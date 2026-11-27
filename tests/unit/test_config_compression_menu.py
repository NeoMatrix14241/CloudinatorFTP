"""
Tests for the Version Engine compression settings in the config.py menu (5.47.7):
Version Engine > Engine settings > 13, `configure_version_compression()`, and the targeted
`save_server_config_keys()` it saves with.

What they guard (the owner's rules): the menu shows the current value, the default, the allowed
range and the restart note; a save writes ONLY the keys that were changed and keeps every other
key of server_config.json (unknown keys, their order, a switch the owner set by hand, an absent
key) exactly as it is; booleans and numbers are real JSON types inside the loader's own bounds;
the menu refuses out-of-range values; the old whole-file save_server_config() is never used by
it; the owner's real server_config.json is never touched.

config.py is executed as a fresh module object per test (its module variables are changed by
the menu), WITHOUT importing the application tree: the file is read and executed from its path
under a private module name (never registered in sys.modules), `paths` is a fake that points every
directory inside tmp_path, CLOUDINATOR_FTP_ROOT sends the storage folder (which config.py creates
at import) into tmp_path, and _SERVER_CONFIG_FILE is a temporary file. Nothing real is read or
written (the autouse guard below checks the real server_config.json) and nothing is started.
"""

import builtins
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
REAL_CONFIG_FILE = ROOT / "server_config.json"

KEYS = [
    "VERSION_COMPRESSION_ENABLED",
    "VERSION_COMPRESSION_LEVEL",
    "VERSION_COMPRESSION_MIN_SAVING_PERCENT",
    "VERSION_COMPRESSION_BUSY_PERCENT",
    "VERSION_COMPRESSION_INTERVAL",
    "VERSION_COMPRESSION_DELTA_ENABLED",
    "VERSION_COMPRESSION_DELTA_MIN_GAIN_PERCENT",
]
INT_BOUNDS = {
    "VERSION_COMPRESSION_LEVEL": (1, 22),
    "VERSION_COMPRESSION_MIN_SAVING_PERCENT": (0, 50),
    "VERSION_COMPRESSION_BUSY_PERCENT": (5, 100),
    "VERSION_COMPRESSION_INTERVAL": (60, 86400),
    "VERSION_COMPRESSION_DELTA_MIN_GAIN_PERCENT": (1, 90),
}
# the menu number of each setting (the table order)
NUMBER = {key: str(n) for n, key in enumerate(KEYS, 1)}
DEFAULTS = {
    "VERSION_COMPRESSION_ENABLED": False,
    "VERSION_COMPRESSION_LEVEL": 22,
    "VERSION_COMPRESSION_MIN_SAVING_PERCENT": 5,
    "VERSION_COMPRESSION_BUSY_PERCENT": 25,
    "VERSION_COMPRESSION_INTERVAL": 600,
    "VERSION_COMPRESSION_DELTA_ENABLED": False,
    "VERSION_COMPRESSION_DELTA_MIN_GAIN_PERCENT": 20,
}

# The owner's real file today: compression ON, the delta key ABSENT (= off), unknown / other keys.
OWNER_FILE = {
    "PORT": 5000,
    "VERSION_ENGINE_ENABLED": True,
    "VERSION_TRACK_DIRECTORIES": ["C:\\Server\\SharedFolder\\QB Data 2024"],
    "VERSION_COMPRESSION_ENABLED": True,
    "SOME_HAND_ADDED_KEY": {"note": "config.py does not know this key", "n": [1, 2]},
    "VERSION_COMPRESSION_LEVEL": 22,
    "configured_at": "2026-11-20 09:00:00",
}


