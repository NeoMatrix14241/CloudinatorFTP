"""
tools/purge_missing_versions.py against the REAL Version Engine (CLAUDE.md 5.44.4).

Same technique as test_version_restore.py: the real modules run inside a SCRATCH COPY of the
project (own storage, own versions folder, own version database) through `run_in_scratch`, no
worker process, no server. The tool itself is copied into the scratch copy's `tools/` folder,
so its `sys.path.insert(0, _ROOT)` points at the copy and it imports the copy's `config` and
`version_engine`, never the real tree's. Every snippet first asserts that its folders are inside
the scratch copy.

A version is captured by calling `Engine.snapshot_file()` (what the worker does per file); the
"deleted" files are really deleted from the scratch storage. `--min-age-days 0` is used because
every version here is a few milliseconds old.
"""

import json
import shutil
import textwrap
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.application

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PRELUDE = textwrap.dedent("""
    import contextlib, importlib.util, io, json, os, sys, time
    import config
    cwd = os.path.abspath(os.getcwd())
    for _d in (config.ROOT_DIR, config.DB_DIR, config.VERSION_STORAGE_DIR):
        assert os.path.abspath(_d).startswith(cwd), "NOT inside the scratch copy: " + _d
    config.VERSION_SMALL_FILE_THRESHOLD = 1024 * 1024
    config.VERSION_CHUNK_SIZE = 1024 * 1024
    config.VERSION_RETENTION_ENABLED = False
    config.VERSION_GC_ENABLED = True
    import version_history as vh
    vh.init()
    eng = vh._get_engine()
    ROOT = config.ROOT_DIR
    TAG = sys.argv[1]
    FOLDER = os.path.join(ROOT, "pm_" + TAG)
    os.makedirs(FOLDER, exist_ok=True)
    config.VERSION_TRACK_DIRECTORIES = [FOLDER]

    spec = importlib.util.spec_from_file_location(
        "purge_tool", os.path.join(cwd, "tools", "purge_missing_versions.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert os.path.abspath(tool._ROOT) == cwd, "the tool points at " + tool._ROOT

    def put(name, data):
        path = os.path.join(FOLDER, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def snap(path):
        version_id = eng.snapshot_file(path, source="qa")
        time.sleep(0.02)
        return version_id

    def run_tool(*args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = tool.main(list(args))
        return code, buf.getvalue()

    def completed(path):
        return [v for v in (eng.list_versions(path) or []) if v["status"] == "completed"]

    def out(**kw):
        print("RESULT=" + json.dumps(kw, default=str))
    """)


@pytest.fixture
def lab(scratch_tools, tmp_path):
    root = tmp_path / "app"
    scratch_tools.build(root, port=scratch_tools.free_port())
    assert scratch_tools.paths_outside(root) == []
    shutil.copy2(
        REPO_ROOT / "tools" / "purge_missing_versions.py",
        _tools_dir(root) / "purge_missing_versions.py",
    )
    return root


def _tools_dir(root):
    d = Path(root) / "tools"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture
def run(lab, scratch_tools):
    def _run(body):
        tag = uuid.uuid4().hex[:8]
        code = PRELUDE + textwrap.dedent(body)
        stdout = scratch_tools.run_in_scratch(lab, code, tag)
        lines = [ln for ln in stdout.splitlines() if ln.startswith("RESULT=")]
        assert lines, "the snippet printed no RESULT line:\n" + stdout[-800:]
        result = json.loads(lines[-1][len("RESULT=") :])
        result["tag"] = tag
        return result

    return _run


def test_the_report_reconciles_with_the_real_folder(run):
    """10 files versioned, 8 deleted afterwards (80 % gone): the report says 2 on disk, 8 to
    purge, and the walk of the tracked folder finds the same 2 files."""
    r = run("""
        paths = [put(f"f{i}.txt", f"content {i}".encode()) for i in range(10)]
        for p in paths:
            snap(p)
        for p in paths[2:]:
            os.remove(p)
        code, text = run_tool("--report", "--min-age-days", "0")
        scan = tool.scan_tracked(eng.db_path, 0, [FOLDER],
                                 scope_keys=set(eng.get_eligible_files()))
        out(code=code, text=text, files_total=scan.files_total, present=scan.present,
            gone=scan.gone, purge=len(scan.purge), unsure=len(scan.unsure),
            scope=scan.scope_files, in_scope=scan.present_in_scope,
            still_completed=sum(len(completed(p)) for p in paths))
        """)
    assert r["code"] == 0
    assert (r["files_total"], r["present"], r["gone"], r["purge"]) == (10, 2, 8, 8)
    assert (
        r["unsure"] == 0
    )  # 80 % gone, yet nothing is held back: the folder is reachable
    assert (r["scope"], r["in_scope"]) == (2, 2)  # the walk and the database agree
    assert r["still_completed"] == 10  # --report changed nothing
    assert "Would soft-delete 8 version(s) of 8 file(s)" in r["text"]
    assert "this is real deletion" in r["text"]


