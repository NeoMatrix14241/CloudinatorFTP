"""
routes/files.py - browse, download, file operations and bulk jobs: /, /<path>, /download, /view,
/bulk-download, /cancel_bulk_zip, /api/files, /api/dir_info, /bulk_move|copy|job|delete, rename, mkdir,
delete, /api/check_conflicts and /api/exists (Phase 9 of the split, CLAUDE.md 4.77).

Moved verbatim from app.py. The shared bulk_zip_progress / bulk_zip_cancelled dicts and
_trigger_reconcile come from core (one copy, one reconcile gate for the whole app). The bulk-job
registry (_bulk_jobs, _bulk_jobs_lock) lives here. Gets shared objects via `from core import ...`;
imports no other route module.
"""

from core import (
    _stream_from_thread,
    _trigger_reconcile,
    app,
    bulk_zip_cancelled,
    bulk_zip_progress,
    login_required,
)

from quart import (
    Response,
    abort,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
import os
import shutil
import asyncio
import threading
import time
import logging
import zipstream
import secrets as _secrets
from config import ROOT_DIR, CHUNK_SIZE
from auth import current_user, get_role
import storage


@app.route("/cancel_bulk_zip", methods=["POST"])
async def cancel_bulk_zip():
    session_id = session.get("session_id") or request.cookies.get("session")
    if not session_id:
        return jsonify({"error": "No session ID"}), 400
    bulk_zip_cancelled[session_id] = True
    print(f"❌ Bulk ZIP cancelled for session {session_id}")
    return jsonify({"status": "cancelled"})


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
@login_required
async def index(path):
    # Anything starting with "static" here means Quart's own built-in
    # /static/<filename> route (registered separately, ahead of this
    # catch-all) failed to match — almost always a malformed request like
    # a double slash ("/static//whatever") that a real static asset would
    # never produce. Previously this fell through to the login-gated
    # catch-all below, which redirected anonymous requests to /login and
    # returned 200 — indistinguishable from a real page to a scanner, and
    # exactly what tripped ZAP's Path Traversal heuristic. A plain 404
    # here is both more correct and stops that false positive, without
    # touching the real is_safe_path()/is_valid_path() traversal guards
    # used everywhere else in this file.
    #
    # Broadened beyond the exact "static"/"static/..." match: scanners
    # (e.g. sqlmap-style boolean-blind probes) also throw garbage directly
    # onto the "static" prefix with no separating slash at all — "static%",
    # "staticXYZABCDEFGHIJ", etc. None of those can ever be a legitimate
    # top-level directory entry the app is supposed to serve (real folder
    # browsing always goes through a "/"-separated path), so reject any
    # path that starts with "static" and isn't cleanly followed by "/".
    if (
        path == "static"
        or path.startswith("static/")
        or (path.startswith("static") and not path[len("static") :].startswith("/"))
    ):
        abort(404)

    # Comprehensive path validation: safety and existence
    if path and not storage.is_valid_path(path):
        if not storage.is_safe_path(path):
            await flash(
                "Invalid path: contains unsafe characters or directory traversal"
            )
        else:
            await flash(f'Path "{path}" does not exist or is not a directory')
        return redirect(url_for("index"))

    try:
        # Get current directory info
        current_path = os.path.join(ROOT_DIR, path) if path else ROOT_DIR
        items = await asyncio.to_thread(storage.list_dir, path)

        response = await make_response(
            await render_template(
                "index.html",
                items=items,
                path=path,
                role=session.get("role", "readonly"),
                CHUNK_SIZE=CHUNK_SIZE,
            )
        )

        # Add strict cache control headers to prevent caching of authenticated content
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

        return response

    except Exception as e:
        logging.error(f"Error loading directory {path}: {e}", exc_info=True)
        await flash("Error loading directory")
        return redirect(url_for("index"))


@app.route("/download/<path:path>")
@login_required
async def download(path):
    # Security check: ensure path is safe
    if not storage.is_safe_path(path):
        await flash("Invalid file path")
        return redirect(url_for("index"))

    full_path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        await flash("File not found")
        return redirect(url_for("index"))

    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)
    return await send_from_directory(directory, filename, as_attachment=True)


@app.route("/view/<path:path>")
@login_required
async def view_file(path):
    """Serve a file inline (for in-browser preview — images, video, audio, PDF, text)."""
    if not storage.is_safe_path(path):
        return "Invalid file path", 400
    full_path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return "File not found", 404
    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)
    return await send_from_directory(directory, filename, as_attachment=False)


