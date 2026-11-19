"""
Unit tests for helpers/version_zstd.py (5.46: the zstd codec of the Version Engine objects).

Nothing here starts a server or imports the application. The helper is a leaf (standard library
plus the zstd module); these tests feed it good and bad frames. The hard rules of this feature
are checked with `ast`: NO asyncio, no thread, no thread pool, a leaf in the sense of smoke
rule 7b, and the codec never mixes `level=` with `options=` (that is a TypeError in
compression.zstd).

The codec tests need Python 3.14 (`compression.zstd`) or `pip install backports.zstd`; without
either they are skipped, the structure tests below always run.
"""

import ast
import hashlib
import io
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from helpers import version_zstd as vz  # noqa: E402

needs_zstd = pytest.mark.skipif(not vz.available(), reason="no zstd in this Python")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _sample(n=300_000):
    """Compressible but not trivial."""
    rng = __import__("random").Random(7)
    return rng.randbytes(5000) + (b"row%05d|" % 42) * (n // 8)


# -- round trips -------------------------------------------------------------------------


@needs_zstd
@pytest.mark.parametrize("level", [1, 3, 19, 22])
def test_round_trip_at_every_kind_of_level(level):
    raw = _sample()
    frame = vz.compress(raw, level)
    assert len(frame) < len(raw)
    assert vz.decode_bounded(frame, len(raw)) == raw


@needs_zstd
@pytest.mark.parametrize("raw", [b"", b"x", b"\x00" * 10, os.urandom(70_000)])
def test_empty_tiny_and_incompressible_objects_round_trip(raw):
    assert vz.decode_bounded(vz.compress(raw, 19), len(raw)) == raw


@needs_zstd
def test_an_object_over_several_blocks_round_trips():
    raw = os.urandom(3 * vz.BLOCK + 17)
    assert vz.decode_bounded(vz.compress(raw, 1), len(raw)) == raw


@needs_zstd
def test_the_frame_is_a_standard_frame_with_content_size_and_checksum():
    """`zstd -d < file.zst | sha256sum` must work by hand (disaster recovery, plan 6.1)."""
    zstd = vz._z  # the helper's own module: compression.zstd, or the backport on < 3.14

    raw = _sample()
    frame = vz.compress(raw, 19)
    assert zstd.get_frame_info(frame).decompressed_size == len(raw)
    assert zstd.decompress(frame) == raw  # the one-shot stock call reads it too
    flipped = bytearray(frame)
    flipped[len(flipped) // 2] ^= 1
    with pytest.raises(zstd.ZstdError):
        zstd.decompress(
            bytes(flipped)
        )  # a checksum is in the frame: stock tools catch it


@needs_zstd
def test_a_window_log_is_clamped_into_the_range_a_stock_decoder_accepts():
    raw = _sample(60_000)
    for wl in (1, 99):
        assert vz.decode_bounded(vz.compress(raw, 3, window_log=wl), len(raw)) == raw


@needs_zstd
@pytest.mark.parametrize(
    "given, expected", [(0, 1), (-5, 1), (99, 22), ("19", 19), (None, 22), ("x", 22)]
)
def test_clamp_level(given, expected):
    assert vz.clamp_level(given) == expected


# -- bad frames all raise CodecError -----------------------------------------------------


@needs_zstd
def test_a_flipped_byte_is_detected():
    raw = _sample()
    frame = bytearray(vz.compress(raw, 19))
    frame[len(frame) // 2] ^= 0x01
    with pytest.raises(vz.CodecError, match="corrupt"):
        vz.decode_bounded(bytes(frame), len(raw))


@needs_zstd
def test_a_truncated_frame_is_detected():
    raw = _sample()
    frame = vz.compress(raw, 19)
    for cut in (1, 5, len(frame) // 2):
        with pytest.raises(vz.CodecError):
            vz.decode_bounded(frame[:-cut], len(raw))


@needs_zstd
def test_bytes_after_the_frame_are_detected_inside_and_across_blocks():
    raw = _sample()
    frame = vz.compress(raw, 19)
    with pytest.raises(vz.CodecError, match="unexpected bytes"):
        vz.decode_bounded(frame + b"x", len(raw))
    big = os.urandom(2 * vz.BLOCK)
    big_frame = vz.compress(big, 1)
    with pytest.raises(vz.CodecError, match="unexpected bytes"):
        vz.decode_bounded(big_frame + b"\x00" * (vz.BLOCK + 5), len(big))


@needs_zstd
def test_an_object_that_expands_beyond_its_recorded_size_is_refused():
    """A decompression bomb: 50 MB of zeros in a couple of KB."""
    bomb = vz.compress(b"\x00" * 50_000_000, 19)
    assert len(bomb) < 10_000
    with pytest.raises(vz.CodecError, match="expands beyond"):
        vz.decode_bounded(bomb, 1000)


@needs_zstd
@pytest.mark.parametrize("junk", [b"", b"not a zstd frame" * 10, b"\x28\xb5\x2f\xfd"])
def test_empty_and_garbage_input_raise_codec_error(junk):
    with pytest.raises(vz.CodecError):
        vz.decode_bounded(junk, 100)


# -- the streaming decoder of the read path ----------------------------------------------


@needs_zstd
def test_iter_decode_yields_the_object_in_bounded_non_empty_pieces():
    raw = _sample(3 * vz.BLOCK + 123)
    pieces = list(vz.iter_decode(io.BytesIO(vz.compress(raw, 3)), len(raw)))
    assert b"".join(pieces) == raw
    assert all(0 < len(p) <= vz.BLOCK for p in pieces)
    small = list(vz.iter_decode(io.BytesIO(vz.compress(raw, 3)), len(raw), block=4096))
    assert b"".join(small) == raw and all(0 < len(p) <= 4096 for p in small)


@needs_zstd
@pytest.mark.parametrize("raw", [b"", b"x", os.urandom(50_000)])
def test_iter_decode_handles_empty_tiny_and_incompressible_objects(raw):
    frame = vz.compress(raw, 19)
    assert b"".join(vz.iter_decode(io.BytesIO(frame), len(raw))) == raw


@needs_zstd
def test_iter_decode_never_reads_more_than_one_block_of_input_at_a_time():
    raw = os.urandom(3 * vz.BLOCK)
    sizes = []

    class Spy(io.BytesIO):
        def read(self, n=-1):
            sizes.append(n)
            return super().read(n)

    list(vz.iter_decode(Spy(vz.compress(raw, 1)), len(raw)))
    assert sizes and max(s for s in sizes if s != 1) <= vz.BLOCK


@needs_zstd
@pytest.mark.parametrize(
    "damage", ["flip", "truncate", "trailing", "trailing_far", "junk"]
)
def test_iter_decode_refuses_every_kind_of_damage(damage):
    raw = _sample()
    frame = vz.compress(raw, 19)
    if damage == "flip":
        bad = bytearray(frame)
        bad[len(bad) // 2] ^= 1
        data = bytes(bad)
    elif damage == "truncate":
        data = frame[:-6]
    elif damage == "trailing":
        data = frame + b"x"
    elif damage == "trailing_far":
        data = frame + b"\x00" * (2 * vz.BLOCK)
    else:
        data = b"not zstd at all" * 20
    with pytest.raises(vz.CodecError):
        list(vz.iter_decode(io.BytesIO(data), len(raw)))


@needs_zstd
def test_iter_decode_stops_at_the_recorded_size_before_a_bomb_is_inflated():
    bomb = vz.compress(b"\x00" * 40_000_000, 19)
    produced = 0
    with pytest.raises(vz.CodecError, match="expands beyond"):
        for piece in vz.iter_decode(io.BytesIO(bomb), 1000):
            produced += len(piece)
    assert produced <= 1000


def test_iter_decode_without_zstd_says_so(monkeypatch):
    monkeypatch.setattr(vz, "_z", None)
    with pytest.raises(vz.CodecError, match="not available"):
        list(vz.iter_decode(io.BytesIO(b"x"), 1))


def test_the_shared_constants_are_the_ones_the_plan_and_the_owner_set():
    assert (
        vz.DEFAULT_LEVEL == 22 and vz.MAX_LEVEL == 22
    )  # the owner's decision (2026-11-16)
    assert vz.MIN_OBJECT_SIZE == 4096 and vz.PROBE_LEVEL == 3
    assert (
        0 < vz.PROBE_MIN_SAVING_PERCENT < 5
    )  # far below the default MIN_SAVING_PERCENT


# -- verified compression ----------------------------------------------------------------


@needs_zstd
def test_compress_verified_returns_a_frame_that_decodes_to_the_object():
    raw = _sample()
    frame = vz.compress_verified(raw, _sha(raw), 19)
    assert vz.decode_bounded(frame, len(raw)) == raw


@needs_zstd
def test_compress_verified_refuses_when_the_hash_does_not_match():
    raw = _sample()
    with pytest.raises(vz.CodecError, match="verification failed"):
        vz.compress_verified(raw, _sha(raw + b"!"), 19)


@needs_zstd
def test_compress_verified_refuses_when_the_decode_differs(monkeypatch):
    """A library bug or a RAM fault: whatever comes back is compared, never trusted."""
    raw = _sample()
    monkeypatch.setattr(vz, "decode_bounded", lambda frame, max_size: raw[:-1] + b"?")
    with pytest.raises(vz.CodecError, match="verification failed"):
        vz.compress_verified(raw, _sha(raw), 19)


@needs_zstd
def test_the_level_never_goes_in_next_to_options(monkeypatch):
    """compression.zstd raises TypeError for both `level=` and `options=`: the level goes in
    the options only."""
    seen = {}
    real = vz._z.compress

    def spy(data, *args, **kwargs):
        seen.update(kwargs, args=args)
        return real(data, *args, **kwargs)

    monkeypatch.setattr(vz._z, "compress", spy)
    vz.compress(b"abc" * 1000, 19)
    assert "level" not in seen and "options" in seen and seen["args"] == ()
    cp = vz._z.CompressionParameter
    assert seen["options"][cp.compression_level] == 19
    assert seen["options"][cp.checksum_flag] == 1
    assert cp.nb_workers not in seen["options"]  # no native worker threads


# -- dictionaries (used by the probe only) -----------------------------------------------


@needs_zstd
def test_a_raw_dictionary_makes_a_delta_that_decodes_only_with_that_dictionary():
    base = os.urandom(200_000)
    new = bytearray(base)
    new[1000:1016] = b"X" * 16
    new = bytes(new)
    zdict = vz.raw_dictionary(base)
    frame = vz.compress(new, 19, zstd_dict=zdict, window_log=19)
    assert len(frame) < 2000 < len(vz.compress(new, 19))
    assert vz.decode_bounded(frame, len(new), zstd_dict=zdict) == new
    with pytest.raises(vz.CodecError):
        vz.decode_bounded(frame, len(new))  # without the base it is not decodable


@needs_zstd
def test_training_on_too_little_data_is_a_codec_error_not_a_crash():
    with pytest.raises(vz.CodecError, match="training failed"):
        vz.train_dictionary([b"a" * 10, b"b" * 10], 110 * 1024)


# -- zstd missing ------------------------------------------------------------------------


def test_without_zstd_the_helper_says_so_clearly(monkeypatch):
    monkeypatch.setattr(vz, "_z", None)
    assert vz.available() is False
    assert vz.self_test() is False
    assert vz.version() == ""
    for call in (
        lambda: vz.compress(b"x", 3),
        lambda: vz.decode_bounded(b"x", 1),
        lambda: vz.compress_verified(b"x", _sha(b"x"), 3),
        lambda: vz.raw_dictionary(b"x"),
        lambda: vz.train_dictionary([b"x"], 1000),
    ):
        with pytest.raises(vz.CodecError, match="not available"):
            call()


@needs_zstd
def test_self_test_is_false_when_the_round_trip_breaks(monkeypatch):
    monkeypatch.setattr(vz._z, "decompress", lambda data: b"other")
    assert vz.self_test() is False


@needs_zstd
def test_the_version_text_and_self_test_on_a_working_python():
    assert vz.self_test() is True
    assert vz.version().count(".") >= 1


# -- the hard rules, with ast ------------------------------------------------------------

_FORBIDDEN_MODULES = {"asyncio", "concurrent", "anyio", "trio", "quart", "hypercorn"}
_FORBIDDEN_CALLS = {
    "to_thread",
    "run_in_executor",
    "get_event_loop",
    "get_running_loop",
    "new_event_loop",
    "create_task",
    "ensure_future",
    "run_coroutine_threadsafe",
    "ThreadPoolExecutor",
    "ProcessPoolExecutor",
    "submit",
    "Thread",
    "Timer",
}
_LEAF_FORBIDDEN_ROOTS = {"app", "core", "middleware", "routes", "tools", "tests"}
_ALLOWED_IMPORTS = {
    "version_zstd": {"hashlib", "compression", "backports"},
}


def _tree(name):
    return ast.parse((ROOT / name).read_text(encoding="utf-8"))


def _async_findings(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [
                a.name for a in node.names if a.name.split(".")[0] in _FORBIDDEN_MODULES
            ]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _FORBIDDEN_MODULES:
                found.append(node.module)
        elif isinstance(
            node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)
        ):
            found.append(type(node).__name__)
        elif isinstance(node, ast.Call):
            fn = node.func
            called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if called in _FORBIDDEN_CALLS:
                found.append(called)
    return found


def test_the_codec_uses_no_asyncio_no_thread_and_no_thread_pool():
    assert _async_findings(_tree("helpers/version_zstd.py")) == []


def test_the_codec_is_a_stdlib_only_leaf():
    allowed = _ALLOWED_IMPORTS["version_zstd"]
    for node in ast.walk(_tree("helpers/version_zstd.py")):
        if isinstance(node, ast.Import):
            roots = {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
        else:
            continue
        assert roots <= allowed, roots
        assert not roots & _LEAF_FORBIDDEN_ROOTS


def test_every_text_file_of_the_feature_is_lf():
    for name in (
        "helpers/version_zstd.py",
        "helpers/version_probe.py",
        "tests/unit/test_version_zstd.py",
        "tests/unit/test_version_probe.py",
    ):
        assert b"\r" not in (ROOT / name).read_bytes(), name
