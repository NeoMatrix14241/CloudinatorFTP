"""
protocol_manager.py — Unified launcher for WebDAV, SFTP, FTP, and SMB servers
-------------------------------------------------------------------------------
Call start_all() once at server startup (in dev_server.py / prod_server.py
right after 'from app import app') to spin up all enabled protocol servers
in background daemon threads.

Each server is started only if:
  1. The ENABLED flag in config.py is True (or missing, defaulting to True)
  2. The required library is installed (wsgidav / paramiko / pyftpdlib / impacket)

If a library is missing the server is skipped with a helpful message; the
main Flask server is never affected.

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

import socket
import threading
from app import get_local_ip

LOCAL_IP = get_local_ip()

_lock = threading.Lock()
_started = False


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
    if _cfg("WEBDAV_ENABLED", True):
        try:
            import webdav_server

            ok = webdav_server.start()
            results["WebDAV"] = "✅ started" if ok else "⚠️  skipped (missing deps)"
        except Exception as e:
            results["WebDAV"] = f"❌ error: {e}"
    else:
        results["WebDAV"] = "— disabled"

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

    # Print install hint if anything was skipped due to missing dependencies
    missing_hints = {
        "WebDAV": ("wsgidav", "wsgidav"),
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
    Called automatically when the process exits (daemon threads).
    You can also call this explicitly for a clean shutdown.
    """
    for mod_name in ("webdav_server", "sftp_server", "ftp_server", "smb_server"):
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
