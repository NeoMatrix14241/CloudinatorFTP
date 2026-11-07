"""
5.44 (ASYNC_BLOCKING_REFACTOR_PLAN, T7): `helpers/walk_executor.run_walk` - long folder walks run
in a pool of their own (2 threads), so they never queue up the loop's default thread pool.

The helper is loaded from its file (standard library only). A second group reads the three
callers with `ast` and checks they use it.
"""

import ast
import asyncio
import importlib.util
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER_PATH = ROOT / "helpers" / "walk_executor.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "walk_executor_under_test", HELPER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_importing_starts_no_thread_and_creates_no_pool():
    before = threading.active_count()
    module = _load()
    assert module._state["executor"] is None
    assert threading.active_count() == before


def test_the_walk_runs_in_a_walk_thread_and_returns_its_value():
    module = _load()

    async def go():
        return await module.run_walk(
            lambda a, b: (a + b, threading.current_thread().name), 2, 3
        )

    total, name = asyncio.run(go())
    assert total == 5 and name.startswith("walk")


def test_an_exception_of_the_walk_is_raised_to_the_caller():
    module = _load()

    def boom():
        raise OSError("disk went away")

    async def go():
        await module.run_walk(boom)

    with pytest.raises(OSError, match="disk went away"):
        asyncio.run(go())


def test_at_most_two_walks_run_at_once_and_the_default_pool_is_untouched():
    module = _load()
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    def walk():
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.1)
        with lock:
            state["now"] -= 1

    async def go():
        loop = asyncio.get_running_loop()
        await asyncio.gather(*(module.run_walk(walk) for _ in range(6)))
        return getattr(loop, "_default_executor", None)

    assert asyncio.run(go()) is None
    assert state["peak"] == module.WALK_WORKERS == 2


def test_one_pool_is_shared_by_every_caller():
    module = _load()
    assert module._get_executor() is module._get_executor()


# ------------------------------------------------------------------------ the callers


def _calls(path, function):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == function
        ):
            return [
                f"{ast.unparse(c.func)}({', '.join(ast.unparse(a) for a in c.args)})"
                for c in ast.walk(node)
                if isinstance(c, ast.Call)
            ]
    raise AssertionError(f"{path}:{function} not found")


@pytest.mark.parametrize(
    ("path", "function", "expected"),
    [
        (
            "routes/stats.py",
            "_cached_storage_stats",
            "run_walk(storage.get_storage_stats)",
        ),
        ("routes/shares.py", "shared_download", "run_walk(_dir_size, full_path)"),
        ("routes/files.py", "dir_info", "run_walk(_dir_info_live_sync, path)"),
    ],
)
def test_the_three_long_walks_use_the_walk_pool(path, function, expected):
    calls = _calls(path, function)
    assert expected in calls, calls
    assert not [
        c for c in calls if c.startswith("asyncio.to_thread(") and "walk" in c.lower()
    ]
