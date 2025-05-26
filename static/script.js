// Global variables
let socket = null;
let connectionTestInProgress = false;

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

function initializeApp() {
    // Initialize Socket.IO if on monitor page
    if (window.location.pathname === '/monitor') {
        initializeSocket();
    }

    // Add event listeners
    addEventListeners();

    // Auto-refresh dashboard status
    if (window.location.pathname === '/') {
        setInterval(updateDashboardStatus, 30000); // Every 30 seconds
    }
}

function initializeSocket() {
    if (typeof io !== 'undefined') {
        socket = io();

        socket.on('connect', function() {
            console.log('Connected to monitoring service');
            showNotification('Connected to monitoring service', 'success');
        });

        socket.on('disconnect', function() {
            console.log('Disconnected from monitoring service');
            showNotification('Disconnected from monitoring service', 'warning');
        });

        socket.on('connect_error', function(error) {
            console.error('Connection error:', error);
            showNotification('Connection error: ' + error, 'error');
        });
    }
}

function addEventListeners() {
    // Test connection buttons
    const testButtons = document.querySelectorAll('[onclick*="testConnection"]');
    testButtons.forEach(button => {
        button.removeAttribute('onclick');
        button.addEventListener('click', testConnection);
    });

    // Download logs buttons
    const downloadButtons = document.querySelectorAll('[onclick*="downloadLogs"]');
    downloadButtons.forEach(button => {
        button.removeAttribute('onclick');
        button.addEventListener('click', downloadLogs);
    });

    // Form submissions
    const configForm = document.getElementById('config-form');
    if (configForm) {
        configForm.addEventListener('submit', handleConfigSubmit);
    }

    // Stop monitoring button
    const stopButton = document.getElementById('stop-monitoring');
    if (stopButton) {
        stopButton.addEventListener('click', stopMonitoring);
    }

    // Auto-save form data
    const formInputs = document.querySelectorAll('input, select');
    formInputs.forEach(input => {
        input.addEventListener('change', saveFormData);
        input.addEventListener('input', saveFormData);
    });

    // Load saved form data
    loadFormData();
}

function testConnection() {
    if (connectionTestInProgress) {
        showNotification('Connection test already in progress...', 'warning');
        return;
    }

    connectionTestInProgress = true;
    const button = event.target.closest('button');
    const originalText = button.innerHTML;

    // Update button state
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Testing...';

    // Clear previous results
    const resultDiv = document.getElementById('connection-result') ||
                     document.getElementById('config-result');
    if (resultDiv) {
        resultDiv.innerHTML = '';
    }

    fetch('/api/test_connection', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        const resultClass = data.success ? 'success' : 'error';
        const icon = data.success ? 'fa-check-circle' : 'fa-exclamation-triangle';

        if (resultDiv) {
            resultDiv.innerHTML = `
                <div class="alert alert-${resultClass}">
                    <i class="fas ${icon}"></i>
                    <strong>${data.success ? 'Success:' : 'Error:'}</strong> ${data.message}
                    ${data.status_code ? `<br><small>HTTP Status: ${data.status_code}</small>` : ''}
                </div>
            `;
        }

        showNotification(data.message, resultClass);

        // Log the test result
        console.log('Connection test result:', data);
    })
    .catch(error => {
        const errorMsg = 'Network error: ' + error.message;

        if (resultDiv) {
            resultDiv.innerHTML = `
                <div class="alert alert-error">
                    <i class="fas fa-exclamation-triangle"></i>
                    <strong>Network Error:</strong> ${error.message}
                </div>
            `;
        }

        showNotification(errorMsg, 'error');
        console.error('Connection test error:', error);
    })
    .finally(() => {
        // Restore button state
        button.disabled = false;
        button.innerHTML = originalText;
        connectionTestInProgress = false;
    });
}

function downloadLogs() {
    const button = event.target.closest('button');
    const originalText = button.innerHTML;

    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Downloading...';

    fetch('/api/get_logs')
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (data.logs.length === 0) {
                showNotification('No logs available to download', 'warning');
                return;
            }

            // Create downloadable file
            const logContent = data.logs.join('\n');
            const blob = new Blob([logContent], { type: 'text/plain' });
            const url = window.URL.createObjectURL(blob);

            // Create download link
            const a = document.createElement('a');
            a.href = url;
            a.download = `xdr_logs_${new Date().toISOString().split('T')[0]}.txt`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);

            showNotification(`Downloaded ${data.logs.length} log entries`, 'success');
        } else {
            showNotification('Error downloading logs: ' + data.message, 'error');
        }
    })
    .catch(error => {
        showNotification('Error downloading logs: ' + error.message, 'error');
        console.error('Download error:', error);
    })
    .finally(() => {
        button.disabled = false;
        button.innerHTML = originalText;
    });
}

function handleConfigSubmit(event) {
    event.preventDefault();

    const formData = new FormData(event.target);
    const config = {};

    // Convert FormData to object
    for (let [key, value] of formData.entries()) {
        config[key] = value;
    }

    // Validate required fields
    if (!config.syslog_server) {
        showNotification('Syslog server IP is required', 'error');
        return;
    }

    // Validate IP address format
    if (!isValidIP(config.syslog_server)) {
        showNotification('Please enter a valid IP address', 'error');
        return;
    }

    // Show loading state
    const submitButton = event.target.querySelector('button[type="submit"]');
    const originalText = submitButton.innerHTML;
    submitButton.disabled = true;
    submitButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';

    // Start monitoring
    fetch('/api/start_monitoring', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(config)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Monitoring started successfully!', 'success');

            // Save configuration
            localStorage.setItem('xdr_config', JSON.stringify(config));

            // Redirect to monitor page after short delay
            setTimeout(() => {
                window.location.href = '/monitor';
            }, 1500);
        } else {
            showNotification('Error starting monitoring: ' + data.message, 'error');
        }
    })
    .catch(error => {
        showNotification('Error starting monitoring: ' + error.message, 'error');
        console.error('Start monitoring error:', error);
    })
    .finally(() => {
        submitButton.disabled = false;
        submitButton.innerHTML = originalText;
    });
}

