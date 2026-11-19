"""
helpers/version_probe.py - READ-ONLY compression probe for the Version Engine store (5.46, Phase 0).

It measures the owner's REAL objects before any level, dictionary or delta decision is made
(VERSION_COMPRESSION_PLAN.md section 7). Nothing here writes into the store:

  * the database is opened with `file:...?mode=ro` plus `PRAGMA query_only=1`;
  * object files are opened `rb` and read once;
  * the compressed frames only ever live in memory and are dropped.

(SQLite itself keeps a `-shm` / `-wal` pair beside a WAL database for ANY reader, the
engine's own `status()` does the same. While the engine runs they exist already; with the engine
stopped a reader can leave an EMPTY pair behind, which the next engine start tidies. No row, no
byte of the database file and no object file is changed.)

What it reports: a random sample of raw objects (hash-verified, a mismatch is a FINDING, not an
error), per zstd level the size, the compress / decompress speed and the incompressible share,
a per-file-extension grouping (REPORT ONLY, never engine logic), an extrapolation to the whole
store (clearly an estimate), a trained-dictionary test and the previous-version delta test
(the number that decides Phase 4).

Rules of this file: standard library plus helpers/version_zstd.py (a leaf as well), no import of
config / version_engine / app / routes / tools (smoke rule 7b), NO asyncio, no thread, no pool.
The probe throttles itself with a duty cycle (`busy_percent`), so it is safe while the server
runs; the caller (tools/version_manage.py) only wires it to the command line.
"""

import hashlib
import os
import random
import re
import sqlite3
import time
from pathlib import Path

from helpers import version_zstd as vz

DEFAULT_LEVELS = (1, 3, 9, 15, 19, 22)
PROBE_LEVEL = (
    vz.PROBE_LEVEL
)  # the engine's fast "is it worth it" attempt (plan 6.5 step 3)
DEFAULT_SAMPLES = 400
DEFAULT_MIN_SAVING = 5.0  # VERSION_COMPRESSION_MIN_SAVING_PERCENT default
DEFAULT_BUSY_PERCENT = (
    50  # the probe's own duty cycle (the engine thread defaults to 25)
)
MIN_OBJECT_SIZE = (
    vz.MIN_OBJECT_SIZE
)  # the engine's minimum object size (plan 6.5 step 2)
MAX_OBJECT_BYTES = (
    256 * 1024 * 1024
)  # a recorded size above this is a finding, not a read
DICT_SIZES = (110 * 1024, 1024 * 1024)
DEFAULT_DICT_TRAIN_BYTES = 64 * 1024 * 1024
DEFAULT_DICT_TEST_BYTES = 64 * 1024 * 1024
DEFAULT_DICT_TEST_OBJECTS = 60
DEFAULT_DELTA_PAIRS = 200
MIN_DICT_SAMPLES = 8  # fewer usable objects than this: the dictionary test is skipped
TOP_EXTENSIONS = 12
IN_CHUNK = (
    500  # ids per `IN (...)` query (SQLite's variable limit is 999 on old builds)
)

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MIB = 1024 * 1024


class ProbeError(Exception):
    """The probe cannot run at all (no zstd, no usable database)."""


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------


def fmt_bytes(n) -> str:
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"  # pragma: no cover - the loop always returns


def fmt_duration(seconds) -> str:
    seconds = float(seconds)
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


def parse_levels(text) -> tuple:
    """'1,3,19' -> (1, 3, 19). Sorted, unique, each 1..22. ValueError otherwise."""
    levels = set()
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            raise ValueError(f"{part!r} is not a level number") from None
        if not vz.MIN_LEVEL <= value <= vz.MAX_LEVEL:
            raise ValueError(f"level {value} is outside {vz.MIN_LEVEL}..{vz.MAX_LEVEL}")
        levels.add(value)
    if not levels:
        raise ValueError("no level given")
    return tuple(sorted(levels))


def _ext_of(path) -> str:
    """Lower-case extension of a stored path (either slash style); '(none)' without one."""
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    ext = os.path.splitext(name)[1].lower()
    return ext or "(none)"


def _pct(part, whole) -> float:
    return (100.0 * part / whole) if whole else 0.0


def open_readonly(db_path) -> sqlite3.Connection:
    """A connection that CANNOT write: URI mode=ro and query_only. Raises ProbeError when the
    file is missing or is not a Version Engine database. Never creates anything."""
    if not os.path.isfile(db_path):
        raise ProbeError(f"No Version Engine database at: {db_path}")
    uri = Path(os.path.abspath(db_path)).as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA query_only=1")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("SELECT 1 FROM objects LIMIT 1").fetchall()
    except sqlite3.Error as exc:
        raise ProbeError(f"Cannot read the Version Engine database ({exc})") from exc
    return conn


