# 📁 Cloudinator - Cloudflare and Termux FTP

A lightweight FTP-like file transfer server that runs on Termux and exposes itself to the internet via Cloudflare tunnels. Access your Android device's storage from anywhere in the world!

## 🚀 Quick Start

### Prerequisites

- Android device with Termux installed (Not the playstore one, download in github or f-droid)
- Internet connection

### Installation & Setup

#### 1. 🔧 Initial Termux Setup

```bash
# Setup storage permissions and update packages
pkg --check-mirror update && pkg update && pkg upgrade -y

# Install required packages
pkg install python git cloudflared python-bcrypt

# ⚠️ IMPORTANT: Setup storage access for Android file managers
termux-setup-storage
```
*Grant storage permissions when prompted - this allows files to be accessible from Android file managers*

#### 2. 🐍 Install Python Dependencies

```bash
pip install flask flash_cors bcrypt
```

> **⚠️ Troubleshooting bcrypt installation:**
> If bcrypt installation fails, install build tools first:
> ```bash
> pkg install clang python-dev libcrypt-dev
> ```

#### 3. 📥 Clone the Project

```bash
git clone https://github.com/NeoMatrix14241/cloudflare-termux-ftp.git
cd cloudflare-termux-ftp
```

#### 4. 📂 Configure Storage Location

**Option A: Interactive Setup (Recommended)**
```bash
python setup_storage.py
python windows_setup.py # For Windows
```

**Option B: Quick Setup**
```bash
# Run the automated setup
python setup.py
```

**Option C: Manual Configuration**
Edit `config.py` and set your desired storage location:
```python
# For Android Downloads folder (accessible in file managers)
ROOT_DIR = '/storage/emulated/0/Download/CloudflareFTP'

# For Android Documents folder
ROOT_DIR = '/storage/emulated/0/Documents/CloudflareFTP'

# For Termux-only storage
ROOT_DIR = 'uploads'
```

#### 5. 👥 Setup Users

**Default Users** (created automatically):
- Username: `admin`, Password: `admin123` (readwrite access)
- Username: `guest`, Password: `guest123` (readonly access)

**⚠️ Change default passwords immediately!**

**Add/Modify Users:**
```bash
python create_user.py
```

#### 6. 🎯 Launch the Server

```bash
python app.py
```

#### 7. 🌍 Expose to Internet

Open a new terminal session and run:

```bash
cloudflared tunnel --url http://localhost:5000
```

You'll receive a public URL like: `https://random-words-12345.trycloudflare.com`

## 📂 Storage Configuration Guide

### 📱 Android (Termux) Storage Options

After running `termux-setup-storage`, you can choose from:

| Location | Path | Accessible From | Best For |
|----------|------|-----------------|----------|
| **Downloads** ⭐ | `/storage/emulated/0/Download/CloudflareFTP` | Files app > Downloads | File sharing, easy access |
| **Documents** | `/storage/emulated/0/Documents/CloudflareFTP` | Files app > Documents | Document storage |
| **Internal Root** | `/storage/emulated/0/CloudflareFTP` | Files app > Internal Storage | General purpose |
| **Camera Folder** | `/storage/emulated/0/DCIM/CloudflareFTP` | Gallery/Photos apps | Photo/video sharing |
| **Termux Only** | `~/uploads` | Termux terminal only | Secure, private files |

### 🖥️ Desktop Platforms

**Linux:**
- `~/CloudflareFTP` (Home directory)
- `~/Documents/CloudflareFTP` (Documents)
- `~/Downloads/CloudflareFTP` (Downloads)

**Windows:**
- `%USERPROFILE%\Documents\CloudflareFTP` (Documents)
- `%USERPROFILE%\Downloads\CloudflareFTP` (Downloads)
- `%USERPROFILE%\Desktop\CloudflareFTP` (Desktop)

**macOS:**
- `~/Documents/CloudflareFTP` (Documents)
- `~/Downloads/CloudflareFTP` (Downloads)

### 🔧 Advanced Storage Setup

**Environment Variable Method:**
```bash
# Set custom storage location
export CLOUDFLARE_FTP_ROOT="/your/custom/path"
python app.py
```

**Programmatic Method:**
```python
from config import set_custom_path
set_custom_path('downloads')  # Use downloads folder
set_custom_path('documents')  # Use documents folder
```

