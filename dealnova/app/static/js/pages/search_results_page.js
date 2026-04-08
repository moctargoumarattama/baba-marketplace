(function () {
"use strict";

function readConfig(configId, fallbackConfig) {
  const fallback = fallbackConfig || {};
  const node = document.getElementById(configId);
  if (!node) return fallback;
  try {
    const parsed = JSON.parse(node.textContent || "{}");
    if (!parsed || typeof parsed !== "object") return fallback;
    return parsed;
  } catch (_error) {
    return fallback;
  }
}

const pageConfig = readConfig("searchResultsPageConfig", {
  api: {
    cartAddBase: "/cart/api/add",
    searchProducts: "/api/search/products",
    searchShops: "/api/search/shops",
    searchCategories: "/api/search/categories",
    searchLocations: "/api/search/locations",
    shopHome: "/shop",
  },
});
const apiConfig = pageConfig.api || {};
const endpointCartAddBase = String(apiConfig.cartAddBase || "/cart/api/add");
const endpointSearchProducts = String(apiConfig.searchProducts || "/api/search/products");
const endpointSearchShops = String(apiConfig.searchShops || "/api/search/shops");
const endpointSearchCategories = String(apiConfig.searchCategories || "/api/search/categories");
const endpointSearchLocations = String(apiConfig.searchLocations || "/api/search/locations");
const endpointShopHome = String(apiConfig.shopHome || "/shop");
const searchInput = document.getElementById('search-input');
const resultsContainer = document.getElementById('search-results');
const loadingIndicator = document.getElementById('loading');
const clearButton = document.getElementById('search-clear');
const pillsRoot = document.querySelector('.search-pills');
const perfFlags = window.BM_PERF_FLAGS || {};
const frontFluidityEnabled = perfFlags.frontFluidity !== false;

function navigateToUrl(url) {
  const targetUrl = String(url || "").trim();
  if (!targetUrl) return;
  if (window.BMPageNav && typeof window.BMPageNav.navigate === "function") {
    window.BMPageNav.navigate(targetUrl);
    return;
  }
  window.location.assign(targetUrl);
}
const SEARCH_MIN_CHARS = 2;
const SEARCH_SECONDARY_MIN_CHARS = 3;
const SEARCH_DEBOUNCE_MS = frontFluidityEnabled ? 240 : 300;
let searchTimeout = null;
let searchController = null;
let pendingResultsHtml = null;
let resultsRenderFrame = 0;
let lastResultsMarkup = null;
const ajaxGuardApi = window.BMAjaxGuard || null;
const ajaxFetchApi = window.BMAjaxFetch || null;
const ajaxCsrfApi = window.BMAjaxCSRF || null;
const coreDomApi = window.BMCoreDom || {};
const createRequestSeq = (coreDomApi && typeof coreDomApi.makeRequestSeq === "function")
  ? coreDomApi.makeRequestSeq
  : ajaxGuardApi.makeRequestSeq.bind(ajaxGuardApi);
const requestSeq = createRequestSeq();
const escapeHtml = coreDomApi.escapeHtml;
const safeUrl = coreDomApi.safeUrl;
const uiLang = (document.body.dataset.lang || 'fr').toLowerCase();
const i18n = {
  fr: {
    products: 'Produits',
    shops: 'Boutiques',
    categories: 'Categories',
    locations: 'Locations',
    add: 'Ajouter',
    reserve: 'Reserver',
    noDesc: 'Aucune description',
    items: 'produits',
    cityMissing: 'Ville non précisée',
    daily: 'Journalier',
    monthly: 'Mensuel',
    viewDetail: 'Voir detail',
  },
  en: {
    products: 'Products',
    shops: 'Shops',
    categories: 'Categories',
    locations: 'Rentals',
    add: 'Add',
    reserve: 'Book',
    noDesc: 'No description',
    items: 'items',
    cityMissing: 'City not specified',
    daily: 'Daily',
    monthly: 'Monthly',
    viewDetail: 'View details',
  },
  ary: {
    products: 'mntjat',
    shops: 'mtajr',
    categories: 'fyat',
    locations: 'ijarat',
    add: 'zid',
    reserve: 'hjez',
    noDesc: 'bla wasf',
    items: 'mntj',
    cityMissing: 'mdina ma mktoba-sh',
    daily: 'b nhar',
    monthly: 'b chhar',
    viewDetail: 'chof tafasil',
  },
};
const t = i18n[uiLang] || i18n.fr;

if (!searchInput || !resultsContainer || !loadingIndicator || !clearButton) {
  return;
}

function safeFile(file) {
  return encodeURIComponent(String(file || '').replace(/[\\/]/g, ''));
}

function safeMediaUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) {
    return '';
  }
  if (raw.startsWith('/') || raw.startsWith('http://') || raw.startsWith('https://')) {
    return raw;
  }
  const normalized = raw.replace(/\\/g, '/').replace(/^\/+/, '');
  if (normalized.startsWith('uploads/')) {
    return `/static/${encodeURI(normalized)}`;
  }
  if (normalized.startsWith('static/')) {
    return `/${encodeURI(normalized)}`;
  }
  return `/static/uploads/rentals/${encodeURIComponent(normalized)}`;
}

