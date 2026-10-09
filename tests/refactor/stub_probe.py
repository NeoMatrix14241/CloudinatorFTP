#!/usr/bin/env python3
"""
stub_probe.py - runtime comparison of the REAL Quart app, without touching real data.

It imports app.py for real (so Quart builds its genuine url_map, hook lists, error handlers,
Jinja filters, config), but replaces every OTHER project module (config, database, auth,
storage, file_monitor, ...) with a stand-in, so nothing reads or writes your real storage,
database, cache or logs and no real file monitor / crawler starts. (initialize_cleanup()
still starts its daemon threads, but against the stand-ins.)

Typical use around a phase (from the project root):

    # 1. BEFORE the phase: record the state of the current (previous-phase) tree
    python tests/refactor/stub_probe.py --out before.json --http

    # 2. do the phase

    # 3. AFTER the phase: record again and compare
    python tests/refactor/stub_probe.py --out after.json --http
    python tests/refactor/stub_probe.py --compare before.json after.json

For Phase 1 the "before" must come from the pristine code: check out the 4.68 commit in a
second folder (git worktree add ../CloudinatorFTP_before <commit>) and run
    python tests/refactor/stub_probe.py --project ../CloudinatorFTP_before --out before.json --http

What it proves: same URL rules/endpoints/methods, same hook order (incl. CSRF's own
before_request), same error handlers, Jinja filters/globals, session interface, config keys,
CSRF-exempt endpoints, static/template folders, exported names, and (with --http) the same
status code and response headers for a dozen requests. What it cannot prove: behaviour that
depends on real data (uploads, shares, video...) - click through the real app for that.
Needs `pip install quart` (already required by the project).
"""

import ast
import asyncio
import json
import os
import re
import sys
import types
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parents[1]
OWN_MODULES = ("app", "core", "middleware", "routes", "services")


def _stub_class():
    from unittest.mock import MagicMock

    class Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            up = name.upper()
            if name.isupper() and any(
                k in up
                for k in (
                    "DIR",
                    "PATH",
                    "ROOT",
                    "FOLDER",
                    "FILE",
                    "NAME",
                    "SALT",
                    "SECRET",
                    "HOST",
                    "DOMAIN",
                )
            ):
                v = "/tmp/stub_" + name.lower()
            elif name.isupper() and any(
                k in up
                for k in (
                    "SIZE",
                    "LIMIT",
                    "SECONDS",
                    "TTL",
                    "PORT",
                    "COUNT",
                    "MAX",
                    "MIN",
                    "TIMEOUT",
                    "INTERVAL",
                    "DAYS",
                    "HOURS",
                    "LIFETIME",
                    "WORKERS",
                    "THRESHOLD",
                )
            ):
                v = 60
            elif name.isupper() and (up.startswith("ENABLE") or up.endswith("ENABLED")):
                v = False
            else:
                v = MagicMock(name=f"{self.__name__}.{name}")
            setattr(self, name, v)
            return v

    return Stub


