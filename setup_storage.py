#!/usr/bin/env python3
"""
Interactive storage setup script for CloudinatorFTP.
Configures three independent directories:
  1. Files      — where uploaded files are stored        (ROOT_DIR)
  2. Database   — SQLite DB, encryption key, session secret (DB_DIR)
  3. Cache      — storage_index.json, file_index.json     (CACHE_DIR)

Moving db/ and cache/ outside the server/web root is recommended for
production: a compromised web directory then cannot expose your keys.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import importlib
    import config

    importlib.reload(config)
    from config import (
        detect_platform,
        PRESET_PATHS,
        format_bytes,
        set_preset_path,
        set_custom_storage_path,
    )
    from paths import (
        get_db_dir,
        get_cache_dir,
        set_db_dir,
        set_cache_dir,
        reset_db_dir,
        reset_cache_dir,
        get_all_paths,
    )

    # DB_DIR and CACHE_DIR come from paths directly — not from config —
    # so setup_storage.py works even on an older config.py that doesn't
    # export them yet.
    DB_DIR = get_db_dir()
    CACHE_DIR = get_cache_dir()
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this script from the project directory.")
    sys.exit(1)


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_banner():
    print("=" * 60)
    print("🚀 CLOUDINATOR FTP — STORAGE SETUP")
    print("=" * 60)
    print()


def _get_choice(max_choice):
    while True:
        try:
            raw = input(f"Select option (1-{max_choice}, 0 to cancel): ").strip()
            if raw == "0":
                return 0
            n = int(raw)
            if 1 <= n <= max_choice:
                return n
            print(f"❌ Enter a number between 1 and {max_choice}")
        except ValueError:
            print("❌ Please enter a valid number")
        except KeyboardInterrupt:
            print("\n👋 Cancelled")
            return 0


def _confirm_path(final_path: str, label: str) -> bool:
    """Show the resolved final path and ask user to confirm before saving."""
    print()
    print(f"  📁 {label} will be set to:")
    print(f"     {final_path}")
    print()
    while True:
        try:
            ans = input("  Confirm? (y/n): ").strip().lower()
            if ans in ("y", "yes"):
                return True
            if ans in ("n", "no"):
                print("  ↩️  Cancelled.")
                return False
        except KeyboardInterrupt:
            print("\n👋 Cancelled")
            return False


def _check_path(path):
    if not os.path.exists(path):
        return False, False
    try:
        test = os.path.join(path, ".write_test")
        with open(test, "w") as f:
            f.write("test")
        os.remove(test)
        return True, True
    except Exception:
        return True, False


def _free_space(path):
    try:
        if os.name == "nt":
            import shutil

            _, _, free = shutil.disk_usage(path)
        else:
            st = os.statvfs(path)
            free = st.f_bavail * st.f_frsize
        return format_bytes(free)
    except Exception:
        return "Unknown"


def print_current_config():
    importlib.reload(config)
    paths = get_all_paths()
    server_root = os.path.dirname(os.path.abspath(__file__))

    print("📋 Current Configuration:")
    print()

    rows = [
        ("Files   (ROOT_DIR) ", config.ROOT_DIR, "🗂️ "),
        ("Database (DB_DIR)  ", paths["db_dir"], "🔐"),
        ("Cache   (CACHE_DIR)", paths["cache_dir"], "⚡"),
    ]

    for label, path, icon in rows:
        exists, writable = _check_path(path)
        status = "✅" if writable else ("⚠️ " if exists else "❌ missing")
        inside = (
            " ⚠️  inside server root"
            if os.path.abspath(path).startswith(os.path.abspath(server_root))
            else " ✅ outside server root"
        )
        print(f"  {icon}  {label}")
        print(f"      {status} {path}")
        print(f"         {inside}")
        if exists:
            print(f"         Free space: {_free_space(path)}")
        print()


# ---------------------------------------------------------------------------
# Files (ROOT_DIR) configuration
# ---------------------------------------------------------------------------


def show_preset_options():
    platform_type = detect_platform()
    if platform_type not in PRESET_PATHS:
        print(f"❌ No preset paths available for {platform_type}")
        return []

    presets = PRESET_PATHS[platform_type]
    print(f"📍 Available File Storage Locations for {platform_type.title()}:")
    print("-" * 50)

    options = []
    for i, (key, path) in enumerate(presets.items(), 1):
        try:
            parent = os.path.dirname(path)
            status = (
                "✅"
                if os.path.exists(parent) and os.access(parent, os.W_OK)
                else ("⚠️ " if os.path.exists(parent) else "❌")
            )
        except Exception:
            status = "❌"

        print(f"{i:2d}. {status} {key.replace('_', ' ').title()}")
        print(f"      {path}")
        options.append((key, path))

        descs = {
            "downloads": "Recommended for easy access",
            "documents": "Good for document storage",
            "desktop": "Quick access from desktop",
            "internal": "Android internal storage root",
            "dcim": "Camera/media folder",
            "termux_home": "Termux app directory only",
        }
        if key in descs:
            print(f"      💡 {descs[key]}")
        print()

    return options


def configure_files_path():
    print("\n🗂️  Files Storage Path Configuration")
    print("=" * 50)
    print(f"Current: {config.ROOT_DIR}\n")

    options = show_preset_options()
    if not options:
        _configure_custom_files_path()
        return

    print(f"{len(options) + 1}. 🎯 Enter custom path")
    print(f"{len(options) + 2}. ↩️  Back")
    print()

    choice = _get_choice(len(options) + 2)
    if choice == 0 or choice == len(options) + 2:
        return
    elif choice == len(options) + 1:
        _configure_custom_files_path()
    elif 1 <= choice <= len(options):
        key, path = options[choice - 1]
        if not _confirm_path(path, "Files storage"):
            return
        if set_preset_path(key):
            importlib.reload(config)
            print(f"✅ Files storage set to: {path}")


def _configure_custom_files_path():
    print("\n🎯 Custom Files Path")
    print("Enter the exact path where uploaded files should be stored.")
    try:
        custom = input("Path: ").strip()
        if not custom:
            return
        expanded = os.path.abspath(os.path.expanduser(custom))
        if not _confirm_path(expanded, "Files storage"):
            return
        if set_custom_storage_path(expanded, use_subfolder=False):
            importlib.reload(config)
            print(f"✅ Files storage set to: {expanded}")
    except KeyboardInterrupt:
        print("\n👋 Cancelled")


# ---------------------------------------------------------------------------
# DB directory configuration
# ---------------------------------------------------------------------------


def _db_cache_examples(kind):
    home = os.path.expanduser("~")
    platform_type = detect_platform()
    subfolder = "cloudinator_db" if kind == "db" else "cloudinator_cache"

    if platform_type == "windows":
        appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        return [
            os.path.join(appdata, "CloudinatorFTP", subfolder),
            os.path.join(home, ".cloudinator", subfolder),
        ]
    elif platform_type == "termux":
        return [
            os.path.join(home, ".cloudinator", subfolder),
            f"/data/data/com.termux/files/home/.cloudinator/{subfolder}",
        ]
    else:
        return [
            os.path.join(home, ".cloudinator", subfolder),
            f"/etc/cloudinator/{subfolder}",
            f"/var/lib/cloudinator/{subfolder}",
        ]


def _pick_suggested_path(kind, examples):
    print()
    for i, ex in enumerate(examples, 1):
        exists, writable = _check_path(ex)
        if writable:
            note = "✅ exists & writable"
        elif not exists:
            note = "📁 will be created"
        else:
            note = "❌ not writable"
        print(f"{i}. {ex}  [{note}]")
    print(f"{len(examples) + 1}. ↩️  Back")
    print()
    choice = _get_choice(len(examples) + 1)
    if choice == 0 or choice == len(examples) + 1:
        return
    path = examples[choice - 1]
    label = "Database" if kind == "db" else "Cache"
    if not _confirm_path(path, label):
        return
    if kind == "db":
        set_db_dir(path)
    else:
        set_cache_dir(path)


def _configure_custom_dir(kind):
    label = "Database" if kind == "db" else "Cache"
    subfolder = "db" if kind == "db" else "cache"
    print(f"\n🎯 Custom {label} Directory")
    print(f"   Enter a parent folder — '{subfolder}' will be appended automatically.")
    print(f"   Example: C:\\Server  →  C:\\Server\\{subfolder}")
    try:
        custom = input("Path: ").strip()
        if not custom:
            return
        expanded = os.path.abspath(os.path.expanduser(custom))
        # Preview the final path (mirrors paths.set_db_dir / set_cache_dir logic)
        if os.path.basename(expanded).lower() != subfolder:
            final = os.path.join(expanded, subfolder)
        else:
            final = expanded
        if not _confirm_path(final, label):
            return
        if kind == "db":
            set_db_dir(expanded)
        else:
            set_cache_dir(expanded)
    except KeyboardInterrupt:
        print("\n👋 Cancelled")


def configure_db_path():
    print("\n🔐 Database Directory Configuration")
    print("=" * 50)
    print(f"Current: {get_db_dir()}")
    print()
    print("This directory holds three sensitive files:")
    print("  • cloudinator.db  — SQLite user accounts database")
    print("  • secret.key      — Fernet AES-128 encryption key")
    print("  • session.secret  — Flask session cookie signing key")
    print()
    print("⚠️  SECURITY: Move this OUTSIDE the server root so that")
    print("   a path traversal or misconfigured web server cannot")
    print("   serve these files to an attacker.")
    print()
    print("⚠️  After moving: copy your existing db/ files to the new")
    print("   location BEFORE restarting, or you will lose all accounts.")
    print()

    examples = _db_cache_examples("db")
    print("Suggested secure locations:")
    for ex in examples:
        print(f"  • {ex}")
    print()

    print("1. 📁 Use a suggested location")
    print("2. 🎯 Enter custom path")
    print("3. 🔄 Reset to default  (inside server root — less secure)")
    print("4. ↩️  Back")
    print()

    choice = _get_choice(4)
    if choice == 0 or choice == 4:
        return
    elif choice == 1:
        _pick_suggested_path("db", examples)
    elif choice == 2:
        _configure_custom_dir("db")
    elif choice == 3:
        reset_db_dir()


# ---------------------------------------------------------------------------
# Cache directory configuration
# ---------------------------------------------------------------------------


def configure_cache_path():
    print("\n⚡ Cache Directory Configuration")
    print("=" * 50)
    print(f"Current: {get_cache_dir()}")
    print()
    print("This directory holds two auto-generated index files:")
    print("  • storage_index.json — recursive file/dir counts per folder")
    print("  • file_index.json    — cached directory listings (speeds up browsing)")
    print()
    print("These files are fully rebuilt on next server start if missing.")
    print("Moving cache outside the server root prevents directory-structure")
    print("metadata from leaking via a misconfigured web server.")
    print()

    examples = _db_cache_examples("cache")
    print("Suggested locations:")
    for ex in examples:
        print(f"  • {ex}")
    print()

    print("1. 📁 Use a suggested location")
    print("2. 🎯 Enter custom path")
    print("3. 🔄 Reset to default  (inside server root)")
    print("4. ↩️  Back")
    print()

    choice = _get_choice(4)
    if choice == 0 or choice == 4:
        return
    elif choice == 1:
        _pick_suggested_path("cache", examples)
    elif choice == 2:
        _configure_custom_dir("cache")
    elif choice == 3:
        reset_cache_dir()


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------


def main_menu():
    while True:
        clear_screen()
        print_banner()
        print_current_config()

        print("🔧 Configuration Options:")
        print("1. 🗂️  Configure Files storage path   (ROOT_DIR)")
        print("2. 🔐 Configure Database directory    (DB_DIR)  ← keys & secrets")
        print("3. ⚡ Configure Cache directory       (CACHE_DIR)")
        print("4. 📋 Refresh current settings")
        print("5. ❌ Exit")
        print()

        choice = _get_choice(5)

        if choice == 0 or choice == 5:
            print("👋 Goodbye!")
            break
        elif choice == 1:
            configure_files_path()
            input("\nPress Enter to continue...")
        elif choice == 2:
            configure_db_path()
            input("\nPress Enter to continue...")
        elif choice == 3:
            configure_cache_path()
            input("\nPress Enter to continue...")
        elif choice == 4:
            pass  # loop re-prints print_current_config


def main():
    try:
        print("🚀 CloudinatorFTP Storage Setup")
        print("Configure where files, the database, and the cache are stored.\n")

        if not os.path.exists("config.py"):
            print("❌ Error: config.py not found!")
            print("Run this script from the project directory.")
            return 1

        main_menu()
        print("\n🎯 Setup Complete!")
        return 0

    except KeyboardInterrupt:
        print("\n\n👋 Setup cancelled")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
