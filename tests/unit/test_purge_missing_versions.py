"""
tools/purge_missing_versions.py (CLAUDE.md 5.44.4): the decisions it makes about WHICH tracked
files are gone, what it counts, and what it changes in the Version Engine database.

The tool is loaded by path (its root-module imports are lazy, so no engine, no config and no
server are needed) and runs against a real SQLite file that is built from the engine's own
`_SCHEMA_SQL`, read out of `version_engine.py` with `ast`. Files live in a temporary folder.

The case that matters most is `test_a_cleanup_of_most_tracked_files_is_not_blocked`: the old
tool refused to act when over half of the tracked files were missing (it took that for an
unmounted drive), which is exactly the situation of a database that grew to 250,000 rows while
the folder holds 60,000 files.
"""

import ast
import importlib.util
import ntpath
import sqlite3
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
DAY = 86400


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "purge_missing_versions_under_test",
        ROOT / "tools" / "purge_missing_versions.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine_schema():
    tree = ast.parse((ROOT / "version_engine.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "_SCHEMA_SQL" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    pytest.fail("_SCHEMA_SQL not found in version_engine.py")


tool = _load_tool()


class Db:
    """A throw-away Version Engine database with the engine's real schema."""

    def __init__(self, path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_engine_schema())
        self.conn.commit()
        self._objects = set()

    def add(self, path, versions=(), key=None):
        """versions: (status, age_days, [sha, ...]) tuples. Returns (file_id, [version_ids])."""
        now = time.time()
        cur = self.conn.execute(
            "INSERT INTO files(path, norm_key, tracking_source, created_at, "
            "last_seen_at, deleted) VALUES (?, ?, 'directory', ?, ?, 0)",
            (str(path), key or str(path).lower(), now, now),
        )
        file_id, ids = cur.lastrowid, []
        for status, age_days, shas in versions:
            created = now - age_days * DAY
            vcur = self.conn.execute(
                "INSERT INTO versions(file_id, sha256, size, storage_mode, status, "
                "created_at, completed_at) VALUES (?, ?, 10, 'chunked', ?, ?, ?)",
                (file_id, (shas or ["-"])[0], status, created, created),
            )
            ids.append(vcur.lastrowid)
            for index, sha in enumerate(shas):
                if sha not in self._objects:
                    self.conn.execute(
                        "INSERT INTO objects(sha256, size, created_at) VALUES (?, 100, ?)",
                        (sha, now),
                    )
                    self._objects.add(sha)
                self.conn.execute(
                    "INSERT INTO version_objects(version_id, chunk_index, sha256) "
                    "VALUES (?, ?, ?)",
                    (vcur.lastrowid, index, sha),
                )
        self.conn.commit()
        return file_id, ids

    def status_of(self, version_id):
        row = self.conn.execute(
            "SELECT status, error FROM versions WHERE version_id=?", (version_id,)
        ).fetchone()
        return row["status"], row["error"]


@pytest.fixture
def world(tmp_path):
    """A tracked folder with a file in it (so it is not empty) and a database."""
    folder = tmp_path / "tracked"
    folder.mkdir()
    (folder / "keep.txt").write_text("x")
    return folder, Db(tmp_path / "engine.sqlite3")


def _scan(db, folder, **kw):
    kw.setdefault("min_age_days", 30)
    return tool.scan_tracked(db.path, scope_dirs=[str(folder)], **kw)


# ------------------------------------------------------------------ the counts reconcile
def test_every_file_lands_in_exactly_one_bucket(world):
    folder, db = world
    here = folder / "here.txt"
    here.write_text("y")
    db.add(here, [("completed", 90, ["a"])])  # on disk
    db.add(folder / "old1.txt", [("completed", 90, ["b"])])  # gone, old
    db.add(folder / "old2.txt", [("completed", 40, ["c"])])  # gone, old
    db.add(folder / "new.txt", [("completed", 2, ["d"])])  # gone, but recent
    db.add(folder / "nothing.txt", [("deleted", 90, ["e"])])  # no completed version

    s = _scan(db, folder)

    assert s.files_total == 5
    assert s.with_completed == 4
    assert s.present == 1
    assert s.gone == 3
    assert s.too_recent == 1
    assert len(s.purge) == 2
    assert s.unsure == []
    assert s.present + s.gone + len(s.unsure) == s.with_completed
    assert s.gone == s.too_recent + len(s.purge)


def test_too_recent_files_are_counted_not_dropped(world):
    folder, db = world
    db.add(folder / "recent.txt", [("completed", 5, ["a"])])
    s = _scan(db, folder, min_age_days=30)
    assert (s.gone, s.too_recent, len(s.purge)) == (1, 1, 0)
    s = _scan(db, folder, min_age_days=0)
    assert (s.gone, s.too_recent, len(s.purge)) == (1, 0, 1)


def test_a_gone_file_lists_all_its_completed_versions_only(world):
    folder, db = world
    _fid, ids = db.add(
        folder / "gone.txt",
        [
            ("completed", 90, ["a"]),
            ("completed", 80, ["b"]),
            ("failed", 70, ["c"]),
            ("deleted", 60, ["d"]),
        ],
    )
    s = _scan(db, folder)
    assert len(s.purge) == 1
    assert sorted(s.purge[0]["ids"]) == sorted(ids[:2])
    assert s.purge[0]["versions"] == 2


def test_gone_files_are_summarised_by_extension_and_date(world):
    folder, db = world
    db.add(folder / "a.QBW", [("completed", 5, ["a"])])
    db.add(folder / "b.qbw", [("completed", 9, ["b"])])
    db.add(folder / "c.tlg", [("completed", 2, ["c"])])
    db.add(folder / "noext", [("completed", 40, ["d"])])
    s = _scan(db, folder)  # default 30 days: only "noext" is old enough to purge
    assert s.gone_ext == {".qbw": 2, ".tlg": 1, "(none)": 1}
    assert s.gone_newest_min < s.gone_newest_max
    assert len(s.purge) == 1


class _Args:
    min_age_days = 30.0
    show = 10


def test_the_report_explains_why_recent_gone_files_are_not_purged(world, capsys):
    """The state of a real database: every gone file is younger than --min-age-days, the old
    tool printed "No longer on disk: 0" and said nothing else."""
    folder, db = world
    for i in range(3):
        db.add(folder / f"gone_{i}.qbw", [("completed", 2, [f"g{i}"])])
    s = _scan(db, folder)
    tool._print_report(s, {}, 0, _Args)
    out = capsys.readouterr().out
    assert "3 gone file(s) are NOT in the purge list only because" in out
    assert "younger than 30 day(s)" in out
    assert "--min-age-days N" in out
    assert ".qbw 3" in out
    assert "Nothing to purge." in out


def test_the_age_hint_is_absent_when_nothing_was_held_back(world, capsys):
    folder, db = world
    db.add(folder / "old.txt", [("completed", 90, ["a"])])
    s = _scan(db, folder)
    tool._print_report(s, {}, 100, _Args)
    out = capsys.readouterr().out
    assert "NOT in the purge list" not in out
    assert "Would soft-delete 1 version(s) of 1 file(s)" in out


# ------------------------------------------------------ the discrepancy this version fixes
def test_a_cleanup_of_most_tracked_files_is_not_blocked(world):
    """100 rows, 24 files on disk, 76 gone: the old "over half looks gone" brake refused this
    although the tracked folder is present and full."""
    folder, db = world
    for i in range(24):
        f = folder / f"real_{i}.txt"
        f.write_text("x")
        db.add(f, [("completed", 90, [f"r{i}"])])
    for i in range(76):
        db.add(folder / f"gone_{i}.txt", [("completed", 90, [f"g{i}"])])

    s = _scan(db, folder)

    assert s.gone == 76 and len(s.purge) == 76
    assert s.unsure == []  # nothing is held back as "maybe unmounted"
    assert s.gone / s.files_total > 0.5


def test_the_scope_cross_check_explains_the_difference(world):
    folder, db = world
    a, b = folder / "a.txt", folder / "b.txt"
    a.write_text("1")
    b.write_text("2")
    db.add(a, [("completed", 90, ["a"])], key="key-a")
    db.add(b, [("completed", 90, ["b"])], key="key-b")  # on disk, no longer in scope
    db.add(folder / "gone.txt", [("completed", 90, ["g"])], key="key-g")

    # the engine's walk finds a.txt and one file that has no version yet
    s = _scan(db, folder, scope_keys={"key-a", "key-new"})

    assert s.scope_files == 2
    assert s.present == 2 and s.present_in_scope == 1
    assert s.present_out_of_scope == 1  # b.txt: on disk, excluded, never purged
    assert len(s.purge) == 1


def test_without_scope_keys_the_cross_check_is_skipped(world):
    folder, db = world
    f = folder / "a.txt"
    f.write_text("1")
    db.add(f, [("completed", 90, ["a"])])
    s = _scan(db, folder, scope_keys=None)
    assert s.scope_files is None and s.present_in_scope == 0


# ------------------------------------------------- unavailable places are never called gone
def test_a_missing_tracked_folder_means_cannot_tell_not_gone(tmp_path):
    db = Db(tmp_path / "engine.sqlite3")
    missing = tmp_path / "nas_share"
    for i in range(3):
        db.add(missing / f"f{i}.txt", [("completed", 90, [f"s{i}"])])

    s = tool.scan_tracked(db.path, 30, [str(missing)])

    assert s.gone == 0 and s.purge == []
    assert len(s.unsure) == 3
    assert "missing" in s.unsure[0][1]


def test_an_empty_tracked_folder_is_an_unmounted_share(tmp_path):
    db = Db(tmp_path / "engine.sqlite3")
    mount = tmp_path / "mnt"
    mount.mkdir()  # the mount point exists but nothing is mounted on it
    db.add(mount / "f.txt", [("completed", 90, ["s"])])

    s = tool.scan_tracked(db.path, 30, [str(mount)])

    assert s.purge == [] and len(s.unsure) == 1
    assert "empty" in s.unsure[0][1]


def test_force_treats_unavailable_places_as_deleted(tmp_path):
    db = Db(tmp_path / "engine.sqlite3")
    missing = tmp_path / "gone_for_good"
    db.add(missing / "f.txt", [("completed", 90, ["s"])])

    s = tool.scan_tracked(db.path, 30, [str(missing)], force=True)

    assert s.unsure == [] and len(s.purge) == 1


def test_an_unreadable_tracked_folder_is_not_called_gone(tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()

    def refuse(_path):
        raise PermissionError("denied")

    probe = tool._Probe([str(folder)], scandir=refuse)
    assert "cannot be read" in probe.reason(str(folder / "f.txt"))


def test_a_missing_windows_drive_is_unavailable():
    probe = tool._Probe(
        [], isdir=lambda p: p.upper().startswith("C:"), splitdrive=ntpath.splitdrive
    )
    assert probe.reason("E:\\data\\f.txt") == "E: is not reachable"
    assert probe.reason("C:\\data\\f.txt") is None
    # a UNC share is a "drive" too
    assert "not reachable" in probe.reason("\\\\nas\\share\\f.txt")


def test_a_file_belongs_to_its_most_specific_tracked_folder(tmp_path):
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / "x.txt").write_text("x")  # outer is not empty; inner is
    probe = tool._Probe([str(outer), str(inner)])
    assert "empty" in probe.reason(str(inner / "f.txt"))
    assert probe.reason(str(outer / "other" / "f.txt")) is None


def test_a_sibling_folder_with_the_same_prefix_is_not_under_the_root(tmp_path):
    assert tool._under(str(tmp_path / "data" / "f"), str(tmp_path / "data"))
    assert not tool._under(str(tmp_path / "data_backup" / "f"), str(tmp_path / "data"))


def test_files_outside_every_tracked_folder_are_judged_by_the_file_alone(
    world, tmp_path
):
    folder, db = world
    db.add(tmp_path / "legacy" / "old.txt", [("completed", 90, ["s"])])
    s = _scan(db, folder)
    assert len(s.purge) == 1 and s.unsure == []


# ----------------------------------------------------------------- how much would be freed
def test_a_chunk_shared_with_a_kept_file_is_not_counted_as_freed(world):
    folder, db = world
    kept = folder / "kept.txt"
    kept.write_text("x")
    db.add(kept, [("completed", 90, ["shared", "kept-only"])])
    gone_id, _ = db.add(
        folder / "gone.txt", [("completed", 90, ["shared", "gone-only"])]
    )

    s = _scan(db, folder)
    per_file, total = tool.reclaimable(db.path, s.purge)

    assert total == 100  # only "gone-only"; "shared" is still used by kept.txt
    assert per_file == {gone_id: 100}


def test_a_chunk_used_only_by_purged_files_counts_once_in_the_total(world):
    folder, db = world
    db.add(folder / "g1.txt", [("completed", 90, ["same"])])
    db.add(folder / "g2.txt", [("completed", 90, ["same"])])
    s = _scan(db, folder)
    per_file, total = tool.reclaimable(db.path, s.purge)
    assert total == 100
    assert sorted(per_file.values()) == [
        100,
        100,
    ]  # shown for both files, once in total


# ------------------------------------------------------------------- what it changes
def test_soft_delete_marks_only_completed_versions_and_is_repeatable(world):
    folder, db = world
    _fid, ids = db.add(
        folder / "gone.txt", [("completed", 90, ["a"]), ("failed", 80, ["b"])]
    )
    changed = tool.soft_delete(db.conn, ids, batch=1, pause=0)
    assert changed == 1
    assert db.status_of(ids[0]) == ("deleted", tool._MARK)
    assert db.status_of(ids[1])[0] == "failed"
    assert tool.soft_delete(db.conn, ids, batch=1, pause=0) == 0


def test_undo_restores_versions_whose_chunks_are_still_stored(world, tmp_path):
    folder, db = world
    _fid, ids = db.add(folder / "gone.txt", [("completed", 90, ["a"])])
    objects = tmp_path / "objects"
    objects.mkdir()
    (objects / "a").write_bytes(b"chunk")
    tool.soft_delete(db.conn, ids, pause=0)

    restored, skipped = tool.undo_versions(db.conn, ids, lambda sha: str(objects / sha))

    assert (restored, skipped) == (1, 0)
    assert db.status_of(ids[0]) == ("completed", None)


def test_undo_skips_versions_whose_chunk_file_is_gone(world, tmp_path):
    folder, db = world
    _fid, ids = db.add(folder / "gone.txt", [("completed", 90, ["a"])])
    tool.soft_delete(db.conn, ids, pause=0)

    restored, skipped = tool.undo_versions(
        db.conn, ids, lambda sha: str(tmp_path / "no_such_object" / sha)
    )

    assert (restored, skipped) == (0, 1)
    assert db.status_of(ids[0])[0] == "deleted"


def test_undo_never_touches_a_version_deleted_by_someone_else(world, tmp_path):
    folder, db = world
    _fid, ids = db.add(folder / "gone.txt", [("completed", 90, ["a"])])
    db.conn.execute(
        "UPDATE versions SET status='deleted', error='Deleted by user' "
        "WHERE version_id=?",
        (ids[0],),
    )
    db.conn.commit()
    (tmp_path / "a").write_bytes(b"chunk")

    restored, skipped = tool.undo_versions(
        db.conn, ids, lambda sha: str(tmp_path / sha)
    )

    assert (restored, skipped) == (0, 1)
    assert db.status_of(ids[0])[0] == "deleted"


# ------------------------------------------------------------------ the command line
def test_report_and_apply_cannot_be_combined(capsys):
    assert tool.main(["--report", "--apply"]) == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_the_decision_logic_needs_no_engine_to_import():
    """The root modules are imported inside functions, after sys.path got the project root
    (smoke check 9); a module-level import would make the logic untestable without them.
    """
    tree = ast.parse((ROOT / "tools" / "purge_missing_versions.py").read_text("utf-8"))
    top_level = {
        a.name.split(".")[0]
        for n in tree.body
        if isinstance(n, ast.Import)
        for a in n.names
    } | {
        n.module.split(".")[0]
        for n in tree.body
        if isinstance(n, ast.ImportFrom) and n.module
    }
    assert not top_level & {"config", "version_engine", "database", "core", "app"}


def test_the_old_over_half_brake_is_gone():
    source = (ROOT / "tools" / "purge_missing_versions.py").read_text("utf-8")
    assert "suspicious" not in source
    assert "> 0.5" not in source.replace("scan.gone / scan.files_total > 0.5", "")


def test_byte_formatting():
    assert tool._fmt_bytes(0) == "0 B"
    assert tool._fmt_bytes(1536) == "1.50 KB"
    assert tool._fmt_bytes(5 * 1024**3) == "5.00 GB"
