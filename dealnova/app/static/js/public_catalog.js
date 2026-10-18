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
  function location3DIconMarkup(isApartment) {
    if (isApartment) {
      return (
        '<svg class="loc-3d-svg" viewBox="0 0 220 170" aria-hidden="true" focusable="false">' +
          '<defs>' +
            '<radialGradient id="aptShadow" cx="50%" cy="50%" r="50%">' +
              '<stop offset="0%" stop-color="#8b6b5d" stop-opacity="0.28"/>' +
              '<stop offset="100%" stop-color="#8b6b5d" stop-opacity="0"/>' +
            '</radialGradient>' +
            '<linearGradient id="aptBaseTop" x1="0" y1="0" x2="1" y2="1">' +
              '<stop offset="0%" stop-color="#c9d4f8"/>' +
              '<stop offset="100%" stop-color="#a8b8f0"/>' +
            '</linearGradient>' +
            '<linearGradient id="aptBaseSide" x1="0" y1="0" x2="1" y2="0">' +
              '<stop offset="0%" stop-color="#94a5e4"/>' +
              '<stop offset="100%" stop-color="#7c8fd6"/>' +
            '</linearGradient>' +
            '<linearGradient id="aptWallLeft" x1="0" y1="0" x2="0" y2="1">' +
              '<stop offset="0%" stop-color="#fce3be"/>' +
              '<stop offset="100%" stop-color="#f3ca96"/>' +
            '</linearGradient>' +
            '<linearGradient id="aptWallRight" x1="0" y1="0" x2="0" y2="1">' +
              '<stop offset="0%" stop-color="#e8b87d"/>' +
              '<stop offset="100%" stop-color="#d89f60"/>' +
            '</linearGradient>' +
            '<linearGradient id="aptRoofTop" x1="0" y1="0" x2="1" y2="1">' +
              '<stop offset="0%" stop-color="#f7b293"/>' +
              '<stop offset="100%" stop-color="#ea8f6a"/>' +
            '</linearGradient>' +
          '</defs>' +
          '<ellipse class="loc-3d-ground-shadow" cx="110" cy="144" rx="64" ry="16" fill="url(#aptShadow)"/>' +
          '<g class="loc-3d-floating-group">' +
            '<path d="M52 124 L110 146 L168 124 L168 132 Q168 135 164 137 L114 156 Q110 158 106 156 L56 137 Q52 135 52 132 Z" fill="url(#aptBaseSide)"/>' +
            '<path d="M106 102 Q110 100 114 102 L165 121 Q170 123 165 125 L114 145 Q110 147 106 145 L55 125 Q50 123 55 121 Z" fill="url(#aptBaseTop)"/>' +
            '<path d="M74 44 L110 58 L110 132 L74 118 Z" fill="url(#aptWallLeft)"/>' +
            '<path d="M110 58 L146 44 L146 118 L110 132 Z" fill="url(#aptWallRight)"/>' +
            '<path d="M69 40 Q110 25 110 25 L151 40 L110 56 Z" fill="url(#aptRoofTop)"/>' +
            '<path d="M69 40 L110 56 L110 63 L69 47 Z" fill="#e58c67"/>' +
            '<path d="M110 56 L151 40 L151 47 L110 63 Z" fill="#cf734e"/>' +
            '<g fill="#a3b5ef" stroke="#f49d78" stroke-width="2" stroke-linejoin="round">' +
              '<rect x="81" y="62" width="9" height="12" rx="4" transform="skewY(21)"/>' +
              '<rect x="95" y="62" width="9" height="12" rx="4" transform="skewY(21)"/>' +
              '<rect x="81" y="81" width="9" height="12" rx="4" transform="skewY(21)"/>' +
              '<rect x="95" y="81" width="9" height="12" rx="4" transform="skewY(21)"/>' +
            '</g>' +
            '<g fill="#8da1e2" stroke="#df8560" stroke-width="2" stroke-linejoin="round">' +
              '<rect x="116" y="114" width="9" height="12" rx="4" transform="skewY(-21)"/>' +
              '<rect x="130" y="114" width="9" height="12" rx="4" transform="skewY(-21)"/>' +
              '<rect x="116" y="133" width="9" height="12" rx="4" transform="skewY(-21)"/>' +
              '<rect x="130" y="133" width="9" height="12" rx="4" transform="skewY(-21)"/>' +
            '</g>' +
            '<path d="M88 106 Q92 104 96 106 L96 126 L88 123 Z" fill="#9fb2f2"/>' +
          '</g>' +
        '</svg>'
      );
    }
    return (
      '<svg class="loc-3d-svg" viewBox="0 0 220 170" aria-hidden="true" focusable="false">' +
        '<defs>' +
          '<radialGradient id="houseShadow" cx="50%" cy="50%" r="50%">' +
            '<stop offset="0%" stop-color="#476c6a" stop-opacity="0.26"/>' +
            '<stop offset="100%" stop-color="#476c6a" stop-opacity="0"/>' +
          '</radialGradient>' +
          '<linearGradient id="houseBaseTop" x1="0" y1="0" x2="1" y2="1">' +
            '<stop offset="0%" stop-color="#bde2d0"/>' +
            '<stop offset="100%" stop-color="#96ccb4"/>' +
          '</linearGradient>' +
          '<linearGradient id="houseBaseSide" x1="0" y1="0" x2="1" y2="0">' +
            '<stop offset="0%" stop-color="#82bca3"/>' +
            '<stop offset="100%" stop-color="#6ba88e"/>' +
          '</linearGradient>' +
          '<linearGradient id="houseWallLeft" x1="0" y1="0" x2="0" y2="1">' +
            '<stop offset="0%" stop-color="#fff5e4"/>' +
            '<stop offset="100%" stop-color="#f2dfc1"/>' +
          '</linearGradient>' +
          '<linearGradient id="houseWallRight" x1="0" y1="0" x2="0" y2="1">' +
            '<stop offset="0%" stop-color="#e7cfa8"/>' +
            '<stop offset="100%" stop-color="#d8ba8c"/>' +
          '</linearGradient>' +
          '<linearGradient id="houseRoofLeft" x1="0" y1="0" x2="1" y2="1">' +
            '<stop offset="0%" stop-color="#b8c7f4"/>' +
            '<stop offset="100%" stop-color="#95aae8"/>' +
          '</linearGradient>' +
          '<linearGradient id="houseRoofRight" x1="0" y1="0" x2="1" y2="1">' +
            '<stop offset="0%" stop-color="#8b9fe0"/>' +
            '<stop offset="100%" stop-color="#7489d1"/>' +
          '</linearGradient>' +
        '</defs>' +
        '<ellipse class="loc-3d-ground-shadow" cx="110" cy="144" rx="68" ry="16" fill="url(#houseShadow)"/>' +
        '<g class="loc-3d-floating-group">' +
          '<path d="M46 122 L110 146 L174 122 L174 130 Q174 134 169 136 L114 156 Q110 158 106 156 L51 136 Q46 134 46 130 Z" fill="url(#houseBaseSide)"/>' +
          '<path d="M106 98 Q110 96 114 98 L170 119 Q175 121 170 123 L114 145 Q110 147 106 145 L50 123 Q45 121 50 119 Z" fill="url(#houseBaseTop)"/>' +
          '<path d="M68 78 L106 94 L106 131 L68 116 Z" fill="url(#houseWallLeft)"/>' +
          '<path d="M106 94 L142 78 L142 116 L106 131 Z" fill="url(#houseWallRight)"/>' +
          '<path d="M68 78 L87 52 L106 94 Z" fill="#faebd4"/>' +
          '<path d="M61 81 L87 46 L112 56 L87 92 Z" fill="url(#houseRoofLeft)"/>' +
          '<path d="M87 46 L148 70 L124 102 L106 94 Z" fill="url(#houseRoofRight)"/>' +
          '<rect x="116" y="47" width="12" height="16" rx="3" fill="#e9d5b7"/>' +
          '<rect x="114" y="44" width="16" height="5" rx="2.5" fill="#f7ead5"/>' +
          '<path d="M88 102 Q93 100 97 102 L97 127 L88 123 Z" fill="#a7d7c2"/>' +
          '<circle cx="95" cy="115" r="1.6" fill="#eab308"/>' +
          '<rect x="73" y="88" width="11" height="11" rx="2.5" transform="skewY(21)" fill="#b8ccf5" stroke="#ffffff" stroke-width="1.8"/>' +
          '<g class="loc-3d-tree">' +
            '<rect x="148" y="102" width="5" height="14" rx="2" fill="#9c6b43"/>' +
            '<ellipse cx="150.5" cy="95" rx="10" ry="13" fill="#7eb89c"/>' +
            '<ellipse cx="148.5" cy="92" rx="6" ry="8" fill="#9ad0b5"/>' +
          '</g>' +
        '</g>' +
      '</svg>'
    );
  }
  function productService3DIconMarkup(isService) {
    if (isService) {
      return (
        '<svg class="loc-3d-svg" viewBox="0 0 220 176" aria-hidden="true" focusable="false">' +
          '<defs>' +
            '<radialGradient id="svcShadow" cx="50%" cy="50%" r="50%">' +
              '<stop offset="0%" stop-color="#312e81" stop-opacity="0.22"/>' +
              '<stop offset="100%" stop-color="#312e81" stop-opacity="0"/>' +
            '</radialGradient>' +
            '<linearGradient id="svcBaseTop" x1="0" y1="0" x2="1" y2="1">' +
              '<stop offset="0%" stop-color="#d4ddf7"/>' +
              '<stop offset="100%" stop-color="#b9c7ef"/>' +
            '</linearGradient>' +
            '<linearGradient id="svcBaseSide" x1="0" y1="0" x2="0" y2="1">' +
              '<stop offset="0%" stop-color="#9fb1e5"/>' +
              '<stop offset="100%" stop-color="#8498d6"/>' +
            '</linearGradient>' +
            '<linearGradient id="svcBoardFront" x1="0" y1="0" x2="1" y2="1">' +
              '<stop offset="0%" stop-color="#f5c9b8"/>' +
              '<stop offset="100%" stop-color="#e3ab96"/>' +
            '</linearGradient>' +
            '<linearGradient id="svcBoardSide" x1="0" y1="0" x2="0" y2="1">' +
              '<stop offset="0%" stop-color="#d6967f"/>' +
              '<stop offset="100%" stop-color="#bf7e67"/>' +
            '</linearGradient>' +
            '<linearGradient id="svcBellDome" x1="0" y1="0" x2="1" y2="1">' +
              '<stop offset="0%" stop-color="#f7da9e"/>' +
              '<stop offset="100%" stop-color="#dfb269"/>' +
            '</linearGradient>' +
          '</defs>' +
          '<ellipse class="loc-3d-ground-shadow" cx="110" cy="144" rx="68" ry="16" fill="url(#svcShadow)"/>' +
          '<g class="loc-3d-floating-group">' +
            '<path d="M46 122 L110 146 L174 122 L174 130 Q174 134 169 136 L114 156 Q110 158 106 156 L51 136 Q46 134 46 130 Z" fill="url(#svcBaseSide)"/>' +
            '<path d="M106 98 Q110 96 114 98 L170 119 Q175 121 170 123 L114 145 Q110 147 106 145 L50 123 Q45 121 50 119 Z" fill="url(#svcBaseTop)"/>' +
            '<g transform="rotate(-7 98 84)">' +
              '<rect x="64" y="42" width="66" height="82" rx="11" fill="url(#svcBoardSide)"/>' +
              '<rect x="60" y="39" width="66" height="82" rx="11" fill="url(#svcBoardFront)"/>' +
              '<rect x="67" y="48" width="52" height="66" rx="7" fill="#fbf3dc"/>' +
              '<rect x="78" y="33" width="30" height="14" rx="6" fill="#b4c2ec"/>' +
              '<circle cx="93" cy="39" r="3" fill="#7c8ec9"/>' +
              '<circle cx="93" cy="81" r="16" fill="#bbc8f2"/>' +
              '<path d="M86 81 L91 86 L101 75" fill="none" stroke="#ffffff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>' +
            '</g>' +
            '<g transform="translate(0, 2)">' +
              '<ellipse cx="142" cy="118" rx="20" ry="7" fill="#c68b67"/>' +
              '<ellipse cx="142" cy="115" rx="18" ry="6" fill="#dc9f7a"/>' +
              '<path d="M126 114 C126 95 158 95 158 114 Z" fill="url(#svcBellDome)"/>' +
              '<circle cx="142" cy="96" r="3.6" fill="#d39e54"/>' +
            '</g>' +
          '</g>' +
        '</svg>'
      );
    }
    return (
      '<svg class="loc-3d-svg" viewBox="0 0 220 176" aria-hidden="true" focusable="false">' +
        '<defs>' +
          '<radialGradient id="prodShadow" cx="50%" cy="50%" r="50%">' +
            '<stop offset="0%" stop-color="#064e3b" stop-opacity="0.22"/>' +
            '<stop offset="100%" stop-color="#064e3b" stop-opacity="0"/>' +
          '</radialGradient>' +
          '<linearGradient id="prodBaseTop" x1="0" y1="0" x2="1" y2="1">' +
            '<stop offset="0%" stop-color="#c4ead9"/>' +
            '<stop offset="100%" stop-color="#a2dec3"/>' +
          '</linearGradient>' +
          '<linearGradient id="prodBaseSide" x1="0" y1="0" x2="0" y2="1">' +
            '<stop offset="0%" stop-color="#84ccb0"/>' +
            '<stop offset="100%" stop-color="#66b596"/>' +
          '</linearGradient>' +
          '<linearGradient id="prodBagFront" x1="0" y1="0" x2="1" y2="1">' +
            '<stop offset="0%" stop-color="#68c199"/>' +
            '<stop offset="100%" stop-color="#479d76"/>' +
          '</linearGradient>' +
          '<linearGradient id="prodBagSide" x1="0" y1="0" x2="0" y2="1">' +
            '<stop offset="0%" stop-color="#3f8f6b"/>' +
            '<stop offset="100%" stop-color="#2f7455"/>' +
          '</linearGradient>' +
          '<linearGradient id="prodBoxTop" x1="0" y1="0" x2="1" y2="1">' +
            '<stop offset="0%" stop-color="#f0c79e"/>' +
            '<stop offset="100%" stop-color="#dfb082"/>' +
          '</linearGradient>' +
          '<linearGradient id="prodBoxLeft" x1="0" y1="0" x2="0" y2="1">' +
            '<stop offset="0%" stop-color="#dfa978"/>' +
            '<stop offset="100%" stop-color="#c9905e"/>' +
          '</linearGradient>' +
          '<linearGradient id="prodBoxRight" x1="0" y1="0" x2="0" y2="1">' +
            '<stop offset="0%" stop-color="#c78d5b"/>' +
            '<stop offset="100%" stop-color="#b17746"/>' +
          '</linearGradient>' +
        '</defs>' +
        '<ellipse class="loc-3d-ground-shadow" cx="110" cy="144" rx="68" ry="16" fill="url(#prodShadow)"/>' +
        '<g class="loc-3d-floating-group">' +
          '<path d="M46 122 L110 146 L174 122 L174 130 Q174 134 169 136 L114 156 Q110 158 106 156 L51 136 Q46 134 46 130 Z" fill="url(#prodBaseSide)"/>' +
          '<path d="M106 98 Q110 96 114 98 L170 119 Q175 121 170 123 L114 145 Q110 147 106 145 L50 123 Q45 121 50 119 Z" fill="url(#prodBaseTop)"/>' +
          '<path d="M77 62 C77 40 103 40 103 62" fill="none" stroke="#e4d4b3" stroke-width="6.5" stroke-linecap="round"/>' +
          '<path d="M62 64 Q60 58 66 57 L110 53 Q117 53 118 60 L122 108 Q122 116 114 118 L70 122 Q60 122 59 113 Z" fill="url(#prodBagSide)"/>' +
          '<path d="M56 64 Q55 57 62 56 L106 52 Q113 52 114 59 L118 108 Q118 116 110 118 L66 122 Q56 122 55 113 Z" fill="url(#prodBagFront)"/>' +
          '<ellipse cx="85" cy="58" rx="22" ry="4.5" fill="#2c6e50"/>' +
          '<path d="M71 63 C71 39 99 39 99 61" fill="none" stroke="#f8eed7" stroke-width="6.5" stroke-linecap="round"/>' +
          '<circle cx="71" cy="64" r="3.2" fill="#275e45"/>' +
          '<circle cx="99" cy="62" r="3.2" fill="#275e45"/>' +
          '<g>' +
            '<path d="M108 92 L134 82 L160 92 L134 102 Z" fill="url(#prodBoxTop)"/>' +
            '<path d="M108 92 L134 102 L134 128 L108 117 Z" fill="url(#prodBoxLeft)"/>' +
            '<path d="M134 102 L160 92 L160 117 L134 128 Z" fill="url(#prodBoxRight)"/>' +
            '<path d="M120 87 L146 97 L146 108 L140 110 L140 99 L114 89 Z" fill="#f7eedb" opacity="0.92"/>' +
            '<rect x="142" y="112" width="10" height="5" rx="1.5" transform="skewY(-21)" fill="#f7eedb" opacity="0.85"/>' +
          '</g>' +
        '</g>' +
      '</svg>'
    );
  }
  function isPlaceholderImageUrl(url) {
    return !url || /\/img\/placeholders\//i.test(String(url));
  }
  function imageFor(item) {
    var media = node('div', 'u-item-media catalog-media');
    if (item.item_type === 'location') {
      if (item.image_url && !isPlaceholderImageUrl(item.image_url)) {
        var locImg = node('img'); locImg.src = safeURL(item.image_url, ''); locImg.alt = item.name || ''; locImg.loading = 'lazy'; locImg.decoding = 'async'; locImg.width = 300; locImg.height = 230;
        locImg.addEventListener('error', function () { locImg.remove(); media.appendChild(placeholder(item)); }, { once: true }); media.appendChild(locImg);
      } else if (item.video_url && !isPlaceholderImageUrl(item.video_url)) {
        var locVid = node('video', 'catalog-media-video'); locVid.src = safeURL(item.video_url, ''); locVid.muted = true; locVid.loop = true; locVid.playsInline = true; locVid.autoplay = true; locVid.preload = 'metadata';
        locVid.addEventListener('error', function () { locVid.remove(); media.appendChild(placeholder(item)); }, { once: true }); media.appendChild(locVid);
      } else {
        media.appendChild(placeholder(item));
      }
      return media;
    }
    if (item.image_url && !isPlaceholderImageUrl(item.image_url)) {
      var image = node('img'); image.src = safeURL(item.image_url, ''); image.alt = item.name || ''; image.loading = 'lazy'; image.decoding = 'async'; image.width = 300; image.height = 230;
      image.addEventListener('error', function () { image.remove(); media.appendChild(placeholder(item)); }, { once: true }); media.appendChild(image);
    } else media.appendChild(placeholder(item));
    return media;
  }
  function placeholder(item) {
    var type = item && item.item_type ? item.item_type : 'product';
    if (type === 'location') {
      var isApartment = ['apartment', 'studio', 'room'].indexOf(String(item.property_type || '').toLowerCase()) !== -1;
      var wrap = node('span', 'catalog-image-placeholder loc-3d-placeholder ' + (isApartment ? 'is-apartment' : 'is-house'));
      var stage = node('span', 'loc-3d-stage');
      stage.innerHTML = location3DIconMarkup(isApartment);
      var badge = node('span', 'loc-3d-badge', 'Aucune photo');
      wrap.appendChild(stage);
      wrap.appendChild(badge);
      return wrap;
    }
    if (type === 'product' || type === 'service') {
      var isService = type === 'service' || (item && item.kind === 'service');
      var pWrap = node('span', 'catalog-image-placeholder loc-3d-placeholder ' + (isService ? 'is-service' : 'is-product'));
      var pStage = node('span', 'loc-3d-stage');
      pStage.innerHTML = productService3DIconMarkup(isService);
      var pBadge = node('span', 'loc-3d-badge', 'Aucune photo');
      pWrap.appendChild(pStage);
      pWrap.appendChild(pBadge);
      return pWrap;
    }
    var el = node('span', 'catalog-image-placeholder');
    el.appendChild(icon(type === 'shop' ? 'shop' : 'image'));
    el.appendChild(node('span', '', 'Aucune photo'));
    return el;
  }
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
