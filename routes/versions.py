"""
routes/versions.py - Version History routes: /api/versions/* and /download/recovered/*
(Phase 4 of the split, CLAUDE.md 4.72).

Moved verbatim from app.py. Thin wrappers over version_history.py; `version_history.init()` stays
in core.py. Gets shared objects via `from core import ...`; imports no other route module.
"""

from core import app, app_logger, login_required

from quart import Response, jsonify, request, send_from_directory
import os
import asyncio
import logging
import mimetypes
from config import ROOT_DIR
from auth import current_user, get_role
import storage
import version_history


@app.route("/api/versions/list", methods=["GET"])
@login_required
async def api_versions_list():
    """List a file's version history — used to populate the Version
    History modal. Available to any logged-in user (mirrors /download
    and /api/share/status, which have no role restriction either)."""
    path = request.args.get("path", "")
    if not path or not storage.is_safe_path(path):
        return jsonify({"error": "Invalid file path"}), 400

    full_path = os.path.join(ROOT_DIR, path)
    try:
        versions = await asyncio.to_thread(version_history.get_history, full_path)
    except Exception as e:
        app_logger.exception("Version history list failed for %s", path)
        return jsonify({"error": "Could not load version history: " + str(e)}), 503
    if versions is None:
        return jsonify({"tracked": False, "versions": []})
    return jsonify(
        {
            "tracked": True,
            "versions": versions,
            "retention": version_history.retention_info(versions),
            "restoring": version_history.inflight_versions(full_path),
        }
    )


@app.route("/api/versions/restore", methods=["POST"])
@login_required
async def api_versions_restore():
    """Reconstruct a past version into .recovered/ — never overwrites the
    live file. See version_history.py's module docstring for the naming
    scheme and why this deliberately isn't an in-place restore."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    data = await request.get_json(silent=True) or {}
    path = data.get("path", "")
    version_id = data.get("version_id")
    if not path or not storage.is_safe_path(path) or not isinstance(version_id, int):
        return jsonify({"error": "Invalid request"}), 400

    full_path = os.path.join(ROOT_DIR, path)
    ok, message, recovered_rel = await asyncio.to_thread(
        version_history.restore, full_path, version_id
    )
    if not ok:
        if message == version_history.IN_PROGRESS_MSG:
            # Double-click / second tab: the first request is still
            # rebuilding this version. 409 + in_progress lets the UI keep
            # the button in its loading state instead of showing an error.
            return jsonify({"error": message, "in_progress": True}), 409
        return jsonify({"error": message}), 400

    logging.info(
        f"Version restored by {current_user()}: {path} v{version_id} -> {recovered_rel}"
    )
    return jsonify(
        {
            "success": True,
            "message": message,
            "recovered_path": recovered_rel,
            "download_url": (
                f"/download/recovered/{recovered_rel[len(version_history.RECOVERED_DIRNAME) + 1:]}"
                if recovered_rel
                else None
            ),
        }
    )


@app.route("/api/versions/download", methods=["GET"])
@login_required
async def api_versions_download():
    """Stream a past version's content directly to the browser WITHOUT
    restoring anything — reconstructed into a throwaway temp dir, read
    into memory, and cleaned up, all inside version_history.prepare_download()
    (see its docstring for why this buffers rather than streams: Quart's
    Response has no call_on_close/equivalent completion hook — confirmed
    against the actual installed Quart version, not assumed)."""
    path = request.args.get("path", "")
    version_id_raw = request.args.get("version_id", "")
    if not path or not storage.is_safe_path(path) or not version_id_raw.isdigit():
        return jsonify({"error": "Invalid request"}), 400

    full_path = os.path.join(ROOT_DIR, path)
    ok, message, size, download_filename, chunks = await asyncio.to_thread(
        version_history.open_download_stream, full_path, int(version_id_raw)
    )
    if not ok:
        return jsonify({"error": message}), 400

    async def _stream():
        # Pull the (blocking, disk-bound) sync generator one 1 MB block at a
        # time on a worker thread so the event loop never stalls. Any
        # integrity failure raises here, aborting the response rather than
        # delivering corrupt bytes.
        sentinel = object()
        try:
            while True:
                block = await asyncio.to_thread(next, chunks, sentinel)
                if block is sentinel:
                    break
                yield block
        finally:
            chunks.close()

    mimetype = mimetypes.guess_type(download_filename)[0] or "application/octet-stream"
    response = Response(_stream(), mimetype=mimetype)
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{download_filename}"'
    )
    response.headers["Content-Length"] = str(size)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/download/recovered/<path:recovered_rel>")
@login_required
async def download_recovered(recovered_rel):
    """Download a file previously restored into .recovered/ by
    /api/versions/restore. Deliberately does NOT use storage.is_safe_path
    (that helper's handling of a dot-prefixed top-level directory like
    RECOVERED_DIRNAME hasn't been verified against the live storage.py —
    see handoff doc) — this route does its own containment check, scoped
    strictly to version_history.RECOVERED_ROOT, which is narrower and
    doesn't depend on that assumption either way."""
    candidate = os.path.abspath(
        os.path.join(version_history.RECOVERED_ROOT, recovered_rel)
    )
    if not version_history.is_within_recovered(candidate):
        return "Invalid path", 400
    if not os.path.exists(candidate) or os.path.isdir(candidate):
        return "File not found", 404

    directory = os.path.dirname(candidate)
    filename = os.path.basename(candidate)
    return await send_from_directory(directory, filename, as_attachment=True)


