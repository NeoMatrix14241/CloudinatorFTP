"""file_monitor: the storage_index.json cache, saved and loaded (5.40).

storage_index.json is what lets the server start without walking the whole storage again: the
counters and the per-folder dir_info records. A broken or foreign file must never be trusted, and
a save must never leave a half-written file behind. Both rules live in three methods of
FileSystemMonitor (_save_cache, _load_cache, _cleanup_stale_tmp), which are read out of
file_monitor.py with `ast` (the module itself starts threads and imports config, so it is never
imported) and run on a small fake monitor in a temporary cache folder, with a recording fake for
`file_index_manager`. No watchdog, no thread, no real project data.

What is NOT covered here: the walks that build the numbers (_full_walk, _reconcile_walk) and the
folder correction pass (_correct_folders); those need a real tree and are tested separately.
"""

import ast
import hashlib
import json
import os
import textwrap
import threading
import time
import types
from pathlib import Path
from typing import Dict

import pytest

try:  # the fuzz test at the end needs Hypothesis (requirements-dev.txt); the rest does not
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    HAVE_HYPOTHESIS = True
except ImportError:  # pragma: no cover - a machine without the dev requirements
    HAVE_HYPOTHESIS = False

ROOT = Path(__file__).resolve().parents[2]

_METHODS = ("_cleanup_stale_tmp", "_load_cache", "_save_cache")
_FUNCTIONS = ("_norm_root", "_nonneg_int")
_CONSTANTS = (
    "_TMP_PREFIX",
    "_TMP_MAX_AGE_SECS",
    "CACHE_SCHEMA_VERSION",
    "_ACCEPTED_CACHE_VERSIONS",
)


def _cache_source():
    source = (ROOT / "file_monitor.py").read_text(encoding="utf-8")
    functions, constants, methods = [], [], {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in _FUNCTIONS:
            functions.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign):
            if {t.id for t in node.targets if isinstance(t, ast.Name)} & set(
                _CONSTANTS
            ):
                constants.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.ClassDef) and node.name == "FileSystemMonitor":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in _METHODS:
                    methods[item.name] = textwrap.dedent(
                        ast.get_source_segment(source, item)
                    )
    assert set(methods) == set(
        _METHODS
    ), f"methods not found: {set(_METHODS) - set(methods)}"
    assert len(functions) == len(_FUNCTIONS) and len(constants) == len(_CONSTANTS)
    return "\n\n".join(constants + functions), methods


class _Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, *args))

        return record


class _FakeClock:
    def __init__(self):
        self.sleeps = []

    def __getattr__(self, name):
        return getattr(time, name)

    def sleep(self, seconds):
        self.sleeps.append(seconds)


class _ReplaceProxy:
    """The real os, except that os.replace can be made to fail like a locked file on Windows."""

    def __init__(self):
        self.fail_times = 0
        self.attempts = 0

    def __getattr__(self, name):
        return getattr(os, name)

    def replace(self, src, dst):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise PermissionError(13, "The process cannot access the file", dst)
        return os.replace(src, dst)


@pytest.fixture()
def lab(tmp_path):
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_file = cache_dir / "storage_index.json"
    consts_source, methods = _cache_source()
    file_index, clock, proxy = _Recorder(), _FakeClock(), _ReplaceProxy()
    namespace = {
        "os": proxy,
        "json": json,
        "time": clock,
        "hashlib": hashlib,
        "Dict": Dict,
        "CACHE_DIR": str(cache_dir),
        "CACHE_FILE": str(cache_file),
        "file_index_manager": file_index,
    }
    exec(consts_source, namespace)
    for source in methods.values():
        exec(source, namespace)

    def new_monitor():
        mon = types.SimpleNamespace(
            root_path=str(storage_root),
            lock=threading.RLock(),
            _save_lock=threading.RLock(),
            _dir_info={},
            _file_count=0,
            _dir_count=0,
            _total_size=0,
            _last_modified=0.0,
            _last_saved_digest=None,
            _last_save_ts=0.0,
            _load_repaired=0,
        )
        for name in _METHODS:
            setattr(mon, name, types.MethodType(namespace[name], mon))
        return mon

    return types.SimpleNamespace(
        new_monitor=new_monitor,
        cache_dir=cache_dir,
        cache_file=cache_file,
        storage_root=storage_root,
        file_index=file_index,
        clock=clock,
        proxy=proxy,
    )


