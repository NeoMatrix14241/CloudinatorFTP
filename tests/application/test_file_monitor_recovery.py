"""
file_monitor.py (cache/storage_index.json and the counters behind the folder sizes): what happens
when the saved index is damaged, foreign or stale, and whether a walk or a per-folder correction
produces the numbers the disk really has. The real module runs inside a SCRATCH COPY of the
project (own cache folder, own storage) with the same helper the other tests use for the scratch
database (`run_in_scratch`); no server, no watchdog observer and no thread of the monitor is
started. Every snippet first asserts that its cache and storage folders are inside the scratch
copy and then EMPTIES the scratch storage, so the expected numbers below are exact.

Contracts tested (CLAUDE.md 4.59, 4.62, 4.64, 4.65): a damaged, foreign or half-valid
storage_index.json is discarded or repaired without leaving half-loaded counters, a walk counts
what is on disk (hidden files and .chunks excluded), unchanged data does not rewrite the JSON,
a walk that finds nothing while the index holds many files (or whose root is unreadable) never
replaces good data, a per-folder correction lands on the same numbers as a fresh walk, and the
file index (file_index.json) is kept in step with it.

Not covered on purpose: the watchdog event handlers (timing dependent), the settle / drain timers
and the SSE callbacks.
"""

import json
import textwrap
import uuid

import pytest

pytestmark = pytest.mark.application

PRELUDE = textwrap.dedent("""
    import json, os, shutil, sys, time
    cwd = os.path.abspath(os.getcwd())
    import file_index as fi
    fi.THRESHOLD = 3
    from config import ROOT_DIR as ROOT
    import file_monitor as fm
    for _d in (fm.CACHE_DIR, fi.CACHE_DIR, ROOT):
        assert os.path.abspath(_d).startswith(cwd), "NOT inside the scratch copy: " + _d
    os.makedirs(fm.CACHE_DIR, exist_ok=True)
    os.makedirs(ROOT, exist_ok=True)
    for _n in os.listdir(fm.CACHE_DIR):
        _p = os.path.join(fm.CACHE_DIR, _n)
        if os.path.isfile(_p):  # ensure_dirs() makes sub-folders such as hls/
            os.remove(_p)
    for _n in os.listdir(ROOT):
        _p = os.path.join(ROOT, _n)
        shutil.rmtree(_p) if os.path.isdir(_p) else os.remove(_p)
    TAG = sys.argv[1]
    INDEX = fm.CACHE_FILE

    def put(rel, size):
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        return path

    def build():
        put("a.txt", 3)
        put("b.txt", 5)
        put("d1/f1.txt", 10)
        put("d1/sub/f2.txt", 20)
        put(".hidden", 7)
        put(".chunks/part", 9)

    def monitor(root=None):
        return fm.FileSystemMonitor(root or ROOT)

    def apply(m, r):
        with m.lock:
            m._file_count = r["file_count"]
            m._dir_count = r["dir_count"]
            m._total_size = r["total_size"]
            m._last_modified = r["last_modified"]
            m._dir_info = r["dir_info"]

    def walked(m=None):
        m = m or monitor()
        apply(m, m._full_walk(silent=True))
        return m

    def counters(m):
        return [m._file_count, m._dir_count, m._total_size]

    def read_index():
        with open(INDEX, encoding="utf-8") as f:
            return json.load(f)

    def index_text():
        with open(INDEX, encoding="utf-8") as f:
            return f.read()

    def out(**kw):
        print("RESULT=" + json.dumps(kw, default=str))
    """)


@pytest.fixture(scope="module")
def lab(scratch_tools, tmp_path_factory):
    root = tmp_path_factory.mktemp("monitor_lab") / "app"
    scratch_tools.build(root, port=scratch_tools.free_port())
    assert scratch_tools.paths_outside(root) == []
    return root


