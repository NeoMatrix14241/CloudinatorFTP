# 🖥️ manage.sh — Server Management Script Guide

**Last Updated**: 2026-09-30
**Works on**: Windows (Git Bash), Linux, and Android (Termux)
**Checked against**: `manage.sh` itself (commands, menu numbers, and behaviour below are read from the script, not from memory)

`manage.sh` runs the Cloudinator server in the **background** so your terminal stays free, and gives you one entry point for the maintenance utilities (users, config, SMB, share links, version engine, and so on).

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Platform Notes (Windows / Linux / Termux)](#platform-notes)
3. [Server Commands](#server-commands)
4. [Log Commands](#log-commands)
5. [Utility Commands](#utility-commands)
6. [security.txt Command](#securitytxt-command)
7. [Interactive Menu](#interactive-menu)
8. [Files and Folders It Uses](#files-and-folders-it-uses)
9. [How Background Mode and Ctrl-C Work](#how-background-mode-and-ctrl-c-work)
10. [WebDAV Is a Separate Process](#webdav-is-a-separate-process)
11. [Environment Variable: PYTHON](#environment-variable-python)
12. [Troubleshooting](#troubleshooting)

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
| `version-manage` | `version_manage.py` | Version Engine: list, restore, delete file versions (no arguments opens its own menu) |
| `setup-smb` | `smb_setup.py` | One-time SMB setup (see `SMB_PROTOCOL_DEPLOYMENT.md`) |
| `kick-sessions` | `kick_sessions.py` | Force logout of every active session (server must be running) |
| `config` | `config.py` | Interactive configuration (see `CONFIG_PY_REFERENCE.md`) |
| `manage-users` | `manage_users.py` | Manage user credentials |
| `debug-pw` | `debug_passwords.py` | Debug passwords |
| `reset-db` | `reset_db.py` | Reset the database |
| `setup-storage` | `setup_storage.py` | Configure storage |
| `update-modules [-y]` | `setup_pymodules.sh` | Update Python packages (alias: `setup-modules`) |
| `revoke-shares` | `revoke_sharing.py` | Share link management |
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

Edit options: `--mode public|passkey|approval`, `--passkey KEY`, `--generate-passkey`, `--clear-passkey`, `--expires-in 1h|2d|30m|7d|SECONDS`, `--never-expire`.

### update-modules

```bash
./manage.sh update-modules        # asks before doing anything
./manage.sh update-modules -y     # skips that first question (for scripts)
```

It runs `setup_pymodules.sh`, which rewrites `requirements.txt` and `constraints.txt`, runs a pip dry-run to check the versions fit together, and asks once more before installing or upgrading. Ctrl-C at the first question cancels with nothing changed.

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

| # | Command | # | Command |
|---|---|---|---|
| 1 | `start server` | 11 | `setup-smb` |
| 2 | `start dev_server` | 12 | `kick-sessions` |
| 3 | `stop` | 13 | `manage-users` |
| 4 | `restart` | 14 | `debug-pw` |
| 5 | `status` | 15 | `reset-db` |
| 6 | `logs` (asks which server and whether to follow) | 16 | `setup-storage` |
| 7 | `clean-logs` | 17 | `update-modules` |
| 8 | `restart-webdav` | 18 | `revoke-shares` |
| 9 | `version-manage` | 19 | `security-txt` |
| 10 | `config` | 20 | `termux-setup` (shown dimmed when not on Termux) |

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

Because background mode discards raw console output (see below), the log files are where diagnostics live. Console banners that `print()` at startup are only visible if you run the server in the foreground (`python prod_server.py`).

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
2. Sweep ports **8080 and 8443**. Whatever is listening there is killed **only if it is a Python process**, so unrelated programs on those ports are left alone.

Note that this sweep uses the fixed ports 8080 and 8443. If you changed the WebDAV ports in `config.py`, the PID file is what cleans up your custom ports. If a stale process ever holds a port or a log file open (a common Windows complaint), running `./manage.sh stop` and `./manage.sh start server` again clears it.

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
| `Permission denied` running `./manage.sh` | Run `chmod +x manage.sh`, or use `bash manage.sh <command>` |
| `termux-setup` says Android-only | You are not on Termux. Follow the message for your platform |
| Windows: stale Python process locks a log file | Run `./manage.sh stop`, then start again. The script also clears leftover WebDAV processes on every start |

---

**See also:** [README](../README.md) · [Configuration Reference](./CONFIG_PY_REFERENCE.md) · [SMB Setup](./SMB_PROTOCOL_DEPLOYMENT.md) · [User Guide](./USER_GUIDE.md)