def _filled(mon):
    mon._file_count, mon._dir_count, mon._total_size = 3, 1, 300
    mon._last_modified = 1234.5
    mon._dir_info = {
        "": {"file_count": 3, "dir_count": 1, "total_size": 300},
        "docs": {"file_count": 2, "dir_count": 0, "total_size": 200},
    }
    return mon


def _write(lab, data):
    lab.cache_file.write_text(
        data if isinstance(data, str) else json.dumps(data), encoding="utf-8"
    )


def _valid(lab, **changes):
    data = {
        "version": 2,
        "root": str(lab.storage_root),
        "file_count": 3,
        "dir_count": 1,
        "total_size": 300,
        "last_modified": 1234.5,
        "dir_info": {
            "": {"file_count": 3, "dir_count": 1, "total_size": 300},
            "docs": {"file_count": 2, "dir_count": 0, "total_size": 200},
        },
    }
    data.update(changes)
    return data


def _temp_files(lab):
    return sorted(p.name for p in lab.cache_dir.iterdir() if p.name.endswith(".tmp"))


# ---------------------------------------------------------------------------- save
def test_a_save_writes_the_versioned_index_and_leaves_no_temp_file(lab):
    mon = _filled(lab.new_monitor())
    mon._save_cache()
    data = json.loads(lab.cache_file.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert data["root"] == str(lab.storage_root)
    assert (data["file_count"], data["dir_count"], data["total_size"]) == (3, 1, 300)
    assert data["last_modified"] == 1234.5
    assert data["dir_info"]["docs"] == {
        "file_count": 2,
        "dir_count": 0,
        "total_size": 200,
    }
    assert isinstance(data["saved_at"], float)
    assert _temp_files(lab) == []
    assert [c[0] for c in lab.file_index.calls] == [
        "save"
    ], "file_index.json is saved with it"


def test_a_save_of_unchanged_content_does_not_write_again(lab):
    mon = _filled(lab.new_monitor())
    mon._save_cache()
    first = lab.cache_file.read_text(encoding="utf-8")
    mon._save_cache()
    assert (
        lab.cache_file.read_text(encoding="utf-8") == first
    ), "same digest: nothing rewritten"
    assert lab.proxy.attempts == 1, "one os.replace for two saves"


def test_a_save_after_a_change_writes_the_new_numbers(lab):
    mon = _filled(lab.new_monitor())
    mon._save_cache()
    mon._file_count = 4
    mon._dir_info[""]["file_count"] = 4
    mon._save_cache()
    data = json.loads(lab.cache_file.read_text(encoding="utf-8"))
    assert data["file_count"] == 4 and data["dir_info"][""]["file_count"] == 4


def test_a_deleted_index_file_is_written_again_even_if_nothing_changed(lab):
    mon = _filled(lab.new_monitor())
    mon._save_cache()
    lab.cache_file.unlink()
    mon._save_cache()
    assert lab.cache_file.exists()


def test_a_locked_index_file_is_retried_and_then_written(lab):
    lab.proxy.fail_times = (
        2  # antivirus / indexer holds storage_index.json for a moment
    )
    mon = _filled(lab.new_monitor())
    mon._save_cache()
    assert lab.proxy.attempts == 3
    assert lab.clock.sleeps == [0.05, 0.1]
    assert json.loads(lab.cache_file.read_text(encoding="utf-8"))["file_count"] == 3
    assert _temp_files(lab) == []


def test_a_save_that_cannot_replace_the_file_keeps_the_old_one_and_cleans_up(
    lab, capsys
):
    mon = _filled(lab.new_monitor())
    mon._save_cache()
    good = lab.cache_file.read_text(encoding="utf-8")
    mon._file_count = 99
    mon._dir_info[""]["file_count"] = 99
    lab.proxy.attempts = 0
    lab.proxy.fail_times = 99  # the file stays locked
    mon._save_cache()  # must not raise: a failed save is reported, not fatal
    assert lab.proxy.attempts == 7, "a bounded number of attempts"
    assert (
        lab.cache_file.read_text(encoding="utf-8") == good
    ), "the old index is untouched"
    assert _temp_files(lab) == [], "the temp file is removed"
    assert "Failed to save cache" in capsys.readouterr().out
    assert [c[0] for c in lab.file_index.calls][-1] == "save"


def test_a_save_that_fails_before_any_temp_file_exists_is_reported_not_raised(
    lab, capsys
):
    mon = _filled(lab.new_monitor())
    mon._dir_info["bad"] = {"file_count": {1, 2}}  # a set: json cannot write it
    mon._save_cache()  # must not raise
    assert "Failed to save cache" in capsys.readouterr().out
    assert not lab.cache_file.exists() and _temp_files(lab) == []


# ---------------------------------------------------------------------------- load: accepted
def test_what_was_saved_is_loaded_back_unchanged(lab):
    _filled(lab.new_monitor())._save_cache()
    fresh = lab.new_monitor()
    lab.file_index.calls.clear()
    assert fresh._load_cache() is True
    assert (fresh._file_count, fresh._dir_count, fresh._total_size) == (3, 1, 300)
    assert fresh._last_modified == 1234.5
    assert fresh._dir_info["docs"] == {
        "file_count": 2,
        "dir_count": 0,
        "total_size": 200,
    }
    assert fresh._load_repaired == 0
    assert ("load",) in lab.file_index.calls, "the companion file index is loaded too"


def test_a_missing_index_file_means_a_first_boot_walk(lab):
    mon = lab.new_monitor()
    assert mon._load_cache() is False
    assert mon._file_count == 0 and mon._dir_info == {}
    assert lab.file_index.calls == []


def test_a_legacy_version_1_file_without_a_root_is_accepted_but_flagged(lab):
    data = _valid(lab)
    del data["version"], data["root"]
    _write(lab, data)
    mon = lab.new_monitor()
    assert mon._load_cache() is True
    assert (
        mon._load_repaired == 1
    ), "it cannot prove which tree it describes: verify by walk"


def test_a_version_1_file_that_names_its_root_is_trusted(lab):
    data = _valid(lab, version=1)  # old schema, but it says which tree it describes
    _write(lab, data)
    mon = lab.new_monitor()
    assert mon._load_cache() is True
    assert mon._load_repaired == 0


def test_the_root_may_be_spelled_differently(lab):
    _write(lab, _valid(lab, root=str(lab.storage_root) + os.sep))
    assert lab.new_monitor()._load_cache() is True


# ---------------------------------------------------------------------------- load: rejected
@pytest.mark.parametrize(
    "content",
    [
        "[1, 2, 3]",
        "not json at all {",
        '{"version": 2}',
    ],
    ids=["not an object", "not json", "no counters and no dir_info"],
)
def test_a_file_that_is_not_an_index_is_discarded(lab, content):
    _write(lab, content)
    mon = lab.new_monitor()
    assert mon._load_cache() is False
    assert mon._dir_info == {} and mon._file_count == 0
    assert (
        lab.file_index.calls == []
    ), "the file index is loaded only after a valid index"


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 3},
        {"version": "two"},
        {"root": "/some/other/storage"},
        {"file_count": -1},
        {"dir_count": "many"},
        {"total_size": None, "file_count": True},
        {"dir_info": {}},
        {"dir_info": ["not", "a", "dict"]},
    ],
    ids=[
        "future schema",
        "schema not a number",
        "other root",
        "negative counter",
        "text counter",
        "bool counter",
        "empty dir_info",
        "dir_info not a dict",
    ],
)
def test_an_index_that_fails_validation_is_discarded_and_nothing_is_half_loaded(
    lab, changes
):
    _write(lab, _valid(lab, **changes))
    mon = lab.new_monitor()
    mon._file_count = 7  # whatever was there stays: no partial assignment
    assert mon._load_cache() is False
    assert mon._file_count == 7 and mon._dir_info == {}
    assert lab.file_index.calls == []


