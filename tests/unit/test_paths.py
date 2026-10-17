"""
Unit tests for paths.py (the central db/cache/versions path resolver).

paths.py has no project imports and no import-time side effects, so it is imported from the
real tree; every test points its module-level _HERE / _CONFIG_FILE at a temporary folder, so
no real storage_config.json or db/ folder is ever read or written.
"""

import json
import os

import pytest

import paths


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_HERE", str(tmp_path))
    monkeypatch.setattr(paths, "_CONFIG_FILE", str(tmp_path / "storage_config.json"))
    return tmp_path


def _write_cfg(root, data):
    (root / "storage_config.json").write_text(json.dumps(data), encoding="utf-8")


def _read_cfg(root):
    return json.loads((root / "storage_config.json").read_text(encoding="utf-8"))


def test_defaults_without_config_file(root):
    assert paths.get_db_dir(create=False) == str(root / "db")
    assert paths.get_cache_dir(create=False) == str(root / "cache")
    assert paths.get_versions_dir(create=False) == str(root / "versions")
    assert paths.get_hls_cache_dir(create=False) == str(root / "cache" / "hls")
    assert paths.get_img_cache_dir(create=False) == str(root / "cache" / "img")


def test_create_false_creates_nothing(root):
    paths.get_db_dir(create=False)
    paths.get_cache_dir(create=False)
    paths.get_all_paths()
    assert list(root.iterdir()) == []


def test_create_true_creates_the_directory(root):
    assert os.path.isdir(paths.get_db_dir(create=True))
    assert (root / "db").is_dir()


def test_configured_paths_are_honoured(root):
    _write_cfg(
        root, {"db_path": str(root / "elsewhere" / "d"), "cache_path": str(root / "c")}
    )
    assert paths.get_db_dir(create=False) == str(root / "elsewhere" / "d")
    assert paths.get_cache_dir(create=False) == str(root / "c")
    # the HLS / image defaults follow the configured cache dir
    assert paths.get_hls_cache_dir(create=False) == str(root / "c" / "hls")
    assert paths.get_img_cache_dir(create=False) == str(root / "c" / "img")


def test_empty_string_falls_back_to_default(root):
    _write_cfg(root, {"db_path": "", "versions_path": ""})
    assert paths.get_db_dir(create=False) == str(root / "db")
    assert paths.get_versions_dir(create=False) == str(root / "versions")


@pytest.mark.parametrize("content", ["{not json", "[1, 2]x", ""])
def test_corrupt_config_falls_back_to_defaults(root, content):
    (root / "storage_config.json").write_text(content, encoding="utf-8")
    assert paths.get_db_dir(create=False) == str(root / "db")


@pytest.mark.parametrize(
    "setter,getter,leaf",
    [
        (paths.set_db_dir, paths.get_db_dir, "db"),
        (paths.set_cache_dir, paths.get_cache_dir, "cache"),
        (paths.set_versions_dir, paths.get_versions_dir, "versions"),
    ],
)
def test_setters_append_the_leaf_folder(root, setter, getter, leaf):
    parent = root / "parent"
    assert setter(str(parent)) is True
    assert getter(create=False) == str(parent / leaf)
    assert (parent / leaf).is_dir()


@pytest.mark.parametrize("name", ["db", "DB"])
def test_set_db_dir_keeps_an_existing_db_leaf(root, name):
    target = root / "x" / name
    assert paths.set_db_dir(str(target)) is True
    assert paths.get_db_dir(create=False) == str(target)


def test_setters_merge_and_never_wipe_sibling_keys(root):
    _write_cfg(root, {"storage_path": "S", "platform": "windows"})
    assert paths.set_db_dir(str(root / "a")) is True
    assert paths.set_cache_dir(str(root / "b")) is True
    cfg = _read_cfg(root)
    assert cfg["storage_path"] == "S" and cfg["platform"] == "windows"
    assert cfg["db_path"].endswith("db") and cfg["cache_path"].endswith("cache")


def test_set_hls_and_img_dirs(root):
    assert paths.set_hls_cache_dir(str(root / "h")) is True
    assert paths.set_img_cache_dir(str(root / "i")) is True
    assert paths.get_hls_cache_dir(create=False) == str(root / "h" / "hls")
    assert paths.get_img_cache_dir(create=False) == str(root / "i" / "img")


def test_setter_returns_false_when_path_is_unusable(root):
    blocker = root / "a_file"
    blocker.write_text("x", encoding="utf-8")
    assert paths.set_db_dir(str(blocker / "sub")) is False
    assert not (root / "storage_config.json").exists()  # nothing persisted


@pytest.mark.parametrize(
    "setter,resetter,getter,leaf",
    [
        (paths.set_db_dir, paths.reset_db_dir, paths.get_db_dir, "db"),
        (paths.set_cache_dir, paths.reset_cache_dir, paths.get_cache_dir, "cache"),
        (
            paths.set_versions_dir,
            paths.reset_versions_dir,
            paths.get_versions_dir,
            "versions",
        ),
    ],
)
def test_reset_returns_to_default(root, setter, resetter, getter, leaf):
    setter(str(root / "moved"))
    assert getter(create=False) != str(root / leaf)
    resetter()
    assert getter(create=False) == str(root / leaf)


def test_ensure_dirs_creates_all_five(root):
    paths.ensure_dirs()
    for rel in ("db", "cache", "cache/hls", "cache/img", "versions"):
        assert (root / rel).is_dir(), rel


def test_get_all_paths_reports_configured_and_default_values(root):
    _write_cfg(root, {"db_path": str(root / "d")})
    info = paths.get_all_paths()
    assert info["db_dir"] == str(root / "d")
    assert info["default_db_dir"] == str(root / "db")
    assert info["versions_dir"] == str(root / "versions")
