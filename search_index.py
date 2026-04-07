"""
search_index.py — SQLite-backed filename search index for CloudinatorFTP
-------------------------------------------------------------------------
Provides fast substring search over all files and folders under ROOT_DIR
without walking the filesystem on every query.

Architecture
------------
  Startup    → background crawler walks ROOT_DIR once, populates DB
               (sleeps 10 ms between dirs to avoid I/O saturation).
               Sets _ready=True when complete.
               On restart with an existing DB, skips the crawl immediately.
  Runtime    → file_monitor watchdog hooks call add/remove/rename_tree
               keeping the index current with zero filesystem walking.
  Query      → search() queries SQLite FTS5 or LIKE table in RAM/disk.
               While the crawler is still building, falls back to os.walk
               (same behaviour as before — temporary, one-time only).

Storage
-------
  DB file : <DB_DIR>/search_index.db
  Mode A  : FTS5 with trigram tokenizer  (SQLite ≥ 3.34, 2020-12-01)
             → native arbitrary substring matching via MATCH
  Mode B  : Regular table + name_lower index  (older SQLite / Termux)
             → LIKE '%query%' full-table scan, still far faster than os.walk

Threading
---------
  All writes use _write_lock (same pattern as database.py).
  The crawler is a daemon thread; reads are always safe in parallel.
  WAL mode allows concurrent reads while the crawler is writing.
"""

import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Optional

from paths import get_db_dir
from config import ROOT_DIR

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------

_DB_DIR = get_db_dir(create=False)
SEARCH_INDEX_PATH = os.path.join(_DB_DIR, "search_index.db")

_write_lock = threading.Lock()
_bootstrapped = False
_use_fts: Optional[bool] = None  # set at bootstrap; True = trigram FTS5, False = LIKE table


# ------------------------------------------------------------------
# Connection + lazy bootstrap
# ------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    global _bootstrapped, _use_fts
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(SEARCH_INDEX_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, faster than FULL
    conn.execute("PRAGMA cache_size=-8000")    # 8 MB page cache
    if not _bootstrapped:
        _bootstrapped = True
        _use_fts = _do_bootstrap(conn)
    return conn


def _do_bootstrap(conn) -> bool:
    """
    Create the files table.
    Tries FTS5 trigram first (SQLite ≥ 3.34); falls back to a plain
    indexed table if trigram is unavailable (e.g. older Termux builds).
    Returns True if FTS5 trigram was used, False for plain table.
    """
    use_fts = False
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe "
            "USING fts5(x, tokenize='trigram')"
        )
        conn.execute("DROP TABLE IF EXISTS _fts_probe")
        use_fts = True
    except Exception:
        pass

    if use_fts:
        conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS files USING fts5(
                name,
                rel_path,
                is_dir,
                parent_rel,
                tokenize='trigram'
            );
        """)
        print("✅ Search index: FTS5 trigram mode (fast substring search)")
    else:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                rel_path   TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                name_lower TEXT NOT NULL,
                is_dir     INTEGER NOT NULL DEFAULT 0,
                parent_rel TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_files_name_lower
                ON files(name_lower);
        """)
        print("✅ Search index: LIKE table mode (SQLite trigram unavailable)")

    return use_fts


# ------------------------------------------------------------------
# Search Index Manager
# ------------------------------------------------------------------


