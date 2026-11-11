#!/usr/bin/env python3
"""
purge_missing_versions.py - reclaim Version Engine storage for files that no longer exist
==========================================================================================
The Version Engine keeps every version of a file after the file itself is deleted (so it can
be restored), and nothing ever ages those versions out: retention only runs when the same
file gets a NEW snapshot, which a deleted file never does. With many deleted files the chunk
store only grows. This tool finds tracked files whose path no longer exists on disk,
soft-deletes their versions, and optionally frees the chunks right away.

    python tools/purge_missing_versions.py                 # on a terminal: the interactive menu
    python tools/purge_missing_versions.py --menu           # the menu, with starting settings from the flags
    python tools/purge_missing_versions.py --report         # report only, never asks, never changes
    python tools/purge_missing_versions.py --apply         # soft-delete (on a terminal it asks first; --yes skips)
    python tools/purge_missing_versions.py --apply --free-now   # ...and free the chunks now
    python tools/purge_missing_versions.py --undo <file>.json   # re-activate an earlier --apply

Run via `./manage.sh purge-versions` (menu 31); extra arguments go straight to this script.

The menu (no arguments on a terminal, or --menu): 1 report, 2 soft-delete, 3 soft-delete and free
the disk space now, 4 undo an earlier purge (lists the undo files), 5 minimum age, 6 scope check
on/off, 7 --force on/off, 8 exit. A report is reused by 2 and 3 when the settings did not change
(its candidates are re-checked first, files that exist again drop out), so a 250,000-row scan is
not repeated. Any argument keeps the plain command line below, and with no terminal (a script, a
pipe) no arguments mean "report only", as before. With flags but without --apply on a terminal
the command line prints the report and then asks y/N.

Options:
    --min-age-days N   Only files whose NEWEST version is at least N days old (default 30).
                       A safety margin; use 0 to take everything. Files that are gone but
                       younger than that are COUNTED in the report, never silently dropped.
    --force            Also treat files on an unreachable drive, share or tracked folder as
                       deleted. Check first: that pattern usually means the location is not
                       mounted right now, NOT that you deleted everything.
    --show N           List the N files that would free the most space (default 10).
    --yes              Do not ask for confirmation (for scripts).

What the report tells you (so the numbers can be checked against the real folder):
    files known to the engine         every row of the engine's `files` table
    with completed versions           the ones this tool can act on
    still on disk / gone from disk    os.path.lexists() on the stored path
    in tracking scope on disk now     a fresh walk of the configured tracked folders: this is
                                      the number to compare with the real folder
    outside the tracking scope        on disk, but excluded or no longer tracked: NEVER purged
    cannot tell                       the drive, share or tracked folder is missing / empty /
                                      unreadable, so "gone" would be a guess: NEVER purged
                                      unless --force

Why there is no "more than half looks gone" brake (5.44.4): the old guard refused to apply
whenever over half of the tracked files were missing. A real clean-up can easily be 70 % (for
example 250,000 rows against 60,000 files on disk), so the guard blocked exactly the case this
tool exists for. The guard is now a direct check: every file is placed under the tracked
folder it belongs to, and a folder that is missing, empty or unreadable makes its files
"cannot tell" instead of "gone".

How it stays safe:
  * Report first; nothing changes without --apply (or an explicit "y" at the prompt).
  * Works on the same SQLite database as the engine (WAL + busy timeout); safe while the server
    runs. It only marks versions status='deleted' (exactly what "delete version" in the web UI
    and `version-manage delete` do); the engine's own garbage collector removes the chunks,
    re-checking under the write lock that nothing still references them.
  * Chunks shared with a file that still exists are never freed (counted per chunk).
  * --apply writes an undo file next to the object store; --undo brings the versions back as long
    as their chunks are still there (i.e. before the grace period ended / --free-now ran).
  * The decision uses the file system, not the engine's `deleted` flag (that flag is only set
    for files the running engine had seen, so it misses files deleted while it was stopped).
  * --free-now frees EVERY orphaned chunk past a zero grace period, including chunks of
    versions deleted by hand in the last 24 hours; the report of the run says how much.

Ctrl-C at any prompt cancels cleanly (exit code 130), never a traceback and never a half-done
batch: each batch is one transaction.
"""

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field

