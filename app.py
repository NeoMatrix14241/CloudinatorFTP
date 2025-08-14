from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session, jsonify
from werkzeug.utils import secure_filename
import os
import shutil
import json
import threading
import time
import logging
import uuid
from datetime import datetime
from config import PORT, ROOT_DIR, SESSION_SECRET, CHUNK_SIZE, ENABLE_CHUNKED_UPLOADS
from auth import check_login, login_user, logout_user, current_user, is_logged_in, get_role
import storage

app = Flask(__name__)
app.secret_key = SESSION_SECRET
storage.ensure_root()

# Add Jinja2 filter for timestamp formatting
@app.template_filter('timestamp_to_date')
def timestamp_to_date_filter(timestamp):
    """Convert Unix timestamp to readable date format"""
    try:
        dt = datetime.fromtimestamp(timestamp)
        # Format as mm/dd/yyyy HH:MM AM/PM
        return dt.strftime('%m/%d/%Y %I:%M %p')
    except (ValueError, OSError):
        return '--'

# Chunk Tracker Class for better session management
class ChunkTracker:
    def __init__(self):
        self.active_uploads = {}  # session_id -> set of file_ids
        self.lock = threading.Lock()
        self.upload_timestamps = {}  # file_id -> timestamp
    
    def track_upload(self, session_id, file_id):
        with self.lock:
            if session_id not in self.active_uploads:
                self.active_uploads[session_id] = set()
            self.active_uploads[session_id].add(file_id)
            self.upload_timestamps[file_id] = time.time()
            print(f"📊 Tracking upload: {file_id} for session {session_id}")
    
    def untrack_upload(self, session_id, file_id):
        with self.lock:
            if session_id in self.active_uploads:
                self.active_uploads[session_id].discard(file_id)
                if not self.active_uploads[session_id]:
                    del self.active_uploads[session_id]
            self.upload_timestamps.pop(file_id, None)
            print(f"📊 Untracked upload: {file_id} for session {session_id}")
    
    def cleanup_session_chunks(self, session_id):
        """Clean up all chunks for a session"""
        with self.lock:
            if session_id in self.active_uploads:
                file_ids = self.active_uploads[session_id].copy()
                for file_id in file_ids:
                    try:
                        storage.cleanup_chunks(file_id)
                        print(f"🧹 Cleaned up abandoned chunks for session {session_id}: {file_id}")
                    except Exception as e:
                        print(f"❌ Error cleaning up chunks for {file_id}: {e}")
                    self.upload_timestamps.pop(file_id, None)
                del self.active_uploads[session_id]
                print(f"🧹 Cleaned up all chunks for session: {session_id}")
    
    def cleanup_orphaned_chunks(self):
        """Find and cleanup chunks that don't belong to any active session"""
        chunks_dir = os.path.join(ROOT_DIR, '.chunks')
        if not os.path.exists(chunks_dir):
            return
            
        try:
            with self.lock:
                all_tracked_files = set()
                for file_ids in self.active_uploads.values():
                    all_tracked_files.update(file_ids)
                
                current_time = time.time()
                cleaned_count = 0
                
                # Find chunks that aren't tracked by any session
                for file_id in os.listdir(chunks_dir):
                    chunk_dir = os.path.join(chunks_dir, file_id)
                    if not os.path.isdir(chunk_dir):
                        continue
                    
                    should_cleanup = False
                    cleanup_reason = ""
                    
                    if file_id not in all_tracked_files:
                        # Check age before cleanup
                        timestamp_file = os.path.join(chunk_dir, '.timestamp')
                        
                        if os.path.exists(timestamp_file):
                            try:
                                with open(timestamp_file, 'r') as f:
                                    timestamp = float(f.read().strip())
                                # Cleanup untracked chunks older than 10 minutes (more aggressive for interruptions)
                                if current_time - timestamp > 600:  
                                    should_cleanup = True
                                    cleanup_reason = f"untracked >10min old (interrupted upload)"
                            except (ValueError, OSError):
                                should_cleanup = True
                                cleanup_reason = "corrupted timestamp file"
                        else:
                            # No timestamp, cleanup if dir is older than 10 minutes
                            try:
                                dir_mtime = os.path.getmtime(chunk_dir)
                                if current_time - dir_mtime > 600:
                                    should_cleanup = True
                                    cleanup_reason = "no timestamp >10min old"
                            except OSError:
                                should_cleanup = True
                                cleanup_reason = "cannot read metadata"
                    else:
                        # Even tracked files - cleanup if very old (stale uploads)
                        file_timestamp = self.upload_timestamps.get(file_id, current_time)
                        if current_time - file_timestamp > 3600:  # 1 hour
                            should_cleanup = True
                            cleanup_reason = "tracked but stale >1hr"
                            print(f"🧹 Cleaning up stale tracked chunks (>1hr): {file_id}")
                    
                    if should_cleanup:
                        try:
                            storage.cleanup_chunks(file_id)
                            cleaned_count += 1
                            print(f"🧹 Cleaned up orphaned chunks: {file_id} ({cleanup_reason})")
                        except Exception as e:
                            print(f"❌ Failed to cleanup orphaned chunks {file_id}: {e}")
                        
                        # Remove from tracking if it was tracked
                        if file_id in all_tracked_files:
                            for session_id, file_set in self.active_uploads.items():
                                file_set.discard(file_id)
                            self.upload_timestamps.pop(file_id, None)
                
                if cleaned_count > 0:
                    print(f"🧹 Orphaned chunk cleanup completed: {cleaned_count} directories removed")
                            
        except Exception as e:
            print(f"❌ Error in orphaned chunk cleanup: {e}")

    def cleanup_interrupted_uploads(self):
        """Detect and cleanup uploads that were interrupted (no activity for 2+ minutes)"""
        current_time = time.time()
        interrupted_uploads = []
        
        try:
            with self.lock:
                for session_id, file_ids in list(self.active_uploads.items()):
                    for file_id in list(file_ids):
                        timestamp = self.upload_timestamps.get(file_id)
                        if timestamp and (current_time - timestamp) > 120:  # 2 minutes of inactivity
                            interrupted_uploads.append((session_id, file_id))
                            print(f"🧹 Detected interrupted upload: {file_id} (inactive for {int(current_time - timestamp)}s)")
                
                # Clean up interrupted uploads
                for session_id, file_id in interrupted_uploads:
                    try:
                        self.untrack_upload(session_id, file_id)
                        storage.cleanup_chunks(file_id)
                        print(f"🧹 Cleaned up interrupted upload: {file_id}")
                    except Exception as e:
                        print(f"❌ Failed to cleanup interrupted upload {file_id}: {e}")
                
                if interrupted_uploads:
                    print(f"🧹 Interrupted upload cleanup completed: {len(interrupted_uploads)} uploads cleaned")
                        
        except Exception as e:
            print(f"❌ Error in interrupted upload cleanup: {e}")

    def get_stats(self):
        """Get statistics about active uploads"""
        with self.lock:
            total_sessions = len(self.active_uploads)
            total_uploads = sum(len(file_set) for file_set in self.active_uploads.values())
            return {
                'active_sessions': total_sessions,
                'active_uploads': total_uploads,
                'tracked_files': list(self.upload_timestamps.keys())
            }

