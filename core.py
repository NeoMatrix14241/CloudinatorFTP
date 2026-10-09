"""
core.py - shared application objects, security setup and import-time startup.

Phase 1 of the app.py split (CLAUDE.md 4.69; map: CLAUDE.md "app.py SPLIT MAP").
Everything that used to sit in the top ~1,900 lines of app.py and is NOT a route or
a request/response hook lives here, moved verbatim and in the original order, so
every import-time side effect (ensure_dirs, storage.ensure_root, file monitor,
search crawler, version_history.init, session/CSRF/CSP/CORS setup) runs in the same
sequence as before. Hooks live in middleware.py; routes stay in app.py until their
own phase. This module imports nothing from middleware, routes or app.
"""

# ── Ensure db/ and cache/ directories exist at their configured locations ──
# Must run BEFORE importing config/database/file_index/file_monitor so that
# those modules find their directories already in place.
# setup_storage.py and config.py intentionally do NOT call this.
from paths import ensure_dirs

ensure_dirs()

# Bulk ZIP progress tracking
bulk_zip_progress = {}

# Global flag for cancelling bulk ZIP
bulk_zip_cancelled = {}

# Move this endpoint below app initialization
from quart import (
    Quart,
    g,
    render_template,
    request,
    redirect,
    url_for,
    send_from_directory,
    send_file,
    flash,
    session,
    jsonify,
    Response,
    make_response,
    render_template_string,
    abort,
)
from werkzeug.utils import secure_filename
from werkzeug.exceptions import ClientDisconnected
import os
import sys
import shutil
import json
import asyncio
import threading
import time
import logging
import uuid
import socket

# get_local_ip's real implementation now lives in net_utils.py (no
# side effects on import) — aliased here so the wrapper below can
# re-export it under its original name without self-recursion. See
# net_utils.py's docstring and the wrapper function for why this split
# exists.
from net_utils import get_local_ip as _get_local_ip


async def _stream_from_thread(sync_generator):
    """Bridges a blocking, synchronous generator (e.g. zipstream reading
    files off disk) into an async stream, so building a large ZIP doesn't
    block Hypercorn's event loop — and every other in-flight request —
    for the whole duration of the download. Runs sync_generator's
    iteration in a worker thread and re-yields its items on the loop.

    Used by every route that streams a folder/multi-select ZIP download
    (Response(generate_zip_stream(), ...) previously handed the raw sync
    generator straight to Flask, which was fine under Waitress's
    thread-per-request model but would stall the whole server under
    Quart's single event loop).
    """
    loop = asyncio.get_running_loop()
    out_queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    _DONE = object()

    def _worker():
        try:
            for chunk in sync_generator:
                asyncio.run_coroutine_threadsafe(out_queue.put(chunk), loop).result()
        except Exception as e:  # noqa: BLE001 — re-raised on the loop below
            asyncio.run_coroutine_threadsafe(out_queue.put(e), loop).result()
        finally:
            asyncio.run_coroutine_threadsafe(out_queue.put(_DONE), loop).result()

    threading.Thread(target=_worker, daemon=True).start()

    while True:
        item = await out_queue.get()
        if item is _DONE:
            break
        if isinstance(item, Exception):
            raise item
        yield item


def get_local_ip() -> str:
    """
    Resolve the machine's LAN IP without parsing ifconfig/ipconfig.
    Works identically on Windows, Linux, macOS, and Termux (Android).
    A UDP socket to 8.8.8.8:80 sends no packets — it just forces the OS
    to pick the right outbound interface, revealing the real LAN IP.
    Falls back to 127.0.0.1 if the device has no network.

    MOVED to net_utils.py (2026-09-25), re-exported here so every other
    module that already does `from app import get_local_ip`
    (sftp_server.py, ftp_server.py, smb_server.py) keeps working
    unchanged — they run as threads inside this same process, so
    importing from here was never the problem. webdav_server.py, which
    runs as its own separate OS process, now imports directly from
    net_utils instead — see that module's docstring for why: this
    function used to be defined directly in this file, and merely
    importing it from a fresh process ran this entire 7500+ line module's
    side-effecting top-level code (file_monitor, search index crawler,
    SSE machinery, RateLimiter — all duplicated, uselessly, inside the
    WebDAV subprocess). The function body itself is unchanged.
    """
    return _get_local_ip()


# Ensure ffmpeg and thread prints appear immediately in terminal
sys.stdout.reconfigure(line_buffering=True)
import zipfile
import io
import re
import subprocess
import hashlib
import zipstream
from datetime import datetime
from config import (
    PORT,
    HOST,
    ROOT_DIR,
    CHUNK_SIZE,
    ENABLE_CHUNKED_UPLOADS,
    MAX_CONTENT_LENGTH,
    ALLOWED_EXTENSIONS,
    PERMANENT_SESSION_LIFETIME,
    HLS_MIN_SIZE,
    HLS_FORCE_FORMATS,
    IMG_COMPRESS_MIN_SIZE,
    IMG_WEBP_QUALITY,
    IMG_CACHE_DIR,
    ENABLE_FFMPEG,
    ENABLE_LIBVIPS,
    ENABLE_SEARCH_INDEX,
)
from database import get_session_secret, db

SESSION_SECRET = get_session_secret()
from auth import (
    check_login,
    login_user,
    logout_user,
    current_user,
    is_logged_in,
    get_role,
)
import storage
import version_history
import secrets as _secrets
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# Signs the passkey-unlock cookie for gated share links — independent of the
# login session cookie, since a share-link visitor is never logged in.
_share_unlock_signer = URLSafeTimedSerializer(
    SESSION_SECRET, salt="share-passkey-unlock"
)
_SHARE_UNLOCK_MAX_AGE = 30 * 24 * 3600  # 30 days


# ------------------------------------------------------------------
# Client IP resolution — shared by RateLimiter and the per-request logger
# below, so both agree on "who sent this" instead of RateLimiter having
# its own private copy that only fired on failed logins.
#
# Deployment: this app sits behind a Cloudflare Tunnel (cloudflared,
# orange-cloud/proxied). That means two things for IP trust:
#   1. There's no open inbound port on this box at all — cloudflared
#      makes an OUTBOUND connection to Cloudflare's edge, so nobody can
#      reach this process directly and forge headers the way they could
#      against a plain reverse-proxy with an exposed port. Every request
#      that reaches this app genuinely came through Cloudflare.
#   2. request.remote_addr is therefore useless here — it's cloudflared's
#      local connection to this process, so it reads the same
#      loopback-ish address for every request, real traffic and attack
#      traffic alike.
# CF-Connecting-IP is what to trust instead: Cloudflare sets this itself
# at the edge with the real connecting client's IP and overwrites/strips
# whatever the client tried to put there — unlike X-Forwarded-For, which
# Cloudflare only APPENDS to. A client-forged "X-Forwarded-For: 1.2.3.4"
# arrives at Cloudflare, which appends the real IP after it
# ("1.2.3.4, <real ip>") rather than replacing it — so blindly taking
# XFF's first entry (the old behavior here) would have logged the
# attacker's chosen fake IP, not their real one. CF-Connecting-IP doesn't
# have that hole. X-Forwarded-For is kept only as a fallback for local/
# direct access (e.g. hitting dev_server.py on the LAN with no tunnel in
# front of it, where there's no CF-Connecting-IP to read).
#
# This trust chain assumes the app is ONLY reachable through the tunnel.
# If this port is also directly reachable (bound to 0.0.0.0 with the
# firewall open, port-forwarded, etc.) rather than solely through
# cloudflared, someone could connect directly and set CF-Connecting-IP
# themselves, and it would be trusted here just as wrongly as XFF was.
# Worth double-checking that's not the case if this matters to you.
# ------------------------------------------------------------------
def get_client_ip() -> str:
    cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cf_ip:
        return cf_ip
    return (
        request.headers.get("X-Forwarded-For", request.remote_addr or "")
        .split(",")[0]
        .strip()
    )


