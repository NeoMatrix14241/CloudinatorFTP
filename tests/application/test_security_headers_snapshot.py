"""
Security headers of the login / logout / index responses (5.48, Phase 0 of the no-refresh login).

The site is scored by an external header scanner, so the response headers must not move when the
login page starts answering JSON and the file manager starts being fetched into the page. Every
security header comes from `after_request` in middleware.py; these tests pin that the NEW response
flavours go through the same hook and carry the very same set:

* `GET /login` as the browser asks for it, as the page shell fetches it (header
  `X-Requested-With: XMLHttpRequest`), and the answers of `POST /login` in JSON mode;
* `GET /` as a navigation and as the shell's fetch;
* `GET /logout` (classic) and `POST /logout` (JSON, the in-page logout).

The ONE intended difference is `Clear-Site-Data`: it stays on the classic `GET /login` and `GET /logout`
(a navigation, which the browser honours by reloading the page) and is left off the answers that
the page shell asks for itself, because there it would reload the very page that is fetching.
A scanner or a browser navigation never sends `X-Requested-With`, so it never sees the difference.

Secure-only headers (HSTS, Clear-Site-Data) are only sent for requests that arrive over HTTPS, so
these requests carry `X-Forwarded-Proto: https` and the session cookie is passed by hand (the
scratch server speaks plain http, and a client library would not send a Secure cookie back).
The Content-Security-Policy contains a per-response nonce; it is replaced before comparing.
"""

import re

import pytest

pytestmark = pytest.mark.application

RW = "qa_writer"
HTTPS = {"X-Forwarded-Proto": "https"}
XHR = {"X-Requested-With": "XMLHttpRequest"}
JSON_ACCEPT = {"Accept": "application/json"}

# What the scanner looks at (observed on the scratch server; a header that disappears fails the
# "all present" test below, a header that changes value fails the comparisons).
SECURITY_HEADERS = (
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
    "cross-origin-opener-policy",
    "cross-origin-embedder-policy",
    "cross-origin-resource-policy",
    "origin-agent-cluster",
    "integrity-policy-report-only",
    "document-policy",
    "x-permitted-cross-domain-policies",
    "x-dns-prefetch-control",
    "x-xss-protection",
    "x-robots-tag",
)
CACHE_HEADERS = ("cache-control", "pragma", "expires")


@pytest.fixture
def server(scratch_server):
    return scratch_server


def _headers(reply):
    out = {}
    for name, value in reply.headers.items():
        out[name.lower()] = re.sub(r"'nonce-[^']+'", "'nonce-X'", value)
    return out


def _security(reply):
    h = _headers(reply)
    return {name: h.get(name) for name in SECURITY_HEADERS}


def _cache(reply):
    h = _headers(reply)
    return {name: h.get(name) for name in CACHE_HEADERS}


def _secure_login(server):
    """A logged-in client, the headers that present its (Secure) cookie over 'https', and its
    CSRF token. The token is minted by the first call and becomes part of the session cookie,
    so the cookie header is rebuilt after it."""
    client = server.login_as(RW)
    first = {"Cookie": client.cookie_header(), **HTTPS}
    token = client.get("/csrf-token", headers=first).json()["csrf_token"]
    return client, {"Cookie": client.cookie_header(), **HTTPS}, token


def _json_login(client, user, password, token, headers):
    return client.request(
        "POST",
        "/login",
        json_body={"username": user, "password": password},
        headers={**JSON_ACCEPT, **XHR, "X-CSRFToken": token, **headers},
    )


def test_every_expected_security_header_is_present_on_the_login_page(server):
    page = server.client().get("/login", headers=HTTPS)
    missing = [n for n, v in _security(page).items() if not v]
    assert not missing, f"security headers missing from GET /login: {missing}"


def test_login_page_flavours_carry_the_same_security_headers(server):
    classic = server.client().get("/login", headers=HTTPS)
    shell_fetch = server.client().get("/login", headers={**HTTPS, **XHR})

    anonymous = server.client()
    token = anonymous.csrf_token()
    failed = _json_login(anonymous, "no_such_user", "x", token, HTTPS)
    assert failed.status == 401
    signing_in = server.client()
    ok = _json_login(
        signing_in, RW, server.users[RW][0], signing_in.csrf_token(), HTTPS
    )
    assert ok.status == 200 and ok.json()["success"] is True

    for name, reply in (
        ("GET /login via the shell", shell_fetch),
        ("POST /login (JSON) wrong password", failed),
        ("POST /login (JSON) success", ok),
    ):
        assert _security(reply) == _security(classic), name
        assert _cache(reply) == _cache(classic), name


def test_clear_site_data_stays_on_the_classic_pages_and_only_there(server):
    classic = server.client().get("/login", headers=HTTPS)
    assert _headers(classic).get("clear-site-data") == '"executionContexts"'

    shell_fetch = server.client().get("/login", headers={**HTTPS, **XHR})
    assert "clear-site-data" not in _headers(shell_fetch)

    client, secure, token = _secure_login(server)
    classic_logout = client.get("/logout", headers=secure)
    assert classic_logout.status == 302
    assert _headers(classic_logout).get("clear-site-data") == '"executionContexts"'

    client, secure, token = _secure_login(server)
    in_page = client.request(
        "POST",
        "/logout",
        headers={**secure, **JSON_ACCEPT, **XHR, "X-CSRFToken": token},
    )
    assert in_page.status == 200
    assert "clear-site-data" not in _headers(in_page)


def test_the_index_page_carries_the_same_headers_when_the_shell_fetches_it(server):
    client, secure, token = _secure_login(server)
    navigation = client.get("/", headers=secure)
    shell_fetch = client.get("/", headers={**secure, **XHR, "Accept": "text/html"})
    assert navigation.status == shell_fetch.status == 200
    assert _security(shell_fetch) == _security(navigation)
    assert _cache(shell_fetch) == _cache(navigation)
    assert "clear-site-data" not in _headers(shell_fetch)


def test_the_in_page_logout_carries_the_same_security_headers_as_the_classic_one(
    server,
):
    client, secure, token = _secure_login(server)
    classic = client.get("/logout", headers=secure)

    client, secure, token = _secure_login(server)
    in_page = client.request(
        "POST",
        "/logout",
        headers={**secure, **JSON_ACCEPT, **XHR, "X-CSRFToken": token},
    )
    assert _security(in_page) == _security(classic)
    for name, value in _cache(in_page).items():
        assert value, f"{name} missing from the in-page logout answer"
    assert "no-store" in _cache(in_page)["cache-control"]
