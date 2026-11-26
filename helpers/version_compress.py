"""
helpers/version_compress.py - the READ-ONLY queries and the report of the object compressor
(5.47, release B of VERSION_COMPRESSION_PLAN.md).

The engine (`version_engine.py`, `Engine.compress_object` and friends) does the compressing,
the sweeping and the decompressing; this leaf only holds what can be written without any file
or thread: which objects are next in line, and the numbers and text of
`./manage.sh version-manage compress --status`.

States of an object's `compress_state` column (bookkeeping, never what a reader goes by):

    pending   a raw object that has not been looked at yet (every existing object at migration)
    done      compressed: the `.zst` is published and verified, the raw copy may still be on disk
              (it is removed by the sweep a few minutes later)
    swept     compressed and the raw copy is gone: the final state
    skip      stays raw on purpose: too small, already-compressed data, or no real saving
    failed    something was wrong with the object (it failed its own SHA-256, or the round trip
              did not match): never touched again, logged as an error

Rules of this file: standard library only, a leaf (smoke rule 7b), takes the database
connection from its caller, starts no thread and no event loop, NO asyncio. It works on a
schema-1 database too (no compression columns yet: everything counts as raw / pending).
"""

import sqlite3

STATES = ("pending", "done", "swept", "skip", "failed")


def has_compression_columns(conn: sqlite3.Connection) -> bool:
    """True when the `objects` table already has the schema-2 columns."""
    return any(
        row[1] == "compress_state" for row in conn.execute("PRAGMA table_info(objects)")
    )


def candidate_batch(conn: sqlite3.Connection, cursor: int, limit: int, min_size: int):
    """The next raw objects to compress after row `cursor`: [(rowid, sha256, size)], oldest
    row first. Orphaned objects (the GC is about to remove them) and objects below `min_size`
    are not candidates. An empty list means the end of the table: the caller wraps to 0.
    """
    return conn.execute(
        "SELECT rowid, sha256, size FROM objects "
        "WHERE rowid > ? AND codec = 'raw' AND compress_state = 'pending' "
        "AND orphaned_since IS NULL AND size >= ? ORDER BY rowid LIMIT ?",
        (int(cursor), int(min_size), int(limit)),
    ).fetchall()


def mark_small_objects_skipped(conn: sqlite3.Connection, min_size: int) -> int:
    """Objects below `min_size` are never compressed: say so once instead of leaving them
    'pending' for ever. Returns the number of rows changed (the caller holds the write lock and
    commits)."""
    cur = conn.execute(
        "UPDATE objects SET compress_state = 'skip' "
        "WHERE codec = 'raw' AND compress_state = 'pending' AND size < ?",
        (int(min_size),),
    )
    return cur.rowcount


def status_counts(conn: sqlite3.Connection, min_size: int = 4096) -> dict:
    """The numbers behind `compress --status`. Works on schema 1 and schema 2."""
    total_n, total_b = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM objects"
    ).fetchone()
    orphan_n, orphan_b = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM objects WHERE orphaned_since IS NOT NULL"
    ).fetchone()
    out = {
        "schema2": has_compression_columns(conn),
        "objects": total_n,
        "raw_bytes": total_b,
        "orphaned": orphan_n,
        "orphaned_bytes": orphan_b,
        "states": {s: {"objects": 0, "raw_bytes": 0} for s in STATES},
        "zstd_objects": 0,
        "zstd_raw_bytes": 0,
        "zstd_stored_bytes": 0,
        "levels": {},
        "pending_eligible": 0,
        "pending_eligible_bytes": 0,
        "raw_copies_waiting": 0,  # compressed, raw copy not swept yet
        # 5.47.1: objects stored as a delta against another object (schema 3)
        "delta_objects": 0,
        "delta_raw_bytes": 0,
        "delta_stored_bytes": 0,
        "delta_bases": 0,
    }
    if not out["schema2"]:
        # nothing was ever compressed; every object is raw and waiting
        out["states"]["pending"] = {"objects": total_n, "raw_bytes": total_b}
        elig = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM objects "
            "WHERE orphaned_since IS NULL AND size >= ?",
            (int(min_size),),
        ).fetchone()
        out["pending_eligible"], out["pending_eligible_bytes"] = elig
        return out

    for state, n, b in conn.execute(
        "SELECT compress_state, COUNT(*), COALESCE(SUM(size), 0) FROM objects "
        "GROUP BY compress_state"
    ):
        out["states"].setdefault(state, {"objects": 0, "raw_bytes": 0})
        out["states"][state] = {"objects": n, "raw_bytes": b}
    zn, zraw, zstored = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(size), 0), COALESCE(SUM(COALESCE(stored_size, size)), 0) "
        "FROM objects WHERE codec = 'zstd'"
    ).fetchone()
    out["zstd_objects"], out["zstd_raw_bytes"], out["zstd_stored_bytes"] = (
        zn,
        zraw,
        zstored,
    )
    out["levels"] = {
        lv: n
        for lv, n in conn.execute(
            "SELECT codec_level, COUNT(*) FROM objects WHERE codec = 'zstd' "
            "GROUP BY codec_level ORDER BY codec_level"
        )
    }
    out["pending_eligible"], out["pending_eligible_bytes"] = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM objects "
        "WHERE codec = 'raw' AND compress_state = 'pending' "
        "AND orphaned_since IS NULL AND size >= ?",
        (int(min_size),),
    ).fetchone()
    out["raw_copies_waiting"] = out["states"].get("done", {}).get("objects", 0)
    if any(row[1] == "base_sha" for row in conn.execute("PRAGMA table_info(objects)")):
        dn, draw, dstored = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(size), 0), "
            "COALESCE(SUM(COALESCE(stored_size, size)), 0) "
            "FROM objects WHERE base_sha IS NOT NULL"
        ).fetchone()
        out["delta_objects"], out["delta_raw_bytes"], out["delta_stored_bytes"] = (
            dn,
            draw,
            dstored,
        )
        out["delta_bases"] = conn.execute(
            "SELECT COUNT(DISTINCT base_sha) FROM objects WHERE base_sha IS NOT NULL"
        ).fetchone()[0]
    return out