class SearchIndexManager:
    """
    Thread-safe manager for search_index.db.

    Write API  (called from file_monitor watchdog hooks):
        add(rel_path, name, is_dir)
        remove(rel_path)
        remove_tree(rel_path_prefix)
        rename_tree(old_prefix, new_prefix)

    Read API:
        search(query, max_results=100) → (results, from_index)
        get_stats() → dict

    Lifecycle:
        start_crawler()  — call once after init_file_monitor()
        stop()           — call on server shutdown
    """

    def __init__(self):
        self._ready = False
        self._crawler_thread: Optional[threading.Thread] = None
        self._stop_crawler = False

    # ------------------------------------------------------------------
    # Internal write helpers
    # ------------------------------------------------------------------

    def _rows_for_batch(self, entries: list) -> list:
        """
        Convert a list of (rel_path, name, is_dir) tuples into DB row tuples.
        Returns rows ready for executemany — format depends on _use_fts.
        """
        rows = []
        for rel_path, name, is_dir in entries:
            rel_path = rel_path.replace("\\", "/")
            parent_rel = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
            if _use_fts:
                rows.append((name, rel_path, "1" if is_dir else "0", parent_rel))
            else:
                rows.append((rel_path, name, name.lower(), 1 if is_dir else 0, parent_rel))
        return rows

    def _batch_insert(self, conn, entries: list):
        """
        Bulk-insert a batch of (rel_path, name, is_dir) tuples.
        Called from the crawler — conn is already open, no extra locking needed.
        """
        if not entries:
            return
        rows = self._rows_for_batch(entries)
        if _use_fts:
            conn.executemany(
                "INSERT INTO files(name, rel_path, is_dir, parent_rel) VALUES (?,?,?,?)",
                rows,
            )
        else:
            conn.executemany(
                "INSERT OR IGNORE INTO files"
                "(rel_path, name, name_lower, is_dir, parent_rel) VALUES (?,?,?,?,?)",
                rows,
            )

    # ------------------------------------------------------------------
    # Public write API — called from file_monitor watchdog hooks
    # ------------------------------------------------------------------

    def add(self, rel_path: str, name: str, is_dir: bool):
        """Insert or replace a single entry (file or folder)."""
        rel_path = rel_path.replace("\\", "/")
        parent_rel = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
        try:
            with _write_lock, _connect() as conn:
                if _use_fts:
                    # FTS5 virtual tables have no REPLACE — delete then insert
                    conn.execute("DELETE FROM files WHERE rel_path = ?", (rel_path,))
                    conn.execute(
                        "INSERT INTO files(name, rel_path, is_dir, parent_rel) "
                        "VALUES (?,?,?,?)",
                        (name, rel_path, "1" if is_dir else "0", parent_rel),
                    )
                else:
                    conn.execute(
                        "INSERT OR REPLACE INTO files"
                        "(rel_path, name, name_lower, is_dir, parent_rel) "
                        "VALUES (?,?,?,?,?)",
                        (rel_path, name, name.lower(), 1 if is_dir else 0, parent_rel),
                    )
        except Exception as e:
            print(f"⚠️  Search index add error for '{rel_path}': {e}")

    def remove(self, rel_path: str):
        """Remove a single entry."""
        rel_path = rel_path.replace("\\", "/")
        try:
            with _write_lock, _connect() as conn:
                conn.execute("DELETE FROM files WHERE rel_path = ?", (rel_path,))
        except Exception as e:
            print(f"⚠️  Search index remove error for '{rel_path}': {e}")

    def remove_tree(self, rel_path_prefix: str):
        """Remove a folder and every path beneath it."""
        rel_path_prefix = rel_path_prefix.replace("\\", "/")
        try:
            with _write_lock, _connect() as conn:
                conn.execute(
                    "DELETE FROM files WHERE rel_path = ? OR rel_path LIKE ?",
                    (rel_path_prefix, rel_path_prefix + "/%"),
                )
        except Exception as e:
            print(f"⚠️  Search index remove_tree error for '{rel_path_prefix}': {e}")

    def rename_tree(self, old_prefix: str, new_prefix: str):
        """
        Migrate all rel_paths when a folder is renamed or moved.
        FTS5 doesn't support UPDATE on indexed columns, so we fetch → delete → re-insert.
        The plain table does the same for consistency (avoids partial-update edge cases).
        """
        old_prefix = old_prefix.replace("\\", "/")
        new_prefix = new_prefix.replace("\\", "/")
        try:
            with _write_lock, _connect() as conn:
                # Fetch affected rows
                rows = conn.execute(
                    "SELECT name, rel_path, is_dir FROM files "
                    "WHERE rel_path = ? OR rel_path LIKE ?",
                    (old_prefix, old_prefix + "/%"),
                ).fetchall()

                if not rows:
                    return

                # Delete old entries
                conn.execute(
                    "DELETE FROM files WHERE rel_path = ? OR rel_path LIKE ?",
                    (old_prefix, old_prefix + "/%"),
                )

                # Re-insert with updated paths
                new_entries = []
                for r in rows:
                    suffix = r["rel_path"][len(old_prefix):]   # '' or '/child/...'
                    new_rel = new_prefix + suffix
                    new_entries.append((new_rel, r["name"], str(r["is_dir"]) == "1"))

                self._batch_insert(conn, new_entries)

        except Exception as e:
            print(f"⚠️  Search index rename_tree error '{old_prefix}'→'{new_prefix}': {e}")

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def search(self, query: str, ext_filter: list = None,
               limit: int = 500, offset: int = 0) -> tuple:
        """
        Paginated search. Returns (results, from_index, has_more).

        limit   — page size. Default 500.
        offset  — starting row for pagination. Default 0.
        has_more — True when there are more rows beyond this page.
        """
        if not self._ready:
            rows, has_more = self._walk_fallback(query, ext_filter, limit, offset)
            return rows, False, has_more
        try:
            rows, has_more = self._db_search(query, ext_filter, limit, offset)
            return rows, True, has_more
        except Exception as e:
            print(f"⚠️  Search index query error, falling back to os.walk: {e}")
            rows, has_more = self._walk_fallback(query, ext_filter, limit, offset)
            return rows, False, has_more

    def _db_search(self, query: str, ext_filter: list,
                   limit: int, offset: int) -> tuple:
        query_lower = query.lower()
        ext_list = [e.lstrip(".").lower() for e in (ext_filter or []) if e]

        # Fetch limit+1 to detect whether a next page exists.
        fetch = limit + 1

        with _connect() as conn:
            if _use_fts:
                # FTS5 trigram — match by name, then post-filter by ext in Python.
                # For pagination with ext-filtering we overfetch from the DB
                # (offset+fetch)*20 rows, apply the Python ext filter, then slice.
                clauses = []
                params: list = []
                if query_lower:
                    safe = '"' + query_lower.replace('"', '""') + '"'
                    clauses.append("files MATCH ?")
                    params.append(safe)
                if ext_list:
                    clauses.append("is_dir = '0'")
                where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
                overfetch = (offset + fetch) * (20 if ext_list else 1)
                raw_rows = conn.execute(
                    f"SELECT name, rel_path, is_dir FROM files {where} LIMIT ?",
                    params + [overfetch],
                ).fetchall()

                if ext_list:
                    raw_rows = [
                        r for r in raw_rows
                        if os.path.splitext(r["name"])[1].lstrip(".").lower() in ext_list
                    ]
                rows = raw_rows[offset: offset + fetch]

            else:
                # Plain table — push offset/limit into SQL directly.
                clauses = []
                params = []
                if query_lower:
                    clauses.append("name_lower LIKE ?")
                    params.append(f"%{query_lower}%")
                if ext_list:
                    ext_sql = " OR ".join("name_lower LIKE ?" for _ in ext_list)
                    clauses.append(f"({ext_sql})")
                    params.extend(f"%.{e}" for e in ext_list)
                    clauses.append("is_dir = 0")
                where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
                params += [fetch, offset]
                rows = conn.execute(
                    f"SELECT name, rel_path, is_dir FROM files {where} "
                    f"LIMIT ? OFFSET ?",
                    params,
                ).fetchall()

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        # Resolve stat for each matched row — only hits matched files, not the whole tree
        results = []
        for row in rows:
            name     = row["name"]
            rel_path = row["rel_path"]
            is_dir   = str(row["is_dir"]) == "1" if _use_fts else bool(row["is_dir"])
            full_path = os.path.join(ROOT_DIR, rel_path)
            try:
                st = os.stat(full_path)
                size     = 0 if is_dir else st.st_size
                modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            except OSError:
                continue  # deleted since last index update — skip silently
            _, ext = os.path.splitext(name)
            file_type = "folder" if is_dir else (ext[1:].upper() if ext else "FILE")
            results.append({
                "name":       name,
                "path":       rel_path,
                "type":       file_type,
                "is_dir":     is_dir,
                "size":       size,
                "modified":   modified,
                "match_type": "name",
            })

        return results, has_more

    def _walk_fallback(self, query: str, ext_filter: list = None,
                       limit: int = 500, offset: int = 0) -> tuple:
        """
        os.walk fallback used on first boot while the crawler is still building.
        Supports the same limit/offset pagination so the API shape is identical.
        """
        query_lower = query.lower()
        ext_list = [e.lstrip(".").lower() for e in (ext_filter or []) if e]
        collected = []
        # Collect offset+limit+1 to detect has_more without walking the entire tree
        need = offset + limit + 1

        for root, dirs, files in os.walk(ROOT_DIR):
            if len(collected) >= need:
                break
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            rel_path = os.path.relpath(root, ROOT_DIR).replace("\\", "/")
            if rel_path == ".":
                rel_path = ""

            if not ext_list:
                for dirname in dirs:
                    if query_lower and query_lower not in dirname.lower():
                        continue
                    folder_path = (rel_path + "/" + dirname) if rel_path else dirname
                    try:
                        st = os.stat(os.path.join(root, dirname))
                        collected.append({
                            "name": dirname, "path": folder_path,
                            "type": "folder", "is_dir": True, "size": 0,
                            "modified": datetime.fromtimestamp(st.st_mtime).strftime(
                                "%Y-%m-%d %H:%M:%S"),
                            "match_type": "name",
                        })
                    except OSError:
                        continue
                    if len(collected) >= need:
                        break

            for filename in files:
                if len(collected) >= need:
                    break
                if filename.startswith("."):
                    continue
                if ext_list:
                    _, fext = os.path.splitext(filename)
                    if fext.lstrip(".").lower() not in ext_list:
                        continue
                if query_lower and query_lower not in filename.lower():
                    continue
                file_path = (rel_path + "/" + filename) if rel_path else filename
                try:
                    st = os.stat(os.path.join(root, filename))
                    _, ext = os.path.splitext(filename)
                    collected.append({
                        "name": filename, "path": file_path,
                        "type": ext[1:].upper() if ext else "FILE",
                        "is_dir": False, "size": st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).strftime(
                            "%Y-%m-%d %H:%M:%S"),
                        "match_type": "name",
                    })
                except OSError:
                    continue

        has_more = len(collected) > offset + limit
        page = collected[offset: offset + limit]
        return page, has_more

    # ------------------------------------------------------------------
    # Background crawler
    # ------------------------------------------------------------------

    def start_crawler(self):
        """
        Launch the background crawler daemon thread.
        Call once, immediately after init_file_monitor() so watchdog hooks
        are already active before the crawl completes.
        """
        if self._crawler_thread and self._crawler_thread.is_alive():
            return
        self._stop_crawler = False
        self._crawler_thread = threading.Thread(
            target=self._crawl,
            daemon=True,
            name="search-index-crawler",
        )
        self._crawler_thread.start()
        print("🔍 Search index: background crawler started")

    def _crawl(self):
        """
        Walk ROOT_DIR once, inserting entries in per-directory batches.
        Sleeps 10 ms between directories to avoid I/O saturation.
        On restart, detects an existing DB and skips the crawl entirely.
        Sets _ready=True on completion.
        """
        print("🔍 Search index: crawling filesystem...")
        start = time.time()

        try:
            # Trigger bootstrap (creates table if needed)
            with _connect():
                pass

            # If DB already has data (restart case), mark ready and return
            with _connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()
                existing = row["c"] if row else 0

            if existing > 0:
                elapsed = time.time() - start
                print(
                    f"✅ Search index: existing DB loaded "
                    f"({existing:,} entries, {elapsed:.1f}s)"
                )
                self._ready = True
                return

            # Fresh crawl — walk ROOT_DIR
            dir_count  = 0
            file_count = 0

            for root, dirs, files in os.walk(ROOT_DIR):
                if self._stop_crawler:
                    print("🛑 Search index: crawler stopped early")
                    return

                # Skip hidden directories (mirrors _full_walk in file_monitor)
                dirs[:] = [d for d in dirs if not d.startswith(".")]

                rel_root = os.path.relpath(root, ROOT_DIR).replace("\\", "/")
                if rel_root == ".":
                    rel_root = ""

                batch = []

                # The directory itself (skip root — it has no name to search by)
                if rel_root:
                    batch.append((rel_root, os.path.basename(root), True))
                    dir_count += 1

                # All non-hidden files in this directory
                for fname in files:
                    if fname.startswith("."):
                        continue
                    frel = (
                        (rel_root + "/" + fname) if rel_root else fname
                    )
                    batch.append((frel, fname, False))
                    file_count += 1

                if batch:
                    with _write_lock, _connect() as conn:
                        self._batch_insert(conn, batch)

                # Progress every 5 000 directories
                if dir_count > 0 and dir_count % 5000 == 0:
                    print(
                        f"🔍 Search index: {dir_count:,} dirs, "
                        f"{file_count:,} files indexed so far…"
                    )

                # Yield — 10 ms sleep keeps this from saturating disk I/O
                time.sleep(0.01)

            elapsed = time.time() - start
            print(
                f"✅ Search index ready: "
                f"{dir_count:,} dirs + {file_count:,} files "
                f"indexed in {elapsed:.1f}s"
            )
            self._ready = True

        except Exception as e:
            print(f"❌ Search index crawler error: {e}")
            # Don't set _ready — callers fall back to os.walk until fixed

    # ------------------------------------------------------------------
    # Stats + shutdown
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return summary stats for the /api/status or admin endpoints."""
        try:
            with _connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()
                total = row["c"] if row else 0
            return {
                "ready":         self._ready,
                "total_entries": total,
                "mode":          "fts5_trigram" if _use_fts else "like_table",
                "db_path":       SEARCH_INDEX_PATH,
            }
        except Exception:
            return {"ready": self._ready, "total_entries": 0}

    def stop(self):
        """Signal the crawler to stop on server shutdown."""
        self._stop_crawler = True


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

search_index_manager = SearchIndexManager()