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
_uid_by_username: dict[str, int] = (
    {}
)  # stable across refreshes — see _load_credentials()


def _get_stable_uid(username: str) -> int:
    """
    Return the same UID for a given username across every refresh cycle,
    assigning a new one only the first time that username is ever seen.

    Keyed on the lowercased username, matching impacket's own internal
    storage (addCredential() stores keys as name.lower() — confirmed
    directly from source) — otherwise a mixed-case username would get a
    fresh entry here on every call, defeating the entire point.

    This exists defensively: the previous version reassigned a brand new
    UID to EVERY user on every single refresh cycle (every 30s by
    default), even when nothing about that user had changed. Direct
    source inspection confirms impacket's UID value is only ever
    consulted at the initial login/session-setup step, never afterward —
    so this almost certainly wasn't the cause of any mid-session
    disruption — but there's no reason to reassign it pointlessly either,
    and ruling it out completely removes one more variable from the
    investigation into reports of SMB connections dropping during active,
    long-running file transfers.
    """
    key = username.lower()
    if key not in _uid_by_username:
        _uid_by_username[key] = next(_uid_counter)
    return _uid_by_username[key]


# ── Tree Connect hook — the actual per-user permission enforcement ─────────


def _make_tree_connect_hooks():
    """
    Build wrapped versions of the SMB1 and SMB2 Tree Connect handlers that
    call the real impacket handler first, then override the connected
    share's effective read-only flag for THIS connection based on the
    authenticated user's role.

    Returns (smb1_hook, smb2_hook, smb1_orig_holder, smb2_orig_holder).
    The two holders are single-element lists — set holder[0] = <the real
    original handler> immediately after hooking, at the call site (see
    _install_role_enforcement()). This explicit holder pattern is used
    deliberately instead of the more common "stash the original in a
    mutable default argument, then overwrite it via __defaults__" trick:
    that trick silently breaks the moment a hook's signature uses *args
    with any keyword-only parameter after it (as an earlier draft of
    this exact code did) — __defaults__ only ever updates positional-
    or-keyword parameter defaults, never a keyword-only one, so the
    "original" would have stayed permanently None and every hooked
    command would have failed on every single call. Caught directly by
    testing before this shipped; a plain holder list avoids the whole
    footgun by not relying on function-default mutation at all.
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

    smb1_orig_holder = [None]
    smb2_orig_holder = [None]

    def smb1_tree_connect_hook(*args, **kwargs):
        # *args/**kwargs, not fixed positional params: confirmed directly
        # that at least one SMB2 command (SMB2_NEGOTIATE, in its legacy
        # SMB1-upgrade call path) is invoked with a different argument
        # count than its "normal" 3-arg form — a fixed-arity signature
        # elsewhere in this file previously broke on exactly that call.
        # Since Tree Connect's own call sites haven't been exhaustively
        # audited for similar surprises, this defensive pattern removes
        # the whole class of risk rather than patching one instance of it.
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
    Fix MS Office "Ctrl+S throws access denied" on Windows.

    THE EXACT BUG (confirmed directly from impacket's source at lines
    1703 and 3700 — there are two os.rename() call sites):

        os.rename(pathName, newPathName)

    MS Office saves via an atomic rename: it writes changes to a .tmp
    file while keeping the original .docx open (so it's safe to abort),
    then renames .tmp → .docx. On Windows, os.rename() fails with
    [WinError 32] "The process cannot access the file because it is being
    used by another process" (ERROR_SHARING_VIOLATION) when the
    DESTINATION file is already open by another process — and Word itself
    has the .docx open while saving.

    impacket catches *any* OSError from os.rename() and maps it to
    STATUS_ACCESS_DENIED, which Windows reports to the application as a
    permissions failure — even though the real cause is a Windows
    file-locking limitation, nothing to do with permissions at all.

    THE FIX: patch impacket.smbserver.os.rename, to a wrapper that falls
    back to os.replace() specifically and ONLY when os.rename() fails
    with winerror == 32. os.replace() calls MoveFileExW(MOVEFILE_REPLACE_
    EXISTING) on Windows, which handles this exact case correctly even
    when the destination is open. Covers both the SMB2 path
    (smb2SetInfo, line 3700) and the SMB1 path (smbComRename, line 1703)
    simultaneously, since both go through the same patched name.

    WHY ONLY winerror == 32, SPECIFICALLY: os.rename() on Windows can
    fail for at least two structurally different reasons — WinError 183
    (ERROR_ALREADY_EXISTS: the destination exists and Windows refuses to
    silently overwrite it) and WinError 32 (the lock case above). This
    wrapper catches ONLY the winerror==32 case. The 183 case — and
    therefore CloudinatorFTP's own web-UI rename endpoint in app.py,
    which independently checks os.path.exists() and returns 409 before
    ever calling os.rename() — is completely unaffected by this patch.

    ⚠️ REAL, HONEST SCOPE — READ THIS BEFORE ASSUMING IT'S FULLY ISOLATED:
    impacket.smbserver's "os" import is the exact same module singleton
    as the global "os" module (confirmed directly — same object id).
    Patching os.rename here changes os.rename for the ENTIRE Python
    process this server runs in, not just impacket's code — including,
    in principle, app.py's own os.rename() call for its rename endpoint.
    In practice this is a narrow risk, not a broad one: the wrapper is
    installed ONCE at startup as a stable, non-swapping object (so there
    is no race on the patch itself), and it only ever changes behavior
    in the specific case where the ORIGINAL os.rename() would have
    raised WinError 32 — which, per the analysis above, is a distinct
    failure mode from "destination already exists" and doesn't overlap
    with app.py's existing exists-check. The only theoretical residual
    risk is a narrow TOCTOU race in app.py (something else creates the
    destination file, AND has it open, in the tiny window between
    app.py's os.path.exists() check and its os.rename() call) — at which
    point this patch would silently replace instead of raising, versus
    app.py's own pre-existing (and separate) TOCTOU exposure either way.
    Judged this an acceptable, well-understood trade-off rather than
    something to hide.

    NOT A SANDBOX-TESTABLE FIX: reproducing [WinError 32] requires a
    real Windows machine with a file open by another process as the
    rename destination. The logic and mechanics are straightforward enough
    to audit by reading, but functional verification must happen on your
    actual server.
    """
    if platform.system() != "Windows":
        log.debug("SMB: smb2SetInfo rename fix not needed (non-Windows platform)")
        return

    import impacket.smbserver as _smbserver_module

    _original_rename = _smbserver_module.os.rename

    def _windows_safe_rename(src, dst):
        """
        Drop-in replacement for os.rename() that falls back to
        os.replace() ONLY when the failure is specifically WinError 32
        (destination locked by another process — the MS Office atomic-
        save case). Any other error, including the destination already
        existing (WinError 183), is re-raised exactly as os.rename()
        would have raised it — this wrapper changes nothing about that.
        """
        try:
            _original_rename(src, dst)
        except OSError as e:
            if getattr(e, "winerror", None) == 32:
                log.debug(
                    f"SMB: os.rename failed with WinError 32 (file in use), "
                    f"retrying with os.replace for {src!r} -> {dst!r}"
                )
                _smbserver_module.os.replace(src, dst)
            else:
                raise

    _smbserver_module.os.rename = _windows_safe_rename
    log.info(
        "SMB: Windows atomic-save fix applied (os.rename → os.replace for WinError 32)"
    )


