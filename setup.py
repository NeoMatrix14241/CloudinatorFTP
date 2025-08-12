#!/usr/bin/env python3
"""
Cloudflare FTP Setup Script
Automatically sets up the application with default configuration
"""

import os
import sys
import subprocess
import json

def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < (3, 6):
        print("❌ Python 3.6 or higher is required")
        return False
    print(f"✅ Python {sys.version.split()[0]} detected")
    return True

def install_dependencies():
    """Install required Python packages"""
    print("📦 Installing dependencies...")
    dependencies = ['flask', 'bcrypt']
    
    for dep in dependencies:
        try:
            __import__(dep)
            print(f"✅ {dep} already installed")
        except ImportError:
            print(f"📥 Installing {dep}...")
            try:
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', dep])
                print(f"✅ {dep} installed successfully")
            except subprocess.CalledProcessError:
                print(f"❌ Failed to install {dep}")
                return False
    return True

def create_directories():
    """Create necessary directories"""
    directories = ['uploads', 'templates']
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"📁 Created directory: {directory}")
        else:
            print(f"✅ Directory exists: {directory}")

def create_default_config():
    """Create default configuration if it doesn't exist"""
    if not os.path.exists('config.py'):
        config_content = '''PORT = 5000
ROOT_DIR = 'uploads'
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB adjustable chunk size
ENABLE_CHUNKED_UPLOADS = True
SESSION_SECRET = 'change_this_secret_in_production'
'''
        with open('config.py', 'w') as f:
            f.write(config_content)
        print("✅ Created default config.py")
    else:
        print("✅ config.py already exists")

def create_default_users():
    """Create default users file"""
    if not os.path.exists('users.json'):
        # Import bcrypt here after we've ensured it's installed
        import bcrypt
        
        def hash_password(password):
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
            return hashed.decode('utf-8')
        
        users = {
            "admin": {
                "password": hash_password("password123"),
                "role": "readwrite"
            },
            "guest": {
                "password": hash_password("guest123"),
                "role": "readonly"
            }
        }
        
        with open('users.json', 'w') as f:
            json.dump(users, f, indent=2)
        
        print("✅ Created default users.json")
        print("   👤 admin (password: password123) - readwrite")
        print("   👤 guest (password: guest123) - readonly")
        print("⚠️  Please change these default passwords using create_user.py!")
    else:
        print("✅ users.json already exists")

def check_cloudflared():
    """Check if cloudflared is available"""
    try:
        result = subprocess.run(['cloudflared', '--version'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ cloudflared is installed")
            return True
    except FileNotFoundError:
        pass
    
    print("⚠️  cloudflared not found")
    print("   Install it with: pkg install cloudflared")
    return False

def main():
    print("🚀 Cloudflare FTP Setup")
    print("=" * 50)
    
    # Check Python version
    if not check_python_version():
        return False
    
    # Install dependencies
    if not install_dependencies():
        print("❌ Failed to install dependencies")
        return False
    
    # Create directories
    create_directories()
    
    # Create config
    create_default_config()
    
    # Create default users
    create_default_users()
    
    # Check cloudflared
    cloudflared_available = check_cloudflared()
    
    print("\n🎉 Setup Complete!")
    print("=" * 50)
    print("📋 Next steps:")
    print("1. Run: python app.py")
    if cloudflared_available:
        print("2. In another terminal: cloudflared tunnel --url http://localhost:5000")
    else:
        print("2. Install cloudflared: pkg install cloudflared")
        print("3. Then run: cloudflared tunnel --url http://localhost:5000")
    print("4. Access your FTP server via the provided Cloudflare URL")
    print("\n🔧 User Management:")
    print("- Run: python create_user.py (to add/modify users)")
    print("- Default login: admin/password123")
    
    return True

if __name__ == '__main__':
    try:
        success = main()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n❌ Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        sys.exit(1)