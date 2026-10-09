"""
routes/uploads.py - uploads, chunks, assembly and the cleanup schedulers: /upload, /cleanup_chunks,
/cancel_upload, /admin/cleanup_chunks, /admin/chunk_stats, /admin/upload_status,
/api/assembly_status*, /api/protect_assembly and the start_* startup functions
(Phase 8 of the split, CLAUDE.md 4.76).

Moved verbatim from app.py. Nothing here runs at import: the schedulers and the assembly worker
are started by initialize_cleanup(), which stays in app.py. Gets shared objects via
`from core import ...`; imports routes.shares only for _prune_expired_shares.
"""

from core import (
    _trigger_reconcile,
    app,
    assembly_queue,
    chunk_tracker,
    get_protected_files,
    login_required,
)

from quart import jsonify, request, session
from werkzeug.exceptions import ClientDisconnected
import os
import shutil
import json
import asyncio
import threading
import time
import uuid
import queue
from config import (
    ROOT_DIR,
    CHUNK_SIZE,
    ENABLE_CHUNKED_UPLOADS,
    ALLOWED_EXTENSIONS,
)
from database import db
from auth import current_user, get_role
import storage
from routes.shares import _prune_expired_shares


@app.route("/upload", methods=["POST"])
@login_required
async def upload():
    session_id = session.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
        session["session_id"] = session_id

    # Initialize these variables outside the try block to ensure they're available in the except blocks
    file_id = None
    filename = None

    try:
        role = get_role(current_user())
        if role != "readwrite":
            return "Permission denied", 403

        file_id = (await request.form).get("file_id")
        chunk_num = (await request.form).get("chunk_num")
        total_chunks = (await request.form).get("total_chunks")
        filename = (await request.form).get("filename", "")
        dest_path = (await request.form).get("dest_path", "")

        # Validate filename (must not be empty)
        if not filename:
            return "Filename is required", 400

        # Remove all sanitization, only check for empty and slashes
        if "/" in filename or "\\" in filename:
            return "Invalid filename", 400

        # Enforce configured file-type allowlist, if one is set.
        # ALLOWED_EXTENSIONS = None means "allow all" (config.py default).
        if ALLOWED_EXTENSIONS is not None:
            ext = os.path.splitext(filename)[1].lower().lstrip(".")
            if ext not in ALLOWED_EXTENSIONS:
                return (
                    f"File type '.{ext}' not allowed. Allowed types: "
                    f"{', '.join(sorted(ALLOWED_EXTENSIONS))}",
                    400,
                )

        # Security check: ensure destination path is safe
        if dest_path and not storage.is_safe_path(dest_path):
            return "Invalid destination path", 400

        if (
            ENABLE_CHUNKED_UPLOADS
            and chunk_num is not None
            and total_chunks is not None
        ):
            # Chunked upload handling
            try:
                chunk_num = int(chunk_num)
                total_chunks = int(total_chunks)
            except ValueError:
                return "Invalid chunk parameters", 400

            if not file_id:
                return "File ID is required for chunked upload", 400

            # Track this upload
            chunk_tracker.track_upload(session_id, file_id)

            chunk = (await request.files).get("chunk")
            if not chunk:
                return "No chunk data received", 400

            chunk_data = chunk.read()
            if len(chunk_data) > CHUNK_SIZE:
                return f"Chunk too large (max {CHUNK_SIZE} bytes)", 413

            # Save chunk
            if not storage.save_chunk(file_id, chunk_num, chunk_data):
                # Cleanup on failure
                chunk_tracker.untrack_upload(session_id, file_id)
                storage.cleanup_chunks(file_id)
                return "Failed to save chunk", 500

            print(
                f"📦 Saved chunk {chunk_num + 1}/{total_chunks} for {filename} (ID: {file_id})"
            )

            # If this is the last chunk, queue for background assembly
            if chunk_num == total_chunks - 1:
                try:
                    # Save metadata for assembly worker
                    chunk_dir = os.path.join(ROOT_DIR, ".chunks", file_id)
                    metadata_file = os.path.join(chunk_dir, ".metadata")
                    metadata = {
                        "filename": filename,
                        "dest_path": dest_path,
                        "total_chunks": total_chunks,
                        "session_id": session_id,
                        "timestamp": time.time(),
                    }
                    with open(metadata_file, "w") as f:
                        json.dump(metadata, f)

                    # Add to background assembly queue
                    assembly_queue.add_job(
                        file_id, filename, dest_path, total_chunks, session_id
                    )

                    print(f"🔄 Queued {filename} for background assembly")
                    return (
                        jsonify(
                            {
                                "status": "upload_complete",
                                "message": f"Upload complete - processing {filename}...",
                                "file_id": file_id,
                                "assembly_queued": True,
                            }
                        ),
                        200,
                    )

                except Exception as e:
                    # Failed to queue assembly - cleanup
                    chunk_tracker.untrack_upload(session_id, file_id)
                    storage.cleanup_chunks(file_id)
                    print(f"❌ Failed to queue assembly for {filename}: {e}")
                    return f"Failed to queue file assembly: {str(e)}", 500

            return f"Chunk {chunk_num + 1}/{total_chunks} uploaded successfully", 200

        else:
            # Whole file upload handling
            uploaded_file = (await request.files).get("file")
            if not uploaded_file or uploaded_file.filename == "":
                return "No file selected", 400

            # Use provided filename or fall back to uploaded filename
            if not filename:
                filename = uploaded_file.filename
                if not filename:
                    return "Invalid filename", 400
            # Only check for slashes
            if "/" in filename or "\\" in filename:
                return "Invalid filename", 400

            # Construct target path
            target_dir = os.path.join(ROOT_DIR, dest_path) if dest_path else ROOT_DIR
            target_path = os.path.join(target_dir, filename)

            # Ensure target directory exists
            os.makedirs(target_dir, exist_ok=True)

            # Conflict check: return 409 if file exists and overwrite not explicitly requested
            overwrite = (await request.form).get("overwrite", "0")
            if (
                os.path.exists(target_path)
                and os.path.isfile(target_path)
                and overwrite != "1"
            ):
                return "File already exists", 409

            # Save file — retry on Windows file-lock errors (e.g. FastCopy holding a write lock).
            # Without this, save() blocks indefinitely waiting for the lock to release,
            # which stalls the request and freezes the entire upload queue.
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    uploaded_file.stream.seek(0)
                    await uploaded_file.save(target_path)
                    return "File uploaded successfully", 200
                except PermissionError as e:
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(0.5)
                    else:
                        print(
                            f"❌ File locked after {max_attempts} attempts: {filename} — {e}"
                        )
                        return f"File is locked by another process: {str(e)}", 423
                except Exception as e:
                    print(f"❌ Failed to save whole file {filename}: {e}")
                    return f"Failed to save file: {str(e)}", 500

    except ClientDisconnected as e:
        print(
            f"👋 Client disconnected during upload of {filename or 'unknown file'} (ID: {file_id})"
        )
        # Untrack immediately (fast), but run the actual disk cleanup in the background
        # so this handler returns without blocking a Waitress thread on safe_rmtree.
        if file_id:
            chunk_tracker.untrack_upload(session_id, file_id)

            def _bg_disconnect_cleanup(fid):
                try:
                    storage.cleanup_chunks(fid)
                    print(f"🧹 Background disconnect cleanup done: {fid}")
                except Exception as ex:
                    print(f"⚠️ Background disconnect cleanup error for {fid}: {ex}")

            threading.Thread(
                target=_bg_disconnect_cleanup, args=(file_id,), daemon=True
            ).start()
        return "", 499

    except Exception as e:
        print(f"❌ Upload error: {e}")
        # If there was an error and we were tracking this upload, clean it up
        if file_id:
            chunk_tracker.untrack_upload(session_id, file_id)
            storage.cleanup_chunks(file_id)
        return f"Upload error: {str(e)}", 500


