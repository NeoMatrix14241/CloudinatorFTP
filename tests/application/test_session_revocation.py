"""Logout ends the session on the SERVER (CLAUDE.md 5.17).

The session is a signed cookie, so clearing it only empties the copy in the browser that logged
out; a copy taken earlier used to stay valid. Now logout records the session id in the
`revoked_sessions` table (database.py) and auth.is_logged_in() refuses a listed id.

Everything is read out of auth.py / database.py / routes/login.py with `ast` and run against
fakes and a temporary SQLite file, so no app and no scratch server is needed. The end-to-end
check (a copied cookie is rejected after logout) is in tests/application/test_login.py.
"""

import ast
import re
import sqlite3
import textwrap
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _source(name):
    return (ROOT / name).read_text(encoding="utf-8")


def _function(source, name):
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{name} not found")


class FakeSession(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cleared = False

    def clear(self):
        self.cleared = True
        super().clear()


class FakeDb:
    def __init__(self, token="t1", roles=None, revoked=()):
        self.token = token
        self.roles = {"alice": "readwrite"} if roles is None else roles
        self.revoked = set(revoked)
        self.recorded = []
        self.checked = []

    def get_server_token(self):
        return self.token

    def get_role(self, username):
        return self.roles.get(username)

    def is_session_revoked(self, session_id):
        self.checked.append(session_id)
        return session_id in self.revoked

    def revoke_session(self, session_id):
        self.recorded.append(session_id)


def _auth(session, db):
    source = _source("auth.py")
    code = "\n\n".join(
        _function(source, n) for n in ("is_logged_in", "revoke_current_session")
    )
    namespace = {"session": session, "db": db}
    exec(code, namespace)
    return namespace


def _login(**extra):
    data = {
        "username": "alice",
        "logged_in": True,
        "server_token": "t1",
        "session_id": "sid-1",
    }
    data.update(extra)
    return FakeSession(data)


def test_a_normal_session_is_logged_in():
    db = FakeDb()
    assert _auth(_login(), db)["is_logged_in"]() is True
    assert db.checked == ["sid-1"]


def test_a_session_whose_id_was_ended_is_refused_and_cleared():
    session, db = _login(), FakeDb(revoked={"sid-1"})
    assert _auth(session, db)["is_logged_in"]() is False
    assert session.cleared


def test_another_session_of_the_same_user_is_not_affected():
    db = FakeDb(revoked={"sid-1"})
    assert _auth(_login(session_id="sid-2"), db)["is_logged_in"]() is True


@pytest.mark.parametrize(
    "extra",
    [{"server_token": "old"}, {"username": "ghost"}, {"logged_in": False}],
)
def test_the_other_ways_a_session_ends_still_work(extra):
    assert _auth(_login(**extra), FakeDb())["is_logged_in"]() is False


def test_a_session_without_an_id_cannot_be_listed_and_stays_valid():
    # /login always sets an id; this only documents what an id-less session does.
    db = FakeDb()
    assert _auth(_login(session_id=None), db)["is_logged_in"]() is True


def test_revoke_current_session_records_the_id_before_the_cookie_is_cleared():
    session, db = _login(), FakeDb()
    _auth(session, db)["revoke_current_session"]()
    assert db.recorded == ["sid-1"]


def test_revoke_current_session_without_an_id_does_nothing():
    session, db = _login(session_id=None), FakeDb()
    _auth(session, db)["revoke_current_session"]()
    assert db.recorded == []


def test_a_database_error_never_blocks_the_logout():
    class Broken(FakeDb):
        def revoke_session(self, session_id):
            raise sqlite3.OperationalError("database is locked")

    _auth(_login(), Broken())["revoke_current_session"]()  # must not raise


def test_the_logout_route_revokes_before_it_clears_the_session():
    source = _source("routes/login.py")
    logout = next(
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "logout"
    )
    try_block = logout.body[0]
    assert isinstance(try_block, ast.Try)
    calls = []
    for node in ast.walk(ast.Module(body=try_block.body, type_ignores=[])):
        if isinstance(node, ast.Call):
            calls.append((node.lineno, ast.unparse(node.func)))
    revoke = [line for line, name in calls if name == "revoke_current_session"]
    clear = [line for line, name in calls if name == "session.clear"]
    assert revoke and clear and min(revoke) < min(clear)


# ---- the two database methods, on a real SQLite file ----------------------------------


@pytest.fixture()
def database(tmp_path):
    source = _source("database.py")
    table = re.search(
        r"CREATE TABLE IF NOT EXISTS revoked_sessions \(.*?\);", source, re.DOTALL
    )
    assert table, "revoked_sessions table is no longer created by database.py"
    cls = next(
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.ClassDef) and n.name == "_Database"
    )
    wanted = {"REVOKED_SESSION_KEEP_SECS", "revoke_session", "is_session_revoked"}
    parts = []
    for node in cls.body:
        name = getattr(node, "name", None)
        if name is None and isinstance(node, ast.Assign):
            name = node.targets[0].id
        if name in wanted:
            parts.append(
                textwrap.dedent(ast.get_source_segment(source, node, padded=True))
            )
    assert len(parts) == len(wanted)
    body = textwrap.indent("\n\n".join(parts), "    ")
    db_file = tmp_path / "t.db"

    def connect():
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        return conn

    setup = connect()
    setup.execute(table.group(0))
    setup.commit()
    setup.close()
    namespace = {"_connect": connect, "_write_lock": threading.Lock()}
    exec("class Db:\n" + body, namespace)
    instance = namespace["Db"]()
    instance.file = db_file
    return instance


def test_revoked_ids_are_remembered(database):
    assert not database.is_session_revoked("sid-1")
    database.revoke_session("sid-1")
    assert database.is_session_revoked("sid-1")
    assert not database.is_session_revoked("sid-2")


def test_revoking_twice_is_harmless(database):
    database.revoke_session("sid-1")
    database.revoke_session("sid-1")
    assert database.is_session_revoked("sid-1")


@pytest.mark.parametrize("bad", [None, "", 5])
def test_unusable_ids_are_ignored(database, bad):
    database.revoke_session(bad)
    assert not database.is_session_revoked(bad)
    conn = sqlite3.connect(database.file)
    assert conn.execute("SELECT COUNT(*) FROM revoked_sessions").fetchone()[0] == 0
    conn.close()


def test_old_rows_are_purged_when_a_new_one_is_added(database):
    conn = sqlite3.connect(database.file)
    old = database.REVOKED_SESSION_KEEP_SECS + 3600
    conn.execute(
        "INSERT INTO revoked_sessions(session_id, revoked_at) "
        "VALUES('ancient', unixepoch() - ?)",
        (old,),
    )
    conn.commit()
    conn.close()
    database.revoke_session("fresh")
    assert database.is_session_revoked("fresh")
    assert not database.is_session_revoked("ancient")


def test_rows_are_kept_longer_than_a_cookie_can_live(database):
    # PERMANENT_SESSION_LIFETIME is 24 h; a row must outlive any cookie it guards.
    assert database.REVOKED_SESSION_KEEP_SECS >= 7 * 24 * 3600
