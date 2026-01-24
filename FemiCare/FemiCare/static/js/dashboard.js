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