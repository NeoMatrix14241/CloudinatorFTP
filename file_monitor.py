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

# Cache location — anchored to where this file lives (add cache/ to .gitignore)
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'storage_index.json')

# Reconciliation interval
RECONCILE_INTERVAL = 900  # 15 minutes
# How long to suppress watchdog counter updates after a bulk-op reconcile
SETTLE_DELAY = 2.0  # seconds
# Burst detection: if this many on_created events arrive within BURST_WINDOW seconds
# the handler auto-arms the settle (same as an explicit bulk_copy reconcile does).
BURST_THRESHOLD = 50   # events
BURST_WINDOW    = 3.0  # seconds


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
    if rel == '.':
        return ''
    return rel.replace('\\', '/')


def _parents(rel_path: str):
    """
    Yield all parent relative paths from closest to root.
    e.g. 'a/b/c' → ['a/b', 'a', '']
    """
    parts = rel_path.split('/')
    for i in range(len(parts) - 1, 0, -1):
        yield '/'.join(parts[:i])
    yield ''  # root always gets updated


class InstantFileEventHandler(FileSystemEventHandler):
    """
    Handles watchdog events.
    Updates in-memory counters AND dir_info cache directly — no walking.
    """

    def __init__(self, monitor):
        self.monitor = monitor
        self.debounce_timer = None
        self.debounce_delay = 0.5   # Fire SSE 0.5s after last change (was 2.0s)
        self.debounce_lock = threading.Lock()
        self._first_change_time = None  # For max_wait enforcement
        # Burst detection: if more than BURST_THRESHOLD on_created events arrive
        # within BURST_WINDOW seconds, treat it as a bulk op and arm the settle.
        self._burst_count = 0
        self._burst_window_start = 0.0
        self._burst_armed = False    # True once settle has been armed for this burst

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
            print(f"⚡ Burst detected ({self._burst_count} events in "
                  f"{now - self._burst_window_start:.1f}s) — arming settle reconcile")
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
                    self.debounce_delay,
                    self.monitor._notify_and_save
                )
            self.debounce_timer.start()

    def on_created(self, event):
        # Skip hidden files/dirs (matches _full_walk) and anything inside .chunks
        _name = os.path.basename(event.src_path)
        if _name.startswith('.') or '.chunks' in event.src_path:
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
                        'file_count': 0, 'dir_count': 0, 'total_size': 0
                    }
                # Update parent dir_count
                for parent in _parents(src_rel):
                    if parent in self.monitor._dir_info:
                        self.monitor._dir_info[parent]['dir_count'] += 1
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
                parent_rel = _rel(os.path.dirname(event.src_path), str(self.monitor.root_path))
                if parent_rel in self.monitor._dir_info:
                    self.monitor._dir_info[parent_rel]['file_count'] += 1
                    self.monitor._dir_info[parent_rel]['total_size'] += file_size
                for ancestor in _parents(parent_rel):
                    if ancestor in self.monitor._dir_info:
                        self.monitor._dir_info[ancestor]['file_count'] += 1
                        self.monitor._dir_info[ancestor]['total_size'] += file_size

        # --- file index: re-scan the parent folder (outside monitor lock) ---
        _parent_abs = os.path.dirname(event.src_path)
        _parent_rel = _rel(_parent_abs, str(self.monitor.root_path))
        file_index_manager.update_folder(_parent_rel, _parent_abs)
        # If a new subdirectory was created, seed it in the index (starts empty,
        # update_folder will skip it; it will be added once it exceeds threshold)
        if event.is_directory:
            file_index_manager.update_folder(src_rel, event.src_path)

        # Auto-arm settle if this looks like a bulk copy from outside the web UI
        if not event.is_directory:
            self._check_burst()

        self._schedule_notify()

    def on_deleted(self, event):
        # Skip hidden files/dirs (matches _full_walk) and anything inside .chunks
        _name = os.path.basename(event.src_path)
        if _name.startswith('.') or '.chunks' in event.src_path:
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
                    k for k in self.monitor._dir_info
                    if k == src_rel or k.startswith(src_rel + '/')
                ]
                for k in keys_to_remove:
                    entry = self.monitor._dir_info.pop(k, {})
                    if k == src_rel:
                        removed_size = entry.get('total_size', 0)
                        removed_dirs = 1 + entry.get('dir_count', 0)
                        removed_files = entry.get('file_count', 0)

                self.monitor._dir_count = max(0, self.monitor._dir_count - removed_dirs)
                self.monitor._file_count = max(0, self.monitor._file_count - removed_files)
                self.monitor._total_size = max(0, self.monitor._total_size - removed_size)

                # Bubble all three counts up to all ancestors
                for parent in _parents(src_rel):
                    if parent in self.monitor._dir_info:
                        self.monitor._dir_info[parent]['dir_count'] = max(
                            0, self.monitor._dir_info[parent]['dir_count'] - removed_dirs
                        )
                        self.monitor._dir_info[parent]['file_count'] = max(
                            0, self.monitor._dir_info[parent]['file_count'] - removed_files
                        )
                        self.monitor._dir_info[parent]['total_size'] = max(
                            0, self.monitor._dir_info[parent]['total_size'] - removed_size
                        )
            else:
                # Deleted file — bubble file_count down from all ancestors
                self.monitor._file_count = max(0, self.monitor._file_count - 1)

                parent_rel = _rel(os.path.dirname(event.src_path), str(self.monitor.root_path))
                if parent_rel in self.monitor._dir_info:
                    self.monitor._dir_info[parent_rel]['file_count'] = max(
                        0, self.monitor._dir_info[parent_rel]['file_count'] - 1
                    )
                for ancestor in _parents(parent_rel):
                    if ancestor in self.monitor._dir_info:
                        self.monitor._dir_info[ancestor]['file_count'] = max(
                            0, self.monitor._dir_info[ancestor]['file_count'] - 1
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

        self._schedule_notify()

    def on_moved(self, event):
        # Skip hidden files/dirs (matches _full_walk) and pure .chunks-to-.chunks moves
        _src_name = os.path.basename(event.src_path)
        _dst_name = os.path.basename(event.dest_path)
        if (_src_name.startswith('.') and _dst_name.startswith('.')) or \
           ('.chunks' in event.src_path and '.chunks' in event.dest_path):
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
                    k for k in list(self.monitor._dir_info.keys())
                    if k == src_rel or k.startswith(src_rel + '/')
                ]
                for old_key in keys_to_migrate:
                    new_key = dest_rel + old_key[len(src_rel):]
                    self.monitor._dir_info[new_key] = self.monitor._dir_info.pop(old_key)

                # Update old parent dir_count down, new parent dir_count up
                for parent in _parents(src_rel):
                    if parent in self.monitor._dir_info:
                        self.monitor._dir_info[parent]['dir_count'] = max(
                            0, self.monitor._dir_info[parent]['dir_count'] - 1
                        )
                for parent in _parents(dest_rel):
                    if parent in self.monitor._dir_info:
                        self.monitor._dir_info[parent]['dir_count'] += 1
            else:
                # File renamed/moved
                src_parent = _rel(os.path.dirname(event.src_path), str(self.monitor.root_path))
                dest_parent = _rel(os.path.dirname(event.dest_path), str(self.monitor.root_path))

                if src_parent != dest_parent:
                    # Moving to a different folder — transfer file count between parents
                    try:
                        file_size = os.path.getsize(event.dest_path)
                    except OSError:
                        file_size = 0

                    if src_parent in self.monitor._dir_info:
                        self.monitor._dir_info[src_parent]['file_count'] = max(
                            0, self.monitor._dir_info[src_parent]['file_count'] - 1
                        )
                        self.monitor._dir_info[src_parent]['total_size'] = max(
                            0, self.monitor._dir_info[src_parent]['total_size'] - file_size
                        )
                    if dest_parent in self.monitor._dir_info:
                        self.monitor._dir_info[dest_parent]['file_count'] += 1
                        self.monitor._dir_info[dest_parent]['total_size'] += file_size

        # --- file index: rename dir keys or update both parent folders ---
        if event.is_directory:
            file_index_manager.rename_folder(src_rel, dest_rel)
            # Both old and new parent folders changed their direct entry list
            _src_parent_abs  = os.path.dirname(event.src_path)
            _dest_parent_abs = os.path.dirname(event.dest_path)
            _src_parent_rel  = _rel(_src_parent_abs,  str(self.monitor.root_path))
            _dest_parent_rel = _rel(_dest_parent_abs, str(self.monitor.root_path))
            file_index_manager.update_folder(_src_parent_rel,  _src_parent_abs)
            if _src_parent_rel != _dest_parent_rel:
                file_index_manager.update_folder(_dest_parent_rel, _dest_parent_abs)
        else:
            _src_parent_abs  = os.path.dirname(event.src_path)
            _dest_parent_abs = os.path.dirname(event.dest_path)
            _src_parent_rel  = _rel(_src_parent_abs,  str(self.monitor.root_path))
            _dest_parent_rel = _rel(_dest_parent_abs, str(self.monitor.root_path))
            file_index_manager.update_folder(_src_parent_rel, _src_parent_abs)
            if _src_parent_rel != _dest_parent_rel:
                file_index_manager.update_folder(_dest_parent_rel, _dest_parent_abs)

        self._schedule_notify()

    def on_modified(self, event):
        # File content changed — size may have changed, let reconcile handle it
        if '.chunks' in event.src_path or event.is_directory:
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
        self._save_lock = threading.Lock()   # serialises writes to storage_index.json
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

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def add_change_callback(self, callback: Callable):
        with self.lock:
            self.change_callbacks.add(callback)

    def remove_change_callback(self, callback: Callable):
        with self.lock:
            self.change_callbacks.discard(callback)

    def _notify_changes(self, old_snapshot: StorageSnapshot, new_snapshot: StorageSnapshot):
        with self.lock:
            callbacks = list(self.change_callbacks)
        for cb in callbacks:
            try:
                cb(old_snapshot, new_snapshot)
            except Exception as e:
                print(f"❌ Error in change callback: {e}")

    # ------------------------------------------------------------------
    # Cache load / save
    # ------------------------------------------------------------------

    def _load_cache(self) -> bool:
        try:
            if not os.path.exists(CACHE_FILE):
                print(f"📂 No cache found at {CACHE_FILE} — will do initial walk")
                return False

            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._file_count = int(data.get('file_count', 0))
            self._dir_count = int(data.get('dir_count', 0))
            self._total_size = int(data.get('total_size', 0))
            self._last_modified = float(data.get('last_modified', 0))
            self._dir_info = data.get('dir_info', {})

            print(f"✅ Loaded cache: {self._file_count:,} files, "
                  f"{self._dir_count:,} dirs, "
                  f"{self._total_size / (1024**3):.2f} GB, "
                  f"{len(self._dir_info):,} folders indexed")

            # Load the companion file index
            file_index_manager.load()
            return True

        except Exception as e:
            print(f"⚠️ Failed to load cache: {e} — will do initial walk")
            self._dir_info = {}
            return False

    def _save_cache(self):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            data = {
                'file_count': self._file_count,
                'dir_count': self._dir_count,
                'total_size': self._total_size,
                'last_modified': self._last_modified,
                'dir_info': self._dir_info,
                'saved_at': time.time()
            }
            tmp = CACHE_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f)
            os.replace(tmp, CACHE_FILE)
        except Exception as e:
            print(f"⚠️ Failed to save cache: {e}")

        # Keep file_index.json in sync with storage_index.json
        file_index_manager.save()

    # ------------------------------------------------------------------
    # Full walk — first boot or reconcile
    # ------------------------------------------------------------------

    def _full_walk(self, silent: bool = False) -> dict:
        """
        Walk entire filesystem in one pass.
        Builds global counters AND dir_info for every folder simultaneously.
        Only called on first boot (no cache) or every 15 minutes for reconciliation.
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
        dir_info[''] = {'file_count': 0, 'dir_count': 0, 'total_size': 0}
        direct_entries[''] = []

        try:
            for root, dirs, files in os.walk(str(self.root_path), topdown=True):
                # Skip chunk temp directory
                if '.chunks' in dirs:
                    dirs.remove('.chunks')

                root_rel = _rel(root, str(self.root_path))

                # Ensure this dir exists in index
                if root_rel not in dir_info:
                    dir_info[root_rel] = {'file_count': 0, 'dir_count': 0, 'total_size': 0}
                if root_rel not in direct_entries:
                    direct_entries[root_rel] = []

                # Register immediate subdirs and bubble dir_count up to all ancestors
                for d in dirs:
                    if d.startswith('.'):
                        continue
                    sub_rel = (root_rel + '/' + d) if root_rel else d
                    if sub_rel not in dir_info:
                        dir_info[sub_rel] = {'file_count': 0, 'dir_count': 0, 'total_size': 0}
                    if sub_rel not in direct_entries:
                        direct_entries[sub_rel] = []
                    dir_info[root_rel]['dir_count'] += 1
                    dir_count += 1
                    # Bubble dir count up to all ancestors
                    for ancestor in _parents(root_rel):
                        if ancestor in dir_info:
                            dir_info[ancestor]['dir_count'] += 1
                    # Record subdir as a direct entry of root_rel (for file index)
                    d_path = os.path.join(root, d)
                    try:
                        d_mtime = os.stat(d_path).st_mtime
                    except OSError:
                        d_mtime = None
                    direct_entries[root_rel].append({
                        'name': d, 'is_dir': True, 'size': None, 'modified': d_mtime
                    })

                # Count files in this directory
                for fname in files:
                    if fname.startswith('.'):
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

                        # Add file to immediate parent
                        dir_info[root_rel]['file_count'] += 1
                        dir_info[root_rel]['total_size'] += fsize

                        # Bubble file_count and size up to all ancestors
                        for ancestor in _parents(root_rel):
                            if ancestor in dir_info:
                                dir_info[ancestor]['file_count'] += 1
                                dir_info[ancestor]['total_size'] += fsize

                        # Record as a direct entry of root_rel (for file index)
                        direct_entries[root_rel].append({
                            'name': fname, 'is_dir': False,
                            'size': fsize, 'modified': fmtime,
                        })

                    except (OSError, IOError):
                        continue

                # Sort direct_entries for root_rel now that all children are known
                direct_entries[root_rel].sort(
                    key=lambda x: (not x['is_dir'], x['name'].lower())
                )

        except Exception as e:
            print(f"❌ Error during filesystem walk: {e}")

        if not silent:
            elapsed = time.time() - walk_start
            print(f"✅ Walk + index complete in {elapsed:.1f}s: "
                  f"{file_count:,} files, {dir_count:,} dirs, "
                  f"{total_size / (1024**3):.2f} GB, "
                  f"{len(dir_info):,} folders indexed")

        # Build file_index.json for folders exceeding the direct-entry threshold
        file_index_manager.build_from_walk(direct_entries)

        return {
            'file_count': file_count,
            'dir_count': dir_count,
            'total_size': total_size,
            'last_modified': latest_mtime,
            'dir_info': dir_info
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
            self._settle_timer = threading.Timer(SETTLE_DELAY, self._settle_reconcile)
            self._settle_timer.daemon = True
            self._settle_timer.start()
        print(f"🔄 Settle reconcile armed — counter updates suppressed for {SETTLE_DELAY}s")

    def _settle_reconcile(self):
        """Fired by the hard timer — ground-truth walk after suppression window."""
        print("🔄 Settle reconcile firing (hard timer expired)")
        try:
            from realtime_stats import trigger_storage_update
            old_snap = self.last_snapshot
            self._reconcile()           # clears _pending_reconcile, bumps epoch
            new_snap = self.last_snapshot
            # Force-push SSE regardless of drift so UI always reflects reality
            trigger_storage_update(old_snap, new_snap)
        except Exception as e:
            print(f"⚠️ Settle reconcile error: {e}")
        finally:
            with self._settle_lock:
                self._settle_timer = None

    def _reconcile(self):
        print("🔄 Background reconciliation walk starting...")
        # Clear the pending flag before the walk so new events arriving during
        # the walk are counted normally (epoch guard handles in-flight ones).
        with self.lock:
            self._pending_reconcile = False
        result = self._full_walk(silent=True)
        old_snapshot = self._build_snapshot()

        with self.lock:
            self._file_count = result['file_count']
            self._dir_count = result['dir_count']
            self._total_size = result['total_size']
            self._last_modified = result['last_modified']
            self._dir_info = result['dir_info']
            # Bump AFTER writing corrected counters, not before the walk.
            # Events that snapshotted epoch before this lock acquisition will now
            # see a mismatch and skip their increment — preventing post-reconcile
            # overshoot from the watchdog backlog draining after the walk finishes.
            self._reconcile_epoch += 1

        new_snapshot = self._build_snapshot()
        self.last_snapshot = new_snapshot
        self._save_cache()

        if (old_snapshot.file_count != new_snapshot.file_count or
                old_snapshot.dir_count != new_snapshot.dir_count or
                old_snapshot.total_size != new_snapshot.total_size):
            print(f"🔄 Reconciliation corrected drift: "
                  f"files {old_snapshot.file_count}→{new_snapshot.file_count}, "
                  f"dirs {old_snapshot.dir_count}→{new_snapshot.dir_count}")
            self._notify_changes(old_snapshot, new_snapshot)
        else:
            print("✅ Reconciliation complete — no drift detected")

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
            timestamp=time.time()
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
            print(f"📊 Notified: files={new_snapshot.file_count:,}, "
                  f"dirs={new_snapshot.dir_count:,}")

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

        if not cache_loaded:
            result = self._full_walk()
            with self.lock:
                self._file_count = result['file_count']
                self._dir_count = result['dir_count']
                self._total_size = result['total_size']
                self._last_modified = result['last_modified']
                self._dir_info = result['dir_info']
            self._save_cache()

        self.last_snapshot = self._build_snapshot()
        print(f"📸 Snapshot ready: {self.last_snapshot.file_count:,} files, "
              f"{self.last_snapshot.dir_count:,} dirs, "
              f"{len(self._dir_info):,} folders indexed")

        # Start watchdog
        try:
            self.event_handler = InstantFileEventHandler(self)
            self.observer = Observer()
            self.observer.schedule(self.event_handler, str(self.root_path), recursive=True)
            self.observer.start()
            print("⚡ Watchdog started — instant change detection active")
        except Exception as e:
            print(f"⚠️ Failed to start watchdog: {e}")

        # Start reconcile thread
        self.reconcile_thread = threading.Thread(
            target=self._reconcile_loop, daemon=True, name="reconcile-thread"
        )
        self.reconcile_thread.start()
        print(f"🔄 Reconciliation every {RECONCILE_INTERVAL // 60} minutes")

        # Post-startup reconcile to catch offline changes
        if cache_loaded:
            def delayed_reconcile():
                time.sleep(30)
                if self.monitoring:
                    print("🔄 Post-startup reconciliation (catching offline changes)...")
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
        rel_path = rel_path.replace('\\', '/').strip('/')
        with self.lock:
            return self._dir_info.get(rel_path, None)

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
            target=self._reconcile,
            daemon=True,
            name="reconcile-on-demand"
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