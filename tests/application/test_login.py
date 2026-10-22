"""
Login, CSRF, brute-force lockout and session lifecycle of the REAL application, started from a
scratch copy (see tests/conftest.py). Every test uses its own client and therefore its own fake
client IP (CF-Connecting-IP), so the in-memory login rate limiter never leaks between tests.

Test accounts: qa_writer (readwrite) and qa_reader (readonly), created in the scratch database.
"""

import re

import pytest

pytestmark = pytest.mark.application

RW, RO = "qa_writer", "qa_reader"
RW_PASSWORD = "QaWriter-Pass-1!"
JSON_HEADERS = {"Accept": "application/json"}  # what the front end sends for API calls


@pytest.fixture
def server(scratch_server):
    return scratch_server


def _cookie(client, name="cloudinator_session"):
    return next((c.value for c in client.jar if c.name == name), None)


def _flash(reply):
    m = re.search(r'id="flashText">(.*?)</span>', reply.text, re.S)
    return m.group(1).strip() if m else ""


def _wrong(client, user=RW):
    return client.login(user, "definitely-wrong-password")


# ---------------------------------------------------------------------------- login page
def test_login_page_has_the_form_and_a_csrf_field(server):
    client = server.client()
    page = client.get("/login")
    assert page.status == 200
    assert 'name="username"' in page.text and 'name="password"' in page.text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token and len(token.group(1)) >= 32
    # the hidden field and /csrf-token describe the same session token
    assert client.csrf_token() == token.group(1)


def test_login_page_is_not_cacheable(server):
    page = server.client().get("/login")
    assert "no-store" in page.header("Cache-Control")
    assert page.header("Pragma") == "no-cache"


def test_login_page_security_headers(server):
    page = server.client().get("/login")
    assert page.header("X-Frame-Options") == "DENY"
    assert page.header("X-Content-Type-Options") == "nosniff"
    assert page.header("Content-Security-Policy")
    # plain http: no HSTS, and Clear-Site-Data is only sent on secure requests
    assert page.header("Strict-Transport-Security") == ""
    assert page.header("Clear-Site-Data") == ""


def test_clear_site_data_is_execution_contexts_only_over_https(server):
    page = server.client().get("/login", headers={"X-Forwarded-Proto": "https"})
    assert page.header("Clear-Site-Data") == '"executionContexts"'


def test_session_cookie_flags(server):
    plain = server.client().get("/login")
    cookie = next(c for c in plain.set_cookies if c.startswith("cloudinator_session="))
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "Secure" not in cookie  # plain http: a Secure cookie would never come back
    behind_tls = server.client().get("/login", headers={"X-Forwarded-Proto": "https"})
    cookie = next(
        c for c in behind_tls.set_cookies if c.startswith("cloudinator_session=")
    )
    assert "Secure" in cookie


# ---------------------------------------------------------------------------- CSRF
def test_csrf_token_is_stable_per_session_and_differs_between_sessions(server):
    a, b = server.client(), server.client()
    first = a.csrf_token()
    assert len(first) >= 32 and a.csrf_token() == first
    assert b.csrf_token() != first


def test_login_without_a_csrf_token_is_refused(server):
    client = server.client()
    reply = client.post_form("/login", {"username": RW, "password": RW_PASSWORD})
    assert reply.status == 400
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401


def test_login_with_a_wrong_csrf_token_is_refused(server):
    client = server.client()
    client.csrf_token()
    reply = client.login(RW, RW_PASSWORD, csrf_token="not-the-token")
    assert reply.status == 400
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401


def test_csrf_token_of_another_session_is_refused(server):
    victim_token = server.client().csrf_token()
    attacker = server.client()
    attacker.csrf_token()
    assert attacker.login(RW, RW_PASSWORD, csrf_token=victim_token).status == 400


# ---------------------------------------------------------------------------- logging in
@pytest.mark.parametrize("user,role", [(RW, "readwrite"), (RO, "readonly")])
def test_valid_login_starts_a_session_with_the_right_role(server, user, role):
    client = server.client()
    reply = client.login(user, server.users[user][0])
    assert reply.status == 302
    assert reply.header("Location") in ("/", server.base_url + "/")
    assert client.get("/check_session", headers=JSON_HEADERS).json() == {"status": "ok"}
    assert client.get("/").status == 200
    listing = client.get("/api/files/", headers=JSON_HEADERS)
    assert listing.status == 200 and listing.json()["role"] == role


def test_login_issues_a_new_session_and_csrf_token(server):
    client = server.client()
    before_cookie, before_token = None, client.csrf_token()
    before_cookie = _cookie(client)
    assert client.login(RW, RW_PASSWORD, csrf_token=before_token).status == 302
    assert _cookie(client) != before_cookie
    assert client.csrf_token() != before_token


def test_wrong_password_is_refused_without_a_session(server):
    client = server.client()
    reply = _wrong(client)
    assert reply.status == 401
    assert "Invalid username or password" in _flash(reply)
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401


def test_unknown_user_and_wrong_password_look_identical(server):
    known = _flash(_wrong(server.client(), RW))
    unknown = _flash(_wrong(server.client(), "no_such_user_at_all"))
    assert known == unknown == "Invalid username or password. 4 attempt(s) remaining."


def test_empty_credentials_are_refused(server):
    reply = server.client().login("", "")
    assert reply.status == 401


