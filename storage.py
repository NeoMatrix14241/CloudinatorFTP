import os
import shutil
import time
import threading
import stat
from config import ROOT_DIR, CHUNK_SIZE

def ensure_root():
    if not os.path.exists(ROOT_DIR):
        os.makedirs(ROOT_DIR)

def windows_remove_readonly(func, path, _):
    """
    Error handler for Windows read-only file removal.
    If the error is due to an access being denied because the file is read-only,
    then change the file permissions and retry.
    """
    if os.path.exists(path):
        # Change the file to be writable and try again
        os.chmod(path, stat.S_IWRITE)
        func(path)

def safe_rmtree(path):
    """
    Safely remove a directory tree, handling Windows read-only files
    """
    try:
        if os.name == 'nt':  # Windows
            shutil.rmtree(path, onerror=windows_remove_readonly)
        else:  # Unix-like systems
            shutil.rmtree(path)
        return True
    except Exception as e:
        print(f"❌ Error removing directory {path}: {e}")
        return False

def safe_remove_file(file_path):
    """
    Safely remove a single file, handling Windows read-only files
    """
    try:
        if os.path.exists(file_path):
            if os.name == 'nt':  # Windows
                # Make sure file is writable before deletion
                os.chmod(file_path, stat.S_IWRITE)
            os.remove(file_path)
        return True
    except Exception as e:
        print(f"❌ Error removing file {file_path}: {e}")
        return False

def list_dir(path):
    full_path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(full_path):
        return []
    items = []
    try:
        with os.scandir(full_path) as it:
            for entry in it:
                # Skip hidden files and chunk directories
                if entry.name.startswith('.'):
                    continue

                try:
                    stat = entry.stat()

                    if entry.is_dir():
                        # Never recursively walk directories on listing —
                        # that caused 8+ second page loads with large file trees.
                        # Size and item_count are returned as None and rendered
                        # as '--' in the template. Use the /api/dir_info endpoint
                        # for on-demand lazy loading if needed.
                        size = None
                        item_count = None
                    else:
                        # Single stat call — already fetched above, instant
                        size = stat.st_size
                        item_count = None

                    items.append({
                        'name': entry.name,
                        'is_dir': entry.is_dir(),
                        'size': size,
                        'item_count': item_count,
                        'modified': stat.st_mtime
                    })
                except (OSError, IOError):
                    items.append({
                        'name': entry.name,
                        'is_dir': entry.is_dir(),
                        'size': None,
                        'item_count': None,
                        'modified': None
                    })

        # Sort: directories first, then files, both alphabetically
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    except (OSError, PermissionError):
        return []
    return items

def count_directory_items(path):
    """Count files and subdirectories in a directory"""
    full_path = os.path.join(ROOT_DIR, path)
    try:
        file_count = 0
        dir_count = 0
        
        for item in os.listdir(full_path):
            if item.startswith('.'):
                continue
            item_path = os.path.join(full_path, item)
            if os.path.isdir(item_path):
                dir_count += 1
            else:
                file_count += 1
        
        return {'files': file_count, 'dirs': dir_count}
    except (OSError, IOError):
        return {'files': 0, 'dirs': 0}

def save_chunk(file_id, chunk_num, chunk_data):
    tmp_dir = os.path.join(ROOT_DIR, '.chunks', file_id)
    os.makedirs(tmp_dir, exist_ok=True)
    chunk_path = os.path.join(tmp_dir, f'{chunk_num}')
    try:
        with open(chunk_path, 'wb') as f:
            f.write(chunk_data)
        
        # Ensure the chunk file is writable (important for Windows)
        if os.name == 'nt':
            os.chmod(chunk_path, stat.S_IWRITE | stat.S_IREAD)
        
        # Update timestamp for cleanup tracking
        timestamp_file = os.path.join(tmp_dir, '.timestamp')
        with open(timestamp_file, 'w') as f:
            f.write(str(time.time()))
        
        # Ensure timestamp file is also writable
        if os.name == 'nt':
            os.chmod(timestamp_file, stat.S_IWRITE | stat.S_IREAD)
        
        return True
    except (OSError, IOError) as e:
        print(f"❌ Error saving chunk {chunk_num} for {file_id}: {e}")
        return False

