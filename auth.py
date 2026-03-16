"""
auth.py — Authentication helpers for CloudinatorFTP
-----------------------------------------------------
All user data and the server token now live in cloudinator.db (SQLite).
users.json and session_token.txt are no longer used.
"""

from flask import session
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


def logout_user():
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

    return True
