# CloudinatorFTP - Codebase Documentation for Claude AI

**Version**: 1.0 | **Last Updated**: 2026-04-06  
**Purpose**: Comprehensive codebase reference for AI-assisted development

This document provides a complete overview of the CloudinatorFTP project architecture, components, and design patterns. It remains stable and canonical regardless of future changes or deprecations.

---

## 📋 PROJECT OVERVIEW

### What is CloudinatorFTP?

CloudinatorFTP is a lightweight, cross-platform file sharing server that:
- Runs on **Windows, Linux, and Android (Termux)**
- Exposes file storage via a secure web interface
- Integrates with **Cloudflare Tunnels** for internet accessibility
- Supports role-based access control (admin/guest)
- Handles chunked uploads for large files (up to 16GB)
- Provides real-time storage monitoring
- Includes media streaming (HLS video, WebP image conversion)

### Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.10+ with Flask 3.1.3 |
| **Database** | SQLite with Fernet encryption |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript |
| **File Processing** | FFmpeg (video HLS), libvips (image compression) |
| **Archive Support** | ZIP, RAR, 7Z handling |
| **Streaming** | Server-Sent Events (SSE), chunked uploads |
| **Security** | bcrypt passwords, Fernet field encryption, rate limiting |
| **Deployment** | Flask dev, Waitress production, Apache mod_wsgi |

---

## ⚡ QUICK REFERENCE

**Use this section alone for ~80% of common questions. Just copy-paste this entire section when asking about:**
- Authentication flows
- Common file operations
- Database queries
- Configuration changes
- Typical troubleshooting
- Command-line tools
- API endpoint usage

### Key Commands

```bash
# User Management
python create_user.py              # Interactive menu: add/delete/change users
python debug_passwords.py          # Test credentials
python reset_db.py                 # DESTRUCTIVE: wipe DB, use defaults (admin/admin123, guest/guest123)

# Session Management
python revoke_session.py           # Rotate server token → log out all users instantly

# Storage Configuration
python setup_storage.py            # Interactive: configure storage/db/cache paths

# Server
python dev_server.py               # Development (debug=True, auto-reload)
python prod_server.py              # Production (Waitress WSGI)
./start_dev_server.bat/sh          # Batch/shell wrapper
./start_prod_server.bat/sh         # Batch/shell wrapper
```

### Core Module Functions Quick Lookup

| Function | Module | Purpose | Example |
|----------|--------|---------|---------|
| `check_login(user, pass)` | auth.py | Verify credentials | `if check_login("alice", "secret"): ...` |
| `login_user(username)` | auth.py | Stamp session + token | Called after login succeeds |
| `is_logged_in()` | auth.py | Validate session+token+user | Use in route decorators |
| `save_chunk(file_id, num, data)` | storage.py | Store upload chunk | `/upload` calls this |
| `assemble_chunks(file_id, name, dest)` | storage.py | Merge chunks → final file | Called when all chunks done |
| `list_dir(path)` | storage.py | List directory with caching | Returns file list JSON |
| `delete_path(path)` | storage.py | Safe delete (Windows compat) | Handles read-only files |
| `check_login(user, pass)` | database.py | Verify bcrypt hash | Returns bool |
| `get_role(username)` | database.py | Retrieve user role | Returns "readwrite"/"readonly"/None |
| `get_server_token()` | database.py | Current session token | Used in session validation |
| `rotate_server_token()` | database.py | Invalidate all sessions | Called by revoke_session.py |
| `list_users()` | database.py | All users + metadata | Returns list of dicts |
| `add_user(user, pass, role)` | database.py | Create user | Immediate effect, no restart needed |

### Configuration Quick Edits

```python
# config.py adjustments (no restart needed for most):

PORT = 5000                                # Server port
CHUNK_SIZE = 10 * 1024 * 1024             # 10MB upload chunks
MAX_CONTENT_LENGTH = 16 * 1024**3         # 16GB max file
PERMANENT_SESSION_LIFETIME = 3600         # 1 hour session timeout

HLS_MIN_SIZE = 50 * 1024 * 1024           # Files >50MB get HLS
HLS_FORCE_FORMATS = {"mkv", "avi", ...}   # Always use HLS for these

IMG_COMPRESS_MIN_SIZE = 1 * 1024 * 1024   # Images >1MB get WebP
IMG_WEBP_QUALITY = 50                     # 1-100, lower=smaller

ENABLE_FFMPEG = True                      # False → raw playback
ENABLE_LIBVIPS = True                     # False → raw images
```

### Authentication Flow (5-Second Version)

```python
# 1. User submits form → POST /login
username, password = request.form.get("username"), request.form.get("password")

# 2. Check rate limiter (5 attempts/60s, then 5min lockout)
if rate_limiter.is_locked(client_ip):
    return "Too many failed attempts", 429

# 3. Verify password
if check_login(username, password):
    # 4. Stamp session with DB token
    login_user(username)  # Sets session["server_token"] = db.get_server_token()
    return redirect("/")
else:
    rate_limiter.record_failure(client_ip)
    return "Invalid credentials", 401

# 5. Every request checks is_logged_in():
#    - Session has "username" + "logged_in" flag
#    - Session["server_token"] == current DB token (catches revoke_session.py)
#    - User still exists in DB
```

### File Upload (Chunked) Quick Flow

```python
# Client (index.js):
# 1. Split file into 10MB chunks
# 2. POST each chunk with: file_id, chunk_num, chunk_data
# 3. Server stores: ROOT_DIR/.tmp_chunks/{file_id}/chunk_{num}

# Server (/upload endpoint):
storage.save_chunk(file_id, chunk_num, binary_data)
# Returns: {"chunk": N, "total_chunks": M, "progress": "N/M"}

# When all chunks done, client polls /api/assembly_status
# If complete=true:
storage.assemble_chunks(file_id, filename, dest_path)
# Merges chunks sequentially, verifies size, deletes temp dir

# File monitor detects file appears → broadcasts SSE → UI refreshes
```

### Database Schema (Users & Sessions)

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,        -- bcrypt hash (slow)
    role TEXT NOT NULL,                 -- 'readwrite' or 'readonly'
    is_active INTEGER DEFAULT 1,
    created_at INTEGER,
    last_login INTEGER
);

CREATE TABLE server_tokens (
    key TEXT UNIQUE,                    -- 'server_token' (singleton)
    value TEXT NOT NULL,                -- current token
    created_at INTEGER
);
```

### Common Path Validation

```python
# NEVER trust user paths directly — always validate:

def is_path_valid(user_path: str) -> bool:
    abs_root = os.path.abspath(ROOT_DIR)
    abs_path = os.path.abspath(os.path.join(ROOT_DIR, user_path))
    
    # 1. Prevent escaping ROOT_DIR
    if not abs_path.startswith(abs_root):
        return False
    
    # 2. Prevent absolute paths
    if os.path.isabs(user_path):
        return False
    
    return True

# ALWAYS validate before: download, delete, rename, open
```

### Index.js Global State

```javascript
const CHUNK_SIZE = parseInt(configElement.dataset.chunkSize) || 10485760;
const UPLOAD_URL = configElement.dataset.uploadUrl || "/upload";
const CURRENT_PATH = configElement.dataset.currentPath || "";
const USER_ROLE = configElement.dataset.userRole || "readonly";

let currentPath = CURRENT_PATH;
let selectedFiles = new Set();
let isUploading = false;
let uploadSessions = new Map();           // Tracks multiple uploads
let sseConnection = null;                 // SSE stream
let fileData = [];                        // Cached file list
```

### Real-Time Storage Stats (SSE)

```javascript
// Client connects to persistent stream:
const eventSource = new EventSource('/api/storage_stats_stream');

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  // data.type can be:
  // - "storage_update": file added/deleted/modified
  // - "reconcile_complete": 15-minute walk finished
  // - "walk_progress": directory reconciliation in progress
  
  updateStorageStatsUI(data);
};

// Falls back to polling if SSE unavailable:
setInterval(() => {
  fetch('/api/storage_stats_poll')
    .then(r => r.json())
    .then(data => updateUI(data));
}, 5000);
```

### File Monitor Key Settings (file_monitor.py)

```python
RECONCILE_INTERVAL = 900       # 15 minutes — silent full walk
BURST_THRESHOLD = 200          # >200 events in BURST_WINDOW triggers reconcile
BURST_WINDOW = 5.0             # seconds
SETTLE_DELAY = 0.5             # grace period after bulk operation
WALK_PROGRESS_INTERVAL = 1000  # log every N files during walk
```

### API Endpoints (All 30+)

**Auth**: `/login`, `/logout`, `/check_session`  
**Files**: `/`, `/<path>`, `/download/<path>`, `/upload`, `/bulk-download`, `/view/<path>`  
**Media**: `/office_preview/<path>`, `/archive_preview/<path>`  
**Stats**: `/api/storage_stats`, `/api/storage_stats_stream`, `/api/storage_stats_poll`, `/api/dir_info/<path>`  
**Search**: `/api/search?q=<query>&path=<dir>`  
**Admin**: `/admin/rebuild_cache`, `/admin/cleanup_chunks`, `/admin/chunk_stats`, `/admin/upload_status`  
**Util**: `/api/health_check`, `/api/monitoring_status`, `/api/assembly_status`, `/api/protect_assembly/<id>`

### Typical Debugging Steps

```bash
# 1. File not found?
python -c "from config import ROOT_DIR; print(f'ROOT_DIR={ROOT_DIR}')"
# Then check: ls -la "$ROOT_DIR/myfile.txt"

# 2. Upload failing?
# Check: GET /admin/chunk_stats (see orphaned chunks)
# Then: POST /admin/cleanup_chunks (remove old uploads)
# Or reduce: CHUNK_SIZE in config.py

# 3. Search broken?
# Clean cache: rm cache/file_index.json
# Then search again (triggers re-index)

# 4. Video black/no sound?
ffmpeg -version  # Check installed
ffmpeg -i input.mkv -f hls test.m3u8  # Test transcode

# 5. Image thumbnails slow?
vips --version  # Check libvips
# If missing → set ENABLE_LIBVIPS=False in config.py

# 6. Session expired suddenly?
# Someone ran: python revoke_session.py
# Effects: all users logged out (token rotated)
python -c "from database import db; print(db.get_server_token()[:8])"
```

### Error Response Format

```python
# All endpoints return standardized errors:
{
  "success": false,
  "error": "invalid_path",
  "message": "Path traversal detected",
  "timestamp": "2026-04-06T14:30:00.123456",
  "details": {
    "path": "../../etc/passwd",
    "reason": "Outside ROOT_DIR"
  }
}
```

### Rate Limiter (Brute-Force Protection)

```python
# In app.py RateLimiter class:
MAX_ATTEMPTS = 5        # failures before lockout
WINDOW = 60             # seconds — rolling window
LOCKOUT = 300           # seconds (5 minutes)

