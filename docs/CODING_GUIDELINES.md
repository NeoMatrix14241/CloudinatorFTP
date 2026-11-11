# CloudinatorFTP Coding Guidelines

This document explains how to make changes to CloudinatorFTP safely: where behavior belongs, which related files and contracts to update, and how to validate each kind of change. It is written first as contributor guidelines; the later architecture, file, import, and reference maps provide supporting detail.

Use the change recipes and validation sections as the working checklist. Use the file and dependency indexes when tracing ownership or impact across the codebase.

## Start Here: Change Checklist

1. **Find the behavior owner.** Use the [complete source index](#25-complete-source-index) to locate the Python module, route, tool, template, or frontend asset that owns the behavior.
2. **Trace its edges before editing.** Check the [Python import graph](#27-python-import-graph) for module dependencies and the [cross-file reference map](#28-cross-file-reference-map) for runtime, API, DOM, asset, configuration, and persistence contracts.
3. **Follow the relevant change recipe.** The [change recipes](#22-change-recipes) cover routes, filesystem mutations, frontend controls, configuration, database schema, indexes/live updates, security, protocols, and route modules.
4. **Keep ownership boundaries intact.** Use one shared Quart app; keep hooks in middleware; put route handlers in their feature route module; use `paths.py` for persistent directory configuration; keep helpers as leaf utilities; do not edit vendored bundles for app-specific integration fixes.
5. **Update both sides of each interface.** When changing an endpoint, data shape, DOM ID/class, config key, persisted schema, or asset, update its callers/consumers and any operator-facing documentation that names it.
6. **Validate the touched surface.** Start with [validation by change type](#23-validation-by-change-type), then run focused behavior checks for filesystem, browser, authentication, or protocol changes. Static checks do not prove runtime behavior.

## 1. Project summary

CloudinatorFTP is a Quart-based file server and browser UI for managing files, sharing links, previews, upload flows, and optional protocol services such as WebDAV, SFTP, FTP, and SMB. The project combines:

- a browser-driven file manager UI
- a SQLite-backed user and share database
- a filesystem monitor for live updates
- optional preview/transcoding systems for images and video
- a versioning subsystem for file history
- exposed protocol listeners for alternate file access methods

The main entry points are:

- [../app.py](../app.py) — composition root and startup wiring
- [../core.py](../core.py) — shared runtime state, config, security, and app-wide infrastructure
- [../middleware.py](../middleware.py) — request hooks and security middleware
- [../routes](../routes) — route modules grouped by feature area

## 2. Architecture overview

The project is organized around a shared Quart app instance and a split route layout rather than a Blueprints-based structure.

### Core structural rule

The codebase explicitly keeps one shared application object and registers routes directly on it. This is visible in the split architecture notes described in [../docs/CLAUDE.md](../docs/CLAUDE.md) and is reflected in the actual code:

- [../core.py](../core.py) defines the shared Quart app and central runtime objects
- [../middleware.py](../middleware.py) registers the hooks in the required order
- [../routes](../routes) each expose feature routes with plain @app.route decorators
- [../app.py](../app.py) imports those modules so their route handlers register on the same app

This design is important because many checks in the project assume route names, endpoint names, and auth rules remain stable across modules.

### Layer map

| Layer | Main files | Responsibility |
|---|---|---|
| Boot and composition | [../app.py](../app.py), [../dev_server.py](../dev_server.py), [../prod_server.py](../prod_server.py), [../protocol_manager.py](../protocol_manager.py) | Launch web server and protocol services |
| Shared runtime | [../core.py](../core.py), [../config.py](../config.py), [../paths.py](../paths.py), [../database.py](../database.py) | Config, paths, DB, auth primitives, shared objects |
| Security/request flow | [../middleware.py](../middleware.py), [../auth.py](../auth.py) | Session validation, CSRF, CORS, auth and request posture |
| Feature routes | [../routes](../routes) | UI endpoints, downloads, previews, admin actions |
| Storage + indexing | [../storage.py](../storage.py), [../file_monitor.py](../file_monitor.py), [../search_index.py](../search_index.py), [../file_index.py](../file_index.py) | Filesystem scan, live updates, indexing |
| Versioning | [../version_engine.py](../version_engine.py), [../version_history.py](../version_history.py) | Snapshot/version management |
| Alternate protocols | [../webdav_server.py](../webdav_server.py), [../sftp_server.py](../sftp_server.py), [../ftp_server.py](../ftp_server.py), [../smb_server.py](../smb_server.py) | Protocol listeners beside the browser app |
| Utilities | [../tools](../tools), [../helpers](../helpers) | Admin utilities and support modules |
| Frontend | [../templates](../templates), [../static](../static) | Browser UI, CSS, JS, static assets |

## 3. Startup and boot sequence

The application boot path is intentionally explicit and side-effect aware.

### 3.1 Boot path

1. [../core.py](../core.py) runs first.
2. It calls ensure_dirs() from [../paths.py](../paths.py) before the rest of the app creates files.
3. It imports and initializes shared objects such as session secret, logging, file monitor, search index, and signal/event systems.
4. [../middleware.py](../middleware.py) is imported so request hooks are registered.
5. Feature route modules under [../routes](../routes) are imported in a fixed order in [../app.py](../app.py).
6. Startup cleanup and assembly workers are initialized once via initialize_cleanup().
7. [../prod_server.py](../prod_server.py) or [../dev_server.py](../dev_server.py) starts the main server.
8. [../protocol_manager.py](../protocol_manager.py) launches alternative protocol servers as needed.

### 3.2 Why this matters

The project has been carefully structured to avoid circular imports and to preserve import-time order. Several modules intentionally run initialization logic during import, so a change in import ordering can break the app in subtle ways.

Examples include:

- [../core.py](../core.py) sets up app-level state, logging, and the security config
- [../database.py](../database.py) lazily bootstraps SQLite tables and encryption state
- [../paths.py](../paths.py) resolves storage directories from storage_config.json
- [../version_history.py](../version_history.py) and the search/index monitor are initialized in the core startup path

## 4. Configuration and environment

The project centralizes configuration in [../config.py](../config.py) and path config in [../paths.py](../paths.py) plus [../storage_config.json](../storage_config.json).

### 4.1 Main config file

[../config.py](../config.py) defines:

- HTTP port, host, chunk upload size, max content length
- feature toggles for ffmpeg, libvips, search indexing
- preview and compression settings
- WebDAV, FTP, SFTP, and SMB settings
- version engine configuration
- default directory locations for DB, cache, HLS, images, and version storage

### 4.2 Path logic

[../paths.py](../paths.py) is the single source of truth for database and cache directory resolution. It reads and writes [../storage_config.json](../storage_config.json) without requiring the app to be running.

Key ideas:

- the default DB directory is under the project root in db/
- the default cache directory is under the project root in cache/
- directory locations can be moved outside the web root for production safety
- functions like get_db_dir(), get_cache_dir(), set_db_dir(), and set_cache_dir() are used widely

This separation matters because the project is designed to keep sensitive state like database files and encryption keys out of the served web directory where practical.

### 4.3 Server config

[../server_config.json](../server_config.json) stores runtime settings for the HTTP app and protocol listeners. It covers items like:

- port bindings
- session lifetime
- HLS thresholds
- feature toggles
- protocol enablement
- preview/compression settings

## 5. Authentication and sessions

Authentication is intentionally SQLite-based and not file-based.

### 5.1 Auth module

[../auth.py](../auth.py) is a thin layer over the database auth API. It provides:

- check_login()
- get_role() (remembered per request since 5.44)
- request_is_logged_in() (5.44: `is_logged_in()` answered once per request; the hooks and `login_required` use it)
- forget_request_auth() (drops both per-request memos; called by login_user and logout_user)
- login_user()
- logout_user()
- revoke_current_session()
- current_user()
- is_logged_in()

The check is tied to the current server token stored in SQLite, so sessions can be invalidated centrally when the app token changes.

### 5.2 Session flow

The app uses Quart session state and stores a server token in the DB. This ensures:

- users are not trusted by stale session data
- deleted users are automatically logged out
- server token rotation invalidates active sessions
- login state is checked consistently by middleware and route handlers
- a logged-out session stays logged out: logout records the session id in the `revoked_sessions` table and `is_logged_in()` refuses it (5.17)

### 5.3 Logout and the Clear-Site-Data header

[../routes/login.py](../routes/login.py) sends `Clear-Site-Data: "executionContexts"` only, on `GET /login` and on `/logout`, and only over HTTPS. The directives `"cache"`, `"cookies"`, `"storage"` and `"*"` were removed in 4.89: in the owner's measurements they made the browser do synchronous clearing work (a 3-15 s logout), while `"executionContexts"` takes 0.1-0.5 s. Do not add them back without measuring logout time again in Chrome and Edge.

What replaced them: the cache policy is `Cache-Control: no-cache, no-store, must-revalidate` (set by the logout route and, for every authenticated response, by `after_request` in [../middleware.py](../middleware.py)); the session and cookies are removed by `session.clear()` and `delete_cookie()` in the logout route. Not cleared any more: `localStorage`, `sessionStorage` and IndexedDB of the site, so keep secrets out of them.

**Logout ends the session on the server (5.17).** The session is a signed cookie, so `session.clear()` only empties the copy in the browser that logs out; a copy of the old cookie stays valid until it expires. The logout route therefore calls `revoke_current_session()` in [../auth.py](../auth.py) BEFORE `session.clear()` (the id lives in the session); it stores `session["session_id"]` in the `revoked_sessions` table ([../database.py](../database.py), `db.revoke_session()`), and `is_logged_in()` refuses any cookie whose id is listed there (`db.is_session_revoked()`). Rules: `/login` must keep setting a fresh `session["session_id"]` (a session without an id cannot be ended); any new code path that ends a session on purpose (an admin kick, a password change) should call `revoke_current_session()` or `db.revoke_session(id)` too; `revoke_current_session()` never raises, so a database problem cannot block a logout. Rows are purged after 30 days (`REVOKED_SESSION_KEEP_SECS`), which must stay longer than `PERMANENT_SESSION_LIFETIME`. The unit tests are `tests/unit/test_session_revocation.py`; the end-to-end check is `tests/application/test_login.py`.

After changing login or logout code, test by hand: log in, open a folder, log out, press Back (private data must not appear) and time `GET /logout` in the browser's network tab.


## 6. Database and persistence

The main persistence layer is [../database.py](../database.py).

### 6.1 Database responsibilities

It manages:

- users table
- server token table
- share_links and share access request tables
- lazy creation of the encryption key and session secret
- Fernet-based encryption of sensitive fields
- optional NT hash generation for SMB/NTLM compatibility

### 6.2 Lazy initialization

The module is designed to avoid creating paths or files on import. It only initializes on the first real database query or write. This choice matters because tools like setup scripts and config loaders need to import database logic without immediately creating directories.

### 6.3 Separation of secrets

Sensitive fields are encrypted at rest, and the app does not trust raw file state alone. The code intentionally separates:

- the password hash for web auth
- the NT hash for SMB authentication
- the session secret and app key store

## 7. Storage, files, and cache

Filesystem behavior is centered around [../storage.py](../storage.py), [../file_monitor.py](../file_monitor.py), [../file_index.py](../file_index.py), and [../search_index.py](../search_index.py).

### 7.1 Storage layer

[../storage.py](../storage.py) is the main helper for filesystem operations and directory queries, including:

- listing directories
- safe deletion and cleanup
- copying, moving, and rename operations
- file downloads and view paths
- bulk ZIP creation logic
- root guard and directory safety checks

### 7.2 File monitor

[../file_monitor.py](../file_monitor.py) is one of the most important runtime pieces. It tracks filesystem changes, debounces events, reconciles state, and updates the in-memory index.

It is responsible for:

- watching storage changes
- maintaining folder counters and directory metadata
- detecting create / delete / move / modify events
- reconciling against real disk state
- updating JSON caches and index data structures

This subsystem is what makes the browser UI feel live without constant full re-scans.

### 7.3 File index and cache JSON

[../file_index.py](../file_index.py) manages cached folder metadata. The JSON cache is intended to speed up directory listings and avoid repeated full scans while still allowing reconciliation against the real disk.

Key behaviors include:

- threshold-based indexing for large folders
- validation of cached records
- live refresh on mismatch or staleness
- directory-level metadata tracking

### 7.4 Search index

[../search_index.py](../search_index.py) provides the deep-search capability. It maintains a searchable internal structure built from filesystem data and supports:

- index build and full rebuild
- incremental update on filesystem changes
- fallback to filesystem walk when the index is not ready or a query fails
- result counting and search execution

This subsystem is important because deep search is intentionally backed by a specialized index rather than a naive path walk for every query.

## 8. Route organization

The route modules live under [../routes](../routes), each grouped by a feature area.

### 8.1 Route modules

The main route files are:

- [../routes/admin.py](../routes/admin.py) — admin and cache maintenance endpoints
- [../routes/files.py](../routes/files.py) — browsing, downloads, bulk actions, moves, copies, deletes
- [../routes/hls.py](../routes/hls.py) — adaptive video streaming and transcode orchestration
- [../routes/image_preview.py](../routes/image_preview.py) — image preview and WebP conversion
- [../routes/login.py](../routes/login.py) — login / logout / session checks / CSRF token
- [../routes/previews.py](../routes/previews.py) — Office and archive preview endpoints
- [../routes/shares.py](../routes/shares.py) — share links and access controls
- [../routes/site_meta.py](../routes/site_meta.py) — robots.txt, security.txt, sitemap endpoints
- [../routes/stats.py](../routes/stats.py) — storage stats, SSE, search, health checks, polling
- [../routes/uploads.py](../routes/uploads.py) — chunked uploads and background assembly
- [../routes/versions.py](../routes/versions.py) — version-history APIs and recovered-file downloads

### 8.2 Route conventions

The route modules follow a shared pattern:

- they import the shared app from [../core.py](../core.py)
- they do not define their own app instance
- they use plain quart decorators directly on the shared app
- they do not import each other, with two documented exceptions enforced by `tests/smoke.py` (check 7): [../routes/admin.py](../routes/admin.py) imports the HLS and image-preview cache helpers, and [../routes/uploads.py](../routes/uploads.py) imports the share-pruning helper from [../routes/shares.py](../routes/shares.py)
- they rely on middleware for auth, CSRF, and CORS checks
- **no blocking disk, subprocess or database call on the event-loop thread (5.44).** An `async def` (route, hook, `login_required`) runs on the one thread that serves every request, so a `shutil.rmtree`, an `os.walk` / `os.listdir`, a `storage.<helper>` that touches many files, or a SQLite open stops every other request, the receiving of uploads and the SSE streams for as long as the disk takes. Move the work into a plain sync function and call it with `await asyncio.to_thread(fn, plain_value, ...)`: pass the callable UNCALLED (`asyncio.to_thread(storage.x())` runs `x` on the loop and hands over its result), pass plain values (strings, lists), never `request`, `session` or `g`, and let the worker return plain values; the response is built on the loop afterwards. A single `os.path.exists` / `getsize` is not blocking in this sense and stays inline; a loop over many paths is, so it goes into ONE worker call, not one call per path. Cheap in-memory lookups (the file monitor index through `storage.get_dir_info_indexed()`) stay inline: a thread hop costs more than the lookup. **Long walks** (`storage.get_storage_stats`, the share page's `_dir_size`, the live part of `dir_info`) go through `await run_walk(fn, plain_value)` from `helpers/walk_executor.py` instead of `asyncio.to_thread`: a pool of 2 threads of their own, so a few walks at the same moment never queue up the default pool that also serves logins, listings, chunk writes and downloads. **A long loop in a worker thread that must let the event loop breathe paces its handoff by TIME, never per item** (`file_monitor._WalkYielder`: at most one 1 ms nap per 25 ms; sleeping after every folder cost 79% of a measured walk). **Never wait for a thread job by parking a pool worker** (`to_thread(thread.join, 60)`, `to_thread(event.wait, 60)`): resolve an asyncio future from the job's thread with `loop.call_soon_threadsafe` and `await asyncio.wait_for(future, timeout)` (see `routes/image_preview.py`). **A sync generator pulled in a worker (`next` through `to_thread`) is closed under the same lock as the pulls, in a thread, never by `.close()` on the loop** (`routes/versions._stream_version_blocks`). A worker thread must not hold a `threading.Lock` that the loop also takes while it does disk work (the `ChunkTracker` lock is taken only for short in-memory steps since 5.44; see `core.py`), and every `threading.Thread` gets a `name=`. A justified exception carries `# blocking-ok: <reason>` on the call line. `tests/unit/test_async_handlers_no_blocking.py` enforces this with `ast`: a new offender fails the test, and a listed one that was fixed must be deleted from its `KNOWN` table (the ratchet only goes down; since 5.44 it holds only the database calls of the hooks and handlers, plan task T9).

## 9. Request lifecycle and middleware

The request lifecycle is centralized in [../middleware.py](../middleware.py).

### 9.1 Middleware responsibilities

This file handles:

- request timing and logging
- CORS preflight handling
- CSRF protection
- session validation
- response header adjustments
- **who is logged in is looked up once per request (5.44):** every lookup is a SQLite open ON the event loop (`database._connect()`), and a request used to make up to 10 of them before its handler ran. `validate_session`, `before_request`, `after_request`, `login_required` and the handlers call `auth.request_is_logged_in()` and `auth.get_role()`, which remember their answer on Quart's `g` for ONE request. A True answer is kept together with the four session values it was computed from, so a login, a logout, a `session.clear()` anywhere or a changed session id makes the next call check again from scratch; a False answer is never kept. Do NOT call the plain `auth.is_logged_in()` in a hook or handler (three opens each time; it stays only as the primitive and for its own tests), and do not add another database call to a hook without a reason: an open slower than 0.1 s is logged as `Slow SQLite open` with the thread name, which is how a slow open is told apart from many fast ones. Still on the loop by design: the remaining opens (about 4 per request); offloading them with `to_thread` adds a hop to every request and puts logins behind the default pool, so it waits for that log line (plan T9, decision pending).
- error handling and template filtering

The project places these in a single module rather than scattering them through feature routes. That is a deliberate design choice to keep the request lifecycle consistent and predictable.

### 9.2 Security posture

Middleware and config implement an intentionally locked-down request model:

- origin allowlist checks for local and trusted domains
- no broad wildcard CORS by default
- secure-cookie logic tied to HTTPS detection
- a strict session check path
- CSRF token enforcement on sensitive state-changing routes

## 10. Upload, chunking, and assembly

Large file handling is managed through the upload system.

### 10.1 Upload routes

[../routes/uploads.py](../routes/uploads.py) handles:

- chunk upload endpoints
- cleanup of stale chunks
- canceled uploads
- upload status polling
- assembly status and protected assembly jobs
- background assembly workers

### 10.2 Queue system

[../core.py](../core.py) defines the assembly queue used to track upload jobs. It keeps:

- active jobs
- recent completed jobs
- session-based tracking
- status state such as pending, processing, completed, and error

This allows the browser to monitor a large upload rebuild without blocking the main request loop.

### 10.3 Upload ids and chunk keys

The browser names each upload with an id (`generateFileId` in [../static/js/index.js](../static/js/index.js): `fid_<counter>_<file size>_<16 random hex>`). That id is only unique inside one page, so the server never uses it as it is: [../routes/uploads.py](../routes/uploads.py) builds a **chunk key** `<first 16 hex of sha256(session_id)>_<client id>` (`_chunk_key`) and uses the key for the `.chunks/<key>/` folder, `chunk_tracker`, `assembly_queue` (`job.file_id` is the key), the metadata file, the cleanup and cancel routes, `/api/protect_assembly/<id>` and the status routes. Rules when touching this code:

- Any new code that takes an upload id from a request must go through `_valid_client_upload_id()` and `_chunk_key()`; never join a request value into a path or look it up in `assembly_queue` / `chunk_tracker` directly. A session without a `session_id` has no key.
- Responses and URLs carry the client id, not the key (`_client_file_id()` maps back); the front end does not know the key exists.
- The client id is at most 128 characters so the key stays within the 200 characters allowed by `storage.is_safe_chunk_id()`.
- Chunk folders of the same upload from older server versions have no prefix; the age-based cleanup removes them.

### 10.4 When the assembly starts

`/upload` calls `storage.chunks_complete(key, total_chunks)` after every saved chunk and queues the assembly when chunk files `0..total-1` are all present, in whatever order they arrived (the last chunk is checked first, so an in-order upload scans once, at its end). A retried chunk while the job is pending or processing queues nothing. `storage.assemble_chunks(..., total_chunks)` re-verifies the announced count, so a folder with a different number of chunk files is never published. Pure helpers of this section are covered by `tests/unit/test_upload_chunk_keys.py`, the behaviour by `tests/application/test_upload_integrity.py`. Since 5.38 `storage.assemble_chunks` writes the chunks to a hidden `.assembling_<hex>.part` file in the target folder, checks its size and publishes it with `os.replace`, so no reader ever sees a partial file and a failed assembly never touches an existing file of the same name (it removes only the temp file); keep any change to the assembly atomic, and keep the temp file in the target's folder.

### 10.5 Recovering uploads at startup

`detect_ready_assemblies()` in [../routes/uploads.py](../routes/uploads.py) re-queues uploads that were complete when the server stopped. A folder under `.chunks/` is assembled only when it has a usable `.metadata` (`_read_upload_metadata()`: non-empty `filename`, string `dest_path`, integer `total_chunks >= 1`; `/upload` writes it only once every chunk is on disk), the destination passes `storage.is_safe_path()`, and `storage.verify_chunks_complete(id, total_chunks)` finds exactly that many sequential chunks. Folders without metadata, or with a different chunk count, are skipped and removed later by the age-based orphan cleanup; never assemble "whatever is there" (5.17: that used to publish truncated `recovered_file_...` files). Covered by `tests/unit/test_recover_uploads.py`.

### 10.6 Upload performance (5.41)

What `/upload` does per chunk, and the rules that keep it fast. Background and the measurements are in CLAUDE.md 5.41 and `TESTING_STRATEGY.md` section 16.

- **Everything that touches many files runs in a worker thread (5.44, section 8.2).** `storage.chunks_complete` (up to `total_chunks` stats, after EVERY chunk), `storage.cleanup_chunks`, `/cleanup_chunks`, `/admin/cleanup_chunks`, the `.chunks` listing of `/admin/chunk_stats`, the abandoned-upload cleanup of `middleware.before_request` and the chunk cleanup of `/logout` all go through `asyncio.to_thread`; the cleanup in the generic `except` of `upload()` is wrapped so it can never replace the error text the browser shows.
- **No synchronous chunk I/O in the handler.** Reading the uploaded piece (`chunk.read()`) and writing it (`storage.save_chunk`) run in a worker thread: `_read_and_save_chunk()` through `asyncio.to_thread()`. On the event-loop thread a 10 MB read and write stops every other request, and the receiving of other uploads' bodies, for as long as the disk takes. `tests/unit/test_upload_body_paths.py` reads `upload()` with `ast` and fails if `storage.save_chunk` or `chunk.read` come back into it.
- **The form is parsed once**, through `_upload_form_and_files()`; do not add `await request.form` / `await request.files` to the handler.
- **`UPLOAD_CHUNKS_IN_MEMORY` (default True since 5.43; False before)** parses a chunk-sized multipart body in RAM (`helpers/upload_perf.parse_form_in_memory`) instead of Quart's spooled temp file in the system temp folder. It applies only when the CSRF token came in a header (otherwise the CSRF hook has already read the form and the body is gone), the body has a known `Content-Length` of at most `CHUNK_SIZE` + 1 MiB and is `multipart/form-data`; anything else keeps Quart's parser, so RAM per request stays bounded. A value already saved in `server_config.json` wins over a changed default (the loader uses the module value only as the `config.get()` fallback), so a default change reaches an existing install only through the menu (Server Settings > 14) or the JSON; say so in the sync note. On this path `_upload_form_and_files(in_memory, timer)` also tells the stage timer how the stage divides (`StageTimer.detail()`: `body arrived`, `parse`); Quart's own parser reads and parses while the body arrives, so it cannot be divided and reports nothing. Do not rename the stages `receive+parse` / `read+save`: `parse_timing_lines()` and the tests read them.
- **`BODY_TIMEOUT` (default 600 s, 0 = no limit)** is the time Quart gives one request body to arrive AND be parsed; see section 19 (Quart timeouts). Quart's own default of 60 s cut off a 10 MB chunk that needed a minute and the browser, which has no per-chunk retry, then ended the whole upload.
- **`UPLOAD_TIMING_ENABLED` (default False)** logs the stages of every chunk (`role`, `receive+parse`, `read+save`, with `read` / `save` measured in the worker thread) and an average every 20 chunks, and starts an event-loop lag probe (with the first upload request, not a startup hook: `tests/smoke.py` check 5 keeps lifecycle hooks in `middleware.py`; median / p95 / max every 30 s, a warning for a stall of half a second). The lines are in the server log; they cost nothing when the flag is off. A RAM-parsed chunk's line adds `(body arrived X s, parse Y s)` before the total (5.43).
- **The reconcile walk after an assembly waits for running uploads.** `assembly_worker` used to call `_trigger_reconcile()` whenever the assembly queue drained, so a multi-file upload walked the whole tree (one `os.stat` per file) between files. It now goes through `_reconcile_after_uploads` (`IdleDeferral`): while `chunk_tracker.active_uploads` is not empty it re-checks every 5 s, and it runs after 10 minutes at the latest (an abandoned upload stays tracked for up to 30 minutes). Never call `_trigger_reconcile()` directly from this module (a test guards it).
- **The Version Engine never tracks `.chunks`** (`_ALWAYS_EXCLUDED_DIR_NAMES` in `version_engine.py`), whatever `VERSION_EXCLUDE_DIRECTORIES` says.

## 11. Previewing, media conversion, and HLS

The app supports preview generation for media and document types.

### 11.1 HLS

[../routes/hls.py](../routes/hls.py) handles adaptive video streaming and ffmpeg-based transcoding. It creates HLS playlists and segment files under the configured HLS cache directory.

### 11.2 Image preview

[../routes/image_preview.py](../routes/image_preview.py) handles image conversion and previews, especially for large images that are compressed to WebP for browser delivery.

### 11.3 Office and archive preview

[../routes/previews.py](../routes/previews.py) handles previews for office documents and archive content. The file uses background threading when needed so heavy preview generation does not freeze the event loop.

## 12. Version history and restore workflow

The versioning subsystem is split between [../version_history.py](../version_history.py) and [../version_engine.py](../version_engine.py), and is surfaced through [../routes/versions.py](../routes/versions.py).

### 12.1 Purpose

This subsystem tracks file snapshots and offers restore operations. It is designed to protect against accidental overwrites and to preserve change history for files under tracked directories.

### 12.2 Notes for maintainers

The app enables version tracking through config values in [../config.py](../config.py), and the engine is a separate process/service model rather than a simple in-memory tracker. It is intentionally isolated from the main browser routes to reduce event-loop contention.

## 13. Protocol servers

The project can expose file access through alternate protocols in addition to the browser UI.

### 13.1 Protocol manager

[../protocol_manager.py](../protocol_manager.py) is the central supervisor for WebDAV, SFTP, FTP, and SMB. It determines which services are enabled and decides how they are started.

### 13.2 Server files

- [../webdav_server.py](../webdav_server.py) — WebDAV listener
- [../sftp_server.py](../sftp_server.py) — SFTP listener
- [../ftp_server.py](../ftp_server.py) — FTP and FTPS listener
- [../smb_server.py](../smb_server.py) — SMB listener and Windows networking integration

### 13.3 Operational pattern

Some services are started as background threads in-process; WebDAV is separated into its own process for resilience and recovery, as described in the module comments and the architecture notes. This is a deliberate choice to avoid a wedged WebDAV loop taking down the entire app. The Version Engine ([../version_engine.py](../version_engine.py)) is also a separate OS process, started by the launcher (`version_engine.start()` in [../dev_server.py](../dev_server.py) / [../prod_server.py](../prod_server.py)) independently of `protocol_manager.py`.

**Shutdown contract (4.99).** Every separate OS process the server spawns must die with it, however the server ends: (1) graceful: `./manage.sh stop` creates `.manage_pids/prod.stop` / `dev.stop` (prod also gets SIGTERM on POSIX), the launcher shuts down like the first Ctrl+C and its `finally:` block calls `protocol_manager.stop_all()` and `version_engine.stop()`; (2) forced: after `STOP_GRACE_SECS` (default 45) `manage.sh` kills the whole process tree (`taskkill //F //T`, or `kill -9 -- -PGID`); (3) sweeps: pid files plus the WebDAV port sweep and a `version_engine.py --worker` command-line sweep; (4) orphan guard: the children watch `CLOUDINATOR_PARENT_PID` via [../helpers/parent_watch.py](../helpers/parent_watch.py) and exit if the parent vanishes. A new child process must be added to all four.

## 14. Front-end structure

The frontend is served directly from [../templates](../templates) and [../static](../static).

### 14.1 Templates

The main browser pages include:

- [../templates/index.html](../templates/index.html)
- [../templates/login.html](../templates/login.html)
- [../templates/shared.html](../templates/shared.html)
- [../templates/404.html](../templates/404.html)

### 14.2 Frontend behavior

The browser logic is mostly in JavaScript files under [../static/js](../static/js), especially:

- [../static/js/index.js](../static/js/index.js) — main file manager logic
- [../static/js/login.js](../static/js/login.js) — login page behavior
- [../static/js/shared.js](../static/js/shared.js) — public share page behavior
- [../static/js/bg_audio.js](../static/js/bg_audio.js) — background music behavior
- [../static/js/viewer.mjs](../static/js/viewer.mjs) and related viewer assets — preview viewer logic

The app uses external static assets and hashed resource integrity checks for the browser-facing frontend, which is why the project includes SRI validation tooling.

**`fetch()` on the login page (5.43).** A logged-out visitor's request to a protected URL is answered with a redirect to `/login` (301; only a request that asks for JSON gets 401, see `login_required` in [../core.py](../core.py)). A default `fetch()` follows it and sees the login page itself as `ok`, so a status-only question ("am I logged in?") must use `redirect: 'manual'` (the answer is `type: 'opaqueredirect'`, `ok` is false) and should `response.body?.cancel()` the body it will not read: Chromium reports a request as finished only once its body is read or dropped, which is what kept the browser smoke from ever settling. `checkAuthenticationStatus()` and `checkAndRedirectIfLoggedIn()` in `login.js` follow this (the second one used to reload the login page and wipe what the visitor had typed when the tab became visible again); [../tests/unit/test_login_js.py](../tests/unit/test_login_js.py) fails when a `fetch(` in `login.js` lacks `redirect: 'manual'`. `index.js` still has fetches that read only `response.ok` and never the body: harmless for users, and the reason the browser smoke's `Watcher` treats an answered fetch/XHR as finished.

**Connection status toast (5.43, seventh delivery).** The browser's `offline` event is only a hint: Edge/Chromium raise it on idle tabs while the network works. `index.js` therefore never shows the "Connection lost" toast from the event alone: the `offline` listener waits `OFFLINE_CONFIRM_DELAY_MS` and asks the server with `_serverReachable()` (`/api/speedtest/ping`, `redirect: 'manual'`, `AbortController` timeout, body cancelled; any HTTP answer means reachable, only a network error or the timeout means lost). "Connection restored" is shown only when "lost" was (`_offlineToastShown`). A new network-status message must use the same probe, not `navigator.onLine`. An `Uncaught TypeError` from a `VM<n>` script with minified names (for example `reportAllChanges`, a `web-vitals` option) is an injected extension script, not project code: check with an InPrivate window before searching the repo.

**Upload conflict decisions (5.43, sixth delivery).** The file-exists dialog (`_promptOverwrite`) is reached only through `_resolveFileConflict(item, name, destPath)` in `index.js`. An "all" answer is stored in `_overwriteDecisions` under `item._groupId` (folder upload) or `_LOOSE_CONFLICT_KEY` (plain files), and concurrent conflicts of one key are chained through `_conflictPromptTail`, so they never open stacked dialogs. Never read or write `_overwriteDecisions` directly from `uploadSingleFile()`, and clear both maps at the start of a batch (`startUpload()`). A new upload path that can answer 409 must call the resolver, not `_promptOverwrite`.

## 15. Security and hardening notes

### 15.1 CSP and inline script policy

The project is security-conscious about browser policy. The inline style hash and CSP configuration are discussed in [../core.py](../core.py), and the app intentionally avoids relying on unsafe inline script patterns where practical.

### 15.2 SRI validation

The project includes a validator for static asset integrity checks. See [../tools/sri_validator.py](../tools/sri_validator.py) and the manage.sh entry for validate-sri. An SRI hash is computed over the raw bytes of the file, so the repository is LF everywhere (see 19.1); `python tests/qa.py ci` runs the check on GitHub, and a stale hash fails that run. After editing anything under `static/` or `templates/` run `./manage.sh validate-sri --fix` and commit the templates together with the asset.

### 15.3 Security.txt and robots

The app exposes metadata endpoints for crawlers and security scanners through [../routes/site_meta.py](../routes/site_meta.py) and the static security file under [../static/.well-known/security.txt](../static/.well-known/security.txt).

### 15.4 Client IP and the login lockout

`get_client_ip()` in [../core.py](../core.py) feeds the login lockout (`RateLimiter`) and the request logger. It reads `CF-Connecting-IP` (then `X-Forwarded-For`) **only when `request.remote_addr` is loopback** (`_TRUSTED_PROXY_NETWORKS`; cloudflared connects from loopback); every other peer is identified by its real address, so a client that reaches the port directly cannot choose its own lockout bucket. A reverse proxy on another machine must be added to `_TRUSTED_PROXY_NETWORKS`, otherwise all its users share one bucket. Tests connect from loopback, so their fake `CF-Connecting-IP` header still works (18.x test rules); the rule itself is covered by `tests/unit/test_client_ip_trust.py`. `webdav_server.py` has its own `_client_ip()` for its audit log (it is not a lockout); since 5.21 it applies the same rule (headers only from a loopback `REMOTE_ADDR`, helper `_is_loopback_peer()`), covered by `tests/unit/test_webdav_client_ip.py`. `RateLimiter` methods take an optional `key` (default: the client IP); `share_passkey_limiter` is a second instance used by `/shared/<token>/passkey` with the key `"<ip>|<token>"` (5 wrong passkeys in 60 s lock that client out of that link for 300 s, answered with 429 and `Retry-After`; covered by `tests/application/test_share_hardening.py` and `tests/unit/test_rate_limiter_keys.py`).

### 15.5 Protocol servers: permission rules (5.29 to 5.31)

- **Read the role LIVE.** A role (and the existence of the account) is read from the database at the moment of each permission decision, never once at login or tree connect: `ftp_server.py` on every command, `sftp_server.py` through `_current_role()` (also on every write to an open handle), `smb_server.py` through `_apply_role()` called by the CREATE / SET_INFO / WRITE guards, `webdav_server.py` through the 30-second `_AuthCache` (the only cache; keep it short). Fail CLOSED: an unknown user or a lookup error means `readonly`.
- **No session without credentials.** `smb_server._install_guest_block()` turns impacket's guest and anonymous sessions into `STATUS_LOGON_FAILURE`; do not remove it when upgrading impacket without re-running `tests/protocols/test_smb_protocol.py`.
- **Containment uses path components, not string prefixes.** impacket's `isInFileJail` (a `commonprefix` check) is replaced by `smb_server._is_in_file_jail` (`commonpath` + `realpath` + `normcase`). Never write `startswith(root)` or `commonprefix` for a containment check: `/data/storage_backup` starts with `/data/storage`.
- **Hypercorn binds.** `webdav_server._listener_binds()` decides `bind` / `insecure_bind`: `insecure_bind` is only honoured when TLS is configured, so a plain-only listener goes into `bind`.
- Branch rules: `main` and `dev` require a pull request and the checks `smoke + check` and `behavioral tests` (`docs/rulesets/`); never rename those two jobs in `tests.yml`.
- Every rule above has a test in `tests/protocols/` (or `tests/unit/test_webdav_listener_binds.py`); a protocol change needs a restart of the server.

## 16. Utilities and project tooling

The repo includes support scripts under [../tools](../tools) and helper modules under [../helpers](../helpers).

### 16.1 Utility scripts

Examples include:

- [../tools/manage_users.py](../tools/manage_users.py) — create and manage users
- [../tools/setup_storage.py](../tools/setup_storage.py) — configure storage paths and DB/cache directories
- [../tools/reset_db.py](../tools/reset_db.py) — reset DB state
- [../tools/revoke_sharing.py](../tools/revoke_sharing.py) — remove or revoke share links
- [../tools/smb_setup.py](../tools/smb_setup.py) — SMB preparation
- [../tools/version_manage.py](../tools/version_manage.py) — versioning operations
- [../tools/purge_missing_versions.py](../tools/purge_missing_versions.py) — frees the storage of versions whose file no longer exists (`./manage.sh purge-versions`, menu 31)
- [../tools/kick_sessions.py](../tools/kick_sessions.py) — session invalidation
- [../tools/sri_validator.py](../tools/sri_validator.py) — integrity validation

### 16.2 Helper modules

The helper folder contains utility modules with leaf-style responsibilities:

- [../helpers/net_utils.py](../helpers/net_utils.py)
- [../helpers/parent_watch.py](../helpers/parent_watch.py)
- [../helpers/lanman_guard.py](../helpers/lanman_guard.py)
- [../helpers/hypercorn_ssl_fix.py](../helpers/hypercorn_ssl_fix.py)
- [../helpers/ssl_cert.py](../helpers/ssl_cert.py)

These are designed to stay lightweight and side-effect minimal. They may import other root modules such as `logging_setup`, `paths` and `config`, but never `app`, `core`, `middleware`, `routes`, `tools` or `tests`; `tests/smoke.py` (check 7b) and `tests/check.py` (layering) enforce this.

## 17. server management and shells

The repo includes shell orchestration and deployment scripts such as:

- [../manage.sh](../manage.sh)
- [../termux_setup.sh](../termux_setup.sh)
- [../setup_pymodules.sh](../setup_pymodules.sh)

These are not the app logic itself, but they are critical for development, installation, and service control on Windows, Linux, and Android/Termux.

## 18. Testing philosophy and validation

> **`docs/TESTING_STRATEGY.md` is a LOCAL planning document since 5.44.3** (all testing phases are done; it is in `.gitignore` and was removed from git with `git rm --cached docs/TESTING_STRATEGY.md`). Do not assume it is on GitHub, do not link to it from a committed document, do not `git add -f` it and do not record a fact only there (the facts live in `docs/CLAUDE.md`, in this section, in the test docstrings and in `python tests/qa.py --help`). The owner attaches it by hand when a chat needs it. Check which state applies with `git ls-files docs/TESTING_STRATEGY.md` (a path printed = tracked). If it is in `.gitignore` but still tracked, `git rm --cached docs/TESTING_STRATEGY.md` once.

The project's automated checks are static: they read the source and do not start the app. Examples include:

- [../tests/smoke.py](../tests/smoke.py)
- [../tests/check.py](../tests/check.py)
- [../tests/smoke_routes.json](../tests/smoke_routes.json)

The project’s internal notes in [../docs/CLAUDE.md](../docs/CLAUDE.md) describe a strong emphasis on:

- static syntax validation
- pyflakes checks
- route registration verification
- import resolution and layering rules (checked statically; `tests/smoke.py` deliberately never imports `app`, because a real import runs the startup cleanup)
- ensuring route names and auth rules remain consistent after refactors

This is especially important because the app is intentionally designed as a single app object with many route modules.

Since 5.00 there is also a behavioral **pytest** suite next to the static checks (Phase 1 of the test plan: `tests/conftest.py`, `tests/unit/`, `tests/application/`, run through `python tests/qa.py`). It is deliberately built around two rules:

- **Never import the application in the pytest process.** `paths.py` and `config.py` read their JSON next to the code and `core.py` starts the file monitor, search crawler and cleanup threads at import. The suite therefore copies the source tree into a temporary folder, writes fresh `storage_config.json` / `server_config.json` that point inside it (all protocols, search, ffmpeg, libvips and the Version Engine off, ephemeral port), checks that every data path resolves inside that folder, and starts `dev_server.py` there as a subprocess (stopped through the same `.manage_pids/dev.stop` file `manage.sh` uses). Tests talk to it over HTTP. In-process imports from the real tree are limited to side-effect-free leaf modules (today only `paths`); an autouse guard in `tests/conftest.py` fails any test that imports another root module.
- **Test files in subfolders are not exempt from `smoke.py`.** The `tests/` exemption in checks 4, 5 and 6b covers only files directly in `tests/`. A file in `tests/unit/` or `tests/application/` that contains `import app`, a quoted `url_for('x')` / `request.endpoint == 'x'` for an unknown endpoint, or a hook/route decorator fails the smoke test. Use literal URLs in tests.

Rules for application tests (`tests/application/`, written against the real app through `scratch_server`):

- Use `server.client()` or `server.login_as("qa_writer" | "qa_reader")` so every test has its own fake client IP (`CF-Connecting-IP`) and therefore its own login rate-limit bucket; never reuse a client across tests.
- Create throw-away accounts with `server.make_user(role)` and change the scratch database with `server.db(code, *args)` (`db` is `database.db`); never touch the real database.
- Fetch the CSRF token BEFORE invalidating a session: a request to the public `/csrf-token` runs the session hooks and clears the cookie of a deleted user.
- **Several threads through ONE `HttpClient`: fetch the CSRF token once, first (5.44.2).** `HttpClient.api()` calls `GET /csrf-token` before every non-GET request, and the application creates the token the first time it is asked for and keeps it in the signed session cookie (`core.py` `generate_csrf()`; `CSRFProtect._protect` compares by exact string). A burst of threads on a fresh session therefore asks for several tokens at once, the cookie jar keeps the last one and the others get `400 CSRF token missing or incorrect` (about 1 run in 10, always on one of the first requests; the first Ubuntu Nightly found it). A test that sends from several threads through one client calls `client.csrf_token()` before the burst (twice: the first authenticated request of a session also writes `session_id` into the cookie) and sends with `client.request(..., headers={"X-CSRFToken": token})`, like `_send_chunk(..., token)` in `tests/reliability/test_concurrency.py`; a browser does the same (one token from the page's `<meta>` tag, one shared refresh and one retry on a CSRF-shaped 400). One client per thread is also fine. A test that fails with that 400 under load is the client, not the upload routes: read the body first.
- **A concurrency test's failure message prints what is needed to find the cause (5.44.2).** `(number, status, full body)` of every reply that is not the expected one, and `server.log_tail()`; never `r.text[:120]` (it cut off the sentence that named the cause) and never only a list of status codes.
- A new public route must be added to `PUBLIC_ENDPOINTS` in `tests/application/test_authorization.py` on purpose (and to the public list in `validate_session`); a new mutating route belongs in `READONLY_REFUSED`.
- Test files cannot import `conftest`; repeat small constants or use a fixture.
- Slow or timing-sensitive tests are OPT-IN: `tests/performance/` (throttled download, speed baselines), `tests/reliability/` (the live Version Engine worker, concurrency, stop / crash / restart) and `tests/frontend/` (Playwright) skip themselves unless `CLOUDINATOR_SLOW_TESTS=1` is set (`CLOUDINATOR_SLOW_TESTS=1 python tests/qa.py layer reliability`; the nightly workflow sets it); never put a test that takes more than a few seconds in the default layers. Put the skip in a module-level `pytestmark` (`pytest.mark.skipif(os.environ.get("CLOUDINATOR_SLOW_TESTS") != "1", ...)`): a skipped test never starts its session fixture, so no server is launched. Wait for a background process (the Version Engine worker, an assembly) with a BOUNDED POLL on what the HTTP API or the disk shows, never a fixed sleep, and never read the scratch server's stdout for logic (it goes to a file and is block-buffered).
- **Test files must not register routes or lifecycle hooks, and no scratch `.py` file may sit in the repository.** `tests/smoke.py` scans the tests and the repository root too: an `@app.route` in a test is reported as a new route (check 11b), a second `upload` endpoint or `POST /upload` fails check 3, and `@app.before_serving` anywhere but `middleware.py` fails check 5. Use `app.test_request_context(...)` for a toy request, start a diagnostic from a request handler instead of a hook, and keep throw-away scripts (`quart_upload_reference.py`) outside the repository.
- **Browser tests (`tests/frontend/`, 5.43).** (1) Never `wait_until="networkidle"` or `wait_for_load_state("networkidle")`: these pages keep EventSource streams and a looping `<audio>` open, and an unread `fetch()` body keeps a request "open" in Playwright; use `load` plus `Watcher.wait_until_quiet(page)`, whose timeout message names every open request (method, type, URL, redirected-from, Accept, age, status). (2) A Playwright event handler is a Python function, lambda or bound method, never a built-in such as `set.add` (Playwright sets an attribute on the handler to wrap it; 5.43 fix1). (3) A fake of a third-party API in a throw-away check must send handlers and arguments through the real library's code path (`ImplToApiMapping.wrap_handler`), or it accepts what the real one rejects. (4) A 404 in the smoke test for a file that exists is the scratch copy: `COPY_SKIP` in `tests/conftest.py` skips a folder NAME at any depth, so a name in it hides every `static/` folder called that; only names no tested page requests belong there (`images`, `wasm`, `cmaps`, `iccs`, `standard_fonts`; `webfonts`, `audio` and `locale` were removed in 5.43). (5) A stale SRI hash shows up there as a console error "Failed to find a valid digest". (6) If a traceback shows source lines that do not match the file, clear `__pycache__`: `find tests -name __pycache__ -prune -exec rm -rf {} +`.
- **CodeQL reads the tests too.** `Potentially uninitialized local variable` is an ERROR and fails the PR's code-scanning check (set the variable before the `try` / loop that may skip it); `Explicit returns mixed with implicit` is a notice (a helper that returns inside a loop and then falls through to `pytest.fail(...)`: find with `next(..., None)` or `for ... else`, and keep ONE `return` at the end). Local proxy before pushing: `python -m pylint --disable=all --enable=inconsistent-return-statements,possibly-used-before-assignment,used-before-assignment,undefined-loop-variable <files>`. **The proxy does NOT reproduce the uninitialised-variable ERROR** (5.43: pylint is silent on `try: x = ... / except: pytest.skip(...)` then `yield x`, CodeQL is not, because `pytest.skip` / `pytest.fail` look like they can return): set the name BEFORE the `try` (`instance, problem = None, ""`, then test it after the `except`) and call `pytest.skip` / `pytest.fail` outside the `except`. A helper that polls and fails on timeout is `result = predicate()`, a `while not result and time.monotonic() < deadline:` loop, `if not result: pytest.fail(...)`, then ONE `return result`.
- **Opt-in tests must also run in Termux (Android).** Termux is a supported platform and the slow tier may be run there by hand: use `tmp_path` / the scratch fixtures (never a literal `/tmp` or a Windows path), small payloads (hundreds of KB, not tens of MB, unless the test is about size), bounded polls instead of fixed sleeps, loose time bounds that catch a blocked event loop (seconds) rather than rank machines, no `psutil`, `fork` or Windows-only calls, and when a burst or a window matters (the monitor's burst counter) create the files FIRST and fire the events afterwards in a tight loop so slow phone storage cannot stretch them over the window.
- **Do not reformat a literal that another test reads as text.** `tests/unit/test_qa_audit.py` and `test_qa_coverage.py` read the `choices=[` list of `tests/qa.py` as text (`audit` must be within its first 80 characters and `"coverage"]` within 90), so a new mode is appended with `+ [...]`; putting it inside the list makes Black explode the list and fails both tests.
- **The suite must give the same verdict on the standard and the free-threaded build.** Never assume `python3.14` or `python3.14t`: `PYTHON_GIL=0` is a startup error on a standard build, so a scratch server gets it only through `child_gil_environment()` (free-threaded build running without the GIL); `qa.py` prints the build of every run. `tests/unit/test_scratch_environment.py` exercises every build / GIL combination with stand-ins.
- **`dev_server.py` is the development server and must stay one.** Every scratch server is `python dev_server.py` (plain HTTP/1.1, `app.run`). A copy of `prod_server.py` in its place (TLS mandatory, HTTP/3) made every scratch-server fixture fail with hundreds of `E` lines and a 20 s wait; `tests/unit/test_dev_server_identity.py` names that problem in one line.
- **A/B a performance baseline with `CLOUDINATOR_SCRATCH_CONFIG`**, a JSON object merged into every scratch server's `server_config.json` (explicit fixture config wins), e.g. `CLOUDINATOR_SCRATCH_CONFIG='{"UPLOAD_TIMING_ENABLED": true}' CLOUDINATOR_SLOW_TESTS=1 python -m pytest tests/performance/test_baselines.py -q -s`. Never change a default because of a single run: run the A and the B, read both.
- **A test that waits for a line in the scratch server's log needs the child's output unbuffered:** the server's stdout goes to a file, which is block-buffered. `start_scratch_server` sets `PYTHONUNBUFFERED=1` in the child environment since 5.41 (`dev_server.py` sets it too, but only after its imports, which is too late for the startup lines). Still wait with a bounded poll for the expected line, never a fixed sleep.
- **Functions that cannot be imported are read with `ast` (5.38, 5.40).** `storage.assemble_chunks`, the handler class and cache methods of `file_monitor.py` and the chunk-key helpers of `routes/uploads.py` live in modules that import `config`, start threads or are root modules the guard refuses to import. The unit tests therefore read the function (or class, or method) out of the source file with `ast.get_source_segment`, `exec` it in a private namespace with fakes (a recording fake for `file_index_manager` / `search_index_manager`, a fake monitor, a fake clock whose `sleep` only records) and a temporary folder. The tests fail with a clear message when a name is not found, so renaming one of these functions means updating its test file in the same change. This is also why mutmut does not work here (it rewrites functions into trampolines); use `python tests/mutation_trial.py <file> --functions a,b --tests <paths>` (5.40) to see whether a test file really notices a wrong operator, and add a test for a survivor that matters. **First run (5.44.2, `storage.py`: `is_safe_chunk_id`, `is_safe_path`, `assemble_chunks`):** 26 of 32 killed (81 %). Read every survivor before writing a test: a `return False` in an `except` of a containment function mattered (`test_is_safe_path_error_branch.py`, which forces the exception because the branch is unreachable with a real path on Linux); a progress `print`, the length of a random temp name and an `os.name == "nt"` chmod did not (the last one changes a published file's mode on Linux only: add a test for it if other OS users must read the storage). Line numbers in a trial report move with every edit of the file.
- **`static/js/index.js` logic is tested in plain Node, by function NAME (5.44.3).** `tests/unit/test_index_js_logic.py` cuts `[async ]function name(` out of `index.js` from its line to the first line that is just `}` at column 0 (and one-line `const name = ...;` statements) and runs it with `node -e` against stubs for the globals it reads (`currentPath`, `VT`, `_promptOverwrite`). No markers in `index.js` (so its SRI hash does not change), no jsdom, no `package.json`. Keep a function that has such a test formatted the same way (closing `}` alone at column 0); a rename or reformat fails with a message naming the function. New front-end logic that is a pure function of its inputs gets a test here; behaviour that needs a real page (clicking, layout, scrolling) goes into `tests/frontend/test_browser_flows.py` (opt-in Playwright, its own scratch server). The older markers (`@@chunk-progress-begin/end`, `test_upload_progress_js.py`) stay as they are.
- **`dev_server.py` saves coverage data before `os._exit` (5.44.3).** The stop-file watcher ends the process with `os._exit(0)`, which skips `atexit`, where coverage.py saves; without `_save_coverage_data()` the whole application server was missing from every Linux coverage report (39 % instead of about 50 %). Any new code path that ends a measured process with `os._exit` (or `kill`) must save first, or its code reads as untested. The floor of `qa coverage` is `COVERAGE_FLOOR` in `tests/qa.py` (45 %; Linux and macOS; none on Windows; `--fail-under N` wins).
- **Hypothesis tests (5.40, `tests/property/` and the loader fuzz in `tests/unit/test_monitor_cache.py`) are deterministic in the required check:** `@settings(derandomize=True, database=None, deadline=None, max_examples=150)`; `CLOUDINATOR_NIGHTLY=1` (set by `nightly.yml`) switches to random inputs and ten times as many examples. Generated names and paths must be valid on Windows too: a folder name never ends in a space or a dot (Windows strips them, so `storage\\ ` is `storage`), and a NUL byte must be refused by the code itself, never by hoping `os.path` raises (it does on Linux, not on Windows with Python 3.14, found 5.40). The nightly Windows run exists to catch this class of difference. `@settings` without `@given` is an error: pin a boundary (length 200 / 201) with a plain example test. When a nightly run finds a falsifying example, copy it into a normal example test. A test module that must keep working without Hypothesis installed imports it in `try / except ImportError` and defines the property test inside `if HAVE_HYPOTHESIS:`; a layer that is Hypothesis-only uses `pytest.importorskip`.
- **A passive-port range in a protocol test is probed, never assumed (5.43).** `free_port()` proves ONE port is free, not the 39 after it. pyftpdlib binds a random port of `passive_ports` for every PASV, skips only `EADDRINUSE`, and ends the connection on any other bind error (Windows `WSAEACCES`: an excluded port range or a port held with exclusive use); the client then fails with `EOFError` inside `ftplib.makepasv()` while login and every command without a data channel still work. `test_ftp_protocol.py` therefore tests every port of the block with the same socket options before it sets `passive_ports`, and falls back to `None` (kernel-chosen). Do the same for any new server that takes a port range.
- Containment tests (`test_path_containment.py`) state the DESIRED behaviour. A confirmed hole is kept visible with `xfail(strict=True)` and a one-line reason that points to the sync note; when the hole is fixed the test XPASSes and the run fails until the marker is removed. Create per-test names (`outside_<tag>.txt`, `storage_<tag>`) so tests never collide, and poll (`_wait_for`) for background jobs instead of sleeping blindly.

Test-only packages live in `requirements-dev.txt` (never in `requirements.txt` / `constraints.txt`, which `setup_pymodules.sh` rewrites): `python -m pip install -r requirements-dev.txt` (pytest, pytest-timeout, pip-audit, coverage, hypothesis, and `ruff` pinned EXACTLY: the `lint.yml` workflow reads that one line, so bump it there only). Playwright and Chromium for `tests/frontend/` are NOT in the file (large download): `python -m pip install playwright` and `python -m playwright install chromium`; the nightly workflow does it on Linux.

### 18.1 Automated checks on GitHub (dev and main)

Two GitHub Actions workflows run on every push and pull request to `main` and `dev`:

- [../.github/workflows/tests.yml](../.github/workflows/tests.yml) installs only `pyflakes` and runs `python tests/smoke.py` and `python tests/check.py -q --skip-packages`: the same static checks as on a developer machine, nothing is imported or started. `--skip-packages` hides "package not installed" warnings because the runner does not install `requirements.txt`. A second job, `behavioral tests` (it needs `smoke + check` first), installs `requirements.txt` and `requirements-dev.txt` and runs `python tests/qa.py ci` (static checks, SRI, `node --check`, pytest; JUnit XML is uploaded as the `test-results` artifact). Keep the `smoke + check` job name unchanged: branch protection may require it.
- [../.github/workflows/codeql.yml](../.github/workflows/codeql.yml) runs CodeQL for Python and JavaScript and keeps the raw SARIF files. It converts them to CSV with [../tests/codeql_sarif_parser.py](../tests/codeql_sarif_parser.py) and uploads the artifacts `sarif-artifact-<language>`, `codeql-csv-<language>` and the combined `codeql-findings-csv`. Vendored third-party files are excluded through [../.github/codeql/codeql-config.yml](../.github/codeql/codeql-config.yml); keep that list in step with `VENDORED` in the parser.

Other workflows (none of them is a required check; the required ones are `smoke + check` and `behavioral tests`):

- [../.github/workflows/audit.yml](../.github/workflows/audit.yml) (5.32): weekly `pip-audit` through `python tests/qa.py audit`; accepted findings go into `tests/audit_ignore.txt` with a reason and a review date.
- [../.github/workflows/coverage.yml](../.github/workflows/coverage.yml) (5.34): weekly and on demand, Linux, `python tests/qa.py coverage`. 5.40: **Run workflow** takes an optional `fail_under` percentage (passed through an environment variable) to try a floor without editing the file; the Linux total is 50 % since 5.44.3 (it read 39 % while `dev_server.py` lost the application server's data, see section 18) and the floor is `COVERAGE_FLOOR = 45.0` in `tests/qa.py`, the default of `qa coverage` on Linux and macOS (none on Windows; the workflow file itself did not change; an explicit `fail_under` input overrides it).
- [../.github/workflows/lint.yml](../.github/workflows/lint.yml) (5.40): Ruff, REPORT ONLY (`--exit-zero`, findings as annotations plus a summary by rule), rules in `pyproject.toml` `[tool.ruff]`; path-filtered, so it does not report on every pull request; it stays the report-only twin. Since 5.43 the findings are at ZERO and the required `smoke + check` job runs `python -m ruff check .` (the check name stays, so no ruleset changes), and `python tests/qa.py quick` runs the same step strict: run it BEFORE committing. A new finding is fixed, gets a per-line `# noqa: CODE` with a one-line reason, or (for a file that was read) a per-file ignore in `pyproject.toml`; never an unread ignore.
  **How a finding is triaged (5.43):** read the code first, never ignore a rule for a file that has not been read. A finding that is a real, behaviour-neutral improvement is fixed (`hashlib.md5(..., usedforsecurity=False)` for a non-security fingerprint, a `def` instead of an assigned `lambda`, `raise X(...) from e` inside `except`). A verified false alarm gets a **per-line `# noqa: CODE`** on the FIRST line of the flagged statement, plus a one-line comment above it saying why (S608: only `?` placeholders or fixed fragments are interpolated and every value is bound; S603: a fixed argv; S104: an intentional all-interface bind, CLAUDE.md part 46). Keep the `noqa` short: Black counts a long trailing comment into the line length and re-wraps the call, which moves the `noqa` off the line Ruff looks at. A file-wide ignore in `pyproject.toml` is only for a rule that fires many times for one stated reason in a file that was read (E402 in `core.py`, S104 in `config.py`, S110 in the five files whose every `except Exception: pass` carries a comment). Application code keeps the 4.97 convention for a deliberate swallow (the `except` block stays and a comment says what is skipped and why); TEST code never does (`contextlib.suppress`, section 18.1), so S110 stays active in `tests/`. A new SQL string built with an f-string that interpolates anything but `?` placeholders is a bug, not a `noqa`. More patterns settled in 5.43: an unused loop variable is renamed `_name` (or the `enumerate` is dropped); `raise X(...) from e` inside `except`; a secret, a passkey or a confirmation code is generated with `secrets`, never `random` (S311, also in `tools/`); a `subprocess` call whose argv is a fixed list gets `# noqa: S603` on the line the rule reports with the reason above it, and a call that must find a tool through PATH (`readlink`, `su`) `# noqa: S607` the same way; tool scripts under `tests/` use `contextlib.suppress`, like tests.
- [../.github/workflows/nightly.yml](../.github/workflows/nightly.yml) (5.40): every night on `main` (and on demand for any branch: Actions > Nightly > Run workflow > pick `dev` to test before a merge), Linux AND Windows, `python tests/qa.py ci` with `CLOUDINATOR_SLOW_TESTS=1` and `CLOUDINATOR_NIGHTLY=1`; Chromium is installed on Linux only (on Windows the browser test skips itself); JUnit XML (the measured baselines are properties) is the artifact `nightly-results-<os>`. First real runs (5.44.2): green on both systems after one test fix (a CSRF race in the 12-chunk test's client, see section 18).
- [../.github/workflows/mutation.yml](../.github/workflows/mutation.yml) (5.40): manual only, runs `tests/mutation_trial.py` on a file, functions and tests you name; survivors are reported, never failed.
- [../.github/dependabot.yml](../.github/dependabot.yml) (5.40): weekly version-update pull requests for pip and GitHub Actions, into `dev`. `requirements.txt` / `constraints.txt` are rewritten by `setup_pymodules.sh`; decide which one you trust before merging a pip update.

Rules:

- Run `python tests/smoke.py` and `python tests/check.py` locally before pushing; fix a red Tests run, do not bypass it. For a change that has tests, also run `python tests/qa.py quick` (or one layer: `python tests/qa.py layer unit`).
- The advanced CodeQL workflow cannot run while the repository's CodeQL "default setup" is enabled; disable the default setup first.
- Parse downloaded results by hand with `python tests/codeql_sarif_parser.py <artifact.zip | .sarif file | folder>`; CSV files are written next to the script (add `tests/*.csv`, `tests/*.sarif` and `tests/*.zip` to `.gitignore`).
- When a workflow, the parser's `VENDORED` list or the CodeQL config changes, update sections 18.1, 25.5, 25.8 and 27.2 together.
- CodeQL also scans `tests/`. Rules for test code (5.37): never leave an empty `except ...: pass` (use `with contextlib.suppress(...):  # why the error is expected`); set `ctx.minimum_version = ssl.TLSVersion.TLSv1_2` right after every `ssl.create_default_context()` even when verification is switched off for a self-signed test server; bind test sockets to `127.0.0.1`, not `0.0.0.0`, EXCEPT the SMB port holder `occupy_a_port()` in `test_smb_protocol.py`, which must bind `0.0.0.0` to block the server's own wildcard bind on Windows (it takes the wildcard address from `socket.getaddrinfo(None, 0, AF_INET, SOCK_STREAM, 0, AI_PASSIVE)` so no `0.0.0.0` literal is written; if CodeQL still reports it, dismiss it as "used in tests"); a `dict` subclass that adds an attribute defines `__eq__` (and `__hash__ = None`). In upload tests wait for the expected CONTENT (`exists() and read_bytes() == expected`), never only for the file to exist.

- Workflow inputs and `github.*` values never go straight into a `run:` script: pass them through `env:` and quote the variable (`coverage.yml` `FAIL_UNDER`, `mutation.yml` `TARGET_*`). Pin a new tool's version exactly when a new release could turn a green build red (Ruff); `actions/*` are kept current by Dependabot.
- When a workflow or a test layer is added, update 18, 18.1, 25 (file map rows) and 27.2 together with `docs/TESTING_STRATEGY.md` sections 3, 4, 12 and 14.

## 19. Key contributor conventions

When editing this project, keep these conventions in mind:

1. Respect import order and startup side effects.
2. Do not create a second Quart app instance.
3. Route changes belong in the appropriate module under [../routes](../routes).
4. Keep auth, CORS, and session logic in middleware or auth helpers instead of duplicating it in route code.
5. Prefer filesystem-safe operations and make sure cache/index reconciliation is consistent with the live filesystem.
6. Distinguish between app runtime modules and helper leaf modules.
7. Preserve the project’s design of one shared app object and one central config source.
8. All files are LF (see 19.1). Python is Black-formatted and shell scripts are shfmt-formatted; check with `black --check <file>` and `shfmt -d <file>` before handing a file over.
9. Commit messages describe the change; avoid generic ones such as "Renormalize with LF line endings".

### 19.1 Line endings, formatters and editor setup

- **LF everywhere.** `.gitattributes` has `* text=auto eol=lf`, `eol=lf` for `*.py *.sh *.js *.mjs *.css *.html *.json *.md *.txt *.ftl`, and `binary` for images, fonts, `*.wasm`, `*.pfb`, `*.bcmap`. It exists because SRI hashes are byte hashes: a CRLF working tree on Windows and an LF checkout on the GitHub runner produced different hashes and the `behavioral tests` job failed with 22 stale hashes (CLAUDE.md part 56).
- **Fixing a stray CRLF file:** `sed -i 's/\r$//' <file>`, then `git add --renormalize .`; if it was a template asset, `./manage.sh validate-sri --fix` afterwards.
- **Editor (VS Code, owner):** user setting `"files.eol": "\n"`; default terminal Git Bash; `[python]` formatter `ms-python.black-formatter`, `[shellscript]` formatter `mkhl.shfmt`; Alt+Shift+F formats only the file types an installed extension supports. Extensions: Better Jinja, Black Formatter, HTML CSS Support, Pylance, Python, Python Debugger, Python Environments, Python Indent, shfmt, YAML.
- **Formatter rules for contributors (including Claude):** Black with its defaults (88 columns, no `[tool.black]` section) and shfmt with its defaults (tab indentation). The existing project files are clean under both.
- **Develop inside a virtual environment:** `python -m venv .venv`; Git Bash on Windows `source ./.venv/Scripts/activate` (the script must be sourced, not executed); Linux, macOS and Termux `source .venv/bin/activate`; then `pip install -r requirements.txt` and, for tests and CI, `pip install -r requirements-dev.txt`. `bash setup_pymodules.sh` (or `./manage.sh update-modules`) creates and activates `.venv` itself when you answer `y`. Keep the README command tables in sync with `manage.sh`.
- **GitHub Actions (since 5.09, Node 24):** `actions/checkout@v7`, `actions/setup-python@v7`, `actions/upload-artifact@v7`, `actions/download-artifact@v8`, `github/codeql-action/init@v4` and `analyze@v4`. Keep the major tags current (Node 20 is deprecated) and never replace a workflow file from an old copy: ask for the current one first.
- **Quart timeouts are TOTAL-time caps, not idle timeouts:** `RESPONSE_TIMEOUT` (default 60 s) for sending a whole response and `BODY_TIMEOUT` (default 60 s) for receiving a whole request body. A transfer that can legitimately take longer than a minute (a download through the tunnel, a ZIP stream, an SSE stream, a big upload chunk on a slow uplink) is cut off mid-stream unless the cap is raised or switched off. `core.py` must set `RESPONSE_TIMEOUT=None` (the 5.11 patch; `tests/unit/test_response_timeout.py` guards it) and `BODY_TIMEOUT=BODY_TIMEOUT or None` from `config.BODY_TIMEOUT` (5.41, default 600 s, 0 = no limit; `tests/unit/test_upload_settings.py` guards it and `tests/application/test_upload_tuning.py` proves that a stalled body is cut off after `BODY_TIMEOUT`: the `/upload` handler's generic `except Exception` turns Quart's 408 into a 500 whose text says `408 Request Timeout`, which is what a browser shows).
- **Quart sends a file in 8 KiB steps, two thread hand-offs each.** `FileBody` reads 8 KiB per iteration and awaits aiofiles `tell()` and `read()` for every one: a 32 MB file is 4096 steps, which held a RAM-cached download to 2.6 MB/s on the owner's Windows PC (41 MB/s on Linux; 346 MB/s with 256 KiB steps). `core.py` must call `use_file_buffer(app, DOWNLOAD_BUFFER_SIZE)` (`helpers/file_body.py`, 5.42; `tests/unit/test_upload_settings.py` guards the call, `tests/unit/test_file_body.py` and `tests/application/test_download_buffer.py` guard the bytes and `Range`). Do not replace `send_from_directory` by a hand-written streaming generator with small pieces, and keep any new streaming response at 256 KiB or more per step.
- **Shell scripts under Git Bash:** never rely on `grep`, `head`, `sed` or `$(...)` to see a `\r`; use an `od` hex dump or bash `printf` escapes (see `append_req_line()` in `setup_pymodules.sh`).

## 20. Typical development flow

A normal contributor workflow looks like this:

1. Review startup path in [../app.py](../app.py) and [../core.py](../core.py).
2. Check route placement under [../routes](../routes).
3. Confirm the config in [../config.py](../config.py) and [../storage_config.json](../storage_config.json).
4. Run the relevant validation script, such as the smoke/test checks under [../tests](../tests).
5. Update any SRI or asset hashes if frontend JS/CSS changes.
6. Restart the app and validate the changed behavior against the real filesystem and UI.

## 21. Summary

CloudinatorFTP is a broad but cohesive project built around a single Quart app, a SQLite persistence layer, a filesystem monitor, a live UI, and several protocol listeners. The codebase is intentionally modular but still architecture-sensitive: feature routes are separated by file, while shared application runtime remains centralized in the core layer.

The best way to modify the project safely is to treat it as:

- one app instance
- one storage root
- one central config and path layer
- many route modules with a strict import and lifecycle order
- a file-monitor-driven live UI that depends on index and cache consistency

That mental model is the most important reference when making a change in this codebase.

---

## 22. Change recipes

Use these recipes as starting points. They name the usual owner files and the cross-layer work that is easy to miss. Follow the existing implementation in the named module when its behavior is more specific than this guide.

### 22.1 Add or change a browser API endpoint

1. Choose the feature owner under [../routes](../routes): browsing and file operations in [../routes/files.py](../routes/files.py), uploads in [../routes/uploads.py](../routes/uploads.py), shares in [../routes/shares.py](../routes/shares.py), stats/search in [../routes/stats.py](../routes/stats.py), previews in [../routes/previews.py](../routes/previews.py), versions in [../routes/versions.py](../routes/versions.py), and so on.
2. Import the existing shared `app` and required shared state from [../core.py](../core.py). Do not instantiate another Quart app and do not import `app` from [../app.py](../app.py).
3. Register a plain `@app.route(...)` function. Use the bare endpoint name expected by `url_for()` and middleware. Do not move routes to a Blueprint: endpoint names are used by auth/CSRF policy and route checks.
4. Decide access intentionally. Use `@login_required` for logged-in routes. For mutations, copy the neighboring pattern (`role = get_role(current_user())`, then `if role != "readwrite":` return the error response); authentication alone does not imply write permission. Public share routes are intentionally exceptions; follow the nearby route and share-token checks rather than making them globally public.
5. Validate request data and storage paths before filesystem access. Existing file routes use `storage.is_safe_path()` / `storage.is_valid_path()`; do not build a path from user input and access it directly without the same safety boundary.
6. Keep the async handler non-blocking. Disk walks, hashing, conversion, SQLite-heavy work, and blocking library calls should follow nearby wrappers using `asyncio.to_thread()` or a worker thread. Preserve the existing JSON/status response shape if a browser caller already consumes it. `/upload` is the worked example since 5.41 (`_read_and_save_chunk` in a worker thread, section 10.6).
7. If adding an endpoint used by the UI, update its caller in [../static/js/index.js](../static/js/index.js) or the relevant page script and check any URL in [../templates](../templates). Update endpoint-name allow/exempt/public sets only when the endpoint's security policy actually requires it.
8. Run the route checks listed in [Validation by change type](#23-validation-by-change-type). The smoke suite catches duplicate endpoints/rules, missing `url_for()` targets, route modules not imported from `app.py`, and hooks placed in the wrong module.

Useful examples in this checkout: `api_versions_list()` in [../routes/versions.py](../routes/versions.py) shows a read endpoint with path validation and offloaded database work; `api_versions_restore()` shows explicit role checking and a state-changing response; `index()` in [../routes/files.py](../routes/files.py) shows path validation and `storage.list_dir()` offloaded from the event loop.

### 22.2 Add or change a file mutation

1. Put browser-facing file operations in [../routes/files.py](../routes/files.py), upload writes in [../routes/uploads.py](../routes/uploads.py), or protocol-specific writes in the relevant protocol server.
2. Use the shared storage root and safety helpers from [../storage.py](../storage.py). Keep paths relative to `ROOT_DIR` at API boundaries and normalized with `/` in index/cache keys.
3. Check role and conflict/overwrite behavior before changing the filesystem. Keep the API's error codes and payloads stable for the frontend.
4. After a successful web-UI mutation, call `_trigger_reconcile()` from [../core.py](../core.py) using the same pattern as the neighboring mutation route. Use `settle=True` for operations that create a large event burst, as the bulk-copy path does. Trigger only after actual success (or partial success where the route reports completed items).
5. Do not directly edit the file monitor's global counters or cache JSON from a route. The monitor's reconcile path is the source of truth and also emits the update the browser consumes.
6. Check the operation's response and the browser update path. The table/listing and stats may consume different APIs/events; verify both when the mutation affects both.

External filesystem writes (Explorer, WebDAV, SFTP, FTP, SMB) are observed through [../file_monitor.py](../file_monitor.py), not through `_trigger_reconcile()` in a browser route. When changing that monitor, preserve its event batching, dirty-folder correction, cache-save behavior, and change-sequence/SSE notifications. For large changes, use a focused test against a temporary tree rather than a real storage root.

### 22.3 Change frontend behavior or add a control

1. Identify the existing state owner and handler in [../static/js/index.js](../static/js/index.js) before adding a second state variable or listener. The main file table has its own virtualized data model; mounted table rows are not the complete dataset.
2. For controls generated in HTML, prefer the existing delegated dispatcher: add `data-fn`, `data-args` (built with `dataArgs()`), or `data-fn-change` attributes, then expose/use the matching handler. This survives row rebuilds and avoids inline event handlers.
3. When a control calls an API, keep request and response handling together in the feature's existing client workflow. State-changing `fetch()` calls are wrapped centrally to attach/refresh the CSRF token; don't bypass `window.fetch` without a reason.
4. Add layout and responsive rules to the owning stylesheet under [../static/css](../static/css). Avoid new inline `style="..."` attributes or inline scripts: the CSP allow-list in [../core.py](../core.py) is hash-based. CSSOM style updates from JavaScript are distinct from literal inline style attributes, but follow the existing component pattern.
5. If a frontend asset is referenced by a template with `integrity`, run `./manage.sh validate-sri --fix` (or `python tools/sri_validator.py --fix`) after changing it. Run `node --check static/js/<file>.js` for JavaScript syntax; for `.mjs`, use the project's available Node version and check the actual edited module.
6. Verify interaction states, not just the happy path: loading, empty, error, permission denied, stale session/CSRF, cancellation, and repeated clicks where applicable. For table features, test after sorting/filtering/scrolling because virtualization can make DOM-only assumptions fail.
7. After changing a page's JavaScript, run the browser smoke (opt-in): `CLOUDINATOR_SLOW_TESTS=1 python -m pytest tests/frontend -q` must say `3 passed`. It sees what the Python tests cannot: an SRI mismatch, a 404 of a static file, a failed request, a script error on the login page and the file manager.

### 22.4 Add or modify configuration

1. Put runtime constants and defaults in [../config.py](../config.py), next to the feature's existing settings. Keep directory resolution in [../paths.py](../paths.py), not scattered across routes.
2. If the setting is user-persisted, trace how `server_config.json` is loaded/saved in `config.py` and how the configuration menu edits it. Update both defaults and persistence/validation; a constant alone may be overwritten or never saved.
3. For a new storage directory, add a `paths.py` getter/setter following the existing `get_*_dir(create=True)` / `set_*_dir(path)` pattern and merge its key through the shared JSON read/write helper. Keep imports side-effect free where the existing path APIs use `create=False`.
4. Update the relevant configuration reference, deployment guide, and defaults table. Test valid, absent, malformed, and legacy config values where the loader supports fallback behavior.
5. Restart the app for settings imported into module-level constants; changing JSON on disk does not necessarily update already-imported values.
6. A setting an owner is meant to switch gets a menu entry (5.43: Server Settings > 14, `configure_transfer_performance()`): the menu function declares the module globals it changes (`global`), validates input with the loader's own validator, and is tested by running the REAL function with a scripted `input()` (`tests/unit/test_upload_settings.py`). Changing a DEFAULT is a behaviour change only for installs that never saved the value: state that, and test that a saved value still wins.

### 22.5 Change database schema or persisted records

1. Find the owning database API in [../database.py](../database.py), [../search_index.py](../search_index.py), or the version subsystem; do not have a route construct SQL against another module's private tables.
2. Main application schema bootstrap is in `_do_bootstrap()` after `_connect()` in [../database.py](../database.py). `CREATE TABLE IF NOT EXISTS` handles first creation but does not migrate an existing table. Add an explicit, repeatable migration for existing installs when a schema changes.
3. Preserve the module's connection, transaction, lock, WAL, and lazy-bootstrap patterns. Do not create DB files merely by importing a leaf utility.
4. Consider recovery for interrupted writes and old data. For indexes, decide whether stale entries should be rebuilt, reconciled, or ignored; do not assume a cache file is the source of truth.
5. Test both a fresh database and an existing database created with the previous schema. Use a temporary database path; do not point migration tests at a live installation.

### 22.6 Change storage indexing or live updates

There are three distinct indexes; choose the right owner before editing:

| Data | Owner | Represents | Rebuilt/reconciled by |
|---|---|---|---|
| Recursive counts and per-folder totals | [../file_monitor.py](../file_monitor.py) | `storage_index.json` and live storage snapshots | Full reconcile walk and dirty-folder correction |
| Direct listing entries for large folders | [../file_index.py](../file_index.py) | `file_index.json` rows for `storage.list_dir()` | `build_from_walk()`, `update_folder()`, and freshness checks in `get_entries()` |
| Deep filename search | [../search_index.py](../search_index.py) | SQLite `search_index.db` | Crawler, watchdog updates, and reconcile-from-walk |

Do not conflate these stores: rebuilding the file-monitor cache does not automatically mean the deep-search DB was rebuilt. For index changes, preserve relative-path normalization, hidden-file behavior, incomplete-walk protection, lock boundaries, and atomic cache writes. Add a test for the specific correction path, not only the initial full build.

### 22.7 Change route security or session behavior

1. Put shared request/response hooks in [../middleware.py](../middleware.py); the smoke suite expects hooks there, with the documented event-loop watchdog exception in [../routes/stats.py](../routes/stats.py).
2. Keep hook registration order stable. `app.py` imports `core` first, then `middleware`, then route modules; CSRF's `csrf.init_app(app)` is deliberately positioned between the timer and session validation hooks.
3. Route-level login protection uses `login_required` from `core`. Role policy is separate and must be checked by write routes.
4. API authentication failures should remain machine-readable 401 responses; browser-page routes may redirect. Follow the response distinction in `login_required` and `validate_session`.
5. When endpoint names or public/CSRF exemptions change, inspect the corresponding endpoint sets in [../core.py](../core.py) and [../middleware.py](../middleware.py), plus `url_for()` call sites. A renamed function can silently change a security decision even when its URL still works.
6. Test both anonymous and authenticated requests, including readonly and readwrite accounts for mutations. Confirm status, content type, and cache/security headers.

### 22.8 Add or change a protocol feature

1. Protocol listener settings belong in [../config.py](../config.py); service startup/supervision belongs in [../protocol_manager.py](../protocol_manager.py); protocol behavior belongs in its `*_server.py` module.
2. Preserve the shared database authentication and read-only/read-write role semantics. Validate paths under the configured storage root in the protocol library's own path adapter.
3. Keep the process model in mind: SFTP/FTP/SMB are background threads; WebDAV is its own supervised process. Do not import [../app.py](../app.py) into a helper subprocess just to get a utility; use a leaf helper such as [../helpers/net_utils.py](../helpers/net_utils.py).
4. Test startup with the feature disabled, the dependency missing, and the port unavailable. The main browser server should still start if an optional protocol cannot.
5. Update the protocol deployment guide and config reference for user-visible ports, TLS/auth behavior, or platform setup changes.

### 22.9 Add or change a route module

Every route module must be imported in [../app.py](../app.py), or its decorators never execute. Keep route modules importing shared app/state from `core`, not from `app`. Route-to-route imports are deliberately narrow: the static checker currently permits [../routes/admin.py](../routes/admin.py) to import HLS/image-preview helpers and [../routes/uploads.py](../routes/uploads.py) to import the share-pruning helper. If a new dependency is needed, first ask whether the shared state/helper belongs in `core.py` or a non-route service module instead of broadening route coupling.

Do not add request hooks to a route module merely because the hook is related to that feature. Use the lifecycle owner [../middleware.py](../middleware.py); it is registered once and order-sensitive.

## 23. Validation by change type

Run checks from the project root. These static checks do not import or start the app unless explicitly requested.

| Change | Suggested checks |
|---|---|
| Any Python file, route, or `manage.sh` change | `python tests/smoke.py`; `python tests/check.py <group-or-module>` |
| Route registration/auth wiring | `python tests/smoke.py -v`; `python tests/check.py routes` |
| One Python module | `python tests/check.py routes/files.py` (replace with the target path); then run its focused behavioral test |
| Config JSON or config constants | `python tests/check.py config --config` |
| Python syntax quick check | `python -m py_compile path/to/module.py` |
| JavaScript asset | `node --check static/js/index.js` (substitute the edited file); `./manage.sh validate-sri` |
| Template/static asset hashes | `./manage.sh validate-sri`; repair with `./manage.sh validate-sri --fix` |
| `manage.sh` | `bash -n manage.sh`; `python tests/smoke.py` |
| `requirements.txt` / `constraints.txt` | `python tests/qa.py audit` (`pip-audit` is in `requirements-dev.txt`; needs network; not part of `quick`); a finding that cannot be fixed yet goes into `tests/audit_ignore.txt` with the reason; `.github/workflows/audit.yml` repeats it weekly |
| Anything with tests (a periodic look, not every change) | `python tests/qa.py coverage` (`coverage` is in `requirements-dev.txt`; slow; not part of `quick`); read the server numbers from the Linux workflow `.github/workflows/coverage.yml` (on Windows the harness kills the servers and their data is lost); never add `source` to `[tool.coverage.run]` in `pyproject.toml` (the subprocess servers would measure nothing) |
| File monitor/index behavior | Run the narrow temporary-tree test for the changed behavior, then `python tests/smoke.py` |
| `storage.py` upload assembly, `file_monitor.py` event handler or index cache | `python tests/qa.py layer unit` (the `ast`-based tests `test_assemble_atomic.py`, `test_monitor_handler.py`, `test_monitor_cache.py`; they fail loudly when a function is renamed) and, for a counter change, `python tests/mutation_trial.py file_monitor.py --functions on_moved --tests tests/unit/test_monitor_handler.py` (5.40) |
| Any Python file (5.40) | `python -m black --check <file>`; `python tests/qa.py lint` (5.41, = `ruff check .` with the rules of `pyproject.toml`, report only: findings listed and counted per rule, the step passes; `--strict` fails on any finding; the pinned version is in `requirements-dev.txt`; not part of `quick`) |
| Anything with pytest coverage (`paths.py`, test harness, server boot) | `python tests/qa.py quick`; one layer: `python tests/qa.py layer unit` / `layer application` (needs `requirements-dev.txt`) |
| `setup_pymodules.sh` | `bash -n setup_pymodules.sh`; `python tests/qa.py layer unit` (covers `append_req_line()`) |
| `manage.sh` | `bash -n manage.sh`; `shfmt -d manage.sh`; `python tests/smoke.py` (10a/10b); `python tests/qa.py layer unit` (menu-numbering tests); update the guide and `LAST_ENTRY` if the menu changed |
| New or changed test, `tests/conftest.py` or `tests/qa.py` | `python tests/check.py tests`; `python tests/smoke.py`; `python tests/qa.py layer unit`; never import `app` / `core` / `config` in a test (see 18) |

`tests/smoke.py` is read-only and checks the whole project's syntax, import/layering constraints, route registration, endpoint references, hooks, and manage.sh references. `tests/check.py` selects a smaller group/module and supports `--config`; its `--import` option really imports modules and is refused for app modules with startup side effects unless forced. Do not use `--force` on a live server.

These commands are guardrails, not substitutes for feature tests. In particular, syntax checks cannot validate browser rendering, filesystem correctness, auth policy, or protocol interoperability. Run focused behavior tests and a manual browser/protocol check for those surfaces.

## 24. Quick file map

- [../app.py](../app.py) — startup composition root
- [../core.py](../core.py) — global runtime, security, app object, monitoring glue
- [../middleware.py](../middleware.py) — auth, CSRF, CORS, request hooks
- [../config.py](../config.py) — runtime configuration
- [../database.py](../database.py) — SQLite and encrypted auth data
- [../paths.py](../paths.py) — DB/cache path resolution
- [../storage.py](../storage.py) — filesystem operations
- [../file_monitor.py](../file_monitor.py) — live filesystem monitoring
- [../file_index.py](../file_index.py) — file index cache
- [../search_index.py](../search_index.py) — deep index and search
- [../version_engine.py](../version_engine.py) — snapshot/version engine
- [../version_history.py](../version_history.py) — version history layer
- [../routes](../routes) — feature endpoints
- [../templates](../templates) — browser pages
- [../static](../static) — JS/CSS/assets
- [../tools](../tools) — admin and maintenance scripts
- [../helpers](../helpers) — utility modules
- [../docs/CLAUDE.md](../docs/CLAUDE.md) — the most detailed project history and architecture notes

## 25. Complete source index

This section is the file-by-file map of executable, first-party project code. The workspace inventory contains **53 Python files**, and every one has an individual entry in sections 25.1–25.5: 23 root modules, 12 route files, 5 helpers, 8 tools, and 3 test scripts. Frontend CSS and JavaScript files are documented in sections 25.6 and 26. Each entry describes its implementation role and the neighboring contracts to check when modifying it. Use the change recipes above to plan cross-layer edits, then use this index to locate the owning implementation.

### 25.1 Root Python modules

| File | What it implements | When changing it, also check |
|---|---|---|
| [../app.py](../app.py) | Application composition root. Imports `core` first, registers middleware and all route modules, runs `initialize_cleanup()`, and exposes the app for launchers. | Import order is functional: preserve `core` first, middleware before routes, and every `routes/*.py` import. Importing this module has startup side effects. |
| [../auth.py](../auth.py) | Web-session wrappers for login checks, current user and role lookup; delegates credential persistence to `database.db`. | Changes to account/session semantics should be tested with middleware, `database.py`, routes, and all protocol authentication paths. |
| [../config.py](../config.py) | Runtime defaults, platform detection, server-config load/save and interactive configuration menus. Resolves `ROOT_DIR` and re-exports configured data paths. | Update persistence and validation as well as defaults; check `server_config.json`, `storage_config.json`, config docs, and restart requirements. The upload settings `BODY_TIMEOUT`, `UPLOAD_TIMING_ENABLED` and `UPLOAD_CHUNKS_IN_MEMORY` (5.41) need default, save, load, display and a test together (22.4); `view_current_settings()` looks the Version Engine up with `importlib.import_module`, not an import statement (CodeQL #612). `DOWNLOAD_BUFFER_SIZE` (5.42) is the fourth of the upload / download tuning settings and has the same default, save, load, display and test requirements. |
| [../core.py](../core.py) | Shared Quart app, security/session configuration, rate limiter, chunk/assembly state, auth decorators, stream helpers, file monitor setup and reconciliation gate. | This is shared process state. Preserve one app instance, endpoint policy sets, locks, and the helper/API contracts imported by routes and middleware. Since 5.42 it applies `DOWNLOAD_BUFFER_SIZE` to file responses through `helpers.file_body.use_file_buffer` (section 19). |
| [../database.py](../database.py) | Lazy SQLite schema/bootstrap and APIs for users, roles, server token, shares and access requests; password/secret protection and SMB NT hashes. | Existing databases need explicit idempotent migrations; test fresh and prior-schema DBs on temporary paths. Keep lock, transaction, WAL and key-file behavior intact. |
| [../dev_server.py](../dev_server.py) | Development launcher; starts the app, protocol services and Version Engine and manages debug/background shutdown behavior. | Verify reload/background mode, signal handling, and cleanup of both threads and child processes. |
| [../file_index.py](../file_index.py) | `FileIndexManager` for direct listings of large folders, with thresholding, freshness validation, reconciliation, and atomic JSON persistence. | Keep `storage.list_dir()`, monitor callbacks, path normalization, threshold/schema, hidden entries, and cache recovery consistent. |
| [../file_monitor.py](../file_monitor.py) | Watchdog event processing, recursive counts/`dir_info`, dirty-folder corrections, reconciliation walks, JSON cache persistence and callbacks to file/search indexes and live updates. | Treat event arithmetic, walk epochs, incomplete-walk handling, ignored paths, persistence, and SSE change sequencing as one contract; test against a temporary tree. |
| [../ftp_server.py](../ftp_server.py) | FTP/explicit FTPS server, DB authorizer, read/write permission mapping, passive mode, audit events and thread lifecycle. | Check TLS fallback warnings, shared certificate paths, role mapping, and optional-dependency/port failure behavior. |
| [../logging_setup.py](../logging_setup.py) | Shared logger tree, daily log handler, stdout/stderr tee and exception hooks; gives modules child loggers. | Avoid adding duplicate handlers or writing relayed child output through the tee twice; launchers/processes share log naming and stream behavior. |
| [../middleware.py](../middleware.py) | Request/response hooks, CSRF initialization, session validation, CORS preflight/headers, security headers, error handling and template filters. | Preserve exact hook registration order and coordinate endpoint names with `core.py`, route decorators, CSRF exemptions and `url_for()` references. |
| [../paths.py](../paths.py) | Read/write/resolve functions for DB, cache, HLS/image cache and version directories in `storage_config.json`; startup directory preparation. | Setters persist paths but do not migrate old contents. Merge keys rather than replacing sibling config values; callers may depend on `create=False` import safety. |
| [../prod_server.py](../prod_server.py) | Production Hypercorn launcher, TLS certificate selection/renewal and orderly lifecycle for protocol and version-engine services. | Preserve one-worker assumptions, TLS/HTTP protocol settings, signal shutdown, process startup and fallback certificate behavior. |
| [../protocol_manager.py](../protocol_manager.py) | Starts/stops FTP, SFTP and SMB threads and supervises the WebDAV subprocess, including PID/output/watchdog/restart behavior. | Keep lifecycle idempotent and WebDAV isolated; optional protocol failures must not prevent the web app from serving. |
| [../realtime_shares.py](../realtime_shares.py) | In-memory SSE manager for pending share requests and active-share changes; bridges thread callbacks to the event loop. | Preserve client queue limits, event names/payloads and thread-safe loop scheduling; callers are in `routes/shares.py`. |
| [../realtime_stats.py](../realtime_stats.py) | Storage statistics/filesystem activity SSE, polling support, initial state and missed-change catch-up. Connects file-monitor callbacks to clients. | Keep sequence/epoch/catch-up payloads aligned with `file_monitor.py`, `routes/stats.py`, and `static/js/index.js`. |
| [../search_index.py](../search_index.py) | SQLite deep-search index manager, FTS5 trigram and LIKE fallback, crawler, incremental mutations and full-walk reconciliation. | Maintain synchronization between FTS and metadata tables, completion marker behavior, path normalization, and API pagination/count expectations. |
| [../sftp_server.py](../sftp_server.py) | Paramiko SSH/SFTP server with host key, DB auth, rooted path mapping, permission enforcement, cipher hardening and audit logging. | Preserve containment including Windows paths/symlinks, Paramiko OS-flag interpretation, host-key stability, and readonly behavior. |
| [../smb_server.py](../smb_server.py) | impacket SMB listener, periodic credential refresh, live role enforcement (tree connect, CREATE, SET_INFO, WRITE), guest/anonymous block, corrected path jail, audit hooks and port fallback. | Its hooks patch/vendor internal behavior; check impacket version compatibility, Windows-specific fixes, NT hash lifecycle, and fallback port behavior. |
| [../storage.py](../storage.py) | Filesystem API for listing, path validation, directory info, file operations, chunk storage/assembly/cleanup and storage statistics. | Routes and protocol adapters must validate caller paths; coordinate listing changes with `file_index.py`, mutations with `file_monitor.py`, and uploads with `routes/uploads.py`. |
| [../version_engine.py](../version_engine.py) | Parent-process lifecycle API and `--worker` engine for snapshots, content-addressed storage, restore, scan, retention and GC. | Keep the process API used by both launchers, DB/object-store schema, crash recovery, and tracking/exclusion configuration aligned. Since 5.41 `.chunks` is never tracked and a watcher or scanner pass of 2 s or more is logged (at most once a minute). |
| [../version_history.py](../version_history.py) | Web-facing synchronous adapter for history, restore, download, retry, deletion and in-flight restore state. | Routes offload blocking calls; web restore targets `.recovered/`, not the original file. Coordinate API/schema changes with `routes/versions.py` and `tools/version_manage.py`. |
| [../webdav_server.py](../webdav_server.py) | WsgiDAV provider bridged into Hypercorn; TLS selection, authentication/role middleware, audit logging and client disconnect handling. | It runs in a child process. Preserve middleware wrapping order, HTTP/1.1 compatibility, TLS/plaintext fallback policy, and avoid importing the full app for utility functions. |

### 25.2 Route modules

All route modules register directly on the shared `core.app`; `app.py` must import each module. The path below is the behavior owner, not merely a namespace.

| File | Endpoints and implementation areas | Cross-file contract |
|---|---|---|
| [../routes/__init__.py](../routes/__init__.py) | Package marker; no feature handlers. | Keep package importable; route registration occurs in individual modules imported by `app.py`. |
| [../routes/admin.py](../routes/admin.py) | Media-preview cache clearing and asynchronous cache rebuild/status workflow. | Uses HLS/image cache state, `file_monitor`, and `file_index`; do not delete active conversion/transcode outputs. |
| [../routes/files.py](../routes/files.py) | Browser listing, view/download, directory APIs, bulk ZIP, bulk move/copy/delete jobs, rename and mkdir/delete/conflict APIs. | Preserve path and role checks, stable response payloads, worker-job ownership, and `_trigger_reconcile()` after successful mutations. |
| [../routes/hls.py](../routes/hls.py) | HLS job start/status, ffprobe/ffmpeg processing, cache files, playlist/segment/subtitle serving. | Align profile and output naming with `static/js/index.js` and player assets; keep cache state readable by `routes/admin.py`. |
| [../routes/image_preview.py](../routes/image_preview.py) | Image metadata, preview conversion/compression, status polling and cache coordination. | Align file-type/threshold decisions with frontend preview routing; protect active conversions when clearing cache. |
| [../routes/login.py](../routes/login.py) | Login/logout, session check, CSRF-token route. | Coordinate session fields and response semantics with `auth.py`, `middleware.py`, and JS token refresh behavior. |
| [../routes/previews.py](../routes/previews.py) | Office document and archive preview APIs; blocking parsers execute via worker threads. | Preserve output formats and row/entry limits consumed by `index.js`; optional parser dependencies can be absent. |
| [../routes/shares.py](../routes/shares.py) | Share CRUD/settings, public token access/passkey/approval, public browsing/download, admin request workflows and share SSE. | Keep share gates consistent on every public route; coordinate DB payloads with `database.py`, notifications with `realtime_shares.py`, and shared client with `shared.js`. |
| [../routes/site_meta.py](../routes/site_meta.py) | `robots.txt`, `security.txt`, and deliberately unavailable sitemap behavior. | Keep served files and headers in sync with `static/robots.txt` and `static/.well-known/security.txt`. |
| [../routes/stats.py](../routes/stats.py) | Storage stats, live stream/polling, monitoring, health, disk, search, speed test and event-loop watchdog. | Search and SSE contracts connect `search_index.py`, `realtime_stats.py`, `file_monitor.py`, and `index.js`; audit unauthenticated diagnostic routes deliberately. |
| [../routes/uploads.py](../routes/uploads.py) | Whole/chunked upload, cancellation, cleanup/status endpoints, assembly worker and schedulers. | Worker startup is called from `app.py`; use shared core queues and storage helpers; preserve CSRF, write-role checks and share cleanup import. Since 5.41: the chunk is read and saved in a worker thread, the after-assembly reconcile waits for running uploads, and the in-memory / timing options live here (section 10.6). |
| [../routes/versions.py](../routes/versions.py) | Version list/restore/download/retry/delete/failed cleanup and recovered-file serving. | Coordinate with `version_history.py`, the JS modal/download UI, and readonly/readwrite rules; thread-offload blocking operations. |

### 25.3 Helper modules

The helpers package is intentionally made of leaf utilities; the static checks reject imports from app/core/middleware/routes/tools/tests.

| File | What it implements | Callers/constraints |
|---|---|---|
| [../helpers/__init__.py](../helpers/__init__.py) | Package initializer. | Keep it free of application initialization. |
| [../helpers/hypercorn_ssl_fix.py](../helpers/hypercorn_ssl_fix.py) | One-time patch to bound/handle Hypercorn TLS shutdown. | Called by production and WebDAV processes; revalidate against Hypercorn internals on dependency upgrades. |
| [../helpers/lanman_guard.py](../helpers/lanman_guard.py) | Windows LanmanServer/elevation/port checks and pending-setup state access. | Used by SMB setup/server and DB reset paths; preserve platform guards and state format. |
| [../helpers/net_utils.py](../helpers/net_utils.py) | Local IP discovery with fallback. | Imported by launchers/protocol servers; must stay side-effect-light and not import the app. |
| [../helpers/parent_watch.py](../helpers/parent_watch.py) | Orphan guard for child processes: polls the PID in `CLOUDINATOR_PARENT_PID` and shuts the child down when the parent is gone. | Used by `webdav_server.py` and `version_engine.py --worker`; stdlib only, no `__file__` tricks; the parent must set the env var in every spawn (`protocol_manager._spawn_webdav_process`, `version_engine._spawn_version_engine_process`). |
| [../helpers/ssl_cert.py](../helpers/ssl_cert.py) | Shared certificate/key creation, IP SAN discovery, path resolution, regeneration and CLI instructions. | Used by production/WebDAV/FTPS; regeneration replaces trust material and needs operator notification. |
| [../helpers/upload_perf.py](../helpers/upload_perf.py) | Upload-path helpers (5.41): `StageTimer` / `UploadTimingLog` (stage timings of one `/upload` chunk), `watch_loop_lag` / `LagProbeStarter` (event-loop lag, started once by the first upload request), `IdleDeferral` (run an action once a busy condition ends, with a hard cap) and `parse_form_in_memory` (a multipart body parsed in RAM). 5.43: `StageTimer.detail()` splits one stage (`body arrived`, `parse`) without changing the total, and `parse_timing_lines()` returns `body` / `parse` only when a line has them. | Standard library only (werkzeug is imported inside `parse_form_in_memory`); never imports the application; used by `routes/uploads.py`; covered by `tests/unit/test_upload_perf.py` and `tests/unit/test_upload_perf_split.py`. |
| [../helpers/walk_executor.py](../helpers/walk_executor.py) | `run_walk(fn, *args)` (5.44): runs a long folder walk in a pool of its own (`WALK_WORKERS` = 2 threads named `walk_0`, `walk_1`, created on first use) so walks never queue up the loop's default thread pool. Standard library only; used by `routes/stats.py`, `routes/shares.py`, `routes/files.py`. | Standard library only; keep the callable uncalled and pass plain values (section 8.2). |
| [../helpers/file_body.py](../helpers/file_body.py) | `use_file_buffer(app, size)` (5.42): makes `send_file` / `send_from_directory` of ONE app read `size` bytes per step instead of Quart's 8 KiB, by giving the app a response class whose `file_body_class` is a subclass with that `buffer_size`. | Standard library only; never raises (logs and keeps Quart's default when the hook is missing); leaves Quart's own classes untouched; used by `core.py`; covered by `tests/unit/test_file_body.py`. |

### 25.4 Operator tools

Tools are direct-entry utilities, not application services. Avoid importing them from runtime modules, and use the wrapper in `manage.sh` where available.

| File | What it changes or reports | Important modification consideration |
|---|---|---|
| [../tools/kick_sessions.py](../tools/kick_sessions.py) | Lists users, rotates/deletes accounts, rotates passwords or server token to revoke sessions. | Password rotation output is sensitive; bulk mode has an admin-preservation default. |
| [../tools/manage_users.py](../tools/manage_users.py) | Interactive user creation, password/role changes, deletion and default-account management. | Must keep role values and encrypted/hash credential writes consistent with `database.py`. |
| [../tools/reset_db.py](../tools/reset_db.py) | Destructively clears the configured DB directory and reboots the database schema. | The directory can contain keys/certificates too; preserve confirmation and document data loss clearly. |
| [../tools/revoke_sharing.py](../tools/revoke_sharing.py) | Lists, revokes or edits shares; approves/denies access requests via menu or CLI. | Revoke-all uses a single-use confirmation code; preserve confirmation and expiry semantics. |
| [../tools/setup_storage.py](../tools/setup_storage.py) | Interactive storage, DB/cache and HLS path configuration. | Setters validate writable paths but do not migrate existing stored data. |
| [../tools/smb_setup.py](../tools/smb_setup.py) | Host-level SMB port setup/restore for Windows/Linux/Termux, including elevation and OS settings. | This changes host state; preserve explicit operator confirmation and the matching pending-state protocol. |
| [../tools/sri_validator.py](../tools/sri_validator.py) | Checks/fixes SHA-384 integrity attributes for local template assets. | `--fix` writes templates bytewise; run after referenced JS/CSS changes. |
| [../tools/version_manage.py](../tools/version_manage.py) | Lists, restores, deletes version records and runs garbage collection. | Uses engine internals; restore overwrite and reclamation are destructive paths needing confirmation. |
| [../tools/purge_missing_versions.py](../tools/purge_missing_versions.py) | Finds tracked files that are gone from disk, soft-deletes their versions and optionally frees the chunks (`--free-now`); `--undo` re-activates a purge while its chunks still exist. | Destructive: report first, confirm before `--apply`. No arguments on a terminal opens its own menu (`interactive_menu`, same conventions as `version_manage.py`); any argument keeps the plain command line, no terminal means report only. Menu and command line share `_collect`, `_apply`, `_run_undo`. Long steps must not look stuck: the scan and `soft_delete` report every 50,000 items, the space calculation and the two steps of freeing chunks print a heartbeat every 5 s through `_with_progress` (a worker thread; the engine's `run_gc` is not changed). A file counts as gone only when its drive, share or tracked folder is reachable and not empty (otherwise "cannot tell"; `--force` overrides). Do NOT bring back a "more than half is gone" brake: a real clean-up can be 70 %+. `config` and `version_engine` are imported inside functions so the decision logic (`scan_tracked`, `reclaimable`, `soft_delete`, `undo_versions`) stays testable without an engine; the tests are `tests/unit/test_purge_missing_versions.py` and `tests/application/test_purge_missing_versions.py` (real Engine in a scratch copy). |

### 25.5 Tests and checks

| File | What it executes/checks | What it does not prove |
|---|---|---|
| [../tests/check.py](../tests/check.py) | Parameterized static source checks for syntax, pyflakes, project imports, import-name resolution, helper layering; optional guarded subprocess imports and JSON config checks. | AST/import heuristics are not full runtime coverage; `--import` executes modules and may have side effects when forced. |
| [../tests/codeql_sarif_parser.py](../tests/codeql_sarif_parser.py) | Converts CodeQL SARIF files (loose, zipped artifacts or folders) to per-language and combined CSV files; skips vendored files by default; optional `--fail-on` exit code. Standard library only. | Used by `codeql.yml` and by hand; keep `VENDORED` in step with `.github/codeql/codeql-config.yml`. |
| [../tests/conftest.py](../tests/conftest.py) | Shared pytest fixtures: `build_scratch()` copies the source tree into a temp folder and writes scratch `storage_config.json` / `server_config.json`; `paths_outside()` asks the copy's own `paths.py` where it would keep data and lists anything outside the scratch folder; `scratch_server` starts `dev_server.py` there on an ephemeral port and stops it through `.manage_pids/dev.stop`; autouse guard against in-process imports of application modules. Since 5.08 also: seeded accounts `qa_writer` (readwrite) and `qa_reader` (readonly), `scratch_server.client()` / `login_as()` / `db()` / `make_user()` / `.storage`, and a cookie-aware `HttpClient` / `Reply` (no redirect following, own fake client IP per client, `api()` adds the CSRF and JSON headers). | It never runs the application in-process and does not start protocol servers or the Version Engine. 5.40: `build_scratch(config=...)` merges extra settings into the scratch `server_config.json`; `start_scratch_server()` / `stop_scratch_server()` are the one place that launches and stops a scratch `dev_server.py` (also exposed as `scratch_tools.start_server` / `stop_server` / `seed_users` for the restart tests); fixtures `scratch_server` and `scratch_server_with_versions` (Version Engine on, tracking the scratch storage). |
| [../tests/dir_tree.py](../tests/dir_tree.py) | Walks a filtered directory tree (`collect_entries()`, `build_tree()`), prints it and saves it to `docs/DIRECTORY_TREE.md`. | It is a diagnostic utility, not a product behavior test. Run it with `./manage.sh dir-tree` (menu 26); it takes no options. It rewrites `docs/DIRECTORY_TREE.md` (creating `docs/` if needed) and skips that file itself; regenerate and commit it after files are added, moved or removed. `EXCLUDE_DIR_WALK` matches folder names only. |
| [../tests/qa.py](../tests/qa.py) | The one QA runner for developers, `manage.sh` (the `qa` command, menu 21-25) and GitHub: `static` (smoke, check, SRI, `node --check`), `tests` (pytest on every existing layer folder), `quick`, `layer <name>`, `ci` (JUnit XML to `./artifacts`), `audit`, `coverage` and, since 5.41, `lint` (Ruff, report only; `--strict` fails on a finding; menu 30); prints PASS/FAIL/SKIP per step, exit 1 on any failure (including a `layout` FAIL when a `test_*.py` file sits directly in `tests/` instead of a layer folder), never passes `--force`; `python tests/qa.py --version` prints which copy you run; the "pip install" hint appears only when pytest cannot be imported. | A SKIP (missing tool or folder) is not a pass of that check. |
| [../tests/smoke.py](../tests/smoke.py) | Read-only project safety checks: syntax, optional pyflakes, route/endpoints, hooks, import cycles/layering, route-module registration, tool launch paths, shell syntax, and route snapshot changes. | Does not import/start the app, issue HTTP requests, or test filesystem/runtime behavior. Run it with `./manage.sh smoke [--save\|-v\|--files]`; options pass straight through. `--save` intentionally updates the route snapshot, runs all checks first and saves even if one failed; menu 27 (`smoke --save`) asks y/N before saving. |
| [../tests/smoke_routes.json](../tests/smoke_routes.json) | Baseline route signature consumed by `smoke.py`. | Update only when route additions/removals are intended and reviewed. |
| [../tests/unit/](../tests/unit/) | `test_paths.py` (every `paths.py` getter, setter, reset, merge-safe save, corrupt config), `test_scratch_copy.py` (the harness isolates everything and the guard catches outside paths), `test_qa_runner.py` (plan selection, exit codes, skip handling, the stray-file `layout` check), `test_setup_pymodules.py` (the `append_req_line()` function of `setup_pymodules.sh`, run in bash), `test_http_client.py` (the HTTP client and scratch helpers of `conftest.py`), `test_response_timeout.py` (parses `core.py`: Quart's 60 s `RESPONSE_TIMEOUT` must be switched off; strict xfail until the 5.11 patch is applied), `test_session_revocation.py` (logout ends the session on the server, the two `revoked_sessions` methods), `test_recover_uploads.py` (startup recovery assembles only complete uploads), `test_client_ip_trust.py` (`get_client_ip()` trusts the proxy headers only from a loopback peer), `test_webdav_client_ip.py` (the same rule for the WebDAV audit address), `test_rate_limiter_keys.py` (`RateLimiter` buckets by key), `test_revoke_code_generation.py` (the revoke-all code is made with `secrets`, never `random`), `test_upload_chunk_keys.py` (chunk keys per session and `storage.chunks_complete`), `test_manage_qa.py` (the Quality Assurance and Developer Tools sections of `manage.sh`: menu numbers 1-27 agree between listing, dispatch and help (`LAST_ENTRY` = 27); the `qa` modes; the `dir-tree` and `smoke` commands and menu 26-27; exit codes), `test_assemble_atomic.py` (5.38, extended in 5.40: the atomic publish and the bounded retry of a busy target, read out of `storage.py` with `ast`), `test_monitor_handler.py` (5.40: the counters and the calls into the folder and search indexes of `file_monitor.InstantFileEventHandler`, including the hidden-rename fix), `test_monitor_cache.py` (5.40: `storage_index.json` save, load, validation, repair, stale temp files, and a Hypothesis fuzz of the loader), `test_upload_perf.py` (stage timer, lag probe, idle deferral, in-memory multipart parse; 5.41), `test_upload_body_paths.py` (the real upload helper functions on a toy Quart app, and an `ast` guard that `upload()` does no chunk I/O itself), `test_upload_settings.py` (defaults off, save / load / display, validation, `BODY_TIMEOUT` reaches Quart), `test_version_engine_scope.py` (`.chunks` never tracked, slow-pass log)., `test_file_body.py` (the file response read size on real Quart; 5.42), `test_scratch_environment.py` (GIL parity of the scratch servers for both Python builds, `CLOUDINATOR_SCRATCH_CONFIG`), `test_dev_server_identity.py` (`dev_server.py` stays the dev server), `test_async_handlers_no_blocking.py` (5.44: the ratchet of section 8.2, `ast` over `routes/*.py`, `middleware.py` and `core.py`, with a self-test of the scanner), `test_stream_from_thread.py` (5.44: the zip-stream worker ends and closes its generator when the consumer leaves), `test_chunk_tracker_lock.py` (5.44: the tracker lock is free while a delete runs; thresholds unchanged), `test_storage_stats_cache.py` (5.44: one walk for parallel callers, 30 s cache, failures not cached), `test_abandoned_upload_cleanup.py` (5.44: the page-load cleanup helper and that `before_request` hands it to a thread), `test_request_auth_memo.py` (5.44: one login lookup per request, and when the memo must NOT be used), `test_database_connect.py` (5.44: WAL and folder once per process, `foreign_keys` on every open, the slow-open line), `test_image_preview_waiters.py` (5.44: waiting requests are woken by futures, not by parked pool threads), `test_versions_stream_close.py` (5.44: the versions download never closes its generator on the loop), `test_walk_executor.py` (5.44: the walk pool, 2 at a time, default pool untouched), `test_upload_progress_js.py` (5.44.1: the upload progress math of index.js, run in Node, skipped without node), `test_version_engine_backoff.py` (5.44.1: the engine waits in proportion to its pass; watcher and scanner never run the same pass together), `test_manage_log_follow.py` (5.44.1: `logs -f` moves to the next day's file after midnight), `test_is_safe_path_error_branch.py` (5.44.2: `storage.is_safe_path` answers exactly `False` when the check itself raises; the branch is unreachable with a real path on Linux, so the test makes `os.path.commonpath` / `realpath` raise), `test_dev_server_coverage_save.py` (5.44.3: `dev_server._save_coverage_data()` read with `ast`, run against a fake `coverage`; the save sits before `os._exit(0)`), `test_index_js_logic.py` (5.44.3: `_resolveFileConflict`, `_classifyChangedDirs` and `_sameListing` of index.js in plain Node, cut out by name), `test_static_check_skip_dirs.py` (5.44.3: `smoke.py` and `check.py` skip the same folders, including a local `build/`), `test_purge_missing_versions.py` (5.44.4: which tracked files `tools/purge_missing_versions.py` calls gone, what it counts and changes, on the engine's real schema) | Not application behavior beyond `paths.py`. |
| [../tests/property/](../tests/property/) | `test_properties.py` (5.40): Hypothesis properties of `storage.is_safe_path`, `storage.is_safe_chunk_id`, the chunk keys of `routes/uploads.py` and the path helpers of `file_monitor.py`; deterministic unless `CLOUDINATOR_NIGHTLY=1`. | Runs in the required check (about 3 s); needs `hypothesis`. |
| [../tests/reliability/](../tests/reliability/) | `test_version_engine_live.py` (the real Version Engine worker captures a new and a changed file; fixture `scratch_server_with_versions`), `test_concurrency.py` (parallel users with the same upload id, parallel chunks of one upload, parallel logins, reads during assembly, read latency during uploads), `test_restart.py` (graceful stop, crash and restart: accounts and files survive, an interrupted upload publishes nothing), `test_version_engine_crash.py` (5.44.3: a killed server leaves no worker, the restart catches up with changes made while it was down, earlier versions restore byte for byte; a dead worker does not take the web application down). | OPT-IN (`CLOUDINATOR_SLOW_TESTS=1`, nightly); a failure can be a real race: keep the log. Written in 5.40; first real runs in 5.44.2 (Linux and Windows, green after one test fix: the 12-chunk test now sends with one CSRF token, see section 18). |
| [../tests/frontend/](../tests/frontend/) | `test_browser_smoke.py` (5.40): a real Chromium (or `CLOUDINATOR_BROWSER_CHANNEL=msedge`) loads `/login`, logs in and opens the file manager; fails on a script error, a failed request, an HTTP error or an SRI mismatch; the Document-Policy `document-write` console message is ignored. `test_browser_flows.py` (5.44.3, own scratch server): an upload lands on disk and in the table, "Overwrite all conflicts" is asked once for loose files, a 400-entry folder keeps the DOM small and a deep scroll shows rows. | OPT-IN, needs Playwright; `test_browser_flows.py` has not been run yet (check its selectors first if it fails). |
| [../tests/mutation_trial.py](../tests/mutation_trial.py) | Standard-library mutation trial (5.40): makes one small mistake at a time in named functions inside a temporary copy and reports the ones the named tests do not catch. | Not part of `qa quick` / `qa ci`; manual workflow `mutation.yml`. |
| [../tests/protocols/](../tests/protocols/) | `conftest.py` (`protocol_lab`: scratch copy with the accounts `qa_writer` / `qa_reader`; `launch`: starts one protocol server from the copy as a separate process on an ephemeral port and stops it) `test_webdav_protocol.py` (HTTPS listener and plain fallback: Basic auth, readwrite cycle, readonly 403 on every write method, role changes after the 30 s credential cache, containment, no plaintext listener next to TLS, certificate download, HTTP/1.1 only; one strict xfail: the plain listener never opens because `insecure_bind` is ignored without TLS) and `test_sftp_protocol.py` (logins, readwrite and readonly file operations, containment, weak ciphers and MACs refused, no forwarding or commands; one strict xfail: the role is read once per session) and `test_ftp_protocol.py` (FTP fallback and FTPS: logins refused, the whole file cycle for a readwrite account, every change refused for a readonly account, roles read from the database on every command, nothing leaves the storage root, FTPS needs TLS on control and data). | Real protocol servers over real sockets (5.26); about 1 minute (bcrypt logins). SMB follows. Run with `python tests/qa.py layer protocols` (also part of `qa quick`); marker `protocol`. |
| [../tests/performance/](../tests/performance/) | `test_slow_download.py`: opt-in (`CLOUDINATOR_SLOW_TESTS=1`) proof that a 200 MB download throttled to about 2.5 MB/s (80 s) arrives complete; `test_baselines.py` (5.40): a 24 MB chunked upload, login latency, read latency and eight parallel readers, each with a deliberately loose upper bound; the measured numbers are printed and recorded as JUnit properties. | Needs about 85 s (+ about 1 minute); skipped by default. |
| [../tests/application/](../tests/application/) | `test_path_containment.py` (traversal against 11 read routes, sibling-folder and chunk-id escapes on the read, write, share and upload paths, legitimate-use controls; both holes it found are fixed and the tests keep them closed), `test_upload_integrity.py` (chunk ordering, no wrong file ever published; two recorded xfails: upload ids collide between users, assembly starts at the last chunk number), `test_login.py` (login page headers and cookie flags, CSRF, login, lockout, logout, session invalidation, a copied cookie refused after logout on every kind of route), `test_shares.py` (share links: public / passkey / approval gates, expiry, revocation, folder confinement, revoke-all code), `test_share_hardening.py` (passkey attempt limit per client and link, `/api/share` on an already shared item reports what the link really has), `test_version_restore.py` (version history on the real engine: restore, download, delete, retention, refusals), `test_version_routes.py` (the HTTP routes `/api/versions/*` and `/download/recovered/*`: input validation, JSON shape, headers, the cross-file guard over HTTP, recovered-file containment), `test_file_index_recovery.py` (file index: damaged, foreign and stale files, walks, audit), `test_file_monitor_recovery.py` (`file_monitor.py` with no server and no watchdog: damaged, foreign and half-valid `storage_index.json`, the walk's numbers, save only on change, rejected suspect-empty and unreadable-root walks, per-folder correction against a fresh walk, file index kept in step, the app's own folders ignored) and `test_authorization.py` (anonymous sweep over every declared route against the reviewed `PUBLIC_ENDPOINTS`, readonly refusals, role changes), plus `test_boot.py`: starts the real app from the scratch copy and checks `/login`, `/robots.txt`, anonymous `/`, that data folders were created only in the scratch tree and that the real `storage_config.json` / `server_config.json` are untouched. | Login, CSRF, lockout, session, authorization, containment, upload integrity and share links (5.18); version history and file-index recovery on the real modules (5.19, no server: they run snippets in their own scratch copy with `scratch_tools.run_in_scratch`); the HTTP routes `/api/versions/*` are driven in the normal scratch server (5.22): `version_history.init()` runs in `core.py` even with the engine subprocess off, and versions are captured by a snippet that calls `Engine.snapshot_file()` through `server.db()`; the engine's worker, watcher and scanner threads are not covered; `test_async_offload_routes.py` (5.44: `/mkdir`, `/delete`, `/bulk_delete`, `/api/dir_info`, `/api/check_conflicts`, `/api/storage_stats_slow` and `_debug`, `/cleanup_chunks`, `/admin/cleanup_chunks`, `/admin/chunk_stats`, `/logout` with an unfinished upload and a ZIP download larger than the hand-over queue answer exactly as before the move into worker threads), `test_purge_missing_versions.py` (5.44.4: `tools/purge_missing_versions.py` against the REAL Version Engine in a scratch copy; the tool is copied into the scratch `tools/` so it imports the copy's modules). |

### 25.6 Frontend source and stylesheets

| File | What it implements | Keep coordinated with |
|---|---|---|
| [../static/js/404.js](../static/js/404.js) | Delayed redirect to the home page; user interaction cancels it. | `templates/404.html` and `static/css/404.css`. |
| [../static/js/bg_audio.js](../static/js/bg_audio.js) | Background audio autoplay attempt, localStorage state/position persistence, interaction fallback. | The `#bgMusic` element/source in all templates that load it; SRI hashes there. |
| [../static/js/index.js](../static/js/index.js) | Main file-manager client: CSRF fetch wrapper, delegated actions, virtualized listing and deep search, upload queues, file actions, media/document viewers, shares, versions, storage SSE/polling and admin actions. | `templates/index.html` DOM/config data, route JSON/HTTP contracts, `index.css`, and SRI hashes. Mounted table rows are not the full virtualized result set. |
| [../static/js/login.js](../static/js/login.js) | Login page session redirect/check behavior, submit feedback and lockout countdown. | Form IDs/markup and login response/flash behavior. |
| [../static/js/shared.js](../static/js/shared.js) | Public share passkey/access-request submission, status polling, shared-folder browsing and selected downloads. | `templates/shared.html` data attributes/form IDs and `routes/shares.py` contracts. |
| [../static/js/pdfjs-worker-init.mjs](../static/js/pdfjs-worker-init.mjs) | App-owned bootstrap for PDF.js worker/resource paths and preference/sample-document behavior. | PDF.js version, `templates/index.html` module order, PDF.js viewer root and local assets. |
| [../static/css/404.css](../static/css/404.css) | Not-found page layout and responsive styling. | `404.html` class names. |
| [../static/css/index.css](../static/css/index.css) | File-manager UI, responsive table, virtual-scroll spacers, modals, upload/share/version components, viewer and background layout. | `index.js` class/ID contracts and CSP constraints; static CSS changes require template SRI updates. |
| [../static/css/login.css](../static/css/login.css) | Login form, flash/error/loading states and responsive presentation. | `login.html` structure and `login.js` state classes. |
| [../static/css/pdfjs-viewer-overlay.css](../static/css/pdfjs-viewer-overlay.css) | App-owned isolation/overrides for bundled PDF.js styles inside the preview modal. | Upstream `viewer.css`, `index.css`, and PDF modal markup. |
| [../static/css/shared.css](../static/css/shared.css) | Public share/gate/browse page styling and responsive states. | `shared.html` structure and `shared.js` state/class updates. |
| [../static/css/video-skin-overrides.css](../static/css/video-skin-overrides.css) | App-owned video-player shadow-root styling, including small-screen controls and captions. | Video.js web component/shadow DOM selectors and template player setup. |

### 25.7 Templates

| File | Rendered page and contracts |
|---|---|
| [../templates/404.html](../templates/404.html) | Not-found UI; loads 404 CSS/JS, icons, and shared background audio. |
| [../templates/index.html](../templates/index.html) | Authenticated file manager; owns server-to-client configuration, CSRF meta, initial listing data, control IDs, modals, PDF.js/video player markup and local assets. The explicitly marked stock PDF.js viewer block is upstream; wrapper and app integrations are project-owned. |
| [../templates/login.html](../templates/login.html) | Login form, CSRF field, flashed messages, lockout feedback and login assets. |
| [../templates/shared.html](../templates/shared.html) | Public share/gate state, token/security/request URLs, download/browse markup and share-page assets. |

Template IDs, `data-*` properties, endpoint names and asset order are executable interfaces to the JS, routes and SRI validator; change both sides together.

### 25.8 Shell scripts and configuration/data files

| File | Purpose |
|---|---|
| [../manage.sh](../manage.sh) | Operator CLI/menu for server start/stop/restart/status/logs and wrapped utilities; also handles PID/log management, WebDAV restart, security.txt and SRI operations, the Quality Assurance section (menu 21-25 and the `qa` command, which only call `tests/qa.py`) and the Developer Tools section (menu 26-27: `dir-tree` runs `tests/dir_tree.py`, `smoke [options]` runs `tests/smoke.py`; menu 27 is `smoke --save` and asks y/N first); the menu numbering (`LAST_ENTRY`, now 27) is enforced by `tests/unit/test_manage_qa.py`. `stop` is two-stage (graceful stop file / SIGTERM, then process-tree kill) and always sweeps WebDAV and Version Engine leftovers. |
| [../setup_pymodules.sh](../setup_pymodules.sh) | Generates `requirements.txt`/`constraints.txt`, resolves package constraints, handles Termux system packages and offers installation. New package lines are appended through `append_req_line()` (adds a missing final newline first; keeps CRLF files CRLF, detected from an `od` hex dump and written with `printf` escapes; never `grep` / `head` / `$(...)` for a CR, because they hide it in Git Bash); `tests/unit/test_setup_pymodules.py` covers it. The install branch creates and activates `.venv` (`.venv/bin` on Linux and Termux, `.venv/Scripts` on Windows Git Bash; on Termux with `--system-site-packages` so the `pkg` packages stay visible) and installs inside it; the venv block is tested too. |
| [../.gitattributes](../.gitattributes) | Line-ending policy: LF for every text type, `binary` for images/fonts/wasm. Do not remove entries: SRI hashes depend on it. |
| [../termux_setup.sh](../termux_setup.sh) | Installs Termux native/Python prerequisites with retry logic and requests shared-storage permission. |
| [../requirements.txt](../requirements.txt) | Declares Python dependency ranges used by setup. Update alongside imports and compatibility-sensitive protocol libraries. |
| [../constraints.txt](../constraints.txt) | Generated/platform package constraints, particularly Termux-managed packages; regenerate through the setup workflow rather than hand-editing without reason. |
| [../server_config.json](../server_config.json) | Persisted runtime/server/protocol/feature settings loaded by `config.py`. |
| [../storage_config.json](../storage_config.json) | Persisted storage, database and cache directory overrides read by `paths.py`. |
| [../.github/workflows/tests.yml](../.github/workflows/tests.yml) | GitHub Actions on every push / pull request to `main` and `dev`: job `smoke + check` (`tests/smoke.py`, `tests/check.py`) and job `behavioral tests` (`python tests/qa.py ci`). |
| [../.github/workflows/lint.yml](../.github/workflows/lint.yml), [nightly.yml](../.github/workflows/nightly.yml), [mutation.yml](../.github/workflows/mutation.yml), [audit.yml](../.github/workflows/audit.yml), [coverage.yml](../.github/workflows/coverage.yml) | Report-only Ruff; the nightly full run (Linux + Windows, slow tiers on); the manual mutation trial; the weekly dependency audit; the weekly coverage report (optional `fail_under` input). None is a required check. See 18.1. |
| [../.github/dependabot.yml](../.github/dependabot.yml) | Weekly version-update pull requests (pip, GitHub Actions) into `dev`. |
| [../pyproject.toml](../pyproject.toml) | Tool configuration only (no `[project]` / `[build-system]`): `[tool.pytest.ini_options]` with `pythonpath = ["."]`, `--import-mode=importlib` (tests/ has no `__init__.py`), `timeout = 120`, markers; `[tool.coverage.*]`; `[tool.ruff]` (5.40: `E`, `F`, `B`, `S`, report only, per-file ignores with reasons). Do not keep a `pytest.ini` next to it: pytest would use that instead. |
| [../requirements-dev.txt](../requirements-dev.txt) | Test-only packages (`pytest`, `pytest-timeout`, `pip-audit`, `coverage`, `hypothesis`, and `ruff` pinned exactly); not managed by `setup_pymodules.sh`. Deliberately NOT merged into `requirements.txt` / `setup_pymodules.sh`: that is the production dependency list, and the script rewrites constraints to `<next_major` and drops version floors. |
| [../.github/workflows/codeql.yml](../.github/workflows/codeql.yml) | GitHub Actions: CodeQL for Python and JavaScript on `main` and `dev` plus a weekly run; stores SARIF and CSV artifacts. |
| [../.github/codeql/codeql-config.yml](../.github/codeql/codeql-config.yml) | CodeQL configuration: `paths-ignore` for vendored third-party files (pdf.js, video.js, Font Awesome). |
| [../README.md](../README.md) | Project overview, installation and usage; keep its command examples in sync with `manage.sh` and `tools/`. |
| [../LICENSE](../LICENSE) | Project license. |
| [../.gitignore](../.gitignore) | Files kept out of git (logs, caches, bytecode, machine-specific data); keep generated folders such as `__pycache__/` covered. |
| [../static/robots.txt](../static/robots.txt) | Static crawler policy served by `routes/site_meta.py`. |
| [../static/.well-known/security.txt](../static/.well-known/security.txt) | Static security contact/expiry/language/canonical metadata served by `routes/site_meta.py`. |

### 25.9 Vendored, generated, and binary resources

These files exist in the repository but are not first-party implementation modules. Their licenses, headers, and directory structure were inspected to classify ownership; their internals were not all read line by line. Prefer upstream upgrades over local edits, and keep app-owned integration files separate.

| Path/group | Classification and project relationship |
|---|---|
| [../static/js/pdf.mjs](../static/js/pdf.mjs), [../static/js/pdf.worker.mjs](../static/js/pdf.worker.mjs), [../static/js/viewer.mjs](../static/js/viewer.mjs), [../static/css/viewer.css](../static/css/viewer.css) | Bundled Mozilla PDF.js runtime/viewer and upstream CSS. `pdfjs-worker-init.mjs` and `pdfjs-viewer-overlay.css` are the app-owned integration layer. |
| [../static/js/video.js](../static/js/video.js), [../static/css/video.css](../static/css/video.css) | Bundled Video.js/web-component player runtime and stylesheet; `video-skin-overrides.css` is app-owned. |
| [../static/css/all.min.css](../static/css/all.min.css), [../static/webfonts](../static/webfonts) | Minified Font Awesome CSS and its binary fonts. |
| `static/js/cmaps/`, `static/js/iccs/`, `static/js/standard_fonts/`, `static/js/images/`, `static/css/images/`, `static/js/locale/` | PDF.js support data, profiles, fonts, viewer icons and translations; not app feature logic. |
| `static/js/wasm/*.wasm` and generated fallback JS | WebAssembly binaries and generated PDF.js support runtimes. Generated headers warn against manual edits. |
| [../static/audio/bg_mus.opus](../static/audio/bg_mus.opus), [../static/icons/icon.webp](../static/icons/icon.webp), `images/page/*`, `images/scanner/*` | Binary media/icon/documentation screenshots, not executable code. |

**Read coverage for this reference:** the first-party Python source (root, `routes/`, `helpers/`, `tools/`, and `tests/`), maintained JavaScript/MJS and CSS, templates, root shell scripts, requirements/constraints, JSON runtime configs, and static text policy files were read from start to end. Vendor bundles, minified CSS, translation catalogs, CMaps, generated fallback code, WASM/font/image/audio binaries were classified from their metadata, headers, licenses and directory structure; they were not treated as first-party source and were not fully read internally. Documentation under `docs/` is a separate body of operator/deployment material; this coding reference links to it where relevant but does not claim every documentation page was read line by line.

## 26. Requested frontend files: implementation notes

This section gives a closer implementation guide for the exact CSS and JS/MJS files called out for documentation. “Modify” means the project-owned source that should normally change; the bundled viewer/player files are identified so their app integrations are not confused with upstream implementation.

### 26.1 CSS files

#### [../static/css/404.css](../static/css/404.css)

Styles the standalone error page in [../templates/404.html](../templates/404.html). The file is organized around a full-viewport centered page, animated radial-dot background (`body::before` / `@keyframes float`), translucent `.error-container`, entrance animation (`slideIn`), pulsing `.error-icon`, and the error title/message/actions/details (`.error-title`, `.error-subtitle`, `.error-message`, `.error-actions`, `.error-details`). `.btn`, `.btn-primary`, and `.btn-secondary` are shared action styles used by the template.

When adjusting the page, preserve vertical scrolling for long error text and the small-screen rules at the end of the stylesheet. Keep the class names aligned with `404.html`; the redirect/cancel interaction is in [../static/js/404.js](../static/js/404.js), not CSS. This asset is linked from the template and has an SRI hash, so edits require `./manage.sh validate-sri --fix`.

#### [../static/css/index.css](../static/css/index.css)

This is the main file-manager stylesheet. It is a layered cascade with final responsive/override sections near the end; before changing an early rule, search later in this same file for a more specific override. Main areas are:

- Page foundation and animated background: `body`, `body::before`, `body::after`, `--doc-height`, `--mx`, `--my`, and `--scroll-light`. [../static/js/index.js](../static/js/index.js) measures document height and updates pointer/scroll variables. The layers must cover the document, not only the viewport; reduced-motion rules hide the animated glow.
- Header, role badge, breadcrumbs, toolbar, manual/admin actions and bulk-action controls.
- File table and scrolling: `.file-table`, `#tableScrollWrapper`, sticky table headers, custom scrollbars, `.vt-*` spacer/loading classes for the normal virtual table and `.ds-*` loading classes for deep search. The virtualizer in `index.js` positions spacer cells dynamically; avoid forcing a row height on those spacer rows or adding markup styles that conflict with CSP.
- File names, icons, action buttons, directory-size cells, and responsive column widths (the Actions column width itself comes from `_actionsColWidth()` in `index.js`, not from this file). The columnizer in `index.js` writes some inline CSSOM `!important` values; a weaker selector in this file may not override those values. Preserve wrapping behavior and the `.search-highlight` inline-span rules.
- Upload section, queue, parallel-upload controls, per-file/folder progress, status notifications, and stacked notification layouts. Their IDs/classes are manipulated by upload functions in `index.js`.
- Modals and viewer content, including move/copy and share/version dialogs; share create/security/manage panels; folder browser; storage-stat cards; search results and sorting controls.
- Responsive layout blocks for mobile, small mobile, tablet, portrait large mobile, landscape and coarse pointers. Multiple late rules deliberately override earlier generic rules; test at more than one breakpoint after edits.

When changing a selector used by generated rows or modal content, search [../static/js/index.js](../static/js/index.js) for the class/ID creation and mutation. For share browser styles also check [../static/js/shared.js](../static/js/shared.js) and [../static/css/shared.css](../static/css/shared.css). The PDF overlay is intentionally separated into [../static/css/pdfjs-viewer-overlay.css](../static/css/pdfjs-viewer-overlay.css). Avoid literal inline-style additions in templates: CSP configuration is in [../core.py](../core.py). After CSS edits, refresh template integrity hashes and verify the actual browser layout, especially virtual scrolling and mobile widths.

#### [../static/css/login.css](../static/css/login.css)

Styles [../templates/login.html](../templates/login.html): full-screen gradient and animated particle backdrop, centered `.login-container`, header/subtitle, `.form-group`, `.input-wrapper`, `.form-control`, `.btn-login`, flashed errors and footer. `login.js` adds form loading state and scales an input's parent on focus/blur; lockout text is presented through `.flash-messages` / `.flash-message`.

Keep control IDs and class names aligned with the template and [../static/js/login.js](../static/js/login.js). Check narrow viewport sizing and text wrapping when changing the fixed desktop card width/padding. This stylesheet is SRI-referenced in the login template; run the SRI validator after editing.

#### [../static/css/pdfjs-viewer-overlay.css](../static/css/pdfjs-viewer-overlay.css)

App-owned integration overrides for the upstream [../static/css/viewer.css](../static/css/viewer.css), which assumes it owns the whole document. This file undoes the upstream `:root`/`body` effects that would leak PDF viewer color-scheme, margins and scrollbar styling onto the file manager, while preserving the app's animated document-spanning background. Do not set a competing `body` background here: `index.css` paints the background through pseudo-elements and this later-loaded stylesheet would win the cascade.

The `#pdfjsViewerRoot` rules place the viewer as a flex child inside the file-viewer modal, after its header, and make `#outerContainer` / `#mainContainer` fill that root. Mobile rules make the PDF toolbar horizontally scrollable and compact its controls. Keep this aligned with the PDF DOM in [../templates/index.html](../templates/index.html), the modal open/close code in [../static/js/index.js](../static/js/index.js), and upstream `viewer.css`. Do not patch vendor CSS to fix an app integration issue. This local CSS has an SRI hash in the template.

#### [../static/css/shared.css](../static/css/shared.css)

Styles the public share page in [../templates/shared.html](../templates/shared.html), including the centered card, status/security icon variants, metadata/description, download action, passkey/request forms, error states and spinner. The folder-browser section styles breadcrumbs, scrollable `.browser-list`, `.browser-row`, checkboxes, icons, names, sizes, buttons, selection bar and empty/loading/error states emitted by [../static/js/shared.js](../static/js/shared.js).

When changing dynamic browser markup, update the corresponding selector and escaping/DOM behavior together in `shared.js`; do not assume a browser row is server-rendered. Keep card width and overflow usable on narrow screens and long filenames. This stylesheet is loaded from the shared template and requires SRI refresh after edits.

#### [../static/css/video-skin-overrides.css](../static/css/video-skin-overrides.css)

Small app-owned stylesheet injected into the `<video-skin>` shadow root by `_injectMobileSpeedHide()` in [../static/js/index.js](../static/js/index.js). At widths up to 600px it hides the playback-rate control selectors; `::cue` styles captions for readable white text with dark outline/shadow.

This file is deliberately external rather than generated as a `<style>` element, so it is allowed by the app's `style-src-elem 'self'` policy without adding a CSP hash. If a Video.js upgrade changes shadow-root selectors, update this stylesheet and the injection URL together; validate that the stylesheet link is accepted inside the shadow root and refresh the SRI hash in `index.html`.

#### [../static/css/viewer.css](../static/css/viewer.css)

This is the upstream Mozilla PDF.js viewer stylesheet (Apache-2.0 header), not the app's general-purpose CSS. It supplies the PDF viewer's toolbar, sidebar, page canvas/text/annotation layers, dialogs, print/download controls, themes and accessibility/forced-color behavior. It contains document-level selectors and assumes the viewer owns a standalone page, which is why it can affect `html`/`body` when merged into the app.

Treat it as a vendored asset: do not make local feature changes here. Put host-page corrections in [../static/css/pdfjs-viewer-overlay.css](../static/css/pdfjs-viewer-overlay.css), update the upstream bundle as a unit when upgrading PDF.js, then check the viewer root markup, `viewer.mjs` version, worker/resources and SRI hashes. Its binary/resource URLs also depend on the PDF.js asset tree under `static/js/`.

### 26.2 JavaScript and module files

#### [../static/js/404.js](../static/js/404.js)

Starts a ten-second timer to navigate to `/`. A document click or keydown cancels that timer so an interacting visitor is not redirected away. It has no server API dependency; the matching page is [../templates/404.html](../templates/404.html) with styles in [../static/css/404.css](../static/css/404.css).

The `countdown` variable is currently declared but not used to update a visible counter. If adding one, add/identify a matching DOM element in the template and make timer cleanup cover navigation and repeated interaction; do not assume the existing variable currently drives UI.

#### [../static/js/bg_audio.js](../static/js/bg_audio.js)

An IIFE that initializes the `#bgMusic` element when the DOM is ready. It sets volume to 0.20, restores `currentTime` from `cloudinator_bg_music_time` after metadata is loaded, and attempts playback if the saved state says playing or has never been set. Browser autoplay rejection is intentionally swallowed; capture-phase pointer/mouse/click/key/touch listeners remain armed until playback actually succeeds.

`timeupdate`, `play`, and `pause` maintain the two localStorage keys. `beforeunload` and `pagehide` save position while marking the page as leaving so a teardown pause does not overwrite the saved play state. To change behavior, coordinate the storage keys/audio element with the identical audio markup in the templates that include it. Browsers may still block autoplay; the interaction fallback is required. Update SRI hashes in every template referencing this script.

#### [../static/js/index.js](../static/js/index.js)

The main browser application script. It is composed of subsystems in one file; locate the existing subsystem before adding another global handler or state store:

1. **Request/security and action dispatch:** wraps same-origin state-changing `window.fetch` calls to attach a CSRF token, refresh/retry once for a CSRF-related 400, and exposes refresh helpers. Delegated document handlers dispatch `data-fn`, `data-fn-change`, `data-fn-keyup`, and `data-fn-error`; `dataArgs()` safely serializes handler arguments. `encodePathForUrl()` encodes each path segment while preserving separators. New controls should use this existing dispatcher rather than inline event attributes.
2. **Table sizing and modal/event protections:** `smartTableColumnizer()` / `applyColumnWidths()` manage responsive columns (the Actions column width is decided in one place, `_actionsColWidth()`: it must cover the row buttons AND the header label, because the `<th>` clips its text, so update it when a row button or the header label changes); modal input protection prevents global delegated actions from stealing modal interactions. Authentication/history checks run during page initialization.
3. **Search:** local filtering operates on the current table data; deep search parses text/extension filters, calls the search API, pages results, and maintains a separate virtualized window/data model. `_ds*` functions build offsets, mount rows, fetch pages, preserve selection, sort/reset and measure variable-height results. Do not derive total results or selection state from mounted DOM rows. Highlight helpers escape content; pass raw text to `highlightText()`.
4. **Normal file table (`VT`):** the `VT` module owns the full current directory list, filter/sort state, row-height cache, offset index, scroll-window mounting and selection-facing data. `createFileTableRow()` creates normal rows; `loadDirInfoCells()` updates folder cells from the directory-info API and reports height changes to VT. Preserve the virtualizer's spacer-cell sizing and native scroll anchoring rules documented in the surrounding code; DOM rows only represent the viewport window.
5. **Navigation, listing and file actions:** `navigateToFolder()` fetches directory data, updates breadcrumbs/history and initializes the table. Related functions implement download/view, rename/delete/mkdir, bulk actions, conflict handling, selected-item state, and scroll-to-renamed-item behavior. URL construction must use path-segment encoding and API payload changes must match `routes/files.py`.
6. **Uploads:** file/folder queueing, parallel upload configuration, chunked XHR, assembly progress, cancellation and upload-protection state coordinate with `/upload`, chunk/assembly APIs, and `routes/uploads.py`. Keep progress IDs/state and CSRF refresh for XHR aligned with the template and server contracts.
7. **Preview and viewer integrations:** image metadata/conversion/status, video/HLS playback, Office/archive previews, and PDF.js opening/closing coordinate with `routes/image_preview.py`, `routes/hls.py`, `routes/previews.py`, and the modal markup in `index.html`. `_injectMobileSpeedHide()` loads `video-skin-overrides.css` into the player shadow root. PDF.js is bootstrapped by `pdfjs-worker-init.mjs` before the bundled `viewer.mjs` module.
8. **Shares, versions and admin UI:** share forms/manage tabs, request updates, version-history controls, cache rebuild state and other admin operations call their route APIs and maintain UI locks/state across DOM repaints. Preserve existing server response/status handling, especially `202` background jobs and `409` attach-to-existing operations.
9. **Live updates and page lifecycle:** storage SSE with polling fallback, catch-up/change sequence tracking, visibility pause/resume, notification timers, online/offline handling, and document-height/pointer background updates. Coordinate payload changes with `realtime_stats.py`, `realtime_shares.py`, `routes/stats.py`, and the monitor; hidden-tab resume relies on sequence/epoch replay.

The DOM contract is defined jointly with [../templates/index.html](../templates/index.html); styles and virtualizer selectors are in [../static/css/index.css](../static/css/index.css). Before changing a control, search for its template ID/class, dispatcher name, route URL and response consumer. After changing JS, run `node --check static/js/index.js`, update template SRI, then test sorting/filtering/scrolling, uploads, session-expiry and browser behavior as applicable.

#### [../static/js/login.js](../static/js/login.js)

On DOM ready it removes the `logged_out` query marker and skips the logged-in redirect for a logout return; otherwise it fetches `/` without cache to see whether an existing session redirects away from login. The form submit handler displays a loading label, `.form-control` focus/blur scales the containing element, and an IIFE parses a “Try again in N seconds” flash to disable inputs/button until lockout expires. When the page becomes visible again, it probes `/admin/upload_status` and redirects home if authorized.

It depends on `loginForm`, `loginBtn`, `flashText`, `username`, and `.form-control` in [../templates/login.html](../templates/login.html), with presentation in [../static/css/login.css](../static/css/login.css). If changing the server lockout message, update the countdown parser too; its regular expression is coupled to the displayed text. The file is SRI-referenced.

#### [../static/js/pdfjs-worker-init.mjs](../static/js/pdfjs-worker-init.mjs)

App-owned PDF.js bootstrap module. `index.html` must load this non-async module before `viewer.mjs`; the module imports `GlobalWorkerOptions` from the local PDF.js runtime, then listens once for `webviewerloaded` to configure `PDFViewerApplicationOptions` before the bundled viewer applies defaults. It disables PDF.js preference persistence and clears its development sample PDF default, then sets absolute `/static/js/...` paths for worker, CMaps, ICC profiles, standard fonts, WASM and image resources.

The early direct `workerSrc` assignment alone is not durable because viewer initialization overwrites it; retain the `webviewerloaded` options update. On a PDF.js upgrade, verify the event timing, option names, local bundle paths and module order, then test opening a real PDF from the app modal. Refresh the SRI hash for this module.

#### [../static/js/shared.js](../static/js/shared.js)

Public-share page controller. At DOM ready it reads `body.dataset.securityMode` and initializes a passkey form or approval-request form/status poll; when the server marks a directory share unlocked, it initializes the folder browser. Form handlers POST JSON to URL values rendered in `shared.html`, then reload on success or write errors into the page.

Folder browsing keeps `_browseToken`, `_browseCurrentPath`, and `_browseSelected` as client state. `_loadFolder()` requests the current subpath and redraws breadcrumbs/list; `_renderList()` sorts directories before files and builds row/checkbox/download controls; `_downloadItem()` fetches one item; `_downloadSelected()` submits selected relative paths for ZIP output; size and text/attribute escaping helpers format safe output. The UI contract is the `body[data-*]` URLs/state and the `folderBrowser`, `browserList`, breadcrumb, selection-bar and gate form IDs in [../templates/shared.html](../templates/shared.html), plus classes in [../static/css/shared.css](../static/css/shared.css). Update this file together with the corresponding public endpoints in `routes/shares.py`; test passkey, approval pending/denied/approved, nested names with special characters, browser back/forward, and empty folders.

#### [../static/js/video.js](../static/js/video.js)

Bundled Video.js web-component/player runtime, not app-maintained source. The file is minified/compiled and does not provide a safe local feature-edit surface. The application integration is in `index.html` (module/style loading and `<video-skin>` markup), `index.js` (player setup, HLS sources and shadow-root stylesheet injection), [../static/css/video.css](../static/css/video.css) (upstream companion CSS), and [../static/css/video-skin-overrides.css](../static/css/video-skin-overrides.css) (app-owned overrides).

To change player behavior or fix a player defect, identify whether the behavior is controlled by app setup, the app override, or upstream Video.js; modify app-owned integration when possible. For an upstream fix, upgrade/rebuild the vendor distribution as a matched asset set, preserve its license notices, validate the player against HLS and native playback, and refresh SRI hashes. Avoid hand-editing minified code because it is difficult to review and will be lost on the next upgrade.

#### [../static/js/viewer.mjs](../static/js/viewer.mjs)

Bundled Mozilla PDF.js viewer application (Apache-2.0 notice; version/build are declared near the header), not the app-owned worker bootstrap. It contains the upstream PDF.js UI and viewer implementation and is loaded as a module by `index.html`. Its standalone-page assumptions are adapted by the modal root in `index.html`, [../static/css/pdfjs-viewer-overlay.css](../static/css/pdfjs-viewer-overlay.css), and [../static/js/pdfjs-worker-init.mjs](../static/js/pdfjs-worker-init.mjs).

Do not implement CloudinatorFTP-specific modal, resource-path, preference, or default-document fixes by patching this generated bundle. Put host integration in `pdfjs-worker-init.mjs`, modal actions in `index.js`, markup in `index.html`, and scoped presentation in `pdfjs-viewer-overlay.css`. For upstream PDF.js changes, update `viewer.mjs`, `pdf.mjs`, `pdf.worker.mjs`, CSS, locale/support assets and licenses as a compatible distribution; then verify worker/resource loading, real PDF open/close, mobile toolbar, CSP and every affected SRI hash.

## 27. Python import graph

The rows below list each Python file's **direct** imports, grouped as standard library, third-party, and project-local. Names suffixed with `*` are imported inside a function, conditional, or optional-dependency probe; they still form a dependency when that path runs. This is a module dependency inventory, not a list of every imported symbol or every transitive dependency.

### 27.1 Root modules

| File | Standard library | Third-party | Project-local imports |
|---|---|---|---|
| [../app.py](../app.py) | `os`, `atexit*` | None | `core`, `middleware`, `routes.hls`, `routes.image_preview`, `routes.versions`, `routes.previews`, `routes.admin`, `routes.stats`, `routes.shares`, `routes.uploads`, `routes.files`, `routes.login`, `routes.site_meta`, `config`, `storage`, `protocol_manager*` |
| [../auth.py](../auth.py) | None | `quart` | `database` |
| [../config.py](../config.py) | `importlib`, `os`, `platform`, `subprocess`, `json`, `time`, `winreg*`, `shutil*` | None | `paths`, `version_engine*` (looked up with `importlib.import_module` inside `view_current_settings()`, so it is not an import statement; 5.41, CodeQL #612) |
| [../core.py](../core.py) | `os`, `sys`, `shutil`, `json`, `asyncio`, `threading`, `time`, `logging`, `uuid`, `socket`, `zipfile`, `io`, `re`, `subprocess`, `hashlib`, `datetime`, `queue`, `dataclasses`, `typing`, `mimetypes`, `secrets`, `random*`, `hmac*`, `functools*` | `quart`, `werkzeug`, `zipstream`, `itsdangerous` | `paths`, `helpers.file_body`, `helpers.net_utils`, `config`, `database`, `auth`, `storage`, `version_history`, `file_monitor`, `search_index`, `realtime_stats`, `realtime_shares`, `logging_setup` |
| [../database.py](../database.py) | `os`, `secrets`, `sqlite3`, `threading`, `time`, `uuid` | `bcrypt`, `cryptography.fernet`, `impacket.ntlm*` | `paths` |
| [../dev_server.py](../dev_server.py) | `os`, `sys`, `signal`, `threading*` | None | `helpers.net_utils`, `app`, `protocol_manager`, `version_engine`, `config*` |
| [../file_index.py](../file_index.py) | `os`, `hashlib`, `json`, `time`, `threading`, `tempfile` | None | `paths`, `config*` |
| [../file_monitor.py](../file_monitor.py) | `os`, `sys`, `json`, `time`, `threading`, `hashlib`, `functools`, `collections`, `pathlib`, `dataclasses`, `typing`, `ctypes*`, `tempfile*` | `watchdog.observers`, `watchdog.events` | `config`, `file_index`, `search_index`, `paths` |
| [../ftp_server.py](../ftp_server.py) | `logging`, `threading` | `pyftpdlib*`, `OpenSSL*` | `logging_setup`, `helpers.net_utils`, `config*`, `helpers.ssl_cert*`, `database*` |
| [../logging_setup.py](../logging_setup.py) | `logging`, `os`, `sys`, `threading`, `datetime` | None | None |
| [../middleware.py](../middleware.py) | `os`, `threading`, `time`, `logging`, `uuid`, `datetime`, `secrets` | `quart` | `core`, `config`, `auth`, `storage` |
| [../paths.py](../paths.py) | `os`, `json` | None | None |
| [../prod_server.py](../prod_server.py) | `os`, `sys`, `json`, `shutil`, `signal`, `asyncio`, `logging`, `threading*`, `traceback*` | `hypercorn.config*`, `hypercorn.asyncio*` | `logging_setup`, `helpers.net_utils`, `app`, `helpers.hypercorn_ssl_fix`, `protocol_manager`, `version_engine`, `config*`, `paths*`, `helpers.ssl_cert*` |
| [../protocol_manager.py](../protocol_manager.py) | `os`, `socket`, `subprocess`, `sys`, `threading`, `time`, `importlib*` | None | `logging_setup`, `app`, `config*`, `sftp_server*`, `ftp_server*`, `smb_server*` |
| [../realtime_shares.py](../realtime_shares.py) | `asyncio`, `json`, `time`, `threading`, `typing` | `quart` | None |
| [../realtime_stats.py](../realtime_stats.py) | `asyncio`, `json`, `time`, `threading`, `typing`, `dataclasses`, `os*`, `shutil*` | `quart` | `config*`, `file_monitor*` |
| [../search_index.py](../search_index.py) | `os`, `sqlite3`, `threading`, `time`, `datetime`, `typing` | None | `paths`, `config` |
| [../sftp_server.py](../sftp_server.py) | `errno`, `os`, `socket`, `threading`, `time`, `logging`, `builtins*` | `paramiko*` | `logging_setup`, `helpers.net_utils`, `database*`, `paths*`, `config*` |
| [../smb_server.py](../smb_server.py) | `itertools`, `logging`, `os`, `platform`, `threading`, `re*`, `time*`, `socket*`, `sys*`, `traceback*`, `msvcrt*`, `_winapi*` | `impacket.smbserver*`, `impacket.smb3structs*`, `impacket.nt_errors*`, `impacket.smb*`, `impacket.nmb*` | `logging_setup`, `helpers.net_utils`, `database*`, `helpers.lanman_guard*`, `config*`, `paths*` |
| [../storage.py](../storage.py) | `os`, `shutil`, `time`, `threading`, `stat`, `traceback*` | None | `config`, `file_index*`, `file_monitor*` |
| [../version_engine.py](../version_engine.py) | `argparse`, `atexit`, `fnmatch`, `hashlib`, `json`, `os`, `queue`, `re`, `signal`, `sqlite3`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `uuid` | None | `config`, `paths`, `logging_setup` |
| [../version_history.py](../version_history.py) | `os`, `sqlite3`, `threading`, `time`, `shutil*`, `tempfile*` | None | `config`, `logging_setup`, `version_engine` |
| [../webdav_server.py](../webdav_server.py) | `base64`, `hashlib`, `logging`, `os`, `re`, `asyncio`, `threading`, `time`, `urllib.parse`, `signal*` | `wsgidav*`, `asgiref*`, `hypercorn*` | `logging_setup`, `helpers.net_utils`, `helpers.hypercorn_ssl_fix`, `database*`, `paths*`, `config*`, `helpers.ssl_cert*` |

### 27.2 Routes, helpers, tools, and checks

| File | Standard library | Third-party | Project-local imports |
|---|---|---|---|
| [../routes/__init__.py](../routes/__init__.py) | None | None | None |
| [../routes/admin.py](../routes/admin.py) | `os`, `shutil`, `asyncio`, `threading`, `time` | `quart` | `core`, `auth`, `routes.hls`, `routes.image_preview`, `file_monitor*`, `file_index*`, `realtime_stats*` |
| [../routes/files.py](../routes/files.py) | `os`, `shutil`, `asyncio`, `threading`, `time`, `logging`, `secrets`, `json*` | `quart`, `zipstream` | `core`, `config`, `auth`, `storage`, `helpers.walk_executor`, `file_monitor*` |
| [../routes/hls.py](../routes/hls.py) | `os`, `json`, `asyncio`, `threading`, `re`, `subprocess`, `hashlib`, `shutil*`, `glob*` | `quart` | `core`, `config`, `storage`, `paths*` |
| [../routes/image_preview.py](../routes/image_preview.py) | `os`, `json`, `asyncio`, `threading`, `time`, `re`, `hashlib` | `quart`, `pyvips*` | `core`, `config`, `storage`, `paths*` |
| [../routes/login.py](../routes/login.py) | `asyncio`, `time`, `logging`, `uuid` | `quart` | `core`, `auth` |
| [../routes/previews.py](../routes/previews.py) | `os`, `asyncio`, `logging`, `zipfile`, `html*`, `datetime*`, `csv*`, `tarfile*` | `quart`, `mammoth*`, `openpyxl*`, `pptx*`, `pyzipper*`, `py7zr*`, `rarfile*` | `core`, `config`, `storage` |
| [../routes/shares.py](../routes/shares.py) | `os`, `asyncio`, `time`, `logging`, `uuid`, `secrets` | `quart`, `zipstream`, `itsdangerous` | `core`, `config`, `database`, `auth`, `storage`, `helpers.walk_executor`, `realtime_shares` |
| [../routes/site_meta.py](../routes/site_meta.py) | None | `quart` | `core` |
| [../routes/stats.py](../routes/stats.py) | `os`, `sys`, `io`, `asyncio`, `threading`, `time`, `traceback*`, `shutil*` | `quart` | `core`, `config`, `auth`, `storage`, `helpers.walk_executor`, `search_index`, `realtime_stats`, `file_monitor*` |
| [../routes/uploads.py](../routes/uploads.py) | `os`, `shutil`, `json`, `asyncio`, `threading`, `time`, `uuid`, `queue` | `quart`, `werkzeug` | `core`, `config`, `database`, `auth`, `storage`, `helpers.upload_perf`, `routes.shares` |
| [../routes/versions.py](../routes/versions.py) | `os`, `asyncio`, `logging`, `mimetypes`, `threading` | `quart` | `core`, `config`, `auth`, `storage`, `version_history` |
| [../helpers/__init__.py](../helpers/__init__.py) | None | None | None |
| [../helpers/hypercorn_ssl_fix.py](../helpers/hypercorn_ssl_fix.py) | `asyncio` | `hypercorn.asyncio.tcp_server*` | `logging_setup` |
| [../helpers/lanman_guard.py](../helpers/lanman_guard.py) | `ctypes`, `json`, `os`, `platform`, `subprocess`, `datetime`, `socket*` | None | None |
| [../helpers/net_utils.py](../helpers/net_utils.py) | `socket` | None | None |
| [../helpers/parent_watch.py](../helpers/parent_watch.py) | `os`, `sys`, `threading`, `time`, `ctypes*` | None | None |
| [../helpers/ssl_cert.py](../helpers/ssl_cert.py) | `datetime`, `ipaddress`, `os`, `socket`, `sys*` | `cryptography*` | `paths*`, `config*` |
| [../helpers/upload_perf.py](../helpers/upload_perf.py) | `asyncio`, `re`, `threading`, `time`, `io*` | `werkzeug*` | None |
| [../helpers/walk_executor.py](../helpers/walk_executor.py) | `asyncio`, `functools`, `threading`, `concurrent.futures` | None | None |
| [../helpers/file_body.py](../helpers/file_body.py) | None | None | None |
| [../tools/kick_sessions.py](../tools/kick_sessions.py) | `os`, `secrets`, `sys` | None | `database` |
| [../tools/manage_users.py](../tools/manage_users.py) | `os`, `sys`, `getpass*`, `datetime*` | None | `paths`, `database` |
| [../tools/reset_db.py](../tools/reset_db.py) | `os`, `shutil`, `sys`, `importlib*` | None | `paths*`, `helpers.lanman_guard*`, `database*` |
| [../tools/revoke_sharing.py](../tools/revoke_sharing.py) | `argparse`, `getpass`, `random`, `os`, `re`, `sys`, `time` | None | `database` |
| [../tools/setup_storage.py](../tools/setup_storage.py) | `os`, `sys`, `json`, `importlib*`, `shutil*`, `traceback*` | None | `config*`, `paths*` |
| [../tools/smb_setup.py](../tools/smb_setup.py) | `json`, `os`, `platform`, `subprocess`, `sys`, `ctypes*` | None | `helpers.lanman_guard`, `paths`, `config*` |
| [../tools/sri_validator.py](../tools/sri_validator.py) | `argparse`, `base64`, `hashlib`, `os`, `re`, `sys` | None | None |
| [../tools/version_manage.py](../tools/version_manage.py) | `argparse`, `os`, `sys`, `time` | None | `config`, `version_engine` |
| [../tools/purge_missing_versions.py](../tools/purge_missing_versions.py) | `argparse`, `dataclasses`, `json`, `os`, `sqlite3`, `sys`, `time` | None | `config`, `version_engine` (inside functions) |
| [../tests/check.py](../tests/check.py) | `argparse`, `ast`, `fnmatch`, `importlib.util`, `json`, `os`, `re`, `subprocess`, `sys`, `pathlib`, `importlib*` | `pyflakes*` | Runtime-selected imports via subprocess* |
| [../tests/codeql_sarif_parser.py](../tests/codeql_sarif_parser.py) | `argparse`, `collections`, `csv`, `fnmatch`, `json`, `re`, `sys`, `zipfile`, `pathlib`, `urllib.parse` | None | None |
| [../tests/dir_tree.py](../tests/dir_tree.py) | `pathlib` | None | None |
| [../tests/smoke.py](../tests/smoke.py) | `argparse`, `ast`, `json`, `os`, `re`, `shutil`, `subprocess`, `sys`, `pathlib` | `pyflakes*` | None |
| [../tests/conftest.py](../tests/conftest.py) | `hashlib`, `json`, `os`, `shutil`, `socket`, `subprocess`, `sys`, `sysconfig`, `time`, `types`, `urllib.*`, `pathlib` | `pytest` | None (loads project code only in the scratch subprocess) |
| [../tests/qa.py](../tests/qa.py) | `argparse`, `importlib.util`, `shutil`, `subprocess`, `sys`, `sysconfig`, `time`, `pathlib` | None | None |
| [../tests/unit/test_paths.py](../tests/unit/test_paths.py) | `json`, `os` | `pytest` | `paths` (the only module tests import in-process) |
| [../tests/mutation_trial.py](../tests/mutation_trial.py) | `argparse`, `ast`, `copy`, `os`, `shutil`, `subprocess`, `sys`, `tempfile`, `time`, `pathlib` | None (runs `pytest` as a subprocess) | None (reads the project's `.py` files, mutates a temporary copy) |
| [../tests/unit/test_assemble_atomic.py](../tests/unit/test_assemble_atomic.py) | `ast`, `os`, `stat`, `time`, `uuid`, `pathlib` | `pytest` | None (reads `storage.py` with `ast`, never imports it) |
| [../tests/unit/test_monitor_handler.py](../tests/unit/test_monitor_handler.py) | `ast`, `functools`, `os`, `threading`, `time`, `types`, `pathlib` | `pytest` | None (reads `file_monitor.py` with `ast`, never imports it) |
| [../tests/unit/test_monitor_cache.py](../tests/unit/test_monitor_cache.py) | `ast`, `hashlib`, `json`, `os`, `textwrap`, `threading`, `time`, `types`, `typing`, `pathlib` | `pytest`, `hypothesis` (optional: only the loader fuzz test needs it) | None (reads `file_monitor.py` with `ast`) |
| [../tests/unit/test_upload_perf.py](../tests/unit/test_upload_perf.py) | `asyncio`, `importlib.util`, `tempfile`, `uuid`, `pathlib` | `pytest`, `werkzeug` (inside two tests) | None (loads `helpers/upload_perf.py` from its file; fake clocks, timers and app) |
| [../tests/unit/test_upload_perf_split.py](../tests/unit/test_upload_perf_split.py) | `importlib.util`, `pathlib` | `pytest` | None (loads `helpers/upload_perf.py` from its file; a fake clock) |
| [../tests/unit/test_upload_body_paths.py](../tests/unit/test_upload_body_paths.py) | `ast`, `asyncio`, `importlib.util`, `time`, `uuid`, `pathlib` | `pytest`, `quart` (skips without it) | None (reads `routes/uploads.py` with `ast`, never imports it) |
| [../tests/unit/test_async_handlers_no_blocking.py](../tests/unit/test_async_handlers_no_blocking.py) | `ast`, `pathlib` | `pytest` | None (reads `routes/*.py`, `middleware.py` and `core.py` with `ast`, never imports them) |
| [../tests/unit/test_stream_from_thread.py](../tests/unit/test_stream_from_thread.py) | `ast`, `asyncio`, `concurrent.futures`, `threading`, `time`, `pathlib` | `pytest` | None (reads `core.py` with `ast`, never imports it) |
| [../tests/unit/test_chunk_tracker_lock.py](../tests/unit/test_chunk_tracker_lock.py) | `ast`, `os`, `threading`, `time`, `pathlib` | `pytest` | None (reads `core.py` with `ast`; fake `storage` and `assembly_queue`, a temporary `.chunks` folder) |
| [../tests/unit/test_storage_stats_cache.py](../tests/unit/test_storage_stats_cache.py) | `ast`, `asyncio`, `threading`, `time`, `pathlib` | `pytest` | None (reads `routes/stats.py` with `ast`; fake `storage`) |
| [../tests/unit/test_abandoned_upload_cleanup.py](../tests/unit/test_abandoned_upload_cleanup.py) | `ast`, `os`, `time`, `pathlib` | `pytest` | None (reads `middleware.py` with `ast`; fake tracker, queue and `storage`) |
| [../tests/unit/test_request_auth_memo.py](../tests/unit/test_request_auth_memo.py) | `ast`, `pathlib`, `pytest` | `pytest` | None (reads `auth.py` with `ast`; fake `g`, `session` and a counting `db`) |
| [../tests/unit/test_database_connect.py](../tests/unit/test_database_connect.py) | `ast`, `sqlite3`, `threading`, `time`, `pathlib` | `pytest*` | None (reads `database.py` with `ast`; a real temporary SQLite file) |
| [../tests/unit/test_image_preview_waiters.py](../tests/unit/test_image_preview_waiters.py) | `ast`, `asyncio`, `threading`, `pathlib` | `pytest` | None (reads `routes/image_preview.py` and `routes/admin.py` with `ast`) |
| [../tests/unit/test_versions_stream_close.py](../tests/unit/test_versions_stream_close.py) | `ast`, `asyncio`, `threading`, `time`, `pathlib` | `pytest` | None (reads `routes/versions.py` with `ast`) |
| [../tests/unit/test_walk_executor.py](../tests/unit/test_walk_executor.py) | `ast`, `asyncio`, `importlib.util`, `threading`, `time`, `pathlib` | `pytest` | None (loads `helpers/walk_executor.py` from its file; reads three route modules with `ast`) |
| [../tests/unit/test_upload_progress_js.py](../tests/unit/test_upload_progress_js.py) | `json`, `re`, `shutil`, `subprocess`, `pathlib`, `pytest` | `pytest` | None (cuts the progress block out of `static/js/index.js` and runs it in `node`) |
| [../tests/unit/test_version_engine_backoff.py](../tests/unit/test_version_engine_backoff.py) | `ast`, `threading`, `types`, `pathlib`, `pytest` | `pytest` | None (reads `version_engine.py` with `ast`) |
| [../tests/unit/test_manage_log_follow.py](../tests/unit/test_manage_log_follow.py) | `re`, `subprocess`, `sys`, `threading`, `time`, `pathlib`, `pytest` | `pytest` | None (cuts the follower out of `manage.sh` and runs it as a subprocess) |
| [../tests/unit/test_upload_settings.py](../tests/unit/test_upload_settings.py) | `ast`, `pathlib` | `pytest` | None (reads `config.py` and `core.py` with `ast`) |
| [../tests/unit/test_version_engine_scope.py](../tests/unit/test_version_engine_scope.py) | `ast`, `os`, `types`, `fnmatch`, `pathlib` | `pytest` | None (reads `version_engine.py` with `ast`) |
| [../tests/unit/test_file_body.py](../tests/unit/test_file_body.py) | `asyncio`, `hashlib`, `importlib.util`, `math`, `pathlib` | `pytest`, `quart` (skips without it) | None (loads `helpers/file_body.py` from its file; real Quart objects and files) |
| [../tests/unit/test_scratch_environment.py](../tests/unit/test_scratch_environment.py) | `ast`, `json`, `os`, `types`, `pathlib` | `pytest` | None (reads `tests/conftest.py` with `ast`) |
| [../tests/unit/test_dev_server_identity.py](../tests/unit/test_dev_server_identity.py) | `re`, `pathlib` | `pytest` | None (reads `dev_server.py` and `prod_server.py` as text) |
| [../tests/application/test_async_offload_routes.py](../tests/application/test_async_offload_routes.py) | `io`, `os`, `time`, `uuid`, `zipfile` | `pytest` | None (HTTP against the shared scratch server; a ZIP download is read and compared byte for byte) |
| [../tests/application/test_upload_tuning.py](../tests/application/test_upload_tuning.py) | `os`, `socket`, `time`, `uuid` | `pytest` | None (HTTP and a raw socket against its own scratch server with `BODY_TIMEOUT` 2 s, timing and in-memory parsing on) |
| [../tests/application/test_download_buffer.py](../tests/application/test_download_buffer.py) | `hashlib`, `os`, `uuid`, `concurrent.futures` | `pytest` | None (HTTP against the shared scratch server) |
| [../tests/reliability/test_version_chunks_excluded.py](../tests/reliability/test_version_chunks_excluded.py) | `contextlib`, `os`, `sqlite3`, `time`, `uuid` | `pytest` | None (opt-in; the live Version Engine of `scratch_server_with_versions`; reads its database read-only) |
| [../tests/property/test_properties.py](../tests/property/test_properties.py) | `ast`, `hashlib`, `ntpath`, `os`, `posixpath`, `types`, `pathlib` | `pytest`, `hypothesis` | None (reads `storage.py`, `routes/uploads.py` and `file_monitor.py` with `ast`) |
| [../tests/reliability/test_version_engine_live.py](../tests/reliability/test_version_engine_live.py), [test_concurrency.py](../tests/reliability/test_concurrency.py), [test_restart.py](../tests/reliability/test_restart.py) | `concurrent.futures`, `hashlib`, `os`, `time`, `uuid` | `pytest` | None (HTTP against a scratch server; fixtures from `tests/conftest.py`) |
| [../tests/performance/test_baselines.py](../tests/performance/test_baselines.py) | `concurrent.futures`, `hashlib`, `os`, `statistics`, `time`, `uuid` | `pytest` | None |
| [../tests/frontend/test_browser_smoke.py](../tests/frontend/test_browser_smoke.py), [test_browser_flows.py](../tests/frontend/test_browser_flows.py) | `os`, `time`, `uuid` | `pytest`, `playwright` (optional: the test skips without it) | None |
| [../tests/reliability/test_version_engine_crash.py](../tests/reliability/test_version_engine_crash.py) | `hashlib`, `os`, `time`, `uuid` | `pytest`, `psutil` | None (opt-in; its own scratch server with the Version Engine on, killed and restarted) |
| [../tests/unit/test_index_js_logic.py](../tests/unit/test_index_js_logic.py) | `json`, `re`, `shutil`, `subprocess`, `pathlib` | `pytest` (node is optional: the tests skip without it) | None (runs functions cut out of `static/js/index.js` in Node) |
| [../tests/unit/test_static_check_skip_dirs.py](../tests/unit/test_static_check_skip_dirs.py) | `ast`, `pathlib` | `pytest` | None (reads `tests/smoke.py`, `tests/check.py` and `.gitignore`) |
| [../tests/unit/test_dev_server_coverage_save.py](../tests/unit/test_dev_server_coverage_save.py) | `ast`, `types`, `pathlib` | `pytest` | None (reads `dev_server.py` with `ast`) |

### 27.3 Inbound project imports

This reverse index answers “who imports this module?” It includes direct and lazy project imports; it does not count a caller that only reaches a module indirectly through another module.

| Module/package | Python importers |
|---|---|
| `app` | `dev_server`, `prod_server`, `protocol_manager` |
| `auth` | `core`, `middleware`, and route modules `admin`, `files`, `login`, `shares`, `stats`, `uploads`, `versions` |
| `config` | `app`, `core`, `file_index`, `file_monitor`, `ftp_server`, `middleware`, `prod_server`, `protocol_manager`, routes `files/hls/image_preview/previews/shares/stats/uploads/versions`, `search_index`, `sftp_server`, `smb_server`, `storage`, `version_engine`, `version_history`, `webdav_server`, tools `setup_storage/smb_setup/version_manage`, `helpers.ssl_cert` |
| `core` | `app`, `middleware`, all 11 route modules |
| `database` | `auth`, `core`, routes `shares/uploads`, `ftp_server`, `sftp_server`, `smb_server`, `webdav_server`, tools `kick_sessions/manage_users/reset_db/revoke_sharing` |
| `file_index` | `file_monitor`, `routes.admin`, `storage` |
| `file_monitor` | `core`, routes `admin/files/stats`, `storage` |
| `logging_setup` | `core`, `ftp_server`, `prod_server`, `protocol_manager`, `sftp_server`, `smb_server`, `webdav_server`, `version_engine`, `version_history`, `helpers.hypercorn_ssl_fix` |
| `paths` | `config`, `core`, `database`, `file_index`, `file_monitor`, `search_index`, `prod_server`, `sftp_server`, `smb_server`, `webdav_server`, `version_engine`, tools `manage_users/reset_db/setup_storage/smb_setup`, helpers `ssl_cert` |
| `protocol_manager` | `app`, `dev_server`, `prod_server` |
| `realtime_shares` | `core`, `routes.shares` |
| `realtime_stats` | `core`, `routes.admin`, `routes.stats` |
| `routes.*` | `app` imports every route module; additional permitted route-to-route imports are `routes.admin -> routes.hls, routes.image_preview` and `routes.uploads -> routes.shares` |
| `search_index` | `core`, `file_monitor`, `routes.stats` |
| `storage` | `app`, `core`, `middleware`, routes `files/hls/image_preview/previews/shares/stats/uploads/versions` |
| `version_engine` | `dev_server`, `prod_server`, `version_history`, `tools.version_manage`, `tools.purge_missing_versions`, and `config` through a dynamic status lookup |
| `version_history` | `core`, `routes.versions` |
| `helpers.hypercorn_ssl_fix` | `prod_server`, `webdav_server` |
| `helpers.lanman_guard` | `smb_server`, `tools.reset_db`, `tools.smb_setup` |
| `helpers.net_utils` | `core`, `dev_server`, `ftp_server`, `prod_server`, `sftp_server`, `smb_server`, `webdav_server` |
| `helpers.ssl_cert` | `ftp_server`, `prod_server`, `webdav_server` |
| `helpers.upload_perf` | `routes.uploads` |
| `helpers.file_body` | `core` |
| `helpers.walk_executor` | `routes.files`, `routes.shares`, `routes.stats` |

The complete per-file outbound edges are in tables 27.1–27.2. `tests/check.py` verifies import resolution and helper/route layering statically; `--import` performs selected real imports in subprocesses and can execute startup side effects if forced.

## 28. Cross-file reference map

Imports do not capture every dependency. These are the principal runtime/data/API/asset edges that contributors should follow when a change crosses module boundaries. Routes are registered by Python function decorators; the browser often builds request URLs dynamically, so endpoint family references matter in addition to literal string searches.

### 28.1 Startup, process, and lifecycle references

```text
manage.sh
  -> dev_server.py | prod_server.py
	   -> app.py
			-> core.py (first; paths.ensure_dirs, shared Quart app/state)
			-> middleware.py (request lifecycle hooks)
			-> routes/*.py (decorators register on core.app)
			-> initialize_cleanup() (routes.uploads worker/schedulers)
	   -> protocol_manager.start_all()/stop_all()
			-> ftp_server.py / sftp_server.py / smb_server.py (threads)
			-> webdav_server.py (supervised subprocess)
	   -> version_engine.start()/stop() (separate subprocess)
```

Direct `python app.py` is a separate supported path: `app.py` calls cleanup during import, then its `__main__` block starts protocols and the Quart dev app. Do not assume an import of `app` is side-effect free. `webdav_server.py` deliberately imports leaf helpers instead of `app.py` so its subprocess does not start a second monitor/crawler.

### 28.2 Storage, mutation, and index references

```text
routes/files.py / routes/uploads.py / protocol adapters
  -> storage.py (filesystem operation and path helpers)
	  -> file_index.py (large-directory direct-entry cache, lazy from storage.list_dir)
  -> core._trigger_reconcile() after successful web mutations
	  -> file_monitor.py (dirty-folder correction / reconcile / storage_index.json)
		  -> file_index.py (rebuild and changed folders)
		  -> search_index.py (live updates and reconcile-from-walk)
		  -> realtime_stats.py (SSE/poll data and change sequence)
			  -> routes/stats.py -> static/js/index.js
```

These stores have different meanings: `storage_index.json` is recursive counters/`dir_info`; `file_index.json` is direct listing rows for large folders; `search_index.db` is deep-search metadata. External writes from Explorer/protocols are observed by the file monitor, while web mutations also explicitly request reconciliation. Do not update those cache files directly from a route.

### 28.3 Authentication and authorization references

```text
routes/login.py -> auth.py -> database.py
routes + middleware.py -> core.login_required / auth.is_logged_in / auth.get_role
FTP/SFTP/WebDAV -> database.py credentials + role
SMB -> database.py NT hash + role (not web bcrypt verification on the wire)
tools/manage_users.py, kick_sessions.py -> database.py
tools/revoke_sharing.py, routes/shares.py -> database.py share/request APIs
```

Login authentication is not the same as write authorization. Route mutations and protocol operations must independently preserve `readwrite` versus `readonly` behavior. `middleware.py` and `core.py` also contain endpoint-name security sets; route renames or auth policy changes require reviewing both sets and their route names.

### 28.4 Frontend request and response references

| Browser source | Python route/service owners | Reference contract |
|---|---|---|
| `static/js/index.js` authentication | `routes/login.py`, `routes/uploads.py` | `/check_session`, `/csrf-token`, `/logout`, `/admin/upload_status`; CSRF token is rendered in the template meta tag and refreshed on stale-token errors. |
| `static/js/index.js` browse/search/stats | `routes/files.py`, `routes/stats.py`, `search_index.py`, `realtime_stats.py` | `/api/files`, `/api/dir_info`, `/api/search`, storage stats, SSE/poll sequence payloads. `EventSource` reconnect/catch-up behavior depends on `file_monitor` sequence epochs. |
| `static/js/index.js` file and bulk actions | `routes/files.py`, `storage.py`, `core._trigger_reconcile` | Download/view/rename/mkdir/delete/move/copy/ZIP and async bulk-job status responses. Preserve response code/body contracts and job ownership. |
| `static/js/index.js` uploads | `routes/uploads.py`, `storage.py`, `core` queues | Whole/chunk uploads, chunk cancellation, assembly progress and cleanup. XHR upload requests are distinct from `fetch`; keep their CSRF refresh behavior aligned. |
| `static/js/index.js` image/Office/archive/video preview | `routes/image_preview.py`, `routes/previews.py`, `routes/hls.py` | Preview metadata/status and conversion/transcode API payloads; HLS manifests may add segment/subtitle URLs that the client consumes dynamically. |
| `static/js/index.js` share and version UI | `routes/shares.py`, `routes/versions.py`, `realtime_shares.py`, `version_history.py` | Share creation/security/manage actions and streams; history list/restore/download/retry/delete actions. Busy/202/409 states are part of the UI contract. |
| `static/js/shared.js` public link page | `routes/shares.py` | Passkey/request/status URLs supplied through `shared.html` body data attributes; folder browse/item download/ZIP endpoints are assembled from the token and relative path. |
| `static/js/login.js` | `routes/login.py`, `routes/uploads.py` | Fetches `/` and `/admin/upload_status` to detect an existing authenticated session; lockout countdown parses the server flash-message text. |

### 28.5 Template, CSS, and asset references

| Template | Direct app-owned asset references | Important relationships |
|---|---|---|
| `templates/404.html` | `css/404.css`, `js/404.js`, `js/bg_audio.js`, `icons/icon.webp`, `audio/bg_mus.opus`, plus Font Awesome | 404 script cancels redirect on input; CSS class names match error markup. |
| `templates/index.html` | `css/index.css`, `js/index.js`, video player JS/CSS and skin override URL, PDF.js bootstrap/viewer/CSS/locale/resources, icon/audio assets, plus Font Awesome | Main IDs/data attributes are read by `index.js`; it builds dynamic table/modal DOM styled by `index.css`. `pdfjs-worker-init.mjs` must load before `viewer.mjs`. The skin override is dynamically linked into the player shadow root by JS. |
| `templates/login.html` | `css/login.css`, `js/login.js`, `js/bg_audio.js`, icon/audio assets, plus Font Awesome | Form/flash IDs and classes are shared with login JS and route flash output. |
| `templates/shared.html` | `css/shared.css`, conditional `js/shared.js`, `js/bg_audio.js`, icon/audio assets, plus Font Awesome | Body `data-*` URLs/security state drive share JS; generated `.browser-*` classes are styled by shared CSS. |

Template-loaded local scripts/styles carry SRI hashes. `tools/sri_validator.py` discovers template tags only; dynamically inserted links such as the video shadow-root stylesheet are not found by that validator and require separate review if their URL/hash behavior changes. CSP is configured in `core.py`; literal inline scripts/styles and delegated action attributes are therefore security-policy references, not just markup style choices.

### 28.6 Config, persistent data, and operator references

| Source | Reads/writes or invokes | Consumers |
|---|---|---|
| `config.py` | Reads/writes `server_config.json`; imports path functions from `paths.py` and exposes module-level settings. | Core, storage/index, routes, protocols, launchers, setup/version tools. Changing a default alone may not update persisted configuration or already-imported constants. |
| `paths.py` | Reads/writes `storage_config.json`; resolves storage, DB, cache, HLS/image cache and versions paths. | `config.py`, DB/index/monitor modules, protocols, helpers, tools and Version Engine. |
| `database.py` | `db/cloudinator.db`, encryption key and session secret; schema for users, server token, shares and access requests. | Auth, core, routes, protocol adapters, tools. Back up the DB together with required key files. |
| `file_monitor.py` / `file_index.py` | `storage_index.json` and `file_index.json` under configured cache paths. | Routes/storage and browser stats/listing; do not confuse these caches with the deep-search DB. |
| `search_index.py` | `search_index.db` under configured DB path. | Core crawler, file monitor updates, `/api/search` route. |
| `version_engine.py` / `version_history.py` | Version DB/object storage and `.recovered/` under configured roots. | Launchers, version routes, version CLI and config tracking rules. |
| `manage.sh` | Launches server scripts and Python tools; delegates package setup and SRI checks. | Keep commands, menu dispatch, script paths and this file map aligned after moving/renaming a tool. Any new child process the server spawns needs (a) its PID file / command-line fingerprint in the `stop` sweeps and (b) the parent-PID env var for the orphan guard. |

## 29. What “all references” means here

The guide now inventories every first-party Python module's direct imports, reverse project importers, major startup/runtime calls, browser API families, template-loaded assets, config/data ownership, and the principal cross-layer reference paths. This is intended to make change impact traceable and to provide a durable navigation map.

It does **not** reproduce every symbol occurrence, every string literal, or every transitive call edge in the repository. Those change constantly and are better answered against current source with “Find All References”, workspace search, route checks, and the focused test for the behavior being changed. Dynamic imports, URL construction, template-generated URLs, subprocess launches, CSS selector coupling, and vendor internals are called out where static import edges alone would miss them. The vendor bundles and binary/resource trees remain integration references, not a hand-maintained symbol-level map.