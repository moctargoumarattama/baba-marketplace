(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_SHOPS_PAGE_BOOTSTRAP__) return;
  window.__BM_SHOPS_PAGE_BOOTSTRAP__ = true;

  function initShopsPage() {
    if (window.__BM_SHOPS_PAGE_INIT__) return;
    window.__BM_SHOPS_PAGE_INIT__ = true;

  function qs(selector, root) {
    return (root || document).querySelector(selector);
  }

  function qsa(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function normalizeKind(value) {
    var kind = String(value || "").trim().toLowerCase();
    if (kind === "physical" || kind === "service" || kind === "location") return kind;
    return "";
  }

  function parseConfig() {
    var el = qs("#shopsPageConfig");
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || "{}");
    } catch (_err) {
      return null;
    }
  }

  var cfg = parseConfig();
  if (!cfg) return;

  var form = qs("#searchFormShops");
  var searchInput = qs("#searchInputShops");
  var kindFilterWrap = qs("#kindFilterWrap");
  var kindChips = qsa(".kind-chip", kindFilterWrap);
  var kindAllLabel = qs("#kindAllLabel");
  var shopsResults = qs("#shopsResults");
  var searchBtn = qs(".search-btn-shops", form);
  var baseUrl = cfg.base_url || (form ? form.getAttribute("action") : window.location.pathname) || "/shops";
  var interactionFeedbackEnabled = (window.BM_PERF_FLAGS || {}).interactionFeedback !== false;
  var navigationPending = false;
  var pendingTrigger = null;
  var pendingAnchorTop = null;
  var pendingLockedHeight = 0;
  var pendingAnchorSelector = "";
  var loadingShowTimer = null;
  var loadingHideTimer = null;
  var loadingVisibleSince = 0;

  if (!form || !searchInput || kindChips.length === 0) return;

  function clearPendingTrigger() {
    if (!pendingTrigger || !pendingTrigger.removeAttribute) {
      pendingTrigger = null;
      return;
    }
    pendingTrigger.removeAttribute("data-bm-pending");
    pendingTrigger = null;
  }

  function lockResultsLayout() {
    if (!shopsResults || !shopsResults.style) return 0;
    var height = Math.max(0, Math.round(shopsResults.getBoundingClientRect().height || 0));
    if (height > 0) {
      shopsResults.style.minHeight = height + "px";
      shopsResults.classList.add("is-swapping");
    }
    return height;
  }

  function unlockResultsLayout() {
    if (!shopsResults || !shopsResults.style) return;
    shopsResults.style.removeProperty("min-height");
    shopsResults.classList.remove("is-swapping");
  }

  function prepareStableSwap(triggerEl, anchorSelector) {
    pendingAnchorSelector = anchorSelector || "";
    var anchorNode = pendingAnchorSelector ? qs(pendingAnchorSelector) : null;
    pendingAnchorTop = anchorNode
      ? anchorNode.getBoundingClientRect().top
      : shopsResults ? shopsResults.getBoundingClientRect().top : null;
    pendingLockedHeight = lockResultsLayout();
    setNavigationPending(true, triggerEl || null);
  }

  function finalizeStableSwap() {
    if (shopsResults && pendingAnchorTop != null) {
      var anchorNode = pendingAnchorSelector ? qs(pendingAnchorSelector) : null;
      var nextTop = anchorNode
        ? anchorNode.getBoundingClientRect().top
        : shopsResults.getBoundingClientRect().top;
      var delta = nextTop - pendingAnchorTop;
      if (Math.abs(delta) > 1) {
        window.scrollBy(0, delta);
      }
    }
    pendingAnchorTop = null;
    pendingAnchorSelector = "";
    if (pendingLockedHeight > 0) {
      window.setTimeout(function () {
        unlockResultsLayout();
        pendingLockedHeight = 0;
      }, 120);
    } else {
      unlockResultsLayout();
    }
  }

  function setFormPending(active) {
    if (!interactionFeedbackEnabled) return;
    form.classList.toggle("is-pending", !!active);
    if (searchBtn) {
      searchBtn.setAttribute("aria-busy", active ? "true" : "false");
    }
  }

  function setResultsLoading(active) {
    if (loadingShowTimer) {
      window.clearTimeout(loadingShowTimer);
      loadingShowTimer = null;
    }
    if (loadingHideTimer) {
      window.clearTimeout(loadingHideTimer);
      loadingHideTimer = null;
    }
    if (active) {
      loadingVisibleSince = Date.now();
    }
    if (shopsResults && shopsResults.classList) {
      shopsResults.classList.toggle("is-loading", !!active);
    }
  }

  function scheduleResultsLoading() {
    if (loadingShowTimer) {
      window.clearTimeout(loadingShowTimer);
    }
    loadingShowTimer = window.setTimeout(function () {
      loadingShowTimer = null;
      setResultsLoading(true);
    }, 140);
  }

  function hideResultsLoadingSmooth() {
    if (loadingShowTimer) {
      window.clearTimeout(loadingShowTimer);
      loadingShowTimer = null;
    }
    if (!shopsResults || !shopsResults.classList || !shopsResults.classList.contains("is-loading")) {
      setResultsLoading(false);
      return;
    }
    var elapsed = loadingVisibleSince ? Date.now() - loadingVisibleSince : 0;
    var remaining = Math.max(0, 120 - elapsed);
    if (remaining > 0) {
      loadingHideTimer = window.setTimeout(function () {
        setResultsLoading(false);
      }, remaining);
      return;
    }
    setResultsLoading(false);
  }

  function setNavigationPending(active, triggerEl) {
    navigationPending = !!active;
    setFormPending(active);
    if (active) {
      scheduleResultsLoading();
    } else {
      hideResultsLoadingSmooth();
    }
    if (!interactionFeedbackEnabled) return;
    clearPendingTrigger();
    if (active && triggerEl && triggerEl.setAttribute) {
      pendingTrigger = triggerEl;
      pendingTrigger.setAttribute("data-bm-pending", "1");
    }
  }

  function getStateFromLocation() {
    var url = new URL(window.location.href);
    var page = parseInt(url.searchParams.get("page") || "1", 10);
    return {
      q: (url.searchParams.get("q") || "").trim(),
      kind: normalizeKind(url.searchParams.get("kind") || ""),
      page: Number.isFinite(page) && page > 0 ? page : 1,
    };
  }

  var state = getStateFromLocation();

  function ensureKindInput() {
    var input = form.querySelector('input[name="kind"]');
    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = "kind";
      form.appendChild(input);
    }
    return input;
  }

  var kindInput = ensureKindInput();

  function syncUi() {
    if (document.activeElement !== searchInput) {
      searchInput.value = state.q || "";
    }
    kindInput.value = state.kind || "";

    kindChips.forEach(function (chip) {
      var chipKind = normalizeKind(chip.getAttribute("data-kind"));
      var active = !!state.kind && chipKind === state.kind;
      chip.classList.toggle("active", active);
      chip.setAttribute("aria-pressed", active ? "true" : "false");
    });

    if (kindAllLabel) {
      kindAllLabel.classList.toggle("kind-hidden", !!state.kind);
    }
  }

  function buildUrl(nextState) {
    var target = {
      q: (nextState && typeof nextState.q !== "undefined") ? nextState.q : state.q,
      kind: (nextState && typeof nextState.kind !== "undefined") ? nextState.kind : state.kind,
      page: (nextState && typeof nextState.page !== "undefined") ? nextState.page : state.page,
    };
    var params = new URLSearchParams();
    if (target.q) params.set("q", target.q);
    if (target.kind) params.set("kind", target.kind);
    if (target.page && Number(target.page) > 1) params.set("page", String(target.page));
    var query = params.toString();
    return query ? (baseUrl + "?" + query) : baseUrl;
  }

  function navigateTo(url, push, triggerEl) {
    prepareStableSwap(triggerEl, "#shopsPagination");
    if (window.AjaxPagination && typeof window.AjaxPagination.navigate === "function") {
      window.AjaxPagination.navigate(url, { push: push !== false, triggerEl: triggerEl || null });
      return;
    }
    window.location.href = url;
  }

  function applyAndNavigate(partial, push, triggerEl) {
    if (navigationPending) return;
    state = {
      q: typeof partial.q !== "undefined" ? partial.q : state.q,
      kind: typeof partial.kind !== "undefined" ? partial.kind : state.kind,
      page: typeof partial.page !== "undefined" ? partial.page : state.page,
    };
    syncUi();
    navigateTo(buildUrl(state), push, triggerEl || null);
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (searchDebounceTimer) {
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = null;
    }
    applyAndNavigate({
      q: (searchInput.value || "").trim(),
      kind: normalizeKind(kindInput.value),
      page: 1,
    }, true, searchBtn || event.submitter || null);
  });

  var searchDebounceTimer = null;
  searchInput.addEventListener("input", function () {
    if (navigationPending) return;
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
    setFormPending(true);
    searchDebounceTimer = window.setTimeout(function () {
      applyAndNavigate({
        q: (searchInput.value || "").trim(),
        kind: normalizeKind(kindInput.value),
        page: 1,
      }, true, searchBtn || null);
      searchDebounceTimer = null;
    }, 320);
  });

  searchInput.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (navigationPending) return;
    if (searchDebounceTimer) {
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = null;
    }
    applyAndNavigate({
      q: (searchInput.value || "").trim(),
      kind: normalizeKind(kindInput.value),
      page: 1,
    }, true, searchBtn || null);
  });

  kindChips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      if (navigationPending) return;
      var desiredKind = normalizeKind(chip.getAttribute("data-kind"));
      var nextKind = (state.kind === desiredKind) ? "" : desiredKind;
      applyAndNavigate({
        q: (searchInput.value || "").trim(),
        kind: nextKind,
        page: 1,
      }, true, chip);
    });
  });

  function syncFromUrl() {
    state = getStateFromLocation();
    syncUi();
  }

  document.addEventListener("ajax:page-replaced", function () {
    setNavigationPending(false);
    finalizeStableSwap();
    syncFromUrl();
  });
  window.addEventListener("popstate", function () {
    window.setTimeout(function () {
      setNavigationPending(false);
      finalizeStableSwap();
      syncFromUrl();
    }, 0);
  });
  window.addEventListener("pageshow", function () {
    setNavigationPending(false);
    finalizeStableSwap();
  });

  document.addEventListener("click", function (event) {
    var link = event.target.closest("#shopsPagination a.page-link-shops[href]");
    if (!link) return;
    prepareStableSwap(link, "#shopsPagination");
  }, true);

    setNavigationPending(false);
    syncUi();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initShopsPage, { once: true });
  } else {
    initShopsPage();
  }
})();

