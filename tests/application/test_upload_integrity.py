"""
Chunked upload integrity: what arrives must be exactly what was sent, and one user's chunks must
never end up in another user's file. Against the REAL application, from a scratch copy.

The front end names an upload  fid_<counter>_<file size>_<random hex>  (static/js/index.js,
generateFileId): the counter restarts at 1 on every page load, so the browser's id alone can repeat
between users. The SERVER therefore keys every upload by the session as well
(routes/uploads.py, _chunk_key; CLAUDE.md 5.16), and starts the assembly when every chunk is on
disk, whatever the order they arrived in. The tests below send the OLD short id on purpose: any
safe id is accepted, and it is the case that used to collide.
"""

import time
import uuid

import pytest

pytestmark = pytest.mark.application


@pytest.fixture
def server(scratch_server):
    return scratch_server


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


def _wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.25)
    return predicate()


def test_a_three_chunk_upload_is_assembled_in_order(server):
    client = server.login_as("qa_writer")
    name = f"ordered_{uuid.uuid4().hex[:8]}.bin"
    parts = [b"first-", b"second-", b"third"]
    for number in (0, 1, 2):
        assert _chunk(client, "fid_1_18", number, 3, name, parts[number]).status == 200
    target = server.storage / name
    assert _wait_for(lambda: target.exists() and target.read_bytes() == b"".join(parts))


def test_an_upload_whose_last_chunk_arrives_early_never_publishes_a_wrong_file(server):
    # Whatever the order, the file is published only when the last MISSING chunk has arrived,
    # and never with wrong bytes (the next test checks the result once everything is there).
    client = server.login_as("qa_writer")
    name = f"early_{uuid.uuid4().hex[:8]}.bin"
    parts = [b"AAAA", b"BBBB", b"CCCC"]
    for number in (2, 0, 1):
        assert _chunk(client, "fid_2_12", number, 3, name, parts[number]).status == 200
        time.sleep(1)
    time.sleep(5)
    target = server.storage / name
    assert not target.exists() or target.read_bytes() == b"".join(parts)


def test_chunks_arriving_out_of_order_still_assemble_correctly(server):
    client = server.login_as("qa_writer")
    name = f"shuffled_{uuid.uuid4().hex[:8]}.bin"
    parts = [b"AAAA", b"BBBB", b"CCCC"]
    for number in (2, 0, 1):
        assert _chunk(client, "fid_3_12", number, 3, name, parts[number]).status == 200
        time.sleep(1)
    target = server.storage / name
    assert _wait_for(lambda: target.exists() and target.read_bytes() == b"".join(parts))


def test_two_users_with_the_same_upload_id_do_not_mix_their_chunks(server):
    # Same id: the short counter + size form (e.g. two 8-byte files) that two browsers can produce.
    name, password = server.make_user("readwrite")
    alice, bob = server.login_as("qa_writer"), server.client()
    assert bob.login(name, password).status == 302
    tag = uuid.uuid4().hex[:8]
    file_id = "fid_1_8"
    _chunk(alice, file_id, 0, 2, f"alice_{tag}.txt", b"AAAA")
    _chunk(bob, file_id, 0, 2, f"bob_{tag}.txt", b"BBBB")
    _chunk(alice, file_id, 1, 2, f"alice_{tag}.txt", b"aaaa")
    target = server.storage / f"alice_{tag}.txt"
    assert _wait_for(
        lambda: target.exists() and target.read_bytes() == b"AAAAaaaa"
    ), f"Alice's file is wrong or missing: {target.read_bytes() if target.exists() else None!r}"
    # Bob finishes his own file: it must hold his bytes only.
    _chunk(bob, file_id, 1, 2, f"bob_{tag}.txt", b"bbbb")
    bobs = server.storage / f"bob_{tag}.txt"
    assert _wait_for(
        lambda: bobs.exists() and bobs.read_bytes() == b"BBBBbbbb"
    ), f"Bob's file is wrong or missing: {bobs.read_bytes() if bobs.exists() else None!r}"
