"""
routes/login.py - login, logout, session check and the CSRF token endpoint: /login, /logout,
/check_session, /csrf-token (Phase 10 of the split, CLAUDE.md 4.78).

5.48: no-refresh login and logout. `POST /login` and `POST /logout` also answer JSON (the
front end asks for it with `Accept: application/json` or `X-Requested-With: XMLHttpRequest`);
the classic form flow (302 / rendered page with a flash message) is unchanged and stays the
fallback for a browser without JavaScript. `GET /login` called by the page shell
(`static/js/shell.js`, header `X-Requested-With: XMLHttpRequest`) is the same HTML without
the `Clear-Site-Data` header, which would otherwise reload the very page that is fetching it.
No other header is touched: every security header still comes from `after_request`.

Moved from app.py in Phase 10. Since 4.89 the Clear-Site-Data header on /login and /logout is
"executionContexts" only (see CLAUDE.md, part 39). Gets shared objects via `from core import ...`;
imports no other route module.
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
    request_is_logged_in,
    get_role,
    revoke_current_session,
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
    if not request_is_logged_in():
        return jsonify({"error": "Session expired"}), 401
    return jsonify({"status": "ok"}), 200


def _wants_json() -> bool:
    """True when the caller asked for the JSON flavour of /login or /logout."""
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )


def _is_fragment_fetch() -> bool:
    """True for the page shell's in-page fetch of a view (static/js/shell.js)."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _no_store(response):
    response.headers.update(
        {
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )
    return response


async def _credentials() -> tuple[str, str]:
    """Username (trimmed) and password (exact) from a JSON body or a form."""
    if request.is_json:
        data = await request.get_json(silent=True)
        if isinstance(data, dict):
            username = data.get("username", "")
            password = data.get("password", "")
            if isinstance(username, str) and isinstance(password, str):
                return username.strip(), password
            return "", ""
    form = await request.form
    return form.get("username", "").strip(), form.get("password", "")


def _login_failure_json(message: str, status: int, **extra):
    body = {"success": False, "error": message, "message": message}
    body.update(extra)
    response = jsonify(body)
    response.status_code = status
    if status == 429:
        response.headers["Retry-After"] = str(extra.get("retry_after", 0))
    return _no_store(response)


@app.route("/login", methods=["GET", "POST"])
async def login():
    wants_json = _wants_json()

    # If user is already logged in, redirect to index
    if session.get("logged_in"):
        if wants_json and request.method == "POST":
            # Same rule as the classic flow: a POST never switches a logged-in session to
            # another account. The caller learns who is logged in and goes on to the app.
            return _no_store(
                jsonify(
                    {
                        "success": True,
                        "already_logged_in": True,
                        "username": session.get("username"),
                        "role": session.get("role"),
                        "redirect": url_for("index"),
                    }
                )
            )
        return redirect(url_for("index"))

    if request.method == "POST":
        # Check brute-force lockout before touching DB
        if rate_limiter.is_blocked():
            remaining = rate_limiter.remaining_lockout()
            message = f"Too many failed attempts. Try again in {remaining} seconds."
            if wants_json:
                return _login_failure_json(message, 429, retry_after=remaining)
            await flash(message)
            return await render_template("login.html"), 429

        username, password = await _credentials()

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

            if wants_json:
                return _no_store(
                    jsonify(
                        {
                            "success": True,
                            "username": session.get("username"),
                            "role": session.get("role"),
                            "redirect": url_for("index"),
                            # session.clear() above dropped the old token: hand out the new
                            # one so the page does not have to ask for it.
                            "csrf_token": generate_csrf(),
                        }
                    )
                )
            return redirect(url_for("index"))
        else:
            rate_limiter.record_failure()
            left = rate_limiter.attempts_remaining()
            if left > 0:
                message = f"Invalid username or password. {left} attempt(s) remaining."
            else:
                message = f"Too many failed attempts. Try again in {RateLimiter.LOCKOUT} seconds."
            if wants_json:
                if left > 0:
                    return _login_failure_json(message, 401, attempts_remaining=left)
                return _login_failure_json(
                    message, 429, retry_after=rate_limiter.remaining_lockout()
                )
            await flash(message)
            return await render_template("login.html"), 401

    # Render login page with no-cache headers
    response = await make_response(await render_template("login.html"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    # Clear-Site-Data on GET /login: "executionContexts" only, deliberately.
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
    #   - NOT "storage" / "*" either (4.89): any of cache / storage /
    #     cookies / "*" made the browser do synchronous clearing work.
    #   - "executionContexts": cheap, no cookie involved, no collision — kept
    #     to satisfy security-scanner checks that want more than zero
    #     directives present on this header.
    # /logout below is the state-ending action; see the comment there for
    # what replaced the old "cache", "cookies", "storage" header.
    #
    # 5.48: NOT on the page shell's in-page fetch of this view (X-Requested-With:
    # XMLHttpRequest). The header makes the browser reload the page that receives it, which
    # would undo the no-refresh logout it is part of. A scanner or a browser navigation
    # never sends that request header, so the header stays exactly where it was.
    if _request_is_secure() and not _is_fragment_fetch():
        response.headers["Clear-Site-Data"] = '"executionContexts"'
    return response


async def _end_session() -> None:
    """Everything a logout does on the server, shared by GET and POST /logout."""
    # Clean up any upload chunks
    session_id = session.get("session_id")
    if session_id:
        # An rmtree per tracked upload: worker thread since 5.44. session / request
        # stay on the loop (the value is passed in as a plain string).
        await asyncio.to_thread(chunk_tracker.cleanup_session_chunks, session_id)

    # End the session on the SERVER too (5.17): a copy of the cookie taken before this
    # logout is refused from now on. Must run before session.clear(); never raises.
    revoke_current_session()

    # Clear the session completely
    session.clear()


@app.route("/logout", methods=["GET", "POST"])
async def logout():
    # POST (5.48, CSRF-protected like every state-changing route): the in-page logout of the
    # page shell. JSON answer, no redirect, no Clear-Site-Data (see /login above); the page
    # tears itself down in JavaScript. GET stays as the classic, fully-clearing logout.
    in_page = request.method == "POST" and _wants_json()
    try:
        await _end_session()

        if in_page:
            response = jsonify({"success": True, "redirect": url_for("login")})
            response.delete_cookie("cloudinator_session")
            response.delete_cookie("session_check")
            return _no_store(response)

        # Create response with session-clearing headers
        response = await make_response(redirect(url_for("login", logged_out="1")))
        response.delete_cookie("cloudinator_session")
        response.delete_cookie("session_check")

        # Add cache-control headers to prevent caching
        _no_store(response)

        # Clear-Site-Data: "executionContexts" only (4.89). The old
        # '"cache", "cookies", "storage"' made the browser do synchronous
        # clearing work: a 3-15 s logout; "executionContexts" takes 0.1-0.5 s.
        # What replaced it: cache policy = the Cache-Control no-store
        # headers above (middleware sets the same on every authenticated
        # response), session/cookies = session.clear() + delete_cookie()
        # above. NOT cleared any more: localStorage / sessionStorage /
        # IndexedDB. Browsers only honor this header on secure origins
        # (HTTPS), so it is set only when the request came in over HTTPS.
        if _request_is_secure():
            response.headers["Clear-Site-Data"] = '"executionContexts"'
        return response

    except Exception as e:
        logging.error(f"Logout error: {e}", exc_info=True)
        # Still try to end and clear the session even if other operations fail
        revoke_current_session()
        session.clear()
        if in_page:
            return (
                _no_store(jsonify({"success": False, "redirect": url_for("login")})),
                500,
            )
        return redirect(url_for("login", logged_out="1"))