function withCsrfHeaders(headers) {
  const baseHeaders = Object.assign({}, headers || {});
  if (ajaxCsrfApi && typeof ajaxCsrfApi.addToHeaders === "function") {
    return ajaxCsrfApi.addToHeaders(baseHeaders);
  }
  return baseHeaders;
}

const requestJSON = (coreDomApi && typeof coreDomApi.requestJSON === "function")
  ? coreDomApi.requestJSON
  : ajaxFetchApi.requestJSON.bind(ajaxFetchApi);

searchInput.focus();

resultsContainer.addEventListener('click', function (event) {
  const bookingBtn = event.target.closest('[data-booking-url]');
  if (bookingBtn) {
    event.preventDefault();
    event.stopPropagation();
    const bookingUrl = safeUrl(bookingBtn.getAttribute('data-booking-url') || '#');
    if (bookingUrl && bookingUrl !== '#') {
      navigateToUrl(bookingUrl);
    }
    return;
  }

  const addBtn = event.target.closest('[data-add-cart-id]');
  if (addBtn) {
    event.preventDefault();
    event.stopPropagation();
    const productId = Number.parseInt(addBtn.getAttribute('data-add-cart-id') || '0', 10);
    if (Number.isFinite(productId) && productId > 0) {
      addToCart(productId);
    }
  }
});

function toggleClearButton() {
  clearButton.style.display = searchInput.value.trim() ? 'inline-flex' : 'none';
}

function flushResultsMarkup() {
  if (resultsRenderFrame) {
    window.cancelAnimationFrame(resultsRenderFrame);
    resultsRenderFrame = 0;
  }
  const nextHtml = pendingResultsHtml;
  pendingResultsHtml = null;
  if (typeof nextHtml !== 'string') {
    return;
  }
  if (nextHtml === lastResultsMarkup) {
    return;
  }
  resultsContainer.innerHTML = nextHtml;
  lastResultsMarkup = nextHtml;
}

function renderResultsMarkup(html) {
  const nextHtml = String(html || '');
  pendingResultsHtml = nextHtml;
  if (!frontFluidityEnabled) {
    flushResultsMarkup();
    return;
  }
  if (resultsRenderFrame) {
    return;
  }
  resultsRenderFrame = window.requestAnimationFrame(function () {
    resultsRenderFrame = 0;
    flushResultsMarkup();
  });
}

function clearResultsMarkup() {
  pendingResultsHtml = '';
  lastResultsMarkup = null;
  flushResultsMarkup();
}

toggleClearButton();

clearButton.addEventListener('click', () => {
  searchInput.value = '';
  toggleClearButton();
  clearResultsMarkup();
  loadingIndicator.classList.remove('show');
  searchInput.focus();
});

if (pillsRoot) {
  pillsRoot.addEventListener('click', function (event) {
    const pill = event.target.closest('.pill');
    if (!pill || !pillsRoot.contains(pill)) return;
    searchInput.value = pill.dataset.query || '';
    toggleClearButton();
    searchInput.dispatchEvent(new Event('input'));
  });
}

