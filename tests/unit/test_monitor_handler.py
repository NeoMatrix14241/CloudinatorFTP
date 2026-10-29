"""file_monitor.InstantFileEventHandler: the counters and the calls into the two indexes (5.40).

The handler is the part of file_monitor.py that turns watchdog events into counter changes
(file_count / dir_count / total_size, and the per-folder dir_info records) and into calls on
`file_index_manager` (the folder index) and `search_index_manager` (the search index). A wrong
counter is repaired by `_correct_folders()` a few seconds later, so these tests pin down what the
INSTANT path does, not what the correction pass eventually makes of it.

file_monitor.py starts a watchdog observer and threads and imports `config` (which reads the real
server_config.json), so it is never imported. Its handler class, the three small helpers it uses
and four constants are read out of the source with `ast` and run against a fake monitor, two
recording fakes for the indexes and a temporary folder, the same technique as
test_assemble_atomic.py. Nothing here touches the real project, a socket or a thread.

5.40: a hidden -> visible rename inside one folder (storage.assemble_chunks publishes
`.assembling_<hex>.part` onto the final name with os.replace) now counts the new file, a
visible -> hidden rename uncounts it, and a hidden name never enters the search index.
"""

import ast
import functools
import os
import threading
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_FUNCTIONS = {"_rel", "_parents", "_timed_handler"}
_CONSTANTS = {"SLOW_HANDLER_LOG_SECS", "BURST_THRESHOLD", "BURST_WINDOW"}
_CLASS = "InstantFileEventHandler"


def _handler_source():
    source = (ROOT / "file_monitor.py").read_text(encoding="utf-8")
    parts, found = [], set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in _FUNCTIONS:
            parts.append(ast.get_source_segment(source, node))
            found.add(node.name)
        elif isinstance(node, ast.ClassDef) and node.name == _CLASS:
            parts.append(ast.get_source_segment(source, node))
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & _CONSTANTS:
                parts.append(ast.get_source_segment(source, node))
                found |= names & _CONSTANTS
    missing = (_FUNCTIONS | _CONSTANTS | {_CLASS}) - found
    assert not missing, f"not found in file_monitor.py: {sorted(missing)}"
    # Functions first (the decorator is applied while the class body runs), then the class.
    parts.sort(key=lambda text: text.startswith("class "))
    return "\n\n".join(parts)


