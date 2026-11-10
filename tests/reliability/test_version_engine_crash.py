"""
The Version Engine after a crash (5.44.3): the application is killed without any chance to clean
up, files change while nothing is running, the application starts again. And the other way round:
the worker process alone dies while the web application keeps running.

What must hold (the contract of version_engine.py: its own worker process, the SQLite database and
the version store under cache/, an orphan guard that stops the worker when its parent is gone):

* the worker does NOT outlive a killed parent (helpers/parent_watch.py), so a crashed server never
  leaves a second engine behind that would fight the next one for the database;
* the versions captured before the crash are still listed and still restore byte for byte;
* a file that changed (or appeared) while nothing was running is captured after the restart: the
  scanner finds it, nobody has to touch the file again;
* nothing is left half-captured: no version stays in a status other than `completed`;
* a dead worker does not take the web application down: the history of every earlier capture is
  still readable and restorable through the routes.

These tests start their OWN scratch server (a copy of the project with the Version Engine ON, its
own port and data), because they kill and restart it. OPT-IN (CLOUDINATOR_SLOW_TESTS=1, set by the
nightly workflow): every start takes several seconds and the worker polls every 3 s. Every wait is
a BOUNDED POLL on what the HTTP API reports, never a fixed sleep.

    CLOUDINATOR_SLOW_TESTS=1 python -m pytest tests/reliability/test_version_engine_crash.py -q

A crash is `Popen.kill()` (SIGKILL on Linux, TerminateProcess on Windows). Not covered: a power cut
(no fsync checks), a full disk, retention under load.
"""

import hashlib
import os
import time
import uuid

import psutil
import pytest

pytestmark = [
    pytest.mark.reliability,
    pytest.mark.skipif(
        os.environ.get("CLOUDINATOR_SLOW_TESTS") != "1",
        reason="slow and timing-sensitive: set CLOUDINATOR_SLOW_TESTS=1 to run",
    ),
]

RW = "qa_writer"
JSON_ACCEPT = {"Accept": "application/json"}
WAIT_SECONDS = 60


def _engine_config(storage_dir) -> dict:
    """The same settings as tests/conftest.py version_engine_config (tests cannot import it)."""
    return {
        "VERSION_ENGINE_ENABLED": True,
        "VERSION_TRACK_ALL_FILES": True,
        "VERSION_TRACK_ROOTS": [str(storage_dir)],
        "VERSION_WATCH_ENABLED": True,
        "VERSION_SCAN_ENABLED": True,
        "VERSION_SCAN_INTERVAL": 5,
        "VERSION_RETENTION_ENABLED": False,
    }


class App:
    """One scratch application with the Version Engine on, that can be killed and started again."""

    def __init__(self, tools, root, port):
        self.tools, self.root, self.port = tools, root, port
        self.server = None
        self.worker_pid = None

    def start(self):
        # dev_server.py writes the worker's PID for manage.sh (version_engine._write_ve_pidfile);
        # a crash leaves the OLD file behind, so it goes first or the wait below reads a stale pid
        pidfile = self.root / ".manage_pids" / "version_engine.pid"
        pidfile.unlink(missing_ok=True)
        self.server = self.tools.start_server(self.root, self.port)
        self.worker_pid = _wait_for(
            lambda: int(pidfile.read_text("utf-8").strip()) if pidfile.is_file() else 0,
            "the worker's pid file",
        )
        assert _alive(
            self.worker_pid
        ), "the worker is not running right after the start"
        return self.server

    def crash(self):
        self.server.proc.kill()
        self.server.proc.wait()
        self.tools.stop_server(self.server)  # only closes the log handle now

    def stop(self):
        self.tools.stop_server(self.server)

    @property
    def storage(self):
        return self.root / "data" / "storage"

    def client(self):
        return self.server.login_as(RW)


def _alive(pid) -> bool:
    """True while `pid` runs. A zombie (killed, not yet reaped by its parent) is gone."""
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _wait_for(predicate, what, timeout=WAIT_SECONDS, interval=0.5):
    deadline = time.monotonic() + timeout
    result = predicate()
    while not result and time.monotonic() < deadline:
        time.sleep(interval)
        result = predicate()
    if not result:
        pytest.fail(f"timed out after {timeout}s waiting for: {what}")
    return result


