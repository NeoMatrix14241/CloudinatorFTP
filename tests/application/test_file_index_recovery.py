"""
file_index.py (cache/file_index.json): what happens when the cached folder listings are corrupt,
stale, from another version, or drift away from the disk. The module is run inside a SCRATCH COPY
of the project (own cache folder, own storage) with the same helper the other tests use for the
scratch database (`run_in_scratch`); no server and no file monitor are involved. THRESHOLD is
lowered to 3 inside each snippet so a "large" folder needs only 4 files; every snippet first
asserts that its cache and storage folders are inside the scratch copy.

Contracts tested (CLAUDE.md 4.58, 4.61, 4.65): a damaged or foreign index is dropped and rebuilt,
every record loaded from disk is re-scanned before it is served, a change that raised no event is
seen by the next read, an empty or partial walk never wipes the index, unchanged data does not
rewrite the JSON, and the on-demand audit reports and repairs drift.
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
    for _d in (fi.CACHE_DIR, ROOT):
        assert os.path.abspath(_d).startswith(cwd), "NOT inside the scratch copy: " + _d
    os.makedirs(fi.CACHE_DIR, exist_ok=True)
    for _n in os.listdir(fi.CACHE_DIR):
        _p = os.path.join(fi.CACHE_DIR, _n)
        if os.path.isfile(_p):  # ensure_dirs() makes sub-folders such as hls/; os.remove fails on them
            os.remove(_p)
    TAG = sys.argv[1]
    INDEX = fi.FILE_INDEX_PATH

    def folder(name, count, hidden=0):
        path = os.path.join(ROOT, name)
        os.makedirs(path, exist_ok=True)
        for n in range(count):
            with open(os.path.join(path, f"f{n:03d}.txt"), "wb") as f:
                f.write(b"x" * (n + 1))
        for n in range(hidden):
            with open(os.path.join(path, f".hidden{n}"), "wb") as f:
                f.write(b"h")
        return path

    def names(entries):
        return sorted(e["name"] for e in entries)

    def write_index(data):
        with open(INDEX, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def record(entry_names, **extra):
        rec = {
            "entry_count": len(entry_names),
            "indexed_at": time.time(),
            "dir_mtime_ns": None,
            "entries": [
                {"name": n, "is_dir": False, "size": 1, "modified": 1.0} for n in entry_names
            ],
        }
        rec.update(extra)
        return rec

    def index_text():
        with open(INDEX, encoding="utf-8") as f:
            return f.read()

    def out(**kw):
        print("RESULT=" + json.dumps(kw, default=str))
    """)


@pytest.fixture(scope="module")
def lab(scratch_tools, tmp_path_factory):
    root = tmp_path_factory.mktemp("index_lab") / "app"
    scratch_tools.build(root, port=scratch_tools.free_port())
    assert scratch_tools.paths_outside(root) == []
    return root


@pytest.fixture(scope="module")
def run(lab, scratch_tools):
    def _run(body):
        tag = uuid.uuid4().hex[:8]
        stdout = scratch_tools.run_in_scratch(lab, PRELUDE + textwrap.dedent(body), tag)
        lines = [ln for ln in stdout.splitlines() if ln.startswith("RESULT=")]
        assert lines, "the snippet printed no RESULT line:\n" + stdout[-800:]
        result = json.loads(lines[-1][len("RESULT=") :])
        result["tag"] = tag
        return result

    return _run


# ---------------------------------------------------------------------------- damaged files
@pytest.mark.parametrize(
    "garbage", ["{not json", "", "[]", '{"version": 2, "threshold": 3, "dirs": []}']
)
def test_a_damaged_index_file_is_ignored_and_the_next_walk_rebuilds_it(run, garbage):
    r = run(f"""
        write_index({garbage!r})
        m = fi.FileIndexManager()
        loaded = m.load()
        stats_after_load = m.get_stats()["indexed_folders"]
        path = folder(f"idx_{{TAG}}", 5)
        m.build_from_walk({{f"idx_{{TAG}}": fi._scan_folder_entries(path)}})
        data = json.loads(index_text())
        again = fi.FileIndexManager()
        out(loaded=loaded, stats_after_load=stats_after_load,
            version=data["version"], threshold=data["threshold"],
            keys=sorted(data["dirs"]), count=data["dirs"][f"idx_{{TAG}}"]["entry_count"],
            reload=again.load(), indexed=again.get_indexed_dirs())
        """)
    assert r["loaded"] is False and r["stats_after_load"] == 0
    assert r["version"] == 2 and r["threshold"] == 3
    assert r["keys"] == [f"idx_{r['tag']}"] and r["count"] == 5
    assert r["reload"] is True and r["indexed"] == [f"idx_{r['tag']}"]


