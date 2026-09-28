#!/usr/bin/env python3
"""
version_history.py — Web-layer logic for the Version History feature
=========================================================================
Pure logic module, no `@app.route` — mirrors this codebase's existing
convention (realtime_shares.py, realtime_stats.py, search_index.py) of
"logic lives in its own module, route handlers live in app.py". See
version_history_web_ui_prompt.md §0/§3 for the design this was built from.

Runs INSIDE the Quart/Hypercorn process (app.py), not inside the Version
Engine's own child process. Every function here is synchronous — app.py's
route handlers are the ones that wrap calls into this module with
`await asyncio.to_thread(...)`. Nothing in this file should ever be
awaited directly.

Two things this module deliberately does NOT do:
  - Primary path authorization. By the time a call reaches this module,
    app.py's route handler has already resolved and authorized the
    requested file_path exactly like existing download/browse routes
    (storage.is_safe_path() + os.path.join(ROOT_DIR, path)). This module
    only does a defensive second check (_within_root) as a last line of
    defense, never the primary one.
  - Starting the Version Engine's watcher/scanner/worker threads. init()
    only bootstraps the schema and directories (mirrors
    version_manage.py's _get_engine()) — no threads, no subprocess.

Restore semantics (deliberately NOT in-place overwrite of the live file):
  A web-UI restore never touches the live file directly. It reconstructs
  the requested version, byte-for-byte verified exactly like
  Engine.restore_version() already guarantees, into a dedicated hidden
  top-level directory under ROOT_DIR: `.recovered/` — mirroring the
  existing `.chunks/` convention (see app.py's chunked-upload staging
  dir) of a dot-prefixed ROOT_DIR subdirectory that isn't meant to show
  up in the normal file browser. Each restore lands at:

      .recovered/<original's relative directory>/
          <original stem>__<version's original date, YYYY-MM-DD_HHMMSS>
          __v<version_id><original extension>

  e.g. restoring version 42 of "docs/report.docx" (snapshotted
  2026-09-20 14:30:12) lands at:

      .recovered/docs/report__2026-09-20_143012__v42.docx

  This is intentional, not a placeholder for "real" in-place restore:
  the live file is never silently replaced. The user gets a clearly
  dated, clearly version-tagged sibling copy alongside where the
  original lives, and can inspect/rename/move/delete it like any other
  file — including feeding it back through a normal move/rename if they
  decide to actually replace the live file with it. Restoring the same
  version twice lands at the exact same path (deterministic naming) and
  is treated as a harmless re-verify-and-rewrite, not an error.

  NOTE: this differs from version_manage.py's CLI `restore` command,
  which restores to any destination the operator names, in place if they
  ask for it, with a typed-confirmation gate before overwriting. That
  CLI behavior is unchanged by this module — see
  version_history_web_ui_prompt.md and CLAUDE.md's Version Engine
  section for that command's own documented behavior. The web UI's
  restore-to-.recovered/ behavior is a deliberately safer, DIFFERENT
  default for a browser UI where there is no terminal-style typed
  confirmation friction protecting an in-place overwrite.

Download semantics: a version's content can also be streamed straight to
the browser WITHOUT creating anything under .recovered/ and without
touching the live file at all — reconstructed into a throwaway OS temp
directory (outside both ROOT_DIR and the Version Engine's own storage
directory), streamed, then deleted. Use prepare_download()'s returned
cleanup() callback to remove it once the response has been sent.
"""

import os
import sqlite3
import threading
import time

import config
import logging_setup
import version_engine as ve

log = logging_setup.get_logger("version_history")

# The Version Engine's worker is a separate OS process writing to the same
# SQLite file. When it holds the write lock past busy_timeout, this process
# gets `sqlite3.OperationalError: database is locked`. Every web-side call
# below retries that specific error with backoff (these functions run in
# asyncio.to_thread, so sleeping is fine) instead of surfacing a 500.
_LOCK_RETRY_DELAYS = (0.25, 0.5, 1.0, 2.0, 3.0)
_BUSY_MSG = (
    "The version database is busy (the Version Engine is writing to it). "
    "Please try again in a few seconds."
)


def _is_lock_error(exc) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and any(
        s in str(exc).lower() for s in ("locked", "busy")
    )


def _with_lock_retry(fn, *args, **kwargs):
    for delay in _LOCK_RETRY_DELAYS:
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if not _is_lock_error(e):
                raise
            log.warning(
                "%s hit '%s' - retrying in %.2fs", getattr(fn, "__name__", fn), e, delay
            )
            time.sleep(delay)
    return fn(*args, **kwargs)  # last attempt; caller handles the raise


