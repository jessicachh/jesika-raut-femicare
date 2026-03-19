// Mobile menu toggle
document.addEventListener('DOMContentLoaded', function() {
  const menuToggle = document.getElementById('menuToggle');
  const sidebar = document.querySelector('.dashboard-sidebar');
  
  if (menuToggle && sidebar) {
    menuToggle.addEventListener('click', function() {
      sidebar.classList.toggle('open');
    });
    
    // Close sidebar when clicking outside on mobile
    document.addEventListener('click', function(event) {
      const isClickInside = sidebar.contains(event.target) || menuToggle.contains(event.target);
      
      if (!isClickInside && sidebar.classList.contains('open')) {
        sidebar.classList.remove('open');
      }
    });
  }
});

// Optional: Close sidebar when window is resized to desktop size
window.addEventListener('resize', function() {
  const sidebar = document.querySelector('.dashboard-sidebar');
  if (window.innerWidth > 768 && sidebar.classList.contains('open')) {
    sidebar.classList.remove('open');
  }
});


document.querySelectorAll(".cycle-card").forEach(card => {
  card.addEventListener("click", () => {
    const body = document.getElementById("cycleDetailsBody");

    body.innerHTML = `
      <p><strong>🩸 Last period started:</strong> ${card.dataset.lastPeriod}</p>
      <p><strong>📆 Cycle length:</strong> ${card.dataset.cycleLength} days</p>
      <p><strong>⏱ Menses length:</strong> ${card.dataset.mensesLength} days</p>
      <p><strong>💧 Bleeding intensity:</strong> ${card.dataset.bleeding}</p>
      <p><strong>⚠️ Unusual bleeding:</strong> ${card.dataset.unusual === "True" ? "Yes" : "No"}</p>
    `;

    const modal = new bootstrap.Modal(
      document.getElementById("viewCycleModal")
    );
    modal.show();
  });
});
document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
  new bootstrap.Tooltip(el);
});


function getCookie(name) {
  const cookieValue = document.cookie
    .split('; ')
    .find(row => row.startsWith(name + '='));
  return cookieValue ? decodeURIComponent(cookieValue.split('=')[1]) : null;
}

function updateNotificationBadge(count) {
  const badge = document.getElementById('notificationUnreadBadge');
  if (!badge) {
    return;
  }

  badge.textContent = count;
  if (count > 0) {
    badge.classList.remove('d-none');
  } else {
    badge.classList.add('d-none');
  }
}

function renderNotifications(items) {
  const list = document.getElementById('notificationDropdownList');
  if (!list) {
    return;
  }

  if (!items.length) {
    list.innerHTML = '<div class="notification-empty-state">No notifications yet</div>';
    return;
  }

  list.innerHTML = items
    .map(item => {
      const itemClass = item.is_read ? 'notification-item' : 'notification-item unread';
      return `
        <button type="button" class="${itemClass}" data-id="${item.id}">
          <div class="notification-item-head">
            <strong>${item.title}</strong>
            <span>${item.relative_time}</span>
          </div>
          <p>${item.message}</p>
        </button>
      `;
    })
    .join('');

  list.querySelectorAll('.notification-item').forEach(button => {
    button.addEventListener('click', async () => {
      const id = button.getAttribute('data-id');

      try {
        const response = await fetch(`/notifications/mark-read/${id}/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'X-Requested-With': 'XMLHttpRequest'
          }
        });

        if (!response.ok) {
          return;
        }

        const data = await response.json();
        button.classList.remove('unread');
        updateNotificationBadge(data.unread_count || 0);
      } catch (err) {
        console.error('Failed to mark notification as read', err);
      }
    });
  });
}

async function loadNotifications() {
  const list = document.getElementById('notificationDropdownList');
  if (!list) {
    return;
  }

  try {
    const response = await fetch('/notifications/', {
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    });

    if (!response.ok) {
      return;
    }

    const data = await response.json();
    updateNotificationBadge(data.unread_count || 0);
    renderNotifications(data.notifications || []);
  } catch (err) {
    console.error('Failed to load notifications', err);
  }
}

document.addEventListener('DOMContentLoaded', function () {
  const bell = document.getElementById('notificationBell');
  const markAllButton = document.getElementById('markAllNotificationsRead');

  if (bell) {
    bell.addEventListener('click', function () {
      loadNotifications();
    });
  }

  if (markAllButton) {
    markAllButton.addEventListener('click', async function () {
      try {
        const response = await fetch('/notifications/mark-all-read/', {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'X-Requested-With': 'XMLHttpRequest'
          }
        });

        if (!response.ok) {
          return;
        }

        updateNotificationBadge(0);
        loadNotifications();
      } catch (err) {
        console.error('Failed to mark all notifications as read', err);
      }
    });
  }

  loadNotifications();
});