async function addToCart(productId) {
  try {
    const cartAddUrl = `${endpointCartAddBase.replace(/\/+$/, '')}/${productId}`;
    const result = await requestJSON(cartAddUrl, {
      method: 'POST',
      headers: withCsrfHeaders({}),
      credentials: 'same-origin'
    });
    const data = result.data || {};

    if (result.ok && data.success) {
      const cartBadge = document.querySelector('.cart-badge');
      if (cartBadge) {
        cartBadge.textContent = data.cart_count;
      }
      document.dispatchEvent(new CustomEvent("cart:changed", {
        detail: { source: "search_results", cartCount: data.cart_count ?? null },
      }));
      showNotification(`Ajoute au panier (${data.product_qty})`, 'success');
    } else {
      showNotification(data.message || result.error || "Erreur lors de l'ajout au panier", 'error');
    }
  } catch (error) {
    console.error('Erreur:', error);
    showNotification("Erreur lors de l'ajout au panier", 'error');
  }
}

function showNotification(message, type) {
  let notification = document.getElementById('search-notification');
  if (!notification) {
    notification = document.createElement('div');
    notification.id = 'search-notification';
    notification.className = 'search-toast';
    document.body.appendChild(notification);
  }
  notification.classList.remove('success', 'error');
  notification.classList.add(type);
  const safeMessage = escapeHtml(message);
  notification.innerHTML = `
    <div class="d-flex align-items-center gap-2">
      <i class="bi ${type === 'success' ? 'bi-check-circle-fill' : 'bi-exclamation-circle-fill'}"></i>
      <span>${safeMessage}</span>
    </div>
  `;

  setTimeout(() => {
    notification.style.animation = 'slideOut 0.3s ease';
    setTimeout(() => notification.remove(), 300);
  }, 2500);
}