# tools/ sits one level below the project root: put the root on sys.path so the root modules
# (config, version_engine, ...) are importable from here. They are imported inside the
# functions that need them, so the decision logic below can be tested without an engine.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_MARK = "purged: file no longer exists (purge_missing_versions.py)"
_BATCH = 500
_PROGRESS_EVERY = 50_000


# ── small helpers ────────────────────────────────────────────────────────────


def _fmt_bytes(n) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"  # unreachable; keeps every path returning


def _fmt_time(ts) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "-"


def _prompt(msg: str):
    """input() that treats Ctrl-C / Ctrl-D / closed stdin as "cancel": returns the typed
    string, or None when the person backed out."""
    try:
        return input(msg)
    except (KeyboardInterrupt, EOFError):
        print()
        return None


def _confirm(msg: str) -> bool:
    answer = _prompt(f"  {msg} [y/N]: ")
    return answer is not None and answer.strip().lower() in ("y", "yes")


# ── where a file belongs: tracked folders and unreachable locations ───────────


def _under(path: str, root: str) -> bool:
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(os.path.abspath(root))
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


class _Probe:
    """Decides whether a path that is missing on disk can be called DELETED, or whether the
    place it lived in is itself unavailable (drive or share not mounted, tracked folder
    missing, empty or unreadable). Answers are cached per drive and per tracked folder, so
    250,000 paths cost a handful of probes, not 250,000. The file system calls are
    parameters so the logic can be tested without a real disk."""

    def __init__(
        self,
        scope_dirs,
        isdir=os.path.isdir,
        scandir=os.scandir,
        splitdrive=os.path.splitdrive,
    ):
        # Longest folder first: a file belongs to its most specific tracked folder.
        self._dirs = sorted(
            {os.path.abspath(os.path.expanduser(d)) for d in scope_dirs},
            key=len,
            reverse=True,
        )
        self._isdir = isdir
        self._scandir = scandir
        self._splitdrive = splitdrive
        self._drive_cache = {}
        self._dir_cache = {}

    def _drive_problem(self, path: str):
        drive, _rest = self._splitdrive(path)
        if not drive:
            return None  # POSIX: there is no drive letter to probe
        if drive not in self._drive_cache:
            self._drive_cache[drive] = self._isdir(drive + os.sep)
        return None if self._drive_cache[drive] else f"{drive} is not reachable"

    def _dir_problem(self, root: str):
        if root not in self._dir_cache:
            problem = None
            if not self._isdir(root):
                problem = f"tracked folder {root} is missing"
            else:
                try:
                    with self._scandir(root) as it:
                        if next(iter(it), None) is None:
                            problem = (
                                f"tracked folder {root} is empty (a share that is "
                                "not mounted looks like this)"
                            )
                except OSError as e:
                    problem = f"tracked folder {root} cannot be read ({e})"
            self._dir_cache[root] = problem
        return self._dir_cache[root]

    def reason(self, path: str):
        """None = the place is fine, so the missing file really is gone. Otherwise a text
        saying why we cannot tell."""
        problem = self._drive_problem(path)
        if problem:
            return problem
        for root in self._dirs:
            if _under(path, root):
                return self._dir_problem(root)
        return None  # not under any configured tracked folder: judged by the file alone


# ── the scan ─────────────────────────────────────────────────────────────────


@dataclass
class Scan:
    files_total: int = 0  # every row of the engine's `files` table
    with_completed: int = 0  # rows that have at least one completed version
    present: int = 0  # ...and are on disk
    present_in_scope: int = 0  # ...and the engine's walk still sees them
    gone: int = 0  # ...and are not on disk, place reachable (any age)
    too_recent: int = 0  # gone, but the newest version is younger than --min-age-days
    purge: list = field(default_factory=list)  # gone and old enough: dicts, see _scan
    unsure: list = field(default_factory=list)  # (path, reason): place unavailable
    gone_ext: dict = field(default_factory=dict)  # extension -> gone files (any age)
    gone_newest_min: float | None = None  # oldest "newest version" among the gone files
    gone_newest_max: float | None = (
        None  # youngest "newest version" among the gone files
    )
    scope_files: int | None = (
        None  # files the engine's walk finds now (None = not checked)
    )

    @property
    def purge_ids(self):
        return [i for g in self.purge for i in g["ids"]]

    @property
    def present_out_of_scope(self):
        return self.present - self.present_in_scope


