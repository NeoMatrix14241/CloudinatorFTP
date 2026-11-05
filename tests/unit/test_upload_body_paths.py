"""
Tests of the 5.41 changes in routes/uploads.py that can be checked without the application: the
REAL code of `_in_memory_parse_wanted`, `_upload_form_and_files` and `_read_and_save_chunk` is
read with `ast` (the module cannot be imported: it starts the whole application) and run against
real Quart objects in a toy app. A second group reads the `upload()` handler itself and guards
the two rules of the change: no synchronous chunk I/O on the event-loop thread, and the form is
parsed once.

Needs Quart (installed with requirements.txt); the tests skip without it.
"""

import ast
import asyncio
import importlib.util
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
UPLOADS_PATH = ROOT / "routes" / "uploads.py"
HELPER_PATH = ROOT / "helpers" / "upload_perf.py"

NAMES = (
    "_IN_MEMORY_BODY_MARGIN",
    "_CSRF_HEADER_NAMES",
    "_in_memory_parse_wanted",
    "_upload_form_and_files",
    "_read_and_save_chunk",
)
CHUNK_SIZE = 1024 * 1024  # a small chunk size keeps the test bodies small


def _tree():
    return ast.parse(UPLOADS_PATH.read_text(encoding="utf-8"))


def _load_helper():
    spec = importlib.util.spec_from_file_location("upload_perf_for_paths", HELPER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _namespace(storage, in_memory):
    quart = pytest.importorskip("quart")
    body = []
    for node in _tree().body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name in NAMES
        ):
            body.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in NAMES for t in node.targets
        ):
            body.append(node)
    found = {getattr(n, "name", None) for n in body if hasattr(n, "name")}
    assert {
        "_in_memory_parse_wanted",
        "_upload_form_and_files",
        "_read_and_save_chunk",
    } <= found, found
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "request": quart.request,
        "UPLOAD_CHUNKS_IN_MEMORY": in_memory,
        "CHUNK_SIZE": CHUNK_SIZE,
        "parse_form_in_memory": _load_helper().parse_form_in_memory,
        "storage": storage,
        "time": time,
    }
    exec(compile(module, str(UPLOADS_PATH), "exec"), namespace)
    return namespace


def _multipart(fields, payload):
    boundary = "qa-" + uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields.items()
    ]
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="chunk"; '
            'filename="blob"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode()
        + payload
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _post(
    namespace,
    payload,
    csrf_header=True,
    extra_headers=None,
    content_length=True,
    timer=None,
):
    """Make the calls /upload makes inside a Quart request context built from a multipart POST;
    returns what they gave. No route is registered (tests/smoke.py scans tests for routes and
    would report a "new" one). A browser's XHR always sends Content-Length for a FormData body;
    the test request context does not, so the header is set here (content_length=False leaves it
    out)."""
    quart = pytest.importorskip("quart")
    app = quart.Quart("toy_upload")
    body, content_type = _multipart({"file_id": "fid_1", "chunk_num": "2"}, payload)
    headers = {"Content-Type": content_type}
    if content_length:
        headers["Content-Length"] = str(len(body))
    if csrf_header:
        headers["X-CSRFToken"] = "token"
    headers.update(extra_headers or {})

    async def run():
        async with app.test_request_context(
            "/probe", method="POST", data=body, headers=headers
        ):
            wanted = namespace["_in_memory_parse_wanted"]()
            form, files = await namespace["_upload_form_and_files"](timer=timer)
            chunk = files.get("chunk")
            data = chunk.read()
            return {
                "wanted": wanted,
                "stream": type(chunk.stream).__name__,
                "same": data == payload,
                "file_id": form.get("file_id"),
                "chunk_num": form.get("chunk_num"),
            }

    return asyncio.run(run())


PAYLOAD = (
    bytes(range(256)) * 4096
)  # 1 MiB = one chunk, above werkzeug's 500 KB spool limit


# ---------------------------------------------------------------------------- body parsing
def test_default_uses_quarts_own_parser_with_a_spooled_temp_file():
    out = _post(_namespace(None, in_memory=False), PAYLOAD)
    assert out["wanted"] is False and out["same"] is True
    assert out["stream"] != "BytesIO"  # a SpooledTemporaryFile rolled over to disk
    assert out["file_id"] == "fid_1" and out["chunk_num"] == "2"


def test_the_flag_parses_a_chunk_sized_body_in_memory():
    out = _post(_namespace(None, in_memory=True), PAYLOAD)
    assert out["wanted"] is True and out["same"] is True
    assert out["stream"] == "BytesIO"
    assert out["file_id"] == "fid_1" and out["chunk_num"] == "2"


def test_without_a_csrf_header_the_flag_is_ignored():
    """The CSRF hook then reads the form with Quart's parser, so the body is already consumed."""
    out = _post(_namespace(None, in_memory=True), PAYLOAD, csrf_header=False)
    assert out["wanted"] is False and out["same"] is True


def test_a_body_without_a_known_length_keeps_quarts_parser():
    """Its size is not known up front, so it cannot be bounded: the safe default applies."""
    out = _post(_namespace(None, in_memory=True), PAYLOAD, content_length=False)
    assert out["wanted"] is False and out["same"] is True


def test_the_alternative_csrf_header_name_counts_too():
    out = _post(
        _namespace(None, in_memory=True),
        PAYLOAD,
        csrf_header=False,
        extra_headers={"X-CSRF-Token": "token"},
    )
    assert out["wanted"] is True and out["stream"] == "BytesIO"


