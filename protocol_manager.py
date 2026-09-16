"""
protocol_manager.py — Unified launcher for WebDAV, SFTP, FTP, and SMB servers
-------------------------------------------------------------------------------
Call start_all() once at server startup (in dev_server.py / prod_server.py
right after 'from app import app') to spin up all enabled protocol servers.

SFTP/FTP/SMB run as background daemon threads in this process, as before.
WebDAV runs as its own OS PROCESS (spawned via subprocess.Popen, see
_spawn_webdav_process), supervised by a watchdog thread that respawns it on
an unexpected crash. This isolation exists specifically because of a known
Hypercorn/asyncio failure mode: a client cancelling a large in-flight
download can leave WebDAV's event loop stuck in a tight, non-terminating
write-retry loop ("SSL connection closed" flooding the log) that never
exits on its own — as a thread in this process that used to mean the ONLY
recovery was restarting the whole server (main app included); as its own
process, call restart_webdav() to recover WebDAV alone, main app unaffected.

Each server is started only if:
  1. The ENABLED flag in config.py is True (or missing, defaulting to True)
  2. The required library is installed (wsgidav / paramiko / pyftpdlib / impacket)

If a library is missing the server is skipped with a helpful message; the
main Flask server is never affected. For WebDAV specifically, a missing
'wsgidav' is discovered inside the subprocess and printed there — see that
process's own stdout rather than this module's synchronous `results` dict.

Usage (add to dev_server.py and prod_server.py):
    from app import app
    import protocol_manager          # ← add this
    protocol_manager.start_all()     # ← and this

Config keys to add to config.py (all optional — shown with defaults):
    WEBDAV_ENABLED = True
    WEBDAV_PORT    = 8080
    SFTP_ENABLED   = True
    SFTP_PORT      = 2222
    FTP_ENABLED    = True
    FTP_PORT       = 2121
    SMB_ENABLED    = True
    SMB_PORT       = 445
    SMB_FALLBACK_PORT = 8445

Windows WebDAV note:
    Windows requires the WebClient service to be running for HTTP WebDAV.
    If 'Map Network Drive' fails, run in an elevated PowerShell:
        Set-Service WebClient -StartupType Automatic
        Start-Service WebClient
    Then re-try mapping to http://HOST:8080/
    For HTTPS WebDAV (recommended for internet exposure), add a reverse
    proxy (nginx/caddy) with TLS in front of port 8080.

SMB note:
    Port 445 needs root/Administrator (Linux/Android) or for Windows'
    own native file sharing (LanmanServer) to be stopped first — see
    smb_server.py and lanman_guard.py. Falls back to SMB_FALLBACK_PORT
    automatically when 445 isn't available.
"""

import os
import socket
import subprocess
import sys
import threading
import time
import logging_setup
from app import get_local_ip

# ---------------------------------------------------------------------------
# This module's own logger. Previously `logging.getLogger(__name__).debug(...)`
# was called at two call sites below with no handler configured anywhere in
# the project — that logger never produced output anywhere, console or
# file. Now a child of logging_setup's shared "cloudinatorftp" logger, so
# these lines land in the same console + daily-dated log file
# (logs/prod_server_YYYY-MM-DD.log) as every other logger in the project.
# ---------------------------------------------------------------------------
_pm_logger = logging_setup.get_logger("protocol")

LOCAL_IP = get_local_ip()

_lock = threading.Lock()
_started = False

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# PID file for the WebDAV subprocess, in the SAME directory manage.sh uses
# for its own prod/dev PID files (.manage_pids/). This lets manage.sh (a
# separate, short-lived process — it can't call restart_webdav() directly,
# since that function only knows about the Popen handle held in THIS
# process's memory) discover the WebDAV subprocess's real PID, signal it
# directly, and rely on the watchdog in the already-running server process
# to notice the exit and respawn it — see restart-webdav in manage.sh.
_PID_DIR = os.path.join(_PROJECT_DIR, ".manage_pids")
_WEBDAV_PID_FILE = os.path.join(_PID_DIR, "webdav.pid")

