#!/usr/bin/env python3
"""
File Index — cache/file_index.json
------------------------------------
Tracks the full direct-entry listing for every folder whose direct child
count (files + subdirs you see when you open that folder) exceeds THRESHOLD.

This is distinct from storage_index.json, which stores *recursive* totals.
file_index.json stores the actual rows that would render in the file browser,
so the UI can skip the scandir call entirely for large folders.

Lifecycle
---------
  _full_walk completes  →  build_from_walk(direct_entries)
                            the walk only decides WHICH folders are large;
                            each one is then re-read from disk (never trusts
                            minutes-old walk data), diffed against the previous
                            cache (drift is logged), and installed atomically

  watchdog event fires  →  update_folder(rel_path, abs_path)
                            re-scans that ONE folder (O(entries), not recursive)
                            adds/updates or removes it if count dropped below threshold

  folder deleted        →  remove_folder(rel_path)
                            prunes that folder and all its children from index

  folder renamed/moved  →  rename_folder(old_rel, new_rel)
                            migrates all affected keys

  list_dir() lookup     →  get_entries(rel_path)
                            validates freshness BEFORE returning (see below)

  save / load           →  persists to cache/file_index.json (atomic write via
                            unique temp file + fsync + os.replace)

Validation layers (4.58) — why a stale cache cannot be served for long
----------------------------------------------------------------------
  1. load()         schema version, threshold and every record are checked;
                    anything malformed is dropped. A cache saved with a
                    different THRESHOLD is discarded entirely. Every record
                    loaded from disk is "unverified".
  2. get_entries()  an unverified record is fully re-scanned on its FIRST read
                    (so a restart never serves data from before the restart).
                    After that, one os.stat() of the folder is compared with
                    the folder mtime stored at scan time (dir_mtime_ns); a
                    mismatch (file added/removed/renamed with no watchdog
                    event, e.g. handler skipped it) triggers a re-scan.
  3. build_from_walk() re-reads every large folder, keeps folders the walk
                    missed but that still exist on disk, never wipes on an
                    empty walk, and does not overwrite folders a watchdog
                    handler updated while the walk was running.
  4. verify_all()   on-demand audit: re-scans every indexed folder and reports
                    (and optionally repairs) drift.

  Known limits (cannot be seen from a single os.stat of the folder):
    - A file modified IN PLACE (same name, new size/mtime) does not change the
      folder's mtime. It is corrected by the next walk (15 min) or by a
      watchdog on_modified that calls update_folder().
    - A subfolder's own "modified" value in the parent's listing goes stale
      when something changes deeper inside it; same repair path.

JSON structure
--------------
{
  "version": 2,                 (1 is still accepted on load)
  "threshold": 80,
  "saved_at": <unix timestamp>,
  "dir_count": <number of indexed folders>,
  "dirs": {
    "relative/folder/path": {
      "entry_count": 150,
      "indexed_at": <unix timestamp>,
      "dir_mtime_ns": <st_mtime_ns of the folder, read BEFORE the scan>,
      "entries": [
        {"name": "...", "is_dir": false, "size": 12345,  "modified": <unix ts>},
        {"name": "...", "is_dir": true,  "size": null,   "modified": <unix ts>},
        ...
      ]
    },
    "": {   <-- root folder, empty string key
      ...
    }
  }
}

Notes
-----
- Entries are sorted: directories first, then files, both case-insensitive alpha.
- Hidden entries (name starts with '.') are excluded, matching list_dir() behaviour.
- Folder size is always null (same as list_dir — avoids expensive recursive walk).
- The root folder uses the key "" (empty string), identical to storage_index.json.
- All relative paths use forward slashes with no leading slash.
- The "unverified" state is in-memory only and is never written to the JSON.
"""

import os
import json
import time
import threading
import tempfile

# Cache dir resolved via paths.py — created by ensure_dirs() at server startup.
from paths import get_cache_dir

CACHE_DIR = get_cache_dir(create=False)
FILE_INDEX_PATH = os.path.join(CACHE_DIR, "file_index.json")

# A folder must have MORE THAN this many direct entries to be recorded.
THRESHOLD = 80