@pytest.fixture(scope="module")
def run(lab, scratch_tools):
    def _run(body, *args):
        tag = uuid.uuid4().hex[:8]
        code = PRELUDE + textwrap.dedent(body)
        stdout = scratch_tools.run_in_scratch(lab, code, tag, *args)
        lines = [ln for ln in stdout.splitlines() if ln.startswith("RESULT=")]
        assert lines, "the snippet printed no RESULT line:\n" + stdout[-800:]
        result = json.loads(lines[-1][len("RESULT=") :])
        result["tag"] = tag
        return result

    return _run


# ---------------------------------------------------------------------------- the walk
def test_a_walk_counts_what_is_on_disk_and_skips_hidden_files_and_chunks(run):
    r = run("""
        build()
        res = monitor()._full_walk(silent=True)
        out(complete=res["complete"], errors=res["errors"], files=res["file_count"],
            dirs=res["dir_count"], size=res["total_size"], info=res["dir_info"])
        """)
    assert r["complete"] is True and r["errors"] == 0
    assert (r["files"], r["dirs"], r["size"]) == (4, 2, 38)
    assert r["info"] == {
        "": {"file_count": 4, "dir_count": 2, "total_size": 38},
        "d1": {"file_count": 2, "dir_count": 1, "total_size": 30},
        "d1/sub": {"file_count": 1, "dir_count": 0, "total_size": 20},
    }


def test_get_dir_info_normalises_the_path_and_returns_a_copy(run):
    r = run("""
        build()
        m = walked()
        first = m.get_dir_info("d1/sub/")
        first["file_count"] = 999
        out(slash=first, backslash=m.get_dir_info("d1\\\\sub"),
            root=m.get_dir_info(""), missing=m.get_dir_info("nope"))
        """)
    assert r["slash"]["file_count"] == 999  # it is the caller's copy
    assert r["backslash"] == {"file_count": 1, "dir_count": 0, "total_size": 20}
    assert r["root"]["file_count"] == 4 and r["missing"] is None


# ---------------------------------------------------------------------------- save and load
def test_a_saved_index_loads_back_unchanged(run):
    r = run("""
        build()
        m = walked()
        m._save_cache()
        data = read_index()
        m2 = monitor()
        loaded = m2._load_cache()
        out(version=data["version"], root=data["root"], rooted=str(m.root_path),
            has_saved_at="saved_at" in data, loaded=loaded, repaired=m2._load_repaired,
            same_info=(m2._dir_info == m._dir_info), counters=counters(m2),
            saved=[data["file_count"], data["dir_count"], data["total_size"]])
        """)
    assert r["version"] == 2 and r["root"] == r["rooted"] and r["has_saved_at"]
    assert r["loaded"] is True and r["repaired"] == 0 and r["same_info"]
    assert r["counters"] == r["saved"] == [4, 2, 38]


DISCARDED = {
    "not_json": "RAW:{not json",
    "empty_file": "RAW:",
    "a_list": "RAW:[]",
    "null": "RAW:null",
    "unknown_version": "d['version'] = 99",
    "other_root": "d['root'] = os.path.join(os.path.dirname(d['root']), 'other_root')",
    "negative_counter": "d['file_count'] = -1",
    "text_counter": "d['total_size'] = 'abc'",
    "bool_counter": "d['dir_count'] = True",
    "empty_dir_info": "d['dir_info'] = {}",
    "no_dir_info": "del d['dir_info']",
    "dir_info_is_a_list": "d['dir_info'] = [1, 2]",
}


@pytest.mark.parametrize("spec", DISCARDED.values(), ids=DISCARDED.keys())
def test_a_damaged_or_foreign_index_is_discarded_and_leaves_nothing_half_loaded(
    run, spec
):
    r = run(
        """
        build()
        walked()._save_cache()
        spec = sys.argv[2]
        if spec.startswith("RAW:"):
            text = spec[4:]
        else:
            d = read_index()
            exec(spec)
            text = json.dumps(d)
        with open(INDEX, "w", encoding="utf-8") as f:
            f.write(text)
        m = monitor()
        loaded = m._load_cache()
        out(loaded=loaded, info=m._dir_info, counters=counters(m), repaired=m._load_repaired)
        """,
        spec,
    )
    assert r["loaded"] is False
    assert r["info"] == {} and r["counters"] == [0, 0, 0] and r["repaired"] == 0


