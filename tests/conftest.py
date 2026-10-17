"""
tests/conftest.py - shared pytest fixtures for CloudinatorFTP (CLAUDE.md 5.00).

The one rule: a test must NEVER touch the real db/, cache/, versions/ or storage folders.

Why a scratch copy: paths.py reads storage_config.json and config.py reads server_config.json
from the folder that contains the .py file, and core.py starts the file monitor, the cleanup
threads etc. at import time. So the application is never imported into the pytest process.
Instead the source tree is copied into a temporary folder, fresh config files that point
inside that folder are written, and the app runs there as a SUBPROCESS (dev_server.py) on an
ephemeral port. Tests talk to it over HTTP.

In-process imports from the real tree are limited to side-effect-free leaf modules (today:
paths, which has no project imports and no import-time side effects). The autouse guard
below fails any test run in which another root module was imported from the real tree.
"""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Root modules that are safe to import in-process from the real tree.
IN_PROCESS_OK = {"paths"}

# Never copied into the scratch tree (any depth): real data, caches, vendored pdf.js/fonts.
COPY_SKIP = {
    ".git",
    ".github",
    ".manage_pids",
    "__pycache__",
    ".pytest_cache",
    ".hypothesis",
    "venv",
    ".venv",
    "node_modules",
    "logs",
    "db",
    "cache",
    "versions",
    "uploads",
    "docs",
    "tests",
    "cmaps",
    "iccs",
    "images",
    "locale",
    "standard_fonts",
    "wasm",
    "webfonts",
    "audio",
}
# Config files that are written fresh in the scratch tree, never copied.
CONFIG_FILES = {"storage_config.json", "server_config.json"}


def _is_inside(child, parent) -> bool:
    c = os.path.normcase(os.path.realpath(str(child)))
    p = os.path.normcase(os.path.realpath(str(parent)))
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_scratch(dest, src_root=REPO_ROOT, port=0) -> Path:
    """Copy the source tree into `dest` and write config files that point inside it."""
    dest = Path(dest)
    src_root = Path(src_root)

    def _ignore(_dir, names):
        return [n for n in names if n in COPY_SKIP or n in CONFIG_FILES]

    # Root-level .py files, plus helpers/, routes/, templates/ and a trimmed static/.
    dest.mkdir(parents=True, exist_ok=True)
    for f in src_root.glob("*.py"):
        shutil.copy2(f, dest / f.name)
    for sub in ("helpers", "routes", "templates", "static"):
        if (src_root / sub).is_dir():
            shutil.copytree(src_root / sub, dest / sub, ignore=_ignore)

    data = dest / "data"
    storage = data / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    storage_cfg = {
        "storage_path": str(storage),
        "db_path": str(data / "db"),
        "cache_path": str(data / "cache"),
        "versions_path": str(data / "versions"),
        "hls_cache_path": str(data / "cache" / "hls"),
        "img_cache_path": str(data / "cache" / "img"),
    }
    server_cfg = {
        "PORT": int(port),
        "HOST": "127.0.0.1",
        "ENABLE_SEARCH_INDEX": False,
        "ENABLE_FFMPEG": False,
        "ENABLE_LIBVIPS": False,
        "WEBDAV_ENABLED": False,
        "WEBDAV_HTTPS_ENABLED": False,
        "SFTP_ENABLED": False,
        "FTP_ENABLED": False,
        "SMB_ENABLED": False,
        "VERSION_ENGINE_ENABLED": False,
    }
    (dest / "storage_config.json").write_text(
        json.dumps(storage_cfg, indent=2), "utf-8"
    )
    (dest / "server_config.json").write_text(json.dumps(server_cfg, indent=2), "utf-8")
    return dest


