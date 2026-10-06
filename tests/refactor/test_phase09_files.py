#!/usr/bin/env python3
"""
Phase 9 - browse, download, file operations, bulk jobs -> routes/files.py.

Holds the catch-all /<path:path> route (endpoint 'index'), which validate_session special-cases by name.

Usage (from the project root):
    python tests/refactor/test_phase09_files.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase09_files.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase09_files.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase


def check_files(t):
    """catch-all route, shared download state and bulk-job registry"""
    routes, _ = scan_all()
    table = route_table(routes)
    idx = table.get("index")
    t.check(
        "endpoint 'index' serves both '/' (defaults path='') and '/<path:path>' from routes/files.py",
        bool(idx)
        and idx["files"] == {"routes/files.py"}
        and sorted(r["rule"] for r in idx["rules"]) == ["/", "/<path:path>"],
        str(idx),
    )
    for g in (
        "bulk_zip_progress",
        "bulk_zip_cancelled",
        "_bulk_jobs",
        "_bulk_jobs_lock",
    ):
        locs = symbol_index().get(g, [])
        t.check(
            f"{g} exists exactly once (two copies = bulk download progress and cancel stop talking to each other)",
            len(locs) == 1,
            str(locs),
        )
    fl = tree_of("routes/files.py")
    if fl is not None:
        imp = from_imports(fl)
        t.check(
            "routes/files.py uses the shared bulk_zip_* dicts from core, not its own copies",
            imp.get("bulk_zip_progress") == "core"
            and imp.get("bulk_zip_cancelled") == "core",
            f"{imp.get('bulk_zip_progress')} / {imp.get('bulk_zip_cancelled')}",
        )
        t.check(
            "_trigger_reconcile comes from core (one reconcile gate for the whole app)",
            imp.get("_trigger_reconcile") == "core",
        )


if __name__ == "__main__":
    sys.exit(run_phase(9, extra=[check_files]))
