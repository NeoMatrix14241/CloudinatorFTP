"""
5.44 ratchet guard (ASYNC_BLOCKING_REFACTOR_PLAN, Step 0): no blocking disk, subprocess or
database call may run on the event-loop thread inside an `async def`.

Reads every `routes/*.py`, `middleware.py` and `core.py` with `ast` (none of them can be
imported: they start the whole application) and lists the calls of every `async def` whose
dotted name is on DENYLIST and that are not handed to a worker thread. Nested SYNC defs are
not scanned: they run where their caller puts them (usually a thread). The list is compared
with KNOWN, a table keyed by (file, function, call), never by line:

  * a NEW offender fails the test   -> offload it with `asyncio.to_thread`, or, when the call
                                       is justified, add `# blocking-ok: <reason>` to its line;
  * a LISTED offender that is gone  -> delete its KNOWN entry (the ratchet only goes down).

"Offloaded" = the callable is passed uncalled to `asyncio.to_thread(...)` /
`loop.run_in_executor(...)`, or the call sits inside a `lambda` that is passed to them.
`asyncio.to_thread(storage.x())` (the call runs on the loop, its RESULT is handed over) is
flagged. Single `os.path.*` stats are deliberately not on the denylist (plan, section 1.4).

No project import, no Quart: runs on any Python.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

SHUTIL_BLOCKING = {"rmtree", "copytree", "move", "copy", "copy2", "copyfile"}
STORAGE_BLOCKING = {
    "get_storage_stats",
    "delete_path",
    "get_dir_info",
    "create_folder",
    "cleanup_chunks",
    "chunks_complete",
    "cleanup_old_chunks",
    "manual_chunks_cleanup",
    "emergency_cleanup_all",
    "verify_chunks_complete",
    "safe_rmtree",
    "get_directory_size",
    "assemble_chunks",
}
EXACT_BLOCKING = {
    "os.walk",
    "os.listdir",
    "os.scandir",
    "glob.glob",
    "time.sleep",
    "subprocess.run",
    "subprocess.check_output",
    "subprocess.call",
    # database calls on the event loop (plan T9, revision 13)
    "sqlite3.connect",
    "auth.get_role",
    "auth.is_logged_in",
    "auth.request_is_logged_in",
    "request_is_logged_in",
    "get_role",
    "is_logged_in",
}
OFFLOADERS = {
    "asyncio.to_thread": 0,
    "run_in_executor": 1,
}  # name -> index of the callable

# (file, async function, call): the task of the plan that removes it. Delete a line when the
# call is gone. Everything left here is T9: the SQLite opens of the hooks and handlers
# (`request_is_logged_in`, `get_role`, `db.*`). 5.44 cut them from about 10 to about 4 per request
# (one memoised login check, one memoised role, WAL set once) and left them ON the loop on
# purpose: offloading adds a thread hop to every request and puts logins behind the default pool,
# so it waits for the `Slow SQLite open` line of database._connect() (plan T9, part B item 5).
KNOWN = {
    ("core.py", "decorated", "request_is_logged_in"): "T9",
    ("middleware.py", "after_request", "request_is_logged_in"): "T9",
    ("middleware.py", "before_request", "request_is_logged_in"): "T9",
    ("middleware.py", "validate_session", "get_role"): "T9",
    ("routes/admin.py", "admin_rebuild_cache", "get_role"): "T9",
    ("routes/admin.py", "admin_rebuild_cache_status", "get_role"): "T9",
    ("routes/files.py", "_bulk_start", "get_role"): "T9",
    ("routes/files.py", "api_files", "get_role"): "T9",
    ("routes/files.py", "bulk_delete", "get_role"): "T9",
    ("routes/files.py", "bulk_job_status", "get_role"): "T9",
    ("routes/files.py", "delete", "get_role"): "T9",
    ("routes/files.py", "mkdir", "get_role"): "T9",
    ("routes/files.py", "rename_item", "get_role"): "T9",
    ("routes/login.py", "check_session", "request_is_logged_in"): "T9",
    ("routes/login.py", "login", "get_role"): "T9",
    (
        "routes/shares.py",
        "admin_approve_share_request",
        "db.approve_access_request",
    ): "T9",
    (
        "routes/shares.py",
        "admin_approve_share_request",
        "db.list_pending_requests",
    ): "T9",
    ("routes/shares.py", "admin_approve_share_request", "get_role"): "T9",
    ("routes/shares.py", "admin_deny_share_request", "db.deny_access_request"): "T9",
    ("routes/shares.py", "admin_deny_share_request", "db.list_pending_requests"): "T9",
    ("routes/shares.py", "admin_deny_share_request", "get_role"): "T9",
    ("routes/shares.py", "admin_revoke_all_shares", "db.revoke_all_shares"): "T9",
    ("routes/shares.py", "admin_revoke_all_shares", "get_role"): "T9",
    ("routes/shares.py", "admin_revoke_all_shares_code", "get_role"): "T9",
    ("routes/shares.py", "admin_shares_count", "db.list_active_shares"): "T9",
    ("routes/shares.py", "admin_shares_count", "get_role"): "T9",
    ("routes/shares.py", "admin_shares_list", "db.list_active_shares"): "T9",
    ("routes/shares.py", "admin_shares_list", "get_role"): "T9",
    (
        "routes/shares.py",
        "admin_shares_pending_requests",
        "db.list_pending_requests",
    ): "T9",
    ("routes/shares.py", "admin_shares_pending_requests", "get_role"): "T9",
    ("routes/shares.py", "admin_shares_requests_stream", "get_role"): "T9",
    ("routes/shares.py", "bulk_share", "db.bulk_revoke_by_paths"): "T9",
    ("routes/shares.py", "bulk_share", "get_role"): "T9",
    ("routes/shares.py", "create_share", "get_role"): "T9",
    ("routes/shares.py", "revoke_share", "db.revoke_share_by_path"): "T9",
    ("routes/shares.py", "revoke_share", "get_role"): "T9",
    ("routes/shares.py", "share_status", "db.get_share_by_path"): "T9",
    (
        "routes/shares.py",
        "shared_download",
        "db.get_access_request_by_access_token",
    ): "T9",
    (
        "routes/shares.py",
        "shared_download_item",
        "db.record_access_request_download",
    ): "T9",
    ("routes/shares.py", "shared_download_item", "db.record_share_download"): "T9",
    (
        "routes/shares.py",
        "shared_file_download",
        "db.record_access_request_download",
    ): "T9",
    ("routes/shares.py", "shared_file_download", "db.record_share_download"): "T9",
    ("routes/shares.py", "shared_request_access", "db.create_access_request"): "T9",
    ("routes/shares.py", "shared_request_access", "db.list_pending_requests"): "T9",
    (
        "routes/shares.py",
        "shared_request_status",
        "db.get_access_request_by_access_token",
    ): "T9",
    (
        "routes/shares.py",
        "shared_zip_selected",
        "db.get_access_request_by_access_token",
    ): "T9",
    (
        "routes/shares.py",
        "shared_zip_selected",
        "db.record_access_request_download",
    ): "T9",
    ("routes/shares.py", "shared_zip_selected", "db.record_share_download"): "T9",
    ("routes/shares.py", "update_share_settings", "db.get_share_by_token"): "T9",
    ("routes/shares.py", "update_share_settings", "get_role"): "T9",
    ("routes/stats.py", "monitoring_status", "request_is_logged_in"): "T9",
    ("routes/stats.py", "storage_stats_poll", "request_is_logged_in"): "T9",
    ("routes/stats.py", "storage_stats_stream", "request_is_logged_in"): "T9",
    ("routes/uploads.py", "admin_cleanup_chunks", "get_role"): "T9",
    ("routes/uploads.py", "cancel_upload", "get_role"): "T9",
    ("routes/uploads.py", "chunk_stats", "get_role"): "T9",
    ("routes/uploads.py", "cleanup_chunks", "get_role"): "T9",
    ("routes/uploads.py", "upload", "get_role"): "T9",
    ("routes/uploads.py", "upload_status", "get_role"): "T9",
    ("routes/versions.py", "api_versions_clear_failed", "get_role"): "T9",
    ("routes/versions.py", "api_versions_delete", "get_role"): "T9",
    ("routes/versions.py", "api_versions_restore", "get_role"): "T9",
    ("routes/versions.py", "api_versions_retry", "get_role"): "T9",
}


def _dotted(node):
    """ast.Attribute / ast.Name chain -> "a.b.c"; anything else -> None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _is_blocking(name):
    if name is None:
        return False
    if name in EXACT_BLOCKING:
        return True
    head, _, tail = name.partition(".")
    if head == "shutil":
        return tail in SHUTIL_BLOCKING
    if head == "storage":
        return tail in STORAGE_BLOCKING
    if head == "chunk_tracker":
        return tail.startswith("cleanup_")
    if head == "db":
        return bool(tail)
    return False


