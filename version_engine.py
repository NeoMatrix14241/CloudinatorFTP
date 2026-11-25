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
import fnmatch
import hashlib
import os
import queue
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

import config
import logging_setup
from helpers import (
    parent_watch,
    version_compress,
    version_purge,
    version_wal,
    version_zstd,
)

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_PATH = os.path.join(_PROJECT_DIR, "version_engine.py")

_ENGINE_VERSION = "1.0.0"
# 5.46: schema 2 adds the object-compression columns (see _OBJECT_V2_COLUMNS / _migrate_schema).
# 5.47.1: schema 3 adds `base_sha` (the previous-version delta, see _OBJECT_V3_COLUMNS).
_SCHEMA_VERSION = 3

# Folder names that are never tracked, whatever VERSION_EXCLUDE_DIRECTORIES says (5.41). `.chunks`
# is where the web server keeps the pieces of an upload that is still arriving (<root>/.chunks/):
# a version of a half-finished 10 MB piece is useless, and when the tracked scope includes the
# storage root the watcher would hash and copy every piece, doubling the disk traffic of an upload.
_ALWAYS_EXCLUDED_DIR_NAMES = (".chunks",)

# A watcher / scanner pass that takes at least this many seconds is logged (at most once a
# minute): on a slow disk a pass over a big tracked folder competes with everything else on it.
_SLOW_PASS_SECONDS = 2.0
_SLOW_PASS_LOG_EVERY = 60.0

# How often the (optional) watcher polls tracked paths for changes. Not a
# config.py setting — this is an internal implementation constant for the
# stat-polling loop, distinct from config.VERSION_SCAN_INTERVAL (the full
# reconciliation scanner's interval, which IS configurable).
_WATCH_POLL_INTERVAL = 3  # seconds

# 5.44.1: a watcher / scanner pass walks and stats EVERY tracked file. On a big tree a pass takes
# longer than the 3 s wait between two passes, so the engine (its own process) was walking the
# whole tree back to back, in two threads at once, and the server's own walks (Rebuild Cache) had
# to share a hard disk with that. The wait after a pass is now proportional to how long the pass
# took: the engine is busy at most 1 / (1 + _PASS_BUSY_FACTOR) of the time (25%), never longer
# than _MAX_PASS_WAIT between passes. A small tree (a pass under 1 s) still polls every 3 s.
_PASS_BUSY_FACTOR = 3
_MAX_PASS_WAIT = 900.0  # seconds

# 5.45: the optional background purge of versions whose file no longer exists
# (config.VERSION_PURGE_MISSING_*, on by default since the owner's decision). Its thread waits this long after the engine
# starts before its first pass, so it never competes with crash recovery and the first scan.
# Skipped passes (a tracked folder missing, empty or unreadable) are logged at most this often.
_PURGE_START_DELAY = 300.0  # seconds
_PURGE_SKIP_LOG_EVERY = 3600.0
# Keys in engine_metadata (the same table _set_meta writes the watcher / scanner flags to).
_META_PURGE_CURSOR = "purge_missing_cursor"
_META_PURGE_RUNNING = "purge_missing_running"
_META_PURGE_LAST = "purge_missing_last"

# 5.45.1: the write-ahead log (version_engine.sqlite3-wal) never shrinks by itself: a checkpoint
# reuses the file from its start, so it keeps the size of the biggest burst it ever saw (2.9 GB
# on the owner's server after a purge and a GC). Two measures, see
# helpers/version_wal.py: every connection sets `PRAGMA journal_size_limit`, and a pass that
# wrote a lot ends with `wal_checkpoint(TRUNCATE)` when the file is above the same limit
# (config.VERSION_WAL_SIZE_LIMIT_MB, never above 64 MB, 0 = off). The checkpoint waits at most
# this long for readers and writers, then gives up until the next pass (the data is safe
# either way); a busy answer is logged at most this often.
_WAL_CHECKPOINT_BUSY_MS = 2000
_WAL_BUSY_LOG_EVERY = 900.0


# 5.46: object compression (VERSION_COMPRESSION_PLAN.md). An object's IDENTITY is always the
# SHA-256 of its RAW bytes; compression is only a storage encoding. A compressed object is the
# NEW file `objects/ab/<sha>.zst` next to (never replacing) the raw `objects/ab/<sha>`; the file
# name says which form it is. The columns below are BOOKKEEPING: readers go by the files and the
# SHA-256 of the decoded bytes decides whether an object is correct.
_OBJECT_V2_COLUMNS = (
    ("codec", "TEXT NOT NULL DEFAULT 'raw'"),  # 'raw' | 'zstd'
    (
        "stored_size",
        "INTEGER",
    ),  # bytes on disk when codec='zstd'; NULL = same as `size`
    ("compress_state", "TEXT NOT NULL DEFAULT 'pending'"),  # pending|done|skip|failed
    ("codec_level", "INTEGER"),  # the level used or attempted
    ("compressed_at", "REAL"),  # when the swap committed
)
# 5.47.1 (Phase 4): an object compressed as a DELTA against another object (its "base") has the
# base's sha256 here; NULL for every other object. The delta is the new chunk compressed with
# the base's raw bytes as a raw zstd dictionary, so decoding needs the base. The base is always a
# PLAIN object (never itself a delta: depth 1, a read needs at most two objects and chains never
# form), the GC treats a base as referenced for as long as any delta needs it, and nothing is
# ever stored in a delta that is not also verified against its base before it is published.
_OBJECT_V3_COLUMNS = (("base_sha", "TEXT"),)
_READ_BLOCK = 1024 * 1024
# A delta is only built when base + data fit the 2**27-byte window a stock decoder accepts.
_DELTA_MAX_OBJECT_BYTES = 32 * 1024 * 1024
# Upper bound for a decoded object whose size is not known (no `objects` row): far above
# anything the engine stores (chunk and small-file sizes are at most a few MiB); it only has to
# stop a decompression bomb.
_MAX_DECODED_BYTES = 1 << 40

# 5.47: the object compressor, the engine's own `ve-compress` thread (config.VERSION_COMPRESSION_*,
# OFF by default). Built like `ve-purge`: a plain daemon thread of this worker process, stopped
# through _shutdown_event, every wait is `_shutdown_event.wait(...)` (never time.sleep), no
# asyncio, no thread pool. It starts this long after the engine so it never competes with crash
# recovery, the first scan or the purge.
_COMPRESS_START_DELAY = 600.0  # seconds
# The raw copy of a compressed object is removed this long after the `.zst` was committed.
_COMPRESS_SWEEP_GRACE = 300.0  # seconds
_COMPRESS_MAX_PAUSE = 60.0  # one duty-cycle pause is never longer than this
_COMPRESS_PAGE = 50  # rows looked at per query
_COMPRESS_PROGRESS_EVERY = (
    500  # objects between a log line, a cursor save and a WAL check
)
# An object above this size is not compressed at all (it would have to be held in memory); above
# the second one the level is capped (level 22 needs a window as big as the object).
_COMPRESS_MAX_OBJECT_BYTES = 256 * 1024 * 1024
_COMPRESS_HIGH_LEVEL_BYTES = 32 * 1024 * 1024
_COMPRESS_HIGH_LEVEL_CAP = 19
# Keys in engine_metadata (shown by `version-manage compress --status` and status()).
_META_COMPRESS_CURSOR = "compress_cursor"
_META_COMPRESS_RUNNING = "compress_running"
_META_COMPRESS_LAST = "compress_last"


def _wal_limit_bytes() -> int:
    """The WAL size limit in bytes (config.VERSION_WAL_SIZE_LIMIT_MB, 0 = off, at most 64 MB)."""
    return version_wal.limit_bytes(getattr(config, "VERSION_WAL_SIZE_LIMIT_MB", 64))


def _next_pass_wait(base: float, pass_seconds: float) -> float:
    """Seconds to wait after a pass that took `pass_seconds`: never less than `base`, about
    _PASS_BUSY_FACTOR times the pass otherwise, at most _MAX_PASS_WAIT (or `base` if larger).
    """
    wanted = max(float(base), float(pass_seconds) * _PASS_BUSY_FACTOR)
    return min(wanted, max(float(base), _MAX_PASS_WAIT))


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
        # The engine's output pipe closed; the pump simply ends.
        pass
    finally:
        try:
            stream.close()
        except Exception:
            # Pipe already closed.
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
        # PID file is a convenience for manage.sh; failing to write it must not stop startup.
        pass