def test_bad_records_are_repaired_in_place_and_counted(run):
    r = run("""
        build()
        good = {"file_count": 4, "dir_count": 2, "total_size": 38}
        write = lambda d: open(INDEX, "w", encoding="utf-8").write(json.dumps(d))
        base = {"version": 2, "root": str(ROOT), "file_count": 4, "dir_count": 2,
                "total_size": 38, "last_modified": 1.0}
        write({**base, "dir_info": {
            "": good,
            "d1": {"file_count": -5, "dir_count": 1, "total_size": 30},
            "bad" + chr(92) + "key": good,
            "/lead": good,
            "sub": 7,
        }})
        m = monitor()
        loaded = m._load_cache()
        first = dict(keys=sorted(m._dir_info), d1=m._dir_info["d1"], sub=m._dir_info["sub"],
                     repaired=m._load_repaired)

        write({**base, "dir_info": {"d1": good}})
        m2 = monitor()
        m2._load_cache()
        missing_root = dict(root=m2._dir_info[""], repaired=m2._load_repaired)

        write({**base, "dir_info": {"": {**good, "file_count": 99}}})
        m3 = monitor()
        m3._load_cache()
        disagrees = dict(root_files=m3._dir_info[""]["file_count"], repaired=m3._load_repaired)

        write({"file_count": 4, "dir_count": 2, "total_size": 38, "last_modified": 1.0,
               "dir_info": {"": good}})   # legacy file: no version, no root
        m4 = monitor()
        legacy = dict(loaded=m4._load_cache(), repaired=m4._load_repaired)
        out(loaded=loaded, first=first, missing_root=missing_root, disagrees=disagrees,
            legacy=legacy)
        """)
    assert r["loaded"] is True
    assert r["first"]["keys"] == ["", "d1", "sub"]  # the two malformed keys are gone
    # one bad field makes the whole record untrustworthy: every field is reset to 0
    assert r["first"]["d1"] == {"file_count": 0, "dir_count": 0, "total_size": 0}
    assert r["first"]["sub"] == {"file_count": 0, "dir_count": 0, "total_size": 0}
    assert r["first"]["repaired"] == 4  # two keys, one bad field, one non-dict record
    assert r["missing_root"]["root"] == {
        "file_count": 4,
        "dir_count": 2,
        "total_size": 38,
    }
    assert r["missing_root"]["repaired"] == 1
    assert r["disagrees"] == {
        "root_files": 99,
        "repaired": 1,
    }  # flagged, verified by a walk
    assert r["legacy"] == {"loaded": True, "repaired": 1}


def test_old_temp_files_of_a_crashed_save_are_swept_and_others_are_left_alone(run):
    r = run("""
        def make(name, age):
            p = os.path.join(fm.CACHE_DIR, name)
            with open(p, "w") as f:
                f.write("x")
            old = time.time() - age
            os.utime(p, (old, old))
        make("storage_index.dead.tmp", 7200)
        make("storage_index.recent.tmp", 10)
        make("file_index_dead.tmp", 7200)
        loaded = monitor()._load_cache()
        out(loaded=loaded, left=sorted(
            n for n in os.listdir(fm.CACHE_DIR)
            if os.path.isfile(os.path.join(fm.CACHE_DIR, n))))
        """)
    assert r["loaded"] is False  # no storage_index.json: first-boot walk
    assert r["left"] == ["file_index_dead.tmp", "storage_index.recent.tmp"]


def test_unchanged_data_does_not_rewrite_the_json_but_a_change_does(run):
    r = run("""
        build()
        m = walked()
        m._save_cache()
        first_text, first_ns = index_text(), os.stat(INDEX).st_mtime_ns
        time.sleep(0.05)
        m._save_cache()                                   # nothing changed
        same_text, same_ns = index_text(), os.stat(INDEX).st_mtime_ns
        put("new.txt", 4)
        apply(m, m._full_walk(silent=True))
        m._save_cache()
        changed = read_index()
        os.remove(INDEX)
        m._save_cache()                                   # content unchanged, file gone
        out(untouched=(first_text == same_text and first_ns == same_ns),
            files=changed["file_count"], size=changed["total_size"],
            written_again=os.path.exists(INDEX),
            tmp_left=[n for n in os.listdir(fm.CACHE_DIR)
                      if n.startswith("storage_index.") and n.endswith(".tmp")])
        """)
    assert r["untouched"] is True
    assert (r["files"], r["size"]) == (5, 42)
    assert r["written_again"] is True and r["tmp_left"] == []


