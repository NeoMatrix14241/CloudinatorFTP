"""
dev_server.py must stay the DEVELOPMENT server (5.42).

Every scratch server of the test suite is `python dev_server.py` (plain HTTP/1.1, no TLS, no HTTP/3,
`app.run`, stopped by manage.sh's stop file). When a copy of prod_server.py (TLS is mandatory there,
Tailscale / self-signed certificate, HTTP/3 over QUIC) ended up in dev_server.py, no scratch server
answered on its plain-HTTP port, every fixture failed and `qa quick` printed hundreds of `E` lines
and a 20 s wait for a process that never exited. This test names the real problem in one line.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
DEV = ROOT / "dev_server.py"
PROD = ROOT / "prod_server.py"

pytestmark = pytest.mark.skipif(not DEV.is_file(), reason="dev_server.py not found")


def _text(path):
    return path.read_text(encoding="utf-8")


def test_dev_server_is_the_quart_development_server():
    text = _text(DEV)
    assert "app.run(" in text, "the dev server starts Quart's own server with app.run()"
    assert (
        'os.environ.get("CLOUDINATOR_BG")' in text
    ), "manage.sh / the test suite pass CLOUDINATOR_BG"
    assert "Development Server for CloudinatorFTP" in text
    assert "Production Server for CloudinatorFTP" not in text, (
        "dev_server.py contains the PRODUCTION server: restore it with "
        "`git checkout HEAD -- dev_server.py` (or from the last good commit)"
    )


def test_dev_server_does_not_configure_hypercorn_tls_or_quic_itself():
    """Assignments in CODE (its comments may mention these names while explaining why)."""
    text = _text(DEV)
    for pattern in (
        r"^\s*hyper_cfg\s*=",
        r"\bquic_bind\s*=",
        r"\.certfile\s*=",
        r"\.alpn_protocols\s*=",
    ):
        assert not re.search(
            pattern, text, re.M
        ), f"{pattern} belongs to prod_server.py"


def test_dev_and_prod_server_are_different_files():
    if not PROD.is_file():
        pytest.skip("prod_server.py not found")
    assert _text(DEV) != _text(PROD)
    # not merely the same program with one line changed (the failure that was seen)
    similar = sum(
        1 for a, b in zip(_text(DEV).splitlines(), _text(PROD).splitlines()) if a == b
    )
    assert similar < 0.5 * max(1, len(_text(PROD).splitlines()))


def test_dev_server_stops_through_the_documented_stop_file():
    text = _text(DEV)
    assert re.search(r"\.manage_pids.{0,20}dev\.stop|dev\.stop", text)