def modules_to_stub(root: Path):
    """Top-level modules imported by app/core/middleware/routes that are project files
    (or not installed), excluding the modules under test."""
    import importlib.util

    files = [root / "app.py", root / "core.py", root / "middleware.py"]
    for d in ("routes", "services"):
        if (root / d).is_dir():
            files += sorted((root / d).rglob("*.py"))
    names = []
    for f in files:
        if not f.is_file():
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names += [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                names.append(n.module.split(".")[0])
    out = []
    for m in dict.fromkeys(names):
        if m in sys.stdlib_module_names or m in OWN_MODULES:
            continue
        is_project = (root / f"{m}.py").is_file() or (root / m).is_dir()
        if is_project or importlib.util.find_spec(m) is None:
            out.append(m)
    return out


def collect(root: Path, with_http: bool) -> dict:
    root = root.resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    Stub = _stub_class()
    stubbed = modules_to_stub(root)
    for m in stubbed:
        sys.modules[m] = Stub(m)
    if "database" in sys.modules:
        sys.modules["database"].get_session_secret = lambda *a, **k: "s" * 32
    if "net_utils" in sys.modules:
        sys.modules["net_utils"].get_local_ip = lambda *a, **k: "127.0.0.1"
    import importlib

    mod = importlib.import_module("app")
    a = mod.app
    nm = lambda f: getattr(f, "__name__", repr(f))
    rules = sorted(
        (
            r.rule,
            r.endpoint,
            sorted(x for x in (r.methods or ()) if x not in ("HEAD", "OPTIONS")),
            sorted(map(str, (r.defaults or {}).items())),
        )
        for r in a.url_map.iter_rules()
    )
    out = {
        "stubbed_modules": sorted(stubbed),
        "rules": [[str(x) for x in r] for r in rules],
        "before_request": [nm(f) for f in a.before_request_funcs.get(None, [])],
        "after_request": [nm(f) for f in a.after_request_funcs.get(None, [])],
        "before_serving": [nm(f) for f in a.before_serving_funcs],
        "error_handlers": sorted(
            str(k)
            for d in a.error_handler_spec.values()
            for dd in d.values()
            for k in dd
        ),
        "jinja_filters": sorted(a.jinja_env.filters),
        "jinja_globals": sorted(a.jinja_env.globals),
        "secret_key_set": a.secret_key is not None,
        "session_interface": type(a.session_interface).__name__,
        "config": {
            k: str(v)
            for k, v in sorted(a.config.items())
            if k.startswith(
                (
                    "SESSION",
                    "PERMANENT",
                    "MAX_",
                    "SEND_",
                    "TEMPLATES",
                    "PREFERRED",
                    "APPLICATION",
                )
            )
        },
        "static_folder": os.path.relpath(a.static_folder, root),
        "template_folder": str(a.template_folder),
        # 4.75: `csrf` is read from core (since Phase 7 app.py no longer imports it; core.csrf is
        # the same object app.csrf used to be). Keeps recordings from before Phase 7 comparable.
        "exports": {
            n: hasattr(mod, n) if n != "csrf" else hasattr(sys.modules.get("core", mod), n)
            for n in ("app", "get_local_ip", "csrf")
        },
        "csrf_exempt": sorted(
            getattr(getattr(sys.modules.get("core", mod), "csrf", None), "_exempt_endpoints", [])
            or []
        ),
    }
    if with_http:

        async def run():
            c = a.test_client()
            reqs = [
                ("GET", "/robots.txt", {}),
                ("GET", "/login", {}),
                ("GET", "/csrf-token", {}),
                ("GET", "/definitely-not-a-page", {}),
                ("GET", "/api/files", {}),
                ("POST", "/login", {}),
                ("POST", "/api/share", {}),
                (
                    "OPTIONS",
                    "/api/files",
                    {
                        "Origin": "https://evil.example",
                        "Access-Control-Request-Method": "GET",
                    },
                ),
                ("GET", "/shared/abc", {}),
                ("POST", "/shared/abc/request_access", {}),
                ("GET", "/check_session", {}),
                ("GET", "/sitemap.xml", {}),
            ]
            res = []
            for m, p, h in reqs:
                try:
                    r = await c.open(p, method=m, headers=h)
                    hd = {
                        k: v
                        for k, v in r.headers.items()
                        if k.lower()
                        not in (
                            "date",
                            "content-length",
                            "set-cookie",
                            "etag",
                            "last-modified",
                        )
                    }
                    if "content-security-policy" in hd:  # per-request random nonce
                        hd["content-security-policy"] = re.sub(
                            r"'nonce-[^']+'", "'nonce-X'", hd["content-security-policy"]
                        )
                    res.append(
                        {"req": f"{m} {p}", "status": r.status_code, "headers": hd}
                    )
                except Exception as e:  # recorded, compared like any other result
                    res.append({"req": f"{m} {p}", "error": type(e).__name__})
            return res

        out["http"] = asyncio.run(run())
    return out


def compare(fa: str, fb: str) -> int:
    a, b = json.load(open(fa, encoding="utf-8")), json.load(open(fb, encoding="utf-8"))
    bad = 0
    for k in a:
        if k in ("stubbed_modules",):
            continue
        if k == "http":
            for x, y in zip(a[k], b.get(k, [])):
                if x != y:
                    bad += 1
                    diff = [
                        h
                        for h in sorted(
                            set(x.get("headers", {})) | set(y.get("headers", {}))
                        )
                        if x.get("headers", {}).get(h) != y.get("headers", {}).get(h)
                    ]
                    print(
                        f"[DIFF] {x['req']}: status {x.get('status', x.get('error'))} -> {y.get('status', y.get('error'))}, headers differ: {diff}"
                    )
            ok = sum(1 for x, y in zip(a[k], b.get(k, [])) if x == y)
            print(
                f"[{'OK' if ok == len(a[k]) else 'DIFF'}] http: {ok}/{len(a[k])} requests identical (status + all headers)"
            )
        elif a[k] != b.get(k):
            bad += 1
            print(
                f"[DIFF] {k}\n   before: {str(a[k])[:300]}\n   after : {str(b.get(k))[:300]}"
            )
        else:
            print(f"[OK]   {k}" + (f" ({len(a[k])})" if isinstance(a[k], list) else ""))
    print("\nIDENTICAL" if not bad else f"\n{bad} DIFFERENCE(S)")
    return 1 if bad else 0


def main(argv):
    if "--compare" in argv:
        i = argv.index("--compare")
        return compare(argv[i + 1], argv[i + 2])
    root = (
        Path(argv[argv.index("--project") + 1]) if "--project" in argv else DEFAULT_ROOT
    )
    out = Path(argv[argv.index("--out") + 1]).resolve() if "--out" in argv else None
    if out is None:
        print(
            "usage: stub_probe.py [--project DIR] --out FILE [--http]   |   --compare A.json B.json"
        )
        return 2
    data = collect(root, "--http" in argv)
    out.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    print(
        f"wrote {out}: {len(data['rules'])} url rules; before_request={data['before_request']}; "
        f"stubbed {len(data['stubbed_modules'])} modules"
    )
    os._exit(
        0
    )  # daemon cleanup threads started by initialize_cleanup() must not keep the process alive


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
