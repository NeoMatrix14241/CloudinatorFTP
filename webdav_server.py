"""
webdav_server.py — WebDAV server for CloudinatorFTP
----------------------------------------------------
Exposes ROOT_DIR over HTTP WebDAV on WEBDAV_PORT (default 8080)
using wsgidav + waitress.  Shares the same user database and roles
as the main Flask server.

Native drive mapping:
  Windows → This PC → Map Network Drive → http://HOST:8080/
            (requires WebClient service to be running)
  macOS   → Finder → Go → Connect to Server → http://HOST:8080
            (appears as a removable volume on the desktop)
  Linux   → sudo apt install davfs2
            sudo mount -t davfs http://HOST:8080/ /mnt/cloudinator
            /etc/fstab: http://HOST:8080/ /mnt/cloudinator davfs user,auto 0 0

Roles (same as Flask):
  readwrite → full access: GET PUT DELETE MKCOL MOVE COPY LOCK PROPFIND …
  readonly  → read access only: GET PROPFIND OPTIONS HEAD
              write-method requests return 403 before reaching wsgidav

Authentication uses the shared _AuthCache to avoid repeated bcrypt
calls on every WebDAV request (WebDAV clients often re-authenticate
on every request, which is expensive with bcrypt).
"""

import base64
import hashlib
import logging
import os
import threading
import time
from app import get_local_ip

LOCAL_IP = get_local_ip()

log = logging.getLogger(__name__)

# ── HTTP methods considered "writes" ──────────────────────────────────────
_WRITE_METHODS = frozenset(
    ["PUT", "DELETE", "MKCOL", "COPY", "MOVE", "LOCK", "UNLOCK", "PROPPATCH", "PATCH"]
)

# ── Shared per-process auth cache ─────────────────────────────────────────
# Avoids repeated bcrypt checks on every WebDAV request.
# Maps username → {hash: sha256_of_password, role: str|None, exp: float}
# role = str  → valid credentials, role is the role string
# role = None → valid username but wrong password (cached failure)


class _AuthCache:
    """
    Thread-safe cache for WebDAV credentials → role.
    Stores sha256(password), NOT the raw password, so a cache dump is safe.
    TTL is short (30 s) so password changes take effect quickly.
    """

    TTL = 30  # seconds

    def __init__(self):
        self._data: dict = {}
        self._lock = threading.Lock()

    def lookup(self, username: str, password: str):
        """
        Return:
          str   — cached role (credentials valid)
          None  — cached failure (wrong password)
          False — cache miss (must do real auth)
        """
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        with self._lock:
            entry = self._data.get(username)
            if entry and entry["hash"] == pw_hash and time.time() < entry["exp"]:
                return entry["role"]
        return False

    def store(self, username: str, password: str, role):
        """Store result. role=None means authentication failed."""
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        with self._lock:
            self._data[username] = {
                "hash": pw_hash,
                "role": role,
                "exp": time.time() + self.TTL,
            }

    def invalidate(self, username: str):
        """Drop cached entry (call after password change)."""
        with self._lock:
            self._data.pop(username, None)


_auth_cache = _AuthCache()


# ── Internal helpers ──────────────────────────────────────────────────────


def _parse_basic_auth(environ):
    """Extract (username, password) from HTTP Basic Auth header, or (None, None)."""
    auth = environ.get("HTTP_AUTHORIZATION", "")
    if not auth.lower().startswith("basic "):
        return None, None
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8", errors="replace")
        if ":" not in decoded:
            return None, None
        return decoded.split(":", 1)
    except Exception:
        return None, None


def _resolve_role(username: str, password: str):
    """
    Authenticate username/password and return the role string, or None on failure.
    Uses _auth_cache to avoid bcrypt on every request.
    """
    cached = _auth_cache.lookup(username, password)
    if cached is not False:
        return cached  # str or None

    from database import db

    if db.check_login(username, password):
        role = db.get_role(username) or "readonly"
        db.update_last_login(username)
        _auth_cache.store(username, password, role)
        return role
    else:
        _auth_cache.store(username, password, None)
        return None


# ── WSGI middleware — blocks write operations for readonly users ───────────


class _RoleEnforcerMiddleware:
    """
    Wraps the WsgiDAV WSGI app to enforce read-only access.

    For write-method requests where valid credentials are present:
      • readwrite → pass through to wsgidav as normal
      • readonly  → return 403 immediately (never reaches wsgidav)

    Unauthenticated write requests are forwarded so wsgidav can 401
    them and prompt the client for credentials.  On the client's retry
    (with credentials) the role check runs again.
    """

    def __init__(self, app):
        self._app = app

    def __call__(self, environ, start_response):
        if environ.get("REQUEST_METHOD", "").upper() in _WRITE_METHODS:
            username, password = _parse_basic_auth(environ)
            if username and password:
                role = _resolve_role(username, password)
                # role is None  → bad credentials, let wsgidav return 401
                # role is str but not readwrite → block with 403
                if role is not None and role != "readwrite":
                    body = (
                        b"403 Forbidden\n"
                        b"Your account has read-only access.\n"
                        b"Contact the server admin to request write access."
                    )
                    start_response(
                        "403 Forbidden",
                        [
                            ("Content-Type", "text/plain; charset=utf-8"),
                            ("Content-Length", str(len(body))),
                            ("DAV", "1, 2"),
                        ],
                    )
                    return [body]
        return self._app(environ, start_response)


