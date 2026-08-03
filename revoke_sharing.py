#!/usr/bin/env python3
"""
revoke_sharing.py — Backend/CLI management for CloudinatorFTP share links
---------------------------------------------------------------------------
Lets an operator manage public share links directly from the server,
without needing to log into the web UI. Useful when the frontend is
unreachable, when scripting a bulk cleanup, or as a "break glass" tool
if a share link needs to be killed immediately.

Talks directly to the same SQLite-backed `db` singleton the Flask app
uses (database.py) — no HTTP calls, no running server required.

CLI USAGE (unchanged — safe to call from scripts or manage.sh directly)
    python revoke_sharing.py list
    python revoke_sharing.py revoke <token>
    python revoke_sharing.py revoke-path <path>
    python revoke_sharing.py revoke-all               [--yes]
    python revoke_sharing.py requests                 # pending access requests
    python revoke_sharing.py approve <request_id>      [--max-downloads N]
    python revoke_sharing.py deny <request_id>
    python revoke_sharing.py edit <token>              [--mode MODE] [--passkey KEY]
                                                        [--generate-passkey] [--clear-passkey]
                                                        [--expires-in DURATION] [--never-expire]
    python revoke_sharing.py edit-path <path>          [same flags as edit]

Every destructive action (single revoke, revoke-all) asks for confirmation
before touching the database. revoke-all additionally requires typing back
a freshly-randomized 10-digit code shown on screen — the same "type the
code" pattern used by the admin 'Revoke All Shares' → Danger Zone button
in the web UI — so a scripted/careless invocation can't nuke every share
link by accident. --yes only skips the initial y/N prompt; the typed-code
step always runs.

INTERACTIVE MODE
    python revoke_sharing.py           # no subcommand → menu loop

Run with no arguments and it drops into a numbered menu instead of a
single one-shot action, so an operator can list shares, revoke one, edit
its security, or work through the pending-approvals queue, all in one
sitting — the menu keeps re-displaying after each action until you choose
Exit (0), at which point the script returns control to its caller (e.g.
manage.sh) exactly like any single CLI command does.
"""

import argparse
import getpass
import random
import re
import sys
import time

from database import db

DURATION_RE = re.compile(r"^(\d+)\s*([smhdw]?)$", re.IGNORECASE)
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "": 1}


def _operator_id():
    """Identity recorded as 'decided_by' / 'created_by' for actions taken
    from this CLI, so the admin UI's history is honest about where an
    approval or edit came from."""
    try:
        return f"cli:{getpass.getuser()}"
    except Exception:
        return "cli"


def _fmt_ts(ts):
    if not ts:
        return "--"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _fmt_expiry(ts):
    if not ts:
        return "never"
    if ts <= time.time():
        return "expired"
    return _fmt_ts(ts)


def _parse_duration(raw):
    """'1h' / '2d' / '30m' / '3600' (seconds) → absolute epoch timestamp.
    Raises ValueError on anything unrecognized."""
    raw = raw.strip().lower()
    m = DURATION_RE.match(raw)
    if not m:
        raise ValueError(
            f"Invalid duration: {raw!r} — use e.g. 1h, 2d, 30m, 7d, or a plain number of seconds"
        )
    amount, unit = m.groups()
    return time.time() + int(amount) * DURATION_UNITS[unit]


def _confirm_yes_no(prompt):
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer == "y"


# ------------------------------------------------------------------
# Active shares
# ------------------------------------------------------------------


def cmd_list(_args):
    shares = db.list_active_shares()
    if not shares:
        print("No active share links.")
        return

    print(f"\n{len(shares)} active share link(s):\n")
    print(
        f"{'TOKEN':<20} {'NAME':<26} {'TYPE':<6} {'MODE':<9} {'EXPIRES':<20} "
        f"{'CREATED BY':<15} {'DOWNLOADS':<10}"
    )
    print("-" * 115)
    for s in shares:
        kind = "dir" if s["is_dir"] else "file"
        mode = s.get("security_mode", "public")
        print(
            f"{s['token']:<20} {s['item_name'][:25]:<26} {kind:<6} {mode:<9} "
            f"{_fmt_expiry(s.get('expires_at')):<20} {(s['created_by'] or '--')[:14]:<15} "
            f"{s['download_count']:<10}"
        )
        print(f"{'':<20} path: {s['file_path']}")
    print()


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


# ------------------------------------------------------------------
# Share security editing (mode / passkey / expiry)
# ------------------------------------------------------------------


def _generate_passkey(length=8):
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    return "".join(random.choice(alphabet) for _ in range(length))