def _install_setdelete_retry_fix():
    """
    Defensive companion to the rename fix above — same underlying Windows
    limitation (WinError 32 / ERROR_SHARING_VIOLATION), different syscall.

    os.remove() maps to DeleteFileW on Windows, which can ALSO fail with
    WinError 32 if the file is momentarily still held open by another
    process — e.g. an antivirus scanner mid-scan, or a lingering handle
    that hasn't been released yet. impacket's delete-on-close handling
    (smbserver.py, SMB2_CLOSE handler) catches any exception from
    os.remove() and maps it to STATUS_ACCESS_DENIED — same user-visible
    "permission" error as the rename case, different trigger.

    UNLIKE rename, there is no atomic "force delete even if open"
    Windows API — os.replace() has no equivalent for delete. The
    standard, well-established mitigation for this exact class of
    transient lock (used internally by tools like robocopy) is a short
    backoff-retry: the lock is very often released within tens to a few
    hundred milliseconds once whatever briefly held it finishes.

    HONESTY NOTE: unlike the rename fix (built directly from your exact
    traceback), this is a DEFENSIVE addition based on a structurally
    identical, plausible mechanism — not something confirmed from a
    traceback of yours yet. It's a safe, well-precedented thing to add
    regardless of whether it turns out to be the actual cause here.
    """
    if platform.system() != "Windows":
        return

    import impacket.smbserver as _smbserver_module
    import time as _time

    _original_remove = _smbserver_module.os.remove
    _RETRY_DELAYS = (0.1, 0.15, 0.2, 0.25)  # ~700ms total worst case

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
    log.info(
        "SMB: Windows delete-retry fix applied (backoff retry for WinError 32 on delete)"
    )


