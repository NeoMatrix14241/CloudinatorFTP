"""
Browser smoke test (5.40): a real Chromium opens the scratch application, logs in and loads the
file manager. It checks what no HTTP-level test can see: that the page's JavaScript runs without
errors, that every script, style sheet and font the page asks for really loads, and that the
Subresource Integrity hashes in the templates match the files being served (a stale hash makes the
browser refuse the file and print a console error).

It deliberately does NOT click through features: the DOM ids and the upload flow are checked by
the HTTP tests and by hand. This is a tripwire for "the page is broken in a browser".

OPT-IN: needs Playwright and a browser, and takes several seconds. Skipped unless
CLOUDINATOR_SLOW_TESTS=1 (the nightly workflow sets it and installs both):

    python -m pip install playwright
    python -m playwright install chromium
    CLOUDINATOR_SLOW_TESTS=1 python -m pytest tests/frontend -q

CLOUDINATOR_BROWSER_CHANNEL picks another installed browser, e.g. `msedge` to run it in Edge on
Windows. The Document-Policy `document-write` console message is ignored on purpose: some
browsers (Edge) do not recognise that policy token and warn about it; it is not an application bug.

Not covered: Firefox and Safari, mobile layouts, drag and drop, the video and PDF viewers.
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

IGNORED_MESSAGES = ("Document-Policy", "document-write")


@pytest.fixture(scope="module")
def server(scratch_server):
    return scratch_server


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        channel = os.environ.get("CLOUDINATOR_BROWSER_CHANNEL") or None
        try:
            instance = playwright.chromium.launch(headless=True, channel=channel)
        except Exception as exc:  # the browser binary is missing
            pytest.skip(
                f"no browser available ({exc}); run: python -m playwright install chromium"
            )
        yield instance
        instance.close()


class Watcher:
    """Collects everything that goes wrong while a page loads."""

    def __init__(self, page, base_url):
        self.problems = []
        page.on("pageerror", lambda exc: self._add("page error", str(exc)))
        page.on("console", self._console)
        page.on(
            "requestfailed",
            lambda req: self._add("request failed", f"{req.url} {req.failure}"),
        )
        page.on("response", lambda resp: self._response(resp, base_url))

    def _add(self, kind, text):
        if not any(token in text for token in IGNORED_MESSAGES):
            self.problems.append(f"{kind}: {text}")

    def _console(self, message):
        if message.type == "error":
            self._add("console error", message.text)

    def _response(self, response, base_url):
        if response.url.startswith(base_url) and response.status >= 400:
            self._add("HTTP error", f"{response.status} {response.url}")


def _fresh_page(browser, server):
    context = browser.new_context(extra_http_headers={"CF-Connecting-IP": "10.99.0.1"})
    page = context.new_page()
    return context, page, Watcher(page, server.base_url)


def test_the_login_page_loads_without_errors(browser, server):
    context, page, watcher = _fresh_page(browser, server)
    try:
        page.goto(server.base_url + "/login", wait_until="networkidle")
        assert (
            page.locator("input[type=password]").count() >= 1
        ), "no password field on /login"
        assert watcher.problems == [], "\n".join(watcher.problems)
    finally:
        context.close()


def test_logging_in_opens_the_file_manager_without_errors(browser, server):
    context, page, watcher = _fresh_page(browser, server)
    try:
        page.goto(server.base_url + "/login", wait_until="networkidle")
        user_name = "qa_writer"
        password = server.users[user_name][
            0
        ]  # TEST_USERS maps name -> (password, role)
        page.locator("input[name=username], input[type=text]").first.fill(user_name)
        page.locator("input[type=password]").first.fill(password)
        page.locator("input[type=password]").first.press("Enter")
        page.wait_for_url(lambda url: "/login" not in url, timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=30_000)
        assert page.title().strip() != ""
        assert page.locator("body").inner_text().strip() != ""
        assert watcher.problems == [], "\n".join(watcher.problems)
    finally:
        context.close()


def test_a_page_that_needs_a_login_sends_an_anonymous_browser_to_the_login_page(
    browser, server
):
    context, page, _ = _fresh_page(browser, server)
    try:
        page.goto(server.base_url + "/", wait_until="networkidle")
        assert "/login" in page.url
    finally:
        context.close()
