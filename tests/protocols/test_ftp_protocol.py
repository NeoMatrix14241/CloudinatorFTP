"""
FTP and FTPS (ftp_server.py, pyftpdlib) against the REAL server code, started from a scratch copy
of the project on ephemeral ports and driven with the standard library's ftplib.

Checked, for the plain FALLBACK server and for the FTPS server (explicit AUTH TLS):
- wrong password, unknown user and empty password are refused; too many failures end the session;
- a readwrite account can upload, download, list, rename, make and remove folders, delete;
- a readonly account can list and download but every change is refused and changes nothing;
- the role is read from the database on every command (a demoted account loses write access in
  its OPEN session);
- nothing can leave the storage root (.., absolute paths, a sibling folder named like the root);
- FTPS: the control channel must be TLS before a login, the data channel must be TLS too.

Not covered: passive-port firewalling, FTPS with a CA-signed certificate, very large transfers.
"""

import ftplib
import io
import ssl
import uuid

import pytest

pytestmark = pytest.mark.protocol

RW, RO = "qa_writer", "qa_reader"

FTP_LAUNCHER = """
import ftp_server
port, passive = int(sys.argv[1]), int(sys.argv[2])
assert ftp_server.start(port), "ftp_server.start() returned False"
ftp_server._server.handler.passive_ports = range(passive, passive + 40)
print("READY", flush=True)
while True:
    time.sleep(1)
"""


class FtpEnv:
    def __init__(self, port, lab, users, tls):
        self.port, self.tls = port, tls
        self.storage = lab / "data" / "storage"
        self.data = lab / "data"
        self.users = users

    def connect(self, user=None, password=None, tls=None):
        """A logged-in ftplib client (user=None: connected, not logged in)."""
        tls = self.tls if tls is None else tls
        if tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ftp = ftplib.FTP_TLS(context=ctx)
        else:
            ftp = ftplib.FTP()
        ftp.connect("127.0.0.1", self.port, timeout=30)
        if user is not None:
            pw = password if password is not None else self.users[user][0]
            ftp.login(user, pw)
            if tls:
                ftp.prot_p()
        return ftp

    def login_as(self, user):
        return self.connect(user)


def _users(scratch_tools):
    return dict(scratch_tools.test_users)


@pytest.fixture(scope="module")
def ftp_plain(launch, protocol_lab, scratch_tools):
    port, passive = scratch_tools.free_port(), scratch_tools.free_port()
    launch(
        FTP_LAUNCHER,
        port,
        passive,
        config={"FTP_ENABLED": True, "FTP_PORT": port, "FTP_TLS_ENABLED": False},
    )
    return FtpEnv(port, protocol_lab, _users(scratch_tools), tls=False)


@pytest.fixture(scope="module")
def ftps(launch, protocol_lab, scratch_tools):
    pytest.importorskip("OpenSSL")
    port, passive = scratch_tools.free_port(), scratch_tools.free_port()
    launch(
        FTP_LAUNCHER,
        port,
        passive,
        config={"FTP_ENABLED": True, "FTP_PORT": port, "FTP_TLS_ENABLED": True},
    )
    return FtpEnv(port, protocol_lab, _users(scratch_tools), tls=True)


@pytest.fixture(params=["plain", "tls"])
def ftp(request, ftp_plain, ftps):
    """Every test that uses `ftp` runs against the plain fallback AND the FTPS server."""
    return ftp_plain if request.param == "plain" else ftps


