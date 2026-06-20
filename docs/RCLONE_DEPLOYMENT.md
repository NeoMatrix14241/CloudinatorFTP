# 🔄 rclone Integration Guide for CloudinatorFTP

rclone is a powerful command-line tool that connects to CloudinatorFTP via **WebDAV**, **SFTP**, or **FTP** and gives you sync, copy, mount, and serve capabilities. Think of it as rsync for cloud storage — but pointing at your own server.

## 📋 Table of Contents

1. [Why rclone?](#why-rclone)
2. [Install rclone](#install-rclone)
3. [Quick Connect (No Config File)](#quick-connect-no-config-file)
4. [Named Remotes (Persistent Config)](#named-remotes-persistent-config)
5. [Mount as a Drive](#mount-as-a-drive)
6. [Sync & Copy](#sync--copy)
7. [Other Useful Commands](#other-useful-commands)
8. [Platform Notes](#platform-notes)
9. [Troubleshooting](#troubleshooting)

---

## Why rclone?

| Feature | rclone | WebDAV (native) | SFTP client |
|---------|--------|-----------------|-------------|
| Mount as drive letter | ✅ All OSes | ✅ Windows/macOS/Linux | ⚠️ Linux/macOS only (sshfs) |
| Sync folders (one-way) | ✅ | ❌ | ❌ |
| Two-way sync | ✅ (bisync) | ❌ | ❌ |
| Copy with filters | ✅ | ❌ | ❌ |
| Resume interrupted transfers | ✅ | ❌ | ❌ |
| Works on Windows without registry | ✅ | ❌ (BasicAuthLevel) | ❌ |
| Works through Cloudflare Tunnel | ✅ | ✅ | ❌ |
| Scripting & automation | ✅ | ❌ | ❌ |

**Best use cases for rclone with CloudinatorFTP:**
- Automated backups from your PC to the server
- Syncing a local folder with the server on a schedule
- Mounting the server as a drive on Windows **without any registry edits**
- Accessing the server through a Cloudflare Tunnel domain

---

## Install rclone

### Windows

```powershell
# Option A: winget
winget install Rclone.Rclone

# Option B: Download from rclone.org
# Visit https://rclone.org/downloads/ → Windows → download zip → extract rclone.exe → add to PATH
```

### Linux

```bash
# Ubuntu/Debian
sudo apt install rclone

# Or install latest from rclone.org
curl https://rclone.org/install.sh | sudo bash
```

### macOS

```bash
brew install rclone
```

### Android (Termux)

```bash
pkg install rclone
```

### Verify Installation

```bash
rclone version
```

---

## Quick Connect (No Config File)

rclone supports **connection strings** — you can connect to CloudinatorFTP without writing any config file. Useful for one-off commands or scripting.

### WebDAV (recommended)

```bash
# List files at root
rclone ls :webdav,url=http://SERVER-IP:8080/,user=admin,pass=admin123:

# List top-level directories
rclone lsd :webdav,url=http://SERVER-IP:8080/,user=admin,pass=admin123:

# Copy a file to the server
rclone copy /local/file.txt :webdav,url=http://SERVER-IP:8080/,user=admin,pass=admin123:backups/

# Copy a file from the server
rclone copy :webdav,url=http://SERVER-IP:8080/,user=admin,pass=admin123:photos/IMG_001.jpg ./
```

### SFTP

```bash
rclone ls :sftp,host=SERVER-IP,port=2222,user=admin,pass=admin123:

rclone copy /local/folder :sftp,host=SERVER-IP,port=2222,user=admin,pass=admin123:backup/
```

### FTP

```bash
rclone ls :ftp,host=SERVER-IP,port=2121,user=admin,pass=admin123:
```

---

## Named Remotes (Persistent Config)

Save connection details once; use the remote name everywhere.

### Interactive Setup

```bash
rclone config
```

Choose **n** for new remote, give it a name (e.g., `cloudinator`), then follow the prompts. For WebDAV, select type `webdav`.

### Manual Config (faster)

Edit `~/.config/rclone/rclone.conf` (Linux/macOS) or `%APPDATA%\rclone\rclone.conf` (Windows):

#### WebDAV HTTP Remote

```ini
[cloudinator]
type = webdav
url = http://SERVER-IP:8080/
vendor = other
user = admin
pass = ENCRYPTED_PASSWORD
```

> **Encrypt the password**: run `rclone obscure admin123` and paste the output as `pass`.

#### WebDAV HTTPS Remote (with self-signed cert)

```ini
[cloudinator-https]
type = webdav
url = https://SERVER-IP:8443/
vendor = other
user = admin
pass = ENCRYPTED_PASSWORD
no_check_certificate = true
```

> Or import `db/webdav.crt` as a system CA (see WINDOWS_DEPLOYMENT.md) and remove the `no_check_certificate` line.

#### SFTP Remote

```ini
[cloudinator-sftp]
type = sftp
host = SERVER-IP
port = 2222
user = admin
pass = ENCRYPTED_PASSWORD
```

#### FTP Remote

```ini
[cloudinator-ftp]
type = ftp
host = SERVER-IP
port = 2121
user = admin
pass = ENCRYPTED_PASSWORD
explicit_tls = false
```

#### Via Cloudflare Tunnel Domain

```ini
[cloudinator-remote]
type = webdav
url = https://files.domain.com/
vendor = other
user = admin
pass = ENCRYPTED_PASSWORD
```

Once saved, use the remote name in all commands:

```bash
rclone ls cloudinator:
rclone copy cloudinator:photos ./local-photos
```

---

## Mount as a Drive

rclone can mount the server as a local drive letter (Windows) or mount point (Linux/macOS). Unlike WebDAV native mounting, **no registry edits are required on Windows**.

### Windows — Mount as Drive Letter

**Prerequisites**: Install [WinFsp](https://winfsp.dev/rel/) (free, open source). This is a one-time install.

```powershell
# Download WinFsp
winget install WinFsp.WinFsp
```

**Mount WebDAV as Z: drive**:

```powershell
# Using named remote
rclone mount cloudinator: Z: --vfs-cache-mode full

# Using connection string (no config needed)
rclone mount :webdav,url=http://SERVER-IP:8080/,user=admin,pass=admin123: Z: --vfs-cache-mode full
```

Open File Explorer — you'll see `Z:` with your server files.

**Unmount**: Press `Ctrl+C` in the terminal, or:
```powershell
# In another terminal
rclone mount --umount Z:
# Or just close the rclone window
```

**Mount on startup** (Windows Task Scheduler):
1. Create a `.bat` file:
   ```bat
   rclone mount cloudinator: Z: --vfs-cache-mode full
   ```
2. Add to Task Scheduler with trigger "At log on"

### macOS — Mount as Volume

**Prerequisites**: Install [macFUSE](https://osxfuse.github.io/) (free).

```bash
rclone mount cloudinator: ~/cloudinator-drive --vfs-cache-mode full &
```

Unmount:
```bash
fusermount -u ~/cloudinator-drive    # Linux
umount ~/cloudinator-drive           # macOS
```

### Linux — Mount as Directory

```bash
# Install FUSE
sudo apt install fuse3   # Ubuntu/Debian

# Create mount point
mkdir -p ~/cloudinator

# Mount
rclone mount cloudinator: ~/cloudinator --vfs-cache-mode full --daemon

# Unmount
fusermount -u ~/cloudinator
```

**Persistent mount** (`/etc/fstab` equivalent — use systemd service):

```ini
# /etc/systemd/system/cloudinator-mount.service
[Unit]
Description=rclone mount for CloudinatorFTP
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USERNAME
ExecStart=/usr/bin/rclone mount cloudinator: /home/YOUR_USERNAME/cloudinator \
  --vfs-cache-mode full \
  --allow-other
ExecStop=/bin/fusermount -u /home/YOUR_USERNAME/cloudinator
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable cloudinator-mount
sudo systemctl start cloudinator-mount
```

### VFS Cache Modes Explained

| Mode | Disk Usage | Write Support | Best For |
|------|-----------|---------------|---------|
| `off` | None | Limited | Read-only browsing |
| `minimal` | Low | Files already cached | Mostly reading |
| `writes` | Low | ✅ Write cached | General use |
| `full` | High | ✅ Full cache | Best compatibility |

Use `--vfs-cache-mode full` for the best experience when editing files or using applications that expect random access.

---

## Sync & Copy

### Copy Local → Server (Backup)

```bash
# Copy everything in ~/Documents to the server's "documents" folder
rclone copy ~/Documents cloudinator:documents

# Copy with progress bar
rclone copy ~/Documents cloudinator:documents --progress

# Dry run (shows what would happen, no actual transfer)
rclone copy ~/Documents cloudinator:documents --dry-run
```

### Copy Server → Local (Download)

```bash
rclone copy cloudinator:photos ~/local-photos --progress
```

### Sync (one-way, makes destination identical to source)

```bash
# WARNING: sync DELETES files on the destination that aren't on the source
rclone sync ~/Documents cloudinator:documents --progress

# Always dry-run first!
rclone sync ~/Documents cloudinator:documents --dry-run
```

### Two-Way Sync (bisync)

```bash
# First run: initialize
rclone bisync ~/Documents cloudinator:documents --resync

# Subsequent runs
rclone bisync ~/Documents cloudinator:documents
```

### Filtered Copy

```bash
# Copy only JPG files
rclone copy ~/Photos cloudinator:photos --include "*.jpg"

# Copy everything except .tmp files
rclone copy ~/Documents cloudinator:docs --exclude "*.tmp"

# Copy files modified in the last 7 days
rclone copy ~/Documents cloudinator:docs --max-age 7d
```

### Scheduled Backup (Windows Task Scheduler)

Create `backup.bat`:
```bat
@echo off
rclone sync C:\Users\%USERNAME%\Documents cloudinator:documents-backup --log-file C:\rclone-backup.log --log-level INFO
```

Add to Task Scheduler → trigger "Daily at 11pm".

### Scheduled Backup (Linux cron)

```bash
crontab -e
# Add:
0 23 * * * /usr/bin/rclone sync ~/Documents cloudinator:documents-backup --log-file ~/rclone-backup.log
```

---

## Other Useful Commands

```bash
# List files with sizes
rclone ls cloudinator:

# List directories only
rclone lsd cloudinator:

# List files with details (like ls -l)
rclone lsl cloudinator:photos

# Check differences between local and remote
rclone check ~/Documents cloudinator:documents

# Delete a remote file
rclone delete cloudinator:old-file.txt

# Delete a remote folder and contents
rclone purge cloudinator:old-folder

# Move (copy + delete source)
rclone move ~/Downloads/file.zip cloudinator:archives/

# Show disk usage
rclone about cloudinator:

# Show file size
rclone size cloudinator:photos

# Cat a file (print contents)
rclone cat cloudinator:notes.txt

# Serve the remote as a local HTTP server (read-only preview)
rclone serve http cloudinator: --addr :8765
```

---

## Platform Notes

### Windows

- WinFsp required for `rclone mount`
- No registry edits needed (unlike native WebDAV)
- Password in config must be obscured: `rclone obscure yourpassword`
- If mount shows as read-only: add `--vfs-cache-mode writes` or `full`
- Use `rclone mount --network-mode` flag for network drive appearance

### macOS

- macFUSE required for `rclone mount`
- macFUSE requires a kernel extension approval on first install (System Preferences → Security)
- SFTP remote uses the system's known_hosts — accept the key with `ssh -p 2222 admin@SERVER-IP` first

### Linux

- Install `fuse3` or `fuse` package for mounting
- Add `user_allow_other` to `/etc/fuse.conf` if mounting for multiple users
- For systemd mount, ensure `--allow-other` flag is set

### Android (Termux)

```bash
# Mount is not supported on Android (no FUSE)
# Use copy/sync instead:
rclone copy ~/storage/dcim cloudinator:phone-backup --progress
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `no FUSE found` (Windows) | Install WinFsp from winfsp.dev |
| `no FUSE found` (Linux) | `sudo apt install fuse3` |
| `certificate verify failed` | Add `no_check_certificate = true` to remote config |
| `connection refused` | Check server is running; verify IP and port |
| Mount shows empty | Check `--vfs-cache-mode` setting; try `full` |
| Slow transfers | Increase `--transfers 8 --checkers 16` flags |
| Files appear read-only | Use `--vfs-cache-mode writes` or `full` |
| `401 Unauthorized` | Check username/password; ensure password is obscured with `rclone obscure` |
| SFTP key warning | Run `ssh -p 2222 admin@SERVER-IP` once to accept host key |
| FTP transfers stall | Open ports 60000-60100 in firewall; try `--ftp-disable-epsv` |
| Windows drive not visible in Explorer | Use `--network-mode` flag; or press F5 in Explorer |

### Debug Mode

```bash
rclone ls cloudinator: -vv 2>&1 | head -50
```

---

## rclone vs Native Protocol Clients — Summary

| | rclone | WinSCP | WebDAV Native | davfs2 | sshfs |
|--|--------|--------|--------------|--------|-------|
| **Windows drive mount** | ✅ (WinFsp) | ❌ | ✅ | ❌ | ❌ |
| **Linux mount** | ✅ | ❌ | ✅ | ✅ | ✅ |
| **macOS mount** | ✅ | ❌ | ✅ | ❌ | ✅ |
| **Sync/Backup** | ✅ | ⚠️ limited | ❌ | ❌ | ❌ |
| **GUI** | ❌ CLI only | ✅ | ✅ Explorer | ❌ | ❌ |
| **No registry (Windows)** | ✅ | ✅ | ❌ | ✅ | ✅ |
| **Works via domain/tunnel** | ✅ | ✅ | ✅ | ✅ | ❌ |

---

## Additional Resources

- [rclone Documentation](https://rclone.org/docs/)
- [rclone WebDAV Backend](https://rclone.org/webdav/)
- [rclone SFTP Backend](https://rclone.org/sftp/)
- [rclone FTP Backend](https://rclone.org/ftp/)
- [rclone Mount](https://rclone.org/commands/rclone_mount/)
- [WinFsp (Windows FUSE)](https://winfsp.dev/)
- [macFUSE](https://osxfuse.github.io/)