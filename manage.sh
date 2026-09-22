#!/usr/bin/env bash
# =============================================================================
#  manage.sh — Cloudinator Server & Utility Management
# =============================================================================

set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use whatever 'python' resolves to in PATH (your system env var).
# Override any time:  PYTHON=python3.11 ./manage.sh start server
if [[ -z "${PYTHON:-}" ]]; then
	if command -v python &>/dev/null; then
		PYTHON="python"
	elif command -v python3 &>/dev/null; then
		PYTHON="python3"
	else
		PYTHON="python"
	fi
fi

PID_DIR="${SCRIPT_DIR}/.manage_pids"
LOG_DIR="${SCRIPT_DIR}/logs"

# ── Colours ───────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
	# ANSI-C quoting ($'...') stores REAL escape bytes, not the 4 literal
	# characters \033. `echo -e` was hiding this, but `cat <<EOF` (cmd_help)
	# printed "\033[1m" as plain text.
	RED=$'\033[0;31m' GREEN=$'\033[0;32m' YELLOW=$'\033[1;33m'
	BLUE=$'\033[0;34m' CYAN=$'\033[0;36m' BOLD=$'\033[1m'
	DIM=$'\033[2m' NC=$'\033[0m'
else
	RED='' GREEN='' YELLOW='' BLUE='' CYAN='' BOLD='' DIM='' NC=''
fi

# ── Print helpers ─────────────────────────────────────────────────────────────
info() { echo -e "${BLUE}  ➜ ${NC}$*"; }
success() { echo -e "${GREEN}  ✔ ${NC}$*"; }
warn() { echo -e "${YELLOW}  ⚠ ${NC}$*"; }
error() { echo -e "${RED}  ✖ ${NC}$*" >&2; }
header() { echo -e "\n${BOLD}${CYAN}$*${NC}"; }
divider() { echo -e "${DIM}──────────────────────────────────────────────────${NC}"; }

# Yes/no prompt. Ctrl-C, Ctrl-D or a closed stdin all count as "no" instead of
# killing the script.   usage: _confirm "Do the thing?" || return 0
_confirm() {
	local ans=""
	read -rp "  $1 [y/N]: " ans || {
		echo ""
		return 1
	}
	[[ "$ans" =~ ^[Yy]([Ee][Ss])?$ ]]
}

# Free-text prompt into a variable. Returns 1 on Ctrl-C / Ctrl-D / EOF so the
# caller can cancel cleanly.   usage: _ask VAR "prompt: " || return 130
_ask() {
	local __ans=""
	read -rp "$2" __ans || {
		echo ""
		return 1
	}
	printf -v "$1" '%s' "$__ans"
}

# ── Platform helpers ──────────────────────────────────────────────────────────
is_windows() {
	[[ "$OSTYPE" == msys* ]] || [[ "$OSTYPE" == cygwin* ]]
}

is_termux() {
	[[ -d "/data/data/com.termux" ]] || command -v termux-setup-storage &>/dev/null 2>&1
}

# ── Name / path helpers ───────────────────────────────────────────────────────
pid_file_for() {
	case "$1" in
	prod) echo "${PID_DIR}/prod.pid" ;;
	dev) echo "${PID_DIR}/dev.pid" ;;
	*)
		error "Unknown type: $1"
		exit 1
		;;
	esac
}

# WebDAV runs as its own OS process (see protocol_manager.py), separate
# from the main server process this script tracks in prod.pid/dev.pid.
# protocol_manager.py writes its real PID here on every (re)spawn.
webdav_pid_file() {
	echo "${PID_DIR}/webdav.pid"
}

script_for() {
	case "$1" in
	prod) echo "prod_server.py" ;;
	dev) echo "dev_server.py" ;;
	*)
		error "Unknown type: $1"
		exit 1
		;;
	esac
}

# Map user-facing names → internal keys (also accepts internal keys for safety)
normalize_type() {
	case "$1" in
	server | prod) echo "prod" ;;
	dev_server | dev) echo "dev" ;;
	*)
		error "Unknown server: '${1}'. Use 'server' or 'dev_server'"
		exit 1
		;;
	esac
}

# Map internal keys → user-facing names (for hints / messages)
display_name_for() {
	case "$1" in
	prod) echo "server" ;;
	dev) echo "dev_server" ;;
	esac
}

# ── Log path helper ───────────────────────────────────────────────────────────
# The log file is now fully deterministic from type + today's date — it's
# the SAME file logging_setup.py's DailyDatedFileHandler is writing to from
# inside the Python process (app.py/prod_server.py/protocol_manager.py all
# funnel their logger output there). No more per-start timestamped files or
# a .logpath tracking file to keep in sync — "today's file for this type"
# is always just this one computation, whether the server has been running
# for five minutes or five days.
# Example: logs/prod_server_2026-09-15.log
current_log_for() {
	local type="$1"
	echo "${LOG_DIR}/${type}_server_$(date '+%Y-%m-%d').log"
}

# ── Process helpers ───────────────────────────────────────────────────────────
# Read a PID file and return ONLY its digits. Windows tools (python's print(),
# netstat, powershell) end lines with \r\n; a stray \r on the PID made
# `tasklist //FI "PID eq 1234\r"` match nothing, so a perfectly healthy
# server looked like it "crashed immediately".
read_pid() {
	local raw=""
	if [[ -f "$1" ]]; then
		raw=$(<"$1") || raw=""
	fi
	printf '%s' "${raw//[^0-9]/}"
}

is_running() {
	local pid_file="$1"
	[[ -f "$pid_file" ]] || return 1
	local pid
	pid=$(read_pid "$pid_file")
	[[ -n "$pid" ]] || return 1

	if is_windows; then
		# We store the real Windows PID; tasklist is the reliable check on Windows.
		tasklist //FI "PID eq ${pid}" //NH 2>/dev/null | grep -qi "python" || return 1
	else
		kill -0 "$pid" 2>/dev/null || return 1
	fi
}

active_server() {
	if is_running "$(pid_file_for prod)"; then
		echo "prod"
	elif is_running "$(pid_file_for dev)"; then
		echo "dev"
	else
		echo ""
	fi
}

ensure_dirs() {
	mkdir -p "$PID_DIR" "$LOG_DIR"
}

