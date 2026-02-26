# Bulk ZIP progress tracking
bulk_zip_progress = {}

from flask import g
# Global flag for cancelling bulk ZIP
bulk_zip_cancelled = {}

# Move this endpoint below app initialization
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, send_file, flash, session, jsonify, Response, make_response, render_template_string
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.exceptions import ClientDisconnected
import os
import shutil
import json
import threading
import time
import logging
import uuid
import zipfile
import io
import re
import zipstream
from datetime import datetime
from config import PORT, ROOT_DIR, SESSION_SECRET, CHUNK_SIZE, ENABLE_CHUNKED_UPLOADS
from auth import check_login, login_user, logout_user, current_user, is_logged_in, get_role
import storage

# File monitoring and real-time updates
from file_monitor import get_file_monitor, init_file_monitor
from realtime_stats import storage_stats_sse, trigger_storage_update, get_event_manager

# Assembly Queue System
import queue
from dataclasses import dataclass
from typing import Optional

@dataclass
class AssemblyJob:
    file_id: str
    filename: str
    dest_path: str
    total_chunks: int
    created_at: float
    status: str = 'pending'  # pending, processing, completed, error
    error_message: Optional[str] = None
    session_id: Optional[str] = None

class AssemblyQueue:
    def __init__(self):
        self.job_queue = queue.Queue()
        self.active_jobs = {}  # file_id -> AssemblyJob
        self.completed_jobs = {}  # file_id -> AssemblyJob (keep for 1 hour)
        self.lock = threading.Lock()
        
    def add_job(self, file_id, filename, dest_path, total_chunks, session_id=None):
        """Add a new assembly job to the queue"""
        job = AssemblyJob(
            file_id=file_id,
            filename=filename,
            dest_path=dest_path,
            total_chunks=total_chunks,
            created_at=time.time(),
            session_id=session_id
        )
        
        with self.lock:
            self.active_jobs[file_id] = job
            
        self.job_queue.put(job)
        print(f"🔄 Added assembly job for {filename} (ID: {file_id})")
        return job
    
    def get_job_status(self, file_id):
        """Get the current status of an assembly job"""
        with self.lock:
            if file_id in self.active_jobs:
                return self.active_jobs[file_id]
            elif file_id in self.completed_jobs:
                return self.completed_jobs[file_id]
            return None
    
    def get_all_active_jobs(self):
        """Get all currently active assembly jobs"""
        with self.lock:
            return list(self.active_jobs.values())
    
    def get_jobs_for_session(self, session_id):
        """Get all jobs (active + recent completed) for a session"""
        with self.lock:
            jobs = []
            # Active jobs
            for job in self.active_jobs.values():
                if job.session_id == session_id:
                    jobs.append(job)
            # Recent completed jobs (last hour)
            current_time = time.time()
            for job in self.completed_jobs.values():
                if (job.session_id == session_id and 
                    current_time - job.created_at < 3600):  # 1 hour
                    jobs.append(job)
            return jobs
    
    def complete_job(self, file_id, success=True, error_message=None):
        """Mark a job as completed"""
        with self.lock:
            if file_id in self.active_jobs:
                job = self.active_jobs.pop(file_id)
                job.status = 'completed' if success else 'error'
                if error_message:
                    job.error_message = error_message
                self.completed_jobs[file_id] = job
                print(f"✅ Assembly job completed for {job.filename} (Success: {success})")
                
                # Untrack the upload when assembly is successfully completed
                if success and job.session_id:
                    try:
                        chunk_tracker.untrack_upload(job.session_id, file_id)
                        print(f"🧹 Untracked completed upload: {file_id} for session {job.session_id}")
                    except Exception as e:
                        print(f"⚠️ Failed to untrack upload {file_id}: {e}")
                
                return job
            return None
    
    def cleanup_old_jobs(self):
        """Remove completed jobs older than 1 hour"""
        with self.lock:
            current_time = time.time()
            expired_jobs = [
                file_id for file_id, job in self.completed_jobs.items()
                if current_time - job.created_at > 3600
            ]
            for file_id in expired_jobs:
                del self.completed_jobs[file_id]
            if expired_jobs:
                print(f"🧹 Cleaned up {len(expired_jobs)} old assembly jobs")

# Global assembly queue
assembly_queue = AssemblyQueue()

app = Flask(__name__)
CORS(app)
app.secret_key = SESSION_SECRET

# Configure session handling
app.config.update(
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=300,  # Seconds
    SESSION_REFRESH_EACH_REQUEST=True,
    SESSION_COOKIE_NAME='cloudinator_session'
)

storage.ensure_root()

# Initialize file system monitoring
file_monitor = init_file_monitor()
file_monitor.add_change_callback(trigger_storage_update)
print(f"📡 File system monitoring started for: {ROOT_DIR}")

@app.before_request
def validate_session():
    # Skip validation for login-related routes
    if request.endpoint in ['login', 'static']:
        return
        
    # Check if user is logged in
    if not session.get('logged_in'):
        session.clear()
        return redirect(url_for('login'))
        
    # Validate session age
    login_time = session.get('login_time', 0)
    if time.time() - login_time > 3600:  # 1 hour
        session.clear()
        return redirect(url_for('login'))

@app.route('/cancel_bulk_zip', methods=['POST'])
def cancel_bulk_zip():
    session_id = session.get('session_id') or request.cookies.get('session')
    if not session_id:
        return jsonify({'error': 'No session ID'}), 400
    bulk_zip_cancelled[session_id] = True
    print(f"❌ Bulk ZIP cancelled for session {session_id}")
    return jsonify({'status': 'cancelled'})

