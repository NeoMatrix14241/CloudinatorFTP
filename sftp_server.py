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
"""

import errno
import os
import socket
import threading
import time
import logging
from app import get_local_ip

LOCAL_IP = get_local_ip()

log = logging.getLogger(__name__)

# ── SFTP open-flags (SSH protocol constants) ──────────────────────────────
_FXF_READ = 0x00000001
_FXF_WRITE = 0x00000002
_FXF_APPEND = 0x00000004
_FXF_CREAT = 0x00000008
_FXF_TRUNC = 0x00000010
_FXF_EXCL = 0x00000020

_WRITE_FLAGS = _FXF_WRITE | _FXF_APPEND | _FXF_CREAT


def _flags_to_mode(flags: int) -> str:
    """Convert SFTP open flags to a Python binary open-mode string."""
    is_read = bool(flags & _FXF_READ)
    is_write = bool(flags & _FXF_WRITE)
    is_append = bool(flags & _FXF_APPEND)
    is_creat = bool(flags & _FXF_CREAT)
    is_trunc = bool(flags & _FXF_TRUNC)

    if is_append:
        return "a+b" if is_read else "ab"
    if is_write or is_creat:
        if is_trunc or is_creat:
            return "w+b" if is_read else "wb"
        return "r+b"
    return "rb"


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
        self._realpath, self._to_sftp = _make_realpath(root_dir)

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
        is_write = bool(flags & _WRITE_FLAGS)

        if is_write and self._role != "readwrite":
            log.warning(
                f"SFTP open() PERMISSION_DENIED (readonly role): requested={path!r} "
                f"resolved={real!r} user={self._username!r} role={self._role!r} flags={flags}"
            )
            return self._p.SFTP_PERMISSION_DENIED

        mode = _flags_to_mode(flags)

        # For new-file creation, ensure the parent directory exists
        if (flags & _FXF_CREAT) and not os.path.exists(real):
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
            return self._p.SFTP_OK
        except OSError as e:
            return self._p.SFTPServer.convert_errno(e.errno)

    def rename(self, oldpath: str, newpath: str):
        err = self._check_write()
        if err:
            return err
        try:
            os.rename(self._realpath(oldpath), self._realpath(newpath))
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
            return self._p.SFTP_OK
        except OSError as e:
            return self._p.SFTPServer.convert_errno(e.errno)

    def rmdir(self, path: str):
        err = self._check_write()
        if err:
            return err
        try:
            os.rmdir(self._realpath(path))
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

        def check_channel_request(self, kind, chanid):
            if kind == "session":
                return paramiko.OPEN_SUCCEEDED
            return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_auth_none(self, username):
            return paramiko.AUTH_FAILED

        def check_auth_password(self, username, password):
            from database import db

            if db.check_login(username, password):
                self.username = username
                self.role = db.get_role(username) or "readonly"
                db.update_last_login(username)
                return paramiko.AUTH_SUCCESSFUL
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


# ── Per-connection handler ────────────────────────────────────────────────


def _handle_connection(conn, addr, host_key, sftp_interface_class, ssh_server_class):
    import paramiko

    transport = None
    try:
        transport = paramiko.Transport(conn)
        transport.add_server_key(host_key)
        transport.set_subsystem_handler(
            "sftp", paramiko.SFTPServer, sftp_interface_class
        )
        server = ssh_server_class()
        transport.start_server(server=server)

        # Accept the session channel (required for SFTP subsystem to activate)
        chan = transport.accept(30)
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


def _accept_loop(host_key, port: int, sftp_class, ssh_class):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
    try:
        sock.bind(("0.0.0.0", port))
        sock.listen(50)
        sock.settimeout(1.0)
    except OSError as e:
        print(f"❌ SFTP: cannot bind to port {port}: {e}")
        return

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
    _accept_thread = threading.Thread(
        target=_accept_loop,
        args=(host_key, port, sftp_class, ssh_class),
        name="sftp-accept",
        daemon=True,
    )
    _accept_thread.start()
    return True


def stop():
    """Signal the SFTP accept loop to stop."""
    _stop_event.set()
