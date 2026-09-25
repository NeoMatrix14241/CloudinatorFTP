"""
sftp_server.py — SFTP server for CloudinatorFTP
------------------------------------------------
Runs a Paramiko-based SSH/SFTP server on SFTP_PORT (default 2222)
in a background daemon thread, exposing ROOT_DIR over SFTP.

Client usage:
  WinSCP      → Protocol: SFTP  Host: HOST  Port: 2222
  FileZilla   → sftp://HOST:2222
  macOS/Linux → sftp -P 2222 user@HOST
  sshfs       → sshfs -p 2222 user@HOST:/ /mnt/cloudinator
                (mount as a filesystem on Linux/macOS)

Roles (same as Flask):
  readwrite → full access: list, download, upload, delete, rename, mkdir …
  readonly  → list and download only; all mutations return SFTP_PERMISSION_DENIED

Authentication is password-based against the CloudinatorFTP database.
Public-key auth is not supported (would require storing keys per user).

Host key:
  Generated as RSA-2048 on first run, stored at db/sftp_host.rsa.
  Back this file up — clients will see a host-key-changed warning if it
  is regenerated.

Cipher & MAC hardening:
  CBC-mode, 3DES, and arcfour/RC4 ciphers, plus MD5-based and
  truncated-SHA1 MACs, are stripped from every connection's offered
  algorithm lists (see _harden_transport_ciphers) — paramiko offers them
  by default for legacy-client compatibility, but this server doesn't
  need them and they're what OpenVAS's "Weak Encryption Algorithm(s)
  Supported (SSH)" and "Weak MAC Algorithm(s) Supported (SSH)" checks flag.
"""

import errno
import os
import socket
import threading
import time
import logging
import logging_setup

# get_local_ip() lives in net_utils.py, not app.py (2026-09-25) — a
# small, side-effect-free module. See net_utils.py's docstring: this
# used to be `from app import get_local_ip`, which works fine wherever
# app.py gets fully imported anyway, but importing the lightweight
# function from the lightweight module is one less thing to reason
# about if that ever changes.
from net_utils import get_local_ip

LOCAL_IP = get_local_ip()

# Was logging.getLogger(__name__) — a plain stdlib logger with no handler
# ever attached, so it silently went nowhere (console or file). Now a
# child of logging_setup's shared "cloudinatorftp" logger, same fix
# already applied to protocol_manager.py's _pm_logger — see that file's
# comment for the full story. Also now used for AUDIT-level success
# logging below, not just the pre-existing PERMISSION_DENIED warnings.
log = logging_setup.get_logger("sftp")

# ── SFTP open-flags ────────────────────────────────────────────────────────
# BUGFIX (found while smoke-testing the audit-logging patch below, 2026-09-24):
# this used to define SSH_FXF_* protocol-level bit values (READ=0x01,
# WRITE=0x02, CREAT=0x08, TRUNC=0x10 — straight from the SFTP wire format)
# and test the `flags` argument against them. But paramiko's
# SFTPServerInterface.open() does NOT receive raw wire-protocol flags —
# paramiko's own SFTPServer._process() calls _convert_pflags() first,
# which translates them into Python's os.O_* flags (os.O_WRONLY=1,
# os.O_RDWR=2, os.O_CREAT=64, os.O_TRUNC=512, os.O_APPEND=1024) before
# ever calling into this file. The two bit layouts don't line up —
# critically, os.O_WRONLY (1) collides with the old _FXF_READ (0x01) —
# so a brand-new file opened for writing was being misread as a
# read-only open, the open() call then failed with FileNotFoundError on
# a file that doesn't exist yet, and the client saw a bare "No such
# file" on what should have been a normal upload. Confirmed live against
# a real paramiko client: new-file uploads failed 100% of the time
# before this fix. Existing-file overwrites were similarly broken (would
# open in read mode, then fail on the first write with
# io.UnsupportedOperation instead of succeeding).
#
# Fixed to test the actual os.O_* flags paramiko hands us. Not stored as
# hardcoded hex anymore since os.O_* values, while POSIX-stable, are
# technically platform-defined — os.O_CREAT etc. are looked up at import
# time instead so this stays correct if this ever runs somewhere the
# raw ints differ.


