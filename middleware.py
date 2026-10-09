"""
middleware.py - every request/response hook, the CORS preflight route, the error
handlers and the Jinja filter.

Phase 1 of the app.py split (CLAUDE.md 4.69). Registration ORDER is the HOOK ORDER in
CLAUDE.md and must not change: before_request = _start_request_timer, CSRFProtect._protect
(csrf.init_app below), validate_session, before_request; after_request = _log_request_duration,
_apply_cors_headers, after_request (Quart runs after_request hooks in reverse).
Imports shared objects from core; never imports app.
"""

from core import (
    SLOW_REQUEST_THRESHOLD_SECONDS,
    _INLINE_STYLE_ELEMENT_HASHES,
    _INLINE_STYLE_HASHES,
    _cors_origin_allowed,
    _request_is_secure,
    _request_via_trusted_tls,
    _unauthenticated_response,
    app,
    assembly_queue,
    chunk_tracker,
    cleanup_stale_chunks_on_request,
    csrf,
    get_client_ip,
    request_logger,
)
from quart import (
    g,
    render_template,
    request,
    session,
    Response,
    abort,
)
import os
import threading
import time
import logging
import uuid
from datetime import datetime
from config import ROOT_DIR
from auth import is_logged_in, get_role
import storage
import secrets as _secrets


@app.before_request
async def _start_request_timer():
    g.request_start_time = time.monotonic()


@app.after_request
async def _log_request_duration(response):
    start = g.get("request_start_time")
    if start is not None:
        duration = time.monotonic() - start
        is_slow = duration > SLOW_REQUEST_THRESHOLD_SECONDS
        # Client IP is included on every line (not just login-lockout
        # events) so an attack shows up in context — same IP hitting many
        # paths in a short window, correlated against everything else in
        # the daily log. See get_client_ip()'s docstring for the
        # X-Forwarded-For spoofing caveat if this server sits directly on
        # the internet with no reverse proxy in front of it.
        client_ip = get_client_ip()

        # Also surface the raw X-Forwarded-For value when it disagrees
        # with the resolved (trusted) IP — this only happens if a client
        # sent Cloudflare a pre-populated/forged X-Forwarded-For header,
        # since Cloudflare appends the real IP rather than replacing it.
        # A mismatch here isn't noise to filter out — it's evidence
        # someone was actively trying to spoof their IP, which is worth
        # keeping visible rather than silently discarding.
        raw_xff = request.headers.get("X-Forwarded-For", "").strip()
        xff_tag = ""
        if raw_xff and raw_xff != client_ip:
            xff_tag = f" [XFF: {raw_xff}]"

        request_logger.log(
            logging.WARNING if is_slow else logging.INFO,
            "%s%s%s %s %s took %.3fs (status %s)",
            "SLOW REQUEST: " if is_slow else "",
            client_ip,
            xff_tag,
            request.method,
            request.path,
            duration,
            response.status_code,
        )
    return response


@app.after_request
async def _apply_cors_headers(response):
    origin = request.headers.get("Origin")
    if _cors_origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        # Origin-dependent response — never let a shared cache serve one
        # origin's CORS headers back to a different origin.
        existing_vary = response.headers.get("Vary", "")
        if "Origin" not in existing_vary:
            response.headers["Vary"] = (
                f"{existing_vary}, Origin" if existing_vary else "Origin"
            )
    return response


@app.route("/<path:_cors_any_path>", methods=["OPTIONS"])
@app.route("/", methods=["OPTIONS"])
async def _cors_preflight(_cors_any_path=""):
    """Handles CORS preflight for every route. Registered before any other
    route with the same path/method combo would otherwise 405 on OPTIONS."""
    origin = request.headers.get("Origin")
    resp = Response("", status=204)
    if _cors_origin_allowed(origin):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        )
        requested_headers = request.headers.get("Access-Control-Request-Headers")
        resp.headers["Access-Control-Allow-Headers"] = requested_headers or (
            "Content-Type, X-CSRFToken, X-CSRF-Token"
        )
        resp.headers["Access-Control-Max-Age"] = "600"
    return resp


