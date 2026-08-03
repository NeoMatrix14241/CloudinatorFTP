"""
database.py — SQLite persistence layer for CloudinatorFTP
----------------------------------------------------------
LAZY INITIALISATION: nothing is created on disk when this module is
imported. File I/O only happens on first actual use (first DB query).
This allows setup_storage.py and config.py to import this module
without creating any directories or files.
"""

import os
import secrets
import sqlite3
import threading
import uuid
import bcrypt
from cryptography.fernet import Fernet

# ------------------------------------------------------------------
# NT hash — required for SMB/NTLM authentication.
# NTLM is a challenge-response protocol: the plaintext password is NEVER
# sent over the wire, so the server must already know the NT hash (raw
# MD4 of the UTF-16LE password) to verify a client's response. This is
# true of every SMB server, including real Windows and Samba — it's an
# inherent property of NTLM, not a design choice we're making.
#
# Because of this, the NT hash can ONLY be captured at the moment we
# have the plaintext in hand (add_user / update_password). It CANNOT be
# derived from the existing bcrypt hash (bcrypt is one-way by design).
# Any user created before this feature existed must have their password
# reset once before SMB access works for that account — see
# users_missing_nt_hash().
#
# The NT hash is intentionally much weaker than bcrypt (unsalted, fast
# MD4) — that weakness is inherent to the NTLM protocol itself. We still
# encrypt it at rest with the same Fernet key as the bcrypt hash, for
# defense-in-depth against raw database-file theft.
# ------------------------------------------------------------------
try:
    from impacket.ntlm import compute_nthash as _compute_nthash

    _SMB_AVAILABLE = True
except ImportError:
    _SMB_AVAILABLE = False

    def _compute_nthash(password: str) -> bytes:
        raise RuntimeError("impacket is not installed — cannot compute NT hash")


# ------------------------------------------------------------------
# Paths — create=False: dirs NOT created on import
# ------------------------------------------------------------------
from paths import get_db_dir

_DB_DIR = get_db_dir(create=False)
DB_PATH = os.path.join(_DB_DIR, "cloudinator.db")
_KEY_PATH = os.path.join(_DB_DIR, "secret.key")
_SECRET_PATH = os.path.join(_DB_DIR, "session.secret")

_write_lock = threading.Lock()


# ------------------------------------------------------------------
# Fernet encryption — lazy
# ------------------------------------------------------------------


