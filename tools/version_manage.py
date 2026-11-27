#!/usr/bin/env python3
"""
version_manage.py — Admin CLI + interactive menu for the Version Engine
=========================================================================
list / restore / delete / wal against version_engine.sqlite3, deliberately kept
SEPARATE from version_engine.py (which stays parent-API + --worker only —
no interactive/admin surface belongs in the same file as the process
lifecycle code).

This script does NOT start the Version Engine (no watcher, no scanner, no
worker threads, no subprocess) — it talks to the same SQLite DB and object
store directly, using the same Engine class's storage/restore methods,
via its own short-lived connection. Safe to run whether or not the real
version_engine.py --worker process is currently running: SQLite WAL mode
plus the busy_timeout already set in Engine._connect() handles the
concurrent access.

Two ways to run it — same underlying logic either way (do_list/do_restore/
do_delete/do_wal), never duplicated:

    python tools/version_manage.py                          # interactive menu
    python tools/version_manage.py list                      # every tracked file + version count
    python tools/version_manage.py list <file_path>           # every version of one file
    python tools/version_manage.py restore <version_id> <destination> [--overwrite]
    python tools/version_manage.py delete <version_id> [--run-gc-now]
    python tools/version_manage.py wal                       # sizes of the database, -wal and -shm files
    python tools/version_manage.py wal --checkpoint          # PRAGMA wal_checkpoint(TRUNCATE): shrink the -wal file
    python tools/version_manage.py wal --checkpoint [--mode passive|full|restart|truncate]
                                       [--timeout SECONDS] [--if-larger-mb 0..64]
    python tools/version_manage.py compress --probe          # READ-ONLY: measure what zstd would save on the real store
    python tools/version_manage.py compress --probe [--samples N] [--levels 1,3,9,15,19,22] [--seed N]
                                       [--seconds S] [--max-bytes MB] [--busy-percent 5..100]
                                       [--min-saving 0..50] [--no-dictionary] [--no-delta]
                                       [--delta-pairs N] [--db PATH] [--objects DIR]
    python tools/version_manage.py compress --status         # READ-ONLY: how much is compressed, the backlog, the thread
    python tools/version_manage.py compress --sweep [--grace SECONDS] [--busy-percent 5..100]
    python tools/version_manage.py compress --verify [--busy-percent 5..100]
    python tools/version_manage.py compress --decompress [--yes] [--force] [--busy-percent 5..100]

`wal` (5.45.1): the write-ahead log `version_engine.sqlite3-wal` never shrinks by itself, it keeps
the size of the biggest burst of writes it ever saw (2.9 GB after a purge and a GC). A checkpoint
merges what is left into the database and truncates the file; nothing can be lost by it, so it
asks for no confirmation. It is safe while the engine runs: if a reader or writer keeps it busy
past --timeout it reports that (exit code 1) and you try again, or stop the server first.
The engine does the same by itself when the file is above VERSION_WAL_SIZE_LIMIT_MB (at most 64).
No asyncio, no thread: one short synchronous connection, like the other commands.

`compress --probe` (5.46, Phase 0 of VERSION_COMPRESSION_PLAN.md): a READ-ONLY measurement. It opens the
database with mode=ro, reads a random sample of raw objects (SHA-256 verified), compresses them in memory
at several zstd levels and prints the size, the speeds, an estimate for the whole store, a trained-dictionary
test and the previous-version delta test. It writes nothing into the object store, sleeps between samples
(--busy-percent, default 50) and is safe while the server runs. The output is what the owner pastes back
before the level / dictionary / delta decisions are made. No asyncio, no thread: one synchronous loop.

`compress --status|--sweep|--verify|--decompress` (5.47, release B of VERSION_COMPRESSION_PLAN.md): the
hand tools of the object compressor that the Version Engine's `ve-compress` thread runs when
VERSION_COMPRESSION_ENABLED is true. `--status` only reads. `--sweep` removes the raw copy of every
compressed object, but only after the `.zst` was decoded and hashed once more (the thread does the
same, 5 minutes after compressing). `--verify` re-reads every compressed object and compares size and
SHA-256 (changes nothing). `--decompress` turns every compressed object back into a plain raw file
(verified while it is written; the way back to the 5.45.1 layout): it refuses while compression is
switched on (switch it off in server_config.json and restart the engine first), checks the free space,
and asks for a typed confirmation unless --yes. Every step is safe to interrupt (Ctrl-C) and to run
again. No asyncio, no thread: one synchronous loop with an optional duty cycle (--busy-percent).

The interactive menu (option 7, 5.47.7) has a compression sub-menu with the same hand tools:
status and probe (both read-only), sweep (asks y/N first), verify, and decompress (asks for the
same typed phrase as the command line). It calls the very same do_compress_* functions with the
command line's defaults; the options (--samples, --grace, --yes, --force ...) stay command-line
only. The settings are shown there read-only: change them in `./manage.sh config` (Version
Engine > Engine settings > 13).

Ctrl-C behavior (both modes): cancels whatever prompt/action is in progress
and returns to the menu (interactive mode) or exits cleanly with code 130
(CLI mode / top-level menu prompt) — never a raw traceback, never a
half-finished restore or delete. Run via `./manage.sh version-manage`,
this also means manage.sh itself is unaffected by Ctrl-C here: manage.sh's
run_utility() installs a *handled* SIGINT trap around the child process
(see manage.sh's own comment above run_utility()), so the Python process
receives a normal, default-disposition SIGINT and can exit on its own
terms, while manage.sh survives to show its "Press Enter to return to
menu…" prompt afterward.

Nothing here mutates config.py's VERSION_* settings — for that, use
config.py's "Version History / Version Engine" menu (configure_*
functions), not this script.
"""