# ------------------------------------------------------------------
# Brute-force protection — tracks failed login attempts per IP
# ------------------------------------------------------------------
class RateLimiter:
    """
    Tracks failed login attempts per IP address.
    After MAX_ATTEMPTS failures within WINDOW seconds, the IP is locked
    out for LOCKOUT seconds.
    All state is in-memory — resets on server restart (intentional).
    """

    MAX_ATTEMPTS = 5  # failures before lockout
    WINDOW = 60  # seconds — rolling window for counting failures
    LOCKOUT = 300  # seconds — how long the IP is blocked (5 minutes)

    def __init__(self):
        self._attempts: dict = {}  # ip -> list of failure timestamps
        self._locked: dict = {}  # ip -> lockout-expiry timestamp
        self._lock = threading.Lock()

    def _get_ip(self) -> str:
        return get_client_ip()

    def is_blocked(self) -> bool:
        ip = self._get_ip()
        with self._lock:
            expiry = self._locked.get(ip)
            if expiry:
                if time.time() < expiry:
                    return True
                else:
                    del self._locked[ip]
                    self._attempts.pop(ip, None)
        return False

    def record_failure(self):
        ip = self._get_ip()
        now = time.time()
        with self._lock:
            attempts = [t for t in self._attempts.get(ip, []) if now - t < self.WINDOW]
            attempts.append(now)
            self._attempts[ip] = attempts
            if len(attempts) >= self.MAX_ATTEMPTS:
                self._locked[ip] = now + self.LOCKOUT
                print(f"IP locked out after {self.MAX_ATTEMPTS} failed attempts: {ip}")

    def record_success(self):
        ip = self._get_ip()
        with self._lock:
            self._attempts.pop(ip, None)
            self._locked.pop(ip, None)

    def remaining_lockout(self) -> int:
        ip = self._get_ip()
        with self._lock:
            expiry = self._locked.get(ip, 0)
            return max(0, int(expiry - time.time()))

    def attempts_remaining(self) -> int:
        ip = self._get_ip()
        now = time.time()
        with self._lock:
            recent = [t for t in self._attempts.get(ip, []) if now - t < self.WINDOW]
            return max(0, self.MAX_ATTEMPTS - len(recent))


rate_limiter = RateLimiter()

# File monitoring and real-time updates
from file_monitor import get_file_monitor, init_file_monitor
from search_index import search_index_manager
from realtime_stats import (
    storage_stats_sse,
    trigger_storage_update,
    trigger_fs_activity,
    get_event_manager,
)
from realtime_shares import (
    share_events_sse,
    trigger_share_event,
    trigger_active_shares_changed,
)

# Assembly Queue System
import queue
from dataclasses import dataclass
from typing import Optional


@dataclass
class AssemblyJob:
    file_id: str
    filename: str
    dest_path: str
    total_chunks: int
    created_at: float
    status: str = "pending"  # pending, processing, completed, error
    error_message: Optional[str] = None
    session_id: Optional[str] = None


class AssemblyQueue:
    def __init__(self):
        self.job_queue = queue.Queue()
        self.active_jobs = {}  # file_id -> AssemblyJob
        self.completed_jobs = {}  # file_id -> AssemblyJob (keep for 1 hour)
        self.lock = threading.Lock()

    def add_job(self, file_id, filename, dest_path, total_chunks, session_id=None):
        """Add a new assembly job to the queue"""
        job = AssemblyJob(
            file_id=file_id,
            filename=filename,
            dest_path=dest_path,
            total_chunks=total_chunks,
            created_at=time.time(),
            session_id=session_id,
        )

        with self.lock:
            self.active_jobs[file_id] = job

        self.job_queue.put(job)
        print(f"🔄 Added assembly job for {filename} (ID: {file_id})")
        return job

    def get_job_status(self, file_id):
        """Get the current status of an assembly job"""
        with self.lock:
            if file_id in self.active_jobs:
                return self.active_jobs[file_id]
            elif file_id in self.completed_jobs:
                return self.completed_jobs[file_id]
            return None

    def get_all_active_jobs(self):
        """Get all currently active assembly jobs"""
        with self.lock:
            return list(self.active_jobs.values())

    def get_jobs_for_session(self, session_id):
        """Get all jobs (active + recent completed) for a session"""
        with self.lock:
            jobs = []
            # Active jobs
            for job in self.active_jobs.values():
                if job.session_id == session_id:
                    jobs.append(job)
            # Recent completed jobs (last hour)
            current_time = time.time()
            for job in self.completed_jobs.values():
                if (
                    job.session_id == session_id
                    and current_time - job.created_at < 3600
                ):  # 1 hour
                    jobs.append(job)
            return jobs

    def complete_job(self, file_id, success=True, error_message=None):
        """Mark a job as completed"""
        with self.lock:
            if file_id in self.active_jobs:
                job = self.active_jobs.pop(file_id)
                job.status = "completed" if success else "error"
                if error_message:
                    job.error_message = error_message
                self.completed_jobs[file_id] = job
                print(
                    f"✅ Assembly job completed for {job.filename} (Success: {success})"
                )

                # Untrack the upload when assembly is successfully completed
                if success and job.session_id:
                    try:
                        chunk_tracker.untrack_upload(job.session_id, file_id)
                        print(
                            f"🧹 Untracked completed upload: {file_id} for session {job.session_id}"
                        )
                    except Exception as e:
                        print(f"⚠️ Failed to untrack upload {file_id}: {e}")

                return job
            return None

    def cleanup_old_jobs(self):
        """Remove completed jobs older than 1 hour"""
        with self.lock:
            current_time = time.time()
            expired_jobs = [
                file_id
                for file_id, job in self.completed_jobs.items()
                if current_time - job.created_at > 3600
            ]
            for file_id in expired_jobs:
                del self.completed_jobs[file_id]
            if expired_jobs:
                print(f"🧹 Cleaned up {len(expired_jobs)} old assembly jobs")


# Global assembly queue
assembly_queue = AssemblyQueue()

import mimetypes

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")

