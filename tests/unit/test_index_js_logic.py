"""
static/js/index.js: the decision logic that has regressed before, run as the REAL source in Node
(5.44.3, option B of TESTING_STRATEGY.md 15: plain Node, no jsdom, no package.json).

Three pieces, each a pure function of its inputs plus a few globals that the test supplies:

* `_resolveFileConflict` (+ `_overwriteDecisions`, `_LOOSE_CONFLICT_KEY`, `_conflictPromptTail`):
  "Overwrite all conflicts" used to be remembered for nobody when the files were not part of a
  folder upload (5.43), and parallel 409s opened stacked dialogs. The dialog itself
  (`_promptOverwrite`) is replaced by a stub that records and answers.
* `_classifyChangedDirs` (4.66): which changed folders mean "re-read the listing" and which only
  mean "re-read one size cell". A wrong answer made every size cell flash, or hid a change.
* `_sameListing` (4.66): the check that lets an SSE-triggered refresh skip the table rebuild.

Nothing in the page is started. The functions are cut out of index.js by NAME: from the
`function` line to the first line that is just `}` (the file is formatted that way), so index.js
needs no markers and its SRI hash is untouched. If a function is renamed or reformatted, the
extraction fails with a message that names it. Skipped when node is not installed (CI has it, the
`node --check` step of qa.py needs it as well).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INDEX_JS = Path(__file__).resolve().parents[2] / "static" / "js" / "index.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

_TEXT = INDEX_JS.read_text(encoding="utf-8") if INDEX_JS.is_file() else ""


def _function(name):
    """`[async ]function name(...) { ... }` at column 0, up to the first `}` at column 0."""
    match = re.search(
        rf"^(?:async )?function {re.escape(name)}\(.*?^\}}$", _TEXT, re.S | re.M
    )
    assert match, f"function {name} not found in index.js (renamed or reformatted?)"
    return match.group(0)


def _statement(name):
    """A one-line top-level `const name = ...;`."""
    match = re.search(rf"^const {re.escape(name)} = .*;[^\n]*$", _TEXT, re.M)
    assert match, f"const {name} not found in index.js (renamed or reformatted?)"
    return match.group(0)


def _node(program):
    """Run a program that console.logs ONE JSON value; return that value."""
    result = subprocess.run(
        [NODE, "-e", program], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ------------------------------------------------------------------ _resolveFileConflict
def _conflict_program(script):
    return (
        "\n".join(
            [
                _statement("_overwriteDecisions"),
                _statement("_LOOSE_CONFLICT_KEY"),
                _statement("_conflictPromptTail"),
                # The dialog: records each question, counts how many are open at once, and
                # answers from `answers` after a tick, like a person clicking.
                "const prompts = []; let open = 0, maxOpen = 0; const answers = [];",
                "async function _promptOverwrite(filename, destPath) {",
                "  prompts.push(filename); open++; maxOpen = Math.max(maxOpen, open);",
                "  await new Promise(r => setTimeout(r, 5));",
                "  open--;",
                "  const a = answers.shift();",
                "  if (a === 'THROW') throw new Error('dialog failed');",
                "  return a;",
                "}",
                _function("_resolveFileConflict"),
            ]
        )
        + "\n(async () => {\n"
        + script
        + "\n})();\n"
    )


def test_overwrite_all_is_remembered_for_loose_files_and_asked_only_once():
    # The 5.43 bug: loose files have no _groupId, the decision was stored for nobody and every
    # file after the first one opened its own dialog (or was silently not overwritten).
    out = _node(_conflict_program("""
        answers.push('overwrite-all');
        const items = [{}, {}, {}];
        const got = await Promise.all(items.map((it, i) => _resolveFileConflict(it, 'f' + i, '')));
        const later = await _resolveFileConflict({}, 'late', '');
        console.log(JSON.stringify({got, later, prompts, saved: [..._overwriteDecisions]}));
        """))
    assert out["got"] == ["overwrite"] * 3
    assert out["later"] == "overwrite"
    assert out["prompts"] == ["f0"], "one dialog for the whole batch"
    assert out["saved"] == [["__loose__", "overwrite"]]


def test_parallel_conflicts_are_asked_one_at_a_time():
    out = _node(_conflict_program("""
        answers.push('overwrite-one', 'skip-one', 'rename-one');
        const got = await Promise.all(['a', 'b', 'c'].map(n => _resolveFileConflict({}, n, '')));
        console.log(JSON.stringify({got, prompts, maxOpen, saved: [..._overwriteDecisions]}));
        """))
    assert out["got"] == ["overwrite", "skip", "rename"]
    assert out["prompts"] == [
        "a",
        "b",
        "c",
    ], "in arrival order, each answer applies to its file"
    assert out["maxOpen"] == 1, "a second modal never stacks on top of the first"
    assert out["saved"] == [], "'one' answers are not remembered"


@pytest.mark.parametrize(
    ("answer", "decision"),
    [("skip-all", "skip"), ("rename-all", "rename"), ("overwrite-all", "overwrite")],
)
def test_every_all_answer_is_remembered_and_applied_to_the_rest(answer, decision):
    out = _node(_conflict_program(f"""
        answers.push('{answer}');
        const first = await _resolveFileConflict({{}}, 'one', '');
        const second = await _resolveFileConflict({{}}, 'two', '');
        console.log(JSON.stringify({{first, second, prompts}}));
        """))
    assert out["first"] == decision and out["second"] == decision
    assert out["prompts"] == ["one"]


def test_folder_uploads_keep_a_decision_per_folder_and_apart_from_loose_files():
    out = _node(_conflict_program("""
        answers.push('overwrite-all', 'skip-all', 'rename-one');
        const a1 = await _resolveFileConflict({_groupId: 'A'}, 'a1', '');
        const a2 = await _resolveFileConflict({_groupId: 'A'}, 'a2', '');   // no dialog
        const b1 = await _resolveFileConflict({_groupId: 'B'}, 'b1', '');   // its own dialog
        const l1 = await _resolveFileConflict({}, 'l1', '');                // not A's or B's
        console.log(JSON.stringify({a1, a2, b1, l1, prompts}));
        """))
    assert [out["a1"], out["a2"], out["b1"], out["l1"]] == [
        "overwrite",
        "overwrite",
        "skip",
        "rename",
    ]
    assert out["prompts"] == ["a1", "b1", "l1"]


def test_a_dialog_that_throws_does_not_block_the_next_conflict():
    out = _node(_conflict_program("""
        answers.push('THROW', 'overwrite-all');
        let failed = false;
        try { await _resolveFileConflict({}, 'x', ''); } catch (e) { failed = e.message; }
        const next = await _resolveFileConflict({}, 'y', '');
        console.log(JSON.stringify({failed, next, prompts}));
        """))
    assert out["failed"] == "dialog failed", "the caller still sees the failure"
    assert out["next"] == "overwrite", "the chain stays alive"
    assert out["prompts"] == ["x", "y"]


# ------------------------------------------------------------------ _classifyChangedDirs
def _classify(view, data):
    out = _node(
        "\n".join(
            [
                f"const currentPath = {json.dumps(view)};",
                _function("_classifyChangedDirs"),
                f"const r = _classifyChangedDirs({json.dumps(data)});",
                "console.log(JSON.stringify({known: r.known, listing: r.listing,"
                " children: r.children === null ? null : [...r.children].sort()}));",
            ]
        )
    )
    return out["known"], out["listing"], out["children"]


@pytest.mark.parametrize(
    ("view", "changed", "listing", "children"),
    [
        # at the root: a deep change marks only the top-level sub-folder, the listing is unchanged
        ("", ["a/b/c"], False, ["a"]),
        # a direct child of the view changed: its Date modified may have moved, so re-read
        ("", ["a"], True, ["a"]),
        # the view itself changed (a file was added or removed in it)
        ("", [""], True, []),
        ("a", ["a"], True, []),
        ("a", ["a/b/c"], False, ["a/b"]),
        ("a", ["a/b"], True, ["a/b"]),
        ("a/b", ["a/b/c/d", "a/x"], False, ["a/b/c"]),
        # unrelated folders and look-alike prefixes do not count
        ("a", ["other", "ab", "ab/c"], False, []),
        ("a/b", ["a", "a/bc"], False, []),
        # slashes around the view are ignored
        ("/a/", ["a/b"], True, ["a/b"]),
        ("", [], False, []),
    ],
)
def test_changed_folders_are_classified_against_the_folder_on_screen(
    view, changed, listing, children
):
    known, got_listing, got_children = _classify(view, {"changed_dirs": changed})
    assert known is True
    assert got_listing is listing
    assert got_children == children


def test_a_truncated_batch_means_re_read_the_listing_and_every_size_cell():
    assert _classify("a", {"changed_dirs": ["x"], "changed_dirs_truncated": True}) == (
        True,
        True,
        None,
    )


@pytest.mark.parametrize(
    "data", [None, {}, {"changed_dirs": None}, {"changed_dirs": "a"}]
)
def test_a_message_without_a_folder_list_is_unknown(data):
    assert _classify("a", data) == (False, False, [])


# ------------------------------------------------------------------ _sameListing
def _same(screen_path, screen_files, new_files, path, vt_raises=False):
    getall = (
        "() => { throw new Error('boom'); }"
        if vt_raises
        else f"() => {json.dumps(screen_files)}"
    )
    return _node(
        "\n".join(
            [
                f"const VT = {{ getPath: () => {json.dumps(screen_path)}, getAll: {getall} }};",
                _function("_sameListing"),
                f"console.log(JSON.stringify(_sameListing({json.dumps(new_files)}, {json.dumps(path)})));",
            ]
        )
    )


def _f(name, size=1, modified=10, is_dir=False):
    return {"name": name, "size": size, "modified": modified, "is_dir": is_dir}


SCREEN = [_f("a.txt"), _f("b.txt", 5, 20), _f("d", 0, 30, True)]


def test_an_identical_listing_is_the_same_whatever_the_order():
    assert _same("docs", SCREEN, list(reversed(SCREEN)), "docs") is True


def test_the_path_is_compared_without_slash_style_or_edge_slashes():
    assert _same("docs/sub", SCREEN, SCREEN, "/docs\\sub/") is True
    assert _same("docs", SCREEN, SCREEN, "other") is False
    assert _same("", SCREEN, SCREEN, "/") is True


def test_a_folder_size_is_ignored_but_a_file_size_is_not():
    folder_bigger = [_f("a.txt"), _f("b.txt", 5, 20), _f("d", 999, 30, True)]
    assert (
        _same("p", SCREEN, folder_bigger, "p") is True
    ), "a folder's size comes from dir_info"
    file_bigger = [_f("a.txt", 2), _f("b.txt", 5, 20), _f("d", 0, 30, True)]
    assert _same("p", SCREEN, file_bigger, "p") is False


@pytest.mark.parametrize(
    "new_files",
    [
        [_f("a.txt"), _f("b.txt", 5, 20)],  # one removed
        [*SCREEN, _f("c.txt")],  # one added
        [_f("a.txt"), _f("b.txt", 5, 21), _f("d", 0, 30, True)],  # modified time moved
        [
            _f("a.txt"),
            _f("b.txt", 5, 20),
            _f("d", 0, 31, True),
        ],  # a folder's date moved
        [
            _f("a.txt"),
            _f("b.txt", 5, 20),
            _f("d", 0, 30, False),
        ],  # a folder became a file
        [
            _f("a.txt"),
            _f("b.txt", 5, 20),
            _f("renamed", 0, 30, True),
        ],  # same count, new name
        None,
    ],
)
def test_any_visible_difference_means_the_listing_is_not_the_same(new_files):
    assert _same("p", SCREEN, new_files, "p") is False


def test_a_failure_while_comparing_means_not_the_same_so_the_table_is_rebuilt():
    assert _same("p", SCREEN, SCREEN, "p", vt_raises=True) is False
