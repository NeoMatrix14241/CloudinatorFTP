"""
Path containment: nothing a client sends may read, write, delete, share or create anything
outside the storage root, against the REAL application started from a scratch copy.

Layout built per test, next to the storage root ("<scratch>/data/storage"):
    data/outside_<tag>.txt      a secret in the parent folder
    data/storage_<tag>/         a SIBLING whose name starts with the storage root's name
    data/victim_<tag>/          a folder that must never be deleted
    data/storage/ok_<tag>.txt   a normal file inside the root

Every test states the desired behaviour. Two holes were found here and fixed in 5.10/5.11
(CLAUDE.md part 60); these tests keep them closed:
  1. storage.is_safe_path() used startswith(), so a sibling folder named like the root plus a
     suffix (storage -> storage_backup) counted as inside the root;
  2. file_id (upload, cancel_upload, cleanup_chunks) was joined into .chunks/ unchecked.
"""

import io
import json
import os
import shutil
import time
import uuid
import zipfile
from types import SimpleNamespace
from urllib.parse import quote

import pytest

pytestmark = pytest.mark.application

RW = "qa_writer"
JSON_HEADERS = {"Accept": "application/json"}
PARENT_SECRET = "TOP-SECRET-PARENT"
SIBLING_SECRET = "TOP-SECRET-SIBLING"


@pytest.fixture
def server(scratch_server):
    return scratch_server


@pytest.fixture
def world(server):
    tag = uuid.uuid4().hex[:8]
    data = server.root / "data"
    outside = data / f"outside_{tag}.txt"
    outside.write_text(PARENT_SECRET, encoding="utf-8")
    sibling = data / f"storage_{tag}"
    sibling.mkdir()
    (sibling / "secret.txt").write_text(SIBLING_SECRET, encoding="utf-8")
    victim = data / f"victim_{tag}"
    victim.mkdir()
    (victim / "important.txt").write_text("VICTIM", encoding="utf-8")
    inside = server.storage / f"ok_{tag}.txt"
    inside.write_text("OK-INSIDE", encoding="utf-8")
    (server.storage / ".chunks").mkdir(
        exist_ok=True
    )  # exists while any upload is running
    ns = SimpleNamespace(
        tag=tag,
        data=data,
        outside=outside,
        sibling=sibling,
        sibling_rel=f"../storage_{tag}",
        victim=victim,
        inside=inside,
        storage=server.storage,
        client=server.login_as(RW),
    )
    yield ns
    shutil.rmtree(sibling, ignore_errors=True)
    shutil.rmtree(victim, ignore_errors=True)
    shutil.rmtree(data / f"escape_{tag}", ignore_errors=True)
    outside.unlink(missing_ok=True)


def _leaked(reply):
    return b"TOP-SECRET" in reply.body


def _reveals_nothing(reply):
    """A 200 that only says 'there is nothing at that path inside the root' (for example a
    backslash name on Linux, where it is an ordinary file name, not a separator)."""
    try:
        data = reply.json()
    except ValueError:
        return False
    if "exists" in data:
        return data["exists"] is False
    if "file_count" in data:
        return not (data["file_count"] or data["dir_count"] or data["total_size"])
    if "tracked" in data:
        return data["tracked"] is False
    return False


def _zip_names(reply):
    try:
        return zipfile.ZipFile(io.BytesIO(reply.body)).namelist()
    except zipfile.BadZipFile:
        return []


def _settle(seconds=2.5):
    time.sleep(seconds)  # bulk jobs and chunk clean-up run in background threads


def _wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.25)
    return predicate()


# ---------------------------------------------------------------------------- traversal (blocked)
READ_ROUTES = [
    "/download/{}",
    "/view/{}",
    "/api/files/{}",
    "/api/dir_info/{}",
    "/image_preview/{}",
    "/image_info/{}",
    "/office_preview/{}",
    "/archive_preview/{}",
    "/hls_start/{}",
    "/api/exists?path={}",
    "/api/versions/list?path={}",
]

TRAVERSAL = {
    "dotdot": lambda w: f"../outside_{w.tag}.txt",
    "encoded_dots": lambda w: f"%2e%2e/outside_{w.tag}.txt",
    "encoded_slash": lambda w: f"..%2foutside_{w.tag}.txt",
    "encoded_both": lambda w: f"%2e%2e%2foutside_{w.tag}.txt",
    "backslash": lambda w: f"..%5coutside_{w.tag}.txt",
    "double_encoded": lambda w: f"%252e%252e%252foutside_{w.tag}.txt",
    "four_dots": lambda w: f"....//outside_{w.tag}.txt",
    "deep": lambda w: f"a/b/../../../outside_{w.tag}.txt",
    "absolute": lambda w: quote(str(w.outside), safe="/"),
}


@pytest.mark.parametrize("route", READ_ROUTES)
@pytest.mark.parametrize("payload", sorted(TRAVERSAL))
def test_traversal_out_of_the_root_is_refused(world, route, payload):
    reply = world.client.get(
        route.format(TRAVERSAL[payload](world)), headers=JSON_HEADERS
    )
    assert not _leaked(reply)
    assert reply.status != 200 or _reveals_nothing(reply), (
        reply.status,
        reply.text[:100],
    )


