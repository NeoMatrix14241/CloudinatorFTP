import os
import platform
import subprocess
import json
import time

# Server configuration
PORT = 5000
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB adjustable chunk size
ENABLE_CHUNKED_UPLOADS = True
HOST = "0.0.0.0"  # Listen on all interfaces
MAX_CONTENT_LENGTH = 16 * 1024 * 1024 * 1024  # 16GB max file size
ALLOWED_EXTENSIONS = None  # None = allow all file types
PERMANENT_SESSION_LIFETIME = 3600  # 1 hour session timeout

# HLS streaming configuration
# Files smaller than HLS_MIN_SIZE skip HLS for web-native formats (play raw instead)
HLS_MIN_SIZE = 50 * 1024 * 1024  # 50 MB default
# These formats always get HLS regardless of size — browser can't play them raw
HLS_FORCE_FORMATS = {"mkv", "avi", "wmv", "flv", "mpg", "mpeg", "m2ts", "mts", "3gp", "ogv"}

# Feature toggles — both default to True (enabled).
# When True and the tool IS installed     → full functionality (HLS / WebP conversion).
# When True and the tool is NOT installed → existing graceful fallback (raw playback /
#                                           raw image serving) — no change in behaviour.
# When False                              → intentionally disabled regardless of whether
#                                           the binary is present; raw fallback is used
#                                           and a "requires processing" notice is shown
#                                           for formats that cannot be displayed raw.
ENABLE_FFMPEG = True    # False → skip HLS transcoding entirely, use raw playback only
ENABLE_LIBVIPS = True   # False → skip image conversion entirely, use raw serving only

# Image preview / WebP compression configuration
# Native images (jpg/png/gif/etc.) smaller than this are served raw with no conversion.
# Above this threshold they are compressed to lossy WebP to save bandwidth.
IMG_COMPRESS_MIN_SIZE = 1 * 1024 * 1024  # 1 MB default
# Quality used for lossy WebP encoding (1-100). Lower = smaller file, more artefacts.
IMG_WEBP_QUALITY = 50  # default

# Path exports — create=False so importing config never creates directories.
from paths import (
    get_db_dir,
    get_cache_dir,
    get_hls_cache_dir,
    get_img_cache_dir,
    set_db_dir,
    set_cache_dir,
    set_hls_cache_dir,
    set_img_cache_dir,
    reset_db_dir,
    reset_cache_dir,
    reset_hls_cache_dir,
    reset_img_cache_dir,
)

DB_DIR = get_db_dir(create=False)
CACHE_DIR = get_cache_dir(create=False)
HLS_CACHE_DIR = get_hls_cache_dir(create=False)
IMG_CACHE_DIR = get_img_cache_dir(create=False)


def detect_platform():
    """Detect the current platform and return appropriate info"""
    system = platform.system().lower()

    # Check if running in Termux
    if "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux"):
        return "termux"
    elif system == "linux":
        return "linux"
    elif system == "windows":
        return "windows"
    elif system == "darwin":
        return "macos"
    else:
        return "unknown"


def get_windows_documents_path():
    """Get the proper Windows Documents folder path"""
    try:
        # Try using the USERPROFILE environment variable first
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            documents_path = os.path.join(userprofile, "Documents")
            if os.path.exists(documents_path):
                return documents_path

        # Try using Windows registry
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            ) as key:
                documents_path = winreg.QueryValueEx(key, "Personal")[0]
                if os.path.exists(documents_path):
                    return documents_path
        except (ImportError, OSError, FileNotFoundError):
            pass

        # Fallback methods
        fallbacks = [
            os.path.join(os.path.expanduser("~"), "Documents"),
            os.path.join(
                os.environ.get("HOMEDRIVE", "C:"),
                os.environ.get(
                    "HOMEPATH", "\\Users\\" + os.environ.get("USERNAME", "User")
                ),
                "Documents",
            ),
            os.path.expanduser("~"),
        ]

        for path in fallbacks:
            if os.path.exists(path):
                return path

    except Exception as e:
        print(f"Error detecting Windows Documents folder: {e}")

    # Final fallback
    return os.getcwd()


def get_accessible_storage_path():
    """Get an accessible storage path based on the platform"""
    platform_type = detect_platform()

    if platform_type == "termux":
        # Check if termux-setup-storage has been run
        shared_storage = "/storage/emulated/0"  # Internal storage root
        downloads = os.path.join(shared_storage, "Download")
        documents = os.path.join(shared_storage, "Documents")

        # Try to find the best accessible location
        if os.path.exists(downloads) and os.access(downloads, os.W_OK):
            return os.path.join(downloads, "CloudinatorFTP")
        elif os.path.exists(documents) and os.access(documents, os.W_OK):
            return os.path.join(documents, "CloudinatorFTP")
        elif os.path.exists(shared_storage) and os.access(shared_storage, os.W_OK):
            return os.path.join(shared_storage, "CloudinatorFTP")
        else:
            # Fallback to termux home if shared storage not accessible
            print(
                "⚠️  Warning: Shared storage not accessible. Files will be saved to Termux directory."
            )
            print(
                "   Run 'termux-setup-storage' and grant permissions to save to internal storage."
            )
            return os.path.join(os.path.expanduser("~"), "uploads")

    elif platform_type == "linux":
        # Linux: try user's home directory
        home = os.path.expanduser("~")
        return os.path.join(home, "CloudinatorFTP")

    elif platform_type == "windows":
        # Windows: use improved Documents folder detection
        documents_path = get_windows_documents_path()
        return os.path.join(documents_path, "CloudinatorFTP")

    elif platform_type == "macos":
        # macOS: use user's home directory
        home = os.path.expanduser("~")
        return os.path.join(home, "CloudinatorFTP")

    else:
        # Unknown platform: use current directory
        return os.path.join(os.getcwd(), "uploads")


