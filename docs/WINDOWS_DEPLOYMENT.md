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
10. [Server Management Script (manage.sh)](#-server-management-script-managesh)
11. [Updating Python Dependencies](#-updating-python-dependencies)
12. [Batch Script Setup](#batch-script-setup)
13. [Windows Service Setup](#windows-service-setup)
14. [Protocol Servers — WebDAV, SFTP, FTP](#protocol-servers--webdav-sftp-ftp)
12. [Cloudflare Tunnel](#cloudflare-tunnel)
13. [Apache/WSGI Deployment](#apachewsgi-deployment-optional)
14. [Storage Configuration](#storage-configuration)
15. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Windows Version**: Windows 10 1909+, Windows 11, Windows Server 2019+
- **Administrator Access**: Required for installation
- **Internet Connection**
- **Basic Command-Line Knowledge** (Windows Terminal, PowerShell, or Command Prompt)

### Tested Versions

- ✅ Windows 10 (Version 1909+)
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
| **Python** | 3.10 | 3.11+ |

---

## Python Installation

### Step 1: Download and Install Python

1. Visit [python.org](https://www.python.org/downloads/)
2. Download **Python 3.11+** for Windows
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
Python 3.11.x
pip 24.x.x
```

### Step 3: Upgrade pip

```cmd
python -m pip install --upgrade pip
```

---

## Dependency Installation

### Step 1: Install Git

1. Download from [git-scm.com](https://git-scm.com/download/win)
2. Run installer using defaults
3. Verify:

```cmd
git --version
```

### Step 2: Install FFmpeg (Optional but Recommended)

FFmpeg enables video streaming and format conversion.

#### Option A: Direct Download

1. Download from [gyan.dev/ffmpeg](https://www.gyan.dev/ffmpeg/builds/)
2. Choose **"full" build**
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

### Step 3: Install libvips (Optional)

For image optimization and WebP compression.

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
powershell -Command "(New-Object System.Net.ServicePointManager).SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; (New-Object System.Net.WebClient).DownloadFile('https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe', 'C:\cloudflared.exe')"

# Move to Program Files
move C:\cloudflared.exe "C:\Program Files\cloudflared\cloudflared.exe"
```

Or download manually from [Cloudflare Releases](https://github.com/cloudflare/cloudflared/releases)

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
python -m venv venv
```

#### Activate Virtual Environment

**Command Prompt:**
```cmd
venv\Scripts\activate.bat
```

**PowerShell:**
```powershell
venv\Scripts\Activate.ps1
```

> **Note**: You'll see `(venv)` in your prompt when activated.

#### Deactivate (When Done)

```cmd
deactivate
```

---

## Configuration

### Step 7.1: Install Python Dependencies

```cmd
# Ensure virtual environment is activated
venv\Scripts\activate.bat

# Install requirements
pip install -r requirements.txt
```

> **If bcrypt fails**, install build tools first:
> ```cmd
> pip install --upgrade setuptools wheel
> pip install -r requirements.txt
> ```

### Step 7.1b: Install Protocol Server Dependencies

The WebDAV, SFTP, and FTP servers require additional libraries:

```cmd
pip install wsgidav cheroot paramiko pyftpdlib
```

| Package | Protocol | Purpose |
|---------|----------|---------|
| `wsgidav` | WebDAV | WebDAV WSGI server |
| `cheroot` | WebDAV HTTPS | WSGI server with TLS support |
| `paramiko` | SFTP | SSH/SFTP implementation |
| `pyftpdlib` | FTP | FTP server |

> **Note**: These are optional. If any are missing, the corresponding server skips on startup with an install hint. The main web UI is unaffected.

### Step 7.2: Configure Storage Location

```cmd
python setup_storage.py
```

Follow the prompts to set:
- **Files Directory**: Where uploaded files are stored
- **Database Directory**: SQLite database
- **Cache Directory**: Temporary files and index

#### Recommended Storage Paths

| Component | Path | Why |
|-----------|------|-----|
| **Files** | `C:\CloudinatorFTP\Files` | Simple, easy backup |
| **Files** | `%USERPROFILE%\Documents\CloudinatorFTP` | User Documents |
| **Files** | `%USERPROFILE%\Downloads\CloudinatorFTP` | Share Downloads |
| **Database** | `C:\Server\config\db` | Secure location |
| **Cache** | `C:\Server\config\cache` | System cache |

### Step 7.3: Advanced Configuration (Optional)

```cmd
python config.py
```

Customize:
- Server port (default: 5000)
- Chunk size (default: 10 MB)
- Session lifetime (default: 1 hour)
- HLS/compression settings
- **Protocol server ports and enable/disable** (option 13)

---

## User Management

### Step 8: Setup Users

#### Default Users (Automatic)

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | readwrite |
| `guest` | `guest123` | readonly |

> 🚨 **Change these passwords immediately!**

#### Add/Modify Users

```cmd
python create_user.py
```

**Menu Options:**
1. List users
2. Add user
3. Change password
4. Change role
5. Delete user

#### Test Authentication

```cmd
python debug_passwords.py
```

---

## Launch Server

### Step 9: Start the Server

#### Method 1: Command Prompt

**Production Server (Recommended):**
```cmd
venv\Scripts\activate.bat
python prod_server.py
```

**Development Server (Testing):**
```cmd
venv\Scripts\activate.bat
python dev_server.py
```

#### Method 2: Batch Scripts (Easier)

**Production:**
```cmd
start_prod_server.bat
```

**Development:**
```cmd
start_dev_server.bat
```

### Expected Startup Output

When all protocol servers start successfully:
```
────────────────────────────────────────────────────────
  CloudinatorFTP — Protocol servers
────────────────────────────────────────────────────────
🌐 WebDAV HTTP:  http://HOST:8080/
🔐 WebDAV HTTPS: https://HOST:8443/
🔒 SFTP:         sftp://HOST:2222/
📁 FTP:          ftp://HOST:2121/

  WebDAV    ✅ started
  SFTP      ✅ started
  FTP       ✅ started
────────────────────────────────────────────────────────
```

> **Keep terminal open while server is running**

---

## 🖥️ Server Management Script (`manage.sh`)

> 💡 **Recommended for Git Bash users:** Use `manage.sh` to run servers in the background while keeping your terminal free — no separate window or batch file needed.

### ⚡ Setup (Git Bash)

```bash
chmod +x manage.sh
```

> **Note**: `termux_setup.sh` is for **Android (Termux) only** and is not applicable on Windows. Use the Python/pip installation steps above instead.

### 🚦 Server Commands

> ⚠️ Only one server can run at a time. Starting a second shows a clear status block instead.

| Command | Description |
|---------|-------------|
| `./manage.sh start server` | Start `prod_server.py` (Waitress) in the background |
| `./manage.sh start dev_server` | Start `dev_server.py` (Flask) in the background |
| `./manage.sh stop` | Gracefully stop the running server |
| `./manage.sh restart` | Restart the currently active server |
| `./manage.sh status` | Show server status, PID, and recent log tail |

### 📋 Log Commands

Logs are saved to `logs/` with datetime stamps — each server start creates a new file (e.g. `logs/prod_server_2026-06-09_10-32-01.log`).

| Command | Description |
|---------|-------------|
| `./manage.sh logs` | Last 50 lines (auto-detects active server) |
| `./manage.sh logs server -f` | Follow live production logs |
| `./manage.sh logs dev_server -f` | Follow live dev logs |
| `./manage.sh clean-logs` | Delete old log files (with confirmation) |

> 💡 **Ctrl-C while following logs detaches your terminal without stopping the server.** The server runs as a fully detached Windows process (`CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`), so Ctrl-C never reaches it.

### 🔧 Utility Commands

Run any of these **while a server is running in the same Git Bash window**:

| Command | Equivalent |
|---------|------------|
| `./manage.sh config` | `python config.py` |
| `./manage.sh create-user` | `python create_user.py` |
| `./manage.sh debug-pw` | `python debug_passwords.py` |
| `./manage.sh reset-db` | `python reset_db.py` |
| `./manage.sh setup-storage` | `python setup_storage.py` |
| `./manage.sh update-modules` | `bash update_pymodules.sh` |

### 🎛️ Interactive Menu

```bash
./manage.sh menu
```

### 💡 Typical Workflow (Git Bash)

```bash
# Start production server in the background
./manage.sh start server

# Run utilities in the same Git Bash window while the server is up
./manage.sh create-user
./manage.sh config

# Check server is still running (also shown on open with no args)
./manage.sh

# View logs on demand — Ctrl-C detaches, server keeps running
./manage.sh logs server -f

# Stop when done
./manage.sh stop
```

---

## 🔄 Updating Python Dependencies

To update all Python packages to their latest available versions on PyPI:

```bash
# Git Bash
bash update_pymodules.sh

# Or via manage.sh
./manage.sh update-modules
```

This script will:
1. Check the latest available version of each package on PyPI
2. Update `requirements.txt` with the latest versions
3. Prompt you to install the updates immediately

> **Note**: If using a virtual environment, activate it first:
> `venv\Scripts\activate.bat` (CMD) or `source venv/Scripts/activate` (Git Bash)

---

## Batch Script Setup

### Step 10: Automatic Batch Scripts

The project includes ready-to-use batch scripts:

#### `start_prod_server.bat`
- Activates virtual environment
- Runs production server
- Auto-restarts on error

#### `start_dev_server.bat`
- Activates virtual environment
- Runs development server
- Debug mode enabled

### Using Batch Scripts

**Option 1: Double-click from Explorer**
1. Navigate to project folder
2. Double-click `start_prod_server.bat`

**Option 2: Command Prompt**
```cmd
start_prod_server.bat
```

**Option 3: Create Desktop Shortcut**
1. Right-click `start_prod_server.bat`
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
nssm install CloudinatorFTP "C:\path\to\venv\Scripts\python.exe" "prod_server.py"
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
   - Program: `C:\path\to\start_prod_server.bat`
   - Start in: `C:\path\to\CloudinatorFTP`
6. Click "Finish"

---

## Protocol Servers — WebDAV, SFTP, FTP

Protocol servers start automatically when you run `prod_server.py` or `dev_server.py`. No extra commands needed. They all use the same database credentials as the web UI.

### Firewall Rules (Required for Remote Access)

Open an **elevated PowerShell** and run once:

```powershell
# Web UI (if not already open)
New-NetFirewallRule -DisplayName "CloudinatorFTP Web UI"      -Direction Inbound -Protocol TCP -LocalPort 5000        -Action Allow

# WebDAV HTTP
New-NetFirewallRule -DisplayName "CloudinatorFTP WebDAV HTTP" -Direction Inbound -Protocol TCP -LocalPort 8080        -Action Allow

# WebDAV HTTPS
New-NetFirewallRule -DisplayName "CloudinatorFTP WebDAV HTTPS"-Direction Inbound -Protocol TCP -LocalPort 8443        -Action Allow

# SFTP
New-NetFirewallRule -DisplayName "CloudinatorFTP SFTP"        -Direction Inbound -Protocol TCP -LocalPort 2222        -Action Allow

# FTP control channel
New-NetFirewallRule -DisplayName "CloudinatorFTP FTP"         -Direction Inbound -Protocol TCP -LocalPort 2121        -Action Allow

# FTP passive data ports (required for file transfers)
New-NetFirewallRule -DisplayName "CloudinatorFTP FTP Passive" -Direction Inbound -Protocol TCP -LocalPort 60000-60100 -Action Allow
```

Verify connectivity from another machine:
```powershell
Test-NetConnection -ComputerName SERVER-IP -Port 2222
Test-NetConnection -ComputerName SERVER-IP -Port 2121
Test-NetConnection -ComputerName SERVER-IP -Port 8080
```

### 🌐 WebDAV — Map as Network Drive

WebDAV lets you mount CloudinatorFTP as a Windows drive letter — drag and drop files in File Explorer without a browser.

#### Option A: HTTPS (Recommended — No Registry Edit)

**Import the certificate once** (elevated PowerShell, run on each client PC):
```powershell
# Downloads cert from server and imports it as Trusted Root CA
$f="$env:TEMP\c.crt"
Invoke-WebRequest http://SERVER-IP:8080/webdav.crt -OutFile $f
Import-Certificate $f -CertStoreLocation Cert:\LocalMachine\Root
del $f
```

**Map the drive:**
```cmd
net use X: https://SERVER-IP:8443/ /user:admin admin123 /persistent:yes
```

#### Option B: HTTP (Requires One Registry Edit)

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
5. **User name / Password**: your Cloudinator credentials
6. Click **Login**
7. **First connection**: click **Accept** when the host key warning appears

### 📁 FTP — WinSCP Setup

1. Open WinSCP → New Session
2. **File protocol**: FTP
3. **Encryption**: No encryption
4. **Host name**: server IP
5. **Port number**: `2121`
6. **User name / Password**: credentials
7. Click Login

> ⚠️ FTP is plaintext. Use only on trusted local networks.

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
  "FTP_PORT": 2121
}
```

---

## Cloudflare Tunnel

### Step 12: Expose to the Internet

#### Simple Tunnel (Easiest)

Open new Command Prompt and run:

```cmd
cloudflared tunnel --url http://localhost:5000
```

Get your public URL:
```
https://random-words-12345.trycloudflare.com
```

✨ Access your server from anywhere!

#### Tunnel a Specific Port

```cmd
# Tunnel WebDAV HTTP (for remote drive mapping)
cloudflared tunnel --url http://localhost:8080

# Tunnel WebDAV HTTPS
cloudflared tunnel --url https://localhost:8443
```

> **Note**: Cloudflare Tunnel works with HTTP/HTTPS services only. SFTP (port 2222) and FTP (port 2121) are raw TCP protocols and cannot be tunneled with the standard `--url` method — use them on your local network or set up a VPN for remote SFTP/FTP access.

#### Custom Domain (Advanced)

See: [Advanced Cloudflared Tunnel Setup](https://github.com/NeoMatrix14241/CloudinatorFTP/wiki/Advanced-Cloudflare-Tunnelling-Setup)

---

## Apache/WSGI Deployment (Optional)

### Step 13: Production Deployment with Apache

For production environments, Apache with mod_wsgi is recommended.

#### Prerequisites

- XAMPP with Apache installed
- mod_wsgi installed
- Python virtual environment set up

#### Step 13.1: Install mod_wsgi

```cmd
venv\Scripts\activate.bat
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
venv_path = os.path.join(os.path.dirname(__file__), 'venv')
activate_this = os.path.join(venv_path, 'Scripts', 'activate_this.py')
exec(open(activate_this).read(), {'__file__': activate_this})

# Import Flask app
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
%USERPROFILE%\Documents\CloudinatorFTP
%USERPROFILE%\Downloads\CloudinatorFTP
%USERPROFILE%\Desktop\CloudinatorFTP
```

Example (replace `USERNAME`):
```
C:\Users\USERNAME\Documents\CloudinatorFTP
C:\Users\USERNAME\Downloads\CloudinatorFTP
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

```cmd
netsh advfirewall firewall add rule name="CloudinatorFTP-WebDAV" dir=in action=allow protocol=TCP localport=8080
netsh advfirewall firewall add rule name="CloudinatorFTP-WebDAV-HTTPS" dir=in action=allow protocol=TCP localport=8443
netsh advfirewall firewall add rule name="CloudinatorFTP-SFTP" dir=in action=allow protocol=TCP localport=2222
netsh advfirewall firewall add rule name="CloudinatorFTP-FTP" dir=in action=allow protocol=TCP localport=2121
netsh advfirewall firewall add rule name="CloudinatorFTP-FTP-Passive" dir=in action=allow protocol=TCP localport=60000-60100
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

### Protocol Server Issues

| Issue | Solution |
|-------|----------|
| WebDAV not starting | Run `pip install wsgidav cheroot` |
| SFTP not starting | Run `pip install paramiko` |
| FTP not starting | Run `pip install pyftpdlib` |
| WebDAV "inaccessible" (HTTP) | Enable WebClient: `Start-Service WebClient`; set `BasicAuthLevel=2` |
| WebDAV "inaccessible" (HTTPS) | Import `db\webdav.crt` as Trusted Root CA |
| WebDAV drive not in Explorer | Run `net use` in a **non-elevated** terminal |
| SFTP auth fails | Accept host key warning in WinSCP on first connect; verify port 2222 |
| FTP stalls after login | Open ports 60000-60100 in firewall |
| Ports blocked | Add firewall rules (see Firewall Configuration above) |
| Wrong IP | Run `ipconfig` to find correct LAN IP; use that in WinSCP/net use |

### Virtual Environment Issues

| Issue | Solution |
|-------|----------|
| Can't activate venv | Run: `venv\Scripts\activate.bat` exactly |
| venv folder empty | Delete and recreate: `rmdir venv` then `python -m venv venv` |
| Wrong Python version | Check: `venv\Scripts\python --version` |

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
| Server won't start | Run `python debug_passwords.py` to check |
| High CPU usage | Reduce HLS settings or check file count |
| Blank white screen | Check browser console for errors |

### Authentication Issues

| Issue | Solution |
|-------|----------|
| Login fails | Run: `python debug_passwords.py` |
| Database corrupted | Run: `python reset_db.py` |
| Password reset | Use: `python create_user.py` |

### Batch Script Issues

| Issue | Solution |
|-------|----------|
| Batch doesn't close | Use: `python dev_server.py` instead |
| Can't find venv | Ensure venv folder exists in project |
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

2. **Increase Performance**:
   ```cmd
   # Modify config.py
   CHUNK_SIZE = 50 * 1024 * 1024  # Increase to 50 MB
   IMG_COMPRESS_MIN_SIZE = 1 * 1024 * 1024  # 1 MB
   ```

3. **Enable HTTPS** with self-signed certificate for local network

---

## Next Steps

1. ✅ Server running on `http://localhost:5000`
2. 🌐 WebDAV mapped as network drive (port 8080 or 8443)
3. 🔒 SFTP accessible via WinSCP (port 2222)
4. 📁 FTP accessible via WinSCP/FileZilla (port 2121)
5. 📤 Get Cloudflare tunnel URL (optional)
6. 🔐 Change default passwords
7. 👥 Create users for team
8. 🌍 Share the URL
9. 📊 Monitor performance

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

---

## Support

- 🐛 Found a bug? [GitHub Issues](https://github.com/NeoMatrix14241/CloudinatorFTP/issues)
- 💡 Feature requests? [GitHub Discussions](https://github.com/NeoMatrix14241/CloudinatorFTP/discussions)
- 📞 Need help? Check this guide's troubleshooting section

---