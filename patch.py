"""
patch_index_native_compress.py - one-off patch for static/js/index.js (CLAUDE.md 4.79).

Fix: _imgStartPreview() returned early for every "native" image (jpg/png/...) and loaded the raw
file from /view/, so large photos were never compressed. After the patch, jpg/jpeg/png/webp go
through /image_info first: small ones still load raw, files above IMG_COMPRESS_MIN_SIZE are
served by /image_preview as compressed WebP (spinner + status polling, same as non-native
formats). gif, svg, ico, avif and jfif keep loading raw (compressing them would flatten
animation / vector data).

Usage (project root):   python patch_index_native_compress.py [path/to/index.js]
Then:                   ./manage.sh validate-sri --fix      (index.js changed -> new SRI hash)
The script refuses to touch the file unless the old block matches exactly once.
"""
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "static/js/index.js")
raw = path.read_bytes()
crlf = b"\r\n" in raw
text = raw.decode("utf-8").replace("\r\n", "\n")

OLD = """    // ── Small native image: load directly, no backend processing needed ───
    if (isNative) {
        _setLabel('Loading image…');
        _showImage(viewUrl);
        return;
    }

    // ── Non-native / potentially large: ask backend for info first ────────
    let info;
    try {
        _setLabel('Checking image…');
        const r = await fetch(`/image_info/${encodePathForUrl(itemPath)}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        info = await r.json();
    } catch (e) {
        _showImage(previewUrl);
        return;
    }

    if (!_alive()) return;

    // Already cached or no processing needed → serve immediately
"""

NEW = """    // ── Native formats that must never be re-encoded (animated gif, svg, ico, avif,
    //    jfif): load directly, no backend processing ───────────────────────────────
    const _COMPRESSIBLE_NATIVE = new Set(['jpg', 'jpeg', 'png', 'webp']);
    if (isNative && !_COMPRESSIBLE_NATIVE.has(ext)) {
        _setLabel('Loading image…');
        _showImage(viewUrl);
        return;
    }

    // ── Non-native, or a jpg/png/webp that may be large: ask backend for info first.
    //    Small native files come back needs_processing=false and load raw below; files
    //    above IMG_COMPRESS_MIN_SIZE are compressed to WebP by /image_preview. ───────
    let info;
    try {
        _setLabel(isNative ? 'Loading image…' : 'Checking image…');
        const r = await fetch(`/image_info/${encodePathForUrl(itemPath)}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        info = await r.json();
    } catch (e) {
        _showImage(isNative ? viewUrl : previewUrl);
        return;
    }

    if (!_alive()) return;

    // Small native image: the original is fine, load it directly
    if (isNative && !info.needs_processing) {
        _setLabel('Loading image…');
        _showImage(viewUrl);
        return;
    }

    // Already cached or no processing needed → serve immediately
"""

if NEW in text:
    sys.exit("Already patched, nothing to do.")
n = text.count(OLD)
if n != 1:
    sys.exit(f"ABORT: expected the old block exactly once, found {n}. index.js was not changed.")
text = text.replace(OLD, NEW)
if crlf:
    text = text.replace("\n", "\r\n")
path.write_bytes(text.encode("utf-8"))
print(f"patched {path} ({'CRLF' if crlf else 'LF'}). Now run: ./manage.sh validate-sri --fix")