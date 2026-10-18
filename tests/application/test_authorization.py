"""
Who may reach what, tested against the REAL application started from a scratch copy.

1. Anonymous sweep: every route declared in routes/*.py and middleware.py must refuse an
   anonymous caller, except an explicit, independently maintained list of public endpoints.
   A new public route fails this test until it is added to PUBLIC_ENDPOINTS on purpose.
2. Role gates: a readonly account is refused on every mutating route; a readwrite account passes.
3. The role is read from the database on every request, not cached in the session.

The source files are only PARSED here (ast); the application is never imported.
"""

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.application

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RW, RO = "qa_writer", "qa_reader"
JSON_HEADERS = {"Accept": "application/json"}

# Endpoints that are meant to work without an account. Keep this list independent of the
# application code: it is the reviewed statement of what is public.
PUBLIC_ENDPOINTS = {
    "login",
    "get_csrf_token",
    "robots_txt",
    "security_txt",
    "sitemap_xml",
    "shared_download",
    "shared_file_download",
    "shared_verify_passkey",
    "shared_request_access",
    "shared_request_status",
    "shared_browse",
    "shared_download_item",
    "shared_zip_selected",
}


UNPARSABLE = []  # route decorators this parser could not read (reported by a test)


def _declared_routes():
    """(endpoint, rule, methods) for every route decorator in routes/*.py and middleware.py."""
    found = []
    sources = sorted((REPO_ROOT / "routes").glob("*.py")) + [
        REPO_ROOT / "middleware.py"
    ]
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (
                    isinstance(dec, ast.Call) and ast.unparse(dec.func) == "app.route"
                ):
                    continue
                where = f"{source.name}:{dec.lineno} ({node.name})"
                if not (dec.args and isinstance(dec.args[0], ast.Constant)):
                    UNPARSABLE.append(f"{where}: rule is not a string literal")
                    continue
                methods = ["GET"]
                for kw in dec.keywords:
                    if kw.arg != "methods":
                        continue
                    if isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                        methods = [e.value for e in kw.value.elts]
                    else:
                        UNPARSABLE.append(f"{where}: methods is not a literal list")
                found.append(
                    (
                        node.name,
                        dec.args[0].value,
                        [m for m in methods if m != "OPTIONS"],
                    )
                )
    return found


def _url_for_rule(rule):
    return re.sub(
        r"<(?:(\w+):)?\w+>", lambda m: "1" if m.group(1) == "int" else "x", rule
    )


ROUTES = _declared_routes()
PROTECTED = [
    (endpoint, rule, method)
    for endpoint, rule, methods in ROUTES
    if endpoint not in PUBLIC_ENDPOINTS
    for method in methods
]


@pytest.fixture
def server(scratch_server):
    return scratch_server


# ---------------------------------------------------------------------------- anonymous sweep
def test_routes_were_found():
    assert len(ROUTES) >= 40, "the route parser found suspiciously few routes"


def test_every_route_decorator_could_be_read():
    assert UNPARSABLE == [], "extend _declared_routes() for: " + "; ".join(UNPARSABLE)


def test_the_public_allow_list_matches_the_declared_routes():
    declared = {endpoint for endpoint, _rule, _methods in ROUTES}
    assert PUBLIC_ENDPOINTS - declared == set(), "allow-list names a route that is gone"


@pytest.mark.parametrize(
    "endpoint,rule,method", PROTECTED, ids=[f"{m} {r}" for _e, r, m in PROTECTED]
)
def test_anonymous_callers_are_refused(server, endpoint, rule, method):
    client = server.client()
    url = _url_for_rule(rule)
    # the deep catch-all of the directory browser deliberately answers 404, not a redirect
    refused_json = 404 if endpoint == "index" and rule != "/" else 401
    if method == "GET":
        api = client.get(url, headers=JSON_HEADERS)
        page = client.get(url)
        # /api/* always answers JSON 401; page URLs get a 301 to /login (or the 404 above)
        page_refused = (401,) if rule.startswith("/api/") else (301, 404)
        assert page.status in page_refused, (page.status, page.text[:120])
    else:
        # a valid CSRF token, so the request is stopped by the login check and not by CSRF
        headers = {**JSON_HEADERS, "X-CSRFToken": client.csrf_token()}
        api = client.request(method, url, fields={}, headers=headers)
    assert api.status == refused_json, (api.status, api.text[:160])


