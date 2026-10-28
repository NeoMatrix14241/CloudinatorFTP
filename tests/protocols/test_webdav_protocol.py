"""
WebDAV (webdav_server.py: wsgidav behind Hypercorn) against the REAL server code, started from a
scratch copy of the project on ephemeral ports and driven with the standard library's http.client
(raw WebDAV methods: PROPFIND, MKCOL, PUT, MOVE, COPY, LOCK ...). Two servers, as in production:
the HTTPS listener and the plain-HTTP FALLBACK listener (WEBDAV_ENABLED with HTTPS off).

Checked on both: no credentials, wrong password, unknown user, empty password and a non-Basic
scheme get 401 (and an anonymous write changes nothing); a readwrite account does the whole cycle
on disk; a readonly account can read but every write method gets 403 and changes nothing; role
changes apply once the 30-second credential cache expires (the launcher shortens it to 1 s); paths
cannot leave the storage root. HTTPS only: the plaintext listener is NOT opened next to a working
HTTPS one even when WEBDAV_ENABLED is on, the certificate (never the key) is downloadable without
login, the connection is HTTP/1.1 only (the Windows WebClient rule), and plain HTTP to the TLS
port gets no answer.

The plain-HTTP fallback listener (HTTPS off, or failing) really opens since CLAUDE.md 5.29:
Hypercorn only honours `insecure_bind` when TLS is configured, so webdav_server now puts the plain
port in `bind` when there is no TLS (the pure helper `_listener_binds`, also tested in
tests/unit/test_webdav_listener_binds.py).

Not covered: Windows WebClient quirks, LOCK-based editing sessions, very large transfers.
"""

import base64
import http.client
import socket
import ssl
import time
import uuid

import pytest

pytestmark = pytest.mark.protocol

RW, RO = "qa_writer", "qa_reader"

WEBDAV_LAUNCHER = """
import webdav_server
webdav_server._AuthCache.TTL = 1   # production: 30 s; a role change must show quickly here
assert webdav_server.start(), "webdav_server.start() returned False"
print("READY", flush=True)
while True:
    time.sleep(1)
"""

WRITE_METHODS = ("PUT", "DELETE", "MKCOL", "COPY", "MOVE", "LOCK", "PROPPATCH")
PROPFIND_BODY = b'<?xml version="1.0"?><propfind xmlns="DAV:"><allprop/></propfind>'


def wait_for_port(port, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"nothing is listening on port {port}")


class DavEnv:
    def __init__(self, port, lab, users, tls):
        self.port, self.tls, self.users = port, tls, users
        self.storage = lab / "data" / "storage"
        self.data = lab / "data"

    def _connection(self):
        if self.tls:
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return http.client.HTTPSConnection(
                "127.0.0.1", self.port, timeout=30, context=ctx
            )
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)

    def basic(self, user, password=None):
        pw = password if password is not None else self.users[user][0]
        return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()

    def request(self, method, path, body=None, user=None, password=None, headers=None):
        """(status, headers, body). `user` None sends no credentials."""
        hdrs = dict(headers or {})
        if user is not None:
            hdrs["Authorization"] = self.basic(user, password)
        conn = self._connection()
        try:
            conn.request(method, path, body=body, headers=hdrs)
            resp = conn.getresponse()
            head = {k.lower(): v for k, v in resp.getheaders()}
            try:
                return resp.status, head, resp.read()
            except http.client.IncompleteRead as cut:
                # the server may drop the connection mid-answer for a hostile path
                return resp.status, head, cut.partial
        except (OSError, http.client.HTTPException):
            return 0, {}, b""  # no answer at all
        finally:
            conn.close()

    def destination(self, path):
        return {
            "Destination": f"{'https' if self.tls else 'http'}://127.0.0.1:{self.port}{path}"
        }


@pytest.fixture(scope="module")
def dav_http_port(launch, scratch_tools):
    port = scratch_tools.free_port()
    launch(
        WEBDAV_LAUNCHER,
        config={
            "WEBDAV_ENABLED": True,
            "WEBDAV_PORT": port,
            "WEBDAV_HTTPS_ENABLED": False,
        },
    )
    return port


@pytest.fixture(scope="module")
def dav_http(dav_http_port, protocol_lab, scratch_tools):
    try:
        wait_for_port(dav_http_port, timeout=10)
    except RuntimeError:
        pytest.skip(
            "the plain-HTTP fallback listener does not open (see the xfail test)"
        )
    return DavEnv(
        dav_http_port, protocol_lab, dict(scratch_tools.test_users), tls=False
    )


