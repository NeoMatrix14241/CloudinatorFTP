"""
Performance baselines (5.40): a few measurements against the REAL application started from a
scratch copy, each with a deliberately LOOSE upper bound.

The bounds are not a promise of speed. They catch an order-of-magnitude regression (a chunk
assembly that suddenly reads the whole file twice, a login that takes seconds, a read route that
holds a lock). Every measured number is printed and recorded with `record_property`, so the JUnit
XML of the nightly run (artifact `test-results`) holds the trend, and the bounds can be tightened
once a few weeks of nightly numbers exist. Machine speed varies a lot (a shared CI runner, a
laptop on battery, Windows with antivirus), which is why nothing here is tight.

OPT-IN (CLOUDINATOR_SLOW_TESTS=1, set by the nightly workflow):

    CLOUDINATOR_SLOW_TESTS=1 python -m pytest tests/performance/test_baselines.py -q -s

5.41 adds the numbers the upload-speed investigation needed: chunks of the PRODUCTION size (10 MB,
one client and four at once) and a download of a 32 MB file. The bounds stay loose on purpose; the
numbers are what matters. Compare them with `python quart_upload_reference.py` on the same machine
(docs/TESTING_STRATEGY.md, section 16).

Not covered: large files (the 85 s throttled download is test_slow_download.py), many thousands of
files in one folder, a browser (parallel files, the source file read from the same disk), the
Version Engine, and HTTP/2 or HTTP/3 (the scratch server is plain HTTP/1.1).
"""

import hashlib
import os
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = [
    pytest.mark.performance,
    pytest.mark.skipif(
        os.environ.get("CLOUDINATOR_SLOW_TESTS") != "1",
        reason="slow and timing-sensitive: set CLOUDINATOR_SLOW_TESTS=1 to run",
    ),
]

JSON_ACCEPT = {"Accept": "application/json"}


@pytest.fixture(scope="module")
def server(scratch_server):
    return scratch_server


def _report(record_property, name, value, unit):
    print(f"[baseline] {name}: {value:.3f} {unit}")
    record_property(name, f"{value:.3f} {unit}")


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


def test_a_chunked_upload_of_24_mb_is_assembled_in_reasonable_time(
    server, record_property
):
    client = server.login_as("qa_writer")
    name = f"baseline_{uuid.uuid4().hex[:8]}.bin"
    chunk_size, chunks = 2 * 1024 * 1024, 12
    parts = [os.urandom(chunk_size) for _ in range(chunks)]
    expected = hashlib.sha256(b"".join(parts)).hexdigest()

    started = time.monotonic()
    for number, data in enumerate(parts):
        reply = _chunk(client, "fid_1_big", number, chunks, name, data)
        assert reply.status == 200, (number, reply.status)
    sent = time.monotonic() - started

    target = server.storage / name
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if target.exists() and target.stat().st_size == chunk_size * chunks:
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest == expected:
                break
        time.sleep(0.25)
    else:
        pytest.fail(
            f"the 24 MB file was not assembled correctly within 120 s\n{server.log_tail()}"
        )
    total = time.monotonic() - started

    megabytes = chunk_size * chunks / (1024 * 1024)
    _report(record_property, "upload_send_seconds", sent, "s")
    _report(record_property, "upload_until_published_seconds", total, "s")
    _report(record_property, "upload_mb_per_second", megabytes / total, "MB/s")
    assert (
        total < 120
    ), f"24 MB took {total:.1f} s from the first chunk to the published file"


MB = 1024 * 1024


def _wait_for_file(server, name, expected_sha256, size, seconds=240):
    """Bounded poll until the published file has the expected size and content."""
    target = server.storage / name
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if target.exists() and target.stat().st_size == size:
            if hashlib.sha256(target.read_bytes()).hexdigest() == expected_sha256:
                return
        time.sleep(0.25)
    pytest.fail(
        f"{name} was not published correctly within {seconds} s\n{server.log_tail()}"
    )


def _upload_parts(client, name, parts):
    """Send the chunks one after the other (what the browser does for ONE file)."""
    file_id = f"fid_{uuid.uuid4().hex[:8]}_perf"
    for number, data in enumerate(parts):
        reply = _chunk(client, file_id, number, len(parts), name, data)
        assert reply.status == 200, (name, number, reply.status)