@app.route("/bulk-download", methods=["POST"])
@login_required
async def bulk_download():
    """Download multiple files and folders as a streaming ZIP file using zipstream-new"""
    try:
        print(f"📥 Bulk download request received from user: {current_user()}")

        # Handle both JSON and form data
        if request.is_json:
            data = await request.get_json()
            print(f"📋 JSON Request data: {data}")

            if not data or "paths" not in data:
                print("❌ Error: No paths provided in JSON request")
                return jsonify({"error": "No paths provided"}), 400

            paths = data["paths"]
        else:
            # Handle form data
            print("📋 Form data request received")
            paths_json = (await request.form).get("paths")
            if not paths_json:
                print("❌ Error: No paths provided in form request")
                return jsonify({"error": "No paths provided"}), 400

            try:
                import json

                paths = json.loads(paths_json)
                print(f"📋 Form Request paths: {paths}")
            except json.JSONDecodeError:
                print("❌ Error: Invalid JSON in form paths")
                return jsonify({"error": "Invalid paths format"}), 400
        print(f"📁 Requested paths ({len(paths)} items): {paths}")

        if not paths:
            print("❌ Error: Empty paths list")
            return jsonify({"error": "Empty paths list"}), 400

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

        print(
            f"📊 Validation results: {len(valid_paths)} valid, {len(invalid_paths)} invalid"
        )

        if invalid_paths:
            return jsonify({"error": f"Invalid paths: {invalid_paths}"}), 400

        # Generate a filename for the ZIP based on selection
        if len(paths) == 1:
            # Single item - use its name
            base_name = os.path.basename(paths[0]) or "download"
        else:
            # Multiple items - use generic name with count
            base_name = f"bulk_download_{len(paths)}_items"

        zip_filename = f"{base_name}.zip"
        print(f"📦 Creating streaming ZIP file: {zip_filename}")

        # Capture session data before creating the generator (outside request context)
        session_id = session.get("session_id")
        if session_id:
            bulk_zip_progress[session_id] = {
                "current": 0,
                "total": len(paths),
                "done": False,
            }

        def generate_zip_stream():
            """Generator function to create ZIP file using zipstream-new for true streaming"""

            print(f"🗂️ Starting ZIP stream generation for {len(paths)} paths...")

            # Create zipstream object with optimized compression for large files
            zf = zipstream.ZipFile(
                mode="w", compression=zipstream.ZIP_DEFLATED, allowZip64=True
            )

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
                    bulk_zip_progress[session_id]["current"] = i

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
                        print(
                            f"📄 Adding file to stream: {arc_name} ({file_size:,} bytes)"
                        )
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
                            if rel_path == ".":
                                arc_root = dir_name
                            else:
                                arc_root = os.path.join(dir_name, rel_path).replace(
                                    "\\", "/"
                                )

                            # Add all files in current directory
                            for file in files:
                                try:
                                    file_path = os.path.join(root, file)
                                    file_size = os.path.getsize(file_path)
                                    total_size += file_size
                                    arc_name = os.path.join(arc_root, file).replace(
                                        "\\", "/"
                                    )
                                    zf.write(file_path, arcname=arc_name)
                                    dir_files_added += 1
                                except (PermissionError, OSError) as e:
                                    print(f"⚠️  Skipped file {file_path}: {str(e)}")
                                    logging.warning(
                                        f"Skipped file {file_path}: {str(e)}"
                                    )
                                    continue

                            # Create empty directory entry if no files and no subdirs
                            if not files and not dirs:
                                zf.writestr(arc_root + "/", "")

                        print(f"📁 Directory added with {dir_files_added} files")
                        files_added += dir_files_added

                except (PermissionError, OSError) as e:
                    print(f"⚠️  Skipped item {full_path}: {str(e)}")
                    logging.warning(f"Skipped item {full_path}: {str(e)}")
                    continue

            print(
                f"✅ ZIP stream setup complete: {files_added} files queued for streaming"
            )
            if session_id:
                bulk_zip_progress[session_id]["done"] = True

            # Stream the ZIP file
            for chunk in zf:
                yield chunk

            print(f"� ZIP stream download completed")

        # Create response with streaming optimized for large files
        response = Response(
            _stream_from_thread(generate_zip_stream()),
            mimetype="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{zip_filename}"',
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Content-Encoding": "identity",
            },
        )

        print(f"🎉 Bulk download response ready for {len(paths)} items")
        logging.info(f"Bulk download initiated by {current_user()}: {len(paths)} items")
        logging.debug(f"Paths requested: {paths}")
        return response

    except Exception as e:
        print(f"❌ Bulk download error: {str(e)}")
        logging.error(f"Bulk download error: {str(e)}")
        return jsonify({"error": "Failed to create download"}), 500


