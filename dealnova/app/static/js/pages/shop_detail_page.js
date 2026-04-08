(function () {
"use strict";
if (window.__BM_SHOP_DETAIL_BOOTSTRAP__) {
    return;
}
window.__BM_SHOP_DETAIL_BOOTSTRAP__ = true;
const createRequestSeq =
    window.BMCoreDom && typeof window.BMCoreDom.makeRequestSeq === "function"
        ? window.BMCoreDom.makeRequestSeq
        : window.BMAjaxGuard.makeRequestSeq.bind(window.BMAjaxGuard);

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

function navigateToUrl(url) {
    const targetUrl = String(url || "").trim();
    if (!targetUrl) return;
    if (window.BMPageNav && typeof window.BMPageNav.navigate === "function") {
        window.BMPageNav.navigate(targetUrl);
        return;
    }
    window.location.assign(targetUrl);
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
    const loadMoreWrap = document.getElementById('loadMoreWrap');
    const loadMoreButton = document.getElementById('loadMoreProducts');
    const fallbackPagination = document.getElementById('fallbackPagination');
    const scrollTopButton = document.getElementById('shopScrollTop');
    const backLinks = Array.from(document.querySelectorAll('[data-shop-back-link]'));
    const catalogRow = document.getElementById('shopCatalogRow');
    const locationPanel = document.getElementById('shopLocationPanel');
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
    let currentLoadingMode = '';
    let gridUnlockTimer = null;
    let rentalVideoObserver = null;
    const productsRequestSeq = createRequestSeq();
    let currentFilters = {
        q: searchInput ? searchInput.value.trim() : '',
        cat: catInput ? catInput.value : '',
        sort: sortSelect ? sortSelect.value : '',
        kind: kindInput ? kindInput.value : String(pageConfig.initialKind || '')
    };
    const liveSearchDelay = (
        window.matchMedia &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(pointer: coarse)').matches
    ) ? 220 : 160;

    function filtersEqual(left, right) {
        return ['q', 'cat', 'sort', 'kind'].every(key => String((left && left[key]) || '') === String((right && right[key]) || ''));
    }

    function getBackFallbackUrl() {
        return String(pageConfig.fallbackBackUrl || '/shops');
    }

    function canGoBackInApp() {
        if (!window.history || window.history.length <= 1) return false;
        if (!document.referrer) return false;
        try {
            const referrerUrl = new URL(document.referrer, window.location.origin);
            return referrerUrl.origin === window.location.origin;
        } catch (_error) {
            return false;
        }
    }

    function handleBackNavigation(event) {
        if (event) event.preventDefault();
        if (canGoBackInApp()) {
            window.history.back();
            return;
        }
        navigateToUrl(getBackFallbackUrl());
    }

    function initScrollTopButton() {
        if (!scrollTopButton) return;

        const prefersReducedMotion = (
            window.matchMedia &&
            typeof window.matchMedia === 'function' &&
            window.matchMedia('(prefers-reduced-motion: reduce)').matches
        );

        let ticking = false;
        let isVisible = null;

        function applyScrollTopVisibility() {
            const revealAfter = Math.max(220, Math.round(window.innerHeight * 0.42));
            const nextVisible = window.scrollY > revealAfter;
            if (nextVisible !== isVisible) {
                scrollTopButton.classList.toggle('show', nextVisible);
                isVisible = nextVisible;
            }
        }

        function onScroll() {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(() => {
                applyScrollTopVisibility();
                ticking = false;
            });
        }

        function scrollPageToTop() {
            const behavior = prefersReducedMotion ? 'auto' : 'smooth';
            try {
                window.scrollTo({ top: 0, behavior });
            } catch (_error) {
                window.scrollTo(0, 0);
            }

            if (document.documentElement && typeof document.documentElement.scrollTo === 'function') {
                try {
                    document.documentElement.scrollTo({ top: 0, behavior });
                } catch (_error) {
                    document.documentElement.scrollTop = 0;
                }
            } else if (document.documentElement) {
                document.documentElement.scrollTop = 0;
            }

            if (document.body && typeof document.body.scrollTo === 'function') {
                try {
                    document.body.scrollTo({ top: 0, behavior });
                } catch (_error) {
                    document.body.scrollTop = 0;
                }
            } else if (document.body) {
                document.body.scrollTop = 0;
            }

            window.requestAnimationFrame(() => {
                if (window.scrollY > 4) {
                    window.scrollTo(0, 0);
                    if (document.documentElement) document.documentElement.scrollTop = 0;
                    if (document.body) document.body.scrollTop = 0;
                }
            });
        }

        window.addEventListener('scroll', onScroll, { passive: true });
        applyScrollTopVisibility();

        function handleScrollTopActivate(event) {
            event.preventDefault();
            event.stopPropagation();
            scrollPageToTop();
        }

        scrollTopButton.addEventListener('click', handleScrollTopActivate);
        scrollTopButton.addEventListener('touchend', handleScrollTopActivate, { passive: false });
    }

    function buildStateUrl() {
        const params = new URLSearchParams();
        ['q', 'cat', 'sort', 'kind'].forEach(key => {
            const value = currentFilters[key];
            if (value !== null && typeof value !== 'undefined' && String(value).trim() !== '') {
                params.set(key, String(value).trim());
            }
        });
        const query = params.toString();
        return query ? `${detailFetchBase}?${query}` : detailFetchBase;
    }

    function syncStateUrl() {
        if (!window.history || typeof window.history.replaceState !== 'function') return;
        const nextUrl = buildStateUrl();
        const currentUrl = `${window.location.pathname}${window.location.search}`;
        if (nextUrl !== currentUrl) {
            window.history.replaceState(null, '', nextUrl);
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

    function initShopLocationCarousels(scope) {
        (scope || document).querySelectorAll('#shopLocationPanel .js-card-carousel').forEach(function (carousel) {
            if (carousel.dataset.carouselInit === '1') return;
            carousel.dataset.carouselInit = '1';

            const track = carousel.querySelector('.rental-track');
            const prev = carousel.querySelector('.js-prev');
            const next = carousel.querySelector('.js-next');
            const dots = carousel.querySelectorAll('.slide-dot');
            const slides = track ? Array.from(track.children) : [];
            if (!track || slides.length <= 1) return;

            let index = 0;
            let touchStartX = 0;

            function render() {
                track.style.transform = `translateX(-${index * 100}%)`;
                dots.forEach((dot, dotIndex) => {
                    dot.classList.toggle('active', dotIndex === index);
                });
            }

            function go(step) {
                index += step;
                if (index >= slides.length) index = 0;
                if (index < 0) index = slides.length - 1;
                render();
            }

            if (prev) {
                prev.addEventListener('click', function (event) {
                    event.preventDefault();
                    event.stopPropagation();
                    go(-1);
                });
            }

            if (next) {
                next.addEventListener('click', function (event) {
                    event.preventDefault();
                    event.stopPropagation();
                    go(1);
                });
            }

            carousel.addEventListener('touchstart', function (event) {
                touchStartX = event.changedTouches[0].screenX;
            }, { passive: true });

            carousel.addEventListener('touchend', function (event) {
                const delta = event.changedTouches[0].screenX - touchStartX;
                if (Math.abs(delta) <= 35) return;
                go(delta < 0 ? 1 : -1);
            }, { passive: true });

            render();
        });
    }

    function initShopLocationVideos(scope) {
        const root = scope || document;
        const videos = root.querySelectorAll('#shopLocationPanel .js-lazy-rental-video');
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
            const promise = video.play();
            if (promise && typeof promise.catch === 'function') {
                promise.catch(function () {});
            }
        }

        if ('IntersectionObserver' in window && !rentalVideoObserver) {
            rentalVideoObserver = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    const video = entry.target;
                    if (!video) return;
                    if (entry.isIntersecting && entry.intersectionRatio >= 0.2) {
                        hydrate(video);
                        playIfPossible(video);
                        return;
                    }
                    try {
                        video.pause();
                    } catch (_error) {}
                });
            }, { rootMargin: '140px 0px', threshold: [0, 0.2, 0.6] });
        }

        if (!('IntersectionObserver' in window)) {
            videos.forEach(function (video) {
                hydrate(video);
                playIfPossible(video);
            });
            return;
        }

        videos.forEach(function (video) {
            if (video.dataset.videoObserved === '1') return;
            video.dataset.videoObserved = '1';
            rentalVideoObserver.observe(video);
        });
    }

    function normalizeKind(value) {
        const kind = (value || '').toString().trim().toLowerCase();
        if (kind === 'physical' || kind === 'service' || kind === 'location') return kind;
        return '';
    }

    function isCatalogKind(kind) {
        return kind === 'physical' || kind === 'service';
    }

    function getCountForKind(el, kind) {
        if (!el || !kind) return 0;
        const key = kind === 'physical' ? 'countPhysical' : 'countService';
        const raw = (el.dataset && el.dataset[key]) ? el.dataset[key] : '0';
        const count = parseInt(raw, 10);
        return Number.isNaN(count) ? 0 : count;
    }

    function getKindLabel(kind) {
        if (kind === 'location') return 'Locations';
        if (kind === 'service') return 'Services';
        if (kind === 'physical') return 'Produits';
        return String(pageConfig.defaultCatalogLabel || 'Tout le catalogue');
    }

    function getItemLabel(kind) {
        if (kind === 'location') return 'annonce(s)';
        if (kind === 'service') return 'service(s)';
        if (kind === 'physical') return 'produit(s)';
        return String(pageConfig.defaultItemLabel || 'article(s)');
    }

    function shouldShowMixedDefaultState() {
        const kind = normalizeKind(currentFilters.kind);
        if (kind) return false;
        if (!pageConfig.hasProductUniverse || !pageConfig.hasLocationMode) return false;
        const hasCatalogFilters = !!(
            (currentFilters.q && currentFilters.q.trim()) ||
            (currentFilters.cat && String(currentFilters.cat).trim())
        );
        return !hasCatalogFilters;
    }

    function getDisplayTotalCount() {
        if (!shouldShowMixedDefaultState()) {
            return lastTotal;
        }
        const locationTotal = parseInt(pageConfig.locationTotal || '0', 10);
        return lastTotal + (Number.isNaN(locationTotal) ? 0 : locationTotal);
    }

    function getResultsHeading(kind, queryText) {
        const cleanQuery = String(queryText || '').trim();
        if (cleanQuery) return `Recherche : "${cleanQuery}"`;
        return getKindLabel(kind);
    }

    function getEmptyHeading(kind) {
        if (kind === 'location') return 'Aucune annonce';
        if (kind === 'service') return 'Aucun service';
        if (kind === 'physical') return 'Aucun produit';
        return String(pageConfig.defaultEmptyHeading || 'Aucun article');
    }

    function syncContentPanels() {
        const kind = normalizeKind(currentFilters.kind);
        const showCatalog = !!catalogRow && !!pageConfig.hasProductUniverse && kind !== 'location';
        const showLocation = !!locationPanel && (kind === '' || kind === 'location');

        if (catalogRow) {
            catalogRow.classList.toggle('d-none', !showCatalog);
        }
        if (locationPanel) {
            locationPanel.classList.toggle('d-none', !showLocation);
        }
        if (showLocation) {
            initShopLocationCarousels(locationPanel || document);
            initShopLocationVideos(locationPanel || document);
        }
    }

    function syncEmptyStateCopy() {
        const kind = normalizeKind(currentFilters.kind);
        const queryText = (currentFilters.q && currentFilters.q.trim()) || '';
        const hasFilters = !!(
            queryText ||
            (currentFilters.cat && String(currentFilters.cat).trim()) ||
            (currentFilters.sort && String(currentFilters.sort).trim()) ||
            kind
        );

        if (noResultsTitle) {
            noResultsTitle.textContent = getEmptyHeading(kind);
        }

        if (noResultsText) {
            if (queryText) {
                noResultsText.textContent = 'Essaie un mot plus simple.';
            } else if (hasFilters) {
                noResultsText.textContent = 'Essaie un autre filtre.';
            } else {
                noResultsText.textContent = 'Aucun contenu pour le moment.';
            }
        }

        if (clearSearch) {
            clearSearch.textContent =
                kind === 'service' ? 'Tous les services' :
                kind === 'physical' ? 'Tous les produits' :
                String(pageConfig.defaultClearLabel || 'Tout voir');
        }

        if (searchInput) {
            searchInput.placeholder =
                kind === 'service' ? 'Rechercher un service...' :
                kind === 'physical' ? 'Rechercher un produit...' :
                String(pageConfig.defaultSearchPlaceholder || 'Rechercher dans la boutique...');
        }

        if (sortSelect) {
            const labels = {
                '': 'Plus recent',
                new: 'Nouveautes',
                low: 'Prix bas',
                high: 'Prix haut',
                promo: "Promos d'abord"
            };
            Object.keys(labels).forEach(value => {
                const option = sortSelect.querySelector(`option[value="${value}"]`);
                if (option) {
                    option.textContent = labels[value];
                }
            });
            if (!sortSelect.querySelector('option[value="promo"]')) {
                const promoOption = document.createElement('option');
                promoOption.value = 'promo';
                promoOption.textContent = labels.promo;
                sortSelect.appendChild(promoOption);
            }
        }

        if (resetFilters) {
            resetFilters.textContent = 'Tout effacer';
        }
    }

    function syncTotalsUI() {
        const displayTotal = getDisplayTotalCount();
        if (sidebarAllCatsCount) {
            sidebarAllCatsCount.textContent = String(lastTotal);
        }

        if (productCount) {
            const kind = normalizeKind(currentFilters.kind);
            productCount.textContent = `${displayTotal} ${getItemLabel(kind)}`;
        }

        if (resultsTitle) {
            const kind = normalizeKind(currentFilters.kind);
            resultsTitle.textContent = getResultsHeading(kind, currentFilters.q);
        }
    }

    function syncKindUI() {
        const kind = normalizeKind(currentFilters.kind);
        const hasCatalogKind = isCatalogKind(kind);

        if (modeAllLabel) {
            modeAllLabel.classList.toggle('kind-hidden', !!kind);
        }
        if (categoryStripWrap) {
            categoryStripWrap.classList.toggle('kind-hidden', !hasCatalogKind);
        }
        if (sidebarCategoriesWrap) {
            sidebarCategoriesWrap.classList.toggle('kind-hidden', !hasCatalogKind);
        }

        if (categoryStripTitleText) {
            categoryStripTitleText.textContent =
                kind === 'physical' ? 'Catégories produits' :
                kind === 'service' ? 'Catégories services' :
                'Catégories';
        }

        document.querySelectorAll('.sd-mode-btn[data-kind]').forEach(btn => {
            const val = normalizeKind(btn.getAttribute('data-kind'));
            const isActive = !!kind && val === kind;
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

        if (!hasCatalogKind) {
            catChips.forEach(el => el.classList.remove('kind-hidden'));
            catLinks.forEach(el => el.classList.remove('kind-hidden'));
            syncTotalsUI();
            syncEmptyStateCopy();
            syncContentPanels();
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
        syncContentPanels();
    }

    function resetLoadingState() {
        if (productsFetchController) {
            productsFetchController.abort();
        }
        productsFetchController = null;
        isLoading = false;
        hasMore = true;
        currentLoadingMode = '';
    }

    function lockGridHeight() {
        if (!productsGrid) return;
        const height = Math.max(0, Math.round(productsGrid.getBoundingClientRect().height || 0));
        if (height > 0) {
            productsGrid.style.minHeight = `${height}px`;
        }
    }

    function unlockGridHeight() {
        if (!productsGrid) return;
        if (gridUnlockTimer) {
            window.clearTimeout(gridUnlockTimer);
        }
        gridUnlockTimer = window.setTimeout(() => {
            productsGrid.style.removeProperty('min-height');
            gridUnlockTimer = null;
        }, 180);
    }

    function setResultsLoading(active, mode) {
        const nextMode = active ? (mode || 'refresh') : '';
        currentLoadingMode = nextMode;

        if (productsGrid) {
            if (active && nextMode === 'refresh') {
                lockGridHeight();
            }
            productsGrid.classList.toggle('is-refreshing', !!active && nextMode === 'refresh');
            productsGrid.classList.toggle('is-appending', !!active && nextMode === 'append');
            productsGrid.setAttribute('aria-busy', active ? 'true' : 'false');
            if (!active) {
                productsGrid.classList.add('is-fresh');
                window.setTimeout(() => {
                    productsGrid.classList.remove('is-fresh');
                }, 240);
                unlockGridHeight();
            }
        }

        if (loadingSpinner) {
            loadingSpinner.classList.toggle('d-none', !active);
            loadingSpinner.classList.toggle('is-overlay', !!active && nextMode === 'refresh');
            loadingSpinner.classList.toggle('is-inline', !!active && nextMode === 'append');
            loadingSpinner.setAttribute('aria-hidden', active ? 'false' : 'true');
        }
    }

    function syncLoadMoreUI() {
        if (fallbackPagination) {
            fallbackPagination.classList.add('d-none');
        }
        if (!loadMoreWrap || !loadMoreButton) {
            return;
        }
        const shouldShow = normalizeKind(currentFilters.kind) !== 'location' && hasMore && lastTotal > 0 && currentLoadingMode !== 'refresh';
        loadMoreWrap.classList.toggle('d-none', !shouldShow);
        loadMoreButton.disabled = !!isLoading;
        loadMoreButton.setAttribute('aria-busy', isLoading ? 'true' : 'false');
        loadMoreButton.textContent = isLoading ? 'Chargement...' : 'Voir plus';
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

    function applyFilters(nextFilters, options) {
        const opts = options || {};
        const previousFilters = Object.assign({}, currentFilters);
        currentFilters = Object.assign({}, currentFilters, nextFilters || {});
        currentFilters.q = String(currentFilters.q || '').trim();
        currentFilters.cat = String(currentFilters.cat || '').trim();
        currentFilters.sort = String(currentFilters.sort || '').trim();
        currentFilters.kind = normalizeKind(currentFilters.kind);

        if (kindInput) kindInput.value = currentFilters.kind;
        if (catInput) catInput.value = currentFilters.cat;
        syncKindUI();
        syncStateUrl();

        if (!opts.force && filtersEqual(previousFilters, currentFilters)) {
            return;
        }

        resetLoadingState();
        currentPage = 1;
        if (noResults) noResults.classList.add('d-none');
        syncContentPanels();
        syncLoadMoreUI();
        if (normalizeKind(currentFilters.kind) === 'location') {
            return;
        }
        loadProducts({ replace: true });
    }

    function updateFiltersFromInputs() {
        applyFilters({
            q: searchInput ? searchInput.value.trim() : '',
            sort: sortSelect ? sortSelect.value : ''
        });
    }

    function setKind(nextKind) {
        const desired = normalizeKind(nextKind);
        const current = normalizeKind(currentFilters.kind);
        const allowResetToAll = document.querySelectorAll('.sd-mode-btn[data-kind]').length > 1;
        applyFilters({
            kind: (allowResetToAll && current === desired) ? '' : desired,
            cat: ''
        });
    }

    function setCategory(value) {
        applyFilters({
            cat: (value || '').toString().trim()
        });
    }

    function loadProducts(options) {
        const opts = options || {};
        const replace = !!opts.replace;
        if (!productsGrid || normalizeKind(currentFilters.kind) === 'location') return;
        if (isLoading || (!replace && !hasMore)) return;

        isLoading = true;
        setResultsLoading(true, replace ? 'refresh' : 'append');
        syncLoadMoreUI();

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

                if (replace) {
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
                syncLoadMoreUI();
            })
            .catch(error => {
                if (!productsRequestSeq.isLatest(requestId)) return;
                if (error && error.name === 'AbortError') return;
                console.error('Error loading products:', error);
            })
            .finally(() => {
                if (!productsRequestSeq.isLatest(requestId)) return;
                isLoading = false;
                setResultsLoading(false);
                syncLoadMoreUI();
            });
    }

    function handleScroll() {
        if (normalizeKind(currentFilters.kind) === 'location') return;
        const scrollPosition = window.innerHeight + window.scrollY;
        const scrollOffset = Number(pageConfig.infiniteScrollOffset || 140);
        const pageHeight = document.documentElement.scrollHeight - (Number.isFinite(scrollOffset) ? scrollOffset : 140);
        if (scrollPosition >= pageHeight && hasMore && !isLoading) {
            loadProducts({ replace: false });
        }
    }

    // Listeners
    if (filterForm) {
        filterForm.addEventListener('submit', function(e) {
            e.preventDefault();
            updateFiltersFromInputs();
        });
    }

    if (searchInput) {
        searchInput.addEventListener('input', debounce(updateFiltersFromInputs, liveSearchDelay));
        searchInput.addEventListener('search', updateFiltersFromInputs);
    }
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
            applyFilters({
                q: '',
                sort: '',
                cat: '',
                kind: ''
            });
        });
    }

    if (clearSearch) {
        clearSearch.addEventListener('click', function() {
            if (searchInput) searchInput.value = '';
            applyFilters({ q: '' });
        });
    }

    if (loadMoreButton) {
        loadMoreButton.addEventListener('click', function() {
            loadProducts({ replace: false });
        });
    }

    backLinks.forEach(link => {
        link.addEventListener('click', handleBackNavigation);
    });

    if (productsGrid && productsGrid.children.length === 0) {
        if (noResults) noResults.classList.remove('d-none');
    }

    window.addEventListener('scroll', debounce(handleScroll, 100), { passive: true });

    initScrollTopButton();
    syncKindUI();
    syncContentPanels();
    syncLoadMoreUI();
    initShopLocationCarousels();
    initShopLocationVideos();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initShopDetailPage, { once: true });
} else {
    initShopDetailPage();
}
})();

