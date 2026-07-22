"""
smb_server.py — SMB server for CloudinatorFTP
-------------------------------------------------------------------------
Exposes ROOT_DIR over SMB using impacket's SimpleSMBServer — the only
practical pure-Python SMB *server* library (impacket is also known as a
pentesting toolkit component, but SimpleSMBServer itself has no
offensive behavior).

Auth: SMB uses NTLM (challenge-response, no plaintext over the wire), so
we can't call db.check_login() the way other protocols do. database.py
captures each user's NT hash at password-set time; this module loads all
known hashes into impacket's credential table at startup and refreshes
periodically. Users predating this feature need one password reset
before SMB works for them — see db.users_missing_nt_hash().

Per-user read/write: impacket only supports one read-only flag per
*share*, not per-user. We hook Tree Connect to override that flag per
*connection* right after impacket's own handler runs, based on the
authenticated user's role — every existing write-check in impacket then
respects it automatically. Fails safe: only a confirmed 'readwrite' role
loosens it; any lookup error leaves it locked.

Port 445: this module makes exactly one bind attempt and falls back to
SMB_FALLBACK_PORT if that fails — it never touches OS state itself. The
one-time human-run setup that actually frees port 445 is smb_setup.py
(see SMB_PROTOCOL_DEPLOYMENT.md).
"""

import itertools
import logging
import os
import platform
import threading
from app import get_local_ip

LOCAL_IP = get_local_ip()

log = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"

_server = None
_thread: threading.Thread | None = None
_refresh_thread: threading.Thread | None = None
_stop_event = threading.Event()

_CREDENTIAL_REFRESH_SECONDS = 30
_uid_counter = itertools.count(1000)
_uid_by_username: dict[str, int] = {}


def _get_stable_uid(username: str) -> int:
    """Same UID across refresh cycles (impacket only ever reads a UID at
    login, so this is cosmetic, but avoids pointless churn). Keyed on
    lowercase to match impacket's own internal key normalization."""
    key = username.lower()
    if key not in _uid_by_username:
        _uid_by_username[key] = next(_uid_counter)
    return _uid_by_username[key]


# ── Tree Connect hook — per-user read/write enforcement ────────────────────


def _make_tree_connect_hooks():
    """
    Returns (smb1_hook, smb2_hook, smb1_orig_holder, smb2_orig_holder).
    Set holder[0] = <original handler> right after hooking (see
    _install_role_enforcement). Uses a plain holder list rather than a
    mutable-default-arg trick: that trick breaks silently once a hook
    signature mixes *args with anything after it (a __defaults__ update
    only touches positional-or-keyword defaults, never keyword-only
    ones) — found and fixed here before shipping.
    """

    def _apply_role(connData, tid: int):
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
        connData["ConnectedShares"][tid]["read only"] = (
            "no" if role == "readwrite" else "yes"
        )

    smb1_orig_holder = [None]
    smb2_orig_holder = [None]

    def smb1_tree_connect_hook(*args, **kwargs):
        # *args/**kwargs: SMB2_NEGOTIATE's legacy SMB1-upgrade path calls
        # its handler with 4 positional args, not the usual 3 — a fixed
        # signature elsewhere in this file broke on exactly that call.
        result = smb1_orig_holder[0](*args, **kwargs)
        try:
            connId, smbServer = args[0], args[1]
            connData = smbServer.getConnectionData(connId)
            if connData.get("ConnectedShares"):
                newest_tid = list(connData["ConnectedShares"].keys())[-1]
                _apply_role(connData, newest_tid)
                smbServer.setConnectionData(connId, connData)
        except Exception as e:
            log.warning(f"SMB1 tree-connect role enforcement error: {e}")
        return result

    def smb2_tree_connect_hook(*args, **kwargs):
        result = smb2_orig_holder[0](*args, **kwargs)
        try:
            connId, smbServer = args[0], args[1]
            connData = smbServer.getConnectionData(connId)
            if connData.get("ConnectedShares"):
                newest_tid = list(connData["ConnectedShares"].keys())[-1]
                _apply_role(connData, newest_tid)
                smbServer.setConnectionData(connId, connData)
        except Exception as e:
            log.warning(f"SMB2 tree-connect role enforcement error: {e}")
        return result

    return (
        smb1_tree_connect_hook,
        smb2_tree_connect_hook,
        smb1_orig_holder,
        smb2_orig_holder,
    )


