"""
The JSON flavour of /login and /logout and the view contract of the page shell (5.48).

`POST /login` and `POST /logout` also answer JSON, which is what static/js/login.js and
static/js/shell.js use to log in and out WITHOUT a page refresh. The classic form flow (302 / a
rendered page with a flash message) is covered in test_login.py and is unchanged; these tests
cover what is new:

* the shape of the answers (success, wrong password, lockout with `retry_after`);
* that the same rules hold: CSRF is required, a lockout refuses even the right password, a
  logged-in session is never switched to another account by a POST;
* that the in-page logout really ends the session on the server (a copy of the cookie stops
  working) and answers without redirect;
* what the shell fetches: `GET /login` and `GET /` with `X-Requested-With: XMLHttpRequest` are the
  normal pages, each marked with `data-shell-view`, and the app page names its user in
  `data-username` (the shell refuses to reuse a document for a different user).

Every test uses its own client and therefore its own fake client IP, so the in-memory login rate
limiter never leaks between tests (see test_login.py).
"""

import re

import pytest

pytestmark = pytest.mark.application

RW, RO = "qa_writer", "qa_reader"
RW_PASSWORD = "QaWriter-Pass-1!"
JSON_HEADERS = {"Accept": "application/json"}
XHR = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
def server(scratch_server):
    return scratch_server


def _cookie(client, name="cloudinator_session"):
    return next((c.value for c in client.jar if c.name == name), None)


def _login(client, user, password, token=None, extra=None):
    """A login the way login.js sends it: JSON body, Accept, X-Requested-With, CSRF header."""
    token = client.csrf_token() if token is None else token
    headers = {**JSON_HEADERS, **XHR, "X-CSRFToken": token}
    headers.update(extra or {})
    return client.request(
        "POST",
        "/login",
        json_body={"username": user, "password": password},
        headers=headers,
    )


def _wrong(client, user=RW):
    return _login(client, user, "definitely-wrong-password")


def _logout(client, token=None):
    token = client.csrf_token() if token is None else token
    return client.request(
        "POST", "/logout", headers={**JSON_HEADERS, **XHR, "X-CSRFToken": token}
    )


# ---------------------------------------------------------------------------- logging in
@pytest.mark.parametrize("user,role", [(RW, "readwrite"), (RO, "readonly")])
def test_json_login_answers_json_and_starts_a_session(server, user, role):
    client = server.client()
    reply = _login(client, user, server.users[user][0])
    assert reply.status == 200
    assert reply.header("Content-Type").startswith("application/json")
    body = reply.json()
    assert body["success"] is True
    assert body["username"] == user and body["role"] == role
    assert body["redirect"] in ("/", server.base_url + "/")
    assert client.get("/check_session", headers=JSON_HEADERS).json() == {"status": "ok"}
    assert client.get("/api/files/", headers=JSON_HEADERS).json()["role"] == role


def test_json_login_hands_out_the_new_csrf_token(server):
    client = server.client()
    before_cookie, before_token = None, client.csrf_token()
    before_cookie = _cookie(client)
    body = _login(client, RW, RW_PASSWORD, token=before_token).json()
    assert len(body["csrf_token"]) >= 32 and body["csrf_token"] != before_token
    assert _cookie(client) != before_cookie  # a new session, as in the classic flow
    assert client.csrf_token() == body["csrf_token"]


def test_json_login_is_never_cached(server):
    client = server.client()
    reply = _login(client, RW, RW_PASSWORD)
    assert "no-store" in reply.header("Cache-Control")
    assert reply.header("Pragma") == "no-cache"


def test_json_login_also_accepts_a_form_encoded_body(server):
    client = server.client()
    token = client.csrf_token()
    reply = client.request(
        "POST",
        "/login",
        fields={"username": RW, "password": RW_PASSWORD, "csrf_token": token},
        headers={**JSON_HEADERS, **XHR},
    )
    assert reply.status == 200 and reply.json()["success"] is True


def test_json_login_trims_the_username_but_not_the_password(server):
    assert _login(server.client(), f"  {RW}  ", RW_PASSWORD).status == 200
    assert _login(server.client(), RW, RW_PASSWORD + " ").status == 401


def test_a_json_body_of_the_wrong_type_is_a_failed_login_not_a_crash(server):
    client = server.client()
    token = client.csrf_token()
    reply = client.request(
        "POST",
        "/login",
        json_body={"username": ["a"], "password": {"b": 1}},
        headers={**JSON_HEADERS, **XHR, "X-CSRFToken": token},
    )
    assert reply.status == 401 and reply.json()["success"] is False


def test_json_login_without_a_csrf_token_is_refused(server):
    client = server.client()
    client.csrf_token()
    reply = client.request(
        "POST",
        "/login",
        json_body={"username": RW, "password": RW_PASSWORD},
        headers={**JSON_HEADERS, **XHR},
    )
    assert reply.status == 400
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401


def test_json_login_with_a_wrong_csrf_token_is_refused(server):
    client = server.client()
    client.csrf_token()
    assert _login(client, RW, RW_PASSWORD, token="not-the-token").status == 400


def test_a_json_login_cannot_switch_a_logged_in_session_to_another_account(server):
    client = server.login_as(RO)
    reply = _login(client, RW, RW_PASSWORD, token=client.csrf_token())
    assert reply.status == 200
    body = reply.json()
    assert body["already_logged_in"] is True
    assert body["username"] == RO and body["role"] == "readonly"
    assert client.get("/api/files/", headers=JSON_HEADERS).json()["role"] == "readonly"


