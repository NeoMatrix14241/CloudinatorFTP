"""
Tests for the compression sub-menu of tools/version_manage.py (5.47.7): option 7 of its
interactive menu with status, probe, sweep, verify and decompress.

What they guard: each entry calls the very same do_compress_* function the command line calls, with
the command line's defaults (compared through inspect, so a drift in either place fails); status and
probe are read-only (they never open the engine for writing); sweep asks y/N first; decompress asks
for the same typed phrase as the command line and is refused while compression is switched on; the
menu never edits config; Ctrl-D / Ctrl-C leave cleanly; the numbers of the main menu moved to
1..8 with Exit last. The command line itself is checked as unchanged.

The tool is loaded against fake `config`, `version_engine` and `helpers` modules (the same trick as
tests/unit/test_version_wal.py), so nothing touches a database or an object store.
"""

import builtins
import importlib.util
import inspect
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = ROOT / "tools" / "version_manage.py"


class FakeEngine:
    """Records what the tool asks of it; `plan` is what decompress_plan() answers."""

    instances = []
    plan = {
        "compressed_objects": 5,
        "objects": 5,
        "raw_bytes": 1000,
        "free_bytes": 10**12,
    }
    running = "0"

    def __init__(self):
        self.calls = []
        FakeEngine.instances.append(self)

    def _ensure_dirs(self):
        self.calls.append("_ensure_dirs")

    def _bootstrap_schema(self):
        self.calls.append("_bootstrap_schema")

    def _get_meta(self, key, default=None):
        return self.running if key == "compress_running" else default

    def decompress_plan(self):
        return dict(self.plan)

    def decompress_all(self, pause=None, busy=100.0):
        self.calls.append(("decompress_all", busy))
        return {"decompressed": 5, "lost": 0, "error": 0}


