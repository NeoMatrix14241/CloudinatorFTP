"""
smb_server.py — SMB server for CloudinatorFTP
-------------------------------------------------------------------------
Exposes ROOT_DIR over SMB (so Windows/macOS/Linux can map it as a real
network drive, discoverable via \\\\HOST\\ShareName) using impacket's
SimpleSMBServer.

Why impacket: there is no mature, production-grade, pure-Python SMB
SERVER library. impacket's smbserver module is the only practical
"runs in our own process" option — it's primarily known as a component
of penetration-testing tooling, which is worth being aware of, but the
SimpleSMBServer class itself is a straightforward, documented SMB1/2
server implementation with no offensive-security behavior of its own.

────────────────────────────────────────────────────────────────────────
AUTHENTICATION — why this needs an NT hash, not a plaintext check
────────────────────────────────────────────────────────────────────────
SMB uses NTLM, a challenge-response protocol: the plaintext password is
NEVER sent over the wire. The server must already know the NT hash (raw
MD4 of the password) to verify a client's response itself. This is true
of every SMB server, including real Windows and Samba.

Because of this, we can't call database.db.check_login(user, password)
the way the other protocols do — by the time a request arrives, there
is no plaintext to check. Instead, database.py captures and stores the
NT hash at the moment a password is actually set (add_user /
update_password), and this module loads all known hashes into
impacket's in-memory credential table at startup, refreshing
periodically so changes don't require a full SMB restart.

Any user created before this feature existed has no NT hash on record
and cannot authenticate over SMB until their password is reset once —
see database.db.users_missing_nt_hash().

────────────────────────────────────────────────────────────────────────
PER-USER READ/WRITE ENFORCEMENT — how this maps to readwrite/readonly
────────────────────────────────────────────────────────────────────────
impacket's addShare() only supports a single READ-ONLY FLAG PER SHARE,
not per-user. But impacket's existing internal access-control checks
(in smb2Create, smbComCreateDirectory, etc.) all key off a per-CONNECTION
value: connData['ConnectedShares'][tid]["read only"], which is set once,
at Tree Connect time, from the share's static registration.

Rather than reimplement file-level access control ourselves, we hook
the Tree Connect handlers (SMB2 and SMB1) to call the original handler
first, then OVERRIDE that per-connection flag immediately afterward,
based on the authenticated user's role in our own database. Every
existing write-check inside impacket then automatically respects it —
zero duplicated access-control logic, and we inherit impacket's
already-tested enforcement across every command, not just the ones we
thought to check.

The share is registered as read-only by default (fail-safe): only a
user confirmed to hold the 'readwrite' role gets it loosened to
read-write for their connection. Any lookup error leaves it locked.

────────────────────────────────────────────────────────────────────────
PORT 445 — this module never touches the OS to try to claim it
────────────────────────────────────────────────────────────────────────
Binding port 445 needs root (Linux/Android) or for Windows' own native
file-sharing service to be out of the way first. This module makes
exactly one attempt to bind it, and silently falls back to
SMB_FALLBACK_PORT (8445) if that fails — it never stops services, never
requests elevation, never touches anything system-level itself.

The one-time, human-run setup that actually clears the way for port 445
lives in smb_setup.py (run via `python smb_setup.py` or
`./manage.sh smb-setup`) — see SMB_PROTOCOL_DEPLOYMENT.md for the full
walkthrough per platform. On Windows specifically, that setup requires a
restart to take effect; this module reads back a small pending-state
file (via lanman_guard.py) purely to give an accurate fallback message
("looks like you haven't restarted yet" vs "nothing's been set up").
"""

import itertools
import logging
import os
import platform
import threading

log = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"

_server = None
_thread: threading.Thread | None = None
_refresh_thread: threading.Thread | None = None
_stop_event = threading.Event()

_CREDENTIAL_REFRESH_SECONDS = 30
_uid_counter = itertools.count(1000)