def _install_create_share_delete_fix(server):
    """
    Fix a SECOND, more fundamental cause of the same MS Office save
    error you already saw fixed once (WinError 32 during smb2SetInfo's
    rename) — this one showing up on the OTHER rename in Office's save
    sequence: renaming the ORIGINAL file to a backup temp name (e.g.
    'Tutorial.docx' -> '3672D6CB.tmp'), rather than the new-content temp
    file replacing the original.

    THE ROOT CAUSE — CONFIRMED AGAINST CPYTHON'S OWN BUG TRACKER, NOT
    GUESSED: Python's os.open() on Windows never requests the
    FILE_SHARE_DELETE sharing flag, and there is no way to request it
    through the standard os.open()/open() API — this is a genuine,
    still-open CPython limitation (bpo-15244, filed 2012), rooted in a
    limitation of the MSVC C runtime Python builds on. Practically:
    ANY file our server opens via plain os.open() — even a file it just
    briefly opened to serve a read, even from our own process — cannot
    be renamed or deleted by ANYONE (including our own server, for a
    completely separate operation) while that handle remains open,
    because Windows enforces sharing restrictions per-handle, and
    Python's handle was never granted permission to allow that.

    Office's save sequence needs to rename the ORIGINAL file (which our
    server may still have an open handle to, e.g. from serving Word's
    initial read) to a backup name — and that rename fails with the
    exact WinError 32 you're seeing, for exactly this reason.

    THE FIX: replace the os.open() call used specifically by impacket's
    own SMB2_CREATE handler with a Windows-native equivalent, built from
    the official recipe published directly on CPython's bug tracker for
    this exact issue (_winapi.CreateFile() + msvcrt.open_osfhandle(),
    requesting FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    explicitly — something the standard os.open() path has no way to
    do). Uses ONLY Python's own standard library on Windows (_winapi and
    msvcrt are both built into CPython's Windows distribution) — no new
    pip dependency required.

    ONE REAL GAP FOUND AND FIXED IN THE OFFICIAL RECIPE ITSELF: its
    create-disposition mapping table has no entry for "no creation
    flags at all" (flags == 0) — i.e. simply opening an EXISTING file
    with neither O_CREAT, O_TRUNC, nor O_EXCL set, which is actually the
    single most common case for a file server (e.g. opening an existing
    .docx just to read or edit it) — the recipe's own demo code always
    used Python's open(path, "w+"), which implies O_CREAT|O_TRUNC, so
    this common case was apparently never exercised by its author.
    Verified directly: without this fix, that case raises a bare
    KeyError. Added `0: OPEN_EXISTING` to the mapping to close this gap.

    WHY SCOPED AS A TEMPORARY SWAP, NOT A PERMANENT PATCH (unlike the
    rename/remove fixes above): os.open() is called constantly, by many
    unrelated parts of the whole process (database connections, config
    loading, anything else running alongside SMB) — far more pervasively
    than os.rename()/os.remove(). A permanent global replacement risks
    silently misbehaving for some flag combination used elsewhere in the
    codebase that hasn't been audited here. A temporary swap, installed
    only around the single synchronous os.open() call inside impacket's
    own CREATE handler and restored immediately after, keeps the blast
    radius to exactly the moment that one call happens — safe under
    Python's GIL, since no other thread can be executing Python bytecode
    (including a call to os.open()) during that exact window.

    NOT A SANDBOX-TESTABLE FIX: _winapi and msvcrt are Windows-only
    standard library modules with no Linux equivalent — this cannot be
    exercised end-to-end outside a real Windows machine. The flag-
    translation logic itself (which os.O_* combination maps to which
    Win32 access/share/create-disposition flags) has been verified
    directly against every real combination impacket's smb2Create can
    produce (confirmed by reading its source), with correct results
    including the gap fix above — but the actual CreateFile()/
    open_osfhandle() calls themselves are unverified until run on your
    server.
    """
    if platform.system() != "Windows":
        log.debug("SMB: FILE_SHARE_DELETE create fix not needed (non-Windows platform)")
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
        0: OPEN_EXISTING,  # the gap fix — see docstring above
        os.O_EXCL: OPEN_EXISTING,
        os.O_CREAT: OPEN_ALWAYS,
        os.O_CREAT | os.O_EXCL: CREATE_NEW,
        os.O_CREAT | os.O_TRUNC | os.O_EXCL: CREATE_NEW,
        os.O_TRUNC: TRUNCATE_EXISTING,
        os.O_TRUNC | os.O_EXCL: TRUNCATE_EXISTING,
        os.O_CREAT | os.O_TRUNC: CREATE_ALWAYS,
    }

    def _share_delete_open(path, flags, mode=0o777):
        """
        Windows-native open() granting FILE_SHARE_READ | FILE_SHARE_WRITE
        | FILE_SHARE_DELETE, so this file can be renamed or deleted by
        anyone (including this same server, for a different operation)
        while still open — the thing plain os.open() can never do on
        Windows. Adapted from the official CPython bug-tracker recipe
        for bpo-15244, with the create-disposition gap fixed (see
        _install_create_share_delete_fix's docstring).
        """
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
        return msvcrt.open_osfhandle(handle, flags)

    inner = server.getServer()
    create_orig_holder = [None]

    def create_hook(*args, **kwargs):
        # Temporary swap, restored immediately after — see the "WHY
        # SCOPED AS A TEMPORARY SWAP" section of this function's
        # docstring for why this is deliberately NOT a permanent patch
        # the way the rename/remove fixes are.
        real_open = _smbserver_module.os.open
        _smbserver_module.os.open = _share_delete_open
        try:
            return create_orig_holder[0](*args, **kwargs)
        finally:
            _smbserver_module.os.open = real_open

    create_orig_holder[0] = inner.hookSmb2Command(smb2.SMB2_CREATE, create_hook)
    log.info("SMB: FILE_SHARE_DELETE create fix applied (Windows file-open sharing)")