# Check before login: if rate_limiter.is_locked(client_ip): ...
# On failure: rate_limiter.record_failure(client_ip)
# All state is in-memory (resets on server restart)
```

### Feature Toggles Behavior

```python
# Three states for ENABLE_FFMPEG / ENABLE_LIBVIPS:

# State 1: True + tool installed → Full functionality
ENABLE_FFMPEG = True
# Result: HLS video streaming works

# State 2: True + tool NOT installed → Graceful fallback
ENABLE_FFMPEG = True
# Result: Raw video playback (no transcode), server doesn't crash

# State 3: False → Intentionally disabled
ENABLE_FFMPEG = False
# Result: Raw playback + "Requires processing" notice in UI
```

### Common Imports (When Adding Features)

```python
# Backend
from flask import Flask, request, session, jsonify, send_file, redirect
from database import db
from auth import is_logged_in, check_login, login_user
from storage import list_dir, save_chunk, assemble_chunks
from file_monitor import start_monitor, is_running
from config import ROOT_DIR, CHUNK_SIZE, ENABLE_FFMPEG
from paths import get_cache_dir, get_db_dir

# Frontend
// index.js
const CHUNK_SIZE = parseInt(configElement.dataset.chunkSize);
const USER_ROLE = configElement.dataset.userRole;
const eventSource = new EventSource('/api/storage_stats_stream');
```

---

## 🏗️ ARCHITECTURE OVERVIEW

### System Flow

```
User Browser
    ↓
Flask Application (app.py)
    ├─ Authentication Layer (auth.py)
    ├─ Database Layer (database.py)
    ├─ File Operations (storage.py, file_index.py)
    ├─ File Monitoring (file_monitor.py)
    ├─ Media Processing (real-time HLS/WebP)
    └─ Real-time Stats (realtime_stats.py)
    ↓
SQLite Database (db/cloudinator.db)
Local File Storage (configured via storage_config.json)
```

### Directory Structure

```
CloudinatorFTP/
├── app.py                      # Main Flask application + all route handlers
├── auth.py                     # Authentication helpers
├── database.py                 # SQLite persistence layer (lazy init)
├── storage.py                  # File I/O operations
├── file_index.py               # File indexing for large folder caching
├── file_monitor.py             # Real-time file system watching (watchdog)
├── realtime_stats.py           # SSE broadcasting for live storage updates
├── config.py                   # Global configuration settings
├── paths.py                    # Central path resolver (no circular deps)
├── create_user.py              # CLI tool for user management
├── debug_passwords.py          # Testing tool for authentication
├── reset_db.py                 # Database reset utility
├── revoke_session.py           # Session token rotation utility
├── setup_storage.py            # Interactive storage configuration
├── dev_server.py               # Development server starter
├── prod_server.py              # Production server starter
├── requirements.txt            # Python dependencies
├── storage_config.json         # Runtime storage path configuration
├── server_config.json          # Server settings (if used)
├── templates/                  # Jinja2 HTML templates
│   ├── login.html             # Login page
│   ├── index.html             # Main file manager UI
│   └── 404.html               # 404 error page
├── static/                     # Static assets
│   ├── css/                   # Stylesheets
│   │   ├── login.css
│   │   ├── index.css
│   │   ├── video.css
│   │   ├── 404.css
│   │   └── all.min.css        # Font Awesome icons
│   ├── js/                    # Client-side JavaScript
│   │   ├── login.js           # Login page scripts
│   │   ├── index.js           # File manager UI controller
│   │   ├── 404.js             # 404 page behavior
│   │   ├── video.js           # Video player component
│   │   ├── pdf.min.js         # PDF.js library
│   │   └── pdf.worker.min.js  # PDF.js worker thread
│   ├── webfonts/              # Font files
│   └── icons/                 # Icon assets
├── db/                        # Database + encryption keys (created at runtime)
│   ├── cloudinator.db         # SQLite database
│   ├── secret.key             # Fernet encryption key (Fernet)
│   └── session.secret         # Flask session secret
├── cache/                     # Cache directory (created at runtime)
│   ├── storage_index.json     # File count/dir info cache
│   ├── file_index.json        # Large folder search index
│   └── hls/ & img/            # HLS and WebP transcodes
├── docs/                      # Deployment guides
│   ├── WINDOWS_DEPLOYMENT.md
│   ├── LINUX_DEPLOYMENT.md
│   ├── ANDROID_DEPLOYMENT.md
│   ├── DEPLOY_APACHE.md
│   └── SETUP_TUNNEL_ADVANCED.md
├── __pycache__/               # Python bytecode (git ignored)
├── .gitignore                 # Git ignore patterns
├── LICENSE                    # Apache 2.0
└── README.md                  # User-facing documentation
```

---

## 🔑 CORE MODULES

### 1. **app.py** — Main Flask Application

**Responsibility**: Route handlers, request processing, business logic orchestration

**Key Sections**:
- **Rate Limiting** (RateLimiter class): Brute-force protection on login (max 5 attempts in 60s, 5-min lockout)
- **Session Management**: `check_session`, server token validation
- **Authentication Routes**: `/login`, `/logout`, `/check_session`
- **File Operations**: `/upload`, `/download`, `/view`, `/bulk-download`
- **Media Handling**: Office previews, archive previews, HLS streaming
- **Admin Tools**: `/admin/rebuild_cache`, `/admin/cleanup_chunks`, `/admin/chunk_stats`
- **Real-time Stats**: `/api/storage_stats`, `/api/storage_stats_stream`, `/api/storage_stats_poll`
- **Search/Indexing**: `/api/search`, `/api/dir_info/`

**Global State**:
```python
bulk_zip_progress = {}      # Tracks ZIP generation progress per session
bulk_zip_cancelled = {}     # Flags for cancelling bulk operations
```

**Key Features**:
- Chunked upload support (10MB default chunks, configurable)
- Streaming ZIP downloads for large selections
- Protection against invalid chunk assembly
- Browser history management for auth redirects
- CORS enabled for cross-origin requests

---

### 2. **database.py** — SQLite Persistence Layer

**Responsibility**: User management, authentication, session tokens, encryption key storage

**Lazy Initialization**: Module can be imported without creating files (setup_storage.py compatibility)

**Encryption Strategy**:
- **Fernet (symmetric)**: Encrypts sensitive fields (servers storing backup tokens)
- **bcrypt**: Hashes user passwords (one-way, salted)

**Key Files Created on First Use**:
- `db/cloudinator.db` — SQLite database
- `db/secret.key` — Fernet encryption key (CRITICAL: must be backed up)
- `db/session.secret` — Flask session secret

**Database Schema**:

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,         # bcrypt hash
    role TEXT NOT NULL,                  # 'readwrite' or 'readonly'
    is_active INTEGER DEFAULT 1,
    created_at INTEGER,
    last_login INTEGER
);

CREATE TABLE server_tokens (
    key TEXT UNIQUE,                     # 'server_token' (singleton)
    value TEXT NOT NULL,                 # Current token (rotated by revoke_session.py)
    created_at INTEGER
);
```

**Key Functions**:
- `check_login(username, password)` — Verify credentials against bcrypt hashes
- `get_role(username)` — Retrieve user role
- `rotate_server_token()` — Invalidate all sessions
- `get_server_token()` — Current token for session validation
- `list_users()` — All users (username, role, last login)
- `get_session_secret()` — Flask secret (lazily generated)

**Thread Safety**:
- `_write_lock` protects concurrent writes
- SQLite itself handles read consistency

---

### 3. **auth.py** — Authentication Helpers

**Responsibility**: Authentication logic, session management

**Key Functions**:
```python
check_login(username, password)  # DB call → bcrypt verify
get_role(username)                # DB call → user role or None
login_user(username)              # Set session + server token from DB
logout_user()                     # Clear session
current_user()                    # Get username from session
is_logged_in()                    # Validate session + token + user exists
```

**Session Validation Logic**:
```
is_logged_in() returns True only if:
  1. Session has 'logged_in' flag AND 'username'
  2. Session's 'server_token' matches current DB token
  3. User still exists in DB (deletion invalidates immediately)
```

**Design Pattern**: Thin wrapper around `database.db` calls — all logic lives in database.py

---

### 4. **storage.py** — File I/O Operations

**Responsibility**: Safe file operations, chunked uploads, directory management

**Key Functions**:
- `list_dir(path)` — List directory with caching for large folders
- `count_directory_items(path)` — Get file/dir counts
- `save_chunk(file_id, chunk_num, chunk_data)` — Store upload chunk
- `verify_chunks_complete(file_id)` — Check all chunks received
- `assemble_chunks(file_id, filename, dest_path)` — Merge chunks into final file
- `cleanup_chunks(file_id)` — Remove chunk temp files
- `create_folder(path, foldername)` — Create directory safely
- `delete_path(path)` — Safe delete with Windows read-only handling
- `get_file_size(path)` — Single file size
- `get_directory_size(path)` — Recursive folder size

**Windows Compatibility**:
```python
def windows_remove_readonly(func, path, _):
    # Handle Windows read-only file deletion
    os.chmod(path, stat.S_IWRITE)
    func(path)
```

**Chunking Strategy**:
```
Upload → /upload endpoint receives chunks
         Each chunk: file_id + chunk_num + binary data
         Stored in temp directory (hash-based file_id naming)
         
Assembly → /verify checks all N chunks present
           /assemble merges sequentially into final file
           cleanup_chunks removes temp dir
```

**File Index Caching** (large folders):
- Uses `file_index_manager` from `file_index.py`
- Cache hits avoid re-listing massive directories
- Auto-invalidates on file changes

---

### 5. **file_monitor.py** — Real-time File System Watching

**Responsibility**: Track storage changes, cache invalidation, SSE updates

**Architecture**:
```
First Boot:      Full recursive walk → builds file counters + dir_info index
                 → saves to cache/storage_index.json

On File Event:   Watchdog event handler → update counters + dir_info
                 → announce via SSE to clients

Reconciliation:  Every 15 minutes (RECONCILE_INTERVAL=900s)
                 Silent full walk corrects counter drift
```

**Data Structures**:
```python
@dataclass
class DirInfo:
    path: str                    # Relative path
    file_count: int             # Files in this dir only
    dir_count: int              # Subdirs in this dir only
    total_size: int             # Total size (recursive)
    mod_time: float             # Last modification time
```

**Key State**:
```python
CACHE_FILE = os.path.join(cache_dir, "storage_index.json")
RECONCILE_INTERVAL = 900         # 15 minutes
BURST_THRESHOLD = 200            # Events triggering full walk
BURST_WINDOW = 5.0               # Seconds to watch for burst
```

**Watchdog Events**:
- `on_created` — File/folder added
- `on_deleted` — File/folder removed
- `on_modified` — File changed
- `on_moved` — File renamed/moved

**Burst Detection**:
- If >200 events in 5 seconds → likely bulk copy → trigger full reconcile walk
- Otherwise → incremental counter updates

---

### 6. **config.py** — Global Configuration

**Responsibility**: Server settings, feature toggles, path management