def _fail_message(prefix: str, exc: Exception) -> str:
    if _is_lock_error(exc):
        return _BUSY_MSG
    return f"{prefix}: {exc}"


try:
    ROOT_DIR = config.ROOT_DIR
except AttributeError:
    # Should not happen in this codebase (app.py imports ROOT_DIR from
    # config the same way) — fail loudly rather than silently operating
    # against the wrong root if config.py's shape ever changes.
    raise RuntimeError(
        "version_history.py requires config.ROOT_DIR — check config.py's shape "
        "hasn't changed since this module was written (2026-09-26)."
    )

RECOVERED_DIRNAME = getattr(config, "VERSION_RECOVERED_DIRNAME", ".recovered")
RECOVERED_ROOT = os.path.join(ROOT_DIR, RECOVERED_DIRNAME)

_engine = None

# In-flight restores (2026-09-28). Double-clicking Restore used to start two
# reconstructions of the same version at once; both wrote/renamed the same
# files in .recovered/ -> WinError 32. Now the second request is refused
# immediately (HTTP 409 from app.py) while the first is running, and the
# UI can ask which versions are busy via inflight_versions().
IN_PROGRESS_MSG = (
    "This version is already being restored. Please wait for it to finish."
)
_inflight = set()
_inflight_lock = threading.Lock()


def _inflight_key(resolved_file_path: str, version_id: int):
    return (ve._normalize_path(resolved_file_path), int(version_id))


def inflight_versions(resolved_file_path: str) -> list:
    """version_ids of this file that are being restored right now."""
    norm = ve._normalize_path(resolved_file_path)
    with _inflight_lock:
        return sorted(v for (p, v) in _inflight if p == norm)


def init():
    """Bootstrap this module's own Engine instance — schema + directories
    only, no threads, no subprocess. Call exactly once, from app.py's own
    module-level startup code (NOT from dev_server.py/prod_server.py,
    which start the separate Version Engine subprocess via
    version_engine.start() — an entirely different thing). Calling this
    more than once is harmless (idempotent — _bootstrap_schema() just
    re-runs CREATE TABLE IF NOT EXISTS) but should only happen once in
    practice."""
    global _engine
    if _engine is not None:
        return
    engine = ve.Engine()
    engine._ensure_dirs()
    engine._bootstrap_schema()
    os.makedirs(RECOVERED_ROOT, exist_ok=True)
    _engine = engine


def _get_engine() -> ve.Engine:
    if _engine is None:
        # Defensive fallback — init() should always have run by the time a
        # request reaches here, but don't 500 with an unhelpful
        # AttributeError if app.py's startup wiring is ever reordered.
        init()
    return _engine


def is_within_recovered(path: str) -> bool:
    """Public wrapper so app.py's dedicated recovered-file download route
    can validate a requested path is contained within RECOVERED_ROOT
    without reaching into this module's private helper."""
    return _within_root(path, RECOVERED_ROOT)


def _within_root(path: str, root: str) -> bool:
    path = os.path.abspath(path)
    root = os.path.abspath(root)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        # Different drives on Windows, etc. — definitely not contained.
        return False


def _version_belongs_to(version: dict, resolved_file_path: str) -> bool:
    """Cross-file authorization guard: confirms a version_id actually
    belongs to the file the caller was authorized for, not some other
    tracked file the caller has no business touching. app.py authorizes
    file_path; this is what stops a version_id for a DIFFERENT (perhaps
    unauthorized) file from being smuggled through a request that only
    named an authorized file_path in its URL."""
    if not version:
        return False
    return ve._normalize_path(version["file_path"]) == ve._normalize_path(
        resolved_file_path
    )


# ------------------------------------------------------------------
# Read
# ------------------------------------------------------------------


def get_history(resolved_file_path: str):
    """List of version dicts (newest first) for one file, or None if the
    file has no tracking history at all. resolved_file_path must already
    be an authorized, absolute (or ROOT_DIR-relative-resolved-to-absolute)
    path — app.py's route does that resolution before calling this."""
    return _with_lock_retry(_get_engine().list_versions, resolved_file_path)


def list_tracked():
    """Every tracked file with its version count — for an admin-facing
    overview. app.py's route is responsible for restricting this to
    readwrite/admin users if that overview is exposed at all; this
    function itself has no per-user concept."""
    return _get_engine().list_tracked_files()


