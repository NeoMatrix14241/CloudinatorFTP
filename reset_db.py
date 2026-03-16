#!/usr/bin/env python3
"""
reset_db.py — Wipe and recreate cloudinator.db from scratch
------------------------------------------------------------
Use this if the database is corrupted or you want a clean slate.

    python reset_db.py

Deletes the entire db/ folder and recreates it with default credentials:
  admin / admin123  (readwrite)
  guest / guest123  (readonly)
"""

import os
import shutil
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

_HERE = os.path.dirname(os.path.abspath(__file__))
_DB_DIR = os.path.join(_HERE, "db")


def main():
    print("⚠️  This will DELETE all users and reset the database to defaults.")
    confirm = input("Type 'yes' to continue: ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    # Wipe the db/ folder (removes .db, -wal, -shm and anything else inside)
    if os.path.exists(_DB_DIR):
        shutil.rmtree(_DB_DIR)
        print(f"🗑️  Deleted {_DB_DIR}")

    # Re-importing database triggers _bootstrap() which recreates everything
    # We need to reload if database was already imported in this session
    import importlib
    import database

    importlib.reload(database)

    print("✅ Database recreated with default credentials:")
    print("   👤 admin / admin123  (readwrite)")
    print("   👤 guest / guest123  (readonly)")
    print("⚠️  Change these passwords before exposing to network!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
