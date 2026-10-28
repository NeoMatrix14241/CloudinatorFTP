"""
auth.py — Authentication helpers for CloudinatorFTP
-----------------------------------------------------
All user data and the server token now live in cloudinator.db (SQLite).
users.json and session_token.txt are no longer used.
"""

from quart import session
from database import db


def check_login(username: str, password: str) -> bool:
    """Verify credentials. Always reads live from DB — never stale."""
    return db.check_login(username, password)


def get_role(username: str) -> str | None:
    """Return 'readwrite', 'readonly', or None if user doesn't exist."""
    return db.get_role(username)


def login_user(username: str):
    """Stamp the session with the current server token."""
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