def _flags_to_mode(flags: int) -> str:
    """Convert the os.O_* flags paramiko passes into a Python open() mode."""
    is_rdwr = bool(flags & os.O_RDWR)
    is_wronly = bool(flags & os.O_WRONLY)
    is_read = is_rdwr or not (
        is_wronly or is_rdwr
    )  # O_RDONLY is 0 — the "none of the above" case
    is_write = is_wronly or is_rdwr
    is_append = bool(flags & os.O_APPEND)
    is_creat = bool(flags & os.O_CREAT)
    is_trunc = bool(flags & os.O_TRUNC)

    if is_append:
        return "a+b" if is_read else "ab"
    if is_write or is_creat:
        if is_trunc or is_creat:
            return "w+b" if is_read and is_rdwr else "wb"
        return "r+b"
    return "rb"


def _is_write_open(flags: int) -> bool:
    """True if these os.O_* flags represent any kind of write access."""
    return bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT))


# ── Path helper ───────────────────────────────────────────────────────────


def _make_realpath(root_dir: str):
    """
    Return a chroot function that maps SFTP absolute paths to real paths
    under root_dir, preventing path-traversal attacks.

    IMPORTANT (Windows bug fix): the previous implementation called
    os.path.join(root, some_path_starting_with_backslash). On Windows,
    ntpath.join("C:\\Server\\Files", "\\subfolder") returns "C:\\subfolder"
    — NOT "C:\\Server\\Files\\subfolder" — because a drive-less absolute
    path resets the join to the drive root. This silently broke every
    subdirectory lookup (they got clamped back to root instead of
    resolving correctly), even though the root itself happened to also
    resolve correctly by coincidence (the clamp caught that case too).

    Fix: split the SFTP path into individual segments and join them one
    at a time. A bare segment name (e.g. "subfolder") never starts with
    a separator, so it can never trigger ntpath's absolute-path-reset
    behavior, on any OS.
    """
    root = os.path.realpath(root_dir)

    def realpath(sftp_path: str) -> str:
        posix_path = sftp_path.replace("\\", "/")
        segments = [s for s in posix_path.split("/") if s not in ("", ".")]

        real = root
        for seg in segments:
            if seg == "..":
                parent = os.path.dirname(real)
                # Only ascend if doing so stays at or under root
                if parent == root or parent.startswith(root + os.sep):
                    real = parent
                # else: silently ignore an escape attempt
                continue
            real = os.path.join(real, seg)

        real = os.path.realpath(real)
        # Final safety clamp in case a symlink inside root points outside it
        if real != root and not real.startswith(root + os.sep):
            return root
        return real

    def to_sftp(real_path: str) -> str:
        try:
            rel = os.path.relpath(real_path, root)
        except ValueError:
            return "/"
        sftp = "/" + rel.replace(os.sep, "/")
        return "/" if sftp in ("/.", "") else sftp

    return realpath, to_sftp


# ── SFTP file handle ──────────────────────────────────────────────────────


# ── SFTP file handle ──────────────────────────────────────────────────────
# Use paramiko's built-in SFTPHandle with readfile/writefile attributes.
# paramiko's default read() does: self.readfile.seek(offset); self.readfile.read(length)
# paramiko's default write() does: self.writefile.seek(offset); self.writefile.write(data)
# We just supply a real file object and override stat()/close() only.


def _make_sftp_handle_class():
    import paramiko

    class _SFTPHandle(paramiko.SFTPHandle):
        """
        Thin wrapper around a real file object.
        paramiko.SFTPHandle.read/write use self.readfile/writefile directly,
        so no custom read/write needed — just set those attributes.
        """

        def __init__(self, fobj, flags=0):
            super().__init__(flags)
            self.readfile = fobj
            self.writefile = fobj

        def stat(self):
            try:
                return paramiko.SFTPAttributes.from_stat(
                    os.fstat(self.readfile.fileno())
                )
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)

        def close(self):
            try:
                self.readfile.close()
            except Exception:
                pass

    return _SFTPHandle


