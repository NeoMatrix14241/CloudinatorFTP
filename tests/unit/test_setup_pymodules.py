"""
Regression tests for setup_pymodules.sh.

Bug (5.01): when a package was missing from requirements.txt and the file had no final newline,
the script glued the new package onto the last line ("pyOpenSSL<27pyflakes<5"). The script now
appends through append_req_line(). The function is cut out of the real script text and run in
bash, so these tests exercise the shipped code, not a copy. The script itself is never run
(it needs pip, network and, on Windows, elevation).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent.parent / "setup_pymodules.sh"
BASH = shutil.which("bash")


def _function_text():
    text = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"^append_req_line\(\) \{\n.*?^\}\n", text, re.S | re.M)
    assert m, (
        "append_req_line() not found in setup_pymodules.sh: this is the OLD script (before 5.01). "
        "Overwrite setup_pymodules.sh in the repository root with the one from the zip."
    )
    return m.group(0)


@pytest.fixture(scope="module")
def bash_append():
    if BASH is None:
        pytest.skip("bash not available")
    func = _function_text()

    def run(cwd, initial, line="pyflakes<5"):
        target = Path(cwd) / "requirements.txt"
        if initial is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(initial)
        # relative file name + cwd: works for Git Bash, Linux and a WSL bash.exe alike
        proc = subprocess.run(
            [
                BASH,
                "-c",
                func + '\nappend_req_line "$1" "$2"\n',
                "bash",
                "requirements.txt",
                line,
            ],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        return target.read_bytes()

    return run


@pytest.mark.parametrize(
    "initial,expected",
    [
        (None, b"pyflakes<5\n"),
        (b"", b"pyflakes<5\n"),
        (b"a<1\n", b"a<1\npyflakes<5\n"),
        (b"a<1", b"a<1\npyflakes<5\n"),  # the reported bug
        (b"a<1\nb<2", b"a<1\nb<2\npyflakes<5\n"),
        (b"a<1\r\nb<2\r\n", b"a<1\r\nb<2\r\npyflakes<5\r\n"),
        (b"a<1\r\nb<2", b"a<1\r\nb<2\r\npyflakes<5\r\n"),  # CRLF file stays CRLF
    ],
)
def test_append_req_line(bash_append, tmp_path, initial, expected):
    assert bash_append(tmp_path, initial) == expected


def test_reported_case_is_two_lines(bash_append, tmp_path):
    out = bash_append(tmp_path, b"pyOpenSSL<27")
    assert b"pyOpenSSL<27pyflakes" not in out
    assert out.splitlines() == [b"pyOpenSSL<27", b"pyflakes<5"]


def test_two_appends_stay_on_separate_lines(bash_append, tmp_path):
    bash_append(tmp_path, b"a<1")
    out = bash_append(
        tmp_path, (tmp_path / "requirements.txt").read_bytes(), line="b<2"
    )
    assert out.splitlines() == [b"a<1", b"pyflakes<5", b"b<2"]


def test_function_does_not_read_or_hold_a_cr_in_the_shell():
    # Under Git Bash on Windows grep, head and $(...) can hide CR characters (seen on the owner's
    # machine in 5.01 and 5.04), so the function must not detect CRLF through them or keep a CR
    # in a shell variable: it uses an od hex dump and printf escapes instead.
    func = _function_text()
    for bad in ("grep", "head", "$'\\r'", "$'\\r\\n'"):
        assert bad not in func, bad
    assert "od -An" in func


def test_script_appends_only_through_the_function():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'append_req_line "$REQ"' in text
    assert not re.search(
        r'echo\s+"\$\{pkg\}\$\{constraint\}"\s*>>', text
    ), "a plain echo >> append is back in setup_pymodules.sh"
