"""
5.44 (ASYNC_BLOCKING_REFACTOR_PLAN, T9 part B item 1): what one request learns about the login
state and the role is looked up ONCE. Every lookup is a SQLite open on the event-loop thread; a
request on a @login_required route used to make up to 10 of them before its handler ran.

The REAL functions are cut out of `auth.py` with `ast` (auth.py imports the database module) and
run with a fake `g` (one per request), a fake `session` and a counting fake `db`. The point of
the memo is that it may never make an answer OLDER than the session it describes, so most tests
below are about when it must NOT be used.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
AUTH_PATH = ROOT / "auth.py"
FUNCTIONS = (
    "forget_request_auth",
    "get_role",
    "login_user",
    "logout_user",
    "current_user",
    "is_logged_in",
    "revoke_current_session",
    "request_is_logged_in",
)
CONSTANTS = ("_LOGIN_MEMO", "_ROLE_MEMO")


class FakeG:
    """The attribute bag Quart gives each request (get / pop / setattr)."""

    def get(self, name, default=None):
        return self.__dict__.get(name, default)

    def pop(self, name, default=None):
        return self.__dict__.pop(name, default)


class FakeSession:
    """The part of Quart's session the auth functions use: a mapping with get / [] / in / pop /
    clear, a `permanent` flag, and a record that clear() was called. A plain class around a dict
    (not a dict subclass): a subclass that adds attributes without overriding __eq__ is a CodeQL
    warning, and nothing here compares sessions."""

    def __init__(self, data=None):
        self.data = dict(data or {})
        self.permanent = False
        self.cleared = False

    def get(self, key, default=None):
        return self.data.get(key, default)

    def pop(self, key, default=None):
        return self.data.pop(key, default)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __contains__(self, key):
        return key in self.data

    def clear(self):
        self.cleared = True
        self.data.clear()


class CountingDb:
    def __init__(self, roles=None, token="t1", revoked=()):  # noqa: S107 - a fake token
        self.roles = (
            {"alice": "readwrite", "bob": "readonly"} if roles is None else roles
        )
        self.token = token
        self.revoked = set(revoked)
        self.opens = (
            0  # every method below is one SQLite open in the real database module
        )

    def get_server_token(self):
        self.opens += 1
        return self.token

    def get_role(self, username):
        self.opens += 1
        return self.roles.get(username)

    def is_session_revoked(self, session_id):
        self.opens += 1
        return session_id in self.revoked

    def revoke_session(self, session_id):
        self.opens += 1
        self.revoked.add(session_id)

    def update_last_login(self, username):
        self.opens += 1


def _login(**extra):
    data = {
        "username": "alice",
        "logged_in": True,
        "server_token": "t1",
        "session_id": "sid-1",
    }
    data.update(extra)
    return FakeSession(data)


def _load(session, db, in_context=True):
    tree = ast.parse(AUTH_PATH.read_text(encoding="utf-8"))
    wanted, seen = [], set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            wanted.append(node)
            seen.add(node.name)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets
        ):
            wanted.append(node)
    assert seen == set(FUNCTIONS), f"auth.py lost {set(FUNCTIONS) - seen}"
    namespace = {
        "session": session,
        "db": db,
        "g": FakeG(),
        "has_app_context": lambda: in_context,
        "print": lambda *a, **k: None,
    }
    exec(
        compile(ast.Module(body=wanted, type_ignores=[]), str(AUTH_PATH), "exec"),
        namespace,
    )  # noqa: S102
    return namespace


# ------------------------------------------------------------------ fewer opens per request


def test_a_whole_request_costs_four_opens_instead_of_ten():
    db = CountingDb()
    auth = _load(_login(), db)
    # the sequence of one request: validate_session's role lookup, before_request,
    # login_required, the handler's own role lookup, after_request
    assert auth["get_role"]("alice") == "readwrite"
    assert auth["request_is_logged_in"]() is True
    assert auth["request_is_logged_in"]() is True
    assert auth["get_role"]("alice") == "readwrite"
    assert auth["request_is_logged_in"]() is True
    # token + role + revoked-list for the first check, one role lookup for the memoised role
    assert db.opens == 4


def test_the_same_sequence_with_the_plain_functions_costs_ten():
    # documents the old behaviour the memo removes
    db = CountingDb()
    auth = _load(_login(), db)
    db_get_role = db.get_role
    for _ in range(3):
        assert auth["is_logged_in"]() is True
    db_get_role("alice")
    assert db.opens == 10


def test_without_an_application_context_nothing_is_remembered():
    db = CountingDb()
    auth = _load(_login(), db, in_context=False)
    auth["get_role"]("alice")
    auth["get_role"]("alice")
    auth["request_is_logged_in"]()
    auth["request_is_logged_in"]()
    assert db.opens == 2 + 3 + 3


# --------------------------------------------------- the memo must never outlive the session


def test_a_logout_inside_the_request_is_seen_by_the_next_check():
    db = CountingDb()
    session = _login()
    auth = _load(session, db)
    assert auth["request_is_logged_in"]() is True
    auth["logout_user"]()
    assert auth["request_is_logged_in"]() is False
    assert db.revoked == {"sid-1"}


def test_a_session_cleared_without_logout_user_is_seen_too():
    # routes/login.py and middleware.py call session.clear() directly in several places
    db = CountingDb()
    session = _login()
    auth = _load(session, db)
    assert auth["request_is_logged_in"]() is True
    opens = db.opens
    session.clear()
    assert auth["request_is_logged_in"]() is False
    assert db.opens == opens  # no name in the session: refused without a database call


def test_another_user_in_the_same_session_object_is_checked_again():
    db = CountingDb()
    session = _login()
    auth = _load(session, db)
    assert auth["request_is_logged_in"]() is True
    session["username"] = "ghost"  # a user that does not exist
    assert auth["request_is_logged_in"]() is False
    assert session.cleared


def test_a_new_session_id_is_checked_again():
    db = CountingDb(revoked={"sid-2"})
    session = _login()
    auth = _load(session, db)
    assert auth["request_is_logged_in"]() is True
    session["session_id"] = "sid-2"
    assert auth["request_is_logged_in"]() is False


@pytest.mark.parametrize(
    "extra",
    [
        {"server_token": "old"},  # token rotated
        {"username": "ghost"},  # user deleted
        {"session_id": "sid-ended"},  # logged out elsewhere
        {"logged_in": False},
    ],
)
def test_the_ways_a_session_ends_are_refused_on_the_first_check_of_a_request(extra):
    db = CountingDb(revoked={"sid-ended"})
    session = _login(**extra)
    auth = _load(session, db)
    assert auth["request_is_logged_in"]() is False
    assert auth["request_is_logged_in"]() is False  # and stays refused


def test_a_false_answer_is_not_remembered():
    db = CountingDb(token="rotated")  # noqa: S106 - a fake token
    session = _login()
    auth = _load(session, db)
    assert auth["request_is_logged_in"]() is False  # stale token: session cleared
    # a login in the same request rebuilds the session with the NEW token
    auth["login_user"]("alice")
    assert auth["request_is_logged_in"]() is True


def test_each_request_starts_with_an_empty_memo():
    db = CountingDb()
    session = _login()
    first = _load(session, db)
    assert first["request_is_logged_in"]() is True
    opens = db.opens
    second = _load(session, db)  # a new request: a new `g`
    assert second["request_is_logged_in"]() is True
    assert db.opens == opens + 3


# --------------------------------------------------------------------------- the role memo


def test_login_drops_the_role_remembered_earlier_in_the_request():
    db = CountingDb()
    auth = _load(FakeSession(), db)
    assert auth["get_role"]("bob") == "readonly"
    db.roles["bob"] = "readwrite"
    assert auth["get_role"]("bob") == "readonly"  # still the memo inside one request
    auth["login_user"]("bob")
    assert auth["get_role"]("bob") == "readwrite"


def test_a_missing_user_is_remembered_as_missing_for_the_request_only():
    db = CountingDb()
    auth = _load(FakeSession(), db)
    assert auth["get_role"]("nobody") is None
    assert auth["get_role"]("nobody") is None
    assert db.opens == 1


def test_the_hooks_and_login_required_use_the_memoised_check():
    for name, funcs in {
        "middleware.py": {"before_request", "after_request"},
        "core.py": {"decorated"},
        "routes/login.py": {"check_session"},
        "routes/stats.py": {
            "monitoring_status",
            "storage_stats_poll",
            "storage_stats_stream",
        },
    }.items():
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in funcs:
                called = {
                    ast.unparse(c.func)
                    for c in ast.walk(node)
                    if isinstance(c, ast.Call)
                }
                assert "is_logged_in" not in called, f"{name}:{node.name}"
                assert "request_is_logged_in" in called, f"{name}:{node.name}"
                found.add(node.name)
        assert found == funcs, f"{name}: {funcs - found} not found"
