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
(waitress + cheroot + Hypercorn). Verified directly: PROPFIND, GET, PUT,
and auth enforcement (401/207/201) all behave identically to the old
waitress+cheroot setup.

Deliberately HTTP/1.1-only (unlike the main app's HTTPS listener, which is
h2-only) — see the alpn_protocols comment in _start_hypercorn(). WebDAV is
mounted by OS-level clients (Windows WebClient/mrxdav.sys, davfs2, etc.)
that are almost universally HTTP/1.1-only; offering h2 here causes
mid-transfer connection resets ("SSL connection closed") on those clients,
worst on downloads.

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

Audit logging (2026-09-24, IP trust chain fixed same day):
  Every WebDAV login, failed login, and file operation is written as one
  "WebDAV AUDIT: user=... action=... path=... ip=..." line through the
  shared logging_setup logger — same shape as the FTP/SFTP/SMB AUDIT lines,
  so all four protocols are greppable the same way. Before this, this file
  had a logger (`log`) that nothing ever called and a plain stdlib one at
  that, so WebDAV traffic left no user/action/IP trail at all. The client
  IP is resolved by _client_ip() the same way app.py's get_client_ip()
  resolves it for the main app: CF-Connecting-IP first (this listener,
  port 8443, is tunneled through cloudflared — confirmed, not assumed),
  then X-Forwarded-For, then REMOTE_ADDR (asgiref's fill-in from
  Hypercorn's ASGI scope["client"], the raw TCP peer — correct for direct
  LAN/Tailscale access, but would be cloudflared's own local address for
  anything arriving through the tunnel, which is why it's no longer
  trusted first).