import argparse
import os
import sys
import time

# tools/ sits one level below the project root: put the root on sys.path so the
# root modules (database, config, paths, ...) are still importable from here.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import config
import version_engine as ve
from helpers import version_compress, version_probe, version_wal, version_zstd


def _get_engine() -> ve.Engine:
    """A ready-to-query Engine instance with schema bootstrapped, but
    with NO threads/process started — list/restore/delete are all
    synchronous, one-shot operations invoked from the command line."""
    engine = ve.Engine()
    engine._ensure_dirs()
    engine._bootstrap_schema()
    return engine


def _fmt_time(ts):
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _prompt(msg: str):
    """input() that treats Ctrl-C / Ctrl-D / closed stdin as "cancel this
    action", not "crash with a traceback". Returns the typed string
    (possibly empty), or None if the person backed out. Every prompt in
    this file — CLI confirmation prompts included — goes through this,
    so Ctrl-C is safe to press at any point, in either mode."""
    try:
        return input(msg)
    except (KeyboardInterrupt, EOFError):
        print()
        return None


# =============================================================================
# Core logic — shared by CLI subcommands (argparse) and the interactive menu.
# Each returns an int exit/result code; none of them read from argparse.
# =============================================================================


def do_list(file_path=None) -> int:
    engine = _get_engine()
    conn = engine._connect()

    if file_path:
        target = os.path.abspath(os.path.expanduser(file_path))
        norm_key = ve._normalize_path(target)
        file_row = conn.execute(
            "SELECT file_id, path, deleted FROM files WHERE norm_key=?", (norm_key,)
        ).fetchone()
        if file_row is None:
            print(f"❌ No tracking history for: {target}")
            print(
                "   (Version Engine only has history for files it has actually snapshotted —"
            )
            print(
                "    check the path is tracked, and that at least one snapshot has run.)"
            )
            return 1

        rows = engine.list_versions(target)

        presence = (
            "🗑️  source deleted from disk"
            if file_row["deleted"]
            else "✅ source present"
        )
        print(f"\n📄 {file_row['path']}  ({presence})")
        print("=" * 78)
        if not rows:
            print("   (no versions yet)")
            return 0
        for r in rows:
            marker = {
                "completed": "✅",
                "failed": "❌",
                "deleted": "🗑️ ",
                "pending": "⏳",
                "processing": "⚙️ ",
                "verifying": "🔍",
            }.get(r["status"], "  ")
            print(
                f"  {marker} version_id={r['version_id']:<6} "
                f"{_fmt_time(r['created_at'])}   "
                f"{config.format_bytes(r['size']):>10}   "
                f"{r['storage_mode']:<8}   "
                f"sha256={r['sha256'][:12] if r['sha256'] else '—'}…   "
                f"status={r['status']}"
            )
            if r["error"]:
                print(f"         ↳ {r['error']}")
        return 0

    # No file given — summary across all tracked files.
    rows = engine.list_tracked_files()

    print(f"\n📚 Version Engine — {len(rows)} tracked file(s)")
    print("=" * 78)
    if not rows:
        print("   (nothing tracked yet — see config.py's Version Tracking Scope menu)")
        return 0
    for r in rows:
        presence = "🗑️  deleted from disk" if r["deleted"] else ""
        print(
            f"  {r['path']}\n"
            f"      {r['n_completed']} version(s)   last activity: {_fmt_time(r['last_activity'])}   {presence}"
        )
    return 0


def do_restore(version_id: int, destination: str, overwrite: bool = False) -> int:
    engine = _get_engine()
    conn = engine._connect()

    version = conn.execute(
        "SELECT v.*, f.path AS file_path FROM versions v "
        "JOIN files f ON f.file_id = v.file_id WHERE v.version_id=?",
        (version_id,),
    ).fetchone()
    if version is None:
        print(f"❌ No such version_id: {version_id}")
        return 1
    if version["status"] != "completed":
        print(
            f"❌ version_id {version_id} is not restorable (status={version['status']})."
        )
        if version["error"]:
            print(f"   {version['error']}")
        return 1

    destination = os.path.abspath(os.path.expanduser(destination))

    print(f"\n📄 Source file:      {version['file_path']}")
    print(
        f"🕓 Version:          {version_id}  (snapshotted {_fmt_time(version['created_at'])})"
    )
    print(f"📦 Size:             {config.format_bytes(version['size'])}")
    print(f"🔑 SHA-256:          {version['sha256']}")
    print(f"📁 Restoring to:     {destination}")

    if os.path.exists(destination) and not overwrite:
        print(
            f"\n⚠️  {destination} already exists. Re-run with --overwrite (CLI) or answer "
            "'yes' to the overwrite prompt (menu) to replace it — only after the restored "
            "content's hash has been verified: the original file is never touched until the "
            "copy is confirmed byte-for-byte correct."
        )
        return 1

    if os.path.exists(destination) and overwrite:
        confirm_phrase = (
            f"overwrite {os.path.basename(destination)} with version {version_id}"
        )
        print(f"\n⚠️  This will REPLACE the existing file at:\n   {destination}")
        print(f"   Type the following EXACTLY to continue:\n\n   {confirm_phrase}\n")
        typed = _prompt("> ")
        if typed is None:
            print("❌ Cancelled — nothing was touched.")
            return 1
        if typed.strip() != confirm_phrase:
            print(
                "❌ Confirmation did not match — restore cancelled. Nothing was touched."
            )
            return 1

    try:
        result_path = engine.restore_version(
            version_id, destination, overwrite=overwrite
        )
    except ve.VersionEngineError as e:
        print(f"❌ Restore failed: {e}")
        return 1

    print(f"\n✅ Restored and verified byte-for-byte: {result_path}")
    return 0


