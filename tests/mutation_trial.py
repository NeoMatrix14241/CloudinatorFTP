#!/usr/bin/env python3
"""
tests/mutation_trial.py - does the test suite NOTICE when the code is wrong? (CLAUDE.md 5.40)

A mutation trial makes one small deliberate mistake at a time in a function (== becomes !=,
`and` becomes `or`, a number goes up by one, a `not` disappears ...), runs the tests, and counts
the mistakes the tests did NOT catch ("survivors"). A survivor is either a missing test or a line
that does not matter; either way it is worth a look. 100 % is not the goal.

    python tests/mutation_trial.py storage.py --functions is_safe_chunk_id,is_safe_path \\
        --tests tests/property tests/unit/test_assemble_atomic.py

Why this instead of mutmut: mutmut 3 rewrites every function into a trampoline, and the unit tests
read their functions straight out of the source file with `ast` (the modules start threads and
import config, so they are never imported), which cannot read a trampoline. This script mutates
the SOURCE TEXT's syntax tree and works with that kind of test. Standard library only.

Safety: the work happens in a TEMPORARY COPY of the Python files and the tests (never in the real
tree), so a Ctrl-C can never leave a mutated file in the project. Run it on Linux or Windows; it
needs pytest (and hypothesis, if the chosen tests use it). Not part of `qa quick` / `qa ci`:
a trial runs the tests once per mutation, so it takes minutes. The nightly workflow does not run
it either; the manual "Mutation trial" workflow does.

Exit code: 0 = the trial ran (survivors are REPORTED, not failed; use --max-survivors N to fail),
2 = bad arguments or the tests do not pass on the unmodified code.
"""

import argparse
import ast
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPY_DIRS = ("tests", "routes", "helpers", "tools")
SWAP_COMPARE = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}


def _candidates(function):
    """Every place inside `function` where one small mistake can be made, in a stable order."""
    found = []
    for node in ast.walk(function):
        if isinstance(node, ast.Compare):
            for index, op in enumerate(node.ops):
                if type(op) in SWAP_COMPARE:
                    found.append(("compare", node, index))
        elif isinstance(node, ast.BoolOp):
            found.append(("boolop", node, None))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            found.append(("not", node, None))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            found.append(("bool", node, None))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool)
        ):
            found.append(("number", node, None))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            found.append(("arith", node, None))
        elif isinstance(node, ast.Return) and node.value is not None:
            found.append(("return", node, None))
    return found


def _describe(kind, node, index):
    line = getattr(node, "lineno", "?")
    if kind == "compare":
        return f"line {line}: comparison #{index + 1} inverted"
    return {
        "boolop": f"line {line}: and <-> or",
        "not": f"line {line}: `not` removed",
        "bool": f"line {line}: True <-> False",
        "number": f"line {line}: number changed by one",
        "arith": f"line {line}: + <-> -",
        "return": f"line {line}: return value replaced by None",
    }[kind]


def _apply(kind, node, index):
    """Make the mistake in `node` (a node of a private copy of the tree). Returns the node that
    replaces it (or None to keep the node)."""
    if kind == "compare":
        node.ops[index] = SWAP_COMPARE[type(node.ops[index])]()
    elif kind == "boolop":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif kind == "not":
        return node.operand
    elif kind == "bool":
        node.value = not node.value
    elif kind == "number":
        node.value = node.value + 1
    elif kind == "arith":
        node.op = ast.Sub() if isinstance(node.op, ast.Add) else ast.Add()
    elif kind == "return":
        node.value = ast.Constant(value=None)
    return None


def _mutant_source(tree, function_name, number):
    """Source text of `tree` with the `number`-th candidate of the function(s) called
    `function_name` mutated, plus what was done."""
    clone = copy.deepcopy(tree)
    counter = 0
    for function in ast.walk(clone):
        if not (
            isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            and function.name == function_name
        ):
            continue
        for kind, node, index in _candidates(function):
            if counter == number:
                label = _describe(kind, node, index)
                replacement = _apply(kind, node, index)
                if replacement is not None:
                    _replace(clone, node, replacement)
                return ast.unparse(ast.fix_missing_locations(clone)), label
            counter += 1
    return None, None


