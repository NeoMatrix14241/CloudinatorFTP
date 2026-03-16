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
  _full_walk completes  →  build_from_walk(root_path, direct_entries)
                            filters to folders > THRESHOLD, saves JSON

  watchdog event fires  →  update_folder(rel_path, abs_path)
                            re-scans that ONE folder (O(entries), not recursive)
                            adds/updates or removes it if count dropped below threshold

  folder deleted        →  remove_folder(rel_path)
                            prunes that folder and all its children from index

  folder renamed/moved  →  rename_folder(old_rel, new_rel)
                            migrates all affected keys

  save / load           →  persists to cache/file_index.json (atomic write via .tmp)

JSON structure
--------------
{
  "version": 1,
  "threshold": 80,
  "saved_at": <unix timestamp>,
  "dir_count": <number of indexed folders>,
  "dirs": {
    "relative/folder/path": {
      "entry_count": 150,
      "indexed_at": <unix timestamp>,
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
"""

import os
import json
import time
import threading
import tempfile

# Cache dir resolved via paths.py — created by ensure_dirs() at server startup.
from paths import get_cache_dir
CACHE_DIR       = get_cache_dir(create=False)
FILE_INDEX_PATH = os.path.join(CACHE_DIR, 'file_index.json')

# A folder must have MORE THAN this many direct entries to be recorded.
THRESHOLD = 80


# ---------------------------------------------------------------------------
# Internal helper — scan one folder, return sorted entry list
# ---------------------------------------------------------------------------

def _scan_folder_entries(abs_path: str) -> list:
    """
    Scan a single directory and return its direct entries as a list of dicts.
    Hidden entries (name starts with '.') are skipped.
    Entries are sorted: directories first, then files, both case-insensitive alpha.
    Never recurses — only the immediate children of abs_path are returned.
    """
    entries = []
    try:
        with os.scandir(abs_path) as it:
            for entry in it:
                if entry.name.startswith('.'):
                    continue
                try:
                    st = entry.stat()
                    entries.append({
                        'name':     entry.name,
                        'is_dir':   entry.is_dir(),
                        # Directories don't report size (matches list_dir behaviour)
                        'size':     None if entry.is_dir() else st.st_size,
                        'modified': st.st_mtime,
                    })
                except (OSError, IOError):
                    entries.append({
                        'name':     entry.name,
                        'is_dir':   entry.is_dir(),
                        'size':     None,
                        'modified': None,
                    })
    except (OSError, PermissionError):
        return []

    # Directories first, then files — both groups sorted case-insensitively
    entries.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    return entries


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
        self.lock       = threading.Lock()
        self._save_lock = threading.Lock()   # serialises writes to file_index.json
        # rel_path → {entry_count: int, indexed_at: float, entries: list}
        self._dirs: dict = {}

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def load(self) -> bool:
        """
        Load file_index.json into memory.
        Returns True on success, False if the file doesn't exist or is corrupt.
        """
        try:
            if not os.path.exists(FILE_INDEX_PATH):
                print(f"📂 No file index at {FILE_INDEX_PATH} — will rebuild during walk")
                return False

            with open(FILE_INDEX_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)

            dirs = data.get('dirs', {})
            with self.lock:
                self._dirs = dirs

            count = len(dirs)
            total_entries = sum(v.get('entry_count', 0) for v in dirs.values())
            print(
                f"✅ Loaded file index: {count:,} large folder(s) indexed "
                f"({total_entries:,} total entries, threshold={THRESHOLD})"
            )
            return True

        except Exception as e:
            print(f"⚠️  Failed to load file index: {e}")
            with self.lock:
                self._dirs = {}
            return False

    def save(self):
        """
        Atomically write the current index to cache/file_index.json.

        Windows fix: _save_lock serialises concurrent saves so two threads
        never race on the same temp file (WinError 32). tempfile.NamedTemporaryFile
        with delete=False generates a unique random filename (e.g. tmpXXXXXX.json)
        in the same directory, so os.replace() is always a same-filesystem rename.
        """
        with self._save_lock:
            tmp = None
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with self.lock:
                    dirs_snapshot = dict(self._dirs)  # shallow copy under lock

                data = {
                    'version':   1,
                    'threshold': THRESHOLD,
                    'saved_at':  time.time(),
                    'dir_count': len(dirs_snapshot),
                    'dirs':      dirs_snapshot,
                }

                with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8',
                    dir=CACHE_DIR, suffix='.tmp',
                    delete=False,
                ) as tf:
                    json.dump(data, tf)
                    tmp = tf.name

                os.replace(tmp, FILE_INDEX_PATH)

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

        We filter to only folders with len(entries) > THRESHOLD, store them,
        and immediately persist to disk.
        """
        new_dirs = {}
        now = time.time()
        for rel_path, entries in direct_entries.items():
            if len(entries) > THRESHOLD:
                new_dirs[rel_path] = {
                    'entry_count': len(entries),
                    'indexed_at':  now,
                    'entries':     entries,
                }

        with self.lock:
            self._dirs = new_dirs

        added = len(new_dirs)
        if added:
            print(
                f"📋 File index built: {added:,} folder(s) exceed "
                f"threshold of {THRESHOLD} direct entries"
            )
        else:
            print(f"📋 File index built: no folders exceed threshold of {THRESHOLD} entries")

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
        """
        if not os.path.isdir(abs_path):
            # Folder itself was deleted — caller should use remove_folder()
            return

        entries = _scan_folder_entries(abs_path)
        count   = len(entries)

        with self.lock:
            if count > THRESHOLD:
                self._dirs[rel_path] = {
                    'entry_count': count,
                    'indexed_at':  time.time(),
                    'entries':     entries,
                }
            else:
                # Dropped below threshold — evict from index
                removed = self._dirs.pop(rel_path, None)
                if removed is not None:
                    print(
                        f"📋 File index: '{rel_path}' dropped to {count} entries "
                        f"(≤ {THRESHOLD}), removed from index"
                    )

    def remove_folder(self, rel_path: str):
        """
        Remove rel_path and ALL of its descendants from the index.
        Call when a directory is deleted.
        """
        with self.lock:
            keys_to_remove = [
                k for k in self._dirs
                if k == rel_path or k.startswith(rel_path + '/')
            ]
            for k in keys_to_remove:
                del self._dirs[k]

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
        with self.lock:
            keys_to_migrate = [
                k for k in list(self._dirs.keys())
                if k == old_rel or k.startswith(old_rel + '/')
            ]
            now = time.time()
            for old_key in keys_to_migrate:
                suffix  = old_key[len(old_rel):]      # '' or '/child/...'
                new_key = new_rel + suffix
                entry   = self._dirs.pop(old_key)
                entry['indexed_at'] = now
                self._dirs[new_key] = entry

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
        Return the cached entry list for rel_path, or None if not indexed.
        rel_path uses forward slashes; root is '' or '/'.
        """
        rel_path = rel_path.replace('\\', '/').strip('/')
        with self.lock:
            record = self._dirs.get(rel_path)
            return record['entries'] if record else None

    def is_indexed(self, rel_path: str) -> bool:
        """Return True if this folder has a cached entry list."""
        rel_path = rel_path.replace('\\', '/').strip('/')
        with self.lock:
            return rel_path in self._dirs

    def get_indexed_dirs(self) -> list:
        """Return the list of all rel_paths that currently have a cached listing."""
        with self.lock:
            return list(self._dirs.keys())

    def get_stats(self) -> dict:
        """Return summary statistics about the index."""
        with self.lock:
            total_entries = sum(v['entry_count'] for v in self._dirs.values())
            return {
                'indexed_folders': len(self._dirs),
                'threshold':       THRESHOLD,
                'total_entries':   total_entries,
            }

    def clear(self):
        """Wipe the in-memory index (does NOT delete the file)."""
        with self.lock:
            self._dirs.clear()


# ---------------------------------------------------------------------------
# Module-level singleton — imported by file_monitor.py and app.py
# ---------------------------------------------------------------------------

file_index_manager = FileIndexManager()