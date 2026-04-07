"""
paths.py — Central path resolver for db/ and cache/ directories.
-----------------------------------------------------------------
Single source of truth for where CloudinatorFTP keeps its sensitive
and ephemeral data.  No dependencies on any other project module,
so it can be safely imported by database.py (which config.py imports),
breaking any circular-import risk.

All three configurable paths live in storage_config.json:
  storage_path  — where uploaded files are stored        (owned by config.py)
  db_path       — SQLite DB + encryption keys + session secret
  cache_path    — storage_index.json + file_index.json

Default locations (when not set in storage_config.json):
  db_path    → <server_root>/db
  cache_path → <server_root>/cache

Changing these to a location OUTSIDE the web-served directory tree is
recommended in production — a compromised web root then cannot expose
your encryption key, session secret, or user database.

Usage:
  from paths import get_db_dir, get_cache_dir, set_db_dir, set_cache_dir
"""

import os
import json

# Server root = the directory that contains this file
_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILE = os.path.join(_HERE, "storage_config.json")


# ---------------------------------------------------------------------------
# Internal helpers — merge-safe read/write so no caller ever wipes a sibling key
# ---------------------------------------------------------------------------


def _load() -> dict:
    """Load storage_config.json, returning {} on any error."""
    try:
        if os.path.exists(_CONFIG_FILE):
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save(updates: dict):
    """
    Merge `updates` into storage_config.json.
    Existing keys NOT in `updates` are preserved — this prevents config.py's
    storage_path write from wiping db_path/cache_path and vice-versa.
    """
    try:
        data = _load()
        data.update(updates)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"⚠️  paths.py: could not write {_CONFIG_FILE}: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_db_dir(create: bool = True) -> str:
    """
    Return the configured db directory (absolute path).
    Defaults to <server_root>/db if not set in storage_config.json.
    Pass create=False to just read the path without creating the directory
    (used by setup_storage.py for display before the user configures anything).
    """
    path = _load().get("db_path") or os.path.join(_HERE, "db")
    path = os.path.abspath(path)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def get_cache_dir(create: bool = True) -> str:
    """
    Return the configured cache directory (absolute path).
    Defaults to <server_root>/cache if not set in storage_config.json.
    Pass create=False to just read the path without creating the directory
    (used by setup_storage.py for display before the user configures anything).
    """
    path = _load().get("cache_path") or os.path.join(_HERE, "cache")
    path = os.path.abspath(path)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def set_db_dir(path: str) -> bool:
    """
    Validate, create, and persist a new db directory.
    Automatically appends a 'db' subfolder so the user can point at a
    parent like C:\\Server and get C:\\Server\\db.
    Returns True on success, False if the path is not writable.
    """
    path = os.path.abspath(os.path.expanduser(path))
    # Auto-append 'db' subfolder if not already ending in 'db'
    if os.path.basename(path).lower() != "db":
        path = os.path.join(path, "db")
    try:
        os.makedirs(path, exist_ok=True)
        _test_writable(path)
        _save({"db_path": path})
        print(f"✅ DB directory set to: {path}")
        print("⚠️  Restart the server for the change to take effect.")
        print("   Don't forget to move your existing db/ files to the new location!")
        return True
    except Exception as e:
        print(f"❌ Cannot use DB path '{path}': {e}")
        return False


def set_cache_dir(path: str) -> bool:
    """
    Validate, create, and persist a new cache directory.
    Automatically appends a 'cache' subfolder so the user can point at a
    parent like C:\\Server and get C:\\Server\\cache.
    Returns True on success, False if the path is not writable.
    """
    path = os.path.abspath(os.path.expanduser(path))
    # Auto-append 'cache' subfolder if not already ending in 'cache'
    if os.path.basename(path).lower() != "cache":
        path = os.path.join(path, "cache")
    try:
        os.makedirs(path, exist_ok=True)
        _test_writable(path)
        _save({"cache_path": path})
        print(f"✅ Cache directory set to: {path}")
        print("⚠️  Restart the server for the change to take effect.")
        print("   Cache will be rebuilt automatically if the new directory is empty.")
        return True
    except Exception as e:
        print(f"❌ Cannot use cache path '{path}': {e}")
        return False


def reset_db_dir():
    """Reset db directory to the default (<server_root>/db)."""
    _save({"db_path": ""})
    print(f"✅ DB directory reset to default: {os.path.join(_HERE, 'db')}")
    print("⚠️  Restart the server for the change to take effect.")


def reset_cache_dir():
    """Reset cache directory to the default (<server_root>/cache)."""
    _save({"cache_path": ""})
    print(f"✅ Cache directory reset to default: {os.path.join(_HERE, 'cache')}")
    print("⚠️  Restart the server for the change to take effect.")