# Global chunk tracker instance
chunk_tracker = ChunkTracker()

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def cleanup_stale_chunks_on_request():
    """Clean up chunks that are older than 1 hour - called on each request"""
    try:
        storage.cleanup_old_chunks(max_age_hours=1)
    except Exception as e:
        print(f"❌ Error in stale chunk cleanup: {e}")

@app.before_request
def before_request():
    """Run cleanup before certain requests and handle interrupted uploads"""
    # Ensure session ID exists for logged-in users
    if is_logged_in() and 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    
    # Enhanced cleanup on page load/refresh - more aggressive for interrupted uploads
    if request.endpoint in ['index', 'upload']:
        # Check for and cleanup any stale uploads from this session
        session_id = session.get('session_id')
        if session_id and request.endpoint == 'index':
            # This is a page load/refresh - check for abandoned uploads
            # If we're loading the main page, any pending uploads are likely abandoned
            try:
                current_uploads = chunk_tracker.active_uploads.get(session_id, set())
                if current_uploads:
                    print(f"🧹 Detected {len(current_uploads)} potentially abandoned uploads on page refresh")
                    # Give a grace period for genuine page refreshes during upload
                    for file_id in current_uploads.copy():
                        timestamp = chunk_tracker.upload_timestamps.get(file_id)
                        if timestamp and (time.time() - timestamp) > 30:  # 30 seconds grace period
                            print(f"🧹 Cleaning up abandoned upload: {file_id}")
                            chunk_tracker.untrack_upload(session_id, file_id)
                            storage.cleanup_chunks(file_id)
            except Exception as e:
                print(f"❌ Error in abandoned upload cleanup: {e}")
        
        # Run periodic cleanup in background thread to not slow down requests
        cleanup_thread = threading.Thread(
            target=cleanup_stale_chunks_on_request, 
            daemon=True
        )
        cleanup_thread.start()