def resolve_paths(scratch) -> dict:
    """Ask the scratch copy's own paths.py where it would keep its data (read-only call)."""
    code = (
        "import json, os, sys; sys.path.insert(0, os.getcwd()); import paths; "
        "print(json.dumps(paths.get_all_paths()))"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(scratch),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(f"could not resolve scratch paths: {out.stderr.strip()}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def paths_outside(scratch, repo_root=REPO_ROOT) -> list:
    """Return human-readable violations; an empty list means the scratch tree is isolated."""
    bad = []
    if _is_inside(scratch, repo_root) or _is_inside(repo_root, scratch):
        bad.append(f"scratch folder overlaps the real project: {scratch}")
    resolved = resolve_paths(scratch)
    for key in (
        "db_dir",
        "cache_dir",
        "hls_cache_dir",
        "img_cache_dir",
        "versions_dir",
    ):
        if not _is_inside(resolved[key], scratch):
            bad.append(f"{key} resolves outside the scratch folder: {resolved[key]}")
    try:
        cfg = json.loads((Path(scratch) / "storage_config.json").read_text("utf-8"))
    except (OSError, ValueError) as e:
        return bad + [f"scratch storage_config.json unreadable: {e}"]
    if not _is_inside(cfg.get("storage_path", ""), scratch):
        bad.append(
            f"storage_path is outside the scratch folder: {cfg.get('storage_path')}"
        )
    return bad


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _hash_real_configs() -> dict:
    out = {}
    for name in sorted(CONFIG_FILES):
        p = REPO_ROOT / name
        out[name] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    return out


# --------------------------------------------------------------------------------------
# Guard: nothing but the leaf modules may be imported in-process from the real tree.
# --------------------------------------------------------------------------------------
def _forbidden_loaded() -> list:
    root_mods = {p.stem for p in REPO_ROOT.glob("*.py")} - IN_PROCESS_OK
    bad = []
    for name in sorted(root_mods):
        mod = sys.modules.get(name)
        f = getattr(mod, "__file__", None)
        if mod is not None and f and _is_inside(f, REPO_ROOT):
            bad.append(name)
    return bad


def pytest_collection_finish(session):
    bad = _forbidden_loaded()
    if bad:
        raise pytest.UsageError(
            "tests imported application modules from the real project in-process: "
            + ", ".join(bad)
            + ". Use the scratch_server fixture (subprocess) instead; see tests/conftest.py."
        )


@pytest.fixture(autouse=True)
def _no_real_app_modules():
    yield
    bad = _forbidden_loaded()
    assert not bad, (
        "a test imported application modules from the real project in-process: "
        + ", ".join(bad)
    )


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def scratch_tools():
    """The scratch-copy helpers, for tests of the harness itself."""
    return types.SimpleNamespace(
        build=build_scratch,
        resolve_paths=resolve_paths,
        paths_outside=paths_outside,
        free_port=free_port,
        is_inside=_is_inside,
        real_config_hashes=_hash_real_configs,
        repo_root=REPO_ROOT,
    )


class ScratchServer:
    def __init__(self, root, port, proc, log_path, real_hashes):
        self.root = Path(root)
        self.port = port
        self.proc = proc
        self.log_path = Path(log_path)
        self.base_url = f"http://127.0.0.1:{port}"
        self.real_config_hashes = real_hashes
        self._opener = urllib.request.build_opener(_NoRedirect)

    def get(self, path, headers=None):
        """GET without following redirects. Returns (status, headers, body_bytes)."""
        req = urllib.request.Request(self.base_url + path, headers=headers or {})
        try:
            with self._opener.open(req, timeout=15) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def log_tail(self, n=40) -> str:
        try:
            lines = self.log_path.read_text("utf-8", errors="replace").splitlines()
        except OSError:
            return "(no log)"
        return "\n".join(lines[-n:])


@pytest.fixture(scope="session")
def scratch_server(tmp_path_factory):
    """Start dev_server.py from a scratch copy of the project on an ephemeral port."""
    if not (REPO_ROOT / "dev_server.py").exists():
        pytest.skip("dev_server.py not found next to tests/")
    real_hashes = _hash_real_configs()
    root = tmp_path_factory.mktemp("cloudinator_scratch") / "app"
    port = free_port()
    build_scratch(root, port=port)

    violations = paths_outside(root)
    if violations:  # refuse to start anything; this is the production-data safety net
        pytest.fail(
            "scratch isolation check failed, nothing started:\n" + "\n".join(violations)
        )

    (root / ".manage_pids").mkdir(exist_ok=True)
    stop_file = root / ".manage_pids" / "dev.stop"
    log_path = root / "scratch_server.log"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "CLOUDINATOR_BG": "1",  # no reloader (see dev_server.py)
            "CLOUDINATOR_FTP_ROOT": str(root / "data" / "storage"),
        }
    )
    env.pop("CLOUDINATOR_PUBLIC_DOMAIN", None)

    log = open(log_path, "wb")
    proc = subprocess.Popen(
        [sys.executable, "dev_server.py"],
        cwd=str(root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    server = ScratchServer(root, port, proc, log_path, real_hashes)
    try:
        deadline = time.monotonic() + 90
        while True:
            if proc.poll() is not None:
                pytest.fail(
                    f"scratch server exited with code {proc.returncode} during startup:\n"
                    + server.log_tail()
                )
            try:
                server.get("/login")
                break  # any HTTP answer means the server is up
            except (urllib.error.URLError, OSError):
                if time.monotonic() > deadline:
                    pytest.fail(
                        "scratch server did not answer in 90 s:\n" + server.log_tail()
                    )
                time.sleep(0.5)
        yield server
    finally:
        # Same graceful request manage.sh uses (dev_server.py watches this file).
        try:
            stop_file.write_text("stop", "utf-8")
        except OSError:
            pass
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        log.close()