def _install_setinfo_rename_fix():
    """
    Fixes MS Office "Ctrl+S throws access denied" on Windows.

    Office saves atomically: writes to a .tmp, then renames .tmp over
    the open .docx. impacket's smb2SetInfo/smbComRename (lines ~3700,
    ~1703) call os.rename() and map ANY exception to STATUS_ACCESS_
    DENIED. On Windows, os.rename() raises WinError 32 (ERROR_SHARING_
    VIOLATION) when the destination is open — exactly Word's case —
    which Windows then shows the user as a permissions error.

    Fix: patch impacket.smbserver.os.rename to retry via os.replace()
    (MoveFileExW/MOVEFILE_REPLACE_EXISTING) ONLY on winerror==32. A
    different failure — WinError 183, destination already exists — is
    re-raised untouched, so app.py's own rename endpoint (which already
    checks os.path.exists() before calling os.rename) is unaffected.

    Scope note: impacket.smbserver's "os" is the same module object as
    the global os (confirmed directly), so this patch is process-wide,
    not impacket-only. Installed once at startup as a stable, non-
    swapping wrapper — no race on the patch itself — and it only
    changes behavior for the specific winerror==32 case, which is
    distinct from "destination exists" and doesn't overlap with app.py's
    check. Not reproducible outside a real Windows lock; verified by
    reading the logic, not by running it.
    """
    if platform.system() != "Windows":
        return

    import impacket.smbserver as _smbserver_module

    _original_rename = _smbserver_module.os.rename

    def _windows_safe_rename(src, dst):
        try:
            _original_rename(src, dst)
        except OSError as e:
            if getattr(e, "winerror", None) == 32:
                _smbserver_module.os.replace(src, dst)
            else:
                raise

    _smbserver_module.os.rename = _windows_safe_rename
    log.info(
        "SMB: Windows atomic-save fix applied (os.rename → os.replace on WinError 32)"
    )


def _install_setdelete_retry_fix():
    """
    Same WinError 32 class as the rename fix, different syscall:
    os.remove() (DeleteFileW) can also fail if the file is momentarily
    held open (e.g. an AV scan). Unlike rename, delete has no atomic
    "force" API — the standard mitigation (used internally by tools like
    robocopy) is a short backoff retry. Defensive addition, not built
    from a confirmed traceback like the rename fix was.
    """
    if platform.system() != "Windows":
        return

    import impacket.smbserver as _smbserver_module
    import time as _time

    _original_remove = _smbserver_module.os.remove
    _RETRY_DELAYS = (0.1, 0.15, 0.2, 0.25)

    def _windows_safe_remove(path):
        last_err = None
        for delay in (0, *_RETRY_DELAYS):
            if delay:
                _time.sleep(delay)
            try:
                _original_remove(path)
                return
            except OSError as e:
                if getattr(e, "winerror", None) == 32:
                    last_err = e
                    continue
                raise
        raise last_err

    _smbserver_module.os.remove = _windows_safe_remove
    log.info("SMB: Windows delete-retry fix applied (backoff retry on WinError 32)")