# ── Tree Connect hook — the actual per-user permission enforcement ─────────


def _make_tree_connect_hooks():
    """
    Build wrapped versions of the SMB1 and SMB2 Tree Connect handlers that
    call the real impacket handler first, then override the connected
    share's effective read-only flag for THIS connection based on the
    authenticated user's role.

    Returns (smb1_hook, smb2_hook) with mutable default-arg cells used to
    stash the original handlers once start() registers them — see
    _install_role_enforcement().
    """

    def _apply_role(connData, tid: int):
        """Mutate connData in place to tighten/loosen read-only for this TID.
        Caller is responsible for persisting connData via setConnectionData."""
        if tid not in connData.get("ConnectedShares", {}):
            return
        username = connData.get("user_name")
        role = None
        if username:
            try:
                from database import db

                role = db.get_role(username)
            except Exception as e:
                log.warning(f"SMB: role lookup failed for {username!r}: {e}")

        # Fail-safe: anything other than a confirmed 'readwrite' stays read-only.
        is_readwrite = role == "readwrite"
        connData["ConnectedShares"][tid]["read only"] = "no" if is_readwrite else "yes"

    def smb1_tree_connect_hook(connId, smbServer, SMBCommand, recvPacket, _orig=[None]):
        result = _orig[0](connId, smbServer, SMBCommand, recvPacket)
        try:
            connData = smbServer.getConnectionData(connId)
            if connData.get("ConnectedShares"):
                newest_tid = list(connData["ConnectedShares"].keys())[-1]
                _apply_role(connData, newest_tid)
                smbServer.setConnectionData(connId, connData)
        except Exception as e:
            log.warning(f"SMB1 tree-connect role enforcement error: {e}")
        return result

    def smb2_tree_connect_hook(connId, smbServer, recvPacket, _orig=[None]):
        result = _orig[0](connId, smbServer, recvPacket)
        try:
            connData = smbServer.getConnectionData(connId)
            if connData.get("ConnectedShares"):
                newest_tid = list(connData["ConnectedShares"].keys())[-1]
                _apply_role(connData, newest_tid)
                smbServer.setConnectionData(connId, connData)
        except Exception as e:
            log.warning(f"SMB2 tree-connect role enforcement error: {e}")
        return result

    return smb1_tree_connect_hook, smb2_tree_connect_hook


def _install_role_enforcement(server):
    """Register the Tree Connect hooks on the live impacket server instance."""
    from impacket import smb
    from impacket import smb3structs as smb2

    inner = server.getServer()  # the underlying SMBSERVER instance (public accessor)
    smb1_hook, smb2_hook = _make_tree_connect_hooks()

    # smbComTreeConnectAndX is the SMB1 dispatch key; SMB2_TREE_CONNECT for SMB2.
    original_smb1 = inner.hookSmbCommand(smb.SMB.SMB_COM_TREE_CONNECT_ANDX, smb1_hook)
    original_smb2 = inner.hookSmb2Command(smb2.SMB2_TREE_CONNECT, smb2_hook)
    # Bind the captured originals into the closures via their default-arg cells.
    smb1_hook.__defaults__ = ([original_smb1],)
    smb2_hook.__defaults__ = ([original_smb2],)


# ── Auth callback — logging only; the real role check happens above ────────


def _auth_callback(smbServer, connData, domain_name, user_name, host_name):
    log.info(f"SMB: {user_name!r} authenticated from {host_name!r}")


# ── Credential loading ──────────────────────────────────────────────────────


