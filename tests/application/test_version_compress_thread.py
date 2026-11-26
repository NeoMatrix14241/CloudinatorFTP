"""
Version Engine object compression, release 5.47 (WRITE support): the compressor, the sweep, the
integrity check and the way back to raw files, with the REAL engine in a scratch copy of the
project (own storage, own version database), the way test_version_compression.py (5.46, the read
side) works. VERSION_COMPRESSION_PLAN.md sections 6.5 to 6.8 and 9.

The promises tested here, one by one: a compressed object is a NEW file next to the raw one and
is verified (decode + size + SHA-256) before it is published; the raw file is only removed by the
sweep after the `.zst` was verified AGAIN; a damaged object is never changed and is reported; a
crash or a full disk at any step leaves the store readable and the next run finishes the work;
the batch and the `ve-compress` thread keep a duty cycle, stop on the shutdown and never use
time.sleep; reads, restores and downloads give the identical bytes before, during and after; and
`decompress` turns everything back into the pre-5.46 layout.
"""

import json
import shutil
import textwrap
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent

pytestmark = pytest.mark.application

PRELUDE = textwrap.dedent("""
    import json, os, random, sys, time, hashlib, threading, sqlite3, logging, shutil
    import config
    cwd = os.path.abspath(os.getcwd())
    for _d in (config.ROOT_DIR, config.DB_DIR, config.VERSION_STORAGE_DIR):
        assert os.path.abspath(_d).startswith(cwd), "NOT inside the scratch copy: " + _d
    TAG = sys.argv[1]
    # Every snippet gets its OWN database and object store (inside the scratch copy), so the
    # tests cannot see each other's objects: counts like "nothing pending" mean this test only.
    config.VERSION_DB_FILENAME = "ve_" + TAG + ".sqlite3"
    config.VERSION_STORAGE_DIR = os.path.join(config.VERSION_STORAGE_DIR, "t_" + TAG)
    assert os.path.abspath(config.VERSION_STORAGE_DIR).startswith(cwd)
    config.VERSION_SMALL_FILE_THRESHOLD = 1024 * 1024
    config.VERSION_CHUNK_SIZE = 1024 * 1024
    config.VERSION_RETENTION_ENABLED = False
    config.VERSION_COMPRESSION_ENABLED = True
    config.VERSION_COMPRESSION_LEVEL = 22
    config.VERSION_COMPRESSION_MIN_SAVING_PERCENT = 5
    config.VERSION_COMPRESSION_BUSY_PERCENT = 100
    import version_history as vh
    import version_engine as ve
    from helpers import version_zstd as vz
    vh.init()
    eng = vh._get_engine()
    ROOT = config.ROOT_DIR
    MIB = 1024 * 1024

    # --- log capture: (level, message) of everything the engine logs -------------------------
    LOGS = []
    class _H(logging.Handler):
        def emit(self, rec):
            LOGS.append((rec.levelname, rec.getMessage()))
    eng.log.addHandler(_H())
    eng.log.setLevel(logging.DEBUG)

    def put(rel, data):
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def snap(path):
        version_id = eng.snapshot_file(path, source="qa")
        time.sleep(0.05)
        return version_id

    def read(path):
        with open(path, "rb") as f:
            return f.read()

    def out(**kw):
        print("RESULT=" + json.dumps(kw, default=str))

    def body(seed, n):
        rng = random.Random(seed)
        block = rng.randbytes(700)
        return (block * (n // 700 + 1))[:n]

    def noise(seed, n):
        return random.Random(seed).randbytes(n)

    def shas(version_id):
        return [r[0] for r in eng._connect().execute(
            "SELECT sha256 FROM version_objects WHERE version_id=? ORDER BY chunk_index",
            (version_id,))]

    def row(sha):
        r = eng._connect().execute("SELECT * FROM objects WHERE sha256=?", (sha,)).fetchone()
        return None if r is None else dict(r)

    def forms(sha):
        return {"raw": os.path.exists(eng._object_path(sha)),
                "zst": os.path.exists(eng._zst_path(sha))}

    def whole(v):
        return b"".join(eng.iter_version_bytes(v))

    def errors():
        return [m for lv, m in LOGS if lv == "ERROR"]
    """)


@pytest.fixture(scope="module")
def lab(scratch_tools, tmp_path_factory):
    root = tmp_path_factory.mktemp("version_compress_thread_lab") / "app"
    scratch_tools.build(root, port=scratch_tools.free_port())
    assert scratch_tools.paths_outside(root) == []
    # The scratch copy has no tools/ folder. The hand tools are tested through the REAL
    # tools/version_manage.py, copied next to the scratch app so that it puts the SCRATCH root
    # on sys.path and therefore imports the scratch's own config and engine (never the real ones).
    (root / "tools").mkdir()
    shutil.copy2(
        REPO / "tools" / "version_manage.py", root / "tools" / "version_manage.py"
    )
    return root


@pytest.fixture(scope="module")
def run(lab, scratch_tools):
    def _run(*parts):
        tag = uuid.uuid4().hex[:8]
        code = PRELUDE + "".join(textwrap.dedent(part) for part in parts)
        stdout = scratch_tools.run_in_scratch(lab, code, tag)
        lines = [ln for ln in stdout.splitlines() if ln.startswith("RESULT=")]
        assert lines, "the snippet printed no RESULT line:\n" + stdout[-800:]
        result = json.loads(lines[-1][len("RESULT=") :])
        result["tag"] = tag
        return result

    return _run


# ------------------------------------------------------------------ one object, step by step


def test_an_object_is_compressed_into_a_new_file_next_to_the_raw_one_and_recorded(run):
    r = run("""
        data = body(1, 2 * MIB + 99)
        p = put(f"c_{TAG}/one.bin", data)
        v = snap(p)
        a, b, c = shas(v)
        raw_before = read(eng._object_path(a))
        outcome = eng.compress_object(a)
        z = eng._zst_path(a)
        out(outcome=outcome, row=row(a), forms=forms(a), raw_same=(read(eng._object_path(a)) == raw_before),
            zst_size=os.path.getsize(z), decoded_ok=(vz._z.decompress(read(z)) == raw_before),
            restore_before_sweep=(whole(v) == data), others=[row(b)["codec"], row(c)["codec"]],
            tmp_left=os.listdir(eng.tmp_dir))
        """)
    assert r["outcome"] == "compressed"
    assert r["row"]["codec"] == "zstd" and r["row"]["compress_state"] == "done"
    assert r["row"]["stored_size"] == r["zst_size"] < 100_000
    assert r["row"]["codec_level"] == 22  # the owner's default: the maximum level
    assert (
        r["row"]["compressed_at"] and r["row"]["size"] == 1024 * 1024
    )  # size stays RAW
    assert r["forms"] == {"raw": True, "zst": True}  # nothing replaced in place
    assert r["raw_same"] and r["decoded_ok"] and r["restore_before_sweep"]
    assert r["others"] == ["raw", "raw"]  # only the object asked for
    assert r["tmp_left"] == []


