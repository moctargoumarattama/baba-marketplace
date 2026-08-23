(function () {
  "use strict";

  if (window.__BM_PAGE_LOADER_INIT__) return;
  window.__BM_PAGE_LOADER_INIT__ = true;

  if (window.__BM_DISABLE_PAGE_LOADER__ === true) {
    // eslint-disable-next-line no-console
    console.info("[page_loader] disabled by window.__BM_DISABLE_PAGE_LOADER__");
    return;
  }

  var SHARED = {
    coreCart: "js/core/core_cart.js",
    coreLive: "js/core/core_live.js",
    liveShim: "js/live.js",
    ajaxPagination: "js/ajax_pagination.js",
    featurePagination: "js/ajax/features/pagination.js",
    featureForms: "js/ajax/features/forms.js",
    featurePolling: "js/ajax/features/polling.js",
    adminTable: "js/admin/admin_table.js",
    adminForms: "js/admin/admin_forms.js",
  };

  var ADMIN_STACK = [
    SHARED.coreLive,
    SHARED.liveShim,
    SHARED.featurePagination,
    SHARED.featureForms,
    SHARED.featurePolling,
    SHARED.adminTable,
    SHARED.adminForms,
  ];

  var VENDOR_STACK = [
    SHARED.coreLive,
    SHARED.liveShim,
    SHARED.ajaxPagination,
    SHARED.featurePagination,
    SHARED.featureForms,
    SHARED.featurePolling,
  ];

  var PAGE_SCRIPT_MAP = {
    "shop.home": [
      SHARED.coreCart,
      SHARED.coreLive,
      SHARED.liveShim,
      SHARED.ajaxPagination,
      SHARED.featurePagination,
      SHARED.featureForms,
      SHARED.featurePolling,
    ],
    global_search: [
      SHARED.coreCart,
      SHARED.coreLive,
      SHARED.liveShim,
      SHARED.ajaxPagination,
      SHARED.featurePagination,
      SHARED.featureForms,
    ],
    "shops.list_shops": [
      SHARED.coreCart,
      SHARED.coreLive,
      SHARED.liveShim,
      SHARED.ajaxPagination,
      SHARED.featurePagination,
      SHARED.featureForms,
    ],
    "shop.shop_detail": [
      SHARED.coreCart,
      SHARED.coreLive,
      SHARED.liveShim,
      SHARED.ajaxPagination,
      SHARED.featurePagination,
      SHARED.featureForms,
      SHARED.featurePolling,
    ],
    "shop.product_detail": [
      SHARED.coreCart,
      SHARED.coreLive,
      SHARED.liveShim,
      SHARED.featureForms,
    ],
    "cart.view": [SHARED.coreCart, SHARED.coreLive, SHARED.liveShim, SHARED.featureForms],
    "cart.checkout": [SHARED.coreCart, SHARED.coreLive, SHARED.liveShim, SHARED.featureForms],
    "vendor.dashboard": VENDOR_STACK,
    "vendor.earnings": VENDOR_STACK,
    "vendor.manage_shop": [SHARED.coreLive, SHARED.liveShim, SHARED.featureForms],
    "vendor.product_new": [SHARED.coreLive, SHARED.liveShim, SHARED.featureForms],
    "vendor.product_edit": [SHARED.coreLive, SHARED.liveShim, SHARED.featureForms],
    "admin.product_contacts": ADMIN_STACK,
    "admin_users.fraud_monitor": ADMIN_STACK,
    "admin_users.catalog_quality": ADMIN_STACK,
    "admin_users.reconciliation": ADMIN_STACK,
    "admin_users.manage_shops": ADMIN_STACK,
    "admin_users.manage_users": ADMIN_STACK,
    "admin_users.view_logs": ADMIN_STACK,
    "admin_categories.index": ADMIN_STACK,
    "rentals.admin_locations": ADMIN_STACK,
  };

  var ADM_PAGE_SCRIPT_MAP = {
    deliveries: ADMIN_STACK,
    fraud: ADMIN_STACK,
    shops: ADMIN_STACK,
    users: ADMIN_STACK,
    admin_locations: ADMIN_STACK,
    categories: ADMIN_STACK,
    logs: ADMIN_STACK,
    catalog_quality: ADMIN_STACK,
    reconciliation: ADMIN_STACK,
  };

  function normalize(value) {
    return String(value || "").trim().toLowerCase();
  }

  function pushAssets(target, assets) {
    if (!Array.isArray(assets)) return;
    assets.forEach(function (asset) {
      if (!asset) return;
      if (target.indexOf(asset) === -1) {
        target.push(asset);
      }
    });
  }

  function collectHintAssets(ctx, list) {
    var hasAjaxForms = !!document.querySelector('form[data-ajax="true"], form[data-adm-ajax="1"], [data-adm-action="post"]');
    var hasAjaxPagination = !!document.querySelector('[data-ajax-pagination], [data-ajax-listing], [data-adm-pager], [data-adm-listing]');
    var hasPollingHint = !!document.querySelector('[data-live], [data-orders-live-url], [data-notify-url], [data-track-poll]');
    var hasCartHint = !!document.querySelector('[data-nav-badges], [data-cart-badge], [data-drawer-cart-badge], [data-track-badge], [data-track-icon]');

    if (!ctx.isAdmin && !ctx.isVendor && hasCartHint) {
      pushAssets(list, [SHARED.coreCart]);
    }
    if (hasAjaxForms || hasPollingHint) {
      pushAssets(list, [SHARED.coreLive, SHARED.liveShim, SHARED.featureForms]);
    }
    if (hasAjaxPagination) {
      pushAssets(list, [SHARED.ajaxPagination, SHARED.featurePagination]);
    }
    if (hasPollingHint) {
      pushAssets(list, [SHARED.featurePolling]);
    }
  }

  function getContext() {
    var body = document.body;
    var pageId = normalize(body && body.dataset ? body.dataset.page : "");
    var admPageId = normalize(body && body.dataset ? body.dataset.admPage : "");
    var path = normalize(window.location && window.location.pathname ? window.location.pathname : "");
    var isAdmin = !!(body && body.dataset && body.dataset.admin === "1");
    var isVendor = pageId.indexOf("vendor.") === 0 || path.indexOf("/vendor") === 0;

    return {
      body: body,
      pageId: pageId,
      admPageId: admPageId,
      path: path,
      isAdmin: isAdmin,
      isVendor: isVendor,
    };
  }

  function resolveAssets(ctx) {
    var list = [];

    pushAssets(list, PAGE_SCRIPT_MAP[ctx.pageId]);
    pushAssets(list, ADM_PAGE_SCRIPT_MAP[ctx.admPageId]);

    if (!list.length && ctx.isVendor) {
      pushAssets(list, VENDOR_STACK);
    }

    collectHintAssets(ctx, list);
    return list;
  }

  function getStaticRoot(ctx) {
    var root = (ctx.body && ctx.body.dataset && ctx.body.dataset.staticRoot) || "/static/";
    root = String(root || "/static/");
    if (!root.endsWith("/")) root += "/";
    return root;
  }

  function getVersion(ctx) {
    if (ctx.body && ctx.body.dataset && ctx.body.dataset.staticVersion) {
      return String(ctx.body.dataset.staticVersion);
    }
    if (window.BM_APP_STATIC_VERSION != null) {
      return String(window.BM_APP_STATIC_VERSION);
    }
    return "";
  }

  function buildUrl(ctx, assetPath) {
    var rel = String(assetPath || "").replace(/^\/+/, "");
    var base = getStaticRoot(ctx) + rel;
    var version = getVersion(ctx);
    if (!version) return base;
    return base + (base.indexOf("?") >= 0 ? "&" : "?") + "v=" + encodeURIComponent(version);
  }

  function hasScriptFor(assetPath) {
    var rel = String(assetPath || "").replace(/^\/+/, "");
    var escaped = rel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    var matcher = new RegExp("/" + escaped + "(?:\\?|$)");
    var scripts = document.querySelectorAll("script[src]");
    for (var i = 0; i < scripts.length; i += 1) {
      var src = String(scripts[i].getAttribute("src") || "");
      if (matcher.test(src)) return true;
    }
    return false;
  }

  function loadScript(ctx, assetPath) {
    return new Promise(function (resolve) {
      if (!assetPath || hasScriptFor(assetPath)) {
        resolve({ ok: true, skipped: true, asset: assetPath });
        return;
      }

      var key = String(assetPath);
      var loadedSet = window.__BM_PAGE_LOADER_ASSETS__;
      if (!(loadedSet instanceof Set)) {
        loadedSet = new Set();
        window.__BM_PAGE_LOADER_ASSETS__ = loadedSet;
      }
      if (loadedSet.has(key)) {
        resolve({ ok: true, skipped: true, asset: assetPath });
        return;
      }

      var el = document.createElement("script");
      el.src = buildUrl(ctx, assetPath);
      el.defer = true;
      el.async = false;
      el.onload = function () {
        loadedSet.add(key);
        resolve({ ok: true, asset: assetPath });
      };
      el.onerror = function () {
        // eslint-disable-next-line no-console
        console.warn("[page_loader] failed to load", assetPath);
        resolve({ ok: false, asset: assetPath });
      };
      document.head.appendChild(el);
    });
  }

  async function loadAssetsSequentially(ctx, assets) {
    for (var i = 0; i < assets.length; i += 1) {
      // eslint-disable-next-line no-await-in-loop
      await loadScript(ctx, assets[i]);
    }
  }

  function init() {
    var ctx = getContext();
    if (!ctx.body) return;

    var assets = resolveAssets(ctx);
    if (!assets.length) {
      // eslint-disable-next-line no-console
      console.info("[page_loader] no dynamic assets for page", ctx.pageId || "(unknown)");
      return;
    }

    loadAssetsSequentially(ctx, assets).catch(function () {
      // eslint-disable-next-line no-console
      console.warn("[page_loader] load sequence failed");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("readystatechange", function onReadyStateChange() {
      if (document.readyState === "loading") return;
      document.removeEventListener("readystatechange", onReadyStateChange);
      init();
    });
  } else {
    init();
  }
})();


