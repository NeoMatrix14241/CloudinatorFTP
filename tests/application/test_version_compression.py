"""
Version Engine object compression, release 5.46 (READ support, schema 2): the REAL engine in a
scratch copy of the project (own storage, own version database), the way test_version_restore.py
works. VERSION_COMPRESSION_PLAN.md sections 6.3, 6.4, 6.7, 9.

Release 5.46 only READS compressed objects (the `ve-compress` thread is 5.47), so the tests make
the compressed form by hand, exactly as the thread will: `<sha>.zst` = one verified zstd frame
next to (or instead of) the raw `<sha>` file, and the bookkeeping columns on the `objects` row.
What must hold, in every mix of forms: a restore and a download give the identical bytes, a
corrupted compressed object aborts without a partial file, an object that exists in either form
is never written again, the GC removes both forms, a purge undo sees either form, and nothing
depends on the VERSION_COMPRESSION_ENABLED switch (it only controls WRITING).

What is NOT covered here: the compressor thread (5.47, test_version_compress_thread.py), the
HTTP routes (test_version_routes.py) and the CLI (test_version_probe.py, test_version_compress.py).
"""

import json
import textwrap
import uuid

import pytest

pytestmark = pytest.mark.application

PRELUDE = textwrap.dedent("""
    import json, os, random, sys, time, hashlib, threading, sqlite3, logging
    import config
    cwd = os.path.abspath(os.getcwd())
    for _d in (config.ROOT_DIR, config.DB_DIR, config.VERSION_STORAGE_DIR):
        assert os.path.abspath(_d).startswith(cwd), "NOT inside the scratch copy: " + _d
    config.VERSION_SMALL_FILE_THRESHOLD = 1024 * 1024
    config.VERSION_CHUNK_SIZE = 1024 * 1024
    config.VERSION_RETENTION_ENABLED = False
    config.VERSION_COMPRESSION_ENABLED = False   # reading must never depend on it
    import version_history as vh
    import version_engine as ve
    from helpers import version_zstd as vz
    vh.init()
    eng = vh._get_engine()
    ROOT = config.ROOT_DIR
    TAG = sys.argv[1]
    MIB = 1024 * 1024

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
        # compressible but different per seed, like a database page store
        rng = random.Random(seed)
        block = rng.randbytes(700)
        return (block * (n // 700 + 1))[:n]

    def shas(version_id):
        return [r[0] for r in eng._connect().execute(
            "SELECT sha256 FROM version_objects WHERE version_id=? ORDER BY chunk_index",
            (version_id,))]

    def make_zst(sha, keep_raw=False, level=19):
        # What the 5.47 compressor does for one object: verified frame, published as <sha>.zst,
        # row updated; the raw file goes away unless keep_raw (the minutes before the sweep).
        raw = eng._object_path(sha)
        data = read(raw)
        frame = vz.compress_verified(data, sha, level)
        with open(raw + ".zst", "wb") as f:
            f.write(frame)
        conn = eng._connect()
        conn.execute(
            "UPDATE objects SET codec='zstd', stored_size=?, compress_state='done', "
            "codec_level=?, compressed_at=? WHERE sha256=?",
            (len(frame), level, time.time(), sha))
        conn.commit()
        if not keep_raw:
            os.remove(raw)
        return len(frame)

    def stream_all(v, path):
        ok, msg, size, name, chunks = vh.open_download_stream(path, v)
        return ok, msg, size, b"".join(chunks)
    """)


@pytest.fixture(scope="module")
def lab(scratch_tools, tmp_path_factory):
    root = tmp_path_factory.mktemp("version_compression_lab") / "app"
    scratch_tools.build(root, port=scratch_tools.free_port())
    assert scratch_tools.paths_outside(root) == []
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


# ------------------------------------------------------------------------ schema 2


def test_a_new_database_is_schema_3_with_the_compression_and_delta_columns(run):
    r = run("""
        conn = eng._connect()
        cols = [row[1] for row in conn.execute("PRAGMA table_info(objects)")]
        ver = conn.execute("SELECT value FROM engine_metadata WHERE key='schema_version'").fetchone()[0]
        p = put(f"cmp_{TAG}/a.txt", body(1, 5000))
        v = snap(p)
        row = dict(conn.execute("SELECT * FROM objects LIMIT 1").fetchone())
        out(cols=cols, ver=ver, row=row, schema=ve._SCHEMA_VERSION)
        """)
    assert r["ver"] == "3" and r["schema"] == 3
    for col in (
        "codec",
        "stored_size",
        "compress_state",
        "codec_level",
        "compressed_at",
        "base_sha",
    ):
        assert r["cols"].count(col) == 1, col
    assert r["row"]["codec"] == "raw" and r["row"]["compress_state"] == "pending"
    assert r["row"]["stored_size"] is None and r["row"]["compressed_at"] is None
    assert r["row"]["base_sha"] is None