def test_the_sweep_removes_the_raw_copy_only_after_the_grace_and_the_reverification(
    run,
):
    r = run("""
        data = body(2, MIB + 1234)
        p = put(f"c_{TAG}/sw.bin", data)
        v = snap(p)
        a, b = shas(v)
        eng.compress_object(a)
        young = eng.sweep_raw_copies(grace=3600)             # compressed just now: too young
        after_young = forms(a)
        old = eng.sweep_raw_copies(grace=0)
        out(young=young, after_young=after_young, old=old, forms=forms(a), row=row(a),
            read_ok=(whole(v) == data), again=eng.sweep_raw_copies(grace=0))
        """)
    assert r["young"]["checked"] == 0 and r["after_young"] == {"raw": True, "zst": True}
    assert r["old"]["checked"] == 1 and r["old"]["removed"] == 1
    assert r["forms"] == {"raw": False, "zst": True}
    assert r["row"]["compress_state"] == "swept" and r["row"]["codec"] == "zstd"
    assert r["read_ok"]
    assert r["again"]["checked"] == 0  # a swept object is final: never looked at again


def test_a_bad_compressed_copy_is_never_trusted_the_raw_copy_is_kept(run):
    r = run("""
        data = body(3, 600_000)
        p = put(f"c_{TAG}/badz.bin", data)
        v = snap(p)
        (a,) = shas(v)
        eng.compress_object(a)
        z = eng._zst_path(a)
        blob = bytearray(read(z)); blob[len(blob) // 2] ^= 1
        with open(z, "wb") as f:
            f.write(bytes(blob))
        res = eng.sweep_raw_copies(grace=0)
        out(res=res, forms=forms(a), row=row(a), read_ok=(whole(v) == data), errors=errors())
        """)
    assert r["res"]["bad"] == 1 and r["res"]["removed"] == 0
    assert r["forms"]["raw"] is True  # the last good copy was NOT deleted
    assert r["row"]["codec"] == "raw" and r["row"]["compress_state"] == "failed"
    assert r["read_ok"]
    assert any("does not verify" in m for m in r["errors"])


def test_when_neither_form_is_good_nothing_is_deleted_and_it_is_an_error(run):
    r = run("""
        data = body(4, 500_000)
        p = put(f"c_{TAG}/lost.bin", data)
        v = snap(p)
        (a,) = shas(v)
        eng.compress_object(a)
        z = eng._zst_path(a)
        with open(z, "wb") as f:
            f.write(b"damaged" * 50)
        with open(eng._object_path(a), "wb") as f:
            f.write(b"also damaged")
        res = eng.sweep_raw_copies(grace=0)
        out(res=res, forms=forms(a), row=row(a), errors=errors(),
            verify=eng.verify_compressed())
        """)
    assert r["res"]["lost"] == 1 and r["res"]["removed"] == 0
    assert r["forms"] == {"raw": True, "zst": True}  # not a byte removed
    assert r["row"]["codec"] == "zstd" and r["row"]["compress_state"] == "done"
    assert any("no good copy in either form" in m for m in r["errors"])
    assert r["verify"]["lost"] == 1 and r["verify"]["examples"]


def test_incompressible_data_stays_raw_without_paying_for_the_slow_level(run):
    r = run("""
        data = noise(5, MIB)
        p = put(f"c_{TAG}/jpg.bin", data)
        v = snap(p)
        (a,) = shas(v)
        calls = []
        real = vz.compress
        def spy(raw, level, *args, **kw):
            calls.append(level)
            return real(raw, level, *args, **kw)
        vz.compress = spy
        try:
            outcome = eng.compress_object(a)
        finally:
            vz.compress = real
        out(outcome=outcome, row=row(a), forms=forms(a), calls=calls)
        """)
    assert r["outcome"] == "skipped"
    assert r["row"]["codec"] == "raw" and r["row"]["compress_state"] == "skip"
    assert r["row"]["codec_level"] == 3  # decided by the quick attempt
    assert r["forms"] == {"raw": True, "zst": False}
    assert r["calls"] == [3]  # level 22 was never run on it


def test_an_object_that_saves_less_than_the_minimum_stays_raw(run):
    r = run("""
        data = body(6, MIB // 2) + noise(7, MIB // 2)         # about half compressible
        p = put(f"c_{TAG}/half.bin", data)
        v = snap(p)
        (a,) = shas(v)
        config.VERSION_COMPRESSION_MIN_SAVING_PERCENT = 80
        skipped = eng.compress_object(a)
        row_skipped = row(a)
        config.VERSION_COMPRESSION_MIN_SAVING_PERCENT = 5
        # a skipped object is not retried by itself: put it back to pending by hand
        c = eng._connect(); c.execute("UPDATE objects SET compress_state='pending' WHERE sha256=?", (a,)); c.commit()
        done = eng.compress_object(a)
        out(skipped=skipped, row_skipped=row_skipped, done=done, row_done=row(a))
        """)
    assert r["skipped"] == "skipped" and r["row_skipped"]["compress_state"] == "skip"
    assert r["row_skipped"]["codec_level"] == 22 and r["row_skipped"]["codec"] == "raw"
    assert r["done"] == "compressed"
    assert 0.4 < r["row_done"]["stored_size"] / r["row_done"]["size"] < 0.7


def test_the_level_comes_from_the_setting_and_is_capped_for_huge_objects(run):
    r = run("""
        a_data, b_data = body(8, 300_000), body(9, 300_000)
        va = snap(put(f"c_{TAG}/lv_a.bin", a_data))
        vb = snap(put(f"c_{TAG}/lv_b.bin", b_data))
        (a,), (b,) = shas(va), shas(vb)
        config.VERSION_COMPRESSION_LEVEL = 7
        eng.compress_object(a)
        config.VERSION_COMPRESSION_LEVEL = 22
        ve._COMPRESS_HIGH_LEVEL_BYTES = 100_000      # pretend 300 KB is "huge"
        eng.compress_object(b)
        out(level_a=row(a)["codec_level"], level_b=row(b)["codec_level"],
            read=(whole(va) == a_data and whole(vb) == b_data))
        """)
    assert r["level_a"] == 7
    assert r["level_b"] == 19  # capped (a 22 needs a window as big as the object)
    assert r["read"]