# ── Detached launcher ─────────────────────────────────────────────────────────
# Starts a Python script in a FULLY DETACHED process so Ctrl-C from any
# terminal window can NEVER reach the server.  Two layers of protection:
#
#   Layer 1 — process group / console isolation
#     Windows : CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
#               (process has no console → can't receive Ctrl-C events)
#     Linux / Termux : os.setsid()
#               (new session → new process group → immune to terminal SIGINT)
#
#   Layer 2 — signal handler hardening inside the child
#     The child is launched as `python -c <wrapper>` which sets
#     signal.SIGINT = SIG_IGN *before* importing or running the server
#     script.  This defeats any framework (Flask/Quart reloader, Werkzeug,
#     Hypercorn) that might otherwise reinstall its own SIGINT handler.
#     The env var CLOUDINATOR_BG=1 tells dev_server.py to disable
#     use_reloader (the reloader spawns a watchdog subprocess that has
#     its own signal wiring and can't be silenced any other way).
#
# Prints the real native PID (Windows PID on Windows, Unix PID elsewhere).
#
# stdout+stderr both -> /dev/null (2026-09-15, final iteration — this went
# through two earlier variants same day: devnull-stdout/file-stderr, then
# full dual capture into log_path, before landing here). Nothing from this
# process's raw output is captured by manage.sh anymore, on purpose: this
# is now a pure-Python-logger setup. logging_setup.py's DailyDatedFileHandler
# writes every structured log line directly to logs/{type}_server_YYYY-MM-DD.log
# from inside the process (app.py's request logger, Hypercorn's errorlog,
# protocol_manager's logger), with correct midnight rotation. Uncaught
# exceptions — main thread and background threads both — are caught by
# logging_setup.py's sys.excepthook/threading.excepthook and logged
# through that same mechanism, so crash tracebacks get the same correct
# rotation too, without needing any OS-level redirect. current_log_for()
# below computes that same file path independently, which is what
# `manage.sh logs -f` tails — so following logs still works exactly the
# same as before; only the (redundant, duplicate-line-causing) raw
# redirect capture is gone. Remaining plain print() calls not yet
# converted to logger calls (the ~267 across the project — see CLAUDE.md)
# are genuinely unobserved output in background mode now; convert them to
# logger calls if/when they turn out to matter.
_launch_detached() {
	local script_path="$1"

	local tmp
	tmp=$(mktemp "${TMPDIR:-/tmp}/manage_launcher_XXXXXX")

	cat >"$tmp" <<'PYEOF'
import subprocess, sys, os

script_path = sys.argv[1]

# ── env for the child ────────────────────────────────────────────────────────
env = dict(os.environ)
env['PYTHONUTF8']          = '1'
# CLOUDINATOR_BG=1 → server scripts know they are a managed BG service:
#   - dev_server.py disables use_reloader (reloader can't run detached)
#   - both scripts skip their "Press Ctrl+C to stop" messaging
env['CLOUDINATOR_BG']      = '1'
# _CLOUDINATOR_SCRIPT is read by the inline wrapper below
env['_CLOUDINATOR_SCRIPT'] = script_path

# ── inline wrapper run inside the child process ──────────────────────────────
# Ignores SIGINT (and SIGBREAK on Windows) at OS level before the server
# script is imported, so no framework can reinstate Ctrl-C sensitivity.
# Uses runpy.run_path so __file__, __name__ == '__main__' etc. are correct.
wrapper = "\n".join([
    "import signal, sys, os, runpy",
    "signal.signal(signal.SIGINT, signal.SIG_IGN)",
    "if hasattr(signal, 'SIGBREAK'): signal.signal(signal.SIGBREAK, signal.SIG_IGN)",
    "s = os.environ['_CLOUDINATOR_SCRIPT']",
    "sys.argv = [s]",
    "sys.path.insert(0, os.path.dirname(os.path.abspath(s)))",
    "runpy.run_path(s, run_name='__main__')",
])

# ── platform detach flags ────────────────────────────────────────────────────
kw = {'env': env, 'stdin': subprocess.DEVNULL}
if sys.platform == 'win32':
    kw['creationflags'] = (
        subprocess.CREATE_NEW_PROCESS_GROUP |
        subprocess.DETACHED_PROCESS
    )
else:
    kw['preexec_fn'] = os.setsid
    kw['close_fds']  = True

with open(os.devnull, 'w') as devnull:
    p = subprocess.Popen(
        [sys.executable, '-c', wrapper],
        stdout=devnull, stderr=devnull,
        **kw
    )

print(p.pid)
sys.exit(0)
PYEOF

	# `|| true`: under `set -e` a failing launcher (python missing, bad path)
	# used to kill manage.sh silently right here; now the caller sees an empty
	# PID and prints a real error message instead.
	local pid err="${tmp}.err"
	pid=$("$PYTHON" "$tmp" "$script_path" 2>"$err") || true
	pid="${pid//[^0-9]/}" # digits only (strip Windows \r)
	if [[ -z "$pid" && -s "$err" ]]; then
		sed 's/^/    launcher: /' "$err" >&2 || true
	fi
	rm -f "$tmp" "$err"
	echo "$pid"
}

# ── Log follower ─────────────────────────────────────────────────────────────
# Uses a Python-based follower instead of `tail -f`.
# Reason: on Windows (Git Bash), `tail -f` does not reliably release the
# terminal on Ctrl-C — it leaves the shell stuck waiting for it to exit.
# The Python follower catches KeyboardInterrupt cleanly and exits on its own,
# so Ctrl-C always returns you to the prompt with the server still running.
_follow_log() {
	local log="$1"
	# `trap ':' INT` (handled) instead of `trap '' INT` (ignored): an IGNORED
	# signal is inherited by children, and Python leaves an inherited SIG_IGN
	# alone -- so on Linux/Termux Ctrl-C could never detach the follower.
	# A handled trap keeps manage.sh alive AND resets to default in the child.
	trap ':' INT

	# Python reads from stdin (-), log path is argv[1].
	# 'PYEOF' (quoted) prevents bash expanding anything inside the heredoc.
	"$PYTHON" - "$log" <<'PYEOF'
import sys, time, collections

log_path   = sys.argv[1]
TAIL_LINES = 20          # lines of history shown before following live output

try:
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        # Replay the last TAIL_LINES lines without loading the whole file.
        # deque(f, maxlen=N) reads line-by-line and keeps only the last N;
        # the file pointer ends up at EOF, so readline() below picks up from there.
        buf = collections.deque(f, maxlen=TAIL_LINES)
        for line in buf:
            print(line, end="", flush=True)

        # Follow new content as it arrives
        while True:
            line = f.readline()
            if line:
                print(line, end="", flush=True)
            else:
                time.sleep(0.1)     # poll every 100 ms

except KeyboardInterrupt:
    pass                            # clean exit, no traceback
except OSError as e:
    print(f"\n[log follower] {e}", file=sys.stderr)
PYEOF

	trap - INT # restore default signal handling
}

