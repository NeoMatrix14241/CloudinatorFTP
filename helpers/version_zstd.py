"""
helpers/version_zstd.py - zstd codec for Version Engine objects (leaf helper, 5.46 / 5.47).

Compression is a STORAGE ENCODING of an object, never its identity: the object's name stays the
SHA-256 of the RAW bytes (VERSION_COMPRESSION_PLAN.md D1). This module is only the codec:

  * `compress()` / `decode_bounded()`   one standard zstd frame per object, no dictionary by
                                          default, a frame checksum on top of the SHA-256;
  * `iter_decode()`                     the same decoding as a generator over an open file, one
                                          bounded block at a time (the read path of the engine:
                                          a restore or a download never holds a whole object);
  * `compress_verified()`               compress, decode it back, compare size and SHA-256
                                          BEFORE the frame is returned (a frame that was never
                                          verified is never published);
  * `raw_dictionary()` / `train_dictionary()`   used by the read-only probe (Phase 0) to measure
                                          the previous-version delta and a trained dictionary.
                                          The engine's Phase 1 / 2 objects never use them.

Rules of this file (smoke rule 7b, CODING_GUIDELINES "Background work inside the Version Engine"):
standard library only (the optional `backports.zstd` import sits inside a try), no import of
config / version_engine / app / routes / tools, NO asyncio, no thread, no pool. The caller
passes level and sizes in. Every function is synchronous and blocking by design; it runs in the
Version Engine worker's own plain thread (`ve-compress`) or in a CLI tool, never in the web
process' event loop.

Python 3.14 ships `compression.zstd`; older Pythons can `pip install backports.zstd` (same API).
When neither exists `available()` is False and every codec function raises CodecError.
"""

import hashlib

try:  # Python 3.14+
    from compression import zstd as _z
except ImportError:  # optional backport: pip install backports.zstd
    try:
        from backports import zstd as _z
    except ImportError:
        _z = None

SUFFIX = ".zst"
BLOCK = 1024 * 1024
MIN_LEVEL = 1
MAX_LEVEL = 22
# The owner's decision (2026-11-16): the maximum level, even when it gains nothing over 19.
DEFAULT_LEVEL = 22
# Shared by the engine's compressor thread and the read-only probe, so the probe's estimate
# models exactly what the engine does (VERSION_COMPRESSION_PLAN.md 6.5):
MIN_OBJECT_SIZE = 4096  # an object below this stays raw (compress_state 'skip')
PROBE_LEVEL = 3  # the fast "is this worth compressing at all" attempt
# An object that does not even shrink by this much at the probe level is data that is already
# compressed (jpg, zip, ...): it stays raw. Deliberately far below MIN_SAVING_PERCENT: the
# probe only avoids the slow level for hopeless data, the owner's setting decides the rest.
PROBE_MIN_SAVING_PERCENT = 1.0
# zstd's default decoder limit is a 2**27 window; stay inside it so any stock `zstd -d` works.
MAX_WINDOW_LOG = 27
MIN_WINDOW_LOG = 10


class CodecError(Exception):
    """A frame is corrupt, truncated, too big, does not match its object, or zstd is missing."""


def available() -> bool:
    return _z is not None


def version() -> str:
    """The zstd library version text (for example '1.5.7'), or '' without zstd."""
    return str(getattr(_z, "zstd_version", "")) if _z is not None else ""


def self_test() -> bool:
    """One tiny round trip. False means: treat compression as off (the engine keeps storing raw)."""
    if _z is None:
        return False
    try:
        data = b"cloudinator" * 1000
        return _z.decompress(_z.compress(data)) == data
    except Exception:
        return False


def clamp_level(level) -> int:
    """A level as an int inside 1..22. Garbage gives DEFAULT_LEVEL (22)."""
    try:
        value = int(level)
    except (TypeError, ValueError):
        return DEFAULT_LEVEL
    return max(MIN_LEVEL, min(MAX_LEVEL, value))


def _require() -> None:
    if _z is None:
        raise CodecError("zstd is not available in this Python")


