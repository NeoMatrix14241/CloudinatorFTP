# 📱 CloudinatorFTP Android (Termux) Deployment Guide

A comprehensive guide to deploy CloudinatorFTP on Android devices using Termux, enabling secure file sharing over the internet using Cloudflare tunnels.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Termux Installation](#termux-installation)
3. [Initial Setup](#initial-setup)
4. [Dependency Installation](#dependency-installation)
5. [Project Setup](#project-setup)
6. [Configuration](#configuration)
7. [User Management](#user-management)
8. [Launch Server](#launch-server)
9. [Network Exposure](#network-exposure)
10. [Storage Configuration](#storage-configuration)
11. [Troubleshooting](#troubleshooting)

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

Open Termux and run the following command:

```bash
pkg --check-mirror update && pkg update -y && pkg upgrade -y && pkg install -y build-essential clang make binutils llvm rust python python-pip python-bcrypt python-cryptography python-psutil libffi openssl libxml2 libxslt git cloudflared ffmpeg libvips && pip install --upgrade pip setuptools wheel && pip cache purge && pip uninstall pyppmd -y ; pip download pyppmd==1.3.1 --no-binary pyppmd -d $TMPDIR/ppmd && cd $TMPDIR/ppmd && rm -rf pyppmd-1.3.1 && tar -xzf pyppmd-1.3.1.tar.gz && cd pyppmd-1.3.1 && sed -i 's/pthread_cancel(tc->handle);/pthread_kill(tc->handle, SIGTERM);/g' src/lib/buffer/ThreadDecoder.c && python3 -c "
import re
c = open('pyproject.toml').read()
c = c.replace('dynamic = [\"version\"]', 'version = \"1.3.1\"')
c = re.sub(r'\[tool\.setuptools_scm\].*?(?=\[|\Z)', '', c, flags=re.DOTALL)
c = re.sub(r',?\s*\"setuptools.scm[^\"]*\"', '', c)
open('pyproject.toml','w').write(c)
" && pip install . --no-build-isolation --no-cache-dir && pip install py7zr --no-deps && pip install PyCryptodomex pybcj texttable multivolumefile brotli backports.zstd inflate64
```

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

```bash
pip install -r requirements.txt
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
python setup_storage.py
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

This allows you to customize:
- Port number (default: 5000)
- Chunk size for uploads
- HLS streaming settings
- Image compression quality

---

## User Management

### Step 6: Setup Users

#### Default Users (Created Automatically)

When the server starts for the first time, it creates:

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | readwrite |
| `guest` | `guest123` | readonly |

> 🚨 **Security Warning**: Change these passwords immediately before exposing to the internet!

#### Add/Modify Users

```bash
python create_user.py
```

**Menu Options:**
1. List users
2. Add user
3. Change password
4. Change role
5. Delete user

#### Example: Add a New User

```bash
python create_user.py
# Select option 2 (Add user)
# Enter username: alice
# Enter password: [your secure password]
# Select role: readwrite or readonly
```

#### Test Authentication

If you're having login issues:

```bash
python debug_passwords.py
```

This tool allows you to:
- Test password authentication
- View all users
- Reset passwords
- Debug login failures

---

## Launch Server

### Step 7: Start the Server

#### Production/Live Server (Recommended for Termux)

```bash
python prod_server.py
```

Starting output:
```
🧪 Starting CloudinatorFTP Production Server...
🌐 Server running on http://localhost:5000
🔧 Debug mode: OFF - Auto-reload disabled
```

#### Development/Testing Server

```bash
python dev_server.py
```

> **Note**: Keep this terminal window open while the server is running.

---

## Network Exposure

### Step 8: Expose to the Internet

Open a **NEW** Termux session (or use a tmux session) and run:

```bash
cloudflared tunnel --url http://localhost:5000
```

You'll receive a public URL like:
```
https://random-words-12345.trycloudflare.com
```

>  ✨ You can now access your files from anywhere in the world using this URL!

#### Using a Custom Domain (Optional)

For a persistent domain setup, refer to [Advanced Cloudflared Tunneling Setup](https://github.com/NeoMatrix14241/CloudinatorFTP/wiki/Advanced-Cloudflare-Tunnelling-Setup).

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
| Login fails with correct password | Run: `python debug_passwords.py` |
| Forgot password | Use: `python create_user.py` > Change password |
| Users file corrupted | Run: `python reset_db.py` |
| Looping redirects on login | Run: `python revoke_session.py` |
| Database corrupted | Run: `python reset_db.py` |

### Server Issues

| Issue | Solution |
|-------|----------|
| Port 5000 already in use | Change port in `config.py` or kill process |
| Server won't start | Check: `python debug_passwords.py` |
| Cloudflare tunnel fails | Restart Termux, check internet connection |
| High CPU/Battery drain | Reduce HLS settings in `config.py` |

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
tmux send-keys -t cloudinator "python prod_server.py" Enter

# Run tunnel in another window
tmux new-window -t cloudinator
tmux send-keys -t cloudinator "cloudflared tunnel --url http://localhost:5000" Enter

# View sessions
tmux list-sessions

# Attach to session
tmux attach-session -t cloudinator
```

### Battery Optimization

- Use production server (`prod_server.py`) instead of development
- Disable video preview HLS if not needed: set `HLS_MIN_SIZE` to very high value
- Use WiFi instead of mobile data for stability
- Enable battery saver mode if needed

---

## Next Steps

1. ✅ Server is running!
2. 📤 Get your Cloudflare tunnel URL
3. 🔐 Change default passwords
4. 👥 Add more users with specific roles
5. 🌍 Share your URL with others
6. 📊 Monitor storage and performance

---

## Additional Resources

- [Termux Documentation](https://termux.dev/)
- [Cloudflare Tunnel Docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-applications/)
- [Project GitHub](https://github.com/NeoMatrix14241/CloudinatorFTP)
- [Advanced Tunnel Setup](https://github.com/NeoMatrix14241/CloudinatorFTP/wiki/Advanced-Cloudflare-Tunnelling-Setup)

---

## Support

- 🐛 Found a bug? Open an issue on GitHub
- 💡 Have a feature request? Discuss on GitHub Discussions
- 📧 Need help? Check the troubleshooting section

---