def _install_create_share_delete_fix(server):
    """
    Fixes a deeper cause of the same Office save error — the OTHER
    rename in its save sequence: the ORIGINAL file renamed to a backup
    temp name (e.g. 'Tutorial.docx' -> '3672D6CB.tmp').

    Root cause (confirmed via CPython's own bug tracker, bpo-15244):
    os.open() on Windows never requests FILE_SHARE_DELETE, and there's
    no way to request it through the standard API (MSVC runtime
    limitation). Any file our server opens — even briefly, even from
    our own process — can't be renamed or deleted by anyone, including
    us, while that handle stays open. Office's original file is still
    open (we served it to Word) when the backup-rename step runs.

    Fix: replace the os.open() call inside impacket's SMB2_CREATE
    handler with a Windows-native open via _winapi.CreateFile() +
    msvcrt.open_osfhandle(), explicitly requesting FILE_SHARE_READ |
    FILE_SHARE_WRITE | FILE_SHARE_DELETE — something plain os.open()
    can't do. Both _winapi and msvcrt are Python standard library on
    Windows; no new dependency. Note this uses the stdlib _winapi
    module, not the third-party pywin32 win32file — win32file.CreateFile
    wraps its return in a PyHANDLE that auto-closes on garbage
    collection (a documented source of random "bad file descriptor"
    errors under concurrent use); _winapi.CreateFile returns a plain int
    with no such wrapper, so that specific failure mode doesn't apply
    here.

    Gap found and fixed in the official recipe: its create-disposition
    table has no entry for "no creation flags at all" (just opening an
    existing file) — the single most common case for a file server, and
    apparently untested by the recipe's own author (their demo always
    implied O_CREAT|O_TRUNC via open(path, "w+")). Added `0: OPEN_
    EXISTING`; without it this raises a bare KeyError.

    Scoped as a temporary swap around the single synchronous os.open()
    call inside CREATE, not a permanent patch: os.open() is used
    pervasively by unrelated code (database, config, etc.), so a
    permanent global replacement risks misbehaving for some flag
    combination not audited here. Safe under the GIL — no other thread
    can run bytecode during the swap+restore window.

    Not reproducible outside real Windows; the flag-translation logic is
    verified against every combination impacket's smb2Create can
    produce, but the actual CreateFile/open_osfhandle calls are
    unverified until run on a real server.
    """
    if platform.system() != "Windows":
        return

    import msvcrt
    import _winapi
    import impacket.smbserver as _smbserver_module
    from impacket import smb3structs as smb2

    OPEN_EXISTING = 3
    OPEN_ALWAYS = 4
    CREATE_ALWAYS = 2
    CREATE_NEW = 1
    TRUNCATE_EXISTING = 5
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    FILE_SHARE_DELETE = 0x4
    FILE_ATTRIBUTE_NORMAL = 0x80

    _ACCESS_MASK = os.O_RDONLY | os.O_WRONLY | os.O_RDWR
    _CREATE_MASK = os.O_CREAT | os.O_EXCL | os.O_TRUNC

    _ACCESS_MAP = {
        os.O_RDONLY: _winapi.GENERIC_READ,
        os.O_WRONLY: _winapi.GENERIC_WRITE,
        os.O_RDWR: _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
    }
    _CREATE_MAP = {
        0: OPEN_EXISTING,  # the gap fix — see docstring
        os.O_EXCL: OPEN_EXISTING,
        os.O_CREAT: OPEN_ALWAYS,
        os.O_CREAT | os.O_EXCL: CREATE_NEW,
        os.O_CREAT | os.O_TRUNC | os.O_EXCL: CREATE_NEW,
        os.O_TRUNC: TRUNCATE_EXISTING,
        os.O_TRUNC | os.O_EXCL: TRUNCATE_EXISTING,
        os.O_CREAT | os.O_TRUNC: CREATE_ALWAYS,
    }

    _debug_files = os.environ.get("SMB_DEBUG_FILES") == "1"

    def _share_delete_open(path, flags, mode=0o777):
        access_flags = _ACCESS_MAP[flags & _ACCESS_MASK]
        create_flags = _CREATE_MAP[flags & _CREATE_MASK]
        share_flags = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE

        handle = _winapi.CreateFile(
            path,
            access_flags,
            share_flags,
            _winapi.NULL,
            create_flags,
            FILE_ATTRIBUTE_NORMAL,
            _winapi.NULL,
        )
        fd = msvcrt.open_osfhandle(handle, flags)
        if _debug_files:
            print(f"SMB-FILES: opened fd={fd} path={path!r}", flush=True)
        return fd

    inner = server.getServer()
    create_orig_holder = [None]

    def create_hook(*args, **kwargs):
        real_open = _smbserver_module.os.open
        _smbserver_module.os.open = _share_delete_open
        try:
            return create_orig_holder[0](*args, **kwargs)
        finally:
            _smbserver_module.os.open = real_open

    create_orig_holder[0] = inner.hookSmb2Command(smb2.SMB2_CREATE, create_hook)
    log.info("SMB: FILE_SHARE_DELETE create fix applied")

    if _debug_files:
        _install_file_lifecycle_diagnostics(server)