SCHEMA_VERSION = 2
# Backoff (seconds) between os.replace() attempts when the target is locked (Windows).
_REPLACE_RETRY_DELAYS = (0, 0.05, 0.1, 0.2, 0.4, 0.8, 1.5)
_ACCEPTED_VERSIONS = (1, 2)

# Temp files written by save() carry this prefix so the stale-temp sweep can
# never touch another module's temp files in the same cache dir.
_TMP_PREFIX = "file_index_"
_TMP_MAX_AGE_SECS = 3600


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _norm(rel_path: str) -> str:
    """Normalise to the key format: forward slashes, no leading/trailing slash."""
    return (rel_path or "").replace("\\", "/").strip("/")


def _abs_path(rel_path: str):
    """
    Absolute path of an index key, or None if ROOT_DIR cannot be resolved.
    Imported lazily so ROOT_DIR is read at call time (config may reassign it).
    """
    try:
        from config import ROOT_DIR
    except Exception:
        return None
    return os.path.join(ROOT_DIR, rel_path) if rel_path else ROOT_DIR


def _scan_checked(abs_path: str):
    """
    Scan a single directory.  Returns (entries, dir_mtime_ns).

    The folder's mtime is read BEFORE the scan: if something changes while we
    are scanning, the stored mtime is older than the folder's real one, so the
    next freshness check mismatches and re-scans (never the other way round).

    Returns (None, None) if the folder cannot be read — callers must treat that
    as "unknown", NOT as "empty folder".
    """
    try:
        mtime_ns = os.stat(abs_path).st_mtime_ns
    except OSError:
        return None, None

    entries = []
    try:
        with os.scandir(abs_path) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                try:
                    st = entry.stat()
                    entries.append(
                        {
                            "name": entry.name,
                            "is_dir": entry.is_dir(),
                            # Directories don't report size (matches list_dir behaviour)
                            "size": None if entry.is_dir() else st.st_size,
                            "modified": st.st_mtime,
                        }
                    )
                except (OSError, IOError):
                    entries.append(
                        {
                            "name": entry.name,
                            "is_dir": entry.is_dir(),
                            "size": None,
                            "modified": None,
                        }
                    )
    except (OSError, PermissionError):
        return None, None

    # Directories first, then files — both groups sorted case-insensitively
    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return entries, mtime_ns


def _scan_folder_entries(abs_path: str) -> list:
    """
    Scan a single directory and return its direct entries as a list of dicts.
    Hidden entries (name starts with '.') are skipped.
    Entries are sorted: directories first, then files, both case-insensitive alpha.
    Never recurses — only the immediate children of abs_path are returned.
    Returns [] if the folder cannot be read (kept for existing callers).
    """
    entries, _ = _scan_checked(abs_path)
    return entries if entries is not None else []


def _diff_entries(old: list, new: list):
    """(added, removed, changed) between two entry lists, compared by name."""

    def keyed(lst):
        return {
            e["name"]: (e.get("is_dir"), e.get("size"), e.get("modified")) for e in lst
        }

    o, n = keyed(old), keyed(new)
    added = len(n.keys() - o.keys())
    removed = len(o.keys() - n.keys())
    changed = sum(1 for k in (n.keys() & o.keys()) if o[k] != n[k])
    return added, removed, changed


def _valid_record(rec) -> bool:
    """Structural sanity check for one record loaded from disk."""
    if not isinstance(rec, dict):
        return False
    entries = rec.get("entries")
    if not isinstance(entries, list) or len(entries) <= THRESHOLD:
        return False
    if rec.get("entry_count") != len(entries):
        return False
    for e in entries:
        if (
            not isinstance(e, dict)
            or not isinstance(e.get("name"), str)
            or not isinstance(e.get("is_dir"), bool)
        ):
            return False
    return True


