"""
Tests of the test harness itself: the scratch copy must isolate everything.

These are the safety-net tests. If one of them fails, do not run the application tests until
it is fixed, because the application tests start a real server from the scratch copy.
"""

import json
import shutil

import pytest


@pytest.fixture
def fake_repo(tmp_path, scratch_tools):
    """A miniature project that looks like the real one, including 'production' data."""
    repo = tmp_path / "repo"
    (repo / "helpers").mkdir(parents=True)
    (repo / "routes").mkdir()
    (repo / "templates").mkdir()
    (repo / "static" / "css").mkdir(parents=True)
    (repo / "static" / "js" / "cmaps").mkdir(parents=True)
    (repo / "db").mkdir()
    (repo / "logs").mkdir()
    (repo / "docs").mkdir()
    shutil.copy2(scratch_tools.repo_root / "paths.py", repo / "paths.py")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "helpers" / "net.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "routes" / "r.py").write_text("z = 3\n", encoding="utf-8")
    (repo / "templates" / "t.html").write_text("<html></html>", encoding="utf-8")
    (repo / "static" / "css" / "a.css").write_text("a{}", encoding="utf-8")
    (repo / "static" / "js" / "cmaps" / "big.bin").write_bytes(b"0" * 10)
    (repo / "db" / "users.db").write_bytes(b"secret")
    (repo / "logs" / "prod.log").write_text("log", encoding="utf-8")
    (repo / "docs" / "CLAUDE.md").write_text("doc", encoding="utf-8")
    (repo / "storage_config.json").write_text(
        json.dumps(
            {"storage_path": "C:\\Server\\storage", "db_path": "C:\\Server\\config\\db"}
        ),
        encoding="utf-8",
    )
    (repo / "server_config.json").write_text(
        json.dumps({"PORT": 5000, "SFTP_ENABLED": True, "ENABLE_SEARCH_INDEX": True}),
        encoding="utf-8",
    )
    return repo


def test_source_files_are_copied(tmp_path, scratch_tools, fake_repo):
    dest = scratch_tools.build(tmp_path / "scratch", src_root=fake_repo, port=4321)
    for rel in (
        "paths.py",
        "app.py",
        "helpers/net.py",
        "routes/r.py",
        "templates/t.html",
        "static/css/a.css",
    ):
        assert (dest / rel).is_file(), rel


def test_real_data_and_vendored_folders_are_not_copied(
    tmp_path, scratch_tools, fake_repo
):
    dest = scratch_tools.build(tmp_path / "scratch", src_root=fake_repo)
    assert not (dest / "db").exists()
    assert not (dest / "logs").exists()
    assert not (dest / "docs").exists()
    assert not (dest / "static" / "js" / "cmaps").exists()
    assert not list(dest.rglob("users.db"))


def test_config_files_are_rewritten_not_copied(tmp_path, scratch_tools, fake_repo):
    dest = scratch_tools.build(tmp_path / "scratch", src_root=fake_repo, port=4321)
    server = json.loads((dest / "server_config.json").read_text(encoding="utf-8"))
    storage = json.loads((dest / "storage_config.json").read_text(encoding="utf-8"))
    assert server["PORT"] == 4321 and server["HOST"] == "127.0.0.1"
    for key in (
        "ENABLE_SEARCH_INDEX",
        "ENABLE_FFMPEG",
        "ENABLE_LIBVIPS",
        "WEBDAV_ENABLED",
        "WEBDAV_HTTPS_ENABLED",
        "SFTP_ENABLED",
        "FTP_ENABLED",
        "SMB_ENABLED",
        "VERSION_ENGINE_ENABLED",
    ):
        assert server[key] is False, key
    text = (dest / "storage_config.json").read_text(encoding="utf-8")
    assert "C:\\\\Server" not in text and "config\\\\db" not in text
    for key, value in storage.items():
        assert scratch_tools.is_inside(value, dest), key


def test_scratch_paths_resolve_inside_the_scratch_folder(
    tmp_path, scratch_tools, fake_repo
):
    dest = scratch_tools.build(tmp_path / "scratch", src_root=fake_repo)
    assert scratch_tools.paths_outside(dest, repo_root=fake_repo) == []


def test_guard_detects_a_path_outside_the_scratch_folder(
    tmp_path, scratch_tools, fake_repo
):
    dest = scratch_tools.build(tmp_path / "scratch", src_root=fake_repo)
    outside = tmp_path / "production" / "db"
    cfg_file = dest / "storage_config.json"
    cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    cfg["db_path"] = str(outside)
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    problems = scratch_tools.paths_outside(dest, repo_root=fake_repo)
    assert any("db_dir" in p for p in problems), problems


def test_guard_detects_a_storage_path_outside(tmp_path, scratch_tools, fake_repo):
    dest = scratch_tools.build(tmp_path / "scratch", src_root=fake_repo)
    cfg_file = dest / "storage_config.json"
    cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    cfg["storage_path"] = str(tmp_path / "real_storage")
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    problems = scratch_tools.paths_outside(dest, repo_root=fake_repo)
    assert any("storage_path" in p for p in problems), problems


def test_guard_detects_a_scratch_folder_inside_the_repo(scratch_tools, fake_repo):
    dest = scratch_tools.build(fake_repo / "inner", src_root=fake_repo)
    problems = scratch_tools.paths_outside(dest, repo_root=fake_repo)
    assert any("overlaps" in p for p in problems), problems


def test_free_port_is_usable_and_changes(scratch_tools):
    ports = {scratch_tools.free_port() for _ in range(3)}
    assert all(1024 <= p <= 65535 for p in ports)
