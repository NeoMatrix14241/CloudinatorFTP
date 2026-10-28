"""get_client_ip() in core.py: the proxy headers are trusted only from a loopback peer.

The function is read out of core.py with `ast` and run against a fake request, so no app,
no server and no scratch copy is needed (core.py cannot be imported in a bare test process).
Why it matters: the login lockout is keyed by this address, so a client that reaches the port
directly must not be able to pick its own address with a forged CF-Connecting-IP header
(CLAUDE.md 5.16).
"""

import ast
import ipaddress
from pathlib import Path
from types import SimpleNamespace

import pytest

CORE = Path(__file__).resolve().parents[2] / "core.py"
WANTED = {"_TRUSTED_PROXY_NETWORKS", "_is_trusted_proxy", "get_client_ip"}


def _load():
    source = CORE.read_text(encoding="utf-8")
    parts = []
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        else:
            continue
        if name in WANTED:
            parts.append(ast.get_source_segment(source, node))
    assert len(parts) == len(WANTED), "core.py no longer defines the trust helpers"
    request = SimpleNamespace(remote_addr="", headers={})
    namespace = {"ipaddress": ipaddress, "request": request}
    exec("\n\n".join(parts), namespace)
    return namespace, request


def _client_ip(peer, headers=None):
    namespace, request = _load()
    request.remote_addr = peer
    request.headers = _Headers(headers or {})
    return namespace["get_client_ip"]()


class _Headers(dict):
    def get(self, key, default=""):
        return super().get(key, default)


@pytest.mark.parametrize("peer", ["127.0.0.1", "127.8.9.10", "::1", "::ffff:127.0.0.1"])
def test_cloudflare_header_is_trusted_from_a_loopback_peer(peer):
    assert _client_ip(peer, {"CF-Connecting-IP": "203.0.113.5"}) == "203.0.113.5"


def test_forwarded_for_is_the_fallback_behind_a_loopback_proxy():
    headers = {"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}
    assert _client_ip("127.0.0.1", headers) == "198.51.100.7"


def test_loopback_peer_without_headers_is_itself():
    assert _client_ip("127.0.0.1") == "127.0.0.1"


@pytest.mark.parametrize(
    "peer", ["192.168.1.50", "10.0.0.7", "203.0.113.9", "fe80::1%eth0", "2001:db8::1"]
)
def test_forged_headers_from_a_direct_client_are_ignored(peer):
    headers = {"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"}
    assert _client_ip(peer, headers) == peer


@pytest.mark.parametrize("peer", [None, "", "not-an-ip"])
def test_unknown_or_broken_peer_is_never_trusted(peer):
    result = _client_ip(peer, {"CF-Connecting-IP": "1.2.3.4"})
    assert result == (peer or "")
