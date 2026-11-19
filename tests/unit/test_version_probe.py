"""
Unit tests for helpers/version_probe.py and for `version-manage compress --probe`
(5.46, Phase 0 of VERSION_COMPRESSION_PLAN.md: the READ-ONLY probe of the real object store).

Nothing here starts a server or imports the application. A tiny Version Engine store is built in
a temporary folder with the engine's REAL schema (`_SCHEMA_SQL`, read out of version_engine.py
with `ast`); the tool is loaded with a fake `config` and a fake `version_engine` module, so the
real engine never runs (the way test_version_wal.py does it). Timing never matters: the probe's
`clock` and `sleep` are injected.

The hard rules checked here: the probe writes NOTHING into the store (object tree and database
file byte-identical), opens the database with mode=ro, never calls the engine's _get_engine()
(that creates folders and tables), and uses no asyncio / thread / pool.
"""

import ast
import hashlib
import importlib.util
import itertools
import os
import random
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from helpers import version_probe as vp  # noqa: E402
from helpers import version_zstd as vz  # noqa: E402

needs_zstd = pytest.mark.skipif(not vz.available(), reason="no zstd in this Python")

CHUNK = 32 * 1024


# -- a tiny store with the real schema --------------------------------------------------


def _engine_schema():
    tree = ast.parse((ROOT / "version_engine.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "_SCHEMA_SQL" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("_SCHEMA_SQL not found in version_engine.py")


def _put(objects_dir, data):
    sha = hashlib.sha256(data).hexdigest()
    folder = Path(objects_dir) / sha[:2]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / sha).write_bytes(data)
    return sha


def _dblike(rng, size=CHUNK):
    out = b""
    while len(out) < size:
        out += rng.randbytes(8) + (b"ROW%05d|" % rng.randrange(1000)) * 40
    return out[:size]


class Store:
    """files: three kinds (.qbw db-like, .txt text-like, .jpg random), several versions each,
    where every new version changes a few bytes of one chunk. Plus the odd objects the findings
    need: a tiny one, an orphan, a corrupted file and a row whose file is missing."""

    def __init__(self, root, files=6, versions=3, chunks=2, seed=3):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.db = self.root / "version_engine.sqlite3"
        self.objects.mkdir(parents=True)
        rng = random.Random(seed)
        conn = sqlite3.connect(self.db)
        conn.executescript(_engine_schema())
        now = 1_700_000_000.0
        kinds = ["qbw", "txt", "jpg"]
        for fi in range(files):
            ext = kinds[fi % 3]
            path = f"C:\\QB Data\\sub.dir\\file{fi}.{ext.upper()}"
            conn.execute(
                "INSERT INTO files(path, norm_key, tracking_source, created_at, "
                "last_seen_at) VALUES (?,?,?,?,?)",
                (path, path.lower(), "root", now, now),
            )
            fid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            base = [self._chunk(rng, ext) for _ in range(chunks)]
            for v in range(versions):
                if v:
                    i = rng.randrange(chunks)
                    b = bytearray(base[i])
                    b[100:116] = rng.randbytes(16)
                    base[i] = bytes(b)
                conn.execute(
                    "INSERT INTO versions(file_id, sha256, size, storage_mode, status, "
                    "created_at, completed_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        fid,
                        "0" * 64,
                        CHUNK * chunks,
                        "chunked",
                        "completed",
                        now + v,
                        now + v,
                    ),
                )
                vid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                for ci, data in enumerate(base):
                    sha = _put(self.objects, data)
                    conn.execute(
                        "INSERT OR IGNORE INTO objects(sha256, size, created_at) VALUES (?,?,?)",
                        (sha, len(data), now),
                    )
                    conn.execute(
                        "INSERT INTO version_objects VALUES (?,?,?)", (vid, ci, sha)
                    )
        self.tiny = _put(self.objects, b"tiny object")
        self.orphan = _put(self.objects, rng.randbytes(CHUNK))
        self.corrupt = _put(self.objects, rng.randbytes(CHUNK))
        (self.objects / self.corrupt[:2] / self.corrupt).write_bytes(
            rng.randbytes(CHUNK)
        )
        self.missing = hashlib.sha256(b"never written").hexdigest()
        for sha, size, orphaned in (
            (self.tiny, len(b"tiny object"), None),
            (self.orphan, CHUNK, now),
            (self.corrupt, CHUNK, None),
            (self.missing, CHUNK, None),
        ):
            conn.execute(
                "INSERT INTO objects(sha256, size, created_at, orphaned_since) "
                "VALUES (?,?,?,?)",
                (sha, size, now, orphaned),
            )
        conn.commit()
        conn.close()

    @staticmethod
    def _chunk(rng, ext):
        if ext == "jpg":
            return rng.randbytes(CHUNK)
        if ext == "txt":
            words = [rng.randbytes(4).hex().encode() for _ in range(300)]
            out = b""
            while len(out) < CHUNK:
                out += b" ".join(rng.choice(words) for _ in range(8)) + b"\n"
            return out[:CHUNK]
        return _dblike(rng)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "store")


