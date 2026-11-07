"""
5.44 (ASYNC_BLOCKING_REFACTOR_PLAN, T3c, the case the plan missed): the page-load cleanup in
`middleware.before_request` removed abandoned chunk folders (an rmtree each) ON THE EVENT LOOP.
It now lives in `_cleanup_abandoned_uploads_sync`, awaited through `asyncio.to_thread`.

The REAL helper is cut out of `middleware.py` with `ast` (the module cannot be imported: it
registers the application hooks) and run with fakes. A second test reads `before_request` and
checks it hands the helper to a thread instead of calling it.
"""

import ast
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MIDDLEWARE_PATH = ROOT / "middleware.py"
HELPER = "_cleanup_abandoned_uploads_sync"


def _tree():
    return ast.parse(MIDDLEWARE_PATH.read_text(encoding="utf-8"))


class FakeTracker:
    def __init__(self, uploads):
        self.uploads = dict(uploads)  # file_id -> timestamp
        self.untracked = []

    def uploads_for_session(self, session_id):
        return set(self.uploads)

    def upload_timestamp(self, file_id):
        return self.uploads.get(file_id)

    def untrack_upload(self, session_id, file_id):
        self.untracked.append(file_id)
        self.uploads.pop(file_id, None)


class FakeQueue:
    def __init__(self, busy=()):
        self.busy = set(busy)

    def get_job_status(self, file_id):
        return "processing" if file_id in self.busy else None


class FakeStorage:
    def __init__(self, fail=False):
        self.cleaned = []
        self.fail = fail

    def cleanup_chunks(self, file_id):
        if self.fail:
            raise OSError("locked")
        self.cleaned.append(file_id)


def _run(tmp_path, tracker, queue=None, storage=None, marker_for=()):
    nodes = [
        n for n in _tree().body if isinstance(n, ast.FunctionDef) and n.name == HELPER
    ]
    assert len(nodes) == 1, f"middleware.{HELPER} was renamed or removed"
    for file_id in marker_for:
        folder = tmp_path / ".chunks" / file_id
        folder.mkdir(parents=True)
        (folder / ".assembling").write_text("assembling:1")
    namespace = {
        "os": os,
        "time": time,
        "ROOT_DIR": str(tmp_path),
        "chunk_tracker": tracker,
        "assembly_queue": queue or FakeQueue(),
        "storage": storage or FakeStorage(),
        "print": lambda *a, **k: None,
    }
    code = compile(
        ast.Module(body=nodes, type_ignores=[]), str(MIDDLEWARE_PATH), "exec"
    )
    exec(code, namespace)  # noqa: S102
    namespace[HELPER]("session-1")
    return namespace["storage"]


def test_only_uploads_older_than_thirty_seconds_are_cleaned(tmp_path):
    now = time.time()
    tracker = FakeTracker({"old": now - 120, "young": now - 5})
    storage = _run(tmp_path, tracker)
    assert storage.cleaned == ["old"]
    assert tracker.untracked == ["old"]


def test_assembly_protected_uploads_are_kept(tmp_path):
    old = time.time() - 600
    tracker = FakeTracker({"queued": old, "marked": old, "plain": old})
    storage = _run(
        tmp_path, tracker, FakeQueue(busy={"queued"}), marker_for=("marked",)
    )
    assert storage.cleaned == ["plain"]
    assert sorted(tracker.uploads) == ["marked", "queued"]


def test_a_failing_delete_is_swallowed(tmp_path):
    tracker = FakeTracker({"old": time.time() - 600})
    _run(tmp_path, tracker, storage=FakeStorage(fail=True))  # must not raise


def test_before_request_hands_the_helper_to_a_thread():
    hooks = [
        n
        for n in _tree().body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "before_request"
    ]
    assert len(hooks) == 1
    calls = [n for n in ast.walk(hooks[0]) if isinstance(n, ast.Call)]
    direct = [c for c in calls if ast.unparse(c.func) == HELPER]
    threaded = [
        c
        for c in calls
        if ast.unparse(c.func) == "asyncio.to_thread"
        and c.args
        and ast.unparse(c.args[0]) == HELPER
    ]
    assert not direct, "the page-load cleanup is back on the event loop"
    assert len(threaded) == 1
