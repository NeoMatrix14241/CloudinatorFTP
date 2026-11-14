"""
helpers/version_wal.py - keep the Version Engine database's write-ahead log (WAL) small (5.45.1)
================================================================================================

Why this exists. SQLite in WAL mode appends every change to `version_engine.sqlite3-wal` and
merges it into the main file in a "checkpoint". A checkpoint does NOT shrink the -wal file: the
file is reused from its start and keeps the size of the biggest burst it ever saw. On the
owner's server a burst of purging and garbage collection left a 2.9 GB -wal file next to a
730 MB database; `PRAGMA wal_checkpoint(TRUNCATE)` returned (0, 0, 0) and the file went to
1 KB. (After a TRUNCATE the two counters are always 0, so that answer does not say whether
frames still had to be merged.) The engine is stopped with a hard kill, so SQLite never got
the chance to remove the file on a clean close either.

Two plain mechanisms, both here:

  1. `apply_journal_size_limit(conn, limit)`: `PRAGMA journal_size_limit`. After a checkpoint has
     reset the log, SQLite cuts the file back to this size. It is a setting of ONE connection
     (it is not stored in the database file), so every connection sets it.
  2. `checkpoint_if_larger(...)` / `checkpoint(...)`: `PRAGMA wal_checkpoint(TRUNCATE)`, which
     merges whatever is left and truncates the file to zero bytes. The engine calls
     `checkpoint_if_larger` at the end of a garbage-collection or purge pass; the
     `version-manage wal` command calls `checkpoint` by hand.

The limit is never above MAX_LIMIT_MB (64 MB), whatever a settings file says.

Rules for this file (CODING_GUIDELINES.md, helpers): standard library only, a leaf (no import of
config, version_engine, app, tools), no thread, no event loop, no asyncio, no thread pool. The
caller passes the connection and the database path in. A checkpoint can wait for readers and
writers, so it always runs with a SHORT busy timeout of its own (restored afterwards) and a
busy answer is a result, never an exception: the data is safe either way, a checkpoint only
moves it from the log into the main file.
"""

import math
import os
import sqlite3
import time
from dataclasses import dataclass

MB = 1024 * 1024
MAX_LIMIT_MB = 64  # the hard ceiling: neither the limit nor the threshold goes above it
MIN_LIMIT_MB = 1  # a non-zero setting below this is raised to it
DEFAULT_LIMIT_MB = 64

# `PRAGMA wal_checkpoint(<mode>)` cannot take a bound parameter, so the mode is checked against
# this list before it is put into the statement.
MODES = ("PASSIVE", "FULL", "RESTART", "TRUNCATE")


def limit_bytes(megabytes) -> int:
    """The size limit in bytes for a setting given in MB: 0 means switched off, anything that is
    not a real number gives the default, and the result is never above MAX_LIMIT_MB."""
    if isinstance(megabytes, bool) or not isinstance(megabytes, (int, float)):
        megabytes = DEFAULT_LIMIT_MB
    if math.isnan(megabytes):
        megabytes = DEFAULT_LIMIT_MB
    if megabytes <= 0:
        return 0
    return int(min(max(megabytes, MIN_LIMIT_MB), MAX_LIMIT_MB) * MB)


def human_bytes(n) -> str:
    """12345678 -> '11.8 MB' (the helper must not import config.format_bytes)."""
    size = float(max(0, n))
    if size < 1024:
        return f"{size:.0f} B"
    for unit in ("KB", "MB"):
        size /= 1024
        if size < 1024:
            return f"{size:.1f} {unit}"
    return f"{size / 1024:.1f} GB"


def _size(path) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def wal_path(db_path) -> str:
    return f"{db_path}-wal"


def wal_size(db_path) -> int:
    """Bytes of the -wal file next to `db_path` (0 when it does not exist)."""
    return _size(wal_path(db_path))


def file_sizes(db_path) -> dict:
    """Sizes in bytes of the database file, its -wal file and its -shm file (0 = missing)."""
    return {
        "db": _size(db_path),
        "wal": _size(wal_path(db_path)),
        "shm": _size(f"{db_path}-shm"),
    }


def apply_journal_size_limit(conn, limit) -> None:
    """Set `PRAGMA journal_size_limit` on this connection; a limit of 0 or less changes nothing."""
    limit = int(limit)
    if limit > 0:
        conn.execute(f"PRAGMA journal_size_limit={limit}")


@dataclass
class CheckpointResult:
    mode: str
    ran: bool = (
        False  # False: nothing was attempted (see `error` for the reason, if any)
    )
    busy: int = 0  # 1: a reader or writer kept the checkpoint from finishing
    log_frames: int = 0  # frames in the log when the checkpoint ended
    checkpointed_frames: int = 0  # frames written back to the main file
    wal_before: int = 0  # bytes of the -wal file before
    wal_after: int = 0  # bytes of the -wal file after
    seconds: float = 0.0
    error: str = ""

    @property
    def completed(self) -> bool:
        return self.ran and not self.error and self.busy == 0


def checkpoint(
    conn, db_path, mode="TRUNCATE", busy_timeout_ms=10000
) -> CheckpointResult:
    """Run `PRAGMA wal_checkpoint(mode)` on `conn` and report what happened. It waits at most
    `busy_timeout_ms` for readers and writers (the connection's own timeout, normally much
    longer, is put back afterwards). Never raises for a SQLite error: a busy database or a
    failure is `completed == False` with the reason in `error`."""
    mode = str(mode).upper()
    if mode not in MODES:
        raise ValueError(f"unknown checkpoint mode {mode!r}; use one of {MODES}")
    result = CheckpointResult(mode=mode, wal_before=wal_size(db_path))
    if conn.in_transaction:
        result.error = "the connection has an open transaction"
        result.wal_after = result.wal_before
        return result
    started = time.monotonic()
    old_timeout = None
    try:
        old_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        conn.execute(f"PRAGMA busy_timeout={max(0, int(busy_timeout_ms))}")
        row = conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        result.ran = True
        result.busy, result.log_frames, result.checkpointed_frames = (
            int(row[0]),
            int(row[1]),
            int(row[2]),
        )
    except sqlite3.Error as e:
        result.ran = True
        result.busy = 1
        result.error = str(e)
    finally:
        if old_timeout is not None:
            try:
                conn.execute(f"PRAGMA busy_timeout={int(old_timeout)}")
            except sqlite3.Error:
                # The connection is unusable anyway; the result above is what matters.
                pass
    result.seconds = time.monotonic() - started
    result.wal_after = wal_size(db_path)
    return result


def checkpoint_if_larger(
    conn, db_path, limit, mode="TRUNCATE", busy_timeout_ms=2000
) -> "CheckpointResult | None":
    """Checkpoint only when the -wal file is LARGER than `limit` bytes (limit 0 = switched off).
    Returns None when nothing was attempted."""
    if int(limit) <= 0 or wal_size(db_path) <= int(limit):
        return None
    return checkpoint(conn, db_path, mode, busy_timeout_ms)