def test_a_body_bigger_than_one_chunk_keeps_quarts_parser():
    big = bytes(range(256)) * 4096 * 3  # 3 MiB > CHUNK_SIZE (1 MiB) + 1 MiB margin
    out = _post(_namespace(None, in_memory=True), big)
    assert out["wanted"] is False and out["same"] is True
    assert out["stream"] != "BytesIO"


# ---------------------------------------------------------------------------- the split (5.43)
class _Timer:
    """Stands in for helpers.upload_perf.StageTimer: records the details it is told."""

    def __init__(self):
        self.details = []

    def detail(self, name, seconds):
        self.details.append((name, seconds))


def test_the_ram_parse_tells_the_timer_how_long_the_body_took_and_how_long_the_parse():
    timer = _Timer()
    out = _post(_namespace(None, in_memory=True), PAYLOAD, timer=timer)
    assert out["stream"] == "BytesIO" and out["same"] is True
    assert [name for name, _ in timer.details] == ["body arrived", "parse"]
    assert all(isinstance(sec, float) and sec >= 0 for _, sec in timer.details)


def test_quarts_own_parser_cannot_be_divided_so_it_reports_nothing():
    """It reads and parses the body piece by piece while it arrives."""
    timer = _Timer()
    out = _post(_namespace(None, in_memory=False), PAYLOAD, timer=timer)
    assert out["wanted"] is False and out["same"] is True
    assert timer.details == []


def test_the_handler_gives_the_helper_its_stage_timer():
    calls = [
        n.value
        for n in ast.walk(_upload_handler())
        if isinstance(n, ast.Await)
        and isinstance(n.value, ast.Call)
        and _dotted(n.value.func) == "_upload_form_and_files"
    ]
    assert [ast.unparse(a) for a in calls[0].args] == ["in_memory", "timer"]


# ---------------------------------------------------------------------------- read + save
class FakeChunk:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class FakeStorage:
    def __init__(self, result=True):
        self.result = result
        self.saved = []

    def save_chunk(self, key, number, data):
        self.saved.append((key, number, bytes(data)))
        return self.result


def test_a_piece_is_read_and_saved_and_the_times_are_reported():
    storage = FakeStorage()
    ns = _namespace(storage, in_memory=False)
    outcome, read_s, save_s, size = ns["_read_and_save_chunk"](
        FakeChunk(b"abc" * 100), "key_1", 4
    )
    assert (outcome, size) == ("saved", 300)
    assert read_s >= 0 and save_s >= 0
    assert storage.saved == [("key_1", 4, b"abc" * 100)]


def test_a_failed_save_is_reported_as_failed():
    ns = _namespace(FakeStorage(result=False), in_memory=False)
    assert ns["_read_and_save_chunk"](FakeChunk(b"x"), "k", 0)[0] == "failed"


def test_a_piece_over_the_chunk_size_is_refused_and_never_written():
    storage = FakeStorage()
    ns = _namespace(storage, in_memory=False)
    outcome, _read, save_s, size = ns["_read_and_save_chunk"](
        FakeChunk(b"x" * (CHUNK_SIZE + 1)), "k", 0
    )
    assert (outcome, save_s, size) == ("too_large", 0.0, CHUNK_SIZE + 1)
    assert storage.saved == []


def test_a_piece_of_exactly_the_chunk_size_is_accepted():
    ns = _namespace(FakeStorage(), in_memory=False)
    assert ns["_read_and_save_chunk"](FakeChunk(b"x" * CHUNK_SIZE), "k", 0)[0] == (
        "saved"
    )


# ---------------------------------------------------------------------------- the handler itself
def _upload_handler():
    found = next(
        (
            node
            for node in _tree().body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "upload"
        ),
        None,
    )
    if found is None:
        pytest.fail("async def upload() not found in routes/uploads.py")
    return found


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def test_the_handler_does_no_synchronous_chunk_io_itself():
    calls = {
        _dotted(n.func) for n in ast.walk(_upload_handler()) if isinstance(n, ast.Call)
    }
    assert "storage.save_chunk" not in calls, "save_chunk must run in the worker thread"
    assert "chunk.read" not in calls, "reading the piece must run in the worker thread"


def test_the_handler_hands_the_piece_to_a_worker_thread():
    threaded = [
        n
        for n in ast.walk(_upload_handler())
        if isinstance(n, ast.Call)
        and _dotted(n.func) == "asyncio.to_thread"
        and n.args
        and isinstance(n.args[0], ast.Name)
        and n.args[0].id == "_read_and_save_chunk"
    ]
    assert len(threaded) == 1


def test_the_form_is_parsed_once_through_the_helper():
    awaited = [
        _dotted(n.value)
        for n in ast.walk(_upload_handler())
        if isinstance(n, ast.Await) and isinstance(n.value, ast.Attribute)
    ]
    assert "request.form" not in awaited and "request.files" not in awaited
    calls = [
        _dotted(n.value.func)
        for n in ast.walk(_upload_handler())
        if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
    ]
    assert calls.count("_upload_form_and_files") == 1


def test_the_after_assembly_reconcile_goes_through_the_deferral():
    """core._trigger_reconcile must only be called by the IdleDeferral, never directly."""
    direct = [
        n
        for node in _tree().body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and _dotted(n.func) == "_trigger_reconcile"
    ]
    assert direct == [], "call _reconcile_after_uploads.request() instead"
    text = UPLOADS_PATH.read_text(encoding="utf-8")
    assert "_reconcile_after_uploads.request()" in text
    assert "action=_trigger_reconcile" in text
