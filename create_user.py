#!/usr/bin/env python3
"""
User management CLI for CloudinatorFTP.
Uses the same SQLite + Fernet-encrypted database as the server.
Users created here work immediately for login — no server restart needed.

Run: python create_user.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Ensure db/ directory exists at configured path before database.py writes to it
from paths import ensure_dirs

ensure_dirs()

from database import db

DEFAULT_CREDENTIALS = [("admin", "admin123"), ("guest", "guest123")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _warn_defaults():
    """Warn if any default credentials are still active."""
    active = [u for u, p in DEFAULT_CREDENTIALS if db.check_login(u, p)]
    if active:
        print()
        print("⚠️  WARNING: Default credentials still active for:", ", ".join(active))
        print("   Change or delete these before exposing the server to a network!")


def _input_password(prompt="Enter password: ") -> str:
    """Read password — hides input if possible."""
    try:
        import getpass

        return getpass.getpass(prompt)
    except Exception:
        return input(prompt).strip()


def _confirm(prompt: str) -> bool:
    ans = input(f"{prompt} (yes/no): ").strip().lower()
    return ans in ("yes", "y")


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def list_users():
    users = db.list_users()
    if not users:
        print("  No users found.")
        return
    print()
    print(f"  {'Username':<20} {'Role':<12} {'Last Login'}")
    print("  " + "-" * 50)
    for u in users:
        import datetime

        last = (
            datetime.datetime.fromtimestamp(u["last_login"]).strftime("%Y-%m-%d %H:%M")
            if u.get("last_login")
            else "Never"
        )
        flag = (
            " ⚠️  default password!"
            if any(
                u["username"] == un and db.check_login(un, pw)
                for un, pw in DEFAULT_CREDENTIALS
            )
            else ""
        )
        print(f"  {u['username']:<20} {u['role']:<12} {last}{flag}")
    print()


def add_user():
    print("\n➕ Add New User")
    username = input("  Username: ").strip()
    if not username:
        print("  ❌ Username cannot be empty.")
        return
    if db.user_exists(username):
        print(f"  ❌ User '{username}' already exists.")
        return

    password = _input_password("  Password: ")
    if not password:
        print("  ❌ Password cannot be empty.")
        return
    confirm = _input_password("  Confirm password: ")
    if password != confirm:
        print("  ❌ Passwords do not match.")
        return

    print("  Roles:  readwrite — upload, download, delete, create folders")
    print("          readonly  — download only")
    role = input("  Role (readwrite/readonly): ").strip().lower()
    if role not in ("readwrite", "readonly"):
        print("  ❌ Invalid role.")
        return

    if db.add_user(username, password, role):
        print(f"  ✅ User '{username}' added with role '{role}'.")
    else:
        print(f"  ❌ Failed to add user '{username}'.")


def change_password():
    print("\n🔑 Change Password")
    username = input("  Username: ").strip()
    if not db.user_exists(username):
        print(f"  ❌ User '{username}' not found.")
        return

    password = _input_password("  New password: ")
    if not password:
        print("  ❌ Password cannot be empty.")
        return
    confirm = _input_password("  Confirm new password: ")
    if password != confirm:
        print("  ❌ Passwords do not match.")
        return

    if db.update_password(username, password):
        print(f"  ✅ Password updated for '{username}'.")
    else:
        print(f"  ❌ Failed to update password.")


def change_role():
    print("\n🔄 Change Role")
    username = input("  Username: ").strip()
    if not db.user_exists(username):
        print(f"  ❌ User '{username}' not found.")
        return

    current = db.get_role(username)
    print(f"  Current role: {current}")
    role = input("  New role (readwrite/readonly): ").strip().lower()
    if role not in ("readwrite", "readonly"):
        print("  ❌ Invalid role.")
        return
    if role == current:
        print("  ℹ️  Role unchanged.")
        return

    if db.update_role(username, role):
        print(f"  ✅ Role for '{username}' changed to '{role}'.")
    else:
        print(f"  ❌ Failed to update role.")


def delete_user():
    print("\n🗑️  Delete User")
    username = input("  Username: ").strip()
    if not db.user_exists(username):
        print(f"  ❌ User '{username}' not found.")
        return

    role = db.get_role(username)
    print(f"  About to delete: {username} ({role})")
    if not _confirm("  Are you sure?"):
        print("  ↩️  Cancelled.")
        return

    if db.delete_user(username):
        print(f"  ✅ User '{username}' deleted.")
    else:
        print(f"  ❌ Failed to delete user.")


def delete_default_users():
    """One-shot: delete admin and guest if they still have default passwords."""
    print("\n🧹 Remove Default Users")
    removed = []
    for username, password in DEFAULT_CREDENTIALS:
        if db.user_exists(username):
            if db.check_login(username, password):
                if db.delete_user(username):
                    removed.append(username)
            else:
                print(
                    f"  ℹ️  '{username}' exists but password was already changed — skipping."
                )
        else:
            print(f"  ℹ️  '{username}' does not exist — skipping.")

    if removed:
        print(f"  ✅ Removed default account(s): {', '.join(removed)}")
    else:
        print("  ✅ No default-password accounts to remove.")


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------


def main():
    print("=" * 50)
    print("🔐 CloudinatorFTP — User Management")
    print("=" * 50)

    _warn_defaults()

    while True:
        print("\nOptions:")
        print("  1. List users")
        print("  2. Add user")
        print("  3. Change password")
        print("  4. Change role")
        print("  5. Delete user")
        print("  6. Remove default users (admin/guest with default passwords)")
        print("  7. Exit")

        choice = input("\nSelect (1-7): ").strip()

        if choice == "1":
            list_users()
        elif choice == "2":
            add_user()
        elif choice == "3":
            change_password()
        elif choice == "4":
            change_role()
        elif choice == "5":
            delete_user()
        elif choice == "6":
            delete_default_users()
        elif choice == "7":
            print("👋 Goodbye!")
            break
        else:
            print("❌ Invalid option.")

        _warn_defaults()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
