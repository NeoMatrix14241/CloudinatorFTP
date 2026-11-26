"""
Version Engine object compression, release 5.47.1 (Phase 4): the PREVIOUS-VERSION DELTA, with the
REAL engine in a scratch copy of the project (every snippet gets its own database and store), the
way test_version_compress_thread.py (the plain compressor) works. VERSION_COMPRESSION_PLAN.md
section 4.3 and the Phase 4 entry of section 16.

What is promised, one test each: a changed chunk is stored as a delta against the SAME chunk of
the file's previous version and nothing but a few KB is written for a small edit; a chain of
versions hangs on ONE plain anchor (depth 1: a read needs at most two objects and chains never
form); the base is never freed while a delta needs it (GC, purge), is never itself turned into a
delta and is verified every time it is used; every failure (damaged base, missing base, damaged
delta, a base removed between the choice and the commit, a crash, a full disk) leaves every
version readable or says so clearly and changes nothing; the sweep never removes a raw copy
unless the delta decodes with its base; `decompress` turns deltas back into plain raw files; and
READING a delta never depends on either switch.
"""

import json
import shutil
import textwrap
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.application

REPO = Path(__file__).resolve().parent.parent.parent

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
    config.VERSION_COMPRESSION_LEVEL = 19
    config.VERSION_COMPRESSION_DELTA_ENABLED = True
    config.VERSION_COMPRESSION_DELTA_MIN_GAIN_PERCENT = 20
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

    def tweak(data, chunk_index, seed, n=16, off=100):
        # `data` with n bytes of ONE 1 MiB chunk replaced: a small edit of a big file
        pos = chunk_index * MIB + off
        out_ = bytearray(data)
        out_[pos:pos + n] = noise(seed, n)
        return bytes(out_)

    def base_of(sha):
        return row(sha)["base_sha"]

    def version_chunks(v):
        return shas(v)

    def settle(limit=None):
        # compress everything pending (the batch), then sweep the raw copies at once
        res = eng.run_compress_batch(limit=limit)
        eng.sweep_raw_copies(grace=0)
        return res
    """)


@pytest.fixture(scope="module")
def lab(scratch_tools, tmp_path_factory):
    root = tmp_path_factory.mktemp("version_delta_lab") / "app"
    scratch_tools.build(root, port=scratch_tools.free_port())
    assert scratch_tools.paths_outside(root) == []
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


# ------------------------------------------------------------------ the happy path


def test_a_small_edit_of_a_big_file_is_stored_as_a_few_kb_delta_against_the_previous_chunk(
    run,
):
    r = run("""
        data1 = noise(1, 2 * MIB)                 # two incompressible chunks (like a db file)
        p = put(f"d_{TAG}/f.bin", data1)
        v1 = snap(p)
        settle()                                  # v1 has nothing to be a delta against
        data2 = tweak(data1, 0, 11)               # 16 bytes of chunk 0 changed
        put(f"d_{TAG}/f.bin", data2)
        v2 = snap(p)
        (a1, b1), (a2, b2) = shas(v1), shas(v2)
        res = settle()
        ok, msg, rel = vh.restore(p, v2)
        out(res=res, same_b=(b1 == b2), a_diff=(a1 != a2), row_a2=row(a2), row_a1=row(a1),
            forms_a1=forms(a1), forms_a2=forms(a2), v1_ok=(whole(v1) == data1),
            v2_ok=(whole(v2) == data2), restored=(ok and read(os.path.join(ROOT, rel)) == data2),
            a1=a1)
        """)
    assert (
        r["same_b"] and r["a_diff"]
    )  # the unchanged chunk is shared, one object changed
    a2 = r["row_a2"]
    assert a2["codec"] == "zstd" and a2["base_sha"] == r["a1"]
    assert a2["stored_size"] < 5_000 < a2["size"] // 100  # a few KB instead of 1 MiB
    assert (
        r["row_a1"]["codec"] == "raw" and r["row_a1"]["base_sha"] is None
    )  # the anchor is plain
    assert r["forms_a1"] == {"raw": True, "zst": False}
    assert r["forms_a2"] == {"raw": False, "zst": True}  # the raw copy was swept
    assert r["v1_ok"] and r["v2_ok"] and r["restored"]


def test_a_compressible_changed_chunk_is_a_delta_too_and_far_smaller_than_plain(run):
    r = run("""
        def pages(seed, n_bytes):
            # like a database: 4 KiB pages, a random header, then repetitive row text
            rng = random.Random(seed)
            out_ = b""
            while len(out_) < n_bytes:
                out_ += rng.randbytes(1500) + (b"ROW%05d|" % rng.randrange(1000)) * 300
            return out_[:n_bytes]
        base = pages(5, MIB + 100_000)
        v1 = snap(put(f"d_{TAG}/db.bin", base))
        settle()
        new = tweak(base, 0, 12, n=64, off=5000)
        p = put(f"d_{TAG}/db.bin", new)
        v2 = snap(p)
        (a1, _), (a2, _) = shas(v1), shas(v2)
        plain = len(vz.compress(read(eng._object_path(a2)), 19))   # a plain copy of the new chunk
        settle()
        out(row=row(a2), plain=plain, a1=a1, ok=(whole(v2) == new))
        """)
    assert r["row"]["base_sha"] == r["a1"] and r["ok"]
    assert r["plain"] > 100_000  # the data really is only moderately compressible
    assert (
        r["row"]["stored_size"] * 20 < r["plain"]
    )  # and the delta is a small fraction of it


def test_a_chain_of_versions_hangs_on_one_plain_anchor_never_on_another_delta(run):
    r = run("""
        d1 = noise(7, MIB)
        p = put(f"d_{TAG}/chain.bin", d1)
        v1 = snap(p); settle()
        data = [d1]
        vs = [v1]
        for i in range(2, 6):                      # versions 2..5, each a small edit of the last
            data.append(tweak(data[-1], 0, 20 + i))
            put(f"d_{TAG}/chain.bin", data[-1])
            vs.append(snap(p))
            settle()
        chunk = [shas(v)[0] for v in vs]
        out(anchor=chunk[0], bases=[base_of(s) for s in chunk],
            codecs=[row(s)["codec"] for s in chunk],
            reads=[whole(v) == d for v, d in zip(vs, data)],
            depth_ok=all(base_of(base_of(s) or s) is None for s in chunk))
        """)
    assert (
        r["bases"] == [None] + [r["anchor"]] * 4
    )  # every delta points at the SAME plain object
    assert r["codecs"] == ["raw"] + ["zstd"] * 4
    assert all(r["reads"]) and r["depth_ok"]


def test_when_a_chunk_changes_too_much_it_becomes_the_new_anchor(run):
    r = run("""
        d1 = noise(8, MIB)
        p = put(f"d_{TAG}/anchor.bin", d1)
        v1 = snap(p); settle()
        d2 = tweak(d1, 0, 31)
        put(f"d_{TAG}/anchor.bin", d2); v2 = snap(p); settle()
        d3 = noise(9, MIB)                         # everything changed: a delta gains nothing
        put(f"d_{TAG}/anchor.bin", d3); v3 = snap(p); settle()
        d4 = tweak(d3, 0, 32)                      # a small edit of the NEW chunk
        put(f"d_{TAG}/anchor.bin", d4); v4 = snap(p); settle()
        c = [shas(v)[0] for v in (v1, v2, v3, v4)]
        out(c=c, bases=[base_of(s) for s in c], codecs=[row(s)["codec"] for s in c],
            reads=[whole(v) == d for v, d in zip((v1, v2, v3, v4), (d1, d2, d3, d4))])
        """)
    c = r["c"]
    assert r["bases"] == [None, c[0], None, c[2]]  # v3 stands alone and is v4's anchor
    assert r["codecs"] == ["raw", "zstd", "raw", "zstd"]
    assert all(r["reads"])


def test_a_delta_is_only_built_when_the_delta_switch_is_on_but_reading_never_needs_it(
    run,
):
    r = run("""
        d1 = noise(10, MIB)
        p = put(f"d_{TAG}/sw.bin", d1)
        v1 = snap(p); settle()
        config.VERSION_COMPRESSION_DELTA_ENABLED = False
        d2 = tweak(d1, 0, 41)
        put(f"d_{TAG}/sw.bin", d2); v2 = snap(p); settle()
        off_row = row(shas(v2)[0])
        config.VERSION_COMPRESSION_DELTA_ENABLED = True
        d3 = tweak(d2, 0, 42)
        put(f"d_{TAG}/sw.bin", d3); v3 = snap(p); settle()
        on_row = row(shas(v3)[0])
        res = {}
        for delta_flag in (True, False):
            for comp_flag in (True, False):
                config.VERSION_COMPRESSION_DELTA_ENABLED = delta_flag
                config.VERSION_COMPRESSION_ENABLED = comp_flag
                res[f"{delta_flag}/{comp_flag}"] = (whole(v3) == d3 and whole(v1) == d1)
        out(off_base=off_row["base_sha"], off_codec=off_row["codec"], on_base=on_row["base_sha"],
            res=res)
        """)
    assert (
        r["off_base"] is None and r["off_codec"] == "raw"
    )  # a random chunk, no delta: stays raw
    assert r["on_base"] is not None
    assert all(r["res"].values()) and len(r["res"]) == 4


def test_the_minimum_gain_decides_whether_a_delta_is_worth_its_dependency(run):
    r = run("""
        d1 = noise(11, MIB)
        p = put(f"d_{TAG}/gain.bin", d1)
        v1 = snap(p); settle()
        half = d1[: MIB // 2] + noise(12, MIB // 2)         # half the chunk changed: gain ~50 %
        put(f"d_{TAG}/gain.bin", half); v2 = snap(p)
        config.VERSION_COMPRESSION_DELTA_MIN_GAIN_PERCENT = 80
        settle()
        strict = row(shas(v2)[0])
        c = eng._connect(); c.execute("UPDATE objects SET compress_state='pending' WHERE sha256=?", (shas(v2)[0],)); c.commit()
        config.VERSION_COMPRESSION_DELTA_MIN_GAIN_PERCENT = 20
        settle()
        lenient = row(shas(v2)[0])
        out(strict_base=strict["base_sha"], strict_codec=strict["codec"],
            lenient_base=lenient["base_sha"], lenient_codec=lenient["codec"],
            stored=lenient["stored_size"], read=(whole(v2) == half))
        """)
    assert r["strict_base"] is None and r["strict_codec"] == "raw"
    assert r["lenient_base"] is not None and r["lenient_codec"] == "zstd"
    assert r["read"] and r["stored"] < 600_000


# ------------------------------------------------------------------ more shapes of file

TWO_VERSIONS = """
    # one file, two versions: v2 is a small edit of v1's chunk 0, so chunk 0 of v2 is a delta
    d1 = noise(70, 2 * MIB)
    p = put(f"d_{TAG}/two.bin", d1)
    v1 = snap(p); settle()
    d2 = tweak(d1, 0, 71)
    put(f"d_{TAG}/two.bin", d2)
    v2 = snap(p)
    (a1, b1), (a2, b2) = shas(v1), shas(v2)
"""


def test_a_small_file_in_whole_file_mode_is_a_delta_too(run):
    r = run("""
        d1 = noise(60, 600_000)                    # below the 1 MiB threshold: ONE object
        p = put(f"d_{TAG}/small.bin", d1)
        v1 = snap(p); settle()
        d2 = tweak(d1, 0, 61, n=8, off=300_000)
        put(f"d_{TAG}/small.bin", d2); v2 = snap(p); settle()
        (a1,), (a2,) = shas(v1), shas(v2)
        out(base=base_of(a2), a1=a1, stored=row(a2)["stored_size"], size=row(a2)["size"],
            ok=(whole(v1) == d1 and whole(v2) == d2))
        """)
    assert r["base"] == r["a1"] and r["ok"] and r["stored"] < 3_000 < r["size"]


def test_several_changed_chunks_each_get_their_own_base_and_unchanged_ones_are_shared(
    run,
):
    r = run("""
        d1 = noise(61, 3 * MIB)
        p = put(f"d_{TAG}/multi.bin", d1)
        v1 = snap(p); settle()
        d2 = tweak(tweak(d1, 0, 62), 2, 63)        # chunks 0 and 2 change, chunk 1 does not
        put(f"d_{TAG}/multi.bin", d2); v2 = snap(p); settle()
        c1, c2 = shas(v1), shas(v2)
        out(shared=(c1[1] == c2[1]), bases=[base_of(c2[0]), base_of(c2[1]), base_of(c2[2])],
            c1=c1, ok=(whole(v1) == d1 and whole(v2) == d2))
        """)
    assert r["shared"] and r["ok"]
    assert r["bases"] == [r["c1"][0], None, r["c1"][2]]


def test_the_default_level_22_works_for_deltas_too(run):
    r = run(
        TWO_VERSIONS,
        """
        config.VERSION_COMPRESSION_LEVEL = 22
        settle()
        out(row=row(a2), a1=a1, ok=(whole(v2) == d2 and whole(v1) == d1))
        """,
    )
    assert r["row"]["base_sha"] == r["a1"] and r["row"]["codec_level"] == 22 and r["ok"]


def test_a_chunk_that_survives_into_later_versions_is_based_on_the_version_that_introduced_it(
    run,
):
    """The compressor runs minutes behind the snapshots: by then a changed chunk is often used by
    several versions (the next edit touched another chunk). Its base must still be the chunk it
    REPLACED, not nothing."""
    r = run("""
        d1 = noise(64, 2 * MIB)
        p = put(f"d_{TAG}/span.bin", d1)
        v1 = snap(p); settle()
        d2 = tweak(d1, 0, 65)                          # v2 changes chunk 0 ...
        put(f"d_{TAG}/span.bin", d2); v2 = snap(p)
        d3 = tweak(d2, 1, 66)                          # ... v3 changes only chunk 1
        put(f"d_{TAG}/span.bin", d3); v3 = snap(p)
        c1, c2, c3 = shas(v1), shas(v2), shas(v3)
        eng.run_compress_batch()                       # both new versions exist before it runs
        out(shares=(c2[0] == c3[0]), c1=c1, c2=c2, c3=c3,
            base_c2_0=base_of(c2[0]), base_c3_1=base_of(c3[1]),
            reads=(whole(v1) == d1, whole(v2) == d2, whole(v3) == d3))
        """)
    assert r["shares"]  # chunk 0 of v2 is also chunk 0 of v3 (so the newest user is v3)
    assert r["base_c2_0"] == r["c1"][0]  # and yet its base is what v2 replaced
    assert r["base_c3_1"] == r["c1"][1]
    assert r["reads"] == [True, True, True]


def test_the_candidate_rules_first_version_no_such_chunk_deleted_version_size_limits(
    run,
):
    r = run("""
        d1 = noise(62, MIB)
        p = put(f"d_{TAG}/cand.bin", d1)
        v1 = snap(p)
        (a1,) = shas(v1)
        first = eng._pick_delta_base(a1)                    # no earlier version at all
        d2 = d1 + noise(63, MIB)                            # grows: chunk 1 has no counterpart
        put(f"d_{TAG}/cand.bin", d2); v2 = snap(p)
        c2 = shas(v2)
        no_counterpart = eng._pick_delta_base(c2[1])
        d3 = tweak(d2, 0, 64)
        put(f"d_{TAG}/cand.bin", d3); v3 = snap(p)
        c3 = shas(v3)
        ok_pick = eng._pick_delta_base(c3[0])
        real_max = ve._DELTA_MAX_OBJECT_BYTES
        ve._DELTA_MAX_OBJECT_BYTES = 1000                   # the base would be "too big"
        too_big = eng._pick_delta_base(c3[0])
        ve._DELTA_MAX_OBJECT_BYTES = real_max
        c = eng._connect()
        c.execute("UPDATE versions SET status='deleted' WHERE version_id IN (?, ?)", (v1, v2))
        c.commit()
        prev_deleted = eng._pick_delta_base(c3[0])          # its predecessors are gone
        out(first=first, no_counterpart=no_counterpart, ok=(ok_pick[0] if ok_pick else None),
            c2_0=c2[0], too_big=too_big, prev_deleted=prev_deleted)
        """)
    assert r["first"] is None and r["no_counterpart"] is None
    assert (
        r["ok"] == r["c2_0"]
    )  # v3's chunk 0 is based on v2's chunk 0 (v2 is the newest earlier one)
    assert r["too_big"] is None and r["prev_deleted"] is None


# ------------------------------------------------------------------ the base is protected


def test_the_gc_never_frees_a_base_while_a_delta_needs_it_and_frees_both_afterwards(
    run,
):
    r = run(
        """
        config.VERSION_GC_ENABLED = True
        config.VERSION_GC_GRACE_PERIOD = 0
    """,
        TWO_VERSIONS,
        """
        settle()
        eng.delete_version(v1, "test")                      # v1 is gone, but a2 still needs a1
        for _ in range(5):
            eng.run_gc()
        kept = {"a1_row": row(a1) is not None, "a1_forms": forms(a1),
                "orphaned": row(a1)["orphaned_since"], "v2_ok": whole(v2) == d2}
        eng.delete_version(v2, "test")                      # now nothing needs either of them
        for _ in range(8):
            eng.run_gc()
        out(kept=kept, gone={"a1": row(a1), "a2": row(a2), "f1": forms(a1), "f2": forms(a2)},
            errors=errors())
        """,
    )
    assert r["kept"]["a1_row"] and r["kept"]["a1_forms"]["raw"] is True
    assert r["kept"]["orphaned"] is None  # never even marked: a delta still needs it
    assert r["kept"]["v2_ok"]
    assert r["gone"] == {
        "a1": None,
        "a2": None,
        "f1": {"raw": False, "zst": False},
        "f2": {"raw": False, "zst": False},
    }  # the delta went first, the base on a later pass
    assert r["errors"] == []


def test_a_base_the_gc_marked_as_an_orphan_is_put_back_in_use_by_the_delta_commit(run):
    r = run(
        """
        config.VERSION_GC_ENABLED = True
        config.VERSION_GC_GRACE_PERIOD = 3600
    """,
        TWO_VERSIONS,
        """
        real = vz.compress_verified
        def gc_strikes(raw, sha, level, zstd_dict=None, window_log=None):
            frame = real(raw, sha, level, zstd_dict=zstd_dict, window_log=window_log)
            if zstd_dict is not None:                       # between the choice and the commit:
                eng.delete_version(v1, "retention")         # the old version is deleted ...
                eng.run_gc()                                # ... and the GC marks a1 an orphan
                state["marked"] = row(a1)["orphaned_since"]
            return frame
        state = {}
        vz.compress_verified = gc_strikes
        try:
            outcome = eng.compress_object(a2)
        finally:
            vz.compress_verified = real
        out(outcome=outcome, marked=state.get("marked"), after=row(a1)["orphaned_since"],
            base=base_of(a2), a1=a1, ok=(whole(v2) == d2))
        """,
    )
    assert r["marked"] is not None  # the GC really had marked it
    assert r["outcome"] == "compressed" and r["base"] == r["a1"]
    assert r["after"] is None  # and the commit put it back in use
    assert r["ok"]


def test_a_base_removed_between_the_choice_and_the_commit_means_a_plain_object(run):
    r = run(
        """
        config.VERSION_GC_ENABLED = True
        config.VERSION_GC_GRACE_PERIOD = 0
    """,
        TWO_VERSIONS,
        """
        real = vz.compress_verified
        def base_vanishes(raw, sha, level, zstd_dict=None, window_log=None):
            frame = real(raw, sha, level, zstd_dict=zstd_dict, window_log=window_log)
            if zstd_dict is not None:
                eng.delete_version(v1, "retention")
                for _ in range(3):
                    eng.run_gc()                            # a1 is really deleted now
            return frame
        vz.compress_verified = base_vanishes
        try:
            outcome = eng.compress_object(a2)
        finally:
            vz.compress_verified = real
        out(outcome=outcome, a1=row(a1), row=row(a2), forms=forms(a2), ok=(whole(v2) == d2),
            tmp=os.listdir(eng.tmp_dir))
        """,
    )
    assert r["a1"] is None  # the base really was removed
    assert r["outcome"] == "skipped"  # no delta possible, random data: stays raw
    assert r["row"]["codec"] == "raw" and r["row"]["base_sha"] is None
    assert r["forms"] == {
        "raw": True,
        "zst": False,
    }  # the stray delta frame was removed
    assert r["ok"] and r["tmp"] == []


def test_a_base_is_never_turned_into_a_delta_and_a_delta_is_never_a_base(run):
    r = run(
        TWO_VERSIONS,
        """
        settle()
        eng_conn = eng._connect()
        # a1 is the base of a2: it must stay plain whatever its own history says
        pick_for_base = eng._pick_delta_base(a1)
        other = shas(snap(put(f"d_{TAG}/other.bin", noise(72, MIB))))[0]
        refuse_base_as_delta = eng._commit_compressed(a1, 100, 19, base_sha=other)
        refuse_delta_as_base = eng._commit_compressed(other, 100, 19, base_sha=a2)
        refuse_self = eng._commit_compressed(other, 100, 19, base_sha=other)
        out(pick_for_base=pick_for_base, refuse_base_as_delta=refuse_base_as_delta,
            refuse_delta_as_base=refuse_delta_as_base, refuse_self=refuse_self,
            a1_row=row(a1), other_row=row(other))
        """,
    )
    assert r["pick_for_base"] is None
    assert r["refuse_base_as_delta"] == "base_unusable"
    assert r["refuse_delta_as_base"] == "base_unusable"
    assert r["refuse_self"] == "base_unusable"
    assert r["a1_row"]["codec"] == "raw" and r["a1_row"]["base_sha"] is None
    assert r["other_row"]["codec"] == "raw" and r["other_row"]["base_sha"] is None


def test_the_purge_space_figures_do_not_count_a_base_that_a_live_delta_still_needs(run):
    r = run(
        TWO_VERSIONS,
        """
        from helpers import version_purge as vp
        settle()
        fid = eng._connect().execute("SELECT file_id FROM versions WHERE version_id=?", (v1,)).fetchone()[0]
        only_v1 = vp.reclaimable_detail(eng.db_path, [{"ids": [v1], "file_id": fid}])
        both = vp.reclaimable_detail(eng.db_path, [{"ids": [v1, v2], "file_id": fid}])
        out(only_v1=list(only_v1[1:]), both=list(both[1:]), a1_size=row(a1)["size"],
            a2_size=row(a2)["size"], a2_stored=row(a2)["stored_size"], b_size=row(b1)["size"])
        """,
    )
    assert r["only_v1"] == [
        0,
        0,
    ]  # a1 stays (a live delta needs it) and b is shared with v2
    # purging both versions frees the base (raw), the delta (its few KB ON DISK) and the shared chunk
    assert r["both"][0] == r["a1_size"] + r["a2_stored"] + r["b_size"]
    assert (
        r["both"][1] == r["a1_size"] + r["a2_size"] + r["b_size"]
    )  # the raw total next to it


# ------------------------------------------------------------------ damage is reported, never served


@pytest.mark.parametrize(
    "damage", ["base_flip", "base_missing", "delta_flip", "delta_empty"]
)
def test_a_damaged_or_missing_base_or_delta_is_reported_and_never_served_as_wrong_bytes(
    run, damage
):
    r = run(
        TWO_VERSIONS,
        f"""
        settle()
        z2 = eng._zst_path(a2)
        if "{damage}" == "base_flip":
            blob = bytearray(read(eng._object_path(a1))); blob[5000] ^= 1
            open(eng._object_path(a1), "wb").write(bytes(blob))
        elif "{damage}" == "base_missing":
            os.remove(eng._object_path(a1))
        elif "{damage}" == "delta_flip":
            blob = bytearray(read(z2)); blob[len(blob) // 2] ^= 1
            open(z2, "wb").write(bytes(blob))
        else:
            open(z2, "wb").write(b"")
        try:
            got = whole(v2); err = None
        except Exception as exc:
            got, err = b"", str(exc)
        ok_restore, msg, rel = vh.restore(p, v2)
        folder = os.path.join(ROOT, ".recovered", f"d_{{TAG}}")
        left = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
        out(err=err, served_wrong=(got != b"" and got != d2), restore_ok=ok_restore, left=left)
        """,
    )
    assert r["err"], "the damage must be reported"
    assert (
        r["served_wrong"] is False
    )  # never a single wrong byte served as if it were right
    assert r["restore_ok"] is False and r["left"] == []  # no half-written file
    if damage == "base_missing":
        assert "base object" in r["err"]
    else:
        assert "corrupted" in r["err"] or "unreadable" in r["err"]


def test_the_sweep_keeps_the_raw_copy_of_a_delta_whose_base_is_damaged(run):
    r = run(
        TWO_VERSIONS,
        """
        eng.run_compress_batch()                            # a2 is a delta, raw copy still there
        before = forms(a2)
        blob = bytearray(read(eng._object_path(a1))); blob[777] ^= 1
        open(eng._object_path(a1), "wb").write(bytes(blob))   # the base is damaged
        res = eng.sweep_raw_copies(grace=0)
        out(before=before, res=res, row=row(a2), forms=forms(a2), read=(whole(v2) == d2),
            errors=errors())
        """,
    )
    assert r["before"] == {"raw": True, "zst": True}
    assert r["res"]["bad"] == 1 and r["res"]["removed"] == 0
    assert r["forms"]["raw"] is True  # the last good copy was NOT deleted
    assert r["row"]["codec"] == "raw" and r["row"]["base_sha"] is None
    assert r["row"]["compress_state"] == "failed"
    assert r["read"]  # the raw copy serves v2 without the damaged base
    assert any("does not verify" in m for m in r["errors"])


def test_verify_reports_a_delta_with_no_usable_base_and_crash_recovery_says_so(run):
    r = run(
        TWO_VERSIONS,
        """
        settle()
        good = eng.verify_compressed()
        os.remove(eng._object_path(a1))                     # the base vanishes
        bad = eng.verify_compressed()
        LOGS.clear()
        eng._crash_recovery()
        out(good=good, bad=bad, recovery=[m for lv, m in LOGS if lv == "ERROR"])
        """,
    )
    assert r["good"]["ok"] >= 1 and r["good"]["bad"] == 0 and r["good"]["lost"] == 0
    assert r["bad"]["lost"] == 1  # the delta cannot be decoded, no raw copy either
    assert any("delta object(s) have no base object" in m for m in r["recovery"])


# ------------------------------------------------------------------ crashes and full disks


def test_a_crash_between_publishing_a_delta_and_recording_it_is_finished_by_the_next_run(
    run,
):
    r = run(
        TWO_VERSIONS,
        """
        real = eng._commit_compressed
        def killed(*args, **kw):
            raise RuntimeError("killed right after the rename")
        eng._commit_compressed = killed
        try:
            eng.compress_object(a2)
        except RuntimeError:
            pass
        eng._commit_compressed = real
        mid = (forms(a2), row(a2)["codec"], row(a2)["base_sha"], whole(v2) == d2)
        outcome = eng.compress_object(a2)                   # the next run
        out(mid=mid, outcome=outcome, row=row(a2), a1=a1, ok=(whole(v2) == d2),
            tmp=os.listdir(eng.tmp_dir))
        """,
    )
    assert r["mid"] == [{"raw": True, "zst": True}, "raw", None, True]
    assert r["outcome"] == "compressed"
    assert r["row"]["codec"] == "zstd" and r["row"]["base_sha"] == r["a1"]
    assert r["ok"] and r["tmp"] == []


@pytest.mark.parametrize("failing", ["mkstemp", "fsync", "replace"])
def test_a_full_disk_while_writing_a_delta_changes_nothing_and_the_retry_succeeds(
    run, failing
):
    r = run(
        TWO_VERSIONS,
        f"""
        target = {{"mkstemp": (ve.tempfile, "mkstemp"), "fsync": (os, "fsync"),
                  "replace": (os, "replace")}}["{failing}"]
        real = getattr(target[0], target[1])
        def no_space(*args, **kw):
            raise OSError(28, "No space left on device")
        setattr(target[0], target[1], no_space)
        try:
            outcome = eng.compress_object(a2)
        finally:
            setattr(target[0], target[1], real)
        state = (forms(a2), row(a2)["codec"], row(a2)["compress_state"], os.listdir(eng.tmp_dir),
                 whole(v2) == d2)
        retry = eng.compress_object(a2)
        out(outcome=outcome, state=state, retry=retry, base=base_of(a2), a1=a1)
        """,
    )
    assert r["outcome"] == "error"
    assert r["state"] == [{"raw": True, "zst": False}, "raw", "pending", [], True]
    assert r["retry"] == "compressed" and r["base"] == r["a1"]


def test_a_chain_of_deltas_is_refused_on_read_and_never_followed(run):
    """Depth 1 is enforced when READING as well: should a database ever claim that a base is
    itself a delta (a bug, a damaged row), the read stops with 'corrupted' instead of following
    the chain (so no loop can ever form)."""
    r = run(
        TWO_VERSIONS,
        """
        settle()
        other = shas(snap(put(f"d_{TAG}/other.bin", noise(73, MIB))))[0]
        z = vz.compress_verified(read(eng._object_path(a1)), a1, 19)
        open(eng._zst_path(a1), "wb").write(z)
        os.remove(eng._object_path(a1))                    # the base is stored as a .zst only ...
        c = eng._connect()
        c.execute("UPDATE objects SET codec='zstd', stored_size=?, base_sha=? WHERE sha256=?",
                  (len(z), other, a1))                     # ... and its row claims a base too
        c.commit()
        try:
            whole(v2); err = None
        except Exception as exc:
            err = str(exc)
        out(err=err)
        """,
    )
    assert r["err"] and "corrupted" in r["err"]


# ------------------------------------------------------------------ everything together


def test_readers_and_new_versions_stay_correct_while_deltas_are_made_and_swept(run):
    r = run("""
        ve._COMPRESS_SWEEP_GRACE = 0
        data = {0: noise(80, 2 * MIB)}
        p = put(f"d_{TAG}/conc.bin", data[0])
        vs = {0: snap(p)}
        eng.run_compress_batch()
        for i in range(1, 6):                              # five more small edits, snapshotted
            data[i] = tweak(data[i - 1], i % 2, 90 + i)
            put(f"d_{TAG}/conc.bin", data[i])
            vs[i] = snap(p)
        errors_seen = []
        stop = threading.Event()
        def reader():
            while not stop.is_set():
                for i, v in vs.items():
                    try:
                        if whole(v) != data[i]:
                            errors_seen.append(("mismatch", i))
                    except Exception as exc:               # noqa
                        errors_seen.append((type(exc).__name__, str(exc)[:90]))
        rt = threading.Thread(target=reader); rt.start()
        res = eng.run_compress_batch()                     # deltas are made while it reads
        eng.sweep_raw_copies(grace=0)
        stop.set(); rt.join()
        deltas = eng._connect().execute("SELECT COUNT(*) FROM objects WHERE base_sha IS NOT NULL").fetchone()[0]
        out(errors=errors_seen, deltas=deltas, compressed=res["compressed"],
            reads=all(whole(v) == data[i] for i, v in vs.items()))
        """)
    assert r["errors"] == []
    assert r["deltas"] >= 4 and r["reads"]


def test_decompress_turns_deltas_back_into_plain_raw_files_and_frees_the_base_later(
    run,
):
    r = run(
        """
        config.VERSION_GC_ENABLED = True
        config.VERSION_GC_GRACE_PERIOD = 0
    """,
        TWO_VERSIONS,
        """
        settle()
        before = (row(a2)["codec"], row(a2)["base_sha"] == a1, forms(a2))
        plan = eng.decompress_plan()
        res = eng.decompress_all()
        after = (row(a2)["codec"], row(a2)["base_sha"], row(a2)["compress_state"], forms(a2))
        again = eng.decompress_all()
        reads = (whole(v1) == d1, whole(v2) == d2)
        eng.delete_version(v1, "test"); eng.delete_version(v2, "test")
        for _ in range(8):
            eng.run_gc()
        out(before=before, plan=plan, res=res, after=after, again=again, reads=reads,
            freed=(row(a1), row(a2), forms(a1), forms(a2)), errors=errors())
        """,
    )
    assert r["before"] == ["zstd", True, {"raw": False, "zst": True}]
    assert r["plan"]["compressed_objects"] == 1 and r["plan"]["objects"] == 1
    assert r["res"]["decompressed"] == 1 and r["res"]["lost"] == 0
    assert r["after"] == ["raw", None, "skip", {"raw": True, "zst": False}]
    assert r["again"]["checked"] == 0 and r["reads"] == [True, True]
    # no dependency is left, so after the versions are deleted everything can be freed
    assert r["freed"][0] is None and r["freed"][1] is None
    assert r["freed"][2:] == [
        {"raw": False, "zst": False},
        {"raw": False, "zst": False},
    ]
    assert r["errors"] == []


def test_decompress_handles_a_delta_whose_base_is_itself_compressed(run):
    r = run("""
        def pages(seed, n_bytes):
            rng = random.Random(seed)
            out_ = b""
            while len(out_) < n_bytes:
                out_ += rng.randbytes(1500) + (b"ROW%05d|" % rng.randrange(1000)) * 300
            return out_[:n_bytes]
        d1 = pages(81, MIB + 4000)
        p = put(f"d_{TAG}/cb.bin", d1)
        v1 = snap(p); settle()                              # the base is compressed AND swept
        d2 = tweak(d1, 0, 82, n=32, off=9000)
        put(f"d_{TAG}/cb.bin", d2); v2 = snap(p); settle()
        a1, a2 = shas(v1)[0], shas(v2)[0]
        mid = (forms(a1), forms(a2), row(a1)["codec"], row(a2)["base_sha"] == a1)
        first = eng.decompress_object(a2)          # the DELTA first, while its base is a .zst only
        second = eng.decompress_object(a1)
        out(mid=mid, first=first, second=second, f1=forms(a1), f2=forms(a2),
            reads=(whole(v1) == d1, whole(v2) == d2), errors=errors())
        """)
    assert r["mid"] == [
        {"raw": False, "zst": True},
        {"raw": False, "zst": True},
        "zstd",
        True,
    ]
    assert (r["first"], r["second"]) == ("decompressed", "decompressed")
    assert r["f1"] == r["f2"] == {"raw": True, "zst": False}
    assert r["reads"] == [True, True] and r["errors"] == []


def test_the_ve_compress_thread_makes_deltas_too(run):
    r = run(
        TWO_VERSIONS,
        """
        ve._COMPRESS_START_DELAY = 0
        ve._COMPRESS_SWEEP_GRACE = 0
        t = threading.Thread(target=eng._compress_loop, daemon=True, name="ve-compress")
        t.start()
        deadline = time.time() + 40
        while time.time() < deadline and row(a2)["codec"] != "zstd":
            time.sleep(0.2)
        eng._stop_scheduling.set(); eng._shutdown_event.set()
        t.join(timeout=15)
        out(base=base_of(a2), a1=a1, alive=t.is_alive(), read=(whole(v2) == d2))
        """,
    )
    assert r["base"] == r["a1"] and r["alive"] is False and r["read"]


# ------------------------------------------------------------------ the hand tools

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
    """


def test_status_shows_the_deltas_and_the_delta_setting(run):
    r = run(
        CLI,
        TWO_VERSIONS,
        """
        settle()
        code, text = cli("--status")
        config.VERSION_COMPRESSION_DELTA_ENABLED = False
        code_off, text_off = cli("--status")
        out(code=code, text=text, text_off=text_off)
        """,
    )
    assert r["code"] == 0
    assert (
        "deltas  : 1 object(s) are stored as a delta against 1 base object(s)"
        in r["text"]
    )
    assert "previous-version delta is ON" in r["text"]
    assert "previous-version delta is OFF" in r["text_off"]


def test_verify_sweep_and_decompress_work_on_a_store_with_deltas(run):
    r = run(
        CLI,
        TWO_VERSIONS,
        """
        eng.run_compress_batch()
        sweep_code, sweep_text = cli("--sweep")
        verify_code, verify_text = cli("--verify", "--busy-percent", "100")
        config.VERSION_COMPRESSION_ENABLED = False
        dec_code, dec_text = cli("--decompress", "--yes")
        out(sweep=(sweep_code, "1 raw copy(ies) removed" in sweep_text),
            verify=(verify_code, "every compressed object is intact" in verify_text),
            dec=(dec_code, "raw files again" in dec_text), row=row(a2),
            reads=(whole(v1) == d1, whole(v2) == d2))
        """,
    )
    assert (
        r["sweep"] == [0, True] and r["verify"] == [0, True] and r["dec"] == [0, True]
    )
    assert r["row"]["codec"] == "raw" and r["row"]["base_sha"] is None
    assert r["reads"] == [True, True]


def test_the_probe_still_reads_a_schema_3_store_with_deltas(run):
    r = run(
        TWO_VERSIONS,
        """
        settle()
        from helpers import version_probe as vp
        report = vp.run_probe(eng.db_path, eng.objects_dir, samples=50, levels=(3,),
                              busy_percent=100, dictionary_test=False, delta_test=False)
        out(eligible=report["store"]["eligible_objects"], read=report["sample"]["read"],
            findings=report["findings"])
        """,
    )
    assert r["read"] > 0 and r["findings"] == {}
