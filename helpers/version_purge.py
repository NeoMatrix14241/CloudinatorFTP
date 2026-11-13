"""
helpers/version_purge.py - decide which versions belong to files that no longer exist
=====================================================================================
The decision logic of "free the storage of versions whose file is gone", shared by

  * tools/purge_missing_versions.py (the manual tool: report, apply, undo), and
  * version_engine.py (5.45: the OPTIONAL background purge that runs in the engine's own
    thread, on by default, VERSION_PURGE_MISSING_* in config.py).

A leaf helper (CODING_GUIDELINES section 16.2): standard library only, no import of config,
version_engine, the app or the tools, so both consumers can import it without a cycle. It
touches the SQLite database only through a connection the CALLER passes in, and never starts
a thread, an event loop or an executor: the engine runs `run_pass()` in its own `ve-purge`
thread and hands it the engine's shutdown event and its write-lock.

What "gone" means (unchanged since 5.44.4): a file is gone only when its path does not exist
AND the place it lived in is reachable (drive mounted, tracked folder present, not empty,
readable). "Cannot tell" always means "leave it alone". The automatic purge is stricter still:
see run_pass().
"""

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field

MARK = "purged: file no longer exists (purge_missing_versions.py)"
# Written by the engine's background purge. Both marks are accepted by undo_versions().
MARK_AUTO = "purged: file no longer exists (Version Engine, automatic)"
MARKS = (MARK, MARK_AUTO)
BATCH = 500
PROGRESS_EVERY = 50_000
UNDO_PREFIX = "purge_undo_"
AUTO_UNDO_PREFIX = "purge_undo_auto_"


def scope_dirs_from(cfg):
    """Every folder the engine is (or was) set to track, from a config-like object (the
    config module, or any object with the VERSION_TRACK_* attributes)."""
    dirs = list(getattr(cfg, "VERSION_TRACK_DIRECTORIES", []) or [])
    dirs += list(getattr(cfg, "VERSION_TRACK_ROOTS", []) or [])
    return dirs


# -- the decision logic (moved here unchanged from the tool in 5.45) --------------------


def under(path: str, root: str) -> bool:
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(os.path.abspath(root))
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


class Probe:
    """Decides whether a path that is missing on disk can be called DELETED, or whether the
    place it lived in is itself unavailable (drive or share not mounted, tracked folder
    missing, empty or unreadable). Answers are cached per drive and per tracked folder, so
    250,000 paths cost a handful of probes, not 250,000. The file system calls are
    parameters so the logic can be tested without a real disk."""

    def __init__(
        self,
        scope_dirs,
        isdir=os.path.isdir,
        scandir=os.scandir,
        splitdrive=os.path.splitdrive,
        require_parent=False,
    ):
        # Longest folder first: a file belongs to its most specific tracked folder.
        self._dirs = sorted(
            {os.path.abspath(os.path.expanduser(d)) for d in scope_dirs},
            key=len,
            reverse=True,
        )
        self._isdir = isdir
        self._scandir = scandir
        self._splitdrive = splitdrive
        # The automatic purge (5.45) is stricter than the tool: a missing file that is NOT
        # under any tracked folder is only called gone while its parent folder still exists.
        self._require_parent = require_parent
        self._drive_cache = {}
        self._dir_cache = {}

    def _drive_problem(self, path: str):
        drive, _rest = self._splitdrive(path)
        if not drive:
            return None  # POSIX: there is no drive letter to probe
        if drive not in self._drive_cache:
            self._drive_cache[drive] = self._isdir(drive + os.sep)
        return None if self._drive_cache[drive] else f"{drive} is not reachable"

    def _dir_problem(self, root: str):
        if root not in self._dir_cache:
            problem = None
            if not self._isdir(root):
                problem = f"tracked folder {root} is missing"
            else:
                try:
                    with self._scandir(root) as it:
                        if next(iter(it), None) is None:
                            problem = (
                                f"tracked folder {root} is empty (a share that is "
                                "not mounted looks like this)"
                            )
                except OSError as e:
                    problem = f"tracked folder {root} cannot be read ({e})"
            self._dir_cache[root] = problem
        return self._dir_cache[root]

    def reason(self, path: str):
        """None = the place is fine, so the missing file really is gone. Otherwise a text
        saying why we cannot tell."""
        problem = self._drive_problem(path)
        if problem:
            return problem
        for root in self._dirs:
            if under(path, root):
                return self._dir_problem(root)
        if self._require_parent:
            parent = os.path.dirname(os.path.abspath(path))
            if not self._isdir(parent):
                return f"{parent} is missing and the file is not under a tracked folder"
        return None  # not under any configured tracked folder: judged by the file alone

    def scope_problems(self):
        """Every configured tracked folder (and its drive) that is missing, empty or
        unreadable right now: [] means all of them are fine. The automatic purge does not
        run at all while this list is not empty."""
        found = []
        for root in self._dirs:
            problem = self._drive_problem(root) or self._dir_problem(root)
            if problem:
                found.append(problem)
        return found