OLD_DATABASE = """
        OLD = os.path.join(config.DB_DIR, "old_v1_" + TAG + ".sqlite3")
        assert os.path.abspath(OLD).startswith(cwd)
        c = sqlite3.connect(OLD)
        c.executescript('''
            CREATE TABLE engine_metadata (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE objects (sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL,
                                  created_at REAL NOT NULL, orphaned_since REAL);
            CREATE TABLE version_objects (version_id INTEGER NOT NULL, chunk_index INTEGER NOT NULL,
                                          sha256 TEXT NOT NULL, PRIMARY KEY (version_id, chunk_index));
            INSERT INTO engine_metadata VALUES ('schema_version', '1');
            INSERT INTO objects VALUES ('aa', 10, 1.0, NULL), ('bb', 20, 2.0, 5.0);
        ''')
        c.commit(); c.close()
        def engine_on(path):
            e = ve.Engine()
            e.db_path = path
            return e
    """


def test_migrating_a_schema_1_database_keeps_every_row_and_is_idempotent(run):
    r = run(
        OLD_DATABASE,
        """
        e = engine_on(OLD)
        e._bootstrap_schema()
        e._bootstrap_schema()          # twice: a second run changes nothing and raises nothing
        conn = e._connect()
        cols = [row[1] for row in conn.execute("PRAGMA table_info(objects)")]
        rows = [dict(x) for x in conn.execute("SELECT * FROM objects ORDER BY sha256")]
        ver = conn.execute("SELECT value FROM engine_metadata WHERE key='schema_version'").fetchone()[0]
        out(cols=cols, rows=rows, ver=ver)
        """,
    )
    assert r["ver"] == "3"
    assert len(r["cols"]) == len(set(r["cols"])) and "compress_state" in r["cols"]
    assert "base_sha" in r["cols"]
    assert [x["sha256"] for x in r["rows"]] == ["aa", "bb"]
    assert all(
        x["codec"] == "raw" and x["compress_state"] == "pending" for x in r["rows"]
    )
    assert r["rows"][1]["orphaned_since"] == 5.0 and r["rows"][0]["size"] == 10


_RACE = """
        errors = []
        where = []
        barrier = threading.Barrier(4)
        def go():
            try:
                e = engine_on(OLD)      # its own connection (thread-local), like a second process
                barrier.wait()
                e._bootstrap_schema()
            except Exception as exc:    # noqa
                errors.append(repr(exc))
                tb = exc.__traceback__
                while tb.tb_next is not None:
                    tb = tb.tb_next
                where.append(f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno} "
                             f"in {tb.tb_frame.f_code.co_name}")
        ts = [threading.Thread(target=go) for _ in range(4)]
        [t.start() for t in ts]; [t.join() for t in ts]
        c = sqlite3.connect(OLD)
        cols = [row[1] for row in c.execute("PRAGMA table_info(objects)")]
        out(errors=errors, where=where, cols=cols,
            mode=c.execute("PRAGMA journal_mode").fetchone()[0],
            ver=c.execute("SELECT value FROM engine_metadata WHERE key='schema_version'").fetchone()[0])
        """


def test_two_threads_migrating_the_same_old_database_at_once_both_succeed(run):
    """Four connections open an OLD database that is still in rollback-journal mode, in the same
    instant: they race to switch it to WAL AND to add the new columns. 5.47.1 failed here on the
    owner's Windows machine with 'database is locked' (3 of 4 threads): SQLite does not use
    busy_timeout for the switch to WAL, see helpers/version_wal.enable_wal. `where` names the
    last frame of every failure, so a recurrence points at the statement."""
    r = run(OLD_DATABASE, _RACE)
    assert r["errors"] == [], r["where"]
    assert sorted(r["cols"]) == sorted(set(r["cols"]))
    assert r["mode"].lower() == "wal"
    assert r["ver"] == "3"


def test_two_threads_migrating_an_old_database_that_is_already_wal_both_succeed(run):
    """The migration race alone (a real schema-1 database was made by the engine, so it is
    already in WAL mode): the four threads only compete for ALTER TABLE and the version row."""
    r = run(
        OLD_DATABASE,
        """
        c = sqlite3.connect(OLD)
        c.execute("PRAGMA journal_mode=WAL")
        c.close()
        """,
        _RACE,
    )
    assert r["errors"] == [], r["where"]
    assert sorted(r["cols"]) == sorted(set(r["cols"]))
    assert r["mode"].lower() == "wal"
    assert r["ver"] == "3"