def _load_credentials(server, log_missing: bool = True):
    """
    (Re)load all known NT-hash credentials from the database into impacket.

    IMPORTANT: clears the existing table first. addCredential() only ever
    adds or overwrites — it has no corresponding remove, so without this
    clear, a deleted (or renamed) user's old credential would silently
    linger in memory forever, valid, even though they no longer exist in
    our database. Confirmed directly: deleting a user and reloading
    without clearing first still let them log in with the old password.
    getCredentials() returns the real internal dict by reference (not a
    copy — checked the source directly), so .clear() on it is safe and
    immediate.
    """
    from database import db

    inner = server.getServer()
    inner.getCredentials().clear()

    creds = db.get_smb_credentials()
    for username, nt_hash_hex in creds:
        server.addCredential(username, next(_uid_counter), "", nt_hash_hex)

    if log_missing:
        missing = db.users_missing_nt_hash()
        if missing:
            print(
                f"⚠️  SMB: {len(missing)} user(s) cannot use SMB until their password "
                f"is reset once: {', '.join(missing)}"
            )
    return len(creds)


def _credential_refresh_loop(server):
    """Periodically reload credentials so password/user changes propagate
    without requiring a full SMB server restart. NTLM auth requires
    pre-known hashes (see module docstring) so this can't be instant the
    way the other protocols are, but ~30s is a reasonable compromise."""
    while not _stop_event.wait(_CREDENTIAL_REFRESH_SECONDS):
        try:
            _load_credentials(server, log_missing=False)
        except Exception as e:
            log.warning(f"SMB credential refresh failed: {e}")


# ── Port selection ──────────────────────────────────────────────────────────


def _try_bind(port: int) -> bool:
    """Quick pre-check: can we bind this TCP port right now?"""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _select_port(preferred: int, fallback: int, state_path: str) -> int:
    """
    Try the preferred port (445 by default) first. On failure, fall back
    to `fallback` — this module never touches the OS itself to try to
    claim the preferred port. See smb_setup.py for the one-time, manual,
    human-run setup that actually does that (Windows: needs a restart;
    Linux: setcap, immediate; Android: root or nothing).
    """
    if _try_bind(preferred):
        # Confirms any prior smb_setup.py change actually took effect
        # (e.g. the user restarted Windows since running it) — nothing to
        # track anymore once we know it works.
        if _IS_WINDOWS:
            import lanman_guard

            if lanman_guard.get_pending_state(state_path):
                lanman_guard.clear_pending_state(state_path)
                print(
                    f"✅ SMB: port {preferred} confirmed working — setup is complete."
                )
        return preferred

    if _IS_WINDOWS:
        import lanman_guard

        pending = lanman_guard.get_pending_state(state_path)
        if pending:
            print(
                f"⚠️  SMB: port {preferred} still isn't available since you ran "
                f"smb_setup.py on {pending.get('changed_at', '?')}."
            )
            print(
                f"   If you haven't restarted since then, restart now (use Restart, "
                f"not Shut Down). Already restarted? Something else may be holding "
                f"the port — check: netstat -ano | findstr :{preferred}"
            )
        else:
            print(
                f"⚠️  SMB: port {preferred} is in use (likely Windows' own file "
                f"sharing). Run `python smb_setup.py` once to allow CloudinatorFTP "
                f"to use it — see SMB_PROTOCOL_DEPLOYMENT.md for details."
            )
    else:
        print(
            f"⚠️  SMB: could not bind port {preferred} (needs root, or a one-time "
            f"capability grant). Run `python smb_setup.py` once — see "
            f"SMB_PROTOCOL_DEPLOYMENT.md for details."
        )

    print(f"   Falling back to port {fallback}.")
    if _IS_WINDOWS and fallback >= 1024:
        # Windows 11 24H2+/Server 2025+ support custom-port SMB via /TCPPORT:
        print(
            f"   Map with:  net use X: \\\\HOST\\SHARE /TCPPORT:{fallback}  (Windows 11 24H2+ / Server 2025+ only)"
        )
        print(f"   Older Windows clients cannot map a non-445 SMB share natively.")
    return fallback


# ── Public API ────────────────────────────────────────────────────────────