# ── SFTP server interface (file operations) ───────────────────────────────


class _CloudinatorSFTPInterface:
    """
    Implements paramiko.SFTPServerInterface, chrooted to ROOT_DIR.
    Receives the authenticated SSHServer instance so it can read the user's role.

    All paths received from SFTP clients are POSIX-absolute (start with /).
    _realpath() maps them to real filesystem paths safely.
    """

    def __init__(self, server, root_dir: str):
        import paramiko

        self._p = paramiko
        self._username = getattr(server, "username", "")
        self._role = getattr(server, "role", "readonly")
        # Set on the _SSHServer instance in _handle_connection() right
        # after construction — see that function for where this comes
        # from. Falls back to "?" defensively; should always be present
        # in practice since it's set before start_server() is called.
        self._client_ip = getattr(server, "client_addr", ("?", "?"))[0]
        self._realpath, self._to_sftp = _make_realpath(root_dir)

    # ── Audit logging (new) ─────────────────────────────────────────────
    # One-line success-path audit trail for every write operation below.
    # Previously this class only logged PERMISSION_DENIED cases — a
    # successful delete/rename/mkdir/upload produced zero log output,
    # meaning "who deleted this file" had no direct answer anywhere in
    # the logs. Same shape as the request_logger line in app.py
    # (user + action + path + ip), so both are greppable the same way.

    def _audit(self, action: str, path: str, extra: str = ""):
        log.info(
            "SFTP AUDIT: user=%r action=%s path=%r ip=%s%s",
            self._username,
            action,
            path,
            self._client_ip,
            f" {extra}" if extra else "",
        )

    # ── Read operations ───────────────────────────────────────────────────

    def list_folder(self, path: str):
        real = self._realpath(path)
        try:
            out = []
            with os.scandir(real) as it:
                for entry in it:
                    try:
                        st = entry.stat(follow_symlinks=False)
                        attr = self._p.SFTPAttributes.from_stat(st)
                        attr.filename = entry.name
                        out.append(attr)
                    except OSError:
                        continue
            return out
        except PermissionError as e:
            log.warning(
                f"SFTP list_folder PERMISSION_DENIED: requested={path!r} "
                f"resolved={real!r} user={self._username!r} role={self._role!r} os_error={e}"
            )
            return self._p.SFTP_PERMISSION_DENIED
        except FileNotFoundError:
            return self._p.SFTP_NO_SUCH_FILE
        except OSError as e:
            return self._p.SFTPServer.convert_errno(e.errno)

    def stat(self, path: str):
        real = self._realpath(path)
        try:
            return self._p.SFTPAttributes.from_stat(os.stat(real))
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EPERM):
                log.warning(
                    f"SFTP stat() PERMISSION_DENIED: requested={path!r} "
                    f"resolved={real!r} user={self._username!r} os_error={e}"
                )
            return self._p.SFTPServer.convert_errno(e.errno)

    def lstat(self, path: str):
        real = self._realpath(path)
        try:
            return self._p.SFTPAttributes.from_stat(os.lstat(real))
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EPERM):
                log.warning(
                    f"SFTP lstat() PERMISSION_DENIED: requested={path!r} "
                    f"resolved={real!r} user={self._username!r} os_error={e}"
                )
            return self._p.SFTPServer.convert_errno(e.errno)

    def open(self, path: str, flags: int, attr):
        real = self._realpath(path)
        is_write = _is_write_open(flags)

        if is_write and self._role != "readwrite":
            log.warning(
                f"SFTP open() PERMISSION_DENIED (readonly role): requested={path!r} "
                f"resolved={real!r} user={self._username!r} role={self._role!r} flags={flags}"
            )
            return self._p.SFTP_PERMISSION_DENIED

        mode = _flags_to_mode(flags)

        # For new-file creation, ensure the parent directory exists
        if (flags & os.O_CREAT) and not os.path.exists(real):
            parent = os.path.dirname(real)
            if not os.path.isdir(parent):
                return self._p.SFTP_NO_SUCH_FILE

        try:
            import builtins

            fobj = builtins.open(real, mode)
        except FileNotFoundError:
            return self._p.SFTP_NO_SUCH_FILE
        except PermissionError as e:
            log.warning(
                f"SFTP open() PERMISSION_DENIED (OS-level): requested={path!r} "
                f"resolved={real!r} user={self._username!r} role={self._role!r} os_error={e}"
            )
            return self._p.SFTP_PERMISSION_DENIED
        except IsADirectoryError:
            return self._p.SFTP_BAD_MESSAGE
        except OSError as e:
            return self._p.SFTPServer.convert_errno(e.errno)

        if is_write:
            self._audit("upload", path, extra=f"mode={mode}")

        # Return a proper paramiko SFTPHandle — the adapter will use it directly.
        return _make_sftp_handle_class()(fobj, flags)

    def canonicalize(self, path: str) -> str:
        """Called for SSH_FXP_REALPATH — return canonical SFTP path."""
        return self._to_sftp(self._realpath(path))

    # ── Write operations (role-gated) ─────────────────────────────────────

    def _check_write(self):
        if self._role != "readwrite":
            log.warning(
                f"SFTP write-op PERMISSION_DENIED (readonly role): "
                f"user={self._username!r} role={self._role!r}"
            )
            return self._p.SFTP_PERMISSION_DENIED
        return None

    def remove(self, path: str):
        err = self._check_write()
        if err:
            return err
        real = self._realpath(path)
        try:
            os.remove(real)
            self._audit("delete", path)
            return self._p.SFTP_OK
        except OSError as e:
            return self._p.SFTPServer.convert_errno(e.errno)

    def rename(self, oldpath: str, newpath: str):
        err = self._check_write()
        if err:
            return err
        try:
            os.rename(self._realpath(oldpath), self._realpath(newpath))
            self._audit("rename", oldpath, extra=f"-> {newpath!r}")
            return self._p.SFTP_OK
        except OSError as e:
            return self._p.SFTPServer.convert_errno(e.errno)

    def mkdir(self, path: str, attr):
        err = self._check_write()
        if err:
            return err
        real = self._realpath(path)
        try:
            os.mkdir(real)
            if attr and attr.st_mode is not None:
                os.chmod(real, attr.st_mode)
            self._audit("mkdir", path)
            return self._p.SFTP_OK
        except OSError as e:
            return self._p.SFTPServer.convert_errno(e.errno)

    def rmdir(self, path: str):
        err = self._check_write()
        if err:
            return err
        try:
            os.rmdir(self._realpath(path))
            self._audit("rmdir", path)
            return self._p.SFTP_OK
        except OSError as e:
            return self._p.SFTPServer.convert_errno(e.errno)

    def chattr(self, path: str, attr):
        err = self._check_write()
        if err:
            return err
        real = self._realpath(path)
        try:
            if attr.st_mode is not None:
                os.chmod(real, attr.st_mode)
            if attr.st_atime is not None and attr.st_mtime is not None:
                os.utime(real, (attr.st_atime, attr.st_mtime))
            return self._p.SFTP_OK
        except OSError as e:
            return self._p.SFTPServer.convert_errno(e.errno)

    # ── Unsupported operations ────────────────────────────────────────────

    def symlink(self, target_path: str, path: str):
        return self._p.SFTP_OP_UNSUPPORTED

    def readlink(self, path: str):
        return self._p.SFTP_OP_UNSUPPORTED


