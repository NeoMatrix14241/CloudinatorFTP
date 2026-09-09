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
from app import get_local_ip

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


def _cfg(key: str, default):
    """Read a config key with a fallback default (avoids ImportError)."""
    try:
        import config

        return getattr(config, key, default)
    except ImportError:
        return default


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
    try:
        proc = subprocess.Popen(
            [sys.executable, script],
            cwd=_PROJECT_DIR,
            stdout=sys.stdout,
            stderr=sys.stderr,
            stdin=subprocess.DEVNULL,
            **kw,
        )
    except Exception as e:
        print(f"❌ WebDAV: failed to launch subprocess: {e}")
        return None
    _write_webdav_pidfile(proc.pid)
    return proc


def _webdav_watchdog():
    """
    Background loop: respawns the WebDAV subprocess if it exits
    unexpectedly (crash, exit code != 0). A clean exit (code 0 — either
    WEBDAV disabled in config, or a graceful stop via stop_all()/
    restart_webdav()) is NOT respawned.

    Does NOT detect a wedged-but-still-running process (e.g. the
    Hypercorn/asyncio write-retry loop on a cancelled large download) —
    that process never exits, it just stops making progress. For that
    case use restart_webdav() to force a kill + respawn.
    """
    global _webdav_proc
    while not _webdav_watchdog_stop.wait(timeout=2):
        with _webdav_proc_lock:
            proc = _webdav_proc
        if proc is None:
            continue
        ret = proc.poll()
        if ret is None:
            continue  # still running, nothing to do
        if ret == 0:
            break  # intentional/clean exit — don't respawn
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
    global _webdav_proc
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
            import logging

            logging.getLogger(__name__).debug(f"Stop error for webdav subprocess: {e}")
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
            import logging

            logging.getLogger(__name__).debug(f"Stop error for {mod_name}: {e}")


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
