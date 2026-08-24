"""
webdav_server.py — WebDAV server for CloudinatorFTP
----------------------------------------------------
Exposes ROOT_DIR over HTTP/HTTPS WebDAV on WEBDAV_PORT/WEBDAV_HTTPS_PORT
(default 8080/8443) using wsgidav, served via Hypercorn — same server
library as the main app, standardized on for every server in this project
now that the main app moved off Flask/Waitress to Quart/Hypercorn.

HTTPS is the default and runs exclusively when it's enabled and the cert
loads fine (WEBDAV_ENABLED=False, WEBDAV_HTTPS_ENABLED=True in config.py) —
WebDAV auth is HTTP Basic, which sends credentials in a reversible (base64,
not encrypted) form on every request, so the plaintext :8080 listener never
runs alongside a working HTTPS one, even if WEBDAV_ENABLED=True. It's only
used when HTTPS is disabled outright, or as an automatic fallback if HTTPS
can't start (missing `cryptography`, cert-write failure, etc.) — same
graceful-degradation pattern as the FTP→FTPS TLS support.

wsgidav's app is WSGI-only (no ASGI-native alternative exists), so
asgiref.wsgi.WsgiToAsgi bridges it into something Hypercorn can serve.
This is a dependency-consolidation move, not a performance one — the
underlying wsgidav app is still synchronous, and WsgiToAsgi still runs it
in a thread pool under the hood, same as waitress/cheroot did before.
The concrete win: one server library everywhere instead of three
(waitress + cheroot + Hypercorn), and HTTP/2 on the HTTPS listener.
Verified directly: PROPFIND, GET, PUT, and auth enforcement (401/207/201)
all behave identically to the old waitress+cheroot setup, including over
HTTP/2.

Native drive mapping:
  Windows → This PC → Map Network Drive → http://HOST:8080/
            (requires WebClient service to be running)
  macOS   → Finder → Go → Connect to Server → http://HOST:8080
            (appears as a removable volume on the desktop)
  Linux   → sudo apt install davfs2
            sudo mount -t davfs http://HOST:8080/ /mnt/cloudinator
            /etc/fstab: http://HOST:8080/ /mnt/cloudinator davfs user,auto 0 0

Roles (same as the main app):
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
import asyncio
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
# Both HTTP and HTTPS run from a single Hypercorn Config/process/thread —
# `bind` is the TLS listener, `insecure_bind` is the plain-HTTP one, same
# pattern as prod_server.py. Either can be an empty list to disable that
# listener independently, matching the old WEBDAV_ENABLED/WEBDAV_HTTPS_ENABLED
# split.

_webdav_thread: "threading.Thread | None" = None
_webdav_loop: "asyncio.AbstractEventLoop | None" = None
_webdav_shutdown_event: "asyncio.Event | None" = None


def _build_hypercorn_logger(name: str) -> logging.Logger:
    """Hypercorn's default error-log formatter (used whenever Config.errorlog
    is left at its default "-") includes %(process)d, which crashes under
    Python 3.14 — record.process comes back None in that code path, a
    Python 3.14 logging-module behavior change, not a bug in this app.
    Passing a pre-built Logger instead of the string "-" makes Hypercorn's
    _create_logger() skip its own crashing formatter construction entirely
    (it has an early return for an already-built logging.Logger target).
    Same fix as prod_server.py's identical helper — duplicated rather than
    imported since this module and prod_server.py aren't otherwise coupled.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _start_hypercorn(wsgi_app, http_port, https_port, cert_path, key_path):
    """Runs WebDAV (HTTP and/or HTTPS) via Hypercorn in a background thread.
    Returns the Thread object."""
    from asgiref.wsgi import WsgiToAsgi
    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    asgi_app = WsgiToAsgi(wsgi_app)

    cfg = Config()
    cfg.bind = [f"0.0.0.0:{https_port}"] if https_port else []
    cfg.insecure_bind = [f"0.0.0.0:{http_port}"] if http_port else []
    cfg.errorlog = _build_hypercorn_logger(
        "hypercorn.webdav"
    )  # see _build_hypercorn_logger's docstring
    if https_port:
        cfg.certfile = cert_path
        cfg.keyfile = key_path
        cfg.alpn_protocols = ["h2", "http/1.1"]
    # keep_alive_max_requests intentionally left at Hypercorn's default
    # (1000) — see prod_server.py's comment on this exact setting. 0 does
    # NOT mean unlimited, it means "close after the very first request".

    async def _run():
        global _webdav_loop, _webdav_shutdown_event
        _webdav_loop = asyncio.get_running_loop()
        _webdav_shutdown_event = asyncio.Event()

        async def _shutdown_trigger():
            await _webdav_shutdown_event.wait()

        await serve(asgi_app, cfg, shutdown_trigger=_shutdown_trigger)

    thread = threading.Thread(
        target=lambda: asyncio.run(_run()), name="webdav-hypercorn", daemon=True
    )
    thread.start()
    return thread


