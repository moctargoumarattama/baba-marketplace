(function () {
  "use strict";

  if (typeof window === "undefined") return;

  const existing = window.VendorUI || {};
  if (existing.__loaded) {
    if (typeof existing.initOnce === "function") existing.initOnce();
    return;
  }

  const pollers = new Map();
  const SCROLL_KEY_PREFIX = "bm:vendor:scroll:";

  function getScrollKey() {
    const path = window.location && window.location.pathname ? window.location.pathname : "";
    const search = window.location && window.location.search ? window.location.search : "";
    return SCROLL_KEY_PREFIX + path + search;
  }

  function rememberScrollPosition() {
    try {
      if (!window.sessionStorage) return;
      const y = Math.max(0, Number(window.scrollY || window.pageYOffset || 0));
      window.sessionStorage.setItem(getScrollKey(), String(y));
    } catch (_error) {}
  }

  function restoreScrollPosition() {
    try {
      if (!window.sessionStorage) return;
      const raw = window.sessionStorage.getItem(getScrollKey());
      if (raw == null) return;
      window.sessionStorage.removeItem(getScrollKey());
      const y = Number(raw);
      if (!Number.isFinite(y) || y < 0) return;
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(function () {
          window.scrollTo(0, y);
        });
      });
    } catch (_error) {}
  }

  function bindScrollMemory() {
    if (window.__BM_VENDOR_SCROLL_MEMORY_BOUND__) return;
    window.__BM_VENDOR_SCROLL_MEMORY_BOUND__ = true;

    restoreScrollPosition();

    window.addEventListener("beforeunload", rememberScrollPosition, { passive: true });

    document.addEventListener(
      "submit",
      function (event) {
        const form = event.target;
        if (!form || form.dataset.ajax === "true" || form.dataset.preserveScroll === "off") return;
        rememberScrollPosition();
      },
      true
    );

    document.addEventListener(
      "click",
      function (event) {
        const anchor = event.target && event.target.closest ? event.target.closest("a[href]") : null;
        if (!anchor) return;
        if (anchor.dataset.preserveScroll === "off") return;
        if (anchor.target && anchor.target !== "_self") return;
        const href = String(anchor.getAttribute("href") || "").trim();
        if (!href || href.startsWith("#") || href.startsWith("javascript:") || href.startsWith("mailto:") || href.startsWith("tel:")) return;
        if (event.defaultPrevented) return;
        let nextUrl;
        try {
          nextUrl = new URL(href, window.location.href);
        } catch (_error) {
          return;
        }
        if (nextUrl.origin !== window.location.origin) return;
        rememberScrollPosition();
      },
      true
    );
  }

  function initOnce() {
    if (window.__BM_VENDOR_INIT__) return false;
    window.__BM_VENDOR_INIT__ = true;
    return true;
  }

  function parsePageConfig(nodeId, defaults) {
    const fallback = defaults && typeof defaults === "object" ? defaults : {};
    if (!nodeId) return fallback;

    const node = document.getElementById(String(nodeId));
    if (!node) return fallback;

    try {
      const parsed = JSON.parse(node.textContent || "{}");
      if (!parsed || typeof parsed !== "object") return fallback;
      return Object.assign({}, fallback, parsed);
    } catch (_error) {
      return fallback;
    }
  }

  function markFieldInvalid(node, options) {
    if (!node || !node.style) return;

    const cfg = options || {};
    const color = String(cfg.color || "#ef4444");
    const durationMs = Math.max(200, Number(cfg.durationMs || 1800));

    node.style.borderColor = color;
    window.setTimeout(function () {
      node.style.borderColor = "";
    }, durationMs);
  }

  function toast(message, type) {
    const ui = window.BMCoreUI || {};
    if (ui && typeof ui.showToast === "function") {
      ui.showToast(String(message || ""), type || "success");
      return;
    }
    if (message) {
      try {
        window.alert(String(message));
      } catch (_error) {}
    }
  }

  function setLoadingState(node, active, className) {
    if (!node || !node.classList) return;
    node.classList.toggle(className || "active", !!active);
  }

  function bindConfirmForms(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("form[data-confirm]").forEach(function (form) {
      if (form.dataset.vendorConfirmBound === "1") return;
      form.dataset.vendorConfirmBound = "1";
      form.addEventListener("submit", function (event) {
        const message = form.dataset.confirm || "Confirmer ?";
        if (!window.confirm(message)) {
          event.preventDefault();
        }
      });
    });
  }

  function getCoreDomApi() {
    return window.BMCoreDom || {};
  }

  function getAjaxFetchApi() {
    return window.BMAjaxFetch || {};
  }

  function unavailablePayload(expect) {
    return {
      ok: false,
      status: 0,
      data: expect === "text" ? "" : null,
      error: "request_unavailable",
      aborted: false,
      timedOut: false,
    };
  }

  function request(url, options) {
    const opts = options || {};
    const domApi = getCoreDomApi();
    if (typeof domApi.request === "function") {
      return domApi.request(url, opts);
    }
    const ajaxFetch = getAjaxFetchApi();
    if (typeof ajaxFetch.request === "function") {
      return ajaxFetch.request(url, opts);
    }
    return Promise.resolve(unavailablePayload(opts.expect === "json" ? "json" : "text"));
  }

  function requestText(url, options) {
    const opts = options || {};
    const domApi = getCoreDomApi();
    if (typeof domApi.requestText === "function") {
      return domApi.requestText(url, opts);
    }
    const ajaxFetch = getAjaxFetchApi();
    if (typeof ajaxFetch.requestText === "function") {
      return ajaxFetch.requestText(url, opts);
    }
    return request(url, Object.assign({}, opts, { expect: "text" }));
  }

  function requestJSON(url, options) {
    const opts = options || {};
    const domApi = getCoreDomApi();
    if (typeof domApi.requestJSON === "function") {
      return domApi.requestJSON(url, opts);
    }
    const ajaxFetch = getAjaxFetchApi();
    if (typeof ajaxFetch.requestJSON === "function") {
      return ajaxFetch.requestJSON(url, opts);
    }
    return request(url, Object.assign({}, opts, { expect: "json" }));
  }

  function createRequestSeq() {
    const domApi = getCoreDomApi();
    if (typeof domApi.makeRequestSeq === "function") {
      return domApi.makeRequestSeq();
    }
    const ajaxGuard = window.BMAjaxGuard || {};
    if (typeof ajaxGuard.makeRequestSeq === "function") {
      return ajaxGuard.makeRequestSeq();
    }
    let latestId = 0;
    return {
      next: function () {
        latestId += 1;
        return latestId;
      },
      isLatest: function (id) {
        return Number(id) === latestId;
      },
    };
  }

  function stopAdaptivePoll(key) {
    const poller = pollers.get(key);
    if (!poller) return;
    poller.stop();
    pollers.delete(key);
  }

  function startAdaptivePoll(key, fn, options) {
    stopAdaptivePoll(key);
    const config = options || {};
    const activeInterval = Math.max(1000, Number(config.activeInterval || 15000));
    const inactiveInterval = Math.max(activeInterval, Number(config.inactiveInterval || activeInterval * 3));
    const runWhenHidden = !!config.runWhenHidden;
    const immediate = config.immediate !== false;
    const refreshOnVisible = config.refreshOnVisible !== false;
    const when = typeof config.when === "function" ? config.when : null;
    const initialDelayMs = Math.max(
      0,
      Number(
        Object.prototype.hasOwnProperty.call(config, "initialDelayMs")
          ? config.initialDelayMs
          : immediate
          ? 0
          : activeInterval
      )
    );

    let stopped = false;
    let timer = null;

    function canRun() {
      if (!when) return true;
      try {
        return when() !== false;
      } catch (_error) {
        return false;
      }
    }

    function schedule(nextMs) {
      if (stopped) return;
      timer = window.setTimeout(tick, nextMs);
    }

    function tick() {
      if (stopped) return;
      const hidden = !!document.hidden;
      const nextMs = hidden ? inactiveInterval : activeInterval;
      if (!canRun()) {
        schedule(nextMs);
        return;
      }

      if (!hidden || runWhenHidden) {
        Promise.resolve()
          .then(function () {
            return fn();
          })
          .catch(function () {})
          .finally(function () {
            schedule(nextMs);
          });
        return;
      }

      schedule(nextMs);
    }

    schedule(initialDelayMs);

    const handle = {
      refreshOnVisible: refreshOnVisible,
      stop: function () {
        stopped = true;
        if (timer) {
          window.clearTimeout(timer);
          timer = null;
        }
      },
      refresh: function () {
        if (stopped) return;
        if (timer) {
          window.clearTimeout(timer);
          timer = null;
        }
        schedule(0);
      },
    };

    pollers.set(key, handle);
    return handle;
  }

  function rafThrottle(fn) {
    if (typeof fn !== "function") return function () {};
    let ticking = false;
    return function throttled() {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () {
        ticking = false;
        fn();
      });
    };
  }

  function announceFlashAlerts() {
    var coreUI = window.BMCoreUI || {};
    if (typeof coreUI.showToast !== "function") return;

    var alerts = Array.from(document.querySelectorAll("#pageContent .alert[role='alert']"));
    if (!alerts.length) return;

    alerts.slice(0, 3).forEach(function (alertNode, index) {
      if (!alertNode || alertNode.dataset.vendorToastAnnounced === "1") return;
      alertNode.dataset.vendorToastAnnounced = "1";

      var text = String(alertNode.textContent || "")
        .replace(/\s+/g, " ")
        .trim();
      if (!text) return;

      var type = "info";
      if (alertNode.classList.contains("alert-success")) type = "success";
      else if (alertNode.classList.contains("alert-danger")) type = "danger";
      else if (alertNode.classList.contains("alert-warning")) type = "warning";

      window.setTimeout(function () {
        coreUI.showToast(text, type);
      }, 120 + index * 140);
    });
  }

  document.addEventListener(
    "visibilitychange",
    function () {
      if (document.hidden) return;
      pollers.forEach(function (poller) {
        if (
          poller &&
          poller.refreshOnVisible !== false &&
          typeof poller.refresh === "function"
        ) {
          poller.refresh();
        }
      });
    },
    { passive: true }
  );

  window.VendorUI = {
    initOnce: initOnce,
    parsePageConfig: parsePageConfig,
    markFieldInvalid: markFieldInvalid,
    toast: toast,
    setLoadingState: setLoadingState,
    bindConfirmForms: bindConfirmForms,
    request: request,
    requestText: requestText,
    requestJSON: requestJSON,
    createRequestSeq: createRequestSeq,
    startAdaptivePoll: startAdaptivePoll,
    stopAdaptivePoll: stopAdaptivePoll,
    rafThrottle: rafThrottle,
    __loaded: true,
  };

  initOnce();
  bindScrollMemory();
  announceFlashAlerts();
})();