def do_delete(version_id: int, run_gc_now: bool = False) -> int:
    engine = _get_engine()
    conn = engine._connect()

    version = conn.execute(
        "SELECT v.*, f.path AS file_path FROM versions v "
        "JOIN files f ON f.file_id = v.file_id WHERE v.version_id=?",
        (version_id,),
    ).fetchone()
    if version is None:
        print(f"❌ No such version_id: {version_id}")
        return 1
    if version["status"] == "deleted":
        print(f"ℹ️  version_id {version_id} is already marked deleted.")
        return 0

    print("\n" + "🛑 " * 20)
    print("PERMANENT VERSION DELETION")
    print("🛑 " * 20)
    print(f"\n  File:        {version['file_path']}")
    print(f"  version_id:  {version_id}")
    print(f"  Snapshotted: {_fmt_time(version['created_at'])}")
    print(f"  Size:        {config.format_bytes(version['size'])}")
    print(f"  SHA-256:     {version['sha256']}")
    print(
        "\n  This is NOT the same as deleting the live file — this deletes a point-in-time"
        "\n  BACKUP of it. Once this is done, this exact version can never be recovered"
        "\n  through this tool again, by you or anyone else with access to this server."
        "\n  Retention and normal garbage collection do this automatically and safely on a"
        "\n  schedule — this command does it immediately and irreversibly, on purpose, right now."
    )

    other_versions = conn.execute(
        "SELECT COUNT(*) c FROM versions WHERE file_id=? AND status='completed' AND version_id != ?",
        (version["file_id"], version_id),
    ).fetchone()["c"]
    if other_versions:
        print(
            f"\n  ({other_versions} other version(s) of this file will remain untouched.)"
        )
    else:
        print(
            "\n  ⚠️  THIS IS THE ONLY REMAINING VERSION of this file. Deleting it erases ALL"
            "\n  version history for it — there will be nothing left to restore, ever, for this file."
        )

    confirm_phrase = (
        f"I understand this permanently and irreversibly deletes version {version_id} "
        f"of {os.path.basename(version['file_path'])} and cannot be undone"
    )
    print("\nTo proceed, type the following sentence EXACTLY, then press Enter:\n")
    print(f"    {confirm_phrase}\n")
    typed = _prompt("> ")
    if typed is None:
        print("\n❌ Cancelled — nothing was touched.")
        return 1
    if typed.strip() != confirm_phrase:
        print(
            "\n❌ That did not match exactly — deletion cancelled. Nothing was touched."
        )
        return 1

    ok, message = engine.delete_version(
        version_id,
        reason=f"manually deleted via version_manage.py at {_fmt_time(time.time())}",
    )
    if not ok:
        # Shouldn't normally happen — version/already-deleted checks above
        # already cover both cases this could fail for — but don't print a
        # false success if engine.delete_version() ever disagrees.
        print(f"\n❌ {message}")
        return 1
    print(f"\n✅ version_id {version_id} marked deleted.")
    print(
        "   Its storage objects aren't necessarily freed yet — they're reclaimed by the next "
        f"garbage-collection pass, after VERSION_GC_GRACE_PERIOD ({config.VERSION_GC_GRACE_PERIOD}s) "
        "has elapsed, same as automatic retention cleanup."
    )
    if run_gc_now:
        print("\nRunning garbage collection now (--run-gc-now)…")
        engine.run_gc()
        print(
            "   Note: objects orphaned by THIS delete still won't be freed until the grace"
        )
        print(
            "   period above has elapsed — --run-gc-now only reclaims objects that were"
        )
        print("   already past their grace period from earlier activity.")
    return 0


def _print_wal_sizes(db_path: str, sizes: dict) -> None:
    print(f"\n🗄️  {db_path}")
    print("=" * 78)
    print(f"  database file  {config.format_bytes(sizes['db']):>10}")
    print(f"  -wal file      {config.format_bytes(sizes['wal']):>10}")
    print(f"  -shm file      {config.format_bytes(sizes['shm']):>10}")
    limit = version_wal.limit_bytes(getattr(config, "VERSION_WAL_SIZE_LIMIT_MB", 64))
    if limit:
        print(
            f"  engine limit   {config.format_bytes(limit):>10}   "
            "(VERSION_WAL_SIZE_LIMIT_MB; above it the engine truncates the -wal after a GC / purge pass)"
        )
    else:
        print("  engine limit        off   (VERSION_WAL_SIZE_LIMIT_MB = 0)")


