# CloudinatorFTP User Guide

**Version**: 1.2 | **Last Updated**: 2026-08-22  
**For**: End users accessing the web file manager (note: documentation for administration will come soon)

Welcome to **The Cloudinator** — a lightweight, secure file sharing platform that works across Windows, Linux, and Android (Termux).

> 🆕 **What's new in 1.2**: Public **Share Links** (Section 8) — send anyone a link to a file or folder without giving them a login, optionally protected by a passkey or admin approval, with expiry and download limits. The server itself was also migrated from Flask/Waitress to **Quart/Hypercorn**, adding **HTTP/2 and HTTP/3** support for the web UI and WebDAV HTTPS — nothing changes in how you use the app, but pages and downloads may feel snappier on modern browsers.

---

## 📋 Table of Contents

1. [Getting Started](#getting-started)
2. [Login & Authentication](#login--authentication)
3. [File Manager Interface](#file-manager-interface)
4. [Navigation & Browsing](#navigation--browsing)
5. [Uploading Files](#uploading-files)
6. [Downloading Files](#downloading-files)
7. [Advanced Search](#advanced-search)
8. [Sharing Files Publicly (Share Links)](#sharing-files-publicly-share-links)
9. [File Operations](#file-operations)
10. [Bulk Operations](#bulk-operations)
11. [Media Preview](#media-preview)
12. [Protocol Access — FTP, SFTP, WebDAV, SMB](#protocol-access--ftp-sftp-webdav)
13. [Tips & Tricks](#tips--tricks)
14. [Troubleshooting](#troubleshooting)

---

## Getting Started

### System Requirements

- **Browser**: Chrome, Firefox, Safari, Edge (or any modern browser)
- **Internet Connection**: Required (optional Cloudflare Tunnel for internet access)
- **JavaScript**: Enabled (required for file manager)

### First Login

1. Navigate to your Cloudinator instance (e.g., `http://localhost:5000` or your custom domain)
2. You'll see the **login page** with "The Cloudinator" header
3. Enter your **username** and **password**
4. Click **Login**

**Default Credentials**:
- **admin** / **admin123** (read/write access)
- **guest** / **guest123** (read-only access)

**Change Default Credentials**:
```bash
python create_user.py
# Select: 2. Add user
# Or: 3. Change password
```

> ⚠️ **Security**: Always change default passwords before exposing to the internet or other users!

---

## Login & Authentication

### Session Management

Your login session is valid for **1 hour** (default setting). After that:
- You'll be automatically redirected to the login page
- Your files remain safe — only your session expired

### Session Expiration

Sessions can end for two reasons:

1. **Time Expired**: 1 hour of inactivity (default)
   - Configured in `config.py`: `PERMANENT_SESSION_LIFETIME = 3600`
   - Adjust as needed for your use case

2. **Token Revoked**: An admin ran `python kick_sessions.py` (this replaced the older `revoke_session.py` script)
   - `kick-all` logs out every connected user within a few seconds
   - `logout-web` logs out only the web UI, leaving WebDAV/SFTP/FTP/SMB sessions alone
   - Also used to instantly revoke one user (`rotate`/`delete`) — useful for security incidents or testing

### Browser History

The file manager cleans up browser history after login:
- Prevents the back button from returning to login page
- Keeps you on the file manager when navigating forward

### Logging Out

Click the **Logout** button in the top-right corner:
- Your session is cleared
- You're redirected to login page
- Session cookie is deleted

---

## File Manager Interface

### Layout Overview (Top to Bottom)

```
┌─────────────────────────────────────────────────────────┐
│  HEADER                                                 │
│  🏠 Cloudinator  │  User: alice [readwrite] │ Logout    │
├─────────────────────────────────────────────────────────┤
│  STORAGE STATS (Real-time)                              │
│  📊 1,234 files | 87 folders | Total: 1.5 TB            │
├─────────────────────────────────────────────────────────┤
│  UPLOAD AREA                                            │
│  📥 Upload Files  📁 Upload Folders                      │
├─────────────────────────────────────────────────────────┤
│  BULK ACTIONS (shown when files are selected)           │
│  ☐ Select All  │  ⬇️ Download ZIP  🗑️ Delete            │
├─────────────────────────────────────────────────────────┤
│  FOLDER PATH & CREATE FOLDER                            │
│  📍 Root / photos / 2024  │  ➕ New Folder              │
├─────────────────────────────────────────────────────────┤
│  SEARCH CONTAINER                                       │
│  🔍 Search (e.g., *.pdf, report *.jpg, ...)            │
├─────────────────────────────────────────────────────────┤
│  FILE TABLE                                             │
│  ☐ | Name | Size | Type | Modified | Actions           │
│  ☐ | vacation.jpg | 2.5 MB | Image | 2024-03-15 | ⋯   │
│  ☐ | memories/ | — | Folder | — | ⋯                   │
└─────────────────────────────────────────────────────────┘
```

### Header & Top Navigation

| Element | Purpose |
|---------|---------|
| **Cloudinator Logo** | Click to go to home directory |
| **User Badge** | Shows your username and role |
| **Role Badge** | "readwrite" (admin) or "readonly" (guest) |
| **Logout Button** | Sign out and return to login |

### Permission Levels

| Role | Permissions |
|------|-------------|
| **readwrite** (Admin) | View, upload, download, delete, rename, create folders |
| **readonly** (Guest) | View and download only — no upload/delete/modify |

### Storage Information

Real-time stats displayed below header:

| Stat | Shows |
|------|-------|
| **File count** | Total number of files |
| **Folder count** | Total number of folders  |
| **Total size** | Combined storage used |

**Example**: "📊 1,234 files | 87 folders | Total: 1.5 TB"

---

## Uploading Files

### Upload Area

Two upload options displayed at the top:

- **📥 Upload Files**: Select individual files from your computer (single or multiple)
- **📁 Upload Folders**: Select an entire folder with all subfolders

### Single File Upload

1. Click **📥 Upload Files**
2. Browser file picker opens
3. Select one file or multiple files (Ctrl+Click to select multiple)
4. Files begin uploading automatically

### Folder Upload

1. Click **📁 Upload Folders**
2. Select a folder from your computer
3. Entire folder structure uploads with all files

### Drag & Drop Upload

1. Drag files/folders from your computer
2. Drop them anywhere over the file table
3. Upload starts automatically

### Real-Time Progress

- **Progress bar** shows upload percentage
- **File count** shows "1/5 uploading"
- **Current speed** shown (e.g., "2.5 MB/s")

### Large File Uploads (>1GB)

Chunked upload system automatically activates:
- Files split into **10 MB chunks**
- If connection drops, resume from next chunk (saves bandwidth)

---

## Bulk Actions

Bulk actions bar appears when you select files:

```
☐ Select All  │  ⬇️ Download ZIP  🗑️ Delete
```

### Download as ZIP

1. Select multiple files/folders using checkboxes
2. Click **⬇️ Download ZIP**
3. Browser prompts to save `backup.zip`

### Delete Multiple Files

1. Select files using checkboxes
2. Click **🗑️ Delete**
3. Confirm deletion (cannot be undone)

---

## Navigation & Folder Management

### Breadcrumb Navigation

Shows your current location:

```
📍 Root / photos / 2024
```

Click any part to jump to that directory.

### Create Folder

The **➕ New Folder** button appears next to breadcrumb:

1. Click **➕ New Folder**
2. Enter folder name
3. Press **Enter** or click **Create**

---

## Search

The search bar accepts plain text and **extension filters**:

### Search by Name

```
report
```
Finds all files with "report" in the name (case-insensitive).

**Examples**:
- `meeting` → finds "meeting_notes.txt", "team-meeting.pdf", etc.
- `2024` → finds "photo_2024.jpg", "2024_backup.zip", etc.

### Search by Extension

```
*.css
```
Finds all CSS files.

**Examples**:
- `*.jpg` → all JPEG images
- `*.mp4` → all MP4 videos
- `*.pdf` → all PDF documents

### Multiple Extensions

```
*.css,js,ts
```
Finds all CSS, JavaScript, and TypeScript files.

**Examples**:
- `*.jpg,png,gif` → all image formats
- `*.mp4,mkv,avi` → all video formats
- `*.py,js,go` → all code files

### Name + Extension (Any Order)

```
report *.pdf
```
or
```
*.pdf report
```

Finds PDFs with "report" in the name.

**Examples**:
- `data *.csv` → CSV files with "data" in name
- `*.js analytics` → JavaScript files named "analytics"
- `backup *.zip,tar` → ZIP or TAR archives with "backup" in name

### Search Examples

| Query | Finds |
|-------|-------|
| `budget` | All files with "budget" in name (any type) |
| `*.xlsx` | All Excel spreadsheets |
| `2024 *.jpg` | JPG files with "2024" in name |
| `*.py,java,cpp` | Python, Java, C++ source files |
| `contract *.pdf,doc` | PDF or DOC files with "contract" |
| `*.mp4` | All MP4 videos in entire storage |

---

## Sharing Files Publicly (Share Links)

Share Links let you send someone a file or folder without giving them a Cloudinator login. Anyone with the link can view/download it in their browser at `https://YOUR-SERVER/shared/<token>` — the link uses a random opaque token, never the real file path, so it doesn't reveal anything about your folder structure.

**Note**: Only **readwrite** (admin) users can create or manage shares. Readonly users don't see the share button.

### Creating a Share

1. Hover over a file or folder row (or tap on mobile)
2. Click the **🔗 share** button in the Actions column
3. The **Share** modal opens — choose your protection level (see below), then click **Create Link**
4. The link appears in the modal with a **Copy Link** button

### Protection Levels

| Mode | Behavior |
|------|----------|
| **Public** | Anyone with the link can view/download immediately — no extra step |
| **Passkey** | Visitors must enter a PIN/passphrase before the download unlocks. Set your own passkey, or let Cloudinator generate a random one. The passkey is shown to you **once**, at creation — copy it down, it can't be viewed again (only regenerated) |
| **Approval** | Visitors submit their name (and an optional note) and wait for you to approve the request from the **Manage Shared** panel. You choose how many downloads each approval allows before it locks again |

### Expiry

Every share can optionally expire:
- Pick a **preset** (e.g. 1 hour, 1 day, 7 days) or set a **custom date/time**
- Leave it unset for a link that never expires
- Once a link expires, visitors see "Link Not Available" — the same message shown for a revoked link

### Sharing a Folder

If you share a folder, visitors get a built-in **folder browser** on the landing page (once unlocked) — they can navigate into subfolders, download individual files, or check multiple items and **Download Selected** as a zip, without needing to download the entire folder at once. A top-level **Download All (.zip)** button is always available too.

### Bulk Share / Unshare

From the bulk-actions bar (select files with checkboxes first):
1. Click **Share Selected** to create links for every selected item at once (same protection-level options apply to all of them)
2. Click **Unshare Selected** to revoke links for every selected item at once

### Managing Active Shares — "Manage Shared" Panel

Click **Manage Shared** (readwrite users only) to open a panel with three tabs:

| Tab | Shows |
|-----|-------|
| **Active Shares** | Every currently-live share link — edit its protection level, passkey, or expiry, copy the link again, or revoke it individually |
| **Pending Requests** | Approval-mode requests waiting on a decision — **Approve** or **Deny** each one. A badge on the Manage Shared button shows the live pending count and updates automatically (no need to refresh) |
| **Revoke All** | Danger zone — instantly revokes **every** active share link at once |

**Revoke All confirmation**: To prevent an accidental click from nuking every link, this button requires you to type a random 10-digit code shown on screen (a fresh one every attempt) before it proceeds.

### Revoking a Single Share

From the file table: open the share modal for that item again and click **Revoke**. From Manage Shared → Active Shares: click **Revoke** next to that entry.

### Command-Line Revocation (revoke_sharing.py)

For scripting or when you don't want to use the web UI:
```bash
python revoke_sharing.py            # interactive menu (loops until Exit)
python revoke_sharing.py list       # list all active shares
python revoke_sharing.py revoke <token>
python revoke_sharing.py revoke-all # requires its own typed confirmation
```

### What the Visitor Sees

A visitor who opens a share link with no protection sees the item name, size, and a **Download** button immediately. A passkey-protected link shows a PIN entry field first. An approval-gated link shows a **Request Access** form; after submitting, the page automatically polls and updates itself once you approve or deny — the visitor doesn't need to keep refreshing.

---

## File Table

### File Table Columns

| Column | Shows | Details |
|--------|-------|---------|
| **☐** | Checkbox | Select multiple files for bulk operations |
| **Name** | File/folder name | Click name to open folder or preview file |
| **Size** | File size | Folder sizes shown as "—" (recursive size available in search) |
| **Type** | File type | Image, Video, PDF, Folder, Archive, etc. |
| **Modified** | Last edited date | "2024-03-15 14:30" format (hidden on mobile) |
| **Actions** | Quick buttons | Download, preview, delete, etc. |

### Responsive Columns (Mobile)

The table adjusts based on screen width:

- **Mobile (<600px)**: ☐ | Name | Size | Actions (type + modified hidden)
- **Tablet (600-899px)**: ☐ | Name | Size | Type | Actions (modified hidden)
- **Desktop (≥900px)**: All columns visible

### Opening Folders

1. Click the **folder name** in the table, OR
2. Click the **folder icon** next to the name

---

## Downloading Files

### Download Single File

1. Hover over file row (or tap on mobile)
2. Click the **⬇️ download** button in the Actions column
3. File downloads to your computer's default download folder

### Download Speed

Download speed depends on:
- Your internet connection bandwidth
- Server's disk I/O performance
- File size and compression

---

## Media Preview

📄 annual_report_2024.pdf       1.2 MB  📍 documents/finance/
📄 sales_report_q1.pdf           890 KB  📍 documents/reports/q1/
```

**Click any result** to:
- Download the file, OR
- Preview it in the viewer, OR
- Navigate to the file's folder

### Search Performance

- **Small storage** (< 100 files): Near-instant
- **Medium storage** (1,000-10,000 files): 0.5-3 seconds
- **Large storage** (>100,000 files): May take 5-10 seconds

**Performance Tips**:
- Use extension filters: `*.pdf` narrows search scope
- Run `/admin/rebuild_cache` if search index is stale
- Monitor file monitor reconciliation: `/api/monitoring_status`

**Tuning**:
Adjust `file_monitor.py` for your workload:
```python
RECONCILE_INTERVAL = 900       # 15 min: adjust for your storage
BURST_THRESHOLD = 200          # Lower = more frequent walks
```

---

## File Operations

### Rename File

1. Hover over file (or long-press on mobile)
2. Click **✏️ rename** button
3. A text field appears with current name
4. Type new name and press **Enter**
5. File is renamed instantly

**Note**: Readonly users cannot rename.

### Delete File/Folder

1. Hover over file (or long-press on mobile)
2. Click **🗑️ delete** button
3. Confirmation dialog appears: "Delete <filename>?"
4. Click **"Yes, delete"** to confirm
5. File/folder removed permanently

**Warning**: Deletion is **permanent and unrecoverable**.

**Note**: Readonly users cannot delete.

### Create New Folder

1. In the controls bar, type folder name in **"New Folder"** input
2. Press **Enter** or click **➕ Create**
3. New folder appears in file listing
4. To rename: use rename operation above

**Example**:
```
📝 Input: my_photos
Result: Creates folder named "my_photos"
```

### Move Files (via Download/Upload)

Currently, Cloudinator doesn't support drag-to-move. Instead:

1. **Download** file from source folder
2. **Navigate** to destination folder
3. **Upload** file to new location
4. **Delete** from old location (if needed)

> **Tip**: Use bulk download as ZIP, then upload to new location.

---

## Bulk Operations

### Select Multiple Files

**Method 1: Checkbox Selection**
1. Click the **☐ checkbox** next to each file you want
2. Or click **☐** in table header to select ALL files on current page

**Method 2: Shift+Click**
1. Click first file's checkbox
2. Hold **Shift** and click last file's checkbox
3. All files between are selected

### Bulk Actions Bar

Once files are selected, a blue bar appears:

```
🔵 3 files selected
[📦 Download as ZIP] [🗑️ Delete Selected]
```

### Bulk Download (as ZIP)

1. Select 1+ files/folders
2. Click **📦 Download as ZIP**
3. All selected items are bundled into `backup.zip`
4. Browser downloads the archive

### Bulk Delete

1. Select 1+ files/folders
2. Click **🗑️ Delete Selected**
3. Confirmation: "Delete 3 files permanently?"
4. Click **"Yes, delete"** to confirm
5. All selected files deleted

**Warning**: Bulk deletion is permanent.

### Deselect All

Click the **☐** checkbox in the table header again to deselect all.

---

## Media Preview

### Supported File Types

| Type | Preview Method | Supported Formats |
|------|-----------------|-------------------|
| **Images** | Web viewer (with WebP conversion) | JPG, PNG, GIF, BMP, WebP |
| **Video** | HTML5 player (HLS streaming) | MP4, WebM, MKV, AVI, WMV, FLV |
| **Audio** | HTML5 player | MP3, WAV, OGG, M4A |
| **Documents** | Embedded HTML preview | DOCX (Word), XLSX (Excel), PPTX (PowerPoint) |
| **PDF** | PDF.js viewer | PDF documents |
| **Archives** | File listing | ZIP, RAR, 7Z |
| **Text** | Code viewer with syntax highlighting | TXT, JSON, XML, CSV, LOG, MD, PY, JS, etc. |

### Preview a File

1. Click the **👁️ preview** button, OR
2. Click the filename itself
3. Preview opens in a modal or new view

**Note**: Preview is read-only. To modify, download the file, edit locally, and re-upload.

### Image Preview

- **Format**: JPG, PNG, GIF, BMP, WebP
- **Large images** (>1 MB): Automatically converted to **WebP** for faster loading
- **Quality**: Lossy compression (quality 50, adjustable)
- **Features**:
  - Zoom in/out with mouse wheel or pinch
  - Download original size
  - Next/previous image navigation

### Video Streaming

- **Format**: MP4, WebM, or MKV/AVI/WMV (converted to HLS)
- **Streaming**: Large videos (>50 MB) use **HLS streaming** for smooth playback
- **Controls**:
  - Play / Pause
  - Seek / Timeline scrubbing
  - Volume control
  - Fullscreen
  - Captions (if available)
  - Playback speed (0.5x to 2x)

**Note**: First time playing a video may take 30 seconds as it's transcoding.

### Document Preview

**Word Documents (DOCX)**:
- Rendered as clean HTML
- Formatting preserved (fonts, colors, tables)
- Embedded images shown

**Excel Spreadsheets (XLSX)**:
- Displays active sheet
- Formulas calculated
- Tables formatted

**PowerPoint (PPTX)**:
- Shows slide thumbnails
- Click to navigate between slides
- Animations not supported

### PDF Viewing

- Uses **PDF.js** viewer (Mozilla's open-source library)
- Features:
  - Page navigation
  - Zoom in/out
  - Search within PDF
  - Download original PDF
  - Print

### Archive Preview

- **ZIP**, **RAR**, **7Z**: List all contents
- Shows:
  - Filename
  - Size (uncompressed and compressed)
  - Compression ratio
- Option to download entire archive

### Text File Preview

- Displays plain text with syntax highlighting
- Supported languages: Python, JavaScript, JSON, XML, SQL, HTML, CSS, etc.
- Features:
  - Line numbers
  - Syntax coloring
  - Copy to clipboard

---

## Protocol Access — FTP, SFTP, WebDAV, SMB

In addition to the web UI, CloudinatorFTP runs four additional protocol servers. These use the **same username and password** as the web interface — no separate credentials needed. SMB is the one exception — it's off by default until a one-time setup is run (see below).

> 💡 **These are optional extras.** The web UI at `http://SERVER:5000` always works regardless of these protocols.

> 🆕 The web UI and WebDAV HTTPS now run on **Hypercorn**, which speaks **HTTP/2** and **HTTP/3** in addition to HTTP/1.1 — modern browsers and WebDAV clients pick these up automatically, no configuration needed. If the server is running on a [Tailscale](https://tailscale.com) network, it will automatically request a real trusted certificate for the device's `*.ts.net` name instead of the self-signed one below (falling back to self-signed if Tailscale isn't installed/logged in) — so on a Tailscale machine you can usually skip the certificate-import steps entirely.

### Port Reference

| Protocol | Port | Best For |
|----------|------|----------|
| Web UI | 5000 | Browser access |
| WebDAV HTTP | 8080 | Network drive mapping |
| WebDAV HTTPS | 8443 | Network drive mapping (secure, recommended) |
| SFTP | 2222 | WinSCP, FileZilla, command-line `sftp` |
| FTP | 2121 | Legacy FTP clients |
| SMB | 445 (8445 fallback) | Native network drive, `\\HOST\SharedFolder` |

---

### 🌐 WebDAV — Map as a Network Drive

WebDAV lets you mount the server as a drive letter (Windows) or volume (macOS/Linux) so you can drag-and-drop files in File Explorer — no browser needed.

#### Windows — Map as Drive Letter

**First-time setup** (elevated PowerShell, once per machine):
```powershell
# Enable the WebClient service
Set-Service WebClient -StartupType Automatic; Start-Service WebClient

# For HTTP (port 8080): allow Basic Auth over plain HTTP
reg add "HKLM\SYSTEM\CurrentControlSet\Services\WebClient\Parameters" /v BasicAuthLevel /t REG_DWORD /d 2 /f
Restart-Service WebClient
```

**Map the drive**:
```cmd
# HTTP (after registry fix above)
net use X: http://SERVER-IP:8080/ /user:admin admin123 /persistent:yes

# HTTPS (no registry fix needed — just import the cert once first)
net use X: https://SERVER-IP:8443/ /user:admin admin123 /persistent:yes
```

**Import HTTPS certificate (one-time, elevated PowerShell)**:
```powershell
# Download and import in one line — no file copying needed
$f="$env:TEMP\c.crt"
Invoke-WebRequest http://SERVER-IP:8080/webdav.crt -OutFile $f
Import-Certificate $f -CertStoreLocation Cert:\LocalMachine\Root
del $f
```

After mapping, the server appears as a drive in **This PC** — copy, paste, rename, and delete files just like a local drive.

#### macOS — Mount as Volume

**Finder:**
1. Finder → Go → Connect to Server (`⌘K`)
2. Enter: `http://SERVER-IP:8080` or `https://SERVER-IP:8443`
3. Click Connect → enter credentials

The server appears as a removable volume on the Desktop.

#### Linux — Mount with davfs2

```bash
sudo apt install davfs2
sudo mount -t davfs http://SERVER-IP:8080/ /mnt/cloudinator
# Enter credentials when prompted

# Unmount
sudo umount /mnt/cloudinator
```

**Persistent mount** (add to `/etc/fstab`):
```
http://SERVER-IP:8080/ /mnt/cloudinator davfs user,auto,_netdev 0 0
```

---

### 🔒 SFTP — WinSCP / FileZilla / Command Line

SFTP is the most compatible protocol for file transfer clients. Credentials are the same as the web UI.

#### WinSCP Setup

1. Open WinSCP → click **New Session**
2. Set:
   - **File protocol**: SFTP
   - **Host name**: your server IP
   - **Port number**: `2222`
   - **User name**: your Cloudinator username
   - **Password**: your Cloudinator password
3. Click **Login**
4. **First connection**: WinSCP shows a host key warning — click **Accept** to cache it (you only see this once)

#### FileZilla Setup

1. File → Site Manager → New Site
2. **Protocol**: SFTP
3. **Host**: your server IP
4. **Port**: `2222`
5. **Logon Type**: Normal
6. **User / Password**: your Cloudinator credentials
7. Click Connect

#### Command Line (Linux / macOS / Windows Terminal)

```bash
sftp -P 2222 admin@SERVER-IP

# Then use standard sftp commands:
ls          # list files
get file    # download
put file    # upload
exit
```

#### sshfs — Mount as Filesystem (Linux / macOS)

```bash
# Install sshfs
sudo apt install sshfs   # Ubuntu/Debian
brew install macfuse     # macOS (then install sshfs)

# Mount
sshfs -p 2222 admin@SERVER-IP:/ /mnt/cloudinator

# Unmount
fusermount -u /mnt/cloudinator   # Linux
umount /mnt/cloudinator           # macOS
```

---

### 📁 FTP — Legacy FTP Clients

FTP is supported for compatibility with older clients. Use SFTP or WebDAV if possible — FTP sends credentials in plaintext and should only be used on trusted local networks.

> ⚠️ **Security Warning**: FTP transmits passwords in cleartext. Do not use FTP over the internet.

#### WinSCP FTP Setup

1. Open WinSCP → New Session
2. Set:
   - **File protocol**: FTP
   - **Encryption**: No encryption
   - **Host name**: your server IP
   - **Port number**: `2121`
   - **User name / Password**: your Cloudinator credentials
3. Click Login

#### FileZilla FTP Setup

1. File → Site Manager → New Site
2. **Protocol**: FTP
3. **Host**: your server IP
4. **Port**: `2121`
5. **Encryption**: Use plain FTP
6. **Logon Type**: Normal
7. **User / Password**: credentials
8. Connect

#### Windows Firewall Note

FTP requires two port ranges open:
```powershell
# Control channel
New-NetFirewallRule -DisplayName "CloudinatorFTP FTP" -Direction Inbound -Protocol TCP -LocalPort 2121 -Action Allow
# Passive data ports (required for file transfers)
New-NetFirewallRule -DisplayName "CloudinatorFTP FTP Passive" -Direction Inbound -Protocol TCP -LocalPort 60000-60100 -Action Allow
```

---

### 📡 SMB — Native Network Drive

SMB gives you the most "just works" experience — `\\HOST\SharedFolder` shows up like any other network drive, no client software needed on Windows. The trade-off: unlike WebDAV/SFTP/FTP, it needs a **one-time machine setup** before it's usable (port 445 is normally taken by Windows' own file sharing), and it's **off by default** until that's done.

> 💡 If you'd rather skip the setup step entirely, WebDAV gives a very similar mapped-drive experience with zero extra configuration — see above.

**One-time setup** (run once, on the server):
```bash
python smb_setup.py
```
Walks you through it per platform — Windows needs a restart afterward (never done automatically, only requested), Linux takes effect immediately, Android needs root. Full details: `docs/SMB_PROTOCOL_DEPLOYMENT.md`.

**After setup, map the drive (Windows):**
```cmd
net use X: \\SERVER-IP\SharedFolder /persistent:yes
```

**macOS:** Finder → Go → Connect to Server → `smb://SERVER-IP/SharedFolder`

**Linux:**
```bash
sudo mount -t cifs //SERVER-IP/SharedFolder /mnt/cloudinator -o username=admin,password=admin123
```

**Before setup is done (port 8445 fallback)** — only Windows 11 24H2+ / Server 2025+ can map a non-445 SMB share natively:
```cmd
net use X: \\SERVER-IP\SharedFolder /TCPPORT:8445 /persistent:yes
```

> ⚠️ **If your account existed before SMB support was added**, you'll need to reset your password once (even to the same value) before SMB accepts your login — this is a requirement of how SMB authentication works, not something specific to CloudinatorFTP.

---

### 🔧 rclone — Advanced Sync & Mount

rclone can connect to CloudinatorFTP via WebDAV, SFTP, or FTP and provides powerful sync, copy, and mount features. See `docs/RCLONE_DEPLOYMENT.md` for full setup instructions.

**Quick example** (WebDAV mount):
```bash
rclone mount :webdav,url=http://SERVER-IP:8080/,user=admin,pass=admin123: Z: --vfs-cache-mode full
```

---

## Tips & Tricks

### 1. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| **Ctrl+A** (Windows/Linux) | Select all files |
| **Cmd+A** (Mac) | Select all files |
| **Escape** | Close modal/preview |
| **Enter** | Confirm action (rename, create folder) |
| **Delete** | Delete selected files (with confirmation) |

### 2. Speed Up Uploads

- **Use WiFi** instead of mobile data (faster, more stable)
- **Upload near server** if using local network
- **Avoid uploading during peak hours**
- **Close other browser tabs** to free up bandwidth

### 3. Speed Up Downloads

- **Download as ZIP** if getting multiple files (faster than individual)
- **Close other downloads** to dedicate bandwidth
- **Use wired connection** for large files

### 4. Find Large Files Quickly

Search for specific file types, then sort by size:
```
*.mp4  → find all videos
```
Look for the largest video files to identify space hogs.

### 5. Organize with Folders

Create a folder structure before uploading:
```
media/
  photos/
  videos/
  documents/
```

Then upload files to appropriate folders.

### 6. Backup Important Files

**Regularly download backups**:
1. Select important folders
2. **Download as ZIP**
3. Store on local computer and cloud storage

### 7. Search by Date

While Cloudinator doesn't have date filter, you can organize files by date:
```
2024-01 files → 2024-02 files → etc.
```

### 8. Clean Up Old Uploads

Watch **"Orphaned chunks"** stat (shows incomplete uploads):
- Click **🧹 Cleanup** button to remove partial uploads
- Or run: `curl -X POST http://localhost:5000/admin/cleanup_chunks`
- Frees disk space automatically (24-hour auto-purge also runs)

---

## Troubleshooting

### Common Issues

#### Issue: "Session Expired" Message

**Cause**: 
- 1 hour of inactivity, OR
- Administrator revoked all sessions

**Solution**:
1. Click **"Return to Login"**
2. Enter credentials again
3. You'll be back at file manager

**Prevention**:
- Keep browser tab active
- To change timeout: `PERMANENT_SESSION_LIFETIME` in `config.py`
- Re-login before timeout expires

---

#### Issue: Upload Stuck at 50%

**Cause**: 
- Network interruption
- Large chunk (10 MB) hitting timeout
- Server connection lost

**Solution**:
1. Click **⊗ Stop** to cancel upload
2. Wait 30 seconds
3. Try uploading again (resumes from last chunk)

**Workaround**:
- Reduce `CHUNK_SIZE` in `config.py` (e.g., 5 MB instead of 10 MB)
- Check internet connection stability
- Increase timeout in Quart/Hypercorn config if needed

---

#### Issue: File Search Returns No Results

**Cause**: 
- File doesn't exist in storage
- Typo in search term
- File in different folder than expected

**Solution**:
1. Try searching by **extension only** (e.g., `*.pdf`)
2. Browse folders manually to find file
3. Check if file name is correct

**Tip**: Use extension search to narrowly scope:
```
*.pdf report  → finds "report*.pdf" files
```

---

#### Issue: Video Plays But No Sound

**Cause**: 
- Browser audio muted
- Video codec not supported
- HLS transcoding failed

**Solution**:
1. Check **browser volume** (not player volume)
2. Check **system volume** on your computer
3. Try a different browser (Chrome vs Firefox)
4. Check server logs: `python prod_server.py 2>&1 | grep -i audio`
5. Ensure FFmpeg is installed: `ffmpeg -version`

---

#### Issue: Image Thumbnails Won't Load

**Cause**: 
- WebP conversion not available
- Browser doesn't support WebP
- Corrupted image file

**Solution**:
1. Try in different browser (Chrome has best WebP support)
2. Check `ENABLE_LIBVIPS` in `config.py`: set to `False` to disable WebP conversion
3. Verify libvips is installed: `vips --version`
4. Try downloading and viewing locally

---

#### Issue: Can't Rename or Delete (Readonly User)

**Cause**: Your account has **readonly role**

**Solution**:

Upgrade your own account to readwrite:
```bash
python create_user.py
# Select: 4. Change role
# Choose: readwrite
```

Or set up a readwrite user:
```bash
python create_user.py
# Select: 2. Add user
# Enter credentials and select "readwrite" role
```

---

#### Issue: Folder Shows "0 files" But Files are There

**Cause**: 
- Cache not refreshed
- Large folder not indexed yet
- Files hidden or moved

**Solution**:
1. Refresh browser: **F5** or **Ctrl+R**
2. Rebuild cache:
   ```bash
   curl -X POST http://localhost:5000/admin/rebuild_cache
   ```
   Or monitor progress: `GET /api/monitoring_status`
3. Use search to find files

---

#### Issue: Download Speed Very Slow

**Cause**: 
- Server overloaded
- Disk I/O bottleneck
- Network congestion
- Large ZIP generation in progress

**Solution**:
1. Check server stats: `GET /api/disk_stats_fast`
2. Monitor active downloads:
   ```bash
   curl http://localhost:5000/api/monitoring_status | jq
   ```
3. Check system resources: `top` or Task Manager
4. Consider upgrading disk or splitting large downloads
5. Download smaller files first to test baseline speed

---

#### Issue: "Link Not Available" on a Share Link

**Cause**: The link expired, was individually revoked, or an admin used **Revoke All** in Manage Shared

**Solution**: Ask the file owner to create a new share link — there's no way to recover the old one, it's gone by design once revoked/expired.

---

#### Issue: Share Request Stuck on "Waiting for Approval"

**Cause**: No admin has approved or denied it yet, or the browser tab lost its polling connection

**Solution**:
1. Ask the file owner to check **Manage Shared → Pending Requests**
2. If it's not listed there, the request may not have reached the server — try requesting access again
3. Refreshing the page re-checks the current status immediately

---

#### Issue: WebDAV Drive Shows "Inaccessible" on Windows

**Cause**: WebClient service not started, or BasicAuthLevel not set

**Solution** (elevated PowerShell):
```powershell
Set-Service WebClient -StartupType Automatic; Start-Service WebClient
reg add "HKLM\SYSTEM\CurrentControlSet\Services\WebClient\Parameters" /v BasicAuthLevel /t REG_DWORD /d 2 /f
Restart-Service WebClient
```
Then retry `net use`.

---

#### Issue: SFTP Login Fails in WinSCP

**Cause**: Host key dialog was dismissed, or wrong port

**Solution**:
1. Ensure port is set to **2222** (not 22)
2. On first connection, click **Accept** when WinSCP shows the host key warning
3. Verify server IP with `ipconfig` on the server machine

---

#### Issue: FTP Connects but File Transfer Stalls

**Cause**: Passive data ports (60000-60100) blocked by firewall

**Solution** (elevated PowerShell):
```powershell
New-NetFirewallRule -DisplayName "CloudinatorFTP FTP Passive" -Direction Inbound -Protocol TCP -LocalPort 60000-60100 -Action Allow
```

---

#### Issue: SMB Stuck on Port 8445 / Won't Use Port 445

**Cause**: The one-time setup hasn't been run yet, or Windows hasn't been restarted since it was

**Solution**:
```bash
python smb_setup.py
```
On Windows, restart the machine afterward (use **Restart**, not Shut Down) — port 445 only releases on a true reboot.

---

#### Issue: SMB Login Fails Even With the Correct Password

**Cause**: Your account existed before SMB support was added — SMB needs a special hash of your password that can only be captured the moment it's set

**Solution**: Reset your password once (even to the same value) via `create_user.py` or the web UI

---

### Self-Help Commands

| Issue | Command |
|-------|----------|
| Account permissions wrong | `python create_user.py` → change role |
| Reset default credentials | `python reset_db.py` (destructive) or `python create_user.py` |
| Cache stale | `curl -X POST http://localhost:5000/admin/rebuild_cache` |
| Orphaned upload chunks | `curl -X POST http://localhost:5000/admin/cleanup_chunks` |
| Storage full | Check `ROOT_DIR` in `config.py` → configure larger path |
| Search slow | `file_monitor.py` tuning → adjust `RECONCILE_INTERVAL` |
| Upload timeout | `config.py`: increase `PERMANENT_SESSION_LIFETIME` |
| Check health | `curl http://localhost:5000/api/health_check` |
| Regenerate WebDAV cert | `python ssl_cert.py --regenerate` |
| Set up SMB (port 445) | `python smb_setup.py` |
| Lock someone out quickly | `python kick_sessions.py` |
| Revoke a share link (or all of them) | `python revoke_sharing.py` |
| See who has active share links | `curl http://localhost:5000/admin/shares` (readwrite session required) |

---

## Frequently Asked Questions

### Q: How long does my login session last?

**A:** Standard session is **1 hour** of inactivity. After that, you're automatically logged out. Contact administrator to change this.

### Q: Are my files safe?

**A:** Files are:
- ✅ Stored on your server
- ✅ Protected by user authentication (bcrypt hashing)
- ❌ NOT encrypted at rest (only session encryption via Fernet)
- ❌ NOT backed up (organize your own backups)

**To enable encryption**:
- Files are stored in plaintext in `ROOT_DIR`
- Database is encrypted via Fernet (see `db/secret.key`)
- Consider OS-level encryption for production

### Q: Can I share files with other users?

**A:** Multiple approaches:

1. **Share Link (no login needed)**: Click the **🔗 share** button on any file/folder to generate a public link — optionally protected with a passkey or admin approval, with an expiry. See [Sharing Files Publicly](#sharing-files-publicly-share-links). This is the fastest option for sharing with people who shouldn't have a full account.

2. **Same Server**: Create additional user accounts
   ```bash
   python create_user.py  # Add new user
   ```
   They can then browse and download shared files.

3. **Different Server**: Create second instance on different port
   ```bash
   # In config.py, change PORT to 5001
   python prod_server.py
   ```

4. **Public URL**: Set up Cloudflare Tunnel (see `docs/SETUP_TUNNEL_ADVANCED.md`)
   - Expose to internet with custom domain

### Q: What file types are supported?

**A:** Almost all files! Cloudinator supports:

**Preview in Browser**:
- ✅ Images (JPG, PNG, GIF, WebP) — with WebP conversion
- ✅ Videos (MP4, WebM, MKV, AVI) — with HLS streaming
- ✅ Documents (DOCX, XLSX, PPTX, PDF)
- ✅ Archives (ZIP, RAR, 7Z) — listing only
- ✅ Text files (TXT, JSON, XML, CSV, LOG, MD, PY, JS, etc.)
- ✅ Audio (MP3, WAV, OGG, M4A)

**Upload/Download**:
- ✅ Any file type (no restrictions by default)
- Configure `ALLOWED_EXTENSIONS` in `config.py` to restrict

**Note**: Large media files >50MB use HLS streaming (requires FFmpeg)

### Q: Is there a file size limit?

**A:** Default maximum is **16 GB**.

**To increase**:
```python
# config.py
MAX_CONTENT_LENGTH = 32 * 1024 * 1024 * 1024  # 32 GB
```
Restart server for changes to take effect.

### Q: Can I upload directly from URL?

**A:** No, currently only local file upload supported. Download file locally first, then upload.

### Q: Where are my files stored?

**A:** In `ROOT_DIR` configured in `config.py` or `storage_config.json`.

**Check current location**:
```python
from config import ROOT_DIR
print(f"Files stored in: {ROOT_DIR}")
```

**Default**: `<project_root>` (wherever CloudinatorFTP is installed)

**Change location**:
```bash
python setup_storage.py  # Interactive configuration
# Or manually edit storage_config.json
```

### Q: Can I delete files permanently?

**A:** Yes, by clicking 🗑️ delete. **Deletion is permanent and cannot be undone** — no recycle bin.

> **Tip**: Backup important files before deleting!

### Q: What is the difference between the web UI and FTP/SFTP/WebDAV/SMB?

**A:** They all access the same files — just through different protocols:

| Method | Best for |
|--------|---------|
| Web UI (port 5000) | Browser-based access, media preview, bulk ZIP download |
| WebDAV (8080/8443) | Native OS drive mapping — drag & drop in File Explorer |
| SFTP (port 2222) | Secure file transfer clients (WinSCP, FileZilla, sshfs) |
| FTP (port 2121) | Legacy FTP clients on trusted local networks only |
| SMB (445/8445) | Native network drive, `\\HOST\SharedFolder` — needs one-time setup (`python smb_setup.py`) |

---

## Monitoring & Debugging

### Health & Status Endpoints

```bash
# Server health
curl http://localhost:5000/api/health_check

# File monitor status
curl http://localhost:5000/api/monitoring_status

# Storage stats
curl http://localhost:5000/api/storage_stats

# Disk usage
curl http://localhost:5000/api/disk_stats_fast

# Upload chunk stats
curl http://localhost:5000/admin/chunk_stats
```

### View Logs

```bash
# Development server
python dev_server.py  # Logs to console

# Production server (save output to file)
python prod_server.py > cloudinator.log 2>&1 &

# Check logs
tail -f cloudinator.log
```

### In-App Help

- **Hover over buttons** (desktop) to see tooltips
- **Tap buttons** (mobile) to see labels
- **Search documentation** (this guide)
- **Check server logs** for detailed error messages

---

## Summary

You now know how to:

✅ Log in and manage sessions  
✅ Navigate the file manager interface  
✅ Upload files (single, multiple, drag-drop)  
✅ Download files individually or as ZIP  
✅ Use advanced search with extension filters  
✅ Share files/folders publicly via a Share Link (passkey, approval, or expiry)  
✅ Preview media and documents  
✅ Perform bulk operations  
✅ Connect via WebDAV as a mapped drive  
✅ Connect via SFTP using WinSCP or FileZilla  
✅ Connect via FTP for legacy clients  
✅ Connect via SMB as a native network drive  
✅ Troubleshoot common issues  
✅ Configure server settings  
✅ Monitor server health  
✅ Manage user accounts  

**Happy file sharing!** 🎉

---

## For More Help

**Developer Documentation**: See `CLAUDE.md` for architecture and advanced configuration

**Deployment Guides**: 
- `docs/WINDOWS_DEPLOYMENT.md` — Windows setup
- `docs/LINUX_DEPLOYMENT.md` — Linux/systemd setup
- `docs/ANDROID_DEPLOYMENT.md` — Android/Termux setup
- `docs/DEPLOY_APACHE.md` — Apache/mod_wsgi production (⚠️ predates the Quart/ASGI migration — mod_wsgi only runs WSGI apps, so this guide needs a review/rewrite before relying on it; use `prod_server.py` directly or a reverse proxy in front of it in the meantime)
- `docs/SETUP_TUNNEL_ADVANCED.md` — Cloudflare Tunnel setup
- `docs/RCLONE_DEPLOYMENT.md` — rclone sync & mount
- `docs/SMB_PROTOCOL_DEPLOYMENT.md` — SMB one-time setup, per platform

**Last Updated**: 2026-08-22