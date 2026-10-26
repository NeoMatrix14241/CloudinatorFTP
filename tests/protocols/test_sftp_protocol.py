"""
SFTP (sftp_server.py, paramiko) against the REAL server code, started from a scratch copy of the
project on an ephemeral port and driven with paramiko's own SFTP client.

Checked: bad logins are refused (wrong password, unknown user, empty password, no authentication);
a readwrite account does the whole file cycle on disk; a readonly account can list and read but
every change is refused and changes nothing; nothing can leave the storage root (.. segments,
a sibling folder named like the root, a symlink pointing outside); weak ciphers and MACs are not
accepted; port forwarding and command execution over the SSH connection are refused; the role is
read from the database on every operation (CLAUDE.md 5.29): a demoted account loses write access
in its OPEN session, also on a file handle opened before the demotion, a promoted account gains it,
and a deleted account can no longer write.

Not covered: public-key login (not supported by the server), very large transfers, sshfs.
"""

import io
import uuid

import paramiko
import pytest

pytestmark = pytest.mark.protocol

RW, RO = "qa_writer", "qa_reader"

SFTP_LAUNCHER = """
import sftp_server
port = int(sys.argv[1])
assert sftp_server.start(port), "sftp_server.start() returned False"
print("READY", flush=True)
while True:
    time.sleep(1)
"""


class SftpEnv:
    def __init__(self, port, lab, users):
        self.port, self.users = port, users
        self.storage = lab / "data" / "storage"
        self.data = lab / "data"
        self._open = []

    def transport(self, user=None, password=None, **options):
        sock_args = ("127.0.0.1", self.port)
        t = paramiko.Transport(sock_args)
        for key, value in options.items():
            setattr(t.get_security_options(), key, value)
        self._open.append(t)
        if user is None:
            t.start_client(timeout=30)
            return t
        pw = password if password is not None else self.users[user][0]
        t.connect(username=user, password=pw)
        return t

    def client(self, user, password=None):
        t = self.transport(user, password)
        return paramiko.SFTPClient.from_transport(t)

    def close_all(self):
        for t in self._open:
            try:
                t.close()
            except Exception:
                pass
        self._open.clear()


@pytest.fixture(scope="module")
def sftp(launch, protocol_lab, scratch_tools):
    port = scratch_tools.free_port()
    launch(SFTP_LAUNCHER, port, config={"SFTP_ENABLED": True, "SFTP_PORT": port})
    env = SftpEnv(port, protocol_lab, dict(scratch_tools.test_users))
    yield env
    env.close_all()


