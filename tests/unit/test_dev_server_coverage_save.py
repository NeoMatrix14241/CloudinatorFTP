"""
dev_server.py saves its coverage data before it ends itself (5.44.3).

The scratch server of every application test is `python dev_server.py`, stopped by manage.sh's
stop file. The watcher thread that handles that request ends the process with `os._exit(0)`, which
skips every `atexit` hook, and coverage.py saves its data from one. So the data of the whole
application server (core, storage, routes, middleware) was thrown away and the Linux coverage
report read 39 % where the real number is about 50 %: `storage.py` 5 %, `routes/uploads.py` 7 %,
for code the application tests plainly run. `_save_coverage_data()` writes the data first, only when
coverage.py is already loaded in the process (a normal start never imports it).

The function is read out of dev_server.py with `ast` (importing the file would start the application)
and run against a fake `coverage` module.
"""

import ast
import types
from pathlib import Path

import pytest

DEV = Path(__file__).resolve().parents[2] / "dev_server.py"

pytestmark = pytest.mark.skipif(not DEV.is_file(), reason="dev_server.py not found")


def _text():
    return DEV.read_text(encoding="utf-8")


def _function(name):
    source = _text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{name} not found in dev_server.py")


class _Cov:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def stop(self):
        self.calls.append("stop")

    def save(self):
        self.calls.append("save")
        if self.fail:
            raise OSError("disk full")


def _run(modules, capsys):
    namespace = {"sys": types.SimpleNamespace(modules=modules)}
    exec(_function("_save_coverage_data"), namespace)
    namespace["_save_coverage_data"]()
    return capsys.readouterr().out


def _fake_coverage(cov):
    return types.SimpleNamespace(Coverage=types.SimpleNamespace(current=lambda: cov))


def test_nothing_happens_when_coverage_is_not_loaded(capsys):
    assert _run({}, capsys) == ""


def test_the_running_measurement_is_stopped_and_then_saved(capsys):
    cov = _Cov()
    assert _run({"coverage": _fake_coverage(cov)}, capsys) == ""
    assert cov.calls == ["stop", "save"]


def test_a_loaded_coverage_without_a_running_measurement_is_left_alone(capsys):
    assert _run({"coverage": _fake_coverage(None)}, capsys) == ""


def test_a_failing_save_is_reported_and_never_stops_the_shutdown(capsys):
    cov = _Cov(fail=True)
    out = _run({"coverage": _fake_coverage(cov)}, capsys)
    assert "Could not save coverage data" in out and "disk full" in out


def test_the_save_runs_after_the_clean_up_and_before_os_exit():
    watcher = _function("_stop_file_watcher")
    shutdown = watcher.index("logging.shutdown()")
    save = watcher.index("_save_coverage_data()")
    leave = watcher.index("os._exit(0)")
    assert shutdown < save < leave, "os._exit() skips atexit: save first, then leave"


def test_a_normal_start_does_not_import_coverage():
    text = _text()
    assert "import coverage" not in text and "from coverage" not in text
