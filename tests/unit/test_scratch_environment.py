"""
Tests of two helpers in tests/conftest.py (5.42), read with `ast` (conftest cannot be imported
as a module by name):

  child_gil_environment()            the GIL setting a scratch server inherits: PYTHON_GIL=0 only
                                     when the test run is a free-threaded build WITHOUT the GIL,
                                     nothing on a standard build (PYTHON_GIL=0 is a startup error
                                     there) and nothing when a free-threaded build runs WITH the GIL
  scratch_config_from_environment()  CLOUDINATOR_SCRATCH_CONFIG, a JSON object merged into the
                                     server_config.json of every scratch server (A/B switch for the
                                     performance baselines); explicit fixture config still wins

The suite must give the same verdicts on python3.14 and python3.14t, so every build / GIL
combination is exercised here with stand-ins, whatever interpreter runs the test.
"""

import ast
import json
import os
import types
from pathlib import Path

import pytest

CONFTEST = Path(__file__).resolve().parent.parent / "conftest.py"


def _tree():
    return ast.parse(CONFTEST.read_text(encoding="utf-8"))


def _function(name):
    found = next(
        (
            node
            for node in _tree().body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ),
        None,
    )
    if found is None:
        pytest.fail(f"{name}() not found in tests/conftest.py")
    return found


def _load(name, **namespace):
    module = ast.Module(body=[_function(name)], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = dict(namespace)
    exec(compile(module, str(CONFTEST), "exec"), scope)
    return scope[name]


def _gil_helper(free_threaded, gil_enabled="absent"):
    """child_gil_environment() with a stand-in `sysconfig` and `sys`."""
    sysconfig = types.SimpleNamespace(
        get_config_var=lambda key: (
            1 if (key == "Py_GIL_DISABLED" and free_threaded) else 0
        )
    )
    sys = types.SimpleNamespace()
    if gil_enabled != "absent":
        sys._is_gil_enabled = lambda: gil_enabled
    return _load("child_gil_environment", sysconfig=sysconfig, sys=sys)


# ---------------------------------------------------------------------------- GIL parity
def test_a_standard_build_gets_no_gil_setting():
    """PYTHON_GIL=0 on a standard build stops the interpreter at startup."""
    assert _gil_helper(free_threaded=False, gil_enabled=True)() == {}
    assert _gil_helper(free_threaded=False)() == {}  # not even _is_gil_enabled exists


def test_a_free_threaded_build_running_without_the_gil_passes_it_on():
    assert _gil_helper(free_threaded=True, gil_enabled=False)() == {"PYTHON_GIL": "0"}


def test_a_free_threaded_build_running_with_the_gil_sets_nothing():
    assert _gil_helper(free_threaded=True, gil_enabled=True)() == {}


def test_a_free_threaded_build_without_the_query_function_sets_nothing():
    assert _gil_helper(free_threaded=True)() == {}


def test_on_this_interpreter_the_answer_is_consistent_with_its_build():
    import sys
    import sysconfig

    result = _load("child_gil_environment", sysconfig=sysconfig, sys=sys)()
    if not sysconfig.get_config_var("Py_GIL_DISABLED"):
        assert result == {}
    else:
        assert result in ({}, {"PYTHON_GIL": "0"})
        assert (result == {"PYTHON_GIL": "0"}) == (not sys._is_gil_enabled())


def test_the_scratch_server_environment_uses_the_helper():
    calls = [
        n
        for n in ast.walk(_function("start_scratch_server"))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "child_gil_environment"
    ]
    assert len(calls) == 1


# ---------------------------------------------------------------------------- CLOUDINATOR_SCRATCH_CONFIG
@pytest.fixture
def from_environment(monkeypatch):
    monkeypatch.delenv("CLOUDINATOR_SCRATCH_CONFIG", raising=False)
    return _load("scratch_config_from_environment", os=os, json=json, pytest=pytest)


def test_nothing_is_added_when_the_variable_is_unset_or_blank(
    from_environment, monkeypatch
):
    assert from_environment() == {}
    monkeypatch.setenv("CLOUDINATOR_SCRATCH_CONFIG", "   ")
    assert from_environment() == {}


def test_a_json_object_is_returned_as_it_is(from_environment, monkeypatch):
    monkeypatch.setenv(
        "CLOUDINATOR_SCRATCH_CONFIG",
        '{"UPLOAD_CHUNKS_IN_MEMORY": true, "DOWNLOAD_BUFFER_SIZE": 65536}',
    )
    assert from_environment() == {
        "UPLOAD_CHUNKS_IN_MEMORY": True,
        "DOWNLOAD_BUFFER_SIZE": 65536,
    }


@pytest.mark.parametrize("bad", ["not json", "[1, 2]", '"text"', "42", "{"])
def test_anything_but_a_json_object_stops_the_run_with_a_clear_message(
    from_environment, monkeypatch, bad
):
    monkeypatch.setenv("CLOUDINATOR_SCRATCH_CONFIG", bad)
    with pytest.raises(pytest.fail.Exception) as raised:
        from_environment()
    assert "CLOUDINATOR_SCRATCH_CONFIG" in str(raised.value)


def test_the_environment_is_merged_first_and_the_fixture_config_wins():
    updates = [
        ast.unparse(n.args[0])
        for n in ast.walk(_function("build_scratch"))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "update"
        and ast.unparse(n.func.value) == "server_cfg"
    ]
    assert updates == ["scratch_config_from_environment()", "config or {}"]
