#!/usr/bin/env python3
"""
version_engine.py — Universal File Versioning Engine for CloudinatorFTP
=========================================================================

This single file is BOTH:

  A. The parent-process integration API, imported by dev_server.py and
     prod_server.py only:

         import version_engine
         version_engine.start()        # idempotent
         version_engine.stop()         # graceful
         version_engine.force_kill()   # immediate, signal-handler-safe
         version_engine.status()       # dict

  B. The child-process worker entry point, run directly:

         python version_engine.py --worker

Process architecture (mirrors protocol_manager.py's WebDAV subprocess
pattern EXACTLY — see _spawn_version_engine_process() below, which is a
close copy of protocol_manager._spawn_webdav_process()):

    dev_server.py / prod_server.py (parent / launcher)
        └── version_engine.start()
                └── subprocess.Popen([sys.executable, "version_engine.py", "--worker"])
                        (separate OS process — its own DB connections,
                         its own watcher/scanner/worker threads; never
                         shares the Quart/Hypercorn event loop)

Importing this module MUST NOT start anything — no process, thread,
watcher, scanner, or job loop starts merely from `import version_engine`.
Only an explicit call to start() (parent side) or running this file with
--worker (child side) does that.

protocol_manager.py has ZERO references to this module — it stays
protocol-only (WebDAV/SFTP/FTP/SMB). The only callers of
start()/stop()/force_kill() are dev_server.py and prod_server.py.

Design decisions explicitly recorded (see CLAUDE.md for the full log):
  - No watchdog/auto-respawn thread (unlike WebDAV's _webdav_watchdog()).
    A crashed Version Engine is expected to be repaired by crash recovery
    on the NEXT start(), not silently respawned — a bad respawn loop could
    mask a real problem such as a corrupt DB or a full disk.
  - The watcher is a lightweight polling loop (stat-based: mtime+size),
    not an OS-level filesystem-event watcher (inotify/ReadDirectoryChangesW/
    FSEvents), since this repo has no `watchdog`-package dependency today.
    It still satisfies "watcher + scanner, not watcher alone": the watcher
    polls on a SHORT interval (see _WATCH_POLL_INTERVAL) for fast reaction,
    the scanner reconciles on the slower, configurable
    config.VERSION_SCAN_INTERVAL and also discovers brand-new files. The
    engine works correctly with the watcher disabled — the scanner alone
    still eventually catches everything.
"""

import argparse
import atexit
import fnmatch
import hashlib
import json
import os
import queue
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import config
import paths
import logging_setup

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_PATH = os.path.join(_PROJECT_DIR, "version_engine.py")

_ENGINE_VERSION = "1.0.0"
_SCHEMA_VERSION = 1

# How often the (optional) watcher polls tracked paths for changes. Not a
# config.py setting — this is an internal implementation constant for the
# stat-polling loop, distinct from config.VERSION_SCAN_INTERVAL (the full
# reconciliation scanner's interval, which IS configurable).
_WATCH_POLL_INTERVAL = 3  # seconds

_VERSION_STATES = (
    "pending",
    "processing",
    "verifying",
    "completed",
    "failed",
    "deleted",
)


# =============================================================================
# A. PARENT-PROCESS API  (imported by dev_server.py / prod_server.py ONLY)
# =============================================================================

_version_engine_proc = None
_version_engine_proc_lock = threading.Lock()
_ve_pm_logger = None


def _pm_log():
    global _ve_pm_logger
    if _ve_pm_logger is None:
        _ve_pm_logger = logging_setup.get_logger("version_engine.parent")
    return _ve_pm_logger


def _pump_child_output(stream, tag: str) -> None:
    """Relay the child's stdout/stderr lines into this (parent) process's
    own log stream, exactly mirroring protocol_manager._pump_child_output
    so Version Engine's output lands in the same daily log file rather
    than vanishing or opening a second console."""
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            _pm_log().info(f"[version_engine:{tag}] {line.rstrip()}")
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


_PID_DIR = os.path.join(_PROJECT_DIR, ".manage_pids")
_VE_PID_FILE = os.path.join(_PID_DIR, "version_engine.pid")


def _write_ve_pidfile(pid: int):
    """Optional — mirrors protocol_manager._write_webdav_pidfile(). Not
    required for correctness (start()/stop()/status() all work purely off
    the in-process Popen handle); exists only so external tooling in the
    same style as manage.sh can find the pid without talking to this
    module directly."""
    try:
        os.makedirs(_PID_DIR, exist_ok=True)
        with open(_VE_PID_FILE, "w") as f:
            f.write(str(pid))
    except Exception:
        pass


def _clear_ve_pidfile():
    try:
        os.remove(_VE_PID_FILE)
    except OSError:
        pass


def _spawn_version_engine_process():
    """Launch version_engine.py --worker as an independent OS process.

    This is a deliberate close copy of
    protocol_manager._spawn_webdav_process() — same stdio handling, same
    env vars, same Windows console-window fix, same reasoning. See that
    function's docstring for the full rationale; not re-derived here.
    Returns the Popen handle, or None if the launch failed.
    """
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW

    env = dict(os.environ)
    # Same daily log file as the parent, not a second one — see
    # logging_setup.py's CLOUDINATOR_LOG_PREFIX mechanism.
    env["CLOUDINATOR_LOG_PREFIX"] = logging_setup._LOG_PREFIX
    # Unconditional (not just Windows) — see protocol_manager.py's
    # _spawn_webdav_process for the emoji/cp1252 root-cause writeup this
    # avoids; Version Engine's own logging prints similarly non-ASCII text.
    env["PYTHONUTF8"] = "1"

    try:
        proc = subprocess.Popen(
            [sys.executable, _SCRIPT_PATH, "--worker"],
            cwd=_PROJECT_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            **kw,
        )
    except Exception as e:
        print(f"❌ Version Engine: failed to launch subprocess: {e}")
        return None

    threading.Thread(
        target=_pump_child_output, args=(proc.stdout, "OUT"), daemon=True
    ).start()
    threading.Thread(
        target=_pump_child_output, args=(proc.stderr, "ERR"), daemon=True
    ).start()
    _write_ve_pidfile(proc.pid)
    return proc


