#!/usr/bin/env bash
# =============================================================================
#  manage.sh — Cloudinator Server & Utility Management
# =============================================================================

set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use whatever 'python' resolves to in PATH (your system env var).
# Override any time:  PYTHON=python3.11 ./manage.sh start server
PYTHON="${PYTHON:-python}"

PID_DIR="${SCRIPT_DIR}/.manage_pids"
LOG_DIR="${SCRIPT_DIR}/logs"

# ── Colours ───────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    RED='\033[0;31m'   GREEN='\033[0;32m'  YELLOW='\033[1;33m'
    BLUE='\033[0;34m'  CYAN='\033[0;36m'   BOLD='\033[1m'
    DIM='\033[2m'      NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' CYAN='' BOLD='' DIM='' NC=''
fi

# ── Print helpers ─────────────────────────────────────────────────────────────
info()    { echo -e "${BLUE}  ➜ ${NC}$*"; }
success() { echo -e "${GREEN}  ✔ ${NC}$*"; }
warn()    { echo -e "${YELLOW}  ⚠ ${NC}$*"; }
error()   { echo -e "${RED}  ✖ ${NC}$*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}$*${NC}"; }
divider() { echo -e "${DIM}──────────────────────────────────────────────────${NC}"; }

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
        dev)  echo "${PID_DIR}/dev.pid"  ;;
        *) error "Unknown type: $1"; exit 1 ;;
    esac
}

logpath_file_for() {
    # Stores the active log file path so we can find it by server type
    case "$1" in
        prod) echo "${PID_DIR}/prod.logpath" ;;
        dev)  echo "${PID_DIR}/dev.logpath"  ;;
        *) error "Unknown type: $1"; exit 1 ;;
    esac
}

script_for() {
    case "$1" in
        prod) echo "prod_server.py" ;;
        dev)  echo "dev_server.py"  ;;
        *) error "Unknown type: $1"; exit 1 ;;
    esac
}

# Map user-facing names → internal keys (also accepts internal keys for safety)
normalize_type() {
    case "$1" in
        server|prod)    echo "prod" ;;
        dev_server|dev) echo "dev"  ;;
        *) error "Unknown server: '${1}'. Use 'server' or 'dev_server'"; exit 1 ;;
    esac
}

# Map internal keys → user-facing names (for hints / messages)
display_name_for() {
    case "$1" in
        prod) echo "server" ;;
        dev)  echo "dev_server" ;;
    esac
}

# ── Log path helpers ──────────────────────────────────────────────────────────
# Each server start creates a new log file stamped with the datetime.
# Example: logs/prod_server_2026-06-09_10-32-01.log
new_log_path_for() {
    local type="$1"
    local dt
    dt=$(date '+%Y-%m-%d_%H-%M-%S')
    echo "${LOG_DIR}/${type}_server_${dt}.log"
}

# Return the log file for a running server (from .logpath) or the most recent one.
current_log_for() {
    local type="$1"
    local lp
    lp=$(logpath_file_for "$type")
    if [[ -f "$lp" ]]; then
        cat "$lp"
    else
        ls -t "${LOG_DIR}/${type}_server_"*.log 2>/dev/null | head -1 || echo ""
    fi
}

# ── Process helpers ───────────────────────────────────────────────────────────
is_running() {
    local pid_file="$1"
    [[ -f "$pid_file" ]] || return 1
    local pid
    pid=$(<"$pid_file")
    [[ -n "$pid" ]] || return 1
    
    if is_windows; then
        # We store the real Windows PID; tasklist is the reliable check on Windows.
        tasklist //FI "PID eq ${pid}" //NH 2>/dev/null | grep -qi "python" || return 1
    else
        kill -0 "$pid" 2>/dev/null || return 1
    fi
}

