#!/usr/bin/env python3
"""
Phase 1 - core.py + middleware.py.

All shared objects, startup side effects and EVERY hook move out of app.py; routes stay.
This is the riskiest phase: hook order, CSRF/CORS/CSP, startup order.

Usage (from the project root):
    python tests/refactor/test_phase01_core_middleware.py --pre       # BEFORE starting this phase: invariants only
    python tests/refactor/test_phase01_core_middleware.py             # AFTER finishing it: invariants + "moved" + extras
    python tests/refactor/test_phase01_core_middleware.py --runtime   # also compare Quart's real url_map (scratch copy only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403  (test helpers only; this is not a project module)
from common import run_phase


def check_core(t):
    """core.py is the bottom layer and owns the shared singletons"""
    tree = tree_of("core.py")
    if tree is None:
        t.check("core.py exists", False)
        return
    syms = top_level_symbols(tree)
    need = [
        "app",
        "csrf",
        "rate_limiter",
        "chunk_tracker",
        "assembly_queue",
        "file_monitor",
        "request_logger",
        "app_logger",
        "login_required",
        "get_client_ip",
        "get_local_ip",
        "get_protected_files",
        "_trigger_reconcile",
    ]
    t.check(
        "core.py defines the shared singletons/helpers",
        all(n in syms for n in need),
        "missing: " + ", ".join(n for n in need if n not in syms),
    )
    miss = [n for n in CORE_EXPORTS if not binds_name(tree, n)]
    t.check(
        f"core.py exposes all {len(CORE_EXPORTS)} names the later phases import from it",
        not miss,
        "missing in core.py: " + ", ".join(miss),
    )
    quart_calls = count_calls("Quart")
    t.check(
        "exactly ONE Quart(...) application object exists in the project",
        len(quart_calls) == 1,
        str(quart_calls),
    )
    local = local_module_names()
    above = [
        m
        for m in imports_of(path_of("core.py"), local, include_nested=True)
        if m.split(".")[0] in ("middleware", "routes", "services")
    ]
    t.check(
        "core.py imports nothing from middleware/routes/services (it is the bottom layer)",
        not above,
        str(above),
    )
    for fn, label in (
        ("init_file_monitor", "file monitor"),
        ("version_history.init", "version_history.init"),
        ("storage.ensure_root", "storage.ensure_root"),
    ):
        hits = count_calls(fn)
        t.check(f"{label} started exactly once ({fn})", len(hits) == 1, str(hits))
    attr_assigns = {
        ast.unparse(tg)
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        for tg in n.targets
        if isinstance(tg, ast.Attribute)
    }
    t.check(
        "import-time app configuration moved too: app.secret_key and app.session_interface assigned in core.py",
        {"app.secret_key", "app.session_interface"} <= attr_assigns,
        f"found: {sorted(attr_assigns)}",
    )
    t.check(
        "app.config.update(...) (cookie flags, session lifetime) still executed once in core.py",
        len([c for c in count_calls("app.config.update") if c[0] == "core.py"]) == 1,
        str(count_calls("app.config.update")),
    )
    t.check(
        "both mimetypes.add_type(...) calls (.js and .mjs) still executed",
        len(
            [
                c
                for c in count_calls("mimetypes.add_type")
                if c[0] in ("core.py", "app.py")
            ]
        )
        == 2,
        str(count_calls("mimetypes.add_type")),
    )
    t.check(
        "sys.stdout.reconfigure(line_buffering=True) still executed at import",
        len(count_calls("sys.stdout.reconfigure")) >= 1,
    )
    t.info(
        "Quart(__name__) in core.py makes app.name == 'core' (was 'app'). The old code never reads "
        "app.name/import_name (only app.static_folder), but if you see a template/static problem, "
        "check Quart('app', root_path=...) first."
    )


def check_middleware(t):
    """middleware.py owns every hook, the CORS preflight route and the error handlers"""
    routes, hooks = scan_all()
    stray = [
        f"{h['kind']}:{h['func']} in {h['file']}"
        for h in hooks
        if h["kind"]
        in ("before_request", "after_request", "errorhandler", "template_filter")
        and h["file"] != "middleware.py"
    ]
    t.check(
        "all before_request/after_request/errorhandler/template_filter hooks are in middleware.py",
        not stray,
        "\n".join(stray),
    )
    mw = tree_of("middleware.py")
    if mw is not None:

        def is_def(s, name):
            return (
                isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
                and s.name == name
            )

        def is_csrf_hook(s):
            return not isinstance(
                s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ) and (stmt_calls(s, "csrf.init_app") or stmt_calls(s, "CSRFProtect"))

        i_timer = stmt_index(mw, lambda s: is_def(s, "_start_request_timer"))
        i_val = stmt_index(mw, lambda s: is_def(s, "validate_session"))
        i_csrf = stmt_index(mw, is_csrf_hook)
        t.check(
            "CSRF's own before_request is registered in middleware.py (csrf.init_app(app)) AFTER _start_request_timer "
            "and BEFORE validate_session (runtime order: _start_request_timer, _protect, validate_session, before_request)",
            None not in (i_timer, i_val, i_csrf) and i_timer < i_csrf < i_val,
            f"timer@{i_timer} csrf@{i_csrf} validate_session@{i_val}. core.py must only create `csrf = CSRFProtect()`; "
            "calling CSRFProtect(app) there would register _protect FIRST.",
        )
        in_core = [c for c in count_calls("CSRFProtect") if c[0] != "core.py"] + [
            c for c in count_calls("csrf.init_app") if c[0] == "core.py"
        ]
        t.check(
            "core.py does not register the CSRF hook itself", not in_core, str(in_core)
        )
    pre = [r for r in routes if r["func"] == "_cors_preflight"]
    t.check(
        "the CORS OPTIONS route (_cors_preflight) lives in middleware.py",
        bool(pre) and all(r["file"] == "middleware.py" for r in pre),
        str(pre),
    )


def check_app_composition(t):
    """app.py = ensure_dirs -> import core -> import middleware -> routes -> initialize_cleanup()"""
    tree = tree_of("app.py")

    def imports_routes(s):
        if isinstance(s, ast.ImportFrom):
            return (s.module or "").split(".")[0] == "routes"
        if isinstance(s, ast.Import):
            return any(a.name.split(".")[0] == "routes" for a in s.names)
        return False

    i_core = stmt_index(tree, lambda s: stmt_imports_module(s, "core"))
    i_mw = stmt_index(tree, lambda s: stmt_imports_module(s, "middleware"))
    i_init = stmt_index(
        tree, lambda s: isinstance(s, ast.Expr) and stmt_calls(s, "initialize_cleanup")
    )
    t.check(
        "app.py imports core, then middleware",
        i_core is not None and i_mw is not None and i_core < i_mw,
        f"core@{i_core} middleware@{i_mw}",
    )
    # ensure_dirs() must run before the heavy imports (config, database, storage ...)
    i_dirs_app = stmt_index(
        tree, lambda s: isinstance(s, ast.Expr) and stmt_calls(s, "ensure_dirs")
    )
    ok = False
    if i_dirs_app is not None and i_core is not None:
        ok = i_dirs_app < i_core
    else:
        ctree = tree_of("core.py")
        if ctree is not None:
            i_d = stmt_index(
                ctree,
                lambda s: isinstance(s, ast.Expr) and stmt_calls(s, "ensure_dirs"),
            )
            heavy = (
                "config",
                "database",
                "auth",
                "storage",
                "file_monitor",
                "search_index",
            )
            i_h = stmt_index(
                ctree, lambda s: any(stmt_imports_module(s, m) for m in heavy)
            )
            ok = i_d is not None and (i_h is None or i_d < i_h)
    t.check(
        "ensure_dirs() still runs before the heavy imports (config, database, storage, ...)",
        ok,
    )
    after = [i for i, s in enumerate(tree.body) if imports_routes(s)] + [
        i_mw if i_mw is not None else 0
    ]
    t.check(
        "initialize_cleanup() runs after every middleware/routes import",
        i_init is not None and all(i < i_init for i in after),
        f"init@{i_init} imports@{after}",
    )


if __name__ == "__main__":
    sys.exit(run_phase(1, extra=[check_core, check_middleware, check_app_composition]))