# ---------------------------------------------------------------------------- failures
def test_wrong_password_is_a_401_with_the_server_message_and_no_session(server):
    client = server.client()
    reply = _wrong(client)
    assert reply.status == 401
    body = reply.json()
    assert body["success"] is False and body["attempts_remaining"] == 4
    assert body["message"] == "Invalid username or password. 4 attempt(s) remaining."
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401


def test_unknown_user_and_wrong_password_look_identical_in_json_too(server):
    known = _wrong(server.client(), RW).json()
    unknown = _wrong(server.client(), "no_such_user_at_all").json()
    assert known == unknown


def test_five_failures_lock_out_with_a_429_and_a_retry_after(server):
    client = server.client()
    replies = [_wrong(client) for _ in range(5)]
    assert [r.status for r in replies] == [401, 401, 401, 401, 429]
    last = replies[-1]
    body = last.json()
    assert body["success"] is False
    assert body["message"] == "Too many failed attempts. Try again in 300 seconds."
    assert 295 <= body["retry_after"] <= 300
    assert last.header("Retry-After") == str(body["retry_after"])
    assert "attempts_remaining" not in body


def test_the_right_password_is_refused_while_locked_out(server):
    client = server.client()
    for _ in range(5):
        _wrong(client)
    reply = _login(client, RW, RW_PASSWORD)
    assert reply.status == 429
    assert 0 < reply.json()["retry_after"] <= 300
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401


def test_the_lockout_counts_json_and_classic_failures_together(server):
    client = server.client()
    client.login(RW, "wrong-one")  # classic form post
    client.login(RW, "wrong-two")
    assert _wrong(client).json()["attempts_remaining"] == 2


# ---------------------------------------------------------------------------- logging out
def test_json_logout_ends_the_session_on_the_server(server):
    client = server.login_as(RW)
    token = client.csrf_token()
    old_cookie = client.cookie_header()
    reply = _logout(client, token)
    assert reply.status == 200
    assert reply.header("Content-Type").startswith("application/json")
    body = reply.json()
    assert body["success"] is True and body["redirect"].endswith("/login")
    assert "no-store" in reply.header("Cache-Control")
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401
    # a copy of the cookie taken before the logout stops working too (5.17)
    replay = server.client().get(
        "/api/files/", headers={**JSON_HEADERS, "Cookie": old_cookie}
    )
    assert replay.status == 401


def test_json_logout_needs_a_csrf_token(server):
    client = server.login_as(RW)
    client.csrf_token()
    reply = client.request("POST", "/logout", headers={**JSON_HEADERS, **XHR})
    assert reply.status == 400
    assert client.get("/check_session", headers=JSON_HEADERS).json() == {"status": "ok"}


def test_a_logout_form_post_without_json_headers_still_redirects(server):
    client = server.login_as(RW)
    token = client.csrf_token()
    reply = client.post_form("/logout", {"csrf_token": token})
    assert reply.status == 302 and "/login" in reply.header("Location")
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401


def test_the_classic_get_logout_is_unchanged(server):
    client = server.login_as(RW)
    reply = client.get("/logout")
    assert reply.status == 302 and "/login" in reply.header("Location")
    assert client.get("/check_session", headers=JSON_HEADERS).status == 401


def test_after_an_in_page_logout_the_old_csrf_token_is_dead(server):
    client = server.login_as(RW)
    token = client.csrf_token()
    assert _logout(client, token).status == 200
    fresh = client.csrf_token()
    assert fresh != token
    assert _login(client, RW, RW_PASSWORD, token=token).status == 400
    assert _login(client, RW, RW_PASSWORD, token=fresh).status == 200


# ---------------------------------------------------------------------------- shell contract
def test_the_login_view_is_marked_and_carries_a_csrf_meta_tag(server):
    page = server.client().get("/login", headers={**XHR, "Accept": "text/html"})
    assert page.status == 200
    assert '<body data-shell-view="login"' in page.text
    meta = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
    assert meta and len(meta.group(1)) >= 32
    assert 'data-shell="page"' in page.text and "/static/js/login.js" in page.text
    assert "/static/js/shell.js" in page.text


def _without_tokens(text):
    return re.sub(r'(csrf_token" value|content)="[^"]+"', r'\1=""', text)


def test_the_login_view_is_the_same_page_with_or_without_the_shell_header(server):
    plain = server.client().get("/login")
    shell = server.client().get("/login", headers=XHR)
    assert _without_tokens(plain.text) == _without_tokens(shell.text)


def test_the_app_view_names_its_user_and_is_marked(server):
    client = server.login_as(RW)
    page = client.get("/", headers={**XHR, "Accept": "text/html"})
    assert page.status == 200
    assert '<body data-shell-view="app"' in page.text
    assert f'data-username="{RW}"' in page.text
    assert 'data-shell="page"' in page.text and "/static/js/index.js" in page.text
    assert (
        "data-shell-persist" in page.text
    )  # the pdf viewer root and the music element


def test_the_app_view_for_another_user_names_that_user(server):
    page = server.login_as(RO).get("/", headers={**XHR, "Accept": "text/html"})
    assert f'data-username="{RO}"' in page.text
    assert f'data-username="{RW}"' not in page.text


def test_the_shell_gets_a_401_not_a_redirect_for_the_app_view_when_logged_out(server):
    reply = server.client().get("/", headers={**XHR, "Accept": "text/html"})
    assert reply.status == 401
