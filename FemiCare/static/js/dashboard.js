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