def get_version_info(version_id: int, resolved_file_path: str):
    """Single version's metadata, or None if it doesn't exist OR doesn't
    belong to resolved_file_path (the cross-file guard is applied here so
    every caller gets it for free rather than remembering to call
    _version_belongs_to() separately)."""
    version = _with_lock_retry(_get_engine().get_version, version_id)
    if version is None or not _version_belongs_to(version, resolved_file_path):
        return None
    return version


# ------------------------------------------------------------------
# Restore-to-.recovered/
# ------------------------------------------------------------------


def _recovered_destination(resolved_file_path: str, version: dict) -> str:
    """Deterministic .recovered/ path for one (file, version) pair — see
    module docstring for the naming scheme and rationale."""
    rel = os.path.relpath(resolved_file_path, ROOT_DIR)
    rel_dir = os.path.dirname(rel)
    base = os.path.basename(rel)
    stem, ext = os.path.splitext(base)

    created = version["created_at"]
    date_tag = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(created))

    new_name = f"{stem}__{date_tag}__v{version['version_id']}{ext}"
    return os.path.join(RECOVERED_ROOT, rel_dir, new_name)


def restore(resolved_file_path: str, version_id: int):
    """Reconstruct version_id into .recovered/ (see module docstring —
    NEVER overwrites the live file). Returns (ok, message,
    recovered_rel_path). recovered_rel_path is relative to ROOT_DIR (e.g.
    ".recovered/docs/report__2026-09-20_143012__v42.docx"), suitable for
    handing straight to app.py's dedicated recovered-file download route
    — see version_history_web_ui_prompt.md §4's route sketch, adapted."""
    engine = _get_engine()
    try:
        version = _with_lock_retry(engine.get_version, version_id)
    except Exception as e:
        log.exception("restore: get_version(%s) failed", version_id)
        return False, _fail_message("Restore failed", e), None
    if version is None:
        return False, f"No such version_id: {version_id}", None
    if not _version_belongs_to(version, resolved_file_path):
        return False, "That version does not belong to this file.", None
    if version["status"] != "completed":
        msg = f"version_id {version_id} is not restorable (status={version['status']})."
        if version.get("error"):
            msg += f" {version['error']}"
        return False, msg, None

    destination = _recovered_destination(resolved_file_path, version)
    if not _within_root(destination, RECOVERED_ROOT):
        # Should be unreachable (destination is built entirely from
        # RECOVERED_ROOT + a relpath + a synthesized filename, no raw
        # user input) - defensive check kept anyway per section 5's checklist.
        return False, "Refusing to restore outside the recovered-files area.", None

    recovered_rel = None
    key = _inflight_key(resolved_file_path, version_id)
    with _inflight_lock:
        if key in _inflight:
            return False, IN_PROGRESS_MSG, None
        _inflight.add(key)
    try:
        # Fast path: the destination name is unique per (file, version) and
        # the engine only ever publishes it by atomic rename AFTER full
        # sha256+size verification, so an existing file of the right size is
        # a complete, verified restore - no need to rebuild it again.
        try:
            if (
                os.path.isfile(destination)
                and os.path.getsize(destination) == version["size"]
            ):
                recovered_rel = os.path.relpath(destination, ROOT_DIR).replace(
                    os.sep, "/"
                )
                return (
                    True,
                    f"Restored version {version_id} to {recovered_rel}",
                    recovered_rel,
                )
        except OSError:
            pass

        try:
            result_path = _with_lock_retry(
                engine.restore_version, version_id, destination, overwrite=True
            )
        except ve.VersionEngineError as e:
            return False, f"Restore failed: {e}", None
        except Exception as e:
            # Anything else used to escape as an HTML 500, which the browser
            # reported as "Could not reach the server". Log the real cause.
            log.exception("restore: restore_version(%s) failed", version_id)
            return False, _fail_message("Restore failed", e), None

        recovered_rel = os.path.relpath(result_path, ROOT_DIR).replace(os.sep, "/")
        return True, f"Restored version {version_id} to {recovered_rel}", recovered_rel
    finally:
        with _inflight_lock:
            _inflight.discard(key)


# ------------------------------------------------------------------
# Download (stream a version's content without restoring anything)
# ------------------------------------------------------------------


