"""
Tests of the three 5.41 upload settings, read from the source with `ast` (config.py and core.py
cannot be imported in the test process):

  BODY_TIMEOUT             seconds Quart gives one request body; default 600, 0 = no limit
  UPLOAD_TIMING_ENABLED    stage timings + event-loop lag probe; default OFF
  UPLOAD_CHUNKS_IN_MEMORY  chunk-sized bodies parsed in RAM; default OFF

CODING_GUIDELINES.md 22.4: a setting that is not saved and loaded is lost on the next start, and
a default that changes silently changes the server's behaviour.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "config.py"
CORE = ROOT / "core.py"
KEYS = ("BODY_TIMEOUT", "UPLOAD_TIMING_ENABLED", "UPLOAD_CHUNKS_IN_MEMORY")


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _module_literals():
    values = {}
    for node in _tree(CONFIG).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in KEYS:
                values[node.targets[0].id] = ast.literal_eval(node.value)
    return values


def _function(name):
    for node in _tree(CONFIG).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    pytest.fail(f"{name}() not found in config.py")


def _string_constants(node):
    return {
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


# ---------------------------------------------------------------------------- defaults
def test_the_defaults_keep_the_new_behaviour_off_and_the_timeout_generous():
    assert _module_literals() == {
        "BODY_TIMEOUT": 600,
        "UPLOAD_TIMING_ENABLED": False,
        "UPLOAD_CHUNKS_IN_MEMORY": False,
    }


# ---------------------------------------------------------------------------- persistence
@pytest.mark.parametrize("key", KEYS)
def test_every_setting_is_saved(key):
    assert key in _string_constants(_function("save_server_config"))


@pytest.mark.parametrize("key", KEYS)
def test_every_setting_is_loaded_and_declared_global(key):
    load = _function("load_server_config")
    assert key in _string_constants(load)
    declared = {
        name for n in ast.walk(load) if isinstance(n, ast.Global) for name in n.names
    }
    assert key in declared, "without `global` the loaded value never reaches the module"


@pytest.mark.parametrize("key", KEYS)
def test_every_setting_is_shown_in_the_settings_view(key):
    view = _function("view_current_settings")
    names = {n.id for n in ast.walk(view) if isinstance(n, ast.Name)}
    assert key in names


# ---------------------------------------------------------------------------- validation
def _validator():
    node = _function("_non_negative_number")
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(CONFIG), "exec"), namespace)
    return namespace["_non_negative_number"]


@pytest.mark.parametrize(
    "value, expected",
    [(0, 0), (1, 1), (600, 600), (2.5, 2.5), (-1, 600), (-0.1, 600)],
)
def test_a_number_of_at_least_zero_is_kept_anything_else_gets_the_default(
    value, expected
):
    assert _validator()(value, 600) == expected


@pytest.mark.parametrize("value", ["soon", "600", None, True, False, [], {}])
def test_a_hand_edited_wrong_type_falls_back_to_the_default(value):
    assert _validator()(value, 600) == 600


def test_load_server_config_validates_the_timeout():
    source = ast.unparse(_function("load_server_config"))
    assert "_non_negative_number(" in source


# ---------------------------------------------------------------------------- core.py wiring
def test_core_gives_quart_the_timeout_and_treats_zero_as_no_limit():
    updates = [
        n
        for n in ast.walk(_tree(CORE))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "update"
        and any(k.arg == "BODY_TIMEOUT" for k in n.keywords)
    ]
    assert len(updates) == 1, "app.config.update(BODY_TIMEOUT=...) not found in core.py"
    value = next(k.value for k in updates[0].keywords if k.arg == "BODY_TIMEOUT")
    assert ast.unparse(value) == "BODY_TIMEOUT or None"


def test_core_imports_the_setting_from_config():
    imported = {
        alias.name
        for node in _tree(CORE).body
        if isinstance(node, ast.ImportFrom) and node.module == "config"
        for alias in node.names
    }
    assert "BODY_TIMEOUT" in imported