def test_opening_an_old_database_waits_for_a_writer_instead_of_failing_at_once(run):
    """The race of the test above, made deterministic: another connection holds the write lock of
    the rollback-mode database for 1.5 s. The engine's first connection must wait it out (the
    bare `PRAGMA journal_mode=WAL` fails in 0 ms whatever busy_timeout says) and then migrate."""
    r = run(
        OLD_DATABASE,
        """
        holder = sqlite3.connect(OLD, isolation_level=None, check_same_thread=False)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO objects VALUES ('cc', 30, 3.0, NULL)")
        threading.Timer(1.5, lambda: holder.execute("COMMIT")).start()
        e = engine_on(OLD)
        started = time.monotonic()
        error = None
        try:
            e._bootstrap_schema()
        except Exception as exc:   # noqa
            error = repr(exc)
        waited = time.monotonic() - started
        time.sleep(0.2)
        c = sqlite3.connect(OLD)
        out(error=error, waited=waited,
            mode=c.execute("PRAGMA journal_mode").fetchone()[0],
            shas=[x[0] for x in c.execute("SELECT sha256 FROM objects ORDER BY sha256")],
            ver=c.execute("SELECT value FROM engine_metadata WHERE key='schema_version'").fetchone()[0])
        """,
    )
    assert r["error"] is None
    assert r["waited"] >= 1.0  # it really waited for the writer, it did not skip anything
    assert r["mode"].lower() == "wal"
    assert r["shas"] == ["aa", "bb", "cc"]  # the writer's row was committed and kept
    assert r["ver"] == "3"


def test_a_schema_2_database_migrates_to_3_with_its_rows_and_a_partial_index(run):
    r = run(
        OLD_DATABASE,
        """
        c = sqlite3.connect(OLD)
        for ddl in (
            "ALTER TABLE objects ADD COLUMN codec TEXT NOT NULL DEFAULT 'raw'",
            "ALTER TABLE objects ADD COLUMN stored_size INTEGER",
            "ALTER TABLE objects ADD COLUMN compress_state TEXT NOT NULL DEFAULT 'pending'",
            "ALTER TABLE objects ADD COLUMN codec_level INTEGER",
            "ALTER TABLE objects ADD COLUMN compressed_at REAL",
        ):
            c.execute(ddl)
        c.execute("UPDATE objects SET codec='zstd', stored_size=3, compress_state='done' WHERE sha256='aa'")
        c.execute("UPDATE engine_metadata SET value='2' WHERE key='schema_version'")
        c.commit(); c.close()
        e = engine_on(OLD)
        e._bootstrap_schema()
        e._bootstrap_schema()
        conn = e._connect()
        rows = [dict(x) for x in conn.execute("SELECT * FROM objects ORDER BY sha256")]
        idx = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_objects_base_sha'"
        ).fetchone()
        ver = conn.execute("SELECT value FROM engine_metadata WHERE key='schema_version'").fetchone()[0]
        out(rows=rows, idx=idx[0] if idx else None, ver=ver)
        """,
    )
    assert r["ver"] == "3"
    assert [x["codec"] for x in r["rows"]] == [
        "zstd",
        "raw",
    ]  # the 5.46 / 5.47 data is kept
    assert all(x["base_sha"] is None for x in r["rows"])
    assert r["idx"] and "WHERE base_sha IS NOT NULL" in r["idx"]


def test_bootstrapping_a_current_database_writes_nothing(run):
    """bootstrap runs at every start of the worker, the web process and every CLI tool: on a
    database that is already current it must only READ (a write transaction would compete for
    SQLite's one write lock with the engine's own work, for nothing)."""
    r = run("""
        writes = []
        import re as _re
        real = ve._GatedConnection.execute
        pattern = _re.compile(r"^\\s*(insert|update|delete|replace|alter|create|drop)\\b", _re.I)
        def spy(self, sql, *a, **k):
            if pattern.match(sql):
                writes.append(sql.strip().split("\\n")[0][:70])
            return real(self, sql, *a, **k)
        ve._GatedConnection.execute = spy
        try:
            eng._bootstrap_schema()
            eng._bootstrap_schema()
        finally:
            ve._GatedConnection.execute = real
        out(writes=writes)
        """)
    assert r["writes"] == []


def test_a_newer_schema_number_is_never_lowered_and_the_old_insert_still_works(run):
    r = run(
        OLD_DATABASE,
        """
        c = sqlite3.connect(OLD)
        c.execute("UPDATE engine_metadata SET value='9' WHERE key='schema_version'")
        c.commit(); c.close()
        e = engine_on(OLD)
        e._bootstrap_schema()
        conn = e._connect()
        ver = conn.execute("SELECT value FROM engine_metadata WHERE key='schema_version'").fetchone()[0]
        # the INSERT the 5.45.1 engine used (explicit columns) still works on a schema-2 table
        conn.execute("INSERT INTO objects(sha256, size, created_at, orphaned_since) VALUES ('cc', 5, 3.0, NULL)")
        conn.commit()
        row = dict(conn.execute("SELECT * FROM objects WHERE sha256='cc'").fetchone())
        out(ver=ver, row=row)
        """,
    )
    assert r["ver"] == "9"
    assert r["row"]["codec"] == "raw" and r["row"]["compress_state"] == "pending"


