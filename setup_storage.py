#!/usr/bin/env python3
"""
Interactive storage setup script for Cloudflare FTP
"""
import os
import sys
import json

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import importlib, config
    importlib.reload(config)
    import importlib
    import config
    from config import detect_platform, PRESET_PATHS, format_bytes, set_preset_path, set_custom_storage_path
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this script from the project directory.")
    sys.exit(1)

def clear_screen():
    """Clear the terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    """Print the setup banner"""
    print("=" * 60)
    print("🚀 CLOUDFLARE FTP - STORAGE SETUP")
    print("=" * 60)
    print()

def print_current_config():
    """Print current storage configuration"""
    platform = detect_platform()
    
    print(f"📋 Current Configuration:")
    print(f"   Platform: {platform.title()}")
    print(f"   Storage Path: {config.ROOT_DIR}")
    
    # Check if path exists and is writable
    if os.path.exists(config.ROOT_DIR):
        try:
            test_file = os.path.join(config.ROOT_DIR, '.write_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            print(f"   Status: ✅ Accessible and writable")
            
            # Show available space
            try:
                if platform == 'windows':
                    import shutil
                    total, used, free = shutil.disk_usage(config.ROOT_DIR)
                else:
                    stat = os.statvfs(config.ROOT_DIR)
                    free = stat.f_bavail * stat.f_frsize
                
                print(f"   Free Space: {format_bytes(free)}")
            except:
                print(f"   Free Space: Unknown")
                
        except Exception as e:
            print(f"   Status: ❌ Not writable ({e})")
    else:
        print(f"   Status: ❌ Path does not exist")
    
    print()

def show_preset_options():
    """Show available preset paths for current platform"""
    platform = detect_platform()
    
    if platform not in PRESET_PATHS:
        print(f"❌ No preset paths available for {platform}")
        return []
    
    presets = PRESET_PATHS[platform]
    print(f"📍 Available Storage Locations for {platform.title()}:")
    print("-" * 50)
    
    options = []
    for i, (key, path) in enumerate(presets.items(), 1):
        # Check if parent directory exists and is accessible
        try:
            parent = os.path.dirname(path)
            if os.path.exists(parent) and os.access(parent, os.W_OK):
                status = "✅"
            elif os.path.exists(parent):
                status = "⚠️ "
            else:
                status = "❌"
        except:
            status = "❌"
        
        print(f"{i:2d}. {status} {key.replace('_', ' ').title()}")
        print(f"     {path}")
        options.append((key, path))
        
        # Add helpful descriptions
        descriptions = {
            'downloads': 'Recommended for easy access',
            'documents': 'Good for document storage', 
            'desktop': 'Quick access from desktop',
            'internal': 'Android internal storage root',
            'dcim': 'Camera/media folder',
            'termux_home': 'Termux app directory only'
        }
        
        if key in descriptions:
            print(f"     💡 {descriptions[key]}")
        print()
    
    return options

def get_user_choice(max_choice):
    """Get user input with validation"""
    while True:
        try:
            choice = input(f"Select option (1-{max_choice}, 0 to cancel): ").strip()
            if choice == '0':
                return 0
            choice_num = int(choice)
            if 1 <= choice_num <= max_choice:
                return choice_num
            else:
                print(f"❌ Please enter a number between 1 and {max_choice}")
        except ValueError:
            print("❌ Please enter a valid number")
        except KeyboardInterrupt:
            print("\n👋 Setup cancelled")
            return 0

def setup_custom_path():
    """Setup custom storage path"""
    print("\n🔧 Custom Path Setup")
    print("-" * 30)
    print("Enter the full path where you want to store files.")
    print("No subdirectory will be created; the exact path will be used.")
    print()
    
    examples = {
        'windows': [
            'C:\\Users\\YourName\\Desktop',
            'D:\\MyFiles',
            'C:\\Users\\YourName\\Documents'
        ],
        'linux': [
            '/home/username/Desktop',
            '/media/username/USB_Drive',
            '/opt/storage'
        ],
        'termux': [
            '/storage/emulated/0',
            '/storage/emulated/0/Download',
            '/sdcard/Documents'
        ],
        'macos': [
            '/Users/username/Desktop',
            '/Users/username/Documents',
            '/Volumes/ExternalDrive'
        ]
    }
    
    platform = detect_platform()
    if platform in examples:
        print("💡 Examples for your platform:")
        for example in examples[platform]:
            print(f"   {example}")
        print()
    
    while True:
        try:
            custom_path = input("Enter custom path: ").strip()
            if not custom_path:
                print("❌ Path cannot be empty")
                continue
            
            # Expand user paths like ~/Documents
            expanded_path = os.path.expanduser(custom_path)
            # For custom path, use exactly what the user specified (no subfolder)
            if set_custom_storage_path(expanded_path, use_subfolder=False):
                importlib.reload(config)
                return True
            else:
                retry = input("\n❓ Try a different path? (y/n): ").strip().lower()
                if retry != 'y':
                    return False
                    
        except KeyboardInterrupt:
            print("\n👋 Custom setup cancelled")
            return False

def main_menu():
    """Main interactive menu"""
    while True:
        clear_screen()
        print_banner()
        print_current_config()
        
        print("🔧 Setup Options:")
        print("1. 📍 Choose from preset locations")
        print("2. 🎯 Enter custom path") 
        print("3. ✅ Keep current configuration")
        print("4. 🔄 Refresh/test current path")
        print("5. ❌ Exit")
        print()
        
        choice = get_user_choice(5)
        
        if choice == 0 or choice == 5:
            print("👋 Goodbye!")
            break
            
        elif choice == 1:
            # Preset locations
            options = show_preset_options()
            if not options:
                input("Press Enter to continue...")
                continue
                
            print(f"{len(options) + 1}. 🎯 Enter custom path instead")
            print(f"{len(options) + 2}. ↩️  Back to main menu")
            print()
            
            preset_choice = get_user_choice(len(options) + 2)
            
            if preset_choice == 0 or preset_choice == len(options) + 2:
                continue
            elif preset_choice == len(options) + 1:
                setup_custom_path()
                input("\nPress Enter to continue...")
            elif 1 <= preset_choice <= len(options):
                key, path = options[preset_choice - 1]
                if set_preset_path(key):
                    importlib.reload(config)
                    print(f"\n✅ Storage location updated successfully!")
                    print(f"📁 New path: {path}")
                else:
                    print(f"\n❌ Failed to set storage location")
                input("\nPress Enter to continue...")
                
        elif choice == 2:
            # Custom path
            if setup_custom_path():
                print(f"\n✅ Custom storage path set successfully!")
            input("\nPress Enter to continue...")
            
        elif choice == 3:
            # Keep current
            print("✅ Keeping current configuration")
            print(f"📁 Storage path: {config.config.ROOT_DIR}")
            break
            
        elif choice == 4:
            # Refresh/test
            try:
                from config import setup_storage_directory
                new_path = setup_storage_directory()
                print(f"🔄 Configuration refreshed")
                print(f"📁 Path: {new_path}")
            except Exception as e:
                print(f"❌ Error refreshing configuration: {e}")
            input("\nPress Enter to continue...")

def main():
    """Main entry point"""
    try:
        print("🚀 Cloudflare FTP Storage Setup")
        print("This tool will help you configure where files are stored.\n")
        
        # Check if running from correct directory
        if not os.path.exists('config.py'):
            print("❌ Error: config.py not found!")
            print("Make sure you're running this script from the project directory.")
            return 1
        
        main_menu()
        
        print("\n🎯 Setup Complete!")
        print("Run 'python app.py' to start the FTP server.")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n👋 Setup cancelled by user")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())