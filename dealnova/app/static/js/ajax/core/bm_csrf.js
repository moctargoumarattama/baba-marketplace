(function () {
  "use strict";

  function readMetaToken() {
    if (!document || !document.querySelector) return "";
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (!meta) return "";
    return String(meta.getAttribute("content") || "").trim();
  }

  function readFormToken(formEl) {
    if (!formEl || !formEl.querySelector) return "";
    const input = formEl.querySelector('input[name="csrf_token"]');
    if (!input) return "";
    return String(input.value || "").trim();
  }

  function readAnyFormToken() {
    if (!document || !document.querySelector) return "";
    const input = document.querySelector('form input[name="csrf_token"]');
    if (!input) return "";
    return String(input.value || "").trim();
  }

  function getToken(formEl) {
    const fromMeta = readMetaToken();
    if (fromMeta) return fromMeta;

    const fromForm = readFormToken(formEl);
    if (fromForm) return fromForm;

    const fromAnyForm = readAnyFormToken();
    if (fromAnyForm) return fromAnyForm;

    if (window && window.csrfToken) {
      return String(window.csrfToken).trim();
    }

    return "";
  }

  function addToHeaders(headersObj, formEl) {
    const headers = Object.assign({}, headersObj || {});
    const hasTokenHeader =
      Object.prototype.hasOwnProperty.call(headers, "X-CSRFToken") ||
      Object.prototype.hasOwnProperty.call(headers, "x-csrftoken");

    if (hasTokenHeader) return headers;

    const token = getToken(formEl);
    if (token) {
      headers["X-CSRFToken"] = token;
    }
    return headers;
  }

  const api = window.BMAjaxCSRF || {};
  api.getToken = getToken;
  api.addToHeaders = addToHeaders;
  api.withCsrfHeaders = addToHeaders;
  window.BMAjaxCSRF = api;
})();

