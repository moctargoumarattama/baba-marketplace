(function () {
  "use strict";

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
  var baseUrl = cfg.base_url || (form ? form.getAttribute("action") : window.location.pathname) || "/shops";

  if (!form || !searchInput || kindChips.length === 0) return;

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

  function navigateTo(url, push) {
    if (window.AjaxPagination && typeof window.AjaxPagination.navigate === "function") {
      window.AjaxPagination.navigate(url, { push: push !== false });
      return;
    }
    window.location.href = url;
  }

  function applyAndNavigate(partial, push) {
    state = {
      q: typeof partial.q !== "undefined" ? partial.q : state.q,
      kind: typeof partial.kind !== "undefined" ? partial.kind : state.kind,
      page: typeof partial.page !== "undefined" ? partial.page : state.page,
    };
    syncUi();
    navigateTo(buildUrl(state), push);
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
    }, true);
  });

  var searchDebounceTimer = null;
  searchInput.addEventListener("input", function () {
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
    searchDebounceTimer = window.setTimeout(function () {
      applyAndNavigate({
        q: (searchInput.value || "").trim(),
        kind: normalizeKind(kindInput.value),
        page: 1,
      }, true);
      searchDebounceTimer = null;
    }, 320);
  });

  searchInput.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (searchDebounceTimer) {
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = null;
    }
    applyAndNavigate({
      q: (searchInput.value || "").trim(),
      kind: normalizeKind(kindInput.value),
      page: 1,
    }, true);
  });

  kindChips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      var desiredKind = normalizeKind(chip.getAttribute("data-kind"));
      var nextKind = (state.kind === desiredKind) ? "" : desiredKind;
      applyAndNavigate({
        q: (searchInput.value || "").trim(),
        kind: nextKind,
        page: 1,
      }, true);
    });
  });

  function syncFromUrl() {
    state = getStateFromLocation();
    syncUi();
  }

  document.addEventListener("ajax:page-replaced", syncFromUrl);
  window.addEventListener("popstate", function () {
    window.setTimeout(syncFromUrl, 0);
  });

  syncUi();
})();
