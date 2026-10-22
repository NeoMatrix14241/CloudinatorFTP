"""
Tests for the Quality Assurance section of manage.sh (menu 21-25 and the `qa` command) and for
its Developer Tools section (menu 26-27, the `dir-tree` and `smoke` commands).

They read the real manage.sh and only run side-effect-free commands (`help`, `qa --version`,
`qa bogus`, `qa layer nope`); no server is started and nothing is written. The numbering test
guards against the menu drifting from its dispatch table and from `help` (CLAUDE.md records
three earlier renumbering accidents). Raise LAST_ENTRY whenever the menu grows.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "manage.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    BASH is None or not SCRIPT.is_file(), reason="bash or manage.sh not found"
)

LAST_ENTRY = 27


def _text():
    return SCRIPT.read_text(encoding="utf-8")


def _function(name):
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", _text(), re.S | re.M)
    assert m, f"{name}() not found in manage.sh"
    return m.group(0)


def _run(*args):
    return subprocess.run(
        [BASH, "manage.sh", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def test_menu_listing_and_dispatch_cover_the_same_numbers():
    body = _function("cmd_menu")
    listed = set()
    for line in body.splitlines():
        m = re.match(
            r"\t+echo.*?\b(\d{1,2})\) ", line
        )  # 19) sits one level deeper (if is_termux)
        if m:
            listed.add(int(m.group(1)))
    arms = {int(n) for n in re.findall(r"^\t\t(\d{1,2})\) ", body, re.M)}
    assert listed == arms == set(range(1, LAST_ENTRY + 1)), (
        sorted(listed),
        sorted(arms),
    )


def test_help_menu_map_lists_every_number():
    out = _run("help").stdout
    block = out.split("COMMAND MAP", 1)[1].split("EXAMPLES", 1)[0]
    numbers = {int(n) for n in re.findall(r"(?<!\d)(\d{1,2})  (?=[a-z])", block)}
    assert numbers == set(range(1, LAST_ENTRY + 1)), sorted(numbers)


def test_menu_arms_run_the_expected_qa_modes():
    body = _function("cmd_menu")
    for num, call in {
        21: "cmd_qa quick",
        22: "cmd_qa static",
        23: "cmd_qa tests",
        24: "_menu_qa_layer",
        25: "cmd_qa ci",
    }.items():
        assert re.search(
            rf"^\t\t{num}\) _menu_run {re.escape(call)} ;;$", body, re.M
        ), num


def test_menu_arms_run_the_developer_tools():
    body = _function("cmd_menu")
    for num, call in {
        26: 'run_utility "tests/dir_tree.py"',
        27: "_menu_smoke_save",
    }.items():
        assert re.search(
            rf"^\t\t{num}\) _menu_run {re.escape(call)} ;;$", body, re.M
        ), num


def test_qa_is_dispatched_and_launches_the_runner_through_run_utility():
    assert re.search(r"^\tqa\) cmd_qa \"\$@\" ;;$", _function("main"), re.M)
    assert 'run_utility "tests/qa.py"' in _function("cmd_qa")
    assert (ROOT / "tests" / "qa.py").is_file()


def test_developer_tools_are_dispatched_and_launch_their_scripts():
    main = _function("main")
    assert re.search(
        r"^\tdir-tree\) run_utility \"tests/dir_tree.py\" \"\$@\" ;;$", main, re.M
    )
    assert re.search(r"^\tsmoke\) cmd_smoke \"\$@\" ;;$", main, re.M)
    assert 'run_utility "tests/smoke.py"' in _function("cmd_smoke")
    assert (ROOT / "tests" / "dir_tree.py").is_file()
    assert (ROOT / "tests" / "smoke.py").is_file()


def test_help_documents_the_developer_tools():
    out = _run("help").stdout
    for text in (
        "DEVELOPER TOOLS COMMANDS",
        "dir-tree",
        "smoke [options]",
        "smoke --save",
    ):
        assert text in out, text


def test_help_documents_every_qa_mode():
    out = _run("help").stdout
    for text in (
        "QUALITY ASSURANCE COMMANDS",
        "qa [quick]",
        "qa static",
        "qa tests",
        "qa layer <name>",
        "qa ci",
        "qa --version",
    ):
        assert text in out, text


def test_unknown_qa_mode_exits_2():
    proc = _run("qa", "bogus")
    assert proc.returncode == 2
    assert "Unknown qa mode" in proc.stderr


def test_qa_version_reaches_the_runner():
    proc = _run("qa", "--version")
    assert proc.returncode == 0, proc.stderr
    assert "qa.py" in proc.stdout


def test_runner_exit_code_is_passed_through():
    proc = _run("qa", "layer", "no_such_layer")
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "unknown layer" in proc.stderr
