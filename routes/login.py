"""
routes/login.py - login, logout, session check and the CSRF token endpoint: /login, /logout,
/check_session, /csrf-token (Phase 10 of the split, CLAUDE.md 4.78).

Moved verbatim from app.py. Gets shared objects via `from core import ...`; imports no other route
module.
"""

from core import (
    RateLimiter,
    _request_is_secure,
    app,
    chunk_tracker,
    generate_csrf,
    rate_limiter,
)

from quart import (
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
import asyncio
import time
import logging
import uuid
from auth import (
    check_login,
    login_user,
    is_logged_in,
    get_role,
)


@app.route("/csrf-token")
async def get_csrf_token():
    """Return the CSRF token for the CURRENT session as JSON.

    Any page/tab left open across a login/account-switch (session.clear()
    in login()) is holding a token baked in at render time that no longer
    matches the new session, so its next POST/PUT/PATCH/DELETE 400s with
    "The CSRF token is missing/incorrect." Rather than trusting a token
    embedded at page load, the frontend should call this right before a
    state-changing fetch (or on catching a 400 CSRF error) and use the
    fresh value instead of reloading the whole page.
    No @login_required — an anonymous session still needs a valid token
    to submit the /login form itself.
    """
    return jsonify({"csrf_token": generate_csrf()})

    # Session lifetime controlled by PERMANENT_SESSION_LIFETIME (86400s = 24h)
    # and refreshed on every request via SESSION_REFRESH_EACH_REQUEST=True.


@app.route("/check_session")
async def check_session():
    if not is_logged_in():
        return jsonify({"error": "Session expired"}), 401
    return jsonify({"status": "ok"}), 200


@app.route("/login", methods=["GET", "POST"])
async def login():
    # If user is already logged in, redirect to index
    if session.get("logged_in"):
        return redirect(url_for("index"))

    if request.method == "POST":
        # Check brute-force lockout before touching DB
        if rate_limiter.is_blocked():
            remaining = rate_limiter.remaining_lockout()
            await flash(f"Too many failed attempts. Try again in {remaining} seconds.")
            return await render_template("login.html"), 429

        username = (await request.form).get("username", "").strip()
        password = (await request.form).get("password", "")

        if await asyncio.to_thread(check_login, username, password):
            rate_limiter.record_success()
            # Set up session data
            session.clear()
            session.permanent = True
            login_user(username)
            session["role"] = get_role(username)
            session["session_id"] = str(uuid.uuid4())
            session["logged_in"] = True
            session["login_time"] = int(time.time())
            session.modified = True

            return redirect(url_for("index"))
        else:
            rate_limiter.record_failure()
            left = rate_limiter.attempts_remaining()
            if left > 0:
                await flash(
                    f"Invalid username or password. {left} attempt(s) remaining."
                )
            else:
                await flash(
                    f"Too many failed attempts. Try again in {RateLimiter.LOCKOUT} seconds."
                )
            return await render_template("login.html"), 401

    # Render login page with no-cache headers
    response = await make_response(await render_template("login.html"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    # Clear-Site-Data on GET /login: "storage" only, deliberately.
    #   - NOT "cache" (was set until 2026-09-14): forces a synchronous full
    #     disk-cache wipe on every anonymous page view — the real suspect
    #     for the intermittent ~45s mobile-Chrome hang (worse on
    #     older/slower-storage phones, invisible to server-side
    #     request-timing logs since the wipe happens client-side after the
    #     response is already sent). No security benefit on a pre-auth page
    #     either way, so no reason to bring it back.
    #   - NOT "cookies": generate_csrf() (see CSRFProtect above) sets
    #     session["csrf_token"] on first render, which makes Quart's
    #     session interface emit Set-Cookie on THIS SAME response — racing
    #     against Clear-Site-Data:"cookies" on the same response can wipe
    #     the just-issued CSRF cookie before the form is even shown,
    #     breaking the subsequent login POST for every fresh visitor.
    #   - "storage" (localStorage/IndexedDB): cheap, no cookie involved, no
    #     collision — kept to satisfy security-scanner checks that want
    #     more than zero directives present on this header.
    # /logout below is the actual state-ending action and keeps the full
    # "cache", "cookies", "storage" — no cookie race there since logout
    # explicitly deletes cookies via response.delete_cookie(), not a
    # session-modification-triggered Set-Cookie.
    if _request_is_secure():
        response.headers["Clear-Site-Data"] = '"storage"'
    return response


@app.route("/logout")
async def logout():
    try:
        # Clean up any upload chunks
        session_id = session.get("session_id")
        if session_id:
            chunk_tracker.cleanup_session_chunks(session_id)

        # Clear the session completely
        session.clear()

        # Create response with session-clearing headers
        response = await make_response(redirect(url_for("login", logged_out="1")))
        response.delete_cookie("cloudinator_session")
        response.delete_cookie("session_check")

        # Add cache-control headers to prevent caching
        response.headers.update(
            {
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            }
        )

        # Tell the browser to wipe cookies/cache/storage for this origin now
        # that the session is gone, rather than relying solely on cookie
        # expiry — helps on shared/public machines. Browsers only honor this
        # header on secure origins (HTTPS) — sending it over plain HTTP (e.g.
        # local LAN access by IP) just produces a harmless console warning,
        # so only set it when the request actually came in over HTTPS.
        if _request_is_secure():
            response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'

        return response
    except Exception as e:
        logging.error(f"Logout error: {e}", exc_info=True)
        session.clear()  # Still try to clear session even if other operations fail
        return redirect(url_for("login", logged_out="1"))