def do_wal(
    checkpoint: bool = False,
    mode: str = "truncate",
    timeout: float = 10.0,
    if_larger_mb=None,
) -> int:
    """Show the sizes of the database, -wal and -shm files; with checkpoint=True also run
    PRAGMA wal_checkpoint(<mode>) (TRUNCATE by default) and show the before / after.
    Exit code: 0 = shown, finished or nothing to do; 1 = busy / failed / no database."""
    engine = ve.Engine()
    db_path = engine.db_path
    if not os.path.exists(db_path):
        print(f"❌ No Version Engine database at: {db_path}")
        return 1

    sizes = version_wal.file_sizes(db_path)
    _print_wal_sizes(db_path, sizes)
    if not checkpoint:
        print(
            "\n  To shrink the -wal file: version-manage wal --checkpoint  "
            "(safe while the server runs; nothing can be lost)"
        )
        return 0

    if if_larger_mb is not None and sizes["wal"] <= if_larger_mb * version_wal.MB:
        print(f"\nℹ️  The -wal file is not above {if_larger_mb:g} MB: nothing to do.")
        return 0

    conn = engine._connect()
    try:
        result = version_wal.checkpoint(
            conn, db_path, mode, busy_timeout_ms=int(timeout * 1000)
        )
        db_after = version_wal.file_sizes(db_path)["db"]
    finally:
        conn.close()
        engine._conn_local.conn = None

    print(f"\n🧹 wal_checkpoint({result.mode}), waited up to {timeout:g}s for readers:")
    print(
        f"   -wal file:     {config.format_bytes(result.wal_before)} → "
        f"{config.format_bytes(result.wal_after)}   (took {result.seconds:.1f}s)"
    )
    print(
        f"   database file: {config.format_bytes(sizes['db'])} → "
        f"{config.format_bytes(db_after)}"
    )
    if result.error:
        print(f"❌ The checkpoint failed: {result.error}")
        return 1
    print(
        f"   (busy, frames in the log, frames written back) = "
        f"({result.busy}, {result.log_frames}, {result.checkpointed_frames})"
    )
    if result.busy:
        print(
            "⚠️  A reader or writer kept the checkpoint from finishing. Nothing is lost: run it "
            "again, raise --timeout, or stop the server first (./manage.sh stop)."
        )
        return 1
    if result.mode == "TRUNCATE":
        print(
            "✅ Done. The log is merged into the database and the -wal file is cut to zero."
        )
    else:
        print(
            f"✅ Done. The log is merged into the database. ({result.mode} does not shrink "
            "the -wal file; use TRUNCATE for that.)"
        )
    return 0


# =============================================================================
# CLI subcommand wrappers (argparse Namespace -> core function call)
# =============================================================================


def do_compress_probe(
    samples=version_probe.DEFAULT_SAMPLES,
    levels=version_probe.DEFAULT_LEVELS,
    seed=None,
    seconds=0.0,
    max_mb=0.0,
    busy_percent=version_probe.DEFAULT_BUSY_PERCENT,
    min_saving=version_probe.DEFAULT_MIN_SAVING,
    dictionary_test=True,
    delta_test=True,
    delta_pairs=version_probe.DEFAULT_DELTA_PAIRS,
    db_path=None,
    objects_dir=None,
) -> int:
    """READ-ONLY compression probe (VERSION_COMPRESSION_PLAN.md Phase 0). Never calls
    _get_engine(): that creates folders and tables, and the probe must change nothing.
    Exit code: 0 = report printed, 1 = cannot run (no zstd / no database), 130 = Ctrl-C
    (the partial report is still printed)."""
    engine = ve.Engine()  # paths only: its constructor starts nothing and opens nothing
    db_path = db_path or engine.db_path
    objects_dir = objects_dir or engine.objects_dir
    print("\n🔬 Compression probe: READ-ONLY, nothing in the object store is changed.")
    print(
        f"   Safe while the server runs; it works at about {busy_percent:g} % duty cycle."
    )
    try:
        report = version_probe.run_probe(
            db_path,
            objects_dir,
            samples=samples,
            levels=levels,
            seed=seed,
            min_saving_percent=min_saving,
            busy_percent=busy_percent,
            max_seconds=seconds,
            max_bytes=int(max_mb * 1024 * 1024),
            dictionary_test=dictionary_test,
            delta_test=delta_test,
            delta_pairs=delta_pairs,
            estimate_busy_percent=float(
                getattr(config, "VERSION_COMPRESSION_BUSY_PERCENT", 25)
            ),
            progress=lambda text: print(text, flush=True),
        )
    except version_probe.ProbeError as exc:
        print(f"❌ {exc}")
        return 1
    print()
    print(version_probe.format_report(report, db_path, objects_dir))
    return 130 if report["interrupted"] else 0


def _pause(seconds: float) -> bool:
    """The duty-cycle pause of the compress hand tools (a plain CLI process: time.sleep is fine
    here; the engine's own thread uses _shutdown_event.wait). False = keep going."""
    time.sleep(seconds)
    return False


def _compress_settings_now() -> dict:
    return {
        "enabled": bool(getattr(config, "VERSION_COMPRESSION_ENABLED", False)),
        "level": getattr(
            config, "VERSION_COMPRESSION_LEVEL", version_zstd.DEFAULT_LEVEL
        ),
        "min_saving": getattr(config, "VERSION_COMPRESSION_MIN_SAVING_PERCENT", 5),
        "busy": getattr(config, "VERSION_COMPRESSION_BUSY_PERCENT", 25),
        "interval": getattr(config, "VERSION_COMPRESSION_INTERVAL", 600),
        "delta_enabled": getattr(config, "VERSION_COMPRESSION_DELTA_ENABLED", False)
        is True,
        "delta_min_gain": getattr(
            config, "VERSION_COMPRESSION_DELTA_MIN_GAIN_PERCENT", 20
        ),
    }


def do_compress_status(db_path=None) -> int:
    """READ-ONLY: the numbers behind the compressor. Never calls _get_engine() (that creates
    folders and tables)."""
    engine = ve.Engine()  # paths only: its constructor starts nothing and opens nothing
    db_path = db_path or engine.db_path
    try:
        conn = version_probe.open_readonly(db_path)
    except version_probe.ProbeError as exc:
        print(f"❌ {exc}")
        return 1
    try:
        counts = version_compress.status_counts(conn, version_zstd.MIN_OBJECT_SIZE)
        meta = dict(conn.execute("SELECT key, value FROM engine_metadata").fetchall())
    finally:
        conn.close()
    print()
    print(
        version_compress.format_status(
            counts, meta, _compress_settings_now(), version_zstd.version()
        )
    )
    return 0


