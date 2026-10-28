"""
Version history of the REAL code (version_history.py on top of version_engine.py): what a
restore, a download and a delete really return, and what they must refuse.

The scratch server runs with the version engine OFF (conftest.py), so these tests do not go
through HTTP. They run the real modules inside a SCRATCH COPY of the project (own storage, own
versions folder, own version database) with the same helper the other tests use for the scratch
database (`run_in_scratch`): no worker process, no watcher, no timing; a snapshot is taken by
calling `Engine.snapshot_file()` directly, which is exactly what the worker does per file.
Every snippet first asserts that its storage, database and version folders are inside the
scratch copy, so a wrong configuration can never touch real versions.

What is NOT covered here: the HTTP routes /api/versions/* (the role gates are in
test_authorization.py) and the engine's background threads.
"""

import json
import re
import textwrap
import uuid

import pytest

pytestmark = pytest.mark.application

PRELUDE = textwrap.dedent("""
    import json, os, random, sys, time
    import config
    cwd = os.path.abspath(os.getcwd())
    for _d in (config.ROOT_DIR, config.DB_DIR, config.VERSION_STORAGE_DIR):
        assert os.path.abspath(_d).startswith(cwd), "NOT inside the scratch copy: " + _d
    config.VERSION_SMALL_FILE_THRESHOLD = 1024 * 1024
    config.VERSION_CHUNK_SIZE = 1024 * 1024
    config.VERSION_RETENTION_ENABLED = False
    import version_history as vh
    vh.init()
    eng = vh._get_engine()
    ROOT = config.ROOT_DIR
    TAG = sys.argv[1]

    def put(rel, data):
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def snap(path):
        version_id = eng.snapshot_file(path, source="qa")
        time.sleep(0.05)  # distinct created_at even on a coarse clock
        return version_id

    def read(path):
        with open(path, "rb") as f:
            return f.read()

    def out(**kw):
        print("RESULT=" + json.dumps(kw, default=str))
    """)


@pytest.fixture(scope="module")
def lab(scratch_tools, tmp_path_factory):
    root = tmp_path_factory.mktemp("version_lab") / "app"
    scratch_tools.build(root, port=scratch_tools.free_port())
    assert scratch_tools.paths_outside(root) == []
    return root


@pytest.fixture(scope="module")
def run(lab, scratch_tools):
    def _run(body):
        tag = uuid.uuid4().hex[:8]
        code = PRELUDE + textwrap.dedent(body)
        stdout = scratch_tools.run_in_scratch(lab, code, tag)
        lines = [ln for ln in stdout.splitlines() if ln.startswith("RESULT=")]
        assert lines, "the snippet printed no RESULT line:\n" + stdout[-800:]
        result = json.loads(lines[-1][len("RESULT=") :])
        result["tag"] = tag
        return result

    return _run


# ---------------------------------------------------------------------------- restore
def test_restore_returns_the_chosen_version_and_never_touches_the_live_file(run):
    r = run("""
        p = put(f"vh_{TAG}/doc.txt", b"first-content")
        v1 = snap(p)
        put(f"vh_{TAG}/doc.txt", b"second-content!!")
        v2 = snap(p)
        ok, msg, rel = vh.restore(p, v1)
        out(v1=v1, v2=v2, ok=ok, msg=msg, rel=rel,
            recovered=read(os.path.join(ROOT, rel)).decode(),
            live=read(p).decode(), ids_differ=(v1 != v2))
        """)
    assert r["ok"] and r["ids_differ"] and r["v1"] and r["v2"]
    assert r["recovered"] == "first-content"
    assert r["live"] == "second-content!!"
    pattern = rf"^\.recovered/vh_{r['tag']}/doc__\d{{4}}-\d{{2}}-\d{{2}}_\d{{6}}__v{r['v1']}\.txt$"
    assert re.match(pattern, r["rel"]), r["rel"]


def test_restoring_the_same_version_twice_lands_on_the_same_path(run):
    r = run("""
        p = put(f"vh_{TAG}/again.bin", b"\\x00\\x01\\x02 binary \\xff")
        v = snap(p)
        first = vh.restore(p, v)
        second = vh.restore(p, v)
        out(first=first, second=second,
            data_ok=read(os.path.join(ROOT, second[2])) == read(p))
        """)
    assert r["first"][0] and r["second"][0]
    assert r["first"][2] == r["second"][2]
    assert r["data_ok"]


def test_a_deleted_file_can_be_recovered_from_its_history(run):
    r = run("""
        p = put(f"vh_{TAG}/precious.txt", b"must survive the delete")
        v = snap(p)
        os.remove(p)
        ok, msg, rel = vh.restore(p, v)
        out(ok=ok, rel=rel, recovered=read(os.path.join(ROOT, rel)).decode(),
            live_exists=os.path.exists(p))
        """)
    assert r["ok"] and r["recovered"] == "must survive the delete"
    assert r["live_exists"] is False  # restore never recreates the original