@pytest.mark.parametrize(
    "header", ['"version": 99, "threshold": 3', '"version": 2, "threshold": 5']
)
def test_an_index_of_another_version_or_threshold_is_discarded(run, header):
    r = run(f"""
        path = folder(f"idx_{{TAG}}", 5)
        write_index('{{{header}, "dirs": {{"idx_' + TAG + '": ' +
                    json.dumps(record(sorted(os.listdir(path)))) + '}}}}')
        m = fi.FileIndexManager()
        out(loaded=m.load(), indexed=m.get_indexed_dirs())
        """)
    assert r["loaded"] is False and r["indexed"] == []


def test_invalid_records_are_dropped_and_the_valid_one_is_kept(run):
    r = run("""
        good = [f"a{n}" for n in range(4)]
        bad_count = record(good, entry_count=99)
        too_small = record(["a", "b"])
        bad_entry = record(good)
        bad_entry["entries"][0]["is_dir"] = "yes"
        no_name = record(good)
        no_name["entries"][1] = {"is_dir": False}
        write_index({"version": 2, "threshold": 3, "dirs": {
            "ok": record(good), "bad_count": bad_count, "too_small": too_small,
            "bad_entry": bad_entry, "no_name": no_name, "/leading": record(good),
            "trailing/": record(good), "not_a_dict": [1, 2, 3],
        }})
        m = fi.FileIndexManager()
        out(loaded=m.load(), indexed=sorted(m.get_indexed_dirs()))
        """)
    assert r["loaded"] is True and r["indexed"] == ["ok"]


def test_old_temp_files_of_a_crashed_save_are_swept_and_others_are_left_alone(run):
    r = run("""
        def make(name, age_secs):
            p = os.path.join(fi.CACHE_DIR, name)
            with open(p, "w") as f:
                f.write("x")
            old = time.time() - age_secs
            os.utime(p, (old, old))
        make("file_index_dead.tmp", 7200)
        make("file_index_recent.tmp", 10)
        make("other_module_dead.tmp", 7200)
        fi.FileIndexManager().load()
        out(left=sorted(n for n in os.listdir(fi.CACHE_DIR)
                        if os.path.isfile(os.path.join(fi.CACHE_DIR, n))))
        """)
    assert r["left"] == ["file_index_recent.tmp", "other_module_dead.tmp"]


# ---------------------------------------------------------------------------- stale rows
def test_a_restart_never_serves_rows_from_before_the_restart(run):
    r = run("""
        path = folder(f"idx_{TAG}", 5)
        write_index({"version": 2, "threshold": 3, "dirs": {
            f"idx_{TAG}": record([f"ghost{n}" for n in range(6)])}})
        m = fi.FileIndexManager()
        loaded = m.load()
        unverified = m.get_stats()["unverified_folders"]
        first = names(m.get_entries(f"idx_{TAG}"))
        out(loaded=loaded, unverified=unverified, first=first,
            real=sorted(os.listdir(path)), after=m.get_stats()["unverified_folders"])
        """)
    assert r["loaded"] is True and r["unverified"] == 1
    assert r["first"] == r["real"]  # the real listing, never the ghosts
    assert r["after"] == 0


def test_a_change_that_raised_no_event_is_seen_by_the_next_read(run):
    r = run("""
        rel = f"idx_{TAG}"
        path = folder(rel, 5)
        m = fi.FileIndexManager()
        m.update_folder(rel, path)
        before = names(m.get_entries(rel))
        old_ns = os.stat(path).st_mtime_ns
        with open(os.path.join(path, "added_later.txt"), "wb") as f:
            f.write(b"new")
        # force a different folder mtime whatever the clock resolution is
        os.utime(path, ns=(old_ns + 10**9, old_ns + 10**9))
        after = names(m.get_entries(rel))
        os.remove(os.path.join(path, "f000.txt"))
        os.utime(path, ns=(old_ns + 2 * 10**9, old_ns + 2 * 10**9))
        after_remove = names(m.get_entries(rel))
        out(before=before, after=after, after_remove=after_remove)
        """)
    assert "added_later.txt" not in r["before"]
    assert "added_later.txt" in r["after"]
    assert (
        "f000.txt" not in r["after_remove"] and "added_later.txt" in r["after_remove"]
    )


