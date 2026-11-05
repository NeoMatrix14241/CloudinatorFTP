# 🐧 CloudinatorFTP Linux Deployment Guide

A comprehensive guide to deploy CloudinatorFTP on Linux systems, enabling lightweight file sharing with Cloudflare tunnel integration.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [System Requirements](#system-requirements)
3. [Dependency Installation](#dependency-installation)
4. [Project Setup](#project-setup)
5. [Virtual Environment](#virtual-environment)
6. [Configuration](#configuration)
7. [User Management](#user-management)
8. [Launch Server](#launch-server)
9. [Server Management Script (manage.sh)](#️-server-management-script-managesh)
10. [Updating Python Dependencies](#-updating-python-dependencies)
11. [Systemd Service Setup](#systemd-service-setup)
12. [Protocol Servers — WebDAV, SFTP, FTP, SMB](#protocol-servers--webdav-sftp-ftp-smb)
13. [Network Exposure](#network-exposure)
14. [Storage Configuration](#storage-configuration-details)
15. [Troubleshooting](#troubleshooting)
16. [Performance Optimization](#performance-optimization)
17. [Monitoring](#monitoring)

---

## Prerequisites

- **Linux Distribution**: Ubuntu 20.04+, Debian 11+, Fedora, CentOS, Arch, or similar
- **Root or Sudo Access**: Required for system package installation
- **Python 3.14.3+**, pip, git, libvips, and ffmpeg (optional)
- **Internet Connection**
- **Basic Command-Line Knowledge**

### Tested Distributions

- ✅ Ubuntu 20.04, 22.04, 24.04
- ✅ Debian 11, 12
- ✅ Fedora 38, 39, 40
- ✅ CentOS 8, 9
- ✅ Arch Linux
- ✅ Linux Mint

---

## System Requirements

### Minimum Specifications

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 2 Cores | 4+ Cores |
| **RAM** | 512 MB | 2 GB + |
| **Storage** | 1 GB | 10 GB + |
| **Python** | 3.14.3 | 3.14.3+ |

### Disk Space Requirements

- **Application**: ~500 MB
- **Database**: ~10 MB
- **Cache**: ~100 MB (varies by usage)
- **File Storage**: Depends on your files

---

## Dependency Installation

### Tools and Versions

| Tool | Version | Required? |
|------|---------|-----------|
| [Python](https://www.python.org/downloads/) | 3.14.3+ | ✅ Required |
| [Git](https://git-scm.com/) | Latest version/build | ✅ Required |
| [libvips](https://www.libvips.org/) | v8.18.1 (the version listed in the README; distro packages may be older) | ✅ Required |
| [FFmpeg](https://www.ffmpeg.org/) | Your distro's package | Optional — adaptive bitrate video preview with [Video.js](https://videojs.org/) |
| [Node.js](https://nodejs.org/en) | v24.22.0 LTS | Optional — only used by `./manage.sh qa` to syntax-check the JavaScript |
| [cloudflared](https://github.com/cloudflare/cloudflared/releases) | Latest | Optional — exposing the server to the internet |

The web UI also uses [Video.js](https://videojs.org/) v10, [PDF.js](https://mozilla.github.io/pdf.js/) v3.11.174 and [Font Awesome](https://fontawesome.com/) v7.2.0 — there is nothing to install for these.

### Step 1: Update System Packages

```bash
sudo apt update && sudo apt upgrade -y
```

### Step 2: Install Required Dependencies

#### Ubuntu/Debian

```bash
sudo apt install -y python3-pip python3-venv git build-essential libvips42 libvips-dev ffmpeg
```

#### Fedora

```bash
sudo dnf install -y python3-pip python3-devel git gcc libvips-devel libvips ffmpeg
```

#### CentOS/RHEL

```bash
sudo yum install -y python3-pip python3-devel git gcc libvips-devel libvips ffmpeg
```

#### Arch Linux

```bash
sudo pacman -S python-pip git base-devel libvips ffmpeg --noconfirm
```

> **Python 3.14.3+ is required.** Many distributions ship an older Python in their default repositories. If `python3 --version` reports something older, install 3.14.3+ from [python.org](https://www.python.org/downloads/) or with a version manager such as `pyenv` or `uv`, and use that interpreter to create the virtual environment below.
>
> **ffmpeg is optional** — it enables adaptive bitrate video preview with Video.js.

### Step 3: Upgrade pip

```bash
pip3 install --upgrade pip setuptools wheel
```

### Step 4: Install Cloudflare Tunnel (Optional)

For exposing your server to the internet:

```bash
# Download the latest version
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb

# Install
sudo dpkg -i cloudflared.deb
```

Or use your package manager:

```bash
# Ubuntu/Debian
sudo apt install cloudflared

# Fedora
sudo dnf install cloudflared

# AUR (Arch Linux)
yay -S cloudflared
```

### Step 4b: Install Node.js (Optional)

Only needed if you modify the code and run the QA checks: `./manage.sh qa` runs `node --check` on the JavaScript when Node.js is installed. Install the **v24 LTS** release from [nodejs.org](https://nodejs.org/en) (or your package manager / a version manager) and verify:

```bash
node --version
```

---

## Project Setup

### Step 5: Clone the Repository

#### Stable Release (Main Branch)

```bash
git clone https://github.com/NeoMatrix14241/CloudinatorFTP.git
cd CloudinatorFTP
```

#### Development Branch

```bash
git clone -b dev https://github.com/NeoMatrix14241/CloudinatorFTP.git
cd CloudinatorFTP
```

---

## Virtual Environment

### Step 6: Create and Activate Virtual Environment

#### Create Virtual Environment

```bash
python3 -m venv .venv
```

#### Activate Virtual Environment

```bash
source .venv/bin/activate
```

> **Note**: You'll see `(.venv)` in your terminal prompt when activated.

> **Note**: The activation script must be **sourced** (`source ...`). Running `.venv/bin/activate` on its own starts a subshell and activates nothing. `bash setup_pymodules.sh` (or `./manage.sh update-modules`) creates and activates `.venv` for you when you answer `y`.

#### Deactivate (When Done)

```bash
deactivate
```

---

## Configuration

### Step 7.1: Install Python Dependencies

```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# Main requirements
pip install -r requirements.txt

# Dev only (optional) - if you will modify the code and run the tests
pip install -r requirements-dev.txt
```

### Step 7.1b: Install Protocol Server Dependencies (Optional)

The WebDAV, SFTP, FTP, and SMB servers use the libraries below. Most are already pulled in by `requirements.txt`; if a protocol server reports a missing package at startup, install it with:

```bash
pip install wsgidav cheroot paramiko pyftpdlib impacket
```

| Package | Protocol | Purpose |
|---------|----------|---------|
| `wsgidav` | WebDAV | WebDAV WSGI server (HTTPS on port 8443 by default) |
| `cheroot` | WebDAV HTTPS | WSGI server with TLS support |
| `paramiko` | SFTP | SSH/SFTP implementation (port 2222) |
| `pyftpdlib` | FTP | FTP server (port 2121) |
| `impacket` | SMB | SMB server (the only pure-Python option that exists) |

> **Note**: Each is optional — if missing, only that protocol server is skipped, with a warning. The web UI always starts regardless.

### Step 7.2: Configure Storage Location

```bash
python tools/setup_storage.py
```

Follow the interactive prompts to configure:
- **Files Directory**: Where uploaded files are stored
- **Database Directory**: SQLite database and encryption keys
- **Cache Directory**: File index and temporary data

#### Recommended Storage Paths

| Component | Path | Why |
|-----------|------|-----|
| **Files** | `~/CloudflareFTP` | Easy access, user-owned |
| **Files** | `~/Documents/CloudflareFTP` | Organized, backed up |
| **Files** | `~/Downloads/CloudflareFTP` | Share downloads |
| **Database** | `/var/lib/cloudinator/db` | Out of web root, secure |
| **Cache** | `/var/cache/cloudinator` | Temporary data, auto-cleanup |

#### Example Configuration

```
Files:     /home/user/CloudflareFTP
Database:  /var/lib/cloudinator/db
Cache:     /var/cache/cloudinator
```

### Step 7.3: Advanced Configuration (Optional)

```bash
python config.py
```

Every setting is explained in the [Configuration Reference](./CONFIG_PY_REFERENCE.md).

Customize:
- Server port (default: 5000)
- Chunk size (default: 10 MB)
- Session lifetime (default: 365 days)
- HLS/compression settings
- **Protocol server ports and enable/disable** (option 13)

#### Default Settings

These are the built-in defaults in `config.py`. Values saved in `server_config.json` (written by `python config.py`) override them. See the [Configuration Reference](./CONFIG_PY_REFERENCE.md) for every setting.

- **Port**: 5000 (configurable in `config.py`)
- **Host**: 0.0.0.0 (listens on all interfaces)
- **Chunk Size**: 10MB (`10485760` bytes, for large file uploads)
- **Chunked Uploads**: Enabled
- **Max Content Length**: 16GB (`17179869184` bytes)
- **Session Lifetime**: 365 days (`31536000` seconds)
- **HLS Minimum Size**: 50MB (`52428800` bytes)
- **HLS Forced Formats**: 3gp, avi, flv, m2ts, mkv, mpeg, mpg, mts, ogv, wmv
- **Image Compression Threshold**: 1.0 MB (`1048576` bytes)
- **Lossy WebP Quality**: 50
- **WebDAV HTTPS Port**: 8443 (enabled by default)
- **WebDAV HTTP Port**: 8080 (off by default; only used if HTTPS is disabled or its certificate can't be prepared)
- **SFTP Port**: 2222
- **FTP Port**: 2121 (FTPS enabled by default)
- **SMB Port**: 445, fallback 8445 (off by default; run `python tools/smb_setup.py` first)

### Step 7.4: Update security.txt and robots.txt

**Important if you expose the server through a tunnel; otherwise optional.**

- `static/.well-known/security.txt` — use your own details (security contact, RFC 9116)
- `static/robots.txt` — by default, everything is blocked politely

You can create `security.txt` from the command line:

```bash
./manage.sh security-txt --contact you@example.com --expires 2030-09-03 --preferred-lang en,fil --canonical https://yourdomain.com/.well-known/security.txt
```

or from the interactive menu: `./manage.sh menu` → entry **18**.

---

## User Management

### Step 8: Setup Users

#### User Roles

- **`readwrite`**: Can upload, download, create folders, delete files
- **`readonly`**: Can only download files and browse folders

Both roles apply equally to the web UI, WebDAV, SFTP, and FTP.

#### Default Users

When initialized, the system creates:

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | readwrite |
| `guest` | `guest123` | readonly |

> 🚨 **Change these immediately before exposing to the internet!**

#### Add/Modify Users

```bash
python tools/manage_users.py
```

**Menu Options:**
1. **List users** - List all users (flags accounts that still have a default password)
2. **Add user** - Create additional user accounts
3. **Change password** - Change an existing user's password
4. **Change role** - Change an existing user's role
5. **Delete user** - Remove user accounts
6. **Remove default users** - Delete `admin` and `guest` if they still have their default passwords
7. **Exit**

#### Example: Create Admin User

```bash
python tools/manage_users.py
# Select: Add user (2)
# Username: alice
# Password: [secure password]
# Role: readwrite
```

#### Check a Login

The old `debug_passwords.py` tester was removed in 4.80. If you're having login issues, list the users and change the password if needed:

```bash
python tools/manage_users.py
# 1. List users   3. Change password
```

This tool helps:
- See which accounts exist, their role and last login (and which still use a default password)
- Set a new password for an account you are locked out of
- Fix a wrong role, or remove the default accounts

> After 5 failed logins a client is locked out for 5 minutes, so wait for the lockout to end before trying again.

#### Revoke Access Quickly (Security Incident)

```bash
python tools/kick_sessions.py
```

Interactive tool for "lock this person out now" situations — rotate a password, delete a user, or instantly log everyone out of the web UI. If the web UI is stuck in a looping refresh, run `python tools/kick_sessions.py logout-web`. See [SMB_PROTOCOL_DEPLOYMENT.md](./SMB_PROTOCOL_DEPLOYMENT.md) for the per-protocol timing breakdown.

---

## Launch Server

### Step 9: Start the Server

> 💡 **Recommended:** Use [`manage.sh`](#️-server-management-script-managesh) to run servers in the background while keeping your terminal free for utilities.

#### Production Server — Hypercorn ASGI (Recommended: HTTP/1.1, HTTP/2 and HTTP/3)

```bash
source .venv/bin/activate
python prod_server.py
```

Expected output:
```
🧪 Starting CloudinatorFTP Production Server...
🌐 Server running on https://localhost:5000
```

Protocol servers (WebDAV, SFTP, FTP) start **automatically** alongside the web server — no extra command needed. When they start successfully, you'll additionally see:
```
────────────────────────────────────────────────────────
  CloudinatorFTP — Protocol servers
────────────────────────────────────────────────────────
🔐 WebDAV HTTPS: https://HOST:8443/
🔒 SFTP:         sftp://HOST:2222/
📁 FTP:          ftp://HOST:2121/

  WebDAV    ✅ started
  SFTP      ✅ started
  FTP       ✅ started
────────────────────────────────────────────────────────
```

> A `🌐 WebDAV HTTP: http://HOST:8080/` line only appears when plain-HTTP WebDAV is enabled (HTTPS disabled, or the automatic fallback when the HTTPS certificate can't be prepared).

#### Development Server — Quart (Development/Testing, HTTP/1.1)

```bash
source .venv/bin/activate
python dev_server.py
```

> **Note**: Keep this terminal open or run in the background.

#### Run in Background

```bash
# Recommended: manage.sh (see below)
./manage.sh start server

# Or using nohup
nohup python prod_server.py > server.log 2>&1 &

# Or using screen
screen -S cloudinator
python prod_server.py
# Ctrl+A then D to detach
```

---

## 🖥️ Server Management Script (`manage.sh`)

> 💡 **Recommended:** Use `manage.sh` instead of `nohup`/`screen` — it manages background servers, log files, and utilities from a single command. Full reference: **[MANAGE_SCRIPT_GUIDE.md](./MANAGE_SCRIPT_GUIDE.md)**.

### ⚡ Setup

```bash
chmod +x manage.sh
```

> **Note**: `termux_setup.sh` is for **Android (Termux) only** and is not applicable on Linux. For Linux dependencies, follow the steps above.

### 🚦 Server Commands

> ⚠️ Only one server can run at a time. Attempting to start a second will show a clear status block and stop.

| Command | Description |
|---------|-------------|
| `./manage.sh start server` | Start `prod_server.py` (Hypercorn) in the background |
| `./manage.sh start dev_server` | Start `dev_server.py` (Quart) in the background |
| `./manage.sh stop` | Gracefully stop whichever server is running |
| `./manage.sh restart` | Restart the currently active server |
| `./manage.sh restart-webdav` | Restart only WebDAV (recovers a stuck WebDAV without touching the web UI) |
| `./manage.sh status` | Show server status, PID, uptime, and recent log tail |

### 📋 Log Commands

Logs are always saved to `logs/` regardless of whether you're watching them. Each server start creates a new datetime-stamped file (e.g. `logs/prod_server_2026-06-09_10-32-01.log`).

| Command | Description |
|---------|-------------|
| `./manage.sh logs` | Last 50 lines (auto-detects active server) |
| `./manage.sh logs server` | Last 50 lines of production logs |
| `./manage.sh logs server -f` | Follow live production logs |
| `./manage.sh logs dev_server -f` | Follow live dev logs |
| `./manage.sh clean-logs` | List and delete old log files (asks for confirmation) |

> 💡 **Ctrl-C while following logs detaches your terminal without stopping the server.**

> ℹ️ **Background mode hides startup banners.** `start` discards the server's console output, so messages the code `print()`s at startup (such as the WebDAV certificate hint) only show when you run `python prod_server.py` in the foreground. The log files in `logs/` contain everything that goes through the app's logger.

### 🔧 Utility Commands

Run any utility **while a server is running in the same terminal**:

| Command | Equivalent |
|---------|------------|
| `./manage.sh config` | `python config.py` |
| `./manage.sh manage-users` | `python tools/manage_users.py` |
| `./manage.sh reset-db` | `python tools/reset_db.py` |
| `./manage.sh setup-storage` | `python tools/setup_storage.py` |
| `./manage.sh version-manage` | `python tools/version_manage.py` (Version Engine: list, restore, delete file versions) |
| `./manage.sh setup-smb` | `python tools/smb_setup.py` (one-time SMB setup) |
| `./manage.sh kick-sessions` | `python tools/kick_sessions.py` (force logout of every session; the server must be running) |
| `./manage.sh revoke-shares` | `python tools/revoke_sharing.py` (share link management) |
| `./manage.sh security-txt` | Update `static/.well-known/security.txt` (RFC 9116) |
| `./manage.sh validate-sri [--fix]` | `python tools/sri_validator.py` (check or repair the Subresource Integrity hashes) |
| `./manage.sh update-modules [-y]` | `bash setup_pymodules.sh` (see [Updating Python Dependencies](#-updating-python-dependencies)) |

### Quality Assurance Commands

The automated checks (needs `pip install -r requirements-dev.txt` once). They run in the foreground and are safe while a server is running: the tests use a scratch copy of the project and never touch your data.

| Command | What it runs |
|---------|--------------|
| `./manage.sh qa` or `qa quick` | `smoke.py`, `check.py`, the SRI check, `node --check` on the JavaScript (if Node.js is installed) and every pytest layer |
| `./manage.sh qa static` | Only the static checks (no pytest) |
| `./manage.sh qa tests` | Only pytest |
| `./manage.sh qa layer unit` | One layer: `unit`, `application`, `performance`, ... |
| `./manage.sh qa ci` | Same as `quick`, with JUnit XML in `./artifacts` (what GitHub runs) |

### Developer Tools Commands

Two helpers for people who change the code. They never touch your stored files and need no running server (`dir-tree` rewrites `docs/DIRECTORY_TREE.md`, `smoke --save` rewrites `tests/smoke_routes.json`).

| Command | What it runs |
|---------|--------------|
| `./manage.sh dir-tree` | `python tests/dir_tree.py` (prints the project folder tree and saves it to `docs/DIRECTORY_TREE.md`) |
| `./manage.sh smoke [options]` | `python tests/smoke.py` (fast static checks: syntax, pyflakes, routes, hooks, imports). `--save` writes the route snapshot `tests/smoke_routes.json` (the menu asks y/N first; the shell command does not), `-v` prints the route table, `--files` lists the scanned files |

### 🎛️ Interactive Menu

```bash
./manage.sh menu
```

A numbered menu (27 entries: servers, utilities, quality assurance and developer tools) with live status shown at the top.

### 💡 Typical Workflow

```bash
# 1. Start production server in the background
./manage.sh start server

# 2. Run utilities in the same terminal while the server is up
./manage.sh manage-users
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
bash setup_pymodules.sh   # or: ./manage.sh update-modules
```

Or via `manage.sh` (works on all platforms):

```bash
./manage.sh update-modules
```

The script will:
1. Query PyPI for the latest available version of each package and set a ceiling below the next major version
2. Update `requirements.txt` in place and rewrite `constraints.txt` (on Termux it locks the packages installed with `pkg`)
3. Check with a dry run that the constraints can be resolved together
4. Ask whether to install now: on `y` it creates and activates `.venv` (`.venv/bin` on Linux) and installs the packages there

`requirements-dev.txt` (the test packages) is not touched by the script: install it yourself with `pip install -r requirements-dev.txt`.

> **Linux**: No need to activate anything first, the script does it.

---

## Systemd Service Setup

### Step 10: Create Systemd Service (Optional but Recommended)

This allows automatic startup on boot.

#### Step 10.1: Create Service File

```bash
sudo nano /etc/systemd/system/cloudinator.service
```

#### Step 10.2: Add Service Configuration

```ini
[Unit]
Description=CloudinatorFTP File Sharing Service
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/CloudinatorFTP
Environment="PATH=/home/YOUR_USERNAME/CloudinatorFTP/.venv/bin"
ExecStart=/home/YOUR_USERNAME/CloudinatorFTP/.venv/bin/python prod_server.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

> **Replace `YOUR_USERNAME` with your actual Linux username**

#### Step 10.3: Enable and Start Service

```bash
# Reload systemd daemon
sudo systemctl daemon-reload

# Enable on boot
sudo systemctl enable cloudinator.service

# Start the service
sudo systemctl start cloudinator.service

# Check status
sudo systemctl status cloudinator.service

# View logs
sudo journalctl -u cloudinator.service -f
```

#### Service Management

```bash
# Start service
sudo systemctl start cloudinator.service

# Stop service
sudo systemctl stop cloudinator.service

# Restart service
sudo systemctl restart cloudinator.service

# View live logs
sudo journalctl -u cloudinator.service -f
```

---

## Protocol Servers — WebDAV, SFTP, FTP, SMB

In addition to the web UI, CloudinatorFTP runs additional protocol servers. WebDAV, SFTP and FTP start **automatically** alongside the web server and share the same user database — all use the **same credentials** as the web UI. SMB is disabled until a one-time setup is run; see its own subsection below.

### Port Reference

| Protocol | Port | Default State |
|----------|------|--------------|
| Web UI | 5000 | Always on |
| WebDAV HTTPS | 8443 | Enabled (secure, on by default) |
| WebDAV HTTP | 8080 | Off by default — only listens if HTTPS is disabled (with `WEBDAV_ENABLED` on) or as the automatic fallback when the HTTPS certificate can't be prepared |
| SFTP | 2222 | Enabled |
| FTP | 2121 | Enabled (FTPS enabled by default) |
| FTP passive data | 60000–60100 | (used by FTP) |
| SMB | 445 (8445 fallback) | Disabled until `python tools/smb_setup.py` is run once |

### Firewall Rules

```bash
# UFW (Ubuntu/Debian)
sudo ufw allow 5000/tcp comment "CloudinatorFTP Web UI"
sudo ufw allow 8080/tcp comment "CloudinatorFTP WebDAV HTTP (only if plain-HTTP WebDAV is enabled)"
sudo ufw allow 8443/tcp comment "CloudinatorFTP WebDAV HTTPS"
sudo ufw allow 2222/tcp comment "CloudinatorFTP SFTP"
sudo ufw allow 2121/tcp comment "CloudinatorFTP FTP"
sudo ufw allow 60000:60100/tcp comment "CloudinatorFTP FTP Passive"
sudo ufw allow 445/tcp comment "CloudinatorFTP SMB"
sudo ufw allow 8445/tcp comment "CloudinatorFTP SMB Fallback"

# Firewalld (Fedora/CentOS)
sudo firewall-cmd --add-port=5000/tcp --permanent
sudo firewall-cmd --add-port=8080/tcp --permanent   # only if plain-HTTP WebDAV is enabled
sudo firewall-cmd --add-port=8443/tcp --permanent
sudo firewall-cmd --add-port=2222/tcp --permanent
sudo firewall-cmd --add-port=2121/tcp --permanent
sudo firewall-cmd --add-port=60000-60100/tcp --permanent
sudo firewall-cmd --add-port=445/tcp --permanent
sudo firewall-cmd --add-port=8445/tcp --permanent
sudo firewall-cmd --reload
```

### 🌐 WebDAV — Mount as Filesystem

No browser needed — the server appears as a volume in your file manager.

> The examples below use **HTTPS on port 8443**, which is what runs by default. Plain HTTP on port 8080 is off by default and only listens if HTTPS is disabled (with `WEBDAV_ENABLED` on) or as the automatic fallback when the HTTPS certificate can't be prepared.

#### Option A: davfs2

```bash
# Install davfs2
sudo apt install davfs2   # Ubuntu/Debian
sudo dnf install davfs2   # Fedora
sudo pacman -S davfs2     # Arch

# Trust the server's certificate: copy db/webdav.crt from the server to this
# machine yourself (USB, scp, shared folder...), then:
sudo cp webdav.crt /usr/local/share/ca-certificates/cloudinator.crt
sudo update-ca-certificates

# Mount HTTPS (default)
sudo mount -t davfs https://SERVER-IP:8443/ /mnt/cloudinator

# Mount HTTP (only if plain-HTTP WebDAV is enabled)
sudo mount -t davfs http://SERVER-IP:8080/ /mnt/cloudinator

# Unmount
sudo umount /mnt/cloudinator
```

**Store credentials** (avoid interactive prompt):
```bash
echo "SERVER-IP:8443 admin admin123" >> ~/.davfs2/secrets
chmod 600 ~/.davfs2/secrets
```

**Persistent mount** (`/etc/fstab`):
```
https://SERVER-IP:8443/ /mnt/cloudinator davfs user,auto,_netdev 0 0
```

#### Option B: GNOME Files / Nautilus

Files → Other Locations → Connect to Server:
```
davs://SERVER-IP:8443    (HTTPS, default)
dav://SERVER-IP:8080     (HTTP, only if plain-HTTP WebDAV is enabled)
```

### 🔒 SFTP — Command Line and sshfs

#### Command Line

```bash
sftp -P 2222 admin@SERVER-IP

# Standard sftp commands:
ls, get, put, exit
```

#### sshfs — Mount as Filesystem

```bash
# Install sshfs
sudo apt install sshfs   # Ubuntu/Debian
sudo dnf install fuse-sshfs  # Fedora

# Create mount point
mkdir -p /mnt/cloudinator

# Mount
sshfs -p 2222 admin@SERVER-IP:/ /mnt/cloudinator

# Unmount
fusermount -u /mnt/cloudinator
```

**Persistent mount** (`/etc/fstab`):
```
admin@SERVER-IP:/ /mnt/cloudinator fuse.sshfs port=2222,_netdev,allow_other 0 0
```

> Accept the host key warning on first connect.

### 📁 FTP — Command Line

```bash
# Using lftp (recommended)
lftp -u admin,admin123 -p 2121 SERVER-IP

# Using ftp
ftp SERVER-IP 2121
```

> ⚠️ FTP is plaintext — use on trusted local networks only.

### 📡 SMB — Native Network Drive

Port 445 needs root (a privileged port), so it's disabled by default even with `impacket` installed. Unlike Windows, this is a one-time, **immediate, no-reboot** fix on Linux:

```bash
python tools/smb_setup.py
```

(or `./manage.sh setup-smb`). Detects it isn't root, prints the exact command to run:
```bash
sudo setcap cap_net_bind_service=+ep $(readlink -f $(which python3))
```
Run that once — port 445 works immediately afterward, every future run, no root needed again. If your virtualenv/interpreter path ever changes, re-run it for the new path.

**Mount with cifs-utils:**
```bash
sudo apt install cifs-utils
sudo mount -t cifs //SERVER-IP/SharedFolder /mnt/cloudinator -o username=admin,password=admin123
```

**Before running `smb_setup.py` (port 8445 fallback):**
```bash
sudo mount -t cifs //SERVER-IP/SharedFolder /mnt/cloudinator -o username=admin,password=admin123,port=8445
```

> ⚠️ **Existing users need a one-time password reset** before SMB accepts their login — SMB uses NTLM, which needs a hash of the password that can only be captured the moment it's set. Full details: [SMB_PROTOCOL_DEPLOYMENT.md](./SMB_PROTOCOL_DEPLOYMENT.md).

### 🔄 rclone

rclone can mount, sync, and copy via WebDAV, SFTP, or FTP. See [RCLONE_DEPLOYMENT.md](./RCLONE_DEPLOYMENT.md) for full setup.

```bash
# Quick WebDAV mount (no configuration needed)
rclone mount :webdav,url=https://SERVER-IP:8443/,user=admin,pass=admin123,no_check_certificate=true: /mnt/cloudinator --vfs-cache-mode full
```

### Configure Protocol Servers

```bash
python config.py
# Select option 13: Protocol Servers
```

Or edit `server_config.json`:
```json
{
  "WEBDAV_ENABLED": true,
  "WEBDAV_PORT": 8080,
  "WEBDAV_HTTPS_ENABLED": true,
  "WEBDAV_HTTPS_PORT": 8443,
  "SFTP_ENABLED": true,
  "SFTP_PORT": 2222,
  "FTP_ENABLED": true,
  "FTP_PORT": 2121,
  "SMB_ENABLED": false,
  "SMB_PORT": 445,
  "SMB_FALLBACK_PORT": 8445,
  "SMB_SHARE_NAME": "SharedFolder"
}
```

> WebDAV over HTTPS (8443) is the default. The plain-HTTP server on 8080 only listens if HTTPS is disabled (with `WEBDAV_ENABLED` on) or as the automatic fallback when the HTTPS certificate can't be prepared.

---

## Network Exposure

### Step 11: Expose to the Internet

#### Using Cloudflare Tunnel (Simple)

Open a new terminal session and run — **choose what to tunnel**:

```bash
# Tunnel the web UI (most common)
cloudflared tunnel --url https://localhost:5000

# Or tunnel WebDAV (for remote network drive mapping)
cloudflared tunnel --url https://localhost:8443
```

You'll receive a public URL like:
```
https://random-words-12345.trycloudflare.com
```

> **What port should I tunnel?**
> - `5000` → Web browser access (upload, download, preview via browser)
> - `8443` → WebDAV drive mapping from remote Windows/macOS/Linux machines (HTTPS, the default — use with `--url https://localhost:8443`)
> - `8080` → plain-HTTP WebDAV — **off by default**; it only listens if HTTPS is disabled (with `WEBDAV_ENABLED` on) or as the automatic fallback when the HTTPS certificate can't be prepared
> - Only one port can be tunneled at once with the quick `--url` method. For multiple services, see the [Advanced Tunnel Setup](./SETUP_TUNNEL_ADVANCED.md).
>
> **Note**: SFTP (2222) and FTP (2121) are raw TCP — they work on your local network but cannot be exposed via standard Cloudflare Tunnel. Set up a VPN for remote SFTP/FTP access.

#### Using Custom Domain (Advanced)

For persistent domain setup, see:
[Advanced Cloudflared Tunneling Setup](https://github.com/NeoMatrix14241/CloudinatorFTP/wiki/Advanced-Cloudflare-Tunnelling-Setup)

Then use this configuration for the `config.yml` of cloudflared:

```yaml
tunnel: <tunnel id>
credentials-file: /home/YOUR_USERNAME/.cloudflared/<tunnel id>.json
protocol: quic
ingress:
  - hostname: yourowndomain.com
    service: https://localhost:5000
    originRequest:
      connectTimeout: 0s
      tlsTimeout: 0s
      tcpKeepAlive: 0s
      noTLSVerify: true
      disableChunkedEncoding: false
      keepAliveConnections: 100000000
      keepAliveTimeout: 0s
      proxyConnectTimeout: 0s
      expectContinueTimeout: 0s
  - hostname: files.yourowndomain.com
    service: https://localhost:8443
    originRequest:
      connectTimeout: 0s
      tlsTimeout: 0s
      tcpKeepAlive: 0s
      noTLSVerify: true
      disableChunkedEncoding: false
      keepAliveConnections: 100000000
      keepAliveTimeout: 0s
      proxyConnectTimeout: 0s
      expectContinueTimeout: 0s
  - service: http_status:404
```

#### Firewall Configuration

If you want local network access:

**Allow port 5000 through firewall:**

```bash
# UFW (Ubuntu)
sudo ufw allow 5000/tcp

# Firewalld (Fedora/CentOS)
sudo firewall-cmd --add-port=5000/tcp --permanent
sudo firewall-cmd --reload
```

#### Firewall Configuration for Local Network Access (Protocol Servers)

```bash
# UFW (Ubuntu)
sudo ufw allow 5000/tcp
sudo ufw allow 8080/tcp   # only if plain-HTTP WebDAV is enabled
sudo ufw allow 8443/tcp
sudo ufw allow 2222/tcp
sudo ufw allow 2121/tcp
sudo ufw allow 60000:60100/tcp
sudo ufw allow 445/tcp
sudo ufw allow 8445/tcp
```

---

## Storage Configuration Details

### Recommended Linux Paths

#### Home Directory Paths

```
~/CloudflareFTP           # Simple, user-owned
~/Documents/CloudflareFTP # Organized
~/Downloads/CloudflareFTP # Share downloads
```

#### System Paths (For Servers)

```
/srv/cloudinator/files    # Files storage
/var/lib/cloudinator/db   # Database (secure, out of web)
/var/cache/cloudinator    # Cache directory
```

#### Permission Setup

```bash
# Create directories
sudo mkdir -p /srv/cloudinator/files
sudo mkdir -p /var/lib/cloudinator/db
sudo mkdir -p /var/cache/cloudinator

# Set permissions
sudo chown -R $USER:$USER /srv/cloudinator
sudo chown -R $USER:$USER /var/lib/cloudinator
sudo chown -R $USER:$USER /var/cache/cloudinator

# Set proper permissions
sudo chmod 750 /var/lib/cloudinator/db
sudo chmod 755 /srv/cloudinator/files
```

---

## Troubleshooting

### Installation Issues

| Issue | Solution |
|-------|----------|
| Python 3.14.3+ not found | Your distribution may ship an older Python — install 3.14.3+ from python.org or with `pyenv`/`uv`, then check `python3 --version` |
| `pip` command not found | Install: `sudo apt install python3-pip` |
| Permission denied | Use `sudo` or check file permissions |
| libvips not found | Install development headers: `sudo apt install libvips-dev` |

### Protocol Server Issues

| Issue | Solution |
|-------|----------|
| WebDAV not starting | `pip install wsgidav cheroot` |
| SFTP not starting | `pip install paramiko` |
| FTP not starting | `pip install pyftpdlib` |
| davfs2 permission denied | Run `sudo mount` or add user to `davfs2` group |
| sshfs connection refused | Verify port 2222 open: `nc -zv SERVER-IP 2222` |
| FTP transfers stall | Open ports 60000-60100: `sudo ufw allow 60000:60100/tcp` |
| Certificate errors (HTTPS WebDAV) | `sudo cp db/webdav.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates` |
| Nothing listens on port 8080 | Expected — plain-HTTP WebDAV is off by default. Use `https://SERVER-IP:8443/` instead |
| SMB won't bind port 445 | Run `python tools/smb_setup.py` (or `./manage.sh setup-smb`) once, then `sudo setcap cap_net_bind_service=+ep $(readlink -f $(which python3))` if it printed that command |
| SMB login fails for an existing user | Reset their password once — see [SMB_PROTOCOL_DEPLOYMENT.md](./SMB_PROTOCOL_DEPLOYMENT.md) |
| `setcap` command not found | `sudo apt install libcap2-bin` |

### Virtual Environment Issues

| Issue | Solution |
|-------|----------|
| `.venv` not found | Run: `python3 -m venv .venv` |
| Can't activate venv | Run: `source .venv/bin/activate` (exact path) |
| Permission denied on venv | Check: `ls -la .venv/bin/` |
| Wrong Python version | Use: `python3 -m venv .venv` explicitly (needs 3.14.3+) |

### Dependency Installation

| Issue | Solution |
|-------|----------|
| `bcrypt` fails to build | Install: `sudo apt install build-essential python3-dev` |
| `cryptography` fails | Install: `sudo apt install libssl-dev libffi-dev` |
| `pyvips` not working | Install: `sudo apt install libvips-dev` |

### Server Issues

| Issue | Solution |
|-------|----------|
| Port 5000 in use | Kill process: `lsof -i :5000` then `kill -9 PID` |
| Server won't start | Check logs: `./manage.sh logs` |
| High CPU usage | Reduce HLS in `config.py`, check file count |
| Out of memory | Check: `free -h`, reduce chunk size |

### Database Issues

| Issue | Solution |
|-------|----------|
| Login fails | Run: `python tools/manage_users.py` (list users / change password) |
| Looping web refresh | Run: `python tools/kick_sessions.py logout-web` |
| Locked out after failed logins | After 5 failed logins a client is locked out for 5 minutes — wait, then retry |
| Database corrupted | Run: `python tools/reset_db.py` (destructive: recreates the default accounts) |
| Users not found | Check DB path: `ls -la /var/lib/cloudinator/db/` |

### Cloudflare Tunnel Issues

| Issue | Solution |
|-------|----------|
| Tunnel disconnects | Keep tunnel running, check internet |
| DNS issues | Verify domain is on Cloudflare |
| Connection timeout | Check firewall, server status |

### Permission Issues

| Issue | Solution |
|-------|----------|
| Can't write to storage | Check ownership: `ls -la /srv/cloudinator` |
| Can't read files | Set permissions: `chmod 755` on directories |
| Systemd service fails | Check user in service file, check paths |

---

## Performance Optimization

### Increase File Descriptor Limit

```bash
# Temporary
ulimit -n 4096

# Permanent (add to ~/.bashrc or ~/.profile)
echo "ulimit -n 4096" >> ~/.bashrc
source ~/.bashrc
```

### Tune Systemd Service

For better performance, add to service file:

```ini
[Service]
# ... existing config ...
LimitNOFILE=65536
LimitNPROC=4096
CPUQuota=80%
MemoryLimit=2G
```

### Enable Compression

Use `python config.py` (settings saved to `server_config.json` override the built-in defaults in `config.py`), or adjust:

```python
IMG_COMPRESS_MIN_SIZE = 1 * 1024 * 1024  # 1 MB
IMG_WEBP_QUALITY = 50  # 1-100
```

---

## Monitoring

### Check Server Status

```bash
# Using systemctl
sudo systemctl status cloudinator.service

# Using curl (if running locally; -k accepts the local certificate)
curl -k https://localhost:5000

# Check port
netstat -tlnp | grep 5000
```

### View Logs

```bash
# Real-time logs
sudo journalctl -u cloudinator.service -f

# Last 100 lines
sudo journalctl -u cloudinator.service -n 100

# Today's logs
sudo journalctl -u cloudinator.service --since today
```

### Monitor Resource Usage

```bash
# CPU and Memory
top

# Disk usage
df -h

# File descriptor usage
lsof -p $(pgrep -f "python prod_server.py")
```

---

## Next Steps

1. ✅ Installation complete
2. 🌐 WebDAV accessible over HTTPS at port 8443 (8080 only if plain HTTP is enabled)
3. 🔒 SFTP accessible at port 2222
4. 📁 FTP accessible at port 2121
5. 📡 SMB — run `python tools/smb_setup.py` if you want native port 445 mapping (optional)
6. 📤 Get your Cloudflare tunnel URL
7. 🔐 Change default passwords
8. 👥 Add users for team members
9. 🌍 Share the URL
10. 📊 Monitor performance

---

## Additional Resources

- [Python Virtual Environments](https://docs.python.org/3/tutorial/venv.html)
- [Systemd Documentation](https://systemd.io/)
- [Cloudflare Tunnel Docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-applications/)
- [davfs2 Manual](http://savannah.nongnu.org/projects/davfs2)
- [sshfs Documentation](https://github.com/libfuse/sshfs)
- [Project GitHub](https://github.com/NeoMatrix14241/CloudinatorFTP)
- [rclone Integration](./RCLONE_DEPLOYMENT.md)
- [SMB Protocol Setup](./SMB_PROTOCOL_DEPLOYMENT.md)
- [manage.sh Guide](./MANAGE_SCRIPT_GUIDE.md)
- [Configuration Reference](./CONFIG_PY_REFERENCE.md)
- [Advanced Tunnel Setup](./SETUP_TUNNEL_ADVANCED.md)
- [User Guide](./USER_GUIDE.md)

---

## Support

- 🐛 Found a bug? [GitHub Issues](https://github.com/NeoMatrix14241/CloudinatorFTP/issues)
- 💡 Feature requests? [GitHub Discussions](https://github.com/NeoMatrix14241/CloudinatorFTP/discussions)
- 📚 Need help? Check this guide's troubleshooting section

---