# ── the scan ─────────────────────────────────────────────────────────────────


@dataclass
class Scan:
    files_total: int = 0  # every row of the engine's `files` table
    with_completed: int = 0  # rows that have at least one completed version
    present: int = 0  # ...and are on disk
    present_in_scope: int = 0  # ...and the engine's walk still sees them
    gone: int = 0  # ...and are not on disk, place reachable (any age)
    too_recent: int = 0  # gone, but the newest version is younger than --min-age-days
    purge: list = field(default_factory=list)  # gone and old enough: dicts, see _scan
    unsure: list = field(default_factory=list)  # (path, reason): place unavailable
    gone_ext: dict = field(default_factory=dict)  # extension -> gone files (any age)
    gone_newest_min: float | None = None  # oldest "newest version" among the gone files
    gone_newest_max: float | None = (
        None  # youngest "newest version" among the gone files
    )
    scope_files: int | None = (
        None  # files the engine's walk finds now (None = not checked)
    )

    @property
    def purge_ids(self):
        return [i for g in self.purge for i in g["ids"]]

    @property
    def present_out_of_scope(self):
        return self.present - self.present_in_scope


def scan_tracked(
    db_path,
    min_age_days,
    scope_dirs,
    scope_keys=None,
    force=False,
    now=None,
    exists=os.path.lexists,
    probe=None,
    progress=None,
):
    """Classify every file the engine knows. `scope_keys` is the set of normalized keys the
    engine's own walk finds right now (None = skip that cross-check). `force` lets files
    whose place is unavailable count as gone."""
    cutoff = (time.time() if now is None else now) - min_age_days * 86400
    probe = probe or Probe(scope_dirs)
    out = Scan(scope_files=None if scope_keys is None else len(scope_keys))
    db = sqlite3.connect(db_path, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        out.files_total = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        rows = db.execute(
            "SELECT f.file_id, f.path, f.norm_key, MAX(v.created_at) AS newest, "
            "COUNT(*) AS n FROM files f "
            "JOIN versions v ON v.file_id = f.file_id AND v.status='completed' "
            "GROUP BY f.file_id"
        ).fetchall()
        out.with_completed = len(rows)
        candidates = []
        for i, r in enumerate(rows, 1):
            if progress and i % PROGRESS_EVERY == 0:
                progress(i, len(rows))
            if exists(r["path"]):
                out.present += 1
                if scope_keys is not None and r["norm_key"] in scope_keys:
                    out.present_in_scope += 1
                continue
            why = probe.reason(r["path"])
            if why and not force:
                out.unsure.append((r["path"], why))
                continue
            out.gone += 1
            ext = os.path.splitext(r["path"])[1].lower() or "(none)"
            out.gone_ext[ext] = out.gone_ext.get(ext, 0) + 1
            newest = r["newest"]
            if out.gone_newest_min is None or newest < out.gone_newest_min:
                out.gone_newest_min = newest
            if out.gone_newest_max is None or newest > out.gone_newest_max:
                out.gone_newest_max = newest
            if r["newest"] > cutoff:
                out.too_recent += 1
                continue
            candidates.append(r)
        # One pass over the versions instead of one query per file.
        wanted = {r["file_id"]: [] for r in candidates}
        for vid_row in db.execute(
            "SELECT file_id, version_id FROM versions WHERE status='completed'"
        ):
            ids = wanted.get(vid_row["file_id"])
            if ids is not None:
                ids.append(vid_row["version_id"])
        out.purge = [
            {
                "file_id": r["file_id"],
                "path": r["path"],
                "newest": r["newest"],
                "versions": r["n"],
                "ids": wanted[r["file_id"]],
            }
            for r in candidates
        ]
        return out
    finally:
        db.close()


def reclaimable(db_path, purge):
    """({file_id: bytes} that deleting each file's versions would really free, total).
    A chunk counts only if no completed version OUTSIDE the purge set uses it. A chunk shared
    by two purged files shows in both per-file figures but once in the total."""
    db = sqlite3.connect(db_path, timeout=30)
    try:
        db.execute("CREATE TEMP TABLE purge_v(version_id INTEGER PRIMARY KEY)")
        db.executemany(
            "INSERT INTO purge_v VALUES (?)", [(i,) for g in purge for i in g["ids"]]
        )
        # Both queries spell the "no completed version outside the purge set uses this chunk"
        # test out in full: constant SQL only, nothing is interpolated.
        per_file = {
            fid: size or 0
            for fid, size in db.execute(
                "SELECT pv.file_id, SUM(o.size) FROM objects o "
                "JOIN (SELECT DISTINCT vo.sha256, v.file_id FROM version_objects vo "
                "      JOIN versions v ON v.version_id = vo.version_id "
                "      WHERE vo.version_id IN (SELECT version_id FROM purge_v)) pv "
                "  ON pv.sha256 = o.sha256 "
                "WHERE NOT EXISTS (SELECT 1 FROM version_objects x "
                "                  JOIN versions xv ON xv.version_id = x.version_id "
                "                  WHERE x.sha256 = o.sha256 AND xv.status='completed' "
                "                  AND x.version_id NOT IN (SELECT version_id FROM purge_v)) "
                "GROUP BY pv.file_id"
            )
        }
        total = db.execute(
            "SELECT COALESCE(SUM(o.size), 0) FROM objects o "
            "WHERE o.sha256 IN (SELECT sha256 FROM version_objects "
            "                   WHERE version_id IN (SELECT version_id FROM purge_v)) "
            "AND NOT EXISTS (SELECT 1 FROM version_objects x "
            "                JOIN versions xv ON xv.version_id = x.version_id "
            "                WHERE x.sha256 = o.sha256 AND xv.status='completed' "
            "                AND x.version_id NOT IN (SELECT version_id FROM purge_v))"
        ).fetchone()[0]
        return per_file, total
    finally:
        db.close()


def soft_delete(
    conn, ids, batch=BATCH, pause=0.01, progress=None, mark=MARK, should_stop=None
) -> int:
    """status='completed' -> 'deleted' in short write transactions (the engine's own pattern);
    returns how many rows really changed. progress(done, total) is called each time another
    PROGRESS_EVERY versions are done (never for small runs). `mark` is written to the error
    column (MARK for the tool, MARK_AUTO for the engine) so an undo knows what it may revive;
    `should_stop()` is asked before every batch and ends the loop early (what was done stays
    done, every batch is committed on its own)."""
    changed = 0
    for start in range(0, len(ids), batch):
        if should_stop is not None and should_stop():
            break
        chunk = ids[start : start + batch]
        conn.execute("BEGIN IMMEDIATE")
        try:
            for vid in chunk:
                changed += conn.execute(
                    "UPDATE versions SET status='deleted', error=? "
                    "WHERE version_id=? AND status='completed'",
                    (mark, vid),
                ).rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        time.sleep(pause)  # let the engine's own writers in between batches
        done = start + len(chunk)
        if progress and done // PROGRESS_EVERY > start // PROGRESS_EVERY:
            progress(done, len(ids))
    return changed


def undo_versions(conn, ids, engine_object_path, batch=BATCH):
    """Re-activate versions that an earlier --apply deleted, but only while every chunk of the
    version is still stored. Returns (restored, skipped)."""
    restored = skipped = 0
    for start in range(0, len(ids), batch):
        chunk = ids[start : start + batch]
        conn.execute("BEGIN IMMEDIATE")
        try:
            for vid in chunk:
                row = conn.execute(
                    "SELECT status, error FROM versions WHERE version_id=?", (vid,)
                ).fetchone()
                if row is None or row[0] != "deleted" or row[1] not in MARKS:
                    skipped += 1
                    continue
                shas = [
                    r[0]
                    for r in conn.execute(
                        "SELECT sha256 FROM version_objects WHERE version_id=?",
                        (vid,),
                    )
                ]
                intact = bool(shas) and all(
                    conn.execute(
                        "SELECT 1 FROM objects WHERE sha256=?", (s,)
                    ).fetchone()
                    is not None
                    and os.path.exists(engine_object_path(s))
                    for s in shas
                )
                if not intact:
                    skipped += 1  # the chunks were already freed; nothing to bring back
                    continue
                conn.execute(
                    "UPDATE versions SET status='completed', error=NULL "
                    "WHERE version_id=?",
                    (vid,),
                )
                conn.executemany(
                    "UPDATE objects SET orphaned_since=NULL WHERE sha256=?",
                    [(s,) for s in shas],
                )
                restored += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return restored, skipped


def read_undo_file(path):
    """(created, number of versions) of an undo file, or None when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return float(data.get("created", 0)), len(data["version_ids"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def list_undo_files(directory):
    """[(path, created, versions)] of the undo files in `directory`, newest first."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    found = []
    for name in names:
        if name.startswith("purge_undo_") and name.endswith(".json"):
            path = os.path.join(directory, name)
            info = read_undo_file(path)
            if info is not None:
                found.append((path, info[0], info[1]))
    found.sort(key=lambda item: item[1], reverse=True)
    return found


# -- the automatic purge: one bounded, throttled pass ------------------------------------

_SLICE_FILES = 200  # files whose existence is checked between two pauses
_BUSY_FACTOR = 3  # pause = this many times a slice's own duration: at most 25 % busy
_LOCK_POLL = 1.0  # seconds between looks at the stop event while waiting for the lock

_SLICE_SQL = (
    "SELECT f.file_id, f.path FROM files f "
    "JOIN versions v ON v.file_id = f.file_id AND v.status='completed' "
    "WHERE f.file_id > ? GROUP BY f.file_id "
    "HAVING MAX(v.created_at) <= ? ORDER BY f.file_id LIMIT ?"
)


@dataclass
class PassResult:
    status: str = "completed"  # completed | skipped | stopped
    reason: str = ""  # why a pass was skipped
    examined: int = 0  # files whose existence was checked
    present: int = 0  # ...and still exist
    gone: int = 0  # ...and are gone, the place reachable
    unsure: int = 0  # missing, but the place cannot be vouched for: left alone
    unsure_sample: str = ""
    reappeared: int = 0  # gone during the scan, back at the last check before writing
    purged_files: int = 0
    purged_versions: int = 0
    logical_bytes: int = (
        0  # sum of versions.size of the purged versions (not disk bytes)
    )
    undo_file: str = ""
    cursor_start: int = 0
    cursor_next: int = 0
    wrapped: bool = False  # the whole files table has been looked at once
    seconds: float = 0.0


def write_undo_file(directory, version_ids, prefix=AUTO_UNDO_PREFIX, now=None):
    """Write {"created", "version_ids"} atomically (temp file, fsync, rename) and return its
    path. Same format as the tool's undo files, so `purge-versions --undo` reads it."""
    now = time.time() if now is None else now
    name = f"{prefix}{time.strftime('%Y%m%d_%H%M%S', time.localtime(now))}.json"
    path = os.path.join(directory, name)
    n = 0
    while os.path.exists(path):  # two passes in the same second
        n += 1
        path = os.path.join(directory, name[:-5] + f"_{n}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"created": now, "version_ids": list(version_ids)}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


def prune_auto_undo_files(directory, older_than_seconds, now=None):
    """Delete AUTOMATIC undo files older than `older_than_seconds` (the engine passes the GC
    grace period plus a day: after that the chunks are gone and an undo can bring nothing
    back). The tool's own undo files are never touched. Returns how many were removed.
    """
    now = time.time() if now is None else now
    removed = 0
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    for name in names:
        if not (name.startswith(AUTO_UNDO_PREFIX) and name.endswith(".json")):
            continue
        path = os.path.join(directory, name)
        try:
            if now - os.path.getmtime(path) > older_than_seconds:
                os.remove(path)
                removed += 1
        except OSError:
            continue
    return removed


def run_pass(
    conn,
    scope_dirs,
    *,
    min_age_days,
    max_files,
    batch_pause,
    undo_dir,
    stop=None,
    cursor=0,
    now=None,
    exists=os.path.lexists,
    probe_factory=None,
    write_lock=None,
    slice_files=_SLICE_FILES,
    write_batch=BATCH,
):
    """ONE bounded pass of the automatic purge; returns a PassResult. Never raises for a
    "cannot tell"; a database error propagates to the caller (the engine's loop logs it).

    * Looks at no more than `max_files` files, in file_id order, starting after `cursor`
      (the caller stores `cursor_next` between passes; it goes back to 0 when the end of the
      table is reached). Only files whose NEWEST completed version is at least
      `min_age_days` old are looked at at all.
    * The existence checks are spread out: after every slice of `slice_files` files it waits
      three times as long as the slice took (and at least `batch_pause`), by waiting on
      `stop`, so a shutdown ends the wait at once. The disk is busy at most a quarter of the
      time and no write lock is held while checking.
    * Nothing runs while ANY configured tracked folder or its drive is missing, empty or
      unreadable (status "skipped"). A missing file outside every tracked folder counts only
      while its parent folder exists.
    * Before the first write the tracked folders are probed again with a fresh probe (a share
      can vanish during a slow pass) and every candidate is checked once more; a file that
      is back is dropped (`reappeared`).
    * The write phase takes `write_lock` (the engine's maintenance lock, also taken by its
      garbage collector, so the two never overlap), writes the undo file FIRST, then
      soft-deletes in short transactions of BATCH versions with `batch_pause` between them.
    * `stop` (a threading.Event) is honoured at every file and every batch. A pass that is
      stopped does not advance the cursor: the next run looks at the same files again.
    """
    t_start = time.monotonic()
    stop = stop if stop is not None else threading.Event()
    now = time.time() if now is None else now
    make_probe = probe_factory or (lambda: Probe(scope_dirs, require_parent=True))
    res = PassResult(cursor_start=cursor, cursor_next=cursor)

    def done(result):
        result.seconds = time.monotonic() - t_start
        return result

    probe = make_probe()
    problems = probe.scope_problems()
    if problems:
        res.status = "skipped"
        res.reason = "; ".join(problems[:3])
        return done(res)

    cutoff = now - float(min_age_days) * 86400
    candidates = []  # {"file_id", "path", "ids", "size"}
    last_id = cursor
    wrapped = False
    while res.examined < max_files and not stop.is_set():
        slice_started = time.monotonic()
        limit = max(1, min(slice_files, max_files - res.examined))
        rows = conn.execute(_SLICE_SQL, (last_id, cutoff, limit)).fetchall()
        for row in rows:
            if stop.is_set():
                res.status = "stopped"
                return done(res)
            file_id, path = row[0], row[1]
            last_id = file_id
            res.examined += 1
            if exists(path):
                res.present += 1
                continue
            why = probe.reason(path)
            if why:
                res.unsure += 1
                res.unsure_sample = res.unsure_sample or f"{path}: {why}"
                continue
            res.gone += 1
            versions = conn.execute(
                "SELECT version_id, size FROM versions "
                "WHERE file_id=? AND status='completed'",
                (file_id,),
            ).fetchall()
            if versions:
                candidates.append(
                    {
                        "file_id": file_id,
                        "path": path,
                        "ids": [v[0] for v in versions],
                        "size": sum(v[1] or 0 for v in versions),
                    }
                )
        if len(rows) < limit:
            wrapped = True  # fewer rows than asked for: the end of the table
            break
        if res.examined >= max_files:
            break  # the cap is reached: no point in waiting before stopping
        took = time.monotonic() - slice_started
        if stop.wait(max(float(batch_pause), took * _BUSY_FACTOR)):
            res.status = "stopped"
            return done(res)
    if stop.is_set():
        res.status = "stopped"
        return done(res)

    if candidates and not _apply_candidates(
        conn,
        candidates,
        res,
        make_probe,
        exists,
        stop,
        write_lock,
        undo_dir,
        batch_pause,
        write_batch,
    ):
        return done(res)  # skipped or stopped, details are in `res`

    res.cursor_next = 0 if wrapped else last_id
    res.wrapped = wrapped
    return done(res)


def _acquire(lock, stop):
    """Take `lock` (None = nothing to take), looking at `stop` every second. False = the stop
    event came first and the lock is NOT held."""
    if lock is None:
        return True
    while not stop.is_set():
        if lock.acquire(timeout=_LOCK_POLL):
            return True
    return False


def _apply_candidates(
    conn,
    candidates,
    res,
    make_probe,
    exists,
    stop,
    write_lock,
    undo_dir,
    batch_pause,
    write_batch,
):
    """The write phase. True = finished normally; False = skipped or stopped (`res` says
    which and nothing more is to be done)."""
    if not _acquire(write_lock, stop):
        res.status = "stopped"
        return False
    try:
        fresh = make_probe()
        problems = fresh.scope_problems()
        if problems:
            res.status = "skipped"
            res.reason = "during the pass: " + "; ".join(problems[:3])
            return False
        still_gone = []
        for c in candidates:
            if exists(c["path"]) or fresh.reason(c["path"]):
                res.reappeared += 1
            else:
                still_gone.append(c)
        res.gone -= res.reappeared
        if not still_gone:
            return True
        ids = [i for c in still_gone for i in c["ids"]]
        # Undo record FIRST: if anything below fails or the process dies, every version that
        # was touched is listed and `purge-versions --undo <file>` brings it back.
        res.undo_file = write_undo_file(undo_dir, ids)
        changed = soft_delete(
            conn,
            ids,
            batch=write_batch,
            pause=batch_pause,
            mark=MARK_AUTO,
            should_stop=stop.is_set,
        )
        res.purged_versions = changed
        res.purged_files = len(still_gone)
        res.logical_bytes = sum(c["size"] for c in still_gone)
        if stop.is_set() and changed < len(ids):
            res.status = "stopped"
            return False
        return True
    finally:
        if write_lock is not None:
            write_lock.release()