def _tree_digest(folder):
    digest = hashlib.sha256()
    for dirpath, _dirs, files in sorted(os.walk(folder)):
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            digest.update(os.path.relpath(full, folder).encode())
            digest.update(Path(full).read_bytes())
    return digest.hexdigest()


def _fake_clock(step=1.0):
    counter = itertools.count()
    return lambda: next(counter) * step


def _probe(store, **kw):
    kw.setdefault("levels", (1, 3, 19))
    kw.setdefault("seed", 11)
    kw.setdefault("busy_percent", 100)
    kw.setdefault("samples", 1000)
    return vp.run_probe(str(store.db), str(store.objects), **kw)


# -- small pieces ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, ext",
    [
        ("C:\\QB Data\\file.QBW", ".qbw"),
        ("/srv/data/archive.tar.GZ", ".gz"),
        ("C:\\dir.v2\\README", "(none)"),
        ("noext", "(none)"),
        ("", "(none)"),
    ],
)
def test_extension_grouping_handles_both_slash_styles_and_case(path, ext):
    assert vp._ext_of(path) == ext


def test_levels_are_parsed_sorted_unique_and_range_checked():
    assert vp.parse_levels("19, 3,3,1") == (1, 3, 19)
    for bad in ("0", "23", "x", "", ",,"):
        with pytest.raises(ValueError):
            vp.parse_levels(bad)


def test_human_formatting():
    assert vp.fmt_bytes(0) == "0 B"
    assert vp.fmt_bytes(1536) == "1.5 KiB"
    assert vp.fmt_bytes(5 * 1024**3) == "5.0 GiB"
    assert vp.fmt_duration(30) == "30 s"
    assert vp.fmt_duration(3600) == "60 min"
    assert vp.fmt_duration(7200) == "2.0 h"
    assert vp.fmt_duration(3 * 86400) == "3.0 days"


def test_the_recommended_level_is_the_lowest_within_half_a_percent_of_the_best():
    def stats(sizes):
        return {
            lv: {"stored_bytes": size, "raw_bytes": 1000} for lv, size in sizes.items()
        }

    # 300 is NOT within 0.5 % of 298 (limit 299.49), 299 is: level 19 is the lowest that is.
    got = vp.recommend_level(
        stats({1: 400, 3: 380, 9: 300, 19: 299, 22: 298}), (1, 3, 9, 19, 22)
    )
    assert got == 19
    # levels 3, 9 and 19 are equal: the cheapest of them wins
    assert (
        vp.recommend_level(stats({1: 400, 3: 300, 9: 300, 19: 300}), (1, 3, 9, 19)) == 3
    )
    # not worth it: less than min_saving saved at the pick
    assert vp.recommend_level(stats({1: 990, 3: 985}), (1, 3), min_saving=5) is None
    # nothing measured
    empty = {1: {"stored_bytes": 0, "raw_bytes": 0}}
    assert vp.recommend_level(empty, (1,)) is None


# -- the probe on a store ----------------------------------------------------------------


@needs_zstd
def test_the_report_has_every_section_and_the_recommended_level_line(store):
    report = _probe(store)
    text = vp.format_report(report, str(store.db), str(store.objects))
    for section in (
        "STORE (what the database lists)",
        "SAMPLE",
        "LEVELS",
        "BY FILE EXTENSION",
        "ESTIMATE FOR THE WHOLE STORE",
        "an ESTIMATE",
        "TRAINED DICTIONARY",
        "PREVIOUS-VERSION DELTA",
        "RECOMMENDED LEVEL:",
        "READ-ONLY",
        "--seed 11",
    ):
        assert section in text, section
    assert "  This is a recommendation for the owner to confirm" in text
    assert f"The default VERSION_COMPRESSION_LEVEL is {vz.DEFAULT_LEVEL}" in text
    assert report["recommended_level"] in (1, 3, 19)


