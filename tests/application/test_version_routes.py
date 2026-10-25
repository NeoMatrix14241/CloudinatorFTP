"""
The HTTP routes /api/versions/* and /download/recovered/* against the REAL application started
from a scratch copy (routes/versions.py on top of version_history.py and version_engine.py).

No new fixture is needed: core.py calls version_history.init() at import whether or not the
Version Engine subprocess runs, so the routes work in the normal scratch server (engine OFF in
its config; no worker, no watcher, no timing). A version is captured by a small snippet that
runs the REAL engine inside the scratch copy (`server.db`, same helper the other tests use for
the scratch database) and calls `Engine.snapshot_file()`, which is what the worker does per file.
The test process never imports the application.

Role gates and the anonymous sweep for these routes are in test_authorization.py; the logic
behind them (restore, retention, corruption, ...) is in test_version_restore.py. This file
checks what the ROUTES add: input validation, status codes, JSON shape, headers, the
cross-file guard over HTTP and the recovered-file download.
"""

import json
import re
import textwrap
import uuid

import pytest

pytestmark = pytest.mark.application

RW, RO = "qa_writer", "qa_reader"

SEED = textwrap.dedent("""
    import json, os, time
    import config
    import version_history as vh
    assert os.path.abspath(config.ROOT_DIR).startswith(os.path.abspath(os.getcwd()))
    vh.init()
    eng = vh._get_engine()
    rel, contents = sys.argv[1], json.loads(sys.argv[2])
    path = os.path.join(config.ROOT_DIR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ids = []
    for text in contents:
        with open(path, "wb") as f:
            f.write(text.encode())
        ids.append(eng.snapshot_file(path, source="qa"))
        time.sleep(0.05)  # distinct created_at even on a coarse clock
    print("RESULT=" + json.dumps({"ids": ids}))
    """)

MARK_FAILED = textwrap.dedent("""
    import version_history as vh
    conn = vh._get_engine()._connect()
    conn.execute("UPDATE versions SET status='failed', error='boom' WHERE version_id=?",
                 (int(sys.argv[1]),))
    conn.commit()
    """)


@pytest.fixture
def server(scratch_server):
    return scratch_server


@pytest.fixture
def rw(server):
    return server.login_as(RW)


@pytest.fixture
def tag():
    return uuid.uuid4().hex[:8]


def seed(server, rel, *contents):
    """Write each content as the live file and capture a version of it; the LAST content stays
    live. Returns the version ids, oldest first."""
    out = server.db(SEED, rel, json.dumps(list(contents)))
    line = next(x for x in out.splitlines() if x.startswith("RESULT="))
    ids = json.loads(line[len("RESULT=") :])["ids"]
    assert all(isinstance(i, int) for i in ids), ids
    return ids


def get(client, url):
    return client.get(url, headers={"Accept": "application/json"})


def history(client, rel):
    reply = get(client, f"/api/versions/list?path={rel}")
    assert reply.status == 200, (reply.status, reply.text[:200])
    return reply.json()


def post(client, route, **body):
    return client.api("POST", f"/api/versions/{route}", json_body=body)


# ---------------------------------------------------------------------------- list
def test_list_of_an_untracked_file_says_so(server, rw, tag):
    (server.storage / f"untracked_{tag}.txt").write_bytes(b"never captured")
    body = history(rw, f"untracked_{tag}.txt")
    assert body == {"tracked": False, "versions": []}


def test_list_shows_the_versions_newest_first_with_retention_info(server, rw, tag):
    rel = f"vr_{tag}/doc.txt"
    ids = seed(server, rel, "one", "second!", "third one")
    body = history(rw, rel)
    assert body["tracked"] is True and body["restoring"] == []
    listed = body["versions"]
    assert [v["version_id"] for v in listed] == list(reversed(ids))
    assert [v["size"] for v in listed] == [9, 7, 3]
    assert all(v["status"] == "completed" for v in listed)
    assert all(re.fullmatch(r"[0-9a-f]{64}", v["sha256"]) for v in listed)
    retention = body["retention"]
    assert set(retention) == {"enabled", "max", "kept"} and retention["kept"] == 3