**Key Settings**:
```python
# Server
PORT = 5000
HOST = "0.0.0.0"
MAX_CONTENT_LENGTH = 16 * 1024 * 1024 * 1024  # 16GB max file
CHUNK_SIZE = 10 * 1024 * 1024                  # 10MB chunking
PERMANENT_SESSION_LIFETIME = 3600              # 1 hour timeout

# Streaming
HLS_MIN_SIZE = 50 * 1024 * 1024               # 50MB threshold for HLS
HLS_FORCE_FORMATS = {"mkv", "avi", "wmv", ...}

# Image Processing
IMG_COMPRESS_MIN_SIZE = 1 * 1024 * 1024       # 1MB threshold
IMG_WEBP_QUALITY = 50                          # Lossy WebP quality

# Feature Toggles
ENABLE_FFMPEG = True    # False → raw playback only
ENABLE_LIBVIPS = True   # False → raw image serving only

# Paths (lazy-loaded from paths.py)
ROOT_DIR = get_root_dir()      # File storage location
DB_PATH = get_db_dir()         # SQLite location
CACHE_PATH = get_cache_dir()   # HLS/WebP/indexes
```

**Feature Toggle Behavior**:
- `True + tool installed` → Full functionality (HLS/WebP)
- `True + tool NOT installed` → Graceful fallback (raw playback/images)
- `False` → Intentionally disabled, no fallback, "requires processing" notice shown

---

### 7. **paths.py** — Central Path Resolver

**Responsibility**: Centralized path management to prevent circular imports

**Design Principle**: No dependencies on other project modules (safe to import by database.py)

**Key Functions**:
```python
get_db_dir(create=True)        # DB directory (default: ./db)
get_cache_dir(create=True)     # Cache directory (default: ./cache)
get_hls_cache_dir(create=True) # HLS transcodes (default: ./cache/hls)
get_img_cache_dir(create=True) # WebP conversions (default: ./cache/img)

set_db_dir(path)               # Validate + persist new DB location
set_cache_dir(path)            # Validate + persist new cache location
ensure_dirs()                  # Create all directories (called by app.py)
```

**Configuration Source**:
- Reads from `storage_config.json` at project root
- Merges updates safely (no key overwrites on write)
- Production recommendation: Store `db_path` and `cache_path` outside web root

**Example storage_config.json**:
```json
{
  "storage_path": "C:\\Server\\SharedFolder",
  "db_path": "C:\\Server\\config\\db",
  "cache_path": "C:\\Server\\config\\cache",
  "hls_cache_path": "C:\\Server\\config\\cache\\hls",
  "img_cache_path": "C:\\Server\\config\\cache\\img"
}
```

---

### 8. **realtime_stats.py** — Real-time Storage Stats Broadcasting

**Responsibility**: Server-Sent Events (SSE) for live storage updates

**Architecture**:
```
Storage Event → file_monitor detects change
              → calls trigger_storage_update()
              → event_manager broadcasts to all connected clients
              → clients update UI in real-time
```

**Key Class**: `StorageStatsEventManager`
```python
add_client(client_queue)           # Register new SSE connection
remove_client(client_queue)        # Deregister disconnected client
broadcast_update(old, new, ...)    # Push update to all clients
get_last_stats()                   # Return most recent snapshot
get_client_count()                 # Active SSE connections
```

**SSE Endpoint**: `/api/storage_stats_stream`

**Broadcast Payload**:
```json
{
  "type": "storage_update",
  "old_snapshot": { "file_count": ..., "size": ... },
  "new_snapshot": { "file_count": ..., "size": ... },
  "reconcile_complete": false,
  "walk_progress": false
}
```

---

### 9. **file_index.py** — File Indexing for Large Folders

**Responsibility**: Rapid search and large folder caching

**Key Purpose**: Instant listing of massive directories (1000+ files)

**Functionality**:
- Full-text search across file names
- Cache serialization for instant loads
- Lazy indexing on demand

---

### 10. **create_user.py** — User Management CLI

**Responsibility**: Add/delete/modify users, manage roles

**Usage**:
```bash
python create_user.py
```

**Menu Options**:
1. List users
2. Add user (prompt for username, password, role)
3. Change password
4. Change role (readwrite ↔ readonly)
5. Delete user

**Features**:
- Hidden password input (getpass)
- Warns when using default credentials (admin/admin123, guest/guest123)
- Immediate effect (no server restart needed)

---

### 11. **database.py** Utilities

**reset_db.py**:
```bash
python reset_db.py  # DESTRUCTIVE: Wipes DB, recreates with defaults
```
Default users: admin/admin123 (readwrite), guest/guest123 (readonly)

**revoke_session.py**:
```bash
python revoke_session.py  # Rotates server token → logs out all clients
```

**debug_passwords.py**:
```bash
python debug_passwords.py  # Test password verification
```

---

## 🔐 AUTHENTICATION FLOW

### Login Process

1. User submits form on `/login`
2. `RateLimiter.check()` validates IP not locked out
3. `auth.check_login(username, password)` → `database.db.check_login()`
4. `database.db.check_login()`:
   - Queries user from DB
   - Compares password against bcrypt hash
   - Returns True/False
5. On success: `auth.login_user(username)`
   - Clears old session data
   - Sets session["username"], session["role"]
   - Sets session["server_token"] from DB
   - Sets session["logged_in"] = True
   - Updates user's last_login timestamp
6. Redirects to `/` (file manager)

### Session Validation

On every request:
1. Check `is_logged_in()` from auth.py
2. Validates:
   - Session has "username" and "logged_in" flag
   - Session's "server_token" matches current DB token
   - User still exists in DB
3. If any check fails → redirect to `/login`

### Logout

1. User clicks logout button
2. Hits `/logout` endpoint
3. `auth.logout_user()` clears session
4. Redirects to `/login?logged_out`

### Session Revocation

Admins can revoke all sessions:
```bash
python revoke_session.py
```
This rotates the DB server token. All existing sessions fail validation on next poll.

---

## 📤 FILE UPLOAD FLOW

### Chunked Upload Process

1. **Client initiates upload** (`index.js`):
   - Splits large file into 10MB chunks
   - Generates random file_id (UUID)
   - Submits each chunk with: `file_id`, `chunk_num`, `chunk_data`

2. **Server receives chunk** (`/upload` endpoint):
   - Validates authentication + permissions
   - Calls `storage.save_chunk(file_id, chunk_num, chunk_data)`
   - Returns progress JSON: `{ "chunk": N, "total": M, "status": "... }`

3. **Chunk Storage**:
   - Temp directory: `ROOT_DIR/.tmp_chunks/[file_id]/`
   - Individual files: `chunk_0`, `chunk_1`, etc.

4. **Client completes upload**:
   - Polls `/api/assembly_status` to verify all chunks received
   - On completion, calls `/assemble` (internal, not exposed directly)

5. **Server assembles file**:
   - `storage.verify_chunks_complete(file_id)` checks all chunks exist
   - `storage.assemble_chunks(file_id, filename, dest_path)`:
     - Opens each chunk sequentially
     - Writes to final destination file
     - Verifies total size matches
   - `storage.cleanup_chunks(file_id)` removes temp directory

6. **File appears in UI**:
   - File monitor's watchdog detects new file
   - Broadcasts SSE update to all connected clients
   - Clients refresh file listing

### Resumable Uploads

- Each chunk stores to named file (`chunk_0`, `chunk_1`, etc.)
- If client disconnects then reconnects:
  - Queries `/api/assembly_status` to see which chunks already uploaded
  - Resumes from next missing chunk
  - No re-upload of existing chunks

---

## 📥 FILE DOWNLOAD FLOW

### Single File Downloads

1. User clicks download button on file
2. Client navigates to `/download/<path>`
3. Flask endpoint:
   - Validates path (security: ensure within ROOT_DIR)
   - Calls `send_file(path)` — streaming download
   - Browser receives as attachment

### Bulk ZIP Downloads

1. User selects multiple files/folders
2. Clicks "Download as ZIP"
3. POSTs to `/bulk-download` with file list
4. Server endpoint:
   - Validates each path (readonly users get read-only archive, readwrite get all)
   - Creates streaming ZIP on-the-fly (no temp file)
   - Uses `zipstream.ZipStream` for instant response
   - Streams ZIP to client as generation happens
5. Client browser downloads as `backup.zip`

### Protected Assembly Files

- Large ZIP assemblies can be "protected" via `/api/protect_assembly/<file_id>`
- Prevents accidental cleanup of in-progress downloads
- Auto-cleanup on download completion or 24-hour timeout

---

## 🎬 MEDIA PREVIEW FLOW

### Video Streaming (HLS)

**Trigger**:
- Video file size > HLS_MIN_SIZE (50MB) OR
- File format in HLS_FORCE_FORMATS (mkv, avi, wmv, flv, etc.)

**Process**:
1. User clicks video preview
2. Client requests `/view/<video_path>`
3. Server checks cache: `cache/hls/<video_hash>.m3u8`
4. If not cached:
   - Spawns FFmpeg subprocess to transcode to HLS
   - Generates `.m3u8` playlist + `.ts` segments
   - Caches in `cache/hls/`
5. Client loads `.m3u8` into Video.js player
6. Player streams `.ts` segments on demand

**Configuration**:
- ENABLE_FFMPEG = True → transcode
- ENABLE_FFMPEG = False → raw playback (fallback)

### Image Preview & WebP Conversion

**Trigger**:
- Image file size > IMG_COMPRESS_MIN_SIZE (1MB)

**Process**:
1. User requests image preview
2. Server checks cache: `cache/img/<image_hash>.webp`
3. If not cached:
   - Spawns libvips subprocess
   - Converts to lossy WebP at IMG_WEBP_QUALITY (50)
   - Caches in `cache/img/`
4. Client loads WebP (smaller bandwidth)

**Fallback**:
- ENABLE_LIBVIPS = False → serve raw image
- Warns user: "Image compression not available"

### Office Document Preview

- Requests `/office_preview/<doc_path>`
- Uses `mammoth` (DOCX), `openpyxl` (XLSX), `python-pptx` (PPTX)
- Converts to HTML → embedded in iframe
- No caching (documents may change)

### Archive Preview

- `/archive_preview/<archive_path>`
- Lists contents (ZIP, RAR, 7Z)
- Uses `zipfile`, `rarfile`, `py7zr`
- JSON response: `{ "files": [...], "total_size": ... }`

---

## 🔍 SEARCH & INDEXING

### Real-time Search

**Endpoint**: `/api/search?q=<query>&path=<dir>`

**Process**:
1. Validates user has read access to path
2. Gets `file_index_manager` (lazy)
3. Searches file names matching query (substring/regex)
4. Returns matching files with metadata

### Directory Info Caching

**Endpoint**: `/api/dir_info/<path>`

**Response**:
```json
{
  "path": "photos",
  "file_count": 42,
  "dir_count": 3,
  "total_size": 1073741824,
  "mod_time": 1712425600.0
}
```