def unique(prefix="f", ext=".txt"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"


def put(client, name, data=b"payload"):
    client.putfo(io.BytesIO(data), name)


def get(client, name):
    buf = io.BytesIO()
    client.getfo(name, buf)
    return buf.getvalue()


DENIED = (PermissionError, IOError, OSError)


# ---------------------------------------------------------------------------- authentication
def test_a_wrong_password_is_refused(sftp):
    with pytest.raises(paramiko.AuthenticationException):
        sftp.transport(RW, "definitely-not-the-password")


def test_an_unknown_user_is_refused(sftp):
    with pytest.raises(paramiko.AuthenticationException):
        sftp.transport(f"nobody_{uuid.uuid4().hex[:6]}", "whatever")


def test_an_empty_password_is_refused(sftp):
    with pytest.raises(paramiko.AuthenticationException):
        sftp.transport(RW, "")


def test_no_authentication_at_all_is_refused(sftp):
    t = sftp.transport()  # SSH handshake only
    with pytest.raises(paramiko.BadAuthenticationType) as err:
        t.auth_none(RW)
    assert err.value.allowed_types == ["password"]
    assert not t.is_authenticated()


# ---------------------------------------------------------------------------- readwrite account
def test_a_readwrite_account_can_do_the_whole_file_cycle(sftp):
    client = sftp.client(RW)
    name, folder, renamed = unique(), unique("dir", ""), unique("renamed")
    data = bytes(range(256)) * 20
    put(client, name, data)
    assert (sftp.storage / name).read_bytes() == data
    assert name in client.listdir(".")
    assert get(client, name) == data
    assert client.stat(name).st_size == len(data)
    client.rename(name, renamed)
    assert not (sftp.storage / name).exists() and (sftp.storage / renamed).exists()
    client.mkdir(folder)
    assert (sftp.storage / folder).is_dir()
    put(client, f"{folder}/inner.txt", b"inner")
    assert get(client, f"{folder}/inner.txt") == b"inner"
    client.remove(f"{folder}/inner.txt")
    client.rmdir(folder)
    client.remove(renamed)
    assert (
        not (sftp.storage / folder).exists() and not (sftp.storage / renamed).exists()
    )


def test_an_existing_file_can_be_overwritten_and_appended(sftp):
    client = sftp.client(RW)
    name = unique()
    put(client, name, b"first version")
    put(client, name, b"second")
    assert (sftp.storage / name).read_bytes() == b"second"
    with client.open(name, "a") as f:
        f.write(b" + appended")
    assert (sftp.storage / name).read_bytes() == b"second + appended"


# ---------------------------------------------------------------------------- readonly account
def test_a_readonly_account_can_list_and_download(sftp):
    name = unique("shared")
    (sftp.storage / name).write_bytes(b"public content")
    client = sftp.client(RO)
    assert name in client.listdir(".")
    assert get(client, name) == b"public content"


def test_a_readonly_account_cannot_change_anything(sftp):
    keep = unique("keep")
    (sftp.storage / keep).write_bytes(b"must survive")
    folder = unique("existing", "")
    (sftp.storage / folder).mkdir()
    client = sftp.client(RO)

    new_name = unique("blocked")
    with pytest.raises(DENIED):
        put(client, new_name)
    with pytest.raises(DENIED):
        put(client, keep, b"overwritten")
    with pytest.raises(DENIED):
        client.remove(keep)
    with pytest.raises(DENIED):
        client.rename(keep, unique("renamed"))
    with pytest.raises(DENIED):
        client.mkdir(unique("newdir", ""))
    with pytest.raises(DENIED):
        client.rmdir(folder)
    with pytest.raises(DENIED):
        client.chmod(keep, 0o600)
    with pytest.raises(DENIED):
        client.truncate(keep, 0)

    assert not (sftp.storage / new_name).exists()
    assert (sftp.storage / keep).read_bytes() == b"must survive"
    assert (sftp.storage / folder).is_dir()


# ---------------------------------------------------------------------------- roles
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


def _delete_account(scratch_tools, protocol_lab, name):
    scratch_tools.run_in_scratch(
        protocol_lab, "assert db.delete_user(sys.argv[1])", name
    )


def test_a_new_session_after_a_demotion_is_readonly(sftp, scratch_tools, protocol_lab):
    name, password = _new_account(scratch_tools, protocol_lab, "readwrite")
    first = unique("before")
    put(sftp.client(name, password), first)
    assert (sftp.storage / first).exists()

    _set_role(scratch_tools, protocol_lab, name, "readonly")
    blocked = unique("after")
    reconnected = sftp.client(name, password)
    with pytest.raises(DENIED):
        put(reconnected, blocked)
    assert not (sftp.storage / blocked).exists()
    assert get(reconnected, first) == b"payload"


def test_a_demoted_account_loses_write_access_in_its_open_session(
    sftp, scratch_tools, protocol_lab
):
    name, password = _new_account(scratch_tools, protocol_lab, "readwrite")
    client = sftp.client(name, password)
    put(client, unique("before"))

    _set_role(scratch_tools, protocol_lab, name, "readonly")
    second = unique("after")
    with pytest.raises(DENIED):
        put(client, second)
    assert not (sftp.storage / second).exists()


def test_a_file_handle_opened_before_a_demotion_stops_accepting_data(
    sftp, scratch_tools, protocol_lab
):
    name, password = _new_account(scratch_tools, protocol_lab, "readwrite")
    client = sftp.client(name, password)
    target = unique("handle")
    handle = client.open(target, "wb", bufsize=0)  # unbuffered: every write is sent
    handle.write(b"before")

    _set_role(scratch_tools, protocol_lab, name, "readonly")
    with pytest.raises(DENIED):
        handle.write(b"AFTER-THE-DEMOTION")
    try:
        handle.close()
    except DENIED:
        pass  # the close may report the refused write again
    assert (sftp.storage / target).read_bytes() == b"before"
    assert get(client, target) == b"before"  # reading still works


def test_a_promoted_account_gains_write_access_in_its_open_session(
    sftp, scratch_tools, protocol_lab
):
    name, password = _new_account(scratch_tools, protocol_lab, "readonly")
    client = sftp.client(name, password)
    blocked = unique("blocked")
    with pytest.raises(DENIED):
        put(client, blocked)

    _set_role(scratch_tools, protocol_lab, name, "readwrite")
    allowed = unique("allowed")
    put(client, allowed)
    assert (sftp.storage / allowed).exists() and not (sftp.storage / blocked).exists()


def test_a_deleted_account_cannot_write_in_its_open_session(
    sftp, scratch_tools, protocol_lab
):
    name, password = _new_account(scratch_tools, protocol_lab, "readwrite")
    client = sftp.client(name, password)
    keep = unique("keep")
    put(client, keep)

    _delete_account(scratch_tools, protocol_lab, name)
    blocked = unique("after_delete")
    with pytest.raises(DENIED):
        put(client, blocked)
    with pytest.raises(DENIED):
        client.remove(keep)
    with pytest.raises(DENIED):
        client.mkdir(unique("dir", ""))
    assert not (sftp.storage / blocked).exists()
    assert (sftp.storage / keep).exists()


# ---------------------------------------------------------------------------- containment
@pytest.fixture()
def world(sftp):
    tag = uuid.uuid4().hex[:8]
    outside = sftp.data / f"outside_{tag}.txt"
    outside.write_text("TOP-SECRET-PARENT", encoding="utf-8")
    sibling = sftp.data / f"storage_{tag}"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("TOP-SECRET-SIBLING", encoding="utf-8")
    yield type("World", (), {"tag": tag, "outside": outside, "sibling": sibling})
    outside.unlink(missing_ok=True)
    for p in sibling.glob("*"):
        p.unlink()
    sibling.rmdir()


def _paths_to_outside(world):
    return [
        f"../outside_{world.tag}.txt",
        f"../../outside_{world.tag}.txt",
        f"/../outside_{world.tag}.txt",
        f"..\\outside_{world.tag}.txt",
        f"a/../../outside_{world.tag}.txt",
        f"../storage_{world.tag}/secret.txt",
        f"/../storage_{world.tag}/secret.txt",
    ]


def test_files_outside_the_storage_root_cannot_be_downloaded(sftp, world):
    client = sftp.client(RW)
    for path in _paths_to_outside(world):
        try:
            content = get(client, path)
        except (OSError, IOError):
            content = b""
        assert b"TOP-SECRET" not in content, path


def test_the_root_cannot_be_left_by_listing_or_normalizing(sftp, world):
    client = sftp.client(RW)
    for target in ("..", "../..", "/..", "/../.."):
        assert client.normalize(target) == "/", target
        names = client.listdir(target)
        assert not any(n.startswith("outside_") for n in names), target
        assert not any(n == f"storage_{world.tag}" for n in names), target


def test_nothing_can_be_written_outside_the_storage_root(sftp, world):
    client = sftp.client(RW)
    for n, path in enumerate(_paths_to_outside(world)[:3]):
        escape = f"escape_{world.tag}_{n}.txt"
        target = path.replace(f"outside_{world.tag}.txt", escape)
        try:
            put(client, target, b"ATTACKER")
        except (OSError, IOError):
            pass
        assert not (sftp.data / escape).exists(), target
    try:
        client.mkdir(f"../madedir_{world.tag}")
    except (OSError, IOError):
        pass
    assert not (sftp.data / f"madedir_{world.tag}").exists()


def test_files_outside_the_storage_root_cannot_be_deleted_or_renamed(sftp, world):
    client = sftp.client(RW)
    for path in _paths_to_outside(world):
        for action in (
            lambda p=path: client.remove(p),
            lambda p=path: client.rename(p, f"moved_{world.tag}.txt"),
        ):
            try:
                action()
            except (OSError, IOError):
                pass
    assert world.outside.read_text(encoding="utf-8") == "TOP-SECRET-PARENT"
    assert (world.sibling / "secret.txt").exists()
    assert not (sftp.storage / f"moved_{world.tag}.txt").exists()


def test_a_symlink_pointing_outside_is_not_followed(sftp, world):
    link = sftp.storage / f"link_{world.tag}"
    try:
        link.symlink_to(world.outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    try:
        client = sftp.client(RW)
        try:
            content = get(client, link.name)
        except (OSError, IOError):
            content = b""
        assert b"TOP-SECRET" not in content
    finally:
        link.unlink(missing_ok=True)


# ---------------------------------------------------------------------------- transport hardening
@pytest.mark.parametrize("cipher", ["aes128-cbc", "aes256-cbc", "3des-cbc"])
def test_cbc_and_3des_ciphers_are_not_accepted(sftp, cipher):
    with pytest.raises(paramiko.SSHException):
        sftp.transport(RW, ciphers=(cipher,))


@pytest.mark.parametrize("mac", ["hmac-md5", "hmac-sha1-96"])
def test_md5_and_truncated_sha1_macs_are_not_accepted(sftp, mac):
    with pytest.raises(paramiko.SSHException):
        sftp.transport(RW, digests=(mac,))


def test_a_modern_cipher_still_works(sftp):
    t = sftp.transport(RW, ciphers=("aes256-ctr",), digests=("hmac-sha2-256",))
    assert t.is_authenticated()


def test_port_forwarding_through_the_server_is_refused(sftp):
    t = sftp.transport(RW)
    with pytest.raises(paramiko.ChannelException):
        t.open_channel("direct-tcpip", ("127.0.0.1", 22), ("127.0.0.1", 0))


def test_running_a_command_over_the_connection_is_refused(sftp):
    t = sftp.transport(RW)
    chan = t.open_session()
    with pytest.raises(paramiko.SSHException):
        chan.exec_command("echo owned")
