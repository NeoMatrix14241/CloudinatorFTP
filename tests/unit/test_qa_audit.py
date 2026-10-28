"""
tests/qa.py `audit` mode (CLAUDE.md 5.32): pip-audit stays OUT of quick / ci / static (advisories
change without any code change, and an offline machine cannot run it), is skipped when pip-audit
is not installed, reads the accepted findings from tests/audit_ignore.txt and can audit another
environment's site-packages with --path. qa.py is loaded by path; nothing is executed.
"""

import importlib.util
from pathlib import Path

import pytest

QA = Path(__file__).resolve().parents[1] / "qa.py"


@pytest.fixture()
def qa():
    spec = importlib.util.spec_from_file_location("qa_under_test", QA)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pretend_installed(qa, monkeypatch, installed):
    real = qa.importlib.util.find_spec
    monkeypatch.setattr(
        qa.importlib.util,
        "find_spec",
        lambda name, *a, **k: (
            (object() if installed else None)
            if name == "pip_audit"
            else real(name, *a, **k)
        ),
    )


def test_ignore_file_takes_the_first_word_of_each_real_line(qa, tmp_path):
    f = tmp_path / "ignore.txt"
    f.write_text(
        "# header\n\nPYSEC-2026-1  # why, review 2026-12\n  GHSA-aaaa-bbbb-cccc\nCVE-2026-9 # x\n",
        encoding="utf-8",
    )
    assert qa._audit_ignores(f) == ["PYSEC-2026-1", "GHSA-aaaa-bbbb-cccc", "CVE-2026-9"]


def test_a_missing_ignore_file_means_no_ignores(qa, tmp_path):
    assert qa._audit_ignores(tmp_path / "nope.txt") == []


def test_audit_is_skipped_when_pip_audit_is_not_installed(qa, monkeypatch):
    _pretend_installed(qa, monkeypatch, False)
    (step,) = qa.build_plan("audit")
    assert step.name == "audit" and step.skip and "pip install pip-audit" in step.skip


def test_audit_runs_pip_audit_on_the_local_environment(qa, monkeypatch):
    _pretend_installed(qa, monkeypatch, True)
    (step,) = qa.build_plan("audit")
    (cmd,) = step.cmds
    assert cmd[1:3] == ["-m", "pip_audit"] and "--local" in cmd and "--path" not in cmd


def test_audit_path_audits_another_environment(qa, monkeypatch):
    _pretend_installed(qa, monkeypatch, True)
    (step,) = qa.build_plan("audit", path="/x/site-packages")
    (cmd,) = step.cmds
    assert cmd[cmd.index("--path") + 1] == "/x/site-packages" and "--local" not in cmd


def test_audit_passes_every_accepted_advisory_as_ignore_vuln(qa, monkeypatch, tmp_path):
    _pretend_installed(qa, monkeypatch, True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "audit_ignore.txt").write_text(
        "PYSEC-1  # a\nGHSA-2\n", encoding="utf-8"
    )
    monkeypatch.setattr(qa, "ROOT", tmp_path)
    (cmd,) = qa.build_plan("audit")[0].cmds
    pairs = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--ignore-vuln"]
    assert pairs == ["PYSEC-1", "GHSA-2"]


@pytest.mark.parametrize("mode", ["static", "tests", "quick", "ci"])
def test_the_everyday_modes_never_run_the_audit(qa, mode):
    assert "audit" not in [s.name for s in qa.build_plan(mode)]


def test_audit_is_a_registered_mode(qa):
    assert "audit" in QA.read_text(encoding="utf-8").split("choices=[", 1)[1][:80]


def test_venv_python_location_matches_the_spelling_of_virtual_env(qa):
    # Git Bash: VIRTUAL_ENV uses forward slashes, sys.executable backslashes (Windows)
    venv = "C:/Users/kyle/My Project/CloudinatorFTP/.venv"
    exe = r"C:\Users\kyle\My Project\CloudinatorFTP\.venv\Scripts\python.exe"
    location = qa._venv_python_location(venv, exe)
    assert location.startswith(venv)  # what pip-audit checks, as plain text
    assert location.endswith(r"\Scripts\python.exe")


def test_venv_python_location_keeps_posix_paths_and_a_trailing_slash(qa):
    assert qa._venv_python_location("/home/u/.venv/", "/home/u/.venv/bin/python") == (
        "/home/u/.venv/bin/python"
    )


def test_venv_python_location_is_none_outside_the_venv_or_without_one(qa):
    assert qa._venv_python_location(None, "/usr/bin/python") is None
    assert qa._venv_python_location("/home/u/.venv", "/usr/bin/python") is None
    assert (
        qa._venv_python_location("/home/u/.venv", "/home/u/.venv2/bin/python") is None
    )
