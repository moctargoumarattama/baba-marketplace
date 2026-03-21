(function () {
  "use strict";

  if (window.__BM_DELIVERY_PRICING_INIT__ && window.DeliveryPricing) {
    return;
  }
  window.__BM_DELIVERY_PRICING_INIT__ = true;

  function q(selector) {
    try {
      return document.querySelector(selector);
    } catch (_) {
      return null;
    }
  }

  function toText(value, fallback) {
    if (value === null || value === undefined) return fallback || "";
    const text = String(value).trim();
    return text || (fallback || "");
  }

  function debounce(fn, waitMs) {
    let timer = null;
    return function debounced() {
      const ctx = this;
      const args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(ctx, args);
      }, Math.max(0, Number(waitMs) || 0));
    };
  }

  const bmFetchApi = window.BMAjaxFetch || null;
  const bmCsrfApi = window.BMAjaxCSRF || window.BMAjaxCsrf || null;

  function bmAddCsrfHeaders(headers, formEl) {
    const nextHeaders = Object.assign({}, headers || {});
    if (bmCsrfApi && typeof bmCsrfApi.addToHeaders === "function") {
      return bmCsrfApi.addToHeaders(nextHeaders, formEl || null);
    }
    if (!nextHeaders["X-CSRFToken"] && !nextHeaders["x-csrftoken"] && window.csrfToken) {
      nextHeaders["X-CSRFToken"] = window.csrfToken;
    }
    return nextHeaders;
  }

  async function bmFetchJSON(url, options) {
    if (bmFetchApi && typeof bmFetchApi.requestJSON === "function") {
      return bmFetchApi.requestJSON(url, options || {});
    }

    try {
      const response = await fetch(url, Object.assign({}, options || {}));
      let data = {};
      try {
        data = await response.json();
      } catch (_) {
        data = {};
      }
      return {
        ok: response.ok,
        status: response.status,
        data: data,
        error: response.ok ? null : (response.statusText || ("HTTP " + response.status)),
        aborted: false,
        timedOut: false,
      };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        data: null,
        error: String((error && error.message) || "network_error"),
        aborted: !!(error && error.name === "AbortError"),
        timedOut: false,
      };
    }
  }

  function init(options) {
    const cfg = options || {};
    const cityEl = q(cfg.citySelector);
    if (!cityEl) return null;

    const hiddenPriceEl = q(cfg.hiddenPriceSelector || "");
    const endpoint = toText(cfg.endpoint, "/api/pricing/delivery");
    const source = toText(cfg.source, "marketplace");
    const debounceMs = Number.isFinite(Number(cfg.debounceMs)) ? Number(cfg.debounceMs) : 150;

    const state = {
      lastReqId: 0,
      destroyed: false,
      activeController: null,
    };

    function invoke(handler, args) {
      if (typeof handler !== "function") return;
      try {
        handler.apply(null, args || []);
      } catch (_) {
        // UI callback errors must never break pricing flow.
      }
    }

    function abortActiveRequest() {
      if (!state.activeController) return;
      try {
        state.activeController.abort();
      } catch (_) {}
      state.activeController = null;
    }

    async function refreshNow() {
      if (state.destroyed) return;

      const city = toText(cityEl.value, "");
      if (!city) {
        abortActiveRequest();
        if (hiddenPriceEl) hiddenPriceEl.value = "";
        invoke(cfg.onEmpty, []);
        return;
      }

      const reqId = ++state.lastReqId;
      invoke(cfg.onLoading, [city]);
      abortActiveRequest();

      const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
      state.activeController = controller;

      try {
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set("city", city);
        url.searchParams.set("source", source);

        const result = await bmFetchJSON(url.toString(), {
          method: "GET",
          headers: bmAddCsrfHeaders({ Accept: "application/json" }),
          credentials: "same-origin",
          cache: "no-store",
          signal: controller ? controller.signal : undefined,
          timeoutMs: 12000,
        });

        if (state.destroyed || reqId !== state.lastReqId) return;
        if (!result || result.aborted || result.timedOut) return;

        const data = result.data && typeof result.data === "object" ? result.data : {};

        const parsedCents = Number(data && data.price_cents);
        const ok = Boolean(
          result.ok &&
            data &&
            (data.ok === true || data.success === true) &&
            Number.isFinite(parsedCents)
        );

        if (!ok) {
          if (hiddenPriceEl) hiddenPriceEl.value = "";
          invoke(cfg.onError, [toText(data && data.message, "Prix indisponible"), data, null]);
          return;
        }

        const priceCents = Math.max(0, Math.trunc(parsedCents));
        if (hiddenPriceEl) hiddenPriceEl.value = String(priceCents);
        invoke(cfg.onPrice, [priceCents, data]);
      } catch (_) {
        if (state.destroyed || reqId !== state.lastReqId) return;
        if (hiddenPriceEl) hiddenPriceEl.value = "";
        invoke(cfg.onError, ["Prix indisponible (reseau)"]);
      } finally {
        if (!state.destroyed && reqId === state.lastReqId) {
          state.activeController = null;
          invoke(cfg.onDone, []);
        }
      }
    }

    const debouncedRefresh = debounce(refreshNow, debounceMs);
    cityEl.addEventListener("change", debouncedRefresh);
    if (cfg.listenInput) {
      cityEl.addEventListener("input", debouncedRefresh);
    }

    if (cfg.runOnInit !== false) {
      refreshNow();
    }

    return {
      refresh: refreshNow,
      destroy: function destroy() {
        state.destroyed = true;
        abortActiveRequest();
        cityEl.removeEventListener("change", debouncedRefresh);
        if (cfg.listenInput) cityEl.removeEventListener("input", debouncedRefresh);
      },
    };
  }

  window.DeliveryPricing = { init: init };
})();

