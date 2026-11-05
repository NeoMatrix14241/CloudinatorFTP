"""
Tests of helpers/file_body.py (5.42): the app's file responses read big pieces instead of Quart's
8 KiB, and nothing else about a download changes.

Real Quart objects and real files; no server is started. Needs Quart (installed with
requirements.txt); the tests skip without it.
"""

import asyncio
import hashlib
import importlib.util
import math
from pathlib import Path

import pytest

HELPER_PATH = Path(__file__).resolve().parent.parent.parent / "helpers" / "file_body.py"
SIZE = 3 * 1024 * 1024 + 12345  # not a multiple of any buffer size used below


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location("file_body_under_test", HELPER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def quart():
    return pytest.importorskip("quart")


@pytest.fixture
def blob(tmp_path):
    data = bytes(range(256)) * (SIZE // 256 + 1)
    data = data[:SIZE]
    (tmp_path / "blob.bin").write_bytes(data)
    return tmp_path, data


def _chunks_of(app, directory):
    """The pieces FileBody yields for blob.bin, read inside a real request context."""
    from quart import send_from_directory

    async def run():
        async with app.test_request_context("/d"):
            response = await send_from_directory(str(directory), "blob.bin")
            body = response.response
            async with body:
                return [piece async for piece in body]

    return asyncio.run(run())


# ---------------------------------------------------------------------------- the piece size
@pytest.mark.parametrize("size", [64 * 1024, 256 * 1024, 1024 * 1024])
def test_a_file_is_read_in_pieces_of_the_configured_size(helper, quart, blob, size):
    directory, data = blob
    app = quart.Quart("sized")
    assert helper.use_file_buffer(app, size) is not None
    pieces = _chunks_of(app, directory)
    assert len(pieces) == math.ceil(SIZE / size)
    assert all(len(p) == size for p in pieces[:-1])
    assert b"".join(pieces) == data


def test_the_default_of_quart_is_what_the_helper_replaces(helper, quart, blob):
    """Documents the cost: Quart's own read size is small, so a big file is thousands of pieces."""
    directory, _ = blob
    pieces = _chunks_of(quart.Quart("plain"), directory)
    assert len(pieces) >= 100  # 3 MiB in 8 KiB pieces is 385


# ---------------------------------------------------------------------------- nothing else changes
def _serve(app, directory, headers=None, **kwargs):
    """(status, headers, body) of send_from_directory inside a request context built from
    `headers`. No route is registered: tests/smoke.py scans the tests and reports a route in a
    test as a new route of the application (checks 3 and 11b)."""
    from quart import send_from_directory

    async def run():
        async with app.test_request_context("/d", headers=headers or {}):
            response = await send_from_directory(str(directory), "blob.bin", **kwargs)
            return response.status_code, response.headers, await response.get_data()

    return asyncio.run(run())


def test_a_download_is_byte_identical(helper, quart, blob):
    directory, data = blob
    app = quart.Quart("sized")
    helper.use_file_buffer(app, 1024 * 1024)
    status, headers, body = _serve(app, directory, as_attachment=True)
    assert status == 200
    assert hashlib.sha256(body).hexdigest() == hashlib.sha256(data).hexdigest()
    assert int(headers["Content-Length"]) == SIZE
    assert "attachment" in headers["Content-Disposition"]


@pytest.mark.parametrize(
    "spec, begin, end",
    [
        ("bytes=1000-5000", 1000, 5000),
        ("bytes=0-0", 0, 0),
        (f"bytes={SIZE - 10}-", SIZE - 10, SIZE - 1),
        ("bytes=1048570-1048590", 1048570, 1048590),  # across a 1 MiB piece boundary
    ],
)
def test_a_range_request_still_returns_exactly_the_requested_bytes(
    helper, quart, blob, spec, begin, end
):
    directory, data = blob
    app = quart.Quart("sized")
    helper.use_file_buffer(app, 1024 * 1024)
    status, headers, body = _serve(app, directory, headers={"Range": spec})
    assert status == 206, status
    assert body == data[begin : end + 1]
    assert headers["Content-Range"] == f"bytes {begin}-{end}/{SIZE}"


def test_quarts_own_classes_are_left_alone(helper, quart):
    from quart.wrappers.response import FileBody, Response

    before = (FileBody.buffer_size, Response.file_body_class)
    first, second = quart.Quart("one"), quart.Quart("two")
    helper.use_file_buffer(first, 512 * 1024)
    assert (FileBody.buffer_size, Response.file_body_class) == before
    assert (
        second.response_class.file_body_class is FileBody
    )  # another app is unaffected
    assert first.response_class.file_body_class.buffer_size == 512 * 1024
    assert issubclass(first.response_class, Response)


def test_an_existing_file_body_customisation_is_extended_not_replaced(helper, quart):
    from quart.wrappers.response import FileBody

    class Mine(FileBody):
        marker = "kept"

    app = quart.Quart("custom")
    app.response_class = type("R", (app.response_class,), {"file_body_class": Mine})
    sized = helper.use_file_buffer(app, 256 * 1024)
    assert issubclass(sized, Mine) and sized.marker == "kept"


# ---------------------------------------------------------------------------- never breaks the app
@pytest.mark.parametrize("bad", [0, 100, 8191, 16 * 1024 * 1024 + 1, "big", None, -5])
def test_an_unusable_size_is_logged_and_changes_nothing(helper, quart, bad):
    app, lines = quart.Quart("bad"), []
    before = app.response_class
    assert helper.use_file_buffer(app, bad, log=lines.append) is None
    assert app.response_class is before
    assert len(lines) == 1 and "default read size" in lines[0]


def test_an_app_without_the_quart_hook_is_tolerated(helper):
    class Odd:
        class response_class:  # no file_body_class: another Quart version
            pass

    lines = []
    assert helper.use_file_buffer(Odd(), 1024 * 1024, log=lines.append) is None
    assert any("file_body_class" in line for line in lines)


def test_the_bounds_are_the_documented_ones(helper):
    assert helper.MIN_BUFFER_SIZE == 8192
    assert helper.MAX_BUFFER_SIZE == 16 * 1024 * 1024
    app_like = type("A", (), {})

    # exactly on the bounds is allowed (a stub response class with the hook)
    class Resp:
        file_body_class = type("F", (), {})

    for size in (helper.MIN_BUFFER_SIZE, helper.MAX_BUFFER_SIZE):
        app = app_like()
        app.response_class = Resp
        assert helper.use_file_buffer(app, size) is not None


def test_the_helper_registers_no_lifecycle_hook():
    """tests/smoke.py check 5: hooks belong in middleware.py, never in a helper."""
    source = HELPER_PATH.read_text(encoding="utf-8")
    for hook in ("before_serving", "after_serving", "before_request", "after_request"):
        assert f"@app.{hook}" not in source and f".{hook}(" not in source, hook