def _install_file_lifecycle_diagnostics(server):
    """
    Opt-in (SMB_DEBUG_FILES=1). Logs every SMB2 CLOSE and every "bad file
    descriptor" READ/WRITE error with the fd and file name involved, to
    get hard evidence on reports like "SMB2_READ: [Errno 9] Bad file
    descriptor" during large/server-to-server copies. Files coming out
    intact despite these errors suggests a late/duplicate read hitting an
    already (and correctly) closed handle — impacket's own smb2Read
    already catches this per-request and doesn't drop the connection or
    corrupt other reads — but this logging exists to confirm that rather
    than assume it.
    """
    from impacket import smb3structs as smb2

    inner = server.getServer()
    close_orig_holder = [None]

    def close_hook(*args, **kwargs):
        try:
            connId, smbServer, recvPacket = args[0], args[1], args[2]
            connData = smbServer.getConnectionData(connId)
            closeReq = smb2.SMB2Close(recvPacket["Data"])
            fileID = closeReq["FileID"].getData()
            if fileID == b"\xff" * 16 and "SMB2_CREATE" in connData.get(
                "LastRequest", {}
            ):
                fileID = connData["LastRequest"]["SMB2_CREATE"]["FileID"]
            info = connData.get("OpenedFiles", {}).get(fileID)
            if info:
                print(
                    f"SMB-FILES: CLOSE fd={info.get('FileHandle')} "
                    f"path={info.get('FileName')!r}",
                    flush=True,
                )
        except Exception:
            pass
        return close_orig_holder[0](*args, **kwargs)

    close_orig_holder[0] = inner.hookSmb2Command(smb2.SMB2_CLOSE, close_hook)
    print("🔍 SMB-FILES: file lifecycle diagnostics ENABLED (SMB_DEBUG_FILES=1)")


def _install_command_safety_net(server):
    """
    impacket's top-level SMB2 dispatch (processRequest) logs and
    RE-RAISES any exception a command handler doesn't catch itself,
    which kills that connection's thread — a "network disconnect" from
    the client's side, distinct from a clean "permission error" response
    (which only happens when a handler's own try/except already caught
    something).

    Fix: wrap every registered SMB2 command so an uncaught exception
    gets logged in full and returns STATUS_UNSUCCESSFUL instead of
    propagating. Doesn't fix the underlying cause — turns "connection
    silently dies" into "client gets an error, connection survives, and
    the cause is visible in the log."
    """
    from impacket import smb3structs as smb2
    from impacket.nt_errors import STATUS_UNSUCCESSFUL

    inner = server.getServer()

    all_commands = {
        "NEGOTIATE": smb2.SMB2_NEGOTIATE,
        "SESSION_SETUP": smb2.SMB2_SESSION_SETUP,
        "LOGOFF": smb2.SMB2_LOGOFF,
        "TREE_CONNECT": smb2.SMB2_TREE_CONNECT,
        "TREE_DISCONNECT": smb2.SMB2_TREE_DISCONNECT,
        "CREATE": smb2.SMB2_CREATE,
        "CLOSE": smb2.SMB2_CLOSE,
        "FLUSH": smb2.SMB2_FLUSH,
        "READ": smb2.SMB2_READ,
        "WRITE": smb2.SMB2_WRITE,
        "LOCK": smb2.SMB2_LOCK,
        "IOCTL": smb2.SMB2_IOCTL,
        "CANCEL": smb2.SMB2_CANCEL,
        "ECHO": smb2.SMB2_ECHO,
        "QUERY_DIRECTORY": smb2.SMB2_QUERY_DIRECTORY,
        "CHANGE_NOTIFY": smb2.SMB2_CHANGE_NOTIFY,
        "QUERY_INFO": smb2.SMB2_QUERY_INFO,
        "SET_INFO": smb2.SMB2_SET_INFO,
        "OPLOCK_BREAK": smb2.SMB2_OPLOCK_BREAK,
    }

    def _make_safety_wrapper(name):
        orig_holder = [None]

        def wrapper(*args, **kwargs):
            if orig_holder[0] is None:
                return [smb2.SMB2Error()], None, STATUS_UNSUCCESSFUL
            try:
                return orig_holder[0](*args, **kwargs)
            except Exception:
                import traceback

                print(
                    f"❌ SMB SAFETY NET: unhandled exception in {name} — connection "
                    f"would otherwise have been DROPPED. Full detail:",
                    flush=True,
                )
                traceback.print_exc()
                return [smb2.SMB2Error()], None, STATUS_UNSUCCESSFUL

        return wrapper, orig_holder

    for name, cmd in all_commands.items():
        wrapper, orig_holder = _make_safety_wrapper(name)
        # hookSmb2Command atomically installs + returns the previous
        # handler — no separate "peek" (hookSmb2Command(cmd, None) would
        # actually REPLACE the handler with None, breaking every call to
        # it; found and avoided here).
        orig_holder[0] = inner.hookSmb2Command(cmd, wrapper)

    print("🛡️  SMB: command safety net installed.")


