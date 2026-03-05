#!/usr/bin/env python3
"""
User management for CloudinatorFTP
Usage: python create_user.py
"""

import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from database import db


def list_users():
    users = db.list_users()
    if not users:
        print("❌ No users exist")
        return
    print("\n📋 Current Users:")
    print("-" * 40)
    for u in users:
        last = f", last login: {u['last_login']:.0f}" if u['last_login'] else ""
        print(f"  👤 {u['username']} ({u['role']}{last})")


def add_user():
    username = input("Enter username: ").strip()
    if not username:
        print("❌ Username cannot be empty")
        return

    password = input("Enter password: ").strip()
    if not password:
        print("❌ Password cannot be empty")
        return

    print("\nRole options:")
    print("  readwrite - Can upload, download, create folders, delete")
    print("  readonly  - Can only download files")
    role = input("Enter role (readwrite/readonly): ").strip().lower()

    if role not in ('readwrite', 'readonly'):
        print("❌ Invalid role")
        return

    if db.add_user(username, password, role):
        print(f"✅ User '{username}' added with role '{role}'")
    else:
        print(f"❌ User '{username}' already exists")


def update_password():
    username = input("Enter username: ").strip()
    if not db.user_exists(username):
        print(f"❌ User '{username}' not found")
        return

    password = input("Enter new password: ").strip()
    if not password:
        print("❌ Password cannot be empty")
        return

    if db.update_password(username, password):
        print(f"✅ Password updated for '{username}'")


def update_role():
    username = input("Enter username: ").strip()
    if not db.user_exists(username):
        print(f"❌ User '{username}' not found")
        return

    role = input("Enter new role (readwrite/readonly): ").strip().lower()
    if role not in ('readwrite', 'readonly'):
        print("❌ Invalid role")
        return

    if db.update_role(username, role):
        print(f"✅ Role updated for '{username}' → {role}")


def delete_user():
    username = input("Enter username to delete: ").strip()
    if not db.user_exists(username):
        print(f"❌ User '{username}' not found")
        return

    confirm = input(f"Delete '{username}'? (yes/no): ").strip().lower()
    if confirm in ('yes', 'y'):
        if db.delete_user(username):
            print(f"✅ User '{username}' deleted")
    else:
        print("Cancelled")


def main():
    print("🔐 CloudinatorFTP User Management")
    print("=" * 40)

    while True:
        print("\nOptions:")
        print("1. List users")
        print("2. Add user")
        print("3. Update password")
        print("4. Update role")
        print("5. Delete user")
        print("6. Exit")

        choice = input("\nSelect option (1-6): ").strip()

        if choice == '1':
            list_users()
        elif choice == '2':
            add_user()
        elif choice == '3':
            update_password()
        elif choice == '4':
            update_role()
        elif choice == '5':
            delete_user()
        elif choice == '6':
            print("👋 Goodbye!")
            break
        else:
            print("❌ Invalid option")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")