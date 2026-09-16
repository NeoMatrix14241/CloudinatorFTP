"""
Shared logging setup for CloudinatorFTP.

One central logger ("cloudinatorftp") owns three things — a console
handler (stdout), a daily-rotating file (DailyDatedFileHandler), and a
stdout/stderr tee (_TeeStream) — and every other logger in the project
(Hypercorn's errorlog, app.py's per-request logger, protocol_manager.py's
logger) is a *child* logger with no handlers of its own, so everything
funnels into the same place instead of several separate files.

History, briefly (full detail in CLAUDE.md's troubleshooting log):
previously app.py's request logger wrote its own logs/requests.log,
prod_server.py had no file output of its own (whoever launched it was
expected to shell-redirect stdout to a manually timestamped filename that
never rotated), and manage.sh separately generated a new timestamped file
per `start`. All reconciled into the single scheme below on 2026-09-15,
after also trying (and rejecting) having manage.sh redirect the child
process's stdout/stderr into this same file — that caused every logger
line to be written twice (once here, once via the redirect capturing this
module's own console handler) and still couldn't give plain print() calls
correct midnight rotation, since an OS-level file descriptor is fixed at
process start and can't itself follow DailyDatedFileHandler onto a new
day's file the way this module's direct writes do.

Final design: manage.sh no longer touches the child's stdout/stderr at
all (both go to /dev/null when launched detached). Full capture is
instead achieved entirely inside this process:
  - DailyDatedFileHandler: every real `logging` call (request timing,
    Hypercorn's errorlog, protocol_manager's logger, app_logger) writes
    directly to today's file, correct rotation, no OS redirect involved.
  - _TeeStream: replaces sys.stdout/sys.stderr so plain print() calls
    (the ~267 not converted to logger calls) are ALSO captured into that
    same file, tagged [PRINT]/[STDERR] to distinguish them from real
    [INFO]/[WARNING]/etc. logger lines, while still appearing on screen
    for foreground/interactive runs. This also picks up correct daily
    rotation, since it writes through DailyDatedFileHandler.write_line()
    rather than through any fixed OS descriptor.
  - sys.excepthook / threading.excepthook: uncaught exceptions (main
    thread and background threads both) are logged as CRITICAL through
    the real logging path — with full traceback and correct rotation —
    rather than relying on the tee to catch a raw traceback dump.
Net effect: every line the process ever produces, logger-based or plain
print(), ends up in exactly one place, with correct rotation, exactly
once — no duplication, nothing silently lost.

Component tag (2026-09-15): every line also carries [component] — e.g.
[prod_server] or [webdav_server] — identifying which OS process actually
wrote it. Needed because CLOUDINATOR_LOG_PREFIX (above) deliberately
makes the WebDAV subprocess share the main process's log FILE, which
means the filename alone can no longer answer "which process wrote this
line" once they're interleaved together — this tag is what does.
"""

import logging
import os
import sys
import threading
from datetime import datetime

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

# Prefix matches manage.sh's own "prod"/"dev" naming (script_for()/type in
# manage.sh) so both land in the same file manage.sh already knows how to
# find via its "${type}_server_*.log" glob (current_log_for(), clean-logs).
#
# Two sources, checked in order:
#   1. CLOUDINATOR_LOG_PREFIX env var — set by protocol_manager.py when it
#      spawns webdav_server.py as its own OS process (own interpreter, own
#      __main__ = "webdav_server", which __main__-detection below would
#      never recognize). Without this, WebDAV silently fell through to the
#      "app" fallback and wrote its own separate logs/app_YYYY-MM-DD.log
#      instead of joining the parent's prod_server_*.log/dev_server_*.log
#      — a second, undocumented log file that only shows up once WebDAV
#      has spawned at least once (2026-09-15 regression: `manage.sh start
#      server` produced an extra app_*.log that `python prod_server.py`
#      run directly never did, since a direct run's first WebDAV spawn
#      hit no pre-existing port conflict and never needed a respawn).
#   2. __main__ detection — which script is __main__ in *this* process.
#      Previously hardcoded to "prod_server" unconditionally, which meant
#      dev_server.py was silently writing into a file literally named
#      prod_server_....log; fixed to actually check __main__. Falls back
#      to "app" if this is imported directly rather than via prod_server.py/
#      dev_server.py (e.g. `python app.py` directly, or a one-off script/
#      REPL import) — that fallback is intentional there, just not correct
#      for a subprocess that has its own separate __main__ entirely.
_main_file = getattr(sys.modules.get("__main__"), "__file__", "") or ""
_main_name = os.path.splitext(os.path.basename(_main_file))[0]
_LOG_PREFIX = os.environ.get("CLOUDINATOR_LOG_PREFIX") or (
    _main_name if _main_name in ("prod_server", "dev_server") else "app"
)

