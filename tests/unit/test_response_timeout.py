"""
Quart caps the TOTAL time a response may take to send (RESPONSE_TIMEOUT, default 60 s); it is not
an idle timeout. Every download longer than a minute end to end (a big file through the Cloudflare
tunnel) was therefore cut off mid-stream. core.py switches the cap off for the app (fixed in 5.11,
CLAUDE.md part 61); this test keeps it that way.

The file is only PARSED here; the application is never imported.
"""

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent.parent / "core.py"
SIX_HOURS = 6 * 3600


def _config_updates():
    """Every keyword given to app.config.update(...) in core.py, as {name: ast node}."""
    found = {}
    for node in ast.walk(ast.parse(CORE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "app.config.update":
            for kw in node.keywords:
                found[kw.arg] = kw.value
    return found


def test_core_configures_the_app_in_one_update_call():
    assert "SESSION_COOKIE_NAME" in _config_updates()  # the parser found the right call


def test_the_response_timeout_does_not_cut_long_downloads():
    value = _config_updates().get("RESPONSE_TIMEOUT")
    assert (
        value is not None
    ), "RESPONSE_TIMEOUT is not set: Quart's 60 s default applies"
    assert isinstance(value, ast.Constant)
    assert value.value is None or value.value >= SIX_HOURS
