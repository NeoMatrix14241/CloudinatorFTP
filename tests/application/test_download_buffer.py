"""
Downloads against the REAL application after 5.42 made file responses read DOWNLOAD_BUFFER_SIZE
(default 1 MiB) per step instead of Quart's 8 KiB (helpers/file_body.py).

The speed is measured by tests/performance/test_baselines.py (opt-in). These tests guard what must
not change: the bytes, the headers, `Range` requests (a video preview seeks with them), a request
that ends exactly on a piece boundary, and many downloads at the same moment.

Uses the shared scratch server (default settings, so the 1 MiB default is what runs).
"""

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

MB = 1024 * 1024
SIZE = 2 * MB + 54321  # two full 1 MiB pieces and a short last one


@pytest.fixture(scope="module")
def blob(scratch_server):
    name = f"dl_{uuid.uuid4().hex[:8]}.bin"
    data = os.urandom(SIZE)
    (scratch_server.storage / name).write_bytes(data)
    return name, data


def test_a_download_is_byte_identical_with_the_right_headers(scratch_server, blob):
    name, data = blob
    reply = scratch_server.login_as("qa_reader").get(f"/download/{name}")
    assert reply.status == 200, reply.status
    assert hashlib.sha256(reply.body).hexdigest() == hashlib.sha256(data).hexdigest()
    assert int(reply.header("Content-Length")) == SIZE
    assert "attachment" in reply.header("Content-Disposition")
    assert name in reply.header("Content-Disposition")


def test_an_inline_view_is_byte_identical_and_not_an_attachment(scratch_server, blob):
    name, data = blob
    reply = scratch_server.login_as("qa_reader").get(f"/view/{name}")
    assert reply.status == 200, reply.status
    assert reply.body == data
    assert "attachment" not in reply.header("Content-Disposition")


@pytest.mark.parametrize(
    "begin, end",
    [
        (0, 0),
        (1000, 5000),
        (MB - 10, MB + 10),  # across the first 1 MiB piece boundary
        (2 * MB - 1, 2 * MB),  # across the second
        (SIZE - 100, SIZE - 1),  # the short last piece
    ],
)
def test_a_range_request_returns_exactly_those_bytes(scratch_server, blob, begin, end):
    name, data = blob
    reply = scratch_server.login_as("qa_reader").get(
        f"/view/{name}", headers={"Range": f"bytes={begin}-{end}"}
    )
    assert reply.status == 206, reply.status
    assert reply.body == data[begin : end + 1]
    assert reply.header("Content-Range") == f"bytes {begin}-{end}/{SIZE}"


def test_an_open_ended_range_runs_to_the_end_of_the_file(scratch_server, blob):
    name, data = blob
    reply = scratch_server.login_as("qa_reader").get(
        f"/view/{name}", headers={"Range": f"bytes={MB + 5}-"}
    )
    assert reply.status == 206
    assert reply.body == data[MB + 5 :]


def test_eight_downloads_at_the_same_moment_are_all_intact(scratch_server, blob):
    name, data = blob
    expected = hashlib.sha256(data).hexdigest()
    clients = [scratch_server.login_as("qa_reader") for _ in range(8)]

    def fetch(client):
        reply = client.get(f"/download/{name}")
        return reply.status, hashlib.sha256(reply.body).hexdigest()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, clients))
    assert results == [(200, expected)] * 8


def test_a_missing_file_is_still_refused(scratch_server):
    reply = scratch_server.login_as("qa_reader").get("/view/no_such_file.bin")
    assert reply.status == 404