**Cache Invalidation**:
- File monitor updates on any change
- SSE broadcasts updates to clients
- Clients cache in-memory (short-lived)

---

## 🎨 FRONTEND ARCHITECTURE

### Templates

#### **login.html**
- Login form (username + password + remember me)
- Flash message display (errors)
- Browser history management (prevent back-to-login after login)
- Lockout timer countdown display

#### **index.html**
- File manager UI (responsive)
- Breadcrumb navigation
- File/folder listing (table)
- Upload area (drag-drop + button)
- Bulk actions (select multiple, download as ZIP)
- Search bar
- Real-time storage stats (SSE updates)
- Mobile/tablet/desktop responsive layout

#### **404.html**
- Custom 404 error page
- Auto-redirect to home (10 seconds)
- Manual return buttons

### CSS

#### **login.css**
- Animated background (floating particles)
- Login card animation (slide-in)
- Form controls with icons
- Button hover/active states
- Loading animation
- Mobile responsiveness

#### **index.css**
- Header with user badge + logout button
- Table column widths (responsive breakpoints)
  - Mobile (<600px): checkbox, name, size, actions
  - Tablet (600-899px): + type column
  - Desktop (≥900px): all columns + modified time
- Breadcrumb styling
- Bulk action bar
- Create folder input
- Responsive grid layout
- Icon theming (Font Awesome)

#### **video.css**
- Video player styling (Video.js)
- Media button states (play, pause, fullscreen, captions)
- Custom controls layout

#### **all.min.css**
- Font Awesome 7.2.0 icon library
- Icon size utilities (1x-10x, 2xs-2xl)
- Icon animations (bounce, beat, fade)
- Responsive icon behavior

### JavaScript

#### **login.js**
- Form submission handling
- Password strength validation (optional)
- Lockout timer countdown
- Auto-redirect if already logged in
- Browser history cleanup (logged_out parameter)
- Session storage for tracking logout state

#### **index.js** (Main Controller)
- **Configuration**: Reads from HTML data attributes (Flask → JS)
  - `CHUNK_SIZE` (10MB default)
  - `UPLOAD_URL` ("/upload")
  - `CURRENT_PATH` (current directory)
  - `USER_ROLE` ("readwrite" or "readonly")

- **Upload Handling**:
  - Drag-drop file acceptance
  - Chunked upload with progress tracking
  - Resumable uploads on disconnect
  - Multiple file uploads
  - Error handling + retry logic

- **File Listing**:
  - Table rendering (file icon, name, size, type, modified time, actions)
  - Lazy loading for large folders
  - Search filtering
  - Breadcrumb navigation

- **Bulk Actions**:
  - Multi-select with checkbox
  - Download selected as ZIP
  - Delete selected (admin only)
  - Rename files (admin only)

- **Real-time Updates**:
  - SSE listener for storage stats
  - Live file count/size updates
  - Progress during file monitor reconciliation

- **Responsive Table Columns**:
  - `smartTableColumnizer()` ResizeObserver
  - Dynamic column hiding on mobile
  - Width cmath adjustments for scroll

- **Event Delegation Protection**:
  - Modal inputs protected from event bubbling
  - Prevents accidental file operations during form entry

#### **video.js**
- HTML5 Video element web component
- Playback controls (play, pause, seek, volume, fullscreen)
- Caption/subtitle support
- Responsive player sizing
- Keyboard shortcuts

#### **404.js**
- Auto-redirect to home (10 seconds)
- Cancel redirect on user interaction (click/keyboard)

---

## 🛣️ API ENDPOINTS

### Authentication
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/login` | GET, POST | Login form + submission |
| `/logout` | GET | Clear session, redirect to login |
| `/check_session` | POST | Validate current session (returns user info) |

### File Operations
| Endpoint | Method | Purpose | Auth | Role |
|----------|--------|---------|------|----|
| `/` | GET | Browse root directory | ✓ | Any |
| `/<path:path>` | GET | Browse file/folder | ✓ | Any |
| `/download/<path>` | GET | Download single file | ✓ | Any |
| `/bulk-download` | POST | Download multiple items as ZIP | ✓ | Any |
| `/upload` | POST | Upload file (chunked) | ✓ | readwrite |
| `/view/<path>` | GET | Preview file (media, docs, archives) | ✓ | Any |

### Media Processing
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/office_preview/<path>` | GET | DOCX/XLSX/PPTX preview (HTML) |
| `/archive_preview/<path>` | GET | List archive contents (JSON) |

### Real-time Storage Stats
| Endpoint | Method | Response | Purpose |
|----------|--------|----------|---------|
| `/api/storage_stats` | GET | JSON | Current stats (fast) |
| `/api/storage_stats_stream` | GET | SSE | Live updates on file changes |
| `/api/storage_stats_poll` | GET | JSON | Stats snapshot for polling |
| `/api/storage_stats_slow` | GET | JSON | Full recursive walk (slow) |
| `/api/storage_stats_debug` | GET | JSON | Debug info |
| `/api/disk_stats_fast` | GET | JSON | Disk usage (system-level) |

### Search & Indexing
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/search` | GET | Full-text search across files |
| `/api/dir_info/` | GET | Directory metadata (cache) |
| `/api/dir_info/<path>` | GET | Directory metadata (cache) |

### Admin Tools
| Endpoint | Method | Purpose | Role |
|----------|--------|---------|------|
| `/admin/rebuild_cache` | POST | Rebuild storage_index.json | readwrite |
| `/admin/cleanup_chunks` | POST | Remove orphaned upload chunks | readwrite |
| `/admin/chunk_stats` | GET | Upload chunk statistics | readwrite |
| `/admin/upload_status` | GET | Current uploads in progress | readwrite |

### Upload Management
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/cleanup_chunks` | POST | Manual chunk cleanup |
| `/cancel_upload` | POST | Cancel ongoing upload |
| `/cancel_bulk_zip` | POST | Cancel ZIP generation |
| `/api/assembly_status` | GET | Check if all chunks received |
| `/api/protect_assembly/<file_id>` | POST | Prevent cleanup during download |

### Health & Monitoring
| Endpoint | Method | Response |
|----------|--------|----------|
| `/api/health_check` | GET | `{ "status": "ok" }` |
| `/api/monitoring_status` | GET | File monitor status + reconciliation info |

---

## 🔧 CONFIGURATION SYSTEM

### Three Independent Path Systems

**1. File Storage (config.py)**
- `ROOT_DIR` — Where user uploads go
- Set via `setup_storage.py` interactive menu
- Stored in `storage_config.json["storage_path"]`
- Default: `.` (project root)

**2. Database (paths.py)**
- `db_path` — SQLite + encryption keys + session secret
- Set via `setup_storage.py` interactive menu
- Stored in `storage_config.json["db_path"]`
- Default: `./db`

**3. Cache (paths.py)**
- `cache_path` — storage_index.json, file_index.json
- `hls_cache_path` — HLS transcodes
- `img_cache_path` — WebP conversions
- Set via `setup_storage.py` interactive menu
- Defaults: `./cache`, `./cache/hls`, `./cache/img`

### Feature Toggles (config.py)

```python
ENABLE_FFMPEG = True    # Toggle HLS transcoding
ENABLE_LIBVIPS = True   # Toggle WebP conversion
```

- When disabled: Graceful fallback without error
- When enabled but tool not installed: Still fallback (no crash)
- Tools checked at runtime (on first use)

### Server Settings (config.py)

```python
PORT = 5000
MAX_CONTENT_LENGTH = 16GB
CHUNK_SIZE = 10MB
PERMANENT_SESSION_LIFETIME = 3600 seconds
HLS_MIN_SIZE = 50MB
IMG_COMPRESS_MIN_SIZE = 1MB
IMG_WEBP_QUALITY = 50
```

---

## 🚀 DEPLOYMENT OPTIONS

### 1. Development Server

```bash
python dev_server.py  # or start_dev_server.bat / start_dev_server.sh
```

- Flask debug mode enabled
- Auto-reload on file changes
- Threaded (supports concurrent requests)
- Suitable for testing/development only

### 2. Production Server (Waitress)

```bash
python prod_server.py  # or start_prod_server.bat / start_prod_server.sh
```

- Waitress WSGI server
- Debug mode disabled
- Multi-threaded (production safe)
- Configurable via `flask.app.config`

### 3. Apache + mod_wsgi (Production)

See **[DEPLOY_APACHE.md](./docs/DEPLOY_APACHE.md)**

- Apache HTTP Server (Windows XAMPP)
- mod_wsgi module bridges Apache to Python
- SSL certificates (HTTPS)
- Performance tuning (worker processes, thread pools)

### 4. Systemd Service (Linux)

See **[LINUX_DEPLOYMENT.md](./docs/LINUX_DEPLOYMENT.md)**

- Auto-start on boot
- Supervised through systemd
- Logging via journalctl
- Graceful restart/stop

### 5. Cloudflare Tunnel (Internet Exposure)

See **[SETUP_TUNNEL_ADVANCED.md](./docs/SETUP_TUNNEL_ADVANCED.md)**

- Expose localhost:5000 to internet
- Custom domain support
- SSL/TLS encryption
- No port forwarding needed
- Secure by default

### 6. Android (Termux)

See **[ANDROID_DEPLOYMENT.md](./docs/ANDROID_DEPLOYMENT.md)**

- Install on Android device via Termux
- FFmpeg + libvips compilation from source
- PyPPMd patches (Android-specific)
- Background process management

---

## 🔐 SECURITY MODEL

### Authentication & Authorization

- **Users**: Stored in SQLite with bcrypt-hashed passwords
- **Roles**:
  - `readwrite` — View, upload, delete, rename, create folders
  - `readonly` — View and download only
- **Session Tokens**:
  - Server-side token stored in DB
  - Client receives token in session cookie
  - Token rotates via `revoke_session.py` → logs out all users
  - Token validated on every incoming request

### Encryption

- **Fields**: Fernet (symmetric) encrypts sensitive DB fields on INSERT/UPDATE
- **Passwords**: bcrypt (one-way hash) with salt
- **Session Secret**: Generated once, stored in `db/session.secret`
- **Encryption Key**: Stored in `db/secret.key` — MUST be backed up separately

### Path Security

- All file paths validated against `ROOT_DIR`
- Uses `secure_filename()` for uploads
- Prevents directory traversal (`../` attacks)
- Read-only users cannot access delete/rename/upload endpoints

### Rate Limiting

- **Brute-force Protection**: Max 5 failed logins per IP in 60 seconds
- **Lockout Duration**: 5 minutes (300 seconds)
- **In-Memory**: Resets on server restart (intentional)

### CORS

- CORS enabled for cross-origin requests
- Configurable via Flask-CORS in app.py

---

## 🎯 KEY DESIGN PATTERNS

### 1. Lazy Initialization

**Pattern**: Large I/O operations delayed until first use

**Examples**:
- Database schema created on first `_connect()` call
- Encryption key generated on first `_encrypt()` call
- Directories created only when `ensure_dirs()` called (not on import)

