(function () {
  'use strict';

  function init(form) {
    var input = form.querySelector('input[name="q"]');
    var clear = form.querySelector('.hub-search-clear');
    var panel = form.querySelector('[data-search-panel]');
    var status = form.querySelector('[data-search-status]');
    var list = form.querySelector('[role="listbox"]');
    var all = form.querySelector('[data-search-all]');
    var isHome = form.id === 'homeSearchForm';
    var timer, controller, sequence = 0, active = -1, composing = false, choosingResult = false;

    function cancel() {
      clearTimeout(timer);
      if (controller) controller.abort();
      controller = null;
      sequence += 1;
    }
    function select(index) {
      var options = list.querySelectorAll('[role="option"]');
      active = index;
      options.forEach(function (option, position) { option.setAttribute('aria-selected', String(position === index)); });
      if (options[index]) {
        input.setAttribute('aria-activedescendant', options[index].id);
        options[index].scrollIntoView({ block: 'nearest' });
      } else input.removeAttribute('aria-activedescendant');
    }
    function close() {
      cancel();
      panel.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      list.setAttribute('aria-busy', 'false');
      select(-1);
    }
    function fitPanel() {
      var viewport = window.visualViewport;
      var bottom = viewport ? viewport.offsetTop + viewport.height : innerHeight;
      form.style.setProperty('--hub-search-available-height', Math.max(100, bottom - form.getBoundingClientRect().bottom - 16) + 'px');
    }
    function show() {
      fitPanel();
      panel.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    }
    function updateClear() { clear.style.display = input.value ? 'inline-flex' : 'none'; }
    function safeUrl(value) {
      if (!value || typeof value !== 'string' || !value.trim()) return '';
      try {
        var url = new URL(value, window.location.origin);
        return url.origin === window.location.origin && /^https?:$/.test(url.protocol) ? url.href : '';
      } catch (_) {
        return '';
      }
    }
    function render(items) {
      var fragment = document.createDocumentFragment();
      items.forEach(function (item, index) {
        var href = safeUrl(item.url);
        if (!href) return;
        var row = document.createElement('li');
        row.setAttribute('role', 'presentation');
        var link = document.createElement('a');
        link.className = 'hub-live-search-result';
        link.href = href;
        link.id = list.id + '-' + index;
        link.tabIndex = -1;
        link.setAttribute('role', 'option');
        link.setAttribute('aria-selected', 'false');
        if (isHome && (item.item_type === 'product' || item.item_type === 'service')) link.dataset.openProductDetail = item.id;
        if (isHome && item.item_type === 'shop') link.dataset.openShopDetail = item.slug;
        var imgUrl = safeUrl(item.image_url);
        if (imgUrl) {
          var image = document.createElement('img');
          image.src = imgUrl;
          image.alt = '';
          image.width = image.height = 48;
          image.loading = 'lazy';
          image.addEventListener('error', function () { image.hidden = true; }, { once: true });
          link.appendChild(image);
        }
        var copy = document.createElement('span');
        copy.className = 'hub-live-search-copy';
        var name = document.createElement('strong');
        name.textContent = item.name;
        var detail = document.createElement('small');
        var type = { product: 'Produit', service: 'Service', shop: 'Boutique', location: 'Location' }[item.item_type] || '';
        detail.textContent = type + (typeof item.final_price === 'number' ? ' · ' + new Intl.NumberFormat('fr-MA', { maximumFractionDigits: 2 }).format(item.final_price) + ' DH' : '');
        copy.append(name, detail);
        link.appendChild(copy);
        row.appendChild(link);
        fragment.appendChild(row);
      });
      list.replaceChildren(fragment);
      select(-1);
    }
    async function search(query, requestId) {
      controller = new AbortController();
      var requestController = controller;
      var timeout = setTimeout(function () { requestController.abort(); }, 10000);
      try {
        var url = new URL(form.dataset.searchUrl, window.location.origin);
        url.search = new URLSearchParams({ universe: 'search', q: query, per_page: '6' }).toString();
        var response = await fetch(url, { credentials: 'same-origin', signal: requestController.signal });
        if (!response.ok) throw new Error('Search unavailable');
        var payload = await response.json();
        if (requestId !== sequence || input.value.trim() !== query) return;
        if (!payload.success || !Array.isArray(payload.items)) throw new Error('Invalid search');
        render(payload.items.slice(0, 6));
        var total = payload.pagination.total;
        status.textContent = total ? total + (total === 1 ? ' résultat' : ' résultats') : 'Aucun résultat. Essayez un autre mot.';
        all.hidden = !total;
      } catch (_error) {
        if (requestId !== sequence) return;
        list.replaceChildren();
        status.textContent = 'Recherche indisponible. Réessayez dans un instant.';
        all.hidden = false;
      } finally {
        clearTimeout(timeout);
        if (requestId === sequence) {
          controller = null;
          list.setAttribute('aria-busy', 'false');
        }
      }
    }
    function queue() {
      cancel();
      updateClear();
      var query = input.value.trim();
      if (!query || composing) { close(); return; }
      list.replaceChildren();
      select(-1);
      status.textContent = 'Recherche…';
      list.setAttribute('aria-busy', 'true');
      all.hidden = true;
      var href = new URL(form.action);
      href.searchParams.set('q', query);
      all.href = href.href;
      show();
      var requestId = sequence;
      timer = setTimeout(function () { search(query, requestId); }, 280);
    }
    input.addEventListener('input', queue);
    input.addEventListener('search', queue);
    input.addEventListener('compositionstart', function () { composing = true; close(); });
    input.addEventListener('compositionend', function () { composing = false; queue(); });
    input.addEventListener('click', function () { if (panel.hidden && input.value.trim()) queue(); });
    input.addEventListener('keydown', function (event) {
      if (composing || event.isComposing || event.keyCode === 229) {
        if (event.key === 'Enter') event.stopImmediatePropagation();
        return;
      }
      if (panel.hidden) return;
      var options = list.querySelectorAll('[role="option"]');
      if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && options.length) {
        event.preventDefault();
        event.stopImmediatePropagation();
        select(active < 0 ? (event.key === 'ArrowDown' ? 0 : options.length - 1) :
          (active + (event.key === 'ArrowDown' ? 1 : options.length - 1)) % options.length);
      } else if (event.key === 'Enter' && active >= 0) {
        event.preventDefault();
        event.stopImmediatePropagation();
        options[active].click();
        close();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        event.stopImmediatePropagation();
        close();
      }
    }, true);
    clear.addEventListener('click', function () { input.value = ''; close(); updateClear(); input.focus(); });
    // Safari can blur the input before the chosen link receives its click.
    // Preserve touch gestures and keep the list available until selection.
    panel.addEventListener('pointerdown', function (event) {
      if (!event.target.closest('a')) return;
      choosingResult = true;
      if (event.pointerType === 'mouse') event.preventDefault();
    });
    document.addEventListener('pointerup', function () { setTimeout(function () { choosingResult = false; }, 0); });
    document.addEventListener('pointercancel', function () { choosingResult = false; });
    all.addEventListener('click', function (event) {
      if (isHome) { event.preventDefault(); form.requestSubmit(); }
      close();
    });
    form.addEventListener('submit', close, true);
    form.addEventListener('focusout', function (event) { if (!choosingResult && !form.contains(event.relatedTarget)) close(); });
    document.addEventListener('click', function (event) {
      if (!form.contains(event.target) || (panel.contains(event.target) && event.target.closest('a'))) close();
    }, true);
    document.addEventListener('visibilitychange', function () { if (document.hidden) close(); });
    window.addEventListener('pagehide', close);
    window.addEventListener('resize', fitPanel, { passive: true });
    if (window.visualViewport) window.visualViewport.addEventListener('resize', fitPanel, { passive: true });
    updateClear();
  }

  function boot() { document.querySelectorAll('[data-live-search]').forEach(init); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