# ---------------------------------------------------------------------------
# CSP: SHA-256 hashes of every static inline style="..." attribute value used
# in index.html / viewer.html / index.js. These let the CSP allow exactly
# these inline styles via style-src-attr 'unsafe-hashes' instead of a blanket
# style-src 'unsafe-inline', which would let an attacker inject arbitrary
# styles anywhere on the page.
#
# index.js was added to this list's scope after it became clear it has its
# own static inline style="..." attributes (built via innerHTML template
# strings) that were never covered here before — they were silently being
# dropped by the CSP the whole time. Any inline style="..." attribute in
# index.js that is DYNAMIC (built from a variable, e.g.
# style="color: ${getFileColor(x)}") CANNOT go in this list — a hash only
# matches one exact string. Those must instead be set via element.style.x =
# value in JS (a CSSOM property assignment — exempt from style-src-attr
# entirely, unlike setAttribute('style', ...) or a literal style="..." in
# markup/innerHTML) or reduced to a fixed set of CSS classes. As of this
# writing every dynamic one has already been converted that way — this list
# should only ever need static, fixed string values.
#
# If you add a NEW inline style="..." attribute to index.html, viewer.html,
# or index.js later, that new value's hash won't be in this list and the
# browser will silently drop that one style (console will show a CSP
# violation) until you regenerate this list:
#
#   python3 -c "
#   import re, hashlib, base64, html
#   values = set()
#   for f in ['templates/index.html', 'templates/viewer.html', 'static/js/index.js']:
#       content = open(f, encoding='utf-8').read()
#       for m in re.finditer(r'style=\"([^\"]*)\"', content):
#           v = m.group(1)
#           if '\${' in v:
#               continue  # dynamic — can't be hashed, see note above
#           values.add(html.unescape(v))
#   for v in sorted(values):
#       print(f\"'sha256-{base64.b64encode(hashlib.sha256(v.encode()).digest()).decode()}'\")"
#
# (adjust the index.js path above to wherever it's actually served from)
#
# Caveat: style-src-attr / 'unsafe-hashes' is CSP Level 3. Safari does not
# support it (as of this writing), so Safari visitors will lose the styling
# from these specific inline style="..." attributes (external stylesheets
# and JS-driven element.style.x = ... assignments are unaffected — those
# aren't governed by style-src at all). If Safari support matters for your
# users, keeping 'unsafe-inline' in style-src is the safer tradeoff; this
# hash-based approach was chosen to satisfy stricter CSP scanners instead.
_INLINE_STYLE_HASHES = (
    "'sha256-r25i9SQ35Us6nTLoruoxJdALlPTTv/IeeORrrrUzRK0=' "
    "'sha256-7qyL3LD+dxC9gI5qIgfX5v6DokFCI42AWnxZkoBGoT8=' "
    "'sha256-lcVB6kHisHNwCdUxsNEKDJjPp8hGNXNYnL20Eae5DE8=' "
    "'sha256-WZdhx2SzCX7zHovuZ2+a+y8sBj45N4TBgSfQl4A1nv4=' "
    "'sha256-+AaOZzK2E+0J9BbQSRH8mwtk1I5TAc2NnSTpTzZflJc=' "
    "'sha256-LcyIb7dElRXQXxwxDtvfz0XyjJ6U40EGOE9MBj5ibbk=' "
    "'sha256-/I1tLJ54rW9hhBM7nVdm/+4XIUvJo9X00wYfoJpcF70=' "
    "'sha256-KQf6ggmn2qCLLXaSRHavuYMzHWy2sEXNC7KomW10Xmg=' "
    "'sha256-F9baujUqeoDKfQ2dnPlvbJpJVJjDkNv1WipKtex8yow=' "
    "'sha256-oUGuUZBJIQ6iW5Js4a/fNu+hp3aMVpsZ6jIlzeAWEhA=' "
    "'sha256-TyteffVsWq8HgF3YOUegwJYLyMFy9X0pRNsweUCPsf8=' "
    "'sha256-b0KlPu3vzU/LeqsQ2vQlpPHnvV8e7DPtVmI9IppmnNI=' "
    "'sha256-8BWaAeutIg45vhjU2Q8adJtqk9zxc15uJTfhv0NbgmE=' "
    "'sha256-eccAHNSQBqfYKUDNYg+py0npHiEOfCamlATU/WMib7g=' "
    "'sha256-svGi/Rg7zp3nJoJ4EAur17MxP9/qV5MVttrA45GLwoA=' "
    "'sha256-2AwsEeLaV/IHpjORhXy1GnsX6OpjpfE9PlICcaDnj4o=' "
    "'sha256-Jr2IPEfvhF4Z7LjqMw2sFBG2/BwyPNgH8hS4j0Kze5I=' "
    "'sha256-fA+Gq1RWMzVOfRLxqhYDHEkv5mTE5Id9hCuHr3/ce8A=' "
    "'sha256-WmToIF8dN+S5QYolwfgz3rotAhNTqLEmasXInTk6yUU=' "
    "'sha256-5ERFXPrSxchg3KuJXIpJTfCwXYp8Udn8uBU0sVZlBEg=' "
    "'sha256-zAU6mrv49LKwzXbaX+F7ErY4UEN2/ilHbUI4KQIlJdU=' "
    "'sha256-3r77NK4Z6ydai56SDVy2UjE8tYqRtg3Y8PXTgBXBxLc=' "
    "'sha256-WsTfWDCxyLzkwCtut0G153S6hCsL0+VfSoP1Yy5y8gc=' "
    "'sha256-biLFinpqYMtWHmXfkA1BPeCY0/fNt46SAZ+BBk5YUog=' "
    "'sha256-Ir6vChCKDg9/KP2U0WQWMrI4gEO4309XI0EaCayJ4pQ=' "
    "'sha256-d9z+KPOVMxq/Q8Z6EynnUHayoo0Sgsl++YwXz2m9fhE=' "
    "'sha256-BZI1PyuIrR4tIdThQfv9GHre/Yb+0/R8G1eOMAY8vMA=' "
    "'sha256-ptz686Se/XUHh8rTUDuU0PKUL0yRbmldDI8LOodc+wI=' "
    "'sha256-EZPzprA/HrmKtEbD+m6ZBGfpZbBDUwGAJh40N1DipZQ=' "
    "'sha256-ftJpBGmPKfbqF83L7HADfWrZMnpFDzdrY1ghf43/aRU=' "
    "'sha256-TLgbjUSdbVy121inPSsUxeepzRSqJfJOYQ0P9OLjteI=' "
    "'sha256-9ieazHMmP+99mDOeave9ALQe2O8uPGlsKcqlRN1xtOE=' "
    "'sha256-Mt3avz3KEd+SxFidm0UOgsfssJDbaOujfkFMq66pNqc=' "
    "'sha256-vbLE+aj1FSX0spELBkZ2qQ94bfBF3zBm75zeVBRN7+8=' "
    "'sha256-mv2rrMvJiTh0L/lqG+mZqvQZ2GgpXYbGy9jzuKMDNTo=' "
    "'sha256-aTdbQRvGP3e1XeBg8FHyuGxs78AI4gRBrp4RCtQpQfY=' "
    "'sha256-z46HxwBCCFGlAwyXLabnKjm6W3M7UDQA5YHmTx0uquQ=' "
    "'sha256-XIqgIHk7Mx0cuILsJ4+dn+7fegyo4mTxteDunEm4OWQ=' "
    "'sha256-HySlaiiEGO7UC7rouq09dSadbB3Pg5auhHorOP7OMLE=' "
    "'sha256-t010gU9hvVxsqH9ewxs6l8tQm5Ez5ZlhBmSv99ZfNjA=' "
    "'sha256-IiOeKVA1QyGLALmp1a5dbKwoEyk7LHAmM5+L4p42aig=' "
    "'sha256-lvfRQFIMq67Ovx/BSkYt8qws5JmtbECZNtU4PUq4h4k=' "
    "'sha256-4u26w655+v9v24iVFEIM1kaU764K4ku3lzXesOCCJ7I=' "
    "'sha256-vkCRP7LPuAarIz51OTF9l5kYQMqDY7AFk8PeF46IRCQ=' "
    "'sha256-qQUBUjasnJdhrNlgzajDJnnOf9HGERy1tkajP7dru0c=' "
    "'sha256-UC/rPT8ePS0krShMIz91SpGDtU2xAAufG2ZQqsj3KmI=' "
    "'sha256-zdQPf5K78OGn8y4CK9yFtqUgByZwmgIRi9mvc6tb49I=' "
    "'sha256-wCFZAa1dZsiggSbcMIW5aFunC9l1v0s7qIGBHUVldWs=' "
    "'sha256-CQ7MRS85HJMXW3YxOGAZvjnkdGZwr8MGmR6V1pjpQDM=' "
    "'sha256-PH0DEd1b/ScTdFgwQurj1qsz8izmFSVJPv7y3x4fIzE=' "
    "'sha256-MFnzbRN2ummEtLbjqVmAx9EZ36GDgHykzBkkjODUur8=' "
    "'sha256-tLhJLdhP/19dgmpWYiz9xIF+DCqxjOgU8dXIGTdF3Wg=' "
    "'sha256-NjYDAvf3Yswi9GqXn8q5mE3okYa3Q4PuzJ0DkAhe4yQ=' "
    "'sha256-r+kKTo91UeZ8VS1VQWyNsdB9Zi5TaQKG9Dg7TBeSY/w=' "
    "'sha256-8OJVJw6LnDTwJvgQ15Uij+G5lbrYOWEw1LE+/Kq6L9Y=' "
    "'sha256-jsriSIEfqFC/B9X7+tpl+eS9ypUx8V6BOcnV68ztSZQ=' "
    "'sha256-9ig60SJFAJpRoRoEpSxw6KWwIKRUchVM08ZMUObL1DQ=' "
    "'sha256-sWB6XOuBfsiqNdjt23qlKOInevfQerm+VjzKuzm7I9M=' "
    "'sha256-+Vc1EaQBqwRzEzB1EnS+SnnpCeJh+Bi+gjGJT87SM3I=' "
    "'sha256-dAKIyuEsumLvyLFlrlgzJQt0T2a9q4AgfBmidg4UgJc=' "
    "'sha256-h3YznOZSlYQ2T/3Jzv2EgiySj4U8Y8CwBXdOPW4hu7k=' "
    "'sha256-iK5NXTOsH05WBEU4bMLhEG2/HXIHjskPURnxlqP3Fog=' "
    "'sha256-FMZfA0LYx1qGOGNmQzmXVOXNmPxzmRViqQ7sPTxH3YA=' "
    "'sha256-cICVVvhFn82zHo0E0TTHn7OQdbmnOPx4apHsb4ALb4M=' "
    "'sha256-SZYjMs0U3hA54QFWhfNpEflnP+KvIiRnXOMor5iZgQo=' "
    "'sha256-KDXwFxmUk8bphB8Y70oJCrTy5NA1eRE4eY8YtBFzHbk=' "
    "'sha256-FNGrYfufbCyXUTAe+FIRzXZJordZR26z2rTygC4t4lI=' "
    "'sha256-jtY41J3/AqgOz+JFyBQATgOwvRnJbSRU0sK1JUb7Vtc=' "
    "'sha256-fovNQmL0rXwWkckSMD5QaJIPRdlgwMgfSHQULmjrf0A=' "
    "'sha256-CUYeeW+qK6aN9sIB78XKVx5IejFavF5gpiUZxO72w14=' "
    "'sha256-TYKX08g140mCCzTydWf8yx2U96PISYFmCwIqKmn4roQ=' "
    "'sha256-hiCdyfqY5jkLejsYYDPs16eBb2hAyf26y0KGGGgR1Y0=' "
    "'sha256-YAXWZKFV3jDcZW23JuKauwd8p8v2sWP2lQno1EjMTE0=' "
    "'sha256-GsBdobBqUHnsJL4Y2AGmh1agrRrExMSa5Ux8g9qu7EI=' "
    "'sha256-BQ5eA/mw6jES31KSfh/A55TC7nzftLBWpZBzzDfwUrA=' "
    "'sha256-Sp06Do6sWir54qEPJBpq/hq4FmShf3d7tnObRrV40XA=' "
    "'sha256-hpgnRQgrknYEHM7TNkPerV0IW9uqIhHkxj0SzDGIST8=' "
    "'sha256-RplG6L4DS7tinB+kpxygtAVbINLXXNahDRzdfk1+cwY=' "
    "'sha256-UsOOA4poiDExagMqyBHrj94aHDnzvCDg3iI4EswFiS0=' "
    "'sha256-IuTtgGQymstyVrH9I9l6uJp6gLjJ9QW9k/VwH1OBFPk=' "
    "'sha256-3L/EVCTr6pdzsJZnVQO+uVRk9X2Pc1Nz+WDQJD31/Ak=' "
    "'sha256-JgCtqZG0a58cRleZMam7zrTD76G2pXWpVJ9slnA4+Es=' "
    "'sha256-i7SUXS+H1UryBgDwNFnobea8SMwVjnYL0rGvOD8PIy4=' "
    "'sha256-o2rj/Gic8u14SvdwtadxEkNsIsEkowTRyt/NRHZHmdg=' "
    "'sha256-VoXb0HBC5xgbqNg7NRsxTqMHD8jeFY8Ew5fXiCz3GX4=' "
    "'sha256-aqNNdDLnnrDOnTNdkJpYlAxKVJtLt9CtFLklmInuUAE=' "
    "'sha256-0EZqoz+oBhx7gF4nvY2bSqoGyy4zLjNF+SDQXGp/ZrY=' "
    "'sha256-NudHPjq+wtjofQf9mavUp2gqZIj9pkzEQgjGNVciSg8=' "
    "'sha256-SHY0SLkaoN1bfsrcBa32dJT7QMoVQEgHd95XBg0p/jE=' "
    "'sha256-EmJE8TUego+hQrwTWTKzP0FR9OmqkES7/jmdtYY3/yk=' "
    "'sha256-MpuM1tcGyuu2bCBYRgExbpm3+b7qR0QkgfXDIQQ0Vls=' "
    "'sha256-YlOHamSaY0ai4QEZYjD+9Mf+UG1KI007SUtO6nnQNKQ=' "
    "'sha256-ytj0z3sXS6CFRvCsW9eKWoxIe+9e3IT+Oj8M62IJ/Ac=' "
    "'sha256-mQCI/c9DbNleo/ZiMLl8mjjRMRY7T33/2gljmJF3GQo=' "
    "'sha256-0BY2dc4Z+icxyPhKj2/3TNNa9+5CgJmfqrf7inraJ3c=' "
    "'sha256-4UPH2xZ4U6bOpmGs3BxEo0GZVmpbUZkNf8lrL0HYvFg=' "
    "'sha256-CryCX1yRt50anZ6OH1cFffEJkNUjwyWWqwcM5sQKQ4o=' "
    "'sha256-MG9fl9dQ40AbtNbCFSyyjWxoLlQ1chPyyHPTaHQXjtU=' "
    "'sha256-4Y31uXfvb2tlLh0QMJ43fjefLlCGwwh8lM/sCeKkpto=' "
    "'sha256-TgJQVwAL23+5sBOjWyePt+Ct8lfrbIQ1PTY7CNoAT9g=' "
    "'sha256-zc7xhsgV170rEuPoIssaeSOeF4YDmIe96rN7JCujVyc=' "
    "'sha256-qDx2lRwBtFwvichL63r+EzOvUKXI2vAWAeql+L4CcvI=' "
    "'sha256-K4tYHy3/DDsKrrQWgO9XsaGwb4HyOnEkmnPaXbddqvc=' "
    "'sha256-Htw2WBqtRbH9KPKQfV+9vs9Gm2MWxq3aceazwQcOezY=' "
    "'sha256-fGkDP7tFaZbeV2kt/WyqN2cs2qo39ErOM2XxSNxNMe0=' "
    "'sha256-wbu5VAl7cs5jkQC5RsSyZG0+TGJiIioEPOVhIYNsntw=' "
    "'sha256-6FGICTHHyk8eCQxgG2QJ7FKBvmh0Bad9ny8YAUlogJo=' "
    "'sha256-iuT1LgdNEVTThHpnZwkUc+V1FW84ztl5dKJ8eWZJjVI=' "
    "'sha256-tWmH28u+UOD+TwBRVCmUv4XSGLM3bwZmv5BCa9X43gw=' "
    "'sha256-l8Ql11beu0/kas4wyLi/uHYtkwoGc9vxP2d5zPUle0w=' "
    "'sha256-Vv7wUBsu2D+kFu36NbC05J7Ta8SM6CcvZaHq7V7are4=' "
    "'sha256-ueQyfiv9Hz6/QCe9zgG6oGo4ymD5b6HFmZwC6RJWpQM=' "
    "'sha256-PpZyeb/uN2vEHgWDQLqD6Fz17C0qk8EdQCN3u3ngch0=' "
    "'sha256-N3h02OF5cjS55dyJpDbPWucOroXTyzA2qWpWWxcKwO0=' "
    "'sha256-iq0Z0m764A1/OeseXMFPqJ7brCXUQZIaj1vrzR9ax9w=' "
    "'sha256-dSDoLSm14g+4WtW5g8pUFyaSTnQIpc5DB8o6ZZ/ZHpw=' "
    "'sha256-GqFTJUCWicExXmV0AE20UXYqkOJqOAtjKvC48DVs7rw=' "
    "'sha256-3GABHWx0GJuf2OVqcmjh7PcQNV9yW3UH842ECBwHO4Y=' "
    "'sha256-zHwg6jvnCP3ddKXScxiMY4ZLLIR3rFJIro7HED0j/kI=' "
    "'sha256-NFiCpimeh2u6pfe4jDQiazh5+pTuAb2eggl4+WZbJMI=' "
    "'sha256-Dl4HFNCXafSV452QXkPxJVKqiX5QSSY1Zm7tAhiLBJI=' "
    "'sha256-OVvBzncEtn7q+H7vP0bKUq4sazWwT63XyT4lk39tF04=' "
    "'sha256-jqPfeFdtQz8DQlNJu8TELikip/ow4YibFJn8/FTRAjk=' "
    "'sha256-LTjqMsPXt96oUZEsonzBuEGV35S2K3zfgz3VsgxFK54=' "
    "'sha256-f46QcEOvwjbVktF4ZELkp2OjsBBF3IilXneZe2xpmr4=' "
    "'sha256-UiXlt9djFx1o7crFtCH7sUqquV6B2BX9ozY9jqs43JE=' "
    "'sha256-K+MErBm2dfoNYzPiv+JwnlCpeJjCcnq0XN+FP6+Esz0=' "
    "'sha256-G1BR0wU4PZyN/xje5UjmpZbkO0q6sDomFK2DT81svxA=' "
    "'sha256-CFz7XUx3dO7TOX4RcnZ+osqCc+Owc1o8JNUiD0DGKqQ='"
)

