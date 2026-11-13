"""
Application test for the Version Engine's background purge (5.45): the REAL Engine, in a scratch
copy of the source tree, on a real SQLite database and real files.

The pytest process never imports the application (config.py and paths.py read their JSON next to
the code and the engine opens databases): the source is copied into a temporary folder and a
small driver script runs there in a subprocess, prints one JSON line, and the assertions read it.
Nothing outside the temporary folder is touched (CLOUDINATOR_FTP_ROOT, the storage and database
folders and the tracked folder all live in it).

What it proves, with the real engine code:
  * a pass soft-deletes the versions of a file that is gone and writes an undo file first;
  * it never touches a file that still exists;
  * it never runs while the tracked folder is missing;
  * it is off when switched off (no pass, no thread);
  * the `ve-purge` thread stops promptly on the engine's shutdown, even in the middle of a
    throttle wait (a 2 s batch pause does not delay a shutdown);
  * the garbage collector and the purge's write phase never overlap (the maintenance lock).
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

pytestmark = pytest.mark.skipif(
    not (ROOT / "version_engine.py").is_file()
    or not (ROOT / "helpers" / "version_purge.py").is_file(),
    reason="version_engine.py or helpers/version_purge.py not found",
)

_DRIVER = r"""
import json, os, sqlite3, sys, threading, time

scratch, scenario = sys.argv[1], sys.argv[2]
sys.path.insert(0, scratch)
os.chdir(scratch)

import config

work = os.path.join(scratch, "work")
tracked = os.path.join(work, "tracked")
os.makedirs(tracked, exist_ok=True)
config.VERSION_STORAGE_DIR = os.path.join(work, "versions")
config.DB_DIR = os.path.join(work, "db")
config.VERSION_TRACK_DIRECTORIES = [tracked]
config.VERSION_TRACK_ROOTS = []
config.VERSION_TRACK_FILES = []
config.VERSION_TRACK_ALL_FILES = False
config.VERSION_SCAN_ENABLED = False
config.VERSION_WATCH_ENABLED = False
config.VERSION_WORKER_COUNT = 1
config.VERSION_GC_ENABLED = True
config.VERSION_GC_GRACE_PERIOD = 86400
config.VERSION_PURGE_MISSING_ENABLED = scenario != "disabled"
config.VERSION_PURGE_MISSING_MIN_AGE_DAYS = 0
config.VERSION_PURGE_MISSING_INTERVAL = 60
config.VERSION_PURGE_MISSING_MAX_FILES_PER_PASS = 1000
config.VERSION_PURGE_MISSING_BATCH_PAUSE = 0

import version_engine as ve

engine = ve.Engine()
engine._ensure_dirs()
engine._bootstrap_schema()