def get_hls_cache_dir(create: bool = True) -> str:
    """
    Return the configured HLS transcode cache directory (absolute path).
    Defaults to <cache_dir>/hls if not set in storage_config.json.
    This is where ffmpeg writes .ts segments and .m3u8 playlists.
    Pass create=False to read the path without creating the directory.
    """
    configured = _load().get("hls_cache_path")
    if configured:
        path = os.path.abspath(configured)
    else:
        # Default: a 'hls' subfolder inside the configured cache dir
        path = os.path.join(get_cache_dir(create=False), "hls")
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def set_hls_cache_dir(path: str) -> bool:
    """
    Validate, create, and persist a new HLS cache directory.
    Automatically appends an 'hls' subfolder so the user can point at a
    parent like C:\\Server\\cache and get C:\\Server\\cache\\hls.
    Returns True on success, False if the path is not writable.
    """
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.basename(path).lower() != "hls":
        path = os.path.join(path, "hls")
    try:
        os.makedirs(path, exist_ok=True)
        _test_writable(path)
        _save({"hls_cache_path": path})
        print(f"✅ HLS cache directory set to: {path}")
        print("⚠️  Restart the server for the change to take effect.")
        print("   Existing HLS transcodes in the old location will NOT be migrated.")
        return True
    except Exception as e:
        print(f"❌ Cannot use HLS cache path '{path}': {e}")
        return False


def reset_hls_cache_dir():
    """Reset HLS cache directory to the default (<cache_dir>/hls)."""
    _save({"hls_cache_path": ""})
    default = os.path.join(get_cache_dir(create=False), "hls")
    print(f"✅ HLS cache directory reset to default: {default}")
    print("⚠️  Restart the server for the change to take effect.")


def get_img_cache_dir(create: bool = True) -> str:
    """
    Return the configured image preview cache directory (absolute path).
    Defaults to <cache_dir>/img if not set in storage_config.json.
    This is where pyvips writes converted WebP/JPEG preview files.
    Pass create=False to read the path without creating the directory.
    """
    configured = _load().get("img_cache_path")
    if configured:
        path = os.path.abspath(configured)
    else:
        path = os.path.join(get_cache_dir(create=False), "img")
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def set_img_cache_dir(path: str) -> bool:
    """
    Validate, create, and persist a new image cache directory.
    Automatically appends an 'img' subfolder so the user can point at a
    parent like /srv/cloudinator/cache and get /srv/cloudinator/cache/img.
    Returns True on success, False if the path is not writable.
    """
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.basename(path).lower() != "img":
        path = os.path.join(path, "img")
    try:
        os.makedirs(path, exist_ok=True)
        _test_writable(path)
        _save({"img_cache_path": path})
        print(f"✅ Image cache directory set to: {path}")
        print("⚠️  Restart the server for the change to take effect.")
        print("   Existing image previews in the old location will NOT be migrated.")
        return True
    except Exception as e:
        print(f"❌ Cannot use image cache path '{path}': {e}")
        return False


def reset_img_cache_dir():
    """Reset image cache directory to the default (<cache_dir>/img)."""
    _save({"img_cache_path": ""})
    default = os.path.join(get_cache_dir(create=False), "img")
    print(f"✅ Image cache directory reset to default: {default}")
    print("⚠️  Restart the server for the change to take effect.")


def ensure_dirs():
    """
    Create db/, cache/, HLS cache, and image cache directories at their
    configured locations.  Call this ONCE at server startup (app.py /
    prod_server.py / dev_server.py) BEFORE importing database, file_index,
    or file_monitor.

    Never called by setup_storage.py or config.py — those tools only
    read/display/save paths, they must not create directories.
    """
    db_path = get_db_dir(create=True)
    cache_path = get_cache_dir(create=True)
    hls_path = get_hls_cache_dir(create=True)
    img_path = get_img_cache_dir(create=True)
    print(f"📂 DB dir ready:        {db_path}")
    print(f"📂 Cache dir ready:     {cache_path}")
    print(f"📂 HLS cache ready:     {hls_path}")
    print(f"📂 Image cache ready:   {img_path}")


def get_all_paths() -> dict:
    """Return a summary dict of all configured paths (useful for display).
    Does NOT create directories — read-only."""
    return {
        "db_dir": get_db_dir(create=False),
        "cache_dir": get_cache_dir(create=False),
        "hls_cache_dir": get_hls_cache_dir(create=False),
        "img_cache_dir": get_img_cache_dir(create=False),
        "default_db_dir": os.path.join(_HERE, "db"),
        "default_cache_dir": os.path.join(_HERE, "cache"),
        "default_hls_cache_dir": os.path.join(get_cache_dir(create=False), "hls"),
        "default_img_cache_dir": os.path.join(get_cache_dir(create=False), "img"),
    }


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _test_writable(path: str):
    """Raise OSError if `path` is not writable."""
    test = os.path.join(path, ".write_test")
    with open(test, "w") as f:
        f.write("test")
    os.remove(test)
