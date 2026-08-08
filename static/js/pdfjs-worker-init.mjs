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
    window.PDFViewerApplicationOptions?.set('defaultUrl', '');
}, { once: true });
