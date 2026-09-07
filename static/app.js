(() => {
  const menu = document.getElementById('menu');
  const sidebar = document.getElementById('sidebar');
  const loader = document.getElementById('loadingScreen');
  const progress = document.getElementById('pageProgress');

  if (menu && sidebar) menu.addEventListener('click', () => {
    sidebar.classList.toggle('show');
    document.body.classList.toggle('menu-open', sidebar.classList.contains('show'));
  });

  // Smooth first-load / navigation experience.
  const hideLoader = () => {
    if (!loader) return;
    loader.classList.add('loaded');
    setTimeout(() => loader.remove(), 550);
  };
  window.addEventListener('load', () => setTimeout(hideLoader, 900));
  setTimeout(hideLoader, 2600);

  document.addEventListener('click', (e) => {
    const link = e.target.closest('a');
    if (!link || !link.href || link.target === '_blank' ||
        link.hasAttribute('download') || link.href.startsWith('javascript:') ||
        link.href.includes('#') && new URL(link.href).pathname === location.pathname) return;

    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin) return;
    e.preventDefault();
    if (progress) progress.classList.add('active');
    document.body.classList.add('page-leaving');
    setTimeout(() => { window.location.href = url.href; }, 180);
  });

  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', () => {
      const button = form.querySelector('button[type="submit"]');
      if (button && !button.dataset.loading) {
        button.dataset.loading = '1';
        button.disabled = true;
        button.classList.add('is-loading');
        button.innerHTML = '<span class="button-spinner"></span> Please wait...';
      }
      if (progress) progress.classList.add('active');
    });
  });

  setTimeout(() => document.querySelectorAll('.toast').forEach(x => {
    x.classList.add('toast-hide');
    setTimeout(() => x.remove(), 350);
  }), 4500);

  // Scroll reveal for cards.
  const revealItems = document.querySelectorAll('.item-card, .how-card, .cta-banner, .formpage, .summary');
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries, obs) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view');
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08 });
    revealItems.forEach(el => io.observe(el));
  } else revealItems.forEach(el => el.classList.add('in-view'));
})();