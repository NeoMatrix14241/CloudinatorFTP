"""
routes/image_preview.py - image preview / format conversion / WebP compression
(Phase 3 of the split, CLAUDE.md 4.71).

Moved verbatim from app.py. Gets shared objects via `from core import ...`; imports no other
route module.
"""

from core import app, login_required

from quart import jsonify, send_file, send_from_directory
import os
import json
import asyncio
import threading
import time
import re
import hashlib
from config import (
    ROOT_DIR,
    IMG_COMPRESS_MIN_SIZE,
    IMG_WEBP_QUALITY,
    ENABLE_LIBVIPS,
)
import storage

# ═════════════════════════════════════════════════════════════════════════════
# IMAGE PREVIEW — Format Conversion & Lossless/Lossy WebP Compression
# ═════════════════════════════════════════════════════════════════════════════
#
# Any image request routed through /image_preview/<path> is handled here:
#
#   ┌─────────────────────────────────────────────────────────────────┐
#   │ Non-native format (tif/tiff/bmp/heic/psd/raw/dng/…)?           │
#   │   → Convert to lossless WebP, cache in cache/img/              │
#   │                                                                 │
#   │ File size > 15 MB (any format)?                                 │
#   │   → Compress to WebP Q=50, cache in cache/img/                 │
#   │                                                                 │
#   │ Small native image (jpg/png/gif/webp/svg ≤ 15 MB)?             │
#   │   → Serve directly from ROOT_DIR (no processing)               │
#   └─────────────────────────────────────────────────────────────────┘
#
# DPI is preserved via pyvips' automatic EXIF/XMP/IPTC passthrough.
# Cache lives in cache/img/ — outside ROOT_DIR, so the watchdog file
# listing never surfaces these .webp artefacts to end-users.
#
# Termux install:
#   pkg install libvips          # native C library
#   pip install pyvips           # Python binding
#
# Optional (for camera RAW support):
#   pkg install dcraw            # adds CR2/NEF/DNG/ARW decode support
# ═════════════════════════════════════════════════════════════════════════════

# ── Constants ─────────────────────────────────────────────────────────────────
_IMG_CACHE_THRESHOLD = (
    IMG_COMPRESS_MIN_SIZE  # configurable via Image Settings in config.py
)

# Extensions the browser CANNOT render natively → always convert to WebP
_IMG_NON_NATIVE: frozenset = frozenset(
    {
        # TIFF family
        "tif",
        "tiff",
        # Bitmap
        "bmp",
        "dib",
        # Photoshop
        "psd",
        "psb",
        # Apple HEIF / HEIC
        "heic",
        "heif",
        # Camera RAW formats
        "raw",
        "cr2",
        "cr3",
        "nef",
        "nrw",
        "arw",
        "srf",
        "sr2",  # Sony
        "dng",  # Adobe DNG
        "orf",  # Olympus
        "rw2",  # Panasonic
        "raf",  # Fujifilm
        "3fr",
        "mef",
        "mos",
        "erf",  # Hasselblad / Mamiya / Kodak
        "kdc",
        "dcr",  # Kodak
        "mrw",  # Minolta
        "x3f",  # Sigma
        # HDR / linear
        "exr",
        "hdr",
        "rgbe",
        # Other non-native
        "tga",
        "pcx",
        "icb",
        "vda",
        "vst",
        "wmf",
        "emf",  # Windows metafiles
        "jxl",  # JPEG XL (no universal browser support yet)
        "jp2",
        "jpx",
        "j2k",
        "jpf",  # JPEG 2000
        "avif",  # AVIF (not universal; convert for safety)
        "ico",  # ICO (multi-frame, browser rendering varies)
    }
)

# Extensions browsers handle natively (conversion only for size > threshold)
_IMG_NATIVE: frozenset = frozenset(
    {
        "jpg",
        "jpeg",
        "png",
        "gif",
        "webp",
        "svg",
    }
)

# All recognised image extensions = union of both sets
_ALL_IMG_EXTS: frozenset = _IMG_NATIVE | _IMG_NON_NATIVE