def _fake_paths(base):
    """Stands in for paths.py: every directory is inside `base`, nothing is read or saved."""
    module = types.ModuleType("paths")

    def getter(create=True):
        return str(base)

    for name in ("db", "cache", "hls_cache", "img_cache", "versions"):
        setattr(module, f"get_{name}_dir", getter)
        setattr(module, f"set_{name}_dir", lambda *a, **k: None)
        setattr(module, f"reset_{name}_dir", lambda *a, **k: None)
    module._load = lambda: {}
    module._save = lambda *a, **k: None
    return module


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """A fresh copy of config.py whose server_config.json lives in tmp_path."""
    monkeypatch.setitem(sys.modules, "paths", _fake_paths(tmp_path))
    monkeypatch.setenv("CLOUDINATOR_FTP_ROOT", str(tmp_path / "ftp_root"))
    spec = importlib.util.spec_from_file_location(
        "config_compression_menu_under_test", ROOT / "config.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._SERVER_CONFIG_FILE = str(tmp_path / "server_config.json")
    return mod


@pytest.fixture(autouse=True)
def real_server_config_is_never_touched():
    before = REAL_CONFIG_FILE.read_bytes() if REAL_CONFIG_FILE.is_file() else None
    yield
    after = REAL_CONFIG_FILE.read_bytes() if REAL_CONFIG_FILE.is_file() else None
    assert before == after, "a test changed the real server_config.json"


def write_file(cfg, data):
    Path(cfg._SERVER_CONFIG_FILE).write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    cfg.load_server_config()


def read_file(cfg):
    return json.loads(Path(cfg._SERVER_CONFIG_FILE).read_text(encoding="utf-8"))


def script(monkeypatch, answers):
    """Feed input() from a list; running out of answers is end-of-input (the menu leaves)."""
    queue = iter(answers)

    def fake_input(prompt=""):
        try:
            return next(queue)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(builtins, "input", fake_input)


def run_menu(cfg, monkeypatch, capsys, answers):
    script(monkeypatch, answers)
    capsys.readouterr()
    cfg.configure_version_compression()
    return capsys.readouterr().out


# ── the table and the loader agree ──────────────────────────────────────────────────────────


def test_the_table_lists_the_seven_settings_with_the_documented_defaults(cfg):
    assert [s["key"] for s in cfg.VERSION_COMPRESSION_SETTINGS] == KEYS
    assert {
        s["key"]: s["default"] for s in cfg.VERSION_COMPRESSION_SETTINGS
    } == DEFAULTS
    assert cfg.VERSION_COMPRESSION_BOUNDS == INT_BOUNDS


@pytest.mark.parametrize("key", sorted(INT_BOUNDS))
def test_the_loader_accepts_the_bounds_and_refuses_one_step_outside(cfg, key):
    """The menu's range IS the loader's range: the same table feeds both."""
    low, high = INT_BOUNDS[key]
    for value, expected in (
        (low, low),
        (high, high),
        (low - 1, DEFAULTS[key]),
        (high + 1, DEFAULTS[key]),
    ):
        setattr(cfg, key, DEFAULTS[key])  # the loader falls back to the value in memory
        write_file(cfg, {key: value})
        assert getattr(cfg, key) == expected, (key, value)


def test_the_loader_is_still_fail_safe_for_the_two_switches(cfg):
    write_file(
        cfg,
        {"VERSION_COMPRESSION_ENABLED": "true", "VERSION_COMPRESSION_DELTA_ENABLED": 1},
    )
    assert cfg.VERSION_COMPRESSION_ENABLED is False
    assert cfg.VERSION_COMPRESSION_DELTA_ENABLED is False
    write_file(cfg, {"VERSION_COMPRESSION_ENABLED": True})
    assert cfg.VERSION_COMPRESSION_ENABLED is True
    assert cfg.VERSION_COMPRESSION_DELTA_ENABLED is False  # absent key = off


# ── what the menu shows ─────────────────────────────────────────────────────────────────────


def test_the_menu_shows_every_setting_with_current_default_range_and_the_restart_note(
    cfg, monkeypatch, capsys
):
    write_file(cfg, OWNER_FILE)
    out = run_menu(cfg, monkeypatch, capsys, ["9"])
    for key in KEYS:
        assert key in out, key
    for text in (
        "1 to 22",
        "0 to 50",
        "5 to 100",
        "60 to 86400",
        "1 to 90",
        "on / off",
    ):
        assert text in out, text
    assert out.count("default ") >= 7
    assert "RESTART" in out and "Version Engine" in out
    assert "Save & Back" in out and "Back Without Saving" in out
    # the owner's state: switch ON in the file, delta key absent
    assert "VERSION_COMPRESSION_ENABLED" in out and "✅ ON" in out
    assert (
        "not in server_config.json: default applies" in out
    )  # the absent delta key etc.
    assert "in server_config.json" in out


def test_the_menu_warns_about_a_file_value_the_loader_ignores(cfg, monkeypatch, capsys):
    write_file(
        cfg, {"VERSION_COMPRESSION_ENABLED": "true", "VERSION_COMPRESSION_LEVEL": 99}
    )
    out = run_menu(cfg, monkeypatch, capsys, ["9"])
    assert "file holds 'true'" in out and "this is OFF" in out
    assert "file holds 99" in out and "the default is used" in out


def test_the_menu_marks_unsaved_changes(cfg, monkeypatch, capsys):
    write_file(cfg, OWNER_FILE)
    out = run_menu(cfg, monkeypatch, capsys, ["2", "19", "9"])
    assert "*2. zstd level: 19" in out


def test_engine_settings_menu_has_entry_13_and_keeps_save_11_and_exit_12(
    cfg, monkeypatch, capsys
):
    """13 is listed before Save & Exit (the server menu's 14 does the same), so the numbers the
    owner already types do not move. Opening 13 and backing out writes nothing."""
    answers = iter(["13", "9", "12"])
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr(builtins, "input", fake_input)
    capsys.readouterr()
    cfg.configure_version_engine_settings()
    out = capsys.readouterr().out
    assert "13. Compression (zstd)" in out
    assert "11. Save & Exit" in out and "12. Exit Without Saving" in out
    assert "Select option (1-13): " in prompts
    assert not Path(cfg._SERVER_CONFIG_FILE).exists()


def test_view_current_settings_shows_the_compression_line(cfg, monkeypatch, capsys):
    fake_engine = types.ModuleType(
        "version_engine"
    )  # config.py looks it up at call time

    def status():
        raise RuntimeError("no engine in a test")

    fake_engine.status = status
    monkeypatch.setitem(sys.modules, "version_engine", fake_engine)
    write_file(cfg, OWNER_FILE)
    capsys.readouterr()
    cfg.view_current_settings()
    out = capsys.readouterr().out
    assert "Compression:" in out and "zstd level 22" in out


# ── saving: only the changed keys, everything else as it is ────────────────────────────────


def test_a_save_writes_only_the_changed_key_and_keeps_everything_else(
    cfg, monkeypatch, capsys
):
    write_file(cfg, OWNER_FILE)
    path = Path(cfg._SERVER_CONFIG_FILE)
    before_text = path.read_text(encoding="utf-8")
    out = run_menu(
        cfg,
        monkeypatch,
        capsys,
        [NUMBER["VERSION_COMPRESSION_BUSY_PERCENT"], "40", "8"],
    )
    assert "Restart the Version Engine" in out
    after = read_file(cfg)
    expected = dict(OWNER_FILE)
    expected["VERSION_COMPRESSION_BUSY_PERCENT"] = 40
    assert after == expected
    # the owner's switch is as it was, the absent delta key is still absent, configured_at kept
    assert after["VERSION_COMPRESSION_ENABLED"] is True
    assert "VERSION_COMPRESSION_DELTA_ENABLED" not in after
    assert after["configured_at"] == OWNER_FILE["configured_at"]
    # same order of the old keys, the new key appended at the end
    assert list(after)[:-1] == list(OWNER_FILE)
    assert before_text != path.read_text(encoding="utf-8")
    assert cfg.VERSION_COMPRESSION_BUSY_PERCENT == 40


def test_a_changed_value_keeps_its_position_in_the_file(cfg, monkeypatch, capsys):
    write_file(cfg, OWNER_FILE)
    run_menu(cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_LEVEL"], "19", "8"])
    after = read_file(cfg)
    assert list(after) == list(OWNER_FILE)
    assert after["VERSION_COMPRESSION_LEVEL"] == 19


def test_the_delta_switch_is_written_as_a_real_json_boolean(cfg, monkeypatch, capsys):
    write_file(cfg, OWNER_FILE)
    run_menu(
        cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_DELTA_ENABLED"], "8"]
    )
    raw = Path(cfg._SERVER_CONFIG_FILE).read_text(encoding="utf-8")
    assert '"VERSION_COMPRESSION_DELTA_ENABLED": true' in raw
    after = read_file(cfg)
    assert after["VERSION_COMPRESSION_DELTA_ENABLED"] is True
    assert after["VERSION_COMPRESSION_ENABLED"] is True  # untouched
    assert cfg.VERSION_COMPRESSION_DELTA_ENABLED is True


def test_the_main_switch_can_be_turned_off_and_on_again_in_one_visit(
    cfg, monkeypatch, capsys
):
    """Two toggles are no change: nothing is written."""
    write_file(cfg, OWNER_FILE)
    before = Path(cfg._SERVER_CONFIG_FILE).read_bytes()
    out = run_menu(cfg, monkeypatch, capsys, ["1", "1", "8"])
    assert "Nothing changed" in out
    assert Path(cfg._SERVER_CONFIG_FILE).read_bytes() == before


def test_every_number_is_written_as_a_json_number_inside_the_bounds(
    cfg, monkeypatch, capsys
):
    write_file(cfg, OWNER_FILE)
    answers = []
    wanted = {}
    for key, (low, high) in INT_BOUNDS.items():
        value = high if key != "VERSION_COMPRESSION_LEVEL" else low
        if value == DEFAULTS[key]:
            value = low if value == high else high
        wanted[key] = value
        answers += [NUMBER[key], str(value)]
    run_menu(cfg, monkeypatch, capsys, answers + ["8"])
    after = read_file(cfg)
    for key, (low, high) in INT_BOUNDS.items():
        assert type(after[key]) is int, key
        assert low <= after[key] <= high, key
        assert after[key] == wanted[key], key
    # the loader reads back exactly what the menu wrote
    cfg.load_server_config()
    for key, value in wanted.items():
        assert getattr(cfg, key) == value


def test_the_two_ends_of_every_range_are_accepted(cfg, monkeypatch, capsys):
    for key, (low, high) in INT_BOUNDS.items():
        for value in (low, high):
            if os.path.exists(cfg._SERVER_CONFIG_FILE):
                os.remove(cfg._SERVER_CONFIG_FILE)
            cfg.load_server_config()
            setattr(
                cfg, key, DEFAULTS[key] if value != DEFAULTS[key] else (low + high) // 2
            )
            run_menu(cfg, monkeypatch, capsys, [NUMBER[key], str(value), "8"])
            assert read_file(cfg)[key] == value, (key, value)


def test_a_missing_file_is_created_with_only_the_changed_keys(cfg, monkeypatch, capsys):
    assert not Path(cfg._SERVER_CONFIG_FILE).exists()
    run_menu(cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_LEVEL"], "9", "8"])
    assert read_file(cfg) == {"VERSION_COMPRESSION_LEVEL": 9}


def test_the_file_is_written_with_lf_and_no_temporary_file_is_left(
    cfg, monkeypatch, capsys
):
    write_file(cfg, OWNER_FILE)
    run_menu(cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_LEVEL"], "3", "8"])
    assert b"\r" not in Path(cfg._SERVER_CONFIG_FILE).read_bytes()
    assert not Path(cfg._SERVER_CONFIG_FILE + ".tmp").exists()


def test_the_menu_never_uses_the_whole_file_save(cfg, monkeypatch, capsys):
    """save_server_config() rebuilds the file from memory (drops unknown keys, resets values the
    loader refused, adds absent keys): the compression menu must not call it."""

    def forbidden():
        raise AssertionError(
            "save_server_config() must not be used by the compression menu"
        )

    monkeypatch.setattr(cfg, "save_server_config", forbidden)
    write_file(cfg, OWNER_FILE)
    run_menu(cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_LEVEL"], "3", "8"])
    assert read_file(cfg)["VERSION_COMPRESSION_LEVEL"] == 3


def test_a_hand_edited_value_the_owner_did_not_touch_is_kept_as_written(
    cfg, monkeypatch, capsys
):
    """A string "true" counts as OFF for the loader, but the menu must not 'repair' it behind the
    owner's back: only the key that was edited changes."""
    odd = dict(
        OWNER_FILE, VERSION_COMPRESSION_ENABLED="true", VERSION_COMPRESSION_INTERVAL=7
    )
    write_file(cfg, odd)
    run_menu(cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_LEVEL"], "12", "8"])
    after = read_file(cfg)
    assert after["VERSION_COMPRESSION_ENABLED"] == "true"
    assert after["VERSION_COMPRESSION_INTERVAL"] == 7
    assert after["VERSION_COMPRESSION_LEVEL"] == 12


# ── refusals ────────────────────────────────────────────────────────────────────────────────


BAD_ENTRIES = ["abc", "1.5", "-3", "+5", "1e2", "0x10", "True", "٣", "², ", "1 2"]


@pytest.mark.parametrize("key", sorted(INT_BOUNDS))
def test_the_menu_refuses_out_of_range_and_non_integer_values(
    cfg, monkeypatch, capsys, key
):
    low, high = INT_BOUNDS[key]
    write_file(cfg, OWNER_FILE)
    before = Path(cfg._SERVER_CONFIG_FILE).read_bytes()
    memory_before = getattr(cfg, key)
    bad = [str(low - 1), str(high + 1), str(high * 1000)] + BAD_ENTRIES
    answers = []
    for entry in bad:
        answers += [NUMBER[key], entry]
    out = run_menu(cfg, monkeypatch, capsys, answers + ["8"])
    assert out.count("nothing changed") == len(bad), (key, out[-400:])
    assert "Nothing changed" in out  # the final Save & Back had nothing to write
    assert Path(cfg._SERVER_CONFIG_FILE).read_bytes() == before
    assert getattr(cfg, key) == memory_before


def test_parse_compression_value_reports_the_range(cfg):
    assert cfg.parse_compression_value("VERSION_COMPRESSION_LEVEL", " 22 ") == (
        22,
        None,
    )
    value, error = cfg.parse_compression_value("VERSION_COMPRESSION_LEVEL", "23")
    assert value is None and "1 to 22" in error
    value, error = cfg.parse_compression_value("VERSION_COMPRESSION_INTERVAL", "59")
    assert value is None and "60 to 86400" in error
    value, error = cfg.parse_compression_value("VERSION_COMPRESSION_BUSY_PERCENT", "")
    assert value is None and "5 to 100" in error


def test_an_empty_answer_keeps_the_value(cfg, monkeypatch, capsys):
    write_file(cfg, OWNER_FILE)
    out = run_menu(
        cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_LEVEL"], "", "8"]
    )
    assert "Nothing changed" in out


# ── leaving without saving, end of input, a damaged file, a failing write ───────────────────


def test_back_without_saving_writes_nothing_and_changes_nothing_in_memory(
    cfg, monkeypatch, capsys
):
    write_file(cfg, OWNER_FILE)
    before = Path(cfg._SERVER_CONFIG_FILE).read_bytes()
    run_menu(
        cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_LEVEL"], "5", "1", "9"]
    )
    assert Path(cfg._SERVER_CONFIG_FILE).read_bytes() == before
    assert (
        cfg.VERSION_COMPRESSION_LEVEL == 22 and cfg.VERSION_COMPRESSION_ENABLED is True
    )


def test_end_of_input_leaves_without_saving(cfg, monkeypatch, capsys):
    write_file(cfg, OWNER_FILE)
    before = Path(cfg._SERVER_CONFIG_FILE).read_bytes()
    out = run_menu(
        cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_LEVEL"], "5"]
    )  # then EOF
    assert "nothing saved" in out
    assert Path(cfg._SERVER_CONFIG_FILE).read_bytes() == before


def test_ctrl_c_at_a_value_prompt_cancels_only_that_entry(cfg, monkeypatch, capsys):
    write_file(cfg, OWNER_FILE)
    calls = iter([NUMBER["VERSION_COMPRESSION_LEVEL"], KeyboardInterrupt, "9"])

    def fake_input(prompt=""):
        item = next(calls)
        if item is KeyboardInterrupt:
            raise KeyboardInterrupt
        return item

    monkeypatch.setattr(builtins, "input", fake_input)
    capsys.readouterr()
    cfg.configure_version_compression()
    assert cfg.VERSION_COMPRESSION_LEVEL == 22


def test_an_invalid_menu_choice_is_reported(cfg, monkeypatch, capsys):
    out = run_menu(cfg, monkeypatch, capsys, ["x", "0", "10", "9"])
    assert out.count("Invalid option") == 3


def test_a_damaged_file_is_never_overwritten(cfg, monkeypatch, capsys):
    path = Path(cfg._SERVER_CONFIG_FILE)
    path.write_text("{ this is not json", encoding="utf-8")
    before = path.read_bytes()
    out = run_menu(
        cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_LEVEL"], "9", "8", "9"]
    )
    assert "cannot be read" in out and "Nothing was written" in out
    assert path.read_bytes() == before
    assert cfg.VERSION_COMPRESSION_LEVEL == 22  # not applied in memory either


def test_a_file_that_is_not_a_json_object_is_never_overwritten(
    cfg, monkeypatch, capsys
):
    path = Path(cfg._SERVER_CONFIG_FILE)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert cfg.save_server_config_keys({"VERSION_COMPRESSION_LEVEL": 9}) is False
    assert path.read_text(encoding="utf-8") == "[1, 2, 3]"


def test_a_failing_replace_leaves_the_old_file_and_no_temporary_file(
    cfg, monkeypatch, capsys
):
    write_file(cfg, OWNER_FILE)
    path = Path(cfg._SERVER_CONFIG_FILE)
    before = path.read_bytes()

    def broken_replace(src, dst):
        raise OSError("disk says no")

    monkeypatch.setattr(os, "replace", broken_replace)
    out = run_menu(
        cfg, monkeypatch, capsys, [NUMBER["VERSION_COMPRESSION_LEVEL"], "9", "8", "9"]
    )
    assert "Error saving configuration" in out
    assert path.read_bytes() == before
    assert not Path(cfg._SERVER_CONFIG_FILE + ".tmp").exists()
    assert cfg.VERSION_COMPRESSION_LEVEL == 22  # a failed save is not applied in memory


def test_save_server_config_keys_returns_true_and_names_the_keys(cfg, capsys):
    write_file(cfg, OWNER_FILE)
    assert cfg.save_server_config_keys({"VERSION_COMPRESSION_LEVEL": 5}) is True
    assert "VERSION_COMPRESSION_LEVEL" in capsys.readouterr().out
    assert read_file(cfg)["VERSION_COMPRESSION_LEVEL"] == 5
    assert read_file(cfg)["SOME_HAND_ADDED_KEY"] == OWNER_FILE["SOME_HAND_ADDED_KEY"]


# ── structure guards ────────────────────────────────────────────────────────────────────────


def test_the_old_whole_file_save_is_untouched_by_name(cfg):
    """Entry 11 of the Engine settings menu still calls save_server_config() (the other menus
    rely on it); only the compression sub-menu uses the targeted save."""
    source = (ROOT / "config.py").read_text(encoding="utf-8")
    engine_menu = source.split("def configure_version_engine_settings():")[1].split(
        "\ndef "
    )[0]
    assert 'choice == "11"' in engine_menu and "save_server_config()" in engine_menu
    compression_menu = source.split("def configure_version_compression():")[1].split(
        "\ndef "
    )[0]
    assert "save_server_config()" not in compression_menu
    assert "save_server_config_keys(" in compression_menu
