"""
The REAL Version Engine worker, end to end (5.40): a file appears or changes in the storage
folder, the worker process notices and captures a version, and the HTTP routes show it.

The other version tests (test_version_restore.py, test_version_routes.py) run the engine's code
directly and capture with `Engine.snapshot_file()`; they never start the worker. This file uses
the `scratch_server_with_versions` fixture (tests/conftest.py): dev_server.py with
VERSION_ENGINE_ENABLED on, tracking the scratch storage folder, so dev_server.py spawns
`version_engine.py --worker` exactly like production. The worker is a separate process that polls
the folder (every 3 s) and the scanner runs every 5 s here, so every wait is a BOUNDED POLL on
what the HTTP API reports, never a fixed sleep.

OPT-IN: these tests take real time (tens of seconds) and depend on a background process, so they
are skipped unless CLOUDINATOR_SLOW_TESTS=1 (the nightly workflow sets it):

    CLOUDINATOR_SLOW_TESTS=1 python -m pytest tests/reliability/test_version_engine_live.py -q

Not covered: crash recovery of the worker (killing it and starting it again) and retention under
load; see docs/TESTING_STRATEGY.md.
"""

import hashlib
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
JSON_ACCEPT = {"Accept": "application/json"}
WAIT_SECONDS = 60  # the worker needs a few seconds to start, then polls every 3 s


@pytest.fixture(scope="module")
def server(scratch_server_with_versions):
    return scratch_server_with_versions


@pytest.fixture(scope="module")
def rw(server):
    return server.login_as(RW)


def _tag():
    return uuid.uuid4().hex[:8]


def _history(client, rel):
    reply = client.get(f"/api/versions/list?path={rel}", headers=JSON_ACCEPT)
    assert reply.status == 200, (reply.status, reply.text[:200])
    return reply.json()


def _completed(client, rel):
    body = _history(client, rel)
    return [v for v in body["versions"] if v["status"] == "completed"]


def _wait_for(predicate, what, timeout=WAIT_SECONDS, interval=0.5):
    """Poll `predicate` until it returns something truthy; fail with `what` after `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    pytest.fail(f"timed out after {timeout}s waiting for: {what}")


def test_a_new_file_is_captured_by_the_worker_without_any_request(server, rw):
    rel = f"live_{_tag()}.txt"
    data = b"captured by the background worker " * 20
    (server.storage / rel).write_bytes(data)
    versions = _wait_for(lambda: _completed(rw, rel), f"a captured version of {rel}")
    assert len(versions) == 1
    assert versions[0]["size"] == len(data)
    assert versions[0]["sha256"] == hashlib.sha256(data).hexdigest()


def test_a_change_gets_a_second_version_and_the_first_one_stays_restorable(server, rw):
    rel = f"changing_{_tag()}.txt"
    first, second = b"first content", b"second content, longer"
    (server.storage / rel).write_bytes(first)
    _wait_for(lambda: len(_completed(rw, rel)) == 1, f"the first version of {rel}")
    (server.storage / rel).write_bytes(second)
    versions = _wait_for(
        lambda: len(_completed(rw, rel)) == 2 and _completed(rw, rel),
        f"the second version of {rel}",
    )
    oldest = min(versions, key=lambda v: v["created_at"])
    assert oldest["sha256"] == hashlib.sha256(first).hexdigest()

    restored = rw.api(
        "POST",
        "/api/versions/restore",
        json_body={"path": rel, "version_id": oldest["version_id"]},
    )
    assert restored.status == 200, restored.text[:200]
    recovered = server.storage / restored.json()["recovered_path"]
    assert recovered.read_bytes() == first, "the old content comes back"
    assert (
        server.storage / rel
    ).read_bytes() == second, "the live file is never touched"


def test_an_excluded_file_is_never_captured(server, rw):
    # *.tmp is in the default exclude patterns. The plain file is written AFTER the excluded one,
    # so once the plain file is captured a full pass has certainly seen both.
    tag = _tag()
    (server.storage / f"scratch_{tag}.tmp").write_bytes(b"temporary")
    (server.storage / f"plain_{tag}.txt").write_bytes(b"ordinary")
    _wait_for(lambda: _completed(rw, f"plain_{tag}.txt"), "the ordinary file")
    assert _history(rw, f"scratch_{tag}.tmp") == {"tracked": False, "versions": []}


def test_deleting_a_file_keeps_its_history_and_it_can_still_be_recovered(server, rw):
    rel = f"deleted_{_tag()}.txt"
    data = b"must survive the delete"
    (server.storage / rel).write_bytes(data)
    versions = _wait_for(lambda: _completed(rw, rel), f"a captured version of {rel}")
    (server.storage / rel).unlink()
    time.sleep(
        7
    )  # let the watcher and the scanner notice the deletion (3 s and 5 s periods)
    after = _history(rw, rel)
    assert after["tracked"] is True and len(after["versions"]) == len(versions)
    restored = rw.api(
        "POST",
        "/api/versions/restore",
        json_body={"path": rel, "version_id": versions[0]["version_id"]},
    )
    assert restored.status == 200, restored.text[:200]
    assert (server.storage / restored.json()["recovered_path"]).read_bytes() == data
    assert not (server.storage / rel).exists(), "restore never recreates the original"