Authentication uses the shared _AuthCache to avoid repeated bcrypt
calls on every WebDAV request (WebDAV clients often re-authenticate
on every request, which is expensive with bcrypt).
"""

import base64
import hashlib
import logging
import os
import re
import asyncio
import threading
import time
from urllib.parse import unquote, urlsplit

import logging_setup
from app import get_local_ip

# Patch the same real, still-open Hypercorn bug (hypercorn#202) that
# prod_server.py patches for the main app — see hypercorn_ssl_fix.py's
# module docstring. WebDAV runs as its own separate OS process with its
# own independent Hypercorn instance (see protocol_manager.py), so it
# needs this call too; prod_server.py's own call does not cover it.
import hypercorn_ssl_fix

hypercorn_ssl_fix.apply()

LOCAL_IP = get_local_ip()

# Was logging.getLogger(__name__) — in the WebDAV subprocess that resolves to
# "__main__", a plain stdlib logger with no handler attached anywhere, and it
# was never called in this file anyway (a dead logger — same situation
# ftp_server.py and sftp_server.py were in before their own AUDIT patches).
# Now a child of logging_setup's shared "cloudinatorftp" logger, so AUDIT
# lines land in the same daily file as every other protocol's, tagged
# [webdav_server] by logging_setup's per-line component tag.
log = logging_setup.get_logger("webdav")

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


# ── Audit logging ─────────────────────────────────────────────────────────
# WebDAV is stateless HTTP Basic — there is no "session" to hang a login/logout
# pair on the way FTP/SFTP/SMB have, and clients (Windows WebClient especially)
# send several requests per second. So this is split by what each event
# actually is:
#   login / login_failed  → CloudinatorDC.basic_auth_user() below, which is
#                           where credentials are really checked. Successful
#                           logins are de-duplicated per (user, ip) for
#                           _LOGIN_AUDIT_TTL seconds so one Explorer window
#                           doesn't write a "login" line per request.
#                           Failures are NOT de-duplicated — every bad
#                           attempt is a line, same as FTP/SFTP.
#   upload/delete/mkdir/  → _AuditMiddleware, which sees the final HTTP
#   rename/copy/download    status, so only operations that actually
#                           succeeded are logged (same success-path-only
#                           convention as the other three protocols).
#   permission_denied     → _AuditMiddleware, for the readonly-role 403.
# PROPFIND / OPTIONS / HEAD / LOCK / UNLOCK / PROPPATCH are deliberately
# NOT audited: they are browsing and lock-keepalive chatter that would bury
# every real event (same reasoning as smb_server.py's audit hooks).


def _client_ip(environ) -> str:
    """
    Client IP for audit lines. Mirrors app.py's get_client_ip() trust chain
    (2026-09-23 sync note), adapted from Quart's request.headers to WSGI's
    environ HTTP_* convention — CF-Connecting-IP is set by Cloudflare's edge
    itself from the true connecting client and isn't spoofable by the client
    since there's no direct inbound path to this box; X-Forwarded-For is the
    fallback for a non-Cloudflare reverse proxy.

    FIXED 2026-09-24 (originally shipped as REMOTE_ADDR-only, same day):
    this listener (port 8443) is confirmed tunneled through cloudflared —
    every WebDAV audit line was showing cloudflared's local loopback
    address instead of the real client, for 100% of internet-facing
    traffic, since HTTPS wins exclusively over the plaintext :8080
    fallback whenever it's enabled and starts (see this file's own
    start() logic) and 8080 itself is not tunneled. REMOTE_ADDR is still
    the right answer for genuinely direct access (LAN/Tailscale, or a
    future non-tunneled deployment) — CF-Connecting-IP is the real
    connecting client, deliberately trusted over a possible middlebox.
    """
    environ = environ or {}
    cf_ip = (environ.get("HTTP_CF_CONNECTING_IP") or "").strip()
    if cf_ip:
        return cf_ip
    xff = environ.get("HTTP_X_FORWARDED_FOR")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return environ.get("REMOTE_ADDR") or "?"


_LOGIN_AUDIT_TTL = 300  # seconds — one "login" line per (user, ip) per window
_recent_logins: dict = {}
_recent_logins_lock = threading.Lock()


def _audit_login(username, role, environ) -> None:
    """Best-effort: an audit-logging problem must never break authentication."""
    try:
        ip = _client_ip(environ)
        if role is None:
            log.warning("WebDAV AUDIT: user=%r action=login_failed ip=%s", username, ip)
            return
        key = (username, ip)
        now = time.monotonic()
        with _recent_logins_lock:
            last = _recent_logins.get(key)
            if last is not None and now - last < _LOGIN_AUDIT_TTL:
                return
            if len(_recent_logins) > 1024:  # keep the dict bounded
                for k in [
                    k for k, v in _recent_logins.items() if now - v >= _LOGIN_AUDIT_TTL
                ]:
                    _recent_logins.pop(k, None)
            _recent_logins[key] = now
        log.info(
            "WebDAV AUDIT: user=%r action=login role=%r ip=%s tls=%s",
            username,
            role,
            ip,
            (environ or {}).get("wsgi.url_scheme") == "https",
        )
    except Exception:
        pass


# HTTP method → audit action name, and the status codes that count as success.
_AUDIT_ACTIONS = {
    "GET": "download",
    "PUT": "upload",
    "DELETE": "delete",
    "MKCOL": "mkdir",
    "MOVE": "rename",
    "COPY": "copy",
}
_AUDIT_OK_CODES = {
    "GET": {200, 206},
    "PUT": {200, 201, 204},
    "DELETE": {200, 204},
    "MKCOL": {201},
    "MOVE": {201, 204},
    "COPY": {201, 204},
}


def _request_path(environ) -> str:
    """PATH_INFO as a real str. asgiref hands WSGI the path as latin-1-decoded
    UTF-8 bytes (the WSGI convention), so a non-ASCII filename would log as
    mojibake without this round-trip."""
    raw = environ.get("PATH_INFO", "")
    try:
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def _destination_path(environ) -> str:
    """Target path of a MOVE/COPY. The Destination header is a full,
    percent-encoded URL (https://host:8443/dir/new.txt) — reduce it to the
    same path form _request_path() returns."""
    dest = environ.get("HTTP_DESTINATION", "")
    return unquote(urlsplit(dest).path) if dest else "?"


def _is_first_chunk(environ) -> bool:
    """Windows' WebDAV client downloads large files as many 206 range
    requests. Audit a GET once — when it's un-ranged, or ranged from byte 0 —
    instead of once per range."""
    rng = environ.get("HTTP_RANGE")
    if not rng:
        return True
    m = re.match(r"\s*bytes\s*=\s*(\d+)\s*-", rng)
    return bool(m) and int(m.group(1)) == 0


class _AuditMiddleware:
    """
    WSGI middleware that writes one AUDIT line per successful file operation.

    Wraps start_response so it can see the final status code that wsgidav (or
    _RoleEnforcerMiddleware's 403) chose, then logs user + action + path + ip.
    Sits OUTSIDE _RoleEnforcerMiddleware in _build_app() so it can see that
    middleware's 403s too.

    Downloads are logged when the response starts (status known, body not
    yet streamed), not when the last byte is sent — unlike FTP's
    on_file_sent, WSGI gives no completion hook, and a cancelled download
    still records that the user asked for the file.
    """

    def __init__(self, app):
        self._app = app

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "").upper()
        if method not in _AUDIT_ACTIONS and method not in _WRITE_METHODS:
            return self._app(environ, start_response)  # PROPFIND/OPTIONS/HEAD…

        def audited_start_response(status, headers, exc_info=None):
            try:
                self._record(method, status, environ)
            except Exception:
                pass  # best-effort — never break the response over a log line
            return start_response(status, headers, exc_info)

        return self._app(environ, audited_start_response)

    @staticmethod
    def _record(method, status, environ) -> None:
        code = int(status.split(" ", 1)[0])
        username, _pw = _parse_basic_auth(environ)
        ip = _client_ip(environ)

        if code == 403 and method in _WRITE_METHODS:
            log.warning(
                "WebDAV AUDIT: user=%r action=permission_denied method=%s path=%r ip=%s",
                username,
                method,
                _request_path(environ),
                ip,
            )
            return

        action = _AUDIT_ACTIONS.get(method)
        if action is None or code not in _AUDIT_OK_CODES[method]:
            return

        path = _request_path(environ)
        if method == "GET" and (path.endswith("/") or not _is_first_chunk(environ)):
            return  # directory listing, or a follow-up range of one download

        if method in ("MOVE", "COPY"):
            log.info(
                "WebDAV AUDIT: user=%r action=%s path=%r -> %r ip=%s",
                username,
                action,
                path,
                _destination_path(environ),
                ip,
            )
        else:
            log.info(
                "WebDAV AUDIT: user=%r action=%s path=%r ip=%s",
                username,
                action,
                path,
                ip,
            )


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
            _audit_login(user_name, role, environ)  # login / login_failed + ip
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

    # Order matters: _AuditMiddleware wraps _RoleEnforcerMiddleware (not the
    # other way round) so it sees the enforcer's own 403s, and sits inside
    # _CertMiddleware so the unauthenticated /webdav.crt download isn't audited.
    return _CertMiddleware(
        _AuditMiddleware(_RoleEnforcerMiddleware(dav_app)), cert_path=cert_path
    )


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

    2026-09-24: now returns a child of logging_setup's shared
    "cloudinatorftp" logger, same as prod_server.py's identical helper
    already did. This copy had been left building its own plain
    StreamHandler on sys.stderr — which by then is logging_setup's
    _TeeStream — so every Hypercorn line reached the log file
    double-timestamped and tagged [STDERR] (e.g. "[STDERR] [webdav_server]
    2026-09-24 02:57:50 [INFO] Running on https://..."), instead of as a
    normal [INFO]/[WARNING] logger line. `name` is kept for compatibility
    with the existing call site but no longer names the logger.
    """
    return logging_setup.get_logger("hypercorn")


# ── ASGI-level disconnect guard (fixes a real, verified silent-flood bug) ──


# The exact text guarded_send() raises with, shared with the except clause in
# __call__ below so the two can't drift apart — that clause must recognize
# ONLY this guard's own deliberate error, never a real connection failure.
_GUARD_MSG = (
    "WebDAV client disconnected mid-response (_DisconnectAbortMiddleware guard)"
)


class _DisconnectAbortMiddleware:
    """
    ASGI-level middleware wrapping WsgiToAsgi(wsgi_app). Fixes a real,
    silent, fast-flood bug — confirmed by reading the actual source of
    CPython's asyncio.sslproto, asgiref 3.12.1, and Hypercorn 0.18.0, not
    guessed:

    1. Once a client abruptly resets a connection (e.g. cancelling a large
       download), asyncio's own SSL transport (asyncio/sslproto.py's
       _SSLProtocol._write_appdata) NEVER raises on further write() calls —
       by design, per asyncio's documented Transport contract (write() is
       "fire and forget", errors surface via connection_lost(), not
       exceptions). Once past an internal grace threshold (5 writes), it
       just logs "SSL connection is closed" and silently no-ops — for
       EVERY remaining write, forever, with no way for calling code to
       detect this via a normal try/except.
    2. asgiref's WsgiToAsgiInstance.run_wsgi_app() streams a WSGI response
       body via an *unguarded* loop — `for output in wsgi_application(...):
       ... self.sync_send(...)` — with no try/except around sync_send() and
       no check of the ASGI receive() channel for a disconnect signal
       during that loop (verified directly against asgiref's actual
       wsgi.py source).
    3. wsgidav's FilesystemProvider just keeps yielding the next chunk of
       whatever file is being served, with no idea the client is gone.

    Combined: once a client cancels a large download, nothing in this
    chain ever stops — it silently "succeeds" (per point 1) and logs once
    per chunk, for every remaining chunk of the file, as fast as the rest
    of the file can be read from disk. For a large file cancelled early,
    that's thousands of log lines in a few seconds.

    Fix: watch the ASGI `receive()` channel for `http.disconnect` — which
    Hypercorn DOES deliver once its read-side loop detects the connection
    is gone (confirmed in hypercorn/protocol/http_stream.py) — for the
    full lifetime of the request, including during the response-streaming
    phase when neither wsgidav nor asgiref ever call receive() again
    themselves. Once disconnect is observed, the wrapped `send()` starts
    raising instead of silently succeeding — which DOES propagate, since
    asgiref's sync_send() call is unguarded (point 2 above) — breaking the
    WSGI response loop on the very next chunk instead of continuing
    through the rest of the file.

    Careful to avoid a receive() race with the inner app: WsgiToAsgiInstance
    reads the full request body via its own receive() loop before ever
    calling the wrapped WSGI app. This middleware's own background watcher
    does not start pulling from receive() itself until AFTER it has
    observed (via wrapping the SAME receive() calls the inner app makes)
    that the inner app's body-read loop has completed — so the two never
    compete for the same message.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        disconnected = False
        body_fully_received = asyncio.Event()

        async def watched_receive():
            nonlocal disconnected
            message = await receive()
            if message.get("type") == "http.disconnect":
                disconnected = True
            elif message.get("type") == "http.request" and not message.get(
                "more_body", False
            ):
                body_fully_received.set()
            return message

        async def watch_after_body():
            nonlocal disconnected
            await body_fully_received.wait()
            try:
                while not disconnected:
                    message = await receive()
                    if message.get("type") == "http.disconnect":
                        disconnected = True
            except Exception:
                # Any failure here just means we stop watching — worst
                # case we fall back to the pre-fix (slow) behavior for
                # this one request, never worse.
                pass

        async def guarded_send(message):
            if disconnected:
                raise ConnectionResetError(_GUARD_MSG)
            await send(message)

        watcher = asyncio.ensure_future(watch_after_body())
        try:
            await self.app(scope, watched_receive, guarded_send)
        except ConnectionResetError as exc:
            # 2026-09-24: guarded_send() raising is this middleware doing its
            # job — it's how a cancelled download's response loop gets broken
            # (see the class docstring). That raise is meant to end the
            # request, not to be reported as a server failure, but nothing
            # caught it, so Hypercorn logged a full "Error in ASGI
            # Framework" traceback every time. Most visibly when a client
            # hung up right after receiving a complete response, a split
            # second before asgiref's final empty body send — nothing was
            # actually wrong, the client already had everything. Swallow
            # ONLY this guard's own error (matched on its exact message);
            # any other ConnectionResetError — a real one from the socket,
            # from wsgidav, from anywhere else — is re-raised exactly as
            # before. The response loop was already broken by the raise
            # itself, so the flood protection is unaffected.
            if str(exc) != _GUARD_MSG:
                raise
        finally:
            disconnected = True  # lets the watcher's own loop condition exit
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass


# ── Connection-teardown errors (TLS close_notify) ──────────────────────────
# An ssl.SSLError APPLICATION_DATA_AFTER_CLOSE_NOTIFY at connection teardown
# used to escape Hypercorn's TCPServer._close() as an anonymous "Unhandled
# exception in client_connected_cb" traceback (no client address — asyncio no
# longer knows it by then). That is now handled where the rest of the
# _close() fixes live: hypercorn_ssl_fix.py's patched _close(), applied at the
# top of this file, reads the peer before teardown and logs one IP-tagged
# line. Nothing needed here.


def _start_hypercorn(wsgi_app, http_port, https_port, cert_path, key_path):
    """Runs WebDAV (HTTP and/or HTTPS) via Hypercorn in a background thread.
    Returns the Thread object."""
    from asgiref.wsgi import WsgiToAsgi
    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    asgi_app = _DisconnectAbortMiddleware(WsgiToAsgi(wsgi_app))

    cfg = Config()
    cfg.bind = [f"0.0.0.0:{https_port}"] if https_port else []
    cfg.insecure_bind = [f"0.0.0.0:{http_port}"] if http_port else []
    cfg.errorlog = _build_hypercorn_logger(
        "hypercorn.webdav"
    )  # see _build_hypercorn_logger's docstring
    if https_port:
        cfg.certfile = cert_path
        cfg.keyfile = key_path
        # HTTP/1.1 only — deliberately NOT offering "h2" here.
        # WebDAV is mounted by OS-level clients (Windows WebClient/mrxdav.sys,
        # davfs2, Cyberduck, etc.), almost all of which are HTTP/1.1-only.
        # If TLS negotiates h2 with one of these (their TLS layer can claim
        # ALPN h2 support even though the WebDAV component can't actually
        # speak HTTP/2 framing), the connection breaks below the HTTP layer —
        # surfacing as "SSL connection closed" rather than a clean HTTP
        # error, and repeating forever as the OS driver auto-retries the
        # mount/download. Unlike prod_server.py's main app (browser-only,
        # h2 is safe and desired there), WebDAV gains nothing from h2 and
        # loses broad client compatibility, so it stays HTTP/1.1-only.
        cfg.alpn_protocols = ["http/1.1"]
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
        print(f"🔐 WebDAV HTTPS: https://{LOCAL_IP}:{https_port}/  (HTTP/1.1 only)")
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


# ── Standalone process entrypoint ───────────────────────────────────────────
# WebDAV is launched as its own OS process by protocol_manager.py (see
# _spawn_webdav_process there), NOT as a thread inside the main app's
# process like SFTP/FTP/SMB still are. Reason: Hypercorn/asyncio has a known
# failure mode where a large in-flight download that the client cancels
# mid-transfer can leave the event loop stuck retrying a write to a dead SSL
# transport in a tight, non-terminating loop ("SSL connection closed",
# flooding the log, CPU pegged on that thread) — with no clean way to
# recover except killing the whole process. Running WebDAV in its own
# process means that failure mode now only costs a WebDAV restart (see
# protocol_manager.restart_webdav()), not a full-server restart — the main
# app keeps serving on :5000 throughout.


def _run_standalone():
    """
    Entrypoint used when this module is launched as `python webdav_server.py`
    (a subprocess of the main app, not imported). Starts WebDAV and then
    blocks in the foreground so the process stays alive for the parent to
    supervise, until it receives SIGTERM/SIGINT (normal shutdown, exit code
    0 — see protocol_manager.stop_all()/restart_webdav()) or start() fails
    (exit code 1, so the parent's watchdog knows to retry).

    Exits 0 immediately, without starting anything, if both WEBDAV_ENABLED
    and WEBDAV_HTTPS_ENABLED are off — this is treated as an intentional
    "nothing to do" exit, distinct from a real failure, so the parent's
    watchdog does NOT try to respawn it in that case.
    """
    import signal

    try:
        from config import WEBDAV_ENABLED, WEBDAV_HTTPS_ENABLED
    except ImportError:
        WEBDAV_ENABLED, WEBDAV_HTTPS_ENABLED = True, True

    if not WEBDAV_ENABLED and not WEBDAV_HTTPS_ENABLED:
        print("ℹ️  WebDAV disabled in config.py — subprocess exiting cleanly.")
        return  # exit code 0, watchdog will not respawn

    if not start():
        # start() already printed the specific reason (missing dependency,
        # port bind failure, etc.) — exit non-zero so the parent knows this
        # was a real failure, not an intentional no-op.
        raise SystemExit(1)

    stop_requested = threading.Event()

    def _handle_signal(signum, frame):
        print(f"\n🛑 WebDAV process received signal {signum}, shutting down...")
        stop()
        stop_requested.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # The actual Hypercorn server runs in _webdav_thread (a daemon thread
    # started by start()) — just block the main thread here until told to
    # stop, so the process (and its daemon thread) stays alive.
    while not stop_requested.is_set():
        stop_requested.wait(timeout=1)


if __name__ == "__main__":
    _run_standalone()