# ── cmd_start ─────────────────────────────────────────────────────────────────
cmd_start() {
	local raw="${1:-}"
	if [[ -z "$raw" ]]; then
		error "Specify a server:  start server  or  start dev_server"
		return 1
	fi
	local type
	type=$(normalize_type "$raw") || return 1

	# ── Mutual exclusion ──
	local other
	other=$(active_server)
	if [[ -n "$other" ]]; then
		if [[ "$other" == "$type" ]]; then
			local pid uptime_str log
			pid=$(read_pid "$(pid_file_for "$type")")
			if is_windows; then
				uptime_str="running"
			else
				uptime_str=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ') || uptime_str="unknown"
			fi
			log=$(current_log_for "$type")
			header "Already Running"
			divider
			echo -e "  ${GREEN}● RUNNING${NC}  ${BOLD}$(script_for "$type")${NC}"
			echo -e "             ${DIM}PID    :${NC} ${pid}"
			echo -e "             ${DIM}Uptime :${NC} ${uptime_str}"
			echo -e "             ${DIM}Log    :${NC} $(basename "$log")"
			divider
			echo ""
			info "Follow logs:  ./manage.sh logs $(display_name_for "$type") -f"
			info "Stop server:  ./manage.sh stop"
			info "Restart:      ./manage.sh restart"
			return 0
		else
			header "Already Running"
			divider
			echo -e "  ${YELLOW}⚠ ${BOLD}$(script_for "$other")${NC} is already running (PID $(read_pid "$(pid_file_for "$other")"))."
			echo -e "    Only one server can run at a time."
			divider
			echo ""
			info "Stop it first:   ./manage.sh stop"
			info "Then run:        ./manage.sh start $(display_name_for "$type")"
			return 1
		fi
	fi

	ensure_dirs

	# Defensive cleanup (2026-09-15) — catches a WebDAV orphan left behind
	# by a crash, a stop that predates this fix, or anything else that
	# left webdav.pid stale/missing, before it can lock out this start's
	# own WebDAV spawn (port conflict) or its log file (see
	# _kill_webdav_child's own comment for the full story). Safe to call
	# unconditionally — a no-op when nothing's actually orphaned.
	_kill_webdav_child

	local script pid_file log
	script=$(script_for "$type")
	pid_file=$(pid_file_for "$type")
	log=$(current_log_for "$type")

	if [[ ! -f "${SCRIPT_DIR}/${script}" ]]; then
		error "Script not found: ${SCRIPT_DIR}/${script}"
		return 1
	fi

	info "Starting ${BOLD}${script}${NC} in the background…"
	info "Python  → ${PYTHON}  ($(${PYTHON} --version 2>&1))"
	info "Log     → ${log}"

	local pid
	pid=$(_launch_detached "${SCRIPT_DIR}/${script}")

	if [[ -z "$pid" ]]; then
		error "Launcher returned no PID — is '${PYTHON}' a working Python? (see the launcher line above)"
		return 1
	fi

	echo "$pid" >"$pid_file"

	# Brief pause to catch immediate crashes
	sleep 0.8

	if is_running "$pid_file"; then
		success "${script} started  (PID ${BOLD}${pid}${NC})"
		echo ""
		info "Logs saved to: ${DIM}${log}${NC}"
		echo ""
		info "Utilities:   ./manage.sh config | manage-users | debug-pw | reset-db"
		info "Follow logs: ./manage.sh logs $(display_name_for "$type") -f"
		info "Stop server: ./manage.sh stop"
	else
		rm -f "$pid_file"
		error "${script} crashed immediately."
		if [[ -f "$log" ]]; then
			error "Check the log: ${log}"
		else
			error "No log was written (it died before logging started, e.g. an import error)."
		fi
		info "See the real error by running it in the foreground:  ${PYTHON} ${script}"
		return 1
	fi
}

# ── WebDAV child cleanup ─────────────────────────────────────────────────────
# WebDAV runs as its OWN OS process (see protocol_manager.py), a child of
# the main server process but tracked under its own PID/pidfile — killing
# the main PID (below) does NOT touch it: `taskkill //F //PID` has no `//T`
# (kill-tree) flag, and plain `kill "$pid"`/SIGTERM on POSIX only signals
# that one PID, not its children, even though _launch_detached put the main
# process in its own session via os.setsid(). Left uncleaned, that orphaned
# WebDAV process keeps its port bound (and, once running, its own log file
# handle open) — every subsequent `start` then spawns a brand-new WebDAV
# subprocess that immediately fails to bind (port already in use) and exits
# 1, which protocol_manager.py's watchdog dutifully respawns every 3s
# forever, always failing the same way, since the real occupant of the port
# is never touched. Same escalation (kill → wait → SIGKILL) as
# cmd_restart_webdav below, extracted here so both call sites share it.
#
# Port-based fallback added 2026-09-15: the pidfile-based kill above only
# works when webdav.pid is accurate, and it's been observed pointing at an
# already-dead PID while the REAL orphan (predating this fix, or from a
# crash, or anything else that desynced the pidfile) keeps holding the
# port and its log file handle open — the "stale python process locking
# the log file, have to kill it in Task Manager" symptom. Rather than
# trust the pidfile alone, this now also actively finds whatever's bound
# to WebDAV's ports (8080/8443, matching protocol_manager.py's own
# _webdav_target_ports() fallback) and kills that directly — a no-op on
# any port nothing is actually listening on. Called both from cmd_stop
# and defensively from cmd_start before spawning, so this self-heals
# without needing a manual netstat/taskkill step going forward.
_kill_webdav_child() {
	local pf pid
	pf=$(webdav_pid_file)
	if [[ -f "$pf" ]]; then
		pid=$(read_pid "$pf")
		if [[ -n "$pid" ]]; then
			if is_windows; then
				taskkill //F //PID "$pid" &>/dev/null || true
			else
				kill "$pid" 2>/dev/null || true
				local i=0
				while kill -0 "$pid" 2>/dev/null && ((i < 10)); do
					sleep 0.5
					i=$((i + 1)) # post-increment form returns status 1 on the first pass, which set -e treats as failure
				done
				if kill -0 "$pid" 2>/dev/null; then
					kill -9 "$pid" 2>/dev/null || true
				fi
			fi
		fi
		rm -f "$pf"
	fi

	# Port-based fallback sweep (2026-09-15) — the pidfile-based kill above
	# only works when webdav.pid is accurate. It's been observed pointing
	# at an already-dead PID while the REAL orphan (from an earlier crash,
	# or a stop that predates this fix, or any other way the pidfile could
	# get out of sync) keeps holding the port — and, once running, its log
	# file handle — open indefinitely. That's the "stale python process
	# locking the log file, have to kill it in Task Manager" symptom.
	# Rather than trust the pidfile at all, actively find whatever's bound
	# to WebDAV's ports and kill that directly — matches the ports
	# protocol_manager.py's own _webdav_target_ports() checks
	# (WEBDAV_PORT/WEBDAV_HTTPS_PORT from config.py, falling back to
	# 8080/8443 same as that function does). Harmless no-op on every port
	# nothing is actually listening on.
	#
	# !! Every lookup below ends in `|| true` on purpose. With `set -eo
	# pipefail`, "nothing is listening on this port" makes grep/lsof exit 1,
	# which fails the whole pipeline AND the assignment — and set -e then
	# killed manage.sh silently, so `./manage.sh start server` (and `stop`,
	# `restart`) printed nothing and exited 1 whenever WebDAV wasn't orphaned.
	#
	# Safety: only ever kill a *python* process — never whatever unrelated
	# program happens to be listening on 8080/8443.
	local port webdav_pid
	for port in 8080 8443; do
		webdav_pid=""
		if is_windows; then
			webdav_pid=$(netstat -ano 2>/dev/null | tr -d '\r' | grep ":${port} " | grep LISTENING | awk '{print $NF}' | head -1) || true
		elif command -v lsof &>/dev/null; then
			webdav_pid=$(lsof -ti tcp:"${port}" -sTCP:LISTEN 2>/dev/null | head -1) || true
		fi
		webdav_pid="${webdav_pid//[^0-9]/}"
		if [[ -n "$webdav_pid" && "$webdav_pid" != "0" ]] && _pid_is_python "$webdav_pid"; then
			if is_windows; then
				taskkill //F //PID "$webdav_pid" &>/dev/null || true
			else
				kill -9 "$webdav_pid" 2>/dev/null || true
			fi
		fi
	done
	return 0
}

# True only if PID belongs to a python process (guards the port sweep above).
_pid_is_python() {
	local pid="$1"
	if is_windows; then
		tasklist //FI "PID eq ${pid}" //NH 2>/dev/null | grep -qi "python"
	else
		ps -o comm= -p "$pid" 2>/dev/null | grep -qi "python"
	fi
}