def test_an_unchanged_file_is_not_captured_twice(run):
    r = run("""
        p = put(f"vh_{TAG}/same.txt", b"unchanged")
        first = snap(p)
        second = snap(p)
        out(first=first, second=second, count=len(vh.get_history(p)))
        """)
    assert r["first"] and r["second"] is None and r["count"] == 1


def test_a_multi_chunk_file_restores_byte_for_byte(run):
    r = run("""
        config.VERSION_SMALL_FILE_THRESHOLD = 1000
        config.VERSION_CHUNK_SIZE = 4096
        data = random.Random(7).randbytes(3 * 4096 + 123)
        p = put(f"vh_{TAG}/big.bin", data)
        v = snap(p)
        info = eng.get_version(v)
        parts = eng._connect().execute(
            "SELECT COUNT(*) FROM version_objects WHERE version_id=?", (v,)).fetchone()[0]
        ok, msg, rel = vh.restore(p, v)
        out(mode=info["storage_mode"], parts=parts, ok=ok, size=info["size"],
            same=read(os.path.join(ROOT, rel)) == data, length=len(data))
        """)
    assert r["mode"] == "chunked" and r["parts"] == 4
    assert r["ok"] and r["same"] and r["size"] == r["length"]


# ---------------------------------------------------------------------------- refusals
def test_a_version_of_another_file_cannot_be_restored_downloaded_or_deleted(run):
    r = run("""
        a = put(f"vh_{TAG}/a.txt", b"file A")
        b = put(f"vh_{TAG}/b.txt", b"file B")
        va, vb = snap(a), snap(b)
        restore = vh.restore(a, vb)
        download = vh.prepare_download(a, vb)
        stream = vh.open_download_stream(a, vb)
        delete = vh.delete(a, vb, "a.txt")
        out(restore=restore[:2], restore_rel=restore[2], download=download[:2],
            download_data=download[2], stream=stream[:2], delete=delete,
            b_status=vh.get_version_info(vb, b)["status"],
            info_through_a=vh.get_version_info(vb, a),
            recovered_exists=os.path.exists(os.path.join(ROOT, ".recovered", f"vh_{TAG}")))
        """)
    assert r["restore"][0] is False and "does not belong" in r["restore"][1]
    assert r["restore_rel"] is None
    assert r["download"][0] is False and r["download_data"] is None
    assert r["stream"][0] is False
    assert r["delete"][0] is False
    assert r["b_status"] == "completed"
    assert r["info_through_a"] is None
    assert r["recovered_exists"] is False


def test_unknown_and_failed_versions_are_not_restorable(run):
    r = run("""
        p = put(f"vh_{TAG}/f.txt", b"content")
        v = snap(p)
        unknown = vh.restore(p, 987654321)
        conn = eng._connect()
        conn.execute("UPDATE versions SET status='failed', error='boom' WHERE version_id=?", (v,))
        conn.commit()
        failed = vh.restore(p, v)
        out(unknown=unknown, failed=failed)
        """)
    assert r["unknown"][0] is False and "No such version_id" in r["unknown"][1]
    assert r["failed"][0] is False and "not restorable" in r["failed"][1]
    assert "failed" in r["failed"][1] and r["failed"][2] is None


def test_a_corrupted_stored_object_aborts_the_restore_without_a_partial_file(run):
    r = run("""
        p = put(f"vh_{TAG}/rot.txt", b"original bytes of the file")
        v = snap(p)
        sha = eng._connect().execute(
            "SELECT sha256 FROM version_objects WHERE version_id=?", (v,)).fetchone()[0]
        with open(eng._object_path(sha), "ab") as f:
            f.write(b"bit rot")
        ok, msg, rel = vh.restore(p, v)
        folder = os.path.join(ROOT, ".recovered", f"vh_{TAG}")
        left = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
        stream = vh.open_download_stream(p, v)
        try:
            streamed = b"".join(stream[4])
            stream_failed = False
        except Exception as exc:
            streamed, stream_failed = b"", True
        out(ok=ok, msg=msg, rel=rel, left=left, live=read(p).decode(),
            stream_failed=stream_failed, streamed=streamed.decode("latin-1"))
        """)
    assert r["ok"] is False and "Restore failed" in r["msg"] and r["rel"] is None
    assert r["left"] == []  # no half-written file, no leftover temp file
    assert r["live"] == "original bytes of the file"
    assert r["stream_failed"] or r["streamed"] != "original bytes of the file"


def test_a_file_outside_the_storage_root_is_never_restored_beside_it(run):
    r = run("""
        p = os.path.join(os.path.dirname(ROOT), f"outside_{TAG}.txt")
        with open(p, "wb") as f:
            f.write(b"outside the storage root")
        v = snap(p)
        ok, msg, rel = vh.restore(p, v)
        stray = [n for n in os.listdir(ROOT) if n.startswith("outside")]
        out(ok=ok, msg=msg, rel=rel, stray=stray)
        """)
    assert r["ok"] is False and "outside the recovered-files area" in r["msg"]
    assert r["rel"] is None and r["stray"] == []