# ── WebDAV process supervision ──────────────────────────────────────────
# WebDAV runs as its own OS process (launched via `python webdav_server.py`,
# see webdav_server.py's _run_standalone), NOT a thread in this process like
# SFTP/FTP/SMB below. Reason: a wedged WebDAV listener (see the known
# Hypercorn/asyncio large-download-cancel bug documented in
# webdav_server.py) previously required restarting this whole process —
# main app included — to recover. As its own process, it can be killed and
# respawned independently; see restart_webdav().
_webdav_proc: "subprocess.Popen | None" = None
_webdav_watchdog_thread: "threading.Thread | None" = None
_webdav_watchdog_stop = threading.Event()
_webdav_proc_lock = threading.Lock()


def _pump_child_output(stream, tag: str) -> None:
    """Background-thread reader for one of the WebDAV subprocess's PIPE'd
    streams (see _spawn_webdav_process). Relays each line straight to
    THIS process's real console (bypassing logging_setup's tee — see
    below for why) instead of relying on the OS to hand the child a
    directly-usable, inheritable stdout/stderr handle.

    Added 2026-09-15 after inherited-handle stdio (both the original
    stdout=sys.stdout/stderr=sys.stderr, and later the default/omitted
    inherit-real-fd-1/2 approach) both failed to surface ANY output from
    a crashing WebDAV child on one user's Windows machine — not even a
    raw Python traceback — despite webdav_server.py working perfectly
    when run as a fully standalone process with its own real console.
    Something about handle inheritance specifically wasn't getting the
    child's writes back to the parent/console at all on that machine;
    piping and reading the bytes ourselves sidesteps that entirely,
    regardless of root cause.

    Writes via logging_setup.get_real_stdout()/get_real_stderr(), NOT
    print() (2026-09-16 fix): print() goes through THIS process's own
    tee, which would write a second copy of every relayed line into the
    shared log file — on top of the WebDAV subprocess's own direct write
    via its own logging_setup instance (proven reliable by that point;
    this relay's file-writing purpose is now redundant, only its
    console-visibility purpose — and its value for a WebDAV crash so
    early that even ITS OWN logging_setup import hasn't finished — still
    matter). get_real_stdout()/get_real_stderr() return the streams from
    before the tee replaced sys.stdout/sys.stderr, so writing there shows
    up on a real console live without looping back through the tee.

    Runs until the pipe closes (child exited and both ends drained).
    Best-effort: any decode/read error just ends this thread quietly, it
    should never take down the watchdog or main app.
    """
    real_stream = (
        logging_setup.get_real_stdout()
        if tag == "OUT"
        else logging_setup.get_real_stderr()
    )
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            try:
                real_stream.write(f"[webdav:{tag}] {line.rstrip()}\n")
                real_stream.flush()
            except Exception:
                pass
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _cfg(key: str, default):
    """Read a config key with a fallback default (avoids ImportError)."""
    try:
        import config

        return getattr(config, key, default)
    except ImportError:
        return default


def _webdav_target_ports() -> list:
    """Ports webdav_server.py may try to bind, per config.py — used only
    for the pre-flight occupancy check and diagnostic message below, not
    to actually connect to WebDAV itself."""
    ports = []
    if _cfg("WEBDAV_ENABLED", False):
        ports.append(_cfg("WEBDAV_PORT", 8080))
    if _cfg("WEBDAV_HTTPS_ENABLED", True):
        ports.append(_cfg("WEBDAV_HTTPS_PORT", 8443))
    return ports or [8080, 8443]


