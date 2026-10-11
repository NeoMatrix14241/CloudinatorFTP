#!/usr/bin/env python3
"""
tests/smoke.py - fast static safety net for CloudinatorFTP (CLAUDE.md 4.83).

    python tests/smoke.py            run all checks (a few seconds, safe at any time)
    python tests/smoke.py --save     write tests/smoke_routes.json (the route snapshot)
    python tests/smoke.py -v         also list the individual route table

SAFE BY DESIGN: it only READS source files. It never imports the app, starts no thread or
server, touches no storage/db/cache and needs no config, so it can run while the server is up
(importing `app` for real would run initialize_cleanup(), which deletes "old" chunks of the
current process only and could hit uploads of a running server - so that is deliberately NOT done).

What it catches (the mistakes the 4.68-4.82 refactor was most exposed to):
  1  syntax errors in any .py (root, routes/, tools/, tests/)
  2  pyflakes: undefined names / star imports (skipped with a hint if pyflakes is not installed)
  3  route table: one function per endpoint name, no (rule, method) registered twice
  4  url_for('x') / request.endpoint == 'x' / *_ENDPOINTS sets name a real endpoint
  5  hooks (before/after_request, errorhandler, template_filter, ...) only in middleware.py
     (+ the event-loop watchdog's before_serving in routes/stats.py)
  6  no `from app import` except the launchers; no `from x import *`; no import cycle through
     app / core / middleware / routes
  7  routes/ modules only import each other where the design allows it
  8  every routes/*.py is imported by app.py (otherwise its routes silently never register)
  9  every tools/*.py that imports a root module puts the project root on sys.path first
 10  manage.sh: every .py it launches exists, `bash -n` passes
 11  route snapshot: no route lost since the last `--save` (new routes are only reported)

Exit code 0 = no FAIL, 1 = at least one FAIL.
"""

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = Path(__file__).resolve().parent / "smoke_routes.json"
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "node_modules",
    "logs",
    "static",
    "images",
    "uploads",
    "site-packages",
}

# routes/ modules that may import another routes/ module (documented in CLAUDE.md)
ALLOWED_ROUTE_IMPORTS = {
    "routes.admin": {"routes.hls", "routes.image_preview"},
    "routes.uploads": {"routes.shares"},
}
LAUNCHERS = {"dev_server.py", "prod_server.py", "protocol_manager.py"}
HOOK_NAMES = {
    "before_request",
    "after_request",
    "teardown_request",
    "errorhandler",
    "template_filter",
    "template_global",
    "template_test",
    "context_processor",
    "before_serving",
    "after_serving",
    "before_websocket",
    "after_websocket",
    "teardown_appcontext",
}
HOOK_ALLOWED = {"middleware.py": HOOK_NAMES, "routes/stats.py": {"before_serving"}}
CYCLE_SCOPE_FILES = {"app.py", "core.py", "middleware.py"}

results = []  # (status, check, detail lines)


def report(status, check, details=()):
    results.append((status, check, list(details)))


def rel(p):
    return p.relative_to(ROOT).as_posix()


def py_files():
    """Every .py under the project root (all folders, not only routes/ tools/ tests/), except
    SKIP_DIRS and hidden folders. A .py file in a brand-new folder is therefore checked too.
    """
    out = []
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
        )
        out += [Path(dirpath) / f for f in sorted(files) if f.endswith(".py")]
    return sorted(out, key=lambda p: (len(p.relative_to(ROOT).parts), p.as_posix()))


def parse(path):
    try:
        return ast.parse(
            path.read_text(encoding="utf-8", errors="replace"), filename=str(path)
        )
    except SyntaxError as e:
        return e


# --------------------------------------------------------------------------------------
def check_syntax(files, trees):
    bad = [
        f"{rel(f)}: {t.msg} (line {t.lineno})"
        for f, t in trees.items()
        if isinstance(t, SyntaxError)
    ]
    report("FAIL" if bad else "PASS", f"1 syntax ({len(files)} files)", bad)


