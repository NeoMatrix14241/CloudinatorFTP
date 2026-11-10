"""
Browser scenarios (5.44.3, option D of TESTING_STRATEGY.md 15): a real Chromium DOES click.

test_browser_smoke.py is a tripwire ("the page loads without errors"). This file drives the three
places where the front end has regressed in ways no HTTP test and no Node test can see:

* an upload lands on disk and shows up in the file table;
* "Overwrite all conflicts" is asked ONCE for a batch of loose files and really overwrites every one
  of them (5.43: it was remembered for nobody, and parallel 409s stacked dialogs). If the dialog
  came back for every file, the poll below would time out and the message says what was missing;
* the file table is windowed (4.31 / 4.34, VT module): a folder of hundreds of entries keeps a
  bounded number of rows mounted, and after a deep scroll the viewport shows rows, not a blank
  table (the "rubber band" family of bugs, 4.4x).

The logic behind the first two is also tested without a browser in tests/unit/test_index_js_logic.py;
what only a browser shows is that the real page wires the buttons and the queue to that logic.

OPT-IN, like the smoke test (CLOUDINATOR_SLOW_TESTS=1; the nightly workflow installs Playwright and
Chromium). It starts its OWN scratch server so that the hundreds of files it creates and the uploads
it makes never appear in the listing of another test:

    python -m pip install playwright
    python -m playwright install chromium
    CLOUDINATOR_SLOW_TESTS=1 python -m pytest tests/frontend/test_browser_flows.py -q

CLOUDINATOR_BROWSER_CHANNEL picks another installed browser (`msedge` on Windows), as in the smoke
test. Every wait is a bounded poll or a Playwright locator with a timeout, never a fixed sleep.

Not covered: drag and drop, the folder picker, mobile layouts, Firefox and Safari.
"""

import os
import time
import uuid

import pytest

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("CLOUDINATOR_SLOW_TESTS") != "1",
        reason="needs a browser and takes time: set CLOUDINATOR_SLOW_TESTS=1 to run",
    ),
]

RW = "qa_writer"
WAIT_MS = 45_000
MANY_FILES = 400


@pytest.fixture(scope="module")
def server(scratch_tools, tmp_path_factory):
    root = tmp_path_factory.mktemp("browser_flows") / "app"
    port = scratch_tools.free_port()
    scratch_tools.build(root, port=port)
    assert scratch_tools.paths_outside(root) == []
    scratch_tools.seed_users(root)
    running = scratch_tools.start_server(root, port)
    try:
        yield running
    finally:
        scratch_tools.stop_server(running)


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


@pytest.fixture()
def page(browser, server):
    """A logged-in page on the file manager, in a fresh context (own fake IP, own session)."""
    context = browser.new_context(
        extra_http_headers={"CF-Connecting-IP": "10.99.0.2"},
        viewport={"width": 1280, "height": 800},
    )
    tab = context.new_page()
    tab.set_default_timeout(WAIT_MS)
    tab.goto(server.base_url + "/login", wait_until="load")
    tab.locator("input[name=username], input[type=text]").first.fill(RW)
    tab.locator("input[type=password]").first.fill(server.users[RW][0])
    tab.locator("input[type=password]").first.press("Enter")
    tab.wait_for_url(lambda url: "/login" not in url, timeout=WAIT_MS)
    tab.wait_for_selector("#filesTableBody", state="attached")
    try:
        yield tab
    finally:
        context.close()


def _wait_for(predicate, what, timeout=60, interval=0.25):
    deadline = time.monotonic() + timeout
    result = predicate()
    while not result and time.monotonic() < deadline:
        time.sleep(interval)
        result = predicate()
    if not result:
        pytest.fail(f"timed out after {timeout}s waiting for: {what}")
    return result


def _file(name, data):
    return {"name": name, "mimeType": "application/octet-stream", "buffer": data}


def _read(path):
    try:
        return path.read_bytes()
    except OSError:
        return None  # not there yet, or momentarily busy: the poll tries again


def test_an_uploaded_file_lands_on_disk_and_appears_in_the_table(server, page):
    name = f"uploaded_{uuid.uuid4().hex[:8]}.txt"
    data = b"uploaded through the real page " * 40
    page.set_input_files("#fileInput", [_file(name, data)])
    page.locator("#startUploadBtn").click()
    _wait_for(
        lambda: _read(server.storage / name) == data, f"{name} on disk with its content"
    )
    page.reload(wait_until="load")
    page.locator("#filesTableBody tr", has_text=name).first.wait_for(state="visible")


def test_overwrite_all_is_asked_once_and_overwrites_every_loose_file(server, page):
    tag = uuid.uuid4().hex[:8]
    names = [f"conflict_{tag}_{n}.txt" for n in range(3)]
    for name in names:
        (server.storage / name).write_bytes(b"OLD " + name.encode())
    page.reload(wait_until="load")  # so the page knows the files exist
    new = {name: b"NEW " + name.encode() * 5 for name in names}
    page.set_input_files("#fileInput", [_file(n, d) for n, d in new.items()])
    page.locator("#startUploadBtn").click()

    # ONE dialog; answering it with "all" must settle the other two without another dialog
    page.locator('button[data-action="overwrite-all"]').click()
    _wait_for(
        lambda: all(_read(server.storage / n) == d for n, d in new.items()),
        "all three files overwritten after ONE 'Overwrite all conflicts' answer; on disk: "
        + str({n: _read(server.storage / n) for n in names}),
    )
    assert page.locator('button[data-action="overwrite-all"]').count() == 0


def test_a_big_folder_keeps_the_dom_small_and_a_deep_scroll_shows_rows(server, page):
    folder = server.storage / f"many_{uuid.uuid4().hex[:8]}"
    folder.mkdir()
    for n in range(MANY_FILES):
        (folder / f"file_{n:04d}.txt").write_bytes(b"x")
    page.goto(f"{server.base_url}/{folder.name}", wait_until="load")
    page.wait_for_selector("#filesTableBody tr", state="attached")

    def mounted():
        return page.locator(
            "#filesTableBody tr:not(#vtTopSpacer):not(#vtBottomSpacer)"
        ).count()

    first = mounted()
    assert 0 < first < MANY_FILES, f"{first} rows mounted for {MANY_FILES} entries"

    wrapper = page.locator("#tableScrollWrapper")
    scrollable = wrapper.evaluate("el => el.scrollHeight - el.clientHeight")
    assert scrollable > 500, "the spacer rows must make the whole folder scrollable"

    for target in (scrollable // 2, scrollable):
        wrapper.evaluate("(el, top) => { el.scrollTop = top; }", target)
        page.wait_for_function(
            """() => {
                const w = document.getElementById('tableScrollWrapper');
                const box = w.getBoundingClientRect();
                return [...document.querySelectorAll('#filesTableBody tr')]
                    .filter(r => r.id !== 'vtTopSpacer' && r.id !== 'vtBottomSpacer')
                    .some(r => {
                        const b = r.getBoundingClientRect();
                        return b.height > 0 && b.bottom > box.top && b.top < box.bottom;
                    });
            }""",
            timeout=WAIT_MS,
        )
        assert mounted() < MANY_FILES, "scrolling must not mount the whole folder"
