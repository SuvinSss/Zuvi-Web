(() => {
  'use strict';
  const form = document.getElementById('product-entry-form');
  if (!form || !window.fetch || !window.FormData) return;
  const input = form.elements.images;
  const grid = document.getElementById('entry-photo-grid');
  const main = form.elements.main_photo;
  const count = document.getElementById('entry-photo-count');
  const empty = document.getElementById('entry-photo-empty');
  const summary = document.getElementById('entry-error-summary');
  const status = document.getElementById('entry-save-status');
  const existing = Array.from(grid.querySelectorAll('[data-existing-photo]'));
  let uploads = [], busy = false;
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const retained = () => existing.filter(photo => !photo.querySelector('input[name="remove_images"]').checked);
  const showErrors = errors => {
    form.querySelectorAll('.entry-field-errors').forEach(node => { node.replaceChildren(); });
    form.querySelectorAll('[aria-invalid]').forEach(node => { node.removeAttribute('aria-invalid'); });
    const list = summary.querySelector('ul');
    list.replaceChildren();
    errors.forEach(error => {
      const item = element('li');
      const field = Array.from(form.querySelectorAll('[data-field]')).find(node => node.dataset.field === error.field);
      const control = field && field.querySelector('input:not([type=hidden]),select,textarea');
      const text = `${error.label || 'Product'}: ${error.message}`;
      if (control && control.id) {
        const link = element('a', text);
        link.href = `#${control.id}`;
        link.addEventListener('click', event => { event.preventDefault(); control.focus(); });
        item.append(link);
        control.setAttribute('aria-invalid', 'true');
        const errorBox = field.querySelector('.entry-field-errors');
        if (errorBox) {
          errorBox.append(element('p', error.message));
          if (errorBox.id) control.setAttribute('aria-describedby', `${control.getAttribute('aria-describedby') || ''} ${errorBox.id}`.trim());
        }
        const advanced = field.closest('details');
        if (advanced) advanced.open = true;
      } else item.textContent = text;
      list.append(item);
    });
    summary.hidden = !errors.length;
    if (errors.length) summary.focus();
  };
  const setMain = value => { main.value = value; renderPhotos(); };
  function renderPhotos() {
    const current = main.value;
    main.replaceChildren(new Option('Keep current / choose automatically', ''));
    retained().forEach((photo, index) => main.add(new Option(`Existing photo ${existing.indexOf(photo) + 1}`, `existing:${photo.dataset.existingPhoto}`)));
    uploads.forEach((upload, index) => main.add(new Option(`New photo ${index + 1}: ${upload.file.name}`, `new:${index}`)));
    main.value = Array.from(main.options).some(option => option.value === current) ? current : '';
    const originalPrimary = retained().find(photo => photo.dataset.primary === 'true');
    const automatic = originalPrimary || retained()[0];
    const effectiveMain = main.value || (automatic ? `existing:${automatic.dataset.existingPhoto}` : uploads.length ? 'new:0' : '');
    existing.forEach(photo => {
      const removed = photo.querySelector('input').checked;
      const key = `existing:${photo.dataset.existingPhoto}`;
      photo.classList.toggle('is-removed', removed);
      photo.querySelector('.entry-photo-badge').hidden = removed || effectiveMain !== key;
      const button = photo.querySelector('[data-set-main]');
      button.hidden = false;
      button.disabled = removed || effectiveMain === key;
      button.textContent = effectiveMain === key && !removed ? 'Main photo selected' : 'Make main';
      button.setAttribute('aria-pressed', String(effectiveMain === key && !removed));
    });
    grid.querySelectorAll('[data-new-photo]').forEach(photo => photo.remove());
    uploads.forEach((upload, index) => {
      const photo = element('div', '', 'entry-photo');
      photo.dataset.newPhoto = String(index);
      const image = element('img'); image.src = upload.url; image.alt = `New photo ${index + 1}: ${upload.file.name}`;
      const badge = element('span', 'Main photo', 'entry-photo-badge'); badge.hidden = effectiveMain !== `new:${index}`;
      const choose = element('button', effectiveMain === `new:${index}` ? 'Main photo selected' : 'Make main', 'entry-photo-primary');
      choose.type = 'button'; choose.disabled = effectiveMain === `new:${index}`;
      choose.setAttribute('aria-label', `Make new photo ${index + 1} main`);
      choose.setAttribute('aria-pressed', String(effectiveMain === `new:${index}`));
      choose.addEventListener('click', () => setMain(`new:${index}`));
      const remove = element('button', `Remove new photo ${index + 1}`, 'entry-photo-remove'); remove.type = 'button';
      remove.addEventListener('click', () => {
        const previous = main.value;
        const selectedIndex = previous.startsWith('new:') ? Number(previous.split(':')[1]) : -1;
        URL.revokeObjectURL(upload.url); uploads.splice(index, 1);
        if (selectedIndex === index) main.value = '';
        else if (selectedIndex > index) main.value = `new:${selectedIndex - 1}`;
        renderPhotos(); input.focus();
      });
      photo.append(image, badge, element('p', upload.file.name, 'entry-photo-name'), choose, remove); grid.append(photo);
    });
    const total = retained().length + uploads.length;
    count.value = `${total}/5`; count.textContent = `${total}/5`;
    count.classList.toggle('is-over-limit', total > 5);
    empty.hidden = total > 0;
  }
  existing.forEach(photo => {
    photo.querySelector('input[name="remove_images"]').addEventListener('change', renderPhotos);
    photo.querySelector('[data-set-main]').addEventListener('click', event => setMain(event.currentTarget.dataset.setMain));
  });
  main.addEventListener('change', renderPhotos);
  input.addEventListener('change', () => {
    for (const file of input.files) uploads.push({ file, url: URL.createObjectURL(file) });
    input.value = '';
    renderPhotos();
    if (retained().length + uploads.length > 5) showErrors([{field:'images',label:'Photos',message:'A product may have at most 5 images, including existing photos. Remove a photo to continue.'}]);
  });
  renderPhotos();

  const search = document.getElementById('category-search');
  const category = form.elements.category;
  if (search && category) {
    const allOptions = Array.from(category.options, option => ({value:option.value,text:option.text}));
    search.closest('.entry-category-search').hidden = false;
    search.addEventListener('input', () => {
      const selected = category.value;
      const matches = allOptions.filter(option => !option.value || option.text.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()));
      // Preserve the current selection even if it does not match the typed filter.
      const options = allOptions.filter(option => option.value === selected || matches.includes(option));
      category.replaceChildren(...options.map(option => new Option(option.text, option.value, false, option.value === selected)));
      document.getElementById('category-search-status').textContent = `${matches.filter(option => option.value).length} matching categories. Your current selection is kept until you choose another.`;
    });
  }
  const pricingToggle = document.getElementById('apply-pricing');
  if (pricingToggle) {
    const pricingFields = document.getElementById('entry-pricing-fields');
    const updatePricing = () => { pricingFields.disabled = !pricingToggle.checked; };
    pricingToggle.addEventListener('change', updatePricing); updatePricing();
  }
  // Server validation keeps all upload and photo-selection state in this page.
  form.noValidate = true;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    if (retained().length + uploads.length > 5) {
      showErrors([{field:'images',label:'Photos',message:'A product may have at most 5 images, including existing photos.'}]); return;
    }
    const action = event.submitter || form.querySelector('button[type=submit][value=save]') || form.querySelector('button[type=submit][value=submit]');
    const body = new FormData(form);
    body.delete('images'); uploads.forEach(upload => body.append('images', upload.file));
    body.set('entry_action', action ? action.value : 'submit');
    const buttons = Array.from(form.querySelectorAll('button[type=submit]'));
    busy = true; buttons.forEach(button => { button.disabled = true; });
    form.setAttribute('aria-busy', 'true'); status.textContent = 'Saving product and photos…';
    let navigating = false;
    try {
      const response = await fetch(form.action, {method:'POST',body,credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
      if (response.status === 403) {
        showErrors([{message:'Your session or permissions changed. Check the product list and sign in again before saving.'}]);
        status.textContent = 'Save not authorized.'; return;
      }
      if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Unconfirmed save');
      const result = await response.json();
      if (response.ok && result.ok && result.redirect) {
        const destination = new URL(result.redirect, location.origin);
        if (destination.origin !== location.origin) throw new Error('Unexpected destination');
        navigating = true; status.textContent = 'Saved. Opening product…'; location.assign(destination.href); return;
      }
      if (!Array.isArray(result.errors) || !result.errors.length) throw new Error('Unconfirmed save');
      showErrors(result.errors); status.textContent = 'Not saved. Correct the details above; your selected photos are kept.';
    } catch (_) {
      showErrors([{message:'Saving could not be confirmed. Check the product list for this SKU before trying again. Do not submit a second product while the result is uncertain.'}]);
      status.textContent = 'Save result is uncertain. No automatic retry was made.';
    } finally {
      if (!navigating) { busy = false; buttons.forEach(button => { button.disabled = false; }); form.removeAttribute('aria-busy'); }
    }
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) { busy = false; form.removeAttribute('aria-busy'); form.querySelectorAll('button[type=submit]').forEach(button => { button.disabled = false; }); }
  });
})();