# CSRFProtect registers its own before_request (_protect). It used to be created at this point of
# app.py (`csrf = CSRFProtect(app)`), i.e. AFTER _start_request_timer and BEFORE validate_session.
csrf.init_app(app)


@app.before_request
async def validate_session():
    if "//" in request.path:
        abort(404)
    # Reject a literal '%' ONLY on the generic catch-all route ("index",
    # matching "/<path:path>") — never on file-serving routes like
    # download/view/shared_*, which legitimately need to accept filenames
    # containing '%' (confirmed: ReadMe%.txt downloads fine via
    # /download/ReadMe%25.txt for a logged-in user). The catch-all is
    # where scanner probes like "/%" and "/%25" actually land (they don't
    # match any real route), and letting those through used to fall to
    # the generic redirect-to-/login below — telling scanners "this is a
    # live endpoint" instead of a dead one. request.endpoint is already
    # resolved by routing at this point, so this check is safe here.
    if request.endpoint == "index" and "%" in request.path:
        abort(404)
    # Skip validation for login-related routes and the public share-link
    # pages/downloads — those are meant to work for anyone with the link,
    # no account required.
    if request.endpoint in [
        "login",
        "get_csrf_token",
        "static",
        "robots_txt",
        "security_txt",
        "sitemap_xml",
        "shared_download",
        "shared_file_download",
        "shared_verify_passkey",
        "shared_request_access",
        "shared_request_status",
        "shared_browse",
        "shared_download_item",
        "shared_zip_selected",
    ]:
        return

    # Check if user is logged in
    if not session.get("logged_in"):
        # Only clear if the session is carrying stale auth remnants
        # (e.g. a half-expired login). Don't clear a genuinely anonymous
        # session just because it's anonymous — it may hold nothing but a
        # freshly-issued CSRF token for a login page open in another
        # request/tab. Clearing it here deletes/regenerates that cookie,
        # which then no longer matches the token baked into the login
        # form the user is about to submit ("CSRF tokens do not match")
        # — triggered by something as innocuous as the browser's automatic
        # /favicon.ico request racing the login page load.

        if session.get("username") or session.get("server_token"):
            session.clear()

        # Only the bare site root ("/") redirects an anonymous visitor to
        # /login. Every other URL under the generic directory browser
        # ("index" endpoint, i.e. "/<path:path>") used to get the exact
        # same 301-to-/login regardless of whether that path pointed at a
        # real folder or was pure scanner noise — which is itself a
        # "this endpoint is alive" oracle (a 301 vs. a flat 404 is a
        # boolean-distinguishable response, the same class of issue as
        # the earlier '%'/'static%' findings). Deep, non-root catch-all
        # requests from an anonymous caller now just 404 instead.
        #
        # This only narrows the catch-all ("index"); every other
        # login-required route — /download/*, /view/*, /api/*, /admin/*,
        # bulk_*, upload, etc. — keeps its normal redirect-to-/login
        # behavior below, so real deep links, bookmarks, and the
        # frontend's own API calls are unaffected.
        if request.endpoint == "index" and request.path != "/":
            abort(404)

        return _unauthenticated_response()

    # Verify the account still exists in users.json.
    # Without this, a deleted account's still-valid cookie causes an infinite
    # loop: /admin/upload_status returns 403 (role=None) → JS redirects to
    # /login → /login sees logged_in=True → redirects back to / → repeat.
    username = session.get("username")
    if not username or get_role(username) is None:
        session.clear()
        return _unauthenticated_response()


# Add Jinja2 filter for timestamp formatting
@app.template_filter("timestamp_to_date")
def timestamp_to_date_filter(timestamp):
    """Convert Unix timestamp to time on first line, date on second"""
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%m/%d/%Y") + "||" + dt.strftime("%I:%M %p")
    except (ValueError, OSError):
        return "--"


