"""
lanman_guard.py — Windows native SMB service ("LanmanServer") state tracker
"""

import ctypes
import json
import os
import platform
import subprocess
from datetime import datetime, timezone

_IS_WINDOWS = platform.system() == "Windows"

_PS_TIMEOUT = 15  # seconds — generous; PowerShell cold-start can be slow


# ── Internal helpers ────────────────────────────────────────────────────────


def run_ps(cmd: str) -> str:
    """Run a PowerShell command and return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True,
        text=True,
        timeout=_PS_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "powershell command failed")
    return result.stdout.strip()


def is_elevated() -> bool:
    """True if the current process is running with Administrator rights."""
    if not _IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_lanman_state() -> dict:
    """Query LanmanServer's current Status and StartType via PowerShell."""
    out = run_ps(
        "Get-Service LanmanServer | Select-Object Status,StartType | ConvertTo-Json -Compress"
    )
    data = json.loads(out)

    # PowerShell serializes enums as either a plain string or
    # {"value":N,"Value":"Name"} depending on version — normalize both.
    def _norm(v):
        if isinstance(v, dict):
            return v.get("Value") or v.get("value") or str(v)
        return str(v)

    return {"status": _norm(data["Status"]), "start_type": _norm(data["StartType"])}


def can_bind_445() -> bool:
    """Direct, unambiguous test: can ANY process bind port 445 right now?
    This is the only signal that actually proves whether the change has
    taken effect — checking boot time is not reliable, since Windows' Fast
    Startup can make a shutdown/power-on cycle skip a true reinitialization
    (only a real Restart guarantees that), so we test the real thing
    instead of inferring it indirectly."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", 445))
        return True
    except OSError:
        return False
    finally:
        s.close()


# ── Shared pending-state file — written by smb_setup.py, read by smb_server.py ──


def get_pending_state(state_path: str) -> dict | None:
    """Return the pending-disable state dict, or None if there isn't one."""
    if not os.path.exists(state_path):
        return None
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def mark_disable_pending(state_path: str, original_start_type: str, was_running: bool):
    """Called by smb_setup.py right after successfully disabling LanmanServer,
    to record what it needs to be restored to later and that a restart is
    still owed before port 445 will actually work."""
    state = {
        "original_start_type": original_start_type,
        "was_running": was_running,
        "changed_at": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def clear_pending_state(state_path: str):
    """Called either by smb_server.py once it confirms 445 actually works
    (the setup is done, nothing left to track), or by smb_setup.py's
    restore action (going back to native sharing, nothing left to track
    either way)."""
    try:
        os.remove(state_path)
    except FileNotFoundError:
        pass
