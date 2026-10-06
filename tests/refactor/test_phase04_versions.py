#!/usr/bin/env python3
"""
Phase 4 - Version History routes -> routes/versions.py.

Thin wrappers over version_history.py; must not start a second Version History engine.

Usage (from the project root):
    python tests/refactor/test_phase04_versions.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase04_versions.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase04_versions.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase


def check_versions(t):
    """routes/versions.py only wraps version_history; init() stays in core"""
    tree = tree_of("routes/versions.py")
    if tree is None:
        t.check("routes/versions.py exists", False)
        return
    hits = count_calls("version_history.init")
    t.check(
        "version_history.init() is still called exactly once, and not in routes/versions.py",
        len(hits) == 1 and hits[0][0] != "routes/versions.py",
        str(hits),
    )
    t.check(
        "routes/versions.py imports version_history",
        any(
            (
                isinstance(n, ast.Import)
                and any(a.name == "version_history" for a in n.names)
            )
            or (isinstance(n, ast.ImportFrom) and n.module == "version_history")
            for n in ast.walk(tree)
        ),
    )
    routes, _ = scan_all()
    rules = sorted(r["rule"] for r in routes if r["file"] == "routes/versions.py")
    want = sorted(
        [
            "/api/versions/list",
            "/api/versions/restore",
            "/api/versions/download",
            "/download/recovered/<path:recovered_rel>",
            "/api/versions/retry",
            "/api/versions/clear-failed",
            "/api/versions/delete",
        ]
    )
    t.check(
        "the 7 Version History URLs are all served from routes/versions.py",
        rules == want,
        f"{rules}",
    )


if __name__ == "__main__":
    sys.exit(run_phase(4, extra=[check_versions]))