# ------------------------------------------------------------------------ reading


def test_a_version_restores_and_streams_identically_in_every_mix_of_forms(run):
    r = run("""
        data = body(1, MIB) + body(2, MIB) + body(3, MIB) + body(4, 12345)   # 4 chunks
        p = put(f"cmp_{TAG}/mix.bin", data)
        v = snap(p)
        a, b, c, d = shas(v)
        make_zst(a)                    # compressed only
        make_zst(b, keep_raw=True)     # both forms (the minutes before the sweep)
        # c stays raw only; d is compressed only too
        make_zst(d)
        forms = {n: (os.path.exists(eng._object_path(s)), os.path.exists(eng._zst_path(s)))
                 for n, s in zip("abcd", (a, b, c, d))}
        ok, msg, rel = vh.restore(p, v)
        restored = read(os.path.join(ROOT, rel))
        sok, smsg, size, streamed = stream_all(v, p)
        out(forms=forms, ok=ok, msg=msg, restored_ok=(restored == data), sok=sok, size=size,
            streamed_ok=(streamed == data), streamed_len=len(streamed), want=len(data),
            direct_ok=(b"".join(eng.iter_version_bytes(v)) == data),
            small_blocks_ok=(b"".join(eng.iter_version_bytes(v, block_size=4096)) == data))
        """)
    assert r["forms"] == {
        "a": [False, True],
        "b": [True, True],
        "c": [True, False],
        "d": [False, True],
    }
    assert r["ok"] and r["restored_ok"]
    assert r["sok"] and r["streamed_ok"] and r["size"] == r["want"] == r["streamed_len"]
    assert r["direct_ok"] and r["small_blocks_ok"]


def test_a_small_whole_file_version_in_compressed_form_restores(run):
    r = run("""
        data = body(7, 300_000)
        p = put(f"cmp_{TAG}/small.txt", data)
        v = snap(p)
        (sha,) = shas(v)
        stored = make_zst(sha)
        ok, msg, rel = vh.restore(p, v)
        out(ok=ok, same=(read(os.path.join(ROOT, rel)) == data), stored=stored, raw=len(data))
        """)
    assert r["ok"] and r["same"] and r["stored"] < r["raw"] // 10


def test_reading_never_depends_on_the_compression_switch(run):
    r = run("""
        data = body(8, 2 * MIB + 77)
        p = put(f"cmp_{TAG}/sw.bin", data)
        v = snap(p)
        for s in shas(v):
            make_zst(s)
        res = {}
        for flag in (False, True, False):
            config.VERSION_COMPRESSION_ENABLED = flag
            res[str(flag)] = b"".join(eng.iter_version_bytes(v)) == data
        out(res=res)
        """)
    assert r["res"] == {"False": True, "True": True}


def test_the_raw_form_is_read_when_both_exist_and_either_one_when_one_is_missing(run):
    r = run("""
        p = put(f"cmp_{TAG}/f.bin", body(9, 100_000))
        v = snap(p)
        (sha,) = shas(v)
        make_zst(sha, keep_raw=True)
        both = eng._find_object(sha)
        os.remove(eng._object_path(sha))
        only_zst = eng._find_object(sha)
        make_zst  # noqa
        os.remove(eng._zst_path(sha))
        none = eng._find_object(sha)
        out(both_is_raw=(both == (eng._object_path(sha), False)),
            only_zst=(only_zst == (eng._zst_path(sha), True)), none=none,
            exists_none=eng._object_exists(sha))
        """)
    assert r["both_is_raw"] and r["only_zst"] and r["none"] is None
    assert r["exists_none"] is False