@app.route("/api/dir_info/", defaults={"path": ""})
@app.route("/api/dir_info/<path:path>")
@login_required
async def dir_info(path):
    """
    Returns folder size and item count.
    Hits the in-memory index instantly if indexed.
    Falls back to live walk for brand-new folders not yet in the index,
    then stores the result back so subsequent requests are instant.
    """
    if path and not storage.is_safe_path(path):
        return jsonify({"error": "Invalid path"}), 400
    try:
        info = storage.get_dir_info(path)

        # If this was a live walk fallback, store it back into the monitor index
        # so the next request for this path is instant
        try:
            from file_monitor import get_file_monitor

            monitor = get_file_monitor()
            rel_path = path.replace("\\", "/").strip("/")
            if monitor.get_dir_info(rel_path) is None:
                with monitor.lock:
                    monitor._dir_info[rel_path] = {
                        "file_count": info["file_count"],
                        "dir_count": info["dir_count"],
                        "total_size": info["total_size"],
                    }
                print(f"📥 Stored live walk result for '{rel_path}' into index")
        except Exception:
            pass

        return jsonify(info), 200
    except Exception as e:
        print(f"❌ Error getting dir info for {path}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/files/", defaults={"path": ""})
@app.route("/api/files/<path:path>")
@login_required
async def api_files(path):
    """API endpoint to get file listings as JSON"""
    try:
        # Comprehensive path validation: safety and existence
        if path and not storage.is_valid_path(path):
            return jsonify({"error": "Invalid path"}), 400

        role = get_role(current_user())
        items = await asyncio.to_thread(storage.list_dir, path)

        response_data = {
            "success": True,
            "files": items,
            "current_path": path,
            "role": role,
        }

        return jsonify(response_data), 200

    except Exception as e:
        print(f"❌ Error in api_files: {e}")
        return jsonify({"error": "Failed to load files"}), 500


# ---------------------------------------------------------------------------
# 4.64: bulk move / copy run as background jobs.
# A big move or copy can take longer than a reverse proxy / CDN waits for the
# response (Cloudflare gives up after ~100 s with an HTML 524 page), so the POST
# validates the request, starts a worker thread and returns 202 with a job id;
# the page polls GET /bulk_job/<id>. The copy used to run shutil.copytree /
# copy2 / rmtree directly on the event loop, freezing the whole server too.
# ---------------------------------------------------------------------------
_bulk_jobs = {}
_bulk_jobs_lock = threading.Lock()
_BULK_JOB_KEEP_SECS = 900  # finished jobs stay pollable for 15 minutes


def _bulk_job_start(kind, user, total, worker, *args):
    """Register a job, start its worker thread, return the job id."""
    now = time.time()
    job_id = _secrets.token_hex(8)
    job = {
        "id": job_id,
        "kind": kind,
        "user": user,
        "state": "running",
        "total": total,
        "done": 0,
        "current": "",
        "status": None,
        "result": None,
        "started_at": now,
        "finished_at": None,
    }
    with _bulk_jobs_lock:
        for jid in [
            j
            for j, v in _bulk_jobs.items()
            if v["finished_at"] and now - v["finished_at"] > _BULK_JOB_KEEP_SECS
        ]:
            _bulk_jobs.pop(jid, None)
        _bulk_jobs[job_id] = job

    def _target():
        try:
            status, payload = worker(job, *args)
        except Exception as e:
            print(f"❌ Bulk {kind} job error: {e}")
            status, payload = 500, {"error": f"Bulk {kind} error: {str(e)}"}
        with _bulk_jobs_lock:
            job.update(
                state="done", status=status, result=payload, finished_at=time.time()
            )

    threading.Thread(target=_target, name=f"bulk-{kind}", daemon=True).start()
    return job_id


def _bulk_find_free_name(dest_dir, filename):
    base, ext = os.path.splitext(filename)
    for i in range(1, 1000):
        candidate = f"{base} ({i}){ext}"
        if not os.path.exists(os.path.join(dest_dir, candidate)):
            return candidate
    return f"{base} ({int(time.time())}){ext}"