def unique(prefix="f", ext=".txt"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"


def upload(client, name, data=b"payload"):
    client.storbinary(f"STOR {name}", io.BytesIO(data))


def download(client, name):
    buf = io.BytesIO()
    client.retrbinary(f"RETR {name}", buf.write)
    return buf.getvalue()


# ---------------------------------------------------------------------------- authentication
def test_a_wrong_password_is_refused(ftp):
    client = ftp.connect()
    with pytest.raises(ftplib.error_perm, match="530"):
        client.login(RW, "definitely-not-the-password")


def test_an_unknown_user_is_refused(ftp):
    client = ftp.connect()
    with pytest.raises(ftplib.error_perm, match="530"):
        client.login(f"nobody_{uuid.uuid4().hex[:6]}", "whatever")


def test_an_empty_password_is_refused(ftp):
    client = ftp.connect()
    with pytest.raises(ftplib.error_perm):
        client.login(RW, "")


def test_nothing_works_before_a_login(ftp):
    client = ftp.connect()
    with pytest.raises(ftplib.error_perm, match="530"):
        client.nlst()
    with pytest.raises(ftplib.error_perm, match="530"):
        client.mkd(unique("dir", ""))


def test_repeated_wrong_passwords_end_the_session(ftp_plain):
    client = ftp_plain.connect()
    ended = False
    for _ in range(8):
        try:
            client.login(RW, "wrong")
            pytest.fail("a wrong password was accepted")
        except ftplib.error_perm:
            continue  # 530, the session is still open
        except (ftplib.error_temp, EOFError, ConnectionError, OSError):
            ended = True  # 421 or a closed connection
            break
    assert ended, "the server kept the session open after 8 wrong passwords"


# ---------------------------------------------------------------------------- readwrite account
def test_a_readwrite_account_can_do_the_whole_file_cycle(ftp):
    client = ftp.login_as(RW)
    name, folder, renamed = unique(), unique("dir", ""), unique("renamed")
    data = bytes(range(256)) * 20
    upload(client, name, data)
    assert (ftp.storage / name).read_bytes() == data
    assert name in client.nlst()
    assert download(client, name) == data
    client.rename(name, renamed)
    assert not (ftp.storage / name).exists() and (ftp.storage / renamed).exists()
    client.mkd(folder)
    assert (ftp.storage / folder).is_dir()
    upload(client, f"{folder}/inner.txt", b"inner")
    assert download(client, f"{folder}/inner.txt") == b"inner"
    client.delete(f"{folder}/inner.txt")
    client.rmd(folder)
    client.delete(renamed)
    assert not (ftp.storage / folder).exists() and not (ftp.storage / renamed).exists()
    client.quit()


def test_login_message_names_the_role(ftp):
    client = ftp.connect()
    reply = client.login(RW, ftp.users[RW][0])
    assert "read-write" in reply
    client = ftp.connect()
    assert "read-only" in client.login(RO, ftp.users[RO][0])


# ---------------------------------------------------------------------------- readonly account
def test_a_readonly_account_can_list_and_download(ftp):
    name = unique("shared")
    (ftp.storage / name).write_bytes(b"public content")
    client = ftp.login_as(RO)
    assert name in client.nlst()
    assert download(client, name) == b"public content"


def test_a_readonly_account_cannot_change_anything(ftp):
    keep = unique("keep")
    (ftp.storage / keep).write_bytes(b"must survive")
    folder = unique("existing", "")
    (ftp.storage / folder).mkdir()
    client = ftp.login_as(RO)

    new_name = unique("blocked")
    with pytest.raises(ftplib.error_perm, match="550"):
        upload(client, new_name)
    with pytest.raises(ftplib.error_perm, match="550"):
        client.delete(keep)
    with pytest.raises(ftplib.error_perm, match="550"):
        client.rename(keep, unique("renamed"))
    with pytest.raises(ftplib.error_perm, match="550"):
        client.mkd(unique("newdir", ""))
    with pytest.raises(ftplib.error_perm, match="550"):
        client.rmd(folder)
    with pytest.raises(ftplib.error_perm, match="550"):
        client.sendcmd(f"APPE {keep}")

    assert not (ftp.storage / new_name).exists()
    assert (ftp.storage / keep).read_bytes() == b"must survive"
    assert (ftp.storage / folder).is_dir()


# ---------------------------------------------------------------------------- roles are live
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


def test_a_demoted_account_loses_write_access_in_its_open_session(
    ftp, scratch_tools, protocol_lab
):
    name, password = _new_account(scratch_tools, protocol_lab, "readwrite")
    client = ftp.connect(name, password)
    first = unique("before")
    upload(client, first)
    assert (ftp.storage / first).exists()

    _set_role(scratch_tools, protocol_lab, name, "readonly")
    second = unique("after")
    with pytest.raises(ftplib.error_perm, match="550"):
        upload(client, second)
    assert not (ftp.storage / second).exists()
    assert download(client, first) == b"payload"  # reading still works


def test_a_promoted_account_gains_write_access_in_its_open_session(
    ftp, scratch_tools, protocol_lab
):
    name, password = _new_account(scratch_tools, protocol_lab, "readonly")
    client = ftp.connect(name, password)
    blocked = unique("blocked")
    with pytest.raises(ftplib.error_perm, match="550"):
        upload(client, blocked)

    _set_role(scratch_tools, protocol_lab, name, "readwrite")
    allowed = unique("allowed")
    upload(client, allowed)
    assert (ftp.storage / allowed).exists() and not (ftp.storage / blocked).exists()


# ---------------------------------------------------------------------------- containment
@pytest.fixture()
def world(ftp):
    tag = uuid.uuid4().hex[:8]
    outside = ftp.data / f"outside_{tag}.txt"
    outside.write_text("TOP-SECRET-PARENT", encoding="utf-8")
    sibling = ftp.data / f"storage_{tag}"
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


def test_files_outside_the_storage_root_cannot_be_downloaded(ftp, world):
    client = ftp.login_as(RW)
    for path in _paths_to_outside(world):
        buf = io.BytesIO()
        try:
            client.retrbinary(f"RETR {path}", buf.write)
        except (ftplib.error_perm, ftplib.error_temp):
            pass
        assert b"TOP-SECRET" not in buf.getvalue(), path


def test_the_root_cannot_be_left_by_changing_directory(ftp, world):
    client = ftp.login_as(RW)
    for target in ("..", "../..", "/..", "/../.."):
        try:
            client.cwd(target)
        except (ftplib.error_perm, ftplib.error_temp):
            pass
        assert client.pwd() == "/", target
    assert not any(n.startswith("outside_") for n in client.nlst())


def test_nothing_can_be_written_outside_the_storage_root(ftp, world):
    client = ftp.login_as(RW)
    for n, path in enumerate(_paths_to_outside(world)[:3]):
        escape = f"escape_{world.tag}_{n}.txt"
        target = path.replace(f"outside_{world.tag}.txt", escape)
        try:
            upload(client, target, b"ATTACKER")
        except (ftplib.error_perm, ftplib.error_temp):
            pass
        assert not (ftp.data / escape).exists(), target
    try:
        client.mkd(f"../madedir_{world.tag}")
    except (ftplib.error_perm, ftplib.error_temp):
        pass
    assert not (ftp.data / f"madedir_{world.tag}").exists()


def test_files_outside_the_storage_root_cannot_be_deleted_or_renamed(ftp, world):
    client = ftp.login_as(RW)
    for path in _paths_to_outside(world):
        for action in (
            lambda p=path: client.delete(p),
            lambda p=path: client.rename(p, f"moved_{world.tag}.txt"),
        ):
            try:
                action()
            except (ftplib.error_perm, ftplib.error_temp):
                pass
    assert world.outside.read_text(encoding="utf-8") == "TOP-SECRET-PARENT"
    assert (world.sibling / "secret.txt").exists()
    assert not (ftp.storage / f"moved_{world.tag}.txt").exists()


# ---------------------------------------------------------------------------- FTPS requirements
def test_ftps_refuses_a_login_without_tls_on_the_control_channel(ftps):
    client = ftps.connect(tls=False)  # a plain client against the TLS server
    with pytest.raises(ftplib.error_perm):
        client.login(RW, ftps.users[RW][0])


def test_ftps_refuses_a_clear_text_data_channel(ftps):
    client = ftps.connect(tls=True)
    client.login(RW, ftps.users[RW][0])  # FTP_TLS.login runs AUTH TLS first
    client.voidcmd("PBSZ 0")
    client.voidcmd("PROT C")  # ask for a clear-text data channel
    with pytest.raises(ftplib.error_perm):
        client.nlst()
    client.prot_p()
    assert isinstance(client.nlst(), list)