@needs_zstd
def test_a_seed_gives_the_same_sample_and_the_same_numbers(store):
    a = _probe(store, samples=12, seed=5)
    b = _probe(store, samples=12, seed=5)
    assert a["sample"]["picked"] == b["sample"]["picked"] == 12
    for lv in a["levels"]:
        assert (
            a["level_stats"][lv]["stored_bytes"] == b["level_stats"][lv]["stored_bytes"]
        )
        assert a["level_stats"][lv]["raw_bytes"] == b["level_stats"][lv]["raw_bytes"]
    assert a["delta"]["pairs_picked"] == b["delta"]["pairs_picked"]


@needs_zstd
def test_the_seed_is_chosen_and_reported_when_none_is_given(store):
    report = vp.run_probe(
        str(store.db), str(store.objects), samples=3, levels=(1,), busy_percent=100
    )
    assert isinstance(report["seed"], int) and report["seed"] > 0


@needs_zstd
def test_orphans_tiny_corrupt_and_missing_objects_are_handled(store):
    report = _probe(store)
    s = report["store"]
    assert (
        s["all_objects"] == s["eligible_objects"] + 1
    )  # only the orphan is not eligible
    sample = report["sample"]
    assert sample["picked"] == s["eligible_objects"]
    assert sample["tiny_objects"] == 1 and sample["tiny_bytes"] == len(b"tiny object")
    findings = report["findings"]
    assert findings["hash_mismatch"]["count"] == 1
    assert findings["hash_mismatch"]["examples"] == [store.corrupt[:16]]
    assert findings["missing"]["count"] == 1
    assert sample["read"] == sample["picked"]
    assert sample["usable"] == sample["picked"] - 2  # the corrupt and the missing one
    text = vp.format_report(report)
    assert "possible disk corruption" in text and "hash_mismatch" in text


@needs_zstd
def test_the_extension_groups_come_from_the_files_that_reference_the_objects(store):
    report = _probe(store)
    exts = {e["ext"]: e for e in report["extensions"]}
    assert {".qbw", ".txt", ".jpg"} <= set(exts)
    # the db-like and text-like chunks shrink a lot, the random ones do not
    assert exts[".qbw"]["stored"][19] < 0.3 * exts[".qbw"]["raw_bytes"]
    assert exts[".txt"]["stored"][19] < 0.5 * exts[".txt"]["raw_bytes"]
    assert exts[".jpg"]["stored"][19] > 0.99 * exts[".jpg"]["raw_bytes"]


@needs_zstd
def test_incompressible_objects_are_counted_and_kept_raw_by_the_rules(store):
    report = _probe(store)
    st = report["level_stats"][19]
    assert 0 < st["not_shrunk"] < st["objects"]
    assert st["kept_bytes"] < report["sample"]["bytes"]
    # kept never exceeds raw: the engine rules never keep a bigger form
    for lv in report["levels"]:
        assert report["level_stats"][lv]["kept_bytes"] <= report["sample"]["bytes"]


@needs_zstd
def test_the_estimate_is_a_proportion_of_the_eligible_bytes(store):
    report = _probe(store)
    eligible = report["store"]["eligible_bytes"]
    for lv in report["levels"]:
        e = report["estimate"][lv]
        assert 0 < e["expected_stored_bytes"] <= eligible
        assert e["saving_bytes"] == pytest.approx(eligible - e["expected_stored_bytes"])
        assert e["migration_seconds"] >= 0
    # the higher level saves at least as much as the lowest one
    assert (
        report["estimate"][19]["saving_bytes"] >= report["estimate"][1]["saving_bytes"]
    )


@needs_zstd
def test_the_previous_version_delta_beats_plain_compression(store):
    report = _probe(store, levels=(3, 19))
    d = report["delta"]
    assert d["tested"] > 0 and d["unusable"] == 0
    assert d["delta_bytes"] * 2 < d["plain_bytes"]
    assert d["smaller"] == d["tested"]
    assert d["pairs_available"] >= d["pairs_picked"]
    assert vp.format_report(report).count("smaller than plain") == 1


