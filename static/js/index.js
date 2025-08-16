// Read Flask configuration from HTML data attributes (avoids VS Code parsing issues)
const configElement = document.getElementById('flask-config');
const CHUNK_SIZE = parseInt(configElement.dataset.chunkSize) || 10485760; // 10MB fallback
const UPLOAD_URL = configElement.dataset.uploadUrl || "/upload";
const CURRENT_PATH = configElement.dataset.currentPath || "";
const USER_ROLE = configElement.dataset.userRole || "readonly";

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

// Upload queue management
let uploadQueue = [];
let isUploading = false;
let currentUploadIndex = 0;
let currentUploadingFile = null;
let cancelledUploads = new Set(); // Track cancelled upload IDs
let uploadStartTime = 0;
let totalBytesToUpload = 0;
let totalBytesUploaded = 0;

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

window.addEventListener('beforeunload', function (e) {
    if (isUploading || uploadQueue.some(item => item.status === 'pending')) {
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
        console.log('📄 Processing file:', file.name, 'Size:', file.size);
        const fileId = generateFileId(file);

        // Check if file already in queue
        if (uploadQueue.find(item => item.id === fileId)) {
            console.log('⚠️ File already in queue:', file.name);
            showUploadStatus(`📁 File "${file.name}" is already in the queue`, 'info');
            return;
        }

        const queueItem = {
            id: fileId,
            file: file,
            name: file.name,
            size: file.size,
            status: 'pending',
            progress: 0,
            error: null,
            uploadedBytes: 0,
            createdTime: Date.now()
        };

        uploadQueue.push(queueItem);
        addedCount++;
        console.log('✅ Added to queue:', file.name, 'ID:', fileId);
    });

    console.log('📊 Queue status - Total items:', uploadQueue.length, 'Added:', addedCount);
    updateQueueDisplay();
    showUploadStatus(`➕ Added ${addedCount} file(s) to upload queue`, 'success');
}

