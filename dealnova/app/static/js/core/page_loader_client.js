(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_PAGE_LOADER_CLIENT_INIT__) return;
  window.__BM_PAGE_LOADER_CLIENT_INIT__ = true;

  var perfFlags = window.BM_PERF_FLAGS || {};
  var parallelPageLoaderEnabled = perfFlags.parallelPageLoader !== false;

  if (window.__BM_DISABLE_PAGE_LOADER__ === true) {
    // eslint-disable-next-line no-console
    console.info("[page_loader_client] disabled");
    document.dispatchEvent(
      new CustomEvent("bm:page-interactive", {
        detail: { disabled: true }
      })
    );
    return;
  }

  var ASSETS = {
    coreCart: "js/core/core_cart.js",
    coreLive: "js/core/core_live.js",
    liveShim: "js/live.js",
    ajaxPagination: "js/ajax_pagination.js",
    featurePagination: "js/ajax/features/pagination.js",
    featureForms: "js/ajax/features/forms.js",
    featurePolling: "js/ajax/features/polling.js",
    shopHomePage: "js/pages/shop_home_page.js",
    shopsPage: "js/shops_page.js",
    checkoutPage: "js/pages/checkout_page.js",
    deliveryPricing: "js/delivery_pricing.js",
    locationsIndexPage: "js/pages/locations_index_page.js"
  };

  var CLIENT_MAP = {
    shop_home: [ASSETS.coreCart, ASSETS.ajaxPagination, ASSETS.shopHomePage],
    checkout: [ASSETS.coreCart, ASSETS.deliveryPricing, ASSETS.checkoutPage],
    shops: [ASSETS.coreCart, ASSETS.ajaxPagination, ASSETS.shopsPage],
    locations_index: [ASSETS.coreCart, ASSETS.ajaxPagination, ASSETS.locationsIndexPage],

    // Compatibility aliases if templates still expose endpoint-like page ids.
    "shop.home": [ASSETS.coreCart, ASSETS.ajaxPagination, ASSETS.shopHomePage],
    "cart.checkout": [ASSETS.coreCart, ASSETS.deliveryPricing, ASSETS.checkoutPage],
    "shops.list_shops": [ASSETS.coreCart, ASSETS.ajaxPagination, ASSETS.shopsPage],
    "rentals.locations_home": [ASSETS.coreCart, ASSETS.ajaxPagination, ASSETS.locationsIndexPage]
  };

  var VENDOR_RUNTIME = [
    ASSETS.coreLive,
    ASSETS.liveShim,
    ASSETS.ajaxPagination,
    ASSETS.featurePagination,
    ASSETS.featureForms,
    ASSETS.featurePolling
  ];

  var VENDOR_MAP = {
    "vendor.dashboard": VENDOR_RUNTIME,
    "vendor.earnings": VENDOR_RUNTIME,
    "vendor.periods": VENDOR_RUNTIME,
    "vendor.manage_shop": [ASSETS.coreLive, ASSETS.liveShim, ASSETS.featureForms],
    "vendor.product_new": [ASSETS.coreLive, ASSETS.liveShim, ASSETS.featureForms],
    "vendor.product_edit": [ASSETS.coreLive, ASSETS.liveShim, ASSETS.featureForms],
    "vendor.security": [ASSETS.coreLive, ASSETS.liveShim, ASSETS.featureForms]
  };

  var LOAD_PLANS = {
    shop_home: [[ASSETS.shopHomePage, ASSETS.coreCart, ASSETS.ajaxPagination]],
    "shop.home": [[ASSETS.shopHomePage, ASSETS.coreCart, ASSETS.ajaxPagination]],
    shops: [[ASSETS.shopsPage, ASSETS.coreCart, ASSETS.ajaxPagination]],
    "shops.list_shops": [[ASSETS.shopsPage, ASSETS.coreCart, ASSETS.ajaxPagination]],
    locations_index: [[ASSETS.locationsIndexPage, ASSETS.coreCart, ASSETS.ajaxPagination]],
    "rentals.locations_home": [[ASSETS.locationsIndexPage, ASSETS.coreCart, ASSETS.ajaxPagination]],
    checkout: [[ASSETS.deliveryPricing, ASSETS.coreCart], [ASSETS.checkoutPage]],
    "cart.checkout": [[ASSETS.deliveryPricing, ASSETS.coreCart], [ASSETS.checkoutPage]],
    "vendor.dashboard": [[ASSETS.coreLive], [ASSETS.liveShim, ASSETS.ajaxPagination, ASSETS.featurePagination, ASSETS.featureForms, ASSETS.featurePolling]],
    "vendor.earnings": [[ASSETS.coreLive], [ASSETS.liveShim, ASSETS.ajaxPagination, ASSETS.featurePagination, ASSETS.featureForms, ASSETS.featurePolling]],
    "vendor.periods": [[ASSETS.coreLive], [ASSETS.liveShim, ASSETS.ajaxPagination, ASSETS.featurePagination, ASSETS.featureForms, ASSETS.featurePolling]],
    "vendor.manage_shop": [[ASSETS.coreLive], [ASSETS.liveShim, ASSETS.featureForms]],
    "vendor.product_new": [[ASSETS.coreLive], [ASSETS.liveShim, ASSETS.featureForms]],
    "vendor.product_edit": [[ASSETS.coreLive], [ASSETS.liveShim, ASSETS.featureForms]],
    "vendor.security": [[ASSETS.coreLive], [ASSETS.liveShim, ASSETS.featureForms]]
  };

  var QUIET_PAGES = new Set([
    "rentals.owner_location_new",
    "rentals.owner_location_edit"
  ]);

  function normalize(value) {
    return String(value || "").trim().toLowerCase();
  }

  function getBody() {
    return document.body || null;
  }

  function getPageId() {
    var body = getBody();
    if (!body || !body.dataset) return "";
    return normalize(body.dataset.page);
  }

  function getStaticRoot() {
    var body = getBody();
    var root = body && body.dataset ? body.dataset.staticRoot : "";
    var value = String(root || "/static/");
    if (!value.endsWith("/")) value += "/";
    return value;
  }

  function getStaticVersion() {
    var body = getBody();
    if (body && body.dataset && body.dataset.staticVersion) {
      return String(body.dataset.staticVersion);
    }
    if (typeof window.BM_APP_STATIC_VERSION !== "undefined" && window.BM_APP_STATIC_VERSION !== null) {
      return String(window.BM_APP_STATIC_VERSION);
    }
    return "";
  }

  function buildAssetUrl(path) {
    var rel = String(path || "").replace(/^\/+/, "");
    var url = getStaticRoot() + rel;
    var version = getStaticVersion();
    if (!version) return url;
    return url + (url.indexOf("?") >= 0 ? "&" : "?") + "v=" + encodeURIComponent(version);
  }

  function pathRegex(path) {
    var escaped = String(path || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp("/" + escaped + "(?:\\?|$)");
  }

  function hasScript(path) {
    var matcher = pathRegex(path);
    var scripts = document.querySelectorAll("script[src]");
    for (var i = 0; i < scripts.length; i += 1) {
      var src = String(scripts[i].getAttribute("src") || "");
      if (matcher.test(src)) return true;
    }
    return false;
  }

  function pushUnique(list, assets) {
    if (!Array.isArray(assets)) return;
    for (var i = 0; i < assets.length; i += 1) {
      var asset = assets[i];
      if (!asset) continue;
      if (list.indexOf(asset) === -1) {
        list.push(asset);
      }
    }
  }

  function resolveAssets(pageId) {
    var assets = [];
    var explicit = false;

    if (CLIENT_MAP[pageId]) {
      pushUnique(assets, CLIENT_MAP[pageId]);
      explicit = true;
    } else if (VENDOR_MAP[pageId]) {
      pushUnique(assets, VENDOR_MAP[pageId]);
      explicit = true;
    }

    if (explicit) return assets;

    // Compatibility fallback for non-target client pages.
    if (document.querySelector('[data-nav-badges], [data-cart-badge], [data-drawer-cart-badge], [data-track-badge], [data-track-icon]')) {
      pushUnique(assets, [ASSETS.coreCart]);
    }

    if (document.querySelector('[data-ajax-pagination], [data-ajax-listing], [data-adm-pager], [data-adm-listing]')) {
      pushUnique(assets, [ASSETS.ajaxPagination, ASSETS.featurePagination]);
    }

    if (document.querySelector('form[data-ajax="true"], form[data-adm-ajax="1"], [data-adm-action="post"]')) {
      pushUnique(assets, [ASSETS.coreLive, ASSETS.liveShim, ASSETS.featureForms]);
    }

    if (document.querySelector('[data-live], [data-orders-live-url], [data-notify-url], [data-track-poll]')) {
      pushUnique(assets, [ASSETS.featurePolling]);
    }

    return assets;
  }

  function ensureLoadedSet() {
    if (!(window.__BM_PAGE_LOADER_CLIENT_ASSETS__ instanceof Set)) {
      window.__BM_PAGE_LOADER_CLIENT_ASSETS__ = new Set();
    }
    return window.__BM_PAGE_LOADER_CLIENT_ASSETS__;
  }

  function loadScript(path) {
    return new Promise(function (resolve) {
      if (!path || hasScript(path)) {
        resolve({ ok: true, skipped: true, path: path });
        return;
      }

      var loaded = ensureLoadedSet();
      if (loaded.has(path)) {
        resolve({ ok: true, skipped: true, path: path });
        return;
      }

      var script = document.createElement("script");
      script.src = buildAssetUrl(path);
      script.defer = true;
      script.async = false;
      script.onload = function () {
        loaded.add(path);
        resolve({ ok: true, path: path });
      };
      script.onerror = function () {
        // eslint-disable-next-line no-console
        console.warn("[page_loader_client] failed", path);
        resolve({ ok: false, path: path });
      };
      document.head.appendChild(script);
    });
  }

  async function loadSequentially(paths) {
    for (var i = 0; i < paths.length; i += 1) {
      // eslint-disable-next-line no-await-in-loop
      await loadScript(paths[i]);
    }
  }

  function resolveLoadPlan(pageId, assets) {
    var assetList = Array.isArray(assets) ? assets.slice() : [];
    if (!assetList.length) return [];

    var assetSet = new Set(assetList);
    var explicitPlan = LOAD_PLANS[pageId];
    if (Array.isArray(explicitPlan) && explicitPlan.length) {
      return explicitPlan
        .map(function (phase) {
          return (Array.isArray(phase) ? phase : []).filter(function (asset) {
            return assetSet.has(asset);
          });
        })
        .filter(function (phase) {
          return Array.isArray(phase) && phase.length > 0;
        });
    }

    return [assetList];
  }

  function loadPhase(paths) {
    var phaseAssets = Array.isArray(paths) ? paths.filter(Boolean) : [];
    if (!phaseAssets.length) return Promise.resolve([]);
    return Promise.all(
      phaseAssets.map(function (path) {
        return loadScript(path);
      })
    );
  }

  function loadPlannedAssets(pageId, assets) {
    var phases = resolveLoadPlan(pageId, assets);
    if (!phases.length) return Promise.resolve([]);

    if (!parallelPageLoaderEnabled) {
      return loadSequentially(Array.isArray(assets) ? assets.slice() : []);
    }

    return phases.reduce(function (chain, phase) {
      return chain.then(function () {
        return loadPhase(phase);
      });
    }, Promise.resolve([]));
  }

  function markPageInteractive(detail) {
    if (window.__BM_PAGE_INTERACTIVE_MARKED__ === true) return;
    window.__BM_PAGE_INTERACTIVE_MARKED__ = true;

    var body = getBody();
    if (body && body.dataset) {
      body.dataset.pageInteractive = "1";
    }
    document.documentElement.setAttribute("data-bm-page-interactive", "1");
    document.dispatchEvent(
      new CustomEvent("bm:page-interactive", {
        detail: detail || {}
      })
    );
  }

  function supportsPrefetchNetwork() {
    try {
      var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
      if (!conn) return true;
      if (conn.saveData) return false;
      var type = String(conn.effectiveType || "").toLowerCase();
      if (type === "2g" || type === "slow-2g" || type === "3g") return false;
    } catch (_error) {}
    return true;
  }

  function normalizePrefetchUrl(url) {
    if (!url) return "";
    try {
      var parsed = new URL(String(url), window.location.href);
      if (parsed.origin !== window.location.origin) return "";
      parsed.hash = "";
      return parsed.toString();
    } catch (_error) {
      return "";
    }
  }

  function getPrefetchStore() {
    if (!(window.__BM_INTENT_PREFETCH_DONE__ instanceof Set)) {
      window.__BM_INTENT_PREFETCH_DONE__ = new Set();
    }
    if (!(window.__BM_INTENT_PREFETCH_INFLIGHT__ instanceof Map)) {
      window.__BM_INTENT_PREFETCH_INFLIGHT__ = new Map();
    }
    return {
      done: window.__BM_INTENT_PREFETCH_DONE__,
      inflight: window.__BM_INTENT_PREFETCH_INFLIGHT__
    };
  }

  function prefetchUrl(url, options) {
    var normalizedUrl = normalizePrefetchUrl(url);
    if (!normalizedUrl || !supportsPrefetchNetwork()) {
      return Promise.resolve({ ok: false, skipped: true, url: normalizedUrl || String(url || "") });
    }

    var store = getPrefetchStore();
    if (store.done.has(normalizedUrl)) {
      return Promise.resolve({ ok: true, skipped: true, url: normalizedUrl });
    }
    if (store.inflight.has(normalizedUrl)) {
      return store.inflight.get(normalizedUrl);
    }

    var config = options || {};
    var headers = Object.assign(
      {
        "X-Requested-With": "prefetch"
      },
      config.headers || {}
    );

    var requestPromise = fetch(normalizedUrl, {
      method: "GET",
      credentials: "same-origin",
      cache: "force-cache",
      mode: "same-origin",
      headers: headers
    })
      .then(function (response) {
        if (response && response.ok) {
          store.done.add(normalizedUrl);
        }
        return { ok: !!(response && response.ok), status: response ? response.status : 0, url: normalizedUrl };
      })
      .catch(function () {
        return { ok: false, status: 0, url: normalizedUrl };
      })
      .finally(function () {
        store.inflight.delete(normalizedUrl);
      });

    store.inflight.set(normalizedUrl, requestPromise);
    return requestPromise;
  }

  function runIdle(task, timeoutMs) {
    var safeTask = typeof task === "function" ? task : function () {};
    if (typeof window.requestIdleCallback === "function") {
      window.requestIdleCallback(
        function () {
          safeTask();
        },
        { timeout: Math.max(200, Number(timeoutMs) || 1200) }
      );
      return;
    }
    window.setTimeout(safeTask, 180);
  }

  function prefetchIdle(urls, options) {
    if (!Array.isArray(urls) || !urls.length) return;
    runIdle(function () {
      urls.forEach(function (url) {
        prefetchUrl(url, options || {});
      });
    }, options && options.timeoutMs);
  }

  function prefetchOnIntent(root, selector, options) {
    if (!selector || !supportsPrefetchNetwork()) return;
    var scope = root && root.querySelectorAll ? root : document;
    var nodes = scope.querySelectorAll(selector);
    if (!nodes || !nodes.length) return;
    var config = options || {};

    function bindNode(node) {
      if (!node || node.dataset.bmPrefetchBound === "1") return;
      node.dataset.bmPrefetchBound = "1";
      var href = String(node.getAttribute("href") || "").trim();
      if (!href) return;

      var trigger = function () {
        prefetchUrl(href, config);
      };

      node.addEventListener("pointerenter", trigger, { passive: true });
      node.addEventListener("focus", trigger, { passive: true });
      node.addEventListener(
        "touchstart",
        function () {
          runIdle(trigger, 600);
        },
        { passive: true }
      );
    }

    nodes.forEach(bindNode);
  }

  window.BMIntentPrefetch = window.BMIntentPrefetch || {};
  window.BMIntentPrefetch.prefetchUrl = prefetchUrl;
  window.BMIntentPrefetch.prefetchIdle = prefetchIdle;
  window.BMIntentPrefetch.prefetchOnIntent = prefetchOnIntent;
  window.BMIntentPrefetch.runIdle = runIdle;

  function init() {
    var body = getBody();
    if (!body) return;

    // Never own admin shell loading here.
    if (body.dataset && body.dataset.admin === "1") return;

    var pageId = getPageId();
    var assets = resolveAssets(pageId);
    if (!assets.length) {
      if (QUIET_PAGES.has(pageId)) {
        markPageInteractive({ pageId: pageId, assets: [], mapped: true, inline: true });
        return;
      }
      // eslint-disable-next-line no-console
      console.info("[page_loader_client] page not mapped", pageId || "(empty)");
      markPageInteractive({ pageId: pageId, assets: [], mapped: false });
      return;
    }

    loadPlannedAssets(pageId, assets)
      .catch(function () {
      // eslint-disable-next-line no-console
      console.warn("[page_loader_client] load error");
      })
      .finally(function () {
        markPageInteractive({
          pageId: pageId,
          assets: assets.slice(),
          parallel: parallelPageLoaderEnabled
        });
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();

