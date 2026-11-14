"""
Unit tests for helpers/version_wal.py (5.45.1: keep the Version Engine's write-ahead log small),
for how version_engine.py wires it in, for the VERSION_WAL_SIZE_LIMIT_MB setting and for the
`version-manage wal` command of tools/version_manage.py.

Nothing here starts a server or imports the application. The helper is a stdlib-only leaf and
works on throw-away SQLite files; the engine and config files are only read with `ast` (the way
test_version_purge.py does it); the tool is loaded with a fake `config` and a fake
`version_engine` module, so the real engine never runs. The hard rule of this feature: NO
asyncio, no thread pool anywhere in it, and the limit is NEVER above 64 MB.
"""

import ast
import importlib.util
import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from helpers import version_wal as vw  # noqa: E402

MB = 1024 * 1024


# -- helpers -----------------------------------------------------------------------------


def _open(path):
    """A WAL-mode connection that never checkpoints by itself, so the -wal file really grows."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE IF NOT EXISTS t(x BLOB)")
    return conn


def _fill(conn, rows=30, size=100_000):
    blob = b"x" * size
    for _ in range(rows):
        conn.execute("INSERT INTO t VALUES(?)", (blob,))


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "version_engine.sqlite3")
    conn = _open(path)
    yield path, conn
    conn.close()


# -- the limit ---------------------------------------------------------------------------


def test_the_limit_is_never_above_64_mb():
    assert vw.MAX_LIMIT_MB == 64
    for big in (65, 100, 10**9, float("inf")):
        assert vw.limit_bytes(big) == 64 * MB


def test_the_limit_in_bytes_for_normal_settings():
    assert vw.limit_bytes(64) == 64 * MB
    assert vw.limit_bytes(32) == 32 * MB
    assert vw.limit_bytes(0.2) == 1 * MB  # a non-zero value is raised to the 1 MB floor


def test_zero_or_negative_switches_it_off_and_garbage_gives_the_default():
    assert vw.limit_bytes(0) == 0
    assert vw.limit_bytes(-5) == 0
    for bad in (None, "64", True, [], float("nan")):
        assert vw.limit_bytes(bad) == vw.DEFAULT_LIMIT_MB * MB


def test_human_bytes():
    assert vw.human_bytes(0) == "0 B"
    assert vw.human_bytes(2048) == "2.0 KB"
    assert vw.human_bytes(5 * MB) == "5.0 MB"
    assert vw.human_bytes(3 * 1024 * MB) == "3.0 GB"


# -- sizes and the pragma ----------------------------------------------------------------


def test_file_sizes_of_a_missing_database_are_zero(tmp_path):
    assert vw.file_sizes(str(tmp_path / "none.sqlite3")) == {
        "db": 0,
        "wal": 0,
        "shm": 0,
    }


def test_file_sizes_see_the_wal_file(db):
    path, conn = db
    _fill(conn)
    sizes = vw.file_sizes(path)
    assert sizes["wal"] > 1 * MB and sizes["shm"] > 0
    assert vw.wal_size(path) == sizes["wal"]


def test_journal_size_limit_is_set_on_the_connection_only_when_positive(db):
    _, conn = db
    before = conn.execute("PRAGMA journal_size_limit").fetchone()[0]
    vw.apply_journal_size_limit(conn, 0)
    assert conn.execute("PRAGMA journal_size_limit").fetchone()[0] == before
    vw.apply_journal_size_limit(conn, 64 * MB)
    assert conn.execute("PRAGMA journal_size_limit").fetchone()[0] == 64 * MB


def test_with_the_limit_set_the_wal_shrinks_by_itself_after_a_checkpoint(db):
    """No manual truncate: a passive checkpoint plus the next write cuts the file back."""
    path, conn = db
    vw.apply_journal_size_limit(conn, 65536)
    _fill(conn)
    assert vw.wal_size(path) > 1 * MB
    conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    conn.execute("INSERT INTO t VALUES(?)", (b"x",))
    assert vw.wal_size(path) <= 65536


# -- the checkpoint ----------------------------------------------------------------------


def test_truncate_merges_the_log_and_cuts_the_file_to_zero(db):
    path, conn = db
    _fill(conn)
    db_before = vw.file_sizes(path)["db"]
    result = vw.checkpoint(conn, path)
    assert result.completed and result.mode == "TRUNCATE" and result.error == ""
    assert result.wal_before > 1 * MB and result.wal_after == 0
    assert os.path.getsize(vw.wal_path(path)) == 0
    assert vw.file_sizes(path)["db"] > db_before  # the data was merged, not dropped
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 30


def test_a_busy_database_is_a_result_not_an_exception_and_the_timeout_is_restored(db):
    path, conn = db
    _fill(conn, rows=5)
    reader = sqlite3.connect(path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM t").fetchone()  # pins an old snapshot
    _fill(conn, rows=5)
    conn.execute("PRAGMA busy_timeout=4321")
    try:
        result = vw.checkpoint(conn, path, busy_timeout_ms=50)
        assert result.ran and result.busy == 1 and not result.completed
        assert result.wal_after == result.wal_before > 0  # the file was not cut
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 4321
    finally:
        reader.execute("COMMIT")
        reader.close()
    assert vw.checkpoint(conn, path, busy_timeout_ms=50).completed  # reader gone


def test_a_connection_with_an_open_transaction_is_not_checkpointed(db):
    path, conn = db
    _fill(conn, rows=2)
    conn.execute("BEGIN")
    conn.execute("INSERT INTO t VALUES(?)", (b"y",))
    result = vw.checkpoint(conn, path)
    assert not result.ran and not result.completed
    assert "open transaction" in result.error
    conn.execute("ROLLBACK")


def test_the_mode_is_checked_before_it_goes_into_the_statement(db):
    path, conn = db
    with pytest.raises(ValueError):
        vw.checkpoint(conn, path, mode="TRUNCATE); DROP TABLE t; --")
    assert vw.checkpoint(conn, path, mode="passive").mode == "PASSIVE"
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0


def test_passive_merges_but_does_not_shrink_the_file(db):
    path, conn = db
    _fill(conn)
    before = vw.wal_size(path)
    result = vw.checkpoint(conn, path, mode="PASSIVE")
    assert result.completed and result.wal_after == before


def test_checkpoint_if_larger_only_runs_above_the_limit(db):
    path, conn = db
    assert vw.checkpoint_if_larger(conn, path, 64 * MB) is None  # empty log
    _fill(conn)
    assert vw.wal_size(path) < 64 * MB
    assert vw.checkpoint_if_larger(conn, path, 64 * MB) is None  # below the limit
    assert vw.wal_size(path) > 0  # untouched
    result = vw.checkpoint_if_larger(conn, path, 1 * MB)  # above it
    assert result is not None and result.completed and result.wal_after == 0


def test_a_limit_of_zero_switches_the_checkpoint_off(db):
    path, conn = db
    _fill(conn)
    assert vw.checkpoint_if_larger(conn, path, 0) is None
    assert vw.wal_size(path) > 0


# -- the hard rule: no asyncio -----------------------------------------------------------

_FORBIDDEN_MODULES = {"asyncio", "concurrent", "anyio", "trio", "quart", "hypercorn"}
_FORBIDDEN_CALLS = {
    "to_thread",
    "run_in_executor",
    "get_event_loop",
    "get_running_loop",
    "new_event_loop",
    "create_task",
    "ensure_future",
    "run_coroutine_threadsafe",
    "ThreadPoolExecutor",
    "ProcessPoolExecutor",
    "submit",
    "Thread",
    "Timer",
}


def _tree(name):
    return ast.parse((ROOT / name).read_text(encoding="utf-8"))


def _async_findings(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [
                a.name for a in node.names if a.name.split(".")[0] in _FORBIDDEN_MODULES
            ]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _FORBIDDEN_MODULES:
                found.append(node.module)
        elif isinstance(
            node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)
        ):
            found.append(type(node).__name__)
        elif isinstance(node, ast.Call):
            fn = node.func
            called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if called in _FORBIDDEN_CALLS:
                found.append(called)
    return found


def test_the_helper_uses_no_asyncio_no_thread_and_no_thread_pool():
    assert _async_findings(_tree("helpers/version_wal.py")) == []


def test_the_tool_uses_no_asyncio_no_thread_and_no_thread_pool():
    assert _async_findings(_tree("tools/version_manage.py")) == []


def test_the_helper_is_a_stdlib_only_leaf():
    allowed = {"math", "os", "sqlite3", "time", "dataclasses"}
    for node in ast.walk(_tree("helpers/version_wal.py")):
        if isinstance(node, ast.Import):
            assert {a.name.split(".")[0] for a in node.names} <= allowed
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in allowed


# -- how the engine wires it in ----------------------------------------------------------


def _engine_method(name):
    for cls in ast.walk(_tree("version_engine.py")):
        if isinstance(cls, ast.ClassDef) and cls.name == "Engine":
            for node in cls.body:
                if isinstance(node, ast.FunctionDef) and node.name == name:
                    return node
    raise AssertionError(f"Engine.{name} not found in version_engine.py")


def _source(node):
    return ast.unparse(node)


def test_every_engine_connection_sets_the_journal_size_limit():
    connect = _source(_engine_method("_connect"))
    assert "version_wal.apply_journal_size_limit(conn, _wal_limit_bytes())" in connect
    assert connect.index("journal_mode=WAL") < connect.index("apply_journal_size_limit")
    assert connect.index("apply_journal_size_limit") < connect.index(
        "self._conn_local.conn = conn"
    )


def test_the_scanner_checkpoints_after_the_garbage_collection():
    loop = _source(_engine_method("_scanner_loop"))
    assert "self.checkpoint_wal_if_large('GC')" in loop
    assert loop.index("self.run_gc") < loop.index("checkpoint_wal_if_large")


def test_the_purge_thread_checkpoints_after_each_pass():
    loop = _source(_engine_method("_purge_loop"))
    assert "self.checkpoint_wal_if_large('purge')" in loop
    assert loop.index("self.run_purge_missing_pass()") < loop.index(
        "checkpoint_wal_if_large"
    )


def test_the_engine_checkpoint_never_raises_waits_briefly_and_takes_no_lock():
    method = _source(_engine_method("checkpoint_wal_if_large"))
    assert "except Exception" in method  # a failed checkpoint must not stop a loop
    assert "version_wal.checkpoint_if_larger(" in method
    assert "busy_timeout_ms=_WAL_CHECKPOINT_BUSY_MS" in method
    assert "_maintenance_lock" not in method and "_WRITE_GATE" not in method
    consts = {
        t.id: ast.literal_eval(n.value)
        for n in _tree("version_engine.py").body
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name) and t.id.startswith("_WAL_")
    }
    assert (
        0 < consts["_WAL_CHECKPOINT_BUSY_MS"] <= 5000
    )  # short: writers wait behind it


def test_the_engine_limit_comes_from_the_setting_through_the_helper():
    text = (ROOT / "version_engine.py").read_text(encoding="utf-8")
    assert 'getattr(config, "VERSION_WAL_SIZE_LIMIT_MB", 64)' in text
    assert "version_wal.limit_bytes(" in text


# -- config ------------------------------------------------------------------------------


def _config_function(name):
    for node in _tree("config.py").body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            namespace = {}
            code = compile(ast.Module([node], []), "config.py", "exec")
            exec(code, namespace)  # noqa: S102
            return namespace[name]
    raise AssertionError(name)


def test_the_config_default_is_64_mb():
    values = {
        t.id: ast.literal_eval(n.value)
        for n in _tree("config.py").body
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name) and t.id == "VERSION_WAL_SIZE_LIMIT_MB"
    }
    assert values == {"VERSION_WAL_SIZE_LIMIT_MB": 64}


def test_a_hand_edited_value_above_64_falls_back_to_64():
    bounded = _config_function("_bounded_number")
    assert bounded(32, 64, 0, 64) == 32
    assert bounded(0, 64, 0, 64) == 0  # 0 = off is allowed
    for bad in (65, 500, 10**9, -1, "64", None, True, float("nan")):
        assert bounded(bad, 64, 0, 64) == 64


def test_the_setting_is_saved_loaded_through_the_validator_and_bounded_to_64():
    text = (ROOT / "config.py").read_text(encoding="utf-8")
    assert '"VERSION_WAL_SIZE_LIMIT_MB": VERSION_WAL_SIZE_LIMIT_MB,' in text
    assert 'config.get("VERSION_WAL_SIZE_LIMIT_MB")' in text
    start = text.index("VERSION_WAL_SIZE_LIMIT_MB = _bounded_number(")
    snippet = text[start : text.index(")\n", start) + 1]
    assert "0,\n" in snippet and "64,\n" in snippet  # low 0, high 64


# -- the tool: tools/version_manage.py ---------------------------------------------------


class _FakeEngine:
    db_path = None  # set per test

    def __init__(self):
        self._conn_local = types.SimpleNamespace(conn=None)

    def _connect(self):
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        return conn


@pytest.fixture
def tool(monkeypatch, tmp_path):
    """tools/version_manage.py loaded against a fake config and a fake version_engine."""
    cfg = types.ModuleType("config")
    cfg.format_bytes = lambda n: f"{n} B"
    cfg.VERSION_WAL_SIZE_LIMIT_MB = 64
    cfg.VERSION_GC_GRACE_PERIOD = 86400
    fake_ve = types.ModuleType("version_engine")
    engine_cls = type("Engine", (_FakeEngine,), {})
    engine_cls.db_path = str(tmp_path / "version_engine.sqlite3")
    fake_ve.Engine = engine_cls
    fake_ve.VersionEngineError = type("VersionEngineError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "config", cfg)
    monkeypatch.setitem(sys.modules, "version_engine", fake_ve)
    spec = importlib.util.spec_from_file_location(
        "version_manage_under_test", ROOT / "tools" / "version_manage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.db_path = engine_cls.db_path
    return module


def _parse(tool, *argv):
    return tool._build_parser().parse_args(list(argv))


def test_wal_is_a_subcommand_with_the_documented_options(tool):
    args = _parse(tool, "wal")
    assert args.command == "wal" and args.checkpoint is False
    assert args.mode is None and args.timeout is None and args.if_larger_mb is None
    args = _parse(
        tool,
        "wal",
        "--checkpoint",
        "--mode",
        "full",
        "--timeout",
        "30",
        "--if-larger-mb",
        "64",
    )
    assert (args.checkpoint, args.mode, args.timeout, args.if_larger_mb) == (
        True,
        "full",
        30.0,
        64.0,
    )


@pytest.mark.parametrize(
    "bad",
    [
        ["--checkpoint", "--if-larger-mb", "65"],  # above the 64 MB ceiling
        ["--checkpoint", "--if-larger-mb", "-1"],
        ["--checkpoint", "--if-larger-mb", "lots"],
        ["--checkpoint", "--timeout", "601"],
        ["--checkpoint", "--mode", "delete"],
    ],
)
def test_wal_rejects_out_of_range_values(tool, bad):
    with pytest.raises(SystemExit) as exc:
        _parse(tool, "wal", *bad)
    assert exc.value.code == 2


def test_wal_options_without_checkpoint_are_an_error_not_silently_ignored(tool, capsys):
    for extra in (["--mode", "full"], ["--timeout", "5"], ["--if-larger-mb", "10"]):
        assert tool.cmd_wal(_parse(tool, "wal", *extra)) == 2
    assert "only apply with --checkpoint" in capsys.readouterr().out


def test_wal_on_a_missing_database_says_so_and_creates_nothing(tool, capsys):
    assert tool.do_wal() == 1
    assert "No Version Engine database" in capsys.readouterr().out
    assert not os.path.exists(tool.db_path)


def test_wal_status_shows_the_sizes_and_changes_nothing(tool, capsys):
    keep = _open(tool.db_path)
    try:
        _fill(keep)
        before = vw.file_sizes(tool.db_path)
        assert tool.do_wal() == 0
        out = capsys.readouterr().out
        assert "-wal file" in out and "VERSION_WAL_SIZE_LIMIT_MB" in out
        assert vw.file_sizes(tool.db_path) == before
    finally:
        keep.close()


def test_wal_checkpoint_truncates_the_file_and_exits_0(tool, capsys):
    keep = _open(tool.db_path)
    try:
        _fill(keep)
        assert vw.wal_size(tool.db_path) > 1 * MB
        assert tool.do_wal(checkpoint=True) == 0
        out = capsys.readouterr().out
        assert "wal_checkpoint(TRUNCATE)" in out and "Done" in out
        assert vw.wal_size(tool.db_path) == 0
        assert keep.execute("SELECT count(*) FROM t").fetchone()[0] == 30
    finally:
        keep.close()


def test_wal_if_larger_mb_skips_a_small_file(tool, capsys):
    keep = _open(tool.db_path)
    try:
        _fill(keep)
        before = vw.wal_size(tool.db_path)
        assert tool.do_wal(checkpoint=True, if_larger_mb=64) == 0
        assert "nothing to do" in capsys.readouterr().out
        assert vw.wal_size(tool.db_path) == before
        assert tool.do_wal(checkpoint=True, if_larger_mb=1) == 0
        assert vw.wal_size(tool.db_path) == 0
    finally:
        keep.close()


def test_wal_reports_busy_with_exit_1_and_loses_nothing(tool, capsys):
    keep = _open(tool.db_path)
    reader = sqlite3.connect(tool.db_path, isolation_level=None)
    try:
        _fill(keep, rows=5)
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM t").fetchone()
        _fill(keep, rows=5)
        assert tool.do_wal(checkpoint=True, timeout=0.05) == 1
        assert "kept the checkpoint from finishing" in capsys.readouterr().out
        assert keep.execute("SELECT count(*) FROM t").fetchone()[0] == 10
    finally:
        reader.execute("COMMIT")
        reader.close()
        keep.close()


def test_the_interactive_menu_offers_the_wal_option_and_exit_moved_to_7(tool):
    text = (ROOT / "tools" / "version_manage.py").read_text(encoding="utf-8")
    assert "6) WAL file: show its size / shrink it (checkpoint)" in text
    assert '"  7) Exit"' in text and "Select option (1-7)" in text
    assert 'elif choice in ("7", "q", "Q"):' in text