def check_pyflakes(files):
    try:
        import pyflakes  # noqa: F401
    except ImportError:
        report(
            "SKIP",
            "2 pyflakes",
            [
                "not installed: pip install pyflakes  (this is the check that finds missing imports)"
            ],
        )
        return
    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes"] + [str(f) for f in files],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    fatal, warn = [], []
    for line in (proc.stdout + proc.stderr).splitlines():
        line = line.replace(str(ROOT) + "\\", "").replace(str(ROOT) + "/", "")
        if re.search(
            r"undefined name|undefined local|may be undefined|unable to detect undefined|import \*|unable to compile",
            line,
        ):
            fatal.append(line)
        elif "redefinition of unused" in line:
            warn.append(line)
    if fatal:
        report("FAIL", "2 pyflakes: undefined names / star imports", fatal)
    else:
        report("PASS", "2 pyflakes: undefined names / star imports")
    if warn:
        report(
            "WARN",
            f"2b pyflakes: {len(warn)} redefinition(s) (often a harmless local re-import; look at them once)",
            warn[:8],
        )


# --------------------------------------------------------------------------------------
def route_decorators(path, tree):
    """Yield (file, func, endpoint, rule, methods, lineno) for every @app.route(...) in a file."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if not (
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr == "route"
                and isinstance(d.func.value, ast.Name)
                and d.func.value.id == "app"
            ):
                continue
            rule = (
                d.args[0].value
                if d.args and isinstance(d.args[0], ast.Constant)
                else "?"
            )
            methods, endpoint = ["GET"], node.name
            for kw in d.keywords:
                if kw.arg == "methods" and isinstance(
                    kw.value, (ast.List, ast.Tuple, ast.Set)
                ):
                    methods = sorted(
                        e.value.upper()
                        for e in kw.value.elts
                        if isinstance(e, ast.Constant)
                    )
                if kw.arg == "endpoint" and isinstance(kw.value, ast.Constant):
                    endpoint = kw.value.value
            yield rel(path), node.name, endpoint, rule, methods, node.lineno


def collect_routes(trees):
    routes = []
    for f, t in trees.items():
        if isinstance(t, SyntaxError):
            continue
        if f.parent == ROOT / "tools" or f.parent == ROOT / "tests":
            continue
        routes += list(route_decorators(f, t))
    return routes


def check_routes(routes, verbose):
    by_endpoint = {}
    for file, func, endpoint, rule, methods, line in routes:
        by_endpoint.setdefault(endpoint, set()).add((file, func, line))
    dup_ep = [
        f"endpoint '{e}' defined {len(v)} times: "
        + ", ".join(f"{a}:{c}" for a, _b, c in sorted(v))
        for e, v in sorted(by_endpoint.items())
        if len(v) > 1
    ]
    seen, dup_rule = {}, []
    for file, func, endpoint, rule, methods, line in routes:
        for m in methods:
            key = (rule, m)
            if key in seen and seen[key] != (file, func, line):
                dup_rule.append(
                    f"{m} {rule} registered by {seen[key][1]} ({seen[key][0]}) and {func} ({file})"
                )
            seen.setdefault(key, (file, func, line))
    report(
        "FAIL" if dup_ep else "PASS",
        f"3a one function per endpoint ({len(by_endpoint)} endpoints)",
        dup_ep,
    )
    report(
        "FAIL" if dup_rule else "PASS",
        "3b no (rule, method) registered twice",
        dup_rule,
    )
    if verbose:
        for file, func, endpoint, rule, methods, _line in sorted(
            routes, key=lambda r: (r[3], r[2])
        ):
            print(f"      {','.join(methods):<22} {rule:<48} {endpoint}  [{file}]")
    return set(by_endpoint)


def check_endpoint_names(files, trees, endpoints):
    known = set(endpoints) | {"static"}
    bad, soft = [], []
    pat_url = re.compile(r"""url_for\(\s*['"]([\w.]+)['"]""")
    pat_ep = re.compile(r"""request\.endpoint\s*(?:==|!=)\s*['"](\w+)['"]""")
    for f in files:
        if f.parent == ROOT / "tests":
            continue  # the test scripts quote url_for('x') in their own docs
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in pat_url.finditer(text):
            if m.group(1) not in known:
                bad.append(f"{rel(f)}: url_for('{m.group(1)}') - no such endpoint")
        for m in pat_ep.finditer(text):
            if m.group(1) not in known:
                bad.append(
                    f"{rel(f)}: request.endpoint == '{m.group(1)}' - no such endpoint"
                )
    tdir = ROOT / "templates"
    if tdir.is_dir():
        for t in sorted(tdir.glob("*.html")):
            for m in pat_url.finditer(t.read_text(encoding="utf-8", errors="replace")):
                if m.group(1) not in known:
                    bad.append(
                        f"templates/{t.name}: url_for('{m.group(1)}') - no such endpoint"
                    )
    for f, tree in trees.items():
        if isinstance(tree, SyntaxError) or f.name not in ("middleware.py", "core.py"):
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Assign)
                and node.targets
                and isinstance(node.targets[0], ast.Name)
            ):
                continue
            name = node.targets[0].id
            if not re.search(r"ENDPOINT|EXEMPT|PUBLIC", name):
                continue
            val = node.value
            if isinstance(val, ast.Call) and val.args:
                val = val.args[0]
            if not isinstance(val, (ast.Set, ast.List, ast.Tuple)):
                continue
            for e in val.elts:
                if (
                    isinstance(e, ast.Constant)
                    and isinstance(e.value, str)
                    and not e.value.startswith("/")
                ):
                    if e.value not in known:
                        (bad if "ENDPOINT" in name else soft).append(
                            f"{rel(f)}: {name} lists '{e.value}' - no such endpoint (a renamed route silently changes auth rules)"
                        )
    report("FAIL" if bad else "PASS", "4 url_for / endpoint names exist", bad)
    if soft:
        report("WARN", "4b EXEMPT/PUBLIC sets name unknown endpoints", soft)