def scan_tracked(
    db_path,
    min_age_days,
    scope_dirs,
    scope_keys=None,
    force=False,
    now=None,
    exists=os.path.lexists,
    probe=None,
    progress=None,
):
    """Classify every file the engine knows. `scope_keys` is the set of normalized keys the
    engine's own walk finds right now (None = skip that cross-check). `force` lets files
    whose place is unavailable count as gone."""
    cutoff = (time.time() if now is None else now) - min_age_days * 86400
    probe = probe or _Probe(scope_dirs)
    out = Scan(scope_files=None if scope_keys is None else len(scope_keys))
    db = sqlite3.connect(db_path, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        out.files_total = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        rows = db.execute(
            "SELECT f.file_id, f.path, f.norm_key, MAX(v.created_at) AS newest, "
            "COUNT(*) AS n FROM files f "
            "JOIN versions v ON v.file_id = f.file_id AND v.status='completed' "
            "GROUP BY f.file_id"
        ).fetchall()
        out.with_completed = len(rows)
        candidates = []
        for i, r in enumerate(rows, 1):
            if progress and i % _PROGRESS_EVERY == 0:
                progress(i, len(rows))
            if exists(r["path"]):
                out.present += 1
                if scope_keys is not None and r["norm_key"] in scope_keys:
                    out.present_in_scope += 1
                continue
            why = probe.reason(r["path"])
            if why and not force:
                out.unsure.append((r["path"], why))
                continue
            out.gone += 1
            ext = os.path.splitext(r["path"])[1].lower() or "(none)"
            out.gone_ext[ext] = out.gone_ext.get(ext, 0) + 1
            newest = r["newest"]
            if out.gone_newest_min is None or newest < out.gone_newest_min:
                out.gone_newest_min = newest
            if out.gone_newest_max is None or newest > out.gone_newest_max:
                out.gone_newest_max = newest
            if r["newest"] > cutoff:
                out.too_recent += 1
                continue
            candidates.append(r)
        # One pass over the versions instead of one query per file.
        wanted = {r["file_id"]: [] for r in candidates}
        for vid_row in db.execute(
            "SELECT file_id, version_id FROM versions WHERE status='completed'"
        ):
            ids = wanted.get(vid_row["file_id"])
            if ids is not None:
                ids.append(vid_row["version_id"])
        out.purge = [
            {
                "file_id": r["file_id"],
                "path": r["path"],
                "newest": r["newest"],
                "versions": r["n"],
                "ids": wanted[r["file_id"]],
            }
            for r in candidates
        ]
        return out
    finally:
        db.close()


def reclaimable(db_path, purge):
    """({file_id: bytes} that deleting each file's versions would really free, total).
    A chunk counts only if no completed version OUTSIDE the purge set uses it. A chunk shared
    by two purged files shows in both per-file figures but once in the total."""
    db = sqlite3.connect(db_path, timeout=30)
    try:
        db.execute("CREATE TEMP TABLE purge_v(version_id INTEGER PRIMARY KEY)")
        db.executemany(
            "INSERT INTO purge_v VALUES (?)", [(i,) for g in purge for i in g["ids"]]
        )
        # Both queries spell the "no completed version outside the purge set uses this chunk"
        # test out in full: constant SQL only, nothing is interpolated.
        per_file = {
            fid: size or 0
            for fid, size in db.execute(
                "SELECT pv.file_id, SUM(o.size) FROM objects o "
                "JOIN (SELECT DISTINCT vo.sha256, v.file_id FROM version_objects vo "
                "      JOIN versions v ON v.version_id = vo.version_id "
                "      WHERE vo.version_id IN (SELECT version_id FROM purge_v)) pv "
                "  ON pv.sha256 = o.sha256 "
                "WHERE NOT EXISTS (SELECT 1 FROM version_objects x "
                "                  JOIN versions xv ON xv.version_id = x.version_id "
                "                  WHERE x.sha256 = o.sha256 AND xv.status='completed' "
                "                  AND x.version_id NOT IN (SELECT version_id FROM purge_v)) "
                "GROUP BY pv.file_id"
            )
        }
        total = db.execute(
            "SELECT COALESCE(SUM(o.size), 0) FROM objects o "
            "WHERE o.sha256 IN (SELECT sha256 FROM version_objects "
            "                   WHERE version_id IN (SELECT version_id FROM purge_v)) "
            "AND NOT EXISTS (SELECT 1 FROM version_objects x "
            "                JOIN versions xv ON xv.version_id = x.version_id "
            "                WHERE x.sha256 = o.sha256 AND xv.status='completed' "
            "                AND x.version_id NOT IN (SELECT version_id FROM purge_v))"
        ).fetchone()[0]
        return per_file, total
    finally:
        db.close()


def soft_delete(conn, ids, batch=_BATCH, pause=0.01, progress=None) -> int:
    """status='completed' -> 'deleted' in short write transactions (the engine's own pattern);
    returns how many rows really changed. progress(done, total) is called each time another
    _PROGRESS_EVERY versions are done (never for small runs)."""
    changed = 0
    for start in range(0, len(ids), batch):
        chunk = ids[start : start + batch]
        conn.execute("BEGIN IMMEDIATE")
        try:
            for vid in chunk:
                changed += conn.execute(
                    "UPDATE versions SET status='deleted', error=? "
                    "WHERE version_id=? AND status='completed'",
                    (_MARK, vid),
                ).rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        time.sleep(pause)  # let the engine's own writers in between batches
        done = start + len(chunk)
        if progress and done // _PROGRESS_EVERY > start // _PROGRESS_EVERY:
            progress(done, len(ids))
    return changed


def undo_versions(conn, ids, engine_object_path, batch=_BATCH):
    """Re-activate versions that an earlier --apply deleted, but only while every chunk of the
    version is still stored. Returns (restored, skipped)."""
    restored = skipped = 0
    for start in range(0, len(ids), batch):
        chunk = ids[start : start + batch]
        conn.execute("BEGIN IMMEDIATE")
        try:
            for vid in chunk:
                row = conn.execute(
                    "SELECT status, error FROM versions WHERE version_id=?", (vid,)
                ).fetchone()
                if row is None or row[0] != "deleted" or row[1] != _MARK:
                    skipped += 1
                    continue
                shas = [
                    r[0]
                    for r in conn.execute(
                        "SELECT sha256 FROM version_objects WHERE version_id=?",
                        (vid,),
                    )
                ]
                intact = bool(shas) and all(
                    conn.execute(
                        "SELECT 1 FROM objects WHERE sha256=?", (s,)
                    ).fetchone()
                    is not None
                    and os.path.exists(engine_object_path(s))
                    for s in shas
                )
                if not intact:
                    skipped += 1  # the chunks were already freed; nothing to bring back
                    continue
                conn.execute(
                    "UPDATE versions SET status='completed', error=NULL "
                    "WHERE version_id=?",
                    (vid,),
                )
                conn.executemany(
                    "UPDATE objects SET orphaned_since=NULL WHERE sha256=?",
                    [(s,) for s in shas],
                )
                restored += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return restored, skipped


# ── the engine, and the report ───────────────────────────────────────────────


def _get_engine():
    import version_engine as ve

    engine = ve.Engine()
    engine._ensure_dirs()
    engine._bootstrap_schema()
    return engine


def _scope_dirs():
    """Every folder the engine is (or was) set to track, from config.py."""
    import config

    dirs = list(getattr(config, "VERSION_TRACK_DIRECTORIES", []) or [])
    dirs += list(getattr(config, "VERSION_TRACK_ROOTS", []) or [])
    return dirs


def _print_report(scan: Scan, per_file, total, args):
    def line(label, value, indent=0):
        print(f"  {' ' * indent}{label:<{52 - indent}} {value:>10,}")

    print("\nVersion Engine database")
    line("files known to the engine", scan.files_total)
    line("with completed versions (this tool acts on these)", scan.with_completed, 2)
    line("still on disk", scan.present, 4)
    line("gone from disk", scan.gone, 4)
    line(
        f"kept: newest version younger than {args.min_age_days:g} day(s)",
        scan.too_recent,
        6,
    )
    line("to purge", len(scan.purge), 6)
    line("cannot tell (location unavailable, left alone)", len(scan.unsure), 4)
    if scan.scope_files is not None:
        print("\nCross-check with the real folder")
        line("in the tracking scope on disk right now", scan.scope_files)
        line("...of which the database holds with versions", scan.present_in_scope, 2)
        line(
            "...of which the engine has not versioned yet",
            max(scan.scope_files - scan.present_in_scope, 0),
            2,
        )
        line(
            "on disk but outside the tracking scope (never purged)",
            scan.present_out_of_scope,
        )
    if scan.unsure:
        reasons = {}
        for _path, why in scan.unsure:
            reasons[why] = reasons.get(why, 0) + 1
        print("\n  Not touched, because the place they live in is unavailable:")
        for why, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:5]:
            print(f"    {n:>9,} file(s): {why}")
        print(
            "  Mount / restore that place and run again, or use --force if it is gone for good."
        )
    if scan.files_total and scan.gone / scan.files_total > 0.5 and not scan.unsure:
        print(
            f"\n  {scan.gone / scan.files_total:.0%} of the files are gone from disk. "
            "Every tracked folder is reachable and not empty, so this is real deletion."
        )
    if scan.gone:
        top = sorted(scan.gone_ext.items(), key=lambda kv: -kv[1])[:8]
        print("\nThe gone files")
        print("  by extension: " + "   ".join(f"{e} {n:,}" for e, n in top))
        print(
            f"  newest version of each: between {_fmt_time(scan.gone_newest_min)} "
            f"and {_fmt_time(scan.gone_newest_max)}"
        )
    if scan.too_recent:
        print(
            f"\n  {scan.too_recent:,} gone file(s) are NOT in the purge list only because "
            f"their newest version is younger than {args.min_age_days:g} day(s).\n"
            "  Use --min-age-days N (0 = take them all) to include them."
        )
    if not scan.purge:
        print("\nNothing to purge.")
        return
    print(
        f"\nWould soft-delete {len(scan.purge_ids):,} version(s) of {len(scan.purge):,} file(s)"
        f" and free {_fmt_bytes(total)} of chunk storage"
    )
    top = sorted(scan.purge, key=lambda g: per_file.get(g["file_id"], 0), reverse=True)
    for g in top[: args.show]:
        print(
            f"  {_fmt_bytes(per_file.get(g['file_id'], 0)):>10}  {g['versions']:>4} version(s)"
            f"  last {_fmt_time(g['newest'])}  {g['path']}"
        )
    if len(top) > args.show:
        print(f"  ... and {len(top) - args.show:,} more")


