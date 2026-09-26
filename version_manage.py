#!/usr/bin/env python3
"""
version_manage.py — Admin CLI + interactive menu for the Version Engine
=========================================================================
list / restore / delete against version_engine.sqlite3, deliberately kept
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
do_delete), never duplicated:

    python version_manage.py                          # interactive menu
    python version_manage.py list                      # every tracked file + version count
    python version_manage.py list <file_path>           # every version of one file
    python version_manage.py restore <version_id> <destination> [--overwrite]
    python version_manage.py delete <version_id> [--run-gc-now]

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

import config
import version_engine as ve
from config import format_bytes


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

        rows = conn.execute(
            "SELECT version_id, sha256, size, storage_mode, status, created_at, completed_at, error "
            "FROM versions WHERE file_id=? ORDER BY created_at DESC",
            (file_row["file_id"],),
        ).fetchall()

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
                f"{format_bytes(r['size']):>10}   "
                f"{r['storage_mode']:<8}   "
                f"sha256={r['sha256'][:12] if r['sha256'] else '—'}…   "
                f"status={r['status']}"
            )
            if r["error"]:
                print(f"         ↳ {r['error']}")
        return 0

    # No file given — summary across all tracked files.
    rows = conn.execute(
        "SELECT f.file_id, f.path, f.deleted, "
        "COUNT(CASE WHEN v.status='completed' THEN 1 END) AS n_completed, "
        "MAX(v.created_at) AS last_activity "
        "FROM files f LEFT JOIN versions v ON v.file_id = f.file_id "
        "GROUP BY f.file_id ORDER BY last_activity DESC"
    ).fetchall()

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
    print(f"📦 Size:             {format_bytes(version['size'])}")
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
    print(f"  Size:        {format_bytes(version['size'])}")
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

    conn.execute(
        "UPDATE versions SET status='deleted', error=? WHERE version_id=?",
        (
            f"manually deleted via version_manage.py at {_fmt_time(time.time())}",
            version_id,
        ),
    )
    conn.commit()
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


# =============================================================================
# CLI subcommand wrappers (argparse Namespace -> core function call)
# =============================================================================


def cmd_list(args):
    return do_list(args.file_path)


def cmd_restore(args):
    return do_restore(args.version_id, args.destination, overwrite=args.overwrite)


def cmd_delete(args):
    return do_delete(args.version_id, run_gc_now=args.run_gc_now)


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
        print("  6) Exit")
        print("=" * 60)

        choice = _prompt("\nSelect option (1-6): ")
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

        elif choice in ("6", "q", "Q"):
            print("👋 Goodbye!")
            return 0

        else:
            print(f"❌ Invalid option: {choice}")

        _prompt("\nPress Enter to return to the menu…")


# =============================================================================


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Admin CLI for the Version Engine — list, restore, and delete versions. "
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
