"""
static/js/shell.js: the page lifecycle, run as the REAL source in Node (plain Node, no jsdom, like
test_index_js_logic.py). Skipped when node is not installed (CI has it).

`createLifecycle()` is what lets index.js be started again after a login and ended at a logout.
The guarantee under test: after `dispose()` NOTHING the page started is still running, and the
old page cannot start anything new. A fake `window` / `document` stands in for the browser; the
fakes record what is registered, so the test can see what is left over.

Cases (each is one test below):
  timers_and_frames        timeouts, intervals and animation frames are cleared; late calls are refused
  listeners                listeners are removed with their capture flag; unlisten forgets one
  on_ready                 DOMContentLoaded handlers are removed; an already loaded document runs at once
  fetch_in_flight          a fetch in flight is aborted; a fetch after dispose is refused
  streams_and_xhr          EventSource closed, XHR aborted, new ones refused
  observers                observers disconnected
  patch_export_own         patched globals restored, exports and owned globals removed
  disposer_failure         a throwing disposer makes the report "not clean" (the shell then navigates)
  idempotent               a second dispose() returns the first report
  register_and_debug       registerPage / debug / view as the path names it
  zombie_closures          a closure kept from the old page can neither schedule nor listen nor fetch
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SHELL_JS = Path(__file__).resolve().parents[2] / "static" / "js" / "shell.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

CASES = (
    "timers_and_frames",
    "listeners",
    "on_ready",
    "fetch_in_flight",
    "streams_and_xhr",
    "observers",
    "patch_export_own",
    "disposer_failure",
    "idempotent",
    "register_and_debug",
    "zombie_closures",
)

PROGRAM = r"""
const vm = require('vm');
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');

function makeEnv() {
    const env = { timers: new Map(), next: 1, es: [], xhr: [], mo: 0, docListeners: [], docRemoved: [] };
    const win = {
        setTimeout: (fn) => { const id = env.next++; env.timers.set(id, { fn, kind: 't' }); return id; },
        clearTimeout: (id) => { env.timers.delete(id); },
        setInterval: (fn) => { const id = env.next++; env.timers.set(id, { fn, kind: 'i' }); return id; },
        clearInterval: (id) => { env.timers.delete(id); },
        requestAnimationFrame: (cb) => { const id = env.next++; env.timers.set(id, { fn: cb, kind: 'f' }); return id; },
        cancelAnimationFrame: (id) => { env.timers.delete(id); },
        location: { pathname: '/login', search: '', href: 'http://t/login', replace() {} },
        history: { replaceState() {} },
        addEventListener() {},
        scrollTo() {},
        pending: [],
        fetch: (url, init) => new Promise((resolve, reject) => {
            win.pending.push(url);
            if (init && init.signal) {
                init.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
            }
        }),
        EventSource: class { constructor(url) { this.url = url; this.readyState = 1; env.es.push(this); } close() { this.readyState = 2; } },
        XMLHttpRequest: class { constructor() { this.aborted = false; env.xhr.push(this); } addEventListener() {} abort() { this.aborted = true; } },
        MutationObserver: class { constructor(cb) { this.cb = cb; } observe() {} disconnect() { env.mo += 1; } },
    };
    win.window = win;
    const doc = {
        body: null,
        readyState: 'complete',
        addEventListener(type, fn, opts) { env.docListeners.push([type, fn, opts]); },
        removeEventListener(type, fn, opts) { env.docRemoved.push([type, fn, opts]); },
        querySelectorAll() { return []; },
    };
    const sandbox = { window: win, document: doc, URL, AbortController, DOMException, Promise, console, Headers,
        DOMParser: class {}, BroadcastChannel: undefined };
    vm.createContext(sandbox);
    vm.runInContext(source, sandbox);
    return { env, win, doc, shell: win.CloudinatorShell };
}

const cases = {};
const target = () => {
    const t = { added: [], removed: [] };
    t.addEventListener = (type, fn, opts) => t.added.push([type, fn, opts]);
    t.removeEventListener = (type, fn, capture) => t.removed.push([type, fn, capture]);
    return t;
};
const eq = (a, b, what) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(what + ': ' + JSON.stringify(a) + ' !== ' + JSON.stringify(b)); };
const ok = (v, what) => { if (!v) throw new Error('not true: ' + what); };

cases.timers_and_frames = async () => {
    const { env, shell } = makeEnv();
    const life = shell.createLifecycle('t');
    const g = life.globals;
    g.setTimeout(() => {}, 5); g.setInterval(() => {}, 5); g.requestAnimationFrame(() => {});
    eq([life.stats().timeouts, life.stats().intervals, life.stats().frames], [1, 1, 1], 'tracked');
    const cancelled = g.setTimeout(() => {}, 5); g.clearTimeout(cancelled);
    eq(life.stats().timeouts, 1, 'clearTimeout forgets');
    const report = life.dispose();
    ok(report.clean, 'clean'); eq(env.timers.size, 0, 'native timers left');
    eq(g.setTimeout(() => {}, 1), 0, 'late setTimeout');
    eq(g.setInterval(() => {}, 1), 0, 'late setInterval');
    eq(env.timers.size, 0, 'late timers were not scheduled');
};

cases.listeners = async () => {
    const { shell } = makeEnv();
    const life = shell.createLifecycle('t');
    const t = target(); const a = () => {}; const b = () => {}; const c = () => {};
    life.listen(t, 'click', a, true);
    life.listen(t, 'keyup', b, { capture: false, once: true });
    life.listen(t, 'scroll', c);
    life.unlisten(t, 'scroll', c);
    eq(life.stats().listeners, 2, 'two tracked');
    life.dispose();
    eq(t.removed.map((r) => [r[0], r[2]]).filter((r) => r[0] !== 'scroll'), [['click', true], ['keyup', false]], 'removed with capture');
    life.listen(t, 'late', a);
    eq(t.added.filter((x) => x[0] === 'late').length, 0, 'late listen refused');
};

cases.on_ready = async () => {
    const loading = makeEnv();
    loading.doc.readyState = 'loading';
    const l1 = loading.shell.createLifecycle('t');
    let ran = 0; l1.onReady(() => { ran += 1; });
    eq(loading.env.docListeners.filter((x) => x[0] === 'DOMContentLoaded').length, 2, 'shell + page listener');
    l1.dispose();
    eq(loading.env.docRemoved.filter((x) => x[0] === 'DOMContentLoaded').length, 1, 'page listener removed');
    const done = makeEnv();
    const l2 = done.shell.createLifecycle('t');
    l2.onReady(() => { ran += 10; });
    eq(l2.stats().timeouts, 1, 'scheduled through the tracked timer');
    for (const t of done.env.timers.values()) t.fn();
    eq(ran, 10, 'ran once the document was loaded');
};

cases.fetch_in_flight = async () => {
    const { win, shell } = makeEnv();
    const life = shell.createLifecycle('t');
    const inFlight = life.globals.fetch('/api/files/');
    eq(life.stats().fetches, 1, 'tracked');
    life.dispose();
    let name = null; try { await inFlight; } catch (e) { name = e.name; }
    eq(name, 'AbortError', 'aborted');
    let late = null; try { await life.globals.fetch('/api/files/'); } catch (e) { late = e.name; }
    eq(late, 'AbortError', 'late fetch refused');
    eq(win.pending.length, 1, 'only the first request was ever sent');
};

cases.streams_and_xhr = async () => {
    const { env, shell } = makeEnv();
    const life = shell.createLifecycle('t');
    const es = new life.globals.EventSource('/stream'); const x = new life.globals.XMLHttpRequest();
    eq([life.stats().eventSources, life.stats().xhrs], [1, 1], 'tracked');
    es.close(); eq(life.stats().eventSources, 0, 'close() forgets');
    const es2 = new life.globals.EventSource('/stream2');
    const report = life.dispose();
    ok(report.clean, 'clean'); eq(es2.readyState, 2, 'stream closed'); ok(x.aborted, 'xhr aborted');
    let refused = false; try { new life.globals.EventSource('/s3'); } catch (e) { refused = true; }
    ok(refused, 'new EventSource refused'); eq(env.es.length, 2, 'no third stream was opened');
};

cases.observers = async () => {
    const { env, shell } = makeEnv();
    const life = shell.createLifecycle('t');
    const o = new life.globals.MutationObserver(() => {});
    eq(life.stats().observers, 1, 'tracked');
    life.dispose();
    eq(env.mo, 1, 'disconnected'); ok(o, 'observer object');
    eq(life.globals.ResizeObserver, undefined, 'missing in the environment stays missing');
};

cases.patch_export_own = async () => {
    const { win, shell } = makeEnv();
    const life = shell.createLifecycle('t');
    const original = win.fetch; win.keep = 'mine';
    life.patch(win, 'fetch', () => 'wrapped');
    life.patch(win, 'keep', 'overwritten');
    life.exportGlobals({ navigateToFolder: () => 1 });
    win.CloudinatorUpload = {}; life.ownGlobals(['CloudinatorUpload']);
    ok(win.fetch !== original && typeof win.navigateToFolder === 'function', 'published');
    const report = life.dispose();
    ok(report.clean, 'clean');
    ok(win.fetch === original, 'fetch restored'); eq(win.keep, 'mine', 'value restored');
    ok(!('navigateToFolder' in win), 'export removed'); ok(!('CloudinatorUpload' in win), 'owned removed');
};

cases.disposer_failure = async () => {
    const { shell } = makeEnv();
    const life = shell.createLifecycle('t');
    let second = false;
    life.onDispose(() => { second = true; });
    life.onDispose(() => { throw new Error('boom'); });
    const report = life.dispose();
    eq(report.clean, false, 'not clean'); eq(report.errors.length, 1, 'one error'); ok(second, 'other disposers still ran');
};

cases.idempotent = async () => {
    const { shell } = makeEnv();
    const life = shell.createLifecycle('t');
    const first = life.dispose();
    ok(life.dispose() === first, 'same report'); ok(life.isDisposed(), 'disposed');
};

cases.register_and_debug = async () => {
    const { shell } = makeEnv();
    eq(shell.view(), 'login', 'view from the path');
    shell.registerPage({ name: 'p', dispose() {}, stats() { return { a: 1 }; } });
    shell.setUser('qa_writer');
    const d = shell.debug();
    eq([d.page, d.pageStats, d.lastUser, d.hadApp], ['p', { a: 1 }, 'qa_writer', true], 'debug');
    eq(shell.takeNotice(), null, 'no notice');
};

cases.zombie_closures = async () => {
    const { env, win, shell } = makeEnv();
    const life = shell.createLifecycle('old page');
    const g = life.globals; const t = target();
    const later = () => { g.setTimeout(() => {}, 1); life.listen(t, 'x', () => {}); return g.fetch('/secret'); };
    life.dispose();
    let rejected = false; try { await later(); } catch (e) { rejected = true; }
    ok(rejected, 'fetch of a leftover closure rejects');
    eq([env.timers.size, t.added.length, win.pending.length], [0, 0, 0], 'nothing scheduled, registered or sent');
};

(async () => {
    const out = {};
    for (const [name, fn] of Object.entries(cases)) {
        let timer;
        const limit = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('case timed out (a promise never settled)')), 3000); });
        try { await Promise.race([fn(), limit]); out[name] = null; } catch (e) { out[name] = String(e && e.message || e); }
        clearTimeout(timer);
    }
    console.log(JSON.stringify(out));
})();
"""


@pytest.fixture(scope="module")
def outcome():
    result = subprocess.run(
        [NODE, "-e", PROGRAM, str(SHELL_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_every_case_ran(outcome):
    assert set(outcome) == set(CASES)


@pytest.mark.parametrize("case", CASES)
def test_lifecycle(outcome, case):
    assert outcome[case] is None, outcome[case]
