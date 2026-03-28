// Read Flask configuration from HTML data attributes (avoids VS Code parsing issues)
const configElement = document.getElementById('flask-config');
const CHUNK_SIZE = parseInt(configElement.dataset.chunkSize) || 10485760; // 10MB fallback
const UPLOAD_URL = configElement.dataset.uploadUrl || "/upload";
const CURRENT_PATH = configElement.dataset.currentPath || "";
const USER_ROLE = configElement.dataset.userRole || "readonly";

// Browser history management for authentication
document.addEventListener('DOMContentLoaded', function () {
    // Immediate authentication check on page load
    checkAuthenticationOnPageLoad();

    // Clean up browser history to prevent login page from being accessible via back button
    cleanupAuthenticationHistory();
    // Transform any server-rendered rows to use detailed file type & icon mapping
    try { transformInitialRows(); } catch (e) { console.warn('transformInitialRows not available yet', e); }

    // Initialize VT engine from server-rendered JSON (replaces the inline HTML script)
    _initVTFromPageData();

    const createFolderForm = document.getElementById('createFolderForm');
    if (createFolderForm) {
        createFolderForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const folderName = document.getElementById('folderNameInput').value;

            // Use the global currentPath variable
            console.log('Current global path:', currentPath);

            await createFolder(folderName, currentPath);
        });
    }

    // Stop-folder delegation — survives any innerHTML rebuild on folder rows
    const _fqEl = document.getElementById('fileQueue');
    if (_fqEl) {
        _fqEl.addEventListener('click', function (e) {
            const b = e.target.closest('.fg-stop-btn');
            if (b) { e.stopPropagation(); e.preventDefault(); _stopFolderGroup(b.dataset.gid); }
        });
    }

    // Mobile tap-tooltip — shows label on touchstart, hides after 1.2s or on touchend
    initTapTooltips();
});

function initTapTooltips() {
    // Single tooltip element reused for both hover (desktop) and tap (mobile)
    const tip = document.createElement('div');
    tip.id = 'btn-action-tooltip';
    document.body.appendChild(tip);

    let hideTimer = null;

    function showTip(btn) {
        const label = btn.dataset.label;
        if (!label) return;
        clearTimeout(hideTimer);
        tip.textContent = label;
        tip.classList.add('visible');

        const rect = btn.getBoundingClientRect();
        // Measure after setting text so width is accurate
        const tw = tip.offsetWidth;
        const th = tip.offsetHeight;
        let left = rect.left + rect.width / 2 - tw / 2;
        let top = rect.top - th - 7;
        // Clamp inside viewport
        left = Math.max(6, Math.min(left, window.innerWidth - tw - 6));
        if (top < 6) top = rect.bottom + 7; // flip below if no room above
        tip.style.left = left + 'px';
        tip.style.top = top + 'px';
    }

    function hideTip(delay) {
        clearTimeout(hideTimer);
        if (delay) {
            hideTimer = setTimeout(() => tip.classList.remove('visible'), delay);
        } else {
            tip.classList.remove('visible');
        }
    }

    const SEL = '.actions-cell .btn-sm[data-label], #filesTable .actions .btn-sm[data-label]';

    // ── Desktop: mouseenter / mouseleave ─────────────────────────────────────
    document.addEventListener('mouseenter', e => {
        if (!e.target || e.target.nodeType !== 1) return;
        const btn = e.target.closest(SEL);
        if (btn) showTip(btn);
    }, true);

    document.addEventListener('mouseleave', e => {
        if (!e.target || e.target.nodeType !== 1) return;
        if (e.target.closest(SEL)) hideTip(80);
    }, true);

    // ── Mobile: touchstart shows label, hides after 1.3s or on move ──────────
    document.addEventListener('touchstart', e => {
        if (!e.target || e.target.nodeType !== 1) return;
        const btn = e.target.closest(SEL);
        if (btn) {
            showTip(btn);
            hideTip(1300);
        } else {
            hideTip(0);
        }
    }, { passive: true });

    document.addEventListener('touchmove', () => hideTip(0), { passive: true });
}

let _smartColumnizerRO = null; // ResizeObserver reference

function lockTableColumnWidths() {
    // Delegate to smart columnizer — keeps backward-compat for callers
    smartTableColumnizer();
}

/**
 * Smart real-time column width adjuster.
 * Uses setProperty(...,'important') so inline styles beat any CSS !important rule.
 * Mobile (<600px):  cb | name | size | actions          (type + modified hidden)
 * Tablet (600-899): cb | name | size | type | actions   (modified hidden)
 * Desktop (≥900px): all 6 columns
 */
function smartTableColumnizer() {
    const wrapper = document.getElementById('tableScrollWrapper');
    const table = document.getElementById('filesTable');
    if (!wrapper || !table) return;

    if (_smartColumnizerRO) { _smartColumnizerRO.disconnect(); _smartColumnizerRO = null; }

    function _set(el, prop, val) {
        el.style.setProperty(prop, val, 'important');
    }

    function applyWidths() {
        const W = wrapper.clientWidth || wrapper.offsetWidth;
        if (!W) return;

        const isMobile = W < 600;
        const isTablet = W >= 600 && W < 900;

        // Mobile (<600px):  cb | name | size | actions               (type + modified hidden)
        // Tablet (600-899): cb | name | size | type | actions        (modified hidden, slimmer cols)
        // Desktop (≥900px): all 6 columns
        const cbW = 36;
        const sizeW = isTablet ? 110 : 200;
        const typeW = isTablet ? 110 : 125;
        const modW = 140;
        const actW = isTablet ? 155 : 172;

        const showMod = !isTablet && !isMobile;
        const fixedTotal = cbW + sizeW + typeW + (showMod ? modW : 0) + actW;

        const nameFloor = isMobile ? 250 : isTablet ? 100 : 160;
        const nameW = Math.max(nameFloor, W - fixedTotal - 4);
        const totalW = fixedTotal + nameW;
        _set(table, 'table-layout', 'fixed');
        _set(table, 'width', '100%');
        _set(table, 'min-width', totalW + 'px');

        const colDefs = [cbW, nameW, sizeW, typeW, showMod ? modW : 0, actW];

        const padTop = isMobile ? '8px' : '11px';

        function _fixCheckbox(el) {
            if (!el) return;
            _set(el, 'width', '16px');
            _set(el, 'height', '16px');
            _set(el, 'min-width', '16px');
            _set(el, 'min-height', '16px');
            _set(el, 'max-width', '16px');
            _set(el, 'max-height', '16px');
            _set(el, 'display', 'block');
            _set(el, 'margin', '0 auto');
        }

        // ── Apply to <thead th> ───────────────────────────────────────────────────
        table.querySelectorAll('thead th').forEach((th, i) => {
            const w = colDefs[i];
            if (w === 0) { _set(th, 'display', 'none'); return; }
            _set(th, 'display', '');
            _set(th, 'width', w + 'px');
            _set(th, 'max-width', w + 'px');
            _set(th, 'white-space', 'nowrap');
            if (i === 0) {
                _set(th, 'overflow', 'visible');
                _set(th, 'padding', '0');
                _set(th, 'text-align', 'center');
                _set(th, 'vertical-align', 'middle');
                _fixCheckbox(th.querySelector('input[type="checkbox"]'));
            } else {
                _set(th, 'overflow', 'hidden');
                _set(th, 'padding', isMobile ? '14px 6px' : '18px 13px');
            }
        });

        // ── Apply to <tbody td> ───────────────────────────────────────────────────
        _styleRows(table.querySelectorAll('tbody tr'), colDefs, isMobile);
    }

    function _styleRows(rows, colDefs, isMobile) {
        const pad = isMobile ? '8px 8px' : '11px 13px';
        const padTop = isMobile ? '8px' : '11px';
        rows.forEach(row => {
            if (row.classList.contains('empty-folder-row')) return;
            if (row.cells.length && row.cells[0].colSpan > 1) return;

            Array.from(row.cells).forEach((td, i) => {
                const w = colDefs[i];
                if (w === 0) { _set(td, 'display', 'none'); return; }

                _set(td, 'display', '');
                _set(td, 'width', w + 'px');
                _set(td, 'max-width', w + 'px');

                if (i === 0) {
                    _set(td, 'overflow', 'visible');
                    _set(td, 'padding', padTop + ' 0 0 0');
                    _set(td, 'text-align', 'center');
                    _set(td, 'vertical-align', 'top');
                    _set(td, 'line-height', 'normal');
                    const cb = td.querySelector('input[type="checkbox"]');
                    if (cb) {
                        _set(cb, 'width', '16px');
                        _set(cb, 'height', '16px');
                        _set(cb, 'min-width', '16px');
                        _set(cb, 'min-height', '16px');
                        _set(cb, 'max-width', '16px');
                        _set(cb, 'max-height', '16px');
                        _set(cb, 'display', 'block');
                        _set(cb, 'margin', '0 auto');
                    }
                    return;
                }

                _set(td, 'overflow', 'hidden');
                _set(td, 'padding', pad);
                _set(td, 'vertical-align', 'top');
                _set(td, 'line-height', '1.3');

                if (i === 1) {
                    // Name: word-wrap on all breakpoints
                    _set(td, 'white-space', 'normal');
                    _set(td, 'text-overflow', 'unset');
                    _set(td, 'vertical-align', 'top');
                    const fn = td.querySelector('.file-name');
                    if (fn) {
                        _set(fn, 'display', 'flex');
                        _set(fn, 'align-items', 'flex-start');
                        _set(fn, 'gap', '6px');
                        _set(fn, 'overflow', 'hidden');
                        _set(fn, 'white-space', 'normal');
                        _set(fn, 'max-width', '100%');
                        fn.querySelectorAll('a, span').forEach(el => {
                            _set(el, 'white-space', 'normal');
                            _set(el, 'word-break', 'break-word');
                            _set(el, 'overflow-wrap', 'anywhere');
                            _set(el, 'overflow', 'hidden');
                            _set(el, 'text-overflow', 'unset');
                            _set(el, 'display', 'block');
                            _set(el, 'max-width', '100%');
                        });
                    }
                } else if (i === 2) {
                    // Size: allow wrapping so "5000 files, 5000 folders\n204 MB" shows fully
                    _set(td, 'white-space', 'normal');
                    _set(td, 'word-break', 'break-word');
                    _set(td, 'text-overflow', 'unset');
                } else {
                    // All other cells: single line, ellipsis
                    _set(td, 'white-space', 'nowrap');
                    _set(td, 'text-overflow', 'ellipsis');
                }
            });
        });
    }

    // Expose helpers so applyColumnWidths can style new VT rows consistently
    smartTableColumnizer._styleRows = _styleRows;
    smartTableColumnizer._getColDefs = function () {
        const W = wrapper.clientWidth || wrapper.offsetWidth || 800;
        const isMobile = W < 600;
        const isTablet = W >= 600 && W < 900;
        const cbW = 36, sizeW = isTablet ? 110 : 200, typeW = isTablet ? 110 : 125, modW = 140, actW = isTablet ? 155 : 172;
        const showMod = !isTablet && !isMobile;
        const fixedTotal = cbW + sizeW + typeW + (showMod ? modW : 0) + actW;
        const nameFloor = isMobile ? 250 : isTablet ? 100 : 160;
        const nameW = Math.max(nameFloor, W - fixedTotal - 4);
        return { colDefs: [cbW, nameW, sizeW, typeW, showMod ? modW : 0, actW], isMobile };
    };

    applyWidths();

    _smartColumnizerRO = new ResizeObserver(() => applyWidths());
    _smartColumnizerRO.observe(wrapper);
    window.addEventListener('resize', applyWidths, { passive: true });
}

function applyColumnWidths(row) {
    if (!row) return;
    if (smartTableColumnizer._styleRows && smartTableColumnizer._getColDefs) {
        const { colDefs, isMobile } = smartTableColumnizer._getColDefs();
        smartTableColumnizer._styleRows([row], colDefs, isMobile);
    }
}

// Function to protect all modal inputs from event delegation
function protectModalInputs() {
    const modals = document.querySelectorAll('.modal');

    modals.forEach(modal => {
        const inputs = modal.querySelectorAll('input, textarea, select');

        inputs.forEach(input => {
            // Stop propagation for all events that might interfere
            ['click', 'keydown', 'keyup', 'keypress', 'input', 'focus', 'blur'].forEach(eventType => {
                input.addEventListener(eventType, function (e) {
                    e.stopPropagation();
                }, true);
            });
        });
    });
}

// Call this after DOM is loaded or after modals are created
document.addEventListener('DOMContentLoaded', protectModalInputs);

async function checkAuthenticationOnPageLoad() {
    try {
        const response = await fetch('/admin/upload_status', {
            method: 'GET',
            cache: 'no-cache',
            headers: { 'Cache-Control': 'no-cache' }
        });

        if (!response.ok || response.url.includes('/login')) {
            // FIX: Never redirect mid-upload — the page-load check fires on each hard
            // reload, but if somehow called while uploading is in progress, don't kill it.
            if (isUploading) {
                console.warn('🔒 Page-load auth check failed but upload in progress — skipping redirect');
                return;
            }
            console.log('🔒 Not authenticated, redirecting to login...');
            window.location.replace('/login');
            return;
        }

        console.log('✅ Authentication verified');
    } catch (error) {
        if (isUploading) {
            console.warn('🔒 Page-load auth check error during upload — skipping redirect:', error.message);
            return;
        }
        console.log('🔒 Authentication check failed, redirecting to login...');
        window.location.replace('/login');
    }
}

function cleanupAuthenticationHistory() {
    // Check if we came from the login page and clean up history
    const referrer = document.referrer;
    if (referrer && referrer.includes('/login')) {
        // Replace the current history state to remove login page from history
        const currentUrl = window.location.href;
        console.log('🔄 Cleaning up authentication history');

        // Replace current state to ensure login page is not in history
        window.history.replaceState({ authenticated: true }, '', currentUrl);

        // Add a state to prevent accidental back navigation to login
        window.history.pushState({ authenticated: true }, '', currentUrl);

        // Handle popstate events to prevent going back to login
        window.addEventListener('popstate', function (event) {
            if (event.state && event.state.authenticated) {
                // User is authenticated, prevent going back to login
                console.log('🔒 Preventing navigation back to login page');
                window.history.pushState({ authenticated: true }, '', window.location.href);
            }
        });
    }

    // Add periodic authentication check
    setInterval(checkAuthenticationStatus, 1000); // Check every 1 second
}

// FIX: Track consecutive auth failures — transient network blips must not kill active uploads
let _authFailCount = 0;
const _AUTH_FAIL_THRESHOLD = 3;

async function checkAuthenticationStatus() {
    // Always ping the server — this refreshes the session cookie even on background tabs.
    // Never skip the fetch during upload; only skip the *redirect* so uploads aren't interrupted.
    try {
        const response = await fetch('/check_session', {
            method: 'GET',
            cache: 'no-cache',
            headers: { 'Cache-Control': 'no-cache' }
        });

        if (!response.ok || response.url.includes('/login')) {
            _authFailCount++;
            console.log(`🔒 Auth check failed (${_authFailCount}/${_AUTH_FAIL_THRESHOLD})`);
            if (_authFailCount >= _AUTH_FAIL_THRESHOLD && !isUploading) {
                console.log('🔒 Session expired, redirecting to login...');
                window.location.replace('/login');
            }
        } else {
            _authFailCount = 0;
        }
    } catch (error) {
        _authFailCount++;
        console.log(`🔒 Auth check error (${_authFailCount}/${_AUTH_FAIL_THRESHOLD}):`, error.message);
        if (_authFailCount >= _AUTH_FAIL_THRESHOLD && !isUploading) {
            console.log('🔒 Repeated auth errors, redirecting to login...');
            window.location.replace('/login');
        }
    }
}

// Device detection for mobile-specific features
const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
const isAndroid = /Android/i.test(navigator.userAgent);
const isIOS = /iPhone|iPad|iPod/i.test(navigator.userAgent);

// Global search state tracking
let isSearchResultsDisplayed = false;

// Feature detection for folder upload capabilities
const supportsDragDrop = 'ondrop' in window && 'ondragover' in window;
const supportsWebkitDirectory = 'webkitdirectory' in document.createElement('input');
const supportsWebkitGetAsEntry = 'webkitGetAsEntry' in DataTransferItem.prototype;

console.log(`📱 Device Info: Mobile=${isMobile}, Android=${isAndroid}, iOS=${isIOS}`);
console.log(`🔧 Feature Support: DragDrop=${supportsDragDrop}, WebkitDir=${supportsWebkitDirectory}, WebkitEntry=${supportsWebkitGetAsEntry}`);

// Notification timing configuration (in milliseconds)
// You can easily adjust these values to change how long notifications stay visible:
const NOTIFICATION_TIMERS = {
    SUCCESS: 2000,  // 2 seconds - for positive actions (uploads, deletes, queue operations)
    INFO: 2000,     // 4 seconds - for general information
    ERROR: 4000        // 0 = never auto-hide, stays until manually clicked (for important errors)
};

// Utility function to update notification timers at runtime (for debugging/testing)
function setNotificationTimer(type, milliseconds) {
    if (NOTIFICATION_TIMERS.hasOwnProperty(type.toUpperCase())) {
        NOTIFICATION_TIMERS[type.toUpperCase()] = milliseconds;
        console.log(`📝 Updated ${type.toUpperCase()} notification timer to ${milliseconds}ms`);
    } else {
        console.warn(`❌ Invalid notification type: ${type}. Valid types: SUCCESS, INFO, ERROR`);
    }
}

// Table sorting and searching functionality
let currentSort = { column: null, direction: 'asc' };
let originalRowOrder = []; // Store original order for reset functionality
let searchTimeout = null;

// Search functionality
function searchTable(searchTerm) {
    clearTimeout(searchTimeout);

    // Show/hide clear button
    const clearButton = document.getElementById('clearSearch');
    if (searchTerm.trim()) {
        clearButton.style.display = 'block';
    } else {
        clearButton.style.display = 'none';
    }

    // Debounce search to avoid too many API calls
    searchTimeout = setTimeout(() => {
        if (searchTerm.trim().length >= 2) {
            // Use deep search for queries with 2+ characters
            performDeepSearch(searchTerm.trim());
        } else if (searchTerm.trim().length === 0) {
            // Clear search - return to local filtering
            performLocalSearch('');
        } else {
            // Single character - use local search only
            performLocalSearch(searchTerm.trim());
        }
    }, 500); // Increased debounce for API calls
}

function performLocalSearch(searchTerm) {
    // Hide any deep search results overlay first
    hideDeepSearchResults();

    // Delegate filter to VT engine — works on data array, re-renders visible rows
    VT.applyFilter(searchTerm);

    const count = document.getElementById('visibleCount');
    console.log(`🔍 Local VT filter for "${searchTerm}"`);
}

// Deep search using API to scan nested folders
function performDeepSearch(searchTerm) {
    console.log(`🔍 Starting deep search for: "${searchTerm}"`);

    // Show loading indicator
    showSearchLoading(true);

    fetch(`/api/search?q=${encodeURIComponent(searchTerm)}`)
        .then(response => response.json())
        .then(data => {
            console.log(`✅ Deep search results:`, data);
            displayDeepSearchResults(data, searchTerm);
        })
        .catch(error => {
            console.error('❌ Deep search error:', error);
            showNotification('Search failed. Please try again.', 'ERROR');
            // Fallback to local search
            performLocalSearch(searchTerm);
        })
        .finally(() => {
            showSearchLoading(false);
        });
}


function highlightSearchTerm(row, term) {
    const nameCell = row.querySelector('td:nth-child(2) .file-name');
    if (nameCell) {
        const originalText = nameCell.dataset.originalText || nameCell.textContent;
        nameCell.dataset.originalText = originalText;

        const regex = new RegExp(`(${term})`, 'gi');
        const highlightedText = originalText.replace(regex, '<span class="search-highlight">$1</span>');

        // Only update if we have a match and it's different
        if (highlightedText !== originalText) {
            const linkElement = nameCell.querySelector('a');
            if (linkElement) {
                linkElement.innerHTML = linkElement.textContent.replace(regex, '<span class="search-highlight">$1</span>');
            } else {
                nameCell.innerHTML = nameCell.innerHTML.replace(originalText, highlightedText);
            }
        }
    }
}

function removeHighlights(row) {
    const highlights = row.querySelectorAll('.search-highlight');
    highlights.forEach(highlight => {
        highlight.outerHTML = highlight.textContent;
    });
}

// Deep search helper functions
function displayDeepSearchResults(data, searchTerm) {
    if (!data.results || data.results.length === 0) {
        showNotification(`No results found for "${searchTerm}"`, 'INFO');
        performLocalSearch(searchTerm); // Fallback to local search
        return;
    }

    // Clear any existing search results FIRST to prevent duplicates
    hideDeepSearchResults();

    // Hide local results
    hideLocalResults();

    // Mark that search results are now displayed
    isSearchResultsDisplayed = true;

    // Show deep search results with header above table
    const table = document.getElementById('filesTable');
    const tbody = table.querySelector('tbody');

    // Create search results header as a separate element
    const searchHeader = createSearchResultsHeaderDiv(data);

    // Insert header before the table
    table.parentNode.insertBefore(searchHeader, table);

    // Add search results to table
    data.results.forEach(result => {
        const row = createSearchResultRow(result, searchTerm);
        tbody.appendChild(row);
    });

    // Update visible count
    updateVisibleCount(data.results.length);

    const truncatedMsg = data.truncated ? ` (showing first ${data.total_found})` : '';
    showNotification(`Found ${data.total_found} results${truncatedMsg} in ${data.search_time}s`, 'SUCCESS');
}

function createSearchResultsHeaderDiv(data) {
    const headerDiv = document.createElement('div');
    headerDiv.className = 'search-results-header-div';
    headerDiv.id = 'searchResultsHeader';

    headerDiv.innerHTML = `
        <div class="search-header-content">
            <div class="search-header-main">
                <i class="fas fa-search-plus"></i>
                <span class="search-title">Deep Search Results</span>
                <span class="search-count">${data.total_found} items found</span>
                ${data.truncated ? '<span class="search-truncated">(showing first 100)</span>' : ''}
            </div>
            <div class="search-header-meta">
                <span class="search-time">Search time: ${data.search_time}s</span>
                <button onclick="clearSearch()" class="btn-close-search">
                    <i class="fas fa-times"></i> Close Results
                </button>
            </div>
        </div>
    `;

    return headerDiv;
}

function createSearchResultsHeader(data) {
    const row = document.createElement('tr');
    row.className = 'search-results-header';
    // Add inline styles to force visibility on mobile
    row.style.display = 'table-row';
    row.style.visibility = 'visible';
    row.style.opacity = '1';
    row.style.minHeight = '50px';

    // Detect mobile screen size
    const isMobile = window.innerWidth <= 480;

    row.innerHTML = `
        <td colspan="6" class="search-header-cell" style="display: table-cell !important; visibility: visible !important; width: 100% !important; ${isMobile ? 'font-size: 12px !important; padding: 10px !important;' : ''}">
            <div class="search-header-content" style="display: flex !important; visibility: visible !important; padding: ${isMobile ? '10px' : '12px 15px'}; ${isMobile ? 'flex-direction: column; gap: 8px; min-height: 40px;' : ''}">
                <div class="search-header-main" style="display: flex !important; visibility: visible !important; align-items: center; gap: 12px; flex-wrap: wrap; ${isMobile ? 'font-size: 12px;' : ''}">
                    <i class="fas fa-search-plus" style="${isMobile ? 'font-size: 14px;' : ''}"></i>
                    <span class="search-title" style="display: inline-block !important; visibility: visible !important; ${isMobile ? 'font-size: 12px !important; font-weight: bold !important;' : ''}">Deep Search Results</span>
                    <span class="search-count" style="${isMobile ? 'font-size: 10px; padding: 2px 6px;' : ''}">${data.total_found} items found</span>
                    ${data.truncated ? '<span class="search-truncated">(showing first 100)</span>' : ''}
                </div>
                <div class="search-header-meta" style="display: flex !important; gap: 10px; align-items: center; ${isMobile ? 'justify-content: space-between; width: 100%;' : ''}">
                    <span class="search-time" style="${isMobile ? 'font-size: 10px;' : ''}">Search time: ${data.search_time}s</span>
                    <button onclick="clearSearch()" class="btn-close-search" style="${isMobile ? 'font-size: 10px; padding: 4px 8px;' : ''}">
                        <i class="fas fa-times"></i> Close Results
                    </button>
                </div>
            </div>
        </td>
    `;
    return row;
}

function createSearchResultRow(result, searchTerm) {
    const row = document.createElement('tr');
    row.className = 'file-row search-result-row';
    row.dataset.path = result.path;

    const sizeDisplay = result.is_dir ? `<span class="folder-size-text">Folder</span>` : formatFileSize(result.size);

    // Extract folder path (excluding filename)
    const pathParts = result.path.split('/');
    const folderPath = pathParts.slice(0, -1).join('/');
    const displayPath = folderPath || 'Root';

    // Build safer name HTML using escapeHtml and mapping for icon/type
    let nameHtml = '';
    if (result.is_dir) {
        nameHtml = `
        <div class="search-result-name">
            <div class="search-result-icon">
                <i class="fas fa-folder"></i>
            </div>
            <div class="search-result-details">
                <div class="search-result-title">
                    <a href="#" onclick="navigateToFolder('${escapeHtml(result.path)}'); return false;" 
                       class="search-folder-link">
                        ${highlightText(escapeHtml(result.name), searchTerm)}
                    </a>
                </div>
                <div class="search-result-path">
                    <i class="fas fa-folder-open"></i>
                    /${escapeHtml(displayPath)}
                </div>
            </div>
        </div>`;
    } else {
        const iconClass = getFileIcon(result.name);
        const typeText = getFileType(result.name);
        nameHtml = `
        <div class="search-result-name">
            <div class="search-result-icon">
                <i class="${iconClass}"></i>
            </div>
            <div class="search-result-details">
                <div class="search-result-title">
                    ${highlightText(escapeHtml(result.name), searchTerm)}
                </div>
                <div class="search-result-path">
                    <i class="fas fa-folder-open"></i>
                    /${escapeHtml(displayPath)}
                </div>
            </div>
        </div>`;
        // expose type for the column below
        result._derived_type = typeText;
    }

    const actionsHtml = result.is_dir ?
        `<div class="search-result-actions">
            <button class="btn btn-sm btn-primary" onclick="navigateToFolder('${result.path}')" title="Open folder">
                <i class="fas fa-folder-open"></i>
            </button>
            <button class="btn btn-sm btn-success" onclick="downloadFolderAsZip('${result.path}', '${result.name}')" title="Download folder as ZIP">
                <i class="fas fa-download"></i>
            </button>
            <button class="btn btn-sm btn-outline" onclick="openFileLocation('${folderPath}')" title="Open file location">
                <i class="fas fa-level-up-alt"></i>
            </button>
        </div>` :
        `<div class="search-result-actions">
            <button class="btn btn-sm btn-success" onclick="downloadItem('${result.path}')" title="Download file">
                <i class="fas fa-download"></i>
            </button>
            <button class="btn btn-sm btn-outline" onclick="openFileLocation('${folderPath}')" title="Open file location">
                <i class="fas fa-folder-open"></i>
            </button>
        </div>`;

    row.innerHTML = `
        <td class="search-checkbox-cell">
            <input type="checkbox" class="file-checkbox item-checkbox" 
                   data-path="${result.path}"
                   data-name="${result.name}"
                   data-is-dir="${result.is_dir}"
                   onchange="updateSelection()">
        </td>
        <td class="search-name-cell">${nameHtml}</td>
        <td class="search-size-cell">${sizeDisplay}</td>
        <td class="search-type-cell">${escapeHtml(result._derived_type || result.type || (result.is_dir ? 'Folder' : getFileType(result.name)))}</td>
        <td class="search-date-cell">${result.modified}</td>
        <td class="search-actions-cell">${actionsHtml}</td>
    `;

    return row;
}

function highlightText(text, searchTerm) {
    const regex = new RegExp(`(${searchTerm})`, 'gi');
    return text.replace(regex, '<span class="search-highlight">$1</span>');
}

function hideLocalResults() {
    const table = document.getElementById('filesTable');
    const tbody = table.querySelector('tbody');
    const rows = tbody.querySelectorAll('tr:not(.search-results-header):not(.search-result-row)');

    rows.forEach(row => {
        if (!row.innerHTML.includes('.. (Parent Directory)')) {
            row.style.display = 'none';
        }
    });
}

function hideDeepSearchResults() {
    // Mark that search results are no longer displayed
    isSearchResultsDisplayed = false;

    // Remove table-based search headers
    const searchRows = document.querySelectorAll('.search-results-header, .search-result-row');
    searchRows.forEach(row => row.remove());

    // Remove div-based search header
    const searchHeaderDiv = document.getElementById('searchResultsHeader');
    if (searchHeaderDiv) {
        searchHeaderDiv.remove();
    }

    // Show local results again
    const table = document.getElementById('filesTable');
    const tbody = table.querySelector('tbody');
    const localRows = tbody.querySelectorAll('tr');

    localRows.forEach(row => {
        row.style.display = '';
    });
}

function showSearchLoading(show) {
    const searchInput = document.getElementById('tableSearch');
    if (show) {
        searchInput.style.background = 'url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAiIGhlaWdodD0iMjAiIHZpZXdCb3g9IjAgMCAyMCAyMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KICAgIDxjaXJjbGUgY3g9IjEwIiBjeT0iMTAiIHI9IjMiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzMzMzMzMyIgc3Ryb2tlLXdpZHRoPSIyIj4KICAgICAgICA8YW5pbWF0ZSBhdHRyaWJ1dGVOYW1lPSJyIiB2YWx1ZXM9IjM7NjszIiBkdXI9IjFzIiByZXBlYXRDb3VudD0iaW5kZWZpbml0ZSIvPgogICAgPC9jaXJjbGU+Cjwvc3ZnPg==") no-repeat right 10px center';
        searchInput.style.paddingRight = '35px';
    } else {
        searchInput.style.background = '';
        searchInput.style.paddingRight = '';
    }
}

function updateVisibleCount(count) {
    const visibleCountSpan = document.getElementById('visibleCount');
    if (visibleCountSpan) {
        visibleCountSpan.textContent = count;
    }
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Open file location function for search results
function openFileLocation(folderPath) {
    console.log(`🔍 === OPEN FILE LOCATION START ===`);
    console.log(`🔍 Input folderPath: "${folderPath}"`);
    console.log(`🔍 folderPath type: ${typeof folderPath}`);
    console.log(`🔍 Current path before: "${currentPath}"`);

    // IMPORTANT: Clear search when opening file location
    console.log(`🧹 Clearing search before navigation...`);
    clearSearch();
    hideDeepSearchResults();

    // Clean and validate the folder path
    let targetPath = '';
    if (!folderPath || folderPath === 'Root' || folderPath === '' || folderPath === '/') {
        console.log(`📁 Navigating to root directory (empty path)`);
        targetPath = '';
    } else {
        // Ensure path doesn't start with / and clean it
        targetPath = String(folderPath).replace(/^\/+/, '').trim();
        console.log(`📁 Cleaned target path: "${targetPath}"`);
    }

    console.log(`� Final target path: "${targetPath}"`);
    console.log(`🔍 Calling navigateToFolder...`);

    // Navigate to the folder containing the file
    console.log("🚀 About to call navigateToFolder...");
    navigateToFolder(targetPath).then(() => {
        console.log("✅ navigateToFolder completed successfully");
    }).catch((error) => {
        console.error("❌ navigateToFolder failed:", error);
    });
}

function clearSearch() {
    const searchInput = document.getElementById('tableSearch');
    const clearButton = document.getElementById('clearSearch');

    searchInput.value = '';
    clearButton.style.display = 'none';

    // Clear both local and deep search results
    hideDeepSearchResults();
    performLocalSearch('');
}

// Column sorting functionality
function sortTable(column, forceDirection) {
    // Show reset button
    const resetBtn = document.getElementById('resetSort');
    if (resetBtn) resetBtn.style.display = 'inline-block';

    // Delegate to VT engine (works on data array, handles re-render)
    VT.applySort(column, forceDirection);

    console.log(`📊 Sorted by ${column} (${currentSort.direction})`);
}

function getSortValue(row, column) {
    switch (column) {
        case 'name':
            const nameCell = row.querySelector('td:nth-child(2)');
            if (!nameCell) return '';

            // For folders, get text from the link
            const folderLink = nameCell.querySelector('.folder-link');
            if (folderLink) {
                return folderLink.textContent.trim();
            }

            // For files, get text content but exclude icon text
            const fileDiv = nameCell.querySelector('.file-name');
            if (fileDiv) {
                // Clone the div and remove icon elements to get clean text
                const clone = fileDiv.cloneNode(true);
                const icons = clone.querySelectorAll('i');
                icons.forEach(icon => icon.remove());
                return clone.textContent.trim();
            }

            // Fallback to full text content
            return nameCell.textContent.trim();
        case 'size':
            const sizeCell = row.querySelector('td:nth-child(3)');
            if (!sizeCell) return '';

            // For folders with dir-info-cell, extract size from <small> tag
            const dirInfoCell = sizeCell.querySelector('.dir-info-cell small');
            if (dirInfoCell) {
                return dirInfoCell.textContent.trim();
            }

            // For regular files or folders without size info yet
            return sizeCell.textContent.trim();
        case 'type':
            const typeCell = row.querySelector('td:nth-child(4)');
            return typeCell ? typeCell.textContent.trim() : '';
        case 'modified':
            const modifiedCell = row.querySelector('td:nth-child(5)');
            return modifiedCell ? modifiedCell.textContent.trim() : '';
        default:
            return '';
    }
}

function compareSizes(a, b) {
    const aBytes = parseSize(a);
    const bBytes = parseSize(b);
    return aBytes - bBytes;
}

function parseSize(sizeStr) {
    if (!sizeStr || sizeStr === '--') {
        return 0;
    }

    // Try to extract size value (works for both files and folders)
    const match = sizeStr.match(/([\d.]+)\s*(bytes?|KB|MB|GB|TB)?/i);
    if (!match) return 0;

    const number = parseFloat(match[1]);
    const unit = (match[2] || '').toLowerCase();

    switch (unit) {
        case 'tb': return number * 1024 * 1024 * 1024 * 1024;
        case 'gb': return number * 1024 * 1024 * 1024;
        case 'mb': return number * 1024 * 1024;
        case 'kb': return number * 1024;
        default: return number;
    }
}

function compareDates(a, b) {
    if (a === '--' && b === '--') return 0;
    if (a === '--') return -1;
    if (b === '--') return 1;

    // Simple string comparison should work for ISO dates
    return a.localeCompare(b);
}



function updateSortHeaders(activeColumn, direction) {
    // Reset all headers
    document.querySelectorAll('.sortable').forEach(header => {
        header.classList.remove('sort-asc', 'sort-desc');
        const icon = header.querySelector('.sort-icon');
        if (icon) icon.className = 'fas fa-sort sort-icon';
    });

    // Update active header
    const activeHeader = document.querySelector(`[data-sort="${activeColumn}"]`);
    if (activeHeader) {
        activeHeader.classList.add(`sort-${direction}`);
        const icon = activeHeader.querySelector('.sort-icon');
        if (icon) {
            icon.className = `fas fa-sort-${direction === 'asc' ? 'up' : 'down'} sort-icon`;
        }
    }

    // Update sort info and show/hide reset button
    updateSortInfo(activeColumn, direction);
}

// Store original table order for reset functionality
function storeOriginalTableOrder() {
    const table = document.getElementById('filesTable');
    if (!table) return;

    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));

    // Store clones of all rows in their original order
    originalRowOrder = rows.map(row => row.cloneNode(true));

    console.log('📋 Stored original table order:', originalRowOrder.length, 'rows');
}

// Update sort information display
function updateSortInfo(column, direction) {
    const sortInfo = document.getElementById('currentSortInfo');
    const resetButton = document.getElementById('resetSort');

    if (column && direction) {
        const columnNames = {
            'name': 'Name',
            'size': 'Size',
            'type': 'Type',
            'modified': 'Modified'
        };

        const directionText = direction === 'asc' ? 'ascending' : 'descending';
        const columnText = columnNames[column] || column;

        if (sortInfo) {
            sortInfo.textContent = `• Sorted by ${columnText} (${directionText})`;
        }

        if (resetButton) {
            resetButton.style.display = 'inline-flex';
        }
    } else {
        if (sortInfo) {
            sortInfo.textContent = '';
        }

        if (resetButton) {
            resetButton.style.display = 'none';
        }
    }
}

// Reset sorting to default state
function resetSorting() {
    console.log('🔄 Resetting table sorting to default');

    // Clear deep search results first
    hideDeepSearchResults();

    // Clear search input and hide clear button
    const searchInput = document.getElementById('tableSearch');
    const clearButton = document.getElementById('clearSearch');
    if (searchInput) searchInput.value = '';
    if (clearButton) clearButton.style.display = 'none';

    // Reset sort state
    currentSort = { column: null, direction: 'asc' };

    // Reset all header styles
    document.querySelectorAll('.sortable').forEach(header => {
        header.classList.remove('sort-asc', 'sort-desc');
        const icon = header.querySelector('.sort-icon');
        if (icon) icon.className = 'fas fa-sort sort-icon';
    });

    // Update sort info display
    updateSortInfo(null, null);

    // Always fetch fresh data — never restore stale DOM clones.
    // Clones captured at render time show deleted files if any refresh
    // was blocked between the delete and this reset call.
    refreshFileTable();

    console.log('✅ Table sorting reset — fetching fresh data from server');
}

// Reinitialize table controls after content update
function reinitializeTableControls(itemCount) {
    // Update visible count
    const visibleCountSpan = document.getElementById('visibleCount');
    if (visibleCountSpan) {
        visibleCountSpan.textContent = itemCount;
    }

    // NOTE: do NOT call VT.applyFilter here either — VT._renderAll already
    // applies the current _filter before rendering rows. Calling applyFilter
    // here would re-trigger _renderAll (another infinite loop).

    // NOTE: do NOT call sortTable here — VT already sorts on the data array
    // before rendering. Calling sortTable here would cause an infinite loop:
    // _renderAll → reinitializeTableControls → sortTable → VT.applySort → _renderAll

    // Initialize sort event listeners for any new headers
    document.querySelectorAll('.sortable').forEach(header => {
        // Remove existing event listeners by cloning
        const newHeader = header.cloneNode(true);
        header.parentNode.replaceChild(newHeader, header);

        // Add new event listener
        newHeader.addEventListener('click', function () {
            const column = this.dataset.sort;
            if (column) {
                sortTable(column);
            }
        });
    });

    // Re-apply table-layout:fixed after cloneNode replaces <th> elements
    lockTableColumnWidths();
}

// Upload queue management
let uploadQueue = [];
// Folder groups — keyed by groupId, one entry per folder upload
const folderGroups = new Map();
// O(1) duplicate check — replaces O(n) uploadQueue.find()
const _seenFileKeys = new Set();
let isUploading = false;
let _mutationInFlight = false; // blocks SSE refresh during delete/move
let _deletingPaths = new Set(); // paths currently being deleted — for real-time size feedback
let _lastFreeSpace = null;      // last known free_space from SSE for delta calculation
let _lastTableRefresh = 0;
let currentUploadIndex = 0;
let currentUploadingFile = null;
let cancelledUploads = new Set(); // Track cancelled upload IDs
let uploadStartTime = 0;
// BUG FIX: Throttle timestamp for mid-upload table refreshes (Bug 2)
let _lastMidUploadTableRefresh = 0;
let totalBytesToUpload = 0;
let totalBytesUploaded = 0;
let lazyBytesUploaded = 0; // bytes from completed lazy folder files

// --- Upload freeze/resume protection ---
// Tracks the last time any file completed uploading. Used by the stall detector
// to decide if the upload loop froze when the tab was backgrounded.
let _lastUploadActivity = 0;
// Cooldown tracker: prevents _resumeStalledUploads from spawning duplicate loops
// when the user switches tabs multiple times in quick succession.
let _lastResumeTime = 0;
// Interval handle for session keepalive pings (sent every 60s during uploads)
let _sessionKeepAliveInterval = null;

// Parallel upload configuration
const PARALLEL_UPLOAD_CONFIG = {
    maxConcurrentUploads: 10,  // Number of files to upload simultaneously
    enableParallelUploads: true,  // Can be toggled by user
    activeUploads: new Set(),  // Track currently uploading file IDs
    completedUploads: new Set(), // Track completed upload IDs for progress
};

// Utility function to update parallel upload settings
function setParallelUploadConfig(maxConcurrent, enabled = true) {
    PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads = Math.max(1, Math.min(10, maxConcurrent)); // Limit 1-10
    PARALLEL_UPLOAD_CONFIG.enableParallelUploads = enabled;
    console.log(`⚡ Parallel uploads: ${enabled ? 'Enabled' : 'Disabled'}, Max concurrent: ${PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads}`);
}

// Current path tracking for AJAX navigation
let currentPath = CURRENT_PATH;

// AJAX Folder Navigation
async function navigateToFolder(newPath) {
    try {
        console.log(`� === NAVIGATION START ===`);
        console.log(`📁 Current path: "${currentPath}"`);
        console.log(`📁 Target path: "${newPath}"`);
        console.log(`📁 Path type: ${typeof newPath}`);

        showUploadStatus('📁 Loading folder...', 'info');

        // Clean and validate the path
        const cleanPath = newPath ? String(newPath).trim() : '';
        console.log(`🧹 Cleaned path: "${cleanPath}"`);

        // Update URL without page refresh
        const url = cleanPath ? `/${cleanPath}` : '/';
        console.log(`🔗 Updating URL to: "${url}"`);
        window.history.pushState({ path: cleanPath }, '', url);

        // Fetch folder contents via API
        const apiUrl = cleanPath ? `/api/files/${encodeURIComponent(cleanPath)}` : '/api/files/';
        console.log(`📡 API URL: "${apiUrl}"`);
        console.log(`🔗 Fetching from: ${apiUrl}`);

        console.log("🚀 Starting fetch request...");
        const response = await fetch(apiUrl);
        console.log(`📡 Response status: ${response.status} ${response.statusText}`);
        console.log(`📡 Response headers:`, response.headers);
        console.log("📡 Response object:", response);

        if (!response.ok) {
            // 401 means session expired — show message, redirect only if not uploading
            if (response.status === 401) {
                showUploadStatus('⚠️ Session expired — please log in again', 'error');
                if (!isUploading) {
                    setTimeout(() => { window.location.href = '/login'; }, 1500);
                }
                return;
            }
            throw new Error(`Failed to load folder: ${response.status} ${response.statusText}`);
        }

        // Guard: if the server returned HTML instead of JSON (e.g. session redirect),
        // handle gracefully without a JSON parse explosion.
        const contentType = response.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            showUploadStatus('⚠️ Session expired — please log in again', 'error');
            if (!isUploading) {
                setTimeout(() => { window.location.href = '/login'; }, 1500);
            }
            return;
        }

        console.log("🔄 Parsing response as JSON...");
        const data = await response.json();
        console.log(`📊 Raw API response:`, data);
        console.log(`📊 Response keys:`, Object.keys(data));
        console.log(`📊 data.success:`, data.success);
        console.log(`📊 data.files:`, data.files);
        console.log(`📊 data.error:`, data.error);

        if (!data.success) {
            console.error(`❌ API returned error:`, data.error);
            throw new Error(data.error || 'Failed to load folder contents');
        }

        // Handle different data formats from API
        let files = [];
        if (data.files && Array.isArray(data.files)) {
            files = data.files;
            console.log(`✅ Using data.files array`);
        } else if (data.items && Array.isArray(data.items)) {
            files = data.items;
            console.log(`✅ Using data.items array`);
        } else {
            console.warn(`⚠️ Unexpected data format:`, data);
            console.warn(`⚠️ data.files:`, data.files);
            console.warn(`⚠️ data.items:`, data.items);
            files = [];
        }

        console.log(`📁 Processed files array:`, files);
        console.log(`📁 Found ${files.length} items in folder`);

        // Update current path
        const oldPath = currentPath;
        currentPath = cleanPath;
        console.log(`📝 Updated currentPath: "${oldPath}" → "${currentPath}"`);

        // Update hidden path input
        const pathInput = document.querySelector('input[name="path"]');
        if (pathInput) {
            pathInput.value = currentPath;
            console.log(`📝 Updated hidden path input to: "${currentPath}"`);
        }

        // Update page content
        console.log(`🔄 Updating file table with ${files.length} items...`);
        console.log(`🔄 Files array:`, files);
        console.log(`🔄 Before update - table body innerHTML length:`, document.querySelector('#filesTable tbody')?.innerHTML?.length || 'not found');
        updateFileTable(files, cleanPath);
        console.log(`🔄 After update - table body innerHTML length:`, document.querySelector('#filesTable tbody')?.innerHTML?.length || 'not found');
        console.log(`🍞 Updating breadcrumb...`);
        updateBreadcrumb(cleanPath);

        // Scroll table rows to top, then bring table into view on the page
        requestAnimationFrame(() => {
            const wrapper = document.getElementById('tableScrollWrapper');
            if (wrapper) wrapper.scrollTop = 0;
            const fileTable = document.querySelector('.file-table');
            if (fileTable) fileTable.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });

        // Clear selection when navigating
        clearSelection();

        // Also clear any search filters when navigating
        const searchInput = document.getElementById('tableSearch');
        if (searchInput && searchInput.value) {
            console.log(`🧹 Clearing search filter during navigation...`);
            clearSearch();
        }

        console.log(`✅ === NAVIGATION SUCCESS ===`);
        showUploadStatus(`📁 Loaded folder: ${cleanPath || 'Root'}`, 'success');

    } catch (error) {
        console.error('❌ Navigation error:', error.message);
        showUploadStatus(`❌ Failed to load folder: ${error.message}`, 'error');

        // Only fallback-reload if not uploading — a reload kills the active upload
        if (!isUploading) {
            setTimeout(() => {
                window.location.href = newPath ? `/${newPath}` : '/';
            }, 2000);
        }
    }
}

// Handle browser back/forward buttons
window.addEventListener('popstate', function (event) {
    const path = event.state?.path || '';
    console.log('🔄 POPSTATE EVENT FIRED - Browser back/forward navigation to:', path);
    navigateToFolder(path);
});

function _initVTFromPageData() {
    const tbody = document.querySelector('#filesTable tbody');
    if (!tbody) return;

    // Remove the initial loading spinner row if present
    const loader = document.getElementById('vtInitialLoader');
    if (loader) loader.remove();

    const dataEl = document.getElementById('initialFilesData');
    let files = [];
    if (dataEl) {
        try {
            files = JSON.parse(dataEl.textContent || '[]');
        } catch (e) {
            console.warn('⚠️ _initVTFromPageData: JSON parse failed, starting empty', e);
        }
    }

    // Always init VT — even for empty folders it must set _curPath so the
    // sticky parent row and sort/filter work correctly on first load.
    tbody.innerHTML = '';
    VT.init(files, CURRENT_PATH);
}

/** Parse "1.5 MB" / "230 KB" / "4.2 GB" → approximate bytes for sort */
function _parseDisplaySize(str) {
    if (!str || str === '--') return 0;
    const m = str.match(/([\d.]+)\s*(bytes?|KB|MB|GB|TB)?/i);
    if (!m) return 0;
    const n = parseFloat(m[1]);
    switch ((m[2] || '').toLowerCase()) {
        case 'tb': return n * 1e12;
        case 'gb': return n * 1e9;
        case 'mb': return n * 1e6;
        case 'kb': return n * 1024;
        default: return n;
    }
}

/** Parse displayed date string → Unix timestamp (approximate, for sort only) */
function _parseDisplayDate(str) {
    if (!str || str === '--') return 0;
    try { return Math.floor(new Date(str.replace(/\n/g, ' ')).getTime() / 1000) || 0; }
    catch (e) { return 0; }
}

const VT = (() => {
    const CHUNK = 80;     // rows to render per batch
    let _allFiles = []; // raw server data for current folder
    let _curPath = '';
    let _filter = ''; // active search term
    let _sortCol = null;
    let _sortDir = 'asc';
    let _rendered = 0;
    let _observer = null;
    let _searchResultsMode = false; // true when deep-search is active

    const _dirInfoCache = new Map();
    // ── public API ────────────────────────────────────────────
    function init(files, path) {
        _allFiles = Array.isArray(files) ? files : [];
        _curPath = path ? path.replace(/\\/g, '/').replace(/\/$/, '') : '';
        _filter = '';
        _rendered = 0;
        _searchResultsMode = false;
        // preserve existing sort state
        _sortCol = currentSort.column;
        _sortDir = currentSort.direction;
        // Re-apply cached folder sizes so they survive a refresh rebuild.
        _allFiles.forEach(f => {
            if (!f.is_dir) return;
            const fullPath = _curPath ? `${_curPath}/${f.name}` : f.name;
            const cached = _dirInfoCache.get(fullPath);
            if (cached) f.size = cached.total_size;
        });
        _renderAll();
    }

    function applySort(col, forceDir) {
        if (_searchResultsMode) return;
        if (forceDir) {
            currentSort.column = col;
            currentSort.direction = forceDir;
        } else if (currentSort.column === col) {
            currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
        } else {
            currentSort.column = col;
            currentSort.direction = 'asc';
        }
        _sortCol = currentSort.column;
        _sortDir = currentSort.direction;
        updateSortHeaders(_sortCol, _sortDir);
        _rendered = 0;
        _renderAll();
    }

    function applyFilter(term) {
        _filter = (term || '').toLowerCase().trim();
        _rendered = 0;
        _searchResultsMode = false;
        _renderAll();
        const clearBtn = document.getElementById('clearSearch');
        if (clearBtn) clearBtn.style.display = _filter ? 'block' : 'none';
    }

    function markSearchResults() {
        _searchResultsMode = true;
        _disconnectObserver();
    }

    function getAll() { return _allFiles; }
    function getPath() { return _curPath; }

    function patchFolderSize(folderFullPath, totalSize) {
        const existing = _dirInfoCache.get(folderFullPath) || {};
        _dirInfoCache.set(folderFullPath, { ...existing, total_size: totalSize });
        const folderName = folderFullPath.split('/').pop();
        const entry = _allFiles.find(f => f.is_dir && f.name === folderName);
        if (entry) entry.size = totalSize;
    }

    function cacheDirInfo(fullPath, data) {
        _dirInfoCache.set(fullPath, { file_count: data.file_count, dir_count: data.dir_count, total_size: data.total_size || 0 });
        const folderName = fullPath.split('/').pop();
        const entry = _allFiles.find(f => f.is_dir && f.name === folderName);
        if (entry) entry.size = data.total_size || 0;
    }

    function getCachedDirInfo(fullPath) {
        return _dirInfoCache.get(fullPath) || null;
    }

    function invalidateDirCache(fullPath) {
        _dirInfoCache.delete(fullPath);
    }

    function clearDirCache() {
        _dirInfoCache.clear();
    }

    // ── internals ─────────────────────────────────────────────
    function _getDisplayFiles() {
        let list = _allFiles;

        // 1. filter
        if (_filter) {
            list = list.filter(item =>
                item.name.toLowerCase().includes(_filter) ||
                (item.is_dir ? 'folder' : _getTypeName(item.name)).toLowerCase().includes(_filter)
            );
        }

        // 2. sort
        if (_sortCol) {
            const dir = _sortDir === 'asc' ? 1 : -1;
            list = [...list].sort((a, b) => {
                // folders always first (Windows Explorer rule)
                if (a.is_dir && !b.is_dir) return dir === 1 ? -1 : 1;
                if (!a.is_dir && b.is_dir) return dir === 1 ? 1 : -1;

                let cmp = 0;
                if (_sortCol === 'name') {
                    cmp = a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
                } else if (_sortCol === 'size') {
                    const sa = (a.size != null) ? a.size : -1;
                    const sb = (b.size != null) ? b.size : -1;
                    cmp = sa - sb;
                } else if (_sortCol === 'modified') {
                    cmp = (a.modified || 0) - (b.modified || 0);
                } else if (_sortCol === 'type') {
                    const ta = a.is_dir ? 'Folder' : _getTypeName(a.name);
                    const tb = b.is_dir ? 'Folder' : _getTypeName(b.name);
                    cmp = ta.localeCompare(tb, undefined, { numeric: true, sensitivity: 'base' });
                }
                return cmp * dir;
            });
        }

        return list;
    }

    function _getTypeName(filename) {
        try { return getFileType(filename); } catch (e) { return 'File'; }
    }

    function _getTbody() { return document.querySelector('#filesTable tbody'); }

    function _renderAll() {
        const tbody = _getTbody();
        if (!tbody) return;
        _disconnectObserver();
        tbody.innerHTML = '';

        // parent-directory row
        if (_curPath) {
            const parentPath = _curPath.split('/').slice(0, -1).join('/');
            const pRow = document.createElement('tr');
            pRow.className = 'parent-dir-sticky';
            pRow.innerHTML = `
                <td></td>
                <td><div class="file-name">
                    <i class="fas fa-level-up-alt file-icon folder-icon"></i>
                    <a href="#" onclick="navigateToFolder('${parentPath}'); return false;" class="folder-link">
                        .. (Parent Directory)
                    </a>
                </div></td>
                <td class="size-cell"><span style="color:white;font-size:13px;"></span></td>
                <td class="type-cell"><span class="file-type"></span></td>
                <td class="date-cell"><span style="color:white;font-size:13px;"></span></td>
                <td></td>`;
            tbody.appendChild(pRow);
            _updateTheadHeightVar();
        }

        const display = _getDisplayFiles();

        if (display.length === 0) {
            tbody.appendChild(createEmptyFolderRow());
            updateVisibleCount(0);
            reinitializeTableControls(0);
            return;
        }

        // render first chunk
        const end = Math.min(CHUNK, display.length);
        for (let i = 0; i < end; i++) {
            tbody.appendChild(createFileTableRow(display[i], _curPath));
        }
        _rendered = end;

        // highlight if filtering
        if (_filter) {
            _highlightVisible(_filter);
        }

        updateVisibleCount(display.length);
        reinitializeTableControls(display.length);

        // sentinel for infinite scroll
        if (_rendered < display.length) {
            _attachSentinel(display);
        }

        loadDirInfoCells();
        storeOriginalTableOrder();
    }

    function _renderNextChunk(display) {
        if (_rendered >= display.length) {
            _disconnectObserver();
            _removeSentinel();
            return;
        }
        const tbody = _getTbody();
        if (!tbody) return;

        // remove old sentinel
        _removeSentinel();

        const end = Math.min(_rendered + CHUNK, display.length);
        for (let i = _rendered; i < end; i++) {
            tbody.appendChild(createFileTableRow(display[i], _curPath));
        }
        _rendered = end;

        if (_filter) {
            _highlightVisible(_filter);
        }

        loadDirInfoCells();

        if (_rendered < display.length) {
            _attachSentinel(display);
        }
    }

    function _attachSentinel(display) {
        const tbody = _getTbody();
        if (!tbody) return;

        // loading indicator row
        const loadRow = document.createElement('tr');
        loadRow.id = 'vtSentinelRow';
        loadRow.className = 'vt-loading-row';
        loadRow.innerHTML = `<td colspan="6">
            <span id="vtSentinel" style="display:inline-block;height:1px;width:100%;"></span>
            <i class="fas fa-circle-notch fa-spin" style="margin-right:6px;opacity:0.6;font-size:12px;"></i>
            <span style="font-size:12px;opacity:0.7;">Loading ${Math.min(CHUNK, display.length - _rendered)} more of ${display.length - _rendered} remaining…</span>
        </td>`;
        tbody.appendChild(loadRow);

        const sentinel = document.getElementById('vtSentinel');
        if (!sentinel) return;

        const wrapper = document.getElementById('tableScrollWrapper');
        _observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    _disconnectObserver();
                    _renderNextChunk(display);
                }
            });
        }, { root: wrapper, threshold: 0.1 });
        _observer.observe(sentinel);
    }

    function _removeSentinel() {
        const row = document.getElementById('vtSentinelRow');
        if (row) row.remove();
    }

    function _disconnectObserver() {
        if (_observer) { _observer.disconnect(); _observer = null; }
    }

    function _highlightVisible(term) {
        const tbody = _getTbody();
        if (!tbody) return;
        tbody.querySelectorAll('tr.file-row').forEach(row => {
            highlightSearchTerm(row, term);
        });
    }

    function _updateTheadHeightVar() {
        // Measures real thead height → writes CSS var so the sticky
        // parent row top offset is always pixel-perfect.
        requestAnimationFrame(() => {
            const thead = document.querySelector('#filesTable thead');
            const wrapper = document.getElementById('tableScrollWrapper');
            if (thead && wrapper) {
                wrapper.style.setProperty('--table-thead-h', thead.offsetHeight + 'px');
            }
        });
    }

    return { init, applySort, applyFilter, getAll, getPath, markSearchResults, patchFolderSize, cacheDirInfo, getCachedDirInfo, invalidateDirCache, clearDirCache };
})();

function updateFileTable(files, path) {
    console.log(`🔄 updateFileTable: ${files ? files.length : 0} items at "${path}"`);

    const tbody = document.querySelector('#filesTable tbody');
    if (!tbody) { console.error('❌ File table body not found'); return; }

    // Clear deep search results from overlay
    hideDeepSearchResults();

    // Hand off to virtual table engine
    VT.init(files || [], path);

    console.log(`📋 updateFileTable complete (VT engine)`);
}

// Create empty folder message row
function createEmptyFolderRow() {
    const row = document.createElement('tr');
    row.className = 'empty-folder-row';
    row.innerHTML = `
        <td colspan="6" style="text-align: center; padding: 40px 20px; color: white;">
            <div style="opacity: 0.6; display: flex; flex-direction: column; align-items: center;">
                <i class="fas fa-folder-open" style="font-size: 48px; margin-bottom: 15px;"></i>
                <div style="font-size: 16px; font-weight: 500; margin-bottom: 5px;">This folder is empty</div>
                <div style="font-size: 13px;">No files or folders to display</div>
            </div>
        </td>
    `;
    return row;
}

// Create a file table row element
function createFileTableRow(item, currentPath) {
    const row = document.createElement('tr');

    const itemPath = currentPath ? `${currentPath}/${item.name}` : item.name;

    // Add the file-row class that matches the original template
    row.className = 'file-row';
    row.setAttribute('data-path', itemPath);

    // Use escaped names and mapped icons/types
    const safeName = escapeHtml(item.name);
    const itemIcon = item.is_dir ? 'fas fa-folder' : getFileIcon(item.name);
    const itemTypeText = item.is_dir ? 'Folder' : getFileType(item.name);

    row.innerHTML = `
        <td>
            <input type="checkbox" class="file-checkbox item-checkbox" 
                   data-path="${itemPath}" 
                   data-name="${item.name}"
                   data-is-dir="${item.is_dir ? 'true' : 'false'}"
                   onchange="updateSelection()" ${selectedItems.has(itemPath) ? 'checked' : ''}>
        </td>
        <td class="name-cell">
            <div class="file-name">
                ${item.is_dir ?
            `<i class="fas fa-folder file-icon folder-icon"></i>
                     <a href="#" onclick="navigateToFolder('${escapeHtml(itemPath)}'); return false;" 
                        data-folder-path="${escapeHtml(itemPath)}" class="folder-link">
                         ${safeName}
                     </a>` :
            `<i class="${itemIcon} file-icon file-icon-default" style="color: ${getFileColor(item.name)}"></i>
                     ${safeName}${getViewerType(item.name) ? ` <button type="button" class="btn-eye-view" onclick="event.stopPropagation();openFileViewer('${escapeHtml(itemPath)}','${escapeHtml(item.name)}')" title="Preview"><i class="fas fa-eye"></i></button>` : ''}`
        }
            </div>
        </td>
        <td class="size-cell">
            ${item.is_dir ?
            `<span class="dir-info-cell" data-dir-path="${escapeHtml(itemPath)}" style="color: white; font-size: 13px;">
                    <i class="fas fa-spinner fa-spin" style="opacity: 0.4; font-size: 11px;"></i>
                </span>` :
            `<span class="file-size" style="color: white; font-weight: 500;">${formatFileSize(item.size)}</span>`
        }
        </td>
        <td class="type-cell">
            ${`<span class="file-type"><i class="${item.is_dir ? 'fas fa-folder folder-icon file-icon' : itemIcon}"></i> ${escapeHtml(itemTypeText)}</span>`}
        </td>
        <td class="date-cell">
            ${item.modified ?
            `<span class="file-date" style="color: white; font-size: 12px; white-space: nowrap;">${(() => { const d = new Date(item.modified * 1000); return d.toLocaleDateString('en-US') + ' ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }); })()}</span>` :
            '<span style="color: white; font-size: 12px;">--</span>'
        }
        </td>
        <td class="actions-cell">
            <div class="actions" style="display:flex;flex-wrap:nowrap;gap:3px;align-items:center;">
                ${!item.is_dir ?
            `<button type="button" class="btn btn-outline btn-sm download-btn" 
                             data-item-path="${itemPath}"
                             data-label="Download"
                             onclick="downloadItem('${itemPath}')"
                             title="Download file">
                         <i class="fas fa-download"></i>
                     </button>` :
            `<button type="button" class="btn btn-outline btn-sm download-btn" 
                             data-item-path="${itemPath}"
                             data-label="Download ZIP"
                             onclick="downloadFolderAsZip('${itemPath}', '${item.name}')"
                             title="Download folder as ZIP">
                         <i class="fas fa-download"></i>
                     </button>`
        }
                
                ${USER_ROLE === 'readwrite' ? `
                <button type="button" class="btn btn-warning btn-sm move-btn" 
                        data-item-name="${item.name}"
                        data-item-path="${itemPath}"
                        data-label="Move"
                        onclick="showSingleMoveModal('${itemPath}', '${item.name}')"
                        title="Move">
                    <i class="fas fa-cut"></i>
                </button>
                
                <button type="button" class="btn btn-success btn-sm copy-btn" 
                        data-item-name="${item.name}"
                        data-item-path="${itemPath}"
                        data-label="Copy"
                        onclick="showSingleCopyModal('${itemPath}', '${item.name}')"
                        title="Copy">
                    <i class="fas fa-copy"></i>
                </button>
                
                <button type="button" class="btn btn-primary btn-sm rename-btn" 
                        data-item-name="${item.name}"
                        data-item-path="${itemPath}"
                        data-label="Rename"
                        onclick="showSingleRenameModal('${itemPath}', '${item.name}')"
                        title="Rename">
                    <i class="fas fa-edit"></i>
                </button>
                
                <button type="button" class="btn btn-danger btn-sm delete-btn" 
                        data-item-name="${item.name}"
                        data-item-path="${itemPath}"
                        data-label="Delete"
                        onclick="showSingleDeleteModal('${itemPath}', '${item.name}')"
                        title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
                ` : ''}
            </div>
        </td>
    `;

    applyColumnWidths(row);
    return row;
}

// Lazy-load folder size and item count for all visible dir-info-cell spans.
// Called after every table render — initial load, navigation, and SSE refresh.
function loadDirInfoCells() {
    function formatSize(bytes) {
        if (!bytes || bytes <= 0) return null;
        if (bytes >= 1024 * 1024 * 1024) return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
        if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return bytes + ' bytes';
    }

    const cells = document.querySelectorAll('.dir-info-cell');
    if (!cells.length) return;

    cells.forEach(function (cell) {
        if (cell.dataset.loaded === 'true') return;
        cell.dataset.loaded = 'true';

        const dirPath = cell.dataset.dirPath;

        const cached = VT.getCachedDirInfo(dirPath);
        if (cached !== null) {
            var html = cached.file_count + ' files, ' + cached.dir_count + ' folders';
            if (cached.total_size > 0) {
                html += '<br><small style="color:white;">' + formatSize(cached.total_size) + '</small>';
            }
            cell.innerHTML = html;
            return;
        }

        fetch('/api/dir_info/' + dirPath)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) { cell.textContent = '--'; return; }
                var html = data.file_count + ' files, ' + data.dir_count + ' folders';
                var sizeStr = formatSize(data.total_size);
                if (sizeStr) {
                    html += '<br><small style="color:white;">' + sizeStr + '</small>';
                }
                cell.innerHTML = html;
                VT.cacheDirInfo(dirPath, data);
            })
            .catch(function () { cell.textContent = '--'; });
    });
}

// Update breadcrumb navigation
function updateBreadcrumb(path) {
    console.log(`🍞 Updating breadcrumb for path: "${path}"`);

    const breadcrumbContainer = document.querySelector('.breadcrumb');
    if (!breadcrumbContainer) {
        console.error('❌ Breadcrumb container not found!');
        return;
    }

    // Find or create the flex container (first div child with flex styling)
    let flexContainer = breadcrumbContainer.querySelector('div[style*="display: flex"]');

    if (!flexContainer) {
        console.log('📦 Creating new flex container...');
        flexContainer = document.createElement('div');
        flexContainer.style.cssText = 'display: flex; align-items: center; justify-content: space-between;';

        // Insert before controls div if it exists
        const controlsDiv = breadcrumbContainer.querySelector('.controls');
        if (controlsDiv) {
            breadcrumbContainer.insertBefore(flexContainer, controlsDiv);
        } else {
            breadcrumbContainer.insertBefore(flexContainer, breadcrumbContainer.firstChild);
        }
    }

    // Build the flex container content
    const displayPath = path ? `/Root/${path}` : '/Root/';
    let flexHTML = `<h3><i class="fas fa-folder-open"></i> ${displayPath}</h3>`;

    // Add navigation buttons if not at root
    if (path && path !== '') {
        flexHTML += '<div class="btn-group" style="display: flex; gap: 5px;">';

        // Root button
        flexHTML += `
            <a href="#" onclick="navigateToFolder(''); return false;" 
               class="btn btn-outline btn-sm"
               style="color: white; border-color: rgba(255,255,255,0.4);" 
               title="Go to root folder">
                <i class="fas fa-home"></i> Root
            </a>`;

        // Calculate parent path for Up button
        let parentPath = '';
        if (path.includes('/')) {
            const pathParts = path.split('/');
            pathParts.pop();
            parentPath = pathParts.join('/');
        }

        // Escape single quotes in parentPath for onclick
        const escapedParentPath = parentPath.replace(/'/g, "\\'");

        // Up button
        flexHTML += `
            <a href="#" onclick="navigateToFolder('${escapedParentPath}'); return false;"
               class="btn btn-outline btn-sm"
               style="color: white; border-color: rgba(255,255,255,0.4);"
               title="Go up one level to: ${parentPath || 'Root'}">
                <i class="fas fa-level-up-alt"></i> Up
            </a>`;

        flexHTML += '</div>';
    }

    // Update the flex container
    flexContainer.innerHTML = flexHTML;
    console.log(`✅ Updated breadcrumb to: "${displayPath}"`);

    // Update hidden path input if it exists
    const pathInput = breadcrumbContainer.querySelector('input[name="path"]');
    if (pathInput) {
        pathInput.value = path || '';
        console.log(`📝 Updated hidden path input to: "${path || ''}"`);
    }
}

// Selection management
let selectedItems = new Set();
let _lastRenderedPath = undefined;
let currentModalAction = '';

// Storage stats loading with enhanced error handling
async function loadStorageStats() {
    try {
        console.log('� Loading storage stats...');

        // Single-phase approach with longer timeout for reliability
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 20000); // 20 second timeout

        let response;
        try {
            // Try the normal authenticated endpoint first
            response = await fetch('/api/storage_stats', {
                signal: controller.signal,
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Cache-Control': 'no-cache'
                }
            });
        } catch (authError) {
            console.log('Auth endpoint failed, trying debug endpoint:', authError);
            // If auth fails, try debug endpoint
            response = await fetch('/api/storage_stats_debug', {
                signal: controller.signal,
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Cache-Control': 'no-cache'
                }
            });
        }

        clearTimeout(timeoutId);

        console.log('Storage stats response status:', response.status);

        if (response.ok) {
            const data = await response.json();
            console.log('✅ Storage stats loaded successfully:', data);

            // Handle both normal and debug response formats
            const stats = data.stats || data;
            updateStorageDisplay(stats);
        } else {
            console.warn('Failed to load storage stats, status:', response.status);
            const errorText = await response.text();
            console.warn('Error response:', errorText);
            showStorageError('Server Error');
        }
    } catch (error) {
        console.error('Error loading storage stats:', error);
        if (error.name === 'AbortError') {
            console.error('Storage stats request timed out');
            showStorageError('Timeout - Try refreshing');
        } else if (error.name === 'TypeError' && error.message.includes('fetch')) {
            console.error('Network error - server might be unreachable');
            showStorageError('Network Error');
        } else {
            showStorageError('Error');
        }
    }
}

function showStorageError(errorType) {
    const elements = ['totalSpace', 'freeSpace', 'usedSpace', 'fileCount', 'dirCount'];
    elements.forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = errorType;
            element.style.color = '#ff6b6b';
        }
    });

    // Hide progress bar on error
    const progressBar = document.querySelector('.progress-bar');
    if (progressBar) {
        progressBar.style.display = 'none';
    }

    // Show retry button on error
    const retryButton = document.getElementById('retryStorageStats');
    if (retryButton) {
        retryButton.style.display = 'inline-block';
    }
}

// Retry function for storage stats
async function retryStorageStats() {
    console.log('Retrying storage stats...');

    // Hide retry button during retry
    const retryButton = document.getElementById('retryStorageStats');
    if (retryButton) {
        retryButton.style.display = 'none';
    }

    // Reset loading state
    const elements = ['totalSpace', 'freeSpace', 'usedSpace', 'fileCount'];
    elements.forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = 'Loading...';
            element.style.color = 'white';
        }
    });

    // Try to reinitialize
    await initializeStorageStats();
}

function updateStorageDisplay(stats) {
    console.log('📊 updateStorageDisplay called with:', stats);

    // Update text displays with null checks
    const totalSpaceEl = document.getElementById('totalSpace');
    const freeSpaceEl = document.getElementById('freeSpace');
    const usedSpaceEl = document.getElementById('usedSpace');
    const fileCountEl = document.getElementById('fileCount');
    const dirCountEl = document.getElementById('dirCount');

    console.log('📊 Found elements:', {
        totalSpaceEl: !!totalSpaceEl,
        freeSpaceEl: !!freeSpaceEl,
        usedSpaceEl: !!usedSpaceEl,
        fileCountEl: !!fileCountEl
    });

    // Update disk space (always numeric)
    if (totalSpaceEl && typeof stats.total_space === 'number') {
        if (totalSpaceEl) {
            totalSpaceEl.textContent = formatFileSize(stats.total_space || 0);
            totalSpaceEl.style.color = 'white';
        }
        console.log('✅ Updated totalSpace:', formatFileSize(stats.total_space));
    } else {
        console.log('❌ Failed to update totalSpace:', { totalSpaceEl: !!totalSpaceEl, total_space: stats.total_space, type: typeof stats.total_space });
    }
    if (freeSpaceEl && typeof stats.free_space === 'number') {
        if (freeSpaceEl) {
            freeSpaceEl.textContent = formatFileSize(stats.free_space || 0);
            freeSpaceEl.style.color = 'white';
        }
        console.log('✅ Updated freeSpace:', formatFileSize(stats.free_space));
    }
    if (usedSpaceEl && typeof stats.used_space === 'number') {
        if (usedSpaceEl) {
            usedSpaceEl.textContent = formatFileSize(stats.used_space || 0);
            usedSpaceEl.style.color = 'white';
        }
        console.log('✅ Updated usedSpace:', formatFileSize(stats.used_space));
    }

    // Handle file counts (should be numbers)
    if (fileCountEl) {
        const fileText = `${stats.file_count || 0} files, ${stats.dir_count || 0} folders`;
        if (fileCountEl) {
            fileCountEl.textContent = fileText;
            fileCountEl.style.color = 'white';
        }
        console.log('✅ Updated fileCount:', fileText);
    }

    // Calculate and display usage percentage (only if we have numeric values)
    if (typeof stats.total_space === 'number' && typeof stats.used_space === 'number') {
        const usagePercent = stats.total_space > 0 ? (stats.used_space / stats.total_space) * 100 : 0;
        const usagePercentRounded = Math.round(usagePercent * 10) / 10; // Round to 1 decimal

        const usagePercentageEl = document.getElementById('usagePercentage');
        const diskUsageFillEl = document.getElementById('diskUsageFill');

        if (usagePercentageEl) usagePercentageEl.textContent = `${usagePercentRounded}%`;
        if (diskUsageFillEl) {
            diskUsageFillEl.style.width = `${usagePercent}%`;

            // Change color based on usage
            if (usagePercent < 70) {
                diskUsageFillEl.style.background = 'linear-gradient(90deg, #27ae60, #2ecc71)';
            } else if (usagePercent < 90) {
                diskUsageFillEl.style.background = 'linear-gradient(90deg, #f39c12, #e67e22)';
            } else {
                diskUsageFillEl.style.background = 'linear-gradient(90deg, #e74c3c, #c0392b)';
            }

            // Show progress bar on successful load
            const progressBar = document.querySelector('.progress-bar');
            if (progressBar) {
                progressBar.style.display = 'block';
            }
        }

        // Add content size info to the title
        if (stats.content_size !== stats.used_space) {
            const contentSizeText = `Content: ${formatFileSize(stats.content_size)}`;
            const usedSpaceEl = document.getElementById('usedSpace');
            if (usedSpaceEl && usedSpaceEl.parentElement) {
                usedSpaceEl.parentElement.title = contentSizeText;
            }
        }
    }

    // Hide retry button on successful load
    const retryButton = document.getElementById('retryStorageStats');
    if (retryButton) {
        retryButton.style.display = 'none';
    }
}

// Track if user is actively downloading to avoid false beforeunload warnings
let activeDownloads = new Set();

window.addEventListener('beforeunload', function (e) {
    // Only show warning if uploads are in progress AND user is actually navigating away
    // Don't interfere with downloads
    if ((isUploading || uploadQueue.some(item => item.status === 'pending')) && activeDownloads.size === 0) {
        // Try immediate cleanup for chunks
        cleanupUnfinishedChunks().catch(console.error);

        // Show warning message
        const message = 'Upload in progress. Leaving will cancel uploads and cleanup temporary files.';
        e.preventDefault();
        e.returnValue = message;
        return message;
    }
});

// Page visibility handling
document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
        // Only cleanup if NOT uploading — never interrupt active uploads
        if (!isUploading && uploadQueue.some(item => item.status === 'pending' || item.status === 'error')) {
            console.log('🧹 Page hidden - cleaning up abandoned uploads');
            cleanupUnfinishedChunks().catch(console.error);
        }
    } else if (document.visibilityState === 'visible') {
        console.log('👀 Page visible again');
        if (!isUploading) {
            updateManualCleanupButton();
        }
    }
});

// Better connection handling
window.addEventListener('online', function () {
    console.log('🌐 Connection restored');
    const failedItems = uploadQueue.filter(item => item.status === 'error');
    if (failedItems.length > 0) {
        showUploadStatus(`🌐 Connection restored. ${failedItems.length} failed upload(s) can be retried.`, 'info');
    }
});

window.addEventListener('offline', function () {
    console.log('📡 Connection lost');
    showUploadStatus('📡 Connection lost. Uploads will fail until connection is restored.', 'error');
});

// File input handling
document.getElementById('fileInput')?.addEventListener('change', function (e) {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
        addFilesToQueue(files);
        // Reset input for future selections
        e.target.value = '';
    }
});

function addFilesToQueue(files) {
    // Separate folder uploads (have relativePath / webkitRelativePath) from plain files
    const folderFiles = [];
    const plainFiles = [];
    files.forEach(file => {
        const fp = file.relativePath || file.webkitRelativePath || '';
        if (fp.includes('/')) folderFiles.push(file);
        else plainFiles.push(file);
    });

    // Plain files — one queue row each, O(1) duplicate check
    let added = 0;
    plainFiles.forEach(file => {
        const key = `${currentPath}::${file.name}::${file.size}`;
        if (_seenFileKeys.has(key)) { showUploadStatus(`⚠️ "${file.name}" already in queue`, 'info'); return; }
        _seenFileKeys.add(key);
        uploadQueue.push({
            id: generateFileId(file), file,
            name: file.name, displayName: file.name,
            destinationPath: currentPath,
            size: file.size, status: 'pending',
            progress: 0, error: null, uploadedBytes: 0,
            createdTime: Date.now(),
            _seenKey: key  // stored so we can remove it from _seenFileKeys on cleanup
        });
        added++;
    });
    if (added > 0) {
        updateQueueDisplay();
        showUploadStatus(`➕ Added ${added} file(s) to queue`, 'success');
        _spawnFileWorkersIfNeeded();
    }

    // Folder files (webkitdirectory fallback) — group by root folder, show 1 row per folder
    if (folderFiles.length > 0) {
        _addFolderFilesToQueue(folderFiles);
    }
}

/**
 * Called from drag-drop path — groups files by root folder, registers lazily.
 * Does NOT push into uploadQueue upfront (avoids memory spike).
 * Files are iterated one-at-a-time when upload actually starts.
 */
function _addFolderFilesToQueue(files) {
    // Group by root folder name to detect which distinct folders were dropped
    const byRoot = new Map();
    for (let i = 0; i < files.length; i++) {
        const fp = (files[i].relativePath || files[i].webkitRelativePath || '').replace(/^\//, '');
        const root = fp.split('/')[0] || 'Upload';
        if (!byRoot.has(root)) byRoot.set(root, []);
        byRoot.get(root).push(files[i]);
    }

    byRoot.forEach((groupFiles, rootName) => {
        for (const g of folderGroups.values()) {
            if (g.rootName === rootName) {
                showUploadStatus(`📁 "${rootName}" is already in the queue`, 'info');
                return;
            }
        }
        const groupId = `fg_${Date.now()}_${Math.random().toString(36).slice(2)}`;
        const group = {
            id: groupId, rootName,
            basePath: currentPath || '',
            pendingFiles: groupFiles,
            totalCount: groupFiles.length,
            scanned: groupFiles.length,
            completed: 0, errors: 0,
            totalSize: 0,
            status: 'pending',
            scanComplete: true,
            cancelled: false,
            createdTime: Date.now()
        };
        folderGroups.set(groupId, group);
        updateQueueDisplay();
        showUploadStatus(`✅ "${rootName}" ready — ${groupFiles.length.toLocaleString()} files (computing size…)`, 'success');
        // Non-blocking background size scan
        _scanSizeChunked(group, groupFiles);
        _spawnFolderWorkersIfNeeded();
    });
}

/**
 * Registers a webkitdirectory FileList lazily.
 * Count is instant (fileList.length). Size computed in background without blocking.
 */
function _registerFolderGroup(fileArray, mobilePrefix) {
    if (!fileArray || fileArray.length === 0) return;

    const rootName = mobilePrefix
        || (fileArray[0].webkitRelativePath || '').split('/')[0]
        || 'Upload';

    for (const g of folderGroups.values()) {
        if (g.rootName === rootName) {
            showUploadStatus(`📁 "${rootName}" is already in the queue`, 'info');
            return;
        }
    }

    const groupId = `fg_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const group = {
        id: groupId,
        rootName,
        basePath: currentPath || '',  // frozen at queue time — never changes when user browses
        pendingFiles: fileArray, // Stable Array snapshot — never invalidated by input reset
        mobilePrefix,
        totalCount: fileArray.length,
        scanned: fileArray.length,
        completed: 0, errors: 0,
        totalSize: 0,    // Filled progressively by _scanSizeChunked in background
        status: 'pending',
        scanComplete: true,  // webkitdirectory already enumerated everything before change fired
        cancelled: false,
        createdTime: Date.now()
    };
    folderGroups.set(groupId, group);
    updateQueueDisplay();
    showUploadStatus(`✅ "${rootName}" queued — ${fileArray.length.toLocaleString()} files (computing size…)`, 'success');
    _scanSizeChunked(group, fileArray); // Non-blocking background size scan
    _spawnFolderWorkersIfNeeded();
}

async function _scanSizeChunked(group, source, chunkSize = 1000) {
    const total = source.length;
    let i = 0;
    while (i < total && !group.cancelled) {
        const effectiveChunk = document.hidden ? 5000 : chunkSize;
        const end = Math.min(i + effectiveChunk, total);
        for (; i < end; i++) {
            group.totalSize += (source[i].size || 0);
        }
        updateQueueDisplay(); // Paint size update after each chunk
        await new Promise(r => setTimeout(r, 0)); // Yield to browser
    }
    updateQueueDisplay(); // Final update
}

async function _uploadFolderGroupLazy(group, startFrom = 0) {
    if (group._running) {
        console.warn(`⚠️ Group "${group.rootName}" loop already running — skipping duplicate start`);
        return;
    }
    group._running = true;
    group.status = 'uploading';
    _updateGroupRowInPlace(group);

    const total = group.totalCount || group.scanned;
    const usePendingFiles = !!group.pendingFiles;
    const source = usePendingFiles ? group.pendingFiles : (group.pendingEntries || []);

    console.log(`📁 Starting folder upload: "${group.rootName}" — ${total.toLocaleString()} files`);

    function _resolveItem(i) {
        if (!usePendingFiles) {
            const entry = source[i];
            if (!entry) return null;
            // pendingEntries have dest baked in at scan time using the original rootName.
            // If a rename override was applied after scanning, rewrite dest now.
            if (group.rootNameOverride && group._origRootName) {
                const origName = group._origRootName;
                const oldPrefix = group.basePath ? `${group.basePath}/${origName}` : origName;
                const newPrefix = group.basePath ? `${group.basePath}/${group.rootNameOverride}` : group.rootNameOverride;
                let newDest = entry.dest;
                if (newDest === oldPrefix) {
                    newDest = newPrefix;
                } else if (newDest.startsWith(oldPrefix + '/')) {
                    newDest = newPrefix + newDest.slice(oldPrefix.length);
                }
                const newDisplay = entry.displayName.startsWith(origName)
                    ? group.rootNameOverride + entry.displayName.slice(origName.length)
                    : entry.displayName;
                return { ...entry, dest: newDest, displayName: newDisplay };
            }
            return entry;
        }
        const file = source[i];
        if (!file) return null; // freed slot
        const fp = group.mobilePrefix
            ? `${group.mobilePrefix}/${file.name}`
            : (file.webkitRelativePath || file.relativePath || '').replace(/^\//, '');
        const parts = fp.split('/'); parts.pop();
        let relDir = parts.join('/');
        if (group.rootNameOverride && relDir) {
            const relParts = relDir.split('/');
            relParts[0] = group.rootNameOverride;
            relDir = relParts.join('/');
        } else if (group.rootNameOverride && !relDir) {
            relDir = group.rootNameOverride;
        }
        const base = group.basePath || '';
        const dest = base ? (relDir ? `${base}/${relDir}` : base) : relDir;
        const displayName = relDir ? `${relDir}/${file.name}` : file.name;
        return { file, dest, displayName };
    }

    const uiEvery = 1;
    // Log progress every 1000 files
    const logEvery = 1000;

    try {
        for (let i = startFrom; ; i++) {
            if (group.cancelled || !isUploading) break;

            while (i >= source.length) {
                if (group.scanComplete || group.cancelled || !isUploading) break;
                await new Promise(r => setTimeout(r, 50)); // yield ~50 ms then re-check
            }
            if (i >= source.length) break; // scanner finished and all entries consumed

            group._currentIndex = i;

            const _resolved = _resolveItem(i);
            if (!_resolved) continue; // freed slot from previous run
            const { file, dest, displayName } = _resolved;

            const ac = new AbortController();
            if (!group._activeControllers) group._activeControllers = new Set();
            group._activeControllers.add(ac);

            const queueItem = {
                id: generateFileId(file), file,
                name: file.name, displayName,
                destinationPath: dest,
                size: file.size, status: 'pending',
                progress: 0, error: null, uploadedBytes: 0,
                createdTime: Date.now(),
                _groupId: group.id,
                _abortSignal: ac.signal
            };

            uploadQueue.push(queueItem);
            updateItemStatus(queueItem.id, 'uploading');

            try {
                await uploadSingleFile(queueItem);
                if (!group.cancelled) {
                    updateItemStatus(queueItem.id, 'completed');
                    lazyBytesUploaded += file.size;
                    _recordSpeedSample(totalBytesUploaded);
                    _lastUploadActivity = Date.now();
                }
            } catch (err) {
                const userCancelled = group.cancelled
                    || err.message === 'Upload cancelled by user';
                const unexpectedAbort = !userCancelled && err.name === 'AbortError';

                const isNetworkError = unexpectedAbort || (!userCancelled && (
                    err.message.includes('Failed to fetch') ||
                    err.message.includes('NetworkError') ||
                    err.message.includes('net::ERR_') ||
                    err.name === 'TypeError'
                ));

                if (userCancelled) {
                    group.cancelled = true;
                    updateItemStatus(queueItem.id, 'cancelled', 'Stopped');
                } else if (isNetworkError && isUploading) {
                    updateItemStatus(queueItem.id, 'pending', 'Waiting to retry…');
                    if (document.hidden) {
                        await new Promise(resolve => {
                            const handler = () => { document.removeEventListener('visibilitychange', handler); resolve(); };
                            document.addEventListener('visibilitychange', handler);
                        });
                    }
                    await new Promise(r => setTimeout(r, 1500));
                    const retryIdx = uploadQueue.findIndex(q => q.id === queueItem.id);
                    if (retryIdx !== -1) uploadQueue.splice(retryIdx, 1);
                    i--;
                    continue;
                } else {
                    updateItemStatus(queueItem.id, 'error', err.message);
                }
            } finally {
                if (group._activeControllers) group._activeControllers.delete(ac);
            }

            const idx = uploadQueue.findIndex(q => q.id === queueItem.id);
            if (idx !== -1) uploadQueue.splice(idx, 1);

            if (usePendingFiles && source[i]) {
                source[i] = null;
            }

            const done = group.completed + group.errors;

            // Folder-level progress log every 1000 files
            if (done > 0 && done % logEvery === 0) {
                const pct = Math.round((done / total) * 100);
                console.log(`📁 "${group.rootName}": ${done.toLocaleString()} / ${total.toLocaleString()} files (${pct}%) — ${group.errors} errors`);
            }

            if (done % uiEvery === 0 || done === total) {
                _updateGroupRowInPlace(group);
                updateOverallProgress();
            }
        }
    } finally {
        group._running = false;
        group._currentIndex = null;
    }

    const finalStatus = group.cancelled ? 'cancelled' : (group.errors > 0 ? 'done with errors' : 'done');
    console.log(`📁 "${group.rootName}" finished: ${group.completed.toLocaleString()} uploaded, ${group.errors} errors — ${finalStatus}`);

    group.status = group.cancelled ? 'error' : (group.errors > 0 ? 'error' : 'done');
    if (group._activeControllers) group._activeControllers.clear();
    group._activeControllers = null;
    group.pendingFiles = null;
    group.pendingEntries = null;
    _updateGroupRowInPlace(group);
    updateOverallProgress();

    // Each folder removes itself 2s after finishing — independent of other folders.
    if (group.status === 'done') {
        _freeSeen(group); // Release dedup keys immediately so the same folder can be re-queued after deletion
        setTimeout(() => {
            if (folderGroups.has(group.id)) {
                folderGroups.delete(group.id);
                updateQueueDisplay();
            }
        }, 2000);
    }
}

function _freeSeen(group) {
    if (group._ownedKeys) {
        group._ownedKeys.forEach(key => _seenFileKeys.delete(key));
        group._ownedKeys.clear();
    }
}

/** Remove a pending folder group from queue */
function _cancelFolderGroup(groupId) {
    const group = folderGroups.get(groupId);
    if (!group) return;
    group.cancelled = true;
    _freeSeen(group);
    uploadQueue = uploadQueue.filter(item => item._groupId !== groupId);
    folderGroups.delete(groupId);
    updateQueueDisplay();
    showUploadStatus('🗑️ Folder removed from queue', 'info');
}

/** Stop an in-progress folder upload — aborts current fetch + sets cancelled flag */
function _stopFolderGroup(groupId) {
    const group = folderGroups.get(groupId);
    if (!group) return;

    group.cancelled = true;

    if (group._activeControllers && group._activeControllers.size > 0) {
        group._activeControllers.forEach(ac => { try { ac.abort(); } catch (e) { } });
        group._activeControllers.clear();
    }
    // Legacy fallback for any older reference
    if (group._activeController) {
        try { group._activeController.abort(); } catch (e) { }
        group._activeController = null;
    }

    // Mark any items in the queue so chunked loops exit at next check
    uploadQueue.filter(item => item._groupId === groupId).forEach(item => {
        cancelledUploads.add(item.id);
        item.status = 'cancelled';
    });

    group.pendingFiles = null;
    group.pendingEntries = null;
    showUploadStatus(`⛔ Stopping "${group.rootName}" — ${group.completed} files uploaded`, 'info');
    _updateGroupRowInPlace(group);
}


function addToUploadQueue(itemData) {
    // Add a single item to the upload queue (for assembly recovery)
    const queueItem = {
        id: itemData.id,
        file: null, // No file object for recovered items
        name: itemData.name,
        displayName: itemData.name,
        destinationPath: '',
        size: itemData.size || 0,
        status: itemData.status || 'pending',
        progress: itemData.progress || 0,
        error: itemData.error || null,
        uploadedBytes: itemData.size || 0,
        createdTime: Date.now(),
        message: itemData.message || null
    };

    uploadQueue.push(queueItem);
    updateQueueDisplay();
    console.log('📝 Added recovered item to queue:', itemData.name);
}

let _fileIdCounter = 0;

function generateFileId(file) {
    return `fid_${++_fileIdCounter}_${file.size}`;
}

function removeFromQueue(fileId) {
    const index = uploadQueue.findIndex(item => item.id === fileId);
    if (index > -1) {
        const item = uploadQueue[index];
        if (item.status === 'uploading') {
            showUploadStatus('❌ Cannot remove file currently being uploaded', 'error');
            return;
        }

        uploadQueue.splice(index, 1);

        // Try to cleanup chunks for this item
        if (item.status === 'pending' || item.status === 'error' || item.status === 'cancelled') {
            cleanupSingleFile(fileId).catch(console.error);
        }

        updateQueueDisplay();
        showUploadStatus(`🗑️ Removed "${item.name}" from queue`, 'success');
    }
}

async function cancelUpload(fileId) {
    console.log(`🚫 Cancelling upload for file: ${fileId}`);

    // Immediately mark as cancelled to stop ongoing processes
    cancelledUploads.add(fileId);

    const index = uploadQueue.findIndex(item => item.id === fileId);
    if (index === -1) {
        console.error(`❌ File ${fileId} not found in queue`);
        return;
    }

    const item = uploadQueue[index];
    if (item.status !== 'uploading') {
        console.error(`❌ File ${fileId} is not currently uploading (status: ${item.status})`);
        return;
    }

    try {
        showUploadStatus(`🚫 Cancelling upload of "${item.name}"...`, 'info');

        // Mark as cancelled immediately
        item.status = 'cancelled';
        item.error = 'Upload cancelled by user';
        updateQueueDisplay();

        // Call the cancel endpoint to clean up server-side chunks
        const response = await fetch('/cancel_upload', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                file_id: fileId,
                filename: item.name
            })
        });

        const result = await response.json();

        if (result.success) {
            console.log(`✅ Successfully cancelled upload: ${result.message}`);
            showUploadStatus(`🚫 Cancelled: ${item.name}`, 'warning');

            // Update global state
            if (currentUploadingFile === fileId) {
                currentUploadingFile = null;
                isUploading = false;
            }

            // Refresh file table after cancel
            setTimeout(() => {
                refreshFileTable();
            }, 500);

            // Continue with next file if we were batch uploading
            if (uploadQueue.some(item => item.status === 'pending') && !isUploading) {
                setTimeout(() => {
                    startBatchUpload();
                }, 500);
            }
        } else {
            console.error(`❌ Failed to cancel upload: ${result.error}`);
            showUploadStatus(`❌ Failed to cancel upload: ${result.error}`, 'error');

            // Revert status for retry
            item.status = 'error';
            item.error = 'Cancel failed: ' + result.error;
            cancelledUploads.delete(fileId); // Remove from cancelled set
            updateQueueDisplay();
        }

    } catch (error) {
        console.error('❌ Cancel upload error:', error);
        showUploadStatus(`❌ Cancel upload error: ${error.message}`, 'error');

        // Revert status for retry
        item.status = 'error';
        item.error = 'Cancel error: ' + error.message;
        cancelledUploads.delete(fileId); // Remove from cancelled set
        updateQueueDisplay();
    }
}

function clearAllQueue() {
    if (isUploading) {
        showUploadStatus('❌ Cannot clear queue while uploading', 'error');
        return;
    }
    const itemsToCleanup = uploadQueue.filter(item => item.status === 'pending' || item.status === 'error');
    uploadQueue = [];
    folderGroups.clear();
    _seenFileKeys.clear();
    updateQueueDisplay();
    if (itemsToCleanup.length > 0) cleanupUnfinishedChunks(itemsToCleanup).catch(console.error);
    showUploadStatus('🧹 Upload queue cleared', 'success');
}

function clearCompletedItems() {
    const before = uploadQueue.length;
    // Release dedup keys of completed/error items so they can be re-queued
    uploadQueue.forEach(item => {
        if (item.status !== 'pending' && item.status !== 'uploading' && item.status !== 'assembling') {
            if (item._seenKey) _seenFileKeys.delete(item._seenKey);
        }
    });
    uploadQueue = uploadQueue.filter(item =>
        item.status === 'pending' || item.status === 'uploading' || item.status === 'assembling'
    );
    const filesCleared = before - uploadQueue.length;

    let groupsCleared = 0;
    folderGroups.forEach((group, id) => {
        if (group.status === 'done' || group.status === 'error' || group.status === 'cancelled' || group.cancelled) {
            _freeSeen(group); // Release dedup keys so same folder can be re-queued
            folderGroups.delete(id);
            groupsCleared++;
        }
    });

    const total = filesCleared + groupsCleared;
    if (total === 0) { showUploadStatus('ℹ️ No completed items to clear', 'info'); return; }
    updateQueueDisplay();
    showUploadStatus(`🧹 Cleared ${total} item${total > 1 ? 's' : ''}`, 'success');
}

// Enhanced cleanup function with retry logic
async function cleanupUnfinishedChunks(specificItems = null) {
    const itemsToClean = specificItems || uploadQueue.filter(item =>
        item.status === 'pending' || item.status === 'error'
    );

    if (itemsToClean.length === 0) return;

    console.log(`🧹 Cleaning up ${itemsToClean.length} unfinished uploads...`);

    const cleanupPromises = itemsToClean.map(item => cleanupSingleFile(item.id, item.name));

    try {
        await Promise.allSettled(cleanupPromises);
        console.log('✅ Bulk cleanup completed');
    } catch (error) {
        console.error('❌ Error in bulk cleanup:', error);
    }
}

async function cleanupSingleFile(fileId, fileName = 'unknown') {
    const maxRetries = 3;
    let retries = 0;

    while (retries < maxRetries) {
        try {
            const response = await fetch('/cleanup_chunks', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ file_id: fileId })
            });

            if (response.ok) {
                console.log(`🧹 Cleaned up chunks for: ${fileName} (${fileId})`);
                return;
            } else {
                const errorData = await response.json();
                throw new Error(`HTTP ${response.status}: ${errorData.error || 'Unknown error'}`);
            }
        } catch (error) {
            retries++;
            console.warn(`🔄 Cleanup retry ${retries}/${maxRetries} for ${fileId}:`, error.message);

            if (retries < maxRetries) {
                // Wait before retrying (exponential backoff)
                await new Promise(resolve => setTimeout(resolve, Math.pow(2, retries) * 1000));
            } else {
                console.error(`❌ Failed to cleanup chunks for ${fileId} after ${maxRetries} attempts:`, error.message);
                throw error;
            }
        }
    }
}

function updateQueueDisplay() {
    const queueContainer = document.getElementById('uploadQueue');
    const queueElement = document.getElementById('fileQueue');
    const statsElement = document.getElementById('queueStats');
    const uploadBtn = document.getElementById('startUploadBtn');
    const countElement = document.getElementById('uploadCount');
    const progressSummary = document.getElementById('uploadProgressSummary');

    if (!queueContainer) return;

    const hasItems = uploadQueue.length > 0 || folderGroups.size > 0;
    if (!hasItems) {
        queueContainer.classList.remove('show');
        if (uploadBtn) uploadBtn.disabled = true;
        return; // progress bar driven by setUploadingState() only
    }

    queueContainer.classList.add('show');

    const totalSize = uploadQueue.reduce((sum, item) => sum + (item.size || 0), 0);
    const pendingCount = uploadQueue.filter(item => item.status === 'pending').length;
    const scanning = [...folderGroups.values()].some(g => g.status === 'scanning');

    // Count files + size from ALL lazy folder groups (not yet in uploadQueue)
    let lazyFileCount = 0, lazySize = 0, hasPendingLazyGroups = false;
    folderGroups.forEach(g => {
        if (!g.cancelled) {
            lazyFileCount += (g.totalCount || g.scanned || 0);
            lazySize += (g.totalSize || 0);
            if (g.status === 'pending' && (g.pendingFiles || g.pendingEntries)) {
                hasPendingLazyGroups = true;
            }
        }
    });
    const totalFileCount = uploadQueue.length + lazyFileCount;
    const grandTotalSize = totalSize + lazySize;
    const sizeStr = scanning ? 'scanning…' : formatFileSize(grandTotalSize);

    let statsText = `(${totalFileCount.toLocaleString()} files, ${sizeStr})`;
    if (folderGroups.size > 0)
        statsText = `(${totalFileCount.toLocaleString()} files from ${folderGroups.size} folder${folderGroups.size > 1 ? 's' : ''}, ${sizeStr})`;
    if (scanning) statsText += ' — scanning…';

    if (statsElement) statsElement.textContent = statsText;
    if (countElement) countElement.textContent = pendingCount + lazyFileCount;
    if (uploadBtn) uploadBtn.disabled = (pendingCount === 0 && !hasPendingLazyGroups && !scanning) || isUploading;

    // Progress bar driven by setUploadingState() — not here

    if (queueElement) {
        queueElement.innerHTML = '';
        // One row per folder group
        folderGroups.forEach(group => queueElement.appendChild(_createFolderGroupRow(group)));
        // Individual rows only for non-folder files
        uploadQueue.filter(item => !item._groupId).forEach(item => queueElement.appendChild(createQueueItemElement(item)));
    }
}

function _folderRowContent(group) {
    const total = group.totalCount || group.scanned;
    const pct = total > 0 ? Math.round((group.completed / total) * 100) : 0;
    const sizeStr = group.status === 'scanning'
        ? 'computing…'
        : (group.totalSize > 0 ? formatFileSize(group.totalSize) : '0 bytes');
    const icons = {
        scanning: 'fas fa-circle-notch fa-spin', pending: 'fas fa-clock',
        uploading: 'fas fa-spinner fa-spin', done: 'fas fa-check-circle',
        error: 'fas fa-exclamation-circle'
    };
    const labels = {
        scanning: `Scanning… ${group.scanned.toLocaleString()} files`,
        pending: `Queued — ${total.toLocaleString()} files`,
        uploading: `${group.completed.toLocaleString()} / ${total.toLocaleString()} (${pct}%)`,
        done: `Done — ${total.toLocaleString()} files`,
        error: `${group.errors} failed of ${total.toLocaleString()}`
    };
    const sc = group.status === 'done' ? 'completed' : group.status;
    return { total, pct, sizeStr, icons, labels, sc };
}

function _createFolderGroupRow(group) {
    const { total, pct, sizeStr, icons, labels, sc } = _folderRowContent(group);
    const div = document.createElement('div');
    div.className = `queue-item ${sc}`;
    div.dataset.groupId = group.id;
    div.innerHTML = `
        <div class="file-info">
            <i class="fas fa-folder" style="color:#f39c12;font-size:20px;margin-right:8px;flex-shrink:0;"></i>
            <div class="file-info-details">
                <div class="file-info-name" title="${escapeHtml(group.rootName)}">📁 ${escapeHtml(group.rootName)}</div>
                <div class="file-info-meta">
                    <span class="fg-count"><i class="fas fa-file"></i> ${total.toLocaleString()} files</span>
                    <span class="fg-size"><i class="fas fa-weight-hanging"></i> ${sizeStr}</span>
                </div>
            </div>
        </div>
        <div class="file-status">
            ${group.status === 'uploading'
            ? `<div class="progress-bar-small"><div class="progress-fill-small fg-bar" style="width:${pct}%"></div></div>`
            : ''}
            ${group.status === 'scanning'
            ? `<div class="progress-bar-small"><div class="progress-fill-small" style="width:100%;background:#f39c12;animation:pulse 1s infinite;"></div></div>`
            : ''}
            <span class="status-text status-${sc} fg-status">
                <i class="${icons[group.status] || 'fas fa-folder'}"></i> ${labels[group.status] || group.status}
            </span>
            ${(group.status === 'pending' || group.status === 'scanning') ? `
                <button class="remove-btn" onclick="_cancelFolderGroup('${group.id}')" title="Remove folder">
                    <i class="fas fa-times"></i>
                </button>` : ''}
            ${group.status === 'uploading' ? `
                <button class="remove-btn cancel-btn fg-stop-btn" data-gid="${group.id}" title="Stop upload">
                    <i class="fas fa-ban"></i>
                </button>` : ''}
        </div>`;
    return div;
}

/** Update an existing folder row in-place — never replaces the element, so the Stop button stays clickable */
function _updateGroupRowInPlace(group) {
    const el = document.querySelector(`[data-group-id="${group.id}"]`);
    if (!el) { updateQueueDisplay(); return; }

    const { total, pct, sizeStr, icons, labels, sc } = _folderRowContent(group);
    el.className = `queue-item ${sc}`;

    const cntEl = el.querySelector('.fg-count');
    if (cntEl) cntEl.innerHTML = `<i class="fas fa-file"></i> ${total.toLocaleString()} files`;

    const szEl = el.querySelector('.fg-size');
    if (szEl) szEl.innerHTML = `<i class="fas fa-weight-hanging"></i> ${sizeStr}`;

    const stEl = el.querySelector('.fg-status');
    if (stEl) {
        stEl.className = `status-text status-${sc} fg-status`;
        stEl.innerHTML = `<i class="${icons[group.status] || 'fas fa-folder'}"></i> ${labels[group.status] || group.status}`;
    }

    const barEl = el.querySelector('.fg-bar');
    if (barEl) barEl.style.width = pct + '%';

    // Add progress bar when transitioning to uploading
    if (group.status === 'uploading' && !barEl) {
        const fs = el.querySelector('.file-status');
        if (fs) {
            const wrap = document.createElement('div');
            wrap.className = 'progress-bar-small';
            const fill = document.createElement('div');
            fill.className = 'progress-fill-small fg-bar';
            fill.style.width = pct + '%';
            wrap.appendChild(fill);
            fs.insertBefore(wrap, fs.firstChild);
        }
    }

    const existingStopBtn = el.querySelector('.fg-stop-btn');
    const existingRemoveBtn = el.querySelector('.remove-btn:not(.fg-stop-btn)');

    const needsStopBtn = group.status === 'uploading';
    const needsRemoveBtn = group.status === 'pending' || group.status === 'scanning';

    if (needsStopBtn && !existingStopBtn) {
        // Transition into uploading — create stop button once
        existingRemoveBtn && existingRemoveBtn.remove();
        const _fs = el.querySelector('.file-status');
        if (_fs) {
            const btn = document.createElement('button');
            btn.className = 'remove-btn cancel-btn fg-stop-btn';
            btn.dataset.gid = group.id;
            btn.title = 'Stop upload';
            btn.innerHTML = '<i class="fas fa-ban"></i>';
            _fs.appendChild(btn);
        }
    } else if (!needsStopBtn && existingStopBtn) {
        // Transition out of uploading — remove stop button
        existingStopBtn.remove();
    }

    if (needsRemoveBtn && !existingRemoveBtn) {
        // Transition into pending/scanning — create remove button once
        const _fs = el.querySelector('.file-status');
        if (_fs) {
            const btn = document.createElement('button');
            btn.className = 'remove-btn';
            btn.title = 'Remove folder';
            btn.onclick = () => _cancelFolderGroup(group.id);
            btn.innerHTML = '<i class="fas fa-times"></i>';
            _fs.appendChild(btn);
        }
    } else if (!needsRemoveBtn && existingRemoveBtn) {
        existingRemoveBtn.remove();
    }
}


function createQueueItemElement(item) {
    const div = document.createElement('div');
    div.className = `queue-item ${item.status}`;
    div.dataset.fileId = item.id;

    const statusIcons = {
        pending: 'fas fa-clock',
        uploading: 'fas fa-spinner fa-spin',
        assembling: 'fas fa-cog fa-spin',
        completed: 'fas fa-check-circle',
        error: 'fas fa-exclamation-circle',
        cancelled: 'fas fa-ban'
    };

    const statusLabels = {
        pending: 'Queued',
        uploading: 'Uploading',
        assembling: 'Processing',
        completed: 'Completed',
        error: 'Failed',
        cancelled: 'Cancelled'
    };

    const statusIcon = statusIcons[item.status] || 'fas fa-question-circle';
    const statusLabel = statusLabels[item.status] || item.status.charAt(0).toUpperCase() + item.status.slice(1);

    // Calculate age for display
    const ageInSeconds = Math.floor((Date.now() - (item.createdTime || Date.now())) / 1000);
    const ageDisplay = ageInSeconds < 60 ? `${ageInSeconds}s` :
        ageInSeconds < 3600 ? `${Math.floor(ageInSeconds / 60)}m` :
            `${Math.floor(ageInSeconds / 3600)}h`;

    div.innerHTML = `
                <div class="file-info">
                    <i class="${getFileIcon(item.name)}" style="color: ${getFileColor(item.name)};"></i>
                    <div class="file-info-details">
                        <div class="file-info-name" title="${item.displayName || item.name}">
                            ${escapeHtml(item.displayName || item.name)}
                        </div>
                        <div class="file-info-meta">
                            <span><i class="fas fa-weight-hanging"></i> ${formatFileSize(item.size)}</span>
                            <span><i class="fas fa-clock"></i> ${ageDisplay}</span>
                            ${item.destinationPath && item.destinationPath !== currentPath ?
            `<span><i class="fas fa-folder"></i> ${item.destinationPath}</span>` : ''
        }
                            ${item.status === 'uploading' ? `<span><i class="fas fa-percentage"></i> ${item.progress}%</span>` : ''}
                            ${item.status === 'assembling' ? `<span><i class="fas fa-cog"></i> Processing</span>` : ''}
                            ${item.error ? `<span><i class="fas fa-exclamation"></i> ${item.error}</span>` : ''}
                        </div>
                    </div>
                </div>
                <div class="file-status">
                    ${item.status === 'uploading' || item.status === 'assembling' ? `
                        <div class="progress-bar-small">
                            <div class="progress-fill-small" style="width: ${item.progress}%"></div>
                        </div>
                    ` : ''}
                    <span class="status-text status-${item.status}">
                        <i class="${statusIcon}"></i> ${statusLabel}
                    </span>
                    ${item.status === 'pending' || item.status === 'error' || item.status === 'cancelled' ? `
                        <button class="remove-btn" onclick="removeFromQueue('${item.id}')" title="Remove from queue">
                            <i class="fas fa-times"></i>
                        </button>
                    ` : ''}
                    ${item.status === 'uploading' ? `
                        <button class="remove-btn cancel-btn" onclick="cancelUpload('${item.id}')" title="Cancel upload">
                            <i class="fas fa-ban"></i>
                        </button>
                    ` : ''}
                </div>
            `;

    return div;
}

function updateProgressSummary() {
    const totalSizeElement = document.getElementById('totalSize');
    const uploadedSizeElement = document.getElementById('uploadedSize');
    const uploadSpeedElement = document.getElementById('uploadSpeed');
    const etaElement = document.getElementById('eta');
    const overallPercentageElement = document.getElementById('overallPercentage');
    const overallProgressFill = document.getElementById('overallProgressFill');

    if (isUploading) {
        const live = uploadQueue.reduce((s, i) => s + (i.size || 0), 0)
            + [...folderGroups.values()]
                .filter(g => g.status === 'scanning' || g.status === 'pending' || g.status === 'uploading')
                .reduce((s, g) => s + (g.totalSize || 0), 0);
        if (live > totalBytesToUpload) totalBytesToUpload = live;
    }
    if (totalBytesToUpload === 0) return;

    const uploadSpeed = _rollingSpeed();
    const remainingBytes = Math.max(0, totalBytesToUpload - totalBytesUploaded);
    const eta = uploadSpeed > 0 ? remainingBytes / uploadSpeed : 0;
    const overallProgress = Math.min(100, (totalBytesUploaded / totalBytesToUpload) * 100);

    if (totalSizeElement) totalSizeElement.textContent = formatFileSize(totalBytesToUpload);
    if (uploadedSizeElement) uploadedSizeElement.textContent = formatFileSize(totalBytesUploaded);
    if (uploadSpeedElement) uploadSpeedElement.textContent = uploadSpeed > 0 ? formatFileSize(uploadSpeed) + '/s' : '...';
    if (etaElement) etaElement.textContent = formatTime(eta);
    if (overallPercentageElement) overallPercentageElement.textContent = Math.round(overallProgress) + '%';
    if (overallProgressFill) overallProgressFill.style.width = overallProgress + '%';
}

function formatTime(seconds) {
    if (!seconds || seconds === Infinity) return '--:--';

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    } else {
        return `${minutes}:${secs.toString().padStart(2, '0')}`;
    }
}

function getFileIcon(filename) {
    const ext = String(filename).split('.').pop().toLowerCase();
    return EXTENSION_MAP[ext]?.icon || 'fas fa-file';
}

function getFileColor(filename) {
    const ext = String(filename).split('.').pop().toLowerCase();
    return EXTENSION_MAP[ext]?.color || '#ffffff';
}

// Centralized extension -> {type, icon, color} mapping (partial but extensive)
const EXTENSION_MAP = (function () {
    // Helper to build entries quickly
    const e = (exts, type, icon, color) => exts.forEach(x => map[x] = { type, icon, color });
    const map = Object.create(null);

    // Documents
    e(['txt', 'rtf', 'doc', 'docx', 'odt', 'pdf', 'tex', 'log', 'csv', 'tsv', 'md', 'xml', 'json', 'ini', 'cfg', 'yaml', 'yml', 'nfo', 'readme', 'wps', 'dot', 'dotx'], 'Document', 'fas fa-file-alt', '#34495e');

    // Data
    e(['xls', 'xlsx', 'ods', 'db', 'mdb', 'accdb', 'sqlite', 'sqlite3', 'sql', 'sav', 'dat', 'dbf', 'parquet', 'arff', 'rdata', 'dta', 'pivot'], 'Data', 'fas fa-file-excel', '#27ae60');

    // Presentations
    e(['ppt', 'pptx', 'odp', 'key', 'pub', 'msg', 'eml', 'oft', 'note'], 'Presentation', 'fas fa-file-powerpoint', '#e67e22');

    // Images
    e(['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tif', 'tiff', 'ico', 'svg', 'webp', 'heic', 'heif', 'psd', 'psb', 'ai', 'eps', 'ind', 'indd', 'idml', 'xcf', 'cpt', 'exr', 'hdr', 'raw', 'nef', 'cr2', 'arw', 'dng', 'sketch', 'fig', 'xd'], 'Image', 'fas fa-file-image', '#9b59b6');

    // Video
    e(['mp4', 'avi', 'mov', 'wmv', 'mkv', 'flv', 'webm', 'mpeg', 'mpg', 'm4v', '3gp', 'mxf', 'f4v', 'vob', 'swf', 'blend', 'aep', 'prproj', 'drp', 'veg'], 'Video', 'fas fa-file-video', '#e74c3c');

    // Audio
    e(['mp3', 'wav', 'ogg', 'flac', 'wma', 'aac', 'm4a', 'mid', 'midi', 'aiff', 'aif', 'oma', 'pcm', 'stem'], 'Audio', 'fas fa-file-audio', '#f39c12');

    // 3D / CAD
    e(['dwg', 'dxf', 'dwf', 'dwt', 'dgn', 'rvt', 'rfa', 'rte', 'ifc', 'step', 'stp', 'stl', 'iges', 'igs', 'sldprt', 'sldasm', 'ipt', 'iam', 'f3d', 'fbx', 'obj', '3ds', 'max', 'skp', 'plt', 'cam', 'cnc', 'nc', 'scad'], '3D / CAD', 'fas fa-cube', '#16a085');

    // Code
    e(['py', 'ipynb', 'js', 'jsx', 'ts', 'tsx', 'html', 'htm', 'css', 'java', 'class', 'jar', 'c', 'cpp', 'h', 'hpp', 'cs', 'vb', 'php', 'asp', 'aspx', 'jsp', 'go', 'rb', 'pl', 'sh', 'bat', 'cmd', 'ps1', 'lua', 'sql', 'yaml', 'yml', 'toml', 'r', 'm', 'scala', 'kt', 'swift', 'rs', 'jsonl', 'env', 'config', 'jsonc'], 'Code', 'fas fa-code', '#2ecc71');

    // Archives
    e(['zip', 'rar', '7z', 'tar', 'gz', 'gzip', 'bz2', 'tgz', 'iso', 'img', 'cab', 'arj', 'lzh', 'pkg'], 'Archive', 'fas fa-file-archive', '#95a5a6');

    // Binaries
    e(['exe', 'msi', 'bat', 'cmd', 'ps1', 'vbs', 'dll', 'sys', 'drv', 'ocx', 'reg', 'inf', 'scr', 'com', 'cpl'], 'Binaries', 'fas fa-cogs', '#7f8c8d');

    // Web
    e(['map', 'sitemap', 'url', 'lnk', 'cache', 'cookie'], 'Web', 'fas fa-globe', '#3498db');

    // Security / Certs
    e(['cer', 'crt', 'pem', 'pfx', 'p12', 'key', 'csr', 'enc', 'sig', 'asc'], 'Cert/Key', 'fas fa-shield-alt', '#c0392b');

    // Project / Config
    e(['project', 'workspace', 'sln', 'solution', 'config', 'settings', 'prefs', 'manifest', 'lock', 'jsonc'], 'Config', 'fas fa-folder-tree', '#34495e');

    // Backups / Logs / Misc
    e(['tmp', 'bak', 'old', 'log', 'err', 'torrent', 'dmp', 'cache', 'backup', 'copy'], 'Misc Files', 'fas fa-file', '#95a5a6');

    // Specialized enterprise
    e(['pst', 'ost', 'ics', 'vcf', 'contact', 'form', 'template', 'report', 'policy', 'license', 'audit', 'script', 'blueprint', 'model', 'sim'], 'Specialized', 'fas fa-file-alt', '#9b59b6');

    // Default PDF mapping (also included above) ensure 'pdf' explicit
    map['pdf'] = { type: 'Document', icon: 'fas fa-file-pdf', color: '#e74c3c' };

    return map;
})();

// ── File Viewer ───────────────────────────────────────────────────────────────
// Extensions that can be previewed inline in the browser.
const VIEWABLE_EXTENSIONS = {
    image: new Set(['jpg', 'jpeg', 'jfif', 'png', 'gif', 'webp', 'svg', 'avif', 'tif', 'tiff', 'bmp', 'dib', 'psd', 'psb', 'heic', 'heif', 'raw', 'cr2', 'cr3', 'nef', 'nrw', 'arw', 'srf', 'sr2', 'dng', 'orf', 'rw2', 'raf', '3fr', 'mef', 'mos', 'erf', 'kdc', 'dcr', 'mrw', 'x3f', 'exr', 'hdr', 'rgbe', 'tga', 'pcx', 'icb', 'vda', 'vst', 'wmf', 'emf', 'jxl', 'jp2', 'jpx', 'j2k', 'jpf', 'ico']),
    // All video formats supported by ffmpeg HLS transcoding
    video: new Set([
        'mp4', 'webm', 'ogv', 'mov', 'm4v',
        'mkv', 'avi', 'wmv', 'flv', 'mpg', 'mpeg',
        'm2ts', 'mts', 'ts', '3gp',
    ]),
    audio: new Set(['mp3', 'wav', 'ogg', 'oga', 'aac', 'flac', 'm4a', 'opus']),
    pdf: new Set(['pdf']), // PDFs + Office docs (viewed via embedded Google Docs Viewer)
    text: new Set([
        'txt', 'md', 'json', 'jsonc', 'jsonl', 'xml', 'tsv', 'log', 'ini', 'cfg',
        'yaml', 'yml', 'toml', 'env', 'sh', 'bash', 'bat', 'cmd', 'ps1', 'reg', 'md', 'ahk',
        'py', 'js', 'jsx', 'ts', 'tsx', 'html', 'htm', 'css', 'java', 'c', 'cpp', 'h', 'hpp',
        'cs', 'go', 'rb', 'pl', 'lua', 'rs', 'kt', 'swift', 'php', 'sql', 'r', 'scala', 'crt', 'key',
        'vb', 'asm', 's', 'makefile', 'dockerfile', 'gitignore', 'editorconfig', 'htaccess'
    ]),
    office: new Set(['docx', 'doc', 'xlsx', 'xls', 'csv', 'pptx', 'ppt']),
    archive: new Set(['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'tgz', 'tbz2', 'txz']),
};

/**
 * Returns the viewer category for a filename, or null if not viewable.
 * @param {string} filename
 * @returns {'image'|'video'|'audio'|'pdf'|'text'|null}
 */
function getViewerType(filename) {
    if (!filename) return null;
    const ext = String(filename).split('.').pop().toLowerCase();
    for (const [category, exts] of Object.entries(VIEWABLE_EXTENSIONS)) {
        if (exts.has(ext)) return category;
    }
    return null;
}

/** Open the file viewer modal for a given server-relative path. */
function openFileViewer(itemPath, filename) {
    const viewType = getViewerType(filename);
    if (!viewType) return;

    const modal = document.getElementById('fileViewerModal');
    const body = document.getElementById('fileViewerBody');
    const titleEl = document.getElementById('viewerFileName');
    const dlLink = document.getElementById('viewerDownloadLink');

    const viewUrl = `/view/${itemPath}`;
    const dlUrl = `/download/${itemPath}`;

    titleEl.textContent = filename;
    dlLink.href = dlUrl;

    // Clear previous content
    body.innerHTML = '';
    body.className = 'modal-body file-viewer-body';

    let inner = '';
    switch (viewType) {
        case 'image':
            body.classList.add('viewer-image');
            // Non-native or large images are converted on the backend.
            // Show a spinner immediately and swap to the real image once
            // the backend signals ready via /image_preview_status/.
            // Native small images resolve instantly (backend serves them
            // directly) so the spinner is barely visible in those cases.
            body.innerHTML = `
                <div class="img-conv-wrap" id="img-conv-wrap">
                    <div class="img-conv-spinner" id="img-conv-spinner">
                        <div class="img-conv-ring"></div>
                        <div class="img-conv-label" id="img-conv-label">Loading image…</div>
                    </div>
                    <img id="img-conv-result" class="viewer-img"
                         alt="${escapeHtml(filename)}"
                         style="display:none;"
                         onerror="document.getElementById('img-conv-label') && (document.getElementById('img-conv-label').textContent='');
                                  this.style.display='none';
                                  document.getElementById('img-conv-spinner').innerHTML='<p class=viewer-error>Could not load image.</p>';">
                </div>`;
            _imgStartPreview(itemPath, filename);
            break;
        case 'video': {
            body.classList.add('viewer-video');
            const hlsWrapperId = 'hls-wrap-' + Date.now();
            body.innerHTML = `
              <div class="hls-player-outer" id="${hlsWrapperId}" style="display:flex;flex-direction:column;width:100%;height:100%;min-height:420px;">
                <div class="hls-btn-row" id="hls-btn-row">
                  <button class="hls-btn hls-btn-raw" id="hls-btn-raw" title="Play without transcoding">
                    <i class="fas fa-play"></i> Play Raw
                  </button>
                  <button class="hls-btn hls-btn-stream" id="hls-btn-stream" disabled title="Adaptive bitrate stream">
                    <span class="hls-spinner" id="hls-btn-spinner"></span>
                    <span id="hls-btn-label">Preparing stream…</span>
                  </button>
                </div>
                <div class="hls-quality-row" id="hls-quality-row" style="display:none;"></div>
                <div class="hls-progress-wrap" id="hls-progress-wrap" style="display:none">
                  <div class="hls-progress-bar" id="hls-progress-bar" style="width:0%"></div>
                </div>
                <div class="hls-status-msg" id="hls-status-msg"></div>
                <div class="hls-player-area" id="hls-player-area" style="flex:1 1 auto;width:100%;min-height:300px;position:relative;"></div>
              </div>`;
            _hlsStartStream(itemPath, hlsWrapperId);
            break;
        }
        case 'audio':
            body.classList.add('viewer-audio');
            inner = `<div class="viewer-audio-wrap">
                        <i class="fas fa-music viewer-audio-icon"></i>
                        <div class="viewer-audio-name">${escapeHtml(filename)}</div>
                        <audio controls autoplay class="viewer-audio-el">
                            <source src="${viewUrl}">
                            Your browser does not support HTML5 audio.
                        </audio>
                     </div>`;
            break;
        case 'pdf': {
            body.classList.add('viewer-pdf');
            body.innerHTML = `
                <div class="viewer-pdfjs-wrap">
                    <div class="viewer-pdfjs-controls">
                        <span id="pdf-page-info">Loading…</span>
                        <div class="viewer-pdfjs-zoom">
                            <button class="viewer-pdfjs-btn" onclick="pdfZoomOut()" title="Zoom out"><i class="fas fa-search-minus"></i></button>
                            <span id="pdf-zoom-level">100%</span>
                            <button class="viewer-pdfjs-btn" onclick="pdfZoomIn()" title="Zoom in"><i class="fas fa-search-plus"></i></button>
                            <button class="viewer-pdfjs-btn" onclick="pdfZoomReset()" title="Fit width"><i class="fas fa-expand-arrows-alt"></i></button>
                        </div>
                    </div>
                    <div id="pdf-pages" class="viewer-pdfjs-pages">
                        <div id="pdf-loading" class="viewer-pdfjs-loading"><i class="fas fa-circle-notch fa-spin"></i> Loading PDF…</div>
                    </div>
                </div>`;
            _loadPdfJs(() => _renderPdfJs(viewUrl));
            _pdfAttachPinchZoom(body);
            inner = '';
            break;
        }
        case 'text':
            body.classList.add('viewer-text');
            inner = `<div class="viewer-text-loading"><i class="fas fa-circle-notch fa-spin"></i> Loading…</div>`;
            // Fetch text asynchronously after rendering the modal
            fetch(viewUrl)
                .then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.text();
                })
                .then(txt => {
                    body.innerHTML = `<pre class="viewer-pre"><code>${escapeHtml(txt)}</code></pre>`;
                })
                .catch(err => {
                    body.innerHTML = `<p class="viewer-error"><i class="fas fa-exclamation-triangle"></i> Could not load file: ${escapeHtml(err.message)}</p>`;
                });
            break;
        case 'office':
            body.classList.add('viewer-office');
            inner = `<div class="viewer-office-loading"><i class="fas fa-circle-notch fa-spin"></i> Generating preview…</div>`;
            fetch(`/office_preview/${itemPath}`)
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        body.innerHTML = `<p class="viewer-error"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(data.error)}</p>`;
                        return;
                    }
                    _renderOfficePreview(body, data);
                })
                .catch(err => {
                    body.innerHTML = `<p class="viewer-error"><i class="fas fa-exclamation-triangle"></i> Could not load preview: ${escapeHtml(err.message)}</p>`;
                });
            break;
        case 'archive':
            body.classList.add('viewer-archive');
            inner = `<div class="viewer-archive-loading"><i class="fas fa-circle-notch fa-spin"></i> Reading archive…</div>`;
            _loadArchivePreview(body, itemPath, null);
            break;
    }

    // video, pdf, and image cases set body.innerHTML themselves — skip the overwrite
    if (viewType !== 'video' && viewType !== 'pdf' && viewType !== 'image') body.innerHTML = inner;
    modal.classList.add('show');
}

/**
 * Image preview loader — mirrors the HLS spinner pattern.
 *
 * Flow:
 *  1. Fetch /image_info/<path> to find out if backend processing is needed.
 *  2a. If not needed (small native image) → set img.src directly, hide spinner.
 *  2b. If needed and already cached → set img.src to /image_preview/, hide spinner.
 *  2c. If needed and not yet cached  → show "Converting…" spinner, fire
 *      /image_preview/ request (triggers backend conversion), then poll
 *      /image_preview_status/<key> every 1 s until ready, then reveal image.
 */
async function _imgStartPreview(itemPath, filename) {
    const _NATIVE_IMG = new Set(['jpg', 'jpeg', 'jfif', 'png', 'gif', 'webp', 'svg', 'avif', 'ico']);
    const ext = filename.split('.').pop().toLowerCase();
    const isNative = _NATIVE_IMG.has(ext);
    const previewUrl = `/image_preview/${itemPath}`;
    const viewUrl = `/view/${itemPath}`;

    const wrap = document.getElementById('img-conv-wrap');
    const spinner = document.getElementById('img-conv-spinner');
    const label = document.getElementById('img-conv-label');
    const img = document.getElementById('img-conv-result');

    // Guard: modal may have been closed before async resumes
    function _alive() { return document.getElementById('img-conv-wrap') === wrap; }

    function _showImage(url) {
        if (!_alive()) return;
        img.onload = () => {
            if (!_alive()) return;
            spinner.style.display = 'none';
            img.style.display = 'block';
        };
        img.src = url;
    }

    function _setLabel(text) {
        if (label && _alive()) label.textContent = text;
    }

    // ── Small native image: load directly, no backend processing needed ───
    if (isNative) {
        _setLabel('Loading image…');
        _showImage(viewUrl);
        return;
    }

    // ── Non-native / potentially large: ask backend for info first ────────
    let info;
    try {
        _setLabel('Checking image…');
        const r = await fetch(`/image_info/${itemPath}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        info = await r.json();
    } catch (e) {
        _showImage(previewUrl);
        return;
    }

    if (!_alive()) return;

    // Already cached or no processing needed → serve immediately
    if (!info.needs_processing || info.cached) {
        _setLabel(info.needs_processing ? 'Loading converted image…' : 'Loading image…');
        _showImage(previewUrl);
        return;
    }

    // ── Needs conversion — show spinner and poll ───────────────────────────
    if (!info.pyvips_available) {
        if (!info.libvips_enabled && info.is_non_native) {
            // libvips is intentionally disabled — show same "requires processing"
            // placeholder as HLS uses for non-native video with ffmpeg disabled.
            if (spinner && _alive()) {
                spinner.style.display = 'none';
            }
            const wrap2 = document.getElementById('img-conv-wrap');
            if (wrap2 && _alive()) {
                wrap2.innerHTML = `
                  <div style="text-align:center;color:rgba(255,255,255,0.6);padding:40px 32px;">
                    <div style="font-size:36px;margin-bottom:14px;">🖼️</div>
                    <div style="font-size:14px;font-weight:600;margin-bottom:8px;color:rgba(255,255,255,0.85);">Image Requires Processing</div>
                    <div style="font-size:12px;opacity:0.65;line-height:1.6;">
                      This format (${info.ext ? info.ext.toUpperCase() : 'image'}) cannot be displayed without libvips conversion.<br>
                      libvips is currently disabled in server settings.<br>
                      Download the file to view it in a local image viewer.
                    </div>
                  </div>`;
            }
        } else {
            _setLabel('⚠️ pyvips not installed — trying raw…');
            _showImage(viewUrl);
        }
        return;
    }

    _setLabel('Converting image…');

    // Kick off backend conversion by touching /image_preview/ once.
    // Don't await — we discover completion via polling below.
    fetch(previewUrl).catch(() => { });

    // Poll /image_preview_status/<cache_key> every 1 s
    const cacheKey = info.cache_key;
    let elapsed = 0;
    const poll = setInterval(async () => {
        if (!_alive()) { clearInterval(poll); return; }

        elapsed += 1;
        const mins = Math.floor(elapsed / 60);
        const secs = elapsed % 60;
        const timeStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
        _setLabel(`Converting image… ${timeStr}`);

        let st;
        try {
            const r = await fetch(`/image_preview_status/${cacheKey}`);
            st = await r.json();
        } catch { return; }

        if (!_alive()) { clearInterval(poll); return; }

        if (st.status === 'ready') {
            clearInterval(poll);
            const fmt = st.out_fmt === 'jpeg' ? 'JPEG' : st.out_fmt === 'png' ? 'PNG' : 'WebP';
            const sizeMB = st.cached_size ? (st.cached_size / 1048576).toFixed(1) + ' MB' : '';
            const extra = st.oversized ? ` (oversized → ${fmt})` : ` (${fmt})`;
            _setLabel(`Done${extra}${sizeMB ? ' · ' + sizeMB : ''}`);
            _showImage(previewUrl);
        } else if (st.status === 'error') {
            clearInterval(poll);
            _setLabel('');
            if (spinner && _alive()) {
                spinner.innerHTML = `<p class="viewer-error">Conversion failed: ${st.message || 'unknown error'}</p>`;
            }
        }
    }, 1000);
}

/** Close the file viewer and stop any media playback. */
function closeFileViewer() {
    const modal = document.getElementById('fileViewerModal');
    const body = document.getElementById('fileViewerBody');
    if (!modal) return;
    modal.classList.remove('show');

    window._hlsPollCancel = true;
    window._vjsCurrentPlayer = null;

    // 1. Stop every media element first — pause + blank src + load resets decoder
    body.querySelectorAll('video, audio').forEach(m => {
        try { m.pause(); } catch (_) { }
        try { m.removeAttribute('src'); } catch (_) { }
        try { while (m.firstChild) m.removeChild(m.firstChild); } catch (_) { }
        try { m.load(); } catch (_) { }
    });

    // 2. Call the Lit web component's own destroy() — this is what actually
    //    releases the internal MediaSource / HLS stream held by the component.
    //    The props dump showed: destroy, destroyCallback on the element prototype.
    body.querySelectorAll('video-player, video-skin').forEach(el => {
        try { if (typeof el.destroy === 'function') el.destroy(); } catch (_) { }
        try { if (typeof el.destroyCallback === 'function') el.destroyCallback(); } catch (_) { }
    });

    // 3. Physically remove video elements from DOM before clearing innerHTML —
    //    this forces the browser to release the MediaSource reference immediately
    body.querySelectorAll('video, audio').forEach(m => {
        try { m.parentNode && m.parentNode.removeChild(m); } catch (_) { }
    });

    // 4. Clear the body
    body.innerHTML = '';

    // 5. Reset PDF.js state so reopening a PDF starts fresh
    _pdfState.doc = null;
    _pdfState.scale = 1;
    _pdfState.baseScale = 1;
    _pdfState.rendering = false;
}

// ── PDF.js helpers ────────────────────────────────────────────────────────────

const _pdfState = { doc: null, scale: 1, baseScale: 1, rendering: false };

function _loadPdfJs(cb) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/js/pdf.worker.min.js';
    cb();
}

function _renderPdfJs(url) {
    _pdfState.doc = null;
    _pdfState.scale = 1;
    _pdfState.baseScale = 1;
    _pdfState.rendering = false;

    pdfjsLib.getDocument(url).promise
        .then(doc => {
            _pdfState.doc = doc;
            const loadingEl = document.getElementById('pdf-loading');
            if (loadingEl) loadingEl.style.display = 'none';
            const info = document.getElementById('pdf-page-info');
            if (info) info.textContent = `${doc.numPages} page${doc.numPages !== 1 ? 's' : ''}`;

            doc.getPage(1).then(page => {
                const pagesEl = document.getElementById('pdf-pages');
                const availW = pagesEl ? pagesEl.clientWidth - 24 : window.innerWidth - 24;
                _pdfState.baseScale = availW / page.getViewport({ scale: 1 }).width;
                _pdfState.scale = _pdfState.baseScale;
                _pdfZoomLabel();
                _renderAllPages();
            });
        })
        .catch(err => {
            const loadingEl = document.getElementById('pdf-loading');
            if (loadingEl) loadingEl.innerHTML =
                `<i class="fas fa-exclamation-triangle"></i> Could not load PDF: ${err.message}`;
        });
}

function _renderAllPages(restoreScrollRatio) {
    if (!_pdfState.doc) return;
    const pagesEl = document.getElementById('pdf-pages');
    if (!pagesEl) return;

    const scrollRatio = restoreScrollRatio !== undefined
        ? restoreScrollRatio
        : (pagesEl.scrollHeight > 0 ? pagesEl.scrollTop / pagesEl.scrollHeight : 0);

    const total = _pdfState.doc.numPages;
    const existing = [...pagesEl.querySelectorAll('.viewer-pdfjs-page')];

    for (let i = existing.length + 1; i <= total; i++) {
        const wrap = document.createElement('div');
        wrap.className = 'viewer-pdfjs-page';
        wrap.dataset.page = i;

        const canvas = document.createElement('canvas');
        canvas.className = 'viewer-pdfjs-canvas';

        const textLayer = document.createElement('div');
        textLayer.className = 'viewer-pdfjs-text textLayer';

        wrap.appendChild(canvas);
        wrap.appendChild(textLayer);
        pagesEl.appendChild(wrap);
        existing.push(wrap);
    }

    const renders = existing.slice(0, total).map((wrap, idx) => {
        const canvas = wrap.querySelector('.viewer-pdfjs-canvas');
        const textLayer = wrap.querySelector('.viewer-pdfjs-text');
        return _renderSinglePage(idx + 1, canvas, textLayer);
    });

    Promise.all(renders).then(() => {
        pagesEl.scrollTop = pagesEl.scrollHeight * scrollRatio;
    });
}

function _renderSinglePage(pageNum, canvas, textLayer) {
    const gen = (canvas._pdfGen = (canvas._pdfGen || 0) + 1);

    return _pdfState.doc.getPage(pageNum).then(page => {
        const dpr = window.devicePixelRatio || 1;
        const viewport = page.getViewport({ scale: _pdfState.scale });
        const viewportHiDp = page.getViewport({ scale: _pdfState.scale * dpr });

        const offscreen = document.createElement('canvas');
        offscreen.width = viewportHiDp.width;
        offscreen.height = viewportHiDp.height;

        return page.render({ canvasContext: offscreen.getContext('2d'), viewport: viewportHiDp }).promise.then(() => {
            if (canvas._pdfGen !== gen) return;

            canvas.width = viewportHiDp.width;
            canvas.height = viewportHiDp.height;
            canvas.style.width = viewport.width + 'px';
            canvas.style.height = viewport.height + 'px';
            canvas.getContext('2d').drawImage(offscreen, 0, 0);

            const wrap = canvas.parentElement;
            if (wrap) {
                wrap.style.width = viewport.width + 'px';
                wrap.style.height = viewport.height + 'px';
            }

            if (textLayer) {
                textLayer.innerHTML = '';
                textLayer.style.width = viewport.width + 'px';
                textLayer.style.height = viewport.height + 'px';
                // --scale-factor must be the logical scale (not DPR-multiplied)
                textLayer.style.setProperty('--scale-factor', String(_pdfState.scale));
                page.getTextContent().then(textContent => {
                    if (canvas._pdfGen !== gen) return;
                    // v3.11.174 correct API: textContentSource + container
                    pdfjsLib.renderTextLayer({
                        textContentSource: textContent,
                        container: textLayer,
                        viewport: viewport,
                        textDivs: [],
                    });
                });
            }

            const pagesEl = document.getElementById('pdf-pages');
            if (pagesEl) {
                pagesEl.style.alignItems = viewport.width <= pagesEl.clientWidth
                    ? 'center'
                    : 'flex-start';
            }
        });
    });
}
function _pdfZoomLabel() {
    const el = document.getElementById('pdf-zoom-level');
    if (el) el.textContent = Math.round((_pdfState.scale / _pdfState.baseScale) * 100) + '%';
}

function pdfZoomIn() {
    const pagesEl = document.getElementById('pdf-pages');
    const ratio = pagesEl && pagesEl.scrollHeight > 0 ? pagesEl.scrollTop / pagesEl.scrollHeight : 0;
    _pdfState.scale = Math.min(_pdfState.baseScale * 4, _pdfState.scale * 1.25);
    _pdfZoomLabel();
    _renderAllPages(ratio);
}

function pdfZoomOut() {
    const pagesEl = document.getElementById('pdf-pages');
    const ratio = pagesEl && pagesEl.scrollHeight > 0 ? pagesEl.scrollTop / pagesEl.scrollHeight : 0;
    _pdfState.scale = Math.max(_pdfState.baseScale * 0.5, _pdfState.scale / 1.25);
    _pdfZoomLabel();
    _renderAllPages(ratio);
}

function pdfZoomReset() {
    const pagesEl = document.getElementById('pdf-pages');
    const ratio = pagesEl && pagesEl.scrollHeight > 0 ? pagesEl.scrollTop / pagesEl.scrollHeight : 0;
    _pdfState.scale = _pdfState.baseScale;
    _pdfZoomLabel();
    _renderAllPages(ratio);
}

/**
 * Intercepts native pinch-to-zoom on the PDF pages container.
 * During pinch: re-renders only the visible pages each frame — fast enough
 * to feel real-time. On release: re-renders all pages for full sharpness.
 */
function _pdfAttachPinchZoom(container) {
    let startDist = 0;
    let startScale = 1;
    let pinching = false;
    let rafPending = false;

    function _dist(touches) {
        const dx = touches[0].clientX - touches[1].clientX;
        const dy = touches[0].clientY - touches[1].clientY;
        return Math.hypot(dx, dy);
    }

    function _visibleCanvases() {
        const pagesEl = document.getElementById('pdf-pages');
        if (!pagesEl) return [];
        const top = pagesEl.scrollTop;
        const bottom = top + pagesEl.clientHeight;
        return [...pagesEl.querySelectorAll('.viewer-pdfjs-canvas')].filter(c => {
            const wrap = c.parentElement;
            const offsetTop = wrap ? wrap.offsetTop : c.offsetTop;
            return offsetTop + (wrap ? wrap.offsetHeight : c.offsetHeight) >= top && offsetTop <= bottom;
        });
    }

    function _renderVisible() {
        _visibleCanvases().forEach(canvas => {
            const pageNum = parseInt(canvas.dataset.page, 10) ||
                parseInt(canvas.closest('.viewer-pdfjs-page')?.dataset.page, 10);
            const textLayer = canvas.parentElement?.querySelector('.viewer-pdfjs-text');
            if (pageNum) _renderSinglePage(pageNum, canvas, textLayer);
        });
        _pdfZoomLabel();
    }

    container.addEventListener('touchstart', e => {
        if (e.touches.length === 2) {
            pinching = true;
            startDist = _dist(e.touches);
            startScale = _pdfState.scale;
            e.preventDefault();
        }
    }, { passive: false });

    container.addEventListener('touchmove', e => {
        if (!pinching || e.touches.length !== 2) return;
        e.preventDefault();

        const ratio = _dist(e.touches) / startDist;
        const newScale = Math.max(
            _pdfState.baseScale * 0.5,
            Math.min(_pdfState.baseScale * 4, startScale * ratio)
        );
        _pdfState.scale = newScale;

        // Throttle to one render per animation frame
        if (!rafPending) {
            rafPending = true;
            requestAnimationFrame(() => {
                _renderVisible();
                rafPending = false;
            });
        }
    }, { passive: false });

    container.addEventListener('touchend', e => {
        if (!pinching || e.touches.length >= 2) return;
        pinching = false;

        // Re-render all pages (including off-screen) at the final scale
        const pagesEl = document.getElementById('pdf-pages');
        const scrollRatio = pagesEl && pagesEl.scrollHeight > 0
            ? pagesEl.scrollTop / pagesEl.scrollHeight : 0;
        _renderAllPages(scrollRatio);
    });
}

// ── End PDF.js helpers ────────────────────────────────────────────────────────

function _renderOfficePreview(body, data) {
    body.innerHTML = '';

    // ── DOCX ──────────────────────────────────────────────────────────────────
    if (data.type === 'docx') {
        const wrap = document.createElement('div');
        wrap.className = 'office-docx-body';
        wrap.innerHTML = data.html || '<p style="color:#999">No content found.</p>';
        body.appendChild(wrap);

        // ── XLSX ──────────────────────────────────────────────────────────────────
    } else if (data.type === 'xlsx') {
        const sheets = data.sheets || [];
        if (!sheets.length) {
            body.innerHTML = '<p class="viewer-error">No sheets found.</p>';
            return;
        }

        // Build tab strip
        const tabStrip = document.createElement('div');
        tabStrip.className = 'office-tabs';
        sheets.forEach((s, i) => {
            const btn = document.createElement('button');
            btn.className = 'office-tab' + (i === 0 ? ' active' : '');
            btn.textContent = s.name;
            btn.dataset.idx = i;
            tabStrip.appendChild(btn);
        });

        // Build sheet panels
        const sheetsWrap = document.createElement('div');
        sheetsWrap.className = 'office-sheets';

        sheets.forEach((s, i) => {
            const panel = document.createElement('div');
            panel.className = 'office-sheet-panel' + (i === 0 ? ' active' : '');
            panel.dataset.idx = i;

            const tableWrap = document.createElement('div');
            tableWrap.className = 'office-table-wrap';

            const table = document.createElement('table');
            table.className = 'office-table';

            const rows = s.rows || [];
            if (rows.length) {
                const thead = document.createElement('thead');
                const headerTr = document.createElement('tr');
                (rows[0] || []).forEach(cell => {
                    const th = document.createElement('th');
                    th.innerHTML = cell;
                    headerTr.appendChild(th);
                });
                thead.appendChild(headerTr);
                table.appendChild(thead);

                const tbody = document.createElement('tbody');
                rows.slice(1).forEach(row => {
                    const tr = document.createElement('tr');
                    row.forEach(cell => {
                        const td = document.createElement('td');
                        td.innerHTML = cell;
                        tr.appendChild(td);
                    });
                    tbody.appendChild(tr);
                });
                table.appendChild(tbody);
            }

            tableWrap.appendChild(table);
            panel.appendChild(tableWrap);

            if (s.truncated) {
                const notice = document.createElement('div');
                notice.className = 'office-truncation-notice';
                notice.innerHTML = '<i class="fas fa-info-circle"></i> Preview limited to 500 rows. Download the file to view all data.';
                panel.appendChild(notice);
            }

            sheetsWrap.appendChild(panel);
        });

        // Wire up tab switching
        tabStrip.addEventListener('click', e => {
            const btn = e.target.closest('.office-tab');
            if (!btn) return;
            const idx = btn.dataset.idx;
            tabStrip.querySelectorAll('.office-tab').forEach(b => b.classList.remove('active'));
            sheetsWrap.querySelectorAll('.office-sheet-panel').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            sheetsWrap.querySelector(`.office-sheet-panel[data-idx="${idx}"]`).classList.add('active');
        });

        const viewer = document.createElement('div');
        viewer.className = 'office-xlsx-viewer';
        viewer.appendChild(tabStrip);
        viewer.appendChild(sheetsWrap);
        body.appendChild(viewer);

        // ── PPTX ──────────────────────────────────────────────────────────────────
    } else if (data.type === 'pptx') {
        const slides = data.slides || [];
        if (!slides.length) {
            body.innerHTML = '<p class="viewer-error">No slides found.</p>';
            return;
        }

        let currentSlide = 0;

        function buildSlideHtml(idx) {
            const slide = slides[idx];
            const titleShape = slide.shapes.find(s => s.is_title);
            const bodyShapes = slide.shapes.filter(s => !s.is_title);

            let html = '';

            if (titleShape) {
                const titleText = titleShape.paragraphs.map(p => p.text).join(' ');
                html += `<h2 class="pptx-slide-title">${titleText}</h2>`;
            }

            if (bodyShapes.length) {
                html += '<div class="pptx-body">';
                bodyShapes.forEach(shape => {
                    shape.paragraphs.forEach(p => {
                        const indent = p.level > 0 ? ` style="padding-left:${p.level * 22}px"` : '';
                        const bullet = p.level === 0 ? '• ' : '◦ ';
                        html += `<p class="pptx-para"${indent}>${bullet}${p.text}</p>`;
                    });
                });
                html += '</div>';
            }

            if (!html) {
                html = '<p class="pptx-empty"><i class="fas fa-image"></i><br>No text content on this slide</p>';
            }

            return html;
        }

        function updateSlide() {
            slidePanel.innerHTML = `<div class="pptx-slide">${buildSlideHtml(currentSlide)}</div>`;
            counter.textContent = `${currentSlide + 1} / ${slides.length}`;
            prevBtn.disabled = currentSlide === 0;
            nextBtn.disabled = currentSlide === slides.length - 1;
        }

        const viewer = document.createElement('div');
        viewer.className = 'office-pptx-viewer';

        const slidePanel = document.createElement('div');
        slidePanel.className = 'pptx-slide-panel';

        const controls = document.createElement('div');
        controls.className = 'pptx-controls';

        const prevBtn = document.createElement('button');
        prevBtn.className = 'btn btn-outline btn-sm pptx-prev';
        prevBtn.innerHTML = '<i class="fas fa-chevron-left"></i> Prev';

        const nextBtn = document.createElement('button');
        nextBtn.className = 'btn btn-outline btn-sm pptx-next';
        nextBtn.innerHTML = 'Next <i class="fas fa-chevron-right"></i>';

        const counter = document.createElement('span');
        counter.className = 'pptx-counter';

        prevBtn.addEventListener('click', () => { if (currentSlide > 0) { currentSlide--; updateSlide(); } });
        nextBtn.addEventListener('click', () => { if (currentSlide < slides.length - 1) { currentSlide++; updateSlide(); } });

        // Keyboard navigation (only when viewer is open)
        const _pptxKeyHandler = (e) => {
            const modal = document.getElementById('fileViewerModal');
            if (!modal || !modal.classList.contains('show')) return;
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') nextBtn.click();
            if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') prevBtn.click();
        };
        document.addEventListener('keydown', _pptxKeyHandler);
        // Clean up key handler when modal closes
        const _origClose = window._pptxCloseCleanup;
        window._pptxCloseCleanup = () => {
            document.removeEventListener('keydown', _pptxKeyHandler);
            if (_origClose) _origClose();
        };

        controls.append(prevBtn, counter, nextBtn);
        viewer.append(slidePanel, controls);
        body.appendChild(viewer);
        updateSlide();

    } else {
        body.innerHTML = `<p class="viewer-error">Unknown preview type: ${escapeHtml(data.type)}</p>`;
    }
}

// Close viewer on outside-click
document.addEventListener('click', function (e) {
    const modal = document.getElementById('fileViewerModal');
    if (modal && e.target === modal) closeFileViewer();
});

// Close viewer on Escape key (registers alongside other modal listeners)
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        const modal = document.getElementById('fileViewerModal');
        if (modal && modal.classList.contains('show')) closeFileViewer();
    }
    // Arrow keys: skip ±10s when video viewer is open
    const modal = document.getElementById('fileViewerModal');
    if (modal && modal.classList.contains('show')) {
        if (e.key === 'ArrowRight') { e.preventDefault(); _hlsSkip(10); }
        if (e.key === 'ArrowLeft') { e.preventDefault(); _hlsSkip(-10); }
    }
});

/** Skip the active HLS/raw video by +/- seconds */
function _hlsSkip(seconds) {
    // Try video-player web component first, then plain <video>
    const area = document.getElementById('hls-player-area');
    if (!area) return;
    let vid = area.querySelector('video');
    if (!vid) {
        const vp = area.querySelector('video-player');
        if (vp) vid = vp.querySelector('video') || vp.shadowRoot?.querySelector('video');
    }
    if (vid && isFinite(vid.duration)) {
        vid.currentTime = Math.max(0, Math.min(vid.duration, vid.currentTime + seconds));
    }
}
// ─────────────────────────────────────────────────────────────────────────────


function escapeHtml(unsafe) {
    return String(unsafe).replace(/[&<>"'`]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": "&#39;", "`": "&#96;" }[c];
    });
}

function getFileType(filename) {
    if (!filename) return 'Unknown';
    const name = String(filename);
    // directories are handled separately by callers
    const ext = name.includes('.') ? name.split('.').pop().toLowerCase() : '';
    if (!ext) return 'Unknown';
    return EXTENSION_MAP[ext]?.type || ext.toUpperCase() + ' File';
}

// Transform server-rendered rows (initial page load) to use detailed icons/type text
function transformInitialRows() {
    const tbody = document.querySelector('#filesTable tbody');
    if (!tbody) return;

    const rows = Array.from(tbody.querySelectorAll('tr.file-row'));
    rows.forEach(row => {
        try {
            const nameCell = row.querySelector('td:nth-child(2) .file-name');
            if (!nameCell) return;

            const link = nameCell.querySelector('a.folder-link');
            const isDir = !!link;
            let filename = '';
            if (isDir) {
                filename = link.textContent.trim();
                // ensure link onclick uses safe path
                const dataPath = row.dataset.path || '';
                link.setAttribute('onclick', `navigateToFolder('${escapeHtml(dataPath)}'); return false;`);
            } else {
                // for files, the filename text may follow the icon
                filename = nameCell.textContent.trim();
            }

            // Replace icon and text with mapped icon and escaped name
            const iconEl = nameCell.querySelector('i');
            const iconClass = isDir ? 'fas fa-folder' : getFileIcon(filename);
            if (iconEl) iconEl.className = iconClass + ' file-icon';

            // Replace displayed name safely
            if (isDir) {
                link.textContent = filename; // textContent is safe
            } else {
                // Remove existing text nodes after icon
                const clone = nameCell.cloneNode(true);
                const icons = clone.querySelectorAll('i'); icons.forEach(i => i.remove());
                const rawText = clone.textContent.trim();
                nameCell.innerHTML = `<i class="${iconClass} file-icon file-icon-default" style="color: ${getFileColor(filename)}"></i> ${escapeHtml(rawText)}`;
            }

            // Update type column
            const typeCell = row.querySelector('td:nth-child(4) .file-type') || row.querySelector('td:nth-child(4)');
            if (typeCell) {
                const typeText = isDir ? 'Folder' : getFileType(filename);
                typeCell.innerHTML = `<i class="${isDir ? 'fas fa-folder' : getFileIcon(filename)}"></i> ${escapeHtml(typeText)}`;
            }
        } catch (err) {
            console.warn('transformInitialRows skipped a row due to error', err);
        }
    });
}

// Notification stacking system
let notificationId = 0;
let notificationCount = 0; // Track active notifications
let notificationTimers = new Map(); // Track timers for consistent timing

function showUploadStatus(message, type = 'info') {
    // While uploading, only errors pass through — everything else is silent.
    // This stops per-file toasts from burying the Stop button.
    if (isUploading && type !== 'error') return;

    // Hard cap: never stack more than 3 at once regardless of source.
    if (notificationCount >= 3) return;

    // Create unique notification element
    const notificationId_current = ++notificationId;
    const notification = document.createElement('div');
    notification.className = `upload-status show ${type}`;
    notification.innerHTML = message;
    notification.id = `notification-${notificationId_current}`;
    notification.dataset.type = type; // Store type for batch operations

    // Calculate position immediately based on header and notification count
    const headerElement = document.querySelector('.header');
    const headerHeight = headerElement ? headerElement.offsetHeight : 70;
    const notificationHeight = 60; // Estimated notification height
    const gap = 10;
    const startPosition = headerHeight + 20;
    const topPosition = startPosition + (notificationCount * (notificationHeight + gap));

    // Style for stacking - set position immediately
    notification.style.position = 'fixed';
    notification.style.right = '20px';
    notification.style.top = `${topPosition}px`;
    notification.style.zIndex = '10000';
    notification.style.minWidth = '300px';
    notification.style.maxWidth = '500px';
    notification.style.transform = 'translateX(100%)'; // Start off-screen
    notification.style.transition = 'transform 0.3s ease-out';

    // Increment count and add to page
    notificationCount++;
    document.body.appendChild(notification);

    // Trigger slide-in animation immediately
    requestAnimationFrame(() => {
        notification.style.transform = 'translateX(0)';
    });

    // Consistent timing for all notifications using centralized config
    if (type === 'info' || type === 'success') {
        // Use centralized timer configuration
        const hideDelay = type === 'success' ? NOTIFICATION_TIMERS.SUCCESS : NOTIFICATION_TIMERS.INFO;

        const timerId = setTimeout(() => {
            removeNotification(notificationId_current);
        }, hideDelay);

        // Store timer reference
        notificationTimers.set(notificationId_current, timerId);
    }

    // Add click to dismiss
    notification.addEventListener('click', () => {
        removeNotification(notificationId_current);
    });

    notification.style.cursor = 'pointer';
    notification.title = 'Click to dismiss';
}

// Function to clear all notifications of a specific type
function clearNotificationsByType(type) {
    const notifications = document.querySelectorAll(`[id^="notification-"][data-type="${type}"]`);
    notifications.forEach(notif => {
        const id = notif.id.replace('notification-', '');
        removeNotification(parseInt(id));
    });
}

function removeNotification(notificationId) {
    const notification = document.getElementById(`notification-${notificationId}`);
    if (notification) {
        // Clear any existing timer
        if (notificationTimers.has(notificationId)) {
            clearTimeout(notificationTimers.get(notificationId));
            notificationTimers.delete(notificationId);
        }

        // Slide out animation
        notification.style.transform = 'translateX(100%)';
        notification.style.opacity = '0';

        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
                notificationCount--; // Decrease count
                // Reposition remaining notifications immediately
                repositionNotifications();
            }
        }, 300);
    }
}

function repositionNotifications() {
    const existingNotifications = document.querySelectorAll('[id^="notification-"]');
    const headerElement = document.querySelector('.header');
    const headerHeight = headerElement ? headerElement.offsetHeight : 70;
    const notificationHeight = 60; // Estimated height
    const gap = 10;
    const startPosition = headerHeight + 20;

    // Reset count to match actual notifications
    notificationCount = existingNotifications.length;

    existingNotifications.forEach((notif, index) => {
        const topPosition = startPosition + (index * (notificationHeight + gap));
        notif.style.top = `${topPosition}px`;
        notif.style.transition = 'top 0.3s ease-out'; // Smooth repositioning
    });
}

// Function to clear all notifications
function clearNotificationQueue() {
    const existingNotifications = document.querySelectorAll('[id^="notification-"]');
    existingNotifications.forEach(notif => {
        if (notif.parentNode) {
            notif.parentNode.removeChild(notif);
        }
    });

    // Clear all timers
    notificationTimers.forEach(timerId => clearTimeout(timerId));
    notificationTimers.clear();

    notificationCount = 0; // Reset count
}

// Rolling 5-second speed window — accurate for small and large files.
const _speedSamples = [];
function _recordSpeedSample(bytes) {
    const now = Date.now();
    _speedSamples.push({ t: now, b: bytes });
    const cutoff = now - 5000;
    while (_speedSamples.length > 1 && _speedSamples[0].t < cutoff) _speedSamples.shift();
}
function _rollingSpeed() {
    if (_speedSamples.length < 2) return 0;
    const oldest = _speedSamples[0];
    const newest = _speedSamples[_speedSamples.length - 1];
    const dt = (newest.t - oldest.t) / 1000;
    return dt > 0 ? (newest.b - oldest.b) / dt : 0;
}

function updateItemProgress(fileId, progress, uploadedBytes = 0) {
    const item = uploadQueue.find(item => item.id === fileId);
    if (item) {
        // Delta accumulator — O(1), survives auto-clear removing completed items
        const delta = (uploadedBytes || 0) - (item.uploadedBytes || 0);
        if (delta > 0) {
            totalBytesUploaded += delta;
            _recordSpeedSample(totalBytesUploaded);
        }
        item.progress = progress;
        item.uploadedBytes = uploadedBytes;

        const element = document.querySelector(`[data-file-id="${fileId}"]`);
        if (element) {
            const progressBar = element.querySelector('.progress-fill-small');
            const progressText = element.querySelector('.file-info-meta span:nth-child(3)');
            if (progressBar) progressBar.style.width = progress + '%';
            if (progressText) progressText.innerHTML = `<i class="fas fa-percentage"></i> ${progress}%`;
        }

        updateOverallProgress();
    }
}

function updateOverallProgress() {
    // totalBytesUploaded is a running accumulator — never re-reduce the queue
    updateProgressSummary();
}

function updateItemStatus(fileId, status, error = null) {
    const item = uploadQueue.find(item => item.id === fileId);
    if (!item) { return; }

    const prevStatus = item.status;
    item.status = status;
    item.error = error;
    if (status === 'completed' || status === 'error') item.completedTime = Date.now();

    // Keep folder group progress in sync
    if (item._groupId) {
        const group = folderGroups.get(item._groupId);
        if (group) {
            if (status === 'uploading' && group.status === 'pending') group.status = 'uploading';
            if (status === 'completed' && prevStatus !== 'completed') group.completed++;
            if (status === 'error' && prevStatus !== 'error') group.errors++;
            const groupTotal = group.totalCount || group.scanned;
            if (group.completed + group.errors >= groupTotal && groupTotal > 0)
                group.status = group.errors > 0 ? 'error' : 'done';
        }
        // FIX: Folder group items are transient — pushed, uploaded, then spliced out
        // of uploadQueue in the same loop iteration. They never appear as individual
        // rows in the UI (updateQueueDisplay filters them out via !item._groupId).
        // Calling updateQueueDisplay() here caused a full innerHTML wipe + DOM rebuild
        // on EVERY file — 2 rebuilds × 10 parallel workers = 20 full DOM destructions
        // per batch. Over 16k files this caused Chrome's DOM GC to crash the renderer.
        // The group row is managed by _updateGroupRowInPlace (throttled inside the loop).
        return;
    }

    updateQueueDisplay();
}

// AJAX function to refresh file table without page reload
async function refreshFileTable() {
    const startTime = Date.now();
    console.log('📁 refreshFileTable() started...');

    // Check if search results are currently displayed - don't refresh if they are
    const searchHeader = document.getElementById('searchResultsHeader');
    const searchRows = document.querySelectorAll('.search-result-row');

    if (isSearchResultsDisplayed || searchHeader || searchRows.length > 0) {
        console.log('🔍 Search results currently displayed - skipping refresh to preserve search view');
        return;
    }

    try {
        // Use the current path from navigation state, not the static page load path
        const pathToUse = currentPath || '';
        console.log(`📁 Using current navigation path: "${pathToUse}"`);
        console.log(`📁 Fetching files from: /api/files/${pathToUse}`);
        const response = await fetch(`/api/files/${pathToUse}`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Failed to load files');
        }

        // BUG FIX: Route through updateFileTable (VT.init) instead of updateFileTableContent.
        // updateFileTableContent bypassed VT entirely — raw DOM rows, _allFiles never updated.
        // After any SSE/upload/delete refresh, _allFiles stayed stale (root page-load data),
        // so sort headers re-sorted the wrong folder. VT.init reads global currentSort so sort is preserved.
        updateFileTable(data.files, currentPath || '');

        const endTime = Date.now();
        console.log(`✅ refreshFileTable() completed in ${endTime - startTime}ms`);

        console.log('✅ File table refreshed successfully');

    } catch (error) {
        console.error('❌ Failed to refresh file table:', error);

        // FIX: Never reload the page while an upload is in progress.
        // The old code unconditionally called window.location.reload() on any
        // fetch failure. During a long upload (50k files, 1+ hour) the session
        // can expire, making /api/files/ return a redirect to /login. The reload
        // then lands on /login → grey screen and the entire upload is lost.
        if (isUploading) {
            console.warn('⚠️ refreshFileTable failed during upload — skipping reload to protect active upload');
            return;
        }

        // Also guard against auth redirect specifically (session expired mid-session).
        const errMsg = error.message || '';
        if (errMsg.includes('401') || errMsg.includes('403') || errMsg.includes('302')) {
            console.warn('⚠️ refreshFileTable got auth error — skipping reload');
            return;
        }

        showUploadStatus('❌ Failed to refresh file list, reloading page...', 'error');
        setTimeout(() => {
            window.location.reload();
        }, 1000);
    }
}

// Function to update file table content
function updateFileTableContent(files) {
    const tbody = document.querySelector('.table tbody');
    if (!tbody) {
        console.error('❌ File table tbody not found');
        return;
    }

    // Clear existing content
    tbody.innerHTML = '';

    // Only wipe selection on actual navigation, NOT background SSE refresh
    const _incomingPath = currentPath || '';
    const _isNavigating = (typeof _lastRenderedPath !== 'undefined') && _lastRenderedPath !== _incomingPath;
    if (_isNavigating || typeof _lastRenderedPath === 'undefined') {
        selectedItems.clear();
        const selectAllCheckbox = document.getElementById('selectAll');
        if (selectAllCheckbox) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        }
        const bulkActions = document.getElementById('bulkActions');
        if (bulkActions) bulkActions.classList.remove('show');
    }
    _lastRenderedPath = _incomingPath;

    // Use currentPath from navigation state, not CURRENT_PATH from page load
    const pathToUse = currentPath || '';
    console.log(`📁 updateFileTableContent using path: "${pathToUse}"`);

    // Add "Go Up" row if we're not at root
    if (pathToUse) {
        const parentPath = pathToUse.includes('/')
            ? pathToUse.split('/').slice(0, -1).join('/')
            : '';

        const goUpRow = document.createElement('tr');
        goUpRow.className = 'parent-dir-sticky';
        goUpRow.innerHTML = `
            <td></td>
            <td>
                <div class="file-name">
                    <i class="fas fa-level-up-alt file-icon folder-icon"></i>
                    <a href="#" data-action="navigate" data-path="${parentPath}" class="folder-link">
                        .. (Parent Directory)
                    </a>
                </div>
            </td>
            <td class="size-cell">
                <span style="color: white; font-size: 13px;">--</span>
            </td>
            <td class="type-cell">
                <span style="color: white; font-size: 13px;">Folder</span>
            </td>
            <td class="date-cell">
                <span style="color: white; font-size: 13px;">--</span>
            </td>
            <td></td>
        `;
        tbody.appendChild(goUpRow);
        requestAnimationFrame(() => {
            const thead = document.querySelector('#filesTable thead');
            const wrapper = document.getElementById('tableScrollWrapper');
            if (thead && wrapper) wrapper.style.setProperty('--table-thead-h', thead.offsetHeight + 'px');
        });
    }

    if (files.length === 0) {
        // Show empty state
        const colspan = '6'; // Always 6 columns for consistent layout
        tbody.innerHTML += `
            <tr>
                <td colspan="${colspan}" style="text-align: center; padding: 40px 20px; vertical-align: middle;">
                    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 120px;">
                        <i class="fas fa-folder-open" style="font-size: 36px; color: white; margin-bottom: 15px; opacity: 0.7;"></i>
                        <div style="color: white; font-weight: 500; margin-bottom: 8px; font-size: 18px;">This folder is empty</div>
                        <div style="color: white; font-size: 14px; text-align: center; max-width: 300px;">
                            ${USER_ROLE === 'readwrite' ? 'Upload files or create folders to get started' : 'No files available'}
                        </div>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    // Add files to table
    files.forEach(file => {
        const row = document.createElement('tr');
        row.className = 'file-row';
        row.setAttribute('data-path', pathToUse ? `${pathToUse}/${file.name}` : file.name);

        let iconHtml, sizeHtml, typeHtml, actionsHtml;
        const itemPath = pathToUse ? `${pathToUse}/${file.name}` : file.name;

        if (file.is_dir || file.type === 'dir') {
            // Directory
            iconHtml = `<i class="fas fa-folder file-icon folder-icon"></i>
                <a href="#" data-action="navigate" data-path="${itemPath}">${file.name}</a>`;

            sizeHtml = `<span class="dir-info-cell" data-dir-path="${itemPath}" style="color: white; font-size: 13px;">
                <i class="fas fa-spinner fa-spin" style="opacity: 0.4; font-size: 11px;"></i>
            </span>`;

            typeHtml = '<span class="file-type"><i class="fas fa-folder folder-icon file-icon"></i> Folder</span>';

            actionsHtml = `
                <button type="button" class="btn btn-outline btn-sm" 
                        data-action="download-folder"
                        data-item-path="${itemPath}"
                        data-item-name="${file.name}"
                        data-label="Download ZIP"
                        title="Download folder as ZIP">
                    <i class="fas fa-download"></i>
                </button>
                
                ${USER_ROLE === 'readwrite' ? `
                <button type="button" class="btn btn-warning btn-sm" 
                        data-action="move"
                        data-item-name="${file.name}"
                        data-item-path="${itemPath}"
                        data-label="Move"
                        title="Move">
                    <i class="fas fa-cut"></i>
                </button>
                
                <button type="button" class="btn btn-success btn-sm" 
                        data-action="copy"
                        data-item-name="${file.name}"
                        data-item-path="${itemPath}"
                        data-label="Copy"
                        title="Copy">
                    <i class="fas fa-copy"></i>
                </button>
                
                <button type="button" class="btn btn-primary btn-sm" 
                        data-action="rename"
                        data-item-name="${file.name}"
                        data-item-path="${itemPath}"
                        data-label="Rename"
                        title="Rename">
                    <i class="fas fa-edit"></i>
                </button>
                
                <button type="button" class="btn btn-danger btn-sm" 
                        data-action="delete"
                        data-item-name="${file.name}"
                        data-item-path="${itemPath}"
                        data-label="Delete"
                        title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
                ` : ''}
            `;
        } else {
            // File - USE getFileIcon and getFileColor functions
            const fileIcon = getFileIcon(file.name);
            const fileColor = getFileColor(file.name);
            const fileType = typeof getFileType === 'function' ? getFileType(file.name) : 'File';

            // Only apply color to the icon in the name column, not the text
            iconHtml = `<i class="${fileIcon} file-icon file-icon-default" style="color: ${fileColor};"></i>${file.name}`;
            sizeHtml = `<span style="color: white; font-weight: 500;">${formatFileSize(file.size)}</span>`;

            // Type cell icon should NOT have color applied
            typeHtml = `<span class="file-type"><i class="${fileIcon} file-icon file-icon-default"></i> ${fileType}</span>`;

            actionsHtml = `
                <button type="button" class="btn btn-outline btn-sm" 
                        data-action="download"
                        data-item-path="${itemPath}"
                        data-label="Download"
                        title="Download file">
                    <i class="fas fa-download"></i>
                </button>
                ${USER_ROLE === 'readwrite' ? `
                    <button type="button" class="btn btn-warning btn-sm" 
                            data-action="move"
                            data-item-name="${file.name}"
                            data-item-path="${itemPath}"
                            data-label="Move"
                            title="Move">
                        <i class="fas fa-cut"></i>
                    </button>
                    
                    <button type="button" class="btn btn-success btn-sm" 
                            data-action="copy"
                            data-item-name="${file.name}"
                            data-item-path="${itemPath}"
                            data-label="Copy"
                            title="Copy">
                        <i class="fas fa-copy"></i>
                    </button>
                    
                    <button type="button" class="btn btn-primary btn-sm" 
                            data-action="rename"
                            data-item-name="${file.name}"
                            data-item-path="${itemPath}"
                            data-label="Rename"
                            title="Rename">
                        <i class="fas fa-edit"></i>
                    </button>
                    
                    <button type="button" class="btn btn-danger btn-sm" 
                            data-action="delete"
                            data-item-name="${file.name}"
                            data-item-path="${itemPath}"
                            data-label="Delete"
                            title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                ` : ''}
            `;
        }

        row.innerHTML = `
            <td>
                ${USER_ROLE === 'readwrite' ? `
                    <input type="checkbox" class="file-checkbox item-checkbox" 
                           data-path="${itemPath}" 
                           data-name="${file.name}" 
                           data-is-dir="${file.is_dir || file.type === 'dir' ? 'true' : 'false'}" 
                           onchange="updateSelection()" ${selectedItems.has(itemPath) ? 'checked' : ''}>
                ` : ''}
            </td>
            <td class="name-cell">
                <div class="file-name">
                    ${iconHtml}
                </div>
            </td>
            <td class="size-cell">${sizeHtml}</td>
            <td class="type-cell">${typeHtml}</td>
            <td class="date-cell">
                ${file.modified ?
                `<span style="color: white; font-size: 13px;">${formatTimestamp(file.modified)}</span>` :
                `<span style="color: white; font-size: 13px;">--</span>`
            }
            </td>
            <td class="actions-cell">
                <div class="actions" style="display:flex;flex-wrap:nowrap;gap:3px;align-items:center;">
                    ${actionsHtml}
                </div>
            </td>
        `;

        applyColumnWidths(row);
        tbody.appendChild(row);
    });

    // ===== EVENT DELEGATION - Handle all button clicks =====
    // Remove old listener if exists
    const oldListener = tbody._actionListener;
    if (oldListener) {
        tbody.removeEventListener('click', oldListener);
    }

    // Create new listener
    const actionListener = function (e) {
        // Handle navigation links
        const navLink = e.target.closest('a[data-action="navigate"]');
        if (navLink) {
            e.preventDefault();
            const path = navLink.getAttribute('data-path');
            navigateToFolder(path);
            return;
        }

        // Handle action buttons
        const button = e.target.closest('button[data-action]');
        if (!button) return;

        const action = button.getAttribute('data-action');
        const itemPath = button.getAttribute('data-item-path');
        const itemName = button.getAttribute('data-item-name');

        console.log(`🔘 Action: ${action}, Path: ${itemPath}, Name: ${itemName}`);

        switch (action) {
            case 'download':
                downloadItem(itemPath);
                break;
            case 'download-folder':
                downloadFolderAsZip(itemPath, itemName);
                break;
            case 'move':
                showSingleMoveModal(itemPath, itemName);
                break;
            case 'copy':
                showSingleCopyModal(itemPath, itemName);
                break;
            case 'rename':
                showSingleRenameModal(itemPath, itemName);
                break;
            case 'delete':
                showSingleDeleteModal(itemPath, itemName);
                break;
        }
    };

    // Store reference and add listener
    tbody._actionListener = actionListener;
    tbody.addEventListener('click', actionListener);

    // Update selection state to ensure UI is in sync
    updateSelection();

    // Reinitialize search and sort controls
    reinitializeTableControls(files.length);

    // Lazy-load folder sizes after table is rendered
    loadDirInfoCells();
}

// Handle delete button clicks
function handleDeleteClick(event) {
    console.log('🗑️ handleDeleteClick function called');
    const itemName = this.getAttribute('data-item-name');
    const itemPath = this.getAttribute('data-item-path');
    console.log('Delete button clicked:', itemName, itemPath);
    showDeleteModal(itemName, () => deleteItem(itemPath, itemName));
}

// Helper function to get file extension
function getFileExtension(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    return ext !== filename ? ext : 'file';
}

// Helper function to format file size
function formatFileSize(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    // Ensure we don't exceed the sizes array
    const sizeIndex = Math.min(i, sizes.length - 1);
    const value = bytes / Math.pow(k, sizeIndex);

    // Round to 1 decimal place and ensure it's a valid number
    const formattedValue = Math.round(value * 10) / 10;

    return `${formattedValue} ${sizes[sizeIndex]}`;
}

// Helper function to format timestamp  
function formatTimestamp(timestamp) {
    try {
        const date = new Date(timestamp * 1000);
        const time = date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
        const day = date.toLocaleDateString('en-US');
        return `<span style="color:white;font-size:12px;white-space:nowrap;">${day} ${time}</span>`;
    } catch (e) {
        return '--';
    }
}

// ── Overwrite decision cache ──────────────────────────────────────────────────
// Stores per-folder-upload user decisions so we don't re-prompt for every file.
// 'overwrite' | 'skip' | 'ask' (default)
const _overwriteDecisions = new Map(); // groupId → 'overwrite' | 'skip' | 'ask'

// ── Conflict Dialog Helpers ──────────────────────────────────────────────────

/**
 * Creates a themed conflict-dialog overlay that matches the blue app UI.
 * Returns a Promise that resolves with the chosen action string.
 *
 * @param {object} opts
 *   icon      – FontAwesome class string (e.g. 'fa-file')
 *   title     – Dialog heading
 *   body      – HTML string shown in the body area
 *   buttons   – Array of { id, label, style } objects
 */
function _buildConflictDialog(opts) {
    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.style.cssText = [
            'position:fixed', 'inset:0',
            'background:rgba(0,0,0,0.55)',
            'backdrop-filter:blur(4px)',
            '-webkit-backdrop-filter:blur(4px)',
            'z-index:9999',
            'display:flex', 'align-items:center', 'justify-content:center'
        ].join(';');

        const btnHtml = opts.buttons.map(b =>
            `<button data-action="${b.id}" style="${b.style}">${b.label}</button>`
        ).join('');

        overlay.innerHTML = `
        <div style="
            background:rgba(255,255,255,0.97);
            border-radius:15px;
            width:90%;
            max-width:440px;
            box-shadow:0 25px 50px rgba(0,0,0,0.35);
            overflow:hidden;
            font-family:inherit;
        ">
            <!-- Header matching app nav gradient -->
            <div style="
                background:linear-gradient(135deg,#1e3c72 0%,#2a5298 100%);
                padding:18px 22px;
                display:flex;
                align-items:center;
                gap:12px;
                color:#fff;
            ">
                <i class="fas ${opts.icon}" style="font-size:1.25em;opacity:0.9"></i>
                <span style="font-size:1.05em;font-weight:600;letter-spacing:0.01em">${opts.title}</span>
            </div>
            <!-- Body -->
            <div style="padding:20px 22px;color:#2c3e50;font-size:0.95em;line-height:1.5">
                ${opts.body}
            </div>
            <!-- Buttons -->
            <div style="
                padding:0 22px 20px;
                display:flex;
                flex-direction:column;
                gap:9px;
            ">
                ${btnHtml}
            </div>
        </div>`;

        document.body.appendChild(overlay);

        const SHARED_BTN = [
            'width:100%', 'padding:10px 16px',
            'border:none', 'border-radius:8px',
            'font-size:0.92em', 'font-weight:600',
            'cursor:pointer', 'text-align:left',
            'transition:filter .15s',
            'display:flex', 'align-items:center', 'gap:9px'
        ].join(';');

        overlay.querySelectorAll('[data-action]').forEach(btn => {
            btn.style.cssText += ';' + SHARED_BTN;
            btn.addEventListener('mouseenter', () => btn.style.filter = 'brightness(0.9)');
            btn.addEventListener('mouseleave', () => btn.style.filter = '');
            btn.addEventListener('click', () => { overlay.remove(); resolve(btn.dataset.action); });
        });
    });
}

/**
 * Prompt the user when a file already exists on the server.
 * Returns one of: 'overwrite-all' | 'overwrite-one' | 'skip-all' | 'skip-one'
 */
async function _promptOverwrite(filename) {
    const safeName = filename.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return _buildConflictDialog({
        icon: 'fa-file-alt',
        title: 'File Already Exists',
        body: `<div style="margin-bottom:12px">
                   <span style="background:#ebf5fb;border:1px solid #aed6f1;border-radius:6px;
                         padding:5px 10px;font-family:monospace;word-break:break-all;
                         display:inline-block;max-width:100%;color:#1a5276">
                       ${safeName}
                   </span>
               </div>
               <div style="color:#566573">
                   A file with this name already exists on the server.
                   Choose how to handle this and any further conflicts.
               </div>`,
        buttons: [
            {
                id: 'overwrite-all',
                label: '<i class="fas fa-sync-alt"></i> Overwrite all conflicts',
                style: 'background:linear-gradient(135deg,#3498db,#2980b9);color:#fff'
            },
            {
                id: 'overwrite-one',
                label: '<i class="fas fa-file-upload"></i> Overwrite this file only',
                style: 'background:linear-gradient(135deg,#5dade2,#3498db);color:#fff'
            },
            {
                id: 'rename-all',
                label: '<i class="fas fa-copy"></i> Keep both — auto-rename all conflicts',
                style: 'background:linear-gradient(135deg,#27ae60,#229954);color:#fff'
            },
            {
                id: 'rename-one',
                label: '<i class="fas fa-i-cursor"></i> Keep both — rename this file only',
                style: 'background:linear-gradient(135deg,#2ecc71,#27ae60);color:#fff'
            },
            {
                id: 'skip-all',
                label: '<i class="fas fa-forward"></i> Skip all conflicts',
                style: 'background:linear-gradient(135deg,#f39c12,#e67e22);color:#fff'
            },
            {
                id: 'skip-one',
                label: '<i class="fas fa-step-forward"></i> Skip this file only',
                style: 'background:linear-gradient(135deg,#7f8c8d,#636e72);color:#fff'
            }
        ]
    });
}

/**
 * Prompt the user when a folder being uploaded already exists on the server.
 * Returns one of: 'merge' | 'rename' | 'skip' | 'cancel'
 */
async function _promptFolderConflict(folderName) {
    const safeName = folderName.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return _buildConflictDialog({
        icon: 'fa-folder-open',
        title: 'Folder Already Exists',
        body: `<div style="margin-bottom:12px">
                   <span style="background:#eaf4fb;border:1px solid #aed6f1;border-radius:6px;
                         padding:5px 10px;font-family:monospace;word-break:break-all;
                         display:inline-block;max-width:100%;color:#1a5276">
                       <i class="fas fa-folder" style="color:#f39c12;margin-right:6px"></i>${safeName}
                   </span>
               </div>
               <div style="color:#566573">
                   A folder named <strong style="color:#2c3e50">${safeName}</strong> already exists
                   at this location. What would you like to do?
               </div>`,
        buttons: [
            {
                id: 'merge',
                label: '<i class="fas fa-code-branch"></i> Merge — upload into existing folder',
                style: 'background:linear-gradient(135deg,#3498db,#2980b9);color:#fff'
            },
            {
                id: 'rename',
                label: '<i class="fas fa-copy"></i> Keep both — upload as a new renamed folder',
                style: 'background:linear-gradient(135deg,#27ae60,#229954);color:#fff'
            },
            {
                id: 'skip',
                label: '<i class="fas fa-forward"></i> Skip this folder entirely',
                style: 'background:linear-gradient(135deg,#f39c12,#e67e22);color:#fff'
            },
            {
                id: 'cancel',
                label: '<i class="fas fa-times"></i> Cancel upload',
                style: 'background:linear-gradient(135deg,#e74c3c,#c0392b);color:#fff'
            }
        ]
    });
}

/**
 * Finds the first non-existing name for a file/folder by appending (1), (2), …
 * @param {string} destDir  - destination directory path (empty = root)
 * @param {string} name     - original file or folder name
 * @returns {Promise<string>} - a free name like "photo (2).jpg" or "myfolder (1)"
 */
async function _findFreeName(destDir, name) {
    const dotIdx = name.lastIndexOf('.');
    const ext = dotIdx > 0 ? name.slice(dotIdx) : '';
    const base = dotIdx > 0 ? name.slice(0, dotIdx) : name;
    for (let i = 1; i <= 999; i++) {
        const candidate = `${base} (${i})${ext}`;
        const checkPath = destDir ? `${destDir}/${candidate}` : candidate;
        try {
            const resp = await fetch(`/api/exists?path=${encodeURIComponent(checkPath)}`);
            if (resp.ok) {
                const data = await resp.json();
                if (!data.exists) return candidate;
            } else {
                return candidate; // server error — use this name and let upload handle it
            }
        } catch (e) {
            return candidate; // network error — proceed optimistically
        }
    }
    return `${base} (${Date.now()})${ext}`; // last-resort fallback
}

/**
 * @param {string[]} paths       - source paths being moved/copied
 * @param {string}   destination - destination directory path
 * @param {string}   action      - 'move' or 'copy'
 */
async function _promptMoveOrCopyConflicts(paths, destination, action) {
    // Step 1: ask the server which items already exist at the destination
    let conflicts = [];
    try {
        const resp = await fetch('/api/check_conflicts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paths, destination })
        });
        if (resp.ok) {
            const data = await resp.json();
            conflicts = data.conflicts || [];
        }
    } catch (e) {
        console.warn('⚠️ Conflict check failed, proceeding without it:', e.message);
        return {};  // empty map → backend default behaviour
    }

    if (conflicts.length === 0) return {};  // no conflicts, proceed normally

    // Step 2: build list HTML
    const listHtml = conflicts.map(c =>
        `<li style="padding:3px 0;display:flex;align-items:center;gap:7px">
            <i class="fas ${c.is_dir ? 'fa-folder' : 'fa-file-alt'}"
               style="color:${c.is_dir ? '#f39c12' : '#3498db'};font-size:0.9em;flex-shrink:0"></i>
            <span style="font-family:monospace;word-break:break-all">${c.name.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</span>
         </li>`
    ).join('');

    const destDisplay = destination || 'Root';
    const verbNoun = action === 'move' ? 'Moving' : 'Copying';

    const choice = await _buildConflictDialog({
        icon: action === 'move' ? 'fa-arrows-alt' : 'fa-copy',
        title: `${conflicts.length} Conflict${conflicts.length > 1 ? 's' : ''} at Destination`,
        body: `<div style="margin-bottom:10px;color:#566573">
                   ${verbNoun} to <strong style="color:#2c3e50">${destDisplay.replace(/</g, '&lt;')}</strong> —
                   the following item${conflicts.length > 1 ? 's' : ''} already exist there:
               </div>
               <ul style="margin:0 0 12px 0;padding:0 0 0 4px;list-style:none;
                           max-height:150px;overflow-y:auto;
                           background:#f8fafc;border:1px solid #d5e8f5;border-radius:6px;padding:8px 12px">
                   ${listHtml}
               </ul>
               <div style="color:#7f8c8d;font-size:0.88em">Choose how to handle all conflicts at once.</div>`,
        buttons: [
            {
                id: 'overwrite',
                label: `<i class="fas fa-sync-alt"></i> Overwrite existing items`,
                style: 'background:linear-gradient(135deg,#3498db,#2980b9);color:#fff'
            },
            {
                id: 'rename',
                label: `<i class="fas fa-copy"></i> Keep both — auto-rename conflicting items`,
                style: 'background:linear-gradient(135deg,#27ae60,#229954);color:#fff'
            },
            {
                id: 'skip',
                label: `<i class="fas fa-forward"></i> Skip conflicting items`,
                style: 'background:linear-gradient(135deg,#f39c12,#e67e22);color:#fff'
            },
            {
                id: 'cancel',
                label: `<i class="fas fa-times"></i> Cancel`,
                style: 'background:linear-gradient(135deg,#e74c3c,#c0392b);color:#fff'
            }
        ]
    });

    if (choice === 'cancel') return null;  // signal: abort entirely

    // Build resolution map: { filename -> choice } for every conflict
    const resolutions = {};
    for (const c of conflicts) {
        resolutions[c.name] = choice;  // same resolution for all
    }
    return resolutions;
}

// ── Live folder worker pool ───────────────────────────────────────────────────
let _activeFolderWorkers = 0;
let _activeFileWorkers = 0;

function _spawnFileWorkersIfNeeded() {
    if (!isUploading || !PARALLEL_UPLOAD_CONFIG.enableParallelUploads) return;
    const max = PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads;
    const pending = uploadQueue.filter(q => q.status === 'pending' && !cancelledUploads.has(q.id)).length;
    const toSpawn = Math.min(pending, max - _activeFileWorkers - PARALLEL_UPLOAD_CONFIG.activeUploads.size);
    for (let i = 0; i < toSpawn; i++) {
        _activeFileWorkers++;
        _runFileWorker().finally(() => { _activeFileWorkers--; });
    }
}

async function _runFileWorker() {
    while (isUploading) {
        const item = uploadQueue.find(q => q.status === 'pending' && !cancelledUploads.has(q.id));
        if (!item) break;
        item.status = 'uploading';
        PARALLEL_UPLOAD_CONFIG.activeUploads.add(item.id);
        try {
            updateItemStatus(item.id, 'uploading');
            await uploadSingleFile(item);
            const currentItem = uploadQueue.find(q => q.id === item.id);
            if (!(currentItem && currentItem.status === 'assembling')) {
                updateItemStatus(item.id, 'completed');
            }
            PARALLEL_UPLOAD_CONFIG.activeUploads.delete(item.id);
            PARALLEL_UPLOAD_CONFIG.completedUploads.add(item.id);
            cancelledUploads.delete(item.id);
        } catch (error) {
            console.error(`❌ Upload failed: ${item.name}`, error.message);
            updateItemStatus(item.id, 'error', error.message);
            PARALLEL_UPLOAD_CONFIG.activeUploads.delete(item.id);
            cancelledUploads.delete(item.id);
            showUploadStatus(`❌ Failed: "${item.name}" - ${error.message}`, 'error');
        }
    }
}

function _spawnFolderWorkersIfNeeded() {
    if (!isUploading) return;
    const max = PARALLEL_UPLOAD_CONFIG.enableParallelUploads
        ? PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads : 1;
    // Include 'scanning' groups — upload can begin while the directory tree walk is still running.
    const pending = [...folderGroups.values()].filter(
        g => (g.status === 'pending' || g.status === 'scanning') && !g.cancelled && (g.pendingFiles || g.pendingEntries)
    ).length;
    const toSpawn = Math.min(pending, max - _activeFolderWorkers);
    for (let i = 0; i < toSpawn; i++) {
        _activeFolderWorkers++;
        _runFolderWorker().finally(() => { _activeFolderWorkers--; });
    }
}

async function _runFolderWorker() {
    while (isUploading) {
        // Include 'scanning' groups — workers can start consuming pendingEntries while
        // the directory tree walk is still in progress.
        const group = [...folderGroups.values()].find(
            g => (g.status === 'pending' || g.status === 'scanning') && !g.cancelled && (g.pendingFiles || g.pendingEntries)
        );
        if (!group) break;
        // Claim immediately so no other worker grabs same group
        group.status = 'uploading';
        _overwriteDecisions.set(group.id, 'ask'); // Reset overwrite decision per folder

        try {
            const destPath = group.basePath
                ? `${group.basePath}/${group.rootName}`
                : group.rootName;
            const checkResp = await fetch(`/api/exists?path=${encodeURIComponent(destPath)}`);
            if (checkResp.ok) {
                const checkData = await checkResp.json();
                if (checkData.exists && checkData.is_dir) {
                    _updateGroupRowInPlace(group); // show 'uploading' indicator while dialog shown
                    const choice = await _promptFolderConflict(group.rootName);
                    if (choice === 'cancel') {
                        // Cancel the entire upload session
                        group.cancelled = true;
                        group.status = 'cancelled';
                        group._running = false;
                        _updateGroupRowInPlace(group);
                        showUploadStatus(`⛔ Upload cancelled — "${group.rootName}" already exists`, 'info');
                        setTimeout(() => {
                            if (folderGroups.has(group.id)) {
                                _freeSeen(group);
                                folderGroups.delete(group.id);
                                updateQueueDisplay();
                            }
                        }, 2000);
                        continue;  // move to next group in while loop (will find no pending ones if cancelled)
                    } else if (choice === 'skip') {
                        group.cancelled = true;
                        group.status = 'skipped';
                        group._running = false;
                        _updateGroupRowInPlace(group);
                        showUploadStatus(`⏭️ Skipped "${group.rootName}" — folder already exists`, 'info');
                        // Auto-remove from queue after 2s and free seen-keys so re-drop works
                        setTimeout(() => {
                            if (folderGroups.has(group.id)) {
                                _freeSeen(group);
                                folderGroups.delete(group.id);
                                updateQueueDisplay();
                            }
                        }, 2000);
                        continue;
                    }

                    if (choice === 'rename') {
                        // Find a free folder name, then reroute all files into it
                        const freeFolder = await _findFreeName(group.basePath || '', group.rootName);
                        group._origRootName = group.rootName; // preserve original before mutating
                        group.rootNameOverride = freeFolder;
                        group.rootName = freeFolder; // update display name in queue UI
                        _updateGroupRowInPlace(group);
                        showUploadStatus(`📁 Uploading as "${freeFolder}"…`, 'info');
                    }
                }
            }
        } catch (existErr) {
            // Non-fatal: if the check fails (network issue, old server), proceed normally
            console.warn('⚠️ Folder existence check failed, proceeding:', existErr.message);
        }

        showUploadStatus(`📂 "${group.rootName}" — ${(group.totalCount || group.scanned).toLocaleString()} files…`, 'info');
        await _uploadFolderGroupLazy(group);
        if (group.status === 'uploading') {
            group.status = group.errors > 0 ? 'error' : 'done';
            group._running = false;
            _updateGroupRowInPlace(group);
        }
    }
}

// Wait until workers are idle AND no scanning/pending groups remain
function _waitForFolderWorkers() {
    _spawnFolderWorkersIfNeeded();
    return new Promise(resolve => {
        const check = setInterval(() => {
            if (!isUploading) { clearInterval(check); resolve(); return; }
            // Still active if: workers running OR groups still scanning/pending
            const stillBusy = _activeFolderWorkers > 0
                || [...folderGroups.values()].some(g =>
                    !g.cancelled && (g.status === 'scanning' || g.status === 'pending'));
            if (!stillBusy) { clearInterval(check); resolve(); }
        }, 100);
    });
}
// ─────────────────────────────────────────────────────────────────────────────

// ── Single source of truth for progress bar visibility ───────────────────────
let _progressHideTimer = null;
function setUploadingState(active) {
    isUploading = active;
    if (!active) _lastResumeTime = 0;
    const ps = document.getElementById('uploadProgressSummary');
    if (!ps) return;

    if (active) {
        clearTimeout(_progressHideTimer);
        ps.classList.add('show');
        updateProgressSummary();

        if (!document.getElementById('_stopAllBtn')) {
            const btn = document.createElement('button');
            btn.id = '_stopAllBtn';
            btn.title = 'Stop all uploads';
            btn.innerHTML = '<i class="fas fa-ban"></i> Stop Upload';
            btn.style.cssText = [
                'display:flex', 'align-items:center', 'gap:6px',
                'margin:8px auto 0', 'padding:7px 18px',
                'background:#e74c3c', 'color:#fff', 'border:none',
                'border-radius:6px', 'cursor:pointer', 'font-size:14px',
                'font-weight:600', 'letter-spacing:0.3px',
                'box-shadow:0 2px 6px rgba(0,0,0,0.4)',
                'transition:background 0.15s'
            ].join(';');
            btn.onmouseenter = () => btn.style.background = '#c0392b';
            btn.onmouseleave = () => btn.style.background = '#e74c3c';
            btn.addEventListener('click', () => {
                // Stop every active folder group
                folderGroups.forEach((group, id) => {
                    if (group.status === 'uploading' || group.status === 'pending') {
                        _stopFolderGroup(id);
                    }
                });
                // Also cancel any individual file uploads in progress
                uploadQueue.forEach(item => {
                    if (item.status === 'uploading') cancelUpload(item.id);
                });
            });
            ps.appendChild(btn);
        }
    } else {
        _progressHideTimer = setTimeout(() => {
            if (!isUploading) ps.classList.remove('show');
        }, 2500);
        // Remove the stop button when upload ends
        const btn = document.getElementById('_stopAllBtn');
        if (btn) btn.remove();
    }
}

async function startBatchUpload() {
    console.log('🚀 startBatchUpload called, isUploading:', isUploading);

    if (isUploading) {
        console.log('❌ Already uploading, returning');
        return;
    }

    const pendingFiles = uploadQueue.filter(item => item.status === 'pending');
    // Lazy folder groups: have fileList/pendingFiles/pendingEntries but nothing in uploadQueue yet.
    // Include 'scanning' groups so Upload can start immediately while the tree walk is still running.
    const pendingLazyGroups = [...folderGroups.values()].filter(
        g => (g.status === 'pending' || g.status === 'scanning') && (g.pendingFiles || g.pendingEntries)
    );
    console.log('📋 Pending files:', pendingFiles.length, '| Lazy groups:', pendingLazyGroups.length);

    if (pendingFiles.length === 0 && pendingLazyGroups.length === 0) {
        console.log('❌ No files to upload');
        showUploadStatus('❌ No files to upload', 'error');
        return;
    }

    console.log('✅ Starting upload process...');
    setUploadingState(true);
    _activeFolderWorkers = 0;
    _activeFileWorkers = 0;
    _overwriteDecisions.clear();
    currentUploadIndex = 0;
    uploadStartTime = Date.now();
    _lastUploadActivity = Date.now(); // FIX: seed heartbeat so stall detector doesn't fire immediately

    // Start session keepalive so long uploads don't expire the server session
    _startSessionKeepAlive();

    // FIX: Reset SSE reconnect counters so a prior disconnect doesn't permanently
    // block reconnection during this upload session.
    reconnectAttempts = 0;
    sseFailedPermanently = false;
    // If SSE is dead, revive it now before upload begins
    if (!storageEventSource || storageEventSource.readyState === EventSource.CLOSED) {
        console.log('📡 Reviving SSE connection before upload starts...');
        connectToStorageStream();
    }
    totalBytesToUpload = pendingFiles.reduce((sum, item) => sum + item.size, 0)
        + pendingLazyGroups.reduce((s, g) => s + (g.totalSize || 0), 0);
    totalBytesUploaded = 0;
    _speedSamples.length = 0; // reset rolling speed window
    lazyBytesUploaded = 0;

    // Reset parallel upload tracking
    PARALLEL_UPLOAD_CONFIG.activeUploads.clear();
    PARALLEL_UPLOAD_CONFIG.completedUploads.clear();

    const uploadBtn = document.getElementById('startUploadBtn');
    const clearBtn = document.getElementById('clearAllBtn');

    console.log('🔧 Upload button element:', uploadBtn);

    if (uploadBtn) {
        uploadBtn.disabled = true;
        const mode = PARALLEL_UPLOAD_CONFIG.enableParallelUploads ? 'Parallel' : 'Sequential';
        const concurrent = PARALLEL_UPLOAD_CONFIG.enableParallelUploads ? ` (${PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads} concurrent)` : '';
        uploadBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${mode} Upload${concurrent}...`;
    }
    if (clearBtn) clearBtn.disabled = true;

    // Hide manual cleanup button during upload
    updateManualCleanupButton();

    try {
        const uploadMode = PARALLEL_UPLOAD_CONFIG.enableParallelUploads ? 'parallel' : 'sequential';
        const concurrentInfo = PARALLEL_UPLOAD_CONFIG.enableParallelUploads ? ` (${PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads} concurrent)` : '';
        showUploadStatus(`🚀 Starting ${uploadMode} upload of ${pendingFiles.length} files${concurrentInfo}...`, 'info');

        // 1. Upload regular queued files
        if (pendingFiles.length > 0) {
            if (PARALLEL_UPLOAD_CONFIG.enableParallelUploads) {
                await startParallelUploads(pendingFiles);
            } else {
                await startSequentialUploads(pendingFiles);
            }
        }

        // 2. Upload lazy folder groups — live worker pool.
        //    Workers grab the next 'pending' or 'scanning' group from folderGroups on each iteration,
        //    so folders added DURING upload are picked up without restarting.
        if (pendingLazyGroups.length > 0 || [...folderGroups.values()].some(g => g.status === 'pending' || g.status === 'scanning')) {
            await _waitForFolderWorkers();
        }

        const completedCount = uploadQueue.filter(item => item.status === 'completed').length
            + [...folderGroups.values()].reduce((s, g) => s + g.completed, 0);
        const errorCount = uploadQueue.filter(item => item.status === 'error').length
            + [...folderGroups.values()].reduce((s, g) => s + g.errors, 0);
        const cancelledCount = uploadQueue.filter(item => item.status === 'cancelled').length;

        // Ensure overall progress is set to 100% after all uploads
        totalBytesUploaded = totalBytesToUpload;
        updateProgressSummary();

        if (errorCount === 0 && cancelledCount === 0) {
            showUploadStatus(
                `🎉 All files uploaded successfully! (${completedCount} files)`,
                'success'
            );

            VT.clearDirCache();

            // Refresh file table via AJAX instead of page reload
            setTimeout(() => {
                refreshFileTable();
            }, 1000);
        } else {
            showUploadStatus(
                `📊 Upload completed: ${completedCount} successful, ${errorCount} failed, ${cancelledCount} cancelled`,
                'info'
            );
        }

        // Auto-clear completed/error/cancelled items after upload batch finishes
        // BUT keep assembling items visible so user can see processing status
        console.log('🧹 Auto-clearing finished items in 3 seconds...');
        setTimeout(() => {
            const itemsToRemove = uploadQueue.filter(item =>
                item.status === 'completed' ||
                item.status === 'error' ||
                item.status === 'cancelled'
                // Note: 'assembling' items are NOT auto-cleared so user can see processing status
            );

            itemsToRemove.forEach(item => {
                removeFromQueue(item.id);
            });

            // Clear completed folder groups too
            folderGroups.forEach((group, id) => {
                if (group.status === 'done' || group.status === 'error') folderGroups.delete(id);
            });

            console.log(`🧹 Auto-cleared ${itemsToRemove.length} finished items from queue`);

            updateQueueDisplay(); // Re-render so cleared folder rows actually disappear

            if (uploadQueue.length === 0 && folderGroups.size === 0) {
                showUploadStatus('✨ Upload queue cleared automatically', 'success');
            } else {
                const remainingPending = uploadQueue.filter(item => item.status === 'pending').length;
                console.log(`📋 ${remainingPending} files still pending in queue`);
            }
        }, 3000);

    } catch (error) {
        console.error('❌ Batch upload error:', error);
        showUploadStatus(`❌ Batch upload failed: ${error.message}`, 'error');
    } finally {
        setUploadingState(false);
        PARALLEL_UPLOAD_CONFIG.activeUploads.clear();
        PARALLEL_UPLOAD_CONFIG.completedUploads.clear();

        if (uploadBtn) {
            uploadBtn.disabled = false;
            uploadBtn.innerHTML = '<i class="fas fa-upload"></i> Upload All (<span id="uploadCount">0</span>)';
        }
        if (clearBtn) clearBtn.disabled = false;

        updateManualCleanupButton();
        updateQueueDisplay();
    }
}

function _startSessionKeepAlive() {
    if (_sessionKeepAliveInterval) return;
    _sessionKeepAliveInterval = setInterval(async () => {
        if (!isUploading) {
            clearInterval(_sessionKeepAliveInterval);
            _sessionKeepAliveInterval = null;
            return;
        }
        try {
            await fetch('/admin/upload_status', {
                method: 'GET', cache: 'no-cache',
                headers: { 'Cache-Control': 'no-cache' }
            });

        } catch (e) {
            console.warn('⚠️ Session keepalive failed (non-fatal):', e.message);
        }
    }, 30000); // Every 30s — browsers throttle background tabs; 30s gives safety margin
}

function _resumeStalledUploads() {
    if (!isUploading) return 0;

    const now = Date.now();
    const msSinceLastResume = now - _lastResumeTime;
    if (msSinceLastResume < 20000) {
        console.log(`⏭️ Resume skipped (cooldown ${Math.round(msSinceLastResume / 1000)}s < 20s)`);
        return 0;
    }
    _lastResumeTime = now;

    const stalledMs = now - (_lastUploadActivity || 0);
    let resumed = 0;
    for (const [, group] of folderGroups) {
        if (group.status !== 'uploading' || group.cancelled || !group.pendingFiles) continue;

        if (group._running) {
            if (stalledMs > 10000) {
                console.warn(`🔄 Force-resetting frozen group "${group.rootName}" (_running=true but stalled ${Math.round(stalledMs / 1000)}s)`);
                group._running = false;
            } else {
                continue;
            }
        }

        // Stagger restarts: launch each group 300ms apart to avoid a thundering
        // herd of simultaneous connections that would exhaust Waitress threads.
        const delay = resumed * 300;
        const capturedGroup = group;
        setTimeout(() => {
            // Re-check: the group might have already restarted naturally
            if (capturedGroup._running || capturedGroup.cancelled || !capturedGroup.pendingFiles) return;
            // Find first non-null slot from _currentIndex (null = already uploaded)
            let resumeFrom = capturedGroup._currentIndex ?? capturedGroup.completed;
            const src = capturedGroup.pendingFiles;
            if (src) {
                while (resumeFrom < src.length && src[resumeFrom] === null) resumeFrom++;
            }
            console.warn(`🔄 Resuming "${capturedGroup.rootName}" from index ${resumeFrom}/${capturedGroup.totalCount} (delay ${delay}ms)`);
            _uploadFolderGroupLazy(capturedGroup, resumeFrom).catch(err => {
                console.error(`❌ Resume failed for "${capturedGroup.rootName}":`, err);
            });
        }, delay);
        resumed++;
    }
    if (resumed > 0) {
        showUploadStatus(`▶️ Resuming ${resumed} upload(s) after tab woke up...`, 'info');
    }
    return resumed;
}

// Page Lifecycle API — fires when a frozen tab is unfrozen
window.addEventListener('resume', () => {
    if (!isUploading) return;
    console.log('▶️ Page resumed from frozen state — checking for stalled uploads');
    // Give the browser 500 ms to settle promise queues before we intervene
    setTimeout(() => {
        const stalledMs = Date.now() - _lastUploadActivity;
        if (stalledMs > 5000) {
            console.warn(`⚠️ Upload stalled for ${Math.round(stalledMs / 1000)}s — attempting resume`);
            _resumeStalledUploads();
        }
    }, 500);
});

// visibilitychange — fires every time the tab becomes visible (including after freeze)
document.addEventListener('visibilitychange', () => {
    if (document.hidden || !isUploading) return;
    const stalledMs = Date.now() - _lastUploadActivity;
    // If no file completed in the last 10 seconds and we're supposed to be uploading,
    // the loop likely froze.
    if (stalledMs > 10000) {
        console.warn(`⚠️ Tab became visible — upload stalled for ${Math.round(stalledMs / 1000)}s`);
        _resumeStalledUploads();
    }
});

// Parallel upload implementation
async function startParallelUploads(pendingFiles) {
    console.log(`⚡ Starting parallel uploads with max concurrency: ${PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads}`);

    // Upload worker — reads live from uploadQueue so files added mid-upload are picked up.
    // Workers exit only when there's nothing left AND no other worker is about to claim something.
    const uploadWorker = async () => {
        while (isUploading) {
            // Grab next unclaimed pending item directly from the live queue
            const item = uploadQueue.find(q => q.status === 'pending' && !cancelledUploads.has(q.id));
            if (!item) break;

            // Claim it immediately to prevent another worker grabbing the same item
            item.status = 'uploading';
            PARALLEL_UPLOAD_CONFIG.activeUploads.add(item.id);

            try {
                updateItemStatus(item.id, 'uploading');
                await uploadSingleFile(item);

                const currentItem = uploadQueue.find(q => q.id === item.id);
                if (!(currentItem && currentItem.status === 'assembling')) {
                    updateItemStatus(item.id, 'completed');
                }

                PARALLEL_UPLOAD_CONFIG.activeUploads.delete(item.id);
                PARALLEL_UPLOAD_CONFIG.completedUploads.add(item.id);
                cancelledUploads.delete(item.id);

            } catch (error) {
                console.error(`❌ Upload failed: ${item.name}`, error.message);
                updateItemStatus(item.id, 'error', error.message);
                PARALLEL_UPLOAD_CONFIG.activeUploads.delete(item.id);
                cancelledUploads.delete(item.id);
                showUploadStatus(`❌ Failed: "${item.name}" - ${error.message}`, 'error');
            }
        }
    };

    const workerCount = Math.min(PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads, pendingFiles.length);
    console.log(`⚡ Starting ${workerCount} upload workers`);

    const workers = [];
    for (let i = 0; i < workerCount; i++) {
        workers.push(uploadWorker());
    }

    await Promise.all(workers);
    console.log(`⚡ All parallel upload workers completed`);
}

// Sequential upload implementation (original behavior)
async function startSequentialUploads(pendingFiles) {
    console.log('📋 Starting sequential uploads (original behavior)');

    for (let i = 0; i < pendingFiles.length; i++) {
        const item = pendingFiles[i];
        currentUploadIndex = i + 1;

        console.log(`📤 Processing file ${i + 1}/${pendingFiles.length}: ${item.name}`);

        // Update status to uploading
        updateItemStatus(item.id, 'uploading');
        currentUploadingFile = item.id;

        try {
            console.log(`📤 Starting upload for: ${item.name}`);
            await uploadSingleFile(item);
            console.log(`✅ Upload completed for: ${item.name}`);
            updateItemStatus(item.id, 'completed');
            currentUploadingFile = null;
            cancelledUploads.delete(item.id);

        } catch (error) {
            console.error(`❌ Upload failed for ${item.name}:`, error);
            updateItemStatus(item.id, 'error', error.message);
            currentUploadingFile = null;
            cancelledUploads.delete(item.id);

            showUploadStatus(
                `❌ Failed to upload "${item.name}": ${error.message}`,
                'error'
            );

            // Ask user if they want to continue with remaining files
            if (i < pendingFiles.length - 1) {
                const continueUpload = confirm(`Upload failed for "${item.name}". Continue with remaining files?`);
                if (!continueUpload) {
                    console.log('🛑 User chose to stop upload');
                    break;
                }
            }
        }
    }
}

async function uploadSingleFile(item) {
    if (cancelledUploads.has(item.id)) {
        throw new Error('Upload cancelled by user');
    }

    const file = item.file;
    const destPath = item.destinationPath || document.getElementById('destPath').value || '';

    try {
        if (file.size <= CHUNK_SIZE) {
            const formData = new FormData();
            formData.append('filename', file.name);
            formData.append('dest_path', destPath);
            formData.append('file', file);

            let response = await fetch(UPLOAD_URL, {
                method: 'POST',
                body: formData,
                signal: item._abortSignal || null
            });

            // Handle file-already-exists: ask user what to do
            if (response.status === 409) {
                response.body?.cancel();
                const groupDecision = item._groupId ? _overwriteDecisions.get(item._groupId) : 'ask';
                let action = groupDecision || 'ask';

                if (action === 'ask') {
                    action = await _promptOverwrite(item.displayName || file.name);
                    if (item._groupId) {
                        if (action === 'overwrite-all') _overwriteDecisions.set(item._groupId, 'overwrite');
                        if (action === 'skip-all') _overwriteDecisions.set(item._groupId, 'skip');
                        if (action === 'rename-all') _overwriteDecisions.set(item._groupId, 'rename');
                    }
                }

                const shouldSkip = action === 'skip-all' || action === 'skip-one' || groupDecision === 'skip';
                const shouldOverwrite = action === 'overwrite-all' || action === 'overwrite-one' || groupDecision === 'overwrite';
                const shouldRename = action === 'rename-all' || action === 'rename-one' || groupDecision === 'rename';

                if (shouldSkip) {
                    updateItemProgress(item.id, 100, file.size);
                    return; // Skip silently
                }

                if (shouldRename) {
                    const freeName = await _findFreeName(destPath, file.name);
                    const renameForm = new FormData();
                    renameForm.append('filename', freeName);
                    renameForm.append('dest_path', destPath);
                    renameForm.append('file', file);
                    response = await fetch(UPLOAD_URL, {
                        method: 'POST',
                        body: renameForm,
                        signal: item._abortSignal || null
                    });
                } else if (shouldOverwrite) {
                    const retryForm = new FormData();
                    retryForm.append('filename', file.name);
                    retryForm.append('dest_path', destPath);
                    retryForm.append('file', file);
                    retryForm.append('overwrite', '1');
                    response = await fetch(UPLOAD_URL, {
                        method: 'POST',
                        body: retryForm,
                        signal: item._abortSignal || null
                    });
                }
            }

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(errorText);
            }

            response.body?.cancel();
            updateItemProgress(item.id, 100, file.size);

        } else {
            // Chunked upload
            const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

            for (let i = 0; i < totalChunks; i++) {
                if (cancelledUploads.has(item.id)) {
                    throw new Error('Upload cancelled by user');
                }

                const currentItem = uploadQueue.find(queueItem => queueItem.id === item.id);
                if (!currentItem || currentItem.status === 'cancelled') {
                    throw new Error('Upload cancelled by user');
                }

                const start = i * CHUNK_SIZE;
                const end = Math.min(file.size, start + CHUNK_SIZE);
                const chunk = file.slice(start, end);

                const formData = new FormData();
                formData.append('file_id', item.id);
                formData.append('chunk_num', i);
                formData.append('total_chunks', totalChunks);
                formData.append('filename', file.name);
                formData.append('dest_path', destPath);
                formData.append('chunk', chunk);

                if (cancelledUploads.has(item.id)) {
                    throw new Error('Upload cancelled by user');
                }

                const response = await fetch(UPLOAD_URL, {
                    method: 'POST',
                    body: formData,
                    signal: item._abortSignal || null
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`Chunk ${i + 1}/${totalChunks}: ${errorText}`);
                }

                if (i === totalChunks - 1) {
                    try {
                        const responseData = await response.json();
                        if (responseData.assembly_queued) {
                            updateItemProgress(item.id, 100, file.size);
                            updateItemStatus(item.id, 'assembling', 'Processing file...');
                            try {
                                await fetch(`/api/protect_assembly/${item.id}`, { method: 'POST' });
                            } catch (protectError) {
                                console.warn(`⚠️ Failed to protect assembly job ${item.id}:`, protectError);
                            }
                            startAssemblyPolling(item.id);
                            updateManualCleanupButton();
                        } else {
                            updateItemProgress(item.id, 100, file.size);
                        }
                    } catch (jsonError) {
                        updateItemProgress(item.id, 100, file.size);
                    }
                } else {
                    // Intermediate chunk — consume/cancel body to release the ReadableStream
                    response.body?.cancel();
                    const progress = Math.round(((i + 1) / totalChunks) * 100);
                    updateItemProgress(item.id, progress, end);
                }
            }
        }
    } catch (error) {
        console.error('❌ Upload failed:', item.name, error.message);
        throw error;
    }
}

// Auto-cleanup old items periodically (safety net)
setInterval(() => {
    if (!isUploading) {
        const now = Date.now();
        const itemsToRemove = [];

        uploadQueue.forEach((item, index) => {
            // Remove very old completed items (over 2 minutes) as safety net
            if ((item.status === 'completed' || item.status === 'error') && item.completedTime) {
                if (now - item.completedTime > 120000) { // 2 minutes
                    itemsToRemove.push(index);
                }
            }

            // Remove very old pending items (stale for 5+ minutes)
            if (item.status === 'pending' && item.createdTime) {
                const age = now - item.createdTime;
                if (age > 300000) { // 5 minutes
                    console.log(`🧹 Removing stale pending item: ${item.name} (${Math.round(age / 60000)}min old)`);
                    itemsToRemove.push(index);
                    // Try to cleanup its chunks
                    cleanupSingleFile(item.id, item.name).catch(console.error);
                }
            }
        });

        // Remove items in reverse order to maintain indices
        itemsToRemove.reverse().forEach(index => {
            uploadQueue.splice(index, 1);
        });

        if (itemsToRemove.length > 0) {
            console.log(`🧹 Safety cleanup removed ${itemsToRemove.length} old items`);
            updateQueueDisplay();
        }
    }
}, 60000); // Check every 60 seconds

// Selection Management Functions
function toggleSelectAll() {
    const selectAllCheckbox = document.getElementById('selectAll');
    if (!selectAllCheckbox) return;

    const isNowChecked = selectAllCheckbox.checked;
    selectAllCheckbox.indeterminate = false;

    selectedItems.clear();

    if (isNowChecked) {
        // Populate selectedItems from the full VT data array, not just visible DOM rows.
        // Virtual scroll only renders ~80 rows at a time, so querySelectorAll misses the rest.
        const curPath = VT.getPath();
        VT.getAll().forEach(item => {
            const itemPath = curPath ? `${curPath}/${item.name}` : item.name;
            selectedItems.add(itemPath);
        });
    }

    // Sync the visible DOM checkboxes to match
    document.querySelectorAll('.item-checkbox').forEach(checkbox => {
        checkbox.checked = isNowChecked;
        const row = checkbox.closest('tr');
        if (row) row.classList.toggle('selected', isNowChecked);
    });

    // Update the bulk actions UI
    const selectedCount = document.getElementById('selectedCount');
    const bulkActions = document.getElementById('bulkActions');

    if (selectedCount) selectedCount.textContent = selectedItems.size;

    // Update download button text based on selection
    const downloadButton = document.getElementById('bulkDownloadBtn');
    if (downloadButton) {
        if (selectedItems.size === 1) {
            downloadButton.innerHTML = '<i class="fas fa-download"></i> Download';
            downloadButton.title = 'Download selected file directly';
            downloadButton.classList.remove('zip-mode');
        } else if (selectedItems.size > 1) {
            downloadButton.innerHTML = '<i class="fas fa-file-archive"></i> Download ZIP';
            downloadButton.title = `Download ${selectedItems.size} items as ZIP file`;
            downloadButton.classList.add('zip-mode');
        } else {
            downloadButton.innerHTML = '<i class="fas fa-download"></i> Download';
            downloadButton.title = 'Select items to download';
            downloadButton.classList.remove('zip-mode');
        }
    }

    // Show/hide rename button based on selection count
    const renameButton = document.querySelector('.bulk-buttons button[onclick*="showRenameModal"]');
    if (renameButton) {
        if (selectedItems.size === 1) {
            renameButton.style.display = 'flex';
            renameButton.disabled = false;
        } else {
            renameButton.style.display = 'none';
            renameButton.disabled = true;
        }
    }

    if (bulkActions) {
        if (selectedItems.size > 0) {
            bulkActions.classList.add('show');
        } else {
            bulkActions.classList.remove('show');
        }
    }

    console.log(`✅ ${isNowChecked ? 'Selected' : 'Deselected'} all ${selectedItems.size} items`);
}

function updateSelection() {
    // Called onchange on individual checkboxes — must NOT clear+rebuild selectedItems
    // from DOM, because virtual scroll only has ~80 rows visible at a time. Wiping
    // selectedItems and rebuilding from DOM would erase all off-screen selections.
    // Instead, sync only the checkboxes that are currently in the DOM.
    const itemCheckboxes = document.querySelectorAll('.item-checkbox');
    const selectAllCheckbox = document.getElementById('selectAll');
    const bulkActions = document.getElementById('bulkActions');
    const selectedCount = document.getElementById('selectedCount');

    itemCheckboxes.forEach(checkbox => {
        const row = checkbox.closest('tr');
        if (checkbox.checked) {
            selectedItems.add(checkbox.dataset.path);
            if (row) row.classList.add('selected');
        } else {
            selectedItems.delete(checkbox.dataset.path);
            if (row) row.classList.remove('selected');
        }
    });

    const checkedCount = selectedItems.size;
    const totalCount = VT.getAll().length;

    console.log(`📊 Selection update: ${checkedCount}/${totalCount} items selected`);

    if (selectAllCheckbox) {
        if (checkedCount === 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        } else if (checkedCount >= totalCount) {
            selectAllCheckbox.checked = true;
            selectAllCheckbox.indeterminate = false;
        } else {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = true;
        }
    }

    if (selectedCount) selectedCount.textContent = checkedCount;

    // Update download button text based on selection
    const downloadButton = document.getElementById('bulkDownloadBtn');
    if (downloadButton) {
        if (checkedCount === 1) {
            downloadButton.innerHTML = '<i class="fas fa-download"></i> Download';
            downloadButton.title = 'Download selected file directly';
            downloadButton.classList.remove('zip-mode');
        } else if (checkedCount > 1) {
            downloadButton.innerHTML = '<i class="fas fa-file-archive"></i> Download ZIP';
            downloadButton.title = `Download ${checkedCount} items as ZIP file`;
            downloadButton.classList.add('zip-mode');
        } else {
            downloadButton.innerHTML = '<i class="fas fa-download"></i> Download';
            downloadButton.title = 'Select items to download';
            downloadButton.classList.remove('zip-mode');
        }
    }

    // Show/hide rename button based on selection count
    const renameButton = document.querySelector('.bulk-buttons button[onclick*="showRenameModal"]');
    if (renameButton) {
        if (checkedCount === 1) {
            renameButton.style.display = 'flex';
            renameButton.disabled = false;
        } else {
            renameButton.style.display = 'none';
            renameButton.disabled = true;
        }
    }

    if (bulkActions) {
        if (checkedCount > 0) {
            bulkActions.classList.add('show');
        } else {
            bulkActions.classList.remove('show');
        }
    }
}

function initializeRenameButtonVisibility() {
    // Set initial rename button visibility based on current selection
    const renameButton = document.querySelector('.bulk-buttons button[onclick*="showRenameModal"]');
    if (renameButton) {
        // On page load, no items should be selected, so hide rename button
        renameButton.style.display = 'none';
        renameButton.disabled = true;
        console.log('🔧 Initialized rename button visibility - hidden on page load');
    }
}

function clearSelection() {
    selectedItems.clear();
    document.querySelectorAll('.item-checkbox').forEach(checkbox => {
        checkbox.checked = false;
        checkbox.closest('tr').classList.remove('selected');
    });

    const selectAllCheckbox = document.getElementById('selectAll');
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
    }

    // Update the selection UI
    updateSelection();

    console.log('✅ Selection cleared successfully');
}

// Modal Functions
let browserCurrentPath = '';  // Track current path in folder browser

// ── VT-style virtual scroll for the selected-items list in Copy/Move modals ──
// Renders items in batches of VT_LIST_CHUNK (mirrors the main table's CHUNK=80)
// and uses an IntersectionObserver sentinel to load the next batch on scroll.
const VT_LIST_CHUNK = 80;
let _vtListObserver = null;

function _vtListDisconnect() {
    if (_vtListObserver) { _vtListObserver.disconnect(); _vtListObserver = null; }
}

function _vtListRenderChunk(ul, items, rendered) {
    const end = Math.min(rendered + VT_LIST_CHUNK, items.length);
    for (let i = rendered; i < end; i++) {
        const li = document.createElement('li');
        li.textContent = items[i].split('/').pop();
        li.style.cssText = 'padding:2px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
        ul.appendChild(li);
    }
    return end;
}

function _populateSelectedItemsVT(ul) {
    if (!ul) return;
    _vtListDisconnect();
    ul.innerHTML = '';

    ul.style.cssText = [
        'max-height:clamp(120px,22vh,280px)',
        'overflow-y:auto',
        'overflow-x:hidden',
        'margin:0',
        'padding:4px 0 4px 18px',
        'list-style:disc',
        'scrollbar-width:thin',
        'font-size:13px',
        'line-height:1.55',
    ].join(';');

    const items = [...selectedItems];
    const total = items.length;

    let badge = ul.previousElementSibling;
    if (!badge || !badge.classList.contains('vt-list-count')) {
        badge = document.createElement('div');
        badge.className = 'vt-list-count';
        badge.style.cssText = 'font-size:11px;opacity:0.65;margin-bottom:3px;';
        ul.parentNode.insertBefore(badge, ul);
    }
    badge.textContent = `${total} item${total !== 1 ? 's' : ''} selected`;

    if (total === 0) return;

    let rendered = _vtListRenderChunk(ul, items, 0);
    if (rendered >= total) return;

    function _attachListSentinel() {
        const old = ul.querySelector('.vt-list-sentinel');
        if (old) old.remove();

        const remaining = total - rendered;
        const sentinel = document.createElement('li');
        sentinel.className = 'vt-list-sentinel';
        sentinel.style.cssText = 'list-style:none;padding:4px 0;font-size:11px;opacity:0.6;text-align:center;';
        sentinel.innerHTML = `<i class="fas fa-circle-notch fa-spin" style="margin-right:5px;"></i>`
            + `Loading ${Math.min(VT_LIST_CHUNK, remaining)} more of ${remaining} remaining…`;
        ul.appendChild(sentinel);

        _vtListObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                _vtListDisconnect();
                sentinel.remove();
                rendered = _vtListRenderChunk(ul, items, rendered);
                if (rendered < total) _attachListSentinel();
            });
        }, { root: ul, threshold: 0.1 });
        _vtListObserver.observe(sentinel);
    }

    _attachListSentinel();
}

function showMoveModal() {
    if (selectedItems.size === 0) return;

    currentModalAction = 'move';
    const modal = document.getElementById('moveModal');
    const modalTitle = document.getElementById('modalTitle');
    const confirmBtn = document.getElementById('confirmAction');
    const selectedItemsList = document.getElementById('selectedItemsList');

    if (modalTitle) modalTitle.textContent = 'Move Items';
    if (confirmBtn) {
        confirmBtn.textContent = 'Move';
        confirmBtn.className = 'btn btn-warning';
    }

    // Populate selected items list with VT-style virtual scroll
    _populateSelectedItemsVT(selectedItemsList);

    // Initialize folder browser
    initializeFolderBrowser();

    if (modal) modal.classList.add('show');
}

function showCopyModal() {
    if (selectedItems.size === 0) return;

    currentModalAction = 'copy';
    const modal = document.getElementById('moveModal');
    const modalTitle = document.getElementById('modalTitle');
    const confirmBtn = document.getElementById('confirmAction');
    const selectedItemsList = document.getElementById('selectedItemsList');

    if (modalTitle) modalTitle.textContent = 'Copy Items';
    if (confirmBtn) {
        confirmBtn.textContent = 'Copy';
        confirmBtn.className = 'btn btn-success';
    }

    // Populate selected items list with VT-style virtual scroll
    _populateSelectedItemsVT(selectedItemsList);

    // Initialize folder browser
    initializeFolderBrowser();

    if (modal) modal.classList.add('show');
}

// Folder Browser Functions
async function initializeFolderBrowser() {
    browserCurrentPath = '';  // Start at root
    await loadFolderContents('');
    updateCurrentPathDisplay();
    updateUpButton();
}

async function loadFolderContents(path) {
    const loading = document.getElementById('browserLoading');
    const folderList = document.getElementById('folderList');
    const emptyState = document.getElementById('emptyFolderState');

    if (loading) loading.style.display = 'block';
    if (folderList) folderList.innerHTML = '';
    if (emptyState) emptyState.style.display = 'none';

    try {
        console.log(`📁 Loading folder contents for path: "${path}"`);

        // Use the existing API endpoint to get folder contents
        const apiUrl = path ? `/api/files/${encodeURIComponent(path)}` : '/api/files/';
        const response = await fetch(apiUrl);

        if (!response.ok) {
            throw new Error(`Failed to load folder: ${response.statusText}`);
        }

        const data = await response.json();

        if (loading) loading.style.display = 'none';

        // Filter to show only directories
        const folders = data.files.filter(item => item.is_dir || item.type === 'dir');

        if (folders.length === 0) {
            if (emptyState) emptyState.style.display = 'block';
        } else {
            displayFolders(folders);
        }

    } catch (error) {
        console.error('❌ Error loading folder contents:', error);
        if (loading) loading.style.display = 'none';
        if (folderList) {
            folderList.innerHTML = `
                <div style="padding: 15px; text-align: center; color: #e74c3c;">
                    <i class="fas fa-exclamation-triangle"></i><br>
                    Error loading folders: ${error.message}
                </div>
            `;
        }
    }
}

function displayFolders(folders) {
    const folderList = document.getElementById('folderList');
    if (!folderList) return;

    folderList.innerHTML = '';

    folders.forEach(folder => {
        const folderItem = document.createElement('div');
        folderItem.className = 'folder-item';
        folderItem.style.cssText = `
            display: flex;
            align-items: center;
            padding: 8px 12px;
            cursor: pointer;
            border-radius: 6px;
            margin-bottom: 2px;
            transition: background-color 0.2s ease;
            color: #fff;
        `;

        folderItem.innerHTML = `
            <i class="fas fa-folder" style="color: #f39c12; margin-right: 10px; font-size: 14px;"></i>
            <span style="flex: 1;">${folder.name}</span>
            <i class="fas fa-chevron-right" style="color: rgba(255,255,255,0.5); font-size: 12px;"></i>
        `;

        // Add hover effect
        folderItem.addEventListener('mouseenter', function () {
            this.style.backgroundColor = 'rgba(255,255,255,0.1)';
        });

        folderItem.addEventListener('mouseleave', function () {
            this.style.backgroundColor = 'transparent';
        });

        // Add click handler to navigate into folder
        folderItem.addEventListener('click', function () {
            const newPath = browserCurrentPath ? `${browserCurrentPath}/${folder.name}` : folder.name;
            navigateFolderBrowser(newPath);
        });

        folderList.appendChild(folderItem);
    });
}

async function navigateFolderBrowser(path) {
    browserCurrentPath = path;
    await loadFolderContents(path);
    updateCurrentPathDisplay();
    updateUpButton();
}

function updateCurrentPathDisplay() {
    const pathDisplay = document.getElementById('currentDestinationPath');
    if (pathDisplay) {
        pathDisplay.textContent = browserCurrentPath || 'Root Directory';
    }
}

function updateUpButton() {
    const upButton = document.getElementById('upButton');
    if (upButton) {
        upButton.disabled = !browserCurrentPath;
    }
}

function goToRoot() {
    navigateFolderBrowser('');
}

function goUpOneLevel() {
    if (!browserCurrentPath) return;

    const pathParts = browserCurrentPath.split('/');
    pathParts.pop();
    const newPath = pathParts.join('/');
    navigateFolderBrowser(newPath);
}

async function createNewFolderInBrowser() {
    const folderName = prompt('Enter new folder name:');
    if (!folderName || !folderName.trim()) return;

    try {
        const newFolderPath = browserCurrentPath ? `${browserCurrentPath}/${folderName.trim()}` : folderName.trim();

        // Create the folder using existing API
        const response = await fetch('/create_folder', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: `folder_name=${encodeURIComponent(folderName.trim())}&path=${encodeURIComponent(browserCurrentPath)}`
        });

        if (!response.ok) {
            throw new Error('Failed to create folder');
        }

        // Refresh the current folder view
        await loadFolderContents(browserCurrentPath);

        showUploadStatus(`✅ Created folder: ${folderName}`, 'success');

    } catch (error) {
        console.error('❌ Error creating folder:', error);
        showUploadStatus(`❌ Failed to create folder: ${error.message}`, 'error');
    }
}

function closeModal() {
    const modal = document.getElementById('moveModal');
    if (modal) modal.classList.remove('show');

    // Tear down the VT list observer so it doesn't fire after the modal closes
    _vtListDisconnect();

    // Reset form
    const destinationPath = document.getElementById('destinationPath');
    if (destinationPath) destinationPath.value = '';
}

function showRenameModal() {
    if (isOperationInProgress) {
        console.log('⏳ Operation in progress, please wait...');
        showNotification('Please Wait', 'An operation is in progress', 'info');
        return;
    }

    if (selectedItems.size === 0) {
        showNotification('No Selection', 'Please select an item to rename', 'error');
        return;
    }

    if (selectedItems.size > 1) {
        showNotification('Multiple Selection', 'Only one item can be renamed at a time. Please select a single item.', 'error');
        return;
    }

    const selectedPath = Array.from(selectedItems)[0];
    const itemName = selectedPath.split('/').pop();

    const modal = document.getElementById('renameModal');
    const newItemNameInput = document.getElementById('newItemName');
    const currentItemNameDiv = document.getElementById('currentItemName');

    if (newItemNameInput) {
        newItemNameInput.value = itemName;

        const stopPropagation = (e) => e.stopPropagation();

        newItemNameInput.removeEventListener('click', stopPropagation);
        newItemNameInput.removeEventListener('keydown', stopPropagation);
        newItemNameInput.removeEventListener('keyup', stopPropagation);
        newItemNameInput.removeEventListener('input', stopPropagation);
        newItemNameInput.removeEventListener('focus', stopPropagation);

        newItemNameInput.addEventListener('click', stopPropagation);
        newItemNameInput.addEventListener('keydown', stopPropagation);
        newItemNameInput.addEventListener('keyup', stopPropagation);
        newItemNameInput.addEventListener('input', stopPropagation);
        newItemNameInput.addEventListener('focus', stopPropagation);

        setTimeout(() => {
            newItemNameInput.focus();
            const lastDotIndex = itemName.lastIndexOf('.');
            if (lastDotIndex > 0) {
                newItemNameInput.setSelectionRange(0, lastDotIndex);
            } else {
                newItemNameInput.select();
            }
        }, 100);
    }

    if (currentItemNameDiv) {
        currentItemNameDiv.innerHTML = `<i class="fas fa-file"></i> ${itemName}`;
    }

    if (modal) modal.classList.add('show');
}

function closeRenameModal() {
    const modal = document.getElementById('renameModal');
    if (modal) modal.classList.remove('show');

    // Reset form
    const newItemNameInput = document.getElementById('newItemName');
    if (newItemNameInput) newItemNameInput.value = '';
}

// Add this at the top of your script
let isOperationInProgress = false;

async function confirmRename() {
    const newName = document.getElementById('newItemName').value.trim();
    const selectedPath = Array.from(selectedItems)[0];

    if (!newName) {
        showNotification('Invalid Name', 'Please enter a valid name', 'error');
        return;
    }

    // Get current name from selected path
    const currentName = selectedPath.split('/').pop();

    if (newName === currentName) {
        showNotification('Same Name', 'The new name is the same as the current name', 'info');
        closeRenameModal();
        return;
    }

    if (!isValidFilename(newName)) {
        showNotification('Invalid Name', 'Invalid filename. Avoid special characters like <, >, :, ", |, ?, *, \\', 'error');
        return;
    }

    // Prevent rapid-fire renames
    if (isOperationInProgress) {
        console.log('⏳ Please wait for previous operation to complete');
        return;
    }

    isOperationInProgress = true;

    const renameButton = document.querySelector('#renameModal .btn-primary');
    const cancelButton = document.querySelector('#renameModal .btn-secondary');

    if (renameButton) {
        renameButton.disabled = true;
        renameButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Renaming...';
    }
    if (cancelButton) {
        cancelButton.disabled = true;
    }

    try {
        await performRename(selectedPath, newName);

        // Small delay for visual feedback
        await new Promise(resolve => setTimeout(resolve, 300));

    } finally {
        if (renameButton) {
            renameButton.disabled = false;
            renameButton.innerHTML = 'Rename';
        }
        if (cancelButton) {
            cancelButton.disabled = false;
        }

        isOperationInProgress = false;
        closeRenameModal();
    }
}

function isValidFilename(filename) {
    // Check for invalid filename characters
    return !/[<>:"|?*\\\/]/.test(filename) && filename !== '.' && filename !== '..';
}

async function performRename(oldPath, newName) {
    try {
        const response = await fetch('/rename', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                old_path: oldPath,
                new_name: newName
            })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showNotification('Success', result.message || 'Item renamed successfully', 'success');

            // Clear selection immediately before navigating — stale selectedItems
            // causes isOperationInProgress check to block the next rename attempt
            selectedItems.clear();
            isOperationInProgress = false;

            // Trigger navigation (file monitor will update later)
            navigateToFolder(currentPath || '');

        } else {
            showNotification('Rename Failed', result.error || 'Could not rename item', 'error');
        }
    } catch (error) {
        console.error('Rename error:', error);
        showNotification('Error', 'Failed to rename item: ' + error.message, 'error');
    }
}

// Single-item action functions for individual action buttons
function downloadItem(itemPath) {
    // Track download to prevent beforeunload warning
    const downloadId = Date.now() + Math.random();
    activeDownloads.add(downloadId);

    // Create a temporary link to track when download completes
    const link = document.createElement('a');
    link.href = `/download/${itemPath}`;
    link.style.display = 'none';
    document.body.appendChild(link);

    // Remove from active downloads after a delay (download should start)
    setTimeout(() => {
        activeDownloads.delete(downloadId);
        if (document.body.contains(link)) {
            document.body.removeChild(link);
        }
    }, 1000);

    // Trigger download
    window.location.href = `/download/${itemPath}`;
}

function downloadFolderAsZip(folderPath, folderName) {
    console.log(`📁 Downloading folder as ZIP: ${folderName} (${folderPath})`);
    showUploadStatus(`📦 Preparing ZIP download for folder: ${folderName}`, 'info');

    // Track download to prevent beforeunload warning
    const downloadId = Date.now() + Math.random();
    activeDownloads.add(downloadId);

    // Remove from active downloads after a delay (download should start)
    setTimeout(() => {
        activeDownloads.delete(downloadId);
    }, 3000); // Longer delay for ZIP preparation

    // Use the existing bulk download function with single folder path
    performBulkZipDownload([folderPath]);
}

function showSingleMoveModal(itemPath, itemName) {
    // Clear any existing selection and select this item
    clearSelection();
    selectedItems.add(itemPath);

    // Set the checkbox as checked
    const checkbox = document.querySelector(`input[data-path="${itemPath}"]`);
    if (checkbox) {
        checkbox.checked = true;
        checkbox.closest('tr').classList.add('selected');
    }

    // Update the UI and show the modal
    updateSelection();
    showMoveModal();
}

function showSingleCopyModal(itemPath, itemName) {
    // Clear any existing selection and select this item
    clearSelection();
    selectedItems.add(itemPath);

    // Set the checkbox as checked
    const checkbox = document.querySelector(`input[data-path="${itemPath}"]`);
    if (checkbox) {
        checkbox.checked = true;
        checkbox.closest('tr').classList.add('selected');
    }

    // Update the UI and show the modal
    updateSelection();
    showCopyModal();
}

function showSingleRenameModal(itemPath, itemName) {
    // Clear any existing selection and select this item
    clearSelection();
    selectedItems.add(itemPath);

    // Set the checkbox as checked
    const checkbox = document.querySelector(`input[data-path="${itemPath}"]`);
    if (checkbox) {
        checkbox.checked = true;
        checkbox.closest('tr').classList.add('selected');
    }

    // Update the UI and show the modal
    updateSelection();
    showRenameModal();
}

function showSingleDeleteModal(itemPath, itemName) {
    // Show delete confirmation directly for single item
    showDeleteModal(itemName, () => {
        performSingleDelete(itemPath, itemName);
    }, 'individual');
}

async function performSingleDelete(itemPath, itemName) {
    try {
        showUploadStatus('🔄 Deleting item...', 'info');

        const response = await fetch('/bulk_delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paths: [itemPath]
            })
        });

        const result = await response.json();

        if (result.success || result.deleted_count > 0) {
            showUploadStatus(`✅ Successfully deleted "${itemName}"`, 'success');
            await refreshFileTable();
            // Refresh storage stats after delete (file count and size changed)
            refreshStorageStats('delete operation');
        } else {
            const errorMsg = result.error || (result.errors && result.errors[0]) || 'Unknown error';
            showUploadStatus(`❌ Delete failed: ${errorMsg}`, 'error');
        }
    } catch (error) {
        console.error('Delete error:', error);
        showUploadStatus('❌ Network error during delete', 'error');
    } finally {
        closeDeleteModal();
    }
}

async function confirmMoveOrCopy() {
    // Use browserCurrentPath instead of text input
    const destinationPath = browserCurrentPath || '';
    const selectedPaths = Array.from(selectedItems);

    if (selectedPaths.length === 0) {
        showNotification('No Selection', 'No items selected', 'error');
        return;
    }

    // Moving to the same location is a no-op — block it.
    // Copying to the same location is fine — the conflict dialog will offer rename/overwrite.
    const currentLocation = currentPath || '';
    if (destinationPath === currentLocation && currentModalAction === 'move') {
        showNotification('Same Location', 'Cannot move items to the same location', 'error');
        return;
    }

    // Validate destination path
    if (destinationPath && !isValidPath(destinationPath)) {
        showNotification('Invalid Path', 'Invalid destination path. Use forward slashes and avoid special characters.', 'error');
        return;
    }

    const actionName = currentModalAction === 'move' ? 'Move' : 'Copy';
    const destinationDisplay = destinationPath || 'Root Directory';

    // Confirm the action with professional modal
    const confirmMessage = `${actionName} ${selectedPaths.length} item(s) to "${destinationDisplay}"?`;
    const confirmClass = currentModalAction === 'move' ? 'btn-warning' : 'btn-primary';
    const icon = currentModalAction === 'move' ? 'fa-cut' : 'fa-copy';

    const confirmed = await showConfirmationModal(
        `Confirm ${actionName}`,
        confirmMessage,
        actionName,
        confirmClass,
        icon
    );
    if (!confirmed) return;

    // ── Conflict check ────────────────────────────────────────────────────────
    const conflictResolutions = await _promptMoveOrCopyConflicts(
        selectedPaths, destinationPath, currentModalAction
    );
    if (conflictResolutions === null) return;  // user cancelled at conflict dialog
    // ─────────────────────────────────────────────────────────────────────────

    closeModal();

    if (currentModalAction === 'move') {
        performBulkMove(selectedPaths, destinationPath, conflictResolutions);
    } else if (currentModalAction === 'copy') {
        performBulkCopy(selectedPaths, destinationPath, conflictResolutions);
    }
}

function isValidPath(path) {
    // Basic path validation
    return !/[<>:"|?*\\]/.test(path) && !path.includes('..');
}

async function performBulkMove(paths, destination, conflictResolutions = {}) {
    try {
        const response = await fetch('/bulk_move', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paths: paths,
                destination: destination,
                current_path: currentPath || '',
                conflict_resolutions: conflictResolutions
            })
        });

        const result = await response.json();

        if (response.ok) {
            showNotification('Move Successful', `Successfully moved ${result.moved_count} item(s)`, 'success');
            // Clear selection first, then refresh file table
            clearSelection();
            VT.clearDirCache(); // Flush stale folder counts so fresh data is fetched
            await refreshFileTable();
            // Refresh storage stats after move (file locations changed)
            refreshStorageStats('move operation');
        } else {
            showNotification('Move Failed', result.error, 'error');
        }
    } catch (error) {
        showNotification('Move Failed', error.message, 'error');
    }
}

async function performBulkCopy(paths, destination, conflictResolutions = {}) {
    try {
        const response = await fetch('/bulk_copy', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paths: paths,
                destination: destination,
                current_path: currentPath || '',
                conflict_resolutions: conflictResolutions
            })
        });

        const result = await response.json();

        if (response.ok) {
            showNotification('Copy Successful', `Successfully copied ${result.copied_count} item(s)`, 'success');
            clearSelection();

            // The server has started a background reconcile walk.
            // Rebuild the file list immediately (new files are visible) but do NOT
            // feed dir-info cells from the stale in-memory _dir_info — the walk
            // hasn't finished yet so sizes would be wrong.
            // Strategy: rebuild table, then invalidate every dir-info cell so they
            // all show a spinner.  They will be re-fetched when the reconcile_complete
            // SSE arrives and triggers another refreshFileTable().
            VT.clearDirCache();
            await refreshFileTable();

            // Mark all freshly-rendered dir-info cells as pending so they show
            // a spinner instead of fetching stale data right now.
            document.querySelectorAll('.dir-info-cell').forEach(cell => {
                cell.dataset.loaded = '';          // reset "loaded" flag
                cell.innerHTML = '<i class="fas fa-circle-notch fa-spin" style="opacity:0.5;font-size:11px;"></i>';
            });

            showUploadStatus('<i class="fas fa-circle-notch fa-spin"></i> Scanning new files…', 'info');
        } else {
            showNotification('Copy Failed', result.error, 'error');
        }
    } catch (error) {
        showNotification('Copy Failed', error.message, 'error');
    }
}

function bulkDelete() {
    const selectedPaths = Array.from(selectedItems);

    if (selectedPaths.length === 0) {
        showNotification('No Selection', 'No items selected', 'error');
        return;
    }

    showDeleteModal('', () => performBulkDelete(selectedPaths), 'bulk');
}

async function performBulkDelete(paths) {
    _mutationInFlight = true;
    paths.forEach(p => {
        _deletingPaths.add(p);
        document.querySelectorAll(`.dir-info-cell[data-dir-path="${p}"]`).forEach(cell => {
            cell.innerHTML = '<i class="fas fa-spinner fa-spin" style="opacity:0.6;font-size:11px;"></i> Deleting…';
            cell.dataset.loaded = '';
        });
    });
    try {
        const response = await fetch('/bulk_delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paths })
        });
        const result = await response.json();
        if (response.ok) {
            showUploadStatus(`🗑️ Successfully deleted ${result.deleted_count} item(s)`, 'success');
            clearSelection();
            await refreshFileTable();
            refreshStorageStats('bulk delete operation');
        } else {
            showUploadStatus(`❌ Bulk delete failed: ${result.error}`, 'error');
        }
    } catch (error) {
        showUploadStatus(`❌ Bulk delete failed: ${error.message}`, 'error');
    } finally {
        paths.forEach(p => _deletingPaths.delete(p));
        VT.clearDirCache();
        setTimeout(() => { _mutationInFlight = false; }, 1500);
    }
}

// Bulk Download Function - handles single files vs multiple files/folders
function bulkDownload() {
    const selectedPaths = Array.from(selectedItems);

    if (selectedPaths.length === 0) {
        showNotification('No Selection', 'No items selected for download', 'error');
        return;
    }

    console.log('📥 Starting bulk download for:', selectedPaths);

    // Check if we have only a single FILE (not folder) for direct download
    if (selectedPaths.length === 1) {
        const singlePath = selectedPaths[0];

        // Check if it's a file by looking at the table row to determine if it's a directory
        const pathRow = document.querySelector(`tr[data-path="${singlePath}"]`);
        const isDirectory = pathRow && pathRow.querySelector('.folder-icon, .fa-folder');

        if (!isDirectory) {
            console.log('📄 Single file selected, doing direct download:', singlePath);
            showUploadStatus('📥 Starting direct download...', 'info');
            downloadItem(singlePath);
            return;
        } else {
            console.log('📁 Single folder selected, creating ZIP stream:', singlePath);
        }
    }

    // For multiple items, single folders, or any combination, do ZIP stream download
    console.log('📦 Multiple items or folder selected, creating ZIP stream');
    showUploadStatus('📦 Preparing ZIP download...', 'info');
    performBulkZipDownload(selectedPaths);
}

// Perform ZIP streaming download for multiple items
async function performBulkZipDownload(paths) {
    try {
        console.log('🔄 Initiating ZIP stream download for paths:', paths);
        showUploadStatus('📦 Preparing ZIP download...', 'info');

        // Track download to prevent beforeunload warning
        const downloadId = Date.now() + Math.random();
        activeDownloads.add(downloadId);

        // Use form submission method for large files - no memory limits
        console.log('📥 Using form submission for large file download (no memory limits)');

        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '/bulk-download';
        form.style.display = 'none';

        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'paths';
        input.value = JSON.stringify(paths);

        form.appendChild(input);
        document.body.appendChild(form);
        form.submit();

        setTimeout(() => {
            if (document.body.contains(form)) {
                document.body.removeChild(form);
            }
            // Remove from active downloads after form submission completes
            activeDownloads.delete(downloadId);
        }, 2000);

        showUploadStatus('✅ Large file ZIP download started', 'success');
        clearSelection();
        return; // Exit early with form method

        const response = await fetch('/bulk-download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paths: paths
            })
        });

        if (!response.ok) {
            let errorMessage = 'Download failed';
            try {
                const errorData = await response.json();
                errorMessage = errorData.error || errorMessage;
            } catch (e) {
                errorMessage = `Server error: ${response.status} ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }

        // Get the filename from the Content-Disposition header
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'download.zip';
        if (contentDisposition) {
            const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(contentDisposition);
            if (matches != null && matches[1]) {
                filename = matches[1].replace(/['"]/g, '');
            }
        }

        console.log('� ZIP stream response received, filename:', filename);
        showUploadStatus('📥 Processing download...', 'info');

        // Create the blob from the stream
        const blob = await response.blob();
        console.log(`📦 Created blob: ${blob.size} bytes, type: ${blob.type}`);

        if (blob.size === 0) {
            throw new Error('Received empty file from server');
        }

        // Create object URL for download (same approach as single files)
        const url = window.URL.createObjectURL(blob);

        // Create hidden link element
        const downloadLink = document.createElement('a');
        downloadLink.href = url;
        downloadLink.download = filename;
        downloadLink.style.display = 'none';

        // Add to DOM, click, then remove (instant download, no new tab)
        document.body.appendChild(downloadLink);
        downloadLink.click();
        document.body.removeChild(downloadLink);

        // Clean up the object URL
        window.URL.revokeObjectURL(url);

        console.log('✅ ZIP download completed via AJAX method');
        showUploadStatus(`✅ ZIP download started: ${filename}`, 'success');

        // Clear selection after successful download
        clearSelection();

    } catch (error) {
        console.error('❌ ZIP download error:', error);
        showUploadStatus(`❌ Download failed: ${error.message}`, 'error');
    }
}

// Create Folder Function
async function createFolder(folderName, path) {
    try {
        // Use the global currentPath variable instead of the passed path
        const actualPath = currentPath || path || '';

        console.log('Creating folder with currentPath:', actualPath);

        const formData = new FormData();
        formData.append('foldername', folderName);
        formData.append('path', actualPath);

        const response = await fetch('/mkdir', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            showNotification('Folder Created', result.message, 'success');
            document.getElementById('folderNameInput').value = '';
            await refreshFileTable();
            refreshStorageStats('folder creation');
        } else {
            showNotification('Create Folder Failed', result.error, 'error');
        }
    } catch (error) {
        showNotification('Create Folder Failed', error.message, 'error');
    }
}

// Delete Modal Functions
let currentDeleteTarget = null;
let currentDeleteType = 'individual'; // 'individual' or 'bulk'

function showDeleteModal(itemName, deleteCallback, type = 'individual') {
    console.log('showDeleteModal called:', itemName, type);
    currentDeleteTarget = deleteCallback;
    currentDeleteType = type;

    const modal = document.getElementById('deleteModal');
    const message = document.getElementById('deleteMessage');

    if (type === 'bulk') {
        const selectedPaths = Array.from(selectedItems);
        message.textContent = `Are you sure you want to delete ${selectedPaths.length} selected item(s)? This action cannot be undone.`;
    } else {
        message.textContent = `Are you sure you want to delete "${itemName}"? This action cannot be undone.`;
    }

    modal.classList.add('show');
}

function closeDeleteModal() {
    const modal = document.getElementById('deleteModal');
    modal.classList.remove('show');
    currentDeleteTarget = null;
    currentDeleteType = 'individual';
}

function confirmDelete() {
    if (currentDeleteTarget) {
        currentDeleteTarget();
    }
    closeDeleteModal();
}

// Notification Modal Functions
function showNotification(title, message, type = 'info') {
    const modal = document.getElementById('notificationModal');
    const titleElement = document.getElementById('notificationTitle');
    const messageElement = document.getElementById('notificationMessage');

    titleElement.textContent = title;
    messageElement.textContent = message;

    // Add appropriate icon based on type
    const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️';
    titleElement.textContent = `${icon} ${title}`;

    modal.classList.add('show');
}

function closeNotificationModal() {
    const modal = document.getElementById('notificationModal');
    modal.classList.remove('show');
}

// Individual Delete Function
async function deleteItem(itemPath, itemName) {
    console.log('deleteItem called:', itemPath, itemName);
    _mutationInFlight = true;
    _deletingPaths.add(itemPath);

    // Immediately mark the target cell as deleting so the user gets instant feedback
    document.querySelectorAll(`.dir-info-cell[data-dir-path="${itemPath}"]`).forEach(cell => {
        cell.innerHTML = '<i class="fas fa-spinner fa-spin" style="opacity:0.6;font-size:11px;"></i> Deleting…';
        cell.dataset.loaded = '';
    });

    try {
        const response = await fetch('/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `target_path=${encodeURIComponent(itemPath)}`
        });
        if (response.ok) {
            showUploadStatus(`🗑️ Successfully deleted "${itemName}"`, 'success');
            clearSelection();
            await refreshFileTable();
        } else {
            const errorText = await response.text();
            showUploadStatus(`❌ Failed to delete "${itemName}": ${errorText}`, 'error');
        }
    } catch (error) {
        console.error('Delete error:', error);
        showUploadStatus(`❌ Delete failed: ${error.message}`, 'error');
    } finally {
        _deletingPaths.delete(itemPath);
        VT.clearDirCache();
        setTimeout(() => { _mutationInFlight = false; }, 1500);
    }
}

// Add manual cleanup button for debugging/admin use
function addManualCleanupButton() {
    const controls = document.querySelector('.controls');
    if (controls && USER_ROLE === 'readwrite') {
        const cleanupBtn = document.createElement('button');
        cleanupBtn.id = 'manualCleanupBtn';
        cleanupBtn.className = 'btn btn-warning btn-sm manual-cleanup-btn';
        cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Chunk';

        // Hide button by default - only show after status check confirms it's safe
        cleanupBtn.style.display = 'none';
        cleanupBtn.title = 'Checking safety status...';

        cleanupBtn.onclick = async function () {
            try {
                // Double-check for active assembly jobs before proceeding
                const assemblyResponse = await fetch('/api/assembly_status');
                if (assemblyResponse.ok) {
                    const assemblyStatus = await assemblyResponse.json();
                    const activeJobs = assemblyStatus.jobs || [];
                    const hasActiveAssembly = activeJobs.some(job =>
                        job.status === 'pending' || job.status === 'processing'
                    );

                    if (hasActiveAssembly) {
                        showUploadStatus('❌ Cannot cleanup - files are currently being processed/assembled', 'error');
                        console.log('🔐 Manual cleanup blocked - active assembly jobs detected');
                        return;
                    }
                }

                cleanupBtn.disabled = true;
                cleanupBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Cleaning...';

                const response = await fetch('/admin/cleanup_chunks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                const result = await response.json();
                if (response.ok) {
                    showUploadStatus('🧹 Manual cleanup completed successfully', 'success');
                    console.log('Cleanup stats:', result);
                } else {
                    throw new Error(result.error || 'Cleanup failed');
                }
            } catch (error) {
                showUploadStatus(`❌ Manual cleanup failed: ${error.message}`, 'error');
            } finally {
                cleanupBtn.disabled = false;
                cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Chunk';
            }
        };

        controls.appendChild(cleanupBtn);
    }
}

// Function to update manual cleanup button visibility
async function updateManualCleanupButton() {
    const cleanupBtn = document.getElementById('manualCleanupBtn');
    if (!cleanupBtn) return;

    try {
        // Check both upload status and assembly status
        const [uploadResponse, assemblyResponse] = await Promise.all([
            fetch('/admin/upload_status'),
            fetch('/api/assembly_status')
        ]);

        let hasActiveUploads = false;
        let hasActiveAssembly = false;
        let chunkCount = 0;

        // Check upload status
        if (uploadResponse.ok) {
            const uploadStatus = await uploadResponse.json();
            hasActiveUploads = uploadStatus.has_active_uploads;
            chunkCount = typeof uploadStatus.chunk_count === 'number' ? uploadStatus.chunk_count : 0;
        }

        // Check assembly status
        if (assemblyResponse.ok) {
            const assemblyStatus = await assemblyResponse.json();
            const activeJobs = assemblyStatus.jobs || [];
            hasActiveAssembly = activeJobs.some(job =>
                job.status === 'pending' || job.status === 'processing'
            );

            if (hasActiveAssembly) {
                console.log(`🔐 Cleanup button disabled - ${activeJobs.length} active assembly jobs`);
            }
        }

        // Disable button if there are active uploads OR active assembly jobs
        if (isUploading || hasActiveAssembly) {
            cleanupBtn.style.setProperty('display', 'none', 'important');
            if (isUploading) {
                cleanupBtn.title = 'Manual cleanup disabled during active uploads';
            } else if (hasActiveAssembly) {
                cleanupBtn.title = 'Manual cleanup disabled during file processing/assembly';
            }
        } else {
            cleanupBtn.style.setProperty('display', 'inline-flex', 'important');
            // Update title based on whether chunks exist
            if (hasActiveUploads && chunkCount > 0) {
                cleanupBtn.title = `Clean up ${chunkCount} temporary chunk files (Safe - no active uploads or processing)`;
                cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Chunk (' + chunkCount + ')';
            } else {
                cleanupBtn.title = 'Clean up temporary chunk files (Safe - no active uploads or processing)';
                cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Chunk';
            }
        }
    } catch (error) {
        console.warn('Failed to check upload/assembly status:', error);
        // On error, hide the button to be safe
        cleanupBtn.style.setProperty('display', 'none', 'important');
        cleanupBtn.title = 'Manual cleanup disabled (Status check failed)';
    }
}

// Add manual cleanup button for debugging/admin use
function addManualCleanupButton() {
    const controls = document.querySelector('.controls');
    if (controls && USER_ROLE === 'readwrite') {

        // --- Cleanup Chunk button ---
        const cleanupBtn = document.createElement('button');
        cleanupBtn.id = 'manualCleanupBtn';
        cleanupBtn.className = 'btn btn-warning btn-sm manual-cleanup-btn';
        cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Chunk';
        cleanupBtn.style.display = 'none';
        cleanupBtn.title = 'Checking safety status...';

        cleanupBtn.onclick = async function () {
            try {
                const assemblyResponse = await fetch('/api/assembly_status');
                if (assemblyResponse.ok) {
                    const assemblyStatus = await assemblyResponse.json();
                    const activeJobs = assemblyStatus.jobs || [];
                    const hasActiveAssembly = activeJobs.some(job =>
                        job.status === 'pending' || job.status === 'processing'
                    );
                    if (hasActiveAssembly) {
                        showUploadStatus('❌ Cannot cleanup - files are currently being processed/assembled', 'error');
                        return;
                    }
                }
                cleanupBtn.disabled = true;
                cleanupBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Cleaning...';
                const response = await fetch('/admin/cleanup_chunks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const result = await response.json();
                if (response.ok) {
                    showUploadStatus('🧹 Temp chunked files cleanup completed', 'success');
                } else {
                    throw new Error(result.error || 'Cleanup failed');
                }
            } catch (error) {
                showUploadStatus(`❌ Cleanup failed: ${error.message}`, 'error');
            } finally {
                cleanupBtn.disabled = false;
                cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Chunk';
                updateManualCleanupButton();
            }
        };

        controls.appendChild(cleanupBtn);

        // --- Rebuild Cache button ---
        const cacheBtn = document.createElement('button');
        cacheBtn.id = 'cleanupCacheBtn';
        cacheBtn.className = 'btn btn-warning btn-sm manual-cleanup-btn';
        cacheBtn.innerHTML = '<i class="fas fa-database"></i> Rebuild Cache';
        cacheBtn.title = 'Delete storage_index.json and rebuild the index from scratch';

        cacheBtn.onclick = async function () {
            if (!confirm('This will delete the storage index cache and rebuild it from scratch.\nThe server will re-scan all files — this may take a few seconds.\n\nContinue?')) {
                return;
            }
            try {
                cacheBtn.disabled = true;
                cacheBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Rebuilding...';
                const response = await fetch('/admin/rebuild_cache', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const result = await response.json();
                if (response.ok) {
                    showUploadStatus('✅ Cache cleared and rebuilt successfully', 'success');
                } else {
                    throw new Error(result.error || 'Cache cleanup failed');
                }
            } catch (error) {
                showUploadStatus(`❌ Cache cleanup failed: ${error.message}`, 'error');
            } finally {
                cacheBtn.disabled = false;
                cacheBtn.innerHTML = '<i class="fas fa-database"></i> Rebuild Cache';
            }
        };

        controls.appendChild(cacheBtn);
    }
}

// Speed Test Modal Functions
function openSpeedTestModal() {
    const modal = document.getElementById('speedTestModal');
    const results = document.getElementById('speedTestResults');
    if (results) results.innerHTML = '<p>Testing connection...</p>';
    if (modal) modal.classList.add('show');
    runSpeedTest();
}

function closeSpeedTestModal() {
    const modal = document.getElementById('speedTestModal');
    if (modal) modal.classList.remove('show');
}

// Speed Test Logic
async function runSpeedTest() {
    const results = document.getElementById('speedTestResults');
    const TEST_SIZE = 5 * 1024 * 1024; // 5 MiB
    let latency = null, uploadMbps = null, downloadMbps = null;

    try {
        // 1. Latency test (small ping)
        const t0 = performance.now();
        await fetch('/api/speedtest/ping', { method: 'GET' });
        const t1 = performance.now();
        latency = t1 - t0;

        // 2. Upload test
        const uploadData = new Uint8Array(TEST_SIZE); // 5MiB zeroes
        const uploadForm = new FormData();
        uploadForm.append('data', new Blob([uploadData]), 'speedtest.bin');
        const uploadStart = performance.now();
        await fetch('/api/speedtest/upload', { method: 'POST', body: uploadForm });
        const uploadEnd = performance.now();
        const uploadTime = (uploadEnd - uploadStart) / 1000;
        uploadMbps = (TEST_SIZE / 1024 / 1024) / uploadTime;

        // 3. Download test
        const downloadStart = performance.now();
        const resp = await fetch('/api/speedtest/download', { method: 'GET' });
        await resp.arrayBuffer();
        const downloadEnd = performance.now();
        const downloadTime = (downloadEnd - downloadStart) / 1000;
        downloadMbps = (TEST_SIZE / 1024 / 1024) / downloadTime;

        // Show results
        if (results) {
            results.innerHTML = `
                <div><strong>Latency:</strong> ${latency.toFixed(1)} ms</div>
                <div><strong>Upload Speed:</strong> ${uploadMbps.toFixed(2)} MiB/s</div>
                <div><strong>Download Speed:</strong> ${downloadMbps.toFixed(2)} MiB/s</div>
                <div style="margin-top:10px;font-size:12px;color:#888;">Tested with 5 MiB transfer</div>
            `;
        }
    } catch (e) {
        if (results) results.innerHTML = `<div style="color:red;">Speed test failed: ${e}</div>`;
    }
}

document.addEventListener('DOMContentLoaded', function () {
    // Store original table order for reset functionality
    storeOriginalTableOrder();

    // Initialize table sorting functionality
    document.querySelectorAll('.sortable').forEach(header => {
        header.addEventListener('click', function () {
            const column = this.dataset.sort;
            if (column) {
                sortTable(column);
            }
        });
    });

    // Initialize search functionality
    const searchInput = document.getElementById('tableSearch');
    if (searchInput) {
        // Set initial visible count
        const rows = document.querySelectorAll('#filesTable tbody tr');
        const initialCount = Array.from(rows).filter(row =>
            !row.style.background?.includes('rgba(52, 152, 219, 0.1)') &&
            !row.innerHTML.includes('.. (Parent Directory)')
        ).length;

        const visibleCountSpan = document.getElementById('visibleCount');
        if (visibleCountSpan) {
            visibleCountSpan.textContent = initialCount;
        }
    }

    const clearBtn = document.getElementById('clearAllBtn');
    const uploadBtn = document.getElementById('startUploadBtn');
    const fileInput = document.getElementById('fileInput');
    const folderInput = document.getElementById('folderInput');
    const fileInputDisplay = document.querySelector('.file-input-display');
    const speedTestBtn = document.getElementById('speedTestBtn');
    const filesBtn = document.getElementById('filesBtn');
    const foldersBtn = document.getElementById('foldersBtn');

    let currentUploadMode = 'files'; // 'files' or 'folders'

    // Upload mode switcher
    function setUploadMode(mode) {
        currentUploadMode = mode;
        const uploadModeHint = document.getElementById('uploadModeHint');
        const uploadInstructions = document.getElementById('uploadInstructions');

        if (mode === 'files') {
            if (filesBtn) filesBtn.classList.add('active');
            if (foldersBtn) foldersBtn.classList.remove('active');
            if (fileInput) fileInput.style.display = '';
            if (folderInput) folderInput.style.display = 'none';
            updateFileInputDisplay('files');
            if (uploadModeHint) {
                uploadModeHint.textContent = 'Multiple file selection supported';
            }
            if (uploadInstructions) {
                uploadInstructions.style.display = 'none';
            }
        } else {
            if (foldersBtn) foldersBtn.classList.add('active');
            if (filesBtn) filesBtn.classList.remove('active');
            if (fileInput) fileInput.style.display = 'none';
            if (folderInput) folderInput.style.display = '';
            updateFileInputDisplay('folders');
            if (uploadModeHint) {
                if (isAndroid) {
                    uploadModeHint.textContent = '⚠️ Android: One folder at a time (browser limitation)';
                } else if (isMobile) {
                    uploadModeHint.textContent = '📱 Mobile: Limited folder support';
                } else {
                    uploadModeHint.textContent = 'Add multiple folders by clicking repeatedly';
                }
            }
            if (uploadInstructions) {
                uploadInstructions.style.display = 'block';
            }
        }
    }

    function updateFileInputDisplay(mode) {
        const display = document.getElementById('fileInputDisplay');
        if (display) {
            if (mode === 'files') {
                display.innerHTML = `
                    <i class="fas fa-upload" style="font-size: 20px;"></i>
                    <div>
                        <strong>Choose files to upload</strong>
                        <div style="font-size: 12px; opacity: 0.8; margin-top: 5px;">
                            Click here or drag and drop files (multiple files supported)
                        </div>
                    </div>
                `;
            } else {
                if (isAndroid) {
                    display.innerHTML = `
                        <i class="fas fa-folder-open" style="font-size: 20px;"></i>
                        <div>
                            <strong>Choose folders to upload</strong>
                            <div style="font-size: 12px; opacity: 0.8; margin-top: 5px;">
                                <div>📱 Android: Select one folder at a time</div>
                                <div style="margin-top: 2px;">🔄 Click repeatedly to add more folders</div>
                                <div style="margin-top: 2px; color: #f39c12;">⚠️ Drag & drop not supported on Android</div>
                            </div>
                        </div>
                    `;
                } else if (isMobile) {
                    display.innerHTML = `
                        <i class="fas fa-folder-open" style="font-size: 20px;"></i>
                        <div>
                            <strong>Choose folders to upload</strong>
                            <div style="font-size: 12px; opacity: 0.8; margin-top: 5px;">
                                <div>📱 Mobile: Limited folder support</div>
                                <div style="margin-top: 2px;">🔄 Click to select folders one by one</div>
                            </div>
                        </div>
                    `;
                } else {
                    display.innerHTML = `
                        <i class="fas fa-folder-open" style="font-size: 20px;"></i>
                        <div>
                            <strong>Choose folders to upload</strong>
                            <div style="font-size: 12px; opacity: 0.8; margin-top: 5px;">
                                <div>🔄 Click repeatedly to add multiple folders</div>
                                <div style="margin-top: 2px;">🖱️ Or Ctrl+select folders in Explorer, then drag here</div>
                            </div>
                        </div>
                    `;
                }
            }
        }
    }

    // Upload mode button handlers
    if (filesBtn) {
        filesBtn.addEventListener('click', () => setUploadMode('files'));
    }
    if (foldersBtn) {
        foldersBtn.addEventListener('click', () => setUploadMode('folders'));
    }

    // Initialize with files mode only if upload elements exist
    if (filesBtn || foldersBtn) {
        setUploadMode('files');
    }

    // Update mobile-specific instructions after initialization
    function updateMobileInstructions() {
        const uploadInstructions = document.getElementById('uploadInstructions');
        if (uploadInstructions && currentUploadMode === 'folders') {
            if (isAndroid) {
                uploadInstructions.innerHTML = '<small>📱 Android limitation: Select folders one at a time. Drag & drop not supported.</small>';
            } else if (isMobile) {
                uploadInstructions.innerHTML = '<small>📱 Mobile: Limited folder support. Select folders one by one.</small>';
            }
        }
    }

    // Apply mobile instructions on load
    setTimeout(updateMobileInstructions, 100);

    // Add event listeners with null checks
    if (clearBtn) {
        console.log('🔧 Setting up clear button event listener');
        clearBtn.addEventListener('click', clearAllQueue);
    } else {
        console.log('ℹ️ Clear button not found');
    }

    // Add Clear Completed button event listener
    const clearCompletedBtn = document.getElementById('clearCompletedBtn');
    if (clearCompletedBtn) {
        console.log('🔧 Setting up clear completed button event listener');
        clearCompletedBtn.addEventListener('click', function () {
            clearCompletedItems();
        });
    } else {
        console.log('ℹ️ Clear completed button not found');
    }

    if (uploadBtn) {
        console.log('🔧 Setting up upload button event listener');
        uploadBtn.addEventListener('click', startBatchUpload);
    } else {
        console.log('ℹ️ Upload button not found');
    }

    // Setup parallel upload controls
    const enableParallelCheckbox = document.getElementById('enableParallelUploads');
    const maxConcurrentSelect = document.getElementById('maxConcurrentUploads');

    if (enableParallelCheckbox) {
        enableParallelCheckbox.addEventListener('change', function (e) {
            PARALLEL_UPLOAD_CONFIG.enableParallelUploads = e.target.checked;
            console.log(`⚡ Parallel uploads ${e.target.checked ? 'enabled' : 'disabled'}`);

            // Update button text to show current mode
            const uploadBtn = document.getElementById('startUploadBtn');
            if (uploadBtn && !isUploading) {
                const mode = e.target.checked ? 'Parallel' : 'Sequential';
                uploadBtn.title = `${mode} upload mode`;
            }
        });
    }

    if (maxConcurrentSelect) {
        maxConcurrentSelect.addEventListener('change', function (e) {
            const newValue = parseInt(e.target.value);
            PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads = newValue;
            console.log(`⚡ Max concurrent uploads set to: ${newValue}`);
        });
    }

    // Ensure Speed Test button event is attached
    if (speedTestBtn) {
        speedTestBtn.addEventListener('click', openSpeedTestModal);
    }

    // Rename modal Enter key support and Ctrl+A support
    const newItemNameInput = document.getElementById('newItemName');
    if (newItemNameInput) {
        newItemNameInput.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                confirmRename();
            }
        });

        // Add Ctrl+A support for select all
        newItemNameInput.addEventListener('keydown', function (e) {
            if (e.ctrlKey && e.key === 'a') {
                e.preventDefault();
                this.select();
            }
        });
    }

    // Drag and drop functionality (disabled on Android due to poor support)
    if (fileInputDisplay && fileInput && !isAndroid) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            fileInputDisplay.addEventListener(eventName, preventDefaults, false);
            document.body.addEventListener(eventName, preventDefaults, false);
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            fileInputDisplay.addEventListener(eventName, highlight, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            fileInputDisplay.addEventListener(eventName, unhighlight, false);
        });

        fileInputDisplay.addEventListener('drop', handleDrop, false);
    } else if (!isAndroid) {
        // fileInputDisplay not found — attach drop to document.body as fallback
        console.warn('⚠️ .file-input-display not found — attaching drag-drop to body as fallback');
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            document.body.addEventListener(eventName, preventDefaults, false);
        });
        document.body.addEventListener('drop', handleDrop, false);
    } else {
        console.log('📱 Android detected: Drag & drop disabled due to limited browser support');
    }

    // Click functionality works on all devices
    if (fileInputDisplay && fileInput) {
        fileInputDisplay.addEventListener('click', function () {
            if (currentUploadMode === 'files') {
                fileInput.click();
            } else {
                // Use showDirectoryPicker (File System Access API) for true lazy scanning.
                // Falls back to webkitdirectory input on mobile / unsupported browsers.
                if (window.showDirectoryPicker && !isMobile) {
                    _pickFolderLazy();
                } else {
                    // webkitdirectory: browser enumerates all files BEFORE firing change event.
                    // Show scanning message immediately so user knows it's working.
                    showUploadStatus('📂 Opening folder — browser is scanning files…', 'info');
                    folderInput.click();
                }
            }
        });

        // Update file input display when files are selected
        fileInput.addEventListener('change', function (e) {
            handleInputChange(e, 'file');
        });

        // webkitdirectory fallback (mobile / browsers without showDirectoryPicker)
        if (folderInput) {
            folderInput.addEventListener('change', function (e) {
                handleInputChange(e, 'folder');
            });
        }
    }

    async function _pickFolderLazy() {
        let dirHandle;
        try {
            dirHandle = await window.showDirectoryPicker({ mode: 'read' });
        } catch (e) {
            if (e.name !== 'AbortError') console.error('showDirectoryPicker error', e);
            return;
        }

        const rootName = dirHandle.name;
        if (folderGroups.has(rootName)) {
            showUploadStatus(`📁 "${rootName}" is already in the queue`, 'info');
            return;
        }

        const groupId = `fg_${Date.now()}_${Math.random().toString(36).slice(2)}`;
        const group = {
            id: groupId, rootName,
            basePath: currentPath || '',   // frozen at queue time — never changes when user browses
            scanned: 0, completed: 0, errors: 0,
            totalSize: 0,
            status: 'scanning',
            scanComplete: false,   // set true when tree walk finishes; upload loop uses this, not status
            cancelled: false,
            createdTime: Date.now()
        };
        folderGroups.set(groupId, group);
        updateQueueDisplay();
        showUploadStatus(`📂 Scanning "${rootName}"…`, 'info');

        // Recursively walk directory entries, yielding File objects
        async function* walkDir(handle, relPath) {
            for await (const [name, entry] of handle.entries()) {
                if (group.cancelled) return;
                const entryPath = relPath ? `${relPath}/${name}` : name;
                if (entry.kind === 'file') {
                    const file = await entry.getFile();
                    // Attach relative path so upload logic knows destination
                    Object.defineProperty(file, 'relativePath', { value: `${rootName}/${entryPath}`, writable: false });
                    yield file;
                } else if (entry.kind === 'directory') {
                    yield* walkDir(entry, entryPath);
                }
            }
        }

        group.pendingEntries = [];

        let uiThrottle = 0;
        for await (const file of walkDir(dirHandle, '')) {
            if (group.cancelled) break;
            const parts = (`${rootName}/${file.relativePath.slice(rootName.length + 1)}`).split('/');
            parts.pop();
            const relDir = parts.join('/');
            const base = group.basePath || '';
            const dest = base ? (relDir ? `${base}/${relDir}` : base) : relDir;
            const key = `${dest}::${file.name}::${file.size}`;
            if (!_seenFileKeys.has(key)) {
                _seenFileKeys.add(key);
                if (!group._ownedKeys) group._ownedKeys = new Set();
                group._ownedKeys.add(key);
                group.pendingEntries.push({ file, dest, displayName: relDir ? `${relDir}/${file.name}` : file.name });
                group.scanned++;
                group.totalSize += file.size;
            }
            if (++uiThrottle % 200 === 0) updateQueueDisplay();
            if (group.scanned === 1 || group.scanned % 1000 === 0) {
                _spawnFolderWorkersIfNeeded();
            }
        }

        if (!group.cancelled) {
            group.totalCount = group.scanned;
            group.scanComplete = true;
            if (group.status === 'scanning') group.status = 'pending';
            updateQueueDisplay();
            showUploadStatus(`✅ "${rootName}" ready — ${group.scanned.toLocaleString()} files, ${formatFileSize(group.totalSize)}`, 'success');
            _spawnFolderWorkersIfNeeded();
        }
    }


    function handleInputChange(e, type) {
        const fileList = e.target.files;
        if (!fileList || fileList.length === 0) return;

        if (type === 'folder') {
            const fileArray = Array.from(fileList);
            const count = fileArray.length;
            e.target.value = '';

            let mobilePrefix = null;
            const hasRelativePath = !!(fileArray[0] && fileArray[0].webkitRelativePath);
            if (isMobile && !hasRelativePath) {
                const ts = new Date().toISOString().slice(0, 19).replace(/[:\-T]/g, '_');
                mobilePrefix = `MobileUpload_${ts}`;
                console.log('📱 Mobile fallback prefix:', mobilePrefix);
            }
            _registerFolderGroup(fileArray, mobilePrefix);

            const display = document.querySelector('.file-input-display');
            if (display) {
                display.innerHTML = `
                    <i class="fas fa-plus-circle" style="font-size:20px;color:#27ae60;"></i>
                    <div>
                        <strong>${count.toLocaleString()} files queued</strong>
                        <div style="font-size:12px;opacity:0.8;margin-top:4px;">Computing size… click again to add more folders</div>
                    </div>`;
                display.style.borderColor = '#27ae60';
                display.style.backgroundColor = 'rgba(39,174,96,0.1)';
                setTimeout(() => {
                    updateFileInputDisplay(currentUploadMode);
                    display.style.borderColor = 'rgba(255,255,255,0.4)';
                    display.style.backgroundColor = 'rgba(255,255,255,0.1)';
                }, 4000);
            }
            return;
        }

        // ── REGULAR FILES PATH ───────────────────────────────────────────────
        const files = Array.from(fileList);
        if (files.length > 0) {
            addFilesToQueue(files);

            const display = document.querySelector('.file-input-display');
            if (display) {
                const itemType = files.length === 1 ? 'file' : 'files';
                display.innerHTML = `
                    <i class="fas fa-plus-circle" style="font-size: 20px; color: #27ae60;"></i>
                    <div>
                        <strong>Added ${files.length} ${itemType} to queue</strong>
                        <div style="font-size: 12px; opacity: 0.8; margin-top: 5px;">
                            Click again to add more files
                        </div>
                    </div>
                `;
                display.style.borderColor = '#27ae60';
                display.style.backgroundColor = 'rgba(39, 174, 96, 0.1)';
                setTimeout(() => {
                    updateFileInputDisplay(currentUploadMode);
                    display.style.borderColor = 'rgba(255, 255, 255, 0.4)';
                    display.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
                }, 2000);
            }
            e.target.value = '';
        }
    }

    // Add dynamic file type icons for existing files
    document.querySelectorAll('.file-icon-default').forEach(icon => {
        const fileNameElement = icon.parentElement.querySelector('a, span');
        if (fileNameElement) {
            const fileName = fileNameElement.textContent.trim();
            const iconClass = getFileIcon(fileName);
            const color = getFileColor(fileName);

            icon.className = iconClass + ' file-icon';
            icon.style.color = color;
        }
    });

    // Initialize selection handlers
    if (USER_ROLE === 'readwrite') {
        document.querySelectorAll('.item-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', updateSelection);
        });

        // Add delete button event listeners
        document.querySelectorAll('.delete-btn').forEach(button => {
            console.log('🔧 Adding delete event listener to button:', button);
            button.addEventListener('click', handleDeleteClick);
        });

        // Initialize rename button visibility on page load
        setTimeout(() => {
            initializeRenameButtonVisibility();
        }, 100);
    }

    // Add manual cleanup button for debugging
    addManualCleanupButton();

    // Check cleanup button status immediately and again shortly after
    updateManualCleanupButton(); // Immediate check
    setTimeout(() => {
        updateManualCleanupButton(); // Follow-up check to be sure
    }, 100);

    // Check server connectivity first
    async function checkConnectivity() {
        try {
            const response = await fetch('/api/health_check', {
                method: 'GET',
                headers: { 'Accept': 'application/json' }
            });

            if (response.ok) {
                const health = await response.json();
                console.log('Server connectivity OK:', health);
                return true;
            } else {
                console.warn('Server connectivity issue, status:', response.status);
                return false;
            }
        } catch (error) {
            console.error('Server connectivity check failed:', error);
            return false;
        }
    }

    // Load storage statistics with connectivity check
    async function initializeStorageStats() {
        // Prevent duplicate calls during page load
        if (window.storageStatsInitialized) {
            console.log('📊 Storage stats already initialized, skipping...');
            return;
        }
        window.storageStatsInitialized = true;

        console.log('Initializing storage stats...');

        // First check if server is reachable
        const isConnected = await checkConnectivity();
        if (!isConnected) {
            console.error('Server not reachable, showing connectivity error');
            showStorageError('Connection Failed');
            return;
        }

        // Try to load storage stats
        await loadStorageStats();
    }

    // Check for existing assembly jobs immediately
    checkExistingAssemblies();

    // Initialize real-time monitoring (which handles storage stats internally)
    // Only do this once to prevent duplicate SSE connections
    if (!window.storageMonitoringInitialized) {
        initializeRealTimeMonitoring();
    } else {
        console.log('📡 Real-time monitoring already initialized, skipping duplicate initialization');
    }

    // Show enhanced upload hints
    showUploadStatus(
        '<i class="fas fa-info-circle"></i> Enhanced server-sided cleanup active: chunks auto-cleanup on page refresh, connection loss, and periodically',
        'info'
    );

    // Cleanup any stale items from previous sessions on page load
    setTimeout(() => {
        cleanupUnfinishedChunks().catch(console.error);
    }, 2000);

    // Debug info
    console.log('🚀 Cloudinator Enhanced initialized');
    console.log('📤 Upload URL:', UPLOAD_URL);
    console.log('📦 Chunk size:', CHUNK_SIZE, 'bytes (' + Math.round(CHUNK_SIZE / (1024 * 1024)) + 'MB)');
    console.log('🧹 Enhanced cleanup system active');
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

function highlight(e) {
    const fileInputDisplay = document.querySelector('.file-input-display');
    if (fileInputDisplay) {
        fileInputDisplay.style.borderColor = '#2ecc71';
        fileInputDisplay.style.backgroundColor = 'rgba(46, 204, 113, 0.1)';
        fileInputDisplay.style.transform = 'scale(1.02)';
    }
}

function unhighlight(e) {
    const fileInputDisplay = document.querySelector('.file-input-display');
    if (fileInputDisplay) {
        fileInputDisplay.style.borderColor = 'rgba(255, 255, 255, 0.4)';
        fileInputDisplay.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
        fileInputDisplay.style.transform = 'scale(1)';
    }
}

async function handleDrop(e) {
    const dt = e.dataTransfer;

    // Handle both files and directories from drag & drop
    if (dt.items) {
        const plainFiles = [];
        const dirEntries = [];

        for (let i = 0; i < dt.items.length; i++) {
            const item = dt.items[i];
            if (item.kind !== 'file') continue;
            const entry = item.webkitGetAsEntry();
            if (!entry) continue;
            if (entry.isFile) {
                const file = item.getAsFile();
                if (file) plainFiles.push(file);
            } else if (entry.isDirectory) {
                dirEntries.push(entry);
            }
        }

        if (plainFiles.length > 0) addFilesToQueue(plainFiles);

        for (const dirEntry of dirEntries) {
            _registerDirEntryLazy(dirEntry);
        }

    } else {
        const files = Array.from(dt.files);
        if (files.length > 0) addFilesToQueue(files);
    }
}

async function _registerDirEntryLazy(dirEntry) {
    const rootName = dirEntry.name;

    for (const g of folderGroups.values()) {
        if (g.rootName === rootName) {
            showUploadStatus(`📁 "${rootName}" is already in the queue`, 'info');
            return;
        }
    }

    const groupId = `fg_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const group = {
        id: groupId, rootName,
        basePath: currentPath || '',
        scanned: 0, completed: 0, errors: 0,
        totalSize: 0,
        status: 'scanning',
        scanComplete: false,   // set true when tree walk finishes; upload loop uses this, not status
        cancelled: false,
        createdTime: Date.now(),
        pendingEntries: []
    };
    folderGroups.set(groupId, group);
    updateQueueDisplay();
    showUploadStatus(`📂 Scanning "${rootName}"…`, 'info');

    // Walk FileSystemEntry tree using createReader (100 entries per batch — browser limit)
    async function walkEntry(entry, relPath) {
        if (group.cancelled) return;
        if (entry.isFile) {
            await new Promise(resolve => {
                entry.file(file => {
                    const dest = relPath
                        ? (group.basePath ? `${group.basePath}/${relPath}` : relPath)
                        : (group.basePath || '');
                    const displayName = relPath ? `${relPath}/${file.name}` : file.name;
                    const key = `${dest}::${file.name}::${file.size}`;
                    if (!_seenFileKeys.has(key)) {
                        _seenFileKeys.add(key);
                        if (!group._ownedKeys) group._ownedKeys = new Set();
                        group._ownedKeys.add(key);
                        group.pendingEntries.push({ file, dest, displayName });
                        group.scanned++;
                        group.totalSize += file.size;
                    }
                    if (group.scanned % 200 === 0) updateQueueDisplay();
                    if (group.scanned === 100 || group.scanned % 1000 === 0) {
                        _spawnFolderWorkersIfNeeded();
                    }
                    resolve();
                }, resolve);
            });
        } else if (entry.isDirectory) {
            const reader = entry.createReader();
            // createReader only returns up to 100 entries per call — must loop until empty
            await new Promise((resolve, reject) => {
                const subPath = relPath ? `${relPath}/${entry.name}` : entry.name;
                function readBatch() {
                    reader.readEntries(async entries => {
                        if (!entries.length) { resolve(); return; }
                        for (const e of entries) {
                            if (group.cancelled) { resolve(); return; }
                            await walkEntry(e, subPath);
                        }
                        readBatch(); // fetch next batch
                    }, reject);
                }
                readBatch();
            });
        }
    }

    try {
        const reader = dirEntry.createReader();
        await new Promise((resolve, reject) => {
            function readBatch() {
                reader.readEntries(async entries => {
                    if (!entries.length) { resolve(); return; }
                    for (const e of entries) {
                        if (group.cancelled) { resolve(); return; }
                        await walkEntry(e, rootName);
                    }
                    readBatch();
                }, reject);
            }
            readBatch();
        });
    } catch (err) {
        console.error(`❌ Error scanning "${rootName}":`, err);
        showUploadStatus(`❌ Failed to scan "${rootName}"`, 'error');
        folderGroups.delete(groupId);
        updateQueueDisplay();
        return;
    }

    if (!group.cancelled) {
        group.totalCount = group.scanned;
        group.scanComplete = true;
        if (group.status === 'scanning') group.status = 'pending';
        updateQueueDisplay();
        showUploadStatus(`✅ "${rootName}" ready — ${group.scanned.toLocaleString()} files, ${formatFileSize(group.totalSize)}`, 'success');
        _spawnFolderWorkersIfNeeded();
    }
}

// Recursively read directory contents
async function readDirectory(directoryEntry) {
    const files = [];

    return new Promise((resolve, reject) => {
        const directoryReader = directoryEntry.createReader();

        function readEntries() {
            directoryReader.readEntries(async (entries) => {
                if (entries.length === 0) {
                    // No more entries, we're done
                    resolve(files);
                    return;
                }

                try {
                    // Process all entries in parallel
                    const entryPromises = entries.map(async (entry) => {
                        if (entry.isFile) {
                            const file = await getFileFromEntry(entry);
                            if (file) {
                                // Preserve folder structure in file path
                                file.relativePath = entry.fullPath;
                                return file;
                            }
                        } else if (entry.isDirectory) {
                            // Recursively read subdirectory
                            const subFiles = await readDirectory(entry);
                            return subFiles;
                        }
                        return null;
                    });

                    const results = await Promise.all(entryPromises);

                    // Add all files to our collection
                    results.forEach(result => {
                        if (result) {
                            if (Array.isArray(result)) {
                                files.push(...result); // Subdirectory files
                            } else {
                                files.push(result); // Single file
                            }
                        }
                    });

                    // Continue reading (directories might have many entries)
                    readEntries();
                } catch (error) {
                    console.error('Error processing directory entries:', error);
                    reject(error);
                }
            }, (error) => {
                console.error('Error reading directory:', error);
                reject(error);
            });
        }

        readEntries();
    });
}

// Convert FileEntry to File object
function getFileFromEntry(fileEntry) {
    return new Promise((resolve) => {
        fileEntry.file(resolve, () => resolve(null));
    });
}

// Enhanced keyboard shortcuts
document.addEventListener('keydown', function (e) {
    // Ctrl/Cmd + U for upload file/folder selection
    if ((e.ctrlKey || e.metaKey) && e.key === 'u' && !isUploading) {
        e.preventDefault();
        if (typeof currentUploadMode !== 'undefined' && currentUploadMode === 'folders') {
            const folderInput = document.getElementById('folderInput');
            if (folderInput) folderInput.click();
        } else {
            const fileInput = document.getElementById('fileInput');
            if (fileInput) fileInput.click();
        }
    }

    // Shift + Ctrl/Cmd + U for quick "add another folder" (switches to folder mode and opens picker)
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'U' && !isUploading) {
        e.preventDefault();
        // Switch to folder mode if not already
        if (typeof setUploadMode !== 'undefined') {
            setUploadMode('folders');
        }
        // Open folder picker
        setTimeout(() => {
            const folderInput = document.getElementById('folderInput');
            if (folderInput) folderInput.click();
        }, 100);
    }

    // Ctrl/Cmd + Enter to start upload
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !isUploading) {
        e.preventDefault();
        if (uploadQueue.filter(item => item.status === 'pending').length > 0) {
            startBatchUpload();
        }
    }

    // Escape to clear queue or close modal
    if (e.key === 'Escape') {
        const modal = document.getElementById('moveModal');
        if (modal && modal.classList.contains('show')) {
            closeModal();
        } else if (!isUploading && uploadQueue.length > 0) {
            clearAllQueue();
        }
    }

    // Delete key to remove completed/failed items or bulk delete
    if (e.key === 'Delete' && !isUploading) {
        if (selectedItems.size > 0) {
            bulkDelete();
        } else {
            const completedItems = uploadQueue.filter(item =>
                item.status === 'completed' || item.status === 'error'
            );
            completedItems.forEach(item => removeFromQueue(item.id));
        }
    }

    // Ctrl/Cmd + A to select all files
    if ((e.ctrlKey || e.metaKey) && e.key === 'a' && USER_ROLE === 'readwrite') {
        e.preventDefault();
        const selectAllCheckbox = document.getElementById('selectAll');
        if (selectAllCheckbox) {
            selectAllCheckbox.checked = true;
            toggleSelectAll();
        }
    }

    // Backspace or Alt + Left Arrow to go up one level
    if ((e.key === 'Backspace' || (e.altKey && e.key === 'ArrowLeft')) && window.location.pathname !== '/') {
        // Check if user is typing in an input field
        const activeElement = document.activeElement;
        const isInputField = activeElement && (
            activeElement.tagName === 'INPUT' ||
            activeElement.tagName === 'TEXTAREA' ||
            activeElement.contentEditable === 'true'
        );

        // Only navigate back if NOT typing in an input field
        if (!isInputField) {
            e.preventDefault();
            const currentPath = CURRENT_PATH;
            if (currentPath) {
                const pathParts = currentPath.split('/');
                pathParts.pop();
                const parentPath = pathParts.join('/');
                window.location.href = parentPath ? `/${parentPath}` : '/';
            }
        }
    }

    // F5 or Ctrl/Cmd + R - Enhanced refresh with cleanup warning
    if (e.key === 'F5' || ((e.ctrlKey || e.metaKey) && e.key === 'r')) {
        if (isUploading || uploadQueue.some(item => item.status === 'pending')) {
            e.preventDefault();
            const shouldRefresh = confirm('⚠️ Upload in progress. Refreshing will cancel uploads and cleanup temporary files. Continue?');
            if (shouldRefresh) {
                // Try cleanup before refresh
                cleanupUnfinishedChunks().finally(() => {
                    window.location.reload();
                });
            }
        }
    }
});

// Modal close on outside click
document.addEventListener('click', function (e) {
    const modal = document.getElementById('moveModal');
    if (modal && e.target === modal) {
        closeModal();
    }
});

// Update progress every second during upload
setInterval(() => {
    if (isUploading) {
        updateProgressSummary();
    }
}, 1000);

// Check cleanup button state periodically (skip during upload to avoid interrupting connections)
setInterval(() => {
    if (!isUploading) updateManualCleanupButton();
}, 5000);

// Enhanced connection monitoring
let isOnline = navigator.onLine;
let connectionLostTime = null;

function updateConnectionStatus() {
    const wasOnline = isOnline;
    isOnline = navigator.onLine;

    if (!wasOnline && isOnline) {
        // Connection restored
        console.log('🌐 Connection restored');
        if (connectionLostTime) {
            const outageTime = Math.round((Date.now() - connectionLostTime) / 1000);
            showUploadStatus(`🌐 Connection restored after ${outageTime}s outage`, 'success');
            connectionLostTime = null;
        }
    } else if (wasOnline && !isOnline) {
        // Connection lost
        console.log('📡 Connection lost');
        connectionLostTime = Date.now();
        showUploadStatus('📡 Connection lost - uploads will fail', 'error');
    }
}

// Monitor connection changes
window.addEventListener('online', updateConnectionStatus);
window.addEventListener('offline', updateConnectionStatus);

// Ping server periodically to detect connection issues
setInterval(async () => {
    if (isUploading) {
        try {
            const response = await fetch('/admin/chunk_stats', {
                method: 'GET',
                cache: 'no-cache'
            });

            if (!response.ok && isOnline) {
                console.warn('⚠️ Server connection issues detected');
                showUploadStatus('⚠️ Server connection unstable', 'error');
            }
        } catch (error) {
            if (isOnline) {
                console.warn('⚠️ Network connectivity issues:', error);
            }
        }
    }
}, 30000); // Check every 30 seconds during upload

// Global error handler for unhandled promise rejections
window.addEventListener('unhandledrejection', function (event) {
    console.error('🚨 Unhandled promise rejection:', event.reason);

    // If it's related to cleanup, try to handle gracefully
    if (event.reason && event.reason.message && event.reason.message.includes('cleanup')) {
        showUploadStatus('⚠️ Cleanup operation failed - some temporary files may remain', 'error');
        event.preventDefault();
    }
});

// Utility functions
function logout() {
    // Cleanup before logout
    cleanupUnfinishedChunks().finally(() => {
        window.location.href = "{{ url_for('logout') }}";
    });
}

// Export functions for global access
window.CloudinatorUpload = {
    addFilesToQueue,
    startBatchUpload,
    clearAllQueue,
    clearNotificationQueue,
    clearNotificationsByType,
    cleanupUnfinishedChunks,
    showMoveModal,
    showCopyModal,
    bulkDelete,
    bulkDownload,
    clearSelection,
    closeModal,
    confirmMoveOrCopy,
    toggleSelectAll,
    updateSelection,
    setNotificationTimer,
    setParallelUploadConfig,
    goToRoot,
    goUpOneLevel,
    createNewFolderInBrowser
};

// Confirmation Modal Functions
let pendingConfirmAction = null;

function showConfirmationModal(title, message, confirmText = 'Confirm', confirmClass = 'btn-primary', icon = 'fa-question-circle') {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirmationModal');
        const titleElement = document.getElementById('confirmationTitle');
        const messageElement = document.getElementById('confirmationMessage');
        const confirmBtn = document.getElementById('confirmationConfirmBtn');
        const iconElement = document.getElementById('confirmationIcon');

        titleElement.textContent = title;
        messageElement.textContent = message;
        confirmBtn.textContent = confirmText;
        confirmBtn.className = `btn ${confirmClass}`;
        iconElement.className = `fas ${icon}`;

        pendingConfirmAction = resolve;
        modal.style.display = 'block';
    });
}

function closeConfirmationModal() {
    const modal = document.getElementById('confirmationModal');
    modal.style.display = 'none';

    if (pendingConfirmAction) {
        pendingConfirmAction(false);
        pendingConfirmAction = null;
    }
}

function executeConfirmedAction() {
    const modal = document.getElementById('confirmationModal');
    modal.style.display = 'none';

    if (pendingConfirmAction) {
        pendingConfirmAction(true);
        pendingConfirmAction = null;
    }
}

// Assembly Status Tracking
const assemblyPollers = new Map(); // file_id -> interval_id

function startAssemblyPolling(fileId) {
    // Clear any existing poller for this file
    if (assemblyPollers.has(fileId)) {
        clearInterval(assemblyPollers.get(fileId));
    }

    console.log(`🔄 Starting assembly status polling for ${fileId}`);

    const pollInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/assembly_status/${fileId}`);

            if (!response.ok) {
                console.error(`❌ Assembly status check failed for ${fileId}`);
                clearInterval(pollInterval);
                assemblyPollers.delete(fileId);
                updateItemStatus(fileId, 'error', 'Assembly status check failed');
                return;
            }

            const status = await response.json();
            console.log(`📊 Assembly status for ${fileId}:`, status.status);

            if (status.status === 'completed') {
                console.log(`✅ Assembly completed for ${status.filename}`);
                updateItemStatus(fileId, 'completed', 'File ready!');
                clearInterval(pollInterval);
                assemblyPollers.delete(fileId);

                // Update cleanup button availability when assembly completes
                updateManualCleanupButton();

                // Auto-clear the completed item after a short delay
                setTimeout(() => {
                    console.log(`🧹 Auto-clearing completed assembly item: ${fileId}`);
                    const queueContainer = document.getElementById('uploadQueue');
                    const item = document.querySelector(`[data-upload-id="${fileId}"]`);
                    if (item && queueContainer) {
                        item.remove();
                        if (queueContainer.children.length === 0) {
                            queueContainer.style.display = 'none';
                        }
                    }
                }, 3000); // Clear after 3 seconds

                // Also trigger the general auto-cleanup function
                setTimeout(autoCleanupCompletedItems, 5000);

                // Refresh file table to show new file
                setTimeout(() => {
                    refreshFileTable();
                    // Also refresh storage stats after successful upload
                    refreshStorageStats('upload completed');
                }, 1000);

            } else if (status.status === 'error') {
                console.error(`❌ Assembly failed for ${status.filename}: ${status.error_message}`);
                updateItemStatus(fileId, 'error', `Assembly failed: ${status.error_message}`);
                clearInterval(pollInterval);
                assemblyPollers.delete(fileId);
            }
            // Keep polling if status is 'pending' or 'processing'

        } catch (error) {
            console.error(`❌ Assembly polling error for ${fileId}:`, error);
            clearInterval(pollInterval);
            assemblyPollers.delete(fileId);
            updateItemStatus(fileId, 'error', 'Connection error during assembly');
        }
    }, 2000); // Poll every 2 seconds

    assemblyPollers.set(fileId, pollInterval);
}

async function checkExistingAssemblies() {
    // Check for any existing assembly jobs on page load
    try {
        const response = await fetch('/api/assembly_status');

        if (!response.ok) {
            console.log('No existing assembly jobs found');
            return;
        }

        const data = await response.json();
        const jobs = data.jobs || [];

        console.log(`🔄 Found ${jobs.length} existing assembly job(s)`);

        // Process each job
        for (const job of jobs) {
            if (job.status === 'pending' || job.status === 'processing') {
                console.log(`🔄 Resuming assembly tracking for ${job.filename}`);

                // IMMEDIATELY protect this job from cleanup
                try {
                    await fetch(`/api/protect_assembly/${job.file_id}`, { method: 'POST' });
                    console.log(`🔐 Protected assembly job ${job.file_id} from cleanup`);
                } catch (protectError) {
                    console.warn(`⚠️ Failed to protect assembly job ${job.file_id}:`, protectError);
                }

                // Add to upload queue as assembling
                addToUploadQueue({
                    id: job.file_id,
                    name: job.filename,
                    status: 'assembling',
                    progress: 100,
                    message: job.status === 'processing' ? 'Processing file...' : 'Queued for processing...',
                    size: 0 // Unknown size for resumed uploads
                });

                // Start polling for this job
                startAssemblyPolling(job.file_id);

                // Update cleanup button to disable it during assembly
                updateManualCleanupButton();
            }
        }

    } catch (error) {
        console.error('❌ Error checking existing assemblies:', error);
    }
}

// Cleanup polling on page unload
window.addEventListener('beforeunload', () => {
    assemblyPollers.forEach(intervalId => clearInterval(intervalId));
    assemblyPollers.clear();
});

// Log parallel upload configuration on page load
console.log('⚡ Parallel Upload System Initialized');
console.log('📊 Default Configuration:');
console.log(`   • Parallel Uploads: ${PARALLEL_UPLOAD_CONFIG.enableParallelUploads ? 'Enabled' : 'Disabled'}`);
console.log(`   • Max Concurrent: ${PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads}`);
console.log('🔧 Use setParallelUploadConfig(maxConcurrent, enabled) to modify via console');

console.log('✅ Cloudinator Enhanced Upload System Ready');

// Auto-clear completed items from upload queue
function autoCleanupCompletedItems() {


    // Count completed items before clearing
    const completedItems = uploadQueue.filter(item =>
        item.status === 'completed' ||
        item.status === 'assembled' ||
        (item.error && item.error.includes('File ready!'))
    );

    if (completedItems.length === 0) {

        return;
    }

    console.log(`🧹 Found ${completedItems.length} completed items to auto-clear:`,
        completedItems.map(item => `${item.name} (${item.status})`));

    // Remove completed items from queue, and release their dedup keys so the
    // same files can be re-added after the user deletes and re-drops them.
    completedItems.forEach(item => {
        if (item._seenKey) _seenFileKeys.delete(item._seenKey);
    });
    uploadQueue = uploadQueue.filter(item =>
        item.status !== 'completed' &&
        item.status !== 'assembled' &&
        !(item.error && item.error.includes('File ready!'))
    );

    // Update display
    updateQueueDisplay();

    console.log(`🧹 Auto-cleared ${completedItems.length} completed items`);

    // If queue is now empty, hide it
    if (uploadQueue.length === 0) {
        const queueContainer = document.getElementById('uploadQueue');
        if (queueContainer) {
            queueContainer.classList.remove('show');
            console.log('🧹 Upload queue hidden (empty after auto-cleanup)');
        }
    }
}

// Run auto-cleanup every 10 seconds
setInterval(autoCleanupCompletedItems, 10000);

// Also run cleanup when page becomes visible
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        setTimeout(autoCleanupCompletedItems, 1000);
    }
});

// Real-time storage monitoring with Server-Sent Events and Polling Fallback
let storageEventSource = null;
let connectionStatus = 'disconnected';
let reconnectAttempts = 0;
const maxReconnectAttempts = 5;
const reconnectDelay = 3000; // 3 seconds
let lastKnownFileCount = null;
let lastKnownDirCount = null;

// Polling fallback variables
let pollingInterval = null;
let pollingEnabled = false;
let lastPollingCheck = 0;
let sseFailedPermanently = false;

// MANUAL TIMING CONTROLS - Edit these for instant loading
const INSTANT_LOAD_SETTINGS = {
    sseTimeout: 1000,        // How long to wait for SSE before fallback (1 second)
    pollingDelay: 50,        // Delay before starting polling (50ms)
    initialDelay: 50,        // Delay before starting any monitoring (50ms)
    pollingIntervalTime: 500, // How often polling checks for changes (0.5 seconds)
    enableInstantMode: true  // Set to false to use original timing
};

function initializeRealTimeMonitoring() {
    console.log('📡 Initializing INSTANT real-time storage monitoring...');

    // Skip duplicate initialization if already done
    if (window.storageMonitoringInitialized) {
        console.log('📡 Real-time monitoring already initialized, skipping...');
        return;
    }
    window.storageMonitoringInitialized = true;

    // Add Page Visibility API handling to prevent issues on tab switching
    document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
            console.log('📱 Tab became hidden - monitoring continues in background');
        } else {
            console.log('📱 Tab became visible - monitoring already active, no re-initialization needed');
            // Don't re-initialize - just log that tab is visible again
            // This prevents the "+1 files" issue when switching tabs
        }
    });

    // Reset fallback state
    sseFailedPermanently = false;
    pollingEnabled = false;

    // Use manual timing controls
    const sseTimeout = INSTANT_LOAD_SETTINGS.enableInstantMode ? INSTANT_LOAD_SETTINGS.sseTimeout : 2000;
    const initialDelay = INSTANT_LOAD_SETTINGS.enableInstantMode ? INSTANT_LOAD_SETTINGS.initialDelay : 100;

    console.log(`📡 Using instant mode: SSE timeout=${sseTimeout}ms, initial delay=${initialDelay}ms`);

    // Try SSE first with minimal delay
    setTimeout(() => {
        console.log('📡 Attempting SSE connection...');
        connectToStorageStream();

        // Fast fallback to polling if SSE fails
        setTimeout(() => {
            if (connectionStatus !== 'connected' && !window.storageStatsInitialized && !sseFailedPermanently) {
                console.log('⚠️ SSE connection timeout, falling back to instant polling...');
                sseFailedPermanently = true;
                setupFallbackPolling();
            }
        }, sseTimeout);

    }, initialDelay);
}

async function initializeStorageStats() {
    // Prevent duplicate calls during page load
    if (window.storageStatsInitialized) {
        console.log('📊 Storage stats already initialized by main handler, skipping fallback...');
        return;
    }

    console.log('📊 Initializing storage stats at startup...');
    try {
        const response = await fetch('/api/storage_stats');
        if (response.ok) {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                const data = await response.json();
                if (data.file_count !== undefined && data.dir_count !== undefined) {
                    lastKnownFileCount = data.file_count;
                    lastKnownDirCount = data.dir_count;
                    console.log(`📊 Initial stats: ${data.file_count} files, ${data.dir_count} dirs`);
                    updateStorageDisplay(data);
                }
            } else {
                // Got HTML instead of JSON - likely an error page
                const text = await response.text();
                console.warn(`⚠️ Initial stats API returned HTML instead of JSON (status ${response.status}):`, text.substring(0, 100) + '...');
            }
        } else {
            throw new Error(`API error: ${response.status} ${response.statusText}`);
        }
    } catch (error) {
        console.warn('⚠️ Failed to initialize storage stats:', error);
    }
}

function handleStatsUpdate(data) {
    // Check for changes and refresh if needed
    if (lastKnownFileCount !== null && lastKnownDirCount !== null) {
        if (data.file_count !== lastKnownFileCount || data.dir_count !== lastKnownDirCount) {
            console.log(`🔄 Real-time update detected: ${lastKnownFileCount}→${data.file_count} files, ${lastKnownDirCount}→${data.dir_count} dirs`);
            refreshFileTable();
        }
    }

    // Update stored values and display
    lastKnownFileCount = data.file_count;
    lastKnownDirCount = data.dir_count;
    updateStorageDisplay(data);
}

function activateEventDrivenUpdates() {
    console.log('🚀 Activating event-driven storage updates (no polling)...');

    // Clear any existing polling
    if (window.realtimePollingInterval) {
        clearInterval(window.realtimePollingInterval);
        window.realtimePollingInterval = null;
    }

    // Set connection status to active
    document.title = '🟢 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
    connectionStatus = 'connected';
    window.storageStatsInitialized = true;

    console.log('✅ Event-driven updates active - storage stats will update only when files change');
}

// Function to manually refresh storage stats when file operations occur
async function refreshStorageStats(reason = 'manual') {
    try {
        console.log(`📊 Refreshing storage stats (reason: ${reason})`);
        const response = await fetch('/api/storage_stats');
        if (response.ok) {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                const data = await response.json();
                handleStatsUpdate(data);
                document.title = '🟢 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
                console.log(`✅ Storage stats updated (${reason})`);
            } else {
                console.warn(`⚠️ API returned HTML instead of JSON (status ${response.status})`);
                document.title = '🟠 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
            }
        } else {
            throw new Error(`API error: ${response.status} ${response.statusText}`);
        }
    } catch (error) {
        console.error('⚠️ Storage stats refresh failed:', error);
        document.title = '🔴 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
    }
}

function setupFallbackPolling() {
    let sseFailureCount = 0;
    let fallbackPollingInterval = null;

    // Only activate fallback if SSE consistently fails
    const checkSSEHealth = () => {
        if (!storageEventSource || storageEventSource.readyState === EventSource.CLOSED) {
            sseFailureCount++;
            console.warn(`⚠️ SSE connection issue detected (${sseFailureCount}/1)`);

            if (sseFailureCount >= 1 && !fallbackPollingInterval) {
                console.log('🔄 SSE failed - using event-driven updates instead of polling...');
                // Instead of polling, use event-driven updates
                activateEventDrivenUpdates();

                // Optional: Very infrequent fallback check (every 5 minutes) only for connection health
                fallbackPollingInterval = setInterval(async () => {
                    try {
                        const response = await fetch('/api/storage_stats');
                        if (response.ok) {
                            const contentType = response.headers.get('content-type');
                            if (contentType && contentType.includes('application/json')) {
                                const data = await response.json();
                                // Only update if there are significant changes
                                if (data.file_count !== undefined && data.dir_count !== undefined) {
                                    if (lastKnownFileCount !== null && lastKnownDirCount !== null) {
                                        if (Math.abs(data.file_count - lastKnownFileCount) > 5 ||
                                            Math.abs(data.dir_count - lastKnownDirCount) > 2) {
                                            console.log(`🔄 Health check detected significant changes: ${lastKnownFileCount}→${data.file_count} files, ${lastKnownDirCount}→${data.dir_count} dirs`);
                                            await refreshFileTable();
                                            updateStorageDisplay(data);
                                        }
                                    }
                                    lastKnownFileCount = data.file_count;
                                    lastKnownDirCount = data.dir_count;
                                }
                            } else {
                                console.warn(`⚠️ Health check API returned HTML instead of JSON (status ${response.status})`);
                            }
                        } else {
                            throw new Error(`API error: ${response.status} ${response.statusText}`);
                        }
                    } catch (error) {
                        console.warn('⚠️ Health check failed:', error);
                    }
                }, 300000); // Very infrequent - 5 minutes instead of 3 seconds
            }
        } else if (storageEventSource && storageEventSource.readyState === EventSource.OPEN) {
            // SSE is working, reset failure count and clear fallback if active
            if (sseFailureCount > 0) {
                console.log('✅ SSE connection restored, disabling fallback polling');
                sseFailureCount = 0;
                if (fallbackPollingInterval) {
                    clearInterval(fallbackPollingInterval);
                    fallbackPollingInterval = null;
                }
            }
        }
    };

    // Check SSE health every 15 seconds
    setInterval(checkSSEHealth, 15000);
}

function connectToStorageStream() {
    try {
        // Only close existing connection if it's actually dead/errored
        if (storageEventSource && storageEventSource.readyState === EventSource.CLOSED) {
            storageEventSource = null;
        } else if (storageEventSource && storageEventSource.readyState === EventSource.OPEN) {
            console.log('📡 SSE connection already active, not creating duplicate');
            return;
        }

        console.log('📡 Connecting to storage stats stream...');
        console.log('🔍 EventSource URL:', '/api/storage_stats_stream');

        // Show connecting state
        document.title = '🟠 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
        console.log('🟠 Set title to connecting state');

        // Create EventSource with credentials to include session cookies
        storageEventSource = new EventSource('/api/storage_stats_stream', { withCredentials: true });
        console.log('🔍 EventSource created with credentials:', storageEventSource);
        console.log('🔍 Initial readyState:', storageEventSource.readyState);

        // POLL the readyState to detect connection success
        let stateCheckInterval = setInterval(() => {
            console.log('🔍 Checking EventSource readyState:', storageEventSource.readyState);
            if (storageEventSource.readyState === EventSource.OPEN) {
                console.log('🎯 EventSource is OPEN! Connection successful!');
                document.title = '🟢 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
                connectionStatus = 'connected';
                window.storageStatsInitialized = true;
                clearInterval(stateCheckInterval);
            } else if (storageEventSource.readyState === EventSource.CLOSED) {
                console.log('❌ EventSource is CLOSED');
                clearInterval(stateCheckInterval);
            }
        }, 100); // Check every 100ms

        // IMMEDIATE detection of ANY data
        let dataReceived = false;
        storageEventSource.addEventListener('message', function (event) {
            if (!dataReceived) {
                dataReceived = true;
                console.log('🎯 FIRST MESSAGE DETECTED!', event.data);
                // Immediately turn green on first message
                document.title = '🟢 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
                connectionStatus = 'connected';
                window.storageStatsInitialized = true;
            }
        });

        // Keep connection alive by preventing premature closure
        storageEventSource.addEventListener('error', function (event) {
            console.warn('⚠️ SSE error event:', event);
            console.warn('⚠️ EventSource readyState:', storageEventSource.readyState);
            console.warn('⚠️ EventSource url:', storageEventSource.url);
            // Don't immediately close on errors - let the reconnect logic handle it
        });

        storageEventSource.onopen = function (event) {
            console.log('✅ SSE connection successful - disabling polling fallback');
            console.log('🟢 SSE onopen fired - changing title to connected');
            console.log('🟢 EventSource readyState:', storageEventSource.readyState);
            connectionStatus = 'connected';
            reconnectAttempts = 0;

            // Stop polling if it was running
            stopPolling();

            // SSE will provide initial data, no need for separate API call
            window.storageStatsInitialized = true;

            // Add clean connection indicator
            document.title = '🟢 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '') + ' (SSE)';
            console.log('🟢 Title set to connected state:', document.title);
        };

        storageEventSource.onmessage = function (event) {


            // If this is the first message and we're still connecting, treat it as successful connection
            if (document.title.startsWith('🟠')) {
                console.log('🟢 First SSE message received - treating as successful connection');
                document.title = '🟢 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
                connectionStatus = 'connected';
                reconnectAttempts = 0;
                updateConnectionStatus();
                window.storageStatsInitialized = true;
            }

            try {
                const data = JSON.parse(event.data);

                handleStorageUpdate(data);
            } catch (error) {
                console.warn('⚠️ Failed to parse SSE data:', error, event.data);
            }
        };

        storageEventSource.onerror = function (event) {
            console.error('❌ Storage stats stream error:', event);
            console.log('🔴 SSE onerror fired - connection failed');
            console.log('🔴 EventSource readyState:', storageEventSource.readyState);
            connectionStatus = 'error';

            document.title = '🔴 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');

            if (isUploading) {
                console.log('📤 Upload in progress — reconnecting SSE immediately (no give-up limit)');
                reconnectAttempts = 0; // Never count against upload sessions
                setTimeout(() => {
                    connectToStorageStream();
                }, 1000); // Reconnect faster during uploads (1s vs 3s)
                return;
            }

            // Normal (non-upload) path: try a few SSE reconnects then fall back to polling
            if (reconnectAttempts < 2) {
                reconnectAttempts++;
                console.log(`🔄 Attempting SSE reconnect (${reconnectAttempts}/2) in ${reconnectDelay}ms...`);
                setTimeout(() => {
                    connectToStorageStream();
                }, reconnectDelay);
            } else {
                console.error('💀 SSE reconnection failed, switching to polling fallback...');
                sseFailedPermanently = true;

                if (storageEventSource) {
                    storageEventSource.close();
                    storageEventSource = null;
                }

                setupFallbackPolling();
            }
        };

    } catch (error) {
        console.error('❌ Error initializing SSE connection:', error);
        sseFailedPermanently = true;
        setupFallbackPolling();
    }
}

// Polling fallback system for when SSE fails
function setupFallbackPolling() {
    if (pollingEnabled) {
        console.log('📊 Polling already enabled, skipping setup');
        return;
    }

    const pollingDelay = INSTANT_LOAD_SETTINGS.enableInstantMode ? INSTANT_LOAD_SETTINGS.pollingDelay : 0;

    console.log(`🔄 Setting up INSTANT polling fallback (delay: ${pollingDelay}ms)...`);

    setTimeout(() => {
        pollingEnabled = true;
        lastPollingCheck = 0; // Start with 0 for instant initial load

        // Update title to show polling mode
        document.title = '🟠 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '') + ' (Polling)';

        // Start polling with configurable interval
        const pollingIntervalTime = INSTANT_LOAD_SETTINGS.pollingIntervalTime || 2000;
        pollingInterval = setInterval(performPollingCheck, pollingIntervalTime);

        // Perform immediate initial check
        performPollingCheck();
    }, pollingDelay);
}

async function performPollingCheck() {
    try {
        // Include current file/dir counts for accurate change detection
        const currentFiles = lastKnownFileCount || 0;
        const currentDirs = lastKnownDirCount || 0;

        const response = await fetch(`/api/storage_stats_poll?last_check=${lastPollingCheck}&last_files=${currentFiles}&last_dirs=${currentDirs}`, {
            method: 'GET',
            cache: 'no-cache',
            headers: {
                'Cache-Control': 'no-cache'
            }
        });

        if (!response.ok) {
            throw new Error(`Polling failed: ${response.status}`);
        }

        const data = await response.json();
        console.log('📊 Polling response:', data);

        // Update connection status on successful poll
        if (connectionStatus !== 'connected') {
            connectionStatus = 'connected';
            document.title = '🟢 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '') + ' (Polling)';
            console.log('🟢 Polling connection established');
        }

        // Update last check timestamp
        lastPollingCheck = data.timestamp;

        // Handle the data same way as SSE
        if (data.changed || !window.storageStatsInitialized) {
            console.log('🔄 Changes detected via polling, updating display...');

            // Convert polling response to SSE-like format
            const sseData = {
                type: 'storage_stats_update',
                timestamp: data.timestamp,
                initial: !window.storageStatsInitialized,
                data: data.data
            };

            handleStorageUpdate(sseData);
            window.storageStatsInitialized = true;
        }

    } catch (error) {
        console.error('❌ Polling check failed:', error);
        connectionStatus = 'error';
        document.title = '🔴 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '') + ' (Polling)';
    }
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
        pollingEnabled = false;
        console.log('🛑 Polling stopped');
    }
}

function handleStorageUpdate(data) {


    switch (data.type) {
        case 'connected':
            console.log('📡 SSE connection established');
            break;

        case 'storage_stats_update':
            console.log('🔄 Processing storage_stats_update...', data.data,
                data.walk_progress ? '(walk progress)' : '(reconcile complete)');

            // Brief flash to show SSE activity
            document.title = '⚡ ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
            setTimeout(() => {
                document.title = '🟢 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
            }, 2000);

            if (data.data) {
                // Always update the storage stats panel (header numbers, disk bar).
                updateStorageDisplay(data.data);
                // Seed free_space tracker for deletion delta calculation
                if (data.data.free_space != null) _lastFreeSpace = data.data.free_space;

                // Update our tracked file counts
                if (data.data.file_count !== undefined) {
                    lastKnownFileCount = data.data.file_count;
                }
                if (data.data.dir_count !== undefined) {
                    lastKnownDirCount = data.data.dir_count;
                }

                // ── Walk-progress event ────────────────────────────────────────────
                // The walk is still in progress; _dir_info is not yet up-to-date.
                // Only update the stats panel — do NOT refresh the file table or
                // dir-info cells, because they'd fetch stale per-folder sizes.
                // Show a lightweight "scanning…" notification so the user can see
                // the count climbing without the table flickering on every tick.
                if (data.walk_progress && !data.initial) {
                    const changes = data.data.changes || {};
                    if (changes.files_changed > 0 || changes.size_changed !== 0) {
                        let msg = '🔍 Scanning: ';
                        if (data.data.file_count) msg += `${data.data.file_count.toLocaleString()} files`;
                        if (data.data.total_size) {
                            const s = data.data.total_size;
                            const sStr = s >= 1e12 ? (s / 1e12).toFixed(2) + ' TB'
                                : s >= 1e9 ? (s / 1e9).toFixed(2) + ' GB'
                                    : s >= 1e6 ? (s / 1e6).toFixed(1) + ' MB'
                                        : s >= 1024 ? (s / 1024).toFixed(1) + ' KB'
                                            : s + ' bytes';
                            msg += ', ' + sStr;
                        }
                        showUploadStatus(`<i class="fas fa-circle-notch fa-spin"></i> ${msg}`, 'info');
                    }
                    break; // Do NOT fall through to file-table refresh logic
                }

                // ── Reconcile-complete (or regular watchdog) event ─────────────────
                // _dir_info is now authoritative — safe to refresh the file table
                // and re-fetch all dir-info cells.

                // Check for file/folder changes and refresh table if needed
                // Skip change notifications for initial data (page load)
                if (data.data.changes && !data.initial) {
                    const changes = data.data.changes;
                    console.log('🔍 Changes detected:', changes);

                    const hasSignificantChanges = (
                        changes.files_changed !== 0 ||
                        changes.dirs_changed !== 0 ||
                        changes.size_changed !== 0
                    );

                    // Check if we should refresh the file table (broader criteria)
                    const shouldRefresh = (
                        data.reconcile_complete ||      // always refresh when walk is done
                        changes.files_changed !== 0 ||
                        changes.dirs_changed !== 0 ||
                        changes.size_changed !== 0 ||
                        changes.content_changed === true ||
                        changes.mtime_changed === true
                    );

                    if (shouldRefresh) {
                        // Only show notification for significant changes
                        if (hasSignificantChanges) {
                            let message = 'Storage updated: ';
                            if (changes.files_changed > 0) message += `+${changes.files_changed} files `;
                            if (changes.files_changed < 0) message += `${changes.files_changed} files `;
                            if (changes.dirs_changed > 0) message += `+${changes.dirs_changed} folders `;
                            if (changes.dirs_changed < 0) message += `${changes.dirs_changed} folders `;
                            if (changes.size_changed !== 0) message += `size changed `;
                            if (changes.files_changed === 0 && changes.dirs_changed === 0 && changes.size_changed === 0) {
                                message += 'files modified/renamed ';
                            }

                            showUploadStatus(`<i class="fas fa-sync-alt"></i> ${message.trim()}`, 'info');
                        } else {
                            // Minor change - refresh table but don't show notification
                            console.log('📊 Minor content change detected - refreshing table silently');
                        }

                        // Refresh file table for any change
                        console.log('🚀 Triggering instant file table refresh via SSE...');

                        if (!isUploading && !_mutationInFlight) {
                            // Clear stale dir-info cache so loadDirInfoCells() re-fetches
                            // from the server instead of showing cached pre-copy counts.
                            VT.clearDirCache();
                            requestAnimationFrame(async () => { await refreshFileTable(); });
                        } else if (isUploading && !_mutationInFlight) {
                            const uploadPaths = new Set();
                            folderGroups.forEach(g => {
                                if (g.status !== 'uploading' && g.status !== 'pending') return;
                                const base = g.basePath || '';
                                const name = g.rootNameOverride || g.rootName || '';
                                if (name) uploadPaths.add(base ? `${base}/${name}` : name);
                            });

                            document.querySelectorAll('.dir-info-cell').forEach(cell => {
                                const p = cell.dataset.dirPath;
                                if (!p) return;
                                const relevant = [...uploadPaths].some(up => {
                                    if (!up) return false;
                                    return p === up || up.startsWith(p + '/');
                                });
                                if (!relevant) return;
                                VT.invalidateDirCache(p);
                                cell.dataset.loaded = '';
                                fetch('/api/dir_info/' + p)
                                    .then(r => r.json())
                                    .then(data => {
                                        if (data.error) return;
                                        let html = data.file_count + ' files, ' + data.dir_count + ' folders';
                                        if (data.total_size > 0) {
                                            const s = data.total_size;
                                            const sStr = s >= 1e12 ? (s / 1e12).toFixed(2) + ' TB'
                                                : s >= 1e9 ? (s / 1e9).toFixed(2) + ' GB'
                                                    : s >= 1e6 ? (s / 1e6).toFixed(1) + ' MB'
                                                        : s >= 1024 ? (s / 1024).toFixed(1) + ' KB'
                                                            : s + ' bytes';
                                            html += '<br><small style="color:white;">' + sStr + '</small>';
                                        }
                                        cell.innerHTML = html;
                                        cell.dataset.loaded = 'true';
                                        VT.cacheDirInfo(p, data);
                                    })
                                    .catch(() => { });
                            });

                            const now = Date.now();
                            if (now - _lastMidUploadTableRefresh > 3000) {
                                _lastMidUploadTableRefresh = now;
                                requestAnimationFrame(async () => { await refreshFileTable(); });
                            }
                        } else if (_mutationInFlight) {
                            const freeNow = data.data.free_space;
                            if (freeNow != null && _lastFreeSpace != null && _deletingPaths.size > 0) {
                                const freed = freeNow - _lastFreeSpace;
                                if (freed > 0) {
                                    _deletingPaths.forEach(p => {
                                        document.querySelectorAll(`.dir-info-cell[data-dir-path="${p}"]`).forEach(cell => {
                                            const s = freed;
                                            const sStr = s >= 1e12 ? (s / 1e12).toFixed(2) + ' TB freed'
                                                : s >= 1e9 ? (s / 1e9).toFixed(2) + ' GB freed'
                                                    : s >= 1e6 ? (s / 1e6).toFixed(1) + ' MB freed'
                                                        : s >= 1024 ? (s / 1024).toFixed(1) + ' KB freed'
                                                            : s + ' bytes freed';
                                            cell.innerHTML = `<i class="fas fa-spinner fa-spin" style="opacity:0.6;font-size:11px;"></i> Deleting… <small style="color:white;">${sStr}</small>`;
                                        });
                                    });
                                }
                            }
                            if (freeNow != null) _lastFreeSpace = freeNow;
                            console.log('🗑️ Mutation in flight — showing deletion progress via free_space delta');
                        }

                        // Skip redundant storage stats call since we already have the data
                        console.log('📊 Using real-time storage data (skipping additional API call)');
                    } else {
                        console.log('📊 No significant changes detected, no file table refresh needed');
                    }
                } else if (data.initial) {
                    console.log('📊 Initial storage data received (no change notification shown)');
                } else {
                    console.log('📊 No changes data in SSE update');
                }

                console.log(`📊 Updated file counts: ${lastKnownFileCount} files, ${lastKnownDirCount} dirs`);
            }
            break;

        case 'ping':
            // Keep-alive ping, just log it

            break;

        default:
            console.log('📡 Unknown SSE message type:', data.type);
    }
}

function updateConnectionStatus() {
    // Update a connection indicator if you have one in the UI
    // This is optional - you could add a small indicator icon
    const indicator = document.getElementById('connectionStatus');
    if (indicator) {
        indicator.className = `connection-status ${connectionStatus}`;
        indicator.title = `Real-time monitoring: ${connectionStatus}`;
    }
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (storageEventSource) {
        storageEventSource.close();
        storageEventSource = null;
    }
});

// Reconnect when page becomes visible (in case connection was lost)
document.addEventListener('visibilitychange', () => {
    if (!document.hidden && connectionStatus === 'error' && storageEventSource === null) {
        console.log('📡 Page visible - attempting to reconnect to storage stream');
        reconnectAttempts = 0;
        connectToStorageStream();
    }
});

// ── Archive preview: load & retry ────────────────────────────────────────────

/**
 * Fetch archive listing from the server, handling password prompts & errors.
 * Called initially with password=null; retried with the user-supplied password.
 */
function _loadArchivePreview(body, itemPath, password) {
    const url = `/archive_preview/${itemPath}` +
        (password != null ? `?password=${encodeURIComponent(password)}` : '');

    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (data.error === 'password_required') {
                _renderArchivePasswordPrompt(body, itemPath, false);
                return;
            }
            if (data.error === 'wrong_password') {
                _renderArchivePasswordPrompt(body, itemPath, true);
                return;
            }
            if (data.error) {
                body.innerHTML = `
                    <p class="viewer-error">
                        <i class="fas fa-exclamation-triangle"></i>
                        ${escapeHtml(data.error)}
                    </p>`;
                return;
            }
            _renderArchivePreview(body, data);
        })
        .catch(err => {
            body.innerHTML = `
                <p class="viewer-error">
                    <i class="fas fa-exclamation-triangle"></i>
                    Could not load archive: ${escapeHtml(err.message)}
                </p>`;
        });
}

// ── Archive preview: password prompt ─────────────────────────────────────────

function _renderArchivePasswordPrompt(body, itemPath, wrongPassword) {
    body.innerHTML = '';
    body.classList.add('viewer-archive');

    const wrap = document.createElement('div');
    wrap.className = 'archive-password-wrap';
    wrap.innerHTML = `
        <div class="archive-password-icon">
            <i class="fas fa-lock"></i>
        </div>
        <div class="archive-password-title">Password Protected Archive</div>
        <div class="archive-password-subtitle">
            Enter the password to browse the archive contents.
        </div>
        ${wrongPassword ? `
            <div class="archive-password-error">
                <i class="fas fa-exclamation-circle"></i> Incorrect password — please try again.
            </div>` : ''}
        <div class="archive-password-form">
            <div class="archive-password-input-wrap">
                <i class="fas fa-key archive-password-input-icon"></i>
                <input
                    type="password"
                    id="archivePasswordInput"
                    class="archive-password-input"
                    placeholder="Archive password"
                    autocomplete="current-password"
                >
            </div>
            <button class="btn btn-primary archive-password-btn" id="archivePasswordBtn">
                <i class="fas fa-unlock-alt"></i> Unlock
            </button>
        </div>
    `;
    body.appendChild(wrap);

    const input = wrap.querySelector('#archivePasswordInput');
    const btn = wrap.querySelector('#archivePasswordBtn');

    const tryPassword = () => {
        const pw = input.value.trim();
        if (!pw) { input.focus(); input.classList.add('archive-input-shake'); setTimeout(() => input.classList.remove('archive-input-shake'), 500); return; }

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Unlocking…';
        // Show inline spinner while re-fetching
        body.innerHTML = `<div class="viewer-archive-loading">
            <i class="fas fa-circle-notch fa-spin"></i> Unlocking…
        </div>`;
        _loadArchivePreview(body, itemPath, pw);
    };

    btn.addEventListener('click', tryPassword);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') tryPassword(); });

    // Prevent viewer Escape handler from eating keystrokes inside the input
    input.addEventListener('keydown', e => e.stopPropagation(), true);

    input.focus();
}

// ── Archive preview: main renderer ───────────────────────────────────────────

function _renderArchivePreview(body, data) {
    body.innerHTML = '';
    body.classList.add('viewer-archive');

    // ── Helpers ──────────────────────────────────────────────────────────────
    const fmtSize = (bytes) => {
        if (bytes == null || bytes < 0) return '—';
        if (bytes === 0) return '0 B';
        if (bytes >= 1e12) return (bytes / 1e12).toFixed(2) + ' TB';
        if (bytes >= 1e9) return (bytes / 1e9).toFixed(2) + ' GB';
        if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
        if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return bytes + ' B';
    };

    const fileIcon = (name) => {
        const ext = (name.split('.').pop() || '').toLowerCase();
        const map = {
            // images
            jpg: 'fa-file-image', jpeg: 'fa-file-image', png: 'fa-file-image', gif: 'fa-file-image',
            bmp: 'fa-file-image', webp: 'fa-file-image', svg: 'fa-file-image', avif: 'fa-file-image',
            // video
            mp4: 'fa-file-video', avi: 'fa-file-video', mov: 'fa-file-video',
            mkv: 'fa-file-video', webm: 'fa-file-video', wmv: 'fa-file-video',
            // audio
            mp3: 'fa-file-audio', wav: 'fa-file-audio', flac: 'fa-file-audio',
            aac: 'fa-file-audio', ogg: 'fa-file-audio', m4a: 'fa-file-audio',
            // docs
            pdf: 'fa-file-pdf',
            doc: 'fa-file-word', docx: 'fa-file-word',
            xls: 'fa-file-excel', xlsx: 'fa-file-excel',
            ppt: 'fa-file-powerpoint', pptx: 'fa-file-powerpoint',
            // code / text
            js: 'fa-file-code', ts: 'fa-file-code', jsx: 'fa-file-code', tsx: 'fa-file-code',
            py: 'fa-file-code', java: 'fa-file-code', cpp: 'fa-file-code', c: 'fa-file-code',
            cs: 'fa-file-code', go: 'fa-file-code', rb: 'fa-file-code', php: 'fa-file-code',
            html: 'fa-file-code', css: 'fa-file-code', json: 'fa-file-code', xml: 'fa-file-code',
            sh: 'fa-file-code', bat: 'fa-file-code',
            txt: 'fa-file-alt', md: 'fa-file-alt', csv: 'fa-file-alt', log: 'fa-file-alt',
            // archives
            zip: 'fa-file-archive', rar: 'fa-file-archive', '7z': 'fa-file-archive',
            tar: 'fa-file-archive', gz: 'fa-file-archive', bz2: 'fa-file-archive',
        };
        return map[ext] || 'fa-file';
    };

    // ── Build tree from flat entry list ──────────────────────────────────────
    // Each node: { name, is_dir, size, compressed_size, modified, children: {} }
    const root = { children: {} };

    for (const entry of data.entries) {
        // Normalise separators and strip leading slash
        const parts = entry.name.replace(/\\/g, '/').split('/').filter(p => p.length > 0);
        if (!parts.length) continue;

        let node = root;
        for (let i = 0; i < parts.length; i++) {
            const part = parts[i];
            const isLast = i === parts.length - 1;

            if (!node.children[part]) {
                node.children[part] = {
                    name: part,
                    is_dir: !isLast || entry.is_dir,
                    size: 0, compressed_size: 0, modified: '',
                    children: {},
                };
            }
            if (isLast) {
                const n = node.children[part];
                n.is_dir = entry.is_dir;
                n.size = entry.size || 0;
                n.compressed_size = entry.compressed_size || 0;
                n.modified = entry.modified || '';
            }
            node = node.children[part];
        }
    }

    // ── Header bar ───────────────────────────────────────────────────────────
    const fileCt = data.entries.filter(e => !e.is_dir).length;
    const dirCt = data.entries.filter(e => e.is_dir).length;

    const typeBadgeColour = { zip: '#e67e22', rar: '#8e44ad', '7z': '#2980b9', tar: '#27ae60' };
    const badgeStyle = `background:${typeBadgeColour[data.type] || '#555'}`;

    const header = document.createElement('div');
    header.className = 'archive-header';
    header.innerHTML = `
        <span class="archive-type-badge" style="${badgeStyle}">${escapeHtml(data.type.toUpperCase())}</span>
        <span class="archive-stat"><i class="fas fa-file"></i> ${fileCt.toLocaleString()} file${fileCt !== 1 ? 's' : ''}</span>
        <span class="archive-stat"><i class="fas fa-folder"></i> ${dirCt.toLocaleString()} folder${dirCt !== 1 ? 's' : ''}</span>
        <span class="archive-stat"><i class="fas fa-weight-hanging"></i> ${fmtSize(data.total_size)}</span>
        ${data.encrypted ? `<span class="archive-stat archive-stat-lock"><i class="fas fa-lock"></i> Encrypted</span>` : ''}
        ${data.truncated ? `<span class="archive-stat archive-stat-warn">
            <i class="fas fa-exclamation-triangle"></i>
            Showing first 10,000 of ${data.total_entries.toLocaleString()} entries
        </span>` : ''}
    `;
    body.appendChild(header);

    // ── Tree ─────────────────────────────────────────────────────────────────
    const treeWrap = document.createElement('div');
    treeWrap.className = 'archive-tree';
    body.appendChild(treeWrap);

    const renderNode = (node, container, depth) => {
        const sorted = Object.values(node.children).sort((a, b) => {
            if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
            return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
        });

        for (const child of sorted) {
            const hasChildren = Object.keys(child.children).length > 0;

            const row = document.createElement('div');
            row.className = 'archive-entry' + (child.is_dir ? ' archive-entry-dir' : '');
            row.style.paddingLeft = (depth * 16 + 10) + 'px';

            // Compression ratio label
            let ratioHtml = '';
            if (!child.is_dir && child.size > 0 && child.compressed_size > 0 && child.compressed_size < child.size) {
                const pct = Math.round((1 - child.compressed_size / child.size) * 100);
                if (pct > 0) ratioHtml = `<span class="archive-entry-ratio">${pct}% saved</span>`;
            }

            row.innerHTML = `
                <span class="archive-entry-toggle">
                    ${child.is_dir
                    ? `<i class="fas ${hasChildren ? 'fa-chevron-right' : 'fa-minus'} archive-chevron${hasChildren ? '' : ' archive-chevron-empty'}"></i>`
                    : ''}
                </span>
                <i class="fas ${child.is_dir ? 'fa-folder' : fileIcon(child.name)} archive-entry-icon ${child.is_dir ? 'archive-icon-dir' : 'archive-icon-file'}"></i>
                <span class="archive-entry-name">${escapeHtml(child.name)}</span>
                <span class="archive-entry-meta">
                    ${child.modified ? `<span class="archive-entry-date">${escapeHtml(child.modified)}</span>` : ''}
                    ${!child.is_dir && child.size >= 0 ? `<span class="archive-entry-size">${fmtSize(child.size)}</span>` : ''}
                    ${ratioHtml}
                </span>
            `;

            container.appendChild(row);

            if (child.is_dir && hasChildren) {
                const childContainer = document.createElement('div');
                childContainer.className = 'archive-children';
                childContainer.style.display = 'none';
                renderNode(child, childContainer, depth + 1);
                container.appendChild(childContainer);

                // Toggle expand/collapse on click
                row.style.cursor = 'pointer';
                row.addEventListener('click', () => {
                    const chevron = row.querySelector('.archive-chevron:not(.archive-chevron-empty)');
                    const open = childContainer.style.display !== 'none';
                    childContainer.style.display = open ? 'none' : '';
                    if (chevron) {
                        chevron.classList.toggle('fa-chevron-right', open);
                        chevron.classList.toggle('fa-chevron-down', !open);
                    }
                    row.classList.toggle('archive-entry-open', !open);
                    // Update folder icon
                    const folderIcon = row.querySelector('.fa-folder, .fa-folder-open');
                    if (folderIcon) {
                        folderIcon.classList.toggle('fa-folder', open);
                        folderIcon.classList.toggle('fa-folder-open', !open);
                    }
                });
            }
        }
    };

    renderNode(root, treeWrap, 0);

    // Auto-expand if the archive has only one top-level folder
    const topLevelKeys = Object.keys(root.children);
    if (topLevelKeys.length === 1) {
        const firstRow = treeWrap.querySelector('.archive-entry-dir');
        if (firstRow) firstRow.click();
    }
}
// ─────────────────────────────────────────────────────────────────────────────
// HLS Adaptive Streaming helpers  (@videojs/html web-component + ffmpeg backend)
// Served locally from static/js/video.js + static/css/video.css — no CDN.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Append seek overlay buttons on top of the player area.
 * Uses MutationObserver on video-skin's shadow root to sync
 * visibility with Video.js controls (media-controls visible state).
 */
/**
 * Mobile double-tap to seek: tap left third = -10s, tap right third = +10s.
 * Works in normal and fullscreen. Single tap passes through to Video.js controls.
 */
function _initMobileDoubleTapSeek(area) {
    if (!area) return;
    let lastTap = 0, lastX = 0;

    area.addEventListener('touchend', function (e) {
        // Ignore taps on buttons/controls
        if (e.target.closest('button, input, select, a, media-controls')) return;
        const now = Date.now();
        const touch = e.changedTouches[0];
        const rect = area.getBoundingClientRect();
        const x = touch.clientX - rect.left;
        const isDouble = (now - lastTap) < 300 && Math.abs(touch.clientX - lastX) < 80;
        lastTap = now;
        lastX = touch.clientX;
        if (!isDouble) return;
        // Left third = back, right third = forward
        const third = rect.width / 3;
        if (x < third) _hlsSkip(-10);
        else if (x > rect.width - third) _hlsSkip(10);
    }, { passive: true });
}

/**
 * Inject a responsive @media CSS rule into video-skin's shadow root
 * to hide the playback rate button on mobile. Uses @media so it
 * responds to resize without re-injecting.
 */
function _injectMobileSpeedHide(playerEl) {
    if (!playerEl) return;
    const css = `
        @media (max-width: 600px) {
            .media-button--playback-rate,
            media-playback-rate-button {
                display: none !important;
            }
        }
    `;
    let attempts = 0;
    const iv = setInterval(() => {
        attempts++;
        // video-skin is a direct child of video-player
        const skin = playerEl.querySelector('video-skin');
        if (skin && skin.shadowRoot) {
            if (!skin.shadowRoot.querySelector('style[data-speed-hide]')) {
                const s = document.createElement('style');
                s.setAttribute('data-speed-hide', '1');
                s.textContent = css;
                skin.shadowRoot.appendChild(s);
            }
            clearInterval(iv);
            return;
        }
        // Also try playerEl's own shadow root
        if (playerEl.shadowRoot) {
            const skin2 = playerEl.shadowRoot.querySelector('video-skin');
            if (skin2 && skin2.shadowRoot && !skin2.shadowRoot.querySelector('style[data-speed-hide]')) {
                const s = document.createElement('style');
                s.setAttribute('data-speed-hide', '1');
                s.textContent = css;
                skin2.shadowRoot.appendChild(s);
                clearInterval(iv);
                return;
            }
        }
        if (attempts >= 40) clearInterval(iv);
    }, 100);
}

async function _hlsStartStream(itemPath, wrapperId) {
    window._hlsPollCancel = false;
    window._vjsCurrentPlayer = null;

    const $id = id => document.getElementById(id);

    function _setStatus(txt) { const e = $id('hls-status-msg'); if (e) e.textContent = txt; }
    function _setProgress(pct) {
        const pw = $id('hls-progress-wrap'); if (pw) pw.style.display = 'block';
        const pb = $id('hls-progress-bar'); if (pb) pb.style.width = pct + '%';
        const bl = $id('hls-btn-label'); if (bl) bl.textContent = `Processing\u2026 ${pct}%`;
    }
    function _setStreamReady() {
        const bs = $id('hls-btn-spinner'); if (bs) bs.style.display = 'none';
        const bl = $id('hls-btn-label'); if (bl) bl.textContent = '\u26a1 Stream HLS';
        const bt = $id('hls-btn-stream'); if (bt) { bt.disabled = false; bt.title = 'Play adaptive bitrate stream'; }
        const pw = $id('hls-progress-wrap'); if (pw) pw.style.display = 'none';
        _setStatus('');
    }
    function _hideStreamBtn() {
        const bt = $id('hls-btn-stream'); if (bt) bt.style.display = 'none';
        const pw = $id('hls-progress-wrap'); if (pw) pw.style.display = 'none';
    }
    function _hideQualityRow() {
        const qr = $id('hls-quality-row'); if (qr) qr.style.display = 'none';
    }

    // Tear down whatever is currently in hls-player-area before mounting
    // a new player. Calling destroy() on the Lit web component is what
    // actually releases the MediaSource — just setting innerHTML doesn't.
    function _destroyCurrentPlayer() {
        const area = $id('hls-player-area');
        if (!area) return;
        area.querySelectorAll('video, audio').forEach(m => {
            try { m.pause(); m.removeAttribute('src'); m.load(); } catch (_) { }
        });
        area.querySelectorAll('video-player, video-skin').forEach(el => {
            try { if (typeof el.destroy === 'function') el.destroy(); } catch (_) { }
        });
        // Remove only player elements, preserve the seek overlay
        Array.from(area.children).forEach(el => {
            el.remove();
        });
    }

    function _mountRawPlayer(src, autoplay) {
        const area = $id('hls-player-area');
        if (!area) return;
        _destroyCurrentPlayer();
        area.style.cssText = 'width:100%;min-height:300px;flex:1 1 auto;position:relative;';
        const ap = autoplay ? 'autoplay muted' : '';
        area.insertAdjacentHTML('afterbegin', `
          <video-player class="vjs-cloudinator-player" style="width:100%;height:100%;display:block;">
            <video-skin>
              <video slot="media" src="${escapeHtml(src)}" ${ap} playsinline style="width:100%;height:100%;"></video>
            </video-skin>
          </video-player>`);
        const playerEl = area.querySelector('video-player');
        window._vjsCurrentPlayer = playerEl;
        if (autoplay) _unmuteWhenReady(playerEl);
        _hideQualityRow();
        _injectMobileSpeedHide(playerEl);
        _initMobileDoubleTapSeek(area);
    }

    function _mountHlsPlayer(masterUrl, autoplay) {
        const area = $id('hls-player-area');
        if (!area) return;
        _destroyCurrentPlayer();
        area.style.cssText = 'width:100%;min-height:300px;flex:1 1 auto;position:relative;';
        const ap = autoplay ? 'autoplay muted' : '';
        area.insertAdjacentHTML('afterbegin', `
          <video-player class="vjs-cloudinator-player" style="width:100%;height:100%;display:block;">
            <video-skin>
              <video slot="media"
                     src="${escapeHtml(masterUrl)}"
                     type="application/x-mpegURL"
                     ${ap}
                     playsinline
                     style="width:100%;height:100%;">
              </video>
            </video-skin>
          </video-player>`);
        const playerEl = area.querySelector('video-player');
        window._vjsCurrentPlayer = playerEl;
        if (autoplay) _unmuteWhenReady(playerEl);
        _attachQualitySelector(playerEl);
        _injectMobileSpeedHide(playerEl);
        _initMobileDoubleTapSeek(area);
    }

    const rawBtn = $id('hls-btn-raw');
    if (rawBtn) {
        rawBtn.addEventListener('click', () => {
            _setStatus('');
            _destroyCurrentPlayer();
            _mountRawPlayer(`/view/${itemPath}`, false);
            rawBtn.classList.add('hls-btn-active');
            const sb = $id('hls-btn-stream'); if (sb) sb.classList.remove('hls-btn-active');
        });
    }

    // Web-native formats browsers can decode directly without transcoding.
    // Non-native formats (mkv, avi, wmv, flv, etc.) must go through HLS because
    // browsers cannot decode x265/HEVC or many other codecs natively.
    const _WEB_NATIVE_EXTS = new Set(['mp4', 'webm', 'mov', 'm4v', 'ogv']);
    const _itemExt = itemPath.split('.').pop().toLowerCase();
    const _isWebNative = _WEB_NATIVE_EXTS.has(_itemExt);

    // ── Check HLS status FIRST before mounting anything ───────────────────────
    // If HLS cache is already ready, go straight to HLS — never flash raw first.
    // Only fall back to raw if HLS is unavailable or still transcoding.
    let startData;
    try {
        _setStatus('Checking stream\u2026');
        const r = await fetch(`/hls_start/${itemPath}`, { cache: 'no-store' });
        startData = await r.json();
    } catch (err) {
        _setStatus('');
        _hideStreamBtn();
        // Fetch failed entirely — fall back to raw
        _mountRawPlayer(`/view/${itemPath}`, true);
        const rb = $id('hls-btn-raw'); if (rb) rb.classList.add('hls-btn-active');
        return;
    }

    if (!startData.hls_available) {
        // No HLS (ffmpeg missing/disabled or unsupported format)
        _hideStreamBtn();
        _setStatus('');
        if (!_isWebNative) {
            // Non-native codec, no HLS — mount raw (audio-only for x265/HEVC is fine)
            const rb = $id('hls-btn-raw');
            if (rb) { rb.style.opacity = ''; rb.style.pointerEvents = ''; rb.title = 'Play without transcoding'; }
            _mountRawPlayer(`/view/${itemPath}`, false);
            if (rb) rb.classList.add('hls-btn-active');
            // Only warn when ffmpeg is genuinely missing; stay silent when it's intentionally disabled
            if (startData.reason !== 'ffmpeg_disabled') {
                _setStatus('\u26a0\ufe0f ffmpeg not found \u2014 raw playback may fail for x265/HEVC files');
            }
        } else {
            _mountRawPlayer(`/view/${itemPath}`, true);
            const rb = $id('hls-btn-raw'); if (rb) rb.classList.add('hls-btn-active');
        }
        return;
    }

    const cacheKey = startData.cache_key;

    if (startData.status === 'ready') {
        // HLS already cached — go straight to HLS, never flash raw first.
        // Raw button is left enabled for audio-only access (e.g. x265 MKV).
        _setStreamReady();
        _wireStreamButton(cacheKey, startData.profiles);
        _setStatus('');
        _mountHlsPlayer(`/hls_files/${cacheKey}/master.m3u8`, true);
        const rb2 = $id('hls-btn-raw');
        if (rb2) {
            rb2.classList.remove('hls-btn-active');
            rb2.style.opacity = '';
            rb2.style.pointerEvents = '';
            if (!_isWebNative) rb2.title = 'Play raw (audio only for x265/HEVC)';
        }
        const sb = $id('hls-btn-stream'); if (sb) sb.classList.add('hls-btn-active');
        _buildQualityBar(startData.profiles, cacheKey);
        return;
    }

    // HLS is still transcoding — mount appropriate fallback while we wait
    if (_isWebNative) {
        // Web-native: raw plays fine while HLS processes in background
        _mountRawPlayer(`/view/${itemPath}`, true);
        const rb = $id('hls-btn-raw'); if (rb) rb.classList.add('hls-btn-active');
    } else {
        // Non-native: show placeholder — raw won't work, HLS will autoplay when ready
        const area = $id('hls-player-area');
        if (area) {
            area.style.cssText = 'width:100%;min-height:300px;flex:1 1 auto;display:flex;align-items:center;justify-content:center;background:#111;border-radius:8px;';
            area.innerHTML = `
              <div style="text-align:center;color:rgba(255,255,255,0.6);padding:32px;">
                <div style="font-size:32px;margin-bottom:12px;">⚙️</div>
                <div style="font-size:14px;font-weight:600;margin-bottom:6px;">Preparing stream…</div>
                <div style="font-size:12px;opacity:0.7;">This format requires transcoding for browser playback.<br>HLS stream will start automatically when ready.</div>
              </div>`;
        }
        _setStatus('Transcoding for browser compatibility\u2026');
        const rb = $id('hls-btn-raw');
        if (rb) {
            rb.title = 'Raw playback unavailable — codec not supported by browser';
            rb.style.opacity = '0.4';
            rb.style.pointerEvents = 'none';
        }
    }

    const MAX_POLLS = 300;
    let polls = 0;
    while (!window._hlsPollCancel) {
        if (++polls > MAX_POLLS) { _hideStreamBtn(); _setStatus(''); return; }
        let st;
        try {
            const r = await fetch(`/hls_status/${cacheKey}`, { cache: 'no-store' });
            st = await r.json();
        } catch (_) { await _hlsSleep(2000); continue; }

        if (st.status === 'ready') {
            _setStreamReady();
            _wireStreamButton(cacheKey, st.profiles);
            _buildQualityBar(st.profiles, cacheKey);
            if (!_isWebNative) {
                // Non-native format: auto-switch to HLS.
                // Also re-enable raw button — now that processing is done it can
                // be used for audio-only playback (e.g. x265/HEVC MKV).
                _mountHlsPlayer(`/hls_files/${cacheKey}/master.m3u8`, true);
                const rb3 = $id('hls-btn-raw');
                if (rb3) {
                    rb3.classList.remove('hls-btn-active');
                    rb3.style.opacity = '';
                    rb3.style.pointerEvents = '';
                    rb3.title = 'Play raw (audio only for x265/HEVC)';
                }
                const sb3 = $id('hls-btn-stream'); if (sb3) sb3.classList.add('hls-btn-active');
                _setStatus('');
            } else {
                _setStatus('HLS ready \u2014 click \u26a1 Stream HLS to switch');
            }
            return;
        }
        if (st.status === 'error') {
            _hideStreamBtn();
            _setStatus('');
            // For non-native formats, show error in the placeholder area
            if (!_isWebNative) {
                const area = $id('hls-player-area');
                if (area && !area.querySelector('video')) {
                    area.innerHTML = `<div style="text-align:center;color:rgba(255,100,100,0.8);padding:32px;"><div style="font-size:28px;margin-bottom:10px;">\u274c</div><div style="font-size:13px;">Transcoding failed. Try downloading the file.</div></div>`;
                }
            }
            return;
        }

        const pct = typeof st.progress === 'number' ? st.progress : 0;
        _setProgress(pct);
        _setStatus('Pre-processing adaptive bitrate stream\u2026');
        await _hlsSleep(2000);
    }
}

function _wireStreamButton(cacheKey, profiles) {
    const btn = document.getElementById('hls-btn-stream');
    if (!btn) return;
    const fresh = btn.cloneNode(true);
    btn.parentNode.replaceChild(fresh, btn);

    fresh.addEventListener('click', () => {
        const masterUrl = `/hls_files/${cacheKey}/master.m3u8`;
        const area = document.getElementById('hls-player-area');
        if (!area) return;

        // Destroy existing player before mounting HLS — prevents double audio
        area.querySelectorAll('video, audio').forEach(m => {
            try { m.pause(); m.removeAttribute('src'); m.load(); } catch (_) { }
        });
        area.querySelectorAll('video-player, video-skin').forEach(el => {
            try { if (typeof el.destroy === 'function') el.destroy(); } catch (_) { }
        });

        area.style.cssText = 'width:100%;min-height:300px;flex:1 1 auto;';
        area.innerHTML = `
          <video-player class="vjs-cloudinator-player" style="width:100%;height:100%;display:block;">
            <video-skin>
              <video slot="media"
                     src="${masterUrl}"
                     type="application/x-mpegURL"
                     playsinline
                     style="width:100%;height:100%;">
              </video>
            </video-skin>
          </video-player>`;
        const playerEl = area.querySelector('video-player');
        window._vjsCurrentPlayer = playerEl;
        _unmuteWhenReady(playerEl);
        _buildQualityBar(profiles, cacheKey);
        fresh.classList.add('hls-btn-active');
        const rawBtn = document.getElementById('hls-btn-raw');
        if (rawBtn) rawBtn.classList.remove('hls-btn-active');
        const sm = document.getElementById('hls-status-msg');
        if (sm) sm.textContent = '';
    });
}


/**
 * Unmute the <video> element inside <video-player> after autoplay starts.
 * Browsers require muted for programmatic autoplay.
 */
function _unmuteWhenReady(playerEl) {
    if (!playerEl) return;
    let attempts = 0;
    const poll = setInterval(() => {
        if (++attempts > 100) { clearInterval(poll); return; }
        const video = playerEl.querySelector('video[slot="media"]');
        if (!video) return;
        clearInterval(poll);

        function doPlayUnmuted() {
            // Unmute first, then play — if play() is blocked by autoplay policy
            // we fall back to muted play so at least the video starts
            video.muted = false;
            video.volume = 1;
            video.play().catch(() => {
                // Browser blocked unmuted autoplay — play muted as fallback
                video.muted = true;
                video.play().catch(() => { });
            });
        }

        if (video.readyState >= 1) {
            doPlayUnmuted();
        } else {
            video.addEventListener('loadedmetadata', doPlayUnmuted, { once: true });
        }
    }, 50);
}

/**
 * Build Auto/1080p/720p/360p quality bar using direct <video> src swaps.
 * No VJS API needed — the <video> element is in the light DOM.
 */
function _buildQualityBar(profiles, cacheKey) {
    const row = document.getElementById('hls-quality-row');
    if (!row || !profiles || profiles.length < 2) return;

    row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:4px 8px;flex-wrap:wrap;';
    row.innerHTML = '';

    const label = document.createElement('span');
    label.textContent = 'Quality:';
    label.style.cssText = 'color:rgba(255,255,255,0.55);font-size:12px;user-select:none;margin-right:2px;';
    row.appendChild(label);

    function makeBtn(text, src) {
        const btn = document.createElement('button');
        btn.className = 'hls-quality-btn' + (text === 'Auto' ? ' hls-quality-active' : '');
        btn.textContent = text;
        btn.addEventListener('click', () => {
            const playerEl = document.querySelector('#hls-player-area video-player');
            if (!playerEl) return;
            const video = playerEl.querySelector('video[slot="media"]');
            if (!video) return;
            const wasPaused = video.paused;
            const currentTime = video.currentTime;
            video.src = src;
            video.load();
            video.addEventListener('loadedmetadata', () => {
                if (currentTime > 0) { try { video.currentTime = currentTime; } catch (_) { } }
                if (!wasPaused) video.play().catch(() => { });
                video.muted = false;
                video.volume = 1;
            }, { once: true });
            row.querySelectorAll('.hls-quality-btn').forEach(b => b.classList.remove('hls-quality-active'));
            btn.classList.add('hls-quality-active');
        });
        return btn;
    }

    // Sort: highest resolution first; at same height, HFR (60fps) before standard.
    // e.g.  2160p60 > 2160p > 1440p60 > 1440p > 1080p60 > 1080p > 720p60 > 720p > 480p > …
    function profileSortKey(name) {
        const m = name.match(/^(\d+)p(\d+)?/);
        const height = m ? parseInt(m[1], 10) : 0;
        const fps = m && m[2] ? parseInt(m[2], 10) : 0;
        return height * 1000 + fps;   // higher is "better"
    }

    row.appendChild(makeBtn('Auto', `/hls_files/${cacheKey}/master.m3u8`));
    const sorted = [...profiles].sort((a, b) => profileSortKey(b) - profileSortKey(a));
    sorted.forEach(p => row.appendChild(makeBtn(p, `/hls_files/${cacheKey}/${p}/index.m3u8`)));
}

function _attachQualitySelector(playerEl) {
    // no-op stub — quality bar is built via _buildQualityBar(profiles, cacheKey)
}

function _hlsSleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
// ─────────────────────────────────────────────────────────────────────────────
// End HLS helpers
// ─────────────────────────────────────────────────────────────────────────────