@pytest.mark.parametrize("damage", ["append", "flip", "truncate", "empty"])
def test_a_corrupted_compressed_object_aborts_the_restore_without_a_partial_file(
    run, damage
):
    r = run(f"""
        data = body(1100 + len("{damage}"), 2 * MIB)   # different bytes per case: no shared object
        p = put(f"cmp_{{TAG}}/bad_{damage}.bin", data)
        v = snap(p)
        first, second = shas(v)
        make_zst(first)
        make_zst(second)
        z = eng._zst_path(second)
        blob = bytearray(read(z))
        if "{damage}" == "append":
            blob += b"bit rot"
        elif "{damage}" == "flip":
            blob[len(blob) // 2] ^= 0x01
        elif "{damage}" == "truncate":
            blob = blob[:-9]
        else:
            blob = bytearray()
        with open(z, "wb") as f:
            f.write(bytes(blob))
        ok, msg, rel = vh.restore(p, v)
        folder = os.path.join(ROOT, ".recovered", f"cmp_{{TAG}}")
        left = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
        try:
            got = b"".join(eng.iter_version_bytes(v))
            stream_error = None
        except Exception as exc:
            got, stream_error = b"", str(exc)
        out(ok=ok, msg=msg, rel=rel, left=left, stream_error=stream_error,
            intact=(got != data))
        """)
    assert r["ok"] is False and "Restore failed" in r["msg"] and r["rel"] is None
    assert r["left"] == []  # no half-written file, no leftover temp file
    assert r["stream_error"] and "corrupted" in r["stream_error"]
    assert r["intact"]


def test_a_missing_object_in_both_forms_is_reported_not_crashed(run):
    r = run("""
        p = put(f"cmp_{TAG}/gone.bin", body(12, 50_000))
        v = snap(p)
        (sha,) = shas(v)
        os.remove(eng._object_path(sha))
        ok, msg, rel = vh.restore(p, v)
        try:
            b"".join(eng.iter_version_bytes(v))
            err = None
        except Exception as exc:
            err = str(exc)
        out(ok=ok, msg=msg, err=err)
        """)
    assert r["ok"] is False
    assert r["err"] and "unreadable" in r["err"]


def test_zstd_missing_gives_a_clear_error_and_raw_objects_still_restore(run):
    r = run("""
        raw_data = body(13, 200_000)
        zst_data = body(14, 200_000)
        p_raw = put(f"cmp_{TAG}/r.bin", raw_data)
        p_zst = put(f"cmp_{TAG}/z.bin", zst_data)
        v_raw, v_zst = snap(p_raw), snap(p_zst)
        (s_zst,) = shas(v_zst)
        make_zst(s_zst)
        saved = vz._z
        vz._z = None                      # Python without zstd (a store copied to another machine)
        try:
            ok_raw, _, rel_raw = vh.restore(p_raw, v_raw)
            try:
                b"".join(eng.iter_version_bytes(v_zst))
                err = None
            except Exception as exc:
                err = str(exc)
        finally:
            vz._z = saved
        out(ok_raw=ok_raw, raw_same=(read(os.path.join(ROOT, rel_raw)) == raw_data), err=err)
        """)
    assert r["ok_raw"] and r["raw_same"]
    assert r["err"] and "zstd is not available" in r["err"]


def test_the_object_size_bounds_the_decoder_against_a_decompression_bomb(run):
    r = run("""
        p = put(f"cmp_{TAG}/bomb.bin", body(15, 100_000))
        v = snap(p)
        (sha,) = shas(v)
        bomb = vz.compress(b"\\x00" * 20_000_000, 19)     # a few KB that expand to 20 MB
        os.remove(eng._object_path(sha))
        with open(eng._zst_path(sha), "wb") as f:
            f.write(bomb)
        produced = 0
        try:
            for piece in eng._iter_object_bytes(sha, 100_000):
                produced += len(piece)
            err = None
        except ve._ObjectError as exc:
            err = (exc.kind, str(exc))
        out(err=err, produced=produced)
        """)
    assert r["err"][0] == "corrupted" and "expands beyond" in r["err"][1]
    assert (
        r["produced"] <= 100_000
    )  # nothing beyond the recorded size ever left the decoder


# ------------------------------------------------------------------------ dedup, GC, undo


def test_an_object_that_exists_only_compressed_is_never_written_again_as_raw(run):
    r = run("""
        data = body(21, 2 * MIB + 5)
        p1 = put(f"cmp_{TAG}/one.bin", data)
        v1 = snap(p1)
        for s in shas(v1):
            make_zst(s)
        before = eng._connect().execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        p2 = put(f"cmp_{TAG}/two.bin", data)       # the same bytes under another name
        v2 = snap(p2)
        raw_again = [os.path.exists(eng._object_path(s)) for s in shas(v2)]
        rows = eng._connect().execute(
            "SELECT codec, compress_state FROM objects WHERE sha256 IN (%s)"
            % ",".join("?" * 3), shas(v2)).fetchall()
        after = eng._connect().execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        tmp_left = os.listdir(eng.tmp_dir)
        out(raw_again=raw_again, rows=[list(x) for x in rows], before=before, after=after,
            tmp_left=tmp_left, same=(b"".join(eng.iter_version_bytes(v2)) == data),
            ids=(shas(v1) == shas(v2)))
        """)
    assert r["raw_again"] == [False, False, False]
    assert r["rows"] == [["zstd", "done"]] * 3
    assert r["before"] == r["after"] and r["tmp_left"] == []
    assert r["same"] and r["ids"]


