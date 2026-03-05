"""
database.py — SQLite persistence layer for CloudinatorFTP
----------------------------------------------------------
Owns two tables:
  users        — username, bcrypt password hash, role
  server_token — single-row table holding the current session token
                 (replaces session_token.txt)

All public functions are thread-safe; sqlite3 connections are created
per-call (thread-local would also work but per-call is simpler and fast
enough for this workload).

Usage
-----
    from database import db
    db.check_login(username, password)   → bool
    db.get_role(username)                → 'readwrite' | 'readonly' | None
    db.get_server_token()                → str (uuid4)
    db.rotate_server_token()             → str  (new token, persisted)
    db.add_user(username, password, role)
    db.delete_user(username)
    db.update_password(username, new_password)
    db.list_users()                      → list[dict]
    db.user_exists(username)             → bool
"""

import os
import sqlite3
import threading
import uuid
import bcrypt

# ------------------------------------------------------------------
# Path — DB lives in the db/ subfolder of the project root
# ------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_DB_DIR = os.path.join(_HERE, 'db')
os.makedirs(_DB_DIR, exist_ok=True)
DB_PATH = os.path.join(_DB_DIR, 'cloudinator.db')

# One lock for the rare write operations that need serialisation
_write_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    """Open a connection with sensible defaults."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads + one writer
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ------------------------------------------------------------------
# Schema bootstrap — called once on import
# ------------------------------------------------------------------
def _bootstrap():
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL DEFAULT 'readonly'
                                      CHECK(role IN ('readwrite','readonly')),
                created_at    REAL    NOT NULL DEFAULT (unixepoch()),
                last_login    REAL
            );

            CREATE TABLE IF NOT EXISTS server_token (
                id         INTEGER PRIMARY KEY CHECK(id = 1),
                token      TEXT    NOT NULL,
                updated_at REAL    NOT NULL DEFAULT (unixepoch())
            );
        """)

        # Seed default users only if the table is empty (first run)
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            defaults = [
                ("admin", "admin123",   "readwrite"),
                ("guest", "guest123",   "readonly"),
            ]
            for username, password, role in defaults:
                hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                conn.execute(
                    "INSERT INTO users(username, password_hash, role) VALUES(?,?,?)",
                    (username, hashed, role)
                )
            print("👤 Seeded default users: admin (readwrite), guest (readonly)")
            print("⚠️  Remember to change default passwords before exposing to network!")

    print(f"✅ SQLite database ready: {DB_PATH}")


# ------------------------------------------------------------------
# Database manager class
# ------------------------------------------------------------------
class _Database:

    # ---- server token ------------------------------------------------

    def get_server_token(self) -> str:
        """Return the current server token, creating one if needed."""
        with _connect() as conn:
            row = conn.execute("SELECT token FROM server_token WHERE id=1").fetchone()
            if row:
                return row["token"]
            # First run — generate and persist
            token = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO server_token(id, token, updated_at) VALUES(1,?,unixepoch())",
                (token,)
            )
            print("🔑 Generated initial server token")
            return token

    def rotate_server_token(self) -> str:
        """Generate a new token and persist it (revokes all active sessions)."""
        new_token = str(uuid.uuid4())
        with _write_lock, _connect() as conn:
            conn.execute("""
                INSERT INTO server_token(id, token, updated_at)
                VALUES(1, ?, unixepoch())
                ON CONFLICT(id) DO UPDATE SET token=excluded.token,
                                               updated_at=excluded.updated_at
            """, (new_token,))
        print(f"🔑 Server token rotated — all sessions invalidated")
        return new_token

    # ---- auth --------------------------------------------------------

    def check_login(self, username: str, password: str) -> bool:
        """Verify username + password. Always reads from DB (never stale)."""
        with _connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username=?", (username,)
            ).fetchone()
        if not row:
            return False
        return bcrypt.checkpw(password.encode(), row["password_hash"].encode())

    def get_role(self, username: str) -> str | None:
        """Return the user's role, or None if the user doesn't exist."""
        with _connect() as conn:
            row = conn.execute(
                "SELECT role FROM users WHERE username=?", (username,)
            ).fetchone()
        return row["role"] if row else None

    def update_last_login(self, username: str):
        with _write_lock, _connect() as conn:
            conn.execute(
                "UPDATE users SET last_login=unixepoch() WHERE username=?", (username,)
            )

    # ---- user management ---------------------------------------------

    def user_exists(self, username: str) -> bool:
        with _connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM users WHERE username=?", (username,)
            ).fetchone()
        return row is not None

    def add_user(self, username: str, password: str, role: str = "readonly") -> bool:
        """Hash password and insert user. Returns False if username already taken."""
        if role not in ("readwrite", "readonly"):
            raise ValueError(f"Invalid role: {role!r}")
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
            with _write_lock, _connect() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, role) VALUES(?,?,?)",
                    (username, hashed, role)
                )
            print(f"👤 User added: {username} ({role})")
            return True
        except sqlite3.IntegrityError:
            print(f"⚠️  User already exists: {username}")
            return False

    def delete_user(self, username: str) -> bool:
        """Delete a user. Returns False if user didn't exist."""
        with _write_lock, _connect() as conn:
            cur = conn.execute("DELETE FROM users WHERE username=?", (username,))
        deleted = cur.rowcount > 0
        if deleted:
            print(f"🗑️  User deleted: {username}")
        return deleted

    def update_password(self, username: str, new_password: str) -> bool:
        """Replace a user's password. Returns False if user not found."""
        hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash=? WHERE username=?",
                (hashed, username)
            )
        updated = cur.rowcount > 0
        if updated:
            print(f"🔐 Password updated: {username}")
        return updated

    def update_role(self, username: str, role: str) -> bool:
        """Change a user's role. Returns False if user not found."""
        if role not in ("readwrite", "readonly"):
            raise ValueError(f"Invalid role: {role!r}")
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                "UPDATE users SET role=? WHERE username=?", (role, username)
            )
        return cur.rowcount > 0

    def list_users(self) -> list:
        """Return all users as a list of dicts (no password hashes)."""
        with _connect() as conn:
            rows = conn.execute(
                "SELECT username, role, created_at, last_login FROM users ORDER BY username"
            ).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------
_bootstrap()
db = _Database()