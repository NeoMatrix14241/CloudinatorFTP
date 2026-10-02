# CloudinatorFTP — Complete Codebase Reference for AI-Assisted Development

**Version**: 4.61 (`file_index.py` only: `save()` now retries the `os.replace()` swap on Windows sharing violations like `storage_index.json` already did; `search_index.db` locking audited, not changed; 2026-10-02) on top of 4.60 (`app.py` only: web-UI move, rename and new-folder now trigger the background reconcile like delete/copy/upload already did, and `_trigger_reconcile()` coalesces overlapping requests into at most one running walk plus one queued follow-up; the 15-minute validation walk is unchanged; 2026-10-02) on top of 4.59 (`file_monitor.py` + `app.py`: `storage_index.json` is now validated on load (schema version, root path, counters, every `dir_info` record) and an aborted or suspect-empty walk can no longer overwrite good counters or the saved cache; reconcile logs per-folder drift; `/admin/rebuild_cache` now audits the file index with `verify_all()`; closes the open items of 4.58; no re-index or file deletion needed; 2026-10-02) on top of 4.58 (`file_index.py` only: `file_index.json` is now validated on load, on every read and on every walk, so the large-folder cache can no longer serve data that is stale after a restart or after a skipped watchdog event; the `storage_index.json` half (`file_monitor.py`) is NOT audited yet because that file was not available; no re-index or file deletion needed; 2026-10-02) on top of 4.57 (`static/js/bg_audio.js` only: background music now keeps retrying on every user gesture until the browser really lets it play, and a blocked autoplay no longer saves a false "paused" state; the 4 templates need their `integrity` hash recomputed (`./manage.sh validate-sri`, menu #21); 2026-10-02) on top of 4.56 (`manage.sh` gains `validate-sri` (runs `sri_validator.py`; menu #21 asks y/N to fix after a failed check, appended so no number shifts); `SERVER_MANAGEMENT_SCRIPT_GUIDE.md` updated; 2026-10-02) on top of 4.55 (`check_search_index.py` deleted by the owner (no longer needed); new `sri_validator.py` checks/repairs the SRI `integrity` hash of every local `<script src>`/`<link href>` in the templates; tooling only, no app code change; 2026-10-02) on top of 4.54 (frontend only: new optional background-music script `static/js/bg_audio.js` + `<audio id="bgMusic">` element added to `index.html`, `login.html`, `shared.html`, `404.html`; every new tag carries an SRI `integrity` hash; cosmetic feature, no backend change; 2026-10-02) on top of 4.53 (`search_index.py` + `file_monitor.py` + `app.py` + new `check_search_index.py`: search index kept correct after the first crawl — `reconcile_from_walk()` hooked into every `_full_walk`, `crawl_complete` marker so a half-built index is never trusted, DB keep-warm thread for the HDD cold-cache stalls, per-step `timing` in `/api/search`, dropped results now logged; owner's index found ~52% built and holding a stale path; 2026-10-01) on top of 4.52 (`app.py` + `search_index.py` + `webdav_server.py`: deep-search routes no longer block the event loop (`asyncio.to_thread`), event-loop stall watchdog, `fallback_reason` in `/api/search`, search crawler only in the main process, and `webdav_server.py` no longer re-runs all of `app.py` via `from app import get_local_ip` (now `from net_utils import get_local_ip`); root cause of the intermittent 20-53 s deep search NOT proven yet; 2026-10-01) on top of 4.51 (`app.py` + `static/js/index.js`: folder navigation no longer replays a cached 301-to-`/login` as "Session expired"; `validate_session` now returns 401 JSON to `/api/*`/XHR callers, `_lean_redirect()` sends `Cache-Control: no-store`, `navigateToFolder()` fetches with `cache:'no-store'`; 2026-10-01) on top of 4.50 (`static/js/index.js` only: deep-search FILE rows now open the Download options modal (Download current version / Version History) instead of downloading directly; column-header sorting now works on deep-search results; 2026-10-01) on top of 4.49 (CSS + `templates/index.html`: search-wrapper layout moved from an inline `style=""` into `.search-wrapper` in CSS because the CSP blocks unhashed inline styles — this was the real cause of the short search box and the floating icon; plus: `.search-row` `max-width` 800px -> 60vw, scales with the screen; the owner's local `min-width: 50vw !important` on `#tableSearch` is to be deleted; 2026-10-01) on top of 4.48 (`templates/index.html` only: removed the floating magnifier `<i>` inside `.search-wrapper` and the 🔍 emoji from the `#tableSearch` placeholder; 2026-10-01) on top of 4.47 (CSS only, `static/css/index.css`: `#tableSearch` left padding 45px -> 15px so text/placeholder start at the left edge; `.search-row` desktop `max-width` 480px -> 800px; the <=480px override is unchanged; 2026-09-30) on top of 4.46 (frontend: search no longer runs while typing — new Search button + Enter key trigger it; `static/js/index.js` + `templates/index.html` + `static/css/index.css`; 2026-09-30) on top of 4.45 (frontend, `static/js/index.js` only: the local-filter search highlight no longer turns into a full-width yellow bar — `smartTableColumnizer()` was restyling `span.search-highlight` with inline `!important` `display:block`; 2026-09-30) on top of 4.44 (frontend: deep search now starts at 3+ characters — 1-2 character terms only filter the current folder, `*.ext` terms still go deep; stale-response guard in `performDeepSearch()`; `index.html` placeholder/title say "3+"; `static/js/index.js` + `templates/index.html`; 2026-09-30) on top of 4.43 (backend fix in `search_index.py`: 1- and 2-character deep-search queries no longer return zero rows — the FTS5 trigram index cannot match under 3 characters, so short queries now use a parameterised `LIKE` on `files_meta`; `count()` now escapes `%`/`_` like the search does; no re-index needed; 2026-09-30) on top of 4.42 (search follow-up in `static/js/index.js`: highlight in FILE rows no longer splits the flex name cell; the "No results found" toast no longer fires while the local-filter fallback is showing a hit; 2026-09-30; the backend 2-char deep search was still open at 4.42 and is fixed in 4.43) on top of 4.41 (search-highlight fixes in `static/js/index.js` + `static/css/index.css`: full-width yellow bar, gaps inside highlighted words, broken markup on entity-like queries, `highlightSearchTerm()` wiping row icons; 2026-09-30) on top of 4.40 (deep search now uses true row windowing in `static/js/index.js`, replacing its append-only infinite scroll; `highlightText()` regex-escape fix; small `index.css` addition; 2026-09-30) on top of 4.39 (`manage.sh` WebDAV orphan-port sweep now follows `server_config.json`; docs clarify that background mode hides startup banners; 2026-09-30) on top of 4.38 (docs only: new `docs/MANAGE_SCRIPT_GUIDE.md` for `manage.sh`, README manage.sh section corrected, 2026-09-30; no code changes) on top of 4.37 (text-only code fixes: `webdav_server.py` startup message, `config.py` SMB comment + prompt; README Deployment Guides table completed; 2026-09-30; no logic changes) on top of 4.36 (docs only: WebDAV-HTTPS-by-default documentation sweep across README / RCLONE_DEPLOYMENT / USER_GUIDE / SETUP_TUNNEL_ADVANCED / SMB_PROTOCOL_DEPLOYMENT / CONFIG_PY_REFERENCE, 2026-09-30; no code changes) on top of 4.35 (docs only: `config.py` settings documentation audit, 2026-09-29; no code changes) on top of 4.34 (+ 2026-09-29 VT rubber-band ROOT-CAUSE fix in `static/js/index.js` + `static/css/index.css` — spacer height moved from the spacer `<tr>` (which `index.css`'s `#filesTable tbody tr{height:auto!important}` override can never lose to) onto its `<td>`, native scroll anchoring instead of JS `scrollTop` compensation, folder-row re-measure after `dir_info` loads; **reproduced and verified in real Chromium**; the two same-day CSP explanations that follow (4.33/4.32) are SUPERSEDED, see the part-8 sync note; earlier same-day entry, SUPERSEDED: 2026-09-29 VT spacer-height CSP fix in `static/js/index.js` — the two windowing spacer `<tr>`s had their dynamic height set via `tr.style.height = ...`, which this app's CSP silently blocks (`style-src-attr`'s precomputed hash allowlist can never match an arbitrary/changing px value); with spacer height never actually applied in a real browser, the wrapper's true scrollable area was far smaller than the windowing math assumed, and the browser clamped `scrollTop` back down on almost every layout pass — likely the dominant real cause of the "rubber band" bug, on top of the `_renderAll()` issue below. Fixed by inserting CSSOM rules into the already-CSP-permitted external stylesheet and mutating those instead of any element's `style` attribute; + 2026-09-29 VT scroll-position "rubber band" fix in `static/js/index.js` — `VT._renderAll()` briefly clears the table body on every refresh (SSE, polling, sort, filter, rename, not just real navigation), which collapses the wrapper's scrollable height and makes the browser clamp `scrollTop` back to 0 as a side effect; the scroll position is now captured before the clear and restored once the spacers give the wrapper its real height back, while `navigateToFolder()`'s own explicit `scrollTop = 0` still wins on real navigation; + 2026-09-28 VT row windowing / virtual scroll rewrite in `static/js/index.js` — replaces the append-only infinite-scroll table body with true windowed rendering, bounded DOM node count on folders with tens of thousands of entries; + 2026-09-28 Version History front-end restore/download loading state in `static/js/index.js`; + 2026-09-28 restore double-click guard + streaming version download: `version_history.py`, `version_engine.py`, `app.py`; 2026-09-28 write gate + storage_index.json WinError 32 fix: `_GatedConnection` in `version_engine.py`, unique-temp/locked `_save_cache` in `file_monitor.py`; 2026-09-28 follow-up: bounded GC transactions, transient-lock retry with self-requeue, `synchronous=NORMAL`, traceback logging; 2026-09-28 SQLite write-lock fix in `version_engine.py` — chunked captures no longer hold the write lock across chunk I/O, plus web-side lock-retry/error handling in `version_history.py`/`app.py`/`index.js`; 2026-09-28 Version History polish — "X of 50 versions kept" line, hide/clear failed attempts, Retry result shown inline, notification modal no longer hidden behind other modals; 2026-09-27 Version History web UI — `version_history.py`, five `/api/versions/*` routes + `/download/recovered/*`, Download-options/Version-History modals, Retry Now, plus three fixes found while verifying it: `call_on_close` doesn't exist in Quart, `/csrf-token` was unreachable anonymously, and `version_engine.py` was storing a generic "capture error" instead of the real exception; 2026-09-26 manage.sh integration for the Version Engine — `version-manage` inserted as menu #9, `config` moved to #10, everything else shifted down; `version_manage.py` gained a full interactive menu alongside its CLI subcommands, plus hardened Ctrl-C handling verified with real SIGINT delivery; 2026-09-25 new subsystem: Universal File Versioning Engine — `version_engine.py`, `version_manage.py`, plus `config.py`/`paths.py`/`dev_server.py`/`prod_server.py` changes; 2026-09-24 WebDAV client-IP trust-chain fix, confirmed tunneled on 8443; 2026-09-24 WebDAV audit logging + client-IP attribution for TLS-teardown errors; 2026-09-24 SFTP/FTP/SMB audit logging, SFTP upload flag bug fix; 2026-09-23 app.py client-IP logging change; 2026-09-22 database.py verification pass; 2026-09-21 ops-tooling sync: manage.sh, setup_pymodules.sh, revoke_sharing.py; earlier 2026-08-28 protocol-hardening, route-sync, and video-skin-overrides.css notes) | **Last Updated**: 2026-10-02  
**For**: AI assistants and developers modifying/extending CloudinatorFTP

**🆕 2026-10-02 sync note, part 8 — write-conflict audit of the JSON caches and `search_index.db` (Version 4.61, `file_index.py` only).** Owner question: can concurrent writes to the cache files lock? **Findings:** (1) `storage_index.json` (`_save_cache`): in-process saves are serialised by `_save_lock`, each save writes a unique temp file, and `os.replace()` is retried 7 times (0/0.05/0.1/0.2/0.4/0.8/1.5 s, about 3 s) on `PermissionError` (WinError 5/32); after that it logs `⚠️ Failed to save cache`, removes its temp file and the next change retries. (2) `file_index.json` (`save()`): same lock and unique temp file, but the swap had **no retry**, so a sharing violation (the WebDAV subprocess runs its own monitor against the same cache dir, plus antivirus/indexer) skipped that save. **Fixed:** `save()` now uses the same backoff (`_REPLACE_RETRY_DELAYS`); on permanent failure it still logs `⚠️  Failed to save file index`, removes its temp file and does not raise. In-memory data was never affected; the file on disk is re-validated on load. (3) **`search_index.db` (read, not changed):** WAL mode, `synchronous=NORMAL`, every write path takes the in-process `_write_lock`, and `sqlite3.connect()` is called with Python's **default 5 s busy timeout** (no explicit `timeout=`/`PRAGMA busy_timeout`, no retry on `database is locked`; the `add/remove/remove_tree/rename_tree` hooks catch the exception and only print `⚠️  Search index … error`, so a lost write is repaired by the next `reconcile_from_walk()`). `_write_lock` covers threads of one process only; a second process whose `FileSystemMonitor` runs the same watchdog hooks (the `_save_cache` docstring says the WebDAV subprocess does) could write the same DB, relying on SQLite's own locking and the 5 s timeout. **Not verified** whether that second monitor really writes the search index on the owner's server. If `database is locked` ever returns, the cheap hardening is `sqlite3.connect(..., timeout=30)`; not applied because the owner reports no current lock errors. **Tested:** `save()` retry with a patched `os.replace` (3 PermissionErrors then success after 4 attempts, temp file gone; permanent failure logs, cleans up, no exception); not on Windows.

**🆕 2026-10-02 sync note, part 7 — reconcile after every web-UI mutation (Version 4.60, `app.py` only; `file_monitor.py` and the 15-minute `_reconcile_loop` untouched).** Owner request: a reconcile should follow every change (delete, new file, move, rename, mkdir, copy) while the 15-minute walk stays as the periodic validation/correction. **Audit of `app.py`:** `_trigger_reconcile()` was already called from `/delete`, `/bulk_delete`, `/bulk_copy` (`settle=True`) and `assembly_worker` (upload finished); it was **not** called from `/bulk_move`, `/rename` or `/mkdir`. **Changes:** (1) `/bulk_move` calls it when `moved_count > 0` (before the 207/200 response, so partial success also reconciles); (2) `/rename` calls it right after the successful `os.rename`; (3) `/mkdir` calls it after a successful `storage.create_folder`. (4) **`_trigger_reconcile()` now coalesces** (`_reconcile_gate`, `_reconcile_running`, `_reconcile_rerun`): it used to start a new full-walk thread on every call, so N quick changes meant N overlapping walks of the HDD. Now one walk runs at a time; any trigger that arrives while it runs sets a flag that queues exactly one follow-up walk (the running walk may have missed the change); log line `🔄 Reconcile already running — follow-up queued`. Applies to all call sites, including the existing ones. Not covered by the gate: the 15-minute loop, the startup reconcile, the settle timer and `/admin/rebuild_cache` (they call `_reconcile()` directly, as before). **Effect on the 4.59 limits:** a deleted file's size and a moved folder's ancestor counts are now corrected within one walk after a web-UI action; changes made outside the web UI (Explorer, FTP/SFTP/SMB/WebDAV) still wait for the next scheduled walk because only the watchdog sees them. **Not done / ideas:** a short debounced reconcile after external watchdog deletions; `/bulk_move` still runs `shutil.move` directly on the event loop (pre-existing, not changed). **Tested:** coalescing logic extracted and run with a stubbed monitor (10 rapid triggers → 2 walks, flag reset, a later trigger runs normally); `app.py` `py_compile` only; the routes themselves and the Windows server were not exercised.

**🆕 2026-10-02 sync note, part 6 — `storage_index.json` validation + 4.58 open items closed (Version 4.59, `file_monitor.py` + `app.py`; `file_index.py`, `storage.py`, `realtime_stats.py`, JS and templates untouched).** Owner request: finish the "JSON caches always validated" work started in 4.58. `file_monitor.py` was supplied this time, so `storage_index.json` (counters, `dir_info`, checksum) was audited and the other three open items of part 5 were checked.

**Gaps found by code reading in `file_monitor.py` (not measured on the owner's server):** (1) `_load_cache()` trusted the file: no schema version, no record of which root it describes (a changed `ROOT_DIR` would have served the old tree's numbers), no check of counters or of any `dir_info` record; a record missing a key would later raise `KeyError` inside a watchdog handler thread; counters were assigned before `dir_info` was checked, so a failed load could leave half-loaded state. (2) `os.walk()` was called without `onerror`, so an offline drive, an unmounted share or an unreadable folder looked like "the tree is empty"; `_reconcile()` applied that result and `_save_cache()` wrote it over the good file, and `_full_walk()` also pushed it into `file_index.json` and the search index. An exception inside the walk was caught and its partial counts were applied the same way. (3) `_save_cache()` did not `fsync` (the file index already did) and never swept orphaned `storage_index.*.tmp` files. (4) The drift log only compared the three global counters, so wrong per-folder records were healed silently. (5) `get_dir_info()` returned the live record that handlers mutate under the lock. (6) If the root was missing at startup, `observer.start()` failed but the half-built observer was kept, so `stop_monitoring()` raised `cannot join thread before it is started` on shutdown.

**Changes:** (1) **`_load_cache()` validation, all-or-nothing for structure:** not a JSON object, `version` not 1 or 2, saved `root` different from the current root (compared with `normcase(abspath)`), bad/negative counters, or missing/empty `dir_info` → file discarded, first-boot walk runs, nothing is left half-loaded. **Repaired in place** (record zeroed or dropped, counted in `_load_repaired`): a `dir_info` record that is not a dict or has a missing/negative/non-numeric field, a malformed key (backslash, leading/trailing `/`), a missing root record `''` (rebuilt from the global counters), root record `file_count` different from the global counter, and legacy files with no `version`/`root` (cannot prove which tree they describe). Any repair makes the post-startup verification walk start after **3 s instead of 30 s** (`POST_START_RECONCILE_DELAY_REPAIRED`). **Expect this on the first start after upgrading:** the existing file has no `version`/`root`, so it is accepted but flagged and re-verified quickly; the next save writes both fields. (2) **`_save_cache()`** now writes `version` (2) and `root`, and `flush()`+`fsync()`s the temp file before `os.replace()`; `_load_cache()` removes `storage_index.*.tmp` older than 10 min (own prefix only; 10 min because the WebDAV subprocess runs its own monitor against the same cache dir). (3) **`_full_walk()` completeness:** `os.walk(onerror=…)` collects unreadable folders; result dict gains `complete` (False if the root is not a directory, the root itself errored, or the walk raised) and `errors` (count of unreadable folders, logged with the first path; the rest of the tree is still counted). `file_index_manager.build_from_walk()` and `search_index_manager.reconcile_from_walk()` run **only when `complete`**. (4) **`_reconcile(force=False)` now returns `bool`** and rejects (keeps the previous index, keeps the cache file, clears `_pending_reconcile`, schedules one retry after 60 s) a walk that is incomplete, or that finds 0 files and 0 dirs while the index holds ≥ 50 files (`SUSPECT_EMPTY_MIN_FILES`) — suspect-empty is rejected **once**; a second consecutive empty walk is accepted (tree really was emptied). `force=True` accepts an empty result. (5) **Drift report:** `_reconcile()` also compares every `dir_info` record old vs new and logs `folder records +added −removed ~changed`; "no drift" now requires `dir_count` and the folder diff to match too. (6) `get_dir_info()` returns a copy. (7) `start_monitoring()`: a first-boot walk that is not `complete` is applied but **not saved**, and a quick re-walk is scheduled; a failed `observer.start()` no longer leaves a dead observer behind (fixes the shutdown exception). (8) **`app.py` `/admin/rebuild_cache`:** calls `monitor._reconcile(force=True)`, then runs `file_index_manager.verify_all(repair=False)` (read-only) and appends `Verified N indexed folder(s) against disk: D drifted, U unreadable` to the success message (the Rebuild Cache button in `index.js` only shows a generic success text, so the detail is visible in the JSON response and the server log only); if the rebuild walk was rejected the route returns HTTP 500 with `previous index kept`. The route's inner function now returns `(monitor, applied, audit)`.

**Open items of part 5, answered:** (a) *`storage_index.json` reviewed* — see above. (b) *Do the handlers call `update_folder()` unconditionally?* **No.** `on_created`, `on_deleted` and `on_moved` return early (before the file-index call) while `_pending_reconcile` is set (whole reconcile walk + 0.5 s settle + 6 s post-walk drain, and burst storms) and when the reconcile epoch changed. This is deliberate (a 200-event burst into a 10k-entry folder would otherwise re-scan it 200 times) and **safe**: the walk's `build_from_walk()` re-reads every large folder at its end, and `get_entries()` compares the folder mtime on every read, so a skipped create/delete/rename is caught on the next read. A folder that crosses 80 entries upward during a suppressed window is simply not indexed yet, so `list_dir()` uses the live `scandir` listing (always correct) until the next walk indexes it. Outside the suppressed windows the call is unconditional (`update_folder()` indexes a folder when its scan exceeds 80). (c) *Is `list_dir()` called off the event loop?* **Yes** — all three call sites in `app.py` (`items = await asyncio.to_thread(storage.list_dir, …)` near lines 2052, 3086 and 5508 of the supplied file) use `asyncio.to_thread`; `grep` finds no other caller in the supplied files. (d) *`verify_all()` wired* — see change (8). `storage.py`'s comment in `list_dir()` ("kept up-to-date by the watchdog … on_created/on_deleted/on_moved each call update_folder()") is now outdated (freshness comes from the per-read mtime check); not edited.

**Known limits (inherent or left alone, not new bugs):** handler arithmetic for `storage_index.json` is still incremental and only the next walk (≤ 15 min, or 3 s after a repaired start) is the ground truth: a deleted file does not subtract its size from `_total_size` (the code cannot stat a deleted file; comment in `on_deleted`), moving a folder to a different parent does not transfer its file counts/sizes between the two ancestor chains, and a file edited in place does not change any counter until a walk. `/api/dir_info` stores a live-walk result for a not-yet-indexed folder into `_dir_info` without touching the global counters or the parents; the next walk replaces it. The suspect-empty rule means that if the whole tree is deleted on purpose, the first automatic walk after it is rejected and the second (≈ 60 s retry, or 15 min) accepts; use Rebuild Cache (`force=True`) to apply it immediately. A transient read error on a subfolder during a walk undercounts that subtree until the next walk (logged as `N folder(s) could not be read`).

**Tested:** 49 assertions in a harness against a real temp tree on Linux with stubbed `paths`/`config`/`search_index` and the real `file_index.py` (clean save/reload with `version`+`root`, `get_dir_info` copy, discard for bad version / other root / negative / string counter / missing / list `dir_info` / garbage JSON / JSON list with no partial state left, repair for a bad record / bad key / missing root record / root-vs-global mismatch / legacy file, stale-temp sweep keeps fresh temp files, offline root rejected with state and cache file untouched, suspect-empty rejected once then accepted, `force=True`, per-folder drift logged and healed, `start_monitoring()` with a repaired cache and with the root missing, no exception on `stop_monitoring()`). `app.py` was only syntax-checked (`py_compile`), the route itself was not exercised. **Not tested:** on the owner's Windows/NTFS server, with real watchdog traffic, the unreadable-subfolder case (the sandbox runs as root, so the `chmod 0` check was skipped), the 3 s quick re-walk on the HDD with a large tree, or the Rebuild Cache button end to end.

**🆕 2026-10-02 sync note, part 5 — `file_index.json` validation (Version 4.58, `file_index.py` only; public API unchanged, `file_monitor.py`/`storage.py`/`app.py` untouched).** Owner request: make the JSON caches (`file_index.json`, `storage_index.json`) always validated and always correct, the way the search index was fixed in 4.53. **This step covers `file_index.json` only.** `storage_index.json` is written/loaded by `file_monitor.py`, which was not supplied, so it has **not** been reviewed — open item, see the end of this note.

**Gaps found by code reading (not measured on the owner's server):** (1) `load()` trusted the file blindly (no version/threshold/record check) and `storage.list_dir()` serves from it immediately, i.e. pre-restart data is served until the post-startup walk finishes (minutes on the HDD). (2) Nothing checked freshness on read, so any event the watchdog handlers skip (the `_pending_reconcile` early-return from 4.53) left the cache wrong until the next 15-minute walk. (3) `build_from_walk()` installed walk data that is minutes old, overwriting `update_folder()` calls that happened during the walk, and dropped folders that still exist if the walk came back partial. (4) `_scan_folder_entries()` returned `[]` on a read error, indistinguishable from an empty folder, so a transient error silently evicted a folder. (5) `update_folder()` never calls `save()` although the docs said it did (the file on disk is only refreshed by `build_from_walk()`). (6) `NamedTemporaryFile` temp files leak if the process dies mid-save.

**Changes:** (1) **`load()` validation**: schema `version` must be 1 or 2, `threshold` must equal `THRESHOLD` (else the whole file is discarded and rebuilt by the next walk), every record must be well-formed (`entry_count == len(entries)`, `entries` a list of `{name:str, is_dir:bool,…}`, key normalised); bad records are dropped and counted in the log line. Every surviving record is **unverified** (in-memory set `_unverified`, never written to JSON). (2) **`get_entries()` validates before returning**: an unverified record is fully re-scanned on its first read; otherwise one `os.stat()` of the folder is compared with the new per-record field **`dir_mtime_ns`** (folder mtime read *before* the scan, so a change during the scan can only cause an extra re-scan, never a missed one). Mismatch, vanished folder, unreadable folder or count ≤ 80 → re-scan or `None` (caller falls back to the live `os.scandir` listing). Version 1 files (no `dir_mtime_ns`) load fine and are simply re-read. (3) **`build_from_walk()` rewrite**: the walk only decides *which* folders exceed `THRESHOLD`; each of those (plus every previously indexed folder, in case the walk was partial) is re-read from disk right then via `_scan_checked()`; an empty walk never wipes the index; folders a handler updated or removed while the build ran (`_touched_seq`/`_mut_seq`) keep the handler's newer state; previous cache vs disk is diffed and logged as `🔧 File index reconcile: N folder(s) differed from disk (+a / -r entries, ~c size/mtime changes), n newly indexed, m dropped` (printed only when something differed — a persistently non-zero number means the live watchdog updates are not keeping up). (4) New `_scan_checked()` returns `(None, None)` on a read error; `update_folder()` then evicts the folder (live listing is always right). `_scan_folder_entries()` keeps its old `[]`-on-error behaviour for existing callers. (5) `save()`: temp files now `file_index_*.tmp`, `flush()`+`fsync()` before `os.replace()`; `load()` removes `file_index_*.tmp` older than 1 h (own prefix only, never another module's temp files). (6) All mutators normalise their key (`\`→`/`, strip `/`); `rename_folder()` copies the record instead of mutating one `save()` may be serialising. (7) New **`verify_all(repair=False)`**: on-demand audit — re-scans every indexed folder, returns `{checked, drifted, unreadable, details}` and with `repair=True` fixes drift. `get_stats()` gained `unverified_folders` and `last_build`. Nothing calls `verify_all()` yet; hook it to `/admin/rebuild_cache` or a console if wanted.

**Known limits (inherent, not bugs):** a file edited *in place* (same name, new size/mtime) does not change its folder's mtime, and a subfolder's own `modified` value in the parent listing goes stale when something changes deeper inside it; both are corrected by the next walk (≤ 15 min) or by a watchdog `on_modified` that calls `update_folder()`. The first listing of each large folder after a restart does one full scan (that is the price of never serving pre-restart data; later reads are a single `stat`). `get_entries()` now does an `os.stat()` and occasionally a scan, so `list_dir()` must be called off the event loop (`asyncio.to_thread`) — **confirm in `app.py`, not checked**.

**Tested:** 34 assertions against a real temp directory tree on Linux with stubbed `paths`/`config` (build, external add/remove/rename with no handler, shrink below threshold, deleted folder, load of bad version/threshold/malformed/truncated/v1 files, first-read re-scan after load, empty and partial walk, stale walk data, handler update and eviction during a build, unreadable folder, key normalisation, temp-file sweep, `verify_all`). **Not tested:** on the owner's Windows/NTFS server, with real watchdog traffic, or at 20k+ entries per folder (scan time of one big folder after a restart is unmeasured). NTFS directory-mtime behaviour was assumed to match Linux for create/delete/rename and not verified.

**Resolved in 4.59 (see part 6 above).** **Open — `storage_index.json`:** needs `file_monitor.py` (`_save_cache`, `_load_cache`, `_full_walk`, handlers, `get_dir_info`, checksum) before any claim about it; likely questions: is the loaded snapshot trusted before the first walk, are `dir_info` counters reconciled against disk, do the skipped-handler paths corrupt counters. **Also unchecked:** whether the handlers call `update_folder()` for *every* event or only when `is_indexed()` is already true (a folder crossing 80 entries upward needs the unconditional call).

**🆕 2026-10-02 sync note, part 4 — background music did not autoplay after a refresh with no interaction (Version 4.57, `static/js/bg_audio.js` only).** Owner report (Edge): after pressing refresh and not touching the page, the music does not start. **Cause (browser policy, not a CSP or markup problem):** browsers only allow sound without a user gesture when the site has earned autoplay (Chromium/Edge "media engagement", or the Edge setting Media autoplay = Allow for the site); a reload resets the page\'s user activation, scrolling and moving the mouse are not gestures, and `<audio autoplay>` + `audio.play()` are both rejected until a click/tap/keypress. This cannot be fully removed from page code. **Three real weaknesses found in the 4.54 script and fixed:** (1) the interaction fallback used `{ once: true }` on `click`/`keydown`/`touchstart`, so the listener was used up by the first event even when `play()` was still refused (for example a lone Shift/Ctrl keypress does not count as a gesture); it now stays armed on `pointerdown`, `mousedown`, `click`, `keydown`, `touchstart` and `touchend` (capture phase) and removes itself only after `play()` succeeds. (2) `saveState()` wrote `cloudinator_bg_music_playing = "false"` whenever the audio was paused, including when the browser had merely blocked autoplay, so after a blocked load plus a refresh the saved state said "not playing" and the autoplay attempt was skipped; `saveState()` now only ever writes `"true"`, and `"false"` comes only from a real `pause` event. (3) a `pause` event fired while the page is being torn down is now ignored (`leavingPage` flag set on `beforeunload`/`pagehide`). **Unchanged:** volume 0.20, position restore, no on-page controls, the `<audio>` markup, CSP (still compliant). **Browser-side fix for the owner (Edge):** Settings → Cookies and site permissions → Media autoplay → set to Allow, or add the site to the Allow list (the exact menu wording was not checked here; the setting is per browser). **Because `bg_audio.js` changed, its SRI hash in `index.html`, `login.html`, `shared.html` and `404.html` is now stale — run `./manage.sh validate-sri` and answer `y` (menu #21) or `./manage.sh validate-sri --fix`, then reload each page once.** **Tested:** logic only, with a stubbed `document`/`window`/`localStorage`/audio object in Node (blocked-autoplay + refresh keeps the flag unset; a refused first gesture keeps the listeners armed and a later gesture starts playback and disarms them; a pause during unload is ignored; a real pause is recorded as false; allowed autoplay still plays); `node --check` clean. **Not tested:** real Edge/Chrome autoplay behaviour, which only the owner\'s browser can show.

**🆕 2026-10-02 sync note, part 3 — `sri_validator.py` hooked into `manage.sh` (Version 4.56; `manage.sh` + guide; no app code change).** (1) **New command `./manage.sh validate-sri [args]`** → `cmd_validate_sri()`, which calls `run_utility "sri_validator.py" --templates "${SCRIPT_DIR}/templates" --static "${SCRIPT_DIR}/static" "$@"`. The two default paths come first so they always point at the project folder wherever manage.sh is run from; anything typed after the command (`--fix`, or `--templates`/`--static` to override) comes later and wins. `run_utility` returns the validator's exit code, so a stale/missing/unresolvable hash makes `validate-sri` exit **1** (red `sri_validator exited with code 1.` line) and a clean check or `--fix` exits 0 ("sri_validator finished."); the `main()` dispatcher is `validate-sri) cmd_validate_sri "$@" ;;`. (2) **Menu #21** (`sri_validator.py — Check SRI hashes in templates`) was **appended** after #20 instead of inserted mid-list, specifically so none of the existing numbers (which this doc has had to renumber three times) move. The menu entry is `_menu_validate_sri()`: it runs the check, and only when the validator exits **1** (stale/missing/unresolvable hashes) asks `Fix the stale/missing hashes now? [y/N]` (via `_confirm`; Enter/`n`/Ctrl-D = no, and it prints the shell command to repair later); `y` runs `cmd_validate_sri --fix`. Exit codes 130 (Ctrl-C) and 2 (templates/static folder not found) are passed through with no question, and if `sri_validator.py` itself is missing `run_utility` reports `Script not found` without asking. From the shell, `--fix` is still explicit. `cmd_help` now has the command description, the MENU ↔ COMMAND MAP line `21  validate-sri`, two EXAMPLES lines, and the "(20 entries)" menu comment became 21. `manage.sh` itself keeps **LF** line endings (CRLF would break a bash script); only the docs are CRLF. (3) **Guide:** the owner\'s manage.sh guide is now named `SERVER_MANAGEMENT_SCRIPT_GUIDE.md` (earlier notes call it `docs/MANAGE_SCRIPT_GUIDE.md`; its own "See also" links imply it still lives in `docs/`). Updated with: Last Updated 2026-10-02, a `validate-sri` row in the Utility Commands table, a new `### validate-sri` section (what a stale hash does, statuses OK/STALE/NONE/MISS/skip, `--fix`, paths, when to run it, pre-commit use, limits), menu row 21, a Files-and-Folders row for `templates/` + `static/`, and two Troubleshooting rows (integrity error in the console; exit code 1). (4) **Tested** (mock tree: the owner\'s real templates + real `bg_audio.js`, made-up other static files; `bash -n manage.sh` clean): `validate-sri` from a different working directory found the templates, check exited 1, `--fix` exited 0, re-check exited 0 with 27 OK; `help` shows all four new lines; menu `21` on a clean tree ran the check with no question; on a stale tree `y` repaired everything (23 fixed) and re-check was clean, `n` and plain Enter left every template untouched, and a missing `sri_validator.py` gave `Script not found` with no prompt; an unknown command still exits 1. **Not tested:** on the owner\'s real tree/Git Bash/Termux, a git pre-commit hook, and the optional idea of a warn-only SRI check inside `start` (not added: it would add a Python launch to every start).

**🆕 2026-10-02 sync note, part 2 — `check_search_index.py` removed, new `sri_validator.py` (Version 4.55; tooling only, no `app.py`/JS/template change).** (1) **`check_search_index.py` deleted** by the owner ("we don't need it anymore"; it went out in the same git commit as the audio files, commit message wrongly said only "Removed check_search_index.py"). Everything the 4.53 notes say about running it is history only; the Quick Reference row is gone and the Performance/Troubleshooting mentions below were reworded. The search-index fixes it was written to verify (`crawl_complete` marker, `reconcile_from_walk`, keep-warm thread, `timing` in `/api/search`) are untouched. (2) **New `sri_validator.py`** (project root, standard library only, written from the owner's request for "all script and link tags"): `python sri_validator.py` scans `templates/*.html` (also `.htm`/`.jinja`/`.j2`), finds every `<script ...>` and `<link ...>` start tag, resolves `href`/`src` written as `{{ url_for('static', filename='X') }}` or `/static/X` to `static/X`, computes SHA-384 of the file bytes, and compares with the tag's `integrity`. Report statuses: `OK`, `STALE` (hash differs), `NONE` (no `integrity`), `MISS` (referenced file not found), `skip` (inline `<script>`, external URL, or not a static file). Exit code 1 on any STALE/NONE/MISS, so it can gate a commit or `manage.sh`. `python sri_validator.py --fix` writes the correct hash (replaces a stale value in place, or appends `integrity="..."` to the tag); templates are read/written as raw bytes, so CRLF and every other byte stay as they were. `--templates DIR` / `--static DIR` override the defaults (`templates`, `static`). It covers everything in the templates, including the files that were left unhashed on purpose in 4.54 (`video.js`, `video.css`, `viewer.mjs`, `viewer.css`, `locale.json`): the owner realised all of them are local files that can be hashed, so nothing has to stay unhashed except what cannot carry a hash. Hash-recompute is then one command after any edit, including the `bg_audio.js` hash duplicated in all four templates. (3) **Limits to remember.** Browsers enforce `integrity` only on `<script>` and on `<link>` with `rel` = `stylesheet`/`preload`/`modulepreload`; on `rel="icon"` and `rel="resource"` (the `locale.json` link) the attribute is ignored, and the validator tags those lines in its output. Hashing `viewer.mjs` does not cover the modules it `import`s or `pdf.worker.mjs` (loaded as a worker), so pdf.js stays only partly integrity-protected. Tags created at runtime (for example the `video-skin-overrides.css` link `index.js` adds) are in no template and are not checked. The hash must equal the bytes the server really sends: if git converts line endings (`core.autocrlf`) the deployed file can differ from the one on the PC, so run the validator on the deployed tree or pin endings with `.gitattributes`. `Integrity-Policy-Report-Only` in `app.py` can only move to enforcing once `video.js` and `viewer.mjs` carry hashes (use `--fix`); Cloudflare\'s injected beacon will be blocked by an enforcing policy regardless (harmless). (4) **Tested / not tested:** run against the uploaded `index/login/shared/404.html` with the real `bg_audio.js` and made-up stand-ins for every other static file: the real `bg_audio.js` hash in all four templates was recomputed identically (confirms the algorithm), `--fix` changed nothing except `integrity` values (CRLF counts identical), and a re-check was clean. NOT run on the owner\'s real `static/` tree yet.

**🆕 2026-10-02 sync note — optional background music + SRI coverage (Version 4.54, `static/js/bg_audio.js`, `templates/index.html`, `login.html`, `shared.html`, `404.html`).** Owner added a purely cosmetic looping background track ("for fun") to every page. Read from the uploaded files (templates, `bg_audio.js`, and `app.py` for the CSP); nothing here was run. (1) **New file `static/js/bg_audio.js`** (IIFE, `"use strict"`): finds `#bgMusic`, sets `audio.volume = 0.20` (edit this one line to change loudness, valid range 0.0–1.0), restores the last position from `localStorage` key `cloudinator_bg_music_time` (only if it is a finite number >= 0 and below `audio.duration`, applied on `loadedmetadata`), and autoplays when `localStorage` key `cloudinator_bg_music_playing` is `"true"` **or has never been set** (first visit therefore tries to play). It saves position on `timeupdate` and `beforeunload`, and play state on `play`/`pause`, so the track continues roughly where it left off when navigating between pages (it is a fresh `<audio>` element per page load, not one shared player, so there can be a short gap and a seek at each navigation). If the browser blocks autoplay (normal until the user has interacted with the site), `play()` rejection is swallowed and one-shot `click`/`keydown`/`touchstart` listeners start playback on the first interaction. There is **no on-page mute/pause control**; a user can only silence it via browser tab mute, because the `<audio>` has no `controls`. (2) **Markup added to all four templates**, identical block: `<audio id="bgMusic" autoplay loop preload="auto"><source src="{{ url_for('static', filename='audio/bg_mus.opus') }}" type="audio/ogg"></audio>` followed by `<script src="{{ url_for('static', filename='js/bg_audio.js') }}" integrity="sha384-zKKwynklM+FAe3fTXAeV2eqsmTFe5hev33WXyk3Ac+ebo5jzquGmawtupMCxiWNL" defer></script>`. The same SHA-384 appears in all four templates, so it must be recomputed in **all four** whenever `bg_audio.js` changes, or the browser silently refuses the script under `script-src 'self'` (same failure mode as the 404.js stale-hash bug in the Changelog). The audio file is `static/audio/bg_mus.opus` (a new `static/audio/` directory); it is declared `type="audio/ogg"`, which is the usual container type for Opus-in-Ogg; the file itself was not provided, so its real container was not checked. The `<audio>` element itself has no `integrity` (the attribute does not exist for media elements). (3) **SRI coverage in `index.html` as uploaded** — tags WITH `integrity`: `all.min.css`, `index.css`, `pdfjs-viewer-overlay.css`, `pdfjs-worker-init.mjs`, `icon.webp`, `index.js`, `bg_audio.js`. Tags WITHOUT `integrity`: `video.css`, `video.js`, `locale/locale.json`, `viewer.css`, `viewer.mjs` (plus the inline `initialFilesData` JSON block, which cannot carry one). Owner states this is deliberate: third-party libraries that have to be patched (pdf.js `viewer.css`/`viewer.mjs`, and by extension the other vendored player/locale files listed) are left unhashed because every local patch or version bump would change the hash; everything the owner writes themselves is hashed. This narrows the older note that only `login.js`/`404.js` had hashes (see [Embedded PDF.js Viewer](#embedded-pdfjs-viewer-2026-08-23) cross-reference and [Login Flow](#login-flow)): `index.js`, `pdfjs-worker-init.mjs`, `pdfjs-viewer-overlay.css`, `bg_audio.js` and the `index.html` stylesheets/icon are now hashed too. `viewer.mjs` still has no hash, so the `Integrity-Policy-Report-Only` -> enforcing blocker in `app.py` still applies to it. (4) **CSP check (done against `app.py`, 2026-10-02): compliant, no `app.py` change needed.** The CSP built in the after-request hook is `default-src 'none'` plus explicit directives. `media-src 'self' blob:` covers `/static/audio/bg_mus.opus` (same-origin media); `script-src 'self' 'nonce-…' https://static.cloudflareinsights.com` covers `bg_audio.js` (external file, no inline script, no inline handlers, so no new CSP hash is needed); `style-src*` is untouched because the feature adds no CSS or `style=""`. `Cross-Origin-Resource-Policy: same-origin` and COEP `credentialless` do not affect same-origin audio. The file is served by Quart's built-in `/static/<filename>` route, which the session check already treats as public (that is how `login.css` loads before login), so the track also plays on `login.html`, `shared.html` and `404.html` for anonymous visitors. `Integrity-Policy-Report-Only: blocked-destinations=(script)` only concerns `<script>` tags; the `<audio>` element is not covered and cannot carry `integrity` anyway. **Remember when changing the feature:** moving the track to a CDN/other origin, or using a `data:` URL, needs `media-src` updated (only `'self'` and `blob:` are allowed); keep the player as an external script, never inline. **Stale comment in `app.py`** (Integrity-Policy block): it still says `index.js` has no `integrity`, which is no longer true (hashed in `index.html` as of 4.54); `video.js` and `viewer.mjs` are the unhashed scripts left. **Still not verified:** the `.opus` file's real container (declared `audio/ogg`), and live playback in a real browser. `login.js` / `shared.js` / `404.js` were not touched. Mobile browsers generally refuse autoplay until a tap, which the interaction fallback covers.

**🆕 2026-10-01 sync note, part 2 — deep-search index found incomplete and stale; fixes (Version 4.53, `search_index.py`, `file_monitor.py`, `app.py`, new `check_search_index.py`).** Follow-up to the 4.52 note below. **What the owner's server showed (measured):** (1) slow searches that were server-side, not event-loop: one deep search returned `from_index: true, fallback_reason: null, search_time: 11.029` (so the 11 s was inside `count()`/`search()`), another reported 20.776 s (console object not captured). `search_index.db` is 223,144 KB on a 1 TB spinning disk. After the keep-warm deploy a single search showed `search_time: 0.039` (`timing: {count: 0.034, search: 0.005}`) — **one data point only.** (2) `Days_of_Thunder.mp3` returned "No results" with `total_count: 1` but `results: []`: `check_search_index.py` showed `files_meta` and the FTS table both held the file at `-- DMS FILES --/MP3/The Midnight Greatest Hits/…` while the real location is `-- DMS FILES --/Media/MP3/…` (folder moved under `Media`), so `_db_search()`'s `os.stat()` raised `FileNotFoundError` and the row was **silently dropped**. (3) The index held only **126,316 FTS rows / 126,307 `files_meta` rows** versus ~241k real entries (228,979 files + 12,131 dirs from the startup log) — about 52% — i.e. a half-built index that the old `_crawl()` Case A had accepted as complete (the 4.52 note's open concern (b), now confirmed on real data).

**Root causes found by code reading (not all individually proven for the owner's case):** (a) `file_monitor.InstantFileEventHandler.on_created/on_deleted/on_moved` `return` early while `monitor._pending_reconcile` is set (bulk-operation settle window) and when the reconcile epoch changed, and those returns come *before* the `file_index_manager` / `search_index_manager` calls. The settle/15-minute/post-startup walk then repaired counters, `dir_info` and (via `file_index_manager.build_from_walk`) the file index — but **nothing ever repaired the search index**, and changes made while the server was down never reached it either. The `MP3` → `Media/MP3` move is consistent with this but the exact trigger was not confirmed. (b) `_crawl()` Case A trusted any DB whose `files_meta` was ≥ 95% of the FTS count, so a crawl interrupted by a restart (the owner restarted several times while deploying) was accepted as complete forever. (c) HDD cold cache: each search opens a fresh SQLite connection (8 MB page cache), so a ~220 MB DB depends entirely on the OS file cache, which transfers/walks evict — **hypothesis**, consistent with the 11 s vs 0.039 s spread, not proven.

**Changes (compiled; exercised on a throwaway DB on Linux — NOT yet run on the owner's server):** (1) **`index_state` table + `crawl_complete` marker** (`search_index.py` bootstrap): `_crawl()` Case A now additionally requires `index_state.crawl_complete = '1'`; the Case B/C wipe also clears `index_state`; the marker (and `crawl_rows`) is written only when a crawl finishes, right before `_ready = True`. A DB without the marker (every DB built by pre-4.53 code, including the owner's current one) prints `🔄 Search index: previous crawl never finished (no completion marker; N rows) — rebuilding from filesystem` and rebuilds once. (2) **`SearchIndexManager.reconcile_from_walk(direct_entries)`**: builds the filesystem path set from the same `direct_entries` dict `_full_walk` hands to `file_index_manager.build_from_walk`, diffs it against `files_meta`, removes stale rows (FTS rows deleted by rowid after one `SELECT rowid, rel_path FROM files` scan, `files_meta` by primary key) and inserts missing ones with `_batch_insert()` in 500/1000-row batches under `_write_lock`. Guards: no-op until `_ready`; empty walk ignored; change sets ≤ 5,000 are re-checked with `os.path.lexists()` against the live disk (a walk takes minutes, events handled meanwhile may already have changed things); if > max(2,000, 25% of the index) rows look stale it refuses to delete and prints a warning (the walk swallows its own errors and can return a partial tree). Prints `🔄 Search index reconciled with filesystem: +N added, -M removed` only when something changed. `file_monitor._full_walk()` calls it right after `file_index_manager.build_from_walk(direct_entries)` inside try/except. (3) **Cache keep-warm**: `_ensure_warmer()` / `_warm_loop()` / `_warm_once()`, constants `_WARM_INTERVAL_SECS = 600`, `_WARM_CHUNK = 4 MB`, daemon thread started whenever `_ready` becomes True; every 10 min it sequentially reads `search_index.db` and `search_index.db-wal` (2 ms sleep per chunk) and runs one `files_meta` count and one FTS `MATCH` so their pages are in the OS cache; prints `🔥 Search index cache warmed: N MB in Xs` for the first pass and later only when a pass took > 1 s (`(was cold)`). (4) **`/api/search` diagnostics** (`app.py`): response gains `timing: {count, search}` (seconds; `count` = the offset-0 `total_count` query, `search` = results query incl. one `os.stat()` per row) and a `⏱️  Slow search …` console line when total > 1 s. (5) `_db_search()` no longer drops rows silently: `⚠️  Search: dropped '<rel_path>' (os.stat failed: …)`. (6) New standalone, read-only **`check_search_index.py`** [deleted in 4.55] (run from the app folder: `python check_search_index.py ["file name"]`): prints DB size, `files` vs `files_meta` row counts, the `crawl_complete` marker, whether the named file is in `files_meta`/FTS and exists on disk, and how many of 300 random `files_meta` names the FTS table cannot find. **Known limit of the checker:** that sample can only test names already in the index — it cannot detect an index that is missing part of the tree; compare its row count with the file monitor's counts (≈ files + dirs) instead.

**Rebuild procedure** (needed once on the owner's server after deploying 4.53; the old index is ~52% built): stop the server completely, delete `search_index.db`, `search_index.db-wal`, `search_index.db-shm` in the DB dir (optional — a marker-less DB is rebuilt automatically, but deleting also gives a fresh, smaller, contiguous file, which helps on an HDD), start, and **do not restart until** `✅ Search index ready: N dirs + M files indexed in Xs` appears (expect roughly 12,131 dirs + ~229k files; hidden entries are skipped; several minutes, the 10 ms/dir pause alone is ~2 min). Until then deep search uses the slow `os.walk` fallback. **NOT verified / open:** whether the keep-warm actually removes the 11–20 s stalls over a longer period; the real rebuild time and its `Search index ready` numbers; what the first reconcile prints on the real tree; `SearchIndexManager.add()` still runs `DELETE FROM files WHERE rel_path = ?` on the FTS table per create event, which FTS5 cannot index (full table scan each time) — a possible improvement is guarding the FTS insert with a `files_meta` primary-key check; during a re-crawl the tables are still wiped first, so the index is empty until it finishes (crawl-without-wiping, or serving a partial index, was considered and not done).

**🆕 2026-10-01 sync note — slow deep search investigation + WebDAV subprocess no longer re-runs `app.py` (Version 4.52, `app.py`, `search_index.py`, `webdav_server.py`).** Owner report: deep search (e.g. `.qbw`) sometimes stalls for 20-53 s. Two different symptoms were seen: (a) the UI showed `Search time: 0.075s, 3932 items found` yet the browser waited ~20 s, with `net::ERR_HTTP2_PING_FAILED` on the SSE streams (`/admin/shares/requests/stream`, `/api/storage_stats_stream`); (b) `Found 500 results (53.661s)` with the console object showing `from_index: false`, i.e. the request was answered by the `os.walk` fallback, not the index. Tree size from the startup log: **228,979 files, 12,131 dirs** (~241k index rows; the "28,500" first quoted in the chat was not the tree size).

**Changes (all code-read + compiled; behaviour verified only where stated below).** (1) `app.py` `/api/search`: `search_index_manager.count()`, `.search()` and `._walk_fallback()` now run via `await asyncio.to_thread(...)`; before, blocking SQLite, per-result `os.stat()` and `os.walk` ran directly on Hypercorn's single event loop, which can stall every request, SSE heartbeat and HTTP/2 ping at once (symptom (a)). (2) New event-loop stall watchdog in `app.py` (just above the `/api/search` route): `_loop_heartbeat()` stamps `_loop_beat` every 250 ms on the loop, a plain daemon thread (`_loop_watchdog_thread`, started from an `@app.before_serving` hook) prints `🚨 EVENT LOOP BLOCKED for N s - blocking code:` plus the loop thread's current stack when the beat is older than `_LOOP_STALL_SECS = 2.0`. Diagnostic only, no effect on requests. (3) `search_index.py`: `SearchIndexManager._last_fallback_reason` records why `search()` used `os.walk` (`"index not ready (crawler still running or failed)"` or `"index query error: ..."`; `None` when the DB answered) and prints a `⚠️  Search: ...` line; `/api/search` returns it as `fallback_reason` next to `from_index` (`None` when served from the DB; the "search index disabled (ENABLE_SEARCH_INDEX)" text when the flag is off). (4) `app.py`: `search_index_manager.start_crawler()` is skipped when `os.path.basename(sys.argv[0])` is `webdav_server.py` or `version_engine.py` (prints `ℹ️  Search index crawler skipped in this helper process`) — a safety net. (5) `webdav_server.py` line ~85: `from net_utils import get_local_ip` replaces `from app import get_local_ip`. **Why (5) matters:** the old import executed all of `app.py`'s top-level code inside the WebDAV OS subprocess, so every start the `[webdav:OUT]` log repeated the whole startup — second file monitor + 12k-folder reconciliation walk, second search crawler on the same `search_index.db` (when the DB is empty, two processes wipe and refill the same tables), second chunk/orphan/share cleanup schedulers, second assembly worker. `app.py`'s own `get_local_ip()` docstring already said the function had moved to `net_utils.py` and that `webdav_server.py` should import it from there; the file just had not been switched. (`net_utils.py` itself was not reviewed in this pass.)

**Verified live (owner's server log, 2026-10-01 17:22 restart, after deploy):** the `[webdav:OUT]` block now stops after the config lines and the WebDAV HTTPS lines — no file monitor, crawler, schedulers, assembly worker or reconciliation walk; no `🚨 EVENT LOOP BLOCKED` line on that restart; HTTP requests logged at 0-47 ms. The watchdog was also tested standalone (it reports a deliberate 3.5 s block with the blocking line) and fired once on the *previous* restart: 2.5 s during start-up inside Hypercorn's lazy `aioquic`/HTTP-3 module import when the QUIC listener starts — one-time and unrelated to search. **NOT verified / open:** (a) the root cause of the slow deep search is **not proven**. Working hypothesis, from code reading plus symptom (b): while `search_index_manager._ready` is `False` (crawler still running, or crashed — `_ready` is only set by `_crawl()` when it finishes) every search falls back to `os.walk`, which on this tree competes with the crawler and the start-up reconciliation walk for disk; the owner has not been able to reproduce a slow search since deploying. The log excerpt captured so far ends before the crawler prints `loaded from disk` / `fresh crawl starting…` / `files_meta incomplete…` / `Search index ready … in Ns`, so it is still unknown whether a restart re-crawls the whole tree and how long the not-ready window lasts. (b) Code-reading concerns, not changed: `_crawl()` Case A treats any DB with `files` > 0, `files_meta` > 0 and `files_meta >= 0.95 * files` as complete, so a restart in the middle of a crawl leaves a half-built index that is then trusted as ready; the crawl wipes both tables before refilling, so the index is empty/unreliable for the whole re-crawl (a crawl-without-wipe plus a "crawl complete" marker would fix both). (c) With `from app import` gone, `ensure_dirs()` no longer runs inside the WebDAV process (its `📂 DB dir ready` lines are gone from `[webdav:OUT]`); by code reading the main process always calls it first because `protocol_manager.start_all()` runs after `from app import app`, but a standalone `python webdav_server.py` on a brand-new install was not tested. **Next step for whoever continues:** restart, wait, capture the main process's `Search index` lines and the `fallback_reason` of any slow search before changing the crawler.

**🆕 2026-10-01 sync note — "Session expired" on Root / Up / Parent-directory navigation (Version 4.51, `app.py` + `static/js/index.js`).** Owner report: clicking Root, Up, or the parent row shows "Session expired - please login again" while the console shows `/api/files/` answering 200 with `redirected: true` and `url: https://<host>/`. Reading of the code (NOT yet confirmed against a live Network tab): the 200 is the HTML of `/`, not JSON, so `navigateToFolder()`'s content-type guard fires the toast. The hop chain `/api/files/` -> 301 `/login` -> 302 `/` happens when a 301 from `validate_session` is replayed from the browser cache: `_lean_redirect()` sent no cache headers, `after_request` only adds `no-store` for logged-in/known endpoints, and a 301 is cacheable indefinitely, so one unauthenticated hit on an API URL is remembered and then replayed even when logged in (`/login` sees `logged_in` and bounces to `/`). The root URL is one fixed string, which is why Root fails consistently. Second defect: `validate_session` pre-empted `login_required`, so its documented 401-JSON branch for `/api/*` was unreachable — the API got a redirect instead. Fix: (1) `_lean_redirect()` adds `Cache-Control: no-store`; (2) new `_wants_json_auth_error()` / `_unauthenticated_response()` apply `login_required`'s own test (`/api/*`, `X-Requested-With: XMLHttpRequest`, `Accept: application/json`) and return 401 JSON + `no-store` at both `validate_session` auth failures, plain `_lean_redirect` 301 otherwise (ZAP behaviour unchanged for page URLs); (3) `navigateToFolder()` fetches with `cache:'no-store'` plus `Accept`/`X-Requested-With` headers, which also bypasses any entry already cached. Verified: `py_compile`, `node --check`, CRLF intact, and a real Quart test that a `before_request` tuple returns 401 + `no-store`. **NOT verified** in the owner's browser. If it persists, check the Network tab: `(from disk cache)` confirms this diagnosis; a real request with a log line `/api/files/ ... (status 301)` means the session genuinely dropped and something else is wrong. Other `fetch()` calls in `index.js` were not changed.

**🆕 2026-10-01 sync note — deep-search download opens the options modal (Version 4.50, `static/js/index.js` only).** Owner report: in deep search, a file row's Download button downloaded straight away while normal rows show `#downloadOptionsModal` (Download current version / Version History). Cause: the deep-search row builder (`createSearchResultRow`-area, the `search-result-actions` block) had `data-fn="downloadItem"`; normal rows use `data-fn="showDownloadOptionsModal"`. Fix: the file button now uses `showDownloadOptionsModal` with `dataArgs([result.path, result.name])`; folder rows still use `downloadFolderAsZip`. The modal/handlers are unchanged (static element, `closeDownloadOptionsModal()` then `downloadItem`/`showVersionHistoryModal`). One line changed for the download button; CRLF kept. **NOT verified** in a browser: that the modal stacks above the deep-search results and that Version History loads for a deep-search path (same path format as normal rows, by code reading).

**Deep-search sorting (same version).** Owner report: clicking a column header did nothing while deep-search results were showing. Cause: `sortTable()` -> `VT.applySort()` returns immediately when `_searchResultsMode` is true (the results live in `_dsAll`, not in VT's data array). Fix: `sortTable()` now routes to new `_dsSortResults()` when `isSearchResultsDisplayed`. Sort state is `_dsSort` (separate from the folder's `currentSort`, which is untouched); it resets on a new search and on teardown, and header arrows go back to `currentSort` via `_dsRestoreSortHeaders()`. Because `/api/search` pages results (500 per page, index order) a sort over only the loaded pages would be wrong while `has_more` is true, so `_dsLoadAllPages()` first fetches every remaining page (1000 rows each, the server max, spinner in the search box), then `_dsApplySort()` sorts `_dsAll` (folders first, like VT; name/size/type/modified), unmounts the window and re-renders from row 0. Selected rows keep their selection (`_dsCreateRow` re-checks `selectedItems`). `modified` is sorted via `Date.parse` on the string the server sends (numbers pass through) — the exact server format was not visible (`search_index.py` not provided). Not done: server-side sorting (would need a `sort` param in `search_index.py`/`/api/search`); with very large result sets the load-all step can take a few seconds. Sorting while the load is in flight is ignored. **Follow-up (same version):** owner report — deep sort only went ascending, and Reset Sort left deep search. (1) A Node `vm` run of the real `_dsSortResults`/`sortTable` toggled asc/desc/asc correctly in isolation, so the logic was not the cause; the likely cause is the header click reaching `sortTable()` twice in the browser (two click listeners on `.sortable`, see the DOMContentLoaded block and `reinitializeTableControls()`), which flips the direction straight back. `_dsSortResults()` now ignores a second non-forced call within 250 ms (`_dsSortClickAt`). **Not confirmed** as the cause — no browser run. (2) `resetSorting()` now, while deep search is open, calls new `_dsResetSort()`: clears `_dsSort`, restores header arrows, and re-sorts `_dsAll` back to server order using `_dsSeq` (stamped on every result as pages arrive via `_dsSeqNext`); results, search box and the folder's `currentSort` are left alone. **NOT verified** in a browser; `node --check` only. **Second follow-up (same version): checkbox/Size cells jumping to the top of deep-search rows.** Owner report: after sorting / Reset Sort in deep search, the checkbox and Size cells moved to the top of the row (name + path make rows two lines tall) while they had been vertically centred. Cause: `smartTableColumnizer()` -> `_styleRows()` sets INLINE `!important` `vertical-align: top` (and `padding: 11px 0 0 0` on the checkbox cell) on every `tbody tr`, search rows included, and re-runs on every `ResizeObserver` tick of `#tableScrollWrapper`; sorting/resetting shows/hides the Reset Sort button and the sort-info text, which resizes the toolbar and fires a tick, so the already-mounted search rows were restyled after the fact. Fix in `_styleRows()`: rows with class `search-result-row` get `vertical-align: middle` on every cell and `padding: 0` on the checkbox cell; folder/file rows unchanged (`top`). Inferred from reading `_styleRows`; the original look came from CSS I did not have, so if the pre-sort alignment was something other than centred, say so. **NOT verified** in a browser; `node --check` only.

**🆕 2026-10-01 sync note — REAL cause of the short search box and floating icon (CSP, Version 4.49).** `app.py` allows inline `style="..."` attributes only via `style-src-attr` SHA-256 hashes (`_INLINE_STYLE_HASHES`). v4.46 changed the `.search-wrapper` inline style (`position: relative; flex: 1; min-width: 0;`), so its hash was not in the list and the browser dropped it silently. Effects: the wrapper did not grow (input measured 204px while `.search-row` was 844px), and the absolutely positioned icon (and the clear X) lost their `position: relative` anchor, so the icon "floated". The `min-width: 50vw` / `60vw` / `800px` attempts were all treating a symptom. Fix: `.search-wrapper { position: relative; flex: 1; min-width: 0; }` in `index.css`, and the wrapper has NO inline style in `index.html`. RULE: never add or change an inline `style="..."` in index.html/viewer.html/index.js without regenerating the hash list in `app.py`; prefer CSS classes. Verified in headless Chromium with `style-src-attr 'none'`: before the fix input 204px, after ~745px at a 1407px window. Owner must also delete their local `min-width: 50vw !important` if still present.

**🆕 2026-10-01 sync note — search width in vw (Version 4.49, `static/css/index.css` only).** `.search-row` `max-width` is now `60vw` (was 800px) so the box scales with the viewport; `#tableSearch` must NOT carry `min-width: 50vw !important` (it forces the input wider than its row on large screens). The <=480px override (`max-width:100%`) is unchanged. Not verified in a browser.

**🆕 2026-10-01 sync note — search icon removed (Version 4.48, `templates/index.html` only).** With the left padding at 15px the absolutely positioned magnifier overlapped typed text, and the Search button already carries a magnifier, so the floating `<i class="fas fa-search">` in `.search-wrapper` was deleted and the placeholder now reads "Search files and folders (3+ chars for deep search)...". Owner note: their local `index.css` had `#tableSearch { min-width: 50vw !important; }` added as a workaround for a short box; the suspected real cause was stale static CSS served after edits (hard refresh did not help, a server restart did). That line is not in the delivered CSS; `.search-row` `max-width` is 800px. Not verified in a browser.

**🆕 2026-09-30 sync note — search box size/padding (Version 4.47, `static/css/index.css` only).** Owner report after 4.46: text and placeholder did not use the left edge of the field, and the box was too short on desktop. The 45px left padding on `#tableSearch` existed only to clear the absolutely positioned magnifier `<i>` in `index.html`; it is now 15px (owner then confirmed the left-edge issue was fixed). `.search-row` `max-width` raised from 480px to 800px (it is `flex:1`, so it still shrinks with the toolbar). Mobile is untouched. **NOT verified** in a real browser by me; the owner confirmed the padding result and asked for the width change.

**🆕 2026-09-30 sync note — explicit Search button (Version 4.46, `static/js/index.js` + `templates/index.html` + `static/css/index.css`; backend untouched).** Owner report: the search fired by itself whenever typing paused (500 ms debounce on `keyup`), which was annoying. Search now runs only on demand.

**What changed.**
1. `index.html`: the search input is wrapped in a new `div.search-row` together with a new `button#searchBtn` (`data-fn="runSearch"`, class `btn btn-primary search-submit-btn`). The input lost `data-fn-keyup="searchTable"` (so the delegated `keyup` handler no longer fires for it); placeholder unchanged; tooltip now says to press Enter or click Search. The inner `.search-wrapper` lost its `max-width:400px`/`min-width:250px` inline style (the row carries `max-width:480px; min-width:250px` in CSS).
2. `index.js`: new `runSearch()` (reads `#tableSearch`, calls `searchTable`). `searchTable(term)` keeps its name and gating (`*.ext` or 3+ chars -> `performDeepSearch`; 1-2 chars -> `performLocalSearch`; empty -> `hideDeepSearchResults()` + `VT.applyFilter('')`) but the `setTimeout` debounce is gone; it runs immediately. New `_syncClearButton()`. Two document-level listeners: `input` on `#tableSearch` only shows/hides the clear (X) button; `keydown` Enter on `#tableSearch` calls `runSearch()`. Typing never starts a search now; clearing the box by hand also needs Search/Enter (or the X) to reset the list. `searchTimeout` is still declared and cleared but no longer used to schedule anything.
3. `index.css`: `.search-row`, `.search-submit-btn`, and a <=480px override next to the `#tableSearch` block. No inline styles were added for the button.

**Verified:** `node --check index.js`; the real `runSearch`/`searchTable`/`_parseSearchQuery` and both listeners in a Node `vm` sandbox: typing fires no search; Enter and `runSearch()` fire exactly one; `qb` -> local, `qbx` -> deep, `*.pdf` -> deep, empty -> hide + reset; 0 bare-LF lines in the three files. **NOT verified:** layout in a real browser (button height/alignment against the input, the <=480px layout), CSP behaviour, live use.

**🆕 2026-09-30 sync note — highlight bar ROOT CAUSE (Version 4.45, `static/js/index.js` only; `index.css` untouched).** Owner report after 4.44: for 1-2 character terms (now the local current-folder filter) the yellow highlight on `QB Data 2024` was a huge bar (`[Q                    ]` then `B Data 2024` on the next line) while 3+ character deep search looked right. This is the same symptom 4.41 tried to fix with CSS; the CSS was never the whole story.

**Root cause (reproduced in headless Chromium 141 with the real `index.css`, the real `createFileTableRow` markup, and the real `highlightSearchTerm()` + `smartTableColumnizer()` source).** `smartTableColumnizer()` -> `_styleRows()` runs `fn.querySelectorAll('a, span').forEach(el => _set(el, 'display', 'block'); ...)` on every name cell, and `_set()` is `el.style.setProperty(prop, val, 'important')`. That is an INLINE `!important` declaration, which beats every stylesheet rule regardless of selector specificity — so the 4.41 rule `#filesTable td .file-name span.search-highlight { display:inline !important; ... }` cannot win against it. `applyWidths()` re-runs on every `ResizeObserver` tick of `#tableScrollWrapper` and on every window `resize` (a scrollbar appearing/disappearing as the filter changes the row count is enough), so it re-styles the highlight span AFTER `highlightSearchTerm()` created it. Measured: `QB` highlight 23 px wide / `display:inline` before the columnizer ran, 765 px / `display:block` after (200 px at a 400 px viewport). The 4.41/4.42 checks rendered the rows statically and never ran the columnizer afterwards, which is why they passed. Deep-search rows do not go through this path, which is why 3+ characters looked fine.

**Fix.** One selector in `_styleRows()`: `fn.querySelectorAll('a, span:not(.search-highlight)')` (with a comment). The highlight span is never given inline styles now, so the stylesheet rules from 4.41 apply as intended. Nothing else changed: `.fn-text`, the folder `<a>`, and every other span/anchor in the name cell are still styled exactly as before.

**Verified** (Playwright + Chromium 141, real `index.css`, real function source): `qb`, `q`, `QB` x viewport 1400 / 400 x call orders (highlight -> columnizer; columnizer -> highlight; highlight -> columnizer x2 -> re-highlight; columnizer -> highlight -> columnizer x2) = 24 combinations, all with the highlight inline, no inline `style` on the highlight span, 9-23 px wide, and the other name-cell elements still carrying `display:block !important`; before/after screenshots (`QB Data 2024` bar vs `[QB] Data 2024`); `node --check`; 0 bare-LF lines.

**NOT verified.** The live app in a real browser: the test page contained only `index.css` (not `all.min.css`, `video.css`, `viewer.css`, `pdfjs-viewer-overlay.css`, `video-skin-overrides.css`, which were not provided), and I called `smartTableColumnizer()` directly rather than waiting for a real `ResizeObserver` callback (it runs the same `applyWidths()` code). Which exact resize event fires first on the owner's machine is therefore inferred, not observed; the mechanism itself is reproduced. Browsers must load the new `index.js` (hard refresh) to see the fix.

**Correction to earlier notes.** The 4.41 statement that the CSS `#filesTable ... span.search-highlight` rule fixes the wide bar (and the 4.42 render check) was incomplete: it holds only until the columnizer next runs. The CSS rule stays; it is still needed for the un-columnized moments.

**🆕 2026-09-30 sync note — deep search starts at 3+ characters in the UI (Version 4.44, `static/js/index.js` + `templates/index.html`; backend untouched).** Owner report after 4.43: with the backend fixed, typing 1 or 2 characters still showed the deep-search list, because `searchTable()` has always called `performDeepSearch()` for every non-empty query (its own comment said "no local-only shortcut"). Owner decision: 1-2 characters should only filter the current folder; deep search starts at 3+.

**What changed.**
1. `index.js`: new `const _DEEP_SEARCH_MIN_CHARS = 3;` next to `searchTimeout`. `searchTable()` now runs `_parseSearchQuery(term)` and calls `performDeepSearch(term)` only when the term has an `*.ext` filter OR the text part (`query`) is >= 3 characters; otherwise it calls the existing `performLocalSearch(term)`, which also tears down any deep-search list still showing (`hideDeepSearchResults()`) and applies `VT.applyFilter()`. So `q`, `qb` -> current folder only; `qbx` -> deep; `*.pdf` -> deep; `qb *.pdf` -> deep (a 2-char name query WITH an extension still goes deep, and is served by the 4.43 short-query `LIKE` path).
2. `index.js` `performDeepSearch()`: the first-page `fetch` had no stale-response guard (only the later page fetches did). It now captures `const gen = _dsGen` and drops the response in `.then` / `.catch` if `_dsGen` changed. Needed because of (1): otherwise a slow deep response for `qbx` could paint over the local filter after the user backspaced to `qb`. Uses the existing `_dsGen` counter; no `_ds*` function, `VT` code, or windowing logic was modified.
3. `index.html`: placeholder and `title` changed from "2+" / "2 or more" to "3+" / "3 or more".

**Backend behaviour is unchanged:** `/api/search` still accepts and correctly answers 1- and 2-character queries (4.43). The UI just no longer sends them unless an `*.ext` filter is present. If the 1-2 character API calls should be rejected, that would be a separate `app.py` guard (not done).

**Verified:** `node --check index.js`; the real `searchTable()`, `_parseSearchQuery()` and `performDeepSearch()` source run in a Node `vm` sandbox with stubbed neighbours: `q`, `qb`, `qb ` (trailing space), `  a  ` -> local filter only, no fetch; `qbx`, `QB Data`, `*.pdf`, `qb *.pdf` -> exactly one `/api/search` fetch and no local call; empty -> `hideDeepSearchResults()` + `VT.applyFilter('')`; race test (deep fetch in flight, then a 2-char term) -> stale response NOT displayed; control (no switch) -> response displayed. CRLF intact (0 bare-LF lines) in both files; diff limited to the lines above.

**NOT verified:** a real browser (the toast/list/scroll behaviour on a live page, backspacing from a deep-search list down to 2 characters visually), and the `VT` filter rendering on a very large folder for 1-2 character terms (this path already existed and is unchanged).

**🆕 2026-09-30 sync note — 2-character deep search fixed (Version 4.43, `search_index.py` only; `app.py`, `index.js`, `index.html` untouched).** Resolves the 4.42 "Still open (backend)" item below.

**Root cause (reproduced with the real `search_index.py`, not just read).** The `files` FTS5 table is created with `tokenize='trigram'`. A trigram index stores 3-character grams, so `MATCH` can never return a row for a query of 1 or 2 characters — it does not error, it silently returns nothing. `_db_search()` sent every name query to `MATCH`, while `count()` (which uses `LIKE` on `files_meta`) had no such limit. So the API answered `total_count: 5999, results: []` for `qb`. It was hypothesis 1 of the handover; there is no minimum-length guard in `/api/search` or the query builder (hypothesis 2 was wrong), and the query is a quoted phrase MATCH, so token-boundary matching (hypothesis 3) is not the issue for 3+ characters.

**What changed (`search_index.py` only).**
1. New `_FTS_MIN_QUERY_LEN = 3` and helper `_like_contains(q)` (escapes `\`, `%`, `_`; callers must add `ESCAPE '\'`).
2. `_db_search()`: `use_fts_path = _use_fts and (no name query or len(query) >= 3)`. Anything else goes through the existing plain-table branch — `SELECT rel_path, is_dir FROM files_meta WHERE name_lower LIKE ? ESCAPE '\' [AND ext_lower IN (...) AND is_dir = 0] LIMIT ? OFFSET ?`. Fully parameterised, `LIMIT`/`OFFSET` in SQL, `limit+1` fetch for `has_more`, same result-row construction, same response shape. Ext-only queries still use Strategy C; 3+ character queries still use the FTS paths (A/B) unchanged.
3. `count()` (and the plain-table branch) now use the escaped pattern. Before, a query containing `%` or `_` was treated as a wildcard by `count()` but as a literal by the FTS `MATCH`, so the total disagreed with the rows (test: `a_b` count 2 vs 1 row; `100%` count 16 vs 1 row). Now both are 1.

**Minimum length — decision (UI part SUPERSEDED in 4.44: the frontend now only starts deep search at 3+ characters; the API/backend behaviour described here is unchanged).** No new minimum was added to the backend. The frontend already sends any non-empty query to `/api/search`, and `count()` and `_walk_fallback()` already accepted 1 character, so 1-character queries now return results too (the `q` test returned 8,426 hits). The `index.html` placeholder/title still say "2+ chars"; that text is now conservative, not wrong. If 1-char should be blocked, add the guard in `search_files()` in `app.py` (not done).

**Permissions.** `/api/search` is `@login_required` only and does no per-user path filtering; results come straight from the index. That is unchanged — the fix adds no new path source and removes none.

**Index rebuild: NOT needed.** `files_meta` already holds `name_lower` + `idx_meta_name_lower` on every existing install, and the FTS table is untouched. Restart (or hot-reload) the server and it works; rebuilding via the web UI is unrelated (`/admin/rebuild_cache` rebuilds `storage_index.json`/`file_index.json`, not `search_index.db`).

**Verified** (real `search_index.py` + real crawler, SQLite 3.45.1, a 20,405-file / 2,117-folder tree modelled on `QB Data 2024`; before/after harness, same queries): `qb` returned 0 rows (count 5,999) before and 500 rows + `has_more` after; paging all 12 pages returned exactly 5,999 rows, no duplicates, every row's name contains `qb`, folders included, depth-4 paths included; `QB`/`Qb` give identical results (case-insensitive); `qb`+`ext=pdf` 2,448 = count; `qb`+`ext=qbw` 1,696 = count; nine 3+ character queries (`qbw`, `invoice`, `quickbooks`, `scan`+pdf, `client 08`, `memo_1`+docx, `qb d`, `batch 4`, `year1`) returned byte-identical result lists in identical order before vs after. Scale test, 1,500,000 rows (610 MB DB): `qb` search 11 ms, offset 10,000 24 ms, `ext=pdf` 59 ms, zero-hit worst case 137 ms (full `SCAN files_meta`, the same scan `count()` already did); `count('qb')` on that set ~280 ms including the first page. `py_compile` clean; 0 bare-LF lines in the edited file.

**NOT verified.** The HTTP route through a running Quart/Hypercorn server, the browser UI (toast gone, windowed list), the owner's real `search_index.db`, Windows/Termux-specific SQLite builds, and the non-FTS ("LIKE table") mode end to end (it shares the same branch, which is now exercised by short queries, but a DB created without trigram support was not built).

**Observed, not changed.** (a) FTS `MATCH` on the `files` table searches ALL its columns (`name`, `rel_path`, `is_dir`, `parent_rel`), so a 3+ character query also returns every entry whose *path* contains the text (`quickbooks`: `count` = 1, but 10,801 rows come back). Short queries use `name_lower` only, so they match names only — consistent with `count()` but not with what 3+ character search returns. (b) `count()` contains an unreachable second `try:` block after its `return`; harmless, left alone.

**🆕 2026-09-30 sync note — search follow-up (Version 4.42, `static/js/index.js` only; owner confirmed deep search with 3+ chars is now fine).** Two things remained for a 2-character query such as `qb`:
1. **Highlight in FILE rows (found by rendering the real `index.css` in headless Chromium, which jsdom cannot do).** `.file-name` is `display:flex` and a file row's name is a BARE text node inside it, so a highlight `<span>` became its own flex item: the name split into separate items (gap around the match, `Q`/`B` stacked vertically in narrow columns). Folder rows were unaffected because the name lives inside an `<a>`. `highlightSearchTerm()` now first wraps bare name text nodes of `.file-name` in one `<span class="fn-text">` (a single flex item, styled by the existing `.file-name span` rules like the folder `<a>`), then highlights inside it. Idempotent; the icon `<i>` and the eye `<button>` are untouched. **Rule: never insert a highlight (or any element) as a direct child of `.file-name` between name text and siblings.**
2. **Misleading toast.** `displayDeepSearchResults()` used to show `No results found for "qb"` and THEN run the local-filter fallback, which could show a real hit. It now runs `performLocalSearch()` first, reads `#visibleCount`, and shows either `No matches in subfolders for "qb" - showing N in this folder` or (only when the local filter is also empty) `No results found`.
**Was open at 4.42 (backend) — RESOLVED in 4.43, see the sync note above:** the `/api/search` call for a 2-character query returns zero results although the UI text promises "2+ chars for deep search" (search input placeholder/title in `index.html`) and the folder `QB Data 2024` contains 28,138 files. Suspect `search_index.py` (FTS5; e.g. a trigram tokenizer or a minimum-length rule) and/or the `/api/search` handler in `app.py`. Needs those two files to confirm.

**🆕 2026-09-30 sync note — search highlight fixes (Version 4.41, `static/js/index.js` + `static/css/index.css`).** Reported with screenshots: (a) normal/non-deep search for `qb` showed the folder "QB Data 2024" with a full-width yellow bar over `QB` and the rest of the name pushed onto a second line; (b) deep search for `are` rendered "Software Services" as "Soft are Services" (visible gaps either side of the highlight). Root causes, all in the highlight path only — the VT/deep-search windowing engines were not touched:
1. **CSS (both symptoms).** `.search-highlight` had `padding: 2px 4px; font-weight: bold`. Horizontal padding and the wider bold glyphs open a gap around a mid-word match. Now `padding: 0; font-weight: inherit; display: inline`.
2. **CSS (wide bar, normal search only).** `index.css` has many `.file-name span { display:block; width:100% }` rules (the wrap/mobile blocks, several `!important`), and the highlight `<span>` is a `span` inside `.file-name`, so it was stretched to the cell width. New override `#filesTable td .file-name span.search-highlight` (id selector so it beats all of them, all `!important`) forces `display:inline; width:auto`. Deep-search results are NOT inside `.file-name` (they use `.search-result-title`), which is why they only showed the gap problem, not the bar. **[INCOMPLETE — see the 4.45 note: `smartTableColumnizer()` re-applied inline `!important` `display:block` to the highlight span after any resize, beating this rule; fixed in `index.js` in 4.45.]**
3. **`highlightSearchTerm(row, term)` (normal search) rewritten.** It used to build the regex from the raw term (a query like `c++` or `(` threw) and, for file rows, replaced `.file-name`'s whole `innerHTML` — deleting the row's icon `<i>` and the preview (eye) button. It now walks the cell's TEXT NODES with a `TreeWalker` (skipping anything inside a `<button>`), wraps matches in `span.search-highlight` via a fragment, escapes the term, and is idempotent (unwraps earlier highlights first). `dataset.originalText` is no longer used.
4. **`highlightText(text, term)` (deep search) now takes RAW text and escapes per piece.** Before, callers passed `escapeHtml(name)` and the regex ran over the escaped string, so a query like `amp`, `lt`, `quot` or `39` matched inside `&amp;` / `&lt;` / `&#039;` and produced broken markup. The two callers in `createSearchResultRow()` now pass `result.name`. **Rule: never pre-escape text before handing it to `highlightText()`; it escapes itself.**
Verified: `node --check`; jsdom test (folder row and file row keep icon + eye button, double highlight does not nest, `amp` / `c++` / `&` queries produce valid HTML). **Not verified:** real-browser rendering — jsdom has no layout engine, so the bar/gap fix (pure CSS) still needs a look in the browser. Rules for future edits: keep highlights as inline spans with no horizontal padding; do not put `display:block`/`width` on `.search-highlight`; do not rewrite `.file-name` `innerHTML` for highlighting.

**🆕 2026-09-30 sync note — deep search is now windowed (Version 4.40, `static/js/index.js` + `static/css/index.css`).** Audit result first: the file table's normal/local search (`VT.applyFilter()` -> `_renderAll()`) already goes through the VT row-windowing engine (4.31/4.34), so it only ever mounts viewport +/- `RENDER_BUFFER` rows — no change needed there. **Deep search did not**: `_dsAdvance()` appended 80-row chunks to the `<tbody>` behind an `IntersectionObserver` sentinel and nothing ever removed a row, so a broad query (tens of thousands of hits) grew the DOM without bound — the same append-only design VT had before 4.31, and the cause of the slow/crashing page. Note `searchTable()` sends *every* non-empty query to deep search, so this was the path normal typing hit. Fix: deep search now has its own windowing engine (the `_ds*` block), modelled on VT: the full result list lives in `_dsAll` (data only), the server is still paged at `_DS_LIMIT = 500` per call but the next page is now pulled by scroll position (`_DS_PREFETCH_ROWS = 40` from the loaded end) instead of by a sentinel, and only rows in the viewport +/- `_DS_RENDER_BUFFER = 7` are mounted between two spacer rows (`#dsTopSpacer`/`#dsBottomSpacer`, classes `vt-spacer-row ds-spacer-row`, the height on the spacer `<td>` via `style.setProperty(..,'important')`). Row height is not fixed (long names and long paths wrap) so there is a per-path height cache seeded at `_DS_DEFAULT_ROW_HEIGHT = 56` and corrected by a batched rAF measure pass, exactly as VT does. **The VT rules still apply here:** no `style=""` attribute in any markup this code builds (the loading row's old inline styles moved to `.ds-loading-row` rules in `index.css`), no JS `scrollTop` compensation (only the one explicit `scrollTop = 0` when a new search starts, mirroring `navigateToFolder()`), never `overflow-anchor:none` on `#tableScrollWrapper`. **Selection consequences (the part that was DOM-derived and had to change):** with only ~25 result rows mounted, anything that counted or walked `.search-result-row` was wrong. `toggleSelectAll()` in deep-search mode now selects every *loaded* result from `_dsAll` (not the mounted rows, and not every result the server has — pages not yet fetched are not selected); `updateSelection()`'s total is `_dsAll.length`; `_dsCreateRow()` re-applies the checked state from `selectedItems` when a row scrolls back in; single and bulk delete now call `_dsRemoveResults(paths)`, which filters the data array, decrements `_dsTotal`, re-mounts the window and rewrites the header count (removing a `<tr>` alone would leave the data array stale). Teardown (`hideDeepSearchResults()`) bumps `_dsGen`, which also invalidates any in-flight page fetch and queued measure pass. Also fixed in passing: `highlightText()` built `new RegExp(searchTerm)` from raw user input, so a query such as `c++` or `(` threw a SyntaxError while rendering results; the term is now regex-escaped. Removed as dead: `_DS_CHUNK`, `_dsResults`, `_dsRendered`, `_dsObserver`, `_dsAttachSentinel`, `_dsAdvance`, `_dsRemoveSentinel`, `_dsDisconnectObserver`. **Verified:** `node --check`; a Node + jsdom harness that runs the real extracted `_ds*` code against a mocked `/api/search` serving 50,000 results in 500-row pages — DOM stayed at ~26 result rows (28 `<tr>` including spacers) through a full sweep and through loading all 100 pages, select-all reached 50,000, `_dsRemoveResults` kept data/count/DOM consistent, `highlightText('c++ file','c++')` no longer throws. **Not verified:** a real browser (jsdom has no layout engine, so row wrapping, real measured heights, native scroll anchoring and scroll feel are untested — same caveat as VT 4.31, which is where the rubber-band bug hid), Safari/touch, and the backend (`/api/search` was not provided; `has_more`/`total_count` behaviour is taken from the existing client code). Hard-refresh (Ctrl+F5) after deploying — `index.js` has no cache-busting query string.

**🆕 2026-09-30 sync note — manage.sh port sweep fix (Version 4.39).** Resolves the 4.38 "observed, not changed" item. `manage.sh` `_kill_webdav_child` swept a hard-coded `8080 8443` although its comments said it followed the configured ports. New helper `_webdav_ports()` reads `WEBDAV_PORT` / `WEBDAV_HTTPS_PORT` from `server_config.json` (read directly with Python's `json`, not by importing `config.py`, because importing it runs `load_server_config()` and prints) and falls back per port to 8080/8443 on any problem, so it cannot break `stop`/`start`/`restart`. `bash -n` passes and the helper was tested standalone under `set -euo pipefail` with custom ports, a non-numeric value, invalid JSON, no file and no Python. **Known limit:** a port changed only by editing the constant in `config.py`, never saved to `server_config.json`, is not seen (the PID-file kill still works). The comments that cited `protocol_manager.py`'s `_webdav_target_ports()` were reworded because that file was not available to check. Docs: `MANAGE_SCRIPT_GUIDE.md` port-sweep section rewritten, new "Startup messages are not shown in background mode" section, `approve` default (`--max-downloads 1`) and `--passkey` behaviour added (checked against `revoke_sharing.py`; `version_manage.py` subcommands also match); README manage.sh section gets the same background-mode note. `version-manage` / `revoke-shares` lists in the guide now verified against the scripts. **Not verified:** the sweep on a live system with non-default ports. See [Version 4.39](#version-439--2026-09-30-managesh-webdav-port-sweep-follows-server_configjson-docs-only-for-everything-else).

**🆕 2026-09-30 sync note — new manage.sh guide (Version 4.38, docs only).** Added `docs/MANAGE_SCRIPT_GUIDE.md`, written from a full read of `manage.sh` (all commands, the 20-item menu, log/PID paths, detached launch and Ctrl-C handling, WebDAV cleanup, `security-txt` flags, `PYTHON` override, Windows/Linux/Termux differences). README's manage.sh section had stale facts, now fixed against the script: Waitress/Flask → Hypercorn/Quart, non-existent `create-user`/`create_user.py` → `manage-users`/`manage_users.py`, `bash update_pymodules.sh` → `setup_pymodules.sh` (or `./manage.sh update-modules`), "menu > 17" for security.txt → 19, platform line now Windows (Git Bash)/Linux/Termux (macOS was claimed but nothing in the script handles it specially). README Deployment Guides table links the new guide. **Observed, not changed (code):** `_kill_webdav_child` sweeps the fixed ports 8080/8443 even though its comment says it follows `WEBDAV_PORT`/`WEBDAV_HTTPS_PORT`; the subcommand lists for `version-manage` and `revoke-shares` are copied from `manage.sh`'s help text, the underlying `.py` scripts were not read; nothing was run on a live system. See [Version 4.38](#version-438--2026-09-30-managesh-guide-and-readme-managesh-section-fixes-docs-only).

**🆕 2026-09-30 sync note — text-only code fixes + README table (Version 4.37).** Resolves items (1) and (2) that 4.36 found and left alone. `webdav_server.py` `start()`: the HTTPS startup `print()` no longer says the cert must be imported "manually (or serve it yourself)" or that the plaintext listener "used to host it"; it now points at `https://{LOCAL_IP}:{https_port}/webdav.crt` (trust-on-first-use), matching `_CertMiddleware`. `config.py`: the SMB comment (~line 94) and the `_configure_smb()` prompt (~line 2411) now say `./manage.sh setup-smb` (checked against `manage.sh`: help text, dispatcher and menu #11) alongside `python smb_setup.py`. No logic, ports, auth or config values changed; both files pass `py_compile` (line endings stay CRLF) but the server was **not** restarted to see the new message. `README.md`: the Deployment Guides table now also lists `SMB_PROTOCOL_DEPLOYMENT.md` and `USER_GUIDE.md`. **Still open:** (3) README's `cheroot` package-table row — `manage.sh` only calls `setup_pymodules.sh`, which generates `requirements.txt`, so it still needs that file to verify; (4) live checks of `/webdav.crt` on `:8443`, `curl.exe -k` and the rclone `no_check_certificate` form. See [Version 4.37](#version-437--2026-09-30-console-and-comment-text-fixes-readme-deployment-guides-table-no-logic-changes).

**🆕 2026-09-30 sync note — docs only, no code changed (Version 4.36).** Six docs (`README.md`, `RCLONE_DEPLOYMENT.md`, `USER_GUIDE.md`, `SETUP_TUNNEL_ADVANCED.md`, `SMB_PROTOCOL_DEPLOYMENT.md`, `CONFIG_PY_REFERENCE.md`) were swept for examples that assumed plain-HTTP WebDAV on `:8080` is on by default; they now lead with HTTPS `:8443` and describe `:8080` as an off-by-default fallback. Checked against `config.py` (`WEBDAV_ENABLED=False`, `WEBDAV_HTTPS_ENABLED=True`, ports 8080/8443), `webdav_server.py` `start()` (HTTPS wins exclusively; `:8080` only when HTTPS is off or the cert can't be prepared), `ssl_cert.py` (cert at `db/webdav.crt`, trust-import commands, `--regenerate`) and `app.py` (session lifetime is read from `config.py`). **Certificate download:** `_CertMiddleware` wraps the WSGI app that `_start_hypercorn()` hands to both the TLS bind and the plain bind, so by code reading `GET /webdav.crt` is answered unauthenticated on `https://HOST:8443/webdav.crt` on a default install — the old `http://HOST:8080/webdav.crt` URL only exists if the plaintext listener is up. *Not exercised against a live server.* The docs now offer copying `db/webdav.crt` by hand first and `curl.exe -k` against `:8443` as the alternative (the cert isn't trusted yet, so that download is trust-on-first-use). **Found, deliberately not changed (code):** (1) `webdav_server.py` `start()` prints that the cert must be imported "manually (or serve it yourself)" because the plaintext listener "used to host it" — contradicts the middleware above; (2) `config.py`'s SMB comment and `_configure_smb()` prompt still say `./manage.sh smb-setup`, but `manage.sh`'s command is `setup-smb` (menu #11, see the menu map) — the docs now just say `python smb_setup.py`; (3) README's package table still lists `cheroot` as enabling WebDAV HTTPS, but `webdav_server.py`'s docstring says the waitress/cheroot setup was replaced by Hypercorn (needs `hypercorn` + `asgiref`, plus `cryptography` for the cert) — `requirements`/`setup_pymodules.sh` weren't part of this pass, so the install line was left alone. See [Version 4.36](#version-436--2026-09-30-webdav-https-by-default-documentation-sweep-docs-only).

**🆕 2026-09-29 sync note, part 8 — VT rubber-band: the real root cause (`index.js` + `index.css`). READ THIS BEFORE TOUCHING VT, and treat the CSP explanation in the 4.32/4.33 material below as WRONG.**

**What was wrong with the earlier diagnosis.** 4.33 claimed `tr.style.height = …` / `style.setProperty(…)` are blocked by `style-src-attr`. They are not: CSSOM writes (`el.style.x = …`, `setProperty`, `insertRule`) are exempt from `style-src-attr` — `app.py`'s own comment above `_INLINE_STYLE_HASHES` (~line 428) says exactly this. The **only** CSP violation in the user's console log was `index.js:1853` in `_makeSpacerRow`: the *static* `style="padding:0;border:0;line-height:0;"` **attribute inside `innerHTML` markup**. Its SHA-256 (`sha256-eKl14Djyh3JtfQn39JMfdSzFqFTCspxUul6VSqVnxKU=`, the hash Chrome asked for) was computed and matches that exact string; it was never in `app.py`'s allow-list, so the spacer `<td>` kept default `6px 8px` padding. That is what the user's diagnostic `vtTopSpacer.getBoundingClientRect().height === 21` was measuring — default cell padding, **not** proof the spacer fix worked. The `--table-thead-h` thread (`_updateTheadHeightVar`) is likewise a CSSOM write, not CSP-blocked, and only feeds the sticky `top` of the `..` row; it never touched scroll math.

**The real cause.** `index.css` ("AUTHORITATIVE TABLE ROW / ACTION BUTTON OVERRIDES", near the end of the file) sets `.file-table .table tbody tr, #filesTable tbody tr { height:auto !important; min-height:0 !important; max-height:none !important }`. `!important` beats every non-important way of giving the spacer `<tr>` a height — inline style, CSSOM `style.height`, or an inserted CSSOM rule (4.33's approach). Confirmed in real Chromium: the inserted rule read `#vtBottomSpacer{height:11067px}` while `getComputedStyle(...).height` was `13px`. So the spacers stayed ~13–21px, a 250-row folder had `scrollHeight` ≈ 2035px instead of ≈ 14,000px, and the wrapper's scroll range was only the ~35 mounted rows. Scrolling past that range snapped back: the rubber band. (The 4.32 `scrollTop` save/restore was a genuine but minor bug; it restored *before* the spacers had height, so it was clamped straight back.)

**Fix (`index.js` VT + `index.css`).**
- Spacer height lives on the spacer's **`<td class="vt-spacer-cell">`**, written with `style.setProperty('height', px, 'important')` (CSSOM). The `!important` row rule doesn't apply to cells. `_ensureSpacerRules()` and the inserted-rule approach are **deleted**. The spacer zeroing (`padding/border/line-height`) is now CSS (`.vt-spacer-row`, `.vt-spacer-cell` in `index.css`), **not** an inline attribute — do not put a `style="…"` attribute back in VT markup.
- `_listBase`: offsets are relative to the list, `wrapper.scrollTop` is relative to the whole scrollable content (sticky thead + optional `..` row above). `_measureListBase()` reads it; `_renderWindow`, `scrollToItem`, `_onResize` all add it.
- `_renderAll()` mounts the window for the *preserved* scroll position (`_renderWindow(true, preservedScrollTop)`), which sizes the spacers, **then** restores `scrollTop`.
- `_mountRange()` is now two-phase and incremental: create missing rows first (`createFileTableRow` → `applyColumnWidths` reads `wrapper.clientWidth`, so it must run against an untouched DOM), then remove off-window rows and insert only nodes not already in place. The old code detached and re-inserted every mounted row through a fragment on every window change.
- `_scheduleMeasure()` compares against what the offsets *currently assume* (not just the cache) and rebuilds only on a real disagreement; `_onResize()` remembers *which row* is at the top and the offset into it, not a pixel scrollTop, because pixel offsets are estimates again after the height cache is cleared.
- **Scroll anchoring is native, on purpose.** `#tableScrollWrapper { overflow-anchor:auto }` (explicit, commented). A manual variant that compensated with `wrapper.scrollTop += delta` was built and measured: those JS writes collide with Chrome's in-flight wheel smooth-scroll and produced visible reversals (a lost 14px, or a whole 120px wheel step) in 4–6 frames per run; dropping them and letting the browser anchor gave 0. **Do not reintroduce `scrollTop` compensation, and do not set `overflow-anchor:none`.**
- New public `VT.rowResized(tr)`, called from `loadDirInfoCells()` right after a folder's size cell is rewritten. That cell starts as a one-line spinner and becomes `"N files, N folders<br>size"` (≈54px) after an async `/api/dir_info` fetch, i.e. the row grows *after* it was measured; without this the cached height stays stale.

**Verified in a real browser** (this is the first VT verification that was; jsdom cannot see any of this): Chromium (`@sparticuz/chromium` from npm + `puppeteer-core`, headless) loading the real `index.html` (rendered with jinja2, 250 synthetic items, long wrapping names), the real `index.css`/`index.js`, and a CSP header with `style-src-attr` hashes built from the static style strings. Wheel-scrolled down 40 steps then back up 40. Metric: a *row that persists across frames must only move in the direction of the scroll* (any reversal > 1px = visible jump). **Original: 29–32 reversal frames per run, worst −240px, ends at `scrollTop=0`, `scrollHeight≈2100`. Final: 0–1 frames** (the one recurring 120px frame was traced to frame index = the first frame after the test flipped its own down→up phase flag, i.e. the last down wheel step still finishing — a metric artifact), `scrollHeight≈14–16k`, 0 CSP violations. Also passed: no blank gap anywhere across a 40-point sweep including the very bottom, refresh (`VT.init`) keeps `scrollTop`, `scrollToItem` lands the row in view, filter and sort correct. Tested with 12 and with 120 folder rows (async `dir_info`, 150–550ms). The harness itself is a dev-only script outside the repo (not shipped).

**Lag — separate from VT, NOT fixed.** In the same headless (software-rendered) browser, disabling `backdrop-filter` and the glow animation dropped median frame time ≈49ms → ≈19ms and p95 ≈1000ms → ≈267ms. `.file-table` has `backdrop-filter: blur(10px)` over a scrolling table sitting on the animated `body::before/::after` layers; that blur re-renders as rows move. Software rendering exaggerates the cost, so a real GPU will differ, but it is the prime suspect for "laggy at ~250 files". Removing/limiting the blur on `.table-scroll-wrapper` is the recommended next step (a visual change, so left for the owner to decide). Also suspected, **not measured**: `updateDocHeight()`'s `MutationObserver` on `document.body` (`subtree:true`) fires on every row mount/unmount and reads `offsetTop/offsetHeight` (forced layout).

**Not verified / caveats.** Safari (as far as known, no `overflow-anchor` support — above-viewport estimate corrections would not be compensated there, so expect small shifts when scrolling *up* over never-measured rows; untested), Firefox, touch/inertial scrolling, real GPU, and a folder with thousands of entries in a real browser (only 250 rows were run). Hard-refresh (Ctrl+F5) after deploying — `index.js`/`index.css` have no cache-busting query string. **Design note for the owner:** the only reason VT needs any of this is that long filenames wrap, so row heights are non-uniform. Single-line rows (`text-overflow:ellipsis` + `title` tooltip) would let row height be measured once, exactly like Clusterize.js, and would remove the estimate/correct machinery entirely; that is a product decision and was not tested.

**VT tunables — owner-set values (2026-09-29).** The three constants at the top of the `VT` module in `static/js/index.js` are deliberately set by the owner and differ from the defaults described in the part-7 note/4.31 below: `RENDER_BUFFER = 12` (rows kept mounted above/below the viewport; 4.31 described 18), `DEFAULT_ROW_HEIGHT = 96` (px seed estimate for never-measured rows, replaced by the first real row measurement in `_scheduleMeasure`; keep it near the real row height so the first render mounts about the right number of rows — a tiny value briefly over-mounts, a huge one under-mounts until the next frame), `RESIZE_DEBOUNCE_MS = 150` (ms; 150 is the default debounce, so a window drag re-measures once the resize settles rather than on every event). Do not "restore" these to the 4.31 numbers. If blank flashes appear at the table edge during fast wheel/touch flings, `RENDER_BUFFER` is the knob.

**🆕 2026-09-28 sync note, part 7 — VT row windowing (virtual scroll rewrite), `static/js/index.js` only.**

The file table's `VT` module (`static/js/index.js`, was ~line 1626) rendered via append-only infinite scroll: an `IntersectionObserver` sentinel appended 80-row `CHUNK`s and never removed a row, so a folder with thousands of entries grew the DOM without bound and every batch re-ran `loadDirInfoCells()`/`_highlightVisible()` over **every** rendered row (quadratic total work as the folder got scrolled through). Rewritten to true row windowing: only rows in the viewport ± a row buffer (`RENDER_BUFFER`; 18 in 4.31, now owner-set to 7 — see the part-8 note) are ever mounted; two spacer `<tr>`s (`#vtTopSpacer`/`#vtBottomSpacer`) stand in for everything else, sized from a cumulative offset array so the scrollbar behaves like the full list is present. **Row height is not hardcoded** — `index.css`'s `.name-cell { white-space: normal; word-break: break-word; }` (present on both the desktop and mobile breakpoints) means long filenames wrap and rows are **not** uniform height, so a naive `scrollTop / fixedRowHeight` index calculation would drift. Fix: a per-path height cache (`Map<path, px>`, survives sort/filter/refresh since it's keyed by item path, not row index) seeded from a live measurement of the first real row and corrected as more rows are measured; the cumulative offset array (`Float64Array`) is only rebuilt (O(n), a plain loop — cheap even at 50k rows) when a measurement actually disagrees with what was assumed, so a folder where every row is one line costs exactly one measurement pass, ever. Scrolling is rAF-throttled; already-mounted row nodes are moved (not destroyed/recreated) via a single `DocumentFragment` + `insertBefore` per window change — batched writes, no interleaved read/write layout thrash. `loadDirInfoCells()` and the (now-private) row highlighter take an explicit `rows` array scoped to just what was freshly mounted this pass, instead of scanning the whole table; folder-size responses still populate the shared `_dirInfoCache` even if the row has since scrolled out (so re-scrolling back is an instant cache hit), but a DOM write is skipped via `cell.isConnected` if the row was recycled before the fetch resolved. Selection (`selectedItems`), `_dirInfoCache`, and `_deletingPaths` were already plain-data `Set`/`Map`s, not DOM-derived, so they needed no changes; select-all already iterated `VT.getAll()` (the full data array), not rendered rows. **(Update 4.40: deep search, which this note treats as a separate already-paginated system, was itself append-only and is now windowed — see the 2026-09-30 deep-search sync note at the top.)** **Grepped every DOM row consumer in the file** for the "will break under windowing" pattern described in the task: found and fixed one real bug — `bulkDownload()`'s single-item download path detected file-vs-folder by querying `tr[data-path="..."]` in the DOM, which silently returns null (mis-detecting a folder as a file) once that row is no longer mounted; now checks `VT.getAll()` first, falling back to the DOM query only for a path VT doesn't know about (a deep-search result row, which is a separate, already-paginated system, untouched here). New `VT.scrollToItem(path)` public method (binary-searches the offset array, sets `wrapper.scrollTop`, forces a window re-render) — wired into `performRename()`'s success path so a rename result is scrolled into view even if the item moved far from its old position under the active sort; not yet wired into the upload-completion path (flagged as a natural follow-up, not done here to avoid touching the multi-file upload queue code under this change). No changes to `init()`, `applySort()`, `applyFilter()`, `_getDisplayFiles()`, `storeOriginalTableOrder()`, `updateVisibleCount()`, `reinitializeTableControls()`, or the `..` parent-directory row's markup/stickiness — all kept byte-for-byte where their logic wasn't the point of the change. **Correction (2026-09-29, two rounds):** the claim below that VT "never touches `wrapper.scrollTop` on its own" was wrong in practice — `_renderAll()`'s `tbody.innerHTML = ''` collapses the wrapper's scrollable height, and the browser clamps `scrollTop` to 0 as an implicit side effect of that, so every refresh (SSE, polling, sort, filter, rename, not just real navigation) was silently snapping the view back to the top mid-scroll (reported as a "rubber band" bug). Fixed in [Version 4.32](#version-432--2026-09-29-vt-scroll-position-rubber-band-fix): `_renderAll()` now captures `wrapper.scrollTop` before the clear and restores it once the spacers give the wrapper its real height back; `navigateToFolder()`'s own explicit `scrollTop = 0` on real navigation still overrides this, unchanged. A second, almost certainly bigger contributor to the same symptom was found from real-browser console logs the same day: the spacer `<tr>`s' dynamic height was being set via `tr.style.height = ...`, which this app's CSP silently blocks (`style-src-attr`'s precomputed hash allowlist can only ever match a fixed, known set of literal style strings — never an arbitrary/changing px value) — meaning the spacers never actually got their real height in any real browser at all, so the wrapper's true scrollable area was far smaller than the windowing math assumed. Fixed in [Version 4.33](#version-433--2026-09-29-vt-spacer-height-csp-fix): spacer height is now applied via CSSOM rules inserted into the already-CSP-permitted external stylesheet, never via an element's `style` attribute. Neither of these was catchable by the jsdom harness below — jsdom enforces no CSP and has no real layout engine, so it can neither clamp scroll height nor block an inline style. **Verified** with a Node + jsdom harness (`vt_test_harness.js`, not shipped — a dev-only test script) driving the actual extracted `VT`/`createFileTableRow`/`loadDirInfoCells` source against a synthetic 50,000-entry folder: DOM node count stays in the low hundreds regardless of scroll position (vs. growing to 50,000 previously); per-scroll-step cost measured flat across a 25× increase in folder size (2.76× slower, not ~25×), confirming O(window) instead of O(n); sort/filter/select-all/range-select/delete-selected/rename+scrollToItem/deep-search-mode handoff/tiny-folder/empty-folder all pass. **Caveat**: jsdom has no real layout engine, so actual text-wrapping and jsdom's own absolute timings aren't representative of a real browser — `getBoundingClientRect()` was monkey-patched to simulate variable row heights for the height-cache code path, and the harness's own conclusion is about *relative* scaling (flat vs. linear), not real frame-rate numbers. **Not yet verified in a real browser** — sanity-check scrolling on an actual large folder (ideally with some long, wrapping filenames) before considering this fully shipped, and hard-refresh (Ctrl+F5) after deploying since `index.js` has no cache-busting query string. See [Version 4.31](#version-431--2026-09-28-vt-row-windowing-virtual-scroll).



Root cause of the UI half of the double-click bug: `restoreVersionAction()` only set `restoreBtn.disabled = true` on the *DOM element*, and `_paintVersionHistory()` rebuilds the rows via `innerHTML`, so any repaint (or reopening the modal) silently produced a fresh **enabled** button mid-restore. Fix: in-flight state now lives in module-level Sets **outside the DOM**: `_vhRestoring` / `_vhDownloading` (keys `"path::versionId"`), and `_versionHistoryRowTemplate()` renders the button from them via `_vhIsRestoring()` — disabled + `aria-busy` + spinner + "Restoring…". `_vhIsRestoring()` is also true when the server's `restoring` list (from `/api/versions/list`) contains the version, so another tab/user's restore shows as busy too. `restoreVersionAction()` ignores clicks while its key is in the Set; on **HTTP 409 `in_progress`** it stays in the loading state, polls `/api/versions/list` every 1.5 s (max 10 min, `_vhWaitForRestoreToFinish`) until the server no longer lists it, then calls restore once more (the server's fast path returns the finished file instantly and the normal success toast/download follows); a `finally` always clears the key and repaints via `_vhRepaintIfOpen()` (only if the modal still shows that file). `downloadVersionAction()` locks its button ("Starting…") for 3 s to stop double-click starting two downloads (the navigation itself is unchanged; the server now streams immediately). No CSS/HTML changes (uses existing `.btn:disabled` and `fa-spinner fa-spin`). **Verified**: `node --check` syntax + a Node `vm` simulation of the real functions (3 rapid clicks → 1 request; 409 → waits → single follow-up → success; lock cleared). **Not verified in a real browser** — hard-refresh (Ctrl+F5) after deploying, since `index.js` is served with no cache-busting query string.

**🆕 2026-09-28 sync note, part 5 — Restore double-click WinError 32 + slow Version History download** (`version_history.py`, `version_engine.py`, `app.py`).

**Restore.** `Engine.restore_version()` rebuilt into a **fixed** `<destination>.tmp`, so two overlapping restores of the same version (fast double-click) both opened/removed/renamed the same temp file and the destination → `[WinError 32]`. Fixes: (1) **in-flight guard** — `version_history.restore()` keeps a `_inflight` set keyed `(norm_path, version_id)`; a second request for the same version returns `IN_PROGRESS_MSG` immediately, and `POST /api/versions/restore` maps that to **HTTP 409 `{"in_progress": true}`** (not an error — the UI should keep the row in its loading state). (2) **Fast path** — if the `.recovered/` destination already exists with the right size it is returned without rebuilding (safe: the name is unique per file+version and the engine only publishes it by atomic rename *after* sha256+size verification). (3) **Unique temp** — `tempfile.mkstemp(dir=dest_dir, prefix=".restore_", suffix=".tmp")`. (4) `os.replace()` retried on `PermissionError`, then a clean `VersionEngineError`. (5) `_create_job`/`_finish_job` in restore go through `_retry_locked`. (6) `GET /api/versions/list` now also returns `"restoring": [version_ids]` (from `version_history.inflight_versions()`), so a reopened modal can show the busy state.

**Download.** `/api/versions/download` used `prepare_download()`: rebuild the whole file into a temp dir, re-hash it, read it all into memory, *then* send — slow and memory-heavy for big QuickBooks files. Replaced by `version_history.open_download_stream()` + new `Engine.iter_version_bytes()`: bytes stream **straight from the object store** (1 MB blocks, no temp file, no rebuild), each object is hashed as it streams and the whole-file sha256/size checked at the end; any mismatch **raises, aborting the response** (failed download, never silent corruption). `app.py` wraps the sync generator in an async generator pulling one block per `asyncio.to_thread(next, …)` so the loop never stalls, and sets `Content-Length` (= version size) for browser progress. `prepare_download()` is kept but no longer used by `app.py`. Download and restore no longer touch each other's files.

**Verified** (stub-config, real Engine): 3 simultaneous restores → 1 success, 2 `IN_PROGRESS_MSG`, byte-exact result, no leftover `.tmp`; re-restore is instant (fast path); download byte-exact, first byte in ~2 ms; a flipped bit in a chunk aborts the stream. **Not verified in the browser or on the real deployment.**

**Front-end (done in v4.30, `static/js/index.js`)** — Restore/Download loading state, see the v4.30 note below.

**🆕 2026-09-28 sync note, part 4 — two log errors fixed (`file_monitor.py`, `version_engine.py`).**

**(A) `[WinError 32] … storage_index.json.tmp -> storage_index.json` (webdav_server, repeated).** Cause: `FileMonitor._save_cache()` wrote to a **fixed** `storage_index.json.tmp` and called `os.replace()` once. `prod_server.py` and the WebDAV subprocess each run their **own** `FileMonitor` against the **same** `cache/` dir, and inside one process the reconcile thread and watchdog handlers also call `_save_cache()` concurrently — so writers collided on the same `.tmp` / on the target while another process (or antivirus/indexer) had it open. `self._save_lock` already existed in `__init__` but was **never used**. Fix: (1) `_save_cache()` now holds `_save_lock`; (2) copies `_dir_info` under `self.lock` first, so `json.dump` never iterates a dict mutating mid-write; (3) writes to a **unique** `tempfile.NamedTemporaryFile(dir=CACHE_DIR, prefix="storage_index.", suffix=".tmp")`; (4) retries `os.replace()` on `PermissionError` with backoff (0/50/100/200/400/800/1500 ms); (5) cleans up its temp file on failure. Cross-process is last-writer-wins, which is fine (both compute the same index from the same disk). Same pattern `file_index.py` already used for `file_index.json`. **All `storage_index.json` users cross-checked**: only `file_monitor.py` reads/writes it (`_load_cache`, `_save_cache`, `CACHE_FILE`); `app.py` (`/admin/...` rebuild route, ~line 4409–4436) imports `CACHE_FILE` and `os.remove()`s it before a fresh walk — a delete, not a write, so it can't collide on the temp file, but it *can* hit the same sharing violation if a save is mid-replace (caught by that route's try/except); `file_index.py`, `paths.py`, `config.py` (menu text) only mention it in docs/comments. **Not verified on the real deployment.**

**(B) Version Engine `database is locked` at startup (12 workers failing in the same second, then `Scanner error: database is locked`).** The holder is still **not proven** from the log alone. Two observations: (1) the pasted log had **no `retry N/5 in Ns` warnings** between worker start and the errors — with the v4.27 code running, a failed first write would warn and back off before the worker-loop error can appear, so the deployed process may not have been running v4.27 (**restart the whole server, not just the engine, and confirm the new traceback/warning lines appear**); (2) SQLite's busy handler is sleep-and-poll with no fairness, so 12 workers + watcher + scanner, each on its own connection doing ~8 tiny commits per file, can starve a thread for the whole `busy_timeout` at the startup burst even with no slow holder. Changes: **`_GatedConnection`** (new, top of `version_engine.py`) — a `sqlite3.Connection` subclass used by `Engine._connect()` (`factory=`) that takes a process-wide `_WRITE_GATE` lock on the first write statement (`INSERT/UPDATE/DELETE/REPLACE/BEGIN`) of a transaction and releases it on `commit()/rollback()/close()`. In-process writers now queue on a real blocking lock instead of polling SQLite; SQLite's lock only arbitrates against the *other* process (web restore/retry). A failed write statement rolls back and releases immediately (no held gate/lock after an error); gate acquisition has a 60 s timeout and falls through to plain SQLite behaviour rather than deadlocking. Reads never take the gate. `busy_timeout` 10 s → 30 s. Previously **unwrapped** writes now go through `_retry_locked`: `run_gc()`'s `_create_job("gc")` and the whole `run_gc` call in `_scanner_loop`, `_set_meta("last_scan")`, the watcher/scanner `vanished` UPDATE loop, and `_finish_job`/`_apply_retention` on the snapshot success path. Scanner/watcher lock errors now log a **warning** ("will retry at the next interval") instead of an ERROR, and other scanner/watcher errors log with a traceback. `_worker_loop` rolls back its connection on any escaped error so it can never leave a transaction (or the gate) held. **Verified** with a stub-config harness against the real `Engine`: 12 workers + 3 chunked 3 MB files + 300 small files + concurrent `run_gc()` + an external connection holding `BEGIN IMMEDIATE` for 12 s (longer than the old 10 s timeout) — original: 1 `ERROR … database is locked` and several retries; patched: **0 errors**, 303/303 completed, 0 failed rows. **Not verified on the real deployment** (QuickBooks `.QBW`/`.TLG` files under `C:\Server\SharedFolder\QB Data 2024` are the real-world trigger). If it persists, the next log line will be a warning/traceback naming the statement.

**🆕 2026-09-28 sync note, part 3 — "database is locked" still appeared in the worker log** (`Snapshot failed for …SearchIndex\SuggestionIndex\_1.cfs: database is locked`, on a small file, during a burst of QuickBooks SearchIndex files) after the v4.26 chunk-commit fix was deployed. The log showed only the *victim* (a write that waited out `busy_timeout`), not the holder, so the exact holder is **not proven**; the fixes below remove every long write-lock window found by audit and make the engine survive and self-heal from any that remain. (1) **`run_gc()` rewritten** — it ran the whole sweep, including an `os.remove()` per deleted object, in one transaction (v4.26 only committed every 100 *deletions*, so orphan-marking UPDATEs still accumulated); it now classifies read-only, then applies writes in short `BEGIN IMMEDIATE` batches (500 rows or 0.25 s) with a 10 ms pause between batches so waiting writers actually get the lock. Measured on 150k objects: longest time another writer was blocked ≈ **1.0 s → 0.02 s** (total GC time 1.2 s → 3.3 s, background only). (2) **Transient-lock handling in `snapshot_file()`**: a lock error is no longer a permanent failure. New `_DatabaseBusy`; the half-made version row is discarded (no clutter, nothing stuck `pending`); the snapshot backs off 2/4/8/16/30 s (5 retries; 2 for a user-triggered web retry). If it gives up, the file's cached `(mtime,size)` is dropped so the watcher **re-queues it on its next poll** — previously a failed snapshot was silently lost until the file changed again. The leading bookkeeping writes (`_create_job`, `_get_or_create_file`, job link) retry too, and `_worker_loop` does the same requeue if a lock error escapes. (3) `PRAGMA synchronous=NORMAL` (WAL) — no per-commit fsync, so each of the ~8 commits per snapshot holds the lock for far less time on Windows/HDD. (4) Failures now log **with a traceback** (`exc_info=True`) so the next report shows *which statement* hit the lock; GC logs its duration. (5) `version_history.retry_snapshot()` now asks `Engine.last_snapshot_busy()` so a Retry that gave up on a locked DB says "database is busy, try again" instead of the misleading "already up to date". Verified against the real engine with stub config (transient lock retried through with no failed row; give-up path re-queues and leaves no failed row; lock released → same file snapshots normally; GC + retention leave the latest version byte-exact restorable; earlier slow-disk and concurrent-capture regressions still pass). **Not verified on the real deployment** — if the error persists, the traceback now in the log is what to look at. See [SQLite write-lock discipline](#sqlite-write-lock-discipline-2026-09-28) and [Version 4.27](#version-427--2026-09-28-lock-follow-up).

**🆕 2026-09-28 sync note, part 2 — "database is locked"**: reported symptoms were Retry failing with `capture failed: database is locked`, the Version History **Download** button returning a 500 (while pasting the same URL a moment later worked), and **Restore** saying "can't reach server". One root cause: `Engine._capture_chunked()` left its per-chunk `version_objects` INSERT **uncommitted**, so Python's implicit transaction (and SQLite's single write lock) stayed open while the *next* 8 MB chunk was read, hashed and fsync'd — i.e. for nearly the whole capture of a large file (a QuickBooks `.QBW.TLG` was the trigger). Any other writer — a second worker, the scanner, or the web process — waited out `busy_timeout` and got `sqlite3.OperationalError`. That includes `restore_version()`, whose **first** action is a write (`_create_job("restore")`), which is why a plain download hit it; the error wasn't a `VersionEngineError`, so `prepare_download()`/`restore()` didn't catch it → HTTP 500 → the frontend's `resp.json()` threw on the HTML body → misreported as "Could not reach the server". Fixed in `version_engine.py` (commit each chunk's object row + link together, immediately), hardened on the web side (bounded lock-retry, friendly "database is busy" message, all unexpected exceptions caught and logged, JSON-safe error parsing in the UI). Verified with a slow-disk simulation against the real engine: original → concurrent writers fail with "database is locked"; patched → succeed instantly; 3 concurrent chunked captures complete, restores byte-identical, GC runs. **Not yet verified on the real deployment.** See [SQLite write-lock discipline](#sqlite-write-lock-discipline-2026-09-28) and [Version 4.26](#version-426--2026-09-28-sqlite-write-lock-fix) in the Changelog.

**🆕 2026-09-28 sync note**: follow-ups to the Version History web UI (v4.24, already pushed). Failed capture rows are now **hidden by default** behind a "Show failed & deleted (N)" toggle, with a **Clear failed attempts** action (new `Engine.clear_failed_versions()` + `POST /api/versions/clear-failed`); the modal shows a **"12 of 50 versions kept"** line (amber from 90%, and warns at the cap that the next save removes the oldest); and the **Retry Now** result now appears inline in the Version History modal instead of a popup. Root cause of "the popup shows behind the modal": every `.modal` is `z-index: 1000` and `#notificationModal` comes earlier in the DOM than `#versionHistoryModal`, so equal z-index let the later modal paint over it — this also affected the Restore/Delete result popups, fixed by giving `#notificationModal` `z-index: 1100` (still under the 10000 toasts and 999999 tooltips). See [4.25 follow-ups](#version-history-web-ui-2026-09-27) and [Version 4.25](#version-425--2026-09-28-version-history-polish) in the Changelog. **Still experimental.**

**🆕 2026-09-27 sync note**: added a browser UI on top of the Version Engine — list a file's history, **download** any past version, **restore** it, **delete** it, and **retry** a failed capture — all from the file browser. New file `version_history.py` (logic only, no routes — same convention as `realtime_shares.py`/`search_index.py`); five routes added to `app.py`; `version_engine.py` gained four pure-data `Engine` methods (`list_tracked_files`/`list_versions`/`get_version`/`delete_version`) that `version_manage.py`'s `do_list()`/`do_delete()` now call instead of running their own SQL (CLI output re-verified unchanged). Two design decisions worth knowing before touching this: (1) a web restore **never overwrites the live file** — it reconstructs into a hidden `ROOT_DIR/.recovered/` folder, named by the version's own snapshot date, and (2) the row's **Download** button now opens a small choice modal (download current / Version History) instead of a permanent extra row icon, because a first attempt at a dedicated icon pushed Delete out of view on narrow screens. Live-verified through a real Quart test client with a real login (not just syntax-checked), which found three real bugs, all fixed: Quart's `Response` has no `call_on_close`; `/csrf-token` was 301-ing anonymous callers because `validate_session`'s exempt list was missing `get_csrf_token`; and `version_engine.py` replaced every capture failure's real exception with the literal string `"capture error"`. See [Version History Web UI](#version-history-web-ui-2026-09-27) and [Version 4.24](#version-424--2026-09-27-version-history-web-ui) in the Changelog. **Still experimental** — not yet deployed to production.

**🆕 2026-09-26 sync note**: `manage.sh` and `version_manage.py` both changed, at the user's explicit request, to finish integrating the Version Engine (added 2026-09-25, see the note below) into the existing ops tooling. `manage.sh`'s Utilities section was reordered — `version-manage` is now **menu #9** (the first Utilities entry), `config` moved to **#10**, and everything that used to occupy 9–19 shifted down to 11–20 in its previous relative order (this is the **third** time this doc's menu numbers have shifted from a mid-list insert — see [manage.sh Internals & Editing Rules](#managesh-internals--editing-rules), which has the full current 1–20 table). `version_manage.py` gained a full interactive menu (`interactive_menu()`, entered automatically with no CLI arguments) that shares its `do_list`/`do_restore`/`do_delete` core functions with the existing CLI subcommands — nothing is duplicated between the two interfaces. Ctrl-C handling was hardened throughout and *verified with real `SIGINT` delivery* (not simulated input) at three points: the interactive menu's top-level prompt (clean exit), mid-action inside a sub-prompt (cancels just that action, returns to the menu), and CLI-mode mid-confirmation (`restore --overwrite`, clean exit 1, no traceback). See [Version Engine (File Versioning)](#version-engine-file-versioning-2026-09-25) for the `version_manage.py` write-up and [Version 4.23](#version-423--2026-09-26-managesh-integration--version_managepy-interactive-mode) in the Changelog.

**🆕 2026-09-25 sync note**: added a brand-new subsystem, not a revision of an existing one — the **Version Engine** (per-file version history, independent of the git-style "share" feature). Two new files, `version_engine.py` (parent-API + `--worker` child process, mirrors `protocol_manager.py`'s WebDAV-subprocess pattern deliberately, see [WebDAV Process Isolation](#webdav-process-isolation-watchdog-restart-webdav-2026-09-09) for the pattern it copies) and `version_manage.py` (a separate admin CLI — `list`/`restore`/`delete` — kept out of `version_engine.py` on purpose, since that file is process-lifecycle code, not an interactive surface). `config.py` gained ~25 `VERSION_*` settings (master switch `VERSION_ENGINE_ENABLED`, chunking, workers, tracking scope, retention, GC) plus the matching menu tree; `paths.py` gained the `get_versions_dir`/`set_versions_dir`/`reset_versions_dir` trio (a fourth sibling of `db_path`/`cache_path`, since version history is irreplaceable, unlike the rebuildable cache tiers); `dev_server.py`/`prod_server.py` gained `version_engine.start()`/`.stop()`/`.force_kill()` calls at the same points WebDAV's process calls sit. `protocol_manager.py` and `app.py` are confirmed **byte-identical** to their pre-change state (`diff`-verified, not just "no changes intended") — the spec for this work explicitly required `protocol_manager.py` stay protocol-only. Full writeup, including the process architecture, SQLite schema, storage layout, the watcher-is-stat-polling-not-inotify design decision, and a real bug found and fixed during testing (`run_gc()`'s foreign-key violation on soft-deleted versions), is in the new **[Version Engine (File Versioning)](#version-engine-file-versioning-2026-09-25)** section, inserted after Protocol Servers. See [Version 4.22](#version-422--2026-09-25-universal-file-versioning-engine) in the Changelog.

**🆕 2026-09-24 sync note**: `sftp_server.py`, `ftp_server.py`, and `smb_server.py` all gained success-path AUDIT logging (`user`/`action`/`path`/`ip`) for login and every write operation (upload, delete, rename, mkdir, rmdir) — previously only PERMISSION_DENIED cases were logged for SFTP, and FTP's `log` object was dead code (created, never called). All three now log through `logging_setup.get_logger(...)` instead of a bare `logging.getLogger(__name__)`, so these lines actually reach the unified log file. While live-testing the SFTP patch against a real paramiko client, found and fixed a genuine pre-existing bug, unrelated to the audit-logging work itself: `sftp_server.py`'s `open()` was checking raw SSH_FXF_* protocol-level flag bits (`0x01`, `0x02`, `0x08`, …) against the `flags` argument, but paramiko's `SFTPServerInterface.open()` actually receives **already-converted `os.O_*` flags** (`os.O_WRONLY=1`, `os.O_CREAT=64`, …) — a different bit layout entirely. Effect: every brand-new-file SFTP upload was silently misdetected as a read-only open (`os.O_WRONLY`'s value of `1` collided with the old `_FXF_READ` bit) and failed with a bare "No such file" on the client side. Fixed in `_flags_to_mode()`/`_is_write_open()` to test the real `os.O_*` flags paramiko passes. All three protocols' full write-path (upload/overwrite/download/mkdir/rename/rmdir/delete, plus SFTP's readonly-role permission block) were re-verified against real clients (paramiko, pyftpdlib+ftplib, impacket's SMBConnection) after the fix, not just read over. SMB deliberately does not log plain read-opens (unlike SFTP/FTP) — see the new bullet in [SMB Implementation Notes](#smb-implementation-notes) for why. See [Version 4.19](#version-419--2026-09-24-sftpftpsmb-audit-logging--sftp-upload-flag-bug-fix) in the Changelog for the full writeup.

**🆕 2026-09-24 sync note, part 2**: `webdav_server.py` (read in full this pass, along with `hypercorn_ssl_fix.py` and the Hypercorn-related parts of `prod_server.py`/`dev_server.py`; `app.py` was **not** part of it) gained the same success-path AUDIT logging the other three protocols got earlier the same day. The note above (and [Version 4.19](#version-419--2026-09-24-sftpftpsmb-audit-logging--sftp-upload-flag-bug-fix)) says "all three" non-web protocols were covered — WebDAV was the fourth and had been missed: its `log` was `logging.getLogger(__name__)` (which resolves to `"__main__"` inside the WebDAV subprocess), attached to no handler and never called anywhere in the file, so WebDAV logins, uploads, deletes, and downloads left no user/action/IP trail at all. Triggered by a live log showing `Unhandled exception in client_connected_cb` / `ssl.SSLError: APPLICATION_DATA_AFTER_CLOSE_NOTIFY` with no client address on it. Two separate findings: (1) the missing WebDAV audit trail, fixed by a new `_AuditMiddleware` + login hooks in the domain controller, logging as `WebDAV AUDIT: user=... action=... path=... ip=...` through `logging_setup.get_logger("webdav")`; (2) that specific traceback can **never** carry an IP as asyncio reports it — by the time the exception reaches asyncio's handler the SSL transport's `peername` is already `None` (verified directly) — so `hypercorn_ssl_fix.py`'s patched `TCPServer._close()` now reads the peer address *before* teardown and logs the error as one IP-tagged line instead of a full traceback — that covers both the WebDAV process and the main listener, since both apply that patch. Two loose ends fixed in the same pass: `hypercorn_ssl_fix.py`'s own logger was a plain stdlib one with no handler (its startup line was silently dropped — now `logging_setup.get_logger("ssl_fix")`), and `webdav_server.py`'s `_build_hypercorn_logger()` still built its own `StreamHandler` on the tee'd stderr (double-timestamped `[STDERR]` lines) — now the same one-line `logging_setup.get_logger("hypercorn")` that `prod_server.py`'s copy already used. Also fixed: the noisy `Error in ASGI Framework` / `ConnectionResetError (_DisconnectAbortMiddleware guard)` traceback (one per cancelled download) — the guard's own deliberate error is now swallowed, everything else still raises; flood protection verified unchanged. See the new section [WebDAV Audit Logging and Client-IP Attribution for TLS-Teardown Errors](#webdav-audit-logging-and-client-ip-attribution-for-tls-teardown-errors-2026-09-24) and [Version 4.20](#version-420--2026-09-24-webdav-audit-logging--client-ip-attribution-for-tls-teardown-errors) in the Changelog. **Caveat, resolved later the same day**: this pass shipped `ip=` as the raw TCP peer (`REMOTE_ADDR`) only, flagging that it would be wrong if WebDAV were ever tunneled. Confirmed hours later that port 8443 genuinely is tunneled through `cloudflared` (8080 is not — HTTPS wins exclusively whenever it's enabled and starts; see WebDAV Implementation Notes) — `_client_ip()` now checks `CF-Connecting-IP`/`X-Forwarded-For` before falling back to `REMOTE_ADDR`, same trust chain as `get_client_ip()`. See [Version 4.21](#version-421--2026-09-24-webdav-client-ip-trust-chain-fix) in the Changelog.

**🆕 2026-09-23 sync note**: `app.py` gained a shared `get_client_ip()` helper (defined right above `RateLimiter`), replacing `RateLimiter`'s own private `_get_ip()`. Behind the project's Cloudflare Tunnel (`cloudflared`, orange-cloud/proxied) deployment, `request.remote_addr` only ever shows cloudflared's local connection — useless for identifying a real client — so `get_client_ip()` now reads `CF-Connecting-IP` first (set by Cloudflare's edge itself from the true connecting client, not spoofable by the client since there's no direct inbound path to this box) and falls back to the old `X-Forwarded-For`-first-entry/`remote_addr` logic only for non-tunneled access (e.g. `dev_server.py` on the LAN). The per-request logger (`_log_request_duration`, see [request-timing diagnostic tooling](#troubleshooting--edge-cases)) now logs this resolved IP on every line, plus a `[XFF: ...]` tag whenever the raw `X-Forwarded-For` header disagrees with it — that mismatch only happens if a client pre-populated `X-Forwarded-For` before Cloudflare appended the real IP, i.e. an active spoofing attempt, so it's surfaced rather than silently dropped. `RateLimiter._get_ip()` is now a one-line delegate to `get_client_ip()`, so login-lockout decisions get the same trust fix. **Caveat carried over into the code comments**: this trust chain assumes the app is reachable *only* through the tunnel — if the port is also directly exposed (firewall hole, port-forward), `CF-Connecting-IP` becomes spoofable again exactly like `X-Forwarded-For` was.

**Recent updates (2026-07-28)**:
- The web UI now uses a client-side logout entrypoint that still routes through the server-side `/logout` handler for session cleanup and cookie invalidation.
- Real-time storage stats now use the authenticated SSE endpoint `/api/storage_stats_stream`, with `/api/storage_stats_poll` available as a fallback when the stream is unavailable.
- The management shell now suppresses Ctrl-C while launching nested utility scripts so `manage.sh` remains in control and the underlying script can exit normally. ⚠️ **Superseded (2026-09-21)**: it no longer *ignores* Ctrl-C — that made child scripts uninterruptible. It now installs a *handled* trap (`trap ':' INT`) so `manage.sh` survives while the child still receives and reacts to Ctrl-C. See [manage.sh Internals & Editing Rules](#managesh-internals--editing-rules).
- SMB server hardening now includes additional Windows-specific save/delete compatibility fixes for Office-style file writes and transient lock handling.

**⚠️ Major update since the above (see the Changelog for full detail)**: The server was migrated **from Flask (WSGI) + Waitress to Quart (ASGI) + Hypercorn**, adding native HTTP/2 and HTTP/3 support across the web UI and WebDAV HTTPS. A full public **Share Links** feature was also added (opaque-token links, passkey/approval protection, expiry, bulk share/unshare, a "Manage Shared" admin panel, `revoke_sharing.py` CLI). Anywhere below that still says "Flask" is describing the pre-migration behavior/history — the live server is Quart/Hypercorn. See the [Sharing Routes](#sharing-routes) and Changelog sections for details.

**🆕 2026-08-23 sync note**: `app.py` and `index.js` were diffed against this doc and found to have drifted further than the sections below reflect — mostly route-path renames and a batch of new endpoints that were never written up. Rather than rewrite the tables below (which still have useful response-shape examples), corrections and additions live in a new **[Route Path Corrections & New Endpoints (2026-08-23)](#route-path-corrections--new-endpoints-2026-08-23)** section right after the original "Quart Routes & API" section, and in the updated JS function list under Quick Reference. Treat that new section as authoritative for *paths*; treat the older tables as authoritative for general request/response shape except where the new section says otherwise.

**🆕 2026-08-23 sync note, part 2**: a further pass against `index.html`/`index.js`/the new `pdfjs-worker-init.mjs`/`pdfjs-viewer-overlay.css` found the old `/pdfviewer` route entirely gone, replaced by pdf.js merged directly into `index.html`. See **[Embedded PDF.js Viewer (2026-08-23)](#embedded-pdfjs-viewer-2026-08-23)**, added right after the Route Path Corrections table.

**🆕 2026-08-28 sync note**: `ssl_cert.py`, `config.py`, `index.css`, `pdfjs-viewer-overlay.css`, `index.js`, `index.html`, `app.py`, and `sftp_server.py` were all touched in the same edit pass. Re-verified `@app.route`/`fetch(` in `app.py`/`index.js` — no route-level drift beyond what the 2026-08-23 corrections already cover. Real deltas found: (1) `sftp_server.py` now hardens the SSH transport's offered ciphers/MACs/KEX on every connection (see the new bullet in [SFTP Implementation Notes](#sftp-implementation-notes)); (2) `config.py` adds `FTP_TLS_ENABLED`/`FTP_TLS_REQUIRE_DATA` (FTPS support) and flips `WEBDAV_ENABLED` (plaintext HTTP WebDAV) to `False` by default (see the updated [config.py Protocol Variables](#configpy-protocol-variables) block); (3) `ssl_cert.py`'s module docstring now documents macOS/Linux (davfs2) trust-import steps, not just Windows (see [SSL Certificate](#ssl-certificate-ssl_certpy)); (4) a likely-unintentional regression was found in `pdfjs-viewer-overlay.css` — see the callout in [Embedded PDF.js Viewer](#embedded-pdfjs-viewer-2026-08-23). `index.css`/`index.html` were reviewed and show no behavioral changes beyond what's already documented.

**🆕 2026-08-28 sync note, part 3**: a later edit in the same day touched `index.js`, `app.py`, and added a brand-new file, `static/css/video-skin-overrides.css`. This is a real (not doc-only) change, and it revises the "no behavioral changes" verdict the note above gave `index.js`/`app.py`: `index.js`'s `_injectMobileSpeedHide()` no longer injects inline `<style>` template-literal elements into the `<video-skin>` shadow root (those were silently dropped once the CSP's `style-src-elem` stopped allowing `'unsafe-inline'`); it now `<link>`s the new external stylesheet instead, which satisfies `style-src-elem 'self'` with no CSP hash to maintain. See the new **[video-skin-overrides.css & the Inline-Style CSP Cleanup (2026-08-28)](#video-skin-overridescss--the-inline-style-csp-cleanup-2026-08-28)** section, added after [Embedded PDF.js Viewer](#embedded-pdfjs-viewer-2026-08-23). `login.html` was also uploaded in this pass and is now documented for the first time under [Login Flow](#login-flow) (its markup wasn't previously written up at all, only `login.js`'s function names). `pdfjs-worker-init.mjs` and `index.css` were re-checked and still match the existing [Embedded PDF.js Viewer](#embedded-pdfjs-viewer-2026-08-23) and `body::before`/`::after` documentation — no further changes found there.

**🆕 2026-09-21 sync note**: `manage.sh`, `setup_pymodules.sh`, and `revoke_sharing.py` were re-read in full and compared against this doc. No earlier copies of those files were available, so this was a doc-vs-code comparison, not a diff — anything below dated 2026-09-21 means "present in the files as reviewed", not "changed on that day". No app-code files (`app.py`, `database.py`, `logging_setup.py`, `protocol_manager.py`, …) were part of this pass. Real gaps found and fixed in this doc: (1) `setup_pymodules.sh` and `constraints.txt` were not documented anywhere → new [Package Management (setup_pymodules.sh)](#package-management-setup_pymodulessh) section; (2) `revoke_sharing.py` has 9 subcommands (list, revoke, revoke-path, revoke-all, edit, edit-path, requests, approve, deny) and this doc listed only 3 (list, revoke, revoke-all) → updated under [Database Tools](#database-tools); (3) `manage.sh`'s Ctrl-C handling changed from *ignore* to *handle*, and its menu is 19 entries with security.txt now at **18** → corrected, plus a new [manage.sh Internals & Editing Rules](#managesh-internals--editing-rules) section. **Problems found but deliberately not fixed here** (they are code changes, not doc changes): `setup_pymodules.sh` strips the `Quart>=0.21.0,<1` floor pin; `revoke_sharing.py`'s `--passkey`/`--generate-passkey` silently no-op without `--mode passkey`; a print()-capture contradiction between `manage.sh` and the logging section below. Each is spelled out in the sections linked above.

**🆕 2026-09-22 sync note**: `database.py` (755 lines) was read in full to verify the four items the 2026-09-21 pass had flagged as inferred-but-unchecked. Result: three of the four `revoke_sharing.py` share/request method signatures guessed on 2026-09-21 were exactly right (`list_active_shares`, `revoke_share_by_token`, `revoke_all_shares`, `list_pending_requests`, `approve_access_request`, `deny_access_request`, `get_share_by_token`, `get_share_by_path`, `revoke_share_by_path`, `create_share`, `update_share_settings`, `verify_share_passkey`, `get_shares_for_paths`, `bulk_revoke_by_paths`, `record_share_download`, `create_access_request`, `get_access_request_by_access_token`, `count_pending_requests`, `record_access_request_download` all present, all matching). **Gotcha #2 in [Database Tools](#database-tools) is now confirmed, not inferred**: `update_share_settings()` only clears `passkey_hash` when the caller passes `clear_passkey=True` explicitly — it does not happen automatically on a mode change, in `database.py` or anywhere else in this file. Whatever clears it for the web UI (if anything does) lives in `app.py`, which still wasn't part of any pass to date. Also confirmed while in there: the double-checked-locking-plus-`conn.commit()` bootstrap fix described under Troubleshooting → Quart/Hypercorn Migration Issues matches `_connect()`/`_do_bootstrap()` line for line, including the exact failure mode described (`sqlite3.OperationalError: no such table: users` from the naive version, a quiet "invalid credentials" from the commit-less version). Share tokens (`create_share`) and access-request tokens (`create_access_request`) both use `secrets.token_urlsafe` — cryptographically fine; this does not extend to the *passkey* itself, which `revoke_sharing.py` still generates with `random`, not `secrets`, as noted in gotcha #3. `app.py`, `auth.py`, and every protocol server remain unread by any pass to date; do not treat statements about them elsewhere in this doc as re-verified.

---

## 📋 Table of Contents

1. [Quick Reference](#quick-reference)
2. [Project Overview](#project-overview)
3. [Architecture & Module Map](#architecture--module-map)
4. [Core Systems Deep Dive](#core-systems-deep-dive)
5. [Data Structures](#data-structures)
6. [Quart Routes & API](#quart-routes--api) (includes [Sharing Routes](#sharing-routes))
7. [Database Schema](#database-schema)
8. [Authentication & Sessions](#authentication--sessions)
9. [File Upload System](#file-upload-system)
10. [Real-Time Monitoring](#real-time-monitoring)
11. [Directory Listing & Caching](#directory-listing--caching)
12. [Full-Text Search](#full-text-search)
13. [Media Handling](#media-handling)
14. [Bulk Operations](#bulk-operations)
15. [Configuration & Deployment](#configuration--deployment)
16. [Protocol Servers (WebDAV / SFTP / FTP / SMB)](#protocol-servers-webdav--sftp--ftp)
17. [Version Engine (File Versioning)](#version-engine-file-versioning-2026-09-25) (includes [Version History Web UI](#version-history-web-ui-2026-09-27))
18. [Admin Tools & Utilities](#admin-tools--utilities)
19. [Performance Characteristics](#performance-characteristics)
20. [Troubleshooting & Edge Cases](#troubleshooting--edge-cases)

---

## ⚡ Quick Reference

### Most Important Files

| File | Purpose | Key Responsibilities |
|------|---------|----------------------|
| **app.py** | Quart (ASGI) server & route handlers, incl. share-link routes | HTTP endpoints, session mgmt, response building — migrated from Flask/WSGI, see Changelog |
| **storage.py** | File system operations | List dirs, chunks, assembly, cleanup |
| **database.py** | SQLite + encryption (read in full 2026-09-22) | Users, passwords, server tokens, sessions, share tokens/requests. `_connect()` does double-checked-locking bootstrap + explicit `conn.commit()` before releasing the lock (see Troubleshooting) — confirmed to match this file exactly. `update_share_settings()` never clears `passkey_hash` implicitly, only via explicit `clear_passkey=True` — see [Database Tools](#database-tools) gotcha #2 |
| **auth.py** | Authentication helpers | Login/logout, session validation, role checking |
| **config.py** | Settings & feature toggles | Paths, sizes, feature flags. 🆕 (2026-09-25) ~25 new `VERSION_*` settings for the Version Engine (master switch, chunking, workers, tracking scope, retention, GC) plus a full menu tree — see [Version Engine](#version-engine-file-versioning-2026-09-25) |
| **paths.py** | Configurable directory resolver | db_path, cache_path, storage_path resolution. 🆕 (2026-09-25) `get_versions_dir()`/`set_versions_dir()`/`reset_versions_dir()` — a fourth sibling of db_path/cache_path, `<server_root>/versions` by default; deliberately NOT nested under cache_path since version history is irreplaceable, unlike cache's rebuildable data — see [Version Engine](#version-engine-file-versioning-2026-09-25) |
| **file_monitor.py** | Real-time filesystem tracking | Watchdog integration, counters, reconciliation. 4.59: `storage_index.json` validated on load (version/root/counters/records), aborted or suspect-empty walks rejected, per-folder drift logged — see the 2026-10-02 part 6 sync note |
| **file_index.py** | Large-folder caching | Indexed dir listings, instant lookups. 4.58: validated on load, on every read (folder-mtime check) and on every walk; `verify_all()` audit — see the 2026-10-02 part 5 sync note |
| **search_index.py** | Full-text search engine | FTS5 indexing, query processing |
| **sri_validator.py** (new, 4.55) | SRI hash checker/fixer for the Jinja templates | `python sri_validator.py` (check, exit 1 on STALE/NONE/MISS) / `--fix` (write correct `integrity` into every local `<script src>`/`<link href>` under `templates/`); `--templates`/`--static` dirs; see the 2026-10-02 part 2 sync note; run via `./manage.sh validate-sri [--fix]` (menu #21, 4.56) |
| **realtime_stats.py** | Server-Sent Events | Live storage stats broadcasting |
| **realtime_shares.py** | Server-Sent Events (admin-only) | Live pending-share-request count + active-shares-changed nudges for the Manage Shared panel |
| **protocol_manager.py** | Protocol server launcher | Starts/stops WebDAV, SFTP, FTP, SMB. 🆕 (2026-09-09) WebDAV now runs as its own isolated OS **subprocess** (not a thread) with a watchdog that auto-respawns it on crash — see [WebDAV Process Isolation, Watchdog & restart-webdav](#webdav-process-isolation-watchdog-restart-webdav-2026-09-09); SFTP/FTP/SMB remain background threads, unchanged |
| **webdav_server.py** | WebDAV server | wsgidav WSGI app bridged onto Hypercorn via `asgiref.WsgiToAsgi`; serves HTTP+HTTPS from one Hypercorn Config; role enforcement (no longer waitress/cheroot for serving — cheroot is now only a transitive wsgidav dependency). 🆕 (2026-09-09) HTTPS listener is now HTTP/1.1-only (h2 dropped from ALPN — see Troubleshooting); also applies `hypercorn_ssl_fix.py`'s patch. 🆕 (2026-09-09, second pass) `_DisconnectAbortMiddleware` wraps `WsgiToAsgi` to stop a real silent write-flood on cancelled downloads — see [WebDAV Disconnect-Flood Guard](#webdav-disconnect-flood-guard-2026-09-09-second-pass). 🆕 (2026-09-24) `_AuditMiddleware` + login hooks write `WebDAV AUDIT: user=... action=... path=... ip=...` lines, and `hypercorn_ssl_fix.py`'s patched `_close()` turns Hypercorn's anonymous TLS-teardown traceback into one IP-tagged line — see [WebDAV Audit Logging and Client-IP Attribution](#webdav-audit-logging-and-client-ip-attribution-for-tls-teardown-errors-2026-09-24) |
| **sftp_server.py** | SFTP server | Paramiko SSH/SFTP, RSA host key, chrooted to ROOT_DIR; hardens offered SSH ciphers/MACs/KEX per connection; 🆕 (2026-09-14) channel-accept window raised `30s`→`120s` + added a 30s transport keepalive to stop mobile clients from getting disconnected (see [SFTP Implementation Notes](#sftp-implementation-notes)) |
| **smb_server.py** | SMB server | impacket SimpleSMBServer, Tree Connect role enforcement, Windows file-locking fixes |
| **smb_setup.py** | SMB one-time setup | Standalone tool — Windows LanmanServer, Linux setcap, Android root check |
| **lanman_guard.py** | SMB Windows state tracker | Passive pending-setup state file, read by smb_server.py, written by smb_setup.py |
| **kick_sessions.py** | Access revocation tool | Rotate/delete a user, or instantly log out the web UI, for security incidents (replaced the older `revoke_session.py`) |
| **revoke_sharing.py** | Share-link management CLI (not just revocation any more) | Interactive 8-item menu + 9 CLI subcommands: list, revoke (by token or path), revoke-all, **edit** security mode/passkey/expiry, and work the approval queue (**requests / approve / deny**) — talks straight to `database.db`, no running server needed. See [Database Tools](#database-tools) for the flags and two verified gotchas |
| **version_engine.py** 🆕 (2026-09-25) | Universal File Versioning Engine — process lifecycle only, no admin CLI (see version_manage.py) | Dual role: parent API (`start()`/`stop()`/`force_kill()`/`status()`, imported only by `dev_server.py`/`prod_server.py`) + `--worker` child-process entry point. Runs as its own OS subprocess, mirroring `protocol_manager.py`'s WebDAV-subprocess pattern exactly (same `Popen` args, `CLOUDINATOR_LOG_PREFIX`/`PYTHONUTF8` env vars, piped-and-relayed stdout/stderr, Windows `CREATE_NO_WINDOW` guard) — deliberately does NOT get a watchdog/auto-respawn thread like WebDAV's, since a stuck engine is expected to self-heal via crash recovery on the next `start()`, not be silently respawned. See [Version Engine](#version-engine-file-versioning-2026-09-25) |
| **version_manage.py** 🆕 (2026-09-25, interactive menu + manage.sh wiring added 2026-09-26) | Version Engine admin CLI + interactive menu (`list` / `restore` / `delete`) | Deliberately a separate file from `version_engine.py` — no interactive/admin code belongs in the process-lifecycle file. Does not start the engine (no threads/subprocess); talks directly to the same SQLite DB + object store, safe to run alongside a live `version_engine.py --worker`. Run with no args for an interactive menu, or use CLI subcommands directly — both call the same underlying `do_list`/`do_restore`/`do_delete` functions. `delete` requires typing a full, version-and-filename-specific confirmation sentence back exactly — no `-f`/`--yes` shortcut exists on purpose. Wired into `manage.sh` as `version-manage` (menu #9); Ctrl-C at any prompt in either mode cancels cleanly, never a traceback. See [Version Engine](#version-engine-file-versioning-2026-09-25) |
| **manage.sh** | Server & utility launcher (bash) | Start/stop/restart/status/logs, `restart-webdav`, and a wrapper for every utility script; 21-entry interactive menu (⚠ 2026-10-02: `validate-sri` appended as #21; 🆕 2026-09-26: `version-manage` inserted as #9). Runs under `set -euo pipefail`, which has caused real bugs — read [manage.sh Internals & Editing Rules](#managesh-internals--editing-rules) before editing it |
| **setup_pymodules.sh** | Python dependency ceiling generator + installer (bash) | Regenerates `constraints.txt` and rewrites managed lines of `requirements.txt` with `<next-major>` ceilings, dry-run-checks for conflicts, then optionally installs. Run via `./manage.sh update-modules`. Windows: self-elevates and adds a Defender exclusion. See [Package Management](#package-management-setup_pymodulessh) |
| **ftp_server.py** | FTP server | pyftpdlib, custom authorizer, passive ports 60000–60100 |
| **ssl_cert.py** | TLS certificate manager | Self-signed cert generation, SAN detection, db/ storage; `prod_server.py` now prefers a real Tailscale-issued cert when available, falling back to this self-signed cert otherwise; module docstring now covers Windows + macOS + Linux trust-import steps |
| **static/js/pdfjs-worker-init.mjs** | pdf.js integration shim (new, undocumented until now — see [Embedded PDF.js Viewer](#embedded-pdfjs-viewer-2026-08-23)) | Sets `GlobalWorkerOptions.workerSrc` directly, then reasserts it (plus `cMapUrl`/`iccUrl`/`standardFontDataUrl`/`wasmUrl`/`imageResourcesPath`) via pdf.js's `webviewerloaded` hook so they survive viewer.mjs's own self-init; also clears the dev build's hardcoded sample-PDF `defaultUrl` |
| **static/css/pdfjs-viewer-overlay.css** | pdf.js viewer scoping/theming fix (new, undocumented until now) | Loaded after the merged `viewer.css` to win cascade ties; undoes viewer.css's page-wide `:root`/`body` leaks and re-parents `#pdfjsViewerRoot` into a normal flex child of the file-viewer modal instead of a full-page absolute overlay; also fixes mobile toolbar overflow |
| **static/css/video-skin-overrides.css** | video-skin shadow-root override stylesheet (new, 2026-08-28 — see [video-skin-overrides.css & the Inline-Style CSP Cleanup](#video-skin-overridescss--the-inline-style-csp-cleanup-2026-08-28)) | `<link>`ed by `index.js`'s `_injectMobileSpeedHide()` into the `<video-skin>` shadow root; hides the playback-rate button under `max-width: 600px`, and styles `::cue` (transparent caption background + black text-shadow outline + white text) for readability over video |
| **static/js/bg_audio.js** (new, 4.54) | Optional looping background music (cosmetic) | Drives `<audio id="bgMusic">` (`static/audio/bg_mus.opus`) on index/login/shared/404 templates: volume 0.20, resumes position + play state via `localStorage` (`cloudinator_bg_music_time` / `_playing`), keeps retrying on every click/key/touch gesture until `play()` really succeeds if autoplay is blocked (4.57). SRI hash is duplicated in all four templates — recompute in all four after any edit |

### Startup Order

```
1. ensure_dirs() → creates db/, cache/, hls_cache/, img_cache/
2. database._connect() → SQLite, _bootstrap() (double-checked-locked + committed before release — see Changelog), default users
3. file_monitor.init() → full initial walk, build storage_index.json
4. file_index.py → `load()` validates file_index.json (records start unverified and are re-read on first use); `build_from_walk()` re-reads every large folder after the walk (4.58)
5. search_index_manager.start_crawler() → background FTS5 population (main process only since 4.52 — skipped in the WebDAV/Version Engine helper processes; `_ready` becomes True only when the crawler finishes or finds a complete DB, until then searches use the slow `os.walk` fallback)
6. start_assembly_worker() → chunk assembly background daemon
7. cleanup_scheduler → starts periodic cleanup
8. Quart app ready, served by Hypercorn (ASGI) — HTTP/1.1, HTTP/2, and HTTP/3; TLS cert comes from Tailscale if available, else ssl_cert.py's self-signed cert
9. protocol_manager.start_all() → WebDAV (8080/8443, wsgidav bridged onto Hypercorn via asgiref — its own OS subprocess since 2026-09-09, supervised by a watchdog), SFTP (2222) and FTP (2121) start in daemon threads; SMB (445/8445) starts too if SMB_ENABLED
10. start_expired_share_cleanup_scheduler() → periodic sweep that auto-revokes share links past their expires_at and notifies connected admins via realtime_shares.py
```

---

## 🔧 Key Functions & Entry Points

### Python modules

- **app.py**: `get_local_ip()`, `RateLimiter`, `AssemblyQueue`, `validate_session()` (the `before_request` hook — async, Quart), `login()`, `logout()`, `index()`, `download()`, `view_file()`, `pdf_viewer()`, `office_preview()`, `archive_preview()`, `storage_stats_stream()`, and the share-link handlers `create_share()`, `update_share_settings()`, `revoke_share()`, `bulk_share()`, `shared_download()`, `shared_browse()`, `shared_zip_selected()`.
- **auth.py**: `check_login()`, `get_role()`, `login_user()`, `logout_user()`, `current_user()`, and `is_logged_in()`.
- **config.py**: `detect_platform()`, `get_windows_documents_path()`, `get_accessible_storage_path()`, `setup_storage_directory()`, and the configuration helpers such as `configure_server_settings()`, `configure_port()`, `configure_chunk_size()`, and `configure_session_timeout()`.
- **database.py**: `_connect()`, `_bootstrap()`, `add_user()`, `update_password()`, `check_login()`, `get_role()`, `get_server_token()`, `rotate_server_token()`, `get_smb_credentials()`, `users_missing_nt_hash()`, and the share-link methods `create_share()`, `get_share_by_token()`, `get_share_by_path()`, `update_share_settings()`, `revoke_share_by_path()`.
- **storage.py**: `list_dir()`, `count_directory_items()`, `save_chunk()`, `verify_chunks_complete()`, `assemble_chunks()`, and `cleanup_chunks()`.
- **file_monitor.py**: `InstantFileEventHandler.on_created()`, `on_deleted()`, `on_moved()`, `on_modified()`, plus `FileSystemMonitor.start()`, `stop()`, and `reconcile()`.
- **file_index.py**: `_scan_folder_entries()`, `_scan_checked()` (4.58), and `FileIndexManager.load()`, `save()`, `build_from_walk()`, `update_folder()`, `remove_folder()`, `rename_folder()`, `get_entries()` (validates freshness before returning, 4.58), `is_indexed()` (membership only), and `verify_all()` (4.58 audit).
- **search_index.py**: `SearchIndexManager.add()`, `remove()`, `rename()`, `query()`, and the background indexing workflow.
- **realtime_shares.py**: `ShareEventManager.broadcast()` (pending-request count), `broadcast_active_shares_changed()` (nudges the Active Shares tab to refetch), and `share_events_sse()` — same call-from-any-thread pattern as `realtime_stats.py`.
- **revoke_sharing.py**: `cmd_list()`, `cmd_revoke()`, `cmd_revoke_path()`, `cmd_revoke_all()`, `cmd_edit()`, `cmd_edit_path()`, `_apply_edit()` (shared by both edit commands and the interactive menu), `cmd_requests()`, `cmd_approve()`, `cmd_deny()`, `run_interactive_menu()`, and helpers `_parse_duration()`, `_generate_passkey()`, `_operator_id()`, `_fmt_expiry()`. It calls into `database.py`'s share/request API — `list_active_shares()`, `revoke_share_by_token()`, `revoke_share_by_path()`, `revoke_all_shares()`, `get_share_by_token()`, `get_share_by_path()`, `update_share_settings()`, `list_pending_requests()`, `approve_access_request()`, `deny_access_request()` — all confirmed present with matching signatures as of the 2026-09-22 `database.py` read.
- **webdav_server.py**, **sftp_server.py**, **ftp_server.py**, and **smb_server.py**: their protocol-specific startup and auth hooks, including the middleware and role enforcement entry points used by each server.
- **version_engine.py** 🆕 (2026-09-25): parent API `start()`, `stop()`, `force_kill()`, `status()`; `Engine` class — `snapshot_file()`, `restore_version()`, `run_gc()`, `get_eligible_files()`, `_crash_recovery()`, `_attempt_snapshot()`, `_capture_full()`/`_capture_chunked()`, `_reconcile_once()`, `_watcher_loop()`/`_scanner_loop()`, `_worker_loop()`, `graceful_shutdown()`. Worker-mode entry: `_worker_main()`, invoked via `python version_engine.py --worker`.
- **version_manage.py** 🆕 (2026-09-25): `cmd_list()`, `cmd_restore()`, `cmd_delete()`, `_get_engine()` (bootstraps schema, starts no threads), `_fmt_time()`. Calls straight into `version_engine.py`'s `Engine.restore_version()` and `Engine.run_gc()` — no duplicated logic.

### JavaScript modules

- **static/js/index.js**: `initTapTooltips()`, `lockTableColumnWidths()`, `smartTableColumnizer()`, `searchTable()`, `performDeepSearch()`, `navigateToFolder()`, `loadStorageStats()`, `updateStorageDisplay()`, `addToUploadQueue()`, `cancelUpload()`, `openFileViewer()`, and `closeFileViewer()`.
- **static/js/login.js**: `isComingFromLogout()`, `checkAuthenticationStatus()`, and `checkAndRedirectIfLoggedIn()`.
- **static/js/404.js**: the redirect countdown logic used by the custom 404 page.

**🆕 Additional index.js functions confirmed present as of 2026-08-23** (not previously listed here — this is additive, the four functions above are still accurate, just incomplete):
  - Upload queue / conflict handling: `_buildConflictDialog()`, `_promptOverwrite()`, `_promptFolderConflict()`, `_promptMoveOrCopyConflicts()`, `_findFreeName()`, `cleanupUnfinishedChunks()`, `cleanupSingleFile()`, `_spawnFileWorkersIfNeeded()`, `_runFileWorker()`, `_spawnFolderWorkersIfNeeded()`, `_runFolderWorker()`, `startBatchUpload()`, `startParallelUploads()`, `startSequentialUploads()`, `xhrUpload()`, `uploadSingleFile()`, `_resumeStalledUploads()`, `_startSessionKeepAlive()` — this whole conflict-prompt cluster talks to `/api/check_conflicts` and `/api/exists`, neither of which was in the routes table before this sync (see the new routes section below).
  - Folder upload grouping: `_registerFolderGroup()`, `_scanSizeChunked()`, `_uploadFolderGroupLazy()`, `_maybeFinalizeGroup()`, `_finalizeGroupCleanup()`, `_cancelFolderGroup()`, `_stopFolderGroup()`, `_folderRowContent()`, `_createFolderGroupRow()`, `_updateGroupRowInPlace()`.
  - Image preview/zoom: `_imgStartPreview()` (drives `/image_preview/<path>` + polls `/image_preview_status/<cache_key>`), `_initImageZoom()`, `_handleImgConvError()`.
  - HLS video preview: `_hlsSkip()`, plus the HLS mount logic around `_mountHlsPlayer()` (talks to `/hls_start/<path>`, `/hls_status/<cache_key>`, and streams from `/hls_files/<cache_key>/...` — see corrected routes below). `_injectMobileSpeedHide()` (called from the same mount path) links `static/css/video-skin-overrides.css` into the player's `<video-skin>` shadow root — see [video-skin-overrides.css & the Inline-Style CSP Cleanup (2026-08-28)](#video-skin-overridescss--the-inline-style-csp-cleanup-2026-08-28).
  - Office preview rendering: `_renderOfficePreview()`.
  - Deep search (windowed, see Version 4.40): `_dsBuildWindow()`, `_dsRenderWindow()`, `_dsMountRange()`, `_dsScheduleMeasure()`, `_dsRebuildOffsets()`, `_dsPositionSpacers()`, `_dsFetchNextPage()`, `_dsRemoveResults()`, `_dsUpdateCount()`, `_parseSearchQuery()`, `displayDeepSearchResults()`, `createSearchResultsHeaderDiv()`, `createSearchResultRow()`, `highlightText()` (deep search; takes RAW text, escapes itself — Version 4.41), `highlightSearchTerm()` (normal search; text-node walker — Version 4.41).
  - Move/copy folder browser modal: `showMoveModal()`, `showCopyModal()`, `initializeFolderBrowser()`, `loadFolderContents()`, `displayFolders()`, `navigateFolderBrowser()`, `createNewFolderInBrowser()`.
  - Selection/rename UI: `toggleSelectAll()`, `updateSelection()`, `initializeRenameButtonVisibility()`, `clearSelection()`, `_populateSelectedItemsVT()` (virtualized selected-items list).
  - `refreshFileTable()`, `handleDeleteClick()` — table refresh after mutating ops instead of a full page reload.

This section is intentionally high-level: the detailed route behavior, storage logic, and protocol-specific implementation notes are covered elsewhere in this guide.

---

## 🎯 Project Overview

**CloudinatorFTP** is a sophisticated Quart-based (ASGI, served by Hypercorn) web file server designed for:
- **Multi-platform**: Windows, Linux, macOS, Android (Termux)
- **Scalability**: Handles 100k+ files with instant response times
- **Real-time**: Live filesystem monitoring with SSE updates
- **Rich media**: HLS video streaming, WebP compression, archive preview
- **Security**: Per-user authentication, role-based access, encrypted passwords
- **Uploads**: Chunked resumable uploads, automatic assembly, conflict resolution
- **Public Sharing**: Opaque-token share links per file/folder, with optional passkey or admin-approval gating and expiry
- **Protocol Access**: WebDAV (native drive mapping), SFTP (WinSCP/sshfs), FTP (legacy clients), SMB (native network drive, one-time setup)

**Core Design Philosophy**:
- Event-driven watchdog for instant monitoring
- Incremental caching (storage_index.json, file_index.json)
- Lazy initialization (nothing created on import)
- Modular systems (auth, storage, search, media all independent)
- Graceful fallbacks (missing ffmpeg → raw video, no libvips → raw images)
- Protocol servers are optional daemon threads — main Quart/Hypercorn server unaffected if any fail
- No blocking calls in the async request path — Hypercorn runs a single event loop, so anything CPU/IO-heavy (bcrypt, image/archive/office conversion, uncached `list_dir()`) is offloaded via `asyncio.to_thread` rather than run inline (unlike the old Waitress/thread-per-request model, a blocking call here stalls every concurrent user, not just one)

---

## 🏗️ Architecture & Module Map

### Dependency Graph

```
app.py (Quart entry point, ASGI routes, incl. share-link routes)
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
├─→ realtime_stats.py (Server-Sent Events — storage stats)
├─→ realtime_shares.py (Server-Sent Events — pending share requests / active-shares changes)
├─→ database.py (SQLite persistence, incl. share tokens/requests)
│
├─ Protocol Layer (started from dev_server.py / prod_server.py):
│   └─→ protocol_manager.py
│       ├─→ webdav_server.py (🆕 2026-09-09: own OS subprocess, not a thread — see Protocol Servers) → wsgidav, bridged onto Hypercorn via asgiref.WsgiToAsgi, ssl_cert.py (or Tailscale cert), hypercorn_ssl_fix.py (🆕 patches a real Hypercorn bug — see Troubleshooting)
│       ├─→ sftp_server.py  → paramiko
│       ├─→ ftp_server.py   → pyftpdlib
│       └─→ smb_server.py   → impacket
│
└─ Supporting CLIs:
   ├─→ manage_users.py (user management — renamed from create_user.py)
   ├─→ reset_db.py (database reset)
   ├─→ kick_sessions.py (session/user revocation — replaced revoke_session.py)
   ├─→ revoke_sharing.py (share-link revocation, editing, approval queue — imports only database.db)
   └─→ debug_passwords.py (auth testing)
```

### Key Principles

1. **Lazy Initialization**: Nothing created on module import—only on first use
2. **Single Source of Truth**: paths.py resolves all directory locations
3. **Atomic Operations**: File operations use platform-specific safety (Windows readonly handling)
4. **No Blocking I/O in the Event Loop**: Chunks processed, assembly backgrounded, cleanup scheduled — and since the migration to Hypercorn's single-event-loop ASGI model, any remaining synchronous heavy-lifting (bcrypt, image/archive/office conversion, uncached `list_dir()`) is explicitly wrapped in `asyncio.to_thread` rather than run inline, because it would otherwise block every concurrent request, not just the one that triggered it
5. **Event-Driven Stats**: Watchdog updates counters; reconcile corrects drift
6. **Protocol Servers are Daemon Threads**: They die automatically when the main process exits; failures do not affect the Quart/Hypercorn server

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
  "version": 2,
  "threshold": 80,
  "saved_at": 1234567890.5,
  "dir_count": 1,
  "dirs": {
    "videos": {
      "entry_count": 500,
      "indexed_at": 1234567890.5,
      "dir_mtime_ns": 1234567890500000000,
      "entries": [
        {"name": "movie1.mkv", "is_dir": false, "size": 4000000000, "modified": 1234567890},
        {"name": "subfolder", "is_dir": true, "size": null, "modified": 1234567890}
      ]
    }
  }
}
```
**Purpose**: Instant listing for folders >80 entries (4.58: version 2 adds `dir_mtime_ns`; version 1 still loads)  
**Updated By**: watchdog (`update_folder()` re-scans the folder in memory — it does **not** write the file), `build_from_walk()` (re-reads every large folder, then saves), `get_entries()` (re-scans a stale folder)  
**Auto-Added**: folders exceeding threshold when the walk or a watchdog `update_folder()` sees them  
**Validated**: on load (schema/threshold/records; survivors are unverified), on every `get_entries()` (first read = full re-scan, later reads = one `stat` vs `dir_mtime_ns`), on every walk. Only the file on disk is ever stale; the in-memory copy is what `list_dir()` reads

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

**Table: share_links**
```sql
CREATE TABLE share_links (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  token          TEXT    UNIQUE NOT NULL,        -- opaque, used in /shared/<token> URLs
  file_path      TEXT    NOT NULL,
  item_name      TEXT    NOT NULL,
  is_dir         INTEGER NOT NULL DEFAULT 0,
  created_by     TEXT,
  created_at     REAL    NOT NULL DEFAULT (unixepoch()),
  revoked        INTEGER NOT NULL DEFAULT 0,
  revoked_at     REAL,
  download_count INTEGER NOT NULL DEFAULT 0,
  security_mode  TEXT    NOT NULL DEFAULT 'public',  -- 'public' | 'passkey' | 'approval'
  passkey_hash   TEXT,                            -- bcrypt hash; plaintext passkey is only ever returned once, at creation
  expires_at     REAL                             -- unix timestamp, NULL = never
);
```

**Table: share_access_requests** (approval-mode only)
```sql
CREATE TABLE share_access_requests (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  token           TEXT    NOT NULL,               -- FK-ish to share_links.token
  requester_name  TEXT    NOT NULL,
  requester_note  TEXT,
  status          TEXT    NOT NULL DEFAULT 'pending',  -- 'pending' | 'approved' | 'denied'
  requested_at    REAL    NOT NULL DEFAULT (unixepoch()),
  decided_at      REAL,
  decided_by      TEXT,
  max_downloads   INTEGER,                        -- how many downloads this approval grants
  downloads_used  INTEGER NOT NULL DEFAULT 0,
  access_token    TEXT    UNIQUE NOT NULL          -- stored in the visitor's cookie, re-checked on every request
);
```

---

## 🔐 Quart Routes & API

> Migrated from Flask to Quart (ASGI) — same route table below, but every handler is now an `async def` and route-registered the same way (`@app.route(...)`) since Quart mirrors Flask's decorator API. See the Changelog for the full migration writeup.

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

### Sharing Routes

Public share links let an unauthenticated visitor view/download a file or folder via an opaque token (`/shared/<token>`), never the real file path. Creation/management routes require a `readwrite` session; the `/shared/*` routes are anonymous by design (two of them — `/shared/<token>/passkey` and `/shared/<token>/request` — are also explicitly `@csrf.exempt`, since an anonymous visitor has no session-tied CSRF token to send).

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/api/share` | POST | readwrite | Create (or return existing) share link for one file/folder, with optional security mode + expiry |
| `/api/share/settings` | POST | readwrite | Edit an active share's security mode, passkey, or expiry (Manage Shared panel) |
| `/api/unshare` | POST | readwrite | Revoke the share link for one file/folder, by path |
| `/api/share/status` | GET | readwrite | Current share state for one path — populates the share modal |
| `/api/share/bulk` | POST | readwrite | Create or revoke share links for multiple paths at once |
| `/shared/<token>` | GET | None | Public landing page — download button, passkey form, or approval-request form depending on `security_mode` |
| `/shared/<token>/passkey` | POST | None | Submit a passkey attempt (`@csrf.exempt`) |
| `/shared/<token>/request` | POST | None | Submit an approval-mode access request (`@csrf.exempt`) |
| `/shared/<token>/status` | GET | None | Poll the current status of an access request (used by the auto-polling landing page) |
| `/shared/<token>/download` | GET | None | Download the shared file, or the whole shared folder as a zip |
| `/shared/<token>/browse` , `/shared/<token>/browse/<path:subpath>` | GET | None | JSON listing for the in-page folder browser (shared folders only) |
| `/shared/<token>/download-item/<path:subpath>` | GET | None | Download a single file/subfolder from inside a shared folder |
| `/shared/<token>/zip` | POST | None | Zip and download a multi-select of items from inside a shared folder |
| `/admin/shares/count` | GET | readwrite | Count of currently-active share links |
| `/admin/shares` | GET | readwrite | List of all active share links (Manage Shared → Active Shares) |
| `/admin/shares/requests` | GET | readwrite | List of pending approval requests |
| `/admin/shares/requests/stream` | GET | readwrite | SSE stream (realtime_shares.py) — live pending-count + active-shares-changed events |
| `/admin/shares/requests/<int:request_id>/approve` | POST | readwrite | Approve a pending access request |
| `/admin/shares/requests/<int:request_id>/deny` | POST | readwrite | Deny a pending access request |
| `/admin/revoke_all_shares/code` | POST | readwrite | Issue a fresh random 10-digit confirmation code for the "Revoke All" danger-zone action |
| `/admin/revoke_all_shares` | POST | readwrite | Revoke every active share link — requires the code from the endpoint above, typed back exactly |

**Create Share Request**:
```json
{
  "path": "photos/vacation.jpg",
  "security_mode": "passkey",
  "passkey": "",
  "generate_passkey": true,
  "expires_at": 1699999999.0
}
```

**Create Share Response** (passkey/plain shown only once, at creation):
```json
{
  "success": true,
  "token": "aB3xQ...",
  "share_url": "https://customdomain.com/shared/aB3xQ...",
  "name": "vacation.jpg",
  "security_mode": "passkey",
  "expires_at": 1699999999.0,
  "passkey": "4821"
}
```

**Share Status Response**:
```json
{
  "shared": true,
  "token": "aB3xQ...",
  "share_url": "https://customdomain.com/shared/aB3xQ...",
  "security_mode": "approval",
  "has_passkey": false,
  "expires_at": null,
  "download_count": 3
}
```

Security settings (`security_mode`, `passkey`, `expires_at`) are only accepted on first creation via `/api/share` — to change them on an already-shared item, use `/api/share/settings` instead, which also handles clearing a passkey when switching away from passkey mode (so switching back later doesn't silently revive the old passkey) and validates that a new `expires_at` is in the future.

---



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
  "timing": {"count": 0.034, "search": 0.005},   // 4.53: per-step seconds
  "from_index": true,
  "fallback_reason": null   // 4.52: null when the DB answered, else why os.walk was used
}
```

---

### Version History Routes

Browser access to the Version Engine (see [Version History Web UI](#version-history-web-ui-2026-09-27)). All are JSON APIs in the `/api/share/*` style — query-param or JSON-body, not path-embedded — and every one resolves its `path` through `storage.is_safe_path()` and `os.path.join(ROOT_DIR, path)` exactly like `/download`.

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/api/versions/list?path=` | GET | login (any role) | A file's version history, newest first — `{"tracked": bool, "versions": [...], "retention": {"enabled", "max", "kept"}}` (`kept` = completed rows only, matching what the engine's retention pass counts) |
| `/api/versions/download?path=&version_id=` | GET | login (any role) | Reconstruct one past version and return its bytes as an attachment — touches nothing on disk that persists |
| `/api/versions/restore` | POST | readwrite | Body `{path, version_id}` — reconstruct into `.recovered/`, never over the live file. Returns `recovered_path` + `download_url` |
| `/download/recovered/<path:recovered_rel>` | GET | login (any role) | Download a file previously restored into `.recovered/` — does its own containment check against `RECOVERED_ROOT` |
| `/api/versions/retry` | POST | readwrite | Body `{path}` — snapshot the live file right now. `{"success", "message", "version"}`; `version` is `null` when content was unchanged |
| `/api/versions/delete` | POST | readwrite | Body `{path, version_id, confirm_text}` — `confirm_text` must equal the file's basename, checked **server-side** |
| `/api/versions/clear-failed` | POST | readwrite | Body `{path}` — hard-delete that file's `failed` rows only. `{"success", "message", "removed"}` |

Every route that takes a `version_id` also verifies that version actually belongs to the `path` given (`_version_belongs_to()`), so a `version_id` from a file you can't access can't be smuggled in alongside one you can.

---

### Real-Time Stats Routes

| Route | Method | Auth | Response |
|-------|--------|------|----------|
| `/api/storage_stats_stream` | GET | Required | SSE stream: real-time stats |
| `/api/storage_stats_poll` | GET | Required | Polling fallback for storage stats |
| `/api/storage_stats_debug` | GET | None | Debug view of storage stats (no auth) |
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

**🆕 Actual current `/api/health_check` response (2026-08-23)** — the shape above no longer matches `health_check()` in app.py; it now returns:
```json
{
  "status": "ok",
  "platform": "posix",
  "has_statvfs": true,
  "root_dir": "/path/to/storage",
  "timestamp": 1693324800.5
}
```
No `version`/`database`/`file_monitor`/`search_index` fields anymore — it's a lighter-weight liveness check, not a component-status check.

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

## 🔄 Route Path Corrections & New Endpoints (2026-08-23)

The tables above were written for an earlier route layout. Verified directly against the current `app.py` (grep on `@app.route`) and confirmed as actually called from `index.js` (grep on `fetch(`). None of the tables above were deleted — use this section for the real path, and the older section for general request/response shape.

**Renamed / never matched the doc:**

| Documented as | Actually is | Notes |
|---|---|---|
| `/api/create_folder` | `/mkdir` | POST, **form-encoded** (`foldername`, `path`), not JSON. Returns JSON `{success, message}` or `{error}`. |
| `/api/rename` | `/rename` | POST, JSON body `{old_path, new_name}` (not `{path, new_name}`). Returns `{success, message, old_path, new_path, new_name}`. |
| `/api/move` (singular) | *(doesn't exist)* | There is no single-item move route — the UI always goes through `/bulk_move`, even for one item. |
| `/api/copy` (singular) | *(doesn't exist)* | Same — always `/bulk_copy`, even for one item. |
| `/api/delete` | `/delete` | POST, **form-encoded** (`target_path`), not JSON — this one still uses flash-message + redirect, not a JSON success response, unlike its sibling `/bulk_delete`. |
| `/api/bulk_copy` | `/bulk_copy` | No `/api` prefix. |
| `/api/bulk_delete` | `/bulk_delete` | No `/api` prefix. |
| `/api/bulk_move` | `/bulk_move` | No `/api` prefix. |
| `/video/<cacheKey>/<filename>` | `/hls_files/<cache_key>/master.m3u8` | Master playlist path pattern changed; also serves per-rendition playlists at `/hls_files/<cache_key>/<profile>/index.m3u8` and subtitle VTTs at `/hls_files/<cache_key>/<sub_filename>`. |
| `/segment/<segmentId>` | *(folded into `/hls_files/...`)* | Individual `.ts`/`.m4s` segments are just files under the same `/hls_files/<cache_key>/...` tree, not a separate `/segment/` route. |
| `/video_status/<cacheKey>` | `/hls_status/<cache_key>` | |
| *(missing entirely)* | `/hls_start/<path:video_path>` | GET, kicks off transcoding for a video and returns the initial status/track info — this is the actual entry point the player calls before polling `/hls_status`. |
| `/image_proxy/<path:path>` | `/image_preview/<path:path>` | Route + underlying cache-key scheme both renamed (see `_img_cache_key()`, `_img_cached_path()` in app.py). |

**New endpoints not documented anywhere above (all confirmed called from index.js unless noted):**

| Route | Method | Auth | Purpose |
|---|---|---|---|
| `/api/check_conflicts` | POST | Required | Pre-flight check before move/copy/upload — tells the UI which of a batch of destination paths already exist, so it can show the conflict-resolution dialog (`_promptOverwrite`, `_promptFolderConflict`, `_promptMoveOrCopyConflicts` in index.js) before making the actual mutating call. |
| `/api/exists` | GET | Required | `?path=...` — single-path existence check, used while auto-generating a free filename (`_findFreeName()`). |
| `/api/storage_stats` | GET | Required | One-shot (non-streaming) storage stats fetch — separate from `/api/storage_stats_stream` and `/api/storage_stats_poll`, used for the initial page-load numbers before SSE/poll takes over. |
| `/api/storage_stats_slow` | GET | Required | Slower/more thorough stats variant (exists in app.py; not currently called from index.js — likely a manual/debug endpoint). |
| `/api/assembly_status` | GET | Required | List of all in-progress chunk-assembly jobs (plural form of the per-file one below). |
| `/api/assembly_status/<file_id>` | GET | Required | Per-file assembly job status, polled by the upload queue UI. |
| `/api/protect_assembly/<file_id>` | POST | Required | Marks an in-progress assembly job as "protected" so cleanup schedulers won't reap it mid-assembly. |
| `/api/files/<path:path>` (and `/api/files/`) | GET | Required | Alternate JSON file-listing endpoint alongside the main `/<path:path>` HTML route — used where the UI wants just the JSON without a full page load. |
| `/image_preview_status/<cache_key>` | GET | Required | Polled while a WebP conversion is running, mirrors the `/hls_status` pattern for images. |
| `/image_info/<path:path>` | GET | Required | Metadata (dimensions etc.) for the image zoom/lightbox view (`_initImageZoom()`). |
| `/admin/clear_media_preview` | POST | readwrite | Clears cached HLS/image preview artifacts (admin maintenance action; distinct from `/admin/rebuild_cache` and `/admin/cleanup_chunks`). |
| `/csrf-token` | GET | None | Issues/returns the CSRF token used by `generate_csrf()`; referenced in the CSRF Protection section below by mechanism but the route itself wasn't listed in the tables. |
| `/robots.txt`, `/.well-known/security.txt`, `/sitemap.xml` | GET | None | Dynamically generated (not static files) — `security.txt` content is also manageable via `manage.sh security-txt` per the Admin Tools section. |
| `/debug/headers` | GET | None | Dumps request headers for debugging proxy/TLS header issues (see `_request_is_secure()`, `_request_via_trusted_tls()`) — dev/troubleshooting only, not called from the UI. |
| `/<path:_cors_any_path>` and `/` | OPTIONS | None | CORS preflight handler (`_cors_preflight`), paired with `_apply_cors_headers()` / `_cors_origin_allowed()` — CORS support isn't mentioned elsewhere in this doc at all. |

**Removed since the tables above were written:**

| Documented as | Actually is | Notes |
|---|---|---|
| `/pdfviewer` (GET, "PDF viewer UI") | *(route no longer exists in app.py)* | PDF preview no longer has its own page/route at all — see [Embedded PDF.js Viewer (2026-08-23)](#embedded-pdfjs-viewer-2026-08-23) just below for what replaced it. |

## 🆕 Embedded PDF.js Viewer (2026-08-23)

Undocumented until this pass — reconstructed from `index.html`, `index.js`, `app.py`'s CSP comments, and the two new static files below. This replaces the old `/pdfviewer` route entirely; there is no PDF-related backend route anymore, only static assets plus the existing authenticated `/view/<path:path>` endpoint (unchanged) that pdf.js fetches the actual bytes from.

**Why it changed**: the app's CSP sets `frame-src 'none'`, so any iframe-based viewer (the old `/pdfviewer` approach implies one) would have required loosening that directive. Merging pdf.js's official viewer UI directly into `index.html`'s own DOM avoids that — `worker-src 'self'` (already present for other reasons) is all `pdf.worker.mjs` needs.

**New assets loaded unconditionally in `index.html`'s `<head>`** (cheap enough to always load; they only do anything once `#pdfjsViewerRoot` is shown):
- `<link rel="resource" type="application/l10n" href=".../js/locale/locale.json">` — pdf.js localization data
- `css/viewer.css` — pdf.js's own stock stylesheet, merged in as-is
- `css/pdfjs-viewer-overlay.css` — this project's override/scoping layer, loaded after `viewer.css` (see below)
- `js/pdfjs-worker-init.mjs` (module script) — **must** stay ordered before `js/viewer.mjs`'s `<script>` tag; both are non-async module scripts, so the HTML spec's document-order execution guarantee is what makes this reliable
- `js/viewer.mjs` (module script) — the actual merged pdf.js viewer app; self-initializes against `#outerContainer` (inside `#pdfjsViewerRoot`) regardless of whether a PDF is open yet

**`pdfjs-worker-init.mjs` in detail**:
- Direct `GlobalWorkerOptions.workerSrc = "/static/js/pdf.worker.mjs"` assignment on import — only survives until viewer.mjs's self-init re-derives and overwrites it from its own `AppOptions` defaults, so this alone isn't durable across pdf.js updates.
- The durable fix: listens once for pdf.js's synchronous `webviewerloaded` `CustomEvent` on `document` (fired strictly before pdf.js decides what to auto-open, specifically so host pages can override `AppOptions` first) and, via `window.PDFViewerApplicationOptions`, sets `workerSrc`, `cMapUrl`, `iccUrl`, `standardFontDataUrl`, `wasmUrl`, and `imageResourcesPath` to their `/static/js/...` equivalents. All five need reasserting on every pdf.js version bump since they live inside viewer.mjs's own bundled defaults.
- Also sets `defaultUrl` to `''` in that same hook: this particular `viewer.mjs` build is a dev/test build with `AppOptions.defaultUrl` hardcoded to pdf.js's own sample PDF (`compressed.tracemonkey-pldi-09.pdf`), auto-opened whenever the page has no `?file=` param — which is always true here, since PDFs are opened via `PDFViewerApplication.open({url})` rather than a URL param. Left unfixed, this would fetch/render the sample PDF (and overwrite the tab title) on every load of `index.html`, not just when the viewer modal is actually open.
- `AppOptions` itself can't be imported/called directly from this module — it's private to viewer.mjs's own module scope, and importing it would force viewer.mjs to fully evaluate (including self-init) before this code could run, i.e. too late. `window.PDFViewerApplicationOptions` + the `webviewerloaded` hook is pdf.js's own documented integration point for this.

**`pdfjs-viewer-overlay.css` in detail**:
- Undoes two page-wide leaks from the merged `viewer.css`, which was written assuming it owns the entire document (its stock deployment is a dedicated `viewer.html` in an iframe):
  1. `:root { color-scheme: light dark; }` — `:root` always resolves to the page's real `<html>`, and `color-scheme` inherits, so this silently forced every native form control on the *whole app* (including its own checkboxes) into browser-default light/dark rendering instead of the app's intended theme. Reset to `normal` (the pre-viewer.css value) at the real root; pdf.js's intended `light dark` value is re-applied scoped to `#pdfjsViewerRoot` only.
  2. `body { margin:0; background-color:...; scrollbar-color:...; }` — also targeted the real `<body>`, not a scoped copy. Restored to this app's own background gradient/margin/scrollbar-color.
  - Both fixes work because this stylesheet is `<link>`ed after `viewer.css`, so it wins the cascade tie on the identical selectors/properties.
- Re-parents `#pdfjsViewerRoot` from `display:none` (shown only while a PDF is open) + `position:relative; flex:1; min-height:0` — a normal flex child of `.modal-content` (which is already `display:flex; flex-direction:column` with `.modal-header` first) — instead of `position:absolute; inset:0`. The old absolute-positioning approach ignored the modal header's height entirely, so pdf.js's own toolbar and the modal header occupied the same strip and fought over clicks; as a flex child it simply fills whatever space is left after the header. `position:relative` on `#pdfjsViewerRoot` also gives pdf.js's internal `#outerContainer`/`#mainContainer` (which use `position:absolute; inset:0` to fill *their* parent) the right containing block.
- `@media (max-width: 768px)` block: makes `#toolbarViewer`/`.toolbar`/`#toolbarContainer` horizontally scrollable (hidden scrollbar, touch-scrolling) instead of wrapping, shrinks toolbar button/input padding and font-size, and keeps `#toolbarViewerLeft/Middle/Right` from shrinking — mobile-only toolbar-overflow fix.

**`index.js` integration** (`openFileViewer()` / `closeFileViewer()` in the file-viewer-modal code):
- `getViewerType()`'s `'pdf'` case now hides `#fileViewerBody` and shows `#pdfjsViewerRoot` instead of writing viewer markup into the body — `#pdfjsViewerRoot` is a **sibling** of `#fileViewerBody`, not a child, so it survives the `body.innerHTML = ''` reset that runs at the top of every `openFileViewer()` call (that reset explicitly re-hides `#pdfjsViewerRoot` first, as the default state, before the switch/case runs).
- `_pdfjsReady()`: module scripts execute asynchronously, so on a cold page load `window.PDFViewerApplication` may not be attached yet by the time a user clicks a PDF. Polls every 50ms for `window.PDFViewerApplication.initializedPromise` to exist, then resolves/rejects on that promise; rejects after a 15s timeout with `"PDF viewer failed to initialize"`.
- On resolve, calls `app.open({ url: viewUrl })` where `viewUrl` is the same existing `/view/<path>` URL already used for images/video/audio/text — no new backend endpoint was needed for this feature.
- `app.setTitle` is stubbed to a no-op immediately before `open()`. Reasoning (per the inline comment): the old iframe-based viewer never touched the real page title (iframes have an isolated `document.title`), but now that pdf.js shares this page's actual DOM, its normal `setTitle()` calls (on open, and again once the PDF's embedded metadata loads) would directly overwrite the app's own live connection-status title indicator (which continuously strips/re-adds an emoji prefix on `document.title` elsewhere in index.js), corrupting it until a full reload.
- `_pdfViewerPrevTitle`: snapshots `document.title` right before `open()` is called and restores it both in `closeFileViewer()` and in the `.catch()` error path (viewer failed to initialize) — so the pre-PDF title is never permanently lost even on failure.
- Error path: if `_pdfjsReady()` or `app.open()` rejects, `#pdfjsViewerRoot` is hidden, `#fileViewerBody` is shown again, the title is restored, and the body shows a `viewer-text-loading`-styled error message with the caught error text (escaped).
- `closeFileViewer()` handles `#pdfjsViewerRoot` as a separate cleanup step from the rest of the modal teardown (again, because it's a sibling of `#fileViewerBody`, not covered by that element's own `innerHTML` reset): hides it, best-effort calls `window.PDFViewerApplication.close()` if present, and restores `_pdfViewerPrevTitle` if set.

**Cross-reference**: `app.py`'s `Integrity-Policy-Report-Only` comment block (see [Authentication & Sessions](#-authentication--sessions) area of app.py, not this doc) notes that `viewer.mjs` does not yet have a computed SRI `integrity` attribute in `index.html`, unlike `login.js`/`404.js` — called out there as a blocker before that header can move from report-only to enforcing.

**⚠️ Regression found in the 2026-08-28 edit of `pdfjs-viewer-overlay.css`**: the file's own comment block above the `body` rule states, in bold, that `body`'s background is "left unset on purpose" because `index.css` paints the page background exclusively via `body::before`/`body::after` (so it can be sized to `--doc-height` instead of clipping to one viewport — see [index.css's own comment](#-media-handling) on this same layering). The current `body` rule contradicts that comment directly:
```css
body {
    margin: 0;
    padding: 0;
    scrollbar-color: auto;
    background-color: #1e3c72;   /* contradicts the comment immediately above this rule */
}
```
`#1e3c72` is the exact same color `index.css` already sets on `body::before` — so this isn't a new color choice, it's that value copied one selector too high. Because this file `<link>`s after `index.css` and wins the cascade tie on `body`, it now paints a second, static copy of the page background directly on `<body>` any time the pdf.js assets are loaded (i.e. on every page load, since they're loaded unconditionally per the "New assets" list above) — competing with the properly `--doc-height`-sized, animated `body::before`/`body::after` layers underneath it. This was very likely an accidental copy-paste while editing the surrounding rule, not an intentional design change, since it directly reverses what the adjacent comment documents. Flagging here rather than silently "fixing" the docs to match: recommend either deleting the `background-color` line to match the stated intent, or updating the comment if the flat background turns out to be wanted after all.

**404.css** (undocumented, unrelated to the PDF viewer but found in the same file-review pass): a `@media (max-height: 700px)` block was added — shrinks `.error-container` padding, `.error-icon` size/margin, `.error-title`/`.error-subtitle` size/margin, and `.error-details` spacing on short viewports (small/laptop monitors), so the 404 card is less likely to need scrolling on those screens. Complements the existing `@media (max-width: 480px)` block, which handles narrow-but-tall (mobile) instead.

---

## 🆕 video-skin-overrides.css & the Inline-Style CSP Cleanup (2026-08-28)

**Where it's used**: the HLS video player (video.js + media-chrome, mounted via `_mountHlsPlayer()`) renders its controls inside a `<video-skin>` custom element, which uses a shadow root — CSS in the main document can't reach inside it, so any override has to be injected directly into that shadow root at mount time. `_injectMobileSpeedHide(playerEl)` in `index.js` does this, called from both HLS mount call sites.

**What changed**: `_injectMobileSpeedHide()` previously built its override rules as inline `<style>` elements (template literals) and appended them straight into the shadow root. Once this project's CSP tightened `style-src-elem` to `'self'` (no `'unsafe-inline'`), the browser started silently dropping both of those injected `<style>` blocks — no console error a casual test would necessarily catch, just the rules quietly not applying. The fix: the same two rules now live in a new external, same-origin stylesheet, `static/css/video-skin-overrides.css`, `<link>`ed into the shadow root instead of built inline:

```js
const HREF = '/static/css/video-skin-overrides.css';
function _addLinkOnce(root) {
    if (!root || root.querySelector('link[data-skin-overrides]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = HREF;
    link.setAttribute('data-skin-overrides', '1');
    root.appendChild(link);
}
```
`<link>` elements are governed by `style-src-elem` too, but a same-origin stylesheet URL satisfies `'self'` directly — no `sha256-...` hash to compute or keep in sync with the file's contents. `_addLinkOnce()` guards against appending the `<link>` twice; the shadow root isn't guaranteed to exist yet at call time, so the function polls every 100ms (up to 40 attempts / 4s) for `playerEl.querySelector('video-skin')` (or, as a fallback, `playerEl.shadowRoot`'s own `video-skin` child) to appear before attaching.

**`video-skin-overrides.css` contents**:
- `@media (max-width: 600px)`: hides `.media-button--playback-rate` / `media-playback-rate-button` — the same mobile playback-speed-button hide this function's docstring already described.
- `::cue`: makes the caption background fully transparent and adds a black multi-directional `text-shadow` outline around white caption text, instead of relying on the browser's default caption box — this rule is new; it wasn't present in any inline injection previously, so this is additional caption-readability styling introduced alongside the CSP fix, not just a straight port of old behavior.

**`app.py` CSP comments updated to match**: the block documenting `_INLINE_STYLE_ELEMENT_HASHES` (SHA-256 hashes for inline `<style>` *elements*, as opposed to `_INLINE_STYLE_HASHES` for `style="..."` *attributes*) now notes that `index.js`'s `_injectMobileSpeedHide()` *and* `_initImageZoom()` both used to inject inline `<style>` elements this way; `_injectMobileSpeedHide()`'s moved to this new external stylesheet, and `_initImageZoom()`'s was separately converted to a fixed rule in the main stylesheet (`index.css`) — so `style-src-elem 'self'` alone now covers both, and the two hashes still listed in `_INLINE_STYLE_ELEMENT_HASHES` belong only to the vendored video.js/media-chrome bundle's own minified shadow-DOM style injections (functions `Bt`/`Ln`), which aren't this project's code to rewrite.

---

## �🔐 Authentication & Sessions

### Login Flow

```
1. User submits POST /login {username, password}
   ↓
2. RateLimiter checks IP address (via shared `get_client_ip()` — see 2026-09-23 sync note above: trusts `CF-Connecting-IP` over `X-Forwarded-For` behind the Cloudflare Tunnel deployment)
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
async def validate_session():
    # Quart before_request hooks are coroutines — this one was the single
    # hold-out sync function missed by two earlier migration passes (found
    # via an AST sweep for sync functions under route-like decorators).
    if request.path.startswith('/api/'):
        # Public endpoints: health_check, speedtest
        if request.path in PUBLIC_ENDPOINTS:
            return None
        # Verify session valid
        if not session.get('logged_in'):
            return _lean_redirect(url_for('login'), code=302)
        # Token rotation check: session['server_token'] must match current DB token
        if session['server_token'] != db.get_server_token():
            session.clear()  # invalidated by logout-all
            return _lean_redirect(url_for('login', reason='session_expired'), code=301)
```

`_lean_redirect()` is a small helper that returns an empty-body `Response` with just the `Location` header set — Quart's default `redirect()` includes an HTML fallback-link body that's harmless functionally but was large enough to trip a ZAP "Big Redirect Detected" finding on the two 301 redirects inside this hook (see Changelog). `login_required`, elsewhere in app.py, is unrelated and still uses Quart's normal `redirect()` — it defaults to 302 and wasn't what ZAP flagged.

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

### CSRF Protection

`quart-wtf` (the natural Flask-WTF equivalent) turned out unusable here: its only release hard-pins `quart<0.19` → `werkzeug~=2.3`, incompatible with the rest of the ASGI stack. Instead, app.py has a small hand-rolled, session-tied `CSRFProtect` implementation.

- **`GET /csrf-token`**: JSON endpoint returning a fresh token tied to the current session.
- **Frontend fetch-wrapper** (index.js): auto-refreshes the token and retries once on a 400 CSRF failure, so a stale token (e.g. after a long-idle tab) doesn't surface as a user-facing error.
- **`/bulk-download`'s real `<form>.submit()` POST** bypasses the fetch wrapper entirely (it's a native form submission, not `fetch()`) — this needed its own explicit fix to include the token.
- **Anonymous share routes are exempted**: `/shared/<token>/passkey` and `/shared/<token>/request` are decorated `@csrf.exempt` — an anonymous visitor has no session-tied CSRF token to send, and without the exemption every visitor POST 400'd with "CSRF token missing" before ever reaching the database (this was the root cause of an earlier "pending access requests aren't being received" report).
- **`templates/login.html`** (documented here for the first time — previously only `login.js`'s function names were listed, not the markup itself): a plain server-rendered `<form method="post">` with the CSRF token as a `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`, username/password fields, and Jinja's `get_flashed_messages()` rendered into a `.flash-messages` block for login errors (e.g. the rate-limit/bad-credentials cases `login()` returns with a 429/401 status — see the Login Flow diagram above). Also sets `<meta name="robots" content="noindex, nofollow">` and loads `login.js` via a `<script>` tag with a computed `integrity` (SRI) hash — matching the note elsewhere in this doc that `login.js`/`404.js` already have SRI hashes while `viewer.mjs` doesn't yet.

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

**4.53 note — handlers can skip the indexes:** `on_created`, `on_deleted` and `on_moved` return early while `monitor._pending_reconcile` is set (bulk-operation settle window) and when the reconcile epoch changed, and those returns happen before the `file_index_manager` / `search_index_manager` calls further down. The settle / 15-minute / post-startup `_full_walk()` repairs counters, `dir_info` and the file index (`build_from_walk`) and — since 4.53 — the search index (`search_index_manager.reconcile_from_walk(direct_entries)`, same data). Before 4.53 the search index had no such repair, which is how a moved folder stayed indexed under its old path. The code sample below is illustrative pseudocode, not the real handler.

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
const sse = new EventSource('/api/storage_stats_stream')
// Note: the endpoint is authenticated (session cookie sent automatically by
// EventSource for same-origin requests) — /api/storage_stats_poll is the
// fallback used if the stream connection can't be established.

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

### Server-Sent Events (realtime_shares.py)

Deliberately mirrors `realtime_stats.py`'s `StorageStatsEventManager`/`storage_stats_sse` pattern exactly — same per-client `asyncio.Queue` broadcast model, same `loop.call_soon_threadsafe` cross-thread handoff (the loop reference is captured lazily on first client connect, always on the event-loop thread), same async-generator streaming response — rather than inventing a second approach that behaves differently under the same server.

Two event kinds, both admin-only (served from `/admin/shares/requests/stream`):
- **`share_requests_update`**: pushed whenever a share request is created/approved/denied — carries the current `pending_count` so the Manage Shared badge redraws instantly. `reason` (`created`/`approved`/`denied`) is informational only.
- **`active_shares_changed`**: pushed whenever a share is auto-revoked for being past `expires_at` — either the periodic sweep (`start_expired_share_cleanup_scheduler()`, see Startup Order) or a lazy revoke-on-read triggered by an admin or a visitor hitting an expired link. Carries no share data, just a nudge — the client refetches. This is what makes expiry removal in Active Shares not depend on a client-side `setTimeout` (unreliable — mobile browsers throttle/suspend those in backgrounded tabs).

A ~15s ping keeps proxies/load balancers from timing out the idle SSE connection, same as `realtime_stats.py`'s ~10s ping.

---

## 🗂️ Directory Listing & Caching

### Two-Tier Listing Strategy

**Tier 1: Cached Folders (>80 entries)**

```python
def storage.list_dir(path):
  file_index_manager = _get_file_index_manager()
  
  if file_index_manager.is_indexed(path):
    # O(1) instant return
    return file_index_manager.get_entries(path)
  
  # First time: scan + cache if exceeds threshold
  entries = os.scandir(path)  # live filesystem
  
  if len(entries) > 80:
    file_index_manager.update_folder(path, abs_path)  # re-scans just this folder, caches if > THRESHOLD
    # in memory only — update_folder() does not save(); the file on disk is rewritten by build_from_walk() and revalidated on load
  
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
  ├─ if file_index.is_indexed("photos"):
  │  └─ file_index.update_folder("photos", abs_path)  # re-scans the whole folder, O(direct entries)
  ├─ Update parent dir_info counters
  └─ Update grandparent dir_info counters (recursive)
```

**Folder Crosses Threshold**:
```
"large_folder" now has 81 entries
  ↓
on_created("large_folder/newfile.txt")
  └─ file_index.update_folder("large_folder", abs_path)
     └─ re-scans; count > THRESHOLD (80) → added to the in-memory index (the file on disk follows at the next walk)
        (the reverse also happens: update_folder() evicts a folder from the
        index once its count drops back to ≤ THRESHOLD)
```

**Performance Result**:
- 1000-file folder: <1ms response (cached)
- 100-file folder: <50ms response (live scan)
- Move between folders: incremental index update

**Other lifecycle methods**: `build_from_walk()` runs right after every `file_monitor` full walk (initial, settle and 15-minute): since 4.58 the walk only picks the candidate folders (> THRESHOLD) and each is re-read from disk before it is stored, so walk data that is minutes old is never trusted (saves once). `remove_folder()` prunes a folder and all its descendants from the index when a directory is deleted. `rename_folder()` migrates every affected key when a folder is renamed/moved, rather than re-scanning from scratch.

---

## 🔍 Full-Text Search

### Dual-Engine Architecture

Verified against `search_index.py` at 4.43. Two tables, both filled by the crawler and the watchdog hooks:

```sql
-- Always present. Plain table: COUNT(*), ext filter, and short-query LIKE.
CREATE TABLE files_meta (
  rel_path   TEXT PRIMARY KEY,
  name_lower TEXT NOT NULL,
  ext_lower  TEXT NOT NULL DEFAULT '',
  is_dir     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_meta_ext_lower  ON files_meta(ext_lower, is_dir);
CREATE INDEX idx_meta_name_lower ON files_meta(name_lower);

-- FTS5 mode (SQLite >= 3.34): name substring MATCH for queries of 3+ characters.
CREATE VIRTUAL TABLE files USING fts5(name, rel_path, is_dir, parent_rel, tokenize='trigram');

-- No-FTS5 mode: `files` is a plain table instead, and files_meta LIKE does all the work.
```

**Which table answers what (`_db_search`, `count`):**
- Name query, 3+ characters, FTS5 available → `files MATCH '"query"'` (quoted phrase; with `ext` it JOINs `files_meta` on `rel_path` for `ext_lower IN (...)`). Note: `MATCH` on `files` covers ALL columns, including `rel_path`/`parent_rel`, not only the name.
- Name query, **1–2 characters** (4.43) → `files_meta.name_lower LIKE ? ESCAPE '\'` with a `%…%` pattern built by `_like_contains()`. The trigram index cannot match under 3 characters (it returns zero rows silently), which was the cause of the pre-4.43 "2-char search returns nothing" bug.
- Ext only → `files_meta.ext_lower IN (...) AND is_dir = 0`.
- No FTS5 → the same `files_meta LIKE` branch for every name query.
- `count()` always uses `files_meta` (name `LIKE`, escaped), never FTS.
- All paths apply `LIMIT ? OFFSET ?` in SQL (fetching `limit + 1` to compute `has_more`). While the crawler is still building, `_walk_fallback()` (os.walk) answers instead. Since 4.52 `/api/search` runs `count()`, `search()` and `_walk_fallback()` through `asyncio.to_thread`, so a slow search no longer blocks the event loop; `_db_search()` still does one `os.stat()` per returned row (up to `limit`, default 500) for size/modified, which is slow on a busy disk (a possible fix — storing size/mtime in `files_meta` — was proposed, not implemented).

**Crawler Process** (verified against `search_index.py` at 4.53):
```
search_index_manager.start_crawler()  → daemon thread running _crawl()
├─ Read COUNT(*) of `files` (FTS) and `files_meta`, and index_state.crawl_complete
├─ Case A: crawl_complete == '1' AND files > 0 AND files_meta > 0 AND files_meta >= 0.95 * files
│     → prints "Search index: loaded from disk (files=… meta=…)", _ready = True, no crawl
│       (4.53: the marker is required — before it, a crawl interrupted by a restart left equal,
│        non-empty counts and a half-built index was trusted as complete)
├─ Otherwise:
│  ├─ prints "previous crawl never finished (no completion marker …) — rebuilding" when rows
│  │  exist but there is no marker (also every pre-4.53 DB, once), or "files_meta incomplete…",
│  │  or "fresh crawl starting…" for an empty DB
│  ├─ DELETE FROM files, files_meta, index_state first (index is empty/unreliable until it ends)
│  ├─ os.walk(ROOT_DIR), one batched insert per directory, hidden entries skipped
│  ├─ 10 ms sleep per directory (12,131 dirs ≈ 2 min of sleep alone on the owner's tree)
│  ├─ progress log every 5,000 dirs
│  ├─ at the very end: INSERT index_state crawl_complete='1' (+ crawl_rows), then _ready = True
│  └─ prints "Search index ready: N dirs + M files indexed in Xs"
├─ Crawler error → prints "Search index crawler error", _ready stays False for the process lifetime
├─ Whenever _ready becomes True: _ensure_warmer() starts the keep-warm thread (see below)
└─ While _ready is False: search() uses _walk_fallback() (os.walk) and sets
   _last_fallback_reason = "index not ready (crawler still running or failed)"
   (a DB query exception also falls back, reason "index query error: …")
```

**Keeping the index correct after the crawl (4.53):** live changes arrive through the watchdog hooks (`add`, `remove`, `remove_tree`, `rename_tree` called from `InstantFileEventHandler`). Those hooks are skipped while a bulk-operation settle is pending and never see offline changes, so every `FileSystemMonitor._full_walk()` (post-startup, settle and 15-minute reconcile) now ends by calling `search_index_manager.reconcile_from_walk(direct_entries)` — it diffs the walk against `files_meta`, deletes stale rows and inserts missing ones (guards: no-op until `_ready`, empty walk ignored, ≤ 5,000 changes re-checked on disk, refuses to delete > max(2,000, 25%) of the index). A keep-warm thread re-reads `search_index.db` (+`-wal`) every `_WARM_INTERVAL_SECS` (600 s) so the OS file cache holds it (the DB is ~220 MB on a spinning disk; each search opens a new SQLite connection with an 8 MB page cache). (The read-only `check_search_index.py` was deleted in 4.55; after a crawl the `Search index ready: N dirs + M files indexed` log line is the quick size check.)

**Diagnosing a slow deep search (4.52):** open the browser console on a slow search and read the `✅ Deep search results:` object. `from_index: false` → look at `fallback_reason` (`index not ready…` = the crawler has not finished since the last restart; check the server console for `loaded from disk` / `fresh crawl starting…` / `files_meta incomplete…` / `Search index ready … in Ns`). `from_index: true` and a small `search_time` while the page still waited → the server was fast; look for `🚨 EVENT LOOP BLOCKED` stacks in the server console (another sync handler on the event loop) and `net::ERR_HTTP2_PING_FAILED`. `from_index: true` with a large `search_time` → since 4.53 read `timing: {count, search}` in the same object (and the `⏱️  Slow search` line in the server console) to see whether the offset-0 `count()` scan of `files_meta` or the results query is slow (typically a cold OS cache of `search_index.db` on the HDD). `total_count` > 0 but no results → look for `⚠️  Search: dropped …` lines (index row whose path no longer exists: stale index) and check the `Search index ready: N dirs + M files` log line against the real tree — `check_search_index.py` was removed in 4.55.

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

**Query Endpoint** (`GET /api/search`, `search_files()` in `app.py`; `@login_required`, no per-user path filtering):
```
GET /api/search?q=mountain&ext=csv,txt&offset=0&limit=50     (limit default 500, max 1000)

Response:
{
  "results": [
    {"name": "mountain_data.csv", "path": "data/mountain_data.csv", "type": "CSV",
     "is_dir": false, "size": 1234, "modified": "2026-09-30 10:00:00", "match_type": "name"}
  ],
  "query": "mountain", "ext_filter": ["csv", "txt"],
  "total_found": 50, "total_count": 237,   // total_count only on offset=0, from count()
  "offset": 0, "limit": 50, "has_more": true,
  "search_time": 0.042, "from_index": true,
  "timing": {"count": 0.034, "search": 0.005},   // 4.53: count = total_count query, search = results query
  "fallback_reason": null     // 4.52: null when served from the index; otherwise the reason (see Crawler Process)
}
```
Empty `q` with no `ext` returns `{"results": [], "query": "", "has_more": false, "offset": 0}`.

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
  "versions_path": "C:\\Server\\secure\\versions",
  "platform": "windows",
  "set_at": 1695475200.5
}
```

🆕 (2026-09-25) `versions_path` — the Version Engine's content-addressed object/chunk store, resolved via `paths.get_versions_dir()`/`set_versions_dir()`/`reset_versions_dir()`, mirroring `db_path`/`cache_path` exactly (merge-safe `_save()`, auto-appended `versions` subfolder). See [Version Engine](#version-engine-file-versioning-2026-09-25).

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

**Notes on the sample above**: the values are illustrative. Today's in-code defaults are `PERMANENT_SESSION_LIFETIME=31536000` (365 days), `HLS_MIN_SIZE=50 MB` and `IMG_COMPRESS_MIN_SIZE=1 MB`. The real file also holds `ENABLE_SEARCH_INDEX`, all protocol keys, the `VERSION_*` keys and a `configured_at` timestamp. **Precedence:** `load_server_config()` runs at the bottom of `config.py` on every import, so any key present in `server_config.json` overrides the constant written in `config.py`. Change it with `python config.py` or by editing the JSON, not the constant. The file lives next to `config.py` (`_HERE`/`_SERVER_CONFIG_FILE`), not in the CWD. Not saved there: `ALLOWED_EXTENSIONS` (code-only) and the directory settings (`ROOT_DIR`, cache dirs, `VERSION_STORAGE_DIR`), which come from `storage_config.json`. Full per-setting reference: `CONFIG_PY_REFERENCE.md`.

**Feature Toggles Explained**:
- `ENABLE_FFMPEG=True`: HLS transcoding enabled; if ffmpeg missing → graceful fallback (raw video)
- `ENABLE_LIBVIPS=True`: WebP compression enabled; if libvips missing → graceful fallback (raw image)
- `ENABLE_SEARCH_INDEX=True`: FTS5 search; if disabled → full folder scans (slower)

🆕 (2026-09-25) **`VERSION_*` settings** (26 keys saved, all in `server_config.json` alongside the above — no separate `version_config.json`): `VERSION_ENGINE_ENABLED` (master switch), `VERSION_STORAGE_DIR` (derived from `storage_config.json`'s `versions_path`, **not** a saved key)/`VERSION_DB_FILENAME`, `VERSION_SMALL_FILE_THRESHOLD`/`VERSION_CHUNK_SIZE`/`VERSION_CHUNKING_ALGORITHM` (chunk size is intentionally unrelated to the upload `CHUNK_SIZE` above — verified independent, see [Version Engine](#version-engine-file-versioning-2026-09-25)), `VERSION_WORKER_COUNT` (default 1)/`VERSION_MAX_CONCURRENT_SNAPSHOTS` (default 2), `VERSION_WATCH_ENABLED`/`VERSION_SCAN_ENABLED`/`VERSION_SCAN_INTERVAL`, the five tracking-scope lists (`VERSION_TRACK_FILES`/`_DIRECTORIES`/`_ROOTS`/`_ALL_FILES`, `VERSION_EXCLUDE_DIRECTORIES`/`_PATTERNS` — every list defaults **empty**, nothing is versioned until explicitly added), `VERSION_RETENTION_ENABLED`/`_MAX_VERSIONS`, `VERSION_GC_ENABLED`/`_GC_GRACE_PERIOD`, `VERSION_RETRY_COUNT`/`_RETRY_DELAY`, `VERSION_COMPRESSION_ENABLED`, `VERSION_FOLLOW_SYMLINKS`, `VERSION_ALLOW_RESTORE_OVERWRITE` (default `False`), `VERSION_SHUTDOWN_TIMEOUT`. Configured via `main_configuration_menu()`'s new "Version History / Version Engine" section — single-value settings use the existing `configure_db_path()`-style single-prompt pattern; the five list settings get their own view/add/remove/clear sub-menu (`configure_version_tracking()`), since nothing else in `config.py` handles a list-value setting. The engine-settings menu only exposes the master switch, small-file threshold, chunk size, worker count and the watcher/scanner/retention/GC/restore-overwrite/symlink toggles; `VERSION_SCAN_INTERVAL`, `VERSION_MAX_VERSIONS`, `VERSION_GC_GRACE_PERIOD`, `VERSION_MAX_CONCURRENT_SNAPSHOTS`, `VERSION_RETRY_*`, `VERSION_COMPRESSION_ENABLED` and `VERSION_SHUTDOWN_TIMEOUT` are edited in `server_config.json` (or `config.py`).

---

## 🔐 Protocol Servers (WebDAV / SFTP / FTP / SMB)

### Overview

Four additional servers start alongside the Quart app, launched by `protocol_manager.start_all()` (called from both `dev_server.py` and `prod_server.py` after `from app import app`). All four share the same authentication database (`database.db`) and role system (`readwrite` / `readonly`).

🆕 **(2026-09-09)** WebDAV now runs as its own isolated OS **process** rather than a background thread — see [WebDAV Process Isolation, Watchdog & restart-webdav](#webdav-process-isolation-watchdog-restart-webdav-2026-09-09) below. SFTP/FTP/SMB are unchanged, still threads.

SMB is architecturally different from the other three: it defaults to **disabled** (`SMB_ENABLED = False`) even with `impacket` installed, because port 445 needs a one-time, human-run machine setup (`smb_setup.py`) before it's actually usable — see its own section below.

### New Files

| File | Purpose |
|------|---------|
| `protocol_manager.py` | Imports and starts all four protocol servers; prints startup summary. 🆕 (2026-09-09) Also supervises WebDAV's subprocess (spawn, watchdog, `restart_webdav()`) |
| `hypercorn_ssl_fix.py` | 🆕 (2026-09-09) Patches a real, still-open Hypercorn bug (`TCPServer._close()` doesn't catch `TimeoutError`; asyncio's default 30s SSL-shutdown wait has no cap) — see Troubleshooting. Applied by both `prod_server.py` and `webdav_server.py`, since each runs its own separate Hypercorn instance. 🆕 (2026-09-24) Also catches teardown-time `OSError`/`ssl.SSLError` and logs it as one IP-tagged line (peer read before close); own logger fixed to `logging_setup.get_logger("ssl_fix")` |
| `webdav_server.py` | wsgidav WSGI app with auth cache, role middleware, HTTP+HTTPS, cert serving, 🆕 (2026-09-24) audit logging — bridged onto Hypercorn via `asgiref.WsgiToAsgi` (no longer waitress/cheroot for serving; see Changelog) |
| `sftp_server.py` | Paramiko SSH accept loop, chrooted SFTPServerInterface |
| `ftp_server.py` | pyftpdlib with standalone CloudinatorAuthorizer (no Windows LogonUser) |
| `ssl_cert.py` | Self-signed RSA cert generator; embeds all local IPs as SANs |
| `smb_server.py` | impacket SimpleSMBServer — auth, Tree Connect role enforcement, Windows file-locking fixes |
| `smb_setup.py` | Standalone one-time setup tool (never auto-run) — Windows/Linux/Android, per-platform |
| `lanman_guard.py` | Small state-tracking library shared by smb_setup.py (writer) and smb_server.py (reader) |
| `kick_sessions.py` | Standalone access-revocation tool for security incidents |

### Port Assignments

| Protocol | Port | Notes |
|----------|------|-------|
| Web UI (Quart/Hypercorn) | 5000 | Now also speaks HTTP/2 and HTTP/3, not just HTTP/1.1 |
| WebDAV HTTP | 8080 | Off by default (`WEBDAV_ENABLED=False`); only listens if HTTPS is disabled or its cert can't be prepared. Native drive mapping needs the `BasicAuthLevel=2` registry edit on Windows |
| WebDAV HTTPS | 8443 | Preferred; no registry edit; requires importing `db/webdav.crt` once |
| SFTP | 2222 | WinSCP / FileZilla / sshfs |
| FTP | 2121 | Explicit FTPS (AUTH TLS) by default as of 2026-08-28 — see `FTP_TLS_ENABLED`; same port, no separate implicit-FTPS port. Falls back to plaintext if TLS is disabled or `pyOpenSSL` is missing; LAN use still recommended either way |
| FTP passive data | 60000–60100 | Must be open in firewall for FTP transfers |
| SMB | 445 | Disabled by default; needs `smb_setup.py` — Windows steals the port by default |
| SMB fallback | 8445 | Used automatically until port 445 setup is done |

### WebDAV Authentication Flow

```
Request → _CertMiddleware (serves /webdav.crt unauthenticated)
        → _AuditMiddleware (🆕 2026-09-24: one AUDIT line per successful write/download,
                             plus permission_denied — outside the enforcer so it sees the enforcer's 403s)
        → _RoleEnforcerMiddleware (blocks write methods for readonly users)
        → WsgiDAVApp (handles auth via _CloudinatorDC domain controller —
                      🆕 which also logs login / login_failed with the client IP)
```

**Auth cache** (`_AuthCache`): bcrypt runs at most once per 30 seconds per user. Subsequent requests within the TTL are verified against `sha256(password)` without hitting bcrypt. This is critical because WebDAV clients re-authenticate on every request.

**`basic_auth_user` wsgidav 4.x**: Must return the **username string** on success (not `True`). Returning `True` causes wsgidav 4.x to reject the auth silently.

**`is_share_anonymous`**: Takes `(share, environ=None)` — `environ` is optional because wsgidav 4.3.x dropped it from the call site.

**Domain controller**: Must be passed as a **class** to `WsgiDAVApp`, not an instance. wsgidav 4.3.x checks `isinstance(dc, type)` and raises if given an instance.

### WebDAV Process Isolation, Watchdog & `restart-webdav` (2026-09-09)

Triggered by a real production report: cancelling a large in-flight WebDAV download could wedge the WebDAV listener badly enough that the *entire server* — main Web UI included — had to be restarted to recover, even though the main Web UI on :5000 was otherwise unaffected the whole time.

**Root cause** was two-fold — see the matching Troubleshooting entries below for the full detail:
1. A real, still-open Hypercorn bug (patched by `hypercorn_ssl_fix.py` — see below and Troubleshooting)
2. WebDAV ran as a background **thread** inside the same OS process as the main app, so a wedged WebDAV listener had no independent recovery path short of killing that whole process

**Fix — WebDAV now runs as its own OS process:**
- `webdav_server.py` gained a `_run_standalone()` entrypoint (`if __name__ == "__main__":`) — the file can now run as `python webdav_server.py`, not just be imported. It starts WebDAV, then blocks in the foreground until a shutdown signal arrives. `SIGTERM`/`SIGINT` are handled gracefully (calls `stop()`, exits code `0`); a genuine startup failure (missing dependency, port bind failure, etc.) exits code `1`. If `WEBDAV_ENABLED` and `WEBDAV_HTTPS_ENABLED` are both off, it exits `0` immediately without starting anything, treated as an intentional no-op.
- `protocol_manager.py`'s `_spawn_webdav_process()` launches this via `subprocess.Popen([sys.executable, "webdav_server.py"], cwd=<project dir>)` instead of `import webdav_server; webdav_server.start()` in-thread. SFTP/FTP/SMB are unchanged — still background threads in this same process, since they have no known equivalent issue.
- A watchdog thread (`_webdav_watchdog`) polls the subprocess: exit code `0` (config-disabled, or a graceful stop) is left stopped; any other exit code is treated as a crash and respawned automatically after a short delay.
- `protocol_manager.restart_webdav()` — force-kills and respawns the WebDAV subprocess on demand. This only works when called **from within the running server process** (it needs the in-memory `Popen` handle) — see the `manage.sh` mechanism below for how an external command achieves the same thing.
- The WebDAV subprocess's real PID is written to `.manage_pids/webdav.pid` — the same directory `manage.sh` already uses for `prod.pid`/`dev.pid` — every time it's (re)spawned, and cleared on a graceful stop.
- `stop_all()` now terminates the WebDAV subprocess (graceful `terminate()`, `wait(timeout=5)`, then `kill()` if it doesn't exit in time) in addition to signaling the SFTP/FTP/SMB threads. `status()` reports the subprocess's `process_pid`/`process_alive`.

**New `manage.sh restart-webdav` command** (also menu option **8** — utility menu options 8–18 shifted to 9–19 to make room): since `manage.sh` runs as its own separate, short-lived process, it **cannot** call `protocol_manager.restart_webdav()` directly — that function only knows about the `Popen` handle held in the *server's* memory, and a fresh Python invocation from `manage.sh` would have no idea a WebDAV process already exists (it would just launch a second one on top of the wedged one, failing to bind the port). Instead:
1. Reads the real PID from `.manage_pids/webdav.pid`
2. Signals that PID directly — graceful `kill`/`SIGTERM` first (Python's signal handling happens on the WebDAV subprocess's main thread, which stays responsive even if its Hypercorn event-loop thread is wedged, since the latter is a daemon thread and doesn't block the main thread's signal handling), escalating to `SIGKILL`/`taskkill //F` after ~5s if it doesn't exit
3. Relies on the **already-running server's own watchdog thread** to notice the exit and respawn WebDAV automatically — `manage.sh` itself never spawns the replacement
4. Polls the PID file for a few seconds afterward, confirming a *new*, different PID shows up, and reports success/failure accordingly

New `webdav_pid_file()` helper in `manage.sh`, alongside the existing `pid_file_for()`/`logpath_file_for()`. See [WebDAV Recovery (manage.sh restart-webdav)](#webdav-recovery-managesh-restart-webdav) under Admin Tools & Utilities for usage.

### WebDAV HTTPS Listener — HTTP/1.1 Only (2026-09-09)

`webdav_server.py`'s HTTPS listener's TLS ALPN changed from `["h2", "http/1.1"]` to **`["http/1.1"]` only**. Real-world WebDAV clients — Windows' native WebClient service (`mrxdav.sys`), `davfs2`, and most other OS-level WebDAV mounters — are almost universally HTTP/1.1-only implementations. If TLS negotiated `h2` with one of these (their TLS layer can claim ALPN `h2` support even when the WebDAV component itself can't actually speak HTTP/2 framing), the connection could break at the protocol level — surfacing as "SSL connection closed" rather than a clean HTTP error, and repeating as the OS driver auto-retried the mount/download. Downloads were hit hardest, since a file GET is a longer, flow-control-sensitive stream compared to a short PROPFIND.

The main Web UI's own HTTPS listener (`prod_server.py`) is **unaffected** and still advertises `h2` — it's accessed exclusively by browsers, which negotiate HTTP/2 correctly, and gains real benefit from it (see the existing SSE/HTTP-2 Troubleshooting entries).

### WebDAV Disconnect-Flood Guard (2026-09-09, second pass)

The subprocess isolation and `hypercorn_ssl_fix.py` above did **not** fully resolve the WebDAV download-cancel problem — a second, separate bug remained: cancelling a large in-progress WebDAV download (e.g. a 700MB file, cancelled ~10s in) produced a genuinely fast, continuous flood — thousands of bare `SSL connection is closed` lines with **no traceback at all** — that kept going until the remaining file had been fully (uselessly) iterated.

**Root cause, verified by reading the actual installed source of all three layers involved (not guessed):**
1. **`asyncio/sslproto.py`** (CPython stdlib) — `_SSLProtocol._write_appdata()` never raises once a connection is confirmed dead; by asyncio's own documented `Transport.write()` contract, writes are fire-and-forget. Past an internal 5-write grace threshold (`LOG_THRESHOLD_FOR_CONNLOST_WRITES`), it just logs `logger.warning('SSL connection is closed')` and silently no-ops — for every remaining write, forever. This is the exact source of the bare, traceback-free message.
2. **`asgiref` 3.12.1**'s `WsgiToAsgiInstance.run_wsgi_app()` — the WSGI-response-streaming loop (`for output in wsgi_application(...): ... self.sync_send(...)`) has **no try/except** around the send call, and never checks the ASGI `receive()` channel for a disconnect signal once the request body has been read. Verified directly against asgiref's real `wsgi.py` source.
3. **wsgidav**'s `FilesystemProvider` just keeps yielding the next chunk of the file being served, with no way to know the client is gone.

Combined: nothing in this chain ever naturally stops once a client cancels — writes silently "succeed" (per point 1) and log once per chunk, for every remaining chunk of the file, as fast as it can be read from disk. For a large file cancelled early, that's thousands of lines in seconds.

**Fix — new `_DisconnectAbortMiddleware`** in `webdav_server.py`, wrapping `WsgiToAsgi(wsgi_app)` at the ASGI level (`asgi_app = _DisconnectAbortMiddleware(WsgiToAsgi(wsgi_app))` in `_start_hypercorn()`). Confirmed via Hypercorn's own `hypercorn/protocol/http_stream.py` (`await self.app_put({"type": "http.disconnect"})`) that Hypercorn DOES deliver `http.disconnect` through `receive()` once its read-side loop detects the connection is gone — the gap was that nothing was listening for it during the long response-streaming phase, since neither wsgidav nor asgiref ever call `receive()` again after the request body is read.

The middleware runs a background task that takes over polling `receive()` for `http.disconnect` **only after** it has observed (via transparently wrapping the same `receive()` calls the inner app makes) that the inner app's own request-body-read loop has completed — avoiding any race for the same message. Once disconnect is observed, the wrapped `send()` starts raising `ConnectionResetError` instead of silently succeeding, which — since asgiref's `sync_send()` call is unguarded (point 2 above) — actually propagates and breaks the WSGI response loop on the very next chunk, instead of the remaining thousands.

Verified with two isolated functional tests (extracted just the middleware class and ran it against simulated ASGI scopes, not just reasoned through): a simulated 1000-chunk download with disconnect injected at chunk 5 stopped at chunk 6 (vs. running all 1000 before the fix); a normal, non-disconnected 50-chunk request completed all 50 messages with no interference and no hang from the background watcher task.

**Follow-up (2026-09-24)**: the guard's deliberate `ConnectionResetError` used to escape uncaught and be logged by Hypercorn as `Error in ASGI Framework` — one traceback per cancelled download, and one more whenever a client hung up just after a complete response. `__call__` now swallows that one error (exact-message match on `_GUARD_MSG`) and nothing else; see [WebDAV Resilience Issues](#webdav-resilience-issues-2026-09-09) for the measurements. The flood protection itself is unchanged.

### WebDAV Audit Logging and Client-IP Attribution for TLS-Teardown Errors (2026-09-24)

Two related problems found from one log excerpt. Both are in `webdav_server.py`; nothing else was changed.

**1. WebDAV had no audit trail.** `log` was `logging.getLogger(__name__)` — `"__main__"` inside the WebDAV subprocess — with no handler and no call sites. It's now `logging_setup.get_logger("webdav")`, so lines reach the shared daily file tagged `[webdav_server]` (see the component-tag note in `logging_setup.py`). Same `user`/`action`/`path`/`ip` shape as the SFTP/FTP/SMB lines, so all four protocols grep the same way (`grep "AUDIT"`).

| Line | Level | Produced by | When |
|------|-------|-------------|------|
| `action=login role=... ip=... tls=...` | INFO | `CloudinatorDC.basic_auth_user()` → `_audit_login()` | Successful auth, **de-duplicated per (user, ip) for 300 s** (`_LOGIN_AUDIT_TTL`) — WebDAV is stateless Basic, so there is no session to log once; without this an Explorer window writes a "login" per request |
| `action=login_failed ip=...` | WARNING | same | Every bad attempt, not de-duplicated (same as FTP/SFTP) |
| `action=upload\|download\|delete\|mkdir path=... ip=...` | INFO | `_AuditMiddleware` | Only on success — upload `PUT` 200/201/204, download `GET` 200/206, delete 200/204, mkdir `MKCOL` 201 |
| `action=rename\|copy path=... -> ... ip=...` | INFO | `_AuditMiddleware` | `MOVE`/`COPY` 201/204; destination parsed from the `Destination` header (full percent-encoded URL reduced to a path) |
| `action=permission_denied method=... path=... ip=...` | WARNING | `_AuditMiddleware` | Any 403 on a write method — chiefly the readonly-role block from `_RoleEnforcerMiddleware` |

- **Deliberately not audited**: `PROPFIND`, `OPTIONS`, `HEAD`, `LOCK`, `UNLOCK`, `PROPPATCH` (browsing/lock-keepalive chatter that would bury every real event — same reasoning as `smb_server.py`'s read-open skip), directory `GET`s (path ending `/`), and 207 Multi-Status responses (a partial failure isn't a clean "it happened").
- **Downloads are logged when the response starts**, not when the last byte is sent — WSGI has no completion hook (FTP's `on_file_sent` has no equivalent here). A cancelled download still records that the user asked for the file. Windows' WebClient fetches big files as many `206` range requests; a `GET` is logged once — when un-ranged or ranged from byte `0` (`_is_first_chunk()`).
- **Paths are decoded correctly**: asgiref hands WSGI `PATH_INFO` as latin-1-decoded UTF-8 bytes (the WSGI convention), so `_request_path()` round-trips it — non-ASCII filenames log as real text, not mojibake.
- **Middleware order matters**: `_CertMiddleware` → `_AuditMiddleware` → `_RoleEnforcerMiddleware` → wsgidav. Audit must stay *outside* the enforcer or the readonly 403s (which the enforcer returns without ever reaching wsgidav) vanish from the trail; it sits inside `_CertMiddleware` so the unauthenticated `/webdav.crt` download isn't audited.
- **Audit code never breaks a request**: `_audit_login()` and `_AuditMiddleware._record()` swallow their own exceptions.
- **Where `ip=` comes from (updated 2026-09-24, later the same day)**: `_client_ip()` now mirrors the web UI's `get_client_ip()` trust chain — `CF-Connecting-IP` (from `environ["HTTP_CF_CONNECTING_IP"]`) first, then `X-Forwarded-For`, then `REMOTE_ADDR` (asgiref's fill-in from Hypercorn's ASGI `scope["client"]`, the raw TCP peer) as the final fallback. Originally shipped REMOTE_ADDR-only (see the entry directly below this one) on the assumption that WebDAV might not be tunneled — confirmed the same day that port 8443 **is** tunneled through `cloudflared` (8080 is not; see the deployment note under WebDAV Implementation Notes for why), which means every audit line was showing cloudflared's local loopback address instead of the real client for 100% of internet-facing traffic until this fix. `REMOTE_ADDR` remains correct, and is still used, for genuinely direct access (LAN/Tailscale). **Verification note**: unit-tested `_client_ip()` in isolation against six scenarios (tunneled-with-CF-header, generic-proxy-with-XFF, direct-LAN, empty environ, `None` environ, blank-CF-header-falls-through) — all correct. Did **not** get a full live-server round-trip for this specific fix: a bare, unmodified `hypercorn.serve()` call failed to bind a listening socket in the sandbox used for this pass (reproduced with zero project code involved — an environment issue, not a regression in this file). The surrounding pipeline (asgiref's WSGI environ population, `_AuditMiddleware` calling this exact function) was already proven working end-to-end in the 2026-09-24 pass documented below; this change only swaps which `environ` keys `_client_ip()` reads.
- **Original 2026-09-24 finding (superseded by the fix above, kept for history)**: `ip=` came from `REMOTE_ADDR` only — correct for a directly exposed listener, but behind any proxy/tunnel the logged IP would be the proxy's. Flagged then as an open question (“nothing in this repo's docs says WebDAV is tunneled; if it ever is…”) — answered and fixed the same day once confirmed.

**2. The anonymous `Unhandled exception in client_connected_cb` traceback.** Same first line as the older `TimeoutError: SSL shutdown timed out` entry in [WebDAV Resilience Issues](#webdav-resilience-issues-2026-09-09) but a **different cause**:
- Hypercorn's `TCPServer.run()` ends in `finally: await self._close()`, which awaits `StreamWriter.wait_closed()`. When the TLS shutdown fails with `ssl.SSLError: [SSL: APPLICATION_DATA_AFTER_CLOSE_NOTIFY]` — the client sent data after its own TLS `close_notify` (which client software does this has **not** been identified — the IP now in the log line is how to find out) — the error escapes through `client_connected_cb`. Stock Hypercorn 0.18.0's `_close()` doesn't catch it (its except-list is `BrokenPipeError`/`ConnectionAbortedError`/`ConnectionResetError`/`RuntimeError`/`CancelledError`), and neither did `hypercorn_ssl_fix.py`'s patched `_close()` until this pass — confirmed by reading the file: it adds only `TimeoutError` (and the 2 s cap) to that list. It's a teardown-time blip — the connection is already closing, nothing is lost — but it prints as a 20-line crash.
- **Why it had no IP**: asyncio reports it through the `"asyncio"` logger (not a child of `"cloudinatorftp"`, so it falls through to Python's last-resort handler → stderr → `_TeeStream` → the `[STDERR]` tag in the log) with only `transport: <asyncio.sslproto._SSLProtocolTransport object at 0x...>`. By the time asyncio's exception handler runs, `transport.get_extra_info("peername")` returns **`None`** — verified directly with a probe server that captured `peername` at connect time (present) and again inside `loop.set_exception_handler()` (gone). Consistent with `_SSLProtocol._get_extra_info()` falling through to its default once its underlying transport is cleared on connection loss. So no logging configuration can recover the IP after the fact; it has to be read *before* teardown.
- **Fix — in `hypercorn_ssl_fix.py`'s `_patched_close()`**, so it covers every Hypercorn instance that applies the patch: the WebDAV process **and** the main `prod_server.py` listener. `_patched_close()` now (1) reads `writer.get_extra_info("peername")` at the very top, while the connection is still open, and (2) has a new `except OSError` clause after the existing `ConnectionError`/`TimeoutError` one (`ssl.SSLError` is an `OSError` subclass but not a `ConnectionError`, so it wasn't caught before). A known-benign `APPLICATION_DATA_AFTER_CLOSE_NOTIFY` becomes one INFO line: `client <ip> sent data after TLS close_notify (harmless teardown error, connection already closing)`; any other `OSError` becomes one WARNING line with the type and message. Logged **once per connection** via a `_ssl_fix_logged` flag on the `TCPServer` instance — `_close()` can run twice for one connection (from `protocol_send(Closed)` and from `run()`'s `finally`) and `wait_closed()` re-raises the same stored exception each time; without the flag that would double-log. Anything that isn't an `OSError` still propagates, so real bugs still surface. The module's logger also changed from a plain `logging.getLogger(__name__)` (no handler — its own startup INFO line was silently dropped) to `logging_setup.get_logger("ssl_fix")`, so **a new `hypercorn_ssl_fix: patched TCPServer._close() …` line now appears in the log at every start** — that's expected, not a regression.
- **Upgrade check**: this still monkeypatches `TCPServer._close()` wholesale, so re-check it against Hypercorn's source after any upgrade, exactly as the module docstring already says — if Hypercorn changes `_close()`'s shape the patch no-ops (with a warning) and the anonymous traceback returns.
- **Main listener**: `prod_server.py` calls the same `hypercorn_ssl_fix.apply()`, so it gets the same handling — but **this was exercised through the WebDAV listener only** (same `TCPServer` class), not through `prod_server.py` itself, and behind the Cloudflare Tunnel the peer it logs is `cloudflared`'s local address, not the real client (see the deployment caveat above; only direct LAN/Tailscale connections show a real IP there).

**Verification** (Python 3.12.3, Hypercorn 0.18.0, asgiref 3.12.1, wsgidav 4.3.5, the real `logging_setup.py`, and — for the teardown fix — the **real, uploaded `hypercorn_ssl_fix.py`**; real HTTPS requests against a real running `webdav_server.py` process, not simulated middleware calls): `MKCOL`, `PUT` of a file with a space and non-ASCII characters in its name, `GET`, ranged `GET` (`bytes=0-4` logged once, `bytes=5-9` not), `COPY`, `MOVE`, `DELETE`, a bad-password login, and a readonly user's `GET` (allowed) vs `PUT`/`DELETE` (403) — 13 audit lines in one run, correct users/paths/IPs, unauthenticated first-contact 401s and `PROPFIND` correctly absent. For the teardown error: the **original** `webdav_server.py` + original `hypercorn_ssl_fix.py` reproduced the exact reported lines (`Unhandled exception in client_connected_cb` / `transport: <asyncio.sslproto._SSLProtocolTransport …>`) 3 out of 3 times; the patched pair produced exactly one IP-tagged line per connection (3 connections → 3 lines, no duplicates) and zero unhandled exceptions. Normal traffic produced zero teardown lines, and Hypercorn's own `Running on …` line now arrives as a normal `[INFO]` line rather than double-stamped under `[STDERR]`.

**Not verified**: (a) Windows / Python 3.14 (the production stack) — tested on Linux/3.12; (b) a *real* client sending data after `close_notify` — OpenSSL won't let a normal client do that, so the identical `SSLError` was injected at asyncio's `unwrap()` call and triggered by a server-initiated close (asyncio only calls `unwrap()` when the server closes first); (c) the main listener through `prod_server.py` itself (needs `app.py`; exercised only via the shared `TCPServer` code path); (d) any proxy/tunnel path.

### SFTP Implementation Notes

- **Host key**: RSA-2048, generated once and stored at `db/sftp_host.rsa`. Back this up — regeneration breaks existing WinSCP known-hosts entries.
- **Chroot**: All SFTP paths are mapped to `ROOT_DIR` via a segment-by-segment path resolver (`_make_realpath()`), not a single `os.path.join(root, sftp_path)` call — see the Windows bug below for why. Final resolution goes through `os.path.realpath()`, with a clamp back to root if a symlink inside root points outside it.
- **Windows path-join bug (fixed)**: The original implementation called `os.path.join(root, some_sftp_path)` directly. On Windows, `ntpath.join("C:\\Server\\Files", "\\subfolder")` returns `"C:\\subfolder"` — **not** `"C:\\Server\\Files\\subfolder"` — because a drive-less absolute path (which is exactly what an SFTP client sends, since SFTP paths are POSIX-style and start with `/`) resets `ntpath.join` back to the drive root. This silently clamped every subdirectory lookup back to `ROOT_DIR` on Windows — the SFTP root itself happened to still resolve correctly by coincidence, which is why it could look fine in a quick smoke test. Fix: split the SFTP path into individual segments and join them one at a time with `os.path.join(real, seg)`, so a bare segment name (never starting with a separator) can't trigger `ntpath`'s absolute-path-reset behavior on any OS.
- **SFTPHandle**: Uses `paramiko.SFTPHandle` with `readfile`/`writefile` attributes — paramiko's default `read()`/`write()` methods use these. Do NOT monkeypatch instance attributes onto `SFTPHandle`; paramiko does not guarantee instance-attribute method dispatch.
- **`transport.accept(120)`** (raised from `30`): Required after `start_server()` to acknowledge the client's session channel. Without it, SFTP subsystem activation stalls. The original 30s window was too tight for some mobile SFTP clients (e.g. Android apps) that show "connected" immediately after auth but don't actually open the SFTP channel until the user navigates into the file browser — if that took longer than 30s, the server closed the transport first, surfacing to the client as a generic "connection closed" error. 120s gives real slack for that UI delay while still bounding a stalled/dead connection.
- **`transport.set_keepalive(30)`** (new): Called right after `start_server()`, alongside the `accept()` change above. Sends keepalive packets so an idle-but-open session (authenticated, channel open, just sitting in the client's file browser with no active transfer) isn't silently dropped by a mobile carrier's or Wi-Fi router's NAT idle timeout. Unrelated to the `accept()` timeout above — this only affects the session after the channel is already open.
- **Cipher/MAC/KEX hardening (new)**: `_harden_transport_ciphers()` is called on every `paramiko.Transport` before `start_server()`, and strips weak algorithms from `transport.get_security_options()` in place (mutating `.ciphers`/`.digests`/`.kex` is enough — no other wiring needed, since `get_security_options()` returns a live view backing the handshake). Dropped, not merely deprioritized, because none of them are needed by any client this server targets (WinSCP, FileZilla, OpenSSH sftp/sshfs all support modern alternatives):
  - **Ciphers** (`_WEAK_SSH_CIPHERS`): all CBC-mode ciphers (`3des-cbc`, `aes128/192/256-cbc`, `blowfish-cbc`, `cast128-cbc`), `arcfour`/`arcfour128`/`arcfour256` (RC4, broken), and `none`.
  - **MACs** (`_WEAK_SSH_MACS`): `hmac-md5`, `hmac-md5-96`, `hmac-sha1-96` (truncated tag weakens SHA1's own forgery-resistance margin), `hmac-sha1` (not broken as a MAC, dropped anyway since every targeted client supports `hmac-sha2-256/512`), and `none`.
  - **KEX** (`_WEAK_SSH_KEX`): all finite-field Diffie-Hellman group/group-exchange algorithms — dropped to close off the D(HE)ater DoS pattern (CVE-2002-20001, CVE-2022-40735, CVE-2024-41996), where an unauthenticated client can force expensive modular-exponentiation work on the server for almost no cost to itself. The elliptic-curve KEX variants (`curve25519-sha256@libssh.org`, `ecdh-sha2-nistp*`) aren't vulnerable to this and stay enabled.
  - Written to satisfy OpenVAS's "Weak Encryption Algorithm(s) Supported (SSH)" and "Weak MAC Algorithm(s) Supported (SSH)" findings — the same category of scanner-driven hardening as the [ZAP Security Scan Fixes](#version-42-2026-08-18) already documented for `app.py`.
- **Audit logging (new, 2026-09-24)**: `_CloudinatorSFTPInterface._audit()` logs one `SFTP AUDIT: user=... action=... path=... ip=...` line on every successful `remove()`/`rename()`/`mkdir()`/`rmdir()` and every write-mode `open()` (upload/overwrite) — previously only `PERMISSION_DENIED` cases produced any log output at all; a successful delete had zero trace. `check_auth_password()` now logs both successful and failed logins the same way. The `_SSHServer` instance gained a `client_addr` attribute, set in `_handle_connection()` right after construction (before `start_server()`), so both the login line and every per-file audit line can attribute activity to a source IP, not just a username. `log` itself changed from `logging.getLogger(__name__)` (no handler ever attached — silently went nowhere) to `logging_setup.get_logger("sftp")`.
- **Open-flags bug (found and fixed, 2026-09-24)**: `_flags_to_mode()` and the write-permission check in `open()` used to test the `flags` argument against hardcoded SSH_FXF_* wire-protocol bit values (`_FXF_READ=0x01`, `_FXF_WRITE=0x02`, `_FXF_CREAT=0x08`, `_FXF_TRUNC=0x10`) — but paramiko's `SFTPServerInterface.open()` does not receive raw wire-protocol flags. paramiko's own `SFTPServer._process()` calls `_convert_pflags()` first, translating them into Python's `os.O_*` flags (`os.O_WRONLY=1`, `os.O_RDWR=2`, `os.O_CREAT=64`, `os.O_TRUNC=512`, `os.O_APPEND=1024`) before ever calling into this file — a completely different bit layout. The collision that actually broke things: `os.O_WRONLY`'s value of `1` is the same bit as the old code's `_FXF_READ`, so a brand-new file opened for writing was misread as a read-only open, then failed with `FileNotFoundError` (the file doesn't exist yet) — surfacing to the client as a bare "No such file" on what should have been a normal upload. Existing-file overwrites were similarly broken (opened in read mode, then failed on the first write with `io.UnsupportedOperation`). Confirmed against a real paramiko client: new-file uploads failed 100% of the time before the fix. Fixed by testing the actual `os.O_*` flags via `_is_write_open()` (write-permission gate) and a rewritten `_flags_to_mode()` (mode-string derivation) that correctly distinguishes `O_RDONLY` — which is `0`, the "none of the bits are set" case, not a testable bit — from `O_WRONLY`/`O_RDWR`. Re-verified end-to-end after the fix: upload, overwrite, download, mkdir, rename, rmdir, delete, and the readonly-role write-block all confirmed working against a real paramiko client, not just read over.

### FTP Implementation Notes

- **`CloudinatorAuthorizer`**: Does NOT inherit from `DummyAuthorizer`. On Windows, `DummyAuthorizer.impersonate_user()` calls `win32security.LogonUser()`, which fails for DB-only users and blocks all file operations post-login. The standalone class has explicit no-op `impersonate_user()` and `terminate_impersonation()` methods.
- **Passive ports**: `60000–60100`. These must be open in the Windows Firewall for file transfers to work.
- **Credentials**: Same as web UI. `has_user()` queries `db.user_exists()`, `validate_authentication()` calls `db.check_login()`.
- **FTPS / explicit TLS (new, via `config.py`)**: `FTP_TLS_ENABLED` (default `True`) turns on explicit FTPS (`AUTH TLS`), reusing the same cert `ssl_cert.py` generates for WebDAV HTTPS rather than issuing a separate one. If `pyOpenSSL` isn't installed, `ftp_server.py` auto-falls back to plaintext FTP rather than failing to start. `FTP_TLS_REQUIRE_DATA` (default `True`) additionally requires the *data* channel to be TLS too, not just the control channel/credentials (which are always TLS-required whenever `FTP_TLS_ENABLED` and `pyOpenSSL` are both available) — set it `False` only to accommodate a legacy client that can't negotiate TLS on the data connection. Configurable interactively via `python config.py` → option 13 → FTP sub-menu (options 3–4).
- **Audit logging (new, 2026-09-24)**: `log` was previously `logging.getLogger(__name__)` — created, but never actually called anywhere in the file, a dead logger. Now `logging_setup.get_logger("ftp")`, and `CloudinatorFTPHandler` overrides pyftpdlib's `on_login`/`on_login_failed`/`on_file_sent`/`on_file_received` callbacks (one call per whole transfer, not per chunk) plus wraps `ftp_DELE`/`ftp_RMD`/`ftp_MKD`/`ftp_RNTO` — each calls the base-class handler first (unchanged behavior, including its own 550/250/257 responses), then checks `self._last_response` (set by every pyftpdlib `respond()` call) to confirm success before writing the `FTP AUDIT: user=... action=... path=... ip=...` line, so a denied or failed operation never produces a false "it happened" entry. This is separate from pyftpdlib's own internal `'pyftpdlib'` logger (used for its low-level protocol trace) — audit lines are written explicitly through the app's own logger rather than relying on pyftpdlib's internal logging reaching the unified log file, which it doesn't by default. Verified end-to-end against a real pyftpdlib server + `ftplib` client: upload, download, mkdir, rename, rmdir, delete, and a failed login all produced correct audit lines.

### SMB Implementation Notes

**Library choice**: `impacket.smbserver.SimpleSMBServer` is the only practical pure-Python SMB *server* library — `smbprotocol` and `pysmb` are both client-only (confirmed against their own docs; `pysmb`'s literally says "this is only a client library, it does not share files"). `impacket` is also a pentesting-toolkit component, which causes real, expected friction: Windows Defender commonly quarantines parts of it on install (`[Errno 22] Invalid argument` on `epm.py` is the signature) — needs an AV exclusion, documented in `SMB_PROTOCOL_DEPLOYMENT.md`.

**Auth — NTLM, not check_login()**: SMB uses NTLM challenge-response; the plaintext password never crosses the wire, so `db.check_login()` can't be used the way the other three protocols use it. `database.py` captures each user's NT hash (raw MD4 of the password) at `add_user()`/`update_password()` time, stored in a new `nt_hash` column, encrypted with the same Fernet key as the bcrypt hash. Users predating this feature have `nt_hash IS NULL` — `db.users_missing_nt_hash()` lists them; they need one password reset (even to the same value) before SMB accepts their login.

**Per-user read/write — Tree Connect hook, not per-share flag**: impacket's `addShare()` only supports one static read-only flag per *share*, not per-user. Fix: hook `SMB2_TREE_CONNECT` (and the SMB1 equivalent) to call impacket's real handler first, then override `connData['ConnectedShares'][tid]["read only"]` for that specific connection based on `db.get_role()`. Every existing write-check in impacket then respects it automatically — no duplicated access-control logic. Fails safe: any lookup error leaves the share read-only. Does NOT apply retroactively to an already-open Tree Connect — a role change takes effect on the next reconnect, same characteristic as a password change.

**Credential refresh — diffed, not rebuilt**: `_load_credentials()` diffs against impacket's live in-memory table every 30s rather than clearing and rebuilding it. Rebuilding wholesale would reassign every user a new UID every cycle for no reason; diffing also closed a real gap where a *deleted* user's old credential lingered forever (impacket's `addCredential()` only adds/overwrites, has no remove). All comparisons are lowercase, matching impacket's own internal key normalization (`addCredential` stores `name.lower()`) — comparing against original-case usernames silently broke the diff for any mixed-case name; found and fixed.

**Shutdown — `block_on_close` / `daemon_threads` timing matters**: `SimpleSMBServer.stop()` only calls `server_close()`, never `shutdown()` — and `server_close()` (via `socketserver.ThreadingMixIn`) joins every per-connection thread by default. A single abandoned connection (client disconnects right after a failed login) leaves its handler thread blocked forever in `socket.recv()`, hanging `stop()` indefinitely. Fix: `inner.block_on_close = False` and `inner.daemon_threads = True`, set **before** the server starts accepting connections (both are only read at the moment a connection is handled — setting them later, e.g. inside `stop()`, is too late for anything already in progress). `stop()` itself calls `shutdown()` then `server_close()` directly, bypassing `SimpleSMBServer.stop()` entirely.

**`NetBIOSTimeout` traceback suppression**: impacket's hardcoded 5-minute idle timeout fires on any connection left open and idle — completely normal, not an error — but the default `handle_error` prints a full traceback for it. `_quiet_handle_error` overrides `handle_error` to log this one specific exception quietly; anything else still gets the full traceback.

**Windows file-locking fixes (the deep one)**: MS Office's atomic save (write `.tmp`, rename over the open `.docx`) collides with two separate Windows limitations:
1. `os.rename()`/`os.remove()` raise `WinError 32` (`ERROR_SHARING_VIOLATION`) when the destination is open — impacket catches this and maps it to `STATUS_ACCESS_DENIED`, which Windows shows the user as a permissions error. Fix: patch `impacket.smbserver.os.rename`/`os.remove` to retry via `os.replace()` (rename) or a short backoff (delete, no atomic alternative exists) — **only** on `winerror==32**`; any other error (e.g. `WinError 183`, destination already exists) is re-raised untouched, so `app.py`'s own rename endpoint is unaffected.
2. Deeper cause: `os.open()` on Windows never requests `FILE_SHARE_DELETE` (confirmed via CPython's own bug tracker, `bpo-15244`, open since 2012 — an MSVC runtime limitation). Any file the server opens, even briefly, can't be renamed/deleted by anyone — including the server itself — while that handle stays open, which is exactly what breaks Office's "rename the original file to a backup" save step. Fix: replace `os.open()` inside impacket's `SMB2_CREATE` handler with `_winapi.CreateFile()` + `msvcrt.open_osfhandle()` (stdlib, no new dependency), explicitly requesting `FILE_SHARE_DELETE`. Deliberately **not** `win32file.CreateFile()` (pywin32) — that wraps its return in a `PyHANDLE` that auto-closes on garbage collection, a documented cause of random "bad file descriptor" errors under concurrent use; `_winapi.CreateFile()` returns a plain int, no such wrapper. Scoped as a **temporary swap** around the single synchronous `os.open()` call inside the CREATE hook (not a permanent patch like rename/remove) — `os.open()` is used far more pervasively by unrelated code than rename/remove, so a permanent global replacement risked misbehaving for some flag combination not audited here. One gap found and fixed in the underlying official recipe: no mapping for "no creation flags at all" (just opening an existing file) — the single most common case for a file server, apparently untested by the recipe's own author.

**Command safety net**: impacket's top-level SMB2 dispatch logs and **re-raises** any exception a command handler doesn't catch itself, which kills that connection's thread — a silent "network disconnect" from the client's side, distinct from a clean "permission error" response. Fix: wrap every registered SMB2 command so an uncaught exception is logged in full and returns `STATUS_UNSUCCESSFUL` instead of propagating. Installed **last** in the hook chain so it's outermost and also catches bugs in the other hooks above it (found genuinely useful during development — it caught two real bugs in this exact hook-wiring pattern before they shipped, see below).

**Recent hardening note**: the latest SMB revision adds Windows-specific retry behavior for delete/rename collisions and a safer file-open path for transient lock windows during Office-style save sequences. These changes are intentionally narrow and only affect the specific error class that was causing false permission reports or interrupted saves.

**Hook-wiring gotcha (found twice, worth documenting so it isn't reintroduced)**: `SMB2_NEGOTIATE`'s legacy SMB1-upgrade call path invokes its handler with **4** positional args, not the usual 3 — a fixed-arity hook signature silently breaks on that call. All hooks in this file use `(*args, **kwargs)`, never a fixed positional signature. Relatedly: stashing the "original handler" in a mutable default argument and later overwriting it via `hook.__defaults__ = (...)` breaks silently the moment a hook signature has `*args` followed by any keyword-only parameter — `__defaults__` only ever updates positional-or-keyword defaults, never keyword-only ones. Every hook here uses a plain single-element holder list (`orig_holder = [None]`, set directly at the call site) instead — no function-default mutation at all.

**Diagnostics, both opt-in via env var, never on by default**:
- `SMB_DEBUG_SIGNING=1` — traces Negotiate/Session Setup/`signSMBv2`/`signSMBv1` calls, built to confirm Windows 11 24H2's mandatory-signing requirement against impacket's (already-present, just unadvertised) signing support.
- `SMB_DEBUG_FILES=1` — logs every SMB2 CLOSE with its fd and file path, for investigating reports like `SMB2_READ: [Errno 9] Bad file descriptor` during large/server-to-server copies (impacket already catches this per-request internally and doesn't corrupt data or drop the connection — this exists to get hard evidence on the mechanism rather than guess further).
- **Audit logging (new, 2026-09-24)**: `_install_audit_logging()` hooks `SMB2_CREATE` (upload/overwrite/mkdir), `SMB2_SET_INFO` (rename), and `SMB2_CLOSE` (delete/rmdir) via the same `hookSmb2Command()` pattern as every other hook in this file, writing `SMB AUDIT: user=... action=... path=... ip=...` lines on success only — each wrapper calls the original handler first and only logs after confirming `STATUS_SUCCESS`. Installed *before* `_install_command_safety_net()` (which is installed last, wrapping everything including these new hooks, same as every other hook here). `log` itself changed from `logging.getLogger(__name__)` to `logging_setup.get_logger("smb")`, so both this and the pre-existing `_auth_callback()` login line now reach the unified log file. Delete is logged from `SMB2_CLOSE`, not `SMB2_SET_INFO`, because that's genuinely where impacket performs the deferred removal — `SET_INFO` with `FileDispositionInformation` only sets a `DeleteOnClose` flag on the open file handle; the actual `os.remove()`/`shutil.rmtree()` call happens later, when the handle is closed (confirmed by reading impacket's `smb2Close` source directly, not assumed). **Deliberately does not log plain read-opens**, unlike SFTP/FTP: in those two protocols “opened for reading” reliably means “the client is downloading this file” — there's no other reason to open a file for read over SFTP/FTP. Over SMB, Windows Explorer issues a read-access `CREATE` for routine directory browsing, thumbnail generation, and property lookups — every folder view generates several — so treating every read-access `CREATE` as a “download” would flood the log with browsing noise rather than reflect actual transfers. Verified against a real impacket `SMBConnection`: upload vs. overwrite correctly distinguished (first write to a new path logs `upload`, a second write to the same path logs `overwrite`), mkdir/rename/delete/rmdir all correct, and a plain read (`getFile`) confirmed to produce zero audit output.

### SSL Certificate (ssl_cert.py)

- Generated at `db/webdav.crt` + `db/webdav.key` on first HTTPS server start. **Note**: this location is not a hardcoded constant — `server_config.json` has no db_dir/cert key of its own; the actual directory comes from `paths.py`'s `get_db_dir()`, which reads `storage_config.json`'s `db_path` (defaulting to `<folder containing paths.py>/db` if unset). `prod_server.py` reuses the same directory for the main Hypercorn HTTPS listener's cert, not just WebDAV's.
- Self-signed, 10-year validity, RSA-2048, SHA-256.
- SANs include `localhost` and all detected local IPv4 addresses (ensures cert matches whatever IP the client uses).
- `CA:TRUE` in BasicConstraints so it can be imported as a Trusted Root CA.
- Served unauthenticated at `GET /webdav.crt` via `_CertMiddleware`, on whichever WebDAV listener is running — `https://HOST:8443/webdav.crt` by default (the middleware wraps the app behind both binds; by code reading, not exercised live). `http://HOST:8080/webdav.crt` only exists if the plaintext listener is up (HTTPS disabled, or cert-preparation fallback). `webdav_server.py`'s HTTPS startup message still says to import the cert "manually (or serve it yourself)" — stale wording, not changed here.
- **Regenerate** after IP change: `python ssl_cert.py --regenerate`.
- **Cross-platform trust-import docs (new)**: `ssl_cert.py`'s module docstring now documents the one-time client-side trust step for all three desktop OSes, not just Windows — `security add-trusted-cert` for macOS, and `update-ca-certificates` (after copying the cert into `/usr/local/share/ca-certificates/`) for Linux `davfs2` mounts. The Windows `Import-Certificate` steps and the `net use` drive-mapping example were already documented and are unchanged.

**Tailscale cert preference (prod_server.py)**: On startup, `prod_server.py` first tries `tailscale cert` to obtain a real, publicly-trusted certificate for the device's `*.ts.net` MagicDNS name, with a 12-hour background renewal loop running for the lifetime of the server. If Tailscale isn't installed, not logged in, or not enabled, it falls back to `ssl_cert.py`'s self-signed cert automatically — no configuration needed either way. This only applies to the certificate `prod_server.py` uses for its own Hypercorn HTTPS listener; `webdav_server.py`'s HTTPS listener still uses `ssl_cert.py`'s cert directly.

### config.py Protocol Variables

```python
WEBDAV_ENABLED       = False  # WebDAV HTTP server — 🆕 now off by default (was True)
WEBDAV_PORT          = 8080
WEBDAV_HTTPS_ENABLED = True   # WebDAV HTTPS server (TLS terminated by Hypercorn now; cheroot is only a transitive wsgidav dependency, not used for serving)
WEBDAV_HTTPS_PORT    = 8443
SFTP_ENABLED         = True
SFTP_PORT            = 2222
FTP_ENABLED          = True
FTP_PORT             = 2121
FTP_TLS_ENABLED      = True   # 🆕 explicit FTPS (AUTH TLS); reuses the WebDAV HTTPS cert
FTP_TLS_REQUIRE_DATA = True   # 🆕 False → allow a plaintext data channel for legacy clients
SMB_ENABLED          = False  # off by default — needs smb_setup.py first, unlike the other three
SMB_PORT             = 445
SMB_FALLBACK_PORT    = 8445
SMB_SHARE_NAME        = "SharedFolder"
```

**🆕 `WEBDAV_ENABLED` default flip (2026-08-28)**: now `False` by default (previously `True`). This is the plaintext-HTTP WebDAV listener — credentials travel unencrypted over Basic Auth, which is exactly what triggered ZAP's "Cleartext Transmission of Sensitive Information via HTTP" finding (see [Version 4.2 — ZAP Security Scan Fixes](#version-42-2026-08-18)). It's also ignored outright whenever `WEBDAV_HTTPS_ENABLED` is on and its cert loads fine — HTTPS then runs exclusively and `:8080` never opens alongside it, regardless of this flag. It only takes effect when HTTPS is disabled, or as an automatic fallback if the HTTPS cert can't be prepared (e.g. `cryptography` isn't installed) — set it `True` for either of those cases, not to run both listeners at once, which `webdav_server.py` won't do anyway.

**🆕 `FTP_TLS_ENABLED` / `FTP_TLS_REQUIRE_DATA` (2026-08-28)**: see [FTP Implementation Notes](#ftp-implementation-notes) above for the full behavior (FTPS via `AUTH TLS`, shared cert with WebDAV HTTPS, `pyOpenSSL`-gated with a plaintext fallback).

All keys are saved/loaded by `save_server_config()` / `load_server_config()` in `server_config.json`. Configurable interactively via `python config.py` → option 13 (Protocol Servers); SMB has its own sub-menu there, and FTP's sub-menu now has two additional options (3: toggle FTPS, 4: toggle "require TLS on data too"). No `SMB_AUTO_MANAGE_LANMAN` toggle exists — an earlier design auto-stopped/restored Windows' LanmanServer on every server start/stop, but this was the wrong model: disabling LanmanServer to free port 445 doesn't take effect until an actual machine restart (a kernel driver binding, not just a service flag), so it was never a per-session toggle to begin with. Replaced with `smb_setup.py`, a rare, human-run, one-time setup — see below.

### Required Dependencies (new)

```
wsgidav    — WebDAV WSGI server
cheroot    — pulled in transitively by wsgidav; no longer used directly for serving (see below)
asgiref    — bridges wsgidav's WSGI app onto Hypercorn (WsgiToAsgi)
hypercorn  — ASGI server for the whole stack (web UI + WebDAV HTTP/HTTPS); replaced waitress. setup_pymodules.sh installs it as `hypercorn[h3]` (the HTTP/3 extra)
paramiko   — SSH/SFTP implementation
pyftpdlib  — FTP server
pyOpenSSL  — 🆕 optional; enables FTPS (AUTH TLS) in ftp_server.py when FTP_TLS_ENABLED is True — plain FTP still works without it, just without TLS
impacket   — SMB server
```

Install: `pip install wsgidav asgiref hypercorn paramiko pyftpdlib pyOpenSSL impacket` (`waitress` and the explicit `cheroot` pin were dropped from requirements.txt as part of the Quart/Hypercorn migration — the project is now standardized on Hypercorn for every HTTP-speaking component, including WebDAV, which is served via `asgiref.WsgiToAsgi` bridging wsgidav's WSGI app onto the same Hypercorn Config/thread as `prod_server.py` uses, `bind=` for TLS and `insecure_bind=` for plain HTTP. Known caveat: `WsgiToAsgi` doesn't implement ASGI lifespan, so Hypercorn logs a harmless "continuing without Lifespan support" warning on WebDAV startup.)

Each is imported lazily inside `start()`. If a library is missing, that protocol server prints a warning and skips — the main Quart server is unaffected.

**Where the full package list actually lives (2026-09-21)**: the list above covers only the protocol servers. The authoritative, complete set of managed packages is the `packages=(...)` array in `setup_pymodules.sh` — it also covers Quart, Werkzeug, watchdog, bcrypt, cryptography, zipstream-new, mammoth, openpyxl, python-pptx, rarfile, pyzipper, py7zr, pyvips, psutil, pynacl, and pyppmd. See [Package Management (setup_pymodules.sh)](#package-management-setup_pymodulessh). ⚠️ That script currently rewrites `Quart>=0.21.0,<1` to `Quart<1`, undoing the floor pin documented under Troubleshooting → Quart/Hypercorn Migration Issues.

---

## 🕓 Version Engine (File Versioning) (2026-09-25)

Added 2026-09-25. A per-file version-history subsystem — every tracked file's content gets snapshotted, content-addressed, and restorable — **unrelated to the Share Links feature** (that's public link sharing of the *current* file; this is private historical backup of *past* versions). Built from a detailed spec that named six files as ground truth (`config.py`, `paths.py`, `dev_server.py`, `prod_server.py`, `protocol_manager.py`, `logging_setup.py`) with the instruction that the repo wins on any conflict with the spec — the process below follows what those files actually do, not just what was asked for.

### Process Architecture — mirrors WebDAV's subprocess pattern deliberately

```
dev_server.py / prod_server.py (parent / launcher)
    └── version_engine.start()
            └── subprocess.Popen([sys.executable, "version_engine.py", "--worker"])
                    (separate OS process — own DB connections, own
                     watcher/scanner/worker threads; never shares the
                     Quart/Hypercorn event loop)
```

This is a **close, deliberate copy** of `protocol_manager._spawn_webdav_process()` (see [WebDAV Process Isolation, Watchdog & restart-webdav](#webdav-process-isolation-watchdog-restart-webdav-2026-09-09)) — same `Popen` kwargs (`stdin=DEVNULL`, piped+relayed stdout/stderr on daemon threads, `text=True`/`encoding="utf-8"`/`errors="replace"`), same `env["CLOUDINATOR_LOG_PREFIX"] = logging_setup._LOG_PREFIX` (child logs into the parent's own daily file instead of opening a second one), same unconditional `env["PYTHONUTF8"] = "1"` (root cause: emoji in `print()` output raises `UnicodeEncodeError` under a piped, non-console stdout — same issue WebDAV already worked around), same `sys.platform == "win32"` guard around `creationflags=subprocess.CREATE_NO_WINDOW`. An optional PID file (`.manage_pids/version_engine.pid`) mirrors WebDAV's `_write_webdav_pidfile()`/`_clear_webdav_pidfile()` too — not required for correctness (everything works off the in-process `Popen` handle), added for parity with future `manage.sh`-style tooling.

**Deliberately does NOT copy** WebDAV's watchdog (`_webdav_watchdog()`, auto-respawn on crash). A stuck/crashed Version Engine is expected to self-heal via crash recovery on the *next* `start()`, not be silently respawned — a respawn loop could mask a real problem (corrupt DB, full disk). This is a considered omission, not an oversight — it's called out in `version_engine.py`'s own module docstring.

`protocol_manager.py` has **zero** new imports/functions/references related to this — confirmed via `diff` against the pre-change file, not just "no changes intended." The only callers of `version_engine.start()`/`.stop()`/`.force_kill()` are `dev_server.py` and `prod_server.py`. `app.py`'s standalone `if __name__ == "__main__":` path (used only for direct `python app.py`, not either real launcher) was deliberately left without a `version_engine` import — same reasoning as the file itself already applies to `protocol_manager` there.

### Lifecycle wiring

| Launcher | Start | Stop (graceful) | Stop (force) |
|---|---|---|---|
| `dev_server.py` | `version_engine.start()` next to `protocol_manager.start_all()` | `version_engine.stop()` in the `except KeyboardInterrupt:` block, next to `protocol_manager.stop_all()` | *(none — `dev_server.py` has no force-quit tier for anything, not just this; left that way rather than introducing a new one)* |
| `prod_server.py` | `version_engine.start()` next to `protocol_manager.start_all()` | `version_engine.stop()` in the `finally:` block (first SIGINT → `shutdown_event` → `serve()` returns), next to `protocol_manager.stop_all()` | `version_engine.force_kill()` in the second-SIGINT fast path, next to `protocol_manager.force_kill_webdav()`, before `os._exit(0)` |

`stop()` mirrors `protocol_manager.stop_all()`'s WebDAV half exactly: `proc.terminate()` → `proc.wait(timeout=VERSION_SHUTDOWN_TIMEOUT)` → `proc.kill()` on `TimeoutExpired`. `force_kill()` mirrors `force_kill_webdav()`: bare `proc.kill()`, no wait, safe to call from a signal handler right before `os._exit()`. The actual graceful *drain* (finish in-flight jobs, close the DB) happens **inside the child**, in response to receiving the signal — see Crash Recovery below for why that boundary matters.

`start()` is idempotent — checks the held `Popen` handle's `.poll()` under a lock (`_version_engine_proc_lock`, mirroring WebDAV's `_webdav_proc_lock`) before spawning; calling it three times in a row produces exactly one child (verified: same pid observed across all three calls in testing).

### SQLite schema (`version_engine.sqlite3`, in the resolved `DB_DIR` — a SEPARATE file from `cloudinator.db`)

`files` (path, normalized dedup key, tracking source, deleted flag) → `versions` (sha256, size, storage_mode `full`/`chunked`, status `pending→processing→verifying→completed`/`failed`/`deleted`) → `version_objects` (ordered chunk_index → sha256, links a version to its content-addressed objects) → `objects` (sha256 PK, size, `orphaned_since` for GC). Plus `jobs` (operation, status, retry_count — recoverable after restart) and `tracked_paths` (a DB-side mirror of `config.py`'s tracking lists, for admin visibility). `engine_metadata` stores `schema_version`/`engine_version` plus live counters (`watcher_running`, `scanner_running`, `last_scan`) that the **parent** process's `status()` reads back via its own short-lived read-only connection — this works because SQLite WAL mode supports concurrent readers from a different process; the parent does NOT and CANNOT share the child's in-process connection/locks (different process entirely).

**Note on `database.py`**: `version_engine.sqlite3` is completely separate from `database.py`'s `cloudinator.db` (see the Quick Reference row above) — same `DB_DIR`, different file, no shared schema, no shared connection object, no import of `database.py` from `version_engine.py`. The connection pattern (`sqlite3.connect(..., check_same_thread=False)`, `row_factory=sqlite3.Row`, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`) is mirrored mechanically from `database.py`'s own `_connect()`, not shared as an object — `database.py`'s module-level `_write_lock`/`_bootstrap_lock` are in-process Python objects that wouldn't apply across the parent/child boundary even if imported.

### Storage: hybrid full-object / chunked, content-addressed

Files ≤ `VERSION_SMALL_FILE_THRESHOLD` (default 4 MB) are stored as one full object; larger files are chunked at `VERSION_CHUNK_SIZE` (default 8 MB, **verified independent of the upload `CHUNK_SIZE`** — mutating one does not affect the other) via a `FixedSizeChunker`, architected so a future `ContentDefinedChunker` can be swapped in without touching the public snapshot/restore API. SHA-256 is the sole identity in both modes — every object write is atomic (temp file → fsync → `os.replace()`), and every object read is hash-verified before use, so a corrupted or truncated object is caught and refused rather than silently served. Dedup is automatic and free: identical content (a whole small file, or a chunk shared across two large files) is only ever stored once.

**Universal, format-agnostic by design**: every file is treated as an opaque byte stream — no branching on extension, ever (`if ext == ".docx"` is explicitly disallowed by the spec this was built from). DOCX, ZIP, video, executables, unknown/no extension all go through the exact same code path.

### Restore — the one invariant that's non-negotiable

```
original_sha256 == restored_sha256   AND   original_size == restored_size
```

`Engine.restore_version(version_id, destination, overwrite=None)` reconstructs into `destination.tmp`, hash-verifies every object read along the way, computes the full restored file's SHA-256, and only calls `os.replace()` into the real destination **after** that hash and size match the original exactly. Refuses by default to overwrite an existing destination (`VERSION_ALLOW_RESTORE_OVERWRITE=False`), and refuses to ever write into the version storage directory itself. Verified directly (not just by code inspection): small-file and chunked-file restores byte-for-byte identical to the original; a manually corrupted stored object is caught and restore refused; an old version stays restorable after the source file changes again.

### Watcher + Scanner — a documented simplification

The watcher is **stat-polling** (mtime + size, every 3 seconds when `VERSION_WATCH_ENABLED`), not an OS-level filesystem-event watch (inotify/ReadDirectoryChangesW/FSEvents) — this repo has no `watchdog`-package dependency for that (the *unrelated* `watchdog` package already used by `file_monitor.py` for the main storage tree was deliberately not reused here, to keep Version Engine's process fully independent). The scanner does full reconciliation on the slower, configurable `VERSION_SCAN_INTERVAL` (default 300s) and is also what discovers brand-new files under tracking roots. The engine works correctly with the watcher disabled entirely — the scanner alone still eventually catches everything. Both share one `_reconcile_once()` implementation; a changed file is enqueued once and debounced (a `_pending_norm_keys` set) so a burst of filesystem activity doesn't produce duplicate jobs.

Tracking scope resolution (`get_eligible_files()`) combines `VERSION_TRACK_FILES` (individual files, always included), `VERSION_TRACK_DIRECTORIES` (recursive, always included), and — only when `VERSION_TRACK_ALL_FILES=True` — `VERSION_TRACK_ROOTS` (recursive). Every list defaults empty; nothing is versioned until explicitly configured. `VERSION_EXCLUDE_DIRECTORIES`/`VERSION_EXCLUDE_PATTERNS` (default `["*.tmp", "*.part", "~$*"]`) apply everywhere. Path equivalence normalization (`_normalize_path()`) case-folds only on `sys.platform == "win32"` — Linux/Termux are case-sensitive filesystems, so folding case there would wrongly merge distinct files.

### Crash recovery — load-bearing on Termux specifically

On every worker startup, before the watcher/scanner/workers start: any job or version left in a non-terminal state (`pending`/`processing`/`verifying`) from a previous run is marked `failed` — **never** silently resumed and **never** left falsely `completed`. Stale temp files (anything still in the tmp dir is, by construction, an incomplete write — finished writes are renamed *out* of tmp atomically) are deleted unconditionally. No work is actually lost: the next scan naturally re-creates a snapshot job for any file whose hash still doesn't match its latest completed version, so a crash just means redoing hashing, not losing history. This matters more on Termux than desktop platforms — Android's battery/doze management can suspend or kill a background process with **no graceful signal at all**, so `stop()`'s graceful path may simply never have run before the next `start()`; the recovery logic doesn't distinguish *how* the process died, so it doesn't need to.

### Retention & GC

`VERSION_MAX_VERSIONS` (default 50) is enforced right after each successful snapshot — oldest `completed` versions beyond the cap are soft-deleted (`status='deleted'`, row kept for audit trail). GC (`run_gc()`, runs at the end of every scanner pass) considers an object orphaned once nothing references it from a `completed` version; sets `orphaned_since` on first sighting, and only actually deletes the object — plus the now-meaningless `version_objects` link rows from non-completed versions that still FK-reference it — once `VERSION_GC_GRACE_PERIOD` (default 24h) has elapsed AND it's re-confirmed unreferenced (race-aware: a snapshot could have re-referenced the same content moments earlier via dedup).

**Bug found and fixed during testing**: the original `run_gc()` tried to `DELETE FROM objects` for an object still linked from soft-deleted/failed versions' `version_objects` rows, which violated the foreign key and raised `sqlite3.IntegrityError`. Fixed by clearing those stale link rows first — the `versions` row itself (audit trail) is untouched, only the dead object-link bookkeeping is cleared.

### version_manage.py — the admin CLI (now with an interactive menu too, 2026-09-26)

```
python version_manage.py                                    # interactive menu
python version_manage.py list                              # every tracked file + version count
python version_manage.py list <file_path>                   # one file's full version history
python version_manage.py restore <version_id> <destination> [--overwrite]
python version_manage.py delete <version_id> [--run-gc-now]
```

Deliberately a **separate file** from `version_engine.py` — the same reasoning `revoke_sharing.py` gets its own file rather than living inside `database.py`. Starts no threads/subprocess; talks to the same SQLite DB and object store directly through `Engine`'s own methods, safe to run alongside a live `version_engine.py --worker` (SQLite WAL + `PRAGMA busy_timeout=10000` already set in `Engine._connect()` handle the concurrent access). Wired into `manage.sh` as `version-manage` / menu **#9** — see [manage.sh Internals & Editing Rules](#managesh-internals--editing-rules) for the menu-numbering history.

**Two interfaces, one shared implementation**: the CLI subcommands (`list`/`restore`/`delete`, via `argparse`) and the interactive menu (`interactive_menu()`, entered automatically when run with no arguments) both call the exact same three core functions — `do_list()`, `do_restore()`, `do_delete()` — so there's no behavior to keep in sync between the two; a bug fix or confirmation-wording change in one core function fixes both interfaces at once. The `cmd_list`/`cmd_restore`/`cmd_delete` functions that `argparse` calls are thin one-line wrappers unpacking a `Namespace` into the same core function calls the menu makes directly.

- `restore --overwrite` (CLI) / answering "yes" to the overwrite prompt (menu) requires typing an exact but short confirmation (`overwrite <filename> with version <id>`) before replacing an existing destination file.
- `delete` requires typing a full, **version-and-filename-specific** sentence back exactly (`"I understand this permanently and irreversibly deletes version <id> of <filename> and cannot be undone"`) — no `-f`/`--yes` flag exists anywhere, on purpose, in either interface. Warns explicitly, before the confirmation prompt, when the version being deleted is the file's *only* remaining one. `delete` only soft-deletes (same mechanism as automatic retention) — actual disk reclaim still goes through the normal GC grace period unless `--run-gc-now`/the menu's "also run GC now?" prompt is used, and even then only objects *already* past their grace period from earlier activity get freed immediately.

**Ctrl-C is safe everywhere in this file** — every `input()` call, CLI confirmation prompts included, goes through a `_prompt()` helper that converts `KeyboardInterrupt`/`EOFError` into a clean cancel rather than a traceback. At the interactive menu's top level, Ctrl-C exits the program (mirroring `manage.sh`'s own `cmd_menu` convention: "Ctrl-C / Ctrl-D / closed stdin at the top-level prompt = quit"); inside any action's own sub-prompts, Ctrl-C cancels just that action and returns to the menu. See the Ctrl-C model table in [manage.sh Internals & Editing Rules](#managesh-internals--editing-rules) for how this composes with `run_utility`'s own signal handling when launched via `./manage.sh version-manage` — the two layers are independent but the outer one (manage.sh) is what makes the inner one (this script) receive a normal, interruptible SIGINT in the first place, rather than an inherited ignored one.

Verified directly: `list` (summary and per-file), `restore` returning the *old* version's content correctly (not current), both overwrite-confirmation and delete-confirmation rejecting non-matching typed input and succeeding on an exact match, a deleted version can no longer be restored afterward, the interactive menu's full flow (list → view history → restore → exit) end-to-end via piped stdin, and — the thing that actually mattered for this addition — three separate real-`SIGINT` scenarios (top-level menu quit, mid-action cancel-and-return-to-menu, CLI-mode cancel), all clean, all traceback-free.

### Known gaps — not yet verified in this pass

Following this doc's own convention of separating *verified* from *inferred/untested*: no test was run on actual Windows (UNC paths, drive letters, long paths, `CREATE_NO_WINDOW` itself) or actual Termux (a literal `kill -9` mid-job with no `stop()` ever called — the crash-recovery test simulated the *state* such a kill leaves behind by writing it directly, not by sending a real signal to a running worker). No benchmark pass (snapshot/restore speed, memory, dedup ratio at 100 KB–1 GB) was run — the streaming-I/O design (no full-file buffering above the small-file threshold) was verified by code inspection, not measured. No test exercises the two-stage `prod_server.py` shutdown through an actual live Hypercorn process tree — the underlying `stop()`/`force_kill()` primitives were tested directly against a real spawned subprocess, and the wiring was confirmed by reading the code, but not through a live `prod_server.py` process. First-session usability gap, now closed: the engine originally shipped with **no way for a human to actually restore anything** — no CLI, no list, no lookup helper — until specifically asked "how do we restore a version?" `version_manage.py` (above) is the fix; worth remembering as a pattern for future subsystems of this shape.

### Version History Web UI (2026-09-27)

Built 2026-09-26/27 from a planning document that specified the module split and the sync-vs-async question; where the real repo disagreed, the repo won (route shape below). **Status: experimental, not yet deployed.**

**Structure.** `version_history.py` is logic-only; the routes live in `app.py` (which has no Blueprints anywhere — none were introduced). It holds one module-level `Engine`, created by `version_history.init()`, called once from `app.py`'s own module-level startup next to the search-index init — **not** from `dev_server.py`/`prod_server.py`, which only start the separate Version Engine subprocess and needed zero changes. `version_engine.py`'s `Engine` stays 100% synchronous; every route wraps its call in `await asyncio.to_thread(...)`. No `aiosqlite`, no async `Engine`.

**Restore never touches the live file.** `restore()` reconstructs (byte-for-byte hash-verified by the same `Engine.restore_version()` the CLI uses) into `ROOT_DIR/.recovered/<original relative dir>/<stem>__<snapshot date YYYY-MM-DD_HHMMSS>__v<id><ext>`, e.g. `.recovered/docs/report__2026-09-20_143012__v42.docx`. Deterministic naming means restoring the same version twice is an idempotent rewrite. `.recovered/` is dot-prefixed like `.chunks/`, and `storage.list_dir()` skips every dot-prefixed entry (confirmed in `storage.py`, then observed live), so it stays out of normal browsing; `/download/recovered/*` serves it. `version_manage.py`'s CLI `restore` is unchanged and can still restore anywhere, including in place.

**Download without restoring** buffers the version in memory: `prepare_download()` reconstructs into a throwaway temp dir, reads the bytes, deletes the dir, returns the bytes — all in one `to_thread` call. This exists because **Quart's `Response` has no `call_on_close`** (verified against the installed 0.22.0 — an earlier draft used it, with a delayed-cleanup fallback that would have silently become the only path). Trade-off: memory proportional to the version's size for one request; a multi-GB download has not been load-tested.

**Delete** requires the exact file basename in `confirm_text`, checked in `version_history.delete()`, not just in JS. Soft-delete only, same as the CLI and retention.

**Retry Now.** `retry_snapshot()` calls `Engine.snapshot_file()` on demand. That method returns `None` for *both* a failed capture and a dedup-skip (content identical to the latest completed version), so `retry_snapshot()` diffs the version list before/after to tell three outcomes apart: new `completed` row (success), new `failed` row (still failing — real error returned), or no new row (unchanged — reported as success with `version: null`). Shown as a single banner at the top of the modal, only when the *newest* version failed — not per row, since a retry always re-captures the current file whichever failed row you'd click. A locked file (a QuickBooks `.QBW` open in QuickBooks is the case that surfaced this) is **not** retried automatically by the engine, so this is the way to force it.

**Retention applies to retries like any capture.** `_apply_retention()` runs after every genuinely new completed snapshot; with `VERSION_RETENTION_ENABLED = True`/`VERSION_MAX_VERSIONS = 50` (the shipped defaults), version 51 soft-deletes the oldest. A retry never overwrites an existing version's content — each capture is a new row.

**Frontend** (`index.html`/`index.js`/`index.css`): the row's Download button (files only; folders keep `downloadFolderAsZip`) opens `#downloadOptionsModal` with "Download current version" and "Version History", which opens `#versionHistoryModal`. Each completed version offers Download/Restore/Delete (Restore/Delete `readwrite` only); Delete expands an inline type-the-filename confirmation. Failed rows show their stored error inline. Uses the existing `data-fn`/`data-args` dispatch and the CSRF-wrapping `fetch`, so no new listener plumbing. **Layout lesson**: a first version added a dedicated Version History icon to each row's action bar, inserted second, which shifted Delete one slot right and forced sideways scrolling on narrow screens; moving it last only shrank the problem. Folding it into the Download button removed the icon entirely — the action bar is back to exactly its pre-feature icons. Don't add icons to that bar without checking the width budget (`.actions-cell .actions` is `flex-wrap: nowrap !important`, fixed 28px buttons).

**Bugs found and fixed while verifying**
- `call_on_close` — above.
- `/csrf-token`: `validate_session` did not exempt `get_csrf_token`, so an anonymous request 301'd to `/login` despite the route's own docstring saying no login was needed. Added `"get_csrf_token"` to the exempt list; verified an anonymous session now gets a token that works for a real login POST. (Login itself never hit this — `login.html` seeds the token via the `csrf_token()` Jinja global.)
- `"capture error"`: `version_engine.py`'s snapshot path caught any exception from `_capture_full`/`_capture_chunked` and stored the literal `"capture error"` in `versions.error`, discarding the real cause (the real message only reached the `jobs` table's error column, which nothing shows). Now stored as `"capture failed: <exception text>"`. **Old rows keep the old text** — the original message was discarded, so it can't be recovered; only new failures carry it. Verified with a simulated `PermissionError`.

**Not a bug, but easy to misread: "corrupt chunk".** `Engine.restore_version()` hash-verifies every object it reads and raises `object <sha>… missing or corrupted — restore aborted` on a mismatch or missing file. That is detect-only; nothing re-derives a bad object. Verified live that deleting a version and running GC does **not** destroy a chunk still shared (deduplicated) with another completed version, so a corrupt-object error means the bytes on disk changed outside the engine. Failed rows in the list are a different thing entirely: failed *captures* (0 B), kept permanently as an audit trail — they are not corruption.

**Verified** (real `app.py` import, real Quart test client, real `database.py` users, and the real `/login` form flow via the uploaded `login.html` — not a session shortcut): list/restore/download/delete/retry, byte-exact recovered and downloaded content, live file untouched after restore, `.recovered/` absent from `storage.list_dir("")`, the cross-file `version_id` guard, wrong/right delete confirmation, readonly → 403 on restore/delete/retry (200 on list), all three retry outcomes, and the async bridge (a restore blocked 3 s by a test patch while an unrelated route answered in ~3 ms). The download-options flow was click-tested against the real rendered page in jsdom (modal opens; "Download current version" closes it and navigates).

**Known gaps.** `file_index.py` was never provided, so the live runs used a stub (test-only, never delivered). No load test of large downloads. Two requests restoring the identical version at the same instant weren't exercised (deterministic destination and identical bytes make it expected to be harmless). The frontend was checked in jsdom, not a real browser's layout. ~~The modal doesn't show how close a file is to `VERSION_MAX_VERSIONS`. Failed capture rows can't be dismissed.~~ Both addressed in 4.25 (see below).

**4.25 follow-ups (2026-09-28).**
- **Hide failed/deleted by default.** The list hides `failed` and `deleted` rows unless "Show failed & deleted (N)" is toggled on (pure frontend; state resets each time the modal opens). Retention soft-deletes one row per save once a file is past the cap, so `deleted` rows pile up the same way failed ones do — hence hiding both. In-progress rows (`pending`/`processing`/`verifying`) are always visible.
- **Clear failed attempts** (readwrite). `Engine.clear_failed_versions(file_path)` is a **hard** delete of `status='failed'` rows for one file — a soft delete would just relabel them `deleted` and they'd still clutter the list. Safe because a failed capture never became a restorable version. It removes any partial `version_objects` rows first (`PRAGMA foreign_keys=ON`; a chunked capture that dies mid-way leaves some), and the chunk objects those pointed at become unreferenced and are reclaimed by the normal GC — verified with GC grace forced to 0 that GC copes and the completed version still restores byte-exact. `completed` and `deleted` rows are never touched; `jobs` rows are left alone (no FK to `versions`). The button is two-step (first click arms it for 5 s, second click clears) and is only shown when there are failed rows.
- **"X of N versions kept."** `version_history.retention_info()` reads `config.VERSION_RETENTION_ENABLED`/`VERSION_MAX_VERSIONS` **at call time**, so a runtime config change shows up immediately. Hidden entirely when retention is disabled. Amber from `ceil(0.9 × max)`; at the cap it says saving a new version removes the oldest.
- **Retry result is inline.** A status line at the top of the modal (green/red) replaces the old popup. When a retry reports "already up to date" the amber "latest attempt failed" banner is suppressed for that open of the modal, because the newest row is still the old failed one and the banner would otherwise nag. It returns the next time the modal is opened while the newest row is still failed — clear the failed attempts to make it go away for good.
- **Notification stacking.** Root cause and fix are in the sync note above; `#notificationModal { z-index: 1100 }`. If a new modal ever needs to sit above notifications, pick a value between 1100 and 10000.
- **Test notes.** The UI was exercised in jsdom against the real rendered page for both a readwrite and a readonly session, with the API mocked (35 checks: retention colouring at 1/46/50 and disabled, toggle, two-step clear incl. the 5 s auto-disarm, inline retry outcomes, readonly sees no Retry/Clear, and the z-index ordering). The app's `fetch` wrapper re-sends a 400 only when the response body mentions "csrf", so a genuinely failed retry (HTTP 400) is **not** replayed — checked because retry returns 400 on failure. Not yet checked in a real browser.


### SQLite write-lock discipline (2026-09-28)

**Rule for anything in `version_engine.py` (and anything else touching `version_engine.sqlite3`): never hold a write transaction across file I/O.** Python's `sqlite3` (default legacy isolation) opens an implicit transaction on the first INSERT/UPDATE/DELETE and keeps it — and SQLite's single database-wide write lock — until `commit()`/`rollback()`. The engine runs in two processes (the worker child, plus the web process via `version_history.py`), and each thread has its own connection (`Engine._connect()` is thread-local), so a lock held by one thread blocks every other writer for up to `busy_timeout` (10 s), then raises `sqlite3.OperationalError: database is locked`. WAL mode does **not** help writers, only readers. So: do the slow thing (read, hash, fsync, `os.remove`) first, then write and `commit()` immediately.

**The bug that broke this** (fixed): `_capture_chunked()` did `_store_object_from_tmp()` (which committed) and then `INSERT INTO version_objects` with **no commit**; the open transaction survived through the next iteration's read/hash/fsync and was only released by the next `_store_object_from_tmp()` commit. Net effect: lock held almost continuously for the whole capture of a big file. Now `_store_object_from_tmp(..., commit=False)` + the `version_objects` INSERT + one `commit()` per chunk (atomic pair, microseconds under lock). `_capture_full()` was already fine (every write followed by a commit).

**Other changes in `version_engine.py`**
- `_connect()`: `PRAGMA busy_timeout=10000` now runs **before** `PRAGMA journal_mode=WAL` (the WAL pragma can itself need a lock and previously only had `sqlite3.connect`'s default 5 s). Value unchanged.
- `run_gc()`: *(v4.26: committed every 100 deletions — superseded in v4.27, see below)*.
- `_mark_version_failed()`: retries up to 3× (1 s apart) on a lock error, so a lock during error handling can't leave a row stuck as `processing`.
- Diff against the pre-change file: 48 changed lines, all in the spots above.

**Web-side hardening** (defence in depth — the engine fix removes the cause, this makes any residual lock survivable)
- `version_history.py`: `_with_lock_retry()` retries `sqlite3.OperationalError` containing "locked"/"busy" with backoff (0.25/0.5/1/2/3 s, ≈7 s total; safe because every caller runs in `asyncio.to_thread`) around `list_versions`, `get_version`, `restore_version`, `delete_version`, `clear_failed_versions`. Still failing → returns `(False, "The version database is busy … try again in a few seconds.")`. Any **other** unexpected exception in restore/download/delete/clear is caught, logged with a traceback (`logging_setup.get_logger("version_history")`) and returned as a normal failure — previously only `VersionEngineError` was caught, so anything else became an HTML 500. `retry_snapshot()` appends a "worker was writing, try again" hint when the stored failure text contains "locked".
- `app.py`: `/api/versions/list` wraps `get_history` and returns a JSON 503 with the reason instead of a 500.
- `index.js`: new `_vhJson(resp)` (never throws; returns `{error: "Server error (HTTP n) — see the server log."}` for a non-JSON body) used by list/retry/restore/delete/clear-failed. **Root cause of the misleading "Could not reach the server"**: `resp.json()` threw on the HTML 500 page and the `catch` assumed a network failure. That message now really means a network failure.

**v4.27 follow-up (same day) — after deploying v4.26 the lock error still showed up in the worker log**
- **`run_gc()`**: read-only classification (live / to-clear / to-mark / due-for-deletion), then writes in batches under `BEGIN IMMEDIATE`, committed every `_GC_BATCH_ROWS` (500) or `_GC_BATCH_SECONDS` (0.25 s), `_GC_PAUSE` 10 ms between batches (SQLite's busy handler only polls, so a tight loop of back-to-back write transactions can starve a waiting writer). The "still unreferenced?" re-check now runs *inside* the write transaction, so no snapshot can commit a new reference between the check and the delete. `os.remove()` deliberately stays inside the batch transaction (same ordering as before) — removing the file *after* commit would open a window where a snapshot dedups against a file about to be deleted. A failed sweep marks its `gc` job `failed` and the next scan continues; batches already committed stay committed.
- **`snapshot_file()`**: separate retry budgets for "source changed during capture" (unchanged, `VERSION_RETRY_COUNT`) and for a locked DB (`_BUSY_MAX_RETRIES = 5`, `_BUSY_MAX_RETRIES_WEB = 2`, backoff `min(30, 2**n)` s). A lock error inside `_attempt_snapshot()` becomes `_DatabaseBusy`, and `_discard_version_row()` (best effort, 3 tries) deletes the half-made row so no permanent `failed` row is recorded for what wasn't the file's fault. On give-up: the norm-key is popped from `_known_state` (see below), the job is marked failed if the DB allows it, and `last_snapshot_busy()` returns True for the calling thread.
- **Why the requeue matters**: `_reconcile_once()` only enqueues a file when its cached `(mtime, size)` differs from the current one, and it updates the cache *at enqueue time*. So before v4.27 a snapshot that failed for any reason was lost until the file happened to change again. Lock-caused give-ups now clear the cache entry so the watcher (3 s poll) re-queues the file. **Not** done for "source changed during capture" or permission errors — re-queueing those would make the engine re-hash a live QuickBooks file every 3 s forever.
- `_retry_locked()` wraps the bookkeeping writes at the top of `snapshot_file()`; `_mark_version_failed()` and `_discard_version_row()` have their own small retries.
- `_connect()`: `PRAGMA synchronous=NORMAL` added (with `journal_mode=WAL`). Trade-off: a power loss can roll back the last few commits; object files are fsync'd separately and crash recovery already marks non-terminal rows failed, so nothing can be left falsely `completed`.
- **Logging**: `Snapshot failed …` now includes the traceback; `GC: …` reports its duration; lock retries/give-ups log at WARNING with the file path.
- **Still true / not addressed**: the worker's `_known_state` is touched by both the watcher and scanner threads without a lock (duplicates are absorbed by `_pending_norm_keys`/dedup); `_store_object_from_tmp()` checks `os.path.exists()` outside any lock, so an object due for GC and re-captured at the same instant could in theory end up with a row but no file (needs an object orphaned ≥ `VERSION_GC_GRACE_PERIOD`, default 24 h, so vanishingly rare; pre-existing).

**Related caveats (not caused by this fix, unchanged by it)**
- A live `.QBW`/`.TLG` (QuickBooks open) can still fail a capture with `source changed during capture` (the file's mtime/size moved mid-capture; the engine retries `VERSION_RETRY_COUNT` times) or a permission error (file locked open). Retry Now is the manual lever; a different error text after this fix means it's one of these, not the DB lock.
- Old failed rows keep their old `database is locked` text (they're audit rows); "Clear failed attempts" removes them.
- Two processes can capture the same file at once (worker + a web Retry). The whole-file SHA dedup discards the loser's row, so this is wasteful, not incorrect.

**Browser-console warnings seen alongside this — not bugs in this app**
- `Permissions-Policy: Unrecognized feature: 'run-ad-auction' / 'join-ad-interest-group' / 'private-aggregation' / 'attribution-reporting'`: none of these strings exist anywhere in `app.py` (its `Permissions-Policy` lists only camera/microphone/geolocation/payment/usb/bluetooth/midi/magnetometer/gyroscope/accelerometer/fullscreen). They are being injected from outside the app (browser extension, or something between the browser and Quart) — not investigated further. **Left alone; no security header was changed.**
- `Document-Policy: Unrecognized document policy feature name document-write` (Edge): comes from `app.py`'s `Document-Policy: document-write=?0, sync-xhr=?0`; Edge doesn't recognise that name. Cosmetic; left in place.
- These do **not** cause the download 500 (that was the DB lock above).

**Verification** — `version_engine.py` was exercised directly (real file, stub `config`/`paths`/`logging_setup`, since the real `config.py` needs the rest of the app): a 40-chunk capture with `os.fsync` slowed to 0.25 s/chunk while a second connection tried `_create_job` and `_set_meta` with a 1 s `busy_timeout` → **original: both fail ("database is locked"); patched: both succeed in ~0 s**. Also: three simultaneous chunked captures all completed; every restore hash-matched its source; `run_gc()` ran. `version_history.py`'s retry/friendly-message/exception paths were tested against a stub `Engine` (transient lock retried through, permanent lock → friendly message, unrelated `OSError` → reported, not raised). **Not tested:** the real `app.py`/Quart routes end-to-end, a real browser, Windows, or a real multi-process worker + web collision on the production box.

---

## 🛠️ Admin Tools & Utilities

`manage.sh` remains the primary launcher for the server and utility commands. It runs every utility script through a wrapper that keeps `manage.sh` alive on Ctrl-C **while still letting the child script be interrupted** (a *handled* SIGINT trap — earlier versions *ignored* SIGINT, which made child scripts uninterruptible; see [manage.sh Internals & Editing Rules](#managesh-internals--editing-rules) for why that matters). `setup_pymodules.sh` (package updates) is documented under [Package Management](#package-management-setup_pymodulessh).

### manage.sh Internals & Editing Rules

Reviewed 2026-09-21 against the 1,536-line `manage.sh` (`bash -n` clean and `./manage.sh help` executes — both run on a CR-stripped copy under bash 5.2). Everything marked *verified* below was run, not just read.

**Conventions**
- Runs under `set -euo pipefail` on Git Bash (Windows), Linux, and Termux. Platform helpers: `is_windows()` (`OSTYPE` msys*/cygwin*), `is_termux()`. The interpreter is `$PYTHON` (env override; else `python`, else `python3`).
- Style is tab-indented (shfmt-like). Print helpers: `info` / `success` / `warn` / `error` / `header` / `divider`. Prompt helpers: `_confirm "q?"` (y/N; **returns 1 on Ctrl-C, Ctrl-D, or closed stdin**, so callers can cancel cleanly), `_ask VAR "prompt"` (same EOF behavior), `_read_line`.
- Colors are ANSI-C quoted (`$'\033[0;31m'`) — real escape bytes, not the four characters `\033`. This is required because `cmd_help` prints through an **unquoted** heredoc (`cat <<EOF`), so `${BOLD}`/`${NC}` expand there — and so does any other `$…`, backtick, or backslash you put in the help text. Escape or avoid them.
- **Line endings**: all four files uploaded for this pass (including `CLAUDE.md`) had CRLF endings. A CRLF `.sh` file fails on Linux/Termux/macOS (`set: pipefail\r: invalid option name`, `$'\r': command not found`). Whether the repo copies are really CRLF or that came from the upload path wasn't determined — check with `git ls-files --eol manage.sh setup_pymodules.sh`, and consider `*.sh text eol=lf` in `.gitattributes`. AI assistants: keep whatever ending a file already has; don't normalize unasked. The scripts already defend against CRs *in tool output* (`read_pid` keeps digits only; `tr -d '\r'` on netstat/PowerShell output).

**`set -e` rules — each of these fixed a real bug**
1. **Never run a command that may legitimately exit non-zero as a bare statement.** Use `cmd || ec=$?` (see `run_utility` / `run_bash_script`). A bare failing utility used to abort the whole `manage.sh` before the menu could redraw — and every Python utility exits non-zero on a cancelled or failed action (`revoke_sharing.py` included), so this is ordinary use, not an edge case.
2. **A `$(pipeline)` where "no match" is a normal result needs `|| true`.** With `pipefail`, `grep`/`lsof` finding nothing fails the assignment, and `set -e` then kills `manage.sh` silently — `start server`, `stop`, and `restart` printed nothing and exited 1 whenever WebDAV wasn't orphaned. That is why every lookup in `_kill_webdav_child` ends in `|| true`. Don't "tidy" them away.
3. **Increment with `i=$((i + 1))`, not `((i++))`** — post-increment from 0 returns status 1. (`cmd_clean_logs` uses `((deleted++)) || true`, the other accepted form.)

**Ctrl-C model** (*verified* on bash 5.2 — see the experiment below)

| Where | Mechanism |
|---|---|
| `run_utility` / `run_bash_script` | `trap ':' INT` before the child, `trap - INT` after. `_report_exit` treats exit **130** as "interrupted" (a warning, not an error). |
| `_follow_log` (`logs -f`) | Same handled trap, plus a Python follower that exits on KeyboardInterrupt — `tail -f` doesn't release the terminal reliably on Git Bash. |
| `cmd_menu` | One `trap ':' INT` for the whole loop. Each action runs through `_menu_run` — a subshell with its own INT trap that prints "Cancelled", exits 130, and returns to the menu. The top-level prompt is read by `_read_line` in a subshell (a plain `read` in the parent just re-enters after the trap runs); Ctrl-C/Ctrl-D there quits the menu. |
| `_launch_detached` (servers) | Fully detached (Windows: `CREATE_NEW_PROCESS_GROUP \| DETACHED_PROCESS`; POSIX: `setsid`) **and** SIGINT/SIGBREAK set to `SIG_IGN` inside the child *before* `runpy.run_path`, so no framework can re-arm Ctrl-C. Ignoring is correct here — the server must never die to a stray Ctrl-C. |
| `version_manage.py` (2026-09-26) | A second, independent layer *inside* the Python process, on top of `run_utility`'s trap — not a manage.sh mechanism, but relies on `run_utility` handing it a normal, default-disposition SIGINT to work at all. Every `input()` goes through a `_prompt()` wrapper that catches `KeyboardInterrupt`/`EOFError` and returns `None` instead of raising; the interactive menu treats `None` at the top-level menu prompt as "quit" and `None` inside an action's own sub-prompt as "cancel this action, return to the menu" (same split as `cmd_menu` itself). A top-level `try/except KeyboardInterrupt` in `main()` is belt-and-suspenders for a Ctrl-C landing outside any `_prompt()` call. *Verified* with real `SIGINT` delivered via `subprocess.Popen.send_signal()` (not simulated input) at three points: the top-level menu prompt (clean exit 0, "Goodbye!", no traceback), mid-action at a sub-prompt (action cancelled, menu redrawn, subsequent input still worked), and CLI-mode (`restore --overwrite` awaiting its confirm phrase — exit 1, "nothing was touched", no traceback). |

Why the utility wrappers must **handle**, not **ignore**: an ignored signal is inherited by children. *Verified*: with a parent running `trap '' INT`, a bash child's own `trap … INT` never fired, and a Python child saw its SIGINT disposition as `SIG_IGN` (so no `KeyboardInterrupt`); with `trap ':' INT` the child's trap fired and Python kept its default handler. This is exactly why Ctrl-C used to skip one pip call and let `setup_pymodules.sh` carry on to the next step. **Do not change `trap ':' INT` back to `trap '' INT`** in either wrapper.

**Menu ↔ command map** (*verified 2026-09-26, after the version-manage insert below*: the menu's `echo` lines, the `case` dispatch, and `cmd_help`'s "MENU ↔ COMMAND MAP" all agree on 1–20; **2026-10-02: #21 `validate-sri` appended and re-checked the same way, now 1–21**)

| # | Command | Runs |
|---|---|---|
| 1 / 2 | `start server` / `start dev_server` | prod (Hypercorn) / dev (Quart), detached |
| 3 / 4 / 5 | `stop` / `restart` / `status` | |
| 6 / 7 | `logs [server or dev_server] [-f]` / `clean-logs` | |
| 8 | `restart-webdav` | see [WebDAV Recovery](#webdav-recovery-managesh-restart-webdav) |
| 9 | `version-manage` 🆕 (2026-09-26) | `version_manage.py` — no args → interactive menu; see [Version Engine](#version-engine-file-versioning-2026-09-25) |
| 10 | `config` | `config.py` |
| 11 | `setup-smb` | `smb_setup.py` |
| 12 | `kick-sessions` | `kick_sessions.py` |
| 13 / 14 / 15 / 16 | `manage-users` / `debug-pw` / `reset-db` / `setup-storage` | `manage_users.py`, `debug_passwords.py`, `reset_db.py`, `setup_storage.py` |
| 17 | `update-modules` (alias `setup-modules`) | `setup_pymodules.sh`, after a confirmation |
| 18 | `revoke-shares` | `revoke_sharing.py` — all extra args pass straight through |
| 19 | `security-txt` | see [security.txt Management](#securitytxt-management-managesh-security-txt) |
| 20 | `termux-setup` | `termux_setup.sh` — always listed so numbers match `help`; dimmed off Termux |
| 21 ⚠ (2026-10-02) | `validate-sri [--fix]` | `sri_validator.py` via `cmd_validate_sri` — from the menu: check, then y/N to fix; `--fix` and `--templates`/`--static` from the shell; exit 1 on any stale/missing hash. Appended last so no existing number moved |

**2026-09-26 reorder**: `version-manage` was inserted as the new **#9** (first Utilities entry) and `config` moved up to **#10**, at the user's explicit request — everything that used to be 9–19 (`setup-smb` through `termux-setup`) shifted down to 11–20, keeping their *relative* order unchanged. This is the **third** time this doc's menu numbers have shifted from a mid-list insert (see the note below) — if you're reading this after yet another insert, the table above is the one to trust, not memory of an older revision.

**Adding a command — touch all of these** (this doc's own menu numbers have now shifted three times from mid-list inserts):
1. A `cmd_<name>()` function (or a `run_utility "<script>.py"` call).
2. The `case "$cmd"` dispatch in `main()`.
3. `cmd_menu`: the `echo` line, the `case` arm wrapped in `_menu_run`, and a renumber of everything below if you insert mid-list.
4. `cmd_help`: the command's own description, the MENU ↔ COMMAND MAP, and an EXAMPLES line.

**`_kill_webdav_child` — caveats** (background: the 2026-09-15 orphan saga under Troubleshooting → Quart/Hypercorn Migration Issues)
- It only ever kills a **python** process (`_pid_is_python`), never whatever unrelated program owns 8080/8443.
- The port sweep **hardcodes `8080 8443`** (the `for port in` loop), even though its comment says it matches `protocol_manager._webdav_target_ports()`. A customized `WEBDAV_PORT`/`WEBDAV_HTTPS_PORT` in `config.py` is **not** swept — the pidfile-based kill is then the only protection.
- It takes only the first listener per port (`head -1`), and on POSIX needs `lsof` — without it the sweep is a silent no-op.
- In `cmd_start` it runs *after* the "a tracked server is already running" check, so it never fires against a live tracked server. It cannot see a server launched *outside* `manage.sh` (e.g. `python prod_server.py` in another terminal); that server's WebDAV child is a python process on those ports, so a `manage.sh start` would likely kill it. *(Inferred from the code, not tested.)*

**⚠️ Unresolved discrepancy — is `print()` output captured in background mode?** `_launch_detached`'s comment (and `./manage.sh help`'s LOG FILES text) say background-mode stdout/stderr go to `/dev/null` and that remaining plain `print()` calls are "genuinely unobserved" — only logger output and crash tracebacks reach `logs/{prod|dev}_server_YYYY-MM-DD.log`. The logging-unification entry under Troubleshooting says `logging_setup.py`'s `_TeeStream` captures `print()` into that same file (tagged `[PRINT]`). Both can't be fully true. `logging_setup.py` wasn't part of the 2026-09-21 pass — read it before relying on `print()` output appearing in the log under `./manage.sh start`.

### Package Management (setup_pymodules.sh)

Not documented anywhere before 2026-09-21. Reviewed against the 342-line script (`bash -n` clean on a CR-stripped copy); the rewrite logic below was *verified* by running the script's own `regex_escape` / `grep` / `sed` against a seeded `requirements.txt`. The full dependency-resolution run needs network and wasn't executed.

**Invocation**: `./manage.sh update-modules [-y|--yes]` (alias `setup-modules`; menu **16**) → `cmd_setup_modules` explains what will happen, asks `_confirm`, then `run_bash_script setup_pymodules.sh`. `-y` skips **only** `manage.sh`'s question — the script's own "install now? (y/n)" prompt, and on Windows the UAC prompt, still appear. Also runnable directly: `bash setup_pymodules.sh`.

**What it does, in order**
1. `cd`s to its own directory, so the files land next to the script even after the Windows elevated relaunch (which opens a login shell in the home folder).
2. **Windows (Git Bash/MSYS) only**: checks for Administrator via PowerShell. If not elevated, it relaunches itself elevated (PowerShell `Start-Process bash -ArgumentList '--login','-i','-c',<this script> -Verb RunAs`, paraphrased) **in a new window and exits 0 immediately** — so under `manage.sh` you'll see "setup_pymodules.sh finished" while the real work is still running in the other window. Once elevated it adds a Windows Defender `-ExclusionPath` for the **entire Python install directory** (the folder containing `sys.executable`, errors silenced). That is broad — it exempts all Python code there, not only `impacket` — and is the automation of the AV-exclusion advice under Troubleshooting → SMB. `manage.sh` warns before launching it. Don't copy or extend this without the operator's say-so.
3. Backs up the current `requirements.txt` / `constraints.txt` to temp files and enters `PHASE="generate"`.
4. **`constraints.txt` is truncated and rewritten** (its header comment says so). **`requirements.txt` is not** — it is only `touch`ed, and then each managed package's line is replaced in place with `sed` or appended if absent. Comments and lines for unmanaged packages survive. The "truncated and rewritten from scratch" header text is written into `constraints.txt` only; it does not describe `requirements.txt`. Treat `constraints.txt` as a build artifact; edits to a *managed* package's line in `requirements.txt` are overwritten on the next run.
5. For each entry in `packages=(...)`:
   - **Termux and the package is in `SYSTEM_MANAGED`** (`bcrypt`→`python-bcrypt`, `cryptography`→`python-cryptography`, `pyppmd`→`python-pyppmd`, `psutil`→`python-psutil`, `pynacl`→`""`): strip any stale line from `requirements.txt`, run `pkg upgrade -y <termux-name>`, then lock `pkg==<installed version>` into `constraints.txt`. Never pip-built — PyPI has no Android wheels and a from-source build breaks against bionic libc (same failure family as pynacl/libsodium). `pynacl` has no Termux package; it is only locked (built once by `termux_setup.sh` with `SODIUM_INSTALL=system`).
   - **Otherwise**: `pip index versions <pkg_base>` → newest version → written as `pkg<next_major>` — a **ceiling only, no floor**, on purpose (the script's comment: a floor at "newest today" removes pip's only way to resolve a conflict, backing off to an older compatible version). If `COMPAT_CEILING[pkg]` is set, that string is used verbatim instead. If the version can't be fetched: `[WARN]` and skip, leaving the existing line untouched.
   - **Extras** (`"hypercorn[h3]"`): written verbatim; `pkg_base` (extras stripped) is used for `pip` queries; `pkg_regex` (regex-escaped) is used in every `grep`/`sed` pattern. Never put a raw `$pkg` inside a pattern — `[` `]` would be parsed as a character class.
6. Dry-run resolve: `pip install -r … -c … --upgrade --dry-run`. On failure it prints the conflict lines and the log path, then **`exit 1`**.
7. Prompts "install/update now? (y/n)". On `y`: `python -m pip install -r … -c … --upgrade --no-cache-dir`, then `pip check` (warns only).

**Managed package list** (single source of truth — post-ASGI-migration: no Flask/waitress/cheroot): Quart, bcrypt, zipstream-new, Werkzeug, watchdog, `hypercorn[h3]`, cryptography, mammoth, openpyxl, python-pptx, rarfile, pyzipper, py7zr, pyvips, wsgidav, asgiref, paramiko, pyftpdlib, psutil, pynacl, pyppmd, impacket, pyOpenSSL. Add a package by adding it to `packages=(...)`; add a Termux-managed one to `SYSTEM_MANAGED` as well; record a known cross-package cap in `COMPAT_CEILING`.

**Ctrl-C contract** — pairs with `manage.sh`'s handled trap (above): `trap _on_interrupt INT TERM` → exit **130**; `trap _cleanup_backups EXIT` removes the temp backups.

| `PHASE` when Ctrl-C lands | Result |
|---|---|
| `init` | Nothing was touched, nothing to undo. |
| `generate` | Both files restored from backup (or deleted, if they didn't exist before). "Nothing was changed." |
| `prompt` | Files stay regenerated; prints the manual `pip install -r … -c …` command. |
| `install` | Files stay; warns the install was interrupted and to re-run or `pip check`. |

*From reading the code:* `PHASE` stays `generate` through the dry-run resolve, so Ctrl-C during that (slow) step also rolls back — but a dry-run **conflict** (`exit 1`) does **not** roll back. The regenerated, unresolvable files are left in place.

**⚠️ Known issues — flagged, not fixed** (they are code changes; this pass only updated docs)
1. **Floor pins are erased.** *Verified*: `Quart>=0.21.0,<1` becomes `Quart<1`. The Troubleshooting entry "`Quart<1` (unpinned) resolves an old pre-0.19 Quart…" documents that floor as the fix for a real production crash. The script's ceiling-only philosophy is defensible, but as written it silently reverts that fix. The mechanism already exists to keep a floor without changing the philosophy: `COMPAT_CEILING[Quart]=">=0.21.0,<1"` — *verified* that the value is appended verbatim.
2. **GNU/bash-4 only.** Uses `declare -A`, `grep -oP`, and GNU-style `sed -i -E`. Fine on Linux, Git Bash, and Termux; stock macOS (bash 3.2, BSD grep/sed) would fail — `pip index` lookups would all report "Could not fetch version" and be skipped. *(Inferred from the constructs; not run on macOS.)*
3. **Interpreter mismatch is possible.** `pip index`, `pip show`, the dry-run, and `pip check` use bare `pip`; the real install uses `python -m pip`; the Defender step uses bare `python`. `PYTHON=… ./manage.sh update-modules` is **not** passed through. If `pip` and `python` resolve to different installations, the conflict check and the real install run against different environments.

### security.txt Management (manage.sh security-txt)

New `manage.sh` subcommand — updates `static/.well-known/security.txt` (RFC 9116) without a dedicated Python script; the whole thing is a bash function plus an inline Python heredoc for parsing/formatting, following the same pattern `_launch_detached()` already uses elsewhere in the file.

```bash
./manage.sh security-txt                      # interactive prompt (blank keeps current value)
./manage.sh security-txt show                  # print the current file
./manage.sh security-txt \
  --contact you@example.com \
  --expires 2030-09-03 \
  --preferred-lang en,fil \
  --canonical https://yourdomain.com/.well-known/security.txt
```

- **Partial updates**: only the flags passed are changed — any existing `Contact`/`Expires`/`Preferred-Languages`/`Canonical` (or other custom field) already in the file is read first and preserved. On a brand-new file, all four required fields must be present after applying the flags, or it errors out listing what's missing.
- **`--contact`**: a bare email is auto-prefixed to `mailto:`; a value already starting with `mailto:`, `http:`, `https:`, or `tel:` is left as-is.
- **`--expires`**: normalized to the exact `YYYY-MM-DDTHH:MM:SS.sssZ` format RFC 9116 expects (also what the person originally specified) — `YYYY-MM-DD` alone becomes that date at `23:00:00.000Z` UTC, a datetime missing milliseconds/`Z` gets them appended, and an already-exact value passes through unchanged.
- **`--expires-in-days N`**: convenience alternative to `--expires` — computes `now (UTC) + N days` and formats it the same way, mirroring the `--expires-in` convention `revoke_sharing.py` already uses for share links.
- **`--preferred-lang`**: comma-separated codes are re-joined with `", "` regardless of the spacing typed in (`en,fil` and `en, fil` produce the same output line).
- Menu option **18** in `cmd_menu` (it was 17 when added; `restart-webdav` later took slot 8 and shifted everything below it by one — see the [menu map](#managesh-internals--editing-rules)); the Termux-only setup option is now **19**.
- File path is fixed at `${SCRIPT_DIR}/static/.well-known/security.txt`; the directory is created automatically if it doesn't exist yet.

### WebDAV Recovery (manage.sh restart-webdav)

🆕 (2026-09-09) Recovers a wedged-but-alive WebDAV listener (e.g. the Hypercorn SSL-shutdown-timeout issue — see Troubleshooting — after a large cancelled download) **without restarting the main server**. Also available as interactive menu option **8**.

```bash
./manage.sh restart-webdav
```

Reads WebDAV's real PID from `.manage_pids/webdav.pid`, signals it directly (POSIX: `SIGTERM`, then `SIGKILL` after ~5s; **Windows: `taskkill //F` immediately — there is no graceful phase on Windows**, which corrects the "after ~5s" wording elsewhere in this doc), then waits up to 10s (20 × 0.5s) for a *different* PID to appear in the pidfile, and relies on the already-running server's own watchdog thread to notice the exit and respawn WebDAV automatically — `manage.sh` itself never spawns the replacement, it only confirms a new PID appeared. Requires a server (`prod` or `dev`) to already be running — errors out otherwise, since there'd be no watchdog to do the respawning. See [WebDAV Process Isolation, Watchdog & restart-webdav](#webdav-process-isolation-watchdog-restart-webdav-2026-09-09) under Protocol Servers for the full mechanism and why this can't just call `protocol_manager.restart_webdav()` directly.

### User Management (manage_users.py — renamed from create_user.py)

> ⚠️ The file itself still has a stale self-reference (`Run: python create_user.py` in its own docstring) — that's a leftover from the rename, not a typo here. The actual filename and the correct command are `manage_users.py`.

```bash
python manage_users.py
# Menu:
# 1. List users (flags any account still on a default password)
# 2. Add user
# 3. Change password
# 4. Change role (readwrite/readonly)
# 5. Delete user
# 6. Remove default users — deletes admin/guest ONLY if their password is
#    still unchanged from the shipped default; does NOT reset a password
#    back to default (for that, see debug_passwords.py's option 4 below)
# 7. Exit
```
Every action re-runs the default-credentials warning banner afterward, so it stays visible across the whole session rather than only at startup.

### Database Tools

**reset_db.py** - Wipe and recreate database:
```bash
python reset_db.py
# Deletes db/ folder entirely
# Recreates with default credentials
# Use: database corrupted, security breach, clean slate
```

**revoke_session.py** - ⚠️ **Superseded by `kick_sessions.py`** (see its own section below) — kept here for history, but new work should use `kick_sessions.py logout-web` instead, which does the same thing plus per-user rotate/delete and a `kick-all` option:
```bash
python revoke_session.py
# Rotates server_token in database
# All sessions invalidated within 5 seconds
# Use: security incident, force re-login
```

**revoke_sharing.py** - Manage share links from the command line, without the web UI. Despite the name it now also **edits** shares and works the **approval queue** (reviewed 2026-09-21):
```bash
python revoke_sharing.py                          # interactive 8-item menu, loops until Exit (0)
python revoke_sharing.py list                     # active shares (token, name, type, mode, expiry, creator, downloads, path)
python revoke_sharing.py revoke <token> [--yes]
python revoke_sharing.py revoke-path <path> [--yes]
python revoke_sharing.py revoke-all [--yes]       # ALWAYS requires typing back a fresh random 10-digit code; --yes skips only the y/N
python revoke_sharing.py edit <token>             [--mode public|passkey|approval]
                                                  [--passkey KEY | --generate-passkey | --clear-passkey]
                                                  [--expires-in 1h|2d|30m|7d|SECONDS | --never-expire]
python revoke_sharing.py edit-path <path>         # same flags as edit
python revoke_sharing.py requests                 # pending approval-mode access requests
python revoke_sharing.py approve <request_id> [--max-downloads N]   # default 1
python revoke_sharing.py deny <request_id>
```
Via `manage.sh`: `./manage.sh revoke-shares [args]` (menu **17**) — every argument passes straight through to the script.

**Behavior**
- Talks directly to the `database.py` `db` singleton — no HTTP, no running server required. Its docstring still says "the Flask app" (stale since the Quart migration); the script only imports `database`.
- `approve`/`deny` record `decided_by = "cli:<os-username>"` (falls back to `"cli"`), so the admin UI's history shows the CLI as the source. *(Verified.)*
- `--expires-in` accepts `^\d+\s*[smhdw]?$` (a bare number is seconds) and is converted to an absolute epoch (now + N). If `--never-expire` is also given, it wins.
- **Interactive menu**: Ctrl-C / Ctrl-D / closed stdin at the top prompt exits **0** quietly; inside an action it prints "Cancelled." and returns to the menu. A `sys.exit()` from a `cmd_*` helper (e.g. wrong revoke-all code) is swallowed by the loop, and other exceptions print `❌ Unexpected error` — neither ends the menu. Menu-driven revokes never pass `--yes`.
- **One-shot exit codes**: `0` success or cancelled-at-prompt · `1` not found / failed / wrong revoke-all code / stdin closed mid-prompt · `130` Ctrl-C. Under `manage.sh`, `run_utility` reports 130 as "interrupted", not "failed".

**Gotchas** (1–2 *verified by running the script against a stubbed `db`*; 3–4 read from the code)
1. **`--passkey` and `--generate-passkey` silently do nothing unless the *resulting* mode is `passkey`** — i.e. `--mode passkey` was also passed, or the share is already in passkey mode. On a public or approval share they are dropped; if nothing else was passed the script prints "Nothing to change" and exits **0**. The flag's own `--help` ("implies --mode passkey") is wrong. Always pass `--mode passkey` explicitly; in scripts, exit code 0 hides the no-op.
2. **Leaving passkey mode doesn't clear the passkey from the CLI side — confirmed 2026-09-22.** `edit --mode approval` sends only `security_mode` to `db.update_share_settings()`, never `clear_passkey`. Read directly in `database.py`: `update_share_settings()` only clears `passkey_hash` when `clear_passkey=True` is passed explicitly — nothing in it clears a passkey automatically on a mode change. The doc text under [Sharing Routes](#sharing-routes) claiming `/api/share/settings` "also handles clearing a passkey when switching away from passkey mode" must therefore be implemented in `app.py`'s route handler itself, not in `database.py` — `app.py` is still unread by any pass to date, so that claim remains unverified, and until it is, assume the CLI and the web UI behave differently here. **Always pass `--clear-passkey` explicitly when moving a share off passkey mode via `revoke_sharing.py`.**
3. **Non-cryptographic RNG.** `_generate_passkey()` (8 chars from an ambiguity-free alphabet) and the revoke-all confirmation code both use Python's `random`, not `secrets`. Harmless for the confirmation code (it only guards against accidents); a *passkey* should come from `secrets.choice`. Whether the web UI's "generate" path uses `secrets` wasn't checked.
4. **No live push to the admin UI.** The CLI writes to the database from a separate process and never touches `realtime_shares.py`'s event manager, which lives in the server's memory. An open Manage Shared panel therefore won't update by itself after a CLI approve/deny/revoke/edit until it refetches. *(Inferred from the code; not tested against a live server.)*

**debug_passwords.py** - Test login credentials:
```bash
python debug_passwords.py
# Menu:
# 1. Show all users
# 2. Test common passwords against all users
# 3. Test custom username/password
# 4. Reset admin + guest to default passwords (admin123/guest123)
# 5. Exit
```
Note the division of labor with `manage_users.py`: that tool's "Remove default users" only *deletes* accounts still on the shipped default password — this tool's option 4 is the one that actually resets a password back to a default value.

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
| `/admin/shares`, `/admin/shares/count` | GET | List / count active share links | readwrite |
| `/admin/shares/requests`, `/admin/shares/requests/stream` | GET | Pending share-access requests (list + live SSE) | readwrite |
| `/admin/shares/requests/<id>/approve`, `/deny` | POST | Decide a pending share-access request | readwrite |
| `/admin/revoke_all_shares/code`, `/admin/revoke_all_shares` | POST | Danger-zone: revoke every active share (typed-code confirmation) | readwrite |

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
| SMB credential refresh | O(n) diff | ~every 30s | Skips unchanged users, no UID churn |
| Concurrent web UI requests | Single event loop (Hypercorn) | One blocking sync call stalls every user, not just one — see Troubleshooting → Quart/Hypercorn Migration Issues | `asyncio.to_thread` for all heavy sync work |
| Web UI HTTPS connection | HTTP/1.1, HTTP/2, or HTTP/3 | Client-negotiated, no config needed | Hypercorn ALPN |
| WebDAV HTTPS connection | HTTP/1.1 only 🆕 (2026-09-09) | Deliberately not offering h2 — most real WebDAV clients can't speak it; see Troubleshooting | Hypercorn ALPN, `webdav_server.py` |

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

**Problem**: SFTP connects and lists the root fine, but every subfolder shows the same (root) contents, only on Windows  
**Cause**: `ntpath.join()`'s absolute-path-reset behavior — see the "Windows path-join bug" note in SFTP Implementation Notes above; this is fixed in the current `_make_realpath()`, so if it recurs the deployed `sftp_server.py` is stale  
**Fix**: Update to the current `sftp_server.py`

**Problem**: SFTP/FTP "searching for host then error"  
**Cause**: Windows Firewall blocking ports 2222, 2121, 60000-60100  
**Fix**: Add inbound firewall rules; verify with `Test-NetConnection -Port 2222`

**Problem**: FTP file transfer starts but stalls/fails  
**Cause**: Passive data ports (60000-60100) blocked by firewall  
**Fix**: Add firewall rule for ports 60000-60100 TCP inbound

**Problem**: SMB `[Errno 22] Invalid argument` on import (Windows)  
**Cause**: Windows Defender quarantined part of `impacket` (heuristic flag — it's also a pentesting-toolkit component)  
**Fix**: Add a Defender exclusion for impacket's install folder, then `pip install impacket --no-cache-dir`

**Problem**: SMB stuck on port 8445, won't use 445  
**Cause**: `smb_setup.py` hasn't been run, or Windows hasn't been restarted since it was  
**Fix**: Run `python smb_setup.py`; on Windows, **Restart** (not Shut Down — Fast Startup can skip re-applying the change)

**Problem**: SMB login fails despite a correct password  
**Cause**: Account predates SMB support — `nt_hash` is `NULL`, NTLM has nothing to verify against  
**Fix**: Reset the password once (even to the same value); check who's affected via `db.users_missing_nt_hash()`

**Problem**: `NetBIOSTimeout` traceback in the console  
**Cause**: impacket's normal 5-minute idle timeout — expected, not an error  
**Fix**: Confirm the deployed `smb_server.py` has `_quiet_handle_error` wired in (`inner.handle_error = _quiet_handle_error` in `start()`) — if it's still printing, the file is stale, not a Python-version issue

**Problem**: MS Office "Ctrl+S" throws a permission error, or the SMB connection drops during a large copy  
**Cause**: Windows file-locking limitations (`WinError 32`) or an unhandled exception in a rarely-hit SMB2 code path  
**Fix**: Update to the latest `smb_server.py` — three layered fixes already applied (rename/delete retry, `FILE_SHARE_DELETE` on open, command safety net); if it recurs, set `SMB_DEBUG_FILES=1` for file-lifecycle logging

### Quart/Hypercorn Migration Issues (post-4.0)

**Problem**: `internal error` (500) downloading a shared file, but folder-zip shares work fine  
**Cause**: Quart's `send_file()`/`send_from_directory()` kept Flask's *older* keyword names (`attachment_filename`, `cache_timeout`) rather than modern Flask's (`download_name`, `max_age`) — an earlier migration pass await-wrapped every `send_file` call but never checked the kwarg names, so 10 call sites (single shared-file download, single-item-from-folder download, every HLS/video/image-cache send) were silently 500ing  
**Fix**: All 10 call sites updated to `download_name=`/`max_age=`; verify with `inspect.signature(app.send_file)` against actual usage if this class of bug recurs

**Problem**: Login always fails right after a fresh startup, even with correct default credentials  
**Cause**: Two stacked `database.py` bootstrap races: (1) `_bootstrapped` flag was set *before* schema creation actually ran, and (2) even after fixing that with double-checked locking, `_do_bootstrap()` never called `conn.commit()` — under WAL-mode snapshot isolation, a different thread's brand-new connection opened right after the lock released could query before the bootstrap transaction committed, seeing zero rows despite "Seeded default users" already having printed  
**Fix**: Double-checked locking around bootstrap + an explicit `conn.commit()` before releasing the bootstrap lock

**Problem**: Everything feels sluggish under load — one slow image preview seems to freeze the whole app for every user, not just the one who requested it  
**Cause**: Waitress ran each request in its own OS thread, so a blocking call only slowed that one request. Hypercorn runs a single event loop — any synchronous blocking call in a route handler freezes the entire app for every concurrent user until it returns. Real offenders found: `image_preview`'s direct `Event.wait(timeout=60)`/`t.join(timeout=60)` (up to 60s app-wide freeze per conversion — the single biggest culprit), `archive_preview`/`office_preview` running their conversion libraries synchronously in the coroutine body, three `storage.list_dir()` call sites, `bcrypt.checkpw`/`bcrypt.hashpw` on login and passkey verification/creation, and `clear_media_preview`'s cache walk  
**Fix**: Wrapped each in `asyncio.to_thread` — either at the call site directly, or (for the two large conversion functions) renamed the body to a plain sync helper with a thin async wrapper around it. Quart's request/`jsonify` context-locals do propagate correctly into `asyncio.to_thread` workers via contextvars (verified directly before relying on it). `webdav_server.py` needed no equivalent fix — `asgiref.WsgiToAsgi` already runs each WSGI request, including its own bcrypt auth checks, in its own thread automatically via `@sync_to_async`

**Problem**: Public share access requests never seem to reach the server ("stuck on pending" for a request that was never actually submitted)  
**Cause**: App-wide `CSRFProtect(app)` wasn't exempting the two anonymous share routes (`/shared/<token>/request`, `/shared/<token>/passkey`) — every visitor POST 400'd with "CSRF token missing" before reaching the database, since an anonymous visitor has no session-tied CSRF token to send  
**Fix**: `@csrf.exempt` added to both routes

**Problem**: `hypercorn` crashes on startup with a `TypeError`/`AttributeError` around `record.process`, only on Python 3.14  
**Cause**: Hypercorn's default `errorlog="-"` builds an internal logger with a `%(process)d` formatter; a Python 3.14 logging-module behavior change means `record.process` can come back `None`  
**Fix**: Pass a pre-built `logging.Logger` via `Config.errorlog` instead of the default string target, so Hypercorn's `_create_logger()` skips its own crashing formatter construction. Applied in both `prod_server.py` and `webdav_server.py`

**Problem**: `Quart<1` (unpinned) resolves an old pre-0.19 Quart on a fresh install, which crashes importing `werkzeug.urls.url_quote` (removed in modern Werkzeug)  
**Fix**: requirements.txt pins `Quart>=0.21.0,<1`. ⚠️ **As of the 2026-09-21 review, running `setup_pymodules.sh` (`./manage.sh update-modules`) rewrites that line to `Quart<1`** — it writes ceilings only, by design — which removes this fix. Verified by running the script's own grep/sed against a seeded file. To keep the floor, add `[Quart]=">=0.21.0,<1"` to the script's `COMPAT_CEILING` table (its value is appended verbatim after the package name). See [Package Management](#package-management-setup_pymodulessh).

**Problem**: Ctrl+C doesn't cleanly stop `prod_server.py` on Windows  
**Cause**: The custom shutdown-trigger signal handler called `loop.add_signal_handler()` unconditionally — Windows' `ProactorEventLoop` never implements it, raising `NotImplementedError`  
**Fix**: Added the same `try/except → signal.signal()` fallback Hypercorn's own internal code already uses in its no-`shutdown_trigger` path

**Problem**: ZAP scan flags "Big Redirect Detected" on the site's root 301  
**Cause**: Quart's default `redirect()` includes an HTML fallback-link body, which pushed the two 301s inside `validate_session`'s `before_request` hook past ZAP's size heuristic  
**Fix**: `_lean_redirect()` helper — empty-body `Response`, explicit status code, same `Location` header — used in those two call sites only (not `login_required`, which is unrelated and defaults to 302)

**Problem**: ZAP Attack Mode flags a High-confidence-Low Path Traversal on `GET /static//...`  
**Cause**: False positive — the double-slash probe didn't match Quart's built-in `/static/<filename>` route, fell through to the login-gated catch-all `@app.route("/<path:path>")` (`index()`), which redirected to `/login` and returned 200, indistinguishable from a real page to the scanner. `index()` already runs `storage.is_safe_path()`/`is_valid_path()` before touching disk, same guard as everywhere else in the app  
**Fix (defense in depth, not because the traversal was real)**: early `if path == "static" or path.startswith("static/"): abort(404)` in `index()` so malformed `/static/*` requests get a clean 404 instead of falling into the authenticated catch-all

**Problem**: Custom 404 page's "Go Back" button (and its 10-second auto-redirect-home) silently does nothing  
**Cause**: The `<script src="...404.js">` tag's hardcoded `integrity` (SRI) hash was stale — didn't match 404.js's actual current content — so browsers silently refused to execute the script at all under the site's `script-src 'self'` CSP (no `unsafe-inline`)  
**Fix**: Recomputed and updated the SRI hash. The "Go Back" button was later removed from the 404 page entirely (design decision, not a further bug) — `history.back()` was a no-op anyway for a visitor with no prior page in that tab's session history, and "Go Home" already covers that case

**Problem** (RESOLVED — was UNRESOLVED 2026-09-11 to 2026-09-14): `/login` intermittently took ~45s–131s to load on Android Chrome's normal (non-incognito) profile only — incognito, desktop Chrome, and other browsers were unaffected. Logging out showed the same delay. Temporarily "fixed" by clearing the browser's site data, but recurred after a period of normal use.  
**Cause**: `/login` (GET) sent `Clear-Site-Data: "cache"` on every anonymous page view (whenever `_request_is_secure()`), forcing the browser to synchronously wipe its *entire* origin disk cache — every cached CSS/JS/font/media-preview asset — before it could finish rendering the page. Confirmed via a live recurrence on an old phone: the request-timing log (added while investigating — see below) showed every request completing in 0.000–0.016s, proving the app/server itself was never blocked; the delay was entirely client-side, after the response was already sent. Worse on older/slower-storage phones because deleting a large number of individual disk-cache entries is real, scaling I/O — explains both the device-specificity and why it visibly got worse the longer a normal profile went between manual clears (bigger accumulated cache → more to wipe next time).  
**Fix**: `/login` GET now sends `Clear-Site-Data: "storage"` only — not `"cache"` (the expensive part, no security benefit on a pre-auth page anyway) and deliberately not `"cookies"` either, because `generate_csrf()` sets `session["csrf_token"]` on first render, which makes Quart's session interface emit `Set-Cookie` on that same response — racing that against `Clear-Site-Data:"cookies"` on the same response risks wiping the just-issued CSRF cookie before the form is even shown, breaking every fresh visitor's login POST. `"storage"` (localStorage/IndexedDB, near-empty for this app) is cheap and collision-free, and was kept specifically to satisfy a site-security scanner (targeting ISO/OWASP-style compliance) that scores the header's mere presence — full removal measurably dropped that score, `"storage"`-only recovered it. `/logout` is unchanged, still the full `"cache", "cookies", "storage"` — that's the correct place for a comprehensive clear (an actual state-ending action, not a passive page view), and has no cookie-race risk since logout uses explicit `response.delete_cookie()` rather than a session-modification-triggered `Set-Cookie`.  
**Ruled out along the way** (kept for reference, in case something adjacent resurfaces):
  - *HSTS lockout* — a real, separate issue existed (`_request_via_trusted_tls()`'s header-based trust check let a dynamic HSTS entry get set even though the self-signed origin can't satisfy it), confirmed via `chrome://net-internals/#hsts`. Ruled out as the cause of *this* hang because `files.ccustomdomain.com` (covered by the same `includeSubDomains` policy) loaded fine throughout, and the hang persisted even after fully disabling HSTS at the Cloudflare dashboard. The underlying HSTS design issue (self-signed origin reachable under the same hostname HSTS pins) is still worth closing off — see hostname-separation note below — but is independent of this bug.
  - *Cloudflare bot-challenge* (`/cdn-cgi/challenge-platform/...`, seen in a chrome://net-export capture) — ruled out because the hang reproduced identically on direct LAN IP access, which never touches Cloudflare.
  - *A genuine server-side TTFB stall* — an early `curl -w` timing test appeared to show a ~131s stall inside app.py/Hypercorn, but was later found to have been run against the wrong IP by mistake. The final request-timing log (0.000–0.016s across the board during a live recurrence) is the real evidence that the server side was never the problem.
**Diagnostic tooling added while investigating** (kept permanently, not just for this bug): request logging in `app.py`, registered as the first `before_request`/`after_request` pair (right after `app = Quart(__name__)`) so the timer wraps the entire request lifecycle. Logs **every** request — `<method> <path> took X.XXXs (status N)` at INFO, escalating to `SLOW REQUEST: ...` at WARNING over `SLOW_REQUEST_THRESHOLD_SECONDS` (default 2.0s) — via its own logger (`cloudinatorftp.requests`, project-standard timestamp format, not Quart's default `app.logger` — that default's `%(module)s` field caused a cosmetic `(unknown file)` glitch, same class of issue as the Python 3.14 `%(process)d` bug documented above). Writes to both console and a persistent `logs/requests.log`. This log is what ultimately solved the bug — worth keeping for whatever comes next.  
**2026-09-23 addition**: each line now also carries the client IP (via `get_client_ip()`) ahead of `<method> <path>`, plus a `[XFF: ...]` tag when the raw `X-Forwarded-For` header disagrees with the trusted `CF-Connecting-IP` value — see the 2026-09-23 sync note near the top of this doc for the full reasoning. Originally added after a suspected-attack review of these logs turned up no source IP to investigate.  
**Longer-term fix, still open, unrelated to this bug**: reserve the public hostname exclusively for the Cloudflare-fronted trusted-cert path; never let the self-signed origin answer under that same hostname (use the Tailscale `*.ts.net` hostname for direct/LAN access instead). Closes off the HSTS design issue above permanently.

**Problem**: `protocol_manager.py`'s two `logging.getLogger(__name__).debug(...)` calls (subprocess/thread stop-error logging) never produced output anywhere, console or file  
**Cause**: No `logging.basicConfig()` call exists anywhere in the project, and nothing else configured a handler for that logger name — combined with `DEBUG` being below the default `WARNING` threshold, the calls were dead code from the start  
**Fix**: Added an explicit module-level logger (`_pm_logger`) near the top of `protocol_manager.py` with a `StreamHandler` using the project's standard timestamp format, `setLevel(logging.DEBUG)`. Both call sites now use `_pm_logger.debug(...)` instead of re-fetching an unconfigured logger inline. Found while auditing all logging call sites for consistent timestamps (same session as the request-logging work above) — unrelated to the `/login` hang itself.  
**Note**: `prod_server.py`'s ~45 and `protocol_manager.py`'s ~13 `print()` calls (startup banners, protocol-server status) and `app.py`'s ~209 scattered `print()` calls remain plain, untimestamped stdout — deliberately left alone as cosmetic/one-time CLI output rather than converting everything to logger calls in the same pass; revisit only if that output specifically becomes relevant to a future investigation.

**Note**: superseded by the entry directly below — as of 2026-09-15, `prod_server.py`'s ~45, `protocol_manager.py`'s ~13, and `app.py`'s ~209 `print()` calls ARE captured now too, via `logging_setup.py`'s stdout/stderr tee. Left in place as a record of the original, narrower scope decision.

**Problem**: Logging was split across multiple places with no daily rotation — `app.py`'s request logger wrote its own `logs/requests.log`; `prod_server.py` had no file output of its own at all (whoever launched it was expected to shell-redirect stdout to a manually timestamped filename, e.g. `python3 prod_server.py > logs/prod_server_2026-09-09_15-56-44.log`); `protocol_manager.py`'s debug logger (see previous entry) wrote to yet another console stream; `manage.sh` separately generated its own fresh timestamped file on every `start` and redirected the whole child process's stdout+stderr there. All of these had the same underlying flaw: whatever generated the filename did so once, at process start, and never revisited it — a process running since Sept 9 with no restart would still be writing into a file named `..._2026-09-09_....log` a week later. Plain `print()` calls (~267 across the project) had no capture path of their own beyond whatever redirect happened to be wrapping the process at the time.  
**Cause**: No shared logging infrastructure existed — each module either rolled its own handler or relied on an external shell/manage.sh redirect, and nothing in Python itself ever recomputed the log filename after the process started; OS-level stdout/stderr redirection is fundamentally unable to fix this on its own, since a file descriptor is bound to one file for the life of the process.  
**Fix**: New `logging_setup.py` module, arrived at after a few same-day iterations (full back-and-forth preserved in the module's own docstring). Final design:
  - `DailyDatedFileHandler` (custom `logging.Handler`) checks the date on every single `emit()` and writes to `logs/{prod|dev}_server_YYYY-MM-DD.log`, transparently opening a new file the instant the date changes — no restart required, unlike `logging.handlers.TimedRotatingFileHandler`, whose *live* file keeps a fixed name and only *past* days get a dated suffix once an actual rollover happens. Prefix (`prod_server`/`dev_server`) is detected from which script is `__main__`, fixing a bug where it was hardcoded to `"prod_server"` always.
  - One central logger (`"cloudinatorftp"`) owns this file handler plus a console `StreamHandler`; every other logger in the project (`app.py`'s `request_logger` and new general-purpose `app_logger`, `prod_server.py`'s Hypercorn errorlog via `_build_hypercorn_logger`, `protocol_manager.py`'s `_pm_logger`) is a child logger (`logging_setup.get_logger(name)`) with no handlers of its own, funneling into the same file.
  - `_TeeStream` replaces `sys.stdout`/`sys.stderr` so plain `print()` calls are captured too — tagged `[PRINT]`/`[STDERR]` to distinguish them from real `[INFO]`/`[WARNING]`/etc. logger lines — while still appearing on screen for foreground/interactive runs. No changes needed at any of the ~267 individual `print()` call sites.
  - `sys.excepthook`/`threading.excepthook` log uncaught exceptions (main thread and background threads both) through the same mechanism as `CRITICAL`, with full traceback — so crashes get correct rotation too.
  - `manage.sh` (see next entry) no longer touches the child process's stdout/stderr at all — full capture happens entirely inside the Python process now, with no OS-level redirect involved anywhere.  
  `logs/requests.log` is retired (old file left alone as a historical archive). `dev_server.py` inherits all of this automatically via its existing `from app import app` import.  
**Verified**: a standalone smoke test (logger calls + plain `print()` + stderr writes) confirmed every line lands in the file exactly once, correctly tagged, with matching timestamps down to the second.

**Problem**: `manage.sh` had its own separate, parallel logging scheme (fresh `logs/{type}_server_<full-datetime>.log` per `start`, full stdout+stderr redirect) that collided with the `logging_setup.py` work above — two different files, two different naming/rotation policies, duplicate content, and `manage.sh`'s `logs`/`status`/`clean-logs` commands had no awareness of the new Python-managed file at all.  
**Cause**: `manage.sh` predates `logging_setup.py` and was never reconciled with it when it landed.  
**Fix**: Removed `logpath_file_for()` and all `.logpath` tracking — the log path is now fully deterministic (`current_log_for()` computes `logs/{type}_server_$(date +%Y-%m-%d).log` directly, no per-start bookkeeping). `_launch_detached` discards the child's stdout/stderr entirely (`/dev/null`) rather than redirecting them anywhere — full capture, including plain `print()` calls and crash tracebacks, is handled entirely by `logging_setup.py`'s tee and exception hooks instead (see entry above), so nothing needed to be captured at the OS level at all. `cmd_start`/`cmd_stop` simplified accordingly (no more `lp_file`). `cmd_logs -f` needed **no changes** — it was already tailing the computed current-day path independently of how the child's streams were wired, so `manage.sh logs -f` continues to follow the live Python-managed file exactly as before. `clean-logs` also needed no changes — its `*_server_*.log` glob already matched the new daily-dated naming. Help text updated to describe the new one-file-per-day-per-type behavior.  
**Operational note**: once this ships, launch `prod_server.py` *without* any old manual shell log redirect — Python now owns that file directly, end to end.

**Problem** (REGRESSION, found 2026-09-15 after the logging unification above shipped): `./manage.sh start server` shows a WebDAV crash-loop forever — `⚠️ WebDAV process exited unexpectedly (code 1) — respawning in 3s...` repeating indefinitely — and also produces an unexpected second log file, `logs/app_YYYY-MM-DD.log`, which on Windows can't be deleted (`⛔ file in use`) until a lingering `python.exe` process is killed manually. Running `python prod_server.py` directly (no `manage.sh`) does **not** reproduce either symptom — only `logs/prod_server_YYYY-MM-DD.log` is created, and WebDAV starts cleanly.  
**Cause (two bugs, same root trigger)**:
  1. `manage.sh`'s `cmd_stop` only ever killed the tracked `prod.pid`/`dev.pid` — it never touched `webdav.pid`. WebDAV runs as its own OS process specifically so a wedged listener can be recovered independently (see WebDAV Process Isolation below), but that isolation cuts both ways: `taskkill //F //PID` (no `//T`, i.e. no kill-tree) and POSIX `kill "$pid"` (SIGTERM to one PID, not children — `os.setsid()` in `_launch_detached` puts the whole tree in a new *session*, but a single-PID signal still only reaches that one PID) both leave the WebDAV child running as an orphan after every `stop`. The orphan keeps its port bound. The very next `start` spawns a fresh WebDAV subprocess that immediately fails to bind (`OSError: address already in use`) and exits with code 1 — an unhandled exception at import/bind time, which is exactly `code 1`. `protocol_manager.py`'s watchdog sees a real, non-zero exit and dutifully respawns every 3s forever, but the orphan holding the port is never touched, so every respawn fails identically — hence the infinite loop. (This also explains the "stale python process" in the symptom report: it's the orphaned WebDAV process from the *previous* `stop`, not the crash-looping one.)
  2. Independently, `logging_setup.py`'s `_LOG_PREFIX` detection (see the `prod_server`/`dev_server` fix two entries above) only recognized those two script names — `webdav_server.py`, spawned by `protocol_manager.py` as its own OS process with its own `__main__`, was never one of them, so every WebDAV process (crash-looping or not) fell through to the `"app"` fallback and wrote its own separate `logs/app_YYYY-MM-DD.log` instead of joining the parent's file. Each crash-loop respawn opens that file freshly; the *orphan* left behind by bug 1 keeps its handle open indefinitely, which is what makes the file undeletable until that specific process is killed.
  Bug 2 is why the second log file exists at all; bug 1 is why it's more than a cosmetic annoyance — it's the same orphan process responsible for the crash loop, and it needs `logging_setup`'s `_LOG_PREFIX` fallback to have already been exercised (i.e. at least one prior successful `stop`/orphan) before it becomes visible.  
**Fix**:
  - `manage.sh`: new `_kill_webdav_child()` helper (same kill → wait → SIGKILL escalation `cmd_restart_webdav` already used), now also called from `cmd_stop` (and therefore `cmd_restart`, which calls `cmd_stop`) right after the main PID is stopped. `stop`/`restart` now clean up both processes, not just the tracked one.
  - `protocol_manager.py`: `_spawn_webdav_process()` now passes `env=` explicitly when launching `webdav_server.py`, setting `CLOUDINATOR_LOG_PREFIX` to this (parent) process's own already-resolved `logging_setup._LOG_PREFIX` (`"prod_server"` or `"dev_server"`).
  - `logging_setup.py`: `_LOG_PREFIX` now checks `CLOUDINATOR_LOG_PREFIX` first, before falling back to `__main__`-name detection. WebDAV's log lines land in the same daily file as everything else; no more second `app_*.log`.
**Verified**: reasoned through against the actual code paths (`cmd_stop`'s taskkill/kill calls, `_spawn_webdav_process`'s `Popen` call, `_LOG_PREFIX`'s fallback chain) — not yet confirmed against a live `manage.sh start`/`stop`/`start` cycle on the user's machine. If the crash loop persists after this fix, capture `webdav_server.py`'s actual traceback by running `python webdav_server.py` directly in the foreground (its own crash output is otherwise swallowed by `manage.sh`'s BG-mode `/dev/null` redirect) — that would point to a different bind conflict (e.g. something else entirely on port 8080) or a real code bug in `webdav_server.py` rather than this orphan-process cause.

**Follow-up (same day)**: the fix above only prevents *future* orphans — it doesn't retroactively kill one that already existed before it shipped, and the user hit exactly that: the crash loop continued (now reproducing even under a direct `python prod_server.py` run, not just via `manage.sh`, since the stale process blocking the port existed independently of how the *new* attempt was launched), and `.manage_pids/webdav.pid` pointed at an already-dead PID rather than the real occupant.  
**Cause**: `_write_webdav_pidfile()` runs after *every* `_spawn_webdav_process()` call, including doomed ones that are about to immediately fail to bind and exit. In a tight 3s respawn loop, the pidfile gets overwritten every cycle with the newest (soon-to-be-dead) attempt's PID — so by the time anyone goes to check it, the real, still-alive occupant's PID has long since been overwritten and is no longer recorded anywhere. That's what made it "untrackable": the file existed and had a PID in it, just not the *right* one.  
**Fix**: `protocol_manager.py` now does a pre-flight TCP connect check (`_port_occupied()`/`_webdav_target_ports()`) against WebDAV's configured port(s) before *every* spawn attempt — the very first one in `start_all()` as well as every watchdog respawn. If something is already listening, it does **not** spawn a new (doomed) process at all — so the pidfile is left untouched instead of being overwritten with junk — and instead prints one clear diagnostic (`_port_conflict_message()`) with the actual `netstat`/`lsof` + kill commands needed to find and remove the real occupant, then backs off to a 15s poll instead of a tight 3s loop until the port frees up on its own.  
**One-time manual cleanup still required** for any orphan that already existed before this shipped — the fix can't retroactively find a PID that's already been overwritten out of the pidfile. Find it directly via the OS, not the pidfile:
  - Windows: `netstat -ano | findstr :8443` (or `:8080` if plaintext WebDAV is enabled) → `taskkill /F /PID <pid>`
  - Linux/macOS/Termux: `lsof -i :8443` (or `ss -ltnp | grep 8443`) → `kill -9 <pid>`
  Once that one process is gone, the watchdog's own port check will detect the port is free and spawn a fresh WebDAV process automatically — no restart of `prod_server.py`/`manage.sh` needed.  
**Not yet verified live** — same caveat as above: `webdav_server.py` wasn't part of the uploaded files, so its own bind/startup path was reasoned about, not read directly.

**Confirmed live (2026-09-15)**: the port-conflict diagnostic above actually fired on the user's machine (`❌ WebDAV port(s) 8080, 8443 already occupied by another process...`), validating the pre-flight-check theory against a real deployment — the watchdog correctly refused to spawn a doomed process instead of continuing the 3s crash loop / pidfile-overwrite cycle. Resolution steps for whoever hits this:
  1. Open an elevated Command Prompt and run `netstat -ano | findstr :8080 :8443` — findstr treats space-separated terms as OR'd literals, so this matches either port in one pass.
  2. Each matching line ends in a PID column; look specifically for `LISTENING` rows (not `ESTABLISHED`/`TIME_WAIT`) — those are the process(es) actually holding the port open. There may be one PID for 8080 and a different one for 8443 if two separate leftover processes accumulated.
  3. `taskkill /F /PID <pid>` for each PID found in step 2.
  4. Re-check with the same `netstat` command — once no `LISTENING` rows remain on 8080/8443, the watchdog (polling every 15s while blocked) picks it up on its own and spawns a fresh WebDAV process; no restart of `prod_server.py`/`manage.sh` needed.
  Not yet confirmed whether killing those PID(s) fully resolved the user's loop — pending confirmation.

**Fully automated (2026-09-15, later same day)**: the manual `netstat`/`taskkill` dance above is no longer needed going forward. `manage.sh`'s `_kill_webdav_child()` no longer trusts `webdav.pid` alone — it now also actively finds whatever's bound to WebDAV's ports (8080/8443, matching `protocol_manager.py`'s own `_webdav_target_ports()` fallback) via `netstat`/`taskkill` (Windows) or `lsof`/`kill` (POSIX) and kills that directly, regardless of what the pidfile says. Called from `cmd_stop` as before, and now *also* defensively from `cmd_start` before every spawn — so an orphan left behind by a crash, an interrupted stop, or anything else that desynced the pidfile gets cleared automatically on the next `start`, without needing to open Task Manager. Not yet confirmed against a live repeat of the scenario, but directly closes the exact gap the three entries above spent the day chasing.  
**Later hardening + caveats (present in the `manage.sh` reviewed 2026-09-21; date of these changes isn't recorded in the file)**: the sweep only kills *python* processes; every lookup ends `|| true` because, under `set -eo pipefail`, "nothing listening" used to kill `manage.sh` silently; and the ports are hardcoded `8080 8443` rather than read from `config.py`. Full list in [manage.sh Internals & Editing Rules](#managesh-internals--editing-rules).

**Follow-up (same day, Version 4.12)**: a *different* trigger for the same `⚠️ WebDAV process exited unexpectedly (code 1) — respawning in 3s...` symptom, this time with no port conflict involved. `python prod_server.py` run directly in a terminal crash-looped; the identical code path via `manage.sh` (detached, stdout/stderr → `/dev/null`) and `python webdav_server.py` run completely standalone were both fine.  
**Cause**: `_spawn_webdav_process()` passed `stdout=sys.stdout, stderr=sys.stderr` explicitly to `Popen`. By that point `logging_setup.py` has already replaced those names with `_TeeStream` instances (see the logging-unification entry above), which have no `fileno()` of their own and forward to the *original* real stream's `fileno()` via `__getattr__`. That resolves fine when the parent's real fd 1/2 are plain files (`manage.sh`'s detached launch → devnull) or aren't involved at all (`webdav_server.py` run standalone, no tee). Attached to a terminal emulator that doesn't back `sys.stdout` with a normal, directly-inheritable OS handle (e.g. Git Bash/MSYS/MinTTY-style consoles on Windows), `Popen` can end up handing the child a bad/non-inheritable handle, and `webdav_server.py` exits immediately (code 1) before reaching its own startup code — reproducing exactly as an infinite 3s respawn loop with no port ever actually contested.  
**Fix**: `protocol_manager.py`'s `_spawn_webdav_process()` no longer passes `stdout`/`stderr` to `Popen` at all. Omitting them (Python's default) makes the child inherit the parent's real OS-level fd 1/2 directly, bypassing the `sys.stdout`/`sys.stderr` Python objects — and therefore the tee/`fileno()` forwarding — entirely. Functionally equivalent to the previous intent (WebDAV's output still lands wherever the parent's own stdout/stderr are pointed) without depending on the wrapped object's `fileno()` resolving cleanly.  
**Not yet verified live** — reasoned from the code path and the reported repro pattern (works via `manage.sh` and standalone, fails only via direct-terminal `prod_server.py`), not from a captured traceback; `webdav_server.py` itself still wasn't part of the uploaded files this session, so its own startup code wasn't directly inspected. If the loop persists after this fix ships, the next diagnostic step is capturing the actual traceback that should now print directly to the terminal (since the child no longer goes through the tee at all) right after the "exited unexpectedly" line.

**Follow-up (same day, Version 4.13)**: the above did NOT fix it, and comparing the two log files pinpointed something more fundamental. `logs/prod_server_2026-09-15.log` (the actual failing run, WebDAV spawned as a subprocess) shows **zero** lines from `webdav_server.py` itself — not its startup banner, not even the `app.py`-level "Starting file system monitor" line that `import app` inside `webdav_server.py` also triggers, nothing — just the parent's own "exited unexpectedly" messages on repeat. By contrast, `logs/app_2026-09-15.log` (leftover from earlier `python webdav_server.py` standalone test runs the same day, using the pre-`CLOUDINATOR_LOG_PREFIX` fallback prefix) shows a complete, successful startup: full banner, `🔐 WebDAV HTTPS: https://...:8443/`, `Running on https://0.0.0.0:8443`, ran fine for several minutes.  
**Cause**: inherited-handle stdio — both the original explicit `stdout=sys.stdout`/`stderr=sys.stderr`, and the Version 4.12 fix (omit them, let `Popen` default to inheriting fd 1/2 directly) — never got a single byte of the crashing child's output back to the parent on this machine, not even a raw Python interpreter traceback that would print before any of this project's own logging is involved. Root mechanism not fully pinned down (some handle-inheritance quirk specific to this Windows setup), but no longer worth chasing once there was a strictly more reliable alternative.  
**Fix**: `_spawn_webdav_process()` now pipes the child's stdout/stderr (`subprocess.PIPE`) instead of inheriting them, and a new `_pump_child_output()` helper runs in two daemon threads (one per stream) reading line-by-line and relaying each line through the parent's own `print()` — which already flows through `logging_setup.py`'s tee into the console and shared daily log file. This depends on nothing at the OS handle-inheritance level; the parent explicitly reads and re-emits every byte the child writes, so whatever was swallowing output before can no longer hide it.  
**Not yet verified live** — this should finally make the real crash cause visible (as `[webdav:ERR] ...` lines) the next time it happens; still waiting on that output or `webdav_server.py`'s own source before the actual underlying bug (whatever's causing exit code 1) can be fixed.

**Root cause found (same day, Version 4.14)**: the PIPE+relay diagnostic worked — it surfaced the real traceback immediately:
```
File "paths.py", line 271, in ensure_dirs
    print(f"\U0001f4c2 DB dir ready:        {db_path}")
UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f4c2' in position 0: character maps to <undefined>
```
`ensure_dirs()` (at the time of this bug pulled in transitively via `webdav_server.py`'s `from app import get_local_ip` → `app.py` → `paths.py`; since 4.52 `webdav_server.py` imports `get_local_ip` from `net_utils` instead, so this path no longer runs in the WebDAV process) prints an emoji. When a process's stdout is attached to a real console, Windows uses the console's codepage and this is fine — true for the main process (always console-attached when run directly) and for `webdav_server.py` run as a genuinely standalone process (own console). But once WebDAV's stdout became a **pipe** (Version 4.13's fix, needed to surface output at all) rather than a console, Python falls back to `locale.getpreferredencoding()` — `cp1252` on the affected machine — which can't encode that character, and the import chain dies with an uncaught exception before `webdav_server.py`'s own code, or even its own logging setup, ever runs. This was almost certainly the *same* failure happening silently under Version 4.12's plain-fd-inheritance approach too — the traceback was just getting lost in Windows' handle-inheritance behavior rather than ever reaching the console/log.  
**Why `manage.sh` never hit this**: its detached launcher already sets `PYTHONUTF8=1` for whatever it spawns (`prod_server.py`/`dev_server.py`), which flows down into `protocol_manager.py`'s `env=dict(os.environ)` for the WebDAV child too — masking the bug entirely under `manage.sh`. Running `python prod_server.py` directly never sets it, so WebDAV's subprocess was the first thing in that path to hit a genuinely non-console stdout and trip over it.  
**Fix**: `_spawn_webdav_process()` now sets `env["PYTHONUTF8"] = "1"` explicitly and unconditionally for the WebDAV subprocess, rather than relying on it having been set somewhere further up the process chain. Correct regardless of how the parent was launched.  
**Known related caveat, not fixed**: the main process itself (`prod_server.py`/`dev_server.py`) would hit the identical `UnicodeEncodeError` if its own stdout were ever redirected to a file/pipe rather than a live console (e.g. `python prod_server.py > out.log`), since `os.environ["PYTHONUTF8"]` set at runtime has no effect on the already-started interpreter's own stdout encoding. Not in scope for this fix (the main process was never actually affected in the reported bug), but `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` near the top of both scripts would close that gap if it ever comes up.

**Follow-up (same day, Version 4.15)**: `PYTHONUTF8=1` fixed the original crash — WebDAV got much further this time (past `ensure_dirs()`, through its own config load, into request handling) — but exposed two more issues, both in the diagnostic path itself rather than the app:

1. **Mojibake in the relayed output** (`ðŸ“‹` instead of `📋`): `_pump_child_output`'s `Popen(text=True)` call had no explicit `encoding=`, so it fell back to the same `locale.getpreferredencoding()` (`cp1252`) on the *parent's* read side — misdecoding the UTF-8 bytes the child was now correctly writing. Fix: added `encoding="utf-8", errors="replace"` explicitly to the `Popen` call, matching the child's `PYTHONUTF8=1`.
2. **The actual crash traceback got swallowed again**, but for a narrower, Windows-specific reason this time: `logging_setup.py`'s console `StreamHandler` tried to write a full uncaught-exception traceback to `sys.stdout`, which is now a pipe (not a console) — and Windows has a known ~32KB limit on a single write to a non-console handle. A long traceback can exceed that, and the write itself raises `OSError: [Errno 22] Invalid argument`, caught internally by `logging`'s own `handleError()` and reported as `--- Logging error ---` instead of the actual exception. Not yet fixed — no `logging_setup.py` changes made pending confirmation of whether this needs hardening (e.g. chunked writes, or skip the console handler when stdout isn't a tty) or was a one-off. Importantly, `DailyDatedFileHandler` — the *other* handler on the same root logger, writing straight to `logs/prod_server_YYYY-MM-DD.log` on disk — is a fully independent code path with no pipe/console involved and isn't subject to that write-size limit, so the real original traceback this round is very likely present in that log file's `[CRITICAL] Uncaught exception` entry even though it never reached the console relay.

**Not yet verified live** — waiting on the log file's `CRITICAL` entry to see the actual traceback that's crashing WebDAV now that the UTF-8 print bug is fixed.

**Confirmed live (2026-09-16)**: with Version 4.15's fixes in place, `python prod_server.py` run directly produced a full, clean WebDAV startup — file-monitor init, cleanup schedulers, search index, `ℹ️ WebDAV: ignoring WEBDAV_ENABLED...`, `🔐 WebDAV HTTPS: https://...:8443/`, `Running on https://0.0.0.0:8443` — with no `exited unexpectedly` loop. The only warning present (`ASGI Framework Lifespan error, continuing without Lifespan support`) is Hypercorn's normal, harmless warning for an ASGI app without a lifespan handler — it appeared identically in the earlier known-good standalone `webdav_server.py` run (`app_2026-09-15.log`) and isn't related to this bug. The original symptom (direct `prod_server.py` runs crash-looping while `manage.sh` and standalone `webdav_server.py` worked) is resolved.

**Problem (same saga, 2026-09-16)**: with the above resolved, a live log revealed two more things — every WebDAV line appeared *twice* in the shared log file (once as a clean `[webdav_server]`-tagged direct write, once again duplicated via the parent's relay), and one line showed a nested/misaligned-looking double timestamp.  
**Cause**: `_pump_child_output` (Version 4.13's PIPE+relay diagnostic, above) was still calling plain `print()` to relay each line — which goes through the *parent's own* `logging_setup` tee, writing a second copy into the shared file on top of the WebDAV subprocess's own direct write (now proven reliable by this point, making the relay's file-writing purpose redundant — only its console-visibility and very-early-crash-diagnosis value still matter). Separately, the nested-timestamp line was Hypercorn itself pre-formatting one specific message (the same ASGI Lifespan warning) with its own embedded timestamp, bypassing the `errorlog` Logger object entirely for that message — our tee's outer timestamp just wraps around it.  
**Fix**: added `logging_setup.get_real_stdout()`/`get_real_stderr()` — the streams captured *before* the tee replaced `sys.stdout`/`sys.stderr` — and changed `_pump_child_output` to write directly to those instead of `print()`. Still shows live on a real console (and still catches a WebDAV crash so early that even its own `logging_setup` import hasn't finished), but no longer duplicates into the file. The Hypercorn-internal double-timestamp isn't fixable from our side without patching Hypercorn's own formatter — now only appears once instead of twice, given the duplication fix.  
**Verified** via a two-process write simulation: relayed line appears on console only, absent from the log file; normal `print()`/logger calls elsewhere unaffected.

**Problem**: rapid double Ctrl+C on `prod_server.py` left the WebDAV child process orphaned (a separate, harder-to-reproduce case from all the entries above — this one about *shutdown*, not startup).  
**Cause**: the force-quit path (second Ctrl+C, `_sigint_handler`'s `else:` branch) calls `os._exit(0)` directly — a hard kernel-level exit that skips the `finally:` block further down, including its `protocol_manager.stop_all()` call. SFTP/FTP/SMB are in-process threads that die automatically the instant the parent does; WebDAV (`subprocess.Popen`, a genuinely separate OS process) does not, and survives as an orphan holding its port and the shared log file open. `dev_server.py` had a structurally different version of the same gap: a second Ctrl+C landing while its `except KeyboardInterrupt:` block was already running `protocol_manager.stop_all()` (specifically during that function's `terminate()`+`wait(timeout=5)` for WebDAV) would raise a fresh, uncaught `KeyboardInterrupt` right there, aborting cleanup before reaching WebDAV.  
**Fix**: added `protocol_manager.force_kill_webdav()` — a fast, no-wait `proc.kill()` targeted at just the WebDAV child (unlike `stop_all()`'s graceful terminate-then-wait, which is exactly the window an impatient second Ctrl+C could interrupt) — called right before `os._exit(0)` in `prod_server.py`'s force-quit branch; fast enough not to meaningfully delay the force-quit UX. `dev_server.py` got a different fix rather than the identical mechanism: `signal.signal(signal.SIGINT, signal.SIG_IGN)` at the very top of its cleanup block, installed only *after* Quart's own `app.run()` has already handled the first Ctrl+C internally for its own graceful teardown (avoiding any conflict with that), so further rapid presses during `stop_all()` are simply ignored until it finishes rather than interrupting it. Net UX difference: `prod_server.py` keeps its instant force-quit feel; `dev_server.py` becomes briefly unresponsive to further Ctrl+C during cleanup instead of orphaning.  
**Not yet verified live** — reasoned from the code paths; next confirmation step is mashing Ctrl+C rapidly on both entry points and checking Task Manager afterward.

### WebDAV Resilience Issues (2026-09-09)

**Problem**: WebDAV clients (Windows Map Network Drive, davfs2, etc.) get "SSL connection closed" repeatedly, especially on downloads, and it loops/retries without resolving  
**Cause**: WebDAV's HTTPS listener advertised HTTP/2 in its TLS ALPN list; real WebDAV client stacks are almost universally HTTP/1.1-only and can break at the protocol level if TLS negotiates h2 with them  
**Fix**: `webdav_server.py`'s HTTPS listener ALPN is now `["http/1.1"]` only — h2 remains unaffected (and beneficial) for the main Web UI, which browsers negotiate correctly. See [WebDAV HTTPS Listener — HTTP/1.1 Only](#webdav-https-listener-http11-only-2026-09-09)

**Problem**: Cancelling a large in-progress WebDAV download wedges or crash-loops the WebDAV listener, requiring a full server restart to recover — main Web UI on :5000 keeps working fine throughout  
**Cause**: A real, still-open Hypercorn bug (see the next entry) combined with WebDAV previously running as a background thread inside the same process as the main app — a wedged thread had no independent recovery path short of killing the whole process  
**Fix**: Two parts — (1) `hypercorn_ssl_fix.py` patches the actual Hypercorn bug (see below), and (2) WebDAV now runs as its own OS subprocess with a watchdog, so `./manage.sh restart-webdav` (or `protocol_manager.restart_webdav()` from in-process) recovers it alone. See [WebDAV Process Isolation, Watchdog & restart-webdav](#webdav-process-isolation-watchdog-restart-webdav-2026-09-09)

**Problem**: `TimeoutError: SSL shutdown timed out` / "Unhandled exception in client_connected_cb" spam in the server log, especially right after a client abruptly resets a connection (e.g. cancelling a download — `ConnectionResetError: [WinError 10054]` on Windows)  
**Cause**: Since Python 3.11, asyncio's SSL transport waits a default **30 seconds** for a clean TLS `close_notify` on every connection close. A peer that already forcibly reset the connection can never complete that handshake, so the wait runs the full 30s before raising `TimeoutError`. Hypercorn's own `TCPServer._close()` (verified directly against the installed 0.18.0 source, not just the bug report) catches `ConnectionResetError`/`BrokenPipeError`/etc. for exactly this "already closed" case, but **not** the resulting `TimeoutError` — so it escapes as an unhandled exception. This is a real, still-open upstream bug: [hypercorn#202](https://github.com/pgjones/hypercorn/issues/202) (unresolved as of the last activity found; an open, unmerged PR #342 exists)  
**Fix**: New `hypercorn_ssl_fix.py`, applied at startup in **both** `prod_server.py` and `webdav_server.py` (each is a separate Hypercorn instance/process, so both need it). Monkeypatches `TCPServer._close()` to (1) actually catch `TimeoutError`, and (2) cap the close-wait at 2 seconds via `asyncio.wait_for(...)` instead of asyncio's 30s default. Defensive: if Hypercorn's internals change in a future version and the patch no longer applies cleanly, it logs a warning and leaves Hypercorn's original (buggy but functional) behavior in place rather than crashing the server — re-check this patch after any Hypercorn upgrade, and remove it entirely if Hypercorn ships an official fix for #202

**Problem**: Even after the fix above, cancelling a large WebDAV download (e.g. a 700MB file, ~10s in) still produces a genuinely fast, continuous flood — thousands of bare `SSL connection is closed` lines, **no traceback at all** — that doesn't stop until the entire rest of the file has been (uselessly) iterated  
**Cause**: A separate bug from the one above, verified against the real source of all three layers involved: (1) `asyncio/sslproto.py`'s `_write_appdata()` never raises on a dead connection — by design, per asyncio's `Transport.write()` fire-and-forget contract — it just logs a warning once past a 5-write grace threshold and silently no-ops forever after; (2) `asgiref`'s `WsgiToAsgiInstance.run_wsgi_app()` streams the WSGI response body via an *unguarded* loop with no try/except around the send call and no disconnect check; (3) wsgidav just keeps yielding the next file chunk regardless. Nothing in the chain ever naturally detects the client is gone — writes silently "succeed" and log, once per chunk, for every remaining chunk  
**Fix**: New `_DisconnectAbortMiddleware` in `webdav_server.py`, wrapping `WsgiToAsgi(wsgi_app)` at the ASGI level. Confirmed via Hypercorn's `http_stream.py` that it does deliver `http.disconnect` through `receive()` once its read side notices the connection is gone — nothing was listening for it during a long download. The middleware watches for that signal in the background (only after the inner app's own request-body read completes, to avoid a `receive()` race) and makes `send()` raise once it arrives, which propagates through asgiref's unguarded loop and stops it on the very next chunk. Verified with isolated functional tests, not just reasoning: a simulated cancelled download stopped at chunk 6 of 1000 (vs. all 1000 before the fix), and a normal completed download still delivered all chunks with no interference. See [WebDAV Disconnect-Flood Guard](#webdav-disconnect-flood-guard-2026-09-09-second-pass)

**Problem (2026-09-24)**: `Unhandled exception in client_connected_cb` + `transport: <asyncio.sslproto._SSLProtocolTransport object at 0x...>` + `ssl.SSLError: [SSL: APPLICATION_DATA_AFTER_CLOSE_NOTIFY] application data after close notify`, tagged `[STDERR] [webdav_server]`, with no client IP on it — looks like the older `TimeoutError: SSL shutdown timed out` entry above but is a different bug  
**Cause**: the client sent data after its own TLS `close_notify`; the TLS shutdown fails with `SSLError`, which neither stock Hypercorn's `_close()` nor (per the reported traceback) `hypercorn_ssl_fix.py`'s patched `_close()` catches — it escapes `client_connected_cb`. The missing IP isn't a logging misconfiguration: asyncio's own handler no longer has the peer address by then (`peername` is `None`, verified)  
**Fix**: `hypercorn_ssl_fix.py`'s `_patched_close()` now reads the peer before teardown and logs one IP-tagged line, once per connection (applies to WebDAV and to `prod_server.py`'s main listener). Harmless: the connection was already closing. See [WebDAV Audit Logging and Client-IP Attribution](#webdav-audit-logging-and-client-ip-attribution-for-tls-teardown-errors-2026-09-24)  
**Problem (2026-09-24, fixed)**: `[ERROR] Error in ASGI Framework` with a full traceback ending in `ConnectionResetError: WebDAV client disconnected mid-response (_DisconnectAbortMiddleware guard)`  
**Cause (confirmed)**: `_DisconnectAbortMiddleware.guarded_send()` raising is the guard doing its job — that raise is what breaks a cancelled download's response loop — but nothing caught it, so Hypercorn reported it as a server failure every time. Reproduced two ways, both against the **unmodified original file**: (1) once per cancelled download (a 200 MB file reset-cancelled after ~256 KB → one traceback per cancel), and (2) when a client hangs up right after a *complete* response, a split second before asgiref's final empty `http.response.body` send (`asgiref/wsgi.py` line ~197) — there nothing was wrong at all. Not introduced by the audit patch  
**Fix**: an `except ConnectionResetError` in `_DisconnectAbortMiddleware.__call__` that swallows **only** an error whose text equals the module constant `_GUARD_MSG` (the same constant `guarded_send()` raises with, so the two can't drift apart) and re-raises anything else. The raise has already broken the response loop by then, so the flood protection is unaffected  
**Verified** (real HTTPS, two 200 MB downloads reset-cancelled after ~256 KB each; three server variants side by side): guard **disabled** (test-only control proving the test can see a flood) → **48,757** `SSL connection is closed` lines, 3.4 MB of log; guard **without** the catch → 0 flood lines, 2 tracebacks; guard **with** the catch → 0 flood lines, 0 tracebacks, 1.2 KB of log. A direct check of the middleware confirmed the guard's own error is swallowed while a real `ConnectionResetError` (e.g. `[WinError 10054] …`) and an unrelated `ValueError` are both still re-raised. Audit logging and the `hypercorn_ssl_fix.py` teardown handling were re-run afterwards and are unaffected. **Not verified** on Windows / Python 3.14 or with real WebDAV clients

**Problem (2026-09-24, partly fixed)**: some lines in the shared log arrive as `[STDERR] [webdav_server] <raw text>` with no level or logger name, and Hypercorn's own errorlog lines from the WebDAV process arrived double-timestamped (`[STDERR] [webdav_server] 2026-09-24 02:57:50 [INFO] Running on https://...`)  
**Cause**: (1) `webdav_server.py`'s `_build_hypercorn_logger()` built its own plain `logging.StreamHandler()` whose stream is `sys.stderr` — already the `_TeeStream` by then — so its already-formatted line got a second timestamp/tag prepended. `prod_server.py`'s copy of the same helper had already been changed to `logging_setup.get_logger("hypercorn")` and did **not** have this problem; the WebDAV copy had simply been left behind. (2) Anything logged through the `"asyncio"` logger has no handlers on it or its parents and lands via Python's last-resort handler on stderr, i.e. through the tee  
**Fix (1)**: done 2026-09-24 — `webdav_server.py`'s helper is now the same one-liner as `prod_server.py`'s. **(2) still open**: attach `logging_setup`'s central handlers to `logging.getLogger("asyncio")` — not done, it changes formatting for the main process too  
**Related, not a bug**: `[WARNING] ASGI Framework Lifespan error, continuing without Lifespan support` at every WebDAV start is Hypercorn noting that `asgiref.WsgiToAsgi` doesn't implement the ASGI lifespan protocol; it has always been there (it just used to be hidden under a `[STDERR]` tag) and is harmless

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
11. **Protocol server dependency missing**: Graceful skip with install hint; Quart unaffected
12. **WebDAV client re-auth on every request**: _AuthCache prevents repeated bcrypt calls
13. **SFTP host key regenerated**: All clients see host-key-changed warning (expected)
14. **FTP passive port range**: Must match firewall rules; default 60000-60100
15. **SMB user deleted while a session is open**: Existing connection keeps working (SMB doesn't re-auth mid-session); only the next new connection attempt is blocked
16. **SMB mixed-case usernames**: Credential diff normalizes to lowercase, matching impacket's own internal key storage
17. **SMB abandoned connection after a failed login**: `block_on_close=False` + `daemon_threads=True` (set before accepting connections) prevent `stop()` from hanging forever

---

### SMB One-Time Setup (smb_setup.py) and lanman_guard.py

Standalone tool, run manually like `manage_users.py`/`reset_db.py` — **never** auto-invoked by `prod_server.py`/`dev_server.py`. Detects platform and branches:

- **Windows**: confirm → request elevation (one UAC prompt, script relaunches itself elevated and continues automatically) → `Set-Service`/`Stop-Service` on `LanmanServer` → prints "restart now" and stops — **never executes a restart itself, under any circumstance**. A matching restore action, same shape, in reverse.
- **Linux**: `setcap cap_net_bind_service=+ep` on the Python binary — immediate, no restart, verified directly (created a genuinely non-root user, confirmed it could bind port 445 right after).
- **Android**: root check only. Rooted → points at running the server via `su -c`/`tsu`, deliberately **not** `setcap` (its behavior on Android is unpredictable across devices due to SELinux policy variance — a granted capability can silently fail to apply at runtime). Not rooted → no path to 445, falls back to 8445 automatically.

`lanman_guard.py` is a small, passive state-tracking library shared between the two: `smb_setup.py` writes a pending-state file after disabling LanmanServer; `smb_server.py` reads it at startup purely to give accurate fallback messaging ("looks like you haven't restarted yet" vs "nothing's been set up"). No watchdog, no auto-restore, no force-kill survival logic — that entire apparatus (originally built, then removed) was solving a problem that doesn't exist once "this needs a reboot" is understood: it's a rare, deliberate, human-driven change, not a per-session toggle.

### Access Revocation (kick_sessions.py)

Standalone tool, `python kick_sessions.py` with no args launches an interactive menu (same convention as `smb_setup.py`); CLI args (`list`, `rotate <user>`, `delete <user>`, `kick-all [--include-admins]`, `logout-web`) still work for scripting.

Works at the database level only — it's a separate process, same constraint `manage_users.py` always had, can't reach into a running server's memory. Real, verified timing per protocol:
- **SFTP/FTP**: instant — both re-validate against the database on every connection, no caching.
- **WebDAV**: ~30s (`_AuthCache` TTL).
- **SMB**: ~30s (credential refresh cycle).
- **None** can forcibly close a connection that's already open — confirmed directly: revoked a user mid-session, their open connection kept working normally; only the *next* connection attempt was blocked.
- **Exception — `logout-web`**: genuinely instant, because a web session cookie is a separate secret from the password (`db.rotate_server_token()`) — rotating it invalidates every existing cookie immediately while leaving passwords untouched. WebDAV's cache doesn't get this same treatment even though it's also HTTP: Basic Auth resends the actual password on every request, so there's no separate session secret to invalidate — only a real password change revokes anything there.

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
6. SMB hooks must use `(*args, **kwargs)`, never a fixed positional signature — `SMB2_NEGOTIATE`'s legacy call path uses 4 args, not the usual 3
7. SMB hooks must stash the original handler in a plain holder list (`[None]`), never a mutable default argument patched via `__defaults__` — breaks silently once `*args` is involved
8. WebDAV middleware order is `_CertMiddleware` → `_AuditMiddleware` → `_RoleEnforcerMiddleware` → wsgidav. Keep audit **outside** the role enforcer or readonly 403s drop out of the audit trail
9. WebDAV's audit `ip=` is `REMOTE_ADDR` (raw TCP peer). Don't add `X-Forwarded-For`/`CF-Connecting-IP` trust unless the listener is genuinely reachable only through a proxy you control — see the 2026-09-23 sync note for the web UI's equivalent caveat
10. `hypercorn_ssl_fix.py`'s `_patched_close()` replaces `TCPServer._close()` for **every** Hypercorn instance that calls `apply()` (main listener + WebDAV). It reads `peername` first, catches `OSError` after the `ConnectionError`/`TimeoutError` clause, and logs once per connection via `_ssl_fix_logged` — keep all three properties when editing it, and re-check it against Hypercorn's source after any upgrade
11. In `_DisconnectAbortMiddleware`, `guarded_send()`'s raise and `__call__`'s `except ConnectionResetError` share the constant `_GUARD_MSG` — keep them on that one constant, and keep the except clause matching the guard's own message only (never a bare `except ConnectionResetError: pass`, which would hide real connection failures)

**When Optimizing**:
1. Profile with Python cProfile first
2. Check if Tier 1 caching can help (>80 entries)
3. Consider async for I/O-heavy operations
4. Batch database operations in transactions
5. Use watchdog incremental over full walks

**When Debugging**:
1. Enable `QUART_DEBUG=1` (dev_server.py sets this automatically; the old `FLASK_DEBUG` env var has no effect post-migration)
2. Check app.py DEBUG_ROUTES (if defined)
3. Use debug_passwords.py for auth issues
4. Monitor /api/health_check endpoint
5. Review .status.json files for transcode progress
6. Check /api/speedtest/* for network issues
7. For WebDAV: test `https://HOST:8443/webdav.crt` (e.g. `curl -k`; use `http://HOST:8080/webdav.crt` only if the plaintext listener is up) — if 404, cert not generated yet
8. For SFTP: check `db/sftp_host.rsa` exists; verify port 2222 with `netstat -an`
9. For FTP: check firewall for ports 2121 AND 60000-60100
10. For SMB: `SMB_DEBUG_SIGNING=1` for Negotiate/Session Setup tracing; `SMB_DEBUG_FILES=1` for file open/close lifecycle; check `db.users_missing_nt_hash()` for auth issues
11. "Who did that / from where?" for any of the four protocols: `grep "AUDIT"` the daily log (`WebDAV AUDIT:` / `SFTP AUDIT:` / `FTP AUDIT:` / `SMB AUDIT:`); failed logins are `action=login_failed`, readonly-role blocks on WebDAV are `action=permission_denied`

---

## 📚 Related Documentation

- **User Guide**: docs/USER_GUIDE.md
- **Linux Deployment**: docs/LINUX_DEPLOYMENT.md
- **Windows Deployment**: docs/WINDOWS_DEPLOYMENT.md
- **Android/Termux Deployment**: docs/ANDROID_DEPLOYMENT.md
- **Apache WSGI Production**: docs/DEPLOY_APACHE.md (⚠️ predates the Quart/ASGI migration — mod_wsgi only runs WSGI apps and cannot serve an ASGI app like the current Quart/Hypercorn stack; needs a rewrite around a reverse proxy in front of `prod_server.py`, or an ASGI-capable Apache module, before it's trustworthy again)
- **Cloudflare Tunnel Setup**: docs/SETUP_TUNNEL_ADVANCED.md
- **rclone Integration**: docs/RCLONE_DEPLOYMENT.md
- **SMB Protocol Setup**: docs/SMB_PROTOCOL_DEPLOYMENT.md
- **manage.sh Guide**: docs/SERVER_MANAGEMENT_SCRIPT_GUIDE.md (was `docs/MANAGE_SCRIPT_GUIDE.md` before 2026-10-02)
- **README**: README.md (quick start)

---

## 📝 Changelog

### Version 4.61 — 2026-10-02 `file_index.json` Save Retry (`file_index.py` only)

No other file changed. Details and the `search_index.db` audit are in the 2026-10-02 part 8 sync note at the top.

- **Fixed:** `FileIndexManager.save()` retries `os.replace()` on `PermissionError` (about 3 s backoff, same as `storage_index.json`); permanent failure logs, cleans the temp file and does not raise.
- **Audited, unchanged:** `search_index.db` uses WAL + an in-process write lock + the default 5 s SQLite busy timeout, with no retry.
- **Tested:** patched `os.replace` on Linux; **not** on the owner's Windows server.

### Version 4.60 — 2026-10-02 Reconcile After Move/Rename/Mkdir + Coalescing (`app.py` only)

No `file_monitor.py`, `file_index.py`, `storage.py`, template or JS change. Details are in the 2026-10-02 part 7 sync note at the top.

- **Added:** `_trigger_reconcile()` calls in `/bulk_move` (when something moved), `/rename` and `/mkdir`; delete, bulk delete, bulk copy and upload-complete already had it.
- **Changed:** `_trigger_reconcile()` coalesces — one walk at a time, at most one queued follow-up — instead of one new walk thread per call.
- **Unchanged:** the 15-minute validation walk; external (non-web-UI) changes still wait for it.
- **Tested:** coalescing logic with a stubbed monitor; `py_compile` only for the routes; **not** on the owner's Windows server.

### Version 4.59 — 2026-10-02 `storage_index.json` Validation (`file_monitor.py` + `app.py`)

No `file_index.py`, `storage.py`, `realtime_stats.py`, template or JS change. Details, limits and the test list are in the 2026-10-02 part 6 sync note at the top.

- **Load validation:** `storage_index.json` is checked for schema version, root path, counters and every `dir_info` record before anything is assigned; bad structure → discarded and rebuilt by a walk, bad records → repaired and re-verified by a walk after 3 s (30 s when clean). The first start after upgrading flags the old file once (it has no `version`/`root`).
- **Walk safety:** `_full_walk()` reports `complete`/`errors`; an aborted walk, or one that finds nothing while the index holds ≥ 50 files (rejected once), no longer replaces the counters or the saved file, and no longer feeds `file_index.json` / the search index. `_reconcile()` returns `bool` and takes `force`.
- **Hygiene:** `version` + `root` written, `fsync` before the atomic replace, stale `storage_index.*.tmp` sweep, `get_dir_info()` returns a copy, per-folder drift in the reconcile log, no dead watchdog observer kept when the root is missing at startup (fixed a shutdown exception).
- **`app.py`:** `/admin/rebuild_cache` forces the walk, audits the file index with `verify_all(repair=False)` and reports the result in the JSON message; returns 500 if the walk was rejected.
- **Checked, no change needed:** `list_dir()` is called via `asyncio.to_thread` at all three call sites; the handlers skip `update_folder()` during reconcile suppression by design and the per-read mtime check covers it.
- **Tested:** 49 assertions on a Linux temp tree; `app.py` syntax-checked only; **not** on the owner's Windows server.

### Version 4.58 — 2026-10-02 `file_index.json` Validation (`file_index.py` only)

No `app.py`, `file_monitor.py`, `storage.py`, template or JS change; public method signatures unchanged. Details and limits are in the 2026-10-02 part 5 sync note at the top.

- **Load validation:** schema version, threshold and per-record sanity checks; bad data is dropped; loaded records are unverified until re-read.
- **Read validation:** `get_entries()` re-scans an unverified record on first use, then compares the folder mtime (`dir_mtime_ns`, new record field) on every read.
- **Walk reconcile:** `build_from_walk()` re-reads every large folder, keeps still-existing folders a partial walk missed, ignores an empty walk, does not overwrite newer handler updates, logs drift.
- **Hygiene:** scan errors evict instead of caching `[]`; fsync'd atomic save with a private temp prefix and a stale-temp sweep; key normalisation; new `verify_all(repair=False)`; `get_stats()` gains `unverified_folders` / `last_build`.
- **Docs corrected:** `update_folder()` never saved to disk (earlier text said it did).
- **Tested:** 34 assertions on a Linux temp tree; **not** on the owner's Windows server. **Open:** `storage_index.json` / `file_monitor.py` not reviewed.

### Version 4.57 — 2026-10-02 Background Music: Autoplay Retry Fix (`bg_audio.js` only)

No `app.py`, CSS or template markup change. Details are in the 2026-10-02 part 4 sync note at the top.

- **Cause of "no autoplay after refresh without interacting":** browser autoplay policy (reload resets user activation; scroll/mouse move are not gestures). Edge setting Media autoplay = Allow for the site removes it entirely; the page can only retry on real gestures.
- **Fixed in `bg_audio.js`:** the fallback is no longer one-shot (stays armed on pointerdown/mousedown/click/keydown/touchstart/touchend until `play()` succeeds); a blocked autoplay no longer saves `playing = "false"`; `pause` events during unload are ignored.
- **Follow-up required:** recompute the `bg_audio.js` SRI hash in all four templates (`./manage.sh validate-sri` → `y`, or `--fix`).
- **Tested:** Node simulation of the state logic; **not** a real browser.

### Version 4.56 — 2026-10-02 `validate-sri` Hooked Into `manage.sh` (tooling + docs)

Files: `manage.sh`, `SERVER_MANAGEMENT_SCRIPT_GUIDE.md`. No `app.py`, JS, CSS or template change. Details and test notes are in the 2026-10-02 part 3 sync note at the top.

- **Added:** `./manage.sh validate-sri [--fix]` (runs `sri_validator.py` against the project\'s `templates/` and `static/`; exit 1 on a stale/missing hash) and interactive menu **#21** (runs the check, then asks y/N to fix when something is stale/missing). Appended at the end so existing menu numbers did not change.
- **Docs:** guide gets the command, a `validate-sri` section, menu row, files row and two troubleshooting rows; help text, MENU ↔ COMMAND MAP and EXAMPLES in `manage.sh` updated; menu-map table and Quick Reference rows in this file updated; guide pointer now `docs/SERVER_MANAGEMENT_SCRIPT_GUIDE.md`.
- **Not verified:** real tree / Git Bash / Termux run; git pre-commit use.

### Version 4.55 — 2026-10-02 `check_search_index.py` Removed + New `sri_validator.py` (tooling only)

No change to `app.py`, JS, CSS or templates. Details and the test notes are in the 2026-10-02 part 2 sync note at the top.

- **Removed:** `check_search_index.py` (owner decision; deleted in the same commit as the 4.54 audio files). Quick Reference row removed; history mentions in 4.53 kept and marked as deleted.
- **Added:** `sri_validator.py` — check mode (default, exit 1 on STALE/NONE/MISS) and `--fix` mode for the `integrity` attribute of every local `<script src>` and `<link href>` in `templates/`; raw-byte read/write keeps CRLF; inline scripts and external URLs are skipped.
- **Policy change:** the 4.54 note that `video.js`, `video.css`, `viewer.mjs`, `viewer.css`, `locale.json` stay unhashed is superseded: the owner can hash them, and the validator does it. Browsers ignore `integrity` on `rel=icon`/`rel=resource` links; pdf.js is still only partly covered (imports, worker).
- **Not verified:** run on the real `static/` tree and in a real browser (a wrong hash silently blocks the script, so load each page once after `--fix`); effect of git line-ending conversion on hashes.

### Version 4.54 — 2026-10-02 Background Music + SRI Coverage Note (frontend only)

Files: new `static/js/bg_audio.js`, new `static/audio/bg_mus.opus` (not provided), `templates/index.html`, `login.html`, `shared.html`, `404.html`. No backend change. Details and the not-verified list are in the 2026-10-02 sync note at the top.

- **Added:** looping background track on every page via `<audio id="bgMusic">` + `bg_audio.js` (volume 0.20, position/play-state persisted in `localStorage`, interaction fallback for blocked autoplay, no on-page controls).
- **SRI:** `bg_audio.js` is loaded with `defer` and the same `sha384-zKKwynklM+FAe3fTXAeV2eqsmTFe5hev33WXyk3Ac+ebo5jzquGmawtupMCxiWNL` in all four templates. Recompute everywhere when the script changes.
- **Documented SRI policy:** owner-written assets are hashed; patched third-party libraries (pdf.js `viewer.css`/`viewer.mjs`, plus `video.css`, `video.js`, `locale.json`) are intentionally not, since each patch would invalidate the hash. `viewer.mjs` remains the blocker for moving `Integrity-Policy` from report-only to enforcing.
- **CSP:** checked against `app.py`: `media-src 'self' blob:` and `script-src 'self'` already allow the track and the script; no `app.py` change. **Not verified:** the `.opus` file's actual container; live playback in a real browser.

### Version 4.45 — 2026-09-30 Local-Filter Highlight Bar Fix (columnizer inline styles)

Code changed in `static/js/index.js` only; CRLF kept. Reasoning and test numbers are in the 4.45 sync note at the top.

- `smartTableColumnizer()` / `_styleRows()`: the name-cell loop is now `fn.querySelectorAll('a, span:not(.search-highlight)')`. It used to inline-`!important` `display:block` onto the highlight span on every resize/scrollbar change, overriding the 4.41 CSS and producing a full-width yellow bar with the rest of the name on the next line (seen on 1-2 char local filters, e.g. `QB Data 2024`).
- **Verified:** real `index.css` + real function source in headless Chromium 141: 24 term/viewport/call-order combinations pass; before/after screenshots. `node --check`. **Not verified:** live app in a real browser with the other stylesheets; a real `ResizeObserver` callback.
- Corrects the 4.41/4.42 "CSS fixes the bar" claim (incomplete).

### Version 4.44 — 2026-09-30 Deep Search Starts at 3+ Characters (UI)

Code changed in `static/js/index.js` and `templates/index.html`; CRLF kept. Reasoning is in the 4.44 sync note at the top. No backend change.

- `searchTable()`: 1-2 character terms use `performLocalSearch()` (current folder only); deep search when the term is >= `_DEEP_SEARCH_MIN_CHARS` (3) characters or contains an `*.ext` filter. Previously every non-empty term went deep.
- `performDeepSearch()`: stale-response guard on the first-page fetch (`gen !== _dsGen` -> ignore), so a late deep response cannot overwrite the local filter.
- `index.html`: search box placeholder/title now say 3+.
- **Verified:** `node --check`; real function source in a Node `vm` sandbox (gating table + stale-response race + control). **Not verified:** real browser.

### Version 4.43 — 2026-09-30 2-Character Deep Search Fix (FTS5 trigram minimum)

Code changed in `search_index.py` only; CRLF kept (853 CRLF, 0 bare LF). Reasoning and test numbers are in the 4.43 sync note at the top.

- **Root cause:** `files` FTS5 uses `tokenize='trigram'`; `MATCH` returns no rows for queries under 3 characters, while `count()` (plain `LIKE`) still counted them — API returned `total_count: 5999, results: []` for `qb`.
- `_db_search()`: queries under `_FTS_MIN_QUERY_LEN` (3) characters use the `files_meta` `LIKE ... ESCAPE '\'` path (parameterised, `LIMIT`/`OFFSET` in SQL, ext filter via `ext_lower`); 3+ characters and ext-only queries unchanged.
- New `_like_contains()` escapes `%`, `_`, `\`; `count()` uses it too, so totals match rows for queries containing those characters.
- Response shape, `app.py`, frontend: unchanged in 4.43. 1-character API queries also return results (no backend minimum added); the UI stops sending 1-2 character terms as of 4.44.
- **No re-index needed.**
- **Verified:** real module + crawler on a 20,405-file tree (2-char before 0 rows → after full pagination = `count`, no dupes, case-insensitive, folders and deep paths included; nine 3+ char queries identical before/after); 1.5M-row DB timings (11 ms typical, 137 ms worst case). **Not verified:** HTTP route, browser UI, owner's real DB, non-FTS mode DB, Windows/Termux.
- **Observed, not changed:** FTS `MATCH` covers path columns, so 3+ char results can include entries whose path (not name) matches, unlike `count()` and the new short-query path; dead code after `return` in `count()`.

### Version 4.42 — 2026-09-30 Search Follow-up (file-row highlight, no-results toast)

Code changed in `static/js/index.js` only; CRLF kept. Reasoning is in the 4.42 sync note at the top.

- `highlightSearchTerm()`: wraps bare name text in `span.fn-text` before highlighting so the flex `.file-name` keeps one text item (fixes the split/stacked highlight on file rows).
- `displayDeepSearchResults()` empty branch: local filter runs first; toast text depends on whether it found anything.
- **Verified:** `node --check`; headless Chromium render of real `index.css` with folder + file rows at 1400px (highlight inline, tight, icon + eye button preserved, double-run idempotent). **Not verified:** the live page; the 2-char backend behaviour (open).

### Version 4.41 — 2026-09-30 Search Highlight Fixes (yellow bar, word gaps, entity-safe, icon-preserving)

Code changed in `static/js/index.js` and `static/css/index.css`; CRLF kept in both. Full reasoning is in the 2026-09-30 search-highlight sync note at the top.

- **`static/css/index.css`**: `.search-highlight` — `padding: 0`, `font-weight: inherit`, `display: inline`, `box-decoration-break: clone`; new `#filesTable td .file-name span.search-highlight` / `... a span.search-highlight` override (`display:inline !important; width:auto !important; max-width:none !important; padding/margin:0 !important; ...`) to beat the `.file-name span {display:block; width:100%}` rules that stretched the highlight across the cell.
- **`static/js/index.js`**: `highlightSearchTerm()` rewritten to wrap matches in text nodes (preserves icon/folder link/eye button, escapes the regex term, idempotent); `highlightText()` takes raw text and escapes per piece (fixes matches inside HTML entities); both call sites in `createSearchResultRow()` pass `result.name` instead of `escapeHtml(result.name)`.
- **Verified:** `node --check`; jsdom test of both functions. **Not verified:** real-browser look of the CSS fix.
- **Observed, not changed:** the `td.vt-spacer-cell` with `style="height: 0px"` and the fixed-width inline style on `td.search-name-cell` shown in DevTools are set from JS (CSSOM / layout code), not markup, and are not the cause of this bug.

### Version 4.40 — 2026-09-30 Deep Search Row Windowing (virtual scroll) + highlightText Regex Fix

Code changed in `static/js/index.js` and `static/css/index.css`; CRLF kept in both. Full reasoning is in the 2026-09-30 deep-search sync note at the top.

- **`static/js/index.js`**: the deep-search pagination block (`_DS_CHUNK`, `_dsResults`, `_dsRendered`, `_dsObserver`, `_dsAttachSentinel`, `_dsAdvance`, `_dsRemoveSentinel`, `_dsDisconnectObserver`) replaced by a windowing engine (`_dsAll`, offsets array, height cache, `_dsMountRange`, `_dsRenderWindow`, `_dsScheduleMeasure`, scroll/resize handlers, `_dsFetchNextPage` prefetch, `_dsRemoveResults`). Touched consumers: `performDeepSearch()` (state reset + `_dsGen++`), `displayDeepSearchResults()`, `hideDeepSearchResults()`, `hideLocalResults()` (skips the new spacer/loading rows), `toggleSelectAll()`, `updateSelection()` total, both delete success paths. `highlightText()` now escapes regex metacharacters.
- **`static/css/index.css`**: `.ds-loading-row .ds-loading-icon` / `.ds-sentinel-label` (replace inline styles that CSP would drop).
- **Behaviour changes worth knowing:** select-all in deep search selects loaded results only; a failed page fetch stops further paging for that search (a new search resets it) instead of retrying on every scroll tick; an empty page ends paging.
- **Verified:** `node --check`; jsdom harness on 50,000 mocked results (bounded DOM, all pages load, select-all, delete, regex-escape).
- **Not verified:** real browser scroll feel/measurement, Safari/touch, backend `/api/search`.
- **Owner tunables (VT):** `RENDER_BUFFER = 12`, `DEFAULT_ROW_HEIGHT = 96`, `RESIZE_DEBOUNCE_MS = 150` reconciled across the part-8 note and the 4.34 entry (they disagreed after the owner's edit).

### Version 4.39 — 2026-09-30 manage.sh WebDAV Port Sweep Follows server_config.json (docs only for everything else)

Only `manage.sh` changed in code (shell, LF endings kept). Exactly what changed:

- **`manage.sh`**: new `_webdav_ports()` helper placed before `_pid_is_python`; `_kill_webdav_child`'s loop is now `for port in $(_webdav_ports)` instead of `for port in 8080 8443`; two comments that cited `protocol_manager.py` reworded. Falls back to 8080/8443 per port when `server_config.json` is missing, unreadable, or holds a non-integer / out-of-range value.
- **`docs/MANAGE_SCRIPT_GUIDE.md`**: port-sweep section rewritten (which ports, fallback, the config.py-constant limit); new startup-messages section; `approve --max-downloads` default and `--passkey` behaviour.
- **`README.md`**: background-mode note in the manage.sh section.
- **`CLAUDE.md`**: Version line; new sync note; this entry.
- **Verified:** `bash -n manage.sh`; `_webdav_ports()` run standalone under `set -euo pipefail` (custom ports, bad value, bad JSON, no file, no Python); `version_manage.py` and `revoke_sharing.py` subcommands/flags against the guide.
- **Not verified:** the full `stop` / `start` sweep on Windows, Linux or Termux with non-default ports; `protocol_manager.py` (not provided).

### Version 4.38 — 2026-09-30 manage.sh Guide and README manage.sh Section Fixes (docs only)

No code changed. Verified against the whole of `manage.sh` before writing. Exactly what changed:

- **`docs/MANAGE_SCRIPT_GUIDE.md`** (new): quick start; platform table (Windows Git Bash / Linux / Termux); server, log and utility commands; `security-txt` flags; the 20-item menu and Ctrl-C behaviour; `.manage_pids/` and `logs/` layout; detached-launch design; WebDAV as a separate process and the 8080/8443 port sweep; `PYTHON` override; troubleshooting table. CRLF line endings.
- **`README.md`**: manage.sh section — platform line, link to the new guide, Waitress → Hypercorn, Flask → Quart, `create-user` → `manage-users`, security.txt menu number 17 → 19, `update_pymodules.sh` → `setup_pymodules.sh`; Deployment Guides table gained a manage.sh row.
- **`CLAUDE.md`**: Version line; new sync note; this entry; Related Documentation bullet. Earlier entries untouched.
- **Left alone (code):** hard-coded 8080/8443 port sweep in `_kill_webdav_child`.
- **Not verified:** any command was run; the `version-manage` / `revoke-shares` subcommands (taken from `manage.sh` help text only); README `cheroot` row (still needs `requirements.txt`).

### Version 4.37 — 2026-09-30 Console and Comment Text Fixes, README Deployment Guides Table (no logic changes)

Only strings and a comment changed in code; verified against `webdav_server.py` (`_build_app()` wraps the app in `_CertMiddleware`, `_start_hypercorn()` gives the same app to both `bind` and `insecure_bind`) and `manage.sh` (`setup-smb`, menu #11) before editing. Exactly what changed:

- **`webdav_server.py`**: the `print()` after "WebDAV HTTPS: ..." in `start()` now reads "Import {cert_path} as a trusted root, or download it from https://{LOCAL_IP}:{https_port}/webdav.crt (the cert isn't trusted yet, so that first fetch is trust-on-first-use)." Replaces the wrong "manually (or serve it yourself)" / "plaintext HTTP listener that used to host it" text.
- **`config.py`**: SMB comment above `SMB_PORT` and the `_configure_smb()` prompt: `./manage.sh smb-setup` → `./manage.sh setup-smb` (2 places).
- **`README.md`**: Deployment Guides table gained an SMB row (`SMB_PROTOCOL_DEPLOYMENT.md`) and a User Guide row (`USER_GUIDE.md`); both files were provided but not linked.
- **`CLAUDE.md`**: Version line; new 2026-09-30 sync note; this entry. Earlier entries untouched.
- **Still open:** README `cheroot` row (needs `requirements.txt` / `setup_pymodules.sh`).
- **Not verified:** the new startup message on a running server (only `py_compile` was run); `/webdav.crt` on `:8443`, `curl.exe -k`, rclone `no_check_certificate=true`.

### Version 4.36 — 2026-09-30 WebDAV HTTPS-by-Default Documentation Sweep (docs only)

No code changed. Verified against `config.py`, `webdav_server.py`, `ssl_cert.py`, `ftp_server.py` and `app.py` before editing. Exactly what changed:

- **`README.md`**: package table `wsgidav` row → "WebDAV (HTTPS on port 8443 by default)"; quick-tunnel command and tunnel-port bullets now lead with `8443` and describe `8080` as off by default; Cloudflare `config.yml` ingress `service:` `http://localhost:8080` → `https://localhost:8443`; port table lists HTTPS first and marks HTTP a fallback; WebDAV section gets an HTTPS-default note; Windows step no longer downloads the cert from `:8080` — copy `db/webdav.crt` by hand, or `curl.exe -k` from `https://SERVER-IP:8443/webdav.crt`, then `Import-Certificate`; macOS example → `https://SERVER-IP:8443/` plus the `security add-trusted-cert` step; Linux davfs2 example → `https://SERVER-IP:8443/` plus the `update-ca-certificates` steps; rclone quick mount → `https://SERVER-IP:8443/` with `no_check_certificate=true`; firewall examples annotate `8080` as only-if-enabled. The README had no `./manage.sh smb-setup` text (its SMB line already read `python smb_setup.py` only), so nothing was removed there.
- **`RCLONE_DEPLOYMENT.md`**: connection strings (5 places, incl. the Windows mount) → `https://SERVER-IP:8443/` + `no_check_certificate=true`; new notes explaining the option and the HTTP fallback; named remote `cloudinator` is now the HTTPS remote (`no_check_certificate = true`), the old `[cloudinator-https]` block is gone, and the HTTP remote is kept as `[cloudinator-http]` for setups with `WEBDAV_ENABLED` on; registry-edit wording in the comparison table, mount intro, platform notes and summary table now says it applies to plain HTTP only; two troubleshooting rows updated; dead `WINDOWS_DEPLOYMENT.md` pointer replaced with the USER_GUIDE WebDAV section.
- **`USER_GUIDE.md`**: WebDAV port table order/labels; `BasicAuthLevel` registry step marked plain-HTTP-only; `net use` lists HTTPS first; cert-import block replaced (no `:8080` download); macOS, Linux (`mount` and `fstab`), rclone example and the methods summary row → HTTPS `8443`; WebDAV "Inaccessible" troubleshooting mentions the untrusted cert and marks the `reg add` HTTP-only; **stale session default fixed** — 1 hour / `3600` → 365 days / `31536000` (Session Management, Session Expiration, Troubleshooting), with the `python config.py` → Server Settings → Session Timeout route and the `server_config.json` override.
- **`SETUP_TUNNEL_ADVANCED.md`**: "What should I tunnel" table and decision guide; quick-demo commands (HTTPS first, HTTP labelled only-if-enabled); troubleshooting row (no more "import cert or use HTTP; check BasicAuthLevel"); parameterized-script intro and `$SERVICE_PORT_WEBDAV` comment (the ingress in that script uses `https://`, so `8080` would not have worked).
- **`SMB_PROTOCOL_DEPLOYMENT.md`**: removed `# or ./manage.sh smb-setup` (manage.sh's command is `setup-smb`, not `smb-setup`).
- **`CONFIG_PY_REFERENCE.md`**: removed the same `./manage.sh smb-setup` mention; `WEBDAV_ENABLED` purpose text now says plain-HTTP, off by default, HTTPS-off/fallback only. Other defaults re-checked against `config.py` and already correct (`PORT` 5000, session 31536000, `HLS_MIN_SIZE` 50 MB, `IMG_COMPRESS_MIN_SIZE` 1 MB, WebP quality 50, ports 8443/8080/2222/2121/445/8445).
- **`CLAUDE.md`**: Version line and Last Updated; new 2026-09-30 sync note; Protocol Servers port table row for `8080`; SSL Certificate bullet and Key Decision Points item 7 no longer claim `/webdav.crt` is served at `http://HOST:8080/`.
- **Left alone (code, not docs):** stale `./manage.sh smb-setup` in `config.py`; the "import manually (or serve it yourself)" startup message in `webdav_server.py`; README's `cheroot` package-table row / `pip install` line (unverifiable without the requirements file).
- **Not verified:** that `/webdav.crt` is actually reachable on `:8443` on a running server (code reading only); the `curl.exe -k` and rclone `no_check_certificate=true` connection-string forms were not run.

### Version 4.35 — 2026-09-29 config.py Settings Documentation Audit (docs only)

- Re-checked every top-level `config.py` name against `CONFIG_PY_REFERENCE.md` and this file. No code changed.
- Added missing settings: `VERSION_WORKER_COUNT` (1), `VERSION_MAX_CONCURRENT_SNAPSHOTS` (2) and the per-platform `PRESET_PATHS`.
- Corrected: `server_config.json` overrides in-code constants on import; the file is anchored next to `config.py` (not the CWD); `ALLOWED_EXTENSIONS` and the directory settings are not saved to it; WebDAV HTTP/HTTPS exclusivity wording; Termux and unknown-platform default paths (`~/uploads`, `./uploads`); which Version Engine settings the admin menu can and cannot change.
- `README.md` "Default Settings" corrected to match `config.py` (session lifetime 365 days not 1 hour, HLS minimum 50 MB not 25 MB, image compression threshold 1 MB not 3 MB, force-HLS list had `mov`/`ts` that `config.py` doesn't; added SMB and the WebDAV HTTP/HTTPS defaults) and now links `docs/CONFIG_PY_REFERENCE.md` (the reference's relative links assume it lives in `docs/`).
- Code observations left untouched: `configure_server_settings()` prompts `(0-13)` but its invalid-option message says `0-12`, and Save & Exit is option 10 though listed last; the protocol comment in `config.py` still says "main Flask server (5000)". All cosmetic.

### Version 4.34 — 2026-09-29 VT Rubber-Band Root-Cause Fix (supersedes 4.33 and the CSP theory in 4.32)

- **Root cause:** `index.css`'s end-of-file `#filesTable tbody tr { height:auto !important }` override makes any height on the spacer `<tr>` ineffective (inline, CSSOM, or inserted rule), so the spacers stayed ~13–21px and the wrapper's scroll range was ~35 rows long. CSSOM writes are **not** blocked by `style-src-attr`; the only real CSP violation was the static `style=` attribute on the spacer `<td>` (`index.js:1853`), which just left default padding. Reproduced in real Chromium (original: 29–32 reversal frames/run, worst −240px, ends at `scrollTop=0`).
- **`static/js/index.js`** (VT module + `loadDirInfoCells`): spacer height on the spacer `<td>` via `style.setProperty(..,'important')`; `_ensureSpacerRules()` removed; `_makeSpacerRow()` builds the `<td>` with a class, no `style` attribute; new `_listBase`/`_measureListBase()` (offsets are list-relative, `scrollTop` is content-relative); `_renderAll()` mounts for the preserved scroll position, sizes spacers, *then* restores `scrollTop`; `_mountRange()` two-phase + incremental (no whole-window fragment re-insert); `_renderWindow(force, scrollTopOverride)`; `_scheduleMeasure()` compares against current offsets and rebuilds only on real disagreement; `_onResize()` anchors on a row + intra-row offset; new public `VT.rowResized(tr)` called after a folder's `dir_info` size cell is rewritten. No manual `scrollTop` compensation (see part-8 note for why).
- **`static/css/index.css`**: new `.vt-spacer-row` / `.vt-spacer-cell` rules (zero padding/border/line-height/font-size, transparent, no pointer events) placed directly under the `tr{height:auto!important}` override with an explanatory comment; `#tableScrollWrapper { overflow-anchor:auto }`.
- **Verification:** real Chromium harness (see part-8 note) — original vs final on 12- and 120-folder lists; final 0–1 reversal frames (the 1 traced to a test-phase artifact), full-range scroll, no blank gaps incl. bottom, refresh/`scrollToItem`/filter/sort OK, 0 CSP violations. **Not verified:** Safari/Firefox/touch/real GPU/thousands of rows in a real browser. Lag from `backdrop-filter` is a separate, unfixed finding (see part-8 note).
- **Owner-set tunables:** `RENDER_BUFFER = 12`, `DEFAULT_ROW_HEIGHT = 96`, `RESIZE_DEBOUNCE_MS = 150` (current owner values, reconciled in 4.40; see the part-8 note). Owner decision: keep `backdrop-filter` on `.file-table` and leave the animated `body::before/::after` background untouched, so the lag items in the part-8 note are not being pursued.
- **Files changed**: `index.js`, `index.css`, `CLAUDE.md`. `app.py` and `index.html` unchanged (no CSP allow-list change needed — the fix removes the offending attribute rather than hashing it).

### Version 4.33 — 2026-09-29 VT Spacer-Height CSP Fix (⚠️ SUPERSEDED by 4.34 — the CSP diagnosis below is wrong; kept for history)

> **Superseded.** CSSOM writes are not CSP-blocked, and the inserted-rule approach could not work anyway because `index.css`'s `tr{height:auto!important}` beats it. See Version 4.34.

- **Root cause (found from real-browser console logs the user pasted):** `#vtTopSpacer`/`#vtBottomSpacer`'s dynamic height was set via `tr.style.height = ...` in `_makeSpacerRow()` and `_positionSpacers()`. This app's CSP enforces `style-src-attr` with a precomputed hash allowlist (built from the fixed, known set of literal inline-style strings the app actually uses elsewhere), so a `style-src-attr` violation is unavoidable for any *arbitrary/changing* value — an offset in pixels can be almost anything, so it can never match a fixed hash. Every single call was silently blocked by the browser; the spacers never got real height in any real browser session. With spacer height stuck near 0, the wrapper's true scrollable area was far smaller than the windowing math assumed, and the browser clamped `scrollTop` back down on almost every layout pass — very likely the dominant contributor to the "rubber band" symptom, on top of the `_renderAll()` scroll-loss issue fixed in 4.32 below. Not caught by the Version 4.31 jsdom harness because jsdom enforces no CSP at all.
- **`static/js/index.js`**: new `_ensureSpacerRules()` — finds an already-loaded, same-origin stylesheet (`index.css`, permitted via `style-src 'self'`, not `style-src-attr`), inserts two rules (`#vtTopSpacer{height:0px}` / `#vtBottomSpacer{height:0px}`) into it via `CSSStyleSheet.insertRule()`, and caches the returned `CSSStyleRule` objects. `_positionSpacers()` now mutates those rule objects' `.style.height` (CSSOM rule mutation, not an element's `style` attribute — outside `style-src-attr`/`style-src-elem` entirely) instead of setting `_topSpacer.style.height`/`_bottomSpacer.style.height` directly; falls back to the old (CSP-blocked) inline-style assignment with a one-time `console.warn` only if no writable stylesheet can be found at all, so a misconfigured environment degrades instead of throwing. `_makeSpacerRow()` no longer sets `tr.style.height` at creation time (redundant now — the CSS rule already defaults to `0px` and is repositioned on the next `_positionSpacers()` call). The spacer `<td>`'s own static `style="padding:0;border:0;line-height:0;"` (parsed from a literal `innerHTML` string, not a JS `.style.X = ` assignment) was left untouched — it's a fixed string, unlike the dynamic height, and evidently already covered by the existing hash allowlist (it wasn't among the violations in the logs).
- **Verification**: `node --check` syntax pass; diffed against the 4.32 file to confirm the change is scoped to the new helper plus the two call sites it replaces (57 changed lines total, all within the spacer-sizing code path). **Not yet verified in a real browser** — this is exactly the class of bug the user's own console logs surfaced, so a real re-test (confirming the CSP violation is gone and scrolling no longer rubber-bands) is the right next check.
- **Files changed**: `index.js`, `CLAUDE.md`.

### Version 4.32 — 2026-09-29 VT Scroll-Position "Rubber Band" Fix (⚠️ partial — see Version 4.34)

> The `scrollTop` save/restore here was a real but minor bug; the dominant cause was the spacer-height override, fixed in 4.34.

- **Root cause:** `VT._renderAll()` (Version 4.31) sets `tbody.innerHTML = ''` to rebuild the table on every refresh — not just real navigation, but SSE-triggered refreshes, polling fallback, sort, filter, and rename too. Clearing the tbody collapses the table's height to ~0, which collapses `#tableScrollWrapper`'s scrollable height with it, and the browser clamps `wrapper.scrollTop` to 0 as an implicit side effect — before any of `_renderAll()`'s own code runs. The 4.31 changelog's claim that "VT never touches `wrapper.scrollTop` on its own" was true of the code as written but false in practice, since the reset happened as a DOM side effect, not an explicit assignment; this is also why the Node+jsdom harness never caught it — jsdom has no real layout engine, so it never actually collapses/clamps scroll height the way a real browser does. Reported by the user as scrolling "rubber-banding" back toward the top. (See [Version 4.33](#version-433--2026-09-29-vt-spacer-height-csp-fix) above for a second, likely bigger contributor to the same symptom, found the same day.)
- **`static/js/index.js`**: `_renderAll()` now reads `wrapper.scrollTop` into a local before clearing the tbody, and restores it right after the spacers are (re)appended and `_rebuildOffsets()` has given the wrapper its real scrollable height back, just before `_renderWindow(true)`. `navigateToFolder()`'s own explicit `wrapper.scrollTop = 0` (set after `updateFileTable()`/`VT.init()` returns) still wins for real navigation, since it runs after this restore.
- **Verification**: `node --check` syntax pass; diffed against the 4.31 file to confirm the change is scoped to exactly these two spots (capture + restore), no other lines touched. **Not yet verified in a real browser.**
- **Files changed**: `index.js`, `CLAUDE.md`.

### Version 4.31 — 2026-09-28 VT Row Windowing (Virtual Scroll)

- **`static/js/index.js`**: `VT` module rewritten from append-only infinite scroll (`IntersectionObserver` sentinel, 80-row `CHUNK`, never-removed rows) to true row windowing — viewport ± 18-row buffer mounted, two spacer `<tr>`s sized from a cumulative offset array, DOM node count bounded regardless of folder size. Per-item-path height cache (not a fixed row height) handles filenames that wrap onto multiple lines (`index.css` `.name-cell white-space:normal`); offsets rebuild only when a measurement disagrees with the estimate. rAF-throttled scroll; already-mounted rows are moved via `DocumentFragment`, not destroyed/recreated. `loadDirInfoCells()`/row highlighter now take an explicit `rows` param scoped to the current render pass instead of scanning the whole table; stale-row dir-info responses are dropped via `cell.isConnected` while still populating the shared cache. New `VT.scrollToItem(path)`, wired into `performRename()`'s success path. Fixed `bulkDownload()`'s single-item folder/file detection, which read a DOM row that isn't guaranteed to be mounted under windowing — now checks `VT.getAll()` first.
- **Unchanged**: `init()`, `applySort()`, `applyFilter()`, `_getDisplayFiles()`, `storeOriginalTableOrder()`, `updateVisibleCount()`, `reinitializeTableControls()`, the `..` parent-directory row, scroll-position-preservation behavior (VT still never resets `scrollTop` on its own).
- **Verification**: Node + jsdom harness against the real extracted `VT` source, synthetic 50,000-entry folder — DOM node count stays bounded (vs. unbounded growth previously); per-scroll-step cost flat across a 25× data-size increase (2.76×, confirming O(window) not O(n)); sort/filter/select-all/range-select/delete-selected/rename+scrollToItem/deep-search handoff/tiny-folder/empty-folder all pass. jsdom has no real layout engine — text-wrapping simulated via a `getBoundingClientRect()` patch; absolute jsdom timings are not meaningful, only the relative (flat vs. linear) scaling claim is. **Not yet verified in a real browser.**
- **Files changed**: `index.js`, `CLAUDE.md`.

### Version 4.30 — 2026-09-28 Version History Front-end Loading State

- **`static/js/index.js`**: `_vhRestoring`/`_vhDownloading` Sets + `_vhIsRestoring()`; row template renders disabled/spinner Restore ("Restoring…") and Download ("Starting…"); `restoreVersionAction()` rewritten (click guard, 409 in-progress wait via `_vhWaitForRestoreToFinish()`, `finally` cleanup); `downloadVersionAction()` 3 s double-click lock; new `_vhRepaintIfOpen()`.
- **Files changed**: `index.js`, `CLAUDE.md`. `index.css`/`index.html` unchanged.

### Version 4.29 — 2026-09-28 Restore Guard + Streaming Version Download

- **`version_history.py`**: `_inflight` guard + `IN_PROGRESS_MSG` + `inflight_versions()`; `restore()` fast path for an already-restored version; new `open_download_stream()`. `import threading` added.
- **`version_engine.py`**: `restore_version()` uses a unique `mkstemp` temp, retries `os.replace()` on `PermissionError`, wraps job writes in `_retry_locked`; new `Engine.iter_version_bytes()` (verified streaming reader).
- **`app.py`**: `/api/versions/restore` returns 409 `{in_progress}` for a duplicate; `/api/versions/download` streams via async generator with `Content-Length`; `/api/versions/list` adds `restoring`.
- **Pending**: client-side loading/disabled Restore button in `index.js` (file not provided).
- **Files changed**: `version_history.py`, `version_engine.py`, `app.py`, `CLAUDE.md`.

### Version 4.28 — 2026-09-28 Write Gate + storage_index.json Save Fix

- **`file_monitor.py`**: `_save_cache()` rewritten — `_save_lock` now actually used, dict copied under `self.lock`, unique temp file via `tempfile.NamedTemporaryFile`, `os.replace()` retried on `PermissionError` (WinError 5/32), temp file cleaned on failure. Fixes the repeated `[WinError 32] … storage_index.json.tmp` in `webdav_server` (two processes + multiple threads sharing one fixed `.tmp` name).
- **`version_engine.py`**: new `_GatedConnection` + `_WRITE_GATE` (process-wide write serialisation, released on commit/rollback/close, auto-rollback on failed write, 60 s acquire timeout); `busy_timeout` 10 s → 30 s; `_retry_locked` now wraps `run_gc`, `_create_job("gc")`, `_set_meta`, the `vanished` UPDATE loop, `_finish_job` and `_apply_retention`; scanner/watcher lock errors log as WARNING and other errors log with traceback; `_worker_loop` rolls back on escaped errors. `import re` added.
- **Verification**: stub-config stress test (12 workers, 303 files incl. chunked, concurrent GC, 12 s external write lock): original 1 ERROR, patched 0 ERROR, 303/303 completed. Real-deployment verification pending. Log evidence suggests the deployed engine may have predated v4.27 — restart the whole server and confirm.
- **Files changed**: `file_monitor.py`, `version_engine.py`, `CLAUDE.md`.

### Version 4.27 — 2026-09-28 Lock Follow-up

- `version_engine.py`: `run_gc()` rewritten to short `BEGIN IMMEDIATE` batches (blocking of other writers on a 150k-object table measured ≈1.0 s → 0.02 s); `snapshot_file()` treats a locked DB as transient (backoff, discard the half-made row, re-queue via `_known_state` on give-up, no permanent failed row); `_retry_locked()` around leading bookkeeping writes; `_worker_loop` requeues on an escaped lock error; `PRAGMA synchronous=NORMAL`; failures log with traceback; `last_snapshot_busy()`.
- `version_history.py`: `retry_snapshot()` reports "database is busy" when the engine gave up on a locked DB instead of "already up to date".
- Verified against the real engine with stub config: transient lock retried through, give-up path, self-heal after release, GC+retention+restore byte-exact, earlier slow-disk/concurrent-capture regressions. Holder of the original lock **not proven** from the log alone; **not verified on the real deployment**. See [SQLite write-lock discipline](#sqlite-write-lock-discipline-2026-09-28).

### Version 4.26 — 2026-09-28 SQLite Write-Lock Fix

- **Root cause found:** `version_engine.py`'s `_capture_chunked()` left each chunk's `version_objects` INSERT uncommitted, holding SQLite's write lock across the next chunk's read/hash/fsync — nearly the whole capture of a large file. Concurrent writers (Retry, `restore_version()`'s leading `_create_job`, scanner, GC) hit `database is locked`. Fixed: object row + link committed together per chunk (`_store_object_from_tmp(..., commit=False)`).
- `version_engine.py` also: `busy_timeout` set before the WAL pragma; `run_gc()` commits every 100 deletions; `_mark_version_failed()` retries on a lock. 48 changed lines total.
- `version_history.py`: `_with_lock_retry()` + friendly "database is busy" message; unexpected exceptions in restore/download/delete/clear are caught and logged instead of becoming a 500. `app.py`: `/api/versions/list` returns JSON 503 on failure. `index.js`: `_vhJson()` so a server error is no longer reported as "Could not reach the server".
- Security headers deliberately **unchanged**; the `Permissions-Policy` ad-API warnings are not from this app, the `Document-Policy: document-write` warning is Edge not recognising it (cosmetic).
- Verified with a slow-disk simulation on the real engine (before: fail, after: pass), concurrent captures, byte-exact restores, GC. **Not yet verified on the real deployment or in a real browser.** See [SQLite write-lock discipline](#sqlite-write-lock-discipline-2026-09-28).

### Version 4.25 — 2026-09-28 Version History Polish

- `version_engine.py`: new `Engine.clear_failed_versions(file_path)` (hard delete of a file's `failed` rows; removes partial `version_objects` first).
- `version_history.py`: `clear_failed()` and `retention_info()`; `app.py`: `/api/versions/list` now also returns `retention`, new `POST /api/versions/clear-failed`.
- Frontend: failed/deleted rows hidden behind a toggle, two-step "Clear failed attempts", "X of N versions kept" line, Retry result shown inline (no popup); `#notificationModal` raised to `z-index: 1100` so Restore/Delete/error popups are no longer hidden behind the Version History modal.
- Verified: backend against a real failed-chunked-capture (partial chunk rows) + GC + restore; UI in jsdom against the real rendered page (readwrite and readonly). **Experimental.**

### Version 4.24 — 2026-09-27 Version History Web UI

- New `version_history.py` (logic only) and six routes in `app.py` (`/api/versions/list|download|restore|retry|delete`, `/download/recovered/<path>`); `version_history.init()` called once from `app.py`'s module-level startup. `dev_server.py`/`prod_server.py` untouched.
- `version_engine.py`: four new pure-data `Engine` methods; `version_manage.py`'s `do_list()`/`do_delete()` refactored onto them (CLI output verified unchanged). Restore-to-`.recovered/` is deliberately different from the CLI's restore-anywhere.
- Frontend: `#downloadOptionsModal` + `#versionHistoryModal`, per-version Download/Restore/Delete, typed-filename delete confirmation, Retry Now banner; row action bar left exactly as it was before the feature.
- Fixed: `Response.call_on_close` doesn't exist in Quart (downloads now buffer); `/csrf-token` unreachable anonymously (added `get_csrf_token` to `validate_session`'s exempt list); `version_engine.py` storing `"capture error"` instead of the real exception (now `"capture failed: <detail>"`; pre-existing rows unchanged).
- Verified live through a real Quart test client with the real login flow; see [Version History Web UI](#version-history-web-ui-2026-09-27) for what was and wasn't covered. **Experimental — not yet deployed.**

### Version 4.23 — 2026-09-26 manage.sh Integration + version_manage.py Interactive Mode

- `manage.sh`: `version-manage` inserted as the new **menu #9** (first Utilities entry, at the user's explicit request), `config` moved to **#10**; everything previously at 9–19 shifted down to 11–20 in unchanged relative order. Touched all four places a menu command lives (per this doc's own "Adding a command" checklist): the `cmd_menu` `echo` lines, the `case "$choice"` dispatch, the `main()` `case "$cmd"` dispatch, and `cmd_help` (command description, MENU ↔ COMMAND MAP, an EXAMPLES block). Also added to the dashboard's "Utilities:" hint line. Verified programmatically (numbers 1–20 each appear exactly once across the menu dispatch) and via a CRLF-preserving syntax check (this sandbox's `bash -n` chokes on CRLF for reasons unrelated to this edit — confirmed identical failure on the untouched original upload — so the check was done against a temporary LF-converted copy; the delivered file's CRLF line endings were preserved throughout, verified byte-for-byte with zero stray LF-only lines afterward).
- `version_manage.py`: added a full interactive menu (`interactive_menu()`, entered automatically when run with no CLI arguments — `list`/`restore`/`delete` subcommands still work exactly as before). Refactored the three commands' logic into `do_list()`/`do_restore()`/`do_delete()`, called identically by both the CLI (`cmd_list`/`cmd_restore`/`cmd_delete` — now one-line `argparse`-`Namespace` unwrappers) and the menu — no logic duplicated between the two interfaces.
- Ctrl-C hardened and *verified with real signal delivery* (`subprocess.Popen.send_signal(SIGINT)`, not simulated stdin input): a `_prompt()` wrapper around every `input()` call converts `KeyboardInterrupt`/`EOFError` into a clean cancel; the top-level menu prompt treats it as "quit", a sub-prompt inside an action treats it as "cancel this action, return to the menu" (mirroring `manage.sh`'s own `cmd_menu` convention exactly). Confirmed: quitting at the top-level menu (exit 0, no traceback), Ctrl-C mid-action returning cleanly to a still-functional menu, and Ctrl-C during a CLI-mode confirmation prompt (`restore --overwrite`, exit 1, "nothing was touched", no traceback). This also confirms the outer layer works as intended: `manage.sh`'s `run_utility()` hands the child a normal, default-disposition SIGINT (not an inherited ignored one), so `./manage.sh version-manage` survives Ctrl-C inside the Python process without `manage.sh` itself exiting.
- `CLAUDE.md`: menu ↔ command map table updated to the new 1–20 numbering with an explicit note that this is the third mid-list renumber; added a `version_manage.py` row to the Ctrl-C model table; expanded the Version Engine section's `version_manage.py` write-up.

### Version 4.22 — 2026-09-25 Universal File Versioning Engine

- New subsystem, not a revision: per-file version history, independent of Share Links. Two new files:
  - `version_engine.py` — parent API (`start`/`stop`/`force_kill`/`status`) + `--worker` child process. Mirrors `protocol_manager._spawn_webdav_process()`'s subprocess pattern deliberately (same Popen args, env vars, Windows console-window guard, piped+relayed stdio). No watchdog/auto-respawn — crash recovery on next `start()` is the sole self-healing mechanism, a considered omission.
  - `version_manage.py` — separate admin CLI (`list`/`restore`/`delete`), added after the first pass shipped with no operator interface at all. `delete` requires a typed, version-and-filename-specific confirmation sentence; no `-f`/`--yes` shortcut exists.
- `config.py`: ~25 new `VERSION_*` settings (master switch, chunking — verified independent of the existing upload `CHUNK_SIZE` — workers, tracking scope, retention, GC), integrated into the existing `save_server_config()`/`load_server_config()` pattern, plus a new menu tree (`configure_version_engine_settings()`, `configure_version_tracking()`'s list add/remove/clear sub-menu).
- `paths.py`: `get_versions_dir()`/`set_versions_dir()`/`reset_versions_dir()` — a fourth sibling of `db_path`/`cache_path`, deliberately not nested under cache (version history is irreplaceable; cache is rebuildable).
- `dev_server.py`/`prod_server.py`: `version_engine.start()`/`.stop()`/`.force_kill()` wired in at the same points as the equivalent WebDAV calls, including `prod_server.py`'s two-stage SIGINT shutdown.
- `protocol_manager.py` and `app.py` confirmed **byte-identical** to pre-change (`diff`-verified) — required by the spec this was built from.
- Storage: hybrid full-object/chunked content-addressed store, SHA-256 identity, hash-verified reads, atomic writes, byte-for-byte-verified restore (`original_sha256==restored_sha256 AND original_size==restored_size`, enforced before any file is replaced).
- Bug found and fixed during testing: `run_gc()`'s object deletion violated a foreign-key constraint when the object was still linked from soft-deleted/failed version rows — fixed by clearing those stale links first.
- See the new [Version Engine (File Versioning)](#version-engine-file-versioning-2026-09-25) section for the full writeup, including what was and wasn't verified (no live Windows/Termux run, no benchmark pass, no live two-stage-shutdown-through-a-real-process test).

### Version 4.21 — 2026-09-24 WebDAV Client-IP Trust-Chain Fix

Follow-up to Version 4.20, same day. That version shipped `webdav_server.py`'s new audit-logging `ip=` field as `REMOTE_ADDR` only, with a flagged open question: is WebDAV ever tunneled? Confirmed yes — port 8443 (HTTPS) runs through `cloudflared`; port 8080 (plaintext) does not, since (per this file's own `start()` logic) HTTPS wins exclusively over the plaintext fallback whenever it's enabled and starts, and only the secure listener is exposed through the tunnel — the same "deploy the secure variant, not both" pattern already used for FTP vs. FTPS.

Practical effect of the gap: every WebDAV audit line for internet-facing traffic was logging `cloudflared`'s own local loopback address instead of the real client — not a wrong-but-plausible IP, a useless one, for 100% of tunneled requests.

- `_client_ip()` in `webdav_server.py` now mirrors `app.py`'s `get_client_ip()` trust chain, adapted from Quart's `request.headers` to WSGI's `environ` `HTTP_*` convention: `CF-Connecting-IP` first, then `X-Forwarded-For`, then `REMOTE_ADDR` as the final fallback (still correct, and still used, for direct LAN/Tailscale access).
- Both call sites — `_audit_login()` and `_AuditMiddleware._record()` — already went through this one function, so no other code changed.
- The module docstring's "Audit logging" section was corrected to match — it previously said `X-Forwarded-For` was "deliberately NOT trusted," which was accurate when written and is no longer accurate now.
- See the updated "Where `ip=` comes from" bullet under [WebDAV Implementation Notes](#webdav-implementation-notes) for the full before/after.

**Verification, and a gap worth being explicit about**: `_client_ip()` was unit-tested in isolation against six scenarios — tunneled request with `CF-Connecting-IP` present, generic reverse proxy via `X-Forwarded-For`, direct access with no proxy headers, an empty `environ`, a `None` environ, and a blank/whitespace `CF-Connecting-IP` header falling through correctly — all passed. This did **not** get the same full live-server round-trip the SFTP/FTP/SMB patches got in Version 4.19: a bare, unmodified `hypercorn.serve()` call — no project code involved — failed to bind a listening socket in the sandbox used for this pass (reproduced directly; an environment issue, not a regression). The change is narrowly scoped (one function, swapping which `environ` keys it reads), and the surrounding pipeline was already proven working end-to-end in Version 4.20's own testing, but this specific fix has not been confirmed against a real running server by either Claude instance. Worth a real-world check post-deploy: trigger a WebDAV operation through the actual tunnel and confirm the audit line shows a real external IP, not `cloudflared`'s.

**Still open**: whether SFTP, FTP/FTPS, or SMB are ever exposed through the Cloudflare Tunnel too. Unlike WebDAV, these are raw TCP protocols, not HTTP — Cloudflare Tunnel can carry them, but only via TCP-mode ingress, which injects no HTTP headers at all. If any of them are tunneled, their audit `ip=` (added in Version 4.19) has the same class of problem this version just fixed for WebDAV, but the fix would be structurally different — parsing the PROXY protocol preamble `cloudflared` can optionally send on a TCP-mode tunnel, which none of `sftp_server.py`/`ftp_server.py`/`smb_server.py` currently do. Not yet investigated — needs confirmation of whether this deployment actually tunnels any of those three before deciding whether it's worth building.

### Version 4.20 — 2026-09-24 WebDAV Audit Logging + Client-IP Attribution for TLS-Teardown Errors

Prompted by a live log excerpt — `Unhandled exception in client_connected_cb` / `ssl.SSLError: [SSL: APPLICATION_DATA_AFTER_CLOSE_NOTIFY]` on the WebDAV process — with the observation that the audit logs are supposed to know which IP a request came from. Two separate causes. Files changed: `webdav_server.py` and `hypercorn_ssl_fix.py`.

- **WebDAV audit logging (the actual gap)**: Version 4.19 added audit logging to SFTP/FTP/SMB and described that as covering the non-web protocols — WebDAV was the fourth and was missed. Its `log` was `logging.getLogger(__name__)` (`"__main__"` in the subprocess), never called. Now `logging_setup.get_logger("webdav")`, plus a new `_AuditMiddleware` (file operations + `permission_denied`) and login/`login_failed` logging in `CloudinatorDC.basic_auth_user()`, in the same `user`/`action`/`path`/`ip` shape. Details, exact status codes, and what's deliberately not logged: [WebDAV Audit Logging and Client-IP Attribution](#webdav-audit-logging-and-client-ip-attribution-for-tls-teardown-errors-2026-09-24).
- **TLS-teardown traceback with no IP**: not fixable by logging configuration — asyncio's own exception handler no longer has the peer address (`peername` is `None`, verified). Fixed in `hypercorn_ssl_fix.py`'s `_patched_close()` (peer read before close; new `except OSError` logs one line per connection instead of a traceback), so it covers both the WebDAV process and the main listener. Same first line as the 2026-09-09 `TimeoutError: SSL shutdown timed out` entry but a different cause — see [WebDAV Resilience Issues](#webdav-resilience-issues-2026-09-09).
- **`hypercorn_ssl_fix.py` logger**: was `logging.getLogger(__name__)` — no handler, so its own startup INFO line was silently dropped (same dead-logger class as FTP/SFTP/WebDAV). Now `logging_setup.get_logger("ssl_fix")`; a `hypercorn_ssl_fix: patched TCPServer._close() …` line now appears in the log at every start.
- **Disconnect-guard traceback**: `_DisconnectAbortMiddleware.__call__` now swallows its own deliberate `ConnectionResetError` (exact match on the new shared constant `_GUARD_MSG`) instead of letting Hypercorn report it as `Error in ASGI Framework` — previously one traceback per cancelled download. Every other exception, including a genuine `ConnectionResetError`, still propagates. See [WebDAV Disconnect-Flood Guard](#webdav-disconnect-flood-guard-2026-09-09-second-pass).
- **`webdav_server.py` Hypercorn errorlog**: `_build_hypercorn_logger()` now returns `logging_setup.get_logger("hypercorn")`, matching `prod_server.py`'s copy, instead of its own `StreamHandler` on the tee'd stderr (which produced double-timestamped `[STDERR]` lines).
- **Doc-only fix**: Startup Order item 9 still said WebDAV starts in a daemon thread; it's been its own OS subprocess since 2026-09-09.

**Verification**: real HTTPS requests against a real running `webdav_server.py` process (Python 3.12.3, Hypercorn 0.18.0, asgiref 3.12.1, wsgidav 4.3.5, real `logging_setup.py`, real `hypercorn_ssl_fix.py`) — 13 audit lines with correct user/path/IP incl. a non-ASCII filename, ranged-download de-duplication, `COPY`/`MOVE` `->` form, readonly `403`s, failed login. The unmodified original pair reproduced the reported log lines 3/3; the patched pair gave exactly one IP-tagged line per connection and zero unhandled exceptions 3/3, and normal traffic produced no teardown lines. For the guard change: two 200 MB downloads reset-cancelled early on three variants — guard disabled (test-only control) 48,757 flood lines; guard without the catch 0 flood lines + 2 tracebacks; guard with the catch 0 + 0 — and a direct check that a real `ConnectionResetError` and an unrelated `ValueError` still propagate.

**Not verified**: Windows / Python 3.14; a real client sending data after `close_notify` (the identical `SSLError` was injected at `unwrap()`); the main listener via `prod_server.py` itself (only through the shared `TCPServer` path); any proxy/tunnel path. The audit `ip=` is the raw TCP peer — see the deployment caveat in the 2026-09-24 sync note, part 2 (behind the Cloudflare Tunnel the main listener's teardown line would show `cloudflared`'s address).

**Found, not fixed** (details under WebDAV Resilience Issues): the `"asyncio"` logger's output still arrives as untagged `[STDERR]` lines.

### Version 4.19 — 2026-09-24 SFTP/FTP/SMB Audit Logging + SFTP Upload Flag Bug Fix

Prompted by a question about whether deleted-file logs could actually identify *who* deleted something — answer at the time was no, for any of the three non-web protocols. `sftp_server.py`, `ftp_server.py`, and `smb_server.py` all gained success-path audit logging (`user`/`action`/`path`/`ip`, one line per operation) for login and every write operation. All three previously either logged nothing on success (SFTP: only `PERMISSION_DENIED` cases were logged) or had a dead logger that was never called at all (FTP: `log = logging.getLogger(__name__)` created but unused anywhere in the file). All three now log through `logging_setup.get_logger(...)` — a plain `logging.getLogger(__name__)` with no handler attached goes nowhere, same class of bug already fixed once before in `protocol_manager.py`'s `_pm_logger`.

- **SFTP**: `_CloudinatorSFTPInterface._audit()` logs `remove()`/`rename()`/`mkdir()`/`rmdir()`/write-mode `open()` on success; `check_auth_password()` logs both successful and failed logins. `_SSHServer` gained a `client_addr` attribute (set in `_handle_connection()` before `start_server()`) so file-op audit lines can attribute a source IP, not just a username. See the new bullets in [SFTP Implementation Notes](#sftp-implementation-notes).
- **FTP**: `CloudinatorFTPHandler` overrides pyftpdlib's `on_login`/`on_login_failed`/`on_file_sent`/`on_file_received` and wraps `ftp_DELE`/`ftp_RMD`/`ftp_MKD`/`ftp_RNTO`, checking `self._last_response` after calling the base handler to confirm success before logging. See [FTP Implementation Notes](#ftp-implementation-notes).
- **SMB**: new `_install_audit_logging()` hooks `SMB2_CREATE`/`SMB2_SET_INFO`/`SMB2_CLOSE` the same way every other hook in this file works (`hookSmb2Command()`, call-original-then-inspect). Deliberately skips plain read-opens (Explorer browsing/thumbnail noise) — logs write/create/mkdir/rename/delete only. See [SMB Implementation Notes](#smb-implementation-notes).

**Bug found and fixed while live-testing the SFTP patch (unrelated to the audit-logging goal, but blocking it)**: `sftp_server.py`'s `_flags_to_mode()` and the write-permission check in `open()` tested the `flags` argument against hardcoded SSH_FXF_* wire-protocol bit values. paramiko's `SFTPServerInterface.open()` doesn't receive those — paramiko's own `_convert_pflags()` translates them into `os.O_*` flags first. The two bit layouts don't line up; critically, `os.O_WRONLY` (`1`) collided with the old `_FXF_READ` bit (`0x01`), so **every brand-new-file SFTP upload was silently misdetected as a read-only open** and failed with a bare "No such file" — confirmed against a real paramiko client, 100% failure rate on new uploads before the fix. Existing-file overwrites were similarly broken. Fixed to test the real `os.O_*` flags; see the "Open-flags bug" bullet under [SFTP Implementation Notes](#sftp-implementation-notes) for the full mechanism.

**Verification**: every claim above was checked by actually running the patched code against a real client, not just read over — `paramiko` for SFTP (upload/overwrite/download/mkdir/rename/rmdir/delete, the readonly-role permission block, and both login outcomes), `pyftpdlib` + `ftplib` for FTP (same set, plus a failed login), and `impacket`'s `SMBConnection` for SMB (upload-vs-overwrite distinction, mkdir/rename/delete/rmdir, and confirming plain reads produce zero audit lines).

### Version 4.17 — 2026-09-22 database.py Verification Pass

Documentation-only — **no code changed**. `database.py` (755 lines) was read in full for the first time, to check items the 2026-09-21 ops-tooling pass had flagged as inferred rather than confirmed.

- **Confirmed**: all `revoke_sharing.py`-called `database.py` share/request methods exist with the guessed signatures (see the updated [Database Tools](#database-tools) and Key Functions entries).
- **Confirmed**: the double-checked-locking + `conn.commit()` bootstrap fix under Troubleshooting → Quart/Hypercorn Migration Issues matches `_connect()`/`_do_bootstrap()` exactly, including the specific failure symptom described.
- **Confirmed, and gotcha #2 strengthened**: `update_share_settings()` never clears `passkey_hash` on a mode change unless `clear_passkey=True` is passed explicitly. This is now a direct finding, not an inference — see [Database Tools](#database-tools).
- **Still open**: whether `/api/share/settings` in `app.py` clears the passkey itself on a mode switch (as the [Sharing Routes](#sharing-routes) section claims) is unverified — `app.py` has not been read in any pass to date.
- Nothing was removed from any earlier section.

### Version 4.16 — 2026-09-21 Ops-Tooling Doc Sync (manage.sh, setup_pymodules.sh, revoke_sharing.py)

Documentation-only pass — **no code was changed**. Compared this doc against the three scripts (no earlier copies of them were available, so this is doc-vs-code, not a diff). Behaviors were exercised where feasible (stubbed `db` for `revoke_sharing.py`; the script's own regex/sed against a seeded `requirements.txt`; a bash SIGINT-inheritance experiment; a programmatic menu/case/help numbering check) rather than only read.

- **New: [Package Management (setup_pymodules.sh)](#package-management-setup_pymodulessh)** — the script and its `constraints.txt` output were entirely undocumented. Covers invocation via `manage.sh update-modules`, the generate → dry-run → install flow, Termux `SYSTEM_MANAGED` locking, the `COMPAT_CEILING` table, the `PHASE`-based Ctrl-C rollback, and the Windows self-elevation + Defender exclusion of the whole Python directory. Note: `requirements.txt` is edited in place, **not** truncated; only `constraints.txt` is rewritten from scratch.
- **New: [manage.sh Internals & Editing Rules](#managesh-internals--editing-rules)** — the `set -e` rules behind two real silent-exit bugs, the ignore-vs-handle Ctrl-C model (experimentally confirmed), the 19-entry menu map, a "touch all of these" checklist for adding a command, `_kill_webdav_child` caveats, and the CRLF/heredoc gotchas.
- **Updated: `revoke_sharing.py`** — 3 documented subcommands → the real 9 (added `revoke-path`, `edit`, `edit-path`, `requests`, `approve`, `deny`), with flags, exit codes, and interactive-menu behavior.
- **Corrected**: manage.sh "suppresses Ctrl-C" (now a handled trap); security.txt menu number 17 → **18** (Termux 18 → **19**); `restart-webdav` on Windows is an immediate `taskkill //F`, not graceful-then-forceful; Quick Reference table (+ `manage.sh`, `setup_pymodules.sh` rows); Key Functions; dependency graph; `hypercorn` → `hypercorn[h3]`.
- **Found, deliberately not fixed** (each needs a code change and a decision from the owner):
  1. `setup_pymodules.sh` rewrites `Quart>=0.21.0,<1` → `Quart<1`, undoing the documented Quart floor fix. Suggested: `COMPAT_CEILING[Quart]=">=0.21.0,<1"`.
  2. `revoke_sharing.py edit --passkey/--generate-passkey` is a silent no-op (exit 0) without `--mode passkey`, contradicting its own help text; switching away from passkey mode doesn't pass `clear_passkey`; passkeys are generated with `random`, not `secrets`.
  3. `manage.sh`/`help` say background-mode `print()` output is discarded; the logging-unification section says `logging_setup.py` captures it. Needs a look at `logging_setup.py`.
  4. `_kill_webdav_child` hardcodes ports 8080/8443 instead of reading `config.py`.
  5. `setup_pymodules.sh` mixes bare `pip`, `python -m pip`, and bare `python`, and ignores `manage.sh`'s `PYTHON` override.
- Nothing was removed from any earlier section; two historical statements were annotated as superseded rather than deleted.

### Version 4.15 — 2026-09-15 (seventh pass) Pipe-Decode Encoding + Console-Handler Write-Size Limit

`PYTHONUTF8=1` (Version 4.14) fixed the original crash — WebDAV got much further, into request handling — but exposed two issues in the diagnostic/logging path itself:

- Relayed WebDAV output showed mojibake (`ðŸ“‹` instead of `📋`): the parent's `_pump_child_output` read the child's PIPE with `text=True` but no explicit `encoding=`, defaulting to `locale.getpreferredencoding()` (`cp1252`) on the read side even though the child now writes proper UTF-8. Fixed: `Popen(..., encoding="utf-8", errors="replace")` added explicitly.
- The crash traceback got swallowed again, this time because `logging_setup.py`'s console `StreamHandler` hit Windows' ~32KB single-write limit trying to print a long traceback to a piped (non-console) `sys.stdout`, failing with `OSError: [Errno 22]` and only reporting `--- Logging error ---`. Not fixed yet — but `DailyDatedFileHandler` (the other handler on the same logger, writing straight to the daily log file) isn't subject to this limit, so the real traceback this round should already be in `logs/prod_server_YYYY-MM-DD.log`'s `[CRITICAL] Uncaught exception` entry.
- **Not yet verified live** — pending that log excerpt.

**Confirmed live (2026-09-16)**: full clean WebDAV startup via `python prod_server.py` run directly, no crash loop — the original bug across Versions 4.10–4.15 is resolved.

### Version 4.14 — 2026-09-15 (sixth pass) Root Cause Found: UnicodeEncodeError on Non-Console Stdout

The Version 4.13 PIPE+relay diagnostic worked immediately — it surfaced the real crash: `paths.py`'s `ensure_dirs()` prints an emoji, which Windows can encode fine on a real console but which crashes with `UnicodeEncodeError` under the `cp1252` fallback encoding Python uses once stdout is a pipe/file rather than a tty. `manage.sh` never hit this because its detached launcher already sets `PYTHONUTF8=1`, masking the bug for that path only. See the [Troubleshooting follow-up entry](#-troubleshooting--edge-cases) for full detail; summary:

- `_spawn_webdav_process()` now sets `env["PYTHONUTF8"] = "1"` explicitly for the WebDAV subprocess, unconditionally — correct regardless of how the parent (`prod_server.py`/`dev_server.py`/`manage.sh`) was launched.
- Known related gap, not fixed here: the main process itself could hit the same error if its own stdout were ever redirected to a file rather than a live console — see the Troubleshooting entry for the one-line fix (`sys.stdout.reconfigure(...)`) if that ever comes up.
- This is the actual fix for the crash loop reported across Versions 4.12–4.13 — pending live confirmation from the user.

### Version 4.13 — 2026-09-15 (fifth pass) WebDAV Subprocess Output: Pipe + Relay Instead of Inherit

Version 4.12's fix (stop passing `stdout=sys.stdout`/`stderr=sys.stderr`, let `Popen` inherit fd 1/2 by default) did not resolve the crash loop, and comparing `prod_server_2026-09-15.log` against a leftover `app_2026-09-15.log` from an earlier standalone `webdav_server.py` test run made the real problem visible: the crashing child was producing **zero** output through either inheritance approach — not even a raw interpreter traceback — while the exact same script ran and printed a full startup banner when launched as a genuinely standalone process. See the [Troubleshooting follow-up entry](#-troubleshooting--edge-cases) for full detail; summary:

- Handle inheritance (both variants tried) wasn't getting the child's writes back to the parent at all on this machine, for reasons not fully identified.
- Fix: `_spawn_webdav_process()` now pipes the child's stdout/stderr (`subprocess.PIPE`) instead of inheriting them; a new `_pump_child_output()` helper reads each stream line-by-line in a daemon thread and relays it through the parent's own `print()` (`[webdav:OUT]`/`[webdav:ERR]` tags), so it flows through the existing tee into the console + shared daily log regardless of OS-level handle-inheritance behavior.
- **Not yet verified live** — this should finally surface the actual crash cause; the underlying bug (why WebDAV exits 1 as a subprocess but not standalone) is still unidentified pending that output or `webdav_server.py`'s own source.

### Version 4.12 — 2026-09-15 (fourth pass) WebDAV Popen stdout/stderr Fix (Direct-Terminal Crash Loop)

Follow-up to Version 4.11: the pre-flight port check fixed the "leftover process still on the port" case, but the same `⚠️ WebDAV process exited unexpectedly (code 1) — respawning in 3s...` symptom recurred from a second, unrelated cause — this time only when `python prod_server.py` was run directly in a terminal (not via `manage.sh`, and not reproducible with `python webdav_server.py` run standalone). See the [Troubleshooting follow-up entry](#-troubleshooting--edge-cases) for full detail; summary:

- `_spawn_webdav_process()` in `protocol_manager.py` passed `stdout=sys.stdout, stderr=sys.stderr` explicitly to `Popen`. Those names are `_TeeStream` objects by that point (`logging_setup.py`'s tee), which forward `fileno()` to the *original* real stream via `__getattr__` — reliable when the parent's real fd 1/2 are plain files (`manage.sh`'s devnull launch) or not involved (`webdav_server.py` run standalone), but not necessarily reliable when the parent is attached to a terminal emulator that doesn't back `sys.stdout` with a normal, directly-inheritable OS handle.
- Fix: stopped passing `stdout`/`stderr` to `Popen` at all — the default (inherit the parent's real fd 1/2 directly) achieves the same intent without going through the Python-level `sys.stdout`/`sys.stderr` objects.
- **Not yet verified live** — no captured traceback yet, reasoned from the code path and the reported repro pattern.

### Version 4.11 — 2026-09-15 (third pass) WebDAV Port Pre-Flight Check — Manual Cleanup Still Required Once

Follow-up to Version 4.10: that fix stopped *future* orphans but couldn't retroactively fix one that already existed, and the untrackable-PID symptom turned out to have its own separate cause. See the [Troubleshooting follow-up entry](#-troubleshooting--edge-cases) for full detail; summary:

- `.manage_pids/webdav.pid` was being overwritten on *every* spawn attempt, including doomed ones — so in a fast respawn loop it only ever pointed at the newest (already-dead) attempt, never the real occupant blocking the port. That's why the PID was "untrackable" via the pidfile.
- `protocol_manager.py` now checks (`_port_occupied()`) whether WebDAV's configured port is already listening *before* every spawn attempt (first spawn in `start_all()` included, not just watchdog respawns). If occupied, it skips the spawn entirely (pidfile left alone), prints one clear diagnostic with the real `netstat`/`lsof` + kill commands, and backs off to a 15s poll instead of a tight 3s loop.
- **Anyone hitting this now** still needs one manual, one-time step: find the real PID via `netstat -ano | findstr :8443` (Windows) or `lsof -i :8443` (POSIX) — not the pidfile — and kill it. WebDAV then comes back automatically once the port is free.

### Version 4.10 — 2026-09-15 (second pass) manage.sh WebDAV-Orphan / Duplicate-Log Fix

Same-day follow-up to the logging unification below (Version 4.9's neighbor entry, the `logging_setup.py` introduction) — a live deploy surfaced a regression it introduced. See the [Troubleshooting entry](#-troubleshooting--edge-cases) for full root-cause detail; summary:

- `manage.sh`'s `cmd_stop` never killed the WebDAV child process (tracked separately in `webdav.pid`), only the main `prod.pid`/`dev.pid`. Every `stop` left an orphaned WebDAV process holding its port, so the next `start`'s WebDAV spawn always failed to bind and exited 1 — `protocol_manager.py`'s watchdog respawned it every 3s forever, always failing the same way. New `_kill_webdav_child()` helper, called from `cmd_stop` (and therefore `cmd_restart`).
- `logging_setup.py`'s `_LOG_PREFIX` detection didn't recognize `webdav_server.py` as a valid `__main__` (it's spawned as its own OS process by `protocol_manager.py`), so every WebDAV process fell back to writing a second, undocumented `logs/app_YYYY-MM-DD.log` instead of joining the parent's `prod_server_*.log`/`dev_server_*.log` — the file the orphan above then held locked. Fixed via a new `CLOUDINATOR_LOG_PREFIX` env var, set by `protocol_manager.py`'s `_spawn_webdav_process()` from the parent's own already-resolved prefix, checked first in `logging_setup.py` before the `__main__` fallback.

Not yet confirmed against a live `start`/`stop`/`start` cycle — see the Troubleshooting entry for the fallback diagnostic step (run `webdav_server.py` directly) if the loop persists.

### Version 4.9 — 2026-09-14 SFTP Mobile-Client Disconnect Fix

Triggered by a real report: a mobile Android SFTP app ("Admin Hands") showing "connection closed"/"SSL connection closed" shortly after connecting, requiring a reconnect-and-immediately-download workaround.

- **Updated: `sftp_server.py`**
  - `_handle_connection()`'s `transport.accept(30)` raised to `transport.accept(120)` — root cause was this 30s window to open the SFTP channel after auth. Some mobile SFTP clients show "connected" immediately post-auth but don't actually open the channel until the user navigates into the file browser; if that took longer than 30s, the server tore down the transport first, which the client surfaced as a generic connection-closed error
  - Added `transport.set_keepalive(30)` right after `start_server()` — secondary fix so an idle-but-open browsing session (channel already open, no active transfer) isn't separately dropped by a mobile carrier/Wi-Fi NAT's idle timeout
  - See [SFTP Implementation Notes](#sftp-implementation-notes) for the updated detail

- Nothing was removed from any earlier section; additive only.

### Version 4.8 — 2026-09-09 WebDAV Disconnect-Flood Guard (second pass on the same download-cancel issue)

The v4.7 fixes (subprocess isolation, ALPN, `hypercorn_ssl_fix.py`) did not fully resolve the WebDAV download-cancel problem — a separate, still-live bug remained: cancelling a large download produced a genuinely fast, continuous flood of bare `SSL connection is closed` lines (no traceback) that didn't stop until the rest of the file had been uselessly iterated.

- **Updated: `webdav_server.py`**
  - New `_DisconnectAbortMiddleware` class, wrapping `WsgiToAsgi(wsgi_app)` at the ASGI level (`_start_hypercorn()`'s `asgi_app = _DisconnectAbortMiddleware(WsgiToAsgi(wsgi_app))`)
  - Root cause, verified against the actual installed source of all three layers (not guessed): (1) CPython's `asyncio/sslproto.py` never raises on a dead-connection write — by design, it just logs `'SSL connection is closed'` once past a 5-write grace threshold and silently no-ops forever after; (2) `asgiref`'s WSGI-response-streaming loop has no try/except around its send call and never checks for disconnect; (3) wsgidav just keeps yielding file chunks regardless. Nothing in the chain ever naturally stopped
  - Fix watches the ASGI `receive()` channel in the background for `http.disconnect` (confirmed Hypercorn does deliver this — `hypercorn/protocol/http_stream.py`) once the inner app's own request-body read completes (avoiding a `receive()` race), and makes `send()` raise once disconnect is observed — which propagates through asgiref's unguarded loop and stops it on the next chunk
  - Verified with isolated functional tests: a simulated cancelled download (disconnect injected at chunk 5 of 1000) stopped at chunk 6 instead of running all 1000; a normal non-disconnected request still delivered all chunks with no interference or hang
  - See [WebDAV Disconnect-Flood Guard](#webdav-disconnect-flood-guard-2026-09-09-second-pass) and the matching Troubleshooting entry

- Nothing was removed from any earlier section; additive only.

### Version 4.7 — 2026-09-09 WebDAV Resilience, Legacy-Client Fix & Hypercorn SSL-Shutdown-Timeout Patch

Triggered by a real production report: WebDAV downloads failing with "SSL connection closed" (looping on retry), and separately, cancelling a large in-flight download wedging the WebDAV listener badly enough to require restarting the whole server (main Web UI included, even though it kept working throughout).

- **Updated: `webdav_server.py`**
  - HTTPS listener's TLS ALPN changed from `["h2", "http/1.1"]` to `["http/1.1"]` only — real WebDAV clients (Windows WebClient/`mrxdav.sys`, davfs2, etc.) are almost universally HTTP/1.1-only, and negotiating h2 with one could break the connection at the protocol level. The main Web UI's listener is unaffected and still speaks h2 — browsers handle it fine
  - New `_run_standalone()` entrypoint (`if __name__ == "__main__":`) — lets this file run as its own OS process (`python webdav_server.py`), not just be imported. Handles `SIGTERM`/`SIGINT` for a graceful shutdown (exit code `0`); a genuine startup failure exits `1`; exits `0` immediately without starting anything if both `WEBDAV_ENABLED`/`WEBDAV_HTTPS_ENABLED` are off
  - Now calls `hypercorn_ssl_fix.apply()` before starting its own Hypercorn instance (see below)

- **Updated: `protocol_manager.py`**
  - WebDAV now launched via `subprocess.Popen` (`_spawn_webdav_process()`) instead of being imported and started in a thread inside this process — SFTP/FTP/SMB are unchanged, still threads
  - New watchdog thread (`_webdav_watchdog`) — respawns the WebDAV subprocess if it exits with a non-zero code (crash); a clean exit (code `0` — config-disabled, or a graceful stop) is not respawned
  - New `restart_webdav()` — force-kills and respawns the WebDAV subprocess on demand, recovering it independently of the main app (callable from in-process only — see `manage.sh`'s mechanism below for external use)
  - Writes the WebDAV subprocess's real PID to `.manage_pids/webdav.pid` (same directory `manage.sh` already uses for `prod.pid`/`dev.pid`) on every (re)spawn, cleared on graceful stop
  - `stop_all()`/`status()` updated for the new subprocess model

- **Updated: `manage.sh`**
  - New `restart-webdav` command (also menu option **8** — utility menu options 8–18 shifted to **9–19** to make room): reads `.manage_pids/webdav.pid`, signals that PID directly (graceful-then-forceful, same pattern as `cmd_stop`), and relies on the already-running server's own watchdog to notice the exit and respawn WebDAV automatically — then polls the PID file for a new PID to confirm. Can't call `protocol_manager.restart_webdav()` directly, since that function only knows about the `Popen` handle held in the *server's* memory, not in this separate, short-lived script process
  - New `webdav_pid_file()` helper alongside the existing `pid_file_for()`/`logpath_file_for()`
  - See [WebDAV Recovery](#webdav-recovery-managesh-restart-webdav) under Admin Tools & Utilities for usage

- **New file: `hypercorn_ssl_fix.py`**
  - Patches a real, still-open Hypercorn bug (verified directly against the installed 0.18.0 source, not just the bug report): `TCPServer._close()` doesn't catch `TimeoutError`, and asyncio's own default 30-second SSL-shutdown-close wait has no cap — so any abruptly-reset connection (e.g. a cancelled download) stalls its cleanup task for a full 30s and then throws an unhandled exception. See [hypercorn#202](https://github.com/pgjones/hypercorn/issues/202) (open since March 2024, unresolved; PR #342 exists but is unmerged)
  - Monkeypatches `TCPServer._close()` in-process: catches `TimeoutError` properly, and caps the close-wait at 2 seconds via `asyncio.wait_for(...)`
  - Applied via `apply()`, called once at startup in **both** `prod_server.py` and `webdav_server.py` — each runs its own independent Hypercorn instance (and, as of this version, its own OS process for WebDAV), so both need the patch
  - Defensive: logs a warning and leaves Hypercorn's original behavior in place (doesn't crash the server) if the patch can't be applied — e.g. after a future Hypercorn upgrade changes `TCPServer._close()`'s internals. Re-check after any Hypercorn upgrade; remove entirely if Hypercorn ships an official fix for #202

- **Updated: `prod_server.py`**
  - Now calls `hypercorn_ssl_fix.apply()` at import time, before `protocol_manager.start_all()` and before its own `await serve(...)` call

- Nothing was removed from any earlier section; all of the above are additive. See [WebDAV Process Isolation, Watchdog & restart-webdav](#webdav-process-isolation-watchdog-restart-webdav-2026-09-09), [WebDAV HTTPS Listener — HTTP/1.1 Only](#webdav-https-listener-http11-only-2026-09-09), and the new [WebDAV Resilience Issues](#webdav-resilience-issues-2026-09-09) Troubleshooting entries for full detail.

### Version 4.6 — 2026-08-28 Doc Sync, cont'd (video-skin-overrides.css, inline-style CSP cleanup, login.html documented)

- **New file: `static/css/video-skin-overrides.css`**
  - Externalizes two CSS rules that `index.js`'s `_injectMobileSpeedHide()` used to inject as inline `<style>` elements into the HLS player's `<video-skin>` shadow root — those were being silently dropped once the CSP's `style-src-elem` tightened to `'self'` with no `'unsafe-inline'`
  - Mobile playback-rate-button hide (`@media (max-width: 600px)`) — same behavior as before, just relocated
  - New `::cue` rule (transparent caption background, black outline + white text) — not present in any prior inline injection, so this is new caption-readability styling, not just a straight port
  - See the new [video-skin-overrides.css & the Inline-Style CSP Cleanup (2026-08-28)](#video-skin-overridescss--the-inline-style-csp-cleanup-2026-08-28) section for the full detail

- **Updated: `index.js`**
  - `_injectMobileSpeedHide()` rewritten: instead of building inline `<style>` template literals, it now `<link>`s `static/css/video-skin-overrides.css` into the shadow root (`_addLinkOnce()`, guarded by a `data-skin-overrides` attribute), polling up to 40× at 100ms intervals for the `<video-skin>` shadow root to exist before attaching
  - This revises [Version 4.5](#version-45--2026-08-28-doc-sync-sftp-hardening-ftps-webdav-http-off-by-default)'s "reviewed, no behavioral change" verdict for `index.js` — that earlier pass evidently missed this CSP-driven refactor

- **Updated: `app.py`**
  - The `_INLINE_STYLE_ELEMENT_HASHES` CSP comment block now explains that `_injectMobileSpeedHide()`'s inline style moved to the new external stylesheet above, and that `_initImageZoom()`'s inline style was separately converted to a fixed rule in `index.css` — so the two hashes still listed there belong only to the vendored video.js/media-chrome bundle's own shadow-DOM style injections, not this project's own code
  - Same revision note as `index.js` above: this is a real change, not just a documentation gap

- **Documented for the first time: `templates/login.html`**
  - Markup was never written up before (only `login.js`'s function names were listed in Quick Reference) — added under [Login Flow](#login-flow) in the Authentication & Sessions section: hidden `csrf_token` field, flashed-message rendering, `noindex, nofollow` robots meta, SRI-hashed `login.js` script tag
  - No functional gap found versus what `app.py`'s `login()` route and the existing CSRF Protection section already describe

- **Re-reviewed, no further changes found: `pdfjs-worker-init.mjs`, `index.css`** — both still match [Embedded PDF.js Viewer (2026-08-23)](#embedded-pdfjs-viewer-2026-08-23) and the existing `body::before`/`::after` layering documentation. The `pdfjs-viewer-overlay.css` regression flagged in Version 4.5 was not part of this pass's uploaded files and remains unfixed/undocumented-as-fixed.

- Nothing was removed from any earlier section; all of the above are additive.

### Version 4.5 — 2026-08-28 Doc Sync (SFTP hardening, FTPS, WebDAV HTTP off by default)

- **Updated: `sftp_server.py`**
  - New `_harden_transport_ciphers()`, called on every accepted connection before `transport.start_server()` — strips weak ciphers (CBC-mode, 3DES, arcfour/RC4), weak MACs (MD5-based, truncated/full SHA1), and DHE key-exchange algorithms (D(HE)ater DoS mitigation) from the offered lists, in place, via `get_security_options()`
  - Addresses OpenVAS's "Weak Encryption Algorithm(s) Supported (SSH)" / "Weak MAC Algorithm(s) Supported (SSH)" findings — no client this server targets needs the dropped algorithms
  - See [SFTP Implementation Notes](#sftp-implementation-notes) for the full breakdown

- **Updated: `config.py`**
  - `WEBDAV_ENABLED` (plaintext HTTP WebDAV) now defaults to `False`, closing off the same class of "cleartext credentials" finding [Version 4.2](#version-42-2026-08-18) fixed elsewhere in the stack; still available as a manual fallback if HTTPS can't be set up
  - New `FTP_TLS_ENABLED` / `FTP_TLS_REQUIRE_DATA` variables add FTPS (explicit `AUTH TLS`) support to `ftp_server.py`, reusing the WebDAV HTTPS cert; gated on `pyOpenSSL` with an automatic plaintext fallback if it's missing
  - New FTP sub-menu options (3, 4) in `python config.py` → option 13 to toggle the two settings above

- **Updated: `ssl_cert.py`**
  - Module docstring gained macOS (`security add-trusted-cert`) and Linux/`davfs2` (`update-ca-certificates`) one-time trust-import instructions alongside the existing Windows steps — documentation-only change, no behavior difference

- **Reviewed, no behavioral change: `app.py`, `index.js`, `index.html`, `index.css`** — re-checked against the [Route Path Corrections](#-route-path-corrections--new-endpoints-2026-08-23) table and the [Embedded PDF.js Viewer](#-embedded-pdfjs-viewer-2026-08-23) section; both still accurate

- **Regression found, not fixed here: `pdfjs-viewer-overlay.css`** — its `body` rule now sets `background-color: #1e3c72`, directly contradicting the file's own adjacent comment that this property is "left unset on purpose." See the callout in [Embedded PDF.js Viewer](#-embedded-pdfjs-viewer-2026-08-23) for detail and a suggested fix.

### Version 4.4 — 2026-08-23 Doc Sync (embedded PDF.js viewer & 404.css tweak)

- No code changes — another documentation-only pass, this time against `index.html`, `index.js`, `pdfjs-worker-init.mjs`, `pdfjs-viewer-overlay.css`, `404.css`, and `app.py`'s CSP/Integrity-Policy comments.
- Added [Embedded PDF.js Viewer (2026-08-23)](#embedded-pdfjs-viewer-2026-08-23): the old `/pdfviewer` route no longer exists in `app.py` at all — PDF preview now uses the official pdf.js viewer merged directly into `index.html` (rooted at `#pdfjsViewerRoot`, avoids the app's `frame-src 'none'` CSP entirely by never using an iframe). Covers the two new static files (`pdfjs-worker-init.mjs`, `pdfjs-viewer-overlay.css`), the `webviewerloaded`/`AppOptions` integration hook, and the `index.js` open/close wiring (`_pdfjsReady()`, `_pdfViewerPrevTitle`, the `setTitle` no-op stub).
- Noted the removed `/pdfviewer` row directly under the existing Route Path Corrections table.
- Added a new row to Quick Reference's "Most Important Files" table for both new static files.
- Documented an additional, unrelated `404.css` tweak found in the same pass: a `@media (max-height: 700px)` block that shrinks the 404 card's spacing on short viewports.
- Nothing was removed from any earlier section; all of the above are additive.

### Version 4.3+ — 2026-08-23 Doc Sync (route paths & undocumented endpoints)

- No code changes — this is a documentation-only pass reconciling this file with the current `app.py`/`index.js`.
- Added [Route Path Corrections & New Endpoints (2026-08-23)](#route-path-corrections--new-endpoints-2026-08-23) covering: `/mkdir`, `/rename`, `/delete`, `/bulk_copy`, `/bulk_delete`, `/bulk_move` losing their old `/api/*` names (and singular `/api/move` and `/api/copy` never having existed); the HLS routes moving to `/hls_start`, `/hls_status`, `/hls_files/...`; `/image_proxy` → `/image_preview`; and a batch of endpoints that existed in code but were never written up at all (`/api/check_conflicts`, `/api/exists`, `/api/storage_stats`, `/api/storage_stats_slow`, `/api/assembly_status[/​<file_id>]`, `/api/protect_assembly/<file_id>`, `/api/files/<path>`, `/image_preview_status/<cache_key>`, `/image_info/<path>`, `/admin/clear_media_preview`, `/csrf-token`, `/robots.txt`, `/.well-known/security.txt`, `/sitemap.xml`, `/debug/headers`, and the CORS preflight handler).
- Corrected the `/api/health_check` response shape (no longer returns `version`/`database`/`file_monitor`/`search_index`; now returns `platform`, `has_statvfs`, `root_dir`, `timestamp`).
- Expanded the `static/js/index.js` function list under Quick Reference — the original four-function list was accurate but far from complete; added the conflict-resolution, folder-upload-grouping, image-zoom, HLS-preview, deep-search, and move/copy-modal function clusters.
- Nothing was removed from the original tables/sections; corrections are additive call-outs placed next to (or just after) the content they update.

### Version 4.3 — manage.sh security-txt Command

- **Updated: `manage.sh`**
  - New `security-txt` subcommand manages `static/.well-known/security.txt` (RFC 9116) — direct flags (`--contact`, `--expires`/`--expires-in-days`, `--preferred-lang`, `--canonical`), an interactive prompt when run with no args, and a `show` subcommand
  - Implemented as a bash function (`cmd_security_txt` + helpers) wrapping an inline Python heredoc for parsing/formatting, the same pattern already used by `_launch_detached()` elsewhere in the file — no new standalone `.py` script added
  - Partial updates: only the fields passed as flags change; existing fields (including any custom ones beyond the four RFC 9116 fields this command manages) are read from the file first and preserved
  - `--expires` accepts `YYYY-MM-DD`, a datetime missing milliseconds/`Z`, or the full `YYYY-MM-DDTHH:MM:SS.sssZ` — all normalized to the exact latter format; date-only defaults to `23:00:00.000Z` that day
  - Added as menu option 17 in `cmd_menu`; the Termux-only setup option shifted from 17 → 18
  - See its own subsection under Admin Tools & Utilities for full usage

### Version 4.2 (2026-08-18)

#### ZAP Security Scan Fixes

- **`app.py`**: `_lean_redirect()` helper added and used in `validate_session`'s two 301 redirects, fixing a ZAP "Big Redirect Detected" false-positive caused by Quart's default `redirect()` HTML fallback body
- **`app.py`**: `index()` (the login-gated catch-all route) now returns an early 404 for any `/static/*`-shaped path that didn't match the real `/static/<filename>` route, closing off a ZAP "Path Traversal" false-positive (confirmed not a real traversal risk — `index()` already runs `storage.is_safe_path()`/`is_valid_path()` before touching disk)
- No app-side fix needed for the Medium/Low findings on `static.cloudflareinsights.com`, `edgeupdates.microsoft.com`, or the stale `/robots.txt`/`/sitemap.xml` headers — all third-party or a Cloudflare edge-cache staleness issue, not an app bug (cache purge + "Always Use HTTPS" are Cloudflare-dashboard-side fixes)

#### 404 Page Fix

- **`404.html`**: corrected the stale SRI `integrity` hash on the `404.js` `<script>` tag, which was silently blocking the script (and both the "Go Back" button and the 10-second auto-redirect) under the site's `script-src 'self'` CSP
- **`404.html` / `404.js`**: "Go Back" button subsequently removed entirely (design decision) — `history.back()` was a no-op for direct-link visitors anyway; "Go Home" already covers that case

### Version 4.1 — Tailscale Certificates

- **Updated: `prod_server.py`**
  - Tries `tailscale cert` first for a real trusted certificate on the device's `*.ts.net` MagicDNS name, with a 12-hour background renewal loop for the life of the server
  - Falls back to `ssl_cert.py`'s self-signed certificate automatically if Tailscale isn't installed/logged in/enabled — no configuration needed either way
  - `webdav_server.py`'s own HTTPS listener is unaffected — it still uses `ssl_cert.py` directly

### Version 4.0 — Flask/Waitress → Quart/Hypercorn (ASGI) Migration

This is the largest architectural change in the project's history: every HTTP-speaking component moved from WSGI (Flask + Waitress) to ASGI (Quart + Hypercorn), adding native HTTP/2 and HTTP/3 support.

- **Updated: `app.py`, `auth.py`, `realtime_stats.py`, `realtime_shares.py`, `dev_server.py`, `prod_server.py`, `requirements.txt`**
  - Every route handler and `before_request`/`after_request` hook converted to `async def`; `render_template`/`render_template_string`/`make_response`/`flash`/`send_file`/`send_from_directory`/`request.form`/`.files`/`.get_json` are all coroutines in Quart and are now awaited throughout
  - `validate_session` (the session-check `before_request` hook) was the one hold-out sync function missed by two earlier conversion passes — found via an AST sweep for sync functions under route-like decorators, then fixed; a second AST sweep afterward confirmed zero remaining
  - `send_file`/`send_from_directory` kwarg mismatch fixed: Quart kept Flask's *older* names (`attachment_filename`, `cache_timeout`) rather than modern Flask's (`download_name`, `max_age`) — 10 call sites were silently 500ing (see Troubleshooting) until fixed
  - `quart-wtf` (only release: hard-pins `quart<0.19` → `werkzeug~=2.3`, incompatible with the rest of the stack) replaced with a small hand-rolled, session-tied `CSRFProtect` in `app.py`, plus a `/csrf-token` endpoint and a frontend auto-refresh-and-retry-once wrapper
  - `quart-cors`'s `allow_origin` can't express regex-based origin matching either — replaced with a manual `after_request` CORS hook
  - Blocking-call audit (Hypercorn's single event loop means one blocking call freezes the app for *every* concurrent user, unlike Waitress's thread-per-request model): `image_preview`'s `Event.wait(timeout=60)`/`t.join(timeout=60)`, `archive_preview`/`office_preview`'s synchronous conversion bodies, 3 `storage.list_dir()` call sites, `bcrypt.checkpw`/`hashpw` on login and share-passkey verify/creation, and `clear_media_preview`'s cache walk — all wrapped in `asyncio.to_thread` (verified Quart's context-locals propagate correctly into `to_thread` workers via contextvars first)
  - `Config.keep_alive_max_requests=0` does **not** mean unlimited in Hypercorn — h2 closes the connection once `keep_alive_requests > max`, silently GOAWAY-ing every HTTP/2 connection after its first request; left at Hypercorn's own default (1000) instead
  - Hypercorn's default `errorlog="-"` crashes on Python 3.14 (a `%(process)d` formatter hitting a `None` `record.process`, a stdlib logging-module behavior change) — fixed by passing a pre-built `logging.Logger` via `Config.errorlog` in both `prod_server.py` and `webdav_server.py`
  - `requirements.txt` pins `Quart>=0.21.0,<1` (a bare `Quart<1` can resolve a pre-0.19 release that still imports `werkzeug.urls.url_quote`, removed in modern Werkzeug — hit in the user's actual Windows/Python 3.14 production deploy)
  - `prod_server.py`'s custom Ctrl+C signal handler now falls back to `signal.signal()` when `loop.add_signal_handler()` raises `NotImplementedError` (Windows' `ProactorEventLoop` never implements it) — mirrors the fallback Hypercorn's own internal code already uses
  - The independently-built CSRF hotfix (`/csrf-token` endpoint, fetch-wrapper auto-refresh-and-retry, and a fix for `/bulk-download`'s real `<form>.submit()` POST bypassing the fetch wrapper) was ported into the migrated `app.py` — `index.js` needed no changes

- **Updated: `database.py`**
  - Two real, pre-existing (not migration-caused) thread-safety bugs found and fixed during verification: `_bootstrapped` was set before schema creation actually ran (fixed with double-checked locking), and even after that, `_do_bootstrap()` never called `conn.commit()`, so a different thread's connection could see zero rows under WAL-mode snapshot isolation despite bootstrap having "completed" — fixed by committing before releasing the bootstrap lock. This was the actual root cause of a 100%-reproducible fresh-startup login failure

- **Rewritten: `webdav_server.py`**
  - `wsgidav` is WSGI-only; rather than keep a separate waitress/cheroot stack just for WebDAV, it's now bridged onto Hypercorn via `asgiref.WsgiToAsgi`, serving both HTTP and HTTPS from one Hypercorn Config/thread (`bind=` for TLS, `insecure_bind=` for plain HTTP — same pattern `prod_server.py` uses)
  - `requirements.txt` drops `waitress` and the explicit `cheroot` pin (cheroot still arrives transitively via wsgidav); adds `asgiref`
  - Known caveat: `WsgiToAsgi` doesn't implement ASGI lifespan, so Hypercorn logs a harmless "continuing without Lifespan support" warning on WebDAV startup
  - `sftp_server.py`, `ftp_server.py`, `smb_server.py`, `smb_setup.py`, `protocol_manager.py` needed **no** changes — all thread-based, only touching `app.py` via the sync `get_local_ip()` helper

- **Unchanged**: `index.js` (pure frontend, no Flask/Quart-specific code) beyond what the independent CSRF hotfix already required

### Version 3.5 — Share Links

Public, opaque-token share links per file/folder, with a "Manage Shared" admin panel.

- **New routes in `app.py`**: `/api/share`, `/api/share/settings`, `/api/unshare`, `/api/share/status`, `/api/share/bulk`, `/shared/<token>` (+ `/passkey`, `/request`, `/status`, `/download`, `/browse`, `/download-item/<subpath>`, `/zip`), `/admin/shares*`, `/admin/revoke_all_shares*` — see [Sharing Routes](#sharing-routes) for the full table
- **New tables in `database.py`**: `share_links` (token, path, security_mode, passkey_hash, expires_at, download_count) and `share_access_requests` (approval-mode requests, access_token cookie, max/used downloads)
- **New file: `revoke_sharing.py`** — CLI + interactive menu for listing/revoking share tokens independent of the web UI; wired into `manage.sh`
- **New file: `realtime_shares.py`** — SSE for the Manage Shared panel's pending-request badge and active-shares-changed nudges, mirroring `realtime_stats.py`'s pattern
- **Frontend**: share button in the file-table action column, share modal (protection level, expiry, copy link), bulk share/unshare in the bulk-actions bar, Manage Shared panel (Active Shares / Pending Requests / Revoke All with a fresh-random-10-digit-code confirmation), `shared.html`/`shared.js`/`shared.css` for the public landing page including an in-page folder browser for shared folders
- **Security fix during rollout**: the two anonymous share routes (`/shared/<token>/passkey`, `/shared/<token>/request`) needed explicit `@csrf.exempt` — the app-wide `CSRFProtect` was 400ing every anonymous visitor POST before it reached the database, which looked like "pending requests aren't being received" until traced

### Version 3.4 (2026-07-28)

- Web UI logout now goes through a client-side entrypoint that still calls the server-side `/logout` handler for session cleanup and cookie invalidation
- Real-time storage stats moved to the authenticated SSE endpoint `/api/storage_stats_stream`, with `/api/storage_stats_poll` as a fallback
- `manage.sh` now suppresses Ctrl-C while a nested utility script runs, so the shell wrapper stays in control instead of exiting prematurely *(superseded 2026-09-21: now a handled trap, not an ignore — see [manage.sh Internals & Editing Rules](#managesh-internals--editing-rules))*
- Additional SMB Windows-specific save/delete compatibility fixes for Office-style file writes and transient lock handling

### Version 3.3 (2026-07-10)

#### SMB Protocol Server

- **New file: `smb_server.py`**
  - `impacket.smbserver.SimpleSMBServer` — the only practical pure-Python SMB server library (confirmed: `smbprotocol`/`pysmb` are client-only)
  - NTLM auth via NT hashes captured at password-set time (`database.py`'s new `nt_hash` column) — plaintext never crosses the wire, so `db.check_login()` can't be used the way other protocols use it
  - Per-user read/write via a Tree Connect hook overriding `connData['ConnectedShares'][tid]["read only"]` per connection, since impacket only supports one static flag per share
  - Diffed credential refresh (not clear-and-rebuild) every 30s, with stable per-user UIDs and lowercase-normalized comparisons matching impacket's own internal key storage
  - `block_on_close=False` / `daemon_threads=True`, set before accepting connections — fixes `stop()` hanging forever on an abandoned connection
  - `_quiet_handle_error` suppresses impacket's normal 5-minute idle-timeout traceback
  - Three layered Windows file-locking fixes for MS Office's atomic save colliding with `WinError 32`: retry-via-`os.replace()` for rename, backoff retry for delete, and a `FILE_SHARE_DELETE`-aware `os.open()` replacement (via stdlib `_winapi`/`msvcrt`, following CPython's own `bpo-15244` recipe, with a gap in that recipe found and fixed)
  - Command safety net wrapping every SMB2 command — impacket's own dispatch loop re-raises uncaught exceptions, silently dropping the connection; the wrapper turns that into a logged error with the client receiving a clean response instead
  - Opt-in diagnostics: `SMB_DEBUG_SIGNING=1` (Windows 11 24H2 signing investigation), `SMB_DEBUG_FILES=1` (file lifecycle logging)

- **New file: `smb_setup.py`**
  - Standalone, human-run, one-time tool — never auto-invoked by the servers
  - Windows: confirm → elevate → stop `LanmanServer` → instructs a restart, never executes one
  - Linux: `setcap cap_net_bind_service=+ep`, immediate, no restart
  - Android: root check only — points rooted users at `su -c`/`tsu` rather than `setcap` (unreliable on Android's SELinux); non-rooted falls back to 8445 automatically

- **New file: `lanman_guard.py`**
  - Small, passive state-tracking library shared between `smb_setup.py` (writer) and `smb_server.py` (reader) — no watchdog, no auto-restore; replaced an earlier, more complex design once "this needs a machine restart" made clear it was never a per-session concern

- **New file: `kick_sessions.py`**
  - Standalone access-revocation tool (interactive menu + CLI) for security incidents: rotate a password, delete a user, kick everyone, or instantly log out the web UI (`logout-web` — genuinely instant, since a session cookie is a separate secret from the password, unlike every other protocol here)

- **Updated: `database.py`**
  - New `nt_hash` column (nullable, migrated in automatically) for SMB/NTLM auth
  - `add_user()`/`update_password()` now also compute and store the NT hash
  - New `get_smb_credentials()` and `users_missing_nt_hash()` methods

- **Updated: `config.py`**
  - New variables: `SMB_ENABLED` (defaults `False`, unlike the other three protocols — installing `impacket` alone isn't enough to be useful without the one-time setup), `SMB_PORT`, `SMB_FALLBACK_PORT`, `SMB_SHARE_NAME`
  - New SMB sub-menu under protocol server configuration (option 13)

- **Updated: `protocol_manager.py`, `prod_server.py`, `dev_server.py`**
  - SMB wired in alongside the other three protocols
  - Also closed a pre-existing gap: `protocol_manager.stop_all()` was never actually being called on graceful shutdown for any of the four protocols — now is

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
  - **Later fix**: chroot path mapping rewritten from a single `os.path.join(root, sftp_path)` call to a segment-by-segment resolver — the original silently clamped every subfolder lookup back to root on Windows only, due to `ntpath.join`'s absolute-path-reset behavior on a drive-less absolute path (which is exactly the shape of every incoming SFTP path). See SFTP Implementation Notes above.

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

**Last Updated**: 2026-10-02  
**For Questions**: Refer to source code comments marked with `###` or `# --`