# 📁 Cloudinator - Cloudflare and Termux FTP

A lightweight FTP-like file transfer server that runs on **Termux (Android), Linux, and Windows** and exposes itself to the internet via Cloudflare tunnels. Access your device's storage from anywhere!

![Android](https://img.shields.io/badge/Android-Termux-3DDC84?logo=android)
![Linux](https://img.shields.io/badge/Linux-supported-FCC624?logo=linux)
![Windows](https://img.shields.io/badge/Windows-supported-0078D6?logo=windows)

## 📷 Login
<img width="1794" height="893" alt="image" src="https://github.com/user-attachments/assets/083a1054-b1bd-446b-946c-a3dda29b459b" />

## 📷 Guest (READONLY)
<img width="1794" height="1201" alt="image" src="https://github.com/user-attachments/assets/b619e8a8-40b7-424d-9628-0c4648e33ed6" />

## 📷 Admin (READWRITE)
<img width="1794" height="1531" alt="image" src="https://github.com/user-attachments/assets/b7167c30-0590-4c23-a391-2022f630e6bb" />

## 📋 Table of Contents

- [📦 Dependencies / Tools](#-dependencies--tools)
- [🚀 Quick Start](#-quick-start)
- [📂 Storage Configuration Guide](#-storage-configuration-guide)
- [👥 User Management Guide](#-user-management-guide)
- [🛠️ Troubleshooting](#️-troubleshooting)
- [🌐 Network & Server Configuration](#-network--server-configuration)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)

## 🚀 Deployment Guides

Platform-specific deployment and production guides are available in the **[`docs/`](./docs)** folder:

| Platform | Guide | Purpose |
|----------|-------|---------|
| 🪟 **Windows** | [WINDOWS_DEPLOYMENT.md](./docs/WINDOWS_DEPLOYMENT.md) | Step-by-step setup for Windows systems |
| 🐧 **Linux** | [LINUX_DEPLOYMENT.md](./docs/LINUX_DEPLOYMENT.md) | Installation and systemd service setup |
| 📱 **Android (Termux)** | [ANDROID_DEPLOYMENT.md](./docs/ANDROID_DEPLOYMENT.md) | Android/Termux deployment and optimization |
| 🪟 **Apache/WSGI** | [DEPLOY_APACHE.md](./docs/DEPLOY_APACHE.md) | Production Apache deployment with mod_wsgi |
| 🔗 **Cloudflare Tunnel** | [SETUP_TUNNEL_ADVANCED.md](./docs/SETUP_TUNNEL_ADVANCED.md) | Advanced tunnel setup with custom domains |

---

## 📦 Dependencies / Tools

- 📱 [Termux](https://termux.dev/en/) - [F-Droid](https://f-droid.org/packages/com.termux/) or [GitHub](https://github.com/termux/termux-app)
- 🎨 [Font Awesome](https://fontawesome.com/) - Free v7.2.0
- 🎬 [FFmpeg](https://www.ffmpeg.org/) - Essentials v57 build 2026-03-19
- 📺 [Video.js](https://videojs.org/) - v10
- 📄 [PDF.js](https://mozilla.github.io/pdf.js/) - v3.11.174
- 🖼️ [libvips](https://www.libvips.org/) - v8.18.1
- 🔧 [Git](https://git-scm.com/) - Latest Version/Build

## 🚀 Quick Start

### Prerequisites

- **Android**: Termux installed (**NOT** the Play Store version)
- **Linux**: Python 3.14.3+, pip, git, libvips, ffmpeg (optional)
- **Windows**: Python 3.14.3+, pip, git, libvips, FFmpeg (optional)
- Internet connection

### Installation & Setup

#### 1. 🔧 Initial Termux Setup

1. Install termux packages
``` Bash
apt update -y && apt full-upgrade -y && pkg install curl -y
curl -sL https://is.gd/8Wvmyb | bash
```

2. Grant termux storage permission when prompted to allow files to be accessible from android file managers
```bash
# Note: Required if serving files with Internal Storage - else will use the termux data path which is inaccessible when not rooted
termux-setup-storage
```

Note: For compatible platforms, [FFmpeg](https://www.gyan.dev/ffmpeg/builds/) is optional for adaptive bitrate video preview with [Video.js](https://videojs.org/).

#### 2. 📥 Clone the Project

For **main** Branch (Stable)
```bash
git clone https://github.com/NeoMatrix14241/CloudinatorFTP.git
cd CloudinatorFTP
```

For **dev** branch
```bash
git clone -b dev https://github.com/NeoMatrix14241/CloudinatorFTP.git
cd CloudinatorFTP
```

#### 3. 🐍 Install Python Dependencies

```bash
pip install -r requirements.txt
```

> **⚠️ Troubleshooting bcrypt installation:**
> If bcrypt installation fails, install build tools first:
> ```bash
> pkg install clang python libcrypt
> ```

#### 4. 📂 Configure Server and Storage Location

**Storage & Cache**
```bash
python setup_storage.py
```

**Server, Storage, & Cache (Advanced)**
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

Or if you want to use it with domain, please refer to this [Advanced Cloudflared Tunneling Setup](https://github.com/NeoMatrix14241/CloudinatorFTP/wiki/Advanced-Cloudflare-Tunnelling-Setup) then use these configuration for config.yml of cloudflared:

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

## 🌐 Network & Server Configuration

### Default Settings
- **Port**: 5000 (configurable in `config.py`)
- **Host**: 0.0.0.0 (listens on all interfaces)
- **Chunk Size**: 10MB (`10485760` bytes, for large file uploads)
- **Chunked Uploads**: Enabled
- **Max Content Length**: 16GB (`17179869184` bytes)
- **Session Lifetime**: 1 hour (`3600` seconds)
- **HLS Minimum Size**: 25MB (`26214400` bytes)
- **HLS Forced Formats**: 3gp, avi, flv, m2ts, mkv, mov, mpeg, mpg, mts, ogv, ts, wmv
- **Compression Thresold**: 3.0 MB (`3145728` bytes)
- **Lossy WebP Quality**: 50

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