class _Recorder:
    """Stands in for file_index_manager / search_index_manager: records every call."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, *args))

        return record


class _FakeMonitor:
    def __init__(self, root):
        self.root_path = str(root)
        self.lock = threading.RLock()
        self._reconcile_epoch = 0
        self._pending_reconcile = False
        self._file_count = 0
        self._dir_count = 0
        self._total_size = 0
        self._dir_info = {"": {"file_count": 0, "dir_count": 0, "total_size": 0}}
        self.ignored_prefixes = []
        self.dirty = []
        self.remapped = []
        self.handler_seconds = []
        self.events_noted = 0

    # --- the monitor API the handler calls
    def is_ignored_path(self, path):
        return any(path.startswith(p) for p in self.ignored_prefixes)

    def mark_folder_dirty(self, rel_path, abs_path):
        # The real monitor keeps a dict, so a folder marked twice (the handler marks it from
        # _touch() and again in its index section) is one entry: tests compare set(dirty).
        self.dirty.append(rel_path)

    def remap_dirty(self, src_rel, dest_rel):
        self.remapped.append((src_rel, dest_rel))

    def set_pending_reconcile(self):
        self._pending_reconcile = True

    def _note_handler_time(self, secs):
        self.handler_seconds.append(secs)

    def _note_event(self):
        self.events_noted += 1

    # --- test helpers
    def add_folder(self, rel, files=0, size=0, dirs=0):
        self._dir_info[rel] = {
            "file_count": files,
            "dir_count": dirs,
            "total_size": size,
        }

    def info(self, rel):
        return dict(self._dir_info[rel])

    def totals(self):
        return self._file_count, self._dir_count, self._total_size


@pytest.fixture()
def lab(tmp_path):
    root = tmp_path / "storage"
    root.mkdir()
    monitor = _FakeMonitor(root)
    file_index, search_index = _Recorder(), _Recorder()
    namespace = {
        "os": os,
        "time": time,
        "threading": threading,
        "functools": functools,
        "FileSystemEventHandler": object,
        "file_index_manager": file_index,
        "search_index_manager": search_index,
    }
    exec(_handler_source(), namespace)
    handler = namespace[_CLASS](monitor)
    notified = []
    # The real _schedule_notify starts a Timer thread; here it only counts.
    handler._schedule_notify = lambda: notified.append(1)
    return types.SimpleNamespace(
        root=root,
        monitor=monitor,
        handler=handler,
        file_index=file_index,
        search=search_index,
        notified=notified,
    )


def _event(src, dest=None, is_directory=False):
    return types.SimpleNamespace(
        src_path=str(src),
        dest_path=str(dest) if dest is not None else None,
        is_directory=is_directory,
    )


def _make_file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


# ---------------------------------------------------------------------------- on_moved, files
def test_a_hidden_name_renamed_to_a_visible_one_in_the_same_folder_is_counted(lab):
    # The assemble_chunks publish: .assembling_<hex>.part -> movie.bin, one folder.
    final = _make_file(lab.root / "movie.bin", 10)
    lab.handler.on_moved(_event(lab.root / ".assembling_ab12.part", final))
    assert lab.monitor.totals() == (1, 0, 10)
    assert lab.monitor.info("") == {"file_count": 1, "dir_count": 0, "total_size": 10}
    assert ("add", "movie.bin", "movie.bin", False) in lab.search.calls
    assert not [
        c for c in lab.search.calls if c[0] == "remove"
    ], "a hidden name was never indexed"
    assert set(lab.monitor.dirty) == {
        ""
    }, "the folder is marked for the correction pass"
    assert lab.notified == [1]


def test_the_count_reaches_every_ancestor_of_the_folder(lab):
    lab.monitor.add_folder("a")
    lab.monitor.add_folder("a/b")
    final = _make_file(lab.root / "a" / "b" / "movie.bin", 7)
    lab.handler.on_moved(_event(lab.root / "a" / "b" / ".assembling_x.part", final))
    for folder in ("a/b", "a", ""):
        assert lab.monitor.info(folder) == {
            "file_count": 1,
            "dir_count": 0,
            "total_size": 7,
        }, folder
    assert lab.monitor.totals() == (1, 0, 7)


def test_a_visible_name_renamed_to_a_hidden_one_is_uncounted(lab):
    lab.monitor._file_count, lab.monitor._total_size = 3, 30
    lab.monitor._dir_info[""] = {"file_count": 3, "dir_count": 0, "total_size": 30}
    hidden = _make_file(lab.root / ".secret", 10)
    lab.handler.on_moved(_event(lab.root / "visible.txt", hidden))
    assert lab.monitor.totals() == (2, 0, 20)
    assert lab.monitor.info("") == {"file_count": 2, "dir_count": 0, "total_size": 20}
    assert ("remove", "visible.txt") in lab.search.calls
    assert not [
        c for c in lab.search.calls if c[0] == "add"
    ], "hidden names stay out of the index"


def test_a_rename_between_two_visible_names_in_one_folder_changes_no_count(lab):
    lab.monitor._file_count, lab.monitor._total_size = 1, 10
    lab.monitor._dir_info[""] = {"file_count": 1, "dir_count": 0, "total_size": 10}
    renamed = _make_file(lab.root / "new.txt", 10)
    lab.handler.on_moved(_event(lab.root / "old.txt", renamed))
    assert lab.monitor.totals() == (1, 0, 10)
    assert lab.monitor.info("") == {"file_count": 1, "dir_count": 0, "total_size": 10}
    assert ("remove", "old.txt") in lab.search.calls
    assert ("add", "new.txt", "new.txt", False) in lab.search.calls


def test_a_move_between_folders_transfers_the_count_and_keeps_the_totals(lab):
    lab.monitor._file_count, lab.monitor._total_size = 1, 10
    lab.monitor._dir_info[""] = {"file_count": 1, "dir_count": 2, "total_size": 10}
    lab.monitor.add_folder("a", files=1, size=10)
    lab.monitor.add_folder("b")
    moved = _make_file(lab.root / "b" / "f.txt", 10)
    lab.handler.on_moved(_event(lab.root / "a" / "f.txt", moved))
    assert lab.monitor.info("a") == {"file_count": 0, "dir_count": 0, "total_size": 0}
    assert lab.monitor.info("b") == {"file_count": 1, "dir_count": 0, "total_size": 10}
    assert lab.monitor.info("")["file_count"] == 1, "the common ancestor is unchanged"
    assert lab.monitor.totals() == (
        1,
        0,
        10,
    ), "a move between two visible names: no global change"
    assert set(lab.monitor.dirty) == {"a", "b"}


def test_a_hidden_file_moved_into_another_folder_under_a_visible_name_is_counted_once(
    lab,
):
    lab.monitor.add_folder("a")
    lab.monitor.add_folder("b")
    moved = _make_file(lab.root / "b" / "f.txt", 4)
    lab.handler.on_moved(_event(lab.root / "a" / ".f.part", moved))
    assert (
        lab.monitor.info("a")["file_count"] == 0
    ), "the hidden source was never counted"
    assert lab.monitor.info("b") == {"file_count": 1, "dir_count": 0, "total_size": 4}
    assert lab.monitor.info("")["file_count"] == 1
    assert lab.monitor.totals() == (1, 0, 4)


def test_a_rename_between_two_hidden_names_is_ignored_completely(lab):
    hidden = _make_file(lab.root / ".b.part", 5)
    lab.handler.on_moved(_event(lab.root / ".a.part", hidden))
    assert lab.monitor.totals() == (0, 0, 0)
    assert lab.monitor.dirty == [] and lab.search.calls == [] and lab.notified == []


def test_the_counters_never_go_below_zero(lab):
    hidden = _make_file(lab.root / ".gone", 5)
    lab.handler.on_moved(
        _event(lab.root / "visible.txt", hidden)
    )  # nothing was counted
    assert lab.monitor.totals() == (0, 0, 0)
    assert lab.monitor.info("") == {"file_count": 0, "dir_count": 0, "total_size": 0}


def test_a_file_that_vanished_again_still_counts_with_size_zero(lab):
    lab.handler.on_moved(
        _event(lab.root / ".x.part", lab.root / "gone.bin")
    )  # no such file
    assert lab.monitor.totals() == (1, 0, 0)


def test_while_a_walk_is_pending_the_counters_are_left_to_the_walk(lab):
    lab.monitor._pending_reconcile = True
    final = _make_file(lab.root / "movie.bin", 10)
    lab.handler.on_moved(_event(lab.root / ".assembling_ab12.part", final))
    assert lab.monitor.totals() == (0, 0, 0)
    assert set(lab.monitor.dirty) == {
        ""
    }, "the folder is still marked for the correction pass"
    assert lab.notified == [1]


def test_a_move_inside_the_apps_own_folders_is_ignored(lab):
    cache = lab.root / "cache"
    lab.monitor.ignored_prefixes = [str(cache)]
    lab.handler.on_moved(_event(cache / "a.tmp", cache / "a.json"))
    assert lab.monitor.dirty == [] and lab.search.calls == [] and lab.notified == []


# ---------------------------------------------------------------------------- on_moved, folders
def test_a_renamed_folder_moves_its_records_and_tells_both_indexes(lab):
    lab.monitor._dir_count = 1
    lab.monitor._dir_info[""] = {"file_count": 2, "dir_count": 1, "total_size": 20}
    lab.monitor.add_folder("old", files=2, size=20)
    lab.monitor.add_folder("old/sub")
    (lab.root / "new").mkdir()
    lab.handler.on_moved(_event(lab.root / "old", lab.root / "new", is_directory=True))
    assert "old" not in lab.monitor._dir_info and "old/sub" not in lab.monitor._dir_info
    assert lab.monitor.info("new")["file_count"] == 2
    assert "new/sub" in lab.monitor._dir_info
    assert ("rename_folder", "old", "new") in lab.file_index.calls
    assert ("rename_tree", "old", "new") in lab.search.calls
    assert lab.monitor.remapped == [("old", "new")]
    assert set(lab.monitor.dirty) == {""}, "old and new parent are the same folder"


def test_a_folder_moved_to_another_parent_marks_both_parents(lab):
    lab.monitor.add_folder("p")
    lab.monitor.add_folder("q")
    lab.monitor.add_folder("p/d", files=1, size=5)
    (lab.root / "q" / "d").mkdir(parents=True)
    lab.handler.on_moved(
        _event(lab.root / "p" / "d", lab.root / "q" / "d", is_directory=True)
    )
    assert set(lab.monitor.dirty) == {"p", "q"}
    assert (
        lab.monitor.info("q")["file_count"] == 1
        and lab.monitor.info("p")["file_count"] == 0
    )


def test_a_folder_move_transfers_the_totals_of_the_whole_ancestor_chain(lab):
    # p/d holds 2 files (20 bytes) and one sub-folder; it moves to q/d. Every old ancestor loses
    # exactly what moved (the folder itself plus everything inside), every new ancestor gains it,
    # and the root, which is in both chains, ends up unchanged.
    lab.monitor._dir_info[""] = {"file_count": 2, "dir_count": 4, "total_size": 20}
    lab.monitor.add_folder("p", files=2, size=20, dirs=2)
    lab.monitor.add_folder("q")
    lab.monitor.add_folder("p/d", files=2, size=20, dirs=1)
    lab.monitor.add_folder("p/d/inner")
    (lab.root / "q" / "d" / "inner").mkdir(parents=True)
    lab.handler.on_moved(
        _event(lab.root / "p" / "d", lab.root / "q" / "d", is_directory=True)
    )
    assert lab.monitor.info("p") == {"file_count": 0, "dir_count": 0, "total_size": 0}
    assert lab.monitor.info("q") == {"file_count": 2, "dir_count": 2, "total_size": 20}
    assert lab.monitor.info("") == {"file_count": 2, "dir_count": 4, "total_size": 20}
    assert lab.monitor.info("q/d") == {
        "file_count": 2,
        "dir_count": 1,
        "total_size": 20,
    }
    assert (
        "q/d/inner" in lab.monitor._dir_info
        and "p/d/inner" not in lab.monitor._dir_info
    )


def test_a_folder_renamed_to_a_hidden_name_is_one_folder_fewer_for_its_parents(lab):
    lab.monitor._dir_info[""] = {"file_count": 1, "dir_count": 1, "total_size": 5}
    lab.monitor.add_folder("visible", files=1, size=5)
    (lab.root / ".visible").mkdir()
    lab.handler.on_moved(
        _event(lab.root / "visible", lab.root / ".visible", is_directory=True)
    )
    root = lab.monitor.info("")
    assert root["dir_count"] == 0, "the folder itself is no longer counted"
    assert (
        root["file_count"] == 1 and root["total_size"] == 5
    ), "what is inside it still is"


def test_a_move_out_of_the_chunk_folder_is_not_mistaken_for_chunk_housekeeping(lab):
    # `.chunks` only on the SOURCE side: a real move into the storage (both sides must be in
    # .chunks for the event to be ignored).
    lab.monitor.add_folder("a")
    moved = _make_file(lab.root / "a" / "f.bin", 6)
    lab.handler.on_moved(_event(lab.root / ".chunks" / "fid" / "0", moved))
    assert lab.monitor.info("a")["file_count"] == 1
    assert lab.search.calls, "the search index is told"


def test_a_move_between_two_chunk_paths_is_ignored(lab):
    first = _make_file(lab.root / ".chunks" / "fid" / "0", 3)
    lab.handler.on_moved(_event(first, lab.root / ".chunks" / "fid" / "1"))
    assert lab.monitor.totals() == (0, 0, 0)
    assert lab.search.calls == [] and lab.monitor.dirty == [] and lab.notified == []


@pytest.mark.parametrize("ignored", ["source", "destination"])
def test_a_move_with_only_one_end_in_the_apps_own_folders_is_still_handled(
    lab, ignored
):
    cache = lab.root / "cache"
    lab.monitor.ignored_prefixes = [str(cache)]
    lab.monitor.add_folder("a")
    if ignored == "source":
        moved = _make_file(lab.root / "a" / "f.txt", 4)
        lab.handler.on_moved(_event(cache / "f.txt", moved))
    else:
        moved = _make_file(cache / "f.txt", 4)
        lab.handler.on_moved(_event(lab.root / "a" / "f.txt", moved))
    assert lab.search.calls, "one end is a user folder: the indexes must hear about it"
    assert lab.notified == [1]


# ---------------------------------------------------------------------------- on_created
def test_a_created_file_is_counted_and_indexed(lab):
    new = _make_file(lab.root / "sub" / "photo.jpg", 12)
    lab.monitor.add_folder("sub")
    lab.handler.on_created(_event(new))
    assert lab.monitor.totals() == (1, 0, 12)
    assert (
        lab.monitor.info("sub")["file_count"] == 1
        and lab.monitor.info("")["file_count"] == 1
    )
    assert ("add", "sub/photo.jpg", "photo.jpg", False) in lab.search.calls
    assert "sub" in lab.monitor.dirty
    assert lab.notified == [1]


def test_a_created_folder_is_seeded_in_dir_info_and_both_indexes_are_told(lab):
    (lab.root / "newdir").mkdir()
    lab.handler.on_created(_event(lab.root / "newdir", is_directory=True))
    assert lab.monitor.totals() == (0, 1, 0)
    assert lab.monitor.info("newdir") == {
        "file_count": 0,
        "dir_count": 0,
        "total_size": 0,
    }
    assert lab.monitor.info("")["dir_count"] == 1
    assert ("add", "newdir", "newdir", True) in lab.search.calls
    assert "newdir" in lab.monitor.dirty and "" in lab.monitor.dirty


@pytest.mark.parametrize(
    "relative",
    [".hidden.txt", ".chunks/fid/0", "sub/.assembling_ab.part"],
    ids=["hidden file", "inside .chunks", "hidden temp file in a folder"],
)
def test_created_hidden_entries_and_chunks_are_not_counted_or_indexed(lab, relative):
    path = _make_file(lab.root / relative, 3)
    lab.handler.on_created(_event(path))
    assert lab.monitor.totals() == (0, 0, 0)
    assert (
        lab.search.calls == []
        and lab.file_index.calls == []
        and lab.monitor.dirty == []
    )


def test_a_created_file_in_the_apps_own_folder_is_ignored(lab):
    db = lab.root / "db"
    lab.monitor.ignored_prefixes = [str(db)]
    lab.handler.on_created(_event(_make_file(db / "x.sqlite", 3)))
    assert lab.monitor.totals() == (0, 0, 0) and lab.search.calls == []


def test_a_burst_of_created_files_arms_the_settle_walk(lab):
    for n in range(200):  # BURST_THRESHOLD
        lab.handler.on_created(_event(_make_file(lab.root / f"f{n}.txt", 1)))
    assert lab.monitor._pending_reconcile is True


# ---------------------------------------------------------------------------- on_deleted
def test_a_deleted_file_is_uncounted_and_removed_from_the_search_index(lab):
    lab.monitor._file_count = 2
    lab.monitor._dir_info[""] = {"file_count": 2, "dir_count": 0, "total_size": 0}
    lab.handler.on_deleted(_event(lab.root / "old.txt"))
    assert lab.monitor._file_count == 1 and lab.monitor.info("")["file_count"] == 1
    assert ("remove", "old.txt") in lab.search.calls
    assert lab.monitor.dirty.count("") >= 1


def test_a_deleted_folder_drops_its_records_and_both_indexes_forget_it(lab):
    lab.monitor._file_count, lab.monitor._dir_count, lab.monitor._total_size = 3, 2, 30
    lab.monitor._dir_info[""] = {"file_count": 3, "dir_count": 2, "total_size": 30}
    lab.monitor.add_folder("gone", files=3, size=30, dirs=1)
    lab.monitor.add_folder("gone/inner")
    lab.handler.on_deleted(_event(lab.root / "gone", is_directory=True))
    assert (
        "gone" not in lab.monitor._dir_info
        and "gone/inner" not in lab.monitor._dir_info
    )
    assert lab.monitor.totals() == (0, 0, 0)
    assert lab.monitor.info("") == {"file_count": 0, "dir_count": 0, "total_size": 0}
    assert ("remove_folder", "gone") in lab.file_index.calls
    assert ("remove_tree", "gone") in lab.search.calls


def test_a_deleted_hidden_file_is_ignored(lab):
    lab.monitor._file_count = 2
    lab.handler.on_deleted(_event(lab.root / ".assembling_ab.part"))
    assert lab.monitor._file_count == 2 and lab.search.calls == []


def test_deleting_the_last_file_brings_every_counter_down_to_exactly_zero(lab):
    lab.monitor._file_count = 1
    lab.monitor._dir_info[""] = {"file_count": 1, "dir_count": 2, "total_size": 0}
    lab.monitor.add_folder("a", files=1, dirs=1)
    lab.monitor.add_folder("a/b", files=1)
    lab.handler.on_deleted(_event(lab.root / "a" / "b" / "only.txt"))
    assert lab.monitor._file_count == 0
    for folder in ("a/b", "a", ""):
        assert lab.monitor.info(folder)["file_count"] == 0, folder


def test_deleting_a_file_that_was_never_counted_cannot_make_a_counter_negative(lab):
    lab.monitor.add_folder("a")
    lab.handler.on_deleted(_event(lab.root / "a" / "ghost.txt"))
    assert lab.monitor._file_count == 0 and lab.monitor.info("a")["file_count"] == 0


def test_a_deleted_folder_takes_its_totals_off_every_ancestor(lab):
    lab.monitor._file_count, lab.monitor._dir_count, lab.monitor._total_size = 5, 3, 50
    lab.monitor._dir_info[""] = {"file_count": 5, "dir_count": 3, "total_size": 50}
    lab.monitor.add_folder("a", files=5, size=50, dirs=2)
    lab.monitor.add_folder("a/b", files=2, size=20, dirs=0)
    lab.handler.on_deleted(_event(lab.root / "a" / "b", is_directory=True))
    assert lab.monitor.info("a") == {"file_count": 3, "dir_count": 1, "total_size": 30}
    assert lab.monitor.info("") == {"file_count": 3, "dir_count": 2, "total_size": 30}
    assert lab.monitor.totals() == (3, 2, 30)


def test_a_deleted_folder_that_was_never_tracked_changes_no_counter(lab):
    lab.monitor._file_count, lab.monitor._dir_count, lab.monitor._total_size = 4, 3, 50
    lab.handler.on_deleted(_event(lab.root / "unknown", is_directory=True))
    assert lab.monitor.totals() == (4, 3, 50)
    assert ("remove_folder", "unknown") in lab.file_index.calls


def test_a_damaged_folder_record_still_counts_the_folder_itself_once(lab):
    lab.monitor._dir_count, lab.monitor._file_count, lab.monitor._total_size = 5, 7, 50
    lab.monitor._dir_info["broken"] = {}  # no counters in the record
    lab.handler.on_deleted(_event(lab.root / "broken", is_directory=True))
    assert lab.monitor.totals() == (7, 4, 50), "only the folder itself is subtracted"


def test_a_created_file_that_vanished_at_once_is_counted_with_size_zero(lab):
    lab.handler.on_created(_event(lab.root / "gone.tmp.bin"))  # never written
    assert lab.monitor.totals() == (1, 0, 0)
    assert lab.monitor.info("") == {"file_count": 1, "dir_count": 0, "total_size": 0}


# ---------------------------------------------------------------------------- the timing wrapper
def test_every_handler_call_reports_its_duration_to_the_monitor(lab):
    lab.handler.on_deleted(_event(lab.root / "x.txt"))
    lab.handler.on_created(_event(_make_file(lab.root / "y.txt", 1)))
    assert len(lab.monitor.handler_seconds) == 2
    assert all(seconds >= 0 for seconds in lab.monitor.handler_seconds)