def _grace_hours() -> int:
    import config

    return config.VERSION_GC_GRACE_PERIOD // 3600


def _orphan_count(engine) -> int:
    """Chunks marked as orphaned and not deleted yet (read-only, safe while the GC runs)."""
    row = (
        engine._connect()
        .execute("SELECT COUNT(*) FROM objects WHERE orphaned_since IS NOT NULL")
        .fetchone()
    )
    return row[0]


def _object_totals(engine):
    row = (
        engine._connect()
        .execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM objects")
        .fetchone()
    )
    return row[0], row[1]


def _free_now(engine):
    import config

    if not config.VERSION_GC_ENABLED:
        print(
            "Garbage collection is switched off (VERSION_GC_ENABLED), so no chunk was freed."
        )
        return
    before = _object_totals(engine)
    saved = config.VERSION_GC_GRACE_PERIOD
    config.VERSION_GC_GRACE_PERIOD = (
        0  # this process only; the engine keeps its own value
    )
    try:
        print(
            "  step 1 of 2: marking the orphaned chunks (and deleting any already due)..."
        )
        _with_progress(
            "marking",
            engine.run_gc,
            lambda: f"{_orphan_count(engine):,} chunk(s) marked so far",
        )
        pending = _orphan_count(engine)
        print(f"  step 2 of 2: deleting {pending:,} chunk file(s) from disk...")
        _with_progress(
            "deleting",
            engine.run_gc,  # deletes them (age >= 0), re-checking references under the write lock
            lambda: f"{max(pending - _orphan_count(engine), 0):,} of {pending:,} deleted",
        )
    finally:
        config.VERSION_GC_GRACE_PERIOD = saved
    after = _object_totals(engine)
    print(
        f"Freed {before[0] - after[0]:,} chunk(s), {_fmt_bytes(before[1] - after[1])} "
        "(every orphaned chunk past a zero grace period, not only this run's)."
    )


