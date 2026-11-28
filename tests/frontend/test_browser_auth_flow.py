"""
Browser scenarios for the no-refresh login and logout (5.48): a real Chromium logs in, logs out and
logs in again WITHOUT the page ever being reloaded.

What the Node/jsdom-free tests cannot show and only a browser can:

* no `document` request is made after the login page loaded: the file manager arrives through
  fetch() and is swapped into the same document (static/js/shell.js). A marker set on `window`
  survives login, logout and the second login; a reload would have wiped it;
* the swap is CSP-clean and SRI-clean in a real browser: not one console message about a blocked
  script, a refused style or an integrity mismatch (the page scripts are injected from JavaScript,
  with the `integrity` attribute copied from the template, under `script-src 'self'`);
* a DIFFERENT user logging in after a logout gets a brand-new document (shell.js refuses to reuse a
  document that showed another account), so nothing of the first user's page can be reached;
* a wrong password is answered in place: message shown, marker still there, no reload;
* the shell never fell back to an ordinary page load: when it does, it logs a `[shell] falling
  back to a page load of ...: <reason>` warning, and these tests print that reason.

Waiting: a swapped view is on screen before its script has run, so the shell marks `<body>` with
`data-shell-ready=<view>` only once the page script is mounted (and changes the address then, and
keeps the file manager `inert` until then). Every wait here uses that attribute. Playwright's
`wait_for_function` is NOT usable on these pages: it evaluates a string, which the
Content-Security-Policy (no 'unsafe-eval') refuses; use locators and selectors.

OPT-IN like the other browser tests (CLOUDINATOR_SLOW_TESTS=1; the nightly workflow installs
Playwright and Chromium):

    python -m pip install playwright
    python -m playwright install chromium
    CLOUDINATOR_SLOW_TESTS=1 python -m pytest tests/frontend/test_browser_auth_flow.py -q

CLOUDINATOR_BROWSER_CHANNEL picks another installed browser (`msedge` on Windows). Every wait is a
Playwright locator or a bounded poll, never a fixed sleep. Each test uses its own fake client IP
(CF-Connecting-IP) so that the login rate limiter of one test never affects another.

Not covered: Firefox and Safari, mobile layouts, the PDF and video viewers after a re-login.
"""

import os

import pytest

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("CLOUDINATOR_SLOW_TESTS") != "1",
        reason="needs a browser and takes time: set CLOUDINATOR_SLOW_TESTS=1 to run",
    ),
]

RW, RO = "qa_writer", "qa_reader"
WAIT_MS = 45_000
IGNORED_MESSAGES = ("Document-Policy", "document-write")
# Console text that means the browser refused something the swap tried to do.
CSP_OR_SRI_WORDS = ("content security policy", "integrity", "refused to")


@pytest.fixture(scope="module")
def server(scratch_server):
    return scratch_server


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        channel = os.environ.get("CLOUDINATOR_BROWSER_CHANNEL") or None
        instance, problem = None, ""
        try:
            instance = playwright.chromium.launch(headless=True, channel=channel)
        except Exception as exc:  # the browser binary is missing
            problem = str(exc)
        if instance is None:
            pytest.skip(
                f"no browser available ({problem}); run: python -m playwright install chromium"
            )
        yield instance
        instance.close()