# ── Internal state for deduplicating concurrent conversions ───────────────────
_img_status_lock = threading.Lock()
_img_events_mutex = threading.Lock()
_img_conv_events: dict = {}  # cache_key → threading.Event


# ── Cache directory helpers ────────────────────────────────────────────────────


def _img_cache_root() -> str:
    """Return (and create) the configured image cache directory."""
    from paths import get_img_cache_dir

    img_root = get_img_cache_dir(create=True)
    return img_root


def _img_cache_key(full_path: str) -> str:
    """
    Stable 32-char hex key derived from (file_size, mtime).
    A file whose content changes (different mtime/size) gets a new key and
    is re-converted automatically; the stale cache entry is left for the
    periodic cleanup to remove.
    """
    try:
        st = os.stat(full_path)
        fingerprint = f"{st.st_size}:{st.st_mtime}"
    except OSError:
        fingerprint = full_path
    return hashlib.md5(fingerprint.encode()).hexdigest()


def _img_cached_path(cache_key: str) -> str:
    """Primary cache path — WebP (used when dimensions are within WebP limits)."""
    return os.path.join(_img_cache_root(), f"{cache_key}.webp")


def _img_cached_path_jpg(cache_key: str) -> str:
    """Fallback cache path — JPEG (used when image exceeds WebP 16383px limit)."""
    return os.path.join(_img_cache_root(), f"{cache_key}.jpg")


def _img_cached_path_png(cache_key: str) -> str:
    """Last-resort cache path — PNG (used when image exceeds JPEG 65535px limit)."""
    return os.path.join(_img_cache_root(), f"{cache_key}.png")


def _img_find_cached(cache_key: str):
    """
    Return (cached_file_path, mimetype) for a completed conversion, or
    (None, None) if no valid cached file exists yet.
    Checks WebP first, then JPEG, then PNG.
    """
    for path, mime in (
        (_img_cached_path(cache_key), "image/webp"),
        (_img_cached_path_jpg(cache_key), "image/jpeg"),
        (_img_cached_path_png(cache_key), "image/png"),
    ):
        if os.path.exists(path):
            return path, mime
    return None, None


def _img_meta_path(cache_key: str) -> str:
    return os.path.join(_img_cache_root(), f"{cache_key}.meta.json")


def _img_write_meta(cache_key: str, data: dict) -> None:
    path = _img_meta_path(cache_key)
    with _img_status_lock:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)


def _img_read_meta(cache_key: str) -> dict:
    path = _img_meta_path(cache_key)
    if not os.path.exists(path):
        return {}
    try:
        with _img_status_lock:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        return {}


# ── pyvips availability ───────────────────────────────────────────────────────


def _pyvips_available() -> bool:
    """Return True if pyvips is both enabled in config AND importable.

    ENABLE_LIBVIPS=True  + installed   → True  (full WebP conversion)
    ENABLE_LIBVIPS=True  + not found   → False (graceful raw fallback, same as before)
    ENABLE_LIBVIPS=False               → False (intentionally disabled, raw fallback)
    """
    if not ENABLE_LIBVIPS:
        return False
    try:
        import pyvips  # noqa: F401

        return True
    except (ImportError, OSError):
        return False


# ── Conversion worker ─────────────────────────────────────────────────────────