def _bulk_move_worker(job, paths, destination, conflict_resolutions):
    """Runs in a worker thread. Returns (http_status, payload)."""
    moved_count = 0
    errors = []
    for source_path in paths:
        job["current"] = os.path.basename(source_path)
        try:
            # Security check
            if not storage.is_safe_path(source_path):
                errors.append(f"Invalid source path: {source_path}")
                continue

            source_full = os.path.join(ROOT_DIR, source_path)
            if not os.path.exists(source_full):
                errors.append(f"Source not found: {source_path}")
                continue

            # Determine destination
            filename = os.path.basename(source_path)
            dest_dir = os.path.join(ROOT_DIR, destination) if destination else ROOT_DIR
            dest_full = os.path.join(dest_dir, filename)

            # Create destination directory if it doesn't exist
            os.makedirs(dest_dir, exist_ok=True)

            # Handle conflict
            if os.path.exists(dest_full):
                resolution = conflict_resolutions.get(filename, "error")
                if resolution == "skip":
                    continue
                elif resolution == "overwrite":
                    if os.path.isdir(dest_full):
                        shutil.rmtree(dest_full)
                    else:
                        os.remove(dest_full)
                elif resolution == "rename":
                    dest_full = os.path.join(
                        dest_dir, _bulk_find_free_name(dest_dir, filename)
                    )
                else:
                    errors.append(
                        f"Destination already exists: {os.path.join(destination, filename) if destination else filename}"
                    )
                    continue

            # Perform the move (cross-volume / big folder = a copy; that is why
            # this runs in a worker thread and not in the request).
            shutil.move(source_full, dest_full)
            moved_count += 1

        except Exception as e:
            errors.append(f"Failed to move {source_path}: {str(e)}")
        finally:
            job["done"] += 1

    if moved_count:
        # The per-folder correction fixes counts, but a full walk remains the
        # ground truth after a web-UI mutation (4.60).
        _trigger_reconcile()

    if errors:
        return 207, {
            "moved_count": moved_count,
            "errors": errors,
            "error": f"Some items could not be moved. Moved {moved_count} items with {len(errors)} errors.",
        }  # Multi-status
    return 200, {"moved_count": moved_count, "success": True}


def _bulk_copy_worker(job, paths, destination, conflict_resolutions):
    """Runs in a worker thread. Returns (http_status, payload)."""
    copied_count = 0
    errors = []
    for source_path in paths:
        job["current"] = os.path.basename(source_path)
        try:
            # Security check
            if not storage.is_safe_path(source_path):
                errors.append(f"Invalid source path: {source_path}")
                continue

            source_full = os.path.join(ROOT_DIR, source_path)
            if not os.path.exists(source_full):
                errors.append(f"Source not found: {source_path}")
                continue

            # Determine destination
            filename = os.path.basename(source_path)
            dest_dir = os.path.join(ROOT_DIR, destination) if destination else ROOT_DIR
            dest_full = os.path.join(dest_dir, filename)

            # Create destination directory if it doesn't exist
            os.makedirs(dest_dir, exist_ok=True)

            # Handle conflict
            if os.path.exists(dest_full):
                resolution = conflict_resolutions.get(
                    filename, "rename"
                )  # default: auto-rename
                if resolution == "skip":
                    continue
                elif resolution == "overwrite":
                    if os.path.isdir(dest_full):
                        shutil.rmtree(dest_full)
                    else:
                        os.remove(dest_full)
                else:  # 'rename' or default
                    dest_full = os.path.join(
                        dest_dir, _bulk_find_free_name(dest_dir, filename)
                    )

            # Perform the copy
            if os.path.isdir(source_full):
                shutil.copytree(source_full, dest_full)
            else:
                shutil.copy2(source_full, dest_full)

            copied_count += 1

        except Exception as e:
            errors.append(f"Failed to copy {source_path}: {str(e)}")
        finally:
            job["done"] += 1

    if copied_count > 0:
        _trigger_reconcile(settle=True)  # copytree fires a backlog storm

    if errors:
        return 207, {
            "copied_count": copied_count,
            "errors": errors,
            "error": f"Some items could not be copied. Copied {copied_count} items with {len(errors)} errors.",
        }  # Multi-status
    return 200, {"copied_count": copied_count, "success": True}


