# 🪟 CloudinatorFTP Windows Deployment Guide

A comprehensive guide to deploy CloudinatorFTP on Windows systems, enabling file sharing with Cloudflare tunnel integration and optional Apache WSGI deployment.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [System Requirements](#system-requirements)
3. [Python Installation](#python-installation)
4. [Dependency Installation](#dependency-installation)
5. [Project Setup](#project-setup)
6. [Virtual Environment](#virtual-environment)
7. [Configuration](#configuration)
8. [User Management](#user-management)
9. [Launch Server](#launch-server)
10. [Server Management Script (manage.sh)](#️-server-management-script-managesh)
11. [Updating Python Dependencies](#-updating-python-dependencies)
12. [Launcher Shortcut Setup](#launcher-shortcut-setup)
13. [Windows Service Setup](#windows-service-setup)
14. [Protocol Servers — WebDAV, SFTP, FTP, SMB](#protocol-servers--webdav-sftp-ftp-smb)
15. [Cloudflare Tunnel](#cloudflare-tunnel)
16. [Apache/WSGI Deployment](#apachewsgi-deployment-optional)
17. [Storage Configuration](#storage-configuration-details)
18. [Firewall Configuration](#firewall-configuration)
19. [Troubleshooting](#troubleshooting)
20. [Performance Tips](#performance-tips)

---

## Prerequisites

- **Windows Version**: Windows 10 1909+, Windows 11, Windows Server 2019+
- **Administrator Access**: Required for installation
- **Python 3.14.3+** and pip
- **Git** (Git for Windows also provides Git Bash, which runs `manage.sh`)
- **libvips**
- **FFmpeg** (optional)
- **Internet Connection**
- **Basic Command-Line Knowledge** (Windows Terminal, PowerShell, or Command Prompt)

### Tested Versions

- ✅ Windows 10 (Version 1909+)
- ✅ Windows 10 22H2 (Build 19045) — the deployment used for the README's tunnel security scans
- ✅ Windows 11
- ✅ Windows Server 2019, 2022

---

## System Requirements

### Minimum Specifications

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 2 Cores | 4+ Cores |
| **RAM** | 2 GB | 4 GB + |
| **Storage** | 2 GB | 20 GB + |
| **Python** | 3.14.3 | 3.14.3+ |

---

## Python Installation

### Step 1: Download and Install Python

1. Visit [python.org](https://www.python.org/downloads/)
2. Download **Python 3.14.3+** for Windows
3. Run the installer

#### Installation Option (Important!)

⚠️ **Check "Add Python to PATH"** ⚠️

During installation:

- ✅ Check: **"Add Python 3.x to PATH"**
- ✅ Check: **"Install pip"**
- ✅ Check: **"Install for all users"** (recommended)

### Step 2: Verify Installation

Open Command Prompt (Win+R, type `cmd`) and run:

```cmd
python --version
pip --version
```

Expected output:
```
Python 3.14.x
pip XX.X (python 3.14)
```

### Step 3: Upgrade pip

```cmd
python -m pip install --upgrade pip
```

---

## Dependency Installation

### Tools and Versions

| Tool | Version | Required? |
|------|---------|-----------|
| [Python](https://www.python.org/downloads/) | 3.14.3+ | ✅ Required |
| [Git](https://git-scm.com/) | Latest version/build | ✅ Required |
| [libvips](https://www.libvips.org/) | v8.18.1 | ✅ Required |
| [FFmpeg](https://www.ffmpeg.org/) | Essentials v57 build 2026-03-19 | Optional — adaptive bitrate video preview with [Video.js](https://videojs.org/) |
| [Node.js](https://nodejs.org/en) | v24.22.0 LTS | Optional — only used by `./manage.sh qa` to syntax-check the JavaScript |
| [cloudflared](https://github.com/cloudflare/cloudflared/releases) | Latest | Optional — exposing the server to the internet |

The web UI also uses [Video.js](https://videojs.org/) v10, [PDF.js](https://mozilla.github.io/pdf.js/) v3.11.174 and [Font Awesome](https://fontawesome.com/) v7.2.0 — there is nothing to install for these.

### Step 1: Install Git

1. Download from [git-scm.com](https://git-scm.com/download/win)
2. Run installer using defaults
3. Verify:

```cmd
git --version
```

### Step 2: Install FFmpeg (Optional but Recommended)

FFmpeg is optional. It enables adaptive bitrate video preview with [Video.js](https://videojs.org/) (video streaming and format conversion).

#### Option A: Direct Download

1. Download from [gyan.dev/ffmpeg](https://www.gyan.dev/ffmpeg/builds/)
2. Choose the **"essentials" build** (the README lists FFmpeg Essentials v57, build 2026-03-19)
3. Extract to: `C:\ffmpeg`
4. Add to PATH:
   - Win+R → `sysdm.cpl`
   - Advanced tab → Environment Variables
   - Click "New" under System Variables
   - Variable name: `FFMPEG_HOME`
   - Variable value: `C:\ffmpeg`
   - Add to PATH: `%FFMPEG_HOME%\bin`

#### Option B: Using Package Manager

```cmd
# Using Chocolatey (if installed)
choco install ffmpeg

# Or using scoop
scoop install ffmpeg
```

### Step 3: Install libvips

libvips is listed as a prerequisite in the README. It powers image optimization and WebP compression.

#### Option A: Pre-built Binary

1. Download from [libvips releases](https://github.com/libvips/libvips/releases)
2. Extract to: `C:\libvips`
3. Add to PATH: `C:\libvips\bin`

#### Option B: Using Chocolatey

```cmd
choco install vips
```

### Step 4: Install Cloudflare Tunnel

For exposing your server to the internet:

```cmd
# Download
powershell -Command "(New-Object System.Net.ServicePointManager).SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; (New-Object System.Net.WebClient).DownloadFile('https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe', 'C:\Server
Cloudflared\cloudflared.exe')"

# Move to Program Files
move C:\cloudflared.exe "C:\Program Files\cloudflared\cloudflared.exe"
```

Or download manually from [Cloudflare Releases](https://github.com/cloudflare/cloudflared/releases)

### Step 4b: Install Node.js (Optional)

Only needed if you modify the code and run the QA checks: `./manage.sh qa` runs `node --check` on the JavaScript when Node.js is installed. Download the **v24 LTS** build from [nodejs.org](https://nodejs.org/en) and verify:

```cmd
node --version
```

---

## Project Setup

### Step 5: Clone the Repository

#### Open Command Prompt or PowerShell

Press `Win+R`, type `cmd` or `pwsh`

#### Clone Stable Release

```cmd
git clone https://github.com/NeoMatrix14241/CloudinatorFTP.git
cd CloudinatorFTP
```

#### Clone Development Branch

```cmd
git clone -b dev https://github.com/NeoMatrix14241/CloudinatorFTP.git
cd CloudinatorFTP
```

---

## Virtual Environment

### Step 6: Create and Activate Virtual Environment

#### Create Virtual Environment

```cmd
python -m venv .venv
```

#### Activate Virtual Environment

**Command Prompt:**
```cmd
.venv\Scripts\activate.bat
```

**PowerShell:**
```powershell
.venv\Scripts\Activate.ps1
```

**Git Bash:**
```bash
source ./.venv/Scripts/activate
```

> **Note**: You'll see `(.venv)` in your prompt when activated.

> **Note**: In Git Bash the activation script must be **sourced** (`source ...`). Running `./.venv/Scripts/activate` on its own starts a subshell and activates nothing. Windows virtual environments keep their scripts in `.venv/Scripts`. `bash setup_pymodules.sh` (or `./manage.sh update-modules`) creates and activates `.venv` for you when you answer `y`.

#### Deactivate (When Done)

```cmd
deactivate
```

---

## Configuration

### Step 7.1: Install Python Dependencies

```cmd
# Ensure virtual environment is activated
.venv\Scripts\activate.bat

# Main requirements
pip install -r requirements.txt

# Dev only (optional) - if you will modify the code and run the tests
pip install -r requirements-dev.txt
```

> **If bcrypt fails**, install build tools first:
> ```cmd
> pip install --upgrade setuptools wheel
> pip install -r requirements.txt
> ```

### Step 7.1b: Install Protocol Server Dependencies (Optional)

The WebDAV, SFTP, FTP, and SMB servers use the libraries below. Most are already pulled in by `requirements.txt`; if a protocol server reports a missing package at startup, install it with:

```cmd
pip install wsgidav cheroot paramiko pyftpdlib impacket
```

| Package | Protocol | Purpose |
|---------|----------|---------|
| `wsgidav` | WebDAV | WebDAV WSGI server (HTTPS on port 8443 by default) |
| `cheroot` | WebDAV HTTPS | WSGI server with TLS support |
| `paramiko` | SFTP | SSH/SFTP implementation (port 2222) |
| `pyftpdlib` | FTP | FTP server (port 2121) |
| `impacket` | SMB | SMB server (the only pure-Python option that exists) |

> **Note**: These are optional. If any are missing, only that protocol server is skipped on startup, with an install hint. The web UI always starts regardless.

> ⚠️ **`impacket` and antivirus**: Windows Defender commonly flags parts of `impacket` heuristically (it's also a component of some pentesting toolkits — `impacket.smbserver` itself does nothing malicious). You'll likely see an error like `[Errno 22] Invalid argument: '...impacket\dcerpc\v5\epm.py'` on first run. Fix: add a Defender exclusion for impacket's install folder, then `pip install impacket --no-cache-dir` if files were already quarantined. Full details: [SMB_PROTOCOL_DEPLOYMENT.md](./SMB_PROTOCOL_DEPLOYMENT.md).

### Step 7.2: Configure Storage Location

```cmd
python tools/setup_storage.py
```

Follow the prompts to set:
- **Files Directory**: Where uploaded files are stored
- **Database Directory**: SQLite database
- **Cache Directory**: Temporary files and index

#### Recommended Storage Paths

| Component | Path | Why |
|-----------|------|-----|
| **Files** | `C:\CloudinatorFTP\Files` | Simple, easy backup |
| **Files** | `%USERPROFILE%\Documents\CloudflareFTP` | User Documents |
| **Files** | `%USERPROFILE%\Downloads\CloudflareFTP` | Share Downloads |
| **Files** | `%USERPROFILE%\Desktop\CloudflareFTP` | Quick access from the Desktop |
| **Database** | `C:\Server\config\db` | Secure location |
| **Cache** | `C:\Server\config\cache` | System cache |

### Step 7.3: Advanced Configuration (Optional)

```cmd
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

- `static\.well-known\security.txt` — use your own details (security contact, RFC 9116)
- `static\robots.txt` — by default, everything is blocked politely

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

#### Default Users (Automatic)

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | readwrite |
| `guest` | `guest123` | readonly |

> 🚨 **Change these passwords immediately!**

#### Add/Modify Users

```cmd
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

#### Check a Login

The old `debug_passwords.py` tester was removed in 4.80. If you're having login issues, list the users and change the password if needed:

```cmd
python tools/manage_users.py
```

Then choose **1** (List users, which flags accounts that still have a default password) or **3** (Change password).

This tool helps:
- See which accounts exist, their role and last login (and which still use a default password)
- Set a new password for an account you are locked out of
- Fix a wrong role, or remove the default accounts

> After 5 failed logins a client is locked out for 5 minutes, so wait for the lockout to end before trying again.

#### Revoke Access Quickly (Security Incident)

```cmd
python tools/kick_sessions.py
```

Interactive tool for "something's wrong, lock this person out now" situations — rotate a password, delete a user, or log everyone out of the web UI instantly. If the web UI is stuck in a looping refresh, run `python tools/kick_sessions.py logout-web`. See [SMB_PROTOCOL_DEPLOYMENT.md](./SMB_PROTOCOL_DEPLOYMENT.md) for the timing breakdown per protocol (some are instant, some take up to ~30 seconds, none can forcibly close a connection that's already open).

---

## Launch Server

### Step 9: Start the Server

> 💡 **Recommended for Windows:** Use [`manage.sh`](#️-server-management-script-managesh) (Method 2) to run servers in the background while keeping your terminal free for utilities.

#### Method 1: Command Prompt

**Production Server — Hypercorn ASGI (recommended; HTTP/1.1, HTTP/2 and HTTP/3):**
```cmd
.venv\Scripts\activate.bat
python prod_server.py
```

**Development Server — Quart (development/testing; HTTP/1.1):**
```cmd
.venv\Scripts\activate.bat
python dev_server.py
```

#### Method 2: manage.sh (Git Bash, runs in the background)

**Production:**
```bash
./manage.sh start server
```

**Development:**
```bash
./manage.sh start dev_server
```

See [Server Management Script](#️-server-management-script-managesh) below. (The `start_prod_server.bat` / `start_dev_server.bat` files that older versions shipped were removed in 4.80; see [Launcher Shortcut Setup](#launcher-shortcut-setup) if you want a double-click launcher of your own.)

Protocol servers (WebDAV, SFTP, FTP) start **automatically** alongside the web server — no extra command needed.

### Expected Startup Output

When the protocol servers start successfully (foreground run):
```
────────────────────────────────────────────────────────
  CloudinatorFTP — Protocol servers
────────────────────────────────────────────────────────
🔐 WebDAV HTTPS: https://HOST:8443/
🔒 SFTP:         sftp://HOST:2222/
📁 FTP:          ftp://HOST:2121/
📡 SMB:          \\HOST\SharedFolder  (port 8445 fallback until smb_setup.py has been run)

  WebDAV    ✅ started
  SFTP      ✅ started
  FTP       ✅ started
  SMB       — disabled by default; see SMB_PROTOCOL_DEPLOYMENT.md
────────────────────────────────────────────────────────
```

> A `🌐 WebDAV HTTP: http://HOST:8080/` line only appears when plain-HTTP WebDAV is enabled (HTTPS disabled, or the automatic fallback when the HTTPS certificate can't be prepared).

> ℹ️ **Background mode hides startup banners.** `./manage.sh start` discards the server's console output, so banners like this one only show when you run `python prod_server.py` in the foreground. The log files in `logs/` contain everything that goes through the app's logger.

> **Keep terminal open while server is running** (Method 1)

---

## 🖥️ Server Management Script (`manage.sh`)

> 💡 **Recommended for Windows:** Use `manage.sh` from **Git Bash** to run servers in the background while keeping your terminal free for utilities — no separate window or batch file needed. Full reference: **[MANAGE_SCRIPT_GUIDE.md](./MANAGE_SCRIPT_GUIDE.md)**.

### ⚡ Setup (Git Bash)

```bash
chmod +x manage.sh
```

> **Note**: `termux_setup.sh` is for **Android (Termux) only** and is not applicable on Windows. Use the Python/pip installation steps above instead.

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

> 💡 **Ctrl-C while following logs detaches your terminal without stopping the server.** The server runs as a fully detached Windows process (`CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`), so Ctrl-C never reaches it.

> ℹ️ **Background mode hides startup banners.** `start` discards the server's console output, so messages the code `print()`s at startup (such as the WebDAV certificate hint) only show when you run `python prod_server.py` in the foreground. The log files in `logs/` contain everything that goes through the app's logger.

### 🔧 Utility Commands

Run any utility **while a server is running in the same Git Bash window**:

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

### 💡 Typical Workflow (Git Bash)

```bash
# 1. Start production server in the background
./manage.sh start server

# 2. Run utilities in the same Git Bash window while the server is up
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
4. Ask whether to install now: on `y` it creates and activates `.venv` (`.venv/Scripts` on Windows Git Bash) and installs the packages there

`requirements-dev.txt` (the test packages) is not touched by the script: install it yourself with `pip install -r requirements-dev.txt`.

> **Windows**: Run in Git Bash, or double-click if you have a `.bat` wrapper.
> The script creates and activates `.venv` for you when you answer `y`, so you don't need to activate anything first.

---

## Launcher Shortcut Setup

### Step 10: Optional Double-Click Launcher

Older versions shipped `start_prod_server.bat` and `start_dev_server.bat`. They were removed in 4.80: start the server with `python prod_server.py` (Method 1) or `./manage.sh start server` (Method 2) instead.

If you still want a launcher you can double-click, create your own `start_server.bat` in the project folder:

```bat
@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python prod_server.py
pause
```

(The old scripts could restart the server after an error; this one does not. For automatic restarts use NSSM (Option A below) or the Task Scheduler "restart on failure" setting.)

**Create a desktop shortcut to it:**
1. Right-click `start_server.bat`
2. "Create shortcut"
3. Move shortcut to Desktop
4. Right-click shortcut → "Properties"
5. Change "Start in" to project directory

---

## Windows Service Setup

### Step 11: Run as Windows Service (Optional)

This allows the server to start automatically on boot.

#### Option A: Using NSSM (Non-Sucking Service Manager)

**Install NSSM:**
```cmd
# Download
powershell -Command "(New-Object System.Net.WebClient).DownloadFile('https://nssm.cc/release/nssm-2.24-101-g897c7f7.zip', 'nssm.zip')"

# Extract
powershell -Command "Expand-Archive nssm.zip"

# Copy to Program Files
xcopy nssm\nssm-*\win64\nssm.exe "C:\Program Files\nssm\" /Y
```

**Create Service:**
```cmd
# Run as Administrator
nssm install CloudinatorFTP "C:\path\to\CloudinatorFTP\.venv\Scripts\python.exe" "prod_server.py"
nssm set CloudinatorFTP AppDirectory "C:\path\to\CloudinatorFTP"
nssm set CloudinatorFTP AppRotate 1
nssm start CloudinatorFTP
```

**Manage Service:**
```cmd
# Start
nssm start CloudinatorFTP

# Stop
nssm stop CloudinatorFTP

# Restart
nssm restart CloudinatorFTP

# Remove
nssm remove CloudinatorFTP confirm
```

#### Option B: Using Task Scheduler

1. Press `Win+R`, type `taskschd.msc`
2. Click "Create Basic Task"
3. **Name**: CloudinatorFTP
4. **Trigger**: At startup
5. **Action**: Start a program
   - Program: `C:\path\to\CloudinatorFTP\.venv\Scripts\python.exe`
   - Add arguments: `prod_server.py`
   - Start in: `C:\path\to\CloudinatorFTP`
6. Click "Finish"
7. Open the task's Properties → **Settings** and tick "If the task fails, restart every" (1 minute) so it restarts after an error

---

## Protocol Servers — WebDAV, SFTP, FTP, SMB

In addition to the web UI, CloudinatorFTP runs additional protocol servers. WebDAV, SFTP and FTP start **automatically** alongside the web server when you run `prod_server.py` or `dev_server.py` — no extra commands needed. They all use the **same credentials** as the web UI. SMB is the one exception — it's disabled by default until a one-time setup is run; see its own subsection below.

### Port Overview

| Service | Port | Best For |
|---------|------|----------|
| 🌐 Web UI | 5000 | Browser-based file management |
| 🔐 WebDAV HTTPS | 8443 | Native drive mapping (secure, on by default) |
| 📂 WebDAV HTTP | 8080 | Plaintext fallback — off by default (see the note under WebDAV below) |
| 🔒 SFTP | 2222 | WinSCP, FileZilla, sshfs |
| 📁 FTP | 2121 | Legacy FTP clients (LAN only) |
| 📡 SMB | 445 (8445 fallback) | Native network drive — disabled until set up once (see below) |

### Firewall Rules (Required for Remote Access)

Open an **elevated PowerShell** and run once:

```powershell
# Web UI (if not already open)
New-NetFirewallRule -DisplayName "CloudinatorFTP Web UI"      -Direction Inbound -Protocol TCP -LocalPort 5000        -Action Allow

# WebDAV HTTP (only if plain-HTTP WebDAV is enabled)
New-NetFirewallRule -DisplayName "CloudinatorFTP WebDAV HTTP" -Direction Inbound -Protocol TCP -LocalPort 8080        -Action Allow

# WebDAV HTTPS
New-NetFirewallRule -DisplayName "CloudinatorFTP WebDAV HTTPS"-Direction Inbound -Protocol TCP -LocalPort 8443        -Action Allow

# SFTP
New-NetFirewallRule -DisplayName "CloudinatorFTP SFTP"        -Direction Inbound -Protocol TCP -LocalPort 2222        -Action Allow

# FTP control channel
New-NetFirewallRule -DisplayName "CloudinatorFTP FTP"         -Direction Inbound -Protocol TCP -LocalPort 2121        -Action Allow

# FTP passive data ports (required for file transfers)
New-NetFirewallRule -DisplayName "CloudinatorFTP FTP Passive" -Direction Inbound -Protocol TCP -LocalPort 60000-60100 -Action Allow

# SMB (445 only usable after smb_setup — see its subsection below; 8445 fallback works either way)
New-NetFirewallRule -DisplayName "CloudinatorFTP SMB"         -Direction Inbound -Protocol TCP -LocalPort 445         -Action Allow
New-NetFirewallRule -DisplayName "CloudinatorFTP SMB Fallback"-Direction Inbound -Protocol TCP -LocalPort 8445        -Action Allow
```

Verify connectivity from another machine:
```powershell
Test-NetConnection -ComputerName SERVER-IP -Port 5000
Test-NetConnection -ComputerName SERVER-IP -Port 8443
Test-NetConnection -ComputerName SERVER-IP -Port 2222
Test-NetConnection -ComputerName SERVER-IP -Port 2121
```

### 🌐 WebDAV — Map as Network Drive

WebDAV lets you mount CloudinatorFTP as a Windows drive letter — drag and drop files in File Explorer without a browser.

> The examples below use **HTTPS on port 8443**, which is what runs by default. Plain HTTP on port 8080 is off by default and only listens if HTTPS is disabled (with `WEBDAV_ENABLED` on) or as the automatic fallback when the HTTPS certificate can't be prepared.

#### Option A: HTTPS (Recommended — No Registry Edit)

**Import the certificate once** (elevated PowerShell, run on each client PC):
```powershell
# 1. Get the certificate. Simplest and safest: copy db/webdav.crt from the server
#    to this PC yourself (USB, scp, shared folder...), then import it:
Import-Certificate -FilePath "C:\path\to\webdav.crt" -CertStoreLocation Cert:\LocalMachine\Root

# Alternative: download it from the server's HTTPS port. The cert isn't trusted yet,
# so the download has to skip verification (curl.exe is bundled with current Windows 10/11).
# This is trust-on-first-use - only do it on a network you trust.
curl.exe -k -o "$env:TEMP\webdav.crt" https://SERVER-IP:8443/webdav.crt
Import-Certificate -FilePath "$env:TEMP\webdav.crt" -CertStoreLocation Cert:\LocalMachine\Root
```

**Map the drive:**
```cmd
net use X: https://SERVER-IP:8443/ /user:admin admin123 /persistent:yes
```

#### Option B: HTTP (Only if plain-HTTP WebDAV is enabled; requires one registry edit)

**Enable HTTP WebDAV** (elevated PowerShell, once per PC):
```powershell
Set-Service WebClient -StartupType Automatic; Start-Service WebClient
reg add "HKLM\SYSTEM\CurrentControlSet\Services\WebClient\Parameters" /v BasicAuthLevel /t REG_DWORD /d 2 /f
Restart-Service WebClient
```

**If WebClient is not installed** (Windows Server):
```powershell
Install-WindowsFeature WebDAV-Redirector
Restart-Computer
# After reboot:
Set-Service WebClient -StartupType Automatic; Start-Service WebClient
```

**Map the drive:**
```cmd
net use X: http://SERVER-IP:8080/ /user:admin admin123 /persistent:yes
```

**Disconnect:**
```cmd
net use X: /delete
```

> ⚠️ **UAC note**: Run `net use` in a **non-elevated** terminal. If you map in an elevated window, the drive won't appear in regular File Explorer.

### 🔒 SFTP — WinSCP Setup

1. Open WinSCP → New Session
2. **File protocol**: SFTP
3. **Host name**: server IP
4. **Port number**: `2222`
5. **User name / Password**: your Cloudinator credentials (same as the web UI)
6. Click **Login**
7. **First connection**: click **Accept** when the host key warning appears

### 📁 FTP — WinSCP Setup

1. Open WinSCP → New Session
2. **File protocol**: FTP
3. **Encryption**: No encryption
4. **Host name**: server IP
5. **Port number**: `2121`
6. **User name / Password**: credentials (same as the web UI)
7. Click Login

> ⚠️ FTP is plaintext — use on trusted local networks only.

### 📡 SMB — Native Network Drive

Unlike WebDAV/SFTP/FTP, SMB needs a **one-time machine setup** before it's usable — port 445 is normally occupied by Windows' own file-sharing service. Until that setup is done, SMB automatically falls back to port 8445.

**One-time setup:**
```cmd
python tools/smb_setup.py
```
(or `./manage.sh setup-smb` from Git Bash). Confirms, requests elevation (one UAC prompt), stops Windows' native file sharing, and tells you to restart — it never reboots the machine for you. Full walkthrough, including the antivirus exclusion and per-platform details: [SMB_PROTOCOL_DEPLOYMENT.md](./SMB_PROTOCOL_DEPLOYMENT.md).

**After setup + restart, map the drive:**
```cmd
net use X: \\SERVER-IP\SharedFolder /persistent:yes
```

**Before setup (port 8445 fallback)** — only Windows 11 24H2+ / Server 2025+ can map a non-445 SMB share natively:
```cmd
net use X: \\SERVER-IP\SharedFolder /TCPPORT:8445 /persistent:yes
```

> ⚠️ **Existing users need a one-time password reset** before SMB accepts their login — SMB uses NTLM, which needs a special hash of the password that can only be captured the moment it's set. New users created after `impacket` was installed don't need this.

### 🔄 rclone

rclone can mount, sync, and copy via WebDAV, SFTP, or FTP. See [RCLONE_DEPLOYMENT.md](./RCLONE_DEPLOYMENT.md) for full setup.

```powershell
# Quick WebDAV mount (no configuration needed)
rclone mount :webdav,url=https://SERVER-IP:8443/,user=admin,pass=admin123,no_check_certificate=true: Z: --vfs-cache-mode full
```

### Configure / Disable Individual Protocols

```cmd
python config.py
# Select option 13: Protocol Servers
# Toggle each server on/off or change ports
```

Or edit `server_config.json` directly:
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

## Cloudflare Tunnel

### Step 12: Expose to the Internet

#### Simple Tunnel (Easiest)

Open a new Command Prompt and run — **choose what to tunnel**:

Tunnel the web UI (most common):
```cmd
cloudflared tunnel --url https://localhost:5000
```

Or tunnel WebDAV (for remote network drive mapping):
```cmd
cloudflared tunnel --url https://localhost:8443
```

You'll receive a public URL like:
```
https://random-words-12345.trycloudflare.com
```

✨ Access your server from anywhere!

> **What port should I tunnel?**
> - `5000` → Web browser access (upload, download, preview via browser)
> - `8443` → WebDAV drive mapping from remote Windows/macOS/Linux machines (HTTPS, the default — use with `--url https://localhost:8443`)
> - `8080` → plain-HTTP WebDAV — **off by default**; it only listens if HTTPS is disabled (with `WEBDAV_ENABLED` on) or as the automatic fallback when the HTTPS certificate can't be prepared
> - Only one port can be tunneled at once with the quick `--url` method. For multiple services, see the [Advanced Tunnel Setup](./SETUP_TUNNEL_ADVANCED.md).
>
> **Note**: SFTP (2222) and FTP (2121) are raw TCP — they work on your local network but cannot be exposed via standard Cloudflare Tunnel. Use a VPN for remote SFTP/FTP access.

#### Custom Domain (Advanced)

See: [Advanced Cloudflared Tunnel Setup](https://github.com/NeoMatrix14241/CloudinatorFTP/wiki/Advanced-Cloudflare-Tunnelling-Setup)

Then use this configuration for the `config.yml` of cloudflared:

```yaml
tunnel: <tunnel id>
credentials-file: C:\Users\%username%\.cloudflared\<tunnel id>.json
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

---

## Apache/WSGI Deployment (Optional)

### Step 13: Production Deployment with Apache

For production environments, Apache with mod_wsgi is recommended.

> ℹ️ The web app now runs on Quart/Hypercorn (ASGI). **[DEPLOY_APACHE.md](./DEPLOY_APACHE.md) is the maintained reference** for Apache/mod_wsgi; the quick steps below were written for the older Flask-based app and may need adjusting.

#### Prerequisites

- XAMPP with Apache installed
- mod_wsgi installed
- Python virtual environment set up

#### Step 13.1: Install mod_wsgi

```cmd
.venv\Scripts\activate.bat
pip install mod_wsgi
```

#### Step 13.2: Get mod_wsgi Configuration

```cmd
mod_wsgi-express module-config
```

Copy the output for Apache configuration.

#### Step 13.3: Create WSGI File

Create `myflaskapp.wsgi` in project root:

```python
import os
import sys

# Add project path
sys.path.insert(0, os.path.dirname(__file__))

# Activate virtual environment
venv_path = os.path.join(os.path.dirname(__file__), '.venv')
activate_this = os.path.join(venv_path, 'Scripts', 'activate_this.py')
exec(open(activate_this).read(), {'__file__': activate_this})

# Import the app (see DEPLOY_APACHE.md for the current entry point)
from app import app as application
```

#### Step 13.4: Configure Apache

Edit `httpd.conf` in XAMPP:

```apache
# Add mod_wsgi module (from mod_wsgi-express module-config output)
LoadModule wsgi_module modules/mod_wsgi.so

# Add virtual host
<VirtualHost *:80>
    ServerName localhost
    DocumentRoot "C:/path/to/CloudinatorFTP"
    
    WSGIScriptAlias / "C:/path/to/CloudinatorFTP/myflaskapp.wsgi"
    
    <Directory "C:/path/to/CloudinatorFTP">
        Require all granted
    </Directory>
</VirtualHost>
```

#### Step 13.5: Restart Apache

```cmd
# In XAMPP Control Panel
# Stop Apache, then Start Apache
```

See [DEPLOY_APACHE.md](DEPLOY_APACHE.md) for detailed Apache setup.

---

## Storage Configuration Details

### Windows Storage Paths

#### User Profile Paths (Recommended)

```
%USERPROFILE%\Documents\CloudflareFTP
%USERPROFILE%\Downloads\CloudflareFTP
%USERPROFILE%\Desktop\CloudflareFTP
```

Example (replace `USERNAME`):
```
C:\Users\USERNAME\Documents\CloudflareFTP
C:\Users\USERNAME\Downloads\CloudflareFTP
```

#### System Paths

```
C:\CloudinatorFTP            # Program files
C:\Server\config\db          # Database (secure)
C:\Server\config\cache       # Cache files
C:\SharedFolder\CloudinatorFTP  # Network share
```

### Environment Variables

You can use Windows environment variables:

| Variable | Expands To |
|----------|-----------|
| `%USERPROFILE%` | `C:\Users\USERNAME` |
| `%APPDATA%` | `C:\Users\USERNAME\AppData\Roaming` |
| `%LOCALAPPDATA%` | `C:\Users\USERNAME\AppData\Local` |
| `%TEMP%` | Temporary files directory |
| `%SYSTEMDRIVE%` | `C:` (or other drive) |

---

## Firewall Configuration

### Allow Server Through Windows Firewall

1. Press `Win+R`, type `wf.msc`
2. Click "Inbound Rules" → "New Rule"
3. **Rule Type**: Port
4. **Protocol**: TCP, **Port**: 5000
5. **Action**: Allow
6. **Name**: CloudinatorFTP

Or use Command Prompt (Admin):

```cmd
netsh advfirewall firewall add rule name="CloudinatorFTP" dir=in action=allow protocol=TCP localport=5000
```

### Protocol Server Ports

> Port `8080` (plain-HTTP WebDAV) is off by default — only open it if you enabled it.

```cmd
netsh advfirewall firewall add rule name="CloudinatorFTP-WebDAV" dir=in action=allow protocol=TCP localport=8080
netsh advfirewall firewall add rule name="CloudinatorFTP-WebDAV-HTTPS" dir=in action=allow protocol=TCP localport=8443
netsh advfirewall firewall add rule name="CloudinatorFTP-SFTP" dir=in action=allow protocol=TCP localport=2222
netsh advfirewall firewall add rule name="CloudinatorFTP-FTP" dir=in action=allow protocol=TCP localport=2121
netsh advfirewall firewall add rule name="CloudinatorFTP-FTP-Passive" dir=in action=allow protocol=TCP localport=60000-60100
netsh advfirewall firewall add rule name="CloudinatorFTP-SMB" dir=in action=allow protocol=TCP localport=445
netsh advfirewall firewall add rule name="CloudinatorFTP-SMB-Fallback" dir=in action=allow protocol=TCP localport=8445
```

---

## Troubleshooting

### Installation Issues

| Issue | Solution |
|-------|----------|
| Python not recognized | Add to PATH: `sysdm.cpl` → Environment Variables |
| git not found | Reinstall Git, ensure PATH is updated |
| pip fails | Update pip: `python -m pip install --upgrade pip` |
| Permission denied | Run Command Prompt as Administrator |
| Python older than 3.14.3 | Install Python 3.14.3+ from [python.org](https://www.python.org/downloads/) and re-create `.venv` |

### Protocol Server Issues

| Issue | Solution |
|-------|----------|
| WebDAV not starting | Run `pip install wsgidav cheroot` |
| SFTP not starting | Run `pip install paramiko` |
| FTP not starting | Run `pip install pyftpdlib` |
| WebDAV "inaccessible" (HTTP) | Enable the WebClient service (`Start-Service WebClient`); set `BasicAuthLevel=2` |
| Nothing listens on port 8080 | Expected — plain-HTTP WebDAV is off by default. Use `https://SERVER-IP:8443/` instead |
| WebDAV "inaccessible" (HTTPS) | Import `db\webdav.crt` as Trusted Root CA |
| WebDAV drive not in Explorer | Run `net use` in a **non-elevated** terminal |
| SFTP auth fails | Accept host key warning in WinSCP on first connect; verify port 2222 |
| FTP stalls after login | Open ports 60000-60100 in firewall |
| Ports unreachable | Add firewall rules (see Firewall Configuration above); verify with `Test-NetConnection` |
| Wrong IP | Run `ipconfig` to find correct LAN IP; use that in WinSCP/net use |
| SMB `[Errno 22] Invalid argument` on import | Windows Defender quarantined `impacket` — add an exclusion, then reinstall with `--no-cache-dir` |
| SMB stuck on port 8445 | Run `python tools/smb_setup.py` (or `./manage.sh setup-smb`) once, then **restart** (not Shut Down) the machine |
| SMB login fails for an existing user | Reset their password once — NTLM needs a fresh hash, see [SMB_PROTOCOL_DEPLOYMENT.md](./SMB_PROTOCOL_DEPLOYMENT.md) |
| SMB "Ctrl+S" errors in Office | Update to the latest `smb_server.py` — this is a known Windows file-locking issue with fixes already applied |

### Virtual Environment Issues

| Issue | Solution |
|-------|----------|
| Can't activate venv | Run: `.venv\Scripts\activate.bat` exactly (in Git Bash: `source ./.venv/Scripts/activate`) |
| venv folder empty | Delete and recreate: `rmdir /s /q .venv` then `python -m venv .venv` |
| Wrong Python version | Check: `.venv\Scripts\python --version` (needs 3.14.3+) |

### Dependency Installation

| Issue | Solution |
|-------|----------|
| bcrypt fails | Install Visual C++ build tools or use prebuilt wheel |
| cryptography fails | Install: `pip install --upgrade setuptools` first |
| pyvips not found | Manual install or use wheels |
| ffmpeg not found | Add to PATH or install to `C:\ffmpeg` |

### Server Issues

| Issue | Solution |
|-------|----------|
| Port 5000 in use | Change port in config.py or: `netstat -ano \| findstr :5000` |
| Server won't start | Read the newest file in `logs/` (`./manage.sh logs`) for the error |
| High CPU usage | Reduce HLS settings or check file count |
| Blank white screen | Check browser console for errors |

### Authentication Issues

| Issue | Solution |
|-------|----------|
| Login fails | Run: `python tools/manage_users.py` (list users / change password) |
| Looping web refresh | Run: `python tools/kick_sessions.py logout-web` |
| Locked out after failed logins | After 5 failed logins a client is locked out for 5 minutes — wait, then retry |
| Database corrupted | Run: `python tools/reset_db.py` (destructive: recreates the default accounts) |
| Password reset | Use: `python tools/manage_users.py` > Change password |

### Launcher Issues (only if you made your own `.bat`; the repo no longer ships one)

| Issue | Solution |
|-------|----------|
| Batch doesn't close | Use: `python dev_server.py` instead |
| Can't find venv | Ensure the `.venv` folder exists in the project |
| PATH errors | Run Command Prompt from project folder |

### Cloudflare Tunnel Issues

| Issue | Solution |
|-------|----------|
| cloudflared not found | Download from GitHub or use `choco install cloudflared` |
| Tunnel disconnects | Keep terminal open, check internet |
| Can't connect to URL | Verify server is running on port 5000 |

### Windows Service Issues

| Issue | Solution |
|-------|----------|
| Service won't start | Check event log, verify paths |
| Can't install service | Run Command Prompt as Administrator |
| Service keeps stopping | Check error logs, increase restart delay |

---

## Performance Tips

### Optimize for Windows

1. **Disable Antivirus Scanning** for project folder:
   - Windows Defender → Virus & threat protection
   - Click "Manage settings"
   - Add exclusion for CloudinatorFTP folder

2. **Increase Performance**: use `python config.py` (settings saved to `server_config.json` override the built-in defaults in `config.py`). Example values:
   ```cmd
   CHUNK_SIZE = 50 * 1024 * 1024  # Increase to 50 MB
   IMG_COMPRESS_MIN_SIZE = 1 * 1024 * 1024  # 1 MB
   ```

3. **Prefer HTTPS** on any network you don't fully control (WebDAV HTTPS on 8443 is the default; plain-HTTP WebDAV on 8080 is off by default)

---

## Next Steps

1. ✅ Server running on `https://localhost:5000`
2. 🌐 WebDAV mapped as network drive (HTTPS on port 8443; port 8080 only if plain HTTP is enabled)
3. 🔒 SFTP accessible via WinSCP (port 2222)
4. 📁 FTP accessible via WinSCP/FileZilla (port 2121)
5. 📡 SMB — run `python tools/smb_setup.py` if you want native port 445 mapping (optional)
6. 📤 Get Cloudflare tunnel URL (optional)
7. 🔐 Change default passwords
8. 👥 Create users for team
9. 🌍 Share the URL
10. 📊 Monitor performance

---

## Additional Resources

- [Python Documentation](https://docs.python.org/3/)
- [Cloudflare Tunnel Docs](https://developers.cloudflare.com/cloudflare-one/)
- [Apache Documentation](https://httpd.apache.org/docs/)
- [XAMPP Documentation](https://www.apachefriends.org/index.html)
- [Project GitHub](https://github.com/NeoMatrix14241/CloudinatorFTP)
- [Apache WSGI Deployment](./DEPLOY_APACHE.md)
- [Cloudflare Tunnel Setup](./SETUP_TUNNEL_ADVANCED.md)
- [rclone Integration](./RCLONE_DEPLOYMENT.md)
- [SMB Protocol Setup](./SMB_PROTOCOL_DEPLOYMENT.md)
- [manage.sh Guide](./MANAGE_SCRIPT_GUIDE.md)
- [Configuration Reference](./CONFIG_PY_REFERENCE.md)
- [User Guide](./USER_GUIDE.md)

---

## Support

- 🐛 Found a bug? [GitHub Issues](https://github.com/NeoMatrix14241/CloudinatorFTP/issues)
- 💡 Feature requests? [GitHub Discussions](https://github.com/NeoMatrix14241/CloudinatorFTP/discussions)
- 📞 Need help? Check this guide's troubleshooting section

---