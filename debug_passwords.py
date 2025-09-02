#!/usr/bin/env python3
"""
Debug script to test password authentication and verify user credentials
"""

import json
import bcrypt

def load_users():
    """Load users from users.json"""
    try:
        with open('users.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ users.json not found")
        return {}
    except json.JSONDecodeError:
        print("❌ Invalid JSON in users.json")
        return {}

def test_password(username, password, users):
    """Test if a password works for a given user"""
    user = users.get(username)
    if not user:
        print(f"❌ User '{username}' not found")
        return False
    
    stored_hash = user['password'].encode('utf-8')
    input_password = password.encode('utf-8')
    
    try:
        result = bcrypt.checkpw(input_password, stored_hash)
        print(f"{'✅' if result else '❌'} {username} / {password} -> {'SUCCESS' if result else 'FAILED'}")
        return result
    except Exception as e:
        print(f"❌ Error checking password for {username}: {e}")
        return False

def test_default_passwords():
    """Test the documented default passwords"""
    users = load_users()
    if not users:
        return
    
    print("🔍 Testing documented default passwords:")
    print("-" * 50)
    
    # Test documented defaults
    test_password('admin', 'password123', users)
    test_password('guest', 'guest123', users)
    
    print("\n🔍 Testing common alternatives:")
    print("-" * 50)
    
    # Test some common alternatives
    common_passwords = ['admin', 'password', '123456', 'admin123', 'guest', '']
    
    for username in users.keys():
        print(f"\nTesting passwords for '{username}':")
        for pwd in common_passwords:
            test_password(username, pwd, users)

def regenerate_default_users():
    """Regenerate users.json with known passwords"""
    print("\n🔧 Regenerating users.json with confirmed passwords...")
    
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
    
    try:
        # Backup existing file
        import shutil
        try:
            shutil.copy('users.json', 'users.json.backup')
            print("📋 Backed up existing users.json to users.json.backup")
        except:
            pass
        
        # Write new file
        with open('users.json', 'w') as f:
            json.dump(users, f, indent=2)
        
        print("✅ Created new users.json with confirmed passwords")
        print("   👤 admin / password123 (readwrite)")
        print("   👤 guest / guest123 (readonly)")
        
        # Verify the new passwords work
        print("\n🧪 Verifying new passwords:")
        print("-" * 30)
        test_password('admin', 'password123', users)
        test_password('guest', 'guest123', users)
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating new users.json: {e}")
        return False

def inspect_hash_details():
    """Inspect the actual hash details"""
    users = load_users()
    if not users:
        return
    
    print("\n🔬 Hash Analysis:")
    print("-" * 50)
    
    for username, user_data in users.items():
        hash_str = user_data['password']
        print(f"\n👤 {username}:")
        print(f"   Hash: {hash_str}")
        print(f"   Length: {len(hash_str)} characters")
        print(f"   Starts with: {hash_str[:7]}")
        
        # Parse bcrypt hash components
        try:
            parts = hash_str.split('$')
            if len(parts) >= 4:
                algorithm = parts[1]
                cost = parts[2]
                salt_hash = parts[3]
                print(f"   Algorithm: {algorithm}")
                print(f"   Cost factor: {cost}")
                print(f"   Salt+Hash length: {len(salt_hash)}")
            else:
                print("   ⚠️  Invalid bcrypt format")
        except:
            print("   ❌ Cannot parse hash")

def main():
    print("🔐 Cloudflare FTP Password Debug Tool")
    print("=" * 50)
    
    users = load_users()
    if not users:
        print("❌ No users found. Run create_user.py or setup.py first.")
        return
    
    print(f"📋 Found {len(users)} user(s)")
    
    while True:
        print("\nOptions:")
        print("1. Test documented default passwords")
        print("2. Test custom password")
        print("3. Inspect hash details")
        print("4. Regenerate users.json with fresh hashes")
        print("5. Exit")
        
        choice = input("\nSelect option (1-5): ").strip()
        
        if choice == '1':
            test_default_passwords()
            
        elif choice == '2':
            username = input("Enter username: ").strip()
            password = input("Enter password to test: ").strip()
            test_password(username, password, users)
            
        elif choice == '3':
            inspect_hash_details()
            
        elif choice == '4':
            confirm = input("This will overwrite users.json. Continue? (yes/no): ").strip().lower()
            if confirm in ['yes', 'y']:
                if regenerate_default_users():
                    users = load_users()  # Reload after regeneration
                
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