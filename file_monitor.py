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
        self.debounce_delay = 0.1  # 100ms debounce for better stability
        
    def _trigger_change_check(self):
        """Trigger a change check after debounce delay"""
        if self.debounce_timer:
            self.debounce_timer.cancel()
        
        self.debounce_timer = threading.Timer(self.debounce_delay, self.file_monitor._handle_instant_change)
        self.debounce_timer.start()
    
    def on_modified(self, event):
        """Handle file/directory modifications"""
        # Trigger on both file and directory modifications
        self._trigger_change_check()
    
    def on_created(self, event):
        """Handle file/directory creation"""
        self._trigger_change_check()
    
    def on_deleted(self, event):
        """Handle file/directory deletion"""
        self._trigger_change_check()
    
    def on_moved(self, event):
        """Handle file/directory moves/renames"""
        # File moves and renames should trigger immediate updates
        self._trigger_change_check()

class FileSystemMonitor:
    """Efficient file system monitor that detects changes without constant scanning"""
    
    def __init__(self, root_path: str = ROOT_DIR, check_interval: int = 2, instant_mode: bool = True):
        self.root_path = Path(root_path)
        self.check_interval = check_interval
        self.instant_mode = instant_mode
        self.last_snapshot: Optional[StorageSnapshot] = None
        self.monitoring = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.change_callbacks: Set[Callable] = set()
        self.lock = threading.Lock()
        
        # Instant monitoring components
        self.observer = None
        self.event_handler = None
        self.pending_change = False
        self.change_event = threading.Event()  # Event to interrupt sleep for instant changes
        
        # Performance optimization: track known file extensions for quick type detection
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
            
        # Prevent duplicate processing of the same change
        current_time = time.time()
        if hasattr(self, '_last_instant_change') and (current_time - self._last_instant_change) < 0.5:
            print("⚡ Duplicate instant change ignored (debounced)")
            return
        
        self._last_instant_change = current_time
        
        # Set flag to trigger immediate check in polling loop
        self.pending_change = True
        self.change_event.set()  # Wake up the monitoring loop immediately
        print("⚡ Instant file change detected!")
    
    def _create_snapshot(self, for_comparison=False) -> StorageSnapshot:
        """Create a lightweight snapshot of the current storage state
        
        Args:
            for_comparison: If True, this snapshot is just for comparison and won't be stored
        """
        try:
            if not for_comparison:
                print(f"📸 Creating storage snapshot for: {self.root_path}")
            
            file_count = 0
            dir_count = 0
            total_size = 0
            latest_mtime = 0
            content_hash = hashlib.md5()
            
            # Use os.walk for better performance than pathlib
            all_files = []
            
            for root, dirs, files in os.walk(self.root_path):
                # Skip scanning temporary chunk directories (created during chunked uploads)
                # so that transient chunk files do not trigger storage-stat changes or notifications.
                # We remove '.chunks' from dirs to prevent os.walk from recursing into it.
                if '.chunks' in dirs:
                    try:
                        dirs.remove('.chunks')
                    except ValueError:
                        pass

                # Count directories (excluding any removed .chunks)
                dir_count += len(dirs)

                # Collect all files with their info
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        stat_info = os.stat(file_path)
                        file_size = stat_info.st_size
                        file_mtime = stat_info.st_mtime
                        
                        file_count += 1
                        total_size += file_size
                        latest_mtime = max(latest_mtime, file_mtime)
                        
                        # Store file info for sorted processing including mtime for better change detection
                        all_files.append((file_path, file_size, file_mtime))
                        
                    except (OSError, IOError) as e:
                        # Skip files we can't access
                        print(f"⚠️ Skipping inaccessible file: {file_path} - {e}")
                        continue
            
            # Sort files by path to ensure consistent checksum
            all_files.sort(key=lambda x: x[0])
            
            # Create comprehensive checksum including path, size, and modification time
            for file_path, file_size, file_mtime in all_files:
                # Round mtime to seconds to avoid float precision issues
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
                print(f"📸 Snapshot created: {file_count} files, {dir_count} dirs, {total_size:,} bytes")
                print(f"🔍 Debug - Actual files found: {len(all_files)}, Root path: {self.root_path}")
            
            return snapshot
            
        except Exception as e:
            print(f"❌ Error creating snapshot: {e}")
            # Return a default snapshot on error
            return StorageSnapshot(0, 0, 0, 0, "", time.time())
    
    def _has_changes(self, old_snapshot: StorageSnapshot, new_snapshot: StorageSnapshot) -> bool:
        """Check if there are meaningful changes between snapshots"""
        if old_snapshot is None:
            return True
        
        # Quick checks for obvious changes
        has_count_changes = (old_snapshot.file_count != new_snapshot.file_count or
                           old_snapshot.dir_count != new_snapshot.dir_count)
        
        has_size_changes = old_snapshot.total_size != new_snapshot.total_size
        
        # Check checksum for file content/structure changes (including renames and modifications)
        has_content_changes = old_snapshot.checksum != new_snapshot.checksum
        
        # Check modification time changes
        has_mtime_changes = old_snapshot.last_modified != new_snapshot.last_modified
        
        return has_count_changes or has_size_changes or has_content_changes or has_mtime_changes
    
    def _monitor_loop(self):
        """Main monitoring loop with adaptive interval"""
        print(f"🔍 File monitor started for: {self.root_path}")
        
        # Create initial snapshot
        if not self.last_snapshot:
            self.last_snapshot = self._create_snapshot()
        
        no_change_count = 0
        current_interval = self.check_interval
        
        while self.monitoring:
            try:
                # Check if instant change was detected
                instant_change_triggered = self.pending_change
                if instant_change_triggered:
                    self.pending_change = False
                    current_interval = self.check_interval  # Reset to fast interval
                    no_change_count = 0  # Reset no-change counter
                
                # Create new snapshot for comparison only (don't print creation message)
                new_snapshot = self._create_snapshot(for_comparison=True)
                
                # Check for actual changes
                if self._has_changes(self.last_snapshot, new_snapshot):
                    change_source = "⚡ instant detection" if instant_change_triggered else "🔍 polling"
                    print(f"📊 File system changes confirmed! ({change_source})")
                    
                    # Detailed change reporting
                    if self.last_snapshot:
                        if self.last_snapshot.file_count != new_snapshot.file_count:
                            print(f"   Files: {self.last_snapshot.file_count} → {new_snapshot.file_count}")
                        if self.last_snapshot.dir_count != new_snapshot.dir_count:
                            print(f"   Directories: {self.last_snapshot.dir_count} → {new_snapshot.dir_count}")
                        if self.last_snapshot.total_size != new_snapshot.total_size:
                            print(f"   Size: {self.last_snapshot.total_size:,} → {new_snapshot.total_size:,} bytes")
                        if self.last_snapshot.checksum != new_snapshot.checksum:
                            if (self.last_snapshot.file_count == new_snapshot.file_count and 
                                self.last_snapshot.dir_count == new_snapshot.dir_count and
                                self.last_snapshot.total_size == new_snapshot.total_size):
                                print(f"   Content: File modification/rename detected")
                            else:
                                print(f"   Content: Structure changes detected")
                        if self.last_snapshot.last_modified != new_snapshot.last_modified:
                            print(f"   Modified: {self.last_snapshot.last_modified:.0f} → {new_snapshot.last_modified:.0f}")
                    
                    # Print the actual snapshot creation message now
                    print(f"📸 Snapshot created: {new_snapshot.file_count} files, {new_snapshot.dir_count} dirs, {new_snapshot.total_size:,} bytes")
                    
                    # Notify callbacks about the change
                    if self.last_snapshot:
                        self._notify_changes(self.last_snapshot, new_snapshot)
                    
                    # Update last snapshot only when changes are detected
                    self.last_snapshot = new_snapshot
                    
                    # Reset to fast checking after change
                    no_change_count = 0
                    current_interval = self.check_interval
                else:
                    # No changes detected - don't update the snapshot
                    no_change_count += 1
                    
                    # In instant mode, use longer intervals since events will trigger immediate checks
                    if self.instant_mode:
                        # Scale up much faster in instant mode since we don't rely on polling
                        if no_change_count > 2:  # After just 4-6 seconds
                            current_interval = min(60, self.check_interval * 10)  # Much longer interval
                            if no_change_count % 30 == 0:  # Less frequent logging
                                print(f"🔍 No changes detected for {no_change_count * self.check_interval}s, using {current_interval}s interval (instant mode)")
                    else:
                        # Original adaptive behavior for polling-only mode
                        if no_change_count > 5:  # After 10 seconds of no changes
                            current_interval = min(30, self.check_interval * 3)  # Max 30s
                            if no_change_count % 10 == 0:  # Every 10 checks with no changes
                                print(f"🔍 No changes detected for {no_change_count * self.check_interval}s, using {current_interval}s interval")
                    
                    # Just update timestamp of existing snapshot
                    self.last_snapshot.timestamp = time.time()
                
            except Exception as e:
                print(f"❌ Error in monitor loop: {e}")
            
            # Wait for next check with adaptive interval, but wake up immediately on instant changes
            if self.change_event.wait(timeout=current_interval):
                # Event was set (instant change detected), clear it and continue immediately
                self.change_event.clear()
                print("🚀 Woke up early due to instant file change!")
            # If timeout expired normally, just continue with next iteration
        
        print("🔍 File monitor stopped")
    
    def start_monitoring(self):
        """Start the file system monitoring"""
        if self.monitoring:
            print("⚠️ File monitor is already running")
            return
        
        mode_desc = "instant + polling" if self.instant_mode else "polling only"
        print(f"🚀 Starting file system monitor ({mode_desc}, check interval: {self.check_interval}s)")
        
        self.monitoring = True
        
        # Setup instant monitoring if enabled
        if self.instant_mode:
            try:
                self.event_handler = InstantFileEventHandler(self)
                self.observer = Observer()
                self.observer.schedule(self.event_handler, str(self.root_path), recursive=True)
                self.observer.start()
                print("⚡ Instant file change detection enabled")
            except Exception as e:
                print(f"⚠️ Failed to setup instant monitoring, falling back to polling: {e}")
                self.instant_mode = False
        
        # Start the monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop the file system monitoring"""
        if not self.monitoring:
            return
        
        print("🛑 Stopping file system monitor")
        self.monitoring = False
        
        # Stop instant monitoring
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=2)
            self.observer = None
            self.event_handler = None
        
        # Stop polling thread
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