# ── Paramiko SFTPServerInterface adapter ─────────────────────────────────
# Paramiko's SFTPServer calls methods on a class that inherits from
# SFTPServerInterface.  We wrap our implementation above so we don't
# need to import paramiko at module load time.


def _make_sftp_interface_class(root_dir: str):
    import paramiko

    class _Adapter(paramiko.SFTPServerInterface):
        def __init__(self, server, *args, **kwargs):
            super().__init__(server, *args, **kwargs)
            self._impl = _CloudinatorSFTPInterface(server, root_dir)

        def list_folder(self, path):
            return self._impl.list_folder(path)

        def stat(self, path):
            return self._impl.stat(path)

        def lstat(self, path):
            return self._impl.lstat(path)

        def open(self, path, flags, attr):
            # _impl.open() now returns a proper paramiko.SFTPHandle subclass
            # (_SFTPHandle via _make_sftp_handle_class) or an SFTP error int.
            # No wrapping needed.
            return self._impl.open(path, flags, attr)

        def remove(self, path):
            return self._impl.remove(path)

        def rename(self, oldpath, newpath):
            return self._impl.rename(oldpath, newpath)

        def mkdir(self, path, attr):
            return self._impl.mkdir(path, attr)

        def rmdir(self, path):
            return self._impl.rmdir(path)

        def chattr(self, path, attr):
            return self._impl.chattr(path, attr)

        def canonicalize(self, path):
            return self._impl.canonicalize(path)

        def symlink(self, target_path, path):
            return self._impl.symlink(target_path, path)

        def readlink(self, path):
            return self._impl.readlink(path)

    return _Adapter


