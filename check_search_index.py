#!/usr/bin/env python3
"""
check_search_index.py - read-only consistency check of cache/db search_index.db
-------------------------------------------------------------------------------
Usage (run from the CloudinatorFTP folder, server can stay running):

    python check_search_index.py                      # checks Days_of_Thunder.mp3
    python check_search_index.py "some file name.ext" # checks another file

Answers: is the file in files_meta? in the FTS table? does the stored path
exist on disk? Plus a sample test of how many files_meta names the FTS table
cannot find. Only SELECTs are executed (PRAGMA query_only=ON).
"""
import os
import random
import sqlite3
import sys

from config import ROOT_DIR
from paths import get_db_dir

DB = os.path.join(get_db_dir(create=False), "search_index.db")
needle = sys.argv[1] if len(sys.argv) > 1 else "Days_of_Thunder.mp3"
nl = needle.lower()

print(f"DB: {DB}  ({os.path.getsize(DB) / 1048576:,.0f} MB)")
print(f"ROOT_DIR: {ROOT_DIR}")
con = sqlite3.connect(DB, timeout=30)
con.execute("PRAGMA query_only=ON")
q = lambda sql, *a: con.execute(sql, a).fetchall()

n_fts = q("SELECT COUNT(*) FROM files")[0][0]
n_meta = q("SELECT COUNT(*) FROM files_meta")[0][0]
print(f"\nrows: files(FTS)={n_fts:,}  files_meta={n_meta:,}  "
      f"difference={n_meta - n_fts:+,}")

print(f"\n--- files_meta rows with name = {needle!r} (case-insensitive) ---")
meta = q("SELECT rel_path FROM files_meta WHERE name_lower = ?", nl)
for (rp,) in meta:
    full = os.path.join(ROOT_DIR, rp)
    try:
        st = os.stat(full)
        print(f"  {rp}\n     on disk: YES ({st.st_size:,} bytes)")
    except OSError as e:
        print(f"  {rp}\n     on disk: NO -> os.stat failed: {e!r}")
if not meta:
    print("  (none)")

print("\n--- FTS table ---")
try:
    hits = q("SELECT rel_path FROM files WHERE files MATCH ?", '"' + nl.replace('"', '""') + '"')
    print(f"  MATCH finds {len(hits)} row(s)")
    for (rp,) in hits[:5]:
        print("   ", rp)
except Exception as e:
    print("  MATCH error:", e)
exact = q("SELECT rel_path FROM files WHERE name = ? COLLATE NOCASE", needle)
print(f"  exact-name scan finds {len(exact)} row(s)")

print("\n--- sample: can FTS find 300 random files_meta names? ---")
rows = q("SELECT rel_path, name_lower FROM files_meta WHERE is_dir=0 AND length(name_lower)>=3 "
         "ORDER BY random() LIMIT 300")
miss = []
for rp, name in rows:
    hit = q("SELECT 1 FROM files WHERE files MATCH ? AND rel_path = ? LIMIT 1",
            '"' + name.replace('"', '""') + '"', rp)
    if not hit:
        miss.append(rp)
print(f"  FTS missed {len(miss)} of {len(rows)} sampled")
for rp in miss[:8]:
    print("   missing:", rp)

print("\nVerdict hint:")
if meta and not hits and not exact:
    print("  File is in files_meta but NOT in the FTS table -> index inconsistent -> rebuild.")
elif meta and (hits or exact):
    print("  File IS in FTS; if search shows nothing, check the 'on disk' line above (stat failure).")
elif not meta:
    print("  File is not in the index at all (also not in files_meta).")
if miss:
    print(f"  {len(miss)}/{len(rows)} sampled names are missing from FTS -> index inconsistent -> rebuild.")