@app.before_request
async def before_request():
    """Run cleanup before certain requests and handle interrupted uploads"""
    # Ensure session ID exists for logged-in users
    if is_logged_in() and "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())

    # Enhanced cleanup on page load/refresh - check for assembly jobs first
    #
    # IMPORTANT: this must stay scoped to "index" only. It used to also match
    # "upload", which is the same endpoint every chunk of a chunked upload
    # POSTs to — that meant the background cleanup_thread below (a full
    # os.listdir + per-directory timestamp-file scan over .chunks) was being
    # spawned on *every chunk*, not once per page load. For a multi-hundred-
    # chunk file that's hundreds of unbounded, un-throttled OS threads doing
    # blocking filesystem work back-to-back, all contending for the GIL
    # against the single asyncio event loop thread Hypercorn runs on (see
    # prod_server.py's sys.setswitchinterval comment for the same class of
    # issue with file_monitor's walk thread) — enough to stall the loop past
    # keep_alive_timeout and drop the upload connection mid-transfer.
    # start_enhanced_cleanup_scheduler() (every 15 min) already covers this
    # exact cleanup_old_chunks(max_age_hours=1) call on a proper interval, so
    # nothing is lost by not also doing it per-request.
    if request.endpoint == "index":
        # Check for and cleanup any stale uploads from this session
        session_id = session.get("session_id")
        if session_id:
            # This is a page load/refresh - check for abandoned uploads
            # IMPORTANT: Check for assembly jobs FIRST before cleaning up chunks
            try:
                current_uploads = chunk_tracker.active_uploads.get(session_id, set())
                if current_uploads:
                    print(
                        f"🧹 Detected {len(current_uploads)} potentially abandoned uploads on page refresh"
                    )
                    # Check if any of these uploads are actually in assembly queue
                    assembly_protected = set()
                    for file_id in current_uploads.copy():
                        # Check if this file is in assembly queue
                        if assembly_queue.get_job_status(file_id):
                            print(f"🔐 Upload {file_id} is protected by assembly queue")
                            assembly_protected.add(file_id)
                            continue

                        # Check for assembly protection marker
                        chunk_dir = os.path.join(ROOT_DIR, ".chunks", file_id)
                        assembly_marker = os.path.join(chunk_dir, ".assembling")
                        if os.path.exists(assembly_marker):
                            print(
                                f"🔐 Upload {file_id} is protected by assembly marker"
                            )
                            assembly_protected.add(file_id)
                            continue

                        # Give a grace period for genuine page refreshes during upload
                        timestamp = chunk_tracker.upload_timestamps.get(file_id)
                        if (
                            timestamp and (time.time() - timestamp) > 30
                        ):  # 30 seconds grace period
                            print(f"🧹 Cleaning up abandoned upload: {file_id}")
                            chunk_tracker.untrack_upload(session_id, file_id)
                            storage.cleanup_chunks(file_id)

                    # Keep assembly-protected uploads in tracker
                    if assembly_protected:
                        print(
                            f"🔐 Keeping {len(assembly_protected)} assembly-protected uploads in tracker"
                        )
            except Exception as e:
                print(f"❌ Error in abandoned upload cleanup: {e}")

        # Run periodic cleanup in background thread to not slow down requests
        cleanup_thread = threading.Thread(
            target=cleanup_stale_chunks_on_request, daemon=True
        )
        cleanup_thread.start()