def start():
    """Idempotent. Spawns the Version Engine child process if
    VERSION_ENGINE_ENABLED and no live handle is already held. Calling
    this repeatedly results in exactly one child process."""
    global _version_engine_proc

    if not getattr(config, "VERSION_ENGINE_ENABLED", True):
        _pm_log().info(
            "Version Engine disabled (VERSION_ENGINE_ENABLED=False) — not starting."
        )
        return False

    with _version_engine_proc_lock:
        if _version_engine_proc is not None and _version_engine_proc.poll() is None:
            # Already running — no-op, per §5.
            return True
        _version_engine_proc = _spawn_version_engine_process()
        ok = _version_engine_proc is not None
        if ok:
            print(
                f"🕓 Version Engine: started (pid {_version_engine_proc.pid}, isolated process)"
            )
        return ok


def stop():
    """Graceful stop: SIGTERM/terminate(), wait up to
    config.VERSION_SHUTDOWN_TIMEOUT, fall back to kill() on timeout.
    Mirrors protocol_manager.stop_all()'s WebDAV-termination half exactly.
    The actual graceful drain (finish in-flight jobs, close DB) happens
    INSIDE the child in response to the signal — see _worker_main()'s
    signal handler."""
    global _version_engine_proc
    with _version_engine_proc_lock:
        proc = _version_engine_proc
        _version_engine_proc = None
    if proc is not None and proc.poll() is None:
        timeout = getattr(config, "VERSION_SHUTDOWN_TIMEOUT", 30)
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception as e:
            _pm_log().debug(f"Stop error for version_engine subprocess: {e}")
    _clear_ve_pidfile()


def force_kill():
    """Fast, no-wait kill — safe to call from a signal handler right
    before os._exit(). Mirrors protocol_manager.force_kill_webdav()
    exactly: a subprocess (unlike SFTP/FTP/SMB's in-process threads)
    does not die automatically when its parent exits via os._exit()."""
    try:
        with _version_engine_proc_lock:
            proc = _version_engine_proc
        if proc is not None and proc.poll() is None:
            proc.kill()
    except Exception:
        pass


def status() -> dict:
    """Return engine status. Process liveness comes from the held Popen
    handle; job/watcher/scanner counters are read directly from the
    child's own SQLite DB (safe: SQLite WAL mode supports concurrent
    readers from a different process; this parent-side connection is a
    fresh, independent one — see CLAUDE.md's database.py note for why it
    can't and shouldn't share the child's in-process connection/locks)."""
    with _version_engine_proc_lock:
        proc = _version_engine_proc
    enabled = getattr(config, "VERSION_ENGINE_ENABLED", True)
    running = (proc is not None) and (proc.poll() is None)
    pid = proc.pid if (proc is not None and running) else None

    result = {
        "enabled": enabled,
        "running": running,
        "pid": pid,
        "worker_count": getattr(config, "VERSION_WORKER_COUNT", 1),
        "watcher_running": False,
        "scanner_running": False,
        "pending_jobs": 0,
        "active_jobs": 0,
        "failed_jobs": 0,
        "last_scan": None,
        "storage_path": getattr(config, "VERSION_STORAGE_DIR", None),
        "database_path": os.path.join(
            getattr(config, "DB_DIR", ""),
            getattr(config, "VERSION_DB_FILENAME", "version_engine.sqlite3"),
        ),
    }

    db_path = result["database_path"]
    if db_path and os.path.exists(db_path):
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
            try:
                cur = conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
                counts = dict(cur.fetchall())
                result["pending_jobs"] = counts.get("pending", 0)
                result["active_jobs"] = counts.get("processing", 0) + counts.get(
                    "verifying", 0
                )
                result["failed_jobs"] = counts.get("failed", 0)
                meta = dict(
                    conn.execute("SELECT key, value FROM engine_metadata").fetchall()
                )
                result["watcher_running"] = meta.get("watcher_running") == "1"
                result["scanner_running"] = meta.get("scanner_running") == "1"
                result["last_scan"] = meta.get("last_scan")
            finally:
                conn.close()
        except Exception:
            pass  # DB not ready yet / mid-bootstrap — status stays at defaults

    return result


