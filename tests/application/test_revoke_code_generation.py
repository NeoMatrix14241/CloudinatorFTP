"""
core._issue_revoke_all_code(): the "revoke all shares" confirmation code comes from the
`secrets` module, not `random` (CLAUDE.md 5.25), and keeps its shape and one-code-per-session rule.
core.py cannot be imported (it starts threads), so the function is cut out with `ast`.
"""

import ast
import threading
import time
import uuid
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[2] / "core.py"


def _function():
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    nodes = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_issue_revoke_all_code"
    ]
    assert nodes, "_issue_revoke_all_code no longer exists in core.py"
    return nodes[0]


def test_the_code_is_not_made_with_the_random_module():
    names = {n.id for n in ast.walk(_function()) if isinstance(n, ast.Name)}
    imports = [n for n in ast.walk(_function()) if isinstance(n, ast.Import)]
    assert "random" not in names and not imports
    assert "_secrets" in names


@pytest.fixture()
def issue():
    import secrets

    store = {}
    ns = {
        "uuid": uuid,
        "time": time,
        "_secrets": secrets,
        "_revoke_all_codes": store,
        "_revoke_all_codes_lock": threading.Lock(),
    }
    module = ast.Module(body=[_function()], type_ignores=[])
    exec(compile(module, str(CORE), "exec"), ns)
    return ns["_issue_revoke_all_code"], store


def test_a_code_is_ten_digits_and_unique_nonces_are_issued(issue):
    fn, _ = issue
    codes, nonces = set(), set()
    for n in range(200):
        nonce, code = fn(f"session-{n}")
        assert len(code) == 10 and code.isdigit()
        codes.add(code)
        nonces.add(nonce)
    assert (
        len(nonces) == 200 and len(codes) > 190
    )  # 10^10 values: collisions are freak events


def test_a_new_code_invalidates_the_previous_one_of_the_same_session(issue):
    fn, store = issue
    first_nonce, _ = fn("same-session")
    other_nonce, _ = fn("another-session")
    second_nonce, _ = fn("same-session")
    assert first_nonce not in store
    assert second_nonce in store and other_nonce in store
