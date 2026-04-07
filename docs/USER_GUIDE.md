# CloudinatorFTP User Guide

**Version**: 1.0 | **Last Updated**: 2026-04-06  
**For**: End users accessing the web file manager

Welcome to **The Cloudinator** — a lightweight, secure file sharing platform that works across Windows, Linux, and Android (Termux).

---

## 📋 Table of Contents

1. [Getting Started](#getting-started)
2. [Login & Authentication](#login--authentication)
3. [File Manager Interface](#file-manager-interface)
4. [Navigation & Browsing](#navigation--browsing)
5. [Uploading Files](#uploading-files)
6. [Downloading Files](#downloading-files)
7. [Advanced Search](#advanced-search)
8. [File Operations](#file-operations)
9. [Bulk Operations](#bulk-operations)
10. [Media Preview](#media-preview)
11. [Tips & Tricks](#tips--tricks)
12. [Troubleshooting](#troubleshooting)

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

2. **Token Revoked**: You ran `python revoke_session.py`
   - Instantly logs out all connected users
   - Useful for security or testing

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
- Increase timeout in Flask config if needed

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

1. **Same Server**: Create additional user accounts
   ```bash
   python create_user.py  # Add new user
   ```
   They can then browse and download shared files.

2. **Different Server**: Create second instance on different port
   ```bash
   # In config.py, change PORT to 5001
   python prod_server.py
   ```

3. **Public URL**: Set up Cloudflare Tunnel (see `docs/SETUP_TUNNEL_ADVANCED.md`)
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
✅ Preview media and documents  
✅ Perform bulk operations  
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
- `docs/DEPLOY_APACHE.md` — Apache/mod_wsgi production
- `docs/SETUP_TUNNEL_ADVANCED.md` — Cloudflare Tunnel setup

**Last Updated**: 2026-04-06