def _with_progress(label, work, measure=None, interval=5.0):
    """Run work() in a worker thread and print a heartbeat line every `interval` seconds until
    it ends, so a long step does not look stuck: `label`, what measure() says (if given) and the
    time spent. Returns work()'s result; an Exception in the worker is raised here. Ctrl-C stops the
    waiting, not the worker (an engine garbage-collection pass cannot be interrupted); the
    engine finishes whatever is left on its own later."""
    box = {}

    def target():
        try:
            box["result"] = work()
        except Exception as e:  # handed to the caller below, not swallowed
            box["error"] = e

    worker = threading.Thread(target=target, daemon=True)
    started = last = time.time()
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.5)  # short joins: Ctrl-C is delivered promptly on Windows too
            if worker.is_alive() and time.time() - last >= interval:
                last = time.time()
                detail = f": {measure()}" if measure else ""
                print(f"  {label}{detail} ({int(last - started)} s)")
    except KeyboardInterrupt:
        print(
            f"\n  Stopped waiting for: {label}. It may still be running in this process; "
            "the engine's own garbage collector finishes any chunk it did not reach."
        )
        raise
    if "error" in box:
        raise box["error"]
    # No result and no error: the worker ended without returning (for example SystemExit).
    if "result" not in box:
        raise RuntimeError(f"{label}: the step ended without a result")
    return box["result"]


