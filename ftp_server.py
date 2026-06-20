"""
ftp_server.py — FTP server for CloudinatorFTP
----------------------------------------------
Runs a pyftpdlib FTP server on FTP_PORT (default 2121) in a background
daemon thread, exposing ROOT_DIR over FTP.

⚠️  FTP sends credentials and data in PLAINTEXT — use only on trusted
    local networks.  For internet-facing use, prefer SFTP or WebDAV.

NOTE: FTP cannot be used as a native OS drive letter/mount.
      It is useful for: WinSCP, FileZilla, legacy FTP clients.

Client usage:
  WinSCP    → Protocol: FTP  Host: HOST  Port: 2121
  FileZilla → ftp://HOST:2121
  CLI       → ftp HOST 2121  (then: USER <username>, PASS <password>)

Roles (same as Flask):
  readwrite → full FTP: list, download, upload, delete, rename, mkdir …
  readonly  → list + download only (elr permissions)

Authentication is against the CloudinatorFTP database (same credentials).
The home directory for all users is ROOT_DIR.  Users are chrooted to it.
"""

import logging
import threading
from app import get_local_ip

LOCAL_IP = get_local_ip()

log = logging.getLogger(__name__)

# pyftpdlib permission strings
# e = change dir, l = list, r = download
# a = append, d = delete, f = rename, m = mkdir, w = upload, M = chmod, T = mtime
_PERMS_READWRITE = "elradfmwMT"
_PERMS_READONLY = "elr"

_server = None
_thread: threading.Thread | None = None


# ── Custom authorizer ─────────────────────────────────────────────────────


def _make_authorizer():
    from pyftpdlib.authorizers import AuthenticationFailed

    class CloudinatorAuthorizer:
        """
        FTP authorizer backed by the CloudinatorFTP database.

        Does NOT inherit from DummyAuthorizer because on Windows,
        DummyAuthorizer.impersonate_user() calls win32security.LogonUser()
        which tries to log in as a real Windows OS account.  Since our users
        exist only in the SQLite database (not as Windows users), that call
        raises AuthorizerError and blocks all file operations after login.

        By implementing the interface directly with no-op impersonate methods
        we use only our own DB credentials — the same ones as the web UI.
        """

        # ── Called during USER command (before password) ───────────────────

        def has_user(self, username: str) -> bool:
            from database import db

            return db.user_exists(username)

        # ── Called during PASS command ─────────────────────────────────────

        def validate_authentication(self, username: str, password: str, handler):
            from database import db

            if not db.check_login(username, password):
                raise AuthenticationFailed("Invalid username or password.")
            db.update_last_login(username)

        # ── Called after successful auth ───────────────────────────────────

        def get_home_dir(self, username: str) -> str:
            from config import ROOT_DIR

            return ROOT_DIR

        # ── Called before every file operation ────────────────────────────

        def has_perm(self, username: str, perm: str, path=None) -> bool:
            from database import db

            role = db.get_role(username) or "readonly"
            allowed = _PERMS_READWRITE if role == "readwrite" else _PERMS_READONLY
            return perm in allowed

        def get_perms(self, username: str) -> str:
            from database import db

            role = db.get_role(username) or "readonly"
            return _PERMS_READWRITE if role == "readwrite" else _PERMS_READONLY

        # ── Login / quit banners ───────────────────────────────────────────

        def get_msg_login(self, username: str) -> str:
            from database import db

            role = db.get_role(username) or "readonly"
            access = "read-write" if role == "readwrite" else "read-only"
            return f"Welcome to CloudinatorFTP. Logged in as {username} ({access})."

        def get_msg_quit(self, username: str) -> str:
            return "Goodbye!"

        # ── OS impersonation — intentional no-ops ─────────────────────────
        # DummyAuthorizer tries to impersonate real OS accounts here.
        # Our users are DB-only, not OS accounts, so we skip impersonation.

        def impersonate_user(self, username: str, password: str):
            pass

        def terminate_impersonation(self, username: str):
            pass

    return CloudinatorAuthorizer()


# ── Build FTP server ──────────────────────────────────────────────────────


def _make_server(port: int):
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer

    # We subclass FTPHandler so each instance gets its own authorizer.
    # (Assigning to the class directly affects all instances globally.)
    class CloudinatorFTPHandler(FTPHandler):
        authorizer = _make_authorizer()
        banner = "CloudinatorFTP Server ready."
        passive_ports = range(60000, 60100)
        # Disable masquerade by default; set to your public IP if behind NAT:
        #   masquerade_address = "1.2.3.4"
        masquerade_address = None
        max_login_attempts = 5
        timeout = 300  # idle disconnect after 5 minutes

    server = FTPServer(("0.0.0.0", port), CloudinatorFTPHandler)
    server.max_cons = 256
    server.max_cons_per_ip = 10
    return server


# ── Public API ────────────────────────────────────────────────────────────


def start(port: int = None) -> bool:
    """
    Start the FTP server in a background daemon thread.
    Returns True on success, False if pyftpdlib is not installed.
    """
    global _server, _thread

    try:
        from config import FTP_ENABLED, FTP_PORT
    except ImportError:
        FTP_ENABLED, FTP_PORT = True, 2121

    if not FTP_ENABLED:
        return False

    port = port or FTP_PORT

    try:
        import pyftpdlib  # noqa — verify available
    except ImportError:
        print("⚠️  FTP not started: 'pyftpdlib' is not installed.")
        print("   Install it: pip install pyftpdlib")
        return False

    try:
        _server = _make_server(port)
    except OSError as e:
        print(f"❌ FTP: cannot bind to port {port}: {e}")
        return False
    except Exception as e:
        print(f"❌ FTP server build failed: {e}")
        return False

    _thread = threading.Thread(
        target=_server.serve_forever,
        name="ftp-server",
        daemon=True,
    )
    _thread.start()

    print(f"📁 FTP:     ftp://{LOCAL_IP}:{port}/")
    print(f"   ⚠️  FTP sends credentials in plaintext — local network only")
    print(f"   WinSCP → Protocol: FTP  Host: {LOCAL_IP}  Port: {port}")
    print(f"   Passive data ports: 60000–60100 (open these in your firewall)")
    return True


def stop():
    """Shut down the FTP server (best-effort)."""
    global _server
    if _server:
        try:
            _server.close_all()
        except Exception:
            pass
        _server = None
