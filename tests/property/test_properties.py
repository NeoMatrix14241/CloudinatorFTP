"""Property-based tests (Hypothesis) for the pure functions that guard paths and upload ids (5.40).

Example tests check the cases somebody thought of; these generate hundreds of inputs and check a
rule that must hold for ALL of them:

- storage.is_safe_chunk_id: an accepted upload id is exactly one folder name under .chunks/.
- storage.is_safe_path: a path is accepted exactly when it stays inside the storage root, and a
  sibling folder whose name merely STARTS with the root's name is never accepted.
- routes/uploads.py chunk keys: one session can never produce another session's key, the client
  id is recoverable from the key, and a key is itself a safe folder name.
- file_monitor path helpers: _rel / _parents / _nonneg_int.

The functions are read out of the source files with `ast` and run in a private namespace (the
modules themselves import config and start threads, so they are never imported). The run is
DETERMINISTIC by default (`derandomize=True`, no example database), so it can never flake in the
required check; set CLOUDINATOR_NIGHTLY=1 for fresh random inputs and ten times as many examples
(the nightly workflow does).
"""

import ast
import hashlib
import ntpath
import os
import posixpath
import types
from pathlib import Path

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

pytestmark = pytest.mark.property

ROOT = Path(__file__).resolve().parents[2]
NIGHTLY = os.environ.get("CLOUDINATOR_NIGHTLY") == "1"
CHECK = settings(
    max_examples=1500 if NIGHTLY else 150,
    derandomize=not NIGHTLY,
    deadline=None,
    database=None,
)


def _segments(path, wanted_functions=(), wanted_constants=()):
    source = (ROOT / path).read_text(encoding="utf-8")
    parts, found = [], set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            parts.append(ast.get_source_segment(source, node))
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & set(wanted_constants):
                parts.append(ast.get_source_segment(source, node))
                found |= names & set(wanted_constants)
    missing = (set(wanted_functions) | set(wanted_constants)) - found
    assert not missing, f"not found in {path}: {sorted(missing)}"
    return "\n\n".join(parts)


@pytest.fixture(scope="module")
def storage_ns(tmp_path_factory):
    root = Path(os.path.realpath(tmp_path_factory.mktemp("prop"))) / "storage"
    root.mkdir()
    namespace = {"os": os, "ROOT_DIR": str(root)}
    exec(_segments("storage.py", ("is_safe_path", "is_safe_chunk_id")), namespace)
    return types.SimpleNamespace(
        root=str(root),
        is_safe_path=namespace["is_safe_path"],
        is_safe_chunk_id=namespace["is_safe_chunk_id"],
    )


@pytest.fixture(scope="module")
def upload_ns(storage_ns):
    namespace = {
        "hashlib": hashlib,
        "storage": types.SimpleNamespace(is_safe_chunk_id=storage_ns.is_safe_chunk_id),
    }
    exec(
        _segments(
            "routes/uploads.py",
            ("_valid_client_upload_id", "_key_prefix", "_chunk_key", "_client_file_id"),
            ("MAX_CLIENT_UPLOAD_ID_LEN",),
        ),
        namespace,
    )
    return types.SimpleNamespace(**namespace)


@pytest.fixture(scope="module")
def monitor_ns():
    namespace = {"os": os}
    exec(_segments("file_monitor.py", ("_rel", "_parents", "_nonneg_int")), namespace)
    return types.SimpleNamespace(**namespace)


# --------------------------------------------------------------------------- is_safe_chunk_id
@CHECK
@given(st.text())
def test_an_accepted_chunk_id_is_exactly_one_folder_name(storage_ns, candidate):
    if not storage_ns.is_safe_chunk_id(candidate):
        return
    assert 0 < len(candidate) <= 200
    assert candidate not in (".", "..")
    for module in (posixpath, ntpath):  # the same rule on Linux and on Windows
        joined = module.join("base", ".chunks", candidate)
        assert module.dirname(joined) == module.join("base", ".chunks")
        assert module.basename(joined) == candidate
        assert module.normpath(joined) == module.join("base", ".chunks", candidate)


