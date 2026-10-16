"""Tests of tests/qa.py: plan selection, exit codes, skip handling."""

import importlib.util
import sys
from pathlib import Path

import pytest

QA_PATH = Path(__file__).resolve().parent.parent / "qa.py"


@pytest.fixture(scope="module")
def qa():
    spec = importlib.util.spec_from_file_location("qa_runner_under_test", QA_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "QA_VERSION"):
        pytest.fail(
            "tests/qa.py is OLDER than tests/unit/test_qa_runner.py (it has no QA_VERSION, "
            "i.e. it predates 5.03). Overwrite tests/qa.py with the one from the zip.",
            pytrace=False,
        )
    return mod


def _ok(qa, name="ok"):
    return qa.Step(name, [[sys.executable, "-c", "pass"]])


def _bad(qa, name="bad", code=3):
    return qa.Step(name, [[sys.executable, "-c", f"raise SystemExit({code})"]])


def test_all_passing_returns_zero(qa):
    code, results = qa.run_steps([_ok(qa, "a"), _ok(qa, "b")])
    assert code == 0 and [r[1] for r in results] == ["PASS", "PASS"]


def test_one_failure_returns_one_and_later_steps_still_run(qa):
    code, results = qa.run_steps([_bad(qa), _ok(qa)])
    assert code == 1
    assert [r[1] for r in results] == ["FAIL", "PASS"]


def test_fail_fast_stops_at_the_first_failure(qa):
    code, results = qa.run_steps([_bad(qa), _ok(qa)], fail_fast=True)
    assert code == 1 and len(results) == 1


def test_skip_never_fails_the_run(qa):
    code, results = qa.run_steps([qa.Step("s", skip="not installed"), _ok(qa)])
    assert code == 0 and results[0][1] == "SKIP"


def test_skip_code_is_reported_as_skip(qa):
    step = qa.Step(
        "p", [[sys.executable, "-c", "raise SystemExit(5)"]], skip_codes=(5,)
    )
    code, results = qa.run_steps([step])
    assert code == 0 and results[0][1] == "SKIP"


def test_a_failing_command_stops_the_rest_of_that_step(qa, tmp_path):
    marker = tmp_path / "ran_second"
    step = qa.Step(
        "multi",
        [
            [sys.executable, "-c", "raise SystemExit(1)"],
            [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
        ],
    )
    code, _ = qa.run_steps([step])
    assert code == 1 and not marker.exists()


def test_failure_detail_carries_the_hint(qa):
    step = qa.Step("h", [[sys.executable, "-c", "raise SystemExit(2)"]], hint="do this")
    _, results = qa.run_steps([step])
    assert "do this" in results[0][3]


def test_static_plan_names_and_order(qa):
    names = [s.name for s in qa.build_plan("static")]
    assert names == ["smoke", "check", "sri", "js-syntax"]


def test_check_gets_skip_packages_only_when_asked(qa):
    plain = qa.build_plan("static")[1].cmds[0]
    skipping = qa.build_plan("static", skip_packages=True)[1].cmds[0]
    assert "--skip-packages" not in plain and "--skip-packages" in skipping
    assert "--force" not in plain + skipping


def test_quick_is_static_plus_tests(qa):
    quick = [s for s in qa.build_plan("quick") if s.name != "layout"]
    assert [s.name for s in quick][:4] == ["smoke", "check", "sri", "js-syntax"]
    assert len(quick) == len(qa.build_plan("static")) + 1


def test_unknown_layer_and_mode_are_rejected(qa):
    with pytest.raises(ValueError):
        qa.build_plan("layer", layer="nope")
    with pytest.raises(ValueError):
        qa.build_plan("bogus")


def test_junit_path_is_added_when_out_is_given(qa, tmp_path):
    step = qa.build_plan("layer", layer="unit", out=str(tmp_path))[0]
    cmd = step.cmds[0]
    assert "--junitxml" in cmd and cmd[cmd.index("--junitxml") + 1].endswith("unit.xml")


def test_stray_test_file_in_tests_root_fails_the_run(qa, tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_stray.py").write_text(
        "def test_x(): pass\n", encoding="utf-8"
    )
    monkeypatch.setattr(qa, "ROOT", tmp_path)
    plan = qa.build_plan("layer", layer="unit")
    assert plan[0].name == "layout" and "test_stray.py" in plan[0].fail
    code, results = qa.run_steps(plan)
    assert code == 1 and results[0][1] == "FAIL"


@pytest.mark.parametrize("mode", ["tests", "quick", "ci"])
def test_stray_test_file_is_reported_in_every_pytest_mode(
    qa, tmp_path, monkeypatch, mode
):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_stray.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(qa, "ROOT", tmp_path)
    assert "layout" in [s.name for s in qa.build_plan(mode)]


def test_clean_tests_folder_has_no_layout_step(qa, tmp_path, monkeypatch):
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "test_ok.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(qa, "ROOT", tmp_path)
    assert "layout" not in [s.name for s in qa.build_plan("layer", layer="unit")]


def test_pip_hint_only_when_pytest_is_missing(qa, monkeypatch):
    monkeypatch.setattr(qa, "_pytest_available", lambda: False)
    assert "pip install" in qa.build_plan("layer", layer="unit")[-1].hint
    monkeypatch.setattr(qa, "_pytest_available", lambda: True)
    assert qa.build_plan("layer", layer="unit")[-1].hint == ""


def test_version_flag_prints_the_version(qa, capsys):
    with pytest.raises(SystemExit) as exc:
        qa.main(["--version"])
    assert exc.value.code == 0
    assert qa.QA_VERSION in capsys.readouterr().out
