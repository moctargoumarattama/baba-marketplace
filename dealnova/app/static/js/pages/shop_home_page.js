(function () {
"use strict";

if (window.__BM_SHOP_HOME_BOOTSTRAP__) {
  return;
}
window.__BM_SHOP_HOME_BOOTSTRAP__ = true;

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

const pageConfig = readConfig("shopHomePageConfig", {
  api: {
    listBase: "/shop",
    searchProducts: "/api/search/products",
    searchShops: "/api/search/shops",
    searchLocations: "/api/search/locations",
  },
});
const apiConfig = pageConfig.api || {};
const endpointListBase = String(apiConfig.listBase || "/shop");
const endpointSearchProducts = String(apiConfig.searchProducts || "/api/search/products");
const endpointSearchShops = String(apiConfig.searchShops || "/api/search/shops");
const endpointSearchLocations = String(apiConfig.searchLocations || "/api/search/locations");
const fallbackConfig = pageConfig.fallbackImages || {};
const fallbackProductImage = String(fallbackConfig.product || "/static/img/placeholders/product.svg");
const fallbackShopImage = String(fallbackConfig.shop || "/static/img/placeholders/shop.svg");
const fallbackLocationImage = String(fallbackConfig.location || "/static/img/placeholders/location.svg");
const perfFlags = window.BM_PERF_FLAGS || {};
const frontFluidityEnabled = perfFlags.frontFluidity !== false;
const LIVE_SEARCH_MIN_CHARS = 2;
const LIVE_SEARCH_SECONDARY_MIN_CHARS = 3;
const LIVE_SEARCH_DEBOUNCE_MS = frontFluidityEnabled ? 250 : 350;
const ajaxFetchApi = window.BMAjaxFetch || null;
const ajaxGuardApi = window.BMAjaxGuard || null;
const ajaxCsrfApi = window.BMAjaxCSRF || null;
const prefetchApi = window.BMIntentPrefetch || null;
const interactionFeedbackEnabled = perfFlags.interactionFeedback !== false;

// État global des filtres
let currentFilters = {
  q: "",
  cat: "",
  shop: "",
  sort: "",
  kind: "",
  min_price: "",
  max_price: "",
  promo: "",
  stock: "",
  page: "1"
};

let totalPages = 1;
let isInfiniteLoading = false;
let userInteracted = false;
let productsFetchController = null;
let suggestFetchController = null;
let pendingFeedbackSeq = 0;
let productsUiRequestSeq = 0;
let urlStateTimer = null;
let modeOnboardingTimer = null;
let activeChipScrollTimer = null;
let lastProductsFetchUrl = "";
let lastProductsResponseHtml = "";
let lastSuggestionsQuery = "";
let lastSuggestionsSignature = "";
const suggestionsCache = new Map();

function createLocalRequestSeq() {
  let latest = 0;
  return {
    next() {
      latest += 1;
      return latest;
    },
    isLatest(id) {
      return Number(id) === latest;
    }
  };
}

const suggestRequestSeq = (
  ajaxGuardApi &&
  typeof ajaxGuardApi.makeRequestSeq === 'function'
)
  ? ajaxGuardApi.makeRequestSeq()
  // KEEP_FALLBACK: protects live-search ordering if ajax core is missing during stale-cache scenarios.
  : createLocalRequestSeq();

function withCsrfHeaders(headers, formEl) {
  const nextHeaders = Object.assign({}, headers || {});
  if (ajaxCsrfApi && typeof ajaxCsrfApi.addToHeaders === 'function') {
    return ajaxCsrfApi.addToHeaders(nextHeaders, formEl || null);
  }
  return nextHeaders;
}

async function requestJSON(url, options) {
  if (ajaxFetchApi && typeof ajaxFetchApi.requestJSON === 'function') {
    return ajaxFetchApi.requestJSON(url, options || {});
  }
  try {
    const response = await fetch(url, options || {});
    let data = null;
    try {
      data = await response.json();
    } catch (_parseError) {
      data = null;
    }
    return {
      ok: response.ok,
      status: response.status,
      data: data,
      error: response.ok ? null : (response.statusText || ('HTTP ' + response.status)),
      aborted: false,
      timedOut: false
    };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      data: null,
      error: String((error && error.message) || 'network_error'),
      aborted: !!(error && error.name === 'AbortError'),
      timedOut: false
    };
  }
}

async function requestText(url, options) {
  if (ajaxFetchApi && typeof ajaxFetchApi.requestText === 'function') {
    return ajaxFetchApi.requestText(url, options || {});
  }
  try {
    const response = await fetch(url, options || {});
    let data = '';
    try {
      data = await response.text();
    } catch (_parseError) {
      data = '';
    }
    return {
      ok: response.ok,
      status: response.status,
      data: data,
      error: response.ok ? null : (response.statusText || ('HTTP ' + response.status)),
      aborted: false,
      timedOut: false
    };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      data: '',
      error: String((error && error.message) || 'network_error'),
      aborted: !!(error && error.name === 'AbortError'),
      timedOut: false
    };
  }
}

function batchDomCommit(fn) {
  if (typeof fn !== 'function') {
    return Promise.resolve();
  }
  if (!frontFluidityEnabled || typeof window.requestAnimationFrame !== 'function') {
    fn();
    return Promise.resolve();
  }
  return new Promise(resolve => {
    window.requestAnimationFrame(() => {
      fn();
      resolve();
    });
  });
}