def _object_path(objects_dir, sha) -> str:
    return os.path.join(objects_dir, sha[:2], sha)


def _read_object(objects_dir, sha, size):
    """(bytes, None) for a good raw object, else (None, reason). The SHA-256 is verified."""
    if not _SHA_RE.match(sha or ""):
        return None, "bad_name"
    if not isinstance(size, int) or size < 0 or size > MAX_OBJECT_BYTES:
        return None, "bad_size"
    try:
        with open(_object_path(objects_dir, sha), "rb") as fh:
            data = fh.read(size + 1)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unreadable"
    if len(data) != size:
        return None, "size_mismatch"
    if hashlib.sha256(data).hexdigest() != sha:
        return None, "hash_mismatch"
    return data, None


class _Findings:
    """What was wrong with objects that could not be used. REPORTED, never raised."""

    REASONS = (
        "hash_mismatch",
        "size_mismatch",
        "missing",
        "unreadable",
        "bad_name",
        "bad_size",
        "roundtrip",
    )

    def __init__(self):
        self.counts = dict.fromkeys(self.REASONS, 0)
        self.examples = {r: [] for r in self.REASONS}

    def add(self, reason, sha):
        self.counts[reason] += 1
        if len(self.examples[reason]) < 5:
            self.examples[reason].append(str(sha)[:16])

    def as_dict(self):
        return {
            r: {"count": self.counts[r], "examples": self.examples[r]}
            for r in self.REASONS
            if self.counts[r]
        }


class _Budget:
    """Seconds and bytes budgets. 0 means no limit. `clock` is injectable for the tests."""

    def __init__(self, max_seconds, max_bytes, clock):
        self.clock = clock
        self.start = clock()
        self.max_seconds = max_seconds or 0
        self.max_bytes = max_bytes or 0
        self.bytes_read = 0
        self.reason = None

    def phase_over(self, fraction):
        """True (and the reason is remembered) when the share `fraction` of the seconds budget
        is used up, or the bytes budget is."""
        if self.max_bytes and self.bytes_read >= self.max_bytes:
            self.reason = self.reason or "byte budget"
            return True
        if (
            self.max_seconds
            and (self.clock() - self.start) >= self.max_seconds * fraction
        ):
            self.reason = self.reason or "time budget"
            return True
        return False


def _throttle(elapsed, busy_percent, sleep):
    if 0 < busy_percent < 100 and elapsed > 0:
        sleep(elapsed * (100.0 / busy_percent - 1.0))


# --------------------------------------------------------------------------------------
# database queries (all read-only)
# --------------------------------------------------------------------------------------


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}  # noqa: S608


def _store_counts(conn):
    cols = _columns(conn, "objects")
    all_n, all_b = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM objects"
    ).fetchone()
    where = "orphaned_since IS NULL"
    if "codec" in cols:  # schema v2 (Phase 1): only objects still stored raw
        where += " AND codec = 'raw'"
    rows = conn.execute(
        f"SELECT sha256, size FROM objects WHERE {where} ORDER BY rowid"  # noqa: S608
    ).fetchall()
    return {
        "all_objects": all_n,
        "all_bytes": all_b,
        "eligible_objects": len(rows),
        "eligible_bytes": sum(r[1] for r in rows),
        "has_codec_column": "codec" in cols,
    }, rows


def _first_paths(conn, shas):
    """sha -> one file path that references it (the smallest path, so it is deterministic)."""
    found = {}
    shas = list(shas)
    for i in range(0, len(shas), IN_CHUNK):
        part = shas[i : i + IN_CHUNK]
        marks = ",".join("?" * len(part))
        sql = (
            "SELECT vo.sha256, MIN(f.path) FROM version_objects vo "  # noqa: S608
            "JOIN versions v ON v.version_id = vo.version_id "
            "JOIN files f ON f.file_id = v.file_id "
            f"WHERE vo.sha256 IN ({marks}) GROUP BY vo.sha256"
        )
        found.update(dict(conn.execute(sql, part).fetchall()))
    return found


_PAIR_SQL = """
WITH ordered AS (
    SELECT version_id, file_id,
           LAG(version_id) OVER (PARTITION BY file_id ORDER BY created_at, version_id)
               AS prev_id
    FROM versions WHERE status = 'completed'
)
SELECT p.sha256, n.sha256, n.chunk_index, f.path
FROM ordered o
JOIN version_objects n ON n.version_id = o.version_id
JOIN version_objects p ON p.version_id = o.prev_id AND p.chunk_index = n.chunk_index
JOIN files f ON f.file_id = o.file_id
WHERE o.prev_id IS NOT NULL AND p.sha256 != n.sha256
"""