def _opts(level, window_log=None) -> dict:
    # `level=` and `options=` cannot be combined (TypeError), so the level goes in options.
    # nb_workers stays 0 (its default): zstd must not start native worker threads of its own.
    opts = {
        _z.CompressionParameter.compression_level: clamp_level(level),
        _z.CompressionParameter.checksum_flag: 1,  # zstd's own check, on top of SHA-256
    }
    if window_log is not None:
        opts[_z.CompressionParameter.window_log] = max(
            MIN_WINDOW_LOG, min(MAX_WINDOW_LOG, int(window_log))
        )
    return opts


def compress(raw, level, zstd_dict=None, window_log=None) -> bytes:
    """ONE zstd frame of `raw` (one-shot, so the frame header carries the content size)."""
    _require()
    try:
        return _z.compress(raw, options=_opts(level, window_log), zstd_dict=zstd_dict)
    except _z.ZstdError as exc:
        raise CodecError(f"zstd could not compress: {exc}") from exc


def decode_bounded(frame, max_size: int, zstd_dict=None) -> bytes:
    """Decode exactly ONE frame and never produce more than `max_size` bytes (bomb guard).

    Raises CodecError for a truncated frame, a corrupt frame (bad checksum or data), output
    beyond `max_size`, or bytes after the frame."""
    _require()
    dec = _z.ZstdDecompressor(zstd_dict=zstd_dict)
    out, view, pos, total = [], memoryview(frame), 0, 0
    try:
        while not dec.eof:
            if dec.needs_input:  # feed input only when asked; otherwise drain with b""
                if pos >= len(view):
                    raise CodecError("compressed object is truncated")
                data = view[pos : pos + BLOCK]
                pos += BLOCK
            else:
                data = b""
            piece = dec.decompress(data, BLOCK)
            total += len(piece)
            if total > max_size:
                raise CodecError("object expands beyond its recorded size")
            out.append(piece)
    except _z.ZstdError as exc:
        raise CodecError(f"corrupt compressed object: {exc}") from exc
    if dec.unused_data or pos < len(view):
        raise CodecError("unexpected bytes after the compressed frame")
    return b"".join(out)


def iter_decode(fileobj, max_size: int, block: int = BLOCK):
    """Decode ONE frame read from the open binary file `fileobj`, yielding the raw bytes in
    pieces of at most `block` bytes (never an empty piece). Memory stays at about one block
    of input plus one of output, whatever the object's size.

    Raises CodecError for a truncated frame, a corrupt frame (bad checksum or data), output
    beyond `max_size` (a decompression bomb) or bytes after the frame. The caller still owns
    the SHA-256 comparison: this only guarantees that the frame itself was sound."""
    _require()
    dec = _z.ZstdDecompressor()
    total = 0
    try:
        while not dec.eof:
            if dec.needs_input:  # feed input only when asked; otherwise drain with b""
                data = fileobj.read(block)
                if not data:
                    raise CodecError("compressed object is truncated")
            else:
                data = b""
            piece = dec.decompress(data, block)
            if piece:
                total += len(piece)
                if total > max_size:
                    raise CodecError("object expands beyond its recorded size")
                yield piece
    except _z.ZstdError as exc:
        raise CodecError(f"corrupt compressed object: {exc}") from exc
    if dec.unused_data or fileobj.read(1):
        raise CodecError("unexpected bytes after the compressed frame")


def compress_verified(raw, sha256_hex: str, level) -> bytes:
    """Compress, decode the frame back and compare size and SHA-256 BEFORE returning it.
    Raises CodecError when anything differs."""
    frame = compress(raw, level)
    back = decode_bounded(frame, len(raw))
    if len(back) != len(raw) or hashlib.sha256(back).hexdigest() != sha256_hex:
        raise CodecError("round-trip verification failed")
    return frame


def raw_dictionary(content):
    """A dictionary made of raw bytes (for example the previous version's chunk). Probe only."""
    _require()
    return _z.ZstdDict(bytes(content), is_raw=True)


def train_dictionary(samples, dict_size: int):
    """A trained dictionary of about `dict_size` bytes from `samples`. Probe only."""
    _require()
    try:
        return _z.train_dict(list(samples), int(dict_size))
    except _z.ZstdError as exc:
        raise CodecError(f"dictionary training failed: {exc}") from exc