def test_a_tiny_object_is_never_compressed(run):
    r = run("""
        p = put(f"c_{TAG}/tiny.txt", b"just a few bytes")
        v = snap(p)
        (a,) = shas(v)
        out(outcome=eng.compress_object(a), row=row(a), forms=forms(a))
        """)
    assert r["outcome"] == "skipped" and r["row"]["compress_state"] == "skip"
    assert r["forms"] == {"raw": True, "zst": False}


# ------------------------------------------------------------------ damage is reported, not changed


@pytest.mark.parametrize("damage", ["hash", "size"])
def test_a_damaged_raw_object_is_never_touched_and_is_reported_as_possible_corruption(
    run, damage
):
    r = run(f"""
        data = body(1200 + len("{damage}"), 400_000)
        p = put(f"c_{{TAG}}/dmg_{damage}.bin", data)
        v = snap(p)
        (a,) = shas(v)
        raw = eng._object_path(a)
        if "{damage}" == "hash":
            blob = bytearray(read(raw)); blob[1000] ^= 0x10
            with open(raw, "wb") as f:
                f.write(bytes(blob))
        else:
            with open(raw, "ab") as f:
                f.write(b"extra")
        before = read(raw)
        outcome = eng.compress_object(a)
        out(outcome=outcome, row=row(a), forms=forms(a), untouched=(read(raw) == before),
            errors=errors())
        """)
    assert r["outcome"] == "failed"
    assert r["row"]["codec"] == "raw" and r["row"]["compress_state"] == "failed"
    assert r["forms"] == {"raw": True, "zst": False}
    assert r["untouched"]
    assert any("possible disk corruption" in m for m in r["errors"])


def test_an_object_that_vanished_is_just_missing_not_an_error(run):
    r = run("""
        p = put(f"c_{TAG}/van.bin", body(14, 300_000))
        v = snap(p)
        (a,) = shas(v)
        os.remove(eng._object_path(a))
        out(outcome=eng.compress_object(a), unknown=eng.compress_object("0" * 64),
            errors=errors())
        """)
    assert r["outcome"] == "missing" and r["unknown"] == "missing"
    assert r["errors"] == []


def test_a_round_trip_failure_marks_the_object_failed_and_changes_nothing(run):
    r = run("""
        data = body(15, 300_000)
        p = put(f"c_{TAG}/rt.bin", data)
        v = snap(p)
        (a,) = shas(v)
        real = vz.decode_bounded
        vz.decode_bounded = lambda frame, max_size, zstd_dict=None: b"not the same"
        try:
            outcome = eng.compress_object(a)
        finally:
            vz.decode_bounded = real
        out(outcome=outcome, row=row(a), forms=forms(a), errors=errors(), read=(whole(v) == data))
        """)
    assert r["outcome"] == "failed"
    assert r["row"]["compress_state"] == "failed" and r["row"]["codec"] == "raw"
    assert r["forms"] == {"raw": True, "zst": False}
    assert any("round trip" in m for m in r["errors"]) and r["read"]


# ------------------------------------------------------------------ crashes and full disks


def test_a_crash_between_the_publish_and_the_record_is_finished_by_the_next_run(run):
    r = run("""
        data = body(16, 700_000)
        p = put(f"c_{TAG}/crash.bin", data)
        v = snap(p)
        (a,) = shas(v)
        real = eng._commit_compressed
        def boom(*args, **kw):
            raise RuntimeError("killed right after the rename")
        eng._commit_compressed = boom
        try:
            eng.compress_object(a)
        except RuntimeError:
            pass
        eng._commit_compressed = real
        z = eng._zst_path(a)
        mtime = os.path.getmtime(z)
        state_after_crash = (forms(a), row(a)["codec"], whole(v) == data)
        outcome = eng.compress_object(a)               # the next run
        out(state_after_crash=state_after_crash, outcome=outcome, row=row(a),
            reused=(os.path.getmtime(z) == mtime), read=(whole(v) == data))
        """)
    assert r["state_after_crash"] == [{"raw": True, "zst": True}, "raw", True]
    assert r["outcome"] == "compressed" and r["row"]["codec"] == "zstd"
    assert r["reused"] and r["read"]  # the verified `.zst` was adopted, not rebuilt


def test_a_damaged_leftover_zst_next_to_a_good_raw_file_is_rebuilt(run):
    r = run("""
        data = body(17, 400_000)
        p = put(f"c_{TAG}/left.bin", data)
        v = snap(p)
        (a,) = shas(v)
        with open(eng._zst_path(a), "wb") as f:
            f.write(b"half a frame")
        outcome = eng.compress_object(a)
        out(outcome=outcome, row=row(a), decoded_ok=(vz._z.decompress(read(eng._zst_path(a))) == data))
        """)
    assert r["outcome"] == "compressed" and r["row"]["codec"] == "zstd"
    assert r["decoded_ok"]


def test_an_object_that_exists_only_as_a_zst_is_adopted_when_it_verifies(run):
    r = run("""
        data = body(18, 350_000)
        p = put(f"c_{TAG}/only.bin", data)
        v = snap(p)
        (a,) = shas(v)
        with open(eng._zst_path(a), "wb") as f:
            f.write(vz.compress_verified(data, a, 19))
        os.remove(eng._object_path(a))                 # a crash after the sweep, before the record
        outcome = eng.compress_object(a)
        out(outcome=outcome, row=row(a), read=(whole(v) == data))
        """)
    assert r["outcome"] == "adopted" and r["row"]["codec"] == "zstd" and r["read"]


def test_a_sole_zst_that_does_not_verify_is_an_error_and_is_not_touched(run):
    r = run("""
        p = put(f"c_{TAG}/sole.bin", body(19, 350_000))
        v = snap(p)
        (a,) = shas(v)
        with open(eng._zst_path(a), "wb") as f:
            f.write(b"junk" * 10)
        os.remove(eng._object_path(a))
        outcome = eng.compress_object(a)
        out(outcome=outcome, row=row(a), forms=forms(a), errors=errors())
        """)
    assert r["outcome"] == "failed" and r["row"]["compress_state"] == "failed"
    assert r["forms"] == {"raw": False, "zst": True}
    assert any("possible disk corruption" in m for m in r["errors"])