def test_an_unchanged_folder_is_answered_from_the_cache(run):
    r = run("""
        rel = f"idx_{TAG}"
        path = folder(rel, 5)
        m = fi.FileIndexManager()
        m.update_folder(rel, path)
        first = m.get_entries(rel)
        second = m.get_entries(rel)
        out(same_object=first is second, count=len(first))
        """)
    assert r["same_object"] is True and r["count"] == 5


def test_a_folder_that_shrinks_or_vanishes_leaves_the_index(run):
    r = run("""
        small, gone = f"small_{TAG}", f"gone_{TAG}"
        sp, gp = folder(small, 5), folder(gone, 5)
        m = fi.FileIndexManager()
        m.update_folder(small, sp)
        m.update_folder(gone, gp)
        indexed_before = sorted(m.get_indexed_dirs())
        for n in range(3):
            os.remove(os.path.join(sp, f"f{n:03d}.txt"))
        m.update_folder(small, sp)
        shutil.rmtree(gp)
        vanished = m.get_entries(gone)
        out(before=indexed_before, after=sorted(m.get_indexed_dirs()),
            small_entries=m.get_entries(small), vanished=vanished)
        """)
    assert len(r["before"]) == 2 and r["after"] == []
    assert r["small_entries"] is None and r["vanished"] is None


def test_hidden_entries_are_excluded_and_folders_sort_first(run):
    r = run("""
        rel = f"idx_{TAG}"
        path = folder(rel, 4, hidden=2)
        os.makedirs(os.path.join(path, "Zdir"))
        m = fi.FileIndexManager()
        m.update_folder(rel, path)
        entries = m.get_entries(rel)
        out(order=[(e["name"], e["is_dir"], e["size"]) for e in entries])
        """)
    assert r["order"][0] == ["Zdir", True, None]
    assert [o[0] for o in r["order"][1:]] == [
        "f000.txt",
        "f001.txt",
        "f002.txt",
        "f003.txt",
    ]


# ---------------------------------------------------------------------------- walks
def test_an_empty_or_partial_walk_never_wipes_a_folder_that_is_still_large(run):
    r = run("""
        rel = f"idx_{TAG}"
        path = folder(rel, 5)
        m = fi.FileIndexManager()
        m.update_folder(rel, path)
        m.build_from_walk({})                               # empty walk
        after_empty = m.get_indexed_dirs()
        m.build_from_walk({f"other_{TAG}": [{"name": "x"}]})  # partial walk, folder missing
        after_partial = m.get_indexed_dirs()
        for n in range(3):
            os.remove(os.path.join(path, f"f{n:03d}.txt"))
        m.build_from_walk({f"other_{TAG}": [{"name": "x"}]})  # now it is small: dropped
        out(rel=rel, after_empty=after_empty, after_partial=after_partial,
            after_shrunk=m.get_indexed_dirs())
        """)
    assert r["after_empty"] == [r["rel"]] and r["after_partial"] == [r["rel"]]
    assert r["after_shrunk"] == []


def test_a_walk_installs_what_is_on_disk_not_what_the_walk_saw(run):
    r = run("""
        rel = f"idx_{TAG}"
        path = folder(rel, 6)
        stale_walk = fi._scan_folder_entries(path)
        for n in range(2):
            os.remove(os.path.join(path, f"f{n:03d}.txt"))   # changes after the walk saw it
        m = fi.FileIndexManager()
        m.build_from_walk({rel: stale_walk})
        out(names=names(m.get_entries(rel)), real=sorted(os.listdir(path)),
            build=m._last_build["indexed_folders"])
        """)
    assert r["names"] == r["real"] and r["build"] == 1