def _make_record(entries: list, mtime_ns, now: float) -> dict:
    return {
        "entry_count": len(entries),
        "indexed_at": now,
        "dir_mtime_ns": mtime_ns,
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# FileIndexManager
# ---------------------------------------------------------------------------


class FileIndexManager:
    """
    Thread-safe manager for cache/file_index.json.

    All mutation methods acquire self.lock for the in-memory dict, then release
    it before doing any I/O (save is always called outside the lock).
    """

    def __init__(self):
        self.lock = threading.Lock()
        self._save_lock = threading.Lock()  # serialises writes to file_index.json
        self._build_lock = threading.Lock()  # one build_from_walk at a time
        # rel_path → {entry_count: int, indexed_at: float, dir_mtime_ns: int|None, entries: list}
        self._dirs: dict = {}
        # Keys loaded from disk and not yet re-read this session (in-memory only)
        self._unverified: set = set()
        # Mutation tracking so build_from_walk never overwrites a newer live update
        self._mut_seq = 0
        self._building = False
        self._touched_seq: dict = {}
        self._last_build: dict | None = None

    def _touch(self, rel_path: str):
        """Record a mutation of rel_path.  MUST be called with self.lock held."""
        self._mut_seq += 1
        if self._building:
            self._touched_seq[rel_path] = self._mut_seq

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _cleanup_stale_tmp(self):
        """Remove file_index_*.tmp files left behind by a crash mid-save."""
        try:
            cutoff = time.time() - _TMP_MAX_AGE_SECS
            for name in os.listdir(CACHE_DIR):
                if name.startswith(_TMP_PREFIX) and name.endswith(".tmp"):
                    p = os.path.join(CACHE_DIR, name)
                    try:
                        if os.path.getmtime(p) < cutoff:
                            os.remove(p)
                    except OSError:
                        pass
        except OSError:
            pass

    def load(self) -> bool:
        """
        Load file_index.json into memory and validate it.
        Returns True on success, False if the file doesn't exist, is corrupt,
        or was written with a different schema/threshold (all of which mean
        'rebuild during the next walk').

        Every record that survives validation is marked unverified: its first
        get_entries() does a full re-scan, so data from before this restart is
        never served as-is.
        """
        self._cleanup_stale_tmp()
        try:
            if not os.path.exists(FILE_INDEX_PATH):
                print(
                    f"📂 No file index at {FILE_INDEX_PATH} — will rebuild during walk"
                )
                return False

            with open(FILE_INDEX_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise ValueError("top level is not an object")

            if data.get("version") not in _ACCEPTED_VERSIONS:
                print(
                    f"🔄 File index: unsupported version {data.get('version')!r} — "
                    f"discarded, will rebuild during walk"
                )
                self._reset()
                return False

            if data.get("threshold") != THRESHOLD:
                print(
                    f"🔄 File index: saved with threshold {data.get('threshold')!r}, "
                    f"now {THRESHOLD} — discarded, will rebuild during walk"
                )
                self._reset()
                return False

            raw = data.get("dirs")
            if not isinstance(raw, dict):
                raise ValueError("'dirs' missing or not an object")

            dirs = {}
            dropped = 0
            for key, rec in raw.items():
                if isinstance(key, str) and key == _norm(key) and _valid_record(rec):
                    if not isinstance(rec.get("dir_mtime_ns"), int):
                        rec["dir_mtime_ns"] = None
                    dirs[key] = rec
                else:
                    dropped += 1

            with self.lock:
                self._dirs = dirs
                self._unverified = set(dirs)

            total_entries = sum(v["entry_count"] for v in dirs.values())
            msg = (
                f"✅ Loaded file index: {len(dirs):,} large folder(s) indexed "
                f"({total_entries:,} total entries, threshold={THRESHOLD}); "
                f"each is re-verified on first read"
            )
            if dropped:
                msg += f" — dropped {dropped} invalid record(s)"
            print(msg)
            return True

        except Exception as e:
            print(f"⚠️  Failed to load file index: {e} — will rebuild during walk")
            self._reset()
            return False

    def _reset(self):
        with self.lock:
            self._dirs = {}
            self._unverified = set()

    def save(self):
        """
        Atomically write the current index to cache/file_index.json.

        Windows fix: _save_lock serialises concurrent saves so two threads
        never race on the same temp file (WinError 32). tempfile.NamedTemporaryFile
        with delete=False generates a unique random filename in the same
        directory, so os.replace() is always a same-filesystem rename. The temp
        file is flushed and fsync'ed first so a power cut can't leave a
        zero-length file at the final path.
        """
        with self._save_lock:
            tmp = None
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with self.lock:
                    dirs_snapshot = dict(self._dirs)  # shallow copy under lock

                data = {
                    "version": SCHEMA_VERSION,
                    "threshold": THRESHOLD,
                    "saved_at": time.time(),
                    "dir_count": len(dirs_snapshot),
                    "dirs": dirs_snapshot,
                }

                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=CACHE_DIR,
                    prefix=_TMP_PREFIX,
                    suffix=".tmp",
                    delete=False,
                ) as tf:
                    tmp = tf.name
                    json.dump(data, tf)
                    tf.flush()
                    os.fsync(tf.fileno())

                # 4.61: retry the swap. On Windows os.replace() raises
                # PermissionError (WinError 5/32) when another process (antivirus,
                # the Windows indexer, or a second server instance on the same
                # cache dir; since 4.52 the WebDAV subprocess runs no monitor)
                # has file_index.json open at that instant. Same backoff as
                # file_monitor._save_cache() (about 3 s in total).
                last_err = None
                for delay in _REPLACE_RETRY_DELAYS:
                    if delay:
                        time.sleep(delay)
                    try:
                        os.replace(tmp, FILE_INDEX_PATH)
                        last_err = None
                        tmp = None  # consumed by the replace
                        break
                    except PermissionError as e:  # WinError 5 / 32
                        last_err = e
                if last_err is not None:
                    raise last_err

            except Exception as e:
                print(f"⚠️  Failed to save file index: {e}")
                try:
                    if tmp and os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass

    # -----------------------------------------------------------------------
    # Build from full walk
    # -----------------------------------------------------------------------

    def build_from_walk(self, direct_entries: dict):
        """
        Called once after _full_walk completes.

        direct_entries: dict mapping  rel_path → list[entry_dict]
                        for EVERY folder encountered during the walk.
                        Keys use forward slashes; root is ''.

        The walk is only used to decide WHICH folders exceed THRESHOLD.  The
        contents of each of those folders are re-read from disk right now
        (a walk takes minutes, so its data may already be stale), which also
        guarantees the stored format is identical to update_folder()'s.

        Safety rules:
          - an empty walk result never wipes the index;
          - a folder that was indexed but is missing from the walk is kept if
            it still exists and is still large (the walk can be partial);
          - a folder a watchdog handler updated/removed while this ran keeps
            the handler's (newer) state;
          - differences between the previous cache and disk are logged, so you
            can see whether the live (watchdog) updates are keeping up.
        """
        if not direct_entries:
            print("⚠️  File index: walk returned no folders — keeping existing index")
            return

        with self._build_lock:
            walk_big = {
                _norm(k): v for k, v in direct_entries.items() if len(v) > THRESHOLD
            }

            with self.lock:
                start_seq = self._mut_seq
                self._building = True
                self._touched_seq = {}
                old = dict(self._dirs)

            try:
                now = time.time()
                fresh = {}
                for rel in sorted(walk_big.keys() | old.keys()):
                    abs_p = _abs_path(rel)
                    if abs_p is None:
                        # Can't re-read (ROOT_DIR unresolved): fall back to the walk's data
                        if rel in walk_big:
                            fresh[rel] = _make_record(walk_big[rel], None, now)
                        continue
                    entries, mtime_ns = _scan_checked(abs_p)
                    if entries is not None and len(entries) > THRESHOLD:
                        fresh[rel] = _make_record(entries, mtime_ns, now)

                # --- drift report: previous cache vs. what is actually on disk ---
                drifted = added = removed = changed = 0
                for rel, rec in fresh.items():
                    prev = old.get(rel)
                    if prev is None:
                        continue
                    a, r, c = _diff_entries(prev["entries"], rec["entries"])
                    if a or r or c:
                        drifted += 1
                        added += a
                        removed += r
                        changed += c
                new_folders = len(fresh.keys() - old.keys())
                gone_folders = len(old.keys() - fresh.keys())

                # --- install atomically, keeping anything newer than this build ---
                kept_live = set()
                with self.lock:
                    final = {}
                    for rel, rec in fresh.items():
                        if rel in self._touched_seq:
                            cur = self._dirs.get(rel)
                            if cur is not None:
                                final[rel] = cur
                                kept_live.add(rel)
                            continue  # handler removed it meanwhile — don't resurrect
                        final[rel] = rec
                    for rel in self._touched_seq:
                        if rel in self._dirs and rel not in final:
                            final[rel] = self._dirs[rel]
                            kept_live.add(rel)
                    self._dirs = final
                    self._unverified &= kept_live
            finally:
                with self.lock:
                    self._building = False
                    self._touched_seq = {}

            self._last_build = {
                "at": time.time(),
                "indexed_folders": len(final),
                "drifted_folders": drifted,
                "added": added,
                "removed": removed,
                "changed": changed,
            }

            if final:
                print(
                    f"📋 File index built: {len(final):,} folder(s) exceed "
                    f"threshold of {THRESHOLD} direct entries"
                )
            else:
                print(
                    f"📋 File index built: no folders exceed threshold of {THRESHOLD} entries"
                )
            if drifted or new_folders or gone_folders:
                print(
                    f"🔧 File index reconcile: {drifted} folder(s) differed from disk "
                    f"(+{added} / -{removed} entries, ~{changed} size/mtime changes), "
                    f"{new_folders} newly indexed, {gone_folders} dropped"
                )

            self.save()

    # -----------------------------------------------------------------------
    # Incremental updates — called from watchdog handlers
    # -----------------------------------------------------------------------

    def update_folder(self, rel_path: str, abs_path: str):
        """
        Re-scan a single folder and update (or remove) its index entry.

        Call this whenever a file or subdirectory is created, deleted, or moved
        inside rel_path.  The scan is O(direct entries only) — never recursive.

        If the folder no longer exists (was deleted) this is a no-op; use
        remove_folder() explicitly for deletions.
        If the folder's count drops to ≤ THRESHOLD it is removed from the index.
        If the folder cannot be read (scan error) it is also removed from the
        index — list_dir() then serves the live listing, which is always right.
        This does not call save(); the in-memory index is authoritative and the
        file on disk is revalidated on load.
        """
        rel_path = _norm(rel_path)
        if not os.path.isdir(abs_path):
            # Folder itself was deleted — caller should use remove_folder()
            return

        entries, mtime_ns = _scan_checked(abs_path)

        msg = None
        with self.lock:
            self._touch(rel_path)
            self._unverified.discard(rel_path)
            if entries is None:
                if self._dirs.pop(rel_path, None) is not None:
                    msg = (
                        f"📋 File index: '{rel_path}' could not be read — "
                        f"removed from index (live listing will be used)"
                    )
            elif len(entries) > THRESHOLD:
                self._dirs[rel_path] = _make_record(entries, mtime_ns, time.time())
            else:
                # Dropped below threshold — evict from index
                if self._dirs.pop(rel_path, None) is not None:
                    msg = (
                        f"📋 File index: '{rel_path}' dropped to {len(entries)} entries "
                        f"(≤ {THRESHOLD}), removed from index"
                    )
        if msg:
            print(msg)

    def remove_folder(self, rel_path: str):
        """
        Remove rel_path and ALL of its descendants from the index.
        Call when a directory is deleted.
        """
        rel_path = _norm(rel_path)
        with self.lock:
            self._touch(rel_path)
            keys_to_remove = [
                k
                for k in self._dirs
                if k == rel_path or (rel_path and k.startswith(rel_path + "/"))
            ]
            for k in keys_to_remove:
                del self._dirs[k]
                self._unverified.discard(k)
                self._touch(k)

        if keys_to_remove:
            print(
                f"📋 File index: removed {len(keys_to_remove)} folder(s) "
                f"under deleted path '{rel_path}'"
            )

    def rename_folder(self, old_rel: str, new_rel: str):
        """
        Migrate all index keys when a folder is renamed or moved.
        E.g. old_rel='photos/2023', new_rel='photos/archive/2023'
        Updates every key that starts with old_rel (including old_rel itself).
        """
        old_rel = _norm(old_rel)
        new_rel = _norm(new_rel)
        with self.lock:
            keys_to_migrate = [
                k
                for k in list(self._dirs.keys())
                if k == old_rel or (old_rel and k.startswith(old_rel + "/"))
            ]
            now = time.time()
            for old_key in keys_to_migrate:
                suffix = old_key[len(old_rel) :]  # '' or '/child/...'
                new_key = new_rel + suffix
                rec = dict(self._dirs.pop(old_key))  # copy: save() may hold the old one
                rec["indexed_at"] = now
                self._dirs[new_key] = rec
                was_unverified = old_key in self._unverified
                self._unverified.discard(old_key)
                if was_unverified:
                    self._unverified.add(new_key)
                self._touch(old_key)
                self._touch(new_key)

        if keys_to_migrate:
            print(
                f"📋 File index: migrated {len(keys_to_migrate)} key(s) "
                f"'{old_rel}' → '{new_rel}'"
            )

    # -----------------------------------------------------------------------
    # Read API
    # -----------------------------------------------------------------------

    def get_entries(self, rel_path: str) -> list | None:
        """
        Return the entry list for rel_path, or None if the caller should use
        the live listing instead.  rel_path uses forward slashes; root is '' or '/'.

        Freshness is validated before returning:
          - first read of a record loaded from disk → full re-scan;
          - otherwise one os.stat() of the folder; if its mtime differs from
            the one recorded at scan time the folder is re-scanned.
        A folder that vanished, became unreadable, or fell to ≤ THRESHOLD
        returns None.
        """
        rel_path = _norm(rel_path)
        with self.lock:
            record = self._dirs.get(rel_path)
            if record is None:
                return None
            entries = record["entries"]
            stored_mtime = record.get("dir_mtime_ns")
            unverified = rel_path in self._unverified

        abs_p = _abs_path(rel_path)
        if abs_p is None:
            return entries  # cannot verify — behave as before

        if not unverified and stored_mtime is not None:
            try:
                if os.stat(abs_p).st_mtime_ns == stored_mtime:
                    return entries  # fast path: nothing changed
            except OSError:
                with self.lock:
                    self._dirs.pop(rel_path, None)
                    self._unverified.discard(rel_path)
                return None

        # Stale or unverified → re-read this one folder now
        self.update_folder(rel_path, abs_p)
        with self.lock:
            record = self._dirs.get(rel_path)
            return record["entries"] if record else None

    def is_indexed(self, rel_path: str) -> bool:
        """Return True if this folder has a cached entry list (membership only, no disk check)."""
        rel_path = _norm(rel_path)
        with self.lock:
            return rel_path in self._dirs

    def get_indexed_dirs(self) -> list:
        """Return the list of all rel_paths that currently have a cached listing."""
        with self.lock:
            return list(self._dirs.keys())

    def get_stats(self) -> dict:
        """Return summary statistics about the index."""
        with self.lock:
            total_entries = sum(v["entry_count"] for v in self._dirs.values())
            return {
                "indexed_folders": len(self._dirs),
                "threshold": THRESHOLD,
                "total_entries": total_entries,
                "unverified_folders": len(self._unverified),
                "last_build": self._last_build,
            }

    def verify_all(self, repair: bool = False) -> dict:
        """
        On-demand audit: re-scan every indexed folder and compare with the cache.

        Returns {"checked", "drifted", "unreadable", "details": [...]}; each detail is
        {"folder", "added", "removed", "changed"} (entries on disk but not in the cache,
        in the cache but not on disk, and size/mtime differences).  With repair=True the
        drifted folders are refreshed and unreadable ones are removed from the index.
        Cost: one scan per indexed folder (the same work as a walk's large-folder pass).
        Cannot discover a large folder that is not in the index yet — only a walk can.
        """
        with self.lock:
            snapshot = dict(self._dirs)

        report = {"checked": 0, "drifted": 0, "unreadable": 0, "details": []}
        for rel, rec in snapshot.items():
            report["checked"] += 1
            abs_p = _abs_path(rel)
            entries, _ = _scan_checked(abs_p) if abs_p else (None, None)
            if entries is None:
                report["unreadable"] += 1
                if repair:
                    self.remove_folder(rel)
                continue
            a, r, c = _diff_entries(rec["entries"], entries)
            if a or r or c:
                report["drifted"] += 1
                report["details"].append(
                    {"folder": rel, "added": a, "removed": r, "changed": c}
                )
                if repair:
                    self.update_folder(rel, abs_p)
        return report

    def clear(self):
        """Wipe the in-memory index (does NOT delete the file)."""
        with self.lock:
            self._dirs.clear()
            self._unverified.clear()


# ---------------------------------------------------------------------------
# Module-level singleton — imported by file_monitor.py and app.py
# ---------------------------------------------------------------------------

file_index_manager = FileIndexManager()
