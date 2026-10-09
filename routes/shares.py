"""
routes/shares.py - share links: owner API (/api/share*, /api/unshare), public /shared/<token>/*,
/admin/shares* and the revoke-all codes (Phase 7 of the split, CLAUDE.md 4.75).

Moved verbatim from app.py. The CSRF-exempt endpoints live here with their @csrf.exempt decorators
unchanged (csrf comes from core: never a second CSRFProtect). Gets shared objects via
`from core import ...`; imports no other route module.
"""

from core import (
    _REVOKE_CODE_TTL,
    _SHARE_UNLOCK_MAX_AGE,
    _check_revoke_all_code,
    _issue_revoke_all_code,
    _share_unlock_signer,
    _stream_from_thread,
    app,
    csrf,
    login_required,
)

from quart import (
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
import os
import asyncio
import time
import logging
import uuid
import zipstream
from config import ROOT_DIR
from database import db
from auth import current_user, get_role
import storage
import secrets as _secrets
from itsdangerous import BadSignature, SignatureExpired
from realtime_shares import (
    share_events_sse,
    trigger_share_event,
    trigger_active_shares_changed,
)


def _generate_passkey(length: int = 8) -> str:
    """Short, readable random passkey — ambiguous chars (0/O, 1/l/I) excluded
    since it's meant to be typed by a human, not pasted."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    return "".join(_secrets.choice(alphabet) for _ in range(length))


def _extract_security_fields(data):
    """Parse security_mode/passkey/generate_passkey/expires_at out of a share
    create/bulk-share request body. Returns
    (security_mode, passkey_or_None, generate_bool, expires_at_or_None, error_or_None).
    """
    security_mode = data.get("security_mode", "public")
    if security_mode not in ("public", "passkey", "approval"):
        return None, None, False, None, "Invalid security_mode"

    passkey = (data.get("passkey") or "").strip() or None
    generate = bool(data.get("generate_passkey"))

    expires_at = None
    expires_raw = data.get("expires_at")
    if expires_raw not in (None, "", "never"):
        try:
            expires_at = float(expires_raw)
        except (TypeError, ValueError):
            return None, None, False, None, "Invalid expires_at"
        if expires_at <= time.time():
            return None, None, False, None, "expires_at must be in the future"

    return security_mode, passkey, generate, expires_at, None


def _passkey_cookie_name(token: str) -> str:
    return f"su_{token}"


def _approval_cookie_name(token: str) -> str:
    return f"ar_{token}"


def _share_is_expired(share: dict) -> bool:
    exp = share.get("expires_at")
    return bool(exp) and time.time() > exp


def _prune_expired_shares(shares: list) -> list:
    """Filter an active-shares list down to genuinely live ones, revoking
    any that are past expires_at along the way. Same lazy-cleanup pattern
    as _get_live_share, but applied to the whole list — used by the
    Manage Shared → Active Shares endpoints so an expired share can't sit
    there looking "active" just because no visitor has hit its link yet
    and the periodic background sweep hasn't gotten to it."""
    live = []
    pruned_any = False
    for s in shares:
        if _share_is_expired(s):
            db.revoke_share_by_token(s["token"])
            pruned_any = True
        else:
            live.append(s)
    if pruned_any:
        # Let every connected admin know — not just whoever made this
        # particular request — so the Active Shares tab updates even in a
        # tab that's just sitting open and never re-fetches on its own.
        try:
            trigger_active_shares_changed("expired")
        except Exception as e:
            logging.warning(f"Failed to broadcast active-shares change: {e}")
    return live


def _get_live_share(token: str):
    """Fetch a share by token, lazily revoking (and returning None for) it
    if it's past its expires_at. Used by every route that touches a share
    token — landing page, passkey verify, request-access, and download —
    so an expired share gets cleaned up out of the active-shares list on
    whichever route a visitor happens to hit first, not just the landing
    page. Without this, list_active_shares() (and the revoke-all count)
    would keep counting shares that are already inaccessible everywhere
    else, until someone happened to reload the plain landing page again."""
    share = db.get_share_by_token(token)
    if not share:
        return None
    if _share_is_expired(share):
        db.revoke_share_by_token(token)
        try:
            trigger_active_shares_changed("expired")
        except Exception as e:
            logging.warning(f"Failed to broadcast active-shares change: {e}")
        return None
    return share


def _is_passkey_unlocked(token: str) -> bool:
    cookie = request.cookies.get(_passkey_cookie_name(token))
    if not cookie:
        return False
    try:
        value = _share_unlock_signer.loads(cookie, max_age=_SHARE_UNLOCK_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return value == token


@app.route("/api/share", methods=["POST"])
@login_required
async def create_share():
    """Create (or return the existing) public share link for one file/folder,
    with optional security: a passkey gate, an admin-approval gate, and/or
    an expiry. Security settings only apply on first creation — to change
    them on an item that's already shared, use /api/share/settings."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    data = await request.get_json(silent=True) or {}
    path = data.get("path", "")
    if not path or not storage.is_safe_path(path):
        return jsonify({"error": "Invalid file path"}), 400

    full_path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(full_path):
        return jsonify({"error": "File not found"}), 404

    security_mode, passkey, generate, expires_at, err = _extract_security_fields(data)
    if err:
        return jsonify({"error": err}), 400

    plain_passkey = None
    if security_mode == "passkey":
        plain_passkey = passkey if (passkey and not generate) else _generate_passkey()

    is_dir = os.path.isdir(full_path)
    item_name = os.path.basename(full_path.rstrip("/\\"))
    token = await asyncio.to_thread(
        db.create_share,
        path,
        item_name,
        is_dir,
        current_user(),
        security_mode=security_mode,
        passkey=plain_passkey,
        expires_at=expires_at,
    )
    share_url = f"{request.host_url.rstrip('/')}/shared/{token}"

    logging.info(
        f"Share link created by {current_user()}: {path} (mode={security_mode})"
    )
    resp = {
        "success": True,
        "token": token,
        "share_url": share_url,
        "name": item_name,
        "security_mode": security_mode,
        "expires_at": expires_at,
    }
    if plain_passkey:
        # Only ever returned once, at creation/regeneration — we only store the hash.
        resp["passkey"] = plain_passkey
    return jsonify(resp)


@app.route("/api/share/settings", methods=["POST"])
@login_required
async def update_share_settings():
    """Edit an already-active share's security mode, passkey, or expiry —
    used by the Manage Shared panel."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    data = await request.get_json(silent=True) or {}
    token = data.get("token", "")
    if not token:
        return jsonify({"error": "token is required"}), 400
    share = db.get_share_by_token(token)
    if not share:
        return jsonify({"error": "Share not found or already revoked"}), 404

    security_mode = data.get("security_mode") or None
    if security_mode and security_mode not in ("public", "passkey", "approval"):
        return jsonify({"error": "Invalid security_mode"}), 400
    target_mode = security_mode or share["security_mode"]

    passkey_in = (data.get("passkey") or "").strip() or None
    generate = bool(data.get("generate_passkey"))
    clear_passkey = bool(data.get("clear_passkey"))
    plain_passkey = None
    if target_mode == "passkey" and (generate or passkey_in):
        plain_passkey = (
            passkey_in if (passkey_in and not generate) else _generate_passkey()
        )
    elif target_mode != "passkey":
        # Leaving passkey mode (e.g. switching to approval/public) must not
        # leave a stale passkey_hash behind — otherwise switching back to
        # "passkey" later without setting a new one silently revives the
        # old, previously-shown passkey.
        clear_passkey = True

    clear_expiry = bool(data.get("clear_expiry"))
    expires_at = None
    expires_raw = data.get("expires_at")
    if not clear_expiry and expires_raw not in (None, "", "never"):
        try:
            expires_at = float(expires_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid expires_at"}), 400
        if expires_at <= time.time():
            return jsonify({"error": "expires_at must be in the future"}), 400

    ok = await asyncio.to_thread(
        db.update_share_settings,
        token,
        security_mode=security_mode,
        passkey=plain_passkey,
        clear_passkey=clear_passkey,
        expires_at=expires_at,
        clear_expiry=clear_expiry,
    )
    if not ok:
        return jsonify({"error": "Nothing to update"}), 400

    logging.info(f"Share settings updated by {current_user()}: {token}")
    resp = {"success": True}
    if plain_passkey:
        resp["passkey"] = plain_passkey
    return jsonify(resp)


@app.route("/api/unshare", methods=["POST"])
@login_required
async def revoke_share():
    """Revoke the active share link for one file/folder, by path."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    data = await request.get_json(silent=True) or {}
    path = data.get("path", "")
    if not path:
        return jsonify({"error": "path is required"}), 400

    revoked = db.revoke_share_by_path(path)
    logging.info(f"Share link revoked by {current_user()}: {path} (found={revoked})")
    return jsonify({"success": True, "revoked": revoked})


@app.route("/api/share/status", methods=["GET"])
@login_required
async def share_status():
    """Return current share state for one path — used to populate the share modal."""
    path = request.args.get("path", "")
    if not path:
        return jsonify({"error": "path is required"}), 400
    share = db.get_share_by_path(path)
    if share:
        share_url = f"{request.host_url.rstrip('/')}/shared/{share['token']}"
        return jsonify(
            {
                "shared": True,
                "token": share["token"],
                "share_url": share_url,
                "security_mode": share["security_mode"],
                "has_passkey": bool(share["passkey_hash"]),
                "expires_at": share["expires_at"],
                "download_count": share["download_count"],
            }
        )
    return jsonify({"shared": False})


@app.route("/api/share/bulk", methods=["POST"])
@login_required
async def bulk_share():
    """Bulk share or unshare a list of paths (used by the multi-select bulk
    action bar). When bulk-sharing, the same security settings (mode /
    passkey / expiry) apply to every item in the batch."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    data = await request.get_json(silent=True) or {}
    paths = data.get("paths") or []
    action = data.get("action")
    if action not in ("share", "unshare"):
        return jsonify({"error": "action must be 'share' or 'unshare'"}), 400
    if not paths:
        return jsonify({"error": "No paths provided"}), 400

    results = {}
    if action == "share":
        security_mode, passkey, generate, expires_at, err = _extract_security_fields(
            data
        )
        if err:
            return jsonify({"error": err}), 400

        # One generated passkey is shared across the whole batch and shown once.
        batch_passkey = None
        if security_mode == "passkey":
            batch_passkey = (
                passkey if (passkey and not generate) else _generate_passkey()
            )

        for path in paths:
            if not storage.is_safe_path(path):
                results[path] = {"error": "Invalid path"}
                continue
            full_path = os.path.join(ROOT_DIR, path)
            if not os.path.exists(full_path):
                results[path] = {"error": "Not found"}
                continue
            is_dir = os.path.isdir(full_path)
            item_name = os.path.basename(full_path.rstrip("/\\"))
            token = await asyncio.to_thread(
                db.create_share,
                path,
                item_name,
                is_dir,
                current_user(),
                security_mode=security_mode,
                passkey=batch_passkey,
                expires_at=expires_at,
            )
            results[path] = {
                "token": token,
                "share_url": f"{request.host_url.rstrip('/')}/shared/{token}",
            }
        if batch_passkey:
            results["_passkey"] = batch_passkey
        logging.info(
            f"Bulk share by {current_user()}: {len(paths)} item(s), mode={security_mode}"
        )
    else:
        revoked_count = db.bulk_revoke_by_paths(paths)
        for path in paths:
            results[path] = {"revoked": True}
        logging.info(
            f"Bulk unshare by {current_user()}: {revoked_count}/{len(paths)} item(s)"
        )

    return jsonify({"success": True, "results": results})


def _human_size(num_bytes):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024 or unit == "TB":
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes} {unit}"
        num_bytes /= 1024


def _dir_size(path, cap_entries=20000):
    """Best-effort recursive size — bails out past cap_entries so a huge
    shared folder can't hang the landing page on every load."""
    total = 0
    count = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
            count += 1
            if count > cap_entries:
                return total, True  # size, truncated
    return total, False


@app.route("/shared/<token>")
async def shared_download(token):
    """
    Public landing page for a share token. No @login_required — this is
    the whole point of a share link (also whitelisted in validate_session()
    below, since that hook runs before route-level decorators even fire).

    Renders depending on the share's security_mode and this visitor's
    current unlock/approval status:
      - public                → straight to the Download button
      - passkey, locked       → passkey entry form
      - approval, no request  → "request access" form
      - approval, pending     → waiting-for-approval status (polls for a decision)
      - approval, approved    → Download button, with downloads-remaining shown
      - approval, denied/used → message + option to request again
    Expired, revoked, or unknown tokens all render the same "not available"
    page — a prober shouldn't be able to tell those cases apart.

    Deliberately does NOT stream file bytes itself. Chat apps and messengers
    auto-fetch a pasted link to build a preview card — if this route served
    the file directly, that preview fetch would count as a real download and
    burn bandwidth on large files. The actual bytes are served from
    /shared/<token>/download, reached only via the button click here.
    """
    share = _get_live_share(token)
    if not share:
        return await render_template("shared.html", valid=False), 404

    file_path = share["file_path"]
    full_path = (
        os.path.join(ROOT_DIR, file_path) if storage.is_safe_path(file_path) else None
    )
    if not full_path or not os.path.exists(full_path):
        return await render_template("shared.html", valid=False), 404

    is_dir = os.path.isdir(full_path)
    size_bytes, size_truncated = (
        _dir_size(full_path) if is_dir else (os.path.getsize(full_path), False)
    )

    mode = share["security_mode"]
    ctx = dict(
        valid=True,
        token=token,
        name=share["item_name"],
        is_dir=is_dir,
        size_display=_human_size(size_bytes),
        size_truncated=size_truncated,
        download_count=share["download_count"],
        security_mode=mode,
        unlocked=True,
        request_state=None,
        downloads_remaining=None,
    )

    if mode == "passkey":
        ctx["unlocked"] = _is_passkey_unlocked(token)

    elif mode == "approval":
        access_token = request.cookies.get(_approval_cookie_name(token))
        req = (
            db.get_access_request_by_access_token(access_token)
            if access_token
            else None
        )
        if req and req["token"] == token:
            if (
                req["status"] == "approved"
                and req["downloads_used"] < req["max_downloads"]
            ):
                ctx["unlocked"] = True
                ctx["downloads_remaining"] = (
                    req["max_downloads"] - req["downloads_used"]
                )
            elif req["status"] == "pending":
                ctx["unlocked"] = False
                ctx["request_state"] = "pending"
            elif req["status"] == "denied":
                ctx["unlocked"] = False
                ctx["request_state"] = "denied"
            else:  # approved, but the download grant is used up
                ctx["unlocked"] = False
                ctx["request_state"] = "used_up"
        else:
            ctx["unlocked"] = False
            ctx["request_state"] = None  # no request yet — show the request form

    return await render_template("shared.html", **ctx)


@app.route("/shared/<token>/passkey", methods=["POST"])
@csrf.exempt  # anonymous visitor, no session — CSRF tokens don't apply here (see shared_request_access below)
async def shared_verify_passkey(token):
    """Verify a passkey for a passkey-gated share; on success, sets a signed
    unlock cookie scoped to this token so the landing/download routes treat
    this browser as unlocked."""
    share = _get_live_share(token)
    if not share or share["security_mode"] != "passkey":
        return jsonify({"error": "Not available"}), 404

    data = await request.get_json(silent=True) or {}
    passkey = (data.get("passkey") or "").strip()
    if not passkey or not await asyncio.to_thread(
        db.verify_share_passkey, token, passkey
    ):
        return jsonify({"success": False, "error": "Incorrect passkey"}), 403

    resp = jsonify({"success": True})
    resp.set_cookie(
        _passkey_cookie_name(token),
        _share_unlock_signer.dumps(token),
        max_age=_SHARE_UNLOCK_MAX_AGE,
        httponly=True,
        samesite="Lax",
    )
    return resp


@app.route("/shared/<token>/request", methods=["POST"])
@csrf.exempt
# Both share-link POST endpoints above are hit by anonymous visitors who were
# never issued a session or a CSRF token (shared.html has no login session —
# it's a public link). CSRFProtect(app) at the top of this file protects
# every POST/PUT/PATCH/DELETE by default, so without this exemption these
# two routes 400 with "The CSRF token is missing" before ever reaching the
# database — that's not a hypothetical, it silently swallowed every access
# request submitted from the landing page. CSRF exemption is correct here
# (not a token workaround) because there's no authenticated session for a
# forged cross-site request to piggyback on in the first place.
async def shared_request_access(token):
    """Submit an access request for an approval-gated share. Issues an
    access_token cookie the visitor's browser uses to poll status and,
    once approved, to authorize downloads."""
    share = _get_live_share(token)
    if not share or share["security_mode"] != "approval":
        return jsonify({"error": "Not available"}), 404

    data = await request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    note = (data.get("note") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    access_token = db.create_access_request(token, name, note)
    logging.info(f"Access requested for share {token} by '{name}'")

    try:
        trigger_share_event(len(db.list_pending_requests()), "created")
    except Exception as e:
        # Never let a broadcast hiccup break the actual request submission —
        # this is an anonymous visitor-facing route.
        logging.warning(f"Failed to broadcast share-request event: {e}")

    resp = jsonify({"success": True, "status": "pending"})
    resp.set_cookie(
        _approval_cookie_name(token),
        access_token,
        max_age=_SHARE_UNLOCK_MAX_AGE,
        httponly=True,
        samesite="Lax",
    )
    return resp


@app.route("/shared/<token>/status", methods=["GET"])
async def shared_request_status(token):
    """Polled by the landing page while a request is pending, so the
    visitor doesn't have to keep refreshing manually."""
    access_token = request.cookies.get(_approval_cookie_name(token))
    if not access_token:
        return jsonify({"status": "none"})
    req = db.get_access_request_by_access_token(access_token)
    if not req or req["token"] != token:
        return jsonify({"status": "none"})
    if req["status"] == "approved" and req["downloads_used"] < req["max_downloads"]:
        return jsonify(
            {
                "status": "approved",
                "downloads_remaining": req["max_downloads"] - req["downloads_used"],
            }
        )
    if req["status"] == "approved":
        return jsonify({"status": "used_up"})
    return jsonify({"status": req["status"]})


def _resolve_shared_subpath(share, subpath):
    """Resolve a browse/download subpath against a share's OWN root, and
    refuse anything that would land outside it.

    storage.is_safe_path only proves a path can't escape ROOT_DIR — it says
    nothing about staying inside *this specific share's* folder. Without an
    extra check here, sharing folder A would let a visitor request a
    subpath that resolves to sibling folder B under ROOT_DIR, which was
    never shared. This adds that second, tighter containment check (and
    covers '..' segments and symlink escapes via realpath comparison, not
    just string prefix matching).

    Returns (rel_path, full_path) — both relative-to-ROOT_DIR and absolute —
    or (None, None) if the subpath is invalid, escapes the share, or the
    target doesn't exist.
    """
    share_root = share["file_path"]
    rel_path = os.path.normpath(os.path.join(share_root, subpath or "")).replace(
        "\\", "/"
    )
    if rel_path in (".", ""):
        rel_path = share_root

    if not storage.is_safe_path(rel_path):
        return None, None

    full_path = os.path.join(ROOT_DIR, rel_path)
    share_full_root = os.path.realpath(os.path.join(ROOT_DIR, share_root))
    real_full = os.path.realpath(full_path)
    if real_full != share_full_root and not real_full.startswith(
        share_full_root + os.sep
    ):
        return None, None

    if not os.path.exists(full_path):
        return None, None

    return rel_path, full_path


def _shared_access_granted(token, share):
    """Re-check the passkey/approval gate for the current visitor. This is
    the single source of truth for "is this browser allowed to see/download
    this share right now" — shared_download (landing page), shared_browse,
    shared_download_item, and shared_zip_selected all call this instead of
    each re-implementing the check, so the gate can't drift out of sync
    between routes.

    Returns (granted: bool, access_token: str | None). access_token is only
    populated for approval mode, since callers that record a download need
    it to know which access-request row to decrement against.
    """
    mode = share["security_mode"]
    if mode == "public":
        return True, None
    if mode == "passkey":
        return _is_passkey_unlocked(share["token"]), None
    if mode == "approval":
        access_token = request.cookies.get(_approval_cookie_name(share["token"]))
        req = (
            db.get_access_request_by_access_token(access_token)
            if access_token
            else None
        )
        if (
            req
            and req["token"] == share["token"]
            and req["status"] == "approved"
            and req["downloads_used"] < req["max_downloads"]
        ):
            return True, access_token
        return False, access_token
    return False, None


def _stream_folder_zip(full_path, arc_name):
    """Stream a folder as a ZIP under mimetype application/zip. arc_name is
    the folder's name as it should appear at the top level of the archive.
    Shared by the top-level share download, single-subfolder download, and
    reused (with a slightly different inner loop) by shared_zip_selected."""

    def generate_zip_stream():
        zf = zipstream.ZipFile(
            mode="w", compression=zipstream.ZIP_DEFLATED, allowZip64=True
        )
        for root, dirs, files in os.walk(full_path):
            rel_path = os.path.relpath(root, full_path)
            arc_root = (
                arc_name
                if rel_path == "."
                else os.path.join(arc_name, rel_path).replace("\\", "/")
            )
            for file in files:
                try:
                    fp = os.path.join(root, file)
                    zf.write(
                        fp, arcname=os.path.join(arc_root, file).replace("\\", "/")
                    )
                except (PermissionError, OSError) as e:
                    logging.warning(f"Shared ZIP: skipped {fp}: {e}")
                    continue
            if not files and not dirs:
                zf.writestr(arc_root + "/", "")
        for chunk in zf:
            yield chunk

    return Response(
        _stream_from_thread(generate_zip_stream()),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{arc_name}.zip"',
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )


@app.route("/shared/<token>/download")
async def shared_file_download(token):
    """
    Public, unauthenticated file/zip stream for a share token. Reached only
    by clicking Download on the /shared/<token> landing page — see the
    docstring there for why this is split out. Re-checks the same
    passkey/approval gate the landing page enforced, since a visitor could
    otherwise skip straight to this URL.
    """
    import time

    _t0 = time.time()
    print(f"[shared_dl {token}] request received")

    share = _get_live_share(token)
    if not share:
        abort(404)
    print(f"[shared_dl {token}] +{time.time()-_t0:.3f}s got share row")

    mode = share["security_mode"]
    granted, access_token = _shared_access_granted(token, share)
    if not granted:
        return redirect(url_for("shared_download", token=token))

    file_path = share["file_path"]
    if not storage.is_safe_path(file_path):
        abort(404)

    full_path = os.path.join(ROOT_DIR, file_path)
    if not os.path.exists(full_path):
        abort(404)
    print(f"[shared_dl {token}] +{time.time()-_t0:.3f}s confirmed file exists")

    db.record_share_download(token)
    if mode == "approval" and access_token:
        db.record_access_request_download(access_token)
    print(f"[shared_dl {token}] +{time.time()-_t0:.3f}s recorded download count")

    if os.path.isfile(full_path):
        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)
        print(
            f"[shared_dl {token}] +{time.time()-_t0:.3f}s calling send_from_directory"
        )
        resp = await send_from_directory(
            directory,
            filename,
            as_attachment=True,
            attachment_filename=share["item_name"],
        )
        print(
            f"[shared_dl {token}] +{time.time()-_t0:.3f}s send_from_directory returned"
        )
        return resp

    # Shared folder — stream it as a ZIP, same approach as bulk-download.
    return _stream_folder_zip(full_path, share["item_name"])


@app.route("/shared/<token>/browse", defaults={"subpath": ""})
@app.route("/shared/<token>/browse/<path:subpath>")
async def shared_browse(token, subpath):
    """List the contents of a folder inside a shared folder (JSON), for the
    in-page browser on the landing page. subpath is relative to the share's
    own root, e.g. browsing into a nested folder inside what was shared.

    Re-checks the passkey/approval gate on every call — browsing is not a
    side door around the gate the landing page enforces — and confines
    subpath to the share's own subtree via _resolve_shared_subpath, so a
    visitor can't walk sideways to anything else under ROOT_DIR.
    """
    share = _get_live_share(token)
    if not share:
        return jsonify({"error": "Not available"}), 404

    granted, _ = _shared_access_granted(token, share)
    if not granted:
        return jsonify({"error": "Locked"}), 403

    rel_path, full_path = _resolve_shared_subpath(share, subpath)
    if rel_path is None or not os.path.isdir(full_path):
        return jsonify({"error": "Not found"}), 404

    items = await asyncio.to_thread(storage.list_dir, rel_path)
    resp = jsonify({"success": True, "items": items, "subpath": subpath})
    # Same no-store pattern as the rest of the app — this listing can reveal
    # filenames inside an approval-gated share, so it shouldn't be cached by
    # a shared/public browser profile any more than the download itself is.
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/shared/<token>/download-item/<path:subpath>")
async def shared_download_item(token, subpath):
    """Download a single file, or a single subfolder (as a ZIP), from
    inside a browsed shared folder. Same gate + subtree confinement as
    shared_browse. Counts as one use against an approval grant's
    downloads_remaining, exactly like the top-level share download —
    browsing into a folder and grabbing files piecemeal isn't a way around
    the download limit.
    """
    share = _get_live_share(token)
    if not share:
        abort(404)

    granted, access_token = _shared_access_granted(token, share)
    if not granted:
        return redirect(url_for("shared_download", token=token))

    rel_path, full_path = _resolve_shared_subpath(share, subpath)
    if rel_path is None:
        abort(404)

    db.record_share_download(token)
    if share["security_mode"] == "approval" and access_token:
        db.record_access_request_download(access_token)

    if os.path.isfile(full_path):
        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)
        return await send_from_directory(
            directory, filename, as_attachment=True, attachment_filename=filename
        )

    item_name = os.path.basename(full_path.rstrip("/\\"))
    return _stream_folder_zip(full_path, item_name)


@app.route("/shared/<token>/zip", methods=["POST"])
@csrf.exempt
# Anonymous visitor, no session — identical rationale to shared_verify_passkey
# and shared_request_access above: CSRFProtect(app) covers every unsafe-verb
# route by default, and there's no authenticated session here for a forged
# cross-site request to piggyback on in the first place.
async def shared_zip_selected(token):
    """Zip up a visitor's multi-selected files/subfolders from inside a
    shared folder into one download. Each selected item counts as one use
    against an approval grant's downloads_remaining — checked up front
    against the *whole* selection so a batch either fully fits inside what's
    left or is rejected outright, never partially spent.
    """
    share = _get_live_share(token)
    if not share:
        return jsonify({"error": "Not available"}), 404

    granted, access_token = _shared_access_granted(token, share)
    if not granted:
        return jsonify({"error": "Locked"}), 403

    data = await request.get_json(silent=True) or {}
    subpaths = data.get("paths") or []
    if not subpaths or not isinstance(subpaths, list):
        return jsonify({"error": "No paths provided"}), 400
    if len(subpaths) > 200:
        return jsonify({"error": "Too many items selected"}), 400

    resolved = []
    for sp in subpaths:
        rel_path, full_path = _resolve_shared_subpath(share, sp)
        if rel_path is None:
            return jsonify({"error": f"Invalid selection: {sp}"}), 400
        resolved.append(full_path)

    if share["security_mode"] == "approval" and access_token:
        req = db.get_access_request_by_access_token(access_token)
        remaining = req["max_downloads"] - req["downloads_used"]
        if len(resolved) > remaining:
            return (
                jsonify(
                    {
                        "error": f"Only {remaining} download(s) remaining for this "
                        f"share, but {len(resolved)} item(s) were selected"
                    }
                ),
                403,
            )

    db.record_share_download(token)
    if share["security_mode"] == "approval" and access_token:
        for _ in resolved:
            db.record_access_request_download(access_token)

    zip_filename = f"{share['item_name']}_selected.zip"

    def generate_zip_stream():
        zf = zipstream.ZipFile(
            mode="w", compression=zipstream.ZIP_DEFLATED, allowZip64=True
        )
        for item_full_path in resolved:
            try:
                if os.path.isfile(item_full_path):
                    zf.write(item_full_path, arcname=os.path.basename(item_full_path))
                elif os.path.isdir(item_full_path):
                    base = os.path.basename(item_full_path.rstrip("/\\"))
                    for root, dirs, files in os.walk(item_full_path):
                        rel = os.path.relpath(root, item_full_path)
                        arc_root = (
                            base
                            if rel == "."
                            else os.path.join(base, rel).replace("\\", "/")
                        )
                        for file in files:
                            try:
                                fp = os.path.join(root, file)
                                zf.write(
                                    fp,
                                    arcname=os.path.join(arc_root, file).replace(
                                        "\\", "/"
                                    ),
                                )
                            except (PermissionError, OSError) as e:
                                logging.warning(f"Shared multi-zip: skipped {fp}: {e}")
                                continue
                        if not files and not dirs:
                            zf.writestr(arc_root + "/", "")
            except (PermissionError, OSError) as e:
                logging.warning(f"Shared multi-zip: skipped {item_full_path}: {e}")
                continue
        for chunk in zf:
            yield chunk

    return Response(
        _stream_from_thread(generate_zip_stream()),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"',
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )


@app.route("/admin/shares/count", methods=["GET"])
@login_required
async def admin_shares_count():
    """How many share links are currently active — shown before the revoke-all confirmation."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403
    count = len(_prune_expired_shares(db.list_active_shares()))
    return jsonify({"count": count})


@app.route("/admin/shares", methods=["GET"])
@login_required
async def admin_shares_list():
    """Every currently-active share, for the Manage Shared → Active Shares tab."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403
    shares = _prune_expired_shares(db.list_active_shares())
    for s in shares:
        s["share_url"] = f"{request.host_url.rstrip('/')}/shared/{s['token']}"
        s["has_passkey"] = bool(s.pop("passkey_hash", None))
    return jsonify({"shares": shares})


@app.route("/admin/shares/requests", methods=["GET"])
@login_required
async def admin_shares_pending_requests():
    """Pending access requests across every approval-gated share, for the
    Manage Shared → Pending Requests tab."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403
    requests = db.list_pending_requests()
    return jsonify({"requests": requests})


@app.route("/admin/shares/requests/stream", methods=["GET"])
@login_required
async def admin_shares_requests_stream():
    """Server-Sent Events stream that pushes the pending-request count the
    instant a request is created, approved, or denied — this is what powers
    the live badge on the Manage Shared button, replacing what used to be a
    30s poll (plus a refresh-on-tab-focus fallback for background-tab
    throttling). Same Waitress-safe streaming approach as
    /api/storage_stats_stream."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403
    return await share_events_sse()


@app.route("/admin/shares/requests/<int:request_id>/approve", methods=["POST"])
@login_required
async def admin_approve_share_request(request_id):
    """Approve a pending access request, granting it a set number of downloads
    before it locks again."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    data = await request.get_json(silent=True) or {}
    try:
        max_downloads = int(data.get("max_downloads", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "max_downloads must be a number"}), 400
    if max_downloads < 1:
        return jsonify({"error": "max_downloads must be at least 1"}), 400

    ok = db.approve_access_request(request_id, current_user(), max_downloads)
    if not ok:
        return jsonify({"error": "Request not found or already decided"}), 404
    logging.info(
        f"Access request {request_id} approved by {current_user()} (max_downloads={max_downloads})"
    )
    try:
        trigger_share_event(len(db.list_pending_requests()), "approved")
    except Exception as e:
        logging.warning(f"Failed to broadcast share-request event: {e}")
    return jsonify({"success": True})


@app.route("/admin/shares/requests/<int:request_id>/deny", methods=["POST"])
@login_required
async def admin_deny_share_request(request_id):
    """Deny a pending access request."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    ok = db.deny_access_request(request_id, current_user())
    if not ok:
        return jsonify({"error": "Request not found or already decided"}), 404
    logging.info(f"Access request {request_id} denied by {current_user()}")
    try:
        trigger_share_event(len(db.list_pending_requests()), "denied")
    except Exception as e:
        logging.warning(f"Failed to broadcast share-request event: {e}")
    return jsonify({"success": True})


@app.route("/admin/revoke_all_shares/code", methods=["POST"])
@login_required
async def admin_revoke_all_shares_code():
    """
    Issue a fresh, random 10-digit confirmation code for the 'revoke all
    shares' action. A new code is minted every time this is called — the
    person must type back exactly the code shown for THIS attempt, so a
    remembered/scripted code from a previous attempt won't work.
    """
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    session_id = session.get("session_id") or str(uuid.uuid4())
    session["session_id"] = session_id
    nonce, code = _issue_revoke_all_code(session_id)
    return jsonify({"nonce": nonce, "code": code, "expires_in": _REVOKE_CODE_TTL})


@app.route("/admin/revoke_all_shares", methods=["POST"])
@login_required
async def admin_revoke_all_shares():
    """Revoke every active share link. Requires the matching code from
    /admin/revoke_all_shares/code, typed back exactly, single-use."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403

    data = await request.get_json(silent=True) or {}
    nonce = data.get("nonce", "")
    typed_code = data.get("code", "")
    session_id = session.get("session_id", "")

    if not nonce or not typed_code:
        return jsonify({"error": "Confirmation code is required"}), 400

    if not _check_revoke_all_code(session_id, nonce, typed_code):
        return (
            jsonify(
                {
                    "error": "Confirmation code is incorrect or expired — request a new one"
                }
            ),
            400,
        )

    count = db.revoke_all_shares()
    logging.info(f"ALL share links revoked by {current_user()} ({count} link(s))")
    return jsonify({"success": True, "revoked_count": count})