def write(name, text):
    path = os.path.join(tracked, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def statuses():
    db = sqlite3.connect(engine.db_path)
    try:
        return {
            os.path.basename(p): sorted(set(s.split(",")))
            for p, s in db.execute(
                "SELECT f.path, GROUP_CONCAT(v.status) FROM files f "
                "JOIN versions v ON v.file_id = f.file_id GROUP BY f.file_id"
            )
        }
    finally:
        db.close()


def undo_files():
    return sorted(
        n for n in os.listdir(engine.storage_dir) if n.startswith("purge_undo_auto_")
    )


def result_dict(r):
    return None if r is None else dict(r.__dict__)


out = {"scenario": scenario}

if scenario == "purge":
    keep = write("keep.txt", "keep v1")
    gone = write("gone.txt", "gone v1")
    engine.snapshot_file(keep)
    engine.snapshot_file(gone)
    write("gone.txt", "gone v2, longer")
    engine.snapshot_file(gone)
    os.remove(gone)
    out["before"] = statuses()
    out["result"] = result_dict(engine.run_purge_missing_pass())
    out["after"] = statuses()
    out["undo_files"] = undo_files()
    out["cursor_meta"] = engine._get_meta("purge_missing_cursor")
    out["last_meta"] = engine._get_meta("purge_missing_last")
    if out["undo_files"]:
        with open(os.path.join(engine.storage_dir, out["undo_files"][0])) as f:
            out["undo_ids"] = json.load(f)["version_ids"]

elif scenario == "missing_folder":
    keep = write("keep.txt", "keep v1")
    engine.snapshot_file(keep)
    os.rename(tracked, tracked + "_away")  # the tracked folder (a share) is gone
    out["result"] = result_dict(engine.run_purge_missing_pass())
    out["after"] = statuses()
    out["undo_files"] = undo_files()

elif scenario == "disabled":
    out["result"] = result_dict(engine.run_purge_missing_pass())
    engine.start()
    out["threads"] = sorted(t.name for t in threading.enumerate())
    engine.graceful_shutdown()

elif scenario == "stop":
    write("anchor.txt", "the tracked folder is not empty")
    db = sqlite3.connect(engine.db_path, isolation_level=None)
    old = time.time() - 90 * 86400
    for i in range(600):
        cur = db.execute(
            "INSERT INTO files(path, norm_key, tracking_source, created_at, last_seen_at) "
            "VALUES (?, ?, 'directory', ?, ?)",
            (os.path.join(tracked, "gone%d.txt" % i), "gone%d" % i, old, old),
        )
        db.execute(
            "INSERT INTO versions(file_id, sha256, size, storage_mode, status, created_at) "
            "VALUES (?, 'x', 1, 'full', 'completed', ?)",
            (cur.lastrowid, old),
        )
    db.close()
    config.VERSION_PURGE_MISSING_BATCH_PAUSE = 2.0  # a long throttle wait after each slice
    ve._PURGE_START_DELAY = 0
    engine.start()
    time.sleep(0.8)  # the first slice is done, the thread is inside its 2 s wait
    out["alive_before"] = any(
        t.name == "ve-purge" and t.is_alive() for t in threading.enumerate()
    )
    started = time.monotonic()
    engine.graceful_shutdown()
    out["shutdown_seconds"] = time.monotonic() - started
    out["alive_after"] = any(
        t.name == "ve-purge" and t.is_alive() for t in threading.enumerate()
    )
    db = sqlite3.connect(engine.db_path)
    out["deleted"] = db.execute(
        "SELECT COUNT(*) FROM versions WHERE status='deleted'"
    ).fetchone()[0]
    out["completed"] = db.execute(
        "SELECT COUNT(*) FROM versions WHERE status='completed'"
    ).fetchone()[0]
    db.close()

elif scenario == "gc_lock":
    keep = write("keep.txt", "keep")
    gone = write("gone.txt", "gone")
    engine.snapshot_file(keep)
    engine.snapshot_file(gone)
    os.remove(gone)
    box = {}

    def run_gc():
        t0 = time.monotonic()
        engine.run_gc()
        box["gc_seconds"] = time.monotonic() - t0

    def run_purge():
        t0 = time.monotonic()
        box["purge_result"] = result_dict(engine.run_purge_missing_pass())
        box["purge_seconds"] = time.monotonic() - t0

    engine._maintenance_lock.acquire()  # "the garbage collector is running"
    threads = [threading.Thread(target=run_gc), threading.Thread(target=run_purge)]
    for t in threads:
        t.start()
    time.sleep(0.8)
    out["finished_while_locked"] = [not t.is_alive() for t in threads]
    out["gone_while_locked"] = statuses().get("gone.txt")
    engine._maintenance_lock.release()
    for t in threads:
        t.join(timeout=30)
    out.update(box)
    out["gone_after"] = statuses().get("gone.txt")

print("RESULT:" + json.dumps(out))
"""


def _scratch(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for f in ROOT.glob("*.py"):
        shutil.copy2(f, scratch / f.name)
    shutil.copytree(
        ROOT / "helpers",
        scratch / "helpers",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (scratch / "driver.py").write_text(_DRIVER, encoding="utf-8")
    return scratch


def _run(tmp_path, scenario):
    scratch = _scratch(tmp_path)
    env = dict(os.environ)
    env["CLOUDINATOR_FTP_ROOT"] = str(scratch / "ftp_root")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "driver.py", str(scratch), scenario],
        cwd=str(scratch),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT:")]
    assert lines, (proc.returncode, proc.stdout[-2000:], proc.stderr[-2000:])
    return json.loads(lines[-1][len("RESULT:") :])


def test_a_pass_purges_the_deleted_file_and_never_touches_the_existing_one(tmp_path):
    out = _run(tmp_path, "purge")
    assert out["before"] == {"keep.txt": ["completed"], "gone.txt": ["completed"]}
    assert out["after"] == {"keep.txt": ["completed"], "gone.txt": ["deleted"]}
    result = out["result"]
    assert result["status"] == "completed"
    assert result["purged_files"] == 1 and result["purged_versions"] == 2
    assert result["present"] == 1  # keep.txt was looked at and left alone
    # the undo record exists, lists exactly the soft-deleted versions, and the pass is logged
    assert len(out["undo_files"]) == 1
    assert len(out["undo_ids"]) == 2
    assert (
        out["cursor_meta"] == "0"
    )  # the whole table was looked at: the sweep starts over
    assert "purged_versions=2" in out["last_meta"]


def test_a_pass_never_runs_while_the_tracked_folder_is_missing(tmp_path):
    out = _run(tmp_path, "missing_folder")
    assert out["result"]["status"] == "skipped"
    assert "missing" in out["result"]["reason"]
    assert out["after"] == {"keep.txt": ["completed"]}  # nothing was purged
    assert out["undo_files"] == []  # and no undo file was even written


def test_the_purge_is_off_when_switched_off_and_starts_no_thread(tmp_path):
    out = _run(tmp_path, "disabled")
    assert out["result"] is None
    assert "ve-purge" not in out["threads"]
    assert "ve-worker-0" in out["threads"]  # the engine itself did start


def test_the_purge_thread_stops_promptly_on_shutdown_even_inside_a_throttle_wait(
    tmp_path,
):
    out = _run(tmp_path, "stop")
    assert out["alive_before"] is True
    assert (
        out["shutdown_seconds"] < 5
    )  # far below the 2 s pauses and VERSION_SHUTDOWN_TIMEOUT
    assert out["alive_after"] is False
    # it was still checking (the writes come after the checks): nothing was half-done
    assert out["deleted"] == 0 and out["completed"] == 600


def test_the_garbage_collector_and_the_purge_never_overlap(tmp_path):
    out = _run(tmp_path, "gc_lock")
    # while "the GC" holds the maintenance lock neither run_gc nor the purge's write phase ends
    assert out["gone_while_locked"] == ["completed"]
    assert out["finished_while_locked"][0] is False  # run_gc waits for the lock
    assert out["finished_while_locked"][1] is False  # the write phase waits for it
    # once it is released both finish, and the purge did its work
    assert out["purge_result"]["status"] == "completed"
    assert out["gone_after"] == ["deleted"]
    assert out["gc_seconds"] >= 0.7 and out["purge_seconds"] >= 0.7
