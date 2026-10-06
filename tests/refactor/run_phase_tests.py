#!/usr/bin/env python3
"""
Run the per-phase test scripts and print one summary table.

    python tests/refactor/run_phase_tests.py 3            # AFTER finishing phase 3: phases 0..3, full
    python tests/refactor/run_phase_tests.py --before 4   # BEFORE starting phase 4: phases 0..3 full +
                                                          #   phase 4 invariants only (the "gate")
    python tests/refactor/run_phase_tests.py all          # every phase 0..10 (final acceptance)
    python tests/refactor/run_phase_tests.py --status     # which phases are done (no test detail)

Extra flags: -q (summary only), -v (show every test's output even when it passes),
             --runtime (also compare Quart's real url_map; scratch copy only).

Each phase script is also runnable on its own (see its docstring). Exit code is 1 if
anything failed.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from phases import PHASES  # noqa: E402


def run_one(n, pre, flags, show):
    script = HERE / PHASES[n]["test"]
    cmd = [sys.executable, str(script)] + (["--pre"] if pre else []) + flags
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    out = proc.stdout + (proc.stderr or "")
    if show == "all" or (show == "fail" and proc.returncode != 0):
        print(out)
    summary = [ln for ln in out.splitlines() if " passed, " in ln]
    return proc.returncode, (
        summary[-1].strip() if summary else "(no summary - crashed?)\n" + out[-600:]
    )


def main(argv):
    flags = [a for a in argv if a == "--runtime"]
    show = "all" if "-v" in argv else ("none" if "-q" in argv else "fail")
    args = [a for a in argv if not a.startswith("-") or a == "--before"]
    if "--status" in argv:
        import handoff

        handoff.print_status_table()
        return 0
    if "--before" in argv:
        i = argv.index("--before")
        n = int(argv[i + 1])
        plan = [(k, False) for k in range(0, n)] + [(n, True)]
        print(
            f"Gate before Phase {n}: phases 0..{n-1} must be done and intact; Phase {n} invariants must hold.\n"
        )
    else:
        nums = [a for a in args if a.isdigit() or a == "all"]
        last = 10 if (not nums or nums[0] == "all") else int(nums[0])
        plan = [(k, False) for k in range(0, last + 1)]
    results = []
    for n, pre in plan:
        code, line = run_one(n, pre, flags, show)
        results.append((n, pre, code, line))
    print("\n" + "=" * 78)
    print(f"{'phase':<7}{'mode':<6}{'result':<8}summary")
    for n, pre, code, line in results:
        print(
            f"{n:<7}{'pre' if pre else 'full':<6}{'OK' if code == 0 else 'FAIL':<8}{line}"
        )
    bad = [n for n, _p, c, _l in results if c != 0]
    print("=" * 78)
    if bad:
        print(
            f"FAILED phases: {bad}.  Re-run a single one for detail, e.g.\n"
            f"  python tests/refactor/{PHASES[bad[0]]['test']}"
        )
        return 1
    print("All requested phases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