def test_username_is_trimmed_but_password_is_exact(server):
    padded_user = server.client().login(f"  {RW}  ", RW_PASSWORD)
    assert padded_user.status == 302
    padded_password = server.client().login(RW, RW_PASSWORD + " ")
    assert padded_password.status == 401


def test_logged_in_visitor_is_sent_away_from_the_login_page(server):
    client = server.login_as(RW)
    reply = client.get("/login")
    assert reply.status == 302 and reply.header("Location").endswith("/")


def test_login_post_cannot_switch_a_logged_in_session_to_another_account(server):
    client = server.login_as(RO)
    token = client.csrf_token()
    reply = client.login(RW, RW_PASSWORD, csrf_token=token)
    assert reply.status == 302
    assert client.get("/api/files/", headers=JSON_HEADERS).json()["role"] == "readonly"


# ---------------------------------------------------------------------------- lockout
def test_five_failures_lock_the_client_out(server):
    client = server.client()
    messages = [_flash(_wrong(client)) for _ in range(5)]
    assert messages[:4] == [
        f"Invalid username or password. {n} attempt(s) remaining." for n in (4, 3, 2, 1)
    ]
    assert messages[4] == "Too many failed attempts. Try again in 300 seconds."


def test_correct_password_is_refused_while_locked_out(server):
    client = server.client()
    for _ in range(5):
        _wrong(client)
    reply = client.login(RW, RW_PASSWORD)
    assert reply.status == 429
    assert "Too many failed attempts" in _flash(reply)
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401


def test_lockout_is_keyed_by_the_client_ip_the_proxy_reports(server):
    # Documented trust model (core.py get_client_ip): behind the Cloudflare tunnel the
    # CF-Connecting-IP header is the client identity. Another identity has its own counter.
    locked = server.client()
    for _ in range(5):
        _wrong(locked)
    assert locked.login(RW, RW_PASSWORD).status == 429
    assert server.client().login(RW, RW_PASSWORD).status == 302


def test_successful_login_resets_the_failure_counter(server):
    ip = "10.99.0.1"
    for _ in range(3):
        _wrong(server.client(ip))
    assert server.client(ip).login(RW, RW_PASSWORD).status == 302
    assert _flash(_wrong(server.client(ip))) == (
        "Invalid username or password. 4 attempt(s) remaining."
    )


# ---------------------------------------------------------------------------- sessions
def test_anonymous_session_check_answers_json_to_api_clients(server):
    reply = server.client().get("/check_session", headers=JSON_HEADERS)
    assert reply.status == 401
    assert reply.json() == {"error": "Session expired", "redirect": "/login"}
    assert reply.header("Cache-Control") == "no-store"


def test_anonymous_page_requests_are_redirected_to_login(server):
    reply = server.client().get("/check_session")
    assert reply.status == 301
    assert reply.header("Location").endswith("/login")
    assert reply.header("Cache-Control") == "no-store"
    assert reply.body == b""


def test_logout_ends_the_session(server):
    client = server.login_as(RW)
    reply = client.get("/logout")
    assert reply.status == 302
    assert reply.header("Location").endswith("/login?logged_out=1")
    assert "no-store" in reply.header("Cache-Control")
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401


@pytest.mark.xfail(
    strict=True,
    reason="KNOWN LIMITATION: a session cookie survives logout (CLAUDE.md part 58)",
)
def test_cookie_copied_before_logout_is_rejected_after_logout(server):
    client = server.login_as(RW)
    copied = client.cookie_header()
    client.get("/logout")
    replay = server.client().get(
        "/check_session", headers={**JSON_HEADERS, "Cookie": copied}
    )
    assert replay.status == 401


def test_deleting_a_user_ends_their_session_immediately(server):
    name, password = server.make_user("readwrite")
    # /cancel_bulk_zip has no login_required decorator: only the global session hook guards it.
    # One logged-in client per path (the first refused request clears that client's cookie), and
    # the CSRF token is fetched BEFORE the deletion, like a page that is already open.
    probes = [
        ("GET", "/check_session"),
        ("GET", "/api/files/"),
        ("POST", "/cancel_bulk_zip"),
    ]
    sessions = []
    for _ in probes:
        client = server.client()
        assert client.login(name, password).status == 302
        assert client.get("/check_session", headers=JSON_HEADERS).status == 200
        sessions.append((client, client.csrf_token()))
    server.db("assert db.delete_user(sys.argv[1])", name)
    for (client, token), (method, path) in zip(sessions, probes):
        headers = {**JSON_HEADERS, "X-CSRFToken": token}
        reply = client.request(method, path, fields=None, headers=headers)
        assert reply.status == 401, (path, reply.status)


def test_rotating_the_server_token_ends_every_session(server):
    first, second = server.login_as(RW), server.login_as(RO)
    assert first.get("/check_session", headers=JSON_HEADERS).status == 200
    server.db("db.rotate_server_token()")
    assert first.get("/check_session", headers=JSON_HEADERS).status == 401
    assert second.get("/check_session", headers=JSON_HEADERS).status == 401
    # and logging in again works with the new token
    assert server.login_as(RW).get("/check_session", headers=JSON_HEADERS).status == 200


def test_a_changed_password_does_not_log_in_with_the_old_one(server):
    name, old = server.make_user("readwrite")
    server.db(
        "assert db.update_password(sys.argv[1], sys.argv[2])", name, "New-Pass-9!"
    )
    assert server.client().login(name, old).status == 401
    assert server.client().login(name, "New-Pass-9!").status == 302
