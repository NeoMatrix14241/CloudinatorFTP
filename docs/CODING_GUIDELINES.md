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
- get_role()
- login_user()
- logout_user()
- current_user()
- is_logged_in()

The check is tied to the current server token stored in SQLite, so sessions can be invalidated centrally when the app token changes.

### 5.2 Session flow

The app uses Quart session state and stores a server token in the DB. This ensures:

- users are not trusted by stale session data
- deleted users are automatically logged out
- server token rotation invalidates active sessions
- login state is checked consistently by middleware and route handlers

### 5.3 Logout and the Clear-Site-Data header

[../routes/login.py](../routes/login.py) sends `Clear-Site-Data: "executionContexts"` only, on `GET /login` and on `/logout`, and only over HTTPS. The directives `"cache"`, `"cookies"`, `"storage"` and `"*"` were removed in 4.89: in the owner's measurements they made the browser do synchronous clearing work (a 3-15 s logout), while `"executionContexts"` takes 0.1-0.5 s. Do not add them back without measuring logout time again in Chrome and Edge.

What replaced them: the cache policy is `Cache-Control: no-cache, no-store, must-revalidate` (set by the logout route and, for every authenticated response, by `after_request` in [../middleware.py](../middleware.py)); the session and cookies are removed by `session.clear()` and `delete_cookie()` in the logout route. Not cleared any more: `localStorage`, `sessionStorage` and IndexedDB of the site, so keep secrets out of them.

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

## 9. Request lifecycle and middleware

The request lifecycle is centralized in [../middleware.py](../middleware.py).

### 9.1 Middleware responsibilities

This file handles:

- request timing and logging
- CORS preflight handling
- CSRF protection
- session validation
- response header adjustments
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

## 15. Security and hardening notes

### 15.1 CSP and inline script policy

The project is security-conscious about browser policy. The inline style hash and CSP configuration are discussed in [../core.py](../core.py), and the app intentionally avoids relying on unsafe inline script patterns where practical.

### 15.2 SRI validation

The project includes a validator for static asset integrity checks. See [../tools/sri_validator.py](../tools/sri_validator.py) and the manage.sh entry for validate-sri. An SRI hash is computed over the raw bytes of the file, so the repository is LF everywhere (see 19.1); `python tests/qa.py ci` runs the check on GitHub, and a stale hash fails that run. After editing anything under `static/` or `templates/` run `./manage.sh validate-sri --fix` and commit the templates together with the asset.

### 15.3 Security.txt and robots

The app exposes metadata endpoints for crawlers and security scanners through [../routes/site_meta.py](../routes/site_meta.py) and the static security file under [../static/.well-known/security.txt](../static/.well-known/security.txt).

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
- A new public route must be added to `PUBLIC_ENDPOINTS` in `tests/application/test_authorization.py` on purpose (and to the public list in `validate_session`); a new mutating route belongs in `READONLY_REFUSED`.
- Test files cannot import `conftest`; repeat small constants or use a fixture.

Test-only packages live in `requirements-dev.txt` (never in `requirements.txt` / `constraints.txt`, which `setup_pymodules.sh` rewrites): `python -m pip install -r requirements-dev.txt`.

### 18.1 Automated checks on GitHub (dev and main)

Two GitHub Actions workflows run on every push and pull request to `main` and `dev`:

- [../.github/workflows/tests.yml](../.github/workflows/tests.yml) installs only `pyflakes` and runs `python tests/smoke.py` and `python tests/check.py -q --skip-packages`: the same static checks as on a developer machine, nothing is imported or started. `--skip-packages` hides "package not installed" warnings because the runner does not install `requirements.txt`. A second job, `behavioral tests` (informational for now: `continue-on-error: true`; it needs `smoke + check` first), installs `requirements.txt` and `requirements-dev.txt` and runs `python tests/qa.py ci` (static checks, SRI, `node --check`, pytest; JUnit XML is uploaded as the `test-results` artifact). Keep the `smoke + check` job name unchanged: branch protection may require it.
- [../.github/workflows/codeql.yml](../.github/workflows/codeql.yml) runs CodeQL for Python and JavaScript and keeps the raw SARIF files. It converts them to CSV with [../tests/codeql_sarif_parser.py](../tests/codeql_sarif_parser.py) and uploads the artifacts `sarif-artifact-<language>`, `codeql-csv-<language>` and the combined `codeql-findings-csv`. Vendored third-party files are excluded through [../.github/codeql/codeql-config.yml](../.github/codeql/codeql-config.yml); keep that list in step with `VENDORED` in the parser.