def _reservoir_pairs(conn, k, rng, budget, fraction):
    """k random (old_sha, new_sha, chunk_index, path) rows of changed chunks between
    consecutive completed versions of the same file, without holding the whole result.
    """
    picks, seen = [], 0
    for row in conn.execute(_PAIR_SQL):
        seen += 1
        if len(picks) < k:
            picks.append(row)
        else:
            j = rng.randrange(seen)
            if j < k:
                picks[j] = row
        if seen % 20000 == 0 and budget.phase_over(fraction):
            break
    return picks, seen


# --------------------------------------------------------------------------------------
# the measurement
# --------------------------------------------------------------------------------------


def _new_level_stats():
    return {
        "raw_bytes": 0,  # non-tiny objects (what the codec was run on)
        "stored_bytes": 0,  # the sum of the frames
        "kept_bytes": 0,  # what the engine rules would keep (all usable sample objects)
        "compress_s": 0.0,
        "decompress_s": 0.0,
        "pipeline_s": 0.0,  # modelled time for the whole sample at this level
        "not_shrunk": 0,
        "not_shrunk_bytes": 0,
        "objects": 0,
    }


class _Probe:
    """One probe run. Holds the state so the three phases read top to bottom."""

    def __init__(self, conn, objects_dir, opts, budget, findings, rng, say):
        self.conn = conn
        self.objects_dir = objects_dir
        self.o = opts
        self.budget = budget
        self.findings = findings
        self.rng = rng
        self.say = say
        self.levels = opts["levels"]
        self.measured = tuple(sorted(set(self.levels) | {PROBE_LEVEL}))
        self.ref_level = 19 if 19 in self.levels else max(self.levels)
        self.stats = {lv: _new_level_stats() for lv in self.levels}
        self.ext_stats = {}
        self.sample = {
            "requested": opts["samples"],
            "picked": 0,
            "read": 0,
            "usable": 0,
            "bytes": 0,
            "tiny_objects": 0,
            "tiny_bytes": 0,
            "read_s": 0.0,
            "probe_s": 0.0,
            "probe_passed": 0,
        }
        self.store = {}
        self.train_keep = []
        self.test_keep = []
        self.dictionary = None
        self.delta = None
        self.interrupted = False

    # -- phase 1: read every picked object once and run every level on it -----------------
    def run_sample(self):
        o = self.o
        self.store, rows = _store_counts(self.conn)
        picks = self.rng.sample(rows, min(max(o["samples"], 0), len(rows)))
        self.sample["picked"] = len(picks)
        paths = _first_paths(self.conn, [p[0] for p in picks])
        half = len(picks) // 2
        train_bytes = test_bytes = 0
        for index, (sha, size) in enumerate(picks):
            if self.budget.phase_over(0.6):
                break
            t_obj = self.o["clock"]()
            data = self._read_and_measure(sha, size, paths)
            if data is not None and o["dictionary_test"]:
                if index < half:
                    if train_bytes + len(data) <= o["dict_train_bytes"]:
                        self.train_keep.append(data)
                        train_bytes += len(data)
                elif (
                    len(self.test_keep) < o["dict_test_objects"]
                    and test_bytes + len(data) <= o["dict_test_bytes"]
                ):
                    self.test_keep.append((sha, data))
                    test_bytes += len(data)
            if self.sample["read"] % 25 == 0:
                self.say(f"  sampled {self.sample['read']} of {len(picks)} objects ...")
            _throttle(o["clock"]() - t_obj, o["busy_percent"], o["sleep"])

    def _read_and_measure(self, sha, size, paths):
        """Read one object, run every level on it, update the totals. Returns the bytes when
        the object was measured by the codec (so the dictionary test may keep them)."""
        o, clock, sample = self.o, self.o["clock"], self.sample
        t0 = clock()
        data, why = _read_object(self.objects_dir, sha, size)
        read_s = clock() - t0
        sample["read"] += 1
        self.budget.bytes_read += size if isinstance(size, int) else 0
        if why:
            self.findings.add(why, sha)
            return None
        sample["usable"] += 1
        sample["bytes"] += size
        sample["read_s"] += read_s
        if size < MIN_OBJECT_SIZE:
            sample["tiny_objects"] += 1
            sample["tiny_bytes"] += size
            for lv in self.levels:
                self.stats[lv]["kept_bytes"] += size
                self.stats[lv]["pipeline_s"] += read_s
            return None

        frames, timing = {}, {}
        for lv in self.measured:
            t0 = clock()
            frame = vz.compress(data, lv)
            c_s = clock() - t0
            t0 = clock()
            try:
                back = vz.decode_bounded(frame, size)
            except vz.CodecError:
                back = None
            d_s = clock() - t0
            if back != data:
                self.findings.add("roundtrip", sha)
                return None
            frames[lv] = len(frame)
            timing[lv] = (c_s, d_s)

        min_saving = o["min_saving_percent"]
        probe_ok = _pct(size - frames[PROBE_LEVEL], size) >= vz.PROBE_MIN_SAVING_PERCENT
        sample["probe_s"] += timing[PROBE_LEVEL][0]
        sample["probe_passed"] += 1 if probe_ok else 0
        ext = _ext_of(paths[sha]) if sha in paths else "(unreferenced)"
        es = self.ext_stats.setdefault(
            ext,
            {"objects": 0, "raw_bytes": 0, "stored": dict.fromkeys(self.levels, 0)},
        )
        es["objects"] += 1
        es["raw_bytes"] += size
        for lv in self.levels:
            st = self.stats[lv]
            c_s, d_s = timing[lv]
            stored = frames[lv]
            shrinks = _pct(size - stored, size) >= min_saving
            st["objects"] += 1
            st["raw_bytes"] += size
            st["stored_bytes"] += stored
            st["compress_s"] += c_s
            st["decompress_s"] += d_s
            es["stored"][lv] += stored
            if not shrinks:
                st["not_shrunk"] += 1
                st["not_shrunk_bytes"] += size
            st["kept_bytes"] += stored if (probe_ok and shrinks) else size
            st["pipeline_s"] += read_s + timing[PROBE_LEVEL][0]
            if probe_ok:
                st["pipeline_s"] += c_s + d_s
        return data

    # -- phase 2: trained dictionary ---------------------------------------------------------
    def run_dictionary(self):
        o = self.o
        if not o["dictionary_test"]:
            return
        if self.budget.phase_over(0.75):
            self.dictionary = {"skipped": f"stopped early ({self.budget.reason})"}
            return
        self.say("  dictionary test ...")
        self.dictionary = _dictionary_test(
            self.train_keep,
            self.test_keep,
            self.ref_level,
            o["busy_percent"],
            o["sleep"],
            o["clock"],
        )
        self.train_keep = self.test_keep = []  # free the memory

    # -- phase 3: previous-version delta -----------------------------------------------------
    def run_delta(self):
        o = self.o
        if not o["delta_test"]:
            return
        if self.budget.phase_over(1.0):
            self.delta = {"skipped": f"stopped early ({self.budget.reason})"}
            return
        self.say("  previous-version delta test ...")
        self.delta = _delta_test(
            self.conn,
            self.objects_dir,
            o["delta_pairs"],
            self.rng,
            self.ref_level,
            o["busy_percent"],
            self.findings,
            self.budget,
            o["sleep"],
            o["clock"],
        )

    # -- the report ----------------------------------------------------------------------
    def report(self, seed):
        o, store, sample = self.o, self.store, self.sample
        total_sample = sample["bytes"]
        estimate = {}
        for lv in self.levels:
            st = self.stats[lv]
            ratio = (st["kept_bytes"] / total_sample) if total_sample else 1.0
            scale = (
                (store.get("eligible_bytes", 0) / total_sample) if total_sample else 0.0
            )
            expected = store.get("eligible_bytes", 0) * ratio
            estimate[lv] = {
                "expected_stored_bytes": expected,
                "saving_bytes": store.get("eligible_bytes", 0) - expected,
                "saving_percent": _pct(
                    store.get("eligible_bytes", 0) - expected,
                    store.get("eligible_bytes", 0),
                ),
                "migration_seconds": st["pipeline_s"]
                * scale
                / (max(o["busy_percent"], 1) / 100.0),
            }
        return {
            "zstd_version": vz.version(),
            "seed": seed,
            "levels": list(self.levels),
            "ref_level": self.ref_level,
            "min_saving_percent": o["min_saving_percent"],
            "busy_percent": o["busy_percent"],
            "store": store,
            "sample": sample,
            "findings": self.findings.as_dict(),
            "stopped": self.budget.reason,
            "interrupted": self.interrupted,
            "level_stats": {lv: self.stats[lv] for lv in self.levels},
            "extensions": _top_extensions(self.ext_stats, self.levels),
            "estimate": estimate,
            "recommended_level": recommend_level(
                self.stats, self.levels, o["min_saving_percent"]
            ),
            "dictionary": self.dictionary,
            "delta": self.delta,
            "seconds": self.budget.clock() - self.budget.start,
        }