@app.route("/cleanup_chunks", methods=["POST"])
@login_required
async def cleanup_chunks():
    """Clean up unfinished chunk files"""
    session_id = session.get("session_id")

    try:
        role = get_role(current_user())
        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

        data = await request.get_json()
        if not data or "file_id" not in data:
            return jsonify({"error": "File ID is required"}), 400

        file_id = data["file_id"]

        # Untrack and cleanup
        chunk_tracker.untrack_upload(session_id, file_id)

        # Clean up chunks directory for this file_id
        chunks_dir = os.path.join(ROOT_DIR, ".chunks", file_id)
        if os.path.exists(chunks_dir):
            try:
                shutil.rmtree(chunks_dir)
                print(f"🧹 Manual cleanup completed for: {file_id}")

                # Try to remove parent chunks directory if empty
                parent_chunks_dir = os.path.join(ROOT_DIR, ".chunks")
                if os.path.exists(parent_chunks_dir) and not os.listdir(
                    parent_chunks_dir
                ):
                    os.rmdir(parent_chunks_dir)
                    print("🧹 Removed empty chunks directory")

                return (
                    jsonify(
                        {"success": True, "message": f"Cleaned up chunks for {file_id}"}
                    ),
                    200,
                )
            except Exception as e:
                print(f"❌ Failed to cleanup chunks for {file_id}: {e}")
                return jsonify({"error": f"Failed to cleanup chunks: {str(e)}"}), 500
        else:
            return jsonify({"success": True, "message": "No chunks to cleanup"}), 200

    except Exception as e:
        print(f"❌ Cleanup error: {e}")
        return jsonify({"error": f"Cleanup error: {str(e)}"}), 500


