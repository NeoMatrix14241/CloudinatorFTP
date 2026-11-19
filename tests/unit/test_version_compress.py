"""
Unit tests for the compression-related helpers that need no engine (5.46): the purge helper's
space figures and the undo check, on throw-away SQLite files with the OLD (schema 1) and the NEW
(schema 2) `objects` table. The engine itself is covered with a real scratch Engine in
tests/application/test_version_compression.py; the codec in test_version_zstd.py; the probe in
test_version_probe.py.
"""

import ast
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from helpers import version_purge as vp  # noqa: E402

V1 = """
CREATE TABLE objects (sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL,
                      created_at REAL NOT NULL, orphaned_since REAL);
"""
V2 = V1.replace(
    "orphaned_since REAL);",
    "orphaned_since REAL, codec TEXT NOT NULL DEFAULT 'raw', stored_size INTEGER);",
)
COMMON = """
CREATE TABLE versions (version_id INTEGER PRIMARY KEY, file_id INTEGER, status TEXT);
CREATE TABLE version_objects (version_id INTEGER, chunk_index INTEGER, sha256 TEXT);
"""


def _db(tmp_path, ddl, rows):
    path = str(tmp_path / "v.sqlite3")
    conn = sqlite3.connect(path)
    conn.executescript(ddl + COMMON)
    for sha, size, stored in rows:
        if "stored_size" in ddl:
            conn.execute(
                "INSERT INTO objects VALUES (?,?,1.0,NULL,?,?)",
                (sha, size, "zstd" if stored else "raw", stored),
            )
        else:
            conn.execute("INSERT INTO objects VALUES (?,?,1.0,NULL)", (sha, size))
    # version 1 (to purge) uses a, b; version 2 (kept, completed) also uses b
    conn.executemany(
        "INSERT INTO versions VALUES (?,?,?)",
        [(1, 10, "completed"), (2, 11, "completed")],
    )
    conn.executemany(
        "INSERT INTO version_objects VALUES (?,?,?)",
        [(1, 0, "a"), (1, 1, "b"), (2, 0, "b")],
    )
    conn.commit()
    conn.close()
    return path


PURGE = [{"ids": [1], "file_id": 10}]


def test_the_space_figures_are_unchanged_on_a_schema_1_database(tmp_path):
    path = _db(tmp_path, V1, [("a", 1000, None), ("b", 500, None)])
    per_file, total, logical = vp.reclaimable_detail(path, PURGE)
    assert (per_file, total, logical) == ({10: 1000}, 1000, 1000)  # b is shared: kept
    assert vp.reclaimable(path, PURGE) == ({10: 1000}, 1000)


def test_on_a_schema_2_database_with_nothing_compressed_the_figures_are_the_same(
    tmp_path,
):
    path = _db(tmp_path, V2, [("a", 1000, None), ("b", 500, None)])
    assert vp.reclaimable_detail(path, PURGE) == ({10: 1000}, 1000, 1000)


def test_a_compressed_chunk_counts_its_bytes_on_disk_and_the_raw_size_is_shown_too(
    tmp_path,
):
    path = _db(tmp_path, V2, [("a", 1000, 120), ("b", 500, 60)])
    per_file, total, logical = vp.reclaimable_detail(path, PURGE)
    assert per_file == {10: 120} and total == 120  # what the disk gets back
    assert logical == 1000  # the chunk's raw size, shown next to it
    assert vp.reclaimable(path, PURGE) == ({10: 120}, 120)


def test_a_chunk_shared_by_two_purged_files_shows_in_both_but_once_in_the_total(
    tmp_path,
):
    path = _db(tmp_path, V2, [("a", 1000, 120), ("b", 500, 60)])
    two = [{"ids": [1], "file_id": 10}, {"ids": [2], "file_id": 11}]
    per_file, total, logical = vp.reclaimable_detail(path, two)
    assert per_file == {10: 120, 11: 60} or per_file == {10: 180, 11: 60}
    assert total == 180 and logical == 1500  # a + b, each once