# ---------------------------------------------------------------------------- reconcile
def test_a_reconcile_corrects_drifted_counters_and_saves_the_truth(run):
    r = run("""
        build()
        m = walked()
        m._save_cache()
        m._file_count = 999
        m._dir_info[""]["file_count"] = 999
        m._dir_info["d1"]["total_size"] = 1
        applied = m._reconcile_walk()
        out(applied=applied, counters=counters(m), d1=m.get_dir_info("d1"),
            saved=[read_index()["file_count"], read_index()["total_size"]])
        """)
    assert r["applied"] is True and r["counters"] == [4, 2, 38]
    assert r["d1"] == {"file_count": 2, "dir_count": 1, "total_size": 30}
    assert r["saved"] == [4, 38]


def test_a_walk_that_finds_nothing_is_rejected_once_when_the_index_is_large(run):
    r = run("""
        for n in range(60):
            put(f"bulk/f{n:02d}.txt", 1)
        m = walked()
        m._save_cache()
        before = index_text()
        shutil.rmtree(os.path.join(ROOT, "bulk"))          # looks like an offline drive
        first = m._reconcile_walk()
        after_first = counters(m), "bulk" in m._dir_info, index_text() == before
        second = m._reconcile_walk()                       # still empty: the tree really is empty
        out(before=[60, 1, 60], first=first, after_first=after_first, second=second,
            after_second=counters(m), saved=read_index()["file_count"])
        """)
    assert r["first"] is False
    assert r["after_first"] == [
        [60, 1, 60],
        True,
        True,
    ]  # nothing replaced, nothing saved
    assert r["second"] is True
    assert r["after_second"] == [0, 0, 0] and r["saved"] == 0


def test_a_forced_rebuild_accepts_an_empty_tree_at_once(run):
    r = run("""
        for n in range(60):
            put(f"bulk/f{n:02d}.txt", 1)
        m = walked()
        shutil.rmtree(os.path.join(ROOT, "bulk"))
        out(applied=m._reconcile_walk(force=True), counters=counters(m))
        """)
    assert r["applied"] is True and r["counters"] == [0, 0, 0]


def test_a_walk_whose_root_is_unreadable_never_replaces_the_index(run):
    r = run("""
        build()
        m = walked()
        m._save_cache()
        before = index_text()
        gone = monitor(os.path.join(ROOT, "gone_" + TAG))  # the root does not exist
        gone._file_count = 100
        gone._dir_info = {"": {"file_count": 100, "dir_count": 0, "total_size": 100}}
        out(plain=gone._reconcile_walk(), forced=gone._reconcile_walk(force=True),
            counters=counters(gone), index_untouched=(index_text() == before))
        """)
    assert r["plain"] is False and r["forced"] is False  # even force cannot accept it
    assert r["counters"][0] == 100 and r["index_untouched"] is True


# ---------------------------------------------------------------------------- per-folder correction
def test_a_folder_correction_lands_on_what_is_on_disk(run):
    r = run("""
        build()
        m = walked()
        put("d1/g1.txt", 100)
        put("d1/g2.txt", 100)
        os.remove(os.path.join(ROOT, "b.txt"))
        put("d1/newsub/n.txt", 7)
        shutil.rmtree(os.path.join(ROOT, "d1", "sub"))
        dirty = {"": ROOT, "d1": os.path.join(ROOT, "d1")}
        changed = m._correct_folders(dirty)
        again = m._correct_folders(dirty)
        fresh = monitor()._full_walk(silent=True)
        out(changed=changed, again=again, counters=counters(m),
            info={k: m.get_dir_info(k) for k in ("", "d1", "d1/newsub", "d1/sub")},
            same_as_fresh_walk=(m._dir_info == fresh["dir_info"]))
        """)
    assert r["changed"] is True and r["again"] is False  # idempotent
    assert r["counters"] == [5, 2, 220]
    assert r["info"] == {
        "": {"file_count": 5, "dir_count": 2, "total_size": 220},
        "d1": {"file_count": 4, "dir_count": 1, "total_size": 217},
        "d1/newsub": {"file_count": 1, "dir_count": 0, "total_size": 7},
        "d1/sub": None,
    }
    assert r["same_as_fresh_walk"] is True


