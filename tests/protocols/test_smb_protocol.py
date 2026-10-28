"""
SMB (smb_server.py, impacket SimpleSMBServer) against the REAL server code, started from a scratch
copy of the project on the FALLBACK port (the preferred port is held by the test, the way port 445
is taken by Windows' own file sharing) and driven with impacket's own SMB client.

Checked: the server falls back to SMB_FALLBACK_PORT when the preferred port is taken and uses the
preferred port when it is free; bad logins are refused (wrong password, unknown user, empty
password) and so are GUEST and ANONYMOUS sessions (CLAUDE.md 5.31: impacket let an empty user name
list and download the whole share); an account created, given a new password or deleted is
followed by the credential table within the refresh interval (the launcher shortens it from 30 s
to 1 s); only the one share is offered; a readwrite account does the whole file cycle on disk
(also a multi-chunk file); a readonly account can list and read but every change is refused and
changes nothing; the role is read live (CLAUDE.md 5.31): a demoted account loses write access on a
tree and a file handle that were already OPEN, a promoted one gains it, a deleted one can no longer
write; nothing can leave the storage root; the write audit lines are logged.

Not covered: SMB1 (impacket's SMB1 path rejected every login from the test client), signing and
encryption, Kerberos, Windows clients, locking, very large transfers, port 445 itself.
"""

import hashlib
import io
import os
import socket
import time
import uuid
from contextlib import suppress

import pytest

pytestmark = pytest.mark.protocol

impacket_smbconnection = pytest.importorskip("impacket.smbconnection")
SMBConnection = impacket_smbconnection.SMBConnection
SessionError = impacket_smbconnection.SessionError

RW, RO = "qa_writer", "qa_reader"
SHARE = "SharedFolder"

LOGON_FAILURE = 0xC000006D
ACCESS_DENIED = 0xC0000022

SMB_LAUNCHER = """
import smb_server
smb_server._CREDENTIAL_REFRESH_SECONDS = 1   # production: 30 s; account changes must show quickly
assert smb_server.start(), "smb_server.start() returned False"
print("READY", flush=True)
while True:
    time.sleep(1)
"""


def wait_for_port(port, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"nothing is listening on port {port}")