async def _bulk_start(kind, worker):
    """Shared request handling for /bulk_move and /bulk_copy: validate, start the
    job, answer 202 at once."""
    try:
        role = get_role(current_user())
        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

        data = await request.get_json()
        if not data or "paths" not in data:
            return jsonify({"error": "Paths are required"}), 400

        paths = data["paths"]
        destination = data.get("destination", "").strip()

        if not paths:
            return jsonify({"error": "No paths provided"}), 400

        # Validate destination path
        if destination and not storage.is_safe_path(destination):
            return jsonify({"error": "Invalid destination path"}), 400

        # conflict_resolutions maps filename -> 'overwrite' | 'rename' | 'skip'
        conflict_resolutions = data.get("conflict_resolutions", {})

        job_id = _bulk_job_start(
            kind,
            current_user(),
            len(paths),
            worker,
            paths,
            destination,
            conflict_resolutions,
        )
        return jsonify({"job_id": job_id, "started": True, "total": len(paths)}), 202

    except Exception as e:
        return jsonify({"error": f"Bulk {kind} error: {str(e)}"}), 500


@app.route("/bulk_move", methods=["POST"])
@login_required
async def bulk_move():
    """Move multiple files/folders to a new location (background job, 202)."""
    return await _bulk_start("move", _bulk_move_worker)


@app.route("/bulk_copy", methods=["POST"])
@login_required
async def bulk_copy():
    """Copy multiple files/folders to a new location (background job, 202)."""
    return await _bulk_start("copy", _bulk_copy_worker)