@app.route('/login', methods=['GET', 'POST'])
def login():
    # If user is already logged in, redirect to main page
    if is_logged_in():
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        if check_login(username, password):
            login_user(username)
            # Generate a unique session ID for tracking uploads
            session['session_id'] = str(uuid.uuid4())
            # Clear any old flash messages when successfully logging in
            session.pop('_flashes', None)
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    try:
        session_id = session.get('session_id')
        
        if session_id:
            chunk_tracker.cleanup_session_chunks(session_id)
        
        logout_user()
        session.pop('_flashes', None)
        return redirect(url_for('login'))
    except Exception as e:
        logging.error(f"Logout error: {e}", exc_info=True)
        return "Internal server error during logout", 500

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
@login_required
def index(path):
    # Comprehensive path validation: safety and existence
    if path and not storage.is_valid_path(path):
        if not storage.is_safe_path(path):
            flash('Invalid path: contains unsafe characters or directory traversal')
        else:
            flash(f'Path "{path}" does not exist or is not a directory')
        return redirect(url_for('index'))
    
    # Ensure session has a session_id for upload tracking
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    
    role = get_role(current_user())
    items = storage.list_dir(path)
    return render_template('index.html', items=items, path=path, role=role, 
                         CHUNK_SIZE=CHUNK_SIZE)

@app.route('/download/<path:path>')
@login_required
def download(path):
    # Security check: ensure path is safe
    if not storage.is_safe_path(path):
        flash('Invalid file path')
        return redirect(url_for('index'))
    
    full_path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        flash('File not found')
        return redirect(url_for('index'))
    
    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)
    return send_from_directory(directory, filename, as_attachment=True)

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    session_id = session.get('session_id')
    if not session_id:
        # Generate session ID if missing
        session_id = str(uuid.uuid4())
        session['session_id'] = session_id
    
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return 'Permission denied', 403

        file_id = request.form.get('file_id')
        chunk_num = request.form.get('chunk_num')
        total_chunks = request.form.get('total_chunks')
        filename = request.form.get('filename', '')
        dest_path = request.form.get('dest_path', '')

        # Validate and secure filename
        if not filename:
            return 'Filename is required', 400
        
        filename = secure_filename(filename)
        if not filename:
            return 'Invalid filename', 400

        # Security check: ensure destination path is safe
        if dest_path and not storage.is_safe_path(dest_path):
            return 'Invalid destination path', 400

        if ENABLE_CHUNKED_UPLOADS and chunk_num is not None and total_chunks is not None:
            # Chunked upload handling
            try:
                chunk_num = int(chunk_num)
                total_chunks = int(total_chunks)
            except ValueError:
                return 'Invalid chunk parameters', 400

            if not file_id:
                return 'File ID is required for chunked upload', 400

            # Track this upload
            chunk_tracker.track_upload(session_id, file_id)

            chunk = request.files.get('chunk')
            if not chunk:
                return 'No chunk data received', 400

            chunk_data = chunk.read()
            if len(chunk_data) > CHUNK_SIZE:
                return f'Chunk too large (max {CHUNK_SIZE} bytes)', 413

            # Save chunk
            if not storage.save_chunk(file_id, chunk_num, chunk_data):
                # Cleanup on failure
                chunk_tracker.untrack_upload(session_id, file_id)
                storage.cleanup_chunks(file_id)
                return 'Failed to save chunk', 500

            print(f"📦 Saved chunk {chunk_num + 1}/{total_chunks} for {filename} (ID: {file_id})")

            # If this is the last chunk, assemble the file
            if chunk_num == total_chunks - 1:
                try:
                    storage.assemble_chunks(file_id, total_chunks, filename, dest_path)
                    # Successful assembly - untrack the upload
                    chunk_tracker.untrack_upload(session_id, file_id)
                    print(f"✅ Successfully assembled {filename} from {total_chunks} chunks")
                    return 'File uploaded successfully', 200
                except Exception as e:
                    # Assembly failed - cleanup will happen in assemble_chunks
                    chunk_tracker.untrack_upload(session_id, file_id)
                    print(f"❌ Failed to assemble {filename}: {e}")
                    return f'Failed to assemble file: {str(e)}', 500

            return f'Chunk {chunk_num + 1}/{total_chunks} uploaded successfully', 200

        else:
            # Whole file upload handling
            uploaded_file = request.files.get('file')
            if not uploaded_file or uploaded_file.filename == '':
                return 'No file selected', 400

            # Use provided filename or fall back to uploaded filename
            if not filename:
                filename = secure_filename(uploaded_file.filename)
                if not filename:
                    return 'Invalid filename', 400

            # Construct target path
            target_dir = os.path.join(ROOT_DIR, dest_path) if dest_path else ROOT_DIR
            target_path = os.path.join(target_dir, filename)

            # Ensure target directory exists
            os.makedirs(target_dir, exist_ok=True)

            # Save file
            try:
                uploaded_file.save(target_path)
                print(f"✅ Successfully uploaded whole file: {filename}")
                return 'File uploaded successfully', 200
            except Exception as e:
                print(f"❌ Failed to save whole file {filename}: {e}")
                return f'Failed to save file: {str(e)}', 500

    except Exception as e:
        print(f"❌ Upload error: {e}")
        # If there was an error and we were tracking this upload, clean it up
        if file_id:
            chunk_tracker.untrack_upload(session_id, file_id)
            storage.cleanup_chunks(file_id)
        return f'Upload error: {str(e)}', 500