function stopMonitoring() {
    if (!confirm('Are you sure you want to stop monitoring?')) {
        return;
    }

    const button = event.target.closest('button');
    const originalText = button.innerHTML;

    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Stopping...';

    fetch('/api/stop_monitoring', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Monitoring stopped successfully', 'success');

            // Update UI
            document.getElementById('monitor-status').textContent = 'Stopped';

            // Optionally redirect to dashboard
            setTimeout(() => {
                if (confirm('Monitoring stopped. Return to dashboard?')) {
                    window.location.href = '/';
                }
            }, 2000);
        } else {
            showNotification('Error stopping monitoring: ' + data.message, 'error');
        }
    })
    .catch(error => {
        showNotification('Error stopping monitoring: ' + error.message, 'error');
        console.error('Stop monitoring error:', error);
    })
    .finally(() => {
        button.disabled = false;
        button.innerHTML = originalText;
    });
}

function saveFormData() {
    const form = event.target.closest('form');
    if (!form) return;

    const formData = new FormData(form);
    const data = {};

    for (let [key, value] of formData.entries()) {
        data[key] = value;
    }

    localStorage.setItem('xdr_form_data', JSON.stringify(data));
}

function loadFormData() {
    const savedData = localStorage.getItem('xdr_form_data');
    if (!savedData) return;

    try {
        const data = JSON.parse(savedData);

        Object.keys(data).forEach(key => {
            const input = document.querySelector(`[name="${key}"]`);
            if (input) {
                input.value = data[key];
            }
        });
    } catch (error) {
        console.error('Error loading form data:', error);
    }
}

function updateDashboardStatus() {
    // Update monitoring status on dashboard
    fetch('/api/monitoring_status')
    .then(response => response.json())
    .then(data => {
        const statusElement = document.querySelector('.monitoring-status');
        if (statusElement) {
            statusElement.className = `monitoring-status ${data.active ? 'active' : 'inactive'}`;
            statusElement.innerHTML = `
                <i class="fas ${data.active ? 'fa-play' : 'fa-stop'}"></i>
                ${data.active ? 'Monitoring Active' : 'Monitoring Stopped'}
            `;
        }
    })
    .catch(error => {
        console.error('Error updating dashboard status:', error);
    });
}

function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;

    const icon = getNotificationIcon(type);
    notification.innerHTML = `
        <i class="fas ${icon}"></i>
        <span>${message}</span>
        <button class="notification-close" onclick="this.parentElement.remove()">
            <i class="fas fa-times"></i>
        </button>
    `;

    // Add to page
    let container = document.querySelector('.notification-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'notification-container';
        document.body.appendChild(container);
    }

    container.appendChild(notification);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 5000);

    // Add slide-in animation
    setTimeout(() => {
        notification.classList.add('show');
    }, 10);
}

function getNotificationIcon(type) {
    switch (type) {
        case 'success': return 'fa-check-circle';
        case 'error': return 'fa-exclamation-triangle';
        case 'warning': return 'fa-exclamation-circle';
        case 'info':
        default: return 'fa-info-circle';
    }
}

function isValidIP(ip) {
    const ipRegex = /^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
    return ipRegex.test(ip);
}

function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];

    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function copyToClipboard(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            showNotification('Copied to clipboard', 'success');
        }).catch(err => {
            console.error('Failed to copy: ', err);
            fallbackCopyTextToClipboard(text);
        });
    } else {
        fallbackCopyTextToClipboard(text);
    }
}

function fallbackCopyTextToClipboard(text) {
    const textArea = document.createElement("textarea");
    textArea.value = text;

    // Avoid scrolling to bottom
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.position = "fixed";

    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();

    try {
        const successful = document.execCommand('copy');
        if (successful) {
            showNotification('Copied to clipboard', 'success');
        } else {
            showNotification('Failed to copy to clipboard', 'error');
        }
    } catch (err) {
        console.error('Fallback: Oops, unable to copy', err);
        showNotification('Failed to copy to clipboard', 'error');
    }

    document.body.removeChild(textArea);
}

// Export functions for global access
window.testConnection = testConnection;
window.downloadLogs = downloadLogs;
window.stopMonitoring = stopMonitoring;
window.showNotification = showNotification;
window.copyToClipboard = copyToClipboard;

// Debug helpers
window.xdrDebug = {
    clearStorage: () => {
        localStorage.removeItem('xdr_form_data');
        localStorage.removeItem('xdr_config');
        showNotification('Storage cleared', 'info');
    },
    getConfig: () => {
        const config = localStorage.getItem('xdr_config');
        return config ? JSON.parse(config) : null;
    },
    getFormData: () => {
        const data = localStorage.getItem('xdr_form_data');
        return data ? JSON.parse(data) : null;
    }
};

console.log('XDR Monitor JavaScript loaded successfully');
console.log('Debug helpers available at window.xdrDebug');