def test_a_chunked_upload_with_production_size_chunks_one_client(
    server, record_property
):
    client = server.login_as("qa_writer")
    name = f"baseline10_{uuid.uuid4().hex[:8]}.bin"
    parts = [os.urandom(10 * MB) for _ in range(3)]  # 30 MB in 3 chunks of 10 MB
    expected = hashlib.sha256(b"".join(parts)).hexdigest()

    started = time.monotonic()
    _upload_parts(client, name, parts)
    sent = time.monotonic() - started
    _wait_for_file(server, name, expected, 30 * MB)
    total = time.monotonic() - started

    _report(record_property, "upload10_send_seconds", sent, "s")
    _report(record_property, "upload10_until_published_seconds", total, "s")
    _report(record_property, "upload10_send_mb_per_second", 30 / sent, "MB/s")
    assert total < 180, f"30 MB in 10 MB chunks took {total:.1f} s"


def test_four_clients_upload_production_size_chunks_at_the_same_time(
    server, record_property
):
    """Four browsers (or four files of one browser) at once: 4 x 20 MB in chunks of 10 MB."""
    jobs = []
    for _ in range(4):
        parts = [os.urandom(10 * MB) for _ in range(2)]
        jobs.append(
            (
                server.login_as("qa_writer"),
                f"baseline10x4_{uuid.uuid4().hex[:8]}.bin",
                parts,
                hashlib.sha256(b"".join(parts)).hexdigest(),
            )
        )

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda job: _upload_parts(job[0], job[1], job[2]), jobs))
    sent = time.monotonic() - started
    for _client, name, _parts, digest in jobs:
        _wait_for_file(server, name, digest, 20 * MB)
    total = time.monotonic() - started

    _report(record_property, "upload10x4_send_seconds", sent, "s")
    _report(record_property, "upload10x4_until_published_seconds", total, "s")
    _report(record_property, "upload10x4_send_mb_per_second", 80 / sent, "MB/s")
    assert total < 300, f"4 x 20 MB in 10 MB chunks took {total:.1f} s"


def test_a_download_of_32_mb_arrives_intact_in_reasonable_time(server, record_property):
    name = f"baseline_download_{uuid.uuid4().hex[:8]}.bin"
    data = os.urandom(32 * MB)
    (server.storage / name).write_bytes(data)
    client = server.login_as("qa_reader")

    started = time.monotonic()
    reply = client.get(f"/download/{name}")
    elapsed = time.monotonic() - started

    assert reply.status == 200, reply.status
    assert hashlib.sha256(reply.body).hexdigest() == hashlib.sha256(data).hexdigest()
    _report(record_property, "download_32mb_seconds", elapsed, "s")
    _report(record_property, "download_mb_per_second", 32 / elapsed, "MB/s")
    assert elapsed < 120, f"32 MB took {elapsed:.1f} s to download"


def test_a_login_takes_well_under_two_seconds(server, record_property):
    timings = []
    for _ in range(10):
        client = server.client()
        started = time.monotonic()
        assert client.login("qa_reader", server.users["qa_reader"][0]).status == 302
        timings.append(time.monotonic() - started)
    median = statistics.median(timings)
    _report(record_property, "login_median_seconds", median, "s")
    _report(record_property, "login_max_seconds", max(timings), "s")
    assert median < 2.0, f"median login {median:.2f} s"


def test_a_read_request_answers_in_well_under_half_a_second(server, record_property):
    client = server.login_as("qa_reader")
    path = "/api/versions/list?path=baseline_missing.txt"
    timings = []
    for _ in range(100):
        started = time.monotonic()
        assert client.get(path, headers=JSON_ACCEPT).status == 200
        timings.append(time.monotonic() - started)
    timings.sort()
    p95 = timings[int(len(timings) * 0.95) - 1]
    _report(record_property, "read_median_seconds", statistics.median(timings), "s")
    _report(record_property, "read_p95_seconds", p95, "s")
    assert p95 < 0.5, f"p95 {p95:.3f} s"


def test_eight_readers_at_once_all_get_correct_answers_quickly(server, record_property):
    clients = [server.login_as("qa_reader") for _ in range(8)]

    def read_many(client):
        return [
            client.get(
                "/api/versions/list?path=baseline_missing.txt", headers=JSON_ACCEPT
            ).status
            for _ in range(25)
        ]

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(read_many, clients))
    elapsed = time.monotonic() - started
    _report(record_property, "parallel_200_requests_seconds", elapsed, "s")
    assert all(set(statuses) == {200} for statuses in results)
    assert elapsed < 30, f"200 requests from 8 clients took {elapsed:.1f} s"