@dataclass
class Collected:
    """One scan with everything the report needs, and the settings it was made with."""

    scan: Scan
    per_file: dict
    total: int
    key: tuple
    when: float


def _settings_key(s):
    return (s.min_age_days, s.force, s.no_scope_check)


def _collect(engine, scope_dirs, s) -> Collected:
    """Read the engine's tracked files, check them on disk, and work out what a purge would
    free. `s` needs min_age_days, force and no_scope_check (the parsed arguments, or the menu's
    own settings)."""
    print("Reading the engine's tracked files and checking them on disk...")
    scope_keys = None
    if not s.no_scope_check:
        try:
            scope_keys = set(engine.get_eligible_files())
        except OSError as e:
            print(f"(scope cross-check skipped: {e})")
    scan = scan_tracked(
        engine.db_path,
        s.min_age_days,
        scope_dirs,
        scope_keys=scope_keys,
        force=s.force,
        progress=lambda done, total: print(f"  checked {done:,} of {total:,}"),
    )
    per_file, total = {}, 0
    if scan.purge:
        print(
            f"Working out how much space {len(scan.purge):,} file(s) would free "
            "(this can take a few minutes)..."
        )
        per_file, total = _with_progress(
            "still working out the space",
            lambda: reclaimable(engine.db_path, scan.purge),
        )
    return Collected(scan, per_file, total, _settings_key(s), time.time())


def _drop_reappeared(scan, exists=os.path.lexists) -> int:
    """Take files out of the purge list that exist again (a report can be minutes old).
    Returns how many were dropped."""
    keep = [g for g in scan.purge if not exists(g["path"])]
    dropped = len(scan.purge) - len(keep)
    scan.purge = keep
    return dropped