**Benefit**: `database.py` can be imported by `config.py` without creating files

### 2. Circular Import Prevention

**Pattern**: `paths.py` has zero dependencies on other project modules

**Reason**: `config.py` imports `paths.py`, and `database.py` imports `paths.py`
Without this, circular import would occur

### 3. Merge-Safe Configuration

**Pattern**: `storage_config.json` updates are merged, not replaced

```python
def _save(updates: dict):
    data = _load()           # Existing keys preserved
    data.update(updates)     # Merge new values
    # Write back to file
```

**Reason**: Multiple paths (storage, db, cache) configured independently

### 4. Thread-Safe Database

**Pattern**: Write operations protected by `_write_lock`

```python
with _write_lock:
    conn.execute(...)
    conn.commit()
```

**Reason**: Prevent concurrent writes to SQLite from corrupting data

### 5. Session Token Validation

**Pattern**: Every request checks `server_token` matches current DB token

**Reason**: Allows instant session revocation via `revoke_session.py`

### 6. File Monitor with Burst Detection

**Pattern**: Incremental updates normally, but full reconcile on bulk operations

**Trigger**: >200 file events in 5 seconds

**Reason**: Prevents counter drift during large copies/batch operations

### 7. Server-Sent Events (SSE)

**Pattern**: Real-time storage updates pushed to connected clients

**Clients**: Browser maintains persistent HTTP connection
**Server**: Broadcasts updates to all connected clients
**Fallback**: Polling available via `/api/storage_stats_poll`

### 8. Streaming ZIP Downloads

**Pattern**: ZIP generated on-the-fly, no temp file

**Tool**: `zipstream.ZipStream`

**Reason**: Large selections (GBs) don't require server disk space

### 9. Chunked Uploads with Resumable Support

**Pattern**: Each chunk stored with unique ID, can resume from last received

**Reason**: Large files (16GB) can handle network interruptions

### 10. Graceful Degradation

**Pattern**: Missing external tools (FFmpeg, libvips) don't crash server

**Behavior**:
- `ENABLE_FFMPEG = True` but FFmpeg not found → raw playback
- `ENABLE_LIBVIPS = True` but libvips not found → raw images
- UI shows "Requires processing" status for unsupported formats

---

## 📊 DATA STRUCTURES

### Session Schema (Flask)

```python
session = {
    "username": "alice",
    "role": "readwrite",  # or "readonly"
    "logged_in": True,
    "server_token": "abc123def456...",  # from DB
}
```

### Storage Index (storage_index.json)

```json
{
  "metadata": {
    "version": 2,
    "created_at": 1712425600.0,
    "completed": true
  },
  "counters": {
    "file_count": 1042,
    "dir_count": 87,
    "total_size": 1099511627776
  },
  "dir_info": {
    "": {            # Root
      "file_count": 42,
      "dir_count": 3,
      "total_size": 1099511627776,
      "mod_time": 1712425600.0
    },
    "photos": {
      "file_count": 200,
      "dir_count": 5,
      "total_size": 549755813888,
      "mod_time": 1712425600.0
    }
  }
}
```

### File Upload Metadata

```python
bulk_zip_progress = {
    "session_id": {
        "status": "zipping",
        "current": 50,
        "total": 150,
        "bytes_done": 1073741824,
        "bytes_total": 2147483648,
        "error": None
    }
}
```

---

## 🧪 TESTING & DEBUGGING

### Test Tooling

**debug_passwords.py**:
```bash
python debug_passwords.py
# Menu:
# 1. Test all default passwords
# 2. Test custom credentials
# 3. Show all users
# 4. Reset to defaults
```

**reset_db.py**:
```bash
python reset_db.py
# DESTRUCTIVE: Wipes DB, recreates with defaults
```

**create_user.py**:
```bash
python create_user.py
# Interactive CLI for user management
```

**revoke_session.py**:
```bash
python revoke_session.py
# Rotates server token → logs out all sessions
```

### Logging

- Console output via `print()` (line-buffered)
- Flask debug logging available when `DEBUG=True`
- File monitor logs reconciliation progress (every N files)

### Debugging Endpoints

**Admin Stats**:
- `/admin/chunk_stats` — Upload chunk statistics
- `/admin/upload_status` — Current uploads
- `/api/storage_stats_debug` — Debug storage info
- `/api/monitoring_status` — File monitor status

---

## 📚 DEPENDENCIES

### Core Framework
- **Flask 3.1.3** — Web framework
- **flask-cors 6.0.2** — CORS support
- **Werkzeug 3.1.6** — WSGI utilities
- **waitress 3.0.2** — Production WSGI server

### Authentication & Security
- **bcrypt 5.0.0** — Password hashing
- **cryptography 46.0.5** — Fernet encryption
- **pyzipper 0.3.6** — Encrypted ZIP support

### File Operations
- **zipstream-new 1.1.8** — Streaming ZIP generation
- **rarfile 4.2** — RAR archive reading
- **py7zr 1.1.0** — 7Z archive support
- **zipfile** (stdlib) — ZIP reading/writing

### Document Processing
- **mammoth 1.12.0** — DOCX (Word) conversion
- **openpyxl 3.1.2** — XLSX (Excel) reading
- **python-pptx 1.0.2** — PPTX (PowerPoint) reading

### Media Processing
- **pyvips 3.1.1** — Image conversion via libvips
- FFmpeg (external) — Video transcoding

### File Monitoring
- **watchdog 6.0.0** — File system event watching

### System Utilities
- Python 3.10+ stdlib: `os`, `json`, `sqlite3`, `threading`, `uuid`, `hashlib`, `subprocess`

---

## 🔄 REQUEST/RESPONSE FLOW EXAMPLES

### Example: File Upload

```
1. POST /upload
   Headers: (multipart/form-data)
   Body:
     file_id: "abc123-def456"
     chunk_num: "0"
     chunk_data: <binary> (10MB)

2. Server:
   - Validates auth + readwrite role
   - Calls storage.save_chunk()
   - Returns JSON

   Response:
   {
     "status": "chunk_saved",
     "chunk": 0,
     "total_chunks": 5,
     "progress": "0/5"
   }

3. File monitor (watchdog):
   - (no event yet, temp file)

4. On completion (all chunks received):
   - storage.assemble_chunks() merges chunks
   - Temp directory deleted
   - File appears in final location

5. File monitor (watchdog):
   - Detects on_created event for final file
   - Updates counters + dir_info
   - Broadcasts SSE update

6. Browser:
   - Receives SSE notification
   - Refreshes file listing
   - New file visible in UI
```

### Example: Session Revocation

```
1. Admin runs: python revoke_session.py

2. Script:
   - Connects to database.py
   - Calls db.rotate_server_token()
   - Generates new token
   - Writes to DB

3. Active Session:
   - Browser has old token in cookie
   - Polls /api/storage_stats_poll
   - Server compares session["server_token"] vs DB token
   - Mismatch → returns 401 Unauthorized

4. Client (index.js):
   - Receives 401 response
   - Redirects to /login
   - User sees "Session expired" message
```

### Example: Search

```
1. GET /api/search?q=photos&path=documents

2. Server:
   - Validates path within ROOT_DIR
   - Gets file_index_manager
   - Searches "documents/" for files matching "photos"
   - Returns JSON

   Response:
   {
     "query": "photos",
     "path": "documents",
     "results": [
       {
         "name": "photos_2024.zip",
         "path": "documents/photos_2024.zip",
         "size": 1073741824,
         "is_dir": false,
         "modified": 1712425600.0
       },
       {
         "name": "vacation_photos",
         "path": "documents/vacation_photos",
         "size": 0,
         "is_dir": true,
         "modified": 1712425600.0
       }
     ]
   }

3. Client (index.js):
   - Receives results
   - Highlights matching files
   - Updates UI
```

---

## 🎓 COMMON TASKS & PATTERNS

### Add a New User Programmatically

```python
from database import db

db.add_user("newuser", "password123", "readonly")
# Immediately usable for login — no restart required
```

### Check User Exists

```python
from database import db

exists = db.get_role("username") is not None
```

### Rotate Session Token (Logging Out Everyone)

```bash
python revoke_session.py
```

### Rebuild Storage Cache

```
POST /admin/rebuild_cache
# Server performs full directory walk
# Rebuilds storage_index.json
# Restarts file monitor
```

### Enable/Disable FFmpeg

In `config.py`:
```python
ENABLE_FFMPEG = False  # True = HLS, False = raw playback
```

### Check if File Monitor Is Running

```
GET /api/monitoring_status

Response:
{
  "is_running": true,
  "last_reconcile": 1712425600.0,
  "pending_events": 0,
  "client_count": 3
}
```

### Retrieve Upload Statistics

```
GET /admin/chunk_stats

Response:
{
  "total_chunks": 42,
  "total_size_mb": 420,
  "file_ids": ["abc123...", "def456..."],
  "orphaned_count": 2
}
```

---

## 📝 NOTES FOR FUTURE CHANGES

### When Modifying Database Schema

1. The schema is created in `database.py` via `_bootstrap()`
2. Existing DBs are NOT migrated (backward compatibility not implemented)
3. Changes require `reset_db.py` — destructive, users lose accounts
4. Consider: Future need for migration logic if schema becomes unstable

### When Adding New Routes

1. Check authentication: `@require_login` decorator needed
2. Check authorization: `get_role()` for readwrite-only endpoints
3. Add to endpoint list above (for documentation)
4. CORS may need updating if cross-origin requests added

### When Modifying File Monitor

1. Test with large directories (1000+ files)
2. Watch for SSE broadcast storms (too frequent updates)
3. Burst detection thresholds may need tuning
4. Reconciliation interval (15 min) is production default

### When Adding Media Support

1. Add to `HLS_FORCE_FORMATS` if browser can't play raw format
2. Test external tool fallback (disabled feature toggle)
3. Add cache directory logic in `config.py` / `paths.py`
4. Update UI to show "Requires processing" notice

### When Scaling to 100,000+ Files

1. File monitor bursting will trigger full walks frequently
2. Consider incremental indexing in `file_index.py`
3. SSE updates may cause UI lag — throttle broadcasts
4. Large directory sizes will slow listing — increase file index caching

---

## ✅ CHECKLIST FOR NEW DEVELOPERS

When joining the project:

- [ ] Read this CLAUDE.md entirely
- [ ] Run `python setup_storage.py` to configure storage paths
- [ ] Run `python create_user.py` to create a test account
- [ ] Run `python dev_server.py` and test login/file operations
- [ ] Review `app.py` endpoints and understand routing
- [ ] Understand the three path systems (storage, db, cache)
- [ ] Understand the authentication/authorization model
- [ ] Test file upload/download with known file sizes
- [ ] Study `file_monitor.py` reconciliation logic
- [ ] Review `database.py` schema and lazy initialization
- [ ] Understand chunked upload flow in `storage.py`
- [ ] Test media preview (video, image, office, archive)
- [ ] Review deployment guides for your platform
- [ ] Understand SSE broadcasting in `realtime_stats.py`
- [ ] Test bulk ZIP download with large selection
- [ ] Review security model (rate limiting, encryption, CORS)