def test_a_symlink_pointing_outside_is_not_followed(world):
    link = world.storage / f"link_{world.tag}"
    try:
        os.symlink(world.outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    reply = world.client.get(f"/download/{link.name}")
    assert not _leaked(reply) and reply.status != 200


def test_a_symlinked_folder_pointing_outside_is_not_followed(world):
    link = world.storage / f"dirlink_{world.tag}"
    try:
        os.symlink(world.victim, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    reply = world.client.get(
        f"/download/{link.name}/important.txt", headers=JSON_HEADERS
    )
    assert b"VICTIM" not in reply.body and reply.status != 200


# ---------------------------------------------------------------------------- is_safe_path itself
SAFE_CASES = ["", ".", "a", "a/b", "a/../b", "../storage", "a/b/../../c.txt"]
UNSAFE_CASES = ["..", "../x", "a/../../x", "../../etc", "a/b/../../../x"]


def _is_safe_path(server, cases):
    code = (
        "import json\n"
        "from storage import is_safe_path\n"
        "cases = json.loads(sys.argv[1])\n"
        "print('RESULT ' + json.dumps({c: bool(is_safe_path(c)) for c in cases}))\n"
    )
    out = server.db(code, json.dumps(cases))
    line = next(x for x in out.splitlines() if x.startswith("RESULT "))
    return json.loads(line[len("RESULT ") :])


def test_is_safe_path_accepts_paths_inside_the_root(server):
    result = _is_safe_path(server, SAFE_CASES)
    assert all(result.values()), result


def test_is_safe_path_rejects_paths_outside_the_root(server):
    result = _is_safe_path(server, UNSAFE_CASES + [str(server.root / "data")])
    assert not any(result.values()), result


def test_is_safe_path_rejects_a_sibling_that_shares_the_roots_name_prefix(server):
    case = "../storage_backup/secret.txt"
    assert _is_safe_path(server, [case])[case] is False


def test_a_folder_that_merely_looks_like_the_root_name_is_fine_inside_the_root(world):
    inner = world.storage / "storage" / "storage_inner"
    inner.mkdir(parents=True)
    (inner / "note.txt").write_text("inside", encoding="utf-8")
    reply = world.client.get("/download/storage/storage_inner/note.txt")
    assert reply.status == 200 and reply.body == b"inside"


# ---------------------------------------------------------------------------- sibling: read
@pytest.mark.parametrize("route", ["/download/{}", "/view/{}"])
def test_sibling_files_cannot_be_read(world, route):
    reply = world.client.get(route.format(f"{world.sibling_rel}/secret.txt"))
    assert not _leaked(reply) and reply.status != 200


@pytest.mark.parametrize(
    "route", ["/api/files/{}", "/api/dir_info/{}", "/api/exists?path={}"]
)
def test_sibling_folders_cannot_be_listed_or_probed(world, route):
    reply = world.client.get(route.format(world.sibling_rel), headers=JSON_HEADERS)
    assert reply.status != 200, reply.text[:120]


def test_a_sibling_file_cannot_be_shared_publicly(server, world):
    created = world.client.api(
        "POST", "/api/share", json_body={"path": f"{world.sibling_rel}/secret.txt"}
    )
    assert created.status != 200, created.text[:120]
    token = created.json().get("token", "")
    anonymous = server.client().get(f"/shared/{token}/download")
    assert not _leaked(anonymous)


def test_a_sibling_file_cannot_be_zipped(world):
    reply = world.client.api(
        "POST",
        "/bulk-download",
        json_body={"paths": [f"{world.sibling_rel}/secret.txt"]},
    )
    assert "secret.txt" not in _zip_names(reply)


def test_a_sibling_file_cannot_be_copied_into_the_storage(world):
    world.client.api(
        "POST",
        "/bulk_copy",
        json_body={"paths": [f"{world.sibling_rel}/secret.txt"], "destination": ""},
    )
    _settle()
    assert not (world.storage / "secret.txt").exists()


# ---------------------------------------------------------------------------- sibling: write
def test_a_sibling_file_cannot_be_deleted(world):
    world.client.api(
        "POST", "/delete", fields={"target_path": f"{world.sibling_rel}/secret.txt"}
    )
    assert (world.sibling / "secret.txt").exists()


def test_a_sibling_file_cannot_be_bulk_deleted(world):
    world.client.api(
        "POST",
        "/bulk_delete",
        json_body={"paths": [f"{world.sibling_rel}/secret.txt"]},
    )
    assert (world.sibling / "secret.txt").exists()


def test_a_sibling_file_cannot_be_renamed(world):
    world.client.api(
        "POST",
        "/rename",
        json_body={
            "old_path": f"{world.sibling_rel}/secret.txt",
            "new_name": "renamed.txt",
        },
    )
    assert (world.sibling / "secret.txt").exists()
    assert not (world.sibling / "renamed.txt").exists()


def test_a_folder_cannot_be_created_in_a_sibling(world):
    world.client.api(
        "POST", "/mkdir", fields={"path": world.sibling_rel, "foldername": "made"}
    )
    assert not (world.sibling / "made").exists()


def test_an_upload_cannot_target_a_sibling(world):
    reply = world.client.api(
        "POST",
        "/upload",
        fields={
            "file_id": uuid.uuid4().hex,
            "chunk_num": "0",
            "total_chunks": "1",
            "filename": "dropped.txt",
            "dest_path": world.sibling_rel,
        },
        files={"chunk": ("blob", b"ATTACKER DATA")},
    )
    assert reply.status == 400, (reply.status, reply.text[:100])
    assert not (world.sibling / "dropped.txt").exists()


def test_files_cannot_be_moved_into_a_sibling(world):
    reply = world.client.api(
        "POST",
        "/bulk_move",
        json_body={"paths": [world.inside.name], "destination": world.sibling_rel},
    )
    _settle()
    assert reply.status == 400, (reply.status, reply.text[:100])
    assert world.inside.exists()
    assert not (world.sibling / world.inside.name).exists()


# ---------------------------------------------------------------------------- upload chunk ids
def _chunk(world, file_id, chunk_num=0, total_chunks=2):
    return world.client.api(
        "POST",
        "/upload",
        fields={
            "file_id": file_id,
            "chunk_num": str(chunk_num),
            "total_chunks": str(total_chunks),
            "filename": "part.txt",
            "dest_path": "",
        },
        files={"chunk": ("blob", b"CHUNK")},
    )


@pytest.mark.parametrize("style", ["relative", "absolute"])
def test_cancel_upload_cannot_delete_outside_the_chunk_area(world, style):
    file_id = f"../../victim_{world.tag}" if style == "relative" else str(world.victim)
    world.client.api(
        "POST", "/cancel_upload", json_body={"file_id": file_id, "filename": "x"}
    )
    _settle()
    assert world.victim.exists() and (world.victim / "important.txt").exists()


@pytest.mark.parametrize("style", ["relative", "absolute"])
def test_cleanup_chunks_cannot_delete_outside_the_chunk_area(world, style):
    file_id = f"../../victim_{world.tag}" if style == "relative" else str(world.victim)
    world.client.api("POST", "/cleanup_chunks", json_body={"file_id": file_id})
    _settle()
    assert world.victim.exists() and (world.victim / "important.txt").exists()


def test_upload_cannot_write_chunks_outside_the_chunk_area(world):
    _chunk(world, f"../../escape_{world.tag}")
    assert not (world.data / f"escape_{world.tag}").exists()


# ---------------------------------------------------------------------------- legitimate use
@pytest.mark.parametrize(
    "file_id",
    [uuid.uuid4().hex, "fid_1_104857600", "fid_27_0", "upload_42-abc.def"],
    ids=["hex", "frontend-style", "frontend-empty-file", "dots-and-dashes"],
)
def test_a_normal_chunked_upload_still_works(world, file_id):
    name = f"up_{world.tag}_{abs(hash(file_id)) % 1000}.txt"
    reply = world.client.api(
        "POST",
        "/upload",
        fields={
            "file_id": file_id,
            "chunk_num": "0",
            "total_chunks": "1",
            "filename": name,
            "dest_path": "",
        },
        files={"chunk": ("blob", b"legit upload")},
    )
    assert reply.status == 200, (reply.status, reply.text[:100])
    target = world.storage / name
    assert _wait_for(lambda: target.exists() and target.read_bytes() == b"legit upload")


def test_a_normal_upload_into_a_subfolder_still_works(world):
    (world.storage / f"sub_{world.tag}").mkdir()
    reply = world.client.api(
        "POST",
        "/upload",
        fields={
            "file_id": uuid.uuid4().hex,
            "chunk_num": "0",
            "total_chunks": "1",
            "filename": "in_sub.txt",
            "dest_path": f"sub_{world.tag}",
        },
        files={"chunk": ("blob", b"in a subfolder")},
    )
    assert reply.status == 200
    target = world.storage / f"sub_{world.tag}" / "in_sub.txt"
    assert _wait_for(
        lambda: target.exists() and target.read_bytes() == b"in a subfolder"
    )


def test_normal_file_operations_inside_the_root_still_work(world):
    client = world.client
    assert client.get(f"/download/{world.inside.name}").body == b"OK-INSIDE"
    renamed = client.api(
        "POST",
        "/rename",
        json_body={
            "old_path": world.inside.name,
            "new_name": f"renamed_{world.tag}.txt",
        },
    )
    assert renamed.status == 200
    assert (world.storage / f"renamed_{world.tag}.txt").exists()
    deleted = client.api(
        "POST", "/delete", fields={"target_path": f"renamed_{world.tag}.txt"}
    )
    assert deleted.status == 302
    assert not (world.storage / f"renamed_{world.tag}.txt").exists()