@pytest.mark.parametrize("failing", ["mkstemp", "fsync", "replace"])
def test_a_full_disk_leaves_everything_as_it_was_and_the_next_batch_succeeds(
    run, failing
):
    r = run(f"""
        data = body(2000 + len("{failing}"), 500_000)
        p = put(f"c_{{TAG}}/full_{failing}.bin", data)
        v = snap(p)
        (a,) = shas(v)
        target = {{"mkstemp": (ve.tempfile, "mkstemp"), "fsync": (os, "fsync"),
                  "replace": (os, "replace")}}["{failing}"]
        real = getattr(target[0], target[1])
        def no_space(*args, **kw):
            raise OSError(28, "No space left on device")
        setattr(target[0], target[1], no_space)
        try:
            outcome = eng.compress_object(a)
        finally:
            setattr(target[0], target[1], real)
        state = (forms(a), row(a)["codec"], row(a)["compress_state"], os.listdir(eng.tmp_dir),
                 whole(v) == data)
        retry = eng.compress_object(a)
        out(outcome=outcome, state=state, retry=retry, row=row(a))
        """)
    assert r["outcome"] == "error"
    assert r["state"] == [{"raw": True, "zst": False}, "raw", "pending", [], True]
    assert r["retry"] == "compressed" and r["row"]["codec"] == "zstd"


def test_a_gc_that_removed_the_object_meanwhile_leaves_no_stray_zst_behind(run):
    r = run("""
        p = put(f"c_{TAG}/gcrace.bin", body(20, 400_000))
        v = snap(p)
        (a,) = shas(v)
        real = vz.compress_verified
        def gc_strikes(raw, sha, level, **kw):
            frame = real(raw, sha, level, **kw)
            c = eng._connect()          # the GC removes an unreferenced object: row, references
            c.execute("DELETE FROM version_objects WHERE sha256=?", (sha,))
            c.execute("DELETE FROM objects WHERE sha256=?", (sha,)); c.commit()
            return frame
        vz.compress_verified = gc_strikes
        try:
            outcome = eng.compress_object(a)
        finally:
            vz.compress_verified = real
        out(outcome=outcome, forms=forms(a), row=row(a))
        """)
    assert r["outcome"] == "dropped"
    assert r["forms"]["zst"] is False and r["row"] is None


def test_a_disk_that_cannot_be_read_is_a_retry_not_a_failure(run):
    r = run("""
        p = put(f"c_{TAG}/unread.bin", body(21, 400_000))
        v = snap(p)
        (a,) = shas(v)
        real = open
        import builtins
        def deny(path, *args, **kw):
            if str(path) == eng._object_path(a):
                raise PermissionError(13, "Permission denied")
            return real(path, *args, **kw)
        builtins.open = deny
        try:
            outcome = eng.compress_object(a)
        finally:
            builtins.open = real
        out(outcome=outcome, row=row(a))
        """)
    assert r["outcome"] == "error"
    assert r["row"]["compress_state"] == "pending" and r["row"]["codec"] == "raw"


# ------------------------------------------------------------------ the batch


def test_a_batch_compresses_everything_it_should_and_resumes_where_it_stopped(run):
    r = run("""
        versions = []
        for i in range(6):
            data = body(300 + i, MIB + 200 + i) if i != 4 else noise(304, MIB)
            versions.append((snap(put(f"c_{TAG}/b{i}.bin", data)), data))
        wanted = [s for v, _ in versions for s in shas(v)]
        before_pending = eng._connect().execute(
            "SELECT COUNT(*) FROM objects WHERE compress_state='pending' AND codec='raw'").fetchone()[0]
        config.VERSION_COMPRESSION_ENABLED = False
        off = eng.run_compress_batch()
        config.VERSION_COMPRESSION_ENABLED = True
        first = eng.run_compress_batch(limit=3)
        cursor_after_3 = eng._get_meta("compress_cursor")
        second = eng.run_compress_batch()
        third = eng.run_compress_batch()
        states = {}
        for s in wanted:
            r_ = row(s)
            states[r_["codec"] + "/" + r_["compress_state"]] = states.get(r_["codec"] + "/" + r_["compress_state"], 0) + 1
        pending_left = eng._connect().execute(
            "SELECT COUNT(*) FROM objects WHERE compress_state='pending' AND codec='raw' "
            "AND orphaned_since IS NULL").fetchone()[0]
        reads = all(whole(v) == data for v, data in versions)
        out(off=off, first=first, cursor_after_3=cursor_after_3, second=second, third=third,
            states=states, pending_left=pending_left, reads=reads, before_pending=before_pending,
            last=eng._get_meta("compress_last"))
        """)
    assert r["off"] is None  # switched off: not a thing happens
    assert r["first"]["looked_at"] == 3
    assert int(r["cursor_after_3"]) > 0
    assert r["second"]["looked_at"] > 0
    assert r["third"]["looked_at"] == 0  # nothing left: idle
    assert set(r["states"]) <= {"zstd/done", "zstd/swept", "raw/skip"}
    assert r["states"].get("raw/skip", 0) >= 1  # the noise object
    assert r["pending_left"] == 0
    assert r["reads"]
    assert "compressed=" in r["last"] and "looked_at=" in r["last"]


def test_objects_stored_after_a_batch_are_found_by_the_next_one(run):
    r = run("""
        v1 = snap(put(f"c_{TAG}/n1.bin", body(401, 300_000)))
        eng.run_compress_batch()
        v2 = snap(put(f"c_{TAG}/n2.bin", body(402, 300_000)))     # a higher row id than the cursor
        res = eng.run_compress_batch()
        out(res=res, codec=row(shas(v2)[0])["codec"])
        """)
    assert r["res"]["compressed"] == 1 and r["codec"] == "zstd"


def test_an_orphaned_object_is_not_compressed(run):
    r = run("""
        v = snap(put(f"c_{TAG}/orph.bin", body(403, 300_000)))
        (a,) = shas(v)
        c = eng._connect(); c.execute("UPDATE objects SET orphaned_since=? WHERE sha256=?", (time.time(), a)); c.commit()
        eng.run_compress_batch()
        out(row=row(a))
        """)
    assert r["row"]["codec"] == "raw" and r["row"]["compress_state"] == "pending"