def test_a_readonly_account_may_read_the_history(server, tag):
    rel = f"vr_{tag}/ro.txt"
    seed(server, rel, "readable history")
    body = history(server.login_as(RO), rel)
    assert body["tracked"] is True and len(body["versions"]) == 1


@pytest.mark.parametrize("bad", ["", "../outside.txt", "a/../../outside.txt"])
def test_list_refuses_an_empty_or_escaping_path(rw, bad):
    reply = get(rw, f"/api/versions/list?path={bad}")
    assert reply.status == 400 and reply.json() == {"error": "Invalid file path"}


# ---------------------------------------------------------------------------- restore
def test_restore_writes_the_chosen_version_into_recovered_and_keeps_the_live_file(
    server, rw, tag
):
    rel = f"vr_{tag}/doc.txt"
    first, second = seed(server, rel, "first-content", "second-content!!")
    reply = post(rw, "restore", path=rel, version_id=first)
    assert reply.status == 200, (reply.status, reply.text[:200])
    body = reply.json()
    assert body["success"] is True
    pattern = (
        rf"^\.recovered/vr_{tag}/doc__\d{{4}}-\d{{2}}-\d{{2}}_\d{{6}}__v{first}\.txt$"
    )
    assert re.match(pattern, body["recovered_path"]), body["recovered_path"]
    assert (
        body["download_url"]
        == "/download/recovered/" + body["recovered_path"][len(".recovered/") :]
    )
    assert (server.storage / body["recovered_path"]).read_bytes() == b"first-content"
    assert (server.storage / rel).read_bytes() == b"second-content!!"
    assert second != first


def test_the_recovered_file_downloads_as_an_attachment(server, rw, tag):
    rel = f"vr_{tag}/dl.bin"
    (first,) = seed(server, rel, "bytes to get back")
    url = post(rw, "restore", path=rel, version_id=first).json()["download_url"]
    reply = rw.get(url)
    assert reply.status == 200 and reply.body == b"bytes to get back"
    assert "attachment" in reply.header("Content-Disposition")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"path": "a.txt"},
        {"version_id": 1},
        {"path": "a.txt", "version_id": "1"},
        {"path": "a.txt", "version_id": None},
        {"path": "../outside.txt", "version_id": 1},
        {"path": "", "version_id": 1},
    ],
)
def test_restore_refuses_a_malformed_request(rw, body):
    reply = rw.api("POST", "/api/versions/restore", json_body=body)
    assert reply.status == 400 and reply.json() == {"error": "Invalid request"}


def test_restore_of_an_unknown_version_is_a_clean_400(server, rw, tag):
    rel = f"vr_{tag}/doc.txt"
    seed(server, rel, "x")
    reply = post(rw, "restore", path=rel, version_id=987654321)
    assert reply.status == 400 and "No such version_id" in reply.json()["error"]


def test_a_version_of_another_file_is_refused_on_every_route(server, rw, tag):
    a, b = f"vr_{tag}/a.txt", f"vr_{tag}/b.txt"
    (va,) = seed(server, a, "file A")
    (vb,) = seed(server, b, "file B")
    for reply in (
        post(rw, "restore", path=a, version_id=vb),
        post(rw, "delete", path=a, version_id=vb, confirm_text="a.txt"),
        get(rw, f"/api/versions/download?path={a}&version_id={vb}"),
    ):
        assert reply.status == 400, (reply.status, reply.text[:200])
        assert "does not belong" in reply.json()["error"]
    assert not (server.storage / ".recovered" / f"vr_{tag}").exists()
    versions_of_b = history(rw, b)["versions"]
    assert [v["status"] for v in versions_of_b] == ["completed"]
    assert va != vb


def test_restoring_a_failed_version_is_refused(server, rw, tag):
    rel = f"vr_{tag}/f.txt"
    (v,) = seed(server, rel, "content")
    server.db(MARK_FAILED, str(v))
    reply = post(rw, "restore", path=rel, version_id=v)
    assert reply.status == 400 and "not restorable" in reply.json()["error"]