def _fmt_bytes(n) -> str:
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"  # pragma: no cover - the loop always returns


def _pct(part, whole) -> float:
    return (100.0 * part / whole) if whole else 0.0


def format_status(
    counts: dict, meta: dict, settings: dict, zstd_version: str = ""
) -> str:
    """The readable `compress --status` text. `meta` is the engine_metadata rows
    (compress_running / compress_last / compress_cursor), `settings` the current values of
    the five config keys."""
    c = counts
    st = c["states"]
    lines = ["Version Engine object compression", "=" * 40]
    lines.append(
        f"  setting : VERSION_COMPRESSION_ENABLED = {settings.get('enabled')}, "
        f"level {settings.get('level')}, min saving {settings.get('min_saving')} %, "
        f"busy {settings.get('busy')} %, idle look every {settings.get('interval')} s"
    )
    lines.append(f"  zstd    : {zstd_version or 'NOT AVAILABLE in this Python'}")
    running = meta.get("compress_running") == "1"
    enabled = bool(settings.get("enabled"))
    if running and enabled:
        thread = "ve-compress reported running (the engine is up and compression is on)"
    elif running:
        thread = (
            "ve-compress reported running, but the setting is now OFF: it stops at the next "
            "restart of the Version Engine"
        )
    elif enabled:
        thread = (
            "the setting is ON but ve-compress has not reported running: the Version Engine is "
            "stopped, or has not been restarted since the setting was changed (the setting is "
            "only read when the engine starts)"
        )
    else:
        thread = (
            "ve-compress is not running (compression is switched off in the settings)"
        )
    lines.append("  thread  : " + thread)
    if meta.get("compress_last"):
        lines.append(f"  last    : {meta['compress_last']}")
    lines.append("")
    if not c["schema2"]:
        lines.append(
            "  The database is still schema 1 (nothing was ever compressed); start the new "
            "release once to migrate it."
        )
    lines.append(
        f"  objects : {c['objects']:,} listed, {_fmt_bytes(c['raw_bytes'])} raw "
        f"({c['orphaned']:,} orphaned, waiting for the GC)"
    )
    lines.append(
        f"  states  : pending {st['pending']['objects']:,} "
        f"({_fmt_bytes(st['pending']['raw_bytes'])}), "
        f"compressed {c['zstd_objects']:,} (raw copy still on disk: "
        f"{c['raw_copies_waiting']:,}), skip {st['skip']['objects']:,}, "
        f"failed {st['failed']['objects']:,}"
    )
    lines.append(
        f"  backlog : {c['pending_eligible']:,} object(s) of "
        f"{_fmt_bytes(c['pending_eligible_bytes'])} still to look at"
    )
    if c["zstd_objects"]:
        saved = c["zstd_raw_bytes"] - c["zstd_stored_bytes"]
        lines.append(
            f"  result  : {c['zstd_objects']:,} compressed object(s): "
            f"{_fmt_bytes(c['zstd_raw_bytes'])} raw -> {_fmt_bytes(c['zstd_stored_bytes'])} "
            f"on disk ({_pct(c['zstd_stored_bytes'], c['zstd_raw_bytes']):.1f} % of raw), "
            f"{_fmt_bytes(saved)} saved once the raw copies are gone"
        )
        if c["levels"]:
            lines.append(
                "  levels  : "
                + ", ".join(
                    f"{'?' if lv is None else lv}: {n:,}"
                    for lv, n in sorted(
                        c["levels"].items(), key=lambda kv: (kv[0] is None, kv[0] or 0)
                    )
                )
            )
    if c["delta_objects"]:
        lines.append(
            f"  deltas  : {c['delta_objects']:,} object(s) are stored as a delta against "
            f"{c['delta_bases']:,} base object(s) (a base stays on disk as long as a delta "
            f"needs it): {_fmt_bytes(c['delta_raw_bytes'])} raw -> "
            f"{_fmt_bytes(c['delta_stored_bytes'])} on disk "
            f"({_pct(c['delta_stored_bytes'], c['delta_raw_bytes']):.1f} % of raw)"
        )
    if settings.get("delta_enabled") is not None:
        lines.append(
            "  delta   : previous-version delta is "
            + ("ON" if settings.get("delta_enabled") else "OFF")
            + f" (VERSION_COMPRESSION_DELTA_ENABLED; a delta must be at least "
            f"{settings.get('delta_min_gain', 20)} % smaller than the plain compressed chunk)"
        )
    if st["failed"]["objects"]:
        lines.append(
            "  WARNING : objects marked failed were not changed; look for 'possible disk "
            "corruption' in the Version Engine log (./manage.sh version-manage compress --verify)."
        )
    if not settings.get("enabled") and c["pending_eligible"]:
        lines.append(
            "  note    : compression is OFF, so the backlog does not shrink. Set "
            '"VERSION_COMPRESSION_ENABLED": true in server_config.json and restart the '
            "Version Engine to start it."
        )
    return "\n".join(lines)