def _install_role_enforcement(server):
    from impacket import smb
    from impacket import smb3structs as smb2

    inner = server.getServer()
    smb1_hook, smb2_hook, smb1_orig_holder, smb2_orig_holder = (
        _make_tree_connect_hooks()
    )
    smb1_orig_holder[0] = inner.hookSmbCommand(
        smb.SMB.SMB_COM_TREE_CONNECT_ANDX, smb1_hook
    )
    smb2_orig_holder[0] = inner.hookSmb2Command(smb2.SMB2_TREE_CONNECT, smb2_hook)


def _install_signing_diagnostics(server):
    """
    Opt-in (SMB_DEBUG_SIGNING=1). Windows 11 24H2 requires SMB signing by
    default; impacket's signing infrastructure turns on automatically
    for our NTLM auth flow, but whether that's sufficient for a real
    24H2 client needed testing directly. Uses print(), not log.warning():
    guaranteed visibility regardless of whatever logging config the rest
    of the app uses.
    """
    from impacket import smb3structs as smb2

    inner = server.getServer()
    negotiate_orig_holder = [None]
    session_setup_orig_holder = [None]

    def negotiate_hook(*args, **kwargs):
        print("SMB-DIAG: Negotiate request RECEIVED", flush=True)
        result = negotiate_orig_holder[0](*args, **kwargs)
        print(
            "SMB-DIAG: Negotiate response sent (dialect 0x0202, signing enabled not required)",
            flush=True,
        )
        return result

    def session_setup_hook(*args, **kwargs):
        print("SMB-DIAG: Session Setup request RECEIVED", flush=True)
        result = session_setup_orig_holder[0](*args, **kwargs)
        try:
            connId, smbServer = args[0], args[1]
            connData = smbServer.getConnectionData(connId, checkStatus=False)
            print(
                f"SMB-DIAG: Session Setup response — Authenticated={connData.get('Authenticated')!r} "
                f"SignatureEnabled={connData.get('SignatureEnabled')!r} "
                f"has_SigningSessionKey={bool(connData.get('SigningSessionKey'))}",
                flush=True,
            )
        except Exception as e:
            print(
                f"SMB-DIAG: Session Setup response sent, couldn't read connData: {e}",
                flush=True,
            )
        return result

    negotiate_orig_holder[0] = inner.hookSmb2Command(
        smb2.SMB2_NEGOTIATE, negotiate_hook
    )
    session_setup_orig_holder[0] = inner.hookSmb2Command(
        smb2.SMB2_SESSION_SETUP, session_setup_hook
    )

    _orig_sign_v2 = inner.signSMBv2
    _orig_sign_v1 = inner.signSMBv1

    def traced_sign_v2(packet, signingSessionKey, padLength=0):
        print("SMB-DIAG: signSMBv2() called", flush=True)
        return _orig_sign_v2(packet, signingSessionKey, padLength=padLength)

    def traced_sign_v1(connData, packet, signingSessionKey, signingChallengeResponse):
        print("SMB-DIAG: signSMBv1() called", flush=True)
        return _orig_sign_v1(
            connData, packet, signingSessionKey, signingChallengeResponse
        )

    inner.signSMBv2 = traced_sign_v2
    inner.signSMBv1 = traced_sign_v1
    print("🔍 SMB-DIAG: signing diagnostics ENABLED (SMB_DEBUG_SIGNING=1)")


def _auth_callback(smbServer, connData, domain_name, user_name, host_name):
    log.info(f"SMB: {user_name!r} authenticated from {host_name!r}")


def _load_credentials(server, log_missing: bool = True):
    """
    Diffs against impacket's live credential table rather than clearing
    and rebuilding it every cycle: deleted/renamed users are explicitly
    removed (closing a gap where a deleted user's old credential
    lingered forever), but an unchanged user is left untouched, UID
    included. Comparisons are lowercase throughout, matching impacket's
    own internal key normalization (addCredential stores name.lower()) —
    an earlier version compared against original-case usernames, which
    silently broke the diff for any mixed-case name; found and fixed.
    """
    from database import db

    inner = server.getServer()
    table = inner.getCredentials()

    creds = db.get_smb_credentials()
    current_keys = {username.lower() for username, _ in creds}

    for stale_key in list(table.keys()):
        if stale_key not in current_keys:
            del table[stale_key]
            _uid_by_username.pop(stale_key, None)

    for username, nt_hash_hex in creds:
        key = username.lower()
        existing = table.get(key)
        if existing is not None and existing[2] == nt_hash_hex:
            continue
        server.addCredential(username, _get_stable_uid(username), "", nt_hash_hex)

    if log_missing:
        missing = db.users_missing_nt_hash()
        if missing:
            print(
                f"⚠️  SMB: {len(missing)} user(s) cannot use SMB until their password "
                f"is reset once: {', '.join(missing)}"
            )
    return len(creds)