def _top_extensions(ext_stats, levels):
    rows = sorted(ext_stats.items(), key=lambda kv: -kv[1]["raw_bytes"])
    out = []
    other = {"objects": 0, "raw_bytes": 0, "stored": dict.fromkeys(levels, 0)}
    for i, (name, es) in enumerate(rows):
        if i < TOP_EXTENSIONS:
            out.append({"ext": name, **es})
        else:
            other["objects"] += es["objects"]
            other["raw_bytes"] += es["raw_bytes"]
            for lv in levels:
                other["stored"][lv] += es["stored"][lv]
    if other["objects"]:
        out.append({"ext": "(other)", **other})
    return out


def run_probe(
    db_path,
    objects_dir,
    *,
    samples=DEFAULT_SAMPLES,
    levels=DEFAULT_LEVELS,
    seed=None,
    min_saving_percent=DEFAULT_MIN_SAVING,
    busy_percent=DEFAULT_BUSY_PERCENT,
    max_seconds=0,
    max_bytes=0,
    dictionary_test=True,
    delta_test=True,
    delta_pairs=DEFAULT_DELTA_PAIRS,
    dict_train_bytes=DEFAULT_DICT_TRAIN_BYTES,
    dict_test_bytes=DEFAULT_DICT_TEST_BYTES,
    dict_test_objects=DEFAULT_DICT_TEST_OBJECTS,
    progress=None,
    sleep=time.sleep,
    clock=time.perf_counter,
) -> dict:
    """Run the whole probe and return the report as a plain dict (see `format_report`).

    Read-only. `progress(text)` gets short status lines. `sleep` and `clock` are injectable so
    the tests need no real waiting. Ctrl-C ends the run early and still returns what was
    measured, with report["interrupted"] = True. Raises ProbeError when the probe cannot run
    at all (no zstd, no usable database)."""
    if not vz.available() or not vz.self_test():
        raise ProbeError(
            "zstd is not available in this Python (Python 3.14 has compression.zstd; "
            "older versions: pip install backports.zstd)"
        )
    if seed is None:
        seed = random.SystemRandom().randrange(1, 2**31)
    opts = {
        "samples": int(samples),
        "levels": tuple(sorted({vz.clamp_level(x) for x in levels})),
        "min_saving_percent": float(min_saving_percent),
        "busy_percent": busy_percent,
        "dictionary_test": dictionary_test,
        "delta_test": delta_test,
        "delta_pairs": int(delta_pairs),
        "dict_train_bytes": dict_train_bytes,
        "dict_test_bytes": dict_test_bytes,
        "dict_test_objects": dict_test_objects,
        "sleep": sleep,
        "clock": clock,
    }
    # Sampling, not security: the same --seed repeats the same sample.
    rng = random.Random(seed)  # noqa: S311
    conn = open_readonly(db_path)
    try:
        run = _Probe(
            conn,
            objects_dir,
            opts,
            _Budget(max_seconds, max_bytes, clock),
            _Findings(),
            rng,
            progress or (lambda text: None),
        )
        try:
            run.run_sample()
            run.run_dictionary()
            run.run_delta()
        except KeyboardInterrupt:
            run.interrupted = True
            run.budget.reason = run.budget.reason or "interrupted"
        return run.report(seed)
    finally:
        conn.close()


