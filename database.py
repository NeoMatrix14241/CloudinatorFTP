"""
database.py — SQLite persistence layer for CloudinatorFTP
----------------------------------------------------------
Owns two tables:
  users        — username, encrypted bcrypt hash, role
  server_token — single-row table holding the current session token

Security layers on password_hash:
  1. bcrypt   — slow hash, immune to brute force even if key is known
  2. Fernet   — AES-128-CBC + HMAC-SHA256 encryption at rest
                anyone opening the DB file sees unreadable ciphertext

The Fernet key is stored in db/secret.key — keep this file private.
Without it the DB is unreadable. Back it up separately from the DB.

All public functions are thread-safe.
"""

import os
import sqlite3
import threading
import uuid
import bcrypt
from cryptography.fernet import Fernet

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
_HERE   = os.path.dirname(os.path.abspath(__file__))
_DB_DIR = os.path.join(_HERE, 'db')
os.makedirs(_DB_DIR, exist_ok=True)

DB_PATH        = os.path.join(_DB_DIR, 'cloudinator.db')
_KEY_PATH      = os.path.join(_DB_DIR, 'secret.key')
_SECRET_PATH   = os.path.join(_DB_DIR, 'session.secret')

# One lock for write operations
_write_lock = threading.Lock()


# ------------------------------------------------------------------
# Fernet encryption — keyed from db/secret.key
# ------------------------------------------------------------------
def _load_or_create_key() -> bytes:
    """Load the Fernet key from disk, generating one on first run."""
    if os.path.exists(_KEY_PATH):
        with open(_KEY_PATH, 'rb') as f:
            return f.read().strip()
    key = Fernet.generate_key()
    with open(_KEY_PATH, 'wb') as f:
        f.write(key)
    print(f"🔑 Generated new encryption key: {_KEY_PATH}")
    print("⚠️  Back up this key file separately — losing it means losing access to all accounts!")
    return key

_fernet = Fernet(_load_or_create_key())

def _encrypt(value: str) -> str:
    """Encrypt a string, returning a base64 ciphertext string."""
    return _fernet.encrypt(value.encode()).decode()

def _decrypt(value: str) -> str:
    """Decrypt a ciphertext string back to plaintext."""
    return _fernet.decrypt(value.encode()).decode()


# ------------------------------------------------------------------
# Session secret — stored in db/session.secret
# ------------------------------------------------------------------
def get_session_secret() -> str:
    """Load the Flask session secret from disk, generating one on first run."""
    if os.path.exists(_SECRET_PATH):
        with open(_SECRET_PATH, 'r') as f:
            return f.read().strip()
    import secrets
    secret = secrets.token_hex(32)  # 256-bit random secret
    with open(_SECRET_PATH, 'w') as f:
        f.write(secret)
    print(f"🔑 Generated new session secret: {_SECRET_PATH}")
    print("⚠️  Back up this file — losing it logs out all active users immediately!")
    return secret


# ------------------------------------------------------------------
# SQLite connection
# ------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ------------------------------------------------------------------
# Schema bootstrap
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

        # Seed default users only on first run
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            defaults = [
                ("admin", "admin123", "readwrite"),
                ("guest", "guest123", "readonly"),
            ]
            for username, password, role in defaults:
                bcrypt_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                encrypted   = _encrypt(bcrypt_hash)
                conn.execute(
                    "INSERT INTO users(username, password_hash, role) VALUES(?,?,?)",
                    (username, encrypted, role)
                )
            print("👤 Seeded default users: admin (readwrite), guest (readonly)")
            print("⚠️  Remember to change default passwords before exposing to network!")

    print(f"✅ SQLite database ready: {DB_PATH}")


# ------------------------------------------------------------------
# Database manager
# ------------------------------------------------------------------
class _Database:

    # ---- server token --------------------------------------------

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
            print("🔑 Generated initial server token")
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

    # ---- auth ----------------------------------------------------

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
            return False  # Corrupted or wrong key
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

    # ---- user management -----------------------------------------

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
        encrypted   = _encrypt(bcrypt_hash)
        try:
            with _write_lock, _connect() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, role) VALUES(?,?,?)",
                    (username, encrypted, role)
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
        encrypted   = _encrypt(bcrypt_hash)
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash=? WHERE username=?",
                (encrypted, username)
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