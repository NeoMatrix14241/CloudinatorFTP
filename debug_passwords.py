#!/usr/bin/env python3
"""
Debug/test tool for CloudinatorFTP authentication
Usage: python debug_passwords.py
"""

import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from database import db


def test_password(username, password):
    result = db.check_login(username, password)
    status = "✅" if result else "❌"
    print(f"  {status} {username} / {password} → {'SUCCESS' if result else 'FAILED'}")
    return result


def test_all_users():
    users = db.list_users()
    if not users:
        print("❌ No users in database")
        return

    common = [
        "admin",
        "admin123",
        "password",
        "password123",
        "guest",
        "guest123",
        "123456",
        "",
    ]

    for u in users:
        username = u["username"]
        print(f"\n🔍 Testing '{username}' ({u['role']}):")
        for pwd in common:
            test_password(username, pwd)


def test_custom():
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    test_password(username, password)


def show_users():
    users = db.list_users()
    if not users:
        print("❌ No users in database")
        return
    print(f"\n{'Username':<20} {'Role':<12} {'Last Login'}")
    print("-" * 50)
    for u in users:
        last = f"{u['last_login']:.0f}" if u["last_login"] else "never"
        print(f"  {u['username']:<18} {u['role']:<12} {last}")


def reset_defaults():
    confirm = (
        input("Reset admin/guest to default passwords? (yes/no): ").strip().lower()
    )
    if confirm not in ("yes", "y"):
        print("Cancelled")
        return

    db.update_password("admin", "admin123")
    db.update_password("guest", "guest123")
    print("✅ Passwords reset to defaults")
    print("⚠️  Change these before exposing to network!")


def main():
    print("🔐 CloudinatorFTP Auth Debug Tool")
    print("=" * 40)

    while True:
        print("\nOptions:")
        print("1. Show all users")
        print("2. Test common passwords against all users")
        print("3. Test custom username/password")
        print("4. Reset admin + guest to default passwords")
        print("5. Exit")

        choice = input("\nSelect option (1-5): ").strip()

        if choice == "1":
            show_users()
        elif choice == "2":
            test_all_users()
        elif choice == "3":
            test_custom()
        elif choice == "4":
            reset_defaults()
        elif choice == "5":
            print("👋 Goodbye!")
            break
        else:
            print("❌ Invalid option")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
