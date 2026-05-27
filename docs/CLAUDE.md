# CloudinatorFTP — Complete Codebase Reference for AI-Assisted Development

**Version**: 3.0 | **Last Updated**: 2026-05-27  
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
16. [Admin Tools & Utilities](#admin-tools--utilities)
17. [Performance Characteristics](#performance-characteristics)
18. [Troubleshooting & Edge Cases](#troubleshooting--edge-cases)

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

**Core Design Philosophy**:
- Event-driven watchdog for instant monitoring
- Incremental caching (storage_index.json, file_index.json)
- Lazy initialization (nothing created on import)
- Modular systems (auth, storage, search, media all independent)
- Graceful fallbacks (missing ffmpeg → raw video, no libvips → raw images)

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

## 🔐 Authentication & Sessions

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
  │  └─ Get: resolution, fps, duration, audio tracks
  ├─ Determine profiles needed
  │  ├─ Standard: 144p–4K (all capped 30fps)
  │  └─ HFR: 720p60–4K60 (if source ≥48fps)
  ├─ Start background _run_hls_transcode() thread
  │  ├─ For each profile: ffmpeg multi-pass encode
  │  ├─ Output: manifest.m3u8 + .ts segments (6s each)
  │  ├─ Write .status.json with live % complete
  │  └─ Multi-audio support: -map 0:a:0 -map 0:a:1 etc.
  └─ Return: {status: 'transcoding', progress: 0%}
     → client polls /video_status/{cache_key}
     → when 100%, serve manifest.m3u8
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

---

## 🔗 Key Decision Points for Modifications

**When Adding Features**:
1. Import paths.py first for directory resolution
2. Use ensure_dirs() before creating files
3. Add watchdog hooks if monitoring needed
4. Update search_index if new indexable content
5. Add SSE event if real-time display needed
6. Test with both ENABLE_* flags True and False

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

---

## 📚 Related Documentation

- **User Guide**: docs/USER_GUIDE.md
- **Linux Deployment**: docs/LINUX_DEPLOYMENT.md
- **Windows Deployment**: docs/WINDOWS_DEPLOYMENT.md
- **Android/Termux Deployment**: docs/ANDROID_DEPLOYMENT.md
- **Apache WSGI Production**: docs/DEPLOY_APACHE.md
- **Cloudflare Tunnel Setup**: docs/SETUP_TUNNEL_ADVANCED.md
- **README**: README.md (quick start)

---

**Last Updated**: 2026-05-27  
**For Questions**: Refer to source code comments marked with `###` or `# --`
| **database.py** | User auth + SQLite | ~300 | `add_user()`, `check_login()`, `get_role()`, `rotate_server_token()` |
| **search_index.py** | Search indexing (FTS5) | ~350 | `SearchIndexManager`, `search()`, `add()`, `remove()` |
| **file_index.py** | Large folder caching | ~200 | `FileIndexManager`, `build_from_walk()`, `update_folder()` |
| **auth.py** | Auth helpers | ~100 | `is_logged_in()`, `login_user()`, `check_login()` |
| **config.py** | Settings + platform detection | ~150 | `PORT`, `CHUNK_SIZE`, `ENABLE_FFMPEG`, `ROOT_DIR` |
| **paths.py** | Central path resolver | ~80 | `get_db_dir()`, `get_cache_dir()`, `get_hls_cache_dir()` |

### Common Commands

```bash
# Run development server
python dev_server.py

# Run production server  
python prod_server.py

# Manage users
python create_user.py

# Change default passwords
python reset_db.py

# Invalidate all sessions
python revoke_session.py

# Debug login
python debug_passwords.py
```

### Key Settings to Know

```python
# config.py
PORT = 5000
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_CONTENT_LENGTH = 16 * 1024 * 1024 * 1024  # 16 GB
PERMANENT_SESSION_LIFETIME = 3600  # 1 hour
ENABLE_FFMPEG = True  # Video streaming
ENABLE_LIBVIPS = True  # Image compression
ENABLE_SEARCH_INDEX = True  # SQLite FTS5
HLS_MIN_SIZE = 50 * 1024 * 1024  # Files > 50 MB use HLS
IMG_COMPRESS_MIN_SIZE = 1 * 1024 * 1024  # Images > 1 MB use WebP
IMG_WEBP_QUALITY = 50  # WebP lossy quality
```

---

## 🏗️ Architecture Overview

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER INTERACTION                             │
│  (Browser: login.html, index.html, viewer.html)                │
└────────────────────┬────────────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────────────┐
│                   FLASK ROUTES (app.py)                         │
│  GET / | POST /upload_chunk | GET /download | GET /search      │
│  POST /create_folder | POST /rename | POST /delete | POST /copy │
└────┬────────────┬────────────┬────────────┬────────────┬────────┘
     │            │            │            │            │
     ▼            ▼            ▼            ▼            ▼
┌─────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐
│ storage │  │  auth   │  │ database │  │realtime_ │  │ config  │
│ (file I/O)│ │(session)│  │ (users)  │  │ stats    │  │ (setup) │
└────┬────┘  └────┬────┘  └────┬─────┘  └────┬─────┘  └────┬────┘
     │            │            │             │             │
     │            └────────────┴─────────────┴─────────────┘
     │                         │
     ▼                         ▼
┌──────────────────────────────────────────┐
│   SQLite: cloudinator.db + search_index.db
│   ├─ users (bcrypt + Fernet encryption)
│   ├─ server_token (session management)
│   └─ files_meta + files (FTS5 index)
└──────────────────────────────────────────┘
     ▲     ▲                      ▲
     │     │                      │
     │     ├──────────┬───────────┤
     │            │            │
     ▼            ▼            ▼
┌──────────┐ ┌─────────┐ ┌──────────────┐
│ Watchdog │ │ File    │ │ Search Index │
│ Monitor  │ │ Index   │ │ Crawler      │
│          │ │ (>80)   │ │ (daemon)     │
└────┬─────┘ └────┬────┘ └──────┬───────┘
     │            │             │
     ▼            ▼             ▼
┌────────────────────────────────────────────────────────────────┐
│              CACHE DIR (db/, cache/, hls/, img_cache/)        │
│  ├─ storage_index.json (reconciliation snapshot)              │
│  ├─ file_index.json (large folder listing)                    │
│  ├─ search_index.db (FTS5 search database)                    │
│  ├─ .hls/ → ffmpeg transcodes (*.m3u8, *.ts)                 │
│  ├─ .img_cache/ → pyvips WebP conversions                     │
│  └─ .chunks/ → temporary upload chunks                        │
└────────────────────────────────────────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────────────────┐
│                  FILE STORAGE (ROOT_DIR)                       │
│  User files organized in folders                              │
│  Platform-specific: ~/Downloads, ~/Documents, etc.            │
└────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
UPLOAD:
  Browser → POST /upload_chunk → save_chunk() → .chunks/file_id/chunk_N
         → POST /assemble → assemble_chunks() → final file → watchdog.on_created
         → increment counters → update indices → SSE broadcast

DOWNLOAD:
  Browser → GET /download/path → send_from_directory() → browser

DELETE:
  Browser → POST /delete → storage.safe_rmtree() → watchdog.on_deleted
         → decrement counters → remove from indices → SSE broadcast

SEARCH:
  Browser → GET /search?q=term → search_index_manager.search()
         → Query FTS5 (or fallback os.walk) → return results

FILE MONITOR (Real-Time):
  watchdog.observer → on_created/on_deleted/on_moved/on_modified
              → update _dir_info + file_index + search_index
              → debounce 0.5s → _notify_and_save()
              → event_manager.broadcast_update() → all SSE clients
  
  Every 15 min: _reconcile() walks ROOT_DIR → ground-truth counters
              → force-push reconcile_complete=True SSE
```

---

## 📦 Core Modules

### storage.py — File I/O Operations

**Key Classes & Functions:**

```python
def list_dir(path: str) -> list[dict]
    # Returns sorted list (dirs first, then files, both alphabetical)
    # Uses file_index.json cache for folders > 80 entries
    # Falls back to os.scandir() for smaller folders
    # Returns: [{"name": str, "is_dir": bool, "size": int|None, "modified": float}]

def ensure_root()
    # Create ROOT_DIR if missing

def save_chunk(file_id: str, chunk_num: int, chunk_data: bytes) -> bool
    # Save to ROOT_DIR/.chunks/<file_id>/<chunk_num>
    # Create .timestamp for cleanup tracking

def verify_chunks_complete(file_id: str, expected_chunks: int|None) -> dict
    # Verify all chunks 0..N exist and are readable
    # Returns: {total_chunks, total_size, chunk_map, tmp_dir}

def assemble_chunks(file_id: str, filename: str, dest_path: str = "") -> bool
    # Merge chunks into single file
    # Creates .assembling protection marker during assembly

def cleanup_chunks(file_id: str)
    # Remove ROOT_DIR/.chunks/<file_id>/ directory

def cleanup_old_chunks(max_age_hours: int = 24, protected_files: set | None = None)
    # Batch remove chunks older than max_age_hours
    # Skips chunks for active assembly jobs

def create_folder(path: str, foldername: str) -> bool
def delete_path(path: str) -> bool
    # Safe on Windows (handles read-only files via os.chmod)

def move_item(source_path, dest_path) -> bool
def copy_item(source_path, dest_path) -> bool
    # Recursive operations

def get_dir_info(path) -> dict
    # {file_count, dir_count, total_size}
    # Cached via file_monitor._dir_info (instant lookup)
    # Falls back to live walk if path not yet indexed

def get_storage_stats() -> dict
    # {total_space, used_space, free_space, file_count, dir_count, content_size}
    # Disk stats instant, file counting has 5-second timeout

def is_safe_path(path) -> bool
    # Prevent directory traversal attacks

def is_valid_path(path) -> bool
    # Path is safe AND exists AND is directory
```

**Key Behavior:**
- Windows: Safe delete via `os.chmod(S_IWRITE)` before removal
- Chunked uploads: Temporary `.chunks/` directory, cleaned on failure
- Large folder optimization: Caches folders > 80 entries in file_index.json

---

### file_monitor.py — Real-Time Filesystem Monitoring

**Key Class:**

```python
class FileSystemMonitor:
    """
    Maintains global counters: file_count, dir_count, total_size
    + directory index (_dir_info) for recursive totals at any path
    """
    
    start_monitoring()
        # Load cache OR do full walk
        # Start watchdog observer + reconciliation thread
    
    get_current_snapshot() -> StorageSnapshot
        # Returns: {file_count, dir_count, total_size, last_modified}
    
    get_dir_info(rel_path: str) -> dict | None
        # Instant cache lookup: {file_count, dir_count, total_size}
        # Returns None if path not yet indexed
    
    add_change_callback(callback: Callable)
        # Receive (old_snapshot, new_snapshot, reconcile_complete=bool)
    
    _reconcile()
        # Silent 15-minute consensus walk
        # Corrects counter drift from watchdog race conditions
        # Force-pushes single reconcile_complete=True SSE event
    
    _full_walk()
        # Ground-truth file counting from scratch
        # Called during reconciliation

class InstantFileEventHandler:
    """Handles on_created, on_deleted, on_moved, on_modified events"""
    # on_created: increment counters + update dir_info + update file_index + search_index
    # on_deleted: decrement counters + bubble up tree + remove from indices
    # on_moved: migrate dir_info keys + update file_index + update search_index
```

**Key Behavior:**
- Instant counter updates on file operations
- 0.5s debounce on notifications to SSE clients
- 15-minute reconciliation walk to correct drift
- Burst detection: >200 events in <5s triggers forced settle
- Cascade updates: Changes bubble up directory tree

---

### search_index.py — Search Indexing (FTS5)

**Key Class:**

```python
class SearchIndexManager:
    """SQLite FTS5 trigram index for fast filename queries"""
    
    start_crawler()
        # Background thread walks ROOT_DIR once, populates DB
        # Sleeps 10ms between directories to avoid I/O saturation
        # Skips crawl if index already exists (instant ready on restart)
    
    search(query: str, max_results: int = 100) -> (list, bool)
        # Returns (results, from_index)
        # from_index=True: results from FTS5
        # from_index=False: fallback os.walk (crawler still running)
    
    add(rel_path: str, name: str, is_dir: bool)
        # Insert into files + files_meta when new entry created
    
    remove(rel_path: str)
        # Delete from both tables when entry deleted
    
    remove_tree(rel_path_prefix: str)
        # Remove folder and all children
    
    rename_tree(old_prefix: str, new_prefix: str)
        # Update all paths under renamed folder
```

**Search Flow:**
```
GET /search?q=vacation&ext=jpg
    ├─ search_index_manager.search("vacation", max_results=100)
    │   ├─ If _ready: Query FTS5 → SELECT * WHERE name MATCH 'vacation'
    │   ├─ Else: Fallback os.walk() + fnmatch
    │   └─ Optional ext filter: WHERE ext_lower = '.jpg'
    └─ Return: JSON {results: [...], from_index: bool}
```

**Modes:**
- **FTS5 Trigram**: SQLite ≥ 3.34 → instant substring matching
- **LIKE Fallback**: Older SQLite / Termux → single full-table scan

---

### file_index.py — Large Folder Caching

**Key Class:**

```python
class FileIndexManager:
    """Large folder caching (threshold: 80 direct entries)"""
    
    build_from_walk(direct_entries: dict)
        # Called after _full_walk completes
        # Filters to folders > 80 entries, saves to file_index.json
    
    get_entries(rel_path: str) -> list | None
        # Return cached entry list for folder (matches list_dir format)
    
    update_folder(rel_path: str, abs_path: str)
        # Re-scan single folder (O(entries), not recursive)
        # Call when files added/deleted/moved
    
    remove_folder(rel_path: str)
        # Remove folder and all descendants from cache
    
    rename_folder(old_rel: str, new_rel: str)
        # Migrate all cached paths when folder renamed/moved
```

**Purpose:**
- Direct filesystem scans are slow for large folders
- Cached folders (>80 entries) loaded from RAM (instant)
- Updated incrementally by watchdog, not full walk

---

### database.py — SQLite User Management

**Database Class Methods:**

```python
def check_login(username: str, password: str) -> bool
    # Live DB check of bcrypt hash + Fernet-encrypted password

def get_role(username: str) -> str | None
    # Return 'readwrite', 'readonly', or None

def add_user(username: str, password: str, role: str) -> bool
    # Create new user with bcrypt hash

def delete_user(username: str) -> bool
    # Remove user from database

def update_password(username: str, new_password: str) -> bool
    # Change password (bcrypt hash)

def update_role(username: str, role: str) -> bool
    # Change 'readwrite' or 'readonly'

def user_exists(username: str) -> bool

def list_users() -> list[dict]
    # Return all users (no passwords)

def get_server_token() -> str
    # Return current session token

def rotate_server_token() -> str
    # Generate new token (invalidates all sessions immediately)
```

**Encryption:**
- Password hashes: bcrypt (12 rounds) → Fernet-encrypted before storage
- Session key: Stored in `db/secret.key` (Fernet format)
- Session signing: `db/session.secret` (64-char hex, Flask requirement)

**User Table Schema:**
```sql
CREATE TABLE users (
    id              INTEGER PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash   TEXT NOT NULL,  -- bcrypt + Fernet encrypted
    role            TEXT NOT NULL DEFAULT 'readonly',  -- readwrite or readonly
    created_at      REAL NOT NULL DEFAULT (unixepoch()),
    last_login      REAL
);
```

---

### auth.py — Authentication Helpers

```python
def check_login(username: str, password: str) -> bool
    # Verify credentials (calls database.check_login)

def login_user(username: str)
    # Set session['username'], session['role'], session['server_token']

def logout_user()
    # Clear session completely

def is_logged_in() -> bool
    # Validate session + verify server_token hasn't rotated + user exists

def get_role(username: str) -> str | None
    # Return user's role

def current_user() -> str | None
    # Return username from session (may be invalid, use is_logged_in() to verify)
```

---

### config.py — Configuration Management

```python
# Server Settings
PORT = 5000
HOST = "0.0.0.0"
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB per chunk
MAX_CONTENT_LENGTH = 16 * 1024 * 1024 * 1024  # 16 GB max file
PERMANENT_SESSION_LIFETIME = 3600  # 1 hour

# Feature Toggles
ENABLE_CHUNKED_UPLOADS = True
ENABLE_FFMPEG = True  # HLS video streaming
ENABLE_LIBVIPS = True  # Image WebP conversion
ENABLE_SEARCH_INDEX = True  # SQLite FTS5

# HLS Video Streaming
HLS_MIN_SIZE = 50 * 1024 * 1024  # 50 MB threshold
HLS_FORCE_FORMATS = {"mkv", "avi", "wmv", "flv", ...}
    # Always transcode to HLS regardless of size

# Image Compression
IMG_COMPRESS_MIN_SIZE = 1 * 1024 * 1024  # 1 MB threshold
IMG_WEBP_QUALITY = 50  # Lossy quality (1-100)

# Platform Detection
ROOT_DIR = setup_storage_directory()
    # Auto-detects and uses ~/Downloads, ~/Documents, etc.
    # Overridable via env: CLOUDINATOR_FTP_ROOT=/custom/path

# Path Resolution
DB_DIR = get_db_dir()  # <root>/db
CACHE_DIR = get_cache_dir()  # <root>/cache
HLS_CACHE_DIR = get_hls_cache_dir()  # <cache>/hls
IMG_CACHE_DIR = get_img_cache_dir()  # <cache>/img
```

---

### realtime_stats.py — Server-Sent Events

```python
class StorageStatsEventManager:
    broadcast_update(old_snapshot, new_snapshot, 
                     reconcile_complete=False, walk_progress=False)
        # Push SSE to all connected clients
        # reconcile_complete=True: frontend refreshes file table
        # walk_progress=True: update stats panel only (during reconcile)
    
    storage_stats_sse()
        # SSE endpoint that yields:
        # 1. "connected" message
        # 2. Initial stats snapshot
        # 3. Continuous updates from broadcast_update()
```

**Event Types:**

| Event | Trigger | Frontend Action |
|-------|---------|-----------------|
| `connected` | On SSE connection | Show "connected" status |
| `initial` | Client connects | Load initial stats snapshot |
| `storage_stats_update` | File ops | Update stats panel + file table |
| `storage_stats_update` (walk_progress) | During reconcile walk | Update stats only (no table refresh) |
| `storage_stats_update` (reconcile_complete) | Reconcile finishes | Refresh stats + file table + all cells |
| `ping` | After 10s idle | Keep-alive (prevents disconnect) |

---

## 🔌 Flask Routes & API

### Authentication

```python
POST   /login                    # User login (form submit)
GET    /logout                   # Clear session, redirect to login
GET    /check_session            # JSON: verify session validity
```

### File Operations

```python
GET    /                         # List root directory
GET    /<path>                   # List specific directory / open file
GET    /download/<path>          # Download file (as attachment)
GET    /view/<path>              # View file inline (images, PDF, video)
GET    /pdfviewer                # PDF viewer UI
GET    /office_preview/<path>    # Convert Office docs to HTML/JSON
POST   /create_folder            # Create new folder
POST   /delete                   # Delete file or folder
POST   /rename                   # Rename file or folder
POST   /move                     # Move file to different folder
POST   /copy                     # Copy file or folder (recursive)
```

### Media Streaming

```python
GET    /media/<type>/<file_id>/<filename>  # HLS master playlist (.m3u8)
GET    /segment/<segment_id>               # HLS video segment (.ts)
GET    /image_proxy/<path>                 # Image with optional WebP conversion
```

### Upload Operations

```python
POST   /upload_chunk               # Upload single file chunk
POST   /upload_status/<file_id>    # Check upload progress
POST   /assemble                   # Finalize chunked upload
POST   /cancel_upload              # Stop chunked upload in progress
POST   /cancel_bulk_zip            # Cancel ZIP download
GET    /admin/upload_status        # Bulk upload status page
```

### Search & Utilities

```python
GET    /search                     # Search endpoint (?q=term&ext=jpg)
GET    /api/storage_stats          # Server-Sent Events stream
GET    /api/dir_info/<path>        # Get folder info on-demand
GET    /zip_preview/<path>         # Generate ZIP preview
```

---

## 🔐 Database Schema

### cloudinator.db

```sql
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash   TEXT NOT NULL,  -- bcrypt + Fernet encrypted
    role            TEXT NOT NULL DEFAULT 'readonly'
        CHECK(role IN ('readwrite','readonly')),
    created_at      REAL NOT NULL DEFAULT (unixepoch()),
    last_login      REAL
);

CREATE TABLE server_token (
    id              INTEGER PRIMARY KEY CHECK(id = 1),
    token           TEXT NOT NULL,  -- UUID, changes on revoke
    updated_at      REAL NOT NULL DEFAULT (unixepoch())
);
```

### search_index.db

```sql
-- files_meta: Always present (metadata)
CREATE TABLE files_meta (
    rel_path        TEXT PRIMARY KEY,
    name_lower      TEXT NOT NULL,
    ext_lower       TEXT NOT NULL DEFAULT '',
    is_dir          INTEGER NOT NULL DEFAULT 0
);

-- files: FTS5 virtual table (if SQLite >= 3.34)
CREATE VIRTUAL TABLE files USING fts5(
    name, rel_path, is_dir, parent_rel,
    tokenize='trigram'
);

-- files: LIKE fallback (older SQLite / Termux)
CREATE TABLE files (
    rel_path        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_lower      TEXT NOT NULL,
    is_dir          INTEGER NOT NULL DEFAULT 0,
    parent_rel      TEXT NOT NULL DEFAULT ''
);
```

### Cache Files

**storage_index.json** (reconciliation snapshot):
```json
{
  "file_count": 12345,
  "dir_count": 543,
  "total_size": 1099511627776,
  "last_modified": 1712505600.0,
  "dir_info": {
    "": { "file_count": 100, "dir_count": 5, "total_size": ... },
    "Documents": { "file_count": 500, "dir_count": 10, ... }
  }
}
```

**file_index.json** (large folder listings):
```json
{
  "version": 1,
  "threshold": 80,
  "dirs": {
    "": { "entry_count": 152, "entries": [...] },
    "LargeFolder": { "entry_count": 500, "entries": [...] }
  }
}
```

---

## 🔐 Authentication Flow

```
User Submission (login.html form)
    ↓
POST /login (check RateLimiter)
    ├─ If blocked: return "Too many attempts, try again in Xs"
    └─ Proceed to credentials check
    ↓
check_login(username, password)
    ├─ Query: SELECT password_hash FROM users WHERE username=?
    ├─ Decrypt: Fernet.decrypt(password_hash) → bcrypt hash
    ├─ Verify: bcrypt.checkpw(password, hash)
    └─ Return: True or False
    ↓
[FAILED]
    ├─ RateLimiter.record_failure()
    ├─ If 5+ failures in 60s → lock IP for 300s
    └─ Flash message + redirect /login
    ↓
[SUCCESS]
    ├─ RateLimiter.record_success() (clear attempts)
    ├─ Create session:
    │   ├─ session.permanent = True
    │   ├─ session['username'] = username
    │   ├─ session['role'] = db.get_role(username)
    │   ├─ session['server_token'] = db.get_server_token()
    │   ├─ session['logged_in'] = True
    │   └─ session['login_time'] = int(time.time())
    ├─ db.update_last_login(username)
    └─ Redirect /
    ↓
Subsequent Requests
    ├─ Check @login_required:
    │   ├─ session.get('logged_in') == True
    │   ├─ session['server_token'] == db.get_server_token()
    │   └─ db.get_role(session['username']) is not None
    ├─ If any fail: clear session → redirect /login
    └─ Proceed with request

Session Lifetime
    ├─ PERMANENT_SESSION_LIFETIME = 3600 (1 hour)
    ├─ SESSION_REFRESH_EACH_REQUEST = True (resets on each request)
    └─ HTTP-only cookie: cloudinator_session=...

Logout Flow
    ├─ chunk_tracker.cleanup_session_chunks(session_id)
    ├─ session.clear()
    ├─ Delete-Cookie
    └─ Redirect /login

Quick Session Invalidation
    └─ python revoke_session.py
        ├─ db.rotate_server_token() (new UUID)
        ├─ All existing cookies fail token check
        └─ All users redirected /login within 5s
```

---

## 📤 File Operations

### Upload (Chunked)

```
User selects files → File picker or drag-drop
    ↓
Generate: file_id = UUID, total_chunks = ceil(file_size / CHUNK_SIZE)
    ↓
chunk_tracker.track_upload(session_id, file_id)
    ↓
[For each chunk 0..N-1]
    ├─ POST /upload_chunk
    │   ├─ storage.save_chunk(file_id, chunk_num, data)
    │   └─ Create: .chunks/<file_id>/<chunk_num> + .timestamp
    ├─ assembly_queue.add_job(file_id, filename, dest_path, total_chunks)
    │   └─ status = "pending"
    └─ GET /upload_status/<file_id> (poll for progress)
    ↓
[All chunks received]
    ├─ POST /assemble
    ├─ assembly_queue.update_job(status="processing")
    ├─ storage.verify_chunks_complete(file_id, total_chunks)
    ├─ storage.assemble_chunks(file_id, filename, dest_path)
    │   ├─ Create .assembling protection marker
    │   ├─ Merge all chunks into final file
    │   └─ Delete .chunks/<file_id>/
    ├─ assembly_queue.complete_job(success=True)
    ├─ chunk_tracker.untrack_upload(session_id, file_id)
    └─ watchdog.on_created → increment counters + SSE broadcast

Cleanup (Background):
    ├─ chunk_tracker.cleanup_interrupted_uploads() (every request)
    │   └─ >30 min inactive → cleanup + untrack
    ├─ chunk_tracker.cleanup_orphaned_chunks() (every request)
    │   └─ >45 min untracked or >1 hour tracked → remove
    └─ storage.cleanup_old_chunks() (every 15 min reconcile)
        └─ >24 hours old → remove
```

### Download (Bulk ZIP)

```
User selects: [Documents] [Videos] [Photo.jpg]
    ↓
GET /bulk_download?files=[...] (with zipstream.ZipStream)
    ↓
For each file/folder:
    ├─ Check is_safe_path()
    ├─ Yield 1 MB chunks to client
    └─ Check if bulk_zip_cancelled[session_id]
    ↓
[User cancels or closes]
    ├─ POST /cancel_bulk_zip
    └─ bulk_zip_cancelled[session_id] = True (stops yielding)
```

### Delete

```
POST /delete with path="Documents"
    ↓
storage.is_safe_path(path) → storage.safe_rmtree()
    ├─ Windows: os.chmod(S_IWRITE) + shutil.rmtree
    └─ Unix: normal shutil.rmtree
    ↓
watchdog.on_deleted
    ├─ Decrement _file_count / _dir_count / _total_size
    ├─ Remove from _dir_info (cascade up tree)
    ├─ Remove from file_index.json
    ├─ Remove from search_index.db
    └─ Schedule _notify_and_save() (debounced 0.5s)
    ↓
event_manager.broadcast_update() → all SSE clients
```

### Copy / Move / Rename

```
POST /copy OR POST /rename OR POST /move
    ↓
storage.copy_item() OR os.rename()
    ↓
watchdog events fire:
    ├─ on_created (for copies) OR on_moved (for renames)
    ├─ Burst detection: >200 events in <5s
    │   └─ Suppress incremental updates + force reconcile
    ├─ Update indices (file_index, search_index)
    └─ Schedule _notify_and_save()
    ↓
event_manager.broadcast_update() → all SSE clients
```

---

## 📹 Media Handling

### Video Streaming (HLS)

**Config:**
```python
ENABLE_FFMPEG = True
HLS_MIN_SIZE = 50 * 1024 * 1024  # 50 MB
HLS_FORCE_FORMATS = {"mkv", "avi", "wmv", "flv", ...}
```

**Flow:**
```
GET /view/<path>.mp4
    ↓
├─ If file < 50 MB AND format is web-native (mp4, webm)
│   └─ send_from_directory() → raw playback
├─ Else (large file OR non-native format):
│   ├─ Check: .hls/<hash>.m3u8 exists?
│   ├─ If not: spawn ffmpeg subprocess
│   │   └─ ffmpeg -i <input> -hls_time 10 -f hls output.m3u8
│   │       → Creates: output.m3u8 + segments (.ts files)
│   └─ Return: m3u8 playlist as JSON
│       └─ Frontend: hls.js loads segments adaptively
└─ GET /segment/<segment_id> → send .ts file
```

**Fallback:** If FFmpeg not installed → raw playback (no error)

### Image Compression (WebP)

**Config:**
```python
ENABLE_LIBVIPS = True
IMG_COMPRESS_MIN_SIZE = 1 * 1024 * 1024
IMG_WEBP_QUALITY = 50
```

**Flow:**
```
GET /view/<path>.jpg
    ↓
├─ If file < 1 MB → send raw image
├─ Else:
│   ├─ Check: .img_cache/<hash>.webp exists?
│   ├─ If not: pyvips.Image.new_from_file()
│   │   └─ img.write_to_buffer('.webp', quality=50)
│   └─ send_from_directory() → WebP (~10x smaller)
```

**Fallback:** If libvips not installed → raw image (no error)

### Office Document Preview

**Supported:**
- `.docx` → mammoth → HTML
- `.xlsx` → openpyxl → JSON (sheets + cells)
- `.pptx` → python-pptx → PNG images
- `.csv` → csv module → JSON table

**Flow:**
```
POST /office_preview/<path>.docx
    ├─ Load file
    ├─ Switch on extension:
    │   ├─ .docx: mammoth.convert_to_html()
    │   ├─ .xlsx: openpyxl + iterate sheets
    │   ├─ .pptx: convert_slide_to_image()
    │   └─ .csv: csv.reader()
    └─ Return: JSON {type, html/sheets/images/...}
```

### Archive Preview (ZIP/RAR/7Z)

**Supported:** `.zip` / `.rar` / `.7z`

**Flow:**
```
GET /zip_preview/<path>.zip
    ├─ zipfile.ZipFile() OR rarfile.RarFile() OR py7zr.SevenZipFile()
    ├─ infolist() → extract metadata
    └─ Return: JSON {entries: [...], total_size, compressed_size}
```

---

## 🔍 Search & Indexing

### Search Flow

```
User enters: [search box] "vacation *.jpg"
    ↓
GET /search?q=vacation&ext=jpg
    ↓
search_index_manager.search("vacation", max_results=100)
    ├─ If _ready: Query FTS5
    │   └─ SELECT rel_path FROM files WHERE name MATCH 'vacation'
    │   + Filter: WHERE ext_lower = '.jpg'
    ├─ Else (crawler running): Fallback os.walk() + fnmatch
    └─ Return: (results, from_index=bool)
    ↓
Frontend:
    ├─ Render results table
    ├─ Click row → download, preview, or open folder
    └─ Show "from_index" badge if FTS5 was used
```

### Index Modes

| Mode | Requirement | Query | Performance |
|------|-------------|-------|-------------|
| **FTS5 Trigram** | SQLite ≥ 3.34 | MATCH 'query' | Instant (any substring) |
| **LIKE Fallback** | Older SQLite / Termux | LIKE '%query%' | Fast (full-table scan) |

### Crawler

```
start_crawler() [daemon thread]
    ├─ os.walk(ROOT_DIR)
    ├─ For each directory:
    │   ├─ Scan entries
    │   ├─ search_index.add(rel_path, name, is_dir)
    │   ├─ sleep(10 ms) [avoid I/O saturation]
    │   └─ _ready = False
    ├─ Done: _ready = True
    └─ [Subsequent restarts: skip crawl, DB already populated]

watchdog triggers:
    ├─ on_created → search_index.add()
    ├─ on_deleted → search_index.remove()
    └─ on_moved → search_index.rename_tree()
```

---

## 🔄 Real-Time Features

### Server-Sent Events (SSE)

**Endpoint:** `GET /api/storage_stats`
- Content-Type: text/event-stream
- Chunks of JSON data pushed to client

**Event Flow:**

```
Client connects → SSE endpoint
    ↓
event_stream() generator
    ├─ yield "data: {connected...}\n\n"
    ├─ yield "data: {initial_stats...}\n\n"
    └─ Loop: yield from client_queue (with 10s timeout)
    ↓
watchdog on_created/on_deleted/on_moved/on_modified
    ├─ Update counters + indices
    ├─ Debounce 0.5s → _notify_and_save()
    ├─ event_manager.broadcast_update()
    │   └─ Push to all client_queues
    └─ Each client yields: "data: {...update...}\n\n"
```

**Event Types:**

| Event | Payload | Frontend Action |
|-------|---------|-----------------|
| `connected` | {} | Show "connected" badge |
| `initial` | {stats snapshot} | Load initial state |
| `storage_stats_update` | {file_count, dir_count, etc.} | Update stats panel + file table |
| `storage_stats_update` (walk_progress) | {walk_progress: true} | Update stats panel only |
| `storage_stats_update` (reconcile_complete) | {reconcile_complete: true} | Refresh entire UI |
| `ping` | {} | Keep-alive (prevents disconnect) |

### Reconciliation

```
Every 15 minutes: _reconcile() thread wakes up
    ├─ Suppress watchdog counter updates (_pending_reconcile = True)
    ├─ _full_walk() counts everything from scratch
    ├─ Bump epoch → in-flight watchdog events ignored
    ├─ Wait 6s for OS event queue to drain
    └─ Single force-push: reconcile_complete=True SSE
        └─ Frontend: refresh file table + all dir-info cache
```

### Debouncing

- Watchdog events: 0.5s debounce
- Max accumulation: 3.0s (force push during heavy uploads)
- Reconciliation: single authoritative push

---

## ⚙️ Configuration

### Essential Settings

```python
# config.py

# Server
PORT = 5000
HOST = "0.0.0.0"

# Upload
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB per chunk
MAX_CONTENT_LENGTH = 16 * 1024 * 1024 * 1024  # 16 GB max

# Session
PERMANENT_SESSION_LIFETIME = 3600  # 1 hour
SESSION_REFRESH_EACH_REQUEST = True

# Features
ENABLE_FFMPEG = True  # Video streaming
ENABLE_LIBVIPS = True  # Image compression
ENABLE_SEARCH_INDEX = True  # FTS5 search

# Media
HLS_MIN_SIZE = 50 * 1024 * 1024  # 50 MB threshold for HLS
IMG_COMPRESS_MIN_SIZE = 1 * 1024 * 1024  # 1 MB threshold for WebP
IMG_WEBP_QUALITY = 50  # WebP quality (1-100)

# Root Directory
ROOT_DIR = setup_storage_directory()  # Auto-detects ~/Downloads, etc.
    # Or: export CLOUDINATOR_FTP_ROOT=/custom/path
```

### Environment Variables

```bash
# Override root directory
export CLOUDINATOR_FTP_ROOT=/large/external/disk

# Run on different port
export PORT=8080
```

---

## 🐛 Troubleshooting

### Search Returns No Results

**Cause:** Crawler still running, or file not indexed

**Solution:**
```bash
# Check crawler status
curl http://localhost:5000/api/search?q=test

# If 'from_index: false', crawler is still running
# Wait 1-2 minutes for initial walk to complete
```

### Uploads Timing Out

**Cause:** PERMANENT_SESSION_LIFETIME too short or large chunk timing out

**Solution:**
```python
# config.py
PERMANENT_SESSION_LIFETIME = 7200  # 2 hours
CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB (smaller chunks)
```

### File Count Wrong After Uploads/Deletes

**Cause:** Watchdog missed events during burst

**Solution:**
- Wait 15 minutes for automatic reconciliation
- Or manually trigger: `curl -X POST http://localhost:5000/admin/rebuild_cache`

### Video Won't Play

**Check:**
```bash
# Verify FFmpeg installed
ffmpeg -version

# Enable HLS transcoding
# config.py: ENABLE_FFMPEG = True

# Check if file is large enough for HLS
# HLS_MIN_SIZE = 50 MB (files <50 MB play raw)
```

### Images Loading Slowly

**Check:**
```bash
# Verify libvips installed
vips --version

# Enable WebP compression
# config.py: ENABLE_LIBVIPS = True

# Check quality vs file size
# IMG_WEBP_QUALITY = 50 (lower = smaller but worse quality)
```

---

## 📝 Common Development Tasks

### Add a New Route

```python
# app.py
@app.route('/api/my_endpoint', methods=['GET', 'POST'])
@login_required
def my_endpoint():
    # Your logic here
    return jsonify(result)
```

### Add a Configuration Option

```python
# config.py
MY_SETTING = os.getenv('MY_SETTING', 'default_value')
```

### Update Search Index

```python
# Automatically called by watchdog
from search_index import search_index_manager

search_index_manager.add(rel_path, name, is_dir)
search_index_manager.remove(rel_path)
search_index_manager.rename_tree(old_prefix, new_prefix)
```

### Add a User

```bash
python create_user.py
# Select: 2. Add user
# Enter: username, password, role
```

### Reset Everything

```bash
python reset_db.py  # Wipes database
python setup_storage.py  # Reconfigure storage path
```

---

## 📚 Important Notes

1. **Thread Safety:** Watchdog runs in background thread; counters use locks
2. **Cache Invalidation:** Reconciliation every 15 minutes corrects any drift
3. **Windows Compatibility:** Special handling for read-only files via `os.chmod`
4. **Mobile:** All code checked for mobile/responsive layout
5. **Backward Compatibility:** FTS5 fallback to LIKE for older SQLite versions

---

**Last Updated:** 2026-04-08  
**Maintained for:** Development using Claude AI assistant