# Per-line component tag (2026-09-15) — distinct from _LOG_PREFIX above.
# _LOG_PREFIX picks which FILE to write to, and is deliberately overridden
# for the WebDAV subprocess so it joins the parent's file instead of
# writing its own. But that override means _LOG_PREFIX can no longer be
# used to tell WHICH process actually wrote a given line once several
# processes share one file — a line from the port-5000 web UI and a line
# from the separate webdav_server.py process were structurally
# indistinguishable, same [INFO]/[WARNING] tags, nothing identifying the
# source. _main_name above is NOT overridden by the env var — it's
# whatever script genuinely is __main__ in *this* process ("webdav_server"
# in that subprocess, "prod_server"/"dev_server" in the main one) — so
# it's the right thing to tag every line with instead.
_COMPONENT = _main_name or "unknown"

_FORMATTER = logging.Formatter(
    "%(asctime)s [%(levelname)s] [" + _COMPONENT + "] %(message)s",
    "%Y-%m-%d %H:%M:%S",
)


class DailyDatedFileHandler(logging.Handler):
    """Writes to <log_dir>/<prefix>_<YYYY-MM-DD>.log, re-checked on every
    emit(). Unlike logging.handlers.TimedRotatingFileHandler — whose *live*
    file keeps a fixed name and only *past* days get a dated suffix once a
    rollover happens — this keeps TODAY's active file dated too, so a
    process that's been running for days rolls onto a new file the instant
    the date changes, with no restart and no reliance on the process ever
    stopping to pick up the new name.
    """

    def __init__(self, log_dir: str, prefix: str, encoding: str = "utf-8"):
        super().__init__()
        self._log_dir = log_dir
        self._prefix = prefix
        self._encoding = encoding
        self._current_date = None
        self._stream = None
        os.makedirs(log_dir, exist_ok=True)
        self._open_for_today()

    def _path_for(self, date_str: str) -> str:
        return os.path.join(self._log_dir, f"{self._prefix}_{date_str}.log")

    def _open_for_today(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._stream is not None:
                self._stream.close()
            self._current_date = today
            self._stream = open(self._path_for(today), "a", encoding=self._encoding)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._open_for_today()  # cheap: one strftime call per line
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def write_line(self, line: str) -> None:
        """For _TeeStream below — writes one already-formatted line
        directly, same date-checked file as emit() above, bypassing the
        LogRecord/Formatter machinery since raw print() output has no
        record to format."""
        try:
            self._open_for_today()
            self._stream.write(line + "\n")
            self._stream.flush()
        except Exception:
            pass

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
        super().close()


# ---------------------------------------------------------------------------
# The one central logger every other logger in the project funnels into.
# ---------------------------------------------------------------------------
class _TeeStream:
    """Wraps a real stream (the original sys.stdout or sys.stderr) so every
    write() goes to BOTH that real stream (so foreground/interactive runs
    still show it on screen) AND the same daily-rotating file
    DailyDatedFileHandler manages — giving plain print() calls the same
    full capture and correct midnight rotation as everything that goes
    through the logging module, with zero changes needed at any of the
    ~267 individual print() call sites across the project.

    Line-buffered: print() may call write() more than once per line (the
    text, then a separate call for the trailing newline), so this
    accumulates into self._buffer and only writes a complete line to the
    file once a "\\n" shows up, rather than writing partial fragments.
    """

    def __init__(self, real_stream, file_handler: "DailyDatedFileHandler", tag: str):
        self._real_stream = real_stream
        self._file_handler = file_handler
        self._tag = tag
        self._buffer = ""

    def write(self, s: str) -> int:
        self._real_stream.write(s)
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:  # skip the empty tail from print()'s trailing \n
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._file_handler.write_line(
                    f"{ts} [{self._tag}] [{_COMPONENT}] {line}"
                )
        return len(s)

    def flush(self) -> None:
        self._real_stream.flush()

    def isatty(self) -> bool:
        return getattr(self._real_stream, "isatty", lambda: False)()

    def __getattr__(self, name: str):
        # Anything not explicitly implemented above (reconfigure, encoding,
        # buffer, fileno, mode, closed, ...) falls through to the real
        # stream. This is what write()/flush()/isatty() above intentionally
        # DON'T do — those three need the tee's own dual-write behavior —
        # but every other real TextIOWrapper attribute/method genuinely
        # just needs to reach the real stream unchanged. Found the hard
        # way: app.py calls sys.stdout.reconfigure(line_buffering=True) at
        # import time, which crashed with AttributeError before this
        # existed, since _TeeStream had no reconfigure() of its own.
        # __getattr__ (not __getattribute__) only fires for attributes
        # Python couldn't find normally, so this never intercepts write/
        # flush/isatty/_real_stream/etc. themselves.
        return getattr(self._real_stream, name)


_root = logging.getLogger("cloudinatorftp")

# Real, pre-tee streams — set below, but declared here so get_real_stdout()/
# get_real_stderr() always have a sane fallback (sys.__stdout__/__stderr__)
# even in the unlikely case this module's setup block doesn't run (e.g. a
# second import after some other code already tore down _root's handlers).
_real_stdout = sys.__stdout__
_real_stderr = sys.__stderr__

if not _root.handlers:
    # Targets the real, original stdout — captured here BEFORE sys.stdout
    # gets replaced by the tee below, so this handler's own writes go
    # straight to the terminal only and never loop back through the tee
    # (which would otherwise double-write every logger line into the file
    # a second time, on top of DailyDatedFileHandler's own direct write).
    _console_handler = logging.StreamHandler(sys.stdout)
    _console_handler.setFormatter(_FORMATTER)
    _root.addHandler(_console_handler)

    _file_handler = DailyDatedFileHandler(_LOG_DIR, _LOG_PREFIX)
    _file_handler.setFormatter(_FORMATTER)
    _root.addHandler(_file_handler)

    # Save the real streams BEFORE replacing them, and expose them via
    # get_real_stdout()/get_real_stderr() below — added 2026-09-16 for
    # protocol_manager.py's WebDAV-subprocess-output relay (_pump_child_
    # output), which was calling plain print() to show the relayed lines
    # on screen. That print() went through THIS process's own tee, which
    # wrote a second copy of every WebDAV line into the shared log file —
    # on top of the WebDAV subprocess's own direct write via its own
    # logging_setup instance — duplicating every line. Writing to the
    # real stream directly instead keeps the "show it on screen live"
    # value (and the crash-diagnosis value for the narrow case of a
    # WebDAV crash so early that even ITS OWN logging_setup import hasn't
    # finished yet) without the second file-write.
    _real_stdout = sys.stdout
    _real_stderr = sys.stderr

    # Install the tee AFTER the console handler above has already captured
    # its reference to the real stdout. PRINT tags plain print() output,
    # STDERR tags anything written directly to stderr outside the logging
    # module (rare, but possible) — both land in the same daily file,
    # distinguishable from real [INFO]/[WARNING]/etc. logger lines by tag.
    sys.stdout = _TeeStream(sys.stdout, _file_handler, "PRINT")
    sys.stderr = _TeeStream(sys.stderr, _file_handler, "STDERR")

_root.setLevel(logging.DEBUG)
_root.propagate = False


def get_real_stdout():
    """The original stdout, from before the tee replaced sys.stdout — for
    callers that need to write directly to the console without it being
    captured (and duplicated) into the shared log file a second time.
    See protocol_manager.py's _pump_child_output for the motivating case.
    """
    return _real_stdout


def get_real_stderr():
    """See get_real_stdout() — same idea, for stderr."""
    return _real_stderr


def _log_uncaught_exception(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        # Ctrl-C / manage.sh's own SIGTERM-then-SIGKILL stop sequence isn't
        # a crash — let it behave normally (default traceback/exit), don't
        # log it as an error.
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    _root.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))


def _log_uncaught_thread_exception(args: threading.ExceptHookArgs) -> None:
    # threading.excepthook (Python 3.8+) — main-thread sys.excepthook above
    # does NOT catch exceptions raised inside background threads (the
    # several this project starts: file_monitor, protocol_manager's
    # per-protocol threads, etc.), so those need their own hook or they'd
    # go right back to being invisible once manage.sh stops redirecting
    # stderr to a file.
    _root.critical(
        "Uncaught exception in thread %r",
        args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


sys.excepthook = _log_uncaught_exception
threading.excepthook = _log_uncaught_thread_exception


def get_logger(name: str) -> logging.Logger:
    """Child logger of "cloudinatorftp" — no handlers of its own, so its
    records bubble up to the console + daily file above. `name` becomes
    the suffix, e.g. get_logger("requests") -> "cloudinatorftp.requests".
    """
    logger = logging.getLogger(f"cloudinatorftp.{name}")
    logger.handlers.clear()
    logger.propagate = True
    logger.setLevel(logging.DEBUG)
    return logger