def _port_occupied(port: int) -> bool:
    """True if something is already accepting TCP connections on `port`
    on this machine — checked via connect_ex against loopback, which
    succeeds against a live listener before any TLS/HTTP handshake even
    starts (webdav_server.py binds all interfaces, so loopback always
    reaches it), so this catches both the plaintext and HTTPS WebDAV
    listeners equally. Best-effort only: a false negative here just means
    we attempt the (harmless) spawn anyway and let it fail on its own."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def _port_conflict_message() -> str:
    ports = _webdav_target_ports()
    port_list = ", ".join(str(p) for p in ports)
    if sys.platform == "win32":
        find_cmd = "  netstat -ano | findstr :" + " :".join(str(p) for p in ports)
        kill_cmd = "  taskkill /F /PID <pid_from_above>"
    else:
        find_cmd = (
            "  lsof -i :"
            + ",".join(str(p) for p in ports)
            + "   (or: ss -ltnp | grep -E '"
            + "|".join(str(p) for p in ports)
            + "')"
        )
        kill_cmd = "  kill -9 <pid_from_above>"
    return (
        f"❌ WebDAV port(s) {port_list} already occupied by another process on "
        f"this machine — NOT respawning blindly. This is almost always a "
        f"leftover WebDAV process from a previous run that manage.sh/this "
        f"watchdog never managed to reach (its real PID isn't necessarily "
        f"the one in .manage_pids/webdav.pid — that file gets overwritten "
        f"by every spawn attempt, including ones that immediately fail, so "
        f"it can't be trusted to point at the actual occupant).\n"
        f"   Find and kill the real owner manually, then WebDAV will come "
        f"back up on its own within a few seconds:\n{find_cmd}\n{kill_cmd}"
    )


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _write_webdav_pidfile(pid: int):
    """Best-effort — used only by manage.sh's restart-webdav to find the
    real PID to signal. Not required for this module's own operation."""
    try:
        os.makedirs(_PID_DIR, exist_ok=True)
        with open(_WEBDAV_PID_FILE, "w") as f:
            f.write(str(pid))
    except Exception:
        pass


def _clear_webdav_pidfile():
    try:
        os.remove(_WEBDAV_PID_FILE)
    except OSError:
        pass