# Add Jinja2 filter for timestamp formatting
@app.template_filter('timestamp_to_date')
def timestamp_to_date_filter(timestamp):
    """Convert Unix timestamp to time on first line, date on second"""
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%m/%d/%Y') + '||' + dt.strftime('%I:%M %p')
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
                    
                    # CRITICAL: Never cleanup chunks for files currently being assembled
                    if assembly_queue.get_job_status(file_id):
                        print(f"🔐 Skipping cleanup for {file_id} - currently being assembled")
                        continue
                    
                    # Also check for assembly protection marker
                    assembly_marker = os.path.join(chunk_dir, '.assembling')
                    if os.path.exists(assembly_marker):
                        print(f"🔐 Skipping cleanup for {file_id} - assembly marker present")
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

def get_protected_files():
    """Get set of file IDs that should be protected from cleanup (currently being assembled)"""
    protected_files = set()
    try:
        for job in assembly_queue.get_all_active_jobs():
            protected_files.add(job.file_id)
    except Exception as e:
        print(f"⚠️ Warning: Could not get active assembly jobs: {e}")
    
    return protected_files

def cleanup_stale_chunks_on_request():
    """Clean up chunks that are older than 1 hour - called on each request"""
    try:
        # Get all active assembly jobs to avoid cleaning their chunks
        active_assembly_jobs = get_protected_files()
            
        if active_assembly_jobs:
            print(f"🔐 Protecting {len(active_assembly_jobs)} files from cleanup (currently being assembled)")
        
        # Pass the protected file IDs to the cleanup function
        storage.cleanup_old_chunks(max_age_hours=1, protected_files=active_assembly_jobs)
    except Exception as e:
        print(f"❌ Error in stale chunk cleanup: {e}")

@app.before_request
def before_request():
    """Run cleanup before certain requests and handle interrupted uploads"""
    # Ensure session ID exists for logged-in users
    if is_logged_in() and 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    
    # Enhanced cleanup on page load/refresh - check for assembly jobs first
    if request.endpoint in ['index', 'upload']:
        # Check for and cleanup any stale uploads from this session
        session_id = session.get('session_id')
        if session_id and request.endpoint == 'index':
            # This is a page load/refresh - check for abandoned uploads
            # IMPORTANT: Check for assembly jobs FIRST before cleaning up chunks
            try:
                current_uploads = chunk_tracker.active_uploads.get(session_id, set())
                if current_uploads:
                    print(f"🧹 Detected {len(current_uploads)} potentially abandoned uploads on page refresh")
                    # Check if any of these uploads are actually in assembly queue
                    assembly_protected = set()
                    for file_id in current_uploads.copy():
                        # Check if this file is in assembly queue
                        if assembly_queue.get_job_status(file_id):
                            print(f"🔐 Upload {file_id} is protected by assembly queue")
                            assembly_protected.add(file_id)
                            continue
                            
                        # Check for assembly protection marker
                        chunk_dir = os.path.join(ROOT_DIR, '.chunks', file_id)
                        assembly_marker = os.path.join(chunk_dir, '.assembling')
                        if os.path.exists(assembly_marker):
                            print(f"🔐 Upload {file_id} is protected by assembly marker")
                            assembly_protected.add(file_id)
                            continue
                            
                        # Give a grace period for genuine page refreshes during upload
                        timestamp = chunk_tracker.upload_timestamps.get(file_id)
                        if timestamp and (time.time() - timestamp) > 30:  # 30 seconds grace period
                            print(f"🧹 Cleaning up abandoned upload: {file_id}")
                            chunk_tracker.untrack_upload(session_id, file_id)
                            storage.cleanup_chunks(file_id)
                    
                    # Keep assembly-protected uploads in tracker
                    if assembly_protected:
                        print(f"🔐 Keeping {len(assembly_protected)} assembly-protected uploads in tracker")
            except Exception as e:
                print(f"❌ Error in abandoned upload cleanup: {e}")
        
        # Run periodic cleanup in background thread to not slow down requests
        cleanup_thread = threading.Thread(
            target=cleanup_stale_chunks_on_request, 
            daemon=True
        )
        cleanup_thread.start()

@app.after_request
def after_request(response):
    """Add security headers to all responses"""
    # Add cache control headers to authenticated pages
    if request.endpoint and request.endpoint not in ['login', 'static']:
        # Check if this is an authenticated route
        if is_logged_in() or request.endpoint in ['index', 'download', 'upload', 'admin']:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
    
    return response

