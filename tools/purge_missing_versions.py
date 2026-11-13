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

Run via `./manage.sh purge-versions` (menu 10); extra arguments go straight to this script.

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
import sys
import threading
import time
from dataclasses import dataclass

# tools/ sits one level below the project root: put the root on sys.path so the root modules
# (config, version_engine, ...) are importable from here. They are imported inside the
# functions that need them, so the decision logic below can be tested without an engine.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# The decision logic (_Probe, scan_tracked, reclaimable, soft_delete, undo_versions, the undo
# file reader) lives in helpers/version_purge.py since 5.45, so the Version Engine's background
# purge uses the very same code. The old names stay importable from here.
from helpers.version_purge import (  # noqa: E402  (after the sys.path line above)
    BATCH as _BATCH,
    MARK as _MARK,
    PROGRESS_EVERY as _PROGRESS_EVERY,
    Probe as _Probe,
    Scan,
    list_undo_files,
    read_undo_file as _read_undo_file,
    reclaimable,
    scan_tracked,
    scope_dirs_from,
    soft_delete,
    undo_versions,
    under as _under,
)

# Names that the unit tests (and anything else written before 5.45) take from this module.
__all__ = [
    "Scan",
    "_BATCH",
    "_MARK",
    "_PROGRESS_EVERY",
    "_Probe",
    "_read_undo_file",
    "_under",
    "list_undo_files",
    "reclaimable",
    "scan_tracked",
    "soft_delete",
    "undo_versions",
]


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

    return scope_dirs_from(config)


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
