(function() {
    'use strict';

    if (window.__BM_VENDOR_DASHBOARD_PAGE_INIT__ === true) return;
    window.__BM_VENDOR_DASHBOARD_PAGE_INIT__ = true;

    const cfgNode = document.getElementById('vendorDashboardConfig');
    const cfg = {
        dashboardUrl: (cfgNode && cfgNode.dataset.dashboardUrl) || '/vendor/dashboard',
        searchUrl: (cfgNode && cfgNode.dataset.searchUrl) || '/vendor/products/search',
        statsUrl: (cfgNode && cfgNode.dataset.statsUrl) || '/vendor/stats/live',
        ordersLiveUrl: (cfgNode && cfgNode.dataset.ordersLiveUrl) || '/vendor/dashboard/orders-live',
        pushConfigUrl: (cfgNode && cfgNode.dataset.pushConfigUrl) || '',
        pushStatusUrl: (cfgNode && cfgNode.dataset.pushStatusUrl) || '',
        pushSubscribeUrl: (cfgNode && cfgNode.dataset.pushSubscribeUrl) || '',
        pushUnsubscribeUrl: (cfgNode && cfgNode.dataset.pushUnsubscribeUrl) || '',
        ordersPollMs: Math.max(5000, Number((cfgNode && cfgNode.dataset.ordersPollMs) || 20000)),
        ordersPerPage: Math.max(4, Number((cfgNode && cfgNode.dataset.ordersPerPage) || 8)),
        bookingsPerPage: Math.max(4, Number((cfgNode && cfgNode.dataset.bookingsPerPage) || 8)),
        vendorId: String((cfgNode && cfgNode.dataset.vendorId) || '0'),
        searchDelayMs: 280,
        refreshStatsMs: 30000,
        refreshStockMs: 60000
    };
    const VENDOR_ORDER_ALERT_MS = 5000;
    const VENDOR_ORDER_VIBRATE_PATTERN = [700, 180, 700, 180, 700, 180, 700, 180, 700, 180, 700];

    const searchInput = document.getElementById('searchInput');
    const searchClear = document.getElementById('searchClear');
    const productsContainer = document.getElementById('productsContainer');
    const productCount = document.getElementById('productCount');
    const categoriesFilter = document.getElementById('categoriesFilter');
    const categorySearchInput = document.getElementById('categorySearchInput');
    const categoriesMeta = document.getElementById('categoriesMeta');
    const categoriesToggleBtn = document.getElementById('categoriesToggleBtn');
    const loadingOverlay = document.getElementById('loadingOverlay');
    const coreDomApi = window.BMCoreDom || {};
    const escapeHtml = coreDomApi.escapeHtml;
    const dashboardShopStatusBar = document.getElementById('dashboardShopStatusBar');
    const stockToast = document.getElementById('stockToast');
    const stockToastText = document.getElementById('stockToastText');
    const orderToast = document.getElementById('orderToast');
    const orderToastTitle = document.getElementById('orderToastTitle');
    const orderToastText = document.getElementById('orderToastText');
    const soundToggle = document.getElementById('soundToggle');
    const vendorPushStatus = document.getElementById('vendorPushStatus');
    const pendingPill = document.getElementById('pendingPill');
    const pendingCount = document.getElementById('pendingCount');
    const todayPrepareCount = document.getElementById('todayPrepareCount');
    const todayBookingsCount = document.getElementById('todayBookingsCount');
    const todayLocationsCount = document.getElementById('todayLocationsCount');
    const recentOrdersList = document.getElementById('recentOrdersList');
    const recentOrdersPager = document.getElementById('recentOrdersPager');
    const todayPrepareList = document.getElementById('todayPrepareList');
    const todayPreparePager = document.getElementById('todayPreparePager');
    const todayBookingsList = document.getElementById('todayBookingsList');
    const todayBookingsPager = document.getElementById('todayBookingsPager');

    if (!productsContainer && !categoriesFilter) {
        return;
    }

    const VendorUI = window.VendorUI || {};
    const prefetchApi = window.BMIntentPrefetch || null;
    const perfFlags = window.BM_PERF_FLAGS || {};
    const interactionFeedbackEnabled = perfFlags.interactionFeedback !== false;
    const frontFluidityEnabled = perfFlags.frontFluidity !== false;
    cfg.searchDelayMs = frontFluidityEnabled ? Math.min(cfg.searchDelayMs, 240) : cfg.searchDelayMs;
    let pendingFeedbackSeq = 0;
    if (typeof VendorUI.initOnce === 'function') {
        VendorUI.initOnce();
    }

    const setLoadingState = (typeof VendorUI.setLoadingState === 'function')
        ? VendorUI.setLoadingState
        : function(node, active) {
            if (!node || !node.classList) return;
            node.classList.toggle('active', !!active);
        };

    const bindConfirmForms = (typeof VendorUI.bindConfirmForms === 'function')
        ? VendorUI.bindConfirmForms
        : function(root) {
            const scope = root && root.querySelectorAll ? root : document;
            scope.querySelectorAll('form[data-confirm]').forEach(function(form) {
                if (form.dataset.bound === '1') return;
                form.dataset.bound = '1';
                form.addEventListener('submit', function(e) {
                    if (!window.confirm(form.dataset.confirm || 'Confirmer ?')) {
                        e.preventDefault();
                    }
                });
            });
        };
    const fallbackRequestJSON = (typeof coreDomApi.requestJSON === 'function')
        ? coreDomApi.requestJSON
        : window.BMAjaxFetch.requestJSON.bind(window.BMAjaxFetch);
    const fallbackRequestText = (typeof coreDomApi.requestText === 'function')
        ? coreDomApi.requestText
        : window.BMAjaxFetch.requestText.bind(window.BMAjaxFetch);
    const requestJSON = (typeof VendorUI.requestJSON === 'function')
        ? VendorUI.requestJSON
        : fallbackRequestJSON;

    const requestText = (typeof VendorUI.requestText === 'function')
        ? VendorUI.requestText
        : fallbackRequestText;

    const createRequestSeq = (typeof VendorUI.createRequestSeq === 'function')
        ? VendorUI.createRequestSeq
        : function() {
            // KEEP_FALLBACK: protects request ordering if VendorUI loads late.
            if (window.BMAjaxGuard && typeof window.BMAjaxGuard.makeRequestSeq === 'function') {
                return window.BMAjaxGuard.makeRequestSeq();
            }
            let latestId = 0;
            return {
                next: function() {
                    latestId += 1;
                    return latestId;
                },
                isLatest: function(id) {
                    return Number(id) === latestId;
                }
            };
        };

    function buildAjaxHeaders(extraHeaders) {
        return Object.assign(
            { 'X-Requested-With': 'XMLHttpRequest' },
            extraHeaders || {}
        );
    }

    let searchTimeout = null;
    let currentCategory = 'all';
    const searchRequestSeq = createRequestSeq();
    let searchAbortController = null;
    const ordersRequestSeq = createRequestSeq();
    let ordersAbortController = null;
    const categoriesRequestSeq = createRequestSeq();
    let categoriesAbortController = null;
    const statsRequestSeq = createRequestSeq();
    let statsAbortController = null;
    let soundEnabled = true;
    try {
        soundEnabled = localStorage.getItem('vendorDashboardSound') !== '0';
    } catch (_error) {}
    const ordersState = {
        recentPage: Math.max(1, Number((recentOrdersPager && recentOrdersPager.dataset.page) || 1)),
        recentPages: Math.max(1, Number((recentOrdersPager && recentOrdersPager.dataset.pages) || 1)),
        preparePage: Math.max(1, Number((todayPreparePager && todayPreparePager.dataset.page) || 1)),
        preparePages: Math.max(1, Number((todayPreparePager && todayPreparePager.dataset.pages) || 1)),
        bookingsPage: Math.max(1, Number((todayBookingsPager && todayBookingsPager.dataset.page) || 1)),
        bookingsPages: Math.max(1, Number((todayBookingsPager && todayBookingsPager.dataset.pages) || 1)),
        isInitialized: false,
        isLoading: false,
        lastNotifiedId: 0,
        lastBookingNotifiedId: 0,
    };
    const dashboardStatCards = Array.prototype.slice.call(document.querySelectorAll('.stats-grid .stat-card'));
    const shopStatusOptimistic = {
        active: false,
        snapshot: null,
        rollbackTimer: null
    };
    const notifyStorageKey = 'vendorDashboardLastOrderId:' + cfg.vendorId;
    const bookingNotifyStorageKey = 'vendorDashboardLastBookingId:' + cfg.vendorId;
    try {
        ordersState.lastNotifiedId = Number(localStorage.getItem(notifyStorageKey) || 0);
    } catch (_error) {}
    try {
        ordersState.lastBookingNotifiedId = Number(localStorage.getItem(bookingNotifyStorageKey) || 0);
    } catch (_error) {}
    let lastLowStockProducts = new Set();
    let categoriesSignature = '';
    let lastSearchHtml = productsContainer ? String(productsContainer.innerHTML || '') : '';
    let lastStatsSignature = '';
    let audioCtx = null;
    let audioArmed = false;
    let categoriesExpanded = false;
    let stockToastTimer = null;
    let orderToastTimer = null;
    const IMAGE_LIGHTBOX_ID = 'vendor-dashboard-image-lightbox';
    const IMAGE_LIGHTBOX_CLOSE_ID = 'vendor-dashboard-image-lightbox-close';
    const IMAGE_LIGHTBOX_CAPTION_ID = 'vendor-dashboard-image-lightbox-caption';

    function batchUiCommit(fn) {
        if (typeof fn !== 'function') {
            return Promise.resolve();
        }
        if (!frontFluidityEnabled || typeof window.requestAnimationFrame !== 'function') {
            fn();
            return Promise.resolve();
        }
        return new Promise(function(resolve) {
            window.requestAnimationFrame(function() {
                fn();
                resolve();
            });
        });
    }

    function bindProductImageFallback(root) {
        const scope = (root && root.querySelectorAll) ? root : document;
        scope.querySelectorAll('.product-card img[data-placeholder]').forEach(function(img) {
            if (img.dataset.fallbackBound === '1') return;
            img.dataset.fallbackBound = '1';
            img.addEventListener('error', function() {
                const fallback = this.dataset.placeholder || '';
                if (!fallback || this.src === fallback) return;
                this.src = fallback;
            });
        });
    }

    function closeImageLightbox() {
        const modal = document.getElementById(IMAGE_LIGHTBOX_ID);
        const closeBtn = document.getElementById(IMAGE_LIGHTBOX_CLOSE_ID);
        const caption = document.getElementById(IMAGE_LIGHTBOX_CAPTION_ID);
        if (modal) modal.remove();
        if (closeBtn) closeBtn.remove();
        if (caption) caption.remove();
        if (document.body && document.body.dataset.dashboardLightboxOverflow !== undefined) {
            document.body.style.overflow = document.body.dataset.dashboardLightboxOverflow || '';
            delete document.body.dataset.dashboardLightboxOverflow;
        }
        document.removeEventListener('keydown', onLightboxKeydown);
    }

    function onLightboxKeydown(event) {
        if (event.key === 'Escape') {
            closeImageLightbox();
        }
    }

    function openImageLightbox(src, title) {
        const imageSrc = String(src || '').trim();
        if (!imageSrc) return;
        closeImageLightbox();

        const modal = document.createElement('div');
        modal.id = IMAGE_LIGHTBOX_ID;
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(2,6,23,.9);display:flex;align-items:center;justify-content:center;padding:16px;z-index:9999;cursor:zoom-out;';

        const img = document.createElement('img');
        img.src = imageSrc;
        img.alt = String(title || 'Photo produit');
        img.style.cssText = 'max-width:min(96vw,1200px);max-height:92vh;object-fit:contain;border-radius:14px;box-shadow:0 30px 70px rgba(0,0,0,.45);';

        const closeBtn = document.createElement('button');
        closeBtn.id = IMAGE_LIGHTBOX_CLOSE_ID;
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', "Fermer l'aperçu");
        closeBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
        closeBtn.style.cssText = 'position:fixed;top:16px;right:16px;width:42px;height:42px;border-radius:999px;border:1px solid rgba(255,255,255,.25);background:rgba(15,23,42,.66);color:#fff;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;z-index:10000;';

        const caption = document.createElement('div');
        caption.id = IMAGE_LIGHTBOX_CAPTION_ID;
        caption.textContent = String(title || '');
        caption.style.cssText = 'position:fixed;left:50%;bottom:16px;transform:translateX(-50%);padding:8px 12px;border-radius:999px;background:rgba(15,23,42,.66);border:1px solid rgba(255,255,255,.2);color:#fff;font-weight:600;font-size:.85rem;max-width:90vw;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
        if (!caption.textContent) {
            caption.style.display = 'none';
        }

        modal.addEventListener('click', function(event) {
            if (event.target === modal) closeImageLightbox();
        });
        closeBtn.addEventListener('click', closeImageLightbox);
        document.addEventListener('keydown', onLightboxKeydown);

        modal.appendChild(img);
        document.body.appendChild(modal);
        document.body.appendChild(closeBtn);
        document.body.appendChild(caption);
        if (document.body) {
            document.body.dataset.dashboardLightboxOverflow = document.body.style.overflow || '';
            document.body.style.overflow = 'hidden';
        }
    }

    function bindProductImagePreview() {
        if (!productsContainer || productsContainer.dataset.previewBound === '1') return;
        productsContainer.dataset.previewBound = '1';

        productsContainer.addEventListener('click', function(event) {
            const img = event.target.closest('.dashboard-product-image-clickable[data-large]');
            if (!img || !productsContainer.contains(img)) return;
            openImageLightbox(img.getAttribute('data-large'), img.getAttribute('data-title') || img.getAttribute('alt') || 'Photo produit');
        });

        productsContainer.addEventListener('keydown', function(event) {
            const img = event.target.closest('.dashboard-product-image-clickable[data-large]');
            if (!img || !productsContainer.contains(img)) return;
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            openImageLightbox(img.getAttribute('data-large'), img.getAttribute('data-title') || img.getAttribute('alt') || 'Photo produit');
        });
    }

    function setElementPending(node) {
        if (!interactionFeedbackEnabled || !node || typeof node.setAttribute !== 'function') {
            return function() {};
        }
        pendingFeedbackSeq += 1;
        const token = String(pendingFeedbackSeq);
        node.setAttribute('data-bm-pending', '1');
        node.setAttribute('data-bm-pending-token', token);
        return function() {
            if (node.getAttribute('data-bm-pending-token') !== token) return;
            node.removeAttribute('data-bm-pending');
            node.removeAttribute('data-bm-pending-token');
        };
    }

    function setLoading(active) {
        setLoadingState(loadingOverlay, !!active);
    }

    function setStatsLoading(active) {
        dashboardStatCards.forEach(function(card) {
            if (!card || !card.classList) return;
            card.classList.toggle('is-loading', !!active);
        });
    }

    function setOrdersLoading(active) {
        [recentOrdersList, todayPrepareList, todayBookingsList].forEach(function(list) {
            if (!list || !list.classList) return;
            list.classList.toggle('is-loading', !!active);
        });
    }

    function setupDashboardPrefetch() {
        if (!prefetchApi) return;

        if (typeof prefetchApi.prefetchOnIntent === 'function') {
            prefetchApi.prefetchOnIntent(
                document,
                '.action-buttons a[data-prefetch-critical]',
                { headers: { Accept: 'text/html' } }
            );
        }

        const pageUrls = Array.prototype.slice
            .call(document.querySelectorAll('.action-buttons a[data-prefetch-critical][href]'))
            .map(function(node) { return node.getAttribute('href'); });
        const endpointUrls = [cfg.statsUrl, cfg.ordersLiveUrl].filter(function(url) {
            return !!String(url || '').trim();
        });

        if (typeof prefetchApi.prefetchIdle === 'function') {
            if (pageUrls.length) {
                prefetchApi.prefetchIdle(pageUrls, {
                    headers: { Accept: 'text/html' },
                    timeoutMs: 1300
                });
            }
            if (endpointUrls.length) {
                prefetchApi.prefetchIdle(endpointUrls, {
                    headers: { Accept: 'application/json' },
                    timeoutMs: 1200
                });
            }
        }
    }

    function captureShopStatusSnapshot(form) {
        if (!dashboardShopStatusBar || !form) return null;
        const pill = dashboardShopStatusBar.querySelector('.status-pill');
        const button = form.querySelector('.status-btn');
        const stateInput = form.querySelector('input[name="state"]');
        return {
            pill: pill,
            button: button,
            stateInput: stateInput,
            barClassName: dashboardShopStatusBar.className,
            pillClassName: pill ? pill.className : '',
            pillHtml: pill ? pill.innerHTML : '',
            buttonClassName: button ? button.className : '',
            buttonText: button ? button.textContent : '',
            nextState: stateInput ? stateInput.value : ''
        };
    }

    function restoreShopStatusSnapshot() {
        const snapshot = shopStatusOptimistic.snapshot;
        if (!snapshot) return;
        if (dashboardShopStatusBar && dashboardShopStatusBar.isConnected) {
            dashboardShopStatusBar.className = snapshot.barClassName || 'shop-status-bar';
        }
        if (snapshot.pill && snapshot.pill.isConnected) {
            snapshot.pill.className = snapshot.pillClassName || 'status-pill';
            snapshot.pill.innerHTML = snapshot.pillHtml || '';
        }
        if (snapshot.button && snapshot.button.isConnected) {
            snapshot.button.className = snapshot.buttonClassName || 'status-btn';
            snapshot.button.textContent = snapshot.buttonText || '';
            snapshot.button.disabled = false;
        }
        if (snapshot.stateInput && snapshot.stateInput.isConnected) {
            snapshot.stateInput.value = snapshot.nextState || snapshot.stateInput.value;
        }
    }

    function clearShopStatusOptimistic(restoreSnapshot) {
        if (shopStatusOptimistic.rollbackTimer) {
            window.clearTimeout(shopStatusOptimistic.rollbackTimer);
            shopStatusOptimistic.rollbackTimer = null;
        }
        if (restoreSnapshot) {
            restoreShopStatusSnapshot();
        }
        if (dashboardShopStatusBar && dashboardShopStatusBar.classList) {
            dashboardShopStatusBar.classList.remove('is-optimistic');
        }
        shopStatusOptimistic.snapshot = null;
        shopStatusOptimistic.active = false;
    }

    function applyShopStatusOptimistic(form) {
        if (!dashboardShopStatusBar || !form) return;
        const stateInput = form.querySelector('input[name="state"]');
        const button = form.querySelector('.status-btn');
        const pill = dashboardShopStatusBar.querySelector('.status-pill');
        if (!stateInput || !button || !pill) return;

        const targetState = String(stateInput.value || '').toLowerCase();
        const willOpen = targetState === 'open';
        const nextState = willOpen ? 'closed' : 'open';

        pill.className = 'status-pill ' + (willOpen ? 'open' : 'closed');
        pill.innerHTML = willOpen
            ? '<i class="bi bi-door-open"></i> OUVERT'
            : '<i class="bi bi-door-closed"></i> FERME';

        button.className = 'status-btn ' + (willOpen ? 'closed' : 'open');
        button.textContent = willOpen ? 'Passer en mode ferme' : 'Reouvrir la boutique';
        button.disabled = true;
        stateInput.value = nextState;

        dashboardShopStatusBar.classList.add('is-optimistic');
    }

    function bindShopStatusOptimistic() {
        if (!dashboardShopStatusBar || dashboardShopStatusBar.dataset.optimisticBound === '1') return;
        dashboardShopStatusBar.dataset.optimisticBound = '1';

        document.addEventListener('submit', function(event) {
            const form = event.target && event.target.closest
                ? event.target.closest('form[data-action="set-shop-open"]')
                : null;
            if (!form || !dashboardShopStatusBar.contains(form)) return;
            if (shopStatusOptimistic.active) return;

            shopStatusOptimistic.snapshot = captureShopStatusSnapshot(form);
            if (!shopStatusOptimistic.snapshot) return;
            shopStatusOptimistic.active = true;
            applyShopStatusOptimistic(form);

            shopStatusOptimistic.rollbackTimer = window.setTimeout(function() {
                clearShopStatusOptimistic(true);
            }, 12000);
        }, true);

        document.addEventListener('bm:ajax-form-success', function(event) {
            const detail = event && event.detail ? event.detail : null;
            const form = detail && detail.form ? detail.form : null;
            if (!form || String(form.dataset.action || '') !== 'set-shop-open') return;
            clearShopStatusOptimistic(false);
        });

        document.addEventListener('ajax:page-replaced', function(event) {
            const detail = event && event.detail ? event.detail : null;
            if (!detail) return;
            if (detail.selector === '#dashboardShopStatusBar') {
                clearShopStatusOptimistic(false);
            }
        });
    }

    function armAudioOnce() {
        if (audioArmed) {
            hideSoundActivationPrompt();
            return;
        }
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            audioCtx = new AudioCtx();
            if (audioCtx.state === 'suspended') {
                audioCtx.resume().catch(function() {});
            }
            audioArmed = true;
            hideSoundActivationPrompt();
        } catch (e) {
            audioArmed = false;
        }
    }

    window.addEventListener('pointerdown', armAudioOnce, { once: true, passive: true });
    window.addEventListener('touchstart', armAudioOnce, { once: true, passive: true });
    window.addEventListener('keydown', armAudioOnce, { once: true });

    function updateSoundToggle() {
        if (!soundToggle) return;
        soundToggle.innerHTML = soundEnabled
            ? '<i class="bi bi-volume-up"></i>'
            : '<i class="bi bi-volume-mute"></i>';
        soundToggle.classList.toggle('muted', !soundEnabled);
        soundToggle.title = soundEnabled ? 'Desactiver le son' : 'Activer le son';
    }

    function hideSoundActivationPrompt() {
        const prompt = document.getElementById('vendorSoundActivationPrompt');
        if (prompt) prompt.remove();
    }

    function showSoundActivationPrompt() {
        if (!soundToggle || audioArmed || document.getElementById('vendorSoundActivationPrompt')) return;
        const prompt = document.createElement('div');
        prompt.className = 'vendor-sound-prompt';
        prompt.id = 'vendorSoundActivationPrompt';
        prompt.setAttribute('role', 'status');
        prompt.innerHTML =
            '<div class="vendor-sound-prompt-icon"><i class="bi bi-volume-up"></i></div>' +
            '<div class="vendor-sound-prompt-copy">' +
            '<strong>Réactiver le son</strong>' +
            '<span>Touchez ici pour armer les alertes du tableau vendeur.</span>' +
            '</div>' +
            '<button type="button" class="vendor-sound-prompt-btn">Activer</button>';
        prompt.addEventListener('click', function() {
            soundEnabled = true;
            try {
                localStorage.setItem('vendorDashboardSound', '1');
            } catch (_error) {}
            updateSoundToggle();
            armAudioOnce();
            playPushTestAlert();
            if (navigator.vibrate) {
                navigator.vibrate([120, 80, 120]);
            }
        });
        document.body.appendChild(prompt);
    }

    function playStockAlert() {
        if (!soundEnabled || !audioArmed || !audioCtx) return;
        try {
            const now = audioCtx.currentTime;
            const osc = audioCtx.createOscillator();
            const gain = audioCtx.createGain();
            osc.type = 'sine';
            osc.frequency.value = 880;
            gain.gain.value = 0.0001;
            osc.connect(gain);
            gain.connect(audioCtx.destination);
            osc.start(now);
            gain.gain.exponentialRampToValueAtTime(0.16, now + 0.05);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.24);
            osc.stop(now + 0.26);
        } catch (e) {}
    }

    function showStockToast(message) {
        if (!stockToast || !stockToastText) return;
        if (stockToastTimer) {
            window.clearTimeout(stockToastTimer);
            stockToastTimer = null;
        }
        stockToastText.textContent = message;
        stockToast.classList.add('show');
        playStockAlert();
        stockToastTimer = window.setTimeout(function() {
            stockToast.classList.remove('show');
            stockToastTimer = null;
        }, 3800);
    }

    function playOrderAlert() {
        if (!soundEnabled || !audioArmed || !audioCtx) return;
        try {
            const pattern = [988, 1318, 1174, 1568];
            const endAt = audioCtx.currentTime + (VENDOR_ORDER_ALERT_MS / 1000);
            let startAt = audioCtx.currentTime;
            while (startAt < endAt) {
                pattern.forEach(function(freq, index) {
                    if (startAt >= endAt) return;
                    const osc = audioCtx.createOscillator();
                    const gain = audioCtx.createGain();
                    const noteStart = startAt + (index * 0.12);
                    const noteStop = Math.min(noteStart + 0.18, endAt);
                    osc.type = 'triangle';
                    osc.frequency.value = freq;
                    gain.gain.value = 0.0001;
                    osc.connect(gain);
                    gain.connect(audioCtx.destination);
                    osc.start(noteStart);
                    gain.gain.exponentialRampToValueAtTime(0.2, noteStart + 0.03);
                    gain.gain.exponentialRampToValueAtTime(0.0001, Math.max(noteStart + 0.08, noteStop - 0.02));
                    osc.stop(noteStop);
                });
                startAt += 0.72;
            }
        } catch (_error) {}
    }

    function vibrateOrderAlert() {
        if (!navigator.vibrate) return;
        try {
            navigator.vibrate(VENDOR_ORDER_VIBRATE_PATTERN);
        } catch (_error) {}
    }

    function playPushTestAlert() {
        if (!soundEnabled || !audioArmed || !audioCtx) return;
        try {
            const now = audioCtx.currentTime;
            [880, 1174, 1568].forEach(function(freq, index) {
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                const startAt = now + (index * 0.12);
                osc.type = 'triangle';
                osc.frequency.value = freq;
                gain.gain.value = 0.0001;
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.start(startAt);
                gain.gain.exponentialRampToValueAtTime(0.16, startAt + 0.03);
                gain.gain.exponentialRampToValueAtTime(0.0001, startAt + 0.22);
                osc.stop(startAt + 0.24);
            });
        } catch (_error) {}
    }

    function showOrderToast(message, title) {
        if (!orderToast || !orderToastText) return;
        if (orderToastTimer) {
            window.clearTimeout(orderToastTimer);
            orderToastTimer = null;
        }
        if (orderToastTitle) {
            orderToastTitle.textContent = title || 'Nouvelle commande';
        }
        orderToastText.textContent = message || 'Une nouvelle commande est arrivee.';
        orderToast.classList.add('show');
        playOrderAlert();
        vibrateOrderAlert();
        showSystemVendorNotification(title || 'Nouvelle commande', message || 'Une nouvelle commande est arrivee.');
        orderToastTimer = window.setTimeout(function() {
            orderToast.classList.remove('show');
            orderToastTimer = null;
        }, VENDOR_ORDER_ALERT_MS);
    }

    function showSystemVendorNotification(title, body) {
        if (!('Notification' in window) || Notification.permission !== 'granted') return;
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.ready.then(function(registration) {
                if (!registration || !registration.showNotification) return;
                registration.showNotification(String(title || 'Baba Market'), {
                    body: String(body || 'Nouvelle activité vendeur.'),
                    icon: '/static/android-chrome-192x192.png',
                    badge: '/static/favicon-32x32.png',
                    tag: 'vendor-dashboard-local',
                    renotify: true,
                    data: { url: cfg.dashboardUrl || '/vendor/dashboard' }
                });
            }).catch(function() {});
        }
    }

    function setVendorPushStatus(label, state) {
        if (!vendorPushStatus) return;
        const text = String(label || 'Alertes téléphone');
        vendorPushStatus.classList.toggle('is-active', state === 'active');
        vendorPushStatus.classList.toggle('is-muted', state === 'muted');
        vendorPushStatus.classList.toggle('is-error', state === 'error');
        vendorPushStatus.innerHTML =
            '<i class="bi bi-phone-vibrate"></i><span>' + text.replace(/[<>&]/g, '') + '</span>';
    }

    function isIosDevice() {
        return /iphone|ipad|ipod/i.test(window.navigator.userAgent || '') ||
            (window.navigator.platform === 'MacIntel' && window.navigator.maxTouchPoints > 1);
    }

    function isStandaloneApp() {
        return Boolean(
            (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
            window.navigator.standalone === true
        );
    }

    function setVendorPushDiagnostic(config) {
        if (!config || !vendorPushStatus) return;
        if (isIosDevice() && !isStandaloneApp()) {
            setVendorPushStatus("Installer l'app", 'error');
            return;
        }
        if (config.configured === false) {
            setVendorPushStatus('Serveur à configurer', 'error');
            return;
        }
        if (Number(config.activeSubscriptions || 0) <= 0 && Notification.permission === 'granted') {
            setVendorPushStatus('Réactiver alertes', 'error');
        }
    }

    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; i += 1) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    function isValidVapidPublicKey(publicKey) {
        try {
            const decoded = urlBase64ToUint8Array(String(publicKey || '').trim());
            return decoded.length === 65 && decoded[0] === 4;
        } catch (_error) {
            return false;
        }
    }

    function jsonHeaders() {
        const headers = { 'Accept': 'application/json', 'Content-Type': 'application/json' };
        if (window.BMAjaxCSRF && typeof window.BMAjaxCSRF.addToHeaders === 'function') {
            return window.BMAjaxCSRF.addToHeaders(headers);
        }
        return headers;
    }

    function postPushSubscription(url, payload) {
        return window.fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: jsonHeaders(),
            body: JSON.stringify(payload || {})
        }).then(function(response) {
            return response.json().catch(function() { return {}; }).then(function(data) {
                if (!response.ok || data.success === false) {
                    throw new Error(data.message || 'push_request_failed');
                }
                return data;
            });
        });
    }

    function initVendorPushNotifications() {
        if (!vendorPushStatus || !cfg.pushConfigUrl || !cfg.pushSubscribeUrl) return;
        if (!('Notification' in window) || !('serviceWorker' in navigator) || !('PushManager' in window)) {
            setVendorPushStatus(isIosDevice() ? "Installer l'app" : 'Non supporté', 'muted');
            return;
        }
        if (isIosDevice() && !isStandaloneApp()) {
            setVendorPushStatus("Installer l'app", 'error');
        }

        function subscribe() {
            setVendorPushStatus('Activation...', 'muted');
            return fetch(cfg.pushConfigUrl, {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' }
            })
                .then(function(response) { return response.json(); })
                .then(function(config) {
                    if (!config || !config.publicKey) {
                        setVendorPushStatus('Serveur à configurer', 'error');
                        return null;
                    }
                    if (config.validPublicKey === false || !isValidVapidPublicKey(config.publicKey)) {
                        setVendorPushStatus('Clé push invalide', 'error');
                        return null;
                    }
                    return Notification.requestPermission().then(function(permission) {
                        if (permission !== 'granted') {
                            setVendorPushStatus('Alertes bloquées', 'error');
                            return null;
                        }
                        return navigator.serviceWorker.ready.then(function(registration) {
                            return registration.pushManager.getSubscription().then(function(existing) {
                                if (existing) return existing;
                                return registration.pushManager.subscribe({
                                    userVisibleOnly: true,
                                    applicationServerKey: urlBase64ToUint8Array(config.publicKey)
                                });
                            });
                        });
                    });
                })
                .then(function(subscription) {
                    if (!subscription) return null;
                    showSystemVendorNotification('Test alerte vendeur', 'Test local: les notifications du navigateur sont autorisées.');
                    return postPushSubscription(cfg.pushSubscribeUrl, {
                        subscription: subscription.toJSON ? subscription.toJSON() : subscription,
                        send_test: true
                    });
                })
                .then(function(result) {
                    if (!result) return;
                    if (result.configured === false) {
                        setVendorPushStatus('Serveur à configurer', 'error');
                        return;
                    }
                    if (Number(result.test_sent || 0) <= 0) {
                        setVendorPushStatus('Aucune alerte envoyée', 'error');
                        return;
                    }
                    playPushTestAlert();
                    if (navigator.vibrate) {
                        navigator.vibrate([250, 120, 250]);
                    }
                    setVendorPushStatus('Alertes actives', 'active');
                })
                .catch(function(error) {
                    console.warn('[vendor-push] subscribe failed', error);
                    setVendorPushStatus('Alertes à vérifier', 'error');
                });
        }

        navigator.serviceWorker.ready
            .then(function(registration) {
                return registration.pushManager.getSubscription();
            })
            .then(function(subscription) {
                if (Notification.permission === 'granted' && subscription) {
                    setVendorPushStatus('Alertes actives', 'active');
                    postPushSubscription(cfg.pushSubscribeUrl, {
                        subscription: subscription.toJSON ? subscription.toJSON() : subscription
                    }).catch(function() {});
                } else if (Notification.permission === 'denied') {
                    setVendorPushStatus('Alertes bloquées', 'error');
                } else {
                    setVendorPushStatus('Activer alertes', 'muted');
                }
            })
            .then(function() {
                if (!cfg.pushStatusUrl) return null;
                return fetch(cfg.pushStatusUrl, {
                    credentials: 'same-origin',
                    headers: { 'Accept': 'application/json' }
                })
                    .then(function(response) { return response.json(); })
                    .then(setVendorPushDiagnostic)
                    .catch(function() {});
            })
            .catch(function() {
                setVendorPushStatus('Activer alertes', 'muted');
            });

        vendorPushStatus.addEventListener('click', function() {
            subscribe();
        });
    }

    function abortDashboardRequests() {
        if (searchAbortController) {
            searchAbortController.abort();
            searchAbortController = null;
        }
        if (ordersAbortController) {
            ordersAbortController.abort();
            ordersAbortController = null;
        }
        if (categoriesAbortController) {
            categoriesAbortController.abort();
            categoriesAbortController = null;
        }
        if (statsAbortController) {
            statsAbortController.abort();
            statsAbortController = null;
        }
    }

    function clearDashboardTimers() {
        if (searchTimeout) {
            window.clearTimeout(searchTimeout);
            searchTimeout = null;
        }
        if (stockToastTimer) {
            window.clearTimeout(stockToastTimer);
            stockToastTimer = null;
        }
        if (orderToastTimer) {
            window.clearTimeout(orderToastTimer);
            orderToastTimer = null;
        }
        if (shopStatusOptimistic.rollbackTimer) {
            window.clearTimeout(shopStatusOptimistic.rollbackTimer);
            shopStatusOptimistic.rollbackTimer = null;
        }
    }

    function buildItemsSignature(items, keys) {
        if (!Array.isArray(items) || !items.length) {
            return 'empty';
        }
        const fields = Array.isArray(keys) && keys.length ? keys : ['id'];
        return items.map(function(item) {
            return fields.map(function(key) {
                return String(item && item[key] != null ? item[key] : '');
            }).join('~');
        }).join('|');
    }

    function renderOrdersList(target, items, emptyText, signatureKey) {
        if (!target) return;
        const nextSignature = String(signatureKey || '');
        if (frontFluidityEnabled && target.dataset.renderSignature === nextSignature) {
            return;
        }
        if (!Array.isArray(items) || !items.length) {
            target.innerHTML = '<div class="today-empty">' + escapeHtml(emptyText || 'Aucune commande.') + '</div>';
            target.dataset.renderSignature = nextSignature;
            return;
        }
        const rowsHtml = items.map(function(item) {
            const orderId = Number(item && item.order_id ? item.order_id : 0);
            const qty = Number(item && item.items_qty ? item.items_qty : 0);
            const amountMad = Number(item && item.amount_mad ? item.amount_mad : 0).toFixed(2);
            const createdLabel = escapeHtml((item && item.created_label) || '');
            const detailsUrl = escapeHtml((item && item.details_url) || '#');
            return (
                '<div class="today-row">' +
                    '<div>' +
                        '<div class="today-row-top">' +
                            '<div>' +
                                '<div class="today-row-title">Commande #' + orderId + '</div>' +
                                '<div class="today-row-sub">' +
                                    qty + ' article(s)  ' + amountMad + ' MAD' + (createdLabel ? '  ' + createdLabel : '') +
                                '</div>' +
                            '</div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="today-row-actions">' +
                        '<a class="today-outline" href="' + detailsUrl + '">' +
                            '<i class="bi bi-receipt"></i> Details' +
                        '</a>' +
                    '</div>' +
                '</div>'
            );
        }).join('');
        target.innerHTML = rowsHtml;
        target.dataset.renderSignature = nextSignature;
    }

    function renderBookingsList(target, items, emptyText, signatureKey) {
        if (!target) return;
        const nextSignature = String(signatureKey || '');
        if (frontFluidityEnabled && target.dataset.renderSignature === nextSignature) {
            return;
        }
        if (!Array.isArray(items) || !items.length) {
            target.innerHTML = '<div class="today-empty">' + escapeHtml(emptyText || "Aucun rendez-vous planifie aujourd'hui.") + '</div>';
            target.dataset.renderSignature = nextSignature;
            return;
        }
        const rowsHtml = items.map(function(item) {
            const scheduled = escapeHtml((item && item.scheduled_label) || '');
            const productName = escapeHtml((item && item.product_name) || 'Service');
            const fullName = escapeHtml((item && item.full_name) || '');
            const phone = escapeHtml((item && item.phone) || '');
            const callUrl = escapeHtml((item && item.call_url) || '');

            return (
                '<div class="today-row">' +
                    '<div>' +
                        '<div class="today-row-top">' +
                            '<div>' +
                                '<div class="today-row-title">' +
                                    (scheduled ? (scheduled + '  ') : '') + productName +
                                '</div>' +
                                '<div class="today-row-sub">' + fullName + (phone ? ('  ' + phone) : '') + '</div>' +
                            '</div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="today-row-actions">' +
                        (callUrl
                            ? ('<a class="today-outline" href="' + callUrl + '"><i class="bi bi-telephone"></i> Appeler</a>')
                            : '<span class="today-outline" aria-disabled="true"><i class="bi bi-telephone"></i> Appeler</span>') +
                    '</div>' +
                '</div>'
            );
        }).join('');
        target.innerHTML = rowsHtml;
        target.dataset.renderSignature = nextSignature;
    }

    function updatePager(target, payload, signatureKey) {
        if (!target) return;
        const page = Math.max(1, Number(payload && payload.page ? payload.page : 1));
        const pages = Math.max(1, Number(payload && payload.pages ? payload.pages : 1));
        const nextSignature = String(signatureKey || (page + '/' + pages));
        if (frontFluidityEnabled && target.dataset.renderSignature === nextSignature) {
            return;
        }
        target.dataset.page = String(page);
        target.dataset.pages = String(pages);

        const prevBtn = target.querySelector('[data-direction="prev"]');
        const nextBtn = target.querySelector('[data-direction="next"]');
        const status = target.querySelector('.today-pager-status');

        if (status) status.textContent = 'Page ' + page + ' / ' + pages;
        if (prevBtn) prevBtn.disabled = page <= 1;
        if (nextBtn) nextBtn.disabled = page >= pages;
        target.hidden = pages <= 1;
        target.dataset.renderSignature = nextSignature;
    }

    function updateRecentChip(count) {
        const value = Math.max(0, Number(count || 0));
        if (pendingCount) pendingCount.textContent = String(value);
        if (pendingPill && pendingPill.classList) {
            pendingPill.classList.toggle('has-new', value > 0);
        }
    }

    function saveLastNotifiedId(latestId) {
        ordersState.lastNotifiedId = Math.max(0, Number(latestId || 0));
        try {
            localStorage.setItem(notifyStorageKey, String(ordersState.lastNotifiedId));
        } catch (_error) {}
    }

    function saveLastBookingNotifiedId(latestId) {
        ordersState.lastBookingNotifiedId = Math.max(0, Number(latestId || 0));
        try {
            localStorage.setItem(bookingNotifyStorageKey, String(ordersState.lastBookingNotifiedId));
        } catch (_error) {}
    }

    function buildNewOrderMessage(item, totalCount) {
        const count = Math.max(0, Number(totalCount || 0));
        if (!item) {
            return count > 0
                ? (count + ' nouvelle(s) commande(s) dans les 4h.')
                : 'Nouvelle commande.';
        }
        const orderId = Number(item.order_id || 0);
        const qty = Number(item.items_qty || 0);
        const amountMad = Number(item.amount_mad || 0).toFixed(2);
        return 'Commande #' + orderId + ' - ' + qty + ' article(s), ' + amountMad + ' MAD.';
    }

    function buildNewBookingMessage(item, totalCount) {
        const count = Math.max(0, Number(totalCount || 0));
        if (!item) {
            return count > 0
                ? (count + ' nouveau(x) rendez-vous aujourd\'hui.')
                : 'Nouveau rendez-vous.';
        }
        const scheduled = String(item.scheduled_label || '').trim();
        const productName = String(item.product_name || 'Service').trim();
        const clientName = String(item.full_name || '').trim();
        const when = scheduled ? (' a ' + scheduled) : '';
        const withClient = clientName ? (' - ' + clientName) : '';
        return productName + when + withClient;
    }

    function refreshOrdersLive(options) {
        const opts = options || {};
        if (!cfg.ordersLiveUrl) return Promise.resolve();
        if (ordersState.isLoading) return Promise.resolve();
        if (document.hidden && !opts.force) return Promise.resolve();
        const clearTriggerPending = setElementPending(opts.triggerEl);

        ordersState.isLoading = true;
        setOrdersLoading(true);
        const requestId = ordersRequestSeq.next();
        if (ordersAbortController) {
            ordersAbortController.abort();
        }
        ordersAbortController = new AbortController();

        const url = new URL(cfg.ordersLiveUrl, window.location.origin);
        url.searchParams.set('recent_page', String(ordersState.recentPage));
        url.searchParams.set('prepare_page', String(ordersState.preparePage));
        url.searchParams.set('bookings_page', String(ordersState.bookingsPage));
        url.searchParams.set('per_page', String(cfg.ordersPerPage));
        url.searchParams.set('bookings_per_page', String(cfg.bookingsPerPage));
        url.searchParams.set('_', String(Date.now()));

        return requestJSON(url.toString(), {
            headers: buildAjaxHeaders({ 'Accept': 'application/json' }),
            cache: 'no-store',
            credentials: 'same-origin',
            signal: ordersAbortController.signal
        })
            .then(function(result) {
                if (!ordersRequestSeq.isLatest(requestId)) return;
                if (!result || !result.ok || !result.data) return;
                const data = result.data;
                if (!data || !data.success) return;

                const recent = data.recent || {};
                const prepare = data.today_prepare || {};
                const bookings = data.today_bookings || {};
                const locationsCount = Math.max(0, Number(data.today_locations_count || 0));
                const recentItems = recent.items || [];
                const prepareItems = prepare.items || [];
                const bookingItems = bookings.items || [];

                batchUiCommit(function() {
                    updateRecentChip(recent.count || 0);
                    if (todayPrepareCount) {
                        todayPrepareCount.textContent = String(Math.max(0, Number(prepare.count || 0)));
                    }
                    if (todayBookingsCount) {
                        todayBookingsCount.textContent = String(Math.max(0, Number(bookings.count || 0)));
                    }
                    if (todayLocationsCount) {
                        todayLocationsCount.textContent = String(locationsCount);
                    }

                    renderOrdersList(
                        recentOrdersList,
                        recentItems,
                        (recentOrdersList && recentOrdersList.dataset.emptyText) || 'Aucune nouvelle commande sur les 4 dernieres heures.',
                        'recent:' + String(recent.count || 0) + ':' + buildItemsSignature(recentItems, ['order_id', 'items_qty', 'amount_mad', 'created_label', 'details_url'])
                    );
                    renderOrdersList(
                        todayPrepareList,
                        prepareItems,
                        (todayPrepareList && todayPrepareList.dataset.emptyText) || "Aucune commande a preparer aujourd'hui.",
                        'prepare:' + String(prepare.count || 0) + ':' + buildItemsSignature(prepareItems, ['order_id', 'items_qty', 'amount_mad', 'created_label', 'details_url'])
                    );
                    renderBookingsList(
                        todayBookingsList,
                        bookingItems,
                        (todayBookingsList && todayBookingsList.dataset.emptyText) || "Aucun rendez-vous planifie aujourd'hui.",
                        'bookings:' + String(bookings.count || 0) + ':' + buildItemsSignature(bookingItems, ['scheduled_label', 'product_name', 'full_name', 'phone', 'call_url'])
                    );

                    updatePager(recentOrdersPager, recent, 'recent:' + String(recent.page || 1) + '/' + String(recent.pages || 1));
                    updatePager(todayPreparePager, prepare, 'prepare:' + String(prepare.page || 1) + '/' + String(prepare.pages || 1));
                    updatePager(todayBookingsPager, bookings, 'bookings:' + String(bookings.page || 1) + '/' + String(bookings.pages || 1));
                });

                ordersState.recentPage = Math.max(1, Number(recent.page || ordersState.recentPage || 1));
                ordersState.preparePage = Math.max(1, Number(prepare.page || ordersState.preparePage || 1));
                ordersState.recentPages = Math.max(1, Number(recent.pages || 1));
                ordersState.preparePages = Math.max(1, Number(prepare.pages || 1));
                ordersState.bookingsPage = Math.max(1, Number(bookings.page || ordersState.bookingsPage || 1));
                ordersState.bookingsPages = Math.max(1, Number(bookings.pages || 1));

                const latestId = Math.max(0, Number(recent.latest_id || 0));
                const latestBookingId = Math.max(0, Number(bookings.latest_id || 0));
                if (!ordersState.isInitialized) {
                    if (!ordersState.lastNotifiedId) {
                        saveLastNotifiedId(latestId);
                    }
                    if (!ordersState.lastBookingNotifiedId) {
                        saveLastBookingNotifiedId(latestBookingId);
                    }
                    ordersState.isInitialized = true;
                    return;
                }

                if (opts.skipNotify) return;
                if (latestId > ordersState.lastNotifiedId) {
                    saveLastNotifiedId(latestId);
                    showOrderToast(
                        buildNewOrderMessage((recent.items || [])[0], recent.count || 0),
                        'Nouvelle commande'
                    );
                }
                if (latestBookingId > ordersState.lastBookingNotifiedId) {
                    saveLastBookingNotifiedId(latestBookingId);
                    showOrderToast(
                        buildNewBookingMessage((bookings.items || [])[0], bookings.count || 0),
                        'Nouveau rendez-vous'
                    );
                }
            })
            .catch(function() {})
            .finally(function() {
                clearTriggerPending();
                if (ordersRequestSeq.isLatest(requestId)) {
                    ordersState.isLoading = false;
                    setOrdersLoading(false);
                }
            });
    }

    function bindOrderPagerControls() {
        document.addEventListener('click', function(event) {
            const btn = event.target.closest('[data-pager][data-direction]');
            if (!btn) return;

            const pagerType = String(btn.dataset.pager || '');
            const direction = String(btn.dataset.direction || '');
            const step = direction === 'next' ? 1 : -1;
            if (!step) return;

            if (pagerType === 'recent') {
                const nextPage = ordersState.recentPage + step;
                if (nextPage < 1 || nextPage > ordersState.recentPages) return;
                ordersState.recentPage = nextPage;
                refreshOrdersLive({ skipNotify: true, triggerEl: btn });
            }

            if (pagerType === 'prepare') {
                const nextPage = ordersState.preparePage + step;
                if (nextPage < 1 || nextPage > ordersState.preparePages) return;
                ordersState.preparePage = nextPage;
                refreshOrdersLive({ skipNotify: true, triggerEl: btn });
            }

            if (pagerType === 'bookings') {
                const nextPage = ordersState.bookingsPage + step;
                if (nextPage < 1 || nextPage > ordersState.bookingsPages) return;
                ordersState.bookingsPage = nextPage;
                refreshOrdersLive({ skipNotify: true, triggerEl: btn });
            }
        });
    }

    function checkLowStock() {
        const lowStockCards = document.querySelectorAll('.status-low-stock, .status-out-stock');
        const currentLowStock = new Set();
        lowStockCards.forEach(function(card) {
            const productCard = card.closest('.product-card');
            if (!productCard) return;
            const productId = String(productCard.dataset.productId || '');
            if (!productId) return;
            currentLowStock.add(productId);

            if (!lastLowStockProducts.has(productId)) {
                const titleEl = productCard.querySelector('.product-title');
                const stockEl = productCard.querySelector('.stock-number');
                const productName = titleEl ? titleEl.textContent.trim() : 'Produit';
                const stockNumber = stockEl ? stockEl.textContent.trim() : '';
                if (stockNumber) {
                    showStockToast(productName + ' - Stock: ' + stockNumber);
                }
            }
        });
        lastLowStockProducts = currentLowStock;
    }

    function selectCategory(categoryId, chip, options) {
        document.querySelectorAll('#categoriesFilter .category-chip').forEach(function(c) {
            c.classList.remove('active');
        });
        if (chip) chip.classList.add('active');
        currentCategory = String(categoryId || 'all');
        performSearch(options);
    }

    function bindCategoryChip(chip) {
        if (chip) {
            chip.dataset.bound = '1';
        }
        if (!categoriesFilter || categoriesFilter.dataset.bound === '1') return;
        categoriesFilter.dataset.bound = '1';
        categoriesFilter.addEventListener('click', function(event) {
            const targetChip = event.target.closest('.category-chip');
            if (!targetChip || !categoriesFilter.contains(targetChip)) return;
            selectCategory(targetChip.dataset.category, targetChip, { triggerEl: targetChip });
        });
    }

    function getCategoryChips() {
        if (!categoriesFilter) return [];
        return Array.prototype.slice.call(categoriesFilter.querySelectorAll('.category-chip'));
    }

    function getFilterableCategoryChips() {
        return getCategoryChips().filter(function(chip) {
            return String(chip.dataset.category || '') !== 'all';
        });
    }

    function refreshCategoriesMeta() {
        const total = getFilterableCategoryChips().length;
        const visible = getFilterableCategoryChips().filter(function(chip) {
            return !chip.classList.contains('is-hidden-filter');
        }).length;

        if (categoriesMeta) {
            categoriesMeta.textContent = visible + ' visibles / ' + total + ' categories';
        }

        if (categoriesToggleBtn) {
            const showToggle = total > 10;
            categoriesToggleBtn.style.display = showToggle ? 'inline-flex' : 'none';
            categoriesToggleBtn.textContent = categoriesExpanded ? 'Voir moins' : 'Voir plus';
            categoriesToggleBtn.setAttribute('aria-expanded', categoriesExpanded ? 'true' : 'false');
        }
    }

    function applyCategoryTextFilter() {
        const term = (categorySearchInput ? categorySearchInput.value : '').trim().toLowerCase();
        getFilterableCategoryChips().forEach(function(chip) {
            const label = (chip.textContent || '').toLowerCase();
            const matches = !term || label.indexOf(term) !== -1;
            chip.classList.toggle('is-hidden-filter', !matches);
        });
        refreshCategoriesMeta();
    }

    function loadCategories() {
        if (!categoriesFilter) return;
        const requestId = categoriesRequestSeq.next();
        if (categoriesAbortController) {
            categoriesAbortController.abort();
        }
        categoriesAbortController = new AbortController();

        const url = new URL(cfg.dashboardUrl, window.location.origin);
        url.searchParams.set('get_categories', '1');
        url.searchParams.set('_', String(Date.now()));

        requestJSON(url.toString(), {
            headers: buildAjaxHeaders({ 'Accept': 'application/json' }),
            cache: 'no-store',
            credentials: 'same-origin',
            signal: categoriesAbortController.signal
        })
            .then(function(result) {
                if (!categoriesRequestSeq.isLatest(requestId)) return;
                if (!result || !result.ok || !result.data) return;
                const data = result.data;
                const categories = data && Array.isArray(data.categories) ? data.categories : [];
                if (!categories.length) return;
                const nextSignature = categories.map(function(cat) {
                    return String(cat.id || '') + ':' + String(cat.name || '') + ':' + String(cat.count || 0);
                }).join('|');
                if (frontFluidityEnabled && nextSignature === categoriesSignature) {
                    applyCategoryTextFilter();
                    return;
                }

                batchUiCommit(function() {
                    const anchor = categoriesFilter.querySelector('.category-chip[data-category="all"]');
                    const fragment = document.createDocumentFragment();

                    categoriesFilter
                        .querySelectorAll('.category-chip:not([data-category="all"])')
                        .forEach(function(chip) { chip.remove(); });

                    categories.forEach(function(cat) {
                        const chip = document.createElement('button');
                        chip.type = 'button';
                        chip.className = 'category-chip';
                        chip.dataset.category = String(cat.id);
                        const icon = document.createElement('i');
                        icon.className = 'bi bi-tag';
                        const label = document.createElement('span');
                        label.textContent = String(cat.name || '');
                        const badge = document.createElement('span');
                        badge.className = 'category-badge';
                        badge.textContent = String(cat.count || 0);
                        chip.appendChild(icon);
                        chip.appendChild(label);
                        chip.appendChild(badge);
                        fragment.appendChild(chip);
                        bindCategoryChip(chip);
                    });

                    if (anchor && anchor.nextSibling) {
                        categoriesFilter.insertBefore(fragment, anchor.nextSibling);
                    } else {
                        categoriesFilter.appendChild(fragment);
                    }
                    categoriesSignature = nextSignature;
                    applyCategoryTextFilter();
                });
            })
            .catch(function() {});
    }

    function attachDeleteConfirmEvents(root) {
        bindConfirmForms(root || document);
    }

    function updateProductCount() {
        if (!productsContainer || !productCount) return;
        const count = productsContainer.querySelectorAll('.product-card').length;
        productCount.textContent = String(count);
    }

    function performSearch(options) {
        if (!productsContainer) return;
        const opts = options || {};
        const searchTerm = searchInput ? searchInput.value.trim() : '';
        const clearTriggerPending = setElementPending(opts.triggerEl);

        if (searchClear) {
            searchClear.classList.toggle('visible', searchTerm.length > 0);
        }

        setLoading(true);
        const requestId = searchRequestSeq.next();
        if (searchAbortController) {
            searchAbortController.abort();
        }
        searchAbortController = new AbortController();

        const params = new URLSearchParams();
        if (searchTerm) params.append('q', searchTerm);
        if (currentCategory !== 'all') params.append('category', currentCategory);
        const requestUrl = params.toString()
            ? (cfg.searchUrl + '?' + params.toString())
            : cfg.searchUrl;

        requestText(requestUrl, {
            headers: buildAjaxHeaders(),
            cache: 'no-store',
            credentials: 'same-origin',
            signal: searchAbortController.signal
        })
            .then(function(result) {
                if (!searchRequestSeq.isLatest(requestId)) return;
                if (!result || !result.ok) {
                    if (result && result.aborted) return;
                    throw new Error((result && result.error) || 'Search failed');
                }
                const html = typeof result.data === 'string' ? result.data : '';
                batchUiCommit(function() {
                    if (frontFluidityEnabled && html === lastSearchHtml) {
                        updateProductCount();
                        checkLowStock();
                        return;
                    }
                    productsContainer.style.opacity = '0.35';
                    productsContainer.innerHTML = html;
                    lastSearchHtml = html;
                    productsContainer.style.opacity = '1';
                    updateProductCount();
                    bindProductImageFallback(productsContainer);
                    attachDeleteConfirmEvents(productsContainer);
                    checkLowStock();
                });
            })
            .catch(function(err) {
                if (err && err.name === 'AbortError') return;
                if (!searchRequestSeq.isLatest(requestId)) return;
                productsContainer.innerHTML =
                    '<div class="empty-state">' +
                    '<div class="empty-icon"><i class="bi bi-exclamation-triangle"></i></div>' +
                    '<h2 class="empty-title">Erreur</h2>' +
                    '<p class="empty-text">Impossible de charger les produits.</p>' +
                    '</div>';
            })
            .finally(function() {
                clearTriggerPending();
                if (searchRequestSeq.isLatest(requestId)) {
                    setLoading(false);
                }
            });
    }

    function refreshStats() {
        if (!cfg.statsUrl || document.hidden) {
            return Promise.resolve();
        }
        const requestId = statsRequestSeq.next();
        setStatsLoading(true);
        if (statsAbortController) {
            statsAbortController.abort();
        }
        statsAbortController = new AbortController();

        return requestJSON(cfg.statsUrl, {
            headers: buildAjaxHeaders({ 'Accept': 'application/json' }),
            cache: 'no-store',
            credentials: 'same-origin',
            signal: statsAbortController.signal
        })
            .then(function(result) {
                if (!statsRequestSeq.isLatest(requestId)) return;
                if (!result || !result.ok || !result.data) return;
                const data = result.data;
                if (!data || !data.success) return;
                const nextSignature = String(data.total_orders) + ':' + String(data.total_revenue);
                if (frontFluidityEnabled && nextSignature === lastStatsSignature) {
                    return;
                }
                lastStatsSignature = nextSignature;
                const ordersEl = document.getElementById('statOrders');
                const revenueEl = document.getElementById('statRevenue');
                batchUiCommit(function() {
                    if (ordersEl && data.total_orders !== undefined) {
                        ordersEl.textContent = String(data.total_orders);
                    }
                    if (revenueEl && data.total_revenue !== undefined) {
                        revenueEl.textContent = String(data.total_revenue);
                    }
                });
            })
            .catch(function() {})
            .finally(function() {
                if (statsRequestSeq.isLatest(requestId)) {
                    setStatsLoading(false);
                }
            });
    }

    if (soundToggle) {
        soundToggle.addEventListener('click', function() {
            armAudioOnce();
            soundEnabled = !soundEnabled;
            try {
                localStorage.setItem('vendorDashboardSound', soundEnabled ? '1' : '0');
            } catch (_error) {}
            updateSoundToggle();
            if (soundEnabled) playStockAlert();
        });
    }
    updateSoundToggle();
    window.setTimeout(showSoundActivationPrompt, 600);

    if (searchInput) {
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = window.setTimeout(performSearch, cfg.searchDelayMs);
        });
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                searchInput.value = '';
                if (searchClear) searchClear.classList.remove('visible');
                performSearch();
            }
        });
    }

    if (searchClear) {
        searchClear.addEventListener('click', function() {
            if (!searchInput) return;
            searchInput.value = '';
            searchClear.classList.remove('visible');
            performSearch({ triggerEl: searchClear });
            searchInput.focus();
        });
    }

    document.addEventListener('keydown', function(e) {
        if (!searchInput) return;
        if (e.key !== '/') return;
        const tag = (document.activeElement && document.activeElement.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea') return;
        if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
        e.preventDefault();
        searchInput.focus();
    });

    if (categorySearchInput) {
        categorySearchInput.addEventListener('input', function() {
            applyCategoryTextFilter();
        });
    }

    if (categoriesToggleBtn && categoriesFilter) {
        categoriesToggleBtn.addEventListener('click', function() {
            categoriesExpanded = !categoriesExpanded;
            categoriesFilter.classList.toggle('expanded', categoriesExpanded);
            refreshCategoriesMeta();
        });
    }

    if (categoriesFilter) {
        categoriesFilter.querySelectorAll('.category-chip').forEach(bindCategoryChip);
        refreshCategoriesMeta();
    }

    attachDeleteConfirmEvents();
    bindProductImageFallback(productsContainer);
    bindProductImagePreview();
    bindShopStatusOptimistic();
    setupDashboardPrefetch();
    initVendorPushNotifications();
    checkLowStock();
    loadCategories();

    const shouldPollOrders = !!(cfg.ordersLiveUrl && (pendingCount || recentOrdersList || todayPrepareList || todayBookingsList));
    function isDashboardPageReady() {
        const bodyPage = String((document.body && document.body.dataset && document.body.dataset.page) || '');
        return !!document.getElementById('vendorDashboardConfig') &&
            (!!productsContainer || !!categoriesFilter || !!recentOrdersList || !!todayPrepareList || !!todayBookingsList) &&
            (bodyPage === 'vendor.dashboard' || window.location.pathname.indexOf('/vendor/dashboard') === 0);
    }
    if (shouldPollOrders) {
        bindOrderPagerControls();
        refreshOrdersLive({ skipNotify: true });
    }

    if (typeof VendorUI.startAdaptivePoll === 'function') {
        VendorUI.startAdaptivePoll('vendor-dashboard-stats', refreshStats, {
            activeInterval: cfg.refreshStatsMs,
            inactiveInterval: Math.max(cfg.refreshStatsMs * 3, 90000),
            when: function() {
                return isDashboardPageReady() && !!cfg.statsUrl;
            }
        });
        VendorUI.startAdaptivePoll('vendor-dashboard-stock', checkLowStock, {
            activeInterval: cfg.refreshStockMs,
            inactiveInterval: Math.max(cfg.refreshStockMs * 3, 120000),
            when: function() {
                return isDashboardPageReady() && !!productsContainer;
            }
        });
        if (shouldPollOrders) {
            VendorUI.startAdaptivePoll('vendor-dashboard-orders', function() {
                return refreshOrdersLive();
            }, {
                activeInterval: cfg.ordersPollMs,
                inactiveInterval: Math.max(cfg.ordersPollMs * 3, 45000),
                when: function() {
                    return isDashboardPageReady() && shouldPollOrders;
                }
            });
        }
    } else {
        const fallbackPollers = [];
        function startFallbackPoll(fn, intervalMs, whenFn) {
            const state = {
                timerId: null,
                intervalMs: Math.max(1000, Number(intervalMs) || 10000),
                when: typeof whenFn === 'function' ? whenFn : null
            };
            function clearTimer() {
                if (state.timerId) {
                    clearTimeout(state.timerId);
                    state.timerId = null;
                }
            }
            function schedule(delayMs) {
                clearTimer();
                state.timerId = window.setTimeout(runTick, Math.max(1000, Number(delayMs) || state.intervalMs));
            }
            function runTick() {
                if (document.hidden) {
                    clearTimer();
                    return;
                }
                if (state.when && state.when() === false) {
                    schedule(state.intervalMs);
                    return;
                }
                Promise.resolve(fn()).finally(function() {
                    schedule(state.intervalMs);
                });
            }
            fallbackPollers.push({
                stop: clearTimer,
                resume: function() {
                    schedule(1000);
                }
            });
            schedule(state.intervalMs);
        }

        startFallbackPoll(refreshStats, cfg.refreshStatsMs, function() {
            return isDashboardPageReady() && !!cfg.statsUrl;
        });
        startFallbackPoll(checkLowStock, cfg.refreshStockMs, function() {
            return isDashboardPageReady() && !!productsContainer;
        });
        if (shouldPollOrders) {
            startFallbackPoll(function() {
                return refreshOrdersLive();
            }, cfg.ordersPollMs, function() {
                return isDashboardPageReady() && shouldPollOrders;
            });
        }
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                clearDashboardTimers();
                abortDashboardRequests();
                fallbackPollers.forEach(function(poller) {
                    if (poller && typeof poller.stop === 'function') {
                        poller.stop();
                    }
                });
                return;
            }
            fallbackPollers.forEach(function(poller) {
                if (poller && typeof poller.resume === 'function') {
                    poller.resume();
                }
            });
            if (shouldPollOrders) {
                refreshOrdersLive({ force: true, skipNotify: true });
            }
        });
    }

    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            if (shouldPollOrders) {
                refreshOrdersLive({ force: true, skipNotify: true });
            }
            return;
        }
        clearDashboardTimers();
    });

    window.addEventListener('focus', function() {
        if (shouldPollOrders && !document.hidden) {
            refreshOrdersLive({ force: true, skipNotify: true });
        }
    });

    window.addEventListener('pagehide', function() {
        clearDashboardTimers();
        abortDashboardRequests();
        if (audioCtx && typeof audioCtx.close === 'function' && audioCtx.state !== 'closed') {
            audioCtx.close().catch(function() {});
        }
    });
})();