# --------------------------------------------------------------------------------------
def check_hooks(trees):
    bad = []
    for f, t in trees.items():
        if isinstance(t, SyntaxError) or f.parent in (ROOT / "tools", ROOT / "tests"):
            continue
        for node in ast.walk(t):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                target = d.func if isinstance(d, ast.Call) else d
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "app"
                    and target.attr in HOOK_NAMES
                ):
                    if target.attr not in HOOK_ALLOWED.get(rel(f), set()):
                        bad.append(
                            f"{rel(f)}: @app.{target.attr} on {node.name}() - hooks belong in middleware.py"
                        )
    report("FAIL" if bad else "PASS", "5 hooks only in middleware.py", bad)


def module_of(path):
    r = rel(path)
    return r[:-3].replace("/", ".")


def project_modules(files):
    return {module_of(f) for f in files}


def is_main_guard(node):
    """True for `if __name__ == "__main__":` (its body only runs when the file is executed directly)."""
    t = getattr(node, "test", None)
    return (
        isinstance(node, ast.If)
        and isinstance(t, ast.Compare)
        and isinstance(t.left, ast.Name)
        and t.left.id == "__name__"
        and len(t.comparators) == 1
        and isinstance(t.comparators[0], ast.Constant)
        and t.comparators[0].value == "__main__"
    )


def imports_of(tree, module_level_only):
    """Yield (module_name, is_star, lineno) for each import (optionally module level only).
    module_level_only skips function/class bodies and the `if __name__ == "__main__":` block
    (those imports do not run when the module is imported, so they cannot form an import cycle).
    """
    stack = (
        list(ast.iter_child_nodes(tree)) if module_level_only else list(ast.walk(tree))
    )
    while stack:
        n = stack.pop(0)
        if module_level_only and (
            isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            )
            or is_main_guard(n)
        ):
            continue
        if isinstance(n, ast.Import):
            for a in n.names:
                yield a.name, False, n.lineno
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            for a in n.names:
                yield n.module, a.name == "*", n.lineno
                if n.module == "routes":
                    yield f"routes.{a.name}", False, n.lineno
        if module_level_only and not isinstance(n, (ast.Import, ast.ImportFrom)):
            stack = list(ast.iter_child_nodes(n)) + stack