UNDO_SCRIPT = V2 + """
CREATE TABLE versions (version_id INTEGER PRIMARY KEY, file_id INTEGER, status TEXT, error TEXT);
CREATE TABLE version_objects (version_id INTEGER, chunk_index INTEGER, sha256 TEXT);
INSERT INTO objects VALUES ('a', 1, 1.0, 5.0, 'zstd', 1), ('b', 1, 1.0, 5.0, 'raw', NULL);
INSERT INTO versions VALUES
    (1, 1, 'deleted', 'purged: file no longer exists (purge_missing_versions.py)'),
    (2, 2, 'deleted', 'purged: file no longer exists (purge_missing_versions.py)');
INSERT INTO version_objects VALUES (1, 0, 'a'), (2, 0, 'b');
"""


def test_undo_checks_either_form_through_the_callable_and_keeps_the_old_call_shape():
    conn = sqlite3.connect(":memory:")
    conn.executescript(UNDO_SCRIPT)
    stored = {"a": "zst", "b": None}  # a: compressed only; b: in neither form

    def exists(sha):
        return stored[sha] is not None

    got = vp.undo_versions(
        conn, [1, 2], lambda s: "/nowhere/" + s, object_exists=exists
    )
    assert got == (1, 1)
    # without the callable the pre-5.46 behaviour: only the raw path counts (none exists here)
    conn.execute("UPDATE versions SET status='deleted' WHERE version_id=1")
    conn.commit()
    assert vp.undo_versions(conn, [1], lambda s: "/nowhere/" + s) == (0, 1)


def test_the_purge_helper_stays_a_stdlib_only_leaf_after_the_change():
    tree = ast.parse(
        (ROOT / "helpers" / "version_purge.py").read_text(encoding="utf-8")
    )
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    assert roots <= {"json", "os", "sqlite3", "threading", "time", "dataclasses"}


@pytest.mark.parametrize("name", ["version_engine.py", "helpers/version_zstd.py"])
def test_no_new_text_file_uses_crlf(name):
    assert b"\\r" not in (ROOT / name).read_bytes()


# -- helpers/version_compress.py (5.47): the compressor's read-only queries and its report ----

from helpers import version_compress as vc  # noqa: E402

V2_FULL = """
CREATE TABLE engine_metadata (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE objects (sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL, created_at REAL NOT NULL,
    orphaned_since REAL, codec TEXT NOT NULL DEFAULT 'raw', stored_size INTEGER,
    compress_state TEXT NOT NULL DEFAULT 'pending', codec_level INTEGER, compressed_at REAL);
"""


def _objects(rows, ddl=V2_FULL):
    conn = sqlite3.connect(":memory:")
    conn.executescript(ddl)
    for r in rows:
        conn.execute(
            "INSERT INTO objects(sha256, size, created_at, orphaned_since, codec, stored_size, "
            "compress_state, codec_level) VALUES (?,?,1.0,?,?,?,?,?)",
            r,
        )
    conn.commit()
    return conn


ROWS = [
    # sha, size, orphaned, codec, stored, state, level
    ("a", 10_000, None, "raw", None, "pending", None),  # eligible
    ("b", 20_000, None, "raw", None, "pending", None),  # eligible
    ("c", 100, None, "raw", None, "pending", None),  # tiny
    ("d", 30_000, 5.0, "raw", None, "pending", None),  # orphaned
    ("e", 40_000, None, "zstd", 4_000, "done", 22),  # compressed, raw copy waiting
    ("f", 50_000, None, "zstd", 5_000, "swept", 22),  # compressed, final
    ("g", 60_000, None, "raw", None, "skip", 3),
    ("h", 70_000, None, "raw", None, "failed", None),
]


def test_candidates_are_the_eligible_raw_objects_after_the_cursor_in_row_order():
    conn = _objects(ROWS)
    got = vc.candidate_batch(conn, 0, 10, 4096)
    assert [sha for _rowid, sha, _size in got] == ["a", "b"]
    assert [x[0] for x in got] == sorted(x[0] for x in got)
    after_first = vc.candidate_batch(conn, got[0][0], 10, 4096)
    assert [sha for _r, sha, _s in after_first] == ["b"]
    assert vc.candidate_batch(conn, got[-1][0], 10, 4096) == []
    assert len(vc.candidate_batch(conn, 0, 1, 4096)) == 1