def _apply_edit(share, args):
    kwargs = {}
    if args.mode:
        kwargs["security_mode"] = args.mode
    if args.clear_passkey:
        kwargs["clear_passkey"] = True
    if args.never_expire:
        kwargs["clear_expiry"] = True
    elif args.expires_in:
        try:
            kwargs["expires_at"] = _parse_duration(args.expires_in)
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)

    plain_passkey = None
    target_mode = args.mode or share["security_mode"]
    if target_mode == "passkey" and (args.generate_passkey or args.passkey):
        plain_passkey = _generate_passkey() if args.generate_passkey else args.passkey
        kwargs["passkey"] = plain_passkey

    if not kwargs:
        print(
            "Nothing to change — pass at least one of --mode/--passkey/--generate-passkey/"
            "--clear-passkey/--expires-in/--never-expire."
        )
        return

    ok = db.update_share_settings(share["token"], **kwargs)
    if not ok:
        print("❌ Failed to update — share may have been revoked concurrently.")
        sys.exit(1)

    print(f"✅ Updated share settings for: {share['file_path']}")
    if plain_passkey:
        print(f"   New passkey (shown once — save it now): {plain_passkey}")


def cmd_edit(args):
    share = db.get_share_by_token(args.token)
    if not share:
        print(f"❌ No active share link found for token: {args.token}")
        sys.exit(1)
    _apply_edit(share, args)


def cmd_edit_path(args):
    share = db.get_share_by_path(args.path)
    if not share:
        print(f"❌ No active share link found for path: {args.path}")
        sys.exit(1)
    _apply_edit(share, args)


def _add_edit_flags(parser):
    parser.add_argument(
        "--mode",
        choices=["public", "passkey", "approval"],
        help="Change the security mode",
    )
    parser.add_argument(
        "--passkey",
        help="Set a specific passkey (implies --mode passkey unless already set)",
    )
    parser.add_argument(
        "--generate-passkey", action="store_true", help="Generate a new random passkey"
    )
    parser.add_argument(
        "--clear-passkey", action="store_true", help="Remove the current passkey"
    )
    parser.add_argument(
        "--expires-in",
        help="Set expiry as a duration, e.g. 1h, 2d, 30m, 7d, or raw seconds",
    )
    parser.add_argument(
        "--never-expire", action="store_true", help="Clear the current expiry"
    )


# ------------------------------------------------------------------
# Approval workflow — pending access requests
# ------------------------------------------------------------------


def cmd_requests(_args):
    pending = db.list_pending_requests()
    if not pending:
        print("No pending access requests.")
        return

    print(f"\n{len(pending)} pending access request(s):\n")
    print(f"{'ID':<6} {'REQUESTER':<20} {'ITEM':<26} {'REQUESTED':<20} {'NOTE'}")
    print("-" * 100)
    for r in pending:
        print(
            f"{r['id']:<6} {r['requester_name'][:19]:<20} {r['item_name'][:25]:<26} "
            f"{_fmt_ts(r['requested_at']):<20} {(r['requester_note'] or '')[:40]}"
        )
    print()


def cmd_approve(args):
    ok = db.approve_access_request(args.request_id, _operator_id(), args.max_downloads)
    if ok:
        print(
            f"✅ Approved request {args.request_id} — granted {args.max_downloads} download(s)."
        )
    else:
        print(f"❌ Request {args.request_id} not found or already decided.")
        sys.exit(1)


def cmd_deny(args):
    ok = db.deny_access_request(args.request_id, _operator_id())
    if ok:
        print(f"🚫 Denied request {args.request_id}.")
    else:
        print(f"❌ Request {args.request_id} not found or already decided.")
        sys.exit(1)


# ------------------------------------------------------------------
# Interactive menu — loops until the operator chooses Exit, then returns
# normally to whatever invoked this script (e.g. manage.sh's own menu).
# ------------------------------------------------------------------


