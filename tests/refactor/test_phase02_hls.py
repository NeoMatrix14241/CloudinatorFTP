#!/usr/bin/env python3
"""
Phase 2 - HLS video streaming -> routes/hls.py.

Self-contained: only needs core. Its cache helpers are still used by
_clear_media_preview_sync until Phase 6, so app.py must import them from routes.hls.

Usage (from the project root):
    python tests/refactor/test_phase02_hls.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase02_hls.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase02_hls.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase


def check_hls(t):
    """routes/hls.py is self-contained and its helpers are reached only via import"""
    tree = tree_of("routes/hls.py")
    if tree is None:
        t.check("routes/hls.py exists", False)
        return
    local = local_module_names()
    peers = [
        m
        for m in imports_of(path_of("routes/hls.py"), local, include_nested=True)
        if m.startswith("routes.") and m != "routes.hls"
    ]
    t.check("routes/hls.py imports no other route module", not peers, str(peers))
    t.check(
        "routes/hls.py gets the app object from core (`from core import app`)",
        from_imports(tree).get("app") == "core",
    )
    problems = cross_module_users(
        ["_hls_cache_root", "_hls_read_status"], "routes/hls.py"
    )
    t.check(
        "other modules use the HLS cache helpers only via `from routes.hls import ...`",
        not problems,
        "\n".join(problems),
    )
    t.check(
        "`from paths import get_hls_cache_dir as _get_hls_cache_dir` moved with the helpers",
        from_imports(tree).get("_get_hls_cache_dir") == "paths",
    )


if __name__ == "__main__":
    sys.exit(run_phase(2, extra=[check_hls]))