def recommend_level(stats, levels, min_saving=DEFAULT_MIN_SAVING, tolerance=0.005):
    """The lowest measured level whose total stored size is within 0.5 % of the smallest one
    measured ('highest practical ratio' without paying for a level that gains nothing).
    None when no object could be measured or compression is not worth it at all."""
    totals = {lv: stats[lv]["stored_bytes"] for lv in levels if stats[lv]["raw_bytes"]}
    if not totals:
        return None
    best = min(totals.values())
    pick = next(lv for lv in sorted(totals) if totals[lv] <= best * (1 + tolerance))
    raw = stats[pick]["raw_bytes"]
    if _pct(raw - totals[pick], raw) < min_saving:
        return None
    return pick


def _dictionary_test(train, test, level, busy_percent, sleep, clock):
    """Train on one half of the sample, measure on the other half (plan section 7)."""
    result = {"level": level, "train_objects": len(train), "test_objects": len(test)}
    result["train_bytes"] = sum(len(d) for d in train)
    result["test_bytes"] = sum(len(d) for _, d in test)
    if len(train) + len(test) < MIN_DICT_SAMPLES or not train or not test:
        result["skipped"] = (
            f"too few usable objects (need at least {MIN_DICT_SAMPLES} non-tiny ones)"
        )
        return result
    plain = 0
    for _sha, data in test:
        t0 = clock()
        plain += len(vz.compress(data, level))
        _throttle(clock() - t0, busy_percent, sleep)
    result["plain_bytes"] = plain
    result["sizes"] = []
    for dict_size in DICT_SIZES:
        entry = {"dict_size": dict_size}
        t0 = clock()
        try:
            zdict = vz.train_dictionary(train, dict_size)
        except (vz.CodecError, ValueError, OverflowError) as exc:
            entry["error"] = str(exc)
            result["sizes"].append(entry)
            continue
        entry["train_s"] = clock() - t0
        entry["dict_bytes"] = len(zdict.dict_content)
        total = 0
        for _sha, data in test:
            t1 = clock()
            frame = vz.compress(data, level, zstd_dict=zdict)
            try:
                back = vz.decode_bounded(frame, len(data), zstd_dict=zdict)
            except vz.CodecError:
                back = None
            if back != data:
                entry["error"] = "round trip with the dictionary FAILED"
                break
            total += len(frame)
            _throttle(clock() - t1, busy_percent, sleep)
        else:
            entry["bytes"] = total
            entry["gain_percent"] = _pct(plain - total, plain)
        result["sizes"].append(entry)
    return result