# CSP: SHA-256 hashes of inline <style>...</style> ELEMENTS (not
# attributes) that the vendored video.js/media-chrome player bundle
# injects into its own shadow-DOM components at runtime — as opposed to
# _INLINE_STYLE_HASHES above, which covers style="..." ATTRIBUTES from
# our own templates/JS and is governed by style-src-attr.
#
# This project's own JS (index.js: _injectMobileSpeedHide,
# _initImageZoom) used to inject inline <style> elements too, but those
# were converted to an external stylesheet
# (static/css/video-skin-overrides.css, loaded via <link>) and a rule in
# the main stylesheet respectively — so 'self' alone covers them now and
# they no longer need a hash here.
#
# These two remaining hashes come from the player library's minified
# bundle (functions `Bt` / `Ln`), not from our code, so we can't remove
# the injection — only pin its known-good output. They correspond to
# that library's fixed per-component shadow-root templates rather than
# any per-video computed value, so they should stay stable across
# different videos/screen sizes for a given pinned bundle version. If
# static/js/video.js is ever upgraded, these WILL break (console will
# show the new correct hash — swap it in here).
_INLINE_STYLE_ELEMENT_HASHES = (
    "'sha256-59zjj0xxtVIRnqPtzjuu1HKYGZQR57lKieZWIsMUmFA=' "
    "'sha256-uvVKilsI7vU78t7JP2zAYfRbql0CeUoAO9EWf76oFTc='"
)