def _busy_or(value, default):
    return default if value is None else value


def do_compress_sweep(grace=0.0, busy_percent=100.0) -> int:
    """Remove the raw copy of every compressed object whose `.zst` verifies (again, now)."""
    engine = _get_engine()
    if not version_zstd.available():
        print("❌ zstd is not available in this Python: nothing can be verified.")
        return 1
    print(
        "\n🧹 Sweeping: the raw copy of an object is removed only after its compressed"
    )
    print("   copy was decoded and its SHA-256 compared again. Safe to interrupt.")
    try:
        res = engine.sweep_raw_copies(grace=grace, pause=_pause, busy=busy_percent)
    except KeyboardInterrupt:
        print(
            "\n⏹️  Interrupted. Every object handled so far is final and safe; run it again."
        )
        return 130
    print(
        f"\n  looked at {res['checked']:,} object(s): {res['removed']:,} raw copy(ies) removed, "
        f"{res['already_gone']:,} already gone, {res['busy']:,} busy (try again later)"
    )
    if res["bad"] or res["lost"]:
        print(
            f"  ⚠️  {res['bad']:,} compressed copy(ies) did not verify (the raw copy was kept), "
            f"{res['lost']:,} object(s) have no good copy at all: see the Version Engine log."
        )
        return 1
    print("  ✅ done.")
    return 0


def do_compress_verify(busy_percent=50.0) -> int:
    """Read-only integrity check of every compressed object."""
    engine = _get_engine()
    if not version_zstd.available():
        print("❌ zstd is not available in this Python: nothing can be verified.")
        return 1
    print(
        "\n🔎 Verifying every compressed object (decode + size + SHA-256); changes nothing."
    )
    try:
        res = engine.verify_compressed(pause=_pause, busy=busy_percent)
    except KeyboardInterrupt:
        print("\n⏹️  Interrupted; nothing was changed.")
        return 130
    print(
        f"\n  checked {res['checked']:,}: {res['ok']:,} ok, {res['bad']:,} with a bad "
        f"compressed copy (a good raw copy exists), {res['lost']:,} with NO good copy"
    )
    if res["examples"]:
        print(f"  first problems: {', '.join(res['examples'])}")
    if res["bad"] or res["lost"]:
        print("  ⚠️  see 'possible disk corruption' in the Version Engine log.")
        return 1
    print("  ✅ every compressed object is intact.")
    return 0


