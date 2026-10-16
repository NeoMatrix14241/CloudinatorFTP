"""
Parent-death watchdog for child processes (orphan guard).

WebDAV (webdav_server.py) and the Version Engine (version_engine.py
--worker) are separate OS processes started with subprocess.Popen by
protocol_manager.py / version_engine.py. A child process does NOT die when
its parent does: on Windows there is no process tree, and on Linux a
SIGKILL / os._exit() / crash of the parent just re-parents the child to
init. manage.sh's old `stop` hard-killed only the main PID, so the Version
Engine kept scanning and snapshotting forever as an orphan.

How it works: the parent puts its own PID into the environment variable
CLOUDINATOR_PARENT_PID when it spawns the child. The child calls start()
once; a daemon thread then polls that PID every second. When the parent is
gone it runs the optional on_gone() callback (graceful shutdown), and then
exits the process with os._exit(0). A hard timer guarantees the exit even
if on_gone() hangs.

Why an explicit PID and not os.getppid(): with a Windows venv the Python
launcher shim can sit between the real parent and the child, so the
"parent" the OS reports is the shim, which stays alive as long as the
child does.

Leaf utility: standard library only. No-op when the variable is absent
(for example `python webdav_server.py` started by hand).
"""

import os
import sys
import threading
import time

ENV_VAR = "CLOUDINATOR_PARENT_PID"

_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_ERROR_INVALID_PARAMETER = 87  # OpenProcess: no process with that PID


def _say(msg: str) -> None:
    try:
        print(msg, flush=True)
    except Exception:
        # stdout pipe to the dead parent is closed; nothing else to do.
        pass


def _make_alive_check(pid: int):
    """Return a zero-argument function that is True while process `pid`
    exists. Returns None if the check cannot be set up, and the string
    "gone" if the process is already dead."""
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k32.WaitForSingleObject.restype = ctypes.c_uint32
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        handle = k32.OpenProcess(_SYNCHRONIZE, 0, pid)
        if not handle:
            if ctypes.get_last_error() == _ERROR_INVALID_PARAMETER:
                return "gone"
            return None  # e.g. access denied: cannot watch, do not guess

        # Holding the handle also stops Windows from reusing the PID.
        def _alive_win() -> bool:
            return k32.WaitForSingleObject(handle, 0) != _WAIT_OBJECT_0

        return _alive_win

    def _alive_posix() -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return True
        return True

    return _alive_posix


def start(
    on_gone=None, label: str = "child", poll: float = 1.0, grace: float = 15.0
) -> bool:
    """Start the watchdog thread. Returns True if it is watching.

    on_gone: optional callable run once when the parent is gone (graceful
             shutdown of this process). Exceptions are swallowed.
    grace:   seconds after which the process is force-exited even if
             on_gone() has not returned.
    """
    raw = os.environ.get(ENV_VAR, "")
    try:
        parent_pid = int(raw)
    except ValueError:
        return False
    if parent_pid <= 0 or parent_pid == os.getpid():
        return False

    alive = _make_alive_check(parent_pid)
    if alive is None:
        _say(f"[{label}] parent watchdog unavailable (cannot open parent process)")
        return False

    def _terminate() -> None:
        _say(
            f"[{label}] parent process {parent_pid} is gone - shutting down (orphan guard)"
        )
        timer = threading.Timer(grace, os._exit, args=(0,))
        timer.daemon = True
        timer.start()
        try:
            if on_gone is not None:
                on_gone()
        except Exception:
            # Shutting down anyway; the exit below is unconditional.
            pass
        os._exit(0)

    if alive == "gone":
        threading.Thread(
            target=_terminate, name=f"{label}-orphan-guard", daemon=True
        ).start()
        return True

    def _loop() -> None:
        while alive():
            time.sleep(poll)
        _terminate()

    threading.Thread(target=_loop, name=f"{label}-orphan-guard", daemon=True).start()
    return True
