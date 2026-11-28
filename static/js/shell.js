/*
 * shell.js - the page shell (5.48): no-refresh login, logout and session expiry.
 *
 * Loaded ONCE per document by templates/login.html and templates/index.html. It owns three things:
 *
 *   1. createLifecycle(name): what a page script (index.js, login.js) uses instead of the raw
 *      browser globals, so that EVERYTHING the page started can be stopped again: listeners on
 *      window/document, timers, animation frames, fetch calls in flight, EventSource streams,
 *      upload XHRs, observers, blob URLs and the globals it published. dispose() ends them all.
 *      After dispose() the old page can no longer start anything (its timers, fetches and
 *      listeners are refused), so a closure that survived cannot act for the next user.
 *   2. The view swap: fetch the HTML of the other view ('/' or '/login'), tear the running page
 *      down, put the new <body> content in the SAME document, load the new page script. Nothing
 *      is replaced through an iframe, eval or an inline script, so the Content-Security-Policy
 *      is untouched: scripts come from 'self' with their integrity attribute, markup is
 *      imported as DOM nodes (never innerHTML of a script), and no inline style="" is added.
 *   3. The transitions: loggedIn / toApp, logout, sessionExpired.
 *
 * Fail closed: whenever anything in a transition is not exactly as expected (the fetch fails, the
 * view is the wrong one, a page did not tear down cleanly, a script does not load, a DIFFERENT
 * user logs in than the one whose page this document showed) the shell does an ordinary page
 * navigation instead. A refresh is the worst case, never a data leak.
 *
 * Nothing here uses localStorage, sessionStorage, cookies from JavaScript, eval or new Function.
 */
(function () {
    'use strict';

    if (window.CloudinatorShell) {
        return;
    }

    var VERSION = '5.48.0';
    var LOGIN_URL = '/login';
    var APP_URL = '/';
    var FETCH_TIMEOUT_MS = 15000;
    var SCRIPT_TIMEOUT_MS = 20000;
    var STYLE_TIMEOUT_MS = 8000;

    // The native functions, kept before any page script can shadow or patch them.
    var native = {
        setTimeout: window.setTimeout.bind(window),
        clearTimeout: window.clearTimeout.bind(window),
        setInterval: window.setInterval.bind(window),
        clearInterval: window.clearInterval.bind(window),
        requestAnimationFrame: window.requestAnimationFrame ? window.requestAnimationFrame.bind(window) : null,
        cancelAnimationFrame: window.cancelAnimationFrame ? window.cancelAnimationFrame.bind(window) : null,
        fetch: window.fetch ? window.fetch.bind(window) : null
    };

    function abortError(message) {
        try {
            return new DOMException(message || 'The page was closed', 'AbortError');
        } catch (e) {
            var err = new Error(message || 'The page was closed');
            err.name = 'AbortError';
            return err;
        }
    }

    function captureOf(options) {
        if (typeof options === 'boolean') {
            return options;
        }
        return !!(options && typeof options === 'object' && options.capture);
    }

    // -----------------------------------------------------------------------------------------
    // 1. Lifecycle
    // -----------------------------------------------------------------------------------------
    function createLifecycle(name) {
        var listeners = [];
        var timeouts = new Set();
        var intervals = new Set();
        var frames = new Set();
        var sources = new Set();
        var xhrs = new Set();
        var observers = new Set();
        var controllers = new Set();
        var blobUrls = new Set();
        var patched = [];
        var owned = new Set();
        var disposers = [];
        var disposed = false;
        var report = null;

        function listen(target, type, fn, options) {
            if (disposed || !target || typeof target.addEventListener !== 'function') {
                return;
            }
            target.addEventListener(type, fn, options);
            listeners.push({ target: target, type: type, fn: fn, capture: captureOf(options) });
        }

        function unlisten(target, type, fn, options) {
            if (!target || typeof target.removeEventListener !== 'function') {
                return;
            }
            target.removeEventListener(type, fn, options);
            var capture = captureOf(options);
            for (var i = listeners.length - 1; i >= 0; i--) {
                var l = listeners[i];
                if (l.target === target && l.type === type && l.fn === fn && l.capture === capture) {
                    listeners.splice(i, 1);
                    break;
                }
            }
        }

        function onReady(fn) {
            if (document.readyState === 'loading') {
                listen(document, 'DOMContentLoaded', fn, { once: true });
            } else {
                setTimeoutT(fn, 0);
            }
        }

        function setTimeoutT(fn, ms) {
            if (disposed) {
                return 0;
            }
            var args = Array.prototype.slice.call(arguments, 2);
            var id = native.setTimeout(function () {
                timeouts.delete(id);
                if (disposed || typeof fn !== 'function') {
                    return undefined;
                }
                return fn.apply(this, args);
            }, ms);
            timeouts.add(id);
            return id;
        }

        function clearTimeoutT(id) {
            timeouts.delete(id);
            native.clearTimeout(id);
        }

        function setIntervalT(fn, ms) {
            if (disposed) {
                return 0;
            }
            var args = Array.prototype.slice.call(arguments, 2);
            var id = native.setInterval(function () {
                if (disposed || typeof fn !== 'function') {
                    return undefined;
                }
                return fn.apply(this, args);
            }, ms);
            intervals.add(id);
            return id;
        }

        function clearIntervalT(id) {
            intervals.delete(id);
            native.clearInterval(id);
        }

        function requestFrameT(cb) {
            if (disposed || !native.requestAnimationFrame) {
                return 0;
            }
            var id = native.requestAnimationFrame(function (t) {
                frames.delete(id);
                if (!disposed) {
                    cb(t);
                }
            });
            frames.add(id);
            return id;
        }

        function cancelFrameT(id) {
            frames.delete(id);
            if (native.cancelAnimationFrame) {
                native.cancelAnimationFrame(id);
            }
        }

        function fetchT(input, init) {
            if (disposed) {
                return Promise.reject(abortError());
            }
            var ctl = new AbortController();
            controllers.add(ctl);
            var opts = init ? Object.assign({}, init) : {};
            var outer = opts.signal || (input && typeof input === 'object' && input.signal) || null;
            if (outer) {
                if (outer.aborted) {
                    ctl.abort();
                } else {
                    outer.addEventListener('abort', function () { ctl.abort(); }, { once: true });
                }
            }
            opts.signal = ctl.signal;
            var p;
            try {
                // window.fetch at CALL time: index.js puts its CSRF wrapper there.
                p = window.fetch(input, opts);
            } catch (e) {
                controllers.delete(ctl);
                throw e;
            }
            return p.finally(function () { controllers.delete(ctl); });
        }

        function trackedEventSource() {
            var Native = window.EventSource;
            if (typeof Native !== 'function') {
                return undefined;
            }
            return class TrackedEventSource extends Native {
                constructor(url, config) {
                    if (disposed) {
                        throw abortError();
                    }
                    super(url, config);
                    sources.add(this);
                }
                close() {
                    sources.delete(this);
                    super.close();
                }
            };
        }

        function trackedXhr() {
            var Native = window.XMLHttpRequest;
            if (typeof Native !== 'function') {
                return undefined;
            }
            return class TrackedXMLHttpRequest extends Native {
                constructor() {
                    if (disposed) {
                        throw abortError();
                    }
                    super();
                    xhrs.add(this);
                    this.addEventListener('loadend', function () { xhrs.delete(this); });
                }
            };
        }

        function trackedObserver(Native) {
            if (typeof Native !== 'function') {
                return undefined;
            }
            return class TrackedObserver extends Native {
                constructor(callback, options) {
                    super(callback, options);
                    observers.add(this);
                }
                disconnect() {
                    observers.delete(this);
                    super.disconnect();
                }
            };
        }

        function createObjectURL(obj) {
            var url = URL.createObjectURL(obj);
            blobUrls.add(url);
            return url;
        }

        function patch(obj, key, value) {
            patched.push({
                obj: obj,
                key: key,
                had: Object.prototype.hasOwnProperty.call(obj, key),
                value: obj[key]
            });
            obj[key] = value;
        }

        function exportGlobals(map) {
            Object.keys(map).forEach(function (key) {
                patch(window, key, map[key]);
            });
        }

        function ownGlobals(names) {
            names.forEach(function (n) { owned.add(n); });
        }

        function onDispose(fn) {
            disposers.push(fn);
        }

        function stats() {
            return {
                listeners: listeners.length,
                timeouts: timeouts.size,
                intervals: intervals.size,
                frames: frames.size,
                eventSources: sources.size,
                xhrs: xhrs.size,
                observers: observers.size,
                fetches: controllers.size,
                blobUrls: blobUrls.size,
                patched: patched.length,
                ownedGlobals: owned.size
            };
        }

        function attempt(errors, label, fn) {
            try {
                fn();
            } catch (e) {
                errors.push(label + ': ' + (e && e.message ? e.message : String(e)));
            }
        }

        function dispose() {
            if (report) {
                return report;
            }
            disposed = true;
            var errors = [];
            var before = stats();

            listeners.splice(0).forEach(function (l) {
                attempt(errors, 'listener', function () { l.target.removeEventListener(l.type, l.fn, l.capture); });
            });
            Array.from(timeouts).forEach(function (id) { native.clearTimeout(id); });
            timeouts.clear();
            Array.from(intervals).forEach(function (id) { native.clearInterval(id); });
            intervals.clear();
            Array.from(frames).forEach(function (id) {
                if (native.cancelAnimationFrame) {
                    native.cancelAnimationFrame(id);
                }
            });
            frames.clear();
            Array.from(sources).forEach(function (es) { attempt(errors, 'EventSource', function () { es.close(); }); });
            sources.clear();
            Array.from(xhrs).forEach(function (x) { attempt(errors, 'XHR', function () { x.abort(); }); });
            xhrs.clear();
            Array.from(observers).forEach(function (o) { attempt(errors, 'observer', function () { o.disconnect(); }); });
            observers.clear();
            Array.from(controllers).forEach(function (c) { attempt(errors, 'fetch', function () { c.abort(); }); });
            controllers.clear();
            Array.from(blobUrls).forEach(function (u) { attempt(errors, 'blob', function () { URL.revokeObjectURL(u); }); });
            blobUrls.clear();

            disposers.splice(0).reverse().forEach(function (fn) {
                attempt(errors, 'disposer', fn);
            });

            for (var i = patched.length - 1; i >= 0; i--) {
                var p = patched[i];
                attempt(errors, 'restore ' + p.key, function () {
                    if (p.had) {
                        p.obj[p.key] = p.value;
                    } else {
                        delete p.obj[p.key];
                    }
                });
            }
            patched.length = 0;
            owned.forEach(function (n) {
                attempt(errors, 'global ' + n, function () { delete window[n]; });
            });
            owned.clear();

            var after = stats();
            var leftover = Object.keys(after).filter(function (k) { return after[k] !== 0; });
            report = {
                name: name,
                clean: errors.length === 0 && leftover.length === 0,
                errors: errors,
                leftover: leftover,
                before: before
            };
            return report;
        }

        return {
            name: name,
            listen: listen,
            unlisten: unlisten,
            onReady: onReady,
            createObjectURL: createObjectURL,
            patch: patch,
            exportGlobals: exportGlobals,
            ownGlobals: ownGlobals,
            onDispose: onDispose,
            stats: stats,
            dispose: dispose,
            isDisposed: function () { return disposed; },
            globals: {
                setTimeout: setTimeoutT,
                clearTimeout: clearTimeoutT,
                setInterval: setIntervalT,
                clearInterval: clearIntervalT,
                requestAnimationFrame: requestFrameT,
                cancelAnimationFrame: cancelFrameT,
                fetch: fetchT,
                EventSource: trackedEventSource(),
                XMLHttpRequest: trackedXhr(),
                MutationObserver: trackedObserver(window.MutationObserver),
                ResizeObserver: trackedObserver(window.ResizeObserver),
                IntersectionObserver: trackedObserver(window.IntersectionObserver)
            }
        };
    }

    // -----------------------------------------------------------------------------------------
    // 2. State and small helpers
    // -----------------------------------------------------------------------------------------
    var state = {
        view: null,
        page: null,
        lastUser: null,
        hadApp: false,
        notice: null,
        held: new Map(),
        loaded: new Set(),
        lock: null
    };

    function keyOf(url) {
        try {
            return new URL(url, window.location.href).pathname;
        } catch (e) {
            return String(url);
        }
    }

    function initialView() {
        var attr = document.body && document.body.getAttribute('data-shell-view');
        if (attr) {
            return attr;
        }
        return window.location.pathname === LOGIN_URL ? 'login' : 'app';
    }

    function seedLoadedScripts() {
        Array.prototype.forEach.call(document.querySelectorAll('script[src]'), function (s) {
            if (s.getAttribute('data-shell') !== 'page') {
                state.loaded.add(keyOf(s.getAttribute('src')));
            }
        });
    }

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : null;
    }

    function setCsrfToken(token) {
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (!token) {
            return;
        }
        if (!meta) {
            meta = document.createElement('meta');
            meta.setAttribute('name', 'csrf-token');
            document.head.appendChild(meta);
        }
        meta.setAttribute('content', token);
    }

    // The fail-closed path: an ordinary page load. It always says WHY in the console ("[shell]"):
    // when a login or logout still reloads the page, that line is what to look at.
    function hardNavigate(url, why) {
        try {
            console.warn('[shell] falling back to a page load of ' + url + ': ' + (why && why.message ? why.message : why));
        } catch (e) {
            // no console
        }
        window.location.replace(url);
        return Promise.resolve(false);
    }

    function nextTask() {
        return new Promise(function (resolve) { native.setTimeout(resolve, 0); });
    }

    // data-shell-ready on <body> says "the page script of this view is mounted": until then the
    // view may be on screen but does not react yet (tests and scripts wait for it).
    function markReady() {
        if (document.body) {
            document.body.setAttribute('data-shell-ready', document.body.getAttribute('data-shell-view') || '');
        }
    }

    function exclusive(fn) {
        if (state.lock) {
            return state.lock;
        }
        state.lock = (async function () {
            try {
                return await fn();
            } finally {
                state.lock = null;
            }
        })();
        return state.lock;
    }

    function withTimeout(promise, ms, label) {
        return new Promise(function (resolve, reject) {
            var timer = native.setTimeout(function () { reject(new Error(label + ' timed out')); }, ms);
            promise.then(function (v) { native.clearTimeout(timer); resolve(v); },
                function (e) { native.clearTimeout(timer); reject(e); });
        });
    }

    async function fetchView(url, expected) {
        var ctl = new AbortController();
        var timer = native.setTimeout(function () { ctl.abort(); }, FETCH_TIMEOUT_MS);
        try {
            var response = await native.fetch(url, {
                method: 'GET',
                credentials: 'same-origin',
                cache: 'no-store',
                redirect: 'follow',
                signal: ctl.signal,
                // This header is how the server knows it is the shell asking (no
                // Clear-Site-Data on that response, 401 JSON instead of a redirect).
                headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'text/html' }
            });
            if (!response.ok) {
                throw new Error('view ' + url + ' answered ' + response.status);
            }
            var type = response.headers.get('content-type') || '';
            if (type.indexOf('text/html') === -1) {
                throw new Error('view ' + url + ' is not HTML');
            }
            var text = await response.text();
            var doc = new DOMParser().parseFromString(text, 'text/html');
            var view = doc.body && doc.body.getAttribute('data-shell-view');
            if (view !== expected) {
                throw new Error('expected the ' + expected + ' view, got ' + view);
            }
            return doc;
        } finally {
            native.clearTimeout(timer);
        }
    }

    function usernameOf(doc) {
        var cfg = doc.getElementById('flask-config');
        return cfg ? cfg.getAttribute('data-username') : null;
    }

    function syncAttributes(live, parsed) {
        Array.prototype.slice.call(live.attributes).forEach(function (a) {
            if (!parsed.hasAttribute(a.name)) {
                live.removeAttribute(a.name);
            }
        });
        Array.prototype.slice.call(parsed.attributes).forEach(function (a) {
            if (live.getAttribute(a.name) !== a.value) {
                live.setAttribute(a.name, a.value);
            }
        });
    }

    function copyAttributes(from, to) {
        Array.prototype.forEach.call(from.attributes, function (a) {
            to.setAttribute(a.name, a.value);
        });
    }

    function isExecutable(script) {
        var type = (script.getAttribute('type') || '').toLowerCase();
        return type === '' || type === 'module' || type === 'text/javascript' || type === 'application/javascript';
    }

    // Stylesheets: new ones are fetched first (media=print keeps them inactive), then switched on
    // in the same task in which the old view's stylesheets are removed, so there is no flash of
    // the wrong styling.
    async function prepareStyles(doc) {
        var wanted = new Set();
        var live = new Map();
        Array.prototype.forEach.call(document.head.querySelectorAll('link[rel~="stylesheet"]'), function (l) {
            live.set(keyOf(l.getAttribute('href')), l);
        });
        var added = [];
        var waits = [];
        Array.prototype.forEach.call(doc.head.querySelectorAll('link[rel~="stylesheet"]'), function (l) {
            var key = keyOf(l.getAttribute('href'));
            wanted.add(key);
            if (live.has(key)) {
                return;
            }
            var el = document.createElement('link');
            copyAttributes(l, el);
            el.setAttribute('media', 'print');
            waits.push(withTimeout(new Promise(function (resolve) {
                el.addEventListener('load', resolve, { once: true });
                el.addEventListener('error', resolve, { once: true });
            }), STYLE_TIMEOUT_MS, 'stylesheet ' + key).catch(function () { /* show it anyway */ }));
            document.head.appendChild(el);
            added.push(el);
        });
        await Promise.all(waits);
        return { wanted: wanted, live: live, added: added };
    }

    function activateStyles(plan) {
        plan.live.forEach(function (el, key) {
            if (!plan.wanted.has(key)) {
                el.remove();
            }
        });
        plan.added.forEach(function (el) {
            el.removeAttribute('media');
        });
    }

    function syncHead(doc) {
        document.title = doc.title;
        var csrf = doc.querySelector('meta[name="csrf-token"]');
        if (csrf) {
            setCsrfToken(csrf.getAttribute('content'));
        } else {
            var old = document.querySelector('meta[name="csrf-token"]');
            if (old) {
                old.remove();
            }
        }
        // Other head <link>s (the pdf.js l10n resource, the icon) are only ever ADDED.
        Array.prototype.forEach.call(doc.head.querySelectorAll('link:not([rel~="stylesheet"])'), function (l) {
            var sig = (l.getAttribute('rel') || '') + '|' + keyOf(l.getAttribute('href'));
            var exists = Array.prototype.some.call(document.head.querySelectorAll('link:not([rel~="stylesheet"])'), function (x) {
                return (x.getAttribute('rel') || '') + '|' + keyOf(x.getAttribute('href')) === sig;
            });
            if (!exists) {
                var el = document.createElement('link');
                copyAttributes(l, el);
                document.head.appendChild(el);
            }
        });
    }

    // Nodes marked data-shell-persist belong to a once-per-document script (the background
    // music element, the pdf.js viewer root). They are MOVED into the new view, never rebuilt:
    // a media element that is removed and put back in the same task keeps playing.
    function buildBody(doc) {
        var persistent = new Map(state.held);
        Array.prototype.forEach.call(document.body.querySelectorAll('[data-shell-persist]'), function (n) {
            persistent.set(n.id, n);
        });
        var fragment = document.createDocumentFragment();
        Array.prototype.slice.call(doc.body.childNodes).forEach(function (child) {
            if (child.nodeType === 1 && child.tagName === 'SCRIPT' && isExecutable(child)) {
                return;
            }
            fragment.appendChild(document.importNode(child, true));
        });
        // Executable scripts nested deeper never occur in our templates; drop them if they do.
        Array.prototype.forEach.call(fragment.querySelectorAll('script'), function (s) {
            if (isExecutable(s)) {
                s.remove();
            }
        });
        Array.prototype.forEach.call(fragment.querySelectorAll('[data-shell-persist]'), function (fresh) {
            var keep = persistent.get(fresh.id);
            if (keep) {
                fresh.replaceWith(keep);
                persistent.delete(fresh.id);
                state.held.delete(fresh.id);
            }
        });
        persistent.forEach(function (node, id) {
            // Not part of the new view: keep it, but cut it loose from the old subtree so that
            // its parents (and whatever the old page put into them) can be released.
            if (node.parentNode) {
                node.parentNode.removeChild(node);
            }
            state.held.set(id, node);
        });
        return fragment;
    }

    function loadScript(source) {
        var page = source.getAttribute('data-shell') === 'page';
        var key = keyOf(source.getAttribute('src'));
        if (!page && state.loaded.has(key)) {
            return Promise.resolve();
        }
        return new Promise(function (resolve, reject) {
            var el = document.createElement('script');
            copyAttributes(source, el);
            el.async = false;
            var timer = native.setTimeout(function () { reject(new Error('script ' + key + ' timed out')); }, SCRIPT_TIMEOUT_MS);
            el.addEventListener('load', function () { native.clearTimeout(timer); resolve(); }, { once: true });
            el.addEventListener('error', function () { native.clearTimeout(timer); reject(new Error('script ' + key + ' failed')); }, { once: true });
            if (!page) {
                state.loaded.add(key);
            }
            (page ? document.body : document.head).appendChild(el);
        });
    }

    async function runScripts(doc) {
        var list = Array.prototype.slice.call(doc.querySelectorAll('script[src]'));
        for (var i = 0; i < list.length; i++) {
            await loadScript(list[i]);
        }
    }

    // Ends the running page. Returns false when it could not be proven clean.
    async function disposeCurrentPage() {
        var page = state.page;
        state.page = null;
        if (!page) {
            // An app page that never registered cannot be proven torn down.
            return state.view !== 'app';
        }
        try {
            var result = await page.dispose();
            return !result || result.clean !== false;
        } catch (e) {
            return false;
        }
    }

    async function swapTo(view, doc, url) {
        // The parser has not reached the later <script> tags when this file first runs, so what
        // the document already loaded is recorded now, at the first transition.
        seedLoadedScripts();
        var styles = await prepareStyles(doc);
        var ok = await disposeCurrentPage();
        if (!ok) {
            throw new Error('the page did not tear down cleanly');
        }
        // From here on there is no await until the new body is in place.
        syncHead(doc);
        syncAttributes(document.documentElement, doc.documentElement);
        syncAttributes(document.body, doc.body);
        if (view === 'app') {
            // The file manager is on screen before its script has run. Until it is mounted it
            // must not react to the user: a click on Logout would be an ordinary link click, that
            // is a page load. (Not for the login view: its form posts the classic way, and the
            // script focuses the username field.)
            document.body.setAttribute('inert', '');
        }
        var fragment = buildBody(doc);
        document.body.replaceChildren(fragment);
        activateStyles(styles);
        state.view = view;
        window.scrollTo(0, 0);
        await runScripts(doc);
        // What the page script queued for "the document is ready" runs in the next tasks.
        await nextTask();
        await nextTask();
        // The address changes only now: whoever waits for the new address (a test, an
        // extension) finds a view that is mounted and answers.
        window.history.replaceState(null, '', url);
        document.body.removeAttribute('inert');
        markReady();
    }

    // -----------------------------------------------------------------------------------------
    // 3. Transitions
    // -----------------------------------------------------------------------------------------
    function toApp() {
        return exclusive(async function () {
            try {
                var doc = await fetchView(APP_URL, 'app');
                var user = usernameOf(doc);
                if (state.hadApp && (!user || user !== state.lastUser)) {
                    // A different account than the one this document showed: only a new
                    // document gives the guarantee that nothing of the old one is left.
                    return hardNavigate(APP_URL, 'a different user than this document showed');
                }
                await swapTo('app', doc, APP_URL);
                state.hadApp = true;
                state.lastUser = user;
                return true;
            } catch (e) {
                return hardNavigate(APP_URL, e);
            }
        });
    }

    // "Reload the page" without leaving it: the same view is fetched again and mounted again,
    // for the same user only (the session did not change, only the page's own state is renewed).
    function reload(url) {
        return exclusive(async function () {
            var target = url || (window.location.pathname + window.location.search);
            try {
                var doc = await fetchView(target, 'app');
                var user = usernameOf(doc);
                if (!user || user !== state.lastUser) {
                    return hardNavigate(target, 'a different user than this document showed');
                }
                await swapTo('app', doc, target);
                return true;
            } catch (e) {
                return hardNavigate(target, e);
            }
        });
    }

    function toLogin(options) {
        var notice = options && options.notice ? options.notice : null;
        return exclusive(async function () {
            try {
                var doc = await fetchView(LOGIN_URL, 'login');
                state.notice = notice;
                await swapTo('login', doc, LOGIN_URL);
                return true;
            } catch (e) {
                return hardNavigate(LOGIN_URL, e);
            }
        });
    }

    function postLogout() {
        var headers = {
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        };
        var token = csrfToken();
        if (token) {
            headers['X-CSRFToken'] = token;
        }
        return window.fetch('/logout', {
            method: 'POST',
            credentials: 'same-origin',
            cache: 'no-store',
            redirect: 'manual',
            headers: headers
        });
    }

    var channel = null;
    try {
        channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('cloudinator-auth') : null;
    } catch (e) {
        channel = null;
    }

    function logout() {
        return exclusive(async function () {
            var ok = false;
            var why = 'no answer';
            try {
                var response = await postLogout();
                ok = response.ok;
                why = 'POST /logout answered ' + response.status;
            } catch (e) {
                ok = false;
                why = e;
            }
            if (!ok) {
                // The classic logout: GET /logout, full headers, full teardown.
                return hardNavigate('/logout', why);
            }
            if (channel) {
                try { channel.postMessage('logout'); } catch (e) { /* not important */ }
            }
            try {
                var doc = await fetchView(LOGIN_URL, 'login');
                state.notice = null;
                await swapTo('login', doc, LOGIN_URL);
                return true;
            } catch (e) {
                return hardNavigate(LOGIN_URL, e);
            }
        });
    }

    function sessionExpired(reason) {
        if (state.view === 'login') {
            return Promise.resolve(true);
        }
        var text = reason === 'signed_out_elsewhere'
            ? 'You were signed out in another tab. Please sign in again.'
            : 'Your session has expired. Please sign in again.';
        return toLogin({ notice: text });
    }

    if (channel) {
        channel.onmessage = function (event) {
            if (event && event.data === 'logout' && state.view === 'app') {
                sessionExpired('signed_out_elsewhere');
            }
        };
    }

    window.addEventListener('popstate', function () {
        // A history entry of the file manager is no reason to show anything while logged out.
        if (state.view === 'login' && window.location.pathname !== LOGIN_URL) {
            window.history.replaceState(null, '', LOGIN_URL);
        }
    });

    window.addEventListener('pageshow', function (event) {
        if (!event.persisted || state.view !== 'app') {
            return;
        }
        // Restored from the back/forward cache: ask the server whether the session is still alive.
        native.fetch('/check_session', {
            cache: 'no-store',
            credentials: 'same-origin',
            redirect: 'manual',
            headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (response) {
            if (response.status === 401 || response.type === 'opaqueredirect') {
                sessionExpired();
            }
        }).catch(function () { /* offline: nothing to decide */ });
    });

    // shell.js sits in <head>, where <body> does not exist yet: the path decides until the body's
    // data-shell-view attribute can be read.
    state.view = initialView();
    state.hadApp = state.view === 'app';
    document.addEventListener('DOMContentLoaded', function () {
        state.view = initialView();
        state.hadApp = state.hadApp || state.view === 'app';
    }, { once: true });
    window.addEventListener('load', markReady, { once: true });

    window.CloudinatorShell = {
        version: VERSION,
        createLifecycle: createLifecycle,
        registerPage: function (page) { state.page = page; },
        setUser: function (name) { state.lastUser = name || null; state.hadApp = true; },
        view: function () { return state.view; },
        toApp: toApp,
        toLogin: toLogin,
        reload: reload,
        logout: logout,
        sessionExpired: sessionExpired,
        takeNotice: function () { var n = state.notice; state.notice = null; return n; },
        csrfToken: csrfToken,
        setCsrfToken: setCsrfToken,
        // For tests and for a look in the console: what the shell currently holds.
        debug: function () {
            return {
                view: state.view,
                page: state.page ? state.page.name : null,
                pageStats: state.page && typeof state.page.stats === 'function' ? state.page.stats() : null,
                lastUser: state.lastUser,
                hadApp: state.hadApp,
                held: Array.from(state.held.keys()),
                loaded: Array.from(state.loaded)
            };
        }
    };
})();