def start() -> bool:
    """
    Start the SMB server in a background daemon thread.
    Returns True on success, False if disabled, impacket is not installed,
    or no port could be bound.
    """
    global _server, _thread, _refresh_thread

    try:
        from config import (
            SMB_ENABLED,
            SMB_PORT,
            SMB_FALLBACK_PORT,
            SMB_SHARE_NAME,
            ROOT_DIR,
        )
    except ImportError:
        SMB_ENABLED, SMB_PORT, SMB_FALLBACK_PORT = False, 445, 8445
        SMB_SHARE_NAME = "SharedFolder"
        try:
            from config import ROOT_DIR
        except ImportError:
            print("❌ SMB: cannot import ROOT_DIR from config.py")
            return False

    if not SMB_ENABLED:
        return False

    try:
        from impacket.smbserver import SimpleSMBServer
    except ImportError:
        print("⚠️  SMB not started: 'impacket' is not installed.")
        print("   Install it: pip install impacket")
        return False

    from paths import get_db_dir

    db_dir = get_db_dir(create=True)
    state_path = os.path.join(db_dir, ".smb_lanman_state.json")

    port = _select_port(SMB_PORT, SMB_FALLBACK_PORT, state_path)

    try:
        server = SimpleSMBServer(listenAddress="0.0.0.0", listenPort=port)
        server.addShare(SMB_SHARE_NAME, ROOT_DIR, "CloudinatorFTP", readOnly="yes")
        server.setSMB2Support(True)
        server.setAuthCallback(_auth_callback)
        _install_role_enforcement(server)

        # Must be set BEFORE the server starts accepting connections: both
        # attributes are only consulted at the moment each connection is
        # handled (block_on_close decides whether the thread even gets
        # tracked for a later join; daemon_threads is read once at thread
        # creation). Setting either of these later, e.g. in stop(), is too
        # late for any connection already in progress — confirmed directly:
        # a single abandoned connection (a client that disconnects right
        # after a failed login) is enough to make server_close() hang
        # forever joining that thread's blocked socket.recv() otherwise.
        inner = server.getServer()
        inner.daemon_threads = True
        inner.block_on_close = False

        loaded = _load_credentials(server)
        if loaded == 0:
            print(
                "⚠️  SMB: no users have an NT hash on record yet — nobody can "
                "log in until at least one password is reset (see above)."
            )
    except Exception as e:
        print(f"❌ SMB server build failed: {e}")
        return False

    _server = server
    _stop_event.clear()

    _thread = threading.Thread(target=server.start, name="smb-server", daemon=True)
    _thread.start()

    _refresh_thread = threading.Thread(
        target=_credential_refresh_loop,
        args=(server,),
        name="smb-cred-refresh",
        daemon=True,
    )
    _refresh_thread.start()

    print(
        f"📡 SMB:     \\\\HOST:{port}\\{SMB_SHARE_NAME}"
        if port != 445
        else f"📡 SMB:     \\\\HOST\\{SMB_SHARE_NAME}"
    )
    print(
        f"   Windows → Map Network Drive → \\\\HOST\\{SMB_SHARE_NAME}"
        + (f" /TCPPORT:{port}" if port != 445 else "")
    )
    return True


def stop():
    """
    Stop the SMB server (best-effort). Does not touch LanmanServer or any
    other OS state — see smb_setup.py for that, which is a separate,
    manually-run, one-time tool, not something tied to server start/stop.

    Relies on daemon_threads=True and block_on_close=False having been set
    in start() BEFORE the server began accepting connections — see the
    comment there for why that timing matters. With those set correctly,
    shutdown() + server_close() return promptly even if a connection was
    abandoned mid-session (e.g. a client that disconnected right after a
    failed login, which otherwise hangs server_close() forever — confirmed
    directly while building this).
    """
    global _server
    _stop_event.set()
    if _server:
        try:
            inner = _server.getServer()
            inner.shutdown()
            inner.server_close()
        except Exception as e:
            log.warning(f"SMB stop() cleanup error: {e}")
        _server = None
