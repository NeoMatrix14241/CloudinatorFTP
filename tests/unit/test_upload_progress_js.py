"""
5.44.1: the upload progress shown for a request in flight (static/js/index.js,
`_chunkShownBytes` / `_noteChunkRate` / `_makeChunkProgress`) must not move in whole-chunk steps.

`xhr.upload` 'progress' counts bytes handed to the browser's network stack, not bytes received
by the server; over HTTP/3 a whole 10 MB chunk is "sent" at once, so the bar went 10, 20, 30 MB.
The number shown is now the smallest of what the browser claims, rate x elapsed (rate = recent
confirmed chunk round trips) and 97% of the chunk, and never goes backwards (the running total
adds positive deltas only).

The REAL functions are cut out of index.js between the `@@chunk-progress-begin/end` markers and run
in Node (skipped when node is not installed); the second group reads the wiring as source.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INDEX_JS = Path(__file__).resolve().parents[2] / "static" / "js" / "index.js"
NODE = shutil.which("node")

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _block():
    text = INDEX_JS.read_text(encoding="utf-8")
    match = re.search(
        r"// @@chunk-progress-begin\n(.*?)// @@chunk-progress-end", text, re.S
    )
    assert match, "the @@chunk-progress markers are gone from index.js"
    return match.group(1)


def _run(script):
    """Run the cut-out block plus `script` (which must console.log one JSON value)."""
    program = (
        "let __now = 0;\n"
        "const performance = { now: () => __now };\n"
        "const calls = [];\n"
        "function updateItemProgress(id, pct, bytes) { calls.push([id, pct, bytes]); }\n"
        + _block()
        + script
    )
    result = subprocess.run(
        [NODE, "-e", program], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


MB = 1024 * 1024


@needs_node
def test_a_burst_from_the_browser_does_not_show_the_whole_chunk_at_once():
    # QUIC: `loaded` is the full chunk after 5 ms; the link really does 5 MB/s.
    out = _run(f"""
        _noteChunkRate(10*{MB}, 2000);              // a confirmed 10 MB chunk took 2 s -> 5 MB/s
        const shown = [];
        for (const ms of [5, 250, 500, 1000, 1500, 1900]) {{
            shown.push(_chunkShownBytes(10*{MB}, 10*{MB}, ms, _chunkRateEma));
        }}
        console.log(JSON.stringify(shown.map(b => +(b/{MB}).toFixed(2))));
        """)
    assert out[0] < 0.1  # not 10 at ms 5
    assert out == sorted(out)  # grows with time
    assert (
        4.5 < out[3] < 5.5 and out[-1] < 9.71
    )  # 1 s -> about 5 MB; never past the 97% cap


@needs_node
def test_accurate_browser_events_are_shown_as_they_are():
    out = _run(f"""
        _noteChunkRate(10*{MB}, 2000);              // 5 MB/s
        // the browser says 2 MB after 1 s: slower than the estimate (5 MB), so its number wins
        console.log(JSON.stringify(_chunkShownBytes(2*{MB}, 10*{MB}, 1000, _chunkRateEma)));
        """)
    assert out == 2 * MB


@needs_node
def test_without_a_measured_rate_the_claim_is_used_but_capped_below_the_chunk_end():
    out = _run(f"""
        console.log(JSON.stringify([
            _chunkShownBytes(3*{MB}, 10*{MB}, 100, 0),
            _chunkShownBytes(10*{MB}, 10*{MB}, 100, 0),
        ]));
        """)
    assert out[0] == 3 * MB
    assert out[1] == int(10 * MB * 0.97)  # 100% only comes with the server's answer


@needs_node
def test_the_reporter_never_goes_backwards_and_reports_cumulative_bytes_of_the_file():
    out = _run(f"""
        _noteChunkRate(10*{MB}, 2000);              // 5 MB/s
        const item = {{ id: 'f1' }};
        // second chunk of a 50 MB file: 10 MB are already confirmed
        const report = _makeChunkProgress(item, 10*{MB}, 10*{MB}, 50*{MB});
        __now = 1000; report(10*{MB});               // burst: estimate 5 MB wins
        __now = 1200; report(1*{MB});                // a LOWER claim must not pull the bar back
        __now = 2500; report(10*{MB});
        console.log(JSON.stringify(calls));
        """)
    cumulative = [c[2] for c in out]
    assert cumulative == sorted(cumulative), cumulative
    assert all(
        c >= 10 * MB for c in cumulative
    )  # the confirmed bytes of earlier chunks stay
    assert out[0][2] - 10 * MB == pytest.approx(5 * MB, abs=1)
    assert out[-1][2] - 10 * MB <= 10 * MB * 0.97
    assert all(0 <= c[1] <= 100 for c in out)


@needs_node
def test_small_requests_do_not_pollute_the_measured_rate():
    out = _run(f"""
        _noteChunkRate(50*1024, 300);                // a 50 KB file: latency, not throughput
        const afterSmall = _chunkRateEma;
        _noteChunkRate(10*{MB}, 1000);               // 10 MB/s
        _noteChunkRate(10*{MB}, 500);                // 20 MB/s -> EMA 15 MB/s
        console.log(JSON.stringify([afterSmall, Math.round(_chunkRateEma/{MB})]));
        """)
    assert out == [0, 15]


@needs_node
def test_a_reporter_done_records_the_round_trip():
    out = _run(f"""
        const item = {{ id: 'f2' }};
        const report = _makeChunkProgress(item, 0, 10*{MB}, 10*{MB});
        __now = 2000; report.done();                 // 10 MB confirmed after 2 s
        console.log(JSON.stringify(Math.round(_chunkRateEma/{MB}*10)/10));
        """)
    assert out == 5


# ----------------------------------------------------------------------------- the wiring


def _upload_single_file():
    text = INDEX_JS.read_text(encoding="utf-8")
    start = text.index("async function uploadSingleFile(item)")
    end = text.index("// Auto-cleanup old items periodically", start)
    return text[start:end]


def test_every_upload_request_reports_through_a_chunk_progress_reporter():
    body = _upload_single_file()
    assert "onFileProgress" not in body and "onChunkProgress" not in body
    # whole-file requests (first try, rename, overwrite) and chunk requests
    assert body.count("onProgress: progress") == 3
    assert "onProgress: chunkProgress" in body
    # the server's answer is the one confirmed measurement
    assert "progress.done();" in body and "chunkProgress.done();" in body


def test_a_new_upload_run_forgets_the_old_rate():
    text = INDEX_JS.read_text(encoding="utf-8")
    start = text.index("totalBytesUploaded = 0;\n    _chunkRateEma = 0;")
    assert "_speedSamples.length = 0" in text[start : start + 300]
