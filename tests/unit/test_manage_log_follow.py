"""
5.44.1: `./manage.sh logs server -f` follows the server's log across midnight.

The server writes logs/<type>_server_YYYY-MM-DD.log and starts a NEW file after midnight. The
follower (a Python heredoc inside `_follow_log` of manage.sh) used to stay on the file it was
started on, so after midnight it kept watching yesterday's file and showed nothing. It now looks
for the same server's file of today and moves over to it when it appears, after showing what the
old file still received.

The REAL follower source is cut out of manage.sh and run as a subprocess; only its one-line
`_today()` is replaced by a read of a file, so the test can move the clock past midnight.
"""

import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

MANAGE = Path(__file__).resolve().parent.parent.parent / "manage.sh"
TODAY_LINE = "    return datetime.date.today().isoformat()"


def _follower_source():
    text = MANAGE.read_text(encoding="utf-8")
    match = re.search(r"\"\$PYTHON\" - \"\$log\" <<'PYEOF'\n(.*?)\nPYEOF\n", text, re.S)
    assert match, "the follower heredoc is gone from manage.sh"
    source = match.group(1)
    assert TODAY_LINE in source, "the follower's _today() changed shape"
    return source.replace(TODAY_LINE, "    return open('today.txt').read().strip()")


class Follower:
    def __init__(self, tmp_path, log_name, today):
        self.dir = tmp_path
        (tmp_path / "today.txt").write_text(today)
        self.script = tmp_path / "follower.py"
        self.script.write_text(_follower_source(), encoding="utf-8")
        self.log = tmp_path / log_name
        self.lines = []
        self._lock = threading.Lock()

    def start(self):
        self.proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-u", str(self.script), str(self.log)],
            cwd=str(self.dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        threading.Thread(target=self._pump, daemon=True).start()
        return self

    def _pump(self):
        for line in self.proc.stdout:
            with self._lock:
                self.lines.append(line.rstrip("\n"))

    def output(self):
        with self._lock:
            return list(self.lines)

    def wait_for(self, text, seconds=8.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if any(text in line for line in self.output()):
                return True
            time.sleep(0.05)
        return False

    def stop(self):
        self.proc.kill()
        self.proc.wait(5)


@pytest.fixture
def follower_factory(tmp_path):
    made = []

    def make(log_name, today):
        follower = Follower(tmp_path, log_name, today)
        made.append(follower)
        return follower

    yield make
    for follower in made:
        if getattr(follower, "proc", None) and follower.proc.poll() is None:
            follower.stop()


def _append(path, text):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def test_the_follower_moves_to_the_next_days_file_after_midnight(
    follower_factory, tmp_path
):
    old = tmp_path / "server_server_2026-11-08.log"
    old.write_text("old line 1\nold line 2\n", encoding="utf-8")
    follower = follower_factory(old.name, "2026-11-08").start()
    assert follower.wait_for("old line 2")  # the history is shown

    _append(old, "line before midnight\n")
    assert follower.wait_for("line before midnight")

    # midnight passes, but the server has not written its first line of the new day yet
    (tmp_path / "today.txt").write_text("2026-11-09")
    time.sleep(1.6)
    assert not any("new day" in line for line in follower.output())

    # the last lines the old file receives, then the new file appears
    _append(old, "late line in the old file\n")
    new = tmp_path / "server_server_2026-11-09.log"
    new.write_text("first line of the new day\n", encoding="utf-8")
    assert follower.wait_for("continuing in server_server_2026-11-09.log")
    assert follower.wait_for("first line of the new day")

    _append(new, "second line of the new day\n")
    assert follower.wait_for("second line of the new day")

    out = follower.output()
    assert out.index("late line in the old file") < next(
        i for i, line in enumerate(out) if "new day: continuing" in line
    )  # the old file is drained BEFORE the switch
    _append(old, "stray line in yesterday's file\n")
    time.sleep(0.6)
    assert not any("stray line" in line for line in follower.output())


def test_a_file_name_without_a_date_is_followed_as_it_is(follower_factory, tmp_path):
    log = tmp_path / "custom.log"
    log.write_text("one\n", encoding="utf-8")
    follower = follower_factory(log.name, "2026-11-08").start()
    assert follower.wait_for("one")
    (tmp_path / "today.txt").write_text("2026-11-09")
    (tmp_path / "custom_2026-11-09.log").write_text("other file\n", encoding="utf-8")
    _append(log, "two\n")
    assert follower.wait_for("two")
    time.sleep(1.5)
    assert not any("other file" in line for line in follower.output())


def test_the_follower_stays_on_a_file_while_the_day_does_not_change(
    follower_factory, tmp_path
):
    log = tmp_path / "dev_server_2026-11-08.log"
    log.write_text("start\n", encoding="utf-8")
    follower = follower_factory(log.name, "2026-11-08").start()
    assert follower.wait_for("start")
    time.sleep(1.5)
    _append(log, "still the same day\n")
    assert follower.wait_for("still the same day")
    assert not any("new day" in line for line in follower.output())


def test_the_logs_command_falls_back_to_the_newest_file_before_the_first_line_of_the_day():
    text = MANAGE.read_text(encoding="utf-8")
    start = text.index("cmd_logs() {")
    body = text[start : text.index("\n}\n", start)]
    assert "newest=$(ls -t" in body and '_server_"*.log' in body
    # ... and still says so when this server has no log file at all
    assert "No log file found" in body
