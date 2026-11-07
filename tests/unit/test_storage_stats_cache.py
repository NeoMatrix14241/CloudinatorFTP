"""
5.44 (ASYNC_BLOCKING_REFACTOR_PLAN, T1): `/api/storage_stats_slow` and
`/api/storage_stats_debug` used to run `storage.get_storage_stats()` (a walk of ROOT_DIR) on the
event loop. Both now go through `routes/stats._cached_storage_stats()`: one worker-thread walk,
shared by parallel callers and kept for 30 s.

The REAL helper and its module-level state are cut out of `routes/stats.py` with `ast`
(the module cannot be imported: it starts the whole application) and run on a plain asyncio
loop with a fake `storage`.
"""

import ast
import asyncio
import importlib.util
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
STATS_PATH = ROOT / "routes" / "stats.py"
STATE_NAMES = {"_STATS_CACHE_TTL_SECS", "_stats_cache", "_stats_lock"}


def _tree():
    return ast.parse(STATS_PATH.read_text(encoding="utf-8"))


def _walk_executor():
    spec = importlib.util.spec_from_file_location(
        "walk_executor_for_stats", ROOT / "helpers" / "walk_executor.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(storage, ttl=None):
    body = []
    for node in _tree().body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in STATE_NAMES for t in node.targets
        ):
            body.append(node)
        elif (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_cached_storage_stats"
        ):
            body.append(node)
    names = {getattr(n, "name", None) for n in body}
    assert "_cached_storage_stats" in names, "stats._cached_storage_stats is gone"
    assert len(body) == 4, "the cache state or helper changed shape"
    namespace = {
        "asyncio": asyncio,
        "time": time,
        "storage": storage,
        # the real helpers/walk_executor.run_walk, loaded from its file (no project imports)
        "run_walk": _walk_executor().run_walk,
    }
    exec(
        compile(ast.Module(body=body, type_ignores=[]), str(STATS_PATH), "exec"),
        namespace,
    )  # noqa: S102
    if ttl is not None:
        namespace["_STATS_CACHE_TTL_SECS"] = ttl
    return namespace["_cached_storage_stats"]


class FakeStorage:
    def __init__(self, result=None, delay=0.0, error=None):
        self.result = (
            result if result is not None else {"total_space": 100, "file_count": 1}
        )
        self.delay = delay
        self.error = error
        self.calls = 0
        self.threads = []

    def get_storage_stats(self):
        self.calls += 1
        self.threads.append(threading.current_thread())
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return dict(self.result)


def test_the_walk_runs_in_a_worker_thread():
    storage = FakeStorage()
    stats = _load(storage)
    asyncio.run(stats())
    assert storage.calls == 1
    assert storage.threads[0] is not threading.main_thread()
    assert storage.threads[0].name.startswith(
        "walk"
    )  # the walk pool, not the default one


def test_parallel_callers_share_one_walk():
    storage = FakeStorage(delay=0.2)
    stats = _load(storage)

    async def go():
        return await asyncio.gather(*(stats() for _ in range(8)))

    results = asyncio.run(go())
    assert storage.calls == 1
    assert all(r == {"total_space": 100, "file_count": 1} for r in results)


def test_a_second_call_inside_the_ttl_is_served_from_the_cache():
    storage = FakeStorage()
    stats = _load(storage, ttl=60)

    async def go():
        await stats()
        await stats()

    asyncio.run(go())
    assert storage.calls == 1


def test_the_cache_expires():
    storage = FakeStorage()
    stats = _load(storage, ttl=0.05)

    async def go():
        await stats()
        await asyncio.sleep(0.12)
        await stats()

    asyncio.run(go())
    assert storage.calls == 2


def test_an_exception_is_not_cached():
    storage = FakeStorage(error=OSError("disk gone"))
    stats = _load(storage)

    async def go():
        for _ in range(2):
            try:
                await stats()
            except OSError:
                # Expected: the fake walk raises every time. The point of the test is that the
                # second call walks again instead of being served from a cached failure.
                continue

    asyncio.run(go())
    assert storage.calls == 2


def test_the_all_zero_failure_answer_is_not_cached():
    zero = {"total_space": 0, "used_space": 0, "free_space": 0, "file_count": 0}
    storage = FakeStorage(result=zero)
    stats = _load(storage)

    async def go():
        first = await stats()
        second = await stats()
        return first, second

    first, second = asyncio.run(go())
    assert first == zero and second == zero
    assert storage.calls == 2


def test_callers_get_a_copy_not_the_cached_dict():
    storage = FakeStorage()
    stats = _load(storage)

    async def go():
        first = await stats()
        first["file_count"] = 999
        return await stats()

    assert asyncio.run(go())["file_count"] == 1


def test_the_two_handlers_no_longer_call_the_walk_directly():
    handlers = [
        n
        for n in _tree().body
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name in ("storage_stats_slow_api", "storage_stats_debug")
    ]
    assert len(handlers) == 2
    for handler in handlers:
        calls = {
            ast.unparse(n.func) for n in ast.walk(handler) if isinstance(n, ast.Call)
        }
        assert "storage.get_storage_stats" not in calls, handler.name
        assert "_cached_storage_stats" in calls, handler.name