active_server() {
    if   is_running "$(pid_file_for prod)"; then echo "prod"
        elif is_running "$(pid_file_for dev)";  then echo "dev"
    else echo ""
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
#     script.  This defeats any framework (Flask reloader, Werkzeug,
#     Waitress) that might otherwise reinstall its own SIGINT handler.
#     The env var CLOUDINATOR_BG=1 tells dev_server.py to disable
#     use_reloader (the reloader spawns a watchdog subprocess that has
#     its own signal wiring and can't be silenced any other way).
#
# Prints the real native PID (Windows PID on Windows, Unix PID elsewhere).
_launch_detached() {
    local script_path="$1"
    local log_path="$2"
    
    local tmp
    tmp=$(mktemp "${TMPDIR:-/tmp}/manage_launcher_XXXXXX")
    
  cat > "$tmp" << 'PYEOF'
import subprocess, sys, os

script_path = sys.argv[1]
log_path    = sys.argv[2]

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

with open(log_path, 'a', encoding='utf-8', errors='replace') as lf:
    p = subprocess.Popen(
        [sys.executable, '-c', wrapper],
        stdout=lf, stderr=lf,
        **kw
    )

print(p.pid)
sys.exit(0)
PYEOF
    
    local pid
    pid=$("$PYTHON" "$tmp" "$script_path" "$log_path" 2>/dev/null)
    rm -f "$tmp"
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
    trap '' INT    # shell ignores Ctrl-C so manage.sh itself doesn't exit
    
    # Python reads from stdin (-), log path is argv[1].
    # 'PYEOF' (quoted) prevents bash expanding anything inside the heredoc.
  "$PYTHON" - "$log" << 'PYEOF'
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
    
    trap - INT     # restore default signal handling
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
            pid=$(<"$(pid_file_for "$type")")
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
            echo -e "  ${YELLOW}⚠ ${BOLD}$(script_for "$other")${NC} is already running (PID $(<"$(pid_file_for "$other")"))."
            echo -e "    Only one server can run at a time."
            divider
            echo ""
            info "Stop it first:   ./manage.sh stop"
            info "Then run:        ./manage.sh start $(display_name_for "$type")"
            return 1
        fi
    fi
    
    ensure_dirs
    
    local script pid_file lp_file log
    script=$(script_for "$type")
    pid_file=$(pid_file_for "$type")
    lp_file=$(logpath_file_for "$type")
    log=$(new_log_path_for "$type")
    
    if [[ ! -f "${SCRIPT_DIR}/${script}" ]]; then
        error "Script not found: ${SCRIPT_DIR}/${script}"
        return 1
    fi
    
    info "Starting ${BOLD}${script}${NC} in the background…"
    info "Python  → ${PYTHON}  ($(${PYTHON} --version 2>&1))"
    info "Log     → ${log}"
    
    local pid
    pid=$(_launch_detached "${SCRIPT_DIR}/${script}" "$log")
    
    if [[ -z "$pid" ]]; then
        error "Launcher returned no PID — check ${log} for details."
        return 1
    fi
    
    echo "$pid" > "$pid_file"
    echo "$log" > "$lp_file"
    
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
        rm -f "$pid_file" "$lp_file"
        error "${script} crashed immediately. Check ${log} for details."
        return 1
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
    
    local pid_file pid script lp_file
    pid_file=$(pid_file_for "$type")
    pid=$(<"$pid_file")
    script=$(script_for "$type")
    lp_file=$(logpath_file_for "$type")
    
    info "Stopping ${BOLD}${script}${NC} (PID ${pid})…"
    
    if is_windows; then
        # taskkill with the real Windows PID — immediate and reliable
        taskkill //F //PID "$pid" &>/dev/null \
        || kill -9 "$pid" 2>/dev/null \
        || true
        sleep 0.3
    else
        kill "$pid" 2>/dev/null || true
        local i=0
        while kill -0 "$pid" 2>/dev/null && (( i < 10 )); do
            sleep 0.5
            (( i++ ))
        done
        if kill -0 "$pid" 2>/dev/null; then
            warn "Process did not exit gracefully — sending SIGKILL…"
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
    
    rm -f "$pid_file" "$lp_file"
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
            pid=$(<"$pid_file")
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
        (( deleted++ )) || true
    done
    
    success "Deleted ${deleted} log file(s)."
}

# ── Utility runners ───────────────────────────────────────────────────────────
run_utility() {
    local script="$1"; shift
    if [[ ! -f "${SCRIPT_DIR}/${script}" ]]; then
        error "Script not found: ${SCRIPT_DIR}/${script}"
        return 1
    fi
    header "Running ${script}"
    divider
    trap '' INT    # shell ignores Ctrl-C so manage.sh itself doesn't exit
    # IMPORTANT: this must be `cmd || ec=$?`, not `cmd; local ec=$?`.
    # Under `set -e`, a bare failing command aborts the ENTIRE manage.sh
    # process on the spot — execution never reaches the next line, so
    # `local ec=$?`, `trap - INT`, and the success/error message below all
    # get skipped, and control never returns to the menu loop. Every Python
    # utility here (including revoke_sharing.py) is expected to exit
    # non-zero on cancelled/failed actions, so this isn't a rare edge case —
    # it fires on ordinary use. Making the command the LHS of `||` puts it
    # in a tested context, which `set -e` explicitly exempts, so a failure
    # is captured into `ec` instead of killing the shell. This makes the
    # function safe regardless of whether the caller also wraps it in
    # `|| true` — see cmd_menu below, which does both as defense in depth.
    local ec=0
    "$PYTHON" "${SCRIPT_DIR}/${script}" "$@" || ec=$?
    trap - INT     # restore default signal handling
    divider
    (( ec == 0 )) && success "${script%.py} finished." \
    || error  "${script%.py} exited with code ${ec}."
    return $ec
}

run_bash_script() {
    local script="$1"; shift
    if [[ ! -f "${SCRIPT_DIR}/${script}" ]]; then
        error "Script not found: ${SCRIPT_DIR}/${script}"
        return 1
    fi
    header "Running ${script}"
    divider
    trap '' INT    # shell ignores Ctrl-C so manage.sh itself doesn't exit
    # See the comment in run_utility() above — same `set -e` hazard, same fix.
    local ec=0
    bash "${SCRIPT_DIR}/${script}" "$@" || ec=$?
    trap - INT     # restore default signal handling
    divider
    (( ec == 0 )) && success "${script} finished." \
    || error  "${script} exited with code ${ec}."
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
cmd_setup_modules() {
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
    "$PYTHON" - "$SECURITY_TXT_PATH" "$contact" "$expires" "$expires_days" "$plang" "$canonical" << 'PYEOF' || ec=$?
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

    local contact expires plang canonical
    read -rp "  Contact (email or mailto:/https: URL) [${cur_contact:-none}]: " contact
    read -rp "  Expires (YYYY-MM-DD or full ISO datetime) [${cur_expires:-none}]: " expires
    read -rp "  Preferred-Languages, comma separated [${cur_plang:-none}]: " plang
    read -rp "  Canonical URL [${cur_canonical:-none}]: " canonical

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
        case "$1" in
            --contact)            contact="$2"; shift 2 ;;
            --expires)            expires="$2"; shift 2 ;;
            --expires-in-days)    expires_days="$2"; shift 2 ;;
            --preferred-lang|--preferred-languages) plang="$2"; shift 2 ;;
            --canonical)          canonical="$2"; shift 2 ;;
            *) error "Unknown option: $1"; return 1 ;;
        esac
    done

    if [[ -z "$contact$expires$expires_days$plang$canonical" ]]; then
        error "Specify at least one of --contact --expires --expires-in-days --preferred-lang --canonical"
        info  "Or run without args for the interactive prompt, or 'show' to print the current file."
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
            pid=$(<"$pid_file")
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
cmd_menu() {
    while true; do
        header "Manage — Interactive Menu"
        divider
        
        local active
        active=$(active_server)
        if [[ -n "$active" ]]; then
            local pid
            pid=$(<"$(pid_file_for "$active")")
            echo -e "  ${GREEN}● Server running:${NC} $(script_for "$active")  ${DIM}(PID ${pid})${NC}"
        else
            echo -e "  ${DIM}○ No server running${NC}"
        fi
        
        echo ""
        echo -e "  ${BOLD}Servers${NC}"
        echo "   1) Start prod server (waitress)"
        echo "   2) Start dev server  (flask)"
        echo "   3) Stop server"
        echo "   4) Restart server"
        echo "   5) Server status"
        echo "   6) Follow logs"
        echo "   7) Clean log files"
        echo ""
        echo -e "  ${BOLD}Utilities${NC}"
        echo "   8) smb_setup.py        — Configure SMB storage"
        echo "   9) kick_sessions.py    — Force logout of all active sessions"
        echo "  10) config.py           — Edit configuration"
        echo "  11) manage_users.py     — Manage user credentials"
        echo "  12) debug_passwords.py  — Debug passwords"
        echo "  13) reset_db.py         — Reset database"
        echo "  14) setup_storage.py    — Configure storage"
        echo "  15) setup_pymodules.sh  — Setup and Update Python packages"
        echo "  16) revoke_sharing.py   — Share link management (links, passkeys, approvals)"
        echo "  17) security.txt        — Update static/.well-known/security.txt"
        if is_termux; then
            echo "  18) termux_setup.sh    — Termux initial setup (Android only)"
        fi
        echo ""
        echo "   q) Quit"
        echo ""
        divider
        read -rp "  Choose an option: " choice
        
        case "$choice" in
            1)  cmd_start server || true ;;
            2)  cmd_start dev_server || true ;;
            3)  cmd_stop || true ;;
            4)  cmd_restart || true ;;
            5)  cmd_status || true ;;
            6)
                local at
                at=$(active_server)
                local lt
                lt=$(display_name_for "${at:-prod}")
                read -rp "  Follow logs? [y/N]: " fa
                if [[ "$fa" =~ ^[Yy] ]]; then
                    cmd_logs "$lt" -f || true
                else
                    cmd_logs "$lt" || true
                fi
            ;;
            7)  cmd_clean_logs || true ;;
            8)  run_utility "smb_setup.py" || true ;;
            9)  run_utility "kick_sessions.py" || true ;;
            10) run_utility "config.py" || true ;;
            11) run_utility "manage_users.py" || true ;;
            12) run_utility "debug_passwords.py" || true ;;
            13) run_utility "reset_db.py" || true ;;
            14) run_utility "setup_storage.py" || true ;;
            15) cmd_setup_modules || true ;;
            16) run_utility "revoke_sharing.py" || true ;;
            17) cmd_security_txt || true ;;
            18) cmd_termux_setup || true ;;
            q|Q) echo ""; success "Goodbye!"; exit 0 ;;
            *) warn "Invalid option: ${choice}" ;;
        esac
        
        echo ""
        read -rp "  Press Enter to return to menu…" _
    done
}

