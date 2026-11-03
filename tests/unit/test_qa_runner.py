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


# ---------------------------------------------------------------------------- lint (5.41)
def _pretend_ruff(qa, monkeypatch, installed=True):
    monkeypatch.setattr(
        qa.importlib.util,
        "find_spec",
        lambda name, *a, **k: object() if (installed and name == "ruff") else None,
    )


def test_lint_is_one_report_only_step_by_default(qa, monkeypatch):
    _pretend_ruff(qa, monkeypatch)
    plan = qa.build_plan("lint")
    assert [s.name for s in plan] == ["lint"]
    listing, counts = plan[0].cmds
    assert listing[1:5] == ["-m", "ruff", "check", "."]
    assert "--exit-zero" in listing and "concise" in listing
    assert "--exit-zero" in counts and "--statistics" in counts
    assert plan[0].keep_going is True and plan[0].skip is None


def test_strict_lint_drops_exit_zero_from_the_listing_only(qa, monkeypatch):
    _pretend_ruff(qa, monkeypatch)
    listing, counts = qa.build_plan("lint", strict=True)[0].cmds
    assert "--exit-zero" not in listing
    assert "--exit-zero" in counts  # the per-rule counts are printed either way


def test_lint_skips_with_the_install_hint_when_ruff_is_missing(qa, monkeypatch):
    _pretend_ruff(qa, monkeypatch, installed=False)
    step = qa.build_plan("lint")[0]
    assert step.skip and "requirements-dev.txt" in step.skip
    code, results = qa.run_steps([step])
    assert code == 0 and results[0][1] == "SKIP"


@pytest.mark.parametrize("mode", ["quick", "static", "tests", "ci"])
def test_lint_is_not_part_of_the_other_modes(qa, monkeypatch, mode):
    _pretend_ruff(qa, monkeypatch)
    assert "lint" not in [s.name for s in qa.build_plan(mode)]


def test_the_strict_flag_reaches_the_plan(qa, monkeypatch):
    seen = []
    monkeypatch.setattr(
        qa, "build_plan", lambda *args, **kwargs: seen.append(args) or []
    )
    qa.main(["lint", "--strict"])
    qa.main(["lint"])
    assert seen[0][0] == "lint" and seen[0][-1] is True
    assert seen[1][-1] is False


# ---------------------------------------------------------------------------- build banner (5.42)
def _fake_python(version, free_threaded, gil_enabled="absent"):
    import types

    sysconfig = types.SimpleNamespace(
        get_config_var=lambda key: (
            1 if (key == "Py_GIL_DISABLED" and free_threaded) else 0
        )
    )
    sys_stub = types.SimpleNamespace(version_info=version)
    if gil_enabled != "absent":
        sys_stub._is_gil_enabled = lambda: gil_enabled
    return sysconfig, sys_stub


@pytest.mark.parametrize(
    "free_threaded, gil, expected",
    [
        (False, True, "3.14.7 standard build, GIL on"),
        (True, False, "3.14.7 free-threaded build, GIL off"),
        (True, True, "3.14.7 free-threaded build, GIL on"),
        (True, "absent", "3.14.7 free-threaded build, GIL state unknown"),
    ],
)
def test_the_build_banner_names_the_build_and_the_gil_state(
    qa, free_threaded, gil, expected
):
    sysconfig, sys_stub = _fake_python((3, 14, 7, "final", 0), free_threaded, gil)
    assert qa.python_build_line(sysconfig, sys_stub) == expected


def test_the_build_banner_of_this_interpreter_is_printed_by_every_mode(
    qa, monkeypatch, capsys
):
    monkeypatch.setattr(qa, "build_plan", lambda *args, **kwargs: [])
    qa.main(["static"])
    assert f"python: {qa.python_build_line()}" in capsys.readouterr().out
