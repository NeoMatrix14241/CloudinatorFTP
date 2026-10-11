#!/usr/bin/env python3
"""
tests/check.py - per-module checker with parameters (CLAUDE.md 4.84).

    python tests/check.py                      every .py file (static checks only)
    python tests/check.py helpers              one group: root | helpers | routes | tools | tests
    python tests/check.py net_utils config     named modules (name, dotted name, path or glob)
    python tests/check.py "*_server" "helpers/*"
    python tests/check.py helpers --import     also import each module in a fresh subprocess
    python tests/check.py config --config      also validate server_config.json / storage_config.json
    python tests/check.py --list               list the targets (size, imported by, __main__), run no checks
    python tests/check.py helpers --json       machine-readable result
    options: -q (only problems)  --strict (WARN counts as failure)  --force (allow --import of app/core/...)

Per module (static, read-only, safe while the server runs):
  syntax        parses
  pyflakes      no undefined names / star imports (skipped with a hint if pyflakes is missing)
  imports       every import of a PROJECT module resolves, and every `from x import name` finds
                `name` in x; an import of a module that moved (e.g. `net_utils` after it went to
                helpers/) is reported with the new location
  layering      helpers/* must stay leaf utilities: they may not import app, core, middleware,
                routes.*, tools.* or tests.*
--import  imports the module for real, in a separate process (cwd = project root, 30 s timeout).
          Refused for modules with start-up side effects (app, core, middleware, routes.*, the
          servers, dev/prod launchers, protocol_manager, ...) unless --force; modules you name
          explicitly are your responsibility, groups only import the safe ones (helpers, tools
          are never auto-imported either: a tool may prompt).
--config  server_config.json / storage_config.json must be valid JSON and every key of
          server_config.json should be a name that config.py defines (stale keys = WARN).

Exit code: 0 = no FAIL (and no WARN with --strict), 1 = problems, 2 = bad arguments.
"""

import argparse
import ast
import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
GROUPS = ("root", "helpers", "routes", "tools", "tests")
LEAF_FORBIDDEN = (
    "app",
    "core",
    "middleware",
    "routes",
    "tools",
    "tests",
)  # helpers/ may not import these
DENY_IMPORT = {
    "app",
    "core",
    "middleware",
    "dev_server",
    "prod_server",
    "protocol_manager",
    "webdav_server",
    "ftp_server",
    "sftp_server",
    "smb_server",
    "version_engine",
    "file_monitor",
    "search_index",
    "realtime_shares",
    "realtime_stats",
    "version_history",
    "storage",
}


def rel(p):
    return p.relative_to(ROOT).as_posix()


def module_of(p):
    m = rel(p)[:-3].replace("/", ".")
    return m[: -len(".__init__")] if m.endswith(".__init__") else m


def group_of(p):
    parts = p.relative_to(ROOT).parts
    return "root" if len(parts) == 1 else (parts[0] if parts[0] in GROUPS else parts[0])


def all_files():
    out = []
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
        )
        out += [Path(dirpath) / f for f in sorted(files) if f.endswith(".py")]
    return sorted(out, key=lambda p: (len(p.relative_to(ROOT).parts), p.as_posix()))


FILES = all_files()
TREES = {}


def tree_of(p):
    if p not in TREES:
        try:
            TREES[p] = ast.parse(
                p.read_text(encoding="utf-8", errors="replace"), filename=str(p)
            )
        except SyntaxError as e:
            TREES[p] = e
    return TREES[p]


def select(tokens):
    """Targets from the command line: groups, module names, dotted names, paths, globs."""
    if not tokens:
        return list(FILES), []
    chosen, unknown = [], []
    for tok in tokens:
        t = tok.replace("\\", "/").strip("/")
        hit = []
        if t in GROUPS:
            hit = [f for f in FILES if group_of(f) == t]
        else:
            for f in FILES:
                r, m = rel(f), module_of(f)
                if (
                    t in (r, m, f.stem)
                    or t + ".py" == r
                    or fnmatch.fnmatch(r, t)
                    or fnmatch.fnmatch(r, t + ".py")
                    or fnmatch.fnmatch(f.stem, t)
                    or fnmatch.fnmatch(m, t)
                ):
                    hit.append(f)
        if not hit:
            unknown.append(tok)
        chosen += [f for f in hit if f not in chosen]
    return chosen, unknown