# ── cmd_help ──────────────────────────────────────────────────────────────────
cmd_help() {
  cat << EOF

${BOLD}manage.sh${NC} — Cloudinator Server & Utility Manager

${BOLD}USAGE${NC}
  ./manage.sh <command> [args]

${BOLD}SERVER COMMANDS${NC}  (mutually exclusive — only one server at a time)
  start  server         Start production server (waitress) in the background
  start  dev_server     Start dev server (flask) in the background
  stop                  Gracefully stop the running server
  restart               Restart the currently active server
  status                Show current server status + recent log tail
  logs   [server|dev_server] [-f]
                        Print logs; -f to follow in real time
                        Ctrl-C detaches tail without stopping the server
  clean-logs            List and delete old log files (with confirmation)

${BOLD}UTILITY COMMANDS${NC}  (foreground — safe to run while server is up)
  setup-smb             Configure SMB protocol storage (Windows/Linux)
  kick-sessions         Force logout of all active sessions (server must be running)
  config                python config.py
  manage-users          python manage_users.py
  debug-pw              python debug_passwords.py
  reset-db              python reset_db.py
  setup-storage         python setup_storage.py
  update-modules        bash setup_pymodules.sh
  revoke-shares          python revoke_sharing.py [no args → interactive menu]
                           subcommands: list | revoke <token> | revoke-path <path> |
                           revoke-all | edit <token> [opts] | edit-path <path> [opts] |
                           requests | approve <id> | deny <id>
                           (edit opts: --mode --passkey --generate-passkey
                            --clear-passkey --expires-in --never-expire)
  security-txt           Update static/.well-known/security.txt (RFC 9116)
                           no args → interactive prompt (blank keeps current value)
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
  menu                  Interactive menu
  help                  Show this help

${BOLD}EXAMPLES${NC}
  ./manage.sh start server       # launch waitress server in background
  ./manage.sh start dev_server   # launch flask dev server in background
  ./manage.sh manage-users       # run tool while server is still up
  ./manage.sh logs server -f     # follow live output; Ctrl-C to detach only
  ./manage.sh clean-logs         # delete old log files
  ./manage.sh revoke-shares list # list active share links
  ./manage.sh revoke-shares      # interactive share-management menu
  ./manage.sh stop               # gracefully stop the server
  ./manage.sh menu               # interactive mode
  ./manage.sh security-txt show  # print the current security.txt
  ./manage.sh security-txt --contact you@example.com --expires 2030-09-03 --preferred-lang en,fil --canonical https://yourdomain.com/.well-known/security.txt

${BOLD}LOG FILES${NC}
  Saved to logs/ with datetime stamps — each start creates a new file:
    logs/prod_server_2026-06-09_10-32-01.log
    logs/dev_server_2026-06-09_10-45-00.log
  Use clean-logs to remove old files.

${BOLD}CTRL-C AND LOGS${NC}
  The server runs in its own detached process group. Pressing Ctrl-C while
  following logs (logs -f) stops ONLY the tail output — the server keeps
  running unaffected. This works on Windows, Linux, and Android/Termux.

${BOLD}ENVIRONMENT${NC}
  PYTHON   Python interpreter to use (default: python, from PATH)
           e.g.  PYTHON=python3.11 ./manage.sh start server

EOF
}