def _history(client, rel):
    reply = client.get(f"/api/versions/list?path={rel}", headers=JSON_ACCEPT)
    assert reply.status == 200, (reply.status, reply.text[:200])
    return reply.json()


def _completed(client, rel):
    return [v for v in _history(client, rel)["versions"] if v["status"] == "completed"]


def _restore(client, app, rel, version):
    reply = client.api(
        "POST",
        "/api/versions/restore",
        json_body={"path": rel, "version_id": version["version_id"]},
    )
    assert reply.status == 200, reply.text[:200]
    return (app.storage / reply.json()["recovered_path"]).read_bytes()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def app(scratch_tools, tmp_path_factory):
    """A fresh scratch application per test: a killed worker must not leak into the next test."""
    root = tmp_path_factory.mktemp("ve_crash_lab") / "app"
    port = scratch_tools.free_port()
    storage = root / "data" / "storage"
    scratch_tools.build(root, port=port, config=_engine_config(storage))
    assert scratch_tools.paths_outside(root) == []
    scratch_tools.seed_users(root)
    application = App(scratch_tools, root, port)
    application.start()
    try:
        yield application
    finally:
        if application.server is not None:
            application.stop()
        # a worker the test killed the server under must not outlive the test
        if application.worker_pid and _alive(application.worker_pid):
            psutil.Process(application.worker_pid).kill()


def test_a_crashed_server_leaves_no_worker_and_the_restart_catches_up(app):
    tag = uuid.uuid4().hex[:8]
    changing, fresh = f"changing_{tag}.txt", f"fresh_{tag}.txt"
    first, second, new = (
        b"first content " * 30,
        b"second content, longer " * 30,
        b"new " * 50,
    )
    rw = app.client()
    (app.storage / changing).write_bytes(first)
    _wait_for(lambda: len(_completed(rw, changing)) == 1, "the first capture")

    worker = app.worker_pid
    app.crash()
    _wait_for(
        lambda: not _alive(worker), "the orphaned worker to stop by itself", timeout=30
    )

    # while nothing is running: one file changes, one appears
    (app.storage / changing).write_bytes(second)
    (app.storage / fresh).write_bytes(new)

    app.start()
    assert app.worker_pid != worker, "a NEW worker, not the old one"
    rw = app.client()
    both = _wait_for(
        lambda: len(_completed(rw, changing)) == 2 and _completed(rw, changing),
        "the change made while the server was down",
    )
    caught_up = _wait_for(
        lambda: _completed(rw, fresh), "the file created while the server was down"
    )
    assert caught_up[0]["sha256"] == _sha(new)

    # the version taken BEFORE the crash is intact and restorable; the live file is untouched
    oldest = min(both, key=lambda v: v["created_at"])
    assert oldest["sha256"] == _sha(first)
    assert _restore(rw, app, changing, oldest) == first
    assert (app.storage / changing).read_bytes() == second

    # nothing is stuck half-way
    for rel in (changing, fresh):
        states = {v["status"] for v in _history(rw, rel)["versions"]}
        assert states == {"completed"}, f"{rel}: {states}"


def test_a_dead_worker_does_not_take_the_web_application_down(app):
    rel = f"before_{uuid.uuid4().hex[:8]}.txt"
    data = b"captured before the worker died " * 20
    rw = app.client()
    (app.storage / rel).write_bytes(data)
    versions = _wait_for(lambda: _completed(rw, rel), "the capture before the crash")

    psutil.Process(app.worker_pid).kill()
    _wait_for(lambda: not _alive(app.worker_pid), "the killed worker to be gone", 15)

    # the application keeps serving: login page, listing, history and restore all still work
    assert app.server.get("/login")[0] == 200
    app.client()  # a new login still works
    assert _history(rw, rel)["tracked"] is True
    assert _restore(rw, app, rel, versions[0]) == data
    assert app.server.proc.poll() is None, "the server process is still running"

    # a restart brings the capturing back: a change made while there was no worker is caught
    app.stop()
    (app.storage / rel).write_bytes(data + b" and changed")
    app.start()
    rw = app.client()
    _wait_for(
        lambda: len(_completed(rw, rel)) == 2,
        "the change made while the worker was dead",
    )
