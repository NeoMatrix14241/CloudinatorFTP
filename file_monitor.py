#!/usr/bin/env python3
"""
File System Monitor for CloudinatorFTP
Efficiently monitors file system changes and triggers storage stats updates
"""

import os
import time
import threading
import hashlib
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Set, Optional, Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from config import ROOT_DIR

@dataclass
class StorageSnapshot:
    """Lightweight snapshot of storage state"""
    file_count: int
    dir_count: int
    total_size: int
    last_modified: float
    checksum: str
    timestamp: float

class InstantFileEventHandler(FileSystemEventHandler):
    """Handles file system events for instant change detection"""
    
    def __init__(self, file_monitor):
        self.file_monitor = file_monitor
        self.debounce_timer = None
        self.debounce_delay = 2.0  # Increased to 2 seconds to wait for file operations to complete
        
    def _trigger_change_check(self):
        """Trigger a change check after debounce delay"""
        if self.debounce_timer:
            self.debounce_timer.cancel()
        
        self.debounce_timer = threading.Timer(
            self.debounce_delay, 
            self.file_monitor._handle_instant_change
        )
        self.debounce_timer.start()
    
    def on_modified(self, event):
        """Handle file/directory modifications"""
        self._trigger_change_check()
    
    def on_created(self, event):
        """Handle file/directory creation"""
        self._trigger_change_check()
    
    def on_deleted(self, event):
        """Handle file/directory deletion"""
        self._trigger_change_check()
    
    def on_moved(self, event):
        """Handle file/directory moves/renames"""
        self._trigger_change_check()

