const TOAST_LABELS = {
    success: 'Success',
    danger: 'Error',
    error: 'Error',
    warning: 'Warning',
    info: 'Info',
};

function ensureToastContainer() {
    let container = document.getElementById('toast-container');

    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        document.body.appendChild(container);
    }

    return container;
}

function createToast(message, type = 'info') {
    if (!message) {
        return;
    }

    const container = ensureToastContainer();
    const toast = document.createElement('div');
    const normalizedType = TOAST_LABELS[type] ? type : 'info';

    toast.className = `toast show align-items-center text-bg-${normalizedType === 'error' ? 'danger' : normalizedType} border-0 shadow-sm rounded-4 mb-2`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.innerHTML = `
        <div class="d-flex align-items-start">
            <div class="toast-body py-3">
                <strong class="d-block mb-1">${TOAST_LABELS[normalizedType] || 'Info'}</strong>
                <span></span>
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" aria-label="Close"></button>
        </div>
    `;

    toast.querySelector('.toast-body span').textContent = message;
    toast.querySelector('.btn-close').addEventListener('click', () => toast.remove());
    container.appendChild(toast);

    window.setTimeout(() => {
        toast.classList.remove('show');
        toast.addEventListener('transitionend', () => toast.remove(), { once: true });
    }, 3200);
}

function showDjangoMessages(messages) {
    if (!Array.isArray(messages)) {
        return;
    }

    messages.forEach((msg) => {
        createToast(msg.message, msg.tags || 'info');
    });
}

const messagesEl = document.getElementById('django-messages');
if (messagesEl) {
    const raw = messagesEl.dataset.messages || '';
    if (raw) {
        raw.split('|||').forEach((message) => createToast(message, 'info'));
    }
}