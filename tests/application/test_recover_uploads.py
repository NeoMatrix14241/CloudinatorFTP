"""detect_ready_assemblies() (routes/uploads.py): only COMPLETE uploads are re-queued at startup.

Before 5.17 a chunk folder without `.metadata` was assembled from whatever sequential chunks it
held and published as `recovered_file_<id>`, so an upload interrupted halfway could appear as a
truncated file after a restart. The functions are read out of routes/uploads.py and storage.py
with `ast` and run against a temporary folder (CLAUDE.md 5.17).
"""

import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _functions(path, names):
    source = (ROOT / path).read_text(encoding="utf-8")
    found = {
        n.name: ast.get_source_segment(source, n)
        for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef) and n.name in names
    }
    assert set(found) == set(
        names
    ), f"{path} no longer defines {set(names) - set(found)}"
    return "\n\n".join(found[name] for name in names)


class Queue:
    def __init__(self):
        self.jobs = []

    def add_job(self, file_id, filename, dest_path, total_chunks, session_id=None):
        self.jobs.append((file_id, filename, dest_path, total_chunks))


@pytest.fixture()
def recover(tmp_path):
    storage_ns = {"os": os, "ROOT_DIR": str(tmp_path)}
    exec(
        _functions("storage.py", ["is_safe_path", "verify_chunks_complete"]),
        storage_ns,
    )
    storage = SimpleNamespace(
        is_safe_path=storage_ns["is_safe_path"],
        verify_chunks_complete=storage_ns["verify_chunks_complete"],
    )
    queue = Queue()
    namespace = {
        "os": os,
        "json": json,
        "ROOT_DIR": str(tmp_path),
        "storage": storage,
        "assembly_queue": queue,
    }
    exec(
        _functions(
            "routes/uploads.py", ["_read_upload_metadata", "detect_ready_assemblies"]
        ),
        namespace,
    )

    def run():
        namespace["detect_ready_assemblies"]()
        return queue.jobs

    return run


def _folder(tmp_path, key, chunks, metadata=None, raw_metadata=None):
    folder = tmp_path / ".chunks" / key
    folder.mkdir(parents=True)
    for number in range(chunks):
        (folder / str(number)).write_bytes(b"x" * 4)
    if metadata is not None:
        (folder / ".metadata").write_text(json.dumps(metadata))
    if raw_metadata is not None:
        (folder / ".metadata").write_text(raw_metadata)
    return folder


def _meta(**overrides):
    data = {"filename": "movie.mp4", "dest_path": "", "total_chunks": 3}
    data.update(overrides)
    return data


def test_a_complete_upload_with_metadata_is_queued(recover, tmp_path):
    _folder(tmp_path, "k1", 3, _meta())
    assert recover() == [("k1", "movie.mp4", "", 3)]


def test_a_destination_inside_the_storage_is_kept(recover, tmp_path):
    (tmp_path / "docs").mkdir()
    _folder(tmp_path, "k1", 3, _meta(dest_path="docs"))
    assert recover() == [("k1", "movie.mp4", "docs", 3)]


def test_an_interrupted_upload_without_metadata_is_never_assembled(recover, tmp_path):
    # Chunks 0..2 are sequential, so the old code published them as a truncated file.
    _folder(tmp_path, "k1", 3)
    assert recover() == []


def test_metadata_announcing_more_chunks_than_exist_is_not_queued(recover, tmp_path):
    _folder(tmp_path, "k1", 3, _meta(total_chunks=5))
    assert recover() == []


def test_metadata_announcing_fewer_chunks_than_exist_is_not_queued(recover, tmp_path):
    _folder(tmp_path, "k1", 4, _meta(total_chunks=3))
    assert recover() == []


@pytest.mark.parametrize(
    "metadata",
    [
        _meta(filename=""),
        _meta(filename=None),
        _meta(total_chunks=0),
        _meta(total_chunks="3"),
        _meta(total_chunks=True),
        _meta(total_chunks=None),
        _meta(dest_path=5),
        ["not", "a", "dict"],
    ],
)
def test_unusable_metadata_is_not_queued(recover, tmp_path, metadata):
    _folder(tmp_path, "k1", 3, metadata)
    assert recover() == []


def test_unreadable_metadata_is_not_queued(recover, tmp_path):
    _folder(tmp_path, "k1", 3, raw_metadata="{not json")
    assert recover() == []


def test_a_destination_outside_the_storage_is_not_queued(recover, tmp_path):
    _folder(tmp_path, "k1", 3, _meta(dest_path="../outside"))
    assert recover() == []


def test_a_folder_being_assembled_right_now_is_skipped(recover, tmp_path):
    folder = _folder(tmp_path, "k1", 3, _meta())
    (folder / ".assembling").write_text("1")
    assert recover() == []


def test_only_the_complete_folder_among_several_is_queued(recover, tmp_path):
    _folder(tmp_path, "done", 3, _meta(filename="a.bin"))
    _folder(tmp_path, "half", 2)
    _folder(tmp_path, "early", 3, _meta(filename="b.bin", total_chunks=6))
    assert recover() == [("done", "a.bin", "", 3)]


def test_no_chunks_folder_is_fine(recover):
    assert recover() == []