app = Quart(__name__)

# ---------------------------------------------------------------------------
# Request logger — every request gets one line with its duration; anything
# over SLOW_REQUEST_THRESHOLD_SECONDS is additionally escalated to WARNING
# with a "SLOW REQUEST" prefix so it's easy to grep for. Logging EVERY
# request (not just slow ones) is deliberate: it lets a recurrence be
# correlated against everything else that was happening at the same
# moment (a periodic background job, another route also going slow at
# the same timestamp, etc.), not just seen in isolation.
#
# Previously had its own console+file handlers writing to a separate
# logs/requests.log. Now a child of logging_setup's shared
# "cloudinatorftp" logger instead, so these lines land in the same daily
# rotating file (logs/prod_server_YYYY-MM-DD.log) as everything else in
# the project rather than a separate file — see logging_setup.py.
# ---------------------------------------------------------------------------
SLOW_REQUEST_THRESHOLD_SECONDS = 2.0

import logging_setup

request_logger = logging_setup.get_logger("requests")

# General-purpose logger for events not tied to a specific HTTP request
# (background jobs like reconcile, startup/shutdown notices, etc.) — added
# 2026-09-15 alongside converting the one identified print()-based error
# (background reconcile failures) that would otherwise have gone silently
# unobserved once manage.sh stopped capturing raw stdout/stderr. The many
# remaining cosmetic print() calls elsewhere are left as-is; convert more
# of them here if a specific one turns out to matter later.
app_logger = logging_setup.get_logger("app")


# ---------------------------------------------------------------------------
# CORS allowlist — localhost, any private LAN address, and your public domain.
# Wildcard "*" (the old `CORS(app)` default) let ANY website read responses
# from your unauthenticated endpoints. This regex instead only allows origins
# that are actually you: localhost/127.0.0.1 (any port), RFC1918 LAN ranges
# (any port), and CLOUDINATOR_PUBLIC_DOMAIN if you set that env var.
#
# Set CLOUDINATOR_PUBLIC_DOMAIN=cloudinator.site (no scheme) if you serve
# through a domain/tunnel. Leave unset and only localhost/LAN are allowed.
#
# Implemented by hand rather than via quart-cors: quart-cors' allow_origin
# only takes exact strings or "*", not regex patterns, so it can't express
# "any port on any RFC1918 address" the way flask-cors' `resources={...}`
# dict could. This after_request hook + explicit OPTIONS route reproduces
# the exact same matching behaviour instead of quietly narrowing it.
# ---------------------------------------------------------------------------
_PUBLIC_DOMAIN = os.environ.get("CLOUDINATOR_PUBLIC_DOMAIN", "").strip()

_CORS_ORIGIN_PATTERNS = [
    r"^https?://localhost(:\d+)?$",
    r"^https?://127\.0\.0\.1(:\d+)?$",
    r"^https?://10(\.\d{1,3}){3}(:\d+)?$",
    r"^https?://172\.(1[6-9]|2\d|3[0-1])(\.\d{1,3}){2}(:\d+)?$",
    r"^https?://192\.168(\.\d{1,3}){2}(:\d+)?$",
]
if _PUBLIC_DOMAIN:
    _CORS_ORIGIN_PATTERNS.append(rf"^https://{re.escape(_PUBLIC_DOMAIN)}$")

_CORS_ORIGIN_REGEXES = [re.compile(p) for p in _CORS_ORIGIN_PATTERNS]


def _cors_origin_allowed(origin: str) -> bool:
    return bool(origin) and any(p.match(origin) for p in _CORS_ORIGIN_REGEXES)


app.secret_key = SESSION_SECRET


def _request_is_secure() -> bool:
    """
    True if this specific request reached us over HTTPS — either directly
    (request.is_secure, e.g. if Flask itself is TLS-terminated) or via a
    reverse proxy/tunnel that terminates TLS and forwards the original
    scheme.

    Two headers are checked because cloudflared (Cloudflare Tunnel) has a
    known gap where it doesn't reliably set X-Forwarded-Proto when relaying
    an HTTPS request to a plain http:// local service — but it does
    consistently send the older CF-Visitor header (JSON, e.g.
    '{"scheme":"https"}') on every proxied request, tunnel or not. Checking
    both covers a standard reverse proxy (X-Forwarded-Proto) and Cloudflare
    specifically (CF-Visitor), whichever is actually present.

    NOTE — this used to also mean "LAN/localhost requests won't carry either
    header, so they correctly fall through to False here." That was true
    under the old Waitress setup, where LAN access was plain HTTP. It is NO
    LONGER true post-Quart/Hypercorn migration: prod_server.py now serves
    HTTPS directly to every client including LAN/WiFi, so request.is_secure
    is True for them too. This function is still fine to use for things
    like the Secure-cookie flag and Clear-Site-Data, where "any HTTPS
    connection, even our own self-signed one" is the right test. It is
    explicitly NOT fine for HSTS — see _request_via_trusted_tls() below.
    """
    if request.is_secure:
        return True

    if request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        return True

    cf_visitor = request.headers.get("CF-Visitor", "")
    if cf_visitor:
        try:
            if json.loads(cf_visitor).get("scheme") == "https":
                return True
        except (ValueError, AttributeError):
            pass

    return False


