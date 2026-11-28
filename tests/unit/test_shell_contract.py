"""
Source contract of the page shell (5.48): what static/js/index.js, shell.js, login.js and the two
templates must keep doing for the no-refresh login and logout to stay safe. No browser, no server.

index.js is ONE function (see the comment at its top) so that the shell can run it again after a
login and end it at a logout. That only works while nothing the page starts can outlive it, so:

* the export list at the end of index.js equals the top-level functions of the file (the data-fn
  dispatcher finds handlers on `window`; the functions stopped being globals when the file became a
  function) and every `data-fn` name in index.html / index.js is in it;
* the list of `window.<name> = ...` globals the page removes at its end equals what the file assigns;
* no raw `document.addEventListener` / `window.addEventListener`, no `window.setTimeout`, no own
  navigation to /login or /logout: those would outlive the page or bypass the shell. Use
  __listen / __onReady / the shadowed timers / __goLogin / logout().

shell.js and login.js never use eval, innerHTML, document.write, browser storage or cookies and add no
inline style attribute (the Content-Security-Policy has no 'unsafe-eval' and a hash allow-list for
style attributes). The templates carry the attributes the shell relies on.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX_JS = (ROOT / "static" / "js" / "index.js").read_text(encoding="utf-8")
SHELL_JS = (ROOT / "static" / "js" / "shell.js").read_text(encoding="utf-8")
LOGIN_JS = (ROOT / "static" / "js" / "login.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
LOGIN_HTML = (ROOT / "templates" / "login.html").read_text(encoding="utf-8")

# Published through __patch (restored when the page ends), not through __ownGlobals.
PATCHED = {"fetch", "_refreshCsrfToken", "_getCsrfToken"}


def _block(begin, end):
    start = INDEX_JS.index(begin) + len(begin)
    return INDEX_JS[start : INDEX_JS.index(end, start)]


def _page_body():
    """index.js without the lifecycle header (which holds the fallbacks) and the footer."""
    after_header = INDEX_JS.index("const __softReload")
    after_header = INDEX_JS.index("\n};\n", after_header) + 4
    footer = INDEX_JS.index("// 5.48 - what the page publishes")
    return INDEX_JS[after_header:footer]


def _strip_comments(js):
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$|(?<=[;{}\s])//[^\n'\"`]*$", "", js)


# ---------------------------------------------------------------------------- index.js
def test_the_file_is_one_function_that_ends_at_the_bottom():
    assert "\n(function () {\nconst __shell = " in INDEX_JS
    assert INDEX_JS.rstrip().endswith("})();")


def test_the_export_list_is_the_list_of_top_level_functions():
    declared = {
        name
        for name in re.findall(
            r"^(?:async )?function ([A-Za-z_$][\w$]*)\(", INDEX_JS, re.M
        )
        if not name.startswith("__")
    }
    exported = set(
        re.findall(
            r"[A-Za-z_$][\w$]*",
            _block(
                "// @@shell-exports-begin\n__exportGlobals({",
                "});\n// @@shell-exports-end",
            ),
        )
    )
    assert declared - exported == set(), "functions missing from the export list"
    assert exported - declared == set(), "export list names functions that do not exist"


def test_every_data_fn_name_is_exported():
    exported = set(
        re.findall(
            r"[A-Za-z_$][\w$]*",
            _block(
                "// @@shell-exports-begin\n__exportGlobals({",
                "});\n// @@shell-exports-end",
            ),
        )
    )
    wanted = set()
    for text in (
        INDEX_HTML,
        _strip_comments(INDEX_JS),
    ):  # the dispatcher's own docs name funcName
        wanted |= set(
            re.findall(r'data-fn(?:-change|-keyup|-error)?="([A-Za-z_$][\w$]*)"', text)
        )
    assert wanted, "no data-fn attributes found: the pattern is out of date"
    assert (
        wanted - exported == set()
    ), "data-fn names that no function on window answers"


def test_the_owned_globals_are_the_window_properties_the_file_assigns():
    owned = set(
        re.findall(
            r"'([^']+)'",
            _block(
                "// @@shell-owned-begin\n__ownGlobals([", "]);\n// @@shell-owned-end"
            ),
        )
    )
    assigned = set(re.findall(r"\bwindow\.([A-Za-z_$][\w$]*)\s*=(?!=)", _page_body()))
    assert (
        assigned - PATCHED - owned == set()
    ), "window.<name> = ... assignments the page never removes: add them to __ownGlobals"
    assert owned - assigned == set(), "__ownGlobals names that nothing assigns"


def test_nothing_in_the_page_body_bypasses_the_lifecycle():
    body = _strip_comments(_page_body())
    banned = (
        "document.addEventListener(",
        "window.addEventListener(",
        "document.body.addEventListener(",
        "document.removeEventListener(",
        "window.removeEventListener(",
        "window.setTimeout(",
        "window.setInterval(",
        "window.clearTimeout(",
        "window.clearInterval(",
        "window.requestAnimationFrame(",
        "URL.createObjectURL(",
        "location.reload(",
        "location.replace('/login')",
        "location.href = '/login'",
    )
    found = [b for b in banned if b in body]
    assert not found, f"use the lifecycle helpers instead of: {found}"
    # the one allowed hard navigation: logout() when the shell did not load
    assert body.count("window.location.href = LOGOUT_URL") == 1


def test_the_lifecycle_helpers_are_used_where_they_are_needed():
    body = _page_body()
    assert body.count("__listen(") >= 50
    assert "__onReady(" in body and "__goLogin()" in body and "__softReload(" in body
    assert "__createObjectURL(" in body


# ---------------------------------------------------------------------------- shell.js / login.js
def test_shell_and_login_scripts_stay_csp_clean():
    forbidden = (
        "eval(",
        "new Function",
        ".innerHTML",
        ".outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "indexedDB",
        "setAttribute('style'",
        '.setAttribute("style"',
        ".cssText",
        'style="',
        "onclick=",
    )
    for name, text in (("shell.js", SHELL_JS), ("login.js", LOGIN_JS)):
        code = _strip_comments(text)
        found = [f for f in forbidden if f in code]
        assert not found, f"{name} uses {found}"


def test_shell_js_runs_once_and_publishes_one_global():
    assert "if (window.CloudinatorShell) {" in SHELL_JS
    assert SHELL_JS.count("window.CloudinatorShell = {") == 1
    for api in (
        "createLifecycle",
        "registerPage",
        "toApp",
        "toLogin",
        "logout",
        "sessionExpired",
        "reload",
    ):
        assert re.search(rf"\b{api}\b", SHELL_JS), api


def test_a_different_user_never_reuses_a_document():
    # The cross-user rule lives in toApp() and reload(): both compare the user named by the
    # fetched page with the user this document showed, and fall back to a real navigation.
    assert SHELL_JS.count("user !== state.lastUser") == 2
    assert "usernameOf(doc)" in SHELL_JS


def test_login_js_hands_over_to_the_shell_and_registers_itself():
    assert "shell.toApp()" in LOGIN_JS
    assert "shell.registerPage(" in LOGIN_JS
    assert "'X-Requested-With': 'XMLHttpRequest'" in LOGIN_JS


def test_every_fallback_page_load_says_why():
    # A login or logout that still reloads the page must be diagnosable from the console: every
    # hardNavigate(url, why) call passes a reason, and the function logs it as "[shell] ...".
    code = _strip_comments(SHELL_JS)
    calls = re.findall(r"return hardNavigate\(([^;]*)\);", code)
    assert (
        len(calls) >= 7
    ), "the fall-back calls were not found: the pattern is out of date"
    assert all("," in call for call in calls), f"fall back without a reason: {calls}"
    assert "console.warn('[shell] falling back to a page load of '" in code


def test_a_swapped_view_is_inert_and_its_address_changes_only_when_mounted():
    # 5.48.1: the file manager is on screen before its script has run. A click on Logout in that
    # window was a plain link click (a page load), and the browser tests that logged in and then
    # acted at once raced the page script. The order below is the fix.
    code = _strip_comments(SHELL_JS)
    swap = code[code.index("async function swapTo(") :]
    swap = swap[: swap.index("function toApp(")]
    order = [
        "setAttribute('inert', '')",
        "document.body.replaceChildren(fragment)",
        "await runScripts(doc)",
        "await nextTask()",
        "window.history.replaceState(null, '', url)",
        "removeAttribute('inert')",
        "markReady()",
    ]
    positions = [swap.index(step) for step in order]
    assert positions == sorted(positions), "swapTo steps are out of order"
    assert "view === 'app'" in swap[: positions[0]]
    assert (
        "'data-shell-ready'" in code
        and "window.addEventListener('load', markReady" in code
    )


# ---------------------------------------------------------------------------- templates
def test_both_views_are_marked_and_load_the_shell_first():
    assert '<body data-shell-view="login">' in LOGIN_HTML
    assert '<body data-shell-view="app">' in INDEX_HTML
    for name, html in (("login.html", LOGIN_HTML), ("index.html", INDEX_HTML)):
        head = html[: html.index("</head>")]
        assert "js/shell.js" in head, f"{name}: shell.js must be loaded in <head>"
        tag = re.search(r"<script[^>]*js/shell\.js[^>]*>", html).group(0)
        assert (
            "integrity=" in tag
        ), f"{name}: shell.js needs its SRI hash (sri_validator --fix)"
        assert (
            " async" not in tag and " defer" not in tag and 'type="module"' not in tag
        )


def test_page_scripts_are_marked_to_run_on_every_mount():
    for name, html, script in (
        ("login.html", LOGIN_HTML, "js/login.js"),
        ("index.html", INDEX_HTML, "js/index.js"),
    ):
        tag = re.search(rf"<script[^>]*{re.escape(script)}[^>]*>", html).group(0)
        assert 'data-shell="page"' in tag, name
    for html in (LOGIN_HTML, INDEX_HTML):
        for tag in re.findall(r"<script[^>]*\ssrc=[^>]*>", html):
            if "login.js" in tag or "index.js" in tag:
                continue
            assert 'data-shell="page"' not in tag, "only the page scripts run again"


def test_persistent_nodes_exist_with_an_id_in_the_views_that_need_them():
    for html in (LOGIN_HTML, INDEX_HTML):
        assert re.search(r'<audio id="bgMusic" data-shell-persist\b', html)
    assert re.search(r'<div id="pdfjsViewerRoot" data-shell-persist>', INDEX_HTML)
    for html in (LOGIN_HTML, INDEX_HTML):
        for tag in re.findall(r"<[a-z]+[^>]*data-shell-persist[^>]*>", html):
            assert re.search(r'\sid="[^"]+"', tag), tag


def test_the_app_view_names_its_user_for_the_cross_user_rule():
    config = re.search(r'<div id="flask-config"[^>]*>', INDEX_HTML, re.S).group(0)
    assert 'data-username="{{ session.username }}"' in config


def test_the_login_view_carries_a_csrf_meta_tag():
    assert '<meta name="csrf-token" content="{{ csrf_token() }}">' in LOGIN_HTML