---

---

## 🔌 DETAILED ENDPOINT SPECIFICATIONS

### Authentication Endpoints

#### **POST /login**

**Purpose**: Authenticate user with username/password

**Request**:
```http
POST /login HTTP/1.1
Content-Type: application/x-www-form-urlencoded

username=alice&password=secret123
```

**Response (Success - 302 Redirect)**:
```http
HTTP/1.1 302 Found
Set-Cookie: session=<encrypted_token>; Path=/; HttpOnly
Location: /

# Browser follows redirect to /
```

**Response (Failure - 200 OK)**:
```html
<!-- Re-renders login.html with flash message -->
<div class="flash-messages">
  <div class="flash-message error">Invalid username or password</div>
</div>
```

**Rate Limiting**:
- Max 5 failures per IP in 60 seconds
- After 5th failure: 300 second (5 minute) lockout
- Response includes countdown timer for UI

**Code Path**:
```python
# app.py @ /login route
if request.method == "POST":
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    
    # Check rate limiter
    if rate_limiter.is_locked(client_ip):
        seconds_left = rate_limiter.seconds_until_unlock(client_ip)
        flash(f"Too many failed attempts. Try again in {seconds_left}s", "error")
        return render_template("login.html"), 429
    
    # Verify credentials
    if check_login(username, password):
        login_user(username)
        return redirect(url_for("browse_dir"))
    else:
        rate_limiter.record_failure(client_ip)
        flash("Invalid username or password", "error")
```

---

#### **GET /logout**

**Purpose**: Clear session and redirect to login

**Request**:
```http
GET /logout HTTP/1.1
Cookie: session=<encrypted_token>
```

**Response**:
```http
HTTP/1.1 302 Found
Set-Cookie: session=; Max-Age=0
Location: /login?logged_out=1
```

**Browser Behavior**:
- Clears session cookie
- Navigates to `/login?logged_out=1`
- JavaScript cleans up URL (removes `logged_out` parameter)

---

#### **POST /check_session**

**Purpose**: Validate current session (used by UI polling)

**Request**:
```http
POST /check_session HTTP/1.1
Cookie: session=<encrypted_token>
Content-Type: application/json

{}
```

**Response (Valid Session - 200 OK)**:
```json
{
  "logged_in": true,
  "username": "alice",
  "role": "readwrite",
  "default_users": false
}
```

**Response (Invalid Session - 401 Unauthorized)**:
```json
{
  "logged_in": false,
  "redirect": "/login"
}
```

**Use Cases**:
- Client-side validation on page load
- Periodic polling to detect session expiration
- Detecting server token rotation (revoke_session.py)

---

### File Operations Endpoints

#### **GET / and GET /<path:path>**

**Purpose**: Browse files and directories with listing and metadata

**Request**:
```http
GET /photos/2024 HTTP/1.1
Cookie: session=<encrypted_token>
```

**Response (Success - 200 OK)**:
```html
<!DOCTYPE html>
<html>
<body>
  <!-- File manager UI with file listing table -->
  <div class="flask-config" 
       data-current-path="photos/2024"
       data-user-role="readwrite"
       data-chunk-size="10485760"
       data-upload-url="/upload">
  </div>
  
  <!-- JavaScript populates this with file data from backend -->
  <table id="fileTable">
    <tr data-path="photos/2024/vacation.jpg" data-is-dir="false">
      <td class="icon"><i class="fas fa-image"></i></td>
      <td class="name">vacation.jpg</td>
      <td class="size">2.5 MB</td>
      <td class="type">Image</td>
      <td class="modified">2024-03-15 14:30</td>
      <td class="actions">
        <button class="download">Download</button>
        <button class="preview">Preview</button>
      </td>
    </tr>
  </table>
</body>
</html>
```

**Backend JSON** (via `index.js` AJAX):
```json
{
  "current_path": "photos/2024",
  "parent_path": "photos",
  "breadcrumbs": [
    {"path": "", "name": "Root"},
    {"path": "photos", "name": "photos"},
    {"path": "photos/2024", "name": "2024"}
  ],
  "items": [
    {
      "name": "vacation.jpg",
      "path": "photos/2024/vacation.jpg",
      "size": 2621440,
      "is_dir": false,
      "type": "image",
      "modified": 1710525000.0,
      "icon": "image"
    },
    {
      "name": "memories",
      "path": "photos/2024/memories",
      "size": 0,
      "is_dir": true,
      "type": "folder",
      "modified": 1710525000.0,
      "icon": "folder"
    }
  ]
}
```

**Security**: 
- Path validated against ROOT_DIR for traversal prevention
- Directory listing respects readonly role (no delete/upload buttons)

---

#### **POST /upload**

**Purpose**: Upload file in chunks with resumable support

**Request (Chunk 0)**:
```http
POST /upload HTTP/1.1
Cookie: session=<encrypted_token>
Content-Type: multipart/form-data

------WebKitBoundary
Content-Disposition: form-data; name="file_id"

f47ac10b-58cc-4372-a567-0e02b2c3d479
------WebKitBoundary
Content-Disposition: form-data; name="chunk_num"

0
------WebKitBoundary
Content-Disposition: form-data; name="total_chunks"

5
------WebKitBoundary
Content-Disposition: form-data; name="chunk_data"; filename="large_file.zip"
Content-Type: application/octet-stream

<10 MB binary data>
------WebKitBoundary--
```

**Response (Success)**:
```json
{
  "status": "chunk_saved",
  "chunk": 0,
  "total_chunks": 5,
  "progress": "1/5",
  "file_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
}
```

**Response (Missing Auth)**:
```json
{
  "error": "Not authenticated",
  "redirect": "/login"
}
```

**Resumable Flow**:
```
User uploads 5 chunks
Connection drops after chunk 2
User reconnects and uploads remaining chunks 3, 4
Query /api/assembly_status returns:
  {
    "complete": true,
    "chunks_received": 3,  // only 2, 3, 4 actually sent
    "total_expected": 5
  }
```

**Backend Storage**:
```
ROOT_DIR/
  .tmp_chunks/
    f47ac10b-58cc-4372-a567-0e02b2c3d479/
      chunk_0   (10 MB)
      chunk_1   (10 MB)
      chunk_2   (10 MB)
      chunk_3   (10 MB)
      chunk_4   (7 MB)
      manifest.json
```

---

#### **POST /bulk-download**

**Purpose**: Generate streaming ZIP of selected files

**Request**:
```http
POST /bulk-download HTTP/1.1
Cookie: session=<encrypted_token>
Content-Type: application/json

{
  "items": [
    "photos/2024/vacation.jpg",
    "photos/2024/memories",
    "documents/report.pdf"
  ]
}
```

**Response (Streaming)**:
```http
HTTP/1.1 200 OK
Content-Type: application/zip
Content-Disposition: attachment; filename="backup.zip"
Transfer-Encoding: chunked

<ZIP data streamed chunk by chunk - no temp file created>
```

**Backend Process**:
```python
# ZIP created on-the-fly using zipstream
# Files added sequentially, not all in memory
# Supports GBs of data without disk overhead
# Readonly users see filtered archive (dirs only accessible, no delete options)
```

---

#### **GET /download/<path:path>**

**Purpose**: Download single file as attachment

**Request**:
```http
GET /download/documents/report.pdf HTTP/1.1
Cookie: session=<encrypted_token>
```

**Response**:
```http
HTTP/1.1 200 OK
Content-Type: application/pdf
Content-Disposition: attachment; filename="report.pdf"
Content-Length: 1048576

<PDF binary data>
```

---

#### **GET /view/<path:path>**

**Purpose**: Preview file (video/image/document/archive)

**Request**:
```http
GET /view/movies/action.mkv HTTP/1.1
Cookie: session=<encrypted_token>
```

**Response (Video - HLS)**:
```html
<!--  Returns HTML with embedded <video-player> web component -->
<video-player src="/cache/hls/action.mkv.m3u8" type="application/x-mpegURL">
</video-player>
<!-- HLS playlist (m3u8) generated by FFmpeg on first access -->
```

**Response (Image)**:
```html
<!-- Image preview in modal -->
<img src="/view/photos/landscape.jpg?format=webp" alt="landscape">
<!-- LibVips converts to WebP on first access if size > 1MB -->
```

**Response (Office Document)**:
```html
<!-- Embedded HTML preview of DOCX/XLSX/PPTX -->
<iframe src="/office_preview/reports/Q1.docx"></iframe>
<!-- Mammoth/openpyxl/python-pptx converts to HTML -->
```

**Response (Archive)**:
```html
<!-- Modal with file list and extraction/download options -->
<div class="archive-preview">
  <table>
    <tr><td>document.pdf</td><td>1.2 MB</td></tr>
    <tr><td>image.png</td><td>2.3 MB</td></tr>
  </table>
</div>
```

---

### Real-time Storage API

#### **GET /api/storage_stats**

**Purpose**: Fast current storage statistics

**Request**:
```http
GET /api/storage_stats HTTP/1.1
Cookie: session=<encrypted_token>
```

**Response**:
```json
{
  "file_count": 1042,
  "dir_count": 87,
  "total_size": 1099511627776,
  "formatted": "1.0 TB",
  "last_update": 1712425600.5,
  "reconcile_in_progress": false,
  "cache_valid": true
}
```

**Cache Strategy**:
- Updated by file_monitor.py on file events
- Stored in cache/storage_index.json
- Return from cache within ms (no directory walk)

---

#### **GET /api/storage_stats_stream**

**Purpose**: Server-Sent Events stream for real-time updates

**Request**:
```http
GET /api/storage_stats_stream HTTP/1.1
Cookie: session=<encrypted_token>
Accept: text/event-stream
```

**Response (Stream)**:
```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

data: {"type":"storage_update","file_count":1042,"dir_count":87,"total_size":1099511627776,"timestamp":1712425600.5}

data: {"type":"storage_update","file_count":1043,"dir_count":87,"total_size":1099516831232}

data: {"type":"reconcile_complete","duration":45.3}

```

**Client-side Usage** (index.js):
```javascript
const eventSource = new EventSource('/api/storage_stats_stream');
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  updateStorageStats(data);  // Update UI in real-time
};
```

**Broadcast Triggers**:
- File added/deleted/modified (via watchdog)
- Reconciliation complete (every 15 minutes)
- User manually refreshes cache

---

#### **GET /api/dir_info/<path>**

**Purpose**: Get metadata for specific directory

**Request**:
```http
GET /api/dir_info/photos/2024 HTTP/1.1
Cookie: session=<encrypted_token>
```

**Response**:
```json
{
  "path": "photos/2024",
  "file_count": 127,
  "dir_count": 3,
  "total_size": 5368709120,
  "mod_time": 1710525000.1234,
  "has_videos": true,
  "has_large_files": true,
  "formatted_size": "5.0 GB"
}
```

