"""static/js/login.js: every fetch() on the login page must use redirect: 'manual' (5.43).

A logged-out visitor's request to a protected URL is answered with a redirect to /login. A
default fetch() follows it and reports the login page itself as ok, so the page would treat an
anonymous visitor as logged in and replace itself with '/', which redirects back to /login: a
reload that wipes what the visitor had typed (found by reading /admin/upload_status's real answer:
301 to /login unless the request asks for JSON). Source test: no browser needed.
"""

import re
from pathlib import Path

LOGIN_JS = Path(__file__).resolve().parents[2] / "static" / "js" / "login.js"


def _fetch_calls(text):
    """Each `fetch(` call with its argument list, up to the matching parenthesis."""
    calls = []
    for match in re.finditer(r"\bfetch\(", text):
        depth, i = 1, match.end()
        while depth and i < len(text):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        calls.append(text[match.start() : i])
    return calls


def test_login_js_has_fetch_calls_to_check():
    assert len(_fetch_calls(LOGIN_JS.read_text(encoding="utf-8"))) >= 2


def test_every_fetch_in_login_js_asks_for_manual_redirect_handling():
    for call in _fetch_calls(LOGIN_JS.read_text(encoding="utf-8")):
        assert re.search(r"redirect:\s*['\"]manual['\"]", call), call