class _Args:
    """Tiny stand-in for argparse.Namespace so interactive-mode prompts can
    reuse the exact same cmd_* / edit-flag logic as the CLI subcommands."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _prompt(label, default=None):
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{label}{suffix}: ").strip()
    return val or default


def _interactive_edit_flags():
    print("Leave any field blank to leave it unchanged.")
    mode = _prompt("New mode (public/passkey/approval)") or None
    if mode and mode not in ("public", "passkey", "approval"):
        print("Invalid mode — ignoring.")
        mode = None

    passkey = None
    generate_passkey = False
    clear_passkey = False
    if mode == "passkey" or (mode is None and _confirm_yes_no("Change the passkey?")):
        choice = (
            _prompt(
                "Type a passkey, or 'gen' to auto-generate, or 'clear' to remove it"
            )
            or ""
        )
        if choice.lower() == "gen":
            generate_passkey = True
        elif choice.lower() == "clear":
            clear_passkey = True
        elif choice:
            passkey = choice

    expires_in = None
    never_expire = False
    if _confirm_yes_no("Change the expiry?"):
        choice = _prompt("Duration (e.g. 1h, 2d, 7d), or 'never' to clear") or ""
        if choice.lower() == "never":
            never_expire = True
        elif choice:
            expires_in = choice

    return _Args(
        mode=mode,
        passkey=passkey,
        generate_passkey=generate_passkey,
        clear_passkey=clear_passkey,
        expires_in=expires_in,
        never_expire=never_expire,
    )


def _menu_list():
    cmd_list(None)


def _menu_revoke():
    token = _prompt("Token to revoke")
    if not token:
        return
    cmd_revoke(_Args(token=token, yes=False))


def _menu_revoke_path():
    path = _prompt("Path to revoke")
    if not path:
        return
    cmd_revoke_path(_Args(path=path, yes=False))


def _menu_edit():
    token = _prompt("Token to edit")
    if not token:
        return
    share = db.get_share_by_token(token)
    if not share:
        print(f"❌ No active share link found for token: {token}")
        return
    print(
        f"Current: mode={share['security_mode']} expires={_fmt_expiry(share.get('expires_at'))} "
        f"passkey_set={bool(share.get('passkey_hash'))}"
    )
    _apply_edit(share, _interactive_edit_flags())


def _menu_requests():
    cmd_requests(None)


def _menu_approve():
    try:
        request_id = int(_prompt("Request ID to approve"))
    except (TypeError, ValueError):
        print("❌ Invalid request ID.")
        return
    try:
        max_downloads = int(_prompt("Max downloads to grant", "1"))
    except (TypeError, ValueError):
        max_downloads = 1
    cmd_approve(_Args(request_id=request_id, max_downloads=max_downloads))


def _menu_deny():
    try:
        request_id = int(_prompt("Request ID to deny"))
    except (TypeError, ValueError):
        print("❌ Invalid request ID.")
        return
    cmd_deny(_Args(request_id=request_id))


def _menu_revoke_all():
    cmd_revoke_all(_Args(yes=False))


_MENU_ITEMS = [
    ("List active shares", _menu_list),
    ("Revoke a share (by token)", _menu_revoke),
    ("Revoke a share (by path)", _menu_revoke_path),
    ("Edit share security (mode/passkey/expiry)", _menu_edit),
    ("List pending access requests", _menu_requests),
    ("Approve an access request", _menu_approve),
    ("Deny an access request", _menu_deny),
    ("Revoke ALL shares", _menu_revoke_all),
]


def run_interactive_menu():
    """The whole point of this loop is that it keeps control inside this
    script — and only this script — until the operator explicitly asks to
    leave. It never calls sys.exit() on its own path back to the caller,
    and never os.exec's or re-invokes manage.sh itself, so whoever launched
    this process (a shell, or manage.sh's own menu loop) regains control
    normally the moment Exit is chosen, exactly like a plain CLI command
    returning after it's done."""
    while True:
        print("\n=== CloudinatorFTP — Share Management ===")
        for i, (label, _fn) in enumerate(_MENU_ITEMS, start=1):
            print(f"  {i}) {label}")
        print("  0) Exit")

        choice = input("\nChoose an option: ").strip()
        if choice == "0" or choice.lower() in ("q", "quit", "exit"):
            print("Bye.")
            return

        try:
            idx = int(choice) - 1
            if idx < 0:
                raise ValueError
            label, fn = _MENU_ITEMS[idx]
        except (ValueError, IndexError):
            print("Not a valid option — try again.")
            continue

        try:
            fn()
        except KeyboardInterrupt:
            print("\nCancelled.")
        except SystemExit:
            # A cmd_* helper called sys.exit() on a hard failure (e.g. bad
            # revoke-all code) — that's fine, it just ends that one action;
            # swallow it here so the menu loop itself keeps running instead
            # of taking the whole script down with it.
            pass
        except Exception as e:
            print(f"❌ Unexpected error: {e}")

        input("\nPress Enter to continue...")


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Manage CloudinatorFTP public share links from the backend. "
        "Run with no arguments for an interactive menu."
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

    p_edit = sub.add_parser(
        "edit", help="Edit an active share's security settings, by token"
    )
    p_edit.add_argument("token", help="Share token to edit")
    _add_edit_flags(p_edit)
    p_edit.set_defaults(func=cmd_edit)

    p_edit_path = sub.add_parser(
        "edit-path",
        help="Edit an active share's security settings, by file/folder path",
    )
    p_edit_path.add_argument("path", help="File or folder path")
    _add_edit_flags(p_edit_path)
    p_edit_path.set_defaults(func=cmd_edit_path)

    sub.add_parser(
        "requests", help="List pending access requests (approval-gated shares)"
    ).set_defaults(func=cmd_requests)

    p_approve = sub.add_parser("approve", help="Approve a pending access request")
    p_approve.add_argument("request_id", type=int, help="Request ID (see 'requests')")
    p_approve.add_argument(
        "--max-downloads",
        type=int,
        default=1,
        help="How many downloads this grant allows (default: 1)",
    )
    p_approve.set_defaults(func=cmd_approve)

    p_deny = sub.add_parser("deny", help="Deny a pending access request")
    p_deny.add_argument("request_id", type=int, help="Request ID (see 'requests')")
    p_deny.set_defaults(func=cmd_deny)

    args = parser.parse_args()
    if not args.command:
        run_interactive_menu()
        return
    args.func(args)


if __name__ == "__main__":
    main()
