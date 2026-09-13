// Auto-hide flash messages after 4 seconds
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flashes li').forEach(li => {
    setTimeout(() => {
      li.style.transition = 'opacity .4s, transform .4s';
      li.style.opacity = '0';
      li.style.transform = 'translateY(-4px)';
      setTimeout(() => li.remove(), 400);
    }, 4000);
  });
});

// Confirmation for delete buttons with data-confirm
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', (e) => {
      if (!confirm(form.dataset.confirm)) e.preventDefault();
    });
  });
});