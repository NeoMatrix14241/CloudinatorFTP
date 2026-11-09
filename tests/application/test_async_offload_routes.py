"""
5.44 (ASYNC_BLOCKING_REFACTOR_PLAN): the routes whose disk work moved into worker threads must
answer exactly as before. Against the REAL application, from a scratch copy: same status
codes, same JSON shapes, same files on disk.

Covered: /mkdir, /delete, /bulk_delete, /api/dir_info (index miss -> live walk, then again),
/api/check_conflicts, /api/storage_stats_slow and _debug (cached), /cleanup_chunks,
/admin/chunk_stats and /logout with an unfinished upload (the abandoned chunk folder goes away).
"""

import time
import uuid

import pytest

pytestmark = pytest.mark.application


@pytest.fixture
def server(scratch_server):
    return scratch_server


def _name(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _wait_for(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return predicate()


def _first_chunk(client, file_id, name):
    return client.api(
        "POST",
        "/upload",
        fields={
            "file_id": file_id,
            "chunk_num": "0",
            "total_chunks": "2",
            "filename": name,
            "dest_path": "",
        },
        files={"chunk": ("blob", b"half of a file")},
    )


def _chunk_folders(server):
    chunks = server.storage / ".chunks"
    return [p for p in chunks.iterdir() if p.is_dir()] if chunks.exists() else []


# ------------------------------------------------------------------------ files.py


def test_mkdir_creates_a_folder_and_refuses_a_duplicate(server):
    client = server.login_as("qa_writer")
    name = _name("made")
    first = client.api("POST", "/mkdir", fields={"foldername": name, "path": ""})
    assert first.status == 200 and first.json()["success"] is True
    assert (server.storage / name).is_dir()
    second = client.api("POST", "/mkdir", fields={"foldername": name, "path": ""})
    assert second.status == 409


def test_delete_removes_a_file_and_a_folder(server):
    client = server.login_as("qa_writer")
    folder, single = _name("del_dir"), _name("del_file") + ".txt"
    (server.storage / folder).mkdir()
    (server.storage / folder / "inner.txt").write_text("x")
    (server.storage / single).write_text("y")
    for target in (folder, single):
        reply = client.api("POST", "/delete", fields={"target_path": target})
        assert reply.status == 302
    assert not (server.storage / folder).exists()
    assert not (server.storage / single).exists()


def test_bulk_delete_reports_success_and_partial_failure(server):
    client = server.login_as("qa_writer")
    folder, single = _name("bulk_dir"), _name("bulk_file") + ".txt"
    (server.storage / folder / "sub").mkdir(parents=True)
    (server.storage / folder / "sub" / "a.txt").write_text("a")
    (server.storage / single).write_text("b")

    ok = client.api("POST", "/bulk_delete", json_body={"paths": [folder, single]})
    assert ok.status == 200
    assert ok.json() == {"deleted_count": 2, "success": True}
    assert not (server.storage / folder).exists()

    other = _name("bulk_other") + ".txt"
    (server.storage / other).write_text("c")
    missing = _name("nope")
    mixed = client.api("POST", "/bulk_delete", json_body={"paths": [other, missing]})
    assert mixed.status == 207
    body = mixed.json()
    assert body["deleted_count"] == 1
    assert body["errors"] == [f"Path not found: {missing}"]
    assert not (server.storage / other).exists()


def test_bulk_delete_without_paths_is_still_a_400(server):
    client = server.login_as("qa_writer")
    assert client.api("POST", "/bulk_delete", json_body={}).status == 400
    assert client.api("POST", "/bulk_delete", json_body={"paths": []}).status == 400


def test_dir_info_answers_for_a_folder_the_index_has_not_seen_yet(server):
    client = server.login_as("qa_writer")
    folder = _name("info")
    (server.storage / folder / "child").mkdir(parents=True)
    (server.storage / folder / "a.bin").write_bytes(b"x" * 1000)
    (server.storage / folder / "child" / "b.bin").write_bytes(b"y" * 500)
    expected = {"file_count": 1, "dir_count": 1, "total_size": 1500}

    first = client.api("GET", f"/api/dir_info/{folder}")
    assert first.status == 200
    assert first.json() == expected
    # the second answer must be the same, whether it came from the live walk or the index
    second = client.api("GET", f"/api/dir_info/{folder}")
    assert second.status == 200 and second.json() == expected


def test_dir_info_rejects_an_unsafe_path(server):
    client = server.login_as("qa_writer")
    assert client.api("GET", "/api/dir_info/..%2F..%2Fetc").status in (400, 404)


def test_check_conflicts_lists_only_the_names_that_exist_at_the_destination(server):
    client = server.login_as("qa_writer")
    dest = _name("conf_dest")
    (server.storage / dest / "taken_dir").mkdir(parents=True)
    (server.storage / dest / "taken.txt").write_text("t")
    reply = client.api(
        "POST",
        "/api/check_conflicts",
        json_body={
            "paths": ["taken.txt", "taken_dir", "free.txt", "../outside.txt"],
            "destination": dest,
        },
    )
    assert reply.status == 200
    conflicts = sorted(reply.json()["conflicts"], key=lambda c: c["name"])
    assert conflicts == [
        {"source": "taken.txt", "name": "taken.txt", "is_dir": False},
        {"source": "taken_dir", "name": "taken_dir", "is_dir": True},
    ]


# ----------------------------------------------------------------------- stats.py


def test_storage_stats_slow_and_debug_answer_and_agree(server):
    client = server.login_as("qa_writer")
    slow = client.api("GET", "/api/storage_stats_slow")
    assert slow.status == 200
    stats = slow.json()
    assert {"total_space", "used_space", "free_space", "file_count"} <= set(stats)

    # served from the 30 s cache: the same numbers, even if a file appeared in between
    (server.storage / (_name("late") + ".txt")).write_text("z")
    again = client.api("GET", "/api/storage_stats_slow")
    assert again.status == 200 and again.json() == stats

    # The debug route has no @login_required of its own, but the session hook of
    # middleware.py still answers an anonymous caller with 401.
    assert server.client().api("GET", "/api/storage_stats_debug").status == 401
    debug = client.api("GET", "/api/storage_stats_debug")
    assert debug.status == 200
    assert debug.json()["stats"] == stats


# --------------------------------------------------------------------- uploads.py


def test_cleanup_chunks_route_removes_only_that_upload(server):
    client = server.login_as("qa_writer")
    name = _name("half") + ".bin"
    assert _first_chunk(client, "fid_7_14", name).status == 200
    assert _wait_for(lambda: len(_chunk_folders(server)) == 1)

    stats = client.api("GET", "/admin/chunk_stats").json()
    assert stats["filesystem_chunks"] == 1

    reply = client.api("POST", "/cleanup_chunks", json_body={"file_id": "fid_7_14"})
    assert reply.status == 200
    assert reply.json() == {
        "success": True,
        "message": "Cleaned up chunks for fid_7_14",
    }
    assert _chunk_folders(server) == []

    again = client.api("POST", "/cleanup_chunks", json_body={"file_id": "fid_7_14"})
    assert again.status == 200
    assert again.json() == {"success": True, "message": "No chunks to cleanup"}
    assert client.api("GET", "/admin/chunk_stats").json()["filesystem_chunks"] == 0


def test_cleanup_chunks_route_rejects_a_bad_id(server):
    client = server.login_as("qa_writer")
    reply = client.api("POST", "/cleanup_chunks", json_body={"file_id": "../x"})
    assert reply.status == 400


def test_admin_cleanup_chunks_runs_the_whole_sequence(server):
    client = server.login_as("qa_writer")
    reply = client.api("POST", "/admin/cleanup_chunks")
    assert reply.status == 200
    body = reply.json()
    assert body["success"] is True
    assert set(body) >= {"stats_before", "stats_after", "manual_cleanup_success"}


def test_logout_removes_the_abandoned_chunks_of_that_session(server):
    client = server.login_as("qa_writer")
    name = _name("abandoned") + ".bin"
    assert _first_chunk(client, "fid_8_14", name).status == 200
    assert _wait_for(lambda: len(_chunk_folders(server)) == 1)

    reply = client.request("GET", "/logout")
    assert reply.status == 302
    assert _wait_for(lambda: _chunk_folders(server) == [])


# ------------------------------------------------------- ZIP download (core.py, T5)


def test_bulk_download_streams_a_valid_zip_larger_than_the_hand_over_queue(server):
    import io
    import os
    import zipfile

    client = server.login_as("qa_writer")
    folder = _name("zipme")
    (server.storage / folder / "deep").mkdir(parents=True)
    expected = {}
    # 12 files of 300 KB of random bytes: far more ZIP chunks than the queue (8) holds, so the
    # worker thread really waits for the reader; the bytes must still arrive intact and in order.
    for i in range(12):
        data = os.urandom(300 * 1024)
        rel = f"{folder}/deep/f{i}.bin" if i % 2 else f"{folder}/f{i}.bin"
        (server.storage / rel).write_bytes(data)
        expected[rel] = data

    reply = client.api("POST", "/bulk-download", json_body={"paths": [folder]})
    assert reply.status == 200
    assert reply.headers.get("Content-Type", "").startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(reply.body)) as archive:
        assert archive.testzip() is None
        got = {n: archive.read(n) for n in archive.namelist() if not n.endswith("/")}
    assert got == expected

    # the server is still healthy afterwards (no leaked state from the stream)
    assert client.api("GET", "/api/dir_info/").status == 200


# ------------------------------------------------ Rebuild Cache (5.44.1, routes/admin.py)


def test_rebuild_cache_runs_in_the_background_and_reports_the_outcome(server):
    client = server.login_as("qa_writer")
    for i in range(5):
        (server.storage / f"rebuild_{i}.txt").write_text("x" * (i + 1))

    started = client.api("POST", "/admin/rebuild_cache")
    assert started.status == 202 and started.json()["started"] is True

    # the status route answers while it runs and names what it is doing
    deadline = time.monotonic() + 90
    status = {}
    while time.monotonic() < deadline:
        status = client.api("GET", "/admin/rebuild_cache/status").json()
        if status["state"] != "running":
            break
        assert "phase" in status and "elapsed" in status
        time.sleep(0.2)
    assert status["state"] == "done", status
    assert status["phase"] == "" and status["error"] == ""
    assert (
        "Cache cleared and rebuilt" in status["message"] and "Took" in status["message"]
    )

    # the audit of the file index no longer holds the button: it arrives after "done"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not status.get("audit"):
        time.sleep(0.3)
        status = client.api("GET", "/admin/rebuild_cache/status").json()
    assert status["audit"].startswith("Verified"), status


def test_a_second_rebuild_after_the_first_one_finished_is_accepted(server):
    client = server.login_as("qa_writer")
    first = client.api("POST", "/admin/rebuild_cache")
    assert first.status in (
        202,
        409,
    )  # 409 only if an earlier test's rebuild is still going
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if (
            client.api("GET", "/admin/rebuild_cache/status").json()["state"]
            != "running"
        ):
            break
        time.sleep(0.2)
    again = client.api("POST", "/admin/rebuild_cache")
    assert again.status == 202
