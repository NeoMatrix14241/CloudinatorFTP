#!/usr/bin/env python3
"""
Shared helpers for the app.py-split phase tests (tests/refactor/).

Everything here is STATIC analysis (the standard-library `ast` module), so the
tests never import app.py: importing it starts the file monitor, the search
crawler and the cleanup threads against the real storage folder. Two optional
extras:
  * `pyflakes` (pip install pyflakes) - catches names that a move left behind.
    Without it that one check is reported as SKIP.
  * a runtime comparison of Quart's real url_map / hook order (`--runtime`),
    which must be run in a SCRATCH COPY of the project (see runtime_collect()).

Each phase script (test_phaseNN_*.py) calls run_phase(N, extra=[...]):
  1. INVARIANTS - must hold at every phase boundary, before and after a move:
     routes, hooks, decorators, endpoint-name references, import rules.
  2. PHASE DONE  - the phase's routes/symbols now live in its target modules
     and are gone from app.py. Skipped with --pre (use --pre BEFORE starting a
     phase to prove the tree is still at the previous phase's baseline).
  3. EXTRAS      - checks specific to that phase.

Exit code 0 = all passed, 1 = at least one failure.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import pathlib
import sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # <project>/tests/refactor -> <project>
BASELINE_FILE = HERE / "baseline_routes.json"
RUNTIME_BASELINE_FILE = HERE / "baseline_runtime.json"

sys.path.insert(0, str(HERE))
from phases import PHASES, COMPAT_EXPORTS, SIDE_EFFECT_CALLS, CORE_EXPORTS  # noqa: E402

NEW_DIRS = ("routes", "services")
NEW_TOP = ("core.py", "middleware.py")
HOOK_ATTRS = {
    "before_request",
    "after_request",
    "before_serving",
    "after_serving",
    "errorhandler",
    "template_filter",
    "context_processor",
    "teardown_request",
    "teardown_appcontext",
    "while_serving",
    "template_global",
    "url_value_preprocessor",
    "url_defaults",
}
PYFLAKES_KEEP = {
    "UndefinedName",
    "UndefinedLocal",
    "UndefinedExport",
    "ImportStarUsed",
    "ImportStarUsage",
    "RedefinedWhileUnused",
    "SyntaxError",
}


# --------------------------------------------------------------------------
# tiny test recorder
# --------------------------------------------------------------------------
class T:
    def __init__(self, title: str):
        self.title = title
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.notes: list[str] = []
        self.failures: list[tuple] = []

    def check(self, name: str, ok: bool, detail: str = ""):
        if ok:
            self.passed += 1
            print(f"  [PASS] {name}")
        else:
            self.failed += 1
            self.failures.append((name, str(detail)))
            print(f"  [FAIL] {name}")
            for line in str(detail).splitlines()[:14]:
                print(f"         {line}")
        return ok

    def skip(self, name: str, why: str):
        self.skipped += 1
        print(f"  [SKIP] {name} - {why}")

    def info(self, text: str):
        print(f"  [info] {text}")

    def section(self, text: str):
        print(f"\n== {text}")

    def finish(self) -> int:
        print(
            f"\n{self.title}: {self.passed} passed, {self.failed} failed, "
            f"{self.skipped} skipped"
        )
        return 1 if self.failed else 0


# --------------------------------------------------------------------------
# file discovery + parsing
# --------------------------------------------------------------------------
def registration_files() -> list[pathlib.Path]:
    """The only files that may register routes/hooks: app.py, core.py,
    middleware.py, routes/**, services/**. (Other project modules are never
    scanned, so unrelated decorators cannot create false alarms.)"""
    files = [ROOT / "app.py"]
    files += [ROOT / n for n in NEW_TOP if (ROOT / n).is_file()]
    for d in NEW_DIRS:
        if (ROOT / d).is_dir():
            files += sorted((ROOT / d).rglob("*.py"))
    return [f for f in files if f.is_file()]


def rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


_cache: dict = {}


def parse(path: pathlib.Path):
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _cache:
        src = path.read_text(encoding="utf-8")
        _cache[key] = (ast.parse(src, filename=str(path)), src)
    return _cache[key]


def sha_normalized(path: pathlib.Path) -> str:
    """sha256 of the file with CRLF/LF differences removed (git autocrlf safe)."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def module_name(path: pathlib.Path) -> str:
    r = path.relative_to(ROOT).with_suffix("")
    parts = list(r.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def is_new_module(path: pathlib.Path) -> bool:
    r = rel(path)
    return r in NEW_TOP or r.split("/")[0] in NEW_DIRS


# --------------------------------------------------------------------------
# registrations: routes and hooks
# --------------------------------------------------------------------------
def _lit(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def scan_file(path: pathlib.Path):
    tree, _src = parse(path)
    routes, hooks = [], []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        order, rules, others = [], [], []
        for d in node.decorator_list:
            call = d if isinstance(d, ast.Call) else None
            target = d.func if call else d
            attr = target.attr if isinstance(target, ast.Attribute) else None
            if attr == "route" and call is not None:
                rule = _lit(call.args[0]) if call.args else None
                kw = {k.arg: k.value for k in call.keywords if k.arg}
                methods = _lit(kw["methods"]) if "methods" in kw else ["GET"]
                defaults = _lit(kw["defaults"]) if "defaults" in kw else None
                endpoint = _lit(kw["endpoint"]) if "endpoint" in kw else None
                rules.append(
                    {
                        "rule": rule,
                        "methods": sorted(m.upper() for m in (methods or ["GET"])),
                        "defaults": defaults,
                        "endpoint": endpoint,
                    }
                )
                order.append("@route")
            elif attr in HOOK_ATTRS:
                arg = _lit(call.args[0]) if call is not None and call.args else None
                hooks.append(
                    {
                        "kind": attr,
                        "arg": arg,
                        "func": node.name,
                        "file": rel(path),
                        "line": node.lineno,
                    }
                )
                order.append("@" + attr)
            else:
                text = ast.unparse(d)
                others.append(text)
                order.append(text)
        for r in rules:
            routes.append(
                {
                    "endpoint": r["endpoint"] or node.name,
                    "rule": r["rule"],
                    "methods": r["methods"],
                    "defaults": r["defaults"],
                    "func": node.name,
                    "file": rel(path),
                    "line": node.lineno,
                    "order": order,
                    "decorators": others,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                }
            )
        # attach this function's hook decorator ordering info
        for h in hooks:
            if h["func"] == node.name and h["file"] == rel(path) and "order" not in h:
                h["order"] = order
                h["decorators"] = others
    return routes, hooks


def scan_all():
    routes, hooks = [], []
    for f in registration_files():
        r, h = scan_file(f)
        routes += r
        hooks += h
    return routes, hooks


def route_table(routes):
    """endpoint -> {rules:[{rule,methods,defaults}], order, decorators, async}"""
    table: dict = {}
    for r in routes:
        e = table.setdefault(
            r["endpoint"],
            {
                "rules": [],
                "order": r["order"],
                "decorators": r["decorators"],
                "async": r["async"],
                "files": set(),
                "funcs": set(),
            },
        )
        e["rules"].append(
            {"rule": r["rule"], "methods": r["methods"], "defaults": r["defaults"]}
        )
        e["files"].add(r["file"])
        e["funcs"].add(r["func"])
    for e in table.values():
        e["rules"].sort(key=lambda x: (str(x["rule"]), x["methods"]))
    return table


def hook_table(hooks):
    out = defaultdict(list)
    for h in sorted(hooks, key=lambda h: (h["file"], h["line"])):
        out[h["kind"]].append(h)
    return out


# --------------------------------------------------------------------------
# symbols
# --------------------------------------------------------------------------
def _target_names(t):
    return [x.id for x in ast.walk(t) if isinstance(x, ast.Name)]


def top_level_symbols(tree) -> dict:
    out: dict = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out[node.name] = ("class", node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ("def", node.lineno)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in _target_names(t):
                    out[n] = ("var", node.lineno)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = ("var", node.lineno)
    return out


def symbol_index() -> dict:
    idx = defaultdict(list)
    for f in registration_files():
        tree, _ = parse(f)
        for name, (kind, line) in top_level_symbols(tree).items():
            idx[name].append((rel(f), kind, line))
    return idx


def binds_name(tree, name: str) -> bool:
    """True if the module binds `name` at top level (def, class, assignment or import)."""
    if name in top_level_symbols(tree):
        return True
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                if (a.asname or a.name).split(".")[0] == name:
                    return True
    return False


# --------------------------------------------------------------------------
# endpoint-name references (url_for / request.endpoint comparisons)
# --------------------------------------------------------------------------
def endpoint_refs() -> dict:
    url_for_names, req_names = set(), set()
    for f in registration_files():
        tree, _ = parse(f)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if (isinstance(fn, ast.Name) and fn.id == "url_for") or (
                    isinstance(fn, ast.Attribute) and fn.attr == "url_for"
                ):
                    if (
                        node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        url_for_names.add(node.args[0].value)
            elif isinstance(node, ast.Compare):
                left = node.left
                if (
                    isinstance(left, ast.Attribute)
                    and left.attr == "endpoint"
                    and isinstance(left.value, ast.Name)
                    and left.value.id == "request"
                ):
                    for comp in node.comparators:
                        if isinstance(comp, ast.Constant) and isinstance(
                            comp.value, str
                        ):
                            req_names.add(comp.value)
                        elif isinstance(comp, (ast.List, ast.Tuple, ast.Set)):
                            for el in comp.elts:
                                if isinstance(el, ast.Constant) and isinstance(
                                    el.value, str
                                ):
                                    req_names.add(el.value)
    return {"url_for": sorted(url_for_names), "request_endpoint": sorted(req_names)}


# --------------------------------------------------------------------------
# import graph (module-level imports only) and cycles
# --------------------------------------------------------------------------
def _toplevel_imports(tree):
    """Yield import nodes that run at import time (not inside def/class bodies)."""
    stack = list(tree.body)
    while stack:
        n = stack.pop(0)
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            yield n
        elif isinstance(n, (ast.If, ast.Try, ast.With)):
            for fld in ("body", "orelse", "finalbody", "handlers"):
                for sub in getattr(n, fld, []) or []:
                    if isinstance(sub, ast.ExceptHandler):
                        stack.extend(sub.body)
                    else:
                        stack.append(sub)


def local_module_names() -> set:
    return {module_name(f) for f in registration_files()}


def imports_of(path: pathlib.Path, local: set, include_nested=False) -> list:
    """Local modules imported by `path`, in source order (module-level imports
    only unless include_nested=True)."""
    tree, _ = parse(path)
    nodes = (
        [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        if include_nested
        else list(_toplevel_imports(tree))
    )
    nodes.sort(key=lambda n: n.lineno)
    return imports_of_nodes(path, nodes, local)


def import_cycles(local: set) -> list:
    graph = {}
    for f in registration_files():
        graph[module_name(f)] = set(imports_of(f, local)) - {module_name(f)}
    index, low, on, stack, sccs, counter = {}, {}, set(), [], [], [0]

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, ()):
            if w not in graph:
                continue
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                sccs.append(sorted(comp))

    for v in list(graph):
        if v not in index:
            strong(v)
    return sccs


# --------------------------------------------------------------------------
# startup side-effect order
# --------------------------------------------------------------------------
def _calls_in_stmt(stmt):
    """Names of SIDE_EFFECT_CALLS invoked while executing one top-level statement
    (function/class bodies are not executed at import time, so not entered)."""
    found = []
    stack = [stmt]
    while stack:
        n = stack.pop(0)
        if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if isinstance(n, ast.Call):
            name = ast.unparse(n.func)
            if name in SIDE_EFFECT_CALLS:
                found.append(name)
        stack.extend(ast.iter_child_nodes(n))
    return found


def effective_sequence(path: pathlib.Path, local: set, seen=None) -> list:
    """Order in which SIDE_EFFECT_CALLS run when `path` is imported: its own
    statements in order, with every imported project module's own sequence
    spliced in at the point of its (first) import - the way Python executes it."""
    seen = set() if seen is None else seen
    key = module_name(path)
    if key in seen:
        return []
    seen.add(key)
    tree, _ = parse(path)
    by_name = {module_name(f): f for f in registration_files()}
    seq = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for m in imports_of_nodes(path, [stmt], local):
                if m in by_name:
                    seq += effective_sequence(by_name[m], local, seen)
        else:
            seq += _calls_in_stmt(stmt)
    return seq


def imports_of_nodes(path, nodes, local):
    out = []
    for n in nodes:
        if isinstance(n, ast.Import):
            for a in n.names:
                m = a.name
                while m and m not in local and "." in m:
                    m = m.rsplit(".", 1)[0]
                if m in local:
                    out.append(m)
        else:
            mod = n.module or ""
            if n.level:
                base = module_name(path).split(".")
                base = base[:-1] if path.name != "__init__.py" else base
                mod = ".".join(base + ([n.module] if n.module else []))
            if mod in local:
                out.append(mod)
            for a in n.names:
                if f"{mod}.{a.name}" in local:
                    out.append(f"{mod}.{a.name}")
    return out


# --------------------------------------------------------------------------
# pyflakes (optional)
# --------------------------------------------------------------------------
def run_pyflakes():
    try:
        from pyflakes import api
    except ImportError:
        return None

    class Collect:
        def __init__(self):
            self.msgs = []

        def unexpectedError(self, filename, msg):
            self.msgs.append(("Error", str(msg), rel(pathlib.Path(filename)), 0))

        def syntaxError(self, filename, msg, lineno, offset, text):
            self.msgs.append(
                ("SyntaxError", str(msg), rel(pathlib.Path(filename)), lineno)
            )

        def flake(self, message):
            cls = type(message).__name__
            args = getattr(message, "message_args", ()) or ()
            self.msgs.append(
                (
                    cls,
                    str(args[0]) if args else "",
                    rel(pathlib.Path(message.filename)),
                    message.lineno,
                )
            )

    rep = Collect()
    for f in registration_files():
        _tree, src = parse(f)
        api.check(src, str(f), rep)
    return [m for m in rep.msgs if m[0] in PYFLAKES_KEEP]


# --------------------------------------------------------------------------
# baseline
# --------------------------------------------------------------------------
def load_baseline():
    if not BASELINE_FILE.is_file():
        return None
    return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))


def build_baseline_from_tree() -> dict:
    routes, hooks = scan_all()
    table = route_table(routes)
    flakes = run_pyflakes()
    refs = endpoint_refs()
    known_eps = set(table) | {"static"}
    app_tree, _ = parse(ROOT / "app.py")
    local = local_module_names()
    return {
        "meta": {
            "app_py_sha256_normalized": sha_normalized(ROOT / "app.py"),
            "app_py_lines": len(
                (ROOT / "app.py").read_text(encoding="utf-8").splitlines()
            ),
            "note": "Generated by snapshot_baseline.py from the PRISTINE app.py. "
            "Do not regenerate after a phase has started.",
        },
        "routes": {
            ep: {
                "rules": e["rules"],
                "order": e["order"],
                "decorators": e["decorators"],
                "async": e["async"],
                "line": min(r["line"] for r in routes if r["endpoint"] == ep),
            }
            for ep, e in sorted(table.items())
        },
        "hooks": {
            kind: [{"func": h["func"], "arg": h["arg"], "line": h["line"]} for h in lst]
            for kind, lst in sorted(hook_table(hooks).items())
        },
        "endpoint_refs": refs,
        "endpoint_refs_unresolved_known": sorted(
            (set(refs["url_for"]) | set(refs["request_endpoint"])) - known_eps
        ),
        "side_effect_order": effective_sequence(ROOT / "app.py", local),
        "pyflakes_known": sorted({(m[0], m[1]) for m in (flakes or [])}),
        "top_level_symbols": sorted(top_level_symbols(app_tree)),
    }


# --------------------------------------------------------------------------
# INVARIANTS (every phase, before and after a move)
# --------------------------------------------------------------------------
def invariants(t: T):
    base = load_baseline()
    t.section("Invariants (must hold at every phase boundary)")
    if base is None:
        t.check(
            "baseline_routes.json present",
            False,
            "run: python tests/refactor/snapshot_baseline.py  (on the pristine tree)",
        )
        return None

    files = registration_files()
    # 1. syntax
    bad = []
    for f in files:
        try:
            parse(f)
        except SyntaxError as e:
            bad.append(f"{rel(f)}:{e.lineno}: {e.msg}")
    t.check("every project module parses (no syntax errors)", not bad, "\n".join(bad))
    if bad:
        return base

    routes, hooks = scan_all()
    table = route_table(routes)

    # 2. unique endpoint -> one function
    dup = {
        ep: {"funcs": sorted(e["funcs"]), "files": sorted(e["files"])}
        for ep, e in table.items()
        if len(e["funcs"]) > 1 or len(e["files"]) > 1
    }
    t.check(
        "each endpoint is defined by exactly one function in exactly one file",
        not dup,
        str(dup),
    )

    # 3. route inventory vs baseline
    b = base["routes"]
    missing = sorted(set(b) - set(table))
    extra = sorted(set(table) - set(b))
    t.check(
        f"no route endpoint lost ({len(b)} in baseline)",
        not missing,
        "missing: " + ", ".join(missing),
    )
    t.check("no unexpected new route endpoint", not extra, "extra: " + ", ".join(extra))
    changed = []
    for ep in sorted(set(b) & set(table)):
        if b[ep]["rules"] != table[ep]["rules"]:
            changed.append(
                f"{ep}: rules/methods/defaults differ\n   baseline={b[ep]['rules']}\n   now     ={table[ep]['rules']}"
            )
    t.check(
        "every route keeps its URL rule(s), methods and defaults",
        not changed,
        "\n".join(changed),
    )
    dec = []
    for ep in sorted(set(b) & set(table)):
        if b[ep]["order"] != table[ep]["order"]:
            dec.append(
                f"{ep}: decorator order/content differs\n   baseline={b[ep]['order']}\n   now     ={table[ep]['order']}"
            )
        if b[ep]["async"] != table[ep]["async"]:
            dec.append(f"{ep}: async/sync changed")
    t.check(
        "every route keeps its decorators (login_required, csrf.exempt, ...) in the same order",
        not dec,
        "\n".join(dec),
    )

    # 4. hooks
    ht = hook_table(hooks)
    hb = base["hooks"]
    for kind in sorted(set(hb) | set(ht)):
        want = [(h["func"], h["arg"]) for h in hb.get(kind, [])]
        got = [(h["func"], h["arg"]) for h in ht.get(kind, [])]
        files_used = sorted({h["file"] for h in ht.get(kind, [])})
        t.check(
            f"hook '{kind}': same functions ({len(want)})",
            sorted(map(str, want)) == sorted(map(str, got)),
            f"baseline={want}\nnow     ={got}",
        )
        if kind in ("before_request", "after_request"):
            t.check(
                f"hook '{kind}': all in ONE file ({', '.join(files_used) or '-'}) and in baseline order",
                len(files_used) <= 1 and want == got,
                f"files={files_used}\nbaseline order={[w[0] for w in want]}\nnow order     ={[g[0] for g in got]}",
            )

    # 5. endpoint-name references
    refs = endpoint_refs()
    known = (
        set(table) | {"static"} | set(base.get("endpoint_refs_unresolved_known", []))
    )
    unresolved = sorted((set(refs["url_for"]) | set(refs["request_endpoint"])) - known)
    t.check(
        "every url_for('x') / request.endpoint == 'x' name is a real endpoint",
        not unresolved,
        "unknown endpoint names: " + ", ".join(unresolved),
    )

    # 6. compat exports on app.py
    app_tree, _ = parse(ROOT / "app.py")
    lost = [n for n in COMPAT_EXPORTS if not binds_name(app_tree, n)]
    t.check(
        f"app.py still exposes {COMPAT_EXPORTS} (prod_server/dev_server/sftp/ftp/smb import them)",
        not lost,
        "missing from app.py: " + ", ".join(lost),
    )

    # 7. import rules for the new modules
    local = local_module_names()
    new_files = [f for f in files if is_new_module(f)]
    offenders = []
    stars = []
    for f in new_files:
        tree, _ = parse(f)
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                if (n.module or "") == "app" and not n.level:
                    offenders.append(f"{rel(f)}:{n.lineno}: from app import ...")
                if any(a.name == "*" for a in n.names):
                    stars.append(f"{rel(f)}:{n.lineno}")
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name == "app":
                        offenders.append(f"{rel(f)}:{n.lineno}: import app")
    t.check(
        "no new module imports app.py (they import `core` instead)",
        not offenders,
        "\n".join(offenders),
    )
    t.check("no `from x import *` in new modules", not stars, "\n".join(stars))
    cyc = [
        c
        for c in import_cycles(local)
        if any(
            m.split(".")[0] in ("core", "middleware", "routes", "services") for m in c
        )
    ]
    t.check("no module-level import cycle involving a new module", not cyc, str(cyc))

    # 8. startup side-effect order
    seq = effective_sequence(ROOT / "app.py", local)
    t.check(
        "startup side effects run in the baseline order (ensure_dirs ... initialize_cleanup)",
        seq == base["side_effect_order"],
        f"baseline={base['side_effect_order']}\nnow     ={seq}",
    )

    # 9. pyflakes
    flakes = run_pyflakes()
    if flakes is None:
        t.skip(
            "no undefined names / leftovers (pyflakes)",
            "pip install pyflakes to enable",
        )
    else:
        known_f = {tuple(x) for x in base.get("pyflakes_known", [])}
        new = sorted(
            {(m[0], m[1], m[2], m[3]) for m in flakes if (m[0], m[1]) not in known_f}
        )
        t.check(
            "pyflakes: no new undefined names / star imports / redefinitions",
            not new,
            "\n".join(f"{c} '{n}' at {f}:{l}" for c, n, f, l in new),
        )
    return base


# --------------------------------------------------------------------------
# PHASE DONE
# --------------------------------------------------------------------------
def phase_done(t: T, n: int):
    ph = PHASES[n]
    t.section(f"Phase {n} done: {ph['title']}")
    mods = ph["modules"]
    if not mods and not ph["routes"] and not ph["symbols"]:
        t.info("this phase moves no code")
        return
    missing_files = [m for m in mods if not (ROOT / m).is_file()]
    t.check(
        f"target module(s) exist: {', '.join(mods)}",
        not missing_files,
        "missing: " + ", ".join(missing_files),
    )
    routes, _ = scan_all()
    table = route_table(routes)
    wrong = []
    for ep in ph["routes"]:
        e = table.get(ep)
        if e is None or not e["files"] <= set(mods):
            wrong.append(
                f"{ep}: registered in {sorted(e['files']) if e else 'NOWHERE'}"
            )
    t.check(
        f"all {len(ph['routes'])} routes of this phase are registered in the target module(s)",
        not wrong,
        "\n".join(wrong),
    )
    idx = symbol_index()
    keep = set(ph.get("keep_in_app", []))
    not_moved, dup = [], []
    for s in ph["symbols"]:
        locs = idx.get(s, [])
        in_mods = [l for l in locs if l[0] in mods]
        in_app = [l for l in locs if l[0] == "app.py"]
        others = [l for l in locs if l[0] not in mods and l[0] != "app.py"]
        if not in_mods:
            not_moved.append(f"{s}: not defined in {mods}")
        elif in_app and s not in keep:
            not_moved.append(f"{s}: still defined in app.py:{in_app[0][2]}")
        if len(locs) > 1 and s not in keep:
            dup.append(f"{s}: defined {len(locs)}x -> {[l[0] for l in locs]}")
    t.check(
        f"all {len(ph['symbols'])} functions/classes/globals of this phase moved out of app.py",
        not not_moved,
        "\n".join(not_moved),
    )
    t.check("none of them is defined twice", not dup, "\n".join(dup))
    # app.py must import every module of the phase (so the routes still register)
    local = local_module_names()
    app_imports = set(imports_of(ROOT / "app.py", local))
    route_mods = [module_name(ROOT / m) for m in mods if m.endswith(".py")]
    not_imported = [m for m in route_mods if m not in app_imports and m != "core"]
    t.check(
        "app.py imports each new module (otherwise its routes never register)",
        not not_imported,
        "app.py does not import: " + ", ".join(not_imported),
    )


# --------------------------------------------------------------------------
# runtime comparison (optional, needs a scratch copy)
# --------------------------------------------------------------------------
def runtime_collect() -> dict:
    """Import app.py for real and describe Quart's url_map + hook order.
    DANGER: importing app.py starts the file monitor, the search crawler and the
    cleanup threads. Only run in a SCRATCH COPY of the project with
    CLOUDINATOR_REFACTOR_SCRATCH=1 (storage/db/cache paths pointing to the copy)."""
    if os.environ.get("CLOUDINATOR_REFACTOR_SCRATCH") != "1":
        raise SystemExit(
            "Refusing to import app.py: set CLOUDINATOR_REFACTOR_SCRATCH=1 and run in a scratch copy."
        )
    sys.path.insert(0, str(ROOT))
    import importlib

    mod = importlib.import_module("app")
    a = mod.app

    def names(funcs):
        return [getattr(f, "__name__", repr(f)) for f in funcs]

    rules = sorted(
        (
            r.rule,
            r.endpoint,
            sorted(m for m in (r.methods or ()) if m not in ("HEAD", "OPTIONS")),
        )
        for r in a.url_map.iter_rules()
    )
    return {
        "rules": [list(r) for r in rules],
        "before_request": names(a.before_request_funcs.get(None, [])),
        "after_request": names(a.after_request_funcs.get(None, [])),
        "before_serving": names(getattr(a, "before_serving_funcs", [])),
        "template_filters": (
            sorted(a.jinja_env.filters.keys()) if hasattr(a, "jinja_env") else []
        ),
    }


def runtime_check(t: T):
    t.section("Runtime comparison (--runtime)")
    if not RUNTIME_BASELINE_FILE.is_file():
        t.skip(
            "runtime url_map / hook order",
            "no baseline_runtime.json - run snapshot_baseline.py --runtime on the pristine tree in a scratch copy first",
        )
        return
    want = json.loads(RUNTIME_BASELINE_FILE.read_text(encoding="utf-8"))
    got = runtime_collect()
    # hook names may be wrapped by Quart; compare only when both have names
    t.check(
        "Quart url_map identical to the pristine tree (rule, endpoint, methods)",
        want["rules"] == got["rules"],
        "\n".join(
            [
                f"only before: {[r for r in want['rules'] if r not in got['rules']][:6]}",
                f"only now   : {[r for r in got['rules'] if r not in want['rules']][:6]}",
            ]
        ),
    )
    for k in ("before_request", "after_request", "before_serving"):
        t.check(
            f"runtime {k} order identical",
            want[k] == got[k],
            f"before={want[k]}\nnow   ={got[k]}",
        )
    t.check(
        "Jinja filters identical",
        want["template_filters"] == got["template_filters"],
        f"before={want['template_filters']}\nnow   ={got['template_filters']}",
    )


# --------------------------------------------------------------------------
# small helpers used by the phase scripts' extra checks
# --------------------------------------------------------------------------
def path_of(relpath: str) -> pathlib.Path:
    return ROOT / relpath


def claude_md_path() -> pathlib.Path:
    """CLAUDE.md in the project root, or in docs/ (whichever exists)."""
    for cand in (ROOT / "CLAUDE.md", ROOT / "docs" / "CLAUDE.md"):
        if cand.is_file():
            return cand
    return ROOT / "CLAUDE.md"


def tree_of(relpath: str):
    p = path_of(relpath)
    return parse(p)[0] if p.is_file() else None


def from_imports(tree) -> dict:
    """name -> module for every top-level `from module import name [as alias]`."""
    out = {}
    for n in _toplevel_imports(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            for a in n.names:
                out[a.asname or a.name] = n.module
    return out


def names_loaded(tree) -> set:
    return {
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }


def count_calls(func_text: str) -> list:
    """[(file, line)] of every call whose callee source text equals func_text."""
    hits = []
    for f in registration_files():
        tree, _ = parse(f)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and ast.unparse(n.func) == func_text:
                hits.append((rel(f), n.lineno))
    return hits


def stmt_index(tree, predicate):
    """Index of the first top-level statement for which predicate(stmt) is true, else None."""
    for i, st in enumerate(tree.body):
        if predicate(st):
            return i
    return None


def stmt_imports_module(st, mod: str) -> bool:
    if isinstance(st, ast.ImportFrom):
        return (st.module or "") == mod or any(
            f"{st.module}.{a.name}" == mod for a in st.names
        )
    if isinstance(st, ast.Import):
        return any(a.name == mod or a.name.startswith(mod + ".") for a in st.names)
    return False


def stmt_calls(st, func_text: str) -> bool:
    return any(
        isinstance(n, ast.Call) and ast.unparse(n.func) == func_text
        for n in ast.walk(st)
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def cross_module_users(names, home_file: str) -> list:
    """For every file other than `home_file` that USES one of `names` (loads it), report
    names that the file does not bind via `from <home module> import ...`."""
    home_mod = module_name(path_of(home_file))
    problems = []
    for f in registration_files():
        if rel(f) == home_file:
            continue
        tree, _ = parse(f)
        used = names_loaded(tree) & set(names)
        if not used:
            continue
        imported = {n for n, m in from_imports(tree).items() if m == home_mod}
        local_defs = set(top_level_symbols(tree))
        for u in sorted(used - imported - local_defs):
            problems.append(f"{rel(f)} uses {u} without `from {home_mod} import {u}`")
    return problems


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------
def run_phase(n: int, extra=None, argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    pre = "--pre" in argv
    runtime = "--runtime" in argv
    ph = PHASES[n]
    mode = "PRE (invariants only)" if pre else "full"
    t = T(f"Phase {n:02d} - {ph['title']} [{mode}]")
    print(f"Project root: {ROOT}")
    if not (ROOT / "app.py").is_file():
        print(
            f"[FAIL] {ROOT / 'app.py'} not found. Copy tests/refactor/ into <project>/tests/refactor/ "
            "(next to app.py) and run from there."
        )
        return 1
    base = invariants(t)
    if base is not None:
        if not pre:
            phase_done(t, n)
            for fn in extra or []:
                t.section(
                    f"Extra: {fn.__doc__.strip().splitlines()[0] if fn.__doc__ else fn.__name__}"
                )
                fn(t)
        else:
            t.info(
                "--pre: phase-done and extra checks skipped (use this BEFORE starting the phase)"
            )
        if runtime:
            runtime_check(t)
    return t.finish()