@pytest.fixture(scope="module")
def dav_https(launch, protocol_lab, scratch_tools):
    pytest.importorskip("cryptography")
    port, plain = scratch_tools.free_port(), scratch_tools.free_port()
    launch(
        WEBDAV_LAUNCHER,
        config={
            "WEBDAV_ENABLED": True,  # must be ignored: HTTPS is used exclusively
            "WEBDAV_PORT": plain,
            "WEBDAV_HTTPS_ENABLED": True,
            "WEBDAV_HTTPS_PORT": port,
        },
    )
    wait_for_port(port)
    env = DavEnv(port, protocol_lab, dict(scratch_tools.test_users), tls=True)
    env.plain_port = plain
    return env


@pytest.fixture(params=["https", "http"])
def dav(request):
    """Every test that uses `dav` runs against HTTPS AND the plain fallback. The fixture of the
    server is looked up lazily, so a skipped plain listener never skips the HTTPS runs.
    """
    return request.getfixturevalue(
        "dav_https" if request.param == "https" else "dav_http"
    )


def unique(prefix="f", ext=".txt"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"


# ---------------------------------------------------------------------------- the plain fallback
def test_the_plain_http_fallback_listener_opens(dav_http_port):
    wait_for_port(dav_http_port, timeout=10)


# ---------------------------------------------------------------------------- authentication
def test_no_credentials_get_a_basic_challenge(dav):
    for method, body in (("GET", None), ("PROPFIND", PROPFIND_BODY), ("OPTIONS", None)):
        status, headers, _ = dav.request(method, "/", body=body)
        assert status == 401, method
        assert headers["www-authenticate"].lower().startswith("basic"), method


def test_a_wrong_password_an_unknown_user_and_an_empty_password_are_refused(dav):
    assert dav.request("GET", "/", user=RW, password="not-the-password")[0] == 401
    assert (
        dav.request("GET", "/", user=f"nobody_{uuid.uuid4().hex[:6]}", password="x")[0]
        == 401
    )
    assert dav.request("GET", "/", user=RW, password="")[0] == 401


def test_another_authentication_scheme_is_refused(dav):
    status, _, _ = dav.request(
        "GET", "/", headers={"Authorization": "Bearer abc.def.ghi"}
    )
    assert status == 401


def test_an_anonymous_write_changes_nothing(dav):
    name = unique("anon")
    assert dav.request("PUT", f"/{name}", body=b"ATTACKER")[0] == 401
    assert dav.request("MKCOL", f"/{name}_dir")[0] == 401
    assert (
        not (dav.storage / name).exists() and not (dav.storage / f"{name}_dir").exists()
    )


def test_a_write_with_a_wrong_password_changes_nothing(dav):
    name = unique("wrongpw")
    assert dav.request("PUT", f"/{name}", body=b"x", user=RW, password="nope")[0] == 401
    assert not (dav.storage / name).exists()


# ---------------------------------------------------------------------------- readwrite account
def test_a_readwrite_account_can_do_the_whole_file_cycle(dav):
    name, folder = unique(), unique("dir", "")
    renamed, copied = unique("renamed"), unique("copy")
    data = bytes(range(256)) * 20

    assert dav.request("PUT", f"/{name}", body=data, user=RW)[0] == 201
    assert (dav.storage / name).read_bytes() == data
    status, _, body = dav.request("GET", f"/{name}", user=RW)
    assert status == 200 and body == data
    status, _, listing = dav.request(
        "PROPFIND", "/", body=PROPFIND_BODY, user=RW, headers={"Depth": "1"}
    )
    assert status == 207 and name.encode() in listing

    assert dav.request("MKCOL", f"/{folder}", user=RW)[0] == 201
    assert (dav.storage / folder).is_dir()
    assert dav.request("PUT", f"/{folder}/inner.txt", body=b"inner", user=RW)[0] == 201

    status = dav.request(
        "MOVE", f"/{name}", user=RW, headers=dav.destination(f"/{renamed}")
    )[0]
    assert status in (201, 204)
    assert (
        not (dav.storage / name).exists()
        and (dav.storage / renamed).read_bytes() == data
    )
    status = dav.request(
        "COPY", f"/{renamed}", user=RW, headers=dav.destination(f"/{copied}")
    )[0]
    assert status in (201, 204)
    assert (dav.storage / copied).read_bytes() == data and (
        dav.storage / renamed
    ).exists()

    assert dav.request("DELETE", f"/{folder}", user=RW)[0] == 204
    assert dav.request("DELETE", f"/{renamed}", user=RW)[0] == 204
    assert dav.request("DELETE", f"/{copied}", user=RW)[0] == 204
    assert not any((dav.storage / n).exists() for n in (folder, renamed, copied))


def test_an_existing_file_can_be_overwritten(dav):
    name = unique()
    assert dav.request("PUT", f"/{name}", body=b"first version", user=RW)[0] == 201
    assert dav.request("PUT", f"/{name}", body=b"second", user=RW)[0] in (200, 204)
    assert (dav.storage / name).read_bytes() == b"second"


# ---------------------------------------------------------------------------- readonly account
def test_a_readonly_account_can_read(dav):
    name = unique("shared")
    (dav.storage / name).write_bytes(b"public content")
    status, _, body = dav.request("GET", f"/{name}", user=RO)
    assert (status, body) == (200, b"public content")
    assert dav.request("HEAD", f"/{name}", user=RO)[0] == 200
    assert dav.request("OPTIONS", "/", user=RO)[0] == 200
    status, _, listing = dav.request(
        "PROPFIND", "/", body=PROPFIND_BODY, user=RO, headers={"Depth": "1"}
    )
    assert status == 207 and name.encode() in listing


def test_a_readonly_account_cannot_change_anything(dav):
    keep = unique("keep")
    (dav.storage / keep).write_bytes(b"must survive")
    folder = unique("existing", "")
    (dav.storage / folder).mkdir()
    new_name = unique("blocked")

    attempts = {
        "PUT": (f"/{new_name}", b"ATTACKER", {}),
        "DELETE": (f"/{keep}", None, {}),
        "MKCOL": (f"/{unique('newdir', '')}", None, {}),
        "COPY": (f"/{keep}", None, dav.destination(f"/{unique('copy')}")),
        "MOVE": (f"/{keep}", None, dav.destination(f"/{unique('moved')}")),
        "LOCK": (f"/{keep}", b"<lockinfo xmlns='DAV:'/>", {}),
        "PROPPATCH": (f"/{keep}", b"<propertyupdate xmlns='DAV:'/>", {}),
    }
    assert set(attempts) == set(WRITE_METHODS)
    for method, (path, body, headers) in attempts.items():
        status, _, _ = dav.request(method, path, body=body, user=RO, headers=headers)
        assert status == 403, method

    put = dav.request("PUT", f"/{keep}", body=b"overwritten", user=RO)[0]
    assert put == 403
    assert not (dav.storage / new_name).exists()
    assert (dav.storage / keep).read_bytes() == b"must survive"
    assert (dav.storage / folder).is_dir()
    assert (
        sorted(
            p.name
            for p in dav.storage.iterdir()
            if p.name.startswith(("copy_", "moved_", "newdir_"))
        )
        == []
    )


# ---------------------------------------------------------------------------- roles (after the credential cache)
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


def test_a_demoted_account_loses_write_access_once_the_cache_expires(
    dav, scratch_tools, protocol_lab
):
    name, password = _new_account(scratch_tools, protocol_lab, "readwrite")
    first = unique("before")
    assert (
        dav.request("PUT", f"/{first}", body=b"x", user=name, password=password)[0]
        == 201
    )

    _set_role(scratch_tools, protocol_lab, name, "readonly")
    time.sleep(
        2
    )  # the launcher sets the credential cache TTL to 1 s (30 s in production)
    second = unique("after")
    assert (
        dav.request("PUT", f"/{second}", body=b"x", user=name, password=password)[0]
        == 403
    )
    assert not (dav.storage / second).exists()
    assert dav.request("GET", f"/{first}", user=name, password=password)[0] == 200


def test_a_promoted_account_gains_write_access_once_the_cache_expires(
    dav, scratch_tools, protocol_lab
):
    name, password = _new_account(scratch_tools, protocol_lab, "readonly")
    blocked = unique("blocked")
    assert (
        dav.request("PUT", f"/{blocked}", body=b"x", user=name, password=password)[0]
        == 403
    )

    _set_role(scratch_tools, protocol_lab, name, "readwrite")
    time.sleep(2)
    allowed = unique("allowed")
    assert (
        dav.request("PUT", f"/{allowed}", body=b"x", user=name, password=password)[0]
        == 201
    )
    assert (dav.storage / allowed).exists() and not (dav.storage / blocked).exists()


# ---------------------------------------------------------------------------- containment
@pytest.fixture()
def world(dav):
    tag = uuid.uuid4().hex[:8]
    outside = dav.data / f"outside_{tag}.txt"
    outside.write_text("TOP-SECRET-PARENT", encoding="utf-8")
    sibling = dav.data / f"storage_{tag}"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("TOP-SECRET-SIBLING", encoding="utf-8")
    yield type("World", (), {"tag": tag, "outside": outside, "sibling": sibling})
    outside.unlink(missing_ok=True)
    for p in sibling.glob("*"):
        p.unlink()
    sibling.rmdir()


def _paths_to_outside(world):
    return [
        f"/../outside_{world.tag}.txt",
        f"/../../outside_{world.tag}.txt",
        f"/%2e%2e/outside_{world.tag}.txt",
        f"/..%2foutside_{world.tag}.txt",
        f"/a/../../outside_{world.tag}.txt",
        f"/../storage_{world.tag}/secret.txt",
        f"/%2e%2e/storage_{world.tag}/secret.txt",
    ]


def test_files_outside_the_storage_root_cannot_be_read(dav, world):
    for path in _paths_to_outside(world):
        status, _, body = dav.request("GET", path, user=RW)
        assert b"TOP-SECRET" not in body, path
        status, _, body = dav.request(
            "PROPFIND", path, body=PROPFIND_BODY, user=RW, headers={"Depth": "0"}
        )
        assert b"TOP-SECRET" not in body, path


def test_nothing_can_be_written_outside_the_storage_root(dav, world):
    for n, path in enumerate(_paths_to_outside(world)[:5]):
        escape = f"escape_{world.tag}_{n}.txt"
        target = path.replace(f"outside_{world.tag}.txt", escape)
        dav.request("PUT", target, body=b"ATTACKER", user=RW)
        assert not (dav.data / escape).exists(), target
    dav.request("MKCOL", f"/../madedir_{world.tag}", user=RW)
    assert not (dav.data / f"madedir_{world.tag}").exists()


def test_files_outside_the_storage_root_cannot_be_deleted_moved_or_overwritten(
    dav, world
):
    for path in _paths_to_outside(world):
        dav.request("DELETE", path, user=RW)
        dav.request(
            "MOVE", path, user=RW, headers=dav.destination(f"/moved_{world.tag}.txt")
        )
        dav.request("PUT", path, body=b"OVERWRITTEN", user=RW)
    assert world.outside.read_text(encoding="utf-8") == "TOP-SECRET-PARENT"
    assert (world.sibling / "secret.txt").read_text(
        encoding="utf-8"
    ) == "TOP-SECRET-SIBLING"
    assert not (dav.storage / f"moved_{world.tag}.txt").exists()


def test_a_file_inside_the_root_cannot_be_moved_outside_it(dav, world):
    name = unique("stay")
    (dav.storage / name).write_bytes(b"inside")
    for dest in (f"/../moved_{world.tag}.txt", f"/%2e%2e/moved_{world.tag}.txt"):
        dav.request("MOVE", f"/{name}", user=RW, headers=dav.destination(dest))
        dav.request("COPY", f"/{name}", user=RW, headers=dav.destination(dest))
        assert not (dav.data / f"moved_{world.tag}.txt").exists(), dest
    assert (dav.storage / name).read_bytes() == b"inside"


# ---------------------------------------------------------------------------- HTTPS specifics
def test_the_plaintext_listener_is_not_opened_next_to_working_https(dav_https):
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", dav_https.plain_port), timeout=3).close()


def test_plain_http_to_the_tls_port_gets_no_answer(dav_https):
    conn = http.client.HTTPConnection("127.0.0.1", dav_https.port, timeout=10)
    try:
        conn.request("GET", "/", headers={"Authorization": dav_https.basic(RW)})
        status = conn.getresponse().status
    except (OSError, http.client.HTTPException):
        return  # reset / closed / garbage: nothing was served
    finally:
        conn.close()
    assert not 200 <= status < 300


def test_the_certificate_but_never_the_key_can_be_downloaded_without_login(dav_https):
    status, _, body = dav_https.request("GET", "/webdav.crt")
    assert status == 200 and b"BEGIN CERTIFICATE" in body
    assert b"PRIVATE KEY" not in body
    assert dav_https.request("GET", "/webdav.key")[0] in (401, 404)


def test_the_tls_listener_speaks_http_1_1_only(dav_https):
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["h2", "http/1.1"])
    with socket.create_connection(("127.0.0.1", dav_https.port), timeout=10) as raw:
        with ctx.wrap_socket(raw, server_hostname="localhost") as tls:
            assert tls.selected_alpn_protocol() == "http/1.1"
