(() => {
  'use strict';
  document.querySelectorAll('[data-search-suggestions]').forEach((form, instance) => {
  const input = form.querySelector('input[name="q"]');
  const panel = document.createElement('div');
  panel.className = 'search-suggestions';
  panel.hidden = true;
  const list = document.createElement('div');
  list.id = `search-suggestion-list-${instance}`;
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', 'Search suggestions');
  const status = document.createElement('div');
  status.className = 'search-suggestion-status';
  status.setAttribute('role', 'status');
  panel.append(status, list);
  form.append(panel);
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', list.id);
  input.setAttribute('aria-expanded', 'false');
  input.setAttribute('autocomplete', 'off');
  input.setAttribute('maxlength', '100');
  let timer, controller, sequence = 0, active = -1, options = [];
  function close() {
    clearTimeout(timer);
    controller?.abort();
    sequence++;
    panel.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  }
  function show() {
    panel.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }
  function select(index) {
    active = index;
    options.forEach((option, i) => option.setAttribute('aria-selected', String(i === index)));
    input.setAttribute('aria-activedescendant', options[index].id);
    options[index].scrollIntoView({block: 'nearest'});
  }
  function addOption(label, detail, url) {
    const option = document.createElement('a');
    option.id = `search-option-${instance}-${options.length}`;
    option.href = url;
    option.setAttribute('role', 'option');
    option.setAttribute('aria-selected', 'false');
    option.tabIndex = -1;
    const title = document.createElement('span');
    title.textContent = label;
    const subtitle = document.createElement('small');
    subtitle.textContent = detail;
    option.append(title, subtitle);
    list.append(option);
    options.push(option);
    // Preserve input focus until the link click is dispatched.
    option.addEventListener('mousedown', event => event.preventDefault());
  }
  function schedule() {
    close();
    if (input.value.trim().length < 1) return;
    const current = sequence;
    timer = setTimeout(async () => {
      controller = new AbortController();
      list.replaceChildren();
      options = [];
      status.textContent = 'Searching…';
      show();
      const query = input.value.trim();
      try {
        const url = new URL(form.dataset.searchSuggestions, location.origin);
        url.searchParams.set('q', query);
        const response = await fetch(url, {signal: controller.signal, headers: {Accept: 'application/json'}});
        if (!response.ok) throw new Error('Search unavailable');
        const data = await response.json();
        if (current !== sequence) return;
        let group = '';
        data.results.forEach(result => {
          if (group !== result.kind) {
            const heading = document.createElement('div');
            heading.className = 'search-suggestion-group';
            heading.setAttribute('role', 'presentation');
            heading.textContent = result.kind === 'Product' ? 'Products' : 'Categories';
            list.append(heading);
            group = result.kind;
          }
          addOption(result.label, result.detail, result.url);
        });
        status.textContent = data.results.length ? `${data.results.length} ${data.results.length === 1 ? 'suggestion' : 'suggestions'}. Use arrow keys to browse.` : 'No suggestions yet. Try another spelling or view all results.';
        const all = new URL(input.form.action || location.href);
        all.searchParams.set('q', query);
        addOption(`View all results for “${query}”`, 'Search the catalogue', all.href);
      } catch (error) {
        if (error.name === 'AbortError' || current !== sequence) return;
        status.textContent = 'Suggestions unavailable. Press Enter to search.';
      }
    }, 200);
  }
  input.addEventListener('input', event => { if (!event.isComposing) schedule(); });
  input.addEventListener('compositionend', schedule);
  input.addEventListener('focus', schedule);
  input.addEventListener('keydown', event => {
    if (event.isComposing) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key === 'Tab') { close(); return; }
    if (!panel.hidden && options.length && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      select(active < 0 ? (event.key === 'ArrowDown' ? 0 : options.length - 1) :
        (active + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length);
    } else if (event.key === 'Enter' && !panel.hidden && active >= 0) {
      event.preventDefault();
      options[active].click();
    }
  });
  document.addEventListener('pointerdown', event => { if (!form.contains(event.target)) close(); });
  form.addEventListener('focusout', event => { if (!form.contains(event.relatedTarget)) close(); });
  input.form.addEventListener('submit', close);
  });
})();
