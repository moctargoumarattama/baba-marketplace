(function () {
  'use strict';
  var filterKeys = ['cat', 'shop', 'city', 'listing_type', 'property_type', 'min_price', 'max_price', 'stock', 'promo', 'sort', 'page'];
  var aliases = { type: 'listing_type', min: 'min_price', max: 'max_price' };
  var state = null;
  var requestId = 0;
  var controller = null;
  var timer = null;
  var elements = null;
  var cache = new Map();
  var money = new Intl.NumberFormat('fr-MA', { maximumFractionDigits: 2 });
  var labels = { cat: 'Catégorie', shop: 'Boutique', city: 'Ville', listing_type: 'Durée', property_type: 'Bien', min_price: 'Dès', max_price: 'Jusqu’à', stock: 'En stock', promo: 'Promotions' };

  function node(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function icon(name) { var el = node('i', 'bi bi-' + name); el.setAttribute('aria-hidden', 'true'); return el; }
  function button(text, action, className) { var el = node('button', className, text); el.type = 'button'; if (action) el.addEventListener('click', action); return el; }
  function safeURL(value, fallback) {
    try { var url = new URL(value || fallback, location.origin); return url.origin === location.origin && /^https?:$/.test(url.protocol) ? url.href : fallback; }
    catch (_) { return fallback; }
  }
  function normalizedFilters(input) {
    var output = {};
    Object.keys(input || {}).forEach(function (key) {
      var name = aliases[key] || key;
      if (filterKeys.indexOf(name) === -1 || input[key] === '' || input[key] === null || input[key] === undefined || input[key] === false) return;
      if (name === 'stock' || name === 'promo') {
        if (String(input[key]).toLowerCase() === 'true') { output[name] = '1'; return; }
        if (String(input[key]).toLowerCase() === 'false' || String(input[key]) === '0') return;
      }
      output[name] = String(input[key] === true ? '1' : input[key]);
    });
    output.page = output.page || '1';
    output.sort = output.sort || 'new';
    output.sort = { price_asc: 'low', price_desc: 'high', newest: 'new' }[output.sort] || output.sort;
    return output;
  }
  function snapshot() { return state ? { universe: state.universe, query: state.query, filters: Object.assign({}, state.filters) } : null; }
  function announceState() { document.dispatchEvent(new CustomEvent('bm:catalog-state', { detail: snapshot() })); }
  function init() {
    if (elements) return true;
    var results = document.getElementById('catalogResults');
    if (!results) return false;
    elements = { results: results, form: document.getElementById('catalogFilters'), toolbar: document.getElementById('catalogToolbar'), toggle: document.getElementById('catalogFilterToggle'), count: document.getElementById('catalogFilterCount'), sort: document.getElementById('catalogSort'), pagination: document.getElementById('catalogPagination'), pageStatus: document.getElementById('catalogPageStatus'), prev: document.getElementById('catalogPrevious'), next: document.getElementById('catalogNext'), active: document.getElementById('catalogActiveFilters'), error: document.getElementById('catalogFilterError'), body: document.getElementById('uModalBody'), total: document.getElementById('uModalCount') };
    elements.toggle.addEventListener('click', function () {
      elements.form.hidden = !elements.form.hidden;
      elements.toggle.setAttribute('aria-expanded', String(!elements.form.hidden));
      if (!elements.form.hidden) {
        elements.body.scrollTo({ top: 0, behavior: 'auto' });
        var first = elements.form.querySelector('label:not([hidden]) :is(input,select)');
        if (first) first.focus({ preventScroll: true });
      }
    });
    elements.form.addEventListener('submit', function (event) {
      event.preventDefault();
      var values = {};
      new FormData(elements.form).forEach(function (value, key) {
        var field = elements.form.querySelector('[name="' + key + '"]');
        if (value && field && !field.closest('[hidden]')) values[key] = value;
      });
      if (values.min_price && values.max_price && Number(values.min_price) > Number(values.max_price)) {
        elements.error.textContent = 'Le prix minimum doit être inférieur au prix maximum.';
        elements.error.hidden = false;
        return;
      }
      elements.error.hidden = true;
      state.filters = normalizedFilters(Object.assign(values, { sort: elements.sort.value, page: '1' }));
      elements.form.hidden = true;
      elements.toggle.setAttribute('aria-expanded', 'false');
      elements.toggle.focus({ preventScroll: true });
      announceState(); load(true);
    });
    document.querySelectorAll('[data-catalog-reset]').forEach(function (el) { el.addEventListener('click', reset); });
    elements.sort.addEventListener('change', function () { state.filters.sort = elements.sort.value; state.filters.page = '1'; announceState(); load(true); });
    elements.prev.addEventListener('click', function () { changePage(-1); });
    elements.next.addEventListener('click', function () { changePage(1); });
    return true;
  }
  function changePage(direction) {
    state.filters.page = String(Math.max(1, Number(state.filters.page || 1) + direction));
    announceState(); load(true, true);
  }
  function reset() {
    if (!state) return;
    state.filters = normalizedFilters({}); state.query = '';
    var search = document.getElementById('uModalSearchInput');
    if (search) search.value = '';
    var clear = document.getElementById('uModalSearchClear'); if (clear) clear.style.display = 'none';
    elements.form.hidden = true; elements.toggle.setAttribute('aria-expanded', 'false');
    announceState(); load(true);
  }
  function visibleFields() {
    var universe = state.universe;
    var allowed = universe === 'shops' ? ['city'] : universe === 'locations' ? ['shop', 'city', 'listing_type', 'property_type', 'min_price', 'max_price'] : ['cat', 'shop', 'city', 'min_price', 'max_price', 'stock', 'promo'];
    if (universe === 'services') allowed = allowed.filter(function (key) { return key !== 'stock'; });
    if (universe === 'promotions') allowed = allowed.filter(function (key) { return key !== 'promo'; });
    if (universe === 'search') allowed = allowed.concat(['listing_type', 'property_type']);
    elements.form.querySelectorAll('[data-catalog-field]').forEach(function (el) { el.hidden = allowed.indexOf(el.dataset.catalogField) === -1; });
    elements.sort.closest('label').hidden = universe === 'shops';
  }
  function updateForm(facets) {
    [['cat', 'categories', 'Toutes les catégories'], ['shop', 'shops', 'Toutes les boutiques']].forEach(function (spec) {
      var select = elements.form.elements[spec[0]];
      select.replaceChildren(node('option', '', spec[2])); select.firstChild.value = '';
      (facets[spec[1]] || []).forEach(function (item) { var option = node('option', '', item.name); option.value = item.id; select.appendChild(option); });
      var selected = state.filters[spec[0]];
      if (selected && !Array.prototype.some.call(select.options, function (opt) { return opt.value === selected; })) { var extra = node('option', '', spec[0] === 'shop' ? 'Boutique sélectionnée' : 'Catégorie sélectionnée'); extra.value = selected; select.appendChild(extra); }
    });
    var cities = document.getElementById('catalogCities'); cities.replaceChildren();
    (facets.cities || []).forEach(function (city) { var option = node('option'); option.value = typeof city === 'string' ? city : city.name; cities.appendChild(option); });
    filterKeys.forEach(function (key) { var input = elements.form.elements[key]; if (!input) return; if (input.type === 'checkbox') input.checked = state.filters[key] === '1'; else input.value = state.filters[key] || ''; });
    elements.sort.value = state.filters.sort || 'new';
  }
  function renderActive() {
    elements.active.replaceChildren();
    var keys = Object.keys(state.filters).filter(function (key) { return labels[key] && state.filters[key] && state.filters[key] !== '0'; });
    keys.forEach(function (key) {
      var value = state.filters[key];
      var field = elements.form.elements[key];
      if (field && field.tagName === 'SELECT' && field.selectedOptions.length) value = field.selectedOptions[0].textContent;
      var text = key === 'stock' || key === 'promo' ? labels[key] : labels[key] + ' : ' + value + (/price/.test(key) ? ' DH' : '');
      var chip = button(text, function () { delete state.filters[key]; state.filters.page = '1'; announceState(); load(true); }, 'catalog-filter-chip');
      chip.appendChild(icon('x')); chip.setAttribute('aria-label', 'Retirer le filtre ' + text); elements.active.appendChild(chip);
    });
    elements.count.textContent = keys.length; elements.count.hidden = !keys.length;
    elements.active.hidden = !keys.length;
  }
  function imageFor(item) {
    var media = node('div', 'u-item-media catalog-media');
    if (item.image_url) {
      var image = node('img'); image.src = safeURL(item.image_url, ''); image.alt = item.name || ''; image.loading = 'lazy'; image.decoding = 'async'; image.width = 300; image.height = 230;
      image.addEventListener('error', function () { image.remove(); media.appendChild(placeholder(item)); }, { once: true }); media.appendChild(image);
    } else media.appendChild(placeholder(item));
    return media;
  }
  function placeholder(item) { var el = node('span', 'catalog-image-placeholder'); el.appendChild(icon(item.item_type === 'shop' ? 'shop' : item.item_type === 'location' ? 'house-door' : 'image')); el.appendChild(node('span', '', 'Sans photo')); return el; }
  function priceLabel(item, value) {
    if (item.item_type === 'location' && Number(value || 0) <= 0) return 'Prix sur demande';
    return money.format(Number(value || 0)) + ' DH' + (item.item_type === 'location' ? (item.listing_type === 'monthly' ? ' / mois' : ' / jour') : '');
  }
  function itemCard(item) {
    var type = item.item_type || 'product';
    var card = node('article', 'u-item-card catalog-item'); card.dataset.itemType = type;
    var mediaLink = node('a', 'u-item-link-media'); mediaLink.href = safeURL(item.url, '/'); mediaLink.setAttribute('aria-label', 'Voir : ' + item.name); mediaLink.appendChild(imageFor(item));
    var content = node('div', 'u-item-content');
    var titleLink = node('a', 'u-item-title-link'); titleLink.href = mediaLink.href;
    if (type === 'product' || type === 'service') { mediaLink.dataset.openProductDetail = item.id; titleLink.dataset.openProductDetail = item.id; card.dataset.productId = item.id; }
    if (type === 'shop') { mediaLink.dataset.openShopDetail = item.slug; titleLink.dataset.openShopDetail = item.slug; }
    titleLink.appendChild(node('h3', 'u-item-title', item.name)); content.appendChild(titleLink);
    if (type === 'location') { var locality = node('p', 'catalog-locality', [item.city, item.area].filter(Boolean).join(' · ')); content.appendChild(locality); }
    else if (item.shop_name && type !== 'shop') content.appendChild(node('p', 'catalog-locality', item.shop_name));
    if (item.description) content.appendChild(node('p', 'u-item-desc', item.description));
    if (type !== 'shop') {
      var prices = node('div', 'catalog-prices'); prices.appendChild(node('span', 'u-item-price', priceLabel(item, item.final_price)));
      if (item.has_promo && Number(item.price) > Number(item.final_price)) { prices.appendChild(node('del', '', priceLabel(item, item.price))); mediaLink.appendChild(node('span', 'catalog-promo', 'Promotion')); }
      content.appendChild(prices);
    }
    var actions = node('div', 'u-item-actions catalog-item-actions');
    if (type === 'product') {
      var add = button('', null, 'u-item-btn u-btn-cart'); add.appendChild(icon('bag-plus')); add.appendChild(node('span', '', 'Ajouter'));
      add.dataset.cartAddBtn = item.id; add.setAttribute('aria-label', 'Ajouter au panier : ' + item.name);
      if (item.available === false || Number(item.stock) <= 0) { add.disabled = true; add.replaceChildren(node('span', '', Number(item.stock) <= 0 ? 'Indisponible' : 'Boutique fermée')); }
      actions.appendChild(add);
    } else if (type === 'service') { var book = node('a', 'u-item-btn', 'Réserver'); book.href = safeURL(item.booking_url, mediaLink.href); actions.appendChild(book); }
    var detail = node('a', 'u-item-btn u-btn-detail', type === 'shop' ? 'Visiter la boutique' : type === 'location' ? 'Voir l’annonce' : 'Détails'); detail.href = mediaLink.href;
    if (type === 'product' || type === 'service') detail.dataset.openProductDetail = item.id;
    if (type === 'shop') detail.dataset.openShopDetail = item.slug;
    actions.appendChild(detail); content.appendChild(actions); card.appendChild(mediaLink); card.appendChild(content); return card;
  }
  function emptyState(error) {
    var hasFilters = Object.keys((state && state.filters) || {}).some(function (k) {
      return k !== 'sort' && k !== 'page' && state.filters[k];
    }) || Boolean((state && state.query || '').trim());
    var box = node('div', 'catalog-empty');
    box.appendChild(icon(error ? 'wifi-off' : (hasFilters ? 'search' : 'inbox')));
    box.appendChild(node('h3', '', error ? 'Le catalogue est momentanément indisponible' : (hasFilters ? 'Aucun résultat pour ces critères' : 'Aucune offre disponible pour le moment')));
    box.appendChild(node('p', '', error || (hasFilters ? 'Modifiez votre recherche ou retirez un filtre.' : 'Revenez bientôt découvrir de nouvelles offres.')));
    if (error) {
      box.appendChild(button('Réessayer', function () { load(true, false, true); }, 'hub-primary-btn'));
      box.appendChild(button('Effacer les filtres', reset, 'catalog-reset'));
    } else if (hasFilters) {
      box.appendChild(button('Réinitialiser les filtres', reset, 'hub-primary-btn'));
    }
    return box;
  }
  function setLoading() {
    elements.results.setAttribute('aria-busy', 'true'); elements.results.classList.add('is-loading'); elements.pagination.hidden = true;
    elements.results.replaceChildren();
    for (var i = 0; i < 6; i++) { var card = node('div', 'catalog-skeleton'); card.setAttribute('aria-hidden', 'true'); card.innerHTML = '<span></span><i></i><i></i>'; elements.results.appendChild(card); }
    if (elements.total) elements.total.textContent = 'Chargement…';
  }
  function render(data, scroll, focus) {
    if (data.pagination) state.filters.page = String(data.pagination.page);
    updateForm(data.facets || {}); renderActive();
    var fragment = document.createDocumentFragment(); (data.items || []).forEach(function (item) { fragment.appendChild(itemCard(item)); });
    if (!(data.items || []).length) fragment.appendChild(emptyState());
    elements.results.replaceChildren(fragment); elements.results.classList.remove('is-loading'); elements.results.setAttribute('aria-busy', 'false');
    var pagination = data.pagination || { total: 0, page: 1, pages: 1 };
    if (elements.total) elements.total.textContent = pagination.total + (state.universe === 'shops' ? ' boutique' : ' résultat') + (pagination.total > 1 ? 's' : '');
    elements.pagination.hidden = pagination.pages <= 1;
    elements.prev.disabled = !pagination.has_prev; elements.next.disabled = !pagination.has_next;
    elements.pageStatus.textContent = 'Page ' + pagination.page + ' sur ' + Math.max(1, pagination.pages);
    if (scroll) elements.body.scrollTo({ top: 0, behavior: 'auto' });
    if (state.restoreScroll !== null) {
      elements.body.scrollTop = state.restoreScroll;
      state.restoreScroll = null;
    }
    if (focus) { var target = elements.results.querySelector('a,button') || elements.results; target.tabIndex = target.tabIndex < 0 ? -1 : target.tabIndex; target.focus({ preventScroll: true }); }
    announceState();
  }
  function load(scroll, focus, force) {
    if (!state || !elements) return;
    var id = ++requestId;
    if (controller) controller.abort();
    var params = new URLSearchParams(Object.assign({ universe: state.universe, q: state.query, per_page: '12' }, state.filters));
    var key = params.toString(), saved = cache.get(key);
    if (!force && saved && Date.now() - saved.at < 20000) { render(saved.data, scroll, focus); return; }
    controller = new AbortController(); setLoading();
    fetch('/api/catalog?' + key, { signal: controller.signal, headers: { Accept: 'application/json' } }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || !data.success) {
          var error = new Error(data.message || 'Réessayez dans un instant.');
          error.userMessage = error.message;
          throw error;
        }
        return data;
      });
    }).then(function (data) {
      if (id !== requestId) return;
      cache.set(key, { at: Date.now(), data: data }); if (cache.size > 20) cache.delete(cache.keys().next().value);
      render(data, scroll, focus);
    }).catch(function (error) {
      if (error.name === 'AbortError' || id !== requestId) return;
      elements.results.replaceChildren(emptyState(error.userMessage || 'Vérifiez votre connexion, puis réessayez.')); elements.results.classList.remove('is-loading'); elements.results.setAttribute('aria-busy', 'false'); elements.pagination.hidden = true;
      if (elements.total) elements.total.textContent = 'Chargement impossible';
    });
  }
  function open(universe, query, filters, scrollTop) {
    if (!init()) return false;
    clearTimeout(timer);
    state = { universe: universe || 'products', query: (query || '').trim(), filters: normalizedFilters(filters || {}), restoreScroll: scrollTop === undefined ? null : scrollTop };
    elements.toolbar.hidden = false; visibleFields(); elements.form.hidden = true; elements.toggle.setAttribute('aria-expanded', 'false'); elements.error.hidden = true;
    elements.sort.value = state.filters.sort;
    load(true); return true;
  }
  function search(query) {
    if (!state || !elements) return;
    clearTimeout(timer); state.query = (query || '').trim(); state.filters.page = '1';
    if (controller) controller.abort(); ++requestId;
    announceState(); timer = setTimeout(function () { load(true); }, 280);
  }
  function pause() { clearTimeout(timer); if (controller) controller.abort(); ++requestId; }
  window.BMCatalog = { open: open, search: search, reset: reset, snapshot: snapshot, pause: pause, filterKeys: filterKeys, normalizeFilters: normalizedFilters, createCard: itemCard };
})();