def _apply(engine, scan, free_now) -> None:
    """Write the undo file, soft-delete, and (optionally) free the chunks now."""
    ids = scan.purge_ids
    undo = os.path.join(
        engine.storage_dir, f"purge_undo_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(undo, "w", encoding="utf-8") as f:
        json.dump({"created": time.time(), "version_ids": ids}, f)
    print(f"\nUndo file written: {undo}")
    done = soft_delete(
        engine._connect(),
        ids,
        progress=lambda d, t: print(f"  soft-deleted {d:,} of {t:,}"),
    )
    print(f"Soft-deleted {done:,} version(s).")

    if free_now:
        print("Freeing chunks now (grace period skipped for this run)...")
        _free_now(engine)
    else:
        print(
            "Chunks are removed by the engine's garbage collector after "
            f"{_grace_hours()} h (VERSION_GC_GRACE_PERIOD); "
            "until then --undo can still bring them back."
        )


def _run_undo(engine, path) -> int:
    with open(path, encoding="utf-8") as f:
        ids = json.load(f)["version_ids"]
    restored, skipped = undo_versions(engine._connect(), ids, engine._object_path)
    print(
        f"Restored {restored:,} version(s); skipped {skipped:,} "
        "(chunks already freed or changed)."
    )
    return 0


def _read_undo_file(path):
    """(created, number of versions) of an undo file, or None when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return float(data.get("created", 0)), len(data["version_ids"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def list_undo_files(directory):
    """[(path, created, versions)] of the undo files in `directory`, newest first."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    found = []
    for name in names:
        if name.startswith("purge_undo_") and name.endswith(".json"):
            path = os.path.join(directory, name)
            info = _read_undo_file(path)
            if info is not None:
                found.append((path, info[0], info[1]))
    found.sort(key=lambda item: item[1], reverse=True)
    return found


# -- the command line ------------------------------------------------------------


def cmd_report_or_apply(args) -> int:
    engine = _get_engine()
    c = _collect(engine, _scope_dirs(), args)
    _print_report(c.scan, c.per_file, c.total, args)
    if not c.scan.purge:
        return 0

    interactive = sys.stdin.isatty() and not args.yes
    if not args.apply:
        if args.report or not interactive:
            print("\nReport only: nothing was changed. Add --apply to soft-delete.")
            return 0
        print()
        if not _confirm("Soft-delete these versions now? (an undo file is written)"):
            print("Nothing was changed.")
            return 0
        args.free_now = args.free_now or _confirm(
            "Also free the disk space now (skips the 24 h grace period)?"
        )
    elif interactive and not _confirm("Soft-delete these versions now?"):
        print("Nothing was changed.")
        return 0
    _apply(engine, c.scan, args.free_now)
    return 0


def cmd_undo(args) -> int:
    return _run_undo(_get_engine(), args.undo)


# -- the interactive menu (no arguments on a terminal, or --menu) -----------------


def _menu_report(engine, scope_dirs, s):
    c = _collect(engine, scope_dirs, s)
    _print_report(c.scan, c.per_file, c.total, s)
    return c


def _menu_apply(engine, scope_dirs, s, cache, free_now):
    """Soft-delete (and optionally free) after a report. A report made with the same settings
    a moment ago is reused instead of scanning again; its candidates are re-checked first.
    Returns the cache to keep (None once something changed)."""
    if cache is not None and cache.key == _settings_key(s):
        age = int(time.time() - cache.when)
        print(
            f"Using the report from {age // 60} min {age % 60} s ago; checking that its "
            f"{len(cache.scan.purge):,} candidate file(s) are still gone..."
        )
        back = _drop_reappeared(cache.scan)
        if back:
            print(f"  {back:,} file(s) exist again and were taken out of the list.")
        c = cache
    else:
        c = _menu_report(engine, scope_dirs, s)
    if not c.scan.purge:
        print("\nNothing to purge.")
        return c
    print(
        f"\nAbout to soft-delete {len(c.scan.purge_ids):,} version(s) "
        f"of {len(c.scan.purge):,} file(s)."
    )
    if free_now:
        print(
            "  The disk space is freed NOW: every orphaned chunk past a zero grace "
            "period goes,\n  including chunks of versions you deleted by hand in the "
            "last 24 hours."
        )
    if not _confirm("Continue? (an undo file is written first)"):
        print("Nothing was changed.")
        return c
    _apply(engine, c.scan, free_now)
    return None


def _menu_undo(engine):
    files = list_undo_files(engine.storage_dir)
    if not files:
        print("No undo files (purge_undo_*.json) in the engine's storage folder.")
        return
    print("\nEarlier purges (newest first):")
    for n, (path, created, versions) in enumerate(files[:10], 1):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(created))
        print(f"  {n}) {when}  {versions:>9,} version(s)  {os.path.basename(path)}")
    raw = _prompt("Which one to undo (number, Enter = cancel): ")
    if raw is None or not raw.strip():
        return
    if not raw.strip().isdigit() or not 1 <= int(raw.strip()) <= min(len(files), 10):
        print("Not a number from the list.")
        return
    path = files[int(raw.strip()) - 1][0]
    if _confirm(f"Bring back the versions in {os.path.basename(path)}?"):
        _run_undo(engine, path)
    else:
        print("Nothing was changed.")


def _menu_set_age(s):
    raw = _prompt(
        f"Minimum age in days (now {s.min_age_days:g}; 0 = take every gone file): "
    )
    if raw is None or not raw.strip():
        return
    try:
        days = float(raw.strip())
    except ValueError:
        days = -1.0
    if days < 0:
        print("Not a number of days (0 or more).")
        return
    s.min_age_days = days
    print(f"Minimum age is now {days:g} day(s).")


def _menu_toggle_force(s):
    if s.force:
        s.force = False
        print("--force is off again.")
        return
    print(
        "--force also purges files whose drive, share or tracked folder is missing, empty or\n"
        "unreadable. That usually means the place is NOT MOUNTED right now, not that the\n"
        "files were deleted. Only use it when that place is gone for good."
    )
    if _confirm("Turn --force on?"):
        s.force = True


def _on_off(flag) -> str:
    return "on" if flag else "off"