def _convert_to_webp(full_path: str, cache_key: str, lossy: bool) -> bool:
    """
    Convert *full_path* to the best format based on image dimensions.

    Tier 1 — WebP  (dimensions ≤ 16383 px):
      lossy=True  → lossy WebP Q=IMG_WEBP_QUALITY  (file > threshold)
      lossy=False → lossless WebP                  (non-native format, ≤ threshold)

    Tier 2 — JPEG Q=85  (dimensions 16384–65535 px, exceeds WebP limit)

    Tier 3 — PNG lossless  (dimensions > 65535 px, exceeds JPEG limit)

    pyvips passes all EXIF/XMP/IPTC metadata (DPI, GPS, colour profile)
    through automatically when strip=False.

    Returns True on success, False on any error.
    """
    _WEBP_MAX_DIM = 16383  # WebP hard pixel limit per dimension
    _JPEG_MAX_DIM = 65535  # JPEG hard pixel limit per dimension

    try:
        import pyvips
    except (ImportError, OSError):
        print("⚠️  pyvips not installed — cannot convert image")
        _img_write_meta(
            cache_key,
            {
                "status": "error",
                "message": "pyvips not installed. Run: pkg install libvips && pip install pyvips[binary]",
            },
        )
        return False

    try:
        # access="sequential" streams the file page-by-page — much lower RAM
        # usage for giant TIFFs or RAW files.
        img = pyvips.Image.new_from_file(full_path, access="sequential")

        exceeds_webp = img.width > _WEBP_MAX_DIM or img.height > _WEBP_MAX_DIM
        exceeds_jpeg = img.width > _JPEG_MAX_DIM or img.height > _JPEG_MAX_DIM
        size_in = os.path.getsize(full_path)

        if exceeds_jpeg:
            # ── Tier 3: PNG — only format with no dimension ceiling ────────
            out_path = _img_cached_path_png(cache_key)
            tmp_path = out_path + ".tmp"
            img.pngsave(tmp_path, compression=6, strip=False)
            os.replace(tmp_path, out_path)
            out_fmt = "png"
            mode_str = f"PNG lossless (oversized {img.width}×{img.height} > {_JPEG_MAX_DIM}px JPEG limit)"

        elif exceeds_webp:
            # ── Tier 2: JPEG — dimensions exceed WebP limit but within JPEG ─
            out_path = _img_cached_path_jpg(cache_key)
            tmp_path = out_path + ".tmp"
            img.jpegsave(tmp_path, Q=85, strip=False, optimize_coding=True)
            os.replace(tmp_path, out_path)
            out_fmt = "jpeg"
            mode_str = f"JPEG Q=85 (oversized {img.width}×{img.height} > {_WEBP_MAX_DIM}px WebP limit)"

        else:
            # ── Tier 1: WebP — primary format ─────────────────────────────
            # strip=False   → keep all metadata (EXIF DPI, GPS, colour profile)
            # effort=6      → reasonable encode speed vs. file-size tradeoff
            out_path = _img_cached_path(cache_key)
            tmp_path = out_path + ".tmp"
            if lossy:
                img.webpsave(
                    tmp_path, Q=IMG_WEBP_QUALITY, lossless=False, strip=False, effort=6
                )
            else:
                img.webpsave(tmp_path, lossless=True, strip=False, effort=6)
            os.replace(tmp_path, out_path)
            out_fmt = "webp"
            mode_str = f"lossy WebP Q={IMG_WEBP_QUALITY}" if lossy else "lossless WebP"

        size_out = os.path.getsize(out_path)
        ratio = round(size_out / size_in * 100, 1) if size_in else 0

        print(
            f"🖼️  Image cached [{mode_str}]: {os.path.basename(full_path)} "
            f"{size_in / 1048576:.1f} MB → {size_out / 1048576:.1f} MB ({ratio}%)",
            flush=True,
        )

        _img_write_meta(
            cache_key,
            {
                "status": "ready",
                "out_fmt": out_fmt,
                "lossy": lossy and not exceeds_jpeg,
                "oversized": exceeds_webp,
                "original_size": size_in,
                "cached_size": size_out,
                "created_at": time.time(),
            },
        )
        return True

    except Exception as exc:
        print(
            f"❌ Image conversion error ({os.path.basename(full_path)}): {exc}",
            flush=True,
        )
        _img_write_meta(
            cache_key,
            {
                "status": "error",
                "message": str(exc),
            },
        )
        # Remove any partial output files
        for p in (
            _img_cached_path(cache_key) + ".tmp",
            _img_cached_path_jpg(cache_key) + ".tmp",
            _img_cached_path_png(cache_key) + ".tmp",
            _img_cached_path(cache_key),
            _img_cached_path_jpg(cache_key),
            _img_cached_path_png(cache_key),
        ):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        return False


def _run_img_conversion(full_path: str, cache_key: str, lossy: bool) -> None:
    """Threadable wrapper: convert then signal all waiters on this cache_key."""
    _convert_to_webp(full_path, cache_key, lossy)
    with _img_events_mutex:
        event = _img_conv_events.pop(cache_key, None)
    if event:
        event.set()


