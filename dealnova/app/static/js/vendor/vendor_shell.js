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

  function toPlainHeaders(headers) {
    if (!headers) return {};
    if (headers instanceof Headers) {
      const plain = {};
      headers.forEach(function (value, key) {
        plain[key] = value;
      });
      return plain;
    }
    return Object.assign({}, headers);
  }

  function shouldAttachCsrf(method) {
    const normalized = String(method || "GET").toUpperCase();
    return normalized !== "GET" && normalized !== "HEAD" && normalized !== "OPTIONS";
  }

  function parseNativeResponse(response, expect) {
    if (expect === "json") {
      return response
        .json()
        .catch(function () {
          return null;
        });
    }
    return response
      .text()
      .catch(function () {
        return "";
      });
  }

  function nativeRequest(url, options) {
    const opts = options || {};
    const method = String(opts.method || "GET").toUpperCase();
    const expect = opts.expect === "json" ? "json" : "text";
    const headers = toPlainHeaders(opts.headers);
    const csrfApi = window.BMAjaxCSRF;
    const finalHeaders =
      shouldAttachCsrf(method) && csrfApi && typeof csrfApi.addToHeaders === "function"
        ? csrfApi.addToHeaders(headers, opts.form || null)
        : headers;

    const fetchOptions = Object.assign({}, opts, {
      method: method,
      headers: finalHeaders,
    });
    delete fetchOptions.expect;
    delete fetchOptions.timeoutMs;
    delete fetchOptions.onError;
    delete fetchOptions.form;

    if (!Object.prototype.hasOwnProperty.call(fetchOptions, "credentials")) {
      fetchOptions.credentials = "same-origin";
    }

    return fetch(url, fetchOptions)
      .then(function (response) {
        return parseNativeResponse(response, expect).then(function (data) {
          return {
            ok: response.ok,
            status: Number(response.status || 0),
            data: data,
            error: response.ok
              ? null
              : String(response.statusText || "HTTP " + String(response.status || 0)),
            aborted: false,
            timedOut: false,
          };
        });
      })
      .catch(function (error) {
        const isAbort = !!(error && error.name === "AbortError");
        return {
          ok: false,
          status: 0,
          data: null,
          error: String((error && error.message) || "network_error"),
          aborted: isAbort,
          timedOut: false,
        };
      });
  }

  function request(url, options) {
    const bmFetch = window.BMAjaxFetch;
    if (bmFetch && typeof bmFetch.request === "function") {
      return bmFetch.request(url, options || {});
    }
    return nativeRequest(url, options || {});
  }

  function requestText(url, options) {
    const opts = Object.assign({}, options || {}, { expect: "text" });
    const bmFetch = window.BMAjaxFetch;
    if (bmFetch && typeof bmFetch.requestText === "function") {
      return bmFetch.requestText(url, opts);
    }
    return request(url, opts);
  }

  function requestJSON(url, options) {
    const opts = Object.assign({}, options || {}, { expect: "json" });
    const bmFetch = window.BMAjaxFetch;
    if (bmFetch && typeof bmFetch.requestJSON === "function") {
      return bmFetch.requestJSON(url, opts);
    }
    return request(url, opts);
  }

  function createRequestSeq() {
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
})();