def test_a_restore_that_is_already_running_is_refused(run):
    r = run("""
        p = put(f"vh_{TAG}/busy.txt", b"busy")
        v = snap(p)
        vh._inflight.add(vh._inflight_key(p, v))
        try:
            busy = vh.restore(p, v)
            listed = vh.inflight_versions(p)
        finally:
            vh._inflight.discard(vh._inflight_key(p, v))
        after = vh.restore(p, v)
        out(busy=busy, listed=listed, v=v, after_ok=after[0])
        """)
    assert (
        r["busy"][0] is False
        and r["busy"][1]
        == "This version is already being restored. Please wait for it to finish."
    )
    assert r["listed"] == [r["v"]] and r["after_ok"] is True


# ---------------------------------------------------------------------------- download / delete
def test_a_download_returns_the_exact_bytes_under_a_dated_name(run):
    r = run("""
        data = bytes(range(256)) * 40
        p = put(f"vh_{TAG}/dl.dat", data)
        v = snap(p)
        ok, msg, body, name = vh.prepare_download(p, v)
        sok, smsg, size, sname, chunks = vh.open_download_stream(p, v)
        streamed = b"".join(chunks)
        out(ok=ok, name=name, same=body == data, sok=sok, sname=sname, size=size,
            length=len(data), streamed_same=streamed == data)
        """)
    assert r["ok"] and r["same"] and r["sok"] and r["streamed_same"]
    assert r["size"] == r["length"] and r["name"] == r["sname"]
    assert re.match(r"^dl__\d{4}-\d{2}-\d{2}_\d{6}__v\d+\.dat$", r["name"])


def test_delete_needs_the_typed_file_name_and_leaves_other_versions(run):
    r = run("""
        p = put(f"vh_{TAG}/gone.txt", b"one")
        v1 = snap(p)
        put(f"vh_{TAG}/gone.txt", b"two!")
        v2 = snap(p)
        wrong = vh.delete(p, v1, "not the name")
        still = vh.get_version_info(v1, p)["status"]
        right = vh.delete(p, v1, "gone.txt")
        after = vh.get_version_info(v1, p)["status"]
        restore_deleted = vh.restore(p, v1)
        restore_other = vh.restore(p, v2)
        out(wrong=wrong, still=still, right=right, after=after,
            restore_deleted=restore_deleted[:2],
            other_ok=restore_other[0],
            other=read(os.path.join(ROOT, restore_other[2])).decode())
        """)
    assert r["wrong"][0] is False and "nothing was deleted" in r["wrong"][1]
    assert r["still"] == "completed"
    assert r["right"][0] is True and r["after"] == "deleted"
    assert (
        r["restore_deleted"][0] is False and "status=deleted" in r["restore_deleted"][1]
    )
    assert r["other_ok"] and r["other"] == "two!"


def test_failed_attempts_can_be_cleared_without_touching_good_versions(run):
    r = run("""
        p = put(f"vh_{TAG}/mixed.txt", b"good one")
        good = snap(p)
        put(f"vh_{TAG}/mixed.txt", b"another try")
        bad = snap(p)
        conn = eng._connect()
        conn.execute("UPDATE versions SET status='failed', error='x' WHERE version_id=?", (bad,))
        conn.commit()
        cleared = vh.clear_failed(p)
        ids = sorted(v["version_id"] for v in vh.get_history(p))
        out(cleared=cleared[:2], good=good, bad=bad, ids=ids, restore_ok=vh.restore(p, good)[0])
        """)
    assert r["cleared"][0] is True
    assert r["ids"] == [r["good"]] and r["bad"] not in r["ids"]
    assert r["restore_ok"] is True


# ---------------------------------------------------------------------------- retention
def test_retention_keeps_the_newest_versions_and_the_oldest_are_not_restorable(run):
    r = run("""
        config.VERSION_RETENTION_ENABLED = True
        config.VERSION_MAX_VERSIONS = 2
        p = put(f"vh_{TAG}/rot.txt", b"v1")
        ids = []
        for n in range(1, 5):
            put(f"vh_{TAG}/rot.txt", f"content number {n}".encode())
            ids.append(snap(p))
        status = {v["version_id"]: v["status"] for v in vh.get_history(p)}
        oldest = vh.restore(p, ids[0])
        newest = vh.restore(p, ids[3])
        out(ids=ids, status=status, oldest=oldest[:2], newest_ok=newest[0],
            newest=read(os.path.join(ROOT, newest[2])).decode())
        """)
    ids = r["ids"]
    status = {int(k): v for k, v in r["status"].items()}
    assert len(set(ids)) == 4
    assert [status[i] for i in ids] == ["deleted", "deleted", "completed", "completed"]
    assert r["oldest"][0] is False and "not restorable" in r["oldest"][1]
    assert r["newest_ok"] and r["newest"] == "content number 4"
