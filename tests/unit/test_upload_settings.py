"""
Tests of the 5.41 upload settings and the 5.42 download setting, read from the source with `ast`
(config.py and core.py cannot be imported in the test process):

  BODY_TIMEOUT             seconds Quart gives one request body; default 600, 0 = no limit
  UPLOAD_TIMING_ENABLED    stage timings + event-loop lag probe; default OFF
  UPLOAD_CHUNKS_IN_MEMORY  chunk-sized bodies parsed in RAM; default ON since 5.43 (was OFF)
  DOWNLOAD_BUFFER_SIZE     bytes read per step when a file is sent; default 1 MiB (5.42)

5.43 adds the menu (Server Configuration > 14, configure_transfer_performance): the real menu
functions are run with a scripted `input()`, and a loaded value still wins over the default.

CODING_GUIDELINES.md 22.4: a setting that is not saved and loaded is lost on the next start, and
a default that changes silently changes the server's behaviour.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "config.py"
CORE = ROOT / "core.py"
KEYS = (
    "BODY_TIMEOUT",
    "UPLOAD_TIMING_ENABLED",
    "UPLOAD_CHUNKS_IN_MEMORY",
    "DOWNLOAD_BUFFER_SIZE",
)


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
    found = next(
        (
            node
            for node in _tree(CONFIG).body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ),
        None,
    )
    if found is None:
        pytest.fail(f"{name}() not found in config.py")
    return found


def _string_constants(node):
    return {
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


# ---------------------------------------------------------------------------- defaults
def test_the_defaults_parse_chunks_in_ram_and_keep_the_timing_log_off():
    assert _module_literals() == {
        "BODY_TIMEOUT": 600,
        "UPLOAD_TIMING_ENABLED": False,
        "UPLOAD_CHUNKS_IN_MEMORY": True,
        "DOWNLOAD_BUFFER_SIZE": 1048576,
    }


def test_a_value_saved_in_server_config_json_still_wins_over_the_new_default():
    """An owner whose server_config.json holds UPLOAD_CHUNKS_IN_MEMORY: false keeps false: the
    loader passes the module's own value only as the fallback of config.get()."""
    source = ast.unparse(_function("load_server_config"))
    assert "config.get('UPLOAD_CHUNKS_IN_MEMORY', UPLOAD_CHUNKS_IN_MEMORY)" in source


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


# ---------------------------------------------------------------------------- download buffer (5.42)
def _buffer_validator():
    node = _function("_buffer_size_or_default")
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(CONFIG), "exec"), namespace)
    return namespace["_buffer_size_or_default"]


@pytest.mark.parametrize(
    "value, expected",
    [
        (8192, 8192),
        (65536, 65536),
        (1048576, 1048576),
        (16 * 1024 * 1024, 16 * 1024 * 1024),
        (8191, 1048576),
        (0, 1048576),
        (-1, 1048576),
        (16 * 1024 * 1024 + 1, 1048576),
    ],
)
def test_a_buffer_size_inside_the_bounds_is_kept_else_the_default(value, expected):
    assert _buffer_validator()(value, 1048576) == expected


@pytest.mark.parametrize("value", ["1048576", None, True, False, 1.5e6, [], {}])
def test_a_hand_edited_wrong_type_gets_the_default_buffer_size(value):
    assert _buffer_validator()(value, 1048576) == 1048576


def test_load_server_config_validates_the_buffer_size():
    assert "_buffer_size_or_default(" in ast.unparse(_function("load_server_config"))


def test_core_applies_the_download_buffer_to_the_app():
    calls = [
        n
        for n in ast.walk(_tree(CORE))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "use_file_buffer"
    ]
    assert len(calls) == 1
    assert [ast.unparse(a) for a in calls[0].args] == ["app", "DOWNLOAD_BUFFER_SIZE"]
    imported = {
        alias.name
        for node in _tree(CORE).body
        if isinstance(node, ast.ImportFrom) and node.module == "helpers.file_body"
        for alias in node.names
    }
    assert imported == {"use_file_buffer"}
    from_config = {
        alias.name
        for node in _tree(CORE).body
        if isinstance(node, ast.ImportFrom) and node.module == "config"
        for alias in node.names
    }
    assert "DOWNLOAD_BUFFER_SIZE" in from_config


# ---------------------------------------------------------------------------- the menu (5.43)
def test_the_server_menu_offers_the_performance_entry():
    source = ast.unparse(_function("configure_server_settings"))
    assert "choice == '14'" in source
    assert "configure_transfer_performance()" in source
    assert "(0-14)" in source, "the prompt must say the new range"


def _run_menu(answers, buffer_size=1048576, in_ram=True, timing=False):
    """configure_transfer_performance() with a scripted input(); returns (globals, printed)."""
    names = (
        "format_bytes",
        "_buffer_size_or_default",
        "configure_transfer_performance",
        "_configure_download_buffer",
    )
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    ast.fix_missing_locations(module)
    script, printed = iter(answers), []
    namespace = {
        "input": lambda prompt="": next(script),
        "print": lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        "UPLOAD_CHUNKS_IN_MEMORY": in_ram,
        "UPLOAD_TIMING_ENABLED": timing,
        "DOWNLOAD_BUFFER_SIZE": buffer_size,
    }
    exec(compile(module, str(CONFIG), "exec"), namespace)
    namespace["configure_transfer_performance"]()
    return namespace, "\n".join(printed)


def test_the_menu_toggles_the_ram_parse_and_back():
    assert _run_menu(["1", "0"])[0]["UPLOAD_CHUNKS_IN_MEMORY"] is False
    assert _run_menu(["1", "1", "0"])[0]["UPLOAD_CHUNKS_IN_MEMORY"] is True


def test_the_menu_toggles_the_timing_log():
    assert _run_menu(["2", "0"])[0]["UPLOAD_TIMING_ENABLED"] is True
    assert _run_menu(["2", "0"], timing=True)[0]["UPLOAD_TIMING_ENABLED"] is False


@pytest.mark.parametrize(
    "preset, expected",
    [("1", 64 * 1024), ("2", 256 * 1024), ("3", 1024 * 1024), ("4", 4 * 1024 * 1024)],
)
def test_the_menu_sets_a_download_read_size_preset(preset, expected):
    namespace, _ = _run_menu(["3", preset, "0"], buffer_size=8192)
    assert namespace["DOWNLOAD_BUFFER_SIZE"] == expected


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("512", 512 * 1024),
        ("8", 8192),  # the lower bound
        ("16384", 16 * 1024 * 1024),  # the upper bound
        ("7", 65536),  # below 8 KB: refused, nothing changes
        ("16385", 65536),  # above 16 MB: refused
        ("0", 65536),
        ("-5", 65536),
        ("1.5", 65536),
        ("big", 65536),
        ("", 65536),
    ],
)
def test_a_custom_download_read_size_is_checked_against_the_bounds(typed, expected):
    namespace, printed = _run_menu(["3", "5", typed, "0"], buffer_size=65536)
    assert namespace["DOWNLOAD_BUFFER_SIZE"] == expected
    if expected == 65536:
        assert "Size must be" in printed


def test_keeping_the_current_read_size_and_a_bad_choice_change_nothing():
    namespace, printed = _run_menu(["3", "6", "3", "9", "x", "0"], buffer_size=65536)
    assert namespace["DOWNLOAD_BUFFER_SIZE"] == 65536
    assert "Invalid option" in printed
