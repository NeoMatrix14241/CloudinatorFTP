"""
The pieces of an unfinished upload (<storage>/.chunks/<key>/0, 1, ...) are not versioned (5.41).

`scratch_server_with_versions` tracks the WHOLE scratch storage folder, so before 5.41 the live
Version Engine hashed and copied every 10 MB piece of every upload. The test leaves an upload
unfinished (its pieces stay under .chunks/), creates an ordinary control file, waits until the
engine has versioned the control file (so it has certainly scanned the folder since the pieces
were written) and then asserts that no tracked path contains `.chunks`.

OPT-IN (CLOUDINATOR_SLOW_TESTS=1): the engine is its own process and polls every few seconds.
"""

import contextlib
import os
import sqlite3
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CLOUDINATOR_SLOW_TESTS") != "1",
    reason="slow and timing-sensitive: set CLOUDINATOR_SLOW_TESTS=1 to run",
)


def _tracked_paths(db_file, pattern):
    """Display paths in the engine's `files` table that match a LIKE pattern (read-only)."""
    conn = sqlite3.connect(f"{db_file.as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT path FROM files WHERE path LIKE ?", (pattern,)
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


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


def test_the_pieces_of_an_unfinished_upload_are_not_versioned(
    scratch_server_with_versions,
):
    server = scratch_server_with_versions
    client = server.login_as("qa_writer")
    name = f"unfinished_{uuid.uuid4().hex[:8]}.bin"
    file_id = f"fid_{uuid.uuid4().hex[:8]}_ve"
    for number in (
        0,
        1,
    ):  # 2 of 3 pieces: the upload never completes, so nothing assembles
        reply = _chunk(client, file_id, number, 3, name, os.urandom(300_000))
        assert reply.status == 200, (number, reply.status)

    chunks_root = server.storage / ".chunks"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        pieces = list(chunks_root.glob("*/0")) if chunks_root.is_dir() else []
        if pieces:
            break
        time.sleep(0.25)
    else:
        pytest.fail(
            f"the uploaded pieces never appeared under .chunks/\n{server.log_tail()}"
        )

    control = f"control_{uuid.uuid4().hex[:8]}.txt"
    (server.storage / control).write_text("an ordinary file", encoding="utf-8")

    db_file = server.root / "data" / "db" / "version_engine.sqlite3"
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        found = []
        # the database is created by the engine process; until then, or while it is busy, the
        # read fails and the poll simply tries again
        with contextlib.suppress(sqlite3.Error, OSError):
            found = _tracked_paths(db_file, f"%{control}")
        if found:
            break
        time.sleep(1)
    else:
        pytest.fail(
            f"the engine never versioned the control file {control}\n{server.log_tail()}"
        )

    assert _tracked_paths(db_file, "%.chunks%") == []
