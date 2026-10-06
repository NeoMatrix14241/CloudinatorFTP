#!/usr/bin/env python3
"""
Phase 10 - login/session pages + site meta -> routes/login.py + routes/site_meta.py; app.py becomes thin.

Final acceptance: no route or hook is left in app.py, everything is registered from routes/*.

Usage (from the project root):
    python tests/refactor/test_phase10_login_final.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase10_login_final.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase10_login_final.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase


def check_final(t):
    """app.py is only a composition root"""
    routes, hooks = scan_all()
    in_app = [r["endpoint"] for r in routes if r["file"] == "app.py"]
    t.check("no route is registered in app.py any more", not in_app, ", ".join(in_app))
    hk = [f"{h['kind']}:{h['func']}" for h in hooks if h["file"] == "app.py"]
    t.check("no hook is registered in app.py any more", not hk, ", ".join(hk))
    tree = tree_of("app.py")
    defs = sorted(
        k
        for k, (kind, _l) in top_level_symbols(tree).items()
        if kind in ("def", "class")
    )
    t.check(
        "app.py defines nothing except initialize_cleanup()",
        defs == ["initialize_cleanup"],
        str(defs),
    )
    n_lines = len(path_of("app.py").read_text(encoding="utf-8").splitlines())
    t.check(
        f"app.py is now short (<= 250 lines, was 8152): {n_lines}",
        n_lines <= 250,
        str(n_lines),
    )
    local = local_module_names()
    imported = set(imports_of(path_of("app.py"), local))
    mods = [
        module_name(f)
        for f in registration_files()
        if rel(f).startswith("routes/") and f.name != "__init__.py"
    ]
    t.check(
        f"app.py imports every routes/* module ({len(mods)})",
        set(mods) <= imported,
        "not imported: " + ", ".join(sorted(set(mods) - imported)),
    )
    outside = [
        r["endpoint"]
        for r in routes
        if not (r["file"].startswith("routes/") or r["file"] == "middleware.py")
    ]
    t.check(
        "every route lives in routes/* (the CORS preflight in middleware.py is the one exception)",
        not outside,
        ", ".join(outside),
    )
    t.info(
        "Now: update README / CLAUDE.md 'Architecture & Module Map', run the full runtime comparison, and click through the app by hand (login, upload, share link, video, image, version history)."
    )


if __name__ == "__main__":
    sys.exit(run_phase(10, extra=[check_final]))
