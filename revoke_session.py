#!/usr/bin/env python3
"""
revoke_session.py — Invalidate all active sessions
----------------------------------------------------
Rotates the server token stored in cloudinator.db.
Every logged-in client's session cookie will fail the token check
on their next poll (within 5 seconds with default settings).

Usage:
    python revoke_session.py
"""

import os
import sys

# Ensure we run from the project directory so database.py is importable
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from database import db


def main():
    print("🔒 Revoking all active sessions...")
    new_token = db.rotate_server_token()
    print(f"✅ Done. New token: {new_token[:8]}...")
    print("   All connected clients will be redirected to /login within 5 seconds.")


if __name__ == "__main__":
    main()