# ── cmd_stop ──────────────────────────────────────────────────────────────────
cmd_stop() {
	local type
	type=$(active_server)

	if [[ -z "$type" ]]; then
		warn "No server is currently running."
		return 0
	fi

	local pid_file pid script
	pid_file=$(pid_file_for "$type")
	pid=$(read_pid "$pid_file")
	script=$(script_for "$type")

	info "Stopping ${BOLD}${script}${NC} (PID ${pid})…"

	if is_windows; then
		# taskkill with the real Windows PID — immediate and reliable
		taskkill //F //PID "$pid" &>/dev/null ||
			kill -9 "$pid" 2>/dev/null ||
			true
		sleep 0.3
	else
		kill "$pid" 2>/dev/null || true
		local i=0
		while kill -0 "$pid" 2>/dev/null && ((i < 10)); do
			sleep 0.5
			i=$((i + 1))
		done
		if kill -0 "$pid" 2>/dev/null; then
			warn "Process did not exit gracefully — sending SIGKILL…"
			kill -9 "$pid" 2>/dev/null || true
		fi
	fi

	rm -f "$pid_file"

	# Clean up the orphaned WebDAV child — see _kill_webdav_child above.
	_kill_webdav_child

	success "${script} stopped."
}

# ── cmd_restart ───────────────────────────────────────────────────────────────
cmd_restart() {
	local type
	type=$(active_server)
	if [[ -z "$type" ]]; then
		warn "No server is running. Use:  ./manage.sh start server|dev_server"
		return 1
	fi
	info "Restarting ${BOLD}$(script_for "$type")${NC}…"
	cmd_stop
	sleep 0.5
	cmd_start "$(display_name_for "$type")"
}

# ── cmd_restart_webdav ───────────────────────────────────────────────────────
# Recovers a wedged-but-alive WebDAV listener (e.g. the Hypercorn/asyncio
# write-retry loop after a large cancelled download — see webdav_server.py's
# module docstring) WITHOUT restarting the main server. WebDAV runs as its
# own OS process; this kills that process directly by PID and relies on the
# watchdog thread inside the already-running server process (prod_server.py
# via protocol_manager.py) to notice the exit and respawn it automatically —
# this script can't call protocol_manager.restart_webdav() itself, since
# that function only knows about the Popen handle held in the SERVER's
# memory, not in this separate manage.sh process.
cmd_restart_webdav() {
	local type
	type=$(active_server)
	if [[ -z "$type" ]]; then
		error "No server is running — WebDAV only runs alongside a started server."
		return 1
	fi

	local pf
	pf=$(webdav_pid_file)
	if [[ ! -f "$pf" ]]; then
		warn "No WebDAV PID file found — it may not have started (check config.py's"
		warn "WEBDAV_ENABLED / WEBDAV_HTTPS_ENABLED, or the server's log)."
		return 1
	fi

	local old_pid
	old_pid=$(read_pid "$pf")
	if [[ -z "$old_pid" ]]; then
		error "WebDAV PID file is empty: ${pf}"
		return 1
	fi

	info "Restarting WebDAV (PID ${old_pid})… main server keeps running unaffected."

	if is_windows; then
		taskkill //F //PID "$old_pid" &>/dev/null || true
	else
		kill "$old_pid" 2>/dev/null || true
		local i=0
		while kill -0 "$old_pid" 2>/dev/null && ((i < 10)); do
			sleep 0.5
			i=$((i + 1))
		done
		if kill -0 "$old_pid" 2>/dev/null; then
			warn "WebDAV did not exit gracefully — sending SIGKILL…"
			kill -9 "$old_pid" 2>/dev/null || true
		fi
	fi

	# The running server's watchdog thread respawns WebDAV automatically —
	# poll the PID file for a new (different) PID to confirm it happened.
	info "Waiting for the server's watchdog to respawn WebDAV…"
	local i=0
	local new_pid=""
	while ((i < 20)); do
		sleep 0.5
		if [[ -f "$pf" ]]; then
			new_pid=$(read_pid "$pf")
			if [[ -n "$new_pid" ]] && [[ "$new_pid" != "$old_pid" ]]; then
				break
			fi
		fi
		i=$((i + 1))
	done

	if [[ -n "$new_pid" ]] && [[ "$new_pid" != "$old_pid" ]]; then
		success "WebDAV restarted (new PID ${new_pid})."
	else
		error "WebDAV did not come back within 10s — check the server log"
		error "(./manage.sh logs $(display_name_for "$type") ) for the actual failure."
		return 1
	fi
}

# ── cmd_status ────────────────────────────────────────────────────────────────
cmd_status() {
	header "Server Status"
	divider

	for type in prod dev; do
		local script pid_file label
		script=$(script_for "$type")
		pid_file=$(pid_file_for "$type")
		label="${BOLD}${script}${NC}"

		if is_running "$pid_file"; then
			local pid uptime_str log
			pid=$(read_pid "$pid_file")
			if is_windows; then
				uptime_str="running"
			else
				uptime_str=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ') || uptime_str="unknown"
			fi
			log=$(current_log_for "$type")
			echo -e "  ${GREEN}● RUNNING${NC}  ${label}  ${DIM}(PID ${pid}  uptime ${uptime_str})${NC}"
			echo -e "             ${DIM}Log: $(basename "$log")${NC}"
		else
			echo -e "  ${DIM}○ stopped${NC}  ${label}"
		fi
	done

	divider

	local active
	active=$(active_server)
	if [[ -n "$active" ]]; then
		local active_log
		active_log=$(current_log_for "$active")
		if [[ -n "$active_log" ]] && [[ -f "$active_log" ]]; then
			echo ""
			info "Last 5 lines of $(basename "$active_log"):"
			echo ""
			tail -n 5 "$active_log" | sed 's/^/    /' || true
			echo ""
		fi
	fi
}

# ── cmd_logs ──────────────────────────────────────────────────────────────────
cmd_logs() {
	local raw="${1:-}"
	local follow=false

	shift || true
	for arg in "$@"; do
		[[ "$arg" == "-f" ]] && follow=true
	done

	local type
	if [[ -z "$raw" ]]; then
		type=$(active_server)
		if [[ -z "$type" ]]; then
			error "No server running. Specify one:  logs server|dev_server  [-f]"
			return 1
		fi
	else
		type=$(normalize_type "$raw") || return 1
	fi

	local log
	log=$(current_log_for "$type")

	if [[ -z "$log" ]] || [[ ! -f "$log" ]]; then
		warn "No log file found for $(display_name_for "$type")."
		return 0
	fi

	if $follow; then
		info "Following $(basename "$log") — ${BOLD}Ctrl-C${NC} to detach (server keeps running)"
		divider
		_follow_log "$log"
		divider
		if is_running "$(pid_file_for "$type")"; then
			success "Detached. Server still running."
		else
			warn "Server is no longer running."
		fi
	else
		info "Last 50 lines of $(basename "$log"):"
		echo ""
		tail -n 50 "$log"
	fi
}