def prepare_download(resolved_file_path: str, version_id: int):
    """Reconstruct version_id into a throwaway OS temp directory, read its
    bytes into memory, and remove the temp directory again — all inside
    this one synchronous call (meant to be run via asyncio.to_thread).

    Returns (ok, message, data: bytes | None, download_filename: str | None).

    This buffers the whole version's content in memory rather than
    streaming it. That trade-off is deliberate: Quart's Response class
    (confirmed against the actual installed version — 0.22.0 as of this
    writing) has no Flask/Werkzeug-style `call_on_close` hook or
    equivalent, so there is no supported way to run cleanup exactly when
    a streamed `send_from_directory` response has finished sending.
    Buffering avoids needing one at all: the temp file is gone before
    app.py ever starts building the HTTP response, so there's nothing
    left to clean up after the fact, and nothing that can be verified
    only by re-checking it — the tradeoff is memory proportional to the
    version's size for the duration of one request. Fine for the file
    sizes this project targets; if this project ever needs to hand back
    very large versions without buffering them, revisit this using
    Quart's `app.add_background_task` (still not a per-response
    completion hook, so it would need pairing with something that
    signals when the body iterator is actually exhausted, e.g. a
    wrapping async generator app.py constructs itself around the file
    body) rather than assuming call_on_close will someday exist."""
    import shutil
    import tempfile

    engine = _get_engine()
    try:
        version = _with_lock_retry(engine.get_version, version_id)
    except Exception as e:
        log.exception("download: get_version(%s) failed", version_id)
        return False, _fail_message("Could not prepare download", e), None, None
    if version is None:
        return False, f"No such version_id: {version_id}", None, None
    if not _version_belongs_to(version, resolved_file_path):
        return False, "That version does not belong to this file.", None, None
    if version["status"] != "completed":
        msg = (
            f"version_id {version_id} is not downloadable (status={version['status']})."
        )
        if version.get("error"):
            msg += f" {version['error']}"
        return False, msg, None, None

    tmp_dir = tempfile.mkdtemp(prefix="cloudinator_vhdownload_")
    base = os.path.basename(resolved_file_path)
    stem, ext = os.path.splitext(base)
    date_tag = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(version["created_at"]))
    download_filename = f"{stem}__{date_tag}__v{version_id}{ext}"
    temp_path = os.path.join(tmp_dir, download_filename)

    try:
        result_path = _with_lock_retry(
            engine.restore_version, version_id, temp_path, overwrite=True
        )
        with open(result_path, "rb") as f:
            data = f.read()
    except ve.VersionEngineError as e:
        return False, f"Could not prepare download: {e}", None, None
    except Exception as e:
        log.exception("download: restore_version(%s) failed", version_id)
        return False, _fail_message("Could not prepare download", e), None, None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return True, "ok", data, download_filename


def open_download_stream(resolved_file_path: str, version_id: int):
    """Fast download: no rebuild, no temp file, no whole-file buffering.

    Returns (ok, message, size, download_filename, chunk_iterator). The
    iterator yields the version's bytes directly from the object store
    (verified as it goes - see Engine.iter_version_bytes) and is meant to be
    pulled via asyncio.to_thread by app.py. Supersedes prepare_download()
    for the web route (kept for compatibility, now unused by app.py)."""
    engine = _get_engine()
    try:
        version = _with_lock_retry(engine.get_version, version_id)
    except Exception as e:
        log.exception("download: get_version(%s) failed", version_id)
        return False, _fail_message("Could not prepare download", e), None, None, None
    if version is None:
        return False, f"No such version_id: {version_id}", None, None, None
    if not _version_belongs_to(version, resolved_file_path):
        return False, "That version does not belong to this file.", None, None, None
    if version["status"] != "completed":
        msg = (
            f"version_id {version_id} is not downloadable (status={version['status']})."
        )
        if version.get("error"):
            msg += f" {version['error']}"
        return False, msg, None, None, None

    base = os.path.basename(resolved_file_path)
    stem, ext = os.path.splitext(base)
    date_tag = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(version["created_at"]))
    filename = f"{stem}__{date_tag}__v{version_id}{ext}"
    return True, "ok", version["size"], filename, engine.iter_version_bytes(version_id)


# ------------------------------------------------------------------
# Clear failed attempts / retention summary
# ------------------------------------------------------------------


def clear_failed(resolved_file_path: str):
    """Permanently remove this file's failed-capture rows (see
    Engine.clear_failed_versions() for why that's safe: a failed capture
    never became a restorable version). Returns (ok, message, removed)."""
    try:
        removed = _with_lock_retry(
            _get_engine().clear_failed_versions, resolved_file_path
        )
    except Exception as e:
        log.exception("clear_failed failed")
        return False, _fail_message("Could not clear failed attempts", e), 0
    if removed == 0:
        return True, "There were no failed attempts to clear.", 0
    noun = "attempt" if removed == 1 else "attempts"
    return True, f"Cleared {removed} failed {noun}.", removed