@app.route('/cleanup_chunks', methods=['POST'])
@login_required
def cleanup_chunks():
    """Clean up unfinished chunk files"""
    session_id = session.get('session_id')
    
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403

        data = request.get_json()
        if not data or 'file_id' not in data:
            return jsonify({'error': 'File ID is required'}), 400

        file_id = data['file_id']
        
        # Untrack and cleanup
        chunk_tracker.untrack_upload(session_id, file_id)
        
        # Clean up chunks directory for this file_id
        chunks_dir = os.path.join(ROOT_DIR, '.chunks', file_id)
        if os.path.exists(chunks_dir):
            try:
                shutil.rmtree(chunks_dir)
                print(f"🧹 Manual cleanup completed for: {file_id}")
                
                # Try to remove parent chunks directory if empty
                parent_chunks_dir = os.path.join(ROOT_DIR, '.chunks')
                if os.path.exists(parent_chunks_dir) and not os.listdir(parent_chunks_dir):
                    os.rmdir(parent_chunks_dir)
                    print("🧹 Removed empty chunks directory")
                    
                return jsonify({'success': True, 'message': f'Cleaned up chunks for {file_id}'}), 200
            except Exception as e:
                print(f"❌ Failed to cleanup chunks for {file_id}: {e}")
                return jsonify({'error': f'Failed to cleanup chunks: {str(e)}'}), 500
        else:
            return jsonify({'success': True, 'message': 'No chunks to cleanup'}), 200

    except Exception as e:
        print(f"❌ Cleanup error: {e}")
        return jsonify({'error': f'Cleanup error: {str(e)}'}), 500

@app.route('/cancel_upload', methods=['POST'])
@login_required
def cancel_upload():
    """Cancel an ongoing upload and clean up its chunks"""
    session_id = session.get('session_id')
    
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403

        data = request.get_json()
        if not data or 'file_id' not in data:
            return jsonify({'error': 'File ID is required'}), 400

        file_id = data['file_id']
        filename = data.get('filename', 'Unknown file')
        
        print(f"🚫 Cancelling upload: {file_id} ({filename})")
        
        # Untrack the upload
        chunk_tracker.untrack_upload(session_id, file_id)
        
        # Clean up chunks directory for this file_id
        chunks_dir = os.path.join(ROOT_DIR, '.chunks', file_id)
        if os.path.exists(chunks_dir):
            try:
                # Use Windows-safe deletion
                storage.safe_rmtree(chunks_dir)
                print(f"🧹 Cancelled upload cleanup completed for: {file_id}")
                
                # Try to remove parent chunks directory if empty
                parent_chunks_dir = os.path.join(ROOT_DIR, '.chunks')
                if os.path.exists(parent_chunks_dir) and not os.listdir(parent_chunks_dir):
                    os.rmdir(parent_chunks_dir)
                    print("🧹 Removed empty chunks directory")
                    
                return jsonify({
                    'success': True, 
                    'message': f'Upload cancelled and cleaned up for {filename}',
                    'file_id': file_id
                }), 200
            except Exception as e:
                print(f"❌ Failed to cleanup cancelled upload {file_id}: {e}")
                return jsonify({'error': f'Failed to cleanup cancelled upload: {str(e)}'}), 500
        else:
            # Upload was cancelled before any chunks were created
            return jsonify({
                'success': True, 
                'message': f'Upload cancelled for {filename}',
                'file_id': file_id
            }), 200

    except Exception as e:
        print(f"❌ Cancel upload error: {e}")
        return jsonify({'error': f'Cancel upload error: {str(e)}'}), 500

