"""
5.44 (ASYNC_BLOCKING_REFACTOR_PLAN, T5): `core._stream_from_thread` must not leave a thread
behind when the consumer goes away.

The REAL function is cut out of `core.py` with `ast` (core.py cannot be imported: it starts
the whole application) and run on a plain asyncio loop. Before 5.44 a worker blocked on the
full queue (maxsize 8) for ever once nobody read it, holding the files zipstream had open.
"""

import ast
import asyncio
import concurrent.futures
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CORE_PATH = ROOT / "core.py"
THREAD_NAME = "zip-stream"


def _load():
    tree = ast.parse(CORE_PATH.read_text(encoding="utf-8"))
    nodes = [
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_stream_from_thread"
    ]
    assert len(nodes) == 1, "core._stream_from_thread was renamed or removed"
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {
        "asyncio": asyncio,
        "threading": threading,
        "concurrent": concurrent,
        "print": print,
    }
    exec(compile(module, str(CORE_PATH), "exec"), namespace)  # noqa: S102
    return namespace["_stream_from_thread"]


stream_from_thread = _load()


def _zip_stream_threads():
    return [t for t in threading.enumerate() if t.name == THREAD_NAME and t.is_alive()]


def _wait_until(predicate, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class Producer:
    """A sync generator that counts what it produced and records being closed."""

    def __init__(self, count):
        self.count = count
        self.produced = 0
        self.closed = threading.Event()

    def __iter__(self):
        return self._run()

    def _run(self):
        try:
            for i in range(self.count):
                self.produced += 1
                yield i
        finally:
            self.closed.set()


def test_items_arrive_in_order_and_the_thread_ends():
    async def go():
        return [x async for x in stream_from_thread(iter(range(50)))]

    assert asyncio.run(go()) == list(range(50))
    assert _wait_until(lambda: not _zip_stream_threads())


def test_an_error_in_the_generator_is_raised_after_the_items_before_it():
    def boom():
        yield 1
        yield 2
        raise ValueError("disk went away")

    async def go():
        seen = []
        try:
            async for item in stream_from_thread(boom()):
                seen.append(item)
        except ValueError as error:
            return seen, str(error)
        return seen, None

    assert asyncio.run(go()) == ([1, 2], "disk went away")
    assert _wait_until(lambda: not _zip_stream_threads())


def test_a_consumer_that_stops_reading_releases_the_worker_and_the_generator():
    # 1000 items and a queue of 8: the worker is blocked on a full queue when we stop.
    producer = Producer(1000)

    async def go():
        stream = stream_from_thread(iter(producer))
        first = await stream.__anext__()
        await asyncio.sleep(0.2)  # let the worker fill the queue and block
        await stream.aclose()  # what Quart does when the client disconnects
        return first

    started = time.monotonic()
    assert asyncio.run(go()) == 0
    assert _wait_until(lambda: not _zip_stream_threads(), seconds=3.0)
    assert time.monotonic() - started < 3.0
    assert producer.closed.wait(2.0), "the sync generator was never closed"
    assert producer.produced < 1000, "the worker kept producing for nobody"


def test_a_cancelled_request_releases_the_worker_too():
    producer = Producer(1000)

    async def go():
        async def consume():
            async for _item in stream_from_thread(iter(producer)):
                await asyncio.sleep(0.05)  # a slow client

        task = asyncio.ensure_future(consume())
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return "cancelled"
        return "finished"

    assert asyncio.run(go()) == "cancelled"
    assert _wait_until(lambda: not _zip_stream_threads(), seconds=3.0)
    assert producer.closed.wait(2.0)


def test_a_generator_without_close_is_accepted():
    class Plain:
        def __iter__(self):
            return iter([1, 2, 3])

    async def go():
        return [x async for x in stream_from_thread(Plain())]

    assert asyncio.run(go()) == [1, 2, 3]


def test_no_coroutine_is_left_unawaited_when_the_loop_closes_mid_stream():
    # 5.44: the worker used to create a `Queue.put` coroutine per item
    # (run_coroutine_threadsafe); when asyncio.run() ended with one still scheduled the coroutine
    # was never awaited ("RuntimeWarning: coroutine 'Queue.put' was never awaited").
    import gc
    import warnings

    producer = Producer(100000)

    async def go():
        stream = stream_from_thread(iter(producer))
        await stream.__anext__()
        await asyncio.sleep(0.1)  # the worker is busy handing items over
        # leave without closing the stream: the loop is closed with the worker still running

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(go())
        time.sleep(0.8)  # the worker notices the closed loop (it polls every 0.5 s)
        gc.collect()
    never_awaited = [w for w in caught if "never awaited" in str(w.message)]
    assert not never_awaited, [str(w.message) for w in never_awaited]
    assert _wait_until(lambda: not _zip_stream_threads(), seconds=3.0)


def test_at_most_eight_items_are_in_flight_while_nobody_reads():
    producer = Producer(1000)

    async def go():
        stream = stream_from_thread(iter(producer))
        await stream.__anext__()  # start the worker, then stop reading
        await asyncio.sleep(0.4)
        produced = producer.produced
        await stream.aclose()
        return produced

    produced = asyncio.run(go())
    # 1 taken + 8 slots + the one the worker holds while it waits for a free slot
    assert 8 <= produced <= 10, produced


def test_the_worker_hands_items_over_without_creating_coroutines():
    tree = ast.parse(CORE_PATH.read_text(encoding="utf-8"))
    function = next(
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_stream_from_thread"
    )
    calls = {ast.unparse(c.func) for c in ast.walk(function) if isinstance(c, ast.Call)}
    assert "asyncio.run_coroutine_threadsafe" not in calls
    assert "loop.call_soon_threadsafe" in calls
