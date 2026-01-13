// Create toast container dynamically if not exists
if (!document.getElementById('toast-container')) {
    const container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
}

// Function to create a toast
function createToast(message, type) {
    const container = document.getElementById('toast-container');

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerText = message;

    container.appendChild(toast);

    // Auto remove after 3 seconds
    setTimeout(() => {
        toast.classList.add('hide');
        toast.addEventListener('transitionend', () => toast.remove());
    }, 3000);
}

// Django messages integration (call this in the HTML template)
function showDjangoMessages(messages) {
    messages.forEach(msg => {
        createToast(msg.message, msg.tags || 'info');
    });
}

const messagesEl = document.getElementById('django-messages');
if (messagesEl) {
    const raw = messagesEl.dataset.messages; // e.g., "Error|||Success|||Info"
    const msgs = raw.split('|||');
    msgs.forEach(m => createToast(m, 'info')); // adjust type if needed
}