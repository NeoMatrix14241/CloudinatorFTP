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

# Cache location — anchored to where this file lives (add cache/ to .gitignore)
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'storage_index.json')

# Reconciliation interval
RECONCILE_INTERVAL = 900  # 15 minutes


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
        self.debounce_delay = 2.0

    def _schedule_notify(self):
        if self.debounce_timer:
            self.debounce_timer.cancel()
        self.debounce_timer = threading.Timer(
            self.debounce_delay,
            self.monitor._notify_and_save
        )
        self.debounce_timer.start()

    def on_created(self, event):
        if '.chunks' in event.src_path:
            return

        src_rel = _rel(event.src_path, str(self.monitor.root_path))

        with self.monitor.lock:
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

                # Update dir_info for every parent folder up to root
                parent_rel = _rel(os.path.dirname(event.src_path), str(self.monitor.root_path))
                if parent_rel in self.monitor._dir_info:
                    self.monitor._dir_info[parent_rel]['file_count'] += 1
                    self.monitor._dir_info[parent_rel]['total_size'] += file_size
                for ancestor in _parents(parent_rel):
                    if ancestor in self.monitor._dir_info:
                        self.monitor._dir_info[ancestor]['total_size'] += file_size

        print(f"⚡ Created: {'dir' if event.is_directory else 'file'} '{src_rel}' → "
              f"files={self.monitor._file_count:,}, dirs={self.monitor._dir_count:,}")
        self._schedule_notify()

    def on_deleted(self, event):
        if '.chunks' in event.src_path:
            return

        src_rel = _rel(event.src_path, str(self.monitor.root_path))

        with self.monitor.lock:
            if event.is_directory:
                # Remove folder and all children from dir_info
                removed_size = 0
                removed_dirs = 0
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
                self.monitor._total_size = max(0, self.monitor._total_size - removed_size)

                # Update parent dir_count and total_size
                for parent in _parents(src_rel):
                    if parent in self.monitor._dir_info:
                        self.monitor._dir_info[parent]['dir_count'] = max(
                            0, self.monitor._dir_info[parent]['dir_count'] - 1
                        )
                        self.monitor._dir_info[parent]['total_size'] = max(
                            0, self.monitor._dir_info[parent]['total_size'] - removed_size
                        )
            else:
                # Deleted file — we don't know the size, reconcile will fix total_size
                # But we can update file counts immediately
                self.monitor._file_count = max(0, self.monitor._file_count - 1)

                parent_rel = _rel(os.path.dirname(event.src_path), str(self.monitor.root_path))
                if parent_rel in self.monitor._dir_info:
                    self.monitor._dir_info[parent_rel]['file_count'] = max(
                        0, self.monitor._dir_info[parent_rel]['file_count'] - 1
                    )
                # Size drift is corrected by 15min reconcile

        print(f"⚡ Deleted: {'dir' if event.is_directory else 'file'} '{src_rel}' → "
              f"files={self.monitor._file_count:,}, dirs={self.monitor._dir_count:,}")
        self._schedule_notify()

    def on_moved(self, event):
        if '.chunks' in event.src_path and '.chunks' in event.dest_path:
            return

        src_rel = _rel(event.src_path, str(self.monitor.root_path))
        dest_rel = _rel(event.dest_path, str(self.monitor.root_path))

        with self.monitor.lock:
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

        print(f"⚡ Moved: '{src_rel}' → '{dest_rel}'")
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

        # Pre-seed root
        dir_info[''] = {'file_count': 0, 'dir_count': 0, 'total_size': 0}

        try:
            for root, dirs, files in os.walk(str(self.root_path), topdown=True):
                # Skip chunk temp directory
                if '.chunks' in dirs:
                    dirs.remove('.chunks')

                root_rel = _rel(root, str(self.root_path))

                # Ensure this dir exists in index
                if root_rel not in dir_info:
                    dir_info[root_rel] = {'file_count': 0, 'dir_count': 0, 'total_size': 0}

                # Register immediate subdirs
                for d in dirs:
                    if d.startswith('.'):
                        continue
                    sub_rel = (root_rel + '/' + d) if root_rel else d
                    if sub_rel not in dir_info:
                        dir_info[sub_rel] = {'file_count': 0, 'dir_count': 0, 'total_size': 0}
                    dir_info[root_rel]['dir_count'] += 1
                    dir_count += 1

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

                        # Bubble size up to all ancestors
                        for ancestor in _parents(root_rel):
                            if ancestor in dir_info:
                                dir_info[ancestor]['total_size'] += fsize

                    except (OSError, IOError):
                        continue

        except Exception as e:
            print(f"❌ Error during filesystem walk: {e}")

        if not silent:
            elapsed = time.time() - walk_start
            print(f"✅ Walk + index complete in {elapsed:.1f}s: "
                  f"{file_count:,} files, {dir_count:,} dirs, "
                  f"{total_size / (1024**3):.2f} GB, "
                  f"{len(dir_info):,} folders indexed")

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

    def _reconcile(self):
        print("🔄 Background reconciliation walk starting...")
        result = self._full_walk(silent=True)
        old_snapshot = self._build_snapshot()

        with self.lock:
            self._file_count = result['file_count']
            self._dir_count = result['dir_count']
            self._total_size = result['total_size']
            self._last_modified = result['last_modified']
            self._dir_info = result['dir_info']

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