**Data Source**: Loaded from cache/storage_index.json (dir_info section)

---

### Search & Index API

#### **GET /api/search**

**Purpose**: Full-text search for files

**Request**:
```http
GET /api/search?q=meeting&path=documents&limit=50 HTTP/1.1
Cookie: session=<encrypted_token>
```

**Response**:
```json
{
  "query": "meeting",
  "path": "documents",
  "results_count": 5,
  "results": [
    {
      "name": "meeting_notes_2024.txt",
      "path": "documents/meetings/meeting_notes_2024.txt",
      "size": 45678,
      "is_dir": false,
      "modified": 1710525000.0,
      "relevance": 0.95
    },
    {
      "name": "meeting_minutes.pdf",
      "path": "documents/archive/meeting_minutes.pdf",
      "size": 234567,
      "is_dir": false,
      "modified": 1709325000.0,
      "relevance": 0.87
    }
  ],
  "search_took_ms": 45
}
```

**Search Strategy**:
- Uses file_index.py lazy loader
- Indexes file names only initially
- Case-insensitive substring matching
- Sorted by relevance (name position, modification time)

---

### Admin Endpoints

#### **POST /admin/rebuild_cache**

**Purpose**: Force full directory walk and cache rebuild

**Request**:
```http
POST /admin/rebuild_cache HTTP/1.1
Cookie: session=<encrypted_token>
Content-Type: application/json

{}
```

**Response (Streaming)**:
```json
{
  "status": "started",
  "message": "Cache rebuild started. Expect 30-60 seconds for large directories."
}
```

**Server Process**:
```
1. Stop file monitor's periodic reconciliation
2. Begin full recursive walk of ROOT_DIR
3. Calculate file_count, dir_count, total_size for EVERY subdirectory
4. Log progress every 1000 files
5. After walk complete:
   - Serialize to cache/storage_index.json
   - Broadcast SSE update with final counts
   - Restart file monitor
6. Return success response
```

**Expected Response** (via SSE):
```json
{"type":"reconcile_complete","duration":45.3,"file_count":5234,"dir_count":123}
```

---

#### **GET /admin/chunk_stats**

**Purpose**: Statistics on pending uploads

**Request**:
```http
GET /admin/chunk_stats HTTP/1.1
Cookie: session=<encrypted_token>
```

**Response**:
```json
{
  "total_chunk_files": 15,
  "total_chunk_size_mb": 150.0,
  "upload_sessions": [
    {
      "file_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "chunks_submitted": 3,
      "chunks_total": 5,
      "size_mb": 50.0,
      "started_at": 1712425500.0,
      "last_activity": 1712425600.0,
      "time_since_activity_seconds": 10
    }
  ],
  "orphaned_count": 2,
  "orphaned_size_mb": 20.0,
  "cleanup_scheduled": true
}
```

**Usage**: Monitor long-running uploads, identify stalled files

---

#### **POST /admin/cleanup_chunks**

**Purpose**: Remove orphaned upload chunks

**Request**:
```http
POST /admin/cleanup_chunks HTTP/1.1
Cookie: session=<encrypted_token>
Content-Type: application/json

{"older_than_hours": 24}
```

**Response**:
```json
{
  "status": "success",
  "cleaned_count": 3,
  "freed_space_mb": 150.0,
  "message": "Removed 3 orphaned uploads (150.0 MB freed)"
}
```

**Safety**:
- Only deletes chunks not accessed in N hours (default 24)
- Protected uploads (via /api/protect_assembly) excluded
- Logs deletion details for audit

---

## 📊 DATABASE PATTERNS & QUERIES

### Common Query Patterns

#### **User Authentication**

```python
# database.py - check_login()
def check_login(username: str, password: str) -> bool:
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT password_hash FROM users WHERE username = ? AND is_active = 1",
            (username,)
        )
        row = cursor.fetchone()
        if row:
            hash_stored = row[0]
            # bcrypt.checkpw() compares plaintext vs stored hash
            return bcrypt.checkpw(password.encode(), hash_stored.encode())
        return False
    except Exception as e:
        print(f"❌ Login check failed: {e}")
        return False
```

**Key Points**:
- One query (fast database hit)
- Returns None if user not found (fails fast)
- bcrypt.checkpw() is slow (intentional, anti-brute-force)
- No user enumeration leaks

---

#### **Session Token Validation**

```python
# database.py - get_server_token()
def get_server_token() -> str:
    """Retrieve current server-wide token used for session validation."""
    try:
        with _write_lock:
            conn = _connect()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM server_tokens WHERE key = 'server_token'"
            )
            row = cursor.fetchone()
            if row:
                return row[0]
            # First call: generate token
            token = secrets.token_hex(32)
            cursor.execute(
                "INSERT INTO server_tokens (key, value, created_at) VALUES (?, ?, ?)",
                ("server_token", token, int(time.time()))
            )
            conn.commit()
            return token
    except Exception as e:
        print(f"❌ Failed to get server token: {e}")
        return ""

# database.py - rotate_server_token()
def rotate_server_token() -> str:
    """Generate new token and invalidate all existing sessions."""
    try:
        with _write_lock:
            conn = _connect()
            cursor = conn.cursor()
            new_token = secrets.token_hex(32)
            cursor.execute(
                "UPDATE server_tokens SET value = ?, created_at = ? WHERE key = 'server_token'",
                (new_token, int(time.time()))
            )
            conn.commit()
            print(f"✅ Server token rotated. All sessions invalidated.")
            return new_token
    except Exception as e:
        print(f"❌ Failed to rotate token: {e}")
        return ""
```

**Key Points**:
- Singleton token replaces ALL user sessions instantly
- One-line update in database
- Client receives 401 on next poll (token mismatch)

---

#### **User Listing with Last Login**

```python
# database.py - list_users()
def list_users() -> list:
    """Return all users with metadata."""
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, role, is_active, created_at, last_login FROM users ORDER BY username"
        )
        users = []
        for row in cursor.fetchall():
            username, role, is_active, created_at, last_login = row
            last_login_str = (
                datetime.fromtimestamp(last_login).strftime("%Y-%m-%d %H:%M:%S")
                if last_login else "Never"
            )
            users.append({
                "username": username,
                "role": role,
                "is_active": is_active,
                "created_at": datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S") if created_at else "Unknown",
                "last_login": last_login_str
            })
        return users
    except Exception as e:
        print(f"❌ Failed to list users: {e}")
        return []
```

---

## 🎨 FRONTEND ARCHITECTURE DEEP DIVE

### index.js State Machine

```javascript
// Global state variables
let currentPath = CURRENT_PATH;          // Current directory
let selectedFiles = new Set();           // Selected checkbox items
let isUploading = false;                 // Upload in progress
let uploadSessions = new Map();          // Tracks multiple uploads
let sseConnection = null;                // SSE event stream
let fileData = [];                       // Cached file list

// State transitions
function navigateToFolder(path) {
  // 1. Validate path
  // 2. Clear selection
  // 3. Fetch file list via AJAX
  // 4. Update breadcrumb
  // 5. Render table
  // 6. Update URL (history)
}

function selectFile(filename) {
  // Toggle selection state
  if (selectedFiles.has(filename)) {
    selectedFiles.delete(filename);
    updateCheckbox(filename, false);
  } else {
    selectedFiles.add(filename);
    updateCheckbox(filename, true);
  }
  // Update bulk action bar visibility
  updateBulkActions();
}

function startUpload(files) {
  // 1. Validate files
  // 2. Check role (readonly → reject)
  // 3. For each file:
  //    - Split into chunks
  //    - Create session ID
  //    - POST each chunk
  // 4. Poll assembly_status
  // 5. On complete: refresh listing
}
```

### Responsive Column Management

```javascript
// smartTableColumnizer() — ResizeObserver pattern
function smartTableColumnizer() {
  const table = document.getElementById('fileTable');
  const rows = table.querySelectorAll('tbody tr');
  
  // Mobile (<600px):    hide type, modified
  // Tablet (600-899px): hide modified
  // Desktop (≥900px):   show all
  
  const resizeObserver = new ResizeObserver(() => {
    const width = table.offsetWidth;
    const headers = table.querySelectorAll('th');
    
    if (width < 600) {
      headers[3].style.setProperty('display', 'none', 'important');  // type
      headers[4].style.setProperty('display', 'none', 'important');  // modified
    } else if (width < 900) {
      headers[3].style.setProperty('display', 'table-cell', 'important');
      headers[4].style.setProperty('display', 'none', 'important');
    } else {
      headers[3].style.setProperty('display', 'table-cell', 'important');
      headers[4].style.setProperty('display', 'table-cell', 'important');
    }
  });
  
  resizeObserver.observe(table);
}
```

### SSE Connection Lifecycle

```javascript
// realtime_stats_stream() — Persistent HTTP connection
function connectStorageStatsStream() {
  if (sseConnection) sseConnection.close();
  
  sseConnection = new EventSource('/api/storage_stats_stream');
  
  sseConnection.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    switch(data.type) {
      case 'storage_update':
        updateStorageStatsUI(data);
        break;
      case 'reconcile_complete':
        showNotification(`Cache rebuilt in ${data.duration}s`);
        break;
      case 'walk_progress':
        updateProgressBar(data.percent);
        break;
    }
  };
  
  sseConnection.onerror = () => {
    console.warn('SSE connection lost. Reconnecting...');
    setTimeout(connectStorageStatsStream, 3000);  // Retry after 3s
  };
}
```

---

## 🔧 PERFORMANCE TUNING

### Database Optimization

```sql
-- Add index for user lookups (already in schema bootstrap)
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_server_tokens_key ON server_tokens(key);
```

### File Monitor Tuning

```python
# config.py adjustments for different workloads

# High-frequency changes directory (e.g., video rendering)
BURST_THRESHOLD = 500      # Fewer reconciles (tolerate more drift)
BURST_WINDOW = 10.0        # Longer observation window
RECONCILE_INTERVAL = 1800  # 30 minutes

# Stable directory (e.g., archive storage)
BURST_THRESHOLD = 50       # More aggressive reconciles
BURST_WINDOW = 2.0         # Quick detection
RECONCILE_INTERVAL = 300   # 5 minutes
```

### Memory Caching

```python
# storage.py - File listing cache for large folders
from functools import lru_cache

@lru_cache(maxsize=100)
def list_dir_cached(path):
    """Cache directory listing for 5 minutes"""
    return storage.list_dir(path)

# Invalidate cache on file event
def on_file_created(path):
    parent = os.path.dirname(path)
    list_dir_cached.cache_clear()  # Clear all cache
```

### ZIP Generation Optimization