def test_tiny_objects_are_marked_skip_once_and_only_those():
    conn = _objects(ROWS)
    assert vc.mark_small_objects_skipped(conn, 4096) == 1  # only "c"
    conn.commit()
    states = dict(conn.execute("SELECT sha256, compress_state FROM objects"))
    assert (
        states["c"] == "skip" and states["a"] == "pending" and states["d"] == "pending"
    )
    assert (
        vc.mark_small_objects_skipped(conn, 4096) == 0
    )  # a second run changes nothing


def test_status_counts_on_a_schema_2_database():
    c = vc.status_counts(_objects(ROWS), 4096)
    assert c["schema2"] is True and c["objects"] == 8 and c["orphaned"] == 1
    assert c["states"]["pending"]["objects"] == 4  # a, b, c, d
    assert c["states"]["done"]["objects"] == 1 and c["states"]["swept"]["objects"] == 1
    assert c["states"]["skip"]["objects"] == 1 and c["states"]["failed"]["objects"] == 1
    assert c["zstd_objects"] == 2 and c["zstd_raw_bytes"] == 90_000
    assert c["zstd_stored_bytes"] == 9_000
    assert c["levels"] == {22: 2}
    assert (c["pending_eligible"], c["pending_eligible_bytes"]) == (2, 30_000)
    assert c["raw_copies_waiting"] == 1


def test_status_counts_on_a_schema_1_database_treat_everything_as_raw_and_pending():
    ddl = "CREATE TABLE engine_metadata (key TEXT PRIMARY KEY, value TEXT); CREATE TABLE objects (sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL, created_at REAL NOT NULL, orphaned_since REAL);"
    conn = sqlite3.connect(":memory:")
    conn.executescript(ddl)
    conn.executemany(
        "INSERT INTO objects VALUES (?,?,1.0,?)",
        [("a", 10_000, None), ("b", 100, None), ("c", 5_000, 7.0)],
    )
    c = vc.status_counts(conn, 4096)
    assert c["schema2"] is False and c["objects"] == 3 and c["zstd_objects"] == 0
    assert c["states"]["pending"]["objects"] == 3
    assert c["pending_eligible"] == 1  # only "a": not tiny, not orphaned
    assert "schema 1" in vc.format_status(c, {}, {"enabled": False}, "1.5.7")


def test_the_status_text_says_what_matters():
    c = vc.status_counts(_objects(ROWS), 4096)
    text = vc.format_status(
        c,
        {"compress_running": "1", "compress_last": "2026-11-18 10:00:00 looked_at=5"},
        {"enabled": True, "level": 22, "min_saving": 5, "busy": 25, "interval": 600},
        "1.5.7",
    )
    for needle in (
        "VERSION_COMPRESSION_ENABLED = True",
        "level 22",
        "zstd    : 1.5.7",
        "reported running",
        "looked_at=5",
        "pending 4",
        "compressed 2 (raw copy still on disk: 1)",
        "failed 1",
        "backlog : 2 object(s)",
        "-> 8.8 KiB on disk (10.0 % of raw)",
        "WARNING : objects marked failed",
    ):
        assert needle in text, needle
    off = vc.format_status(
        c, {}, {"enabled": False, "level": 22}, ""
    )  # no zstd, switched off
    assert "NOT AVAILABLE" in off and "compression is OFF" in off
    assert "not running" in off


def test_the_status_helper_is_a_stdlib_only_leaf_with_no_threads():
    tree = ast.parse(
        (ROOT / "helpers" / "version_compress.py").read_text(encoding="utf-8")
    )
    roots, calls = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call):
            fn = node.func
            calls.add(
                fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            )
    assert roots == {"sqlite3"}
    assert not calls & {
        "Thread",
        "Timer",
        "submit",
        "to_thread",
        "run_in_executor",
        "sleep",
    }
    assert not any(
        isinstance(n, (ast.AsyncFunctionDef, ast.Await)) for n in ast.walk(tree)
    )
