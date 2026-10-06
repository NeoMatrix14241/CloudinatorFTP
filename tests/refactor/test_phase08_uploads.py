#!/usr/bin/env python3
"""
Phase 8 - uploads, chunks, assembly, cleanup schedulers -> routes/uploads.py.

Threads and singletons: nothing may be created twice; initialize_cleanup() stays in app.py
and must import the five start_* functions from routes.uploads.

Usage (from the project root):
    python tests/refactor/test_phase08_uploads.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase08_uploads.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase08_uploads.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase

SCHEDULERS = [
    "detect_ready_assemblies",
    "start_assembly_worker",
    "start_enhanced_cleanup_scheduler",
    "start_expired_share_cleanup_scheduler",
    "start_orphan_cleanup_scheduler",
]


def check_uploads(t):
    """singletons created once; initialize_cleanup() wired to routes.uploads"""
    for cls in ("ChunkTracker", "AssemblyQueue", "RateLimiter"):
        hits = count_calls(cls)
        t.check(
            f"{cls}() is instantiated exactly once in the project",
            len(hits) == 1,
            str(hits),
        )
    app_tree = tree_of("app.py")
    imp = from_imports(app_tree)
    bad = [n for n in SCHEDULERS if imp.get(n) != "routes.uploads"]
    t.check(
        "app.py imports the five startup functions from routes.uploads",
        not bad,
        "not imported from routes.uploads: " + ", ".join(bad),
    )
    t.check(
        "initialize_cleanup() is still defined in app.py and still called once at import",
        "initialize_cleanup" in top_level_symbols(app_tree)
        and len([c for c in count_calls("initialize_cleanup") if c[0] == "app.py"])
        == 1,
    )
    up = tree_of("routes/uploads.py")
    if up is None:
        t.check("routes/uploads.py exists", False)
        return
    t.check(
        "routes/uploads.py imports _prune_expired_shares from routes.shares",
        from_imports(up).get("_prune_expired_shares") == "routes.shares",
    )
    t.check(
        "threads are started only by the start_* functions (no Thread(...).start() at module level)",
        not [
            s
            for s in up.body
            if isinstance(s, ast.Expr) and ".start()" in ast.unparse(s)
        ],
        "module-level .start() call found in routes/uploads.py",
    )


if __name__ == "__main__":
    sys.exit(run_phase(8, extra=[check_uploads]))