def _request_via_trusted_tls() -> bool:
    """
    True ONLY when this request came through the Cloudflare tunnel — i.e.
    a real, publicly-trusted CA certificate was validated by the client,
    not Hypercorn's own self-signed one.

    This is deliberately stricter than _request_is_secure() and exists
    ONLY for gating the HSTS header. request.is_secure now being True for
    direct LAN/WiFi connections (see the migration note in
    _request_is_secure()'s docstring) means those clients are all on the
    self-signed cert whenever they're not tunneled. HSTS is a ratchet: once
    a browser receives it for a host, that browser refuses to offer a
    certificate-warning bypass for that host for the entire max-age (a
    year, here) — no "Proceed anyway" link, no user recourse (this is
    standard, spec'd browser behavior, not a bug in any one browser).
    Sending it to a device running on an unimported self-signed cert
    doesn't just warn them once — it can lock that device out of the app
    entirely (e.g. right after logout forces a fresh TLS handshake) until
    the HSTS entry expires or is manually cleared on that device.

    request.is_secure being True by itself must NEVER count here — under
    this deployment it always means Hypercorn terminated TLS directly with
    the self-signed cert (the tunnel forwards to the app over plain HTTP
    and is identified via the headers below instead), so it's exactly the
    case HSTS needs to be withheld from.
    """
    if request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        return True

    cf_visitor = request.headers.get("CF-Visitor", "")
    if cf_visitor:
        try:
            if json.loads(cf_visitor).get("scheme") == "https":
                return True
        except (ValueError, AttributeError):
            pass

    return False


# ---------------------------------------------------------------------------
# Dynamic "Secure" cookie flag — works over plain HTTP on localhost/LAN AND
# over HTTPS on the public domain, from the same running server.
#
# Flask's SESSION_COOKIE_SECURE is normally a static True/False, which can't
# satisfy both cases at once: True would stop the cookie being sent at all
# over LAN http://, and False would leave it sendable over http on the public
# domain. Overriding get_cookie_secure() makes the flag follow each request:
# secure when the browser actually connected over HTTPS, not secure when it
# didn't (LAN/localhost). Uses _request_is_secure() so it also works when
# reached through a TLS-terminating tunnel/proxy — see that function's
# docstring.
# ---------------------------------------------------------------------------
from quart.sessions import SecureCookieSessionInterface


class _DynamicSecureSessionInterface(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        return _request_is_secure()


app.session_interface = _DynamicSecureSessionInterface()

# Configure session handling.
# PERMANENT_SESSION_LIFETIME now comes from config.py (single source of truth —
# previously app.py hardcoded its own 86400s value and ignored config.py entirely,
# so the setup wizard's "session timeout" prompt didn't actually do anything).
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,  # explicit; JS never needs to read this cookie
    PERMANENT_SESSION_LIFETIME=PERMANENT_SESSION_LIFETIME,
    SESSION_REFRESH_EACH_REQUEST=True,  # cookie expiry slides forward on every request
    SESSION_COOKIE_NAME="cloudinator_session",
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,  # now actually enforced by Quart, was previously unset
)

# ---------------------------------------------------------------------------
# CSRF protection for every state-changing request (POST/PUT/PATCH/DELETE).
# The frontend sends the token as either a hidden form field ("csrf_token")
# or the "X-CSRFToken"/"X-CSRF-Token" header — see index.js/login.html.
#
# Hand-rolled instead of quart_wtf: quart-wtf's only release (0.0.1) hard-pins
# quart<0.19, which in turn needs werkzeug~=2.3 — incompatible with modern
# Quart/Werkzeug and everything else in this app's dependency stack (verified
# directly: installing quart-wtf forces a Werkzeug downgrade that breaks
# Quart's own import). This reimplements only what's actually used here:
# a session-tied random token, header-or-form validation on unsafe methods,
# and an .exempt() decorator for the two anonymous share-link routes.
# Token lives inside the signed session cookie (SecureCookieSessionInterface,
# itsdangerous-backed) — same trust boundary flask-wtf's session-tied tokens
# relied on, not a bare double-submit cookie.
# ---------------------------------------------------------------------------
_CSRF_HEADER_NAMES = ["X-CSRFToken", "X-CSRF-Token"]
_CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def generate_csrf() -> str:
    """Returns this session's CSRF token, minting one on first call. Exposed
    to Jinja as csrf_token() — same name/usage as flask-wtf's template global,
    so index.html's <meta> tag and login.html's hidden field are unchanged."""
    token = session.get("csrf_token")
    if not token:
        token = _secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


class CSRFProtect:
    def __init__(self, app=None):
        self._exempt_endpoints: set = set()
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        app.jinja_env.globals["csrf_token"] = generate_csrf
        app.before_request(self._protect)

    def exempt(self, view):
        """Marks the endpoint exempt, resolved by endpoint name at request
        time rather than by wrapping the function — works regardless of
        whether @csrf.exempt sits above or below @app.route."""
        self._exempt_endpoints.add(view.__name__)
        return view

    async def _protect(self):
        if request.method in _CSRF_SAFE_METHODS:
            return
        if request.endpoint is None or request.endpoint in self._exempt_endpoints:
            return

        expected = session.get("csrf_token")
        if not expected:
            abort(400, description="CSRF token missing")

        provided = None
        for header_name in _CSRF_HEADER_NAMES:
            provided = request.headers.get(header_name)
            if provided:
                break
        if not provided:
            form = await request.form
            provided = form.get("csrf_token")

        if not provided or not secrets_compare(provided, expected):
            abort(400, description="CSRF token missing or incorrect")


# Phase 1 (CLAUDE.md 4.69): created WITHOUT the app on purpose. middleware.py calls
# csrf.init_app(app) at the ORIGINAL position (after _start_request_timer, before
# validate_session) so CSRFProtect._protect keeps its place in the before_request order.
csrf = CSRFProtect()


# 4.60: coalesce on-demand reconciles. Every mutating route used to start its own
# full-tree walk thread, so N quick changes (e.g. 10 mkdirs) meant N overlapping
# walks of the HDD. Now: one walk at a time; changes that arrive while it runs
# queue exactly ONE follow-up walk (the running walk may have missed them).
_reconcile_gate = threading.Lock()
_reconcile_running = False
_reconcile_rerun = False