# ── Entrypoint ────────────────────────────────────────────────────────────────
main() {
    local cmd="${1:-dashboard}"
    shift || true
    
    case "$cmd" in
        start)          cmd_start "$@" ;;
        stop)           cmd_stop ;;
        restart)        cmd_restart ;;
        status)         cmd_status ;;
        logs)           cmd_logs "$@" ;;
        clean-logs)     cmd_clean_logs ;;
        setup-smb)      run_utility "smb_setup.py" "$@" ;;
        kick-sessions)  run_utility "kick_sessions.py" "$@" ;;
        config)         run_utility "config.py" "$@" ;;
        manage-users)   run_utility "manage_users.py" "$@" ;;
        debug-pw)       run_utility "debug_passwords.py" "$@" ;;
        reset-db)       run_utility "reset_db.py" "$@" ;;
        setup-storage)  run_utility "setup_storage.py" "$@" ;;
        setup-modules) cmd_setup_modules ;;
        revoke-shares)  run_utility "revoke_sharing.py" "$@" ;;
        security-txt)   cmd_security_txt "$@" ;;
        termux-setup)   cmd_termux_setup ;;
        menu)           cmd_menu ;;
        dashboard)      cmd_dashboard ;;
        help|--help|-h) cmd_help ;;
        *)
            error "Unknown command: ${cmd}"
            cmd_help
            exit 1
        ;;
    esac
}

main "$@"