def test_a_duplicate_chunk_makes_no_temp_file_at_all(run):
    """Existence first (plan 6.2): the chunk is already stored, so nothing is written or
    fsynced for it, and the row is refreshed exactly as before."""
    r = run("""
        data = body(22, 3 * MIB)
        v1 = snap(put(f"cmp_{TAG}/d1.bin", data))
        made = []
        real = ve.tempfile.mkstemp
        def spy(*a, **k):
            made.append(k.get("prefix"))
            return real(*a, **k)
        ve.tempfile.mkstemp = spy
        try:
            v2 = snap(put(f"cmp_{TAG}/d2.bin", data))
        finally:
            ve.tempfile.mkstemp = real
        out(made=made, same=(shas(v1) == shas(v2)), v2=v2)
        """)
    assert r["made"] == [] and r["same"]


def test_a_changed_chunk_is_still_stored_next_to_the_unchanged_compressed_ones(run):
    r = run("""
        data = body(23, 2 * MIB)
        p = put(f"cmp_{TAG}/chg.bin", data)
        v1 = snap(p)
        for s in shas(v1):
            make_zst(s)
        changed = data[:MIB] + body(99, MIB)
        put(f"cmp_{TAG}/chg.bin", changed)
        v2 = snap(p)
        s1, s2 = shas(v1), shas(v2)
        out(shared=(s1[0] == s2[0]), new_is_raw=os.path.exists(eng._object_path(s2[1])),
            old_stays_zst=os.path.exists(eng._zst_path(s1[0])) and not os.path.exists(eng._object_path(s1[0])),
            v1_ok=(b"".join(eng.iter_version_bytes(v1)) == data),
            v2_ok=(b"".join(eng.iter_version_bytes(v2)) == changed))
        """)
    assert r["shared"] and r["new_is_raw"] and r["old_stays_zst"]
    assert r["v1_ok"] and r["v2_ok"]


def test_the_gc_removes_both_forms_of_an_object(run):
    r = run("""
        config.VERSION_GC_ENABLED = True
        config.VERSION_GC_GRACE_PERIOD = 0
        pa = put(f"cmp_{TAG}/gc_a.bin", body(31, 80_000))
        pb = put(f"cmp_{TAG}/gc_b.bin", body(32, 80_000))
        va, vb = snap(pa), snap(pb)
        (sa,), (sb,) = shas(va), shas(vb)
        make_zst(sa, keep_raw=True)        # both forms
        make_zst(sb)                       # compressed only
        eng.delete_version(va, "test"); eng.delete_version(vb, "test")
        eng.run_gc(); eng.run_gc()         # mark, then delete (grace period 0)
        gone = {n: (not os.path.exists(eng._object_path(s)), not os.path.exists(eng._zst_path(s)))
                for n, s in (("a", sa), ("b", sb))}
        rows = eng._connect().execute(
            "SELECT COUNT(*) FROM objects WHERE sha256 IN (?, ?)", (sa, sb)).fetchone()[0]
        out(gone=gone, rows=rows)
        """)
    assert r["gone"] == {"a": [True, True], "b": [True, True]}
    assert r["rows"] == 0


def test_the_gc_keeps_a_compressed_object_that_a_live_version_still_uses(run):
    r = run("""
        config.VERSION_GC_ENABLED = True
        config.VERSION_GC_GRACE_PERIOD = 0
        data = body(33, 90_000)
        va = snap(put(f"cmp_{TAG}/live_a.bin", data))
        vb = snap(put(f"cmp_{TAG}/live_b.bin", data))     # same object, two versions
        (sha,) = shas(va)
        make_zst(sha)
        eng.delete_version(va, "test")
        eng.run_gc(); eng.run_gc()
        out(zst_kept=os.path.exists(eng._zst_path(sha)),
            ok=(b"".join(eng.iter_version_bytes(vb)) == data))
        """)
    assert r["zst_kept"] and r["ok"]


def test_a_purge_undo_sees_a_compressed_object_and_refuses_a_freed_one(run):
    r = run("""
        from helpers import version_purge as vp
        pa = put(f"cmp_{TAG}/und_a.bin", body(41, 60_000))
        pb = put(f"cmp_{TAG}/und_b.bin", body(42, 60_000))
        va, vb = snap(pa), snap(pb)
        (sa,), (sb,) = shas(va), shas(vb)
        make_zst(sa)                                   # stored compressed only
        os.remove(eng._object_path(sb))                # freed: in neither form any more
        conn = eng._connect()
        conn.execute("UPDATE versions SET status='deleted', error=? WHERE version_id IN (?, ?)",
                     (vp.MARK, va, vb))
        conn.commit()
        restored, skipped = vp.undo_versions(conn, [va, vb], eng._object_path,
                                             object_exists=eng._object_exists)
        old_style = vp.undo_versions(conn, [va], eng._object_path)   # raw-path check only
        status = {v: conn.execute("SELECT status FROM versions WHERE version_id=?", (v,)).fetchone()[0]
                  for v in (va, vb)}
        out(restored=restored, skipped=skipped, status=status, old_style=list(old_style))
        """)
    assert (r["restored"], r["skipped"]) == (1, 1)
    assert list(r["status"].values()).count("completed") == 1
    assert r["old_style"] == [
        0,
        1,
    ]  # the pre-5.46 call shape still means "raw path only"


