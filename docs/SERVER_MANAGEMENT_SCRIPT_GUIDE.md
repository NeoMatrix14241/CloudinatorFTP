# 🖥️ manage.sh — Server Management Script Guide

**Last Updated**: 2026-10-22
**Works on**: Windows (Git Bash), Linux, and Android (Termux)
**Checked against**: `manage.sh` itself (commands, menu numbers, and behaviour below are read from the script, not from memory)

`manage.sh` runs the Cloudinator server in the **background** so your terminal stays free, and gives you one entry point for the maintenance utilities (users, config, SMB, share links, version engine, SRI hash checking, the automated quality checks, the folder-tree and route-snapshot tools, and so on).

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Platform Notes (Windows / Linux / Termux)](#platform-notes)
3. [Server Commands](#server-commands)
4. [Log Commands](#log-commands)
5. [Utility Commands](#utility-commands)
6. [Quality Assurance Commands](#quality-assurance-commands)
7. [Developer Tools Commands](#developer-tools-commands)
8. [security.txt Command](#securitytxt-command)
9. [Interactive Menu](#interactive-menu)
10. [Files and Folders It Uses](#files-and-folders-it-uses)
11. [How Background Mode and Ctrl-C Work](#how-background-mode-and-ctrl-c-work)
12. [WebDAV Is a Separate Process](#webdav-is-a-separate-process)
13. [Environment Variable: PYTHON](#environment-variable-python)
14. [Troubleshooting](#troubleshooting)

---

## Quick Start

Run everything from the project folder (the one that contains `manage.sh`).

```bash
chmod +x manage.sh          # once (or run it as: bash manage.sh <command>)
./manage.sh                 # dashboard: what is running + quick commands
./manage.sh start server    # start the production server in the background
./manage.sh status          # PID, uptime, last 5 log lines
./manage.sh logs server -f  # follow live logs (Ctrl-C detaches, server keeps running)
./manage.sh stop            # stop it
```

Running `./manage.sh` with no arguments is the same as `./manage.sh dashboard`. `./manage.sh help` prints the full built-in command list, and an unknown command prints an error followed by that same help text.

---

## Platform Notes

The script detects where it is running and adjusts. You do not have to tell it.

| | Windows | Linux | Android (Termux) |
|---|---|---|---|
| **Shell** | Git Bash (the script detects `msys`/`cygwin`) | bash | bash |
| **Stopping the server** | `taskkill //F` on the saved PID (immediate, forced) | Polite stop first, then force-kill after about 5 seconds if it has not exited | Same as Linux |
| **Uptime in `status`** | Shows just `running` | Real uptime from `ps` | Real uptime from `ps` |
| **Port sweep for orphaned WebDAV** | Uses `netstat` | Uses `lsof` **if it is installed** (skipped silently otherwise) | Same as Linux, so it needs `lsof` |
| **`termux-setup`** | Explains it is Android-only and points to `pip install -r requirements.txt` | Explains it is Android-only and points to `LINUX_DEPLOYMENT.md` | Runs `termux_setup.sh` |
| **`update-modules`** | Relaunches itself as Administrator (UAC prompt) and adds a Windows Defender exclusion for your Python folder | Runs normally | Runs normally |

Termux is detected by the folder `/data/data/com.termux` or the `termux-setup-storage` command.

> 💡 **Windows:** run it from **Git Bash**, not PowerShell or `cmd`. The script is a bash script.

---

## Server Commands

Only **one** server can run at a time (production *or* dev). Trying to start the other one shows which is running and how to stop it.

| Command | What it does |
|---|---|
| `./manage.sh start server` | Start `prod_server.py` (Hypercorn) in the background |
| `./manage.sh start dev_server` | Start `dev_server.py` (Quart) in the background |
| `./manage.sh stop` | Stop whichever server is running, then clean up WebDAV (see below) |
| `./manage.sh restart` | Stop and start again whichever server is running |
| `./manage.sh restart-webdav` | Restart **only** WebDAV, without touching the main server |
| `./manage.sh status` | Shows both servers as running/stopped, PID, uptime, log file name, and the last 5 log lines |

Details worth knowing:

- **Start** waits about 0.8 seconds and checks the process is still alive. If it died right away it prints `crashed immediately` and tells you to run `python prod_server.py` (or `dev_server.py`) in the foreground to see the real error.
- **Start** first cleans up any leftover WebDAV process from a previous crash, so a stale one cannot block the ports.
- **Restart** needs a server to be running. If none is, it tells you to use `start` instead.
- **restart-webdav** needs a running server and a WebDAV PID file. It kills the WebDAV process and waits up to about 10 seconds for the server's own watchdog to respawn it, then reports the new PID. Use it to recover a stuck WebDAV listener (for example after a large cancelled download) without disconnecting web users.

---

### Startup messages are not shown in background mode

`start` runs the server detached with its console output thrown away. Startup banners that the code `print()`s (for example the WebDAV HTTPS line that tells you where to fetch the certificate) **do not appear** when you use `./manage.sh start server`. To see them, run the server in the foreground instead:

```bash
python prod_server.py     # or: python dev_server.py
```

What does reach the log files is whatever goes through the app's logger (request timing, errors, protocol events, uncaught exceptions). The certificate itself is always at `db/webdav.crt`, and on a default install it can also be downloaded from `https://HOST:8443/webdav.crt`.

---

## Log Commands

| Command | What it does |
|---|---|
| `./manage.sh logs` | Last 50 lines of the running server's log |
| `./manage.sh logs server` | Last 50 lines of the production log |
| `./manage.sh logs dev_server` | Last 50 lines of the dev log |
| `./manage.sh logs server -f` | Follow live (shows the last 20 lines first, then new lines as they arrive) |
| `./manage.sh logs dev_server -f` | Same for the dev server |
| `./manage.sh clean-logs` | List log files with sizes, then delete them after a `y` confirmation |

- With no server named, `logs` uses the one that is running. If none is running, it asks you to name one.
- **Ctrl-C while following** detaches you and leaves the server running. It works the same on Windows, Linux, and Termux.
- `clean-logs` deletes every `*_server_*.log` file **except** the current log of a running server. Anything other than `y` cancels.
- If today's log does not exist yet, `logs` just says no log file was found.

---

## Utility Commands

Utilities run in the **foreground** and are safe to use while the server is up. Any extra arguments you add are passed straight to the script. Ctrl-C cancels the utility and returns you to your prompt.

| Command | Runs | Purpose |
|---|---|---|
| `version-manage` | `tools/version_manage.py` | Version Engine: list, restore, delete file versions (no arguments opens its own menu) |
| `setup-smb` | `tools/smb_setup.py` | One-time SMB setup (see `SMB_PROTOCOL_DEPLOYMENT.md`) |
| `kick-sessions` | `tools/kick_sessions.py` | Force logout of every active session (server must be running) |
| `config` | `config.py` | Interactive configuration (see `CONFIG_PY_REFERENCE.md`) |
| `manage-users` | `tools/manage_users.py` | Manage user credentials |
| `reset-db` | `tools/reset_db.py` | Reset the database |
| `setup-storage` | `tools/setup_storage.py` | Configure storage |
| `update-modules [-y]` | `setup_pymodules.sh` | Update Python packages (alias: `setup-modules`) |
| `revoke-shares` | `tools/revoke_sharing.py` | Share link management |
| `validate-sri [--fix]` | `tools/sri_validator.py` | Check (or repair) the Subresource Integrity hashes in the templates |
| `termux-setup` | `termux_setup.sh` | First-time setup, Android/Termux only |

When a utility finishes, the script prints whether it finished, was interrupted (Ctrl-C), or exited with an error code.

### version-manage

Per the script's built-in help:

```bash
./manage.sh version-manage                                   # interactive menu
./manage.sh version-manage list                              # every tracked file + version count
./manage.sh version-manage list <path>                       # one file's version history
./manage.sh version-manage restore <id> <dest>               # restore a version
./manage.sh version-manage restore <id> <dest> --overwrite   # replace an existing file
./manage.sh version-manage delete <id>                       # permanently delete a version
./manage.sh version-manage delete <id> --run-gc-now
```

`--overwrite` and `delete` ask you to type a confirmation phrase.

### revoke-shares

```bash
./manage.sh revoke-shares                                    # interactive menu
./manage.sh revoke-shares list
./manage.sh revoke-shares revoke <token> [--yes]
./manage.sh revoke-shares revoke-path <path> [--yes]
./manage.sh revoke-shares revoke-all [--yes]                 # asks for a typed code; --yes skips only the y/N
./manage.sh revoke-shares edit <token> --mode passkey --generate-passkey --expires-in 7d
./manage.sh revoke-shares edit-path <path> --never-expire
./manage.sh revoke-shares requests                           # pending access requests
./manage.sh revoke-shares approve <id> --max-downloads 3
./manage.sh revoke-shares deny <id>
```

Edit options: `--mode public|passkey|approval`, `--passkey KEY` (implies passkey mode unless a mode is already set), `--generate-passkey`, `--clear-passkey`, `--expires-in 1h|2d|30m|7d|SECONDS`, `--never-expire`. `approve` allows **1** download unless you pass `--max-downloads N`.

### validate-sri

Your HTML templates load scripts and stylesheets with an `integrity="sha384-..."` hash. If the hash does not match the file, the browser **silently refuses to run the script** (and ignores the stylesheet), so a forgotten update breaks a page with no visible error. This command compares every hash with the file on disk.

```bash
./manage.sh validate-sri          # check only; exit code 1 if any hash is wrong or missing
./manage.sh validate-sri --fix    # write the correct hashes into the templates
```

- It reads every `<script src>` and `<link href>` in `templates/` that points at a file in `static/` (written as `{{ url_for('static', filename='...') }}` or `/static/...`).
- The report lists each tag as `OK`, `STALE` (hash differs from the file), `NONE` (no `integrity` yet), `MISS` (the file is not in `static/`), or `skip` (an inline script or an external URL, which cannot be hashed).
- `--fix` only changes `integrity` values. Line endings and the rest of each template stay exactly as they were.
- It always looks in the `templates/` and `static/` folders next to `manage.sh`, wherever you run it from. `--templates DIR` and `--static DIR` override that.
- **When to run it:** after you edit any JS or CSS under `static/` (including `bg_audio.js`, whose hash is repeated in four templates), and after you change a third-party file such as pdf.js. Then open each page once and look for blocked-script errors in the browser console.
- **From the interactive menu (`./manage.sh menu`, option 20)** it runs the check, and if any hash is stale or missing it asks `Fix the stale/missing hashes now? [y/N]`. `y` runs the same repair as `--fix`; Enter or `n` leaves everything unchanged (and reminds you of the shell command). The question appears only when the check found a fixable problem, not when everything is OK, when you press Ctrl-C, or when the `templates/` or `static/` folder is missing.
- Because it exits with 1 when something is wrong, you can also use it in a script or git pre-commit hook: `./manage.sh validate-sri || exit 1`.

Limits: browsers only enforce the hash on `<script>` tags and on stylesheet/preload links (icon and `locale.json` links accept the attribute but ignore it). Tags that JavaScript adds at runtime are not in any template, so they are not checked. The hash must match the bytes the **server** sends, so if git converts line endings on checkout, run the command on the server's copy.

### update-modules

```bash
./manage.sh update-modules        # asks before doing anything
./manage.sh update-modules -y     # skips that first question (for scripts)
```

It runs `setup_pymodules.sh`, which rewrites `requirements.txt` and `constraints.txt`, runs a pip dry-run to check the versions fit together, and asks once more before installing or upgrading. Ctrl-C at the first question cancels with nothing changed.

---

## Quality Assurance Commands

The `qa` commands run the project's automated checks. Every one of them is a single call to `tests/qa.py`, the same runner the GitHub **Tests** workflow uses, so a green run here means the same commands passed that GitHub runs. They run in the **foreground** and are safe while a server is up: the tests copy the project into a temporary folder and start their own server there on a free port, so they never touch your real `db/`, `cache/`, `versions/` or storage folders.

| Command | What it runs |
|---|---|
| `qa` or `qa quick` | `smoke.py`, `check.py`, the SRI check, `node --check` on the first-party JavaScript (skipped if Node.js is not installed) and every pytest layer |
| `qa static` | Only the static checks above (no pytest) |
| `qa tests` | Only pytest, on every `tests/<layer>` folder that exists |
| `qa layer <name>` | One layer: `unit`, `integration`, `application`, `protocols`, `property`, `reliability`, `performance` or `frontend` |
| `qa ci` | Same as `quick`, and writes JUnit XML into `./artifacts` (what GitHub runs) |
| `qa --version` | Prints which copy of `tests/qa.py` you have |

Extra arguments go straight to `qa.py`: `--skip-packages` (do not warn about packages that are not installed), `--out DIR` (write JUnit XML into `DIR`) and `--fail-fast` (stop at the first failing step).

```bash
./manage.sh qa                    # everything
./manage.sh qa layer unit         # one layer
./manage.sh qa quick || exit 1    # usable from a script or git hook: exit code 1 means a step failed
```

- **Slow tests:** `qa layer performance` runs the end-to-end download test only when `CLOUDINATOR_SLOW_TESTS=1` is set in the environment (about 85 s); otherwise it is reported as skipped.
- **One-time setup:** the test packages are not in `requirements.txt`. Run `python -m pip install -r requirements-dev.txt` once.
- **SKIP is not PASS:** a step that cannot run (Node.js missing, a layer folder that does not exist yet) is reported as `SKIP` with the reason and does not fail the run. A `FAIL` does.
- **Misplaced test files:** a `test_*.py` file directly inside `tests/` runs in no layer, so `qa` reports it as a `FAIL` and tells you to move it into `tests/unit/` or `tests/application/`.
- **Exit codes:** `0` all steps passed or were skipped, `1` at least one step failed, `2` unknown mode or layer, `130` Ctrl-C.

---

## Developer Tools Commands

Two small tools from the `tests/` folder have their own commands. They only **read** source files and folder names (they never start the app or touch your database, cache or storage), so they are safe while a server is up. They run in the foreground, and Ctrl-C cancels them.

| Command | Runs | Purpose |
|---|---|---|
| `dir-tree` | `tests/dir_tree.py` | Print the project folder tree and save it to `docs/DIRECTORY_TREE.md` |
| `smoke [options]` | `tests/smoke.py` | Fast static safety net. `--save` writes the route snapshot `tests/smoke_routes.json` |

### dir-tree

```bash
./manage.sh dir-tree
```

- Prints the tree and writes it to `docs/DIRECTORY_TREE.md`, creating `docs/` if it is missing. The file is overwritten every time and never lists itself.
- Folders come first, then files, each sorted A to Z ignoring case.
- **Hidden completely:** `__pycache__`, `.git`, `.venv`, `venv`, `env`, `.pytest_cache`, `.manage_pids` and `logs`.
- **Shown but not opened** (printed as `... (reason)`): `images`, `cmaps`, `iccs`, `locale`, `standard_fonts`, `wasm`, `uploads` and `webfonts`. They are matched by folder **name** only, so any folder with one of those names is collapsed, including a project-root `images/` folder.
- Vendored files get a short note after their name (`pdf.mjs`, `pdf.worker.mjs`, `viewer.mjs`, `viewer.css`, `video.js`, `video.css`, `all.min.js`). The lists are at the top of `tests/dir_tree.py` if you want to change them.
- It takes **no options**; anything typed after the command is ignored.
- **When to run it:** after files are added, moved or removed, then commit `docs/DIRECTORY_TREE.md`.

### smoke

```bash
./manage.sh smoke            # run every check (a few seconds)
./manage.sh smoke --save     # run every check, then write the route snapshot
./manage.sh smoke -v         # also print the route table
./manage.sh smoke --files    # also list every .py file that was scanned
```

Anything after `smoke` goes straight to `tests/smoke.py`. The checks, in short:

- every `.py` file parses (syntax), and `pyflakes` finds undefined names (skipped with a hint if `pyflakes` is not installed);
- the route table: one function per endpoint name, and no URL and method registered twice;
- every `url_for('x')` and endpoint-name list refers to a real endpoint;
- hooks (`before_request`, `after_request`, error handlers, and so on) exist only in `middleware.py`;
- import rules: no `from x import *`, only the launchers import `app`, no import cycles, route modules do not import each other (except the documented pairs), `helpers/` modules stay small leaf utilities, and `app.py` imports every `routes/*.py`;
- every script in `tools/` puts the project root on `sys.path` before its first project import;
- `manage.sh` launches only files that exist, and `bash -n manage.sh` passes;
- the route snapshot (below).

Exit code `1` means at least one check **FAIL**ed. A `SKIP` is not a pass of that check. `qa quick` runs `smoke.py` as well; use `smoke` on its own when you only want the quick answer.

**The route snapshot.** `tests/smoke_routes.json` lists every route (methods, URL and endpoint). Check 11 **fails** if a route in the snapshot has disappeared from the code (`LOST`), so a route cannot vanish unnoticed. Routes that are not in the snapshot yet only produce a warning (`11b`). Run `--save` after a green run when you added or removed a route **on purpose**, then commit the file. Before the first `--save`, check 11 is reported as `SKIP`.

- `--save` runs **all** the checks first and then saves the snapshot **even if one of them failed**, so read the report before you commit the file.
- **From the interactive menu (option 27)** it first warns, then asks `Save the route snapshot? [y/N]`. Saving after a route was lost by mistake would hide the loss, so Enter or `n` leaves the file unchanged and reminds you of the shell command. From the shell, `smoke --save` does not ask.

---

## security.txt Command

Edits `static/.well-known/security.txt` (RFC 9116).

```bash
./manage.sh security-txt        # interactive prompts (blank keeps the current value)
./manage.sh security-txt show   # print the current file
./manage.sh security-txt --contact you@example.com --expires 2030-09-03 --preferred-lang en,fil --canonical https://yourdomain.com/.well-known/security.txt
./manage.sh security-txt --expires-in-days 365    # change only Expires (365 days from now, UTC)
```

| Flag | Meaning |
|---|---|
| `--contact` | Email, or a `mailto:`, `https:`, or `tel:` URL. A bare email gets `mailto:` added |
| `--expires` | `YYYY-MM-DD`, or a full ISO datetime. A date-only value becomes `23:00:00.000Z` that day |
| `--expires-in-days N` | Relative expiry, computed in UTC |
| `--preferred-lang` | Comma-separated language codes (`--preferred-languages` also works) |
| `--canonical` | The public URL of the file |

Only the flags you pass are changed. Existing fields and any extra custom fields are kept. The file must end up with all four required fields (Contact, Expires, Preferred-Languages, Canonical), otherwise the script reports which are missing and writes nothing. Ctrl-C during the interactive prompts leaves the file untouched.

---

## Interactive Menu

```bash
./manage.sh menu
```

Shows whether a server is running, then a numbered list. Every number is the same as a shell command.

| # | Command | Group |
|---|---|---|
| 1 | `start server` | Servers |
| 2 | `start dev_server` | Servers |
| 3 | `stop` | Servers |
| 4 | `restart` | Servers |
| 5 | `status` | Servers |
| 6 | `logs` (asks which server and whether to follow) | Servers |
| 7 | `clean-logs` | Servers |
| 8 | `restart-webdav` | Servers |
| 9 | `version-manage` | Utilities |
| 10 | `config` | Utilities |
| 11 | `setup-smb` | Utilities |
| 12 | `kick-sessions` | Utilities |
| 13 | `manage-users` | Utilities |
| 14 | `reset-db` | Utilities |
| 15 | `setup-storage` | Utilities |
| 16 | `update-modules` | Utilities |
| 17 | `revoke-shares` | Utilities |
| 18 | `security-txt` | Utilities |
| 19 | `termux-setup` (shown dimmed when not on Termux) | Utilities |
| 20 | `validate-sri` (checks, then asks y/N before fixing) | Utilities |
| 21 | `qa quick` | Quality Assurance |
| 22 | `qa static` | Quality Assurance |
| 23 | `qa tests` | Quality Assurance |
| 24 | `qa layer` (asks which layer, default unit) | Quality Assurance |
| 25 | `qa ci` | Quality Assurance |
| 26 | `dir-tree` | Developer Tools |
| 27 | `smoke --save` (warns, then asks y/N) | Developer Tools |

Type `q` to quit. After each action it waits for Enter before redrawing.

**Ctrl-C in the menu:** during an action it cancels that action and returns to the menu. At the `Choose an option` prompt it quits cleanly.

---

## Files and Folders It Uses

| Path | Purpose |
|---|---|
| `.manage_pids/prod.pid`, `dev.pid` | PID of the running server |
| `.manage_pids/webdav.pid` | PID of the WebDAV process (written by the server, not by `manage.sh`) |
| `logs/prod_server_YYYY-MM-DD.log`, `logs/dev_server_YYYY-MM-DD.log` | One log per day per server type, written by the app's own logger. It rolls to a new file at midnight without a restart |
| `static/.well-known/security.txt` | Edited by `security-txt` |
| `templates/*.html`, `static/` | Read by `validate-sri`; the templates are rewritten only when you add `--fix` |
| `tests/qa.py` | The runner every `qa` command calls |
| `tests/dir_tree.py` | The tool `dir-tree` runs |
| `docs/DIRECTORY_TREE.md` | Written by `dir-tree` (overwritten each run; commit it after files change) |
| `tests/smoke.py` | The tool `smoke` runs (`qa` runs it too) |
| `tests/smoke_routes.json` | The route snapshot written by `smoke --save` (commit it) |
| `artifacts/` | JUnit XML written by `qa ci` (not committed; add it to `.gitignore`) |
| a temporary folder (system temp) | The scratch copy of the project the tests run in; removed by pytest afterwards |

Because background mode discards raw console output (see [Startup messages](#startup-messages-are-not-shown-in-background-mode)), the log files are where diagnostics live.

---

## How Background Mode and Ctrl-C Work

The server is launched as a fully detached process:

- **Windows:** new process group and no console, so it cannot receive Ctrl-C events.
- **Linux / Termux:** its own session, so it is immune to the terminal's Ctrl-C.
- **Inside the process:** Ctrl-C signals are ignored before the server script loads, so no framework can turn them back on.
- The environment variable `CLOUDINATOR_BG=1` is set so the servers know they are managed (the dev server turns off its auto-reloader).

The practical result: closing a log view or pressing Ctrl-C **never** stops the server. Only `./manage.sh stop` (or `restart`) does.

---

## WebDAV Is a Separate Process

WebDAV runs as its own operating-system process next to the main server, tracked by `.manage_pids/webdav.pid`. Killing the main server does not automatically kill it, so `stop` and `start` also clean it up:

1. Kill the process in `webdav.pid`.
2. Sweep the two WebDAV ports. Whatever is listening there is killed **only if it is a Python process**, so unrelated programs on those ports are left alone.

**Which ports:** `WEBDAV_PORT` and `WEBDAV_HTTPS_PORT` from `server_config.json` (the file `python config.py` saves to), otherwise the defaults **8080** and **8443**. The script reads that JSON file directly, and any problem (no file, unreadable file, a value that is not a valid port number) falls back to the default for that port, so this lookup can never break `stop`, `start` or `restart`. One limit: if you change a port only by editing the constant inside `config.py` and never save it through `python config.py`, `manage.sh` does not see it and still checks 8080 and 8443 (the normal PID-file cleanup still works).

If a stale process ever holds a port or a log file open (a common Windows complaint), running `./manage.sh stop` and `./manage.sh start server` again clears it.

---

## Environment Variable: PYTHON

By default the script uses `python` from your PATH, falling back to `python3`. To force a specific interpreter:

```bash
PYTHON=python3.11 ./manage.sh start server
```

This applies to the servers and every utility.

---

## Troubleshooting

| Symptom | What it means and what to do |
|---|---|
| `Launcher returned no PID` | The `python` the script found is not working. Check `python --version`, or set `PYTHON=...` |
| `crashed immediately` | The server died on startup (often an import error before logging began). Run `python prod_server.py` in the foreground to see the real error |
| `Only one server can run at a time` | The other server is running. Run `./manage.sh stop` first |
| `No log file found` | Nothing has been logged today for that server. Start it, or check the folder `logs/` |
| `No WebDAV PID file found` (restart-webdav) | WebDAV did not start. Check `WEBDAV_ENABLED` and `WEBDAV_HTTPS_ENABLED` in `config.py`, and the server log |
| `WebDAV did not come back within 10s` | The respawn failed. Read the server log for the actual error |
| `Script not found` | A utility file is missing from the project folder |
| A page loads but a script or stylesheet does nothing; console shows an integrity error | A stale SRI hash. Run `./manage.sh validate-sri --fix`, then reload (hard refresh) |
| `qa exited with code 1` | At least one step failed. Read the `FAIL` lines in the summary at the end, then the output of that step above it |
| `pytest is not installed` (from `qa`) | Run `python -m pip install -r requirements-dev.txt` |
| `qa` says `SKIP: node is not installed` | Not an error. Install Node.js if you want the JavaScript syntax check |
| `qa` reports a `layout` FAIL | A `test_*.py` file sits directly in `tests/`. Move it into `tests/unit/` or `tests/application/` |
| `smoke exited with code 1` | At least one smoke check FAILed. Read the `[FAIL]` lines in its report |
| `smoke` reports `[FAIL] 11 no route lost` with `LOST` lines | A route that is in `tests/smoke_routes.json` is gone from the code. If you removed it on purpose, run `./manage.sh smoke --save`; if not, put the route back |
| `smoke` reports `[WARN] 11b ... not in the snapshot` | New routes. Not an error; run `./manage.sh smoke --save` once you are sure they are intended |
| `smoke` reports `[SKIP] 11 route snapshot` | There is no `tests/smoke_routes.json` yet. Run `./manage.sh smoke --save` once after a green run |
| `smoke` reports `[SKIP] 2 pyflakes` | `pyflakes` is not installed. Run `python -m pip install pyflakes` (this is the check that finds missing imports) |
| `sri_validator exited with code 1` | `validate-sri` found a stale, missing or unresolvable hash. Read the report above it, then run with `--fix` |
| `Permission denied` running `./manage.sh` | Run `chmod +x manage.sh`, or use `bash manage.sh <command>` |
| `termux-setup` says Android-only | You are not on Termux. Follow the message for your platform |
| Windows: stale Python process locks a log file | Run `./manage.sh stop`, then start again. The script also clears leftover WebDAV processes on every start |

---

**See also:** [README](../README.md) · [Configuration Reference](./CONFIG_PY_REFERENCE.md) · [SMB Setup](./SMB_PROTOCOL_DEPLOYMENT.md) · [User Guide](./USER_GUIDE.md)