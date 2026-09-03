/**
 * Music Catalog App - Client-side JavaScript
 */

// Utility functions
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

// API calls
async function apiCall(endpoint, method = 'GET', data = null) {
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json'
        }
    };

    if (data) {
        options.body = JSON.stringify(data);
    }

    try {
        const response = await fetch(endpoint, options);
        const json = await response.json();
        return { ok: response.ok, status: response.status, data: json };
    } catch (error) {
        console.error('API error:', error);
        return { ok: false, status: 0, data: { error: error.message } };
    }
}

// Search and filter functions
const searchInput = document.getElementById('search');
if (searchInput) {
    searchInput.addEventListener('input', debounce(function() {
        if (typeof filterAndSort === 'function') {
            filterAndSort();
        }
    }, 300));
}

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Focus search on '/' key
    if (e.key === '/' && e.ctrlKey === false && e.metaKey === false) {
        const search = document.getElementById('search');
        if (search) {
            e.preventDefault();
            search.focus();
        }
    }

    // Close modal on 'Escape' key
    if (e.key === 'Escape') {
        const modal = document.getElementById('confirmation-modal');
        if (modal && !modal.classList.contains('hidden')) {
            if (typeof closeModal === 'function') {
                closeModal();
            }
        }
    }
});

// Form utilities
function getFormData(form) {
    const formData = new FormData(form);
    const data = {};

    formData.forEach((value, key) => {
        if (data.hasOwnProperty(key)) {
            if (Array.isArray(data[key])) {
                data[key].push(value);
            } else {
                data[key] = [data[key], value];
            }
        } else {
            data[key] = value;
        }
    });

    return data;
}

// Image preview
function previewImage(inputId, previewId) {
    const input = document.getElementById(inputId);
    const preview = document.getElementById(previewId);

    if (input && preview) {
        input.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function(event) {
                    preview.src = event.target.result;
                    preview.style.display = 'block';
                };
                reader.readAsDataURL(file);
            }
        });
    }
}

// Show/hide elements
function show(elementId) {
    const el = document.getElementById(elementId);
    if (el) el.classList.remove('hidden');
}

function hide(elementId) {
    const el = document.getElementById(elementId);
    if (el) el.classList.add('hidden');
}

function toggle(elementId) {
    const el = document.getElementById(elementId);
    if (el) el.classList.toggle('hidden');
}

// Notifications
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 p-4 rounded-lg text-white max-w-sm ${
        type === 'success' ? 'bg-green-600' :
        type === 'error' ? 'bg-red-600' :
        type === 'warning' ? 'bg-amber-600' :
        'bg-blue-600'
    }`;
    notification.textContent = message;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.remove();
    }, 5000);
}

// Confirm dialog
function confirmAction(message) {
    return confirm(message);
}

// Format utilities
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

function formatYear(year) {
    return year || 'Unknown';
}

// Local storage utilities
const storage = {
    set: (key, value) => localStorage.setItem(key, JSON.stringify(value)),
    get: (key) => {
        const value = localStorage.getItem(key);
        try {
            return value ? JSON.parse(value) : null;
        } catch {
            return null;
        }
    },
    remove: (key) => localStorage.removeItem(key),
    clear: () => localStorage.clear()
};

// Query parameters
function getQueryParam(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name);
}

function setQueryParam(name, value) {
    const params = new URLSearchParams(window.location.search);
    params.set(name, value);
    window.history.replaceState({}, '', `${window.location.pathname}?${params}`);
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    // Remove loading class from body if present
    document.body.classList.remove('loading');

    // Initialize tooltips or other global functionality as needed
});

// Export for use in other scripts
window.MusicCatalogApp = {
    apiCall,
    debounce,
    escapeHtml,
    getFormData,
    show,
    hide,
    toggle,
    showNotification,
    confirmAction,
    formatDate,
    formatYear,
    storage,
    getQueryParam,
    setQueryParam
};
