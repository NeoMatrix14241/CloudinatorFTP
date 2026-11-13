"""
Unit tests for helpers/version_purge.py (the decision logic shared by tools/purge_missing_versions.py
and the Version Engine's background purge, 5.45) and for how version_engine.py wires it in.

Nothing here starts a server or imports the application: the helper is a stdlib-only leaf, its
database is a throw-away SQLite file with the two tables the pass reads, and the engine file is
only read with `ast` (the way test_version_engine_backoff.py does it). The real Engine is driven
in tests/application/test_purge_missing_background.py.

Covered: what counts as gone (strict probe), the pass (bounded, resumable, throttled, never while
a tracked folder is missing / empty / unreadable, undo file first, re-check before writing, write
lock only for the write phase, stop at every file and every batch), the undo file and its pruning,
the config defaults, and the hard rule of 5.45: NO asyncio anywhere in the purge.
"""

import ast
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from helpers import version_purge as vp  # noqa: E402

DAY = 86400


# -- helpers -----------------------------------------------------------------------------


def _make_db(path, files):
    """files: [(path, [(status, age_days, size), ...])] -> the ids are 1, 2, 3 ... in order."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.executescript("""
        CREATE TABLE files (file_id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL,
            norm_key TEXT NOT NULL UNIQUE, deleted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE versions (version_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL,
            created_at REAL NOT NULL, error TEXT);
        CREATE TABLE objects (sha256 TEXT PRIMARY KEY, size INTEGER, orphaned_since REAL);
        CREATE TABLE version_objects (version_id INTEGER, chunk_index INTEGER, sha256 TEXT);
        """)
    now = time.time()
    for p, versions in files:
        cur = conn.execute(
            "INSERT INTO files(path, norm_key) VALUES (?, ?)", (p, p.lower())
        )
        for status, age_days, size in versions:
            conn.execute(
                "INSERT INTO versions(file_id, size, status, created_at) VALUES (?, ?, ?, ?)",
                (cur.lastrowid, size, status, now - age_days * DAY),
            )
    return conn


def _statuses(conn):
    return {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT f.path, GROUP_CONCAT(DISTINCT v.status) FROM files f "
            "JOIN versions v ON v.file_id = f.file_id GROUP BY f.file_id"
        )
    }


def _healthy_probe(scope_dirs=("/data",)):
    return lambda: vp.Probe(
        scope_dirs,
        isdir=lambda p: True,
        scandir=_scandir_with_one_entry,
        splitdrive=lambda p: ("", p),
        require_parent=True,
    )


class _Entries:
    def __init__(self, entries):
        self._entries = entries

    def __enter__(self):
        return iter(self._entries)

    def __exit__(self, *exc):
        return False


def _scandir_with_one_entry(_root):
    return _Entries(["something"])


def _pass(conn, tmp_path, exists, **kw):
    kw.setdefault("min_age_days", 30)
    kw.setdefault("max_files", 1000)
    kw.setdefault("batch_pause", 0)
    kw.setdefault("probe_factory", _healthy_probe())
    return vp.run_pass(conn, ["/data"], undo_dir=str(tmp_path), exists=exists, **kw)


class _FlagStop:
    """A stand-in for the engine's shutdown event that records every wait."""

    def __init__(self):
        self.flag = False
        self.waits = []

    def is_set(self):
        return self.flag

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.flag


class _SpyLock:
    def __init__(self):
        self.held = False
        self.acquired = 0

    def acquire(self, timeout=None):
        self.held = True
        self.acquired += 1
        return True

    def release(self):
        self.held = False


# -- the probe ---------------------------------------------------------------------------


def test_strict_probe_wants_the_parent_folder_for_a_file_outside_every_tracked_folder():
    probe = vp.Probe(
        ["/data"],
        isdir=lambda p: os.path.abspath(p) == os.path.abspath("/elsewhere"),
        splitdrive=lambda p: ("", p),
        require_parent=True,
    )
    assert probe.reason("/elsewhere/gone.txt") is None  # the parent exists: really gone
    assert "is missing" in probe.reason("/unmounted/share/gone.txt")  # cannot tell


def test_lenient_probe_keeps_the_tools_old_behaviour_outside_tracked_folders():
    probe = vp.Probe(["/data"], isdir=lambda p: False, splitdrive=lambda p: ("", p))
    assert probe.reason("/unmounted/share/gone.txt") is None


def test_scope_problems_names_a_missing_an_empty_and_an_unreadable_folder():
    def scandir(root):
        if root.endswith("empty"):
            return _Entries([])
        if root.endswith("locked"):
            raise PermissionError("denied")
        return _Entries(["x"])

    probe = vp.Probe(
        ["/data/missing", "/data/empty", "/data/locked", "/data/fine"],
        isdir=lambda p: not p.endswith("missing"),
        scandir=scandir,
        splitdrive=lambda p: ("", p),
    )
    problems = probe.scope_problems()
    assert len(problems) == 3
    assert any("missing" in p for p in problems)
    assert any("empty" in p for p in problems)
    assert any("cannot be read" in p for p in problems)
    assert not any("fine" in p for p in problems)


def test_scope_problems_names_an_unreachable_drive():
    probe = vp.Probe(
        ["Z:\\Share"],
        isdir=lambda p: False,
        splitdrive=lambda p: ("Z:", p[2:]),
    )
    assert any("Z:" in p for p in probe.scope_problems())


def test_scope_dirs_come_from_directories_and_roots():
    class Cfg:
        VERSION_TRACK_DIRECTORIES = ["/a"]
        VERSION_TRACK_ROOTS = ["/b"]
        VERSION_TRACK_FILES = ["/c/x.txt"]

    assert vp.scope_dirs_from(Cfg) == ["/a", "/b"]
    assert vp.scope_dirs_from(object()) == []


# -- one pass: what it purges and what it never touches ----------------------------------


def test_a_pass_purges_a_gone_file_and_never_touches_an_existing_or_a_recent_one(
    tmp_path,
):
    conn = _make_db(
        tmp_path / "v.db",
        [
            ("/data/gone.txt", [("completed", 90, 10), ("completed", 60, 20)]),
            ("/data/here.txt", [("completed", 90, 5)]),
            ("/data/gone_recently.txt", [("completed", 2, 7)]),
        ],
    )
    present = {"/data/here.txt"}
    result = _pass(conn, tmp_path, exists=lambda p: p in present)
    assert result.status == "completed"
    assert result.purged_files == 1 and result.purged_versions == 2
    assert result.logical_bytes == 30
    assert _statuses(conn) == {
        "/data/gone.txt": "deleted",
        "/data/here.txt": "completed",
        "/data/gone_recently.txt": "completed",  # younger than the minimum age
    }
    marks = {
        r[0] for r in conn.execute("SELECT error FROM versions WHERE status='deleted'")
    }
    assert marks == {vp.MARK_AUTO}


def test_a_file_with_one_old_and_one_new_version_is_kept_the_newest_decides(tmp_path):
    conn = _make_db(
        tmp_path / "v.db",
        [("/data/gone.txt", [("completed", 90, 1), ("completed", 1, 1)])],
    )
    result = _pass(conn, tmp_path, exists=lambda p: False)
    assert result.purged_versions == 0
    assert _statuses(conn) == {"/data/gone.txt": "completed"}


def test_only_completed_versions_are_soft_deleted(tmp_path):
    conn = _make_db(
        tmp_path / "v.db",
        [("/data/gone.txt", [("completed", 90, 1), ("failed", 90, 1)])],
    )
    _pass(conn, tmp_path, exists=lambda p: False)
    states = sorted(r[0] for r in conn.execute("SELECT status FROM versions"))
    assert states == ["deleted", "failed"]


def test_nothing_runs_while_a_tracked_folder_is_missing(tmp_path):
    conn = _make_db(tmp_path / "v.db", [("/data/gone.txt", [("completed", 90, 1)])])
    missing = lambda: vp.Probe(  # noqa: E731
        ["/data"],
        isdir=lambda p: False,
        splitdrive=lambda p: ("", p),
        require_parent=True,
    )
    seen = []
    result = _pass(
        conn, tmp_path, exists=lambda p: seen.append(p) or False, probe_factory=missing
    )
    assert result.status == "skipped" and "missing" in result.reason
    assert seen == []  # not even a single existence check
    assert _statuses(conn) == {"/data/gone.txt": "completed"}
    assert not [n for n in os.listdir(tmp_path) if n.startswith("purge_undo_")]


def test_nothing_runs_while_a_tracked_folder_is_empty_or_unreadable(tmp_path):
    conn = _make_db(tmp_path / "v.db", [("/data/gone.txt", [("completed", 90, 1)])])
    for scandir in (lambda r: _Entries([]), _raise_permission):
        probe = lambda s=scandir: vp.Probe(  # noqa: E731
            ["/data"],
            isdir=lambda p: True,
            scandir=s,
            splitdrive=lambda p: ("", p),
            require_parent=True,
        )
        result = _pass(conn, tmp_path, exists=lambda p: False, probe_factory=probe)
        assert result.status == "skipped"
    assert _statuses(conn) == {"/data/gone.txt": "completed"}


def _raise_permission(_root):
    raise PermissionError("denied")


def test_a_share_that_vanishes_during_a_slow_pass_stops_the_write_phase(tmp_path):
    conn = _make_db(tmp_path / "v.db", [("/data/gone.txt", [("completed", 90, 1)])])
    calls = []

    def factory():
        calls.append(1)
        if len(calls) == 1:
            return _healthy_probe()()
        return vp.Probe(
            ["/data"],
            isdir=lambda p: False,
            splitdrive=lambda p: ("", p),
            require_parent=True,
        )

    result = _pass(conn, tmp_path, exists=lambda p: False, probe_factory=factory)
    assert result.status == "skipped" and result.reason.startswith("during the pass")
    assert _statuses(conn) == {"/data/gone.txt": "completed"}
    assert not [n for n in os.listdir(tmp_path) if n.startswith("purge_undo_")]


def test_a_file_that_is_back_at_the_last_check_is_dropped_not_purged(tmp_path):
    conn = _make_db(tmp_path / "v.db", [("/data/flaky.txt", [("completed", 90, 1)])])
    answers = iter([False, True])  # missing during the scan, back before the write
    result = _pass(conn, tmp_path, exists=lambda p: next(answers))
    assert result.reappeared == 1 and result.purged_versions == 0
    assert _statuses(conn) == {"/data/flaky.txt": "completed"}
    assert not [n for n in os.listdir(tmp_path) if n.startswith("purge_undo_")]


def test_a_missing_file_outside_every_tracked_folder_needs_its_parent_folder(tmp_path):
    conn = _make_db(
        tmp_path / "v.db",
        [
            ("/lost/mount/a.txt", [("completed", 90, 1)]),
            ("/kept/b.txt", [("completed", 90, 1)]),
        ],
    )
    probe = lambda: vp.Probe(  # noqa: E731
        ["/data"],
        isdir=lambda p: os.path.abspath(p)
        in (os.path.abspath("/data"), os.path.abspath("/kept")),
        scandir=_scandir_with_one_entry,
        splitdrive=lambda p: ("", p),
        require_parent=True,
    )
    result = _pass(conn, tmp_path, exists=lambda p: False, probe_factory=probe)
    assert result.unsure == 1 and "/lost/mount/a.txt" in result.unsure_sample
    assert _statuses(conn) == {
        "/lost/mount/a.txt": "completed",
        "/kept/b.txt": "deleted",
    }


# -- bounded and resumable ---------------------------------------------------------------


def test_the_cap_limits_the_files_looked_at_and_the_cursor_resumes_the_sweep(tmp_path):
    conn = _make_db(
        tmp_path / "v.db",
        [(f"/data/f{i}.txt", [("completed", 90, 1)]) for i in range(10)],
    )
    looked = []

    def exists(p):
        looked.append(p)
        return False

    first = _pass(conn, tmp_path, exists=exists, max_files=4, slice_files=2)
    assert first.examined == 4 and first.cursor_next == 4 and not first.wrapped
    assert first.purged_files == 4
    second = _pass(conn, tmp_path, exists=exists, max_files=4, cursor=first.cursor_next)
    assert second.examined == 4 and second.cursor_next == 8
    third = _pass(conn, tmp_path, exists=exists, max_files=4, cursor=second.cursor_next)
    assert third.examined == 2 and third.wrapped and third.cursor_next == 0
    # every file is looked at once in its slice and once more right before the write
    assert len(set(looked)) == 10 and len(looked) == 20
    assert set(_statuses(conn).values()) == {"deleted"}


def test_the_pauses_between_slices_are_proportional_and_never_below_the_batch_pause(
    tmp_path,
):
    conn = _make_db(
        tmp_path / "v.db",
        [(f"/data/f{i}.txt", [("completed", 90, 1)]) for i in range(8)],
    )
    stop = _FlagStop()

    def slow_exists(p):
        time.sleep(0.02)
        return True

    _pass(
        conn, tmp_path, exists=slow_exists, slice_files=4, batch_pause=0.01, stop=stop
    )
    assert len(stop.waits) == 2  # after each full slice; none once the table has ended
    assert min(stop.waits) >= 3 * 0.05  # three times the slice (4 x 0.02 s), with slack

    stop2 = _FlagStop()
    _pass(
        conn,
        tmp_path,
        exists=lambda p: True,
        slice_files=4,
        batch_pause=0.7,
        stop=stop2,
    )
    assert stop2.waits and min(stop2.waits) >= 0.7  # the configured pause is the floor


def test_a_pass_does_not_check_more_files_than_the_cap_even_with_a_big_slice(tmp_path):
    conn = _make_db(
        tmp_path / "v.db",
        [(f"/data/f{i}.txt", [("completed", 90, 1)]) for i in range(10)],
    )
    looked = []
    _pass(
        conn,
        tmp_path,
        exists=lambda p: looked.append(p) or True,
        max_files=3,
        slice_files=200,
    )
    assert len(looked) == 3


# -- stop -------------------------------------------------------------------------------


def test_a_stop_during_the_scan_changes_nothing_and_leaves_the_cursor_alone(tmp_path):
    conn = _make_db(
        tmp_path / "v.db",
        [(f"/data/f{i}.txt", [("completed", 90, 1)]) for i in range(6)],
    )
    stop = _FlagStop()
    seen = []

    def exists(p):
        seen.append(p)
        if len(seen) == 3:
            stop.flag = True  # the shutdown arrives in the middle of the scan
        return False

    result = _pass(conn, tmp_path, exists=exists, stop=stop, cursor=0)
    assert result.status == "stopped"
    assert result.cursor_next == 0 and len(seen) == 3
    assert set(_statuses(conn).values()) == {"completed"}
    assert not [n for n in os.listdir(tmp_path) if n.startswith("purge_undo_")]


def test_a_stop_between_write_batches_keeps_what_is_done_and_the_undo_file_lists_all(
    tmp_path, monkeypatch
):
    conn = _make_db(
        tmp_path / "v.db",
        [(f"/data/f{i}.txt", [("completed", 90, 1)]) for i in range(6)],
    )
    stop = _FlagStop()
    real = vp.soft_delete

    def one_batch_then_stop(conn_, ids, **kw):
        calls = []

        def should_stop():
            calls.append(1)
            if len(calls) > 1:
                stop.flag = True
            return stop.flag

        kw["should_stop"] = should_stop
        return real(conn_, ids, **kw)

    monkeypatch.setattr(vp, "soft_delete", one_batch_then_stop)
    result = _pass(conn, tmp_path, exists=lambda p: False, stop=stop, write_batch=2)
    assert result.status == "stopped"
    assert result.purged_versions == 2 and result.cursor_next == 0
    assert sorted(_statuses(conn).values()).count("deleted") == 2
    undo = json.loads(Path(result.undo_file).read_text(encoding="utf-8"))
    assert len(undo["version_ids"]) == 6  # every version the pass meant to touch


# -- the undo record and the locks -------------------------------------------------------


def test_the_undo_file_exists_before_the_first_row_changes(tmp_path, monkeypatch):
    conn = _make_db(tmp_path / "v.db", [("/data/gone.txt", [("completed", 90, 1)])])
    real = vp.soft_delete
    checked = []

    def check_then_delete(conn_, ids, **kw):
        files = [n for n in os.listdir(tmp_path) if n.startswith(vp.AUTO_UNDO_PREFIX)]
        assert len(files) == 1
        data = json.loads((tmp_path / files[0]).read_text(encoding="utf-8"))
        assert data["version_ids"] == ids
        checked.append(True)
        return real(conn_, ids, **kw)

    monkeypatch.setattr(vp, "soft_delete", check_then_delete)
    _pass(conn, tmp_path, exists=lambda p: False)
    assert checked == [True]


def test_the_write_lock_is_held_for_the_write_phase_only(tmp_path, monkeypatch):
    conn = _make_db(
        tmp_path / "v.db",
        [(f"/data/f{i}.txt", [("completed", 90, 1)]) for i in range(3)],
    )
    lock = _SpyLock()
    held_while_checking = []
    held_while_writing = []
    real = vp.soft_delete

    def exists(p):
        held_while_checking.append(lock.held)
        return False

    def spy_delete(conn_, ids, **kw):
        held_while_writing.append(lock.held)
        return real(conn_, ids, **kw)

    monkeypatch.setattr(vp, "soft_delete", spy_delete)
    _pass(conn, tmp_path, exists=exists, write_lock=lock)
    # the 3 scan-phase checks run with the lock free; only the last look before the write
    # (3 more calls) is made while holding it
    assert held_while_checking[:3] == [False] * 3
    assert held_while_checking[3:] == [True] * 3
    assert held_while_writing == [True]
    assert lock.acquired == 1 and lock.held is False  # released again


def test_a_stop_while_waiting_for_the_lock_gives_up_without_writing(tmp_path):
    conn = _make_db(tmp_path / "v.db", [("/data/gone.txt", [("completed", 90, 1)])])
    lock = threading.Lock()
    lock.acquire()  # the garbage collector is running
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    started = time.monotonic()
    result = _pass(conn, tmp_path, exists=lambda p: False, write_lock=lock, stop=stop)
    assert result.status == "stopped"
    assert time.monotonic() - started < 3  # polls the stop event, does not hang
    assert _statuses(conn) == {"/data/gone.txt": "completed"}


def test_the_undo_file_is_written_atomically_and_never_overwritten(tmp_path):
    first = vp.write_undo_file(str(tmp_path), [1, 2, 3], now=1_700_000_000)
    second = vp.write_undo_file(str(tmp_path), [4], now=1_700_000_000)
    assert first != second
    assert json.loads(Path(first).read_text(encoding="utf-8"))["version_ids"] == [
        1,
        2,
        3,
    ]
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]
    assert Path(first).name.startswith("purge_undo_auto_")
    # the tool's own listing still finds it
    found = vp.list_undo_files(str(tmp_path))
    assert {p for p, _c, _n in found} == {first, second}