# ---------------------------------------------------------------------------- download
def test_download_streams_the_exact_bytes_of_an_old_version(server, rw, tag):
    rel = f"vr_{tag}/dl.dat"
    first, _ = seed(server, rel, "old" * 1000, "new")
    reply = rw.get(f"/api/versions/download?path={rel}&version_id={first}")
    assert reply.status == 200 and reply.body == b"old" * 1000
    assert re.fullmatch(
        r'attachment; filename="dl__\d{4}-\d{2}-\d{2}_\d{6}__v\d+\.dat"',
        reply.header("Content-Disposition"),
    ), reply.header("Content-Disposition")
    assert reply.header("Content-Length") == str(len(reply.body))
    # the route sets no-store; the after_request hook widens it to no-cache, no-store, ...
    assert "no-store" in reply.header("Cache-Control")
    assert not (
        server.storage / ".recovered" / f"vr_{tag}"
    ).exists()  # nothing restored


def test_a_readonly_account_may_download_an_old_version(server, tag):
    rel = f"vr_{tag}/ro_dl.txt"
    (v,) = seed(server, rel, "for readers")
    reply = server.login_as(RO).get(f"/api/versions/download?path={rel}&version_id={v}")
    assert reply.status == 200 and reply.body == b"for readers"


@pytest.mark.parametrize("version_id", ["", "abc", "-1", "1.5", "1%20OR%201"])
def test_download_refuses_a_version_id_that_is_not_digits(rw, version_id):
    reply = get(rw, f"/api/versions/download?path=a.txt&version_id={version_id}")
    assert reply.status == 400 and reply.json() == {"error": "Invalid request"}


@pytest.mark.parametrize("path", ["", "../outside.txt"])
def test_download_refuses_an_empty_or_escaping_path(rw, path):
    reply = get(rw, f"/api/versions/download?path={path}&version_id=1")
    assert reply.status == 400 and reply.json() == {"error": "Invalid request"}


def test_download_of_an_unknown_version_is_a_clean_400(server, rw, tag):
    rel = f"vr_{tag}/doc.txt"
    seed(server, rel, "x")
    reply = get(rw, f"/api/versions/download?path={rel}&version_id=987654321")
    assert reply.status == 400 and "No such version_id" in reply.json()["error"]


# ---------------------------------------------------------------------------- retry
def test_retry_captures_a_changed_file_and_says_so_when_nothing_changed(
    server, rw, tag
):
    rel = f"vr_{tag}/retry.txt"
    seed(server, rel, "before")
    (server.storage / rel).write_bytes(b"after the change")
    first = post(rw, "retry", path=rel)
    assert first.status == 200, (first.status, first.text[:200])
    body = first.json()
    assert body["success"] is True and body["version"]["status"] == "completed"
    assert body["version"]["size"] == len(b"after the change")
    assert len(history(rw, rel)["versions"]) == 2
    again = post(rw, "retry", path=rel)
    assert again.status == 200
    assert again.json()["success"] is True and again.json()["version"] is None
    assert "No new snapshot" in again.json()["message"]
    assert len(history(rw, rel)["versions"]) == 2


@pytest.mark.parametrize("body", [{}, {"path": ""}, {"path": "../outside.txt"}])
def test_retry_refuses_a_missing_or_escaping_path(rw, body):
    reply = rw.api("POST", "/api/versions/retry", json_body=body)
    assert reply.status == 400 and reply.json() == {"error": "Invalid request"}


# ---------------------------------------------------------------------------- clear failed
def test_clear_failed_removes_only_failed_rows(server, rw, tag):
    rel = f"vr_{tag}/mixed.txt"
    good, bad = seed(server, rel, "good one", "another try")
    server.db(MARK_FAILED, str(bad))
    assert [v["status"] for v in history(rw, rel)["versions"]] == [
        "failed",
        "completed",
    ]
    cleared = post(rw, "clear-failed", path=rel)
    assert cleared.status == 200
    assert cleared.json()["success"] is True and cleared.json()["removed"] == 1
    assert [v["version_id"] for v in history(rw, rel)["versions"]] == [good]
    nothing = post(rw, "clear-failed", path=rel)
    assert nothing.json()["success"] is True and nothing.json()["removed"] == 0
    assert post(rw, "restore", path=rel, version_id=good).status == 200


