/* Progressive customer UI only. Pricing, stock and cart mutations stay server-owned. */
(() => {
  'use strict';
  if (!document.body.classList.contains('zuuvi-storefront')) return;
  const disclosures = [...document.querySelectorAll('[data-sf-disclosure]')];
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    disclosures.forEach(details => {
      if (details.open && details.contains(document.activeElement)) {
        details.open = false;
        details.querySelector('summary').focus();
      }
    });
  });
  document.addEventListener('click', event => {
    disclosures.forEach(details => {
      if (details.open && !details.contains(event.target)) details.open = false;
    });
  });
  const image = document.getElementById('sf-gallery-image');
  const photos = [...document.querySelectorAll('[data-sf-gallery-photo]')];
  photos.forEach((photo, index) => {
    photo.addEventListener('click', event => {
      if (!image || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      image.src = photo.href;
      image.alt = photo.dataset.photoAlt;
      photos.forEach(item => item.removeAttribute('aria-current'));
      photo.setAttribute('aria-current', 'true');
      document.getElementById('sf-gallery-status').textContent = `Photo ${index + 1} of ${photos.length}`;
    });
  });
  const filters = document.querySelector('[data-sf-filter-form]');
  const filterPanel = document.getElementById('sf-filters');
  const errors = document.getElementById('filter-errors');
  if (filterPanel && window.matchMedia('(max-width: 991px)').matches) filterPanel.open = Boolean(errors);
  if (errors) errors.focus();
  if (filters) {
    document.getElementById('id_sort').addEventListener('change', () => filters.requestSubmit());
    filters.addEventListener('submit', () => {
      filters.setAttribute('aria-busy', 'true');
      filters.querySelector('[data-sf-filter-status]').textContent = 'Updating results…';
    });
    window.addEventListener('pageshow', () => {
      filters.removeAttribute('aria-busy');
      filters.querySelector('[data-sf-filter-status]').textContent = '';
    });
  }
})();
