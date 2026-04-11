const SEARCH_ENTRIES = {
  user: [
    { label: 'Appointments', keywords: ['appointment', 'doctor', 'session', 'consultation'], url: '/dashboard/appointments/', sectionId: 'appointments-section' },
    { label: 'Symptoms', keywords: ['symptom', 'pain', 'mood', 'cycle'], url: '/dashboard/', sectionId: 'symptoms-section' },
    { label: 'Reports', keywords: ['report', 'analysis', 'insight'], url: '/dashboard/reports/', sectionId: 'reports-section' },
    { label: 'Chat', keywords: ['chat', 'message', 'conversation'], url: '/dashboard/chat/', sectionId: 'chat-section' },
    { label: 'Profile', keywords: ['profile', 'account', 'details'], url: '/dashboard/profile/', sectionId: 'profile-section' },
    { label: 'Documents', keywords: ['document', 'records', 'files'], url: '/dashboard/profile/', sectionId: 'documents-section' },
    { label: 'Settings', keywords: ['settings', 'password', 'security', 'email'], url: '/dashboard/settings/', sectionId: 'settings-section' },
    { label: 'Emergency', keywords: ['emergency', 'urgent', 'alert'], url: '/dashboard/', sectionId: 'emergency-section' },
  ],
  doctor: [
    { label: 'Appointments', keywords: ['appointment', 'consultation', 'requests', 'queue'], url: '/doctor/appointment/', sectionId: 'appointments-section' },
    { label: 'Emergency Queue', keywords: ['emergency', 'urgent', 'alert'], url: '/doctor/appointment/', sectionId: 'emergency-section' },
    { label: 'Profile', keywords: ['profile', 'bio', 'qualifications'], url: '/doctor/profile/', sectionId: 'profile-section' },
    { label: 'Settings', keywords: ['settings', 'password', 'security', 'email'], url: '/doctor/settings/', sectionId: 'settings-section' },
    { label: 'Dashboard', keywords: ['dashboard', 'schedule', 'availability'], url: '/doctor/dashboard/', sectionId: 'appointments-section' },
  ],
};

function getCookie(name) {
  const cookieValue = document.cookie
    .split('; ')
    .find(row => row.startsWith(name + '='));
  return cookieValue ? decodeURIComponent(cookieValue.split('=')[1]) : null;
}

function normalizePath(path) {
  if (!path) {
    return '/';
  }
  return path.endsWith('/') ? path : `${path}/`;
}

function appendHashToUrl(url, sectionId) {
  if (!sectionId) {
    return url;
  }
  const cleanHash = sectionId.startsWith('#') ? sectionId.slice(1) : sectionId;
  return `${url.split('#')[0]}#${cleanHash}`;
}

