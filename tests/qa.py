#!/usr/bin/env python3
"""
tests/qa.py - the single quality-assurance runner for CloudinatorFTP (CLAUDE.md 5.00).

manage.sh (Quality Assurance section, planned), the GitHub workflows and developers all call
this one file, so "green locally" and "green in CI" mean the same commands ran.

    python tests/qa.py static              smoke.py, check.py, SRI check, node --check on first-party JS
    python tests/qa.py tests               pytest on every tests/ layer folder that exists
    python tests/qa.py quick               static + tests
    python tests/qa.py layer <name>        one layer: unit integration application protocols property
                                           reliability performance frontend
    python tests/qa.py ci                  quick, with JUnit XML written to ./artifacts (or --out DIR)
    python tests/qa.py audit               pip-audit on the installed packages (needs network and
                                           `python -m pip install pip-audit`); NOT part of quick / ci
    python tests/qa.py audit --path DIR    the same for another environment's site-packages folder
                                           (CI keeps pip-audit in its own venv, away from the app's)

    --skip-packages   pass to check.py (use where requirements.txt is not installed, like CI static job)
    --out DIR         write JUnit XML for the pytest steps into DIR
    --fail-fast       stop at the first failing step

Exit code: 0 = every step passed or was skipped, 1 = at least one step failed, 130 = Ctrl-C.
A SKIP never hides a failure: tools that are not installed (node, pip-audit) or files that do not
exist (tools/sri_validator.py) are reported as SKIP with the reason.

`audit` stays out of quick / ci on purpose: new advisories appear without any code change and an
offline machine cannot run it, so it must never turn the everyday run (or a pull request) red.
Known, accepted findings go into tests/audit_ignore.txt (one advisory ID per line, then a reason).

Standard library only. This script never imports the application and never passes --force to
check.py.
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

QA_VERSION = (
    "5.32"  # `python tests/qa.py --version`: tells you which copy of this file you run
)

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

LAYERS = (
    "unit",
    "integration",
    "application",
    "protocols",
    "property",
    "reliability",
    "performance",
    "frontend",
)
# Vendored third-party scripts: not ours to syntax-check.
VENDOR_JS = {"video.js", "pdf.mjs", "pdf.worker.mjs", "viewer.mjs"}


class Step:
    """One named step: a list of commands run in order (stops at the first failing one)."""

    def __init__(self, name, cmds=None, skip=None, skip_codes=(), hint="", fail=None):
        self.name = name
        self.cmds = cmds or []
        self.skip = skip  # reason string -> reported as SKIP, nothing runs
        self.fail = fail  # reason string -> reported as FAIL, nothing runs
        self.skip_codes = tuple(skip_codes)  # exit codes that mean "nothing to run"
        self.hint = hint


def _static_steps(skip_packages):
    steps = [Step("smoke", [[PY, "tests/smoke.py"]])]
    check = [PY, "tests/check.py", "-q"]
    if skip_packages:
        check.append("--skip-packages")
    steps.append(Step("check", [check]))

    sri = ROOT / "tools" / "sri_validator.py"
    if sri.is_file():
        steps.append(
            Step(
                "sri",
                [
                    [
                        PY,
                        "tools/sri_validator.py",
                        "--templates",
                        "templates",
                        "--static",
                        "static",
                    ]
                ],
                hint="stale hash: run ./manage.sh validate-sri --fix",
            )
        )
    else:
        steps.append(Step("sri", skip="tools/sri_validator.py not found"))

    js_dir = ROOT / "static" / "js"
    files = []
    if js_dir.is_dir():
        files = sorted(
            p
            for p in js_dir.iterdir()
            if p.suffix in (".js", ".mjs") and p.name not in VENDOR_JS
        )
    if not files:
        steps.append(Step("js-syntax", skip="no first-party JS files found"))
    elif shutil.which("node") is None:
        steps.append(Step("js-syntax", skip="node is not installed"))
    else:
        steps.append(Step("js-syntax", [["node", "--check", str(p)] for p in files]))
    return steps


def _pytest_available():
    return importlib.util.find_spec("pytest") is not None


def _pytest_step(name, dirs, out):
    cmd = [PY, "-m", "pytest", *[str(d) for d in dirs], "-q"]
    if out:
        cmd += ["--junitxml", str(Path(out) / f"{name}.xml")]
    return Step(
        name,
        [cmd],
        skip_codes=(5,),  # pytest exit 5 = no tests collected
        # only when pytest really is missing; any other failure is a test failure
        hint=(
            ""
            if _pytest_available()
            else "pytest is not installed: python -m pip install -r requirements-dev.txt"
        ),
    )


def _audit_ignores(path):
    """Advisory IDs from tests/audit_ignore.txt: the first word of every non-comment line."""
    ids = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ids
    for line in lines:
        word = line.split("#", 1)[0].split()
        if word:
            ids.append(word[0])
    return ids


def _venv_python_location(venv, exe):
    """`exe` re-spelled to start with `venv` exactly as $VIRTUAL_ENV writes it, or None when `exe`
    is not inside that virtual environment (then pip-audit's warning is justified)."""
    if not venv:
        return None

    def norm(p):
        return p.replace("\\", "/").rstrip("/").lower()

    if not norm(exe).startswith(norm(venv) + "/"):
        return None
    venv = venv.rstrip("/\\")
    return venv + exe[len(venv) :]


def _audit_step(path=None):
    """pip-audit on the packages installed for THIS interpreter (what actually runs), or on
    the site-packages folder `path` of another environment."""
    if importlib.util.find_spec("pip_audit") is None:
        return Step(
            "audit", skip="pip-audit is not installed: python -m pip install pip-audit"
        )
    cmd = [PY, "-m", "pip_audit", "--progress-spinner", "off"]
    cmd += ["--path", str(path)] if path else ["--local"]
    for vuln_id in _audit_ignores(ROOT / "tests" / "audit_ignore.txt"):
        cmd += ["--ignore-vuln", vuln_id]
    return Step(
        "audit",
        [cmd],
        hint="upgrade the package, or add the advisory ID and the reason to tests/audit_ignore.txt",
    )


def _existing_layers():
    return [n for n in LAYERS if (ROOT / "tests" / n).is_dir()]


def _layout_step():
    """A FAIL step when test_*.py files sit directly in tests/ (no layer runs them)."""
    tests = ROOT / "tests"
    stray = sorted(p.name for p in tests.glob("test_*.py")) if tests.is_dir() else []
    if not stray:
        return None
    return Step(
        "layout",
        fail="test files directly in tests/ are run by no layer; move them into a layer folder "
        "(tests/unit/ or tests/application/): " + ", ".join(stray),
    )


def _with_layout(steps):
    layout = _layout_step()
    return ([layout] if layout else []) + steps


def build_plan(mode, layer=None, skip_packages=False, out=None, path=None):
    """Return the list of Steps for a mode. Raises ValueError for unknown input."""
    if mode == "static":
        return _static_steps(skip_packages)
    if mode == "tests":
        layers = _existing_layers()
        if not layers:
            return _with_layout([Step("pytest", skip="no tests/<layer> folders yet")])
        return _with_layout(
            [_pytest_step("pytest", [ROOT / "tests" / n for n in layers], out)]
        )
    if mode == "audit":
        return [_audit_step(path)]
    if mode in ("quick", "ci"):
        return _static_steps(skip_packages) + build_plan("tests", out=out)
    if mode == "layer":
        if layer not in LAYERS:
            raise ValueError(
                f"unknown layer {layer!r}; choose one of: {', '.join(LAYERS)}"
            )
        if not (ROOT / "tests" / layer).is_dir():
            return _with_layout(
                [Step(layer, skip=f"tests/{layer}/ does not exist yet")]
            )
        return _with_layout([_pytest_step(layer, [ROOT / "tests" / layer], out)])
    raise ValueError(f"unknown mode {mode!r}")


def run_steps(steps, fail_fast=False, cwd=ROOT):
    """Run the steps, print a summary, return (exit_code, results)."""
    results = []
    for step in steps:
        print(f"\n=== {step.name} ===", flush=True)
        if step.skip:
            print(f"SKIP: {step.skip}")
            results.append((step.name, "SKIP", 0.0, step.skip))
            continue
        if step.fail:
            print(f"FAIL: {step.fail}")
            results.append((step.name, "FAIL", 0.0, step.fail))
            if fail_fast:
                break
            continue
        t0 = time.monotonic()
        status, detail = "PASS", ""
        for cmd in step.cmds:
            code = subprocess.call(cmd, cwd=str(cwd))
            if code in step.skip_codes:
                status, detail = "SKIP", "nothing to run"
                break
            if code != 0:
                status, detail = (
                    "FAIL",
                    f"exit {code}: {' '.join(str(c) for c in cmd[:4])}",
                )
                if step.hint:
                    detail += f"  ({step.hint})"
                break
        results.append((step.name, status, time.monotonic() - t0, detail))
        if status == "FAIL" and fail_fast:
            break

    print("\n" + "-" * 60)
    for name, status, secs, detail in results:
        line = f"[{status}] {name:<12} {secs:6.1f}s"
        print(line + (f"  {detail}" if detail and status != "PASS" else ""))
    failed = [r for r in results if r[1] == "FAIL"]
    print("-" * 60)
    print(f"{len(results) - len(failed)} ok/skipped, {len(failed)} failed")
    return (1 if failed else 0), results


def main(argv=None):
    ap = argparse.ArgumentParser(description="CloudinatorFTP QA runner")
    ap.add_argument("--version", action="version", version=f"qa.py {QA_VERSION}")
    ap.add_argument(
        "mode", choices=["static", "tests", "quick", "layer", "ci", "audit"]
    )
    ap.add_argument("layer", nargs="?", help="layer name (mode 'layer' only)")
    ap.add_argument("--skip-packages", action="store_true")
    ap.add_argument("--out", metavar="DIR")
    ap.add_argument("--fail-fast", action="store_true")
    ap.add_argument(
        "--path", metavar="DIR", help="site-packages to audit (mode 'audit' only)"
    )
    args = ap.parse_args(argv)

    if args.mode == "audit":
        # pip-audit warns "your local environment will not be audited" when the interpreter path
        # does not START WITH $VIRTUAL_ENV as plain text; Git Bash spells the venv C:/..., Windows
        # spells the interpreter C:\... (the venv IS audited: this interpreter is the venv's).
        location = _venv_python_location(os.environ.get("VIRTUAL_ENV"), PY)
        if location:
            os.environ.setdefault("PIPAPI_PYTHON_LOCATION", location)
    out = args.out or ("artifacts" if args.mode == "ci" else None)
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
    try:
        steps = build_plan(args.mode, args.layer, args.skip_packages, out, args.path)
    except ValueError as e:
        print(f"qa: {e}", file=sys.stderr)
        return 2
    try:
        code, _ = run_steps(steps, args.fail_fast)
    except KeyboardInterrupt:
        print("\nqa: interrupted")
        return 130
    return code


if __name__ == "__main__":
    sys.exit(main())
