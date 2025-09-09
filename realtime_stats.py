#!/usr/bin/env python3
"""
Real-time Storage Stats Broadcasting
Handles WebSocket connections and Server-Sent Events for live storage updates
"""

import json
import time
import threading
from flask import request, Response
from queue import Queue, Empty
from typing import Dict, Set
from dataclasses import asdict

class StorageStatsEventManager:
    """Manages real-time storage stats broadcasting to connected clients"""
    
    def __init__(self):
        self.clients: Set[Queue] = set()
        self.lock = threading.Lock()
        self.last_stats = None
        
    def add_client(self, client_queue: Queue):
        """Add a new client to receive updates"""
        with self.lock:
            self.clients.add(client_queue)
            print(f"📡 Client connected. Total clients: {len(self.clients)}")
    
    def remove_client(self, client_queue: Queue):
        """Remove a client from updates"""
        with self.lock:
            self.clients.discard(client_queue)
            print(f"📡 Client disconnected. Total clients: {len(self.clients)}")
    
    def broadcast_update(self, old_snapshot, new_snapshot):
        """Broadcast storage stats update to all connected clients"""
        try:
            # Get fast disk usage stats (without expensive file counting)
            disk_stats = self._get_fast_disk_stats()
            
            # Prepare the update data with complete storage information
            update_data = {
                'type': 'storage_stats_update',
                'timestamp': time.time(),
                'data': {
                    # File/directory counts from snapshot (instant)
                    'file_count': new_snapshot.file_count,
                    'dir_count': new_snapshot.dir_count,
                    'total_size': new_snapshot.total_size,
                    'content_size': new_snapshot.total_size,  # Alias for compatibility
                    'last_modified': new_snapshot.last_modified,
                    
                    # Disk usage stats (fast disk check)
                    'total_space': disk_stats['total_space'],
                    'free_space': disk_stats['free_space'], 
                    'used_space': disk_stats['used_space'],
                    
                    # Change information
                    'changes': {
                        'files_changed': new_snapshot.file_count - (old_snapshot.file_count if old_snapshot else 0),
                        'dirs_changed': new_snapshot.dir_count - (old_snapshot.dir_count if old_snapshot else 0),
                        'size_changed': new_snapshot.total_size - (old_snapshot.total_size if old_snapshot else 0),
                        'content_changed': old_snapshot.checksum != new_snapshot.checksum if old_snapshot else True,
                        'mtime_changed': old_snapshot.last_modified != new_snapshot.last_modified if old_snapshot else True,
                    }
                }
            }
            
            self.last_stats = update_data
            
            # Broadcast to all clients
            with self.lock:
                disconnected_clients = set()
                for client_queue in self.clients:
                    try:
                        # Non-blocking put with timeout
                        client_queue.put(update_data, timeout=0.1)
                    except:
                        # Client queue is full or closed, mark for removal
                        disconnected_clients.add(client_queue)
                
                # Remove disconnected clients
                for client in disconnected_clients:
                    self.clients.discard(client)
                
                if disconnected_clients:
                    print(f"📡 Removed {len(disconnected_clients)} disconnected clients")
            
            print(f"📡 Broadcasted storage update to {len(self.clients)} clients")
            print(f"🔍 Update data includes: files={update_data['data']['file_count']}, dirs={update_data['data']['dir_count']}, total_space={update_data['data']['total_space']}, free_space={update_data['data']['free_space']}")
            
        except Exception as e:
            print(f"❌ Error broadcasting update: {e}")
    
    def get_last_stats(self):
        """Get the last broadcasted stats"""
        return self.last_stats
    
    def get_client_count(self):
        """Get the number of connected clients"""
        with self.lock:
            return len(self.clients)
    
    def _get_fast_disk_stats(self):
        """Get fast disk usage stats without expensive file counting"""
        import os
        import shutil
        from config import ROOT_DIR
        
        try:
            # Determine the best path for disk usage calculation
            disk_usage_path = ROOT_DIR
            
            # Special handling for Android/Termux
            if 'TERMUX_VERSION' in os.environ or os.path.exists('/data/data/com.termux'):
                android_storage_paths = [
                    '/storage/emulated/0',
                    '/sdcard',
                    '/storage/self/primary'
                ]
                
                for path in android_storage_paths:
                    if os.path.exists(path) and os.access(path, os.R_OK):
                        disk_usage_path = path
                        break
            
            # Get disk usage only
            if hasattr(os, 'statvfs'):  # Unix-like systems
                try:
                    stat = os.statvfs(disk_usage_path)
                    total = stat.f_blocks * stat.f_frsize
                    free = stat.f_bavail * stat.f_frsize
                    used = total - free
                except OSError:
                    # Fallback to shutil
                    total, used, free = shutil.disk_usage(disk_usage_path)
            else:  # Windows
                total, used, free = shutil.disk_usage(ROOT_DIR)
            
            return {
                'total_space': total,
                'used_space': used,
                'free_space': free
            }
            
        except Exception as e:
            print(f"❌ Error getting fast disk stats: {e}")
            return {
                'total_space': 0,
                'used_space': 0,
                'free_space': 0
            }

