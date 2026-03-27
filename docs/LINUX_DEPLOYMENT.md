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
9. [Systemd Service Setup](#systemd-service-setup)
10. [Network Exposure](#network-exposure)
11. [Storage Configuration](#storage-configuration)
12. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Linux Distribution**: Ubuntu 20.04+, Debian 11+, Fedora, CentOS, Arch, or similar
- **Root or Sudo Access**: Required for system package installation
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
| **Python** | 3.10 | 3.10+ |

### Disk Space Requirements

- **Application**: ~500 MB
- **Database**: ~10 MB
- **Cache**: ~100 MB (varies by usage)
- **File Storage**: Depends on your files

---

## Dependency Installation

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
python3 -m venv venv
```

#### Activate Virtual Environment

```bash
source venv/bin/activate
```

> **Note**: You'll see `(venv)` in your terminal prompt when activated.

#### Deactivate (When Done)

```bash
deactivate
```

---

## Configuration

### Step 7.1: Install Python Dependencies

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### Step 7.2: Configure Storage Location

```bash
python setup_storage.py
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

Customize:
- Server port (default: 5000)
- Chunk size (default: 10 MB)
- Session lifetime (default: 1 hour)
- HLS/compression settings

---

## User Management

### Step 8: Setup Users

#### Default Users

When initialized, the system creates:

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | readwrite |
| `guest` | `guest123` | readonly |

> 🚨 **Change these immediately before exposing to the internet!**

#### Add/Modify Users

```bash
python create_user.py
```

**Available Options:**
1. List all users
2. Add new user
3. Change password
4. Change role
5. Delete user

#### Example: Create Admin User

```bash
python create_user.py
# Select: Add user (2)
# Username: alice
# Password: [secure password]
# Role: readwrite
```

#### Test Authentication

```bash
python debug_passwords.py
```

---

## Launch Server

### Step 9: Start the Server

#### Production Server (Recommended)

```bash
source venv/bin/activate
python prod_server.py
```

Expected output:
```
🧪 Starting CloudinatorFTP Production Server...
🌐 Server running on http://localhost:5000
```

#### Development Server (Testing)

```bash
source venv/bin/activate
python dev_server.py
```

> **Note**: Keep this terminal open or run in the background.

#### Run in Background

```bash
# Using nohup
nohup python prod_server.py > server.log 2>&1 &

# Or using screen
screen -S cloudinator
python prod_server.py
# Ctrl+A then D to detach
```

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
Environment="PATH=/home/YOUR_USERNAME/CloudinatorFTP/venv/bin"
ExecStart=/home/YOUR_USERNAME/CloudinatorFTP/venv/bin/python prod_server.py
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

## Network Exposure

### Step 11: Expose to the Internet

#### Using Cloudflare Tunnel (Simple)

```bash
cloudflared tunnel --url http://localhost:5000
```

Get your public URL:
```
https://random-words-12345.trycloudflare.com
```

#### Using Custom Domain (Advanced)

For persistent domain setup, see:
[Advanced Cloudflared Tunneling Setup](https://github.com/NeoMatrix14241/CloudinatorFTP/wiki/Advanced-Cloudflare-Tunnelling-Setup)

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
| Python 3.10+ not found | Install: `sudo apt install python3.10 python3.10-venv` |
| `pip` command not found | Install: `sudo apt install python3-pip` |
| Permission denied | Use `sudo` or check file permissions |
| libvips not found | Install development headers: `sudo apt install libvips-dev` |

### Virtual Environment Issues

| Issue | Solution |
|-------|----------|
| `venv` not found | Run: `python3 -m venv venv` |
| Can't activate venv | Run: `source venv/bin/activate` (exact path) |
| Permission denied on venv | Check: `ls -la venv/bin/` |
| Wrong Python version | Use: `python3 -m venv venv` explicitly |

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
| Server won't start | Check logs: `python debug_passwords.py` |
| High CPU usage | Reduce HLS in `config.py`, check file count |
| Out of memory | Check: `free -h`, reduce chunk size |

### Database Issues

| Issue | Solution |
|-------|----------|
| Login fails | Run: `python debug_passwords.py` |
| Database corrupted | Run: `python reset_db.py` |
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

In `config.py`, adjust:

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

# Using curl (if running locally)
curl http://localhost:5000

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
2. 📤 Get your Cloudflare tunnel URL
3. 🔐 Change default passwords
4. 👥 Add users for team members
5. 🌍 Share the URL
6. 📊 Monitor performance

---

## Additional Resources

- [Python Virtual Environments](https://docs.python.org/3/tutorial/venv.html)
- [Systemd Documentation](https://systemd.io/)
- [Cloudflare Tunnel Docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-applications/)
- [Project GitHub](https://github.com/NeoMatrix14241/CloudinatorFTP)

---

## Support

- 🐛 Found a bug? [GitHub Issues](https://github.com/NeoMatrix14241/CloudinatorFTP/issues)
- 💡 Feature requests? [GitHub Discussions](https://github.com/NeoMatrix14241/CloudinatorFTP/discussions)
- 📚 Need help? Check this guide's troubleshooting section

---