def setup_storage_directory():
    """Create and verify the storage directory"""
    custom_path = None

    # 1. Check environment variable
    if "CLOUDINATOR_FTP_ROOT" in os.environ:
        custom_path = os.environ["CLOUDINATOR_FTP_ROOT"]
        print(f"🔧 Using environment variable path: {custom_path}")

    # 2. Read from storage_config.json via paths._load() — same file/path
    #    that set_db_dir/set_cache_dir write to, so they're always in sync.
    else:
        from paths import _load as _paths_load

        cfg = _paths_load()
        custom_path = cfg.get("storage_path")
        if custom_path:
            print(f"📋 Using saved configuration: {custom_path}")

    # 3. Use custom path if provided, otherwise auto-detect
    storage_path = custom_path if custom_path else get_accessible_storage_path()
    platform_type = detect_platform()

    try:
        os.makedirs(storage_path, exist_ok=True)

        # Test write permissions
        test_file = os.path.join(storage_path, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)

        print(f"✅ Storage directory ready: {storage_path}")

        # Platform-specific feedback
        if platform_type == "termux":
            if "/storage/emulated/0" in storage_path:
                print("✅ Files will be accessible from Android file managers")
                if "Download" in storage_path:
                    print("📁 Android location: Files app → Downloads → CloudinatorFTP")
                elif "Documents" in storage_path:
                    print("📁 Android location: Files app → Documents → CloudinatorFTP")
                else:
                    print(
                        "📁 Android location: Files app → Internal Storage → CloudinatorFTP"
                    )
            else:
                print("⚠️  Files will only be accessible within Termux")
                print("   Run 'termux-setup-storage' for broader access")

        elif platform_type == "windows":
            print(f"📁 Windows location: {storage_path}")
            print("💡 Access via File Explorer or any file manager")

        elif platform_type == "linux":
            print(f"📁 Linux location: {storage_path}")
            print("💡 Access via file manager or terminal")

        elif platform_type == "macos":
            print(f"📁 macOS location: {storage_path}")
            print("💡 Access via Finder")

        return storage_path

    except PermissionError:
        print(f"❌ Permission denied: {storage_path}")
        # Fallback to current directory
        fallback = os.path.join(os.getcwd(), "uploads")
        os.makedirs(fallback, exist_ok=True)
        print(f"📁 Using fallback directory: {fallback}")
        return fallback
    except Exception as e:
        print(f"❌ Error creating storage directory: {e}")
        # Fallback to current directory
        fallback = os.path.join(os.getcwd(), "uploads")
        os.makedirs(fallback, exist_ok=True)
        print(f"📁 Using fallback directory: {fallback}")
        return fallback


# Set ROOT_DIR based on platform detection
ROOT_DIR = setup_storage_directory()


def print_platform_info():
    """Print information about the current platform and storage"""
    platform_type = detect_platform()

    print(f"🖥️  Platform: {platform_type.title()}")
    print(f"📁 Storage location: {os.path.abspath(ROOT_DIR)}")

    if platform_type == "termux":
        shared_storage = "/storage/emulated/0"
        if ROOT_DIR.startswith(shared_storage):
            print("✅ Files accessible from Android file managers")
        else:
            print("⚠️  Files only accessible within Termux")
            print("💡 Tip: Run 'termux-setup-storage' for broader access")

    elif platform_type == "windows":
        print("💡 Open File Explorer and navigate to the storage location above")

    elif platform_type == "linux":
        print('💡 Use your file manager or: cd "' + ROOT_DIR + '"')

    elif platform_type == "macos":
        print("💡 Open Finder and navigate to the storage location above")

    # Check available space
    try:
        if platform_type == "windows":
            import shutil

            total, used, free = shutil.disk_usage(ROOT_DIR)
        else:
            stat = os.statvfs(ROOT_DIR)
            free = stat.f_bavail * stat.f_frsize
            total = stat.f_blocks * stat.f_frsize
            used = total - free

        print(f"💾 Available space: {format_bytes(free)}")

    except Exception:
        print("💾 Available space: Unknown")