class Session:
    """One browser context + page with the request / console bookkeeping of a test."""

    def __init__(self, browser, server, ip):
        self.server = server
        self.context = browser.new_context(
            extra_http_headers={"CF-Connecting-IP": ip},
            viewport={"width": 1280, "height": 800},
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(WAIT_MS)
        self.documents = []
        self.problems = []
        self.fallbacks = []
        self.page.on("request", self._on_request)
        self.page.on("console", self._on_console)
        self.page.on("pageerror", lambda error: self.problems.append(str(error)))

    def _on_request(self, request):
        if request.resource_type == "document":
            self.documents.append(request.url)

    def _on_console(self, message):
        text = message.text
        if message.type == "warning" and "[shell]" in text:
            self.fallbacks.append(text)
            return
        if message.type != "error" or any(i in text for i in IGNORED_MESSAGES):
            return
        if any(word in text.lower() for word in CSP_OR_SRI_WORDS):
            self.problems.append(text)

    def open_login_page(self):
        self.page.goto(self.server.base_url + "/login", wait_until="load")
        self.page.wait_for_selector(
            "body[data-shell-view=login][data-shell-ready=login]"
        )
        # From here on a document request means the page was reloaded or navigated.
        self.documents.clear()
        self.page.evaluate("window.__noReload = 'still-the-same-document'")

    def sign_in(self, user, password=None):
        password = self.server.users[user][0] if password is None else password
        self.page.locator("#username").fill(user)
        self.page.locator("#password").fill(password)
        self.page.locator("#password").press("Enter")

    def wait_for_view(self, view, fallback_expected=False):
        self.page.wait_for_selector(
            f"body[data-shell-view={view}][data-shell-ready={view}]"
        )
        if not fallback_expected:
            assert (
                self.fallbacks == []
            ), "the shell fell back to a page load: " + "; ".join(self.fallbacks)
        if view == "app":
            self.page.wait_for_selector("#filesTableBody", state="attached")
        else:
            self.page.wait_for_selector("#loginForm", state="visible")

    def marker(self):
        return self.page.evaluate("window.__noReload || null")

    def close(self):
        self.context.close()


@pytest.fixture()
def session(browser, server, request):
    ip_suffix = abs(hash(request.node.name)) % 200 + 20
    made = Session(browser, server, f"10.98.0.{ip_suffix}")
    try:
        yield made
    finally:
        made.close()


def test_login_logout_and_login_again_never_reload_the_page(session):
    session.open_login_page()

    session.sign_in(RW)
    session.wait_for_view("app")
    assert (
        session.marker() == "still-the-same-document"
    ), "the page was reloaded by the login"
    assert (
        session.documents == []
    ), f"document requests after login: {session.documents}"
    assert "/login" not in session.page.url

    session.page.locator("[data-fn=logout]").first.click()
    session.wait_for_view("login")
    assert (
        session.marker() == "still-the-same-document"
    ), "the page was reloaded by the logout"
    assert (
        session.documents == []
    ), f"document requests after logout: {session.documents}"
    assert session.page.url.endswith("/login")
    assert (
        session.page.locator("#filesTableBody").count() == 0
    ), "file manager DOM left behind"

    session.sign_in(RW)
    session.wait_for_view("app")
    assert (
        session.marker() == "still-the-same-document"
    ), "the second login reloaded the page"
    assert session.documents == []

    assert session.problems == [], "\n".join(session.problems)


def test_a_different_user_after_a_logout_gets_a_new_document(session):
    session.open_login_page()
    session.sign_in(RW)
    session.wait_for_view("app")
    role = session.page.evaluate(
        "document.getElementById('flask-config').dataset.userRole"
    )
    assert role == "readwrite"

    session.page.locator("[data-fn=logout]").first.click()
    session.wait_for_view("login")
    session.documents.clear()

    session.sign_in(RO)
    session.wait_for_view("app", fallback_expected=True)
    assert (
        session.documents
    ), "a different user must get a real page load, not an in-place swap"
    assert (
        session.marker() is None
    ), "state of the first document survived for the second user"
    role = session.page.evaluate(
        "document.getElementById('flask-config').dataset.userRole"
    )
    assert role == "readonly"
    assert session.problems == [], "\n".join(session.problems)


def test_a_wrong_password_is_answered_in_place(session):
    session.open_login_page()
    session.sign_in(RW, "definitely-wrong-password")
    session.page.locator(
        "#flashText", has_text="Invalid username or password"
    ).wait_for()
    assert session.marker() == "still-the-same-document"
    assert session.documents == []
    assert session.page.locator("#loginBtn").is_enabled()
    assert session.problems == [], "\n".join(session.problems)