@app.route("/bulk_job/<job_id>", methods=["GET"])
@login_required
async def bulk_job_status(job_id):
    """State of a bulk move/copy job: running -> done (with the final HTTP status
    and the payload the old synchronous route used to return)."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403
    with _bulk_jobs_lock:
        job = _bulk_jobs.get(job_id)
        if job is None or job["user"] != current_user():
            return jsonify({"error": "Unknown job"}), 404
        snap = {
            "state": job["state"],
            "kind": job["kind"],
            "total": job["total"],
            "done": job["done"],
            "current": job["current"],
            "status": job["status"],
            "result": job["result"],
        }
    return jsonify(snap), 200


@app.route("/bulk_delete", methods=["POST"])
@login_required
async def bulk_delete():
    """Delete multiple files/folders"""
    try:
        role = get_role(current_user())
        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

        data = await request.get_json()
        if not data or "paths" not in data:
            return jsonify({"error": "Paths are required"}), 400

        paths = data["paths"]

        if not paths:
            return jsonify({"error": "No paths provided"}), 400

        deleted_count = 0
        errors = []

        for target_path in paths:
            try:
                # Security check
                if not storage.is_safe_path(target_path):
                    errors.append(f"Invalid path: {target_path}")
                    continue

                full_path = os.path.join(ROOT_DIR, target_path)
                if not os.path.exists(full_path):
                    errors.append(f"Path not found: {target_path}")
                    continue

                # Perform the deletion
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)

                deleted_count += 1

            except Exception as e:
                errors.append(f"Failed to delete {target_path}: {str(e)}")

        # Reconcile immediately so file/dir counts are corrected without waiting 15 min
        if deleted_count > 0:
            _trigger_reconcile()

        if errors:
            return (
                jsonify(
                    {
                        "deleted_count": deleted_count,
                        "errors": errors,
                        "error": f"Some items could not be deleted. Deleted {deleted_count} items with {len(errors)} errors.",
                    }
                ),
                207,
            )  # Multi-status
        else:
            return jsonify({"deleted_count": deleted_count, "success": True}), 200

    except Exception as e:
        return jsonify({"error": f"Bulk delete error: {str(e)}"}), 500


@app.route("/rename", methods=["POST"])
@login_required
async def rename_item():
    """Rename a single file or folder"""
    try:
        role = get_role(current_user())
        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

        data = await request.get_json()
        if not data or "old_path" not in data or "new_name" not in data:
            return jsonify({"error": "Old path and new name are required"}), 400

        old_path = data["old_path"]
        new_name = data["new_name"].strip()

        # Validate inputs
        if not new_name:
            return jsonify({"error": "New name cannot be empty"}), 400

        # Security checks
        if not storage.is_safe_path(old_path):
            return jsonify({"error": "Invalid old path"}), 400

        # Validate new name doesn't contain path separators or invalid characters
        if (
            "/" in new_name
            or "\\" in new_name
            or any(char in new_name for char in '<>:"|?*')
        ):
            return jsonify({"error": "Invalid characters in new name"}), 400

        # Check if old path exists
        old_full_path = os.path.join(ROOT_DIR, old_path)
        if not os.path.exists(old_full_path):
            return jsonify({"error": "Item not found"}), 404

        # Get the directory of the old path
        parent_dir = os.path.dirname(old_path)

        # Create new path
        new_path = os.path.join(parent_dir, new_name) if parent_dir else new_name
        new_full_path = os.path.join(ROOT_DIR, new_path)

        # Check if destination already exists
        if os.path.exists(new_full_path):
            return jsonify({"error": "An item with that name already exists"}), 409

        # Perform the rename
        try:
            os.rename(old_full_path, new_full_path)
            _trigger_reconcile()
            return (
                jsonify(
                    {
                        "success": True,
                        "message": f'Successfully renamed to "{new_name}"',
                        "old_path": old_path,
                        "new_path": new_path,
                        "new_name": new_name,
                    }
                ),
                200,
            )
        except OSError as e:
            return jsonify({"error": f"Failed to rename: {str(e)}"}), 500

    except Exception as e:
        return jsonify({"error": f"Rename error: {str(e)}"}), 500


@app.route("/mkdir", methods=["POST"])
@login_required
async def mkdir():
    try:
        role = get_role(current_user())
        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

        foldername = (await request.form).get("foldername", "").strip()
        path = (await request.form).get("path", "")

        if not foldername:
            return jsonify({"error": "Folder name required"}), 400

        # Only replace slashes, preserve all other characters (including +, spaces, etc.)
        foldername = foldername.replace("/", "_").replace("\\", "_")
        if not foldername:
            return jsonify({"error": "Invalid folder name"}), 400

        # Security check: ensure path is safe
        if path and not storage.is_safe_path(path):
            return jsonify({"error": "Invalid path"}), 400

        created = storage.create_folder(path, foldername)
        if not created:
            return (
                jsonify({"error": "Folder already exists or could not be created"}),
                409,
            )
        else:
            _trigger_reconcile()
            return (
                jsonify(
                    {
                        "success": True,
                        "message": f'Folder "{foldername}" created successfully',
                    }
                ),
                200,
            )

    except Exception as e:
        return jsonify({"error": f"Error creating folder: {str(e)}"}), 500


@app.route("/delete", methods=["POST"])
@login_required
async def delete():
    try:
        role = get_role(current_user())
        if role != "readwrite":
            await flash("Permission denied")
            return redirect(url_for("index"))

        target_path = (await request.form).get("target_path")
        if not target_path:
            await flash("Target path is required")
            return redirect(url_for("index"))

        # Security check: ensure path is safe
        if not storage.is_safe_path(target_path):
            await flash("Invalid target path")
            return redirect(url_for("index"))

        if storage.delete_path(target_path):
            await flash("Item deleted successfully")
            _trigger_reconcile()
        else:
            await flash("Error deleting item")

        # Redirect to parent directory
        parent_path = "/".join(target_path.split("/")[:-1])
        return redirect(url_for("index", path=parent_path))

    except Exception as e:
        await flash(f"Error deleting item: {str(e)}")
        return redirect(url_for("index"))


@app.route("/api/check_conflicts", methods=["POST"])
@login_required
async def api_check_conflicts():
    """Check which of the given paths would conflict at the destination."""
    try:
        data = await request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400
        paths = data.get("paths", [])
        destination = data.get("destination", "").strip()

        if destination and not storage.is_safe_path(destination):
            return jsonify({"error": "Invalid destination path"}), 400

        conflicts = []
        for source_path in paths:
            if not storage.is_safe_path(source_path):
                continue
            filename = os.path.basename(source_path)
            dest_full = (
                os.path.join(ROOT_DIR, destination, filename)
                if destination
                else os.path.join(ROOT_DIR, filename)
            )
            if os.path.exists(dest_full):
                conflicts.append(
                    {
                        "source": source_path,
                        "name": filename,
                        "is_dir": os.path.isdir(dest_full),
                    }
                )
        return jsonify({"conflicts": conflicts})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/exists", methods=["GET"])
@login_required
async def api_exists():
    """Check whether a path (file or folder) exists under ROOT_DIR."""
    path = request.args.get("path", "")
    if path and not storage.is_safe_path(path):
        return jsonify({"error": "Invalid path"}), 400
    full_path = os.path.join(ROOT_DIR, path) if path else ROOT_DIR
    exists = os.path.exists(full_path)
    is_dir = os.path.isdir(full_path) if exists else False
    return jsonify({"exists": exists, "is_dir": is_dir, "path": path})