@needs_zstd
def test_the_delta_and_dictionary_tests_can_be_switched_off(store):
    report = _probe(store, dictionary_test=False, delta_test=False)
    assert report["dictionary"] is None and report["delta"] is None
    text = vp.format_report(report)
    assert text.count("  not run") == 2


@needs_zstd
def test_the_dictionary_test_runs_and_never_raises_on_small_data(tmp_path):
    big = Store(tmp_path / "big", files=18, versions=2, chunks=2)
    report = _probe(big, levels=(19,))
    d = report["dictionary"]
    assert d["train_objects"] > 0 and d["test_objects"] > 0
    assert "plain_bytes" in d
    for entry in d["sizes"]:  # trained, or a clear error text: never an exception
        assert "bytes" in entry or "error" in entry
    assert "TRAINED DICTIONARY" in vp.format_report(report)


@needs_zstd
def test_the_dictionary_test_is_skipped_with_too_few_objects(tmp_path):
    small = Store(tmp_path / "small", files=1, versions=1, chunks=1)
    report = _probe(small, delta_test=False)
    assert "too few usable objects" in report["dictionary"]["skipped"]


@needs_zstd
def test_a_store_without_changed_chunks_skips_the_delta_with_a_reason(tmp_path):
    flat = Store(tmp_path / "flat", files=3, versions=1, chunks=1)
    report = _probe(flat, dictionary_test=False)
    assert "no file has two completed versions" in report["delta"]["skipped"]


# -- schema v2 (Phase 1) is already understood -------------------------------------------


@needs_zstd
def test_with_a_codec_column_only_raw_objects_are_eligible(store):
    conn = sqlite3.connect(store.db)
    conn.execute("ALTER TABLE objects ADD COLUMN codec TEXT NOT NULL DEFAULT 'raw'")
    sha = conn.execute(
        "SELECT sha256 FROM objects WHERE orphaned_since IS NULL"
    ).fetchone()[0]
    conn.execute("UPDATE objects SET codec='zstd' WHERE sha256=?", (sha,))
    conn.commit()
    conn.close()
    report = _probe(store, dictionary_test=False, delta_test=False)
    assert report["store"]["has_codec_column"] is True
    assert report["store"]["eligible_objects"] == report["store"]["all_objects"] - 2
    assert "stored raw, not orphaned" in vp.format_report(report)


# -- nothing is written ------------------------------------------------------------------


@needs_zstd
def test_the_store_is_byte_identical_after_a_probe(store):
    objects_before = _tree_digest(store.objects)
    db_before = hashlib.sha256(store.db.read_bytes()).hexdigest()
    listing_before = sorted(os.listdir(store.root))
    _probe(store)
    assert _tree_digest(store.objects) == objects_before
    assert hashlib.sha256(store.db.read_bytes()).hexdigest() == db_before
    assert sorted(os.listdir(store.root)) == listing_before  # not even a temp file


@needs_zstd
def test_a_live_writer_is_not_disturbed_and_the_object_store_stays_identical(store):
    """The engine runs while the probe reads: a connection with an open write transaction."""
    writer = sqlite3.connect(store.db, isolation_level=None)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO engine_metadata VALUES ('k', 'v')")
    try:
        objects_before = _tree_digest(store.objects)
        report = _probe(store, delta_test=False, dictionary_test=False)
        assert report["sample"]["usable"] > 0
        assert _tree_digest(store.objects) == objects_before
        writer.execute("COMMIT")
        row = writer.execute(
            "SELECT value FROM engine_metadata WHERE key='k'"
        ).fetchone()
        assert row == ("v",)
    finally:
        writer.close()


@needs_zstd
def test_the_database_is_opened_read_only_and_rejects_every_write(store):
    conn = vp.open_readonly(str(store.db))
    try:
        for statement in (
            "INSERT INTO engine_metadata VALUES ('x', 'y')",
            "DELETE FROM objects",
            "CREATE TABLE z (a)",
            "UPDATE objects SET size = 0",
        ):
            with pytest.raises(sqlite3.OperationalError):
                conn.execute(statement)
    finally:
        conn.close()


