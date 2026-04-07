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
    Create the search tables.

    Always creates files_meta — a plain indexed table used for COUNT(*),
    ext-filter queries, and the non-FTS fallback path.  Reliable, correct
    SQL semantics with no FTS quirks.

    Also tries to create the FTS5 trigram virtual table (SQLite >= 3.34)
    for fast name-substring MATCH queries.  If unavailable, name search
    falls back to LIKE on files_meta.

    Returns True if FTS5 trigram is available, False otherwise.
    """
    # files_meta: always present, plain SQL, ext/count queries go here
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files_meta (
            rel_path   TEXT PRIMARY KEY,
            name_lower TEXT NOT NULL,
            ext_lower  TEXT NOT NULL DEFAULT \'\',
            is_dir     INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_meta_ext_lower
            ON files_meta(ext_lower, is_dir);
        CREATE INDEX IF NOT EXISTS idx_meta_name_lower
            ON files_meta(name_lower);
    """)

    use_fts = False
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe "
            "USING fts5(x, tokenize=\'trigram\')"
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
                tokenize=\'trigram\'
            );
        """)
        print("✅ Search index: FTS5 trigram + files_meta (fast name search + exact counts)")
    else:
        # No FTS5 — files_meta handles everything via LIKE
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                rel_path   TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                name_lower TEXT NOT NULL,
                is_dir     INTEGER NOT NULL DEFAULT 0,
                parent_rel TEXT NOT NULL DEFAULT \'\'
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

    def _rows_for_batch(self, entries: list) -> tuple:
        """
        Convert a list of (rel_path, name, is_dir) tuples into two row lists:
          fts_rows  — for the FTS5/plain files table
          meta_rows — for files_meta (always populated, used for COUNT/ext queries)
        """
        fts_rows = []
        meta_rows = []
        for rel_path, name, is_dir in entries:
            rel_path = rel_path.replace("\\", "/")
            parent_rel = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
            _, _ext = os.path.splitext(name)
            ext_lower = _ext.lstrip(".").lower()
            name_lower = name.lower()
            if _use_fts:
                fts_rows.append((name, rel_path, "1" if is_dir else "0", parent_rel))
            else:
                fts_rows.append((rel_path, name, name_lower, 1 if is_dir else 0, parent_rel))
            meta_rows.append((rel_path, name_lower, ext_lower, 1 if is_dir else 0))
        return fts_rows, meta_rows

    def _batch_insert(self, conn, entries: list):
        """
        Bulk-insert a batch of (rel_path, name, is_dir) tuples into both tables.
        Called from the crawler — conn is already open, no extra locking needed.
        """
        if not entries:
            return
        fts_rows, meta_rows = self._rows_for_batch(entries)
        if _use_fts:
            conn.executemany(
                "INSERT INTO files(name, rel_path, is_dir, parent_rel) VALUES (?,?,?,?)",
                fts_rows,
            )
        else:
            conn.executemany(
                "INSERT OR IGNORE INTO files"
                "(rel_path, name, name_lower, is_dir, parent_rel) VALUES (?,?,?,?,?)",
                fts_rows,
            )
        conn.executemany(
            "INSERT OR IGNORE INTO files_meta(rel_path, name_lower, ext_lower, is_dir)"
            " VALUES (?,?,?,?)",
            meta_rows,
        )

    # ------------------------------------------------------------------
    # Public write API — called from file_monitor watchdog hooks
    # ------------------------------------------------------------------

    def add(self, rel_path: str, name: str, is_dir: bool):
        """Insert or replace a single entry in both files and files_meta."""
        rel_path = rel_path.replace("\\", "/")
        parent_rel = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
        _, _ext = os.path.splitext(name)
        ext_lower = _ext.lstrip(".").lower()
        name_lower = name.lower()
        try:
            with _write_lock, _connect() as conn:
                if _use_fts:
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
                        (rel_path, name, name_lower, 1 if is_dir else 0, parent_rel),
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO files_meta"
                    "(rel_path, name_lower, ext_lower, is_dir) VALUES (?,?,?,?)",
                    (rel_path, name_lower, ext_lower, 1 if is_dir else 0),
                )
        except Exception as e:
            print(f"⚠️  Search index add error for '{rel_path}': {e}")

    def remove(self, rel_path: str):
        """Remove a single entry from both tables."""
        rel_path = rel_path.replace("\\", "/")
        try:
            with _write_lock, _connect() as conn:
                conn.execute("DELETE FROM files WHERE rel_path = ?", (rel_path,))
                conn.execute("DELETE FROM files_meta WHERE rel_path = ?", (rel_path,))
        except Exception as e:
            print(f"⚠️  Search index remove error for '{rel_path}': {e}")

    def remove_tree(self, rel_path_prefix: str):
        """Remove a folder and every path beneath it from both tables."""
        rel_path_prefix = rel_path_prefix.replace("\\", "/")
        try:
            with _write_lock, _connect() as conn:
                args = (rel_path_prefix, rel_path_prefix + "/%")
                conn.execute(
                    "DELETE FROM files WHERE rel_path = ? OR rel_path LIKE ?", args
                )
                conn.execute(
                    "DELETE FROM files_meta WHERE rel_path = ? OR rel_path LIKE ?", args
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

                # Migrate files_meta in one shot
                meta_rows_old = conn.execute(
                    "SELECT rel_path, name_lower, ext_lower, is_dir FROM files_meta "
                    "WHERE rel_path = ? OR rel_path LIKE ?",
                    (old_prefix, old_prefix + "/%"),
                ).fetchall()
                if meta_rows_old:
                    conn.execute(
                        "DELETE FROM files_meta WHERE rel_path = ? OR rel_path LIKE ?",
                        (old_prefix, old_prefix + "/%"),
                    )
                    conn.executemany(
                        "INSERT OR REPLACE INTO files_meta"
                        "(rel_path, name_lower, ext_lower, is_dir) VALUES (?,?,?,?)",
                        [
                            (new_prefix + r["rel_path"][len(old_prefix):],
                             r["name_lower"], r["ext_lower"], r["is_dir"])
                            for r in meta_rows_old
                        ],
                    )

        except Exception as e:
            print(f"⚠️  Search index rename_tree error '{old_prefix}'→'{new_prefix}': {e}")

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def count(self, query: str, ext_filter: list = None) -> int:
        """
        Return the exact total number of matching entries.
        Always queries files_meta — a plain indexed table with correct SQL
        semantics, no FTS quirks.  Sub-millisecond on indexed columns.
        Returns -1 if the index isn't ready yet.
        """
        if not self._ready:
            return -1
        try:
            query_lower = query.lower()
            ext_list = [e.lstrip(".").lower() for e in (ext_filter or []) if e]
            clauses: list = []
            params: list = []
            if query_lower:
                clauses.append("name_lower LIKE ?")
                params.append(f"%{query_lower}%")
            if ext_list:
                ext_sql = " OR ".join("ext_lower = ?" for _ in ext_list)
                clauses.append(f"({ext_sql})")
                params.extend(ext_list)
                clauses.append("is_dir = 0")
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            with _connect() as conn:
                row = conn.execute(
                    f"SELECT COUNT(*) AS c FROM files_meta {where}", params
                ).fetchone()
            return row["c"] if row else 0
        except Exception as e:
            print(f"⚠️  Search index count error: {e}")
            return -1
        try:
            query_lower = query.lower()
            ext_list = [e.lstrip(".").lower() for e in (ext_filter or []) if e]
            with _connect() as conn:
                if _use_fts:
                    clauses: list = []
                    params: list = []
                    if query_lower:
                        safe = '"' + query_lower.replace('"', '""') + '"'
                        clauses.append("files MATCH ?")
                        params.append(safe)
                        if ext_list:
                            ext_likes = " OR ".join("name LIKE ?" for _ in ext_list)
                            clauses.append(f"({ext_likes})")
                            params.extend(f"%.{e}" for e in ext_list)
                            clauses.append("is_dir = '0'")
                    else:
                        if ext_list:
                            ext_likes = " OR ".join("name LIKE ?" for _ in ext_list)
                            clauses.append(f"({ext_likes})")
                            params.extend(f"%.{e}" for e in ext_list)
                            clauses.append("is_dir = '0'")
                    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
                    row = conn.execute(
                        f"SELECT COUNT(*) AS c FROM files {where}", params
                    ).fetchone()
                else:
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
                    row = conn.execute(
                        f"SELECT COUNT(*) AS c FROM files {where}", params
                    ).fetchone()
            return row["c"] if row else 0
        except Exception as e:
            print(f"⚠️  Search index count error: {e}")
            return -1


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
        """
        Three strategies, each using the right table for the job:

        A) Name + ext   -> FTS5 MATCH on `files` JOIN files_meta for ext (exact index)
        B) Name only    -> FTS5 MATCH on `files`, no ext filter
        C) Ext only     -> files_meta ext_lower IN (...) — exact indexed column, always correct

        Plain-table mode: files_meta handles everything via LIKE + ext_lower.
        """
        query_lower = query.lower()
        ext_list = [e.lstrip(".").lower() for e in (ext_filter or []) if e]
        fetch = limit + 1  # fetch limit+1 to detect has_more

        with _connect() as conn:
            if _use_fts:
                if query_lower and ext_list:
                    # Strategy A: MATCH + ext exact match via files_meta JOIN
                    safe = '"' + query_lower.replace('"', '""') + '"'
                    ext_ph = ",".join("?" for _ in ext_list)
                    rows = conn.execute(
                        "SELECT f.name, f.rel_path, f.is_dir FROM files f "
                        "JOIN files_meta m ON m.rel_path = f.rel_path "
                        "WHERE f.files MATCH ? "
                        f"AND m.ext_lower IN ({ext_ph}) "
                        "AND m.is_dir = 0 "
                        "LIMIT ? OFFSET ?",
                        [safe] + ext_list + [fetch, offset],
                    ).fetchall()

                elif query_lower:
                    # Strategy B: MATCH only
                    safe = '"' + query_lower.replace('"', '""') + '"'
                    rows = conn.execute(
                        "SELECT name, rel_path, is_dir FROM files "
                        "WHERE files MATCH ? LIMIT ? OFFSET ?",
                        [safe, fetch, offset],
                    ).fetchall()

                else:
                    # Strategy C: ext-only via files_meta — always correct, indexed
                    ext_ph = ",".join("?" for _ in ext_list)
                    rows = conn.execute(
                        "SELECT rel_path, is_dir FROM files_meta "
                        f"WHERE ext_lower IN ({ext_ph}) AND is_dir = 0 "
                        "LIMIT ? OFFSET ?",
                        ext_list + [fetch, offset],
                    ).fetchall()

            else:
                # Plain table — files_meta handles everything
                clauses: list = []
                params: list = []
                if query_lower:
                    clauses.append("name_lower LIKE ?")
                    params.append(f"%{query_lower}%")
                if ext_list:
                    ext_ph = ",".join("?" for _ in ext_list)
                    clauses.append(f"ext_lower IN ({ext_ph})")
                    params.extend(ext_list)
                    clauses.append("is_dir = 0")
                where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
                params += [fetch, offset]
                rows = conn.execute(
                    f"SELECT rel_path, is_dir FROM files_meta {where} "
                    f"LIMIT ? OFFSET ?",
                    params,
                ).fetchall()

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        results = []
        for row in rows:
            rel_path = row["rel_path"]
            name = rel_path.rsplit("/", 1)[-1] if "/" in rel_path else rel_path
            is_dir_val = row["is_dir"]
            is_dir = (str(is_dir_val) == "1") if isinstance(is_dir_val, str) else bool(is_dir_val)
            full_path = os.path.join(ROOT_DIR, rel_path)
            try:
                st = os.stat(full_path)
                size     = 0 if is_dir else st.st_size
                modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            except OSError:
                continue
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

            # Decide whether we need a fresh crawl.
            #
            # files_meta is the authoritative table — it always reflects the
            # filesystem.  We NEVER backfill it from the FTS5 table because the
            # FTS5 table may itself be incomplete (the bug that caused wrong counts).
            # The filesystem is always the ground truth.
            #
            # Restart cases:
            #   A) files_meta populated and matches files  → ready, skip crawl
            #   B) files_meta empty / behind               → fresh crawl (rebuilds both)
            #   C) files empty (brand new DB)              → fresh crawl
            with _connect() as conn:
                fts_count  = conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
                meta_count = conn.execute("SELECT COUNT(*) AS c FROM files_meta").fetchone()["c"]

            # Case A: both tables populated and in sync → ready immediately
            if fts_count > 0 and meta_count > 0 and meta_count >= fts_count * 0.95:
                elapsed = time.time() - start
                print(
                    f"✅ Search index: loaded from disk "
                    f"(files={fts_count:,}  meta={meta_count:,}, {elapsed:.1f}s)"
                )
                self._ready = True
                return

            # Case B / C: crawl the filesystem — single source of truth
            if meta_count < fts_count * 0.95:
                print(
                    f"🔄 Search index: files_meta incomplete "
                    f"({meta_count:,} vs {fts_count:,}) — rebuilding from filesystem"
                )
            else:
                print("🔍 Search index: fresh crawl starting…")

            # Wipe both tables so we start clean (avoids stale partial data)
            with _write_lock, _connect() as conn:
                if _use_fts:
                    conn.execute("DELETE FROM files")
                else:
                    conn.execute("DELETE FROM files")
                conn.execute("DELETE FROM files_meta")

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

                # The directory itself (skip root — no name to search)
                if rel_root:
                    batch.append((rel_root, os.path.basename(root), True))
                    dir_count += 1

                # All non-hidden files in this directory
                for fname in files:
                    if fname.startswith("."):
                        continue
                    frel = (rel_root + "/" + fname) if rel_root else fname
                    batch.append((frel, fname, False))
                    file_count += 1

                if batch:
                    try:
                        with _write_lock, _connect() as conn:
                            self._batch_insert(conn, batch)
                    except Exception as be:
                        # Batch failed (e.g. encoding issue in one filename).
                        # Fall back to entry-by-entry so one bad file never
                        # silently drops the whole directory.
                        print(f"⚠️  Search index batch error in '{rel_root}': {be} — retrying entry-by-entry")
                        for entry in batch:
                            try:
                                with _write_lock, _connect() as conn:
                                    self._batch_insert(conn, [entry])
                            except Exception:
                                pass  # skip truly unindexable entries

                # Progress log every 5 000 directories
                if dir_count > 0 and dir_count % 5000 == 0:
                    print(
                        f"🔍 Search index: {dir_count:,} dirs, "
                        f"{file_count:,} files indexed…"
                    )

                time.sleep(0.01)  # yield — prevents I/O saturation

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