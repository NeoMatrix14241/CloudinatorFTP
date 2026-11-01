"""
helpers/upload_perf.py - measuring and easing the chunk-upload path (CLAUDE.md 5.41).

Standard library only, except `parse_form_in_memory`, which imports werkzeug inside the function
(Quart already depends on it). Nothing here imports the application, so
tests/unit/test_upload_perf.py imports this file as it is.

  StageTimer, UploadTimingLog   wall-clock stages of one /upload request and a running average
  LagStats, watch_loop_lag,     how late the asyncio event loop wakes up (a loop that is blocked
  LagProbeStarter               by synchronous work shows up here as lag)
  IdleDeferral                  run an action once a "busy" condition is over, with a hard cap
                                on how long it may be postponed
  parse_form_in_memory          a multipart body that is already in RAM, parsed WITHOUT the
                                spooled temp file in %TEMP% that Quart / Werkzeug use by default

The timing and the lag probe are OFF unless `config.UPLOAD_TIMING_ENABLED` is true (default
False); `parse_form_in_memory` is used only when `config.UPLOAD_CHUNKS_IN_MEMORY` is true
(default False). See routes/uploads.py.
"""

import asyncio
import threading
import time


# ---------------------------------------------------------------------------
# Stage timing of one request
# ---------------------------------------------------------------------------
class StageTimer:
    """Consecutive stages of ONE request; every method returns at once when `enabled` is False.

    `mark(name)` closes the stage that started at the previous mark. `note(name, seconds)` records
    a sub-timing that was measured elsewhere (a worker thread); notes are shown but never added to
    the total, because they overlap a stage.
    """

    def __init__(self, enabled, clock=time.perf_counter):
        self.enabled = bool(enabled)
        self._clock = clock
        self.stages = []  # [(name, seconds)]
        self.notes = []  # [(name, seconds)]
        if self.enabled:
            self._last = clock()

    def mark(self, name):
        if not self.enabled:
            return
        now = self._clock()
        self.stages.append((name, now - self._last))
        self._last = now

    def note(self, name, seconds):
        if self.enabled:
            self.notes.append((name, seconds))

    def total(self):
        return sum(seconds for _, seconds in self.stages)


class UploadTimingLog:
    """One log line per chunk and an average over every `summary_every` chunks."""

    def __init__(self, log=print, summary_every=20):
        self._log = log
        self._every = max(1, int(summary_every))
        self._lock = threading.Lock()
        self._reset()

    def _reset(self):
        self._count = 0
        self._bytes = 0
        self._seconds = 0.0
        self._stage_sums = {}

    def report(self, timer, nbytes, label):
        """Log the stages of one finished chunk. Does nothing for a disabled timer."""
        if not timer.enabled:
            return
        total = timer.total()
        megabytes = nbytes / (1024 * 1024)
        rate = megabytes / total if total > 0 else 0.0
        stages = " | ".join(f"{name} {seconds:.3f}s" for name, seconds in timer.stages)
        notes = ", ".join(f"{name} {seconds:.3f}s" for name, seconds in timer.notes)
        line = f"⏱️ upload {label}: {stages}"
        if notes:
            line += f" (in the worker thread: {notes})"
        line += f" | total {total:.3f}s, {megabytes:.1f} MB, {rate:.1f} MB/s"
        summary = None
        with self._lock:
            self._count += 1
            self._bytes += nbytes
            self._seconds += total
            for name, seconds in timer.stages:
                self._stage_sums[name] = self._stage_sums.get(name, 0.0) + seconds
            if self._count >= self._every:
                average = " | ".join(
                    f"{name} {seconds / self._count:.3f}s"
                    for name, seconds in self._stage_sums.items()
                )
                avg_rate = (
                    self._bytes / (1024 * 1024) / self._seconds
                    if self._seconds > 0
                    else 0.0
                )
                summary = (
                    f"⏱️ upload average of the last {self._count} chunks: {average} "
                    f"| {avg_rate:.1f} MB/s while a chunk was being handled"
                )
                self._reset()
        self._log(line)
        if summary:
            self._log(summary)