@app.route("/api/versions/retry", methods=["POST"])
@login_required
async def api_versions_retry():
    """Capture the live file right now instead of waiting for the next
    scheduled scan/watch event — shown in the UI only when the file's
    most recent version failed to capture."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    data = await request.get_json(silent=True) or {}
    path = data.get("path", "")
    if not path or not storage.is_safe_path(path):
        return jsonify({"error": "Invalid request"}), 400

    full_path = os.path.join(ROOT_DIR, path)
    ok, message, new_version = await asyncio.to_thread(
        version_history.retry_snapshot, full_path
    )
    logging.info(f"Version retry-snapshot by {current_user()}: {path} -> {message}")
    return jsonify({"success": ok, "message": message, "version": new_version}), (
        200 if ok else 400
    )


@app.route("/api/versions/clear-failed", methods=["POST"])
@login_required
async def api_versions_clear_failed():
    """Permanently remove a file's failed-capture rows. Only ever touches
    status='failed' — a failed capture never produced a restorable
    version, so nothing recoverable is lost (see
    Engine.clear_failed_versions())."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    data = await request.get_json(silent=True) or {}
    path = data.get("path", "")
    if not path or not storage.is_safe_path(path):
        return jsonify({"error": "Invalid request"}), 400

    full_path = os.path.join(ROOT_DIR, path)
    ok, message, removed = await asyncio.to_thread(
        version_history.clear_failed, full_path
    )
    logging.info(
        f"Version failed-attempts cleared by {current_user()}: {path} ({removed})"
    )
    return jsonify({"success": ok, "message": message, "removed": removed})


@app.route("/api/versions/delete", methods=["POST"])
@login_required
async def api_versions_delete():
    """Permanently (soft-)delete one version. confirm_text is checked
    server-side inside version_history.delete() — see its docstring;
    never trust a client-side-only confirm() dialog for this."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    data = await request.get_json(silent=True) or {}
    path = data.get("path", "")
    version_id = data.get("version_id")
    confirm_text = data.get("confirm_text", "")
    if not path or not storage.is_safe_path(path) or not isinstance(version_id, int):
        return jsonify({"error": "Invalid request"}), 400

    full_path = os.path.join(ROOT_DIR, path)
    ok, message = await asyncio.to_thread(
        version_history.delete, full_path, version_id, confirm_text
    )
    if not ok:
        return jsonify({"error": message}), 400

    logging.info(f"Version deleted by {current_user()}: {path} v{version_id}")
    return jsonify({"success": True, "message": message})
