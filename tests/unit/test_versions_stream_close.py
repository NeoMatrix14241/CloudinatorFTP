"""
5.44 (ASYNC_BLOCKING_REFACTOR_PLAN, R8): `routes/versions._stream_version_blocks` must not close
its sync generator on the event-loop thread while a worker is still inside it.

Before 5.44 a client that left during a block read made `finally: chunks.close()` raise
"ValueError: generator already executing" on the loop, replacing the cancellation (logged as an
ASGI error). The REAL helper is cut out of `routes/versions.py` with `ast` (the module cannot be
imported: it starts the whole application) and run on a plain asyncio loop.
"""

import ast
import asyncio
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
VERSIONS_PATH = ROOT / "routes" / "versions.py"
CLOSE_THREAD = "versions-download-close"


def _load():
    tree = ast.parse(VERSIONS_PATH.read_text(encoding="utf-8"))
    nodes = [
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_stream_version_blocks"
    ]
    assert len(nodes) == 1, "routes/versions._stream_version_blocks is gone"
    namespace = {"asyncio": asyncio, "threading": threading}
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(VERSIONS_PATH), "exec"),
        namespace,
    )  # noqa: S102
    return namespace["_stream_version_blocks"]


stream = _load()


def _close_threads():
    return [t for t in threading.enumerate() if t.name == CLOSE_THREAD and t.is_alive()]


def _wait_until(predicate, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class Source:
    """A sync generator that can be held inside next() and records that it was closed."""

    def __init__(self, blocks=3, hold_at=None, fail_at=None):
        self.blocks, self.hold_at, self.fail_at = blocks, hold_at, fail_at
        self.inside = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()
        self.generator = self._run()

    def _run(self):
        try:
            for i in range(self.blocks):
                if i == self.hold_at:
                    self.inside.set()
                    assert self.release.wait(10), "the test never released the read"
                if i == self.fail_at:
                    raise ValueError("object failed its hash check")
                yield bytes([i])
        finally:
            self.closed.set()


def test_a_whole_download_arrives_and_needs_no_close_thread():
    source = Source(blocks=4)

    async def go():
        return [b async for b in stream(source.generator)]

    assert asyncio.run(go()) == [b"\x00", b"\x01", b"\x02", b"\x03"]
    assert not _close_threads()


def test_an_integrity_error_aborts_the_response_and_is_raised():
    source = Source(blocks=4, fail_at=2)

    async def go():
        got = []
        try:
            async for block in stream(source.generator):
                got.append(block)
        except ValueError as error:
            return got, str(error)
        return got, None

    assert asyncio.run(go()) == ([b"\x00", b"\x01"], "object failed its hash check")


def test_a_client_that_leaves_during_a_block_read_does_not_raise_on_the_loop():
    source = Source(blocks=3, hold_at=1)

    async def go():
        async def consume():
            async for _block in stream(source.generator):
                pass

        task = asyncio.ensure_future(consume())
        for _ in range(200):  # wait until the worker is inside next()
            if source.inside.is_set():
                break
            await asyncio.sleep(0.01)
        assert source.inside.is_set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            outcome = (
                "cancelled"  # the cancellation must survive: no ValueError replaces it
            )
        else:
            outcome = "finished"
        # the generator is still running in its worker: it must NOT be closed yet ...
        still_open = not source.closed.is_set()
        # ... and is closed by the release thread as soon as that read returns. (The read is
        # released inside the loop: asyncio.run() waits for the pool thread that is held in it.)
        source.release.set()
        return outcome, still_open

    assert asyncio.run(go()) == ("cancelled", True)
    assert source.closed.wait(3), "the generator was never released"
    assert _wait_until(lambda: not _close_threads())


def test_a_client_that_leaves_between_blocks_releases_the_generator():
    source = Source(blocks=5)

    async def go():
        agen = stream(source.generator)
        first = await agen.__anext__()
        await agen.aclose()
        return first

    assert asyncio.run(go()) == b"\x00"
    assert source.closed.wait(3)
    assert _wait_until(lambda: not _close_threads())
