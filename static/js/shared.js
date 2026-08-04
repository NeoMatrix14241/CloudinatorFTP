// Logic for the public /shared/<token> landing page (passkey unlock +
// approval requests). This used to live as inline <script> blocks in
// shared.html, but the site's CSP is script-src 'self' with no
// 'unsafe-inline' and no script hashes — inline scripts are silently
// blocked by the browser (same reason index.js was externalized earlier).
// Keeping this as its own file under static/js/ makes it load like any
// other same-origin script and actually run.

document.addEventListener('DOMContentLoaded', function () {
    const body = document.body;
    const securityMode = body.dataset.securityMode;

    if (securityMode === 'passkey') {
        initPasskeyForm();
    } else if (securityMode === 'approval') {
        initRequestForm();
        if (body.dataset.requestState === 'pending') {
            initStatusPolling();
        }
    }
});

function initPasskeyForm() {
    const form = document.getElementById('passkeyForm');
    if (!form) return; // already unlocked, no form on the page

    const passkeyUrl = document.body.dataset.passkeyUrl;

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const btn = document.getElementById('passkeySubmit');
        const errEl = document.getElementById('gateError');
        const passkey = document.getElementById('passkeyInput').value.trim();
        errEl.textContent = '';
        if (!passkey) return;
        btn.disabled = true;
        try {
            const res = await fetch(passkeyUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ passkey })
            });
            const data = await res.json();
            if (data.success) {
                window.location.reload();
            } else {
                errEl.textContent = data.error || 'Incorrect passkey';
                btn.disabled = false;
            }
        } catch (err) {
            errEl.textContent = 'Something went wrong — try again.';
            btn.disabled = false;
        }
    });
}

function initRequestForm() {
    const form = document.getElementById('requestForm');
    if (!form) return; // e.g. currently in the "pending" spinner state

    const requestUrl = document.body.dataset.requestUrl;

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const btn = document.getElementById('requestSubmit');
        const errEl = document.getElementById('gateError');
        const name = document.getElementById('requesterName').value.trim();
        const note = document.getElementById('requesterNote').value.trim();
        errEl.textContent = '';
        if (!name) return;
        btn.disabled = true;
        try {
            const res = await fetch(requestUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, note })
            });
            const data = await res.json();
            if (data.success) {
                window.location.reload();
            } else {
                errEl.textContent = data.error || 'Something went wrong — try again.';
                btn.disabled = false;
            }
        } catch (err) {
            errEl.textContent = 'Something went wrong — try again.';
            btn.disabled = false;
        }
    });
}

function initStatusPolling() {
    const statusUrl = document.body.dataset.statusUrl;
    // Poll for a decision so the visitor doesn't have to keep refreshing.
    const pollInterval = setInterval(async function () {
        try {
            const res = await fetch(statusUrl);
            const data = await res.json();
            if (data.status && data.status !== 'pending') {
                clearInterval(pollInterval);
                window.location.reload();
            }
        } catch (err) {
            // silent — try again next tick
        }
    }, 4000);
}