def do_compress_decompress(yes=False, force=False, busy_percent=100.0) -> int:
    """The way back: every compressed object becomes a plain raw file again."""
    engine = _get_engine()
    if not version_zstd.available():
        print(
            "❌ zstd is not available in this Python: compressed objects cannot be read."
        )
        return 1
    running = engine._get_meta("compress_running", "0") == "1"
    switched_on = bool(getattr(config, "VERSION_COMPRESSION_ENABLED", False))
    if (switched_on or running) and not force:
        print(
            "❌ Compression is still switched on"
            + (" and the engine reports its compress thread running" if running else "")
            + '.\n   Set "VERSION_COMPRESSION_ENABLED": false in server_config.json and\n'
            "   restart the Version Engine first (or stop the server), then run this again.\n"
            "   (--force skips this check: only if you know the engine is stopped.)"
        )
        return 1
    plan = engine.decompress_plan()
    if not plan["compressed_objects"]:
        print("ℹ️  No compressed objects: nothing to do.")
        return 0
    margin = max(512 * 1024 * 1024, plan["raw_bytes"] // 20)
    print("\n↩️  Decompress: turn every compressed object back into a plain raw file.")
    print(
        f"   {plan['compressed_objects']:,} compressed object(s); {plan['objects']:,} of them "
        f"have no raw copy and need to be written: {config.format_bytes(plan['raw_bytes'])}."
    )
    print(
        f"   Free space where the objects live: {config.format_bytes(plan['free_bytes'])}."
    )
    if plan["free_bytes"] < plan["raw_bytes"] + margin:
        print(
            f"❌ Not enough free space (needs {config.format_bytes(plan['raw_bytes'] + margin)} "
            "including a safety margin). Nothing was touched."
        )
        return 1
    if not yes:
        phrase = f"decompress {plan['compressed_objects']} objects"
        print(f"\nTo proceed, type exactly:  {phrase}\n")
        typed = _prompt("> ")
        if typed is None or typed.strip() != phrase:
            print("\n❌ Cancelled: nothing was touched.")
            return 1
    try:
        res = engine.decompress_all(pause=_pause, busy=busy_percent)
    except KeyboardInterrupt:
        print(
            "\n⏹️  Interrupted. Every object is either still compressed or already raw and"
        )
        print("   verified; run it again to finish.")
        return 130
    print(
        f"\n  {res['decompressed']:,} object(s) are raw files again, {res['lost']:,} could not "
        f"be restored (no good copy: see the Version Engine log), {res['error']:,} stopped by a "
        "disk problem (run again)."
    )
    if res["lost"] or res["error"]:
        return 1
    print(
        "  ✅ done. Leave VERSION_COMPRESSION_ENABLED off, or the compressor starts again."
    )
    return 0


def cmd_list(args):
    return do_list(args.file_path)


def cmd_restore(args):
    return do_restore(args.version_id, args.destination, overwrite=args.overwrite)


def cmd_delete(args):
    return do_delete(args.version_id, run_gc_now=args.run_gc_now)


def cmd_wal(args):
    if not args.checkpoint and (
        args.mode is not None
        or args.timeout is not None
        or args.if_larger_mb is not None
    ):
        print("❌ --mode, --timeout and --if-larger-mb only apply with --checkpoint.")
        return 2
    return do_wal(
        checkpoint=args.checkpoint,
        mode=args.mode or "truncate",
        timeout=10.0 if args.timeout is None else args.timeout,
        if_larger_mb=args.if_larger_mb,
    )


def cmd_compress(args):
    probe_only = {
        "--samples": args.samples,
        "--levels": args.levels,
        "--seed": args.seed,
        "--seconds": args.seconds,
        "--max-bytes": args.max_bytes,
        "--min-saving": args.min_saving,
        "--delta-pairs": args.delta_pairs,
        "--objects": args.objects,
        "--no-dictionary": args.no_dictionary or None,
        "--no-delta": args.no_delta or None,
    }
    actions = [
        name
        for name, on in (
            ("--probe", args.probe),
            ("--status", args.status),
            ("--sweep", args.sweep),
            ("--verify", args.verify),
            ("--decompress", args.decompress),
        )
        if on
    ]
    if len(actions) > 1:
        print(f"❌ Choose ONE action, not {' and '.join(actions)}.")
        return 2
    action = actions[0] if actions else None
    given_probe_only = [n for n, v in probe_only.items() if v is not None]
    if action != "--probe" and (
        given_probe_only or (args.db is not None and action != "--status")
    ):
        print("❌ These options only apply with --probe.")
        return 2
    if action is None:
        if (
            args.busy_percent is not None
            or args.grace is not None
            or args.yes
            or args.force
        ):
            print("❌ Choose an action first.")
            return 2
        print(
            "❌ Choose an action: --probe, --status, --sweep, --verify or --decompress."
        )
        return 2
    if args.grace is not None and action != "--sweep":
        print("❌ --grace only applies with --sweep.")
        return 2
    if (args.yes or args.force) and action != "--decompress":
        print("❌ --yes and --force only apply with --decompress.")
        return 2
    if args.busy_percent is not None and action == "--status":
        print("❌ --busy-percent does not apply to --status.")
        return 2

    if action == "--status":
        return do_compress_status(db_path=args.db)
    if action == "--sweep":
        return do_compress_sweep(
            grace=_busy_or(args.grace, 0.0),
            busy_percent=_busy_or(args.busy_percent, 100.0),
        )
    if action == "--verify":
        return do_compress_verify(busy_percent=_busy_or(args.busy_percent, 50.0))
    if action == "--decompress":
        return do_compress_decompress(
            yes=args.yes,
            force=args.force,
            busy_percent=_busy_or(args.busy_percent, 100.0),
        )

    def given(value, default):
        return default if value is None else value

    return do_compress_probe(
        samples=given(args.samples, version_probe.DEFAULT_SAMPLES),
        levels=given(args.levels, version_probe.DEFAULT_LEVELS),
        seed=args.seed,
        seconds=given(args.seconds, 0.0),
        max_mb=given(args.max_bytes, 0.0),
        busy_percent=given(args.busy_percent, version_probe.DEFAULT_BUSY_PERCENT),
        min_saving=given(args.min_saving, version_probe.DEFAULT_MIN_SAVING),
        dictionary_test=not args.no_dictionary,
        delta_test=not args.no_delta,
        delta_pairs=given(args.delta_pairs, version_probe.DEFAULT_DELTA_PAIRS),
        db_path=args.db,
        objects_dir=args.objects,
    )


# =============================================================================
# Interactive menu — same do_list/do_restore/do_delete underneath, nothing
# duplicated. Ctrl-C at the top-level menu prompt exits (matches manage.sh's
# cmd_menu's own convention: "Ctrl-C / Ctrl-D / closed stdin at the
# top-level prompt = quit"); Ctrl-C inside an action's own sub-prompts just
# cancels that action and returns to the menu.
# =============================================================================


def _read_int(msg: str):
    """Prompt for an integer (a version_id). Returns None on cancel OR on
    invalid input — the caller just returns to the menu either way, no
    separate error branch needed."""
    raw = _prompt(msg)
    if raw is None:
        return None
    raw = raw.strip()
    if not raw.isdigit():
        print("❌ Not a number.")
        return None
    return int(raw)


def _read_yn(msg: str, default=False) -> bool:
    raw = _prompt(msg)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _print_compress_settings() -> None:
    """The seven compression settings as the loader read them, read-only (this script never
    edits config: `./manage.sh config` > Version Engine > Engine settings > 13 does)."""
    s = _compress_settings_now()
    print(
        f"   Compression: {'ON' if s['enabled'] else 'OFF'}, zstd level {s['level']}, "
        f"min saving {s['min_saving']} %, busy {s['busy']} %, idle look every {s['interval']} s"
    )
    print(
        f"   Delta: {'ON' if s['delta_enabled'] else 'OFF'}, min gain {s['delta_min_gain']} %"
    )
    print(
        "   (change them in ./manage.sh config > Version Engine > Engine settings > 13;"
        " restart the Version Engine afterwards)"
    )


def compression_menu() -> None:
    """Sub-menu of the interactive menu: the object-compression hand tools. Each entry calls the
    same do_compress_* function as `compress --status|--probe|--sweep|--verify|--decompress`
    with that command's defaults, so nothing is duplicated and the command line is unchanged.
    Ctrl-C / Ctrl-D at the sub-menu prompt goes back to the main menu."""
    while True:
        print("\n" + "=" * 60)
        print("  Object compression (zstd)")
        _print_compress_settings()
        print("=" * 60)
        print(
            "  1) Status             (read-only: compressed so far, backlog, the thread)"
        )
        print(
            "  2) Probe              (read-only: what would zstd save on the real store)"
        )
        print(
            "  3) Sweep              (remove raw copies whose compressed copy verifies)"
        )
        print(
            "  4) Verify             (re-read and hash-check every compressed object)"
        )
        print(
            "  5) Decompress         (the way back: every object a plain raw file again)"
        )
        print("  6) Back")
        print("=" * 60)

        choice = _prompt("\nSelect option (1-6): ")
        if choice is None:
            return
        choice = choice.strip()

        if choice == "1":
            do_compress_status()
        elif choice == "2":
            print(
                "\nThe probe can take several minutes; Ctrl-C stops it and prints what it read."
            )
            do_compress_probe()
        elif choice == "3":
            if not _read_yn(
                "Remove the raw copy of every compressed object whose compressed copy "
                "verifies now? (y/N): ",
                default=False,
            ):
                print("❌ Cancelled: nothing was touched.")
                continue
            do_compress_sweep()
        elif choice == "4":
            do_compress_verify()
        elif choice == "5":
            # asks for the typed phrase itself (and refuses while compression is switched on)
            do_compress_decompress()
        elif choice in ("6", "b", "B", "q", "Q"):
            return
        else:
            print(f"❌ Invalid option: {choice}")
            continue

        _prompt("\nPress Enter to return to the menu…")


def interactive_menu():
    print("\n🕓 Version Engine — interactive management")
    print(
        "   (Ctrl-C at this menu exits; Ctrl-C inside an action cancels that action.)"
    )

    while True:
        print("\n" + "=" * 60)
        print("  1) List all tracked files")
        print("  2) View one file's version history")
        print("  3) Restore a version")
        print("  4) Delete a version")
        print("  5) Run garbage collection now")
        print("  6) WAL file: show its size / shrink it (checkpoint)")
        print("  7) Object compression: status / probe / sweep / verify / decompress")
        print("  8) Exit")
        print("=" * 60)

        choice = _prompt("\nSelect option (1-8): ")
        if choice is None:
            print("👋 Goodbye!")
            return 0
        choice = choice.strip()

        if choice == "1":
            do_list()

        elif choice == "2":
            path = _prompt("File path: ")
            if path is None or not path.strip():
                continue
            do_list(path.strip())

        elif choice == "3":
            version_id = _read_int("version_id to restore: ")
            if version_id is None:
                continue
            destination = _prompt("Restore to path: ")
            if destination is None or not destination.strip():
                continue
            destination = destination.strip()
            overwrite = False
            if os.path.exists(os.path.abspath(os.path.expanduser(destination))):
                overwrite = _read_yn(
                    f"'{destination}' already exists — overwrite it? (y/N): ",
                    default=False,
                )
                if not overwrite:
                    print(
                        "❌ Not overwriting — cancelled. Choose a different destination to proceed."
                    )
                    continue
            do_restore(version_id, destination, overwrite=overwrite)

        elif choice == "4":
            version_id = _read_int("version_id to delete: ")
            if version_id is None:
                continue
            run_gc_now = _read_yn(
                "Also run garbage collection immediately afterward? (y/N): ",
                default=False,
            )
            do_delete(version_id, run_gc_now=run_gc_now)

        elif choice == "5":
            print("\nRunning garbage collection…")
            engine = _get_engine()
            engine.run_gc()
            print("Done.")

        elif choice == "6":
            do_wal()
            if _read_yn(
                "Run the checkpoint (TRUNCATE) now? Nothing can be lost (y/N): ",
                default=False,
            ):
                do_wal(checkpoint=True)

        elif choice == "7":
            compression_menu()
            continue

        elif choice in ("8", "q", "Q"):
            print("👋 Goodbye!")
            return 0

        else:
            print(f"❌ Invalid option: {choice}")

        _prompt("\nPress Enter to return to the menu…")


# =============================================================================


def _seconds_arg(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0 <= value <= 600:
        raise argparse.ArgumentTypeError("must be from 0 to 600 seconds")
    return value


def _mb_arg(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0 <= value <= version_wal.MAX_LIMIT_MB:
        raise argparse.ArgumentTypeError(
            f"must be from 0 to {version_wal.MAX_LIMIT_MB} MB"
        )
    return value


def _ranged_number(low, high, kind=float, unit=""):
    """An argparse type: a number from `low` to `high` (inclusive)."""

    def convert(text):
        try:
            value = kind(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"must be from {low:g} to {high:g}{unit}")
        return value

    return convert


def _levels_arg(text: str):
    try:
        return version_probe.parse_levels(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Admin CLI for the Version Engine — list, restore, delete versions and shrink the WAL file. "
        "Run with no arguments for an interactive menu instead.",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    p_list = sub.add_parser(
        "list", help="List tracked files, or one file's full version history"
    )
    p_list.add_argument("file_path", nargs="?", default=None)
    p_list.set_defaults(func=cmd_list)

    p_restore = sub.add_parser(
        "restore", help="Restore a version to a destination path"
    )
    p_restore.add_argument("version_id", type=int)
    p_restore.add_argument("destination")
    p_restore.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing file at the destination (asks for typed confirmation)",
    )
    p_restore.set_defaults(func=cmd_restore)

    p_delete = sub.add_parser(
        "delete",
        help="Permanently delete one version (asks for a typed confirmation sentence)",
    )
    p_delete.add_argument("version_id", type=int)
    p_delete.add_argument(
        "--run-gc-now",
        action="store_true",
        help="Also run a garbage-collection pass immediately after deleting",
    )
    p_delete.set_defaults(func=cmd_delete)

    p_wal = sub.add_parser(
        "wal",
        help="Show the size of the database's write-ahead log (-wal file), or shrink it",
    )
    p_wal.add_argument(
        "--checkpoint",
        action="store_true",
        help="Run PRAGMA wal_checkpoint (TRUNCATE by default); safe while the server runs",
    )
    p_wal.add_argument(
        "--mode",
        choices=["passive", "full", "restart", "truncate"],
        default=None,
        help="Checkpoint mode (default truncate: merge and cut the file to zero bytes)",
    )
    p_wal.add_argument(
        "--timeout",
        type=_seconds_arg,
        default=None,
        help="Seconds to wait for readers / writers (0 to 600, default 10)",
    )
    p_wal.add_argument(
        "--if-larger-mb",
        type=_mb_arg,
        default=None,
        help="Only checkpoint when the -wal file is above this many MB (0 to 64)",
    )
    p_wal.set_defaults(func=cmd_wal)

    p_compress = sub.add_parser(
        "compress",
        help="Object compression: --probe measures the real store, --status / --sweep / "
        "--verify / --decompress manage the compressed objects",
    )
    p_compress.add_argument(
        "--probe",
        action="store_true",
        help="Read-only measurement of zstd on a random sample of the real objects",
    )
    p_compress.add_argument(
        "--status",
        action="store_true",
        help="Read-only: how much is compressed, the backlog and the thread (5.47)",
    )
    p_compress.add_argument(
        "--sweep",
        action="store_true",
        help="Remove the raw copy of every compressed object whose compressed copy verifies",
    )
    p_compress.add_argument(
        "--verify",
        action="store_true",
        help="Re-read and hash-check every compressed object (changes nothing)",
    )
    p_compress.add_argument(
        "--decompress",
        action="store_true",
        help="Turn every compressed object back into a plain raw file (the way back to 5.45.1)",
    )
    p_compress.add_argument(
        "--grace",
        type=_ranged_number(0, 86400),
        default=None,
        metavar="SECONDS",
        help="With --sweep: only objects compressed at least this long ago (default 0)",
    )
    p_compress.add_argument(
        "--yes",
        action="store_true",
        help="With --decompress: do not ask for the typed phrase",
    )
    p_compress.add_argument(
        "--force",
        action="store_true",
        help="With --decompress: skip the 'compression is switched on' check (engine stopped)",
    )
    p_compress.add_argument(
        "--samples",
        type=_ranged_number(1, 100000, int),
        default=None,
        help="Objects to sample at random (1 to 100000, default 400)",
    )
    p_compress.add_argument(
        "--levels",
        type=_levels_arg,
        default=None,
        help="Comma-separated zstd levels, each 1 to 22 (default 1,3,9,15,19,22)",
    )
    p_compress.add_argument(
        "--seed",
        type=_ranged_number(1, 2**31 - 1, int),
        default=None,
        help="Repeat an earlier sample (the report prints its seed)",
    )
    p_compress.add_argument(
        "--seconds",
        type=_ranged_number(0, 86400),
        default=None,
        help="Stop after about this many seconds (0 = no limit); the report covers what was read",
    )
    p_compress.add_argument(
        "--max-bytes",
        type=_ranged_number(0, 10**9),
        default=None,
        metavar="MB",
        help="Stop after reading about this many MB from the store (0 = no limit)",
    )
    p_compress.add_argument(
        "--busy-percent",
        type=_ranged_number(5, 100, float, " %"),
        default=None,
        help="Duty cycle: 50 = pause as long as it works; 100 = no pauses (defaults: probe 50, "
        "verify 50, sweep and decompress 100)",
    )
    p_compress.add_argument(
        "--min-saving",
        type=_ranged_number(0, 50, float, " %"),
        default=None,
        help="An object only counts as shrunk if it is at least this much smaller (default 5)",
    )
    p_compress.add_argument(
        "--no-dictionary", action="store_true", help="Skip the trained-dictionary test"
    )
    p_compress.add_argument(
        "--no-delta", action="store_true", help="Skip the previous-version delta test"
    )
    p_compress.add_argument(
        "--delta-pairs",
        type=_ranged_number(1, 5000, int),
        default=None,
        help="Chunk pairs for the delta test (default 200)",
    )
    p_compress.add_argument(
        "--db",
        default=None,
        help="Probe / show this database file instead of the configured one",
    )
    p_compress.add_argument(
        "--objects",
        default=None,
        help="Use this objects folder instead of the configured one",
    )
    p_compress.set_defaults(func=cmd_compress)

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command is None:
            sys.exit(interactive_menu())
        else:
            sys.exit(args.func(args))
    except KeyboardInterrupt:
        # Belt-and-suspenders: covers a Ctrl-C landing outside any _prompt()
        # call (e.g. mid-query on a very large DB) — every interactive
        # input() is already wrapped by _prompt(), but this guarantees no
        # path through this script ever surfaces a raw traceback for Ctrl-C.
        print("\n👋 Cancelled.")
        sys.exit(130)  # 128 + SIGINT — matches the shell's own convention


if __name__ == "__main__":
    main()