def _spawn_webdav_process() -> "subprocess.Popen | None":
    """Launch webdav_server.py as an independent OS process (its own PID,
    its own asyncio loop) instead of a thread in this process — so it can
    be killed/restarted without touching the main app. Returns the Popen
    handle, or None if the launch itself failed (rare — e.g. python
    executable/script not found).

    stdout/stderr are explicitly inherited from THIS process (not left to
    default) for two reasons:
      1. So WebDAV's own output (startup banner, hypercorn_ssl_fix's log
         line, errors) lands in the SAME log manage.sh's `follow logs`
         already tails, instead of going nowhere or to a fresh console.
      2. On Windows specifically: this process (prod_server.py) may itself
         be fully detached with NO console at all (see manage.sh's
         _launch_detached — CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS).
         A console-subsystem child (python.exe) spawned from a
         console-less parent with no stdout/stderr redirection gets a
         BRAND NEW, VISIBLE console window auto-allocated by Windows —
         that's the "separate python window opens" bug this fixes.
         CREATE_NO_WINDOW below is the belt-and-suspenders second half of
         the same fix — it works together with explicit stdio redirection
         to guarantee no window appears, on a detached parent or not.
    """
    script = os.path.join(_PROJECT_DIR, "webdav_server.py")
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW

    # Tell the child's own logging_setup.py which prefix to log under —
    # webdav_server.py is its own separate __main__ in its own interpreter,
    # so logging_setup's __main__-based detection can never recognize it as
    # "prod_server"/"dev_server" and would otherwise fall back to writing a
    # second, separate logs/app_YYYY-MM-DD.log. logging_setup._LOG_PREFIX
    # here is THIS (parent) process's own already-resolved prefix — reuse
    # it directly instead of re-deriving it, so WebDAV's log lines land in
    # the exact same daily file as everything else.
    env = dict(os.environ)
    env["CLOUDINATOR_LOG_PREFIX"] = logging_setup._LOG_PREFIX

    # Force UTF-8 for this subprocess's own stdout/stderr, unconditionally.
    #
    # Root cause of the actual crash-loop bug (2026-09-15, found via the
    # PIPE+relay diagnostic below once it finally surfaced a real
    # traceback): paths.py's ensure_dirs() prints an emoji ("\U0001f4c2
    # DB dir ready: ..."), pulled in transitively by webdav_server.py's
    # own `from app import get_local_ip`. When a process's stdout is
    # attached to a real console, Windows uses the console's codepage and
    # this just works. When stdout is redirected — piped (as
    # stdout=subprocess.PIPE below now does) or otherwise not a tty —
    # Python instead falls back to locale.getpreferredencoding(), which
    # on the affected machine is cp1252, and cp1252 can't encode that
    # emoji at all: UnicodeEncodeError, raised at import time, before
    # webdav_server.py's own code — or even its own logging setup — has a
    # chance to run. That's also why it was totally silent before this
    # subprocess switched to PIPE+relay: the same exception was very
    # likely already happening under plain fd inheritance too, just with
    # the traceback lost somewhere in Windows' handle-inheritance
    # behavior rather than reaching us.
    #
    # manage.sh's OWN detached launcher already sets PYTHONUTF8=1 for
    # whatever it spawns (prod_server.py/dev_server.py) — which is
    # inherited down into this env dict via os.environ when launched that
    # way, masking the bug entirely under manage.sh. Running `python
    # prod_server.py` directly never sets it, so this subprocess is the
    # first thing in that path to hit a genuinely non-console stdout and
    # trip over it. Setting it explicitly here — rather than relying on
    # it having been set somewhere further up the process chain — makes
    # WebDAV's own launch correct regardless of how the parent was
    # started.
    env["PYTHONUTF8"] = "1"

    # stdout/stderr: PIPE'd and actively read by _pump_child_output threads
    # below, rather than inherited via an OS-level handle.
    #
    # History: this originally passed stdout=sys.stdout / stderr=sys.stderr
    # explicitly, which depends on Popen resolving a usable fileno() off
    # logging_setup's _TeeStream wrapper. Removing that in favor of
    # Popen's default (inherit fd 1/2 directly, no Python object involved)
    # was the first fix attempt — but on the machine that surfaced this
    # bug, NEITHER approach ever produced a single byte of the crashing
    # child's output, console or log file, not even a raw interpreter
    # traceback — while `python webdav_server.py` run as a fully
    # standalone process (own console, no parent involved at all) worked
    # perfectly and printed its full startup banner. Something about
    # handle inheritance itself wasn't getting the child's writes back to
    # this process on that setup, for reasons that didn't matter enough
    # to keep chasing once there was a strictly more reliable option:
    # PIPE + explicit read-and-relay, entirely in Python code we control,
    # with no dependency on OS handle-inheritance semantics either way.
    try:
        proc = subprocess.Popen(
            [sys.executable, script],
            cwd=_PROJECT_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # Explicit encoding — text=True alone decodes with
            # locale.getpreferredencoding() (cp1252 on the machine that
            # surfaced this whole investigation), which mangles anything
            # non-ASCII the child writes (e.g. "ðŸ“‹" instead of "📋")
            # even though the child itself is now writing proper UTF-8
            # thanks to PYTHONUTF8=1 above. Must match on both ends.
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # line-buffered — pump threads read line by line
            env=env,
            **kw,
        )
    except Exception as e:
        print(f"❌ WebDAV: failed to launch subprocess: {e}")
        return None
    threading.Thread(
        target=_pump_child_output, args=(proc.stdout, "OUT"), daemon=True
    ).start()
    threading.Thread(
        target=_pump_child_output, args=(proc.stderr, "ERR"), daemon=True
    ).start()
    _write_webdav_pidfile(proc.pid)
    return proc


