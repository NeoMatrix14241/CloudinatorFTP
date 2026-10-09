# tests/refactor - gates for the app.py split

Static (AST) tests, one script per phase. Full documentation: CLAUDE.md, section "app.py SPLIT MAP".

    pip install pyflakes                                  # once (undefined-name check)
    python tests/refactor/run_phase_tests.py --before 1   # may I start phase 1?
    python tests/refactor/test_phase01_core_middleware.py # after finishing phase 1
    python tests/refactor/run_phase_tests.py 1            # phases 0..1 (regression)
    python tests/refactor/run_phase_tests.py all          # final acceptance
    python tests/refactor/handoff.py                      # status + message for a new chat
    python tests/refactor/stub_probe.py --out after.json --http   # runtime state vs stand-in modules (no real data touched)
    python tests/refactor/stub_probe.py --compare before.json after.json
    python tests/refactor/pack_kit.py                     # whole folder -> ONE file refactor_kit.py (attach it to a new chat)
    python refactor_kit.py                                # (in the other chat) unpack it to tests/refactor/

Files: common.py (checks), phases.py (phase table: single source of truth), baseline_routes.json
(frozen from the pristine 4.67 app.py; re-run snapshot_baseline.py ONLY before Phase 1 if app.py
changed), snapshot_baseline.py, run_phase_tests.py, handoff.py, test_phaseNN_*.py.

If you move a symbol to a different phase/module, edit phases.py and the CLAUDE.md map in the same commit.
The tests never import app.py. `--runtime` (optional) imports it and must be run in a scratch copy.