"""
helpers/walk_executor.py - a small thread pool just for long folder walks (CLAUDE.md 5.44).

`asyncio.to_thread()` runs on the event loop's DEFAULT executor (min(32, cpu + 4) workers on this
Python). That pool also serves logins (bcrypt), directory listings, every chunk write of an upload
and every download. A walk of a big folder (`storage.get_storage_stats`, the share page's folder
size, the live `dir_info` of a folder that is not in the index yet; the file table asks once per
visible folder row) takes seconds, and a few of them at the same moment used to queue everything
else behind them. `run_walk()` sends those walks to a pool of its own with WALK_WORKERS threads
(`walk_0`, `walk_1`): at most that many walks run at once, the rest wait their turn in THIS pool,
and the default pool stays free.

The pool is created on first use (importing this module costs nothing and starts no thread) and is
never shut down explicitly: its threads end with the interpreter, like the default pool's.

Standard library only. Never imports the application.
"""

import asyncio
import functools
import threading
from concurrent.futures import ThreadPoolExecutor

WALK_WORKERS = 2

_state = {"executor": None}
_state_lock = threading.Lock()


def _get_executor():
    """The shared walk pool, created by the first caller."""
    with _state_lock:
        if _state["executor"] is None:
            _state["executor"] = ThreadPoolExecutor(
                max_workers=WALK_WORKERS, thread_name_prefix="walk"
            )
        return _state["executor"]


async def run_walk(func, *args):
    """Run `func(*args)` in the walk pool and return its result.

    Pass the callable UNCALLED and plain values, exactly as for `asyncio.to_thread()`;
    an exception raised by `func` is raised here."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), functools.partial(func, *args))