# ---------------------------------------------------------------------------- load: repaired
def test_bad_folder_records_are_repaired_and_flagged_for_a_verification_walk(lab):
    info = {
        "": {"file_count": 3, "dir_count": 1, "total_size": 300},
        "good": {"file_count": 1, "dir_count": 0, "total_size": 10},
        "negative": {"file_count": -5, "dir_count": 0, "total_size": 10},
        "not_a_record": "oops",
        "back\\slash": {"file_count": 1, "dir_count": 0, "total_size": 1},
        "/leading": {"file_count": 1, "dir_count": 0, "total_size": 1},
    }
    _write(lab, _valid(lab, dir_info=info))
    mon = lab.new_monitor()
    assert mon._load_cache() is True
    assert mon._dir_info["good"] == {"file_count": 1, "dir_count": 0, "total_size": 10}
    assert mon._dir_info["negative"] == {
        "file_count": 0,
        "dir_count": 0,
        "total_size": 0,
    }
    assert mon._dir_info["not_a_record"] == {
        "file_count": 0,
        "dir_count": 0,
        "total_size": 0,
    }
    assert "back\\slash" not in mon._dir_info and "/leading" not in mon._dir_info
    assert mon._load_repaired == 4


def test_a_missing_root_record_is_rebuilt_from_the_counters(lab):
    info = {"docs": {"file_count": 2, "dir_count": 0, "total_size": 200}}
    _write(lab, _valid(lab, dir_info=info))
    mon = lab.new_monitor()
    assert mon._load_cache() is True
    assert mon._dir_info[""] == {"file_count": 3, "dir_count": 1, "total_size": 300}
    assert mon._load_repaired == 1