def _trigger_reconcile(settle=False):
    """Kick off a background reconcile so file/dir counts correct themselves
    immediately after mutations (delete, move, rename, copy) instead of waiting 15 min.

    IMPORTANT: We capture the snapshot BEFORE reconcile starts and always force-push
    SSE afterwards. Without this, a race between watchdog and the reconcile walk
    causes both to see no change and neither fires the SSE update:

      1. Copy finishes -> watchdog on_created events update _file_count/_total_size
         in memory but have NOT yet called _notify_and_save / updated last_snapshot.
      2. Reconcile walk finishes -> old_snapshot = build_snapshot() already has the
         NEW correct counts (watchdog updated the counters) -> old == new ->
         _notify_changes NOT called -> last_snapshot set to new correct values.
      3. Watchdog debounce fires -> old = last_snapshot (now the new correct values
         set by reconcile) -> new = build_snapshot() (same) -> no push again.
      Result: zero SSE pushes, client stuck until manual refresh.

    Fix: _reconcile() now always force-pushes a reconcile_complete=True SSE at the
    end regardless of drift, so this explicit trigger_storage_update call below is
    a belt-and-suspenders safety net only.

    NOTE: settle=True used to arm set_pending_reconcile() AFTER the walk — that
    caused an unnecessary 4th full walk per copy.  It is no longer needed because
    _reconcile() already handles the epoch guard that prevents double-counting from
    the watchdog backlog that drains after copytree finishes.
    """
    import threading
    from file_monitor import get_file_monitor
    from realtime_stats import trigger_storage_update

    global _reconcile_running, _reconcile_rerun
    with _reconcile_gate:
        if _reconcile_running:
            _reconcile_rerun = True  # one follow-up walk after the current one
            print("🔄 Reconcile already running — follow-up queued")
            return
        _reconcile_running = True

    def _run():
        global _reconcile_running, _reconcile_rerun
        while True:
            _run_once()
            with _reconcile_gate:
                if _reconcile_rerun:
                    _reconcile_rerun = False
                    continue
                _reconcile_running = False
                return

    def _run_once():
        try:
            monitor = get_file_monitor()
            # _reconcile() will push incremental walk-progress SSE + a final
            # reconcile_complete SSE internally.  The explicit push below is
            # kept only as a safety net for the case where the walk saw no drift
            # (old == new) but the race condition described above means last_snapshot
            # was already updated before reconcile ran.
            monitor._reconcile()
            new_snap = monitor.get_current_snapshot()
            print(
                f"\U0001f4e1 Reconcile complete (settle={settle}): "
                f"{getattr(new_snap, 'file_count', '?')} files"
            )
        except Exception as e:
            app_logger.error(f"Background reconcile error: {e}", exc_info=True)

    threading.Thread(target=_run, daemon=True).start()


storage.ensure_root()

# Initialize file system monitoring
file_monitor = init_file_monitor()
file_monitor.add_change_callback(trigger_storage_update)
file_monitor.add_activity_callback(trigger_fs_activity)  # 4.64
print(f"📡 File system monitoring started for: {ROOT_DIR}")

# Start search index crawler (daemon thread, non-blocking).
# Only in the MAIN server process: the WebDAV / Version Engine subprocesses
# import this module too, and a second crawler on the same search_index.db
# means a duplicate full-tree walk and (when the DB is empty) two processes
# wiping and refilling the same tables at once.
_AUX_PROC = os.path.basename(sys.argv[0]).lower() in (
    "webdav_server.py",
    "version_engine.py",
)
if ENABLE_SEARCH_INDEX and _AUX_PROC:
    print(
        "ℹ️  Search index crawler skipped in this helper process (main server owns it)"
    )
elif ENABLE_SEARCH_INDEX:
    search_index_manager.start_crawler()
else:
    print("ℹ️  Search index disabled — using os.walk fallback for all searches")

# Version History web UI — logic-only module (version_history.py), no
# routes registered by importing it (see its own docstring). init() here
# bootstraps its Engine instance's schema/directories exactly once, same
# spot as file_monitor/search_index's own one-time startup above — NOT
# the same thing as version_engine.start(), which spawns the separate
# Version Engine subprocess and lives in dev_server.py/prod_server.py
# only. This app.py-side init() just needs a schema-bootstrapped Engine
# to run read/restore/delete queries against the same SQLite DB that
# subprocess already writes to (safe under WAL mode — see
# version_engine.py's own status() docstring for the same pattern).
version_history.init()
print(
    f"🕓 Version History web UI ready (recovered-files dir: {version_history.RECOVERED_ROOT})"
)


def _lean_redirect(location, code=302):
    # Quart's own redirect() (like Flask's) sends a small HTML body with a
    # clickable fallback link. Browsers never show it — they follow the
    # Location header automatically — but ZAP's "Big Redirect Detected"
    # heuristic compares body size against a bare-minimum prediction and
    # flags the difference as a potential info leak. This is the exact
    # unauthenticated "/" -> "/login" redirect ZAP hit (a 301 issued from
    # validate_session below), so give it an empty body instead of pulling
    # in the full page-with-link HTML.
    response = Response("", status=code)
    response.headers["Location"] = location
    # A 301 is cacheable FOREVER by default. This redirect is produced by
    # validate_session for anonymous callers, and after_request only adds
    # no-store for logged-in/known endpoints, so without this a single
    # unauthenticated hit on e.g. /api/files/ was cached by the browser
    # and replayed from disk on every later call, even after login.
    response.headers["Cache-Control"] = "no-store"
    return response


def _wants_json_auth_error():
    """Same test login_required uses: API/XHR callers get 401 JSON, not a redirect."""
    return (
        request.path.startswith("/api/")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )


def _unauthenticated_response():
    if _wants_json_auth_error():
        return (
            jsonify({"error": "Session expired", "redirect": "/login"}),
            401,
            {"Cache-Control": "no-store"},
        )
    return _lean_redirect(url_for("login"), code=301)