def check_imports(files, trees):
    mods = project_modules(files)
    app_importers, stars, route_bad = [], [], []
    graph = {}
    for f, t in trees.items():
        if isinstance(t, SyntaxError):
            continue
        me = module_of(f)
        for mod, star, line in imports_of(t, module_level_only=False):
            if star:
                stars.append(f"{rel(f)}:{line}: from {mod} import *")
            if mod == "app" and f.name not in LAUNCHERS and f.parent != ROOT / "tests":
                app_importers.append(
                    f"{rel(f)}:{line}: imports app (use `from core import ...`)"
                )
        for mod, star, line in imports_of(t, module_level_only=True):
            if mod in mods and mod != me:
                graph.setdefault(me, set()).add(mod)
            if (
                me.startswith("routes.")
                and mod.startswith("routes.")
                and mod != me
                and mod in mods
            ):
                if mod not in ALLOWED_ROUTE_IMPORTS.get(me, set()):
                    route_bad.append(
                        f"{rel(f)}:{line}: imports {mod} (route modules must not import each other)"
                    )
    report("FAIL" if stars else "PASS", "6a no `from x import *`", stars)
    report(
        "FAIL" if app_importers else "PASS",
        "6b only the launchers import app",
        app_importers,
    )
    # cycles (iterative Tarjan) that include app/core/middleware/routes
    index, low, onstack, stack, sccs, counter = {}, {}, set(), [], [], [0]

    def strong(v):
        work = [(v, iter(sorted(graph.get(v, ()))))]
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        onstack.add(v)
        while work:
            node, it = work[-1]
            adv = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    onstack.add(w)
                    work.append((w, iter(sorted(graph.get(w, ())))))
                    adv = True
                    break
                elif w in onstack:
                    low[node] = min(low[node], index[w])
            if adv:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1:
                    sccs.append(sorted(comp))

    for v in sorted(set(graph) | {w for s in graph.values() for w in s}):
        if v not in index:
            strong(v)
    cyc = [
        c
        for c in sccs
        if any(m.startswith("routes.") or m + ".py" in CYCLE_SCOPE_FILES for m in c)
    ]
    other = [c for c in sccs if c not in cyc]
    report(
        "FAIL" if cyc else "PASS",
        "6c no module-level import cycle through app / core / middleware / routes",
        [" <-> ".join(c) for c in cyc],
    )
    if other:
        report(
            "WARN",
            "6d module-level import cycles elsewhere (existing design, only report)",
            [" <-> ".join(c) for c in other],
        )
    report(
        "FAIL" if route_bad else "PASS",
        "7 routes/ modules do not import each other (except the documented pairs)",
        route_bad,
    )


def check_app_registers_routes(trees):
    app_tree = trees.get(ROOT / "app.py")
    rdir = ROOT / "routes"
    if app_tree is None or isinstance(app_tree, SyntaxError) or not rdir.is_dir():
        report(
            "SKIP",
            "8 app.py imports every routes/*.py",
            ["app.py or routes/ not found"],
        )
        return
    imported = {m for m, _, _ in imports_of(app_tree, module_level_only=True)}
    missing = [
        f"routes/{p.name}: not imported by app.py - its routes would never register"
        for p in sorted(rdir.glob("*.py"))
        if p.name != "__init__.py" and f"routes.{p.stem}" not in imported
    ]
    report("FAIL" if missing else "PASS", "8 app.py imports every routes/*.py", missing)


def check_tools(files, trees):
    tdir = ROOT / "tools"
    if not tdir.is_dir():
        report("SKIP", "9 tools/ path preamble", ["no tools/ folder"])
        return
    root_mods = {p.stem for p in ROOT.glob("*.py")}
    bad, n = [], 0
    for p in sorted(tdir.glob("*.py")):
        t = trees.get(p)
        if t is None or isinstance(t, SyntaxError):
            continue
        n += 1
        uses = sorted(
            {m.split(".")[0] for m, _, _ in imports_of(t, module_level_only=False)}
            & root_mods
        )
        text = p.read_text(encoding="utf-8", errors="replace")
        if uses and "sys.path.insert(0, _ROOT)" not in text:
            bad.append(
                f"tools/{p.name}: imports root module(s) {uses} but never does sys.path.insert(0, _ROOT)"
            )
        elif uses:
            first_use = min(
                (
                    ln
                    for m, _, ln in imports_of(t, module_level_only=False)
                    if m.split(".")[0] in uses
                ),
                default=0,
            )
            pre = next(
                (
                    i + 1
                    for i, l in enumerate(text.splitlines())
                    if "sys.path.insert(0, _ROOT)" in l
                ),
                10**9,
            )
            if pre > first_use:
                bad.append(
                    f"tools/{p.name}: sys.path.insert (line {pre}) comes AFTER its first project import (line {first_use})"
                )
    report(
        "FAIL" if bad else "PASS",
        f"9 tools/ scripts can import the root modules ({n} tools)",
        bad,
    )