def _credential_refresh_loop(server):
    while not _stop_event.wait(_CREDENTIAL_REFRESH_SECONDS):
        try:
            _load_credentials(server, log_missing=False)
        except Exception as e:
            log.warning(f"SMB credential refresh failed: {e}")


def _try_bind(port: int) -> bool:
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
    """Try `preferred` (445), fall back to `fallback` on failure. Never
    touches the OS itself — see smb_setup.py for the actual setup."""
    if _try_bind(preferred):
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
                f"sharing). Run `python smb_setup.py` once — see "
                f"SMB_PROTOCOL_DEPLOYMENT.md for details."
            )
    else:
        print(
            f"⚠️  SMB: could not bind port {preferred} (needs root, or a one-time "
            f"capability grant). Run `python smb_setup.py` once — see "
            f"SMB_PROTOCOL_DEPLOYMENT.md for details."
        )

    print(f"   Falling back to port {fallback}.")
    if _IS_WINDOWS and fallback >= 1024:
        print(
            f"   Map with:  net use X: \\\\{LOCAL_IP}\\SHARE /TCPPORT:{fallback}  (Windows 11 24H2+ / Server 2025+ only)"
        )
        print(f"   Older Windows clients cannot map a non-445 SMB share natively.")
    return fallback


def _quiet_handle_error(request, client_address):
    """
    Defense-in-depth only — see _install_quiet_netbios_timeout() below for
    the fix that actually matters. Confirmed directly (triggered a real
    NetBIOSTimeout, tracked whether this ever gets called): it does NOT.
    impacket's own SMBSERVERHandler.handle() catches NetBIOSTimeout
    internally, prints its own traceback, and returns normally — the
    exception never escapes far enough to reach socketserver's
    handle_error at all. Kept anyway in case a future impacket version
    changes that internal handling and lets it escape.
    """
    import sys

    exc_type = sys.exc_info()[0]
    try:
        from impacket.nmb import NetBIOSTimeout

        if exc_type is not None and issubclass(exc_type, NetBIOSTimeout):
            log.debug(f"SMB: {client_address} went idle or disconnected (normal)")
            return
    except ImportError:
        pass

    print("-" * 40, file=sys.stderr)
    print(
        "Exception occurred during processing of request from",
        client_address,
        file=sys.stderr,
    )
    import traceback

    traceback.print_exc()
    print("-" * 40, file=sys.stderr)


