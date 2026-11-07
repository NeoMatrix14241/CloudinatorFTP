"""
auth.py — Authentication helpers for CloudinatorFTP
-----------------------------------------------------
All user data and the server token now live in cloudinator.db (SQLite).
users.json and session_token.txt are no longer used.
"""

from quart import g, has_app_context, session
from database import db

# 5.44 (ASYNC_BLOCKING_REFACTOR_PLAN, T9 part B items 1 and 2): what ONE request learns about
# who is logged in is looked up once, not once per hook. Every lookup is a SQLite open on the
# event-loop thread; before this a request on a @login_required route did up to 10 of them
# before its handler ran. The memo lives on Quart's `g`, i.e. for ONE request only, so a
# deleted user, a rotated server token or an ended session still take effect on the very next
# request (guidelines 5.2 / 5.3). Names of the two `g` attributes:
_LOGIN_MEMO = "_auth_login_memo"
_ROLE_MEMO = "_auth_role_memo"


def check_login(username: str, password: str) -> bool:
    """Verify credentials. Always reads live from DB — never stale."""
    return db.check_login(username, password)


def forget_request_auth() -> None:
    """Drop what this request remembers about the login state and the role.

    Called wherever the session is rebuilt inside a request (login_user, logout_user).
    """
    if has_app_context():
        g.pop(_LOGIN_MEMO, None)
        g.pop(_ROLE_MEMO, None)


def get_role(username: str) -> str | None:
    """Return 'readwrite', 'readonly', or None if user doesn't exist.

    Remembered per request (5.44): the hooks and the handler of one request ask for the same
    user's role several times, and each ask is a SQLite open. Nothing in a request changes a
    user's role or deletes a user, and `forget_request_auth()` clears the memo at login/logout.
    """
    if not has_app_context():
        return db.get_role(username)
    memo = g.get(_ROLE_MEMO)
    if memo is None:
        memo = {}
        setattr(g, _ROLE_MEMO, memo)
    if username not in memo:
        memo[username] = db.get_role(username)
    return memo[username]


def login_user(username: str):
    """Stamp the session with the current server token."""
    forget_request_auth()
    session.clear()
    session.permanent = True
    session["username"] = username
    session["role"] = db.get_role(username)
    session["logged_in"] = True
    session["server_token"] = db.get_server_token()  # token from DB
    db.update_last_login(username)


def revoke_current_session() -> None:
    """Record the current session's id as ended, so a COPY of its cookie stops working too.

    Call it BEFORE session.clear() (the id lives in the session). Never raises: a database
    problem must not stop a logout; the cookie is still cleared by the caller."""
    session_id = session.get("session_id")
    if not session_id:
        return
    try:
        db.revoke_session(session_id)
    except Exception as exc:
        print(f"⚠️ Could not record the ended session: {exc}")


def logout_user():
    revoke_current_session()
    session.clear()
    forget_request_auth()


def current_user() -> str | None:
    return session.get("username")


def is_logged_in() -> bool:
    """
    Returns True only when:
      1. The session has a logged_in flag and a username
      2. The session's server_token still matches the DB token
         (rotating the token via revoke_session.py invalidates all sessions)
      3. The user still exists in the DB
         (deleting a user immediately invalidates their session)
      4. The session's id was not ended by a logout (5.17): a copy of a cookie that was
         logged out stays refused. (A session without an id cannot be listed; /login always
         sets one.)
    """
    username = session.get("username")
    if not username or not session.get("logged_in"):
        return False

    if session.get("server_token") != db.get_server_token():
        session.clear()
        return False

    if db.get_role(username) is None:  # user was deleted
        session.clear()
        return False

    if db.is_session_revoked(session.get("session_id")):  # logged out
        session.clear()
        return False

    return True


def request_is_logged_in() -> bool:
    """is_logged_in(), answered ONCE per request (5.44, T9 part B item 1).

    The three hooks of middleware.py and `login_required` each used to call is_logged_in(),
    up to three SQLite opens apiece. Only a True answer is remembered, together with the four
    session values it was computed from (name, flag, server token, session id). When ANY of
    them differs (a login, a logout, `session.clear()` anywhere, a stale session cleared by a
    hook) the memo is ignored and the check runs again from scratch, so the answer can never
    be older than the session it describes. A False answer is never remembered: it is cheap
    (no database call when there is no name) or it has just cleared the session.
    Same checks, same session.clear() side effect, no weaker guarantee than is_logged_in().
    """
    if not has_app_context():
        return is_logged_in()
    signature = (
        session.get("username"),
        session.get("logged_in"),
        session.get("server_token"),
        session.get("session_id"),
    )
    if g.get(_LOGIN_MEMO) == signature:
        return True
    result = is_logged_in()
    if result:
        setattr(g, _LOGIN_MEMO, signature)
    return result