# ── wsgidav domain controller ─────────────────────────────────────────────


def _make_domain_controller_class():
    """
    Build and return the wsgidav domain controller CLASS (not an instance).
    wsgidav 4.3.x does:
        if not isinstance(dc, type): raise ValueError("Could not resolve...")
        dc_instance = dc(wsgidav_app=app, config=config)
    So we MUST return the class itself; wsgidav instantiates it.

    wsgidav 4.x API change vs 3.x:
      basic_auth_user must return the USERNAME STRING on success, not True.
      is_share_anonymous(share, environ=None) — environ dropped in 4.3.x.
    """
    try:
        from wsgidav.dc.base_dc import BaseDomainController

        _base = BaseDomainController
    except ImportError:
        _base = object  # wsgidav 3.x or very old — no base class required

    class CloudinatorDC(_base):
        """Authenticates WebDAV against the CloudinatorFTP SQLite database."""

        def __init__(self, wsgidav_app=None, config=None):
            # wsgidav 4.x calls CloudinatorDC(wsgidav_app=..., config=...)
            # wsgidav 3.x may call with no args — both signatures handled here
            pass

        def get_domain_realm(self, path_info, environ):
            return "CloudinatorFTP"

        def require_authentication(self, realm, environ):
            return True

        def basic_auth_user(self, realm, user_name, password, environ):
            # wsgidav 4.x REQUIRES returning the username string on success.
            # Returning True (as in 3.x) causes wsgidav to reject the auth.
            role = _resolve_role(user_name, password)
            return user_name if role is not None else False

        def supports_http_digest_auth(self):
            return False

        def digest_auth_user(self, realm, user_name, environ):
            return False

        # environ omitted in wsgidav 4.3.x call site — default=None keeps
        # us compatible with older 4.x builds that still passed it.
        def is_share_anonymous(self, share, environ=None):
            return False

    return CloudinatorDC  # return the CLASS; wsgidav instantiates it


# ── Certificate download middleware ───────────────────────────────────────
# Serves db/webdav.crt at GET /webdav.crt on both HTTP and HTTPS ports.
# No auth required — the cert is the public key, safe to expose.
# Clients download it with one PowerShell line and import it as Trusted Root.


class _CertMiddleware:
    """
    Intercepts GET /webdav.crt and returns the TLS certificate file.
    All other requests pass through to the wsgidav app.
    cert_path is resolved once at startup; existence is checked per-request
    so it works even if the cert is generated after this middleware is built.
    """

    def __init__(self, app, cert_path=None):
        self._app = app
        self._cert_path = cert_path

    def __call__(self, environ, start_response):
        if (
            environ.get("REQUEST_METHOD", "GET") == "GET"
            and environ.get("PATH_INFO", "").rstrip("/") == "/webdav.crt"
        ):
            path = self._cert_path
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    data = f.read()
                start_response(
                    "200 OK",
                    [
                        ("Content-Type", "application/x-pem-file"),
                        (
                            "Content-Disposition",
                            'attachment; filename="cloudinator.crt"',
                        ),
                        ("Content-Length", str(len(data))),
                        ("Cache-Control", "no-store"),
                    ],
                )
                return [data]
            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"Certificate not generated yet - start the server first."]
        return self._app(environ, start_response)


# ── Build the final WSGI app ──────────────────────────────────────────────


def _build_app(root_dir: str):
    try:
        from wsgidav.wsgidav_app import WsgiDAVApp
    except ImportError:
        raise ImportError("wsgidav is not installed. Run: pip install wsgidav")

    try:
        from wsgidav.fs_dav_provider import FilesystemProvider
    except ImportError:
        from wsgidav.dav_provider import FilesystemProvider

    try:
        provider = FilesystemProvider(root_dir, readonly=False)
    except TypeError:
        provider = FilesystemProvider(root_dir)

    config = {
        "provider_mapping": {"/": provider},
        "http_authenticator": {
            "domain_controller": _make_domain_controller_class(),
            "accept_basic": True,
            "accept_digest": False,
            "default_to_digest": False,
            "trusted_auth_header": None,
        },
        "property_manager": True,
        "lock_storage": True,
        "verbose": 0,
        "logging": {"enable_loggers": []},
    }

    dav_app = WsgiDAVApp(config)

    # Resolve cert path once at startup (existence checked per-request)
    cert_path = None
    try:
        from paths import get_db_dir

        cert_path = os.path.join(get_db_dir(create=False), "webdav.crt")
    except Exception:
        pass

    return _CertMiddleware(_RoleEnforcerMiddleware(dav_app), cert_path=cert_path)