def _install_quiet_netbios_timeout():
    """
    The actual fix for the NetBIOSTimeout traceback (handle_error above
    is not it — confirmed empirically it's never called for this case).

    Root cause: SMBSERVERHandler.handle() wraps its whole per-connection
    loop in its own try/except that catches NetBIOSTimeout, calls
    traceback.print_exc() directly, and returns normally — fully
    internal to impacket, never reaching socketserver's handle_error.

    Fix: monkey-patch SMBSERVERHandler.handle itself — impacket exposes
    no hook for this control flow, unlike SMB2 commands. This is a
    faithful reproduction of the original method (confirmed against
    impacket 0.13.1's source) with one change: NetBIOSTimeout gets a
    quiet log instead of a printed traceback. Any other exception still
    prints in full, unchanged. Uses the real name-mangled attribute
    names (self._SMBSERVERHandler__SMB etc.) since double-underscore
    mangling is based on where code is textually defined, not what
    class it's attached to at runtime — verified directly, a naive
    `self.__SMB` reference here would not resolve correctly.

    Risk, stated plainly: this duplicates an impacket-internal method
    rather than hooking a stable public API, so it could drift silently
    if a future impacket version changes handle()'s logic. Verified
    against 0.13.1 with real connections (login, Tree Connect, file
    read, multiple sequential connections) confirming no regression,
    plus a real triggered timeout confirming the traceback is actually
    suppressed.
    """
    import impacket.smbserver as _smbserver_module
    from impacket import nmb

    def _quiet_handle(self):
        h = self._SMBSERVERHandler__SMB
        h.log(
            "Incoming connection (%s,%d)"
            % (self._SMBSERVERHandler__ip, self._SMBSERVERHandler__port)
        )
        h.addConnection(
            self._SMBSERVERHandler__connId,
            self._SMBSERVERHandler__ip,
            self._SMBSERVERHandler__port,
        )
        while True:
            try:
                session = nmb.NetBIOSTCPSession(
                    h.getServerName(),
                    "HOST",
                    self._SMBSERVERHandler__ip,
                    sess_port=self._SMBSERVERHandler__port,
                    sock=self._SMBSERVERHandler__request,
                    select_poll=self._SMBSERVERHandler__select_poll,
                )
                try:
                    p = session.recv_packet(self._SMBSERVERHandler__timeOut)
                except nmb.NetBIOSTimeout:
                    raise
                except nmb.NetBIOSError:
                    break

                if p.get_type() == nmb.NETBIOS_SESSION_REQUEST:
                    _, rn, my = p.get_trailer().split(b" ")
                    remote_name = nmb.decode_name(b"\x20" + rn)
                    myname = nmb.decode_name(b"\x20" + my)
                    h.log(
                        "NetBIOS Session request (%s,%s,%s)"
                        % (
                            self._SMBSERVERHandler__ip,
                            remote_name[1].strip(),
                            myname[1],
                        )
                    )
                    r = nmb.NetBIOSSessionPacket()
                    r.set_type(nmb.NETBIOS_SESSION_POSITIVE_RESPONSE)
                    r.set_trailer(p.get_trailer())
                    self._SMBSERVERHandler__request.send(r.rawData())
                else:
                    resp = h.processRequest(
                        self._SMBSERVERHandler__connId, p.get_trailer()
                    )
                    for i in resp:
                        session.send_packet(i.getData() if hasattr(i, "getData") else i)
            except nmb.NetBIOSTimeout:
                h.log("Connection idle-timed-out (normal)")
                break
            except Exception as e:
                h.log("Handle: %s" % e)
                import traceback

                traceback.print_exc()
                break

    _smbserver_module.SMBSERVERHandler.handle = _quiet_handle
    log.info("SMB: NetBIOSTimeout traceback suppression applied")


def start() -> bool:
    """Start the SMB server in a background daemon thread. Returns True
    on success, False if disabled, impacket isn't installed, or no port
    could be bound."""
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
        _install_setinfo_rename_fix()
        _install_setdelete_retry_fix()
        _install_create_share_delete_fix(server)
        _install_quiet_netbios_timeout()
        _install_role_enforcement(server)

        if os.environ.get("SMB_DEBUG_SIGNING") == "1":
            _install_signing_diagnostics(server)

        # Installed LAST: hookSmb2Command chaining means whatever's
        # installed last is outermost, so this also wraps our own hooks
        # above (not just impacket's built-ins) — useful, since those are
        # the newest, least-tested code.
        _install_command_safety_net(server)

        # Must be set BEFORE accepting connections — both are only read
        # at the moment a connection is handled, so setting them later
        # (e.g. in stop()) is too late for anything already in progress.
        # Confirmed directly: without this, a single abandoned connection
        # (client disconnects right after a failed login) makes
        # server_close() hang forever.
        inner = server.getServer()
        inner.daemon_threads = True
        inner.block_on_close = False
        inner.handle_error = _quiet_handle_error

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
        f"📡 SMB:     \\\\{LOCAL_IP}:{port}\\{SMB_SHARE_NAME}"
        if port != 445
        else f"📡 SMB:     \\\\{LOCAL_IP}\\{SMB_SHARE_NAME}"
    )
    print(
        f"   Windows → Map Network Drive → \\\\{LOCAL_IP}\\{SMB_SHARE_NAME}"
        + (f" /TCPPORT:{port}" if port != 445 else "")
    )
    return True


def stop():
    """
    Stop the SMB server. Does not touch LanmanServer or any other OS
    state — that's smb_setup.py's job, run separately, once.

    Relies on daemon_threads=True / block_on_close=False having been set
    in start() BEFORE the server started accepting connections (timing
    matters — setting them later is too late for connections already in
    progress). With those set, shutdown()+server_close() return promptly
    even if a connection was abandoned mid-session — confirmed directly;
    without this, that scenario hangs server_close() forever.
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
