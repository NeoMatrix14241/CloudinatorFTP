import os
import platform
import subprocess
import json
import time

# Server configuration
PORT = 5000
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB adjustable chunk size
ENABLE_CHUNKED_UPLOADS = True
SESSION_SECRET = 'change_this_secret_in_production'
HOST = '0.0.0.0'  # Listen on all interfaces
MAX_CONTENT_LENGTH = 16 * 1024 * 1024 * 1024  # 16GB max file size
ALLOWED_EXTENSIONS = None  # None = allow all file types
PERMANENT_SESSION_LIFETIME = 3600  # 1 hour session timeout

def detect_platform():
    """Detect the current platform and return appropriate info"""
    system = platform.system().lower()
    
    # Check if running in Termux
    if 'TERMUX_VERSION' in os.environ or os.path.exists('/data/data/com.termux'):
        return 'termux'
    elif system == 'linux':
        return 'linux'
    elif system == 'windows':
        return 'windows'
    elif system == 'darwin':
        return 'macos'
    else:
        return 'unknown'

def get_windows_documents_path():
    """Get the proper Windows Documents folder path"""
    try:
        # Try using the USERPROFILE environment variable first
        userprofile = os.environ.get('USERPROFILE')
        if userprofile:
            documents_path = os.path.join(userprofile, 'Documents')
            if os.path.exists(documents_path):
                return documents_path
        
        # Try using Windows registry
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
                documents_path = winreg.QueryValueEx(key, "Personal")[0]
                if os.path.exists(documents_path):
                    return documents_path
        except (ImportError, OSError, FileNotFoundError):
            pass
        
        # Fallback methods
        fallbacks = [
            os.path.join(os.path.expanduser('~'), 'Documents'),
            os.path.join(os.environ.get('HOMEDRIVE', 'C:'), os.environ.get('HOMEPATH', '\\Users\\' + os.environ.get('USERNAME', 'User')), 'Documents'),
            os.path.expanduser('~')
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
    
    if platform_type == 'termux':
        # Check if termux-setup-storage has been run
        shared_storage = '/storage/emulated/0'  # Internal storage root
        downloads = os.path.join(shared_storage, 'Download')
        documents = os.path.join(shared_storage, 'Documents')
        
        # Try to find the best accessible location
        if os.path.exists(downloads) and os.access(downloads, os.W_OK):
            return os.path.join(downloads, 'CloudflareFTP')
        elif os.path.exists(documents) and os.access(documents, os.W_OK):
            return os.path.join(documents, 'CloudflareFTP')
        elif os.path.exists(shared_storage) and os.access(shared_storage, os.W_OK):
            return os.path.join(shared_storage, 'CloudflareFTP')
        else:
            # Fallback to termux home if shared storage not accessible
            print("⚠️  Warning: Shared storage not accessible. Files will be saved to Termux directory.")
            print("   Run 'termux-setup-storage' and grant permissions to save to internal storage.")
            return os.path.join(os.path.expanduser('~'), 'uploads')
    
    elif platform_type == 'linux':
        # Linux: try user's home directory
        home = os.path.expanduser('~')
        return os.path.join(home, 'CloudflareFTP')
    
    elif platform_type == 'windows':
        # Windows: use improved Documents folder detection
        documents_path = get_windows_documents_path()
        return os.path.join(documents_path, 'CloudflareFTP')
    
    elif platform_type == 'macos':
        # macOS: use user's home directory
        home = os.path.expanduser('~')
        return os.path.join(home, 'CloudflareFTP')
    
    else:
        # Unknown platform: use current directory
        return os.path.join(os.getcwd(), 'uploads')

def setup_storage_directory():
    """Create and verify the storage directory"""
    # Check for custom path from environment or config file
    custom_path = None
    
    # 1. Check environment variable
    if 'CLOUDFLARE_FTP_ROOT' in os.environ:
        custom_path = os.environ['CLOUDFLARE_FTP_ROOT']
        print(f"🔧 Using environment variable path: {custom_path}")
    
    # 2. Check for storage config file
    elif os.path.exists('storage_config.json'):
        try:
            import json
            with open('storage_config.json', 'r') as f:
                config = json.load(f)
                custom_path = config.get('storage_path')
                print(f"📋 Using saved configuration: {custom_path}")
        except Exception as e:
            print(f"⚠️  Error reading storage config: {e}")
    
    # 3. Use custom path if provided, otherwise auto-detect
    storage_path = custom_path if custom_path else get_accessible_storage_path()
    platform_type = detect_platform()
    
    try:
        os.makedirs(storage_path, exist_ok=True)
        
        # Test write permissions
        test_file = os.path.join(storage_path, '.write_test')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        
        print(f"✅ Storage directory ready: {storage_path}")
        
        # Platform-specific feedback
        if platform_type == 'termux':
            if '/storage/emulated/0' in storage_path:
                print("✅ Files will be accessible from Android file managers")
                if 'Download' in storage_path:
                    print("📁 Android location: Files app → Downloads → CloudflareFTP")
                elif 'Documents' in storage_path:
                    print("📁 Android location: Files app → Documents → CloudflareFTP")
                else:
                    print("📁 Android location: Files app → Internal Storage → CloudflareFTP")
            else:
                print("⚠️  Files will only be accessible within Termux")
                print("   Run 'termux-setup-storage' for broader access")
                
        elif platform_type == 'windows':
            print(f"📁 Windows location: {storage_path}")
            print("💡 Access via File Explorer or any file manager")
            
        elif platform_type == 'linux':
            print(f"📁 Linux location: {storage_path}")
            print("💡 Access via file manager or terminal")
            
        elif platform_type == 'macos':
            print(f"📁 macOS location: {storage_path}")
            print("💡 Access via Finder")
        
        return storage_path
        
    except PermissionError:
        print(f"❌ Permission denied: {storage_path}")
        # Fallback to current directory
        fallback = os.path.join(os.getcwd(), 'uploads')
        os.makedirs(fallback, exist_ok=True)
        print(f"📁 Using fallback directory: {fallback}")
        return fallback
    except Exception as e:
        print(f"❌ Error creating storage directory: {e}")
        # Fallback to current directory
        fallback = os.path.join(os.getcwd(), 'uploads')
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
    
    if platform_type == 'termux':
        shared_storage = '/storage/emulated/0'
        if ROOT_DIR.startswith(shared_storage):
            print("✅ Files accessible from Android file managers")
        else:
            print("⚠️  Files only accessible within Termux")
            print("💡 Tip: Run 'termux-setup-storage' for broader access")
    
    elif platform_type == 'windows':
        print("💡 Open File Explorer and navigate to the storage location above")
        
    elif platform_type == 'linux':
        print("💡 Use your file manager or: cd \"" + ROOT_DIR + "\"")
        
    elif platform_type == 'macos':
        print("💡 Open Finder and navigate to the storage location above")
    
    # Check available space
    try:
        if platform_type == 'windows':
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
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
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
            final_path = os.path.join(expanded_path, 'CloudinatorFTP')
        else:
            # Use the exact custom path
            final_path = expanded_path
        
        # Create directory
        os.makedirs(expanded_path, exist_ok=True)
        
        # Test write permissions
        test_file = os.path.join(expanded_path, '.write_test')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        
        # Save configuration
        config_data = {
            'storage_path': expanded_path,
            'platform': detect_platform(),
            'set_at': str(os.path.getctime(expanded_path)) if os.path.exists(expanded_path) else None
        }
        
        try:
            import json
            with open('storage_config.json', 'w') as f:
                json.dump(config_data, f, indent=2)
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
    'termux': {
        'downloads': '/storage/emulated/0/Download/CloudflareFTP',
        'documents': '/storage/emulated/0/Documents/CloudflareFTP',
        'internal': '/storage/emulated/0/CloudflareFTP',
        'dcim': '/storage/emulated/0/DCIM/CloudflareFTP',
        'termux_home': os.path.join(os.path.expanduser('~'), 'uploads'),
    },
    'linux': {
        'home': os.path.join(os.path.expanduser('~'), 'CloudflareFTP'),
        'desktop': os.path.join(os.path.expanduser('~'), 'Desktop', 'CloudflareFTP'),
        'documents': os.path.join(os.path.expanduser('~'), 'Documents', 'CloudflareFTP'),
        'downloads': os.path.join(os.path.expanduser('~'), 'Downloads', 'CloudflareFTP'),
    },
    'windows': {
        'documents': os.path.join(get_windows_documents_path(), 'CloudflareFTP'),
        'desktop': os.path.join(os.path.expanduser('~'), 'Desktop', 'CloudflareFTP'),
        'downloads': os.path.join(os.path.expanduser('~'), 'Downloads', 'CloudflareFTP'),
        'userprofile': os.path.join(os.path.expanduser('~'), 'CloudflareFTP'),
    },
    'macos': {
        'documents': os.path.join(os.path.expanduser('~'), 'Documents', 'CloudflareFTP'),
        'desktop': os.path.join(os.path.expanduser('~'), 'Desktop', 'CloudflareFTP'),
        'downloads': os.path.join(os.path.expanduser('~'), 'Downloads', 'CloudflareFTP'),
    }
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
                accessible = "✅" if os.path.exists(parent) and os.access(parent, os.W_OK) else "❌"
                print(f"{accessible} {key}: {path}")
            except Exception:
                print(f"❌ {key}: {path}")
    else:
        print(f"❌ No presets available for {platform_type}")
    
    print(f"\n🔧 Current location: {ROOT_DIR}")
    print(f"\n💡 To change storage location:")
    print(f"   Python: from config import set_preset_path; set_preset_path('documents')")
    print(f"   Env Var: set CLOUDFLARE_FTP_ROOT=C:\\path\\to\\your\\folder")
    print(f"   Direct: from config import set_custom_storage_path; set_custom_storage_path('C:\\path\\to\\folder')")

def configure_server_settings():
    """Interactive server configuration"""
    global PORT, CHUNK_SIZE, ENABLE_CHUNKED_UPLOADS, SESSION_SECRET
    global HOST, MAX_CONTENT_LENGTH, PERMANENT_SESSION_LIFETIME
    
    print("\n🔧 Server Configuration")
    print("=" * 50)
    
    while True:
        print(f"\nCurrent Settings:")
        print(f"1. Port: {PORT}")
        print(f"2. Chunk Size: {format_bytes(CHUNK_SIZE)}")
        print(f"3. Chunked Uploads: {'Enabled' if ENABLE_CHUNKED_UPLOADS else 'Disabled'}")
        print(f"4. Max File Size: {format_bytes(MAX_CONTENT_LENGTH)}")
        print(f"5. Session Timeout: {PERMANENT_SESSION_LIFETIME//60} minutes")
        print(f"6. Host Binding: {HOST}")
        print("7. Generate New Session Secret")
        print("8. Save & Exit")
        print("9. Exit Without Saving")
        
        choice = input("\nSelect option to configure (1-9): ").strip()
        
        if choice == '1':
            configure_port()
        elif choice == '2':
            configure_chunk_size()
        elif choice == '3':
            configure_chunked_uploads()
        elif choice == '4':
            configure_max_file_size()
        elif choice == '5':
            configure_session_timeout()
        elif choice == '6':
            configure_host_binding()
        elif choice == '7':
            generate_session_secret()
        elif choice == '8':
            save_server_config()
            print("✅ Server configuration saved!")
            break
        elif choice == '9':
            print("❌ Configuration cancelled")
            break
        else:
            print("❌ Invalid option. Please choose 1-9.")

def configure_port():
    """Configure server port"""
    global PORT
    print(f"\nCurrent port: {PORT}")
    print("Common ports: 80 (HTTP), 8080 (Alt HTTP), 5000 (Flask default)")
    print("Note: Ports below 1024 may require root privileges")
    
    while True:
        try:
            new_port = input("Enter new port (1-65535) or press Enter to keep current: ").strip()
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
        '1': 1 * 1024 * 1024,      # 1MB
        '2': 5 * 1024 * 1024,      # 5MB
        '3': 10 * 1024 * 1024,     # 10MB
        '4': 25 * 1024 * 1024,     # 25MB
        '5': 50 * 1024 * 1024,     # 50MB
        '6': 100 * 1024 * 1024,    # 100MB
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
    elif choice == '7':
        configure_custom_chunk_size()
    elif choice == '8':
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
    print("Chunked uploads allow resumable uploads and better memory usage for large files")
    
    choice = input("Enable chunked uploads? (y/n): ").strip().lower()
    if choice in ['y', 'yes']:
        ENABLE_CHUNKED_UPLOADS = True
        print("✅ Chunked uploads enabled")
    elif choice in ['n', 'no']:
        ENABLE_CHUNKED_UPLOADS = False
        print("✅ Chunked uploads disabled")
    else:
        print("✅ Keeping current setting")

def configure_max_file_size():
    """Configure maximum file size"""
    global MAX_CONTENT_LENGTH
    print(f"\nCurrent max file size: {format_bytes(MAX_CONTENT_LENGTH)}")
    
    size_options = {
        '1': 1 * 1024 * 1024 * 1024,      # 1GB
        '2': 4 * 1024 * 1024 * 1024,      # 4GB
        '3': 8 * 1024 * 1024 * 1024,      # 8GB
        '4': 16 * 1024 * 1024 * 1024,     # 16GB
        '5': 32 * 1024 * 1024 * 1024,     # 32GB
        '6': 64 * 1024 * 1024 * 1024,     # 64GB
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
    elif choice == '7':
        configure_custom_max_size()
    elif choice == '8':
        print("✅ Keeping current max file size")
    else:
        print("❌ Invalid option")

def configure_custom_max_size():
    """Configure custom max file size"""
    global MAX_CONTENT_LENGTH
    while True:
        try:
            size_input = input("Enter max file size in GB (e.g., 10 for 10GB): ").strip()
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
    print(f"\nCurrent session timeout: {PERMANENT_SESSION_LIFETIME} seconds ({PERMANENT_SESSION_LIFETIME//60} minutes)")
    
    timeout_options = {
        '1': 900,    # 15 minutes
        '2': 1800,   # 30 minutes
        '3': 3600,   # 1 hour
        '4': 7200,   # 2 hours
        '5': 14400,  # 4 hours
        '6': 28800,  # 8 hours
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
    elif choice == '7':
        configure_custom_timeout()
    elif choice == '8':
        print("✅ Keeping current timeout")
    else:
        print("❌ Invalid option")

def configure_custom_timeout():
    """Configure custom session timeout"""
    global PERMANENT_SESSION_LIFETIME
    while True:
        try:
            timeout_input = input("Enter timeout in minutes (e.g., 90 for 1.5 hours): ").strip()
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
    
    host_options = {
        '1': '0.0.0.0',
        '2': '127.0.0.1'
    }
    
    print("\nOptions:")
    print("1. 0.0.0.0 (All interfaces)")
    print("2. 127.0.0.1 (Localhost only)")
    print("3. Custom IP")
    print("4. Keep current")
    
    choice = input("\nSelect option (1-4): ").strip()
    
    if choice in ['1', '2']:
        HOST = host_options[choice]
        print(f"✅ Host binding set to {HOST}")
    elif choice == '3':
        custom_host = input("Enter custom IP address: ").strip()
        if custom_host:
            HOST = custom_host
            print(f"✅ Host binding set to {HOST}")
    elif choice == '4':
        print("✅ Keeping current host binding")
    else:
        print("❌ Invalid option")

def generate_session_secret():
    """Generate new session secret"""
    global SESSION_SECRET
    import secrets
    import string
    
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    SESSION_SECRET = ''.join(secrets.choice(alphabet) for _ in range(32))
    print("✅ New session secret generated")
    print(f"Secret: {SESSION_SECRET[:8]}... (hidden for security)")

def save_server_config():
    """Save server configuration to file"""
    config_data = {
        'PORT': PORT,
        'CHUNK_SIZE': CHUNK_SIZE,
        'ENABLE_CHUNKED_UPLOADS': ENABLE_CHUNKED_UPLOADS,
        'SESSION_SECRET': SESSION_SECRET,
        'HOST': HOST,
        'MAX_CONTENT_LENGTH': MAX_CONTENT_LENGTH,
        'PERMANENT_SESSION_LIFETIME': PERMANENT_SESSION_LIFETIME,
        'configured_at': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    
    try:
        with open('server_config.json', 'w') as f:
            json.dump(config_data, f, indent=2)
        print("✅ Server configuration saved to server_config.json")
    except Exception as e:
        print(f"❌ Error saving configuration: {e}")

def load_server_config():
    """Load server configuration from file"""
    global PORT, CHUNK_SIZE, ENABLE_CHUNKED_UPLOADS, SESSION_SECRET
    global HOST, MAX_CONTENT_LENGTH, PERMANENT_SESSION_LIFETIME
    
    try:
        if os.path.exists('server_config.json'):
            with open('server_config.json', 'r') as f:
                config = json.load(f)
                
            PORT = config.get('PORT', PORT)
            CHUNK_SIZE = config.get('CHUNK_SIZE', CHUNK_SIZE)
            ENABLE_CHUNKED_UPLOADS = config.get('ENABLE_CHUNKED_UPLOADS', ENABLE_CHUNKED_UPLOADS)
            SESSION_SECRET = config.get('SESSION_SECRET', SESSION_SECRET)
            HOST = config.get('HOST', HOST)
            MAX_CONTENT_LENGTH = config.get('MAX_CONTENT_LENGTH', MAX_CONTENT_LENGTH)
            PERMANENT_SESSION_LIFETIME = config.get('PERMANENT_SESSION_LIFETIME', PERMANENT_SESSION_LIFETIME)
            
            print("✅ Server configuration loaded from server_config.json")
            return True
    except Exception as e:
        print(f"⚠️ Could not load server config: {e}")
    
    return False

def configure_storage_path():
    """Storage path configuration (original function)"""
    platform_type = detect_platform()
    
    print(f"\n🏠 Storage Path Configuration for {platform_type.title()}")
    print("=" * 50)
    
    if platform_type == 'windows':
        print("1. Documents folder (Recommended)")
        print("2. Desktop folder") 
        print("3. Downloads folder")
        print("4. User profile folder")
        print("5. Custom path")
        print("6. Exit")
        
        try:
            choice = input("\nSelect option (1-6): ").strip()
            path_map = {
                '1': 'documents',
                '2': 'desktop', 
                '3': 'downloads',
                '4': 'userprofile'
            }
            
            if choice in path_map:
                if set_preset_path(path_map[choice]):
                    print("\n✅ Storage path updated successfully!")
                else:
                    print("\n❌ Failed to set storage path")
            elif choice == '5':
                custom = input("Enter custom path: ").strip()
                if custom and set_custom_storage_path(custom):
                    print("\n✅ Custom storage path set successfully!")
            elif choice == '6':
                print("✅ Configuration cancelled")
            else:
                print("❌ Invalid option")
                
        except KeyboardInterrupt:
            print("\n👋 Configuration cancelled")
        except Exception as e:
            print(f"\n❌ Error: {e}")
    else:
        # For other platforms, show available presets
        list_available_presets()

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
        
        if choice == '1':
            configure_storage_path()
        elif choice == '2':
            configure_server_settings()
        elif choice == '3':
            view_current_settings()
        elif choice == '4':
            print("✅ Configuration complete!")
            break
        else:
            print("❌ Invalid option. Please choose 1-4.")

def view_current_settings():
    """Display current configuration"""
    print("\n📋 Current Configuration")
    print("=" * 50)
    
    print(f"\n🗂️ Storage Settings:")
    print(f"   Root Directory: {ROOT_DIR}")
    
    print(f"\n🔧 Server Settings:")
    print(f"   Port: {PORT}")
    print(f"   Host: {HOST}")
    print(f"   Chunk Size: {format_bytes(CHUNK_SIZE)}")
    print(f"   Chunked Uploads: {'Enabled' if ENABLE_CHUNKED_UPLOADS else 'Disabled'}")
    print(f"   Max File Size: {format_bytes(MAX_CONTENT_LENGTH)}")
    print(f"   Session Timeout: {PERMANENT_SESSION_LIFETIME//60} minutes")
    print(f"   Session Secret: {'Set' if SESSION_SECRET != 'change_this_secret_in_production' else 'Default (Change Required)'}")

# Load configuration on import
load_server_config()

if __name__ == '__main__':
    main_configuration_menu()