@CHECK
@given(st.text(), st.sampled_from(["/", "\\", ":", "\x00"]), st.text())
def test_an_id_with_a_separator_a_drive_colon_or_nul_is_never_accepted(
    storage_ns, before, bad, after
):
    assert storage_ns.is_safe_chunk_id(before + bad + after) is False


@CHECK
@given(
    st.one_of(st.none(), st.integers(), st.binary(), st.lists(st.text()), st.floats())
)
def test_an_id_that_is_not_text_is_never_accepted(storage_ns, candidate):
    assert storage_ns.is_safe_chunk_id(candidate) is False


@CHECK
@given(st.text(alphabet="abcXYZ019_-. ", min_size=1, max_size=200))
def test_a_plain_name_is_accepted_unless_it_is_a_dot_entry(storage_ns, name):
    assert storage_ns.is_safe_chunk_id(name) is (name not in (".", ".."))


def test_an_id_is_accepted_up_to_200_characters_and_refused_beyond(storage_ns):
    # The boundary: random text almost never has exactly this length, so it is pinned here
    # (found by the mutation trial: `> 200` turned into `>= 200` was not noticed).
    assert storage_ns.is_safe_chunk_id("a" * 200) is True
    assert storage_ns.is_safe_chunk_id("a" * 201) is False
    assert storage_ns.is_safe_chunk_id("a" * 199) is True


# --------------------------------------------------------------------------- is_safe_path
SEGMENT = st.sampled_from(
    ["", ".", "..", "a", "b", "sub", "storage", "storage_backup", "x y"]
)


def _model_inside(root, path):
    """Where the path lands, worked out lexically (the root has no symlinks in this test).
    A path that starts with a separator is absolute: os.path.join then drops the root, exactly
    as the application's own join does, so '/' (the machine's root) is correctly outside.
    """
    landed = os.path.normcase(os.path.normpath(os.path.join(root, path)))
    base = os.path.normcase(root)
    return landed == base or landed.startswith(base + os.sep)


@CHECK
@given(st.lists(SEGMENT, max_size=7))
def test_a_path_is_accepted_exactly_when_it_stays_inside_the_root(storage_ns, segments):
    path = "/".join(segments)
    assert storage_ns.is_safe_path(path) is _model_inside(storage_ns.root, path), path


@CHECK
@given(
    st.integers(min_value=1, max_value=4),
    st.lists(st.sampled_from(["a", "b", "sub"]), max_size=3),
)
def test_going_above_the_root_is_never_accepted(storage_ns, levels, rest):
    path = "/".join([".."] * levels + ["elsewhere"] + rest)
    assert storage_ns.is_safe_path(path) is False


@CHECK
@given(
    st.sampled_from(["storage_backup", "storage2", "storage.old", "storageX"]),
    st.lists(st.sampled_from(["a", "b"]), max_size=2),
)
def test_a_sibling_folder_that_starts_with_the_roots_name_is_refused(
    storage_ns, sibling, rest
):
    path = "/".join(["..", sibling] + rest)
    assert storage_ns.is_safe_path(path) is False


@CHECK
@given(st.lists(st.sampled_from(["a", "b", "sub", "x y"]), max_size=6))
def test_a_path_made_only_of_folder_names_is_always_accepted(storage_ns, names):
    assert storage_ns.is_safe_path("/".join(names)) is True


@CHECK
@given(st.text(max_size=40))
def test_is_safe_path_never_raises_for_any_text(storage_ns, text):
    assert storage_ns.is_safe_path(text) in (True, False)


@pytest.mark.parametrize("path", ["a\x00b", "\x00", "sub/\x00/x", "x" * 3 + "\x00"])
def test_a_path_with_a_nul_byte_is_refused(storage_ns, path):
    # Linux: os.path raises ValueError for a NUL byte. Windows (Python 3.14): it does not, and the
    # path used to count as safe. storage.is_safe_path now refuses a NUL itself, so the answer is
    # the same everywhere (the mutation trial first asked for this test; the first Windows run showed
    # why it matters).
    assert storage_ns.is_safe_path(path) is False


