#!/usr/bin/env python3
"""
Phase 6 - stats/SSE/health/search/speedtest -> routes/stats.py; rebuild cache + clear media preview -> routes/admin.py.

Holds the only before_serving hook and imports HLS/image cache helpers (Phases 2 and 3 must be done).

Usage (from the project root):
    python tests/refactor/test_phase06_stats_admin.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase06_stats_admin.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase06_stats_admin.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase


def check_stats_admin(t):
    """before_serving watchdog, one file monitor, media-preview helper imports"""
    _routes, hooks = scan_all()
    bs = [h for h in hooks if h["kind"] == "before_serving"]
    t.check(
        "the event-loop watchdog (_start_loop_watchdog) is the only before_serving hook, in routes/stats.py",
        len(bs) == 1
        and bs[0]["func"] == "_start_loop_watchdog"
        and bs[0]["file"] == "routes/stats.py",
        str(bs),
    )
    t.check(
        "init_file_monitor() is still called exactly once (stats must use core.file_monitor)",
        len(count_calls("init_file_monitor")) == 1,
        str(count_calls("init_file_monitor")),
    )
    admin = tree_of("routes/admin.py")
    if admin is None:
        t.check("routes/admin.py exists", False)
        return
    imp = from_imports(admin)
    need = {
        "_hls_cache_root": "routes.hls",
        "_hls_read_status": "routes.hls",
        "_img_cache_root": "routes.image_preview",
        "_img_conv_events": "routes.image_preview",
        "_img_events_mutex": "routes.image_preview",
    }
    bad = [
        f"{k} should come from {v}, comes from {imp.get(k)}"
        for k, v in need.items()
        if imp.get(k) != v
    ]
    t.check(
        "routes/admin.py imports the HLS/image cache helpers from their own modules",
        not bad,
        "\n".join(bad),
    )
    t.check(
        "_rebuild_state and _rebuild_state_lock exist once, in routes/admin.py",
        all(
            [f for f, _k, _l in symbol_index().get(s, [])] == ["routes/admin.py"]
            for s in ("_rebuild_state", "_rebuild_state_lock")
        ),
    )


if __name__ == "__main__":
    sys.exit(run_phase(6, extra=[check_stats_admin]))