class FileSystemMonitor:
    """Efficient file system monitor that detects changes without constant scanning"""
    
    def __init__(self, root_path: str = ROOT_DIR, check_interval: int = 2, 
                 instant_mode: bool = True, stability_checks: int = 2):
        self.root_path = Path(root_path)
        self.check_interval = check_interval
        self.instant_mode = instant_mode
        self.stability_checks = stability_checks  # Number of consecutive identical checks before confirming
        self.last_snapshot: Optional[StorageSnapshot] = None
        self.monitoring = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.change_callbacks: Set[Callable] = set()
        self.lock = threading.Lock()
        
        # Instant monitoring components
        self.observer = None
        self.event_handler = None
        self.pending_change = False
        self.change_event = threading.Event()
        
        # Stability tracking
        self.pending_snapshot: Optional[StorageSnapshot] = None
        self.stability_counter = 0
        self.last_change_time = 0
        
        # Performance optimization
        self.known_extensions = {'.txt', '.pdf', '.jpg', '.png', '.mp4', '.zip', '.doc', '.exe'}
        
    def add_change_callback(self, callback: Callable):
        """Add a callback function to be called when changes are detected"""
        with self.lock:
            self.change_callbacks.add(callback)
    
    def remove_change_callback(self, callback: Callable):
        """Remove a callback function"""
        with self.lock:
            self.change_callbacks.discard(callback)
    
    def _notify_changes(self, old_snapshot: StorageSnapshot, new_snapshot: StorageSnapshot):
        """Notify all registered callbacks about changes"""
        with self.lock:
            for callback in self.change_callbacks:
                try:
                    callback(old_snapshot, new_snapshot)
                except Exception as e:
                    print(f"❌ Error in change callback: {e}")
    
    def _handle_instant_change(self):
        """Handle instant file system changes detected by watchdog"""
        if not self.monitoring:
            return
            
        current_time = time.time()
        
        # Always update last change time
        self.last_change_time = current_time
        
        # Reset stability counter since we detected a new change
        self.stability_counter = 0
        
        # Set flag to trigger immediate check in polling loop
        self.pending_change = True
        self.change_event.set()
        print("⚡ File change detected, waiting for operation to complete...")
    
    def _create_snapshot(self, for_comparison=False) -> StorageSnapshot:
        """Create a lightweight snapshot of the current storage state"""
        try:
            if not for_comparison:
                print(f"📸 Creating storage snapshot for: {self.root_path}")
            
            file_count = 0
            dir_count = 0
            total_size = 0
            latest_mtime = 0
            content_hash = hashlib.md5()
            
            all_files = []
            
            for root, dirs, files in os.walk(self.root_path):
                if '.chunks' in dirs:
                    try:
                        dirs.remove('.chunks')
                    except ValueError:
                        pass

                dir_count += len(dirs)

                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        stat_info = os.stat(file_path)
                        file_size = stat_info.st_size
                        file_mtime = stat_info.st_mtime
                        
                        file_count += 1
                        total_size += file_size
                        latest_mtime = max(latest_mtime, file_mtime)
                        
                        all_files.append((file_path, file_size, file_mtime))
                        
                    except (OSError, IOError) as e:
                        print(f"⚠️ Skipping inaccessible file: {file_path} - {e}")
                        continue
            
            all_files.sort(key=lambda x: x[0])
            
            for file_path, file_size, file_mtime in all_files:
                mtime_rounded = int(file_mtime)
                content_hash.update(f"{file_path}:{file_size}:{mtime_rounded}".encode())
            
            snapshot = StorageSnapshot(
                file_count=file_count,
                dir_count=dir_count,
                total_size=total_size,
                last_modified=latest_mtime,
                checksum=content_hash.hexdigest(),
                timestamp=time.time()
            )
            
            if not for_comparison:
                print(f"📸 Snapshot: {file_count} files, {dir_count} dirs, {total_size:,} bytes")
            
            return snapshot
            
        except Exception as e:
            print(f"❌ Error creating snapshot: {e}")
            return StorageSnapshot(0, 0, 0, 0, "", time.time())
    
    def _has_changes(self, old_snapshot: StorageSnapshot, new_snapshot: StorageSnapshot) -> bool:
        """Check if there are meaningful changes between snapshots"""
        if old_snapshot is None:
            return True
        
        has_count_changes = (old_snapshot.file_count != new_snapshot.file_count or
                           old_snapshot.dir_count != new_snapshot.dir_count)
        
        has_size_changes = old_snapshot.total_size != new_snapshot.total_size
        has_content_changes = old_snapshot.checksum != new_snapshot.checksum
        has_mtime_changes = old_snapshot.last_modified != new_snapshot.last_modified
        
        return has_count_changes or has_size_changes or has_content_changes or has_mtime_changes
    
    def _is_snapshot_stable(self, new_snapshot: StorageSnapshot) -> bool:
        """Check if the snapshot has been stable (unchanged) for required number of checks"""
        if self.pending_snapshot is None:
            # First check after change detected
            self.pending_snapshot = new_snapshot
            self.stability_counter = 1
            print(f"🔄 Change detected, verifying stability... (1/{self.stability_checks})")
            return False
        
        # Check if snapshot is identical to pending one
        if self.pending_snapshot.checksum == new_snapshot.checksum:
            self.stability_counter += 1
            print(f"✓ Stable check {self.stability_counter}/{self.stability_checks}")
            
            if self.stability_counter >= self.stability_checks:
                print("✅ File operation complete - storage stable!")
                return True
            return False
        else:
            # Snapshot changed, reset counter
            print(f"🔄 Still changing, resetting stability check...")
            self.pending_snapshot = new_snapshot
            self.stability_counter = 1
            return False
    
    def _monitor_loop(self):
        """Main monitoring loop with stability checks"""
        print(f"🔍 File monitor started for: {self.root_path}")
        
        if not self.last_snapshot:
            self.last_snapshot = self._create_snapshot()
        
        no_change_count = 0
        current_interval = self.check_interval
        
        while self.monitoring:
            try:
                instant_change_triggered = self.pending_change
                if instant_change_triggered:
                    self.pending_change = False
                    current_interval = self.check_interval
                    no_change_count = 0
                
                new_snapshot = self._create_snapshot(for_comparison=True)
                
                if self._has_changes(self.last_snapshot, new_snapshot):
                    # Changes detected, check if they're stable
                    if self._is_snapshot_stable(new_snapshot):
                        # Changes are stable, safe to notify
                        change_source = "⚡ instant detection" if instant_change_triggered else "🔍 polling"
                        print(f"\n{'='*60}")
                        print(f"📊 Storage Updated! ({change_source})")
                        print(f"{'='*60}")
                        
                        # Detailed change reporting
                        if self.last_snapshot:
                            if self.last_snapshot.file_count != new_snapshot.file_count:
                                print(f"   Files: {self.last_snapshot.file_count} → {new_snapshot.file_count}")
                            if self.last_snapshot.dir_count != new_snapshot.dir_count:
                                print(f"   Directories: {self.last_snapshot.dir_count} → {new_snapshot.dir_count}")
                            if self.last_snapshot.total_size != new_snapshot.total_size:
                                old_size_mb = self.last_snapshot.total_size / (1024 * 1024)
                                new_size_mb = new_snapshot.total_size / (1024 * 1024)
                                diff_mb = new_size_mb - old_size_mb
                                print(f"   Size: {old_size_mb:.2f} MB → {new_size_mb:.2f} MB ({diff_mb:+.2f} MB)")
                        
                        print(f"{'='*60}\n")
                        
                        # Notify callbacks
                        if self.last_snapshot:
                            self._notify_changes(self.last_snapshot, new_snapshot)
                        
                        # Update snapshot and reset stability tracking
                        self.last_snapshot = new_snapshot
                        self.pending_snapshot = None
                        self.stability_counter = 0
                        no_change_count = 0
                        current_interval = self.check_interval
                    else:
                        # Still changing, keep checking quickly
                        current_interval = 1  # Check every second during changes
                else:
                    # No changes from last confirmed snapshot
                    if self.pending_snapshot is not None:
                        # We were tracking changes but they reverted - reset
                        print("🔄 Changes reverted, resetting...")
                        self.pending_snapshot = None
                        self.stability_counter = 0
                    
                    no_change_count += 1
                    
                    if self.instant_mode:
                        if no_change_count > 2:
                            current_interval = min(60, self.check_interval * 10)
                    else:
                        if no_change_count > 5:
                            current_interval = min(30, self.check_interval * 3)
                    
                    self.last_snapshot.timestamp = time.time()
                
            except Exception as e:
                print(f"❌ Error in monitor loop: {e}")
            
            if self.change_event.wait(timeout=current_interval):
                self.change_event.clear()
            
        print("🔍 File monitor stopped")
    
    def start_monitoring(self):
        """Start the file system monitoring"""
        if self.monitoring:
            print("⚠️ File monitor is already running")
            return
        
        mode_desc = "instant + polling" if self.instant_mode else "polling only"
        print(f"🚀 Starting file system monitor ({mode_desc}, {self.stability_checks} stability checks)")
        
        self.monitoring = True
        
        if self.instant_mode:
            try:
                self.event_handler = InstantFileEventHandler(self)
                self.observer = Observer()
                self.observer.schedule(self.event_handler, str(self.root_path), recursive=True)
                self.observer.start()
                print("⚡ Instant file change detection enabled")
            except Exception as e:
                print(f"⚠️ Failed to setup instant monitoring: {e}")
                self.instant_mode = False
        
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop the file system monitoring"""
        if not self.monitoring:
            return
        
        print("🛑 Stopping file system monitor")
        self.monitoring = False
        
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=2)
            self.observer = None
            self.event_handler = None
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
    
    def force_check(self) -> Optional[StorageSnapshot]:
        """Force an immediate check for changes"""
        if not self.monitoring:
            print("⚠️ Monitor not running, starting check manually")
        
        new_snapshot = self._create_snapshot()
        
        if self._has_changes(self.last_snapshot, new_snapshot):
            print("📊 Manual check detected changes")
            if self.last_snapshot:
                self._notify_changes(self.last_snapshot, new_snapshot)
            self.last_snapshot = new_snapshot
        
        return new_snapshot
    
    def get_current_snapshot(self) -> Optional[StorageSnapshot]:
        """Get the current snapshot without checking for changes"""
        return self.last_snapshot
    
    def get_stats_dict(self) -> Dict:
        """Get current stats as a dictionary for API responses"""
        if self.last_snapshot:
            return asdict(self.last_snapshot)
        return {}

# Global file monitor instance
file_monitor = FileSystemMonitor()

def init_file_monitor():
    """Initialize and start the global file monitor"""
    global file_monitor
    if not file_monitor.monitoring:
        file_monitor.start_monitoring()
    return file_monitor

def get_file_monitor():
    """Get the global file monitor instance"""
    return file_monitor