def _offloaded_callable_index(call):
    """Index of the argument that is the callable handed to a thread, or None."""
    name = _dotted(call.func)
    if name is None:
        return None
    if name in OFFLOADERS:
        return OFFLOADERS[name]
    if name.endswith(".run_in_executor"):
        return OFFLOADERS["run_in_executor"]
    return None


def _walk_loop_thread(node):
    """Yield every node that runs on the event-loop thread inside one async def body: no
    nested defs, no lambdas, and not the callable argument of to_thread / run_in_executor.
    """
    stack = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        if isinstance(child, ast.Call):
            skip = _offloaded_callable_index(child)
            args = list(child.args)
            if (
                skip is not None
                and skip < len(args)
                and not isinstance(args[skip], ast.Call)
            ):
                # A Name / Attribute / Lambda callable: it runs in the thread. (A Call there
                # is the `to_thread(f())` mistake and stays scanned.)
                del args[skip]
            stack.extend(ast.iter_child_nodes(child.func))
            stack.extend(args)
            stack.extend(kw.value for kw in child.keywords)
        else:
            stack.extend(ast.iter_child_nodes(child))


def _blocking_comment(lines, node):
    """The text after `# blocking-ok:` on the first or last line of the call, or None."""
    for lineno in {node.lineno, getattr(node, "end_lineno", node.lineno)}:
        line = lines[lineno - 1]
        marker = "# blocking-ok:"
        if marker in line:
            return line.split(marker, 1)[1].strip()
    return None


