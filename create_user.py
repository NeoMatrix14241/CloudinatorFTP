#!/usr/bin/env python3
"""
Password hash generator for Cloudflare FTP users
Usage: python create_user.py
"""

import bcrypt
import json
import os

def hash_password(password):
    """Generate bcrypt hash for password"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def load_users():
    """Load existing users from users.json"""
    if os.path.exists('users.json'):
        try:
            with open('users.json', 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print("⚠️  Error reading users.json, starting with empty user list")
            return {}
    return {}

def save_users(users):
    """Save users to users.json"""
    try:
        with open('users.json', 'w') as f:
            json.dump(users, f, indent=2)
        return True
    except IOError:
        print("❌ Error saving users.json")
        return False

def add_user(users):
    """Add a new user"""
    username = input("Enter username: ").strip()
    if not username:
        print("❌ Username cannot be empty")
        return False
    
    if username in users:
        print(f"❌ User '{username}' already exists")
        return False
    
    password = input("Enter password: ").strip()
    if not password:
        print("❌ Password cannot be empty")
        return False
    
    print("\nRole options:")
    print("  readwrite - Can upload, download, create folders, delete")
    print("  readonly  - Can only download files")
    role = input("Enter role (readwrite/readonly): ").strip().lower()
    
    if role not in ['readwrite', 'readonly']:
        print("❌ Invalid role. Must be 'readwrite' or 'readonly'")
        return False
    
    try:
        hashed_password = hash_password(password)
        users[username] = {
            'password': hashed_password,
            'role': role
        }
        
        if save_users(users):
            print(f"✅ User '{username}' added successfully with role '{role}'")
            return True
        else:
            return False
    except Exception as e:
        print(f"❌ Error creating user: {e}")
        return False

def update_user_password(users):
    """Update existing user password"""
    if not users:
        print("❌ No users exist")
        return False
    
    username = input("Enter username to update: ").strip()
    if username not in users:
        print(f"❌ User '{username}' not found")
        return False
    
    password = input("Enter new password: ").strip()
    if not password:
        print("❌ Password cannot be empty")
        return False
    
    try:
        hashed_password = hash_password(password)
        users[username]['password'] = hashed_password
        
        if save_users(users):
            print(f"✅ Password updated for user '{username}'")
            return True
        else:
            return False
    except Exception as e:
        print(f"❌ Error updating password: {e}")
        return False

def list_users(users):
    """List all users"""
    if not users:
        print("❌ No users exist")
        return
    
    print("\n📋 Current Users:")
    print("-" * 30)
    for username, data in users.items():
        role = data.get('role', 'unknown')
        print(f"👤 {username} ({role})")

def delete_user(users):
    """Delete a user"""
    if not users:
        print("❌ No users exist")
        return False
    
    username = input("Enter username to delete: ").strip()
    if username not in users:
        print(f"❌ User '{username}' not found")
        return False
    
    confirm = input(f"Are you sure you want to delete '{username}'? (yes/no): ").strip().lower()
    if confirm in ['yes', 'y']:
        try:
            del users[username]
            if save_users(users):
                print(f"✅ User '{username}' deleted successfully")
                return True
            else:
                return False
        except Exception as e:
            print(f"❌ Error deleting user: {e}")
            return False
    else:
        print("❌ Deletion cancelled")
        return False

def create_default_users():
    """Create default users if users.json doesn't exist"""
    if not os.path.exists('users.json'):
        print("🔧 Creating default users...")
        try:
            users = {
                "admin": {
                    "password": hash_password("admin123"),
                    "role": "readwrite"
                },
                "guest": {
                    "password": hash_password("guest123"),
                    "role": "readonly"
                }
            }
            
            if save_users(users):
                print("✅ Default users created:")
                print("   👤 admin (password: password123) - readwrite")
                print("   👤 guest (password: guest123) - readonly")
                print("⚠️  Please change these default passwords!")
                return True
            else:
                return False
        except Exception as e:
            print(f"❌ Error creating default users: {e}")
            return False
    else:
        print("✅ users.json already exists")
        return True

def main():
    """Main application loop"""
    print("🔐 Cloudflare FTP User Management")
    print("=" * 40)
    
    # Create default users if needed
    if not create_default_users():
        print("❌ Failed to create default users")
        return
    
    while True:
        users = load_users()
        
        print("\nOptions:")
        print("1. Add new user")
        print("2. Update existing user password")
        print("3. List all users")
        print("4. Delete user")
        print("5. Exit")
        
        choice = input("\nSelect option (1-5): ").strip()
        
        if choice == '1':
            add_user(users)
        
        elif choice == '2':
            update_user_password(users)
        
        elif choice == '3':
            list_users(users)
        
        elif choice == '4':
            delete_user(users)
        
        elif choice == '5':
            print("👋 Goodbye!")
            break
        
        else:
            print("❌ Invalid option. Please select 1-5")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
        print("Please check your Python installation and try again.")