# ---------------------------------------------------------------------------- saving
def test_unchanged_data_does_not_rewrite_the_json_but_a_change_does(run):
    r = run("""
        rel = f"idx_{TAG}"
        path = folder(rel, 5)
        m = fi.FileIndexManager()
        m.build_from_walk({rel: fi._scan_folder_entries(path)})
        first_text, first_ns = index_text(), os.stat(INDEX).st_mtime_ns
        time.sleep(0.05)
        m.save()                                  # nothing changed
        m.update_folder(rel, path)                # re-scan: only indexed_at differs
        m.save()
        same_text, same_ns = index_text(), os.stat(INDEX).st_mtime_ns
        with open(os.path.join(path, "new.txt"), "wb") as f:
            f.write(b"n")
        m.update_folder(rel, path)
        m.save()
        changed = json.loads(index_text())
        out(untouched=(first_text == same_text and first_ns == same_ns),
            new_count=changed["dirs"][rel]["entry_count"],
            tmp_left=[n for n in os.listdir(fi.CACHE_DIR) if n.endswith(".tmp")])
        """)
    assert r["untouched"] is True
    assert r["new_count"] == 6
    assert r["tmp_left"] == []


def test_a_deleted_index_file_is_written_again_even_if_nothing_changed(run):
    r = run("""
        rel = f"idx_{TAG}"
        path = folder(rel, 5)
        m = fi.FileIndexManager()
        m.build_from_walk({rel: fi._scan_folder_entries(path)})
        os.remove(INDEX)
        m.save()
        out(exists=os.path.exists(INDEX), keys=sorted(json.loads(index_text())["dirs"]))
        """)
    assert r["exists"] is True and len(r["keys"]) == 1


# ---------------------------------------------------------------------------- audit and tree edits
def test_verify_all_reports_drift_and_repair_fixes_it(run):
    r = run("""
        rel, gone = f"idx_{TAG}", f"gone_{TAG}"
        path, gone_path = folder(rel, 5), folder(gone, 5)
        m = fi.FileIndexManager()
        m.update_folder(rel, path)
        m.update_folder(gone, gone_path)
        for n in range(2):
            with open(os.path.join(path, f"extra{n}.txt"), "wb") as f:
                f.write(b"e")
        os.remove(os.path.join(path, "f000.txt"))
        report = m.verify_all()
        unrepaired = names(m._dirs[rel]["entries"])
        shutil.rmtree(gone_path)
        repaired = m.verify_all(repair=True)
        clean = m.verify_all()
        out(report=report, unrepaired=unrepaired, repaired=repaired, clean=clean,
            indexed=m.get_indexed_dirs(), rel=rel, final=names(m._dirs[rel]["entries"]),
            real=sorted(os.listdir(path)))
        """)
    drift = {d["folder"]: d for d in r["report"]["details"]}
    assert r["report"]["checked"] == 2 and r["report"]["drifted"] == 1
    assert (drift[r["rel"]]["added"], drift[r["rel"]]["removed"]) == (2, 1)
    assert "extra0.txt" not in r["unrepaired"]  # a plain audit repairs nothing
    assert r["repaired"]["unreadable"] == 1 and r["indexed"] == [r["rel"]]
    assert r["clean"]["drifted"] == 0 and r["clean"]["unreadable"] == 0
    assert r["final"] == r["real"]


def test_renaming_and_deleting_a_folder_keep_the_whole_subtree_consistent(run):
    r = run("""
        for name in ("A", "A/sub", "B"):
            folder(f"{name}_{TAG}" if name != "A/sub" else f"A_{TAG}/sub", 5)
        m = fi.FileIndexManager()
        for rel in (f"A_{TAG}", f"A_{TAG}/sub", f"B_{TAG}"):
            m.update_folder(rel, os.path.join(ROOT, rel))
        start = sorted(m.get_indexed_dirs())
        m.rename_folder(f"A_{TAG}", f"C_{TAG}")
        renamed = sorted(m.get_indexed_dirs())
        m.remove_folder(f"C_{TAG}")
        removed = sorted(m.get_indexed_dirs())
        # a name that only STARTS the same must not be treated as a child
        m.update_folder(f"B_{TAG}", os.path.join(ROOT, f"B_{TAG}"))
        m.remove_folder(f"B")
        out(start=start, renamed=renamed, removed=removed,
            sibling_kept=sorted(m.get_indexed_dirs()))
        """)
    tag = r["tag"]
    assert r["start"] == sorted([f"A_{tag}", f"A_{tag}/sub", f"B_{tag}"])
    assert r["renamed"] == sorted([f"B_{tag}", f"C_{tag}", f"C_{tag}/sub"])
    assert r["removed"] == [f"B_{tag}"]
    assert r["sibling_kept"] == [f"B_{tag}"]