def _install_command_safety_net(server):
    """
    THE KEY STRUCTURAL FINDING behind "network disconnect" as a symptom
    DISTINCT from "permission error": impacket's top-level SMB2 dispatch
    loop (processRequest, in smbserver.py) wraps the ENTIRE per-command
    call in a try/except that LOGS and then RE-RAISES:

        except Exception as e:
            self.log('processRequest (0x%x,%s)' % (packet['Command'], e), ...)
            raise

    Individual command handlers (smb2Create, smb2SetInfo, etc.) each have
    their OWN internal try/except around specific OS calls — which is
    where the "permission error" responses come from (an OSError gets
    caught and mapped to STATUS_ACCESS_DENIED). But if a DIFFERENT,
    unanticipated exception occurs — one that isn't the specific type a
    given handler's internal try/except was written to catch — it
    escapes all the way up through processRequest's outer handler, gets
    re-raised, and (per direct reading of the surrounding handle() loop)
    kills that connection's thread entirely. From the client's side,
    that's not an error message — it's the connection just dropping,
    which matches "network disconnect" as its own distinct symptom.

    THE FIX: wrap every registered SMB2 command with a safety net that
    catches ANY exception the command's own internal handling didn't,
    logs it in full (command name + exception type + message + full
    traceback, always-on, not gated behind an env var — these should be
    rare and are worth always knowing about), and returns a graceful
    STATUS_UNSUCCESSFUL response instead of letting it propagate and
    kill the connection. This doesn't fix whatever the underlying cause
    turns out to be — it turns "connection silently dies" into "client
    gets a clean error response, connection survives, and the exact
    cause is now visible in the log" — which is a real improvement
    either way, and gives us hard evidence instead of more speculation
    for whatever's actually happening with Office specifically.
    """
    from impacket import smb3structs as smb2
    from impacket.nt_errors import STATUS_UNSUCCESSFUL

    inner = server.getServer()

    # The full, authoritative list of SMB2 commands, from smb3structs.py.
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
            # *args/**kwargs, not fixed positional params: confirmed
            # directly that SMB2_NEGOTIATE's legacy SMB1-upgrade call
            # path invokes its handler with FOUR positional arguments
            # (connId, self, packet, True), not the usual three — a
            # fixed 3-arg signature here silently broke on exactly that
            # call (the 4th argument landed in what used to be an
            # "_orig" default-arg slot). Caught directly by testing
            # before this shipped.
            if orig_holder[0] is None:
                # Nothing was registered for this command — behave exactly
                # as impacket's own default() handler does.
                return [smb2.SMB2Error()], None, STATUS_UNSUCCESSFUL
            try:
                return orig_holder[0](*args, **kwargs)
            except Exception as e:
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
        # hookSmb2Command atomically installs our wrapper AND returns
        # whatever was registered before — the same safe, already-proven
        # pattern used for every other hook in this file. No separate
        # "peek" step, because there's no safe way to peek without
        # mutating — a design mistake caught and corrected here before
        # it shipped: an earlier draft called hookSmb2Command(cmd, None)
        # to "check" the existing handler first, which actually REPLACES
        # it with None immediately (confirmed by reading hookSmb2Command's
        # source — it unconditionally writes on every call) — that would
        # have broken every SMB2 command in the table the instant this
        # function ran. The holder list (rather than a mutable default
        # argument patched via __defaults__) is used deliberately too —
        # see _make_tree_connect_hooks()'s docstring for why that trick
        # is itself a footgun once *args/**kwargs is involved.
        orig_holder[0] = inner.hookSmb2Command(cmd, wrapper)

    print(
        "🛡️  SMB: command safety net installed — unhandled exceptions will no "
        "longer silently drop the connection, and will be logged in full."
    )