def test_pruning_removes_only_old_automatic_undo_files(tmp_path):
    old_auto = tmp_path / "purge_undo_auto_20250101_000000.json"
    new_auto = tmp_path / "purge_undo_auto_20260101_000000.json"
    manual = tmp_path / "purge_undo_20250101_000000.json"
    for f in (old_auto, new_auto, manual):
        f.write_text(json.dumps({"created": 0, "version_ids": []}), encoding="utf-8")
    long_ago = time.time() - 10 * DAY
    os.utime(old_auto, (long_ago, long_ago))
    os.utime(manual, (long_ago, long_ago))
    assert vp.prune_auto_undo_files(str(tmp_path), 2 * DAY) == 1
    assert not old_auto.exists() and new_auto.exists() and manual.exists()


def test_an_automatic_purge_can_be_undone_while_the_chunks_exist(tmp_path):
    conn = _make_db(tmp_path / "v.db", [("/data/gone.txt", [("completed", 90, 1)])])
    chunk = tmp_path / "chunk"
    chunk.write_bytes(b"x")
    conn.execute("INSERT INTO objects(sha256, size) VALUES ('aa', 1)")
    conn.execute("INSERT INTO version_objects VALUES (1, 0, 'aa')")
    result = _pass(conn, tmp_path, exists=lambda p: False)
    ids = json.loads(Path(result.undo_file).read_text(encoding="utf-8"))["version_ids"]
    restored, skipped = vp.undo_versions(conn, ids, lambda sha: str(chunk))
    assert (restored, skipped) == (1, 0)
    assert _statuses(conn) == {"/data/gone.txt": "completed"}