```python
# app.py - Streaming ZIP without temp files
def bulk_download():
    # Use zipstream.ZipStream for on-the-fly generation
    
    # BAD: Creates temp file
    # with zipfile.ZipFile('/tmp/backup.zip', 'w') as zf:
    #     for item in items:
    #         zf.write(item)
    # return send_file('/tmp/backup.zip')
    
    # GOOD: Stream without temp file
    def generate_zip():
        with zipstream.ZipStream(sized=False) as zs:
            for item in items:
                if os.path.isfile(item):
                    zs.write(item)
                else:
                    for root, dirs, files in os.walk(item):
                        for file in files:
                            filepath = os.path.join(root, file)
                            zs.write(filepath)
            for chunk in zs.flush():
                yield chunk
    
    return Response(generate_zip(), mimetype='application/zip')
```

---

## 🚨 ERROR HANDLING & RECOVERY

### Error Response Format

```python
# Standardized error responses across all endpoints

def error_response(status_code, error_type, message, details=None):
    response = {
        "success": False,
        "error": error_type,
        "message": message,
        "timestamp": datetime.now().isoformat()
    }
    if details:
        response["details"] = details
    return jsonify(response), status_code

# Usage:
return error_response(
    400,
    "invalid_path",
    "Path traversal detected",
    {"path": "../../etc/passwd", "reason": "Outside ROOT_DIR"}
)
```

### Upload Failure Recovery

```javascript
// index.js - Retry logic for failed chunks

async function uploadChunk(file, chunkNum, fileId) {
  let retries = 3;
  
  while (retries > 0) {
    try {
      const response = await fetch('/upload', {
        method: 'POST',
        body: formData  // Contains chunk data
      });
      
      if (response.ok) {
        return await response.json();
      } else if (response.status === 429) {
        // Rate limited, wait then retry
        await sleep(5000);
        retries--;
      } else {
        // Permanent error
        throw new Error(`Upload failed: ${response.status}`);
      }
    } catch (err) {
      console.error(`Chunk ${chunkNum} failed (${retries} retries left)`, err);
      retries--;
      await sleep(2000);
    }
  }
  
  throw new Error(`Chunk ${chunkNum} failed after 3 retries`);
}
```

---

## 🔍 TROUBLESHOOTING GUIDE

### Common Issues & Solutions

#### **Issue: "Session expired" message but I just logged in**

**Cause**: Server token rotated (revoke_session.py was run)

**Solution**:
```bash
# 1. Log out completely
# 2. Clear browser cookies
# 3. Log back in
# 4. If still failing, check: python debug_passwords.py
```

**Debug Steps**:
```python
from database import db
token_now = db.get_server_token()
print(f"Current token: {token_now[:8]}...")
# Compare with session cookie in browser
```

---

#### **Issue: Uploads stuck at 50%, then timeout**

**Cause**: Large chunk (10MB) hitting network timeout or rate limiting

**Solution**:

```python
# config.py - Reduce chunk size
CHUNK_SIZE = 5 * 1024 * 1024  # 5MB instead of 10MB

# Restart server and retry
```

**Or increase timeout**:

```python
# prod_server.py - Configure Waitress
app.config['PERMANENT_SESSION_LIFETIME'] = 7200  # 2 hours
```

**Check orphaned chunks**:
```bash
python -c "from app import app; from database import db; import json
stats = requests.get('http://localhost:5000/admin/chunk_stats').json()
print(f\"Orphaned: {stats['orphaned_count']} files ({stats['orphaned_size_mb']} MB)\")"
# Then POST /admin/cleanup_chunks to remove old uploads
```

---

#### **Issue: "File not found" error when file exists**

**Cause**: File monitor cache out of sync, or file outside ROOT_DIR

**Solution**:

```bash
# 1. Check ROOT_DIR is configured correctly
python -c "from config import ROOT_DIR; print(f'ROOT_DIR={ROOT_DIR}')"

# 2. Rebuild cache
curl -X POST http://localhost:5000/admin/rebuild_cache \
  -H "Cookie: session=<your_session>"

# 3. Check file actually exists
ls -la /path/to/ROOT_DIR/myfile.txt
```

---

#### **Issue: Search returns no results**

**Cause**: file_index.py not loaded or indexed

**Solution**:

```bash
# 1. Force index rebuild
rm cache/file_index.json

# 2. Perform any search (triggers re-index on first use)
# curl "http://localhost:5000/api/search?q=test"

# 3. Check index file was created
ls -la cache/file_index.json
```

---

#### **Issue: Video plays but no sound**

**Cause**: FFmpeg codec issue or HLS segment missing

**Solution**:

```bash
# 1. Check FFmpeg is installed
ffmpeg -version

# 2. Test FFmpeg can transcode the file
ffmpeg -i /path/to/video.mkv -f hls /tmp/test.m3u8

# 3. If fails, video format not supported
# Set ENABLE_FFMPEG=False in config.py to fallback to raw playback
```

---

#### **Issue: WebP images loading very slowly**

**Cause**: libvips not installed, falling back to raw images

**Solution**:

```bash
# 1. Check libvips installed
vips --version

# 2. If not present, install:
# Windows: Download from https://www.libvips.org/install.html
# Linux: sudo apt-get install libvips libvips-dev
# macOS: brew install libvips

# 3. Test conversion
python -c "import pyvips; img = pyvips.Image.new_from_file('test.jpg'); img.webpsave('test.webp')"
```

---

## 🛡️ SECURITY CONSIDERATIONS

### Path Traversal Prevention

```python
# storage.py - All file operations validate path
import os

def is_path_valid(user_path: str) -> bool:
    """
    Ensure user path doesn't escape ROOT_DIR
    
    Valid:   "photos/2024/vacation.jpg"
    Invalid: "../../../etc/passwd"
    Invalid: "/etc/passwd" (absolute path)
    """
    abs_root = os.path.abspath(ROOT_DIR)
    abs_path = os.path.abspath(os.path.join(ROOT_DIR, user_path))
    
    # Prevent escaping ROOT_DIR
    if not abs_path.startswith(abs_root):
        return False
    
    # Prevent absolute paths
    if os.path.isabs(user_path):
        return False
    
    return True

# Usage in all file endpoints
@app.route("/download/<path:path>")
def download_file(path):
    if not is_path_valid(path):
        return error_response(400, "invalid_path", "Path traversal detected")
    
    # Safe to access file now
    return send_file(os.path.join(ROOT_DIR, path))
```

### Password Security

```python
# database.py - bcrypt hashing prevents rainbow tables

def add_user(username: str, password: str, role: str):
    # bcrypt with salt rounds configurable
    password_hash = bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt(rounds=12)  # 12 = ~100ms to hash (slow = secure)
    )
    
    # Never store plaintext password
    # Never log password
    # Use bcrypt.checkpw() for comparison (timing-safe)
```

### Encryption Key Protection

```python
# database.py - Fernet key must be backed up separately

def _load_or_create_key() -> bytes:
    key_path = os.path.join(_DB_DIR, "secret.key")
    
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read().strip()
    
    # Generate new key
    key = Fernet.generate_key()
    
    # Save to disk
    with open(key_path, "wb") as f:
        f.write(key)
    
    print("⚠️  CRITICAL: Backup secret.key file separately!")
    print("    Losing this key means losing access to all encrypted data.")
    print(f"    Location: {key_path}")
    
    return key
```

**Backup Strategy**:
```bash
# 1. Copy secret.key to secure location
cp db/secret.key /encrypted/backup/secret.key

# 2. Copy session.secret  
cp db/session.secret /encrypted/backup/session.secret

# 3. Copy cloudinator.db (user credentials)
cp db/cloudinator.db /encrypted/backup/cloudinator.db

# 4. Keep backups encrypted:
gpg --symmetric /encrypted/backup/secret.key
```

---

## 📈 MONITORING & OBSERVABILITY

### Health Check Endpoint

```python
# app.py - /api/health_check
@app.route("/api/health_check", methods=["GET"])
def health_check():
    health = {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "checks": {}
    }
    
    # Check database
    try:
        db.get_role("admin")  # Quick query
        health["checks"]["database"] = "ok"
    except Exception as e:
        health["checks"]["database"] = f"error: {e}"
        health["status"] = "degraded"
    
    # Check file monitor
    try:
        from file_monitor import is_running
        health["checks"]["file_monitor"] = "ok" if is_running() else "not running"
    except Exception:
        health["checks"]["file_monitor"] = "error"
    
    # Check disk space
    try:
        import shutil
        usage = shutil.disk_usage(ROOT_DIR)
        health["checks"]["disk_space_gb"] = round(usage.free / (1024**3), 2)
        if usage.free < (1024**3 * 5):  # < 5GB
            health["status"] = "warning"
    except Exception as e:
        health["checks"]["disk_space"] = f"error: {e}"
    
    return jsonify(health)
```

### Logging Setup (Optional)

```python
# app.py - Configure logging
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cloudinator.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

@app.before_request
def log_request():
    logger.info(f"{request.method} {request.path} - {request.remote_addr}")

@app.after_request
def log_response(response):
    logger.info(f"Response: {response.status_code}")
    return response
```

---

## 🎬 ADVANCED FFMPEG CONFIGURATION

### Custom HLS Settings

```python
# config.py - FFmpeg HLS tuning

# Default HLS segment duration (seconds)
HLS_SEGMENT_DURATION = 10

# Default HLS playlist size (number of segments)
HLS_PLAYLIST_SIZE = 3

# Custom FFmpeg arguments
FFMPEG_HLS_ARGS = [
    'ffmpeg',
    '-i', '{input}',
    '-c:v', 'libx264',      # Video codec
    '-preset', 'fast',       # Quality vs speed tradeoff
    '-c:a', 'aac',          # Audio codec
    '-b:a', '128k',         # Audio bitrate
    '-f', 'hls',
    '-hls_segment_duration', str(HLS_SEGMENT_DURATION),
    '-hls_list_size', str(HLS_PLAYLIST_SIZE),
    '{output}'
]
```

---

## 📞 REFERENCE LINKS

**Internal**:
- Deployment Guides: `docs/`
- Database: `database.py` (all user/token logic)
- File Ops: `storage.py` (chunking, assembly)
- File Monitor: `file_monitor.py` (watchdog, reconciliation)
- Routes: `app.py` (all 30+ endpoints)
- Configuration: `config.py` + `paths.py`

**External**:
- Flask: https://flask.palletsprojects.com/
- Watchdog: https://watchdog.readthedocs.io/
- Fernet (cryptography): https://cryptography.io/
- bcrypt: https://github.com/pyca/bcrypt
- FFmpeg: https://ffmpeg.org/
- libvips: https://www.libvips.org/
- SQLite: https://www.sqlite.org/

---

## 📄 CANONICAL BEHAVIOR

This document captures the design and architecture **as of April 6, 2026**. Future changes (features, deprecations, rewrites) do not invalidate these descriptions. When asking Claude AI for help on this codebase, reference this CLAUDE.md as ground truth.

**Example**: Even if `file_monitor.py` is rewritten to use polling instead of watchdog, this document's description remains valid historical context for understanding the **intent** of the system.

---

**Last Reviewed**: 2026-04-06  
**Status**: ✅ Stable — Ready for AI-assisted development  
**Approximate Line Count**: 10,000+ lines (comprehensive level)