def _install_role_enforcement(server):
    """Register the Tree Connect hooks on the live impacket server instance."""
    from impacket import smb
    from impacket import smb3structs as smb2

    inner = server.getServer()  # the underlying SMBSERVER instance (public accessor)
    smb1_hook, smb2_hook, smb1_orig_holder, smb2_orig_holder = (
        _make_tree_connect_hooks()
    )

    # smbComTreeConnectAndX is the SMB1 dispatch key; SMB2_TREE_CONNECT for SMB2.
    smb1_orig_holder[0] = inner.hookSmbCommand(
        smb.SMB.SMB_COM_TREE_CONNECT_ANDX, smb1_hook
    )
    smb2_orig_holder[0] = inner.hookSmb2Command(smb2.SMB2_TREE_CONNECT, smb2_hook)


# ── Diagnostic logging — Windows 11 24H2 signing investigation ─────────────
# Opt-in only (set SMB_DEBUG_SIGNING=1 before starting the server). Traces
# exactly how far a connection gets before stalling: does Windows 11 even
# send a Negotiate request? Does it proceed to Session Setup? Does
# SignatureEnabled/SigningSessionKey actually get populated, and does
# impacket's own signSMBv2/signSMBv1 (already present in the library, not
# code we wrote — see module docstring) actually fire on the response?
#
# This exists because Windows 11 24H2 requires SMB signing by default
# (confirmed via Microsoft's own documentation), and impacket's
# SimpleSMBServer DOES contain working signing infrastructure that turns
# itself on automatically for our addCredential()-based NTLM auth flow —
# but whether that's sufficient for a real 24H2 client to accept the
# connection cannot be determined without testing against one directly.
# This logging exists to find that out, not to fix anything by itself.


