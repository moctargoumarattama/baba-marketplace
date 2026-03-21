(function () {
  "use strict";

  let initialized = false;

  function init() {
    if (initialized) return false;
    initialized = true;
    return !!(window.AjaxPagination && typeof window.AjaxPagination.navigate === "function");
  }

  function navigate(url, opts) {
    if (window.AjaxPagination && typeof window.AjaxPagination.navigate === "function") {
      return window.AjaxPagination.navigate(url, opts || {});
    }
    return Promise.resolve(false);
  }

  function isAjaxPage(root) {
    if (window.AjaxPagination && typeof window.AjaxPagination.isAjaxPage === "function") {
      return window.AjaxPagination.isAjaxPage(root || document);
    }
    return false;
  }

  const api = window.BMAjaxPagination || {};
  api.init = init;
  api.navigate = navigate;
  api.isAjaxPage = isAjaxPage;
  window.BMAjaxPagination = api;
})();