function initShopHomePage() {
  if (window.__BM_SHOP_HOME_INIT__) return;
  window.__BM_SHOP_HOME_INIT__ = true;
  if ("scrollRestoration" in history) {
    history.scrollRestoration = "manual";
  }
  // ===== SCROLL TO TOP =====
  const scrollToTopBtn = document.getElementById('scrollToTop');
  let isScrollToTopVisible = false;
  let lastPageBadgeText = "";
  let isPageBadgeVisible = false;
  const floatingPaginationNav = document.getElementById('floatingPaginationNav');
  const floatingPrevBtn = document.getElementById('floatingPrevBtn');
  const floatingNextBtn = document.getElementById('floatingNextBtn');
  const floatingPaginationStatus = document.getElementById('floatingPaginationStatus');

  function updateScrollToTopVisibility() {
    if (!scrollToTopBtn) return;
    const shouldShow = window.scrollY > 300;
    if (shouldShow === isScrollToTopVisible) return;
    isScrollToTopVisible = shouldShow;
    scrollToTopBtn.classList.toggle('visible', shouldShow);
  }
  
  if (scrollToTopBtn) {
    scrollToTopBtn.addEventListener('click', function() {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // ===== CHARGEMENT AJAX =====
  const ajaxLoading = document.getElementById('ajaxLoading');
  const urlState = document.getElementById('urlState');
  
  function showLoading() {
    if (ajaxLoading && ajaxLoading.classList) {
      ajaxLoading.classList.add('active');
    }
    const productsGrid = document.getElementById('productsGrid');
    if (productsGrid && productsGrid.classList) {
      productsGrid.classList.add('loading');
    }
  }
  
  function hideLoading() {
    if (ajaxLoading && ajaxLoading.classList) {
      ajaxLoading.classList.remove('active');
    }
    const productsGrid = document.getElementById('productsGrid');
    if (productsGrid && productsGrid.classList) {
      productsGrid.classList.remove('loading');
    }
  }
  
  function showUrlState(message) {
    if (!urlState) return;
    if (urlStateTimer) {
      window.clearTimeout(urlStateTimer);
      urlStateTimer = null;
    }
    urlState.textContent = message;
    urlState.classList.add('show');
    urlStateTimer = window.setTimeout(() => {
      urlState.classList.remove('show');
      urlStateTimer = null;
    }, 1500);
  }

  function lockContainerHeight(container) {
    if (!container || !container.style) return 0;
    const height = Math.max(0, Math.round(container.getBoundingClientRect().height || 0));
    if (height > 0) {
      container.style.minHeight = `${height}px`;
      container.classList.add('is-swapping');
    }
    return height;
  }

  function unlockContainerHeight(container) {
    if (!container || !container.style) return;
    container.style.removeProperty('min-height');
    container.classList.remove('is-swapping');
  }

  function restoreStableAnchorPosition(anchorSelector, anchorTopBefore, fallbackEl, fallbackTopBefore, fallbackScrollY) {
    if (anchorTopBefore != null && anchorSelector) {
      const anchorEl = document.querySelector(anchorSelector);
      if (anchorEl) {
        const delta = anchorEl.getBoundingClientRect().top - anchorTopBefore;
        if (Math.abs(delta) > 1) {
          window.scrollBy(0, delta);
        }
        return;
      }
    }
    if (fallbackEl && fallbackTopBefore != null) {
      const delta = fallbackEl.getBoundingClientRect().top - fallbackTopBefore;
      if (Math.abs(delta) > 1) {
        window.scrollBy(0, delta);
        return;
      }
    }
    if (typeof fallbackScrollY === 'number') {
      window.scrollTo(0, fallbackScrollY);
    }
  }

  function updateCardSlider(container, direction) {
    if (!container) return;
    const imageElement = container.querySelector('.js-product-slide-image');
    if (!imageElement) return;
    let images = [];
    try {
      images = JSON.parse(container.dataset.sliderImages || '[]');
    } catch (error) {
      images = [];
    }
    if (!images.length) return;
    let index = parseInt(container.dataset.sliderIndex || '0', 10);
    if (Number.isNaN(index)) index = 0;
    index += direction;
    if (index < 0) index = images.length - 1;
    if (index >= images.length) index = 0;
    container.dataset.sliderIndex = String(index);
    imageElement.src = images[index];
  }

  function shouldUseGlobalAjaxPopstate() {
    const owner = String((document.body && document.body.dataset && document.body.dataset.ajaxOwner) || '').trim().toLowerCase();
    if (owner === 'page' || owner === 'off') return false;
    return !!(
      window.AjaxPagination &&
      document.querySelector("[data-ajax-listing]") &&
      document.querySelector("[data-ajax-pagination]")
    );
  }

  function syncListingMetricsFromDom() {
    const pager = document.getElementById("paginationContainer");
    const resultsCountEl = document.querySelector(".results-count");
    if (pager) {
      const total = parseInt(pager.getAttribute("data-total") || "", 10);
      if (resultsCountEl && !Number.isNaN(total)) {
        resultsCountEl.textContent = String(total);
      }
      const pages = parseInt(pager.getAttribute("data-pages") || "1", 10);
      totalPages = Number.isNaN(pages) ? 1 : pages;
      return;
    }

    totalPages = 1;
    if (resultsCountEl) {
      const cards = document.querySelectorAll("#productsGrid .product-card-compact");
      resultsCountEl.textContent = String(cards.length || 0);
    }
  }

  function shouldQueryLiveSearch(value) {
    const q = String(value || "").trim();
    return q.length === 0 || q.length >= LIVE_SEARCH_MIN_CHARS;
  }

  function buildListingUrlForPage(pageValue) {
    const params = new URLSearchParams();
    Object.keys(currentFilters).forEach((key) => {
      const value = currentFilters[key];
      if (value == null || value === "") return;
      params.set(key, value);
    });
    const safePage = Math.max(1, Number(pageValue || 1));
    params.set("page", String(safePage));
    const baseUrl = (searchForm && searchForm.action) ? searchForm.action : endpointListBase;
    const query = params.toString();
    return query ? `${baseUrl}?${query}` : baseUrl;
  }

  function scheduleHomeIdlePrefetch() {
    if (!prefetchApi || typeof prefetchApi.prefetchIdle !== "function") return;
    const urls = [];

    const shopsLink = document.querySelector('.btn-boutiques[href]');
    const locationsLink = document.querySelector('.mode-link.mode-locations[href]');
    if (shopsLink) urls.push(shopsLink.getAttribute('href'));
    if (locationsLink) urls.push(locationsLink.getAttribute('href'));

    const currentPage = Math.max(1, parseInt(currentFilters.page || "1", 10) || 1);
    if ((totalPages || 1) > currentPage) {
      urls.push(buildListingUrlForPage(currentPage + 1));
    }

    if (!urls.length) return;
    prefetchApi.prefetchIdle(urls, {
      headers: { Accept: 'text/html' },
      timeoutMs: 1300
    });
  }

  function bindHomeIntentPrefetch() {
    if (!prefetchApi || typeof prefetchApi.prefetchOnIntent !== "function") return;
    prefetchApi.prefetchOnIntent(
      document,
      '.btn-boutiques[href], .mode-link.mode-locations[href], .shop-stories a[href]',
      { headers: { Accept: 'text/html' } }
    );
  }

  function applyLocalFallbackImage(img, primarySrc, localFallback) {
    if (!img) return;
    const fallbackSrc = String(localFallback || fallbackProductImage);
    if (fallbackSrc) {
      img.setAttribute("data-fallback-src", fallbackSrc);
    }
    img.src = String(primarySrc || fallbackSrc || "");
  }

  document.addEventListener('click', (event) => {
    const prevBtn = event.target.closest('.js-slide-prev');
    const nextBtn = event.target.closest('.js-slide-next');
    if (!prevBtn && !nextBtn) return;
    event.preventDefault();
    event.stopPropagation();
    const container = event.target.closest('[data-slider-images]');
    updateCardSlider(container, prevBtn ? -1 : 1);
  });

  function setSearchButtonLoading(isLoading) {
    const btn = document.getElementById('searchButton');
    if (!btn) return;
    btn.classList.toggle('loading', isLoading);
  }

  function setElementPending(node) {
    if (!interactionFeedbackEnabled || !node || typeof node.setAttribute !== 'function') {
      return function () {};
    }
    pendingFeedbackSeq += 1;
    const token = String(pendingFeedbackSeq);
    node.setAttribute('data-bm-pending', '1');
    node.setAttribute('data-bm-pending-token', token);
    return function () {
      if (node.getAttribute('data-bm-pending-token') !== token) return;
      node.removeAttribute('data-bm-pending');
      node.removeAttribute('data-bm-pending-token');
    };
  }

  function markUserInteracted() {
    if (!userInteracted) {
      userInteracted = true;
      document.body.classList.add('user-interacted');
    }
    updateLoadMoreButton();
    updateClearButton();
  }

  function updateLoadMoreButton() {
    const wrap = document.getElementById('loadMoreWrap');
    const btn = document.getElementById('loadMoreBtn');
    if (!wrap || !btn) return;
    const currentPage = parseInt(currentFilters.page || 1, 10);
    const hasMore = currentPage < (totalPages || 1);
    const floatingPagerVisible = window.innerWidth <= 576 && (totalPages || 1) > 1;
    const shouldShow = !floatingPagerVisible && window.innerWidth <= 768 && hasMore && userInteracted;
    wrap.style.display = shouldShow ? 'flex' : 'none';
    btn.disabled = !hasMore;
  }

  function getPreferredPaginationAnchor() {
    if (window.innerWidth <= 576 && floatingPaginationNav && floatingPaginationNav.classList.contains('show')) {
      return '#floatingPaginationNav';
    }
    return '#paginationContainer';
  }

  function updateFloatingPagination() {
    if (!floatingPaginationNav || !floatingPrevBtn || !floatingNextBtn || !floatingPaginationStatus) return;
    const total = totalPages || 1;
    const current = parseInt(currentFilters.page || 1, 10);
    const inlinePagination = document.getElementById('paginationContainer');
    const inlineRect = inlinePagination ? inlinePagination.getBoundingClientRect() : null;
    const inlineVisible = !!(
      inlineRect &&
      inlineRect.bottom > 0 &&
      inlineRect.top < (window.innerHeight || document.documentElement.clientHeight || 0)
    );
    const shouldShow = window.innerWidth <= 576 && total > 1 && !inlineVisible;
    floatingPaginationNav.classList.toggle('show', shouldShow);
    if (!shouldShow) return;
    floatingPaginationStatus.textContent = `Page ${current}/${total}`;
    floatingPrevBtn.disabled = current <= 1;
    floatingNextBtn.disabled = current >= total;
  }

  function setLoadMoreLoading(isLoading) {
    const btn = document.getElementById('loadMoreBtn');
    if (!btn) return;
    btn.disabled = isLoading;
    btn.classList.toggle('loading', isLoading);
  }

  let pageBadgeTimer = null;
  function updatePageBadge(show = true) {
    const badge = document.getElementById('pageBadge');
    if (!badge || document.hidden || window.innerWidth > 768 || !userInteracted) return;
    if (window.innerWidth <= 576 && floatingPaginationNav && floatingPaginationNav.classList.contains('show')) {
      if (isPageBadgeVisible) {
        badge.classList.remove('show');
        isPageBadgeVisible = false;
      }
      return;
    }
    const total = totalPages || 1;
    const current = parseInt(currentFilters.page || 1, 10);
    const nextText = `Page ${current}/${total}`;
    if (nextText !== lastPageBadgeText) {
      badge.textContent = nextText;
      lastPageBadgeText = nextText;
    }
    if (total <= 1) {
      if (isPageBadgeVisible) {
        badge.classList.remove('show');
        isPageBadgeVisible = false;
      }
      if (pageBadgeTimer) {
        window.clearTimeout(pageBadgeTimer);
        pageBadgeTimer = null;
      }
      return;
    }
    if (show) {
      if (!isPageBadgeVisible) {
        badge.classList.add('show');
        isPageBadgeVisible = true;
      }
      if (pageBadgeTimer) window.clearTimeout(pageBadgeTimer);
      pageBadgeTimer = window.setTimeout(() => {
        badge.classList.remove('show');
        isPageBadgeVisible = false;
        pageBadgeTimer = null;
      }, 1200);
    }
  }

  function hasActiveFilters() {
    return !!(
      currentFilters.q ||
      currentFilters.cat ||
      currentFilters.shop ||
      currentFilters.sort ||
      currentFilters.kind ||
      currentFilters.promo
    );
  }

  function updateClearButton() {
    if (!mobileClearBtn) return;
    const shouldShow = window.innerWidth <= 768 && userInteracted && hasActiveFilters();
    mobileClearBtn.classList.toggle('show', shouldShow);
  }

  function getFiltersFromUrl() {
    const params = new URLSearchParams(window.location.search);
    return {
      q: params.get('q') || '',
      cat: params.get('cat') || '',
      shop: params.get('shop') || '',
      sort: params.get('sort') || '',
      kind: params.get('kind') || '',
      min_price: '',
      max_price: '',
      promo: params.get('promo') || '',
      stock: '',
      page: params.get('page') || '1'
    };
  }

  function syncFiltersFromUrl() {
    currentFilters = getFiltersFromUrl();
    updateActiveFilters();
  }

  // ===== FILTRES MOBILE =====
  const mobileClearBtn = document.getElementById('mobileClearFloat');

  // ===== FILTRAGE AJAX =====
  function updateFilters(filterType, value, options = {}) {
    if (filterType === 'all') {
      markUserInteracted();
      // Réinitialiser tous les filtres sauf la recherche
      currentFilters = {
        q: currentFilters.q,
        cat: "",
        shop: "",
        sort: "",
        kind: "",
        min_price: "",
        max_price: "",
        promo: "",
        stock: "",
        page: 1
      };
    } else if (filterType === 'category') {
      markUserInteracted();
      currentFilters.cat = value;
      currentFilters.shop = "";
      currentFilters.page = 1;
    } else if (filterType === 'shop') {
      markUserInteracted();
      currentFilters.cat = ""; // Clear category when selecting shop
      currentFilters.shop = value;
      currentFilters.page = 1;
    } else if (filterType === 'sort') {
      markUserInteracted();
      currentFilters.sort = value;
      currentFilters.page = 1;
    } else if (filterType === 'kind') {
      markUserInteracted();
      const nextKind = (currentFilters.kind === value) ? "" : value;
      currentFilters.kind = nextKind;
      // Catégories dépendent du mode => reset catégorie quand on change de mode
      currentFilters.cat = "";
      currentFilters.page = 1;
    } else if (filterType === 'stock') {
      markUserInteracted();
      currentFilters.stock = value ? '1' : '';
      currentFilters.page = 1;
    } else if (filterType === 'price') {
      markUserInteracted();
      const minInput = document.getElementById('minPrice');
      const maxInput = document.getElementById('maxPrice');
      const minMobile = document.getElementById('minPriceMobile');
      const maxMobile = document.getElementById('maxPriceMobile');
      const minPrice = (minMobile && minMobile.value !== '') ? minMobile.value : (minInput ? minInput.value : '');
      const maxPrice = (maxMobile && maxMobile.value !== '') ? maxMobile.value : (maxInput ? maxInput.value : '');
      currentFilters.min_price = minPrice;
      currentFilters.max_price = maxPrice;
      currentFilters.page = 1;
    }
    
    updateURL();
    loadProducts({
      triggerEl: options.triggerEl || null,
      loadingMode: 'silent',
      preserveScroll: true,
      showState: false
    });
  }

  function updateURL(options = {}) {
    const params = new URLSearchParams();
    
    Object.keys(currentFilters).forEach(key => {
      if (currentFilters[key] && currentFilters[key] !== '') {
        params.set(key, currentFilters[key]);
      }
    });
    
    const query = params.toString();
    const newUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
    const method = options.replace ? 'replaceState' : 'pushState';
    window.history[method]({ filters: { ...currentFilters } }, '', newUrl);
    updateActiveFilters();
  }

  async function loadProducts(options = {}) {
    const preserveScroll = options.preserveScroll !== false;
    const showState = options.showState !== false;
    const loadingMode = options.loadingMode || 'overlay';
    const append = options.append === true;
    const scrollY = preserveScroll ? window.scrollY : 0;
    const requestId = ++productsUiRequestSeq;
    const clearTriggerPending = setElementPending(options.triggerEl);
    const productsContainer = document.getElementById('productsContainer');
    const anchorSelector = preserveScroll ? (options.anchorSelector || '') : '';
    const stableAnchorBefore = anchorSelector
      ? document.querySelector(anchorSelector)
      : null;
    const stableAnchorTopBefore = stableAnchorBefore
      ? stableAnchorBefore.getBoundingClientRect().top
      : null;
    const anchorTopBefore = (preserveScroll && productsContainer)
      ? productsContainer.getBoundingClientRect().top
      : null;
    const lockedHeight = (!append && productsContainer)
      ? lockContainerHeight(productsContainer)
      : 0;

    try {
      if (productsFetchController) {
        productsFetchController.abort();
      }
      productsFetchController = new AbortController();

      if (loadingMode === 'overlay') {
        showLoading();
      } else if (loadingMode === 'inline') {
        setSearchButtonLoading(true);
      }

      const params = new URLSearchParams();
      Object.keys(currentFilters).forEach(key => {
        if (currentFilters[key] && currentFilters[key] !== '') {
          params.set(key, currentFilters[key]);
        }
      });

      const baseUrl = (searchForm && searchForm.action) ? searchForm.action : endpointListBase;
      const query = params.toString();
      const fetchUrl = query ? `${baseUrl}?${query}` : baseUrl;

      const response = await requestText(fetchUrl, {
        headers: { 'X-Requested-With': 'fetch' },
        cache: 'no-store',
        signal: productsFetchController.signal
      });
      if (response && response.aborted) {
        return;
      }
      if (!response || !response.ok) {
        throw new Error((response && response.error) || 'fetch_failed');
      }
      if (typeof response.data !== 'string') {
        throw new Error('invalid_html_payload');
      }
      if (requestId !== productsUiRequestSeq) {
        return;
      }
      const html = response.data || '';
      if (!append && fetchUrl === lastProductsFetchUrl && html === lastProductsResponseHtml) {
        updateLoadMoreButton();
        updatePageBadge(false);
        if (showState) {
          showUrlState('Filtres appliques');
        }
        return;
      }
      const doc = new DOMParser().parseFromString(html, 'text/html');

      const productsGrid = doc.querySelector('#productsGrid');
      const pagination = doc.querySelector('#paginationContainer');
      const emptyState = doc.querySelector('.empty-state');
      if (!productsGrid && !emptyState) {
        window.location.href = fetchUrl;
        return;
      }

      if (!productsContainer) {
        window.location.href = fetchUrl;
        return;
      }
      await batchDomCommit(() => {
        if (!append && emptyState) {
          productsContainer.replaceChildren(emptyState.cloneNode(true));
        } else if (productsGrid) {
          const newGrid = productsGrid.cloneNode(true);
          const newPagination = pagination ? pagination.cloneNode(true) : null;

          if (append) {
            let existingGrid = document.getElementById('productsGrid');
            if (!existingGrid) {
              existingGrid = newGrid;
              productsContainer.appendChild(existingGrid);
            } else {
              const cardsFragment = document.createDocumentFragment();
              newGrid.querySelectorAll('.product-card-compact').forEach(item => {
                cardsFragment.appendChild(item);
              });
              existingGrid.appendChild(cardsFragment);
            }
            const oldPagination = document.getElementById('paginationContainer');
            if (oldPagination) {
              oldPagination.remove();
            }
            if (newPagination) {
              productsContainer.appendChild(newPagination);
            }
          } else {
            const currentGrid = document.getElementById('productsGrid');
            const currentPagination = document.getElementById('paginationContainer');
            const currentEmptyState = productsContainer.querySelector('.empty-state');

            if (currentGrid) {
              currentGrid.replaceWith(newGrid);
            } else {
              if (currentEmptyState) {
                currentEmptyState.remove();
              }
              productsContainer.insertBefore(newGrid, productsContainer.firstChild || null);
            }

            if (newPagination) {
              if (currentPagination) {
                currentPagination.replaceWith(newPagination);
              } else {
                productsContainer.appendChild(newPagination);
              }
            } else if (currentPagination) {
              currentPagination.remove();
            }
          }

          const targetGrid = document.getElementById('productsGrid');
          if (targetGrid) {
            targetGrid
              .querySelectorAll('.product-card-compact')
              .forEach(card => card.classList.add('fade-in'));
          }
        }

        const resultsCount = doc.querySelector('.results-count');
        const currentResultsCount = document.querySelector('.results-count');
        if (resultsCount && currentResultsCount && currentResultsCount.textContent !== resultsCount.textContent) {
          currentResultsCount.textContent = resultsCount.textContent;
        }

        if (pagination) {
          const pages = parseInt(pagination.getAttribute('data-pages') || '1', 10);
          totalPages = Number.isNaN(pages) ? 1 : pages;
        } else {
          totalPages = 1;
        }

        attachProductEvents(productsContainer);
        initLazyShopVideos(productsContainer);
        attachPaginationEvents(document.getElementById('paginationContainer'));
        updateLoadMoreButton();
        updateFloatingPagination();
        updatePageBadge(false);
        scheduleHomeIdlePrefetch();

        if (showState) {
          showUrlState('Filtres appliques');
        }

        if (preserveScroll) {
          const stableAnchorAfter = anchorSelector
            ? document.querySelector(anchorSelector)
            : null;
          if (stableAnchorTopBefore != null && stableAnchorAfter) {
            const delta = stableAnchorAfter.getBoundingClientRect().top - stableAnchorTopBefore;
            if (Math.abs(delta) > 1) {
              window.scrollBy(0, delta);
            } else {
              window.scrollTo(0, scrollY);
            }
          } else {
            const anchorTopAfter = productsContainer.getBoundingClientRect().top;
            if (anchorTopBefore != null) {
              const delta = anchorTopAfter - anchorTopBefore;
              if (Math.abs(delta) > 1) {
                window.scrollBy(0, delta);
              } else {
                window.scrollTo(0, scrollY);
              }
            } else {
              window.scrollTo(0, scrollY);
            }
          }
        }
      });
      lastProductsFetchUrl = fetchUrl;
      lastProductsResponseHtml = html;

    } catch (error) {
      if (error && error.name === 'AbortError') {
        return;
      }
      console.error('Erreur:', error);
      showToast('Erreur chargement', 'error');
    } finally {
      clearTriggerPending();
      if (requestId !== productsUiRequestSeq) {
        return;
      }
      if (loadingMode === 'overlay') {
        hideLoading();
      } else if (loadingMode === 'inline') {
        setSearchButtonLoading(false);
      }
      if (productsContainer && lockedHeight > 0) {
        window.setTimeout(() => {
          unlockContainerHeight(productsContainer);
          if (preserveScroll) {
            restoreStableAnchorPosition(
              anchorSelector,
              stableAnchorTopBefore,
              productsContainer,
              anchorTopBefore,
              scrollY
            );
          }
        }, 120);
      } else {
        unlockContainerHeight(productsContainer);
        if (preserveScroll) {
          restoreStableAnchorPosition(
            anchorSelector,
            stableAnchorTopBefore,
            productsContainer,
            anchorTopBefore,
            scrollY
          );
        }
      }
    }
  }

  function normalizeKind(value) {
    const kind = (value || '').toString().trim().toLowerCase();
    if (kind === 'physical' || kind === 'service') return kind;
    return '';
  }

  function getCountForKind(el, kind) {
    if (!el || !kind) return 0;
    const key = kind === 'physical' ? 'countPhysical' : 'countService';
    const raw = (el.dataset && el.dataset[key]) ? el.dataset[key] : '0';
    const count = parseInt(raw, 10);
    return Number.isNaN(count) ? 0 : count;
  }

  function syncKindUI() {
    const kind = normalizeKind(currentFilters.kind);
    const hasKind = !!kind;

    const modeAllLabel = document.getElementById('modeAllLabel');
    if (modeAllLabel) {
      modeAllLabel.classList.toggle('kind-hidden', hasKind);
    }

    const categoryStripWrap = document.getElementById('categoryStripWrap');
    if (categoryStripWrap) {
      categoryStripWrap.classList.toggle('kind-hidden', !hasKind);
    }

    const categoryStripTitleText = document.getElementById('categoryStripTitleText');
    if (categoryStripTitleText) {
      if (kind === 'physical') categoryStripTitleText.textContent = 'Catégories produits';
      else if (kind === 'service') categoryStripTitleText.textContent = 'Catégories services';
      else categoryStripTitleText.textContent = 'Catégories';
    }

    document.querySelectorAll('.mode-btn[data-filter="kind"]').forEach(btn => {
      const val = normalizeKind(btn.getAttribute('data-value'));
      const isActive = hasKind && val && val === kind;
      btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });

    const categoryChips = document.querySelectorAll('.category-chip[data-filter="category"]');

    if (!hasKind) {
      categoryChips.forEach(el => el.classList.remove('kind-hidden'));
      return;
    }

    categoryChips.forEach(el => {
      const value = (el.getAttribute('data-value') || '').trim();
      if (!value) {
        el.classList.remove('kind-hidden');
        return;
      }
      const count = getCountForKind(el, kind);
      const shouldHide = count <= 0 && !el.classList.contains('active');
      el.classList.toggle('kind-hidden', shouldHide);
    });

  }

  function updateActiveFilters() {
    // Mettre Ã  jour les boutons actifs
    document.querySelectorAll('[data-filter]').forEach(element => {
      const filterType = element.getAttribute('data-filter');
      const filterValue = element.getAttribute('data-value');
      
      if (filterType === 'all') {
        element.classList.toggle('active', !currentFilters.cat && !currentFilters.shop);
      } else if (filterType === 'category') {
        element.classList.toggle('active', currentFilters.cat === filterValue);
      } else if (filterType === 'shop') {
        element.classList.toggle('active', currentFilters.shop === filterValue);
      } else if (filterType === 'sort') {
        element.classList.toggle('active', currentFilters.sort === filterValue);
      } else if (filterType === 'kind') {
        element.classList.toggle('active', currentFilters.kind === filterValue);
      } else if (filterType === 'stock') {
        element.classList.toggle('active', currentFilters.stock === filterValue);
      }
    });
    
    // Mettre Ã  jour le select
    const sortSelect = document.getElementById('sortSelect');
    if (sortSelect) {
      sortSelect.value = currentFilters.sort;
    }
    
    // Mettre a jour la recherche
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
      searchInput.value = currentFilters.q || '';
    }

    // Mettre a jour les prix (si champs présents)
    const minPriceInput = document.getElementById('minPrice');
    const maxPriceInput = document.getElementById('maxPrice');
    if (minPriceInput) minPriceInput.value = currentFilters.min_price || '';
    if (maxPriceInput) maxPriceInput.value = currentFilters.max_price || '';

    const minPriceMobile = document.getElementById('minPriceMobile');
    const maxPriceMobile = document.getElementById('maxPriceMobile');
    if (minPriceMobile) minPriceMobile.value = currentFilters.min_price || '';
    if (maxPriceMobile) maxPriceMobile.value = currentFilters.max_price || '';

    updateClearButton();
    syncKindUI();
  }

  async function loadNextPage() {
    if (isInfiniteLoading) return;
    const currentPage = parseInt(currentFilters.page || 1, 10);
    if (currentPage >= totalPages) return;
    isInfiniteLoading = true;
    setLoadMoreLoading(true);
    currentFilters.page = currentPage + 1;
    markUserInteracted();
    updateURL({ replace: true });
    await loadProducts({
      append: true,
      preserveScroll: true,
      showState: false,
      loadingMode: 'inline',
      triggerEl: document.getElementById('loadMoreBtn')
    });
    isInfiniteLoading = false;
    setLoadMoreLoading(false);
    updatePageBadge(true);
  }

  function resetFilters(options = {}) {
    markUserInteracted();
    currentFilters = {
      q: "",
      cat: "",
      shop: "",
      sort: "",
      kind: "",
      min_price: "",
      max_price: "",
      promo: "",
      stock: "",
      page: 1
    };
    const searchInput = document.getElementById('searchInput');
    if (searchInput) searchInput.value = '';
    loadSuggestions('');
    updateURL();
    loadProducts({ showState: false, triggerEl: options.triggerEl || null });
    showUrlState('Filtres reinitialises');
  }

  // ===== ÉVÉNEMENTS FILTRES =====
  function attachFilterEvents() {
    // Boutons mode (Produits / Services)
    document.querySelectorAll('.mode-btn[data-filter="kind"]').forEach(button => {
      if (button.dataset.bound === 'true') return;
      button.dataset.bound = 'true';
      button.addEventListener('click', function() {
        const filterType = this.getAttribute('data-filter');
        const filterValue = this.getAttribute('data-value');
        updateFilters(filterType, filterValue, { triggerEl: this });
      });
    });

    // Boutiques (stories)
    document.querySelectorAll('.shop-story[data-filter="shop"]').forEach(button => {
      if (button.dataset.bound === 'true') return;
      button.dataset.bound = 'true';
      button.addEventListener('click', function(e) {
        e.preventDefault();
        const filterType = this.getAttribute('data-filter');
        const filterValue = this.getAttribute('data-value');
        updateFilters(filterType, filterValue, { triggerEl: this });
      });
    });

    
    // Chips
    document.querySelectorAll('.category-chip[data-filter]').forEach(chip => {
      if (chip.dataset.bound === 'true') return;
      chip.dataset.bound = 'true';
      chip.addEventListener('click', function() {
        const filterType = this.getAttribute('data-filter');
        const filterValue = this.getAttribute('data-value');
        updateFilters(filterType, filterValue, { triggerEl: this });
      });
    });
    
    // Prix
    const applyPriceBtn = document.getElementById('applyPrice');
    if (applyPriceBtn) {
      applyPriceBtn.addEventListener('click', function() {
        updateFilters('price', '', { triggerEl: this });
      });
    }
    const applyPriceMobile = document.getElementById('applyPriceMobile');
    if (applyPriceMobile) {
      applyPriceMobile.addEventListener('click', function() {
        updateFilters('price', '', { triggerEl: this });
      });
    }
    
    // Entrée pour les prix
    ['minPrice', 'maxPrice'].forEach(id => {
      const input = document.getElementById(id);
      if (input) {
        input.addEventListener('keypress', function(e) {
          if (e.key === 'Enter') {
            updateFilters('price', '', { triggerEl: this });
          }
        });
      }
    });
    ['minPriceMobile', 'maxPriceMobile'].forEach(id => {
      const input = document.getElementById(id);
      if (input) {
        input.addEventListener('keypress', function(e) {
          if (e.key === 'Enter') {
            updateFilters('price', '', { triggerEl: this });
          }
        });
      }
    });
    
    // Tri select
    const sortSelect = document.getElementById('sortSelect');
    if (sortSelect) {
      sortSelect.addEventListener('change', function() {
        updateFilters('sort', this.value, { triggerEl: this });
      });
    }
    
    // Effacer filtres
    const clearFiltersBtn = document.getElementById('clearFilters');
    if (clearFiltersBtn) {
      clearFiltersBtn.addEventListener('click', function() {
        resetFilters({ triggerEl: this });
      });
    }

    if (mobileClearBtn) {
      mobileClearBtn.addEventListener('click', function() {
        resetFilters({ triggerEl: this });
      });
    }
  }

  // ===== PAGINATION =====
  function attachPaginationEvents(scope) {
    const paginationRoot = scope && scope.matches && scope.matches('#paginationContainer')
      ? scope
      : document.getElementById('paginationContainer');
    if (paginationRoot && paginationRoot.dataset.paginationBound !== 'true') {
      paginationRoot.dataset.paginationBound = 'true';
      paginationRoot.addEventListener('click', function(e) {
        const link = e.target.closest('.page-link-compact:not(.disabled):not(.active)');
        if (!link || !paginationRoot.contains(link)) return;
        e.preventDefault();
        const page = link.getAttribute('data-page');
        if (!page) return;
        currentFilters.page = page;
        updateURL();
        loadProducts({
          triggerEl: link,
          loadingMode: 'silent',
          preserveScroll: true,
          anchorSelector: getPreferredPaginationAnchor(),
          showState: false
        });
      });
    }
    bindNextListingIntentPrefetch(paginationRoot || document);
  }

  function bindNextListingIntentPrefetch(scope) {
    if (!prefetchApi || typeof prefetchApi.prefetchUrl !== 'function') return;
    const triggerPrefetch = () => {
      const currentPage = Math.max(1, parseInt(currentFilters.page || "1", 10) || 1);
      if ((totalPages || 1) <= currentPage) return;
      prefetchApi.prefetchUrl(buildListingUrlForPage(currentPage + 1), {
        headers: { Accept: 'text/html' }
      });
    };

    const searchRoot = (scope && scope.querySelectorAll) ? scope : document;
    const prefetchNodes = Array.from(searchRoot.querySelectorAll('.pagination-compact .next-link[data-page]'));
    const loadMoreNode = document.getElementById('loadMoreBtn');
    if (loadMoreNode) {
      prefetchNodes.push(loadMoreNode);
    }
    prefetchNodes.forEach((node) => {
      if (!node || node.dataset.prefetchBound === '1') return;
      node.dataset.prefetchBound = '1';
      node.addEventListener('pointerenter', triggerPrefetch, { passive: true });
      node.addEventListener('focus', triggerPrefetch, { passive: true });
      node.addEventListener('touchstart', () => {
        if (prefetchApi && typeof prefetchApi.runIdle === 'function') {
          prefetchApi.runIdle(triggerPrefetch, 500);
          return;
        }
        triggerPrefetch();
      }, { passive: true });
    });
  }

  function initLazyShopVideos(scope) {
    const root = (scope && scope.querySelectorAll) ? scope : document;
    const videos = root.querySelectorAll('.js-lazy-shop-video');
    if (!videos.length) return;

    function hydrate(video) {
      if (!video || video.dataset.videoLoaded === '1') return;
      const source = video.querySelector('source');
      const src = video.getAttribute('data-video-src') || (source ? source.getAttribute('data-src') : '');
      if (!src) return;
      if (source && !source.getAttribute('src')) {
        source.setAttribute('src', src);
      }
      video.dataset.videoLoaded = '1';
      video.load();
    }

    function playIfPossible(video) {
      if (!video) return;
      const run = () => {
        const promise = video.play();
        if (promise && typeof promise.catch === 'function') {
          promise.catch(() => {});
        }
      };

      if (video.readyState >= 2) {
        run();
        return;
      }

      video.addEventListener('loadeddata', run, { once: true });
    }

    if (!('IntersectionObserver' in window)) {
      videos.forEach((video) => {
        hydrate(video);
        playIfPossible(video);
      });
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        const video = entry.target;
        if (!entry.isIntersecting) return;
        hydrate(video);
        playIfPossible(video);
        observer.unobserve(video);
      });
    }, { rootMargin: '220px 0px', threshold: 0.2 });

    videos.forEach((video) => {
      if (video.dataset.videoObserved === '1') return;
      video.dataset.videoObserved = '1';
      observer.observe(video);
    });
  }

  function getCartBadgeNodes() {
    return Array.from(document.querySelectorAll('.cart-badge, [data-cart-badge], [data-drawer-cart-badge]'));
  }

  function readCartCount() {
    const nodes = getCartBadgeNodes();
    for (let i = 0; i < nodes.length; i += 1) {
      const text = String(nodes[i].textContent || "").trim();
      const count = parseInt(text, 10);
      if (!Number.isNaN(count)) {
        return Math.max(0, count);
      }
    }
    return 0;
  }

  function writeCartCount(nextCount) {
    const safeCount = Math.max(0, Number(nextCount || 0));
    const hasItems = safeCount > 0;
    getCartBadgeNodes().forEach((node) => {
      node.textContent = String(safeCount);
      if (node.classList && (node.classList.contains('cart-badge') || node.hasAttribute('data-cart-badge'))) {
        node.classList.toggle('d-none', !hasItems);
      }
      if (node.classList && node.classList.contains('cart-badge')) {
        node.style.display = hasItems ? 'flex' : 'none';
      }
    });
  }

  // ===== EVENEMENTS PRODUITS =====
  function attachProductEvents(scope) {
    const productsRoot = (scope && scope.id === 'productsContainer')
      ? scope
      : document.getElementById('productsContainer');
    if (!productsRoot || productsRoot.dataset.productEventsBound === 'true') return;
    productsRoot.dataset.productEventsBound = 'true';

    productsRoot.addEventListener('submit', async function(e) {
      const form = e.target;
      if (!(form instanceof HTMLFormElement) || !form.matches('.add-to-cart-form')) return;
      e.preventDefault();
      e.stopPropagation();

      const btn = form.querySelector('.add-to-cart');
      if (!btn) return;

      const productName = btn.getAttribute('data-name') || 'Produit';
      const apiUrl = form.dataset.apiUrl || form.action;

      const originalHTML = btn.innerHTML;
      const previousCartCount = readCartCount();
      const optimisticCartCount = previousCartCount + 1;
      btn.innerHTML = '<i class="bi bi-hourglass"></i><span>...</span>';
      btn.disabled = true;
      writeCartCount(optimisticCartCount);
      document.dispatchEvent(new CustomEvent('cart:changed', {
        detail: { source: 'shop_home', cartCount: optimisticCartCount, optimistic: true }
      }));

      try {
        const response = await requestJSON(apiUrl, {
          method: 'POST',
          headers: withCsrfHeaders({
            'X-Requested-With': 'fetch',
            'Accept': 'application/json'
          }, form),
          credentials: 'same-origin'
        });

        const data = (response && response.data && typeof response.data === 'object') ? response.data : {};

        if (response.ok && data.success) {
          showToast(productName + ' ajoute au panier !', 'success');
          btn.innerHTML = '<i class="bi bi-check"></i><span>Ajoute !</span>';
          btn.style.background = '#10B981';

          writeCartCount(data.cart_count ?? optimisticCartCount);
          document.dispatchEvent(new CustomEvent('cart:changed', {
            detail: { source: 'shop_home', cartCount: data.cart_count ?? optimisticCartCount }
          }));

          setTimeout(() => {
            btn.innerHTML = originalHTML;
            btn.disabled = false;
            btn.style.background = '';
          }, 2000);

        } else {
          showToast(data.message || response.error || 'Erreur ajout panier', 'error');
          writeCartCount(previousCartCount);
          document.dispatchEvent(new CustomEvent('cart:changed', {
            detail: { source: 'shop_home', cartCount: previousCartCount, rollback: true }
          }));
          btn.innerHTML = originalHTML;
          btn.disabled = false;
        }
      } catch (error) {
        console.error('Error:', error);
        showToast('Erreur de connexion', 'error');
        writeCartCount(previousCartCount);
        document.dispatchEvent(new CustomEvent('cart:changed', {
          detail: { source: 'shop_home', cartCount: previousCartCount, rollback: true }
        }));
        btn.innerHTML = originalHTML;
        btn.disabled = false;
      }
    });

    productsRoot.addEventListener('click', function(e) {
      const card = e.target.closest('.product-card-compact');
      if (!card || !productsRoot.contains(card)) return;
      if (e.target.closest('[data-stop-nav]') ||
          e.target.closest('a') ||
          e.target.closest('button') ||
          e.target.tagName === 'A' ||
          e.target.tagName === 'BUTTON' ||
          e.target.closest('.badge-compact')) {
        return;
      }

      const detailLink = card.querySelector('.btn-detail-compact');
      if (detailLink) {
        window.location.href = detailLink.getAttribute('href');
      }
    });
  }

  window.addEventListener('popstate', () => {
    // Avoid double handlers when ajax_pagination.js controls history for this listing.
    if (shouldUseGlobalAjaxPopstate()) return;
    syncFiltersFromUrl();
    loadProducts({ preserveScroll: true, showState: false });
    loadSuggestions(currentFilters.q || '');
  });

  document.addEventListener("ajax:page-replaced", (event) => {
    if (!shouldUseGlobalAjaxPopstate()) return;
    const detail = event && event.detail ? event.detail : null;
    // Ignore local swap notifications (no URL) to avoid duplicate search/suggest loops.
    if (!detail || !detail.url) return;
    syncFiltersFromUrl();
    syncListingMetricsFromDom();
    attachProductEvents();
    attachPaginationEvents();
    updateActiveFilters();
    updateLoadMoreButton();
    updateFloatingPagination();
    updatePageBadge(false);
    scheduleHomeIdlePrefetch();
    loadSuggestions(currentFilters.q || "");
  });

  // ===== RECHERCHE TEMPS REEL =====
  const searchForm = document.getElementById('searchForm');
  const searchInput = document.getElementById('searchInput');
  const liveSuggest = document.getElementById('liveSuggest');
  const liveProducts = document.getElementById('liveProducts');
  const liveShops = document.getElementById('liveShops');
  const liveLocations = document.getElementById('liveLocations');
  const liveProductsEmpty = document.getElementById('liveProductsEmpty');
  const liveShopsEmpty = document.getElementById('liveShopsEmpty');
  const liveLocationsEmpty = document.getElementById('liveLocationsEmpty');
  const uiLang = (document.body.dataset.lang || 'fr').toLowerCase();
  const langLabels = {
    fr: { products: 'produits', services: 'services', locations: 'locations', location: 'Location' },
    en: { products: 'products', services: 'services', locations: 'rentals', location: 'Rental' },
    ary: { products: 'mntjat', services: 'khdmat', locations: 'ijarat', location: 'Ijar' }
  };
  const l = langLabels[uiLang] || langLabels.fr;

  function toggleSuggestions(show) {
    if (!liveSuggest) return;
    liveSuggest.classList.toggle('show', !!show);
  }

  function clearSuggestions() {
    if (liveProducts) liveProducts.innerHTML = '';
    if (liveShops) liveShops.innerHTML = '';
    if (liveLocations) liveLocations.innerHTML = '';
    if (liveProductsEmpty) liveProductsEmpty.style.display = 'block';
    if (liveShopsEmpty) liveShopsEmpty.style.display = 'block';
    if (liveLocationsEmpty) liveLocationsEmpty.style.display = 'block';
  }

  function setSuggestionsLoading(active) {
    if (!liveSuggest || !liveSuggest.classList) return;
    liveSuggest.classList.toggle('is-loading', !!active);
  }

  function formatPrice(value) {
    const num = Number(value);
    if (Number.isNaN(num)) return '';
    return num.toFixed(2);
  }

  function renderProductSuggestions(items) {
    if (!liveProducts || !liveProductsEmpty) return;
    liveProducts.innerHTML = '';
    if (!items || items.length === 0) {
      liveProductsEmpty.style.display = 'block';
      return;
    }
    liveProductsEmpty.style.display = 'none';

    items.forEach((p) => {
      const link = document.createElement('a');
      link.href = p.url || '#';
      link.className = 'live-suggest-item';

      const img = document.createElement('img');
      img.className = 'live-suggest-thumb';
      const src = p.image_file ? `/static/uploads/${p.image_file}` : '';
      applyLocalFallbackImage(img, src, fallbackProductImage);
      img.alt = p.name || 'Produit';
      img.loading = 'lazy';
      img.decoding = 'async';

      const info = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'live-suggest-name';
      name.setAttribute('data-no-i18n', 'true');
      name.textContent = p.name || 'Produit';

      const priceText = formatPrice(p.final_price ?? p.price);

      const badges = document.createElement('div');
      badges.className = 'live-suggest-badges';

      if (p.category) {
        const catBadge = document.createElement('span');
        catBadge.className = 'live-badge category';
        catBadge.setAttribute('data-no-i18n', 'true');
        catBadge.textContent = p.category;
        badges.appendChild(catBadge);
      }

      if (typeof p.stock !== 'undefined') {
        const stockBadge = document.createElement('span');
        stockBadge.className = 'live-badge';
        if (p.stock <= 0) {
          stockBadge.classList.add('stock-out');
          stockBadge.textContent = 'Rupture';
        } else if (p.stock <= 5) {
          stockBadge.classList.add('stock-low');
          stockBadge.textContent = 'Stock bas';
        } else {
          stockBadge.textContent = 'En stock';
        }
        badges.appendChild(stockBadge);
      }

      if (priceText) {
        const priceBadge = document.createElement('span');
        priceBadge.className = 'live-badge price';
        priceBadge.textContent = `${priceText} DH`;
        badges.appendChild(priceBadge);
      }

      const meta = document.createElement('div');
      meta.className = 'live-suggest-meta';
      const priceSpan = document.createElement('span');
      priceSpan.textContent = priceText ? `${priceText} DH` : '';

      const dot = document.createElement('span');
      dot.textContent = priceText && p.shop_name ? ' â€¢ ' : '';

      const shopSpan = document.createElement('span');
      shopSpan.setAttribute('data-no-i18n', 'true');
      shopSpan.textContent = p.shop_name || '';

      meta.append(priceSpan, dot, shopSpan);
      info.append(name, badges, meta);
      link.append(img, info);

      liveProducts.appendChild(link);
    });
  }

  function renderShopSuggestions(items) {
    if (!liveShops || !liveShopsEmpty) return;
    liveShops.innerHTML = '';
    if (!items || items.length === 0) {
      liveShopsEmpty.style.display = 'block';
      return;
    }
    liveShopsEmpty.style.display = 'none';

    items.forEach((s) => {
      const link = document.createElement('a');
      link.href = s.url || '#';
      link.className = 'live-suggest-item';

      const img = document.createElement('img');
      img.className = 'live-suggest-thumb';
      const src = s.logo ? `/static/uploads/${s.logo}` : '';
      applyLocalFallbackImage(img, src, fallbackShopImage);
      img.alt = s.name || 'Boutique';
      img.loading = 'lazy';
      img.decoding = 'async';

      const info = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'live-suggest-name';
      name.setAttribute('data-no-i18n', 'true');
      name.textContent = s.name || 'Boutique';

      const meta = document.createElement('div');
      meta.className = 'live-suggest-meta';
      const physicalCount = Number(s.physical_count || 0);
      const serviceCount = Number(s.service_count || 0);
      const locationCount = Number(s.location_count || 0);
      meta.textContent = `${physicalCount} ${l.products} â€¢ ${serviceCount} ${l.services} â€¢ ${locationCount} ${l.locations}`;

      info.append(name, meta);
      link.append(img, info);
      liveShops.appendChild(link);
    });
  }

  function renderLocationSuggestions(items) {
    if (!liveLocations || !liveLocationsEmpty) return;
    liveLocations.innerHTML = '';
    if (!items || items.length === 0) {
      liveLocationsEmpty.style.display = 'block';
      return;
    }
    liveLocationsEmpty.style.display = 'none';

    items.forEach((location) => {
      const link = document.createElement('a');
      link.href = location.url || '#';
      link.className = 'live-suggest-item';

      const img = document.createElement('img');
      img.className = 'live-suggest-thumb';
      const src = location.cover ? `/static/uploads/rentals/${location.cover}` : '';
      applyLocalFallbackImage(img, src, fallbackLocationImage);
      img.alt = location.title || l.location;
      img.loading = 'lazy';
      img.decoding = 'async';

      const info = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'live-suggest-name';
      name.textContent = location.title || l.location;

      const meta = document.createElement('div');
      meta.className = 'live-suggest-meta';
      const price = Number(location.rent_dh || 0);
      const city = location.city || '';
      meta.textContent = `${price.toFixed(2)} DH${city ? ` â€¢ ${city}` : ''}`;

      info.append(name, meta);
      link.append(img, info);
      liveLocations.appendChild(link);
    });
  }

  let suggestRenderRafId = 0;
  function buildSuggestionsSignature(payload) {
    const next = payload || {};
    const products = Array.isArray(next.products) ? next.products : [];
    const shops = Array.isArray(next.shops) ? next.shops : [];
    const locations = Array.isArray(next.locations) ? next.locations : [];
    return JSON.stringify({
      p: products.map(item => [item && item.id, item && item.name, item && item.price, item && item.shop_name]),
      s: shops.map(item => [item && item.id, item && item.name, item && item.slug]),
      l: locations.map(item => [item && item.id, item && item.title, item && item.city, item && item.rent_dh])
    });
  }

  function getCachedSuggestions(query) {
    const key = String(query || '').trim().toLowerCase();
    return key ? (suggestionsCache.get(key) || null) : null;
  }

  function setCachedSuggestions(query, payload) {
    const key = String(query || '').trim().toLowerCase();
    if (!key) return;
    if (suggestionsCache.has(key)) {
      suggestionsCache.delete(key);
    }
    suggestionsCache.set(key, payload);
    if (suggestionsCache.size > 12) {
      const firstKey = suggestionsCache.keys().next().value;
      if (firstKey) suggestionsCache.delete(firstKey);
    }
  }

  function renderSuggestionsBatch(payload) {
    const next = payload || {};
    const signature = buildSuggestionsSignature(next);
    if (signature === lastSuggestionsSignature) {
      return;
    }
    if (suggestRenderRafId) {
      window.cancelAnimationFrame(suggestRenderRafId);
      suggestRenderRafId = 0;
    }
    suggestRenderRafId = window.requestAnimationFrame(() => {
      suggestRenderRafId = 0;
      renderProductSuggestions(next.products || []);
      renderShopSuggestions(next.shops || []);
      renderLocationSuggestions(next.locations || []);
      lastSuggestionsSignature = signature;
    });
  }

  async function loadSuggestions(query) {
    if (!liveSuggest) return;
    const q = (query || '').trim();
    if (!q || q.length < LIVE_SEARCH_MIN_CHARS) {
      if (suggestFetchController) {
        suggestFetchController.abort();
        suggestFetchController = null;
      }
      setSuggestionsLoading(false);
      toggleSuggestions(false);
      clearSuggestions();
      lastSuggestionsQuery = "";
      lastSuggestionsSignature = "";
      return;
    }

    toggleSuggestions(true);
    const normalizedQuery = q.toLowerCase();
    const cachedSuggestions = getCachedSuggestions(normalizedQuery);
    if (cachedSuggestions) {
      lastSuggestionsQuery = normalizedQuery;
      setSuggestionsLoading(false);
      renderSuggestionsBatch(cachedSuggestions);
      return;
    }
    setSuggestionsLoading(true);
    const requestId = suggestRequestSeq.next();

    if (suggestFetchController) {
      suggestFetchController.abort();
    }
    suggestFetchController = new AbortController();
    const currentController = suggestFetchController;

    try {
      const buildSuggestUrl = (base, query, limit) => `${base}?q=${encodeURIComponent(query)}&limit=${limit}`;
      const shouldQuerySecondary = q.length >= LIVE_SEARCH_SECONDARY_MIN_CHARS;
      const [prodRes, shopRes, locationRes] = await Promise.all([
        requestJSON(buildSuggestUrl(endpointSearchProducts, q, 6), {
          headers: { 'X-Requested-With': 'fetch' },
          signal: currentController.signal,
          credentials: 'same-origin',
          cache: 'no-store'
        }),
        shouldQuerySecondary
          ? requestJSON(buildSuggestUrl(endpointSearchShops, q, 6), {
            headers: { 'X-Requested-With': 'fetch' },
            signal: currentController.signal,
            credentials: 'same-origin',
            cache: 'no-store'
          })
          : Promise.resolve({ ok: true, data: { shops: [] } }),
        shouldQuerySecondary
          ? requestJSON(buildSuggestUrl(endpointSearchLocations, q, 6), {
            headers: { 'X-Requested-With': 'fetch' },
            signal: currentController.signal,
            credentials: 'same-origin',
            cache: 'no-store'
          })
          : Promise.resolve({ ok: true, data: { locations: [] } })
      ]);

      if (!suggestRequestSeq.isLatest(requestId)) {
        return;
      }

      const prodJson = (prodRes && prodRes.ok && prodRes.data && typeof prodRes.data === 'object')
        ? prodRes.data
        : { products: [] };
      const shopJson = (shopRes && shopRes.ok && shopRes.data && typeof shopRes.data === 'object')
        ? shopRes.data
        : { shops: [] };
      const locationJson = (locationRes && locationRes.ok && locationRes.data && typeof locationRes.data === 'object')
        ? locationRes.data
        : { locations: [] };

      const nextPayload = {
        products: prodJson.products || [],
        shops: shopJson.shops || [],
        locations: locationJson.locations || []
      };
      setCachedSuggestions(normalizedQuery, nextPayload);
      lastSuggestionsQuery = normalizedQuery;
      renderSuggestionsBatch(nextPayload);
    } catch (error) {
      if (error && error.name === 'AbortError') return;
      if (!suggestRequestSeq.isLatest(requestId)) return;
      console.error('Erreur suggestions:', error);
    } finally {
      if (suggestRequestSeq.isLatest(requestId)) {
        setSuggestionsLoading(false);
      }
      if (suggestFetchController === currentController) {
        suggestFetchController = null;
      }
    }
  }

  function debounce(fn, wait) {
    let t;
    return function(...args) {
      if (t) window.clearTimeout(t);
      t = window.setTimeout(() => fn.apply(this, args), wait);
    };
  }

  function applySearch(options = {}) {
    if (!searchInput) return;
    const searchValue = searchInput.value.trim();
    const force = options.force === true;
    if (!force && !shouldQueryLiveSearch(searchValue)) {
      toggleSuggestions(false);
      clearSuggestions();
      return;
    }
    markUserInteracted();
    currentFilters.q = searchValue;
    currentFilters.page = 1;
    updateURL({ replace: !!options.replaceHistory });
    loadProducts({
      preserveScroll: true,
      showState: false,
      loadingMode: options.loadingMode || 'overlay',
      triggerEl: options.triggerEl || null
    });
    if (searchValue.length >= LIVE_SEARCH_MIN_CHARS) {
      loadSuggestions(searchValue);
    } else {
      loadSuggestions('');
    }
  }

  if (searchForm) {
    searchForm.addEventListener('submit', function(e) {
      e.preventDefault();
      const trigger = (e.submitter && typeof e.submitter.setAttribute === 'function')
        ? e.submitter
        : document.getElementById('searchButton');
      applySearch({ replaceHistory: false, loadingMode: 'overlay', force: true, triggerEl: trigger });
    });
  }

  if (searchInput) {
    let isComposing = false;
    const debounced = debounce(() => {
      if (isComposing) return;
      const value = searchInput.value.trim();
      if (!shouldQueryLiveSearch(value)) {
        toggleSuggestions(false);
        clearSuggestions();
        return;
      }
      applySearch({ replaceHistory: true, loadingMode: 'inline' });
    }, LIVE_SEARCH_DEBOUNCE_MS);

    searchInput.addEventListener('input', () => {
      markUserInteracted();
      debounced();
    });
    searchInput.addEventListener('compositionstart', () => { isComposing = true; });
    searchInput.addEventListener('compositionend', () => {
      isComposing = false;
      debounced();
    });
    searchInput.addEventListener('focus', () => {
      const q = searchInput.value.trim();
      if (q) loadSuggestions(q);
    });
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        applySearch({
          replaceHistory: false,
          loadingMode: 'overlay',
          force: true,
          triggerEl: document.getElementById('searchButton') || searchInput
        });
      }
    });
  }

  document.addEventListener('click', (e) => {
    if (!liveSuggest || !searchForm) return;
    if (searchForm.contains(e.target) || liveSuggest.contains(e.target)) return;
    toggleSuggestions(false);
  });

  // ===== TOAST =====
  function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    const toastMessage = document.getElementById('toast-message');
    const toastClose = document.getElementById('toast-close');
    
    if (toast && toastMessage) {
      toast.className = 'toast';
      toast.classList.add(type);
      toastMessage.textContent = message;
      toast.style.display = 'flex';
      
      const hideTimeout = setTimeout(() => {
        toast.style.display = 'none';
      }, 3000);
      
      if (toastClose) {
        const closeHandler = () => {
          toast.style.display = 'none';
          clearTimeout(hideTimeout);
          toastClose.removeEventListener('click', closeHandler);
        };
        
        toastClose.addEventListener('click', closeHandler);
      }
    }
  }

  // ===== DÉFILEMENT CHIPS ACTIFS =====
  function scrollToActiveChip() {
    const activeChip = document.querySelector('.category-chip.active');
    const chipsContainer = document.querySelector('.category-chips');
    
    if (activeChip && chipsContainer) {
      const chipPosition = activeChip.offsetLeft;
      const containerWidth = chipsContainer.clientWidth;
      const chipWidth = activeChip.clientWidth;
      
      chipsContainer.scrollTo({
        left: chipPosition - (containerWidth / 2) + (chipWidth / 2),
        behavior: 'smooth'
      });
    }
  }

  const loadMoreBtn = document.getElementById('loadMoreBtn');
  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', function() {
      loadNextPage();
    });
  }

  function runModeOnboarding() {
    const modeSwitch = document.querySelector('.mode-switch');
    const intro = document.getElementById('modeIntro');
    if (!modeSwitch || !intro) return;
    const key = 'home_mode_onboarding_seen_v1';
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, '1');
    modeSwitch.classList.add('onboarding');
    intro.classList.add('onboarding');
    if (modeOnboardingTimer) {
      window.clearTimeout(modeOnboardingTimer);
      modeOnboardingTimer = null;
    }
    modeOnboardingTimer = window.setTimeout(() => {
      modeSwitch.classList.remove('onboarding');
      intro.classList.remove('onboarding');
      modeOnboardingTimer = null;
    }, 4200);
  }

  function clearPageTimers() {
    if (pageBadgeTimer) {
      window.clearTimeout(pageBadgeTimer);
      pageBadgeTimer = null;
    }
    if (urlStateTimer) {
      window.clearTimeout(urlStateTimer);
      urlStateTimer = null;
    }
    if (modeOnboardingTimer) {
      window.clearTimeout(modeOnboardingTimer);
      modeOnboardingTimer = null;
    }
    if (activeChipScrollTimer) {
      window.clearTimeout(activeChipScrollTimer);
      activeChipScrollTimer = null;
    }
  }

  function abortInFlightHomeRequests() {
    if (productsFetchController) {
      productsFetchController.abort();
      productsFetchController = null;
    }
    if (suggestFetchController) {
      suggestFetchController.abort();
      suggestFetchController = null;
    }
  }

  let scrollTicking = false;
  window.addEventListener('scroll', () => {
    if (document.hidden) return;
    if (scrollTicking) return;
    scrollTicking = true;
    window.requestAnimationFrame(() => {
      updateScrollToTopVisibility();
      updateFloatingPagination();
      if (userInteracted && window.innerWidth <= 768 && totalPages > 1) {
        updatePageBadge(true);
      }
      scrollTicking = false;
    });
  }, { passive: true });

  // ===== LANCEMENT =====
  syncFiltersFromUrl();
  runModeOnboarding();
  attachFilterEvents();
  attachPaginationEvents(document.getElementById('paginationContainer'));
  attachProductEvents(document.getElementById('productsContainer'));
  initLazyShopVideos(document.getElementById('productsContainer'));
  updateActiveFilters();
  const initialPagination = document.getElementById('paginationContainer');
  if (initialPagination) {
    const pages = parseInt(initialPagination.getAttribute('data-pages') || '1', 10);
    totalPages = Number.isNaN(pages) ? 1 : pages;
  }
  updateLoadMoreButton();
  updateFloatingPagination();
  updateScrollToTopVisibility();
  updatePageBadge(false);
  bindHomeIntentPrefetch();
  scheduleHomeIdlePrefetch();
  let resizeRafId = 0;
  window.addEventListener('resize', () => {
    if (document.hidden) return;
    if (resizeRafId) return;
    resizeRafId = window.requestAnimationFrame(() => {
      resizeRafId = 0;
      updateActiveFilters();
      updateLoadMoreButton();
      updateFloatingPagination();
    });
  });

  if (floatingPrevBtn) {
    floatingPrevBtn.addEventListener('click', function() {
      const current = parseInt(currentFilters.page || 1, 10);
      if (current <= 1) return;
      currentFilters.page = current - 1;
      updateURL();
      loadProducts({
        triggerEl: floatingPrevBtn,
        loadingMode: 'silent',
        preserveScroll: true,
        anchorSelector: '#floatingPaginationNav',
        showState: false
      });
    });
  }

  if (floatingNextBtn) {
    floatingNextBtn.addEventListener('click', function() {
      const current = parseInt(currentFilters.page || 1, 10);
      const total = totalPages || 1;
      if (current >= total) return;
      currentFilters.page = current + 1;
      updateURL();
      loadProducts({
        triggerEl: floatingNextBtn,
        loadingMode: 'silent',
        preserveScroll: true,
        anchorSelector: '#floatingPaginationNav',
        showState: false
      });
    });
  }

  // Démarrer avec chips actifs visibles
  activeChipScrollTimer = window.setTimeout(() => {
    scrollToActiveChip();
    activeChipScrollTimer = null;
  }, 500);

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) return;
    clearPageTimers();
  });

  window.addEventListener('pagehide', () => {
    clearPageTimers();
    abortInFlightHomeRequests();
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initShopHomePage, { once: true });
} else {
  initShopHomePage();
}
})();