# =============================================================================
# B. CHILD-PROCESS WORKER — SQLite schema, storage, engine logic
# =============================================================================

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS engine_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS files (
    file_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    path          TEXT NOT NULL,       -- display path, original case
    norm_key      TEXT NOT NULL UNIQUE,-- normalized dedup key (see _normalize_path)
    tracking_source TEXT NOT NULL,     -- 'file' | 'directory' | 'root'
    created_at    REAL NOT NULL,
    last_seen_at  REAL NOT NULL,
    deleted       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS versions (
    version_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id       INTEGER NOT NULL REFERENCES files(file_id),
    sha256        TEXT NOT NULL,
    size          INTEGER NOT NULL,
    storage_mode  TEXT NOT NULL,       -- 'full' | 'chunked'
    status        TEXT NOT NULL,       -- pending|processing|verifying|completed|failed|deleted
    created_at    REAL NOT NULL,
    completed_at  REAL,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_versions_file ON versions(file_id, status, created_at);

CREATE TABLE IF NOT EXISTS objects (
    sha256        TEXT PRIMARY KEY,
    size          INTEGER NOT NULL,
    created_at    REAL NOT NULL,
    orphaned_since REAL
);

CREATE TABLE IF NOT EXISTS version_objects (
    version_id    INTEGER NOT NULL REFERENCES versions(version_id),
    chunk_index   INTEGER NOT NULL,
    sha256        TEXT NOT NULL REFERENCES objects(sha256),
    PRIMARY KEY (version_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_version_objects_sha ON version_objects(sha256);

CREATE TABLE IF NOT EXISTS jobs (
    job_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    operation     TEXT NOT NULL,       -- snapshot|restore|verify|scan|retention|gc
    file_id       INTEGER,
    version_id    INTEGER,
    status        TEXT NOT NULL,       -- pending|processing|verifying|completed|failed
    progress      REAL NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    started_at    REAL,
    finished_at   REAL,
    retry_count   INTEGER NOT NULL DEFAULT 0,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS tracked_paths (
    path          TEXT NOT NULL,
    kind          TEXT NOT NULL,       -- 'file' | 'directory' | 'root'
    added_at      REAL NOT NULL,
    PRIMARY KEY (path, kind)
);
"""


def _normalize_path(path_str: str) -> str:
    """Robust equivalent-path normalization (spec §14). Trailing
    separators are always stripped. Case-folding is applied ONLY on
    Windows (NTFS is case-insensitive) — Linux/Termux filesystems are
    case-sensitive, so folding case there would wrongly merge distinct
    files. This is the dedup key; the display path keeps real case."""
    p = os.path.abspath(os.path.expanduser(path_str))
    p = p.rstrip(os.sep)
    if os.altsep:
        p = p.rstrip(os.altsep)
    if sys.platform == "win32":
        p = p.lower()
    return p


def sha256_stream(fileobj, chunk_size=1024 * 1024):
    """Stream-hash a file object without loading it fully into memory."""
    h = hashlib.sha256()
    while True:
        buf = fileobj.read(chunk_size)
        if not buf:
            break
        h.update(buf)
    return h.hexdigest()


class VersionEngineError(Exception):
    pass


class Engine:
    """The Version Engine's core logic. One instance lives inside the
    worker process; not imported/instantiated by the parent process."""

    def __init__(self):
        self.log = logging_setup.get_logger("version_engine")
        self.storage_dir = config.VERSION_STORAGE_DIR
        self.objects_dir = os.path.join(self.storage_dir, "objects")
        self.tmp_dir = os.path.join(self.storage_dir, "tmp")
        self.db_path = os.path.join(config.DB_DIR, config.VERSION_DB_FILENAME)

        self._shutdown_event = threading.Event()
        self._stop_scheduling = threading.Event()
        self._job_queue = queue.Queue()
        self._workers = []
        self._watcher_thread = None
        self._scanner_thread = None
        self._known_state = (
            {}
        )  # norm_key -> (mtime, size) — watcher/scanner fast-path cache
        self._pending_norm_keys = set()  # debounce: don't double-enqueue
        self._pending_lock = threading.Lock()

        self._conn_local = threading.local()

        self._watcher_running = False
        self._scanner_running = False

    # ------------------------------------------------------------------
    # Storage bootstrap + DB
    # ------------------------------------------------------------------

    def _ensure_dirs(self):
        os.makedirs(self.storage_dir, exist_ok=True)
        os.makedirs(self.objects_dir, exist_ok=True)
        os.makedirs(self.tmp_dir, exist_ok=True)
        os.makedirs(config.DB_DIR, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """One connection per thread (watcher/scanner/each worker) —
        mirrors database.py's check_same_thread=False + WAL + foreign_keys
        pattern, but this is an entirely separate DB file/connection: see
        CLAUDE.md for why version_engine.py must never import database.py
        or share its module-level lock objects (different process)."""
        conn = getattr(self._conn_local, "conn", None)
        if conn is not None:
            return conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        self._conn_local.conn = conn
        return conn

    def _bootstrap_schema(self):
        # threading.Lock is correct and sufficient here (not a
        # cross-process lock) — schema init happens once, early, in the
        # main worker thread before watcher/scanner/worker threads start,
        # so there is no genuine race to guard against beyond SQLite's own
        # WAL-snapshot-isolation trap documented in database.py's
        # _connect(): CREATE TABLE must be committed before any other
        # connection (even one opened later in this same process) can see
        # it, so this is called from __main__ before any thread opens its
        # own connection.
        conn = self._connect()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

        row = conn.execute(
            "SELECT value FROM engine_metadata WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO engine_metadata(key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT INTO engine_metadata(key, value) VALUES ('engine_version', ?)",
                (_ENGINE_VERSION,),
            )
            conn.commit()
        # else: forward-compat — a future version bump would migrate here.

    def _set_meta(self, key, value):
        conn = self._connect()
        conn.execute(
            "INSERT INTO engine_metadata(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Crash recovery (spec §14 "Crash recovery") — run once at startup,
    # BEFORE watcher/scanner/workers start. Load-bearing on Termux, where
    # the process can be suspended/killed with no graceful signal at all
    # (spec §13) — this must fully repair state without ever having seen
    # a clean stop() run first.
    # ------------------------------------------------------------------

    def _crash_recovery(self):
        conn = self._connect()

        # 1. Any job left in a non-terminal state from a previous run was
        #    interrupted — mark it failed. Never silently "resume" a job;
        #    the next scan naturally re-creates a fresh snapshot job for
        #    any file whose hash still doesn't match its latest completed
        #    version, so no real work is lost, only redone.
        n = conn.execute(
            "UPDATE jobs SET status='failed', finished_at=?, "
            "error='interrupted (crash recovery)' "
            "WHERE status IN ('pending','processing','verifying')",
            (time.time(),),
        ).rowcount
        if n:
            self.log.info(f"Crash recovery: marked {n} stale job(s) failed.")

        # 2. Any version left non-terminal is, by definition, NOT safe to
        #    treat as completed — a crash mid-hash/mid-chunk-write must
        #    never leave a falsely-`completed` version (core invariant).
        n = conn.execute(
            "UPDATE versions SET status='failed', error='interrupted (crash recovery)' "
            "WHERE status IN ('pending','processing','verifying')"
        ).rowcount
        if n:
            self.log.info(f"Crash recovery: marked {n} stale version(s) failed.")
        conn.commit()

        # 3. Stale temp files: anything left in tmp_dir is, by construction,
        #    an incomplete write (finished writes are renamed OUT of
        #    tmp_dir atomically) — always safe to delete unconditionally.
        cleaned = 0
        try:
            for name in os.listdir(self.tmp_dir):
                try:
                    os.remove(os.path.join(self.tmp_dir, name))
                    cleaned += 1
                except OSError:
                    pass
        except OSError:
            pass
        if cleaned:
            self.log.info(f"Crash recovery: removed {cleaned} stale temp file(s).")

        # 4. Validate completed-version metadata still has its objects on
        #    disk (defends against a manually/externally deleted object).
        rows = conn.execute(
            "SELECT DISTINCT vo.sha256 AS sha256 FROM version_objects vo "
            "JOIN versions v ON v.version_id = vo.version_id "
            "WHERE v.status='completed'"
        ).fetchall()
        missing = 0
        for row in rows:
            if not os.path.exists(self._object_path(row["sha256"])):
                missing += 1
        if missing:
            self.log.warning(
                f"Crash recovery: {missing} referenced object(s) missing from storage — "
                "affected versions will fail integrity checks on restore."
            )

    # ------------------------------------------------------------------
    # Content-addressed object storage
    # ------------------------------------------------------------------

    def _object_path(self, sha256_hex: str) -> str:
        return os.path.join(self.objects_dir, sha256_hex[:2], sha256_hex)

    def _store_object_from_tmp(self, tmp_path: str, sha256_hex: str, size: int):
        """Atomically publish a fully-written temp file as the
        content-addressed object for `sha256_hex`. Dedup: if the object
        already exists on disk, the incoming tmp is just discarded — the
        existing bytes are already known-good (verified when THEY were
        written)."""
        final_path = self._object_path(sha256_hex)
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        if os.path.exists(final_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        else:
            os.replace(tmp_path, final_path)  # atomic on the same filesystem

        conn = self._connect()
        conn.execute(
            "INSERT INTO objects(sha256, size, created_at, orphaned_since) "
            "VALUES (?, ?, ?, NULL) "
            "ON CONFLICT(sha256) DO UPDATE SET orphaned_since=NULL",
            (sha256_hex, size, time.time()),
        )
        conn.commit()

    def _verify_object(self, sha256_hex: str) -> bool:
        """Integrity check: hash-verify an object on read (spec:
        'every object is hash-verified on read; reject missing/truncated/
        corrupted/hash-mismatched objects')."""
        path = self._object_path(sha256_hex)
        if not os.path.exists(path):
            return False
        with open(path, "rb") as f:
            actual = sha256_stream(f)
        return actual == sha256_hex

    # ------------------------------------------------------------------
    # Tracking scope resolution (spec §14)
    # ------------------------------------------------------------------

    def _is_excluded_dir(self, dirpath: str) -> bool:
        base = os.path.basename(dirpath)
        for pat in config.VERSION_EXCLUDE_DIRECTORIES:
            if base == pat or dirpath == os.path.abspath(os.path.expanduser(pat)):
                return True
        return False

    def _is_excluded_file(self, filepath: str) -> bool:
        base = os.path.basename(filepath)
        for pat in config.VERSION_EXCLUDE_PATTERNS:
            if fnmatch.fnmatch(base, pat):
                return True
        return False

    def _walk_eligible(self, root: str):
        """Recursively yield eligible file paths under `root`, honoring
        excludes and the symlink policy. Guards against symlink cycles
        with a visited-realpaths set when VERSION_FOLLOW_SYMLINKS is on."""
        visited_dirs = set()
        stack = [root]
        while stack:
            current = stack.pop()
            if os.path.islink(current):
                if not config.VERSION_FOLLOW_SYMLINKS:
                    continue
                real = os.path.realpath(current)
                if real in visited_dirs:
                    continue  # cycle guard
                visited_dirs.add(real)
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=config.VERSION_FOLLOW_SYMLINKS):
                        if self._is_excluded_dir(entry.path):
                            continue
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=config.VERSION_FOLLOW_SYMLINKS):
                        if self._is_excluded_file(entry.path):
                            continue
                        yield entry.path
                except OSError:
                    continue

    def get_eligible_files(self):
        """Return the set of normalized-eligible (display_path) tuples
        currently in scope, per config's tracking lists. Dedup'd by
        normalized key."""
        seen = {}  # norm_key -> display_path

        for f in config.VERSION_TRACK_FILES:
            fp = os.path.abspath(os.path.expanduser(f))
            if os.path.isfile(fp) and not self._is_excluded_file(fp):
                seen[_normalize_path(fp)] = fp

        for d in config.VERSION_TRACK_DIRECTORIES:
            dp = os.path.abspath(os.path.expanduser(d))
            if os.path.isdir(dp):
                for fp in self._walk_eligible(dp):
                    seen[_normalize_path(fp)] = fp

        if config.VERSION_TRACK_ALL_FILES:
            for r in config.VERSION_TRACK_ROOTS:
                rp = os.path.abspath(os.path.expanduser(r))
                if os.path.isdir(rp):
                    for fp in self._walk_eligible(rp):
                        seen[_normalize_path(fp)] = fp

        return seen  # {norm_key: display_path}

    def _sync_tracked_paths_table(self):
        conn = self._connect()
        conn.execute("DELETE FROM tracked_paths")
        now = time.time()
        for f in config.VERSION_TRACK_FILES:
            conn.execute(
                "INSERT OR IGNORE INTO tracked_paths(path, kind, added_at) VALUES (?, 'file', ?)",
                (f, now),
            )
        for d in config.VERSION_TRACK_DIRECTORIES:
            conn.execute(
                "INSERT OR IGNORE INTO tracked_paths(path, kind, added_at) VALUES (?, 'directory', ?)",
                (d, now),
            )
        for r in config.VERSION_TRACK_ROOTS:
            conn.execute(
                "INSERT OR IGNORE INTO tracked_paths(path, kind, added_at) VALUES (?, 'root', ?)",
                (r, now),
            )
        conn.commit()

    # ------------------------------------------------------------------
    # files/ table helpers
    # ------------------------------------------------------------------

    def _get_or_create_file(self, display_path: str, source: str) -> int:
        conn = self._connect()
        norm_key = _normalize_path(display_path)
        row = conn.execute(
            "SELECT file_id FROM files WHERE norm_key=?", (norm_key,)
        ).fetchone()
        now = time.time()
        if row:
            conn.execute(
                "UPDATE files SET last_seen_at=?, deleted=0 WHERE file_id=?",
                (now, row["file_id"]),
            )
            conn.commit()
            return row["file_id"]
        cur = conn.execute(
            "INSERT INTO files(path, norm_key, tracking_source, created_at, last_seen_at, deleted) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (display_path, norm_key, source, now, now),
        )
        conn.commit()
        return cur.lastrowid

    def _latest_completed_sha(self, file_id: int):
        conn = self._connect()
        row = conn.execute(
            "SELECT sha256 FROM versions WHERE file_id=? AND status='completed' "
            "ORDER BY created_at DESC LIMIT 1",
            (file_id,),
        ).fetchone()
        return row["sha256"] if row else None

    # ------------------------------------------------------------------
    # Snapshot (the core "create a version" operation)
    # ------------------------------------------------------------------

    def snapshot_file(self, display_path: str, source: str = "scan"):
        """Universal, format-agnostic: every file is treated as an opaque
        byte stream. Never branches on extension. SHA-256 is the sole
        identity; if it matches the latest completed version, this is a
        no-op (skip, no redundant version)."""
        job_id = self._create_job("snapshot", file_id=None)
        conn = self._connect()
        try:
            if not os.path.isfile(display_path):
                self._finish_job(job_id, "failed", error="source file no longer exists")
                return None
            if os.path.islink(display_path) and not config.VERSION_FOLLOW_SYMLINKS:
                self._finish_job(
                    job_id, "failed", error="symlink (VERSION_FOLLOW_SYMLINKS=False)"
                )
                return None

            file_id = self._get_or_create_file(display_path, source)
            conn.execute("UPDATE jobs SET file_id=? WHERE job_id=?", (file_id, job_id))
            conn.commit()

            last_error = None
            for attempt in range(config.VERSION_RETRY_COUNT + 1):
                try:
                    result = self._attempt_snapshot(file_id, display_path, job_id)
                    if result is None:
                        self._finish_job(
                            job_id, "completed"
                        )  # dedup skip — not an error
                    else:
                        self._finish_job(job_id, "completed", version_id=result)
                        self._apply_retention(file_id)
                    return result
                except _SourceChangedDuringCapture as e:
                    last_error = str(e)
                    self.log.info(
                        f"Snapshot retry {attempt + 1}/{config.VERSION_RETRY_COUNT} for "
                        f"{display_path}: source changed during capture"
                    )
                    time.sleep(config.VERSION_RETRY_DELAY)
                except Exception as e:
                    last_error = str(e)
                    self.log.error(f"Snapshot failed for {display_path}: {e}")
                    break

            self._finish_job(job_id, "failed", error=last_error or "unknown error")
            return None
        finally:
            with self._pending_lock:
                self._pending_norm_keys.discard(_normalize_path(display_path))

    def _attempt_snapshot(self, file_id: int, display_path: str, job_id: int):
        conn = self._connect()
        try:
            stat_before = os.stat(display_path)
        except OSError as e:
            raise VersionEngineError(f"stat failed: {e}")

        small = stat_before.st_size <= config.VERSION_SMALL_FILE_THRESHOLD
        version_id = self._create_version_row(file_id, "full" if small else "chunked")
        self._set_job_version(job_id, version_id)

        try:
            if small:
                sha, size = self._capture_full(display_path, version_id)
            else:
                sha, size = self._capture_chunked(display_path, version_id)
        except Exception:
            self._mark_version_failed(version_id, "capture error")
            raise

        try:
            stat_after = os.stat(display_path)
        except OSError as e:
            self._mark_version_failed(version_id, f"stat failed after capture: {e}")
            raise VersionEngineError(str(e))

        if (
            stat_after.st_mtime != stat_before.st_mtime
            or stat_after.st_size != stat_before.st_size
        ):
            self._mark_version_failed(version_id, "source changed during capture")
            raise _SourceChangedDuringCapture(display_path)

        # Whole-file identity check — dedup against the latest completed version.
        latest = self._latest_completed_sha(file_id)
        if latest == sha:
            # Redundant — discard this version row, no new snapshot needed.
            conn.execute(
                "DELETE FROM version_objects WHERE version_id=?", (version_id,)
            )
            conn.execute("DELETE FROM versions WHERE version_id=?", (version_id,))
            conn.commit()
            self.log.debug(f"Snapshot skipped (unchanged): {display_path}")
            return None

        conn.execute(
            "UPDATE versions SET sha256=?, size=?, status='completed', completed_at=? "
            "WHERE version_id=?",
            (sha, size, time.time(), version_id),
        )
        conn.commit()
        self.log.info(f"Snapshot created: {display_path} ({sha[:12]}…, {size} bytes)")
        return version_id

    def _capture_full(self, display_path: str, version_id: int):
        """Full-object mode: stream the whole file into one content-
        addressed object (still streamed, never loaded fully into a
        single bytes blob, even though it's under the small-file
        threshold — keeps one code path's memory behavior consistent)."""
        conn = self._connect()
        conn.execute(
            "UPDATE versions SET status='processing' WHERE version_id=?", (version_id,)
        )
        conn.commit()

        fd, tmp_path = tempfile.mkstemp(dir=self.tmp_dir, prefix="obj_")
        h = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(fd, "wb") as out, open(display_path, "rb") as src:
                while True:
                    buf = src.read(1024 * 1024)
                    if not buf:
                        break
                    h.update(buf)
                    out.write(buf)
                    size += len(buf)
                out.flush()
                os.fsync(out.fileno())
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

        conn.execute(
            "UPDATE versions SET status='verifying' WHERE version_id=?", (version_id,)
        )
        conn.commit()

        sha = h.hexdigest()
        self._store_object_from_tmp(tmp_path, sha, size)
        conn.execute(
            "INSERT OR IGNORE INTO version_objects(version_id, chunk_index, sha256) VALUES (?, 0, ?)",
            (version_id, sha),
        )
        conn.commit()
        return sha, size

    def _capture_chunked(self, display_path: str, version_id: int):
        """Chunked mode (FixedSizeChunker): stream the file in
        config.VERSION_CHUNK_SIZE pieces, hashing each chunk (for content-
        addressed storage / cross-file dedup) AND the whole file (for
        version identity) in a single pass — never buffers the full file.
        Architected so a future ContentDefinedChunker can be swapped in:
        only this method + _restore need to change, nothing in the public
        snapshot/restore API does."""
        conn = self._connect()
        conn.execute(
            "UPDATE versions SET status='processing' WHERE version_id=?", (version_id,)
        )
        conn.commit()

        whole_h = hashlib.sha256()
        total_size = 0
        chunk_index = 0
        chunk_size = config.VERSION_CHUNK_SIZE

        with open(display_path, "rb") as src:
            while True:
                buf = src.read(chunk_size)
                if not buf:
                    break
                whole_h.update(buf)
                total_size += len(buf)

                chunk_h = hashlib.sha256(buf)
                chunk_sha = chunk_h.hexdigest()
                fd, tmp_path = tempfile.mkstemp(dir=self.tmp_dir, prefix="chunk_")
                try:
                    with os.fdopen(fd, "wb") as out:
                        out.write(buf)
                        out.flush()
                        os.fsync(out.fileno())
                except Exception:
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                    raise
                self._store_object_from_tmp(tmp_path, chunk_sha, len(buf))
                conn.execute(
                    "INSERT OR IGNORE INTO version_objects(version_id, chunk_index, sha256) VALUES (?, ?, ?)",
                    (version_id, chunk_index, chunk_sha),
                )
                chunk_index += 1

        conn.execute(
            "UPDATE versions SET status='verifying' WHERE version_id=?", (version_id,)
        )
        conn.commit()
        return whole_h.hexdigest(), total_size

    def _create_version_row(self, file_id: int, storage_mode: str) -> int:
        conn = self._connect()
        cur = conn.execute(
            "INSERT INTO versions(file_id, sha256, size, storage_mode, status, created_at) "
            "VALUES (?, '', 0, ?, 'pending', ?)",
            (file_id, storage_mode, time.time()),
        )
        conn.commit()
        return cur.lastrowid

    def _mark_version_failed(self, version_id: int, error: str):
        conn = self._connect()
        conn.execute(
            "UPDATE versions SET status='failed', error=? WHERE version_id=?",
            (error, version_id),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Restore — the core correctness invariant:
    #     original_sha256 == restored_sha256  AND  original_size == restored_size
    # ------------------------------------------------------------------

    def restore_version(
        self, version_id: int, destination: str, overwrite: bool = None
    ):
        if overwrite is None:
            overwrite = config.VERSION_ALLOW_RESTORE_OVERWRITE

        conn = self._connect()
        job_id = self._create_job("restore", version_id=version_id)

        version = conn.execute(
            "SELECT * FROM versions WHERE version_id=?", (version_id,)
        ).fetchone()
        if version is None or version["status"] != "completed":
            self._finish_job(
                job_id, "failed", error="version not found or not completed"
            )
            raise VersionEngineError("version not found or not completed")

        destination = os.path.abspath(os.path.expanduser(destination))
        # Security: never restore into the version store itself, and
        # never silently overwrite without explicit permission.
        if os.path.commonpath([destination, self.storage_dir]) == self.storage_dir:
            self._finish_job(
                job_id, "failed", error="destination inside version storage — refused"
            )
            raise VersionEngineError(
                "refusing to restore into the version storage directory"
            )
        if os.path.exists(destination) and not overwrite:
            self._finish_job(
                job_id, "failed", error="destination exists and overwrite not permitted"
            )
            raise VersionEngineError(
                "destination exists; VERSION_ALLOW_RESTORE_OVERWRITE is False"
            )

        dest_dir = os.path.dirname(destination)
        os.makedirs(dest_dir, exist_ok=True)
        tmp_dest = destination + ".tmp"

        objects = conn.execute(
            "SELECT chunk_index, sha256 FROM version_objects WHERE version_id=? ORDER BY chunk_index",
            (version_id,),
        ).fetchall()

        h = hashlib.sha256()
        total = 0
        try:
            with open(tmp_dest, "wb") as out:
                for row in objects:
                    if not self._verify_object(row["sha256"]):
                        raise VersionEngineError(
                            f"object {row['sha256'][:12]}… missing or corrupted — restore aborted"
                        )
                    with open(self._object_path(row["sha256"]), "rb") as obj_f:
                        while True:
                            buf = obj_f.read(1024 * 1024)
                            if not buf:
                                break
                            h.update(buf)
                            out.write(buf)
                            total += len(buf)
                out.flush()
                os.fsync(out.fileno())
        except Exception as e:
            try:
                os.remove(tmp_dest)
            except OSError:
                pass
            self._finish_job(job_id, "failed", error=str(e))
            raise

        restored_sha = h.hexdigest()
        if restored_sha != version["sha256"] or total != version["size"]:
            try:
                os.remove(tmp_dest)
            except OSError:
                pass
            err = (
                f"restore verification FAILED: sha {restored_sha[:12]}… != "
                f"{version['sha256'][:12]}… or size {total} != {version['size']}"
            )
            self._finish_job(job_id, "failed", error=err)
            raise VersionEngineError(err)

        os.replace(
            tmp_dest, destination
        )  # atomic publish, only after full verification
        self._finish_job(job_id, "completed")
        self.log.info(
            f"Restore verified + completed: version {version_id} -> {destination} "
            f"({restored_sha[:12]}…, {total} bytes)"
        )
        return destination

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def _create_job(self, operation: str, file_id=None, version_id=None) -> int:
        conn = self._connect()
        cur = conn.execute(
            "INSERT INTO jobs(operation, file_id, version_id, status, created_at, started_at) "
            "VALUES (?, ?, ?, 'processing', ?, ?)",
            (operation, file_id, version_id, time.time(), time.time()),
        )
        conn.commit()
        return cur.lastrowid

    def _set_job_version(self, job_id: int, version_id: int):
        conn = self._connect()
        conn.execute(
            "UPDATE jobs SET version_id=? WHERE job_id=?", (version_id, job_id)
        )
        conn.commit()

    def _finish_job(self, job_id: int, status: str, version_id=None, error=None):
        conn = self._connect()
        if version_id is not None:
            conn.execute(
                "UPDATE jobs SET status=?, finished_at=?, version_id=?, error=? WHERE job_id=?",
                (status, time.time(), version_id, error, job_id),
            )
        else:
            conn.execute(
                "UPDATE jobs SET status=?, finished_at=?, error=? WHERE job_id=?",
                (status, time.time(), error, job_id),
            )
        conn.commit()

    # ------------------------------------------------------------------
    # Retention & GC
    # ------------------------------------------------------------------

    def _apply_retention(self, file_id: int):
        if not config.VERSION_RETENTION_ENABLED:
            return
        conn = self._connect()
        rows = conn.execute(
            "SELECT version_id FROM versions WHERE file_id=? AND status='completed' "
            "ORDER BY created_at DESC",
            (file_id,),
        ).fetchall()
        excess = rows[config.VERSION_MAX_VERSIONS :]
        if not excess:
            return
        for row in excess:
            conn.execute(
                "UPDATE versions SET status='deleted' WHERE version_id=?",
                (row["version_id"],),
            )
        conn.commit()
        self.log.info(
            f"Retention: soft-deleted {len(excess)} version(s) beyond "
            f"VERSION_MAX_VERSIONS={config.VERSION_MAX_VERSIONS} for file_id={file_id}"
        )

    def run_gc(self):
        if not config.VERSION_GC_ENABLED:
            return
        job_id = self._create_job("gc")
        conn = self._connect()
        now = time.time()

        # An object is live if referenced by any 'completed' version.
        live = {
            row["sha256"]
            for row in conn.execute(
                "SELECT DISTINCT vo.sha256 FROM version_objects vo "
                "JOIN versions v ON v.version_id = vo.version_id "
                "WHERE v.status='completed'"
            ).fetchall()
        }
        all_objects = conn.execute(
            "SELECT sha256, orphaned_since FROM objects"
        ).fetchall()

        newly_orphaned = 0
        cleared = 0
        deleted = 0
        for row in all_objects:
            sha = row["sha256"]
            if sha in live:
                if row["orphaned_since"] is not None:
                    conn.execute(
                        "UPDATE objects SET orphaned_since=NULL WHERE sha256=?", (sha,)
                    )
                    cleared += 1
                continue
            if row["orphaned_since"] is None:
                conn.execute(
                    "UPDATE objects SET orphaned_since=? WHERE sha256=?", (now, sha)
                )
                newly_orphaned += 1
            elif now - row["orphaned_since"] >= config.VERSION_GC_GRACE_PERIOD:
                # Still unreferenced after the full grace period — safe to
                # delete. Re-check liveness right before unlinking (race-
                # aware: a snapshot could have re-referenced it moments ago).
                still_unreferenced = conn.execute(
                    "SELECT 1 FROM version_objects vo JOIN versions v "
                    "ON v.version_id = vo.version_id "
                    "WHERE vo.sha256=? AND v.status='completed' LIMIT 1",
                    (sha,),
                ).fetchone()
                if still_unreferenced is None:
                    try:
                        os.remove(self._object_path(sha))
                    except OSError:
                        pass
                    # version_objects rows from non-completed (failed/
                    # deleted) versions still FK-reference this object —
                    # safe to drop them here: a 'deleted' (soft-retention)
                    # version's bytes are, by this point, actually gone,
                    # so its version_objects link is now meaningless
                    # bookkeeping, not a live reference. The versions row
                    # itself is untouched (audit trail preserved).
                    conn.execute("DELETE FROM version_objects WHERE sha256=?", (sha,))
                    conn.execute("DELETE FROM objects WHERE sha256=?", (sha,))
                    deleted += 1
        conn.commit()
        self._finish_job(job_id, "completed")
        self.log.info(
            f"GC: {newly_orphaned} newly orphaned, {cleared} re-referenced, "
            f"{deleted} object(s) deleted (grace period {config.VERSION_GC_GRACE_PERIOD}s)"
        )

    # ------------------------------------------------------------------
    # Scan / reconcile — shared by watcher (fast poll) and scanner (slow,
    # authoritative reconciliation + new-file discovery). See module
    # docstring for why this is stat-polling rather than an OS-level
    # filesystem-event watch.
    # ------------------------------------------------------------------

    def _enqueue_snapshot(self, display_path: str):
        norm_key = _normalize_path(display_path)
        with self._pending_lock:
            if norm_key in self._pending_norm_keys:
                return  # already queued — debounce duplicate events
            self._pending_norm_keys.add(norm_key)
        self._job_queue.put(display_path)

    def _reconcile_once(self):
        eligible = self.get_eligible_files()  # {norm_key: display_path}
        for norm_key, display_path in eligible.items():
            try:
                st = os.stat(display_path)
            except OSError:
                continue
            cached = self._known_state.get(norm_key)
            current = (st.st_mtime, st.st_size)
            if cached != current:
                self._known_state[norm_key] = current
                self._enqueue_snapshot(display_path)

        # Mark files that dropped out of scope / were deleted from disk —
        # NEVER deletes version history, only the "currently present" flag.
        known_norm_keys = set(self._known_state.keys())
        vanished = known_norm_keys - set(eligible.keys())
        if vanished:
            conn = self._connect()
            for norm_key in vanished:
                conn.execute("UPDATE files SET deleted=1 WHERE norm_key=?", (norm_key,))
                self._known_state.pop(norm_key, None)
            conn.commit()

    def _watcher_loop(self):
        self._watcher_running = True
        self._set_meta("watcher_running", "1")
        self.log.info(f"Watcher started (poll interval {_WATCH_POLL_INTERVAL}s).")
        while not self._shutdown_event.is_set():
            if not self._stop_scheduling.is_set():
                try:
                    self._reconcile_once()
                except Exception as e:
                    self.log.error(f"Watcher reconcile error: {e}")
            self._shutdown_event.wait(_WATCH_POLL_INTERVAL)
        self._watcher_running = False
        self._set_meta("watcher_running", "0")
        self.log.info("Watcher stopped.")

    def _scanner_loop(self):
        self._scanner_running = True
        self._set_meta("scanner_running", "1")
        self.log.info(f"Scanner started (interval {config.VERSION_SCAN_INTERVAL}s).")
        while not self._shutdown_event.is_set():
            if not self._stop_scheduling.is_set():
                try:
                    self._reconcile_once()
                    self.run_gc()
                    self._set_meta("last_scan", time.strftime("%Y-%m-%d %H:%M:%S"))
                except Exception as e:
                    self.log.error(f"Scanner error: {e}")
            self._shutdown_event.wait(config.VERSION_SCAN_INTERVAL)
        self._scanner_running = False
        self._set_meta("scanner_running", "0")
        self.log.info("Scanner stopped.")

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def _worker_loop(self, worker_index: int):
        self.log.debug(f"Worker {worker_index} started.")
        while not self._shutdown_event.is_set():
            try:
                display_path = self._job_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.snapshot_file(display_path, source="scan")
            except Exception as e:
                self.log.error(
                    f"Worker {worker_index} snapshot error for {display_path}: {e}"
                )
            finally:
                self._job_queue.task_done()
        self.log.debug(f"Worker {worker_index} stopped.")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self._ensure_dirs()
        self._bootstrap_schema()
        self._crash_recovery()
        self._sync_tracked_paths_table()

        for i in range(max(1, config.VERSION_WORKER_COUNT)):
            t = threading.Thread(
                target=self._worker_loop, args=(i,), daemon=True, name=f"ve-worker-{i}"
            )
            t.start()
            self._workers.append(t)

        if config.VERSION_SCAN_ENABLED:
            self._scanner_thread = threading.Thread(
                target=self._scanner_loop, daemon=True, name="ve-scanner"
            )
            self._scanner_thread.start()

        if config.VERSION_WATCH_ENABLED:
            self._watcher_thread = threading.Thread(
                target=self._watcher_loop, daemon=True, name="ve-watcher"
            )
            self._watcher_thread.start()

        self.log.info(
            f"Version Engine started. pid={os.getpid()} db={self.db_path} "
            f"storage={self.storage_dir} workers={config.VERSION_WORKER_COUNT} "
            f"watch={config.VERSION_WATCH_ENABLED} scan={config.VERSION_SCAN_ENABLED}"
        )

    def graceful_shutdown(self):
        """§7: stop scheduling new jobs, stop watcher/scanner, let
        in-flight work finish within VERSION_SHUTDOWN_TIMEOUT, then close
        the DB. Never falsely marks interrupted work 'completed'."""
        self.log.info("Graceful shutdown initiated.")
        self._stop_scheduling.set()
        self._shutdown_event.set()

        deadline = time.time() + config.VERSION_SHUTDOWN_TIMEOUT
        try:
            while not self._job_queue.empty() and time.time() < deadline:
                time.sleep(0.2)
        except Exception:
            pass

        for t in self._workers:
            t.join(timeout=max(0, deadline - time.time()))
        if self._scanner_thread:
            self._scanner_thread.join(timeout=1)
        if self._watcher_thread:
            self._watcher_thread.join(timeout=1)

        try:
            conn = self._connect()
            conn.close()
        except Exception:
            pass
        self.log.info("Graceful shutdown complete.")


class _SourceChangedDuringCapture(VersionEngineError):
    pass


# =============================================================================
# Worker-mode entry point
# =============================================================================


def _worker_main():
    log = logging_setup.get_logger("version_engine")

    if not getattr(config, "VERSION_ENGINE_ENABLED", True):
        log.info("VERSION_ENGINE_ENABLED is False — exiting cleanly.")
        return 0

    engine = Engine()
    engine.start()

    def _handle_signal(signum, _frame):
        log.info(f"Received signal {signum} — starting graceful shutdown.")
        engine.graceful_shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.graceful_shutdown()
    return 0


def main():
    parser = argparse.ArgumentParser(description="CloudinatorFTP Version Engine")
    parser.add_argument(
        "--worker", action="store_true", help="Run as the Version Engine worker process"
    )
    args = parser.parse_args()

    if args.worker:
        sys.exit(_worker_main())
    else:
        print(
            "version_engine.py: use --worker to run the child process, or `import version_engine` "
            "from dev_server.py / prod_server.py to use the parent API (start/stop/force_kill/status)."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