# -- the tool still sees the moved names -------------------------------------------------


def test_the_tool_still_exports_the_names_its_tests_use():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "purge_tool", ROOT / "tools" / "purge_missing_versions.py"
    )
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert tool._Probe is vp.Probe and tool._MARK == vp.MARK and tool._BATCH == vp.BATCH
    assert tool.scan_tracked is vp.scan_tracked and tool.soft_delete is vp.soft_delete
    assert tool.undo_versions is vp.undo_versions and tool.Scan is vp.Scan


# -- the hard rule: no asyncio anywhere in the purge -------------------------------------

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


def test_the_shared_helper_uses_no_asyncio_and_no_thread_pool():
    assert _async_findings(_tree("helpers/version_purge.py")) == []


def test_the_whole_version_engine_file_uses_no_asyncio_and_no_thread_pool():
    """The engine is a separate worker process with plain threads; the purge must keep it so."""
    assert _async_findings(_tree("version_engine.py")) == []


# -- how the engine wires it in ----------------------------------------------------------


def _engine_method(name):
    """A method of class Engine (the module also has a function called start / stop)."""
    for cls in ast.walk(_tree("version_engine.py")):
        if isinstance(cls, ast.ClassDef) and cls.name == "Engine":
            for node in cls.body:
                if isinstance(node, ast.FunctionDef) and node.name == name:
                    return node
    raise AssertionError(f"Engine.{name} not found in version_engine.py")