# Global event manager
event_manager = StorageStatsEventManager()

def storage_stats_sse():
    """Server-Sent Events endpoint for real-time storage stats - Waitress compatible"""
    from flask import request
    
    def event_stream():
        client_queue = Queue(maxsize=50)
        event_manager.add_client(client_queue)
        
        try:
            # Send initial connection message with proper SSE format (as bytes for Waitress)
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': time.time()})}\n\n".encode('utf-8')
            
            # Always send complete initial stats when client connects
            from file_monitor import get_file_monitor
            file_monitor = get_file_monitor()
            current_snapshot = file_monitor.get_current_snapshot()
            
            # Provide instant stats - don't wait for slow force_check
            if current_snapshot:
                print("� Using cached snapshot for instant SSE response")
                file_count = current_snapshot.file_count
                dir_count = current_snapshot.dir_count
                total_size = current_snapshot.total_size
                last_modified = current_snapshot.last_modified
            else:
                print("📡 No snapshot available, providing instant placeholder stats")
                file_count = 0
                dir_count = 0
                total_size = 0
                last_modified = time.time()
            
            # Get complete initial storage stats (disk stats are fast)
            disk_stats = event_manager._get_fast_disk_stats()
            
            initial_stats = {
                'type': 'storage_stats_update',
                'timestamp': time.time(),
                'initial': True,
                'data': {
                    'file_count': file_count,
                    'dir_count': dir_count,
                    'total_size': total_size,
                    'content_size': total_size,
                    'last_modified': last_modified,
                    'total_space': disk_stats['total_space'],
                    'free_space': disk_stats['free_space'],
                    'used_space': disk_stats['used_space'],
                    'changes': {'files_changed': 0, 'dirs_changed': 0, 'size_changed': 0}
                }
            }
            
            print(f"📡 Sending instant initial storage stats to new client: files={initial_stats['data']['file_count']}, total_space={initial_stats['data']['total_space']}")
            yield f"data: {json.dumps(initial_stats)}\n\n".encode('utf-8')
            
            # Keep connection alive and send updates
            while True:
                try:
                    data = client_queue.get(timeout=10)
                    yield f"data: {json.dumps(data)}\n\n".encode('utf-8')
                except Empty:
                    yield f"data: {json.dumps({'type': 'ping', 'timestamp': time.time()})}\n\n".encode('utf-8')
                except Exception as e:
                    print(f"❌ Error in SSE stream: {e}")
                    break
                    
        finally:
            event_manager.remove_client(client_queue)
            print(f"📡 SSE client cleanup completed")

    # Create response with Waitress-specific SSE headers
    from flask import Response
    response = Response(
        event_stream(),
        mimetype='text/event-stream'
    )
    
    # Essential headers for Waitress SSE compatibility (no hop-by-hop headers!)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    # DO NOT SET Connection header - it's handled by WSGI server
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['X-Accel-Buffering'] = 'no'  # Disable nginx buffering if behind proxy
    
    # Critical for Waitress: disable response buffering
    response.direct_passthrough = True
    
    return response

def trigger_storage_update(old_snapshot, new_snapshot):
    """Callback function to be registered with file monitor"""
    event_manager.broadcast_update(old_snapshot, new_snapshot)

def get_event_manager():
    """Get the global event manager"""
    return event_manager