def wait_until(check, timeout=15, step=0.3):
    """Poll `check` until it returns True (the credential table refreshes about every second)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(step)
    return False


def occupy_a_port():
    """A listening socket nobody else can bind: the 'port 445 is taken' situation."""
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(
        socket, "SO_EXCLUSIVEADDRUSE"
    ):  # Windows: SO_REUSEADDR would let a bind through
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(5)
    return holder


class SmbEnv:
    def __init__(self, port, lab, users, process):
        self.port, self.users, self.process = port, users, process
        self.storage = lab / "data" / "storage"
        self.data = lab / "data"
        self._open = []

    def connect(self, user, password=None):
        pw = password if password is not None else self.users[user][0]
        conn = SMBConnection("127.0.0.1", "127.0.0.1", sess_port=self.port, timeout=30)
        self._open.append(conn)
        conn.login(user, pw)
        return conn

    def audit_lines(self):
        return [line for line in self.process.lines if "SMB AUDIT" in line]

    def close_all(self):
        for conn in self._open:
            with suppress(Exception):  # best-effort cleanup
                conn.close()
        self._open.clear()


@pytest.fixture(scope="module")
def smb(launch, protocol_lab, scratch_tools):
    taken, fallback = occupy_a_port(), scratch_tools.free_port()
    process = launch(
        SMB_LAUNCHER,
        config={
            "SMB_ENABLED": True,
            "SMB_PORT": taken.getsockname()[1],
            "SMB_FALLBACK_PORT": fallback,
            "SMB_SHARE_NAME": SHARE,
        },
    )
    wait_for_port(fallback)
    env = SmbEnv(fallback, protocol_lab, dict(scratch_tools.test_users), process)
    env.taken_port = taken.getsockname()[1]
    yield env
    env.close_all()
    taken.close()


def unique(prefix="f", ext=".txt"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"


def put(conn, name, data=b"payload"):
    conn.putFile(SHARE, name, io.BytesIO(data).read)


def get(conn, name):
    buf = io.BytesIO()
    conn.getFile(SHARE, name, buf.write)
    return buf.getvalue()


def names(conn, pattern="*"):
    return [f.get_longname() for f in conn.listPath(SHARE, pattern)]


def status_of(error):
    return error.value.getErrorCode()


def _new_account(scratch_tools, protocol_lab, role):
    name = f"qa_{uuid.uuid4().hex[:8]}"
    password = "Qa-Live-Pass-1!"
    scratch_tools.run_in_scratch(
        protocol_lab,
        "assert db.add_user(sys.argv[1], sys.argv[2], sys.argv[3])",
        name,
        password,
        role,
    )
    return name, password


def _set_role(scratch_tools, protocol_lab, name, role):
    scratch_tools.run_in_scratch(
        protocol_lab, "assert db.update_role(sys.argv[1], sys.argv[2])", name, role
    )


def _can_log_in(smb, name, password):
    try:
        smb.connect(name, password)
        return True
    except SessionError:
        return False


def _account_ready(smb, scratch_tools, protocol_lab, role):
    """A new account, once the credential refresh has loaded it."""
    name, password = _new_account(scratch_tools, protocol_lab, role)
    assert wait_until(lambda: _can_log_in(smb, name, password)), "account never loaded"
    return name, password


# ---------------------------------------------------------------------------- ports
def test_the_server_falls_back_when_the_preferred_port_is_taken(smb):
    assert smb.port != smb.taken_port
    assert any(f"Falling back to port {smb.port}" in line for line in smb.process.lines)
    assert smb.connect(RW) is not None


def test_the_preferred_port_is_used_when_it_is_free(
    launch, protocol_lab, scratch_tools
):
    preferred, fallback = scratch_tools.free_port(), scratch_tools.free_port()
    process = launch(
        SMB_LAUNCHER,
        config={
            "SMB_ENABLED": True,
            "SMB_PORT": preferred,
            "SMB_FALLBACK_PORT": fallback,
            "SMB_SHARE_NAME": SHARE,
        },
    )
    try:
        wait_for_port(preferred)
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", fallback), timeout=2).close()
        conn = SMBConnection("127.0.0.1", "127.0.0.1", sess_port=preferred, timeout=30)
        conn.login(RW, scratch_tools.test_users[RW][0])
        conn.close()
    finally:
        process.stop()


# ---------------------------------------------------------------------------- authentication
def test_a_wrong_password_is_refused(smb):
    with pytest.raises(SessionError) as err:
        smb.connect(RW, "definitely-not-the-password")
    assert status_of(err) == LOGON_FAILURE


def test_an_unknown_user_is_refused(smb):
    with pytest.raises(SessionError) as err:
        smb.connect(f"nobody_{uuid.uuid4().hex[:6]}", "whatever")
    assert status_of(err) == LOGON_FAILURE


def test_an_empty_password_is_refused(smb):
    with pytest.raises(SessionError):
        smb.connect(RW, "")


def test_an_anonymous_login_is_refused_and_cannot_read_the_share(smb):
    (smb.storage / "private_listing.txt").write_bytes(b"PRIVATE DATA")
    anonymous = SMBConnection("127.0.0.1", "127.0.0.1", sess_port=smb.port, timeout=30)
    with pytest.raises(SessionError) as err:
        anonymous.login("", "")
    assert status_of(err) == LOGON_FAILURE
    with pytest.raises(Exception):
        anonymous.listShares()  # no session: nothing is served


def test_the_guest_account_does_not_get_in_either(smb):
    for name in ("guest", "Guest", "anonymous"):
        with pytest.raises(SessionError):
            smb.connect(name, "")


def test_a_new_account_works_after_the_credential_refresh(
    smb, scratch_tools, protocol_lab
):
    name, password = _account_ready(smb, scratch_tools, protocol_lab, "readwrite")
    put(smb.connect(name, password), unique("new_account"))


def test_a_reset_password_replaces_the_old_one(smb, scratch_tools, protocol_lab):
    name, password = _account_ready(smb, scratch_tools, protocol_lab, "readwrite")
    scratch_tools.run_in_scratch(
        protocol_lab,
        "assert db.update_password(sys.argv[1], sys.argv[2])",
        name,
        "Another-Pass-2!",
    )
    assert wait_until(lambda: _can_log_in(smb, name, "Another-Pass-2!"))
    assert not _can_log_in(smb, name, password)


def test_a_deleted_account_can_no_longer_log_in(smb, scratch_tools, protocol_lab):
    name, password = _account_ready(smb, scratch_tools, protocol_lab, "readwrite")
    scratch_tools.run_in_scratch(
        protocol_lab, "assert db.delete_user(sys.argv[1])", name
    )
    assert wait_until(lambda: not _can_log_in(smb, name, password))


# ---------------------------------------------------------------------------- the share
def test_only_the_configured_share_is_offered(smb):
    shares = {s["shi1_netname"][:-1].upper() for s in smb.connect(RW).listShares()}
    assert shares <= {SHARE.upper(), "IPC$"}
    assert SHARE.upper() in shares


def test_a_share_that_does_not_exist_cannot_be_connected(smb):
    conn = smb.connect(RW)
    for share in ("NoSuchShare", "C$", "ADMIN$"):
        with pytest.raises(SessionError):
            conn.connectTree(share)


# ---------------------------------------------------------------------------- readwrite account
def test_a_readwrite_account_can_do_the_whole_file_cycle(smb):
    conn = smb.connect(RW)
    name, folder, renamed = unique(), unique("dir", ""), unique("renamed")
    data = bytes(range(256)) * 20
    put(conn, name, data)
    assert (smb.storage / name).read_bytes() == data
    assert name in names(conn)
    assert get(conn, name) == data
    conn.rename(SHARE, name, renamed)
    assert not (smb.storage / name).exists() and (smb.storage / renamed).exists()
    conn.createDirectory(SHARE, folder)
    assert (smb.storage / folder).is_dir()
    put(conn, f"{folder}\\inner.txt", b"inner")
    assert get(conn, f"{folder}\\inner.txt") == b"inner"
    conn.deleteFile(SHARE, f"{folder}\\inner.txt")
    conn.deleteDirectory(SHARE, folder)
    conn.deleteFile(SHARE, renamed)
    assert not (smb.storage / folder).exists() and not (smb.storage / renamed).exists()


def test_an_existing_file_can_be_overwritten(smb):
    conn = smb.connect(RW)
    name = unique()
    put(conn, name, b"first version, longer than the second")
    put(conn, name, b"second")
    assert get(conn, name) == b"second"


def test_a_file_of_several_megabytes_arrives_unchanged(smb):
    conn = smb.connect(RW)
    name, blob = unique("big", ".bin"), os.urandom(3 * 1024 * 1024 + 17)
    put(conn, name, blob)
    on_disk = (smb.storage / name).read_bytes()
    assert hashlib.sha256(on_disk).digest() == hashlib.sha256(blob).digest()
    assert get(conn, name) == blob


def test_write_operations_are_audited(smb):
    conn = smb.connect(RW)
    name = unique("audited")
    put(conn, name)
    conn.deleteFile(SHARE, name)
    lines = [line for line in smb.audit_lines() if name in line]
    assert any("action=upload" in line and f"user='{RW}'" in line for line in lines)


# ---------------------------------------------------------------------------- readonly account
def test_a_readonly_account_can_list_and_download(smb):
    name = unique("shared")
    (smb.storage / name).write_bytes(b"public content")
    conn = smb.connect(RO)
    assert name in names(conn)
    assert get(conn, name) == b"public content"


def test_a_readonly_account_cannot_change_anything(smb):
    keep = unique("keep")
    (smb.storage / keep).write_bytes(b"must survive")
    folder = unique("existing", "")
    (smb.storage / folder).mkdir()
    conn = smb.connect(RO)

    new_name = unique("blocked")
    for action in (
        lambda: put(conn, new_name),
        lambda: put(conn, keep, b"overwritten"),
        lambda: conn.deleteFile(SHARE, keep),
        lambda: conn.rename(SHARE, keep, unique("renamed")),
        lambda: conn.createDirectory(SHARE, unique("newdir", "")),
        lambda: conn.deleteDirectory(SHARE, folder),
    ):
        with pytest.raises(SessionError) as err:
            action()
        assert status_of(err) == ACCESS_DENIED

    assert not (smb.storage / new_name).exists()
    assert (smb.storage / keep).read_bytes() == b"must survive"
    assert (smb.storage / folder).is_dir()


# ---------------------------------------------------------------------------- roles are live
def test_a_new_session_after_a_demotion_is_readonly(smb, scratch_tools, protocol_lab):
    name, password = _account_ready(smb, scratch_tools, protocol_lab, "readwrite")
    first = unique("before")
    put(smb.connect(name, password), first)

    _set_role(scratch_tools, protocol_lab, name, "readonly")
    blocked = unique("after")
    reconnected = smb.connect(name, password)
    with pytest.raises(SessionError) as err:
        put(reconnected, blocked)
    assert status_of(err) == ACCESS_DENIED
    assert not (smb.storage / blocked).exists()
    assert get(reconnected, first) == b"payload"


def test_a_promoted_account_gains_write_access_in_its_open_session(
    smb, scratch_tools, protocol_lab
):
    name, password = _account_ready(smb, scratch_tools, protocol_lab, "readonly")
    conn = smb.connect(name, password)
    tree = conn.connectTree(SHARE)  # stays connected, like a mapped drive
    with pytest.raises(SessionError):
        conn.createFile(tree, unique("blocked"))

    _set_role(scratch_tools, protocol_lab, name, "readwrite")
    allowed = unique("allowed")
    handle = conn.createFile(tree, allowed)
    conn.writeFile(tree, handle, b"now allowed", 0)
    conn.closeFile(tree, handle)
    assert (smb.storage / allowed).read_bytes() == b"now allowed"


def test_a_demoted_account_cannot_create_files_on_a_tree_that_is_already_open(
    smb, scratch_tools, protocol_lab
):
    name, password = _account_ready(smb, scratch_tools, protocol_lab, "readwrite")
    conn = smb.connect(name, password)
    tree = conn.connectTree(SHARE)  # a mapped drive stays connected for hours
    keep = unique("keep")
    put(conn, keep)

    _set_role(scratch_tools, protocol_lab, name, "readonly")
    blocked = unique("after_demotion")
    for action in (
        lambda: conn.createFile(tree, blocked),
        lambda: conn.createDirectory(SHARE, unique("dir", "")),
        lambda: conn.deleteFile(SHARE, keep),
        lambda: conn.rename(SHARE, keep, unique("renamed")),
    ):
        with pytest.raises(SessionError) as err:
            action()
        assert status_of(err) == ACCESS_DENIED
    assert not (smb.storage / blocked).exists()
    assert (smb.storage / keep).exists()
    assert keep in names(conn)  # reading still works


def test_a_file_handle_opened_before_a_demotion_stops_accepting_data(
    smb, scratch_tools, protocol_lab
):
    name, password = _account_ready(smb, scratch_tools, protocol_lab, "readwrite")
    conn = smb.connect(name, password)
    tree = conn.connectTree(SHARE)
    target = unique("handle")
    handle = conn.createFile(tree, target)
    conn.writeFile(tree, handle, b"before", 0)

    _set_role(scratch_tools, protocol_lab, name, "readonly")
    with pytest.raises(SessionError) as err:
        conn.writeFile(tree, handle, b"AFTER-THE-DEMOTION", 6)
    assert status_of(err) == ACCESS_DENIED
    with suppress(SessionError):  # the close may report the refused write again
        conn.closeFile(tree, handle)
    assert (smb.storage / target).read_bytes() == b"before"


def test_a_deleted_account_cannot_write_on_a_tree_that_is_already_open(
    smb, scratch_tools, protocol_lab
):
    name, password = _account_ready(smb, scratch_tools, protocol_lab, "readwrite")
    conn = smb.connect(name, password)
    tree = conn.connectTree(SHARE)
    scratch_tools.run_in_scratch(
        protocol_lab, "assert db.delete_user(sys.argv[1])", name
    )
    blocked = unique("after_delete")
    with pytest.raises(SessionError) as err:
        conn.createFile(tree, blocked)
    assert status_of(err) == ACCESS_DENIED
    assert not (smb.storage / blocked).exists()


# ---------------------------------------------------------------------------- containment
@pytest.fixture()
def world(smb):
    tag = uuid.uuid4().hex[:8]
    outside = smb.data / f"outside_{tag}.txt"
    outside.write_text("TOP-SECRET-PARENT", encoding="utf-8")
    sibling = smb.data / f"storage_{tag}"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("TOP-SECRET-SIBLING", encoding="utf-8")
    yield type("World", (), {"tag": tag, "outside": outside, "sibling": sibling})
    outside.unlink(missing_ok=True)
    for p in sibling.glob("*"):
        p.unlink()
    sibling.rmdir()


def _paths_to_outside(world):
    return [
        f"..\\outside_{world.tag}.txt",
        f"..\\..\\outside_{world.tag}.txt",
        f"\\..\\outside_{world.tag}.txt",
        f"../outside_{world.tag}.txt",
        f"a\\..\\..\\outside_{world.tag}.txt",
        f"..\\storage_{world.tag}\\secret.txt",
        f"\\..\\storage_{world.tag}\\secret.txt",
    ]


def test_files_outside_the_storage_root_cannot_be_downloaded(smb, world):
    conn = smb.connect(RW)
    for path in _paths_to_outside(world):
        try:
            content = get(conn, path)
        except Exception:
            content = b""
        assert b"TOP-SECRET" not in content, path


def test_the_root_cannot_be_left_by_listing(smb, world):
    conn = smb.connect(RW)
    for pattern in ("..\\*", "..\\..\\*", "\\..\\*"):
        try:
            listing = names(conn, pattern)
        except Exception:
            listing = []
        assert not any(n.startswith("outside_") for n in listing), pattern
        assert f"storage_{world.tag}" not in listing, pattern


def test_nothing_can_be_written_outside_the_storage_root(smb, world):
    conn = smb.connect(RW)
    for n, path in enumerate(_paths_to_outside(world)[:4]):
        escape = f"escape_{world.tag}_{n}.txt"
        target = path.replace(f"outside_{world.tag}.txt", escape)
        with suppress(Exception):  # refusal is the expected result
            put(conn, target, b"ATTACKER")
        assert not (smb.data / escape).exists(), target
    with suppress(Exception):  # refusal is the expected result
        conn.createDirectory(SHARE, f"..\\madedir_{world.tag}")
    assert not (smb.data / f"madedir_{world.tag}").exists()


def test_files_outside_the_storage_root_cannot_be_deleted_or_renamed(smb, world):
    conn = smb.connect(RW)
    for path in _paths_to_outside(world):
        for action in (
            lambda p=path: conn.deleteFile(SHARE, p),
            lambda p=path: conn.rename(SHARE, p, f"moved_{world.tag}.txt"),
        ):
            with suppress(Exception):  # refusal is the expected result
                action()
    assert world.outside.read_text(encoding="utf-8") == "TOP-SECRET-PARENT"
    assert (world.sibling / "secret.txt").exists()
    assert not (smb.storage / f"moved_{world.tag}.txt").exists()


def test_a_symlink_pointing_outside_is_not_followed(smb, world):
    link = smb.storage / f"link_{world.tag}"
    try:
        link.symlink_to(world.outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    try:
        conn = smb.connect(RW)
        try:
            content = get(conn, link.name)
        except Exception:
            content = b""
        assert b"TOP-SECRET" not in content
        with suppress(Exception):  # refusal is the expected result
            put(conn, link.name, b"ATTACKER")
        assert world.outside.read_text(encoding="utf-8") == "TOP-SECRET-PARENT"
    finally:
        link.unlink(missing_ok=True)
