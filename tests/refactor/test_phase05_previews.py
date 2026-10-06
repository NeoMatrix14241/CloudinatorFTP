#!/usr/bin/env python3
"""
Phase 5 - Office + archive preview -> routes/previews.py.

Usage (from the project root):
    python tests/refactor/test_phase05_previews.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase05_previews.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase05_previews.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase


def check_previews(t):
    """routes/previews.py keeps the blocking *_sync helpers as plain functions"""
    tree = tree_of("routes/previews.py")
    if tree is None:
        t.check("routes/previews.py exists", False)
        return
    syms = top_level_symbols(tree)
    t.check(
        "_office_preview_sync and _archive_preview_sync are plain `def` (run in a thread, not on the loop)",
        syms.get("_office_preview_sync", ("",))[0] == "def"
        and syms.get("_archive_preview_sync", ("",))[0] == "def",
    )
    local = local_module_names()
    peers = [
        m
        for m in imports_of(path_of("routes/previews.py"), local, include_nested=True)
        if m.startswith("routes.") and m != "routes.previews"
    ]
    t.check("routes/previews.py imports no other route module", not peers, str(peers))
    t.check(
        "blocking helpers are still offloaded (asyncio.to_thread used in the module)",
        any(
            ast.unparse(n.func) == "asyncio.to_thread"
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        ),
    )


if __name__ == "__main__":
    sys.exit(run_phase(5, extra=[check_previews]))
