"""
5.44.1: the Version Engine's watcher and scanner no longer walk the whole tracked tree back to back.

Both loops run the same full pass (`_reconcile_once`: walk and stat every tracked file). The wait
between passes was a fixed 3 s (watcher) / 300 s (scanner), so on a big tree, where a pass takes
longer than that, the engine process kept the disk busy all the time, in two threads at once;
the server's own walks (Rebuild Cache) then had to share the disk with it. Now the wait after a
pass is about three times the pass (busy at most 25% of the time, capped at 15 minutes), a small
tree still polls every 3 s, and the two loops never run the pass at the same moment.

The REAL `_next_pass_wait`, `_watcher_loop` and `_scanner_loop` are cut out of version_engine.py
with `ast` (the module starts a worker process machinery and imports config) and run against a
fake clock, a fake shutdown event and a stub pass.
"""

import ast
import threading
import types
from pathlib import Path

import pytest

ENGINE_PATH = Path(__file__).resolve().parent.parent.parent / "version_engine.py"
CONSTANTS = (
    "_WATCH_POLL_INTERVAL",
    "_PASS_BUSY_FACTOR",
    "_MAX_PASS_WAIT",
    "_SLOW_PASS_SECONDS",
    "_SLOW_PASS_LOG_EVERY",
)
FUNCTIONS = ("_next_pass_wait",)
METHODS = ("_watcher_loop", "_scanner_loop", "_note_slow_pass")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def strftime(self, fmt):
        return "2026-01-01 00:00:00"


class FakeShutdown:
    """is_set() is False for `rounds` loop checks, then True; wait(x) records x."""

    def __init__(self, rounds):
        self.rounds = rounds
        self.waits = []

    def is_set(self):
        if self.rounds <= 0:
            return True
        self.rounds -= 1
        return False

    def wait(self, seconds):
        self.waits.append(seconds)


def _load(scan_interval=300):
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    body, found = [], set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets
        ):
            body.append(node)
            found |= {t.id for t in node.targets}
        elif isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            body.append(node)
            found.add(node.name)
        elif isinstance(node, ast.ClassDef) and node.name == "Engine":
            methods = [
                i
                for i in node.body
                if isinstance(i, ast.FunctionDef) and i.name in METHODS
            ]
            found |= {m.name for m in methods}
            body.append(
                ast.ClassDef(
                    name="Probe", bases=[], keywords=[], body=methods, decorator_list=[]
                )
            )
    assert found == set(CONSTANTS) | set(FUNCTIONS) | set(METHODS), found
    clock = Clock()
    namespace = {
        "time": clock,
        "config": types.SimpleNamespace(VERSION_SCAN_INTERVAL=scan_interval),
        "_is_lock_error": lambda e: False,
    }
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    exec(compile(module, str(ENGINE_PATH), "exec"), namespace)  # noqa: S102
    return namespace, clock


def _engine(namespace, clock, rounds, pass_seconds, pass_lock=None):
    probe = namespace["Probe"]()
    probe.log = types.SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    probe._shutdown_event = FakeShutdown(rounds)
    probe._stop_scheduling = threading.Event()
    probe._pass_lock = pass_lock or threading.Lock()
    probe._set_meta = lambda *a, **k: None
    probe._retry_locked = lambda fn, *a, **k: None
    probe.run_gc = lambda: None
    probe.passes = 0
    probe.lock_held_during_pass = []

    def one_pass():
        probe.passes += 1
        probe.lock_held_during_pass.append(probe._pass_lock.locked())
        clock.now += pass_seconds

    probe._reconcile_once = one_pass
    return probe


@pytest.mark.parametrize(
    ("base", "took", "expected"),
    [
        (3, 0.2, 3),  # a small tree: unchanged
        (3, 1.0, 3),  # 3 x 1 s = 3 s
        (3, 40, 120),  # a 40 s pass: wait 2 minutes, i.e. busy 25% of the time
        (300, 40, 300),  # the scanner's own interval is a floor too
        (300, 200, 600),
        (3, 100000, 900),  # capped at 15 minutes
        (3, 0, 3),
    ],
)
def test_the_wait_after_a_pass_is_proportional_to_the_pass(base, took, expected):
    namespace, _clock = _load()
    assert namespace["_next_pass_wait"](base, took) == expected


def test_a_cap_below_the_base_interval_never_shortens_the_configured_wait():
    namespace, _clock = _load()
    # a scanner interval longer than the cap keeps its own length
    assert namespace["_next_pass_wait"](3600, 10) == 3600


def test_the_watcher_waits_longer_after_a_slow_pass():
    namespace, clock = _load()
    probe = _engine(namespace, clock, rounds=2, pass_seconds=40)
    probe._watcher_loop()
    assert probe._shutdown_event.waits == [120, 120]
    assert probe.passes == 2


def test_a_fast_watcher_pass_still_polls_every_three_seconds():
    namespace, clock = _load()
    probe = _engine(namespace, clock, rounds=3, pass_seconds=0.05)
    probe._watcher_loop()
    assert probe._shutdown_event.waits == [3, 3, 3]


def test_the_watcher_skips_its_round_while_the_scanner_runs_the_same_pass():
    namespace, clock = _load()
    held = threading.Lock()
    held.acquire()  # the scanner is in the middle of a pass
    probe = _engine(namespace, clock, rounds=2, pass_seconds=1, pass_lock=held)
    probe._watcher_loop()
    assert probe.passes == 0
    assert probe._shutdown_event.waits == [3, 3]
    assert held.locked()  # and it did not release the scanner's lock


def test_the_watcher_releases_the_pass_lock_even_when_the_pass_fails():
    namespace, clock = _load()
    probe = _engine(namespace, clock, rounds=1, pass_seconds=1)

    def boom():
        raise OSError("disk went away")

    probe._reconcile_once = boom
    probe._watcher_loop()  # logs the error, must not raise
    assert not probe._pass_lock.locked()
    assert probe._shutdown_event.waits == [3]


def test_the_scanner_holds_the_pass_lock_during_its_pass_and_waits_in_proportion():
    namespace, clock = _load(scan_interval=300)
    probe = _engine(namespace, clock, rounds=2, pass_seconds=200)
    probe._scanner_loop()
    assert probe.lock_held_during_pass == [True, True]
    assert not probe._pass_lock.locked()
    assert probe._shutdown_event.waits == [600, 600]


def test_the_scanner_keeps_its_configured_interval_for_a_fast_pass():
    namespace, clock = _load(scan_interval=300)
    probe = _engine(namespace, clock, rounds=1, pass_seconds=2)
    probe._scanner_loop()
    assert probe._shutdown_event.waits == [300]


def test_nothing_runs_while_scheduling_is_stopped():
    namespace, clock = _load()
    probe = _engine(namespace, clock, rounds=2, pass_seconds=1)
    probe._stop_scheduling.set()
    probe._watcher_loop()
    probe._shutdown_event.rounds = 1
    probe._scanner_loop()
    assert probe.passes == 0
