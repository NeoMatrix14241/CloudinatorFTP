"""
net_utils.py — small, side-effect-free network helpers
--------------------------------------------------------
Extracted from app.py (2026-09-25) specifically so it can be imported
without dragging in app.py's module-level initialization.

Why this exists: webdav_server.py used to do `from app import
get_local_ip` for this one function. Python doesn't import selectively —
that line executes the ENTIRE app.py module top-to-bottom on first
import, not just the one function. Since WebDAV runs as its own separate
OS process (deliberately, for Hypercorn/asyncio isolation — see
webdav_server.py's own docstring), that import was silently duplicating
everything app.py sets up at module level inside a process that's only
supposed to serve WebDAV: a second `watchdog` Observer watching the same
ROOT_DIR as the main app's (each with its own independent
FileIndexManager, each periodically saving to the SAME cache/
file_index.json — a genuine cross-process race, surfacing on Windows as
`WinError 5: Access is denied` whenever one process's os.replace() landed
while the other had the file open for reading), plus a duplicate
search-index crawler, duplicate realtime-stats SSE machinery, and a
duplicate RateLimiter — none of which the WebDAV subprocess has any use
for.

This module has exactly one job and zero side effects on import: nothing
here starts a thread, opens a file, or touches the filesystem beyond the
one UDP no-op socket call inside get_local_ip() itself, which only runs
when the function is actually called. Safe to import from any process.

app.py still exposes get_local_ip too (`from net_utils import
get_local_ip`, re-exported) so sftp_server.py/ftp_server.py/smb_server.py
don't need to change — they run as threads inside the main app's own
process, where app.py's module-level code has already executed exactly
once regardless, so this duplication problem never applied to them.
"""

import socket


def get_local_ip() -> str:
    """
    Resolve the machine's LAN IP without parsing ifconfig/ipconfig.
    Works identically on Windows, Linux, macOS, and Termux (Android).
    A UDP socket to 8.8.8.8:80 sends no packets — it just forces the OS
    to pick the right outbound interface, revealing the real LAN IP.
    Falls back to 127.0.0.1 if the device has no network.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
