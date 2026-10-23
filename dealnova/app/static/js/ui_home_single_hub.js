/**
 * BABA MARKET — catalogue public, panneaux accessibles et navigation mobile.
 */

(function () {
  'use strict';

  function initSingleHub() {
    var backdrop = document.getElementById('universeModalBackdrop');
    var panel = document.getElementById('universeModalPanel');
    var titleEl = document.getElementById('uModalTitle');
    var iconEl = document.getElementById('uModalIcon');
    var countEl = document.getElementById('uModalCount');
    var searchInput = document.getElementById('uModalSearchInput');
    var searchClearBtn = document.getElementById('uModalSearchClear');
    var homeSearchInput = document.getElementById('homeSearchInput');
    var homeSearchForm = document.getElementById('homeSearchForm');
    var homeSearchClearBtn = document.getElementById('homeSearchClear');
    var shopDetailSearchInput = document.getElementById('shopDetailSearchInput');
    var shopDetailSearchClearBtn = document.getElementById('shopDetailSearchClear');
    var bodyEl = document.getElementById('uModalBody');

    // Éléments de la modale Quick-View Détail Produit
    var pDetailBackdrop = document.getElementById('productDetailBackdrop');
    var pDetailPanel = document.getElementById('productDetailPanel');
    var pDetailLoading = document.getElementById('pDetailLoading');
    var pDetailContent = document.getElementById('pDetailContent');
    var pDetailCatBadge = document.getElementById('pDetailCatBadge');
    var pDetailStockBadge = document.getElementById('pDetailStockBadge');
    var pDetailShopCard = document.getElementById('pDetailShopCard');
    var pDetailShopLogo = document.getElementById('pDetailShopLogo');
    var pDetailShopName = document.getElementById('pDetailShopName');
    var pDetailShopVerified = document.getElementById('pDetailShopVerified');
    var pDetailShopRating = document.getElementById('pDetailShopRating');
    var pDetailShopBtn = document.getElementById('pDetailShopBtn');
    var pDetailMainImg = document.getElementById('pDetailMainImg');
    var pDetailPhotoDownload = document.getElementById('pDetailPhotoDownload');
    var pDetailMainVideo = document.getElementById('pDetailMainVideo');
    var pDetailVideoBadge = document.getElementById('pDetailVideoBadge');
    var pDetailZoomChip = document.getElementById('pDetailZoomChip');
    var pDetailImgWrap = document.getElementById('pDetailImgWrap');
    var pDetailMainImgBlur = document.getElementById('pDetailMainImgBlur');
    var pDetailLightbox = document.getElementById('pDetailLightbox');
    var pDetailLightboxBackdrop = document.getElementById('pDetailLightboxBackdrop');
    var pDetailLightboxClose = document.getElementById('pDetailLightboxClose');
    var pDetailLightboxCounter = document.getElementById('pDetailLightboxCounter');
    var pDetailLightboxPrev = document.getElementById('pDetailLightboxPrev');
    var pDetailLightboxNext = document.getElementById('pDetailLightboxNext');
    var pDetailLightboxImg = document.getElementById('pDetailLightboxImg');
    var lightboxActiveIndex = 0;

    // Éléments du Smart Cart Drawer 2-en-1 (Plan 1)
    var cartDrawerBackdrop = document.getElementById('cartDrawerBackdrop');
    var cartDrawerPanel = document.getElementById('cartDrawerPanel');
    var cartDrawerSlider = document.getElementById('cartDrawerSlider');
    var cartDrawerCountBadge = document.getElementById('cartDrawerCountBadge');
    var cartDrawerClearBtn = document.getElementById('cartDrawerClearBtn');
    var cartDrawerLoading = document.getElementById('cartDrawerLoading');
    var cartDrawerEmpty = document.getElementById('cartDrawerEmpty');
    var cartDrawerContent = document.getElementById('cartDrawerContent');
    var cartDrawerItemsList = document.getElementById('cartDrawerItemsList');
    var cartDrawerSubtotal = document.getElementById('cartDrawerSubtotal');
    var cartDrawerTotal = document.getElementById('cartDrawerTotal');
    var cartDrawerFooterCart = document.getElementById('cartDrawerFooterCart');
    var cartDrawerBtnProceed = document.getElementById('cartDrawerBtnProceed');
    var cartDrawerBtnPrice = document.getElementById('cartDrawerBtnPrice');
    var cartDrawerBtnBackToStep1 = document.getElementById('cartDrawerBtnBackToStep1');
    var cartDrawerBtnModifyCart = document.getElementById('cartDrawerBtnModifyCart');
    var checkoutContactProgress = document.getElementById('checkoutContactProgress');
    var cartDrawerVendorsList = document.getElementById('cartDrawerVendorsList');

    var currentCartData = null;
    var contactedVendors = {};
    var pDetailPromoBadge = document.getElementById('pDetailPromoBadge');
    var pDetailPhotoCounter = document.getElementById('pDetailPhotoCounter');
    var pDetailPhotoIndex = document.getElementById('pDetailPhotoIndex');
    var pDetailPhotoTotal = document.getElementById('pDetailPhotoTotal');
    var pDetailNavPrev = document.getElementById('pDetailNavPrev');
    var pDetailNavNext = document.getElementById('pDetailNavNext');
    var pDetailThumbs = document.getElementById('pDetailThumbs');
    var pDetailTitle = document.getElementById('pDetailTitle');
    var pDetailPriceFinal = document.getElementById('pDetailPriceFinal');
    var pDetailPriceOrig = document.getElementById('pDetailPriceOrig');
    var pDetailDiscountChip = document.getElementById('pDetailDiscountChip');
    var pDetailDescText = document.getElementById('pDetailDescText');
    var pDetailOrderSection = document.getElementById('pDetailOrderSection');
    var pDetailServiceSection = document.getElementById('pDetailServiceSection');
    var pDetailBtnCart = document.getElementById('pDetailBtnCart');
    var pDetailBtnWa = document.getElementById('pDetailBtnWa');
    var pDetailBtnBook = document.getElementById('pDetailBtnBook');
    var pDetailBtnWaService = document.getElementById('pDetailBtnWaService');
    var pDetailShareBtn = document.getElementById('pDetailShareBtn');

    // Éléments de la modale Vitrine Boutique (Proposition 1)
    var shopDetailBackdrop = document.getElementById('shopDetailBackdrop');
    var shopDetailPanel = document.getElementById('shopDetailPanel');
    var shopDetailLoading = document.getElementById('shopDetailLoading');
    var shopDetailContent = document.getElementById('shopDetailContent');
    var shopDetailBackBtn = document.getElementById('shopDetailBackBtn');
    var shopDetailBannerWrap = document.getElementById('shopDetailBannerWrap');
    var shopDetailLogoWrap = document.getElementById('shopDetailLogoWrap');
    var shopDetailName = document.getElementById('shopDetailName');
    var shopDetailVerified = document.getElementById('shopDetailVerified');
    var shopDetailStatusPill = document.getElementById('shopDetailStatusPill');
    var shopDetailRating = document.getElementById('shopDetailRating');
    var shopDetailAddress = document.getElementById('shopDetailAddress');
    var shopDetailDesc = document.getElementById('shopDetailDesc');
    var shopDetailWaBtn = document.getElementById('shopDetailWaBtn');
    var shopDetailCallBtn = document.getElementById('shopDetailCallBtn');
    var shopDetailShareBtn = document.getElementById('shopDetailShareBtn');
    var shopDetailProductCount = document.getElementById('shopDetailProductCount');
    var shopDetailProductsGrid = document.getElementById('shopDetailProductsGrid');
    var shopDetailEmpty = document.getElementById('shopDetailEmpty');

    var currentShopSlug = null;
    var shopModalOrigin = 'homepage';
    var productDetailOrigin = null;

    var activeGalleryImages = [];
    var activeGalleryIndex = 0;
    var currentActiveProductId = null;

    if (!panel || !backdrop) return;

    var currentUniverse = 'products';
    var searchTimer = null;
    var productRequestId = 0;
    var shopRequestId = 0;

    // One shared lifecycle keeps nested panels, browser Back and assistive tools in sync.
    var hubLayers = {
      universe: { node: panel, backdrop: backdrop },
      product: { node: pDetailPanel, backdrop: pDetailBackdrop },
      shop: { node: shopDetailPanel, backdrop: shopDetailBackdrop },
      cart: { node: cartDrawerPanel, backdrop: cartDrawerBackdrop },
      lightbox: { node: pDetailLightbox, backdrop: null }
    };
    var hubStack = [];
    var isExploreMode = false;
    var backgroundLocks = [];
    var restoringHubHistory = false;
    var historyNavPending = false;
    var pendingReturnFocus = null;
    var lastHubTrigger = null;
    var scrollLock = null;
    var finalReturnFocus = null;
    var lastInputType = 'pointer';
    var activeHubKind = null;
    var pendingHubAction = null;
    var motionNodes = new Set();
    var closeGesture = null;
    var ignoredCloseClick = null;
    var hubHistorySession = String(Date.now()) + '-' + Math.random().toString(36).slice(2);
    var hubHistoryIndex = 0;
    var initialHubUrl = new URL(window.location.href);
    var initialHubParams = new URLSearchParams(initialHubUrl.search);
    var hubHistoryEnabled = !!(window.history && window.history.pushState);
    var hubFocusable = 'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])';
    var viewportFrame = null;
    var viewportDirty = true;
    function updateSheetViewport() {
      viewportDirty = true;
      if (viewportFrame) return;
      viewportFrame = requestAnimationFrame(function () {
        viewportFrame = null;
        if (motionNodes.size || sheetDrag || closeGesture) return;
        var viewport = window.visualViewport;
        if (viewport && viewport.scale > 1.05) return;
        var height = Math.round(viewport ? viewport.height : window.innerHeight);
        var bottom = viewport ? Math.round(Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)) : 0;
        var rootStyle = document.documentElement.style;
        if (rootStyle.getPropertyValue('--hub-visual-height') !== height + 'px') rootStyle.setProperty('--hub-visual-height', height + 'px');
        if (rootStyle.getPropertyValue('--hub-sheet-bottom') !== bottom + 'px') rootStyle.setProperty('--hub-sheet-bottom', bottom + 'px');
        viewportDirty = false;
      });
    }
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', updateSheetViewport, { passive: true });
      window.visualViewport.addEventListener('scroll', updateSheetViewport, { passive: true });
    }
    window.addEventListener('resize', updateSheetViewport, { passive: true });
    updateSheetViewport();

    function lockHubScroll() {
      if (scrollLock) return;
      var bodyStyle = document.body.style;
      scrollLock = { x: window.scrollX, y: window.scrollY, body: {}, rootOverflow: document.documentElement.style.overflow };
      ['position', 'top', 'left', 'width', 'overflow', 'paddingRight'].forEach(function (key) { scrollLock.body[key] = bodyStyle[key]; });
      var scrollbar = Math.max(0, window.innerWidth - document.documentElement.clientWidth);
      if (scrollbar) bodyStyle.paddingRight = (parseFloat(getComputedStyle(document.body).paddingRight) + scrollbar) + 'px';
      bodyStyle.position = 'fixed';
      bodyStyle.top = -scrollLock.y + 'px';
      bodyStyle.left = -scrollLock.x + 'px';
      bodyStyle.width = '100%';
      bodyStyle.overflow = 'hidden';
      document.documentElement.style.overflow = 'hidden';
    }

    function finishHubEffects() {
      if (motionNodes.size || sheetDrag || closeGesture) return;
      if (viewportDirty) updateSheetViewport();
      if (hubStack.length || !scrollLock) return;
      unlockHubBackground();
      var saved = scrollLock;
      scrollLock = null;
      Object.keys(saved.body).forEach(function (key) { document.body.style[key] = saved.body[key]; });
      document.documentElement.style.overflow = saved.rootOverflow;
      window.scrollTo({ left: saved.x, top: saved.y, behavior: 'auto' });
      var target = finalReturnFocus;
      finalReturnFocus = null;
      // A touch dismissal must not reopen the phone keyboard behind the sheet.
      if (target && lastInputType === 'pointer' && window.matchMedia('(max-width: 768px)').matches && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) {
        target = target.closest('form') || target.parentElement;
        if (target && !target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
      }
      focusHubElement(target);
    }

    function visibleHubFocusables(node) {
      return Array.prototype.filter.call(node.querySelectorAll(hubFocusable), function (el) {
        return !el.disabled && !el.closest('[inert], [hidden], [aria-hidden="true"]') && el.getClientRects().length;
      });
    }

    function focusHubElement(node) {
      if (!node || !node.isConnected || node.closest('[inert], [hidden], [aria-hidden="true"]')) return false;
      try { node.focus({ preventScroll: true }); } catch (err) { node.focus(); }
      return document.activeElement === node;
    }

    function unlockHubBackground() {
      backgroundLocks.forEach(function (entry) {
        entry.node.inert = entry.inert;
        if (entry.ariaHidden === null) entry.node.removeAttribute('aria-hidden');
        else entry.node.setAttribute('aria-hidden', entry.ariaHidden);
      });
      backgroundLocks = [];
    }

    function lockHubBackground(parent, activeNode, activeBackdrop) {
      Array.prototype.forEach.call(parent.children, function (child) {
        if (/^(SCRIPT|STYLE|LINK|META)$/.test(child.tagName)) return;
        if (child === activeNode || child === activeBackdrop) return;
        if (child.contains(activeNode) || (activeBackdrop && child.contains(activeBackdrop))) {
          lockHubBackground(child, activeNode, activeBackdrop);
          return;
        }
        backgroundLocks.push({ node: child, inert: child.inert, ariaHidden: child.getAttribute('aria-hidden') });
        child.inert = true;
        child.setAttribute('aria-hidden', 'true');
      });
    }

    function animateHubNode(node, visible, animate, restart) {
      if (!node) return;
      if (node._hubVisible === visible && !restart) return;
      var wasVisible = node._hubVisible === true;
      var reversing = visible && node.classList.contains('is-closing');
      if (node._hubCleanup) node._hubCleanup();
      if (node._hubFrame) cancelAnimationFrame(node._hubFrame);
      node._hubFrame = null;
      node._hubVisible = visible;
      var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (node._hubGeometry) {
        Object.keys(node._hubGeometry).forEach(function (key) { node.style[key] = node._hubGeometry[key]; });
        node._hubGeometry = null;
      }
      var shouldAnimate = animate && !reduced && (visible || wasVisible);
      if (!visible && wasVisible && node.classList.contains('u-modal-panel') && window.matchMedia('(max-width: 768px)').matches) {
        var rect = node.getBoundingClientRect();
        var matrix = getComputedStyle(node).transform;
        var values = matrix === 'none' ? [] : matrix.slice(matrix.indexOf('(') + 1, -1).split(',');
        var offset = Number(values.length === 16 ? values[13] : values[5]) || 0;
        node._hubGeometry = {};
        ['top', 'bottom', 'height', 'maxHeight'].forEach(function (key) { node._hubGeometry[key] = node.style[key]; });
        node.style.top = (rect.top - offset) + 'px';
        node.style.bottom = 'auto';
        node.style.height = rect.height + 'px';
        node.style.maxHeight = 'none';
      }
      node.classList.remove(visible ? 'is-closing' : 'is-opening');
      node.hidden = false;
      node.style.visibility = 'visible';
      var timer;
      function cleanup() {
        clearTimeout(timer);
        node.removeEventListener('transitionend', ended);
        motionNodes.delete(node);
        node._hubCleanup = null;
      }
      function finish() {
        cleanup();
        node.classList.remove('is-opening', 'is-closing');
        node.hidden = !node._hubVisible;
        node.style.visibility = node._hubVisible ? 'visible' : 'hidden';
        if (node._hubGeometry) {
          Object.keys(node._hubGeometry).forEach(function (key) { node.style[key] = node._hubGeometry[key]; });
          node._hubGeometry = null;
        }
        finishHubEffects();
      }
      function ended(event) {
        if (event.target !== node) return;
        var property = node.classList.contains('u-modal-panel') ? 'transform' : 'opacity';
        if (event.propertyName === property) finish();
      }
      function start() {
        node._hubFrame = null;
        node.classList.toggle('is-open', visible);
        // Release a dragged sheet from its current offset straight into the exit.
        node.style.transition = '';
        node.style.transform = '';
        var style = getComputedStyle(node);
        function milliseconds(value) { return parseFloat(value) * (value.indexOf('ms') >= 0 ? 1 : 1000) || 0; }
        var durations = style.transitionDuration.split(',').map(milliseconds);
        var delays = style.transitionDelay.split(',').map(milliseconds);
        var budget = Math.max.apply(null, durations.map(function (duration, index) { return duration + delays[index % delays.length]; }));
        if (!budget) finish();
        else timer = setTimeout(finish, budget + 60);
      }
      if (!shouldAnimate) {
        node.classList.toggle('is-open', visible);
        node.style.transition = '';
        node.style.transform = '';
        finish();
        return;
      }
      motionNodes.add(node);
      node._hubCleanup = cleanup;
      node.classList.add(visible ? 'is-opening' : 'is-closing');
      node.addEventListener('transitionend', ended);
      if (visible && !wasVisible && !reversing) {
        node.classList.remove('is-open');
        node._hubFrame = requestAnimationFrame(function () { node._hubFrame = requestAnimationFrame(start); });
      } else start();
    }

    function syncHubLayers(returnFocus) {
      if (sheetDrag) finishSheetDrag({ pointerId: sheetDrag.pointer, type: 'pointercancel' });
      unlockHubBackground();
      var top = hubStack.length ? hubStack[hubStack.length - 1] : null;
      var previousTop = activeHubKind;
      activeHubKind = top ? top.kind : null;
      if (top) { lockHubScroll(); finalReturnFocus = null; }
      Object.keys(hubLayers).forEach(function (kind) {
        var layer = hubLayers[kind];
        if (!layer.node) return;
        var index = hubStack.findIndex(function (entry) { return entry.kind === kind; });
        var isTop = !!(top && top.kind === kind);
        layer.node.classList.toggle('is-covered', index >= 0 && !isTop);
        layer.node.inert = !isTop;
        layer.node.setAttribute('aria-hidden', isTop ? 'false' : 'true');
        layer.node.setAttribute('aria-modal', isTop ? 'true' : 'false');
        layer.node.setAttribute('tabindex', '-1');
        // Keep a closing layer's depth until its exit transition finishes.
        if (index >= 0 || !layer.node._hubVisible) layer.node.style.zIndex = String(2110 + Math.max(0, index) * 30);
        animateHubNode(layer.node, index >= 0, true);
        if (layer.backdrop) {
          if (index >= 0 || !layer.backdrop._hubVisible) layer.backdrop.style.zIndex = String(2100 + Math.max(0, index) * 30);
          animateHubNode(layer.backdrop, index >= 0, true);
        }
      });
      if (top) {
        var activeLayer = hubLayers[top.kind];
        var focusTarget = returnFocus && activeLayer.node.contains(returnFocus) ? returnFocus : activeLayer.node;
        focusHubElement(focusTarget);
        lockHubBackground(document.body, activeLayer.node, activeLayer.backdrop);
      } else {
        if (returnFocus) finalReturnFocus = returnFocus;
        var closingLayer = Object.keys(hubLayers).map(function (kind) { return hubLayers[kind]; }).find(function (layer) { return layer.node && layer.node.classList.contains('is-closing'); });
        if (closingLayer) lockHubBackground(document.body, closingLayer.node, closingLayer.backdrop);
        finishHubEffects();
      }
      if (pDetailMainVideo && (!top || top.kind !== 'product')) {
        pDetailMainVideo.pause();
        pDetailMainVideo.removeAttribute('src');
        pDetailMainVideo.removeAttribute('data-loaded-src');
        pDetailMainVideo.load();
        pDetailMainVideo.style.display = 'none';
      }
      if (window.BMCatalog && previousTop === 'universe' && (!top || top.kind !== 'universe')) window.BMCatalog.pause();
      if (window.BMCatalog && window.BMCatalog.resume && top && top.kind === 'universe' && previousTop !== 'universe') window.BMCatalog.resume();
      document.querySelectorAll('[data-hub-home]').forEach(function (link) {
        if (!top) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });
      document.querySelectorAll('[data-open-cart]').forEach(function (link) { link.setAttribute('aria-expanded', top && top.kind === 'cart' ? 'true' : 'false'); });
    }

    var sheetDrag = null;
    function closeControl(target) {
      return target.closest('[data-u-modal-close], [data-pdetail-close], [data-shop-close], [data-cart-close], #shopDetailBackBtn');
    }
    function exitInProgress() {
      return Array.from(motionNodes).some(function (node) { return node.classList.contains('u-modal-panel') && node.classList.contains('is-closing'); });
    }
    document.addEventListener('click', function (event) {
      var ignored = ignoredCloseClick && performance.now() < ignoredCloseClick.until && event.detail !== 0 && ignoredCloseClick.node.contains(event.target);
      if (!ignored && !exitInProgress()) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    }, true);
    document.addEventListener('pointerdown', function (event) {
      lastInputType = 'pointer';
      if (exitInProgress()) { event.preventDefault(); event.stopImmediatePropagation(); return; }
      if (event.button !== 0 || event.isPrimary === false || historyNavPending || closeGesture) return;
      var control = closeControl(event.target);
      var top = hubStack[hubStack.length - 1];
      if (!control || !top) return;
      var layer = hubLayers[top.kind];
      if (!layer.node.contains(control) && layer.backdrop !== control) return;
      closeGesture = { node: control, kind: top.kind, pointer: event.pointerId, x: event.clientX, y: event.clientY };
      try { control.setPointerCapture(event.pointerId); } catch (_error) {}
      // Keep the keyboard and target still between touch down and touch up.
      if (event.pointerType === 'touch') event.preventDefault();
    }, true);
    function finishCloseGesture(event) {
      if (!closeGesture || closeGesture.pointer !== event.pointerId) return;
      var gesture = closeGesture; closeGesture = null;
      try { if (gesture.node.hasPointerCapture(gesture.pointer)) gesture.node.releasePointerCapture(gesture.pointer); } catch (_error) {}
      ignoredCloseClick = { node: gesture.node, until: performance.now() + 350 };
      if (event.type === 'pointerup' && Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) < 10) {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeHubLayer(gesture.kind);
      } else finishHubEffects();
    }
    document.addEventListener('pointerup', finishCloseGesture, true);
    document.addEventListener('pointercancel', finishCloseGesture, true);
    document.addEventListener('lostpointercapture', finishCloseGesture, true);
    document.addEventListener('pointerdown', function (event) {
      lastInputType = 'pointer';
      if (!window.matchMedia('(max-width: 768px)').matches || event.button !== 0 || event.isPrimary === false || historyNavPending || sheetDrag) return;
      var handle = event.target.closest('[data-sheet-drag]');
      if (!handle) return;
      var top = hubStack[hubStack.length - 1];
      if (!top || top.kind === 'lightbox') return;
      var sheet = hubLayers[top.kind].node;
      if (!sheet.contains(handle) || motionNodes.has(sheet)) return;
      sheetDrag = { pointer: event.pointerId, start: event.clientY, startX: event.clientX, distance: 0, sheet: sheet, kind: top.kind, handle: handle, width: window.innerWidth, active: false, frame: null };
      try { handle.setPointerCapture(event.pointerId); } catch (_error) { sheetDrag = null; }
    });
    document.addEventListener('pointermove', function (event) {
      if (!sheetDrag || sheetDrag.pointer !== event.pointerId) return;
      if (!sheetDrag.active && Math.abs(event.clientX - sheetDrag.startX) > Math.max(8, Math.abs(event.clientY - sheetDrag.start))) {
        finishSheetDrag({ pointerId: event.pointerId, type: 'pointercancel' });
        return;
      }
      sheetDrag.distance = Math.max(0, event.clientY - sheetDrag.start);
      if (!sheetDrag.active && sheetDrag.distance < 6) return;
      sheetDrag.active = true;
      sheetDrag.sheet.style.transition = 'none';
      if (sheetDrag.frame) return;
      var drag = sheetDrag;
      drag.frame = requestAnimationFrame(function () {
        drag.frame = null;
        if (sheetDrag === drag) drag.sheet.style.transform = 'translateY(' + drag.distance + 'px)';
      });
    });
    function finishSheetDrag(event) {
      if (!sheetDrag || sheetDrag.pointer !== event.pointerId) return;
      var drag = sheetDrag; sheetDrag = null;
      if (drag.frame) cancelAnimationFrame(drag.frame);
      try { if (drag.handle.hasPointerCapture(drag.pointer)) drag.handle.releasePointerCapture(drag.pointer); } catch (_error) {}
      if (drag.active) {
        drag.sheet.style.transform = 'translateY(' + drag.distance + 'px)';
        drag.sheet.getBoundingClientRect();
        if (event.type === 'pointerup' && drag.distance > Math.min(100, drag.sheet.offsetHeight * 0.2) && !historyNavPending) closeHubLayer(drag.kind);
        else animateHubNode(drag.sheet, true, true, true);
      } else finishHubEffects();
    }
    document.addEventListener('pointerup', finishSheetDrag);
    document.addEventListener('pointercancel', finishSheetDrag);
    document.addEventListener('lostpointercapture', finishSheetDrag);
    window.addEventListener('blur', function () {
      if (closeGesture) finishCloseGesture({ pointerId: closeGesture.pointer, type: 'pointercancel' });
      if (sheetDrag) finishSheetDrag({ pointerId: sheetDrag.pointer, type: 'pointercancel' });
    });
    window.addEventListener('resize', function () {
      if (sheetDrag && sheetDrag.width !== window.innerWidth) finishSheetDrag({ pointerId: sheetDrag.pointer, type: 'pointercancel' });
    }, { passive: true });

    function hubSnapshot() {
      return hubStack.map(function (entry) { return { kind: entry.kind, meta: entry.meta }; });
    }

    function hubUrl(view) {
      var url = new URL(window.location.href);
      ['open', 'q', 'pdetail', 'sdetail', 'slug', 'cat', 'shop', 'city', 'listing_type', 'property_type', 'min_price', 'max_price', 'stock', 'promo', 'smart', 'sort', 'page', 'min', 'max', 'type', 'rotation_slot'].forEach(function (key) { url.searchParams.delete(key); });
      view.forEach(function (entry) {
        if (entry.kind === 'universe') {
          url.searchParams.set('open', entry.meta.universe);
          if (entry.meta.query) url.searchParams.set('q', entry.meta.query);
          Object.keys(entry.meta.filters || {}).forEach(function (key) {
            var value = entry.meta.filters[key];
            if (value && key !== 'rotation_slot' && !(key === 'page' && value === '1')) url.searchParams.set(key, value);
          });
        } else if (entry.kind === 'product') {
          url.searchParams.set('pdetail', entry.meta.pid);
        } else if (entry.kind === 'shop') {
          url.searchParams.set('sdetail', entry.meta.slug);
        } else if (entry.kind === 'cart') {
          url.searchParams.set('open', entry.meta.step || 'cart');
        }
      });
      return url.pathname + url.search + url.hash;
    }

    function saveHubHistory(push) {
      if (!hubHistoryEnabled || restoringHubHistory || historyNavPending) return;
      var view = hubSnapshot();
      var nextIndex = hubHistoryIndex + (push ? 1 : 0);
      var state = Object.assign({}, window.history.state || {});
      state.bmHub = { session: hubHistorySession, index: nextIndex, view: view };
      try {
        window.history[push ? 'pushState' : 'replaceState'](state, '', hubUrl(view));
        hubHistoryIndex = nextIndex;
      } catch (err) { hubHistoryEnabled = false; }
    }

    function showHubLayer(kind, meta) {
      var layer = hubLayers[kind];
      if (!layer || !layer.node) return;
      var top = hubStack.length ? hubStack[hubStack.length - 1] : null;
      var existing = hubStack.find(function (entry) { return entry.kind === kind; });
      if (top && top.kind === 'universe' && kind !== 'universe' && bodyEl) {
        top.meta.scrollTop = bodyEl.scrollTop;
        saveHubHistory(false);
      }
      var opener = lastInputType === 'keyboard' ? document.activeElement : lastHubTrigger;
      if (!opener || !opener.isConnected || opener.closest('[inert], [hidden], [aria-hidden="true"]') || !opener.getClientRects().length) opener = document.activeElement;
      var returnFocus = existing ? existing.returnFocus : opener;
      lastHubTrigger = null;
      hubStack = hubStack.filter(function (entry) { return entry.kind !== kind; });
      hubStack.push({ kind: kind, meta: meta || {}, returnFocus: returnFocus });
      if (restoringHubHistory) return;
      syncHubLayers();
      saveHubHistory(!top || top.kind !== kind);
    }

    function restoreHubView(view) {
      var previous = hubStack.slice();
      var reusedUniverse = false;
      restoringHubHistory = true;
      hubStack = [];
      view.forEach(function (entry) {
        if (!hubLayers[entry.kind] || !hubLayers[entry.kind].node) return;
        var existing = previous.find(function (old) {
          return old.kind === entry.kind && JSON.stringify(old.meta) === JSON.stringify(entry.meta);
        });
        if (existing) {
          hubStack.push(existing);
          if (entry.kind === 'universe') reusedUniverse = true;
          return;
        }
        var meta = entry.meta || {};
        if (entry.kind === 'universe') {
          isExploreMode = !!meta.isExplore;
          openUniverseModal(meta.universe, meta.query || '', meta.filters || {});
        }
        else if (entry.kind === 'product') openProductDetailModal(meta.pid, meta.fromShop);
        else if (entry.kind === 'shop') openShopDetailModal(meta.slug, meta.origin);
        else if (entry.kind === 'cart') openCartDrawer(meta.step);
        else if (entry.kind === 'lightbox') openLightbox(meta.index);
      });
      restoringHubHistory = false;
      var restoredUniverse = hubStack.find(function (entry) { return entry.kind === 'universe'; });
      var restoredTop = hubStack[hubStack.length - 1];
      if (restoredUniverse && restoredTop.kind === 'universe' && window.BMCatalog) {
        currentUniverse = restoredUniverse.meta.universe;
        isExploreMode = !!restoredUniverse.meta.isExplore;
        if (searchInput) searchInput.value = restoredUniverse.meta.query || '';
        var results = document.getElementById('catalogResults');
        if (!reusedUniverse || (results && results.getAttribute('aria-busy') === 'true')) {
          showUniverseContent(currentUniverse, restoredUniverse.meta.query || '', restoredUniverse.meta.filters || {}, restoredUniverse.meta.scrollTop || 0);
        } else if (bodyEl) bodyEl.scrollTop = restoredUniverse.meta.scrollTop || 0;
      }
      syncHubLayers(pendingReturnFocus);
      pendingReturnFocus = null;
    }

    function closeHubLayer(kind) {
      var index = hubStack.findIndex(function (entry) { return entry.kind === kind; });
      if (index === -1 || historyNavPending) return;
      if (kind === 'universe') isExploreMode = false;
      if (hubLayers[kind] && hubLayers[kind].node) {
        resetModalFullscreen(hubLayers[kind].node);
      }
      pendingReturnFocus = hubStack[index].returnFocus;
      var useBack = index === hubStack.length - 1 && hubHistoryEnabled && hubHistoryIndex > 0;
      hubStack = hubStack.slice(0, index);
      syncHubLayers(pendingReturnFocus);
      if (useBack) {
        historyNavPending = true;
        try { window.history.back(); return; } catch (_error) { historyNavPending = false; }
      }
      pendingReturnFocus = null;
      saveHubHistory(false);
    }

    function returnHubHome() {
      if (historyNavPending) return;
      isExploreMode = false;
      Object.keys(hubLayers).forEach(function (k) {
        if (hubLayers[k] && hubLayers[k].node) resetModalFullscreen(hubLayers[k].node);
      });
      pendingReturnFocus = document.querySelector('[data-hub-home]') || homeSearchInput;
      hubStack = [];
      syncHubLayers(pendingReturnFocus);
      if (hubHistoryEnabled && hubHistoryIndex > 0) {
        historyNavPending = true;
        try { window.history.go(-hubHistoryIndex); return; } catch (_error) { historyNavPending = false; }
      }
      pendingReturnFocus = null;
      saveHubHistory(false);
    }

    function deferHubAction(action) {
      if (!historyNavPending || restoringHubHistory) return false;
      pendingHubAction = action;
      return true;
    }

    window.addEventListener('popstate', function (event) {
      var state = event.state && event.state.bmHub;
      historyNavPending = false;
      hubHistoryIndex = state && state.session === hubHistorySession ? state.index : 0;
      restoreHubView(state && state.session === hubHistorySession ? state.view || [] : []);
      var action = pendingHubAction;
      pendingHubAction = null;
      if (action) action();
    });

    document.addEventListener('focusin', function (event) {
      var top = hubStack.length ? hubLayers[hubStack[hubStack.length - 1].kind] : null;
      if (top && !top.node.contains(event.target)) focusHubElement(top.node);
    });

    document.addEventListener('click', function (event) {
      var headerSearch = event.target.closest('[data-live-search]');
      lastHubTrigger = headerSearch ? headerSearch.querySelector('input[name="q"]') : event.target.closest('button, a, [role="button"]') || document.activeElement;
    }, true);

    if (pDetailLightbox) {
      pDetailLightbox.setAttribute('role', 'dialog');
      pDetailLightbox.setAttribute('aria-label', 'Photos du produit');
    }
    if (countEl) { countEl.setAttribute('role', 'status'); countEl.setAttribute('aria-live', 'polite'); }
    if (homeSearchInput) homeSearchInput.setAttribute('aria-label', 'Rechercher un produit, un plat ou un service');
    if (searchInput) searchInput.setAttribute('aria-label', 'Rechercher dans le catalogue');
    if (shopDetailSearchInput) shopDetailSearchInput.setAttribute('aria-label', 'Rechercher dans cette boutique');
    syncHubLayers();
    saveHubHistory(false);

    var titles = {
      products: { title: 'Produits', icon: '🛍️', placeholder: 'Rechercher un produit…' },
      services: { title: 'Services', icon: '💈', placeholder: 'Rechercher un service…' },
      locations: { title: 'Locations', icon: '🏡', placeholder: 'Ville, quartier ou annonce…' },
      shops: { title: 'Boutiques', icon: '🏪', placeholder: 'Rechercher une boutique…' },
      delivery: { title: 'Livraison de colis', icon: '📦' },
      promotions: { title: 'Promotions', icon: '🔥', placeholder: 'Rechercher une promotion…' },
      search: { title: 'Résultats de recherche', icon: '🔍', placeholder: 'Rechercher dans le catalogue…' }
    };

    function openUniverseModal(universe, initialQuery, filters) {
      if (deferHubAction(function () { openUniverseModal(universe, initialQuery, filters); })) return;
      clearTimeout(searchTimer);
      if (searchAbortController) searchAbortController.abort();
      currentUniverse = titles[universe] ? universe : 'products';
      var info = titles[currentUniverse] || titles.products;

      if (titleEl) titleEl.textContent = currentUniverse === 'search' && !(initialQuery || '').trim() ? 'Toutes les offres' : info.title;
      if (iconEl) iconEl.textContent = info.icon;
      if (searchInput) {
        searchInput.value = initialQuery || '';
        searchInput.placeholder = info.placeholder || 'Rechercher dans le catalogue…';
      }

      var catalogueFilters = window.BMCatalog ? window.BMCatalog.normalizeFilters(filters || {}) : {};
      showHubLayer('universe', { universe: currentUniverse, query: searchInput ? searchInput.value : '', filters: catalogueFilters, isExplore: isExploreMode });
      showUniverseContent(currentUniverse, initialQuery || '', catalogueFilters);
    }

    function closeUniverseModal() {
      closeHubLayer('universe');
    }

    function toggleModalFullscreen(panelNode) {
      if (!panelNode) return;
      var isFull = panelNode.classList.toggle('is-fullscreen');
      var btns = panelNode.querySelectorAll('[data-modal-fullscreen]');
      btns.forEach(function (btn) {
        btn.setAttribute('aria-pressed', isFull ? 'true' : 'false');
        btn.setAttribute('aria-label', isFull ? 'Quitter le plein écran' : 'Plein écran');
        btn.setAttribute('title', isFull ? 'Quitter le plein écran' : 'Plein écran');
        var icon = btn.querySelector('i');
        if (icon) {
          icon.className = isFull ? 'bi bi-fullscreen-exit' : 'bi bi-arrows-fullscreen';
        }
      });
    }

    function resetModalFullscreen(panelNode) {
      if (!panelNode || !panelNode.classList.contains('is-fullscreen')) return;
      panelNode.classList.remove('is-fullscreen');
      var btns = panelNode.querySelectorAll('[data-modal-fullscreen]');
      btns.forEach(function (btn) {
        btn.setAttribute('aria-pressed', 'false');
        btn.setAttribute('aria-label', 'Plein écran');
        btn.setAttribute('title', 'Plein écran');
        var icon = btn.querySelector('i');
        if (icon) {
          icon.className = 'bi bi-arrows-fullscreen';
        }
      });
    }


    // ========================================================
    // SMART CART & CHECKOUT DRAWER 2-EN-1 (PLAN 1)
    // ========================================================
    function getCsrfToken() {
      var metaCsrf = document.querySelector('meta[name="csrf-token"]');
      if (metaCsrf && metaCsrf.content) return metaCsrf.content;
      var inputCsrf = document.querySelector('input[name="csrf_token"]');
      if (inputCsrf && inputCsrf.value) return inputCsrf.value;
      return '';
    }

    function syncAllCartBadges(count) {
      var badges = document.querySelectorAll('[data-cart-badge], .cart-badge, .cart-count, #cartCount');
      badges.forEach(function (b) {
        b.textContent = count;
        b.setAttribute('data-cart-count', count);
        if (count > 0) {
          b.classList.remove('d-none');
        } else {
          b.classList.add('d-none');
        }
      });
// Floating cart button removed
    }

    function setCartDrawerStep(step) {
      if (!cartDrawerSlider) return;
      var nextStep = step === 'checkout' ? 'checkout' : 'cart';
      var cartEntry = hubStack.find(function (entry) { return entry.kind === 'cart'; });
      var previousStep = cartEntry ? cartEntry.meta.step : null;
      if (!restoringHubHistory && previousStep === 'checkout' && nextStep === 'cart' && hubHistoryEnabled && hubHistoryIndex > 0) {
        if (!historyNavPending) {
          historyNavPending = true;
          window.history.back();
        }
        return;
      }
      if (step === 'checkout') {
        cartDrawerSlider.classList.add('is-checkout-step');
      } else {
        cartDrawerSlider.classList.remove('is-checkout-step');
      }
      var cartSlide = document.getElementById('cartDrawerSlideCart');
      var checkoutSlide = document.getElementById('cartDrawerSlideCheckout');
      if (cartSlide) { cartSlide.inert = nextStep !== 'cart'; cartSlide.setAttribute('aria-hidden', nextStep !== 'cart' ? 'true' : 'false'); }
      if (checkoutSlide) { checkoutSlide.inert = nextStep !== 'checkout'; checkoutSlide.setAttribute('aria-hidden', nextStep !== 'checkout' ? 'true' : 'false'); }
      if (cartEntry && previousStep !== nextStep) {
        cartEntry.meta = { step: nextStep };
        saveHubHistory(nextStep === 'checkout');
        if (!restoringHubHistory) focusHubElement(cartDrawerPanel);
      }
    }

    function openCartDrawer(step) {
      if (deferHubAction(function () { openCartDrawer(step); })) return;
      if (!cartDrawerPanel || !cartDrawerBackdrop) return;
      setCartDrawerStep(step || 'cart');
      showHubLayer('cart', { step: step === 'checkout' ? 'checkout' : 'cart' });

      if (currentCartData) {
        if (cartDrawerLoading) cartDrawerLoading.style.display = 'none';
        renderCartStep1(currentCartData);
        renderCartStep2(currentCartData);
        loadAndRenderCartData(false);
      } else {
        loadAndRenderCartData(true);
      }
    }

    function closeCartDrawer() {
      closeHubLayer('cart');
    }

    function announceHub(message, isError) {
      var top = hubStack.length ? hubLayers[hubStack[hubStack.length - 1].kind].node : document.querySelector('.hub-page-content') || document.body;
      var status = document.getElementById('hubActionStatus');
      if (!status) {
        status = document.createElement('p');
        status.id = 'hubActionStatus';
        status.className = 'hub-feedback';
        status.style.cssText = 'position:fixed;left:50%;bottom:calc(5.5rem + env(safe-area-inset-bottom,0px));transform:translateX(-50%);z-index:3000;max-width:calc(100vw - 2rem);width:max-content;padding:.8rem 1rem;border-radius:14px;background:#0f172a;color:#fff;box-shadow:0 8px 24px #0f172a33;font-size:.875rem;line-height:1.4;pointer-events:none;';
      }
      status.setAttribute('role', isError ? 'alert' : 'status');
      status.setAttribute('aria-live', isError ? 'assertive' : 'polite');
      if (status.parentElement !== top) top.appendChild(status);
      clearTimeout(status._hubTimer);
      status.hidden = false;
      status.style.background = isError ? '#991b1b' : '#0f172a';
      status.textContent = message;
      status._hubTimer = setTimeout(function () { status.hidden = true; }, isError ? 6000 : 3500);
    }

    function readCartResponse(response) {
      return response.json().catch(function () {
        throw new Error('Le serveur ne répond pas correctement. Réessayez.');
      }).then(function (data) {
        if (!response.ok || !data || data.success !== true) {
          throw new Error(data && data.message ? data.message : 'Action impossible. Réessayez.');
        }
        return data;
      });
    }

    function addProductToCart(pid, button, form) {
      if (!pid || (button && button.dataset.hubBusy === '1')) return;
      var previousHtml = button ? button.innerHTML : '';
      var previousDisabled = button ? button.disabled : false;
      var previousLabel = button ? button.getAttribute('aria-label') : null;
      var compactButton = !!(button && button.classList.contains('hub-product-add'));
      if (button) {
        button.dataset.hubBusy = '1';
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        button.setAttribute('aria-label', 'Ajout en cours');
        button.innerHTML = '<i class="bi bi-arrow-repeat spin" aria-hidden="true"></i>' + (compactButton ? '' : ' Ajout en cours…');
      }
      var requestBody = form ? new FormData(form) : new URLSearchParams();
      var csrf = getCsrfToken();
      if (csrf && !requestBody.has('csrf_token')) requestBody.append('csrf_token', csrf);
      var headers = { 'X-Requested-With': 'XMLHttpRequest' };
      if (!form) headers['Content-Type'] = 'application/x-www-form-urlencoded';
      fetch(form ? form.action : '/cart/add/' + encodeURIComponent(pid), {
        method: 'POST', body: requestBody, headers: headers
      }).then(readCartResponse).then(function (data) {
        if (typeof data.cart_count === 'number') syncAllCartBadges(data.cart_count);
        if (button) {
          button.innerHTML = '<i class="bi bi-check2" aria-hidden="true"></i>' + (compactButton ? '' : ' Ajouté au panier');
          button.setAttribute('aria-label', 'Ajouté au panier');
        }
        announceHub(data.message || 'Produit ajouté au panier.', false);
        document.dispatchEvent(new CustomEvent('cart:changed', { detail: data }));
        loadAndRenderCartData(false);
      }).catch(function (error) {
        if (button) button.innerHTML = previousHtml;
        announceHub(error.message || 'Impossible d’ajouter cet article. Réessayez.', true);
      }).finally(function () {
        if (!button) return;
        button.removeAttribute('aria-busy');
        setTimeout(function () {
          button.innerHTML = previousHtml;
          button.disabled = previousDisabled;
          if (previousLabel === null) button.removeAttribute('aria-label');
          else button.setAttribute('aria-label', previousLabel);
          delete button.dataset.hubBusy;
        }, 1200);
      });
    }

    function renderCartStep1(data) {
      var items = data.items || [];
      if (cartDrawerCountBadge) cartDrawerCountBadge.textContent = data.count || 0;

      if (!items.length) {
        if (cartDrawerLoading) cartDrawerLoading.style.display = 'none';
        if (cartDrawerContent) cartDrawerContent.style.display = 'none';
        if (cartDrawerFooterCart) cartDrawerFooterCart.style.display = 'none';
        if (cartDrawerClearBtn) cartDrawerClearBtn.style.display = 'none';
        if (cartDrawerEmpty) cartDrawerEmpty.style.display = 'block';
        return;
      }

      if (cartDrawerEmpty) cartDrawerEmpty.style.display = 'none';
      if (cartDrawerLoading) cartDrawerLoading.style.display = 'none';
      if (cartDrawerContent) cartDrawerContent.style.display = 'block';
      if (cartDrawerFooterCart) cartDrawerFooterCart.style.display = 'block';
      if (cartDrawerClearBtn) cartDrawerClearBtn.style.display = 'inline-flex';

      if (cartDrawerSubtotal) cartDrawerSubtotal.textContent = data.total_label || (Number(data.total).toFixed(2) + ' DH');
      if (cartDrawerTotal) cartDrawerTotal.textContent = data.total_label || (Number(data.total).toFixed(2) + ' DH');
      if (cartDrawerBtnPrice) cartDrawerBtnPrice.textContent = data.total_label || (Number(data.total).toFixed(2) + ' DH');

      if (cartDrawerItemsList) {
        cartDrawerItemsList.innerHTML = '';
        items.forEach(function (item) {
          var card = document.createElement('div');
          card.className = 'u-cart-item-card';
          card.setAttribute('data-cart-pid', item.id);

          var imgSrc = item.image ? ('/static/uploads/' + item.image) : '/static/images/produit.jpeg';

          var html = '';
          html += '<div class="u-cart-item-media">';
          html += '  <img src="' + imgSrc + '" alt="' + (item.name || '').replace(/"/g, '&quot;') + '" onerror="this.src=\'/static/images/produit.jpeg\';" />';
          html += '</div>';
          html += '<div class="u-cart-item-info">';
          html += '  <h5 class="u-cart-item-title">' + (item.name || '') + '</h5>';
          html += '  <div class="u-cart-item-shop"><i class="bi bi-shop" style="color:#db2777;"></i> ' + (item.shop_name || 'Boutique') + ' • ' + Number(item.unit_price).toFixed(2) + ' DH</div>';
          html += '  <div class="u-cart-item-bottom">';
          html += '    <div class="u-cart-qty-ctrl">';
          html += '      <button type="button" class="u-cart-qty-btn" data-cart-action="decrease" data-pid="' + item.id + '" aria-label="Diminuer">-</button>';
          html += '      <span class="u-cart-qty-val">' + item.quantity + '</span>';
          html += '      <button type="button" class="u-cart-qty-btn" data-cart-action="increase" data-pid="' + item.id + '" aria-label="Augmenter">+</button>';
          html += '    </div>';
          html += '    <div class="u-cart-item-price-wrap">';
          html += '      <span class="u-cart-item-line-total">' + Number(item.line_total).toFixed(2) + ' DH</span>';
          html += '      <button type="button" class="u-cart-item-del-btn" data-cart-action="remove" data-pid="' + item.id + '" title="Retirer"><i class="bi bi-trash3"></i></button>';
          html += '    </div>';
          html += '  </div>';
          html += '</div>';

          card.innerHTML = html;
          cartDrawerItemsList.appendChild(card);
        });
      }
    }

    function renderCartStep2(data) {
      var groups = data.shop_groups || [];
      var contactableCount = groups.filter(function (g) { return g.phone_available; }).length;

      var contactedCount = 0;
      groups.forEach(function (g) {
        if (contactedVendors[g.shop_id]) contactedCount++;
      });

      if (checkoutContactProgress) {
        checkoutContactProgress.textContent = contactedCount + (contactedCount > 1 ? ' conversations ouvertes sur ' : ' conversation ouverte sur ') + contactableCount;
      }

      if (cartDrawerVendorsList) {
        cartDrawerVendorsList.innerHTML = '';
        if (!groups.length) {
          cartDrawerVendorsList.innerHTML = '<p style="text-align:center;color:#64748b;padding:1.5rem;">Aucun article dans le panier.</p>';
          return;
        }

        groups.forEach(function (group, idx) {
          var isContacted = !!contactedVendors[group.shop_id];
          var card = document.createElement('div');
          card.className = 'u-checkout-vendor-card';

          var logoHtml = group.shop_logo ? ('<img src="/static/uploads/' + group.shop_logo + '" alt="' + (group.shop_name || '') + '" onerror="this.src=\'/static/images/produit.jpeg\';" />') : '<i class="bi bi-shop"></i>';

          var itemsListHtml = '';
          (group.items || []).forEach(function (it) {
            itemsListHtml += '<div class="u-checkout-vendor-item-row">';
            itemsListHtml += '  <span>' + it.name + ' <strong>x' + it.quantity + '</strong></span>';
            itemsListHtml += '  <span>' + it.line_total_label + '</span>';
            itemsListHtml += '</div>';
          });

          var html = '';
          html += '<div class="u-checkout-vendor-top">';
          html += '  <div class="u-checkout-vendor-avatar">' + logoHtml + '</div>';
          html += '  <div class="u-checkout-vendor-info">';
          html += '    <h4 class="u-checkout-vendor-name">' + group.shop_name + '</h4>';
          if (group.phone_raw) {
            html += '    <p class="u-checkout-vendor-phone"><i class="bi bi-telephone"></i> ' + group.phone_raw + '</p>';
          }
          html += '  </div>';
          html += '</div>';

          html += '<div class="u-checkout-vendor-items-list">' + itemsListHtml + '</div>';

          html += '<div class="u-checkout-vendor-total-row">';
          html += '  <span>Total boutique (' + group.items_count + (group.items_count > 1 ? ' articles' : ' article') + ')</span>';
          html += '  <strong style="color:#059669;font-size:1.02rem;">' + group.subtotal_label + '</strong>';
          html += '</div>';

          if (group.phone_available && group.whatsapp_url) {
            var btnClass = 'u-checkout-btn-wa' + (isContacted ? ' is-contacted' : '');
            var btnText = isContacted ? '<i class="bi bi-check2-circle"></i> WhatsApp ouvert' : '<i class="bi bi-whatsapp"></i> Ouvrir WhatsApp';
            html += '<a href="' + group.whatsapp_url + '" target="_blank" rel="noopener noreferrer" class="' + btnClass + '" data-contact-shop-id="' + group.shop_id + '">';
            html += btnText;
            html += '</a>';
          } else {
            html += '<button type="button" class="u-checkout-btn-wa" style="background:#94a3b8;cursor:not-allowed;" disabled><i class="bi bi-exclamation-circle"></i> WhatsApp indisponible pour cette boutique</button>';
          }

          card.innerHTML = html;
          cartDrawerVendorsList.appendChild(card);
        });
      }
    }

    function loadAndRenderCartData(showSpinner) {
      if (showSpinner !== false && !currentCartData) {
        if (cartDrawerLoading) cartDrawerLoading.style.display = 'block';
        if (cartDrawerContent) cartDrawerContent.style.display = 'none';
      }

      fetch('/cart/api/full', {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
        .then(readCartResponse)
        .then(function (data) {
          if (!data || !data.success) throw new Error('Données indisponibles');
          currentCartData = data;
          syncAllCartBadges(data.count || 0);
          renderCartStep1(data);
          renderCartStep2(data);
          if (cartDrawerLoading) cartDrawerLoading.style.display = 'none';
        })
        .catch(function () {
          if (!currentCartData && cartDrawerLoading) {
            cartDrawerLoading.innerHTML = '<p style="color:#ef4444;font-weight:700;">Impossible de charger votre panier.</p><button type="button" class="u-pdetail-back-btn" data-cart-close style="margin-top:0.8rem;">✕ Fermer</button>';
          }
        });
    }

    function updateCartItemQty(pid, newQty) {
      if (currentCartData && currentCartData.items) {
        var it = currentCartData.items.find(function (item) { return String(item.id) === String(pid); });
        if (it) {
          if (newQty <= 0) {
            currentCartData.items = currentCartData.items.filter(function (item) { return String(item.id) !== String(pid); });
          } else {
            it.quantity = newQty;
            it.line_total = it.unit_price * newQty;
          }
          currentCartData.count = currentCartData.items.reduce(function (sum, item) { return sum + item.quantity; }, 0);
          currentCartData.total = currentCartData.items.reduce(function (sum, item) { return sum + item.line_total; }, 0);
          currentCartData.total_label = Number(currentCartData.total).toFixed(2) + ' DH';
          syncAllCartBadges(currentCartData.count);
          renderCartStep1(currentCartData);
        }
      }

      var csrf = getCsrfToken();
      fetch('/cart/api/update/' + pid, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': csrf
        },
        body: JSON.stringify({ quantity: newQty, csrf_token: csrf })
      })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data && data.success) {
            loadAndRenderCartData(false);
          }
        })
        .catch(function () {});
    }

    function removeCartItem(pid) {
      if (currentCartData && currentCartData.items) {
        currentCartData.items = currentCartData.items.filter(function (item) { return String(item.id) !== String(pid); });
        currentCartData.count = currentCartData.items.reduce(function (sum, item) { return sum + item.quantity; }, 0);
        currentCartData.total = currentCartData.items.reduce(function (sum, item) { return sum + item.line_total; }, 0);
        currentCartData.total_label = Number(currentCartData.total).toFixed(2) + ' DH';
        syncAllCartBadges(currentCartData.count);
        renderCartStep1(currentCartData);
      }

      var csrf = getCsrfToken();
      fetch('/cart/api/remove/' + pid, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': csrf
        },
        body: JSON.stringify({ csrf_token: csrf })
      })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data && data.success) {
            loadAndRenderCartData(false);
          }
        })
        .catch(function () {});
    }

    function clearCartItems() {
      var csrf = getCsrfToken();
      fetch('/cart/api/clear', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': csrf
        },
        body: JSON.stringify({ csrf_token: csrf })
      })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data && data.success) {
            loadAndRenderCartData();
          }
        })
        .catch(function () {});
    }


    // ========================================================
    // VISIONNEUSE PLEIN ÉCRAN LIGHTBOX (SOLUTION 3)
    // ========================================================
    function updateLightboxImage(index) {
      if (!activeGalleryImages.length) return;
      if (index < 0) index = activeGalleryImages.length - 1;
      if (index >= activeGalleryImages.length) index = 0;
      lightboxActiveIndex = index;

      var imgName = activeGalleryImages[index];
      var fullImg = imgName ? ('/static/uploads/' + imgName) : '/static/images/produit.jpeg';
      if (pDetailLightboxImg) pDetailLightboxImg.src = fullImg;
      if (pDetailLightboxCounter) {
        pDetailLightboxCounter.textContent = (index + 1) + ' / ' + activeGalleryImages.length;
      }
      var itemIndex = activeGalleryItems.findIndex(function (it) {
        return it.type === 'image' && it.src === imgName;
      });
      if (itemIndex !== -1) updateGalleryMedia(itemIndex);
    }

    function openLightbox(index) {
      if (deferHubAction(function () { openLightbox(index); })) return;
      if (!pDetailLightbox) return;
      var curItem = activeGalleryItems[activeGalleryIndex];
      if (curItem && curItem.type === 'video') return;
      if (!activeGalleryImages.length) return;

      var targetImgIdx = 0;
      if (curItem && curItem.type === 'image') {
        var foundIdx = activeGalleryImages.indexOf(curItem.src);
        if (foundIdx !== -1) targetImgIdx = foundIdx;
      }
      lightboxActiveIndex = targetImgIdx;
      pDetailLightbox.style.display = 'flex';
      pDetailLightbox.offsetHeight; // reflow

      var hasMultiple = activeGalleryImages.length > 1;
      if (pDetailLightboxPrev) pDetailLightboxPrev.style.display = hasMultiple ? 'flex' : 'none';
      if (pDetailLightboxNext) pDetailLightboxNext.style.display = hasMultiple ? 'flex' : 'none';

      updateLightboxImage(lightboxActiveIndex);
      showHubLayer('lightbox', { index: lightboxActiveIndex });
    }

    function closeLightbox() {
      if (!pDetailLightbox) return;
      closeHubLayer('lightbox');
    }

    // ========================================================
    // GESTION DE LA MODALE DÉTAIL PRODUIT (QUICK-VIEW OPTION A)
    // ========================================================
    var activeGalleryItems = [];
    var currentProductHasPromo = false;
    var currentProductKind = 'product';

    function detailPlaceholderUrl() {
      return currentProductKind === 'service'
        ? '/static/img/placeholders/service.svg'
        : '/static/img/placeholders/product.svg';
    }

    function updatePhotoDownload(url) {
      if (!pDetailPhotoDownload) return;
      pDetailPhotoDownload.hidden = !url;
      if (url) pDetailPhotoDownload.href = url;
      else pDetailPhotoDownload.removeAttribute('href');
    }

    function updateGalleryMedia(index) {
      if (!activeGalleryItems.length) return;
      if (index < 0) index = activeGalleryItems.length - 1;
      if (index >= activeGalleryItems.length) index = 0;
      activeGalleryIndex = index;

      var currentItem = activeGalleryItems[index];
      updatePhotoDownload(currentItem.type === 'image' && currentItem.src ? currentItem.downloadUrl : '');

      if (currentItem.type === 'video') {
        if (pDetailMainImg) pDetailMainImg.style.display = 'none';
        if (pDetailMainImgBlur) pDetailMainImgBlur.style.display = 'none';
        if (pDetailZoomChip) pDetailZoomChip.style.display = 'none';
        if (pDetailPromoBadge) pDetailPromoBadge.style.display = 'none';
        if (pDetailVideoBadge) pDetailVideoBadge.style.display = 'inline-flex';
        if (pDetailMainVideo) {
          pDetailMainVideo.style.display = 'block';
          if (activeGalleryImages.length && activeGalleryImages[0]) {
            pDetailMainVideo.poster = '/static/uploads/' + activeGalleryImages[0];
          } else {
            pDetailMainVideo.removeAttribute('poster');
          }
          if (pDetailMainVideo.getAttribute('data-loaded-src') !== currentItem.src) {
            pDetailMainVideo.src = currentItem.src;
            pDetailMainVideo.setAttribute('data-loaded-src', currentItem.src);
            pDetailMainVideo.load();
          }
        }
      } else {
        if (pDetailMainVideo) {
          pDetailMainVideo.pause();
          pDetailMainVideo.style.display = 'none';
        }
        if (pDetailVideoBadge) pDetailVideoBadge.style.display = 'none';
        var fullImg = currentItem.src ? ('/static/uploads/' + currentItem.src) : detailPlaceholderUrl();
        if (pDetailMainImg) {
          pDetailMainImg.style.display = 'block';
          pDetailMainImg.src = fullImg;
        }
        if (pDetailMainImgBlur) {
          pDetailMainImgBlur.style.display = 'block';
          pDetailMainImgBlur.src = fullImg;
        }
        if (pDetailZoomChip) pDetailZoomChip.style.display = currentItem.src ? 'inline-flex' : 'none';
        if (pDetailPromoBadge && currentProductHasPromo) pDetailPromoBadge.style.display = 'inline-block';
      }

      if (pDetailPhotoIndex) pDetailPhotoIndex.textContent = (index + 1);
      if (pDetailPhotoCounter) {
        var counterIcon = pDetailPhotoCounter.querySelector('i');
        if (counterIcon) {
          counterIcon.className = currentItem.type === 'video' ? 'bi bi-play-circle-fill' : 'bi bi-camera';
        }
      }

      if (pDetailThumbs) {
        var thumbs = pDetailThumbs.querySelectorAll('.u-pdetail-thumb');
        thumbs.forEach(function (th, i) {
          th.classList.toggle('is-active', i === index);
        });
      }
    }
    var updateGalleryImage = updateGalleryMedia;

    function configureDetailShare(button, name, url, label) {
      if (!button) return;
      button.dataset.shareReady = url ? '1' : '0';
      button.disabled = !url || !!button.__sharePending;
      ['title', 'text', 'url'].forEach(function (key) { button.removeAttribute('data-share-' + key); });
      if (url) {
        button.dataset.shareTitle = name + ' | BabaMarket';
        button.dataset.shareText = name;
        button.dataset.shareUrl = url;
      }
      button.setAttribute('aria-label', label || 'Partager');
      if (button.__shareStatus) button.__shareStatus.textContent = '';
    }

    function openProductDetailModal(pid, fromShopSlug) {
      if (deferHubAction(function () { openProductDetailModal(pid, fromShopSlug); })) return;
      if (!pDetailPanel || !pDetailBackdrop) return;
      currentActiveProductId = pid;
      productDetailOrigin = fromShopSlug || null;
      var requestId = ++productRequestId;
      configureDetailShare(pDetailShareBtn);
      updatePhotoDownload('');
      showHubLayer('product', { pid: String(pid), fromShop: fromShopSlug || null });

      if (pDetailLoading) {
        pDetailLoading.style.display = 'block';
        pDetailLoading.innerHTML = '<i class="bi bi-arrow-repeat spin" style="font-size:2.2rem;display:inline-block;color:#10b981;"></i><p style="margin-top:0.6rem;font-weight:600;">Chargement des détails...</p>';
      }
      if (pDetailContent) pDetailContent.style.display = 'none';

      fetch('/api/product/' + encodeURIComponent(pid), { cache: 'no-store' })
        .then(function (res) {
          if (!res.ok) throw new Error('Produit non trouvé');
          return res.json();
        })
        .then(function (data) {
          if (requestId !== productRequestId) return;
          if (!data || !data.success || !data.product) {
            throw new Error('Données indisponibles');
          }
          var product = data.product;
          currentProductKind = product.kind === 'service' ? 'service' : 'product';

          // Catégorie
          if (pDetailCatBadge) pDetailCatBadge.textContent = product.category || 'Détails du produit';

          // Statut Disponibilité
          if (pDetailStockBadge) {
            if (product.kind === 'service') {
              pDetailStockBadge.className = 'u-pdetail-meta-pill pill-stock';
              pDetailStockBadge.innerHTML = '<i class="bi bi-calendar-check"></i> Sur rendez-vous';
            } else if (product.stock > 0) {
              pDetailStockBadge.className = 'u-pdetail-meta-pill pill-stock';
              pDetailStockBadge.innerHTML = '<i class="bi bi-check-circle-fill"></i> En stock';
            } else {
              pDetailStockBadge.className = 'u-pdetail-meta-pill pill-out-of-stock';
              pDetailStockBadge.innerHTML = '<i class="bi bi-x-circle-fill"></i> Indisponible';
            }
          }

          // Boutique
          if (pDetailShopCard) {
            if (product.shop) {
              pDetailShopCard.style.display = 'flex';
              if (pDetailShopName) pDetailShopName.textContent = product.shop.name;
              if (pDetailShopVerified) pDetailShopVerified.style.display = product.shop.is_verified ? 'inline-block' : 'none';
              if (pDetailShopRating) {
                if (product.shop.rating) pDetailShopRating.innerHTML = '<i class="bi bi-star-fill text-warning"></i> ' + (Math.round(product.shop.rating * 10) / 10);
                else pDetailShopRating.textContent = 'Aucun avis';
              }
              if (pDetailShopLogo) {
                if (product.shop.logo) {
                  pDetailShopLogo.innerHTML = '<img src="/static/uploads/' + product.shop.logo + '" alt="' + product.shop.name + '" onerror="this.onerror=null;this.parentElement.innerHTML=\'<i class=\\\'bi bi-shop\\\'></i>\';" />';
                } else {
                  pDetailShopLogo.innerHTML = '<i class="bi bi-shop"></i>';
                }
              }
              if (pDetailShopBtn) {
                pDetailShopBtn.setAttribute('data-open-shop-slug', product.shop.slug || product.shop.id);
                pDetailShopBtn.href = 'javascript:void(0)';
              }
            } else {
              pDetailShopCard.style.display = 'none';
            }
          }

          // Galerie Photos & Vidéos (la vidéo est toujours affichée en premier si présente)
          activeGalleryItems = [];
          if (product.video_url) {
            activeGalleryItems.push({ type: 'video', src: product.video_url });
          }
          if (product.images && product.images.length) {
            product.images.forEach(function (imgName, photoIndex) {
              activeGalleryItems.push({ type: 'image', src: imgName,
                downloadUrl: (product.image_download_urls || [])[photoIndex] ||
                  '/shop/product/' + encodeURIComponent(product.id || pid) + '/photo/' + photoIndex + '/download' });
            });
          }
          if (!activeGalleryItems.length) {
            activeGalleryItems.push({ type: 'image', src: '' });
          }
          activeGalleryImages = activeGalleryItems
            .filter(function (it) { return it.type === 'image'; })
            .map(function (it) { return it.src; });
          activeGalleryIndex = 0;

          // Prix & Promos
          currentProductHasPromo = Boolean(product.has_promo && product.price > product.final_price);

          if (pDetailThumbs) {
            pDetailThumbs.innerHTML = '';
            if (activeGalleryItems.length > 1) {
              activeGalleryItems.forEach(function (item, idx) {
                var thumb;
                if (item.type === 'video') {
                  thumb = document.createElement('button');
                  thumb.type = 'button';
                  thumb.className = 'u-pdetail-thumb u-pdetail-thumb-video' + (idx === 0 ? ' is-active' : '');
                  thumb.setAttribute('aria-label', 'Voir la vidéo');
                  thumb.innerHTML = '<i class="bi bi-play-circle-fill"></i><span>Vidéo</span>';
                } else {
                  thumb = document.createElement('img');
                  thumb.className = 'u-pdetail-thumb' + (idx === 0 ? ' is-active' : '');
                  thumb.src = item.src ? ('/static/uploads/' + item.src) : detailPlaceholderUrl();
                  thumb.alt = product.name;
                }
                thumb.addEventListener('click', function () {
                  updateGalleryMedia(idx);
                });
                pDetailThumbs.appendChild(thumb);
              });
              if (pDetailPhotoCounter) {
                pDetailPhotoCounter.style.display = 'inline-flex';
                if (pDetailPhotoTotal) pDetailPhotoTotal.textContent = activeGalleryItems.length;
              }
              if (pDetailNavPrev) pDetailNavPrev.style.display = 'flex';
              if (pDetailNavNext) pDetailNavNext.style.display = 'flex';
            } else {
              if (pDetailPhotoCounter) pDetailPhotoCounter.style.display = 'none';
              if (pDetailNavPrev) pDetailNavPrev.style.display = 'none';
              if (pDetailNavNext) pDetailNavNext.style.display = 'none';
            }
          }
          updateGalleryMedia(0);

          // Titre
          if (pDetailTitle) pDetailTitle.textContent = product.name;
          configureDetailShare(pDetailShareBtn, product.name, product.share_url,
            product.kind === 'service' ? 'Partager ce service' : 'Partager ce produit');

          // Prix & Promos
          if (pDetailPriceFinal) pDetailPriceFinal.textContent = Number(product.final_price).toFixed(2) + ' DH';

          if (currentProductHasPromo) {
            if (pDetailPriceOrig) {
              pDetailPriceOrig.textContent = Number(product.price).toFixed(2) + ' DH';
              pDetailPriceOrig.style.display = 'inline';
            }
            if (pDetailDiscountChip) {
              var discLabel = '-' + (product.promo_value || product.discount_amount) + (product.promo_type === 'percentage' ? '%' : ' DH');
              pDetailDiscountChip.textContent = discLabel;
              pDetailDiscountChip.style.display = 'inline-block';
            }
            if (pDetailPromoBadge) pDetailPromoBadge.style.display = 'block';
          } else {
            if (pDetailPriceOrig) pDetailPriceOrig.style.display = 'none';
            if (pDetailDiscountChip) pDetailDiscountChip.style.display = 'none';
            if (pDetailPromoBadge) pDetailPromoBadge.style.display = 'none';
          }

          // Description complète (sans troncature)
          if (pDetailDescText) pDetailDescText.textContent = product.description;

          // Actions directes
          if (product.kind === 'service') {
            if (pDetailOrderSection) pDetailOrderSection.style.display = 'none';
            if (pDetailServiceSection) pDetailServiceSection.style.display = 'flex';
            if (pDetailBtnBook) pDetailBtnBook.href = product.booking_url || ('/booking/' + product.id);
            if (pDetailBtnWaService) pDetailBtnWaService.href = product.whatsapp_order_url;
          } else {
            if (pDetailOrderSection) pDetailOrderSection.style.display = 'flex';
            if (pDetailServiceSection) pDetailServiceSection.style.display = 'none';
            if (pDetailBtnWa) pDetailBtnWa.href = product.whatsapp_order_url;
          }

          if (pDetailLoading) pDetailLoading.style.display = 'none';
          if (pDetailContent) pDetailContent.style.display = 'block';
        })
        .catch(function () {
          if (requestId !== productRequestId) return;
          if (pDetailLoading) {
            pDetailLoading.innerHTML = '<p style="color:#ef4444;font-weight:700;">Impossible de charger les détails du produit.</p><button type="button" class="u-pdetail-back-btn" data-pdetail-close style="margin-top:0.8rem;">← Retour</button>';
          }
        });
    }

    // ========================================================
    // GESTION DE LA MODALE VITRINE BOUTIQUE (PROPOSITION 1)
    // ========================================================
    function openShopDetailModal(shopSlugOrId, origin) {
      if (deferHubAction(function () { openShopDetailModal(shopSlugOrId, origin); })) return;
      if (!shopDetailPanel || !shopDetailBackdrop) return;
      currentShopSlug = shopSlugOrId;
      shopModalOrigin = origin || 'homepage';
      var requestId = ++shopRequestId;
      configureDetailShare(shopDetailShareBtn);
      showHubLayer('shop', { slug: String(shopSlugOrId), origin: shopModalOrigin });

      if (shopDetailLoading) {
        shopDetailLoading.style.display = 'block';
        shopDetailLoading.innerHTML = '<i class="bi bi-arrow-repeat spin" style="font-size:2.2rem;display:inline-block;color:#10b981;"></i><p style="margin-top:0.6rem;font-weight:600;">Chargement de la boutique...</p>';
      }
      if (shopDetailContent) shopDetailContent.style.display = 'none';

      fetch('/api/shop/' + encodeURIComponent(shopSlugOrId) + '?preview=1')
        .then(function (res) {
          if (!res.ok) throw new Error('Boutique introuvable');
          return res.json();
        })
        .then(function (data) {
          if (requestId !== shopRequestId) return;
          if (!data || !data.success || !data.shop) {
            throw new Error('Données indisponibles');
          }
          var shop = data.shop;
          var products = data.products || [];

          // Nom
          if (shopDetailName) shopDetailName.textContent = shop.name;
          configureDetailShare(shopDetailShareBtn, shop.name, shop.share_url, 'Partager cette boutique');

          // Badge vérifié
          if (shopDetailVerified) {
            shopDetailVerified.style.display = shop.is_verified ? 'inline-block' : 'none';
          }

          // Logo
          if (shopDetailLogoWrap) {
            if (shop.logo) {
              shopDetailLogoWrap.innerHTML = '<img src="/static/uploads/' + shop.logo + '" alt="' + shop.name + '" onerror="this.onerror=null;this.parentElement.innerHTML=\'<i class=\\\'bi bi-shop\\\'></i>\';" />';
            } else {
              shopDetailLogoWrap.innerHTML = '<i class="bi bi-shop"></i>';
            }
          }

          // Bannière
          if (shopDetailBannerWrap) {
            if (shop.banner) {
              shopDetailBannerWrap.style.backgroundImage = 'url(/static/uploads/' + shop.banner + ')';
            } else {
              shopDetailBannerWrap.style.backgroundImage = 'linear-gradient(135deg, #059669 0%, #10b981 60%, #34d399 100%)';
            }
          }

          // Statut Ouvert/Fermé
          if (shopDetailStatusPill) {
            if (shop.is_open) {
              shopDetailStatusPill.className = 'u-shop-status-pill pill-open';
              shopDetailStatusPill.innerHTML = '<i class="bi bi-clock-fill"></i> Ouvert';
            } else {
              shopDetailStatusPill.className = 'u-shop-status-pill pill-closed';
              shopDetailStatusPill.innerHTML = '<i class="bi bi-door-closed-fill"></i> Fermé';
            }
          }

          // Note
          if (shopDetailRating) {
            var rVal = shop.rating ? (Math.round(shop.rating * 10) / 10) : null;
            var rReviews = shop.review_count || 0;
            if (rVal) {
              shopDetailRating.innerHTML = '<i class="bi bi-star-fill text-warning"></i> ' + rVal + (rReviews ? ' (' + rReviews + ' avis)' : '');
            } else {
              shopDetailRating.textContent = 'Aucun avis';
            }
          }

          // Adresse
          if (shopDetailAddress) {
            shopDetailAddress.innerHTML = '<i class="bi bi-geo-alt-fill"></i> ' + (shop.address || 'Rabat • Salé');
          }

          // Description
          if (shopDetailDesc) {
            if (shop.description) {
              shopDetailDesc.textContent = shop.description;
              shopDetailDesc.style.display = 'block';
            } else {
              shopDetailDesc.style.display = 'none';
            }
          }

          // WhatsApp direct
          if (shopDetailWaBtn) {
            shopDetailWaBtn.href = shop.whatsapp_url;
          }

          // Appel direct
          if (shopDetailCallBtn) {
            if (shop.call_url) {
              shopDetailCallBtn.href = shop.call_url;
              shopDetailCallBtn.style.display = 'inline-flex';
            } else {
              shopDetailCallBtn.style.display = 'none';
            }
          }

          // Nombre d'articles
          var explore = document.getElementById('shopDetailExplore');
          if (explore) explore.dataset.shopId = shop.id;
          if (shopDetailProductCount) {
            var count = data.product_count === undefined ? products.length : data.product_count;
            shopDetailProductCount.textContent = count + (count > 1 ? ' articles' : ' article');
          }

          // Grille des produits de la boutique
          if (shopDetailProductsGrid) {
            shopDetailProductsGrid.innerHTML = '';
            if (products.length > 0) {
              if (shopDetailEmpty) shopDetailEmpty.style.display = 'none';
              shopDetailProductsGrid.style.display = 'grid';

              var csrfToken = '';
              var csrfInput = document.querySelector('input[name="csrf_token"]');
              if (csrfInput) csrfToken = csrfInput.value;

              products.forEach(function (p) {
                if (!window.BMCatalog) return;
                shopDetailProductsGrid.appendChild(window.BMCatalog.createCard({
                  id: p.id, name: p.name, description: p.description, price: p.price,
                  final_price: p.final_price, has_promo: p.has_promo, stock: p.stock,
                  item_type: p.kind === 'service' ? 'service' : 'product', kind: p.kind,
                  image_url: p.image ? '/static/uploads/' + p.image : '',
                  url: '/shop/product/' + p.id, booking_url: '/booking/' + p.id,
                  available: shop.is_open && (p.kind === 'service' || p.stock > 0)
                }));
              });
            } else {
              shopDetailProductsGrid.style.display = 'none';
              if (shopDetailEmpty) shopDetailEmpty.style.display = 'block';
            }
          }

          if (shopDetailLoading) shopDetailLoading.style.display = 'none';
          if (shopDetailContent) shopDetailContent.style.display = 'block';
        })
        .catch(function () {
          if (requestId !== shopRequestId) return;
          if (shopDetailLoading) {
            shopDetailLoading.innerHTML = '<p style="color:#ef4444;font-weight:700;">Impossible de charger cette boutique.</p><button type="button" class="u-pdetail-back-btn" data-shop-close style="margin-top:0.8rem;">✕ Fermer</button>';
          }
        });
    }

    function closeShopDetailModal() {
      closeHubLayer('shop');
    }

    function closeProductDetailModal() {
      closeHubLayer('product');
    }

    // Actions Smart Cart Drawer
    if (cartDrawerBtnProceed) {
      cartDrawerBtnProceed.addEventListener('click', function (e) {
        e.preventDefault();
        setCartDrawerStep('checkout');
      });
    }

    if (cartDrawerBtnBackToStep1) {
      cartDrawerBtnBackToStep1.addEventListener('click', function (e) {
        e.preventDefault();
        setCartDrawerStep('cart');
      });
    }

    if (cartDrawerBtnModifyCart) {
      cartDrawerBtnModifyCart.addEventListener('click', function (e) {
        e.preventDefault();
        setCartDrawerStep('cart');
      });
    }

    if (cartDrawerClearBtn) {
      cartDrawerClearBtn.addEventListener('click', function (e) {
        e.preventDefault();
        if (confirm('Voulez-vous vraiment vider votre panier ?')) {
          clearCartItems();
        }
      });
    }

    // Gestion des clics délégués sur les boutons quantité et suppression
    document.addEventListener('click', function (e) {
      if (nativeLinkNavigation(e)) return;
      var actBtn = e.target.closest('[data-cart-action]');
      if (actBtn) {
        e.preventDefault();
        e.stopPropagation();
        var action = actBtn.getAttribute('data-cart-action');
        var pid = actBtn.getAttribute('data-pid');
        if (!pid || !currentCartData) return;

        var currentItem = (currentCartData.items || []).find(function (it) { return String(it.id) === String(pid); });
        var currentQty = currentItem ? currentItem.quantity : 1;

        if (action === 'increase') {
          updateCartItemQty(pid, currentQty + 1);
        } else if (action === 'decrease') {
          updateCartItemQty(pid, Math.max(0, currentQty - 1));
        } else if (action === 'remove') {
          removeCartItem(pid);
        }
      }

      // Clic WhatsApp vendeur pour enregistrer lead et mettre à jour le statut
      var waContactBtn = e.target.closest('[data-contact-shop-id]');
      if (waContactBtn) {
        var sId = waContactBtn.getAttribute('data-contact-shop-id');
        if (sId) {
          contactedVendors[sId] = true;
          waContactBtn.classList.add('is-contacted');
          waContactBtn.innerHTML = '<i class="bi bi-check2-circle"></i> WhatsApp ouvert';
          // Record contact via API
          fetch('/cart/whatsapp/contact/' + sId, {
            method: 'POST',
            headers: {
              'X-Requested-With': 'XMLHttpRequest',
              'X-CSRFToken': getCsrfToken()
            }
          }).catch(function () {});
          // Recompter après un court délai pour permettre au navigateur mobile d'ouvrir WhatsApp sans détruire le lien prématurément
          if (currentCartData) {
            setTimeout(function () {
              renderCartStep2(currentCartData);
            }, 350);
          }
        }
      }
    });


    // Clic pour ouvrir la visionneuse plein écran (Solution 3)
    if (pDetailImgWrap) {
      pDetailImgWrap.addEventListener('click', function (e) {
        if (e.target.closest('.u-pdetail-nav-arrow')) return;
        if (e.target.closest('video, .u-pdetail-video-main, .u-pdetail-badge-video')) return;
        if (activeGalleryItems[activeGalleryIndex] && activeGalleryItems[activeGalleryIndex].type === 'video') return;
        openLightbox(activeGalleryIndex);
      });
    }

    if (pDetailLightboxClose) {
      pDetailLightboxClose.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        closeLightbox();
      });
    }

    if (pDetailLightboxBackdrop) {
      pDetailLightboxBackdrop.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        closeLightbox();
      });
    }

    if (pDetailLightboxPrev) {
      pDetailLightboxPrev.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        updateLightboxImage(lightboxActiveIndex - 1);
      });
    }

    if (pDetailLightboxNext) {
      pDetailLightboxNext.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        updateLightboxImage(lightboxActiveIndex + 1);
      });
    }

    // Flèches de navigation de la galerie
    if (pDetailNavPrev) {
      pDetailNavPrev.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        updateGalleryImage(activeGalleryIndex - 1);
      });
    }

    if (pDetailNavNext) {
      pDetailNavNext.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        updateGalleryImage(activeGalleryIndex + 1);
      });
    }

    // Clic sur "Voir la boutique" dans la modale détail produit
    if (pDetailShopBtn) {
      pDetailShopBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var sSlug = pDetailShopBtn.getAttribute('data-open-shop-slug');
        if (sSlug) {
          openShopDetailModal(sSlug, 'product_detail');
        }
      });
    }

    // Clic sur "Retour" dans la modale boutique
    if (shopDetailBackBtn) {
      shopDetailBackBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        closeShopDetailModal();
      });
    }

    // Clic direct "Ajouter au panier" dans la modale détail
    if (pDetailBtnCart) {
      pDetailBtnCart.addEventListener('click', function (e) {
        e.preventDefault();
        if (!currentActiveProductId) return;
        addProductToCart(currentActiveProductId, pDetailBtnCart);
      });
    }

    // ========================================================
    // MOTEUR DE RECHERCHE ROBUSTE (0 RECHARGEMENT, RETOUR À ZÉRO GARANTI)
    // ========================================================
    var searchAbortController = null;

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function normalizeSearch(str) {
      if (!str) return '';
      return String(str).toLowerCase()
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .trim();
    }

    function syncClearButtons() {
      if (searchClearBtn) {
        searchClearBtn.style.display = (searchInput && searchInput.value.trim().length > 0) ? 'inline-flex' : 'none';
      }
      if (homeSearchClearBtn) {
        homeSearchClearBtn.style.display = (homeSearchInput && homeSearchInput.value.trim().length > 0) ? 'inline-flex' : 'none';
      }
      if (shopDetailSearchClearBtn) {
        shopDetailSearchClearBtn.style.display = (shopDetailSearchInput && shopDetailSearchInput.value.trim().length > 0) ? 'inline-flex' : 'none';
      }
    }

    // Réinitialisation absolue à zéro d'un univers ou de la recherche
    function resetUniverseSearch() {
      if (window.BMCatalog) window.BMCatalog.reset();
      syncClearButtons();
    }

    function showUniverseContent(universe, filterQuery, filters, scrollTop) {
      var delivery = universe === 'delivery';
      if (panel) {
        panel.dataset.universe = universe;
        panel.classList.toggle('is-explore-mode', isExploreMode);
        if (delivery) panel.setAttribute('aria-describedby', 'deliveryDescription');
        else panel.removeAttribute('aria-describedby');
      }
      if (countEl) countEl.hidden = delivery;
      var footer = document.getElementById('uModalFooter');
      if (footer) footer.hidden = delivery;
      if (bodyEl) bodyEl.hidden = delivery;
      var deliveryBody = document.getElementById('uDeliveryBody');
      if (deliveryBody) deliveryBody.hidden = !delivery;
      var toolbar = document.getElementById('catalogToolbar');
      if (toolbar) toolbar.hidden = delivery;
      var universes = document.getElementById('catalogUniverses');
      if (universes) {
        universes.hidden = !isExploreMode || delivery;
        universes.querySelectorAll('[data-catalog-universe]').forEach(function (button) {
          button.setAttribute('aria-pressed', String(button.getAttribute('data-catalog-universe') === universe));
        });
      }
      var searchBox = document.getElementById('uModalSearchBox');
      if (searchBox) searchBox.hidden = delivery;
      if (!delivery && window.BMCatalog) window.BMCatalog.open(universe, filterQuery || '', filters || {}, scrollTop);
      if (delivery && window.BMCatalog) window.BMCatalog.pause();
      syncClearButtons();
    }

    document.addEventListener('bm:catalog-state', function (event) {
      var state = event.detail;
      var entry = hubStack.find(function (item) { return item.kind === 'universe'; });
      if (!state || !entry || currentUniverse === 'delivery') return;
      entry.meta.query = state.query;
      entry.meta.filters = state.filters;
      if (searchInput && document.activeElement !== searchInput) searchInput.value = state.query;
      if (currentUniverse === 'search' && homeSearchInput) homeSearchInput.value = state.query;
      if (titleEl && currentUniverse === 'search') titleEl.textContent = state.query ? titles.search.title : 'Toutes les offres';
      syncClearButtons();
      saveHubHistory(false);
    });

    function submitHomeSearch() {
      var query = homeSearchInput ? homeSearchInput.value.trim() : '';
      if (!query) { if (homeSearchInput) homeSearchInput.focus(); return; }
      isExploreMode = true;
      openUniverseModal('search', query);
    }

    // Live suggestions keep focus in the header; submission opens the full catalogue.
    if (homeSearchInput) {
      homeSearchInput.addEventListener('input', function () {
        syncClearButtons();
      });

      homeSearchInput.addEventListener('search', function () {
        syncClearButtons();
        if (!homeSearchInput.value.trim()) {
          homeSearchInput.value = '';
          syncClearButtons();
        }
      });

      homeSearchInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.keyCode === 13) {
          e.preventDefault();
          e.stopPropagation();
          submitHomeSearch();
          return false;
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          homeSearchInput.value = '';
          syncClearButtons();
        }
      });
    }

    if (homeSearchClearBtn) {
      homeSearchClearBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        homeSearchInput.value = '';
        syncClearButtons();
        homeSearchInput.focus();
      });
    }

    if (homeSearchForm) {
      homeSearchForm.addEventListener('submit', function (e) {
        e.preventDefault();
        e.stopPropagation();
        submitHomeSearch();
        return false;
      });
    }

    // GESTION ROBUSTE DE LA RECHERCHE MODALE D'UNIVERS (0 ACTUALISATION)
    if (searchInput) {
      searchInput.addEventListener('input', function () {
        syncClearButtons();
        if (window.BMCatalog) window.BMCatalog.search(searchInput.value);
      });
      searchInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') { event.preventDefault(); if (window.BMCatalog) window.BMCatalog.search(searchInput.value); }
      });
    }
    if (searchClearBtn) searchClearBtn.addEventListener('click', function () {
      searchInput.value = '';
      if (window.BMCatalog) window.BMCatalog.search('');
      syncClearButtons(); searchInput.focus();
    });

    function resetShopDetailSearch() {
      if (shopDetailSearchInput) shopDetailSearchInput.value = '';
      syncClearButtons();
    }

    function exploreShopCatalog() {
      var explore = document.getElementById('shopDetailExplore');
      var shopId = explore && explore.dataset.shopId;
      var query = shopDetailSearchInput ? shopDetailSearchInput.value.trim() : '';
      if (shopId) openUniverseModal('search', query, { shop: shopId });
    }

    var shopSearchForm = document.getElementById('shopDetailSearchBox');
    if (shopSearchForm) shopSearchForm.addEventListener('submit', function (event) {
      event.preventDefault();
      exploreShopCatalog();
    });
    if (shopDetailSearchInput) {
      shopDetailSearchInput.addEventListener('input', syncClearButtons);
      shopDetailSearchInput.addEventListener('search', syncClearButtons);
    }

    if (shopDetailSearchClearBtn) {
      shopDetailSearchClearBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        resetShopDetailSearch();
        if (shopDetailSearchInput) shopDetailSearchInput.focus();
      });
    }

    // ========================================================
    // ÉCOUTEURS GLOBAUX EN MODE CAPTURE (INTERCEPTENT TOUT AVANT NAVIGATION)
    // ========================================================

    // Keep real links usable in a new tab while ordinary clicks use the panels.
    function nativeLinkNavigation(event) {
      var link = event.target && event.target.closest ? event.target.closest('a[href]') : null;
      if (!link) return false;
      return event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey ||
        link.hasAttribute('download') || (link.target && link.target.toLowerCase() !== '_self');
    }

    // Explicit homepage navigation and native universe buttons share the same handler.
    document.addEventListener('click', function (e) {
      if (nativeLinkNavigation(e)) return;
      var fullscreenBtn = e.target.closest('[data-modal-fullscreen]');
      if (fullscreenBtn) {
        e.preventDefault();
        e.stopPropagation();
        var targetPanel = fullscreenBtn.closest('.u-modal-panel');
        toggleModalFullscreen(targetPanel);
        return;
      }
      var homeLink = e.target.closest('[data-hub-home]');
      if (homeLink) {
        e.preventDefault();
        e.stopPropagation();
        returnHubHome();
        return;
      }
      var exploreLink = e.target.closest('[data-hub-explore]');
      if (exploreLink) {
        e.preventDefault();
        e.stopPropagation();
        var query = homeSearchInput ? homeSearchInput.value.trim() : '';
        isExploreMode = true;
        openUniverseModal('search', query);
        return;
      }
      var catalogUniverse = e.target.closest('[data-catalog-universe]');
      if (catalogUniverse) {
        e.preventDefault();
        e.stopPropagation();
        var nextUniverse = catalogUniverse.getAttribute('data-catalog-universe');
        if (nextUniverse === currentUniverse) return;
        var catalogQuery = searchInput ? searchInput.value.trim() : '';
        isExploreMode = true;
        openUniverseModal(nextUniverse, catalogQuery);
        catalogUniverse.focus({ preventScroll: true });
        return;
      }
      var card = e.target.closest('[data-open-universe]');
      if (card) {
        e.preventDefault();
        e.stopPropagation();
        var universe = card.getAttribute('data-open-universe');
        isExploreMode = (universe === 'search');
        openUniverseModal(universe);
      }
    }, true);

    // 1a. Intercepter TOUT clic vers le panier / checkout pour ouvrir le Smart Drawer en 0ms
    document.addEventListener('click', function (e) {
      if (nativeLinkNavigation(e)) return;
      var cartClose = e.target.closest('[data-cart-close]');
      if (cartClose) {
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') {
          e.stopImmediatePropagation();
        }
        closeCartDrawer();
        return;
      }

      var cartAddBtn = e.target.closest('[data-cart-add-btn]');
      if (cartAddBtn) {
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') {
          e.stopImmediatePropagation();
        }
        var pid = cartAddBtn.getAttribute('data-cart-add-btn');
        if (pid) {
          addProductToCart(pid, cartAddBtn);
        }
        return;
      }

      var cartTrigger = e.target.closest('.floating-cart, [data-open-cart], [data-cart-icon], a[href*="/cart"]');
      if (cartTrigger) {
        // Ignorer les boutons internes de la modale
        if (cartTrigger.closest('#cartDrawerPanel')) return;

        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') {
          e.stopImmediatePropagation();
        }
        var href = (cartTrigger.getAttribute('href') || '').toLowerCase();
        if (href.indexOf('checkout') !== -1 || cartTrigger.getAttribute('data-open-cart') === 'checkout') {
          openCartDrawer('checkout');
        } else {
          openCartDrawer('cart');
        }
        return;
      }
    }, true);


    // 1b. Clic pour ouvrir la modale Vitrine Boutique (Zero-reload)
    document.addEventListener('click', function (e) {
      if (nativeLinkNavigation(e)) return;
      var shopTrigger = e.target.closest('[data-open-shop-detail]');
      if (shopTrigger) {
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') {
          e.stopImmediatePropagation();
        }
        var sSlug = shopTrigger.getAttribute('data-open-shop-detail');
        if (sSlug) {
          openShopDetailModal(sSlug, 'universe_shops');
          return;
        }
      }

      var sCloseBtn = e.target.closest('[data-shop-close]');
      if (sCloseBtn) {
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') {
          e.stopImmediatePropagation();
        }
        closeShopDetailModal();
        return;
      }
    }, true);

    // 2. Clic pour ouvrir la modale Détail Produit (Quick-View)
    document.addEventListener('click', function (e) {
      if (nativeLinkNavigation(e)) return;
      // Vérifier si clic sur un élément déclencheur explicite
      var detailTarget = e.target.closest('[data-open-product-detail]');
      if (detailTarget) {
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') {
          e.stopImmediatePropagation();
        }
        var pid = detailTarget.getAttribute('data-open-product-detail');
        if (pid) {
          var fromShop = activeHubKind === 'shop' ? currentShopSlug : null;
          if (fromShop) {
            openProductDetailModal(pid, fromShop);
          } else {
            openProductDetailModal(pid);
          }
          return;
        }
      }

      // Ou clic sur la carte produit (hors formulaire panier / bouton panier)
      var itemCard = e.target.closest('.u-item-card');
      if (itemCard && !e.target.closest('.u-modal-cart-form, .u-btn-cart, input')) {
        var cardPid = itemCard.getAttribute('data-product-id') || itemCard.getAttribute('data-promo-id') || itemCard.getAttribute('data-service-id');
        if (cardPid) {
          e.preventDefault();
          e.stopPropagation();
          if (typeof e.stopImmediatePropagation === 'function') {
            e.stopImmediatePropagation();
          }
          var fromShopCard = activeHubKind === 'shop' ? currentShopSlug : null;
          if (fromShopCard) {
            openProductDetailModal(cardPid, fromShopCard);
          } else {
            openProductDetailModal(cardPid);
          }
          return;
        }
      }
    }, true);

    // 3. Clic pour fermer la modale Détail Produit
    document.addEventListener('click', function (e) {
      if (nativeLinkNavigation(e)) return;
      var pCloseBtn = e.target.closest('[data-pdetail-close]');
      if (pCloseBtn) {
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') {
          e.stopImmediatePropagation();
        }
        closeProductDetailModal();
      }
    }, true);

    // 4. Clic pour fermer la modale Univers
    document.addEventListener('click', function (e) {
      if (nativeLinkNavigation(e)) return;
      var closeBtn = e.target.closest('[data-u-modal-close]');
      if (closeBtn) {
        e.preventDefault();
        e.stopPropagation();
        closeUniverseModal();
      }
    }, true);

    // Escape, focus containment and native-equivalent keyboard activation.
    document.addEventListener('keydown', function (e) {
      lastInputType = 'keyboard';
      var top = hubStack.length ? hubStack[hubStack.length - 1] : null;
      if (top && e.key === 'Tab') {
        var layerNode = hubLayers[top.kind].node;
        var focusables = visibleHubFocusables(layerNode);
        var currentIndex = focusables.indexOf(document.activeElement);
        if (top.kind === 'universe' && currentUniverse === 'delivery' && focusables.length) {
          // Safari can skip links in its native Tab order; keep both delivery actions reachable.
          e.preventDefault();
          var nextIndex = currentIndex < 0 ? (e.shiftKey ? focusables.length - 1 : 0) :
            (currentIndex + (e.shiftKey ? -1 : 1) + focusables.length) % focusables.length;
          focusHubElement(focusables[nextIndex]);
        } else if (!focusables.length) {
          e.preventDefault();
          focusHubElement(layerNode);
        } else if (e.shiftKey && currentIndex <= 0) {
          e.preventDefault();
          focusHubElement(focusables[focusables.length - 1]);
        } else if (!e.shiftKey && (currentIndex === -1 || currentIndex === focusables.length - 1)) {
          e.preventDefault();
          focusHubElement(focusables[0]);
        }
        return;
      }
      if (top && e.key === 'Escape') {
        var topNode = hubLayers[top.kind] && hubLayers[top.kind].node;
        if (topNode && topNode.classList.contains('is-fullscreen')) {
          e.preventDefault();
          e.stopImmediatePropagation();
          resetModalFullscreen(topNode);
          return;
        }
        e.preventDefault();
        e.stopImmediatePropagation();
        closeHubLayer(top.kind);
        return;
      }
      if (top && top.kind === 'lightbox' && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
        e.preventDefault();
        updateLightboxImage(lightboxActiveIndex + (e.key === 'ArrowLeft' ? -1 : 1));
        return;
      }
      var universeControl = e.target.closest ? e.target.closest('[data-open-universe]') : null;
      if (universeControl && !/^(BUTTON|A|INPUT)$/.test(universeControl.tagName) && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        universeControl.click();
      }
    }, true);


    // Ajout au panier dans la modale d'univers
    document.addEventListener('submit', function (e) {
      var form = e.target.closest('.u-modal-cart-form');
      if (form) {
        e.preventDefault();
        var btn = form.querySelector('button');
        var pid = (form.action.match(/\/cart\/add\/(\d+)/) || [])[1];
        if (pid) addProductToCart(pid, btn, form);
      }
    });

    // ========================================================
    // OUVERTURE AUTOMATIQUE VIA PARAMÈTRES URL
    // ========================================================
    var shopExplore = document.getElementById('shopDetailExplore');
    if (shopExplore) shopExplore.addEventListener('click', exploreShopCatalog);

    try {
      var urlParams = initialHubParams;
      var queryParam = urlParams.get('q');
      if (queryParam) {
        if (homeSearchInput) homeSearchInput.value = queryParam;
      }
      var autoOpen = urlParams.get('open');
      if (autoOpen && titles[autoOpen]) {
        isExploreMode = (autoOpen === 'search');
        openUniverseModal(autoOpen, queryParam || '', Object.fromEntries(urlParams));
      } else if (autoOpen === 'cart' || autoOpen === 'checkout') {
        openCartDrawer(autoOpen);
      } else if (!autoOpen && queryParam) {
        isExploreMode = true;
        openUniverseModal('search', queryParam, Object.fromEntries(urlParams));
      }
      var autoShop = urlParams.get('sdetail') || (autoOpen === 'shop' ? urlParams.get('slug') : null);
      if (autoShop) openShopDetailModal(autoShop, 'homepage');
      var autoProduct = urlParams.get('pdetail') || document.body.dataset.initialProductId;
      if (autoProduct) openProductDetailModal(autoProduct, autoShop || null);
      syncClearButtons();
    } catch (err) {}

    // Préchargement immédiat et silencieux du panier au lancement de la page (0ms au clic !)
    loadAndRenderCartData(false);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSingleHub, { once: true });
  } else {
    initSingleHub();
  }
})();