def _install_signing_diagnostics(server):
    """
    NOTE: uses print(flush=True) rather than the module's log.warning()
    throughout this function, deliberately. These messages exist for one
    purpose — guaranteed visibility during a live test — and log.warning()
    depends on whatever logging configuration the rest of the application
    sets up elsewhere, which hasn't been verified here. print() goes
    straight to stdout regardless of that, so there's no risk of a real
    event firing silently and looking like it never happened.
    """
    from impacket import smb3structs as smb2

    inner = server.getServer()

    negotiate_orig_holder = [None]
    session_setup_orig_holder = [None]

    def negotiate_hook(*args, **kwargs):
        # *args/**kwargs, not fixed positional params: confirmed directly
        # that SMB2_NEGOTIATE's legacy SMB1-upgrade call path invokes its
        # handler with FOUR positional arguments (connId, self, packet,
        # True), not the usual three. Since this hook is registered
        # directly against SMB2_NEGOTIATE, a fixed 3-arg signature here
        # would break on every single connection's initial handshake via
        # that path — caught directly by testing before this shipped.
        print(
            "SMB-DIAG: Negotiate request RECEIVED — client is attempting to connect",
            flush=True,
        )
        result = negotiate_orig_holder[0](*args, **kwargs)
        # NOTE: the negotiated dialect is NOT stored in connData by impacket
        # (confirmed by reading smb2Negotiate's source directly) — it only
        # ever offers SMB2_DIALECT_002 (0x0202, the oldest SMB2 dialect),
        # hardcoded, so there's nothing variable to read back here.
        print(
            "SMB-DIAG: Negotiate response sent (dialect offered: 0x0202 / SMB 2.0.2, "
            "SecurityMode: signing-enabled, not required)",
            flush=True,
        )
        return result

    def session_setup_hook(*args, **kwargs):
        print(
            "SMB-DIAG: Session Setup request RECEIVED (NTLM negotiate or authenticate leg)",
            flush=True,
        )
        result = session_setup_orig_holder[0](*args, **kwargs)
        try:
            connId, smbServer = args[0], args[1]
            connData = smbServer.getConnectionData(connId, checkStatus=False)
            print(
                f"SMB-DIAG: Session Setup response sent — "
                f"Authenticated={connData.get('Authenticated')!r} "
                f"SignatureEnabled={connData.get('SignatureEnabled')!r} "
                f"has_SigningSessionKey={bool(connData.get('SigningSessionKey'))}",
                flush=True,
            )
        except Exception as e:
            print(
                f"SMB-DIAG: Session Setup response sent, but couldn't read back connData: {e}",
                flush=True,
            )
        return result

    negotiate_orig_holder[0] = inner.hookSmb2Command(
        smb2.SMB2_NEGOTIATE, negotiate_hook
    )
    session_setup_orig_holder[0] = inner.hookSmb2Command(
        smb2.SMB2_SESSION_SETUP, session_setup_hook
    )

    # Also wrap the actual signing functions so we can see directly whether
    # they fire at all — this is the most direct possible confirmation,
    # short of a packet capture, of whether impacket's existing signing
    # code path is being exercised for a given connection.
    _orig_sign_v2 = inner.signSMBv2
    _orig_sign_v1 = inner.signSMBv1

    def traced_sign_v2(packet, signingSessionKey, padLength=0):
        print(
            "SMB-DIAG: signSMBv2() called — server IS signing an outgoing SMB2 response",
            flush=True,
        )
        return _orig_sign_v2(packet, signingSessionKey, padLength=padLength)

    def traced_sign_v1(connData, packet, signingSessionKey, signingChallengeResponse):
        print(
            "SMB-DIAG: signSMBv1() called — server IS signing an outgoing SMB1 response",
            flush=True,
        )
        return _orig_sign_v1(
            connData, packet, signingSessionKey, signingChallengeResponse
        )

    inner.signSMBv2 = traced_sign_v2
    inner.signSMBv1 = traced_sign_v1

    print("🔍 SMB-DIAG: signing diagnostics ENABLED (SMB_DEBUG_SIGNING=1)")
    print("   Watch the console while connecting from the Windows 11 client.")
    print("   See SMB_PROTOCOL_DEPLOYMENT.md → 'Diagnosing the Windows 11")
    print("   signing issue' for how to read the output.")