@app.route('/admin/cleanup_chunks', methods=['POST'])
@login_required
def admin_cleanup_chunks():
    """Admin endpoint to trigger comprehensive chunk cleanup"""
    from storage import manual_chunks_cleanup, emergency_cleanup_all
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403

        print("🧹 Starting comprehensive chunk cleanup...")
        
        # Get stats before cleanup
        stats_before = chunk_tracker.get_stats()
        
        # Cleanup orphaned chunks
        chunk_tracker.cleanup_orphaned_chunks()
        
        # Cleanup interrupted uploads
        chunk_tracker.cleanup_interrupted_uploads()
        
        # Cleanup old chunks (aggressive - 30 minutes)
        storage.cleanup_old_chunks(max_age_hours=0.5)
        
        # Get stats after cleanup
        stats_after = chunk_tracker.get_stats()
        
        # Run enhanced manual cleanup
        manual_success = manual_chunks_cleanup()
        
        print(f"🧹 Comprehensive cleanup completed")
        print(f"   Sessions: {stats_before['active_sessions']} -> {stats_after['active_sessions']}")
        print(f"   Uploads: {stats_before['active_uploads']} -> {stats_after['active_uploads']}")
        
        return jsonify({
            'success': True, 
            'message': 'Comprehensive cleanup completed successfully' if manual_success else 'Cleanup completed with some warnings',
            'stats_before': stats_before,
            'stats_after': stats_after,
            'manual_cleanup_success': manual_success
        }), 200
        
    except Exception as e:
        print(f"❌ Error in comprehensive cleanup: {e}")
        # Try emergency cleanup as fallback
        try:
            emergency_cleanup_all()
            return jsonify({
                'success': True,
                'message': f'Standard cleanup failed, emergency cleanup performed: {str(e)}',
                'emergency_cleanup': True
            }), 200
        except Exception as emergency_error:
            return jsonify({'error': f'All cleanup methods failed: {str(e)} | Emergency: {str(emergency_error)}'}), 500

@app.route('/admin/chunk_stats', methods=['GET'])
@login_required
def chunk_stats():
    """Get chunk tracking statistics"""
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403
            
        stats = chunk_tracker.get_stats()
        
        # Add filesystem stats
        chunks_dir = os.path.join(ROOT_DIR, '.chunks')
        filesystem_chunks = []
        if os.path.exists(chunks_dir):
            try:
                filesystem_chunks = [d for d in os.listdir(chunks_dir) 
                                   if os.path.isdir(os.path.join(chunks_dir, d))]
            except OSError:
                pass
        
        stats['filesystem_chunks'] = len(filesystem_chunks)
        stats['chunk_directories'] = filesystem_chunks
        
        return jsonify(stats), 200
        
    except Exception as e:
        print(f"❌ Error getting chunk stats: {e}")
        return jsonify({'error': f'Stats error: {str(e)}'}), 500

@app.route('/admin/upload_status', methods=['GET'])
@login_required
def upload_status():
    """Get current upload status for UI updates"""
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403
            
        session_id = session.get('session_id')
        stats = chunk_tracker.get_stats()
        
        # Check if current session has active uploads
        session_has_active = False
        if session_id and session_id in chunk_tracker.active_uploads:
            session_has_active = len(chunk_tracker.active_uploads[session_id]) > 0
        
        return jsonify({
            'has_active_uploads': stats['active_uploads'] > 0,
            'session_has_active': session_has_active,
            'total_active_sessions': stats['active_sessions'],
            'total_active_uploads': stats['active_uploads']
        }), 200
        
    except Exception as e:
        print(f"❌ Error getting upload status: {e}")
        return jsonify({'error': f'Status error: {str(e)}'}), 500

