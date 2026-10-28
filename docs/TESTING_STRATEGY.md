# CloudinatorFTP Testing Strategy

> **Status: tracked in git for now.** It becomes `.gitignored` (a local planning document) only after ALL the phases below are 100% implemented; see `CLAUDE.md` READ HERE FIRST and `CODING_GUIDELINES.md` section 18. Until then update it with every testing change; after that do not link to it from a committed document. The facts it holds are repeated in `CLAUDE.md` and `CODING_GUIDELINES.md`.

**Status (2026-10-23, Version 5.19):** Phases 0, 1 and 2 are DONE (the 5.18 and 5.19 tests are written but their first run on the owner's machine is pending). Phase 3 is partly done (see section 14). Everything still marked "Proposed" below does not exist yet.
**This is a temporary working document; the owner does not commit it.** The permanent record is `CLAUDE.md` (sync notes 50-67) and `CODING_GUIDELINES.md`.
**Scope:** Quart HTTP routes, SQLite behavior, storage and file index, upload pipeline, version history, sharing, FTP/SFTP/WebDAV, the front-end contracts that break silently (SRI, CSP), and the `manage.sh` Quality Assurance section.
**Read with:** [CLAUDE.md](CLAUDE.md) (history, rules) and [CODING_GUIDELINES.md](CODING_GUIDELINES.md) (how to change things).

No test suite can guarantee that every defect is caught; the goal is layered, repeatable evidence that changes keep the application's contracts.

## 0. What changed since the first draft (read this first)

The first draft proposed an in-process Quart test client. Reading the code (Phase 0) and then building Phase 1 showed that cannot work, so the design below differs from the draft in these ways:

| Draft said | What exists |
|---|---|
| App imported in-process, Quart test client, `pytest-asyncio`, session-scoped app | The app is **never** imported in the pytest process. `tests/conftest.py` copies the source tree to a temp folder and runs `dev_server.py` there as a **subprocess** on an ephemeral port; tests talk to it over HTTP with a standard-library, cookie-aware `HttpClient`. No `pytest-asyncio`, no `httpx` |
| `pytest.ini` | `pyproject.toml` (`[tool.pytest.ini_options]`, the owner's choice). A leftover `pytest.ini` would silently win, so there must be none |
| `requirements-dev.txt` with many tools | `pytest>=9.1.1`, `pytest-timeout>=2.4`, `pip-audit>=2.10.1` and `coverage>=7.17.0` (the owner added the last two); hypothesis, mutmut, ruff and playwright are still Proposed |
| `qa.py` modes `static / quick / layer / coverage / mutation / ci / full` | `static`, `tests`, `quick`, `layer <name>`, `ci`, `audit` (5.32), `coverage` (5.34), plus `--version`, `--skip-packages`, `--out DIR`, `--fail-fast`. Steps: `smoke`, `check`, `sri`, `js-syntax`, `layout`, `pytest`. `mutation`, `full` do not exist |
| `manage.sh` QA entries 21-26 (with coverage and mutation) | 21-25: `qa quick`, `qa static`, `qa tests`, `qa layer`, `qa ci`; 26-29 are the separate Developer Tools section (`dir-tree`, `smoke --save`, `qa audit` (5.32), `qa coverage` (5.34)). The menu has 29 entries |
| CI: Python 3.12, only pyflakes, SRI "not yet in CI" | `tests.yml` uses Python **3.14.7** and `@v7` actions; job `smoke + check` and job `behavioral tests` (`needs` the first, `continue-on-error: true`, runs `python tests/qa.py ci`, uploads `artifacts/`). SRI and `node --check` run inside `qa.py` (so in CI through `qa ci`), not as separate steps of the static job |
| `tests/integration/`, `protocols/`, `property/`, `reliability/`, `frontend/` | Only `tests/unit/`, `tests/application/` and `tests/performance/` exist (one opt-in slow download test) |
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
| **PR** | push / pull request to `main` and `dev` | `smoke`, `check`, then `qa.py ci` = smoke, check, sri, js-syntax, layout, unit + application pytest, JUnit XML | Exists (`behavioral tests` is still informational: `continue-on-error`; it has been green, so removing that line and requiring the job is the next CI step) |
| **Opt-in** | `CLOUDINATOR_SLOW_TESTS=1` | `tests/performance/test_slow_download.py` (about 85 s, a throttled download that used to be cut at 60 s) | Exists, skipped by default |
| **Nightly** | `schedule` + manual | Windows runner, protocols, property, reliability, performance, mutation, browser smoke | Proposed |
| **Never in CI** | n/a | SMB on port 445, Cloudflare Tunnel, real disk-full, anything touching production paths | n/a |

## 4. Layout (what exists)

```text
CloudinatorFTP/
├── pyproject.toml            # pytest config ONLY (no [project]); there must be no pytest.ini
├── requirements-dev.txt      # pytest, pytest-timeout, pip-audit, coverage (never merged into requirements.txt / setup_pymodules.sh)
├── .github/workflows/        # tests.yml, codeql.yml  (nightly.yml, dependabot.yml: Proposed)
└── tests/
    ├── smoke.py  check.py  qa.py  dir_tree.py  codeql_sarif_parser.py  smoke_routes.json
    ├── conftest.py           # scratch copy, scratch server, HttpClient, test users, safety guards
    ├── unit/                 # pure helpers, qa.py, manage.sh QA section, harness itself, ast-extracted app logic
    ├── application/          # real app over HTTP: boot, login, authorization, containment, uploads, shares
    └── performance/          # opt-in slow tests
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

**Layer 4B - protocols (nightly):** FTP/FTPS, SFTP, WebDAV against isolated local instances; SMB is manual. Proposed.

**Layer 5 - extras:** Hypothesis for path strings and chunk metadata, fault injection and bounded concurrency, performance baselines, node + jsdom suites for `index.js`, a Playwright smoke that fails on CSP or SRI console errors, coverage.py, `mutmut` on pure modules (Linux only). Proposed.

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
| Containment | User paths cannot escape the storage root, including a sibling folder whose name starts with the root's; chunk ids cannot escape `.chunks` | `test_path_containment.py` |
| Uploads | Assembled bytes match; chunks of two sessions never mix; assembly starts when every chunk is present, in any order; a retried last chunk queues once; startup recovery assembles only complete uploads | `test_upload_integrity.py`, `test_upload_chunk_keys.py`, `test_recover_uploads.py` |
| Sharing | Unknown, revoked, expired and wrong-passkey access returns nothing protected; a passkey or approval grant opens only its own link; a shared folder cannot be walked out of; revoke-all needs a fresh single-use code bound to the session | `test_shares.py` |
| Indexing | Reconcile handles corrupt or stale `file_index.json` without losing valid files; every loaded record is re-scanned before it is served; unchanged data does not rewrite the JSON (4.65) | `test_file_index_recovery.py` (`storage_index.json` / the monitor's reconcile: Proposed) |
| Version history | Restore returns the intended bytes, not just a label; a failed or refused restore leaves originals consistent; a version of another file is never restorable | `test_version_restore.py` (HTTP routes: Proposed) |
| File operations | A failed move / write / restore leaves original and unrelated data consistent | partly (containment, mkdir, rename, delete) |
| Protocols | Each enabled protocol enforces authentication and role permissions, reads the role live (a demotion or deletion reaches open sessions), refuses guest / anonymous sessions and keeps every path inside the storage root, a sibling folder named like the root included (5.26-5.31) | `tests/protocols/` (FTP, FTPS, SFTP, WebDAV, SMB), `test_webdav_listener_binds.py` |
| Resource limits | Oversized or expensive inputs are rejected or bounded | partly (`RESPONSE_TIMEOUT` unit test, opt-in slow download) |

For each critical operation test valid, malformed, boundary, unauthorized, repeated, dependency-failure and interrupted cases; add concurrency where requests can overlap.

## 9. pytest configuration

Lives in `pyproject.toml` (the owner's choice), tool tables only: `testpaths`, `python_files`, `pythonpath = ["."]`, `addopts = "-ra --import-mode=importlib"` (`tests/` has no `__init__.py`), `timeout = 120`, and the `markers` list (the application tests use `pytestmark = pytest.mark.application`). `-ra` prints one line per XFAIL / SKIP, which is why xfail reasons stay one line. `smoke.py` and `check.py` are not collected; `qa.py` runs them explicitly. There is no `asyncio_mode`: nothing in the suite is async.

## 10. Dependencies

`requirements.txt` and `constraints.txt` are managed by `setup_pymodules.sh` (ceilings, Termux handling). Test packages are never added there. `requirements-dev.txt` today: `pytest>=9.1.1`, `pytest-timeout>=2.4`, `pip-audit>=2.10.1`, `coverage>=7.17.0`. CI installs `requirements.txt` as well because the application tests start the real server (Quart, Hypercorn, bcrypt, paramiko, pyftpdlib, wsgidav ...). Proposed later: `hypothesis`, `ruff`, and for nightly only `mutmut` and `playwright`. `qa audit` and `qa coverage` still skip with a hint when their tool is missing. The audit workflow installs pip-audit in its own environment (so its dependencies are not audited as the application's); `tests.yml` and `coverage.yml` install `requirements-dev.txt`, which now brings both tools. Optional system tools (`ffmpeg`, libvips) are not needed: the scratch config disables them.

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

- **`tests.yml` (owner-maintained):** job `smoke + check` (keep this name; branch protection may require it) and job `behavioral tests` (`needs` the first; `continue-on-error: true`; installs `requirements.txt` + `requirements-dev.txt`; runs `python tests/qa.py ci`; uploads `artifacts/`). Python 3.14.7 in both jobs; `actions/checkout`, `setup-python` and `upload-artifact` at `@v7`; `concurrency` cancels superseded runs; `permissions: contents: read`. The zips never contain workflow files.
- **`coverage.yml` (5.34):** job `coverage report`: `python tests/qa.py coverage --out artifacts` on Linux, weekly (Monday) and on demand, a markdown summary in the job summary and `artifacts/` (coverage.xml, htmlcov) uploaded; not a required check; `schedule` runs only once the file is on the default branch.
- **`CODEOWNERS` (5.34):** `.github/CODEOWNERS` lists the owner for everything, `tests/`, `.github/`, `docs/rulesets/` and `pyproject.toml`; the rulesets do not require a code-owner review.
- **`audit.yml` (5.32):** job `dependency audit`: installs `requirements.txt`, installs pip-audit in a separate venv and runs `python tests/qa.py audit --path <site-packages>`; weekly, on demand and when `requirements.txt`, `constraints.txt`, `tests/audit_ignore.txt` or `tests/qa.py` change. **Not a required check** (new advisories would block unrelated pull requests, and a path-filtered workflow does not report on every pull request).
- **Branch rules (5.32):** `docs/rulesets/main.json` and `dev.json` (import once, see its README): pull request required (0 approvals), checks `smoke + check` and `behavioral tests` required, no force-push or deletion; admins may bypass (`main`: only through a pull request, `dev`: always). Direct pushes are then rejected: work on a branch and merge by pull request.
- **`codeql.yml`:** CodeQL Advanced for Python and JavaScript plus the SARIF-to-CSV job; unchanged by the test work.
- **Proposed:** (`continue-on-error` is gone and the checks are required through the rulesets above); a Windows runner in the matrix (production is Windows, and several recorded bugs are Windows-only: `WinError 32`, junctions, path separators); `nightly.yml` (`ref: [main, dev]` x `os`) for protocols, property, reliability, performance, browser smoke and Linux-only mutation; `.github/dependabot.yml` for `github-actions` and dev requirements; branch protection on `main` and `dev` if the plan allows it.
- Rules: minimal token permissions; no secrets in jobs that run pull-request code; workflow, marker and threshold changes get the same review as code. `.gitignore` must list `.pytest_cache/`, `artifacts/` (and later `.coverage`, `coverage.xml`, `htmlcov/`, `.hypothesis/`, `mutants/`).

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
| 3 | Coverage report, Ruff, `pip-audit`, Hypothesis, mutmut trial | **Partly**: Developer Tools (`dir-tree`, `smoke --save`), `pip-audit` (5.32) and the coverage report (5.34) done; Ruff, Hypothesis, mutmut not started |
| 4 | `nightly.yml`, protocol tests (**done**, 5.26-5.31: FTP, FTPS, SFTP, WebDAV, SMB), fault / concurrency / restart tests, browser smoke, performance baselines | Not started (one opt-in performance test exists) |
| 5 | Required checks, coverage floor, CODEOWNERS for `tests/` and workflows | **Partly**: required checks through the rulesets in `docs/rulesets/` (imported and active, 5.32); CODEOWNERS (5.34) done; the coverage floor waits for the first Linux baseline (`qa coverage --fail-under N`) |

**Version restore and index recovery: done with approach (b)** (5.19): the real modules run inside a scratch copy through `run_in_scratch()`, deterministic, no worker. **Still Proposed:** a fixture `scratch_server_with_versions` (the same scratch copy with `VERSION_ENGINE_ENABLED: true`; the engine is its own worker process, so tests must wait for a capture with a bounded poll and the server starts slower) to drive the HTTP routes `/api/versions/*` end to end, and tests of `file_monitor.py`'s calls into the index and of `storage_index.json`.

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