@app.route("/cancel_upload", methods=["POST"])
@login_required
async def cancel_upload():
    """Cancel an ongoing upload and clean up its chunks"""
    session_id = session.get("session_id")

    try:
        role = get_role(current_user())
        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

        data = await request.get_json()
        if not data or "file_id" not in data:
            return jsonify({"error": "File ID is required"}), 400

        file_id = data["file_id"]
        filename = data.get("filename", "Unknown file")

        print(f"🚫 Cancelling upload: {file_id} ({filename})")

        # Untrack the upload
        chunk_tracker.untrack_upload(session_id, file_id)

        # Clean up chunks directory for this file_id
        chunks_dir = os.path.join(ROOT_DIR, ".chunks", file_id)
        if os.path.exists(chunks_dir):
            try:
                # Run deletion in a daemon thread so this endpoint returns immediately
                # and does NOT block a Waitress thread (safe_rmtree can stall on Windows
                # file locks, which previously exhausted the thread pool when multiple
                # cancellations arrived at the same time).
                def _bg_cleanup(cdir, fid):
                    try:
                        storage.safe_rmtree(cdir)
                        print(f"🧹 Background cancelled-upload cleanup done: {fid}")
                        parent = os.path.join(ROOT_DIR, ".chunks")
                        if os.path.exists(parent):
                            try:
                                if not os.listdir(parent):
                                    os.rmdir(parent)
                            except OSError:
                                pass
                    except Exception as ex:
                        print(f"⚠️ Background cleanup error for {fid}: {ex}")

                threading.Thread(
                    target=_bg_cleanup, args=(chunks_dir, file_id), daemon=True
                ).start()
                print(f"🧹 Queued background cleanup for cancelled upload: {file_id}")

                return (
                    jsonify(
                        {
                            "success": True,
                            "message": f"Upload cancelled and cleanup queued for {filename}",
                            "file_id": file_id,
                        }
                    ),
                    200,
                )
            except Exception as e:
                print(f"❌ Failed to queue cleanup for cancelled upload {file_id}: {e}")
                return (
                    jsonify({"error": f"Failed to cleanup cancelled upload: {str(e)}"}),
                    500,
                )
        else:
            # Upload was cancelled before any chunks were created
            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Upload cancelled for {filename}",
                        "file_id": file_id,
                    }
                ),
                200,
            )

    except Exception as e:
        print(f"❌ Cancel upload error: {e}")
        return jsonify({"error": f"Cancel upload error: {str(e)}"}), 500


@app.route("/admin/cleanup_chunks", methods=["POST"])
@login_required
async def admin_cleanup_chunks():
    """Admin endpoint to trigger comprehensive chunk cleanup"""
    from storage import manual_chunks_cleanup, emergency_cleanup_all

    try:
        role = get_role(current_user())
        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

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
            print(
                f"🔐 Manual cleanup protecting {len(active_assembly_jobs)} files currently being assembled"
            )

        # Cleanup old chunks (aggressive - 30 minutes)
        storage.cleanup_old_chunks(
            max_age_hours=0.5, protected_files=active_assembly_jobs
        )

        # Get stats after cleanup
        stats_after = chunk_tracker.get_stats()

        # Run enhanced manual cleanup
        manual_success = manual_chunks_cleanup()

        print(f"🧹 Comprehensive cleanup completed")
        print(
            f"   Sessions: {stats_before['active_sessions']} -> {stats_after['active_sessions']}"
        )
        print(
            f"   Uploads: {stats_before['active_uploads']} -> {stats_after['active_uploads']}"
        )

        return (
            jsonify(
                {
                    "success": True,
                    "message": (
                        "Comprehensive cleanup completed successfully"
                        if manual_success
                        else "Cleanup completed with some warnings"
                    ),
                    "stats_before": stats_before,
                    "stats_after": stats_after,
                    "manual_cleanup_success": manual_success,
                }
            ),
            200,
        )

    except Exception as e:
        print(f"❌ Error in comprehensive cleanup: {e}")
        # Try emergency cleanup as fallback
        try:
            emergency_cleanup_all()
            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Standard cleanup failed, emergency cleanup performed: {str(e)}",
                        "emergency_cleanup": True,
                    }
                ),
                200,
            )
        except Exception as emergency_error:
            return (
                jsonify(
                    {
                        "error": f"All cleanup methods failed: {str(e)} | Emergency: {str(emergency_error)}"
                    }
                ),
                500,
            )


@app.route("/admin/chunk_stats", methods=["GET"])
@login_required
async def chunk_stats():
    """Get chunk tracking statistics"""
    try:
        role = get_role(current_user())
        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

        stats = chunk_tracker.get_stats()

        # Add filesystem stats
        chunks_dir = os.path.join(ROOT_DIR, ".chunks")
        filesystem_chunks = []
        if os.path.exists(chunks_dir):
            try:
                filesystem_chunks = [
                    d
                    for d in os.listdir(chunks_dir)
                    if os.path.isdir(os.path.join(chunks_dir, d))
                ]
            except OSError:
                pass

        stats["filesystem_chunks"] = len(filesystem_chunks)
        stats["chunk_directories"] = filesystem_chunks

        return jsonify(stats), 200

    except Exception as e:
        print(f"❌ Error getting chunk stats: {e}")
        return jsonify({"error": f"Stats error: {str(e)}"}), 500


@app.route("/admin/upload_status", methods=["GET"])
@login_required
async def upload_status():
    """Get current upload status for UI updates"""
    try:
        role = get_role(current_user())

        # Allow readonly users to check auth status, but return limited info
        if role == "readonly":
            return jsonify(
                {
                    "authenticated": True,
                    "role": "readonly",
                    "has_active_uploads": False,
                    "session_has_active": False,
                    "total_active_sessions": 0,
                    "can_upload": False,
                }
            )

        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

        session_id = session.get("session_id")
        stats = chunk_tracker.get_stats()

        # Check if current session has active uploads
        session_has_active = False
        if session_id and session_id in chunk_tracker.active_uploads:
            session_has_active = len(chunk_tracker.active_uploads[session_id]) > 0

        return (
            jsonify(
                {
                    "has_active_uploads": stats["active_uploads"] > 0,
                    "session_has_active": session_has_active,
                    "total_active_sessions": stats["active_sessions"],
                    "total_active_uploads": stats["active_uploads"],
                }
            ),
            200,
        )

    except Exception as e:
        print(f"❌ Error getting upload status: {e}")
        return jsonify({"error": f"Status error: {str(e)}"}), 500


@app.route("/api/assembly_status", methods=["GET"])
@login_required
async def get_assembly_status():
    """Get all assembly jobs for current session"""
    session_id = session.get("session_id")
    if not session_id:
        return jsonify({"jobs": []}), 200

    jobs = assembly_queue.get_jobs_for_session(session_id)
    job_data = []

    for job in jobs:
        job_data.append(
            {
                "file_id": job.file_id,
                "filename": job.filename,
                "status": job.status,
                "created_at": job.created_at,
                "error_message": job.error_message,
            }
        )

    return jsonify({"jobs": job_data}), 200


@app.route("/api/protect_assembly/<file_id>", methods=["POST"])
@login_required
async def protect_assembly_job(file_id):
    """Mark an assembly job as protected from cleanup"""
    session_id = session.get("session_id")
    if not session_id:
        return jsonify({"error": "No session ID"}), 400

    # Check if this job belongs to the current session
    job = assembly_queue.get_job_status(file_id)
    if job and job.session_id == session_id:
        # Re-track this upload to prevent cleanup
        chunk_tracker.track_upload(session_id, file_id)
        print(f"🔐 Protected assembly job {file_id} from cleanup")
        return jsonify({"status": "protected"}), 200

    return jsonify({"error": "Job not found or access denied"}), 404


@app.route("/api/assembly_status/<file_id>", methods=["GET"])
@login_required
async def get_single_assembly_status(file_id):
    """Get status of a specific assembly job"""
    job = assembly_queue.get_job_status(file_id)

    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Check if user owns this job
    session_id = session.get("session_id")
    if job.session_id != session_id:
        return jsonify({"error": "Access denied"}), 403

    return (
        jsonify(
            {
                "file_id": job.file_id,
                "filename": job.filename,
                "status": job.status,
                "created_at": job.created_at,
                "error_message": job.error_message,
            }
        ),
        200,
    )


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
                    print(
                        f"🔐 Protecting {len(active_assembly_jobs)} files from periodic cleanup"
                    )

                storage.cleanup_old_chunks(
                    max_age_hours=1, protected_files=active_assembly_jobs
                )  # Clean 1+ hour old chunks

                # Every 4th run (1 hour), do the full 24-hour cleanup
                cleanup_counter = getattr(cleanup_worker, "counter", 0) + 1
                cleanup_worker.counter = cleanup_counter

                if cleanup_counter % 4 == 0:  # Every hour
                    print("🧹 Running full chunk cleanup...")
                    storage.cleanup_old_chunks(
                        max_age_hours=24, protected_files=active_assembly_jobs
                    )

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