# ── cmd_clean_logs ────────────────────────────────────────────────────────────
cmd_clean_logs() {
	header "Clean Logs"
	divider

	local files=()
	local f
	while IFS= read -r f; do
		[[ -n "$f" ]] && files+=("$f")
	done < <(ls -t "${LOG_DIR}/"*_server_*.log 2>/dev/null || true)

	if [[ ${#files[@]} -eq 0 ]]; then
		info "No log files found in ${LOG_DIR}/"
		return 0
	fi

	echo "  Log files (newest first):"
	echo ""
	for f in "${files[@]}"; do
		local size
		size=$(du -sh "$f" 2>/dev/null | cut -f1)
		printf "    %-8s  %s\n" "$size" "$(basename "$f")"
	done
	echo ""

	local active
	active=$(active_server)
	local active_log=""
	if [[ -n "$active" ]]; then
		active_log=$(current_log_for "$active")
		warn "Server is running. Its current log will be kept: $(basename "$active_log")"
		echo ""
	fi

	divider
	read -rp "  Delete all old log files? [y/N]: " confirm
	if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
		info "Cancelled — no files deleted."
		return 0
	fi

	local deleted=0
	for f in "${files[@]}"; do
		if [[ -n "$active_log" ]] && [[ "$f" == "$active_log" ]]; then
			info "Keeping active log: $(basename "$f")"
			continue
		fi
		rm -f "$f"
		((deleted++)) || true
	done

	success "Deleted ${deleted} log file(s)."
}

# ── Utility runners ───────────────────────────────────────────────────────────
# One place that turns an exit code into a message. 130 = 128 + SIGINT, i.e.
# the operator pressed Ctrl-C — that's a cancel, not a failure.
_report_exit() {
	local name="$1" ec="$2"
	if ((ec == 0)); then
		success "${name} finished."
	elif ((ec == 130)); then
		warn "${name} interrupted (Ctrl-C)."
	else
		error "${name} exited with code ${ec}."
	fi
}

# About `trap ':' INT` in the two runners below (it used to be `trap '' INT`):
#   '' = IGNORE the signal. Ignored signals are inherited by child processes,
#        so the script being run could not be interrupted at all on Linux/
#        Termux, and a child *bash* script (setup_pymodules.sh) was not even
#        allowed to install its own Ctrl-C trap ("signals ignored on entry
#        cannot be trapped"). That is why Ctrl-C used to skip one pip call and
#        let setup_pymodules.sh carry on to the next step.
#   ':' = HANDLE the signal (do nothing). manage.sh still survives Ctrl-C, but
#        the child starts with the default disposition, so it really stops.
run_utility() {
	local script="$1"
	shift
	if [[ ! -f "${SCRIPT_DIR}/${script}" ]]; then
		error "Script not found: ${SCRIPT_DIR}/${script}"
		return 1
	fi
	header "Running ${script}"
	divider
	trap ':' INT
	# IMPORTANT: this must be `cmd || ec=$?`, not `cmd; local ec=$?`.
	# Under `set -e`, a bare failing command aborts the ENTIRE manage.sh
	# process on the spot — execution never reaches the next line, so
	# `local ec=$?`, `trap - INT`, and the success/error message below all
	# get skipped, and control never returns to the menu loop. Every Python
	# utility here (including revoke_sharing.py) is expected to exit
	# non-zero on cancelled/failed actions, so this isn't a rare edge case —
	# it fires on ordinary use. Making the command the LHS of `||` puts it
	# in a tested context, which `set -e` explicitly exempts, so a failure
	# is captured into `ec` instead of killing the shell.
	local ec=0
	"$PYTHON" "${SCRIPT_DIR}/${script}" "$@" || ec=$?
	trap - INT # restore default signal handling
	divider
	_report_exit "${script%.py}" "$ec"
	return $ec
}

run_bash_script() {
	local script="$1"
	shift
	if [[ ! -f "${SCRIPT_DIR}/${script}" ]]; then
		error "Script not found: ${SCRIPT_DIR}/${script}"
		return 1
	fi
	header "Running ${script}"
	divider
	trap ':' INT # handled, not ignored — see the note above run_utility()
	# See the comment in run_utility() above — same `set -e` hazard, same fix.
	local ec=0
	bash "${SCRIPT_DIR}/${script}" "$@" || ec=$?
	trap - INT # restore default signal handling
	divider
	_report_exit "${script}" "$ec"
	return $ec
}

# ── cmd_termux_setup ──────────────────────────────────────────────────────────
cmd_termux_setup() {
	if ! is_termux; then
		header "Termux Setup"
		divider
		if is_windows; then
			warn "termux_setup.sh is for Android (Termux) only."
			echo ""
			info "For Windows: install Python from https://python.org"
			info "Then run:    pip install -r requirements.txt"
		else
			warn "termux_setup.sh is for Android (Termux) only."
			echo ""
			info "For Linux: see LINUX_DEPLOYMENT.md for installation steps."
		fi
		return 1
	fi
	run_bash_script "termux_setup.sh"
}

# ── cmd_setup_modules ────────────────────────────────────────────────────────
# Asks for confirmation BEFORE launching setup_pymodules.sh — it rewrites
# requirements.txt/constraints.txt, may relaunch itself elevated on Windows, and
# can upgrade packages. Ctrl-C at this prompt (or answering n) cancels and
# changes nothing.   -y / --yes skips the question for scripted use.
cmd_setup_modules() {
	local assume_yes=false arg
	for arg in "$@"; do
		case "$arg" in
		-y | --yes) assume_yes=true ;;
		*)
			error "Unknown option: ${arg}"
			info "Usage: ./manage.sh update-modules [-y|--yes]"
			return 1
			;;
		esac
	done

	header "Setup / Update Python Packages"
	divider
	info "setup_pymodules.sh will:"
	echo "     • rewrite requirements.txt and constraints.txt"
	echo "     • run a pip dry-run to check the versions can be resolved together"
	echo "     • ask once more before it installs or upgrades anything"
	if is_windows; then
		warn "On Windows it relaunches itself as Administrator (UAC prompt) and adds"
		warn "a Windows Defender exclusion for your Python folder."
	fi
	divider

	if ! $assume_yes; then
		if ! _confirm "Run setup_pymodules.sh now?"; then
			info "Cancelled — nothing was changed."
			return 0
		fi
	fi
	run_bash_script "setup_pymodules.sh"
}

# ── security.txt (static/.well-known/security.txt, RFC 9116) ──────────────────
# Fields supported: Contact, Expires, Preferred-Languages, Canonical.
# Existing fields are preserved — pass only the flags you want to change.
# The Python helper below owns all parsing/formatting/writing so date and
# language-list normalization behave identically on every platform.
SECURITY_TXT_PATH="${SCRIPT_DIR}/static/.well-known/security.txt"

_security_txt_apply() {
	# args: contact expires expires_days preferred_lang canonical
	local contact="$1" expires="$2" expires_days="$3" plang="$4" canonical="$5"
	mkdir -p "$(dirname "$SECURITY_TXT_PATH")"

	local ec=0
	"$PYTHON" - "$SECURITY_TXT_PATH" "$contact" "$expires" "$expires_days" "$plang" "$canonical" <<'PYEOF' || ec=$?
import sys, os, re
from datetime import datetime, timedelta, timezone

target, contact, expires, expires_days, plang, canonical = sys.argv[1:7]

REQUIRED_ORDER = ["Contact", "Expires", "Preferred-Languages", "Canonical"]

# ── Load any existing fields so we only overwrite what was passed ──────────
existing = {}
if os.path.exists(target):
    with open(target, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            if ":" in line:
                k, _, v = line.partition(":")
                existing[k.strip()] = v.strip()

# ── Expires: normalize to YYYY-MM-DDTHH:MM:SS.sssZ (RFC 9116 / ISO 8601) ───
def fmt_expires(raw: str, days: str):
    if days:
        try:
            n = int(days)
        except ValueError:
            print(f"❌ --expires-in-days must be an integer, got {days!r}", file=sys.stderr)
            sys.exit(1)
        dt = datetime.now(timezone.utc) + timedelta(days=n)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    if not raw:
        return None
    raw = raw.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$', raw):
        return raw                                    # already exact format
    m = re.match(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z?$', raw)
    if m:
        return m.group(1) + ".000Z"                   # has a time, missing ms/Z
    if re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
        return raw + "T23:00:00.000Z"                 # date only → end of day UTC
    print(f"❌ Could not parse --expires value: {raw!r}", file=sys.stderr)
    print("   Use YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, or the full YYYY-MM-DDTHH:MM:SS.sssZ", file=sys.stderr)
    sys.exit(1)

if contact:
    c = contact.strip()
    if not re.match(r'^(mailto|https?|tel):', c, re.IGNORECASE):
        c = f"mailto:{c}"
    existing["Contact"] = c

new_expires = fmt_expires(expires, expires_days)
if new_expires:
    existing["Expires"] = new_expires

if plang:
    parts = [p.strip() for p in plang.split(",") if p.strip()]
    existing["Preferred-Languages"] = ", ".join(parts)

if canonical:
    existing["Canonical"] = canonical.strip()

missing = [k for k in REQUIRED_ORDER if k not in existing]
if missing:
    print(f"❌ Missing required field(s): {', '.join(missing)}", file=sys.stderr)
    print("   Provide via --contact / --expires (or --expires-in-days) / --preferred-lang / --canonical", file=sys.stderr)
    sys.exit(1)

lines = [f"{k}: {existing[k]}" for k in REQUIRED_ORDER]
for k, v in existing.items():           # keep any extra custom fields, appended after
    if k not in REQUIRED_ORDER:
        lines.append(f"{k}: {v}")

with open(target, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(lines) + "\n")

print(f"✅ Wrote {target}")
for line in lines:
    print(f"   {line}")
PYEOF
	return $ec
}

_security_txt_show() {
	if [[ -f "$SECURITY_TXT_PATH" ]]; then
		header "Current security.txt"
		divider
		cat "$SECURITY_TXT_PATH"
		divider
	else
		warn "No security.txt yet at ${SECURITY_TXT_PATH}"
		info "Create one:  ./manage.sh security-txt --contact you@example.com --expires 2030-09-03 --preferred-lang en,fil --canonical https://yourdomain.com/.well-known/security.txt"
	fi
}

_security_txt_interactive() {
	local cur_contact="" cur_expires="" cur_plang="" cur_canonical=""
	if [[ -f "$SECURITY_TXT_PATH" ]]; then
		cur_contact=$(grep -m1 '^Contact:' "$SECURITY_TXT_PATH" | cut -d: -f2- | sed 's/^ *//') || true
		cur_expires=$(grep -m1 '^Expires:' "$SECURITY_TXT_PATH" | cut -d: -f2- | sed 's/^ *//') || true
		cur_plang=$(grep -m1 '^Preferred-Languages:' "$SECURITY_TXT_PATH" | cut -d: -f2- | sed 's/^ *//') || true
		cur_canonical=$(grep -m1 '^Canonical:' "$SECURITY_TXT_PATH" | cut -d: -f2- | sed 's/^ *//') || true
	fi

	header "security.txt — Interactive Update"
	divider
	info "Leave a field blank to keep its current value (shown in [brackets])."
	echo ""

	# Each prompt goes through _ask: Ctrl-C / Ctrl-D cancels the whole edit and
	# leaves security.txt untouched (no half-written file, no dead script).
	local contact="" expires="" plang="" canonical=""
	{
		_ask contact "  Contact (email or mailto:/https: URL) [${cur_contact:-none}]: " &&
			_ask expires "  Expires (YYYY-MM-DD or full ISO datetime) [${cur_expires:-none}]: " &&
			_ask plang "  Preferred-Languages, comma separated [${cur_plang:-none}]: " &&
			_ask canonical "  Canonical URL [${cur_canonical:-none}]: "
	} || {
		warn "Cancelled — security.txt was not changed."
		return 130
	}

	_security_txt_apply "$contact" "$expires" "" "$plang" "$canonical"
}

# ── cmd_security_txt ─────────────────────────────────────────────────────────
cmd_security_txt() {
	if [[ $# -eq 0 ]]; then
		_security_txt_interactive
		return $?
	fi
	if [[ "$1" == "show" ]]; then
		_security_txt_show
		return $?
	fi

	local contact="" expires="" expires_days="" plang="" canonical=""
	while [[ $# -gt 0 ]]; do
		# Every flag takes a value; without this check `set -u` aborted with a
		# cryptic "unbound variable" when the value was missing.
		case "$1" in
		--contact | --expires | --expires-in-days | --preferred-lang | --preferred-languages | --canonical)
			if [[ $# -lt 2 ]]; then
				error "Option $1 needs a value."
				return 1
			fi
			;;
		esac
		case "$1" in
		--contact)
			contact="$2"
			shift 2
			;;
		--expires)
			expires="$2"
			shift 2
			;;
		--expires-in-days)
			expires_days="$2"
			shift 2
			;;
		--preferred-lang | --preferred-languages)
			plang="$2"
			shift 2
			;;
		--canonical)
			canonical="$2"
			shift 2
			;;
		*)
			error "Unknown option: $1"
			return 1
			;;
		esac
	done

	if [[ -z "$contact$expires$expires_days$plang$canonical" ]]; then
		error "Specify at least one of --contact --expires --expires-in-days --preferred-lang --canonical"
		info "Or run without args for the interactive prompt, or 'show' to print the current file."
		return 1
	fi

	_security_txt_apply "$contact" "$expires" "$expires_days" "$plang" "$canonical"
}

# ── cmd_dashboard ─────────────────────────────────────────────────────────────
cmd_dashboard() {
	header "Cloudinator — Server Manager"
	divider

	local active
	active=$(active_server)

	for type in prod dev; do
		local script pid_file
		script=$(script_for "$type")
		pid_file=$(pid_file_for "$type")

		if is_running "$pid_file"; then
			local pid uptime_str log
			pid=$(read_pid "$pid_file")
			if is_windows; then
				uptime_str="running"
			else
				uptime_str=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ') || uptime_str="unknown"
			fi
			log=$(current_log_for "$type")
			echo -e "  ${GREEN}● RUNNING${NC}  ${BOLD}${script}${NC}"
			echo -e "             ${DIM}PID    :${NC} ${pid}"
			echo -e "             ${DIM}Uptime :${NC} ${uptime_str}"
			echo -e "             ${DIM}Log    :${NC} $(basename "$log")"
		else
			echo -e "  ${DIM}○ stopped${NC}  ${BOLD}${script}${NC}"
		fi
	done

	divider
	echo ""

	if [[ -n "$active" ]]; then
		local dname
		dname=$(display_name_for "$active")
		echo -e "  ${BOLD}Quick commands:${NC}"
		echo "   ./manage.sh logs ${dname} -f   # follow live logs"
		echo "   ./manage.sh stop               # stop server"
		echo "   ./manage.sh restart            # restart server"
		echo "   ./manage.sh status             # full status + log tail"
		echo "   ./manage.sh clean-logs         # remove old log files"
	else
		echo -e "  ${BOLD}Quick commands:${NC}"
		echo "   ./manage.sh start server       # start production server"
		echo "   ./manage.sh start dev_server   # start dev server"
	fi
	echo ""
	echo -e "  ${DIM}Run  ./manage.sh help  for all commands${NC}"
	echo -e "  ${DIM}Run  ./manage.sh menu  for interactive mode${NC}"
	echo ""
}

# ── cmd_menu ──────────────────────────────────────────────────────────────────
# Ctrl-C in the menu — why it is built this way:
#   • cmd_menu installs a *handled* SIGINT trap (`trap ':' INT`), so no Ctrl-C
#     can ever kill manage.sh out from under you. (Handled, not ignored, so
#     `read` still returns and prompts can react.)
#   • Every action runs through _menu_run: a subshell with its own INT trap.
#     Ctrl-C aborts THAT action — a prompt, python, a sleep, anything — prints
#     "Cancelled" and drops back to the menu.
#   • At the "Choose an option" prompt itself, Ctrl-C / Ctrl-D quits cleanly.
_menu_run() {
	(
		trap 'echo ""; warn "Cancelled (Ctrl-C) — back to the menu."; exit 130' INT
		"$@"
	) || true
}

# Prompt used by the menu loop itself (the parts that are NOT inside _menu_run).
# A plain `read` in the parent shell cannot be interrupted while a SIGINT trap
# is installed — bash simply re-enters the read after running the trap — so the
# read happens in a subshell whose own trap exits with 130.
#   returns 0 = got a line (in VAR) · 130 = Ctrl-C · 1 = Ctrl-D / EOF
_read_line() {
	local __out="" __rc=0
	__out=$(
		trap 'exit 130' INT
		__l=""
		read -rp "$2" __l || exit 1
		printf '%s' "$__l"
	) || __rc=$?
	((__rc == 0)) || return "$__rc"
	printf -v "$1" '%s' "$__out"
}

# Menu 6 — same choices as:  logs [server|dev_server] [-f]
_menu_logs() {
	local active def which="" follow=""
	active=$(active_server)
	def=$(display_name_for "${active:-prod}")
	_ask which "  Which log? server / dev_server [${def}]: " || return 130
	which="${which:-$def}"
	_ask follow "  Follow live, like -f? [y/N]: " || return 130
	if [[ "$follow" =~ ^[Yy] ]]; then
		cmd_logs "$which" -f
	else
		cmd_logs "$which"
	fi
}

cmd_menu() {
	trap ':' INT
	while true; do
		header "Manage — Interactive Menu"
		divider

		local active
		active=$(active_server)
		if [[ -n "$active" ]]; then
			local pid
			pid=$(read_pid "$(pid_file_for "$active")")
			echo -e "  ${GREEN}● Server running:${NC} $(script_for "$active")  ${DIM}(PID ${pid})${NC}"
		else
			echo -e "  ${DIM}○ No server running${NC}"
		fi

		echo ""
		echo -e "  ${BOLD}Servers${NC}"
		echo "   1) Start prod server (hypercorn)"
		echo "   2) Start dev server  (quart)"
		echo "   3) Stop server"
		echo "   4) Restart server"
		echo "   5) Server status"
		echo "   6) Follow logs"
		echo "   7) Clean log files"
		echo "   8) Restart WebDAV only  — recover a wedged WebDAV listener"
		echo ""
		echo -e "  ${BOLD}Utilities${NC}"
		echo "   9) smb_setup.py        — Configure SMB storage"
		echo "  10) kick_sessions.py    — Force logout of all active sessions"
		echo "  11) config.py           — Edit configuration"
		echo "  12) manage_users.py     — Manage user credentials"
		echo "  13) debug_passwords.py  — Debug passwords"
		echo "  14) reset_db.py         — Reset database"
		echo "  15) setup_storage.py    — Configure storage"
		echo "  16) setup_pymodules.sh  — Setup and Update Python packages"
		echo "  17) revoke_sharing.py   — Share link management (links, passkeys, approvals)"
		echo "  18) security.txt        — Update static/.well-known/security.txt"
		# Always listed so the menu numbers match `./manage.sh help` (19 entries).
		# Off Termux, cmd_termux_setup just explains that it is Android-only.
		if is_termux; then
			echo "  19) termux_setup.sh     — Termux initial setup (Android only)"
		else
			echo -e "  ${DIM}19) termux_setup.sh     — Termux initial setup (Android only — n/a on this system)${NC}"
		fi
		echo ""
		echo "   q) Quit"
		echo ""
		divider

		local choice=""
		if ! _read_line choice "  Choose an option: "; then
			# Ctrl-C / Ctrl-D / closed stdin at the top-level prompt = quit.
			echo ""
			success "Goodbye!"
			exit 0
		fi

		case "$choice" in
		1) _menu_run cmd_start server ;;
		2) _menu_run cmd_start dev_server ;;
		3) _menu_run cmd_stop ;;
		4) _menu_run cmd_restart ;;
		5) _menu_run cmd_status ;;
		6) _menu_run _menu_logs ;;
		7) _menu_run cmd_clean_logs ;;
		8) _menu_run cmd_restart_webdav ;;
		9) _menu_run run_utility "smb_setup.py" ;;
		10) _menu_run run_utility "kick_sessions.py" ;;
		11) _menu_run run_utility "config.py" ;;
		12) _menu_run run_utility "manage_users.py" ;;
		13) _menu_run run_utility "debug_passwords.py" ;;
		14) _menu_run run_utility "reset_db.py" ;;
		15) _menu_run run_utility "setup_storage.py" ;;
		16) _menu_run cmd_setup_modules ;;
		17) _menu_run run_utility "revoke_sharing.py" ;;
		18) _menu_run cmd_security_txt ;;
		19) _menu_run cmd_termux_setup ;;
		q | Q)
			echo ""
			success "Goodbye!"
			exit 0
			;;
		*) warn "Invalid option: ${choice}" ;;
		esac

		echo ""
		_read_line _pause "  Press Enter to return to menu…" || echo ""
	done
}