def scan_source(source, label="x.py"):
    """-> (offenders, bad_escapes): offenders is a set of (label, function, call);
    bad_escapes lists `# blocking-ok:` comments that give no reason."""
    tree = ast.parse(source)
    lines = source.splitlines()
    offenders, bad_escapes = set(), []
    for func in ast.walk(tree):
        if not isinstance(func, ast.AsyncFunctionDef):
            continue
        for node in _walk_loop_thread(func):
            if not isinstance(node, ast.Call):
                continue
            name = _dotted(node.func)
            if not _is_blocking(name):
                continue
            reason = _blocking_comment(lines, node)
            if reason is None:
                offenders.add((label, func.name, name))
            elif not reason:
                bad_escapes.append(f"{label}:{node.lineno} {func.name} {name}")
    return offenders, bad_escapes


def _scan_repo():
    paths = sorted((ROOT / "routes").glob("*.py")) + [
        ROOT / "middleware.py",
        ROOT / "core.py",
    ]
    offenders, bad = set(), []
    for path in paths:
        label = path.relative_to(ROOT).as_posix()
        found, escapes = scan_source(path.read_text(encoding="utf-8"), label)
        offenders |= found
        bad += escapes
    return offenders, bad


# ----------------------------------------------------------------------------- the guard


def test_the_scanned_files_exist():
    assert (ROOT / "routes").is_dir()
    assert (ROOT / "middleware.py").is_file() and (ROOT / "core.py").is_file()
    assert list((ROOT / "routes").glob("*.py")), "routes/ has no module to scan"


def test_no_new_blocking_call_in_an_async_handler():
    offenders, bad = _scan_repo()
    assert not bad, f"`# blocking-ok:` needs a reason: {bad}"
    new = sorted(offenders - set(KNOWN))
    assert not new, (
        "blocking call(s) on the event loop: offload with asyncio.to_thread, or add "
        "'# blocking-ok: <reason>' to the line:\n  " + "\n  ".join(map(str, new))
    )


def test_every_known_offender_is_still_there():
    offenders, _bad = _scan_repo()
    gone = sorted(set(KNOWN) - offenders)
    assert not gone, "fixed - delete these entries from KNOWN:\n  " + "\n  ".join(
        map(str, gone)
    )


# ------------------------------------------------------------------- the scanner itself

GOOD = """
import asyncio, os, shutil
async def h(path):
    await asyncio.to_thread(shutil.rmtree, path)
    await asyncio.to_thread(storage.delete_path, path)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, os.listdir, path)
    await asyncio.to_thread(lambda: [os.listdir(path), shutil.rmtree(path)])
    return os.path.exists(path)
"""

BAD = """
import os, shutil, time
async def h(path):
    shutil.rmtree(path)
    os.listdir(path)
    storage.cleanup_chunks(path)
    chunk_tracker.cleanup_session_chunks(path)
    db.execute("select 1")
    time.sleep(1)
"""

CALLED_ARGUMENT = """
import asyncio
async def h(path):
    await asyncio.to_thread(storage.get_storage_stats())
"""

NESTED = """
async def h(path):
    def worker():
        shutil.rmtree(path)
    async def inner():
        shutil.rmtree(path)
    return worker
"""


def test_scanner_accepts_offloaded_calls():
    assert scan_source(GOOD) == (set(), [])


def test_scanner_flags_direct_calls():
    offenders, _ = scan_source(BAD)
    assert {call for _f, _fn, call in offenders} == {
        "shutil.rmtree",
        "os.listdir",
        "storage.cleanup_chunks",
        "chunk_tracker.cleanup_session_chunks",
        "db.execute",
        "time.sleep",
    }


def test_scanner_flags_the_call_evaluated_before_to_thread():
    offenders, _ = scan_source(CALLED_ARGUMENT)
    assert offenders == {("x.py", "h", "storage.get_storage_stats")}


def test_scanner_ignores_nested_sync_defs_and_counts_nested_async_defs_once():
    offenders, _ = scan_source(NESTED)
    assert offenders == {("x.py", "inner", "shutil.rmtree")}


def test_escape_comment_needs_a_reason():
    ok = "async def h(p):\n    shutil.rmtree(p)  # blocking-ok: one empty folder\n"
    empty = "async def h(p):\n    shutil.rmtree(p)  # blocking-ok:\n"
    assert scan_source(ok) == (set(), [])
    offenders, bad = scan_source(empty)
    assert offenders == set() and len(bad) == 1


@pytest.mark.parametrize(
    "name",
    ["os.path.exists", "os.path.getsize", "storage.is_safe_path", "storage.save_chunk"],
)
def test_single_stats_and_unlisted_storage_calls_are_not_flagged(name):
    assert scan_source(f"async def h(p):\n    {name}(p)\n") == (set(), [])