def start() -> bool:
    """
    Start WebDAV (HTTP and/or HTTPS) via Hypercorn in a background thread.
    Returns True if at least one listener started successfully.
    """
    global _webdav_thread

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

    try:
        import asgiref  # noqa — verify available
    except ImportError:
        print("⚠️  WebDAV not started: 'asgiref' is not installed.")
        print("   Install it: pip install asgiref")
        return False

    # HTTPS wins exclusively when it's enabled and actually starts — WEBDAV_ENABLED's
    # plaintext :8080 is only ever used when HTTPS is off entirely, or as an automatic
    # fallback if the cert couldn't be prepared. It is never run *alongside* a working
    # HTTPS listener, even if WEBDAV_ENABLED=True in server_config.json.
    https_port = WEBDAV_HTTPS_PORT if WEBDAV_HTTPS_ENABLED else None
    http_port = None
    http_is_fallback = False  # becomes True if we opened :8080 because HTTPS
    # couldn't start, rather than because HTTPS was simply disabled

    cert_path = key_path = None
    if https_port:
        try:
            from paths import get_db_dir
            import ssl_cert

            db_dir = get_db_dir(create=True)
            cert_path, key_path = ssl_cert.get_cert_paths(db_dir)
        except Exception as exc:
            print(f"❌ WebDAV HTTPS: could not prepare TLS cert: {exc}")
            https_port = None
            # HTTPS was requested but couldn't start — fall back to plaintext
            # so WebDAV still comes up, regardless of what WEBDAV_ENABLED says.
            # Credentials are Basic Auth (weakly obscured, not encrypted) over
            # this listener, so make that loud rather than silent.
            print(
                f"⚠️  Falling back to plaintext WebDAV on port {WEBDAV_PORT} — "
                f"install 'cryptography' (pip install cryptography) to get "
                f"HTTPS back and close this cleartext fallback."
            )
            http_port = WEBDAV_PORT
            http_is_fallback = True
        else:
            if WEBDAV_ENABLED:
                print(
                    f"ℹ️  WebDAV: ignoring WEBDAV_ENABLED (plaintext :{WEBDAV_PORT}) — "
                    f"HTTPS is enabled and started fine, so it's used exclusively."
                )
    else:
        # HTTPS disabled outright in config — plaintext is the only option,
        # so honor WEBDAV_ENABLED as-is.
        http_port = WEBDAV_PORT if WEBDAV_ENABLED else None

    try:
        _webdav_thread = _start_hypercorn(
            app, http_port, https_port, cert_path, key_path
        )
    except OSError as exc:
        print(f"❌ WebDAV: cannot bind requested port(s): {exc}")
        return False
    except Exception as exc:
        print(f"❌ WebDAV Hypercorn failed to start: {exc}")
        return False

    if http_port:
        tag = " (fallback — HTTPS unavailable)" if http_is_fallback else ""
        print(f"🌐 WebDAV HTTP:  http://{LOCAL_IP}:{http_port}/{tag}")
        print(f"   ⚠️  plaintext Basic Auth — credentials are NOT encrypted here")
    if https_port:
        print(f"🔐 WebDAV HTTPS: https://{LOCAL_IP}:{https_port}/  (HTTP/2 enabled)")
        print(
            f"   Import {cert_path} as a trusted root manually (or serve it "
            f"yourself) — the plaintext HTTP listener that used to host it at "
            f"/webdav.crt is disabled while HTTPS is running exclusively."
        )

    return True


def stop():
    """Shut down the WebDAV Hypercorn server (best-effort, graceful)."""
    global _webdav_loop, _webdav_shutdown_event
    if _webdav_loop is not None and _webdav_shutdown_event is not None:
        try:
            _webdav_loop.call_soon_threadsafe(_webdav_shutdown_event.set)
        except Exception:
            pass
    _webdav_loop = None
    _webdav_shutdown_event = None
