(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_ADMIN_CATEGORIES_INIT__) return;
  window.__BM_ADMIN_CATEGORIES_INIT__ = true;

  function initCategoriesPage() {
    var body = document.body;
    if (!body || body.getAttribute("data-adm-page") !== "categories") return;

    if (body.dataset) {
      body.dataset.admCategoriesInit = "1";
    }

    var form = document.getElementById("categoriesFiltersForm");
    if (!form || form.dataset.bmCategoriesBound === "1") return;
    form.dataset.bmCategoriesBound = "1";

    var searchIndicator = document.getElementById("searchInd");
    var debounceTimer = null;

    function setSearchIndicator(on) {
      if (!searchIndicator) return;
      searchIndicator.classList.toggle("on", !!on);
    }

    function clearDebounce() {
      if (!debounceTimer) return;
      window.clearTimeout(debounceTimer);
      debounceTimer = null;
    }

    function submitFilters() {
      clearDebounce();
      setSearchIndicator(false);
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
        return;
      }
      form.submit();
    }

    form.addEventListener("input", function (event) {
      var target = event.target;
      if (!target || target.id !== "fq") return;
      setSearchIndicator(true);
      clearDebounce();
      debounceTimer = window.setTimeout(submitFilters, 700);
    });

    form.addEventListener("keydown", function (event) {
      var target = event.target;
      if (!target || target.id !== "fq") return;
      if (event.key !== "Enter") return;
      event.preventDefault();
      submitFilters();
    });

    form.addEventListener("change", function (event) {
      var target = event.target;
      if (!target || target.id !== "ftype") return;
      submitFilters();
    });

    form.addEventListener("click", function (event) {
      var resetBtn = event.target && event.target.closest ? event.target.closest("#btnReset") : null;
      if (!resetBtn) return;
      event.preventDefault();

      var queryInput = form.querySelector("#fq");
      var typeSelect = form.querySelector("#ftype");
      if (queryInput) queryInput.value = "";
      if (typeSelect) typeSelect.value = "";
      submitFilters();
    });

    document.addEventListener("ajax:page-replaced", function (event) {
      var detail = (event && event.detail) || {};
      if (detail.page && detail.page !== "categories") return;
      setSearchIndicator(false);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCategoriesPage, { once: true });
    return;
  }

  initCategoriesPage();
})();

