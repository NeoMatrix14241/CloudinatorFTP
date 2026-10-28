"""
webdav_server._listener_binds(): which Hypercorn lists the WebDAV ports go into (CLAUDE.md 5.29).

Hypercorn only honours `insecure_bind` when TLS is configured (certfile + keyfile); without TLS
it serves `bind` and silently ignores `insecure_bind`, so the plain-HTTP fallback listener never
opened before 5.29. The function is a pure helper: it is cut out of webdav_server.py with `ast`
(the module itself starts Hypercorn patches and reads the network on import).
"""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "webdav_server.py"


@pytest.fixture(scope="module")
def binds():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_listener_binds"
    )
    namespace: dict = {}
    exec(compile(ast.Module([node], []), str(SOURCE), "exec"), namespace)
    return namespace["_listener_binds"]


def test_https_only_uses_bind(binds):
    assert binds(None, 8443) == (["0.0.0.0:8443"], [])


def test_https_with_a_plain_port_keeps_the_plain_one_in_insecure_bind(binds):
    assert binds(8080, 8443) == (["0.0.0.0:8443"], ["0.0.0.0:8080"])


def test_plain_only_goes_into_bind_because_insecure_bind_needs_tls(binds):
    bind, insecure = binds(8080, None)
    assert bind == ["0.0.0.0:8080"]
    assert insecure == []  # Hypercorn would ignore it without TLS


def test_no_ports_means_no_listeners(binds):
    assert binds(None, None) == ([], [])


def test_the_function_is_used_by_start_hypercorn():
    text = SOURCE.read_text(encoding="utf-8")
    assert (
        "cfg.bind, cfg.insecure_bind = _listener_binds(http_port, https_port)" in text
    )
    assert "cfg.insecure_bind = [f" not in text  # the old direct assignment is gone