def _window_log_for(n_bytes):
    return max(
        vz.MIN_WINDOW_LOG, min(vz.MAX_WINDOW_LOG, (max(n_bytes, 1) - 1).bit_length())
    )


def _delta_test(
    conn, objects_dir, k, rng, level, busy_percent, findings, budget, sleep, clock
):
    """Compress the NEWER chunk with the same chunk of the previous version as a raw
    dictionary and compare with plain compression (plan section 4.3 / 11)."""
    result = {"level": level, "requested": int(k)}
    try:
        picks, seen = _reservoir_pairs(conn, int(k), rng, budget, 1.0)
    except sqlite3.Error as exc:
        result["skipped"] = f"the pair query failed ({exc})"
        return result
    result["pairs_available"] = seen
    result["pairs_picked"] = len(picks)
    if not picks:
        result["skipped"] = (
            "no file has two completed versions with a changed chunk yet"
        )
        return result
    tested = smaller = big_wins = 0
    raw_total = plain_total = delta_total = 0
    by_ext = {}
    unusable = 0
    for old_sha, new_sha, _chunk, path in picks:
        if budget.phase_over(1.0):
            result["stopped"] = budget.reason
            break
        t_obj = clock()
        new, why_new = _read_object(objects_dir, new_sha, _size_of(conn, new_sha))
        old, why_old = (None, None)
        if new is not None:
            old, why_old = _read_object(objects_dir, old_sha, _size_of(conn, old_sha))
        for why, sha in ((why_new, new_sha), (why_old, old_sha)):
            if why:
                findings.add(why, sha)
        if new is None or old is None:
            unusable += 1
            continue
        budget.bytes_read += len(new) + len(old)
        plain = len(vz.compress(new, level))
        zdict = vz.raw_dictionary(old)
        frame = vz.compress(
            new, level, zstd_dict=zdict, window_log=_window_log_for(len(old) + len(new))
        )
        try:
            back = vz.decode_bounded(frame, len(new), zstd_dict=zdict)
        except vz.CodecError:
            back = None
        if back != new:
            findings.add("roundtrip", new_sha)
            unusable += 1
            continue
        tested += 1
        raw_total += len(new)
        plain_total += plain
        delta_total += len(frame)
        smaller += 1 if len(frame) < plain else 0
        big_wins += 1 if len(frame) * 2 <= plain else 0
        ext = _ext_of(path)
        e = by_ext.setdefault(ext, {"pairs": 0, "raw": 0, "plain": 0, "delta": 0})
        e["pairs"] += 1
        e["raw"] += len(new)
        e["plain"] += plain
        e["delta"] += len(frame)
        _throttle(clock() - t_obj, busy_percent, sleep)
    result.update(
        {
            "tested": tested,
            "unusable": unusable,
            "raw_bytes": raw_total,
            "plain_bytes": plain_total,
            "delta_bytes": delta_total,
            "smaller": smaller,
            "at_least_half_smaller": big_wins,
            "by_ext": dict(sorted(by_ext.items(), key=lambda kv: -kv[1]["raw"])[:8]),
        }
    )
    return result


def _size_of(conn, sha):
    row = conn.execute("SELECT size FROM objects WHERE sha256 = ?", (sha,)).fetchone()
    return row[0] if row else -1


# --------------------------------------------------------------------------------------
# the printed report
# --------------------------------------------------------------------------------------


def _mibs(nbytes, seconds) -> str:
    return f"{nbytes / MIB / seconds:8.0f}" if seconds > 0 else "       -"