function navigateToSection(sectionId) {
  if (!sectionId) {
    return false;
  }

  const normalizedId = sectionId.replace(/^#/, '');
  const target = document.getElementById(normalizedId);
  if (!target) {
    return false;
  }

  target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  target.classList.remove('nav-target-highlight');
  void target.offsetWidth;
  target.classList.add('nav-target-highlight');

  window.setTimeout(() => {
    target.classList.remove('nav-target-highlight');
  }, 2600);

  return true;
}

window.navigateToSection = navigateToSection;

function navigateByTarget(targetUrl, targetSectionId) {
  const currentPath = normalizePath(window.location.pathname);
  const resolvedUrl = (targetUrl || '').trim();
  const resolvedSection = (targetSectionId || '').trim();

  if (!resolvedUrl && resolvedSection) {
    navigateToSection(resolvedSection);
    return;
  }

  if (!resolvedUrl) {
    return;
  }

  const destination = new URL(resolvedUrl, window.location.origin);
  const destinationPath = normalizePath(destination.pathname);

  if (destinationPath === currentPath) {
    if (resolvedSection) {
      navigateToSection(resolvedSection);
    }
    return;
  }

  window.location.href = appendHashToUrl(resolvedUrl, resolvedSection);
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

function triggerClickGlow(element) {
  if (!element) {
    return;
  }

  element.classList.remove('click-glow-active');
  void element.offsetWidth;
  element.classList.add('click-glow-active');
}

function initializeSearchNavigation() {
  const header = document.querySelector('.dashboard-header');
  const searchBox = document.querySelector('.search-box');
  const input = document.getElementById('dashboardSearchInput');
  const suggestionsBox = document.getElementById('searchSuggestions');

  if (!header || !input || !suggestionsBox) {
    return;
  }

  if (searchBox) {
    searchBox.addEventListener('click', function () {
      triggerClickGlow(searchBox);
    });
  }

  const role = (header.getAttribute('data-user-role') || 'user').toLowerCase();
  const entries = SEARCH_ENTRIES[role] || SEARCH_ENTRIES.user;
  let currentResults = [];
  let focusedIndex = -1;

  function hideSuggestions() {
    suggestionsBox.classList.add('d-none');
    suggestionsBox.innerHTML = '';
    focusedIndex = -1;
  }

  function showSuggestions() {
    if (!currentResults.length) {
      hideSuggestions();
      return;
    }
    suggestionsBox.classList.remove('d-none');
  }

  function scoreEntry(query, entry) {
    const q = query.toLowerCase().trim();
    if (!q) {
      return -1;
    }

    const label = entry.label.toLowerCase();
    const matchedKeyword = entry.keywords.find((item) => item.includes(q));

    if (label === q) {
      return 100;
    }
    if (label.startsWith(q)) {
      return 80;
    }
    if (matchedKeyword && matchedKeyword.startsWith(q)) {
      return 60;
    }
    if (label.includes(q)) {
      return 40;
    }
    if (matchedKeyword) {
      return 25;
    }
    return -1;
  }

  function buildSuggestions(query) {
    const ranked = entries
      .map((entry) => ({ entry, score: scoreEntry(query, entry) }))
      .filter((row) => row.score >= 0)
      .sort((a, b) => b.score - a.score);

    const unique = [];
    const seen = new Set();
    ranked.forEach((row) => {
      const key = `${row.entry.url}|${row.entry.sectionId}`;
      if (!seen.has(key)) {
        seen.add(key);
        unique.push(row.entry);
      }
    });
    return unique.slice(0, 6);
  }

  function renderSuggestions() {
    suggestionsBox.innerHTML = currentResults
      .map((entry, index) => {
        const activeClass = index === focusedIndex ? 'active' : '';
        return `
          <button
            type="button"
            class="search-suggestion-item ${activeClass}"
            data-index="${index}"
            role="option"
            aria-selected="${index === focusedIndex ? 'true' : 'false'}"
          >
            <span class="search-suggestion-title">${entry.label}</span>
            <span class="search-suggestion-meta">${entry.keywords.slice(0, 2).join(' / ')}</span>
          </button>
        `;
      })
      .join('');

    suggestionsBox.querySelectorAll('.search-suggestion-item').forEach((button) => {
      button.addEventListener('click', function () {
        const idx = Number(button.getAttribute('data-index'));
        const selected = currentResults[idx];
        if (!selected) {
          return;
        }
        input.value = selected.label;
        hideSuggestions();
        navigateByTarget(selected.url, selected.sectionId);
      });
    });
  }

  function selectByEnter() {
    if (!currentResults.length) {
      return;
    }
    const index = focusedIndex >= 0 ? focusedIndex : 0;
    const selected = currentResults[index];
    if (!selected) {
      return;
    }
    input.value = selected.label;
    hideSuggestions();
    navigateByTarget(selected.url, selected.sectionId);
  }

  input.addEventListener('input', function () {
    const query = input.value.trim();
    if (!query) {
      hideSuggestions();
      return;
    }

    currentResults = buildSuggestions(query);
    focusedIndex = currentResults.length ? 0 : -1;
    renderSuggestions();
    showSuggestions();
  });

  input.addEventListener('focus', function () {
    if (input.value.trim()) {
      currentResults = buildSuggestions(input.value.trim());
      focusedIndex = currentResults.length ? 0 : -1;
      renderSuggestions();
      showSuggestions();
    }
  });

  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      selectByEnter();
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (!currentResults.length) {
        return;
      }
      focusedIndex = (focusedIndex + 1) % currentResults.length;
      renderSuggestions();
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (!currentResults.length) {
        return;
      }
      focusedIndex = (focusedIndex - 1 + currentResults.length) % currentResults.length;
      renderSuggestions();
      return;
    }

    if (event.key === 'Escape') {
      hideSuggestions();
    }
  });

  document.addEventListener('click', function (event) {
    if (!suggestionsBox.contains(event.target) && event.target !== input) {
      hideSuggestions();
    }
  });
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
    .map((item) => {
      const itemClass = item.is_read ? 'notification-item clickable' : 'notification-item unread clickable';
      const targetUrl = item.target_url || '';
      const targetSection = item.target_section_id || '';
      return `
        <button
          type="button"
          class="${itemClass}"
          data-id="${item.id}"
          data-target-url="${targetUrl}"
          data-target-section="${targetSection}"
        >
          <div class="notification-item-head">
            <strong>${item.title}</strong>
            <span>${item.relative_time}</span>
          </div>
          <p>${item.message}</p>
        </button>
      `;
    })
    .join('');

  list.querySelectorAll('.notification-item').forEach((button) => {
    button.addEventListener('click', async function () {
      const id = button.getAttribute('data-id');
      const targetUrl = button.getAttribute('data-target-url') || '';
      const targetSectionId = button.getAttribute('data-target-section') || '';

      try {
        const response = await fetch(`/notifications/mark-read/${id}/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'X-Requested-With': 'XMLHttpRequest',
          },
        });

        if (response.ok) {
          const data = await response.json();
          button.classList.remove('unread');
          updateNotificationBadge(data.unread_count || 0);
        }
      } catch (err) {
        console.error('Failed to mark notification as read', err);
      }

      navigateByTarget(targetUrl, targetSectionId);
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
        'X-Requested-With': 'XMLHttpRequest',
      },
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

function applyHashNavigation() {
  const hash = window.location.hash;
  if (!hash || hash.length <= 1) {
    return;
  }

  const sectionId = decodeURIComponent(hash.slice(1));
  window.setTimeout(() => {
    navigateToSection(sectionId);
  }, 180);
}

// Mobile menu toggle
document.addEventListener('DOMContentLoaded', function () {
  const menuToggle = document.getElementById('menuToggle');
  const sidebar = document.querySelector('.dashboard-sidebar');

  if (menuToggle && sidebar) {
    menuToggle.addEventListener('click', function () {
      sidebar.classList.toggle('open');
    });

    document.addEventListener('click', function (event) {
      const isClickInside = sidebar.contains(event.target) || menuToggle.contains(event.target);
      if (!isClickInside && sidebar.classList.contains('open')) {
        sidebar.classList.remove('open');
      }
    });
  }

  document.querySelectorAll('.cycle-card').forEach((card) => {
    card.addEventListener('click', function () {
      const body = document.getElementById('cycleDetailsBody');
      if (!body || typeof bootstrap === 'undefined') {
        return;
      }

      body.innerHTML = `
        <p><strong>🩸 Last period started:</strong> ${card.dataset.lastPeriod}</p>
        <p><strong>📆 Cycle length:</strong> ${card.dataset.cycleLength} days</p>
        <p><strong>⏱ Menses length:</strong> ${card.dataset.mensesLength} days</p>
        <p><strong>💧 Bleeding intensity:</strong> ${card.dataset.bleeding}</p>
        <p><strong>⚠️ Unusual bleeding:</strong> ${card.dataset.unusual === 'True' ? 'Yes' : 'No'}</p>
      `;

      const modal = new bootstrap.Modal(document.getElementById('viewCycleModal'));
      modal.show();
    });
  });

  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
    if (typeof bootstrap !== 'undefined') {
      new bootstrap.Tooltip(el);
    }
  });

  const bell = document.getElementById('notificationBell');
  const markAllButton = document.getElementById('markAllNotificationsRead');

  if (bell) {
    bell.addEventListener('click', function () {
      triggerClickGlow(bell);
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
            'X-Requested-With': 'XMLHttpRequest',
          },
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

  initializeSearchNavigation();
  applyHashNavigation();
  loadNotifications();
});

window.addEventListener('resize', function () {
  const sidebar = document.querySelector('.dashboard-sidebar');
  if (window.innerWidth > 768 && sidebar && sidebar.classList.contains('open')) {
    sidebar.classList.remove('open');
  }
});