@needs_zstd
def test_run_probe_connects_with_mode_ro(monkeypatch, store):
    seen = []
    real = sqlite3.connect

    def spy(database, *args, **kwargs):
        seen.append((database, kwargs.get("uri")))
        return real(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    _probe(store, samples=3, dictionary_test=False, delta_test=False)
    assert seen and all(uri is True and "mode=ro" in db for db, uri in seen)


def test_a_missing_database_is_an_error_and_nothing_is_created(tmp_path):
    missing = tmp_path / "nowhere" / "version_engine.sqlite3"
    with pytest.raises(vp.ProbeError, match="No Version Engine database"):
        vp.run_probe(str(missing), str(tmp_path))
    assert not missing.parent.exists()


@needs_zstd
def test_a_file_that_is_not_a_database_is_a_clear_error(tmp_path):
    junk = tmp_path / "junk.sqlite3"
    junk.write_bytes(b"this is not sqlite" * 100)
    with pytest.raises(vp.ProbeError, match="Cannot read the Version Engine database"):
        vp.run_probe(str(junk), str(tmp_path))


@needs_zstd
def test_a_path_with_spaces_dashes_and_hash_signs_works(tmp_path):
    """The owner's real path is 'C:\\-- IMPORTANT --\\My Projects\\...'."""
    odd = Store(tmp_path / "-- IMPORTANT -- #1" / "My Projects")
    report = _probe(odd, samples=5, dictionary_test=False, delta_test=False)
    assert report["sample"]["usable"] > 0


def test_without_zstd_the_probe_refuses_with_a_clear_message(monkeypatch, tmp_path):
    monkeypatch.setattr(vz, "_z", None)
    with pytest.raises(vp.ProbeError, match="zstd is not available"):
        vp.run_probe(str(tmp_path / "x"), str(tmp_path))


# -- budgets, throttle, Ctrl-C -----------------------------------------------------------


@needs_zstd
def test_the_byte_budget_stops_the_sampling_and_says_so(store):
    report = _probe(store, max_bytes=3 * CHUNK, dictionary_test=False, delta_test=False)
    assert report["stopped"] == "byte budget"
    assert 1 <= report["sample"]["read"] < report["sample"]["picked"]
    assert "stopped early (byte budget)" in vp.format_report(report)


@needs_zstd
def test_the_time_budget_uses_the_injected_clock(store):
    report = _probe(
        store,
        max_seconds=40,
        clock=_fake_clock(1.0),
        dictionary_test=False,
        delta_test=False,
    )
    assert report["stopped"] == "time budget"
    assert report["sample"]["read"] < report["sample"]["picked"]


@needs_zstd
def test_later_phases_are_skipped_not_run_when_the_budget_is_gone(store):
    report = _probe(store, max_bytes=CHUNK)
    assert "stopped early" in report["dictionary"]["skipped"]
    assert "stopped early" in report["delta"]["skipped"]


@needs_zstd
def test_the_duty_cycle_sleeps_between_samples_and_100_percent_never_does(store):
    sleeps = []
    _probe(
        store,
        busy_percent=50,
        sleep=sleeps.append,
        clock=_fake_clock(0.5),
        dictionary_test=False,
        delta_test=False,
    )
    assert sleeps and all(s > 0 for s in sleeps)
    none = []
    _probe(
        store,
        busy_percent=100,
        sleep=none.append,
        clock=_fake_clock(0.5),
        dictionary_test=False,
        delta_test=False,
    )
    assert none == []


@needs_zstd
def test_ctrl_c_ends_the_run_and_still_returns_what_was_measured(monkeypatch, store):
    real = vz.compress
    calls = {"n": 0}

    def interrupting(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 8:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(vz, "compress", interrupting)
    report = _probe(store)
    assert report["interrupted"] is True and report["stopped"] == "interrupted"
    assert 0 < report["sample"]["usable"] < report["sample"]["picked"]
    assert "stopped early (interrupted)" in vp.format_report(report)


@needs_zstd
def test_progress_lines_are_reported(store):
    lines = []
    _probe(store, samples=30, progress=lines.append, delta_test=False)
    assert any("sampled" in line for line in lines)
    assert any("dictionary test" in line for line in lines)


# -- the hard rules, with ast ------------------------------------------------------------

_FORBIDDEN_MODULES = {"asyncio", "concurrent", "anyio", "trio", "quart", "hypercorn"}
_FORBIDDEN_CALLS = {
    "to_thread",
    "run_in_executor",
    "get_event_loop",
    "get_running_loop",
    "new_event_loop",
    "create_task",
    "ensure_future",
    "run_coroutine_threadsafe",
    "ThreadPoolExecutor",
    "ProcessPoolExecutor",
    "submit",
    "Thread",
    "Timer",
}


def _tree(name):
    return ast.parse((ROOT / name).read_text(encoding="utf-8"))


def _async_findings(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [
                a.name for a in node.names if a.name.split(".")[0] in _FORBIDDEN_MODULES
            ]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _FORBIDDEN_MODULES:
                found.append(node.module)
        elif isinstance(
            node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)
        ):
            found.append(type(node).__name__)
        elif isinstance(node, ast.Call):
            fn = node.func
            called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if called in _FORBIDDEN_CALLS:
                found.append(called)
    return found


def test_the_probe_uses_no_asyncio_no_thread_and_no_thread_pool():
    assert _async_findings(_tree("helpers/version_probe.py")) == []


def test_the_probe_is_a_leaf_that_imports_only_the_standard_library_and_the_codec():
    allowed = {"hashlib", "os", "random", "re", "sqlite3", "time", "pathlib", "helpers"}
    for node in ast.walk(_tree("helpers/version_probe.py")):
        if isinstance(node, ast.Import):
            roots = {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
            if roots == {"helpers"}:
                assert {a.name for a in node.names} <= {"version_zstd"}
        else:
            continue
        assert roots <= allowed, roots


def test_the_probe_never_writes_through_sql():
    """No string constant in the probe starts with a statement that changes data."""
    writes = {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "REPLACE"}
    found = []
    for node in ast.walk(_tree("helpers/version_probe.py")):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.strip().split(" ", 1)[0].upper() in writes:
                found.append(node.value[:40])
    assert found == []


# -- the command: version-manage compress --probe ----------------------------------------


class _FakeEngine:
    db_path = None
    objects_dir = None


@pytest.fixture
def tool(monkeypatch, store):
    """tools/version_manage.py loaded against a fake config and a fake version_engine."""
    cfg = types.ModuleType("config")
    cfg.format_bytes = lambda n: f"{n} B"
    cfg.VERSION_WAL_SIZE_LIMIT_MB = 64
    cfg.VERSION_GC_GRACE_PERIOD = 86400
    fake_ve = types.ModuleType("version_engine")
    engine_cls = type("Engine", (_FakeEngine,), {})
    engine_cls.db_path = str(store.db)
    engine_cls.objects_dir = str(store.objects)
    fake_ve.Engine = engine_cls
    fake_ve.VersionEngineError = type("VersionEngineError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "config", cfg)
    monkeypatch.setitem(sys.modules, "version_engine", fake_ve)
    spec = importlib.util.spec_from_file_location(
        "version_manage_probe_under_test", ROOT / "tools" / "version_manage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.store = store
    return module


def _parse(tool, *argv):
    return tool._build_parser().parse_args(list(argv))


def test_compress_is_a_subcommand_with_the_documented_options_and_no_defaults_set(tool):
    args = _parse(tool, "compress", "--probe")
    assert args.command == "compress" and args.probe is True
    for name in (
        "samples",
        "levels",
        "seed",
        "seconds",
        "max_bytes",
        "busy_percent",
        "min_saving",
        "delta_pairs",
        "db",
        "objects",
    ):
        assert getattr(args, name) is None, name
    assert args.no_dictionary is False and args.no_delta is False
    args = _parse(
        tool,
        "compress",
        "--probe",
        "--samples",
        "50",
        "--levels",
        "19,3",
        "--seed",
        "9",
        "--seconds",
        "120",
        "--max-bytes",
        "500",
        "--busy-percent",
        "25",
        "--min-saving",
        "10",
        "--no-dictionary",
        "--no-delta",
        "--delta-pairs",
        "20",
        "--db",
        "x.sqlite3",
        "--objects",
        "objs",
    )
    assert (args.samples, args.levels, args.seed, args.seconds) == (
        50,
        (3, 19),
        9,
        120.0,
    )
    assert (args.max_bytes, args.busy_percent, args.min_saving) == (500.0, 25.0, 10.0)
    assert args.no_dictionary and args.no_delta and args.delta_pairs == 20
    assert (args.db, args.objects) == ("x.sqlite3", "objs")


@pytest.mark.parametrize(
    "bad",
    [
        ["--samples", "0"],
        ["--samples", "many"],
        ["--levels", "0,3"],
        ["--levels", "3,23"],
        ["--levels", "x"],
        ["--seed", "0"],
        ["--seconds", "-1"],
        ["--max-bytes", "-5"],
        ["--busy-percent", "4"],
        ["--busy-percent", "101"],
        ["--min-saving", "51"],
        ["--min-saving", "-1"],
        ["--delta-pairs", "0"],
    ],
)
def test_compress_rejects_out_of_range_values(tool, bad):
    with pytest.raises(SystemExit) as exc:
        _parse(tool, "compress", "--probe", *bad)
    assert exc.value.code == 2


def test_compress_without_an_action_is_an_error_not_a_silent_no_op(tool, capsys):
    assert tool.cmd_compress(_parse(tool, "compress")) == 2
    assert "Choose an action: --probe" in capsys.readouterr().out


def test_compress_options_without_probe_are_an_error_not_silently_ignored(tool, capsys):
    for extra in (
        ["--samples", "5"],
        ["--levels", "3"],
        ["--no-delta"],
        ["--no-dictionary"],
        ["--db", "x"],
    ):
        assert tool.cmd_compress(_parse(tool, "compress", *extra)) == 2
    assert "only apply with --probe" in capsys.readouterr().out


@needs_zstd
def test_compress_probe_prints_the_report_and_exits_0_and_changes_nothing(tool, capsys):
    before = _tree_digest(tool.store.objects)
    db_before = hashlib.sha256(tool.store.db.read_bytes()).hexdigest()
    code = tool.cmd_compress(
        _parse(
            tool,
            "compress",
            "--probe",
            "--levels",
            "1,19",
            "--seed",
            "4",
            "--busy-percent",
            "100",
        )
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "READ-ONLY" in out and "RECOMMENDED LEVEL" in out and "--seed 4" in out
    assert str(tool.store.db) in out
    assert _tree_digest(tool.store.objects) == before
    assert hashlib.sha256(tool.store.db.read_bytes()).hexdigest() == db_before


@needs_zstd
def test_compress_probe_can_aim_at_a_copy_with_db_and_objects(tool, tmp_path, capsys):
    other = Store(tmp_path / "copy")
    code = tool.cmd_compress(
        _parse(
            tool,
            "compress",
            "--probe",
            "--levels",
            "3",
            "--no-dictionary",
            "--no-delta",
            "--busy-percent",
            "100",
            "--db",
            str(other.db),
            "--objects",
            str(other.objects),
        )
    )
    assert code == 0
    assert str(other.db) in capsys.readouterr().out


def test_compress_probe_on_a_missing_database_says_so_and_creates_nothing(
    tool, tmp_path, capsys
):
    tool.ve.Engine.db_path = str(tmp_path / "gone" / "version_engine.sqlite3")
    assert tool.do_compress_probe() == 1
    assert "No Version Engine database" in capsys.readouterr().out
    assert not (tmp_path / "gone").exists()


def test_compress_probe_without_zstd_exits_1_with_the_reason(tool, monkeypatch, capsys):
    monkeypatch.setattr(vz, "_z", None)
    assert tool.do_compress_probe() == 1
    assert "zstd is not available" in capsys.readouterr().out


@needs_zstd
def test_compress_probe_after_ctrl_c_prints_the_partial_report_and_exits_130(
    tool, monkeypatch, capsys
):
    real = vz.compress
    calls = {"n": 0}

    def interrupting(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 6:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(vz, "compress", interrupting)
    assert tool.do_compress_probe(busy_percent=100) == 130
    out = capsys.readouterr().out
    assert "stopped early (interrupted)" in out and "RECOMMENDED LEVEL" in out


def test_the_probe_command_never_calls_get_engine():
    """_get_engine() creates folders and tables: a read-only probe must not use it."""
    checked = 0
    for node in ast.walk(_tree("tools/version_manage.py")):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "do_compress_probe",
            "cmd_compress",
        ):
            checked += 1
            names = {
                (
                    n.func.attr
                    if isinstance(n.func, ast.Attribute)
                    else getattr(n.func, "id", "")
                )
                for n in ast.walk(node)
                if isinstance(n, ast.Call)
            }
            assert not names & {"_get_engine", "_ensure_dirs", "_bootstrap_schema"}
    assert checked == 2


def test_compress_is_a_subcommand_only_the_menu_is_unchanged():
    """Plan 6.11: no new top-level menu entry."""
    source = (ROOT / "tools" / "version_manage.py").read_text(encoding="utf-8")
    menu = source.split("def interactive_menu", 1)[1].split("def _seconds_arg", 1)[0]
    assert "compress" not in menu.lower()


# -- the other actions of `compress` (5.47): dispatch and argument checks ----------------


@pytest.fixture
def dispatched(tool, monkeypatch):
    """Replace the five do_* functions by recorders: only the argument handling is tested."""
    calls = []
    for name in (
        "do_compress_probe",
        "do_compress_status",
        "do_compress_sweep",
        "do_compress_verify",
        "do_compress_decompress",
    ):
        monkeypatch.setattr(
            tool, name, lambda *a, _n=name, **k: calls.append((_n, a, k)) or 0
        )
    return calls


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["--status"], ("do_compress_status", {"db_path": None})),
        (
            ["--status", "--db", "x.sqlite3"],
            ("do_compress_status", {"db_path": "x.sqlite3"}),
        ),
        (
            ["--sweep"],
            ("do_compress_sweep", {"grace": 0.0, "busy_percent": 100.0}),
        ),
        (
            ["--sweep", "--grace", "300", "--busy-percent", "50"],
            ("do_compress_sweep", {"grace": 300.0, "busy_percent": 50.0}),
        ),
        (["--verify"], ("do_compress_verify", {"busy_percent": 50.0})),
        (
            ["--verify", "--busy-percent", "100"],
            ("do_compress_verify", {"busy_percent": 100.0}),
        ),
        (
            ["--decompress"],
            (
                "do_compress_decompress",
                {"yes": False, "force": False, "busy_percent": 100.0},
            ),
        ),
        (
            ["--decompress", "--yes", "--force", "--busy-percent", "25"],
            (
                "do_compress_decompress",
                {"yes": True, "force": True, "busy_percent": 25.0},
            ),
        ),
    ],
)
def test_each_action_reaches_its_function_with_the_documented_defaults(
    tool, dispatched, argv, expected
):
    assert tool.cmd_compress(_parse(tool, "compress", *argv)) == 0
    assert len(dispatched) == 1
    name, _args, kwargs = dispatched[0]
    assert name == expected[0]
    for key, value in expected[1].items():
        assert kwargs[key] == value, key


def test_probe_still_reaches_the_probe_with_its_own_defaults(tool, dispatched):
    assert tool.cmd_compress(_parse(tool, "compress", "--probe")) == 0
    name, _args, kwargs = dispatched[0]
    assert name == "do_compress_probe" and kwargs["busy_percent"] == 50


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--probe", "--status"], "Choose ONE action"),
        (["--sweep", "--decompress"], "Choose ONE action"),
        (["--sweep", "--samples", "5"], "only apply with --probe"),
        (["--status", "--levels", "3"], "only apply with --probe"),
        (["--verify", "--no-delta"], "only apply with --probe"),
        (["--sweep", "--db", "x"], "only apply with --probe"),
        (["--probe", "--grace", "5"], "--grace only applies with --sweep"),
        (["--verify", "--yes"], "only apply with --decompress"),
        (["--sweep", "--force"], "only apply with --decompress"),
        (["--status", "--busy-percent", "50"], "does not apply to --status"),
        (["--yes"], "Choose an action first"),
        (["--grace", "5"], "Choose an action first"),
    ],
)
def test_contradicting_or_orphaned_options_are_an_error_and_nothing_runs(
    tool, dispatched, capsys, argv, message
):
    assert tool.cmd_compress(_parse(tool, "compress", *argv)) == 2
    assert message in capsys.readouterr().out
    assert dispatched == []


def test_no_action_names_every_action(tool, capsys):
    assert tool.cmd_compress(_parse(tool, "compress")) == 2
    out = capsys.readouterr().out
    for word in ("--probe", "--status", "--sweep", "--verify", "--decompress"):
        assert word in out


def test_the_new_options_are_range_checked(tool):
    for bad in (["--grace", "-1"], ["--grace", "99999"], ["--grace", "x"]):
        with pytest.raises(SystemExit) as exc:
            _parse(tool, "compress", "--sweep", *bad)
        assert exc.value.code == 2


def test_the_hand_tools_never_use_threads_asyncio_or_the_engine_loop():
    """The CLI runs one synchronous loop (time.sleep is fine in a plain CLI process)."""
    assert _async_findings(_tree("tools/version_manage.py")) == []
