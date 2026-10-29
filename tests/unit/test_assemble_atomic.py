"""storage.assemble_chunks publishes the file atomically (CLAUDE.md 5.38).

The chunks used to be written straight into the final path, so a download, a listing or the
file monitor could see an empty or half-written file while the assembly ran, and a failed
assembly deleted an existing file of the same name. Now the chunks go to a hidden `.part` file
in the same folder and `os.replace` moves it onto the target once the size has been verified.

assemble_chunks is read out of storage.py with `ast` and run against fakes and a temporary
folder, so no app and no scratch server is needed.

5.40: the publish step retries os.replace a few times when Windows reports a sharing violation
(PermissionError: another program has the target open) and then fails with a clear message. The
retry tests below use a fake clock, so they never really sleep.
"""

import ast
import os
import stat
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _assemble_chunks_source():
    source = (ROOT / "storage.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == "assemble_chunks":
            return ast.get_source_segment(source, node)
    raise AssertionError("assemble_chunks not found in storage.py")


class _OsProxy:
    """The real os, except that os.replace reports what the folder looks like at that moment."""

    def __init__(self, on_replace):
        self._on_replace = on_replace

    def __getattr__(self, name):
        return getattr(os, name)

    def replace(self, src, dst):
        self._on_replace(src, dst)
        return os.replace(src, dst)


@pytest.fixture()
def lab(tmp_path):
    chunks = tmp_path / ".chunks" / "fid"
    chunks.mkdir(parents=True)
    parts = [b"first-", b"second-", b"third"]
    chunk_map = {}
    for number, data in enumerate(parts):
        path = chunks / str(number)
        path.write_bytes(data)
        chunk_map[number] = {"path": str(path), "size": len(data)}
    return tmp_path, chunk_map, b"".join(parts)


class _FakeClock:
    """The time module as assemble_chunks sees it, except that sleep() only records."""

    def __init__(self):
        self.sleeps = []

    def __getattr__(self, name):
        return getattr(time, name)

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def _run(lab, *, total_size=None, on_replace=lambda src, dst: None, clock=None):
    root, chunk_map, expected = lab
    events = {"cleaned": [], "removed": []}

    def verify_chunks_complete(file_id, total_chunks):
        return {
            "total_chunks": len(chunk_map),
            "total_size": len(expected) if total_size is None else total_size,
            "chunk_map": chunk_map,
            "tmp_dir": str(root / ".chunks" / file_id),
        }

    def safe_remove_file(path):
        events["removed"].append(path)
        os.remove(path)
        return True

    namespace = {
        "os": _OsProxy(on_replace),
        "time": clock if clock is not None else time,
        "stat": stat,
        "uuid": uuid,
        "ROOT_DIR": str(root),
        "verify_chunks_complete": verify_chunks_complete,
        "cleanup_chunks": lambda file_id, *a: events["cleaned"].append(file_id),
        "safe_remove_file": safe_remove_file,
    }
    exec(_assemble_chunks_source(), namespace)
    return namespace["assemble_chunks"], events


def _leftovers(root):
    return [p.name for p in root.iterdir() if p.name.endswith(".part")]


def test_the_target_does_not_exist_while_the_chunks_are_being_written(lab):
    root, _, expected = lab
    seen = {}

    def on_replace(src, dst):
        seen["target_existed"] = os.path.exists(dst)
        seen["src_dir"] = os.path.dirname(src)
        seen["src_content"] = Path(src).read_bytes()
        seen["src_name"] = os.path.basename(src)

    assemble, events = _run(lab, on_replace=on_replace)
    assert assemble("fid", "movie.bin", "", 3) is True
    assert seen["target_existed"] is False
    assert seen["src_dir"] == str(root), "the temp file must be in the target folder"
    assert seen["src_content"] == expected, "the file is replaced only once complete"
    assert seen["src_name"].startswith(".") and seen["src_name"].endswith(".part")
    assert (root / "movie.bin").read_bytes() == expected
    assert _leftovers(root) == []
    assert events["cleaned"] == ["fid"]


def test_an_existing_file_keeps_its_old_content_until_the_new_one_is_complete(lab):
    root, _, expected = lab
    (root / "movie.bin").write_bytes(b"OLD VERSION")
    seen = {}

    def on_replace(src, dst):
        seen["old_content"] = Path(dst).read_bytes()

    assemble, _ = _run(lab, on_replace=on_replace)
    assert assemble("fid", "movie.bin", "", 3) is True
    assert seen["old_content"] == b"OLD VERSION"
    assert (root / "movie.bin").read_bytes() == expected


def test_a_failed_assembly_leaves_an_existing_file_untouched_and_no_temp_file(lab):
    root, _, expected = lab
    (root / "movie.bin").write_bytes(b"OLD VERSION")
    assemble, events = _run(lab, total_size=len(expected) + 1)  # size check fails
    with pytest.raises(ValueError):
        assemble("fid", "movie.bin", "", 3)
    assert (root / "movie.bin").read_bytes() == b"OLD VERSION"
    assert _leftovers(root) == []
    assert events["cleaned"] == [], "the chunks are kept after a failed assembly"


def test_a_failed_assembly_of_a_new_file_publishes_nothing(lab):
    root, _, expected = lab
    assemble, _ = _run(lab, total_size=len(expected) + 1)
    with pytest.raises(ValueError):
        assemble("fid", "movie.bin", "", 3)
    assert not (root / "movie.bin").exists()
    assert _leftovers(root) == []


def test_a_subfolder_gets_its_own_temp_file(lab):
    root, _, expected = lab
    seen = {}
    assemble, _ = _run(
        lab, on_replace=lambda src, dst: seen.update(dir=os.path.dirname(src))
    )
    assert assemble("fid", "movie.bin", "sub", 3) is True
    assert seen["dir"] == str(root / "sub")
    assert (root / "sub" / "movie.bin").read_bytes() == expected


# ---------------------------------------------------------------------------- 5.40: busy target
def _busy_times(count, seen):
    """on_replace hook: record the temp file's content, fail the first `count` calls with the
    Windows sharing violation (a PermissionError)."""

    def on_replace(src, dst):
        seen.append((src, Path(src).read_bytes()))
        if len(seen) <= count:
            raise PermissionError(13, "The process cannot access the file", dst)

    return on_replace


def test_a_target_that_is_busy_for_a_moment_is_published_after_a_retry(lab):
    root, _, expected = lab
    (root / "movie.bin").write_bytes(b"OLD VERSION")
    seen, clock = [], _FakeClock()
    assemble, events = _run(lab, on_replace=_busy_times(2, seen), clock=clock)
    assert assemble("fid", "movie.bin", "", 3) is True
    assert len(seen) == 3, "two refused attempts, the third one publishes"
    assert clock.sleeps == [0.05, 0.1], "a short backoff between the attempts"
    assert (root / "movie.bin").read_bytes() == expected
    assert _leftovers(root) == []
    assert events["cleaned"] == ["fid"], "the chunks go only after the publish worked"


def test_every_retry_replaces_the_same_complete_temp_file(lab):
    # The retry covers the os.replace only: nothing is written again, the temp file stays in the
    # target's folder and holds the complete content on every attempt (the publish stays atomic).
    root, _, expected = lab
    seen = []
    assemble, _ = _run(lab, on_replace=_busy_times(3, seen), clock=_FakeClock())
    assert assemble("fid", "movie.bin", "", 3) is True
    assert len(seen) == 4
    assert len({src for src, _ in seen}) == 1, "one temp file for every attempt"
    assert all(os.path.dirname(src) == str(root) for src, _ in seen)
    assert all(content == expected for _, content in seen)


def test_a_target_that_stays_busy_fails_with_a_clear_message_and_changes_nothing(lab):
    root, _, _ = lab
    (root / "movie.bin").write_bytes(b"OLD VERSION")
    seen, clock = [], _FakeClock()
    assemble, events = _run(lab, on_replace=_busy_times(99, seen), clock=clock)
    with pytest.raises(PermissionError) as caught:
        assemble("fid", "movie.bin", "", 3)
    message = str(caught.value)
    assert "movie.bin" in message and "open in another program" in message
    assert str(root) not in message, "no server path in a message the client may see"
    assert isinstance(
        caught.value.__cause__, PermissionError
    ), "the OS error stays chained"
    assert len(seen) == 7, "a bounded number of attempts"
    assert 2 < sum(clock.sleeps) < 4, "bounded wait: about 3 seconds in total"
    assert (root / "movie.bin").read_bytes() == b"OLD VERSION"
    assert _leftovers(root) == [], "the temp file is removed"
    assert events["cleaned"] == [], "the chunks are kept so the upload can be repeated"


def test_only_a_sharing_violation_is_retried(lab):
    root, _, _ = lab
    calls, clock = [], _FakeClock()

    def on_replace(src, dst):
        calls.append(src)
        raise OSError(28, "No space left on device")

    assemble, events = _run(lab, on_replace=on_replace, clock=clock)
    with pytest.raises(OSError, match="No space left"):
        assemble("fid", "movie.bin", "", 3)
    assert len(calls) == 1 and clock.sleeps == [], "any other error fails at once"
    assert _leftovers(root) == []
    assert events["cleaned"] == []