# ---------------------------------------------------------------- name tables
def top_level_names(p):
    """Names a module defines at top level (also inside if/try/with blocks)."""
    t = tree_of(p)
    names, star_or_getattr = set(), False

    def add_target(n):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, (ast.Tuple, ast.List)):
            for e in n.elts:
                add_target(e)

    def walk(body):
        nonlocal star_or_getattr
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
                if n.name == "__getattr__":
                    star_or_getattr = True
            elif isinstance(n, ast.Assign):
                for tg in n.targets:
                    add_target(tg)
            elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
                add_target(n.target)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    names.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if a.name == "*":
                        star_or_getattr = True
                    names.add(a.asname or a.name)
            elif isinstance(
                n, (ast.If, ast.Try, ast.With, ast.AsyncWith, ast.For, ast.While)
            ):
                for attr in ("body", "orelse", "finalbody"):
                    walk(getattr(n, attr, []) or [])
                for h in getattr(n, "handlers", []) or []:
                    walk(h.body)

    if not isinstance(t, SyntaxError):
        walk(t.body)
    return names, star_or_getattr


def resolve_module(dotted):
    """Project file for a dotted module name, or None."""
    parts = dotted.split(".")
    base = ROOT.joinpath(*parts)
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def is_package(dotted):
    return (ROOT.joinpath(*dotted.split(".")) / "__init__.py").is_file()


STEMS = {}
for _f in FILES:
    if group_of(_f) in ("helpers", "root", "routes", "tools"):
        STEMS.setdefault(_f.stem, []).append(_f)


def project_top(name):
    """True if `name` is the first part of a project module/package."""
    return (ROOT / f"{name}.py").is_file() or (ROOT / name / "__init__.py").is_file()