@app.after_request
async def after_request(response):
    """Add security headers to all responses"""
    # Add cache control headers to authenticated pages
    if request.endpoint and request.endpoint not in ["static"]:
        # Check if this is an authenticated route
        if is_logged_in() or request.endpoint in [
            "index",
            "download",
            "upload",
            "admin",
        ]:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        # /login always gets no-store too, even though it's pre-auth: the
        # page embeds a per-session CSRF token, so any CDN/proxy/browser
        # cache serving back a stale copy hands out a token that no longer
        # matches the visitor's actual session — causing exactly the
        # "CSRF tokens do not match" error, not a security hole by itself,
        # but a confusing false failure for real users.
        if request.endpoint == "login":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["Vary"] = "Content-Security-Policy, User-Agent"

    # ── Security headers — applied to every response, on localhost, LAN, ──
    # and the public domain alike. These are all response headers Flask
    # controls directly, so they work no matter how the request reached us.
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers.setdefault("Referrer-Policy", "same-origin")

    # Tell every compliant search engine / AI crawler not to index or follow
    # links on ANY response, site-wide. This is defense-in-depth on top of
    # robots.txt: robots.txt only stops crawlers from ever requesting a page,
    # but a page that's already been linked/discovered elsewhere can still
    # get indexed unless the response itself says not to. Belt-and-suspenders
    # — neither one alone is followed by non-compliant/aggressive scrapers.
    response.headers["X-Robots-Tag"] = (
        "noindex, nofollow, noarchive, nosnippet, noimageindex"
    )

    # Permissions-Policy — deny browser features this app doesn't use.
    # fullscreen=(self) is kept because the video player (video.js) calls
    # requestFullscreen(); everything else here (camera, mic, geolocation,
    # USB, etc.) isn't referenced anywhere in index.js, so it's safe to lock
    # down. If you add a feature that needs one of these later, it'll be
    # silently blocked until you add it back here — check this line first
    # if some future browser API mysteriously stops working.
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
        "bluetooth=(), midi=(), magnetometer=(), gyroscope=(), "
        "accelerometer=(), fullscreen=(self)"
    )

    # index.js/index.html no longer use inline event handler attributes
    # (onclick=, onerror=, etc.) — all of them were converted to a delegated
    # addEventListener-based dispatcher (see the "data-fn" pattern at the top
    # of index.js), so 'unsafe-inline' is no longer needed in script-src.
    # style-src no longer uses 'unsafe-inline' either — see
    # _INLINE_STYLE_HASHES above for the hash-based allow-list approach and
    # its Safari caveat.
    # If you disable Cloudflare Web Analytics/RUM in the dashboard (Analytics
    # & Logs → Web Analytics), you can drop the cloudflareinsights.com entry
    # below — it's only here because Cloudflare auto-injects that beacon
    # script into proxied HTML when Web Analytics is turned on.
    # default-src 'none' — deny-by-default. Every resource type this app
    # actually loads is given its own explicit directive below, so nothing
    # falls back to default-src; anything NOT listed (workers, frames,
    # manifests, etc.) is now correctly blocked instead of silently
    # inheriting 'self' from the old default-src 'self'.
    # Per-response nonce for Cloudflare's JavaScript Detections bootstrap
    # (the __CF$cv$params/challenge-platform snippet injected into the HTML
    # at Cloudflare's edge, after this response leaves origin — part of
    # Bot Fight Mode / Super Bot Fight Mode; forced-on and non-disableable
    # on the Free plan). We can never see or hash that snippet's contents
    # since it isn't in our response body, and its contents differ per
    # request anyway. Per Cloudflare's own docs for this feature: "If your
    # CSP uses a nonce for script tags, Cloudflare will add these nonces to
    # the scripts it injects by parsing your CSP response header." So we
    # generate a fresh nonce every response and put it in script-src; the
    # edge reads this header and stamps the same nonce onto the script tag
    # it injects, before it reaches the browser. No hash, no hardcoding,
    # and it keeps working across tunnel restarts since it's regenerated
    # every single response. index.js/index.html have no inline <script>
    # of their own, so nothing else needs a matching nonce attribute.
    cf_jsd_nonce = _secrets.token_urlsafe(16)
    csp = (
        "default-src 'none'; "
        f"script-src 'self' 'nonce-{cf_jsd_nonce}' https://static.cloudflareinsights.com; "
        "script-src-attr 'none'; "
        # style-src is the fallback for browsers that don't understand
        # style-src-elem/style-src-attr (CSP3). No 'unsafe-inline' here —
        # those older browsers will load external stylesheets fine but will
        # NOT apply the inline style="..." attributes below.
        "style-src 'self'; "
        # <link rel="stylesheet"> external files (including
        # video-skin-overrides.css, loaded dynamically into a shadow
        # root by index.js) load fine under plain 'self'. On top of
        # that, the vendored video.js/media-chrome bundle injects a
        # couple of inline <style> elements of its own into its
        # shadow-DOM components — see _INLINE_STYLE_ELEMENT_HASHES
        # above for what these are and the upgrade caveat. Unlike
        # style-src-attr, element hashes don't need 'unsafe-hashes'.
        f"style-src-elem 'self' {_INLINE_STYLE_ELEMENT_HASHES}; "
        # Exact allow-list of this project's static inline style="..."
        # attribute values (see _INLINE_STYLE_HASHES above for regeneration
        # instructions and the Safari-support caveat).
        f"style-src-attr 'unsafe-hashes' {_INLINE_STYLE_HASHES}; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "object-src 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "frame-src 'none'; "
        "worker-src 'self'; "
        "manifest-src 'none'; "
        "base-uri 'self'"
    )

    # Cross-origin resource-sharing headers that are safe on both HTTP and
    # HTTPS (they don't force any protocol upgrade). COEP is set to
    # "credentialless" rather than "require-corp": the app loads a
    # cross-origin Cloudflare Insights beacon script that doesn't send a
    # Cross-Origin-Resource-Policy header, so "require-corp" would silently
    # block it; "credentialless" still isolates the page (strips credentials
    # from that cross-origin request) without breaking it.
    response.headers["Cross-Origin-Embedder-Policy"] = "credentialless"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["X-DNS-Prefetch-Control"] = "off"

    # Document-Policy: disable legacy document.write() and synchronous XHR.
    # Neither pattern is used anywhere in this app's JS (everything here is
    # fetch()-based), so this has no functional effect other than blocking
    # those calls if they're ever introduced (e.g. by a future third-party
    # embed script). A blocked call just becomes a silent no-op — it doesn't
    # break the rest of the page.
    response.headers["Document-Policy"] = "document-write=?0, sync-xhr=?0"

    # X-XSS-Protection is deprecated (removed from Chrome, never in Firefox)
    # and superseded by CSP — but explicitly setting it to "0" is still
    # recommended best practice: it tells any browser that still has the
    # legacy heuristic XSS auditor to never enable it, closing a known
    # side-channel some old browsers had where the auditor's own behavior
    # could leak page content. This is a no-op on modern browsers.
    response.headers["X-XSS-Protection"] = "0"

    # Integrity-Policy, REPORT-ONLY for now. This does not block anything —
    # it only reports (via a ReportingObserver in-page, or a Reporting-
    # Endpoints server if configured) which <script src="..."> tags are
    # missing a Subresource Integrity `integrity` attribute.
    #
    # login.js and 404.js already have integrity attributes (added in
    # login.html / 404.html). video.js, index.js, and viewer.mjs do NOT yet
    # — until hashes are added for those three, switching this to the
    # enforcing "Integrity-Policy" header (not report-only) would block them
    # from loading and break the main dashboard, video playback, and file
    # viewer. Do not flip this to enforcing mode until all first-party
    # <script src> tags across index.html/viewer.html have integrity
    # attributes computed from the actual deployed file bytes.
    #
    # Note: Cloudflare's auto-injected Web Analytics beacon script (see the
    # script-src CSP comment above) is inserted by Cloudflare's edge after
    # this response leaves the origin, so it can never carry an integrity
    # attribute we control — enforcing this policy will always block that
    # beacon specifically (harmless: it only loses the analytics ping).
    response.headers["Integrity-Policy-Report-Only"] = "blocked-destinations=(script)"

    # These directives/headers only make sense — and are only spec-compliant
    # — once a browser has actually reached us over HTTPS:
    #   • "upgrade-insecure-requests" tells the browser to rewrite every
    #     request (including page navigation) to https://. Sending this on
    #     a plain-HTTP LAN/localhost connection is actively harmful: the
    #     browser tries to re-fetch everything as https:// on a port with
    #     no TLS listener and every asset times out — this is exactly what
    #     broke direct LAN access. It must only go out on a connection
    #     that's already HTTPS.
    #   • Cross-Origin-Opener-Policy is ignored by browsers on insecure
    #     origins anyway (console warning, harmless), but there's no reason
    #     to send it there.
    #   • Origin-Agent-Cluster likewise only makes sense once; toggling it
    #     on/off across HTTP vs HTTPS visits to the same origin is what
    #     produced the "previously placed in a site-keyed agent cluster"
    #     warning — only ever send it on HTTPS so it's consistent.
    # Uses _request_is_secure() so this also fires correctly behind the
    # Cloudflare tunnel, which terminates TLS and talks to Flask over plain
    # HTTP — request.is_secure alone is always False in that setup.
    if _request_is_secure():
        csp += "; upgrade-insecure-requests"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Origin-Agent-Cluster"] = "?1"

    response.headers["Content-Security-Policy"] = csp

    # HSTS must ONLY go to clients who reached us through a real, publicly
    # trusted CA cert (the Cloudflare tunnel) — never to anyone hitting
    # Hypercorn's own self-signed listener directly, LAN/WiFi included.
    # Post-migration, request.is_secure (what _request_is_secure() checks
    # first) is True for direct LAN/WiFi connections too, since Hypercorn
    # now terminates TLS with the self-signed cert for everyone, not just
    # tunnel traffic like under the old Waitress setup. Sending HSTS to a
    # device still running on an unimported self-signed cert removes that
    # browser's certificate-warning bypass for a full year (spec'd browser
    # behavior, "no user recourse") — it doesn't just warn, it can lock the
    # device out entirely the next time it needs a fresh TLS handshake
    # (e.g. right after logout's Clear-Site-Data wipes the connection/cache
    # state). See _request_via_trusted_tls()'s docstring for the full story.
    #
    # TEMPORARY (started 2026-09-10) — HSTS CLEANUP IN PROGRESS.
    # _request_via_trusted_tls() was found to fire on requests that were
    # NOT actually terminated by Cloudflare's trusted cert (it only checks
    # forwarded headers, not the real cert), which pinned
    # "max-age=31536000; includeSubDomains" onto devices that later hit
    # Hypercorn's self-signed cert directly under the same public hostname
    # — a year-long HSTS lockout with no bypass, only fixable by the user
    # clearing all site data. Sending max-age=0 here tells any browser that
    # still has that bad entry to delete it the moment it makes one
    # successful trusted-path request (mobile data / anywhere Cloudflare's
    # real cert is actually served). This does NOT disable HSTS protection
    # going forward — Cloudflare's edge HSTS setting (SSL/TLS > Edge
    # Certificates) is the permanent replacement for this origin-side
    # header and should be doing the real enforcement instead.
    #
    # REVERT PLAN: once the public hostname can no longer resolve to the
    # self-signed origin under any network path (see hostname-separation
    # fix — public domain reserved for Cloudflare only; use the Tailscale
    # *.ts.net hostname for direct/LAN access instead), and Cloudflare's
    # edge HSTS has been verified on for a few days, remove this whole
    # `if _request_via_trusted_tls(): ...` block entirely rather than
    # restoring the max-age=31536000 value — origin-side HSTS shouldn't
    # come back at all once the edge is handling it.
    if _request_via_trusted_tls():
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    return response


@app.errorhandler(413)
async def too_large(e):
    return "File too large", 413


@app.errorhandler(404)
async def not_found(e):
    return await render_template("404.html"), 404


@app.errorhandler(500)
async def internal_error(e):
    return "Internal server error", 500