@app.route('/api/storage_stats', methods=['GET'])
@login_required
def storage_stats_api():
    """Get storage statistics including disk space and file counts"""
    try:
        print(f"📊 Storage stats API called by user: {session.get('username', 'unknown')}")
        stats = storage.get_storage_stats()
        print(f"📊 Storage stats calculated: {stats}")
        return jsonify(stats), 200
        
    except Exception as e:
        print(f"❌ Error getting storage stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Storage stats error: {str(e)}'}), 500

@app.route('/api/storage_stats_debug', methods=['GET'])
def storage_stats_debug():
    """Debug version of storage stats without authentication"""
    try:
        print("🔧 Debug storage stats API called (no auth required)")
        stats = storage.get_storage_stats()
        print(f"🔧 Debug storage stats calculated: {stats}")
        return jsonify({
            'debug': True,
            'platform': os.name,
            'has_statvfs': hasattr(os, 'statvfs'),
            'root_dir': storage.ROOT_DIR,
            'stats': stats
        }), 200
        
    except Exception as e:
        print(f"❌ Error in debug storage stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Debug storage stats error: {str(e)}'}), 500

@app.route('/api/disk_stats_fast', methods=['GET'])
def disk_stats_fast():
    """Fast disk stats only (no file counting) - no auth required"""
    try:
        print("📊 Fast disk stats request")
        
        # Get only disk usage stats, skip file counting
        disk_usage_path = storage.ROOT_DIR
        
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
                import shutil
                total, used, free = shutil.disk_usage(disk_usage_path)
        else:  # Windows
            import shutil
            total, used, free = shutil.disk_usage(storage.ROOT_DIR)
        
        return jsonify({
            'total_space': total,
            'used_space': used,
            'free_space': free,
            'file_count': 'counting...',  # Will be updated by full stats
            'dir_count': 'counting...',
            'content_size': 'counting...'
        }), 200
        
    except Exception as e:
        print(f"❌ Error in fast disk stats: {e}")
        return jsonify({'error': f'Fast disk stats error: {str(e)}'}), 500

@app.route('/api/health_check', methods=['GET'])
def health_check():
    """Simple health check endpoint that doesn't require authentication"""
    return jsonify({
        'status': 'ok',
        'platform': os.name,
        'has_statvfs': hasattr(os, 'statvfs'),
        'root_dir': ROOT_DIR,
        'timestamp': time.time()
    }), 200

@app.route('/api/files/', defaults={'path': ''})
@app.route('/api/files/<path:path>')
@login_required
def api_files(path):
    """API endpoint to get file listings as JSON"""
    try:
        # Comprehensive path validation: safety and existence
        if path and not storage.is_valid_path(path):
            return jsonify({'error': 'Invalid path'}), 400
        
        role = get_role(current_user())
        items = storage.list_dir(path)
        
        return jsonify({
            'success': True,
            'files': items,
            'current_path': path,
            'role': role
        }), 200
        
    except Exception as e:
        print(f"❌ Error in api_files: {e}")
        return jsonify({'error': 'Failed to load files'}), 500

@app.route('/bulk_move', methods=['POST'])
@login_required
def bulk_move():
    """Move multiple files/folders to a new location"""
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403

        data = request.get_json()
        if not data or 'paths' not in data:
            return jsonify({'error': 'Paths are required'}), 400

        paths = data['paths']
        destination = data.get('destination', '').strip()
        current_path = data.get('current_path', '')

        if not paths:
            return jsonify({'error': 'No paths provided'}), 400

        # Validate destination path
        if destination and not storage.is_safe_path(destination):
            return jsonify({'error': 'Invalid destination path'}), 400

        moved_count = 0
        errors = []

        for source_path in paths:
            try:
                # Security check
                if not storage.is_safe_path(source_path):
                    errors.append(f'Invalid source path: {source_path}')
                    continue

                source_full = os.path.join(ROOT_DIR, source_path)
                if not os.path.exists(source_full):
                    errors.append(f'Source not found: {source_path}')
                    continue

                # Determine destination
                filename = os.path.basename(source_path)
                if destination:
                    dest_full = os.path.join(ROOT_DIR, destination, filename)
                    dest_dir = os.path.join(ROOT_DIR, destination)
                else:
                    dest_full = os.path.join(ROOT_DIR, filename)
                    dest_dir = ROOT_DIR

                # Create destination directory if it doesn't exist
                os.makedirs(dest_dir, exist_ok=True)

                # Check if destination already exists
                if os.path.exists(dest_full):
                    errors.append(f'Destination already exists: {os.path.join(destination, filename) if destination else filename}')
                    continue

                # Perform the move
                shutil.move(source_full, dest_full)
                moved_count += 1

            except Exception as e:
                errors.append(f'Failed to move {source_path}: {str(e)}')

        if errors:
            return jsonify({
                'moved_count': moved_count,
                'errors': errors,
                'error': f'Some items could not be moved. Moved {moved_count} items with {len(errors)} errors.'
            }), 207  # Multi-status
        else:
            return jsonify({'moved_count': moved_count, 'success': True}), 200

    except Exception as e:
        return jsonify({'error': f'Bulk move error: {str(e)}'}), 500

@app.route('/bulk_copy', methods=['POST'])
@login_required
def bulk_copy():
    """Copy multiple files/folders to a new location"""
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403

        data = request.get_json()
        if not data or 'paths' not in data:
            return jsonify({'error': 'Paths are required'}), 400

        paths = data['paths']
        destination = data.get('destination', '').strip()
        current_path = data.get('current_path', '')

        if not paths:
            return jsonify({'error': 'No paths provided'}), 400

        # Validate destination path
        if destination and not storage.is_safe_path(destination):
            return jsonify({'error': 'Invalid destination path'}), 400

        copied_count = 0
        errors = []

        for source_path in paths:
            try:
                # Security check
                if not storage.is_safe_path(source_path):
                    errors.append(f'Invalid source path: {source_path}')
                    continue

                source_full = os.path.join(ROOT_DIR, source_path)
                if not os.path.exists(source_full):
                    errors.append(f'Source not found: {source_path}')
                    continue

                # Determine destination
                filename = os.path.basename(source_path)
                if destination:
                    dest_full = os.path.join(ROOT_DIR, destination, filename)
                    dest_dir = os.path.join(ROOT_DIR, destination)
                else:
                    dest_full = os.path.join(ROOT_DIR, filename)
                    dest_dir = ROOT_DIR

                # Create destination directory if it doesn't exist
                os.makedirs(dest_dir, exist_ok=True)

                # Check if destination already exists
                if os.path.exists(dest_full):
                    # For copies, we can create a new name
                    base_name, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(dest_full):
                        new_filename = f"{base_name}_copy{counter}{ext}"
                        if destination:
                            dest_full = os.path.join(ROOT_DIR, destination, new_filename)
                        else:
                            dest_full = os.path.join(ROOT_DIR, new_filename)
                        counter += 1

                # Perform the copy
                if os.path.isdir(source_full):
                    shutil.copytree(source_full, dest_full)
                else:
                    shutil.copy2(source_full, dest_full)
                
                copied_count += 1

            except Exception as e:
                errors.append(f'Failed to copy {source_path}: {str(e)}')

        if errors:
            return jsonify({
                'copied_count': copied_count,
                'errors': errors,
                'error': f'Some items could not be copied. Copied {copied_count} items with {len(errors)} errors.'
            }), 207  # Multi-status
        else:
            return jsonify({'copied_count': copied_count, 'success': True}), 200

    except Exception as e:
        return jsonify({'error': f'Bulk copy error: {str(e)}'}), 500

@app.route('/bulk_delete', methods=['POST'])
@login_required
def bulk_delete():
    """Delete multiple files/folders"""
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403

        data = request.get_json()
        if not data or 'paths' not in data:
            return jsonify({'error': 'Paths are required'}), 400

        paths = data['paths']

        if not paths:
            return jsonify({'error': 'No paths provided'}), 400

        deleted_count = 0
        errors = []

        for target_path in paths:
            try:
                # Security check
                if not storage.is_safe_path(target_path):
                    errors.append(f'Invalid path: {target_path}')
                    continue

                full_path = os.path.join(ROOT_DIR, target_path)
                if not os.path.exists(full_path):
                    errors.append(f'Path not found: {target_path}')
                    continue

                # Perform the deletion
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)
                
                deleted_count += 1

            except Exception as e:
                errors.append(f'Failed to delete {target_path}: {str(e)}')

        if errors:
            return jsonify({
                'deleted_count': deleted_count,
                'errors': errors,
                'error': f'Some items could not be deleted. Deleted {deleted_count} items with {len(errors)} errors.'
            }), 207  # Multi-status
        else:
            return jsonify({'deleted_count': deleted_count, 'success': True}), 200

    except Exception as e:
        return jsonify({'error': f'Bulk delete error: {str(e)}'}), 500

@app.route('/rename', methods=['POST'])
@login_required
def rename_item():
    """Rename a single file or folder"""
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403

        data = request.get_json()
        if not data or 'old_path' not in data or 'new_name' not in data:
            return jsonify({'error': 'Old path and new name are required'}), 400

        old_path = data['old_path']
        new_name = data['new_name'].strip()

        # Validate inputs
        if not new_name:
            return jsonify({'error': 'New name cannot be empty'}), 400

        # Security checks
        if not storage.is_safe_path(old_path):
            return jsonify({'error': 'Invalid old path'}), 400

        # Validate new name doesn't contain path separators or invalid characters
        if '/' in new_name or '\\' in new_name or any(char in new_name for char in '<>:"|?*'):
            return jsonify({'error': 'Invalid characters in new name'}), 400

        # Check if old path exists
        old_full_path = os.path.join(ROOT_DIR, old_path)
        if not os.path.exists(old_full_path):
            return jsonify({'error': 'Item not found'}), 404

        # Get the directory of the old path
        parent_dir = os.path.dirname(old_path)
        
        # Create new path
        new_path = os.path.join(parent_dir, new_name) if parent_dir else new_name
        new_full_path = os.path.join(ROOT_DIR, new_path)

        # Check if destination already exists
        if os.path.exists(new_full_path):
            return jsonify({'error': 'An item with that name already exists'}), 409

        # Perform the rename
        try:
            os.rename(old_full_path, new_full_path)
            return jsonify({
                'success': True,
                'message': f'Successfully renamed to "{new_name}"',
                'old_path': old_path,
                'new_path': new_path,
                'new_name': new_name
            }), 200
        except OSError as e:
            return jsonify({'error': f'Failed to rename: {str(e)}'}), 500

    except Exception as e:
        return jsonify({'error': f'Rename error: {str(e)}'}), 500

@app.route('/mkdir', methods=['POST'])
@login_required
def mkdir():
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403

        foldername = request.form.get('foldername','').strip()
        path = request.form.get('path','')

        if not foldername:
            return jsonify({'error': 'Folder name is required'}), 400

        # Secure the folder name
        foldername = secure_filename(foldername)
        if not foldername:
            return jsonify({'error': 'Invalid folder name'}), 400

        # Security check: ensure path is safe
        if path and not storage.is_safe_path(path):
            return jsonify({'error': 'Invalid path'}), 400

        created = storage.create_folder(path, foldername)
        if not created:
            return jsonify({'error': 'Folder already exists or error creating folder'}), 400
        else:
            return jsonify({
                'success': True, 
                'message': f'Folder "{foldername}" created successfully',
                'folder_name': foldername
            }), 200
    
    except Exception as e:
        return jsonify({'error': f'Error creating folder: {str(e)}'}), 500

@app.route('/delete', methods=['POST'])
@login_required
def delete():
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            flash('Permission denied')
            return redirect(url_for('index'))

        target_path = request.form.get('target_path')
        if not target_path:
            flash('Target path is required')
            return redirect(url_for('index'))

        # Security check: ensure path is safe
        if not storage.is_safe_path(target_path):
            flash('Invalid target path')
            return redirect(url_for('index'))

        if storage.delete_path(target_path):
            flash('Item deleted successfully')
        else:
            flash('Error deleting item')

        # Redirect to parent directory
        parent_path = '/'.join(target_path.split('/')[:-1])
        return redirect(url_for('index', path=parent_path))
    
    except Exception as e:
        flash(f'Error deleting item: {str(e)}')
        return redirect(url_for('index'))

@app.errorhandler(413)
def too_large(e):
    return 'File too large', 413

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    return 'Internal server error', 500

# Enhanced cleanup scheduler functions
def start_enhanced_cleanup_scheduler():
    """Start enhanced background thread for chunk cleanup"""
    def cleanup_worker():
        while True:
            try:
                # More frequent cleanup - every 15 minutes for stale chunks
                time.sleep(900)  # 15 minutes
                print("🧹 Running enhanced chunk cleanup...")
                storage.cleanup_old_chunks(max_age_hours=1)  # Clean 1+ hour old chunks
                
                # Every 4th run (1 hour), do the full 24-hour cleanup
                cleanup_counter = getattr(cleanup_worker, 'counter', 0) + 1
                cleanup_worker.counter = cleanup_counter
                
                if cleanup_counter % 4 == 0:  # Every hour
                    print("🧹 Running full chunk cleanup...")
                    storage.cleanup_old_chunks(max_age_hours=24)
                    
            except Exception as e:
                print(f"❌ Error in enhanced cleanup worker: {e}")
    
    cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
    print("🧹 Started enhanced chunk cleanup scheduler (every 15 minutes)")

def start_orphan_cleanup_scheduler():
    """Start a background thread to cleanup orphaned chunks and detect interruptions"""
    def orphan_cleanup_worker():
        while True:
            try:
                time.sleep(300)  # Every 5 minutes
                chunk_tracker.cleanup_orphaned_chunks()
                chunk_tracker.cleanup_interrupted_uploads()
            except Exception as e:
                print(f"❌ Error in orphan cleanup worker: {e}")
    
    cleanup_thread = threading.Thread(target=orphan_cleanup_worker, daemon=True)
    cleanup_thread.start()
    print("🗑️ Started enhanced orphaned chunk cleanup scheduler (every 5 minutes)")

# Initialize cleanup on startup
def initialize_cleanup():
    """Initialize all cleanup processes"""
    print("🧹 Initializing cleanup systems...")
    
    # Start enhanced cleanup schedulers
    start_enhanced_cleanup_scheduler()
    start_orphan_cleanup_scheduler()
    
    # Do an initial aggressive cleanup on startup
    try:
        print("🧹 Running startup cleanup...")
        storage.cleanup_old_chunks(max_age_hours=0.1)  # Clean chunks older than 30 minutes
        chunk_tracker.cleanup_orphaned_chunks()
        print("✅ Startup cleanup completed")
    except Exception as e:
        print(f"⚠️ Warning: Startup cleanup failed: {e}")

# Initialize cleanup when app starts
initialize_cleanup()

if __name__ == '__main__':
    print(f"🚀 Starting Enhanced Cloudinator FTP Server on port {PORT}")
    print(f"📁 Root directory: {os.path.abspath(ROOT_DIR)}")
    print(f"🔧 Chunked uploads: {'Enabled' if ENABLE_CHUNKED_UPLOADS else 'Disabled'}")
    print(f"📦 Chunk size: {CHUNK_SIZE // (1024*1024)}MB")
    print("✨ Enhanced Features:")
    print("   • Smart progress tracking with speed/ETA")
    print("   • Multi-file selection with bulk operations")
    print("   • Advanced chunk cleanup system")
    print("   • Session-based upload tracking")
    print("   • Orphaned chunk detection and cleanup")
    print("   • Real-time cleanup on page refresh")
    print("🧹 Cleanup Schedule:")
    print("   • Every 5 minutes: Orphaned chunks cleanup")
    print("   • Every 15 minutes: Stale chunks cleanup (1+ hours)")
    print("   • Every 1 hour: Full cleanup (24+ hours)")
    print("   • On page load: Request-based cleanup")
    print("   • On logout: Session cleanup")
    
    app.run(host='0.0.0.0', port=PORT, debug=False)