def format_report(report, db_path="", objects_dir="") -> str:
    """The readable report: one block of tables and a final recommended-level line."""
    out = []
    add = out.append
    store, sample, levels = report["store"], report["sample"], report["levels"]
    add("=" * 78)
    add(f"Version Engine compression probe (READ-ONLY)   zstd {report['zstd_version']}")
    add("=" * 78)
    if db_path:
        add(f"  database : {db_path}")
    if objects_dir:
        add(f"  objects  : {objects_dir}")
    add(
        f"  seed     : {report['seed']}   (repeat the same sample with --seed {report['seed']})"
    )
    add(
        f"  took     : {fmt_duration(report['seconds'])}, duty cycle {report['busy_percent']} %"
    )
    if report["stopped"]:
        add(
            f"  NOTE     : stopped early ({report['stopped']}); numbers cover what was read"
        )

    add("")
    add("STORE (what the database lists)")
    add(
        f"  objects total {store['all_objects']:,}  "
        f"{fmt_bytes(store['all_bytes'])}  (raw sizes)"
    )
    kind = "stored raw, not orphaned" if store["has_codec_column"] else "not orphaned"
    add(
        f"  eligible      {store['eligible_objects']:,}  "
        f"{fmt_bytes(store['eligible_bytes'])}  ({kind})"
    )

    add("")
    add("SAMPLE")
    add(
        f"  picked {sample['picked']:,} of {store['eligible_objects']:,} objects at random; "
        f"read {sample['read']:,}, usable {sample['usable']:,} "
        f"({fmt_bytes(sample['bytes'])}, SHA-256 verified)"
    )
    add(
        f"  tiny objects (under {MIN_OBJECT_SIZE} B, never compressed): "
        f"{sample['tiny_objects']:,} ({fmt_bytes(sample['tiny_bytes'])})"
    )
    if sample["usable"] - sample["tiny_objects"]:
        add(
            f"  level-{PROBE_LEVEL} probe: {sample['probe_passed']:,} of "
            f"{sample['usable'] - sample['tiny_objects']:,} objects shrink by at least "
            f"{vz.PROBE_MIN_SAVING_PERCENT:g} % (the rest would be marked 'skip')"
        )
    if report["findings"]:
        add("  FINDINGS (excluded from the numbers):")
        notes = {
            "hash_mismatch": "stored object fails its own SHA-256: possible disk corruption",
            "size_mismatch": "file size differs from the recorded size",
            "missing": "the database lists it but the file is not there",
            "unreadable": "could not be opened or read",
            "bad_name": "object name is not a SHA-256",
            "bad_size": "recorded size is not usable",
            "roundtrip": "zstd round trip did not give the same bytes (report this!)",
        }
        for reason, info in report["findings"].items():
            add(
                f"    {reason}: {info['count']}  - {notes[reason]}  "
                f"e.g. {', '.join(info['examples'])}"
            )
    else:
        add("  findings: none (every object read matched its SHA-256)")

    add("")
    add("LEVELS (each object is its own frame; speeds in MiB/s of raw data, 1 core)")
    add(
        "  level | stored % | kept % |  compress | decompress | not shrunk >= "
        f"{report['min_saving_percent']:g} %"
    )
    add("        |  of raw  | (rules)|   MiB/s   |    MiB/s   | objects      bytes")
    for lv in levels:
        st = report["level_stats"][lv]
        raw = st["raw_bytes"]
        total = sample["bytes"]
        add(
            f"  {lv:>5} | {_pct(st['stored_bytes'], raw):7.2f}% | "
            f"{_pct(st['kept_bytes'], total):5.1f}% | "
            f"{_mibs(raw, st['compress_s'])}  | {_mibs(raw, st['decompress_s'])}   | "
            f"{_pct(st['not_shrunk'], st['objects']):5.1f}%  "
            f"{_pct(st['not_shrunk_bytes'], raw):6.1f}%"
        )
    add(
        "  stored %: the codec on every non-tiny object. kept %: what the engine rules keep"
    )
    add(
        f"  (tiny objects stay raw; the level-{PROBE_LEVEL} probe must save "
        f"{vz.PROBE_MIN_SAVING_PERCENT:g} %; then the chosen level must save "
        f"{report['min_saving_percent']:g} %)."
    )

    if report["extensions"]:
        add("")
        add("BY FILE EXTENSION (report only; stored % of raw per level)")
        head = "  ext        objects   raw size  " + " ".join(
            f"{'L' + str(lv):>6}" for lv in levels
        )
        add(head)
        for e in report["extensions"]:
            cells = " ".join(
                f"{_pct(e['stored'][lv], e['raw_bytes']):5.1f}%" for lv in levels
            )
            add(
                f"  {e['ext'][:10]:<10} {e['objects']:>7,}  "
                f"{fmt_bytes(e['raw_bytes']):>9}  {cells}"
            )

    add("")
    add("ESTIMATE FOR THE WHOLE STORE (extrapolated from the sample: an ESTIMATE)")
    add(
        f"  eligible raw: {fmt_bytes(store['eligible_bytes'])}. Time = read + hash + probe + "
        f"compress + verify decode,"
    )
    add(
        f"  at {report['busy_percent']} % duty cycle; writing the new files is NOT included "
        "(add a safety margin)."
    )
    add("  level |  expected stored |   saving |  % saved | migration time")
    for lv in levels:
        e = report["estimate"][lv]
        add(
            f"  {lv:>5} | {fmt_bytes(e['expected_stored_bytes']):>16} | "
            f"{fmt_bytes(e['saving_bytes']):>8} | {e['saving_percent']:7.1f}% | "
            f"{fmt_duration(e['migration_seconds']):>13}"
        )

    add("")
    add("TRAINED DICTIONARY (train on one half of the sample, test on the other half)")
    _format_dictionary(report["dictionary"], add)

    add("")
    add(
        "PREVIOUS-VERSION DELTA (newer chunk compressed with the older chunk as dictionary)"
    )
    _format_delta(report["delta"], add)

    add("")
    rec = report["recommended_level"]
    if rec is None:
        if sample["usable"] - sample["tiny_objects"] <= 0:
            add("RECOMMENDED LEVEL: none (no object could be measured)")
        else:
            add(
                "RECOMMENDED LEVEL: none - compression saves less than "
                f"{report['min_saving_percent']:g} % on this sample"
            )
    else:
        st = report["level_stats"][rec]
        add(
            f"RECOMMENDED LEVEL: {rec}  (lowest level within 0.5 % of the smallest total; "
            f"{_pct(st['stored_bytes'], st['raw_bytes']):.2f} % of raw, "
            f"decompress {_mibs(st['raw_bytes'], st['decompress_s']).strip()} MiB/s)"
        )
    add(
        "  This is a recommendation for the owner to confirm, not a setting that was changed."
    )
    add(
        f"  The default VERSION_COMPRESSION_LEVEL is {vz.DEFAULT_LEVEL} (the maximum, the "
        "owner's decision): it is used even where it gains nothing over the level above."
    )
    add("=" * 78)
    return "\n".join(out)


