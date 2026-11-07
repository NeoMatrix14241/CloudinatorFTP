"""
5.44 (ASYNC_BLOCKING_REFACTOR_PLAN, T3b): `core.ChunkTracker` must not hold its lock while it
touches the disk.

The tracker lock is also taken ON THE EVENT LOOP (`track_upload` for every chunk, `get_stats`,
`untrack_upload`). The cleanup methods used to hold it across `os.listdir`, the timestamp
reads and `storage.cleanup_chunks` (an rmtree), so a sweep froze every upload chunk handler.

The REAL class is cut out of `core.py` with `ast` (core.py cannot be imported: it starts the
whole application) and run with a fake `storage`, a fake `assembly_queue` and a temporary
`.chunks` folder.
"""

import ast
import os
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
CORE_PATH = ROOT / "core.py"
WAIT = 1.0  # seconds a lock-free call may take; a held lock would take until the delete ends


class FakeStorage:
    """Records cleanup_chunks calls; optionally blocks inside the first one."""

    def __init__(self, block=False):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = block
        if not block:
            self.release.set()

    def cleanup_chunks(self, file_id):
        self.calls.append(file_id)
        self.entered.set()
        assert self.release.wait(10), "the test never released the fake delete"


class FakeAssemblyQueue:
    def __init__(self):
        self.on_status = None

    def get_job_status(self, file_id):
        if self.on_status:
            self.on_status(file_id)
        return None


def _load(tmp_path, storage):
    tree = ast.parse(CORE_PATH.read_text(encoding="utf-8"))
    nodes = [
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ChunkTracker"
    ]
    assert len(nodes) == 1, "core.ChunkTracker was renamed or removed"
    assembly_queue = FakeAssemblyQueue()
    namespace = {
        "os": os,
        "time": time,
        "threading": threading,
        "ROOT_DIR": str(tmp_path),
        "storage": storage,
        "assembly_queue": assembly_queue,
        "print": lambda *a, **k: None,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(CORE_PATH), "exec"),
        namespace,
    )  # noqa: S102
    return namespace["ChunkTracker"](), assembly_queue


def _make_chunk_dir(tmp_path, file_id, age_seconds=None):
    folder = tmp_path / ".chunks" / file_id
    folder.mkdir(parents=True)
    (folder / "0").write_bytes(b"x")
    if age_seconds is not None:
        (folder / ".timestamp").write_text(str(time.time() - age_seconds))
    return folder


def _run_in_thread(fn, *args):
    thread = threading.Thread(
        target=fn, args=args, name="sweep-under-test", daemon=True
    )
    thread.start()
    return thread


def _tracker_answers_while_delete_is_blocked(tracker, storage, start_sweep):
    """Start a sweep that blocks inside the fake delete, then use the tracker the way the
    event loop does. True when the tracker answered within WAIT seconds."""
    sweep = _run_in_thread(start_sweep)
    assert storage.entered.wait(5), "the sweep never reached the delete"
    done = threading.Event()

    def use_tracker():
        tracker.track_upload("another-session", "another-file")
        tracker.get_stats()
        tracker.untrack_upload("another-session", "another-file")
        done.set()

    _run_in_thread(use_tracker)
    answered = done.wait(WAIT)
    storage.release.set()
    sweep.join(5)
    return answered


# --------------------------------------------------------------------- lock scope


def test_orphan_sweep_does_not_hold_the_lock_while_it_deletes(tmp_path):
    storage = FakeStorage(block=True)
    tracker, _ = _load(tmp_path, storage)
    _make_chunk_dir(tmp_path, "orphan", age_seconds=3 * 3600)
    assert _tracker_answers_while_delete_is_blocked(
        tracker, storage, tracker.cleanup_orphaned_chunks
    )
    assert storage.calls == ["orphan"]


def test_interrupted_sweep_does_not_hold_the_lock_while_it_deletes(tmp_path):
    storage = FakeStorage(block=True)
    tracker, _ = _load(tmp_path, storage)
    tracker.track_upload("s1", "idle-file")
    tracker.upload_timestamps["idle-file"] = time.time() - 3600
    assert _tracker_answers_while_delete_is_blocked(
        tracker, storage, tracker.cleanup_interrupted_uploads
    )
    assert storage.calls == ["idle-file"]


def test_session_cleanup_does_not_hold_the_lock_while_it_deletes(tmp_path):
    storage = FakeStorage(block=True)
    tracker, _ = _load(tmp_path, storage)
    tracker.track_upload("s1", "file-a")
    assert _tracker_answers_while_delete_is_blocked(
        tracker, storage, lambda: tracker.cleanup_session_chunks("s1")
    )
    assert storage.calls == ["file-a"]


# ------------------------------------------------------------- behaviour is unchanged