Rules:

- Run `python tests/smoke.py` and `python tests/check.py` locally before pushing; fix a red Tests run, do not bypass it. For a change that has tests, also run `python tests/qa.py quick` (or one layer: `python tests/qa.py layer unit`).
- The advanced CodeQL workflow cannot run while the repository's CodeQL "default setup" is enabled; disable the default setup first.
- Parse downloaded results by hand with `python tests/codeql_sarif_parser.py <artifact.zip | .sarif file | folder>`; CSV files are written next to the script (add `tests/*.csv`, `tests/*.sarif` and `tests/*.zip` to `.gitignore`).
- When a workflow, the parser's `VENDORED` list or the CodeQL config changes, update sections 18.1, 25.5, 25.8 and 27.2 together.


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
6. Keep the async handler non-blocking. Disk walks, hashing, conversion, SQLite-heavy work, and blocking library calls should follow nearby wrappers using `asyncio.to_thread()` or a worker thread. Preserve the existing JSON/status response shape if a browser caller already consumes it.
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

### 22.4 Add or modify configuration

1. Put runtime constants and defaults in [../config.py](../config.py), next to the feature's existing settings. Keep directory resolution in [../paths.py](../paths.py), not scattered across routes.
2. If the setting is user-persisted, trace how `server_config.json` is loaded/saved in `config.py` and how the configuration menu edits it. Update both defaults and persistence/validation; a constant alone may be overwritten or never saved.
3. For a new storage directory, add a `paths.py` getter/setter following the existing `get_*_dir(create=True)` / `set_*_dir(path)` pattern and merge its key through the shared JSON read/write helper. Keep imports side-effect free where the existing path APIs use `create=False`.
4. Update the relevant configuration reference, deployment guide, and defaults table. Test valid, absent, malformed, and legacy config values where the loader supports fallback behavior.
5. Restart the app for settings imported into module-level constants; changing JSON on disk does not necessarily update already-imported values.

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
| File monitor/index behavior | Run the narrow temporary-tree test for the changed behavior, then `python tests/smoke.py` |
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

This section is the file-by-file map of executable, first-party project code. The workspace inventory contains **51 Python files**, and every one has an individual entry in sections 25.1–25.5: 23 root modules, 12 route files, 5 helpers, 8 tools, and 3 test scripts. Frontend CSS and JavaScript files are documented in sections 25.6 and 26. Each entry describes its implementation role and the neighboring contracts to check when modifying it. Use the change recipes above to plan cross-layer edits, then use this index to locate the owning implementation.

### 25.1 Root Python modules

