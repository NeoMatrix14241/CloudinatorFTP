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
- [🌐 Protocol Access — WebDAV, SFTP, FTP](#-protocol-access--webdav-sftp-ftp)
- [🖥️ Server Management Script (manage.sh)](#️-server-management-script-managesh)
- [🔄 Updating Python Dependencies](#-updating-python-dependencies)
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
| 🔄 **rclone** | [RCLONE_DEPLOYMENT.md](./docs/RCLONE_DEPLOYMENT.md) | Mount and sync via rclone |

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

Install termux packages
``` Bash
apt update -y && apt full-upgrade -y && pkg install curl -y
curl -sL https://tinyurl.com/CloudinatorFTP | bash
```

> The above URL runs `termux_setup.sh` automatically. This script installs all required Termux packages, applies Android-specific PyPPMd patches, requests storage permission, and **retries up to 5 times** on failure. After cloning the repo you can also run it directly with `bash termux_setup.sh`.

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

#### 3b. 📡 Install Protocol Server Dependencies (Optional)

To enable WebDAV, SFTP, and FTP protocol access alongside the web UI:

```bash
pip install wsgidav cheroot paramiko pyftpdlib
```

| Package | Enables |
|---------|---------|
| `wsgidav` | WebDAV HTTP (port 8080) |
| `cheroot` | WebDAV HTTPS (port 8443) |
| `paramiko` | SFTP (port 2222) |
| `pyftpdlib` | FTP (port 2121) |

> **Note**: These are optional. If any are missing, only that protocol server is skipped on startup. The web UI always starts regardless.

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

> 💡 **Recommended for Windows/Linux:** Use [`manage.sh`](#️-server-management-script-managesh) to run servers in the background while keeping your terminal free for utilities.

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

Protocol servers (WebDAV, SFTP, FTP) start **automatically** alongside the web server — no extra command needed.

#### 7. 🌍 Expose to Internet

Open a new terminal session and run — **choose what to tunnel**:

```bash
# Tunnel the web UI (most common)
cloudflared tunnel --url http://localhost:5000

# Or tunnel WebDAV (for remote network drive mapping)
cloudflared tunnel --url http://localhost:8080
```

You'll receive a public URL like: `https://random-words-12345.trycloudflare.com`

> **What port should I tunnel?**
> - `5000` → Web browser access (upload, download, preview via browser)
> - `8080` → WebDAV drive mapping from remote Windows/macOS/Linux machines
> - `8443` → WebDAV HTTPS (use with `--url https://localhost:8443`)
> - Only one port can be tunneled at once with the quick `--url` method. For multiple services, see the [Advanced Tunnel Setup](./docs/SETUP_TUNNEL_ADVANCED.md).
>
> **Note**: SFTP (2222) and FTP (2121) are raw TCP — they work on your local network but cannot be exposed via standard Cloudflare Tunnel.

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

---

## 🌐 Protocol Access — WebDAV, SFTP, FTP

In addition to the web UI, CloudinatorFTP runs three additional protocol servers automatically. All use the **same credentials** as the web interface.

### Port Overview

| Service | Port | Best For |
|---------|------|----------|
| 🌐 Web UI | 5000 | Browser-based file management |
| 📂 WebDAV HTTP | 8080 | Native drive mapping (Windows/macOS/Linux) |
| 🔐 WebDAV HTTPS | 8443 | Native drive mapping (secure, recommended) |
| 🔒 SFTP | 2222 | WinSCP, FileZilla, sshfs |
| 📁 FTP | 2121 | Legacy FTP clients (LAN only) |

### 🌐 WebDAV — Map as a Network Drive

No browser needed — the server appears as a drive letter or volume in your file manager.

**Windows (elevated PowerShell — first time only):**
```powershell
# One-line certificate import from server (no file copying)
$f="$env:TEMP\c.crt"; Invoke-WebRequest http://SERVER-IP:8080/webdav.crt -OutFile $f; Import-Certificate $f -CertStoreLocation Cert:\LocalMachine\Root; del $f

# Map HTTPS drive (no registry edit needed after cert import)
net use X: https://SERVER-IP:8443/ /user:admin admin123 /persistent:yes
```

**macOS:**  Finder → Go → Connect to Server → `http://SERVER-IP:8080`

**Linux:**
```bash
sudo apt install davfs2
sudo mount -t davfs http://SERVER-IP:8080/ /mnt/cloudinator
```

### 🔒 SFTP — WinSCP Quick Setup

- **Protocol**: SFTP  
- **Host**: server IP  
- **Port**: `2222`  
- **Credentials**: same as web UI  
- Accept the host key warning on first connect

### 📁 FTP — WinSCP Quick Setup

- **Protocol**: FTP  
- **Encryption**: No encryption  
- **Host**: server IP  
- **Port**: `2121`  
- **Credentials**: same as web UI

> ⚠️ FTP is plaintext — use on trusted local networks only.

### 🔄 rclone

rclone can mount, sync, and copy via WebDAV, SFTP, or FTP. See [RCLONE_DEPLOYMENT.md](./docs/RCLONE_DEPLOYMENT.md) for full setup.

```bash
# Quick WebDAV mount (no configuration needed)
rclone mount :webdav,url=http://SERVER-IP:8080/,user=admin,pass=admin123: Z: --vfs-cache-mode full
```

---

## 🖥️ Server Management Script (`manage.sh`)

A shell script for **Windows (Git Bash) and Linux/macOS** that runs a server in the background while keeping your terminal free to run utilities — no separate terminal window needed.

### ⚡ Setup

```bash
chmod +x manage.sh
```

### 🚦 Server Commands

> ⚠️ Only one server can run at a time. Attempting to start a second will show a clear status block and stop.

| Command | Description |
|---------|-------------|
| `./manage.sh start server` | Start `prod_server.py` (Waitress) in the background |
| `./manage.sh start dev_server` | Start `dev_server.py` (Flask) in the background |
| `./manage.sh stop` | Gracefully stop whichever server is running |
| `./manage.sh restart` | Restart the currently active server |
| `./manage.sh status` | Show server status, PID, uptime, and recent log tail |

### 📋 Log Commands

Logs are always saved to `logs/` regardless of whether you're watching them.

| Command | Description |
|---------|-------------|
| `./manage.sh logs` | Last 50 lines (auto-detects active server) |
| `./manage.sh logs server` | Last 50 lines of production logs |
| `./manage.sh logs server -f` | Follow live production logs |
| `./manage.sh logs dev_server -f` | Follow live dev logs |

> 💡 **Ctrl-C while following logs detaches your terminal without stopping the server.**

### 🔧 Utility Commands

Run any utility **while a server is running in the same terminal**:

| Command | Equivalent |
|---------|------------|
| `./manage.sh config` | `python config.py` |
| `./manage.sh create-user` | `python create_user.py` |
| `./manage.sh debug-pw` | `python debug_passwords.py` |
| `./manage.sh reset-db` | `python reset_db.py` |
| `./manage.sh setup-storage` | `python setup_storage.py` |

### 🎛️ Interactive Menu

```bash
./manage.sh menu
```

A numbered menu covering all server and utility commands with live status shown at the top.

### 💡 Typical Workflow

```bash
# 1. Start production server in the background
./manage.sh start server

# 2. Run utilities in the same terminal while the server is up
./manage.sh create-user
./manage.sh config

# 3. Check server is still running
./manage.sh status

# 4. View logs on demand (Ctrl-C detaches, server keeps running)
./manage.sh logs server -f

# 5. Stop when done
./manage.sh stop
```

---

## 🔄 Updating Python Dependencies

Keep all packages current without manually editing `requirements.txt`:

```bash
bash update_pymodules.sh
```

Or via `manage.sh` (works on all platforms):

```bash
./manage.sh update-modules
```

The script will:
1. Query PyPI for the latest available version of each package
2. Update `requirements.txt` in place
3. Prompt you to install the updates immediately

> **Android / Termux**: Run the same command in your Termux session.
> **Windows**: Run in Git Bash, or double-click if you have a `.bat` wrapper.
> **Linux**: Activate your virtual environment first (`source venv/bin/activate`).

---

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

Both roles apply equally to the web UI, WebDAV, SFTP, and FTP.

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

### Protocol Server Issues

| Issue | Solution |
|-------|----------|
| WebDAV not starting | `pip install wsgidav cheroot` |
| SFTP not starting | `pip install paramiko` |
| FTP not starting | `pip install pyftpdlib` |
| WebDAV inaccessible (Windows HTTP) | Enable WebClient service; set `BasicAuthLevel=2` |
| WebDAV inaccessible (Windows HTTPS) | Import `db/webdav.crt` as Trusted Root CA |
| SFTP auth fails (WinSCP) | Accept host key warning on first connect; use port 2222 |
| FTP stalls | Open ports 60000-60100 in firewall |
| Ports unreachable | Add firewall rules; verify with `Test-NetConnection` |

### Server Issues

| Issue | Solution |
|-------|----------|
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
- **WebDAV HTTP Port**: 8080
- **WebDAV HTTPS Port**: 8443
- **SFTP Port**: 2222
- **FTP Port**: 2121

### Firewall Configuration (If needed)

**Linux (UFW):**
```bash
sudo ufw allow 80
sudo ufw allow 5000/tcp   # Web UI
sudo ufw allow 8080/tcp   # WebDAV HTTP
sudo ufw allow 8443/tcp   # WebDAV HTTPS
sudo ufw allow 2222/tcp   # SFTP
sudo ufw allow 2121/tcp   # FTP
sudo ufw allow 60000:60100/tcp  # FTP passive
```

**Windows Firewall:**
```bash
netsh advfirewall firewall add rule name="CloudflareFTP" dir=in action=allow protocol=TCP localport=80
```

**Windows Firewall (PowerShell, elevated) — Protocol Servers:**
```powershell
New-NetFirewallRule -DisplayName "CloudinatorFTP Web"           -Direction Inbound -Protocol TCP -LocalPort 5000        -Action Allow
New-NetFirewallRule -DisplayName "CloudinatorFTP WebDAV"        -Direction Inbound -Protocol TCP -LocalPort 8080        -Action Allow
New-NetFirewallRule -DisplayName "CloudinatorFTP WebDAV-HTTPS"  -Direction Inbound -Protocol TCP -LocalPort 8443        -Action Allow
New-NetFirewallRule -DisplayName "CloudinatorFTP SFTP"          -Direction Inbound -Protocol TCP -LocalPort 2222        -Action Allow
New-NetFirewallRule -DisplayName "CloudinatorFTP FTP"           -Direction Inbound -Protocol TCP -LocalPort 2121        -Action Allow
New-NetFirewallRule -DisplayName "CloudinatorFTP FTP-Passive"   -Direction Inbound -Protocol TCP -LocalPort 60000-60100 -Action Allow
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

Apache License - see [LICENSE](LICENSE) file for details.


---