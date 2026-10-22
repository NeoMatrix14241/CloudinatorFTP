"""
End-to-end proof that a download that takes longer than 60 seconds arrives complete.

A 200 MB file is read by a client throttled to about 2.5 MB/s (roughly what a tunnel moves), so the
transfer lasts ~80 s. With Quart's default 60 s RESPONSE_TIMEOUT the server cuts the connection
at about 150 MB (CLAUDE.md part 61). Slow, so it only runs on request:

    CLOUDINATOR_SLOW_TESTS=1 python tests/qa.py layer performance
"""

import os
import time
import urllib.request

import pytest

pytestmark = [
    pytest.mark.performance,
    pytest.mark.skipif(
        os.environ.get("CLOUDINATOR_SLOW_TESTS") != "1",
        reason="slow (~85 s): set CLOUDINATOR_SLOW_TESTS=1 to run",
    ),
]

SIZE = 200 * 1024 * 1024


@pytest.mark.timeout(300)
def test_a_download_longer_than_a_minute_arrives_complete(scratch_server):
    big = scratch_server.storage / "slow_download.bin"
    with open(big, "wb") as handle:
        handle.truncate(SIZE)
    client = scratch_server.login_as("qa_writer")
    request = urllib.request.Request(
        scratch_server.base_url + "/download/slow_download.bin",
        headers={"Cookie": client.cookie_header(), "CF-Connecting-IP": client.ip},
    )
    received, started = 0, time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=120) as reply:
            promised = int(reply.headers["Content-Length"])
            while True:
                chunk = reply.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                time.sleep(0.1)  # about 2.5 MB/s
    finally:
        big.unlink(missing_ok=True)
    seconds = time.monotonic() - started
    assert promised == SIZE
    assert received == promised, f"cut off at {received >> 20} of {promised >> 20} MB"
    assert seconds > 65, "the transfer must outlast the 60 s default to prove anything"
