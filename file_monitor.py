#!/usr/bin/env python3
"""
File System Monitor for CloudinatorFTP
Uses incremental counters + full recursive dir_info index for instant load times at any scale.

Flow:
  First boot  → one full recursive walk → builds file_count/dir_count AND dir_info for
                every folder simultaneously → saves storage_index.json
  Restart     → loads storage_index.json instantly → everything pre-indexed
  File added  → watchdog → update global counters + update dir_info for affected folder
                and all parents up the tree → save JSON → push SSE
  Every 15min → silent reconciliation walk → corrects any drift in counters + dir_info
"""

import os
import sys
import json
import time
import threading
import hashlib
import functools
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Set, Optional, Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from config import ROOT_DIR
from file_index import file_index_manager
from search_index import search_index_manager

# Cache dir resolved via paths.py — created by ensure_dirs() at server startup.
from paths import get_cache_dir


def _lower_current_thread_priority() -> None:
    """On Windows, drop the CALLING thread's OS scheduling priority so it
    never competes evenly with the main thread (which under Hypercorn runs
    the entire asyncio event loop — the only thread pumping every socket
    read/write/accept for the whole app).

    This is a stronger guarantee than time.sleep()-based GIL yielding: it's
    an OS-level scheduling decision, not a cooperative one, so it doesn't
    depend on the walk thread happening to yield at the right moment or on
    Sleep(0)'s weak "only if another thread is already READY" semantics.

    Must only be called from a thread that is NEVER the one running the
    event loop (reconcile threads, to_thread workers — never the main
    thread during start_monitoring()'s synchronous first-boot walk).
    No-op on non-Windows platforms.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        THREAD_PRIORITY_BELOW_NORMAL = -1
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetCurrentThread()
        kernel32.SetThreadPriority(handle, THREAD_PRIORITY_BELOW_NORMAL)
    except Exception as e:
        print(f"⚠️ Could not lower reconcile thread priority: {e}")


CACHE_DIR = get_cache_dir(create=False)
CACHE_FILE = os.path.join(CACHE_DIR, "storage_index.json")

# storage_index.json schema (4.59). v1 = legacy files with no "version"/"root"
# keys (still accepted, but re-verified by a quick reconcile after load).
CACHE_SCHEMA_VERSION = 2
_ACCEPTED_CACHE_VERSIONS = (1, 2)
_TMP_PREFIX = "storage_index."
_TMP_MAX_AGE_SECS = (
    600  # only sweep temp files older than this (other processes save too)
)
# A walk that finds NOTHING while the index holds at least this many files is
# treated as suspect (drive offline / share unmounted) and rejected once.
SUSPECT_EMPTY_MIN_FILES = 50
SUSPECT_RETRY_SECONDS = 60
# Delay before the post-startup verification walk: normal vs. "cache needed repair".
POST_START_RECONCILE_DELAY = 30
POST_START_RECONCILE_DELAY_REPAIRED = 3

# Reconciliation interval
RECONCILE_INTERVAL = 900  # 15 minutes
# How long to suppress watchdog counter updates after a bulk-op reconcile.
# Kept short so the walk starts almost immediately; the walk itself provides
# live progress via SSE rather than waiting for a silent timer to expire.
SETTLE_DELAY = 0.5  # seconds  (was 2.0)
# Burst detection: if this many on_created events arrive within BURST_WINDOW seconds
# the handler auto-arms the settle (same as an explicit bulk_copy reconcile does).
# Raised so small copies (< 200 files) still get individual watchdog increments
# rather than immediately jumping to a full walk.
BURST_THRESHOLD = 200  # events  (was 50)
BURST_WINDOW = 5.0  # seconds (was 3.0)

# Walk progress: log a line every N files during a reconcile walk (no SSE emitted).
# SSE during the walk caused the UI to oscillate between partial counts.
WALK_PROGRESS_INTERVAL = 1000  # print a log line every N files
WALK_PROGRESS_MIN_INTERVAL = 1.0  # (unused — kept for reference only)

# How often (in files) the walk thread voluntarily yields via time.sleep().
# Under Hypercorn there's a single event-loop thread, so a tight stat()-in-
# a-loop walk can starve it of GIL time (esp. on Windows). Use a REAL sleep
# duration, not time.sleep(0): on Windows, time.sleep(0) maps to Win32
# Sleep(0), which only yields to other threads that are already in the
# READY state — it does not force an OS timer-based context switch the way
# POSIX sched_yield() does, so it can return near-instantly without ever
# actually handing control to the event loop thread. A small nonzero sleep
# forces a real handoff. 50 files keeps this frequent even inside one huge
# folder; 1ms per handoff is cheap next to the walk's own syscall cost.
WALK_YIELD_INTERVAL = 50
WALK_YIELD_SECONDS = 0.001

# After a reconcile walk finishes, the OS watchdog event queue may still hold
# thousands of on_created events for files the walk already counted.  Once those
# events see _pending_reconcile=False and the new epoch they will all increment
# _file_count for files the walk already tallied → "infinite drift".
# Re-arming suppression for POST_WALK_DRAIN seconds flushes the OS queue without
# triggering another full walk.
POST_WALK_DRAIN = 6.0  # seconds — enough for OS to drain ~100k queued events

# 4.63: slow-path timing logs. A watchdog batch (first event -> SSE push) or a
# single handler call slower than this is logged with a ⏱️ line so a slow
# "I deleted files in Explorer, the stats took 5-10 s" report shows WHERE the
# time went (handler work, folder re-index, SSE push, JSON save).
SLOW_BATCH_LOG_SECS = 1.0
SLOW_HANDLER_LOG_SECS = 1.0

# 4.64: per-folder correction after watchdog events (see _correct_folders).
# More changed folders than this in one debounce batch = a bulk operation; the
# settle walk handles it instead.
MAX_CORRECT_FOLDERS = 400
# Max folder paths put into one SSE message (the browser refreshes anyway when
# the list was truncated).
MAX_CHANGED_DIRS_SENT = 300


@dataclass
class StorageSnapshot:
    """Lightweight snapshot — kept identical to original for app.py compatibility"""

    file_count: int
    dir_count: int
    total_size: int
    last_modified: float
    checksum: str
    timestamp: float


def _rel(abs_path: str, root: str) -> str:
    """Convert absolute path to relative path key (forward slashes, no leading slash)"""
    rel = os.path.relpath(abs_path, root)
    if rel == ".":
        return ""
    return rel.replace("\\", "/")


def _parents(rel_path: str):
    """
    Yield all parent relative paths from closest to root.
    e.g. 'a/b/c' → ['a/b', 'a', '']

    4.62: the root itself ('') has NO parents. It used to yield '' as well, so
    every caller that first updated the record for `rel_path` and then looped
    over _parents(rel_path) counted anything directly inside the root twice in
    the root record (walk, on_created, on_deleted).
    """
    if not rel_path:
        return
    parts = rel_path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        yield "/".join(parts[:i])
    yield ""  # root always gets updated


def _norm_root(path) -> str:
    """Comparable form of a root path (case-folded on Windows, no trailing slash)."""
    try:
        return os.path.normcase(os.path.abspath(str(path)))
    except Exception:
        return str(path)


def _nonneg_int(value):
    """int(value) if it is a sane non-negative number, else None."""
    if isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if n >= 0 else None


def _is_junction(path: str) -> bool:
    """True for an NTFS junction / mount point. os.walk() does not recognise
    these as links, so it descends into them: an access-denied legacy junction
    (e.g. 'Documents\\My Music') shows up as an unreadable folder on every walk, and
    an accessible one is counted twice (once here, once at its real location)."""
    try:
        fn = getattr(os.path, "isjunction", None)  # Python 3.12+
        if fn is not None:
            return bool(fn(path))
        return getattr(os.lstat(path), "st_reparse_tag", 0) == 0xA0000003
    except OSError:
        return False


def _scan_direct(abs_dir: str):
    """Direct contents of one folder under the SAME rules as _full_walk:
    hidden files are not counted, hidden sub-FOLDERS are visited but not counted
    as folders, '.chunks' and junctions are skipped, unreadable files are skipped.
    Returns (file_count, total_size, latest_mtime, subdir_names) or None if the
    folder cannot be read."""
    files = size = 0
    latest = 0.0
    subdirs = set()
    try:
        with os.scandir(abs_dir) as it:
            for e in it:
                name = e.name
                try:
                    is_dir = e.is_dir()
                except OSError:
                    is_dir = False
                if is_dir:
                    if name == ".chunks" or _is_junction(e.path):
                        continue
                    subdirs.add(name)
                    continue
                if name.startswith("."):
                    continue
                try:
                    st = e.stat()
                except OSError:
                    continue
                files += 1
                size += st.st_size
                if st.st_mtime > latest:
                    latest = st.st_mtime
    except OSError:
        return None
    return files, size, latest, subdirs


def _walk_subtree(root_str: str, abs_root: str):
    """Walk a whole sub-tree under the same rules as _full_walk. Returns
    (dir_info_for_the_subtree, latest_mtime); the sub-tree root's own record
    (key _rel(abs_root)) holds the recursive totals."""
    rel_root = _rel(abs_root, root_str)
    zero = lambda: {"file_count": 0, "dir_count": 0, "total_size": 0}
    info = {rel_root: zero()}
    latest = 0.0
    for root, dirs, files in os.walk(abs_root, topdown=True, onerror=lambda e: None):
        if ".chunks" in dirs:
            dirs.remove(".chunks")
        for d in list(dirs):
            if _is_junction(os.path.join(root, d)):
                dirs.remove(d)
        rr = _rel(root, root_str)
        if rr not in info:
            info[rr] = zero()
        for d in dirs:
            if d.startswith("."):
                continue
            sub = (rr + "/" + d) if rr else d
            if sub not in info:
                info[sub] = zero()
            info[rr]["dir_count"] += 1
            for anc in _parents(rr):
                if anc in info:
                    info[anc]["dir_count"] += 1
        for fname in files:
            if fname.startswith("."):
                continue
            try:
                st = os.stat(os.path.join(root, fname))
            except OSError:
                continue
            info[rr]["file_count"] += 1
            info[rr]["total_size"] += st.st_size
            for anc in _parents(rr):
                if anc in info:
                    info[anc]["file_count"] += 1
                    info[anc]["total_size"] += st.st_size
            if st.st_mtime > latest:
                latest = st.st_mtime
    return info, latest


def _timed_handler(fn):
    """4.63: time each watchdog handler call, add it to the monitor's per-batch
    total and log the call when it is slower than SLOW_HANDLER_LOG_SECS."""

    @functools.wraps(fn)
    def wrapper(self, event):
        t0 = time.perf_counter()
        try:
            return fn(self, event)
        finally:
            dt = time.perf_counter() - t0
            try:
                self.monitor._note_handler_time(dt)
                if dt >= SLOW_HANDLER_LOG_SECS:
                    print(
                        f"⏱️ Slow watchdog handler {fn.__name__}: {dt:.2f}s "
                        f"({os.path.basename(getattr(event, 'src_path', ''))})"
                    )
            except Exception:
                pass

    return wrapper


class InstantFileEventHandler(FileSystemEventHandler):
    """
    Handles watchdog events.
    Updates in-memory counters AND dir_info cache directly — no walking.
    """

    def __init__(self, monitor):
        self.monitor = monitor
        self.debounce_timer = None
        self.debounce_delay = 0.5  # Fire SSE 0.5s after last change (was 2.0s)
        self.debounce_lock = threading.Lock()
        self._first_change_time = None  # For max_wait enforcement
        # Burst detection: if more than BURST_THRESHOLD on_created events arrive
        # within BURST_WINDOW seconds, treat it as a bulk op and arm the settle.
        self._burst_count = 0
        self._burst_window_start = 0.0
        self._burst_armed = False  # True once settle has been armed for this burst

    def _check_burst(self):
        """
        Called from on_created for every non-suppressed file event.
        Tracks event rate; if it exceeds BURST_THRESHOLD in BURST_WINDOW seconds,
        arms the monitor settle so the counters are corrected by a ground-truth walk
        once the storm quiets — instead of trusting incremental adds that may overcount.
        Re-arms on every new burst so back-to-back large copies are each handled.
        """
        now = time.time()
        if now - self._burst_window_start > BURST_WINDOW:
            # Start a fresh window
            self._burst_window_start = now
            self._burst_count = 0
            self._burst_armed = False

        self._burst_count += 1

        if self._burst_count >= BURST_THRESHOLD and not self._burst_armed:
            self._burst_armed = True
            print(
                f"⚡ Burst detected ({self._burst_count} events in "
                f"{now - self._burst_window_start:.1f}s) — arming settle reconcile"
            )
            self.monitor.set_pending_reconcile()

    def _touch(self, *abs_paths):
        """4.64: every event marks the folder whose direct entries changed as
        dirty - EVEN while a walk is pending or the event is otherwise skipped.
        The browser is told which folders changed, and _correct_folders() later
        recomputes each one from disk, so skipped or late events cannot leave the
        counters wrong."""
        root = str(self.monitor.root_path)
        for p in abs_paths:
            parent = os.path.dirname(p)
            self.monitor.mark_folder_dirty(_rel(parent, root), parent)

    def _schedule_notify(self):
        self.monitor._note_event()
        # Standard debounce: reset timer on every event.
        # BUT cap at max_wait=3s so continuous uploads still fire SSE periodically.
        with self.debounce_lock:
            now = time.time()
            if self._first_change_time is None:
                self._first_change_time = now

            time_since_first = now - self._first_change_time
            fire_now = time_since_first >= 3.0  # Max wait: force notify every 3s

            if self.debounce_timer:
                self.debounce_timer.cancel()

            if fire_now:
                self._first_change_time = None
                self.debounce_timer = threading.Timer(0, self.monitor._notify_and_save)
            else:
                self.debounce_timer = threading.Timer(
                    self.debounce_delay, self.monitor._notify_and_save
                )
            self.debounce_timer.start()

    @_timed_handler
    def on_created(self, event):
        # Skip hidden files/dirs (matches _full_walk) and anything inside .chunks
        _name = os.path.basename(event.src_path)
        if _name.startswith(".") or ".chunks" in event.src_path:
            return

        self._touch(event.src_path)  # 4.64: always mark, even if skipped below

        # Snapshot epoch BEFORE any path work (outside the lock).
        # If _reconcile() runs while this event is in flight it will bump the epoch;
        # we detect that below and skip the counter increment to avoid double-counting.
        epoch = self.monitor._reconcile_epoch

        # If a settle reconcile is pending, skip counter updates — the event storm
        # from a bulk op is still draining and would overcount.  Still schedule notify
        # so the debounce fires and eventually triggers the settle reconcile.
        if self.monitor._pending_reconcile:
            self._schedule_notify()
            return

        src_rel = _rel(event.src_path, str(self.monitor.root_path))

        with self.monitor.lock:
            if self.monitor._reconcile_epoch != epoch:
                # A reconcile ran between our path read and now — it already counted
                # this file via _full_walk.  Skip the increment.
                return
            if event.is_directory:
                # New folder — add empty entry, update parent dir counts
                self.monitor._dir_count += 1
                if src_rel not in self.monitor._dir_info:
                    self.monitor._dir_info[src_rel] = {
                        "file_count": 0,
                        "dir_count": 0,
                        "total_size": 0,
                    }
                # Update parent dir_count
                for parent in _parents(src_rel):
                    if parent in self.monitor._dir_info:
                        self.monitor._dir_info[parent]["dir_count"] += 1
            else:
                # New file — update global file count + size in all parents
                self.monitor._file_count += 1
                file_size = 0
                try:
                    file_size = os.path.getsize(event.src_path)
                    self.monitor._total_size += file_size
                except OSError:
                    pass

                # Update dir_info for immediate parent AND all ancestors
                parent_rel = _rel(
                    os.path.dirname(event.src_path), str(self.monitor.root_path)
                )
                if parent_rel in self.monitor._dir_info:
                    self.monitor._dir_info[parent_rel]["file_count"] += 1
                    self.monitor._dir_info[parent_rel]["total_size"] += file_size
                for ancestor in _parents(parent_rel):
                    if ancestor in self.monitor._dir_info:
                        self.monitor._dir_info[ancestor]["file_count"] += 1
                        self.monitor._dir_info[ancestor]["total_size"] += file_size

        # --- file index: re-scan the parent folder (outside monitor lock) ---
        _parent_abs = os.path.dirname(event.src_path)
        _parent_rel = _rel(_parent_abs, str(self.monitor.root_path))
        self.monitor.mark_folder_dirty(_parent_rel, _parent_abs)
        # If a new subdirectory was created, seed it in the index (starts empty,
        # update_folder will skip it; it will be added once it exceeds threshold)
        if event.is_directory:
            self.monitor.mark_folder_dirty(src_rel, event.src_path)

        # --- search index: add the new entry ---
        _entry_name = os.path.basename(event.src_path)
        search_index_manager.add(src_rel, _entry_name, event.is_directory)

        # Auto-arm settle if this looks like a bulk copy from outside the web UI
        if not event.is_directory:
            self._check_burst()

        self._schedule_notify()

    @_timed_handler
    def on_deleted(self, event):
        # Skip hidden files/dirs (matches _full_walk) and anything inside .chunks
        _name = os.path.basename(event.src_path)
        if _name.startswith(".") or ".chunks" in event.src_path:
            return

        self._touch(event.src_path)  # 4.64: always mark, even if skipped below
        epoch = self.monitor._reconcile_epoch

        if self.monitor._pending_reconcile:
            self._schedule_notify()
            return

        src_rel = _rel(event.src_path, str(self.monitor.root_path))

        with self.monitor.lock:
            if self.monitor._reconcile_epoch != epoch:
                return  # reconcile already corrected the counters
            if event.is_directory:
                # Remove folder and all children from dir_info
                removed_size = 0
                removed_dirs = 0
                removed_files = 0
                keys_to_remove = [
                    k
                    for k in self.monitor._dir_info
                    if k == src_rel or k.startswith(src_rel + "/")
                ]
                for k in keys_to_remove:
                    entry = self.monitor._dir_info.pop(k, {})
                    if k == src_rel:
                        removed_size = entry.get("total_size", 0)
                        removed_dirs = 1 + entry.get("dir_count", 0)
                        removed_files = entry.get("file_count", 0)

                self.monitor._dir_count = max(0, self.monitor._dir_count - removed_dirs)
                self.monitor._file_count = max(
                    0, self.monitor._file_count - removed_files
                )
                self.monitor._total_size = max(
                    0, self.monitor._total_size - removed_size
                )

                # Bubble all three counts up to all ancestors
                for parent in _parents(src_rel):
                    if parent in self.monitor._dir_info:
                        self.monitor._dir_info[parent]["dir_count"] = max(
                            0,
                            self.monitor._dir_info[parent]["dir_count"] - removed_dirs,
                        )
                        self.monitor._dir_info[parent]["file_count"] = max(
                            0,
                            self.monitor._dir_info[parent]["file_count"]
                            - removed_files,
                        )
                        self.monitor._dir_info[parent]["total_size"] = max(
                            0,
                            self.monitor._dir_info[parent]["total_size"] - removed_size,
                        )
            else:
                # Deleted file — bubble file_count down from all ancestors
                self.monitor._file_count = max(0, self.monitor._file_count - 1)

                parent_rel = _rel(
                    os.path.dirname(event.src_path), str(self.monitor.root_path)
                )
                if parent_rel in self.monitor._dir_info:
                    self.monitor._dir_info[parent_rel]["file_count"] = max(
                        0, self.monitor._dir_info[parent_rel]["file_count"] - 1
                    )
                for ancestor in _parents(parent_rel):
                    if ancestor in self.monitor._dir_info:
                        self.monitor._dir_info[ancestor]["file_count"] = max(
                            0, self.monitor._dir_info[ancestor]["file_count"] - 1
                        )
                # Size drift corrected by 15min reconcile

        # --- file index: remove deleted dir (and children) or re-scan parent ---
        if event.is_directory:
            file_index_manager.remove_folder(src_rel)
            # Parent folder lost one entry — re-scan it
            _parent_abs = os.path.dirname(event.src_path)
            _parent_rel = _rel(_parent_abs, str(self.monitor.root_path))
            self.monitor.mark_folder_dirty(_parent_rel, _parent_abs)
        else:
            _parent_abs = os.path.dirname(event.src_path)
            _parent_rel = _rel(_parent_abs, str(self.monitor.root_path))
            self.monitor.mark_folder_dirty(_parent_rel, _parent_abs)

        # --- search index: remove the deleted entry ---
        if event.is_directory:
            search_index_manager.remove_tree(src_rel)
        else:
            search_index_manager.remove(src_rel)

        self._schedule_notify()

    @_timed_handler
    def on_moved(self, event):
        # Skip hidden files/dirs (matches _full_walk) and pure .chunks-to-.chunks moves
        _src_name = os.path.basename(event.src_path)
        _dst_name = os.path.basename(event.dest_path)
        if (_src_name.startswith(".") and _dst_name.startswith(".")) or (
            ".chunks" in event.src_path and ".chunks" in event.dest_path
        ):
            return

        self._touch(event.src_path, event.dest_path)  # 4.64: always mark both parents
        if event.is_directory:
            self.monitor.remap_dirty(
                _rel(event.src_path, str(self.monitor.root_path)),
                _rel(event.dest_path, str(self.monitor.root_path)),
            )
        epoch = self.monitor._reconcile_epoch

        if self.monitor._pending_reconcile:
            self._schedule_notify()
            return

        src_rel = _rel(event.src_path, str(self.monitor.root_path))
        dest_rel = _rel(event.dest_path, str(self.monitor.root_path))

        with self.monitor.lock:
            if self.monitor._reconcile_epoch != epoch:
                return  # reconcile already corrected the counters
            if event.is_directory:
                # Rename/move folder — migrate all dir_info keys
                keys_to_migrate = [
                    k
                    for k in list(self.monitor._dir_info.keys())
                    if k == src_rel or k.startswith(src_rel + "/")
                ]
                for old_key in keys_to_migrate:
                    new_key = dest_rel + old_key[len(src_rel) :]
                    self.monitor._dir_info[new_key] = self.monitor._dir_info.pop(
                        old_key
                    )

                # 4.64: transfer the moved folder's TOTALS (files, size, folders
                # inside it, plus the folder itself unless hidden) from the old
                # ancestor chain to the new one. Before, only dir_count moved by 1,
                # so every ancestor's file count / size stayed wrong until a walk.
                moved = self.monitor._dir_info.get(dest_rel)
                if moved is not None:
                    mf, ms, md = (
                        moved["file_count"],
                        moved["total_size"],
                        moved["dir_count"],
                    )
                    inc_src = 0 if _src_name.startswith(".") else 1
                    inc_dst = 0 if _dst_name.startswith(".") else 1
                    for parent in _parents(src_rel):
                        a = self.monitor._dir_info.get(parent)
                        if a is not None:
                            a["file_count"] = max(0, a["file_count"] - mf)
                            a["total_size"] = max(0, a["total_size"] - ms)
                            a["dir_count"] = max(0, a["dir_count"] - (inc_src + md))
                    for parent in _parents(dest_rel):
                        a = self.monitor._dir_info.get(parent)
                        if a is not None:
                            a["file_count"] += mf
                            a["total_size"] += ms
                            a["dir_count"] += inc_dst + md
            else:
                # File renamed/moved
                src_parent = _rel(
                    os.path.dirname(event.src_path), str(self.monitor.root_path)
                )
                dest_parent = _rel(
                    os.path.dirname(event.dest_path), str(self.monitor.root_path)
                )

                if src_parent != dest_parent:
                    # Moving to a different folder — transfer file count between parents
                    try:
                        file_size = os.path.getsize(event.dest_path)
                    except OSError:
                        file_size = 0

                    # 4.64: the whole ancestor chain of both parents, not only the
                    # two immediate parents (a file moved between sub-folders used
                    # to leave every higher ancestor wrong until the next walk).
                    for k in [src_parent, *_parents(src_parent)]:
                        a = self.monitor._dir_info.get(k)
                        if a is not None:
                            a["file_count"] = max(0, a["file_count"] - 1)
                            a["total_size"] = max(0, a["total_size"] - file_size)
                    for k in [dest_parent, *_parents(dest_parent)]:
                        a = self.monitor._dir_info.get(k)
                        if a is not None:
                            a["file_count"] += 1
                            a["total_size"] += file_size

        # --- file index: rename dir keys or update both parent folders ---
        if event.is_directory:
            file_index_manager.rename_folder(src_rel, dest_rel)
            # Both old and new parent folders changed their direct entry list
            _src_parent_abs = os.path.dirname(event.src_path)
            _dest_parent_abs = os.path.dirname(event.dest_path)
            _src_parent_rel = _rel(_src_parent_abs, str(self.monitor.root_path))
            _dest_parent_rel = _rel(_dest_parent_abs, str(self.monitor.root_path))
            self.monitor.mark_folder_dirty(_src_parent_rel, _src_parent_abs)
            if _src_parent_rel != _dest_parent_rel:
                self.monitor.mark_folder_dirty(_dest_parent_rel, _dest_parent_abs)
        else:
            _src_parent_abs = os.path.dirname(event.src_path)
            _dest_parent_abs = os.path.dirname(event.dest_path)
            _src_parent_rel = _rel(_src_parent_abs, str(self.monitor.root_path))
            _dest_parent_rel = _rel(_dest_parent_abs, str(self.monitor.root_path))
            self.monitor.mark_folder_dirty(_src_parent_rel, _src_parent_abs)
            if _src_parent_rel != _dest_parent_rel:
                self.monitor.mark_folder_dirty(_dest_parent_rel, _dest_parent_abs)

        # --- search index: rename the moved entry or tree ---
        _dest_name = os.path.basename(event.dest_path)
        if event.is_directory:
            search_index_manager.rename_tree(src_rel, dest_rel)
        else:
            search_index_manager.remove(src_rel)
            search_index_manager.add(dest_rel, _dest_name, False)

        self._schedule_notify()

    def on_modified(self, event):
        # File content changed (size/mtime). 4.64: mark the parent folder dirty so
        # the size is corrected within seconds instead of at the next 15-min walk.
        if ".chunks" in event.src_path or event.is_directory:
            return
        if not os.path.basename(event.src_path).startswith("."):
            self._touch(event.src_path)
        self._schedule_notify()


class FileSystemMonitor:
    """
    Full recursive index-based file system monitor.

    - Startup: loads cache instantly (all dir_info pre-indexed) OR full walk if missing
    - Runtime: watchdog updates global counters + dir_info for affected paths only
    - Every 15min: silent reconcile corrects any drift
    - get_dir_info(path): instant dict lookup, never walks
    """

    def __init__(self, root_path: str = ROOT_DIR):
        self.root_path = Path(root_path)
        self.monitoring = False
        self.reconcile_thread: Optional[threading.Thread] = None
        self.change_callbacks: Set[Callable] = set()
        self.lock = threading.Lock()
        self._save_lock = threading.Lock()  # serialises writes to storage_index.json
        # Bumped at the START of every _reconcile() run.  Watchdog handlers snapshot
        # this before doing path work; if it changed by the time they acquire the lock
        # the reconcile already counted those files — they skip the increment.
        self._reconcile_epoch: int = 0
        # Hard-timer settle: after a bulk-op reconcile, counter updates are suppressed
        # for SETTLE_DELAY seconds, then a ground-truth reconcile fires unconditionally.
        # Using a hard timer (not debounce) so active uploads can't delay it forever.
        self._pending_reconcile: bool = False
        self._settle_timer: Optional[threading.Timer] = None
        self._settle_lock = threading.Lock()

        # Global counters
        self._file_count: int = 0
        self._dir_count: int = 0
        self._total_size: int = 0
        self._last_modified: float = 0.0

        # Full dir index: rel_path → {file_count, dir_count, total_size}
        # '' (empty string) = root
        self._dir_info: Dict[str, dict] = {}

        self.last_snapshot: Optional[StorageSnapshot] = None
        self.observer = None
        self.event_handler = None

        # 4.59 cache-validation state
        # 4.62: exactly one reconcile walk at a time. A request that was made
        # BEFORE the last applied walk started is satisfied by that walk.
        # 4.63: folders whose file-index record must be re-scanned. The handlers only
        # MARK a parent dirty; one re-scan per folder happens in _notify_and_save
        # (deleting 500 files in a 20k-entry folder used to do 500 full scans).
        # get_entries() re-validates by folder mtime on every read, so a read that
        # arrives before the flush still gets a fresh listing.
        self._dirty_lock = threading.Lock()
        self._dirty_folders: Dict[str, str] = {}
        self._batch_first_ts: Optional[float] = None
        self._batch_events: int = 0
        self._batch_handler_secs: float = 0.0
        self.activity_callbacks: list = []  # 4.64: fn(changed_dirs, truncated)
        self._last_junction_count: int = (
            -1
        )  # log skipped junctions only when it changes
        self._walk_lock = threading.Lock()
        self._walk_started_at: float = 0.0  # time.monotonic() of the last walk start
        self._walk_applied: bool = False  # that walk's result was applied
        # 4.62: generation of the post-walk drain timer; a stale timer must not
        # lift the suppression flag while a newer walk/settle owns it.
        self._drain_gen: int = 0
        self._load_repaired: int = 0  # records fixed/dropped by _load_cache()
        self._suspect_walks: int = 0  # consecutive walks rejected as suspect-empty
        self._retry_timer: Optional[threading.Timer] = None

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def add_change_callback(self, callback: Callable):
        with self.lock:
            self.change_callbacks.add(callback)

    def remove_change_callback(self, callback: Callable):
        with self.lock:
            self.change_callbacks.discard(callback)

    def _notify_changes(
        self,
        old_snapshot: StorageSnapshot,
        new_snapshot: StorageSnapshot,
        reconcile_complete: bool = False,
        walk_progress: bool = False,
        changed_dirs=None,
        changed_dirs_truncated: bool = False,
    ):
        with self.lock:
            callbacks = list(self.change_callbacks)
        extra = {}
        if changed_dirs is not None:
            extra = {
                "changed_dirs": changed_dirs,
                "changed_dirs_truncated": changed_dirs_truncated,
            }
        for cb in callbacks:
            try:
                try:
                    cb(
                        old_snapshot,
                        new_snapshot,
                        reconcile_complete=reconcile_complete,
                        walk_progress=walk_progress,
                        **extra,
                    )
                except TypeError:
                    try:
                        cb(
                            old_snapshot,
                            new_snapshot,
                            reconcile_complete=reconcile_complete,
                            walk_progress=walk_progress,
                        )
                    except TypeError:
                        cb(old_snapshot, new_snapshot)
            except Exception as e:
                print(f"❌ Error in change callback: {e}")

    def add_activity_callback(self, cb):
        """4.64: cb(changed_dirs: list[str], truncated: bool) is called when files
        changed but no counters are pushed (walk/drain in progress)."""
        with self.lock:
            self.activity_callbacks.append(cb)

    def _notify_activity(self, changed_dirs, truncated):
        with self.lock:
            callbacks = list(self.activity_callbacks)
        for cb in callbacks:
            try:
                cb(changed_dirs, truncated)
            except Exception as e:
                print(f"❌ Error in activity callback: {e}")

    # ------------------------------------------------------------------
    # Cache load / save
    # ------------------------------------------------------------------

    def _cleanup_stale_tmp(self):
        """Remove storage_index.*.tmp files left behind by a crash mid-save."""
        try:
            cutoff = time.time() - _TMP_MAX_AGE_SECS
            for name in os.listdir(CACHE_DIR):
                if name.startswith(_TMP_PREFIX) and name.endswith(".tmp"):
                    p = os.path.join(CACHE_DIR, name)
                    try:
                        if os.path.getmtime(p) < cutoff:
                            os.remove(p)
                            print(f"🧹 Removed stale temp file: {name}")
                    except OSError:
                        pass
        except OSError:
            pass

    def _load_cache(self) -> bool:
        """Load and VALIDATE storage_index.json.

        Nothing is assigned to self until the whole file has passed validation,
        so a rejected file can never leave half-loaded counters behind.
        Discarded outright (-> first-boot walk): not a JSON object, unknown
        schema version, saved for a different root, bad counters, no dir_info.
        Repaired in place (-> quick verification walk): individual dir_info
        records with missing/negative/non-numeric fields or a malformed key,
        and a missing root record.
        """
        self._load_repaired = 0
        self._cleanup_stale_tmp()
        try:
            if not os.path.exists(CACHE_FILE):
                print(f"📂 No cache found at {CACHE_FILE} — will do initial walk")
                return False

            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                print("⚠️ Cache is not a JSON object — discarded, will do initial walk")
                return False

            version = data.get("version", 1)
            if version not in _ACCEPTED_CACHE_VERSIONS:
                print(
                    f"⚠️ Cache schema version {version!r} not supported — "
                    f"discarded, will do initial walk"
                )
                return False

            saved_root = data.get("root")
            if saved_root is not None and _norm_root(saved_root) != _norm_root(
                self.root_path
            ):
                print(
                    f"⚠️ Cache was built for a different root ({saved_root}) — "
                    f"discarded, will do initial walk"
                )
                return False

            file_count = _nonneg_int(data.get("file_count", 0))
            dir_count = _nonneg_int(data.get("dir_count", 0))
            total_size = _nonneg_int(data.get("total_size", 0))
            try:
                last_modified = float(data.get("last_modified", 0) or 0)
            except (TypeError, ValueError):
                last_modified = None
            if None in (file_count, dir_count, total_size, last_modified):
                print("⚠️ Cache counters invalid — discarded, will do initial walk")
                return False

            raw_info = data.get("dir_info")
            if not isinstance(raw_info, dict) or not raw_info:
                print(
                    "⚠️ Cache has no usable dir_info — discarded, will do initial walk"
                )
                return False

            repaired = 0
            dir_info: Dict[str, dict] = {}
            for key, rec in raw_info.items():
                # Keys must already be in _rel() form: forward slashes, no
                # leading/trailing slash; otherwise get_dir_info() never hits them.
                if not isinstance(key, str) or "\\" in key or key != key.strip("/"):
                    repaired += 1
                    continue
                fixed = {}
                ok = isinstance(rec, dict)
                for field in ("file_count", "dir_count", "total_size"):
                    n = _nonneg_int(rec.get(field)) if ok else None
                    if n is None:
                        ok = False
                        n = 0
                    fixed[field] = n
                if not ok:
                    repaired += 1
                dir_info[key] = fixed

            if "" not in dir_info:
                # Root record is what every handler bubbles into — rebuild it
                dir_info[""] = {
                    "file_count": file_count,
                    "dir_count": dir_count,
                    "total_size": total_size,
                }
                repaired += 1

            root_rec = dir_info[""]
            if root_rec["file_count"] != file_count:
                print(
                    f"⚠️ Cache inconsistent: root record has {root_rec['file_count']:,} "
                    f"files, global counter {file_count:,} — will verify by walk"
                )
                repaired += 1
            if version == 1 and saved_root is None:
                # Legacy file: cannot prove which tree it describes
                repaired += 1

            # Validation passed — commit
            self._file_count = file_count
            self._dir_count = dir_count
            self._total_size = total_size
            self._last_modified = last_modified
            self._dir_info = dir_info
            self._load_repaired = repaired

            print(
                f"✅ Loaded cache: {self._file_count:,} files, "
                f"{self._dir_count:,} dirs, "
                f"{self._total_size / (1024**3):.2f} GB, "
                f"{len(self._dir_info):,} folders indexed"
                + (f" ({repaired} record(s) repaired/flagged)" if repaired else "")
            )

            # Load the companion file index
            file_index_manager.load()
            return True

        except Exception as e:
            print(f"⚠️ Failed to load cache: {e} — will do initial walk")
            self._dir_info = {}
            self._file_count = self._dir_count = self._total_size = 0
            self._last_modified = 0.0
            return False

    def _save_cache(self):
        """Atomically persist storage_index.json.

        2026-09-28 (WinError 32 fix): the old code wrote to a FIXED
        "storage_index.json.tmp" and called os.replace() once. At that time
        prod_server.py and the WebDAV subprocess each ran their own FileMonitor
        against the same cache dir (since 4.52 webdav_server.py no longer imports
        app.py, so only the main process runs one), and threads inside one
        process also call this concurrently (reconcile + watchdog), so two writers collided on the
        same .tmp / on the target while the other side (or antivirus/indexer)
        had it open -> "[WinError 32] The process cannot access the file".
        Now: (1) in-process saves are serialised by _save_lock (it existed
        but was never used), (2) each save writes to a UNIQUE temp file,
        (3) os.replace() is retried with short backoff on the Windows
        sharing-violation errors (5/32), (4) the dict is copied under
        self.lock first so json.dump never sees a dict mutating mid-write.
        Cross-process (only possible with a second server instance on the same
        cache dir) is last-writer-wins, which is fine: both compute the same
        index from the same disk. The retry now mainly covers antivirus/indexer.
        """
        with self._save_lock:
            tmp = None
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with self.lock:
                    dir_info_copy = {
                        k: (dict(v) if isinstance(v, dict) else v)
                        for k, v in self._dir_info.items()
                    }
                    data = {
                        "version": CACHE_SCHEMA_VERSION,
                        "root": str(self.root_path),
                        "file_count": self._file_count,
                        "dir_count": self._dir_count,
                        "total_size": self._total_size,
                        "last_modified": self._last_modified,
                        "dir_info": dir_info_copy,
                        "saved_at": time.time(),
                    }

                import tempfile

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
                    os.fsync(tf.fileno())  # power cut must not leave a 0-byte file

                last_err = None
                for delay in (0, 0.05, 0.1, 0.2, 0.4, 0.8, 1.5):
                    if delay:
                        time.sleep(delay)
                    try:
                        os.replace(tmp, CACHE_FILE)
                        last_err = None
                        tmp = None  # consumed by the replace
                        break
                    except PermissionError as e:  # WinError 5 / 32
                        last_err = e
                if last_err is not None:
                    raise last_err
            except Exception as e:
                print(f"⚠️ Failed to save cache: {e}")
                try:
                    if tmp and os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass

        # Keep file_index.json in sync with storage_index.json
        file_index_manager.save()

    # ------------------------------------------------------------------
    # Full walk — first boot or reconcile
    # ------------------------------------------------------------------

    def _full_walk(
        self, silent: bool = False, on_progress: Optional[Callable] = None
    ) -> dict:
        """
        Walk entire filesystem in one pass.
        Builds global counters AND dir_info for every folder simultaneously.
        Only called on first boot (no cache) or every 15 minutes for reconciliation.

        on_progress(file_count, dir_count, total_size) is called every
        WALK_PROGRESS_INTERVAL files so callers can push live SSE updates
        while the walk is still in progress.
        """
        if not silent:
            print(f"🚶 Starting full filesystem walk + index build: {self.root_path}")
            walk_start = time.time()

        file_count = 0
        dir_count = 0
        total_size = 0
        latest_mtime = 0.0

        # dir_info[rel_path] = {file_count, dir_count, total_size}
        # We build it bottom-up by accumulating into each folder
        dir_info: Dict[str, dict] = {}

        # direct_entries[rel_path] = [entry_dict, ...]  — immediate children only,
        # used to build file_index.json for folders that exceed THRESHOLD entries.
        direct_entries: Dict[str, list] = {}

        # Pre-seed root
        dir_info[""] = {"file_count": 0, "dir_count": 0, "total_size": 0}
        direct_entries[""] = []

        # 4.59: os.walk() swallows scandir errors by default, so an offline
        # drive or an unreadable folder used to look like "an empty tree" and
        # the result overwrote good data. Collect them; `complete` is False if
        # the root itself could not be walked or the walk raised.
        walk_errors: list = []
        skipped_junctions: list = []
        complete = True
        root_str = str(self.root_path)

        def _on_walk_error(err):
            walk_errors.append(getattr(err, "filename", None) or str(err))

        if not os.path.isdir(root_str):
            complete = False
            print(f"❌ Walk aborted: root is not a readable directory: {root_str}")

        try:
            for root, dirs, files in (
                os.walk(root_str, topdown=True, onerror=_on_walk_error)
                if complete
                else ()
            ):
                # Skip chunk temp directory
                if ".chunks" in dirs:
                    dirs.remove(".chunks")

                # 4.64: do not descend into NTFS junctions / mount points. Legacy
                # profile junctions (e.g. "Documents\\My Music") deny listing and were
                # reported as unreadable on every walk; accessible ones were counted
                # twice (here and at their real location).
                for _d in list(dirs):
                    _jp = os.path.join(root, _d)
                    if _is_junction(_jp):
                        dirs.remove(_d)
                        skipped_junctions.append(_jp)

                # Yield the GIL between directories. Under Hypercorn there is
                # exactly ONE thread running the whole asyncio event loop, so
                # a tight loop of thousands of back-to-back os.stat() calls in
                # this thread can out-race the OS scheduler for the GIL and
                # starve the event loop thread (worse on Windows than POSIX).
                # A real (non-zero) sleep forces this thread to actually give
                # up its turn instead of just offering to — see
                # WALK_YIELD_SECONDS' comment above for why time.sleep(0)
                # isn't reliable enough on Windows. The event loop gets a
                # fair turn between directories.
                time.sleep(WALK_YIELD_SECONDS)

                root_rel = _rel(root, str(self.root_path))

                # Ensure this dir exists in index
                if root_rel not in dir_info:
                    dir_info[root_rel] = {
                        "file_count": 0,
                        "dir_count": 0,
                        "total_size": 0,
                    }
                if root_rel not in direct_entries:
                    direct_entries[root_rel] = []

                # Register immediate subdirs and bubble dir_count up to all ancestors
                for d in dirs:
                    if d.startswith("."):
                        continue
                    sub_rel = (root_rel + "/" + d) if root_rel else d
                    if sub_rel not in dir_info:
                        dir_info[sub_rel] = {
                            "file_count": 0,
                            "dir_count": 0,
                            "total_size": 0,
                        }
                    if sub_rel not in direct_entries:
                        direct_entries[sub_rel] = []
                    dir_info[root_rel]["dir_count"] += 1
                    dir_count += 1
                    # Bubble dir count up to all ancestors
                    for ancestor in _parents(root_rel):
                        if ancestor in dir_info:
                            dir_info[ancestor]["dir_count"] += 1
                    # Record subdir as a direct entry of root_rel (for file index)
                    d_path = os.path.join(root, d)
                    try:
                        d_mtime = os.stat(d_path).st_mtime
                    except OSError:
                        d_mtime = None
                    direct_entries[root_rel].append(
                        {"name": d, "is_dir": True, "size": None, "modified": d_mtime}
                    )

                # Count files in this directory
                for fname in files:
                    if fname.startswith("."):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        st = os.stat(fpath)
                        fsize = st.st_size
                        fmtime = st.st_mtime

                        file_count += 1
                        total_size += fsize
                        if fmtime > latest_mtime:
                            latest_mtime = fmtime

                        # Emit live progress every WALK_PROGRESS_INTERVAL files
                        if on_progress and file_count % WALK_PROGRESS_INTERVAL == 0:
                            on_progress(file_count, dir_count, total_size)

                        # Yield the GIL every WALK_YIELD_INTERVAL files too —
                        # the per-directory sleep above isn't enough if a
                        # single folder holds tens of thousands of files.
                        if file_count % WALK_YIELD_INTERVAL == 0:
                            time.sleep(WALK_YIELD_SECONDS)

                        # Add file to immediate parent
                        dir_info[root_rel]["file_count"] += 1
                        dir_info[root_rel]["total_size"] += fsize

                        # Bubble file_count and size up to all ancestors
                        for ancestor in _parents(root_rel):
                            if ancestor in dir_info:
                                dir_info[ancestor]["file_count"] += 1
                                dir_info[ancestor]["total_size"] += fsize

                        # Record as a direct entry of root_rel (for file index)
                        direct_entries[root_rel].append(
                            {
                                "name": fname,
                                "is_dir": False,
                                "size": fsize,
                                "modified": fmtime,
                            }
                        )

                    except (OSError, IOError):
                        continue

                # Sort direct_entries for root_rel now that all children are known
                direct_entries[root_rel].sort(
                    key=lambda x: (not x["is_dir"], x["name"].lower())
                )

        except Exception as e:
            complete = False
            print(f"❌ Error during filesystem walk: {e}")

        if root_str in walk_errors:
            complete = False  # the root itself failed — nothing below is trustworthy
        if len(skipped_junctions) != self._last_junction_count:
            self._last_junction_count = len(skipped_junctions)
            if skipped_junctions:
                print(
                    f"↪️ Walk: skipped {len(skipped_junctions)} junction folder(s) "
                    f"(not followed, not counted; first: {skipped_junctions[0]})"
                )
        if walk_errors:
            print(
                f"⚠️ Walk: {len(walk_errors)} folder(s) could not be read "
                f"(first: {walk_errors[0]}) — their contents are not counted"
            )

        if not silent:
            elapsed = time.time() - walk_start
            print(
                f"✅ Walk + index complete in {elapsed:.1f}s: "
                f"{file_count:,} files, {dir_count:,} dirs, "
                f"{total_size / (1024**3):.2f} GB, "
                f"{len(dir_info):,} folders indexed"
            )

        # The walk's per-folder data repairs the two companion indexes — but
        # only from a walk that finished. An aborted walk must not touch them.
        if complete:
            # Build file_index.json for folders exceeding the direct-entry threshold
            file_index_manager.build_from_walk(direct_entries)

            # Same data repairs the search index (changes missed while a bulk-op
            # settle was pending, or while the server was down). No-op until the
            # search index's first crawl has finished.
            try:
                search_index_manager.reconcile_from_walk(direct_entries)
            except Exception as e:
                print(f"⚠️  Search index reconcile failed: {e}")

        return {
            "file_count": file_count,
            "dir_count": dir_count,
            "total_size": total_size,
            "last_modified": latest_mtime,
            "dir_info": dir_info,
            "complete": complete,
            "errors": len(walk_errors),
        }

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def set_pending_reconcile(self):
        """
        Arm the hard-timer settle after a bulk-op reconcile.

        Sets _pending_reconcile=True so watchdog counter updates are suppressed,
        then fires a one-shot threading.Timer(SETTLE_DELAY) that runs a ground-truth
        reconcile unconditionally after SETTLE_DELAY seconds.

        Using a hard timer instead of debounce so active uploads cannot delay
        the settle indefinitely — the settle always fires within SETTLE_DELAY seconds
        and catches any genuinely new files (Windows copy, etc.) that arrived during
        the suppression window.
        """
        with self._settle_lock:
            # Cancel any previous settle timer (e.g. rapid back-to-back bulk ops)
            if self._settle_timer is not None:
                self._settle_timer.cancel()
            with self.lock:
                self._pending_reconcile = True
                self._drain_gen += 1  # invalidate any older post-walk drain timer
            self._settle_timer = threading.Timer(SETTLE_DELAY, self._settle_reconcile)
            self._settle_timer.daemon = True
            self._settle_timer.start()
        print(
            f"🔄 Settle reconcile armed — counter updates suppressed for {SETTLE_DELAY}s"
        )

    def _clear_pending_reconcile(self, gen=None):
        """
        Called by the post-walk drain timer to re-enable watchdog increments.
        Does NOT trigger another walk — it only lifts the suppression flag so
        genuine new events (created after the drain window ends) are counted.

        4.62: `gen` is the drain generation the timer was armed for. If a newer
        walk or settle has started since, that one owns the flag and this
        (stale) timer must not clear it mid-walk.
        """
        with self.lock:
            if gen is not None and gen != self._drain_gen:
                print(
                    "⏭️ Stale post-walk drain timer ignored (a newer walk owns the flag)"
                )
                return
            self._pending_reconcile = False
        print("✅ Post-walk drain complete — watchdog increments resumed")
        # 4.64: events that arrived during the walk/drain only marked their
        # folders dirty. Correct those folders now (the walk may have scanned
        # them before the change) and tell the browser.
        with self._dirty_lock:
            has_dirty = bool(self._dirty_folders)
        if has_dirty:
            try:
                self._notify_and_save()
            except Exception as e:
                print(f"⚠️ Post-walk folder correction failed: {e}")

    def _settle_reconcile(self):
        """Fired by the hard timer — ground-truth walk after suppression window."""
        print("🔄 Settle reconcile firing (hard timer expired)")
        try:
            self._reconcile()  # internally force-pushes SSE with reconcile_complete=True
        except Exception as e:
            print(f"⚠️ Settle reconcile error: {e}")
        finally:
            with self._settle_lock:
                self._settle_timer = None

    def _reconcile(self, force: bool = False) -> bool:
        """Ground-truth walk, ONE AT A TIME (4.62). Returns True if the result was
        applied (or an equally fresh walk already was), False if it was rejected.

        Every caller (15-minute loop, startup, settle timer, retry timer,
        reconcile_async, force_check, /admin/rebuild_cache, _trigger_reconcile)
        used to start its own walk with no lock, so walks could overlap: a stale
        drain timer lifted the suppression flag mid-walk, an older walk could
        finish last and overwrite a newer result, and _suspect_walks raced.
        Now callers queue on _walk_lock. A caller that had to wait is skipped if
        a walk that STARTED after its request was applied meanwhile (that walk
        saw every change made before the request). force=True always walks.
        """
        requested_at = time.monotonic()
        with self._walk_lock:
            if (
                not force
                and self._walk_applied
                and self._walk_started_at > requested_at
            ):
                print(
                    "🔄 Reconcile request covered by a walk that started after it — skipped"
                )
                return True
            self._walk_started_at = time.monotonic()
            self._walk_applied = False
            applied = False
            try:
                applied = self._reconcile_walk(force)
                return applied
            finally:
                self._walk_applied = applied

    def _reconcile_walk(self, force: bool = False) -> bool:
        """The actual ground-truth walk (callers must hold _walk_lock via
        _reconcile()). Returns True if the result was applied, False if it
        was rejected (aborted walk, or suspect-empty and not `force`).

        force=True (the admin "Rebuild Cache" button) accepts an empty result.
        """
        # Every caller of _reconcile() runs it on a background thread (the
        # periodic reconcile_loop thread, the post-startup delayed_reconcile
        # thread, the settle timer, reconcile_async's on-demand thread, and
        # admin_rebuild_cache via asyncio.to_thread) — never on the main
        # thread that runs Hypercorn's event loop, so it's always safe to
        # deprioritize the CALLING thread here.
        _lower_current_thread_priority()
        print("🔄 Background reconciliation walk starting...")

        # Keep _pending_reconcile = True for the ENTIRE walk.
        #
        # Why NOT clear it at the top like before:
        #   Clearing it lets _notify_and_save fire during the walk with
        #   partially-incremented watchdog values (e.g. 51000) → wrong SSE.
        #
        # Why keep it True:
        #   on_created/on_deleted/on_moved all skip their counter increment when
        #   _pending_reconcile is True — the walk produces the ground-truth count
        #   so we don't need watchdog increments during the walk at all.
        #   _notify_and_save also returns early, so no spurious SSE mid-walk.
        #
        # When it clears:
        #   After the walk finishes + epoch bumps, we re-arm for POST_WALK_DRAIN
        #   seconds to flush any OS-queued events the burst suppression held back.
        #   _clear_pending_reconcile() then re-enables normal watchdog counting.
        with self.lock:
            self._pending_reconcile = True  # keep suppression on for entire walk
            self._drain_gen += 1  # any drain timer of an earlier walk is now stale

        _true_old_snapshot = self.last_snapshot

        # ── Full walk ───────────────────────────────────────────────────────
        # on_progress only prints — no SSE, no last_snapshot mutation.
        # Walk-progress SSE caused "1000 → 51000 → 50580" oscillation because:
        #   • Early progress tick at 1000 files set last_snapshot(file_count=1000)
        #     → frontend displayed 1000
        #   • _notify_and_save (pending=False, old code) pushed 51000 mid-walk
        #     → frontend displayed 51000
        # The single reconcile_complete push at the end is sufficient.
        def _on_progress(fc: int, dc: int, ts: int):
            print(f"📊 Walk progress: {fc:,} files, {ts / (1024**3):.2f} GB")

        result = self._full_walk(silent=True, on_progress=_on_progress)

        # ── Reject a walk that cannot be trusted ────────────────────────────
        # (4.59) An aborted walk (root unreadable / exception) or one that finds
        # nothing while the index holds many files (drive offline, share not
        # mounted) must not replace good counters or be saved over good data.
        reject = None
        if not result.get("complete", True):
            reject = "walk did not complete"
        elif (
            not force
            and result["file_count"] == 0
            and result["dir_count"] == 0
            and self._file_count >= SUSPECT_EMPTY_MIN_FILES
        ):
            # Accept only if the NEXT walk is empty too (tree really was emptied).
            self._suspect_walks += 1
            if self._suspect_walks < 2:
                reject = (
                    f"walk found 0 files but the index holds {self._file_count:,} "
                    f"— suspect (drive offline?)"
                )
        if reject is None:
            self._suspect_walks = 0
        else:
            print(f"🛑 Reconcile rejected, previous index kept: {reject}")
            with self.lock:
                self._pending_reconcile = False  # nothing was applied; resume counting
            self._schedule_retry()
            return False

        old_dir_info = self._dir_info  # for the per-folder drift report below

        with self.lock:
            self._file_count = result["file_count"]
            self._dir_count = result["dir_count"]
            self._total_size = result["total_size"]
            self._last_modified = result["last_modified"]
            self._dir_info = result["dir_info"]
            # Bump epoch AFTER writing corrected counters.
            # Events that snapshotted the old epoch and are blocked on the lock
            # will see the mismatch and skip their increment.
            self._reconcile_epoch += 1
            # Stay suppressed — OS queue may still hold thousands of events
            # for files the walk already counted.  POST_WALK_DRAIN flushes them.
            self._pending_reconcile = True
            drain_gen = self._drain_gen

        # Drain timer: lifts suppression after OS queue drains.  No walk.
        drain_timer = threading.Timer(
            POST_WALK_DRAIN, self._clear_pending_reconcile, args=(drain_gen,)
        )
        drain_timer.daemon = True
        drain_timer.start()
        print(f"🔄 Post-walk drain armed for {POST_WALK_DRAIN}s")

        new_snapshot = self._build_snapshot()
        self.last_snapshot = new_snapshot
        self._save_cache()

        # Single authoritative SSE push — _dir_info is now complete.
        # reconcile_complete=True tells the frontend to refresh the file table
        # and re-fetch all dir-info cells now that _dir_info is authoritative.
        self._notify_changes(
            _true_old_snapshot or new_snapshot, new_snapshot, reconcile_complete=True
        )

        # Per-folder drift: the global counters can match while individual
        # folder records are wrong (e.g. a moved folder's ancestors), so compare
        # every record old-vs-new and report how many were corrected.
        f_added = f_removed = f_changed = 0
        try:
            new_info = result["dir_info"]
            f_added = sum(1 for k in new_info if k not in old_dir_info)
            f_removed = sum(1 for k in old_dir_info if k not in new_info)
            f_changed = sum(
                1
                for k, v in new_info.items()
                if k in old_dir_info and old_dir_info[k] != v
            )
        except Exception:
            pass
        folder_drift = f_added + f_removed + f_changed

        if _true_old_snapshot and (
            _true_old_snapshot.file_count != new_snapshot.file_count
            or _true_old_snapshot.dir_count != new_snapshot.dir_count
            or _true_old_snapshot.total_size != new_snapshot.total_size
            or folder_drift
        ):
            print(
                f"🔄 Reconciliation corrected drift: "
                f"files {_true_old_snapshot.file_count}→{new_snapshot.file_count}, "
                f"dirs {_true_old_snapshot.dir_count}→{new_snapshot.dir_count}, "
                f"folder records +{f_added} −{f_removed} ~{f_changed}"
            )
        else:
            print("✅ Reconciliation complete — no drift detected")
        return True

    def _schedule_retry(self):
        """One-shot retry of a rejected reconcile (does not stack)."""
        with self._settle_lock:
            if self._retry_timer is not None or not self.monitoring:
                return

            def _go():
                try:
                    self._reconcile()
                except Exception as e:
                    print(f"⚠️ Retry reconcile error: {e}")
                finally:
                    with self._settle_lock:
                        self._retry_timer = None

            self._retry_timer = threading.Timer(SUSPECT_RETRY_SECONDS, _go)
            self._retry_timer.daemon = True
            self._retry_timer.start()
        print(f"🔁 Reconcile retry scheduled in {SUSPECT_RETRY_SECONDS}s")

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def _build_snapshot(self) -> StorageSnapshot:
        checksum = hashlib.md5(
            f"{self._file_count}:{self._dir_count}:{self._total_size}".encode()
        ).hexdigest()
        return StorageSnapshot(
            file_count=self._file_count,
            dir_count=self._dir_count,
            total_size=self._total_size,
            last_modified=self._last_modified,
            checksum=checksum,
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------
    # Notify + save (called after debounce)
    # ------------------------------------------------------------------

    # -- 4.63 helpers: deferred folder re-index + per-batch timing ----------

    def mark_folder_dirty(self, rel_path: str, abs_path: str):
        """Called by the watchdog handlers instead of an immediate
        file_index_manager.update_folder() (a full scandir of the folder)."""
        with self._dirty_lock:
            self._dirty_folders[rel_path] = abs_path

    def _flush_dirty_folders(self, items=None):
        """Re-scan every marked folder once. Returns (folders, seconds).
        `items` = {rel: abs} already taken by the caller; None = take the set."""
        if items is None:
            with self._dirty_lock:
                items = dict(self._dirty_folders)
                self._dirty_folders.clear()
        t0 = time.perf_counter()
        for rel, abs_p in items.items():
            try:
                file_index_manager.update_folder(rel, abs_p)
            except Exception as e:
                print(f"⚠️ File index re-scan of '{rel}' failed: {e}")
        return len(items), time.perf_counter() - t0

    @staticmethod
    def _changed_dirs_payload(dirty):
        """(sorted folder list capped for SSE, truncated flag)."""
        keys = sorted(dirty)
        return keys[:MAX_CHANGED_DIRS_SENT], len(keys) > MAX_CHANGED_DIRS_SENT

    def _correct_folders(self, dirty: Dict[str, str]) -> bool:
        """4.64: recompute the folders whose direct entries changed FROM DISK and
        apply the difference to dir_info, every ancestor and the global counters.

        The watchdog handlers still update the counters instantly, but they cannot
        get everything right (size of a deleted file, size of a file still being
        copied, file/folder moves between folders, in-place edits, events dropped
        while a walk runs). Every event marks its folder dirty, so within one
        debounce cycle each such folder is re-read (one scandir, plus a sub-tree
        walk only for a NEW sub-folder) and the record is set to what is really on
        disk. It is idempotent: a late or duplicate event just marks the folder
        again and the next pass finds nothing to change. The 15-minute walk
        remains the independent validation. Returns True if a counter changed."""
        if not dirty:
            return False
        root_str = str(self.root_path)
        with self.lock:
            epoch = self._reconcile_epoch
            if "" not in self._dir_info:
                return False  # no baseline yet; the first walk builds it
            known = self._dir_info
            targets = set()
            for rel in dirty:
                r = rel
                while r and r not in known:
                    r = r.rpartition("/")[0]
                targets.add(r)
        resolved = set()
        for r in targets:
            # a folder that vanished is handled by its parent's pass
            while r and not os.path.isdir(os.path.join(root_str, r)):
                r = r.rpartition("/")[0]
            resolved.add(r)
        if len(resolved) > MAX_CORRECT_FOLDERS:
            print(
                f"⚠️ {len(resolved)} folders changed in one batch - arming a settle "
                f"walk instead of per-folder correction"
            )
            self.set_pending_reconcile()
            return False

        with self.lock:  # children index: parent -> {child rel}
            children: Dict[str, set] = {}
            for k in self._dir_info:
                if k:
                    children.setdefault(k.rpartition("/")[0], set()).add(k)

        def _drop_subtree(top):
            """Remove `top` and everything below it from dir_info + the index."""
            stack = [top]
            while stack:
                k = stack.pop()
                self._dir_info.pop(k, None)
                stack.extend(children.pop(k, ()))
            parent = top.rpartition("/")[0]
            children.get(parent, set()).discard(top)

        order = sorted(resolved, key=lambda r: (-(r.count("/") + (1 if r else 0)), r))
        changed_any = False
        for idx, rel in enumerate(order):
            abs_p = os.path.join(root_str, rel) if rel else root_str
            scan = _scan_direct(abs_p)
            if scan is None:
                continue  # unreadable: leave the record to the next walk
            files_n, files_sz, latest, subdirs = scan
            prefix = (rel + "/") if rel else ""
            with self.lock:
                unknown = [d for d in subdirs if (prefix + d) not in self._dir_info]
            walked = {}
            for d in unknown:
                walked[prefix + d] = _walk_subtree(root_str, os.path.join(abs_p, d))
            with self.lock:
                if self._reconcile_epoch != epoch or self._pending_reconcile:
                    # a walk replaced the data meanwhile: it is authoritative.
                    # Re-mark what is left so it is checked after the walk.
                    for r in order[idx:]:
                        self.mark_folder_dirty(
                            r, os.path.join(root_str, r) if r else root_str
                        )
                    return changed_any
                rec = self._dir_info.get(rel)
                if rec is None:
                    self.mark_folder_dirty(rel, abs_p)
                    continue
                new_files, new_size, new_dirs = files_n, files_sz, 0
                for d in subdirs:
                    crel = prefix + d
                    inc = 0 if d.startswith(".") else 1
                    if crel in walked:
                        sub_info, sub_latest = walked[crel]
                        top = sub_info[crel]
                        _drop_subtree(crel)  # a partial record made by a handler
                        self._dir_info.update(sub_info)
                        for k in sub_info:
                            children.setdefault(k.rpartition("/")[0], set()).add(k)
                        if sub_latest > self._last_modified:
                            self._last_modified = sub_latest
                    else:
                        top = self._dir_info.get(crel)
                        if top is None:
                            continue
                    new_files += top["file_count"]
                    new_size += top["total_size"]
                    new_dirs += inc + top["dir_count"]
                for c in list(children.get(rel, ())):
                    if c in self._dir_info and c.rpartition("/")[2] not in subdirs:
                        _drop_subtree(c)  # sub-folder no longer on disk
                df = new_files - rec["file_count"]
                dd = new_dirs - rec["dir_count"]
                ds = new_size - rec["total_size"]
                if df or dd or ds:
                    rec["file_count"] = new_files
                    rec["dir_count"] = new_dirs
                    rec["total_size"] = new_size
                    for anc in _parents(rel):
                        a = self._dir_info.get(anc)
                        if a is not None:
                            a["file_count"] = max(0, a["file_count"] + df)
                            a["dir_count"] = max(0, a["dir_count"] + dd)
                            a["total_size"] = max(0, a["total_size"] + ds)
                    self._file_count = max(0, self._file_count + df)
                    self._dir_count = max(0, self._dir_count + dd)
                    self._total_size = max(0, self._total_size + ds)
                    changed_any = True
                if latest > self._last_modified:
                    self._last_modified = latest
        return changed_any

    def remap_dirty(self, src_rel: str, dest_rel: str):
        """A folder was moved/renamed: folders already marked dirty below its OLD
        path now live below the new one. Without this the mark would point at a
        path that no longer exists and the (moved) record would keep stale totals
        until the next walk."""
        root = str(self.root_path)
        prefix = src_rel + "/"
        with self._dirty_lock:
            moved = {}
            for k in list(self._dirty_folders):
                if k == src_rel or k.startswith(prefix):
                    nk = dest_rel + k[len(src_rel) :]
                    del self._dirty_folders[k]
                    moved[nk] = os.path.join(root, nk) if nk else root
            self._dirty_folders.update(moved)

    def _note_event(self):
        with self._dirty_lock:
            if self._batch_first_ts is None:
                self._batch_first_ts = time.time()
            self._batch_events += 1

    def _note_handler_time(self, secs: float):
        with self._dirty_lock:
            self._batch_handler_secs += secs

    def _notify_and_save(self):
        # While a walk or its drain window is active the counters are not
        # touched (the walk is authoritative) - but the browser is still told
        # WHICH folders changed so the visible listing refreshes at once, and the
        # folders stay marked for correction after the walk (_clear_pending_reconcile).
        if self._pending_reconcile:
            with self._dirty_lock:
                pending_dirs = dict(self._dirty_folders)
            if pending_dirs:
                dirs_list, truncated = self._changed_dirs_payload(pending_dirs)
                self._notify_activity(dirs_list, truncated)
            return

        t_start = time.perf_counter()
        with self._dirty_lock:
            first_ts = self._batch_first_ts
            n_events = self._batch_events
            handler_secs = self._batch_handler_secs
            self._batch_first_ts = None
            self._batch_events = 0
            self._batch_handler_secs = 0.0
            dirty = dict(self._dirty_folders)
            self._dirty_folders.clear()
        dirs_list, truncated = self._changed_dirs_payload(dirty)

        old_snapshot = self.last_snapshot
        new_snapshot = self._build_snapshot()
        self.last_snapshot = new_snapshot

        # 4.63: push the SSE update FIRST (before any disk work).
        if old_snapshot:
            self._notify_changes(
                old_snapshot,
                new_snapshot,
                changed_dirs=dirs_list,
                changed_dirs_truncated=truncated,
            )
            print(
                f"📊 Notified: files={new_snapshot.file_count:,}, "
                f"dirs={new_snapshot.dir_count:,}"
                + (f", {len(dirty)} folder(s) changed" if dirty else "")
            )
        push_ts = time.time()
        t_pushed = time.perf_counter()

        # 4.64: correct the changed folders from disk; push again if that moved
        # any counter (deleted-file sizes, moves, edits, files still growing...).
        corrected = False
        try:
            corrected = self._correct_folders(dirty)
        except Exception as e:
            print(f"⚠️ Folder correction failed (the 15-min walk will fix it): {e}")
        t_corrected = time.perf_counter()
        if corrected:
            snap_after = self._build_snapshot()
            before = self.last_snapshot
            self.last_snapshot = snap_after
            if before:
                self._notify_changes(
                    before,
                    snap_after,
                    changed_dirs=dirs_list,
                    changed_dirs_truncated=truncated,
                )
                print(
                    f"📊 Corrected from disk: files={snap_after.file_count:,}, "
                    f"dirs={snap_after.dir_count:,}, size={snap_after.total_size:,}"
                )

        n_dirty, flush_secs = self._flush_dirty_folders(dirty)
        t_flushed = time.perf_counter()
        self._save_cache()
        t_saved = time.perf_counter()

        latency = (push_ts - first_ts) if first_ts else 0.0
        if (
            latency >= SLOW_BATCH_LOG_SECS
            or (t_saved - t_pushed) >= SLOW_BATCH_LOG_SECS
        ):
            print(
                f"⏱️ Watchdog batch: {n_events} event(s); first event → SSE push "
                f"{latency:.2f}s (handlers {handler_secs:.2f}s total, snapshot+push "
                f"{t_pushed - t_start:.2f}s); correction {t_corrected - t_pushed:.2f}s; "
                f"{n_dirty} folder(s) re-indexed in {flush_secs:.2f}s; "
                f"save {t_saved - t_flushed:.2f}s"
            )

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def _reconcile_loop(self):
        while self.monitoring:
            time.sleep(RECONCILE_INTERVAL)
            if self.monitoring:
                try:
                    self._reconcile()
                except Exception as e:
                    print(f"❌ Reconciliation error: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_monitoring(self):
        if self.monitoring:
            print("⚠️ File monitor already running")
            return

        print("🚀 Starting file system monitor (full recursive index)...")
        self.monitoring = True

        cache_loaded = self._load_cache()

        first_walk_complete = True
        if not cache_loaded:
            result = self._full_walk()
            first_walk_complete = bool(result.get("complete", True))
            with self.lock:
                self._file_count = result["file_count"]
                self._dir_count = result["dir_count"]
                self._total_size = result["total_size"]
                self._last_modified = result["last_modified"]
                self._dir_info = result["dir_info"]
            if first_walk_complete:
                self._save_cache()
            else:
                print("⚠️ First walk incomplete — not saving; will retry shortly")

        self.last_snapshot = self._build_snapshot()
        print(
            f"📸 Snapshot ready: {self.last_snapshot.file_count:,} files, "
            f"{self.last_snapshot.dir_count:,} dirs, "
            f"{len(self._dir_info):,} folders indexed"
        )

        # Start watchdog
        try:
            self.event_handler = InstantFileEventHandler(self)
            self.observer = Observer()
            self.observer.schedule(
                self.event_handler, str(self.root_path), recursive=True
            )
            self.observer.start()
            print("⚡ Watchdog started — instant change detection active")
        except Exception as e:
            print(f"⚠️ Failed to start watchdog: {e}")
            # 4.59: do not keep an observer that never started — stop_monitoring()
            # would raise "cannot join thread before it is started" on shutdown.
            self.observer = None
            self.event_handler = None

        # Start reconcile thread
        self.reconcile_thread = threading.Thread(
            target=self._reconcile_loop, daemon=True, name="reconcile-thread"
        )
        self.reconcile_thread.start()
        print(f"🔄 Reconciliation every {RECONCILE_INTERVAL // 60} minutes")

        # Post-startup reconcile to catch offline changes (also re-verifies a
        # cache that needed repair, or a first walk that did not complete)
        if cache_loaded or not first_walk_complete:
            _delay = (
                POST_START_RECONCILE_DELAY_REPAIRED
                if (self._load_repaired or not first_walk_complete)
                else POST_START_RECONCILE_DELAY
            )

            def delayed_reconcile():
                time.sleep(_delay)
                if self.monitoring:
                    print(
                        "🔄 Post-startup reconciliation (catching offline changes)..."
                    )
                    self._reconcile()

            threading.Thread(target=delayed_reconcile, daemon=True).start()

    def stop_monitoring(self):
        if not self.monitoring:
            return
        print("🛑 Stopping file system monitor")
        self.monitoring = False
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=2)
            self.observer = None
            self.event_handler = None
        self._save_cache()
        print("💾 Cache saved on shutdown")

    def get_current_snapshot(self) -> Optional[StorageSnapshot]:
        """Identical interface to original"""
        return self.last_snapshot

    def get_stats_dict(self) -> Dict:
        if self.last_snapshot:
            return asdict(self.last_snapshot)
        return {}

    def get_dir_info(self, rel_path: str) -> Optional[dict]:
        """
        Instant dir info lookup from index — never walks the filesystem.
        Returns {file_count, dir_count, total_size} or None if not indexed yet.
        rel_path: forward-slash relative path from ROOT_DIR, or '' for root.
        """
        # Normalize path separators
        rel_path = rel_path.replace("\\", "/").strip("/")
        with self.lock:
            rec = self._dir_info.get(rel_path, None)
            # Copy: callers (JSON responses) must never see a record the
            # watchdog is mutating under the lock.
            return dict(rec) if isinstance(rec, dict) else rec

    def force_check(self) -> Optional[StorageSnapshot]:
        """Force immediate reconciliation — kept for API compatibility"""
        print("🔍 Force check requested — running reconciliation")
        self._reconcile()
        return self.last_snapshot

    def reconcile_async(self, reason: str = ""):
        """
        Trigger a reconciliation in a background thread — non-blocking.
        Called after upload/copy completes so the count corrects immediately
        without waiting for the 15-minute scheduled reconcile or debounce timer.
        """
        label = f" ({reason})" if reason else ""
        print(f"🔄 Async reconcile queued{label}")
        threading.Thread(
            target=self._reconcile, daemon=True, name="reconcile-on-demand"
        ).start()


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

file_monitor = FileSystemMonitor()


def init_file_monitor():
    global file_monitor
    if not file_monitor.monitoring:
        file_monitor.start_monitoring()
    return file_monitor


def get_file_monitor():
    return file_monitor