def check_manage_sh():
    sh = ROOT / "manage.sh"
    if not sh.is_file():
        report("SKIP", "10 manage.sh", ["manage.sh not found"])
        return
    text = sh.read_text(encoding="utf-8", errors="replace")
    named = set(re.findall(r'run_utility\s+"([\w/]+\.py)"', text))
    named |= set(re.findall(r"SCRIPT_DIR\}?/((?:tools/)?\w+\.py)", text))
    missing = [
        f"manage.sh launches {n} but {n} does not exist"
        for n in sorted(named)
        if not (ROOT / n).is_file()
    ]
    report(
        "FAIL" if missing else "PASS",
        f"10a manage.sh launches only existing files ({len(named)} scripts)",
        missing,
    )
    bash = shutil.which("bash")
    if not bash:
        report("SKIP", "10b bash -n manage.sh", ["bash not found"])
        return
    proc = subprocess.run(
        [bash, "-n", "manage.sh"], capture_output=True, text=True, cwd=str(ROOT)
    )
    report(
        "PASS" if proc.returncode == 0 else "FAIL",
        "10b bash -n manage.sh",
        (proc.stderr or "").splitlines()[:5],
    )


def snapshot_lines(routes):
    return sorted(
        {
            f"{','.join(methods)} {rule} -> {endpoint}"
            for _f, _fn, endpoint, rule, methods, _ln in routes
        }
    )


def check_snapshot(routes, save):
    lines = snapshot_lines(routes)
    if save:
        SNAPSHOT.write_text(
            json.dumps({"routes": lines}, indent=1) + "\n", encoding="utf-8"
        )
        report(
            "PASS",
            f"11 route snapshot saved: {len(lines)} routes -> tests/{SNAPSHOT.name}",
        )
        return
    if not SNAPSHOT.is_file():
        report(
            "SKIP",
            "11 route snapshot",
            [
                f"no tests/{SNAPSHOT.name} yet: run `python tests/smoke.py --save` once after a green run"
            ],
        )
        return
    old = set(json.loads(SNAPSHOT.read_text(encoding="utf-8")).get("routes", []))
    new = set(lines)
    lost, added = sorted(old - new), sorted(new - old)
    report(
        "FAIL" if lost else "PASS",
        f"11 no route lost since the snapshot ({len(old)} saved, {len(new)} now)",
        [f"LOST   {x}" for x in lost],
    )
    if added:
        report(
            "WARN",
            f"11b {len(added)} route(s) not in the snapshot (intended? then run --save)",
            [f"NEW    {x}" for x in added[:15]],
        )


# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--save",
        action="store_true",
        help="write the route snapshot (tests/smoke_routes.json)",
    )
    ap.add_argument(
        "-v", "--verbose", action="store_true", help="print the route table"
    )
    ap.add_argument(
        "--files", action="store_true", help="list every .py file that was scanned"
    )
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    files = py_files()
    trees = {f: parse(f) for f in files}
    groups = {}
    for f in files:
        top = (
            f.relative_to(ROOT).parts[0]
            if len(f.relative_to(ROOT).parts) > 1
            else "(root)"
        )
        groups.setdefault(top, []).append(rel(f))
    check_syntax(files, trees)
    check_pyflakes(files)
    routes = collect_routes(trees)
    endpoints = check_routes(routes, args.verbose)
    check_endpoint_names(files, trees, endpoints)
    check_hooks(trees)
    check_imports(files, trees)
    check_app_registers_routes(trees)
    check_tools(files, trees)
    check_manage_sh()
    check_snapshot(routes, args.save)

    counts = {}
    print(f"smoke test - project root: {ROOT}")
    print(
        f"scanned {len(files)} .py files: "
        + ", ".join(f"{k} {len(v)}" for k, v in groups.items())
    )
    if args.files:
        for k, v in groups.items():
            print(f"  {k}: " + ", ".join(Path(x).name for x in v))
    print()
    for status, check, details in results:
        counts[status] = counts.get(status, 0) + 1
        print(f"[{status}] {check}")
        for d in details:
            print(f"       {d}")
    print("\nSummary: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    if counts.get("FAIL"):
        print("FAILED - fix the FAIL lines above.")
        return 1
    print(
        "OK" + (" (some checks skipped, see SKIP lines)" if counts.get("SKIP") else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