def _replace(tree, old, new):
    for parent in ast.walk(tree):
        for field, value in ast.iter_fields(parent):
            if value is old:
                setattr(parent, field, new)
                return
            if isinstance(value, list):
                for position, item in enumerate(value):
                    if item is old:
                        value[position] = new
                        return


def _count_candidates(tree, function_name):
    total = 0
    for function in ast.walk(tree):
        if (
            isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            and function.name == function_name
        ):
            total += len(_candidates(function))
    return total


def _make_workdir():
    work = Path(tempfile.mkdtemp(prefix="mutation_trial_"))
    for path in ROOT.glob("*.py"):
        shutil.copy2(path, work / path.name)
    for name in ("pyproject.toml",):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, work / name)
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", ".hypothesis")
    for directory in COPY_DIRS:
        if (ROOT / directory).is_dir():
            shutil.copytree(ROOT / directory, work / directory, ignore=skip)
    return work


def _run_tests(work, tests, timeout):
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-x",
        "-q",
        "-p",
        "no:cacheprovider",
        *tests,
    ]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        done = subprocess.run(
            command,
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "timeout", ""
    return ("pass" if done.returncode == 0 else "fail"), done.stdout[-1500:]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "file", help="the source file to mutate, relative to the project root"
    )
    parser.add_argument(
        "--functions", required=True, help="comma-separated function names"
    )
    parser.add_argument(
        "--tests", nargs="+", required=True, help="pytest paths that cover them"
    )
    parser.add_argument("--timeout", type=int, default=120, help="seconds per test run")
    parser.add_argument(
        "--limit", type=int, default=0, help="stop after N mutants (0 = all)"
    )
    parser.add_argument(
        "--max-survivors", type=int, default=-1, help="fail when more survive"
    )
    args = parser.parse_args(argv)

    target = ROOT / args.file
    if not target.is_file():
        print(f"no such file: {target}")
        return 2
    original = target.read_text(encoding="utf-8")
    tree = ast.parse(original)
    names = [n.strip() for n in args.functions.split(",") if n.strip()]
    plan = [(name, _count_candidates(tree, name)) for name in names]
    missing = [name for name, count in plan if count == 0]
    if missing:
        print(
            f"nothing to mutate in: {', '.join(missing)} (not found, or no mutable code)"
        )
        return 2

    work = _make_workdir()
    try:
        status, tail = _run_tests(work, args.tests, args.timeout)
        if status != "pass":
            print(
                "The tests do not pass on the UNMODIFIED code, so a trial would mean nothing:"
            )
            print(tail)
            return 2
        print(
            f"baseline green; {sum(c for _, c in plan)} mutants in {len(plan)} function(s)"
        )

        mutated_file = work / args.file
        survivors, killed, started, run = [], 0, time.monotonic(), 0
        for name, count in plan:
            for number in range(count):
                if args.limit and run >= args.limit:
                    break
                source, label = _mutant_source(tree, name, number)
                if source is None:
                    continue
                run += 1
                mutated_file.write_text(source, encoding="utf-8")
                status, _ = _run_tests(work, args.tests, args.timeout)
                if status == "pass":
                    survivors.append(f"{args.file}::{name}: {label}")
                    print(f"  SURVIVED  {name}: {label}")
                else:
                    killed += 1
                    print(
                        f"  killed    {name}: {label}"
                        + ("  (timeout)" if status == "timeout" else "")
                    )
        mutated_file.write_text(original, encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    total = killed + len(survivors)
    score = 100.0 * killed / total if total else 100.0
    print(
        f"\n{killed} of {total} mutants killed ({score:.0f} %), {len(survivors)} survived, "
        f"{time.monotonic() - started:.0f} s"
    )
    for line in survivors:
        print("  survivor:", line)
    if 0 <= args.max_survivors < len(survivors):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