@pytest.mark.skipif(os.name != "nt", reason="drive letters exist on Windows only")
def test_a_path_on_another_drive_is_refused(storage_ns):
    # os.path.commonpath raises ValueError for two different drives: that must mean "not safe".
    root_drive = os.path.splitdrive(storage_ns.root)[0].upper()
    other = "D:" if root_drive != "D:" else "E:"
    assert storage_ns.is_safe_path(other + "\\somewhere\\else.txt") is False


# --------------------------------------------------------------------------- upload chunk keys
CLIENT_ID = st.text(alphabet="abcdefXYZ0123456789_-", min_size=1, max_size=128)
SESSION = st.text(min_size=1, max_size=60)


@CHECK
@given(SESSION, CLIENT_ID)
def test_a_chunk_key_is_a_safe_folder_name_that_gives_the_client_id_back(
    storage_ns, upload_ns, session_id, file_id
):
    key = upload_ns._chunk_key(session_id, file_id)
    assert key is not None
    assert storage_ns.is_safe_chunk_id(
        key
    ), "the key becomes a folder name under .chunks/"
    assert len(key) <= 200, "the 17 added characters stay under the folder-name limit"
    assert upload_ns._client_file_id(session_id, key) == file_id


@CHECK
@given(SESSION, SESSION, CLIENT_ID)
def test_two_sessions_never_get_the_same_key_for_the_same_upload_id(
    upload_ns, session_a, session_b, file_id
):
    key_a = upload_ns._chunk_key(session_a, file_id)
    key_b = upload_ns._chunk_key(session_b, file_id)
    assert (key_a == key_b) is (session_a == session_b)


@CHECK
@given(SESSION, st.text(max_size=300))
def test_an_unusable_client_id_gets_no_key(upload_ns, session_id, file_id):
    key = upload_ns._chunk_key(session_id, file_id)
    if upload_ns._valid_client_upload_id(file_id):
        assert key is not None and key.endswith(file_id)
    else:
        assert key is None


@CHECK
@given(CLIENT_ID)
def test_without_a_session_there_is_no_key(upload_ns, file_id):
    assert upload_ns._chunk_key("", file_id) is None
    assert upload_ns._chunk_key(None, file_id) is None


# --------------------------------------------------------------------------- file_monitor helpers
# A folder name never ends with a space or a dot here: Windows strips those from every path
# component (GetFullPathName), so "storage\\ " IS "storage" there and no such folder can exist
# (found by the first Windows run). Spaces inside a name are kept.
NAME = st.text(alphabet="abc XYZ019_-", min_size=1, max_size=8).filter(
    lambda name: name == name.strip()
)


@CHECK
@given(st.lists(NAME, min_size=1, max_size=6))
def test_rel_turns_an_absolute_path_back_into_the_parts_it_was_built_from(
    monitor_ns, parts
):
    root = os.path.join(os.sep, "data", "storage")
    assert monitor_ns._rel(os.path.join(root, *parts), root) == "/".join(parts)
    assert monitor_ns._rel(root, root) == ""


@CHECK
@given(st.lists(NAME, min_size=1, max_size=6))
def test_parents_runs_from_the_closest_folder_up_to_the_root(monitor_ns, parts):
    rel = "/".join(parts)
    chain = list(monitor_ns._parents(rel))
    assert chain[-1] == "", "the root always gets updated"
    assert chain[:-1] == ["/".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]
    assert all(len(a) > len(b) for a, b in zip(chain, chain[1:]))
    assert list(monitor_ns._parents("")) == [], "the root has no parents"


@CHECK
@given(
    st.one_of(
        st.integers(), st.floats(), st.text(), st.none(), st.booleans(), st.binary()
    )
)
def test_nonneg_int_returns_a_non_negative_int_or_none_and_never_raises(
    monitor_ns, value
):
    result = monitor_ns._nonneg_int(value)
    assert result is None or (type(result) is int and result >= 0)
    if isinstance(value, bool):
        assert result is None


@CHECK
@given(st.integers(min_value=0, max_value=10**15))
def test_nonneg_int_keeps_every_valid_count(monitor_ns, number):
    assert monitor_ns._nonneg_int(number) == number
    assert monitor_ns._nonneg_int(str(number)) == number