# ── SSH server — handles auth ─────────────────────────────────────────────


def _make_ssh_server_class():
    import paramiko

    class _SSHServer(paramiko.ServerInterface):
        """Handles SSH-layer authentication. SFTP operations are separate."""

        def __init__(self):
            self.username = ""
            self.role = "readonly"
            # Set by _handle_connection() right after construction, before
            # start_server() — lets both the login audit line below and
            # _CloudinatorSFTPInterface's per-file audit lines attribute
            # activity to a source IP, not just a username.
            self.client_addr = ("?", "?")

        def check_channel_request(self, kind, chanid):
            if kind == "session":
                return paramiko.OPEN_SUCCEEDED
            return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_auth_none(self, username):
            return paramiko.AUTH_FAILED

        def check_auth_password(self, username, password):
            from database import db

            ip = self.client_addr[0]
            if db.check_login(username, password):
                self.username = username
                self.role = db.get_role(username) or "readonly"
                db.update_last_login(username)
                log.info(
                    "SFTP AUDIT: user=%r action=login role=%r ip=%s",
                    username,
                    self.role,
                    ip,
                )
                return paramiko.AUTH_SUCCESSFUL
            # Previously silent — a failed SFTP login attempt produced no
            # log line at all, unlike the web login's rate-limiter path.
            log.warning("SFTP AUDIT: user=%r action=login_failed ip=%s", username, ip)
            return paramiko.AUTH_FAILED

        def check_auth_publickey(self, username, key):
            return paramiko.AUTH_FAILED

        def get_allowed_auths(self, username):
            return "password"

    return _SSHServer


# ── Host key management ───────────────────────────────────────────────────


def _get_host_key():
    """Load the RSA host key from db/, generating a new one if absent."""
    import paramiko
    from paths import get_db_dir

    key_path = os.path.join(get_db_dir(create=True), "sftp_host.rsa")
    if os.path.exists(key_path):
        try:
            return paramiko.RSAKey(filename=key_path)
        except Exception as e:
            log.warning(f"Could not load SFTP host key ({e}), regenerating…")

    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(key_path)
    print(f"🔑 SFTP: Generated RSA host key → {key_path}")
    print(
        "   ⚠️  Back up this file — regeneration invalidates all known-hosts entries."
    )
    return key