@app.route('/login', methods=['GET', 'POST'])
def login():
    # If user is already logged in, redirect to index
    if session.get('logged_in'):
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if check_login(username, password):
            # Set up session data
            session.clear()
            session.permanent = True
            login_user(username)
            session['role'] = get_role(username)
            session['session_id'] = str(uuid.uuid4())
            session['logged_in'] = True
            session['login_time'] = int(time.time())
            session.modified = True
            
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password')
            return render_template('login.html'), 401
    
    # Render login page with no-cache headers
    response = make_response(render_template('login.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/logout')
def logout():
    try:
        # Clean up any upload chunks
        session_id = session.get('session_id')
        if session_id:
            chunk_tracker.cleanup_session_chunks(session_id)
        
        # Clear the session completely
        session.clear()
        
        # Create response with session-clearing headers
        response = make_response(redirect(url_for('login', logged_out='1')))
        response.delete_cookie('cloudinator_session')
        response.delete_cookie('session_check')
        
        # Add cache-control headers to prevent caching
        response.headers.update({
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        })
        
        return response
    except Exception as e:
        logging.error(f"Logout error: {e}", exc_info=True)
        session.clear()  # Still try to clear session even if other operations fail
        return redirect(url_for('login', logged_out='1'))

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
    
    try:
        # Get current directory info
        current_path = os.path.join(ROOT_DIR, path) if path else ROOT_DIR
        items = storage.list_dir(path)
        
        response = make_response(render_template('index.html', 
                                               items=items, 
                                               path=path, 
                                               role=session.get('role', 'readonly'),
                                               CHUNK_SIZE=CHUNK_SIZE))
        
        # Add strict cache control headers to prevent caching of authenticated content
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
        
    except Exception as e:
        logging.error(f"Error loading directory {path}: {e}", exc_info=True)
        flash('Error loading directory')
        return redirect(url_for('index'))

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

@app.route('/bulk-download', methods=['POST'])
@login_required
def bulk_download():
    """Download multiple files and folders as a streaming ZIP file using zipstream-new"""
    try:
        print(f"📥 Bulk download request received from user: {current_user()}")
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            print(f"📋 JSON Request data: {data}")
            
            if not data or 'paths' not in data:
                print("❌ Error: No paths provided in JSON request")
                return jsonify({'error': 'No paths provided'}), 400
                
            paths = data['paths']
        else:
            # Handle form data
            print("📋 Form data request received")
            paths_json = request.form.get('paths')
            if not paths_json:
                print("❌ Error: No paths provided in form request")
                return jsonify({'error': 'No paths provided'}), 400
            
            try:
                import json
                paths = json.loads(paths_json)
                print(f"📋 Form Request paths: {paths}")
            except json.JSONDecodeError:
                print("❌ Error: Invalid JSON in form paths")
                return jsonify({'error': 'Invalid paths format'}), 400
        print(f"📁 Requested paths ({len(paths)} items): {paths}")
        
        if not paths:
            print("❌ Error: Empty paths list")
            return jsonify({'error': 'Empty paths list'}), 400
        
        # Validate all paths
        print(f"🔍 Validating {len(paths)} paths...")
        invalid_paths = []
        valid_paths = []
        for path in paths:
            if not storage.is_safe_path(path):
                invalid_paths.append(path)
                print(f"⚠️  Invalid path detected: {path}")
            else:
                valid_paths.append(path)
                print(f"✅ Valid path: {path}")
        
        print(f"📊 Validation results: {len(valid_paths)} valid, {len(invalid_paths)} invalid")
        
        if invalid_paths:
            return jsonify({'error': f'Invalid paths: {invalid_paths}'}), 400
        
        # Generate a filename for the ZIP based on selection
        if len(paths) == 1:
            # Single item - use its name
            base_name = os.path.basename(paths[0]) or 'download'
        else:
            # Multiple items - use generic name with count
            base_name = f'bulk_download_{len(paths)}_items'
        
        zip_filename = f'{base_name}.zip'
        print(f"📦 Creating streaming ZIP file: {zip_filename}")
        
        # Capture session data before creating the generator (outside request context)
        session_id = session.get('session_id')
        if session_id:
            bulk_zip_progress[session_id] = {'current': 0, 'total': len(paths), 'done': False}
        
        def generate_zip_stream():
            """Generator function to create ZIP file using zipstream-new for true streaming"""
            
            print(f"🗂️ Starting ZIP stream generation for {len(paths)} paths...")
            
            # Create zipstream object with optimized compression for large files
            zf = zipstream.ZipFile(mode='w', compression=zipstream.ZIP_DEFLATED, allowZip64=True)
            
            files_added = 0
            total_size = 0
            for i, path in enumerate(paths, 1):
                # Check for cancellation
                if session_id and bulk_zip_cancelled.get(session_id):
                    print(f"❌ ZIP generation cancelled for session {session_id}")
                    bulk_zip_cancelled.pop(session_id, None)
                    break
                
                print(f"📄 Processing item {i}/{len(paths)}: {path}")
                if session_id:
                    bulk_zip_progress[session_id]['current'] = i
                
                full_path = os.path.join(ROOT_DIR, path)
                if not os.path.exists(full_path):
                    print(f"⚠️  Path does not exist: {full_path}")
                    continue
                
                try:
                    if os.path.isfile(full_path):
                        # Add single file
                        arc_name = os.path.basename(full_path)
                        file_size = os.path.getsize(full_path)
                        total_size += file_size
                        print(f"📄 Adding file to stream: {arc_name} ({file_size:,} bytes)")
                        zf.write(full_path, arcname=arc_name)
                        files_added += 1
                    elif os.path.isdir(full_path):
                        # Add directory recursively
                        dir_name = os.path.basename(full_path)
                        print(f"📁 Adding directory to stream: {dir_name}")
                        dir_files_added = 0
                        
                        for root, dirs, files in os.walk(full_path):
                            # Calculate relative path for archive
                            rel_path = os.path.relpath(root, full_path)
                            if rel_path == '.':
                                arc_root = dir_name
                            else:
                                arc_root = os.path.join(dir_name, rel_path).replace('\\', '/')
                            
                            # Add all files in current directory
                            for file in files:
                                try:
                                    file_path = os.path.join(root, file)
                                    file_size = os.path.getsize(file_path)
                                    total_size += file_size
                                    arc_name = os.path.join(arc_root, file).replace('\\', '/')
                                    zf.write(file_path, arcname=arc_name)
                                    dir_files_added += 1
                                except (PermissionError, OSError) as e:
                                    print(f"⚠️  Skipped file {file_path}: {str(e)}")
                                    logging.warning(f"Skipped file {file_path}: {str(e)}")
                                    continue
                            
                            # Create empty directory entry if no files and no subdirs
                            if not files and not dirs:
                                zf.writestr(arc_root + '/', '')
                        
                        print(f"📁 Directory added with {dir_files_added} files")
                        files_added += dir_files_added
                        
                except (PermissionError, OSError) as e:
                    print(f"⚠️  Skipped item {full_path}: {str(e)}")
                    logging.warning(f"Skipped item {full_path}: {str(e)}")
                    continue
            
            print(f"✅ ZIP stream setup complete: {files_added} files queued for streaming")
            if session_id:
                bulk_zip_progress[session_id]['done'] = True
            
            # Stream the ZIP file
            for chunk in zf:
                yield chunk
            
            print(f"� ZIP stream download completed")
        
        # Create response with streaming optimized for large files
        response = Response(
            generate_zip_stream(),
            mimetype='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename="{zip_filename}"',
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Content-Encoding': 'identity'
            }
        )
        
        print(f"🎉 Bulk download response ready for {len(paths)} items")
        logging.info(f"Bulk download initiated by {current_user()}: {len(paths)} items")
        logging.debug(f"Paths requested: {paths}")
        return response
        
    except Exception as e:
        print(f"❌ Bulk download error: {str(e)}")
        logging.error(f"Bulk download error: {str(e)}")
        return jsonify({'error': 'Failed to create download'}), 500

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    session_id = session.get('session_id')
    if not session_id:
        session_id = str(uuid.uuid4())
        session['session_id'] = session_id
    
    # Initialize these variables outside the try block to ensure they're available in the except blocks
    file_id = None
    filename = None

    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return 'Permission denied', 403

        file_id = request.form.get('file_id')
        chunk_num = request.form.get('chunk_num')
        total_chunks = request.form.get('total_chunks')
        filename = request.form.get('filename', '')
        dest_path = request.form.get('dest_path', '')

        # Validate filename (must not be empty)
        if not filename:
            return 'Filename is required', 400

        # Remove all sanitization, only check for empty and slashes
        if '/' in filename or '\\' in filename:
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

            # If this is the last chunk, queue for background assembly
            if chunk_num == total_chunks - 1:
                try:
                    # Save metadata for assembly worker
                    chunk_dir = os.path.join(ROOT_DIR, '.chunks', file_id)
                    metadata_file = os.path.join(chunk_dir, '.metadata')
                    metadata = {
                        'filename': filename,
                        'dest_path': dest_path,
                        'total_chunks': total_chunks,
                        'session_id': session_id,
                        'timestamp': time.time()
                    }
                    with open(metadata_file, 'w') as f:
                        json.dump(metadata, f)
                    
                    # Add to background assembly queue
                    assembly_queue.add_job(file_id, filename, dest_path, total_chunks, session_id)
                    
                    print(f"🔄 Queued {filename} for background assembly")
                    return jsonify({
                        'status': 'upload_complete',
                        'message': f'Upload complete - processing {filename}...',
                        'file_id': file_id,
                        'assembly_queued': True
                    }), 200
                    
                except Exception as e:
                    # Failed to queue assembly - cleanup
                    chunk_tracker.untrack_upload(session_id, file_id)
                    storage.cleanup_chunks(file_id)
                    print(f"❌ Failed to queue assembly for {filename}: {e}")
                    return f'Failed to queue file assembly: {str(e)}', 500

            return f'Chunk {chunk_num + 1}/{total_chunks} uploaded successfully', 200

        else:
            # Whole file upload handling
            uploaded_file = request.files.get('file')
            if not uploaded_file or uploaded_file.filename == '':
                return 'No file selected', 400

            # Use provided filename or fall back to uploaded filename
            if not filename:
                filename = uploaded_file.filename
                if not filename:
                    return 'Invalid filename', 400
            # Only check for slashes
            if '/' in filename or '\\' in filename:
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

    except ClientDisconnected as e:
        print(f"👋 Client disconnected during upload of {filename or 'unknown file'} (ID: {file_id})")
        # Always clean up chunks if we have a file_id
        if file_id:
            chunk_tracker.untrack_upload(session_id, file_id)
            storage.cleanup_chunks(file_id)
        # No need to send response - client is gone
        return '', 499  # Return 499 Client Closed Request
    
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
    
