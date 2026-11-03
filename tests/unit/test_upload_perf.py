"""
Tests of helpers/upload_perf.py (5.41): the per-request stage timer, the event-loop lag probe,
the idle deferral that postpones the after-upload reconcile, and the in-memory multipart parse.

The module is loaded from its file under a private name (it imports nothing from the application),
and every clock, sleep and timer is a fake, so no test waits for real time.
"""

import asyncio
import importlib.util
import tempfile
import uuid
from pathlib import Path

import pytest

HELPER_PATH = (
    Path(__file__).resolve().parent.parent.parent / "helpers" / "upload_perf.py"
)


@pytest.fixture(scope="module")
def perf():
    spec = importlib.util.spec_from_file_location("upload_perf_under_test", HELPER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeClock:
    def __init__(self, start=100.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# ---------------------------------------------------------------------------- StageTimer
def test_a_disabled_timer_records_nothing(perf):
    timer = perf.StageTimer(False)
    timer.mark("a")
    timer.note("b", 1.0)
    assert timer.stages == [] and timer.notes == [] and timer.total() == 0


def test_stages_are_consecutive_and_add_up_to_the_total(perf):
    clock = FakeClock()
    timer = perf.StageTimer(True, clock=clock)
    clock.advance(0.5)
    timer.mark("receive")
    clock.advance(1.5)
    timer.mark("save")
    assert timer.stages == [("receive", 0.5), ("save", 1.5)]
    assert timer.total() == 2.0


def test_notes_are_shown_but_never_added_to_the_total(perf):
    clock = FakeClock()
    timer = perf.StageTimer(True, clock=clock)
    clock.advance(2.0)
    timer.mark("thread")
    timer.note("read", 0.7)
    timer.note("save", 1.2)
    assert timer.total() == 2.0
    assert timer.notes == [("read", 0.7), ("save", 1.2)]


# ---------------------------------------------------------------------------- UploadTimingLog
def _finished_timer(perf, receive=1.0, thread=2.0):
    clock = FakeClock()
    timer = perf.StageTimer(True, clock=clock)
    clock.advance(receive)
    timer.mark("receive+parse")
    clock.advance(thread)
    timer.mark("thread")
    timer.note("save", 1.5)
    return timer


def test_one_line_per_chunk_names_every_stage_and_the_rate(perf):
    lines = []
    log = perf.UploadTimingLog(log=lines.append, summary_every=99)
    log.report(_finished_timer(perf), 3 * 1024 * 1024, "3/190")
    assert len(lines) == 1
    text = lines[0]
    assert "3/190" in text
    assert "receive+parse 1.000s" in text and "thread 2.000s" in text
    assert "save 1.500s" in text
    assert "total 3.000s" in text and "3.0 MB" in text and "1.0 MB/s" in text


def test_a_disabled_timer_logs_nothing(perf):
    lines = []
    perf.UploadTimingLog(log=lines.append).report(perf.StageTimer(False), 10, "x")
    assert lines == []


def test_an_average_is_logged_every_n_chunks_and_then_starts_over(perf):
    lines = []
    log = perf.UploadTimingLog(log=lines.append, summary_every=2)
    for _ in range(2):
        log.report(_finished_timer(perf, 1.0, 3.0), 4 * 1024 * 1024, "c")
    assert len(lines) == 3  # two chunk lines and one average
    assert "average of the last 2 chunks" in lines[2]
    assert "receive+parse 1.000s" in lines[2] and "thread 3.000s" in lines[2]
    log.report(_finished_timer(perf), 1, "c")
    assert len(lines) == 4  # the counter restarted: no second average yet


# ---------------------------------------------------------------------------- lag probe
def test_lag_summary_is_none_without_samples_and_has_percentiles_otherwise(perf):
    stats = perf.LagStats()
    assert stats.summary() is None
    for value in (0.0, 0.1, 0.2, 0.3, 1.0):
        stats.add(value)
    summary = stats.summary()
    assert summary["count"] == 5
    assert summary["p50"] == 0.2
    assert summary["max"] == 1.0
    assert summary["p95"] == 1.0
    stats.reset()
    assert stats.summary() is None


def _run_probe(perf, extra_lags, **kwargs):
    """Run watch_loop_lag on a fake clock: each sleep(s) advances the clock by s + the next lag."""
    clock = FakeClock()
    lags = list(extra_lags)
    lines = []

    async def fake_sleep(seconds):
        clock.advance(seconds + lags.pop(0))

    asyncio.run(
        perf.watch_loop_lag(
            clock=clock,
            sleep=fake_sleep,
            log=lines.append,
            rounds=len(extra_lags),
            **kwargs,
        )
    )
    return lines


def test_a_stall_over_the_threshold_is_reported_at_once(perf):
    lines = _run_probe(perf, [0.0, 2.0, 0.0], interval=0.1, warn_over=0.5)
    warnings = [line for line in lines if "blocked" in line]
    assert len(warnings) == 1 and "2.00s" in warnings[0]


def test_no_warning_when_the_loop_is_never_late(perf):
    assert _run_probe(perf, [0.0] * 5, interval=0.1, warn_over=0.5) == []


def test_a_summary_line_is_logged_after_each_reporting_window(perf):
    # interval 1 s + 0.2 s lag per round: a 3 s window closes every 3 rounds
    lines = _run_probe(perf, [0.2] * 6, interval=1.0, report_every=3.0, warn_over=99.0)
    summaries = [line for line in lines if "event-loop lag" in line]
    assert len(summaries) == 2
    assert "median 200 ms" in summaries[0] and "max 200 ms" in summaries[0]


class FakeApp:
    def __init__(self, fail=False):
        self.tasks = []
        self.fail = fail

    def add_background_task(self, func, *args, **kwargs):
        if self.fail:
            raise RuntimeError("no loop")
        self.tasks.append((func, kwargs))


def test_the_probe_is_started_once_by_the_first_call(perf):
    app, lines = FakeApp(), []
    starter = perf.LagProbeStarter(log=lines.append, interval=0.05)
    assert app.tasks == []  # constructing it starts nothing
    assert starter.start_once(app) is True
    assert starter.start_once(app) is False
    assert starter.start_once(app) is False
    assert len(app.tasks) == 1
    assert app.tasks[0][0] is perf.watch_loop_lag
    assert app.tasks[0][1]["interval"] == 0.05
    assert sum("probe started" in line for line in lines) == 1


def test_a_probe_that_cannot_start_is_logged_never_raised_and_not_retried(perf):
    app, lines = FakeApp(fail=True), []
    starter = perf.LagProbeStarter(log=lines.append)
    assert starter.start_once(app) is False
    assert starter.start_once(app) is False
    assert (
        sum("could not be started" in line and "no loop" in line for line in lines) == 1
    )


def test_the_helper_registers_no_lifecycle_hook(perf):
    """tests/smoke.py check 5: hooks belong in middleware.py, never in a helper."""
    source = HELPER_PATH.read_text(encoding="utf-8")
    for hook in ("before_serving", "after_serving", "before_request", "after_request"):
        assert f"@app.{hook}" not in source and f".{hook}(" not in source, hook


# ---------------------------------------------------------------------------- IdleDeferral
class FakeTimer:
    """Stands in for threading.Timer: records itself and fires only when the test says so."""

    created = []

    def __init__(self, interval, func):
        self.interval = interval
        self.func = func
        self.daemon = False
        self.started = False
        FakeTimer.created.append(self)

    def start(self):
        self.started = True


@pytest.fixture
def timers():
    FakeTimer.created = []
    return FakeTimer


def _deferral(perf, busy, calls, clock=None, **kwargs):
    return perf.IdleDeferral(
        action=lambda: calls.append("ran"),
        busy=busy,
        make_timer=FakeTimer,
        clock=clock or FakeClock(),
        log=calls.append,
        **kwargs,
    )


def test_the_action_runs_at_once_when_nothing_is_busy(perf, timers):
    calls = []
    deferral = _deferral(perf, lambda: False, calls)
    assert deferral.request() == "ran"
    assert calls == ["ran"] and timers.created == []


def test_a_busy_request_is_postponed_and_runs_after_the_busy_state_ends(perf, timers):
    calls, state = [], {"busy": True}
    deferral = _deferral(perf, lambda: state["busy"], calls, interval=5.0)
    assert deferral.request() == "deferred"
    assert calls == []
    timer = timers.created[0]
    assert timer.started and timer.daemon and timer.interval == 5.0
    timer.func()  # still busy: another re-check, still nothing run
    assert calls == [] and len(timers.created) == 2
    state["busy"] = False
    timers.created[1].func()
    assert calls == ["ran"]
    assert deferral.request() == "ran"  # and it is usable again afterwards


def test_requests_while_a_re_check_is_pending_are_merged(perf, timers):
    calls = []
    deferral = _deferral(perf, lambda: True, calls)
    assert deferral.request() == "deferred"
    assert deferral.request() == "merged"
    assert deferral.request() == "merged"
    assert len(timers.created) == 1


def test_the_postponement_has_a_hard_cap(perf, timers):
    calls, clock = [], FakeClock()
    deferral = _deferral(perf, lambda: True, calls, clock=clock, max_wait=600.0)
    deferral.request()
    clock.advance(599)
    timers.created[-1].func()
    assert calls == []  # still inside the cap, still busy
    clock.advance(2)
    timers.created[-1].func()
    assert calls == ["ran"]  # past the cap: it runs although busy() is still true


def test_a_failing_busy_check_means_not_busy(perf, timers):
    calls = []

    def broken():
        raise RuntimeError("tracker gone")

    assert _deferral(perf, broken, calls).request() == "ran"
    assert calls == ["ran"]


def test_a_failing_action_is_logged_and_does_not_raise(perf, timers):
    messages = []

    def action():
        raise OSError("disk")

    deferral = perf.IdleDeferral(
        action=action,
        busy=lambda: False,
        make_timer=FakeTimer,
        log=messages.append,
    )
    assert deferral.request() == "ran"
    assert any("deferred action failed" in m and "disk" in m for m in messages)


# ---------------------------------------------------------------------------- multipart in memory
def _body(fields, files):
    boundary = "qa-" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, (filename, content) in files.items():
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        )
        parts.append(head.encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def test_fields_and_the_file_come_back_like_quarts_form_and_files(perf):
    payload = bytes(range(256)) * 40
    body, ctype = _body(
        {"file_id": "fid_1_5_abc", "chunk_num": "3", "total_chunks": "9"},
        {"chunk": ("blob", payload)},
    )
    form, files = perf.parse_form_in_memory(body, ctype)
    assert form.get("file_id") == "fid_1_5_abc"
    assert form.get("chunk_num") == "3" and form.get("total_chunks") == "9"
    assert form.get("filename", "") == ""  # .get with a default, as /upload calls it
    chunk = files.get("chunk")
    assert chunk is not None and chunk.filename == "blob"
    assert chunk.read() == payload


def test_binary_data_that_looks_like_a_boundary_is_not_cut(perf):
    payload = b"\r\n--not-the-boundary\r\n" * 500 + b"\r\n" + b"-" * 100
    body, ctype = _body({"a": "1"}, {"chunk": ("blob", payload)})
    _form, files = perf.parse_form_in_memory(body, ctype)
    assert files["chunk"].read() == payload


def test_a_multi_megabyte_chunk_round_trips_unchanged(perf):
    payload = (bytes(range(256)) * 4096) * 3  # 3 MiB
    body, ctype = _body({"chunk_num": "0"}, {"chunk": ("blob", payload)})
    _form, files = perf.parse_form_in_memory(body, ctype)
    assert files["chunk"].read() == payload


def test_no_temp_file_is_created(perf, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a temp file was created")

    for name in (
        "SpooledTemporaryFile",
        "TemporaryFile",
        "NamedTemporaryFile",
        "mkstemp",
    ):
        monkeypatch.setattr(tempfile, name, forbidden)
    body, ctype = _body({"a": "1"}, {"chunk": ("blob", b"x" * (2 * 1024 * 1024))})
    _form, files = perf.parse_form_in_memory(body, ctype)
    assert len(files["chunk"].read()) == 2 * 1024 * 1024


@pytest.mark.parametrize(
    "body, ctype",
    [
        (b"not multipart at all", "multipart/form-data; boundary=zzz"),
        (b"", ""),
    ],
)
def test_input_that_is_not_valid_multipart_gives_empty_results(perf, body, ctype):
    form, files = perf.parse_form_in_memory(body, ctype)
    assert not form and not files


def test_a_urlencoded_body_still_gives_its_fields_and_no_files(perf):
    # the same answer Quart's own request.form would give; /upload never relies on it
    form, files = perf.parse_form_in_memory(
        b"a=1&b=2", "application/x-www-form-urlencoded"
    )
    assert form.get("a") == "1" and form.get("b") == "2" and not files


def test_a_huge_text_field_is_refused(perf):
    from werkzeug.exceptions import RequestEntityTooLarge

    body, ctype = _body({"filename": "x" * (2 * 1024 * 1024)}, {})
    with pytest.raises(RequestEntityTooLarge):
        perf.parse_form_in_memory(body, ctype)


def test_a_body_with_too_many_parts_is_refused(perf):
    from werkzeug.exceptions import RequestEntityTooLarge

    body, ctype = _body({f"f{i}": "x" for i in range(1001)}, {})
    with pytest.raises(RequestEntityTooLarge):
        perf.parse_form_in_memory(body, ctype)


# ---------------------------------------------------------------------------- parse_timing_lines
REAL_LINE = (
    "⏱️ upload chunk 1/1: role 0.002s | receive+parse (RAM) 0.004s | read+save 0.006s "
    "(in the worker thread: read 0.000s, save 0.004s) | total 0.012s, 0.1 MB, 8.2 MB/s"
)  # a line of the owner's own server log (5.41)


def test_a_real_log_line_is_parsed(perf):
    stats = perf.parse_timing_lines(REAL_LINE)
    assert stats["chunks"] == 1 and stats["ram"] is True
    assert stats["receive_parse"] == pytest.approx(0.004)
    assert stats["read_save"] == pytest.approx(0.006)
    assert stats["read"] == pytest.approx(0.0) and stats["save"] == pytest.approx(0.004)
    assert stats["total"] == pytest.approx(0.012)
    assert stats["megabytes"] == pytest.approx(0.1)


def test_lines_are_averaged_and_noise_is_ignored(perf):
    other = REAL_LINE.replace("(RAM) 0.004s", "0.008s").replace(
        "save 0.004s", "save 0.010s"
    )
    text = "\n".join(
        [
            "📊 Tracking upload: abc",
            REAL_LINE,
            "⏱️ upload average of the last 2 chunks: role 0.002s | receive+parse 0.1s",
            other,
            "[2026-11-01] INFO POST /upload 200",
        ]
    )
    stats = perf.parse_timing_lines(text)
    assert stats["chunks"] == 2  # the average line is not a chunk line
    assert stats["receive_parse"] == pytest.approx(0.006)
    assert stats["save"] == pytest.approx(0.007)
    assert stats["ram"] is True  # at least one chunk was parsed in RAM


def test_without_timing_lines_there_is_nothing_to_show(perf):
    assert perf.parse_timing_lines("") is None
    assert (
        perf.parse_timing_lines("INFO nothing here\nupload chunk without numbers")
        is None
    )


def test_a_line_the_logger_produced_is_read_back(perf):
    """The stage names are the ones routes/uploads.py gives its StageTimer."""
    lines = []
    log = perf.UploadTimingLog(log=lines.append, summary_every=99)
    clock = FakeClock()
    timer = perf.StageTimer(True, clock=clock)
    clock.advance(0.01)
    timer.mark("role")
    clock.advance(1.5)
    timer.mark("receive+parse")
    clock.advance(2.5)
    timer.mark("read+save")
    log.report(
        timer, 10 * 1024 * 1024, "chunk 4/9"
    )  # the label routes/uploads.py passes
    stats = perf.parse_timing_lines("\n".join(lines))
    assert stats["chunks"] == 1 and stats["ram"] is False
    assert stats["receive_parse"] == pytest.approx(1.5)
    assert stats["read_save"] == pytest.approx(2.5)
    assert stats["megabytes"] == pytest.approx(10.0)
