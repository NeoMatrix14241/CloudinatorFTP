"""
Stop, crash and restart (5.40): the application started from a scratch copy is stopped the way
manage.sh stops it, killed without any chance to clean up, and started again on the same data.

What must hold after a restart: the accounts and the files are still there, the server answers and
lets users log in, a file uploaded before the stop is intact, and a half-finished upload from before
a crash neither shows up as a file nor stops a fresh upload from arriving exactly.

These tests start their OWN scratch server (a second copy of the project, with its own port and
data), because they stop and start it. They are OPT-IN (CLOUDINATOR_SLOW_TESTS=1, set by the
nightly workflow): every start of the application takes several seconds.

    CLOUDINATOR_SLOW_TESTS=1 python -m pytest tests/reliability/test_restart.py -q

A crash is `Popen.kill()`: SIGKILL on Linux, TerminateProcess on Windows. Not covered: a power cut
(no fsync checks), a full disk, and the optional protocol servers (FTP, SFTP, WebDAV, SMB).
"""

import os
import time
import uuid

import pytest

pytestmark = [
    pytest.mark.reliability,
    pytest.mark.skipif(
        os.environ.get("CLOUDINATOR_SLOW_TESTS") != "1",
        reason="slow and timing-sensitive: set CLOUDINATOR_SLOW_TESTS=1 to run",
    ),
]

RW = "qa_writer"


class App:
    """One scratch application that can be stopped, killed and started again."""

    def __init__(self, tools, root, port):
        self.tools, self.root, self.port = tools, root, port
        self.server = None

    def start(self):
        self.server = self.tools.start_server(self.root, self.port)
        return self.server

    def stop(self):
        self.tools.stop_server(self.server)

    def crash(self):
        self.server.proc.kill()
        self.server.proc.wait()
        self.tools.stop_server(self.server)  # only closes the log handle now

    def restart(self, crash=False):
        if crash:
            self.crash()
        else:
            self.stop()
        return self.start()


@pytest.fixture(scope="module")
def app(scratch_tools, tmp_path_factory):
    root = tmp_path_factory.mktemp("restart_lab") / "app"
    port = scratch_tools.free_port()
    scratch_tools.build(root, port=port)
    assert scratch_tools.paths_outside(root) == []
    scratch_tools.seed_users(root)
    application = App(scratch_tools, root, port)
    application.start()
    try:
        yield application
    finally:
        if application.server is not None:
            application.stop()


def _chunk(client, file_id, number, total, name, data):
    return client.api(
        "POST",
        "/upload",
        fields={
            "file_id": file_id,
            "chunk_num": str(number),
            "total_chunks": str(total),
            "filename": name,
            "dest_path": "",
        },
        files={"chunk": ("blob", data)},
    )


def _wait_for_content(path, expected, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if path.read_bytes() == expected:
                return True
        except OSError:
            # not there yet, or momentarily busy: poll again
            pass
        time.sleep(0.25)
    return False


def _upload(client, name, parts, file_id="fid_1_100"):
    for number, data in enumerate(parts):
        reply = _chunk(client, file_id, number, len(parts), name, data)
        assert reply.status == 200, (number, reply.status, reply.text[:200])


def _logged_in(server, user=RW):
    client = server.client()
    reply = client.login(user, server.users[user][0])
    assert (
        reply.status == 302
    ), f"login as {user} failed after the restart: {reply.status}"
    return client


def test_a_graceful_restart_keeps_the_accounts_and_the_uploaded_files(app):
    name = f"before_stop_{uuid.uuid4().hex[:8]}.bin"
    parts = [b"alpha-" * 40, b"beta-" * 40, b"gamma-" * 40]
    _upload(_logged_in(app.server), name, parts)
    assert _wait_for_content(app.server.storage / name, b"".join(parts))

    server = app.restart()

    assert _wait_for_content(
        server.storage / name, b"".join(parts)
    ), "the file is intact"
    client = _logged_in(server)
    reply = client.get(
        f"/api/versions/list?path={name}", headers={"Accept": "application/json"}
    )
    assert reply.status == 200, "an authenticated request works after the restart"
    assert _logged_in(server, "qa_reader"), "every account survived, not only one"


def test_a_crash_in_the_middle_of_an_upload_publishes_nothing_and_a_new_upload_is_exact(
    app,
):
    name = f"crash_{uuid.uuid4().hex[:8]}.bin"
    first_try = [b"AAAA" * 64, b"BBBB" * 64, b"CCCC" * 64]
    client = _logged_in(app.server)
    _chunk(client, "fid_2_768", 0, 3, name, first_try[0])
    _chunk(
        client, "fid_2_768", 1, 3, name, first_try[1]
    )  # the last chunk never arrives

    server = app.restart(crash=True)

    assert not (server.storage / name).exists(), "an unfinished upload is never a file"
    parts = [b"1111" * 64, b"2222" * 64, b"3333" * 64]
    _upload(_logged_in(server), name, parts, file_id="fid_3_768")
    assert _wait_for_content(server.storage / name, b"".join(parts)), server.log_tail()


def test_after_restarts_no_temp_file_of_an_assembly_is_left_in_the_storage_folder(app):
    time.sleep(3)  # let a late assembly or cleanup finish
    leftovers = [
        p.name
        for p in app.server.storage.rglob("*")
        if p.name.startswith(".assembling_")
    ]
    assert leftovers == [], f"hidden temp files left behind: {leftovers}"


def test_the_server_survives_several_quick_restarts_in_a_row(app):
    for _ in range(3):
        server = app.restart(crash=True)
        assert server.get("/login")[0] == 200
    assert _logged_in(app.server)
