#!/usr/bin/env python3
"""
Phase 7 - share links (owner API, public /shared/*, admin) -> routes/shares.py.

Security-sensitive: the three anonymous POST routes must stay CSRF-exempt, the public
paths must keep their endpoint names (validate_session whitelists them by name).

Usage (from the project root):
    python tests/refactor/test_phase07_shares.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase07_shares.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase07_shares.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase

CSRF_EXEMPT = {"shared_request_access", "shared_verify_passkey", "shared_zip_selected"}
PUBLIC_ENDPOINTS = {
    "shared_download",
    "shared_verify_passkey",
    "shared_request_access",
    "shared_request_status",
    "shared_file_download",
    "shared_browse",
    "shared_download_item",
    "shared_zip_selected",
}


def check_shares(t):
    """CSRF exemptions and public endpoint names survive the move"""
    routes, _ = scan_all()
    table = route_table(routes)
    exempt = {ep for ep, e in table.items() if "csrf.exempt" in e["decorators"]}
    t.check(
        f"exactly {sorted(CSRF_EXEMPT)} are @csrf.exempt",
        exempt == CSRF_EXEMPT,
        f"now: {sorted(exempt)}",
    )
    t.check(
        "those three endpoints are registered in routes/shares.py",
        all(
            table.get(ep, {}).get("files") == {"routes/shares.py"} for ep in CSRF_EXEMPT
        ),
    )
    t.check(
        "every public /shared/* endpoint keeps its name",
        PUBLIC_ENDPOINTS <= set(table),
        "missing: " + ", ".join(sorted(PUBLIC_ENDPOINTS - set(table))),
    )
    tree = tree_of("routes/shares.py")
    if tree is None:
        return
    t.check(
        "routes/shares.py gets csrf from core (`from core import csrf`) - never a second CSRFProtect",
        from_imports(tree).get("csrf") == "core"
        and len(count_calls("CSRFProtect")) == 1,
        str(count_calls("CSRFProtect")),
    )
    t.check(
        "_prune_expired_shares is defined in routes/shares.py (Phase 8 imports it)",
        "_prune_expired_shares" in top_level_symbols(tree),
    )


if __name__ == "__main__":
    sys.exit(run_phase(7, extra=[check_shares]))