def start_expired_share_cleanup_scheduler():
    """Start a background thread that periodically revokes expired shares.

    _get_live_share() and _prune_expired_shares() already revoke an expired
    share lazily the moment any visitor route or admin fetch touches it,
    but a share nobody ever revisits after it expires would otherwise sit
    in the DB — and in the Manage Shared → Active Shares list / revoke-all
    count — until someone happens to look. This sweep is what makes expiry
    removal actually "live" for an admin who just has the tab open and
    idle: it runs frequently and (via _prune_expired_shares) broadcasts an
    active_shares_changed SSE event to every connected admin the moment it
    revokes something, rather than depending on a client-side setTimeout
    that browsers can throttle/suspend in a backgrounded tab, or on the
    admin manually triggering a refetch (switching tabs, etc).
    """

    def expired_share_cleanup_worker():
        while True:
            try:
                _prune_expired_shares(db.list_active_shares())
            except Exception as e:
                print(f"❌ Error in expired share cleanup worker: {e}")
            time.sleep(15)  # frequent enough to feel live, cheap enough to not matter

    cleanup_thread = threading.Thread(target=expired_share_cleanup_worker, daemon=True)
    cleanup_thread.start()
    print("🔗 Started expired share cleanup scheduler (every 15 seconds)")


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
                    assembly_queue.active_jobs[job.file_id].status = "processing"

            try:
                # Perform the actual assembly
                success = storage.assemble_chunks(
                    job.file_id, job.filename, job.dest_path
                )

                if success:
                    assembly_queue.complete_job(job.file_id, success=True)
                    print(f"✅ Successfully assembled: {job.filename}")
                else:
                    assembly_queue.complete_job(
                        job.file_id,
                        success=False,
                        error_message="Assembly failed - see server logs",
                    )
                    print(f"❌ Assembly failed: {job.filename}")

            except Exception as e:
                error_msg = str(e)
                assembly_queue.complete_job(
                    job.file_id, success=False, error_message=error_msg
                )
                print(f"❌ Assembly error for {job.filename}: {error_msg}")

            # Mark queue task as done
            assembly_queue.job_queue.task_done()

            # When the assembly queue drains to zero, trigger an immediate reconcile
            # so the file count corrects itself right away. Use _trigger_reconcile (not
            # reconcile_async) so the SSE force-push fires even if watchdog already
            # updated the counters and _reconcile sees no drift.
            if assembly_queue.job_queue.empty() and not assembly_queue.active_jobs:
                _trigger_reconcile()

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
        chunks_dir = os.path.join(ROOT_DIR, ".chunks")
        if not os.path.exists(chunks_dir):
            return

        recovered_count = 0

        for file_id in os.listdir(chunks_dir):
            chunk_dir = os.path.join(chunks_dir, file_id)
            if not os.path.isdir(chunk_dir):
                continue

            try:
                # Skip if assembly is currently in progress
                protection_file = os.path.join(chunk_dir, ".assembling")
                if os.path.exists(protection_file):
                    print(f"🛡️ Skipping {file_id} - assembly protection active")
                    continue

                # Look for metadata file first
                metadata_file = os.path.join(chunk_dir, ".metadata")
                filename = f"recovered_file_{file_id}"
                dest_path = ""
                expected_chunks = None

                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, "r") as f:
                            metadata = json.load(f)
                            filename = metadata.get("filename", filename)
                            dest_path = metadata.get("dest_path", dest_path)
                            expected_chunks = metadata.get("total_chunks")

                            print(
                                f"📋 Found metadata for {file_id}: {filename}, expected {expected_chunks} chunks"
                            )
                    except Exception as e:
                        print(f"⚠️ Error reading metadata for {file_id}: {e}")
                        continue

                # Use enhanced chunk verification
                try:
                    chunk_info = storage.verify_chunks_complete(
                        file_id, expected_chunks
                    )
                    total_chunks = chunk_info["total_chunks"]

                    print(
                        f"🔄 Found complete upload ready for assembly: {filename} ({total_chunks} chunks)"
                    )
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
            print(
                f"🔄 Recovered {recovered_count} incomplete upload(s) for background assembly"
            )
        else:
            print("🔍 No incomplete uploads found ready for recovery")

    except Exception as e:
        print(f"⚠️ Error detecting ready assemblies: {e}")
