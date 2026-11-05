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

Why there is no `wait_until="networkidle"` (5.43): Playwright's networkidle needs 500 ms without
ANY open request, and these pages keep some open on purpose: the file manager holds two
EventSource streams (storage statistics, share requests) and every page with background music
has a looping <audio> element. The first run on the real application timed out after 30 s on
/login and /. `Watcher.wait_until_quiet()` is the same idea with those request types left out;
when something else stays open it fails and NAMES the open requests (method, type, URL, the
request it was redirected from, and its Accept header, so the page script that started it can be
found).
"""

import os
import time

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
        # `instance` and `problem` are set before the try: pytest.skip never returns, but a static
        # analyser (CodeQL) cannot know that and flags a variable that is only set inside the try.
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


# Requests that stay open by design (EventSource streams, the background music, WebSockets).
STREAMING_TYPES = ("eventsource", "media", "websocket")

# Requests whose body the page's own script reads. Once their response has arrived, the page has
# what it asked for; whether the script then reads the body is the script's business.
SCRIPT_REQUEST_TYPES = ("fetch", "xhr")


def _describe(request):
    """One line that says what a request is and where it came from, for failure messages."""
    origin = request.redirected_from.url if request.redirected_from else None
    accept = request.headers.get("accept")
    return (
        f"{request.method} {request.resource_type} {request.url} "
        f"(redirected_from={origin}, accept={accept}, "
        f"navigation={request.is_navigation_request()})"
    )


class Watcher:
    """Collects everything that goes wrong while a page loads."""

    def __init__(self, page, base_url):
        self.problems = []
        self.open_requests = set()
        self.started_at = {}
        self.responses = {}
        page.on("pageerror", lambda exc: self._add("page error", str(exc)))
        page.on("console", self._console)
        # Plain methods, not `set.add`: Playwright wraps every handler by setting an attribute on
        # it, which a built-in method cannot take (AttributeError, 5.43 fix1).
        page.on("request", self._started)
        page.on("requestfinished", self._finished)
        page.on("requestfailed", self._failed)
        page.on("response", lambda resp: self._response(resp, base_url))

    def _add(self, kind, text):
        if not any(token in text for token in IGNORED_MESSAGES):
            self.problems.append(f"{kind}: {text}")

    def _console(self, message):
        if message.type == "error":
            self._add("console error", message.text)

    def _started(self, request):
        self.started_at[request] = time.monotonic()
        self.open_requests.add(request)

    def _finished(self, request):
        self.open_requests.discard(request)
        self.started_at.pop(request, None)
        self.responses.pop(request, None)

    def _failed(self, request):
        self.open_requests.discard(request)
        self.started_at.pop(request, None)
        self.responses.pop(request, None)
        # The browser cancels and re-issues the range requests of an <audio> element by itself;
        # that cancellation is not a broken resource.
        if request.resource_type == "media" and "ERR_ABORTED" in str(request.failure):
            return
        # A fetch() with redirect: "manual" (login.js asks whether the visitor is logged in)
        # makes Chromium cancel the request it would otherwise have followed; Playwright
        # reports that as a failed fetch that was redirected from the first URL. It is the
        # page's own choice not to follow the redirect, not a broken resource.
        if (
            request.resource_type == "fetch"
            and request.redirected_from is not None
            and "ERR_ABORTED" in str(request.failure)
        ):
            return
        self._add("request failed", f"{_describe(request)} {request.failure}")

    def _response(self, response, base_url):
        self.responses[response.request] = response.status
        if response.url.startswith(base_url) and response.status >= 400:
            self._add("HTTP error", f"{response.status} {response.url}")

    def _answered_script_request(self, request):
        """True for a fetch()/XHR whose response has arrived (headers and status are known).

        Chromium reports such a request as finished only once the page script has read or
        dropped the body. Pages here call fetch() for a small JSON answer and look only at
        `response.ok`, so the request stays "open" in Playwright for as long as the body is
        unread (30 s and more on /admin/upload_status), although the server answered at once.
        A server that does not answer at all still counts: it has no response.
        """
        return (
            request.resource_type in SCRIPT_REQUEST_TYPES and request in self.responses
        )

    def wait_until_quiet(self, page, timeout=30.0, quiet=0.5):
        """Wait until no request except a streaming one has been open for `quiet` seconds.

        An answered fetch()/XHR does not count as open (see `_answered_script_request`).

        Bounded polling (the rule of CODING_GUIDELINES.md 18): `page.wait_for_timeout` only lets
        Playwright deliver its events; it is never the thing a test waits for. On a timeout the
        failure lists what was still open, which is the diagnosis a plain timeout would hide.
        """
        deadline = time.monotonic() + timeout
        busy = []
        quiet_since = None
        settled = False
        while not settled and time.monotonic() < deadline:
            busy = [
                request
                for request in self.open_requests
                if request.resource_type not in STREAMING_TYPES
                and not self._answered_script_request(request)
            ]
            now = time.monotonic()
            if busy:
                quiet_since = None
            elif quiet_since is None:
                quiet_since = now
            settled = quiet_since is not None and now - quiet_since >= quiet
            if not settled:
                page.wait_for_timeout(50)
        if not settled:
            # The age tells one request that hangs (open for ~30 s) from a poll that starts a
            # fresh request every time the previous one ends (open for a fraction of a second).
            # The status tells a server that never answered ("no response yet") from a page
            # that got its answer (e.g. "status 200") but never read the body, so the browser
            # does not count the request as finished.
            ended = time.monotonic()
            names = (
                "; ".join(
                    f"{_describe(request)} open for "
                    f"{ended - self.started_at.get(request, ended):.1f} s, "
                    + (
                        f"status {self.responses[request]}"
                        if request in self.responses
                        else "no response yet"
                    )
                    for request in busy
                )
                or "none"
            )
            pytest.fail(
                f"the page was still loading after {timeout:.0f} s; open: {names}"
            )


def _fresh_page(browser, server):
    context = browser.new_context(extra_http_headers={"CF-Connecting-IP": "10.99.0.1"})
    page = context.new_page()
    return context, page, Watcher(page, server.base_url)


def test_the_login_page_loads_without_errors(browser, server):
    context, page, watcher = _fresh_page(browser, server)
    try:
        page.goto(server.base_url + "/login", wait_until="load")
        watcher.wait_until_quiet(page)
        assert (
            page.locator("input[type=password]").count() >= 1
        ), "no password field on /login"
        assert watcher.problems == [], "\n".join(watcher.problems)
    finally:
        context.close()


def test_logging_in_opens_the_file_manager_without_errors(browser, server):
    context, page, watcher = _fresh_page(browser, server)
    try:
        page.goto(server.base_url + "/login", wait_until="load")
        watcher.wait_until_quiet(page)
        user_name = "qa_writer"
        password = server.users[user_name][
            0
        ]  # TEST_USERS maps name -> (password, role)
        page.locator("input[name=username], input[type=text]").first.fill(user_name)
        page.locator("input[type=password]").first.fill(password)
        page.locator("input[type=password]").first.press("Enter")
        page.wait_for_url(lambda url: "/login" not in url, timeout=30_000)
        page.wait_for_load_state("load", timeout=30_000)
        watcher.wait_until_quiet(page)
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
        page.goto(server.base_url + "/", wait_until="load")
        assert "/login" in page.url
    finally:
        context.close()