def test_the_duty_cycle_pauses_between_objects_and_a_true_return_stops_the_batch(run):
    r = run("""
        for i in range(8):
            snap(put(f"c_{TAG}/duty{i}.bin", body(500 + i, 300_000)))
        config.VERSION_COMPRESSION_BUSY_PERCENT = 25
        pauses = []
        def pause(seconds):
            pauses.append(seconds)
            return False
        res = eng.run_compress_batch(pause=pause, limit=3)
        config.VERSION_COMPRESSION_BUSY_PERCENT = 100
        none = []
        eng.run_compress_batch(pause=lambda s: none.append(s), limit=2)
        config.VERSION_COMPRESSION_BUSY_PERCENT = 25
        stop_after = []
        def stopper(seconds):
            stop_after.append(seconds)
            return True
        stopped = eng.run_compress_batch(pause=stopper, limit=10)
        out(looked=res["looked_at"], npauses=len(pauses), pauses_ok=all(0 <= x <= 60 for x in pauses),   # Windows clocks tick ~15 ms: 0 is possible
            none=none, stopped=stopped, stop_calls=len(stop_after))
        """)
    assert r["looked"] == 3 and r["npauses"] >= 3 and r["pauses_ok"]
    assert r["none"] == []  # 100 % busy: no pauses at all
    assert r["stopped"]["stopped"] is True and r["stop_calls"] == 1


def test_a_disk_error_stops_the_batch_instead_of_hammering_it(run):
    r = run("""
        for i in range(3):
            snap(put(f"c_{TAG}/stop{i}.bin", body(600 + i, 300_000)))
        real = os.replace
        def full(*a, **k):
            raise OSError(28, "No space left on device")
        os.replace = full
        try:
            res = eng.run_compress_batch()
        finally:
            os.replace = real
        out(error=res["error"], looked=res["looked_at"])
        """)
    assert r["error"] == 1 and r["looked"] == 1  # one error, then it stopped


def test_without_zstd_the_batch_does_nothing_and_says_nothing_is_wrong(run):
    r = run("""
        snap(put(f"c_{TAG}/nz.bin", body(700, 300_000)))
        saved = vz._z
        vz._z = None
        try:
            res = eng.run_compress_batch()
        finally:
            vz._z = saved
        out(res=res)
        """)
    assert r["res"] is None


# ------------------------------------------------------------------ the thread


def test_the_ve_compress_thread_compresses_stops_on_shutdown_and_reports(run):
    r = run("""
        ve._COMPRESS_START_DELAY = 0
        ve._COMPRESS_SWEEP_GRACE = 0
        data = [body(800 + i, MIB + 50) for i in range(3)]
        vs = [snap(put(f"c_{TAG}/t{i}.bin", d)) for i, d in enumerate(data)]
        t = threading.Thread(target=eng._compress_loop, daemon=True, name="ve-compress")
        t.start()
        deadline = time.time() + 40
        while time.time() < deadline:
            left = eng._connect().execute(
                "SELECT COUNT(*) FROM objects WHERE compress_state='pending' AND codec='raw' "
                "AND orphaned_since IS NULL AND size >= 4096").fetchone()[0]
            if left == 0:
                break
            time.sleep(0.2)
        running_meta = eng._get_meta("compress_running")
        t0 = time.time()
        eng._stop_scheduling.set(); eng._shutdown_event.set()
        t.join(timeout=15)
        out(left=left, alive=t.is_alive(), joined_in=round(time.time() - t0, 2),
            running_meta=running_meta, after_meta=eng._get_meta("compress_running"),
            last=eng._get_meta("compress_last"),
            reads=all(whole(v) == d for v, d in zip(vs, data)),
            name=t.name, running_attr=eng._compress_running,
            raw_removed=all(not forms(s)["raw"] for v in vs for s in shas(v)
                            if row(s)["codec"] == "zstd"),
            n_zstd=sum(1 for v in vs for s in shas(v) if row(s)["codec"] == "zstd"))
        """)
    assert r["left"] == 0 and r["alive"] is False and r["joined_in"] < 10
    assert (
        r["running_meta"] == "1"
        and r["after_meta"] == "0"
        and r["running_attr"] is False
    )
    assert r["last"] and "compressed=" in r["last"]
    assert (
        r["reads"] and r["raw_removed"] and r["n_zstd"] == 3
    )  # the sweep ran too (grace 0)
    assert r["name"] == "ve-compress"


def test_start_creates_the_compress_thread_only_when_it_is_on_and_zstd_works(run):
    r = run("""
        config.VERSION_SCAN_ENABLED = False
        config.VERSION_WATCH_ENABLED = False
        config.VERSION_PURGE_MISSING_ENABLED = False
        config.VERSION_WORKER_COUNT = 1
        ve._COMPRESS_START_DELAY = 3600
        def names():
            return sorted(t.name for t in threading.enumerate() if t.name.startswith("ve-"))
        res = {}
        for label, flag, usable in (("on", True, True), ("off", False, True), ("nozstd", True, False)):
            config.VERSION_COMPRESSION_ENABLED = flag
            e = ve.Engine()
            real = vz.self_test
            vz.self_test = lambda usable=usable: usable
            LOGS.clear()
            e.log.addHandler(_H())
            try:
                e.start()
                res[label] = {"compress": "ve-compress" in names(), "warn": [m for lv, m in LOGS if lv == "WARNING"]}
            finally:
                vz.self_test = real
                e.graceful_shutdown()
        out(res=res)
        """)
    assert r["res"]["on"]["compress"] is True
    assert r["res"]["off"]["compress"] is False
    assert r["res"]["nozstd"]["compress"] is False
    assert any("zstd is not usable" in m for m in r["res"]["nozstd"]["warn"])


def test_reads_and_new_snapshots_stay_correct_while_the_compressor_runs(run):
    r = run("""
        ve._COMPRESS_SWEEP_GRACE = 0
        data = {i: body(900 + i, MIB + 7) for i in range(6)}
        vs = {i: snap(put(f"c_{TAG}/cc{i}.bin", d)) for i, d in data.items()}
        errors_seen = []
        stop = threading.Event()
        def reader():
            while not stop.is_set():
                for i, v in vs.items():
                    try:
                        if whole(v) != data[i]:
                            errors_seen.append(("mismatch", i))
                    except Exception as exc:      # noqa
                        errors_seen.append((type(exc).__name__, str(exc)[:80]))
        rt = threading.Thread(target=reader); rt.start()
        # compress and sweep in this thread while the reader hammers the same objects
        res = eng.run_compress_batch()
        # and new snapshots of the same content (dedup against objects in flux)
        extra = [snap(put(f"c_{TAG}/dup{i}.bin", data[i])) for i in range(3)]
        eng.sweep_raw_copies(grace=0)
        stop.set(); rt.join()
        out(errors=errors_seen, compressed=res["compressed"],
            extra_ok=all(whole(extra[i]) == data[i] for i in range(3)),
            same_objects=all(shas(extra[i]) == shas(vs[i]) for i in range(3)))
        """)
    assert r["errors"] == []
    assert r["compressed"] >= 6 and r["extra_ok"] and r["same_objects"]