def test_the_purge_space_figures_count_the_bytes_on_disk(run):
    r = run("""
        from helpers import version_purge as vp
        data = body(51, 400_000)
        p = put(f"cmp_{TAG}/sz.bin", data)
        v = snap(p)
        (sha,) = shas(v)
        stored = make_zst(sha)
        per_file, total, logical = vp.reclaimable_detail(
            eng.db_path, [{"ids": [v], "file_id": 1}])
        plain = vp.reclaimable(eng.db_path, [{"ids": [v], "file_id": 1}])
        out(total=total, logical=logical, stored=stored, plain_total=plain[1], raw=len(data))
        """)
    assert r["total"] == r["stored"] == r["plain_total"]
    assert r["logical"] == r["raw"] and r["total"] < r["raw"]


def test_crash_recovery_does_not_call_a_compressed_only_object_missing(run):
    r = run("""
        import re
        p = put(f"cmp_{TAG}/cr.bin", body(61, 70_000))
        v = snap(p)
        (sha,) = shas(v)
        records = []
        class H(logging.Handler):
            def emit(self, rec):
                records.append(rec.getMessage())
        h = H(); eng.log.addHandler(h)
        def missing_count():
            # the scratch store is shared with the other tests: count, do not assume zero
            records.clear()
            eng._crash_recovery()
            hits = [m for m in records if "missing from storage" in m]
            return int(re.search(r"(\\d+) referenced", hits[0]).group(1)) if hits else 0
        base = missing_count()
        make_zst(sha)                                   # compressed only: not missing
        with_zst = missing_count()
        os.remove(eng._zst_path(sha))                   # now in neither form
        without = missing_count()
        eng.log.removeHandler(h)
        out(base=base, with_zst=with_zst, without=without)
        """)
    assert r["with_zst"] == r["base"]
    assert r["without"] == r["base"] + 1


def test_the_whole_download_route_data_is_unchanged_for_a_compressed_version(run):
    r = run("""
        data = body(71, 3 * MIB + 11)
        p = put(f"cmp_{TAG}/dl.bin", data)
        v = snap(p)
        for s in shas(v):
            make_zst(s)
        ok, msg, size, name, chunks = vh.open_download_stream(p, v)
        got = b"".join(chunks)
        out(ok=ok, size=size, name=name, same=(got == data), n=len(got), want=len(data))
        """)
    assert r["ok"] and r["same"] and r["size"] == r["n"] == r["want"]


# ------------------------------------------------------------------------ the five settings


SETTINGS_SNIPPET = """
    def load(cfg):
        path = os.path.join(config.DB_DIR, "cfg_" + TAG + ".json")
        assert os.path.abspath(path).startswith(cwd)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        config._SERVER_CONFIG_FILE = path
        # start every case from the in-code defaults, like a fresh server
        config.VERSION_COMPRESSION_ENABLED = False
        config.VERSION_COMPRESSION_LEVEL = 22
        config.VERSION_COMPRESSION_MIN_SAVING_PERCENT = 5
        config.VERSION_COMPRESSION_BUSY_PERCENT = 25
        config.VERSION_COMPRESSION_INTERVAL = 600
        config.load_server_config()
        return [config.VERSION_COMPRESSION_ENABLED, config.VERSION_COMPRESSION_LEVEL,
                config.VERSION_COMPRESSION_MIN_SAVING_PERCENT,
                config.VERSION_COMPRESSION_BUSY_PERCENT, config.VERSION_COMPRESSION_INTERVAL]
    """


def test_the_settings_default_to_off_level_22_and_the_documented_values(run):
    r = run(
        SETTINGS_SNIPPET,
        """
        out(empty=load({}))
        """,
    )
    assert r["empty"] == [False, 22, 5, 25, 600]


def test_the_switch_is_a_real_json_boolean_and_nothing_else_turns_it_on(run):
    r = run(
        SETTINGS_SNIPPET,
        """
        out(cases={repr(v): load({"VERSION_COMPRESSION_ENABLED": v})[0]
                   for v in (True, False, "true", "True", 1, 0, None, [], "yes")})
        """,
    )
    assert r["cases"]["True"] is True
    assert r["cases"]["False"] is False
    for hostile in ("'true'", "'True'", "1", "0", "None", "[]", "'yes'"):
        assert r["cases"][hostile] is False, hostile


