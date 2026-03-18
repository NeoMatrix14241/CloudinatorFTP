# 📁 Cloudinator - Cloudflare and Termux FTP

A lightweight FTP-like file transfer server that runs on Termux and exposes itself to the internet via Cloudflare tunnels. Access your Android device's storage from anywhere!

## 📷 Login
<img width="1794" height="892" alt="image" src="https://github.com/user-attachments/assets/6437db54-1e73-4459-ba45-f3552e7bbad6" />

## 📷 Guest (READONLY)
<img width="1794" height="1318" alt="image" src="https://github.com/user-attachments/assets/39172a69-7c74-46c6-ba8b-f3e786bc8f43" />

## 📷 Admin (READWRITE)
<img width="1794" height="1648" alt="image" src="https://github.com/user-attachments/assets/93578d61-f486-4463-89c1-1102ca27d456" />

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
pkg install python git cloudflared python-bcrypt build-essential libffi openssl rust llvm binutils-is-llvm python-cryptography ffmpeg

# ⚠️ IMPORTANT: Setup storage access for Android file managers
termux-setup-storage
```
*Grant storage permissions when prompted - this allows files to be accessible from Android file managers*

Note: If trying to deploy to other OS, FFMPEG is optional for adaptive bitrate video preview with video.js

#### 2. 📥 Clone the Project

```bash
git clone https://github.com/NeoMatrix14241/CloudinatorFTP.git
cd CloudinatorFTP
```

#### 3. 🐍 Install Python Dependencies

```bash
pip install -r requirements.txt
```

> **⚠️ Troubleshooting bcrypt installation:**
> If bcrypt installation fails, install build tools first:
> ```bash
> pkg install clang python-dev libcrypt-dev
> ```

#### 4. 📂 Configure Server and Storage Location

**Storage & Cache**
```bash
python setup_storage.py
```

**Server**
```bash
python config.py
```

#### 5. 👥 Setup Users (Optional)

**Default Users** (created automatically):
- Username: `admin`, Password: `admin123` (readwrite access)
- Username: `guest`, Password: `guest123` (readonly access)

**⚠️ Change default passwords immediately!**

**Add/Modify Users:**
```bash
python create_user.py
```

#### 6. 🎯 Launch the Server

For Waitress WSGI (Production/Live)
```bash
python prod_server.py # Waitress Server (WSGI)

or

launch:
- start_prod_server.bat > Waitress Server (WSGI)
```

For Flask WSGI (Development/Testing)
```bash
python dev_server.py # Flask Server (WSGI)

or

launch:
- start_dev_server.bat > Flask Server (WSGI)
```

#### 7. 🌍 Expose to Internet

Open a new terminal session and run:

```bash
cloudflared tunnel --url http://localhost:5000
```

You'll receive a public URL like: `https://random-words-12345.trycloudflare.com`

Or if you want to use it with domain, use these configuration for config.yml of cloudflared:

```bash
tunnel: <tunnel id>
credentials-file: C:\Users\%username%\.cloudflared\<tunnel id>.json
ingress:
  - hostname: domain.com
    service: http://localhost:5000
    originRequest:
      connectTimeout: 0s
      tlsTimeout: 0s
      tcpKeepAlive: 0s
      keepAliveTimeout: 0s
      httpHostHeader: domain.com
      noTLSVerify: true
      disableChunkedEncoding: false
      proxyConnectTimeout: 0s
      expectContinueTimeout: 0s
  - service: http_status:404
```

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
1. **List users** - List all users
2. **Add user** - Create additional user accounts
3. **Update password** - Change existing user passwords
4. **Update role** - Change existing user account role
5. **Delete user** - Remove user accounts

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
| Looping web refresh | Run `revoke_sessions.py` |
| Database gets corrupted | Run `reset_db.py` |

### Server Issues

| Issue | Solution |
|-------|----------|
| `bcrypt` installation fails | `pkg install clang python-dev libcrypt-dev` |
| Port already in use | Change port in `config.py` or kill process |
| Cloudflare tunnel fails | Check internet connection, try again |

## 🌐 Network Configuration

### Default Settings
- **Port**: 5000 (configurable in `config.py`)
- **Host**: 0.0.0.0 (listens on all interfaces)
- **Chunk Size**: 10MB (for large file uploads)

### Firewall Configuration (If needed)

**Linux (UFW):**
```bash
sudo ufw allow 80
```

**Windows Firewall:**
```bash
netsh advfirewall firewall add rule name="CloudflareFTP" dir=in action=allow protocol=TCP localport=80
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

Apache License - see [LICENSE](LICENSE) file for details.


---