# ---------------------------------------------------------------------------
# Event-loop lag probe
# ---------------------------------------------------------------------------
class LagStats:
    """Lag samples (seconds) of one reporting window."""

    def __init__(self):
        self.samples = []

    def add(self, lag):
        self.samples.append(lag)

    def reset(self):
        self.samples = []

    def summary(self):
        """{'count', 'p50', 'p95', 'max'} in seconds, or None when there is no sample."""
        if not self.samples:
            return None
        data = sorted(self.samples)
        count = len(data)
        return {
            "count": count,
            "p50": data[count // 2],
            "p95": data[min(count - 1, int(count * 0.95))],
            "max": data[-1],
        }


async def watch_loop_lag(
    interval=0.1,
    report_every=30.0,
    warn_over=0.5,
    log=print,
    clock=time.monotonic,
    sleep=asyncio.sleep,
    rounds=None,
):
    """Sleep `interval` seconds over and over and log how much LATER than that the loop woke up.

    The loop only wakes this task when it is free, so a request handler that does synchronous work
    (a 10 MB disk write, a database call) delays the wake-up by about that long. One line every
    `report_every` seconds (median, 95th percentile, maximum), plus an immediate warning for a
    single stall of `warn_over` seconds or more. `rounds` limits the number of samples (tests).
    """
    stats = LagStats()
    window_start = clock()
    done = 0
    while rounds is None or done < rounds:
        before = clock()
        await sleep(interval)
        lag = max(0.0, clock() - before - interval)
        stats.add(lag)
        done += 1
        if lag >= warn_over:
            log(f"⚠️ event loop was blocked for about {lag:.2f}s")
        if clock() - window_start >= report_every:
            summary = stats.summary()
            if summary:
                log(
                    f"⏱️ event-loop lag, last {report_every:.0f}s: "
                    f"median {summary['p50'] * 1000:.0f} ms, "
                    f"p95 {summary['p95'] * 1000:.0f} ms, "
                    f"max {summary['max'] * 1000:.0f} ms ({summary['count']} samples)"
                )
            stats.reset()
            window_start = clock()


class LagProbeStarter:
    """Starts `watch_loop_lag` as a Quart background task, once, from a request handler.

    There is deliberately NO startup hook: tests/smoke.py (check 5) keeps `before_serving` and the
    other lifecycle hooks in middleware.py. A handler runs on the event loop, so
    `app.add_background_task` is safe there, and a probe that starts with the first upload is the
    one that matters: it measures the loop while uploads are being handled. A failure to start is
    logged and never raised (a diagnostic must not break an upload) and is not retried.
    """

    def __init__(self, log=print, **kwargs):
        self._log = log
        self._kwargs = kwargs
        self._lock = threading.Lock()
        self._tried = False

    def start_once(self, app):
        """True when this call started the probe, False when it had been started (or tried)."""
        with self._lock:
            if self._tried:
                return False
            self._tried = True
        try:
            app.add_background_task(watch_loop_lag, log=self._log, **self._kwargs)
        except Exception as exc:  # a diagnostic must never break the request
            self._log(f"⚠️ event-loop lag probe could not be started: {exc}")
            return False
        self._log("⏱️ event-loop lag probe started (config.UPLOAD_TIMING_ENABLED)")
        return True


# ---------------------------------------------------------------------------
# Postpone an action while something is busy
# ---------------------------------------------------------------------------
class IdleDeferral:
    """Run `action` when `busy()` is false; otherwise re-check every `interval` seconds.

    The wait is capped: `max_wait` seconds after the first postponed request the action runs even
    if `busy()` is still true (an abandoned upload stays "busy" for up to 30 minutes, and the
    action must not be postponed for that long). Requests that arrive while a re-check is already
    pending are merged into it. `busy` raising counts as "not busy": postponing must never be
    the reason an action does not run.
    """

    def __init__(
        self,
        action,
        busy,
        interval=5.0,
        max_wait=600.0,
        make_timer=threading.Timer,
        clock=time.monotonic,
        log=print,
    ):
        self._action = action
        self._busy = busy
        self._interval = interval
        self._max_wait = max_wait
        self._make_timer = make_timer
        self._clock = clock
        self._log = log
        self._lock = threading.Lock()
        self._waiting = False
        self._deadline = 0.0

    def _is_busy(self):
        try:
            return bool(self._busy())
        except Exception:  # see the class docstring: fail open
            return False

    def _schedule(self):
        timer = self._make_timer(self._interval, self._tick)
        timer.daemon = True
        timer.start()

    def _run(self):
        try:
            self._action()
        except Exception as exc:  # a timer thread must not die silently
            self._log(f"❌ deferred action failed: {exc}")

    def request(self):
        """Returns 'ran' (action ran now), 'deferred' (a re-check was scheduled) or 'merged'."""
        with self._lock:
            if self._waiting:
                return "merged"
            if self._is_busy():
                self._waiting = True
                self._deadline = self._clock() + self._max_wait
                self._schedule()
                return "deferred"
        self._run()
        return "ran"

    def _tick(self):
        with self._lock:
            if self._is_busy() and self._clock() < self._deadline:
                self._schedule()
                return
            self._waiting = False
        self._run()


# ---------------------------------------------------------------------------
# Multipart body in memory
# ---------------------------------------------------------------------------
# Limits of the in-memory parse: a text field larger than this is refused (a file part is not
# counted), and so is a body with more parts than werkzeug's own default allows for a request.
_MAX_TEXT_FIELD_BYTES = 1024 * 1024
_MAX_FORM_PARTS = 1000


def _memory_stream_factory(*_args, **_kwargs):
    from io import BytesIO

    return BytesIO()


def parse_form_in_memory(body, content_type):
    """Parse a multipart/form-data `body` (bytes) that is already in memory.

    Returns (form, files) shaped like Quart's `await request.form` / `await request.files`
    (werkzeug MultiDicts; every file is a FileStorage), but each file part lives in a BytesIO, so
    nothing is written to the system temp folder and read back. The caller bounds the size of
    `body` (routes/uploads.py only does this for bodies up to CHUNK_SIZE plus a little). A body
    that is not valid multipart gives two empty MultiDicts, as Quart's own parser does.
    """
    from io import BytesIO

    from werkzeug.formparser import FormDataParser
    from werkzeug.http import parse_options_header

    mimetype, options = parse_options_header(content_type or "")
    parser = FormDataParser(
        stream_factory=_memory_stream_factory,
        max_form_memory_size=_MAX_TEXT_FIELD_BYTES,
        max_form_parts=_MAX_FORM_PARTS,
    )
    _stream, form, files = parser.parse(BytesIO(body), mimetype, len(body), options)
    return form, files