def test_a_folder_that_vanished_is_corrected_through_its_parent(run):
    r = run("""
        build()
        m = walked()
        shutil.rmtree(os.path.join(ROOT, "d1", "sub"))
        changed = m._correct_folders({"d1/sub": os.path.join(ROOT, "d1", "sub")})
        out(changed=changed, counters=counters(m), d1=m.get_dir_info("d1"),
            sub=m.get_dir_info("d1/sub"))
        """)
    assert r["changed"] is True and r["counters"] == [3, 1, 18]
    assert r["d1"] == {"file_count": 1, "dir_count": 0, "total_size": 10}
    assert r["sub"] is None


def test_no_correction_is_made_before_the_first_walk_built_a_baseline(run):
    r = run("""
        build()
        m = monitor()
        changed = m._correct_folders({"d1": os.path.join(ROOT, "d1")})
        out(changed=changed, info=m._dir_info, counters=counters(m))
        """)
    assert r["changed"] is False and r["info"] == {} and r["counters"] == [0, 0, 0]


# ---------------------------------------------------------------------------- file index in step
def test_the_walk_and_the_load_keep_file_index_json_in_step(run):
    r = run("""
        for n in range(5):
            put(f"big/f{n}.txt", 1)
        for n in range(2):
            put(f"small/f{n}.txt", 1)
        m = walked()
        m._save_cache()
        on_disk = sorted(json.load(open(fi.FILE_INDEX_PATH, encoding="utf-8"))["dirs"])
        fm.file_index_manager._dirs.clear()                # forget it in memory
        emptied = fm.file_index_manager.get_indexed_dirs()
        loaded = monitor()._load_cache()
        out(on_disk=on_disk, emptied=emptied, loaded=loaded,
            reloaded=sorted(fm.file_index_manager.get_indexed_dirs()))
        """)
    assert r["on_disk"] == ["big"]  # 5 entries exceed the threshold of 3, 2 do not
    assert r["emptied"] == [] and r["loaded"] is True and r["reloaded"] == ["big"]


# ---------------------------------------------------------------------------- the app's own folders
def test_the_apps_own_folders_inside_the_root_are_ignored_but_not_lookalikes(run):
    r = run("""
        base = os.path.join(ROOT, "ign_" + TAG)
        root = os.path.join(base, "root")
        dirs = [os.path.join(root, "cache"), os.path.join(root, "db"),
                os.path.join(root + "x", "cache"), root,
                os.path.join(base, "elsewhere"), ""]
        got = fm._compute_ignored_prefixes(root, dirs)
        norm = lambda p: os.path.normcase(os.path.abspath(p))
        m = monitor(root)
        m._ignored_prefixes = got
        out(got_ok=(got == tuple(sorted([norm(dirs[0]), norm(dirs[1])]))),
            inside=m.is_ignored_path(os.path.join(root, "cache", "storage_index.json")),
            the_folder=m.is_ignored_path(os.path.join(root, "db")),
            lookalike=m.is_ignored_path(os.path.join(root, "cachex", "f.txt")),
            user_file=m.is_ignored_path(os.path.join(root, "docs", "f.txt")),
            outside=m.is_ignored_path(os.path.join(base, "elsewhere", "f.txt")))
        """)
    assert r["got_ok"] is True and r["inside"] is True and r["the_folder"] is True
    assert r["lookalike"] is False and r["user_file"] is False and r["outside"] is False
