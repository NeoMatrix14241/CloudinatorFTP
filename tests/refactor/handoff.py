#!/usr/bin/env python3
"""
Turnover / handoff script for the app.py split.

    python tests/refactor/handoff.py

Reads the real state of the tree (no guessing from memory): which phases are done,
whether the invariants still hold, what the next phase is and which files to give
Claude for it. Prints a ready-to-paste message for a NEW chat and saves the same text
to tests/refactor/last_handoff.md.

Run it: when you stop for the day, before you open a new chat, and whenever Claude
asks "where are we?".  CLAUDE.md (section "app.py SPLIT MAP") is the permanent map;
this script supplies the current state.
"""

import contextlib
import datetime
import io
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import (
    ROOT,
    T,
    invariants,
    phase_done,
    registration_files,
    rel,
    route_table,  # noqa: E402
    scan_all,
    load_baseline,
    path_of,
    claude_md_path,
)
from phases import PHASES  # noqa: E402


def _silent(fn, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args)


def phase_state(n):
    """'done' | 'todo' for one phase, judged from the tree."""
    if n == 0:
        md = claude_md_path()
        ok = (
            load_baseline() is not None
            and md.is_file()
            and "app.py SPLIT MAP" in md.read_text(encoding="utf-8")
        )
        return "done" if ok else "todo"
    mods = PHASES[n]["modules"]
    if not all(path_of(m).is_file() for m in mods):
        return "todo"
    t = T("x")
    _silent(phase_done, t, n)
    return "done" if t.failed == 0 and t.passed > 0 else "todo"


def all_states():
    return {n: phase_state(n) for n in PHASES}


def print_status_table():
    st = all_states()
    print(f"{'phase':<6}{'version':<9}{'state':<7}title")
    for n, ph in PHASES.items():
        print(f"{n:<6}{ph['version']:<9}{st[n]:<7}{ph['title']}")


def _git(*args):
    try:
        r = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not (ROOT / "app.py").is_file():
        print(
            f"app.py not found at {ROOT}. Place tests/refactor/ inside the project (next to app.py)."
        )
        return 1
    states = all_states()
    done = [n for n, s in states.items() if s == "done"]
    # "next" = first phase that is not done AND whose dependencies are all done
    nxt = next((n for n in PHASES if states[n] != "done"), None)

    t = T("invariants")
    base_ok = load_baseline() is not None
    if base_ok:
        _silent(invariants, t)
    fails = t.failures

    routes, hooks = scan_all()
    by_file = {}
    for r in routes:
        by_file.setdefault(r["file"], set()).add(r["endpoint"])
    sizes = {
        rel(f): len(f.read_text(encoding="utf-8").splitlines())
        for f in registration_files()
    }

    lines = []
    w = lines.append
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    head = _git("rev-parse", "--short", "HEAD")
    dirty = _git("status", "--porcelain")
    w(f"# CloudinatorFTP app.py split - handoff ({now})")
    w("")
    w(f"- Project root: `{ROOT}`")
    if head:
        w(
            f"- Git: `{head}`, {len(dirty.splitlines()) if dirty else 0} uncommitted change(s)"
            + ("  <- COMMIT BEFORE THE NEXT PHASE" if dirty else "")
        )
    w(
        f"- Phases done: {done if done else 'none'}   |   next: {('Phase %d' % nxt) if nxt is not None else 'ALL DONE'}"
    )
    w(
        f"- Invariants: {'PASS' if base_ok and not fails else ('NO BASELINE' if not base_ok else 'FAIL (' + str(len(fails)) + ')')}"
    )
    w("")
    w("## Status")
    w("")
    w("| Phase | Version | State | What |")
    w("|---|---|---|---|")
    for n, ph in PHASES.items():
        w(f"| {n} | {ph['version']} | {states[n]} | {ph['title']} |")
    w("")
    w("## Where the code lives now (lines / routes)")
    w("")
    for f, n_lines in sorted(sizes.items(), key=lambda kv: -kv[1]):
        w(f"- `{f}`: {n_lines} lines, {len(by_file.get(f, []))} route endpoint(s)")
    w("")
    if fails:
        w("## Invariant failures (fix before anything else)")
        w("")
        for name, detail in fails[:12]:
            w(f"- {name}")
            for ln in detail.splitlines()[:4]:
                w(f"    {ln}")
        w("")
    if nxt is not None:
        ph = PHASES[nxt]
        unmet = [d for d in ph["depends"] if states[d] != "done"]
        w(f"## Next: Phase {nxt} - {ph['title']}")
        w("")
        w(f"- Scope: {ph['scope']}")
        w(
            f"- Target module(s): {', '.join(ph['modules']) or '(none)'}   |   routes: {len(ph['routes'])}   |   symbols to move: {len(ph['symbols'])}"
        )
        w(
            f"- CLAUDE.md version to use: **{ph['version']}**   |   test: `python tests/refactor/{ph['test']}`"
        )
        if unmet:
            w(f"- BLOCKED: depends on phase(s) {unmet} which are not done yet.")
        need = ["CLAUDE.md", "app.py"]
        if nxt >= 2:
            need.append("core.py")
        if nxt >= 1 and path_of("middleware.py").is_file() and nxt >= 10:
            need.append("middleware.py")
        for d in ph["depends"]:
            for m in PHASES[d]["modules"]:
                if m not in need and d != 1:
                    need.append(m)
        w(
            f"- Give Claude these files: {', '.join('`%s`' % x for x in need)}  (plus the test output if something failed)"
        )
        w("")
        w("## Paste this into the new chat")
        w("")
        w("```")
        w(
            "Continue the CloudinatorFTP app.py split. CLAUDE.md is attached: read its section"
        )
        w(
            "'app.py SPLIT MAP' first (rules, target layout, phase table, hook order, startup order,"
        )
        w(
            "endpoint-name dependencies). It is the source of truth; the files below are only the code to cut."
        )
        w("")
        w(
            f"State: phases {done if done else 'none'} done; invariants {'PASS' if not fails else 'FAIL - see below'}."
        )
        w(f"Task: do Phase {nxt} - {ph['title']} (CLAUDE.md version {ph['version']}).")
        w(
            "Rules: pure move, no behaviour change, no renamed endpoints, no star imports, new modules"
        )
        w(
            "import `core` (never `app`). After the change: update CLAUDE.md (version bump, sync note at"
        )
        w(
            "the top, changelog entry, tick the phase in the PHASE TABLE, adjust the map if anything was"
        )
        w(
            "re-assigned and edit tests/refactor/phases.py to match), give me the commit message, and"
        )
        w(f"tell me to run: python tests/refactor/{ph['test']}")
        if fails:
            w("")
            w("Invariant failures right now:")
            for name, detail in fails[:6]:
                w(f"- {name}: {detail.splitlines()[0] if detail else ''}")
        w("```")
        w("")
    w("## When a phase is finished")
    w("")
    w("1. `python tests/refactor/run_phase_tests.py N` (N = the phase) - all rows OK.")
    w(
        "2. Start the server in a scratch copy, click through: login, browse, upload, download, share link, "
        "video, image preview, version history (the tests are static; they cannot prove runtime behaviour)."
    )
    w(
        "3. `./manage.sh validate-sri --fix` only if a static/templates file changed (this refactor does not touch them)."
    )
    w(
        "4. Commit with the message Claude gave you, then `python tests/refactor/handoff.py` again."
    )
    text = "\n".join(lines)
    print(text)
    (HERE / "last_handoff.md").write_text(text + "\n", encoding="utf-8")
    print(f"\n(saved to {HERE / 'last_handoff.md'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