| File | What it implements | When changing it, also check |
|---|---|---|
| [../app.py](../app.py) | Application composition root. Imports `core` first, registers middleware and all route modules, runs `initialize_cleanup()`, and exposes the app for launchers. | Import order is functional: preserve `core` first, middleware before routes, and every `routes/*.py` import. Importing this module has startup side effects. |
| [../auth.py](../auth.py) | Web-session wrappers for login checks, current user and role lookup; delegates credential persistence to `database.db`. | Changes to account/session semantics should be tested with middleware, `database.py`, routes, and all protocol authentication paths. |
| [../config.py](../config.py) | Runtime defaults, platform detection, server-config load/save and interactive configuration menus. Resolves `ROOT_DIR` and re-exports configured data paths. | Update persistence and validation as well as defaults; check `server_config.json`, `storage_config.json`, config docs, and restart requirements. |
| [../core.py](../core.py) | Shared Quart app, security/session configuration, rate limiter, chunk/assembly state, auth decorators, stream helpers, file monitor setup and reconciliation gate. | This is shared process state. Preserve one app instance, endpoint policy sets, locks, and the helper/API contracts imported by routes and middleware. |
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
| [../smb_server.py](../smb_server.py) | impacket SMB listener, periodic credential refresh, per-connection role enforcement, audit hooks and port fallback. | Its hooks patch/vendor internal behavior; check impacket version compatibility, Windows-specific fixes, NT hash lifecycle, and fallback port behavior. |
| [../storage.py](../storage.py) | Filesystem API for listing, path validation, directory info, file operations, chunk storage/assembly/cleanup and storage statistics. | Routes and protocol adapters must validate caller paths; coordinate listing changes with `file_index.py`, mutations with `file_monitor.py`, and uploads with `routes/uploads.py`. |
| [../version_engine.py](../version_engine.py) | Parent-process lifecycle API and `--worker` engine for snapshots, content-addressed storage, restore, scan, retention and GC. | Keep the process API used by both launchers, DB/object-store schema, crash recovery, and tracking/exclusion configuration aligned. |
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
| [../routes/uploads.py](../routes/uploads.py) | Whole/chunked upload, cancellation, cleanup/status endpoints, assembly worker and schedulers. | Worker startup is called from `app.py`; use shared core queues and storage helpers; preserve CSRF, write-role checks and share cleanup import. |
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

### 25.5 Tests and checks

