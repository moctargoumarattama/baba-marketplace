(function () {
  "use strict";

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

  async function readJsonSafe(response) {
    try {
      return await response.json();
    } catch (_) {
      return {};
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
      loading: false,
      lastReqId: 0,
      destroyed: false,
    };

    function invoke(handler, args) {
      if (typeof handler !== "function") return;
      try {
        handler.apply(null, args || []);
      } catch (_) {
        // UI callback errors must never break pricing flow.
      }
    }

    async function refreshNow() {
      if (state.destroyed) return;

      const city = toText(cityEl.value, "");
      if (!city) {
        if (hiddenPriceEl) hiddenPriceEl.value = "";
        invoke(cfg.onEmpty, []);
        return;
      }

      if (state.loading) return;
      state.loading = true;
      const reqId = ++state.lastReqId;
      invoke(cfg.onLoading, [city]);

      try {
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set("city", city);
        url.searchParams.set("source", source);

        const response = await fetch(url.toString(), {
          method: "GET",
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        const data = await readJsonSafe(response);

        if (state.destroyed || reqId !== state.lastReqId) return;

        const parsedCents = Number(data && data.price_cents);
        const ok = Boolean(
          response.ok &&
            data &&
            (data.ok === true || data.success === true) &&
            Number.isFinite(parsedCents)
        );

        if (!ok) {
          if (hiddenPriceEl) hiddenPriceEl.value = "";
          invoke(cfg.onError, [toText(data && data.message, "Prix indisponible"), data, response]);
          return;
        }

        const priceCents = Math.max(0, Math.trunc(parsedCents));
        if (hiddenPriceEl) hiddenPriceEl.value = String(priceCents);
        invoke(cfg.onPrice, [priceCents, data]);
      } catch (_) {
        if (hiddenPriceEl) hiddenPriceEl.value = "";
        invoke(cfg.onError, ["Prix indisponible (reseau)"]);
      } finally {
        if (!state.destroyed && reqId === state.lastReqId) {
          state.loading = false;
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
        cityEl.removeEventListener("change", debouncedRefresh);
        if (cfg.listenInput) cityEl.removeEventListener("input", debouncedRefresh);
      },
    };
  }

  window.DeliveryPricing = { init: init };
})();

