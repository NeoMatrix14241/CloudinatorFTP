"""
5.44 (ASYNC_BLOCKING_REFACTOR_PLAN, T6 / R2): requests waiting for an image conversion must not
park a worker of the shared default thread pool.

`to_thread(t.join, 60)` and `to_thread(event.wait, 60)` held one pool worker per waiting request
for the whole conversion (up to 60 s); the pool also serves logins, listings, chunk writes and
downloads. Now the conversion thread resolves one asyncio future per waiting request.

The REAL registry functions are cut out of `routes/image_preview.py` with `ast` (the module
cannot be imported: it starts the whole application) and run on a plain asyncio loop; a second
group reads the `image_preview` handler itself. `routes/admin.py` keeps reading
`_img_conv_events` (cache keys of running conversions) under `_img_events_mutex`: the guard at
the end names that contract.
"""

import ast
import asyncio
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
IMAGE_PATH = ROOT / "routes" / "image_preview.py"
ADMIN_PATH = ROOT / "routes" / "admin.py"
FUNCTIONS = {"_img_wake", "_img_notify_waiters", "_run_img_conversion"}
STATE = {"_img_events_mutex", "_img_conv_events", "_img_conv_waiters"}


def _tree():
    return ast.parse(IMAGE_PATH.read_text(encoding="utf-8"))


def _load(convert):
    nodes, seen = [], set()
    for node in _tree().body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            nodes.append(node)
            seen.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            if names & STATE:
                nodes.append(node)
                seen |= names & STATE
    assert (
        seen == FUNCTIONS | STATE
    ), f"image_preview.py lost {(FUNCTIONS | STATE) - seen}"
    namespace = {"threading": threading, "_convert_to_webp": convert}
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(IMAGE_PATH), "exec"),
        namespace,
    )  # noqa: S102
    return namespace


def _register(ns, loop, key, count):
    """What the handler does in its critical section: event + waiters, then start the thread."""
    waiters = []
    with ns["_img_events_mutex"]:
        ns["_img_conv_events"][key] = threading.Event()
        for _ in range(count):
            future = loop.create_future()
            ns["_img_conv_waiters"].setdefault(key, []).append((loop, future))
            waiters.append(future)
    return waiters


def test_every_waiter_is_woken_without_using_the_default_thread_pool():
    release = threading.Event()
    ns = _load(lambda *args: release.wait(5))

    async def go():
        loop = asyncio.get_running_loop()
        waiters = _register(ns, loop, "k1", 3)
        thread = threading.Thread(
            target=ns["_run_img_conversion"], args=("p", "k1", False)
        )
        thread.start()
        await asyncio.sleep(0.05)
        assert not any(w.done() for w in waiters)  # still converting
        release.set()
        await asyncio.wait_for(asyncio.gather(*waiters), 3)
        thread.join(3)
        return getattr(loop, "_default_executor", None)

    assert asyncio.run(go()) is None  # nothing ever asked for a pool worker
    assert ns["_img_conv_events"] == {} and ns["_img_conv_waiters"] == {}


def test_a_failing_conversion_still_wakes_the_waiters_and_clears_the_event():
    def boom(*args):
        raise RuntimeError("libvips failed")

    ns = _load(boom)

    async def go():
        loop = asyncio.get_running_loop()
        waiters = _register(ns, loop, "k2", 2)
        errors = []

        def run():
            try:
                ns["_run_img_conversion"]("p", "k2", False)
            except RuntimeError as error:
                errors.append(str(error))

        thread = threading.Thread(target=run)
        thread.start()
        await asyncio.wait_for(asyncio.gather(*waiters), 3)
        thread.join(3)
        return errors

    assert asyncio.run(go()) == ["libvips failed"]
    # before 5.44 the event stayed registered and every later request waited the full 60 s
    assert ns["_img_conv_events"] == {}


def test_a_waiter_that_already_gave_up_is_skipped():
    ns = _load(lambda *args: None)

    async def go():
        loop = asyncio.get_running_loop()
        gone, staying = _register(ns, loop, "k3", 2)
        gone.cancel()  # the client left
        await asyncio.get_running_loop().run_in_executor(
            None, ns["_run_img_conversion"], "p", "k3", False
        )
        await asyncio.wait_for(staying, 3)
        return gone.cancelled(), staying.done()

    assert asyncio.run(go()) == (True, True)


def test_a_closed_loop_does_not_break_the_conversion_thread():
    ns = _load(lambda *args: None)
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    loop.close()
    ns["_img_conv_events"]["k4"] = threading.Event()
    ns["_img_conv_waiters"]["k4"] = [(loop, future)]
    ns["_run_img_conversion"]("p", "k4", False)  # must not raise
    assert ns["_img_conv_events"] == {}


# --------------------------------------------------------------- the handler itself


def _handler():
    nodes = [
        n
        for n in _tree().body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "image_preview"
    ]
    assert len(nodes) == 1
    return nodes[0]


def test_the_handler_no_longer_parks_a_pool_thread_to_wait():
    calls = []
    for node in ast.walk(_handler()):
        if isinstance(node, ast.Call):
            args = ", ".join(ast.unparse(a) for a in node.args)
            calls.append(f"{ast.unparse(node.func)}({args})")
    parked = [
        c
        for c in calls
        if c.startswith("asyncio.to_thread(") and ("join" in c or "wait" in c)
    ]
    assert not parked, parked
    assert any(c.startswith("asyncio.wait_for(waiter") for c in calls)


def test_the_handler_registers_its_waiter_inside_the_critical_section():
    handler = _handler()
    mutex_blocks = [
        n
        for n in ast.walk(handler)
        if isinstance(n, ast.With) and "_img_events_mutex" in ast.unparse(n.items[0])
    ]
    registering = [
        b
        for b in mutex_blocks
        if "_img_conv_waiters" in ast.unparse(b)
        and "_img_conv_events[cache_key]" in ast.unparse(b)
    ]
    assert registering, "the waiter must be registered where the converter is decided"


def test_admin_still_finds_the_names_it_reads():
    imported = set()
    for node in ast.parse(ADMIN_PATH.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and node.module == "routes.image_preview":
            imported |= {a.name for a in node.names}
    assert {"_img_cache_root", "_img_conv_events", "_img_events_mutex"} <= imported
