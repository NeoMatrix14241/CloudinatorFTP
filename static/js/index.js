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
});

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
        // Make a quick authentication check
        const response = await fetch('/admin/upload_status', {
            method: 'GET',
            cache: 'no-cache',
            headers: {
                'Cache-Control': 'no-cache'
            }
        });

        // If we get redirected to login or get a 401/403, we're not authenticated
        if (!response.ok || response.url.includes('/login')) {
            console.log('🔒 Not authenticated, redirecting to login...');
            window.location.replace('/login');
            return;
        }

        console.log('✅ Authentication verified');
    } catch (error) {
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
    setInterval(checkAuthenticationStatus, 30000); // Check every 30 seconds
}

async function checkAuthenticationStatus() {
    try {
        const response = await fetch('/admin/upload_status', {
            method: 'GET',
            cache: 'no-cache',
            headers: {
                'Cache-Control': 'no-cache'
            }
        });

        if (!response.ok || response.url.includes('/login')) {
            console.log('🔒 Session expired, redirecting to login...');
            window.location.replace('/login');
        }
    } catch (error) {
        console.log('🔒 Session check failed, redirecting to login...');
        window.location.replace('/login');
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
    const table = document.getElementById('filesTable');
    const tbody = table.querySelector('tbody');
    const rows = tbody.querySelectorAll('tr');
    let visibleCount = 0;

    const term = searchTerm.toLowerCase().trim();

    // Hide any deep search results first
    hideDeepSearchResults();

    rows.forEach(row => {
        // Skip parent directory row
        if (row.style.background === 'rgba(52, 152, 219, 0.1)' ||
            row.innerHTML.includes('.. (Parent Directory)')) {
            return;
        }

        if (!term) {
            // No search term - show all rows
            row.classList.remove('hidden-by-search');
            removeHighlights(row);
            visibleCount++;
        } else {
            // Get searchable text from the row
            const nameCell = row.querySelector('td:nth-child(2)');
            const typeCell = row.querySelector('td:nth-child(4)');

            let searchableText = '';
            if (nameCell) searchableText += nameCell.textContent.toLowerCase() + ' ';
            if (typeCell) searchableText += typeCell.textContent.toLowerCase() + ' ';

            if (searchableText.includes(term)) {
                row.classList.remove('hidden-by-search');
                highlightSearchTerm(row, term);
                visibleCount++;
            } else {
                row.classList.add('hidden-by-search');
                removeHighlights(row);
            }
        }
    });

    // Update visible count
    updateVisibleCount(visibleCount);

    console.log(`🔍 Local search for "${term}" found ${visibleCount} items`);
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

function performSearch(searchTerm) {
    const table = document.getElementById('filesTable');
    const tbody = table.querySelector('tbody');
    const rows = tbody.querySelectorAll('tr');
    let visibleCount = 0;

    const term = searchTerm.toLowerCase().trim();

    rows.forEach(row => {
        // Skip parent directory row
        if (row.style.background === 'rgba(52, 152, 219, 0.1)' ||
            row.innerHTML.includes('.. (Parent Directory)')) {
            return;
        }

        if (!term) {
            // No search term - show all rows
            row.classList.remove('hidden-by-search');
            removeHighlights(row);
            visibleCount++;
        } else {
            // Get searchable text from the row
            const nameCell = row.querySelector('td:nth-child(2)');
            const typeCell = row.querySelector('td:nth-child(4)');

            let searchableText = '';
            if (nameCell) searchableText += nameCell.textContent.toLowerCase() + ' ';
            if (typeCell) searchableText += typeCell.textContent.toLowerCase() + ' ';

            if (searchableText.includes(term)) {
                row.classList.remove('hidden-by-search');
                highlightSearchTerm(row, term);
                visibleCount++;
            } else {
                row.classList.add('hidden-by-search');
                removeHighlights(row);
            }
        }
    });

    // Update visible count
    const visibleCountSpan = document.getElementById('visibleCount');
    if (visibleCountSpan) {
        visibleCountSpan.textContent = visibleCount;
    }

    console.log(`🔍 Search for "${term}" found ${visibleCount} items`);
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
function sortTable(column) {
    const table = document.getElementById('filesTable');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));

    // Update sort state
    if (currentSort.column === column) {
        currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
    } else {
        currentSort.column = column;
        currentSort.direction = 'asc';
    }

    // Update header styles
    updateSortHeaders(column, currentSort.direction);

    // Separate parent directory row and file rows
    const parentRow = rows.find(row =>
        row.style.background === 'rgba(52, 152, 219, 0.1)' ||
        row.innerHTML.includes('.. (Parent Directory)')
    );
    const fileRows = rows.filter(row => row !== parentRow);

    // Sort function that replicates Windows Explorer behavior
    const sortFunction = (a, b) => {
        const aValue = getSortValue(a, column);
        const bValue = getSortValue(b, column);
        const aIsFolder = a.querySelector('.fa-folder, .folder-icon') && !a.querySelector('a[href*="/download/"]');
        const bIsFolder = b.querySelector('.fa-folder, .folder-icon') && !b.querySelector('a[href*="/download/"]');

        // WINDOWS EXPLORER RULE: For ALL columns, always group folders first, then files
        if (aIsFolder && !bIsFolder) {
            return currentSort.direction === 'asc' ? -1 : 1;
        }
        if (!aIsFolder && bIsFolder) {
            return currentSort.direction === 'asc' ? 1 : -1;
        }

        // Both are same type - now sort by the selected column
        let comparison;
        if (column === 'name') {
            // If both are same type, sort alphabetically
            comparison = aValue.localeCompare(bValue, undefined, {
                numeric: true,
                sensitivity: 'base'
            });
        } else if (column === 'size') {
            comparison = compareSizes(aValue, bValue);
        } else if (column === 'modified') {
            comparison = compareDates(aValue, bValue);
        } else if (column === 'type') {
            comparison = aValue.localeCompare(bValue, undefined, { numeric: true, sensitivity: 'base' });
        }

        return currentSort.direction === 'asc' ? comparison : -comparison;
    };

    // Sort all file rows together using Windows Explorer logic
    fileRows.sort(sortFunction);

    // Clear tbody and re-add rows in Windows Explorer order
    tbody.innerHTML = '';

    // Add parent row first if it exists
    if (parentRow) {
        tbody.appendChild(parentRow);
    }

    // Add all sorted file rows (folders and files mixed, but folders first when names are equal)
    fileRows.forEach(row => tbody.appendChild(row));

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

    // Clear deep search results first (fixes green background timing display)
    hideDeepSearchResults();

    // Clear search input and hide clear button
    const searchInput = document.getElementById('tableSearch');
    const clearButton = document.getElementById('clearSearch');
    if (searchInput) {
        searchInput.value = '';
    }
    if (clearButton) {
        clearButton.style.display = 'none';
    }

    // Reset sort state
    currentSort = { column: null, direction: 'asc' };

    // Reset all header styles
    document.querySelectorAll('.sortable').forEach(header => {
        header.classList.remove('sort-asc', 'sort-desc');
        const icon = header.querySelector('.sort-icon');
        if (icon) icon.className = 'fas fa-sort sort-icon';
    });

    // Restore original order from stored state
    const table = document.getElementById('filesTable');
    const tbody = table.querySelector('tbody');

    if (originalRowOrder.length > 0) {
        // Use stored original order
        console.log('✅ Restoring from stored original order');
        tbody.innerHTML = '';

        // Add all original rows back in their original order
        originalRowOrder.forEach(row => {
            tbody.appendChild(row.cloneNode(true));
        });
    } else {
        // Fallback: manual sorting if original order not stored
        console.log('⚠️ Fallback: manual sorting since original order not stored');
        const rows = Array.from(tbody.querySelectorAll('tr'));

        // Separate parent directory row and file rows
        const parentRow = rows.find(row =>
            row.style.background === 'rgba(52, 152, 219, 0.1)' ||
            row.innerHTML.includes('.. (Parent Directory)')
        );
        const fileRows = rows.filter(row => row !== parentRow);

        // Separate folders and files (like Windows Explorer)
        const folders = [];
        const files = [];

        fileRows.forEach(row => {
            // Check if it's a folder by looking for folder icon specifically
            const hasFolderIcon = row.querySelector('.fa-folder, .folder-icon');
            const hasFileIcon = row.querySelector('.fa-file');
            const hasDownloadLink = row.querySelector('a[href*="/download/"]');

            // More precise folder detection: must have folder icon AND no download link
            if (hasFolderIcon && !hasDownloadLink) {
                folders.push(row);
            } else {
                files.push(row);
            }
        });

        // Sort both folders and files by name as default order
        const defaultSort = (a, b) => {
            const aName = getSortValue(a, 'name');
            const bName = getSortValue(b, 'name');
            return aName.localeCompare(bName, undefined, { numeric: true, sensitivity: 'base' });
        };

        folders.sort(defaultSort);
        files.sort(defaultSort);

        // Clear tbody and re-add rows in Windows Explorer order
        tbody.innerHTML = '';

        // Add parent row first if it exists
        if (parentRow) {
            tbody.appendChild(parentRow);
        }

        // Add folders first, then files (like Windows Explorer)
        folders.forEach(row => tbody.appendChild(row));
        files.forEach(row => tbody.appendChild(row));
    }

    // Update sort info display
    updateSortInfo(null, null);

    // Reset the data-loaded attribute on all dir-info-cell spans so they reload
    document.querySelectorAll('.dir-info-cell').forEach(cell => {
        cell.dataset.loaded = 'false';
        cell.innerHTML = '<i class="fas fa-spinner fa-spin" style="color: #95a5a6;"></i>';
    });

    // Reload directory info cells (size column)
    loadDirInfoCells();

    console.log('✅ Table sorting reset to default order');
}

// Reinitialize table controls after content update
function reinitializeTableControls(itemCount) {
    // Update visible count
    const visibleCountSpan = document.getElementById('visibleCount');
    if (visibleCountSpan) {
        visibleCountSpan.textContent = itemCount;
    }

    // Clear any existing search if the search input has content
    const searchInput = document.getElementById('tableSearch');
    if (searchInput && searchInput.value.trim()) {
        performSearch(searchInput.value.trim());
    }

    // Reapply current sort if any
    if (currentSort.column) {
        const column = currentSort.column;
        const direction = currentSort.direction;
        // Reset sort state to trigger a fresh sort
        currentSort.column = null;
        sortTable(column);
    }

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
}

// Upload queue management
let uploadQueue = [];
let isUploading = false;
let currentUploadIndex = 0;
let currentUploadingFile = null;
let cancelledUploads = new Set(); // Track cancelled upload IDs
let uploadStartTime = 0;
let totalBytesToUpload = 0;
let totalBytesUploaded = 0;

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
            console.error(`❌ Response not OK: ${response.status} ${response.statusText}`);
            throw new Error(`Failed to load folder: ${response.status} ${response.statusText}`);
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
        console.error('❌ === NAVIGATION ERROR ===');
        console.error('❌ Error details:', error);
        console.error('❌ Error stack:', error.stack);
        showUploadStatus(`❌ Failed to load folder: ${error.message}`, 'error');

        // Fallback to page reload on error
        setTimeout(() => {
            console.log(`🔄 Fallback: Reloading page...`);
            window.location.href = newPath ? `/${newPath}` : '/';
        }, 2000);
    }
}