def _source(node):
    return ast.unparse(node)


def test_the_purge_thread_is_its_own_named_daemon_thread_started_only_when_enabled():
    start = _source(_engine_method("start"))
    assert "VERSION_PURGE_MISSING_ENABLED" in start
    assert "name='ve-purge'" in start and "daemon=True" in start
    assert "target=self._purge_loop" in start
    assert start.index("VERSION_PURGE_MISSING_ENABLED") < start.index("ve-purge")


def test_the_purge_loop_waits_on_the_engines_shutdown_event_like_the_scanner():
    loop = _source(_engine_method("_purge_loop"))
    assert "self._shutdown_event.is_set()" in loop
    assert "self._shutdown_event.wait(" in loop
    assert "self._stop_scheduling.is_set()" in loop
    assert "time.sleep" not in loop  # a sleep could not be cut short by the shutdown
    assert "_next_pass_wait(" in loop  # the same proportional back-off as the scan


def test_a_pass_gets_the_shutdown_event_and_the_maintenance_lock():
    run = _source(_engine_method("run_purge_missing_pass"))
    assert "stop=self._shutdown_event" in run
    assert "write_lock=self._maintenance_lock" in run
    assert "self._purge_pass_lock.acquire(blocking=False)" in run  # one pass at a time
    assert "VERSION_PURGE_MISSING_ENABLED" in run  # off means off, whoever calls