# ---------------------------------------------------------------------------- role gates
READONLY_REFUSED = [
    ("POST", "/mkdir", {"foldername": "nope", "path": ""}),
    ("POST", "/rename", {"old_path": "a", "new_name": "b"}),
    ("POST", "/upload", {"file_id": "x", "chunk_num": "0", "total_chunks": "1"}),
    ("POST", "/cleanup_chunks", {}),
    ("POST", "/cancel_upload", {"file_id": "x"}),
    ("POST", "/admin/cleanup_chunks", {}),
    ("GET", "/admin/chunk_stats", None),
    ("POST", "/api/share", {"path": "a"}),
    ("POST", "/api/share/settings", {"path": "a"}),
    ("POST", "/api/unshare", {"path": "a"}),
    ("POST", "/api/share/bulk", {"paths": []}),
    ("GET", "/admin/shares", None),
    ("GET", "/admin/shares/count", None),
    ("GET", "/admin/shares/requests", None),
    ("POST", "/admin/revoke_all_shares/code", {}),
    ("POST", "/admin/revoke_all_shares", {}),
]


@pytest.mark.parametrize(
    "method,path,payload",
    READONLY_REFUSED,
    ids=[f"{m} {p}" for m, p, _ in READONLY_REFUSED],
)
def test_readonly_account_is_refused(server, method, path, payload):
    client = server.login_as(RO)
    reply = client.api(method, path, fields=payload)
    assert reply.status == 403, (reply.status, reply.text[:160])


@pytest.mark.parametrize(
    "path",
    [
        "/api/versions/restore",
        "/api/versions/retry",
        "/api/versions/clear-failed",
        "/api/versions/delete",
    ],
)
def test_readonly_account_cannot_change_version_history(server, path):
    client = server.login_as(RO)
    reply = client.api("POST", path, json_body={"path": "a.txt", "version_id": 1})
    assert reply.status == 403 and reply.json() == {"error": "Permission denied"}


def test_readonly_delete_is_refused_and_the_file_survives(server):
    victim = server.storage / "readonly_must_survive.txt"
    victim.write_bytes(b"keep me")
    client = server.login_as(RO)
    reply = client.api("POST", "/delete", fields={"target_path": victim.name})
    assert reply.status == 302  # flashes "Permission denied" and goes back to the index
    assert victim.read_bytes() == b"keep me"


def test_readonly_account_can_still_read(server):
    sample = server.storage / "readable.txt"
    sample.write_bytes(b"hello from the scratch storage")
    client = server.login_as(RO)
    listing = client.get("/api/files/", headers=JSON_HEADERS)
    assert listing.status == 200 and listing.json()["role"] == "readonly"
    assert any(item["name"] == "readable.txt" for item in listing.json()["files"])
    download = client.get("/download/readable.txt")
    assert download.status == 200 and download.body == b"hello from the scratch storage"
    status = client.get("/admin/upload_status", headers=JSON_HEADERS)
    assert status.status == 200 and status.json()["can_upload"] is False


def test_readwrite_account_passes_the_gate_and_can_create_a_folder(server):
    client = server.login_as(RW)
    reply = client.api(
        "POST", "/mkdir", fields={"foldername": "qa_created", "path": ""}
    )
    assert reply.status == 200, (reply.status, reply.text[:160])
    assert (server.storage / "qa_created").is_dir()


# ---------------------------------------------------------------------------- DB-driven roles
def test_demoting_an_account_takes_effect_on_the_next_request(server):
    name, password = server.make_user("readwrite")
    client = server.client()
    assert client.login(name, password).status == 302
    first = client.api("POST", "/mkdir", fields={"foldername": "before_demotion"})
    assert first.status == 200
    server.db("assert db.update_role(sys.argv[1], 'readonly')", name)
    second = client.api("POST", "/mkdir", fields={"foldername": "after_demotion"})
    assert second.status == 403
    assert not (server.storage / "after_demotion").exists()
    assert client.get("/api/files/", headers=JSON_HEADERS).json()["role"] == "readonly"


def test_promoting_an_account_takes_effect_on_the_next_request(server):
    name, password = server.make_user("readonly")
    client = server.client()
    assert client.login(name, password).status == 302
    assert client.api("POST", "/mkdir", fields={"foldername": "x"}).status == 403
    server.db("assert db.update_role(sys.argv[1], 'readwrite')", name)
    assert client.api("POST", "/mkdir", fields={"foldername": "promoted"}).status == 200