def test_orphan_sweep_thresholds(tmp_path):
    storage = FakeStorage()
    tracker, _ = _load(tmp_path, storage)
    _make_chunk_dir(tmp_path, "untracked-old", age_seconds=2701)
    _make_chunk_dir(tmp_path, "untracked-young", age_seconds=600)
    _make_chunk_dir(tmp_path, "tracked-fresh", age_seconds=0)
    _make_chunk_dir(tmp_path, "tracked-stale", age_seconds=0)
    marked = _make_chunk_dir(tmp_path, "assembling", age_seconds=9999)
    (marked / ".assembling").write_text("assembling:1")
    tracker.track_upload("s1", "tracked-fresh")
    tracker.track_upload("s1", "tracked-stale")
    tracker.upload_timestamps["tracked-stale"] = time.time() - 3601

    tracker.cleanup_orphaned_chunks()

    assert sorted(storage.calls) == ["tracked-stale", "untracked-old"]
    assert (
        "tracked-stale" not in tracker.upload_timestamps
    )  # untracked after the delete
    assert "tracked-fresh" in tracker.upload_timestamps


def test_orphan_sweep_skips_an_upload_that_became_active_after_the_snapshot(tmp_path):
    storage = FakeStorage()
    tracker, queue = _load(tmp_path, storage)
    _make_chunk_dir(tmp_path, "woke-up", age_seconds=3 * 3600)
    # the chunk handler tracks the upload after the sweep took its snapshot
    queue.on_status = lambda file_id: tracker.track_upload("s1", file_id)

    tracker.cleanup_orphaned_chunks()

    assert storage.calls == []


def test_stale_tracked_upload_that_got_a_chunk_meanwhile_is_kept(tmp_path):
    storage = FakeStorage()
    tracker, queue = _load(tmp_path, storage)
    _make_chunk_dir(tmp_path, "slow-client", age_seconds=0)
    tracker.track_upload("s1", "slow-client")
    tracker.upload_timestamps["slow-client"] = time.time() - 3601
    # a new chunk arrives (fresh timestamp) after the snapshot, before the delete
    queue.on_status = lambda file_id: tracker.track_upload("s1", file_id)

    tracker.cleanup_orphaned_chunks()

    assert storage.calls == []
    assert "slow-client" in tracker.upload_timestamps


def test_interrupted_sweep_cleans_only_idle_uploads(tmp_path):
    storage = FakeStorage()
    tracker, _ = _load(tmp_path, storage)
    tracker.track_upload("s1", "idle")
    tracker.track_upload("s1", "busy")
    tracker.upload_timestamps["idle"] = time.time() - 1801

    tracker.cleanup_interrupted_uploads()

    assert storage.calls == ["idle"]
    assert tracker.uploads_for_session("s1") == {"busy"}


def test_interrupted_sweep_skips_an_upload_that_got_a_chunk_after_the_scan(tmp_path):
    storage = FakeStorage()
    tracker, _ = _load(tmp_path, storage)
    tracker.track_upload("s1", "idle")
    tracker.upload_timestamps["idle"] = time.time() - 1801
    real = tracker.upload_timestamp

    def woke_up(file_id):  # the second look sees a fresh chunk
        tracker.track_upload("s1", file_id)
        return real(file_id)

    tracker.upload_timestamp = woke_up
    tracker.cleanup_interrupted_uploads()

    assert storage.calls == []
    assert tracker.uploads_for_session("s1") == {"idle"}


def test_session_cleanup_removes_every_entry_of_that_session_only(tmp_path):
    storage = FakeStorage()
    tracker, _ = _load(tmp_path, storage)
    tracker.track_upload("s1", "a")
    tracker.track_upload("s1", "b")
    tracker.track_upload("s2", "c")

    tracker.cleanup_session_chunks("s1")
    tracker.cleanup_session_chunks("never-seen")  # no entry: nothing happens

    assert sorted(storage.calls) == ["a", "b"]
    assert tracker.uploads_for_session("s1") == set()
    assert tracker.uploads_for_session("s2") == {"c"}
    assert tracker.get_stats()["tracked_files"] == ["c"]


def test_a_failing_delete_does_not_stop_the_rest(tmp_path):
    class Flaky(FakeStorage):
        def cleanup_chunks(self, file_id):
            super().cleanup_chunks(file_id)
            if file_id == "a":
                raise OSError("locked")

    storage = Flaky()
    tracker, _ = _load(tmp_path, storage)
    tracker.track_upload("s1", "a")
    tracker.track_upload("s1", "b")

    tracker.cleanup_session_chunks("s1")

    assert sorted(storage.calls) == ["a", "b"]


@pytest.mark.parametrize("method", ["uploads_for_session", "upload_timestamp"])
def test_the_read_helpers_exist(tmp_path, method):
    tracker, _ = _load(tmp_path, FakeStorage())
    assert callable(getattr(tracker, method))
