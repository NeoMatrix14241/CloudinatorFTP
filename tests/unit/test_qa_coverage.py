"""
tests/qa.py `coverage` mode and its pyproject.toml settings (CLAUDE.md 5.34): every layer runs
under coverage.py, the subprocess data is combined, reports go to the output folder, an optional
floor (--fail-under) makes a low total a FAIL, the mode stays out of quick / ci, and the settings
that make subprocess measurement work cannot be broken by accident. qa.py is loaded by path.
"""

import importlib.util
import tomllib
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]
QA = TESTS / "qa.py"
PYPROJECT = TESTS.parent / "pyproject.toml"


@pytest.fixture()
def qa():
    spec = importlib.util.spec_from_file_location("qa_cov_under_test", QA)
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
            if name == "coverage"
            else real(name, *a, **k)
        ),
    )


def _verbs(step):
    return [cmd[3] for cmd in step.cmds]  # python -m coverage <verb> ...


def test_coverage_is_skipped_when_it_is_not_installed(qa, monkeypatch):
    _pretend_installed(qa, monkeypatch, False)
    step = qa._coverage_step(["unit"])
    assert step.skip and "coverage>=7.10" in step.skip


def test_coverage_is_skipped_without_any_layer_folder(qa, monkeypatch):
    _pretend_installed(qa, monkeypatch, True)
    assert qa._coverage_step([]).skip


def test_the_steps_erase_run_every_layer_combine_and_report(qa, monkeypatch):
    _pretend_installed(qa, monkeypatch, True)
    step = qa._coverage_step(["unit", "protocols"])
    assert _verbs(step) == ["erase", "run", "combine", "report"]
    run = step.cmds[1]
    assert run[4:6] == ["-m", "pytest"]
    assert [Path(p).name for p in run if "tests" in p and p != "tests"] == [
        "unit",
        "protocols",
    ]
    assert "--fail-under" not in step.cmds[-1]


def test_reports_are_written_to_the_output_folder(qa, monkeypatch):
    _pretend_installed(qa, monkeypatch, True)
    step = qa._coverage_step(["unit"], out="out")
    assert _verbs(step) == ["erase", "run", "combine", "xml", "html", "report"]
    assert Path(step.cmds[3][-1]) == Path("out") / "coverage.xml"
    assert Path(step.cmds[4][-1]) == Path("out") / "htmlcov"


def test_a_floor_is_only_given_to_the_report_which_comes_last(qa, monkeypatch):
    _pretend_installed(qa, monkeypatch, True)
    step = qa._coverage_step(["unit"], out="out", fail_under=70)
    assert step.cmds[-1][3] == "report"
    assert step.cmds[-1][-2:] == ["--fail-under", "70"]
    assert all("--fail-under" not in c for c in step.cmds[:-1])


def test_a_failing_test_does_not_throw_the_collected_data_away(qa, monkeypatch):
    _pretend_installed(qa, monkeypatch, True)
    assert qa._coverage_step(["unit"]).keep_going is True


def test_keep_going_runs_every_command_but_the_step_still_fails(qa, tmp_path):
    py = qa.PY
    first = [py, "-c", "import sys; sys.exit(1)"]
    second = [py, "-c", "open('second.txt', 'w').write('ran')"]
    step = qa.Step("x", [first, second], keep_going=True, hint="h")
    code, results = qa.run_steps([step], cwd=tmp_path)
    assert code == 1 and results[0][1] == "FAIL"
    assert (tmp_path / "second.txt").read_text() == "ran"
    assert "exit 1" in results[0][3] and "(h)" in results[0][3]


def test_without_keep_going_the_first_failure_stops_the_step(qa, tmp_path):
    py = qa.PY
    first = [py, "-c", "import sys; sys.exit(1)"]
    second = [py, "-c", "open('second.txt', 'w').write('ran')"]
    code, results = qa.run_steps([qa.Step("x", [first, second])], cwd=tmp_path)
    assert code == 1 and not (tmp_path / "second.txt").exists()


def test_pytest_exit_5_means_nothing_to_run(qa, monkeypatch):
    _pretend_installed(qa, monkeypatch, True)
    assert 5 in qa._coverage_step(["unit"]).skip_codes


def test_the_data_file_is_absolute_and_inside_the_output_folder(qa):
    path = Path(qa._coverage_data_file("somewhere"))
    assert path.is_absolute() and path.name == ".coverage"
    assert path.parent.name == "somewhere"
    assert Path(qa._coverage_data_file(None)).parent.name == "artifacts"


@pytest.mark.parametrize("mode", ["static", "tests", "quick", "ci"])
def test_the_everyday_modes_never_run_coverage(qa, mode):
    assert "coverage" not in [s.name for s in qa.build_plan(mode)]


def test_coverage_is_a_registered_mode(qa):
    assert '"coverage"]' in QA.read_text(encoding="utf-8").split("choices=[", 1)[1][:90]


def test_pyproject_keeps_the_settings_subprocess_measurement_needs():
    run = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["coverage"][
        "run"
    ]
    assert run["patch"] == ["subprocess"]  # the servers run as subprocesses
    assert run["sigterm"] is True  # the harness stops them with terminate()
    assert run["parallel"] is True  # one data file per process
    assert run["relative_files"] is True  # scratch copy and repository = same file
    # `source` is resolved to the repository by the parent: a subprocess running in a scratch
    # copy would then measure nothing (found in 5.34).
    assert "source" not in run