## 👥 User Management Guide

### 🔐 User Roles

- **`readwrite`**: Can upload, download, create folders, delete files
- **`readonly`**: Can only download files and browse folders

### 🛠️ Managing Users

Run the user management tool:
```bash
python create_user.py
```

**Available Options:**
1. **Add new user** - Create additional user accounts
2. **Update password** - Change existing user passwords  
3. **List users** - View all user accounts and roles
4. **Delete user** - Remove user accounts

### 🔑 Default Credentials

| Username | Password | Role | Access Level |
|----------|----------|------|-------------|
| `admin` | `password123` | readwrite | Full access |
| `guest` | `guest123` | readonly | Download only |

**🚨 Security Warning**: Change these default passwords immediately!

### 🐛 Password Troubleshooting

If you're having login issues:

```bash
python debug_passwords.py
```

This tool helps:
- Test if passwords work correctly
- Verify password hashes
- Regenerate user files if corrupted
- Debug authentication issues

## 🎉 Usage

1. **Access your server**: Open the Cloudflare URL in any web browser
2. **Login**: Use your credentials (default: admin/password123)
3. **Upload files**: Drag and drop or click to select files
4. **Download files**: Click the download button next to any file
5. **Create folders**: Use the "Create Folder" form (readwrite users only)
6. **Navigate**: Click folder names to enter, use "Up" button to go back

### 📱 Android File Manager Access

After uploading files, find them in your Android file manager:

- **Downloads location**: Files app → Downloads → CloudflareFTP
- **Documents location**: Files app → Documents → CloudflareFTP  
- **Camera location**: Gallery → CloudflareFTP (photos/videos)

## 🛠️ Troubleshooting

### Storage Issues

| Issue | Solution |
|-------|----------|
| Files not visible in Android | Ensure path starts with `/storage/emulated/0/` |
| "Permission denied" | Run `termux-setup-storage` and grant permissions |
| "Directory not found" | Check if path exists: `ls /storage/emulated/0/` |
| "No space left" | Check storage: `df -h /storage/emulated/0` |

### Authentication Issues

| Issue | Solution |
|-------|----------|
| Login fails with correct password | Run `python debug_passwords.py` |
| Forgot password | Use `create_user.py` to reset password |
| Users file corrupted | Run `debug_passwords.py` → option 4 to regenerate |

### Server Issues

| Issue | Solution |
|-------|----------|
| `bcrypt` installation fails | `pkg install clang python-dev libcrypt-dev` |
| Port already in use | Change port in `config.py` or kill process |
| Cloudflare tunnel fails | Check internet connection, try again |
| Upload fails | Check file size limits and permissions |

### 🔍 Diagnostic Commands

**Check current storage location:**
```bash
python -c "from config import ROOT_DIR; print('Storage:', ROOT_DIR)"
```

**Check platform and available paths:**
```bash
python config.py
```

**Test file system access:**
```bash
# Android
ls -la /storage/emulated/0/
touch /storage/emulated/0/Download/test.txt && rm /storage/emulated/0/Download/test.txt

# Linux/macOS
ls -la ~/
df -h ~

# Windows (in Command Prompt)
dir %USERPROFILE%
```

## 🌐 Network Configuration

### Default Settings
- **Port**: 5000 (configurable in `config.py`)
- **Host**: 0.0.0.0 (listens on all interfaces)
- **Chunk Size**: 10MB (for large file uploads)

### Firewall Configuration

**Linux (UFW):**
```bash
sudo ufw allow 80
```

**Windows Firewall:**
```bash
netsh advfirewall firewall add rule name="CloudflareFTP" dir=in action=allow protocol=TCP localport=80
```

## 🚀 Advanced Usage

### Custom Configuration

Create a custom config file:
```python
# custom_config.py
PORT = 8080
ROOT_DIR = '/your/custom/path'
CHUNK_SIZE = 50 * 1024 * 1024  # 50MB chunks
ENABLE_CHUNKED_UPLOADS = True
SESSION_SECRET = 'your-secret-key-here'
```

### Multiple Instances

Run multiple instances on different ports:
```bash
# Instance 1
PORT=5000 python app.py

# Instance 2  
PORT=5001 python app.py
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---