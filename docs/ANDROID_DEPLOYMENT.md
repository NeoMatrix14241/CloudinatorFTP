# 📱 CloudinatorFTP Android (Termux) Deployment Guide

A comprehensive guide to deploy CloudinatorFTP on Android devices using Termux, enabling secure file sharing over the internet using Cloudflare tunnels.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Termux Installation](#termux-installation)
3. [Initial Setup](#initial-setup)
4. [Dependency Installation](#dependency-installation)
5. [Configuration](#configuration)
6. [User Management](#user-management)
7. [Launch Server](#launch-server)
8. [Server Management Script (manage.sh)](#️-server-management-script-managesh)
9. [Updating Python Dependencies](#-updating-python-dependencies)
10. [Protocol Servers on Android](#protocol-servers-on-android)
11. [Network Exposure](#network-exposure)
12. [Storage Configuration](#storage-configuration-details)
13. [Troubleshooting](#troubleshooting)
14. [Tips for Running on Android](#tips-for-running-on-android)

---

## Prerequisites

- **Android Device** with at least 2GB of RAM (4GB+ recommended)
- **Termux App** - **NOT** the Play Store version
- **Internet Connection** (WiFi or Mobile data)
- Basic command-line familiarity

> ⚠️ **Important**: Use the F-Droid or GitHub version of Termux, NOT the Play Store version, as it has limitations.

### Install Termux

1. Visit [Termux](https://termux.dev/en/)
2. Download from:
   - **F-Droid**: [F-Droid](https://f-droid.org/packages/com.termux/)
   - **GitHub**: [GitHub Releases](https://github.com/termux/termux-app)

---

## Termux Installation

### Step 1: Initial Termux Packages Installation

#### Automated Setup Script (Recommended)

First, update Termux and install `curl`:

```bash
pkg update -y && pkg upgrade -y && pkg install curl -y
```

The `termux_setup.sh` script fully automates the installation below, including all Android-specific patches and retry logic. It is also what runs when you use the quick-install URL:

```bash
# Option A: Quick install (runs termux_setup.sh without cloning first)

# For main branch (stable):
curl -sL https://tinyurl.com/CloudinatorFTP | bash

# For dev branch:
curl -sL https://tinyurl.com/CloudinatorFTP-dev | bash

# Option B: Run locally after cloning the repository
bash termux_setup.sh
```

The script automatically:
- Installs all required Termux packages
- Applies both PyPPMd patches for Android compatibility
- Requests storage permission and waits for you to accept
- **Retries up to 5 times** — useful on slow or unstable connections

> **Note**: Re-run the script if errors are encountered on the first attempt.
> **Note**: This includes two important patches:
> 1. **pthread_cancel() workaround**: Android's bionic libc lacks pthread_cancel() support
> 2. **PyPPMd version patch**: Fixes setuptools_scm detection issues on Android

### Step 2: Grant Storage Permission

```bash
termux-setup-storage
```

This command will prompt you to grant storage permission. Accept it to allow Termux to access your device's files.

> **Note**: Required if serving files from Internal Storage or Download folder. Without it, the server will only access Termux's private data path.

---

## Initial Setup

### Step 3: Clone the Project

#### Main Branch (Stable Release)
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

## Dependency Installation

### Step 4: Install Python Dependencies

#### Create and Activate the Virtual Environment

```bash
python -m venv .venv                    # Create the python environment
source .venv/bin/activate               # Use the created environment
```

> **Note**: The activation script must be **sourced** (`source ...`). Running `.venv/bin/activate` on its own starts a subshell and activates nothing. `bash setup_pymodules.sh` (or `./manage.sh update-modules`) creates and activates `.venv` for you when you answer `y`; on Termux it creates the environment with `--system-site-packages` so the packages installed by `pkg` stay visible. If you create the environment by hand and need those packages, add the same flag: `python -m venv --system-site-packages .venv`.

#### Install the Requirements

```bash
pip install -r requirements.txt         # Main requirements
pip install -r requirements-dev.txt     # Dev only (optional) - if you will modify the code and run the tests
```

#### Troubleshooting bcrypt Installation

If bcrypt installation fails:

```bash
pkg install clang python libcrypt
pip install -r requirements.txt
```

---

## Configuration

### Step 5.1: Configure Storage Location

Choose where your files will be stored:

```bash
python tools/setup_storage.py
```

#### Storage Options

After running `termux-setup-storage`, you can choose from:

| Location | Path | Accessible From | Best For |
|----------|------|-----------------|----------|
| **Downloads** ⭐ | `/storage/emulated/0/Download/CloudflareFTP` | Files app > Downloads | File sharing, easy access |
| **Documents** | `/storage/emulated/0/Documents/CloudflareFTP` | Files app > Documents | Document storage |
| **Internal Root** | `/storage/emulated/0/CloudflareFTP` | Files app > Internal Storage | General purpose |
| **Camera Folder** | `/storage/emulated/0/DCIM/CloudflareFTP` | Gallery/Photos apps | Photo/video sharing |
| **Termux Only** | `~/uploads` | Termux terminal only | Secure, private files |

### Step 5.2: Advanced Configuration (Optional)

For detailed server configuration:

```bash
python config.py
```

Every setting is explained in the [Configuration Reference](./CONFIG_PY_REFERENCE.md). This allows you to customize:
- Port number (default: 5000)
- Chunk size for uploads (default: 10 MB)
- Session lifetime (default: 365 days)
- HLS streaming settings
- Image compression quality
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

### Step 5.3: Update security.txt and robots.txt

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

### Step 6: Setup Users

#### User Roles

- **`readwrite`**: Can upload, download, create folders, delete files
- **`readonly`**: Can only download files and browse folders

Both roles apply equally to the web UI, WebDAV, SFTP, and FTP.

#### Default Users (Created Automatically)

When the server starts for the first time, it creates:

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | readwrite |
| `guest` | `guest123` | readonly |

> 🚨 **Security Warning**: Change these passwords immediately before exposing to the internet!

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

#### Example: Add a New User

```bash
python tools/manage_users.py
# Select option 2 (Add user)
# Enter username: alice
# Enter password: [your secure password]
# Select role: readwrite or readonly
```

#### Test Authentication

If you're having login issues, list the users and change the password if needed (the old `debug_passwords.py` tester was removed in 4.80):

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

### Step 7: Start the Server

> 💡 Use [`manage.sh`](#️-server-management-script-managesh) to run the server in the background and keep your Termux session free.

#### Production/Live Server — Hypercorn ASGI (Recommended for Termux)

```bash
source .venv/bin/activate   # if the virtual environment isn't already active
python prod_server.py
```

Starting output:
```
🧪 Starting CloudinatorFTP Production Server...
🌐 Server running on https://localhost:5000
🔧 Debug mode: OFF - Auto-reload disabled
```

#### Development/Testing Server — Quart

```bash
source .venv/bin/activate   # if the virtual environment isn't already active
python dev_server.py
```

Protocol servers (WebDAV, SFTP, FTP) start **automatically** alongside the web server — no extra command needed.

> **Note**: Keep this terminal window open while the server is running (or use `manage.sh` to run it in the background).

---

## 🖥️ Server Management Script (`manage.sh`)

> 💡 **Recommended:** Use `manage.sh` to run servers in the background while keeping your Termux session free for utilities. Full reference: **[MANAGE_SCRIPT_GUIDE.md](./MANAGE_SCRIPT_GUIDE.md)**.

### ⚡ Setup

```bash
chmod +x manage.sh
```

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

Run any utility **while a server is running in the same Termux session**:

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
| `./manage.sh termux-setup` | `bash termux_setup.sh` (first-time setup, Android/Termux only) |

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

A numbered menu covering servers, utilities, quality assurance and developer tools, with live status shown at the top. On Termux, the menu also shows the `termux-setup` option.

### 💡 Typical Workflow (Termux)

```bash
# 1. Start production server in the background
./manage.sh start server

# 2. Run utilities in the same Termux session while the server is up
./manage.sh manage-users
./manage.sh config

# 3. Check server is still running
./manage.sh status

# 4. View logs on demand (Ctrl-C detaches, server keeps running)
./manage.sh logs server -f

# 5. Stop when done
./manage.sh stop
```

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
4. Ask whether to install now: on `y` it creates and activates `.venv` (`.venv/bin` on Termux) and installs the packages there

`requirements-dev.txt` (the test packages) is not touched by the script: install it yourself with `pip install -r requirements-dev.txt`.

> **Android / Termux**: Run the same command in your Termux session. The virtual environment is created with `--system-site-packages` so the packages installed by `pkg` stay visible.

---

## Protocol Servers on Android

> ℹ️ **Android / Termux Note**: Protocol server availability on Android depends on the library. The web UI (port 5000) always works. WebDAV, SFTP and FTP start automatically alongside the web server and use the same credentials as the web UI. For the additional servers:

| Protocol | Android Support | Notes |
|----------|----------------|-------|
| **WebDAV HTTPS** (8443) | ⚠️ May vary | On by default; cheroot SSL support — try `pip install cheroot` |
| **WebDAV HTTP** (8080) | ✅ Likely works | Off by default — only listens if HTTPS is disabled (with `WEBDAV_ENABLED` on) or as the automatic fallback when the HTTPS certificate can't be prepared; wsgidav |
| **SFTP** (2222) | ✅ Usually works | paramiko available via pip on Termux |
| **FTP** (2121) | ✅ Usually works | pyftpdlib available via pip |
| **SMB** (445/8445) | ⚠️ Root-dependent | See dedicated note below — different from the other protocols |

### Install Protocol Dependencies on Termux

Most of these are already pulled in by `requirements.txt`. If a protocol server reports a missing package at startup, install it with:

```bash
pip install wsgidav paramiko pyftpdlib impacket
pip install cheroot   # WebDAV HTTPS (the default WebDAV mode)
```

If any library fails to install on Termux, only that protocol is skipped — the main web UI continues running normally.

### SMB on Android — Root Required for Port 445

SMB is disabled by default even with `impacket` installed — port 445 needs root. Run the setup helper to check:

```bash
python tools/smb_setup.py   # or: ./manage.sh setup-smb
```

**Rooted devices**: rather than granting a capability via `setcap` (its behavior on Android is unpredictable — SELinux policy varies significantly across devices and rooting methods, and a granted capability can silently fail to apply at runtime), the reliable option is running the server itself as root:
```bash
su -c 'python prod_server.py'
# or with tsu:
tsu
python prod_server.py
```

**Non-rooted devices**: there's no path to port 445 at all. CloudinatorFTP automatically falls back to port 8445 — nothing further to do, the rest of the server works normally.

> ⚠️ **Existing users need a one-time password reset** before SMB accepts their login — SMB uses NTLM, which needs a hash of the password only capturable the moment it's set. Full details: [SMB_PROTOCOL_DEPLOYMENT.md](./SMB_PROTOCOL_DEPLOYMENT.md).

### Android Battery & Stability Considerations

Running extra protocol servers increases CPU and battery usage slightly:
- Disable unused protocols via `python config.py` → option 13
- Or in `server_config.json`: set `"SFTP_ENABLED": false` etc.
- FTP is least useful on Android; recommend disabling it to save resources
- SMB is disabled by default already — leave it off unless you specifically need it

### Connecting to Your Android Server

Once running, connect from your PC on the same WiFi:

```
Web UI:          https://ANDROID-IP:5000
WebDAV (HTTPS):  https://ANDROID-IP:8443
SFTP (WinSCP):   sftp://ANDROID-IP:2222
FTP (LAN only):  ftp://ANDROID-IP:2121
SMB:             \\ANDROID-IP\SharedFolder  (rooted) or port 8445 (not rooted)
```

WebDAV over HTTPS uses a certificate you need to trust on each client — it is `db/webdav.crt` in the project folder. See the [Windows](./WINDOWS_DEPLOYMENT.md) and [Linux](./LINUX_DEPLOYMENT.md) guides for the client steps. Plain-HTTP WebDAV (`http://ANDROID-IP:8080`) only works if you have enabled it.

To mount the server from a PC with rclone, see [RCLONE_DEPLOYMENT.md](./RCLONE_DEPLOYMENT.md). Quick WebDAV mount (Windows drive letter shown):

```bash
rclone mount :webdav,url=https://ANDROID-IP:8443/,user=admin,pass=admin123,no_check_certificate=true: Z: --vfs-cache-mode full
```

Find your Android IP in **Settings → About Phone → Status → IP address** or run `ifconfig` in Termux.

---

## Network Exposure

### Step 8: Expose to the Internet

Open a **NEW** Termux session (or use a tmux session) and run — **choose what to tunnel**:

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

>  ✨ You can now access your files from anywhere in the world using this URL!

> 💡 **Which port to tunnel?**
> - `5000` → web browser access (upload, preview, download via browser)
> - `8443` → WebDAV drive mapping from remote computers (HTTPS, the default — use with `--url https://localhost:8443`)
> - `8080` → plain-HTTP WebDAV — **off by default**; it only listens if HTTPS is disabled (with `WEBDAV_ENABLED` on) or as the automatic fallback when the HTTPS certificate can't be prepared
> - Only one port can be tunneled at once with the quick `--url` method. For multiple services, see the [Advanced Tunnel Setup](./SETUP_TUNNEL_ADVANCED.md).
>
> **Note**: SFTP (2222) and FTP (2121) are raw TCP and cannot be tunneled via Cloudflare — use them on your local WiFi only.

#### Using a Custom Domain (Optional)

For a persistent domain setup, refer to [Advanced Cloudflared Tunneling Setup](https://github.com/NeoMatrix14241/CloudinatorFTP/wiki/Advanced-Cloudflare-Tunnelling-Setup), then use this configuration for the `config.yml` of cloudflared (on Termux, `~` is `/data/data/com.termux/files/home`):

```yaml
tunnel: <tunnel id>
credentials-file: /data/data/com.termux/files/home/.cloudflared/<tunnel id>.json
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

## Storage Configuration Details

### Android Storage Paths Explained

#### 📥 Download Folder (Recommended)
```
/storage/emulated/0/Download/CloudflareFTP
```
- **Pros**: Easy access via Files app, automatically backed up to cloud services
- **Cons**: Files may be auto-cleaned by some devices
- **Use Case**: File sharing, temporary uploads

#### 📄 Documents Folder
```
/storage/emulated/0/Documents/CloudflareFTP
```
- **Pros**: Persists across app updates, organized
- **Cons**: Less visibility in some file managers
- **Use Case**: Document storage and archiving

#### 🏠 Internal Storage Root
```
/storage/emulated/0/CloudflareFTP
```
- **Pros**: Clear path, top-level visibility
- **Cons**: Can be cluttered
- **Use Case**: Mixed file types, general purpose

#### 📸 DCIM/Camera Folder
```
/storage/emulated/0/DCIM/CloudflareFTP
```
- **Pros**: Mounted in Gallery app automatically
- **Cons**: Meant for photos/videos only
- **Use Case**: Photo/video sharing

#### 🔒 Termux Private Directory
```
~/uploads
```
- **Pros**: Only accessible in Termux (secure)
- **Cons**: Not accessible from Android's file manager
- **Use Case**: Sensitive/private files

---

## Troubleshooting

### Protocol Server Issues (Android)

| Issue | Solution |
|-------|----------|
| `wsgidav` install fails | Try `pip install wsgidav --no-build-isolation` |
| `paramiko` install fails | Run `pkg install rust` first, then `pip install paramiko` |
| `pyftpdlib` install fails | Run `pip install pyftpdlib --no-binary pyftpdlib` |
| `cheroot` SSL fails | Disable HTTPS WebDAV: `"WEBDAV_HTTPS_ENABLED": false` in server_config.json (WebDAV then falls back to plain HTTP on 8080 if `WEBDAV_ENABLED` is on) |
| Nothing listens on port 8080 | Expected — plain-HTTP WebDAV is off by default. Use `https://ANDROID-IP:8443/` instead |
| Port already in use | Change port in config.py or kill conflicting process |

### Installation Issues

| Issue | Solution |
|-------|----------|
| `bcrypt` fails to install | Run: `pkg install clang python libcrypt` |
| File permissions denied | Run: `termux-setup-storage` and grant permission |
| Package mirror errors | Try: `pkg --check-mirror update` |
| Low storage space | Free up space or use external storage path |

### Storage Issues

| Issue | Solution |
|-------|----------|
| Files not visible in Android | Ensure path starts with `/storage/emulated/0/` |
| "Permission denied" errors | Run `termux-setup-storage` again |
| "Directory not found" | Verify path exists: `ls /storage/emulated/0/` |
| "No space left" | Check storage: `df -h /storage/emulated/0` |

### Authentication Issues

| Issue | Solution |
|-------|----------|
| Login fails with correct password | Run: `python tools/manage_users.py` (list users / change password) |
| Forgot password | Use: `python tools/manage_users.py` > Change password |
| Locked out after failed logins | After 5 failed logins a client is locked out for 5 minutes — wait, then retry |
| Users file corrupted | Run: `python tools/reset_db.py` (destructive: recreates the default accounts) |
| Looping redirects on login / web refresh | Run: `python tools/kick_sessions.py logout-web` |
| Database corrupted | Run: `python tools/reset_db.py` (destructive: recreates the default accounts) |

### Server Issues

| Issue | Solution |
|-------|----------|
| Port 5000 already in use | Change port in `config.py` or kill process |
| Server won't start | Check the newest file in `logs/` (`./manage.sh logs`) |
| Cloudflare tunnel fails | Restart Termux, check internet connection |
| High CPU/Battery drain | Reduce HLS settings in `config.py` |
| SMB won't bind port 445 | Expected on non-rooted devices — falls back to 8445 automatically. Rooted? Run server via `su -c` or `tsu` |

### Network Issues

| Issue | Solution |
|-------|----------|
| Can't access from browser | Ensure server is running and URL is correct |
| Tunnel disconnects | Keep Termux app in foreground or use `tmux` |
| Connection resets | Check WiFi stability, try mobile data |

---

## Tips for Running on Android

### Keep Termux Running in Background

- Use `tmux` to create persistent sessions
- Keep Termux app in recent apps to prevent killing
- Reduce screen lock timeout for better stability

### Session Management

Create a persistent session with tmux:

```bash
# Install tmux (if not already installed)
pkg install tmux

# Create a new session
tmux new-session -d -s cloudinator

# Run server in the session
tmux send-keys -t cloudinator "source .venv/bin/activate && python prod_server.py" Enter

# Run tunnel in another window
tmux new-window -t cloudinator
tmux send-keys -t cloudinator "cloudflared tunnel --url https://localhost:5000" Enter

# View sessions
tmux list-sessions

# Attach to session
tmux attach-session -t cloudinator
```

### Battery Optimization

- Use production server (`prod_server.py`) instead of development
- Disable FTP and HTTPS WebDAV if not needed (saves resources)
- SMB is disabled by default already; leave it off unless you specifically need root-only port 445
- Disable video preview HLS if not needed: set `HLS_MIN_SIZE` to very high value
- Use WiFi instead of mobile data for stability
- Enable battery saver mode if needed

---

## Next Steps

1. ✅ Server is running!
2. 📡 SMB — rooted device? Run via `su -c` for port 445; otherwise 8445 works automatically
3. 📤 Get your Cloudflare tunnel URL
4. 🔐 Change default passwords
5. 👥 Add more users with specific roles
6. 🌍 Share your URL with others
7. 📊 Monitor storage and performance

---

## Additional Resources

- [Termux Documentation](https://termux.dev/)
- [Cloudflare Tunnel Docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-applications/)
- [Project GitHub](https://github.com/NeoMatrix14241/CloudinatorFTP)
- [Advanced Tunnel Setup](https://github.com/NeoMatrix14241/CloudinatorFTP/wiki/Advanced-Cloudflare-Tunnelling-Setup)
- [rclone Integration](./RCLONE_DEPLOYMENT.md)
- [SMB Protocol Setup](./SMB_PROTOCOL_DEPLOYMENT.md)
- [manage.sh Guide](./MANAGE_SCRIPT_GUIDE.md)
- [Configuration Reference](./CONFIG_PY_REFERENCE.md)
- [User Guide](./USER_GUIDE.md)

---

## Support

- 🐛 Found a bug? Open an issue on GitHub
- 💡 Have a feature request? Discuss on GitHub Discussions
- 📧 Need help? Check the troubleshooting section

---