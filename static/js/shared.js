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

    // Folder browser only applies when the share is a directory AND this
    // visitor is currently unlocked (server already decided that when it
    // rendered the page — see shared_download's ctx['unlocked'] in app.py).
    if (body.dataset.isDir === 'true' && body.dataset.unlocked === 'true') {
        initFolderBrowser();
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

// ---------------------------------------------------------------------
// Folder browser — lets a visitor navigate into a shared folder instead
// of only ever getting the "download everything as one zip" button.
// Talks to /shared/<token>/browse (list), /shared/<token>/download-item
// (single file or single subfolder), and /shared/<token>/zip (multi-select).
// ---------------------------------------------------------------------

let _browseToken = null;
let _browseCurrentPath = '';   // subpath relative to the shared folder's own root
let _browseSelected = new Set(); // subpaths currently checked

function initFolderBrowser() {
    _browseToken = document.body.dataset.token;
    const root = document.getElementById('folderBrowser');
    if (!root || !_browseToken) return; // template didn't render the browser container — nothing to do

    // Browser back/forward should move through folders, not reload the page.
    window.addEventListener('popstate', function (e) {
        const path = (e.state && typeof e.state.path === 'string') ? e.state.path : '';
        _loadFolder(path, /*pushState=*/false);
    });

    const downloadSelectedBtn = document.getElementById('browserDownloadSelectedBtn');
    if (downloadSelectedBtn) {
        downloadSelectedBtn.addEventListener('click', _downloadSelected);
    }

    _loadFolder('', /*pushState=*/false);
}

async function _loadFolder(subpath, pushState) {
    const listEl = document.getElementById('browserList');
    const crumbsEl = document.getElementById('browserBreadcrumbs');
    const errEl = document.getElementById('browserError');
    if (!listEl) return;

    _browseCurrentPath = subpath;
    _browseSelected.clear();
    _updateSelectionBar();
    errEl.textContent = '';
    listEl.innerHTML = '<div class="browser-loading">Loading…</div>';

    try {
        const res = await fetch(subpath ? `/shared/${_browseToken}/browse/${encodeURI(subpath)}` : `/shared/${_browseToken}/browse`);
        const data = await res.json();
        if (!res.ok || !data.success) {
            errEl.textContent = data.error || 'Could not load this folder.';
            listEl.innerHTML = '';
            return;
        }

        _renderBreadcrumbs(crumbsEl, subpath);
        _renderList(listEl, data.items || []);

        if (pushState !== false) {
            history.pushState({ path: subpath }, '', '#' + encodeURIComponent(subpath));
        }
    } catch (err) {
        errEl.textContent = 'Something went wrong loading this folder.';
        listEl.innerHTML = '';
    }
}

function _renderBreadcrumbs(crumbsEl, subpath) {
    if (!crumbsEl) return;
    const parts = subpath ? subpath.split('/').filter(Boolean) : [];
    let html = `<a href="#" class="crumb" data-path="">Home</a>`;
    let acc = '';
    parts.forEach(function (part) {
        acc = acc ? `${acc}/${part}` : part;
        html += ` / <a href="#" class="crumb" data-path="${escapeHtmlAttr(acc)}">${escapeHtmlText(part)}</a>`;
    });
    crumbsEl.innerHTML = html;
    crumbsEl.querySelectorAll('.crumb').forEach(function (el) {
        el.addEventListener('click', function (e) {
            e.preventDefault();
            _loadFolder(el.dataset.path, true);
        });
    });
}

function _renderList(listEl, items) {
    if (!items.length) {
        listEl.innerHTML = '<div class="browser-empty">This folder is empty.</div>';
        return;
    }

    // Folders first, then files, alphabetical within each group.
    const sorted = items.slice().sort(function (a, b) {
        if (!!a.is_dir !== !!b.is_dir) return a.is_dir ? -1 : 1;
        return a.name.localeCompare(b.name);
    });

    listEl.innerHTML = sorted.map(function (item) {
        const itemPath = _browseCurrentPath ? `${_browseCurrentPath}/${item.name}` : item.name;
        const sizeText = item.is_dir ? '' : _formatSize(item.size);
        return `
            <div class="browser-row" data-path="${escapeHtmlAttr(itemPath)}" data-is-dir="${item.is_dir ? 'true' : 'false'}">
                <input type="checkbox" class="browser-check" data-path="${escapeHtmlAttr(itemPath)}">
                <span class="browser-icon">${item.is_dir ? '📁' : '📄'}</span>
                <span class="browser-name">${escapeHtmlText(item.name)}</span>
                <span class="browser-size">${sizeText}</span>
                <button type="button" class="browser-download-btn" data-path="${escapeHtmlAttr(itemPath)}" title="Download">⬇</button>
            </div>`;
    }).join('');

    listEl.querySelectorAll('.browser-row').forEach(function (row) {
        row.addEventListener('click', function (e) {
            if (e.target.closest('.browser-check') || e.target.closest('.browser-download-btn')) return;
            if (row.dataset.isDir === 'true') {
                _loadFolder(row.dataset.path, true);
            } else {
                _downloadItem(row.dataset.path);
            }
        });
    });

    listEl.querySelectorAll('.browser-download-btn').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            _downloadItem(btn.dataset.path);
        });
    });

    listEl.querySelectorAll('.browser-check').forEach(function (cb) {
        cb.addEventListener('click', function (e) { e.stopPropagation(); });
        cb.addEventListener('change', function () {
            if (cb.checked) _browseSelected.add(cb.dataset.path);
            else _browseSelected.delete(cb.dataset.path);
            _updateSelectionBar();
        });
    });
}

function _downloadItem(subpath) {
    // Plain navigation, not fetch — lets the browser handle the
    // attachment download/Content-Disposition normally, same as the
    // existing top-level Download button.
    window.location.href = `/shared/${_browseToken}/download-item/${encodeURI(subpath)}`;
}

function _updateSelectionBar() {
    const bar = document.getElementById('browserSelectionBar');
    if (!bar) return;
    const count = _browseSelected.size;
    if (count === 0) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = 'flex';
    const countEl = document.getElementById('browserSelectionCount');
    if (countEl) countEl.textContent = `${count} selected`;
}

async function _downloadSelected() {
    const errEl = document.getElementById('browserError');
    if (_browseSelected.size === 0) return;
    errEl.textContent = '';
    try {
        const res = await fetch(`/shared/${_browseToken}/zip`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paths: Array.from(_browseSelected) })
        });
        if (!res.ok) {
            const data = await res.json().catch(function () { return {}; });
            errEl.textContent = data.error || 'Could not create the zip.';
            return;
        }
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'selected.zip';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
    } catch (err) {
        errEl.textContent = 'Something went wrong creating the zip.';
    }
}

function _formatSize(bytes) {
    if (bytes == null) return '';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let val = bytes, i = 0;
    while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
    return `${i === 0 ? val : val.toFixed(1)} ${units[i]}`;
}

function escapeHtmlText(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeHtmlAttr(str) {
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}