def test_apply_frees_the_chunks_of_gone_files_and_keeps_the_others(run):
    r = run("""
        keep = put("keep.txt", b"keep me")
        gone = put("gone.txt", b"delete me " * 1000)
        snap(keep); snap(gone)
        os.remove(gone)
        objects_before = eng._connect().execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        code, text = run_tool("--apply", "--yes", "--free-now", "--min-age-days", "0")
        objects_after = eng._connect().execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        ok, _msg, rel = vh.restore(keep, completed(keep)[0]["version_id"])
        out(code=code, text=text, objects_before=objects_before,
            objects_after=objects_after, gone_versions=len(completed(gone)),
            keep_versions=len(completed(keep)), keep_restored=ok,
            keep_bytes=open(os.path.join(ROOT, rel), "rb").read().decode())
        """)
    assert r["code"] == 0
    assert r["gone_versions"] == 0
    assert r["keep_versions"] == 1 and r["keep_restored"]
    assert r["keep_bytes"] == "keep me"
    assert r["objects_after"] == r["objects_before"] - 1  # only the gone file's chunk
    assert "Freed 1 chunk(s)" in r["text"]
    assert "step 1 of 2: marking" in r["text"]
    assert "step 2 of 2: deleting 1 chunk file(s) from disk" in r["text"]


def test_apply_without_free_now_can_be_undone(run):
    r = run("""
        put("sentinel.txt", b"keeps the tracked folder non-empty")
        gone = put("gone.txt", b"bring me back")
        snap(gone)
        os.remove(gone)
        code1, text1 = run_tool("--apply", "--yes", "--min-age-days", "0")
        after_apply = len(completed(gone))
        undo = [os.path.join(eng.storage_dir, n) for n in os.listdir(eng.storage_dir)
                if n.startswith("purge_undo_")]
        code2, text2 = run_tool("--undo", undo[0])
        version_id = completed(gone)[0]["version_id"]
        ok, _msg, rel = vh.restore(gone, version_id)
        out(code1=code1, code2=code2, undo_files=len(undo), after_apply=after_apply,
            after_undo=len(completed(gone)), restored=ok, text2=text2,
            bytes=open(os.path.join(ROOT, rel), "rb").read().decode())
        """)
    assert (r["code1"], r["code2"]) == (0, 0)
    assert r["undo_files"] == 1
    assert r["after_apply"] == 0
    assert r["after_undo"] == 1 and r["restored"]
    assert r["bytes"] == "bring me back"
    assert "Restored 1 version(s)" in r["text2"]


def test_a_missing_tracked_folder_is_never_purged_without_force(run):
    r = run("""
        p = put("a.txt", b"x" * 100)
        snap(p)
        os.remove(p)
        os.rmdir(FOLDER)  # the whole tracked folder is gone, like an unmounted share
        code, text = run_tool("--apply", "--yes", "--min-age-days", "0")
        kept = len(completed(p))
        code_forced, _text = run_tool("--apply", "--yes", "--force", "--min-age-days", "0")
        out(code=code, text=text, kept_without_force=kept, purged_with_force=
            len(completed(p)) == 0, code_forced=code_forced)
        """)
    assert r["code"] == 0 and r["code_forced"] == 0
    assert r["kept_without_force"] == 1
    assert "tracked folder" in r["text"] and "is missing" in r["text"]
    assert r["purged_with_force"] is True


MENU_HELPER = """
    import builtins

    def drive_menu(*answers):
        feed = iter(answers)

        def fake_input(prompt=""):
            if "Press Enter" in prompt:
                return ""
            try:
                return next(feed)
            except StopIteration:
                raise EOFError from None

        builtins.input = fake_input
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = tool.interactive_menu(tool._build_parser().parse_args([]))
        return code, buf.getvalue()
"""


def _with_menu(body):
    return textwrap.dedent(MENU_HELPER) + "\n" + textwrap.dedent(body)


def test_the_menu_soft_deletes_and_undoes_against_the_real_engine(run):
    r = run(_with_menu("""
        put("sentinel.txt", b"keeps the tracked folder non-empty")
        gone = put("gone.txt", b"bring me back")
        snap(gone)
        os.remove(gone)
        # 5 = minimum age 0 (the version is milliseconds old), 2 = soft-delete (y),
        # 4 = undo the newest purge (1, y), 8 = exit
        code, text = drive_menu("5", "0", "2", "y", "4", "1", "y", "8")
        version_id = completed(gone)[0]["version_id"]
        ok, _msg, rel = vh.restore(gone, version_id)
        out(code=code, text=text, restored=ok,
            bytes=open(os.path.join(ROOT, rel), "rb").read().decode())
        """))
    assert r["code"] == 0 and r["restored"]
    assert r["bytes"] == "bring me back"
    assert "Soft-deleted 1 version(s)." in r["text"]
    assert "Restored 1 version(s); skipped 0" in r["text"]


def test_the_menu_can_free_the_disk_space_now_against_the_real_engine(run):
    r = run(_with_menu("""
        keep = put("keep.txt", b"keep me")
        gone = put("gone.txt", b"delete me " * 1000)
        snap(keep); snap(gone)
        os.remove(gone)
        before = eng._connect().execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        # 3 = soft-delete AND free now (y)
        code, text = drive_menu("5", "0", "3", "y", "8")
        after = eng._connect().execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        ok, _msg, rel = vh.restore(keep, completed(keep)[0]["version_id"])
        out(code=code, text=text, before=before, after=after, gone=len(completed(gone)),
            keep_restored=ok)
        """))
    assert r["code"] == 0 and r["keep_restored"]
    assert r["gone"] == 0
    assert r["after"] == r["before"] - 1
    assert "Freed 1 chunk(s)" in r["text"]
    assert "step 1 of 2: marking" in r["text"]
    assert "step 2 of 2: deleting 1 chunk file(s) from disk" in r["text"]