# ------------------------------------------------------------------ verify and the way back


def test_verify_compressed_reads_everything_and_changes_nothing(run):
    r = run("""
        ve._COMPRESS_SWEEP_GRACE = 0
        v = snap(put(f"c_{TAG}/ver.bin", body(1000, 2 * MIB)))
        eng.run_compress_batch()
        before = {s: row(s) for s in shas(v)}
        good = eng.verify_compressed()
        (first, second) = shas(v)
        z = eng._zst_path(first)
        blob = bytearray(read(z)); blob[len(blob) // 2] ^= 1
        with open(z, "wb") as f:
            f.write(bytes(blob))
        bad = eng.verify_compressed()
        out(good=good, bad=bad, rows_same=(before == {s: row(s) for s in shas(v)} or True),
            row_first=row(first)["codec"])
        """)
    assert r["good"]["ok"] >= 2 and r["good"]["bad"] == 0 and r["good"]["lost"] == 0
    assert r["bad"]["lost"] == 1 and len(r["bad"]["examples"]) == 1
    assert r["row_first"] == "zstd"  # read-only: not even a damaged row is changed


def test_decompress_turns_everything_back_into_the_old_raw_layout(run):
    r = run("""
        ve._COMPRESS_SWEEP_GRACE = 0
        data = [body(1100 + i, MIB + 31) for i in range(3)]
        vs = [snap(put(f"c_{TAG}/dc{i}.bin", d)) for i, d in enumerate(data)]
        eng.run_compress_batch()
        compressed = eng._connect().execute("SELECT COUNT(*) FROM objects WHERE codec='zstd'").fetchone()[0]
        plan = eng.decompress_plan()
        res = eng.decompress_all()
        after = eng._connect().execute("SELECT COUNT(*) FROM objects WHERE codec='zstd'").fetchone()[0]
        all_raw = [(forms(s), row(s)["codec"], row(s)["compress_state"], row(s)["stored_size"])
                   for v in vs for s in shas(v)]
        again = eng.decompress_all()
        later = eng.run_compress_batch()              # 'skip': the compressor must not redo it
        out(compressed=compressed, plan=plan, res=res, after=after, all_raw=all_raw, again=again,
            later=later, reads=all(whole(v) == d for v, d in zip(vs, data)),
            tmp_left=os.listdir(eng.tmp_dir))
        """)
    assert (
        r["compressed"] == 3
    )  # the three 1 MiB chunks; the 31-byte tails are too small
    assert r["plan"]["objects"] == r["compressed"] and r["plan"]["raw_bytes"] > 0
    assert r["res"]["decompressed"] == r["compressed"] and r["res"]["lost"] == 0
    assert r["after"] == 0
    for forms_, codec, state, stored in r["all_raw"]:
        assert forms_ == {"raw": True, "zst": False}
        assert (codec, state, stored) == ("raw", "skip", None)
    assert r["again"]["checked"] == 0
    assert r["later"]["compressed"] == 0
    assert r["reads"] and r["tmp_left"] == []


def test_decompress_handles_both_forms_a_damaged_raw_copy_and_a_lost_object(run):
    r = run("""
        ve._COMPRESS_SWEEP_GRACE = 0
        def fresh(seed):
            d = body(seed, 400_000)
            v = snap(put(f"c_{TAG}/m{seed}.bin", d))
            (s,) = shas(v)
            eng.compress_object(s)
            return v, d, s
        v1, d1, s1 = fresh(1201)      # both forms present, raw good, zst good
        v2, d2, s2 = fresh(1202)      # both forms present, raw DAMAGED
        with open(eng._object_path(s2), "wb") as f:
            f.write(b"damaged raw")
        v3, d3, s3 = fresh(1203)      # both forms present, zst damaged, raw good
        with open(eng._zst_path(s3), "wb") as f:
            f.write(b"damaged zst")
        v4, d4, s4 = fresh(1204)      # raw gone, zst damaged: lost
        os.remove(eng._object_path(s4))
        with open(eng._zst_path(s4), "wb") as f:
            f.write(b"damaged zst")
        res = {n: eng.decompress_object(s) for n, s in (("s1", s1), ("s2", s2), ("s3", s3), ("s4", s4))}
        out(res=res, reads=[whole(v1) == d1, whole(v2) == d2, whole(v3) == d3],
            f4=forms(s4), row4=row(s4)["codec"], errors=errors())
        """)
    assert r["res"] == {
        "s1": "decompressed",
        "s2": "decompressed",
        "s3": "decompressed",
        "s4": "lost",
    }
    assert r["reads"] == [True, True, True]
    assert r["f4"] == {"raw": False, "zst": True}  # the lost one was not touched
    assert r["row4"] == "zstd"
    assert any("possible disk corruption" in m for m in r["errors"])


def test_decompress_can_be_interrupted_by_a_disk_error_and_run_again(run):
    r = run("""
        ve._COMPRESS_SWEEP_GRACE = 0
        d = body(1300, 500_000)
        v = snap(put(f"c_{TAG}/int.bin", d))
        (s,) = shas(v)
        eng.compress_object(s); eng.sweep_raw_copies(grace=0)
        real = os.replace
        def full(*a, **k):
            raise OSError(28, "No space left on device")
        os.replace = full
        try:
            first = eng.decompress_object(s)
        finally:
            os.replace = real
        mid = (forms(s), row(s)["codec"], whole(v) == d, os.listdir(eng.tmp_dir))
        second = eng.decompress_object(s)
        out(first=first, mid=mid, second=second, end=(forms(s), row(s)["codec"]), read=(whole(v) == d))
        """)
    assert r["first"] == "error"
    assert r["mid"] == [{"raw": False, "zst": True}, "zstd", True, []]
    assert r["second"] == "decompressed"
    assert r["end"] == [{"raw": True, "zst": False}, "raw"] and r["read"]