def test_the_garbage_collector_and_the_purge_share_one_lock():
    gc = _source(_engine_method("run_gc"))
    assert "with self._maintenance_lock" in gc and "_run_gc_unlocked" in gc
    assert "run_gc" in _source(
        _engine_method("_scanner_loop")
    )  # still run by the scanner


def test_graceful_shutdown_joins_the_purge_thread_within_the_drain_window():
    shutdown = _source(_engine_method("graceful_shutdown"))
    assert "self._purge_thread.join(" in shutdown
    assert "deadline" in shutdown[shutdown.index("_purge_thread.join") :].split("\n")[0]


def test_the_settings_are_clamped_before_use():
    settings = _source(_engine_method("_purge_settings"))
    assert "max(60.0" in settings  # interval floor
    assert "min(" in settings and "5.0" in settings  # batch pause ceiling
    assert "max(1," in settings  # at least one file per pass


# -- config ------------------------------------------------------------------------------


def _config_assignments():
    out = {}
    for node in _tree("config.py").body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.startswith(
                "VERSION_PURGE_MISSING"
            ):
                out[target.id] = ast.literal_eval(node.value)
    return out


def test_config_defaults_are_on_with_conservative_limits():
    assert _config_assignments() == {
        "VERSION_PURGE_MISSING_ENABLED": True,
        "VERSION_PURGE_MISSING_MIN_AGE_DAYS": 30,
        "VERSION_PURGE_MISSING_INTERVAL": 3600,
        "VERSION_PURGE_MISSING_MAX_FILES_PER_PASS": 5000,
        "VERSION_PURGE_MISSING_BATCH_PAUSE": 0.05,
    }