| File | What it executes/checks | What it does not prove |
|---|---|---|
| [../tests/check.py](../tests/check.py) | Parameterized static source checks for syntax, pyflakes, project imports, import-name resolution, helper layering; optional guarded subprocess imports and JSON config checks. | AST/import heuristics are not full runtime coverage; `--import` executes modules and may have side effects when forced. |
| [../tests/codeql_sarif_parser.py](../tests/codeql_sarif_parser.py) | Converts CodeQL SARIF files (loose, zipped artifacts or folders) to per-language and combined CSV files; skips vendored files by default; optional `--fail-on` exit code. Standard library only. | Used by `codeql.yml` and by hand; keep `VENDORED` in step with `.github/codeql/codeql-config.yml`. |
| [../tests/conftest.py](../tests/conftest.py) | Shared pytest fixtures: `build_scratch()` copies the source tree into a temp folder and writes scratch `storage_config.json` / `server_config.json`; `paths_outside()` asks the copy's own `paths.py` where it would keep data and lists anything outside the scratch folder; `scratch_server` starts `dev_server.py` there on an ephemeral port and stops it through `.manage_pids/dev.stop`; autouse guard against in-process imports of application modules. Since 5.08 also: seeded accounts `qa_writer` (readwrite) and `qa_reader` (readonly), `scratch_server.client()` / `login_as()` / `db()` / `make_user()` / `.storage`, and a cookie-aware `HttpClient` / `Reply` (no redirect following, own fake client IP per client, `api()` adds the CSRF and JSON headers). | It never runs the application in-process and does not start protocol servers or the Version Engine. |
| [../tests/dir_tree.py](../tests/dir_tree.py) | Walks a filtered directory tree (`collect_entries()`, `build_tree()`), prints it and saves it to `docs/DIRECTORY_TREE.md`. | It is a diagnostic utility, not a product behavior test. It rewrites `docs/directory_tree.txt` (creating `docs/` if needed) and skips that file itself; regenerate and commit it after files are added, moved or removed. `EXCLUDE_DIR_WALK` matches folder names only. |
| [../tests/qa.py](../tests/qa.py) | The one QA runner for developers, `manage.sh` (planned) and GitHub: `static` (smoke, check, SRI, `node --check`), `tests` (pytest on every existing layer folder), `quick`, `layer <name>`, `ci` (JUnit XML to `./artifacts`); prints PASS/FAIL/SKIP per step, exit 1 on any failure (including a `layout` FAIL when a `test_*.py` file sits directly in `tests/` instead of a layer folder), never passes `--force`; `python tests/qa.py --version` prints which copy you run; the "pip install" hint appears only when pytest cannot be imported. | A SKIP (missing tool or folder) is not a pass of that check. |
| [../tests/smoke.py](../tests/smoke.py) | Read-only project safety checks: syntax, optional pyflakes, route/endpoints, hooks, import cycles/layering, route-module registration, tool launch paths, shell syntax, and route snapshot changes. | Does not import/start the app, issue HTTP requests, or test filesystem/runtime behavior. `--save` intentionally updates the route snapshot. |
| [../tests/smoke_routes.json](../tests/smoke_routes.json) | Baseline route signature consumed by `smoke.py`. | Update only when route additions/removals are intended and reviewed. |
| [../tests/unit/](../tests/unit/) | `test_paths.py` (every `paths.py` getter, setter, reset, merge-safe save, corrupt config), `test_scratch_copy.py` (the harness isolates everything and the guard catches outside paths), `test_qa_runner.py` (plan selection, exit codes, skip handling, the stray-file `layout` check), `test_setup_pymodules.py` (the `append_req_line()` function of `setup_pymodules.sh`, run in bash), `test_http_client.py` (the HTTP client and scratch helpers of `conftest.py`), `test_manage_qa.py` (the Quality Assurance section of `manage.sh`: menu numbers 1-25 agree between listing, dispatch and help; the `qa` modes; exit codes). | Not application behavior beyond `paths.py`. |
| [../tests/application/](../tests/application/) | `test_login.py` (login page headers and cookie flags, CSRF, login, lockout, logout, session invalidation) and `test_authorization.py` (anonymous sweep over every declared route against the reviewed `PUBLIC_ENDPOINTS`, readonly refusals, role changes), plus `test_boot.py`: starts the real app from the scratch copy and checks `/login`, `/robots.txt`, anonymous `/`, that data folders were created only in the scratch tree and that the real `storage_config.json` / `server_config.json` are untouched. | Login, CSRF, lockout, session and authorization only (5.08); no upload, share, file-operation or version behavior yet. |

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
| [../manage.sh](../manage.sh) | Operator CLI/menu for server start/stop/restart/status/logs and wrapped utilities; also handles PID/log management, WebDAV restart, security.txt and SRI operations, and the Quality Assurance section (menu 21-25 and the `qa` command, which only call `tests/qa.py`; the menu numbering is enforced by `tests/unit/test_manage_qa.py`). `stop` is two-stage (graceful stop file / SIGTERM, then process-tree kill) and always sweeps WebDAV and Version Engine leftovers. |
| [../setup_pymodules.sh](../setup_pymodules.sh) | Generates `requirements.txt`/`constraints.txt`, resolves package constraints, handles Termux system packages and offers installation. New package lines are appended through `append_req_line()` (adds a missing final newline first; keeps CRLF files CRLF, detected from an `od` hex dump and written with `printf` escapes; never `grep` / `head` / `$(...)` for a CR, because they hide it in Git Bash); `tests/unit/test_setup_pymodules.py` covers it. |
| [../.gitattributes](../.gitattributes) | Line-ending policy: LF for every text type, `binary` for images/fonts/wasm. Do not remove entries: SRI hashes depend on it. |
| [../termux_setup.sh](../termux_setup.sh) | Installs Termux native/Python prerequisites with retry logic and requests shared-storage permission. |
| [../requirements.txt](../requirements.txt) | Declares Python dependency ranges used by setup. Update alongside imports and compatibility-sensitive protocol libraries. |
| [../constraints.txt](../constraints.txt) | Generated/platform package constraints, particularly Termux-managed packages; regenerate through the setup workflow rather than hand-editing without reason. |
| [../server_config.json](../server_config.json) | Persisted runtime/server/protocol/feature settings loaded by `config.py`. |
| [../storage_config.json](../storage_config.json) | Persisted storage, database and cache directory overrides read by `paths.py`. |
| [../.github/workflows/tests.yml](../.github/workflows/tests.yml) | GitHub Actions on every push / pull request to `main` and `dev`: job `smoke + check` (`tests/smoke.py`, `tests/check.py`) and job `behavioral tests` (`python tests/qa.py ci`, informational for now). |
| [../pyproject.toml](../pyproject.toml) | Tool configuration only (no `[project]` / `[build-system]`): `[tool.pytest.ini_options]` with `pythonpath = ["."]`, `--import-mode=importlib` (tests/ has no `__init__.py`), `timeout = 120`, markers. Do not keep a `pytest.ini` next to it: pytest would use that instead. |
| [../requirements-dev.txt](../requirements-dev.txt) | Test-only packages (`pytest`, `pytest-timeout`); not managed by `setup_pymodules.sh`. Deliberately NOT merged into `requirements.txt` / `setup_pymodules.sh`: that is the production dependency list, and the script rewrites constraints to `<next_major` and drops version floors. |
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
| [../config.py](../config.py) | `os`, `platform`, `subprocess`, `json`, `time`, `winreg*`, `shutil*` | None | `paths`, `version_engine*` |
| [../core.py](../core.py) | `os`, `sys`, `shutil`, `json`, `asyncio`, `threading`, `time`, `logging`, `uuid`, `socket`, `zipfile`, `io`, `re`, `subprocess`, `hashlib`, `datetime`, `queue`, `dataclasses`, `typing`, `mimetypes`, `secrets`, `random*`, `hmac*`, `functools*` | `quart`, `werkzeug`, `zipstream`, `itsdangerous` | `paths`, `helpers.net_utils`, `config`, `database`, `auth`, `storage`, `version_history`, `file_monitor`, `search_index`, `realtime_stats`, `realtime_shares`, `logging_setup` |
| [../database.py](../database.py) | `os`, `secrets`, `sqlite3`, `threading`, `uuid` | `bcrypt`, `cryptography.fernet`, `impacket.ntlm*` | `paths` |
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
| [../routes/files.py](../routes/files.py) | `os`, `shutil`, `asyncio`, `threading`, `time`, `logging`, `secrets`, `json*` | `quart`, `zipstream` | `core`, `config`, `auth`, `storage`, `file_monitor*` |
| [../routes/hls.py](../routes/hls.py) | `os`, `json`, `asyncio`, `threading`, `re`, `subprocess`, `hashlib`, `shutil*`, `glob*` | `quart` | `core`, `config`, `storage`, `paths*` |
| [../routes/image_preview.py](../routes/image_preview.py) | `os`, `json`, `asyncio`, `threading`, `time`, `re`, `hashlib` | `quart`, `pyvips*` | `core`, `config`, `storage`, `paths*` |
| [../routes/login.py](../routes/login.py) | `asyncio`, `time`, `logging`, `uuid` | `quart` | `core`, `auth` |
| [../routes/previews.py](../routes/previews.py) | `os`, `asyncio`, `logging`, `zipfile`, `html*`, `datetime*`, `csv*`, `tarfile*` | `quart`, `mammoth*`, `openpyxl*`, `pptx*`, `pyzipper*`, `py7zr*`, `rarfile*` | `core`, `config`, `storage` |
| [../routes/shares.py](../routes/shares.py) | `os`, `asyncio`, `time`, `logging`, `uuid`, `secrets` | `quart`, `zipstream`, `itsdangerous` | `core`, `config`, `database`, `auth`, `storage`, `realtime_shares` |
| [../routes/site_meta.py](../routes/site_meta.py) | None | `quart` | `core` |
| [../routes/stats.py](../routes/stats.py) | `os`, `sys`, `io`, `asyncio`, `threading`, `time`, `traceback*`, `shutil*` | `quart` | `core`, `config`, `auth`, `storage`, `search_index`, `realtime_stats`, `file_monitor*` |
| [../routes/uploads.py](../routes/uploads.py) | `os`, `shutil`, `json`, `asyncio`, `threading`, `time`, `uuid`, `queue` | `quart`, `werkzeug` | `core`, `config`, `database`, `auth`, `storage`, `routes.shares` |
| [../routes/versions.py](../routes/versions.py) | `os`, `asyncio`, `logging`, `mimetypes` | `quart` | `core`, `config`, `auth`, `storage`, `version_history` |
| [../helpers/__init__.py](../helpers/__init__.py) | None | None | None |
| [../helpers/hypercorn_ssl_fix.py](../helpers/hypercorn_ssl_fix.py) | `asyncio` | `hypercorn.asyncio.tcp_server*` | `logging_setup` |
| [../helpers/lanman_guard.py](../helpers/lanman_guard.py) | `ctypes`, `json`, `os`, `platform`, `subprocess`, `datetime`, `socket*` | None | None |
| [../helpers/net_utils.py](../helpers/net_utils.py) | `socket` | None | None |
| [../helpers/parent_watch.py](../helpers/parent_watch.py) | `os`, `sys`, `threading`, `time`, `ctypes*` | None | None |
| [../helpers/ssl_cert.py](../helpers/ssl_cert.py) | `datetime`, `ipaddress`, `os`, `socket`, `sys*` | `cryptography*` | `paths*`, `config*` |
| [../tools/kick_sessions.py](../tools/kick_sessions.py) | `os`, `secrets`, `sys` | None | `database` |
| [../tools/manage_users.py](../tools/manage_users.py) | `os`, `sys`, `getpass*`, `datetime*` | None | `paths`, `database` |
| [../tools/reset_db.py](../tools/reset_db.py) | `os`, `shutil`, `sys`, `importlib*` | None | `paths*`, `helpers.lanman_guard*`, `database*` |
| [../tools/revoke_sharing.py](../tools/revoke_sharing.py) | `argparse`, `getpass`, `random`, `os`, `re`, `sys`, `time` | None | `database` |
| [../tools/setup_storage.py](../tools/setup_storage.py) | `os`, `sys`, `json`, `importlib*`, `shutil*`, `traceback*` | None | `config*`, `paths*` |
| [../tools/smb_setup.py](../tools/smb_setup.py) | `json`, `os`, `platform`, `subprocess`, `sys`, `ctypes*` | None | `helpers.lanman_guard`, `paths`, `config*` |
| [../tools/sri_validator.py](../tools/sri_validator.py) | `argparse`, `base64`, `hashlib`, `os`, `re`, `sys` | None | None |
| [../tools/version_manage.py](../tools/version_manage.py) | `argparse`, `os`, `sys`, `time` | None | `config`, `version_engine` |
| [../tests/check.py](../tests/check.py) | `argparse`, `ast`, `fnmatch`, `importlib.util`, `json`, `os`, `re`, `subprocess`, `sys`, `pathlib`, `importlib*` | `pyflakes*` | Runtime-selected imports via subprocess* |
| [../tests/codeql_sarif_parser.py](../tests/codeql_sarif_parser.py) | `argparse`, `collections`, `csv`, `fnmatch`, `json`, `re`, `sys`, `zipfile`, `pathlib`, `urllib.parse` | None | None |
| [../tests/dir_tree.py](../tests/dir_tree.py) | `pathlib` | None | None |
| [../tests/smoke.py](../tests/smoke.py) | `argparse`, `ast`, `json`, `os`, `re`, `shutil`, `subprocess`, `sys`, `pathlib` | `pyflakes*` | None |
| [../tests/conftest.py](../tests/conftest.py) | `hashlib`, `json`, `os`, `shutil`, `socket`, `subprocess`, `sys`, `time`, `types`, `urllib.*`, `pathlib` | `pytest` | None (loads project code only in the scratch subprocess) |
| [../tests/qa.py](../tests/qa.py) | `argparse`, `shutil`, `subprocess`, `sys`, `time`, `pathlib` | None | None |
| [../tests/unit/test_paths.py](../tests/unit/test_paths.py) | `json`, `os` | `pytest` | `paths` (the only module tests import in-process) |

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
| `version_engine` | `dev_server`, `prod_server`, `version_history`, `tools.version_manage`, and `config` through a dynamic status lookup |
| `version_history` | `core`, `routes.versions` |
| `helpers.hypercorn_ssl_fix` | `prod_server`, `webdav_server` |
| `helpers.lanman_guard` | `smb_server`, `tools.reset_db`, `tools.smb_setup` |
| `helpers.net_utils` | `core`, `dev_server`, `ftp_server`, `prod_server`, `sftp_server`, `smb_server`, `webdav_server` |
| `helpers.ssl_cert` | `ftp_server`, `prod_server`, `webdav_server` |

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