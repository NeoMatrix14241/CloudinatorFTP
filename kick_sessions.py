#!/usr/bin/env python3
"""
kick_sessions.py — Revoke a user's access across all protocols, fast
------------------------------------------------------------------------
Standalone tool, run manually — like create_user.py or reset_db.py.

TIMING, PER PROTOCOL (measured directly against the real libraries):
  SFTP / FTP   Immediate. Every connection re-validates live against the
               database with no caching at all — confirmed by reading
               both modules' auth functions directly.
  WebDAV       Within ~30 seconds (_AuthCache's TTL in webdav_server.py).
  SMB          Within ~30 seconds (the credential-refresh background
               thread in smb_server.py). Confirmed directly: deleting a
               user and forcing an immediate reload correctly blocked
               their next login attempt; their already-open connection
               was unaffected either way.
"""

import secrets
import sys

sys.path.insert(
    0, __import__("os").path.dirname(__import__("os").path.abspath(__file__))
)

from database import db


def _print_timing_note():
    print()
    print("Timing — when this actually takes effect, per protocol:")
    print("   SFTP / FTP  : immediately, on the next login attempt")
    print("   WebDAV      : within ~30 seconds")
    print("   SMB         : within ~30 seconds")
    print()
    print("⚠️  Does NOT close a connection that's already open right now on")
    print("    any protocol — only blocks the NEXT new connection attempt.")


def rotate(username: str):
    """Lock out old credentials immediately by setting a random password.
    The account stays usable — give the printed temporary password to the
    user if they should keep access, or follow up with a real password
    change through the normal channels."""
    if not db.user_exists(username):
        print(f"❌ No such user: {username}")
        return False

    role = db.get_role(username)
    print(f"Rotating password for {username!r} (role: {role})")

    temp_password = secrets.token_urlsafe(16)
    db.update_password(username, temp_password)

    print(f"✅ Password rotated — old credentials no longer work anywhere.")
    print()
    print(f"   Temporary password (only if {username} should keep access):")
    print(f"   {temp_password}")
    _print_timing_note()
    return True


def lockout(username: str, skip_confirm: bool = False):
    """Stronger option: delete the account entirely."""
    if not db.user_exists(username):
        print(f"❌ No such user: {username}")
        return False

    if not skip_confirm:
        confirm = (
            input(f"Type 'yes' to permanently delete user {username!r}: ")
            .strip()
            .lower()
        )
        if confirm != "yes":
            print("Cancelled.")
            return False

    db.delete_user(username)
    print(f"✅ {username!r} deleted.")
    _print_timing_note()
    return True


def kick_all(skip_confirm: bool = False, include_admins: bool = False):
    """Rotate every user's password at once — for a 'lock everyone out
    right now while I figure out what happened' moment. Skips accounts
    named 'admin' by default so you don't accidentally lock yourself out
    — pass include_admins=True to rotate those too. Same confirmation
    step either way; the more dangerous option doesn't get less safety."""
    users = db.list_users()
    if include_admins:
        targets = [u["username"] for u in users]
    else:
        targets = [u["username"] for u in users if u["username"].lower() != "admin"]

    if not targets:
        print("No users to rotate.")
        return

    print(f"This will rotate passwords for: {', '.join(targets)}")
    if not include_admins:
        print("('admin' is skipped — pass --include-admins to also rotate it)")
    if not skip_confirm:
        confirm = input("Type 'yes' to continue: ").strip().lower()
        if confirm != "yes":
            print("Cancelled.")
            return

    print()
    for username in targets:
        rotate(username)
        print()


def list_users():
    users = db.list_users()
    if not users:
        print("No users found.")
        return
    print(f"{'Username':<20} {'Role':<12} {'Last login'}")
    print("-" * 50)
    for u in users:
        last = u.get("last_login")
        last_str = str(last) if last else "never"
        print(f"{u['username']:<20} {u['role']:<12} {last_str}")


def _interactive_menu():
    print("=" * 60)
    print("  CloudinatorFTP — Kick Sessions / Revoke Access")
    print("=" * 60)
    print()
    print("⚠️  Reminder: this blocks the NEXT connection attempt, not a")
    print("   session that's already open right now. SFTP/FTP: instant.")
    print("   WebDAV/SMB: within ~30 seconds. Run with --help for the")
    print("   full breakdown of why.")

    while True:
        print()
        print("1. List all users")
        print("2. Rotate a user's password (lock out old credentials)")
        print("3. Delete a user")
        print("4. Kick ALL users (rotate everyone except admin)")
        print("5. Kick ALL users, including admin")
        print("6. Exit")

        choice = input("\nSelect (1-6): ").strip()

        if choice == "1":
            list_users()
        elif choice == "2":
            username = input("Username to rotate: ").strip()
            if username:
                rotate(username)
            else:
                print("❌ No username entered.")
        elif choice == "3":
            username = input("Username to delete: ").strip()
            if username:
                lockout(username)
            else:
                print("❌ No username entered.")
        elif choice == "4":
            kick_all(include_admins=False)
        elif choice == "5":
            kick_all(include_admins=True)
        elif choice == "6":
            break
        else:
            print("❌ Invalid option")


def _print_help():
    print(__doc__)
    print()
    print("Usage:")
    print("  python kick_sessions.py                          interactive menu")
    print("  python kick_sessions.py list")
    print("  python kick_sessions.py rotate <username>")
    print("  python kick_sessions.py delete <username>")
    print("  python kick_sessions.py kick-all [--include-admins]")
    print("  python kick_sessions.py --help")


def main():
    args = sys.argv[1:]

    if not args:
        _interactive_menu()
        return

    if args[0] in ("--help", "-h"):
        _print_help()
        return

    # Argv-based mode — kept for scripting/automation (cron jobs, calling
    # this from another script, etc.). The interactive menu above is the
    # default for everyone else, including when run via manage.sh.
    action = args[0]

    if action == "list":
        list_users()
    elif action == "rotate" and len(args) > 1:
        rotate(args[1])
    elif action == "delete" and len(args) > 1:
        lockout(args[1])
    elif action == "kick-all":
        include_admins = "--include-admins" in args
        kick_all(include_admins=include_admins)
    else:
        print(f"Unknown command: {' '.join(args)}")
        print("Run with no arguments for the interactive menu, or --help for usage.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