def format_bytes(bytes):
    """Format bytes into human readable format"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} PB"


def set_custom_storage_path(custom_path, use_subfolder=True):
    """
    Set the storage path. If use_subfolder is True, append 'CloudinatorFTP' to the path.
    If False, use the path as-is (for custom user input).
    """
    global ROOT_DIR

    try:
        # Expand user paths like ~/Documents
        expanded_path = os.path.expanduser(custom_path)

        if use_subfolder:
            # Always append CloudinatorFTP for preset paths
            final_path = os.path.join(expanded_path, "CloudinatorFTP")
        else:
            # Use the exact custom path
            final_path = expanded_path

        # Create directory
        os.makedirs(expanded_path, exist_ok=True)

        # Test write permissions
        test_file = os.path.join(expanded_path, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)

        # Save via paths._save() — merge-write so db_path/cache_path
        # already in storage_config.json are never overwritten.
        try:
            from paths import _save

            _save(
                {
                    "storage_path": expanded_path,
                    "platform": detect_platform(),
                    "set_at": (
                        str(os.path.getctime(expanded_path))
                        if os.path.exists(expanded_path)
                        else None
                    ),
                }
            )
            print("📋 Saved storage configuration")
        except Exception as e:
            print(f"⚠️  Could not save config: {e}")

        ROOT_DIR = expanded_path
        print(f"✅ Custom storage path set: {ROOT_DIR}")
        return True

    except Exception as e:
        print(f"❌ Cannot use custom path {custom_path}: {e}")
        return False


# Custom storage paths for quick setup
PRESET_PATHS = {
    "termux": {
        "downloads": "/storage/emulated/0/Download/CloudinatorFTP",
        "documents": "/storage/emulated/0/Documents/CloudinatorFTP",
        "internal": "/storage/emulated/0/CloudinatorFTP",
        "dcim": "/storage/emulated/0/DCIM/CloudinatorFTP",
        "termux_home": os.path.join(os.path.expanduser("~"), "uploads"),
    },
    "linux": {
        "home": os.path.join(os.path.expanduser("~"), "CloudinatorFTP"),
        "desktop": os.path.join(os.path.expanduser("~"), "Desktop", "CloudinatorFTP"),
        "documents": os.path.join(
            os.path.expanduser("~"), "Documents", "CloudinatorFTP"
        ),
        "downloads": os.path.join(
            os.path.expanduser("~"), "Downloads", "CloudinatorFTP"
        ),
    },
    "windows": {
        "documents": os.path.join(get_windows_documents_path(), "CloudinatorFTP"),
        "desktop": os.path.join(os.path.expanduser("~"), "Desktop", "CloudinatorFTP"),
        "downloads": os.path.join(
            os.path.expanduser("~"), "Downloads", "CloudinatorFTP"
        ),
        "userprofile": os.path.join(os.path.expanduser("~"), "CloudinatorFTP"),
    },
    "macos": {
        "documents": os.path.join(
            os.path.expanduser("~"), "Documents", "CloudinatorFTP"
        ),
        "desktop": os.path.join(os.path.expanduser("~"), "Desktop", "CloudinatorFTP"),
        "downloads": os.path.join(
            os.path.expanduser("~"), "Downloads", "CloudinatorFTP"
        ),
    },
}


def set_preset_path(preset_key):
    """Set storage path using a preset key"""
    platform_type = detect_platform()

    if platform_type in PRESET_PATHS and preset_key in PRESET_PATHS[platform_type]:
        preset_path = PRESET_PATHS[platform_type][preset_key]
        return set_custom_storage_path(preset_path)
    else:
        print(f"❌ Invalid preset '{preset_key}' for platform '{platform_type}'")
        available = list(PRESET_PATHS.get(platform_type, {}).keys())
        if available:
            print(f"Available presets: {', '.join(available)}")
        return False


def list_available_presets():
    """List all available preset paths for the current platform"""
    platform_type = detect_platform()

    print(f"\n📍 Available preset locations for {platform_type.title()}:")
    print("-" * 50)

    if platform_type in PRESET_PATHS:
        for key, path in PRESET_PATHS[platform_type].items():
            try:
                parent = os.path.dirname(path)
                accessible = (
                    "✅"
                    if os.path.exists(parent) and os.access(parent, os.W_OK)
                    else "❌"
                )
                print(f"{accessible} {key}: {path}")
            except Exception:
                print(f"❌ {key}: {path}")
    else:
        print(f"❌ No presets available for {platform_type}")

    print(f"\n🔧 Current location: {ROOT_DIR}")
    print(f"\n💡 To change storage location:")
    print(
        f"   Python: from config import set_preset_path; set_preset_path('documents')"
    )
    print(f"   Env Var: set CLOUDINATOR_FTP_ROOT=C:\\path\\to\\your\\folder")
    print(
        f"   Direct: from config import set_custom_storage_path; set_custom_storage_path('C:\\path\\to\\folder')"
    )


def configure_server_settings():
    """Interactive server configuration"""
    global PORT, CHUNK_SIZE, ENABLE_CHUNKED_UPLOADS, SESSION_SECRET
    global HOST, MAX_CONTENT_LENGTH, PERMANENT_SESSION_LIFETIME
    global ENABLE_FFMPEG, ENABLE_LIBVIPS

    print("\n🔧 Server Configuration")
    print("=" * 50)

    while True:
        print(f"\nCurrent Settings:")
        print(f"1. Port: {PORT}")
        print(f"2. Chunk Size: {format_bytes(CHUNK_SIZE)}")
        print(
            f"3. Chunked Uploads: {'Enabled' if ENABLE_CHUNKED_UPLOADS else 'Disabled'}"
        )
        print(f"4. Max File Size: {format_bytes(MAX_CONTENT_LENGTH)}")
        print(f"5. Session Timeout: {PERMANENT_SESSION_LIFETIME//60} minutes")
        print(f"6. Host Binding: {HOST}")
        print("7. Generate New Session Secret")
        print(f"8. HLS Settings    (min size: {format_bytes(HLS_MIN_SIZE) if HLS_MIN_SIZE else 'always'})")
        print(f"9. Image Settings  (compress >{format_bytes(IMG_COMPRESS_MIN_SIZE)}, WebP Q={IMG_WEBP_QUALITY})")
        print(f"11. ffmpeg (HLS):  {'✅ Enabled' if ENABLE_FFMPEG else '🚫 Disabled'}")
        print(f"12. libvips (img): {'✅ Enabled' if ENABLE_LIBVIPS else '🚫 Disabled'}")
        print("10. Save & Exit")
        print("0. Exit Without Saving")

        choice = input("\nSelect option to configure (0-12): ").strip()

        if choice == "1":
            configure_port()
        elif choice == "2":
            configure_chunk_size()
        elif choice == "3":
            configure_chunked_uploads()
        elif choice == "4":
            configure_max_file_size()
        elif choice == "5":
            configure_session_timeout()
        elif choice == "6":
            configure_host_binding()
        elif choice == "7":
            generate_session_secret()
        elif choice == "8":
            configure_hls_settings()
        elif choice == "9":
            configure_image_settings()
        elif choice == "11":
            _toggle_ffmpeg()
        elif choice == "12":
            _toggle_libvips()
        elif choice == "10":
            save_server_config()
            print("✅ Server configuration saved!")
            break
        elif choice == "0":
            print("❌ Configuration cancelled")
            break
        else:
            print("❌ Invalid option. Please choose 0-12.")


def configure_port():
    """Configure server port"""
    global PORT
    print(f"\nCurrent port: {PORT}")
    print("Common ports: 80 (HTTP), 8080 (Alt HTTP), 5000 (Flask default)")
    print("Note: Ports below 1024 may require root privileges")

    while True:
        try:
            new_port = input(
                "Enter new port (1-65535) or press Enter to keep current: "
            ).strip()
            if not new_port:
                break
            port_num = int(new_port)
            if 1 <= port_num <= 65535:
                PORT = port_num
                print(f"✅ Port set to {PORT}")
                break
            else:
                print("❌ Port must be between 1 and 65535")
        except ValueError:
            print("❌ Please enter a valid number")


def configure_chunk_size():
    """Configure upload chunk size"""
    global CHUNK_SIZE
    print(f"\nCurrent chunk size: {format_bytes(CHUNK_SIZE)}")
    print("Recommended: 1MB-50MB (larger = faster uploads, more memory usage)")

    size_options = {
        "1": 1 * 1024 * 1024,  # 1MB
        "2": 5 * 1024 * 1024,  # 5MB
        "3": 10 * 1024 * 1024,  # 10MB
        "4": 25 * 1024 * 1024,  # 25MB
        "5": 50 * 1024 * 1024,  # 50MB
        "6": 100 * 1024 * 1024,  # 100MB
    }

    print("\nPreset options:")
    for key, value in size_options.items():
        print(f"{key}. {format_bytes(value)}")
    print("7. Custom size")
    print("8. Keep current")

    choice = input("\nSelect option (1-8): ").strip()

    if choice in size_options:
        CHUNK_SIZE = size_options[choice]
        print(f"✅ Chunk size set to {format_bytes(CHUNK_SIZE)}")
    elif choice == "7":
        configure_custom_chunk_size()
    elif choice == "8":
        print("✅ Keeping current chunk size")
    else:
        print("❌ Invalid option")


def configure_custom_chunk_size():
    """Configure custom chunk size"""
    global CHUNK_SIZE
    while True:
        try:
            size_input = input("Enter chunk size in MB (e.g., 15 for 15MB): ").strip()
            if not size_input:
                break
            size_mb = float(size_input)
            if 0.1 <= size_mb <= 1024:  # 0.1MB to 1GB
                CHUNK_SIZE = int(size_mb * 1024 * 1024)
                print(f"✅ Chunk size set to {format_bytes(CHUNK_SIZE)}")
                break
            else:
                print("❌ Size must be between 0.1MB and 1024MB")
        except ValueError:
            print("❌ Please enter a valid number")


def configure_chunked_uploads():
    """Toggle chunked uploads"""
    global ENABLE_CHUNKED_UPLOADS
    current = "Enabled" if ENABLE_CHUNKED_UPLOADS else "Disabled"
    print(f"\nChunked uploads currently: {current}")
    print(
        "Chunked uploads allow resumable uploads and better memory usage for large files"
    )

    choice = input("Enable chunked uploads? (y/n): ").strip().lower()
    if choice in ["y", "yes"]:
        ENABLE_CHUNKED_UPLOADS = True
        print("✅ Chunked uploads enabled")
    elif choice in ["n", "no"]:
        ENABLE_CHUNKED_UPLOADS = False
        print("✅ Chunked uploads disabled")
    else:
        print("✅ Keeping current setting")


def configure_max_file_size():
    """Configure maximum file size"""
    global MAX_CONTENT_LENGTH
    print(f"\nCurrent max file size: {format_bytes(MAX_CONTENT_LENGTH)}")

    size_options = {
        "1": 1 * 1024 * 1024 * 1024,  # 1GB
        "2": 4 * 1024 * 1024 * 1024,  # 4GB
        "3": 8 * 1024 * 1024 * 1024,  # 8GB
        "4": 16 * 1024 * 1024 * 1024,  # 16GB
        "5": 32 * 1024 * 1024 * 1024,  # 32GB
        "6": 64 * 1024 * 1024 * 1024,  # 64GB
    }

    print("\nPreset options:")
    for key, value in size_options.items():
        print(f"{key}. {format_bytes(value)}")
    print("7. Custom size")
    print("8. Keep current")

    choice = input("\nSelect option (1-8): ").strip()

    if choice in size_options:
        MAX_CONTENT_LENGTH = size_options[choice]
        print(f"✅ Max file size set to {format_bytes(MAX_CONTENT_LENGTH)}")
    elif choice == "7":
        configure_custom_max_size()
    elif choice == "8":
        print("✅ Keeping current max file size")
    else:
        print("❌ Invalid option")


def configure_custom_max_size():
    """Configure custom max file size"""
    global MAX_CONTENT_LENGTH
    while True:
        try:
            size_input = input(
                "Enter max file size in GB (e.g., 10 for 10GB): "
            ).strip()
            if not size_input:
                break
            size_gb = float(size_input)
            if 0.1 <= size_gb <= 1024:  # 0.1GB to 1TB
                MAX_CONTENT_LENGTH = int(size_gb * 1024 * 1024 * 1024)
                print(f"✅ Max file size set to {format_bytes(MAX_CONTENT_LENGTH)}")
                break
            else:
                print("❌ Size must be between 0.1GB and 1024GB")
        except ValueError:
            print("❌ Please enter a valid number")


def configure_session_timeout():
    """Configure session timeout"""
    global PERMANENT_SESSION_LIFETIME
    print(
        f"\nCurrent session timeout: {PERMANENT_SESSION_LIFETIME} seconds ({PERMANENT_SESSION_LIFETIME//60} minutes)"
    )

    timeout_options = {
        "1": 900,  # 15 minutes
        "2": 1800,  # 30 minutes
        "3": 3600,  # 1 hour
        "4": 7200,  # 2 hours
        "5": 14400,  # 4 hours
        "6": 28800,  # 8 hours
    }

    print("\nPreset options:")
    for key, value in timeout_options.items():
        minutes = value // 60
        print(f"{key}. {minutes} minutes")
    print("7. Custom timeout")
    print("8. Keep current")

    choice = input("\nSelect option (1-8): ").strip()

    if choice in timeout_options:
        PERMANENT_SESSION_LIFETIME = timeout_options[choice]
        minutes = PERMANENT_SESSION_LIFETIME // 60
        print(f"✅ Session timeout set to {minutes} minutes")
    elif choice == "7":
        configure_custom_timeout()
    elif choice == "8":
        print("✅ Keeping current timeout")
    else:
        print("❌ Invalid option")


def configure_custom_timeout():
    """Configure custom session timeout"""
    global PERMANENT_SESSION_LIFETIME
    while True:
        try:
            timeout_input = input(
                "Enter timeout in minutes (e.g., 90 for 1.5 hours): "
            ).strip()
            if not timeout_input:
                break
            timeout_minutes = int(timeout_input)
            if 1 <= timeout_minutes <= 1440:  # 1 minute to 24 hours
                PERMANENT_SESSION_LIFETIME = timeout_minutes * 60
                print(f"✅ Session timeout set to {timeout_minutes} minutes")
                break
            else:
                print("❌ Timeout must be between 1 and 1440 minutes (24 hours)")
        except ValueError:
            print("❌ Please enter a valid number")


def configure_host_binding():
    """Configure host binding"""
    global HOST
    print(f"\nCurrent host binding: {HOST}")
    print("0.0.0.0 = Listen on all interfaces (recommended for tunnels)")
    print("127.0.0.1 = Listen only on localhost (local access only)")

    host_options = {"1": "0.0.0.0", "2": "127.0.0.1"}

    print("\nOptions:")
    print("1. 0.0.0.0 (All interfaces)")
    print("2. 127.0.0.1 (Localhost only)")
    print("3. Custom IP")
    print("4. Keep current")

    choice = input("\nSelect option (1-4): ").strip()

    if choice in ["1", "2"]:
        HOST = host_options[choice]
        print(f"✅ Host binding set to {HOST}")
    elif choice == "3":
        custom_host = input("Enter custom IP address: ").strip()
        if custom_host:
            HOST = custom_host
            print(f"✅ Host binding set to {HOST}")
    elif choice == "4":
        print("✅ Keeping current host binding")
    else:
        print("❌ Invalid option")


def generate_session_secret():
    """Session secret is now auto-managed in db/session.secret"""
    print("ℹ️  Session secret is auto-generated and stored in db/session.secret")
    print("   Delete that file to regenerate it (logs out all active users)")


def _toggle_ffmpeg():
    """Toggle ffmpeg / HLS transcoding on or off."""
    global ENABLE_FFMPEG
    current = "Enabled" if ENABLE_FFMPEG else "Disabled"
    print(f"\n🎬 ffmpeg (HLS transcoding) — currently: {current}")
    print("  Enabled  + ffmpeg installed   → full HLS adaptive streaming")
    print("  Enabled  + ffmpeg not found   → graceful raw-playback fallback (existing behaviour)")
    print("  Disabled                      → raw playback always, regardless of installation")
    print("\n1. Enable  ffmpeg")
    print("2. Disable ffmpeg")
    print("3. Keep current")
    choice = input("\nSelect (1-3): ").strip()
    if choice == "1":
        ENABLE_FFMPEG = True
        print("✅ ffmpeg enabled — HLS transcoding active (falls back to raw if not installed)")
    elif choice == "2":
        ENABLE_FFMPEG = False
        print("🚫 ffmpeg disabled — raw playback only")
    else:
        print("✅ Keeping current setting")


def _toggle_libvips():
    """Toggle libvips / image conversion on or off."""
    global ENABLE_LIBVIPS
    current = "Enabled" if ENABLE_LIBVIPS else "Disabled"
    print(f"\n🖼️  libvips (image conversion) — currently: {current}")
    print("  Enabled  + libvips installed  → WebP conversion & compression")
    print("  Enabled  + libvips not found  → graceful raw-serving fallback (existing behaviour)")
    print("  Disabled                      → raw serving always; non-native formats show")
    print("                                  a 'requires processing' notice instead of broken image")
    print("\n1. Enable  libvips")
    print("2. Disable libvips")
    print("3. Keep current")
    choice = input("\nSelect (1-3): ").strip()
    if choice == "1":
        ENABLE_LIBVIPS = True
        print("✅ libvips enabled — image conversion active (falls back to raw if not installed)")
    elif choice == "2":
        ENABLE_LIBVIPS = False
        print("🚫 libvips disabled — raw fallback only")
    else:
        print("✅ Keeping current setting")


def save_server_config():
    """Save server configuration to file"""
    config_data = {
        "PORT": PORT,
        "CHUNK_SIZE": CHUNK_SIZE,
        "ENABLE_CHUNKED_UPLOADS": ENABLE_CHUNKED_UPLOADS,
        "HOST": HOST,
        "MAX_CONTENT_LENGTH": MAX_CONTENT_LENGTH,
        "PERMANENT_SESSION_LIFETIME": PERMANENT_SESSION_LIFETIME,
        "HLS_MIN_SIZE": HLS_MIN_SIZE,
        "HLS_FORCE_FORMATS": sorted(HLS_FORCE_FORMATS),  # set → sorted list for JSON
        "IMG_COMPRESS_MIN_SIZE": IMG_COMPRESS_MIN_SIZE,
        "IMG_WEBP_QUALITY": IMG_WEBP_QUALITY,
        "ENABLE_FFMPEG": ENABLE_FFMPEG,
        "ENABLE_LIBVIPS": ENABLE_LIBVIPS,
        "configured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        with open("server_config.json", "w") as f:
            json.dump(config_data, f, indent=2)
        print("✅ Server configuration saved to server_config.json")
    except Exception as e:
        print(f"❌ Error saving configuration: {e}")


def load_server_config():
    """Load server configuration from file"""
    global PORT, CHUNK_SIZE, ENABLE_CHUNKED_UPLOADS
    global HOST, MAX_CONTENT_LENGTH, PERMANENT_SESSION_LIFETIME
    global HLS_MIN_SIZE, HLS_FORCE_FORMATS
    global IMG_COMPRESS_MIN_SIZE, IMG_WEBP_QUALITY
    global ENABLE_FFMPEG, ENABLE_LIBVIPS

    try:
        if os.path.exists("server_config.json"):
            with open("server_config.json", "r") as f:
                config = json.load(f)

            PORT = config.get("PORT", PORT)
            CHUNK_SIZE = config.get("CHUNK_SIZE", CHUNK_SIZE)
            ENABLE_CHUNKED_UPLOADS = config.get(
                "ENABLE_CHUNKED_UPLOADS", ENABLE_CHUNKED_UPLOADS
            )
            HOST = config.get("HOST", HOST)
            MAX_CONTENT_LENGTH = config.get("MAX_CONTENT_LENGTH", MAX_CONTENT_LENGTH)
            PERMANENT_SESSION_LIFETIME = config.get(
                "PERMANENT_SESSION_LIFETIME", PERMANENT_SESSION_LIFETIME
            )
            HLS_MIN_SIZE = config.get("HLS_MIN_SIZE", HLS_MIN_SIZE)
            # Stored as a list in JSON, convert back to set
            if "HLS_FORCE_FORMATS" in config:
                HLS_FORCE_FORMATS = set(config["HLS_FORCE_FORMATS"])
            IMG_COMPRESS_MIN_SIZE = config.get("IMG_COMPRESS_MIN_SIZE", IMG_COMPRESS_MIN_SIZE)
            IMG_WEBP_QUALITY = config.get("IMG_WEBP_QUALITY", IMG_WEBP_QUALITY)
            ENABLE_FFMPEG = config.get("ENABLE_FFMPEG", ENABLE_FFMPEG)
            ENABLE_LIBVIPS = config.get("ENABLE_LIBVIPS", ENABLE_LIBVIPS)

            print("✅ Server configuration loaded from server_config.json")
            return True
    except Exception as e:
        print(f"⚠️ Could not load server config: {e}")

    return False


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
    """Check if a path exists and is writable."""
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


def _db_cache_examples(subfolder):
    """Return suggested out-of-server-root paths for db / cache / hls / img."""
    home = os.path.expanduser("~")
    if os.name == "nt":
        return [
            os.path.join(os.environ.get("APPDATA", home), "cloudinator", subfolder),
            os.path.join(os.environ.get("LOCALAPPDATA", home), "cloudinator", subfolder),
            os.path.join(home, ".cloudinator", subfolder),
        ]
    else:
        return [
            os.path.join(home, ".cloudinator", subfolder),
            f"/etc/cloudinator/{subfolder}",
            f"/var/lib/cloudinator/{subfolder}",
        ]


def _pick_suggested_path(kind, examples):
    """Present a numbered list of suggested paths and let the user pick one."""
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
    try:
        raw = input(f"Select option (1-{len(examples) + 1}): ").strip()
        choice = int(raw)
    except (ValueError, KeyboardInterrupt):
        return
    if choice < 1 or choice > len(examples):
        return
    path = examples[choice - 1]
    label = {"db": "Database", "cache": "Cache", "hls": "HLS Cache", "img": "Image Cache"}.get(kind, kind)
    if not _confirm_path(path, label):
        return
    if kind == "db":
        set_db_dir(path)
    elif kind == "cache":
        set_cache_dir(path)
    elif kind == "hls":
        set_hls_cache_dir(path)
    else:
        set_img_cache_dir(path)


def _configure_custom_dir(kind):
    """Prompt user for a custom directory path for db / cache / hls / img."""
    label = {"db": "Database", "cache": "Cache", "hls": "HLS Cache", "img": "Image Cache"}.get(kind, kind)
    subfolder = {"db": "db", "cache": "cache", "hls": "hls", "img": "img"}.get(kind, kind)
    print(f"\n🎯 Custom {label} Directory")
    print(f"   Enter a parent folder — '{subfolder}' will be appended automatically.")
    print(f"   Example: /srv/cloudinator  →  /srv/cloudinator/{subfolder}")
    try:
        custom = input("Path: ").strip()
        if not custom:
            return
        expanded = os.path.abspath(os.path.expanduser(custom))
        if os.path.basename(expanded).lower() != subfolder:
            final = os.path.join(expanded, subfolder)
        else:
            final = expanded
        if not _confirm_path(final, label):
            return
        if kind == "db":
            set_db_dir(expanded)
        elif kind == "cache":
            set_cache_dir(expanded)
        elif kind == "hls":
            set_hls_cache_dir(expanded)
        else:
            set_img_cache_dir(expanded)
    except KeyboardInterrupt:
        print("\n👋 Cancelled")


def configure_files_path():
    """Configure Files storage path (ROOT_DIR)."""
    print("\n🗂️  Files Storage Path Configuration")
    print("=" * 50)
    print(f"Current: {ROOT_DIR}\n")

    platform_type = detect_platform()
    if platform_type not in PRESET_PATHS:
        # Unknown platform — fall back to custom path entry
        _configure_custom_files_path()
        return

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
        options.append((key, path))

    print(f"{len(options) + 1}. 🎯 Enter custom path")
    print(f"{len(options) + 2}. ↩️  Back")
    print()

    try:
        raw = input(f"Select option (1-{len(options) + 2}): ").strip()
        choice = int(raw)
    except (ValueError, KeyboardInterrupt):
        return

    if choice == len(options) + 2 or choice < 1:
        return
    elif choice == len(options) + 1:
        _configure_custom_files_path()
    elif 1 <= choice <= len(options):
        key, path = options[choice - 1]
        if not _confirm_path(path, "Files storage"):
            return
        if set_preset_path(key):
            print(f"✅ Files storage set to: {path}")


def _configure_custom_files_path():
    """Prompt for a fully custom Files storage path."""
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
            print(f"✅ Files storage set to: {expanded}")
    except KeyboardInterrupt:
        print("\n👋 Cancelled")


def configure_db_path():
    """Configure Database directory (DB_DIR)."""
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

    try:
        choice = input("Select option (1-4): ").strip()
    except KeyboardInterrupt:
        return

    if choice == "1":
        _pick_suggested_path("db", examples)
    elif choice == "2":
        _configure_custom_dir("db")
    elif choice == "3":
        reset_db_dir()
        print("🔄 Database directory reset to default.")


def configure_cache_path():
    """Configure Cache directory (CACHE_DIR)."""
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

    try:
        choice = input("Select option (1-4): ").strip()
    except KeyboardInterrupt:
        return

    if choice == "1":
        _pick_suggested_path("cache", examples)
    elif choice == "2":
        _configure_custom_dir("cache")
    elif choice == "3":
        reset_cache_dir()
        print("🔄 Cache directory reset to default.")


def configure_hls_cache_path():
    """Configure HLS Cache directory (HLS_CACHE_DIR)."""
    print("\n🎬 HLS Cache Directory Configuration")
    print("=" * 50)
    print(f"Current: {get_hls_cache_dir()}")
    print()
    print("This directory holds ffmpeg-transcoded HLS segments:")
    print("  • <cache_key>/master.m3u8  — adaptive bitrate playlist")
    print("  • <cache_key>/<quality>/   — .ts segment files")
    print("  • <cache_key>/.status.json — transcode progress/state")
    print()
    print("It can grow large for long videos. Point it at a drive")
    print("with plenty of free space. Safe to delete at any time —")
    print("videos will simply be re-transcoded on next play.")
    print()

    examples = _db_cache_examples("hls")
    print("Suggested locations:")
    for ex in examples:
        print(f"  • {ex}")
    print()

    print("1. 📁 Use a suggested location")
    print("2. 🎯 Enter custom path")
    print("3. 🔄 Reset to default  (inside cache dir)")
    print("4. ↩️  Back")
    print()

    try:
        choice = input("Select option (1-4): ").strip()
    except KeyboardInterrupt:
        return

    if choice == "1":
        _pick_suggested_path("hls", examples)
    elif choice == "2":
        _configure_custom_dir("hls")
    elif choice == "3":
        reset_hls_cache_dir()
        print("🔄 HLS Cache directory reset to default.")


def configure_img_cache_path():
    """Configure Image Cache directory (IMG_CACHE_DIR)."""
    print("\n🖼️  Image Cache Directory Configuration")
    print("=" * 50)
    print(f"Current: {get_img_cache_dir()}")
    print()
    print("This directory holds pyvips-converted image previews:")
    print("  • <cache_key>.webp        — lossless or lossy WebP preview")
    print("  • <cache_key>.jpg         — JPEG fallback for oversized images")
    print("  • <cache_key>.meta.json   — conversion metadata (size, format, quality)")
    print()
    print("Safe to delete at any time — previews are regenerated on next view.")
    print()

    examples = _db_cache_examples("img")
    print("Suggested locations:")
    for ex in examples:
        print(f"  • {ex}")
    print()

    print("1. 📁 Use a suggested location")
    print("2. 🎯 Enter custom path")
    print("3. 🔄 Reset to default  (inside cache dir)")
    print("4. ↩️  Back")
    print()

    try:
        choice = input("Select option (1-4): ").strip()
    except KeyboardInterrupt:
        return

    if choice == "1":
        _pick_suggested_path("img", examples)
    elif choice == "2":
        _configure_custom_dir("img")
    elif choice == "3":
        reset_img_cache_dir()
        print("🔄 Image cache directory reset to default.")


def configure_storage_path():
    """Storage path submenu — covers all five storage directories."""
    while True:
        print("\n🗄️  Storage Configuration")
        print("=" * 50)
        print(f"  🗂️  Files   (ROOT_DIR)    : {ROOT_DIR}")
        print(f"  🔐 Database (DB_DIR)     : {get_db_dir()}")
        print(f"  ⚡ Cache    (CACHE_DIR)  : {get_cache_dir()}")
        print(f"  🎬 HLS Cache             : {get_hls_cache_dir()}")
        print(f"  🖼️  Image Cache           : {get_img_cache_dir()}")
        print()
        print("1. 🗂️  Configure Files storage path   (ROOT_DIR)")
        print("2. 🔐 Configure Database directory    (DB_DIR)  ← keys & secrets")
        print("3. ⚡ Configure Cache directory       (CACHE_DIR)")
        print("4. 🎬 Configure HLS Cache directory   (HLS_CACHE_DIR)")
        print("5. 🖼️  Configure Image Cache directory (IMG_CACHE_DIR)")
        print("6. ↩️  Back")
        print()

        try:
            choice = input("Select option (1-6): ").strip()
        except KeyboardInterrupt:
            break

        if choice == "1":
            configure_files_path()
            input("\nPress Enter to continue...")
        elif choice == "2":
            configure_db_path()
            input("\nPress Enter to continue...")
        elif choice == "3":
            configure_cache_path()
            input("\nPress Enter to continue...")
        elif choice == "4":
            configure_hls_cache_path()
            input("\nPress Enter to continue...")
        elif choice == "5":
            configure_img_cache_path()
            input("\nPress Enter to continue...")
        elif choice == "6":
            break
        else:
            print("❌ Invalid option. Please choose 1-6.")

def main_configuration_menu():
    """Main configuration menu"""
    print("\n🏠 Cloudinator Configuration")
    print("=" * 50)

    while True:
        print("\nConfiguration Options:")
        print("1. Storage Path Configuration")
        print("2. Server Settings Configuration")
        print("3. View Current Settings")
        print("4. Exit")

        choice = input("\nSelect option (1-4): ").strip()

        if choice == "1":
            configure_storage_path()
        elif choice == "2":
            configure_server_settings()
        elif choice == "3":
            view_current_settings()
        elif choice == "4":
            print("✅ Configuration complete!")
            break
        else:
            print("❌ Invalid option. Please choose 1-4.")


def configure_hls_settings():
    """Configure HLS streaming thresholds"""
    global HLS_MIN_SIZE, HLS_FORCE_FORMATS

    print("\n🎬 HLS Streaming Configuration")
    print("=" * 50)

    while True:
        print(f"\nCurrent Settings:")
        print(f"1. Min size for HLS:    {format_bytes(HLS_MIN_SIZE)}")
        print(f"   (web-native files smaller than this play raw instead)")
        print(f"2. Always-HLS formats:  {', '.join(sorted(HLS_FORCE_FORMATS))}")
        print(f"   (these always get HLS regardless of size)")
        print("3. Save & Exit")
        print("4. Exit Without Saving")
        print()

        choice = input("Select option (1-4): ").strip()

        if choice == "1":
            _configure_hls_min_size()
        elif choice == "2":
            _configure_hls_force_formats()
        elif choice == "3":
            save_server_config()
            print("✅ HLS configuration saved!")
            break
        elif choice == "4":
            print("↩️  Cancelled")
            break
        else:
            print("❌ Invalid option")


def _configure_hls_min_size():
    """Configure minimum file size to trigger HLS for web-native formats"""
    global HLS_MIN_SIZE

    size_options = {
        "1": (0,                    "Always use HLS for all videos"),
        "2": (10  * 1024 * 1024,   "10 MB"),
        "3": (25  * 1024 * 1024,   "25 MB"),
        "4": (50  * 1024 * 1024,   "50 MB  (default)"),
        "5": (100 * 1024 * 1024,   "100 MB"),
        "6": (250 * 1024 * 1024,   "250 MB"),
        "7": (500 * 1024 * 1024,   "500 MB"),
    }

    print(f"\nCurrent: {format_bytes(HLS_MIN_SIZE)}")
    print("Files below this threshold play raw (for mp4/webm/mov/m4v).")
    print("Non-web-native formats (mkv, avi, etc.) always use HLS regardless.\n")
    for key, (val, label) in size_options.items():
        marker = " ◀ current" if val == HLS_MIN_SIZE else ""
        print(f"{key}. {label}{marker}")
    print("8. Custom size")
    print("9. Keep current")

    choice = input("\nSelect option (1-9): ").strip()

    if choice in size_options:
        HLS_MIN_SIZE = size_options[choice][0]
        print(f"✅ HLS min size set to {format_bytes(HLS_MIN_SIZE) if HLS_MIN_SIZE else 'always HLS'}")
    elif choice == "8":
        while True:
            try:
                raw = input("Enter size in MB (e.g. 75): ").strip()
                if not raw:
                    break
                mb = float(raw)
                if 0 <= mb <= 10240:
                    HLS_MIN_SIZE = int(mb * 1024 * 1024)
                    print(f"✅ HLS min size set to {format_bytes(HLS_MIN_SIZE)}")
                    break
                else:
                    print("❌ Enter a value between 0 and 10240 MB")
            except ValueError:
                print("❌ Please enter a valid number")
    elif choice == "9":
        print("✅ Keeping current setting")
    else:
        print("❌ Invalid option")


def _configure_hls_force_formats():
    """Configure which formats always get HLS regardless of file size"""
    global HLS_FORCE_FORMATS

    all_formats = sorted({"mkv", "avi", "wmv", "flv", "mpg", "mpeg",
                           "m2ts", "mts", "3gp", "ogv", "mov", "ts"})

    print(f"\nCurrent always-HLS formats: {', '.join(sorted(HLS_FORCE_FORMATS))}")
    print("These formats can't be played raw in most browsers, so they")
    print("always get transcoded to HLS regardless of file size.\n")
    print("Available formats:")
    for i, fmt in enumerate(all_formats, 1):
        marker = "✅" if fmt in HLS_FORCE_FORMATS else "  "
        print(f"  {marker} {i:2d}. {fmt}")

    print("\nEnter format numbers to toggle (comma-separated), or press Enter to cancel:")
    raw = input("> ").strip()
    if not raw:
        print("↩️  Cancelled")
        return

    try:
        indices = [int(x.strip()) - 1 for x in raw.split(",")]
        toggled = []
        for idx in indices:
            if 0 <= idx < len(all_formats):
                fmt = all_formats[idx]
                if fmt in HLS_FORCE_FORMATS:
                    HLS_FORCE_FORMATS.discard(fmt)
                    toggled.append(f"removed {fmt}")
                else:
                    HLS_FORCE_FORMATS.add(fmt)
                    toggled.append(f"added {fmt}")
        if toggled:
            print("✅ " + ", ".join(toggled))
            print(f"   Always-HLS formats now: {', '.join(sorted(HLS_FORCE_FORMATS))}")
    except ValueError:
        print("❌ Please enter valid numbers")


def configure_image_settings():
    """Configure image preview / WebP compression thresholds"""
    global IMG_COMPRESS_MIN_SIZE, IMG_WEBP_QUALITY

    print("\n🖼️  Image Preview / WebP Compression Configuration")
    print("=" * 50)

    while True:
        thresh = format_bytes(IMG_COMPRESS_MIN_SIZE) if IMG_COMPRESS_MIN_SIZE else "Always compress"
        print(f"\nCurrent Settings:")
        print(f"1. Compress threshold: {thresh}")
        print(f"   (native images above this size are compressed to lossy WebP)")
        print(f"2. Lossy WebP quality: {IMG_WEBP_QUALITY}  (1–100, lower = smaller file)")
        print(f"   (non-native formats always convert to lossless WebP regardless)")
        print("3. Save & Exit")
        print("4. Exit Without Saving")
        print()

        choice = input("Select option (1-4): ").strip()

        if choice == "1":
            _configure_img_compress_min_size()
        elif choice == "2":
            _configure_img_webp_quality()
        elif choice == "3":
            save_server_config()
            print("✅ Image configuration saved!")
            break
        elif choice == "4":
            print("↩️  Cancelled")
            break
        else:
            print("❌ Invalid option")


def _configure_img_compress_min_size():
    """Configure the file-size threshold above which native images are compressed to WebP"""
    global IMG_COMPRESS_MIN_SIZE

    size_options = {
        "1": (0,                   "Always compress (all native images)"),
        "2": (1  * 1024 * 1024,   "1 MB  (default)"),
        "3": (3  * 1024 * 1024,   "3 MB"),
        "4": (5  * 1024 * 1024,   "5 MB"),
        "5": (10 * 1024 * 1024,   "10 MB"),
        "6": (15 * 1024 * 1024,   "15 MB"),
        "7": (25 * 1024 * 1024,   "25 MB"),
    }

    current_label = format_bytes(IMG_COMPRESS_MIN_SIZE) if IMG_COMPRESS_MIN_SIZE else "Always compress"
    print(f"\nCurrent: {current_label}")
    print("Native images (jpg/png/gif/webp/etc.) below this threshold are served raw.")
    print("Non-native formats (tiff/heic/psd/raw/…) always convert regardless.\n")
    for key, (val, label) in size_options.items():
        marker = " ◀ current" if val == IMG_COMPRESS_MIN_SIZE else ""
        print(f"{key}. {label}{marker}")
    print("8. Custom size")
    print("9. Keep current")

    choice = input("\nSelect option (1-9): ").strip()

    if choice in size_options:
        IMG_COMPRESS_MIN_SIZE = size_options[choice][0]
        label = format_bytes(IMG_COMPRESS_MIN_SIZE) if IMG_COMPRESS_MIN_SIZE else "always compress"
        print(f"✅ Image compress threshold set to {label}")
    elif choice == "8":
        while True:
            try:
                raw = input("Enter size in MB (e.g. 20): ").strip()
                if not raw:
                    break
                mb = float(raw)
                if 0 <= mb <= 10240:
                    IMG_COMPRESS_MIN_SIZE = int(mb * 1024 * 1024)
                    print(f"✅ Image compress threshold set to {format_bytes(IMG_COMPRESS_MIN_SIZE)}")
                    break
                else:
                    print("❌ Enter a value between 0 and 10240 MB")
            except ValueError:
                print("❌ Please enter a valid number")
    elif choice == "9":
        print("✅ Keeping current setting")
    else:
        print("❌ Invalid option")


def _configure_img_webp_quality():
    """Configure the lossy WebP quality used when compressing large native images"""
    global IMG_WEBP_QUALITY

    quality_options = {
        "1": (30, "30 — maximum compression, visible artefacts"),
        "2": (40, "40 — high compression"),
        "3": (50, "50 — balanced  (default)"),
        "4": (60, "60 — better quality"),
        "5": (75, "75 — high quality"),
        "6": (85, "85 — very high quality, larger files"),
        "7": (95, "95 — near-lossless"),
    }

    print(f"\nCurrent lossy WebP quality: {IMG_WEBP_QUALITY}")
    print("Applied when a native image exceeds the compress threshold.")
    print("Non-native formats always use lossless WebP (this setting does not affect them).\n")
    for key, (val, label) in quality_options.items():
        marker = " ◀ current" if val == IMG_WEBP_QUALITY else ""
        print(f"{key}. {label}{marker}")
    print("8. Custom quality (1–100)")
    print("9. Keep current")

    choice = input("\nSelect option (1-9): ").strip()

    if choice in quality_options:
        IMG_WEBP_QUALITY = quality_options[choice][0]
        print(f"✅ Lossy WebP quality set to {IMG_WEBP_QUALITY}")
    elif choice == "8":
        while True:
            try:
                raw = input("Enter quality (1–100): ").strip()
                if not raw:
                    break
                q = int(raw)
                if 1 <= q <= 100:
                    IMG_WEBP_QUALITY = q
                    print(f"✅ Lossy WebP quality set to {IMG_WEBP_QUALITY}")
                    break
                else:
                    print("❌ Quality must be between 1 and 100")
            except ValueError:
                print("❌ Please enter a valid integer")
    elif choice == "9":
        print("✅ Keeping current setting")
    else:
        print("❌ Invalid option")


def view_current_settings():
    """Display current configuration"""
    print("\n📋 Current Configuration")
    print("=" * 50)

    print(f"\n🗂️ Storage Settings:")
    print(f"   Files  (ROOT_DIR)   : {ROOT_DIR}")
    print(f"   Database (DB_DIR)   : {get_db_dir()}")
    print(f"   Cache (CACHE_DIR)   : {get_cache_dir()}")
    print(f"   HLS Cache           : {get_hls_cache_dir()}")
    print(f"   Image Cache         : {get_img_cache_dir()}")

    print(f"\n🔧 Server Settings:")
    print(f"   Port: {PORT}")
    print(f"   Host: {HOST}")
    print(f"   Chunk Size: {format_bytes(CHUNK_SIZE)}")
    print(f"   Chunked Uploads: {'Enabled' if ENABLE_CHUNKED_UPLOADS else 'Disabled'}")
    print(f"   Max File Size: {format_bytes(MAX_CONTENT_LENGTH)}")
    print(f"   Session Timeout: {PERMANENT_SESSION_LIFETIME//60} minutes")
    print(f"   Session Secret: Managed in db/session.secret")

    print(f"\n🎬 HLS / Video Settings:")
    print(f"   ffmpeg (HLS):       {'✅ Enabled' if ENABLE_FFMPEG else '🚫 Disabled'}")
    print(f"   Min size for HLS: {format_bytes(HLS_MIN_SIZE) if HLS_MIN_SIZE else 'Always HLS'}")
    print(f"   Always-HLS formats: {', '.join(sorted(HLS_FORCE_FORMATS))}")

    print(f"\n🖼️  Image Settings:")
    print(f"   libvips (convert):  {'✅ Enabled' if ENABLE_LIBVIPS else '🚫 Disabled'}")
    print(f"   Compress threshold: {format_bytes(IMG_COMPRESS_MIN_SIZE) if IMG_COMPRESS_MIN_SIZE else 'Always compress'}")
    print(f"   Lossy WebP quality: {IMG_WEBP_QUALITY}  (1–100, lower = smaller file)")
    print(f"   Image Cache         : {get_img_cache_dir()}")


# Load configuration on import
load_server_config()

if __name__ == "__main__":
    main_configuration_menu()