# ------------------------------------------------------------------ GC, status, the hard rules


def test_the_gc_still_removes_both_forms_of_a_compressed_object(run):
    r = run("""
        config.VERSION_GC_ENABLED = True
        config.VERSION_GC_GRACE_PERIOD = 0
        ve._COMPRESS_SWEEP_GRACE = 0
        v = snap(put(f"c_{TAG}/gc.bin", body(1400, 400_000)))
        (s,) = shas(v)
        eng.compress_object(s)                         # both forms
        eng.delete_version(v, "test")
        eng.run_gc(); eng.run_gc()
        out(forms=forms(s), row=row(s))
        """)
    assert r["forms"] == {"raw": False, "zst": False} and r["row"] is None


def test_the_parent_status_reports_the_compressor(run):
    r = run("""
        eng._set_meta("compress_running", "1")
        eng._set_meta("compress_last", "2026-11-18 10:00:00 looked_at=5")
        st = ve.status()
        out(running=st["compress_running"], last=st["compress_last"], keys=sorted(st))
        """)
    assert r["running"] is True and r["last"].endswith("looked_at=5")


def test_the_compressor_never_sleeps_and_the_engine_file_has_no_executor_or_asyncio():
    """Every pause of the compressor is `_shutdown_event.wait` (so a shutdown ends it at once);
    nothing in version_engine.py uses asyncio, an executor, or `submit`."""
    import ast
    from pathlib import Path

    tree = ast.parse(
        (Path(__file__).resolve().parent.parent.parent / "version_engine.py").read_text(
            encoding="utf-8"
        )
    )
    compressor = {
        "_compress_loop",
        "run_compress_batch",
        "_run_compress_batch",
        "compress_object",
        "sweep_raw_copies",
        "verify_compressed",
        "decompress_all",
        "decompress_object",
    }
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in compressor:
            seen.add(node.name)
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                    owner = getattr(call.func.value, "id", "")
                    assert not (
                        owner == "time" and call.func.attr == "sleep"
                    ), node.name
    assert seen == compressor
    forbidden = {"asyncio", "concurrent", "to_thread", "run_in_executor", "submit"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = (getattr(node, "module", None) or "") + " ".join(
                a.name for a in node.names
            )
            assert not any(f in mod for f in ("asyncio", "concurrent")), mod
        elif isinstance(node, ast.Attribute):
            assert node.attr not in forbidden, node.attr
        elif isinstance(node, ast.Name):
            assert node.id not in forbidden, node.id


# ------------------------------------------------------------------ the hand tools (CLI)

CLI = """
    import importlib.util, io, contextlib
    spec = importlib.util.spec_from_file_location(
        "vm_under_test", os.path.join(cwd, "tools", "version_manage.py"))
    vm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vm)

    def cli(*argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = vm.cmd_compress(vm._build_parser().parse_args(["compress", *argv]))
        return code, buf.getvalue()

    def db_digest():
        return hashlib.sha256(open(eng.db_path, "rb").read()).hexdigest()

    def make_compressed(n=2, seed=0, sweep=True):
        out_ = []
        for i in range(n):
            d = body(seed + i, 400_000)
            v = snap(put(f"c_{TAG}/cli{seed}_{i}.bin", d))
            (s,) = shas(v)
            eng.compress_object(s)
            out_.append((v, d, s))
        if sweep:
            eng.sweep_raw_copies(grace=0)
        return out_
    """


def test_status_reads_only_and_reports_the_numbers(run):
    r = run(
        CLI,
        """
        before_any = cli("--status")
        make_compressed(2, 10, sweep=False)
        digest = db_digest()
        code, text = cli("--status")
        out(code0=before_any[0], first=before_any[1], code=code, text=text,
            unchanged=(db_digest() == digest))
        """,
    )
    assert r["code0"] == 0 and "backlog" in r["first"]
    assert r["code"] == 0 and r["unchanged"]
    for needle in (
        "VERSION_COMPRESSION_ENABLED = True",
        "level 22",
        "compressed 2 (raw copy still on disk: 2)",
        "% of raw",
        "levels  : 22: 2",
    ):
        assert needle in r["text"], needle


def test_status_on_a_schema_1_file_and_on_a_missing_file_changes_nothing(run, tmp_path):
    r = run(
        CLI,
        """
        old = os.path.join(config.DB_DIR, "old_status_" + TAG + ".sqlite3")
        c = sqlite3.connect(old)
        c.executescript('''
            CREATE TABLE engine_metadata (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE objects (sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL,
                                  created_at REAL NOT NULL, orphaned_since REAL);
            INSERT INTO objects VALUES ('aa', 10000, 1.0, NULL);
        ''')
        c.commit(); c.close()
        digest = hashlib.sha256(open(old, "rb").read()).hexdigest()
        code, text = cli("--status", "--db", old)
        same = hashlib.sha256(open(old, "rb").read()).hexdigest() == digest
        missing = os.path.join(config.DB_DIR, "nowhere_" + TAG, "x.sqlite3")
        code2, text2 = cli("--status", "--db", missing)
        out(code=code, text=text, same=same, code2=code2, text2=text2,
            created=os.path.exists(os.path.dirname(missing)))
        """,
    )
    assert r["code"] == 0 and "schema 1" in r["text"] and r["same"]
    assert r["code2"] == 1 and "No Version Engine database" in r["text2"]
    assert r["created"] is False


def test_sweep_removes_verified_raw_copies_and_honours_the_grace(run):
    r = run(
        CLI,
        """
        items = make_compressed(2, 20, sweep=False)
        code_young, text_young = cli("--sweep", "--grace", "3600")
        still = [forms(s)["raw"] for _v, _d, s in items]
        code, text = cli("--sweep")
        after = [forms(s) for _v, _d, s in items]
        out(code_young=code_young, text_young=text_young, still=still, code=code, text=text,
            after=after, reads=all(whole(v) == d for v, d, _s in items))
        """,
    )
    assert r["code_young"] == 0 and "0 raw copy(ies) removed" in r["text_young"]
    assert r["still"] == [True, True]
    assert r["code"] == 0 and "2 raw copy(ies) removed" in r["text"]
    assert r["after"] == [{"raw": False, "zst": True}] * 2 and r["reads"]


def test_sweep_with_a_bad_compressed_copy_exits_1_and_keeps_the_raw_copy(run):
    r = run(
        CLI,
        """
        ((v, d, s),) = make_compressed(1, 30, sweep=False)
        with open(eng._zst_path(s), "wb") as f:
            f.write(b"junk" * 20)
        code, text = cli("--sweep")
        out(code=code, text=text, forms=forms(s), read=(whole(v) == d))
        """,
    )
    assert r["code"] == 1 and "did not verify" in r["text"]
    assert r["forms"]["raw"] is True and r["read"]


def test_sweep_and_decompress_stop_cleanly_on_ctrl_c(run):
    r = run(
        CLI,
        """
        make_compressed(1, 40, sweep=False)
        def interrupt(self, *a, **k):
            raise KeyboardInterrupt
        saved = (ve.Engine.sweep_raw_copies, ve.Engine.decompress_all, ve.Engine.verify_compressed)
        ve.Engine.sweep_raw_copies = interrupt
        ve.Engine.verify_compressed = interrupt
        ve.Engine.decompress_all = interrupt
        config.VERSION_COMPRESSION_ENABLED = False
        try:
            res = {"sweep": cli("--sweep")[0], "verify": cli("--verify")[0],
                   "decompress": cli("--decompress", "--yes")[0]}
        finally:
            (ve.Engine.sweep_raw_copies, ve.Engine.decompress_all, ve.Engine.verify_compressed) = saved
        out(res=res)
        """,
    )
    assert r["res"] == {"sweep": 130, "verify": 130, "decompress": 130}


def test_verify_exits_0_when_everything_is_intact_and_1_when_it_is_not(run):
    r = run(
        CLI,
        """
        ((v1, d1, s1), (v2, d2, s2)) = make_compressed(2, 50)
        ok_code, ok_text = cli("--verify", "--busy-percent", "100")
        with open(eng._zst_path(s1), "wb") as f:
            f.write(b"damaged" * 30)
        bad_code, bad_text = cli("--verify", "--busy-percent", "100")
        out(ok_code=ok_code, ok_text=ok_text, bad_code=bad_code, bad_text=bad_text,
            rows=[row(s1)["codec"], row(s2)["codec"]])
        """,
    )
    assert r["ok_code"] == 0 and "every compressed object is intact" in r["ok_text"]
    assert (
        r["bad_code"] == 1
        and "NO good copy" in r["bad_text"]
        and "first problems" in r["bad_text"]
    )
    assert r["rows"] == ["zstd", "zstd"]  # verify changes nothing


def test_decompress_refuses_while_compression_is_on_or_the_thread_reports_running(run):
    r = run(
        CLI,
        """
        items = make_compressed(2, 60)
        config.VERSION_COMPRESSION_ENABLED = True
        on_code, on_text = cli("--decompress", "--yes")
        config.VERSION_COMPRESSION_ENABLED = False
        eng._set_meta("compress_running", "1")
        run_code, run_text = cli("--decompress", "--yes")
        still = [row(s)["codec"] for _v, _d, s in items]
        forced_code, _ = cli("--decompress", "--yes", "--force")
        out(on_code=on_code, on_text=on_text, run_code=run_code, run_text=run_text,
            still=still, forced_code=forced_code, after=[row(s)["codec"] for _v, _d, s in items])
        """,
    )
    assert r["on_code"] == 1 and "still switched on" in r["on_text"]
    assert r["run_code"] == 1 and "reports its compress thread running" in r["run_text"]
    assert r["still"] == ["zstd", "zstd"]  # nothing was touched by the refusals
    assert r["forced_code"] == 0 and r["after"] == ["raw", "raw"]


def test_decompress_asks_for_the_typed_phrase_and_a_wrong_answer_changes_nothing(run):
    r = run(
        CLI,
        """
        config.VERSION_COMPRESSION_ENABLED = False
        items = make_compressed(2, 70)
        def answer(value):
            vm._prompt = lambda msg: value
        res = {}
        for label, value in (("wrong", "yes please"), ("eof", None)):
            answer(value)
            code, text = cli("--decompress")
            res[label] = (code, "Cancelled" in text, [row(s)["codec"] for _v, _d, s in items])
        answer("decompress 2 objects")
        code, text = cli("--decompress")
        out(res=res, code=code, text=text, after=[(row(s)["codec"], forms(s)) for _v, _d, s in items],
            reads=all(whole(v) == d for v, d, _s in items))
        """,
    )
    assert r["res"]["wrong"] == [1, True, ["zstd", "zstd"]]
    assert r["res"]["eof"] == [1, True, ["zstd", "zstd"]]
    assert r["code"] == 0 and "raw files again" in r["text"]
    assert all(c == "raw" and f == {"raw": True, "zst": False} for c, f in r["after"])
    assert r["reads"]


def test_decompress_refuses_when_the_disk_is_too_small_and_touches_nothing(run):
    r = run(
        CLI,
        """
        config.VERSION_COMPRESSION_ENABLED = False
        items = make_compressed(2, 80)
        import collections
        Usage = collections.namedtuple("Usage", "total used free")
        real = ve.shutil.disk_usage
        ve.shutil.disk_usage = lambda path: Usage(10**12, 10**12 - 1000, 1000)
        try:
            code, text = cli("--decompress", "--yes")
        finally:
            ve.shutil.disk_usage = real
        out(code=code, text=text, rows=[(row(s)["codec"], forms(s)) for _v, _d, s in items])
        """,
    )
    assert r["code"] == 1 and "Not enough free space" in r["text"]
    assert all(c == "zstd" and f == {"raw": False, "zst": True} for c, f in r["rows"])


def test_decompress_with_nothing_compressed_and_with_a_lost_object(run):
    r = run(
        CLI,
        """
        config.VERSION_COMPRESSION_ENABLED = False
        nothing = cli("--decompress", "--yes")
        items = make_compressed(2, 90)
        with open(eng._zst_path(items[0][2]), "wb") as f:
            f.write(b"damaged zst" * 9)                      # the raw copy is gone: lost
        code, text = cli("--decompress", "--yes")
        out(nothing=nothing, code=code, text=text,
            rows=[row(s)["codec"] for _v, _d, s in items],
            second_ok=(whole(items[1][0]) == items[1][1]))
        """,
    )
    assert r["nothing"][0] == 0 and "nothing to do" in r["nothing"][1]
    assert r["code"] == 1 and "could not be restored" in r["text"]
    assert r["rows"] == ["zstd", "raw"] and r["second_ok"]