# ── Auth callback — logging only; the real role check happens above ────────


def _auth_callback(smbServer, connData, domain_name, user_name, host_name):
    log.info(f"SMB: {user_name!r} authenticated from {host_name!r}")


# ── Credential loading ──────────────────────────────────────────────────────


def _load_credentials(server, log_missing: bool = True):
    """
    (Re)load all known NT-hash credentials from the database into impacket.

    Diffs against the live table rather than clearing-and-rebuilding it
    wholesale every cycle: removed/renamed users are explicitly deleted
    (closing the original gap where a deleted user's old credential
    lingered forever — confirmed directly: deleting a user and reloading
    without ever clearing first still let them log in with the old
    password), but a user whose credential hasn't changed since the last
    cycle is left completely untouched, including their UID (see
    _get_stable_uid). On the very first call (table empty), this is
    equivalent to a full load.

    All comparisons are done on the LOWERCASED username, matching exactly
    how impacket stores its own keys internally (addCredential() stores
    name.lower() — confirmed directly from source). Comparing against the
    database's original-case usernames without lowercasing first was
    caught and fixed here: it silently broke the diff for any mixed-case
    username, causing it to be deleted and immediately re-added on every
    single cycle instead of being left untouched as intended — verified
    directly against the real library before this fix went in.
    """
    from database import db

    inner = server.getServer()
    table = inner.getCredentials()  # live dict, by reference — confirmed via source

    creds = db.get_smb_credentials()
    current_keys = {username.lower() for username, _ in creds}

    # Remove anyone no longer in the database (deleted, or username changed)
    for stale_key in list(table.keys()):
        if stale_key not in current_keys:
            del table[stale_key]
            _uid_by_username.pop(stale_key, None)

    # Add new users / update anyone whose password (NT hash) actually changed
    for username, nt_hash_hex in creds:
        key = username.lower()
        existing = table.get(key)
        if existing is not None and existing[2] == nt_hash_hex:
            continue  # unchanged — skip entirely, don't touch their UID either
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


def _quiet_handle_error(request, client_address):
    """
    Override socketserver's default handle_error (which prints a full
    traceback to stderr for ANY exception raised inside a connection's
    handle() loop) so that NetBIOSTimeout — impacket's normal, expected
    result when a client goes idle for 5 minutes (its hardcoded timeout)
    or disconnects abruptly — gets a quiet one-line log instead of a
    scary traceback. Confirmed this fires in completely ordinary usage:
    anyone who maps the drive and leaves the window open hits this every
    5 minutes by design, not as a result of anything going wrong.

    Anything else still gets the normal, full traceback — silencing
    handle_error entirely would hide genuine bugs along with the noise.
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
        _install_setinfo_rename_fix()
        _install_setdelete_retry_fix()
        _install_create_share_delete_fix(server)
        _install_role_enforcement(server)

        if os.environ.get("SMB_DEBUG_SIGNING") == "1":
            _install_signing_diagnostics(server)

        # Installed LAST, deliberately: hookSmb2Command's chaining means
        # whatever is installed last becomes the OUTERMOST layer. Doing
        # this last means the safety net also wraps our OWN hooks above
        # (role enforcement, signing diagnostics, the CREATE share-delete
        # fix) — not just impacket's built-in handlers — which matters,
        # since those are exactly the kind of newly-written code most
        # likely to have a bug we haven't found yet.
        _install_command_safety_net(server)

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
