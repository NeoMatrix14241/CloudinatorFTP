# CloudinatorFTP — Codebase Reference for AI-Assisted Development

**Version**: 2.0 | **Last Updated**: 2026-04-08  
**For**: Developers using Claude AI to modify and extend the codebase

---

## 📋 Table of Contents

1. [Quick Reference](#quick-reference)
2. [Architecture Overview](#architecture-overview)
3. [Core Modules](#core-modules)
4. [Flask Routes & API](#flask-routes--api)
5. [Database Schema](#database-schema)
6. [Authentication Flow](#authentication-flow)
7. [File Operations](#file-operations)
8. [Media Handling](#media-handling)
9. [Search & Indexing](#search--indexing)
10. [Real-Time Features](#real-time-features)
11. [Configuration](#configuration)
12. [Troubleshooting](#troubleshooting)

---

## ⚡ Quick Reference

### Most Important Files

| File | Purpose | Line Count | Key Functions |
|------|---------|-----------|----------------|
| **app.py** | Flask routes + server logic | ~1500 | `list_dir()`, `upload_chunk()`, `assemble()`, `download()`, `search()` |
| **storage.py** | File I/O operations | ~600 | `list_dir()`, `save_chunk()`, `assemble_chunks()`, `delete_path()` |
| **file_monitor.py** | Real-time filesystem watching | ~400 | `FileSystemMonitor` class, `_reconcile()`, `_full_walk()` |
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