@pytest.fixture
def tool(monkeypatch):
    """tools/version_manage.py executed against fakes, as a fresh module per test."""
    FakeEngine.instances = []
    FakeEngine.running = "0"
    config = types.ModuleType("config")
    config.VERSION_COMPRESSION_ENABLED = False
    config.VERSION_COMPRESSION_LEVEL = 22
    config.VERSION_COMPRESSION_MIN_SAVING_PERCENT = 5
    config.VERSION_COMPRESSION_BUSY_PERCENT = 25
    config.VERSION_COMPRESSION_INTERVAL = 600
    config.VERSION_COMPRESSION_DELTA_ENABLED = False
    config.VERSION_COMPRESSION_DELTA_MIN_GAIN_PERCENT = 20
    config.format_bytes = lambda n: f"{n} B"
    engine = types.ModuleType("version_engine")
    engine.Engine = FakeEngine
    zstd = types.ModuleType("helpers.version_zstd")
    zstd.DEFAULT_LEVEL = 22
    zstd.MIN_OBJECT_SIZE = 4096
    zstd.available = lambda: True
    zstd.version = lambda: "1.5.7"
    probe = types.ModuleType("helpers.version_probe")
    probe.DEFAULT_SAMPLES = 400
    probe.DEFAULT_LEVELS = (1, 3, 9, 15, 19, 22)
    probe.DEFAULT_BUSY_PERCENT = 50.0
    probe.DEFAULT_MIN_SAVING = 5.0
    probe.DEFAULT_DELTA_PAIRS = 200
    probe.ProbeError = type("ProbeError", (Exception,), {})
    compress = types.ModuleType("helpers.version_compress")
    wal = types.ModuleType("helpers.version_wal")
    helpers = types.ModuleType("helpers")
    helpers.__path__ = []
    helpers.version_compress = compress
    helpers.version_probe = probe
    helpers.version_wal = wal
    helpers.version_zstd = zstd
    for name, module in {
        "config": config,
        "version_engine": engine,
        "helpers": helpers,
        "helpers.version_compress": compress,
        "helpers.version_probe": probe,
        "helpers.version_wal": wal,
        "helpers.version_zstd": zstd,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location(
        "version_manage_menu_under_test", TOOL
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ACTIONS = {
    "1": "do_compress_status",
    "2": "do_compress_probe",
    "3": "do_compress_sweep",
    "4": "do_compress_verify",
    "5": "do_compress_decompress",
}


def feed(monkeypatch, answers):
    queue = iter(answers)
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        try:
            return next(queue)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(builtins, "input", fake_input)
    return prompts


def spy_actions(tool, monkeypatch):
    calls = []
    if not hasattr(tool, "_originals"):  # the real functions, for their signatures
        tool._originals = {n: getattr(tool, n) for n in ACTIONS.values()}
    for name in ACTIONS.values():
        monkeypatch.setattr(
            tool,
            name,
            lambda *a, _n=name, **k: calls.append((_n, a, k)) or 0,
        )
    return calls


def resolved(tool_function, args, kwargs):
    """The arguments a call really gets, defaults filled in: what both entry points must agree on."""
    bound = inspect.signature(tool_function).bind(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


# ── the main menu ───────────────────────────────────────────────────────────────────────────


def test_the_main_menu_lists_compression_as_7_and_exit_as_8(tool, monkeypatch, capsys):
    prompts = feed(monkeypatch, ["8"])
    assert tool.interactive_menu() == 0
    out = capsys.readouterr().out
    assert "7) Object compression: status / probe / sweep / verify / decompress" in out
    assert "8) Exit" in out
    assert "\nSelect option (1-8): " in prompts
    assert "WAL file" in out  # 6 is where it was


def test_option_7_opens_the_sub_menu_and_back_returns_to_the_main_menu(
    tool, monkeypatch, capsys
):
    prompts = feed(monkeypatch, ["7", "6", "8"])
    assert tool.interactive_menu() == 0
    out = capsys.readouterr().out
    assert "Object compression (zstd)" in out
    assert out.count("Version Engine — interactive management") == 1
    assert "\nSelect option (1-6): " in prompts
    assert "Press Enter" not in "".join(prompts)  # no pointless pause after Back


def test_the_old_exit_number_7_no_longer_exits(tool, monkeypatch, capsys):
    feed(monkeypatch, ["7", "6", "q"])
    assert tool.interactive_menu() == 0
    assert "Object compression (zstd)" in capsys.readouterr().out


def test_end_of_input_in_the_sub_menu_returns_without_running_anything(
    tool, monkeypatch, capsys
):
    calls = spy_actions(tool, monkeypatch)
    feed(
        monkeypatch, ["7"]
    )  # then end of input inside the sub-menu, then at the main menu
    assert tool.interactive_menu() == 0
    assert calls == []


# ── the settings are shown, read-only ───────────────────────────────────────────────────────


def test_the_sub_menu_shows_the_settings_and_where_to_change_them(
    tool, monkeypatch, capsys
):
    tool.config.VERSION_COMPRESSION_ENABLED = True
    tool.config.VERSION_COMPRESSION_DELTA_ENABLED = True
    feed(monkeypatch, ["6"])
    tool.compression_menu()
    out = capsys.readouterr().out
    assert "Compression: ON, zstd level 22, min saving 5 %, busy 25 %" in out
    assert "idle look every 600 s" in out
    assert "Delta: ON, min gain 20 %" in out
    assert "Engine settings > 13" in out and "restart the Version Engine" in out


def test_the_tool_never_writes_config(tool):
    source = TOOL.read_text(encoding="utf-8")
    for name in ("save_server_config", "save_server_config_keys", "load_server_config"):
        assert name not in source, name


# ── every entry is the command line's own function with the command line's arguments ──────


@pytest.mark.parametrize("choice", ["1", "2", "4", "5"])
def test_an_entry_calls_the_same_function_with_the_command_lines_arguments(
    tool, monkeypatch, capsys, choice
):
    flag = {"1": "--status", "2": "--probe", "4": "--verify", "5": "--decompress"}[
        choice
    ]
    name = ACTIONS[choice]

    cli_calls = spy_actions(tool, monkeypatch)
    args = tool._build_parser().parse_args(["compress", flag])
    tool.cmd_compress(args)
    assert [c[0] for c in cli_calls] == [name]
    cli = resolved(tool._originals[name], cli_calls[0][1], cli_calls[0][2])

    menu_calls = spy_actions(tool, monkeypatch)
    feed(monkeypatch, [choice, "", "6"])
    tool.compression_menu()
    assert [c[0] for c in menu_calls] == [name]
    menu = resolved(tool._originals[name], menu_calls[0][1], menu_calls[0][2])
    assert menu == cli


def test_sweep_asks_first_and_then_matches_the_command_line(tool, monkeypatch, capsys):
    cli_calls = spy_actions(tool, monkeypatch)
    tool.cmd_compress(tool._build_parser().parse_args(["compress", "--sweep"]))
    cli = resolved(
        tool._originals["do_compress_sweep"], cli_calls[0][1], cli_calls[0][2]
    )

    menu_calls = spy_actions(tool, monkeypatch)
    prompts = feed(monkeypatch, ["3", "y", "", "6"])
    tool.compression_menu()
    assert any("(y/N)" in p for p in prompts)
    assert len(menu_calls) == 1
    assert (
        resolved(
            tool._originals["do_compress_sweep"], menu_calls[0][1], menu_calls[0][2]
        )
        == cli
    )


@pytest.mark.parametrize("answer", ["", "n", "N", "no", "maybe"])
def test_sweep_does_nothing_unless_the_answer_is_yes(tool, monkeypatch, capsys, answer):
    calls = spy_actions(tool, monkeypatch)
    feed(monkeypatch, ["3", answer, "6"])
    tool.compression_menu()
    assert calls == []
    assert "Cancelled" in capsys.readouterr().out


def test_an_invalid_choice_is_reported_and_runs_nothing(tool, monkeypatch, capsys):
    calls = spy_actions(tool, monkeypatch)
    feed(monkeypatch, ["9", "x", "", "6"])
    tool.compression_menu()
    assert calls == []
    assert capsys.readouterr().out.count("Invalid option") == 3


def test_read_only_entries_never_open_the_engine_for_writing(tool, monkeypatch, capsys):
    """status and probe go through do_compress_status / do_compress_probe, which only build a
    path-only Engine(); the menu itself never calls _get_engine() (it creates folders/tables).
    """
    spy_actions(tool, monkeypatch)
    opened = []
    monkeypatch.setattr(tool, "_get_engine", lambda: opened.append(1))
    feed(monkeypatch, ["1", "", "2", "", "6"])
    tool.compression_menu()
    assert opened == []
    body = inspect.getsource(tool.compression_menu)
    assert "_get_engine" not in body


# ── decompress: the same confirmation as the command line ───────────────────────────────────


def test_decompress_asks_for_the_typed_phrase_and_a_wrong_one_touches_nothing(
    tool, monkeypatch, capsys
):
    prompts = feed(monkeypatch, ["5", "decompress 4 objects", "", "6"])
    tool.compression_menu()
    out = capsys.readouterr().out
    assert "decompress 5 objects" in out
    assert "Cancelled: nothing was touched" in out
    assert not any(
        "decompress_all" in str(c) for e in FakeEngine.instances for c in e.calls
    )
    assert "> " in prompts


def test_decompress_runs_only_after_the_exact_phrase(tool, monkeypatch, capsys):
    feed(monkeypatch, ["5", "decompress 5 objects", "", "6"])
    tool.compression_menu()
    out = capsys.readouterr().out
    assert "are raw files again" in out
    ran = [c for e in FakeEngine.instances for c in e.calls if isinstance(c, tuple)]
    assert ran == [("decompress_all", 100.0)]  # the command line's default duty cycle


def test_decompress_is_refused_while_compression_is_switched_on(
    tool, monkeypatch, capsys
):
    tool.config.VERSION_COMPRESSION_ENABLED = True
    feed(monkeypatch, ["5", "", "6"])
    tool.compression_menu()
    out = capsys.readouterr().out
    assert "Compression is still switched on" in out
    assert not any(isinstance(c, tuple) for e in FakeEngine.instances for c in e.calls)


def test_decompress_is_refused_while_the_engine_reports_the_thread_running(
    tool, monkeypatch, capsys
):
    FakeEngine.running = "1"
    feed(monkeypatch, ["5", "", "6"])
    tool.compression_menu()
    assert "compress thread running" in capsys.readouterr().out
    assert not any(isinstance(c, tuple) for e in FakeEngine.instances for c in e.calls)


def test_decompress_never_passes_yes_or_force_from_the_menu(tool, monkeypatch, capsys):
    calls = spy_actions(tool, monkeypatch)
    feed(monkeypatch, ["5", "", "6"])
    tool.compression_menu()
    name, args, kwargs = calls[0]
    assert (
        args == () and kwargs == {}
    )  # yes=False, force=False are the function's defaults
    parameters = inspect.signature(tool._originals[name]).parameters
    assert parameters["yes"].default is False
    assert parameters["force"].default is False


def test_ctrl_d_at_the_typed_phrase_cancels(tool, monkeypatch, capsys):
    feed(monkeypatch, ["5"])  # end of input at the phrase prompt
    tool.compression_menu()
    assert "Cancelled: nothing was touched" in capsys.readouterr().out
    assert not any(isinstance(c, tuple) for e in FakeEngine.instances for c in e.calls)


# ── the command line is unchanged ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["compress", "--status"], ("do_compress_status", {"db_path": None})),
        (
            ["compress", "--sweep"],
            ("do_compress_sweep", {"grace": 0.0, "busy_percent": 100.0}),
        ),
        (
            ["compress", "--sweep", "--grace", "30", "--busy-percent", "40"],
            ("do_compress_sweep", {"grace": 30, "busy_percent": 40}),
        ),
        (["compress", "--verify"], ("do_compress_verify", {"busy_percent": 50.0})),
        (
            ["compress", "--decompress", "--yes", "--force"],
            (
                "do_compress_decompress",
                {"yes": True, "force": True, "busy_percent": 100.0},
            ),
        ),
    ],
)
def test_the_command_line_still_dispatches_as_before(tool, monkeypatch, argv, expected):
    calls = spy_actions(tool, monkeypatch)
    tool.cmd_compress(tool._build_parser().parse_args(argv))
    name, kwargs = expected
    assert calls == [(name, (), kwargs)]


def test_the_command_line_refusals_are_unchanged(tool, capsys):
    parse = tool._build_parser().parse_args
    assert tool.cmd_compress(parse(["compress"])) == 2
    assert tool.cmd_compress(parse(["compress", "--sweep", "--verify"])) == 2
    assert tool.cmd_compress(parse(["compress", "--yes", "--sweep"])) == 2
    assert tool.cmd_compress(parse(["compress", "--grace", "5", "--verify"])) == 2
    out = capsys.readouterr().out
    assert (
        "Choose ONE action" in out
        and "--yes and --force only apply with --decompress" in out
    )
