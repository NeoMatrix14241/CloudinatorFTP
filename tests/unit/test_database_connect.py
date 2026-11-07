"""
5.44 (ASYNC_BLOCKING_REFACTOR_PLAN, T9 part B item 2 and the part A probe): `database._connect()`.

* the folder and `PRAGMA journal_mode=WAL` (stored IN the database file) are done by the first
  open of the process only; `PRAGMA foreign_keys=ON` is per connection and stays on every open;
* the bootstrap still runs exactly once and its commit still happens before the flag is set
  (the WAL snapshot lesson in the comments of `_connect`);
* an open slower than `_SLOW_OPEN_SECS` is logged, at most once a second, with the thread name.

The REAL function is cut out of `database.py` with `ast` (the module reads the config and the
data folder on import) and run against a real temporary SQLite file through a recording shim.
"""

import ast
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATABASE_PATH = ROOT / "database.py"
NAMES = {"_SLOW_OPEN_SECS", "_slow_open_state", "_connect"}


class RecordingConnection:
    def __init__(self, real, log):
        self._real, self._log = real, log
        self.row_factory = None

    def execute(self, sql, *args):
        self._log.append(sql)
        return self._real.execute(sql, *args)

    def commit(self):
        self._log.append("COMMIT")
        return self._real.commit()


class SqliteShim:
    Row = sqlite3.Row
    Connection = sqlite3.Connection  # the return annotation of _connect

    def __init__(self, log):
        self._log = log

    def connect(self, path, **kwargs):
        self._log.append("CONNECT")
        return RecordingConnection(sqlite3.connect(path, **kwargs), self._log)


class OsShim:
    def __init__(self, log):
        self._log = log

    def makedirs(self, path, exist_ok=False):
        self._log.append("MAKEDIRS")
        Path(path).mkdir(parents=True, exist_ok=exist_ok)


def _load(tmp_path, slow_secs=None):
    tree = ast.parse(DATABASE_PATH.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_connect":
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in NAMES for t in node.targets
        ):
            nodes.append(node)
    assert {getattr(n, "name", None) for n in nodes} >= {"_connect"}, "_connect is gone"
    log, printed = [], []
    state = {"done": False}

    def fake_bootstrap(conn):
        log.append("BOOTSTRAP")
        conn.execute("CREATE TABLE IF NOT EXISTS users (name TEXT)")

    namespace = {
        "os": OsShim(log),
        "sqlite3": SqliteShim(log),
        "threading": threading,
        "time": time,
        "_DB_DIR": str(tmp_path / "data"),
        "DB_PATH": str(tmp_path / "data" / "cloudinator.db"),
        "_bootstrap_state": state,
        "_bootstrap_lock": threading.Lock(),
        "_do_bootstrap": fake_bootstrap,
        "print": lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(DATABASE_PATH), "exec"),
        namespace,
    )  # noqa: S102
    if slow_secs is not None:
        namespace["_SLOW_OPEN_SECS"] = slow_secs
    return namespace, log, printed, state


def test_folder_wal_and_bootstrap_happen_on_the_first_open_only(tmp_path):
    ns, log, _printed, state = _load(tmp_path)
    for _ in range(3):
        ns["_connect"]()
    assert log.count("MAKEDIRS") == 1
    assert log.count("PRAGMA journal_mode=WAL") == 1
    assert log.count("PRAGMA foreign_keys=ON") == 3
    assert log.count("BOOTSTRAP") == 1
    assert state["done"] is True


def test_the_bootstrap_is_committed_before_the_flag_is_set(tmp_path):
    ns, log, _printed, _state = _load(tmp_path)
    ns["_connect"]()
    assert log.index("BOOTSTRAP") < log.index("COMMIT")


def test_the_database_file_really_is_in_wal_mode_for_later_connections(tmp_path):
    ns, _log, _printed, _state = _load(tmp_path)
    ns["_connect"]()
    later = sqlite3.connect(ns["DB_PATH"])
    assert later.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    later.close()


def test_foreign_keys_are_on_for_every_connection(tmp_path):
    ns, _log, _printed, _state = _load(tmp_path)
    ns["_connect"]()
    second = ns["_connect"]()
    assert second._real.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_a_slow_open_is_logged_with_the_thread_name_and_rate_limited(tmp_path):
    ns, _log, printed, _state = _load(
        tmp_path, slow_secs=0.0
    )  # every open counts as slow
    ns["_connect"]()
    ns["_connect"]()
    ns["_connect"]()
    slow = [line for line in printed if "Slow SQLite open" in line]
    assert len(slow) == 1  # at most one line a second
    assert threading.current_thread().name in slow[0]


def test_a_fast_open_logs_nothing(tmp_path):
    ns, _log, printed, _state = _load(tmp_path, slow_secs=60.0)
    ns["_connect"]()
    assert not printed
