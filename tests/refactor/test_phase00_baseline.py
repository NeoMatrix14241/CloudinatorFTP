#!/usr/bin/env python3
"""
Phase 0 - baseline, documentation and test harness (no app code moved).

Proves the starting point is sane: baseline_routes.json matches the pristine app.py,
every route/symbol is assigned to exactly one phase, all phase scripts exist, and
CLAUDE.md carries the split map.

Usage (from the project root):
    python tests/refactor/test_phase00_baseline.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase00_baseline.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase00_baseline.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase


def check_baseline_integrity(t):
    """baseline_routes.json matches the pristine app.py"""
    base = load_baseline()
    t.check(
        "baseline has 85 route endpoints and 11 hooks (as recorded on 2026-10-06)",
        len(base["routes"]) == 85 and sum(len(v) for v in base["hooks"].values()) == 11,
        f"routes={len(base['routes'])} hooks={sum(len(v) for v in base['hooks'].values())}",
    )
    started = [n for n in NEW_TOP if path_of(n).exists()] + [
        d for d in NEW_DIRS if path_of(d).exists()
    ]
    if started:
        t.skip(
            "app.py hash equals the baseline",
            f"a phase already started ({', '.join(started)})",
        )
    else:
        same = (
            sha_normalized(path_of("app.py"))
            == base["meta"]["app_py_sha256_normalized"]
        )
        t.check(
            "app.py is byte-identical (newline-normalised) to the snapshot",
            same,
            "app.py changed since the snapshot. Before Phase 1 run:\n"
            "  python tests/refactor/snapshot_baseline.py   and commit the new baseline_routes.json",
        )


def check_phase_table(t):
    """phases.py covers every route and every top-level symbol exactly once"""
    base = load_baseline()
    owner = {}
    twice = []
    for n, ph in PHASES.items():
        for ep in ph["routes"]:
            if ep in owner:
                twice.append(f"route {ep}: phases {owner[ep]} and {n}")
            owner[ep] = n
    t.check(
        "every baseline route endpoint is owned by exactly one phase",
        set(owner) == set(base["routes"]) and not twice,
        f"unowned={sorted(set(base['routes']) - set(owner))} unknown={sorted(set(owner) - set(base['routes']))} dup={twice}",
    )
    sym_owner, dup = {}, []
    for n, ph in PHASES.items():
        for s in ph["symbols"]:
            if s in sym_owner:
                dup.append(f"{s}: phases {sym_owner[s]} and {n}")
            sym_owner[s] = n
    leftover = set(base["top_level_symbols"]) - set(sym_owner) - {"initialize_cleanup"}
    t.check(
        "every top-level function/class/global of the pristine app.py is owned by a phase",
        not leftover and not dup,
        f"unowned={sorted(leftover)[:20]} dup={dup[:10]}",
    )
    missing = [
        ph["test"] for ph in PHASES.values() if not (HERE / ph["test"]).is_file()
    ]
    t.check(
        "one test script exists per phase (0..10)",
        not missing,
        "missing: " + ", ".join(missing),
    )
    for needed in (
        "run_phase_tests.py",
        "handoff.py",
        "snapshot_baseline.py",
        "common.py",
        "phases.py",
    ):
        t.check(f"tests/refactor/{needed} present", (HERE / needed).is_file())


def check_documentation(t):
    """CLAUDE.md carries the map, the phase table and the handoff prompt"""
    p = claude_md_path()
    if not p.is_file():
        t.check("CLAUDE.md found (project root or docs/)", False)
        return
    text = p.read_text(encoding="utf-8")
    for marker in (
        "app.py SPLIT MAP",
        "PHASE TABLE",
        "HANDOFF PROMPT",
        "ENDPOINT-NAME DEPENDENCIES",
        "HOOK ORDER",
        "STARTUP SIDE EFFECTS",
        "tests/refactor",
    ):
        t.check(f"CLAUDE.md contains '{marker}'", marker in text)
    import re

    m = re.search(r"\*\*Version\*\*: (\d+)\.(\d+)", text)
    t.check(
        "CLAUDE.md version is 4.68 or newer",
        bool(m) and (int(m.group(1)), int(m.group(2))) >= (4, 68),
        str(m.group(0) if m else "no version line"),
    )


if __name__ == "__main__":
    sys.exit(
        run_phase(
            0, extra=[check_baseline_integrity, check_phase_table, check_documentation]
        )
    )