@pytest.mark.parametrize("body", [{}, {"path": ""}, {"path": "../outside.txt"}])
def test_clear_failed_refuses_a_missing_or_escaping_path(rw, body):
    reply = rw.api("POST", "/api/versions/clear-failed", json_body=body)
    assert reply.status == 400 and reply.json() == {"error": "Invalid request"}


# ---------------------------------------------------------------------------- delete
def test_delete_needs_the_typed_file_name_and_keeps_the_other_versions(server, rw, tag):
    rel = f"vr_{tag}/gone.txt"
    first, second = seed(server, rel, "one", "two!")
    wrong = post(rw, "delete", path=rel, version_id=first, confirm_text="not the name")
    assert wrong.status == 400 and "nothing was deleted" in wrong.json()["error"]
    assert history(rw, rel)["versions"][-1]["status"] == "completed"

    right = post(rw, "delete", path=rel, version_id=first, confirm_text="gone.txt")
    assert right.status == 200 and right.json()["success"] is True
    status = {v["version_id"]: v["status"] for v in history(rw, rel)["versions"]}
    assert status == {first: "deleted", second: "completed"}

    gone = post(rw, "restore", path=rel, version_id=first)
    assert gone.status == 400 and "status=deleted" in gone.json()["error"]
    other = post(rw, "restore", path=rel, version_id=second)
    assert other.status == 200


@pytest.mark.parametrize(
    "body",
    [
        {"path": "a.txt", "confirm_text": "a.txt"},
        {"path": "a.txt", "version_id": "1", "confirm_text": "a.txt"},
        {"path": "../outside.txt", "version_id": 1, "confirm_text": "outside.txt"},
    ],
)
def test_delete_refuses_a_malformed_request(rw, body):
    reply = rw.api("POST", "/api/versions/delete", json_body=body)
    assert reply.status == 400 and reply.json() == {"error": "Invalid request"}


def test_delete_without_a_confirmation_text_deletes_nothing(server, rw, tag):
    rel = f"vr_{tag}/keep.txt"
    (v,) = seed(server, rel, "keep me")
    reply = rw.api(
        "POST", "/api/versions/delete", json_body={"path": rel, "version_id": v}
    )
    assert reply.status == 400
    assert history(rw, rel)["versions"][0]["status"] == "completed"


# ---------------------------------------------------------------------------- /download/recovered
def test_recovered_download_cannot_leave_the_recovered_folder(server, rw, tag):
    # data/outside_<tag>.txt is two levels above .recovered/, outside the storage root, so no
    # other route can ever serve it; only a broken containment check here could.
    secret = server.root / "data" / f"outside_{tag}.txt"
    secret.write_text("TOP-SECRET-OUTSIDE", encoding="utf-8")
    try:
        for url in (
            f"/download/recovered/../../outside_{tag}.txt",
            f"/download/recovered/%2e%2e/%2e%2e/outside_{tag}.txt",
            f"/download/recovered/..%2f..%2foutside_{tag}.txt",
            f"/download/recovered/a/../../../outside_{tag}.txt",
        ):
            reply = rw.get(url)
            assert b"TOP-SECRET" not in reply.body, (url, reply.status)
    finally:
        secret.unlink(missing_ok=True)


def test_recovered_download_of_a_missing_file_or_a_folder_is_404(server, rw, tag):
    rel = f"vr_{tag}/doc.txt"
    (v,) = seed(server, rel, "x")
    assert post(rw, "restore", path=rel, version_id=v).status == 200
    assert rw.get(f"/download/recovered/vr_{tag}/nothing.txt").status == 404
    assert rw.get(f"/download/recovered/vr_{tag}").status == 404