def _webdav_watchdog():
    """
    Background loop: (re)spawns the WebDAV subprocess whenever it isn't
    currently running — whether because it just exited unexpectedly
    (crash, exit code != 0) or because start_all() found the port already
    occupied and skipped the initial spawn entirely (_webdav_proc left as
    None). A clean/intentional exit (code 0 — WEBDAV disabled in config,
    or a graceful stop via stop_all()/restart_webdav(), both of which set
    _webdav_watchdog_stop before clearing _webdav_proc) stops this loop.

    Does NOT detect a wedged-but-still-running process (e.g. the
    Hypercorn/asyncio write-retry loop on a cancelled large download) —
    that process never exits, it just stops making progress. For that
    case use restart_webdav() to force a kill + respawn.

    Before every (re)spawn attempt, checks whether WebDAV's own port is
    already occupied by something else first (see _port_occupied). Found
    the hard way (2026-09-15): blindly respawning every 3s when the real
    problem is a leftover process still squatting the port doesn't just
    fail forever — it also destroys the ability to *find* that leftover
    process, since _write_webdav_pidfile() overwrites
    .manage_pids/webdav.pid on every attempt, including ones that
    immediately fail. A few cycles in, the pidfile only ever points at the
    latest (already-dead) attempt, not the actual occupant. So: if the
    port is occupied, skip the spawn entirely (leaves the pidfile alone)
    and back off to a slower, print-once-per-streak cadence instead of a
    tight 3s loop, with a message that tells the user how to find and
    kill the real occupant.
    """
    global _webdav_proc
    _conflict_warned = False
    while not _webdav_watchdog_stop.wait(timeout=2):
        with _webdav_proc_lock:
            proc = _webdav_proc

        crashed = False
        if proc is not None:
            ret = proc.poll()
            if ret is None:
                continue  # still running, nothing to do
            if ret == 0:
                break  # intentional/clean exit — don't respawn
            crashed = True

        if any(_port_occupied(p) for p in _webdav_target_ports()):
            if not _conflict_warned:
                print(_port_conflict_message())
                _conflict_warned = True
            # Slow poll instead of a tight loop — nothing productive to do
            # until the port frees up, and pidfile/log spam from repeated
            # doomed spawns is exactly what made this hard to diagnose.
            if _webdav_watchdog_stop.wait(timeout=15):
                break
            continue

        _conflict_warned = False
        if crashed:
            print(
                f"⚠️  WebDAV process exited unexpectedly (code {ret}) — respawning in 3s..."
            )
            time.sleep(3)
            if _webdav_watchdog_stop.is_set():
                break
        with _webdav_proc_lock:
            _webdav_proc = _spawn_webdav_process()


def restart_webdav() -> bool:
    """
    Force-kill and respawn the WebDAV subprocess. This is the fix for a
    wedged-but-alive WebDAV (e.g. stuck in a loop logging "SSL connection
    closed" after a large cancelled download) — recovers WebDAV alone,
    without restarting the whole server or touching the main app on :5000.
    Safe to call any time; a no-op-ish restart if WebDAV wasn't running.
    """
    global _webdav_proc
    with _webdav_proc_lock:
        proc = _webdav_proc
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
    with _webdav_proc_lock:
        _webdav_proc = _spawn_webdav_process()
        ok = _webdav_proc is not None
    if ok and (
        _webdav_watchdog_thread is None or not _webdav_watchdog_thread.is_alive()
    ):
        _start_webdav_watchdog()
    return ok


def _start_webdav_watchdog():
    global _webdav_watchdog_thread
    _webdav_watchdog_stop.clear()
    _webdav_watchdog_thread = threading.Thread(
        target=_webdav_watchdog, name="webdav-watchdog", daemon=True
    )
    _webdav_watchdog_thread.start()