# ── cmd_help ──────────────────────────────────────────────────────────────────
cmd_help() {
	cat <<EOF

${BOLD}manage.sh${NC} — Cloudinator Server & Utility Manager

${BOLD}USAGE${NC}
  ./manage.sh                     Dashboard (same as: ./manage.sh dashboard)
  ./manage.sh <command> [args]
  ./manage.sh menu                Interactive menu — every menu number is one of
                                  the commands below (see MENU ↔ COMMAND MAP)

${BOLD}SERVER COMMANDS${NC}  (mutually exclusive — only one server at a time)
  start  server         Start production server (hypercorn) in the background
  start  dev_server     Start dev server (quart) in the background
  stop                  Gracefully stop the running server
  restart               Restart the currently active server
  restart-webdav        Restart ONLY WebDAV (recovers a wedged/stuck WebDAV
                          listener without touching the main server — see
                          webdav_server.py's module docstring for why this
                          exists: a known Hypercorn/asyncio issue where
                          cancelling a large in-flight download can wedge
                          WebDAV's event loop)
  status                Show current server status + recent log tail
  logs   [server|dev_server] [-f]
                        Print logs; -f to follow in real time
                        (no server given = the one that is running)
                        Ctrl-C detaches tail without stopping the server
  clean-logs            List and delete old log files (with confirmation)

${BOLD}UTILITY COMMANDS${NC}  (foreground — safe to run while server is up)
  Any extra arguments after a utility command are passed straight to its script.
  setup-smb             python smb_setup.py — Configure SMB protocol storage (Windows/Linux)
  kick-sessions         python kick_sessions.py — Force logout of all active
                          sessions (server must be running)
  config                python config.py
  manage-users          python manage_users.py
  debug-pw              python debug_passwords.py
  reset-db              python reset_db.py
  setup-storage         python setup_storage.py
  update-modules [-y]   bash setup_pymodules.sh — rewrites requirements.txt /
                          constraints.txt, checks for conflicts, then offers to
                          install. Asks for confirmation first (-y / --yes skips
                          that question). Ctrl-C at any point stops it and, if
                          it was still generating the files, restores the old ones.
                          (alias: setup-modules)
  revoke-shares         python revoke_sharing.py [no args → interactive menu]
                          subcommands: list | revoke <token> [--yes] |
                          revoke-path <path> [--yes] | revoke-all [--yes] |
                          edit <token> [opts] | edit-path <path> [opts] |
                          requests | approve <id> [--max-downloads N] | deny <id>
                          (edit opts: --mode public|passkey|approval --passkey KEY
                           --generate-passkey --clear-passkey
                           --expires-in 1h|2d|30m|7d|SECONDS --never-expire)
  security-txt          Update static/.well-known/security.txt (RFC 9116)
                          no args → interactive prompt (blank keeps current value;
                                    Ctrl-C cancels without changing the file)
                          show    → print the current file
                          flags   → --contact <email or mailto:/https: URL>
                                    --expires <YYYY-MM-DD | full ISO datetime>
                                    --expires-in-days <N>  (relative, computed in UTC)
                                    --preferred-lang <comma,separated,codes>
                                    --canonical <URL>
                          Only the flags you pass are changed — existing fields
                          in the file are left alone. Expires is normalized to
                          YYYY-MM-DDTHH:MM:SS.sssZ; a date-only value defaults
                          to 23:00:00.000Z that day.
  termux-setup          bash termux_setup.sh  (Android/Termux only)

${BOLD}OTHER${NC}
  dashboard             Status overview + quick commands (default with no args)
  menu                  Interactive menu
  help | -h | --help    Show this help

${BOLD}MENU ↔ COMMAND MAP${NC}  (in ./manage.sh menu type the number; from the shell type the command)
   1  start server          2  start dev_server      3  stop
   4  restart               5  status                6  logs [server|dev_server] [-f]
   7  clean-logs            8  restart-webdav        9  setup-smb
  10  kick-sessions        11  config               12  manage-users
  13  debug-pw             14  reset-db             15  setup-storage
  16  update-modules       17  revoke-shares        18  security-txt
  19  termux-setup (Android/Termux only; shown dimmed elsewhere)       q  quit

${BOLD}EXAMPLES${NC}
  Servers
    ./manage.sh                                  # dashboard
    ./manage.sh dashboard                        # same as above
    ./manage.sh start server                     # launch hypercorn server in background
    ./manage.sh start dev_server                 # launch quart dev server in background
    ./manage.sh stop                             # gracefully stop the server
    ./manage.sh restart                          # restart whichever server is running
    ./manage.sh restart-webdav                   # recover a wedged WebDAV without touching the main server
    ./manage.sh status                           # server status + last log lines
    ./manage.sh logs                             # last 50 lines of the running server's log
    ./manage.sh logs server                      # last 50 lines of the prod server log
    ./manage.sh logs dev_server                  # last 50 lines of the dev server log
    ./manage.sh logs server -f                   # follow live output; Ctrl-C to detach only
    ./manage.sh logs dev_server -f               # same, for the dev server
    ./manage.sh clean-logs                       # delete old log files
  Utilities
    ./manage.sh setup-smb                        # configure SMB storage
    ./manage.sh kick-sessions                    # force logout of every active session
    ./manage.sh config                           # edit configuration
    ./manage.sh manage-users                     # run tool while server is still up
    ./manage.sh debug-pw                         # debug passwords
    ./manage.sh reset-db                         # reset the database
    ./manage.sh setup-storage                    # configure storage
    ./manage.sh update-modules                   # update Python packages (asks first)
    ./manage.sh update-modules -y                # same, without the confirmation question
    ./manage.sh termux-setup                     # Android/Termux first-time setup
  Share links
    ./manage.sh revoke-shares                    # interactive share-management menu
    ./manage.sh revoke-shares list               # list active share links
    ./manage.sh revoke-shares revoke <token>     # revoke one link by token   (add --yes to skip y/N)
    ./manage.sh revoke-shares revoke-path <path> # revoke one link by path    (add --yes to skip y/N)
    ./manage.sh revoke-shares revoke-all         # revoke every link (asks for a typed code; --yes skips only the y/N)
    ./manage.sh revoke-shares edit <token> --mode passkey --generate-passkey --expires-in 7d
    ./manage.sh revoke-shares edit-path <path> --never-expire
    ./manage.sh revoke-shares requests           # list pending access requests
    ./manage.sh revoke-shares approve <id> --max-downloads 3
    ./manage.sh revoke-shares deny <id>
  security.txt
    ./manage.sh security-txt                     # interactive prompt
    ./manage.sh security-txt show                # print the current security.txt
    ./manage.sh security-txt --contact you@example.com --expires 2030-09-03 --preferred-lang en,fil --canonical https://yourdomain.com/.well-known/security.txt
    ./manage.sh security-txt --expires-in-days 365     # only change Expires (1 year from now, UTC)
  Other
    ./manage.sh menu                             # interactive mode
    ./manage.sh help                             # this text
    PYTHON=python3.11 ./manage.sh start server   # pick a specific Python interpreter

${BOLD}LOG FILES${NC}
  One file per day per server type, shared with the app's own logger —
  automatically rolls onto a new file at midnight even without a restart:
    logs/prod_server_2026-09-15.log
    logs/dev_server_2026-09-15.log
  Routine console output (print() banners) is discarded in background
  mode; everything diagnostically useful (request timing, errors,
  protocol events) is in these files already. Use clean-logs to remove
  old ones.

${BOLD}CTRL-C${NC}
  The server runs in its own detached process group. Pressing Ctrl-C while
  following logs (logs -f) stops ONLY the tail output — the server keeps
  running unaffected. This works on Windows, Linux, and Android/Termux.
  In the interactive menu, Ctrl-C cancels the action you are in (a prompt,
  a utility, …) and returns to the menu; at the "Choose an option" prompt
  it quits the menu cleanly.

${BOLD}ENVIRONMENT${NC}
  PYTHON   Python interpreter to use (default: python, else python3, from PATH)
           e.g.  PYTHON=python3.11 ./manage.sh start server

EOF
}

# ── Entrypoint ────────────────────────────────────────────────────────────────
main() {
	local cmd="${1:-dashboard}"
	shift || true

	case "$cmd" in
	start) cmd_start "$@" ;;
	stop) cmd_stop ;;
	restart) cmd_restart ;;
	restart-webdav) cmd_restart_webdav ;;
	status) cmd_status ;;
	logs) cmd_logs "$@" ;;
	clean-logs) cmd_clean_logs ;;
	setup-smb) run_utility "smb_setup.py" "$@" ;;
	kick-sessions) run_utility "kick_sessions.py" "$@" ;;
	config) run_utility "config.py" "$@" ;;
	manage-users) run_utility "manage_users.py" "$@" ;;
	debug-pw) run_utility "debug_passwords.py" "$@" ;;
	reset-db) run_utility "reset_db.py" "$@" ;;
	setup-storage) run_utility "setup_storage.py" "$@" ;;
	update-modules | setup-modules) cmd_setup_modules "$@" ;;
	revoke-shares) run_utility "revoke_sharing.py" "$@" ;;
	security-txt) cmd_security_txt "$@" ;;
	termux-setup) cmd_termux_setup ;;
	menu) cmd_menu ;;
	dashboard) cmd_dashboard ;;
	help | --help | -h) cmd_help ;;
	*)
		error "Unknown command: ${cmd}"
		cmd_help
		exit 1
		;;
	esac
}

main "$@"
