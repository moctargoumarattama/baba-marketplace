(function () {
"use strict";
if (window.__BM_SHOP_DETAIL_BOOTSTRAP__) {
    return;
}
window.__BM_SHOP_DETAIL_BOOTSTRAP__ = true;

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

async function fallbackRequest(url, options, expect) {
    const opts = Object.assign({}, options || {});
    const response = await fetch(url, opts);
    let data = null;

    if (expect === "json") {
        try {
            data = await response.json();
        } catch (_jsonError) {
            data = null;
        }
    } else {
        try {
            data = await response.text();
        } catch (_textError) {
            data = "";
        }
    }

    return {
        ok: response.ok,
        status: response.status,
        data,
        error: response.ok ? null : (response.statusText || `HTTP ${response.status}`),
        aborted: false,
        timedOut: false
    };
}

const bmFetchApi = window.BMAjaxFetch || null;

async function bmFetchJSON(url, options) {
    if (bmFetchApi && typeof bmFetchApi.requestJSON === "function") {
        return bmFetchApi.requestJSON(url, options || {});
    }
    try {
        return await fallbackRequest(url, options, "json");
    } catch (error) {
        return {
            ok: false,
            status: 0,
            data: null,
            error: String((error && error.message) || "network_error"),
            aborted: !!(error && error.name === "AbortError"),
            timedOut: false
        };
    }
}

function initShopDetailPage() {
    if (window.__BM_SHOP_DETAIL_INIT__) {
        return;
    }
    window.__BM_SHOP_DETAIL_INIT__ = true;
    const pageConfig = readConfig("shopDetailPageConfig", {
        fetchBase: window.location.pathname,
        infiniteScrollOffset: 140,
    });
    // Elements
    const productsGrid = document.getElementById('productsGrid');
    const loadingSpinner = document.getElementById('loadingSpinner');
    const noResults = document.getElementById('noResults');
    const productCount = document.getElementById('productCount');
    const resultsTitle = document.getElementById('resultsTitle');
    const searchInput = document.getElementById('searchInput');
    const sortSelect = document.getElementById('sortSelect');
    const filterForm = document.getElementById('filterForm');
    const resetFilters = document.getElementById('resetFilters');
    const clearSearch = document.getElementById('clearSearch');
    const detailFetchBase = (filterForm && filterForm.getAttribute('action'))
        ? filterForm.getAttribute('action')
        : String(pageConfig.fetchBase || window.location.pathname);

    const kindInput = document.getElementById('kindInput');
    const catInput = document.getElementById('catInput');
    const modeAllLabel = document.getElementById('sdModeAllLabel');
    const categoryStripWrap = document.getElementById('sdCategoryStripWrap');
    const categoryStripTitleText = document.getElementById('sdCategoryStripTitleText');
    const sidebarCategoriesWrap = document.getElementById('sidebarCategoriesWrap');
    const sidebarAllCatsCount = document.getElementById('sidebarAllCatsCount');
    const noResultsTitle = document.getElementById('noResultsTitle');
    const noResultsText = document.getElementById('noResultsText');
    const initialPage = parseInt(productsGrid ? (productsGrid.getAttribute('data-current-page') || '1') : '1', 10);
    let currentPage = (Number.isNaN(initialPage) ? 2 : (initialPage + 1));
    let isLoading = false;
    let hasMore = !!(productsGrid && productsGrid.getAttribute('data-has-more') === '1');
    let lastTotal = parseInt(sidebarAllCatsCount ? (sidebarAllCatsCount.textContent || '0') : '0', 10) || 0;
    let productsFetchController = null;
    const productsRequestSeq = (
        window.BMAjaxGuard &&
        typeof window.BMAjaxGuard.makeRequestSeq === "function"
    ) ? window.BMAjaxGuard.makeRequestSeq() : createLocalRequestSeq();
    let currentFilters = {
        q: searchInput ? searchInput.value.trim() : '',
        cat: catInput ? catInput.value : '',
        sort: sortSelect ? sortSelect.value : '',
        kind: kindInput ? kindInput.value : ''
    };

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

    document.addEventListener('click', (event) => {
        const prevBtn = event.target.closest('.js-slide-prev');
        const nextBtn = event.target.closest('.js-slide-next');
        if (!prevBtn && !nextBtn) return;
        event.preventDefault();
        event.stopPropagation();
        const container = event.target.closest('[data-slider-images]');
        updateCardSlider(container, prevBtn ? -1 : 1);
    });

    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
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

    function getKindLabel(kind) {
        if (kind === 'service') return 'Services';
        if (kind === 'physical') return 'Produits';
        return 'Tout';
    }

    function getItemLabel(kind) {
        if (kind === 'service') return 'service(s)';
        if (kind === 'physical') return 'produit(s)';
        return 'article(s)';
    }

    function syncEmptyStateCopy() {
        const kind = normalizeKind(currentFilters.kind);
        const hasQuery = !!(currentFilters.q && currentFilters.q.trim());

        if (noResultsTitle) {
            noResultsTitle.textContent =
                kind === 'service' ? 'Aucun service trouvé' :
                kind === 'physical' ? 'Aucun produit trouvé' :
                'Aucun article trouvé';
        }

        if (noResultsText) {
            if (!hasQuery) {
                noResultsText.textContent = '';
            } else {
                noResultsText.textContent =
                    kind === 'service' ? 'Aucun service ne correspond ? votre recherche' :
                    kind === 'physical' ? 'Aucun produit ne correspond ? votre recherche' :
                    'Aucun article ne correspond ? votre recherche';
            }
        }

        if (clearSearch) {
            clearSearch.textContent =
                kind === 'service' ? 'Voir tous les services' :
                kind === 'physical' ? 'Voir tous les produits' :
                'Voir tout';
        }

        if (searchInput) {
            searchInput.placeholder =
                kind === 'service' ? 'Nom du service...' :
                kind === 'physical' ? 'Nom du produit...' :
                'Nom (produit ou service)...';
        }
    }

    function syncTotalsUI() {
        if (sidebarAllCatsCount) {
            sidebarAllCatsCount.textContent = String(lastTotal);
        }

        if (productCount) {
            const kind = normalizeKind(currentFilters.kind);
            productCount.textContent = `${lastTotal} ${getItemLabel(kind)}`;
        }

        if (resultsTitle && !(currentFilters.q && currentFilters.q.trim())) {
            const kind = normalizeKind(currentFilters.kind);
            resultsTitle.textContent = getKindLabel(kind);
        }
    }

    function syncKindUI() {
        const kind = normalizeKind(currentFilters.kind);
        const hasKind = !!kind;

        if (modeAllLabel) {
            modeAllLabel.classList.toggle('kind-hidden', hasKind);
        }
        if (categoryStripWrap) {
            categoryStripWrap.classList.toggle('kind-hidden', !hasKind);
        }
        if (sidebarCategoriesWrap) {
            sidebarCategoriesWrap.classList.toggle('kind-hidden', !hasKind);
        }

        if (categoryStripTitleText) {
            categoryStripTitleText.textContent =
                kind === 'physical' ? 'Catégories produits' :
                kind === 'service' ? 'Catégories services' :
                'Catégories';
        }

        document.querySelectorAll('.sd-mode-btn[data-kind]').forEach(btn => {
            const val = normalizeKind(btn.getAttribute('data-kind'));
            const isActive = hasKind && val === kind;
            btn.classList.toggle('active', isActive);
            btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });

        // Active states (categories)
        document.querySelectorAll('[data-filter=\"category\"][data-value]').forEach(el => {
            const value = (el.getAttribute('data-value') || '').trim();
            const isActive = (currentFilters.cat || '') === value;
            el.classList.toggle('active', isActive);
        });

        // Hide categories with 0 count in selected kind
        const catChips = document.querySelectorAll('.sd-cat-chip[data-filter=\"category\"]');
        const catLinks = document.querySelectorAll('#sidebarCategoriesList [data-filter=\"category\"]');

        if (!hasKind) {
            catChips.forEach(el => el.classList.remove('kind-hidden'));
            catLinks.forEach(el => el.classList.remove('kind-hidden'));
            syncTotalsUI();
            syncEmptyStateCopy();
            return;
        }

        catChips.forEach(el => {
            const value = (el.getAttribute('data-value') || '').trim();
            if (!value) {
                el.classList.remove('kind-hidden');
                return;
            }
            const count = getCountForKind(el, kind);
            const shouldHide = count <= 0 && !el.classList.contains('active');
            el.classList.toggle('kind-hidden', shouldHide);
        });

        catLinks.forEach(el => {
            const value = (el.getAttribute('data-value') || '').trim();
            if (!value) {
                el.classList.remove('kind-hidden');
                return;
            }
            const count = getCountForKind(el, kind);
            const shouldHide = count <= 0 && !el.classList.contains('active');
            el.classList.toggle('kind-hidden', shouldHide);

            const countEl = el.querySelector('.category-count');
            if (countEl) {
                countEl.textContent = String(count);
            }
        });

        syncTotalsUI();
        syncEmptyStateCopy();
    }

    function resetLoadingState() {
        if (productsFetchController) {
            productsFetchController.abort();
        }
        productsFetchController = null;
        isLoading = false;
        hasMore = true;
    }

    function buildParams(pageNumber) {
        const params = new URLSearchParams();
        params.set('page', String(pageNumber));
        Object.keys(currentFilters).forEach(key => {
            const val = currentFilters[key];
            if (val !== null && typeof val !== 'undefined' && String(val).trim() !== '') {
                params.set(key, String(val));
            }
        });
        return params;
    }

    function updateFiltersFromInputs() {
        resetLoadingState();
        currentFilters.q = (searchInput ? searchInput.value.trim() : '');
        currentFilters.sort = (sortSelect ? sortSelect.value : '');
        if (kindInput) kindInput.value = normalizeKind(currentFilters.kind);
        if (catInput) catInput.value = (currentFilters.cat || '');

        currentPage = 1;
        if (productsGrid) productsGrid.innerHTML = '';
        loadProducts();
        syncKindUI();
    }

    function setKind(nextKind) {
        resetLoadingState();
        const desired = normalizeKind(nextKind);
        const current = normalizeKind(currentFilters.kind);
        currentFilters.kind = (current === desired) ? '' : desired;
        currentFilters.cat = '';

        if (kindInput) kindInput.value = normalizeKind(currentFilters.kind);
        if (catInput) catInput.value = '';

        currentPage = 1;
        if (productsGrid) productsGrid.innerHTML = '';
        loadProducts();
        syncKindUI();
    }

    function setCategory(value) {
        resetLoadingState();
        currentFilters.cat = (value || '').toString().trim();
        if (catInput) catInput.value = currentFilters.cat;

        currentPage = 1;
        if (productsGrid) productsGrid.innerHTML = '';
        loadProducts();
        syncKindUI();
    }

    function loadProducts() {
        if (isLoading || !hasMore) return;

        isLoading = true;
        if (loadingSpinner) loadingSpinner.classList.remove('d-none');

        if (productsFetchController) {
            productsFetchController.abort();
        }
        productsFetchController = new AbortController();
        const requestId = productsRequestSeq.next();

        const params = buildParams(currentPage);
        const query = params.toString();
        const separator = detailFetchBase.includes('?') ? '&' : '?';
        const fetchUrl = query
            ? `${detailFetchBase}${separator}${query}&ajax=1`
            : `${detailFetchBase}${separator}ajax=1`;
        bmFetchJSON(fetchUrl, {
            signal: productsFetchController.signal,
            headers: { 'X-Requested-With': 'fetch' },
            cache: 'no-store',
            credentials: 'same-origin'
        })
            .then(result => {
                if (!productsRequestSeq.isLatest(requestId)) return;
                if (!result || result.aborted) return;
                if (!result.ok) {
                    throw new Error(result.error || `HTTP ${result.status || 0}`);
                }

                const data = (result.data && typeof result.data === 'object') ? result.data : null;
                if (!data || typeof data.products !== 'string') return;

                if (currentPage === 1) {
                    if (productsGrid) productsGrid.innerHTML = data.products;
                    lastTotal = typeof data.total === 'number' ? data.total : lastTotal;

                    if (lastTotal === 0) {
                        if (noResults) noResults.classList.remove('d-none');
                        if (productsGrid) productsGrid.classList.add('d-none');
                    } else {
                        if (noResults) noResults.classList.add('d-none');
                        if (productsGrid) productsGrid.classList.remove('d-none');
                    }
                } else {
                    if (productsGrid) productsGrid.insertAdjacentHTML('beforeend', data.products);
                }

                hasMore = !!data.has_more;
                currentPage++;
                syncKindUI();
            })
            .catch(error => {
                if (!productsRequestSeq.isLatest(requestId)) return;
                if (error && error.name === 'AbortError') return;
                console.error('Error loading products:', error);
            })
            .finally(() => {
                if (!productsRequestSeq.isLatest(requestId)) return;
                isLoading = false;
                if (loadingSpinner) loadingSpinner.classList.add('d-none');
            });
    }

    function handleScroll() {
        const scrollPosition = window.innerHeight + window.scrollY;
        const scrollOffset = Number(pageConfig.infiniteScrollOffset || 140);
        const pageHeight = document.documentElement.scrollHeight - (Number.isFinite(scrollOffset) ? scrollOffset : 140);
        if (scrollPosition >= pageHeight && hasMore && !isLoading) {
            loadProducts();
        }
    }

    // Listeners
    if (filterForm) {
        filterForm.addEventListener('submit', function(e) {
            e.preventDefault();
            updateFiltersFromInputs();
        });
    }

    if (searchInput) searchInput.addEventListener('input', debounce(updateFiltersFromInputs, 450));
    if (sortSelect) sortSelect.addEventListener('change', updateFiltersFromInputs);

    document.querySelectorAll('.sd-mode-btn[data-kind]').forEach(btn => {
        btn.addEventListener('click', function() {
            setKind(this.getAttribute('data-kind'));
        });
    });

    document.querySelectorAll('.sd-cat-chip[data-filter=\"category\"]').forEach(chip => {
        chip.addEventListener('click', function() {
            setCategory(this.getAttribute('data-value'));
        });
    });

    document.querySelectorAll('#sidebarCategoriesList [data-filter=\"category\"]').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            setCategory(this.getAttribute('data-value'));
        });
    });

    if (resetFilters) {
        resetFilters.addEventListener('click', function() {
            if (searchInput) searchInput.value = '';
            if (sortSelect) sortSelect.value = '';
            currentFilters.q = '';
            currentFilters.sort = '';
            currentFilters.cat = '';
            currentFilters.kind = '';
            if (kindInput) kindInput.value = '';
            if (catInput) catInput.value = '';
            currentPage = 1;
            resetLoadingState();
            if (productsGrid) productsGrid.innerHTML = '';
            loadProducts();
            syncKindUI();
        });
    }

    if (clearSearch) {
        clearSearch.addEventListener('click', function() {
            if (searchInput) searchInput.value = '';
            updateFiltersFromInputs();
        });
    }

    if (productsGrid && productsGrid.children.length === 0) {
        if (noResults) noResults.classList.remove('d-none');
    }

    window.addEventListener('scroll', debounce(handleScroll, 100), { passive: true });

    syncKindUI();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initShopDetailPage, { once: true });
} else {
    initShopDetailPage();
}
})();

