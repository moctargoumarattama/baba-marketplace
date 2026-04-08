(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;

  if (window.__BM_VENDOR_EARNINGS_INIT__ || window.__BM_VENDOR_EARNINGS_PAGE_INIT__) return;
  window.__BM_VENDOR_EARNINGS_INIT__ = true;
  window.__BM_VENDOR_EARNINGS_PAGE_INIT__ = true;

  const ROOT_SELECTOR = '[data-vendor-earnings-root="true"]';
  const HISTORY_FLAG = "bmVendorEarnings";
  const state = {
    activeRequest: null,
    requestSeq: null,
    popstateBound: false,
    backToTopBound: false,
    backToTopButton: null,
    uiBusy: false,
    pendingTrigger: null,
  };

  function readConfig() {
    const defaults = {
      refreshIntervalMs: 60000,
      reloadDelayMs: 1000,
      scrollStorageKey: "earningsScrollPosition",
      autoRefreshInfoEvery: 3,
    };
    const node = document.getElementById("vendorEarningsPageConfig");
    if (!node) return defaults;
    try {
      const parsed = JSON.parse(node.textContent || "{}");
      if (!parsed || typeof parsed !== "object") return defaults;
      return {
        refreshIntervalMs: Math.max(1000, Number(parsed.refreshIntervalMs || defaults.refreshIntervalMs)),
        reloadDelayMs: Math.max(0, Number(parsed.reloadDelayMs || defaults.reloadDelayMs)),
        scrollStorageKey: String(parsed.scrollStorageKey || defaults.scrollStorageKey),
        autoRefreshInfoEvery: Math.max(1, Number(parsed.autoRefreshInfoEvery || defaults.autoRefreshInfoEvery)),
      };
    } catch (_error) {
      return defaults;
    }
  }

  const cfg = readConfig();
  const VendorUI = window.VendorUI || {};
  const coreDomApi = window.BMCoreDom || {};
  const perfFlags = window.BM_PERF_FLAGS || {};
  const interactionFeedbackEnabled = perfFlags.interactionFeedback !== false;
  if (typeof VendorUI.initOnce === "function") {
    VendorUI.initOnce();
  }
  state.requestSeq =
    (window.BMAjaxGuard && typeof window.BMAjaxGuard.makeRequestSeq === "function"
      ? window.BMAjaxGuard.makeRequestSeq()
      : null) ||
    (typeof VendorUI.createRequestSeq === "function" ? VendorUI.createRequestSeq() : null) ||
    (function () {
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
    })();
  const fallbackRequestText =
    typeof coreDomApi.requestText === "function"
      ? coreDomApi.requestText
      : window.BMAjaxFetch.requestText.bind(window.BMAjaxFetch);
  const requestText = (typeof VendorUI.requestText === "function")
    ? VendorUI.requestText
    : fallbackRequestText;

  function getRoot() {
    return document.querySelector(ROOT_SELECTOR);
  }

  function clearPendingTrigger() {
    if (state.pendingTrigger && state.pendingTrigger.removeAttribute) {
      state.pendingTrigger.removeAttribute("data-bm-pending");
    }
    state.pendingTrigger = null;
  }

  function setPageLoading(active, options) {
    state.uiBusy = !!active;
    const cfgOptions = options || {};
    const root = (cfgOptions.root && cfgOptions.root.classList) ? cfgOptions.root : getRoot();
    if (root && root.classList) {
      root.classList.toggle("is-loading", !!active);
    }
    if (!interactionFeedbackEnabled) {
      if (!active) clearPendingTrigger();
      return;
    }
    if (!active) {
      clearPendingTrigger();
      return;
    }
    clearPendingTrigger();
    if (cfgOptions.triggerEl && cfgOptions.triggerEl.setAttribute) {
      state.pendingTrigger = cfgOptions.triggerEl;
      state.pendingTrigger.setAttribute("data-bm-pending", "1");
    }
  }

  function showToast(message, type) {
    const toast = document.getElementById("earningsToast");
    const toastMessage = document.getElementById("toastMessage");
    if (!toast || !toastMessage) return;

    const icon = toast.querySelector(".toast-icon i");
    toastMessage.textContent = String(message || "");

    if (icon) {
      if (type === "info") {
        icon.className = "bi bi-info-circle";
        toast.style.background = "linear-gradient(145deg, #ffffff, #eff6ff)";
      } else {
        icon.className = "bi bi-check2-circle";
        toast.style.background = "linear-gradient(145deg, #ffffff, #f0fdf4)";
      }
    }

    toast.classList.add("show");
    window.setTimeout(function () {
      toast.classList.remove("show");
    }, 5000);
  }

  function optimizeTouchFeedback(root) {
    if (!("ontouchstart" in window)) return;
    if (!root || root.dataset.touchFeedbackBound === "1") return;
    root.dataset.touchFeedbackBound = "1";

    function resolveTouchTarget(event) {
      const target = event.target && event.target.closest
        ? event.target.closest(".stat-tile, .product-pill, .pagination-item")
        : null;
      return target && root.contains(target) ? target : null;
    }

    function clearTouchScale(event) {
      const el = resolveTouchTarget(event);
      if (!el) return;
      el.style.transform = "";
    }

    root.addEventListener("touchstart", function (event) {
      const el = resolveTouchTarget(event);
      if (!el) return;
      el.style.transform = "scale(0.98)";
    }, { passive: true });
    root.addEventListener("touchend", clearTouchScale, { passive: true });
    root.addEventListener("touchcancel", clearTouchScale, { passive: true });
  }

  function optimizeFilterPillOnSmallScreens(root) {
    if (!root) return;
    const filterPill = root.querySelector(".filter-pill");
    if (!filterPill || window.innerWidth >= 640) return;
    filterPill.querySelectorAll(".form-control, .form-select").forEach(function (input) {
      input.style.width = "100%";
    });
  }

  function normalizeText(value) {
    return String(value || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  function bindQuickSearch(root) {
    if (!root) return;
    const searchInput = root.querySelector("#quickSearch");
    const clearSearchBtn = root.querySelector("#clearSearch");
    const noResultsRow = root.querySelector("#noSearchResults");
    const orderRows = Array.from(root.querySelectorAll("tbody tr.order-row"));

    if (!searchInput || !orderRows.length) return;

    const rowIndex = new Map(
      orderRows.map(function (row) {
        return [row, normalizeText(row.textContent)];
      })
    );

    function applySearch() {
      const query = normalizeText(searchInput.value.trim());
      let visibleCount = 0;

      orderRows.forEach(function (row) {
        const matches = !query || String(rowIndex.get(row) || "").includes(query);
        row.hidden = !matches;
        if (matches) visibleCount += 1;
      });

      if (noResultsRow) {
        noResultsRow.hidden = visibleCount !== 0;
      }
      if (clearSearchBtn) {
        clearSearchBtn.hidden = !searchInput.value;
      }
    }

    searchInput.addEventListener("input", applySearch, { passive: true });
    if (clearSearchBtn) {
      clearSearchBtn.addEventListener("click", function () {
        searchInput.value = "";
        applySearch();
        searchInput.focus();
      });
    }
    applySearch();
  }

  function bindScrollMemory() {
    const key = cfg.scrollStorageKey || "earningsScrollPosition";
    window.addEventListener("beforeunload", function () {
      try {
        sessionStorage.setItem(key, String(window.scrollY || 0));
      } catch (_error) {}
    });

    window.addEventListener(
      "load",
      function () {
        try {
          const saved = sessionStorage.getItem(key);
          if (!saved) return;
          window.scrollTo(0, parseInt(saved, 10) || 0);
          sessionStorage.removeItem(key);
        } catch (_error) {}
      },
      { once: true }
    );
  }

  function updateBackToTopVisibility() {
    const button = state.backToTopButton;
    if (!button || !button.classList) return;
    const y = Math.max(0, Number(window.scrollY || window.pageYOffset || 0));
    button.classList.toggle("show", y > 360);
  }

  function bindBackToTop(root) {
    if (!root) return;
    const button = root.querySelector("#earningsBackTop");
    state.backToTopButton = button || null;
    if (!button) return;

    if (button.dataset.bound !== "1") {
      button.dataset.bound = "1";
      button.addEventListener("click", function (event) {
        event.preventDefault();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    }

    updateBackToTopVisibility();

    if (state.backToTopBound) return;
    const onScroll = typeof VendorUI.rafThrottle === "function"
      ? VendorUI.rafThrottle(updateBackToTopVisibility)
      : (function () {
          let ticking = false;
          return function () {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(function () {
              ticking = false;
              updateBackToTopVisibility();
            });
          };
        })();

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    state.backToTopBound = true;
  }

  function applyEntranceAnimationDelay(root) {
    if (!root) return;
    root.querySelectorAll(".stat-tile, .table-card, .empty-earnings").forEach(function (el, index) {
      el.style.animationDelay = String(0.1 * (index + 1)) + "s";
    });
  }

  function markHistoryScroll(scrollY) {
    try {
      const current = history.state && typeof history.state === "object" ? history.state : {};
      history.replaceState(
        Object.assign({}, current, {
          [HISTORY_FLAG]: true,
          scrollY: Math.max(0, Number(scrollY) || 0),
        }),
        "",
        window.location.href
      );
    } catch (_error) {}
  }

  function ensureHistoryState() {
    try {
      const current = history.state && typeof history.state === "object" ? history.state : {};
      if (current[HISTORY_FLAG]) return;
      history.replaceState(
        Object.assign({}, current, {
          [HISTORY_FLAG]: true,
          scrollY: Math.max(0, Number(window.scrollY) || 0),
        }),
        "",
        window.location.href
      );
    } catch (_error) {}
  }

  async function fetchAndSwap(url, options) {
    const opts = options || {};
    const requestUrl = String(url || window.location.href);
    const requestId = state.requestSeq.next();
    const preserveScroll = opts.preserveScroll !== false;
    const showFeedback = opts.feedback !== false;
    const currentScrollY = Math.max(0, Number(window.scrollY) || 0);
    const currentScrollX = Math.max(0, Number(window.scrollX) || 0);

    if (showFeedback) {
      setPageLoading(true, { triggerEl: opts.triggerEl || null });
    }

    if (state.activeRequest) {
      try {
        state.activeRequest.abort();
      } catch (_error) {}
    }
    const controller = new AbortController();
    state.activeRequest = controller;

    const headers = Object.assign(
      {
        "X-Requested-With": "fetch",
        "Accept": "text/html,application/xhtml+xml",
      },
      opts.headers || {}
    );
    const method = String(opts.method || "GET").toUpperCase();
    const fetchOptions = {
      method: method,
      headers: headers,
      credentials: "same-origin",
      redirect: "follow",
      signal: controller.signal,
    };
    if (method !== "GET" && opts.body) {
      fetchOptions.body = opts.body;
    }

    try {
      const result = await requestText(requestUrl, fetchOptions);
      if (!state.requestSeq.isLatest(requestId)) {
        return false;
      }
      if (!result || result.aborted || result.timedOut) {
        return false;
      }
      if (!result.ok) {
        throw new Error(String(result.error || ("HTTP " + String(result.status || "error"))));
      }
      const html = String(result.data || "");
      const doc = new DOMParser().parseFromString(html, "text/html");
      const nextRoot = doc.querySelector(ROOT_SELECTOR);
      if (!nextRoot) {
        throw new Error("missing vendor earnings root");
      }
      const currentRoot = getRoot();
      if (!currentRoot) {
        throw new Error("current vendor earnings root missing");
      }

      currentRoot.replaceWith(nextRoot);

      if (doc.title) {
        document.title = doc.title;
      }

      const finalUrl = requestUrl;
      if (opts.history === "push") {
        markHistoryScroll(currentScrollY);
        try {
          history.pushState(
            {
              [HISTORY_FLAG]: true,
              scrollY: currentScrollY,
            },
            "",
            finalUrl
          );
        } catch (_error) {}
      } else if (opts.history === "replace") {
        try {
          const currentState = history.state && typeof history.state === "object" ? history.state : {};
          history.replaceState(
            Object.assign({}, currentState, {
              [HISTORY_FLAG]: true,
              scrollY: currentScrollY,
            }),
            "",
            finalUrl
          );
        } catch (_error) {}
      }

      bindPageInteractions();

      const targetY = typeof opts.restoreScroll === "number"
        ? Math.max(0, opts.restoreScroll)
        : (preserveScroll ? currentScrollY : 0);
      window.scrollTo({
        top: targetY,
        left: currentScrollX,
        behavior: "auto",
      });

      if (opts.successMessage) {
        showToast(opts.successMessage, opts.toastType || "success");
      }
      return true;
    } catch (error) {
      if (error && error.name === "AbortError") return false;
      console.error("[vendor-earnings] ajax navigation failed", error);
      return false;
    } finally {
      if (showFeedback && state.requestSeq.isLatest(requestId)) {
        setPageLoading(false);
      }
      if (state.activeRequest === controller) {
        state.activeRequest = null;
      }
    }
  }

  function buildGetUrlFromForm(form) {
    const action = form.getAttribute("action") || window.location.pathname;
    const url = new URL(action, window.location.origin);
    const params = new URLSearchParams(new FormData(form));
    url.search = params.toString();
    return url.toString();
  }

  function bindAjaxInteractions(root) {
    if (!root || root.dataset.ajaxBound === "1") return;
    root.dataset.ajaxBound = "1";

    root.addEventListener("submit", function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;

      if (form.matches(".filter-pill")) {
        event.preventDefault();
        if (state.uiBusy) return;
        const submitter = (event.submitter instanceof HTMLElement)
          ? event.submitter
          : form.querySelector(".btn-filter");
        const targetUrl = buildGetUrlFromForm(form);
        fetchAndSwap(targetUrl, {
          history: "push",
          preserveScroll: true,
          triggerEl: submitter || null,
        }).then(function (ok) {
          if (!ok) window.location.assign(targetUrl);
        });
        return;
      }

      if (form.matches(".pay-form")) {
        event.preventDefault();
        if (state.uiBusy) return;
        const submitBtn = form.querySelector('button[type="submit"]');
        const wasDisabled = submitBtn ? Boolean(submitBtn.disabled) : false;
        if (submitBtn) submitBtn.disabled = true;

        const targetUrl = form.getAttribute("action") || window.location.href;
        const payload = new FormData(form);
        fetchAndSwap(targetUrl, {
          method: "POST",
          body: payload,
          history: "replace",
          preserveScroll: true,
          successMessage: "Encaissement confirme.",
          triggerEl: submitBtn || null,
        }).then(function (ok) {
          if (!ok) form.submit();
        }).finally(function () {
          if (submitBtn) submitBtn.disabled = wasDisabled;
        });
      }
    });

    root.addEventListener("click", function (event) {
      const link = event.target.closest(".pagination-premium a.pagination-item");
      if (!link || !root.contains(link)) return;

      const href = link.getAttribute("href");
      if (!href || href === "#" || link.classList.contains("disabled")) {
        event.preventDefault();
        return;
      }

      event.preventDefault();
      if (state.uiBusy) return;
      fetchAndSwap(href, {
        history: "push",
        preserveScroll: true,
        triggerEl: link,
      }).then(function (ok) {
        if (!ok) window.location.assign(href);
      });
    }, { passive: false });
  }

  function bindPopStateNavigation() {
    if (state.popstateBound) return;
    state.popstateBound = true;

    window.addEventListener("popstate", function (event) {
      const targetY = event && event.state && typeof event.state.scrollY === "number"
        ? event.state.scrollY
        : 0;
      fetchAndSwap(window.location.href, {
        history: "replace",
        preserveScroll: false,
        restoreScroll: targetY,
        feedback: false,
      }).then(function (ok) {
        if (!ok) window.location.reload();
      });
    });
  }

  function bindPageInteractions() {
    const root = getRoot();
    if (!root) return;
    optimizeTouchFeedback(root);
    optimizeFilterPillOnSmallScreens(root);
    bindBackToTop(root);
    bindQuickSearch(root);
    bindAjaxInteractions(root);
    applyEntranceAnimationDelay(root);
  }

  function bindAutoRefresh() {
    let refreshCount = 0;

    function isEarningsPageReady() {
      const root = getRoot();
      const bodyPage = String((document.body && document.body.dataset && document.body.dataset.page) || "");
      return !!root && (bodyPage === "vendor.earnings" || window.location.pathname.indexOf("/vendor/earnings") === 0);
    }

    function shouldPauseRefresh() {
      const active = document.activeElement;
      if (
        active &&
        (
          active.tagName === "INPUT" ||
          active.tagName === "TEXTAREA" ||
          active.tagName === "SELECT"
        )
      ) {
        return true;
      }
      const root = getRoot();
      if (!root) return false;
      const searchInput = root.querySelector("#quickSearch");
      return Boolean(searchInput && String(searchInput.value || "").trim());
    }

    function runRefreshCycle() {
      if (document.hidden) return;
      if (shouldPauseRefresh()) return;
      refreshCount += 1;
      const shouldInform = refreshCount % cfg.autoRefreshInfoEvery === 0;
      fetchAndSwap(window.location.href, {
        history: "replace",
        preserveScroll: true,
        feedback: false,
      }).then(function (ok) {
        if (!ok) {
          window.setTimeout(function () {
            window.location.reload();
          }, cfg.reloadDelayMs);
          return;
        }
        if (shouldInform) {
          showToast("Mise a jour automatique des donnees", "info");
        }
      });
    }

    if (typeof VendorUI.startAdaptivePoll === "function") {
      VendorUI.startAdaptivePoll("vendor-earnings-refresh", runRefreshCycle, {
        activeInterval: cfg.refreshIntervalMs,
        inactiveInterval: Math.max(cfg.refreshIntervalMs * 3, 180000),
        immediate: false,
        refreshOnVisible: false,
        when: isEarningsPageReady,
      });
      return;
    }

    let refreshTimer = null;
    function clearRefreshTimer() {
      if (refreshTimer) {
        window.clearTimeout(refreshTimer);
        refreshTimer = null;
      }
    }
    function scheduleRefresh(delayMs) {
      clearRefreshTimer();
      refreshTimer = window.setTimeout(runTick, Math.max(1000, Number(delayMs) || cfg.refreshIntervalMs));
    }
    function runTick() {
      if (document.hidden) {
        clearRefreshTimer();
        return;
      }
      if (!isEarningsPageReady()) {
        scheduleRefresh(cfg.refreshIntervalMs);
        return;
      }
      Promise.resolve(runRefreshCycle()).finally(function () {
        scheduleRefresh(cfg.refreshIntervalMs);
      });
    }
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        clearRefreshTimer();
        return;
      }
      scheduleRefresh(1000);
    });
    window.addEventListener(
      "beforeunload",
      function () {
        clearRefreshTimer();
      },
      { once: true }
    );
    scheduleRefresh(cfg.refreshIntervalMs);
  }

  // Keep backward compatibility for templates that call it directly.
  window.showEarningsToast = showToast;

  ensureHistoryState();
  bindPopStateNavigation();
  bindPageInteractions();
  bindScrollMemory();
  bindAutoRefresh();
})();

