"""
tests/smoke.py and tests/check.py skip the same generated / local folders (5.44.3).

Both scripts walk EVERY folder under the project root (a .py file in a brand-new folder is checked
too), except the names in their `SKIP_DIRS`. A local `build/` folder (in .gitignore: Nuitka build,
entry and self-test scripts) was scanned and its self-test's own Quart app, with an `index` route,
made smoke report "endpoint 'index' defined 2 times" next to routes/files.py, so `qa quick` failed
on one machine while the repository and CI were fine. The two lists must stay equal (a name added
to one and forgotten in the other gives one script's pass and the other's failure) and must cover
every folder that .gitignore names as a build output.
"""

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
ROOT = TESTS.parent


def _skip_dirs(script):
    tree = ast.parse((TESTS / script).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SKIP_DIRS" for t in node.targets
        ):
            return set(ast.literal_eval(node.value))
    raise AssertionError(f"SKIP_DIRS not found in tests/{script}")


def test_smoke_and_check_skip_the_same_folders():
    assert _skip_dirs("smoke.py") == _skip_dirs("check.py")


def test_a_local_build_folder_is_never_scanned():
    for script in ("smoke.py", "check.py"):
        assert "build" in _skip_dirs(script), script


def test_every_build_output_folder_of_gitignore_is_skipped():
    ignore = ROOT / ".gitignore"
    if not ignore.is_file():
        return
    listed = {
        line.strip().rstrip("/")
        for line in ignore.read_text(encoding="utf-8").splitlines()
        if line.strip().endswith("/") and "/" not in line.strip().rstrip("/")
    }
    # folders that hold generated or local files and can contain .py files
    generated = {"build", "venv", ".venv", "logs", "uploads"}
    assert (listed & generated) <= _skip_dirs("smoke.py") | {
        d for d in listed if d.startswith(".")
    }