@app.route('/admin/cleanup_cache', methods=['POST'])
@login_required
def admin_cleanup_cache():
    """Delete storage_index.json and trigger a fresh full walk to rebuild it"""
    try:
        role = get_role(current_user())
        if role != 'readwrite':
            return jsonify({'error': 'Permission denied'}), 403

        from file_monitor import get_file_monitor, CACHE_FILE
        import os

        # Delete the cache file
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
            print(f"🗑️ Cache file deleted: {CACHE_FILE}")
        else:
            print("ℹ️ No cache file found — nothing to delete")

        # Trigger a fresh full reconciliation walk to rebuild it
        monitor = get_file_monitor()
        print("🚶 Rebuilding cache from scratch...")
        monitor._reconcile()

        return jsonify({
            'success': True,
            'message': f'Cache cleared and rebuilt: {monitor._file_count:,} files, {monitor._dir_count:,} dirs, {len(monitor._dir_info):,} folders indexed'
        }), 200

    except Exception as e:
        print(f"❌ Error during cache cleanup: {e}")
        return jsonify({'error': str(e)}), 500

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
        
        # Get active assembly jobs to protect them from cleanup
        active_assembly_jobs = get_protected_files()
            
        if active_assembly_jobs:
            print(f"🔐 Manual cleanup protecting {len(active_assembly_jobs)} files currently being assembled")
        
        # Cleanup old chunks (aggressive - 30 minutes)
        storage.cleanup_old_chunks(max_age_hours=0.5, protected_files=active_assembly_jobs)
        
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
        
        # Allow readonly users to check auth status, but return limited info
        if role == 'readonly':
            return jsonify({
                'authenticated': True,
                'role': 'readonly',
                'has_active_uploads': False,
                'session_has_active': False,
                'total_active_sessions': 0,
                'can_upload': False
            })
        
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
    """Get storage statistics - INSTANT VERSION using cached data"""
    try:
        print(f"📊 INSTANT Storage stats API called by user: {session.get('username', 'unknown')}")
        
        # Use cached snapshot for instant response
        from file_monitor import get_file_monitor
        file_monitor = get_file_monitor()
        current_snapshot = file_monitor.get_current_snapshot()
        
        # Get fast disk stats only (no file counting)
        from realtime_stats import StorageStatsEventManager
        event_manager = StorageStatsEventManager()
        disk_stats = event_manager._get_fast_disk_stats()
        
        # Build instant stats response
        if current_snapshot:
            stats = {
                'total_space': disk_stats['total_space'],
                'used_space': disk_stats['used_space'],
                'free_space': disk_stats['free_space'],
                'file_count': current_snapshot.file_count,
                'dir_count': current_snapshot.dir_count,
                'content_size': current_snapshot.total_size
            }
        else:
            # Fallback instant stats
            stats = {
                'total_space': disk_stats['total_space'],
                'used_space': disk_stats['used_space'],
                'free_space': disk_stats['free_space'],
                'file_count': 0,
                'dir_count': 0,
                'content_size': 0
            }
        
        print(f"📊 INSTANT storage stats returned: files={stats['file_count']}, dirs={stats['dir_count']}")
        return jsonify(stats), 200
        
    except Exception as e:
        print(f"❌ Error getting instant storage stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Storage stats error: {str(e)}'}), 500

@app.route('/api/storage_stats_slow', methods=['GET'])
@login_required
def storage_stats_slow_api():
    """Get storage statistics - SLOW VERSION with full file counting"""
    try:
        print(f"📊 SLOW Storage stats API called by user: {session.get('username', 'unknown')}")
        stats = storage.get_storage_stats()
        print(f"📊 SLOW storage stats calculated: {stats}")
        return jsonify(stats), 200
        
    except Exception as e:
        print(f"❌ Error getting slow storage stats: {e}")
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

@app.route('/api/storage_stats_stream', methods=['GET'])
def storage_stats_stream():
    """Server-Sent Events endpoint for real-time storage stats"""
    if not is_logged_in():
        return jsonify({'error': 'Authentication required'}), 401
    
    print(f"📡 SSE connection established for user: {current_user()}")
    return storage_stats_sse()

@app.route('/api/storage_stats_poll', methods=['GET'])
def storage_stats_poll():
    """Polling endpoint for storage stats - fallback when SSE fails"""
    if not is_logged_in():
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        from file_monitor import get_file_monitor
        file_monitor = get_file_monitor()
        
        # Get current timestamp for comparison
        last_check = request.args.get('last_check', type=float, default=0)
        
        # For initial load (last_check=0), provide instant cached stats
        if last_check == 0:
            print("📊 Initial polling request - providing instant cached stats")
            current_time = time.time()
            
            # Get quick disk stats only
            from realtime_stats import StorageStatsEventManager
            event_manager = StorageStatsEventManager()
            disk_stats = event_manager._get_fast_disk_stats()
            
            # Use cached snapshot if available, otherwise provide placeholder
            current_snapshot = file_monitor.get_current_snapshot()
            if current_snapshot:
                file_count = current_snapshot.file_count
                dir_count = current_snapshot.dir_count
                total_size = current_snapshot.total_size
            else:
                # Provide instant placeholder stats
                file_count = 0
                dir_count = 0
                total_size = 0
            
            response_data = {
                'type': 'polling_response',
                'timestamp': current_time,
                'changed': True,  # Always true for initial load
                'data': {
                    'file_count': file_count,
                    'dir_count': dir_count,
                    'total_size': total_size,
                    'content_size': total_size,
                    'last_modified': current_time,
                    'total_space': disk_stats['total_space'],
                    'free_space': disk_stats['free_space'],
                    'used_space': disk_stats['used_space'],
                    'changes': {
                        'files_changed': 0,
                        'dirs_changed': 0,
                        'size_changed': 0,
                        'content_changed': False,
                        'mtime_changed': False
                    }
                }
            }
            
            print(f"📊 Instant polling response: files={file_count}, dirs={dir_count}")
            return jsonify(response_data), 200
        
        # Regular polling check for changes
        current_snapshot = file_monitor.get_current_snapshot()
        current_time = time.time()
        
        # Always return current stats, but include a 'changed' flag
        has_changes = False
        changes_data = {'files_changed': 0, 'dirs_changed': 0, 'size_changed': 0}
        
        if current_snapshot and current_snapshot.timestamp > last_check:
            has_changes = True
            
            # Get the last known file/dir counts from the polling history
            # Use a simple session-based tracking to reduce false positives
            last_known_files = request.args.get('last_files', type=int, default=0)
            last_known_dirs = request.args.get('last_dirs', type=int, default=0)
            
            # Calculate actual count changes
            files_diff = current_snapshot.file_count - last_known_files if last_known_files > 0 else 0
            dirs_diff = current_snapshot.dir_count - last_known_dirs if last_known_dirs > 0 else 0
            
            # Only report specific changes if we have meaningful differences
            if abs(files_diff) > 0 or abs(dirs_diff) > 0:
                # Real file/folder count change detected
                changes_data = {
                    'files_changed': files_diff,
                    'dirs_changed': dirs_diff,
                    'size_changed': 0,  # Size changes are complex to calculate
                    'content_changed': True,
                    'mtime_changed': True
                }
            else:
                # Timestamp changed but no count changes - likely system noise
                # Report as minor content change without specific counts
                changes_data = {
                    'files_changed': 0,  # No count change
                    'dirs_changed': 0,   # No count change
                    'size_changed': 0,   # No size change claimed
                    'content_changed': True,   # Something changed (timestamp)
                    'mtime_changed': True      # Modification time changed
                }
            
        # Debug logging for timestamp comparison
        print(f"📊 Polling debug: last_check={last_check}, snapshot_timestamp={current_snapshot.timestamp if current_snapshot else 'None'}, has_changes={has_changes}")
            
        # Get disk stats
        from realtime_stats import StorageStatsEventManager
        event_manager = StorageStatsEventManager()
        disk_stats = event_manager._get_fast_disk_stats()
        
        response_data = {
            'type': 'polling_response',
            'timestamp': current_time,
            'changed': has_changes,
            'data': {
                'file_count': current_snapshot.file_count if current_snapshot else 0,
                'dir_count': current_snapshot.dir_count if current_snapshot else 0,
                'total_size': current_snapshot.total_size if current_snapshot else 0,
                'content_size': current_snapshot.total_size if current_snapshot else 0,
                'last_modified': current_snapshot.last_modified if current_snapshot else current_time,
                'total_space': disk_stats['total_space'],
                'free_space': disk_stats['free_space'],
                'used_space': disk_stats['used_space'],
                'changes': changes_data  # Add changes field for frontend
            }
        }
        
        print(f"📊 Polling response: changed={has_changes}, files={response_data['data']['file_count']}")
        return jsonify(response_data), 200
        
    except Exception as e:
        print(f"❌ Error in polling endpoint: {e}")
        return jsonify({'error': f'Polling error: {str(e)}'}), 500

@app.route('/api/monitoring_status', methods=['GET'])
def monitoring_status():
    """Get current monitoring system status"""
    if not is_logged_in():
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        event_manager = get_event_manager()
        return jsonify({
            'monitoring_active': file_monitor.monitoring,
            'connected_clients': event_manager.get_client_count(),
            'last_check': getattr(file_monitor, 'last_check_time', None),
            'total_checks': getattr(file_monitor, 'check_count', 0)
        }), 200
    except Exception as e:
        print(f"❌ Error getting monitoring status: {e}")
        return jsonify({'error': f'Monitoring status error: {str(e)}'}), 500

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

@app.route('/api/search', methods=['GET'])
@login_required
def search_files():
    """Deep search through all folders for files/folders matching query"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'results': [], 'query': query}), 200
    
    try:
        query_lower = query.lower()
        results = []
        search_start = time.time()
        max_results = 100  # Limit results to avoid overwhelming UI
        
        # Walk through all directories starting from ROOT_DIR
        for root, dirs, files in os.walk(ROOT_DIR):
            # Stop if we've found enough results
            if len(results) >= max_results:
                break
                
            # Calculate relative path from ROOT_DIR
            rel_path = os.path.relpath(root, ROOT_DIR)
            if rel_path == '.':
                rel_path = ''
            
            # Search in folder names
            for dirname in dirs[:]:  # Use slice to allow modification during iteration
                if query_lower in dirname.lower():
                    folder_path = os.path.join(rel_path, dirname) if rel_path else dirname
                    try:
                        full_path = os.path.join(root, dirname)
                        stat_info = os.stat(full_path)
                        
                        results.append({
                            'name': dirname,
                            'path': folder_path.replace('\\', '/'),
                            'type': 'folder',
                            'is_dir': True,
                            'size': 0,
                            'modified': datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                            'match_type': 'name'
                        })
                    except (OSError, IOError):
                        continue  # Skip inaccessible folders
                        
                    if len(results) >= max_results:
                        break
            
            # Search in file names
            for filename in files:
                if len(results) >= max_results:
                    break
                    
                if query_lower in filename.lower():
                    file_path = os.path.join(rel_path, filename) if rel_path else filename
                    try:
                        full_path = os.path.join(root, filename)
                        stat_info = os.stat(full_path)
                        
                        # Get file extension for type
                        _, ext = os.path.splitext(filename)
                        file_type = ext[1:].upper() if ext else 'FILE'
                        
                        results.append({
                            'name': filename,
                            'path': file_path.replace('\\', '/'),
                            'type': file_type,
                            'is_dir': False,
                            'size': stat_info.st_size,
                            'modified': datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                            'match_type': 'name'
                        })
                    except (OSError, IOError):
                        continue  # Skip inaccessible files
        
        search_time = time.time() - search_start
        
        return jsonify({
            'results': results,
            'query': query,
            'total_found': len(results),
            'search_time': round(search_time, 3),
            'truncated': len(results) >= max_results
        }), 200
        
    except Exception as e:
        print(f"❌ Search error: {str(e)}")
        return jsonify({'error': f'Search failed: {str(e)}'}), 500

@app.route('/api/dir_info/', defaults={'path': ''})
@app.route('/api/dir_info/<path:path>')
@login_required
def dir_info(path):
    """
    Returns folder size and item count.
    Hits the in-memory index instantly if indexed.
    Falls back to live walk for brand-new folders not yet in the index,
    then stores the result back so subsequent requests are instant.
    """
    if path and not storage.is_safe_path(path):
        return jsonify({'error': 'Invalid path'}), 400
    try:
        info = storage.get_dir_info(path)

        # If this was a live walk fallback, store it back into the monitor index
        # so the next request for this path is instant
        try:
            from file_monitor import get_file_monitor
            monitor = get_file_monitor()
            rel_path = path.replace('\\', '/').strip('/')
            if monitor.get_dir_info(rel_path) is None:
                with monitor.lock:
                    monitor._dir_info[rel_path] = {
                        'file_count': info['file_count'],
                        'dir_count': info['dir_count'],
                        'total_size': info['total_size']
                    }
                print(f"📥 Stored live walk result for '{rel_path}' into index")
        except Exception:
            pass

        return jsonify(info), 200
    except Exception as e:
        print(f"❌ Error getting dir info for {path}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/assembly_status', methods=['GET'])
@login_required 
def get_assembly_status():
    """Get all assembly jobs for current session"""
    session_id = session.get('session_id')
    if not session_id:
        return jsonify({'jobs': []}), 200
    
    jobs = assembly_queue.get_jobs_for_session(session_id)
    job_data = []
    
    for job in jobs:
        job_data.append({
            'file_id': job.file_id,
            'filename': job.filename,
            'status': job.status,
            'created_at': job.created_at,
            'error_message': job.error_message
        })
    
    return jsonify({'jobs': job_data}), 200

@app.route('/api/protect_assembly/<file_id>', methods=['POST'])
@login_required
def protect_assembly_job(file_id):
    """Mark an assembly job as protected from cleanup"""
    session_id = session.get('session_id')
    if not session_id:
        return jsonify({'error': 'No session ID'}), 400
    
    # Check if this job belongs to the current session
    job = assembly_queue.get_job_status(file_id)
    if job and job.session_id == session_id:
        # Re-track this upload to prevent cleanup
        chunk_tracker.track_upload(session_id, file_id)
        print(f"🔐 Protected assembly job {file_id} from cleanup")
        return jsonify({'status': 'protected'}), 200
    
    return jsonify({'error': 'Job not found or access denied'}), 404

@app.route('/api/assembly_status/<file_id>', methods=['GET'])
@login_required
def get_single_assembly_status(file_id):
    """Get status of a specific assembly job"""
    job = assembly_queue.get_job_status(file_id)
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    # Check if user owns this job
    session_id = session.get('session_id')
    if job.session_id != session_id:
        return jsonify({'error': 'Access denied'}), 403
    
    return jsonify({
        'file_id': job.file_id,
        'filename': job.filename,
        'status': job.status,
        'created_at': job.created_at,
        'error_message': job.error_message
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
        
        response_data = {
            'success': True,
            'files': items,
            'current_path': path,
            'role': role
        }
        
        return jsonify(response_data), 200
        
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
            return jsonify({'error': 'Folder name required'}), 400

        # Only replace slashes, preserve all other characters (including +, spaces, etc.)
        foldername = foldername.replace('/', '_').replace('\\', '_')
        if not foldername:
            return jsonify({'error': 'Invalid folder name'}), 400

        # Security check: ensure path is safe
        if path and not storage.is_safe_path(path):
            return jsonify({'error': 'Invalid path'}), 400

        created = storage.create_folder(path, foldername)
        if not created:
            return jsonify({'error': 'Folder already exists or could not be created'}), 409
        else:
            return jsonify({'success': True, 'message': f'Folder "{foldername}" created successfully'}), 200
    
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

@app.route('/api/speedtest/ping', methods=['GET'])
def speedtest_ping():
    # Just return OK for latency test
    return jsonify({'ok': True})

@app.route('/api/speedtest/upload', methods=['POST'])
def speedtest_upload():
    # Receive 25MiB data, measure time server-side if needed
    file = request.files.get('data')
    if not file:
        return jsonify({'error': 'No data'}), 400
    # Optionally read to memory to simulate disk write
    file.read()
    return jsonify({'ok': True})

@app.route('/api/speedtest/download', methods=['GET'])
def speedtest_download():
    # Send 5MiB of zero bytes
    size = 5 * 1024 * 1024
    buf = io.BytesIO(b'\x00' * size)
    return send_file(buf, mimetype='application/octet-stream', as_attachment=True, download_name='speedtest.bin')

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
                
                # Get active assembly jobs to protect them from cleanup
                active_assembly_jobs = get_protected_files()
                    
                if active_assembly_jobs:
                    print(f"🔐 Protecting {len(active_assembly_jobs)} files from periodic cleanup")
                
                storage.cleanup_old_chunks(max_age_hours=1, protected_files=active_assembly_jobs)  # Clean 1+ hour old chunks
                
                # Every 4th run (1 hour), do the full 24-hour cleanup
                cleanup_counter = getattr(cleanup_worker, 'counter', 0) + 1
                cleanup_worker.counter = cleanup_counter
                
                if cleanup_counter % 4 == 0:  # Every hour
                    print("🧹 Running full chunk cleanup...")
                    storage.cleanup_old_chunks(max_age_hours=24, protected_files=active_assembly_jobs)
                    
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

def assembly_worker():
    """Background worker that processes assembly jobs"""
    print("🔄 Assembly worker started")
    
    while True:
        try:
            # Get next job from queue (blocks until available)
            job = assembly_queue.job_queue.get(timeout=10)
            
            print(f"🔨 Processing assembly job: {job.filename} (ID: {job.file_id})")
            
            # Update job status to processing
            with assembly_queue.lock:
                if job.file_id in assembly_queue.active_jobs:
                    assembly_queue.active_jobs[job.file_id].status = 'processing'
            
            try:
                # Perform the actual assembly
                success = storage.assemble_chunks(job.file_id, job.filename, job.dest_path)
                
                if success:
                    assembly_queue.complete_job(job.file_id, success=True)
                    print(f"✅ Successfully assembled: {job.filename}")
                else:
                    assembly_queue.complete_job(job.file_id, success=False, 
                                              error_message="Assembly failed - see server logs")
                    print(f"❌ Assembly failed: {job.filename}")
                    
            except Exception as e:
                error_msg = str(e)
                assembly_queue.complete_job(job.file_id, success=False, error_message=error_msg)
                print(f"❌ Assembly error for {job.filename}: {error_msg}")
            
            # Mark queue task as done
            assembly_queue.job_queue.task_done()
            
        except queue.Empty:
            # Timeout - cleanup old jobs periodically
            assembly_queue.cleanup_old_jobs()
            continue
        except Exception as e:
            print(f"❌ Assembly worker error: {e}")
            time.sleep(1)

def start_assembly_worker():
    """Start the background assembly worker"""
    worker_thread = threading.Thread(target=assembly_worker, daemon=True)
    worker_thread.start()
    print("🚀 Started background assembly worker")

def detect_ready_assemblies():
    """Detect chunks that are ready for assembly on startup"""
    try:
        chunks_dir = os.path.join(ROOT_DIR, '.chunks')
        if not os.path.exists(chunks_dir):
            return
        
        recovered_count = 0
        
        for file_id in os.listdir(chunks_dir):
            chunk_dir = os.path.join(chunks_dir, file_id)
            if not os.path.isdir(chunk_dir):
                continue
                
            try:
                # Skip if assembly is currently in progress
                protection_file = os.path.join(chunk_dir, '.assembling')
                if os.path.exists(protection_file):
                    print(f"🛡️ Skipping {file_id} - assembly protection active")
                    continue
                
                # Look for metadata file first
                metadata_file = os.path.join(chunk_dir, '.metadata')
                filename = f"recovered_file_{file_id}"
                dest_path = ""
                expected_chunks = None
                
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                            filename = metadata.get('filename', filename)
                            dest_path = metadata.get('dest_path', dest_path)
                            expected_chunks = metadata.get('total_chunks')
                            
                            print(f"📋 Found metadata for {file_id}: {filename}, expected {expected_chunks} chunks")
                    except Exception as e:
                        print(f"⚠️ Error reading metadata for {file_id}: {e}")
                        continue
                
                # Use enhanced chunk verification
                try:
                    chunk_info = storage.verify_chunks_complete(file_id, expected_chunks)
                    total_chunks = chunk_info['total_chunks']
                    
                    print(f"🔄 Found complete upload ready for assembly: {filename} ({total_chunks} chunks)")
                    assembly_queue.add_job(file_id, filename, dest_path, total_chunks)
                    recovered_count += 1
                    
                except Exception as verify_error:
                    print(f"⚠️ Chunk verification failed for {file_id}: {verify_error}")
                    # Could cleanup incomplete uploads here if desired
                    continue
                        
            except Exception as e:
                print(f"⚠️ Error checking chunks for {file_id}: {e}")
                continue
        
        if recovered_count > 0:
            print(f"🔄 Recovered {recovered_count} incomplete upload(s) for background assembly")
        else:
            print("🔍 No incomplete uploads found ready for recovery")
                
    except Exception as e:
        print(f"⚠️ Error detecting ready assemblies: {e}")

# Initialize cleanup on startup
def initialize_cleanup():
    """Initialize all cleanup processes"""
    print("🧹 Initializing cleanup systems...")
    
    # Start enhanced cleanup schedulers
    start_enhanced_cleanup_scheduler()
    start_orphan_cleanup_scheduler()
    
    # Start assembly worker
    start_assembly_worker()
    
    # Do an initial aggressive cleanup on startup
    try:
        print("🧹 Running startup cleanup...")
        
        # Get active assembly jobs to protect them (should be none on startup)
        active_assembly_jobs = get_protected_files()
            
        storage.cleanup_old_chunks(max_age_hours=0.1, protected_files=active_assembly_jobs)  # Clean chunks older than 6 minutes
        chunk_tracker.cleanup_orphaned_chunks()
        print("✅ Startup cleanup completed")
    except Exception as e:
        print(f"⚠️ Warning: Startup cleanup failed: {e}")

    # Check for any existing chunks that are ready for assembly
    print("🔍 Checking for incomplete uploads ready for assembly...")
    detect_ready_assemblies()

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
    print("   • Background file assembly with status tracking")
    print("🧹 Cleanup Schedule:")
    print("   • Every 5 minutes: Orphaned chunks cleanup")
    print("   • Every 15 minutes: Stale chunks cleanup (1+ hours)")
    print("   • Every 1 hour: Full cleanup (24+ hours)")
    print("   • On page load: Request-based cleanup")
    print("   • On logout: Session cleanup")
    print("🔄 Assembly System:")
    print("   • Background worker processes file assembly")
    print("   • Real-time status updates via API")
    print("   • Resume capability after page refresh")
    print("   • Automatic recovery of incomplete uploads")
    
    app.run(host='0.0.0.0', port=PORT, debug=False)