#!/usr/bin/env python3
"""
revoke_sharing.py — Backend/CLI management for CloudinatorFTP share links
---------------------------------------------------------------------------
Lets an operator list and revoke public share links directly from the
server, without needing to log into the web UI. Useful when the frontend
is unreachable, when scripting a bulk cleanup, or as a "break glass"
tool if a share link needs to be killed immediately.

Talks directly to the same SQLite-backed `db` singleton the Flask app
uses (database.py) — no HTTP calls, no running server required.

USAGE
    python revoke_sharing.py list
    python revoke_sharing.py revoke <token>
    python revoke_sharing.py revoke-path <path>
    python revoke_sharing.py revoke-all
    python revoke_sharing.py revoke-all --yes      # skip the y/N prompt (still requires the typed code)

Every destructive action (single revoke, revoke-all) asks for confirmation
before touching the database. revoke-all additionally requires typing back
a freshly-randomized 10-digit code shown on screen — the same "type the
code" pattern used by the admin 'Revoke All Shares' button in the web UI —
so a scripted/careless invocation can't nuke every share link by accident.
--yes only skips the initial y/N prompt; the typed-code step always runs.
"""

import argparse
import random
import sys
import time

from database import db


def _fmt_ts(ts):
    if not ts:
        return "--"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def cmd_list(_args):
    shares = db.list_active_shares()
    if not shares:
        print("No active share links.")
        return

    print(f"\n{len(shares)} active share link(s):\n")
    print(
        f"{'TOKEN':<20} {'NAME':<30} {'TYPE':<6} {'CREATED BY':<15} {'CREATED':<20} {'DOWNLOADS':<10}"
    )
    print("-" * 105)
    for s in shares:
        kind = "dir" if s["is_dir"] else "file"
        print(
            f"{s['token']:<20} {s['item_name'][:29]:<30} {kind:<6} "
            f"{(s['created_by'] or '--')[:14]:<15} {_fmt_ts(s['created_at']):<20} "
            f"{s['download_count']:<10}"
        )
        print(f"{'':<20} path: {s['file_path']}")
    print()


def _confirm_yes_no(prompt):
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer == "y"


def cmd_revoke(args):
    share = db.get_share_by_token(args.token)
    if not share:
        print(f"❌ No active share link found for token: {args.token}")
        sys.exit(1)

    print("About to revoke share link:")
    print(f"  token : {share['token']}")
    print(f"  path  : {share['file_path']}")
    print(f"  name  : {share['item_name']}")

    if not args.yes and not _confirm_yes_no("Revoke this share link?"):
        print("Cancelled — nothing revoked.")
        return

    if db.revoke_share_by_token(args.token):
        print(f"✅ Revoked share link: {args.token}")
    else:
        print(
            f"❌ Failed to revoke (already revoked or removed concurrently): {args.token}"
        )
        sys.exit(1)


def cmd_revoke_path(args):
    share = db.get_share_by_path(args.path)
    if not share:
        print(f"❌ No active share link found for path: {args.path}")
        sys.exit(1)

    print(f"About to revoke share link for: {args.path} (token: {share['token']})")
    if not args.yes and not _confirm_yes_no("Revoke this share link?"):
        print("Cancelled — nothing revoked.")
        return

    if db.revoke_share_by_path(args.path):
        print(f"✅ Revoked share link for: {args.path}")
    else:
        print(
            f"❌ Failed to revoke (already revoked or removed concurrently): {args.path}"
        )
        sys.exit(1)


def cmd_revoke_all(args):
    shares = db.list_active_shares()
    if not shares:
        print("No active share links — nothing to revoke.")
        return

    print(f"⚠️  This will revoke ALL {len(shares)} currently active share link(s).")
    print(
        "    This cannot be undone — every shared link will stop working immediately.\n"
    )

    if not args.yes and not _confirm_yes_no("Continue to the confirmation code?"):
        print("Cancelled — nothing revoked.")
        return

    code = "".join(random.choices("0123456789", k=10))
    print(
        "\nType the code below exactly to confirm (a new code is generated every attempt):\n"
    )
    print(f"    {code}\n")
    typed = input("Confirmation code: ").strip()

    if typed != code:
        print(
            "❌ Code did not match — nothing revoked. Run the command again to try again."
        )
        sys.exit(1)

    count = db.revoke_all_shares()
    print(f"✅ Revoked {count} share link(s).")


def main():
    parser = argparse.ArgumentParser(
        description="List and revoke CloudinatorFTP public share links from the backend."
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all currently active share links").set_defaults(
        func=cmd_list
    )

    p_revoke = sub.add_parser("revoke", help="Revoke a single share link by token")
    p_revoke.add_argument("token", help="Share token to revoke")
    p_revoke.add_argument(
        "--yes", action="store_true", help="Skip the y/N confirmation prompt"
    )
    p_revoke.set_defaults(func=cmd_revoke)

    p_revoke_path = sub.add_parser(
        "revoke-path", help="Revoke the active share link for a given file/folder path"
    )
    p_revoke_path.add_argument(
        "path",
        help="File or folder path (as stored/shared, relative to the storage root)",
    )
    p_revoke_path.add_argument(
        "--yes", action="store_true", help="Skip the y/N confirmation prompt"
    )
    p_revoke_path.set_defaults(func=cmd_revoke_path)

    p_revoke_all = sub.add_parser("revoke-all", help="Revoke every active share link")
    p_revoke_all.add_argument(
        "--yes",
        action="store_true",
        help="Skip the initial y/N prompt (the typed 10-digit confirmation code is still required)",
    )
    p_revoke_all.set_defaults(func=cmd_revoke_all)

    args = parser.parse_args()
    if not args.command:
        cmd_list(args)
        return
    args.func(args)


if __name__ == "__main__":
    main()
