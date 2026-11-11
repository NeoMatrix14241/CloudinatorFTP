#!/usr/bin/env python3
"""
purge_missing_versions.py - reclaim Version Engine storage for files that no longer exist
==========================================================================================
The Version Engine keeps every version of a file after the file itself is deleted (so it can
be restored), and nothing ever ages those versions out: retention only runs when the same
file gets a NEW snapshot, which a deleted file never does. With many deleted files the chunk
store only grows. This tool finds tracked files whose path no longer exists on disk,
soft-deletes their versions, and optionally frees the chunks right away.

    python tools/purge_missing_versions.py                 # report; on a terminal it then asks
    python tools/purge_missing_versions.py --report         # report only, never asks, never changes
    python tools/purge_missing_versions.py --apply         # soft-delete (on a terminal it asks first; --yes skips)
    python tools/purge_missing_versions.py --apply --free-now   # ...and free the chunks now
    python tools/purge_missing_versions.py --undo <file>.json   # re-activate an earlier --apply

Run via `./manage.sh purge-versions` (menu 31); extra arguments go straight to this script.

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


def soft_delete(conn, ids, batch=_BATCH, pause=0.01) -> int:
    """status='completed' -> 'deleted' in short write transactions (the engine's own pattern);
    returns how many rows really changed."""
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
        engine.run_gc()  # marks the new orphans
        engine.run_gc()  # deletes them (age >= 0), re-checking references under the write lock
    finally:
        config.VERSION_GC_GRACE_PERIOD = saved
    after = _object_totals(engine)
    print(
        f"Freed {before[0] - after[0]:,} chunk(s), {_fmt_bytes(before[1] - after[1])} "
        "(every orphaned chunk past a zero grace period, not only this run's)."
    )


def cmd_report_or_apply(args) -> int:
    engine = _get_engine()
    scope_dirs = _scope_dirs()
    print("Reading the engine's tracked files and checking them on disk...")
    scope_keys = None
    if not args.no_scope_check:
        try:
            scope_keys = set(engine.get_eligible_files())
        except OSError as e:
            print(f"(scope cross-check skipped: {e})")
    scan = scan_tracked(
        engine.db_path,
        args.min_age_days,
        scope_dirs,
        scope_keys=scope_keys,
        force=args.force,
        progress=lambda done, total: print(f"  checked {done:,} of {total:,}"),
    )
    per_file, total = reclaimable(engine.db_path, scan.purge) if scan.purge else ({}, 0)
    _print_report(scan, per_file, total, args)
    if not scan.purge:
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

    ids = scan.purge_ids
    undo = os.path.join(
        engine.storage_dir, f"purge_undo_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(undo, "w", encoding="utf-8") as f:
        json.dump({"created": time.time(), "version_ids": ids}, f)
    print(f"\nUndo file written: {undo}")
    done = soft_delete(engine._connect(), ids)
    print(f"Soft-deleted {done:,} version(s).")

    if args.free_now:
        print("Freeing chunks now (grace period skipped for this run)...")
        _free_now(engine)
    else:
        import config

        print(
            "Chunks are removed by the engine's garbage collector after "
            f"{config.VERSION_GC_GRACE_PERIOD // 3600} h (VERSION_GC_GRACE_PERIOD); "
            "until then --undo can still bring them back."
        )
    return 0


def cmd_undo(args) -> int:
    engine = _get_engine()
    with open(args.undo, encoding="utf-8") as f:
        ids = json.load(f)["version_ids"]
    restored, skipped = undo_versions(engine._connect(), ids, engine._object_path)
    print(
        f"Restored {restored:,} version(s); skipped {skipped:,} "
        "(chunks already freed or changed)."
    )
    return 0


def _build_parser():
    p = argparse.ArgumentParser(
        description="Reclaim Version Engine storage for files that no longer exist."
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
    args = _build_parser().parse_args(argv)
    if args.report and args.apply:
        print("--report and --apply cannot be combined.", file=sys.stderr)
        return 2
    try:
        if args.undo:
            return cmd_undo(args)
        return cmd_report_or_apply(args)
    except KeyboardInterrupt:
        print("\n👋 Cancelled.", file=sys.stderr)
        return 130  # 128 + SIGINT, the shell's own convention


if __name__ == "__main__":
    sys.exit(main())