def verify_chunks_complete(file_id, expected_chunks=None):
    """Verify all chunks exist and map them for assembly"""
    tmp_dir = os.path.join(ROOT_DIR, '.chunks', file_id)
    
    if not os.path.exists(tmp_dir):
        raise FileNotFoundError(f"Chunk directory not found for {file_id}")
    
    # Get all chunk files (exclude metadata files)
    chunk_files = [f for f in os.listdir(tmp_dir) 
                  if f.isdigit() and os.path.isfile(os.path.join(tmp_dir, f))]
    
    if not chunk_files:
        raise FileNotFoundError(f"No chunk files found for {file_id}")
    
    # Sort chunks numerically
    chunk_nums = sorted([int(f) for f in chunk_files])
    total_chunks = len(chunk_nums)
    
    # If expected chunks is provided, verify count
    if expected_chunks is not None and total_chunks != expected_chunks:
        raise ValueError(f"Expected {expected_chunks} chunks but found {total_chunks}")
    
    # Verify sequential chunks (0, 1, 2, ...)
    expected_sequence = list(range(total_chunks))
    if chunk_nums != expected_sequence:
        missing_chunks = set(expected_sequence) - set(chunk_nums)
        extra_chunks = set(chunk_nums) - set(expected_sequence)
        error_msg = f"Chunks are not sequential for {file_id}."
        if missing_chunks:
            error_msg += f" Missing chunks: {sorted(missing_chunks)}"
        if extra_chunks:
            error_msg += f" Extra chunks: {sorted(extra_chunks)}"
        raise ValueError(error_msg)
    
    # Create chunk map with file paths and verify each chunk exists and is readable
    chunk_map = {}
    total_size = 0
    
    for i in range(total_chunks):
        chunk_path = os.path.join(tmp_dir, str(i))
        
        if not os.path.exists(chunk_path):
            raise FileNotFoundError(f"Chunk {i} file not found at {chunk_path}")
        
        if not os.path.isfile(chunk_path):
            raise ValueError(f"Chunk {i} is not a file: {chunk_path}")
        
        # Check if chunk is readable and get size
        try:
            chunk_size = os.path.getsize(chunk_path)
            if chunk_size == 0:
                raise ValueError(f"Chunk {i} is empty")
            total_size += chunk_size
            
            # Test read access
            with open(chunk_path, 'rb') as test_file:
                test_file.read(1)  # Read one byte to verify access
                
        except (OSError, IOError) as e:
            raise IOError(f"Cannot read chunk {i}: {e}")
        
        chunk_map[i] = {
            'path': chunk_path,
            'size': chunk_size
        }
    
    print(f"✅ Chunk verification complete for {file_id}: {total_chunks} chunks, {total_size} bytes total")
    return {
        'total_chunks': total_chunks,
        'total_size': total_size,
        'chunk_map': chunk_map,
        'tmp_dir': tmp_dir
    }

def assemble_chunks(file_id, filename, dest_path=''):
    """Enhanced chunk assembly with pre-verification and protection"""
    print(f"🔨 Starting assembly for {filename} (ID: {file_id})")
    
    # Only replace slashes, preserve all other characters
    safe_filename = filename.replace('/', '_').replace('\\', '_')
    target_dir = os.path.join(ROOT_DIR, dest_path) if dest_path else ROOT_DIR
    target_path = os.path.join(target_dir, safe_filename)
    os.makedirs(target_dir, exist_ok=True)

    try:
        # Step 1: Verify and map all chunks first
        print(f"🔍 Verifying chunks for {file_id}...")
        chunk_info = verify_chunks_complete(file_id)
        total_chunks = chunk_info['total_chunks']
        chunk_map = chunk_info['chunk_map']
        tmp_dir = chunk_info['tmp_dir']
        
        print(f"✅ All {total_chunks} chunks verified and mapped for {filename}")
        
        # Step 2: Create protection marker to prevent cleanup during assembly
        protection_file = os.path.join(tmp_dir, '.assembling')
        try:
            with open(protection_file, 'w') as f:
                f.write(f"assembling:{time.time()}")
            print(f"🛡️ Assembly protection enabled for {file_id}")
        except Exception as e:
            print(f"⚠️ Warning: Could not create protection file: {e}")
        
        # Step 3: Perform assembly using verified chunk map
        print(f"🔧 Assembling {total_chunks} chunks into {target_path}")
        
        with open(target_path, 'wb') as outfile:
            for i in range(total_chunks):
                chunk_info_item = chunk_map[i]
                chunk_path = chunk_info_item['path']
                chunk_size = chunk_info_item['size']
                
                print(f"📦 Processing chunk {i+1}/{total_chunks} ({chunk_size} bytes)")
                
                try:
                    with open(chunk_path, 'rb') as infile:
                        chunk_data = infile.read()
                        if len(chunk_data) != chunk_size:
                            raise IOError(f"Chunk {i} size mismatch: expected {chunk_size}, got {len(chunk_data)}")
                        outfile.write(chunk_data)
                except Exception as e:
                    raise IOError(f"Failed to read chunk {i}: {e}")

        # Step 4: Verify final file
        final_size = os.path.getsize(target_path)
        expected_size = chunk_info['total_size']
        
        if final_size != expected_size:
            raise ValueError(f"Final file size mismatch: expected {expected_size}, got {final_size}")

        # Ensure the final file is writable
        if os.name == 'nt':
            os.chmod(target_path, stat.S_IWRITE | stat.S_IREAD)

        print(f"✅ Assembly successful: {filename} ({final_size} bytes)")
        
        # Step 5: Remove protection and cleanup chunks
        try:
            if os.path.exists(protection_file):
                os.remove(protection_file)
        except Exception as e:
            print(f"⚠️ Warning: Could not remove protection file: {e}")
            
        cleanup_chunks(file_id)
        return True
        
    except Exception as e:
        print(f"❌ Assembly failed for {filename}: {e}")
        # Cleanup on failure
        try:
            if os.path.exists(target_path):
                safe_remove_file(target_path)
            # Remove protection file if it exists
            protection_file = os.path.join(ROOT_DIR, '.chunks', file_id, '.assembling')
            if os.path.exists(protection_file):
                os.remove(protection_file)
        except Exception as cleanup_error:
            print(f"⚠️ Warning: Cleanup after assembly failure had issues: {cleanup_error}")
        raise e