# Chunk Tracker Class for better session management
class ChunkTracker:
    def __init__(self):
        self.active_uploads = {}  # session_id -> set of file_ids
        self.lock = threading.RLock()  # RLock: cleanup_interrupted_uploads() holds
        # this lock and calls untrack_upload(), which re-acquires it on the same
        # thread. A plain Lock() deadlocks there; RLock() allows re-entry.
        self.upload_timestamps = {}  # file_id -> timestamp

    def track_upload(self, session_id, file_id):
        with self.lock:
            if session_id not in self.active_uploads:
                self.active_uploads[session_id] = set()
            self.active_uploads[session_id].add(file_id)
            self.upload_timestamps[file_id] = time.time()
            print(f"📊 Tracking upload: {file_id} for session {session_id}")

    def untrack_upload(self, session_id, file_id):
        with self.lock:
            if session_id in self.active_uploads:
                self.active_uploads[session_id].discard(file_id)
                if not self.active_uploads[session_id]:
                    del self.active_uploads[session_id]
            self.upload_timestamps.pop(file_id, None)
            print(f"📊 Untracked upload: {file_id} for session {session_id}")

    def cleanup_session_chunks(self, session_id):
        """Clean up all chunks for a session"""
        with self.lock:
            if session_id in self.active_uploads:
                file_ids = self.active_uploads[session_id].copy()
                for file_id in file_ids:
                    try:
                        storage.cleanup_chunks(file_id)
                        print(
                            f"🧹 Cleaned up abandoned chunks for session {session_id}: {file_id}"
                        )
                    except Exception as e:
                        print(f"❌ Error cleaning up chunks for {file_id}: {e}")
                    self.upload_timestamps.pop(file_id, None)
                del self.active_uploads[session_id]
                print(f"🧹 Cleaned up all chunks for session: {session_id}")

    def cleanup_orphaned_chunks(self):
        """Find and cleanup chunks that don't belong to any active session"""
        chunks_dir = os.path.join(ROOT_DIR, ".chunks")
        if not os.path.exists(chunks_dir):
            return

        try:
            with self.lock:
                all_tracked_files = set()
                for file_ids in self.active_uploads.values():
                    all_tracked_files.update(file_ids)

                current_time = time.time()
                cleaned_count = 0

                # Find chunks that aren't tracked by any session
                for file_id in os.listdir(chunks_dir):
                    chunk_dir = os.path.join(chunks_dir, file_id)
                    if not os.path.isdir(chunk_dir):
                        continue

                    # CRITICAL: Never cleanup chunks for files currently being assembled
                    if assembly_queue.get_job_status(file_id):
                        print(
                            f"🔐 Skipping cleanup for {file_id} - currently being assembled"
                        )
                        continue

                    # Also check for assembly protection marker
                    assembly_marker = os.path.join(chunk_dir, ".assembling")
                    if os.path.exists(assembly_marker):
                        print(
                            f"🔐 Skipping cleanup for {file_id} - assembly marker present"
                        )
                        continue

                    should_cleanup = False
                    cleanup_reason = ""

                    if file_id not in all_tracked_files:
                        # Check age before cleanup
                        timestamp_file = os.path.join(chunk_dir, ".timestamp")

                        if os.path.exists(timestamp_file):
                            try:
                                with open(timestamp_file, "r") as f:
                                    timestamp = float(f.read().strip())
                                # Cleanup untracked chunks older than 45 minutes.
                                # Must be > cleanup_interrupted_uploads timeout (30 min)
                                # so we never delete chunks that are simply backgrounded.
                                if current_time - timestamp > 2700:
                                    should_cleanup = True
                                    cleanup_reason = (
                                        f"untracked >45min old (abandoned upload)"
                                    )
                            except (ValueError, OSError):
                                should_cleanup = True
                                cleanup_reason = "corrupted timestamp file"
                        else:
                            # No timestamp, cleanup if dir is older than 45 minutes
                            try:
                                dir_mtime = os.path.getmtime(chunk_dir)
                                if current_time - dir_mtime > 2700:
                                    should_cleanup = True
                                    cleanup_reason = "no timestamp >45min old"
                            except OSError:
                                should_cleanup = True
                                cleanup_reason = "cannot read metadata"
                    else:
                        # Even tracked files - cleanup if very old (stale uploads)
                        file_timestamp = self.upload_timestamps.get(
                            file_id, current_time
                        )
                        if current_time - file_timestamp > 3600:  # 1 hour
                            should_cleanup = True
                            cleanup_reason = "tracked but stale >1hr"
                            print(
                                f"🧹 Cleaning up stale tracked chunks (>1hr): {file_id}"
                            )

                    if should_cleanup:
                        try:
                            storage.cleanup_chunks(file_id)
                            cleaned_count += 1
                            print(
                                f"🧹 Cleaned up orphaned chunks: {file_id} ({cleanup_reason})"
                            )
                        except Exception as e:
                            print(
                                f"❌ Failed to cleanup orphaned chunks {file_id}: {e}"
                            )

                        # Remove from tracking if it was tracked
                        if file_id in all_tracked_files:
                            for session_id, file_set in self.active_uploads.items():
                                file_set.discard(file_id)
                            self.upload_timestamps.pop(file_id, None)

                if cleaned_count > 0:
                    print(
                        f"🧹 Orphaned chunk cleanup completed: {cleaned_count} directories removed"
                    )

        except Exception as e:
            print(f"❌ Error in orphaned chunk cleanup: {e}")

    def cleanup_interrupted_uploads(self):
        """Detect and cleanup uploads that were interrupted (no activity for 30+ minutes).

        NOTE: The timeout is intentionally long (30 min) so that background-tab throttling
        does NOT trigger premature cleanup.  Browsers freeze JS timers/fetch in hidden tabs,
        so a 2-minute window incorrectly treated active uploads as abandoned whenever the
        user switched away for more than 2 minutes.  30 minutes gives plenty of headroom
        for large folder uploads that are paused while the user works in another tab.
        """
        current_time = time.time()
        interrupted_uploads = []

        try:
            with self.lock:
                for session_id, file_ids in list(self.active_uploads.items()):
                    for file_id in list(file_ids):
                        timestamp = self.upload_timestamps.get(file_id)
                        if (
                            timestamp and (current_time - timestamp) > 1800
                        ):  # 30 minutes of inactivity
                            interrupted_uploads.append((session_id, file_id))
                            print(
                                f"🧹 Detected interrupted upload: {file_id} (inactive for {int(current_time - timestamp)}s)"
                            )

                # Clean up interrupted uploads
                for session_id, file_id in interrupted_uploads:
                    try:
                        self.untrack_upload(session_id, file_id)
                        storage.cleanup_chunks(file_id)
                        print(f"🧹 Cleaned up interrupted upload: {file_id}")
                    except Exception as e:
                        print(f"❌ Failed to cleanup interrupted upload {file_id}: {e}")

                if interrupted_uploads:
                    print(
                        f"🧹 Interrupted upload cleanup completed: {len(interrupted_uploads)} uploads cleaned"
                    )

        except Exception as e:
            print(f"❌ Error in interrupted upload cleanup: {e}")

    def get_stats(self):
        """Get statistics about active uploads"""
        with self.lock:
            total_sessions = len(self.active_uploads)
            total_uploads = sum(
                len(file_set) for file_set in self.active_uploads.values()
            )
            return {
                "active_sessions": total_sessions,
                "active_uploads": total_uploads,
                "tracked_files": list(self.upload_timestamps.keys()),
            }


# Global chunk tracker instance
chunk_tracker = ChunkTracker()


# ------------------------------------------------------------------
# "Revoke all shares" confirmation codes — a fresh random 10-digit string
# is issued per attempt and must be typed back exactly before the revoke-all
# admin action runs. In-memory, single-use, short-lived (like the rate
# limiter above) — not persisted, resets on restart, which is fine since a
# stale code is simply invalid.
# ------------------------------------------------------------------
_revoke_all_codes = {}  # nonce -> {"code": str, "session_id": str, "issued_at": float}
_revoke_all_codes_lock = threading.Lock()
_REVOKE_CODE_TTL = 120  # seconds a code stays valid


def _issue_revoke_all_code(session_id: str) -> tuple:
    import random

    nonce = str(uuid.uuid4())
    code = "".join(random.choices("0123456789", k=10))
    with _revoke_all_codes_lock:
        # Only one outstanding code per session — a fresh attempt invalidates any prior one
        for existing_nonce, entry in list(_revoke_all_codes.items()):
            if entry["session_id"] == session_id:
                _revoke_all_codes.pop(existing_nonce, None)
        _revoke_all_codes[nonce] = {
            "code": code,
            "session_id": session_id,
            "issued_at": time.time(),
        }
    return nonce, code


def _check_revoke_all_code(session_id: str, nonce: str, typed_code: str) -> bool:
    with _revoke_all_codes_lock:
        entry = _revoke_all_codes.pop(
            nonce, None
        )  # single-use: pop regardless of outcome
    if not entry:
        return False
    if entry["session_id"] != session_id:
        return False
    if time.time() - entry["issued_at"] > _REVOKE_CODE_TTL:
        return False
    return secrets_compare(entry["code"], typed_code or "")


def secrets_compare(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)


def login_required(f):
    from functools import wraps

    @wraps(f)
    async def decorated(*args, **kwargs):
        if not is_logged_in():
            # API and XHR requests: return 401 JSON so the client can handle it
            # without breaking an in-progress upload with a page redirect.
            if (
                request.path.startswith("/api/")
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or request.accept_mimetypes.best == "application/json"
            ):
                return jsonify({"error": "Session expired", "redirect": "/login"}), 401
            return redirect(url_for("login"))
        return await f(*args, **kwargs)

    return decorated


def get_protected_files():
    """Get set of file IDs that should be protected from cleanup (currently being assembled)"""
    protected_files = set()
    try:
        for job in assembly_queue.get_all_active_jobs():
            protected_files.add(job.file_id)
    except Exception as e:
        print(f"⚠️ Warning: Could not get active assembly jobs: {e}")

    return protected_files


def cleanup_stale_chunks_on_request():
    """Clean up chunks that are older than 1 hour - called on each request"""
    try:
        # Get all active assembly jobs to avoid cleaning their chunks
        active_assembly_jobs = get_protected_files()

        if active_assembly_jobs:
            print(
                f"🔐 Protecting {len(active_assembly_jobs)} files from cleanup (currently being assembled)"
            )

        # Pass the protected file IDs to the cleanup function
        storage.cleanup_old_chunks(
            max_age_hours=1, protected_files=active_assembly_jobs
        )
    except Exception as e:
        print(f"❌ Error in stale chunk cleanup: {e}")