def test_a_root_record_that_disagrees_with_the_global_counter_is_flagged(lab):
    info = {"": {"file_count": 9, "dir_count": 1, "total_size": 300}}
    _write(lab, _valid(lab, dir_info=info))
    mon = lab.new_monitor()
    assert mon._load_cache() is True
    assert mon._load_repaired == 1 and mon._file_count == 3


# ---------------------------------------------------------------------------- stale temp files
def test_only_old_temp_files_of_a_crashed_save_are_removed(lab):
    old = lab.cache_dir / "storage_index.crashed.tmp"
    fresh = lab.cache_dir / "storage_index.running.tmp"
    other = lab.cache_dir / "something_else.tmp"
    keep = lab.cache_dir / "storage_index.json"
    for path in (old, fresh, other, keep):
        path.write_text("x", encoding="utf-8")
    long_ago = time.time() - 3600
    os.utime(old, (long_ago, long_ago))
    os.utime(other, (long_ago, long_ago))
    lab.new_monitor()._cleanup_stale_tmp()
    assert not old.exists()
    assert fresh.exists(), "another process may be saving right now"
    assert other.exists(), "not ours: wrong prefix"
    assert keep.exists()


# ---------------------------------------------------------------------------- fuzzing the loader
if HAVE_HYPOTHESIS:
    _NIGHTLY = os.environ.get("CLOUDINATOR_NIGHTLY") == "1"
    _JSON = st.recursive(
        st.none()
        | st.booleans()
        | st.integers()
        | st.floats(allow_nan=False, allow_infinity=False)
        | st.text(max_size=8),
        lambda inner: st.lists(inner, max_size=4)
        | st.dictionaries(st.text(max_size=8), inner, max_size=4),
        max_leaves=12,
    )
    _RECORD = st.fixed_dictionaries(
        {},
        optional={
            "file_count": _JSON,
            "dir_count": _JSON,
            "total_size": _JSON,
        },
    )
    _NEAR_VALID = st.fixed_dictionaries(
        {},
        optional={
            "version": st.sampled_from([1, 2, 3, "2", None]),
            "root": st.sampled_from(["ROOT", "/elsewhere", None, 5]),
            "file_count": _JSON | st.integers(0, 10**6),
            "dir_count": _JSON | st.integers(0, 10**6),
            "total_size": _JSON | st.integers(0, 10**12),
            "last_modified": _JSON | st.floats(0, 2e9),
            "dir_info": st.dictionaries(
                st.sampled_from(["", "a", "a/b", "a\\b", "/a", "a/"]),
                _RECORD | _JSON,
                max_size=5,
            )
            | _JSON,
        },
    )

    @settings(
        max_examples=1000 if _NIGHTLY else 150,
        derandomize=not _NIGHTLY,
        deadline=None,
        database=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(st.one_of(_JSON, _NEAR_VALID))
    def test_whatever_is_in_the_file_the_loader_never_raises_and_a_loaded_index_is_sane(
        lab, content
    ):
        if isinstance(content, dict) and content.get("root") == "ROOT":
            content = {**content, "root": str(lab.storage_root)}
        _write(lab, content)
        mon = lab.new_monitor()
        assert mon._load_cache() in (True, False)  # never an exception
        if not mon._dir_info:
            return  # rejected: nothing was loaded
        for number in (mon._file_count, mon._dir_count, mon._total_size):
            assert type(number) is int and number >= 0
        assert "" in mon._dir_info, "the root record is what every handler bubbles into"
        for key, record in mon._dir_info.items():
            assert isinstance(key, str) and "\\" not in key and key == key.strip("/")
            assert set(record) == {"file_count", "dir_count", "total_size"}
            assert all(type(v) is int and v >= 0 for v in record.values())