def cleanup_chunks(file_id, total_chunks=None):
    """Clean up temporary chunk files using Windows-safe deletion"""
    tmp_dir = os.path.join(ROOT_DIR, '.chunks', file_id)
    
    # Check for assembly protection marker
    protection_file = os.path.join(tmp_dir, '.assembling')
    if os.path.exists(protection_file):
        try:
            with open(protection_file, 'r') as f:
                protection_data = f.read().strip()
                if protection_data.startswith('assembling:'):
                    timestamp = float(protection_data.split(':', 1)[1])
                    # Only skip cleanup if assembly started recently (within 10 minutes)
                    if time.time() - timestamp < 600:
                        print(f"🛡️ Skipping cleanup for {file_id} - assembly in progress")
                        return
                    else:
                        print(f"⚠️ Assembly protection expired for {file_id}, proceeding with cleanup")
        except Exception as e:
            print(f"⚠️ Warning: Could not read protection file for {file_id}: {e}")
    
    try:
        if os.path.exists(tmp_dir):
            success = safe_rmtree(tmp_dir)
            if success:
                print(f"🧹 Cleaned up chunks for file_id: {file_id}")
            else:
                print(f"⚠️ Partial cleanup failure for file_id: {file_id}")
        
        # Clean up parent chunks directory if empty
        chunks_dir = os.path.join(ROOT_DIR, '.chunks')
        if os.path.exists(chunks_dir):
            try:
                # Only remove if it's actually empty
                if not os.listdir(chunks_dir):
                    os.rmdir(chunks_dir)
                    print("🧹 Removed empty chunks directory")
            except OSError:
                pass  # Directory not empty, that's fine
    except (OSError, IOError) as e:
        print(f"⚠️ Warning: Could not cleanup chunks for {file_id}: {e}")