def test_each_number_is_bounded_and_a_bad_value_keeps_the_default(run):
    r = run(
        SETTINGS_SNIPPET,
        """
        def one(key, idx, values):
            return {repr(v): load({key: v})[idx] for v in values}
        out(
            level=one("VERSION_COMPRESSION_LEVEL", 1, (1, 9, 22, 0, 23, -3, "19", True, None, 7.0)),
            saving=one("VERSION_COMPRESSION_MIN_SAVING_PERCENT", 2, (0, 5, 12.5, 50, -1, 51, "x", True)),
            busy=one("VERSION_COMPRESSION_BUSY_PERCENT", 3, (5, 25, 100, 4, 101, 0, "50", False)),
            interval=one("VERSION_COMPRESSION_INTERVAL", 4, (60, 600, 86400, 59, 86401, "9", None)),
        )
        """,
    )
    lv = r["level"]
    assert (lv["1"], lv["9"], lv["22"], lv["7.0"]) == (1, 9, 22, 7)
    assert all(lv[k] == 22 for k in ("0", "23", "-3", "'19'", "True", "None"))
    sv = r["saving"]
    assert (sv["0"], sv["12.5"], sv["50"]) == (0, 12.5, 50)
    assert all(sv[k] == 5 for k in ("-1", "51", "'x'", "True"))
    bz = r["busy"]
    assert (bz["5"], bz["100"]) == (5, 100)
    assert all(bz[k] == 25 for k in ("4", "101", "0", "'50'", "False"))
    iv = r["interval"]
    assert (iv["60"], iv["86400"]) == (60, 86400)
    assert all(iv[k] == 600 for k in ("59", "86401", "'9'", "None"))


def test_the_settings_survive_a_save_and_a_load_and_are_written_to_the_file(run):
    r = run(
        SETTINGS_SNIPPET,
        """
        load({})
        config.VERSION_COMPRESSION_ENABLED = True
        config.VERSION_COMPRESSION_LEVEL = 19
        config.VERSION_COMPRESSION_MIN_SAVING_PERCENT = 10
        config.VERSION_COMPRESSION_BUSY_PERCENT = 50
        config.VERSION_COMPRESSION_INTERVAL = 120
        config.save_server_config()          # writes to the temp path set by load()
        with open(config._SERVER_CONFIG_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        config.VERSION_COMPRESSION_ENABLED = False
        config.VERSION_COMPRESSION_LEVEL = 22
        config.load_server_config()
        out(saved={k: v for k, v in saved.items() if k.startswith("VERSION_COMPRESSION")},
            back=[config.VERSION_COMPRESSION_ENABLED, config.VERSION_COMPRESSION_LEVEL])
        """,
    )
    assert r["saved"] == {
        "VERSION_COMPRESSION_ENABLED": True,
        "VERSION_COMPRESSION_LEVEL": 19,
        "VERSION_COMPRESSION_MIN_SAVING_PERCENT": 10,
        "VERSION_COMPRESSION_BUSY_PERCENT": 50,
        "VERSION_COMPRESSION_INTERVAL": 120,
        "VERSION_COMPRESSION_DELTA_ENABLED": False,
        "VERSION_COMPRESSION_DELTA_MIN_GAIN_PERCENT": 20,
    }
    assert r["back"] == [True, 19]


def test_the_shipped_server_config_json_holds_valid_compression_settings():
    """The file the owner edits. Whether compression is switched ON is the OWNER's decision (he
    turns it on and commits it), so this test never looks at the value of the switch, only that
    it is a real JSON boolean (anything else would count as OFF) and that the other settings, if
    present, are inside the bounds the loader accepts (a value outside them is ignored).
    """
    from pathlib import Path

    cfg = json.loads(
        (
            Path(__file__).resolve().parent.parent.parent / "server_config.json"
        ).read_text(encoding="utf-8")
    )
    assert isinstance(cfg.get("VERSION_COMPRESSION_ENABLED", False), bool)
    bounds = {
        "VERSION_COMPRESSION_LEVEL": (1, 22),
        "VERSION_COMPRESSION_MIN_SAVING_PERCENT": (0, 50),
        "VERSION_COMPRESSION_BUSY_PERCENT": (5, 100),
        "VERSION_COMPRESSION_INTERVAL": (60, 86400),
    }
    for key, (low, high) in bounds.items():
        if key in cfg:
            value = cfg[key]
            assert not isinstance(value, bool) and isinstance(value, (int, float)), key
            assert low <= value <= high, (key, value)
