"""Upload chunk keys (routes/uploads.py) and chunks_complete (storage.py), CLAUDE.md 5.16.

The pure helpers are read out of the two modules with `ast` and run in a small namespace, so no
app or server is needed. The end-to-end behaviour (two users, out-of-order chunks) is covered by
tests/application/test_upload_integrity.py.
"""

import ast
import hashlib
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _extract(path, names):
    source = path.read_text(encoding="utf-8")
    parts = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            parts[node.name] = ast.get_source_segment(source, node)
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in names:
                parts[node.targets[0].id] = ast.get_source_segment(source, node)
    missing = set(names) - set(parts)
    assert not missing, f"{path.name} no longer defines {sorted(missing)}"
    return "\n\n".join(parts[name] for name in names)


@pytest.fixture()
def storage_ns(tmp_path):
    names = ["is_safe_chunk_id", "chunks_complete"]
    namespace = {"os": os, "ROOT_DIR": str(tmp_path)}
    exec(_extract(ROOT / "storage.py", names), namespace)
    return namespace


@pytest.fixture()
def keys(storage_ns):
    names = [
        "MAX_CLIENT_UPLOAD_ID_LEN",
        "_valid_client_upload_id",
        "_key_prefix",
        "_chunk_key",
        "_client_file_id",
    ]
    storage = type(
        "S", (), {"is_safe_chunk_id": staticmethod(storage_ns["is_safe_chunk_id"])}
    )
    namespace = {"hashlib": hashlib, "storage": storage}
    exec(_extract(ROOT / "routes" / "uploads.py", names), namespace)
    return namespace


def test_same_upload_id_in_two_sessions_gives_two_keys(keys):
    a = keys["_chunk_key"]("session-a", "fid_1_104857600")
    b = keys["_chunk_key"]("session-b", "fid_1_104857600")
    assert a and b and a != b


def test_same_session_and_id_always_gives_the_same_key(keys):
    first = keys["_chunk_key"]("session-a", "fid_1_8_abcd")
    assert first == keys["_chunk_key"]("session-a", "fid_1_8_abcd")


def test_key_is_one_safe_folder_name_and_round_trips(keys, storage_ns):
    longest = "f" * keys["MAX_CLIENT_UPLOAD_ID_LEN"]
    for file_id in ("fid_1_8", "fid_27_0_0123456789abcdef", longest):
        key = keys["_chunk_key"]("session-a", file_id)
        assert storage_ns["is_safe_chunk_id"](key)
        assert keys["_client_file_id"]("session-a", key) == file_id


def test_a_session_cannot_name_another_sessions_folder(keys):
    key_of_a = keys["_chunk_key"]("session-a", "fid_1_8")
    # b sending a's folder name as its own id gets a different folder, not a's
    assert keys["_chunk_key"]("session-b", key_of_a) != key_of_a


@pytest.mark.parametrize(
    "bad", ["", ".", "..", "../x", "a/b", "a\\b", "a:b", "a\x00b", "x" * 129, None, 5]
)
def test_unusable_ids_and_missing_sessions_have_no_key(keys, bad):
    assert keys["_chunk_key"]("session-a", bad) is None


@pytest.mark.parametrize("session_id", [None, ""])
def test_no_session_means_no_key(keys, session_id):
    assert keys["_chunk_key"](session_id, "fid_1_8") is None


def _write(tmp_path, key, numbers):
    folder = tmp_path / ".chunks" / key
    folder.mkdir(parents=True, exist_ok=True)
    for number in numbers:
        (folder / str(number)).write_bytes(b"x")


def test_chunks_complete_needs_every_number_in_any_order(storage_ns, tmp_path):
    complete = storage_ns["chunks_complete"]
    _write(tmp_path, "k", [4])
    assert not complete("k", 5)  # last chunk early
    _write(tmp_path, "k", [0, 2])
    assert not complete("k", 5)  # still missing 1 and 3
    _write(tmp_path, "k", [1])
    assert not complete("k", 5)  # still missing 3
    _write(tmp_path, "k", [3])
    assert complete("k", 5)


def test_chunks_complete_edge_cases(storage_ns, tmp_path):
    complete = storage_ns["chunks_complete"]
    _write(tmp_path, "one", [0])
    assert complete("one", 1)
    assert not complete("one", 2)
    assert not complete("one", 0)
    assert not complete("missing-folder", 1)
    assert not complete("../escape", 1)
    assert not complete("one", "1")
