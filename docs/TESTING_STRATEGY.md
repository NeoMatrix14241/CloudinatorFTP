# CloudinatorFTP Testing Strategy

> **Status: tracked in git for now.** It becomes `.gitignored` (a local planning document) only after ALL the phases below are 100% implemented; see `CLAUDE.md` READ HERE FIRST and `CODING_GUIDELINES.md` section 18. Until then update it with every testing change; after that do not link to it from a committed document. The facts it holds are repeated in `CLAUDE.md` and `CODING_GUIDELINES.md`.

**Status (2026-10-29, Version 5.40):** Phases 0, 1 and 2 are DONE. Phase 3 is DONE except that Ruff is report-only until its findings are triaged. Phase 4: the protocol tests are done and in the pull-request tier; `nightly.yml` and the fault / concurrency / restart, live-worker, performance and browser tests are WRITTEN (5.40) but have not run on the real application or on GitHub yet. Phase 5: required checks and CODEOWNERS are done; the coverage floor waits for the first Linux total. Section 14 has the detail.
**It is committed with every testing change (see the banner above).** The permanent record is `CLAUDE.md` (sync notes) and `CODING_GUIDELINES.md`.
**Scope:** Quart HTTP routes, SQLite behavior, storage and file index, upload pipeline, version history, sharing, FTP/SFTP/WebDAV, the front-end contracts that break silently (SRI, CSP), and the `manage.sh` Quality Assurance section.
**Read with:** [CLAUDE.md](CLAUDE.md) (history, rules) and [CODING_GUIDELINES.md](CODING_GUIDELINES.md) (how to change things).

No test suite can guarantee that every defect is caught; the goal is layered, repeatable evidence that changes keep the application's contracts.

## 0. What changed since the first draft (read this first)

The first draft proposed an in-process Quart test client. Reading the code (Phase 0) and then building Phase 1 showed that cannot work, so the design below differs from the draft in these ways:

| Draft said | What exists |
|---|---|
| App imported in-process, Quart test client, `pytest-asyncio`, session-scoped app | The app is **never** imported in the pytest process. `tests/conftest.py` copies the source tree to a temp folder and runs `dev_server.py` there as a **subprocess** on an ephemeral port; tests talk to it over HTTP with a standard-library, cookie-aware `HttpClient`. No `pytest-asyncio`, no `httpx` |
| `pytest.ini` | `pyproject.toml` (`[tool.pytest.ini_options]`, the owner's choice). A leftover `pytest.ini` would silently win, so there must be none |
| `requirements-dev.txt` with many tools | `pytest>=9.1.1`, `pytest-timeout>=2.4`, `pip-audit>=2.10.1`, `coverage>=7.17.0`, `hypothesis>=6.170` and `ruff==0.17.3` (pinned exactly; 5.40). `mutmut` was dropped (it rewrites functions into trampolines the `ast`-based unit tests cannot read; `tests/mutation_trial.py` replaces it) and `playwright` is installed by the nightly job only |
| `qa.py` modes `static / quick / layer / coverage / mutation / ci / full` | `static`, `tests`, `quick`, `layer <name>`, `ci`, `audit` (5.32), `coverage` (5.34), plus `--version`, `--skip-packages`, `--out DIR`, `--fail-fast`. Steps: `smoke`, `check`, `sri`, `js-syntax`, `layout`, `pytest`. `mutation`, `full` do not exist |
| `manage.sh` QA entries 21-26 (with coverage and mutation) | 21-25: `qa quick`, `qa static`, `qa tests`, `qa layer`, `qa ci`; 26-29 are the separate Developer Tools section (`dir-tree`, `smoke --save`, `qa audit` (5.32), `qa coverage` (5.34)). The menu has 29 entries |
| CI: Python 3.12, only pyflakes, SRI "not yet in CI" | `tests.yml` uses Python **3.14.7** and `@v7` actions; job `smoke + check` and job `behavioral tests` (`needs` the first; both jobs are required checks through the rulesets; runs `python tests/qa.py ci`, uploads `artifacts/`). SRI and `node --check` run inside `qa.py` (so in CI through `qa ci`), not as separate steps of the static job |
| `tests/integration/`, `protocols/`, `property/`, `reliability/`, `frontend/` | `tests/unit/`, `application/`, `protocols/` (5.26-5.31), `property/`, `reliability/`, `frontend/` (5.40) and `performance/` exist; `tests/integration/` does not (that approach lives in `tests/application/`, see section 6) |
| Version history, index and shares tested through the app | The scratch config sets `VERSION_ENGINE_ENABLED: false` (and every protocol off). Share tests work through HTTP; version history and the file index are tested by running the REAL modules inside a scratch copy (`run_in_scratch`, no server), see section 6. The HTTP routes `/api/versions/*` still need a scratch server with the engine on (Proposed) |

Two techniques that are NOT in the draft but are now the standing practice:

1. **ast extraction.** Modules that cannot be imported (`core.py`, `routes/*.py`, anything that starts threads) are tested by cutting the functions out of the source file with `ast` and running them in a small namespace with fakes (a fake `request`, `session`, `db`, a temporary SQLite file or folder). Used by `tests/unit/test_client_ip_trust.py`, `test_upload_chunk_keys.py`, `test_session_revocation.py`, `test_recover_uploads.py`. Each such test file asserts that the function still exists, so a rename fails loudly instead of skipping.
2. **Strict xfail for a known bug or limitation**, with a one-line reason that names the CLAUDE.md part. When the fix lands the test XPASSes and **fails the run on purpose** until the marker is removed; that is how the tests prove a fix and how nobody forgets to delete the marker. Remove the marker in the same change that fixes the bug.

## 1. Goals

- Verify observable behavior (bytes on disk, rows in SQLite, HTTP responses, session state), not only syntax or source patterns.
- Protect authentication, authorization, storage boundaries, uploads, sharing and version history.
- Test recovery from invalid input, partial operations and stale or corrupt metadata.
- Never read or modify production data (`db/`, `cache/`, `versions/`, the real storage root, the real config files).
- Keep the pull-request suite fast; move slow or platform-sensitive work to an opt-in or nightly tier.
- One command runs the same checks locally, from `manage.sh`, and in GitHub Actions.
- Keep a regression test for every fixed defect. Treat coverage and mutation scores as signals, not proof.

## 2. Existing checks

| Check | Purpose | Status |
|---|---|---|
| `python tests/smoke.py` | Whole-project static wiring: syntax, pyflakes, endpoints, hooks, import cycles and layering, route registration, tool launch paths, `bash -n manage.sh`, route snapshot (`tests/smoke_routes.json`, written by `smoke --save`) | Exists |
| `python tests/check.py` | Per-module syntax, pyflakes, import resolution, helper layering | Exists |
| `tools/sri_validator.py` (`./manage.sh validate-sri`) | Stale or missing `integrity` hashes in templates; exits 1 | Exists; runs as the `sri` step of `qa.py` |
| `node --check` on `static/js` | JavaScript syntax | Exists; `js-syntax` step of `qa.py` (SKIP when Node.js is missing) |
| `tests/dir_tree.py` (`./manage.sh dir-tree`) | Writes `docs/DIRECTORY_TREE.md`; `artifacts` and other generated folders are excluded | Exists |
| `.github/workflows/tests.yml` | Jobs `smoke + check` and `behavioral tests` on push and PR to `main` and `dev` | Exists (owner maintains it; never re-deliver it from an old copy) |
| `.github/workflows/codeql.yml` + `tests/codeql_sarif_parser.py` | CodeQL for Python and JavaScript, SARIF to CSV | Exists |
| pytest unit + application suites | Behavior | Exists, see section 6 |
| Coverage, property, reliability, protocol, mutation, browser smoke | Extra failure modes | Proposed |

The static checks stay the first gate. Pytest does not repeat structural rules that `smoke.py` already enforces.

## 3. Tiers: what runs when

| Tier | Trigger | Contents | Status |
|---|---|---|---|
| **PR** | push / pull request to `main` and `dev` | `smoke`, `check`, then `qa.py ci` = smoke, check, sri, js-syntax, layout, every existing pytest layer (unit, application, protocols, property) with the opt-in tiers skipped, JUnit XML | Exists; `smoke + check` and `behavioral tests` are required checks (rulesets) |
| **Opt-in** | `CLOUDINATOR_SLOW_TESTS=1` | `tests/performance/` (the 85 s throttled download, speed baselines), `tests/reliability/` (the live Version Engine worker, concurrency, stop / crash / restart), `tests/frontend/` (Playwright smoke) | Exists; skipped by default (the 5.40 files are written but not yet run on the real application) |
| **Nightly** | `schedule` (default branch) + manual (any branch) | `nightly.yml`: `qa.py ci` with both opt-in switches on (`CLOUDINATOR_SLOW_TESTS=1`, `CLOUDINATOR_NIGHTLY=1`: Hypothesis with random inputs) on Linux AND Windows; Chromium on Linux. Manual: `mutation.yml` (mutation trial) | Written (5.40), not yet run on GitHub |
| **Never in CI** | n/a | SMB on port 445, Cloudflare Tunnel, real disk-full, anything touching production paths | n/a |

## 4. Layout (what exists)

```text
CloudinatorFTP/
├── pyproject.toml            # pytest, coverage and ruff config ONLY (no [project]); there must be no pytest.ini
├── requirements-dev.txt      # pytest, pytest-timeout, pip-audit, coverage, hypothesis, ruff==pinned (never merged into requirements.txt / setup_pymodules.sh)
├── .github/                  # workflows: tests.yml, codeql.yml, audit.yml, coverage.yml, lint.yml, nightly.yml, mutation.yml; dependabot.yml; CODEOWNERS
└── tests/
    ├── smoke.py  check.py  qa.py  dir_tree.py  codeql_sarif_parser.py  smoke_routes.json  mutation_trial.py
    ├── conftest.py           # scratch copy, scratch servers (plain and with the Version Engine), start / stop helpers, HttpClient, test users, safety guards
    ├── unit/                 # pure helpers, qa.py, manage.sh QA section, harness itself, ast-extracted app logic (assemble_chunks, file_monitor handler and cache)
    ├── application/          # real app over HTTP: boot, login, authorization, containment, uploads, shares, version routes
    ├── protocols/            # FTP, FTPS, SFTP, WebDAV, SMB against isolated local instances
    ├── property/             # Hypothesis (deterministic in the required check)
    ├── reliability/          # opt-in: live Version Engine worker, concurrency, stop / crash / restart
    ├── performance/          # opt-in: slow download, speed baselines
    └── frontend/             # opt-in: Playwright smoke
```

Rules: `tests/conftest.py` and `tests/qa.py` sit directly in `tests/`; any `tests/test_*.py` directly in `tests/` makes `qa.py` FAIL with the `layout` step (it used to hide as a SKIP). Test file basenames are unique across folders; test modules cannot import `conftest`, so shared constants are repeated locally or provided as fixtures.

## 5. How the application is tested (the decision, as built)

Facts that shaped it (from CLAUDE.md / the code): `core.py` starts threads at import (file monitor, search crawler), `app.py` starts the cleanup schedulers and the assembly worker, `paths.py` reads `storage_config.json` and `config.py` reads `server_config.json` next to the code, `RateLimiter` / `ChunkTracker` / `AssemblyQueue` are module-level singletons, CSRF is global.

**Decision: scratch copy + subprocess.** The `scratch_server` fixture (session scope):

1. copies root `*.py`, `helpers/`, `routes/`, `templates/` and a trimmed `static/` into a temp folder (never `db/`, `cache/`, `versions/`, `logs/`, `docs/`, `tests/`, the vendored pdf.js and fonts, or the real config files);
2. writes fresh `storage_config.json` (every path inside the temp folder) and `server_config.json` (`HOST` 127.0.0.1, an ephemeral `PORT`, search index, ffmpeg, libvips, WebDAV, SFTP, FTP, SMB and the **version engine** all disabled);
3. asks the COPY's own `paths.get_all_paths()` (in a subprocess) where it would keep data and refuses to start anything if a path is outside the folder (`paths_outside`);
4. creates the synthetic accounts `qa_writer` (readwrite) and `qa_reader` (readonly) in the SCRATCH database, then starts `dev_server.py` (`CLOUDINATOR_BG=1`, `CLOUDINATOR_FTP_ROOT` = scratch storage) and stops it through `.manage_pids/dev.stop`, the same graceful request `manage.sh` uses.

An autouse guard fails any test run in which a root module other than `paths` was imported in-process from the real tree. Every client sends its own fake `CF-Connecting-IP`, so each test has its own login rate-limit bucket; this works because the tests reach the server from loopback, the only peer whose proxy headers the app trusts (5.16).

Helpers a test can use: `server.client()` (anonymous, own IP), `server.login_as(user)`, `server.make_user(role)`, `server.db(code, *args)` (runs Python inside the scratch copy with `database.db` in scope; this is also the way to seed or inspect rows), `server.storage` (the scratch storage folder), `HttpClient.api()` (CSRF header + `Accept: application/json`, the way the front end calls), `request(..., files=...)` for multipart, `cookie_header()` to replay a cookie.

Fallback if this ever proves too brittle (not needed so far): an environment override for the db/cache/storage roots and a switch that skips background threads; a code change, not test work.

## 6. Layers and what covers them today

**Layer 1 - static:** `smoke.py`, `check.py`, `sri`, `js-syntax`, CodeQL. Exists.

**Layer 2 - unit (`tests/unit/`):** paths, scratch-copy harness, `qa.py`, `setup_pymodules.sh` functions, the `manage.sh` QA and Developer Tools sections, the HTTP client, the `RESPONSE_TIMEOUT` setting, and the ast-extracted app logic (client-IP trust, upload chunk keys and `chunks_complete`, session revocation, startup recovery of uploads). Exists.

**Layer 3 - integration:** the real module in a scratch copy, no server. Built as `tests/application/test_version_restore.py` (version_history + version_engine) and `tests/application/test_file_index_recovery.py` (file_index): each builds its own scratch copy with `scratch_tools.build`, runs a snippet with `scratch_tools.run_in_scratch`, the snippet prints `RESULT=<json>`, and every snippet first asserts its folders are inside the copy. They sit in `tests/application/` (marker `application`) rather than in a new `tests/integration/` folder so no new marker or layer is needed. `database.py` and `storage.py` could get the same treatment; today `server.db()` snippets and the ast-extraction unit tests cover part of them.

**Layer 4A - application (`tests/application/`):** boot, login / CSRF / lockout / sessions, authorization sweep (every declared route refuses an anonymous caller; one test per mutating route for a readonly account), path containment (about 130 cases), upload integrity, share links (public, passkey, approval, expiry, folder confinement, revoke-all). Exists.

**Layer 4B - protocols (`tests/protocols/`):** FTP/FTPS, SFTP, WebDAV and SMB against isolated local instances (5.26-5.31). Exists, in the pull-request tier (about 1 minute because of the bcrypt logins).

**Layer 5 - extras:** Hypothesis for path strings and chunk keys (`tests/property/`, 5.40, done), the `storage_index.json` loader fuzz (done), fault injection and bounded concurrency (`tests/reliability/`, written, opt-in), performance baselines (`tests/performance/test_baselines.py`, written, opt-in), a Playwright smoke that fails on script errors, failed requests and SRI mismatches (`tests/frontend/`, written, opt-in), coverage.py (done, 5.34), a mutation trial (`tests/mutation_trial.py`, done, manual). Still Proposed: node + jsdom suites for `index.js`.

## 7. Fixtures and isolation rules

Rules (all enforced or followed today):

1. **Safety guard:** the run aborts if a resolved db, cache, versions or storage path is not inside the scratch folder; a unit test also checks the real config files were not touched.
2. Tests never use the repository's config files, production credentials, tokens or user files; all data is synthetic.
3. No internet, tunnel or already-running service; ephemeral local ports only.
4. Tests are order-independent and pass from a clean checkout; each test creates its own files, users and share links with unique names. The one exception is stated in the file: `test_revoking_every_link_needs_a_fresh_single_use_code` ends every active share of the shared scratch database, so it is the last test of `test_shares.py`.
5. No exception suppression to keep a test green; do not weaken a failing test unless its expectation is shown to be wrong.
6. Do not fill a real disk for disk-full tests; use a test double.
7. A known bug gets a strict xfail with a one-line reason; a fixed bug gets the marker removed in the same change.

## 8. Critical invariants

| Area | Invariant | Covered by |
|---|---|---|
| Authentication | Bad credentials create no session; the lockout works and resets; a logout ends the session on the SERVER, so a copied cookie is refused on every route kind (5.17) | `test_login.py`, `test_session_revocation.py` |
| Client identity | Proxy headers (`CF-Connecting-IP`, `X-Forwarded-For`) are trusted only from a loopback peer (5.16) | `test_client_ip_trust.py` |
| Authorization | Anonymous callers are refused on every non-public route; read-only users cannot mutate; the role is read from the database on every request | `test_authorization.py` |
| Containment | User paths cannot escape the storage root, including a sibling folder whose name starts with the root's; a NUL byte is refused on every platform; chunk ids cannot escape `.chunks` | `test_path_containment.py`, `tests/property/test_properties.py` |
| Uploads | Assembled bytes match; chunks of two sessions never mix; assembly starts when every chunk is present, in any order; a retried last chunk queues once; startup recovery assembles only complete uploads; the file is published atomically and a busy Windows target is retried, then refused with a clear message (5.38, 5.40); parallel chunks assemble once | `test_upload_integrity.py`, `test_upload_chunk_keys.py`, `test_recover_uploads.py`, `test_assemble_atomic.py`, `test_concurrency.py` (opt-in) |
| Sharing | Unknown, revoked, expired and wrong-passkey access returns nothing protected; a passkey or approval grant opens only its own link; a shared folder cannot be walked out of; revoke-all needs a fresh single-use code bound to the session | `test_shares.py` |
| Indexing | Reconcile handles corrupt or stale `file_index.json` without losing valid files; every loaded record is re-scanned before it is served; unchanged data does not rewrite the JSON (4.65); `storage_index.json` is written atomically and a foreign, future or corrupt file is never trusted; the counters follow creates, deletes, moves and hidden / visible renames (5.40) | `test_file_index_recovery.py`, `test_monitor_cache.py`, `test_monitor_handler.py` (the monitor's reconcile walk: still Proposed) |
| Version history | Restore returns the intended bytes, not just a label; a failed or refused restore leaves originals consistent; a version of another file is never restorable; the real worker captures a new and a changed file and history survives a delete | `test_version_restore.py`, `test_version_routes.py` (HTTP, 5.20), `test_version_engine_live.py` (worker, opt-in) |
| File operations | A failed move / write / restore leaves original and unrelated data consistent | partly (containment, mkdir, rename, delete) |
| Protocols | Each enabled protocol enforces authentication and role permissions, reads the role live (a demotion or deletion reaches open sessions), refuses guest / anonymous sessions and keeps every path inside the storage root, a sibling folder named like the root included (5.26-5.31) | `tests/protocols/` (FTP, FTPS, SFTP, WebDAV, SMB), `test_webdav_listener_binds.py` |
| Resource limits | Oversized or expensive inputs are rejected or bounded; loose speed bounds catch an order-of-magnitude regression | partly (`RESPONSE_TIMEOUT` unit test, opt-in slow download, opt-in `test_baselines.py`) |
| Restart and crash | After a graceful stop or a kill the accounts and files survive, an interrupted upload publishes nothing, and quick repeated restarts work | `test_restart.py` (opt-in) |
| Front end | The login page and the file manager load with no script error, failed request, HTTP error or SRI mismatch | `test_browser_smoke.py` (opt-in) |

For each critical operation test valid, malformed, boundary, unauthorized, repeated, dependency-failure and interrupted cases; add concurrency where requests can overlap.

## 9. pytest configuration

Lives in `pyproject.toml` (the owner's choice), tool tables only: `testpaths`, `python_files`, `pythonpath = ["."]`, `addopts = "-ra --import-mode=importlib"` (`tests/` has no `__init__.py`), `timeout = 120`, and the `markers` list (the application tests use `pytestmark = pytest.mark.application`). `-ra` prints one line per XFAIL / SKIP, which is why xfail reasons stay one line. `smoke.py` and `check.py` are not collected; `qa.py` runs them explicitly. There is no `asyncio_mode`: nothing in the suite is async.

## 10. Dependencies

`requirements.txt` and `constraints.txt` are managed by `setup_pymodules.sh` (ceilings, Termux handling). Test packages are never added there. `requirements-dev.txt` today: `pytest>=9.1.1`, `pytest-timeout>=2.4`, `pip-audit>=2.10.1`, `coverage>=7.17.0`, `hypothesis>=6.170`, `ruff==0.17.3` (pinned exactly: a new release adds rules and must not change a green build; `lint.yml` reads that line). CI installs `requirements.txt` as well because the application tests start the real server (Quart, Hypercorn, bcrypt, paramiko, pyftpdlib, wsgidav ...). Not in the file: `playwright` (a large download; `python -m pip install playwright` and `python -m playwright install chromium`, done by `nightly.yml` on Linux) and `mutmut` (replaced by `tests/mutation_trial.py`). `qa audit` and `qa coverage` still skip with a hint when their tool is missing. The audit workflow installs pip-audit in its own environment (so its dependencies are not audited as the application's); `tests.yml` and `coverage.yml` install `requirements-dev.txt`, which now brings both tools. Optional system tools (`ffmpeg`, libvips) are not needed: the scratch config disables them.

## 11. One runner, and the `manage.sh` Quality Assurance section

**`tests/qa.py`** (standard library only, cross-platform) is the single source of truth. `python tests/qa.py --version` prints its version (`QA_VERSION`; compare it to the tests when an install looks half-applied).

```text
python tests/qa.py static            # smoke, check, sri, js-syntax
python tests/qa.py tests             # layout + pytest (unit + application)
python tests/qa.py quick             # static + tests
python tests/qa.py layer <name>      # unit | application | performance ...
python tests/qa.py ci                # what the behavioral-tests job runs (writes JUnit XML to ./artifacts)
python tests/qa.py audit             # pip-audit on the installed packages (network; NOT part of quick / ci)
python tests/qa.py audit --path DIR  # the same for another environment's site-packages (what CI does)
flags: --skip-packages, --out DIR, --fail-fast, --path DIR (audit only)
```

It prints one line per step with PASS / FAIL / SKIP and the elapsed time and exits non-zero on any failure; a stray `tests/test_*.py` is a FAIL (`layout`); the "pip install -r requirements-dev.txt" hint appears only when `pytest` cannot be imported. `audit` is kept out of `quick` / `ci` on purpose: advisories appear without any code change and an offline machine cannot run it. Accepted findings go into `tests/audit_ignore.txt` (advisory ID, then the reason and a review date); `tests/unit/test_qa_audit.py` covers the mode. `coverage` (5.34) runs every layer under coverage.py with subprocess measurement (`pyproject.toml` `[tool.coverage.run]`: `patch = subprocess`, `sigterm = true`, `relative_files`, and NO `source`: it would resolve to the repository, not to the scratch copy a subprocess runs in), writes `artifacts/.coverage`, `coverage.xml` and `htmlcov/`, and takes `--fail-under N`; it is not part of `quick` / `ci`. On Windows the harness stops servers with `TerminateProcess`, their data is lost and server code reads too low: use the Linux workflow. Not implemented: `mutation`, `full`.

**`manage.sh`** stays thin: `cmd_qa()` is one `run_utility "tests/qa.py"` call. Menu 21-25 = `qa quick`, `qa static`, `qa tests`, `qa layer` (asks which layer, default `unit`), `qa ci`; menu 26-29 = Developer Tools (`dir-tree`, `smoke --save`, `qa audit` (pip-audit, network, 5.32), `qa coverage` (slow, 5.34), which asks y/N because it overwrites the route baseline). `tests/unit/test_manage_qa.py` fails when the menu, the `case` arms and the help map disagree, and its `LAST_ENTRY` must be raised whenever the menu grows. QA commands are safe while the production server runs: the pytest layers use a scratch copy and a free port and never import the real app.

## 12. GitHub Actions

- **`tests.yml` (owner-maintained):** job `smoke + check` (keep this name; branch protection may require it) and job `behavioral tests` (`needs` the first; both jobs are required checks through the rulesets; installs `requirements.txt` + `requirements-dev.txt`; runs `python tests/qa.py ci`; uploads `artifacts/`). Python 3.14.7 in both jobs; `actions/checkout`, `setup-python` and `upload-artifact` at `@v7`; `concurrency` cancels superseded runs; `permissions: contents: read`. The zips never contain workflow files.
- **`coverage.yml` (5.34):** job `coverage report`: `python tests/qa.py coverage --out artifacts` on Linux, weekly (Monday) and on demand, a markdown summary in the job summary and `artifacts/` (coverage.xml, htmlcov) uploaded; not a required check; `schedule` runs only once the file is on the default branch. 5.40: **Run workflow** takes an optional `fail_under` percentage (passed through an environment variable) to try a floor without editing the file.
- **`CODEOWNERS` (5.34):** `.github/CODEOWNERS` lists the owner for everything, `tests/`, `.github/`, `docs/rulesets/` and `pyproject.toml`; the rulesets do not require a code-owner review.
- **`audit.yml` (5.32):** job `dependency audit`: installs `requirements.txt`, installs pip-audit in a separate venv and runs `python tests/qa.py audit --path <site-packages>`; weekly, on demand and when `requirements.txt`, `constraints.txt`, `tests/audit_ignore.txt` or `tests/qa.py` change. **Not a required check** (new advisories would block unrelated pull requests, and a path-filtered workflow does not report on every pull request).
- **Branch rules (5.32):** `docs/rulesets/main.json` and `dev.json` (import once, see its README): pull request required (0 approvals), checks `smoke + check` and `behavioral tests` required, no force-push or deletion; admins may bypass (`main`: only through a pull request, `dev`: always). Direct pushes are then rejected: work on a branch and merge by pull request.
- **`codeql.yml`:** CodeQL Advanced for Python and JavaScript plus the SARIF-to-CSV job; unchanged by the test work.
- **`lint.yml` (5.40):** Ruff in REPORT-ONLY mode (`--exit-zero`; annotations and a summary by rule), rules in `pyproject.toml` `[tool.ruff]` (`E`, `F`, `B`, `S`; Black keeps the formatting), Ruff version read from the pinned line in `requirements-dev.txt`. Path-filtered and not required. Plan: triage the findings once, then add `python -m ruff check .` to the required `smoke + check` job (same check name, so no ruleset change).
- **`nightly.yml` (5.40):** `schedule` (02:17 UTC, default branch) and manual (any branch: Actions > Nightly > Run workflow > `dev` to test before a merge). Matrix `ubuntu-latest` + `windows-latest` (production is Windows: `WinError 32`, junctions, path separators), `fail-fast: false`, 75 minutes. Runs `python tests/qa.py ci` with `CLOUDINATOR_SLOW_TESTS=1` and `CLOUDINATOR_NIGHTLY=1`; Playwright + Chromium on Linux only. Artifact `nightly-results-<os>` (JUnit XML; the measured baselines are properties). Not required.
- **`mutation.yml` (5.40):** manual only: `tests/mutation_trial.py` on the file, functions and tests you enter; survivors are reported, never failed.
- **`dependabot.yml` (5.40):** weekly pip and GitHub Actions updates, pull requests into `dev`. `requirements.txt` / `constraints.txt` are rewritten by `setup_pymodules.sh`: decide which one you trust before merging a pip update.
- **Still Proposed:** a `qa.py lint` mode and a `manage.sh` menu entry (they need `tests/unit/test_qa_runner.py` and `test_manage_qa.py` updated together); Ruff as a required step; Dependabot security updates (a repository setting, not a file).
- Rules: minimal token permissions; no secrets in jobs that run pull-request code; workflow, marker and threshold changes get the same review as code. `.gitignore` must list `.pytest_cache/`, `artifacts/` and `.coverage`, `coverage.xml`, `htmlcov/`, `.hypothesis/` (the tests use no example database, so it should stay empty); `mutants/` only if mutmut is ever tried. Workflow inputs go through `env:`, never straight into a `run:` script.

## 13. Changes made with AI assistance, and definition of done

- Changed critical behavior needs tests, not just changed lines. Do not delete or weaken a failing test unless its expectation is shown to be wrong.
- Keep independent expected values (bytes, permissions, index records, HTTP responses); do not compare two outputs of the same code path.
- State plainly what was and was not run: the sandbox usually has only the modules that were uploaded, so a new application test that was written but not run is reported as such, and the owner's `./manage.sh qa quick` is the verification.
- Review edits to tests, thresholds, markers and workflows together with the code change.
- Authentication, authorization, filesystem boundaries, upload validation and CI security controls always get explicit review.

Done for a critical change: `./manage.sh qa quick` passes locally; relevant negative-path and authorization tests pass; a regression test exists for each fixed defect; PR checks are green; `CLAUDE.md` (version bump, sync note, changelog) and `CODING_GUIDELINES.md` are updated.

## 14. Phases and status

| Phase | Work | Status |
|---|---|---|
| 0 | Open questions: layering rule for tests, how `paths.py` / `config.py` locate config, import-time threads | **Done** (answers drove the scratch-copy + subprocess design, section 5) |
| 1 | `pyproject.toml`, `requirements-dev.txt`, `conftest.py` with safety guard, unit tests, `qa.py`, `behavioral tests` job | **Done** (5.00-5.05) |
| 2 | Application tests for login, authorization, containment, uploads, sharing, index recovery, version restore; `manage.sh` QA section | **Done**: login, authorization, containment, upload integrity, shares (5.18), version restore and file-index recovery (5.19); `manage.sh` QA 21-25. The 5.18 and 5.19 tests wait for their first run on the owner's machine |
| 3 | Coverage report, Ruff, `pip-audit`, Hypothesis, mutation trial | **Done** (Ruff in report-only mode): Developer Tools (`dir-tree`, `smoke --save`), `pip-audit` (5.32), coverage report (5.34), Hypothesis (5.40), Ruff configured and run by `lint.yml` (5.40), `tests/mutation_trial.py` + `mutation.yml` (5.40; mutmut itself was tried on paper and rejected, section 0) |
| 4 | `nightly.yml`, protocol tests (**done**, 5.26-5.31: FTP, FTPS, SFTP, WebDAV, SMB), fault / concurrency / restart tests, browser smoke, performance baselines | **Written (5.40), not yet run on the real application or on GitHub:** `nightly.yml`, `test_version_engine_live.py` + `scratch_server_with_versions`, `test_concurrency.py`, `test_restart.py`, `test_baselines.py`, `test_browser_smoke.py`. Done means: one green nightly run on Linux and Windows. Known guesses: the browser test's login selectors; the Windows runner's `requirements.txt` install |
| 5 | Required checks, coverage floor, CODEOWNERS for `tests/` and workflows | **Partly**: required checks through the rulesets in `docs/rulesets/` (imported and active, 5.32); CODEOWNERS (5.34) done; `qa coverage --fail-under N` exists (5.34) and `coverage.yml` takes it as an input (5.40), but the FLOOR waits for the first Linux total: run the Coverage workflow, paste its summary, then pick N a few points below it |

**Version restore and index recovery** (5.19, 5.20, 5.40): the real modules run inside a scratch copy through `run_in_scratch()` (deterministic, no worker), the HTTP routes `/api/versions/*` are covered by `test_version_routes.py` in the normal scratch server (the routes work with the engine off), and the REAL worker is covered by `scratch_server_with_versions` (the same scratch copy with `VERSION_ENGINE_ENABLED: true`, `VERSION_TRACK_ROOTS` = the scratch storage; the engine is its own process, so every wait is a bounded poll). `file_monitor.py`'s calls into the folder and search indexes and `storage_index.json` are covered by `test_monitor_handler.py` and `test_monitor_cache.py` (5.40). **Still Proposed:** the monitor's walks (`_full_walk`, `_reconcile_walk`, `_correct_folders`) on a real tree, and crash recovery of the Version Engine worker (kill it, start it again).

**What is open after 5.40, in order:** (1) run `nightly.yml` once from `dev` (Actions > Nightly > Run workflow), fix what the first run shows; (2) run the Coverage workflow, paste the Linux summary, choose the floor; (3) triage the Ruff findings, then make Ruff a required step; (4) `qa lint` mode and menu entry; (5) CodeQL alert #612 (cyclic import `version_engine` / `config`, needs `config.py`). **The `.gitignore` step is NOT due:** when phases 4 and 5 are 100 % done, add `docs/TESTING_STRATEGY.md` to `.gitignore` and run `git rm --cached docs/TESTING_STRATEGY.md` once so git stops tracking it (the file stays on disk); until then it stays committed.

## 15. What is not realistic

- A guarantee of zero regressions, or a high global mutation threshold.
- Strict timing assertions on shared runners; performance gates need loose bounds or a dedicated runner.
- Cloudflare Tunnel, real disk-full simulation and a real Windows SMB / WebDAV client in CI (SMB itself is tested on the fallback port with impacket's client, 5.31).
- Importing the real app repeatedly in one process; singletons and import-time side effects make that fragile, which is why the scratch copy and subprocess exist.
- Automating visual checks (CSS / layout); a Playwright smoke would only catch load errors.

## 16. References

- pytest: <https://docs.pytest.org/> - fixtures: <https://docs.pytest.org/en/stable/how-to/fixtures.html>
- Coverage.py: <https://coverage.readthedocs.io/> - Hypothesis: <https://hypothesis.readthedocs.io/>
- mutmut: <https://mutmut.readthedocs.io/> - pip-audit: <https://github.com/pypa/pip-audit>
- GitHub Actions security hardening: <https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions>
- Protected branches: <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches>