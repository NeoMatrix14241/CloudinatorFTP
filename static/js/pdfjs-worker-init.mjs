// Sets up the merged pdf.js viewer before it self-initializes. This module's
// <script> tag must stay ordered BEFORE viewer.mjs's own <script> tag in
// index.html — both are non-async module scripts, which the HTML spec
// guarantees execute in document order, so everything here is guaranteed to
// run first.
//
// Kept as its own external module (rather than an inline <script
// type="module"> in index.html) because this project's CSP uses
// script-src 'self' with no 'unsafe-inline'/hash/nonce — an inline module
// block would be silently dropped by the browser.

import { GlobalWorkerOptions } from "/static/js/pdf.mjs";
GlobalWorkerOptions.workerSrc = "/static/js/pdf.worker.mjs";

// NOTE: the assignment above only survives until viewer.mjs's own self-init
// runs, which re-derives GlobalWorkerOptions.workerSrc from its internal
// AppOptions default and overwrites it — so on every pdf.js update this
// silently reverts to a stock relative path (e.g. "../build/pdf.worker.mjs",
// which resolves to the wrong "/static/build/..." URL and breaks the worker
// with "Failed to fetch dynamically imported module"). The real, durable fix
// is below: push all our path overrides through AppOptions in the same
// webviewerloaded hook we already use for defaultUrl, since that fires
// before viewer.mjs applies its config to GlobalWorkerOptions. Keeping the
// direct assignment above too doesn't hurt, but don't rely on it alone.

// This particular viewer.mjs build is a dev/test build: it has
// AppOptions.defaultUrl hardcoded to pdf.js's own sample PDF
// ("compressed.tracemonkey-pldi-09.pdf") and auto-opens it on every page
// load whenever the page URL has no `?file=` param — which is always, since
// we open PDFs via PDFViewerApplication.open({url}) rather than a URL param.
// Left alone, this silently fetches/renders that sample PDF on every load of
// index.html (not just when the file-viewer modal is open) and overwrites
// the tab title with its name.
//
// We can't just call AppOptions.set('defaultUrl', '') here directly —
// AppOptions is a class private to viewer.mjs's own module scope, and
// importing it from here would force viewer.mjs to fully evaluate
// (including its self-init) before this statement even runs, i.e. too late.
// Instead we use pdf.js's own documented integration hook: it dispatches a
// synchronous "webviewerloaded" CustomEvent on `document`, strictly before
// deciding what to auto-open, specifically so host pages can override
// AppOptions first. window.PDFViewerApplicationOptions is assigned earlier
// in viewer.mjs's module body than that dispatch, so it's already available
// by the time this listener fires.
document.addEventListener('webviewerloaded', () => {
    const opts = window.PDFViewerApplicationOptions;
    // We use pdf.js purely as a stateless viewer (open a URL, show it, done) -
    // we never rely on it remembering zoom/sidebar/etc. between page loads.
    // Setting this stops its Preferences layer from reading (and re-merging)
    // anything out of localStorage on init, which is what was overriding the
    // AppOptions set below and triggering viewer.mjs's own
    // "manually set AppOptions" console warning on every load.
    opts?.set('disablePreferences', true);
    opts?.set('defaultUrl', '');
    // Reassert our /static/js/ layout — required after every pdf.js update,
    // since these five values live inside viewer.mjs's own AppOptions
    // defaults and get reset to stock relative paths on every file swap.
    opts?.set('workerSrc', '/static/js/pdf.worker.mjs');
    opts?.set('cMapUrl', '/static/js/cmaps/');
    opts?.set('iccUrl', '/static/js/iccs/');
    opts?.set('standardFontDataUrl', '/static/js/standard_fonts/');
    opts?.set('wasmUrl', '/static/js/wasm/');
    opts?.set('imageResourcesPath', '/static/js/images/');
}, { once: true });