# ── Flask routes ──────────────────────────────────────────────────────────────


@app.route("/image_preview/<path:path>")
@login_required
async def image_preview(path):
    """
    Serve any image for in-browser preview, converting/compressing as needed.

    Clients (JS) should call this endpoint for ALL image file types.  It is
    transparent: it always returns an image/* response the browser can render.

    Conversion rules (evaluated in order):
      1. File > 15 MB (any format)  → WebP Q=50, cached
      2. Non-native format          → lossless WebP, cached
      3. Small native format        → served directly, no conversion

    Cache: cache/img/<cache_key>.webp
    Stale detection: cache_key = md5(file_size:mtime), so a changed file
    automatically gets a fresh key and is re-converted on next request.

    Termux dependencies:
      pkg install libvips
      pip install pyvips
    """
    if not storage.is_safe_path(path):
        return "Invalid path", 400

    full_path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return "File not found", 404

    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    if ext not in _ALL_IMG_EXTS:
        return jsonify({"error": "Not a recognised image format"}), 415

    try:
        file_size = os.path.getsize(full_path)
    except OSError:
        return "Cannot read file", 500

    is_non_native = ext in _IMG_NON_NATIVE
    needs_compress = file_size > _IMG_CACHE_THRESHOLD  # configurable, default 3 MB
    needs_processing = is_non_native or needs_compress

    # ── Fast path: small native image → serve as-is ───────────────────────
    if not needs_processing:
        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)
        return await send_from_directory(directory, filename, as_attachment=False)

    # ── pyvips not available → graceful raw fallback ──────────────────────
    if not _pyvips_available():
        reason = "libvips_disabled" if not ENABLE_LIBVIPS else "libvips_not_installed"
        print(
            f"⚠️  pyvips {'disabled' if not ENABLE_LIBVIPS else 'unavailable'} — serving {ext.upper()} raw "
            f"(may not render in browser). "
            f"{'Enable libvips in server settings' if not ENABLE_LIBVIPS else 'Install: pkg install libvips && pip install pyvips'}",
            flush=True,
        )
        # For non-native formats when libvips is explicitly disabled, signal the
        # frontend so it can show the same "requires processing" placeholder as
        # the HLS flow does for non-native video with ffmpeg disabled.
        if is_non_native and not ENABLE_LIBVIPS:
            return (
                jsonify(
                    {
                        "error": "libvips_disabled",
                        "reason": reason,
                        "ext": ext,
                    }
                ),
                503,
            )
        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)
        return await send_from_directory(directory, filename, as_attachment=False)

    # ── Cache hit check ───────────────────────────────────────────────────
    cache_key = _img_cache_key(full_path)
    cached_path, cached_mime = _img_find_cached(cache_key)

    if cached_path:
        meta = _img_read_meta(cache_key)
        if meta.get("status") != "error":
            return await send_file(
                cached_path,
                mimetype=cached_mime,
                as_attachment=False,
                cache_timeout=3600,
            )
        # Previous conversion failed; fall through to retry

    # ── Deduplicate concurrent conversions ────────────────────────────────
    # If two requests arrive for the same file simultaneously, only the first
    # starts a conversion thread; the second waits on the shared Event and
    # then reads from cache once the first finishes.
    with _img_events_mutex:
        existing_event = _img_conv_events.get(cache_key)
        if existing_event is None:
            new_event = threading.Event()
            _img_conv_events[cache_key] = new_event
            should_convert = True
        else:
            should_convert = False

    # lossy=True for >15 MB (any format), lossless for non-native under 15 MB
    lossy = needs_compress

    if should_convert:
        # Spawn daemon thread so it survives a client disconnect, then join
        # for up to 60 s.  Inline join keeps this request from returning a
        # partial/missing image while the first bytes are still being written.
        # The JOIN ITSELF must run off the event loop — Thread.join() is a
        # blocking call, and calling it directly here would freeze Hypercorn's
        # whole single event loop for up to 60s per conversion, stalling
        # every other concurrent request (login, other page loads, video
        # preview, everything) for that entire window.
        t = threading.Thread(
            target=_run_img_conversion,
            args=(full_path, cache_key, lossy),
            daemon=True,
        )
        t.start()
        await asyncio.to_thread(t.join, 60)
    else:
        # Another thread is handling this conversion; wait up to 60 s for it.
        # Same reasoning as above — Event.wait() blocks, must run off-loop.
        await asyncio.to_thread(existing_event.wait, 60)

    # ── Serve from cache (or fall back to raw if conversion timed out) ────
    cached_path, cached_mime = _img_find_cached(cache_key)
    if cached_path:
        meta = _img_read_meta(cache_key)
        if meta.get("status") != "error":
            return await send_file(
                cached_path,
                mimetype=cached_mime,
                as_attachment=False,
                cache_timeout=3600,
            )

    # Conversion timed out or permanently failed → serve raw as fallback
    # (non-native images will show an error in the browser, but that is
    #  preferable to a 500 Internal Server Error for the user)
    print(
        f"⚠️  Image conversion incomplete/failed for '{path}' — serving raw fallback",
        flush=True,
    )
    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)
    return await send_from_directory(directory, filename, as_attachment=False)