def _load_or_create_key() -> bytes:
    if os.path.exists(_KEY_PATH):
        with open(_KEY_PATH, "rb") as f:
            return f.read().strip()
    os.makedirs(_DB_DIR, exist_ok=True)
    key = Fernet.generate_key()
    with open(_KEY_PATH, "wb") as f:
        f.write(key)
    print(f"🔑 Generated new encryption key: {_KEY_PATH}")
    print(
        "⚠️  Back up this key file separately — losing it means losing access to all accounts!"
    )
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
        with open(_SECRET_PATH, "r") as f:
            return f.read().strip()
    os.makedirs(_DB_DIR, exist_ok=True)
    import secrets

    secret = secrets.token_hex(32)
    with open(_SECRET_PATH, "w") as f:
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
        CREATE TABLE IF NOT EXISTS share_links (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            token          TEXT    UNIQUE NOT NULL,
            file_path      TEXT    NOT NULL,
            item_name      TEXT    NOT NULL,
            is_dir         INTEGER NOT NULL DEFAULT 0,
            created_by     TEXT,
            created_at     REAL    NOT NULL DEFAULT (unixepoch()),
            revoked        INTEGER NOT NULL DEFAULT 0,
            revoked_at     REAL,
            download_count INTEGER NOT NULL DEFAULT 0,
            security_mode  TEXT    NOT NULL DEFAULT 'public'
                                   CHECK(security_mode IN ('public','passkey','approval')),
            passkey_hash   TEXT,
            expires_at     REAL
        );
        CREATE INDEX IF NOT EXISTS idx_share_links_path ON share_links(file_path);
        CREATE INDEX IF NOT EXISTS idx_share_links_revoked ON share_links(revoked);

        CREATE TABLE IF NOT EXISTS share_access_requests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            token           TEXT    NOT NULL,
            requester_name  TEXT    NOT NULL,
            requester_note  TEXT,
            status          TEXT    NOT NULL DEFAULT 'pending'
                                    CHECK(status IN ('pending','approved','denied')),
            requested_at    REAL    NOT NULL DEFAULT (unixepoch()),
            decided_at      REAL,
            decided_by      TEXT,
            max_downloads   INTEGER,
            downloads_used  INTEGER NOT NULL DEFAULT 0,
            access_token    TEXT    UNIQUE NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_access_req_token ON share_access_requests(token);
        CREATE INDEX IF NOT EXISTS idx_access_req_status ON share_access_requests(status);
        CREATE INDEX IF NOT EXISTS idx_access_req_access_token ON share_access_requests(access_token);
    """)

    # ── Migration: add nt_hash column for SMB/NTLM auth (idempotent) ───────
    # Nullable — existing users get NULL until their next password change.
    existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
    if "nt_hash" not in existing_cols:
        conn.execute("ALTER TABLE users ADD COLUMN nt_hash TEXT")
        print("🔧 Migrated users table: added nt_hash column (for SMB auth)")
        print(
            "   ⚠️  Existing users must reset their password once before SMB works for them."
        )

    # ── Migration: share link security (mode/passkey/expiry) (idempotent) ──
    share_cols = [row[1] for row in conn.execute("PRAGMA table_info(share_links)")]
    if "security_mode" not in share_cols:
        conn.execute(
            "ALTER TABLE share_links ADD COLUMN security_mode TEXT NOT NULL DEFAULT 'public'"
        )
        conn.execute("ALTER TABLE share_links ADD COLUMN passkey_hash TEXT")
        conn.execute("ALTER TABLE share_links ADD COLUMN expires_at REAL")
        print(
            "🔧 Migrated share_links table: added security_mode/passkey_hash/expires_at"
        )

    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        for username, password, role in [
            ("admin", "admin123", "readwrite"),
            ("guest", "guest123", "readonly"),
        ]:
            bcrypt_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            nt_hash_enc = (
                _encrypt(_compute_nthash(password).hex()) if _SMB_AVAILABLE else None
            )
            conn.execute(
                "INSERT INTO users(username, password_hash, role, nt_hash) VALUES(?,?,?,?)",
                (username, _encrypt(bcrypt_hash), role, nt_hash_enc),
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
                (token,),
            )
            return token

    def rotate_server_token(self) -> str:
        new_token = str(uuid.uuid4())
        with _write_lock, _connect() as conn:
            conn.execute(
                """
                INSERT INTO server_token(id, token, updated_at)
                VALUES(1, ?, unixepoch())
                ON CONFLICT(id) DO UPDATE SET token=excluded.token,
                                               updated_at=excluded.updated_at
            """,
                (new_token,),
            )
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
        nt_hash_enc = (
            _encrypt(_compute_nthash(password).hex()) if _SMB_AVAILABLE else None
        )
        try:
            with _write_lock, _connect() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, role, nt_hash) VALUES(?,?,?,?)",
                    (username, _encrypt(bcrypt_hash), role, nt_hash_enc),
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
        nt_hash_enc = (
            _encrypt(_compute_nthash(new_password).hex()) if _SMB_AVAILABLE else None
        )
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash=?, nt_hash=? WHERE username=?",
                (_encrypt(bcrypt_hash), nt_hash_enc, username),
            )
        updated = cur.rowcount > 0
        if updated:
            print(f"🔐 Password updated: {username}")
            if _SMB_AVAILABLE:
                print(f"   ✅ SMB credential updated too — takes effect within ~30s")
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
    # SMB / NTLM credential access — used by smb_server.py at startup and
    # by the periodic credential-refresh thread.
    # ------------------------------------------------------------------

    def get_smb_credentials(self) -> list[tuple[str, str]]:
        """
        Return [(username, nt_hash_hex), ...] for every user who has an
        NT hash on record (i.e. has set/changed their password since SMB
        support was added). Users without one are silently skipped here —
        see users_missing_nt_hash() to find out who they are.
        """
        with _connect() as conn:
            rows = conn.execute(
                "SELECT username, nt_hash FROM users WHERE nt_hash IS NOT NULL"
            ).fetchall()
        out = []
        for r in rows:
            try:
                out.append((r["username"], _decrypt(r["nt_hash"])))
            except Exception:
                continue  # corrupt/undecryptable entry — skip rather than crash SMB startup
        return out

    def users_missing_nt_hash(self) -> list[str]:
        """
        Return usernames that have NO NT hash on record yet — these accounts
        cannot authenticate over SMB until their password is reset once
        (via create_user.py or the web UI), which captures the plaintext
        long enough to compute and store the hash.
        """
        with _connect() as conn:
            rows = conn.execute(
                "SELECT username FROM users WHERE nt_hash IS NULL ORDER BY username"
            ).fetchall()
        return [r["username"] for r in rows]

    # ------------------------------------------------------------------
    # Share links — opaque-token public download links.
    #
    # The URL a browser sees (/shared/<token>) never contains the real file
    # path — the token is an unguessable random string (secrets.token_urlsafe)
    # mapped server-side to the actual path. The real filename is preserved
    # separately in `item_name` so the download still saves under its
    # original name (via Content-Disposition), even though the URL is opaque.
    # ------------------------------------------------------------------

    @staticmethod
    def _norm_path(file_path: str) -> str:
        return file_path.strip().strip("/").replace("\\", "/")

    @staticmethod
    def _hash_passkey(passkey: str) -> str:
        return bcrypt.hashpw(passkey.encode(), bcrypt.gensalt()).decode()

    def create_share(
        self,
        file_path: str,
        item_name: str,
        is_dir: bool,
        created_by: str,
        security_mode: str = "public",
        passkey: str | None = None,
        expires_at: float | None = None,
    ) -> str:
        """
        Return an active share token for this path — reuses the existing
        token if one is already active (idempotent 'share' toggle), else
        mints a new one with the given security settings. Security settings
        are ignored on reuse; call update_share_settings() to change them.
        """
        if security_mode not in ("public", "passkey", "approval"):
            raise ValueError(f"Invalid security_mode: {security_mode!r}")
        norm = self._norm_path(file_path)
        with _write_lock, _connect() as conn:
            row = conn.execute(
                "SELECT token FROM share_links WHERE file_path=? AND revoked=0",
                (norm,),
            ).fetchone()
            if row:
                return row["token"]

            token = secrets.token_urlsafe(12)
            passkey_hash = self._hash_passkey(passkey) if passkey else None
            conn.execute(
                """
                INSERT INTO share_links(
                    token, file_path, item_name, is_dir, created_by,
                    security_mode, passkey_hash, expires_at
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    token,
                    norm,
                    item_name,
                    1 if is_dir else 0,
                    created_by,
                    security_mode,
                    passkey_hash,
                    expires_at,
                ),
            )
        print(
            f"🔗 Share link created for: {norm} (by {created_by}, mode={security_mode})"
        )
        return token

    def update_share_settings(
        self,
        token: str,
        security_mode: str | None = None,
        passkey: str | None = None,
        clear_passkey: bool = False,
        expires_at: float | None = None,
        clear_expiry: bool = False,
    ) -> bool:
        """Edit an existing active share's security settings from the
        Manage Shared panel. Only provided fields are changed."""
        sets, params = [], []
        if security_mode is not None:
            if security_mode not in ("public", "passkey", "approval"):
                raise ValueError(f"Invalid security_mode: {security_mode!r}")
            sets.append("security_mode=?")
            params.append(security_mode)
        if passkey:
            sets.append("passkey_hash=?")
            params.append(self._hash_passkey(passkey))
        elif clear_passkey:
            sets.append("passkey_hash=NULL")
        if expires_at is not None:
            sets.append("expires_at=?")
            params.append(expires_at)
        elif clear_expiry:
            sets.append("expires_at=NULL")
        if not sets:
            return False
        params.append(token)
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                f"UPDATE share_links SET {', '.join(sets)} WHERE token=? AND revoked=0",
                params,
            )
        return cur.rowcount > 0

    def verify_share_passkey(self, token: str, passkey: str) -> bool:
        share = self.get_share_by_token(token)
        if not share or not share.get("passkey_hash"):
            return False
        try:
            return bcrypt.checkpw(passkey.encode(), share["passkey_hash"].encode())
        except (ValueError, TypeError):
            return False

    def get_share_by_token(self, token: str) -> dict | None:
        """Active share only — revoked/unknown tokens return None."""
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM share_links WHERE token=? AND revoked=0", (token,)
            ).fetchone()
        return dict(row) if row else None

    def get_share_by_path(self, file_path: str) -> dict | None:
        """Active share only, for populating the share modal's current state."""
        norm = self._norm_path(file_path)
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM share_links WHERE file_path=? AND revoked=0", (norm,)
            ).fetchone()
        return dict(row) if row else None

    def get_shares_for_paths(self, file_paths: list) -> dict:
        """Bulk lookup: {normalized_path: share_dict} for every currently-active share among file_paths."""
        norm_paths = [self._norm_path(p) for p in file_paths]
        if not norm_paths:
            return {}
        placeholders = ",".join("?" for _ in norm_paths)
        with _connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM share_links WHERE revoked=0 AND file_path IN ({placeholders})",
                norm_paths,
            ).fetchall()
        return {r["file_path"]: dict(r) for r in rows}

    def revoke_share_by_token(self, token: str) -> bool:
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                "UPDATE share_links SET revoked=1, revoked_at=unixepoch() WHERE token=? AND revoked=0",
                (token,),
            )
        revoked = cur.rowcount > 0
        if revoked:
            print(f"🚫 Share link revoked: {token}")
        return revoked

    def revoke_share_by_path(self, file_path: str) -> bool:
        norm = self._norm_path(file_path)
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                "UPDATE share_links SET revoked=1, revoked_at=unixepoch() WHERE file_path=? AND revoked=0",
                (norm,),
            )
        return cur.rowcount > 0

    def bulk_revoke_by_paths(self, file_paths: list) -> int:
        norm_paths = [self._norm_path(p) for p in file_paths]
        if not norm_paths:
            return 0
        placeholders = ",".join("?" for _ in norm_paths)
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                f"UPDATE share_links SET revoked=1, revoked_at=unixepoch() "
                f"WHERE revoked=0 AND file_path IN ({placeholders})",
                norm_paths,
            )
        return cur.rowcount

    def revoke_all_shares(self) -> int:
        """Revoke every currently-active share link. Used by the admin
        'revoke all' button and revoke_sharing.py — both require their own
        confirmation step before calling this."""
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                "UPDATE share_links SET revoked=1, revoked_at=unixepoch() WHERE revoked=0"
            )
        count = cur.rowcount
        print(f"🚫 Revoked ALL share links ({count} link(s))")
        return count

    def list_active_shares(self) -> list:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM share_links WHERE revoked=0 ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def record_share_download(self, token: str):
        with _write_lock, _connect() as conn:
            conn.execute(
                "UPDATE share_links SET download_count = download_count + 1 WHERE token=?",
                (token,),
            )

    # ------------------------------------------------------------------
    # Share access requests — the "approval" security mode. A visitor on
    # an approval-gated /shared/<token> page submits a request; it lands
    # in the Manage Shared → Pending Requests queue for a readwrite admin
    # to approve (choosing how many downloads the grant is good for) or
    # deny. access_token is issued at request time and doubles as both
    # the poll/status token (stored in the visitor's browser as a cookie)
    # and, once approved, the download-authorization token.
    # ------------------------------------------------------------------

    def create_access_request(
        self, token: str, requester_name: str, requester_note: str | None
    ) -> str:
        access_token = secrets.token_urlsafe(20)
        with _write_lock, _connect() as conn:
            conn.execute(
                """
                INSERT INTO share_access_requests(token, requester_name, requester_note, access_token)
                VALUES(?,?,?,?)
                """,
                (
                    token,
                    requester_name.strip()[:120],
                    (requester_note or "").strip()[:500],
                    access_token,
                ),
            )
        return access_token

    def get_access_request_by_access_token(self, access_token: str) -> dict | None:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM share_access_requests WHERE access_token=?",
                (access_token,),
            ).fetchone()
        return dict(row) if row else None

    def list_pending_requests(self) -> list:
        """All pending requests, joined with their share's item name/path,
        for the admin Pending Requests queue. Skips requests whose share
        was since revoked."""
        with _connect() as conn:
            rows = conn.execute("""
                SELECT r.*, s.item_name, s.file_path, s.is_dir
                FROM share_access_requests r
                JOIN share_links s ON s.token = r.token AND s.revoked = 0
                WHERE r.status = 'pending'
                ORDER BY r.requested_at ASC
                """).fetchall()
        return [dict(r) for r in rows]

    def count_pending_requests(self) -> int:
        with _connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) c FROM share_access_requests WHERE status='pending'"
            ).fetchone()
        return row["c"]

    def approve_access_request(
        self, request_id: int, decided_by: str, max_downloads: int
    ) -> bool:
        max_downloads = max(1, int(max_downloads))
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                """
                UPDATE share_access_requests
                SET status='approved', decided_at=unixepoch(), decided_by=?, max_downloads=?
                WHERE id=? AND status='pending'
                """,
                (decided_by, max_downloads, request_id),
            )
        return cur.rowcount > 0

    def deny_access_request(self, request_id: int, decided_by: str) -> bool:
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                """
                UPDATE share_access_requests
                SET status='denied', decided_at=unixepoch(), decided_by=?
                WHERE id=? AND status='pending'
                """,
                (decided_by, request_id),
            )
        return cur.rowcount > 0

    def record_access_request_download(self, access_token: str) -> bool:
        """Increments downloads_used for an approved grant. Returns False
        (and does nothing) if the grant is missing, not approved, or
        already used up — caller should treat that as unauthorized."""
        with _write_lock, _connect() as conn:
            cur = conn.execute(
                """
                UPDATE share_access_requests
                SET downloads_used = downloads_used + 1
                WHERE access_token=? AND status='approved'
                  AND downloads_used < max_downloads
                """,
                (access_token,),
            )
        return cur.rowcount > 0


# ------------------------------------------------------------------
# Module-level singleton — no disk I/O, everything is lazy
# ------------------------------------------------------------------
db = _Database()