def _config_function(name):
    for node in _tree("config.py").body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            namespace = {}
            exec(
                compile(ast.Module([node], []), "config.py", "exec"), namespace
            )  # noqa: S102
            return namespace[name]
    raise AssertionError(name)


def test_a_hand_edited_value_cannot_leave_the_purge_on_or_remove_its_throttle():
    flag = _config_function("_bool_fail_safe")
    assert flag(None, True) is True  # the key is missing: the default (on) applies
    assert flag(True, True) is True and flag(False, True) is False
    for bad in ("true", "false", "no", 1, 0, [], {}):
        assert flag(bad, True) is False  # not a real JSON boolean: OFF, never on
    bounded = _config_function("_bounded_number")
    assert bounded(120, 3600, 60, 86400) == 120
    for bad in ("soon", None, True, 5, 10**9, -1, [], float("nan")):
        assert bounded(bad, 3600, 60, 86400) == 3600


def test_the_loader_reads_all_five_keys_through_the_validators():
    text = (ROOT / "config.py").read_text(encoding="utf-8")
    for key in (
        "VERSION_PURGE_MISSING_ENABLED",
        "VERSION_PURGE_MISSING_MIN_AGE_DAYS",
        "VERSION_PURGE_MISSING_INTERVAL",
        "VERSION_PURGE_MISSING_MAX_FILES_PER_PASS",
        "VERSION_PURGE_MISSING_BATCH_PAUSE",
    ):
        assert f'"{key}": {key},' in text, f"{key} is not saved by save_server_config"
        assert f'config.get("{key}")' in text, f"{key} is not loaded"
