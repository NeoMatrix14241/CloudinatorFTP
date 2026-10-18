"""
Tests of the HTTP client and scratch-database helpers in tests/conftest.py, against a tiny local
server and a fake scratch folder (the real application is not involved).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _echo(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = {
            "method": self.command,
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": self.rfile.read(length).decode("utf-8") if length else "",
        }
        self._send(200, json.dumps(payload).encode("utf-8"))

    def do_GET(self):
        if self.path == "/set-cookie-and-redirect":
            self._send(
                302,
                headers=[
                    ("Location", "/echo"),
                    ("Set-Cookie", "sid=abc123; Path=/; HttpOnly"),
                    ("Set-Cookie", "other=2; Path=/"),
                ],
            )
        elif self.path == "/missing":
            self._send(404, b"nope")
        else:
            self._echo()

    do_POST = do_GET


@pytest.fixture(scope="module")
def local_server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def make_client(scratch_tools, local_server):
    return lambda ip=None: scratch_tools.HttpClient(local_server, ip)


def test_redirects_are_not_followed_and_cookies_are_kept(make_client):
    client = make_client()
    first = client.get("/set-cookie-and-redirect")
    assert first.status == 302 and first.header("Location") == "/echo"
    assert len(first.set_cookies) == 2
    sent = client.get("/echo").json()["headers"]["cookie"]
    assert "sid=abc123" in sent and "other=2" in sent
    assert "sid=abc123" in client.cookie_header()


def test_every_client_has_its_own_fake_ip_sent_as_cf_connecting_ip(make_client):
    a, b = make_client(), make_client()
    assert a.ip != b.ip
    assert a.get("/echo").json()["headers"]["cf-connecting-ip"] == a.ip
    assert make_client("10.1.2.3").get("/echo").json()["headers"][
        "cf-connecting-ip"
    ] == ("10.1.2.3")


def test_a_header_set_to_none_is_not_sent(make_client):
    sent = make_client().get("/echo", headers={"CF-Connecting-IP": None}).json()
    assert "cf-connecting-ip" not in sent["headers"]


def test_form_and_json_bodies_get_the_right_content_type(make_client):
    client = make_client()
    form = client.post_form("/echo", {"a": "1", "b": "x y"}).json()
    assert form["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert form["body"] == "a=1&b=x+y"
    sent = client.request("POST", "/echo", json_body={"k": [1, 2]}).json()
    assert sent["headers"]["content-type"] == "application/json"
    assert json.loads(sent["body"]) == {"k": [1, 2]}


def test_error_statuses_are_returned_not_raised(make_client):
    reply = make_client().get("/missing")
    assert reply.status == 404 and reply.text == "nope"


def test_api_adds_the_json_accept_header_and_a_csrf_header_for_writes(make_client):
    client = make_client()
    client.csrf_token = lambda: "tok-123"
    read = client.api("GET", "/echo").json()["headers"]
    assert read["accept"] == "application/json" and "x-csrftoken" not in read
    write = client.api("POST", "/echo", fields={"a": "1"}).json()["headers"]
    assert write["x-csrftoken"] == "tok-123"


def test_run_in_scratch_uses_the_scratch_copy_and_passes_arguments(
    scratch_tools, tmp_path
):
    (tmp_path / "paths.py").write_text("def ensure_dirs():\n    pass\n", "utf-8")
    (tmp_path / "database.py").write_text(
        "class _Db:\n    def hello(self, who):\n        return 'hello ' + who\n\n"
        "db = _Db()\n",
        "utf-8",
    )
    out = scratch_tools.run_in_scratch(
        tmp_path, "print(db.hello(sys.argv[1]), os.getcwd())", "world"
    )
    assert out.split()[:2] == ["hello", "world"]
    assert Path(out.split(" ", 2)[2].strip()).resolve() == tmp_path.resolve()


def test_run_in_scratch_raises_with_the_error_text(scratch_tools, tmp_path):
    (tmp_path / "paths.py").write_text("def ensure_dirs():\n    pass\n", "utf-8")
    (tmp_path / "database.py").write_text("db = object()\n", "utf-8")
    with pytest.raises(RuntimeError, match="boom"):
        scratch_tools.run_in_scratch(tmp_path, "raise SystemExit('boom')")


def test_test_users_cover_both_roles(scratch_tools):
    roles = {role for _pw, role in scratch_tools.test_users.values()}
    assert roles == {"readwrite", "readonly"}
