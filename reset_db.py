#!/usr/bin/env python3
"""
reset_db.py — Wipe and recreate cloudinator.db from scratch
------------------------------------------------------------
Use this if the database is corrupted or you want a clean slate.

    python reset_db.py

Deletes the entire db/ folder and recreates it with default credentials:
  admin / admin123  (readwrite)
  guest / guest123  (readonly)

These default accounts get full SMB access immediately too (their NT
hash is computed right here from the known "admin123"/"guest123"
plaintext, the same moment they're seeded) — unlike resetting a single
existing user's password later, a full wipe-and-recreate has no
migration gap to worry about.
"""

import os
import shutil
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

_HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    # paths.py is the single source of truth for where db/ actually lives —
    # this is NOT necessarily <script_dir>/db. It's whatever storage_config.json
    # says (db_path), which on a configured server is typically somewhere else
    # entirely, e.g. C:\Server\config\db. Using the wrong path here would
    # silently delete/recreate nothing useful while leaving the real,
    # in-use database completely untouched.
    from paths import get_db_dir

    db_dir = get_db_dir(create=False)

    print("⚠️  This will DELETE all users and reset the database to defaults.")
    print(f"   Target: {db_dir}")
    confirm = input("Type 'yes' to continue: ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    # ── Heads-up about SMB setup state (informational only) ────────────────
    # smb_setup.py's "disable LanmanServer, waiting on a restart" tracking
    # lives in a small file inside db_dir. Under the current model that's
    # just a reminder, not something urgent — the actual OS-level change
    # (LanmanServer disabled) persists fine on its own regardless of this
    # file's existence, so wiping it away here is harmless, just loses the
    # reminder text. No action needed; this is purely informational.
    try:
        import lanman_guard

        state_path = os.path.join(db_dir, ".smb_lanman_state.json")
        pending = lanman_guard.get_pending_state(state_path)
        if pending:
            print()
            print("ℹ️  Note: this will also clear a pending SMB setup reminder")
            print(f"   (you ran smb_setup.py on {pending.get('changed_at', '?')}).")
            print("   If you haven't restarted since then for port 445 to take")
            print("   effect, that's still worth doing — this reset doesn't change it.")
    except ImportError:
        pass  # lanman_guard.py not present — nothing to check, nothing lost

    # Wipe the db/ folder (removes .db, -wal, -shm and anything else inside,
    # including secret.key, session.secret, sftp_host.rsa, webdav.crt/key —
    # all access methods reset together, since they all live in the same place)
    if os.path.exists(db_dir):
        shutil.rmtree(db_dir)
        print(f"🗑️  Deleted {db_dir}")

    # Re-importing database resets its lazy-init state, but database.py is
    # deliberately lazy — nothing actually touches disk just from importing
    # it (see its own module docstring). Without forcing a real operation
    # here, this script would print "recreated" while nothing has actually
    # been created yet, leaving db_dir simply missing until whatever runs
    # next happens to perform the first real query.
    import importlib
    import database

    importlib.reload(database)
    database.db.list_users()  # forces _connect() → _do_bootstrap() to run now

    print("✅ Database recreated with default credentials:")
    print("   👤 admin / admin123  (readwrite)")
    print("   👤 guest / guest123  (readonly)")
    print("⚠️  Change these passwords before exposing to network!")

    if getattr(database, "_SMB_AVAILABLE", False):
        print(
            "📡 SMB: both accounts are ready to use immediately (NT hash computed at seed time)."
        )
    else:
        print("📡 SMB: 'impacket' isn't installed, so no NT hash was computed —")
        print("   SMB login will be unavailable until impacket is installed and")
        print("   each account's password is set again (even to the same value).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