// Handle browser back/forward buttons
window.addEventListener('popstate', function (event) {
    const path = event.state?.path || '';
    console.log('🔄 POPSTATE EVENT FIRED - Browser back/forward navigation to:', path);
    navigateToFolder(path);
});

// Update file table with new content
function updateFileTable(files, path) {
    console.log(`🔄 === UPDATE FILE TABLE START ===`);
    console.log(`🔄 Files param:`, files);
    console.log(`🔄 Files type:`, typeof files);
    console.log(`🔄 Files isArray:`, Array.isArray(files));
    console.log(`🔄 Files length:`, files ? files.length : 'null/undefined');
    console.log(`🔄 Path param: "${path}"`);

    const tbody = document.querySelector('#filesTable tbody');
    if (!tbody) {
        console.error('❌ File table body not found');
        console.error('❌ Available tbody elements:', document.querySelectorAll('tbody'));
        console.error('❌ Available filesTable:', document.querySelector('#filesTable'));
        return;
    }

    console.log(`✅ File table body found:`, tbody);

    // Clear existing content (including search results)
    console.log(`🧹 Clearing search results...`);
    hideDeepSearchResults();
    console.log(`🧹 Clearing table content...`);
    tbody.innerHTML = '';

    console.log(`📝 Adding parent directory row for path: "${path}"`);

    // Add parent directory row if not at root
    if (path) {
        const parentPath = path.split('/').slice(0, -1).join('/');
        console.log(`📝 Parent path calculated: "${parentPath}"`);
        const parentRow = document.createElement('tr');
        parentRow.style.background = 'rgba(52, 152, 219, 0.1)';
        parentRow.innerHTML = `
            <td></td>
            <td>
                <div class="file-name">
                    <i class="fas fa-level-up-alt file-icon folder-icon"></i>
                    <a href="#" onclick="navigateToFolder('${parentPath}'); return false;" 
                       class="folder-link">
                        .. (Parent Directory)
                    </a>
                </div>
            </td>
            <td class="size-cell">
                <span style="color: white; font-size: 13px;"></span>
            </td>
            <td class="type-cell">
                <span class="file-type">
                    <i class="fas fa-arrow-up"></i> Parent Directory
                </span>
            </td>
            <td class="date-cell">
                <span style="color: white; font-size: 13px;"></span>
            </td>
            <td></td>
        `;
        tbody.appendChild(parentRow);
        console.log(`✅ Added parent directory row`);
    }

    // Check if files array is valid
    if (!files || !Array.isArray(files)) {
        console.warn(`⚠️ Invalid files data:`, files);
        console.warn(`⚠️ Will show empty folder message`);
        // Add empty folder message
        const emptyRow = createEmptyFolderRow();
        tbody.appendChild(emptyRow);
        reinitializeTableControls(0);
        console.log(`📋 === UPDATE FILE TABLE COMPLETE (EMPTY) ===`);
        return;
    }

    // Add files to table
    if (files.length === 0) {
        console.log(`📂 Folder is empty, adding empty message`);
        const emptyRow = createEmptyFolderRow();
        tbody.appendChild(emptyRow);
    } else {
        console.log(`📁 Adding ${files.length} files to table...`);
        files.forEach((item, index) => {
            console.log(`📄 Adding file ${index + 1}:`, item);
            const row = createFileTableRow(item, path);
            tbody.appendChild(row);
        });
    }

    console.log(`📋 Updated file table with ${files.length} items`);

    // Store the new original order for this folder (so reset sort works correctly)
    console.log(`💾 Storing original table order for current folder...`);
    storeOriginalTableOrder();
    
    // Reset sort state when navigating to a new folder
    console.log(`🔄 Resetting sort state...`);
    currentSort = { column: null, direction: 'asc' };
    
    // Reset sort header styles
    document.querySelectorAll('.sortable').forEach(header => {
        header.classList.remove('sort-asc', 'sort-desc');
        const icon = header.querySelector('.sort-icon');
        if (icon) icon.className = 'fas fa-sort sort-icon';
    });

    // Reinitialize sort functionality for new content
    console.log(`🔄 Reinitializing table controls...`);
    reinitializeTableControls(files.length);

    // Lazy-load folder sizes after table is rendered
    loadDirInfoCells();

    console.log(`📋 === UPDATE FILE TABLE COMPLETE ===`);
}