def cleanup_old_chunks(max_age_hours=24, protected_files=None):
    """Enhanced cleanup function with Windows-safe deletion and assembly protection"""
    chunks_dir = os.path.join(ROOT_DIR, '.chunks')
    if not os.path.exists(chunks_dir):
        return
    
    if protected_files is None:
        protected_files = set()
    
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    cleaned_count = 0
    
    try:
        for file_id in os.listdir(chunks_dir):
            chunk_dir = os.path.join(chunks_dir, file_id)
            if not os.path.isdir(chunk_dir):
                continue
            
            # CRITICAL: Never cleanup chunks for files currently being assembled
            if file_id in protected_files:
                print(f"🔐 Skipping cleanup for {file_id} - currently being assembled")
                continue
            
            # Also check for assembly protection marker
            assembly_marker = os.path.join(chunk_dir, '.assembling')
            if os.path.exists(assembly_marker):
                print(f"🔐 Skipping cleanup for {file_id} - assembly marker present")
                continue
            
            should_cleanup = False
            cleanup_reason = ""
            
            # Check timestamp file
            timestamp_file = os.path.join(chunk_dir, '.timestamp')
            if os.path.exists(timestamp_file):
                try:
                    with open(timestamp_file, 'r') as f:
                        timestamp = float(f.read().strip())
                    
                    if current_time - timestamp > max_age_seconds:
                        should_cleanup = True
                        cleanup_reason = f"timestamp older than {max_age_hours}h"
                except (ValueError, OSError):
                    # If we can't read the timestamp, use directory modification time
                    try:
                        dir_mtime = os.path.getmtime(chunk_dir)
                        if current_time - dir_mtime > max_age_seconds:
                            should_cleanup = True
                            cleanup_reason = "corrupted timestamp, using mtime"
                    except OSError:
                        # If we can't get mtime either, cleanup if very old max_age
                        if max_age_hours <= 1:  # Only for aggressive cleanup
                            should_cleanup = True
                            cleanup_reason = "corrupted metadata"
            else:
                # No timestamp file, use directory modification time
                try:
                    dir_mtime = os.path.getmtime(chunk_dir)
                    if current_time - dir_mtime > max_age_seconds:
                        should_cleanup = True
                        cleanup_reason = "no timestamp file, using mtime"
                except OSError:
                    # Can't get modification time, cleanup if doing aggressive cleanup
                    if max_age_hours <= 1:
                        should_cleanup = True
                        cleanup_reason = "no metadata available"
            
            # ADDITIONAL CHECK: Clean up incomplete chunks that are older than 1 hour
            # regardless of the max_age_hours parameter (for aborted uploads)
            if not should_cleanup and max_age_hours > 1:
                one_hour_ago = current_time - 3600  # 1 hour in seconds
                try:
                    if os.path.exists(timestamp_file):
                        with open(timestamp_file, 'r') as f:
                            timestamp = float(f.read().strip())
                        if timestamp < one_hour_ago:
                            should_cleanup = True
                            cleanup_reason = "stale upload (>1hr old)"
                    else:
                        dir_mtime = os.path.getmtime(chunk_dir)
                        if dir_mtime < one_hour_ago:
                            should_cleanup = True
                            cleanup_reason = "stale upload by mtime (>1hr old)"
                except (ValueError, OSError):
                    pass
            
            if should_cleanup:
                # Check for assembly protection before cleanup
                protection_file = os.path.join(chunk_dir, '.assembling')
                if os.path.exists(protection_file):
                    try:
                        with open(protection_file, 'r') as f:
                            protection_data = f.read().strip()
                            if protection_data.startswith('assembling:'):
                                timestamp = float(protection_data.split(':', 1)[1])
                                # Only skip cleanup if assembly started recently (within 10 minutes)
                                if time.time() - timestamp < 600:
                                    print(f"🛡️ Skipping cleanup for {file_id} - assembly in progress")
                                    continue
                                else:
                                    print(f"⚠️ Assembly protection expired for {file_id}, proceeding with cleanup")
                    except Exception as e:
                        print(f"⚠️ Warning: Could not read protection file for {file_id}: {e}")
                
                success = safe_rmtree(chunk_dir)
                if success:
                    cleaned_count += 1
                    print(f"🧹 Cleaned up chunks for file_id: {file_id} ({cleanup_reason})")
                else:
                    print(f"❌ Failed to cleanup chunks for {file_id} ({cleanup_reason})")
        
        # Try to remove the chunks directory if it's empty
        try:
            if not os.listdir(chunks_dir):
                os.rmdir(chunks_dir)
                print("🧹 Removed empty chunks directory")
        except OSError:
            pass
            
        if cleaned_count > 0:
            print(f"🧹 Chunk cleanup completed: {cleaned_count} old chunk directories removed")
        elif max_age_hours <= 1:  # Only log for aggressive cleanup
            print(f"🧹 Aggressive cleanup completed: no stale chunks found")
            
    except OSError:
        print("⚠️ Warning: Could not access chunks directory for cleanup")

def start_cleanup_scheduler():
    """Original cleanup scheduler - now deprecated in favor of enhanced version"""
    print("⚠️ Warning: Using deprecated cleanup scheduler. Use enhanced version in app.py instead.")
    def cleanup_worker():
        while True:
            try:
                # Sleep for 1 hour
                time.sleep(3600)
                cleanup_old_chunks(max_age_hours=24)
            except Exception as e:
                print(f"❌ Error in cleanup worker: {e}")
    
    cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
    print("📧 Started basic chunk cleanup scheduler (runs every hour)")