def _clear_ve_pidfile():
    try:
        os.remove(_VE_PID_FILE)
    except OSError:
        # PID file already gone.
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
    # Orphan guard: the worker watches this PID (helpers/parent_watch.py)
    # and shuts itself down if this process dies without calling stop() -
    # taskkill /F, SIGKILL, a crash or os._exit() all skip stop().
    env["CLOUDINATOR_PARENT_PID"] = str(os.getpid())

    try:
        # S603: fixed argv (sys.executable and a project script); no user input reaches it.
        proc = subprocess.Popen(  # noqa: S603
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
        # Process already gone or not killable; shutdown continues.
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
        "compress_running": False,
        "compress_last": None,
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
                result["compress_running"] = meta.get("compress_running") == "1"
                result["compress_last"] = meta.get("compress_last")
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


# ---------------------------------------------------------------------------
# In-process write gate (2026-09-28, "database is locked" at startup)
# ---------------------------------------------------------------------------
# SQLite allows ONE writer at a time, and its busy handler is a sleep-and-poll
# loop with no fairness: with 12 worker threads + watcher + scanner all
# opening their own connection and committing ~8 tiny writes per file, a
# thread can lose the race for the whole busy_timeout even though no single
# holder is slow (the startup burst in the log: 8 workers failing in the same
# second, ~10 s after start). This gate serialises write transactions INSIDE
# this process with an ordinary lock (blocking, no polling), so SQLite's
# lock only ever arbitrates against the OTHER process (the web process's
# restore/retry). Reads never take the gate (WAL readers don't block).
#
# The gate is taken on the first write statement of a transaction and
# released by commit()/rollback()/close(). If a write statement raises, the
# transaction is rolled back and the gate released immediately so a failed
# statement can never leave the gate (or the SQLite lock) held. Acquisition
# has a timeout: if it ever expires we proceed WITHOUT the gate (falling back
# to plain SQLite behaviour) rather than deadlocking every thread.
_WRITE_GATE = threading.Lock()
_GATE_ACQUIRE_TIMEOUT = 60
_WRITE_SQL_RE = re.compile(r"^\s*(insert|update|delete|replace|begin)\b", re.IGNORECASE)


class _GatedConnection(sqlite3.Connection):
    _gate_held = False

    def _gate_acquire(self):
        if not self._gate_held and _WRITE_GATE.acquire(timeout=_GATE_ACQUIRE_TIMEOUT):
            self._gate_held = True

    def _gate_release(self):
        if self._gate_held:
            self._gate_held = False
            _WRITE_GATE.release()

    def execute(self, sql, *args, **kwargs):
        is_write = bool(_WRITE_SQL_RE.match(sql))
        if is_write:
            self._gate_acquire()
        try:
            return super().execute(sql, *args, **kwargs)
        except sqlite3.Error:
            if is_write:
                try:
                    super().rollback()
                except sqlite3.Error:
                    # Rollback on a broken connection can fail; the original error is what matters.
                    pass
                self._gate_release()
            raise

    def commit(self):
        try:
            super().commit()
        finally:
            self._gate_release()

    def rollback(self):
        try:
            super().rollback()
        finally:
            self._gate_release()

    def close(self):
        try:
            super().close()
        finally:
            self._gate_release()


def _is_lock_error(exc) -> bool:
    """True for SQLite's transient 'database is locked' / 'busy' errors."""
    return isinstance(exc, sqlite3.OperationalError) and any(
        w in str(exc).lower() for w in ("locked", "busy")
    )


# How many times a worker-driven snapshot is retried (backoff 2,4,8,16,30 s)
# when another writer is holding the DB lock, before it gives up and lets the
# watcher pick the file up again. A user-triggered web retry is kept short
# because an HTTP request is waiting on it.
_BUSY_MAX_RETRIES = 5
_BUSY_MAX_RETRIES_WEB = 2


class VersionEngineError(Exception):
    pass


class _ObjectError(VersionEngineError):
    """One stored object could not be read back correctly (5.46). `kind` is 'missing',
    'unreadable' or 'corrupted'; the callers (restore, download) turn it into the message
    they have always used."""

    def __init__(self, kind: str, sha256_hex: str, detail: str = ""):
        super().__init__(
            f"object {sha256_hex[:12]}... {kind}" + (f": {detail}" if detail else "")
        )
        self.kind = kind
        self.sha256_hex = sha256_hex
        self.detail = detail


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
        # 5.44.1: the watcher and the scanner run the SAME full pass (_reconcile_once); one at a
        # time is enough and halves the disk work when both fire together.
        self._pass_lock = threading.Lock()
        # 5.45: the garbage collector and the background purge's WRITE phase take this lock, so
        # the two never overlap (the purge's slow read-only checking does not hold it).
        self._maintenance_lock = threading.Lock()
        # One purge pass at a time, whoever asks (the ve-purge thread, a test).
        self._purge_pass_lock = threading.Lock()
        self._purge_thread = None
        self._purge_skip_logged_at = None
        # 5.47: one compression batch at a time, whoever asks (the ve-compress thread, a test).
        self._compress_pass_lock = threading.Lock()
        self._compress_thread = None
        self._wal_busy_logged_at = None

        self._conn_local = threading.local()

        self._watcher_running = False
        self._scanner_running = False
        self._purge_running = False
        self._compress_running = False

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
        conn = sqlite3.connect(
            self.db_path, check_same_thread=False, factory=_GatedConnection
        )
        conn.row_factory = sqlite3.Row
        # busy_timeout FIRST: the journal_mode pragma below can itself need
        # a lock, and should wait rather than fail instantly.
        conn.execute("PRAGMA busy_timeout=30000")
        # 5.47.2: switching a database that is still in rollback-journal mode to WAL does NOT
        # honour busy_timeout (SQLite answers "database is locked" at once when another
        # connection is doing the same); enable_wal retries that one answer for a bounded time.
        version_wal.enable_wal(conn)
        # WAL + NORMAL: no fsync on every commit (WAL is still fsync'd at
        # checkpoints). Every snapshot does ~8 commits, so on Windows/HDD
        # the default FULL made each write-lock window several times longer.
        # Safe here: object files are fsync'd separately, and a power loss
        # can only roll back the last few commits, which crash recovery
        # already treats as 'interrupted' (never falsely 'completed').
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # 5.45.1: a setting of THIS connection (not stored in the file): after a checkpoint
        # resets the log SQLite cuts the -wal file back to this size.
        version_wal.apply_journal_size_limit(conn, _wal_limit_bytes())
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
        self._migrate_schema(conn)

    def _migrate_schema(self, conn):
        """Bring the database up to _SCHEMA_VERSION (5.46: schema 2, the object-compression
        columns). Idempotent and race-safe: the engine worker, the web process
        (version_history.init) and the CLI tools all call _bootstrap_schema, so two processes
        can get here at the same moment; the loser's `duplicate column name` is success.
        Existing rows get the column defaults ('raw', 'pending'), so the compression backlog is
        defined by one WHERE and no row is rewritten. An older engine reading a schema-2
        database keeps working for raw objects (it never selects the new columns)."""
        have = {row[1] for row in conn.execute("PRAGMA table_info(objects)")}
        altered = False
        for name, ddl in _OBJECT_V2_COLUMNS + _OBJECT_V3_COLUMNS:
            if name in have:
                continue
            try:
                conn.execute(
                    f"ALTER TABLE objects ADD COLUMN {name} {ddl}"
                )  # noqa: S608
                altered = True
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise
        if altered:
            conn.commit()

        # A database that is already current is only READ: bootstrap runs at every start of the
        # worker, of the web process and of every CLI tool, and a write transaction there would
        # compete for SQLite's one write lock with the engine's own work for nothing.
        row = conn.execute(
            "SELECT value FROM engine_metadata WHERE key='schema_version'"
        ).fetchone()
        try:
            current = int(row[0]) if row is not None else None
        except (TypeError, ValueError):
            current = (
                0  # an unreadable number is older than anything: write the right one
            )
        if current is not None and current >= _SCHEMA_VERSION:
            return  # (a number written by a newer release is never lowered)
        # a partial index: only the few delta objects are in it (the GC and the purge ask "does
        # anything use this object as its base?")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_objects_base_sha ON objects(base_sha) "
            "WHERE base_sha IS NOT NULL"
        )
        if current is None:
            conn.execute(
                "INSERT OR IGNORE INTO engine_metadata(key, value) "
                "VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO engine_metadata(key, value) "
                "VALUES ('engine_version', ?)",
                (_ENGINE_VERSION,),
            )
        else:
            conn.execute(
                "UPDATE engine_metadata SET value=? "
                "WHERE key='schema_version' AND CAST(value AS INTEGER) < ?",
                (str(_SCHEMA_VERSION), _SCHEMA_VERSION),
            )
        conn.commit()

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
                    # Temp file already gone or locked; a later cleanup removes it.
                    pass
        except OSError:
            # Temp directory missing or unreadable; nothing to clean.
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
            if not self._object_exists(row["sha256"]):
                missing += 1
        if missing:
            self.log.warning(
                f"Crash recovery: {missing} referenced object(s) missing from storage — "
                "affected versions will fail integrity checks on restore."
            )

        # 5. (5.47.1) A delta object needs its base: report one whose base row or files are gone.
        try:
            deltas = conn.execute(
                "SELECT sha256, base_sha FROM objects WHERE base_sha IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            deltas = []  # a database without the base_sha column has no deltas
        no_base = [
            row["sha256"]
            for row in deltas
            if not self._object_exists(row["base_sha"])
            or conn.execute(
                "SELECT 1 FROM objects WHERE sha256=?", (row["base_sha"],)
            ).fetchone()
            is None
        ]
        if no_base:
            self.log.error(
                f"Crash recovery: {len(no_base)} delta object(s) have no base object "
                f"(first: {no_base[0][:12]}...): possible disk corruption; those versions "
                "cannot be read."
            )

    # ------------------------------------------------------------------
    # Content-addressed object storage
    # ------------------------------------------------------------------

    def _object_path(self, sha256_hex: str) -> str:
        """Path of the RAW form of an object (the only form before 5.46)."""
        return os.path.join(self.objects_dir, sha256_hex[:2], sha256_hex)

    def _zst_path(self, sha256_hex: str) -> str:
        """Path of the COMPRESSED form of an object (5.46): the raw path plus `.zst`."""
        return self._object_path(sha256_hex) + version_zstd.SUFFIX

    def _object_exists(self, sha256_hex: str) -> bool:
        """True when the object is stored in EITHER form."""
        return os.path.exists(self._object_path(sha256_hex)) or os.path.exists(
            self._zst_path(sha256_hex)
        )

    def _find_object(self, sha256_hex: str):
        """(path, is_zstd) of the form a reader should open, or None. The filesystem decides,
        never the database column. When both forms exist (the few minutes between the
        compressor publishing the `.zst` and the sweep removing the raw file) the RAW one is
        read: it needs no decoding and it is the verified original."""
        raw = self._object_path(sha256_hex)
        if os.path.exists(raw):
            return raw, False
        zst = self._zst_path(sha256_hex)
        if os.path.exists(zst):
            return zst, True
        return None

    def _open_object(self, sha256_hex: str):
        """(open binary file, is_zstd). A file that vanishes between the check and the open (the
        raw form was just swept, a `.zst` was just published) is retried ONCE with the other
        form. Raises _ObjectError('missing' | 'unreadable')."""
        for attempt in (0, 1):
            found = self._find_object(sha256_hex)
            if found is None:
                raise _ObjectError("missing", sha256_hex)
            path, is_zst = found
            try:
                return open(path, "rb"), is_zst
            except FileNotFoundError:
                if attempt == 0:
                    continue
                raise _ObjectError("missing", sha256_hex) from None
            except OSError as e:
                raise _ObjectError("unreadable", sha256_hex, str(e)) from e
        raise _ObjectError("missing", sha256_hex)  # pragma: no cover

    def _object_size(self, sha256_hex: str):
        """The RAW size recorded for an object, or None when it has no `objects` row."""
        row = (
            self._connect()
            .execute("SELECT size FROM objects WHERE sha256=?", (sha256_hex,))
            .fetchone()
        )
        return None if row is None else row[0]

    def _object_base(self, sha256_hex: str):
        """The base of a delta object, or None for every other object (and on a database that
        has no `base_sha` column yet)."""
        try:
            row = (
                self._connect()
                .execute("SELECT base_sha FROM objects WHERE sha256=?", (sha256_hex,))
                .fetchone()
            )
        except sqlite3.OperationalError:
            return None
        return None if row is None else row[0]

    def _base_dictionary(self, sha256_hex: str, base_sha: str, depth: int = 0):
        """The raw zstd dictionary made of a delta's base object (read through the same one
        read path, so the base is hash-verified like everything else). A base that is itself a
        delta is refused (depth 1: no chains, so no loop can ever form). Raises _ObjectError
        with the DELTA's name: 'missing' when the base is gone, else 'corrupted'."""
        if depth >= 1:
            raise _ObjectError(
                "corrupted",
                sha256_hex,
                "its base object is itself stored as a delta (chains are not allowed)",
            )
        try:
            base_bytes = b"".join(
                self._iter_object_bytes(
                    base_sha, self._object_size(base_sha), _READ_BLOCK, depth + 1
                )
            )
        except _ObjectError as e:
            raise _ObjectError(
                "missing" if e.kind == "missing" else "corrupted",
                sha256_hex,
                f"its base object {base_sha[:12]}... is {e.kind}",
            ) from e
        return version_zstd.raw_dictionary(base_bytes)

    def _iter_object_bytes(
        self,
        sha256_hex: str,
        expected_size=None,
        block_size: int = _READ_BLOCK,
        _depth: int = 0,
    ):
        """Yield an object's RAW bytes in blocks, whichever form is stored, hashing as it goes.
        The ONE read path of the engine: restore, download and the integrity check all use it.

        A compressed object is decoded one bounded block at a time (never held whole); the
        decoder refuses a frame that is truncated, corrupt, followed by other bytes or that
        expands beyond `expected_size` (decompression bomb). After the last block the SHA-256
        of the bytes that were yielded must equal the object's name: the hash is the arbiter,
        for a raw file as for a decoded one. Raises _ObjectError (kind 'missing', 'unreadable'
        or 'corrupted'); a consumer has already received the earlier blocks by then, so it must
        discard what it wrote (restore removes its temp file; a download is aborted).
        Synchronous: runs wherever the caller already runs."""
        fh, is_zst = self._open_object(sha256_hex)
        digest = hashlib.sha256()
        try:
            if is_zst:
                if not version_zstd.available():
                    raise _ObjectError(
                        "unreadable",
                        sha256_hex,
                        "this object is compressed and zstd is not available in this Python",
                    )
                limit = _MAX_DECODED_BYTES if expected_size is None else expected_size
                base_sha = self._object_base(sha256_hex)
                zdict = (
                    None
                    if base_sha is None
                    else self._base_dictionary(sha256_hex, base_sha, _depth)
                )
                pieces = version_zstd.iter_decode(
                    fh, limit, block_size, zstd_dict=zdict
                )
            else:
                pieces = iter(lambda: fh.read(block_size), b"")
            try:
                for piece in pieces:
                    digest.update(piece)
                    yield piece
            except version_zstd.CodecError as e:
                raise _ObjectError("corrupted", sha256_hex, str(e)) from e
            except OSError as e:
                raise _ObjectError("unreadable", sha256_hex, str(e)) from e
        finally:
            fh.close()
        if digest.hexdigest() != sha256_hex:
            raise _ObjectError("corrupted", sha256_hex, "SHA-256 mismatch")

    def _upsert_object_row(self, sha256_hex: str, size: int):
        """The `objects` row of a stored object: new rows start as raw / pending, an existing row
        (of either form) only loses its orphan mark. `size` is always the RAW size."""
        self._connect().execute(
            "INSERT INTO objects(sha256, size, created_at, orphaned_since) "
            "VALUES (?, ?, ?, NULL) "
            "ON CONFLICT(sha256) DO UPDATE SET orphaned_since=NULL",
            (sha256_hex, size, time.time()),
        )

    def _store_object_from_tmp(
        self, tmp_path: str, sha256_hex: str, size: int, commit: bool = True
    ):
        """Atomically publish a fully-written temp file as the
        content-addressed object for `sha256_hex`. Dedup: if the object
        already exists on disk in EITHER form (raw, or compressed since 5.46), the
        incoming tmp is just discarded - the existing bytes are already known-good
        (verified when THEY were written)."""
        final_path = self._object_path(sha256_hex)
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        if self._object_exists(sha256_hex):
            try:
                os.remove(tmp_path)
            except OSError:
                # Temp file already gone or locked; a later cleanup removes it.
                pass
        else:
            os.replace(tmp_path, final_path)  # atomic on the same filesystem

        self._upsert_object_row(sha256_hex, size)
        if commit:
            self._connect().commit()

    def _verify_object(self, sha256_hex: str) -> bool:
        """Integrity check: hash-verify an object on read (spec:
        'every object is hash-verified on read; reject missing/truncated/
        corrupted/hash-mismatched objects'). Works on either form."""
        try:
            for _ in self._iter_object_bytes(sha256_hex, self._object_size(sha256_hex)):
                pass
        except _ObjectError:
            return False
        return True

    # ------------------------------------------------------------------
    # Tracking scope resolution (spec §14)
    # ------------------------------------------------------------------

    def _is_excluded_dir(self, dirpath: str) -> bool:
        base = os.path.basename(dirpath)
        if base in _ALWAYS_EXCLUDED_DIR_NAMES:
            return True
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
        self._conn_local.last_snapshot_busy = False
        job_id = self._retry_locked(self._create_job, "snapshot", None)
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

            file_id = self._retry_locked(self._get_or_create_file, display_path, source)

            def _link_job():
                conn.execute(
                    "UPDATE jobs SET file_id=? WHERE job_id=?", (file_id, job_id)
                )
                conn.commit()

            self._retry_locked(_link_job)

            last_error = None
            changed_attempts = 0
            busy_attempts = 0
            busy_gave_up = False
            max_busy = (
                _BUSY_MAX_RETRIES_WEB if source == "web-retry" else _BUSY_MAX_RETRIES
            )
            while True:
                try:
                    result = self._attempt_snapshot(file_id, display_path, job_id)
                    if result is None:
                        self._retry_locked(
                            self._finish_job, job_id, "completed"
                        )  # dedup skip - not an error
                    else:
                        self._retry_locked(
                            self._finish_job, job_id, "completed", result
                        )
                        self._retry_locked(self._apply_retention, file_id)
                    return result
                except _SourceChangedDuringCapture as e:
                    last_error = str(e)
                    changed_attempts += 1
                    if changed_attempts > config.VERSION_RETRY_COUNT:
                        break
                    self.log.info(
                        f"Snapshot retry {changed_attempts}/{config.VERSION_RETRY_COUNT} for "
                        f"{display_path}: source changed during capture"
                    )
                    time.sleep(config.VERSION_RETRY_DELAY)
                except _DatabaseBusy as e:
                    # Another writer held the DB lock past busy_timeout. This
                    # is NOT a problem with the file, so don't record a
                    # permanent failed version - back off and try again.
                    last_error = f"database is locked ({e})"
                    busy_attempts += 1
                    if busy_attempts > max_busy:
                        busy_gave_up = True
                        break
                    delay = min(30, 2**busy_attempts)
                    self.log.warning(
                        f"Snapshot of {display_path} hit a locked database; "
                        f"retry {busy_attempts}/{max_busy} in {delay}s"
                    )
                    time.sleep(delay)
                except Exception as e:
                    last_error = str(e)
                    # exc_info: a bare "database is locked" (or any other
                    # message) is undiagnosable without knowing WHICH
                    # statement raised it.
                    self.log.error(
                        f"Snapshot failed for {display_path}: {e}", exc_info=True
                    )
                    break

            if busy_gave_up:
                # Let the watcher re-discover this file on its next poll
                # (_reconcile_once only enqueues when the cached (mtime,
                # size) differs, so without this the capture would be lost
                # until the file happened to change again).
                self._known_state.pop(_normalize_path(display_path), None)
                self.log.warning(
                    f"Gave up on {display_path} after {max_busy} locked-database "
                    "retries; it will be re-queued automatically."
                )
                # Tell an interactive caller (version_history.retry_snapshot)
                # the truth: nothing was captured because the DB was busy.
                # Not a failed version row - writing one would need the very
                # lock we couldn't get.
                self._conn_local.last_snapshot_busy = True
            try:
                self._finish_job(job_id, "failed", error=last_error or "unknown error")
            except sqlite3.OperationalError as e:
                if not _is_lock_error(e):
                    raise
                # Still locked: leave the job row 'processing' (crash recovery
                # marks it failed at next start) rather than turning a handled
                # give-up into an exception.
                self.log.warning(f"Could not record failed job {job_id}: {e}")
            return None
        finally:
            with self._pending_lock:
                self._pending_norm_keys.discard(_normalize_path(display_path))

    def _discard_version_row(self, version_id: int):
        """Best-effort removal of a not-yet-completed version row (and any
        partial links) after a locked-database failure, so a transient lock
        doesn't leave a permanent 'failed' row or a row stuck 'pending'. If
        even this can't get the lock, crash recovery fixes it at next start."""
        conn = self._connect()
        for attempt in range(3):
            try:
                conn.execute(
                    "DELETE FROM version_objects WHERE version_id=?", (version_id,)
                )
                conn.execute(
                    "DELETE FROM versions WHERE version_id=? AND status!='completed'",
                    (version_id,),
                )
                conn.commit()
                return
            except sqlite3.OperationalError as e:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    # Rollback on a broken connection can fail; the original error is re-raised or retried.
                    pass
                if not _is_lock_error(e) or attempt == 2:
                    self.log.warning(f"Could not discard version row {version_id}: {e}")
                    return
                time.sleep(1.0)

    def _retry_locked(self, fn, *args, delays=(2, 4, 8)):
        """Run a small bookkeeping write, retrying with backoff if another
        writer holds the DB lock past busy_timeout. The final failure is
        re-raised for the caller (worker loop) to handle."""
        for delay in delays:
            try:
                return fn(*args)
            except sqlite3.OperationalError as e:
                if not _is_lock_error(e):
                    raise
                try:
                    self._connect().rollback()
                except sqlite3.Error:
                    # Rollback on a broken connection can fail; the original error is re-raised.
                    pass
                self.log.warning(
                    f"{getattr(fn, '__name__', 'write')}: {e}; retry in {delay}s"
                )
                time.sleep(delay)
        return fn(*args)

    def last_snapshot_busy(self) -> bool:
        """True if this thread's most recent snapshot_file() call gave up
        because the database stayed locked (nothing was captured, and no
        failed version row exists to say so)."""
        return bool(getattr(self._conn_local, "last_snapshot_busy", False))

    def _attempt_snapshot(self, file_id: int, display_path: str, job_id: int):
        holder = {}
        try:
            return self._attempt_snapshot_body(file_id, display_path, job_id, holder)
        except sqlite3.OperationalError as e:
            if not _is_lock_error(e):
                raise
            if holder.get("version_id") is not None:
                self._discard_version_row(holder["version_id"])
            raise _DatabaseBusy(str(e)) from e

    def _attempt_snapshot_body(
        self, file_id: int, display_path: str, job_id: int, holder: dict
    ):
        conn = self._connect()
        try:
            stat_before = os.stat(display_path)
        except OSError as e:
            raise VersionEngineError(f"stat failed: {e}") from e

        small = stat_before.st_size <= config.VERSION_SMALL_FILE_THRESHOLD
        version_id = self._create_version_row(file_id, "full" if small else "chunked")
        holder["version_id"] = version_id
        self._set_job_version(job_id, version_id)

        try:
            if small:
                sha, size = self._capture_full(display_path, version_id)
            else:
                sha, size = self._capture_chunked(display_path, version_id)
        except sqlite3.OperationalError as e:
            if _is_lock_error(e):
                raise  # transient; _attempt_snapshot() discards the row and backs off
            self._mark_version_failed(version_id, f"capture failed: {e}")
            raise
        except Exception as e:
            # Preserve the REAL reason (e.g. "[Errno 13] Permission denied"
            # for a file locked open by another program — QuickBooks .QBW
            # files being the textbook case) instead of a generic string.
            # A vague "capture error" with no detail was previously stored
            # here, which made every capture failure equally undiagnosable
            # from the versions table (and therefore from any UI reading
            # it, including the Version History web UI) even though the
            # real exception text was momentarily available right here.
            self._mark_version_failed(version_id, f"capture failed: {e}")
            raise

        try:
            stat_after = os.stat(display_path)
        except OSError as e:
            self._mark_version_failed(version_id, f"stat failed after capture: {e}")
            raise VersionEngineError(str(e)) from e

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
                # Temp file already gone or locked; a later cleanup removes it.
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
                # 5.46: a chunk that is already stored (in either form) needs no temp file,
                # no write and no fsync: only its row is refreshed, exactly what
                # _store_object_from_tmp does for a duplicate.
                if self._object_exists(chunk_sha):
                    self._upsert_object_row(chunk_sha, len(buf))
                    conn.execute(
                        "INSERT OR IGNORE INTO version_objects(version_id, chunk_index, sha256) VALUES (?, ?, ?)",
                        (version_id, chunk_index, chunk_sha),
                    )
                    conn.commit()
                    chunk_index += 1
                    continue
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
                        # Temp file already gone or locked; a later cleanup removes it.
                        pass
                    raise
                # LOCK-HOLD FIX: the object row and its version_objects link
                # are written and COMMITTED together, right here. Previously
                # the version_objects INSERT was left uncommitted, so SQLite's
                # write lock stayed held while the NEXT chunk was read,
                # hashed and fsync'd (seconds per 8 MB on a slow disk) - i.e.
                # nearly the entire capture. Any other writer (a second
                # worker, the scanner, or the web process's restore/retry)
                # then waited out busy_timeout and got "database is locked".
                # Now the lock is held only for these two tiny statements.
                self._store_object_from_tmp(tmp_path, chunk_sha, len(buf), commit=False)
                conn.execute(
                    "INSERT OR IGNORE INTO version_objects(version_id, chunk_index, sha256) VALUES (?, ?, ?)",
                    (version_id, chunk_index, chunk_sha),
                )
                conn.commit()
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
        for attempt in range(3):
            try:
                conn.execute(
                    "UPDATE versions SET status='failed', error=? WHERE version_id=?",
                    (error, version_id),
                )
                conn.commit()
                return
            except sqlite3.OperationalError as e:
                conn.rollback()
                if "locked" not in str(e).lower() or attempt == 2:
                    raise
                time.sleep(1.0)

    # ------------------------------------------------------------------
    # Query / read-only data access — pure-data methods (dicts / lists of
    # dicts / ints, no printing) shared by version_manage.py's CLI output
    # formatting and, since 2026-09-26, version_history.py's web layer.
    # Added when version_history.py (the web UI) was built — see
    # version_manage.py's do_list()/do_delete(), which now call these
    # instead of running their own copies of this SQL.
    # ------------------------------------------------------------------

    def list_tracked_files(self) -> list:
        """Same summary query do_list() runs with no file_path argument —
        one row per tracked file, with completed-version count and last
        activity timestamp."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT f.file_id, f.path, f.deleted, "
            "COUNT(CASE WHEN v.status='completed' THEN 1 END) AS n_completed, "
            "MAX(v.created_at) AS last_activity "
            "FROM files f LEFT JOIN versions v ON v.file_id = f.file_id "
            "GROUP BY f.file_id ORDER BY last_activity DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_versions(self, file_path: str):
        """Same query do_list(file_path) runs. Returns None if the file
        isn't tracked at all (distinct from an empty list, which means
        tracked but no versions yet), else a list of version dicts,
        newest first."""
        conn = self._connect()
        norm_key = _normalize_path(file_path)
        file_row = conn.execute(
            "SELECT file_id, path, deleted FROM files WHERE norm_key=?", (norm_key,)
        ).fetchone()
        if file_row is None:
            return None

        rows = conn.execute(
            "SELECT version_id, sha256, size, storage_mode, status, created_at, "
            "completed_at, error FROM versions WHERE file_id=? ORDER BY created_at DESC",
            (file_row["file_id"],),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_version(self, version_id: int):
        """Single version's row plus its file's path/deleted flag, or
        None if version_id doesn't exist."""
        conn = self._connect()
        row = conn.execute(
            "SELECT v.*, f.path AS file_path, f.deleted AS file_deleted "
            "FROM versions v JOIN files f ON f.file_id = v.file_id "
            "WHERE v.version_id=?",
            (version_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def delete_version(self, version_id: int, reason: str = ""):
        """Soft-delete: same UPDATE do_delete() ran inline. Returns
        (success: bool, message: str). Does not run GC — call run_gc()
        separately (do_delete()'s --run-gc-now flag does this; the web
        layer can choose to do the same, or leave it to the next
        scheduled scan)."""
        conn = self._connect()
        version = conn.execute(
            "SELECT * FROM versions WHERE version_id=?", (version_id,)
        ).fetchone()
        if version is None:
            return False, f"No such version_id: {version_id}"
        if version["status"] == "deleted":
            return False, f"version_id {version_id} is already deleted"

        conn.execute(
            "UPDATE versions SET status='deleted', error=? WHERE version_id=?",
            (f"Deleted by user: {reason}" if reason else "Deleted by user", version_id),
        )
        conn.commit()
        return True, f"version_id {version_id} marked deleted"

    def clear_failed_versions(self, file_path: str) -> int:
        """Permanently remove every status='failed' version row for one
        file. Returns how many rows were removed (0 if the file isn't
        tracked or has none).

        Unlike delete_version() this is a HARD delete, not a soft one —
        deliberately: a soft-deleted failed row would just turn into a
        'deleted' row that still clutters the history. It's safe because a
        failed capture never became a restorable version: nothing can be
        restored from it, so no user content is lost. Any partial
        version_objects rows a failed chunked capture left behind are
        removed first (foreign_keys is ON), and the chunk objects they
        pointed at become unreferenced, which the normal GC reclaims after
        its grace period. jobs rows are left alone (audit history; jobs
        has no foreign key to versions).

        'completed' and 'deleted' rows are never touched."""
        conn = self._connect()
        file_row = conn.execute(
            "SELECT file_id FROM files WHERE norm_key=?", (_normalize_path(file_path),)
        ).fetchone()
        if file_row is None:
            return 0

        ids = [
            r["version_id"]
            for r in conn.execute(
                "SELECT version_id FROM versions WHERE file_id=? AND status='failed'",
                (file_row["file_id"],),
            ).fetchall()
        ]
        if not ids:
            return 0

        placeholders = ",".join("?" for _ in ids)  # structure only, values stay bound
        try:
            # S608: only "?" placeholders or fixed fragments are interpolated; every value is bound.
            conn.execute(
                f"DELETE FROM version_objects WHERE version_id IN ({placeholders})",  # noqa: S608
                ids,
            )
            # S608: only "?" placeholders or fixed fragments are interpolated; every value is bound.
            conn.execute(
                f"DELETE FROM versions WHERE version_id IN ({placeholders}) "  # noqa: S608
                "AND status='failed'",
                ids,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return len(ids)

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
        job_id = self._retry_locked(self._create_job, "restore", None, version_id)

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
        # UNIQUE temp name (2026-09-28): this used to be destination + ".tmp",
        # so two overlapping restores of the same version (double-click)
        # both opened/removed/renamed the SAME temp file -> WinError 32
        # ("used by another process"). mkstemp in the destination dir keeps
        # os.replace() a same-filesystem atomic rename.
        _fd, tmp_dest = tempfile.mkstemp(
            dir=dest_dir, prefix=".restore_", suffix=".tmp"
        )
        os.close(_fd)

        objects = self._version_object_rows(version_id)

        h = hashlib.sha256()
        total = 0
        try:
            with open(tmp_dest, "wb") as out:
                for row in objects:
                    # One read per object (5.46): the shared reader hashes every object
                    # as it goes and raises on any mismatch; the temp file is removed below.
                    try:
                        for buf in self._iter_object_bytes(
                            row["sha256"], row["osize"] or version["size"]
                        ):
                            h.update(buf)
                            out.write(buf)
                            total += len(buf)
                    except _ObjectError as e:
                        raise VersionEngineError(
                            f"object {row['sha256'][:12]}… missing or corrupted — restore aborted"
                        ) from e
                out.flush()
                os.fsync(out.fileno())
        except Exception as e:
            try:
                os.remove(tmp_dest)
            except OSError:
                # Temp file already gone or locked; a later cleanup removes it.
                pass
            self._finish_job(job_id, "failed", error=str(e))
            raise

        restored_sha = h.hexdigest()
        if restored_sha != version["sha256"] or total != version["size"]:
            try:
                os.remove(tmp_dest)
            except OSError:
                # Temp file already gone or locked; a later cleanup removes it.
                pass
            err = (
                f"restore verification FAILED: sha {restored_sha[:12]}… != "
                f"{version['sha256'][:12]}… or size {total} != {version['size']}"
            )
            self._finish_job(job_id, "failed", error=err)
            raise VersionEngineError(err)

        # Atomic publish, only after full verification. Retried on
        # PermissionError (WinError 5/32): the destination may be briefly held
        # open by a download, antivirus or the indexer.
        last_err = None
        for delay in (0, 0.1, 0.25, 0.5, 1.0, 2.0):
            if delay:
                time.sleep(delay)
            try:
                os.replace(tmp_dest, destination)
                last_err = None
                break
            except PermissionError as e:
                last_err = e
        if last_err is not None:
            try:
                os.remove(tmp_dest)
            except OSError:
                # Temp file already gone or locked; a later cleanup removes it.
                pass
            self._finish_job(job_id, "failed", error=str(last_err))
            raise VersionEngineError(
                f"could not publish restored file (in use by another process): {last_err}"
            )
        self._retry_locked(self._finish_job, job_id, "completed")
        self.log.info(
            f"Restore verified + completed: version {version_id} -> {destination} "
            f"({restored_sha[:12]}…, {total} bytes)"
        )
        return destination

    def _version_object_rows(self, version_id: int):
        """A version's chunks in order, each with the RAW size recorded for its object
        (`osize`, NULL when the object has no row): the decoder's bound (5.46)."""
        return (
            self._connect()
            .execute(
                "SELECT vo.chunk_index AS chunk_index, vo.sha256 AS sha256, "
                "o.size AS osize FROM version_objects vo "
                "LEFT JOIN objects o ON o.sha256 = vo.sha256 "
                "WHERE vo.version_id=? ORDER BY vo.chunk_index",
                (version_id,),
            )
            .fetchall()
        )

    def iter_version_bytes(self, version_id: int, block_size: int = 1024 * 1024):
        """Yield a completed version's bytes straight from the object store
        - no temp file, no rebuild-then-read (the old download path rebuilt
        the whole file, re-hashed it, then read it into memory before the
        first byte went out). Every object is hashed as it streams and the
        whole-file sha256/size are checked at the end; on ANY mismatch this
        raises, which aborts the HTTP response (truncated/failed download)
        instead of ever delivering silently corrupt bytes. Synchronous
        generator - the web layer pulls it via asyncio.to_thread."""
        conn = self._connect()
        version = conn.execute(
            "SELECT * FROM versions WHERE version_id=?", (version_id,)
        ).fetchone()
        if version is None or version["status"] != "completed":
            raise VersionEngineError("version not found or not completed")
        objects = self._version_object_rows(version_id)
        whole = hashlib.sha256()
        total = 0
        for row in objects:
            try:
                for buf in self._iter_object_bytes(
                    row["sha256"], row["osize"] or version["size"], block_size
                ):
                    whole.update(buf)
                    total += len(buf)
                    yield buf
            except _ObjectError as e:
                if e.kind == "corrupted":
                    raise VersionEngineError(
                        f"object {row['sha256'][:12]}... corrupted - download aborted"
                    ) from e
                raise VersionEngineError(
                    f"object {row['sha256'][:12]}... unreadable: {e.detail or e.kind}"
                ) from e
        if whole.hexdigest() != version["sha256"] or total != version["size"]:
            raise VersionEngineError("download verification failed - aborted")

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

    @staticmethod
    def _delta_bases(conn) -> set:
        """sha256 of every object that some delta object needs as its base."""
        try:
            return {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT base_sha FROM objects WHERE base_sha IS NOT NULL"
                )
            }
        except sqlite3.OperationalError:
            return set()  # a database without the base_sha column has no deltas

    @staticmethod
    def _is_delta_base(conn, sha256_hex: str) -> bool:
        try:
            return (
                conn.execute(
                    "SELECT 1 FROM objects WHERE base_sha=? LIMIT 1", (sha256_hex,)
                ).fetchone()
                is not None
            )
        except sqlite3.OperationalError:
            return False

    def run_gc(self):
        """Garbage collection; never overlaps the background purge's write phase (5.45)."""
        with self._maintenance_lock:
            self._run_gc_unlocked()

    def _run_gc_unlocked(self):
        """Orphan marking / deletion, done in SHORT write transactions.

        All classification (which objects are live / newly orphaned / due for
        deletion) is read-only and takes no lock. The writes are then applied
        in small batches, each under BEGIN IMMEDIATE and committed after
        _GC_BATCH_ROWS statements or _GC_BATCH_SECONDS, with a brief pause
        between batches so waiting writers (the snapshot worker, the web
        process) actually get the lock. Previously the whole sweep - including
        an os.remove() per deleted object - ran in one transaction, holding
        the write lock for as long as the sweep took."""
        if not config.VERSION_GC_ENABLED:
            return
        t_start = time.time()
        job_id = self._retry_locked(self._create_job, "gc")
        conn = self._connect()
        now = time.time()

        live = {
            row["sha256"]
            for row in conn.execute(
                "SELECT DISTINCT vo.sha256 FROM version_objects vo "
                "JOIN versions v ON v.version_id = vo.version_id "
                "WHERE v.status='completed'"
            ).fetchall()
        }
        # 5.47.1: an object that a delta object needs as its base counts as referenced for as
        # long as that delta row EXISTS (even an orphaned one: a snapshot may still re-reference
        # it during the grace period). The delta goes first; its base becomes an ordinary orphan
        # on a later pass.
        live |= self._delta_bases(conn)
        all_objects = conn.execute(
            "SELECT sha256, orphaned_since FROM objects"
        ).fetchall()

        to_clear, to_mark, due = [], [], []
        for row in all_objects:
            sha = row["sha256"]
            if sha in live:
                if row["orphaned_since"] is not None:
                    to_clear.append(sha)
            elif row["orphaned_since"] is None:
                to_mark.append(sha)
            elif now - row["orphaned_since"] >= config.VERSION_GC_GRACE_PERIOD:
                due.append(sha)

        _GC_BATCH_ROWS = 500
        _GC_BATCH_SECONDS = 0.25
        _GC_PAUSE = 0.01

        def _run_batches(items, per_item):
            """per_item(sha) runs inside the batch's write transaction."""
            n = 0
            idx = 0
            while idx < len(items):
                conn.execute("BEGIN IMMEDIATE")
                t0 = time.time()
                try:
                    count = 0
                    while idx < len(items):
                        n += per_item(items[idx])
                        idx += 1
                        count += 1
                        if (
                            count >= _GC_BATCH_ROWS
                            or time.time() - t0 >= _GC_BATCH_SECONDS
                        ):
                            break
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                time.sleep(_GC_PAUSE)
            return n

        def _clear(sha):
            conn.execute(
                "UPDATE objects SET orphaned_since=NULL WHERE sha256=?", (sha,)
            )
            return 1

        def _mark(sha):
            conn.execute(
                "UPDATE objects SET orphaned_since=? WHERE sha256=?", (now, sha)
            )
            return 1

        def _delete(sha):
            # Re-check liveness right before unlinking. We hold the write lock
            # here (BEGIN IMMEDIATE), so no snapshot can commit a new
            # reference between this check and the delete.
            still_referenced = conn.execute(
                "SELECT 1 FROM version_objects vo JOIN versions v "
                "ON v.version_id = vo.version_id "
                "WHERE vo.sha256=? AND v.status='completed' LIMIT 1",
                (sha,),
            ).fetchone()
            if still_referenced is not None:
                return 0
            if self._is_delta_base(conn, sha):
                return 0  # a delta that was recorded meanwhile needs this object
            for form in (self._object_path(sha), self._zst_path(sha)):
                try:
                    os.remove(form)
                except OSError:
                    # That form is already removed (or never existed); the DB row is what counts.
                    pass
            # version_objects rows from non-completed (failed/deleted)
            # versions still FK-reference this object; their bytes are gone
            # now, so the links are meaningless bookkeeping. The versions row
            # itself (audit trail) is untouched.
            conn.execute("DELETE FROM version_objects WHERE sha256=?", (sha,))
            conn.execute("DELETE FROM objects WHERE sha256=?", (sha,))
            return 1

        try:
            cleared = _run_batches(to_clear, _clear)
            newly_orphaned = _run_batches(to_mark, _mark)
            deleted = _run_batches(due, _delete)
        except Exception as e:
            # Don't leave the gc job row stuck at 'processing'. Batches
            # already committed are fine; the next scan continues the rest.
            try:
                self._finish_job(job_id, "failed", error=str(e))
            except Exception:
                # Recording the failure itself failed (DB unavailable); the scan retries next cycle.
                pass
            raise

        self._finish_job(job_id, "completed")
        self.log.info(
            f"GC: {newly_orphaned} newly orphaned, {cleared} re-referenced, "
            f"{deleted} object(s) deleted (grace period {config.VERSION_GC_GRACE_PERIOD}s) "
            f"in {time.time() - t_start:.1f}s"
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

            def _mark_vanished():
                for norm_key in vanished:
                    conn.execute(
                        "UPDATE files SET deleted=1 WHERE norm_key=?", (norm_key,)
                    )
                conn.commit()

            self._retry_locked(_mark_vanished)
            for norm_key in vanished:
                self._known_state.pop(norm_key, None)

    def _note_slow_pass(self, label: str, seconds: float):
        """Log a pass that took long, rate-limited; says what to try (5.41)."""
        if seconds < _SLOW_PASS_SECONDS:
            return
        now = time.monotonic()
        if now - getattr(self, "_slow_pass_logged_at", -_SLOW_PASS_LOG_EVERY) < (
            _SLOW_PASS_LOG_EVERY
        ):
            return
        self._slow_pass_logged_at = now
        self.log.warning(
            f"{label} pass took {seconds:.1f}s: the tracked folders are big or the disk is "
            "busy. The engine now waits about three times as long as a pass takes before the "
            "next one, so it stays idle most of the time; track fewer folders, or switch the "
            "watcher off (VERSION_WATCH_ENABLED) and let the scanner find changes, to cut "
            "the disk work further."
        )

    def _watcher_loop(self):
        self._watcher_running = True
        self._set_meta("watcher_running", "1")
        self.log.info(f"Watcher started (poll interval {_WATCH_POLL_INTERVAL}s).")
        while not self._shutdown_event.is_set():
            wait = _WATCH_POLL_INTERVAL
            if not self._stop_scheduling.is_set():
                # Skip this round when the scanner is in the middle of the same pass.
                if self._pass_lock.acquire(blocking=False):
                    try:
                        started = time.monotonic()
                        self._reconcile_once()
                        took = time.monotonic() - started
                        self._note_slow_pass("Watcher", took)
                        wait = _next_pass_wait(_WATCH_POLL_INTERVAL, took)
                    except Exception as e:
                        if _is_lock_error(e):
                            self.log.warning(f"Watcher pass hit a locked database: {e}")
                        else:
                            self.log.error(
                                f"Watcher reconcile error: {e}", exc_info=True
                            )
                    finally:
                        self._pass_lock.release()
            self._shutdown_event.wait(wait)
        self._watcher_running = False
        self._set_meta("watcher_running", "0")
        self.log.info("Watcher stopped.")

    def checkpoint_wal_if_large(self, after: str):
        """5.45.1: at the end of a GC or purge pass, merge the write-ahead log into the database
        and truncate the file, but only when it is above the limit (VERSION_WAL_SIZE_LIMIT_MB,
        at most 64 MB). Waits at most _WAL_CHECKPOINT_BUSY_MS for readers and writers: a busy
        answer is not an error (nothing is lost, the next pass tries again). Runs in the calling
        engine thread on its own connection, takes no lock and uses no asyncio. Never raises;
        returns the CheckpointResult, or None when nothing was attempted."""
        try:
            result = version_wal.checkpoint_if_larger(
                self._connect(),
                self.db_path,
                _wal_limit_bytes(),
                busy_timeout_ms=_WAL_CHECKPOINT_BUSY_MS,
            )
        except Exception as e:
            self.log.warning(f"WAL checkpoint after {after} failed: {e}")
            return None
        if result is None:
            return None
        limit = version_wal.human_bytes(_wal_limit_bytes())
        if result.completed:
            self.log.info(
                f"WAL checkpoint after {after}: the log file was "
                f"{version_wal.human_bytes(result.wal_before)} (limit {limit}); "
                f"{result.mode} finished in {result.seconds:.1f}s, now "
                f"{version_wal.human_bytes(result.wal_after)}."
            )
            return result
        now = time.monotonic()
        last = self._wal_busy_logged_at
        if last is None or now - last >= _WAL_BUSY_LOG_EVERY:
            self._wal_busy_logged_at = now
            reason = result.error or "a reader or writer kept it busy"
            self.log.warning(
                f"WAL checkpoint after {after} did not finish ({reason}); the log file is "
                f"{version_wal.human_bytes(result.wal_after)} (limit {limit}). Nothing is "
                "lost; the next pass tries again."
            )
        return result

    def _scanner_loop(self):
        self._scanner_running = True
        self._set_meta("scanner_running", "1")
        self.log.info(f"Scanner started (interval {config.VERSION_SCAN_INTERVAL}s).")
        while not self._shutdown_event.is_set():
            wait = config.VERSION_SCAN_INTERVAL
            if not self._stop_scheduling.is_set():
                try:
                    started = time.monotonic()
                    with self._pass_lock:  # one full pass at a time (watcher / scanner)
                        self._reconcile_once()
                    took = time.monotonic() - started
                    self._note_slow_pass("Scanner", took)
                    wait = _next_pass_wait(config.VERSION_SCAN_INTERVAL, took)
                    self._retry_locked(self.run_gc, delays=(2, 4, 8))
                    self.checkpoint_wal_if_large("GC")
                    self._retry_locked(
                        self._set_meta,
                        "last_scan",
                        time.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                except Exception as e:
                    if _is_lock_error(e):
                        self.log.warning(
                            f"Scanner pass hit a locked database ({e}); "
                            "will retry at the next interval."
                        )
                    else:
                        self.log.error(f"Scanner error: {e}", exc_info=True)
            self._shutdown_event.wait(wait)
        self._scanner_running = False
        self._set_meta("scanner_running", "0")
        self.log.info("Scanner stopped.")

    # ------------------------------------------------------------------
    # Background purge of versions whose file no longer exists (5.45, on by default)
    #
    # The engine never ages out the versions of a DELETED file (retention only runs when the
    # same file gets a new snapshot). tools/purge_missing_versions.py does it by hand; this
    # does it slowly in the engine's own `ve-purge` thread, built like the scanner: a plain
    # thread of this worker process, stopped through _shutdown_event, no asyncio anywhere, no
    # thread pool, nothing shared with the web server (a separate OS process). The decision
    # logic is helpers/version_purge.py, the same code the tool runs.
    # ------------------------------------------------------------------

    def _purge_settings(self):
        """The five settings, read at the start of every pass and clamped to safe values."""
        return {
            "min_age_days": max(
                0.0, float(getattr(config, "VERSION_PURGE_MISSING_MIN_AGE_DAYS", 30))
            ),
            "interval": max(
                60.0, float(getattr(config, "VERSION_PURGE_MISSING_INTERVAL", 3600))
            ),
            "max_files": max(
                1,
                int(getattr(config, "VERSION_PURGE_MISSING_MAX_FILES_PER_PASS", 5000)),
            ),
            "batch_pause": min(
                5.0,
                max(
                    0.0,
                    float(getattr(config, "VERSION_PURGE_MISSING_BATCH_PAUSE", 0.05)),
                ),
            ),
        }

    def _get_meta(self, key, default=None):
        row = (
            self._connect()
            .execute("SELECT value FROM engine_metadata WHERE key=?", (key,))
            .fetchone()
        )
        return default if row is None else row[0]

    def run_purge_missing_pass(self):
        """ONE pass of the background purge; returns the PassResult, or None when the feature
        is off or another pass is running. Called by the `ve-purge` thread; public so a test
        can drive a pass without waiting for the interval."""
        if not getattr(config, "VERSION_PURGE_MISSING_ENABLED", False):
            return None
        if not self._purge_pass_lock.acquire(blocking=False):
            return None
        try:
            settings = self._purge_settings()
            try:
                cursor = int(self._get_meta(_META_PURGE_CURSOR, 0))
            except (TypeError, ValueError):
                cursor = 0
            result = version_purge.run_pass(
                self._connect(),
                version_purge.scope_dirs_from(config),
                min_age_days=settings["min_age_days"],
                max_files=settings["max_files"],
                batch_pause=settings["batch_pause"],
                undo_dir=self.storage_dir,
                stop=self._shutdown_event,
                cursor=cursor,
                write_lock=self._maintenance_lock,
            )
            self._log_purge_result(result)
            if result.status == "completed":
                self._retry_locked(
                    self._set_meta, _META_PURGE_CURSOR, result.cursor_next
                )
                self._retry_locked(
                    self._set_meta,
                    _META_PURGE_LAST,
                    time.strftime("%Y-%m-%d %H:%M:%S")
                    + f" examined={result.examined} purged_files={result.purged_files}"
                    f" purged_versions={result.purged_versions}",
                )
            # An undo file is only useful while the chunks can still come back: the GC frees
            # them VERSION_GC_GRACE_PERIOD after the soft-delete, so keep the file a day longer.
            version_purge.prune_auto_undo_files(
                self.storage_dir, config.VERSION_GC_GRACE_PERIOD + 86400
            )
            return result
        finally:
            self._purge_pass_lock.release()

    def _log_purge_result(self, r):
        if r.status == "skipped":
            now = time.monotonic()
            last = self._purge_skip_logged_at
            if last is None or now - last >= _PURGE_SKIP_LOG_EVERY:
                self._purge_skip_logged_at = now
                self.log.warning(
                    f"Purge-missing pass skipped, nothing was changed: {r.reason}. A tracked "
                    'folder or drive that is missing, empty or unreadable means "cannot '
                    'tell", so nothing is purged until it is back.'
                )
            return
        if r.status == "stopped":
            self.log.info(
                f"Purge-missing pass stopped by the shutdown after {r.examined} file(s) "
                f"({r.purged_versions} version(s) soft-deleted so far); it resumes at "
                f"file_id {r.cursor_start} after the restart."
            )
            return
        sweep = ", sweep of the whole table complete" if r.wrapped else ""
        undo = f"; undo file {os.path.basename(r.undo_file)}" if r.undo_file else ""
        sample = f" (for example {r.unsure_sample})" if r.unsure_sample else ""
        self.log.info(
            f"Purge-missing pass: looked at {r.examined} file(s) "
            f"(file_id {r.cursor_start} -> {r.cursor_next}{sweep}), {r.present} present, "
            f"{r.gone} gone, {r.unsure} left alone{sample}, {r.reappeared} reappeared; "
            f"soft-deleted {r.purged_versions} version(s) of {r.purged_files} file(s), "
            f"{r.logical_bytes} byte(s) of version data (the GC frees the disk space after "
            f"{config.VERSION_GC_GRACE_PERIOD}s){undo}; took {r.seconds:.1f}s"
        )

    def _purge_loop(self):
        self._purge_running = True
        self._set_meta(_META_PURGE_RUNNING, "1")
        self.log.info(
            "Background purge of deleted files' versions started "
            f"(every {self._purge_settings()['interval']:.0f}s, first pass in "
            f"{_PURGE_START_DELAY:.0f}s, at most "
            f"{self._purge_settings()['max_files']} files per pass)."
        )
        self._shutdown_event.wait(_PURGE_START_DELAY)
        while not self._shutdown_event.is_set():
            wait = self._purge_settings()["interval"]
            if not self._stop_scheduling.is_set():
                try:
                    started = time.monotonic()
                    self.run_purge_missing_pass()
                    self.checkpoint_wal_if_large("purge")
                    wait = _next_pass_wait(wait, time.monotonic() - started)
                except Exception as e:
                    try:
                        self._connect().rollback()  # never leave a txn/gate held
                    except sqlite3.Error:
                        # Rollback on a broken connection can fail; the error below is what matters.
                        pass
                    if _is_lock_error(e):
                        self.log.warning(
                            f"Purge-missing pass hit a locked database ({e}); "
                            "will retry at the next interval."
                        )
                    else:
                        self.log.error(f"Purge-missing error: {e}", exc_info=True)
            self._shutdown_event.wait(wait)
        self._purge_running = False
        self._set_meta(_META_PURGE_RUNNING, "0")
        self.log.info("Background purge stopped.")

    # ------------------------------------------------------------------
    # Object compression (5.47) - VERSION_COMPRESSION_PLAN.md sections 6.5 to 6.8
    #
    # The `ve-compress` thread turns raw objects into `<sha>.zst` files, one object at a time,
    # and never changes an object in place: the raw file stays until the `.zst` was decoded
    # back and compared (size + SHA-256) when it was made, and again just before the raw copy is
    # removed by the sweep. At every instant at least one complete valid form exists, so a
    # crash, a kill or a full disk at any point leaves the store readable; the next pass only
    # has to finish or redo the step. All of it is synchronous code of THIS process' thread
    # (or of a CLI tool); the web server never compresses, it only decodes while it reads.
    # ------------------------------------------------------------------

    def _compress_settings(self):
        """The four settings, read at the start of every batch and clamped to safe values."""

        def number(name, default, low, high):
            try:
                value = float(getattr(config, name, default))
            except (TypeError, ValueError):
                value = float(default)
            if value != value:  # NaN
                value = float(default)
            return min(high, max(low, value))

        return {
            "level": version_zstd.clamp_level(
                getattr(config, "VERSION_COMPRESSION_LEVEL", version_zstd.DEFAULT_LEVEL)
            ),
            "min_saving": number("VERSION_COMPRESSION_MIN_SAVING_PERCENT", 5, 0, 50),
            "busy": number("VERSION_COMPRESSION_BUSY_PERCENT", 25, 5, 100),
            "interval": number("VERSION_COMPRESSION_INTERVAL", 600, 60, 86400),
            # 5.47.1: the previous-version delta, its own switch (OFF by default)
            "delta": getattr(config, "VERSION_COMPRESSION_DELTA_ENABLED", False)
            is True,
            "delta_min_gain": number(
                "VERSION_COMPRESSION_DELTA_MIN_GAIN_PERCENT", 20, 1, 90
            ),
        }

    @staticmethod
    def _saving_percent(raw_size: int, stored_size: int) -> float:
        return 100.0 * (raw_size - stored_size) / raw_size if raw_size else 0.0

    @staticmethod
    def _remove_quietly(path: str) -> bool:
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            # Locked (Windows: a reader has it open) or not allowed: the caller decides.
            return False

    def _read_raw_verified(self, sha256_hex: str, size: int):
        """(bytes, None) when the raw file is whole and matches its SHA-256, else (None, reason)
        with reason 'missing' | 'unreadable' | 'size_mismatch' | 'hash_mismatch'."""
        try:
            with open(self._object_path(sha256_hex), "rb") as f:
                data = f.read(size + 1)
        except FileNotFoundError:
            return None, "missing"
        except OSError:
            return None, "unreadable"
        if len(data) != size:
            return None, "size_mismatch"
        if hashlib.sha256(data).hexdigest() != sha256_hex:
            return None, "hash_mismatch"
        return data, None

    def _zst_is_valid(self, sha256_hex: str, size: int, base_sha=None) -> bool:
        """True when `<sha>.zst` decodes to exactly `size` bytes whose SHA-256 is the object's
        name. Streams the decode, so a big object is never held whole. For a delta object
        `base_sha` is its base: that object is read (and hash-verified) first and the frame is
        decoded with it as the dictionary; a base that is missing or damaged is not valid.
        """
        digest = hashlib.sha256()
        total = 0
        zdict = None
        try:
            if base_sha:
                zdict = self._base_dictionary(sha256_hex, base_sha)
            with open(self._zst_path(sha256_hex), "rb") as f:
                for piece in version_zstd.iter_decode(f, size, zstd_dict=zdict):
                    digest.update(piece)
                    total += len(piece)
        except (OSError, version_zstd.CodecError, _ObjectError):
            return False
        return total == size and digest.hexdigest() == sha256_hex

    def _mark_compress_state(self, sha256_hex: str, state: str, level=None):
        """pending -> skip | failed for a raw object (never touches a compressed row)."""

        def write():
            conn = self._connect()
            conn.execute(
                "UPDATE objects SET compress_state=?, codec_level=? "
                "WHERE sha256=? AND codec='raw'",
                (state, level, sha256_hex),
            )
            conn.commit()

        self._retry_locked(write)

    def _log_corrupt(self, sha256_hex: str, what: str):
        self.log.error(
            f"Compression: object {sha256_hex[:12]}... {what}: possible disk corruption. "
            "The object was NOT changed and is marked 'failed'; "
            "./manage.sh version-manage compress --verify checks every compressed object."
        )

    def _commit_compressed(
        self, sha256_hex: str, stored_size: int, level, base_sha=None
    ):
        """Step 7: the `.zst` is published and verified; record it in ONE short transaction,
        under the lock the GC also takes, so a GC that deleted the object a moment ago cannot
        be followed by a row that points at nothing. Returns 'compressed' | 'already' |
        'dropped' (the object is gone: the stray `.zst` is removed) | 'base_unusable' (a delta
        whose base is no longer a plain, stored object, or that is itself somebody's base: the
        stray `.zst` is removed and nothing is recorded).

        For a delta (`base_sha` given) the same transaction re-checks everything the choice of
        the base rested on, because the GC and other writers may have moved since: the base is
        still a PLAIN object that is stored in some form, this object is not itself a base, and a
        base the GC had marked as an orphan is put back in use (the GC cannot run now).
        """

        def write():
            with self._maintenance_lock:
                conn = self._connect()
                if base_sha is not None:
                    base_row = conn.execute(
                        "SELECT base_sha FROM objects WHERE sha256=?", (base_sha,)
                    ).fetchone()
                    if (
                        base_row is None
                        or base_row[0] is not None
                        or base_sha == sha256_hex
                        or self._is_delta_base(conn, sha256_hex)
                        or not self._object_exists(base_sha)
                    ):
                        return "base_unusable"
                    conn.execute(
                        "UPDATE objects SET orphaned_since=NULL WHERE sha256=?",
                        (base_sha,),
                    )
                cur = conn.execute(
                    "UPDATE objects SET codec='zstd', stored_size=?, compress_state='done', "
                    "codec_level=?, compressed_at=?, base_sha=? WHERE sha256=? AND codec='raw'",
                    (stored_size, level, time.time(), base_sha, sha256_hex),
                )
                changed = cur.rowcount
                conn.commit()
                if changed:
                    return "compressed"
                gone = (
                    conn.execute(
                        "SELECT 1 FROM objects WHERE sha256=?", (sha256_hex,)
                    ).fetchone()
                    is None
                )
                return "dropped" if gone else "already"

        outcome = self._retry_locked(write)
        if outcome in ("dropped", "base_unusable"):
            self._remove_quietly(self._zst_path(sha256_hex))
        return outcome

    def _pick_delta_base(self, sha256_hex: str):
        """(base_sha, base_bytes) when this object can be stored as a delta, else None.

        The base is the SAME chunk of the file's previous completed version: the OLDEST
        completed version that uses this object is the one that INTRODUCED it (the newest one
        may well share the chunk with its own predecessor: the next edit touched another
        chunk), its predecessor, the same chunk index. When that chunk is itself a delta, its own base is used (so every delta of a chain of
        versions hangs on ONE plain object: depth 1). The base must be a plain object, stored,
        readable and hash-verified (it is read through the one read path), of a sane size, and
        this object must not itself be a base of another delta."""
        conn = self._connect()
        try:
            if self._is_delta_base(conn, sha256_hex):
                return None
            ref = conn.execute(
                "SELECT vo.version_id, vo.chunk_index, v.file_id FROM version_objects vo "
                "JOIN versions v ON v.version_id = vo.version_id "
                "WHERE vo.sha256=? AND v.status='completed' "
                "ORDER BY vo.version_id ASC LIMIT 1",
                (sha256_hex,),
            ).fetchone()
            if ref is None:
                return None
            prev = conn.execute(
                "SELECT version_id FROM versions WHERE file_id=? AND status='completed' "
                "AND version_id < ? ORDER BY version_id DESC LIMIT 1",
                (ref["file_id"], ref["version_id"]),
            ).fetchone()
            if prev is None:
                return None
            chunk = conn.execute(
                "SELECT sha256 FROM version_objects WHERE version_id=? AND chunk_index=?",
                (prev["version_id"], ref["chunk_index"]),
            ).fetchone()
            if chunk is None or chunk[0] == sha256_hex:
                return None
            base_sha = chunk[0]
            base_row = conn.execute(
                "SELECT size, base_sha FROM objects WHERE sha256=?", (base_sha,)
            ).fetchone()
            if base_row is not None and base_row["base_sha"]:
                base_sha = base_row["base_sha"]  # the anchor of the chain: depth 1
                base_row = conn.execute(
                    "SELECT size, base_sha FROM objects WHERE sha256=?", (base_sha,)
                ).fetchone()
            if (
                base_row is None
                or base_row["base_sha"] is not None
                or base_sha == sha256_hex
                or not version_zstd.MIN_OBJECT_SIZE
                <= base_row["size"]
                <= _DELTA_MAX_OBJECT_BYTES
            ):
                return None
            base_bytes = b"".join(
                self._iter_object_bytes(base_sha, base_row["size"], _READ_BLOCK, 1)
            )
        except (sqlite3.Error, _ObjectError):
            return None  # no usable base: the object is simply stored as a plain object
        return base_sha, base_bytes

    def _publish_and_commit(
        self, data, sha256_hex, size, level, min_saving, zdict=None, base_sha=None
    ) -> str:
        """Steps 5-7 for ONE candidate frame (plain, or a delta when `zdict` / `base_sha` are
        given): compress and PROVE it (decode with the same dictionary, compare size and
        SHA-256), keep it only if it saves enough, write it to tmp/, fsync, publish with an
        atomic rename, record it. A delta that cannot be used for any reason returns
        'delta_failed' | 'no_gain' | 'base_unusable' and the caller stores a plain object.
        """
        window_log = (
            version_zstd.delta_window_log(len(zdict.dict_content), size)
            if zdict is not None
            else None
        )
        try:
            frame = version_zstd.compress_verified(
                data, sha256_hex, level, zstd_dict=zdict, window_log=window_log
            )
        except version_zstd.CodecError as e:
            if zdict is not None:
                self.log.warning(
                    f"Compression: the delta of {sha256_hex[:12]}... did not survive its "
                    f"round trip check ({e}); it is stored as a plain object instead."
                )
                return "delta_failed"
            self._mark_compress_state(sha256_hex, "failed", level)
            self.log.error(
                f"Compression: object {sha256_hex[:12]}... did not survive the round trip "
                f"check at level {level} ({e}). It was NOT changed and is marked 'failed'."
            )
            return "failed"
        if len(frame) >= size or self._saving_percent(size, len(frame)) < min_saving:
            if zdict is not None:
                return "no_gain"
            self._mark_compress_state(sha256_hex, "skip", level)
            return "skipped"

        # write to tmp/, flush, fsync, then publish with an atomic rename: a reader or a crash
        # sees either no `.zst` or a complete one
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir=self.tmp_dir, prefix="zst_")
            with os.fdopen(fd, "wb") as out:
                out.write(frame)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp_path, self._zst_path(sha256_hex))
            tmp_path = None
        except OSError as e:
            if tmp_path:
                self._remove_quietly(tmp_path)
            self.log.warning(
                f"Compression: could not write the compressed copy of {sha256_hex[:12]}... "
                f"({e}); nothing was changed, it is tried again later."
            )
            return "error"
        return self._commit_compressed(sha256_hex, len(frame), level, base_sha)

    def compress_object(self, sha256_hex: str, level=None, min_saving=None) -> str:
        """Compress ONE object (plan 6.5). Returns:
        'compressed' (a verified `.zst` was published and recorded), 'skipped' (stays raw on
        purpose: too small / too big / already-compressed data / no real saving), 'failed' (the
        object failed its own SHA-256 or the round trip: marked, logged as an ERROR, never
        retried), 'adopted' / 'compressed' for an object whose `.zst` already existed (a crash
        between the publish and the record), 'missing' (the GC or another process removed it),
        'already' / 'dropped', or 'error' (a disk problem such as a full disk: nothing was
        recorded, the next batch tries again). Synchronous; the caller is a plain thread.
        """
        settings = self._compress_settings()
        level = settings["level"] if level is None else version_zstd.clamp_level(level)
        min_saving = settings["min_saving"] if min_saving is None else float(min_saving)
        row = (
            self._connect()
            .execute("SELECT size, codec FROM objects WHERE sha256=?", (sha256_hex,))
            .fetchone()
        )
        if row is None:
            return "missing"
        size, codec = row[0], row[1]
        if codec != "raw":
            return "already"
        has_raw = os.path.exists(self._object_path(sha256_hex))
        has_zst = os.path.exists(self._zst_path(sha256_hex))
        if not has_raw and not has_zst:
            return "missing"

        # Only a `.zst` is on disk (a crash after the sweep but before the record, or an
        # object restored from a copy): it is the only form there is, so adopt it only if it
        # is whole, else say so loudly.
        if not has_raw:
            if self._zst_is_valid(sha256_hex, size):
                self._commit_compressed(
                    sha256_hex, os.path.getsize(self._zst_path(sha256_hex)), None
                )
                return "adopted"
            self._mark_compress_state(sha256_hex, "failed")
            self._log_corrupt(
                sha256_hex,
                "exists only as a compressed file and that file does not verify",
            )
            return "failed"

        if size < version_zstd.MIN_OBJECT_SIZE or size > _COMPRESS_MAX_OBJECT_BYTES:
            self._mark_compress_state(sha256_hex, "skip")
            return "skipped"

        # Step 1: the raw object must be whole and match its name BEFORE anything is built
        # from it. A damaged object is reported and left exactly as it is.
        data, why = self._read_raw_verified(sha256_hex, size)
        if why == "missing":
            return "missing"
        if why == "unreadable":
            self.log.warning(
                f"Compression: object {sha256_hex[:12]}... could not be read right now; "
                "it is tried again later."
            )
            return "error"
        if why in ("size_mismatch", "hash_mismatch"):
            self._mark_compress_state(sha256_hex, "failed")
            self._log_corrupt(
                sha256_hex,
                (
                    "does not match its recorded size"
                    if why == "size_mismatch"
                    else "fails its own SHA-256"
                ),
            )
            return "failed"

        # A `.zst` next to a raw copy that is still 'raw' in the database: a crash between the
        # publish and the record. If it verifies, just record it; if not, it is rebuilt below.
        if has_zst:
            if self._zst_is_valid(sha256_hex, size):
                outcome = self._commit_compressed(
                    sha256_hex, os.path.getsize(self._zst_path(sha256_hex)), None
                )
                return "compressed" if outcome == "compressed" else outcome
            self._remove_quietly(self._zst_path(sha256_hex))

        effective = level
        if size > _COMPRESS_HIGH_LEVEL_BYTES:
            effective = min(level, _COMPRESS_HIGH_LEVEL_CAP)

        # Phase 4 (5.47.1, its own switch, OFF by default): is this object a changed chunk whose
        # earlier version is stored? Then it may be kept as a DELTA against that chunk.
        delta = None
        if settings["delta"] and size <= _DELTA_MAX_OBJECT_BYTES:
            delta = self._pick_delta_base(sha256_hex)

        # Steps 3-4: a quick attempt at a low level; data that does not even shrink by 1 %
        # (jpg, zip, many pdf) stays raw without paying for the slow level, unless a delta
        # against its earlier version is far smaller (a changed chunk of an incompressible file).
        plain_probe = None
        if effective > version_zstd.PROBE_LEVEL or delta is not None:
            try:
                plain_probe = len(version_zstd.compress(data, version_zstd.PROBE_LEVEL))
            except version_zstd.CodecError as e:
                self.log.warning(
                    f"Compression: zstd failed on {sha256_hex[:12]}...: {e}"
                )
                return "error"
        plain_ok = (
            plain_probe is None
            or self._saving_percent(size, plain_probe)
            >= version_zstd.PROBE_MIN_SAVING_PERCENT
        )

        zdict = None
        if delta is not None:
            zdict = version_zstd.raw_dictionary(delta[1])
            try:
                delta_probe = len(
                    version_zstd.compress(
                        data,
                        version_zstd.PROBE_LEVEL,
                        zstd_dict=zdict,
                        window_log=version_zstd.delta_window_log(len(delta[1]), size),
                    )
                )
            except version_zstd.CodecError:
                delta_probe = None
            if (
                delta_probe is None
                or delta_probe > plain_probe * (1 - settings["delta_min_gain"] / 100.0)
                or self._saving_percent(size, delta_probe)
                < version_zstd.PROBE_MIN_SAVING_PERCENT
            ):
                zdict = None  # not worth a dependency on another object

        if zdict is not None:
            outcome = self._publish_and_commit(
                data, sha256_hex, size, effective, min_saving, zdict, delta[0]
            )
            if outcome not in ("delta_failed", "no_gain", "base_unusable"):
                return outcome
            # the delta could not be used: fall through to a plain object

        if not plain_ok:
            self._mark_compress_state(sha256_hex, "skip", version_zstd.PROBE_LEVEL)
            return "skipped"
        return self._publish_and_commit(data, sha256_hex, size, effective, min_saving)

    # ---- the sweep: remove raw copies whose compressed copy is proven good --------------------

    def _revert_to_raw(self, sha256_hex: str):
        """A compressed row whose `.zst` is not good but whose raw copy still exists: put the
        row back to raw and mark it failed (never compress it again by itself)."""

        def write():
            with self._maintenance_lock:
                conn = self._connect()
                conn.execute(
                    "UPDATE objects SET codec='raw', stored_size=NULL, "
                    "compress_state='failed', codec_level=NULL, compressed_at=NULL, "
                    "base_sha=NULL WHERE sha256=? AND codec='zstd'",
                    (sha256_hex,),
                )
                conn.commit()

        self._retry_locked(write)

    def sweep_raw_copies(self, grace=None, limit=None, pause=None, busy=100.0) -> dict:
        """Remove the raw copy of every object that was compressed more than `grace` seconds ago
        (default _COMPRESS_SWEEP_GRACE), but ONLY after the `.zst` was decoded and hashed once
        more: the raw file is the last other copy, so it goes only on proof. Returns counts:
        checked, removed, already_gone (the raw copy was not there), busy (the file could not be
        removed now, e.g. a reader has it open on Windows: next time), bad (the `.zst` did not
        verify: the row went back to raw), lost (neither form is good: ERROR, nothing to do).
        `pause(seconds)` is called between objects to keep a duty cycle (return True = stop).
        """
        grace = _COMPRESS_SWEEP_GRACE if grace is None else float(grace)
        cutoff = time.time() - grace
        result = dict.fromkeys(
            ("checked", "removed", "already_gone", "busy", "bad", "lost"), 0
        )
        conn = self._connect()
        last_rowid = 0
        while limit is None or result["checked"] < limit:
            rows = conn.execute(
                "SELECT rowid, sha256, size, base_sha FROM objects WHERE rowid > ? "
                "AND codec='zstd' AND compress_state='done' AND compressed_at <= ? "
                "ORDER BY rowid LIMIT ?",
                (last_rowid, cutoff, _COMPRESS_PAGE),
            ).fetchall()
            if not rows:
                break
            for rowid, sha, size, base_sha in rows:
                last_rowid = rowid
                if self._shutdown_event.is_set():
                    return result
                started = time.monotonic()
                result["checked"] += 1
                raw_path = self._object_path(sha)
                if not self._zst_is_valid(sha, size, base_sha):
                    # The compressed copy does not verify. The raw copy (if it still exists
                    # AND verifies) is the only good one: keep it and put the row back to
                    # raw. The bad `.zst` is left where it is (readers prefer the raw file,
                    # the GC removes both forms later): one failed read, which may be a
                    # transient error, never deletes a file.
                    if self._read_raw_verified(sha, size)[1] is None:
                        self.log.error(
                            f"Compression: the compressed copy of object {sha[:12]}... does not "
                            "verify; the raw copy is kept and the object is marked 'failed'."
                        )
                        self._revert_to_raw(sha)
                        result["bad"] += 1
                    else:
                        self.log.error(
                            f"Compression: object {sha[:12]}... has no good copy in either "
                            "form: possible disk corruption. Nothing can be done by the engine."
                        )
                        result["lost"] += 1
                    continue
                if os.path.exists(raw_path):
                    if not self._remove_quietly(raw_path):
                        result["busy"] += 1
                        continue
                    result["removed"] += 1
                else:
                    result["already_gone"] += 1

                def swept(sha=sha):
                    c = self._connect()
                    c.execute(
                        "UPDATE objects SET compress_state='swept' "
                        "WHERE sha256=? AND codec='zstd'",
                        (sha,),
                    )
                    c.commit()

                self._retry_locked(swept)
                if pause and 0 < busy < 100:
                    elapsed = time.monotonic() - started
                    if pause(min(_COMPRESS_MAX_PAUSE, elapsed * (100.0 / busy - 1.0))):
                        return result
        return result

    # ---- the batch: what the thread (and the tests) run ---------------------------------------

    def run_compress_batch(self, limit=None, pause=None) -> dict:
        """Compress the next raw objects, in row order, resuming where the last batch stopped
        (`compress_cursor` in engine_metadata), until nothing is left, `limit` objects were
        looked at, an 'error' outcome (disk full ...), or the shutdown. Returns a dict of
        counts, or None when compression is off / zstd is unusable / another batch is running.
        `pause(seconds)` keeps the duty cycle between objects (the thread passes
        `_shutdown_event.wait`; returning True means stop). The raw copies of objects compressed
        earlier are swept first and last."""
        if not getattr(config, "VERSION_COMPRESSION_ENABLED", False):
            return None
        if not version_zstd.available():
            return None
        if not self._compress_pass_lock.acquire(blocking=False):
            return None
        try:
            return self._run_compress_batch(limit, pause)
        finally:
            self._compress_pass_lock.release()

    def _run_compress_batch(self, limit, pause):
        settings = self._compress_settings()
        busy = settings["busy"]
        started = time.monotonic()
        counts = {
            "looked_at": 0,
            "compressed": 0,
            "skipped": 0,
            "failed": 0,
            "missing": 0,
            "error": 0,
            "adopted": 0,
            "delta": 0,
            "saved_bytes": 0,
            "swept": 0,
            "stopped": False,
        }
        conn = self._connect()
        try:
            cursor = int(self._get_meta(_META_COMPRESS_CURSOR, 0))
        except (TypeError, ValueError):
            cursor = 0

        sweep = self.sweep_raw_copies(pause=pause, busy=busy)
        counts["swept"] += sweep["removed"]

        if cursor == 0:
            # the start of a sweep through the table: say once that tiny objects stay raw
            with self._maintenance_lock:
                version_compress.mark_small_objects_skipped(
                    conn, version_zstd.MIN_OBJECT_SIZE
                )
                conn.commit()

        wrapped = False
        while not self._shutdown_event.is_set() and (
            limit is None or counts["looked_at"] < limit
        ):
            rows = version_compress.candidate_batch(
                conn, cursor, _COMPRESS_PAGE, version_zstd.MIN_OBJECT_SIZE
            )
            if not rows:
                if cursor == 0 or wrapped:
                    break  # nothing pending anywhere: idle until the next interval
                wrapped = True
                cursor = 0
                self._retry_locked(self._set_meta, _META_COMPRESS_CURSOR, 0)
                continue
            for rowid, sha, size in rows:
                if self._shutdown_event.is_set() or (
                    limit is not None and counts["looked_at"] >= limit
                ):
                    counts["stopped"] = self._shutdown_event.is_set()
                    break
                t0 = time.monotonic()
                outcome = self.compress_object(sha)
                cursor = rowid
                counts["looked_at"] += 1
                if outcome == "compressed":
                    counts["compressed"] += 1
                    stored = conn.execute(
                        "SELECT stored_size, base_sha FROM objects WHERE sha256=?",
                        (sha,),
                    ).fetchone()
                    if stored and stored[0] is not None:
                        counts["saved_bytes"] += size - stored[0]
                    if stored and stored[1]:
                        counts["delta"] += 1
                elif outcome in counts:
                    counts[outcome] += 1
                if outcome == "error":
                    break  # a disk problem: stop, wait for the next interval
                if counts["looked_at"] % _COMPRESS_PROGRESS_EVERY == 0:
                    self._retry_locked(self._set_meta, _META_COMPRESS_CURSOR, cursor)
                    self._log_compress_progress(counts, started, settings)
                    self.checkpoint_wal_if_large("compress")
                if pause and 0 < busy < 100:
                    elapsed = time.monotonic() - t0
                    if pause(min(_COMPRESS_MAX_PAUSE, elapsed * (100.0 / busy - 1.0))):
                        counts["stopped"] = True
                        break
            else:
                continue
            break  # the inner loop was left early (error, limit, shutdown)

        self._retry_locked(self._set_meta, _META_COMPRESS_CURSOR, cursor)
        if counts["looked_at"] or counts["swept"]:
            sweep = self.sweep_raw_copies(pause=pause, busy=busy)
            counts["swept"] += sweep["removed"]
            self._log_compress_progress(counts, started, settings, final=True)
            self._retry_locked(
                self._set_meta,
                _META_COMPRESS_LAST,
                time.strftime("%Y-%m-%d %H:%M:%S")
                + f" looked_at={counts['looked_at']} compressed={counts['compressed']}"
                f" skipped={counts['skipped']} failed={counts['failed']}"
                f" delta={counts['delta']}"
                f" saved_bytes={counts['saved_bytes']} raw_copies_removed={counts['swept']}",
            )
        return counts

    def _log_compress_progress(self, counts, started, settings, final=False):
        saved_mib = counts["saved_bytes"] / (1024 * 1024)
        self.log.info(
            f"Compression{' batch finished' if final else ' progress'}: looked at "
            f"{counts['looked_at']} object(s) (level {settings['level']}), "
            f"{counts['compressed']} compressed ({counts['delta']} as deltas), "
            f"{counts['skipped']} left raw, "
            f"{counts['failed']} failed, {saved_mib:.1f} MiB saved so far, "
            f"{counts['swept']} raw copy(ies) removed; took {time.monotonic() - started:.0f}s"
        )

    def _compress_loop(self):
        self._compress_running = True
        self._set_meta(_META_COMPRESS_RUNNING, "1")
        s = self._compress_settings()
        self.log.info(
            f"Background compression of stored objects started (zstd level {s['level']}, "
            f"busy at most {s['busy']:.0f}% of the time, looks again every "
            f"{s['interval']:.0f}s when idle, first pass in {_COMPRESS_START_DELAY:.0f}s)."
        )
        self._shutdown_event.wait(_COMPRESS_START_DELAY)
        while not self._shutdown_event.is_set():
            wait = self._compress_settings()["interval"]
            if not self._stop_scheduling.is_set():
                try:
                    self.run_compress_batch(pause=self._shutdown_event.wait)
                    self.checkpoint_wal_if_large("compress")
                except Exception as e:
                    try:
                        self._connect().rollback()  # never leave a txn/gate held
                    except sqlite3.Error:
                        # Rollback on a broken connection can fail; the error below is what matters.
                        pass
                    if _is_lock_error(e):
                        self.log.warning(
                            f"Compression hit a locked database ({e}); will retry at the "
                            "next interval."
                        )
                    else:
                        self.log.error(f"Compression error: {e}", exc_info=True)
            self._shutdown_event.wait(wait)
        self._compress_running = False
        self._set_meta(_META_COMPRESS_RUNNING, "0")
        self.log.info("Background compression stopped.")

    # ---- by hand: verify everything, and the way back to raw files ----------------------------

    def verify_compressed(self, limit=None, pause=None, busy=100.0) -> dict:
        """Read-only integrity check of every compressed object: decode the `.zst` and compare
        size and SHA-256. Changes nothing. Returns counts: checked, ok, bad (the `.zst` does
        not verify but a good raw copy exists), lost (no good copy at all) and `examples`.
        """
        result = {"checked": 0, "ok": 0, "bad": 0, "lost": 0, "examples": []}
        conn = self._connect()
        last_rowid = 0
        while limit is None or result["checked"] < limit:
            rows = conn.execute(
                "SELECT rowid, sha256, size, base_sha FROM objects WHERE rowid > ? "
                "AND codec='zstd' ORDER BY rowid LIMIT ?",
                (last_rowid, _COMPRESS_PAGE),
            ).fetchall()
            if not rows:
                break
            for rowid, sha, size, base_sha in rows:
                last_rowid = rowid
                started = time.monotonic()
                result["checked"] += 1
                if self._zst_is_valid(sha, size, base_sha):
                    result["ok"] += 1
                else:
                    raw_ok = self._read_raw_verified(sha, size)[1] is None
                    result["bad" if raw_ok else "lost"] += 1
                    if len(result["examples"]) < 10:
                        result["examples"].append(sha[:16])
                if pause and 0 < busy < 100:
                    elapsed = time.monotonic() - started
                    if pause(min(_COMPRESS_MAX_PAUSE, elapsed * (100.0 / busy - 1.0))):
                        return result
        return result

    def decompress_plan(self) -> dict:
        """What converting every compressed object back to a raw file would need:
        {'objects', 'raw_bytes' (the bytes that have to be written: only objects whose raw
        copy is gone count), 'free_bytes' (on the drive of the object store)}."""
        conn = self._connect()
        need_n = need_b = 0
        last_rowid = 0
        while True:
            rows = conn.execute(
                "SELECT rowid, sha256, size FROM objects WHERE rowid > ? AND codec='zstd' "
                "ORDER BY rowid LIMIT 500",
                (last_rowid,),
            ).fetchall()
            if not rows:
                break
            for rowid, sha, size in rows:
                last_rowid = rowid
                if not os.path.exists(self._object_path(sha)):
                    need_n += 1
                    need_b += size
        total_n = conn.execute(
            "SELECT COUNT(*) FROM objects WHERE codec='zstd'"
        ).fetchone()[0]
        try:
            free = shutil.disk_usage(self.objects_dir).free
        except OSError:
            free = 0
        return {
            "compressed_objects": total_n,
            "objects": need_n,
            "raw_bytes": need_b,
            "free_bytes": free,
        }

    def _commit_raw(self, sha256_hex: str) -> bool:
        """The row of a decompressed object goes back to raw; 'skip' keeps the compressor from
        picking it up again. False when the row is gone or already changed."""

        def write():
            with self._maintenance_lock:
                conn = self._connect()
                cur = conn.execute(
                    "UPDATE objects SET codec='raw', stored_size=NULL, compress_state='skip', "
                    "codec_level=NULL, compressed_at=NULL, base_sha=NULL "
                    "WHERE sha256=? AND codec='zstd'",
                    (sha256_hex,),
                )
                changed = cur.rowcount
                conn.commit()
                return changed

        return bool(self._retry_locked(write))

    def decompress_object(self, sha256_hex: str) -> str:
        """Turn ONE compressed object back into a raw file (the way back to the 5.45.1 layout).
        Returns 'decompressed', 'not_compressed', 'lost' (no good copy of it: ERROR) or 'error'
        (disk problem: nothing recorded, safe to run again). The raw file is built from the
        `.zst` into tmp/, verified against the SHA-256 while it is written, fsynced and renamed
        into place; only then is the row changed and the `.zst` removed, so every step can be
        interrupted and repeated."""
        row = (
            self._connect()
            .execute(
                "SELECT size, codec, base_sha FROM objects WHERE sha256=?",
                (sha256_hex,),
            )
            .fetchone()
        )
        if row is None or row[1] != "zstd":
            return "not_compressed"
        size, base_sha = row[0], row[2]
        raw_path = self._object_path(sha256_hex)
        zst_path = self._zst_path(sha256_hex)
        raw_ok = False
        if os.path.exists(raw_path):
            why = self._read_raw_verified(sha256_hex, size)[1]
            raw_ok = why is None
            if why == "unreadable":
                return "error"  # maybe a transient problem: touch nothing, run again
            if why in ("size_mismatch", "hash_mismatch"):
                self._remove_quietly(
                    raw_path
                )  # definitely damaged: rebuilt from the .zst
        if not raw_ok:
            if not os.path.exists(zst_path):
                self.log.error(
                    f"Decompress: object {sha256_hex[:12]}... has no good copy in either form."
                )
                return "lost"
            tmp_path = None
            try:
                digest = hashlib.sha256()
                total = 0
                zdict = (
                    self._base_dictionary(sha256_hex, base_sha) if base_sha else None
                )
                fd, tmp_path = tempfile.mkstemp(dir=self.tmp_dir, prefix="raw_")
                with os.fdopen(fd, "wb") as out, open(zst_path, "rb") as src:
                    for piece in version_zstd.iter_decode(src, size, zstd_dict=zdict):
                        digest.update(piece)
                        total += len(piece)
                        out.write(piece)
                    out.flush()
                    os.fsync(out.fileno())
                if total != size or digest.hexdigest() != sha256_hex:
                    self._remove_quietly(tmp_path)
                    self.log.error(
                        f"Decompress: the compressed copy of object {sha256_hex[:12]}... "
                        "does not verify: possible disk corruption. It was NOT changed."
                    )
                    return "lost"
                os.makedirs(os.path.dirname(raw_path), exist_ok=True)
                os.replace(tmp_path, raw_path)
                tmp_path = None
            except _ObjectError as e:
                if tmp_path:
                    self._remove_quietly(tmp_path)
                self.log.error(
                    f"Decompress: object {sha256_hex[:12]}... is stored as a delta and "
                    f"cannot be rebuilt ({e.detail or e.kind}): possible disk corruption. "
                    "It was NOT changed."
                )
                return "lost"
            except version_zstd.CodecError:
                if tmp_path:
                    self._remove_quietly(tmp_path)
                self.log.error(
                    f"Decompress: the compressed copy of object {sha256_hex[:12]}... is "
                    "damaged: possible disk corruption. It was NOT changed."
                )
                return "lost"
            except OSError as e:
                if tmp_path:
                    self._remove_quietly(tmp_path)
                self.log.warning(
                    f"Decompress: could not write the raw file of {sha256_hex[:12]}... "
                    f"({e}); nothing was changed."
                )
                return "error"
        if not self._commit_raw(sha256_hex):
            # The row is gone (the GC removed the object) or already raw: tidy only what we made.
            if not os.path.exists(zst_path):
                return "not_compressed"
        self._remove_quietly(zst_path)
        return "decompressed"

    def decompress_all(self, pause=None, busy=100.0, limit=None) -> dict:
        """decompress_object() for every compressed object, in row order. Returns counts:
        decompressed, lost, error, other."""
        result = dict.fromkeys(("decompressed", "lost", "error", "other", "checked"), 0)
        conn = self._connect()
        last_rowid = 0
        while limit is None or result["checked"] < limit:
            rows = conn.execute(
                "SELECT rowid, sha256 FROM objects WHERE rowid > ? AND codec='zstd' "
                "ORDER BY rowid LIMIT ?",
                (last_rowid, _COMPRESS_PAGE),
            ).fetchall()
            if not rows:
                break
            for rowid, sha in rows:
                last_rowid = rowid
                started = time.monotonic()
                outcome = self.decompress_object(sha)
                result["checked"] += 1
                result[outcome if outcome in result else "other"] += 1
                if outcome == "error":
                    return result  # disk problem: stop, nothing is lost, run again
                if pause and 0 < busy < 100:
                    elapsed = time.monotonic() - started
                    if pause(min(_COMPRESS_MAX_PAUSE, elapsed * (100.0 / busy - 1.0))):
                        return result
        return result

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
                try:
                    self._connect().rollback()  # never leave a txn/gate held
                except sqlite3.Error:
                    # Rollback on a broken connection can fail; the original error was already handled.
                    pass
                self.log.error(
                    f"Worker {worker_index} snapshot error for {display_path}: {e}",
                    exc_info=not _is_lock_error(e),
                )
                if _is_lock_error(e):
                    # Even the bookkeeping writes couldn't get the lock. Forget
                    # the cached (mtime, size) so the watcher re-queues this
                    # file instead of losing the capture until it changes again.
                    self._known_state.pop(_normalize_path(display_path), None)
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

        if getattr(config, "VERSION_PURGE_MISSING_ENABLED", False):
            self._purge_thread = threading.Thread(
                target=self._purge_loop, daemon=True, name="ve-purge"
            )
            self._purge_thread.start()

        if getattr(config, "VERSION_COMPRESSION_ENABLED", False):
            if version_zstd.self_test():
                self._compress_thread = threading.Thread(
                    target=self._compress_loop, daemon=True, name="ve-compress"
                )
                self._compress_thread.start()
            else:
                self.log.warning(
                    "VERSION_COMPRESSION_ENABLED is true but zstd is not usable in this "
                    "Python (it needs Python 3.14 or `pip install backports.zstd`): "
                    "compression stays off and objects are stored raw. Compressed objects, "
                    "if there are any, cannot be read until zstd works."
                )

        self.log.info(
            f"Version Engine started. pid={os.getpid()} db={self.db_path} "
            f"storage={self.storage_dir} workers={config.VERSION_WORKER_COUNT} "
            f"watch={config.VERSION_WATCH_ENABLED} scan={config.VERSION_SCAN_ENABLED} "
            f"purge_missing={getattr(config, 'VERSION_PURGE_MISSING_ENABLED', False)} "
            f"compress={self._compress_thread is not None}"
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
            # Draining the queue is best effort during shutdown.
            pass

        for t in self._workers:
            t.join(timeout=max(0, deadline - time.time()))
        if self._scanner_thread:
            self._scanner_thread.join(timeout=1)
        if self._watcher_thread:
            self._watcher_thread.join(timeout=1)
        if self._purge_thread:
            # It looks at _shutdown_event at every file and every write batch, so this is
            # normally immediate; the deadline is the same drain window the workers get.
            self._purge_thread.join(timeout=max(1, deadline - time.time()))
        if self._compress_thread:
            # It looks at _shutdown_event between objects and every pause is
            # _shutdown_event.wait, so this ends after the object in hand (a few seconds at
            # level 22 at the very most).
            self._compress_thread.join(timeout=max(1, deadline - time.time()))

        try:
            conn = self._connect()
            conn.close()
        except Exception:
            # Connection already closed.
            pass
        self.log.info("Graceful shutdown complete.")


class _DatabaseBusy(VersionEngineError):
    """A DB write hit SQLite's write lock (another writer held it past
    busy_timeout). Transient: the caller backs off and retries instead of
    recording a permanent failed version."""


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

    # Orphan guard: if the server process that spawned this worker dies
    # without stopping it (hard kill, crash), drain and exit instead of
    # scanning forever. No-op when started by hand (no parent PID in env).
    def _parent_gone():
        log.warning("Parent server process is gone - shutting the engine down.")
        engine.graceful_shutdown()

    parent_watch.start(
        _parent_gone,
        label="version_engine",
        grace=float(getattr(config, "VERSION_SHUTDOWN_TIMEOUT", 30)) + 5,
    )

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
