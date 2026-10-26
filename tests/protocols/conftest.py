"""
Fixtures for the protocol tests (FTP/FTPS now; SFTP, WebDAV, SMB later): a SCRATCH COPY of the
project (own storage, database and config, nothing of the real data) in which ONE protocol server
is started as a separate process on an ephemeral port. The tests then talk to it with the
standard library or the client library of the protocol, the way a real client does.

- `protocol_lab`   (session): the scratch copy with the synthetic accounts qa_writer / qa_reader.
- `launch`         (session): factory that writes the config overrides, starts a small launcher
                   script in the scratch copy, waits for its READY line and stops it at the end.
Isolation rules are the same as for tests/application: the real project is only COPIED, every
path is checked to be inside the copy, and ports come from the OS (nothing is assumed free).
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

LAUNCHER_PRELUDE = (
    "import os, sys, time\n"
    "sys.path.insert(0, os.getcwd())\n"
    "from paths import ensure_dirs\n"
    "ensure_dirs()\n"
)

SEED_USERS = (
    "import json\n"
    "for name, (pw, role) in json.loads(sys.argv[1]).items():\n"
    "    assert db.add_user(name, pw, role), name\n"
)


class ProtocolProcess:
    """A launcher process in the scratch copy; its output is drained so a pipe never fills."""

    def __init__(self, root, code, args, ready, timeout):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env.update(
            {
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "CLOUDINATOR_FTP_ROOT": str(Path(root) / "data" / "storage"),
            }
        )
        self.lines = []
        self._ready = threading.Event()
        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-c", LAUNCHER_PRELUDE + code, *map(str, args)],
            cwd=str(root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        def pump():
            for line in self.proc.stdout:
                self.lines.append(line.rstrip())
                if ready in line:
                    self._ready.set()

        threading.Thread(target=pump, daemon=True).start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._ready.is_set():
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)
        if not self._ready.is_set():
            self.stop()
            raise RuntimeError(
                "the protocol server did not become ready:\n"
                + "\n".join(self.lines[-25:])
            )

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)


@pytest.fixture(scope="session")
def protocol_lab(scratch_tools, tmp_path_factory):
    root = tmp_path_factory.mktemp("protocol_lab") / "app"
    scratch_tools.build(root, port=scratch_tools.free_port())
    assert scratch_tools.paths_outside(root) == []
    users = {name: list(v) for name, v in scratch_tools.test_users.items()}
    scratch_tools.run_in_scratch(root, SEED_USERS, json.dumps(users))
    return root


@pytest.fixture(scope="session")
def launch(protocol_lab):
    started = []

    def _launch(code, *args, config=None, ready="READY", timeout=60):
        if config:
            path = Path(protocol_lab) / "server_config.json"
            data = json.loads(path.read_text("utf-8"))
            data.update(config)
            path.write_text(json.dumps(data, indent=2), "utf-8")
        process = ProtocolProcess(protocol_lab, code, args, ready, timeout)
        started.append(process)
        return process

    yield _launch
    for process in started:
        process.stop()