def interactive_menu(args, engine=None, scope_dirs=None) -> int:
    """No arguments on a terminal: report, apply, apply and free now, undo, settings. Settings
    start from the arguments given (--min-age-days, --force, --no-scope-check, --show).
    """
    engine = engine or _get_engine()
    scope_dirs = _scope_dirs() if scope_dirs is None else scope_dirs
    s = argparse.Namespace(
        min_age_days=args.min_age_days,
        force=args.force,
        no_scope_check=args.no_scope_check,
        show=args.show,
    )
    cache = None
    print("\n🧹 Version Engine — purge versions of files that no longer exist")
    print(
        "   (Ctrl-C at this menu exits; Ctrl-C inside an action cancels that action.)"
    )
    while True:
        print("\n" + "=" * 60)
        print(
            f"  Settings: minimum age {s.min_age_days:g} day(s) | "
            f"force {_on_off(s.force)} | scope check {_on_off(not s.no_scope_check)}"
        )
        print("-" * 60)
        print("  1) Report: what do the gone files still cost?  (read-only)")
        print("  2) Soft-delete the versions of the gone files  (asks first)")
        print("  3) Soft-delete AND free the disk space now     (asks first)")
        print("  4) Undo an earlier purge")
        print("  5) Change the minimum age (days)")
        print("  6) Turn the scope check (walk of the tracked folders) on / off")
        print("  7) Turn --force on / off")
        print("  8) Exit")
        print("=" * 60)

        choice = _prompt("\nSelect option (1-8): ")
        if choice is None:
            print("👋 Goodbye!")
            return 0
        choice = choice.strip()
        try:
            if choice == "1":
                cache = _menu_report(engine, scope_dirs, s)
            elif choice in ("2", "3"):
                cache = _menu_apply(engine, scope_dirs, s, cache, choice == "3")
            elif choice == "4":
                _menu_undo(engine)
                cache = None  # the database changed
            elif choice == "5":
                _menu_set_age(s)
            elif choice == "6":
                s.no_scope_check = not s.no_scope_check
                print(f"Scope check is now {_on_off(not s.no_scope_check)}.")
            elif choice == "7":
                _menu_toggle_force(s)
            elif choice == "8":
                print("👋 Goodbye!")
                return 0
            else:
                print(f"❌ Invalid option: {choice}")
        except KeyboardInterrupt:
            print("\nCancelled. Back to the menu.")
        _prompt("\nPress Enter to return to the menu…")


def _build_parser():
    p = argparse.ArgumentParser(
        description="Reclaim Version Engine storage for files that no longer exist. "
        "With no arguments on a terminal it opens an interactive menu."
    )
    p.add_argument(
        "--menu",
        action="store_true",
        help="open the interactive menu (the default with no arguments on a terminal); "
        "--min-age-days, --force, --no-scope-check and --show set its starting settings",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="soft-delete the versions (asks first unless --yes)",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="report only: never ask, never change anything",
    )
    p.add_argument(
        "--free-now",
        action="store_true",
        help="free the chunks now instead of after the grace period",
    )
    p.add_argument("--min-age-days", type=float, default=30.0, metavar="N")
    p.add_argument(
        "--force",
        action="store_true",
        help="also purge files whose drive, share or tracked folder is unavailable",
    )
    p.add_argument("--show", type=int, default=10, metavar="N")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument(
        "--no-scope-check",
        action="store_true",
        help="skip the walk of the tracked folders (faster; no cross-check numbers)",
    )
    p.add_argument(
        "--undo", metavar="FILE", help="re-activate versions listed in an undo file"
    )
    return p


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    args = _build_parser().parse_args(argv)
    if args.report and args.apply:
        print("--report and --apply cannot be combined.", file=sys.stderr)
        return 2
    if args.menu and (args.apply or args.report or args.undo):
        print(
            "--menu cannot be combined with --apply, --report or --undo.",
            file=sys.stderr,
        )
        return 2
    if args.menu and not sys.stdin.isatty():
        print(
            "--menu needs a terminal; use --report or --apply instead.", file=sys.stderr
        )
        return 2
    try:
        if args.menu or (not argv and sys.stdin.isatty()):
            return interactive_menu(args)
        if args.undo:
            return cmd_undo(args)
        return cmd_report_or_apply(args)
    except KeyboardInterrupt:
        print("\n👋 Cancelled.", file=sys.stderr)
        return 130  # 128 + SIGINT, the shell's own convention


if __name__ == "__main__":
    sys.exit(main())