# ── Weak-algorithm hardening ───────────────────────────────────────────────
# paramiko's Transport advertises a broad default cipher/MAC list for backward
# compatibility, including CBC-mode/RC4 ciphers and MD5/truncated-SHA1 MACs
# this server has no need to offer. This is exactly what OpenVAS flags on
# SFTP_PORT (2222, real SSH — paramiko.Transport — not a false positive
# from another service):
#   - OID 1.3.6.1.4.1.25623.1.0.105611 "Weak Encryption Algorithm(s)
#     Supported (SSH)" — CBC-mode ciphers (padding/plaintext-recovery
#     attack), arcfour/RC4 (weak-key problems), "none" (no encryption)
#   - "Weak MAC Algorithm(s) Supported (SSH)" — hmac-md5/hmac-md5-96 (MD5
#     is cryptographically broken) and hmac-sha1-96 (a truncated-to-96-bit
#     tag weakens the forgery-resistance SHA1's own margin already relies on)
# None of these are required for any client this server targets (WinSCP,
# FileZilla, OpenSSH sftp/sshfs all support aes-ctr/gcm ciphers and
# hmac-sha2 MACs), so they're dropped from the offered list before the
# handshake rather than merely deprioritized.
_WEAK_SSH_CIPHERS = frozenset(
    {
        "3des-cbc",
        "aes128-cbc",
        "aes192-cbc",
        "aes256-cbc",
        "blowfish-cbc",
        "cast128-cbc",
        "arcfour",
        "arcfour128",
        "arcfour256",
        "none",
    }
)
_WEAK_SSH_MACS = frozenset(
    {
        "hmac-md5",
        "hmac-md5-96",
        "hmac-sha1-96",
        "hmac-sha1",  # full SHA1 isn't broken as a MAC yet, but every client
        # this server targets supports hmac-sha2-256/512 fine, so there's no
        # reason to keep offering it either — same "drop, don't deprioritize" call.
        "none",
    }
)
# Finite-field Diffie-Hellman ephemeral (DHE) KEX algorithms are dropped for
# the same reason: they let an unauthenticated client force the server into
# expensive modular-exponentiation work with almost no cost to itself (the
# D(HE)ater DoS — CVE-2002-20001, CVE-2022-40735, CVE-2024-41996). The
# elliptic-curve variants (curve25519-sha256@libssh.org, ecdh-sha2-nistp*)
# aren't vulnerable to this and every client this server targets supports
# them, so there's no compatibility reason to keep offering DHE either.
_WEAK_SSH_KEX = frozenset(
    {
        "diffie-hellman-group14-sha256",
        "diffie-hellman-group16-sha512",
        "diffie-hellman-group18-sha512",
        "diffie-hellman-group-exchange-sha256",
        "diffie-hellman-group-exchange-sha1",
        "diffie-hellman-group14-sha1",
        "diffie-hellman-group1-sha1",
    }
)


def _harden_transport_ciphers(transport):
    """Strip weak ciphers/MACs/KEX algorithms from a Transport's offered
    algorithm lists in-place. Must be called before transport.start_server();
    get_security_options() returns a live view backing the handshake, so
    mutating .ciphers/.digests/.kex here is enough — no further wiring needed."""
    opts = transport.get_security_options()
    hardened_ciphers = tuple(c for c in opts.ciphers if c not in _WEAK_SSH_CIPHERS)
    if hardened_ciphers:
        opts.ciphers = hardened_ciphers
    hardened_macs = tuple(m for m in opts.digests if m not in _WEAK_SSH_MACS)
    if hardened_macs:
        opts.digests = hardened_macs
    hardened_kex = tuple(k for k in opts.kex if k not in _WEAK_SSH_KEX)
    if hardened_kex:
        opts.kex = hardened_kex


# ── Per-connection handler ────────────────────────────────────────────────


def _handle_connection(conn, addr, host_key, sftp_interface_class, ssh_server_class):
    import paramiko

    transport = None
    try:
        transport = paramiko.Transport(conn)
        _harden_transport_ciphers(transport)
        transport.add_server_key(host_key)
        transport.set_subsystem_handler(
            "sftp", paramiko.SFTPServer, sftp_interface_class
        )
        server = ssh_server_class()
        # Must be set before start_server() — check_auth_password() reads
        # it during the handshake, and _CloudinatorSFTPInterface.__init__
        # reads it (via getattr on this same server instance) once the
        # SFTP subsystem activates after auth succeeds.
        server.client_addr = addr
        transport.start_server(server=server)

        # Send keepalive packets so idle sessions (e.g. a mobile client that's
        # authenticated but just sitting in its file browser with no active
        # transfer) aren't silently dropped by a carrier/Wi-Fi NAT's idle
        # timeout. This only affects the post-channel-open session below —
        # it has no bearing on the accept() wait right below it.
        transport.set_keepalive(30)

        # Accept the session channel (required for SFTP subsystem to activate).
        # NOTE: some mobile SFTP apps (e.g. Android clients) show "connected"
        # immediately after auth but don't actually open the SFTP channel
        # until the user navigates into the file browser or starts an
        # action. A short timeout here closes the transport before the user
        # gets a chance to do that, surfacing as a generic "connection
        # closed" error in the client. 120s gives real slack for that UI
        # delay while still bounding a stalled/dead connection.
        chan = transport.accept(120)
        if chan is None:
            return

        # Keep thread alive while client is connected
        while transport.is_active():
            time.sleep(0.5)

    except Exception as e:
        log.debug(f"SFTP session {addr}: {e}")
    finally:
        if transport:
            try:
                transport.close()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass


# ── Accept loop ───────────────────────────────────────────────────────────

_stop_event = threading.Event()
_accept_thread: threading.Thread | None = None


def _accept_loop(host_key, port: int, sftp_class, ssh_class, ready_event, bind_error):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
    try:
        sock.bind(("0.0.0.0", port))
        sock.listen(50)
        sock.settimeout(1.0)
    except OSError as e:
        print(f"❌ SFTP: cannot bind to port {port}: {e}")
        bind_error.append(e)
        ready_event.set()
        return

    # Bind succeeded — safe for start() to report success now.
    ready_event.set()

    print(f"🔒 SFTP:    sftp://{LOCAL_IP}:{port}/")
    print(f"   WinSCP  → Protocol: SFTP  Host: {LOCAL_IP}  Port: {port}")
    print(f"   CLI     → sftp -P {port} user@{LOCAL_IP}")
    print(f"   sshfs   → sshfs -p {port} user@{LOCAL_IP}:/ /mnt/cloudinator")

    while not _stop_event.is_set():
        try:
            conn, addr = sock.accept()
        except socket.timeout:
            continue
        except OSError:
            if not _stop_event.is_set():
                log.warning("SFTP accept socket error")
            break

        t = threading.Thread(
            target=_handle_connection,
            args=(conn, addr, host_key, sftp_class, ssh_class),
            name=f"sftp-{addr[0]}:{addr[1]}",
            daemon=True,
        )
        t.start()

    try:
        sock.close()
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────


def start(port: int = None) -> bool:
    """
    Start the SFTP server in a background daemon thread.
    Returns True on success, False if paramiko is not installed.
    """
    global _accept_thread, _stop_event

    try:
        from config import SFTP_ENABLED, SFTP_PORT
    except ImportError:
        SFTP_ENABLED, SFTP_PORT = True, 2222

    if not SFTP_ENABLED:
        return False

    port = port or SFTP_PORT

    try:
        import paramiko  # noqa — verify available
    except ImportError:
        print("⚠️  SFTP not started: 'paramiko' is not installed.")
        print("   Install it: pip install paramiko")
        return False

    try:
        from config import ROOT_DIR
    except ImportError:
        print("❌ SFTP: cannot import ROOT_DIR from config.py")
        return False

    try:
        host_key = _get_host_key()
    except Exception as e:
        print(f"❌ SFTP: host key error: {e}")
        return False

    sftp_class = _make_sftp_interface_class(ROOT_DIR)
    ssh_class = _make_ssh_server_class()

    _stop_event.clear()
    ready_event = threading.Event()
    bind_error: list = []
    _accept_thread = threading.Thread(
        target=_accept_loop,
        args=(host_key, port, sftp_class, ssh_class, ready_event, bind_error),
        name="sftp-accept",
        daemon=True,
    )
    _accept_thread.start()

    # Wait for the accept loop to actually bind (or fail to) before
    # reporting success — previously this returned True unconditionally
    # right after starting the thread, so a bind failure (e.g. port
    # still held by a not-yet-terminated previous instance) printed its
    # error on a background thread but was invisible to protocol_manager,
    # which logged "✅ started" anyway while the OLD process kept
    # answering on the port.
    if not ready_event.wait(timeout=5):
        print(f"❌ SFTP: accept loop did not start within 5s on port {port}")
        return False
    if bind_error:
        return False
    return True


def stop():
    """Signal the SFTP accept loop to stop."""
    _stop_event.set()
