# CloudinatorFTP Configuration Reference

This document explains the main runtime settings defined in [../config.py](../config.py) and how they influence the application.

The file acts as the central configuration hub for:

- HTTP server behavior
- upload and session limits
- media conversion settings
- protocol listeners (WebDAV, SFTP, FTP, SMB)
- filesystem storage locations
- Version Engine behavior
- platform-aware storage defaults

It is also closely tied to [../server_config.json](../server_config.json), which stores a persisted subset of these values when the app saves the server configuration.

> ⚡ Quick fixes for common admin problems
>
> - If settings reset after restart, run `save_server_config()` and confirm the JSON file is being updated.
> - If the app will not bind ports, check for conflicts on `5000`, `8080`, `8443`, `2121`, `2222`, or `445`.
> - If media preview fails, confirm `ENABLE_FFMPEG` and `ENABLE_LIBVIPS` are enabled and the tools are installed.
> - If storage paths fail, make sure the directory exists and is writable by the service account.
> - If SMB does not work, run `python smb_setup.py` once on the host machine.

> ✅ Before you edit production settings
>
> - Back up [../server_config.json](../server_config.json) and your database/data directories first.
> - Keep sensitive paths outside the server root whenever possible.
> - Change only one setting at a time when diagnosing problems.
> - Restart the app after making configuration changes and confirm behavior before continuing.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Core server settings](#2-core-server-settings)
3. [HLS / media streaming settings](#3-hls--media-streaming-settings)
4. [Image conversion settings](#4-image-conversion-settings)
5. [Configuration via the admin console](#5-configuration-via-the-admin-console)
6. [Protocol server configuration](#6-protocol-server-configuration)
7. [Storage directory settings](#7-storage-directory-settings)
8. [Version Engine configuration](#8-version-engine-configuration)
9. [Persistence model: server_config.json](#9-persistence-model-server_configjson)
10. [Platform detection and storage defaults](#10-platform-detection-and-storage-defaults)
11. [Configuration workflow](#11-configuration-workflow)
12. [Recommended configuration checklist](#12-recommended-configuration-checklist)
13. [Practical examples](#13-practical-examples)
14. [Troubleshooting](#14-troubleshooting)
15. [Summary](#15-summary)

---

## 1. Overview

`config.py` defines global constants that are imported and used throughout the project. It also contains helper functions for:

- detecting the current platform
- choosing a default storage directory
- saving and loading configuration from `server_config.json`
- configuring storage directories for DB/cache/version data
- CLI-based configuration prompts for the admin console

The project uses a mix of:

- hardcoded defaults in the module itself
- runtime overrides from environment variables
- persisted values from `server_config.json`
- path helper functions in [../paths.py](../paths.py)

When the app starts, values can be loaded from disk using `load_server_config()`, and saved by `save_server_config()`.

---

## 2. Core server settings

These are the foundational runtime settings for the main web application.

| Setting | Default | Purpose |
|---|---:|---|
| `PORT` | `5000` | Main Flask/Quart web server port |
| `CHUNK_SIZE` | `10 * 1024 * 1024` | Upload chunk size for large transfers |
| `ENABLE_CHUNKED_UPLOADS` | `True` | Enables resumable chunked file uploads |
| `HOST` | `"0.0.0.0"` | Bind address for the main app |
| `MAX_CONTENT_LENGTH` | `16 * 1024 * 1024 * 1024` | Maximum accepted upload size (16 GB) |
| `ALLOWED_EXTENSIONS` | `None` | Restricts upload types when set to a list/set of lowercase extensions |
| `PERMANENT_SESSION_LIFETIME` | `31536000` | Session lifetime in seconds (365 days) |

### Notes

- `ALLOWED_EXTENSIONS` is intentionally set to `None` by default, which means all file types are permitted.
- To restrict uploads, assign a lowercase set/list such as `{"jpg", "jpeg", "png", "pdf"}` without leading dots.
- `PERMANENT_SESSION_LIFETIME` is tied into the Flask session configuration in the app and is no longer just a dormant value.

---

## 3. HLS / media streaming settings

These settings affect browser playback behavior for video files.

| Setting | Default | Purpose |
|---|---:|---|
| `HLS_MIN_SIZE` | `50 * 1024 * 1024` | Files below this size are served raw for web-native formats |
| `HLS_FORCE_FORMATS` | `{"mkv", "avi", "wmv", "flv", "mpg", "mpeg", "m2ts", "mts", "3gp", "ogv"}` | Formats that always use HLS regardless of file size |
| `ENABLE_FFMPEG` | `True` | Enables HLS/transcoding backend when available |

### Behavior

- Small web-native videos can be streamed directly without transcoding.
- Large or unsupported formats are routed toward HLS streaming.
- If `ENABLE_FFMPEG` is disabled, the app falls back to raw playback only.

---

## 4. Image conversion settings

These settings control image optimization and preview generation.

| Setting | Default | Purpose |
|---|---:|---|
| `ENABLE_LIBVIPS` | `True` | Enables image conversion and WebP optimization |
| `IMG_COMPRESS_MIN_SIZE` | `1 * 1024 * 1024` | Images above this size are compressed to WebP |
| `IMG_WEBP_QUALITY` | `50` | Quality setting for lossy WebP conversion |
| `ENABLE_SEARCH_INDEX` | `True` | Uses SQLite search index when available; otherwise falls back to `os.walk` |

### Notes

- Native image formats smaller than `IMG_COMPRESS_MIN_SIZE` are served raw.
- Larger images may be converted to WebP to reduce bandwidth.
- When `ENABLE_LIBVIPS` is false, raw serving is used and unsupported formats may show a fallback notice instead of processed output.

---

## 5. Configuration via the admin console

The project includes a built-in configuration workflow in `config.py` for administrators who want to change runtime values without editing Python files directly. This follows the same pattern as the user guide’s operational sections: a quick access path, a guided menu, and a save step before the new values take effect.

### Accessing the configuration helpers

From a Python session, you can call the configuration menu directly:

```python
from config import main_configuration_menu
main_configuration_menu()
```

The module also exposes individual helper functions for targeted changes, including:

- `configure_storage_path()`
- `configure_db_path()`
- `configure_cache_path()`
- `configure_versions_path()`
- `configure_version_engine_settings()`
- `configure_hls_settings()`
- `configure_image_settings()`
- `configure_server_settings()`

### What the menu covers

The main menu is organized into a few practical categories:

| Menu section | Purpose |
|---|---|
| Storage Path Configuration | Adjust file storage, database, cache, HLS cache, and image cache paths |
| Server Settings Configuration | Change ports, session timeout, upload settings, and host binding |
| Version History / Version Engine | Toggle versioning, tracking rules, retention, and symlink behavior |
| View Current Settings | Review the active runtime values |

### Typical admin workflow

1. Start the Python configuration flow.
2. Pick the section that needs adjustment.
3. Choose a suggested location or custom path when prompted.
4. Confirm the final choice before saving.
5. Save the config and restart the app if the setting is runtime-critical.

### Example: changing the storage root

```python
from config import configure_storage_path
configure_storage_path()
```

This opens the storage submenu and lets the administrator select one of the preset folders or enter a custom directory for the main files root.

### Example: changing the version engine settings

```python
from config import configure_version_engine_settings
configure_version_engine_settings()
```

This editor-friendly flow allows the admin to change:

- engine enable/disable state
- small-file threshold
- chunk size
- worker count
- watcher and scanner behavior
- retention and garbage collection rules
- overwrite and symlink behavior

### Save behavior

The configuration helpers do not blindly mutate the working environment. They call the same persistence functions used elsewhere in the project, saving a subset of current values to [../server_config.json](../server_config.json) so the settings survive restarts.

> ⚠️ After changing storage paths or sensitive runtime values, restart the app so the updated configuration is reapplied consistently.

---

## 6. Protocol server configuration

CloudinatorFTP supports multiple network protocols. These settings are explicitly documented as being loaded from and saved to `server_config.json`.

### WebDAV

| Setting | Default | Purpose |
|---|---:|---|
| `WEBDAV_ENABLED` | `False` | Legacy plain WebDAV listener |
| `WEBDAV_PORT` | `8080` | Plain HTTP WebDAV port |
| `WEBDAV_HTTPS_ENABLED` | `True` | Prefer HTTPS WebDAV listener |
| `WEBDAV_HTTPS_PORT` | `8443` | HTTPS WebDAV port |

### Important WebDAV note

The config comments explicitly state:

- HTTPS is preferred and preferred over the plain HTTP listener when the certificate loads successfully.
- `WEBDAV_ENABLED` does not run alongside HTTPS in the usual case.
- The project reuses an auto-generated certificate in the database directory for HTTPS.

### SFTP

| Setting | Default | Purpose |
|---|---:|---|
| `SFTP_ENABLED` | `True` | Enables SFTP access |
| `SFTP_PORT` | `2222` | SFTP port |

### FTP / FTPS

| Setting | Default | Purpose |
|---|---:|---|
| `FTP_ENABLED` | `True` | Enables FTP | 
| `FTP_PORT` | `2121` | FTP control port |
| `FTP_TLS_ENABLED` | `True` | Enables FTPS (`AUTH TLS`) |
| `FTP_TLS_REQUIRE_DATA` | `True` | Requires TLS on the data channel |

### SMB

| Setting | Default | Purpose |
|---|---:|---|
| `SMB_ENABLED` | `False` | SMB share listener is off by default |
| `SMB_PORT` | `445` | Standard SMB port |
| `SMB_FALLBACK_PORT` | `8445` | Fallback port if 445 cannot be bound |
| `SMB_SHARE_NAME` | `"SharedFolder"` | Share name exposed to clients |

### Notes

- SMB is intentionally off by default even when the library is installed.
- The config comments say the machine requires one-time setup before the service is practically useful.
- The admin can run `python smb_setup.py` or `./manage.sh smb-setup` to enable it properly.

---

## 7. Storage directory settings

`config.py` manages several storage directories that are created and resolved via path helpers from [../paths.py](../paths.py).

### Main storage categories

| Variable | Source | Purpose |
|---|---|---|
| `ROOT_DIR` | `setup_storage_directory()` | main uploaded-file storage root |
| `DB_DIR` | `get_db_dir(create=False)` | database and sensitive secret files |
| `CACHE_DIR` | `get_cache_dir(create=False)` | metadata and index caches |
| `HLS_CACHE_DIR` | `get_hls_cache_dir(create=False)` | HLS segment cache |
| `IMG_CACHE_DIR` | `get_img_cache_dir(create=False)` | generated image preview cache |
| `VERSION_STORAGE_DIR` | `get_versions_dir(create=False)` | version-history object store |

### Path behavior

The project looks for a custom root path in this order:

1. `CLOUDINATOR_FTP_ROOT` environment variable
2. `storage_config.json` saved values via `paths._load()`
3. platform-aware auto-detection via `get_accessible_storage_path()`

The default location depends on platform:

- Termux: `/storage/emulated/0/...` when accessible, otherwise user home
- Linux: `$HOME/CloudinatorFTP`
- Windows: Documents/CloudinatorFTP
- macOS: `$HOME/CloudinatorFTP`

### Security recommendations

The config comments explicitly warn that `DB_DIR` should be moved outside the server root when possible because it may contain:

- SQLite user database
- `secret.key`
- `session.secret`

This is important for preventing a misconfigured web server from exposing private session or encryption data.

---

## 8. Version Engine configuration

The Version Engine is a separate subsystem for tracking historical file versions.

### Master switch and storage

| Setting | Default | Purpose |
|---|---:|---|
| `VERSION_ENGINE_ENABLED` | `True` | Enables the Version Engine child process |
| `VERSION_STORAGE_DIR` | derived from path helpers | Version object and chunk storage |
| `VERSION_DB_FILENAME` | `"version_engine.sqlite3"` | SQLite database for version metadata |

### Chunking and retention

| Setting | Default | Purpose |
|---|---:|---|
| `VERSION_SMALL_FILE_THRESHOLD` | `4 * 1024 * 1024` | Below this: full-object storage |
| `VERSION_CHUNK_SIZE` | `8 * 1024 * 1024` | Version chunk size |
| `VERSION_CHUNKING_ALGORITHM` | `"fixed"` | Chunking strategy |
| `VERSION_RETENTION_ENABLED` | `True` | Enables retention policy |
| `VERSION_MAX_VERSIONS` | `50` | Max versions per file |
| `VERSION_GC_ENABLED` | `True` | Enables garbage collection |
| `VERSION_GC_GRACE_PERIOD` | `24 * 60 * 60` | Time before unreferenced objects are deleted |

### Watcher and scanner

| Setting | Default | Purpose |
|---|---:|---|
| `VERSION_WATCH_ENABLED` | `True` | Enables filesystem watch-based updates |
| `VERSION_SCAN_ENABLED` | `True` | Enables periodic scan-based reconciliation |
| `VERSION_SCAN_INTERVAL` | `300` | Reconciliation interval in seconds |

### Tracking scope

| Setting | Default | Purpose |
|---|---:|---|
| `VERSION_TRACK_FILES` | `[]` | Explicit list of files to track |
| `VERSION_TRACK_DIRECTORIES` | `[]` | Explicit list of directories to track |
| `VERSION_TRACK_ROOTS` | `[]` | Root paths for recursive tracking |
| `VERSION_TRACK_ALL_FILES` | `False` | Recursively track all files under configured roots |
| `VERSION_EXCLUDE_DIRECTORIES` | `[]` | Directories to exclude |
| `VERSION_EXCLUDE_PATTERNS` | `["*.tmp", "*.part", "~$*"]` | Filename patterns to ignore |

### Reliability and restore behavior

| Setting | Default | Purpose |
|---|---:|---|
| `VERSION_RETRY_COUNT` | `3` | Retries for failed operations |
| `VERSION_RETRY_DELAY` | `2` | Delay between retry attempts |
| `VERSION_COMPRESSION_ENABLED` | `False` | Enables object compression |
| `VERSION_FOLLOW_SYMLINKS` | `False` | Whether symlinks are followed during version capture |
| `VERSION_ALLOW_RESTORE_OVERWRITE` | `False` | Allows overwriting files during restore |
| `VERSION_SHUTDOWN_TIMEOUT` | `30` | Grace period before process force-kill |

### Important note

The comments in the config explicitly state that `VERSION_TRACK_FILES`, `VERSION_TRACK_DIRECTORIES`, and `VERSION_TRACK_ROOTS` all default to empty lists so the system does not accidentally version an entire drive or directory tree.

---

## 9. Persistence model: `server_config.json`

The configuration module contains two key functions:

- `save_server_config()`
- `load_server_config()`

These functions serialize a large subset of the module settings into [../server_config.json](../server_config.json) and reload them on startup.

Saved sections include:

- core server settings
- HLS and image settings
- protocol server settings
- Version Engine values
- metadata such as `configured_at`

This makes the app configuration resilient across restarts without hardcoding every setting into the environment.

### Example persisted values

The save function includes entries like:

- `PORT`
- `HOST`
- `CHUNK_SIZE`
- `ENABLE_CHUNKED_UPLOADS`
- `MAX_CONTENT_LENGTH`
- `WEBDAV_ENABLED`
- `SFTP_ENABLED`
- `FTP_ENABLED`
- `SMB_ENABLED`
- `VERSION_ENGINE_ENABLED`
- `VERSION_TRACK_FILES`
- `VERSION_FOLLOW_SYMLINKS`

---

## 10. Platform detection and storage defaults

The config file includes helper functions such as:

- `detect_platform()`
- `get_windows_documents_path()`
- `get_accessible_storage_path()`
- `setup_storage_directory()`

These are used to choose a default root path and to provide user-friendly messaging about storage location.

### Default platform mapping

- `termux` → uses Android storage or Termux home
- `linux` → `$HOME/CloudinatorFTP`
- `windows` → `Documents/CloudinatorFTP`
- `macos` → `$HOME/CloudinatorFTP`
- `unknown` → current working directory fallback

### Preset path helpers

There are also preset path definitions for quick setup such as:

- `downloads`
- `documents`
- `desktop`
- `internal`
- `dcim`
- `userprofile`

This is used by the config wizard and storage path configuration functions.

---

## 11. Configuration workflow

The file contains interactive helper functions such as:

- `configure_server_settings()`
- `configure_storage_path()`
- `configure_db_path()`
- `configure_cache_path()`
- `configure_versions_path()`
- `configure_version_engine_settings()`
- `configure_hls_settings()`
- `configure_image_settings()`

These are intended for manual CLI configuration and are useful when running the project without editing Python constants directly.

---

## 12. Recommended configuration checklist

For most deployments, these settings are worth reviewing first:

1. `HOST` and `PORT` for network exposure
2. `MAX_CONTENT_LENGTH` for upload limits
3. `WEBDAV_HTTPS_ENABLED` and `WEBDAV_HTTPS_PORT`
4. `SFTP_ENABLED` / `FTP_ENABLED` / `SMB_ENABLED`
5. `DB_DIR` and storage locations for security and performance
6. `VERSION_ENGINE_ENABLED` and version retention thresholds
7. `ENABLE_FFMPEG` and `ENABLE_LIBVIPS` for media optimization

---

## 13. Practical examples

### Disable a protocol

```python
FTP_ENABLED = False
SFTP_ENABLED = False
WEBDAV_ENABLED = False
```

### Make the app more conservative with uploads

```python
MAX_CONTENT_LENGTH = 4 * 1024 * 1024 * 1024
CHUNK_SIZE = 5 * 1024 * 1024
ENABLE_CHUNKED_UPLOADS = True
```

### Limit uploaded types

```python
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf", "mp4"}
```

### Move the database outside the app root

```python
from paths import set_db_dir
set_db_dir("/var/lib/cloudinator/db")
```

### Disable version tracking for symlinks and restorations

```python
VERSION_FOLLOW_SYMLINKS = False
VERSION_ALLOW_RESTORE_OVERWRITE = False
```

---

## 14. Troubleshooting

This section covers the most common configuration problems administrators run into when adjusting values in `config.py` or managing the saved settings in [../server_config.json](../server_config.json).

### Problem: settings seem to reset after restart

**Possible cause**
- The values were changed in memory but never saved via `save_server_config()`.
- Or a stale `server_config.json` is overriding the defaults.

**What to check**
- Make sure the active configuration is saved.
- Inspect [../server_config.json](../server_config.json) and confirm the expected keys are present.
- Verify the app is not reloading a previous file from a different working directory.

**Fix**
```python
from config import save_server_config
save_server_config()
```

If the file still looks wrong, compare the runtime values in Python with the JSON file and adjust the keys you want to persist.

---

### Problem: port conflicts prevent the app from starting

**Possible cause**
- Another service is already bound to a port used by CloudinatorFTP.
- Common conflicts include `5000`, `8080`, `8443`, `2121`, `2222`, or `445`.

**What to check**
- Review the port values in `config.py`.
- Confirm no other service is using them.
- If using Windows, check the active listener list or firewall rules.

**Fix**
```python
PORT = 5001
WEBDAV_HTTPS_PORT = 9443
SFTP_PORT = 2223
FTP_PORT = 2122
```

Use unique ports that do not conflict with other services on the same machine.

---

### Problem: WebDAV HTTPS or FTPS certificate errors

**Possible cause**
- `cryptography` or pyOpenSSL is missing.
- A previous certificate was not generated or cannot be loaded.

**What to check**
- Confirm the HTTPS flags are enabled.
- Read the startup logs for TLS/certificate creation errors.
- Make sure the app has permission to write the secure certificate store or local `db/` directory.

**Fix**
- Reinstall the required package dependencies.
- Re-run the app so the certificate can be generated automatically.
- Check whether the app is falling back to plain HTTP when HTTPS cannot be initialized.

---

### Problem: media preview or transcoding is not working

**Possible cause**
- `ENABLE_FFMPEG` is disabled.
- `ENABLE_LIBVIPS` is disabled.
- The external binaries are not installed on the system.

**What to check**
- Confirm the feature toggles in `config.py`.
- Check whether `ffmpeg` and `libvips` are installed and available on `PATH`.

**Fix**
```python
ENABLE_FFMPEG = True
ENABLE_LIBVIPS = True
```

If the binaries are missing, the app usually falls back to raw playback or raw image serving rather than failing outright, but a real conversion pipeline requires the external tools to be installed.

---

### Problem: database or cache paths are not writable

**Possible cause**
- The configured directory does not exist or lacks write permissions.
- The app was started under a user that cannot access the path.

**What to check**
- Inspect `DB_DIR`, `CACHE_DIR`, `HLS_CACHE_DIR`, and `IMG_CACHE_DIR`.
- Validate permissions on the target directories.
- Confirm the parent folder exists and is writable.

**Fix**
```python
from paths import set_db_dir, set_cache_dir
set_db_dir("/path/to/secure/db")
set_cache_dir("/path/to/cache")
```

For locked-down deployments, use a directory outside the web root and verify the service account has write access.

---

### Problem: Version Engine is not tracking files as expected

**Possible cause**
- `VERSION_ENGINE_ENABLED` is false.
- The tracking lists are empty.
- The configured roots or exclude patterns are too restrictive.

**What to check**
- Confirm `VERSION_ENGINE_ENABLED = True`.
- Inspect `VERSION_TRACK_ROOTS`, `VERSION_TRACK_DIRECTORIES`, and `VERSION_TRACK_FILES`.
- Review `VERSION_EXCLUDE_PATTERNS` and `VERSION_EXCLUDE_DIRECTORIES`.

**Fix**
```python
VERSION_ENGINE_ENABLED = True
VERSION_TRACK_ROOTS = ["/path/to/shared/files"]
VERSION_TRACK_ALL_FILES = True
```

Remember that the lists are intentionally empty by default to avoid accidentally versioning an entire drive.

---

### Problem: SMB does not work even though it is enabled

**Possible cause**
- The one-time machine setup was never completed.
- Port 445 is occupied or the OS-level setup is not valid.

**What to check**
- Confirm `SMB_ENABLED = True`.
- Run the SMB setup script once on the host machine.
- Check whether a fallback port is in use or whether the server is allowed to bind the configured port.

**Fix**
```bash
python smb_setup.py
```

If the platform requires it, run the OS-specific instructions and then re-enable SMB in the configuration.

---

### Problem: a setting works in code but not at runtime

**Possible cause**
- The app was not restarted after the change.
- A saved JSON value is overriding the in-code default.
- The setting is only used in one code path and is not wired to the configuration loader.

**What to check**
- Restart the app after editing config values.
- Compare the runtime value against `server_config.json`.
- Confirm the setting is actually imported and used in the code path you expect.

**Best practice**
- Keep configuration changes centralized.
- Save the app config after admin edits.
- Validate the behavior after a restart rather than assuming the value is active immediately.

---

## 15. Summary

`config.py` is the central configuration source for CloudinatorFTP. It defines:

- service ports and access settings
- media conversion behavior
- protocol enablement
- secure/default storage directories
- version history retention and scanning policies
- compatibility with the app’s saved runtime configuration

For production deployments, the safest pattern is to review these settings once, save them to `server_config.json`, and keep sensitive data directories outside the web root. Troubleshooting is usually a matter of confirming the active runtime values, checking filesystem permissions, and ensuring ports and supporting tools are available.