def start_all():
    """
    Start WebDAV, SFTP, and FTP servers (those that are enabled and have
    their dependencies installed).  Safe to call more than once — only
    runs on the first call.
    """
    global _started
    with _lock:
        if _started:
            return
        _started = True

    print()
    print("─" * 56)
    print("  CloudinatorFTP — Protocol servers")
    print("─" * 56)

    results = {}

    # ── WebDAV ────────────────────────────────────────────────────────────
    # Spawned as an isolated subprocess (see _spawn_webdav_process) rather
    # than imported+started in this thread — webdav_server.py's own
    # WEBDAV_ENABLED/WEBDAV_HTTPS_ENABLED check decides whether it actually
    # binds anything; it exits cleanly (code 0) if both are off, in which
    # case the watchdog won't respawn it.
    #
    # Pre-flight port check first: if something is already listening on
    # WebDAV's port (almost always a leftover process from a previous run
    # that was never actually killed — see _port_conflict_message), don't
    # even attempt the spawn. It would just fail to bind and exit 1
    # immediately, and — worse — overwrite .manage_pids/webdav.pid with
    # that doomed attempt's PID, burying the real occupant's PID and
    # making it harder to find manually.
    global _webdav_proc
    if any(_port_occupied(p) for p in _webdav_target_ports()):
        print(_port_conflict_message())
        results["WebDAV"] = "❌ not started: port already occupied (see message above)"
        _webdav_proc = None
        _start_webdav_watchdog()  # will keep polling and retry once the port frees up
    else:
        _webdav_proc = _spawn_webdav_process()
        if _webdav_proc is not None:
            results["WebDAV"] = f"✅ started (pid {_webdav_proc.pid}, isolated process)"
            _start_webdav_watchdog()
        else:
            results["WebDAV"] = "❌ error: failed to launch subprocess"

    # ── SFTP ──────────────────────────────────────────────────────────────
    if _cfg("SFTP_ENABLED", True):
        try:
            import sftp_server

            ok = sftp_server.start()
            results["SFTP"] = "✅ started" if ok else "⚠️  skipped (missing deps)"
        except Exception as e:
            results["SFTP"] = f"❌ error: {e}"
    else:
        results["SFTP"] = "— disabled"

    # ── FTP ───────────────────────────────────────────────────────────────
    if _cfg("FTP_ENABLED", True):
        try:
            import ftp_server

            ok = ftp_server.start()
            results["FTP"] = "✅ started" if ok else "⚠️  skipped (missing deps)"
        except Exception as e:
            results["FTP"] = f"❌ error: {e}"
    else:
        results["FTP"] = "— disabled"

    # ── SMB ───────────────────────────────────────────────────────────────
    if _cfg("SMB_ENABLED", True):
        try:
            import smb_server

            ok = smb_server.start()
            results["SMB"] = "✅ started" if ok else "⚠️  skipped (missing deps)"
        except Exception as e:
            results["SMB"] = f"❌ error: {e}"
    else:
        results["SMB"] = "— disabled"

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    for name, status in results.items():
        print(f"  {name:<8}  {status}")

    # Print install hint if anything was skipped due to missing dependencies.
    # WebDAV is intentionally excluded here — it's spawned as a subprocess
    # now, so a missing 'wsgidav' shows up asynchronously as its own
    # "WebDAV: not started" message printed by webdav_server.py itself
    # (in its subprocess's own stdout), not synchronously in `results` here.
    missing_hints = {
        "SFTP": ("paramiko", "paramiko"),
        "FTP": ("pyftpdlib", "pyftpdlib"),
        "SMB": ("impacket", "impacket"),
    }
    needed = [
        pkg
        for name, (lib, pkg) in missing_hints.items()
        if "missing deps" in results.get(name, "")
    ]
    if needed:
        print()
        print(f"  📦 Install missing libraries:")
        print(f"     pip install {' '.join(needed)}")

    print("─" * 56)
    print()