def _format_dictionary(d, add):
    if not d:
        add("  not run")
        return
    if d.get("skipped"):
        add(f"  skipped: {d['skipped']}")
        return
    add(
        f"  level {d['level']}; trained on {d['train_objects']} objects "
        f"({fmt_bytes(d['train_bytes'])}), tested on {d['test_objects']} other objects "
        f"({fmt_bytes(d['test_bytes'])})"
    )
    add(f"  without a dictionary: {fmt_bytes(d['plain_bytes'])}")
    for e in d["sizes"]:
        label = f"{fmt_bytes(e['dict_size'])} dictionary"
        if "error" in e:
            add(f"  {label}: {e['error']}")
        else:
            add(
                f"  {label}: {fmt_bytes(e['bytes'])}  ({e['gain_percent']:+.2f} % vs none, "
                f"trained in {fmt_duration(e['train_s'])})"
            )


def _format_delta(d, add):
    if not d:
        add("  not run")
        return
    if d.get("skipped"):
        add(f"  skipped: {d['skipped']}")
        return
    add(
        f"  level {d['level']}; {d['pairs_available']:,} changed chunks found between consecutive "
        f"versions, {d['pairs_picked']} picked, {d.get('tested', 0)} tested"
        + (f", {d['unusable']} unusable" if d.get("unusable") else "")
    )
    if d.get("stopped"):
        add(f"  stopped early ({d['stopped']})")
    if not d.get("tested"):
        return
    plain, delta = d["plain_bytes"], d["delta_bytes"]
    factor = (plain / delta) if delta else float("inf")
    add(
        f"  raw {fmt_bytes(d['raw_bytes'])}  plain {fmt_bytes(plain)}  "
        f"delta {fmt_bytes(delta)}  -> delta is {factor:.1f}x smaller "
        f"({_pct(plain - delta, plain):.1f} % saved on top of plain)"
    )
    add(
        f"  delta smaller than plain: {d['smaller']} of {d['tested']} chunks; "
        f"at least 2x smaller: {d['at_least_half_smaller']}"
    )
    if d["by_ext"]:
        add("  ext        pairs     plain     delta   factor")
        for ext, e in d["by_ext"].items():
            f = (e["plain"] / e["delta"]) if e["delta"] else float("inf")
            add(
                f"  {ext[:10]:<10} {e['pairs']:>5}  {fmt_bytes(e['plain']):>9} "
                f"{fmt_bytes(e['delta']):>9}  {f:6.1f}x"
            )