@app.route("/image_preview_status/<cache_key>")
@login_required
async def image_preview_status(cache_key):
    """
    Poll conversion status for a specific cache key.

    Response JSON shape:
      { status: 'not_started' | 'processing' | 'ready' | 'error',
        lossy?: bool, original_size?: int, cached_size?: int,
        created_at?: float, message?: str, cache_key: str }

    The frontend can use this to display a spinner while a large image is
    being converted on first request, then swap to the cached WebP once ready.
    """
    if not re.fullmatch(r"[a-f0-9]{32}", cache_key):
        return jsonify({"error": "Invalid cache key"}), 400

    cached_path, _ = _img_find_cached(cache_key)
    meta = _img_read_meta(cache_key)

    # No meta and no file → conversion never started (or cache was cleared)
    if not meta and not cached_path:
        return jsonify({"status": "not_started", "cache_key": cache_key})

    # Cached file present and not an error → ready
    if cached_path and meta.get("status") != "error":
        return jsonify({**meta, "status": "ready", "cache_key": cache_key})

    # Meta says error → pass it through
    if meta.get("status") == "error":
        return jsonify({**meta, "cache_key": cache_key})

    # Meta exists but file not yet present → still processing
    return jsonify({"status": "processing", "cache_key": cache_key})


@app.route("/image_info/<path:path>")
@login_required
async def image_info(path):
    """
    Return metadata about an image file so the frontend can decide whether to
    use /image_preview/<path> or /view/<path>.

    Response JSON:
      { ext, file_size, is_non_native, needs_compress, needs_processing,
        cache_key?, cached?, pyvips_available }
    """
    if not storage.is_safe_path(path):
        return jsonify({"error": "Invalid path"}), 400

    full_path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return jsonify({"error": "File not found"}), 404

    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    try:
        file_size = os.path.getsize(full_path)
    except OSError:
        file_size = 0

    is_non_native = ext in _IMG_NON_NATIVE
    needs_compress = file_size > _IMG_CACHE_THRESHOLD
    needs_processing = is_non_native or needs_compress

    info: dict = {
        "ext": ext,
        "file_size": file_size,
        "is_non_native": is_non_native,
        "needs_compress": needs_compress,
        "needs_processing": needs_processing,
        "pyvips_available": _pyvips_available(),
        "libvips_enabled": ENABLE_LIBVIPS,
    }

    if needs_processing:
        cache_key = _img_cache_key(full_path)
        found_path, found_mime = _img_find_cached(cache_key)
        meta = _img_read_meta(cache_key)
        info["cache_key"] = cache_key
        info["cached"] = found_path is not None and meta.get("status") != "error"
        if info["cached"]:
            info["cached_size"] = meta.get("cached_size")
            info["out_fmt"] = meta.get("out_fmt")  # "webp" or "jpeg"
            info["lossy"] = meta.get("lossy")
            info["oversized"] = meta.get("oversized", False)

    return jsonify(info)


# ─────────────────────────────────────────────────────────────────────────────
# End Image Preview & WebP Conversion
# ─────────────────────────────────────────────────────────────────────────────
