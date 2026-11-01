"""
Tests of two 5.41 changes in version_engine.py, loaded with the `ast` technique (the real code,
no import of the application):

  * `.chunks` (the folder of half-uploaded pieces under the storage root) is never tracked, whatever
    VERSION_EXCLUDE_DIRECTORIES says, and the real directory walk skips it;
  * a watcher / scanner pass that takes long is logged, at most once a minute.
"""

import ast
import os
import types
from pathlib import Path

import pytest

ENGINE_PATH = Path(__file__).resolve().parent.parent.parent / "version_engine.py"

CONSTANTS = ("_ALWAYS_EXCLUDED_DIR_NAMES", "_SLOW_PASS_SECONDS", "_SLOW_PASS_LOG_EVERY")
METHODS = ("_is_excluded_dir", "_is_excluded_file", "_walk_eligible", "_note_slow_pass")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


def _load(config, clock=None):
    """An `Engine` stand-in that carries the real code of the methods under test."""
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets
        ):
            body.append(node)
        if isinstance(node, ast.ClassDef) and node.name == "Engine":
            body.append(
                ast.ClassDef(
                    name="Probe",
                    bases=[],
                    keywords=[],
                    body=[
                        item
                        for item in node.body
                        if isinstance(item, ast.FunctionDef) and item.name in METHODS
                    ],
                    decorator_list=[],
                    type_params=[],
                )
            )
    found = {n.name for n in body if isinstance(n, ast.ClassDef)}
    assert found == {"Probe"}, "class Engine not found in version_engine.py"
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "os": os,
        "config": config,
        "time": clock or FakeClock(),
        "fnmatch": __import__("fnmatch"),
    }
    exec(compile(module, str(ENGINE_PATH), "exec"), namespace)
    probe = namespace["Probe"]()
    probe.log = types.SimpleNamespace(warning=lambda text: probe.warnings.append(text))
    probe.warnings = []
    return probe, namespace


def _config(**overrides):
    values = {
        "VERSION_EXCLUDE_DIRECTORIES": [],
        "VERSION_EXCLUDE_PATTERNS": ["*.tmp", "*.part", "~$*"],
        "VERSION_FOLLOW_SYMLINKS": False,
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


# ---------------------------------------------------------------------------- .chunks
def test_the_upload_folder_is_excluded_even_with_an_empty_exclude_list():
    probe, _ = _load(_config())
    assert probe._is_excluded_dir(os.path.join("root", ".chunks")) is True


@pytest.mark.parametrize("name", ["photos", ".chunks_backup", "chunks", ".hidden"])
def test_other_folder_names_are_not_excluded_by_the_built_in_rule(name):
    probe, _ = _load(_config())
    assert probe._is_excluded_dir(os.path.join("root", name)) is False


def test_the_configured_exclusions_still_work():
    probe, _ = _load(_config(VERSION_EXCLUDE_DIRECTORIES=["node_modules"]))
    assert probe._is_excluded_dir(os.path.join("root", "node_modules")) is True
    assert probe._is_excluded_dir(os.path.join("root", "src")) is False


def test_the_walk_yields_user_files_and_skips_the_upload_folder(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "skip.part").write_text("temp")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b")
    (tmp_path / ".chunks" / "key_1").mkdir(parents=True)
    (tmp_path / ".chunks" / "key_1" / "0").write_bytes(b"x" * 10)
    (tmp_path / "sub" / ".chunks").mkdir()  # the name is skipped at any depth
    (tmp_path / "sub" / ".chunks" / "9").write_text("y")
    probe, _ = _load(_config())
    names = sorted(
        os.path.relpath(path, tmp_path).replace(os.sep, "/")
        for path in probe._walk_eligible(str(tmp_path))
    )
    assert names == ["a.txt", "sub/b.txt"]


def test_a_tracked_folder_that_is_itself_called_chunks_is_still_walked(tmp_path):
    """The rule applies to sub-folders met during a walk, not to a root the admin chose."""
    root = tmp_path / ".chunks"
    root.mkdir()
    (root / "kept.txt").write_text("k")
    probe, _ = _load(_config())
    assert [os.path.basename(p) for p in probe._walk_eligible(str(root))] == [
        "kept.txt"
    ]


# ---------------------------------------------------------------------------- slow passes
def test_a_fast_pass_logs_nothing():
    probe, _ = _load(_config())
    probe._note_slow_pass("Watcher", 0.4)
    assert probe.warnings == []


def test_a_slow_pass_is_logged_with_a_hint():
    probe, _ = _load(_config())
    probe._note_slow_pass("Watcher", 7.25)
    assert len(probe.warnings) == 1
    text = probe.warnings[0]
    assert "Watcher pass took 7.2s" in text or "Watcher pass took 7.3s" in text
    assert "VERSION_WATCH_ENABLED" in text


def test_slow_passes_are_logged_at_most_once_a_minute():
    clock = FakeClock()
    probe, _ = _load(_config(), clock)
    probe._note_slow_pass("Watcher", 5.0)
    clock.now += 59
    probe._note_slow_pass("Scanner", 5.0)
    assert len(probe.warnings) == 1
    clock.now += 2
    probe._note_slow_pass("Scanner", 5.0)
    assert len(probe.warnings) == 2 and "Scanner" in probe.warnings[1]


def test_the_first_slow_pass_is_logged_even_just_after_the_machine_started():
    clock = FakeClock()
    clock.now = 3.0  # time.monotonic() starts near zero after a boot
    probe, _ = _load(_config(), clock)
    probe._note_slow_pass("Watcher", 9.0)
    assert len(probe.warnings) == 1
