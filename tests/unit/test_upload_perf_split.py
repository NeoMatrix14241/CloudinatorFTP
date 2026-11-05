"""
Tests of the 5.43 addition to helpers/upload_perf.py: a stage can say how it divides.

  StageTimer.detail(name, seconds)   shown in the log line, never added to the total
  parse_timing_lines()               gives `body` and `parse` averages when a line has them, and
                                     exactly the keys it always had when none does

With UPLOAD_CHUNKS_IN_MEMORY the stage "receive+parse (RAM)" is split into the time the body took
to arrive and the time the parse took (routes/uploads.py), because the first 5.42 measurements
showed that this stage is where an upload's time goes but not which half of it.

The helper is loaded by path (it imports nothing from the application).
"""

import importlib.util
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parent.parent.parent / "helpers" / "upload_perf.py"
OLD_KEYS = {
    "chunks",
    "ram",
    "receive_parse",
    "read_save",
    "read",
    "save",
    "total",
    "megabytes",
}


@pytest.fixture(scope="module")
def perf():
    spec = importlib.util.spec_from_file_location(
        "upload_perf_split_under_test", HELPER
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clock(values):
    ticks = iter(values)
    return lambda: next(ticks)


def _timer(perf, enabled=True, split=True):
    """A timer with a fake clock: role 0.001 s, receive+parse (RAM) 0.6 s, read+save 0.02 s."""
    timer = perf.StageTimer(enabled, clock=_clock([0.0, 0.001, 0.601, 0.621]))
    timer.mark("role")
    timer.mark("receive+parse (RAM)")
    timer.mark("read+save")
    timer.note("read", 0.005)
    timer.note("save", 0.01)
    if split:
        timer.detail("body arrived", 0.5)
        timer.detail("parse", 0.1)
    return timer


def _line(perf, **kwargs):
    lines = []
    perf.UploadTimingLog(log=lines.append).report(
        _timer(perf, **kwargs), 10 * 1024 * 1024, "chunk 1/3"
    )
    return lines[0]


# ---------------------------------------------------------------------------- StageTimer
def test_a_detail_is_recorded_but_never_added_to_the_total(perf):
    timer = _timer(perf)
    assert timer.details == [("body arrived", 0.5), ("parse", 0.1)]
    assert timer.total() == pytest.approx(0.621)


def test_a_disabled_timer_records_no_detail(perf):
    timer = perf.StageTimer(False)
    timer.detail("parse", 1.0)
    assert timer.details == []


# ---------------------------------------------------------------------------- the log line
def test_the_line_shows_the_split_between_the_stages_and_the_total(perf):
    line = _line(perf)
    assert "(body arrived 0.500s, parse 0.100s)" in line
    assert line.index("read+save") < line.index("body arrived") < line.index("| total")


def test_a_line_without_a_split_is_exactly_what_it_was_before_5_43(perf):
    assert _line(perf, split=False) == (
        "⏱️ upload chunk 1/3: role 0.001s | receive+parse (RAM) 0.600s | read+save 0.020s"
        " (in the worker thread: read 0.005s, save 0.010s) | total 0.621s, 10.0 MB, 16.1 MB/s"
    )


# ---------------------------------------------------------------------------- parse_timing_lines
def test_the_reader_finds_the_split_in_a_line_the_logger_wrote(perf):
    stats = perf.parse_timing_lines(_line(perf))
    assert stats["body"] == pytest.approx(0.5) and stats["parse"] == pytest.approx(0.1)
    assert stats["receive_parse"] == pytest.approx(0.6) and stats["ram"] is True
    assert stats["read"] == pytest.approx(0.005) and stats["save"] == pytest.approx(
        0.01
    )


def test_without_any_split_the_result_has_exactly_the_old_keys(perf):
    stats = perf.parse_timing_lines(_line(perf, split=False))
    assert set(stats) == OLD_KEYS


def test_the_split_is_averaged_over_the_lines_that_have_one(perf):
    first = _line(perf)
    second = first.replace(
        "body arrived 0.500s, parse 0.100s", "body arrived 0.300s, parse 0.300s"
    )
    plain = _line(perf, split=False)  # a chunk that was not parsed in RAM has no split
    stats = perf.parse_timing_lines("\n".join([first, second, plain]))
    assert stats["chunks"] == 3
    assert stats["body"] == pytest.approx(0.4) and stats["parse"] == pytest.approx(0.2)


def test_text_without_a_timing_line_still_gives_none(perf):
    assert (
        perf.parse_timing_lines("nothing to see\nupload chunk without numbers") is None
    )