function generateFileId(file) {
    return `${Date.now()}-${file.name}-${file.size}`.replace(/[^a-z0-9\-\.]/gi, '');
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

    if (statsElement) statsElement.textContent = `(${uploadQueue.length} files, ${formatFileSize(totalSize)})`;
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
        completed: 'fas fa-check-circle',
        error: 'fas fa-exclamation-circle',
        cancelled: 'fas fa-ban'
    };

    const statusLabels = {
        pending: 'Queued',
        uploading: 'Uploading',
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
                        <div class="file-info-name">${item.name}</div>
                        <div class="file-info-meta">
                            <span><i class="fas fa-weight-hanging"></i> ${formatFileSize(item.size)}</span>
                            <span><i class="fas fa-clock"></i> ${ageDisplay}</span>
                            ${item.status === 'uploading' ? `<span><i class="fas fa-percentage"></i> ${item.progress}%</span>` : ''}
                            ${item.error ? `<span><i class="fas fa-exclamation"></i> ${item.error}</span>` : ''}
                        </div>
                    </div>
                </div>
                <div class="file-status">
                    ${item.status === 'uploading' ? `
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
    const extension = filename.split('.').pop().toLowerCase();
    const iconMap = {
        pdf: 'fas fa-file-pdf',
        doc: 'fas fa-file-word', docx: 'fas fa-file-word',
        xls: 'fas fa-file-excel', xlsx: 'fas fa-file-excel',
        ppt: 'fas fa-file-powerpoint', pptx: 'fas fa-file-powerpoint',
        jpg: 'fas fa-file-image', jpeg: 'fas fa-file-image', png: 'fas fa-file-image',
        gif: 'fas fa-file-image', bmp: 'fas fa-file-image', svg: 'fas fa-file-image',
        mp4: 'fas fa-file-video', avi: 'fas fa-file-video', mkv: 'fas fa-file-video',
        mov: 'fas fa-file-video', wmv: 'fas fa-file-video',
        mp3: 'fas fa-file-audio', wav: 'fas fa-file-audio', flac: 'fas fa-file-audio',
        zip: 'fas fa-file-archive', rar: 'fas fa-file-archive', '7z': 'fas fa-file-archive',
        txt: 'fas fa-file-alt', md: 'fas fa-file-alt',
        html: 'fas fa-file-code', css: 'fas fa-file-code', js: 'fas fa-file-code',
        py: 'fas fa-file-code', java: 'fas fa-file-code'
    };
    return iconMap[extension] || 'fas fa-file';
}

function getFileColor(filename) {
    const extension = filename.split('.').pop().toLowerCase();
    const colorMap = {
        pdf: '#e74c3c',
        doc: '#3498db', docx: '#3498db',
        xls: '#27ae60', xlsx: '#27ae60',
        ppt: '#e67e22', pptx: '#e67e22',
        jpg: '#9b59b6', jpeg: '#9b59b6', png: '#9b59b6',
        gif: '#9b59b6', bmp: '#9b59b6', svg: '#9b59b6',
        mp4: '#e74c3c', avi: '#e74c3c', mkv: '#e74c3c',
        mp3: '#f39c12', wav: '#f39c12', flac: '#f39c12',
        zip: '#95a5a6', rar: '#95a5a6', '7z': '#95a5a6',
        txt: '#34495e', md: '#34495e',
        html: '#2ecc71', css: '#2ecc71', js: '#2ecc71',
        py: '#2ecc71', java: '#2ecc71'
    };
    return colorMap[extension] || '#7f8c8d';
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
            setTimeout(() => {
                console.log(`🧹 Auto-removing completed item: ${item.name}`);
                removeFromQueue(item.id);
            }, 5000);
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
    try {
        const currentPath = CURRENT_PATH || '';
        const response = await fetch(`/api/files/${currentPath}`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Failed to load files');
        }

        // Update the file table with new data
        updateFileTableContent(data.files);

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

    // Add "Go Up" row if we're not at root
    if (CURRENT_PATH) {
        const parentPath = CURRENT_PATH.includes('/')
            ? CURRENT_PATH.split('/').slice(0, -1).join('/')
            : '';

        const goUpRow = document.createElement('tr');
        goUpRow.style.background = 'rgba(52, 152, 219, 0.1)';
        goUpRow.innerHTML = `
                    <td></td>
                    <td>
                        <div class="file-name">
                            <i class="fas fa-level-up-alt file-icon" style="color: #3498db;"></i>
                            <a href="${parentPath ? '/' + parentPath : '/'}" style="color: #3498db; font-weight: 600;">
                                .. (Go Up)
                            </a>
                        </div>
                    </td>
                    <td><span style="color: #7f8c8d; font-size: 12px;">--</span></td>
                    <td><span class="file-type"><i class="fas fa-arrow-up"></i> Parent Directory</span></td>
                    <td><span style="color: #7f8c8d; font-size: 12px;">--</span></td>
                    <td><div class="actions"><span style="color: #7f8c8d; font-size: 12px;">Navigation</span></div></td>
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
                                <i class="fas fa-folder-open" style="font-size: 36px; color: #95a5a6; margin-bottom: 15px; opacity: 0.7;"></i>
                                <div style="color: #7f8c8d; font-weight: 500; margin-bottom: 8px; font-size: 18px;">This folder is empty</div>
                                <div style="color: #95a5a6; font-size: 14px; text-align: center; max-width: 300px;">
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
        row.setAttribute('data-path', CURRENT_PATH ? `${CURRENT_PATH}/${file.name}` : file.name);

        let iconHtml, sizeHtml, typeHtml, actionsHtml;

        if (file.is_dir || file.type === 'dir') {
            // Directory
            iconHtml = `<i class="fas fa-folder file-icon folder-icon"></i>
                                <a href="/${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}">${file.name}</a>`;

            sizeHtml = `<span style="color: #7f8c8d; font-size: 13px;">
                        ${file.item_count ? `${file.item_count.files || 0} files, ${file.item_count.dirs || 0} folders` : '--'}<br>
                        ${file.size ? formatFileSize(file.size) : '--'}
                    </span>`;

            typeHtml = `<i class="fas fa-folder"></i> Folder`;
            actionsHtml = USER_ROLE === 'readwrite' ? `
                        <button type="button" class="btn btn-warning btn-sm move-btn" 
                                data-item-name="${file.name}"
                                data-item-path="${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}"
                                onclick="showSingleMoveModal('${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}', '${file.name}')"
                                title="Move item">
                            <i class="fas fa-cut"></i> Move
                        </button>
                        
                        <button type="button" class="btn btn-success btn-sm copy-btn" 
                                data-item-name="${file.name}"
                                data-item-path="${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}"
                                onclick="showSingleCopyModal('${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}', '${file.name}')"
                                title="Copy item">
                            <i class="fas fa-copy"></i> Copy
                        </button>
                        
                        <button type="button" class="btn btn-primary btn-sm rename-btn" 
                                data-item-name="${file.name}"
                                data-item-path="${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}"
                                onclick="showSingleRenameModal('${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}', '${file.name}')"
                                title="Rename item">
                            <i class="fas fa-edit"></i> Rename
                        </button>
                        
                        <button type="button" class="btn btn-danger btn-sm delete-btn" 
                                data-item-name="${file.name}"
                                data-item-path="${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}"
                                onclick="showSingleDeleteModal('${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}', '${file.name}')"
                                title="Delete item">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    ` : '';
        } else {
            // File
            iconHtml = `<i class="fas fa-file file-icon file-icon-default"></i>${file.name}`;
            sizeHtml = `<span style="color: #2c3e50; font-weight: 500;">${formatFileSize(file.size)}</span>`;
            typeHtml = `<i class="fas fa-file"></i> File`;
            actionsHtml = `
                        <button type="button" class="btn btn-outline btn-sm download-btn" 
                                data-item-path="${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}"
                                onclick="downloadItem('${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}')"
                                title="Download file">
                            <i class="fas fa-download"></i> Download
                        </button>
                        ${USER_ROLE === 'readwrite' ? `
                            <button type="button" class="btn btn-warning btn-sm move-btn" 
                                    data-item-name="${file.name}"
                                    data-item-path="${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}"
                                    onclick="showSingleMoveModal('${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}', '${file.name}')"
                                    title="Move item">
                                <i class="fas fa-cut"></i> Move
                            </button>
                            
                            <button type="button" class="btn btn-success btn-sm copy-btn" 
                                    data-item-name="${file.name}"
                                    data-item-path="${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}"
                                    onclick="showSingleCopyModal('${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}', '${file.name}')"
                                    title="Copy item">
                                <i class="fas fa-copy"></i> Copy
                            </button>
                            
                            <button type="button" class="btn btn-primary btn-sm rename-btn" 
                                    data-item-name="${file.name}"
                                    data-item-path="${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}"
                                    onclick="showSingleRenameModal('${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}', '${file.name}')"
                                    title="Rename item">
                                <i class="fas fa-edit"></i> Rename
                            </button>
                            
                            <button type="button" class="btn btn-danger btn-sm delete-btn" 
                                    data-item-name="${file.name}"
                                    data-item-path="${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}"
                                    onclick="showSingleDeleteModal('${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}', '${file.name}')"
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
                                   data-path="${CURRENT_PATH ? CURRENT_PATH + '/' : ''}${file.name}" 
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
                    <td><span class="file-type">${typeHtml}</span></td>
                    <td>
                        ${file.modified ?
                `<span style="color: #7f8c8d; font-size: 13px; white-space: nowrap;">${formatTimestamp(file.modified)}</span>` :
                `<span style="color: #95a5a6; font-size: 13px;">--</span>`
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

    // Add event listeners to dynamically created action buttons
    if (USER_ROLE === 'readwrite') {
        // Delete buttons
        document.querySelectorAll('.delete-btn').forEach(button => {
            button.removeEventListener('click', handleDeleteClick);
            button.addEventListener('click', handleDeleteClick);
        });

        // Move buttons  
        document.querySelectorAll('.move-btn').forEach(button => {
            button.addEventListener('click', function () {
                const itemName = this.getAttribute('data-item-name');
                const itemPath = this.getAttribute('data-item-path');
                showSingleMoveModal(itemPath, itemName);
            });
        });

        // Copy buttons
        document.querySelectorAll('.copy-btn').forEach(button => {
            button.addEventListener('click', function () {
                const itemName = this.getAttribute('data-item-name');
                const itemPath = this.getAttribute('data-item-path');
                showSingleCopyModal(itemPath, itemName);
            });
        });

        // Rename buttons
        document.querySelectorAll('.rename-btn').forEach(button => {
            button.addEventListener('click', function () {
                const itemName = this.getAttribute('data-item-name');
                const itemPath = this.getAttribute('data-item-path');
                showSingleRenameModal(itemPath, itemName);
            });
        });

        // Add event listeners to checkboxes
        document.querySelectorAll('.item-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', updateSelection);
        });
    }

    // Download buttons (available for all roles)
    document.querySelectorAll('.download-btn').forEach(button => {
        button.addEventListener('click', function () {
            const itemPath = this.getAttribute('data-item-path');
            downloadItem(itemPath);
        });
    });

    // Update selection state to ensure UI is in sync
    updateSelection();
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

    const uploadBtn = document.getElementById('startUploadBtn');
    const clearBtn = document.getElementById('clearAllBtn');

    console.log('🔧 Upload button element:', uploadBtn);

    if (uploadBtn) {
        uploadBtn.disabled = true;
        uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading...';
    }
    if (clearBtn) clearBtn.disabled = true;

    // Hide manual cleanup button during upload
    updateManualCleanupButton();

    try {
        showUploadStatus(`🚀 Starting batch upload of ${pendingFiles.length} files...`, 'info');

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
                console.log(`🔄 About to call updateItemStatus with 'completed' for: ${item.name} (${item.id})`);
                updateItemStatus(item.id, 'completed');
                currentUploadingFile = null;
                cancelledUploads.delete(item.id); // Clean up cancellation flag
                console.log(`✅ updateItemStatus called for: ${item.name}`);

                showUploadStatus(
                    `✅ "${item.name}" uploaded successfully (${currentUploadIndex}/${pendingFiles.length})`,
                    'success'
                );

            } catch (error) {
                console.error(`❌ Upload failed for ${item.name}:`, error);
                updateItemStatus(item.id, 'error', error.message);
                currentUploadingFile = null;
                cancelledUploads.delete(item.id); // Clean up cancellation flag

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

        const completedCount = uploadQueue.filter(item => item.status === 'completed').length;
        const errorCount = uploadQueue.filter(item => item.status === 'error').length;
        const pendingCount = uploadQueue.filter(item => item.status === 'pending').length;

        if (errorCount === 0) {
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
                `📊 Batch upload completed: ${completedCount} successful, ${errorCount} failed`,
                'info'
            );
        }

        // Auto-clear completed items after upload batch finishes
        console.log('🧹 Auto-clearing completed items in 3 seconds...');
        setTimeout(() => {
            // Remove completed and error items
            const itemsToRemove = uploadQueue.filter(item =>
                item.status === 'completed' || item.status === 'error'
            );

            itemsToRemove.forEach(item => {
                removeFromQueue(item.id);
            });

            console.log(`🧹 Auto-cleared ${itemsToRemove.length} finished items from queue`);

            // Only show message if queue is completely empty
            if (uploadQueue.length === 0) {
                showUploadStatus('✨ Upload queue cleared automatically', 'success');
            } else {
                const remainingPending = uploadQueue.filter(item => item.status === 'pending').length;
                console.log(`📋 ${remainingPending} files still pending in queue`);
            }
        }, 3000); // Wait 3 seconds to let user see the completed status

    } catch (error) {
        console.error('❌ Batch upload error:', error);
        showUploadStatus(`❌ Batch upload failed: ${error.message}`, 'error');
    } finally {
        isUploading = false;
        if (uploadBtn) {
            uploadBtn.disabled = false;
            uploadBtn.innerHTML = '<i class="fas fa-upload"></i> Upload All (<span id="uploadCount">0</span>)';
        }
        if (clearBtn) clearBtn.disabled = false;

        // Show manual cleanup button after upload completes
        updateManualCleanupButton();

        updateQueueDisplay();
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
    const destPath = document.getElementById('destPath').value || '';

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

                const progress = Math.round(((i + 1) / totalChunks) * 100);
                const uploadedBytes = end;
                updateItemProgress(item.id, progress, uploadedBytes);
                console.log(`✅ Chunk ${i + 1} completed for ${item.name}, progress: ${progress}%`);
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

    if (modal) modal.classList.add('show');
}

function closeModal() {
    const modal = document.getElementById('moveModal');
    if (modal) modal.classList.remove('show');

    // Reset form
    const destinationPath = document.getElementById('destinationPath');
    if (destinationPath) destinationPath.value = '';
}

function showRenameModal() {
    if (selectedItems.size === 0) {
        showNotification('No Selection', 'Please select an item to rename', 'error');
        return;
    }

    if (selectedItems.size > 1) {
        showNotification('Multiple Selection', 'Only one item can be renamed at a time. Please select a single item.', 'error');
        return;
    }

    const selectedPath = Array.from(selectedItems)[0];
    const itemName = selectedPath.split('/').pop(); // Get just the filename

    const modal = document.getElementById('renameModal');
    const newItemNameInput = document.getElementById('newItemName');
    const currentItemNameDiv = document.getElementById('currentItemName');

    if (newItemNameInput) {
        newItemNameInput.value = itemName; // Pre-fill with current name
        newItemNameInput.focus();
        // Select the name part without extension for easy editing
        const lastDotIndex = itemName.lastIndexOf('.');
        if (lastDotIndex > 0) {
            newItemNameInput.setSelectionRange(0, lastDotIndex);
        } else {
            newItemNameInput.select();
        }
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

async function confirmRename() {
    const newName = document.getElementById('newItemName').value.trim();
    const selectedPath = Array.from(selectedItems)[0];

    if (!newName) {
        showNotification('Invalid Name', 'Please enter a valid name', 'error');
        return;
    }

    if (newName === selectedPath.split('/').pop()) {
        showNotification('Same Name', 'The new name is the same as the current name', 'info');
        closeRenameModal();
        return;
    }

    // Validate new name
    if (!isValidFilename(newName)) {
        showNotification('Invalid Name', 'Invalid filename. Avoid special characters like <, >, :, ", |, ?, *, \\', 'error');
        return;
    }

    await performRename(selectedPath, newName);
    closeRenameModal();
}

function isValidFilename(filename) {
    // Check for invalid filename characters
    return !/[<>:"|?*\\\/]/.test(filename) && filename !== '.' && filename !== '..';
}

async function performRename(oldPath, newName) {
    try {
        showUploadStatus('🔄 Renaming item...', 'info');

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

        if (result.success) {
            showUploadStatus(`✅ Successfully renamed to "${newName}"`, 'success');

            // Clear selection and refresh
            clearSelection();
            await refreshFileTable();
        } else {
            showUploadStatus(`❌ Rename failed: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('Rename error:', error);
        showUploadStatus('❌ Network error during rename', 'error');
    }
}

// Single-item action functions for individual action buttons
function downloadItem(itemPath) {
    window.location.href = `/download/${itemPath}`;
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
    const destinationPath = document.getElementById('destinationPath').value.trim();
    const selectedPaths = Array.from(selectedItems);

    if (selectedPaths.length === 0) {
        showNotification('No Selection', 'No items selected', 'error');
        return;
    }

    // Validate destination path
    if (destinationPath && !isValidPath(destinationPath)) {
        showNotification('Invalid Path', 'Invalid destination path. Use forward slashes and avoid special characters.', 'error');
        return;
    }

    // Perform the action
    if (currentModalAction === 'move') {
        performBulkMove(selectedPaths, destinationPath);
    } else if (currentModalAction === 'copy') {
        performBulkCopy(selectedPaths, destinationPath);
    }

    closeModal();
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
                current_path: CURRENT_PATH
            })
        });

        const result = await response.json();

        if (response.ok) {
            showNotification('Move Successful', `Successfully moved ${result.moved_count} item(s)`, 'success');
            // Clear selection first, then refresh file table
            clearSelection();
            await refreshFileTable();
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
                current_path: CURRENT_PATH
            })
        });

        const result = await response.json();

        if (response.ok) {
            showNotification('Copy Successful', `Successfully copied ${result.copied_count} item(s)`, 'success');
            // Clear selection first, then refresh file table
            clearSelection();
            await refreshFileTable();
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
        } else {
            showUploadStatus(`❌ Bulk delete failed: ${result.error}`, 'error');
        }
    } catch (error) {
        showUploadStatus(`❌ Bulk delete failed: ${error.message}`, 'error');
    }
}

// Create Folder Function
async function createFolder(folderName, path) {
    try {
        const formData = new FormData();
        formData.append('foldername', folderName);
        formData.append('path', path);

        const response = await fetch('/mkdir', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            showNotification('Folder Created', result.message, 'success');
            // Clear the input field
            document.getElementById('folderNameInput').value = '';
            // Refresh the file table
            await refreshFileTable();
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
        cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Temp Files';
        cleanupBtn.onclick = async function () {
            try {
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
                cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Temp Files';
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
        const response = await fetch('/admin/upload_status');
        if (response.ok) {
            const status = await response.json();

            // Only disable during ACTUAL active uploads, not just chunk existence
            if (isUploading) {
                cleanupBtn.style.display = 'none';
                cleanupBtn.title = 'Manual cleanup disabled during active uploads';
            } else {
                cleanupBtn.style.display = 'inline-flex';
                // Update title based on whether chunks exist
                if (status.has_active_uploads) {
                    const chunkCount = typeof status.chunk_count === 'number' ? status.chunk_count : 0;
                    cleanupBtn.title = `Clean up ${chunkCount || 'temporary'} chunk files (Safe - no active uploads)`;
                    if (chunkCount > 0) {
                        cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Temp Files (' + chunkCount + ')';
                    } else {
                        cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Temp Files';
                    }
                } else {
                    cleanupBtn.title = 'Clean up temporary chunk files';
                    cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Temp Files';
                }
            }
        } else {
            // If we can't check status, show button but with warning
            cleanupBtn.style.display = 'inline-flex';
            cleanupBtn.title = 'Clean up temporary chunk files (Status check failed)';
            cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Temp Files';
        }
    } catch (error) {
        console.warn('Failed to check upload status:', error);
        // On error, still show the button - user can decide
        cleanupBtn.style.display = 'inline-flex';
        cleanupBtn.title = 'Clean up temporary chunk files (Status check failed)';
        cleanupBtn.innerHTML = '<i class="fas fa-broom"></i> Cleanup Temp Files';
    }
}

// Event listeners and initialization
document.addEventListener('DOMContentLoaded', function () {
    const clearBtn = document.getElementById('clearAllBtn');
    const uploadBtn = document.getElementById('startUploadBtn');
    const fileInput = document.getElementById('fileInput');
    const fileInputDisplay = document.querySelector('.file-input-display');

    // Add event listeners with null checks
    if (clearBtn) {
        console.log('🔧 Setting up clear button event listener');
        clearBtn.addEventListener('click', clearAllQueue);
    } else {
        console.warn('⚠️ Clear button not found');
    }

    if (uploadBtn) {
        console.log('🔧 Setting up upload button event listener');
        uploadBtn.addEventListener('click', startBatchUpload);
    } else {
        console.warn('⚠️ Upload button not found');
    }

    // Create folder form event listener
    const createFolderForm = document.getElementById('createFolderForm');
    if (createFolderForm) {
        createFolderForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const folderName = document.getElementById('folderNameInput').value.trim();
            const path = e.target.querySelector('input[name="path"]').value;

            if (folderName) {
                createFolder(folderName, path);
            }
        });
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

    // Drag and drop functionality
    if (fileInputDisplay && fileInput) {
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

        // Add click functionality to trigger file input
        fileInputDisplay.addEventListener('click', function () {
            fileInput.click();
        });

        // Update file input display when files are selected
        fileInput.addEventListener('change', function (e) {
            const files = Array.from(e.target.files);
            if (files.length > 0) {
                const display = document.querySelector('.file-input-display');
                if (display) {
                    display.innerHTML = `
                                <i class="fas fa-plus-circle" style="font-size: 20px; color: #27ae60;"></i>
                                <div>
                                    <strong>Added ${files.length} file(s) to queue</strong>
                                    <div style="font-size: 12px; opacity: 0.8; margin-top: 5px;">
                                        Click again to add more files
                                    </div>
                                </div>
                            `;
                    display.style.borderColor = '#27ae60';
                    display.style.backgroundColor = 'rgba(39, 174, 96, 0.1)';

                    // Reset after 2 seconds
                    setTimeout(() => {
                        display.innerHTML = `
                                    <i class="fas fa-upload" style="font-size: 20px;"></i>
                                    <div>
                                        <strong>Choose files to upload</strong>
                                        <div style="font-size: 12px; opacity: 0.8; margin-top: 5px;">
                                            Click here or drag and drop files (multiple files supported)
                                        </div>
                                    </div>
                                `;
                        display.style.borderColor = 'rgba(255, 255, 255, 0.4)';
                        display.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
                    }, 2000);
                }
            }
        });
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

    // Initial cleanup button state check
    setTimeout(() => {
        updateManualCleanupButton();
    }, 1000);

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

    // Initialize storage stats
    initializeStorageStats();

    // Refresh storage stats every 30 seconds
    setInterval(loadStorageStats, 30000);

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

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = Array.from(dt.files);

    if (files.length > 0) {
        addFilesToQueue(files);
    }
}

// Enhanced keyboard shortcuts
document.addEventListener('keydown', function (e) {
    // Ctrl/Cmd + U for upload file selection
    if ((e.ctrlKey || e.metaKey) && e.key === 'u' && !isUploading) {
        e.preventDefault();
        const fileInput = document.getElementById('fileInput');
        if (fileInput) fileInput.click();
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
        e.preventDefault();
        const currentPath = CURRENT_PATH;
        if (currentPath) {
            const pathParts = currentPath.split('/');
            pathParts.pop();
            const parentPath = pathParts.join('/');
            window.location.href = parentPath ? `/${parentPath}` : '/';
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
    clearSelection,
    closeModal,
    confirmMoveOrCopy,
    toggleSelectAll,
    updateSelection,
    setNotificationTimer
};

console.log('✅ Cloudinator Enhanced Upload System Ready');