def retention_info(versions):
    """What the modal needs for its "12 of 50 versions kept" line.

    `kept` counts only status='completed' rows, because that is exactly
    what Engine._apply_retention() counts — failed and deleted rows don't
    use up the allowance. Reads config at call time (not import time) so a
    runtime change to VERSION_MAX_VERSIONS is reflected immediately."""
    return {
        "enabled": bool(config.VERSION_RETENTION_ENABLED),
        "max": int(config.VERSION_MAX_VERSIONS),
        "kept": sum(1 for v in (versions or []) if v["status"] == "completed"),
    }


# ------------------------------------------------------------------
# Retry — capture the live file right now, instead of waiting for the
# next scheduled scan/watch event to happen to pick it back up.
# ------------------------------------------------------------------


def retry_snapshot(resolved_file_path: str):
    """Trigger a fresh snapshot attempt of resolved_file_path immediately
    (used by the "Retry Now" action shown when a file's most recent
    version failed to capture — see version_engine.py's snapshot_file()
    for what "capture" actually does; this just calls it on demand).

    Returns (ok: bool, message: str, new_version: dict | None).

    Engine.snapshot_file() itself returns a version_id on a genuinely new
    completed snapshot, or None for BOTH a failure and a dedup-skip (the
    file's current content is byte-identical to the latest completed
    version, so nothing new was needed) — those two None cases read very
    differently to a person clicking "Retry", so this function tells them
    apart by diffing the version list before and after the call, rather
    than trusting snapshot_file()'s return value alone."""
    engine = _get_engine()
    before_ids = {
        v["version_id"]
        for v in (_with_lock_retry(engine.list_versions, resolved_file_path) or [])
    }

    try:
        engine.snapshot_file(resolved_file_path, source="web-retry")
    except Exception as e:
        log.exception("retry: snapshot_file failed")
        return False, _fail_message("Retry failed", e), None

    if engine.last_snapshot_busy():
        # The engine gave up because the DB stayed locked, so no version row
        # (failed or otherwise) exists. Without this the diff below would say
        # "already up to date", which would be false.
        return False, _BUSY_MSG, None

    after = _with_lock_retry(engine.list_versions, resolved_file_path) or []
    new_versions = [v for v in after if v["version_id"] not in before_ids]

    if not new_versions:
        return (
            True,
            "No new snapshot was needed — the file's current content already "
            "matches the most recent saved version.",
            None,
        )

    newest = new_versions[0]  # after is newest-first, per list_versions()
    if newest["status"] == "completed":
        return True, "Snapshot captured successfully.", newest

    msg = "The retry failed again."
    if newest.get("error"):
        msg += f" {newest['error']}"
    if "locked" in (newest.get("error") or "").lower():
        msg += (
            " (the Version Engine's background worker was writing to the "
            "database at the same time - try again in a few seconds)"
        )
    return False, msg, newest


def expected_delete_confirmation(resolved_file_path: str) -> str:
    """The exact string a client must submit to confirm a delete — the
    basename of the file, matching the frontend's typed-confirmation
    modal (see version_history_web_ui_prompt.md §3's recommendation of a
    two-step "type it back" UI, mirroring version_manage.py's CLI
    confirmation-phrase pattern but scoped to something short enough to
    type comfortably in a browser modal)."""
    return os.path.basename(resolved_file_path)


def delete(resolved_file_path: str, version_id: int, confirm_text: str):
    """Permanently (soft-)delete one version. confirm_text is checked
    SERVER-SIDE against expected_delete_confirmation() — never trust a
    client-side-only confirm() dialog for this, per §5's checklist."""
    engine = _get_engine()
    try:
        version = _with_lock_retry(engine.get_version, version_id)
    except Exception as e:
        log.exception("delete: get_version(%s) failed", version_id)
        return False, _fail_message("Delete failed", e)
    if version is None:
        return False, f"No such version_id: {version_id}"
    if not _version_belongs_to(version, resolved_file_path):
        return False, "That version does not belong to this file."

    expected = expected_delete_confirmation(resolved_file_path)
    if (confirm_text or "").strip() != expected:
        return False, "Confirmation text did not match — nothing was deleted."

    try:
        ok, message = _with_lock_retry(
            engine.delete_version, version_id, reason="deleted via web UI"
        )
    except Exception as e:
        log.exception("delete: delete_version(%s) failed", version_id)
        return False, _fail_message("Delete failed", e)
    return ok, message
