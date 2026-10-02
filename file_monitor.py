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

    def _schedule_notify(self):
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

    def on_created(self, event):
        # Skip hidden files/dirs (matches _full_walk) and anything inside .chunks
        _name = os.path.basename(event.src_path)
        if _name.startswith(".") or ".chunks" in event.src_path:
            return

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
        file_index_manager.update_folder(_parent_rel, _parent_abs)
        # If a new subdirectory was created, seed it in the index (starts empty,
        # update_folder will skip it; it will be added once it exceeds threshold)
        if event.is_directory:
            file_index_manager.update_folder(src_rel, event.src_path)

        # --- search index: add the new entry ---
        _entry_name = os.path.basename(event.src_path)
        search_index_manager.add(src_rel, _entry_name, event.is_directory)

        # Auto-arm settle if this looks like a bulk copy from outside the web UI
        if not event.is_directory:
            self._check_burst()

        self._schedule_notify()

    def on_deleted(self, event):
        # Skip hidden files/dirs (matches _full_walk) and anything inside .chunks
        _name = os.path.basename(event.src_path)
        if _name.startswith(".") or ".chunks" in event.src_path:
            return

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
            file_index_manager.update_folder(_parent_rel, _parent_abs)
        else:
            _parent_abs = os.path.dirname(event.src_path)
            _parent_rel = _rel(_parent_abs, str(self.monitor.root_path))
            file_index_manager.update_folder(_parent_rel, _parent_abs)

        # --- search index: remove the deleted entry ---
        if event.is_directory:
            search_index_manager.remove_tree(src_rel)
        else:
            search_index_manager.remove(src_rel)

        self._schedule_notify()

    def on_moved(self, event):
        # Skip hidden files/dirs (matches _full_walk) and pure .chunks-to-.chunks moves
        _src_name = os.path.basename(event.src_path)
        _dst_name = os.path.basename(event.dest_path)
        if (_src_name.startswith(".") and _dst_name.startswith(".")) or (
            ".chunks" in event.src_path and ".chunks" in event.dest_path
        ):
            return

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

                # Update old parent dir_count down, new parent dir_count up
                for parent in _parents(src_rel):
                    if parent in self.monitor._dir_info:
                        self.monitor._dir_info[parent]["dir_count"] = max(
                            0, self.monitor._dir_info[parent]["dir_count"] - 1
                        )
                for parent in _parents(dest_rel):
                    if parent in self.monitor._dir_info:
                        self.monitor._dir_info[parent]["dir_count"] += 1
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

                    if src_parent in self.monitor._dir_info:
                        self.monitor._dir_info[src_parent]["file_count"] = max(
                            0, self.monitor._dir_info[src_parent]["file_count"] - 1
                        )
                        self.monitor._dir_info[src_parent]["total_size"] = max(
                            0,
                            self.monitor._dir_info[src_parent]["total_size"]
                            - file_size,
                        )
                    if dest_parent in self.monitor._dir_info:
                        self.monitor._dir_info[dest_parent]["file_count"] += 1
                        self.monitor._dir_info[dest_parent]["total_size"] += file_size

        # --- file index: rename dir keys or update both parent folders ---
        if event.is_directory:
            file_index_manager.rename_folder(src_rel, dest_rel)
            # Both old and new parent folders changed their direct entry list
            _src_parent_abs = os.path.dirname(event.src_path)
            _dest_parent_abs = os.path.dirname(event.dest_path)
            _src_parent_rel = _rel(_src_parent_abs, str(self.monitor.root_path))
            _dest_parent_rel = _rel(_dest_parent_abs, str(self.monitor.root_path))
            file_index_manager.update_folder(_src_parent_rel, _src_parent_abs)
            if _src_parent_rel != _dest_parent_rel:
                file_index_manager.update_folder(_dest_parent_rel, _dest_parent_abs)
        else:
            _src_parent_abs = os.path.dirname(event.src_path)
            _dest_parent_abs = os.path.dirname(event.dest_path)
            _src_parent_rel = _rel(_src_parent_abs, str(self.monitor.root_path))
            _dest_parent_rel = _rel(_dest_parent_abs, str(self.monitor.root_path))
            file_index_manager.update_folder(_src_parent_rel, _src_parent_abs)
            if _src_parent_rel != _dest_parent_rel:
                file_index_manager.update_folder(_dest_parent_rel, _dest_parent_abs)

        # --- search index: rename the moved entry or tree ---
        _dest_name = os.path.basename(event.dest_path)
        if event.is_directory:
            search_index_manager.rename_tree(src_rel, dest_rel)
        else:
            search_index_manager.remove(src_rel)
            search_index_manager.add(dest_rel, _dest_name, False)

        self._schedule_notify()

    def on_modified(self, event):
        # File content changed — size may have changed, let reconcile handle it
        if ".chunks" in event.src_path or event.is_directory:
            return
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
    ):
        with self.lock:
            callbacks = list(self.change_callbacks)
        for cb in callbacks:
            try:
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

    def _notify_and_save(self):
        # Skip SSE push if suppressed — the hard settle timer will push after SETTLE_DELAY
        if self._pending_reconcile:
            return

        old_snapshot = self.last_snapshot
        new_snapshot = self._build_snapshot()
        self.last_snapshot = new_snapshot
        self._save_cache()
        if old_snapshot:
            self._notify_changes(old_snapshot, new_snapshot)
            print(
                f"📊 Notified: files={new_snapshot.file_count:,}, "
                f"dirs={new_snapshot.dir_count:,}"
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