# ── Server lifecycle ──────────────────────────────────────────────────────

_http_server = None
_https_server = None
_http_thread = None
_https_thread = None


def _start_http(app, port: int):
    """Start HTTP WebDAV server using waitress (fallback: threaded wsgiref)."""
    try:
        from waitress import create_server

        srv = create_server(app, host="0.0.0.0", port=port, threads=8)
        return srv, srv.run
    except ImportError:
        import wsgiref.simple_server as _wss
        from socketserver import ThreadingMixIn

        class _TWSGI(ThreadingMixIn, _wss.WSGIServer):
            daemon_threads = True
            allow_reuse_address = True

        srv = _TWSGI(("0.0.0.0", port), _wss.WSGIRequestHandler)
        srv.set_app(app)
        return srv, srv.serve_forever


def _start_https(app, port: int):
    """
    Start HTTPS WebDAV server using cheroot + BuiltinSSLAdapter.
    Generates a self-signed cert in db/ on first run.
    cheroot is a dependency of wsgidav so it is always available.
    """
    from cheroot import wsgi as cheroot_wsgi
    from cheroot.ssl.builtin import BuiltinSSLAdapter
    from paths import get_db_dir
    import ssl_cert

    db_dir = get_db_dir(create=True)
    cert_path, key_path = ssl_cert.get_cert_paths(db_dir)

    srv = cheroot_wsgi.Server(("0.0.0.0", port), app, numthreads=8)
    srv.ssl_adapter = BuiltinSSLAdapter(cert_path, key_path)
    return srv, srv.start  # cheroot uses .start(), not .run()


def start() -> bool:
    """
    Start WebDAV servers (HTTP and/or HTTPS) in background daemon threads.
    Returns True if at least one server started successfully.
    """
    global _http_server, _https_server, _http_thread, _https_thread

    try:
        from config import (
            WEBDAV_ENABLED,
            WEBDAV_PORT,
            WEBDAV_HTTPS_ENABLED,
            WEBDAV_HTTPS_PORT,
        )
    except ImportError:
        WEBDAV_ENABLED, WEBDAV_PORT = True, 8080
        WEBDAV_HTTPS_ENABLED, WEBDAV_HTTPS_PORT = True, 8443

    if not WEBDAV_ENABLED and not WEBDAV_HTTPS_ENABLED:
        return False

    try:
        from config import ROOT_DIR
    except ImportError:
        print("❌ WebDAV: cannot import ROOT_DIR from config.py")
        return False

    try:
        app = _build_app(ROOT_DIR)
    except ImportError as exc:
        print(f"⚠️  WebDAV not started: {exc}")
        return False
    except Exception as exc:
        print(f"❌ WebDAV app build failed: {exc}")
        return False

    started = False

    # ── HTTP ──────────────────────────────────────────────────────────────
    if WEBDAV_ENABLED:
        try:
            _http_server, run_fn = _start_http(app, WEBDAV_PORT)
            _http_thread = threading.Thread(
                target=run_fn, name="webdav-http", daemon=True
            )
            _http_thread.start()
            print(f"🌐 WebDAV HTTP:  http://{LOCAL_IP}:{WEBDAV_PORT}/")
            started = True
        except Exception as exc:
            print(f"❌ WebDAV HTTP failed: {exc}")

    # ── HTTPS ─────────────────────────────────────────────────────────────
    if WEBDAV_HTTPS_ENABLED:
        try:
            _https_server, run_fn = _start_https(app, WEBDAV_HTTPS_PORT)
            _https_thread = threading.Thread(
                target=run_fn, name="webdav-https", daemon=True
            )
            _https_thread.start()
            print(f"🔐 WebDAV HTTPS: https://{LOCAL_IP}:{WEBDAV_HTTPS_PORT}/")
            print(f"   Import cert on any LAN PC — elevated PowerShell, one line:")
            print(
                f'   $f="$env:TEMP\\c.crt"; Invoke-WebRequest http://{LOCAL_IP}:{WEBDAV_PORT}/webdav.crt -OutFile $f; Import-Certificate $f -CertStoreLocation Cert:\\LocalMachine\\Root; del $f'
            )
            started = True
        except Exception as exc:
            print(f"❌ WebDAV HTTPS failed: {exc}")

    return started


def stop():
    """Shut down both WebDAV servers (best-effort)."""
    global _http_server, _https_server
    for srv in (_http_server, _https_server):
        if srv:
            try:
                if hasattr(srv, "close"):
                    srv.close()
                elif hasattr(srv, "stop"):
                    srv.stop()
                elif hasattr(srv, "shutdown"):
                    srv.shutdown()
            except Exception:
                pass
    _http_server = _https_server = None
