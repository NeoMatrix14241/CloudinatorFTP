"""
Concurrency against the REAL application, started from a scratch copy (5.40): many users and many
requests at the same moment. The example tests elsewhere do one thing at a time; this is where a
race between the upload routes, the assembly queue and the file monitor would show up.

OPT-IN (CLOUDINATOR_SLOW_TESTS=1, set by the nightly workflow): the tests start threads, wait for
the background assembly and take several seconds each.

    CLOUDINATOR_SLOW_TESTS=1 python -m pytest tests/reliability/test_concurrency.py -q

If one of these fails, do not just re-run it: a failure here can be a REAL race in routes/uploads.py
or storage.py. Keep scratch_server.log (the failure output prints its tail).

Rules from CODING_GUIDELINES.md 18.1 that apply: the tests wait for the expected CONTENT, never
only for a file to exist; nothing is written outside the scratch copy.
"""

import hashlib
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = [
    pytest.mark.reliability,
    pytest.mark.skipif(
        os.environ.get("CLOUDINATOR_SLOW_TESTS") != "1",
        reason="slow and timing-sensitive: set CLOUDINATOR_SLOW_TESTS=1 to run",
    ),
]

USERS = 6
CHUNKS = 12


@pytest.fixture(scope="module")
def server(scratch_server):
    return scratch_server


def _send_chunk(client, file_id, number, total, name, data):
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


def _payload(label, number, size=2048):
    seed = hashlib.sha256(f"{label}-{number}".encode()).digest()
    return (seed * (size // len(seed) + 1))[:size]


def test_many_users_with_the_same_upload_id_each_get_their_own_exact_file(server):
    tag = uuid.uuid4().hex[:8]
    file_id = "fid_1_6144"  # the short id every browser can produce
    accounts = [server.make_user("readwrite") for _ in range(USERS)]
    clients = []
    for name, password in accounts:
        client = server.client()
        assert client.login(name, password).status == 302
        clients.append(client)

    expected = {}

    def upload(index):
        parts = [_payload(f"{tag}-user{index}", n) for n in range(3)]
        filename = f"crowd_{tag}_{index}.bin"
        expected[filename] = b"".join(parts)
        for number, data in enumerate(parts):
            reply = _send_chunk(clients[index], file_id, number, 3, filename, data)
            assert reply.status == 200, (index, number, reply.status, reply.text[:200])

    with ThreadPoolExecutor(max_workers=USERS) as pool:
        for future in [pool.submit(upload, i) for i in range(USERS)]:
            future.result(timeout=120)

    for filename, content in expected.items():
        assert _wait_for_content(
            server.storage / filename, content
        ), f"{filename} is missing or has the wrong bytes\n{server.log_tail()}"


def test_the_chunks_of_one_upload_arriving_at_the_same_moment_assemble_exactly_once(
    server,
):
    tag = uuid.uuid4().hex[:8]
    client = server.login_as("qa_writer")
    filename = f"parallel_{tag}.bin"
    parts = [_payload(tag, n) for n in range(CHUNKS)]

    def send(number):
        return _send_chunk(
            client, "fid_2_24576", number, CHUNKS, filename, parts[number]
        )

    with ThreadPoolExecutor(max_workers=CHUNKS) as pool:
        replies = list(pool.map(send, range(CHUNKS)))
    assert [r.status for r in replies] == [200] * CHUNKS, [
        r.text[:120] for r in replies
    ]

    target = server.storage / filename
    assert _wait_for_content(target, b"".join(parts)), server.log_tail()
    time.sleep(3)  # a second, late assembly of the same upload would show up now
    assert target.read_bytes() == b"".join(parts)
    leftovers = [p.name for p in server.storage.iterdir() if p.name.endswith(".part")]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_many_logins_at_the_same_moment_all_succeed(server):
    def log_in(_):
        client = server.client()
        return client.login("qa_reader", server.users["qa_reader"][0]).status

    with ThreadPoolExecutor(max_workers=16) as pool:
        statuses = list(pool.map(log_in, range(32)))
    assert statuses == [302] * 32


def test_reads_keep_working_while_uploads_are_being_assembled(server):
    tag = uuid.uuid4().hex[:8]
    writer = server.login_as("qa_writer")
    reader = server.login_as("qa_reader")
    filename = f"busy_{tag}.bin"
    parts = [_payload(tag, n, size=256 * 1024) for n in range(8)]

    def upload():
        for number, data in enumerate(parts):
            assert (
                _send_chunk(writer, "fid_3_big", number, 8, filename, data).status
                == 200
            )

    def read_history():
        statuses = []
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            reply = reader.get(
                f"/api/versions/list?path={filename}",
                headers={"Accept": "application/json"},
            )
            statuses.append(reply.status)
        return statuses

    with ThreadPoolExecutor(max_workers=2) as pool:
        up, reads = pool.submit(upload), pool.submit(read_history)
        up.result(timeout=120)
        statuses = reads.result(timeout=120)
    assert statuses and set(statuses) == {200}, set(statuses)
    assert _wait_for_content(
        server.storage / filename, b"".join(parts)
    ), server.log_tail()
