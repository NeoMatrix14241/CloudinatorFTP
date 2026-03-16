"""
database.py — SQLite persistence layer for CloudinatorFTP
----------------------------------------------------------
LAZY INITIALISATION: nothing is created on disk when this module is
imported. File I/O only happens on first actual use (first DB query).
This allows setup_storage.py and config.py to import this module
without creating any directories or files.
"""

import os
import sqlite3
import threading
import uuid
import bcrypt
from cryptography.fernet import Fernet

# ------------------------------------------------------------------
# Paths — create=False: dirs NOT created on import
# ------------------------------------------------------------------
from paths import get_db_dir
_DB_DIR      = get_db_dir(create=False)
DB_PATH      = os.path.join(_DB_DIR, 'cloudinator.db')
_KEY_PATH    = os.path.join(_DB_DIR, 'secret.key')
_SECRET_PATH = os.path.join(_DB_DIR, 'session.secret')

_write_lock = threading.Lock()


# ------------------------------------------------------------------
# Fernet encryption — lazy
# ------------------------------------------------------------------

def _load_or_create_key() -> bytes:
    if os.path.exists(_KEY_PATH):
        with open(_KEY_PATH, 'rb') as f:
            return f.read().strip()
    os.makedirs(_DB_DIR, exist_ok=True)
    key = Fernet.generate_key()
    with open(_KEY_PATH, 'wb') as f:
        f.write(key)
    print(f"🔑 Generated new encryption key: {_KEY_PATH}")
    print("⚠️  Back up this key file separately — losing it means losing access to all accounts!")
    return key


_fernet = None  # initialised on first encrypt/decrypt call


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


# ------------------------------------------------------------------
# Session secret — stored in db/session.secret
# ------------------------------------------------------------------

def get_session_secret() -> str:
    """Load the Flask session secret from disk, generating one on first run."""
    if os.path.exists(_SECRET_PATH):
        with open(_SECRET_PATH, 'r') as f:
            return f.read().strip()
    os.makedirs(_DB_DIR, exist_ok=True)
    import secrets
    secret = secrets.token_hex(32)
    with open(_SECRET_PATH, 'w') as f:
        f.write(secret)
    print(f"🔑 Generated new session secret: {_SECRET_PATH}")
    print("⚠️  Back up this file — losing it logs out all active users immediately!")
    return secret


# ------------------------------------------------------------------
# SQLite connection + lazy bootstrap
# ------------------------------------------------------------------

_bootstrapped = False  # schema created on first _connect() call


def _connect() -> sqlite3.Connection:
    global _bootstrapped
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not _bootstrapped:
        _bootstrapped = True
        _do_bootstrap(conn)
    return conn


def _do_bootstrap(conn):
    """Create schema and seed default users — runs once on first connection."""
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
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        for username, password, role in [
            ("admin", "admin123", "readwrite"),
            ("guest", "guest123", "readonly"),
        ]:
            bcrypt_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            conn.execute(
                "INSERT INTO users(username, password_hash, role) VALUES(?,?,?)",
                (username, _encrypt(bcrypt_hash), role)
            )
        print("👤 Seeded default users: admin (readwrite), guest (readonly)")
        print("⚠️  Remember to change default passwords before exposing to network!")
    print(f"✅ SQLite database ready: {DB_PATH}")


# ------------------------------------------------------------------
# Database manager
# ------------------------------------------------------------------

class _Database:

    def get_server_token(self) -> str:
        with _connect() as conn:
            row = conn.execute("SELECT token FROM server_token WHERE id=1").fetchone()
            if row:
                return row["token"]
            token = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO server_token(id, token, updated_at) VALUES(1,?,unixepoch())",
                (token,)
            )
            return token

    def rotate_server_token(self) -> str:
        new_token = str(uuid.uuid4())
        with _write_lock, _connect() as conn:
            conn.execute("""
                INSERT INTO server_token(id, token, updated_at)
                VALUES(1, ?, unixepoch())
                ON CONFLICT(id) DO UPDATE SET token=excluded.token,
                                               updated_at=excluded.updated_at
            """, (new_token,))
        print("🔑 Server token rotated — all sessions invalidated")
        return new_token

    def check_login(self, username: str, password: str) -> bool:
        with _connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username=?", (username,)
            ).fetchone()
        if not row:
            return False
        try:
            bcrypt_hash = _decrypt(row["password_hash"])
        except Exception:
            return False
        return bcrypt.checkpw(password.encode(), bcrypt_hash.encode())

    def get_role(self, username: str) -> str | None:
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

    def user_exists(self, username: str) -> bool:
        with _connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM users WHERE username=?", (username,)
            ).fetchone()
        return row is not None

    def add_user(self, username: str, password: str, role: str = "readonly") -> bool:
        if role not in ("readwrite", "readonly"):
            raise ValueError(f"Invalid role: {role!r}")
        bcrypt_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
            with _write_lock, _connect() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, role) VALUES(?,?,?)",
                    (username, _encrypt(bcrypt_hash), role)
                )
            print(f"👤 User added: {username} ({role})")
            return True
        except sqlite3.IntegrityError:
            print(f"⚠️  User already exists: {username}")
            return False

    def delete_user(self, username: str) -> bool:
        with _write_lock, _connect() as conn:
            cur = conn.execute("DELETE FROM users WHERE username=?", (username,))
        deleted = cur.rowcount > 0
        if deleted:
            print(f"🗑️  User deleted: {username}")
        return deleted

    def update_password(self, username: str, new_password: str) -> bool:
        bcrypt_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash=? WHERE username=?",
                (_encrypt(bcrypt_hash), username)
            )
        updated = cur.rowcount > 0
        if updated:
            print(f"🔐 Password updated: {username}")
        return updated

    def update_role(self, username: str, role: str) -> bool:
        if role not in ("readwrite", "readonly"):
            raise ValueError(f"Invalid role: {role!r}")
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                "UPDATE users SET role=? WHERE username=?", (role, username)
            )
        return cur.rowcount > 0

    def list_users(self) -> list:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT username, role, created_at, last_login FROM users ORDER BY username"
            ).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Module-level singleton — no disk I/O, everything is lazy
# ------------------------------------------------------------------
db = _Database()