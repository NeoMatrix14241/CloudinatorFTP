"""is_safe_path must answer False (never True, never None) when the path check itself fails.

Mutation trial survivors (storage.py::is_safe_path, line 799, `return False` in the except branch):
`return value replaced by None` and `True <-> False`. That branch is unreachable on Linux with a
real path (the NUL check above it catches the only input that raises there), and on Windows it
needs two drives, so the test makes the failure happen on purpose.
"""

import ast
import os
from pathlib import Path

import pytest

STORAGE = Path(
    os.environ.get("STORAGE_PY", Path(__file__).resolve().parents[2] / "storage.py")
)


def _load_is_safe_path(root_dir):
    tree = ast.parse(STORAGE.read_text(encoding="utf-8"))
    nodes = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "is_safe_path"
    ]
    assert nodes, "storage.is_safe_path no longer exists: update this test"
    namespace = {"os": os, "ROOT_DIR": str(root_dir)}
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(STORAGE), "exec"),
        namespace,
    )
    return namespace["is_safe_path"]


def test_a_normal_path_inside_the_root_is_safe(tmp_path):
    assert _load_is_safe_path(tmp_path)("sub/file.txt") is True


@pytest.mark.parametrize(
    "error", [ValueError("different drives"), OSError("cannot resolve")]
)
def test_when_the_check_itself_raises_the_answer_is_exactly_false(
    tmp_path, monkeypatch, error
):
    is_safe_path = _load_is_safe_path(tmp_path)

    def broken(_paths):
        raise error

    monkeypatch.setattr(os.path, "commonpath", broken)
    assert is_safe_path("sub/file.txt") is False


def test_when_realpath_raises_the_answer_is_exactly_false(tmp_path, monkeypatch):
    is_safe_path = _load_is_safe_path(tmp_path)

    def broken(_path):
        raise OSError("cannot resolve")

    monkeypatch.setattr(os.path, "realpath", broken)
    assert is_safe_path("sub/file.txt") is False