def create_folder(path, foldername):
    # Only replace slashes, preserve all other characters
    safe_foldername = foldername.replace('/', '_').replace('\\', '_')
    target_dir = os.path.join(ROOT_DIR, path) if path else ROOT_DIR
    folder_path = os.path.join(target_dir, safe_foldername)
    if os.path.exists(folder_path):
        return False
    try:
        os.makedirs(folder_path)
        return True
    except Exception:
        return False

def delete_path(path):
    full_path = os.path.join(ROOT_DIR, path)
    try:
        if os.path.isdir(full_path):
            return safe_rmtree(full_path)
        elif os.path.isfile(full_path):
            return safe_remove_file(full_path)
        return True
    except (OSError, IOError):
        return False

def get_file_size(path):
    """Get file size in bytes"""
    full_path = os.path.join(ROOT_DIR, path)
    try:
        if os.path.isfile(full_path):
            return os.path.getsize(full_path)
        return 0
    except (OSError, IOError):
        return 0

def get_directory_size(path):
    """Get total size of directory recursively"""
    full_path = os.path.join(ROOT_DIR, path)
    total_size = 0
    try:
        if os.path.isfile(full_path):
            return os.path.getsize(full_path)
        elif os.path.isdir(full_path):
            for dirpath, dirnames, filenames in os.walk(full_path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(file_path)
                    except (OSError, IOError):
                        continue
        return total_size
    except (OSError, IOError):
        return 0

def get_dir_info(path):
    """
    Get shallow item count + recursive total size for a directory.
    Checks file_monitor index first — instant if indexed.
    Falls back to a live walk only if the path isn't in the index yet
    (e.g. brand-new folder not yet reconciled).
    """
    # Normalize to forward slashes, strip leading/trailing slashes
    rel_path = path.replace('\\', '/').strip('/')

    # Try the in-memory index first — this is the fast path
    try:
        from file_monitor import get_file_monitor
        monitor = get_file_monitor()
        cached = monitor.get_dir_info(rel_path)
        if cached is not None:
            return {
                'file_count': cached.get('file_count', 0),
                'dir_count': cached.get('dir_count', 0),
                'total_size': cached.get('total_size', 0)
            }
    except Exception as e:
        print(f"⚠️ Cache lookup failed for '{rel_path}': {e}")

    # Fallback — live walk for paths not yet indexed
    print(f"⚠️ '{rel_path}' not in index yet — doing live walk (will be cached after next reconcile)")
    full_path = os.path.join(ROOT_DIR, path)
    file_count = 0
    dir_count = 0
    total_size = 0

    try:
        with os.scandir(full_path) as it:
            for entry in it:
                if entry.name.startswith('.'):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    dir_count += 1
                else:
                    file_count += 1

        for dirpath, dirnames, filenames in os.walk(full_path):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            for filename in filenames:
                if filename.startswith('.'):
                    continue
                try:
                    total_size += os.path.getsize(os.path.join(dirpath, filename))
                except (OSError, IOError):
                    continue
    except (OSError, IOError):
        pass

    return {
        'file_count': file_count,
        'dir_count': dir_count,
        'total_size': total_size
    }

def is_safe_path(path):
    """Check if path is safe (no directory traversal)"""
    try:
        # Resolve the path and check if it's within ROOT_DIR
        resolved = os.path.realpath(os.path.join(ROOT_DIR, path))
        root_real = os.path.realpath(ROOT_DIR)
        return resolved.startswith(root_real)
    except:
        return False

def is_valid_path(path):
    """Check if path is safe and exists"""
    if not path:
        return True  # Empty path is valid (root directory)
    
    # First check if path is safe
    if not is_safe_path(path):
        return False
    
    # Check if path exists and is a directory
    try:
        full_path = os.path.join(ROOT_DIR, path)
        return os.path.exists(full_path) and os.path.isdir(full_path)
    except:
        return False

def get_storage_stats():
    """Get storage statistics with enhanced Android/Termux compatibility"""
    try:
        print(f"📊 Getting storage stats for ROOT_DIR: {ROOT_DIR}")
        print(f"📊 Platform: {os.name}, hasattr(os, 'statvfs'): {hasattr(os, 'statvfs')}")
        
        # Determine the best path for disk usage calculation
        disk_usage_path = ROOT_DIR
        
        # Special handling for Android/Termux
        if 'TERMUX_VERSION' in os.environ or os.path.exists('/data/data/com.termux'):
            print("📱 Detected Termux/Android environment")
            
            # For Termux, try to use the Android shared storage path for more accurate disk usage
            android_storage_paths = [
                '/storage/emulated/0',  # Main internal storage
                '/sdcard',              # Alternative path
                '/storage/self/primary' # Another alternative
            ]
            
            for path in android_storage_paths:
                if os.path.exists(path) and os.access(path, os.R_OK):
                    disk_usage_path = path
                    print(f"📱 Using Android storage path for disk usage: {disk_usage_path}")
                    break
            
            if disk_usage_path == ROOT_DIR:
                print(f"📱 Using ROOT_DIR for disk usage: {disk_usage_path}")
        
        # Get total, used, and free space
        if hasattr(os, 'statvfs'):  # Unix-like systems (Linux, Android/Termux)
            print("📊 Using os.statvfs for disk usage")
            try:
                stat = os.statvfs(disk_usage_path)
                print(f"📊 statvfs result: f_blocks={stat.f_blocks}, f_frsize={stat.f_frsize}, f_bavail={stat.f_bavail}")
                total = stat.f_blocks * stat.f_frsize
                free = stat.f_bavail * stat.f_frsize
                used = total - free
                print(f"📊 Calculated disk usage - Total: {total}, Used: {used}, Free: {free}")
            except OSError as e:
                print(f"❌ statvfs failed on {disk_usage_path}: {e}, trying shutil fallback")
                # Fallback to shutil.disk_usage for Android/Termux if statvfs fails
                try:
                    import shutil
                    total, used, free = shutil.disk_usage(disk_usage_path)
                    print(f"📊 Fallback shutil.disk_usage on {disk_usage_path} - Total: {total}, Used: {used}, Free: {free}")
                except Exception as fallback_e:
                    print(f"❌ Fallback also failed on {disk_usage_path}: {fallback_e}")
                    # Try ROOT_DIR as last resort
                    if disk_usage_path != ROOT_DIR:
                        print(f"📊 Trying ROOT_DIR as last resort: {ROOT_DIR}")
                        try:
                            import shutil
                            total, used, free = shutil.disk_usage(ROOT_DIR)
                            print(f"📊 ROOT_DIR disk usage - Total: {total}, Used: {used}, Free: {free}")
                        except Exception as final_e:
                            print(f"❌ All disk usage methods failed: {final_e}")
                            total = used = free = 0
                    else:
                        total = used = free = 0
        else:  # Windows
            print("📊 Using shutil.disk_usage for Windows")
            import shutil
            total, used, free = shutil.disk_usage(ROOT_DIR)
            print(f"📊 Windows disk usage - Total: {total}, Used: {used}, Free: {free}")
        
        # First, return disk stats immediately - this is the critical info
        disk_stats = {
            'total_space': total,
            'used_space': used,
            'free_space': free,
        }
        print(f"📊 Disk stats ready: {disk_stats}")
        
        # Now try to count files with timeout protection
        print(f"📊 Starting file and directory counting in: {ROOT_DIR}")
        
        file_count = 0
        dir_count = 0
        total_size = 0
        
        try:
            # Add timeout protection for file counting (web-safe version)
            import time
            
            start_time = time.time()
            max_files_to_check = 10000  # Limit for very large directories
            files_checked = 0
            timeout_seconds = 5
            
            print(f"📊 Starting file walk with {timeout_seconds}s timeout and {max_files_to_check} file limit")
            
            for root, dirs, files in os.walk(ROOT_DIR):
                # Skip hidden directories like .chunks
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                # Check timeout manually (web-safe approach)
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    print(f"⏱️ File counting timeout reached ({elapsed:.1f}s), using partial results")
                    print(f"📊 Partial results: {file_count} files, {dir_count} dirs, {files_checked} files checked")
                    break
                
                dir_count += len(dirs)
                file_count += len(files)
                
                # Process files in batches to check timeout more frequently
                for i, file in enumerate(files):
                    try:
                        if files_checked >= max_files_to_check:
                            print(f"📊 Reached max file check limit ({max_files_to_check}), using partial results")
                            break
                            
                        file_path = os.path.join(root, file)
                        file_size = os.path.getsize(file_path)
                        total_size += file_size
                        files_checked += 1
                        
                        # Check timeout every 100 files or every 500ms
                        if (files_checked % 100 == 0) or (time.time() - start_time > timeout_seconds):
                            elapsed = time.time() - start_time
                            if elapsed > timeout_seconds:
                                print(f"⏱️ File counting timeout during size calculation ({elapsed:.1f}s)")
                                break
                    except (OSError, IOError) as file_error:
                        print(f"⚠️ Could not get size for {file_path}: {file_error}")
                        continue
                
                # Break out of directory loop if timeout occurred
                if time.time() - start_time > timeout_seconds or files_checked >= max_files_to_check:
                    break
            
            elapsed = time.time() - start_time
            print(f"📊 File counting complete in {elapsed:.2f}s - Files: {file_count}, Dirs: {dir_count}, Total size: {total_size} (checked {files_checked} files)")
            
        except TimeoutError:
            print("⏱️ File counting timed out, returning disk stats with partial file info")
        except Exception as walk_e:
            print(f"❌ Error during file walk: {walk_e}")
            import traceback
            traceback.print_exc()
            # Continue with partial or 0 values for file counts
        
        result = {
            'total_space': total,
            'used_space': used,
            'free_space': free,
            'file_count': file_count,
            'dir_count': dir_count,
            'content_size': total_size
        }
        
        print(f"📊 Final storage stats result: {result}")
        return result
        
    except Exception as e:
        print(f"❌ Critical error getting storage stats: {e}")
        import traceback
        traceback.print_exc()
        return {
            'total_space': 0,
            'used_space': 0,
            'free_space': 0,
            'file_count': 0,
            'dir_count': 0,
            'content_size': 0
        }

def move_item(source_path, dest_path):
    """Move a file or directory from source to destination"""
    source_full = os.path.join(ROOT_DIR, source_path)
    dest_full = os.path.join(ROOT_DIR, dest_path)
    
    try:
        # Ensure destination directory exists
        dest_dir = os.path.dirname(dest_full)
        os.makedirs(dest_dir, exist_ok=True)
        
        # Perform the move
        shutil.move(source_full, dest_full)
        return True
    except (OSError, IOError, shutil.Error) as e:
        print(f"❌ Error moving {source_path} to {dest_path}: {e}")
        return False

def copy_item(source_path, dest_path):
    """Copy a file or directory from source to destination"""
    source_full = os.path.join(ROOT_DIR, source_path)
    dest_full = os.path.join(ROOT_DIR, dest_path)
    
    try:
        # Ensure destination directory exists
        dest_dir = os.path.dirname(dest_full)
        os.makedirs(dest_dir, exist_ok=True)
        
        # Perform the copy
        if os.path.isdir(source_full):
            shutil.copytree(source_full, dest_full)
        else:
            shutil.copy2(source_full, dest_full)
        return True
    except (OSError, IOError, shutil.Error) as e:
        print(f"❌ Error copying {source_path} to {dest_path}: {e}")
        return False

def get_chunk_info():
    """Get information about current chunk usage"""
    chunks_dir = os.path.join(ROOT_DIR, '.chunks')
    if not os.path.exists(chunks_dir):
        return {
            'total_chunk_dirs': 0,
            'total_chunk_size': 0,
            'chunk_dirs': []
        }
    
    chunk_dirs = []
    total_size = 0
    
    try:
        for file_id in os.listdir(chunks_dir):
            chunk_dir = os.path.join(chunks_dir, file_id)
            if not os.path.isdir(chunk_dir):
                continue
            
            # Calculate size of this chunk directory
            dir_size = 0
            chunk_count = 0
            timestamp = None
            
            try:
                # Get timestamp
                timestamp_file = os.path.join(chunk_dir, '.timestamp')
                if os.path.exists(timestamp_file):
                    with open(timestamp_file, 'r') as f:
                        timestamp = float(f.read().strip())
                
                # Count chunks and calculate size
                for item in os.listdir(chunk_dir):
                    if item == '.timestamp':
                        continue
                    chunk_file = os.path.join(chunk_dir, item)
                    if os.path.isfile(chunk_file):
                        size = os.path.getsize(chunk_file)
                        dir_size += size
                        chunk_count += 1
                
                total_size += dir_size
                
                chunk_dirs.append({
                    'file_id': file_id,
                    'chunk_count': chunk_count,
                    'size': dir_size,
                    'timestamp': timestamp,
                    'age_minutes': (time.time() - timestamp) / 60 if timestamp else None
                })
                
            except (OSError, ValueError):
                # Handle errors for individual directories
                chunk_dirs.append({
                    'file_id': file_id,
                    'chunk_count': 0,
                    'size': 0,
                    'timestamp': None,
                    'age_minutes': None,
                    'error': 'Could not read directory'
                })
    
    except OSError:
        pass
    
    return {
        'total_chunk_dirs': len(chunk_dirs),
        'total_chunk_size': total_size,
        'chunk_dirs': chunk_dirs
    }

# Enhanced manual cleanup function for testing/debugging and comprehensive cleanup
def manual_chunks_cleanup():
    """Manual cleanup function - removes all chunks regardless of age with detailed reporting"""
    chunks_dir = os.path.join(ROOT_DIR, '.chunks')
    if not os.path.exists(chunks_dir):
        print("🧹 No chunks directory found - nothing to clean")
        return True
    
    try:
        print(f"🧹 Starting comprehensive manual cleanup of {chunks_dir}")
        
        # Get information about what we're cleaning
        chunk_info = []
        total_size = 0
        
        for file_id in os.listdir(chunks_dir):
            chunk_dir = os.path.join(chunks_dir, file_id)
            if not os.path.isdir(chunk_dir):
                continue
                
            try:
                dir_size = 0
                chunk_count = 0
                timestamp = None
                
                # Get timestamp if available
                timestamp_file = os.path.join(chunk_dir, '.timestamp')
                if os.path.exists(timestamp_file):
                    try:
                        with open(timestamp_file, 'r') as f:
                            timestamp = float(f.read().strip())
                    except (ValueError, OSError):
                        pass
                
                # Count chunks and calculate size
                for item in os.listdir(chunk_dir):
                    item_path = os.path.join(chunk_dir, item)
                    if os.path.isfile(item_path):
                        try:
                            size = os.path.getsize(item_path)
                            if item != '.timestamp':
                                chunk_count += 1
                            dir_size += size
                        except OSError:
                            pass
                
                total_size += dir_size
                age_minutes = (time.time() - timestamp) / 60 if timestamp else None
                
                chunk_info.append({
                    'file_id': file_id,
                    'chunks': chunk_count,
                    'size': dir_size,
                    'age_minutes': age_minutes
                })
                
            except Exception as e:
                print(f"⚠️  Error analyzing {file_id}: {e}")
                chunk_info.append({
                    'file_id': file_id,
                    'chunks': 0,
                    'size': 0,
                    'age_minutes': None,
                    'error': str(e)
                })
        
        # Report what we found
        if chunk_info:
            print(f"📊 Found {len(chunk_info)} chunk directories totaling {total_size // (1024*1024)} MB:")
            for info in chunk_info[:10]:  # Show first 10
                age_str = f"{info['age_minutes']:.1f}min" if info['age_minutes'] else "unknown age"
                size_str = f"{info['size'] // 1024}KB" if info['size'] > 0 else "0KB"
                chunk_str = f"{info['chunks']} chunks" if info['chunks'] > 0 else "no chunks"
                print(f"  • {info['file_id']}: {chunk_str}, {size_str}, {age_str}")
            
            if len(chunk_info) > 10:
                print(f"  ... and {len(chunk_info) - 10} more directories")
        
        # Perform the cleanup using Windows-safe deletion
        success = safe_rmtree(chunks_dir)
        
        if success:
            print(f"✅ Manual cleanup completed successfully")
            print(f"   • Removed {len(chunk_info)} chunk directories")
            print(f"   • Freed {total_size // (1024*1024)} MB of space")
        else:
            print(f"⚠️  Manual cleanup completed with some errors")
            print(f"   • Attempted to remove {len(chunk_info)} chunk directories")
            
        return success
        
    except Exception as e:
        print(f"❌ Manual cleanup failed: {e}")
        return False

def emergency_cleanup_all():
    """Emergency cleanup function that attempts to remove all temporary files"""
    print("🚨 Running emergency cleanup...")
    
    try:
        chunks_dir = os.path.join(ROOT_DIR, '.chunks')
        temp_files_removed = 0
        
        # Try to clean up any .tmp files in root directory
        for item in os.listdir(ROOT_DIR):
            if item.endswith('.tmp') or item.endswith('.part'):
                temp_file = os.path.join(ROOT_DIR, item)
                try:
                    if safe_remove_file(temp_file):
                        temp_files_removed += 1
                        print(f"🧹 Removed temp file: {item}")
                except Exception as e:
                    print(f"⚠️  Could not remove temp file {item}: {e}")
        
        # Clean up chunks directory
        manual_chunks_cleanup()
        
        print(f"🚨 Emergency cleanup completed. Removed {temp_files_removed} temp files.")
        return True
        
    except Exception as e:
        print(f"❌ Emergency cleanup failed: {e}")
        return False

print(f"📦 Storage module loaded with Windows support - cleanup managed by app.py")
print(f"🪟 Platform: {os.name} ({'Windows' if os.name == 'nt' else 'Unix-like'})")