def force_kill_webdav():
    """Fast, best-effort, no-wait kill of the WebDAV subprocess only.

    Added 2026-09-16 for prod_server.py's force-quit path (second Ctrl+C):
    stop_all() below does a graceful proc.terminate() then
    proc.wait(timeout=5) — exactly the kind of window an impatient second
    Ctrl+C can land inside and interrupt, before the wait/fallback kill()
    completes. Since WebDAV runs as a genuinely separate OS process
    (unlike SFTP/FTP/SMB, which are in-process threads that die
    automatically the instant the parent exits via os._exit()), it's the
    one thing that can actually survive as an orphan if force-quit
    doesn't explicitly handle it — this does a plain proc.kill() (SIGKILL/
    TerminateProcess) with no wait at all, fast enough to call right
    before os._exit() without meaningfully delaying the force-quit the
    user asked for. Does NOT touch the watchdog stop event or clear the
    pidfile — the whole process is about to hard-exit anyway.
    """
    try:
        with _webdav_proc_lock:
            proc = _webdav_proc
        if proc is not None and proc.poll() is None:
            proc.kill()
    except Exception:
        pass


def stop_all():
    """
    Stop all running protocol servers gracefully.
    Called automatically when the process exits (daemon threads for
    SFTP/FTP/SMB; the WebDAV subprocess is terminated separately below).
    You can also call this explicitly for a clean shutdown.
    """
    global _webdav_proc

    # Stop the watchdog first so it doesn't try to respawn WebDAV while
    # we're intentionally shutting it down.
    _webdav_watchdog_stop.set()
    with _webdav_proc_lock:
        proc = _webdav_proc
        _webdav_proc = None
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception as e:
            _pm_logger.debug(f"Stop error for webdav subprocess: {e}")
    _clear_webdav_pidfile()

    for mod_name in ("sftp_server", "ftp_server", "smb_server"):
        try:
            import importlib

            mod = importlib.import_module(mod_name)
            if hasattr(mod, "stop"):
                mod.stop()
        except ImportError:
            pass
        except Exception as e:
            _pm_logger.debug(f"Stop error for {mod_name}: {e}")


def status() -> dict:
    """
    Return a dict with the enabled/port status of each protocol.
    Useful for a /api/status endpoint or admin panel.
    """
    return {
        "webdav": {
            "enabled": _cfg("WEBDAV_ENABLED", True),
            "port": _cfg("WEBDAV_PORT", 8080),
            "url": f"http://{LOCAL_IP}:{_cfg('WEBDAV_PORT', 8080)}/",
            # Isolated-subprocess status — see restart_webdav() to recover
            # a wedged-but-alive process (process_alive True but not
            # actually serving requests, e.g. the large-download-cancel bug).
            "process_pid": _webdav_proc.pid if _webdav_proc else None,
            "process_alive": (_webdav_proc.poll() is None) if _webdav_proc else False,
        },
        "sftp": {
            "enabled": _cfg("SFTP_ENABLED", True),
            "port": _cfg("SFTP_PORT", 2222),
            "url": f"sftp://{LOCAL_IP}:{_cfg('SFTP_PORT', 2222)}/",
        },
        "ftp": {
            "enabled": _cfg("FTP_ENABLED", True),
            "port": _cfg("FTP_PORT", 2121),
            "url": f"ftp://{LOCAL_IP}:{_cfg('FTP_PORT', 2121)}/",
        },
        "smb": {
            "enabled": _cfg("SMB_ENABLED", True),
            "port": _cfg("SMB_PORT", 445),
            "fallback_port": _cfg("SMB_FALLBACK_PORT", 8445),
            "share_name": _cfg("SMB_SHARE_NAME", "SharedFolder"),
            "url": f"\\\\{LOCAL_IP}\\{_cfg('SMB_SHARE_NAME', 'SharedFolder')}",
        },
    }