// Create empty folder message row
function createEmptyFolderRow() {
    const row = document.createElement('tr');
    row.className = 'empty-folder-row';
    row.innerHTML = `
        <td colspan="6" style="text-align: center; padding: 40px 20px; color: white;">
            <div style="opacity: 0.6;">
                <i class="fas fa-folder-open" style="font-size: 48px; margin-bottom: 15px; display: block;"></i>
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
        <td>
            <div class="file-name">
                ${item.is_dir ?
            `<i class="fas fa-folder file-icon folder-icon"></i>
                     <a href="#" onclick="navigateToFolder('${escapeHtml(itemPath)}'); return false;" 
                        data-folder-path="${escapeHtml(itemPath)}" class="folder-link">
                         ${safeName}
                     </a>` :
            `<i class="${itemIcon} file-icon file-icon-default" style="color: ${getFileColor(item.name)}"></i>
                     ${safeName}`
        }
            </div>
        </td>
        <td>
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
        <td>
            ${item.modified ?
            `<span class="file-date" style="color: white; font-size: 13px;">${new Date(item.modified * 1000).toLocaleString()}</span>` :
            '<span style="color: white; font-size: 13px;">--</span>'
        }
        </td>
        <td>
            <div class="actions">
                ${!item.is_dir ?
            `<button type="button" class="btn btn-outline btn-sm download-btn" 
                             data-item-path="${itemPath}"
                             onclick="downloadItem('${itemPath}')"
                             title="Download file">
                         <i class="fas fa-download"></i> Download
                     </button>` :
            `<button type="button" class="btn btn-outline btn-sm download-btn" 
                             data-item-path="${itemPath}"
                             onclick="downloadFolderAsZip('${itemPath}', '${item.name}')"
                             title="Download folder as ZIP">
                         <i class="fas fa-download"></i> Download
                     </button>`
        }
                
                ${USER_ROLE === 'readwrite' ? `
                <button type="button" class="btn btn-warning btn-sm move-btn" 
                        data-item-name="${item.name}"
                        data-item-path="${itemPath}"
                        onclick="showSingleMoveModal('${itemPath}', '${item.name}')"
                        title="Move item">
                    <i class="fas fa-cut"></i> Move
                </button>
                
                <button type="button" class="btn btn-success btn-sm copy-btn" 
                        data-item-name="${item.name}"
                        data-item-path="${itemPath}"
                        onclick="showSingleCopyModal('${itemPath}', '${item.name}')"
                        title="Copy item">
                    <i class="fas fa-copy"></i> Copy
                </button>
                
                <button type="button" class="btn btn-primary btn-sm rename-btn" 
                        data-item-name="${item.name}"
                        data-item-path="${itemPath}"
                        onclick="showSingleRenameModal('${itemPath}', '${item.name}')"
                        title="Rename item">
                    <i class="fas fa-edit"></i> Rename
                </button>
                
                <button type="button" class="btn btn-danger btn-sm delete-btn" 
                        data-item-name="${item.name}"
                        data-item-path="${itemPath}"
                        onclick="showSingleDeleteModal('${itemPath}', '${item.name}')"
                        title="Delete item">
                    <i class="fas fa-trash"></i> Delete
                </button>
                ` : ''}
            </div>
        </td>
    `;

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
        // Use raw path in URL — do NOT encodeURIComponent as it encodes slashes
        // and breaks Flask's <path:path> route matcher
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

// Enhanced page visibility handling with better interruption detection
document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
        // Page is being hidden - cleanup if needed
        if (!isUploading && uploadQueue.some(item => item.status === 'pending' || item.status === 'error')) {
            console.log('🧹 Page hidden - cleaning up abandoned uploads');
            cleanupUnfinishedChunks().catch(console.error);
        }
    } else if (document.visibilityState === 'visible') {
        // Page became visible again - check for any server-side cleanup needed
        console.log('👀 Page visible again - checking upload status');
        updateManualCleanupButton();
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
    console.log('📂 addFilesToQueue called with:', files.length, 'files');
    let addedCount = 0;

    files.forEach(file => {
        // Determine the destination path for the file
        let destinationPath = currentPath;
        let displayName = file.name;

        // If file has relativePath (from folder upload), preserve folder structure
        // Support both webkitRelativePath (desktop) and relativePath (mobile fallback)
        const folderPath = file.relativePath || file.webkitRelativePath;
        if (folderPath) {
            // Remove leading slash and get directory path
            const relativePath = folderPath.startsWith('/') ? folderPath.slice(1) : folderPath;
            const pathParts = relativePath.split('/');

            // Remove the filename to get just the directory structure
            pathParts.pop();

            if (pathParts.length > 0) {
                // Combine current path with relative directory structure
                const relativeDir = pathParts.join('/');
                destinationPath = currentPath ? `${currentPath}/${relativeDir}` : relativeDir;
                displayName = `${relativeDir}/${file.name}`;
            }

            console.log('📁 Folder file:', file.name, 'Path source:', file.relativePath ? 'relativePath' : 'webkitRelativePath', 'Value:', folderPath, 'Destination:', destinationPath);
        } else {
            console.log('📄 Regular file:', file.name, 'Size:', file.size);
        }

        const fileId = generateFileId(file);

        // Check if file already in queue by relative path and size
        const existingFile = uploadQueue.find(item =>
            (item.destinationPath === destinationPath && item.name === file.name && item.size === file.size) ||
            (item.displayName === displayName && item.size === file.size)
        );

        if (existingFile) {
            console.log('⚠️ File already in queue:', displayName);
            showUploadStatus(`📁 File "${displayName}" is already in the queue`, 'info');
            return;
        }

        const queueItem = {
            id: fileId,
            file: file,
            name: file.name, // original filename
            displayName: displayName, // display name with path
            destinationPath: destinationPath, // where to upload the file
            size: file.size,
            status: 'pending',
            progress: 0,
            error: null,
            uploadedBytes: 0,
            createdTime: Date.now()
        };

        uploadQueue.push(queueItem);
        addedCount++;
        console.log('✅ Added to queue:', displayName, 'ID:', fileId);
    });

    console.log('📊 Queue status - Total items:', uploadQueue.length, 'Added:', addedCount);
    updateQueueDisplay();
    showUploadStatus(`➕ Added ${addedCount} file(s) to upload queue`, 'success');
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

function generateFileId(file) {
    // Only remove slashes, preserve all other characters (including +, spaces, etc.)
    // This ensures uniqueness for files like "OC Extreme+.html" and "OC+.html"
    const safeName = file.name.replace(/[\/\\]/g, '');
    return `${Date.now()}-${safeName}-${file.size}`;
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

    // Cleanup all pending/error items
    const itemsToCleanup = uploadQueue.filter(item =>
        item.status === 'pending' || item.status === 'error'
    );

    uploadQueue = [];
    updateQueueDisplay();

    // Cleanup chunks in background
    if (itemsToCleanup.length > 0) {
        cleanupUnfinishedChunks(itemsToCleanup).catch(console.error);
    }

    showUploadStatus('🧹 Upload queue cleared', 'success');
}

function clearCompletedItems() {
    console.log('🧹 Clearing completed items from queue');

    // Count completed items before clearing
    const completedCount = uploadQueue.filter(item =>
        item.status === 'completed' ||
        item.status === 'assembled' ||
        (item.error && item.error.includes('File ready!'))
    ).length;

    if (completedCount === 0) {
        showUploadStatus('ℹ️ No completed items to clear', 'info');
        return;
    }

    // Remove completed items from queue
    uploadQueue = uploadQueue.filter(item =>
        item.status !== 'completed' &&
        item.status !== 'assembled' &&
        !(item.error && item.error.includes('File ready!'))
    );

    updateQueueDisplay();
    showUploadStatus(`🧹 Cleared ${completedCount} completed item${completedCount > 1 ? 's' : ''}`, 'success');
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

    if (uploadQueue.length === 0) {
        queueContainer.classList.remove('show');
        if (uploadBtn) uploadBtn.disabled = true;
        if (progressSummary) progressSummary.classList.remove('show');
        return;
    }

    queueContainer.classList.add('show');

    // Update stats
    const totalSize = uploadQueue.reduce((sum, item) => sum + item.size, 0);
    const pendingCount = uploadQueue.filter(item => item.status === 'pending').length;

    // Count unique folders
    const folders = new Set();
    uploadQueue.forEach(item => {
        if (item.destinationPath && item.destinationPath !== currentPath) {
            // Get the root folder name from the path
            const pathParts = item.destinationPath.split('/');
            if (pathParts.length > 0) {
                folders.add(pathParts[0]);
            }
        }
    });

    let statsText = `(${uploadQueue.length} files, ${formatFileSize(totalSize)})`;
    if (folders.size > 0) {
        statsText = `(${uploadQueue.length} files from ${folders.size} folder${folders.size > 1 ? 's' : ''}, ${formatFileSize(totalSize)})`;
    }

    if (statsElement) statsElement.textContent = statsText;
    if (countElement) countElement.textContent = pendingCount;
    if (uploadBtn) uploadBtn.disabled = pendingCount === 0 || isUploading;

    // Show progress summary if uploading
    if (isUploading && progressSummary) {
        progressSummary.classList.add('show');
        updateProgressSummary();
    }

    // Update queue items
    if (queueElement) {
        queueElement.innerHTML = '';
        uploadQueue.forEach(item => {
            const queueItemElement = createQueueItemElement(item);
            queueElement.appendChild(queueItemElement);
        });
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

    console.log(`🏷️ Creating queue item for ${item.name}: status=${item.status}, label=${statusLabel}`);

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

    if (totalBytesToUpload === 0) return;

    const currentTime = Date.now();
    const elapsedTime = (currentTime - uploadStartTime) / 1000; // seconds
    const uploadSpeed = elapsedTime > 0 ? totalBytesUploaded / elapsedTime : 0;
    const remainingBytes = totalBytesToUpload - totalBytesUploaded;
    const eta = uploadSpeed > 0 ? remainingBytes / uploadSpeed : 0;
    const overallProgress = (totalBytesUploaded / totalBytesToUpload) * 100;

    if (totalSizeElement) totalSizeElement.textContent = formatFileSize(totalBytesToUpload);
    if (uploadedSizeElement) uploadedSizeElement.textContent = formatFileSize(totalBytesUploaded);
    if (uploadSpeedElement) uploadSpeedElement.textContent = formatFileSize(uploadSpeed) + '/s';
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

    // Documents & Text
    e(['txt', 'rtf', 'doc', 'docx', 'odt', 'pdf', 'tex', 'log', 'csv', 'tsv', 'md', 'xml', 'json', 'ini', 'cfg', 'yaml', 'yml', 'nfo', 'readme', 'wps', 'dot', 'dotx'], 'Document', 'fas fa-file-alt', '#34495e');

    // Spreadsheets & Data
    e(['xls', 'xlsx', 'ods', 'db', 'mdb', 'accdb', 'sqlite', 'sqlite3', 'sql', 'sav', 'dat', 'dbf', 'parquet', 'arff', 'rdata', 'dta', 'pivot'], 'Spreadsheet / Data', 'fas fa-file-excel', '#27ae60');

    // Presentations
    e(['ppt', 'pptx', 'odp', 'key', 'pub', 'msg', 'eml', 'oft', 'note'], 'Presentation / Mail', 'fas fa-file-powerpoint', '#e67e22');

    // Images
    e(['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tif', 'tiff', 'ico', 'svg', 'webp', 'heic', 'heif', 'psd', 'psb', 'ai', 'eps', 'ind', 'indd', 'idml', 'xcf', 'cpt', 'exr', 'hdr', 'raw', 'nef', 'cr2', 'arw', 'dng', 'sketch', 'fig', 'xd'], 'Image', 'fas fa-file-image', '#9b59b6');

    // Video
    e(['mp4', 'avi', 'mov', 'wmv', 'mkv', 'flv', 'webm', 'mpeg', 'mpg', 'm4v', '3gp', 'mxf', 'f4v', 'vob', 'swf', 'blend', 'aep', 'prproj', 'drp', 'veg'], 'Video', 'fas fa-file-video', '#e74c3c');

    // Audio
    e(['mp3', 'wav', 'ogg', 'flac', 'wma', 'aac', 'm4a', 'mid', 'midi', 'aiff', 'aif', 'oma', 'pcm', 'stem'], 'Audio', 'fas fa-file-audio', '#f39c12');

    // 3D / CAD
    e(['dwg', 'dxf', 'dwf', 'dwt', 'dgn', 'rvt', 'rfa', 'rte', 'ifc', 'step', 'stp', 'stl', 'iges', 'igs', 'sldprt', 'sldasm', 'ipt', 'iam', 'f3d', 'fbx', 'obj', '3ds', 'max', 'skp', 'plt', 'cam', 'cnc', 'nc', 'scad'], '3D / CAD', 'fas fa-cube', '#16a085');

    // Dev / Code
    e(['py', 'ipynb', 'js', 'jsx', 'ts', 'tsx', 'html', 'htm', 'css', 'java', 'class', 'jar', 'c', 'cpp', 'h', 'hpp', 'cs', 'vb', 'php', 'asp', 'aspx', 'jsp', 'go', 'rb', 'pl', 'sh', 'bat', 'cmd', 'ps1', 'lua', 'sql', 'yaml', 'yml', 'toml', 'r', 'm', 'scala', 'kt', 'swift', 'rs', 'jsonl', 'env', 'config', 'jsonc'], 'Code / Script', 'fas fa-code', '#2ecc71');

    // Archives
    e(['zip', 'rar', '7z', 'tar', 'gz', 'gzip', 'bz2', 'tgz', 'iso', 'img', 'cab', 'arj', 'lzh', 'pkg'], 'Archive', 'fas fa-file-archive', '#95a5a6');

    // Executables & System
    e(['exe', 'msi', 'bat', 'cmd', 'ps1', 'vbs', 'dll', 'sys', 'drv', 'ocx', 'reg', 'inf', 'scr', 'com', 'cpl'], 'Executable / System', 'fas fa-cogs', '#7f8c8d');

    // Web
    e(['map', 'sitemap', 'url', 'lnk', 'cache', 'cookie'], 'Web / Shortcut', 'fas fa-globe', '#3498db');

    // Security / Certs
    e(['cer', 'crt', 'pem', 'pfx', 'p12', 'key', 'csr', 'enc', 'sig', 'asc'], 'Certificate / Key', 'fas fa-shield-alt', '#c0392b');

    // Project / Config
    e(['project', 'workspace', 'sln', 'solution', 'config', 'settings', 'prefs', 'manifest', 'lock', 'jsonc'], 'Project / Config', 'fas fa-folder-tree', '#34495e');

    // Backups / Logs / Misc
    e(['tmp', 'bak', 'old', 'log', 'err', 'torrent', 'dmp', 'cache', 'backup', 'copy'], 'Backup / Log / Temp', 'fas fa-file', '#95a5a6');

    // Specialized enterprise
    e(['pst', 'ost', 'ics', 'vcf', 'contact', 'form', 'template', 'report', 'policy', 'license', 'audit', 'script', 'blueprint', 'model', 'sim'], 'Enterprise / Specialized', 'fas fa-file-alt', '#9b59b6');

    // Default PDF mapping (also included above) ensure 'pdf' explicit
    map['pdf'] = { type: 'PDF Document', icon: 'fas fa-file-pdf', color: '#e74c3c' };

    return map;
})();

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

function updateItemProgress(fileId, progress, uploadedBytes = 0) {
    const item = uploadQueue.find(item => item.id === fileId);
    if (item) {
        item.progress = progress;
        item.uploadedBytes = uploadedBytes;

        // Update UI
        const element = document.querySelector(`[data-file-id="${fileId}"]`);
        if (element) {
            const progressBar = element.querySelector('.progress-fill-small');
            const progressText = element.querySelector('.file-info-meta span:nth-child(3)');

            if (progressBar) {
                progressBar.style.width = progress + '%';
            }
            if (progressText) {
                progressText.innerHTML = `<i class="fas fa-percentage"></i> ${progress}%`;
            }
        }

        // Update overall progress
        updateOverallProgress();
    }
}

function updateOverallProgress() {
    totalBytesUploaded = uploadQueue.reduce((sum, item) => sum + item.uploadedBytes, 0);
    updateProgressSummary();
}

function updateItemStatus(fileId, status, error = null) {
    console.log(`🔄 updateItemStatus called: ${fileId} -> ${status}`, error);
    const item = uploadQueue.find(item => item.id === fileId);
    if (item) {
        console.log(`✅ Found item for status update: ${item.name}, old status: ${item.status}, new status: ${status}`);
        item.status = status;
        item.error = error;

        // Mark completion time for cleanup
        if (status === 'completed' || status === 'error') {
            item.completedTime = Date.now();
            console.log(`⏰ Set completion time for ${item.name}: ${item.completedTime}`);

            // Auto-remove completed items after 5 seconds
            // Let startBatchUpload handle cleanup after all files are done.
            // setTimeout(() => {
            //     console.log(`🧹 Auto-removing completed item: ${item.name}`);
            //     removeFromQueue(item.id);
            // }, 5000);
        }

        console.log(`🔄 Calling updateQueueDisplay after status update`);
        updateQueueDisplay();
        console.log(`✅ updateQueueDisplay completed for ${item.name}`);
    } else {
        console.error(`❌ Item not found for status update: ${fileId}`);
    }
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

        // Update the file table with new data
        updateFileTableContent(data.files);

        const endTime = Date.now();
        console.log(`✅ refreshFileTable() completed in ${endTime - startTime}ms`);

        console.log('✅ File table refreshed successfully');

    } catch (error) {
        console.error('❌ Failed to refresh file table:', error);
        showUploadStatus('❌ Failed to refresh file list, reloading page...', 'error');
        // Fallback to page reload if AJAX fails
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

    // Reset all selection state when updating table content
    selectedItems.clear();
    const selectAllCheckbox = document.getElementById('selectAll');
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
    }
    const bulkActions = document.getElementById('bulkActions');
    if (bulkActions) {
        bulkActions.classList.remove('show');
    }

    // Use currentPath from navigation state, not CURRENT_PATH from page load
    const pathToUse = currentPath || '';
    console.log(`📁 updateFileTableContent using path: "${pathToUse}"`);

    // Add "Go Up" row if we're not at root
    if (pathToUse) {
        const parentPath = pathToUse.includes('/')
            ? pathToUse.split('/').slice(0, -1).join('/')
            : '';

        const goUpRow = document.createElement('tr');
        goUpRow.style.background = 'rgba(52, 152, 219, 0.1)';
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
                        title="Download folder as ZIP">
                    <i class="fas fa-download"></i> Download
                </button>
                
                ${USER_ROLE === 'readwrite' ? `
                <button type="button" class="btn btn-warning btn-sm" 
                        data-action="move"
                        data-item-name="${file.name}"
                        data-item-path="${itemPath}"
                        title="Move item">
                    <i class="fas fa-cut"></i> Move
                </button>
                
                <button type="button" class="btn btn-success btn-sm" 
                        data-action="copy"
                        data-item-name="${file.name}"
                        data-item-path="${itemPath}"
                        title="Copy item">
                    <i class="fas fa-copy"></i> Copy
                </button>
                
                <button type="button" class="btn btn-primary btn-sm" 
                        data-action="rename"
                        data-item-name="${file.name}"
                        data-item-path="${itemPath}"
                        title="Rename item">
                    <i class="fas fa-edit"></i> Rename
                </button>
                
                <button type="button" class="btn btn-danger btn-sm" 
                        data-action="delete"
                        data-item-name="${file.name}"
                        data-item-path="${itemPath}"
                        title="Delete item">
                    <i class="fas fa-trash"></i> Delete
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
                        title="Download file">
                    <i class="fas fa-download"></i> Download
                </button>
                ${USER_ROLE === 'readwrite' ? `
                    <button type="button" class="btn btn-warning btn-sm" 
                            data-action="move"
                            data-item-name="${file.name}"
                            data-item-path="${itemPath}"
                            title="Move item">
                        <i class="fas fa-cut"></i> Move
                    </button>
                    
                    <button type="button" class="btn btn-success btn-sm" 
                            data-action="copy"
                            data-item-name="${file.name}"
                            data-item-path="${itemPath}"
                            title="Copy item">
                        <i class="fas fa-copy"></i> Copy
                    </button>
                    
                    <button type="button" class="btn btn-primary btn-sm" 
                            data-action="rename"
                            data-item-name="${file.name}"
                            data-item-path="${itemPath}"
                            title="Rename item">
                        <i class="fas fa-edit"></i> Rename
                    </button>
                    
                    <button type="button" class="btn btn-danger btn-sm" 
                            data-action="delete"
                            data-item-name="${file.name}"
                            data-item-path="${itemPath}"
                            title="Delete item">
                        <i class="fas fa-trash"></i> Delete
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
                           onchange="updateSelection()">
                ` : ''}
            </td>
            <td>
                <div class="file-name">
                    ${iconHtml}
                </div>
            </td>
            <td>${sizeHtml}</td>
            <td class="type-cell">${typeHtml}</td>
            <td>
                ${file.modified ?
                `<span style="color: white; font-size: 13px; white-space: nowrap;">${formatTimestamp(file.modified)}</span>` :
                `<span style="color: white; font-size: 13px;">--</span>`
            }
            </td>
            <td>
                <div class="actions">
                    ${actionsHtml}
                </div>
            </td>
        `;

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
        return date.toLocaleDateString('en-US') + ' ' +
            date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
        return '--';
    }
}

async function startBatchUpload() {
    console.log('🚀 startBatchUpload called, isUploading:', isUploading);

    if (isUploading) {
        console.log('❌ Already uploading, returning');
        return;
    }

    const pendingFiles = uploadQueue.filter(item => item.status === 'pending');
    console.log('📋 Pending files count:', pendingFiles.length);
    console.log('📋 Total queue size:', uploadQueue.length);

    if (pendingFiles.length === 0) {
        console.log('❌ No files to upload');
        showUploadStatus('❌ No files to upload', 'error');
        return;
    }

    console.log('✅ Starting upload process...');
    isUploading = true;
    currentUploadIndex = 0;
    uploadStartTime = Date.now();
    totalBytesToUpload = pendingFiles.reduce((sum, item) => sum + item.size, 0);
    totalBytesUploaded = 0;

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

        if (PARALLEL_UPLOAD_CONFIG.enableParallelUploads) {
            await startParallelUploads(pendingFiles);
        } else {
            await startSequentialUploads(pendingFiles);
        }

        const completedCount = uploadQueue.filter(item => item.status === 'completed').length;
        const errorCount = uploadQueue.filter(item => item.status === 'error').length;
        const cancelledCount = uploadQueue.filter(item => item.status === 'cancelled').length;

        // Ensure overall progress is set to 100% after all uploads
        totalBytesUploaded = totalBytesToUpload;
        updateProgressSummary();

        if (errorCount === 0 && cancelledCount === 0) {
            showUploadStatus(
                `🎉 All files uploaded successfully! (${completedCount} files)`,
                'success'
            );

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

            console.log(`🧹 Auto-cleared ${itemsToRemove.length} finished items from queue`);

            if (uploadQueue.length === 0) {
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
        isUploading = false;
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

// Parallel upload implementation
async function startParallelUploads(pendingFiles) {
    console.log(`⚡ Starting parallel uploads with max concurrency: ${PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads}`);

    const fileQueue = [...pendingFiles]; // Copy array to avoid mutations
    let completedCount = 0;
    let errorCount = 0;

    // Create upload worker function
    const uploadWorker = async () => {
        while (fileQueue.length > 0) {
            const item = fileQueue.shift();
            if (!item || cancelledUploads.has(item.id)) continue;

            console.log(`⚡ Worker starting upload: ${item.name} (${completedCount + errorCount + 1}/${pendingFiles.length})`);

            try {
                // Update status to uploading
                updateItemStatus(item.id, 'uploading');
                PARALLEL_UPLOAD_CONFIG.activeUploads.add(item.id);

                showUploadStatus(
                    `⬆️ Uploading "${item.name}" (${PARALLEL_UPLOAD_CONFIG.activeUploads.size} active, ${completedCount}/${pendingFiles.length} completed)`,
                    'info'
                );

                await uploadSingleFile(item);

                // Check if this item is now assembling (chunked upload with assembly queued)
                const currentItem = uploadQueue.find(queueItem => queueItem.id === item.id);
                if (currentItem && currentItem.status === 'assembling') {
                    // Don't overwrite assembling status - keep it as is
                    console.log(`🔄 Upload completed but keeping assembling status for ${item.name}`);
                } else {
                    // Regular completion for non-chunked or non-assembly uploads
                    updateItemStatus(item.id, 'completed');
                }

                PARALLEL_UPLOAD_CONFIG.activeUploads.delete(item.id);
                PARALLEL_UPLOAD_CONFIG.completedUploads.add(item.id);
                completedCount++;
                cancelledUploads.delete(item.id);

                console.log(`✅ Parallel upload completed: ${item.name} (${completedCount}/${pendingFiles.length})`);

                showUploadStatus(
                    `✅ "${item.name}" uploaded (${completedCount}/${pendingFiles.length} completed)`,
                    'success'
                );

            } catch (error) {
                console.error(`❌ Parallel upload failed for ${item.name}:`, error);
                updateItemStatus(item.id, 'error', error.message);
                PARALLEL_UPLOAD_CONFIG.activeUploads.delete(item.id);
                errorCount++;
                cancelledUploads.delete(item.id);

                showUploadStatus(
                    `❌ Failed: "${item.name}" - ${error.message} (${errorCount} errors)`,
                    'error'
                );
            }
        }
    };

    // Start multiple workers based on concurrency setting
    const workers = [];
    const workerCount = Math.min(PARALLEL_UPLOAD_CONFIG.maxConcurrentUploads, pendingFiles.length);

    console.log(`⚡ Starting ${workerCount} upload workers`);

    for (let i = 0; i < workerCount; i++) {
        workers.push(uploadWorker());
    }

    // Wait for all workers to complete
    await Promise.all(workers);

    console.log(`⚡ All parallel upload workers completed. Success: ${completedCount}, Errors: ${errorCount}`);
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

        showUploadStatus(
            `⬆️ Uploading "${item.name}" (${currentUploadIndex}/${pendingFiles.length})`,
            'info'
        );

        try {
            console.log(`📤 Starting upload for: ${item.name}`);
            await uploadSingleFile(item);
            console.log(`✅ Upload completed for: ${item.name}`);
            updateItemStatus(item.id, 'completed');
            currentUploadingFile = null;
            cancelledUploads.delete(item.id);

            showUploadStatus(
                `✅ "${item.name}" uploaded successfully (${currentUploadIndex}/${pendingFiles.length})`,
                'success'
            );

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
    console.log('🚀 Starting upload for:', item.name, 'Size:', item.file.size, 'Chunk size:', CHUNK_SIZE);

    // Check for cancellation before starting
    if (cancelledUploads.has(item.id)) {
        console.log(`🚫 Upload already cancelled for ${item.name}`);
        throw new Error('Upload cancelled by user');
    }

    const file = item.file;
    const destPath = item.destinationPath || document.getElementById('destPath').value || '';

    try {
        if (file.size <= CHUNK_SIZE) {
            console.log('📦 Using whole file upload for:', item.name);
            // Upload whole file
            const formData = new FormData();
            formData.append('filename', file.name);
            formData.append('dest_path', destPath);
            formData.append('file', file);

            const response = await fetch(UPLOAD_URL, {
                method: 'POST',
                body: formData
            });

            console.log('📦 Upload response status for', item.name, ':', response.status);

            if (!response.ok) {
                const errorText = await response.text();
                console.error('❌ Upload error response for', item.name, ':', errorText);
                throw new Error(errorText);
            }

            updateItemProgress(item.id, 100, file.size);
            console.log('✅ Whole file upload completed for:', item.name, 'Progress set to 100%');

        } else {
            console.log('🧩 Using chunked upload for:', item.name);
            // Chunked upload
            const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
            console.log('🧩 Total chunks for', item.name, ':', totalChunks);

            for (let i = 0; i < totalChunks; i++) {
                // Check if upload was cancelled (multiple checks for responsiveness)
                if (cancelledUploads.has(item.id)) {
                    console.log(`🚫 Upload cancelled for ${item.name} at chunk ${i + 1}/${totalChunks}`);
                    throw new Error('Upload cancelled by user');
                }

                const currentItem = uploadQueue.find(queueItem => queueItem.id === item.id);
                if (!currentItem || currentItem.status === 'cancelled') {
                    console.log(`🚫 Upload cancelled for ${item.name} at chunk ${i + 1}/${totalChunks}`);
                    throw new Error('Upload cancelled by user');
                }

                const start = i * CHUNK_SIZE;
                const end = Math.min(file.size, start + CHUNK_SIZE);
                const chunk = file.slice(start, end);

                console.log(`📤 Uploading chunk ${i + 1}/${totalChunks} for ${item.name}, size: ${chunk.size}`);

                const formData = new FormData();
                formData.append('file_id', item.id);
                formData.append('chunk_num', i);
                formData.append('total_chunks', totalChunks);
                formData.append('filename', file.name);
                formData.append('dest_path', destPath);
                formData.append('chunk', chunk);

                // Final check before sending chunk
                if (cancelledUploads.has(item.id)) {
                    console.log(`🚫 Upload cancelled for ${item.name} before sending chunk ${i + 1}/${totalChunks}`);
                    throw new Error('Upload cancelled by user');
                }

                const response = await fetch(UPLOAD_URL, {
                    method: 'POST',
                    body: formData
                });

                console.log(`📤 Chunk ${i + 1} response status for ${item.name}:`, response.status);

                if (!response.ok) {
                    const errorText = await response.text();
                    console.error(`❌ Chunk ${i + 1} error for ${item.name}:`, errorText);
                    throw new Error(`Chunk ${i + 1}/${totalChunks}: ${errorText}`);
                }

                // Check if this is the last chunk and handle assembly
                if (i === totalChunks - 1) {
                    try {
                        const responseData = await response.json();
                        if (responseData.assembly_queued) {
                            console.log(`🔄 Assembly queued for ${item.name}, starting status polling`);
                            updateItemProgress(item.id, 100, file.size);
                            updateItemStatus(item.id, 'assembling', 'Processing file...');

                            // Immediately protect this assembly job from cleanup
                            try {
                                await fetch(`/api/protect_assembly/${item.id}`, { method: 'POST' });
                                console.log(`🔐 Protected new assembly job ${item.id} from cleanup`);
                            } catch (protectError) {
                                console.warn(`⚠️ Failed to protect new assembly job ${item.id}:`, protectError);
                            }

                            startAssemblyPolling(item.id);

                            // Update cleanup button to disable it during assembly
                            updateManualCleanupButton();
                        } else {
                            // Fallback for old response format
                            updateItemProgress(item.id, 100, file.size);
                        }
                    } catch (jsonError) {
                        // Response wasn't JSON, treat as success for backward compatibility
                        console.log(`✅ Chunk ${i + 1} completed (legacy response) for ${item.name}`);
                        updateItemProgress(item.id, 100, file.size);
                    }
                } else {
                    const progress = Math.round(((i + 1) / totalChunks) * 100);
                    const uploadedBytes = end;
                    updateItemProgress(item.id, progress, uploadedBytes);
                    console.log(`✅ Chunk ${i + 1} completed for ${item.name}, progress: ${progress}%`);
                }
            }

            console.log('🎉 Chunked upload completed for:', item.name, 'All chunks processed');
        }
        console.log('✅ uploadSingleFile function completing successfully for:', item.name);
    } catch (error) {
        console.error('❌ Upload failed for:', item.name, error);
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
    const itemCheckboxes = document.querySelectorAll('.item-checkbox');

    if (!selectAllCheckbox || itemCheckboxes.length === 0) {
        console.warn('⚠️ Select all checkbox or item checkboxes not found');
        return;
    }

    // The checkbox state has already been changed by the browser when this function is called
    const isNowChecked = selectAllCheckbox.checked;
    const wasIndeterminate = selectAllCheckbox.indeterminate;

    console.log('🔄 toggleSelectAll called, new checkbox state:', {
        checked: isNowChecked,
        wasIndeterminate: wasIndeterminate
    });

    // Clear indeterminate state since we're making a definitive selection
    selectAllCheckbox.indeterminate = false;

    // Apply the same state to all item checkboxes
    selectedItems.clear();

    itemCheckboxes.forEach(checkbox => {
        checkbox.checked = isNowChecked;
        const row = checkbox.closest('tr');
        if (isNowChecked) {
            row.classList.add('selected');
            selectedItems.add(checkbox.dataset.path);
        } else {
            row.classList.remove('selected');
        }
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

    console.log(`✅ ${isNowChecked ? 'Selected' : 'Deselected'} all ${itemCheckboxes.length} items`);
}

function updateSelection() {
    const itemCheckboxes = document.querySelectorAll('.item-checkbox');
    const selectAllCheckbox = document.getElementById('selectAll');
    const bulkActions = document.getElementById('bulkActions');
    const selectedCount = document.getElementById('selectedCount');

    selectedItems.clear();
    let checkedCount = 0;

    itemCheckboxes.forEach(checkbox => {
        const row = checkbox.closest('tr');
        if (checkbox.checked) {
            checkedCount++;
            selectedItems.add(checkbox.dataset.path);
            row.classList.add('selected');
        } else {
            row.classList.remove('selected');
        }
    });

    console.log(`📊 Selection update: ${checkedCount}/${itemCheckboxes.length} items selected`);

    if (selectAllCheckbox) {
        if (checkedCount === 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        } else if (checkedCount === itemCheckboxes.length) {
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

    // Populate selected items list
    if (selectedItemsList) {
        selectedItemsList.innerHTML = '';
        selectedItems.forEach(path => {
            const li = document.createElement('li');
            li.textContent = path.split('/').pop(); // Show just filename
            selectedItemsList.appendChild(li);
        });
    }

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

    // Populate selected items list
    if (selectedItemsList) {
        selectedItemsList.innerHTML = '';
        selectedItems.forEach(path => {
            const li = document.createElement('li');
            li.textContent = path.split('/').pop(); // Show just filename
            selectedItemsList.appendChild(li);
        });
    }

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

            // CRITICAL: Immediately update selectedItems with new path
            // Don't wait for file monitor - backend confirmed the rename!
            const parentPath = oldPath.includes('/')
                ? oldPath.split('/').slice(0, -1).join('/')
                : '';
            const newPath = parentPath ? `${parentPath}/${newName}` : newName;

            // Update selection immediately
            selectedItems.delete(oldPath);
            selectedItems.add(newPath);

            console.log(`✅ Updated selection: "${oldPath}" → "${newPath}"`);

            // Clear checkboxes to avoid confusion (optional)
            const selectAllCheckbox = document.getElementById('selectAll');
            if (selectAllCheckbox) {
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = false;
            }

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

function confirmMoveOrCopy() {
    // Use browserCurrentPath instead of text input
    const destinationPath = browserCurrentPath || '';
    const selectedPaths = Array.from(selectedItems);

    if (selectedPaths.length === 0) {
        showNotification('No Selection', 'No items selected', 'error');
        return;
    }

    // Check if trying to move/copy to the same location
    const currentLocation = currentPath || '';
    if (destinationPath === currentLocation) {
        showNotification('Same Location', `Cannot ${currentModalAction} items to the same location`, 'error');
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

    showConfirmationModal(
        `Confirm ${actionName}`,
        confirmMessage,
        actionName,
        confirmClass,
        icon
    ).then((confirmed) => {
        if (!confirmed) return;

        // Perform the action
        if (currentModalAction === 'move') {
            performBulkMove(selectedPaths, destinationPath);
        } else if (currentModalAction === 'copy') {
            performBulkCopy(selectedPaths, destinationPath);
        }

        closeModal();
    });
}

function isValidPath(path) {
    // Basic path validation
    return !/[<>:"|?*\\]/.test(path) && !path.includes('..');
}

async function performBulkMove(paths, destination) {
    try {
        const response = await fetch('/bulk_move', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paths: paths,
                destination: destination,
                current_path: currentPath || ''
            })
        });

        const result = await response.json();

        if (response.ok) {
            showNotification('Move Successful', `Successfully moved ${result.moved_count} item(s)`, 'success');
            // Clear selection first, then refresh file table
            clearSelection();
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

async function performBulkCopy(paths, destination) {
    try {
        const response = await fetch('/bulk_copy', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paths: paths,
                destination: destination,
                current_path: currentPath || ''
            })
        });

        const result = await response.json();

        if (response.ok) {
            showNotification('Copy Successful', `Successfully copied ${result.copied_count} item(s)`, 'success');
            // Clear selection first, then refresh file table
            clearSelection();
            await refreshFileTable();
            // Refresh storage stats after copy (new files created, size increased)
            refreshStorageStats('copy operation');
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
    try {
        const response = await fetch('/bulk_delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paths: paths
            })
        });

        const result = await response.json();

        if (response.ok) {
            showUploadStatus(`🗑️ Successfully deleted ${result.deleted_count} item(s)`, 'success');
            // Clear selection first, then refresh file table
            clearSelection();
            await refreshFileTable();
            // Refresh storage stats after bulk delete (multiple files removed, size decreased)
            refreshStorageStats('bulk delete operation');
        } else {
            showUploadStatus(`❌ Bulk delete failed: ${result.error}`, 'error');
        }
    } catch (error) {
        showUploadStatus(`❌ Bulk delete failed: ${error.message}`, 'error');
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
    try {
        const response = await fetch('/delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: `target_path=${encodeURIComponent(itemPath)}`
        });

        console.log('Delete response:', response.status);

        if (response.ok) {
            showUploadStatus(`🗑️ Successfully deleted "${itemName}"`, 'success');
            // Clear selection and refresh file table
            clearSelection();
            await refreshFileTable();
        } else {
            const errorText = await response.text();
            showUploadStatus(`❌ Failed to delete "${itemName}": ${errorText}`, 'error');
        }
    } catch (error) {
        console.error('Delete error:', error);
        showUploadStatus(`❌ Delete failed: ${error.message}`, 'error');
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

        // --- Cleanup Cache button ---
        const cacheBtn = document.createElement('button');
        cacheBtn.id = 'cleanupCacheBtn';
        cacheBtn.className = 'btn btn-warning btn-sm manual-cleanup-btn';
        cacheBtn.innerHTML = '<i class="fas fa-database"></i> Cleanup Cache';
        cacheBtn.title = 'Delete storage_index.json and rebuild the index from scratch';

        cacheBtn.onclick = async function () {
            if (!confirm('This will delete the storage index cache and rebuild it from scratch.\nThe server will re-scan all files — this may take a few seconds.\n\nContinue?')) {
                return;
            }
            try {
                cacheBtn.disabled = true;
                cacheBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Rebuilding...';
                const response = await fetch('/admin/cleanup_cache', {
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
                cacheBtn.innerHTML = '<i class="fas fa-database"></i> Cleanup Cache';
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
    } else if (isAndroid) {
        console.log('📱 Android detected: Drag & drop disabled due to limited browser support');
    }

    // Click functionality works on all devices
    if (fileInputDisplay && fileInput) {
        fileInputDisplay.addEventListener('click', function () {
            if (currentUploadMode === 'files') {
                fileInput.click();
            } else {
                folderInput.click();
            }
        });

        // Update file input display when files are selected
        fileInput.addEventListener('change', function (e) {
            handleInputChange(e, 'file');
        });

        // Update folder input display when folders are selected
        if (folderInput) {
            folderInput.addEventListener('change', function (e) {
                handleInputChange(e, 'folder');
            });
        }
    }

    function handleInputChange(e, type) {
        const files = Array.from(e.target.files);
        if (files.length > 0) {
            // Mobile webkitRelativePath fallback - Android often doesn't populate this properly
            if (type === 'folder' && isMobile) {
                console.log('📱 Mobile folder upload detected - checking webkitRelativePath support');

                // Check if any files have webkitRelativePath
                const hasRelativePath = files.some(f => f.webkitRelativePath);

                if (!hasRelativePath && files.length > 0) {
                    console.log('⚠️ Mobile browser not providing webkitRelativePath - applying folder structure fallback');

                    // Create a folder name based on timestamp for this batch
                    const timestamp = new Date().toISOString().slice(0, 19).replace(/[:\-]/g, '').replace('T', '_');
                    const folderName = `MobileUpload_${timestamp}`;

                    // Manually set relativePath for mobile to preserve folder structure
                    files.forEach(file => {
                        if (!file.relativePath && !file.webkitRelativePath) {
                            file.relativePath = `${folderName}/${file.name}`;
                            console.log(`📱 Mobile fallback: Set relativePath for ${file.name} -> ${file.relativePath}`);
                        }
                    });

                    showUploadStatus(`📱 Mobile: Files grouped into folder "${folderName}"`, 'info');
                } else if (hasRelativePath) {
                    console.log('✅ Mobile browser supports webkitRelativePath');
                }
            }

            // Process files and add to queue
            addFilesToQueue(files);

            const display = document.querySelector('.file-input-display');
            if (display) {
                let itemType, actionText;
                if (type === 'folder') {
                    // For folders, show number of files from folders
                    itemType = files.length === 1 ? 'file from folder' : 'files from folders';
                    actionText = 'Click again to add more folders, or drag multiple folders from Explorer';

                    // Show helpful notification for folder mode
                    // Support both webkitRelativePath and mobile fallback relativePath
                    const folderCount = new Set(files.map(f => {
                        const path = f.webkitRelativePath || f.relativePath;
                        return path ? path.split('/')[0] : 'Unknown';
                    })).size;
                    if (folderCount > 0) {
                        setTimeout(() => {
                            showUploadStatus(`📁 Added ${files.length} files from ${folderCount} folder${folderCount > 1 ? 's' : ''}. Click again to add more folders!`, 'success');
                        }, 100);
                    }
                } else {
                    itemType = files.length === 1 ? 'file' : 'files';
                    actionText = 'Click again to add more files';
                }

                display.innerHTML = `
                    <i class="fas fa-plus-circle" style="font-size: 20px; color: #27ae60;"></i>
                    <div>
                        <strong>Added ${files.length} ${itemType} to queue</strong>
                        <div style="font-size: 12px; opacity: 0.8; margin-top: 5px;">
                            ${actionText}
                        </div>
                    </div>
                `;
                display.style.borderColor = '#27ae60';
                display.style.backgroundColor = 'rgba(39, 174, 96, 0.1)';

                // Reset after 3 seconds for folder mode (longer to read the message)
                const resetTime = type === 'folder' ? 3000 : 2000;
                setTimeout(() => {
                    updateFileInputDisplay(currentUploadMode);
                    display.style.borderColor = 'rgba(255, 255, 255, 0.4)';
                    display.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
                }, resetTime);
            }

            // Reset input for future selections - this is KEY for multiple folder selection
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
        const allFiles = [];
        const processingPromises = [];

        console.log(`📁 Drag & drop: Processing ${dt.items.length} items`);

        // Process all dropped items and collect promises
        for (let i = 0; i < dt.items.length; i++) {
            const item = dt.items[i];

            if (item.kind === 'file') {
                const entry = item.webkitGetAsEntry();

                if (entry) {
                    if (entry.isFile) {
                        // Single file
                        const file = item.getAsFile();
                        if (file) {
                            console.log(`📄 Adding file: ${file.name}`);
                            allFiles.push(file);
                        }
                    } else if (entry.isDirectory) {
                        console.log(`📁 Processing directory: ${entry.name}`);
                        // Directory - add promise to process it
                        const dirPromise = readDirectory(entry).then(dirFiles => {
                            console.log(`📁 Directory ${entry.name} contains ${dirFiles.length} files`);
                            return dirFiles;
                        });
                        processingPromises.push(dirPromise);
                    }
                }
            }
        }

        // Wait for all directories to be processed
        if (processingPromises.length > 0) {
            console.log(`⏳ Waiting for ${processingPromises.length} directories to be processed...`);
            try {
                const directoryResults = await Promise.all(processingPromises);
                // Flatten all directory results and add to allFiles
                directoryResults.forEach(dirFiles => {
                    allFiles.push(...dirFiles);
                });
            } catch (error) {
                console.error('❌ Error processing directories:', error);
                showUploadStatus('❌ Error processing some folders. Try again.', 'error');
                return;
            }
        }

        if (allFiles.length > 0) {
            console.log(`✅ Drag & drop complete: Found ${allFiles.length} total files`);

            // Count unique folders for feedback
            const folders = new Set();
            allFiles.forEach(file => {
                if (file.relativePath) {
                    const parts = file.relativePath.split('/');
                    if (parts.length > 1) {
                        folders.add(parts[0]); // First part is the root folder name
                    }
                }
            });

            showUploadStatus(`📁 Dropped ${allFiles.length} files from ${folders.size} folder${folders.size !== 1 ? 's' : ''}`, 'success');
            addFilesToQueue(allFiles);
        } else {
            console.log('⚠️ No files found in dropped items');
            showUploadStatus('⚠️ No files found in dropped items', 'info');
        }
    } else {
        // Fallback for browsers that don't support webkitGetAsEntry
        console.log('📁 Using fallback file handling');
        const files = Array.from(dt.files);
        if (files.length > 0) {
            addFilesToQueue(files);
        }
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

// Check cleanup button state periodically
setInterval(() => {
    updateManualCleanupButton();
}, 5000); // Check every 5 seconds

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
    console.log('🧹 Checking for completed items to auto-clear...');

    // Count completed items before clearing
    const completedItems = uploadQueue.filter(item =>
        item.status === 'completed' ||
        item.status === 'assembled' ||
        (item.error && item.error.includes('File ready!'))
    );

    if (completedItems.length === 0) {
        console.log('🧹 No completed items found for auto-cleanup');
        return;
    }

    console.log(`🧹 Found ${completedItems.length} completed items to auto-clear:`,
        completedItems.map(item => `${item.name} (${item.status})`));

    // Remove completed items from queue
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
            console.log('📡 Raw SSE message received:', event.data);

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
                console.log('📡 Parsed SSE data:', data);
                handleStorageUpdate(data);
            } catch (error) {
                console.warn('⚠️ Failed to parse SSE data:', error, event.data);
            }
        };

        storageEventSource.onerror = function (event) {
            console.error('❌ Storage stats stream error:', event);
            console.log('🔴 SSE onerror fired - connection failed');
            console.log('🔴 EventSource readyState:', storageEventSource.readyState);
            console.log('🔴 EventSource url:', storageEventSource.url);
            console.log('🔴 Event type:', event.type);
            console.log('🔴 Event target:', event.target);
            connectionStatus = 'error';

            // Add clean disconnection indicator
            document.title = '🔴 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
            console.log('🔴 Title set to error state');

            // Try a few SSE reconnects, then fall back to polling
            if (reconnectAttempts < 2) { // Reduced from 5 to 2 attempts
                reconnectAttempts++;
                console.log(`🔄 Attempting SSE reconnect (${reconnectAttempts}/2) in ${reconnectDelay}ms...`);
                setTimeout(() => {
                    connectToStorageStream();
                }, reconnectDelay);
            } else {
                console.error('💀 SSE reconnection failed, switching to polling fallback...');
                sseFailedPermanently = true;

                // Close SSE connection
                if (storageEventSource) {
                    storageEventSource.close();
                    storageEventSource = null;
                }

                // Start polling fallback
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
    console.log('📊 Real-time storage update received:', data);

    switch (data.type) {
        case 'connected':
            console.log('📡 SSE connection established');
            break;

        case 'storage_stats_update':
            console.log('🔄 Processing storage_stats_update...', data.data);

            // Brief flash to show SSE activity
            document.title = '⚡ ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
            setTimeout(() => {
                document.title = '🟢 ' + document.title.replace(/^🟢 |^🔴 |^🟠 |^⚡ /, '');
            }, 2000);

            if (data.data) {
                // Update storage display with real-time data
                updateStorageDisplay(data.data);

                // Update our tracked file counts
                if (data.data.file_count !== undefined) {
                    lastKnownFileCount = data.data.file_count;
                }
                if (data.data.dir_count !== undefined) {
                    lastKnownDirCount = data.data.dir_count;
                }

                // Check for file/folder changes and refresh table if needed
                // Skip change notifications for initial data (page load)
                if (data.data.changes && !data.initial) {
                    const changes = data.data.changes;
                    console.log('🔍 Changes detected:', changes);

                    // Refresh file table for ANY change including modifications and renames
                    // - files_changed/dirs_changed: for file/folder creation/deletion
                    // - size_changed: for file content modifications
                    // - content_changed: for file renames, modifications, permission changes
                    // - mtime_changed: for any file modifications
                    // Check if there are actual significant changes worth showing to user
                    const hasSignificantChanges = (
                        changes.files_changed !== 0 ||
                        changes.dirs_changed !== 0 ||
                        changes.size_changed !== 0
                    );

                    // Check if we should refresh the file table (broader criteria)
                    const shouldRefresh = (
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
                        // Use requestAnimationFrame for immediate, smooth UI update
                        requestAnimationFrame(async () => {
                            console.log('🔄 SSE triggered refreshFileTable() call starting...');
                            await refreshFileTable();
                            console.log('✅ SSE triggered refreshFileTable() completed!');
                        });

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
            console.log('📡 SSE keep-alive ping');
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