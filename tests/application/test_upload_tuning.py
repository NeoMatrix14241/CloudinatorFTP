"""
The 5.41 upload settings against the REAL application, in a scratch copy started with

    BODY_TIMEOUT = 2, UPLOAD_TIMING_ENABLED = true, UPLOAD_CHUNKS_IN_MEMORY = true

  * chunks parsed in RAM and saved by the worker thread still assemble into exactly the bytes sent;
  * the timing log shows the stage names (and "(RAM)" for the in-memory parse) and the event-loop
    lag probe says it started with the first upload (needs the unbuffered child output of conftest,
    5.41);
  * a request body that stalls is cut off after BODY_TIMEOUT seconds, not after Quart's own 60
    (config.BODY_TIMEOUT reaches Quart through core.py). Quart raises "408 Request Timeout"; the
    /upload handler's generic `except Exception` turns it into a 500 whose text says "408 Request
    Timeout" (that is what the browser showed), so the test accepts a real 408 too, for the day
    the handler lets HTTP errors through.

One extra scratch server is started for this file (about as long as the first fixture of the run).
Nothing here waits on a fixed sleep except the deliberate stall of the last test: every other wait
is a bounded poll for the expected content or log line.
"""

import contextlib
import os
import socket
import time
import uuid

import pytest

BODY_TIMEOUT = 2


@pytest.fixture(scope="module")
def tuned(tmp_path_factory, scratch_tools):
    if not (scratch_tools.repo_root / "dev_server.py").exists():
        pytest.skip("dev_server.py not found next to tests/")
    real_hashes = scratch_tools.real_config_hashes()
    root = tmp_path_factory.mktemp("cloudinator_scratch_upload_tuning") / "app"
    port = scratch_tools.free_port()
    scratch_tools.build(
        root,
        port=port,
        config={
            "BODY_TIMEOUT": BODY_TIMEOUT,
            "UPLOAD_TIMING_ENABLED": True,
            "UPLOAD_CHUNKS_IN_MEMORY": True,
        },
    )
    violations = scratch_tools.paths_outside(root)
    if violations:
        pytest.fail(
            "scratch isolation check failed, nothing started:\n" + "\n".join(violations)
        )
    scratch_tools.seed_users(root)
    server = scratch_tools.start_server(root, port, real_hashes)
    try:
        yield server
    finally:
        scratch_tools.stop_server(server)


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


def _upload(server, parts):
    client = server.login_as("qa_writer")
    name = f"tuned_{uuid.uuid4().hex[:8]}.bin"
    file_id = f"fid_{uuid.uuid4().hex[:8]}_tuned"
    for number, data in enumerate(parts):
        reply = _chunk(client, file_id, number, len(parts), name, data)
        assert reply.status == 200, (number, reply.status, reply.text[:200])
    return name


def _wait_for_content(server, name, expected, seconds=60):
    target = server.storage / name
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if target.exists() and target.stat().st_size == len(expected):
            if target.read_bytes() == expected:
                return
        time.sleep(0.25)
    pytest.fail(
        f"{name} was not assembled correctly within {seconds} s\n{server.log_tail()}"
    )


def _wait_for_log(server, needle, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        text = server.log_path.read_text("utf-8", errors="replace")
        if needle in text:
            return text
        time.sleep(0.25)
    pytest.fail(
        f"{needle!r} did not appear in the server log within {seconds} s\n{server.log_tail()}"
    )


def test_chunks_parsed_in_memory_and_saved_by_the_worker_thread_assemble_exactly(
    tuned,
):
    # 600 kB each: above werkzeug's 500 kB spool limit, so the default parser would use a temp file
    parts = [os.urandom(600_000) for _ in range(3)]
    name = _upload(tuned, parts)
    _wait_for_content(tuned, name, b"".join(parts))


def test_the_timing_log_names_the_stages_and_the_ram_parse(tuned):
    parts = [os.urandom(100_000)]
    name = _upload(tuned, parts)
    _wait_for_content(tuned, name, parts[0])
    text = _wait_for_log(tuned, "upload chunk 1/1")
    line = next(line for line in text.splitlines() if "upload chunk 1/1" in line)
    for stage in ("role", "receive+parse (RAM)", "read+save"):
        assert stage in line, line
    assert "MB/s" in line, line


def test_the_event_loop_lag_probe_starts_with_the_first_upload(tuned):
    # no startup hook (tests/smoke.py check 5): the first /upload request starts the probe
    _upload(tuned, [os.urandom(10_000)])
    _wait_for_log(tuned, "event-loop lag probe started")


def test_a_stalled_request_body_is_cut_off_after_body_timeout(tuned):
    client = tuned.login_as("qa_writer")
    token = client.csrf_token()
    head = (
        "POST /upload HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{tuned.port}\r\n"
        f"CF-Connecting-IP: {client.ip}\r\n"
        f"Cookie: {client.cookie_header()}\r\n"
        f"X-CSRFToken: {token}\r\n"
        "Accept: application/json\r\n"
        "Content-Type: multipart/form-data; boundary=qa-stall\r\n"
        "Content-Length: 600000\r\n"
        "Connection: close\r\n\r\n"
    )
    started = time.monotonic()
    reply = b""
    with socket.create_connection(("127.0.0.1", tuned.port), timeout=30) as sock:
        sock.sendall(head.encode("ascii") + b"--qa-stall\r\n")  # then nothing more
        # Read to the end of the answer. The server closes the connection while body bytes are
        # still unsent, which on Windows can surface as a reset after the answer has arrived.
        with contextlib.suppress(ConnectionResetError):
            while True:
                piece = sock.recv(4096)
                if not piece:
                    break
                reply += piece
    elapsed = time.monotonic() - started
    status_line = reply.split(b"\r\n", 1)[0].decode("latin-1")
    cut_off = " 408 " in status_line or (
        " 500 " in status_line and b"408 Request Timeout" in reply
    )
    assert cut_off, f"{status_line!r}\n{reply[-300:]!r}\n{tuned.log_tail()}"
    assert (
        BODY_TIMEOUT - 0.5 <= elapsed < 20
    ), f"cut off after {elapsed:.1f} s (BODY_TIMEOUT is {BODY_TIMEOUT} s, Quart's own is 60 s)"
    _wait_for_log(tuned, "408 Request Timeout")
