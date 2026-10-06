#!/usr/bin/env python3
"""
Phase 3 - image preview/conversion -> routes/image_preview.py.

Self-contained: only needs core. Its cache globals are still used by
_clear_media_preview_sync until Phase 6, so app.py must import them from routes.image_preview.

Usage (from the project root):
    python tests/refactor/test_phase03_image_preview.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase03_image_preview.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase03_image_preview.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase


def check_image_preview(t):
    """routes/image_preview.py is self-contained and its globals are reached only via import"""
    tree = tree_of("routes/image_preview.py")
    if tree is None:
        t.check("routes/image_preview.py exists", False)
        return
    local = local_module_names()
    peers = [
        m
        for m in imports_of(
            path_of("routes/image_preview.py"), local, include_nested=True
        )
        if m.startswith("routes.") and m != "routes.image_preview"
    ]
    t.check(
        "routes/image_preview.py imports no other route module", not peers, str(peers)
    )
    t.check(
        "routes/image_preview.py gets the app object from core",
        from_imports(tree).get("app") == "core",
    )
    problems = cross_module_users(
        ["_img_cache_root", "_img_conv_events", "_img_events_mutex"],
        "routes/image_preview.py",
    )
    t.check(
        "other modules use the image cache globals only via `from routes.image_preview import ...`",
        not problems,
        "\n".join(problems),
    )
    for lock in ("_img_status_lock", "_img_events_mutex"):
        t.check(
            f"{lock} is defined once (a second copy would silently stop protecting anything)",
            len(symbol_index().get(lock, [])) == 1,
            str(symbol_index().get(lock)),
        )


if __name__ == "__main__":
    sys.exit(run_phase(3, extra=[check_image_preview]))
