# CloudinatorFTP — Complete Codebase Reference for AI-Assisted Development

**Version**: 3.2 | **Last Updated**: 2026-06-18  
**For**: AI assistants and developers modifying/extending CloudinatorFTP

---

## 📋 Table of Contents

1. [Quick Reference](#quick-reference)
2. [Project Overview](#project-overview)
3. [Architecture & Module Map](#architecture--module-map)
4. [Core Systems Deep Dive](#core-systems-deep-dive)
5. [Data Structures](#data-structures)
6. [Flask Routes & API](#flask-routes--api)
7. [Database Schema](#database-schema)
8. [Authentication & Sessions](#authentication--sessions)
9. [File Upload System](#file-upload-system)
10. [Real-Time Monitoring](#real-time-monitoring)
11. [Directory Listing & Caching](#directory-listing--caching)
12. [Full-Text Search](#full-text-search)
13. [Media Handling](#media-handling)
14. [Bulk Operations](#bulk-operations)
15. [Configuration & Deployment](#configuration--deployment)
16. [Protocol Servers (WebDAV / SFTP / FTP)](#protocol-servers-webdav--sftp--ftp)
17. [Admin Tools & Utilities](#admin-tools--utilities)
18. [Performance Characteristics](#performance-characteristics)
19. [Troubleshooting & Edge Cases](#troubleshooting--edge-cases)

---

## ⚡ Quick Reference

### Most Important Files

| File | Purpose | Key Responsibilities |
|------|---------|----------------------|
| **app.py** | Flask server & route handlers | HTTP endpoints, session mgmt, response building |
| **storage.py** | File system operations | List dirs, chunks, assembly, cleanup |
| **database.py** | SQLite + encryption | Users, passwords, server tokens, sessions |
| **auth.py** | Authentication helpers | Login/logout, session validation, role checking |
| **config.py** | Settings & feature toggles | Paths, sizes, feature flags |
| **paths.py** | Configurable directory resolver | db_path, cache_path, storage_path resolution |
| **file_monitor.py** | Real-time filesystem tracking | Watchdog integration, counters, reconciliation |
| **file_index.py** | Large-folder caching | Indexed dir listings, instant lookups |
| **search_index.py** | Full-text search engine | FTS5 indexing, query processing |
| **realtime_stats.py** | Server-Sent Events | Live storage stats broadcasting |
| **protocol_manager.py** | Protocol server launcher | Starts/stops WebDAV, SFTP, FTP in background threads |
| **webdav_server.py** | WebDAV server | wsgidav + waitress/cheroot, HTTP+HTTPS, role enforcement |
| **sftp_server.py** | SFTP server | Paramiko SSH/SFTP, RSA host key, chrooted to ROOT_DIR |
| **ftp_server.py** | FTP server | pyftpdlib, custom authorizer, passive ports 60000–60100 |
| **ssl_cert.py** | TLS certificate manager | Self-signed cert generation, SAN detection, db/ storage |

### Startup Order

```
1. ensure_dirs() → creates db/, cache/, hls_cache/, img_cache/
2. database._connect() → SQLite, _bootstrap(), default users
3. file_monitor.init() → full initial walk, build storage_index.json
4. file_index.py → load/update file_index.json cache
5. search_index_manager.start_crawler() → background FTS5 population
6. start_assembly_worker() → chunk assembly background daemon
7. cleanup_scheduler → starts periodic cleanup
8. Flask app ready
9. protocol_manager.start_all() → WebDAV (8080/8443), SFTP (2222), FTP (2121) start in daemon threads
```

---

## 🎯 Project Overview

**CloudinatorFTP** is a sophisticated Flask-based web file server designed for:
- **Multi-platform**: Windows, Linux, macOS, Android (Termux)
- **Scalability**: Handles 100k+ files with instant response times
- **Real-time**: Live filesystem monitoring with SSE updates
- **Rich media**: HLS video streaming, WebP compression, archive preview
- **Security**: Per-user authentication, role-based access, encrypted passwords
- **Uploads**: Chunked resumable uploads, automatic assembly, conflict resolution
- **Protocol Access**: WebDAV (native drive mapping), SFTP (WinSCP/sshfs), FTP (legacy clients)

**Core Design Philosophy**:
- Event-driven watchdog for instant monitoring
- Incremental caching (storage_index.json, file_index.json)
- Lazy initialization (nothing created on import)
- Modular systems (auth, storage, search, media all independent)
- Graceful fallbacks (missing ffmpeg → raw video, no libvips → raw images)
- Protocol servers are optional daemon threads — main Flask server unaffected if any fail

---

## 🏗️ Architecture & Module Map

### Dependency Graph

```
app.py (Flask entry point, routes)
│
├─→ auth.py → database.py (login, sessions)
├─→ config.py → paths.py (settings, directory resolution)
├─→ storage.py (file I/O, uploads, downloads)
│   ├─→ file_index.py (folder caching)
│   ├─→ search_index.py (search queries)
│   └─→ file_monitor.py (size calculations)
│
├─→ file_monitor.py (watchdog, real-time tracking)
│   ├─→ file_index.py (cache invalidation)
│   ├─→ search_index.py (index updates)
│   └─→ realtime_stats.py (SSE broadcasts)
│
├─→ realtime_stats.py (Server-Sent Events)
├─→ database.py (SQLite persistence)
│
├─ Protocol Layer (started from dev_server.py / prod_server.py):
│   └─→ protocol_manager.py
│       ├─→ webdav_server.py → wsgidav, waitress/cheroot, ssl_cert.py
│       ├─→ sftp_server.py  → paramiko
│       └─→ ftp_server.py   → pyftpdlib
│
└─ Supporting CLIs:
   ├─→ create_user.py (user management)
   ├─→ reset_db.py (database reset)
   ├─→ revoke_session.py (token rotation)
   └─→ debug_passwords.py (auth testing)
```

### Key Principles

1. **Lazy Initialization**: Nothing created on module import—only on first use
2. **Single Source of Truth**: paths.py resolves all directory locations
3. **Atomic Operations**: File operations use platform-specific safety (Windows readonly handling)
4. **No Blocking I/O in HTTP**: Chunks processed, assembly backgrounded, cleanup scheduled
5. **Event-Driven Stats**: Watchdog updates counters; reconcile corrects drift
6. **Protocol Servers are Daemon Threads**: They die automatically when the main process exits; failures do not affect the Flask server

---

## 📊 Data Structures

### **Storage Index** (storage_index.json in cache_path)
```json
{
  "file_count": 125000,
  "dir_count": 8500,
  "total_size": 2684354560,
  "last_modified": 1234567890.5,
  "checksum": "abc123def456...",
  "timestamp": 1234567890.5,
  "dir_info": {
    "photos": {"file_count": 500, "dir_count": 3, "total_size": 50000000000},
    "videos/archive": {"file_count": 50, "dir_count": 0, "total_size": 500000000}
  }
}
```
**Purpose**: Instant file/dir count + total size (global and per-folder)  
**Updated By**: watchdog incremental, reconcile full walk  
**Loaded On**: startup (or recalculated if missing)

### **File Index** (file_index.json in cache_path)
```json
{
  "version": 1,
  "threshold": 80,
  "dirs": {
    "videos": {
      "entry_count": 500,
      "indexed_at": 1234567890.5,
      "entries": [
        {"name": "movie1.mkv", "is_dir": false, "size": 4000000000, "modified": 1234567890},
        {"name": "subfolder", "is_dir": true, "size": 0, "modified": 1234567890}
      ]
    }
  }
}
```
**Purpose**: Instant listing for folders >80 entries  
**Updated By**: watchdog (adds/removes entries)  
**Auto-Added**: folders exceeding threshold on first listing

### **SQLite Database** (cloudinator.db in db_path)

**Table: users**
```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  username TEXT UNIQUE NOT NULL COLLATE NOCASE,
  password_hash BLOB NOT NULL,  -- Fernet-encrypted bcrypt hash
  role TEXT DEFAULT 'readonly',  -- 'readwrite' or 'readonly'
  created_at REAL DEFAULT (unixepoch('now')),
  last_login REAL
);
```

**Table: server_token**
```sql
CREATE TABLE server_token (
  id INTEGER PRIMARY KEY CHECK (id=1),
  token TEXT UNIQUE,  -- UUID4, regenerated on logout-all
  updated_at REAL
);
```

**Encryption Layer**: Fernet (AES-128 CBC) with key stored in secret.key

---

## � Flask Routes & API

### Authentication Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/login` | GET | None | Show login form |
| `/login` | POST | None | Process login credentials |
| `/logout` | GET | Required | Clear session + redirect |
| `/check_session` | GET | None | JSON: verify session validity |

**Login POST Response**:
```json
{
  "success": true,
  "username": "admin",
  "role": "readwrite",
  "redirect": "/"
}
```

**Check Session Response**:
```json
{
  "logged_in": true,
  "username": "admin",
  "role": "readwrite",
  "token_valid": true
}
```

---

### File Browsing & Download Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/` | GET | Required | List root directory |
| `/<path:path>` | GET | Required | List or open file/folder |
| `/download/<path:path>` | GET | Required | Download file as attachment |
| `/view/<path:path>` | GET | Required | View file inline (img/pdf/video) |

**Directory Listing Response**:
```json
{
  "path": "photos/2024",
  "is_dir": true,
  "parent_path": "photos",
  "entries": [
    {"name": "vacation.jpg", "is_dir": false, "size": 5000000, "modified": 1693324800},
    {"name": "family", "is_dir": true, "size": 0, "modified": 1693324800}
  ],
  "file_count": 150,
  "dir_count": 8,
  "total_size": 50000000000,
  "from_cache": true
}
```

---

### Media Preview Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/pdfviewer` | GET | Required | PDF viewer UI |
| `/office_preview/<path:path>` | GET | Required | Convert Office docs to HTML/JSON |
| `/archive_preview/<path:path>` | GET | Required | List archive contents (ZIP/RAR/7Z) |

**Office Preview Response**:
```json
{
  "type": "docx",
  "content": "<h1>Document Title</h1><p>Content here...</p>",
  "preview_pages": 5
}
```

**Archive Preview Response**:
```json
{
  "type": "zip",
  "total_entries": 1250,
  "total_size": 5000000000,
  "compressed_size": 2500000000,
  "entries": [
    {"name": "folder/", "is_dir": true, "size": 0, "compressed_size": 0},
    {"name": "file.txt", "is_dir": false, "size": 1000, "compressed_size": 300}
  ]
}
```

---

### File Modification Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/upload` | POST | readwrite | Upload file chunk |
| `/cancel_upload/<file_id>` | POST | readwrite | Cancel chunked upload |
| `/cleanup_chunks` | POST | readwrite | Manual orphan cleanup |
| `/bulk-download` | POST | readwrite | Download multiple files as ZIP |

**Upload Chunk Request**:
```json
{
  "file_id": "uuid-1234",
  "chunk_num": 0,
  "total_chunks": 100,
  "dest_path": "uploads/"
}
```

**Upload Chunk Response**:
```json
{
  "success": true,
  "chunk_num": 0,
  "assembled": false,
  "percentage": 1,
  "file_id": "uuid-1234"
}
```

**Bulk Download Request**:
```json
{
  "paths": ["file1.txt", "folder/file2.pdf"],
  "format": "zip"
}
```

**Bulk Download Response**: Binary ZIP stream (application/zip)

---

### File System Modification Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/api/create_folder` | POST | readwrite | Create new folder |
| `/api/rename` | POST | readwrite | Rename file/folder |
| `/api/move` | POST | readwrite | Move file/folder |
| `/api/copy` | POST | readwrite | Copy file/folder |
| `/api/delete` | POST | readwrite | Delete file/folder |
| `/api/bulk_copy` | POST | readwrite | Copy multiple items |
| `/api/bulk_delete` | POST | readwrite | Delete multiple items |
| `/api/bulk_move` | POST | readwrite | Move multiple items |

**Create Folder Request**:
```json
{
  "path": "photos/",
  "folder_name": "vacation"
}
```

**Rename Request**:
```json
{
  "path": "old_file.txt",
  "new_name": "new_file.txt"
}
```

**Move Request**:
```json
{
  "source": "file.txt",
  "dest": "subfolder/"
}
```

**Delete Request**:
```json
{
  "path": "file_to_delete.txt"
}
```

**Bulk Copy Request**:
```json
{
  "sources": ["file1.txt", "folder1/"],
  "dest": "target_folder/",
  "conflict": "rename"
}
```

**Success Response**:
```json
{
  "success": true,
  "message": "Operation completed",
  "count": 1
}
```

---

### Search Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/api/search` | GET | Required | Full-text search |

**Search Request**:
```
GET /api/search?q=mountain&ext=csv,txt&offset=0&limit=50
```

**Search Response**:
```json
{
  "results": [
    {"rel_path": "data/mountain.csv", "name": "mountain.csv", "is_dir": false},
    {"rel_path": "docs/guide.txt", "name": "guide.txt", "is_dir": false}
  ],
  "total_count": 237,
  "has_more": true,
  "search_time": 0.042,
  "from_index": true
}
```

---

### Real-Time Stats Routes

| Route | Method | Auth | Response |
|-------|--------|------|----------|
| `/api/storage_stats` | GET | Required | SSE stream: real-time stats |
| `/api/dir_info/<path:path>` | GET | Required | Instant dir counters |
| `/api/monitoring_status` | GET | Required | Watchdog + reconcile status |

**SSE Storage Stats Event**:
```json
{
  "event": "storage_stats_update",
  "data": {
    "timestamp": 1693324800.5,
    "file_count": 125000,
    "dir_count": 8500,
    "total_size": 2684354560,
    "reconcile_complete": false,
    "walk_progress": 45
  }
}
```

**Dir Info Response**:
```json
{
  "path": "photos/",
  "file_count": 500,
  "dir_count": 12,
  "total_size": 50000000000,
  "from_cache": true
}
```

---

### Video/Media Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/video/<cacheKey>/<filename>` | GET | Required | HLS master playlist (m3u8) |
| `/segment/<segmentId>` | GET | Required | HLS video segment (.ts) |
| `/image_proxy/<path:path>` | GET | Required | Image with optional WebP conversion |
| `/video_status/<cacheKey>` | GET | Required | Transcode progress JSON |

**HLS Playlist (manifest.m3u8)**:
```m3u8
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:0

#EXT-X-STREAM-INF:BANDWIDTH=300000,RESOLUTION=256x144
/segment/144p_0
#EXT-X-STREAM-INF:BANDWIDTH=7500000,RESOLUTION=1280x720
/segment/720p_0
```

**Video Status Response**:
```json
{
  "status": "transcoding",
  "progress": 45,
  "profiles_done": ["144p", "360p"],
  "profiles_total": 8,
  "eta_seconds": 120,
  "audio_tracks": [
    {"index": 0, "language": "eng", "label": "English"}
  ],
  "subtitle_tracks": [
    {"index": 0, "language": "eng", "label": "English"},
    {"index": 1, "language": "por", "label": "Portuguese"}
  ]
}
```

---

### Admin Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/admin/rebuild_cache` | POST | readwrite | Delete + rebuild file_index.json |
| `/admin/cleanup_chunks` | POST | readwrite | Force orphaned chunk cleanup |
| `/admin/chunk_stats` | GET | readwrite | Active uploads + queue status |
| `/admin/upload_status` | GET | readwrite | Per-session assembly jobs |

**Chunk Stats Response**:
```json
{
  "orphaned_count": 5,
  "orphaned_size": 500000000,
  "active_uploads": 2,
  "queue_length": 3,
  "oldest_orphan_age_hours": 48
}
```

**Upload Status Response**:
```json
{
  "session_id": "abc123",
  "active_jobs": [
    {
      "file_id": "uuid-1234",
      "filename": "large_video.mkv",
      "status": "processing",
      "progress": 75,
      "error": null
    }
  ],
  "total_active": 1
}
```

---

### Health & Diagnostic Routes

| Route | Method | Auth | Response |
|-------|--------|------|----------|
| `/api/health_check` | GET | None | `{status: 'ok'}` |
| `/api/speedtest/ping` | GET | None | `{latency_ms: N}` |
| `/api/speedtest/upload` | POST | None | `{upload_speed_mbps: N}` |
| `/api/speedtest/download` | GET | None | `{download_speed_mbps: N}` |
| `/api/disk_stats_fast` | GET | Required | `{total, used, free}` |

**Health Check Response**:
```json
{
  "status": "ok",
  "version": "3.1",
  "database": "connected",
  "file_monitor": "running",
  "search_index": "ready"
}
```

**Speedtest Upload**:
```json
{
  "upload_speed_mbps": 45.3,
  "latency_ms": 2.1,
  "packet_loss": 0
}
```

---

### Utility Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/cancel_bulk_zip` | POST | Required | Stop bulk ZIP download |
| `/404` | GET | None | Custom 404 page |

---

## �🔐 Authentication & Sessions

### Login Flow

```
1. User submits POST /login {username, password}
   ↓
2. RateLimiter checks IP address
   - MAX_ATTEMPTS=5 failures in 60s → 300s lockout
   - In-memory state (resets on server restart)
   ↓
3. database.check_login(username, password)
   - SQL: SELECT password_hash, role FROM users WHERE username COLLATE NOCASE=?
   - Fernet decrypt password_hash
   - bcrypt.checkpw(password, decrypted_hash)
   ↓
4. If SUCCESS: login_user(username)
   - session.clear()
   - session['username'] = username
   - session['role'] = db.get_role(username)
   - session['logged_in'] = True
   - session['server_token'] = db.get_server_token()
   - session.permanent = True (24 hours PERMANENT_SESSION_LIFETIME)
   - db.update_last_login(username)
   ↓
5. If FAIL: flash error, increment fail count, redirect to /login
```

### Session Validation (Per Request)

```python
@app.before_request
def check_session():
    if request.path.startswith('/api/'):
        # Public endpoints: health_check, speedtest
        if request.path in PUBLIC_ENDPOINTS:
            return None
        # Verify session valid
        if not session.get('logged_in'):
            return redirect('/login')
        # Token rotation check: session['server_token'] must match current DB token
        if session['server_token'] != db.get_server_token():
            session.clear()  # invalidated by logout-all
            return redirect('/login?reason=session_expired')
```

### Default Credentials (on first boot)

| Username | Password | Role | Purpose |
|----------|----------|------|---------|
| admin | admin123 | readwrite | Full access, admin functions |
| guest | guest123 | readonly | View-only, no modifications |

### Role Permissions

| Action | readwrite | readonly |
|--------|-----------|----------|
| View files, download | ✅ | ✅ |
| Upload files | ✅ | ❌ |
| Delete files | ✅ | ❌ |
| Move/copy/rename | ✅ | ❌ |
| Create folders | ✅ | ❌ |
| Access admin | ✅ | ❌ |

### Encryption & Password Storage

**Password Hash Chain:**
```
User password (plaintext) 
  → bcrypt.hashpw(password, salt) → 60-byte hash
  → Fernet.encrypt(hash) → 88-byte ciphertext
  → stored in SQLite as BLOB
```

**On Verification:**
```
User password (plaintext)
  → SQLite retrieve BLOB
  → Fernet.decrypt(blob) → bcrypt hash
  → bcrypt.checkpw(password, hash) → True/False
```

**Key Storage**: secret.key in db_path (256-bit random, base64 encoded)

---

## 📤 File Upload System

### Chunked Upload Architecture

**Client Side**:
```javascript
file.size = 1GB
CHUNK_SIZE = 10MB

for (let i=0; i<100; i++) {
  chunk = file.slice(i*10MB, (i+1)*10MB)
  formData = new FormData()
  formData.append('file', chunk)
  formData.append('file_id', UUID)
  formData.append('chunk_num', i)
  formData.append('total_chunks', 100)
  
  POST /upload formData
  // Stream upload at browser bandwidth
}
```

**Server Side (app.py /upload endpoint)**:

```python
POST /upload
├─ Validate: user role, chunk size, content-length
├─ Extract: file_id, chunk_num, total_chunks, destination path
├─ Check: path within ROOT_DIR, collision rules
├─ storage.save_chunk(file_id, chunk_num, chunk_data)
│  ├─ Create .chunks/{file_id}/ if needed
│  └─ Write chunk_data to .chunks/{file_id}/{chunk_num}
├─ Check: verify_chunks_complete(file_id, total_chunks)
│  ├─ If complete → queue AssemblyJob
│  └─ If incomplete → return {assembled: false, percentage}
└─ Handle disconnects: ClientDisconnected exception
   ├─ Log incomplete file_id
   └─ Background cleanup will orphan after 45min
```

### Assembly Process

**Assembly Queue** (global state in app.py):
```python
class AssemblyJob:
  file_id: str
  filename: str
  dest_path: str
  total_chunks: int
  status: 'pending'|'processing'|'completed'|'error'
  error_msg: str

assembly_queue: Queue[AssemblyJob]  # FIFO
active_jobs: Dict[str, AssemblyJob]  # file_id → job
completed_jobs: Dict[str, AssemblyJob]  # tracking
```

**Assembly Worker** (background thread):
```
while True:
  job = assembly_queue.get()
  active_jobs[job.file_id] = job
  
  try:
    storage.assemble_chunks(
      file_id=job.file_id,
      filename=job.filename,
      dest_path=job.dest_path
    )
    # assembly_worker writes:
    # 1. Verify chunks exist and sizes match
    # 2. Create .assembling marker file (prevents cleanup)
    # 3. Open dest_file for write
    # 4. For each chunk_num 0→total_chunks:
    #    - Open chunk file, read all, write to dest
    #    - Delete chunk file
    # 5. Delete .assembling marker
    # 6. Delete .chunks/{file_id}/ directory
    
    job.status = 'completed'
    completed_jobs[job.file_id] = job
    
  except Exception as e:
    job.status = 'error'
    job.error_msg = str(e)
    # Chunks left in .chunks/ for manual cleanup
```

### Cleanup Strategies

**1. Immediate Cleanup** (after successful assembly):
- Remove .chunks/{file_id}/ directory
- Mark in completed_jobs

**2. Orphaned Chunks** (untracked files >45 min old):
- Runs every 5 minutes
- Finds .chunks/{file_id}/ with no corresponding AssemblyJob
- Deletes entire .chunks/{file_id}/

**3. Interrupted Uploads** (tracked but inactive >30 min):
- For downloads that disconnect mid-stream
- ChunkTracker tracks per-session active uploads
- Grace period prevents deleting tabs in background
- Removed after 30 min of inactivity

**4. Periodic Cleanup**:
- Every 15 min: remove orphans >1 hour old
- Every 1 hour: remove orphans >24 hours old

**5. Admin Manual Cleanup**:
- POST /admin/cleanup_chunks
- Force scan + cleanup all orphaned chunks immediately

### Conflict Resolution

```python
dest_path = "photos/vacation.jpg"

if os.path.exists(dest_path):
  # User chose: 'skip' | 'overwrite' | 'rename'
  if conflict_resolution == 'skip':
    skip_file()
  elif conflict_resolution == 'overwrite':
    os.remove(dest_path)
    write_file()
  elif conflict_resolution == 'rename':
    name, ext = os.path.splitext(dest_path)
    new_path = f"{name}_1{ext}"  # or _2, _3 if _1 exists
    write_file(new_path)
```

---

## 👁️ Real-Time Monitoring

### Watchdog Integration (file_monitor.py)

**InstantFileEventHandler** (listens for filesystem events):

```python
class InstantFileEventHandler(FileSystemEventHandler):
  def on_created(self, event):
    rel_path = make_relative(event.src_path)
    size = get_size(event.src_path)
    _increment_counters(size, is_dir=event.is_directory)
    _update_dir_info_tree(rel_path)
    _debounce_timer.schedule_reconcile(force_at=5)  # settle if >200 events
    search_index.add_file(rel_path)
  
  def on_deleted(self, event):
    rel_path = make_relative(event.src_path)
    size = get_size(event.src_path)  # may fail if already deleted
    _decrement_counters(size, is_dir=event.is_directory)
    _update_dir_info_tree(rel_path)
    search_index.remove_file(rel_path)
  
  def on_moved(self, event):
    old_rel = make_relative(event.src_path)
    new_rel = make_relative(event.dest_path)
    _atomic_move_dir_info(old_rel, new_rel)
    search_index.rename_file(old_rel, new_rel)
```

**Counter Architecture**:

```python
_file_count = 0       # global, atomic
_dir_count = 0        # global, atomic
_total_size = 0       # global, atomic
_total_size_lock = Lock()

_dir_info = {         # per-folder info, thread-safe dict
  "rel/path": {
    "file_count": 42,
    "dir_count": 3,
    "total_size": 123456789
  }
}
_dir_info_lock = Lock()
```

**Reconciliation Process** (runs every 15 min or on demand):

```
_reconcile() loop:
├─ Every 15 min: trigger full walk
├─ During walk:
│  ├─ os.walk(ROOT_DIR)
│  ├─ Rebuild counters from scratch
│  ├─ Rebuild dir_info for all folders
│  ├─ Emit SSE walk_progress every ~1s
│  ├─ Calculate checksum of final state
│  └─ Compare with previous snapshot
├─ On mismatch: emit SSE reconcile_complete
│  ├─ Include drift info (what changed)
│  └─ Signal UI to refresh table
└─ Update last_snapshot
```

### Server-Sent Events (realtime_stats.py)

**Event Manager**:
```python
class StorageStatsEventManager:
  clients: Set[Queue] = set()
  
  def broadcast_update(self, old_snapshot, new_snapshot, reconcile_complete=False):
    # Build event JSON
    event = {
      "timestamp": time.time(),
      "reconcile_complete": reconcile_complete,
      "stats": new_snapshot,
      "changes": calculate_delta(old_snapshot, new_snapshot)
    }
    # Send to all connected clients (non-blocking)
    for queue in self.clients:
      try:
        queue.put_nowait(event)
      except queue.Full:
        pass  # client disconnected
```

**Client-Side SSE Connection** (index.js):
```javascript
const sse = new EventSource('/api/storage_stats_sse')

sse.addEventListener('message', (e) => {
  const data = JSON.parse(e.data)
  updateStorageDisplay(data.stats)
  
  if (data.reconcile_complete) {
    // Full table refresh (sizes now accurate)
    reloadFileTable()
  } else if (data.changes) {
    // Incremental update (just stats)
    updateTableFooter(data.stats)
  }
})

sse.addEventListener('error', () => {
  // Reconnect with exponential backoff
})
```

**Event Types**:
1. **walk_progress**: during reconcile (stats only, no table refresh)
2. **normal**: after watchdog event (stats + optional table refresh)
3. **reconcile_complete**: walk finished (full UI refresh)

---

## 🗂️ Directory Listing & Caching

### Two-Tier Listing Strategy

**Tier 1: Cached Folders (>80 entries)**

```python
def storage.list_dir(path):
  file_index_manager = _get_file_index_manager()
  
  if file_index_manager.is_cached(path):
    # O(1) instant return
    return file_index_manager.get_entries(path)
  
  # First time: scan + cache if exceeds threshold
  entries = os.scandir(path)  # live filesystem
  
  if len(entries) > 80:
    file_index_manager.cache_folder(path, entries)
    file_index.json updated on disk
  
  return sort_entries(entries)
```

**Tier 2: Live Folders (≤80 entries)**

```python
# Direct os.scandir, no cache overhead
entries = list(os.scandir(path))
for entry in entries:
  stat = entry.stat(follow_symlinks=False)
  yield {
    'name': entry.name,
    'is_dir': entry.is_dir(),
    'size': stat.st_size,
    'modified': stat.st_mtime_ns / 1e9
  }
```

### Watchdog Integration

**File Created in Cached Folder**:
```
watchdog.on_created("photos/vacation.jpg")
  ↓
_update_dir_info_tree("photos/vacation.jpg")
  ├─ if file_index.is_cached("photos"):
  │  └─ file_index.add_entry("photos", "vacation.jpg", size, mtime)
  ├─ Update parent dir_info counters
  └─ Update grandparent dir_info counters (recursive)
```

**Folder Crosses Threshold**:
```
"large_folder" now has 81 entries
  ↓
on_created("large_folder/newfile.txt")
  └─ if not is_cached("large_folder") AND count>80:
     └─ file_index.cache_folder("large_folder")
        └─ scan all 81 entries, save to file_index.json
```

**Performance Result**:
- 1000-file folder: <1ms response (cached)
- 100-file folder: <50ms response (live scan)
- Move between folders: incremental index update

---

## 🔍 Full-Text Search

### Dual-Engine Architecture

**FTS5 Mode** (SQLite ≥3.34):
```sql
CREATE VIRTUAL TABLE files_meta USING fts5(
  rel_path UNINDEXED,
  name_lower,
  ext_lower,
  is_dir,
  content=files_data,
  content_rowid=id
);

-- Trigram tokenizer for substring matching
PRAGMA table_info(files_meta)
-- Enables: "mountain" matches "mount", "mountain", "fountain"
```

**LIKE Fallback** (older SQLite/Termux):
```sql
CREATE TABLE files_meta (
  id INTEGER PRIMARY KEY,
  rel_path TEXT NOT NULL,
  name_lower TEXT,
  ext_lower TEXT,
  is_dir INTEGER
);
CREATE INDEX idx_name_lower ON files_meta(name_lower);

-- Query: LIKE '%mountain%' (slower but universal)
```

**Crawler Process**:
```
search_index_manager.start_crawler():
├─ If search_index.db exists: skip (instant startup)
├─ If not: background walk of ROOT_DIR
│  ├─ os.walk(ROOT_DIR)
│  ├─ For each file: insert into FTS5 table
│  ├─ 10ms sleep between dirs (avoids saturation)
│  ├─ Sets _ready=True when complete
│  └─ Logs "Search index ready in 2.3s"
└─ During crawl: queries use fallback os.walk()
```

**Live Sync**:
```
watchdog.on_created("new_file.csv"):
  ├─ search_index.add_file("new_file.csv")
  │  └─ INSERT INTO files_meta VALUES (...)
  └─ Instant search inclusion

watchdog.on_deleted("old_file.csv"):
  ├─ search_index.remove_file("old_file.csv")
  │  └─ DELETE FROM files_meta WHERE rel_path=?
  └─ Instant removal from search

watchdog.on_moved("old.txt", "new.txt"):
  ├─ search_index.rename_file("old.txt", "new.txt")
  │  └─ UPDATE files_meta SET rel_path='new.txt' WHERE...
  └─ Instant index update
```

**Query Endpoint**:
```
GET /api/search?q=mountain&ext=csv,txt&offset=0&limit=50

Response:
{
  "results": [
    {"rel_path": "data/mountain_data.csv", "name": "mountain_data.csv", "is_dir": false},
    {"rel_path": "docs/mountain_guide.txt", "name": "mountain_guide.txt", "is_dir": false}
  ],
  "total_count": 237,
  "has_more": true,
  "search_time": 0.042,
  "from_index": true
}
```

---

## 🎬 Media Handling

### Video Player Subtitle/Caption System (index.js)

**Core Features**:
- **Synchronous CC Button + Dropdown**: CC button and subtitle dropdown stay synchronized
- **Auto-Enable on Select**: Selecting any subtitle automatically enables captions
- **Persistent Selection**: Toggling CC button on/off remembers the selected subtitle language
- **Track Continuity**: Old track stays visible during new track load to prevent flashing

**Architecture** (_buildTrackSelectors function, line 10998):

```javascript
_buildTrackSelectors(playerEl, audioMeta, subMeta, cacheKey)
  ├─ Create audio track selector (if multiple audio tracks)
  ├─ Create subtitle selector dropdown
  │   └─ Options: Off, English, Portuguese, French, etc.
  └─ Manage single managed <track> element synchronized with:
      ├─ Dropdown selection (user chooses language)
      └─ CC button (native video player control)
```

**State Variables** (lines 11125-11127):

```javascript
let _activeIdx = -1;           // Currently selected subtitle index (-1 = Off)
let _captionsEnabled = false;  // Whether captions display is ON (persistent state)
let _subChanging = false;      // Locking flag to prevent race conditions
let _loadGen = 0;              // Generation counter for load cancellation
```

**Key Functions**:

```javascript
_setSubIdx(idx)
  // User selected a subtitle from dropdown
  ├─ Keep old track at 'showing' mode (no gap in playback)
  ├─ Mount new track element with _mountTrack()
  ├─ Set _captionsEnabled = true (auto-enable captions)
  └─ Immediately enable CC button state:
     ├─ _subChanging = true (lock out CC button listener)
     ├─ Set track mode = 'showing'
     ├─ Disable foreign tracks
     ├─ _subChanging = false (unlock)
     └─ Dispatch 'change' event to update CC button UI

_mountTrack(meta, url, onReady)
  // Mount new subtitle track without removing old one
  ├─ Keep reference to old track: const oldTrackEl = trackEl
  ├─ Create new <track> element, append to video
  ├─ Set trackEl = el (immediately point to new)
  ├─ On load complete (callback):
  │   ├─ Remove old track from DOM
  │   └─ Call onReady()
  └─ Effect: Both tracks exist briefly, prevents flashing

_setOff()
  // User selected "Off" from dropdown
  ├─ _captionsEnabled = false
  ├─ Set track mode = 'hidden' (NOT 'disabled'!)
  │   └─ 'hidden': CC button CAN toggle it back on
  │   └─ 'disabled': CC button CANNOT toggle it
  └─ Update UI immediately

video.textTracks.addEventListener('change', ...)
  // CC button was toggled by user
  ├─ If _activeIdx >= 0 (subtitle selected):
  │   ├─ Track -> 'showing': sync to selected subtitle
  │   └─ _captionsEnabled = true
  ├─ If no tracks showing:
  │   └─ _captionsEnabled = false
  └─ Result: CC button always reflects current subtitle state
```

**Track Mode Constants** (HTML5 spec):
- `'disabled'`: Track exists but won't load; CC button can't toggle it
- `'hidden'`: Track loads silently; CC button can toggle it; cues won't display
- `'showing'`: Track active and displaying cues; CC button shows "on"

**Why This Works**:
1. **Track continuity**: Old track stays visible until new one loads → no momentary disabled state
2. **Immediate CC state**: After selection, track set to 'showing' before onLoad → CC button appears enabled instantly
3. **State separation**: `_captionsEnabled` independent of track modes → can toggle CC on/off while remembering subtitle
4. **Mode isolation**: Use 'hidden' not 'disabled' → CC button always has power to toggle

---

### HLS Video Streaming Pipeline

**Conditions for HLS**:
```python
def should_use_hls(file_path):
  file_size = os.path.getsize(file_path)
  file_ext = os.path.splitext(file_path)[1].lower()[1:]
  
  return (
    (file_size >= HLS_MIN_SIZE)  # Default 50MB
    or (file_ext in HLS_FORCE_FORMATS)  # mkv, avi, wmv, etc.
  )
```

**Transcoding Process**:
```
GET /video/movies/film.mkv
  ├─ Check cache: md5(size:mtime) → existing profile dir?
  │  └─ Yes: skip transcode, serve existing manifest
  ├─ ffprobe(film.mkv)
  │  └─ Get: resolution, fps, duration, audio tracks, subtitle tracks
  ├─ Extract subtitle metadata
  │  ├─ Parse video streams for subtitle tracks
  │  ├─ Convert to VTT format if needed
  │  └─ Store in manifest metadata
  ├─ Determine profiles needed
  │  ├─ Standard: 144p–4K (all capped 30fps)
  │  └─ HFR: 720p60–4K60 (if source ≥48fps)
  ├─ Start background _run_hls_transcode() thread
  │  ├─ For each profile: ffmpeg multi-pass encode
  │  ├─ Output: manifest.m3u8 + .ts segments (6s each)
  │  ├─ Write .status.json with live % complete
  │  └─ Multi-audio support: -map 0:a:0 -map 0:a:1 etc.
  ├─ Render subtitle dropdown with available languages
  └─ Return: {status: 'transcoding', progress: 0%}
     → client polls /video_status/{cache_key}
     → when 100%, serve manifest.m3u8 + subtitle selectors
```

**Profile Ladder (Adaptive Bitrate)**:

| Resolution | Standard (30fps) | HFR (60fps) | Use Case |
|------------|------------------|------------|----------|
| 144p | 300 kbps | — | Mobile, very slow |
| 240p | 800 kbps | — | Mobile |
| 360p | 1500 kbps | — | Tablet, mobile |
| 480p | 4 Mbps | — | Tablet |
| 720p | 7.5 Mbps | 12 Mbps | Desktop, HD |
| 1080p | 12 Mbps | 20 Mbps | Full HD |
| 1440p | 24 Mbps | 36 Mbps | 2K, smooth |
| 4K | 40 Mbps | 60 Mbps | Ultra HD |

**Manifest (manifest.m3u8)**:
```m3u8
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:EVENT

#EXT-X-STREAM-INF:BANDWIDTH=300000,RESOLUTION=256x144
360p/manifest.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=7500000,RESOLUTION=1280x720
720p/manifest.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=40000000,RESOLUTION=3840x2160
4k/manifest.m3u8
```

**Client-Side (Video.js Player)**:
```javascript
<video-js 
  src="manifest.m3u8"
  controls 
  preload="auto">
</video-js>
// Video.js automatically adapts bitrate to connection speed
```

### Image Compression (WebP)

**Compression Pipeline**:
```python
def handle_image(file_path, ext):
  file_size = os.path.getsize(file_path)
  
  if file_size < IMG_COMPRESS_MIN_SIZE:  # 1MB
    return send_raw(file_path)  # Too small to compress
  
  if not ENABLE_LIBVIPS or not pyvips_available:
    return send_raw(file_path)  # Feature disabled
  
  cache_key = md5(f"{file_size}:{mtime}:{ext}")
  cache_path = os.path.join(IMG_CACHE_DIR, f"{cache_key}.webp")
  
  if os.path.exists(cache_path):
    return send_file(cache_path, mimetype='image/webp')
  
  # Compress using pyvips
  img = pyvips.Image.new_from_file(file_path)
  img_thumb = img.thumbnail(img.width, height=img.height)
  img_thumb.write_to_file(cache_path, Q=IMG_WEBP_QUALITY)  # Q=50
  
  return send_file(cache_path, mimetype='image/webp')
```

**Fallback Behavior**:
- libvips installed + ENABLE_LIBVIPS=True → compression
- libvips installed + ENABLE_LIBVIPS=False → raw image (intentional)
- libvips not installed + ENABLE_LIBVIPS=True → raw image (graceful)
- Image <1MB → raw image (too small to benefit)

### Archive Preview (ZIP, 7Z, RAR, TAR)

**endpoint**: GET /archive_preview/{path}

**Response**:
```json
{
  "type": "zip",
  "total_entries": 1250,
  "total_size": 5000000000,
  "encrypted": false,
  "entries": [
    {"name": "folder/", "is_dir": true, "size": 0, "compressed_size": 0, "modified": 1234567890},
    {"name": "file.txt", "is_dir": false, "size": 10000, "compressed_size": 3000, "modified": 1234567890}
  ]
}
```

**Supported Formats**:
- `.zip` (pyzipper with password support)
- `.7z` (py7zr)
- `.rar` (rarfile)
- `.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz` (tarfile)

**Password Support**:
```python
if user_provided_password:
  try:
    if file.endswith('.zip'):
      archive = zipfile.ZipFile(path)
      # Try to open with password
      archive.testzip(pwd=password.encode())
    elif file.endswith('.7z'):
      archive = py7zr.SevenZipFile(path, password=password)
      archive.list()
  except Exception:
    return {"error": "Incorrect password or encrypted content"}
```

### Document Preview (DOCX, XLSX, PPTX, CSV)

| Format | Library | Output |
|--------|---------|--------|
| .docx | mammoth | HTML (preserves formatting) |
| .xlsx | openpyxl | JSON grid (max 500 rows × 50 cols) |
| .pptx | python-pptx | JSON slide structure |
| .csv | csv module | HTML table |

---

## 🔄 Bulk Operations

### Bulk Download (Streaming ZIP)

```python
POST /bulk-download
├─ Body: {paths: ["file1.txt", "folder/"], format: 'zip'}
├─ Check: all paths in ROOT_DIR
├─ No temp files: use zipstream-new for streaming
├─ Response headers:
│  ├─ Content-Type: application/zip
│  ├─ Content-Disposition: attachment; filename="export.zip"
│  └─ Transfer-Encoding: chunked
└─ Stream: generator yields zip chunks as written
```

**Why No Temp Files**:
- Memory-efficient: chunks streamed directly to client
- No disk I/O: faster for large archives
- Instant: can't run out of disk space for temp

### Bulk Copy

```python
POST /bulk_copy
├─ Body: {sources: [...], dest: "target_folder", conflict: "rename"}
├─ For each source:
│  └─ shutil.copytree(src, dest) or shutil.copy2(src, dest)
├─ _trigger_reconcile()  # Large copies detected
│  └─ force=True → immediate full walk (not 15-min defer)
└─ Return: {success: N, skipped: M, errors: [...]}
```

**Reconciliation Trigger**:
- Copies >100MB or >10 items → immediately reconcile
- Prevents stale counters during large operations

### Bulk Delete

```python
POST /bulk_delete
├─ Body: {paths: [...]}
├─ For each path:
│  ├─ os.remove(path) for files
│  └─ shutil.rmtree(path) for directories
├─ windows_remove_readonly() wrapper (Windows safety)
├─ _trigger_reconcile()  # Large deletes immediate
└─ Return: {deleted: N, errors: [...]}
```

**Windows Readonly Handling**:
```python
def windows_remove_readonly(func, path, exc):
  if exc[0] == PermissionError:
    os.chmod(path, stat.S_IWRITE)
    func(path)
```

### Bulk Move/Rename

```python
POST /bulk_move
├─ Body: {sources: [...], dest_folder: "new_location"}
├─ For each source:
│  └─ shutil.move(src, dest)  # atomic on same filesystem
├─ Watchdog handles incremental updates
└─ Return: {moved: N, errors: [...]}
```

---

## ⚙️ Configuration & Deployment

### storage_config.json (User Configurable)

```json
{
  "storage_path": "C:\\Users\\kyle\\Downloads",
  "db_path": "C:\\Server\\secure\\db",
  "cache_path": "C:\\Server\\secure\\cache",
  "hls_cache_path": "C:\\Server\\secure\\cache\\hls",
  "img_cache_path": "C:\\Server\\secure\\cache\\img",
  "platform": "windows",
  "set_at": 1695475200.5
}
```

**Recommended Production Setup**:
```
storage_path:   /mnt/shared/files        (user-facing files)
db_path:        /secure/cloudinator/db   (outside web root!)
cache_path:     /tmp/cloudinator_cache   (ephemeral)
hls_cache_path: /tmp/cloudinator_hls     (can recreate)
img_cache_path: /tmp/cloudinator_img     (can recreate)
```

### server_config.json (Feature Toggles)

```json
{
  "PORT": 5000,
  "CHUNK_SIZE": 10485760,
  "ENABLE_CHUNKED_UPLOADS": true,
  "HOST": "0.0.0.0",
  "MAX_CONTENT_LENGTH": 17179869184,
  "PERMANENT_SESSION_LIFETIME": 3600,
  "HLS_MIN_SIZE": 26214400,
  "HLS_FORCE_FORMATS": ["mkv", "avi", "wmv", ...],
  "IMG_COMPRESS_MIN_SIZE": 3145728,
  "IMG_WEBP_QUALITY": 50,
  "ENABLE_FFMPEG": true,
  "ENABLE_LIBVIPS": true
}
```

**Feature Toggles Explained**:
- `ENABLE_FFMPEG=True`: HLS transcoding enabled; if ffmpeg missing → graceful fallback (raw video)
- `ENABLE_LIBVIPS=True`: WebP compression enabled; if libvips missing → graceful fallback (raw image)
- `ENABLE_SEARCH_INDEX=True`: FTS5 search; if disabled → full folder scans (slower)

---

## 🔐 Protocol Servers (WebDAV / SFTP / FTP)

### Overview

Three additional servers start automatically alongside the Flask app. They are launched by `protocol_manager.start_all()` which is called from both `dev_server.py` and `prod_server.py` immediately after `from app import app`.

All three share the same authentication database (`database.db`) and respect the same role system (`readwrite` / `readonly`).

### New Files

| File | Purpose |
|------|---------|
| `protocol_manager.py` | Imports and starts all three protocol servers; prints startup summary |
| `webdav_server.py` | wsgidav WSGI app with auth cache, role middleware, HTTP+HTTPS, cert serving |
| `sftp_server.py` | Paramiko SSH accept loop, chrooted SFTPServerInterface |
| `ftp_server.py` | pyftpdlib with standalone CloudinatorAuthorizer (no Windows LogonUser) |
| `ssl_cert.py` | Self-signed RSA cert generator; embeds all local IPs as SANs |

### Port Assignments

| Protocol | Port | Notes |
|----------|------|-------|
| Flask web UI | 5000 | Existing, unchanged |
| WebDAV HTTP | 8080 | Native drive mapping; requires `BasicAuthLevel=2` registry on Windows |
| WebDAV HTTPS | 8443 | Preferred; no registry edit; requires importing `db/webdav.crt` once |
| SFTP | 2222 | WinSCP / FileZilla / sshfs |
| FTP | 2121 | Legacy clients; plaintext; LAN only |
| FTP passive data | 60000–60100 | Must be open in firewall for FTP transfers |

### WebDAV Authentication Flow

```
Request → _CertMiddleware (serves /webdav.crt unauthenticated)
        → _RoleEnforcerMiddleware (blocks write methods for readonly users)
        → WsgiDAVApp (handles auth via _CloudinatorDC domain controller)
```

**Auth cache** (`_AuthCache`): bcrypt runs at most once per 30 seconds per user. Subsequent requests within the TTL are verified against `sha256(password)` without hitting bcrypt. This is critical because WebDAV clients re-authenticate on every request.

**`basic_auth_user` wsgidav 4.x**: Must return the **username string** on success (not `True`). Returning `True` causes wsgidav 4.x to reject the auth silently.

**`is_share_anonymous`**: Takes `(share, environ=None)` — `environ` is optional because wsgidav 4.3.x dropped it from the call site.

**Domain controller**: Must be passed as a **class** to `WsgiDAVApp`, not an instance. wsgidav 4.3.x checks `isinstance(dc, type)` and raises if given an instance.

### SFTP Implementation Notes

- **Host key**: RSA-2048, generated once and stored at `db/sftp_host.rsa`. Back this up — regeneration breaks existing WinSCP known-hosts entries.
- **Chroot**: All SFTP paths are mapped to `ROOT_DIR`. Path traversal is prevented via `os.path.realpath()` comparison.
- **SFTPHandle**: Uses `paramiko.SFTPHandle` with `readfile`/`writefile` attributes — paramiko's default `read()`/`write()` methods use these. Do NOT monkeypatch instance attributes onto `SFTPHandle`; paramiko does not guarantee instance-attribute method dispatch.
- **`transport.accept(30)`**: Required after `start_server()` to acknowledge the client's session channel. Without it, SFTP subsystem activation stalls.

### FTP Implementation Notes

- **`CloudinatorAuthorizer`**: Does NOT inherit from `DummyAuthorizer`. On Windows, `DummyAuthorizer.impersonate_user()` calls `win32security.LogonUser()`, which fails for DB-only users and blocks all file operations post-login. The standalone class has explicit no-op `impersonate_user()` and `terminate_impersonation()` methods.
- **Passive ports**: `60000–60100`. These must be open in the Windows Firewall for file transfers to work.
- **Credentials**: Same as web UI. `has_user()` queries `db.user_exists()`, `validate_authentication()` calls `db.check_login()`.

### SSL Certificate (ssl_cert.py)

- Generated at `db/webdav.crt` + `db/webdav.key` on first HTTPS server start.
- Self-signed, 10-year validity, RSA-2048, SHA-256.
- SANs include `localhost` and all detected local IPv4 addresses (ensures cert matches whatever IP the client uses).
- `CA:TRUE` in BasicConstraints so it can be imported as a Trusted Root CA.
- Served unauthenticated at `http://HOST:8080/webdav.crt` via `_CertMiddleware`.
- **Regenerate** after IP change: `python ssl_cert.py --regenerate`.

### config.py Protocol Variables

```python
WEBDAV_ENABLED       = True   # WebDAV HTTP server
WEBDAV_PORT          = 8080
WEBDAV_HTTPS_ENABLED = True   # WebDAV HTTPS server (requires cheroot)
WEBDAV_HTTPS_PORT    = 8443
SFTP_ENABLED         = True
SFTP_PORT            = 2222
FTP_ENABLED          = True
FTP_PORT             = 2121
```

All six keys are saved/loaded by `save_server_config()` / `load_server_config()` in `server_config.json`. They can also be configured interactively via `python config.py` → option 13 (Protocol Servers).

### Required Dependencies (new)

```
wsgidav    — WebDAV WSGI server
cheroot    — WSGI server with SSL support (for HTTPS WebDAV)
paramiko   — SSH/SFTP implementation
pyftpdlib  — FTP server
```

Install: `pip install wsgidav cheroot paramiko pyftpdlib`

Each is imported lazily inside `start()`. If a library is missing, that protocol server prints a warning and skips — the main Flask server is unaffected.

---

## 🛠️ Admin Tools & Utilities

### User Management (create_user.py)

```bash
python create_user.py
# Menu:
# 1. List users
# 2. Add user
# 3. Change password
# 4. Delete user
# 5. Set role (readwrite/readonly)
# 6. Reset to defaults (admin/admin123, guest/guest123)
```

### Database Tools

**reset_db.py** - Wipe and recreate database:
```bash
python reset_db.py
# Deletes db/ folder entirely
# Recreates with default credentials
# Use: database corrupted, security breach, clean slate
```

**revoke_session.py** - Logout all users:
```bash
python revoke_session.py
# Rotates server_token in database
# All sessions invalidated within 5 seconds
# Use: security incident, force re-login
```

**debug_passwords.py** - Test login credentials:
```bash
python debug_passwords.py
# Menu:
# 1. Test common passwords for all users
# 2. Test custom username/password
# 3. Show user list
# 4. Reset to defaults
```

**ssl_cert.py** - Certificate management:
```bash
python ssl_cert.py               # Show cert paths and import command
python ssl_cert.py --regenerate  # Force regenerate (use after IP change)
```

### Admin Endpoints

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/admin/rebuild_cache` | POST | Delete + rebuild file_index.json | readwrite |
| `/admin/cleanup_chunks` | POST | Force orphaned chunk cleanup | readwrite |
| `/admin/chunk_stats` | GET | Active uploads, queue status | readwrite |
| `/admin/upload_status` | GET | Per-session assembly status | readwrite |

### Health & Diagnostic Endpoints

| Endpoint | Method | Auth | Response |
|----------|--------|------|----------|
| `/api/health_check` | GET | None | `{status: 'ok'}` |
| `/api/storage_stats` | GET | Required | `{file_count, dir_count, total_size, ...}` |
| `/api/speedtest/ping` | GET | None | `{latency_ms: N}` |
| `/api/speedtest/upload` | POST | None | `{upload_speed_mbps: N}` |
| `/api/speedtest/download` | GET | None | `{download_speed_mbps: N}` |

---

## 📊 Performance Characteristics

| Operation | Complexity | Notes | Optimization |
|-----------|-----------|-------|--------------|
| List folder (1000 files) | O(1) if cached, O(n) if live | Cached if >80 entries | File index caching |
| Search 100k files | O(1) FTS5, O(n) LIKE | FTS5 if SQLite 3.34+ | Trigram tokenizer |
| Upload 1GB file (chunked) | O(n/chunk_size) | 100 chunks @ 10MB each | Streaming, bg assembly |
| Assembly (combine chunks) | O(n) | Linear copy | Sequential, single thread |
| Bulk copy 1GB | O(n) + full walk | Reconcile triggered | Immediate reconcile |
| Watchdog event | O(1) counters | 500 µs typical | Atomic operations |
| Reconcile walk (100k files) | O(n) | Periodic 15 min | Drift detection |
| HLS transcode 1GB video | ~30% realtime | 1 pass @ CRF18 | ffmpeg optimized |
| Image compress (5MB) | ~100ms | pyvips parallel | libvips speedups |
| WebDAV auth (cache hit) | O(1) | sha256 compare | _AuthCache 30s TTL |
| WebDAV auth (cache miss) | O(bcrypt) | ~100ms | bcrypt cost factor |
| SFTP file transfer | O(n) | Sequential reads | paramiko transport |

---

## 🐛 Troubleshooting & Edge Cases

### Common Issues

**Problem**: "404 file not found" after upload  
**Cause**: Assembly worker still processing or chunk cleanup too aggressive  
**Fix**: Check `/admin/chunk_stats`, wait 5-10 seconds, refresh

**Problem**: Directory size inconsistent  
**Cause**: Watchdog missed event (external tool, symlinks)  
**Fix**: POST `/admin/rebuild_cache` triggers immediate reconcile

**Problem**: Search returns no results  
**Cause**: Crawler still running (set _ready=False)  
**Fix**: Wait for crawler to finish or disable search (queries fallback to os.walk)

**Problem**: HLS video won't play  
**Cause**: Transcode incomplete, ffmpeg missing, or browser cache  
**Fix**: Check .status.json, verify ffmpeg installed, clear cache

**Problem**: Uploads fail with "ClientDisconnected"  
**Cause**: Browser closed tab, network dropped, or chunk assembly failed  
**Fix**: Chunks cleanup automatically after 45 min; manual cleanup via `/admin`

**Problem**: WebDAV app build failed: `Could not resolve domain controller class`  
**Cause**: Passing a DC instance instead of the class to wsgidav  
**Fix**: `_make_domain_controller_class()` must return the class, not `CloudinatorDC()`

**Problem**: WebDAV `basic_auth_user` returns success but authentication fails  
**Cause**: Returning `True` instead of `user_name` string (wsgidav 4.x API change)  
**Fix**: `return user_name if role is not None else False`

**Problem**: WebDAV map network drive says "inaccessible" on Windows  
**Cause 1**: WebClient service not running → `Start-Service WebClient`  
**Cause 2**: BasicAuthLevel not set (HTTP only) → `reg add ... BasicAuthLevel /d 2`  
**Cause 3**: Wrong IP address in `net use` command  
**Fix HTTPS**: Import `db/webdav.crt` as Trusted Root CA; no registry edit needed

**Problem**: FTP login succeeds but file operations fail on Windows  
**Cause**: `DummyAuthorizer.impersonate_user()` calls `win32security.LogonUser()` for non-OS users  
**Fix**: Use `CloudinatorAuthorizer` (standalone class, not DummyAuthorizer subclass)

**Problem**: SFTP "Authentication failed" in WinSCP on first connect  
**Cause**: WinSCP host key warning dialog was dismissed instead of accepted  
**Fix**: On first connect, click Accept/Yes to cache the host key `db/sftp_host.rsa`

**Problem**: SFTP/FTP "searching for host then error"  
**Cause**: Windows Firewall blocking ports 2222, 2121, 60000-60100  
**Fix**: Add inbound firewall rules; verify with `Test-NetConnection -Port 2222`

**Problem**: FTP file transfer starts but stalls/fails  
**Cause**: Passive data ports (60000-60100) blocked by firewall  
**Fix**: Add firewall rule for ports 60000-60100 TCP inbound

### Edge Cases Handled

1. **Symlinks**: Followed by default (can disable with follow_symlinks=False)
2. **Large files**: Chunked upload, never loaded into memory entirely
3. **Deep nesting**: os.walk handles arbitrary depth
4. **Unicode filenames**: UTF-8 throughout, COLLATE NOCASE for SQL
5. **Concurrent uploads**: Per-session chunk tracking prevents conflicts
6. **Windows readonly files**: Special handler removes readonly bit before delete
7. **Rapid changes**: Watchdog debounce, reconcile periodic correction
8. **Database corruption**: reset_db.py for clean slate
9. **Power loss during assembly**: Marker files (.assembling) protect against partial writes
10. **Deleted user mid-request**: Session invalidated, redirect to /login
11. **Protocol server dependency missing**: Graceful skip with install hint; Flask unaffected
12. **WebDAV client re-auth on every request**: _AuthCache prevents repeated bcrypt calls
13. **SFTP host key regenerated**: All clients see host-key-changed warning (expected)
14. **FTP passive port range**: Must match firewall rules; default 60000-60100

---

## 🔗 Key Decision Points for Modifications

**When Adding Features**:
1. Import paths.py first for directory resolution
2. Use ensure_dirs() before creating files
3. Add watchdog hooks if monitoring needed
4. Update search_index if new indexable content
5. Add SSE event if real-time display needed
6. Test with both ENABLE_* flags True and False

**When Modifying Protocol Servers**:
1. wsgidav domain controller must be a **class** (not instance)
2. `basic_auth_user` must return **username string** on success in wsgidav 4.x
3. `is_share_anonymous(self, share, environ=None)` — `environ` optional (dropped in 4.3.x)
4. SFTP handles must use `paramiko.SFTPHandle` with `.readfile`/`.writefile` attributes
5. FTP authorizer must NOT inherit from `DummyAuthorizer` on Windows

**When Optimizing**:
1. Profile with Python cProfile first
2. Check if Tier 1 caching can help (>80 entries)
3. Consider async for I/O-heavy operations
4. Batch database operations in transactions
5. Use watchdog incremental over full walks

**When Debugging**:
1. Enable FLASK_DEBUG=1
2. Check app.py DEBUG_ROUTES (if defined)
3. Use debug_passwords.py for auth issues
4. Monitor /api/health_check endpoint
5. Review .status.json files for transcode progress
6. Check /api/speedtest/* for network issues
7. For WebDAV: test `http://HOST:8080/webdav.crt` — if 404, cert not generated yet
8. For SFTP: check `db/sftp_host.rsa` exists; verify port 2222 with `netstat -an`
9. For FTP: check firewall for ports 2121 AND 60000-60100

---

## 📚 Related Documentation

- **User Guide**: docs/USER_GUIDE.md
- **Linux Deployment**: docs/LINUX_DEPLOYMENT.md
- **Windows Deployment**: docs/WINDOWS_DEPLOYMENT.md
- **Android/Termux Deployment**: docs/ANDROID_DEPLOYMENT.md
- **Apache WSGI Production**: docs/DEPLOY_APACHE.md
- **Cloudflare Tunnel Setup**: docs/SETUP_TUNNEL_ADVANCED.md
- **rclone Integration**: docs/RCLONE_DEPLOYMENT.md
- **README**: README.md (quick start)

---

## 📝 Changelog

### Version 3.2 (2026-06-18)

#### Protocol Servers — WebDAV, SFTP, FTP

- **New file: `protocol_manager.py`**
  - `start_all()` starts WebDAV, SFTP, and FTP in background daemon threads
  - Called from `dev_server.py` and `prod_server.py` after Flask app loads
  - Graceful skip if any library is missing (prints install hint)

- **New file: `webdav_server.py`**
  - HTTP WebDAV on port 8080 (waitress or threaded wsgiref)
  - HTTPS WebDAV on port 8443 (cheroot + BuiltinSSLAdapter)
  - wsgidav 4.x domain controller (class, not instance; returns username string from `basic_auth_user`)
  - `_AuthCache`: bcrypt runs at most once per 30 seconds per user
  - `_RoleEnforcerMiddleware`: blocks write HTTP methods for `readonly` users before reaching wsgidav
  - `_CertMiddleware`: serves `db/webdav.crt` at `GET /webdav.crt` without authentication
  - Fixed `is_share_anonymous(self, share, environ=None)` — `environ` optional for wsgidav 4.3.x

- **New file: `sftp_server.py`**
  - Paramiko-based SSH/SFTP server on port 2222
  - RSA-2048 host key auto-generated in `db/sftp_host.rsa`
  - Full `SFTPServerInterface` implementation chrooted to `ROOT_DIR`
  - Proper `paramiko.SFTPHandle` with `readfile`/`writefile` (not monkeypatched)
  - Role-based access: `readonly` users blocked on all mutation operations

- **New file: `ftp_server.py`**
  - pyftpdlib FTP server on port 2121
  - `CloudinatorAuthorizer` — standalone class, no `DummyAuthorizer` inheritance
  - No-op `impersonate_user()` / `terminate_impersonation()` (avoids Windows `LogonUser` failure)
  - Passive data ports: 60000–60100

- **New file: `ssl_cert.py`**
  - Generates self-signed RSA-2048 TLS cert stored in `db/webdav.crt`
  - Detects all local IPs and embeds as Subject Alternative Names
  - `CA:TRUE` so it can be imported as Trusted Root CA on Windows/macOS/Linux
  - `--regenerate` flag for IP changes

- **Updated: `config.py`**
  - New variables: `WEBDAV_ENABLED`, `WEBDAV_PORT`, `WEBDAV_HTTPS_ENABLED`, `WEBDAV_HTTPS_PORT`, `SFTP_ENABLED`, `SFTP_PORT`, `FTP_ENABLED`, `FTP_PORT`
  - All variables persist in `server_config.json` via `save_server_config()` / `load_server_config()`
  - Interactive configuration available as option 13 in `python config.py`
  - `ENABLE_SEARCH_INDEX` now included in save/load (was previously missing)
  - Fixed `server_config.json` path: now anchored to `_HERE` (file directory) not CWD
  - Added `_HERE` and `_SERVER_CONFIG_FILE` constants at module level

- **Updated: `dev_server.py` and `prod_server.py`**
  - Added `import protocol_manager; protocol_manager.start_all()` after `from app import app`

### Version 3.1 (2026-06-04)

#### Video Player Improvements
- **Fixed subtitle/caption synchronization** (index.js)
  - CC button now always reflects current subtitle selection state
  - Selecting subtitle from dropdown automatically enables captions
  - Toggling CC button on/off remembers previously selected subtitle language
  - Improved track continuity: old track stays visible during new track load (prevents "disabled" flashing)
  
- **Subtitle Track State Management**
  - Added `_captionsEnabled` state variable to track caption visibility independent of track selection
  - Changed track mode logic: use `'hidden'` instead of `'disabled'` when subtitles are off
    - `'hidden'`: CC button can toggle it back on
    - `'disabled'`: CC button cannot toggle it
  - Refactored `_mountTrack()` to avoid gaps in track availability during language switches
  
- **CC Button Event Listener**
  - Improved `video.textTracks` change listener to:
    - Sync CC button state with dropdown selection
    - Restore selected subtitle when captions re-enabled
    - Prevent state flicker during rapid CC button toggles

**Impact**: Users no longer need to manually enable captions after selecting a subtitle; CC button state is always synchronized with actual subtitle selection.

### Version 3.0 (2026-05-27)

- Complete rewrite of media handling documentation
- Added full HLS streaming pipeline details
- Documented image compression and archive preview systems

---

**Last Updated**: 2026-06-18  
**For Questions**: Refer to source code comments marked with `###` or `# --`