def inside_optional_try(tree, target):
    """True if `target` (an import node) sits in a try body that handles ImportError."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Try) and any(
            (h.type is None)
            or (
                isinstance(h.type, ast.Name)
                and h.type.id in ("ImportError", "ModuleNotFoundError", "Exception")
            )
            or (
                isinstance(h.type, ast.Tuple)
                and any(
                    isinstance(e, ast.Name)
                    and e.id in ("ImportError", "ModuleNotFoundError")
                    for e in h.type.elts
                )
            )
            for h in n.handlers
        ):
            for sub in ast.walk(ast.Module(body=n.body, type_ignores=[])):
                if sub is target:
                    return True
    return False


# ---------------------------------------------------------------- checks per module
def check_syntax(p):
    t = tree_of(p)
    if isinstance(t, SyntaxError):
        return "FAIL", [f"{t.msg} (line {t.lineno})"]
    return "PASS", []


def pyflakes_for(files):
    try:
        import pyflakes  # noqa: F401
    except ImportError:
        return None
    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes"] + [str(f) for f in files],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    out = {}
    for line in (proc.stdout + proc.stderr).splitlines():
        m = re.match(r"(.+?):(\d+):(?:\d+:?)? (.*)", line)
        if not m:
            continue
        path = Path(m.group(1))
        try:
            key = path.resolve()
        except OSError:
            key = path
        out.setdefault(key, []).append(f"line {m.group(2)}: {m.group(3)}")
    return out


FATAL = re.compile(
    r"undefined name|undefined local|may be undefined|unable to detect undefined|import \*|unable to compile"
)


def check_imports(p):
    t = tree_of(p)
    if isinstance(t, SyntaxError):
        return "SKIP", ["syntax error, imports not analysed"], []
    fails, warns = [], []
    for n in ast.walk(t):
        pairs = []  # (dotted, [names or None])
        if isinstance(n, ast.Import):
            pairs = [(a.name, None) for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            pairs = [(n.module, [a.name for a in n.names])]
        for dotted, names in pairs:
            top = dotted.split(".")[0]
            target = resolve_module(dotted)
            optional = inside_optional_try(t, n)
            if target is None:
                if project_top(top):
                    # a project package, but the module inside it does not exist
                    fails.append(
                        f"line {n.lineno}: '{dotted}' does not exist in package '{top}'"
                    )
                elif top in STEMS and not _spec_ok(top):
                    where = ", ".join(module_of(x) for x in STEMS[top])
                    fails.append(
                        f"line {n.lineno}: '{dotted}' moved - import it as '{where}'"
                    )
                elif not _spec_ok(top) and not optional:
                    warns.append(
                        f"line {n.lineno}: '{dotted}' is not stdlib, not installed and not a project module"
                    )
                continue
            if names:
                defined, dynamic = top_level_names(target)
                for nm in names:
                    if nm == "*" or dynamic or nm in defined:
                        continue
                    if is_package(dotted) and resolve_module(dotted + "." + nm):
                        continue
                    fails.append(
                        f"line {n.lineno}: '{nm}' is not defined in {rel(target)}"
                    )
    return ("FAIL" if fails else "PASS"), fails, warns


def _spec_ok(top):
    try:
        return importlib.util.find_spec(top) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def check_layering(p):
    if group_of(p) != "helpers":
        return None
    t = tree_of(p)
    if isinstance(t, SyntaxError):
        return "SKIP", []
    bad = []
    for n in ast.walk(t):
        mods = (
            [a.name for a in n.names]
            if isinstance(n, ast.Import)
            else (
                [n.module]
                if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module
                else []
            )
        )
        for m in mods:
            if m.split(".")[0] in LEAF_FORBIDDEN:
                bad.append(
                    f"line {n.lineno}: helpers must stay leaf modules but import '{m}'"
                )
    return ("FAIL" if bad else "PASS"), bad


def try_import(p, force, explicit):
    mod = module_of(p)
    top = mod.split(".")[0]
    if group_of(p) in ("tools", "tests") or p.name == "__init__.py":
        return "SKIP", ["scripts in tools/ and tests/ are run, not imported"]
    if (top in DENY_IMPORT or group_of(p) == "routes") and not force:
        return "SKIP", [
            "refused: start-up side effects (use --force only with the server stopped)"
        ]
    if not explicit and group_of(p) not in ("helpers",):
        return "SKIP", [
            "only helpers/ is imported automatically; name the module to import it"
        ]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    code = f"import importlib,sys; sys.path.insert(0, {str(ROOT)!r}); importlib.import_module({mod!r}); print('imported')"
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return "FAIL", ["import took more than 30 s (it probably starts something)"]
    if r.returncode == 0:
        return "PASS", []
    tail = [l for l in (r.stderr or "").strip().splitlines() if l.strip()][-3:]
    return "FAIL", tail or ["import failed"]


def check_config():
    res = []
    cfg_names, _ = (
        top_level_names(ROOT / "config.py")
        if (ROOT / "config.py").is_file()
        else (set(), False)
    )
    for name in ("server_config.json", "storage_config.json"):
        f = ROOT / name
        if not f.is_file():
            res.append(
                ("SKIP", name, ["file not found (created on first configuration)"])
            )
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            res.append(("FAIL", name, [f"not valid JSON: {e}"]))
            continue
        if not isinstance(data, dict):
            res.append(("FAIL", name, ["top level is not an object"]))
            continue
        stale = []
        if name == "server_config.json" and cfg_names:
            stale = [
                f"key '{k}' is not a name defined in config.py (stale or renamed?)"
                for k in data
                if k not in cfg_names
            ]
        res.append(("WARN" if stale else "PASS", f"{name} ({len(data)} keys)", stale))
    return res


# ---------------------------------------------------------------- main
def importers_count(files):
    counts = {}
    for f in FILES:
        t = tree_of(f)
        if isinstance(t, SyntaxError):
            continue
        seen = set()
        for n in ast.walk(t):
            mods = (
                [a.name for a in n.names]
                if isinstance(n, ast.Import)
                else (
                    [n.module]
                    if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module
                    else []
                )
            )
            for m in mods:
                seen.add(m)
                if isinstance(n, ast.ImportFrom) and n.module == "helpers":
                    seen |= {f"helpers.{a.name}" for a in n.names}
        for m in seen:
            counts.setdefault(m, set()).add(rel(f))
    return {
        module_of(f): len(counts.get(module_of(f), set()) - {rel(f)}) for f in files
    }


def main():
    ap = argparse.ArgumentParser(
        description="Per-module checker for CloudinatorFTP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "targets",
        nargs="*",
        help="groups (root helpers routes tools tests), module names, paths or globs; default: all",
    )
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--import", dest="do_import", action="store_true")
    ap.add_argument("--config", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    files, unknown = select(args.targets)
    if unknown:
        print("no module/group matches: " + ", ".join(unknown))
        print(
            "groups: "
            + ", ".join(GROUPS)
            + "  (helpers/ exists only after the helpers move)"
        )
        return 2
    if args.list:
        counts = importers_count(files)
        print(f"{len(files)} module(s)")
        for f in files:
            t = tree_of(f)
            main_blk = (
                (not isinstance(t, SyntaxError)) and "__main__" in ast.unparse(t)
                if hasattr(ast, "unparse")
                else False
            )
            n_lines = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            print(
                f"  {rel(f):<34} {n_lines:>5} lines  imported by {counts.get(module_of(f), 0):>2}{'  has __main__' if main_blk else ''}"
            )
        return 0

    flakes = pyflakes_for(files)
    entries, counts_n = [], {}
    for f in files:
        checks = []
        s, d = check_syntax(f)
        checks.append(("syntax", s, d))
        if flakes is None:
            checks.append(("pyflakes", "SKIP", ["pip install pyflakes"]))
        else:
            lines = flakes.get(f.resolve(), [])
            fatal = [x for x in lines if FATAL.search(x)]
            checks.append(("pyflakes", "FAIL" if fatal else "PASS", fatal))
        r = check_imports(f)
        checks.append(("imports", r[0], r[1]))
        if r[2]:
            checks.append(("imports(warn)", "WARN", r[2]))
        lay = check_layering(f)
        if lay:
            checks.append(("layering", lay[0], lay[1]))
        if args.do_import:
            explicit = any(
                t.replace("\\", "/").strip("/") not in GROUPS for t in args.targets
            )
            s, d = try_import(f, args.force, explicit)
            checks.append(("import", s, d))
        entries.append((f, checks))

    cfg = check_config() if args.config else []
    worst = lambda cs: (
        "FAIL"
        if any(c[1] == "FAIL" for c in cs)
        else ("WARN" if any(c[1] == "WARN" for c in cs) else "PASS")
    )
    problems = 0
    if args.json:
        out = {
            "modules": {
                rel(f): [{"check": c, "status": s, "details": d} for c, s, d in cs]
                for f, cs in entries
            },
            "config": [{"status": s, "file": n, "details": d} for s, n, d in cfg],
        }
        print(json.dumps(out, indent=1))
    else:
        print(f"check - project root: {ROOT}")
        print(
            f"{len(files)} module(s)"
            + (
                f", targets: {' '.join(args.targets)}"
                if args.targets
                else ", all groups"
            )
        )
        print()
        for f, cs in entries:
            w = worst(cs)
            counts_n[w] = counts_n.get(w, 0) + 1
            if args.quiet and w == "PASS":
                continue
            summary = " | ".join(
                f"{c} {s.lower()}" for c, s, _d in cs if not c.endswith("(warn)")
            )
            print(f"[{w}] {rel(f)}  --  {summary}")
            for c, s, d in cs:
                if s in ("FAIL", "WARN") or (
                    s == "SKIP" and not args.quiet and c == "pyflakes"
                ):
                    for line in d:
                        print(f"       {c}: {line}")
        for s, n, d in cfg:
            counts_n["cfg " + s] = counts_n.get("cfg " + s, 0) + 1
            print(f"[{s}] config: {n}")
            for line in d:
                print(f"       {line}")
        print(
            "\nSummary: " + ", ".join(f"{v} {k}" for k, v in sorted(counts_n.items()))
        )
    fails = sum(1 for _f, cs in entries if worst(cs) == "FAIL") + sum(
        1 for s, _n, _d in cfg if s == "FAIL"
    )
    warns = sum(1 for _f, cs in entries if worst(cs) == "WARN") + sum(
        1 for s, _n, _d in cfg if s == "WARN"
    )
    if fails or (args.strict and warns):
        if not args.json:
            print("FAILED" + (" (strict: warnings count)" if not fails else ""))
        return 1
    if not args.json:
        print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