searchInput.addEventListener('input', function() {
  clearTimeout(searchTimeout);
  const query = this.value.trim();
  const requestId = requestSeq.next();
  toggleClearButton();

  if (searchController) {
    searchController.abort();
    searchController = null;
  }

  if (query.length >= SEARCH_MIN_CHARS) {
    loadingIndicator.classList.add('show');
  } else {
    loadingIndicator.classList.remove('show');
    clearResultsMarkup();
    return;
  }

  searchTimeout = setTimeout(async () => {
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    searchController = controller;
    const requestSignal = controller ? controller.signal : undefined;

    try {
      const buildSearchUrl = (base, q, limit) => `${base}?q=${encodeURIComponent(q)}&limit=${limit}`;
      const shouldQuerySecondary = query.length >= SEARCH_SECONDARY_MIN_CHARS;
      const productRequest = requestJSON(buildSearchUrl(endpointSearchProducts, query, 8), {
        signal: requestSignal,
        credentials: 'same-origin',
        cache: 'no-store'
      });
      const shopsRequest = shouldQuerySecondary
        ? requestJSON(buildSearchUrl(endpointSearchShops, query, 6), {
            signal: requestSignal,
            credentials: 'same-origin',
            cache: 'no-store'
          })
        : Promise.resolve({ ok: true, data: { shops: [] }, skipped: true });
      const categoriesRequest = shouldQuerySecondary
        ? requestJSON(buildSearchUrl(endpointSearchCategories, query, 8), {
            signal: requestSignal,
            credentials: 'same-origin',
            cache: 'no-store'
          })
        : Promise.resolve({ ok: true, data: { categories: [] }, skipped: true });
      const locationsRequest = shouldQuerySecondary
        ? requestJSON(buildSearchUrl(endpointSearchLocations, query, 6), {
            signal: requestSignal,
            credentials: 'same-origin',
            cache: 'no-store'
          })
        : Promise.resolve({ ok: true, data: { locations: [] }, skipped: true });
      const [productsRes, shopsRes, categoriesRes, locationsRes] = await Promise.all([
        productRequest,
        shopsRequest,
        categoriesRequest,
        locationsRequest
      ]);

      if (!requestSeq.isLatest(requestId)) {
        return;
      }

      const responses = [productsRes];
      if (shouldQuerySecondary) {
        responses.push(shopsRes, categoriesRes, locationsRes);
      }
      const allFailed = responses.every((entry) => !entry || !entry.ok);
      if (allFailed) {
        renderResultsMarkup(`
          <div class="empty-results">
            <div class="empty-icon"><i class="bi bi-exclamation-circle"></i></div>
            <div class="empty-title">Erreur de recherche</div>
            <div class="empty-text">Veuillez reessayer.</div>
          </div>
        `);
        return;
      }

      const productsData = productsRes && productsRes.data && typeof productsRes.data === 'object' ? productsRes.data : {};
      const shopsData = shopsRes && shopsRes.data && typeof shopsRes.data === 'object' ? shopsRes.data : {};
      const categoriesData = categoriesRes && categoriesRes.data && typeof categoriesRes.data === 'object' ? categoriesRes.data : {};
      const locationsData = locationsRes && locationsRes.data && typeof locationsRes.data === 'object' ? locationsRes.data : {};

      let html = '';
      let hasResults = false;

      if (productsData.products && productsData.products.length > 0) {
        hasResults = true;
        html += `<section class="results-section">`;
        html += `<div class="results-header">
                  <h3>${t.products}</h3>
                  <span class="results-count">${productsData.products.length}</span>
                 </div>`;
        html += `<div class="products-grid">`;
        productsData.products.forEach(p => {
          const productUrl = safeUrl(p.url);
          const productName = escapeHtml(p.name || '');
          const productPrice = escapeHtml((p.price ?? ''));
          const shopName = escapeHtml(p.shop_name || t.shops);
          const imageFile = safeFile(p.image_file);
          const productId = Number.parseInt(p.id, 10);
          const promoValue = p.promo_value ? escapeHtml(p.promo_value) : '';
          const isService = (p.kind || '') === 'service';
          const bookingUrl = safeUrl(p.booking_url || productUrl);
          const actionHtml = isService
            ?
             `<button type="button" class="btn-add-cart service text-center text-decoration-none d-inline-block" data-stop-nav data-booking-url="${bookingUrl}"><i class="bi bi-calendar-check me-1"></i>${t.reserve}</button>`
            : `<button type="button" class="btn-add-cart" data-stop-nav data-add-cart-id="${Number.isFinite(productId) ? productId : 0}"><i class="bi bi-cart-plus me-1"></i>${t.add}</button>`;
          html += `
            <a href="${productUrl}" class="product-card">
              <div class="product-media">
                ${p.image_file
                  ?
                  `<img src="/static/uploads/${imageFile}" alt="${productName}" loading="lazy" decoding="async">` :
                  `<i class="bi bi-box text-success"></i>`
                }
                ${p.promo_value ? `<span class="product-badge">-${promoValue}%</span>` : ''}
              </div>
              <div class="product-body">
                <div class="product-name">${productName}</div>
                <div class="product-price">${productPrice} MAD</div>
                <div class="product-meta">
                  <i class="bi bi-shop"></i> ${shopName}
                </div>
                ${actionHtml}
              </div>
            </a>`;
        });
        html += `</div></section>`;
      }

      if (shopsData.shops && shopsData.shops.length > 0) {
        hasResults = true;
        html += `<section class="results-section">`;
        html += `<div class="results-header">
                  <h3>${t.shops}</h3>
                  <span class="results-count">${shopsData.shops.length}</span>
                 </div>`;
        html += `<div class="shops-grid">`;
        shopsData.shops.forEach(s => {
          const shopUrl = safeUrl(s.url);
          const shopName = escapeHtml(s.name || '');
          const shopDescription = escapeHtml(s.description || t.noDesc);
          const shopLogo = safeFile(s.logo);
          const productCount = Number(s.product_count || 0);
          html += `
            <a href="${shopUrl}" class="shop-card">
              <div class="shop-logo">
                ${s.logo
                  ?
                  `<img src="/static/uploads/${shopLogo}" alt="${shopName}" loading="lazy" decoding="async">` :
                  `<i class="bi bi-shop"></i>`
                }
              </div>
              <div class="shop-info">
                <h4>${shopName}</h4>
                <p class="shop-description">${shopDescription}</p>
                <div class="shop-stats">
                  <i class="bi bi-box"></i> ${productCount} ${t.items}
                </div>
              </div>
            </a>`;
        });
        html += `</div></section>`;
      }

      if (categoriesData.categories && categoriesData.categories.length > 0) {
        hasResults = true;
        html += `<section class="results-section">`;
        html += `<div class="results-header">
                  <h3>${t.categories}</h3>
                  <span class="results-count">${categoriesData.categories.length}</span>
                 </div>`;
        html += `<div class="categories-grid">`;
        categoriesData.categories.forEach(c => {
          const catId = Number.parseInt(c.id, 10);
          const catUrl = Number.isFinite(catId) ? `${endpointShopHome}?cat=${catId}` : '#';
          const catName = escapeHtml(c.name || '');
          html += `
            <a href="${catUrl}" class="category-tag">
              <i class="bi bi-tag"></i> ${catName}
            </a>`;
        });
        html += `</div></section>`;
      }

      if (locationsData.locations && locationsData.locations.length > 0) {
        hasResults = true;
        html += `<section class="results-section">`;
        html += `<div class="results-header">
                  <h3>${t.locations}</h3>
                  <span class="results-count">${locationsData.locations.length}</span>
                 </div>`;
        html += `<div class="locations-grid">`;
        locationsData.locations.forEach((l) => {
          const title = escapeHtml(l.title || '');
          const city = escapeHtml([l.city, l.area].filter(Boolean).join(', '));
          const listingType = l.listing_type === 'daily' ? t.daily : t.monthly;
          const rentDh = Number(l.rent_dh || 0).toFixed(2);
          const locationUrl = safeUrl(l.url || '#');
          const coverUrl = safeMediaUrl(l.cover_url || l.cover || '');
          html += `
            <article class="location-card">
              <a href="${locationUrl}" class="location-media-link">
                <div class="location-media">
                  ${coverUrl ? `<img src="${coverUrl}" alt="${title}" loading="lazy" decoding="async">` : `<i class="bi bi-house-door"></i>`}
                </div>
              </a>
              <div class="location-body">
                <div class="location-title">${title}</div>
                <div class="location-meta">${city || t.cityMissing} &bull; ${listingType}</div>
                <div class="location-price">${rentDh} DH</div>
                <div class="location-actions">
                  <a href="${locationUrl}" class="btn-location-detail">
                    <i class="bi bi-eye"></i>${t.viewDetail}
                  </a>
                </div>
              </div>
            </article>`;
        });
        html += `</div></section>`;
      }

      if (!hasResults) {
        html = `
          <div class="empty-results">
            <div class="empty-icon"><i class="bi bi-search"></i></div>
            <div class="empty-title">Aucun resultat trouve</div>
            <div class="empty-text">Essayez d'autres mots cles.</div>
          </div>
        `;
      }

      if (!requestSeq.isLatest(requestId)) {
        return;
      }
      renderResultsMarkup(html);
    } catch (error) {
      if (!requestSeq.isLatest(requestId)) {
        return;
      }
      console.error('Erreur de recherche:', error);
      renderResultsMarkup(`
        <div class="empty-results">
          <div class="empty-icon"><i class="bi bi-exclamation-circle"></i></div>
          <div class="empty-title">Erreur de recherche</div>
          <div class="empty-text">Veuillez reessayer.</div>
        </div>
      `);
    } finally {
      if (requestSeq.isLatest(requestId)) {
        loadingIndicator.classList.remove('show');
      }
      if (searchController === controller) {
        searchController = null;
      }
    }
  }, SEARCH_DEBOUNCE_MS);
});

searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    searchInput.value = '';
    toggleClearButton();
    clearResultsMarkup();
    loadingIndicator.classList.remove('show');
  }
});
})();

