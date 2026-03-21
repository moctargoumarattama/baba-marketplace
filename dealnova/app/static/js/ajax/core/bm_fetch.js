(function () {
  "use strict";

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

  function linkAbortSignal(controller, externalSignal) {
    if (!externalSignal) return function () {};

    const onAbort = function () {
      try {
        controller.abort();
      } catch (_err) {}
    };

    if (externalSignal.aborted) {
      onAbort();
      return function () {};
    }

    externalSignal.addEventListener("abort", onAbort, { once: true });
    return function () {
      externalSignal.removeEventListener("abort", onAbort);
    };
  }

  async function parseData(response, expect) {
    if (expect === "json") {
      try {
        return await response.json();
      } catch (_err) {
        return null;
      }
    }

    try {
      return await response.text();
    } catch (_err) {
      return "";
    }
  }

  function resolveRequestUrl(url) {
    try {
      return new URL(String(url || ""), window.location.href).href;
    } catch (_err) {
      return String(url || "");
    }
  }

  function dispatchAjaxResponse(detail) {
    try {
      document.dispatchEvent(
        new CustomEvent("bm:ajax:response", {
          detail: detail || {},
        })
      );
    } catch (_err) {}
  }

  async function request(url, options) {
    const opts = options || {};
    const method = String(opts.method || "GET").toUpperCase();
    const resolvedUrl = resolveRequestUrl(url);
    const expect = opts.expect === "json" ? "json" : "text";
    const timeoutMs = Math.max(0, Number(opts.timeoutMs) || 12000);
    const onError = typeof opts.onError === "function" ? opts.onError : null;

    const controller = new AbortController();
    const detachAbort = linkAbortSignal(controller, opts.signal);
    let timedOut = false;
    let timeoutId = null;

    if (timeoutMs > 0) {
      timeoutId = window.setTimeout(function () {
        timedOut = true;
        try {
          controller.abort();
        } catch (_err) {}
      }, timeoutMs);
    }

    const headers = toPlainHeaders(opts.headers);
    const csrfApi = window.BMAjaxCSRF;
    const finalHeaders =
      shouldAttachCsrf(method) && csrfApi && typeof csrfApi.addToHeaders === "function"
        ? csrfApi.addToHeaders(headers, opts.form || null)
        : headers;

    const fetchOptions = Object.assign({}, opts, {
      method: method,
      headers: finalHeaders,
      signal: controller.signal,
    });
    delete fetchOptions.expect;
    delete fetchOptions.timeoutMs;
    delete fetchOptions.onError;
    delete fetchOptions.form;

    if (!Object.prototype.hasOwnProperty.call(fetchOptions, "credentials")) {
      fetchOptions.credentials = "same-origin";
    }

    try {
      const response = await fetch(url, fetchOptions);
      const data = await parseData(response, expect);
      const error =
        response.ok
          ? null
          : (data && typeof data === "object" && (data.error || data.message)) ||
            response.statusText ||
            ("HTTP " + response.status);

      const payload = {
        ok: response.ok,
        status: response.status,
        data: data,
        error: error ? String(error) : null,
        aborted: false,
        timedOut: false,
      };
      dispatchAjaxResponse({
        url: resolvedUrl,
        method: method,
        ok: payload.ok,
        status: payload.status,
        aborted: false,
        timedOut: false,
      });
      return payload;
    } catch (error) {
      const payload = {
        ok: false,
        status: 0,
        data: null,
        error: timedOut ? "timeout" : String((error && error.message) || "network_error"),
        aborted: timedOut ? false : !!(error && error.name === "AbortError"),
        timedOut: timedOut,
      };

      if (onError) {
        try {
          onError(payload);
        } catch (_err) {}
      }

      dispatchAjaxResponse({
        url: resolvedUrl,
        method: method,
        ok: false,
        status: 0,
        aborted: payload.aborted,
        timedOut: payload.timedOut,
        error: payload.error,
      });

      return payload;
    } finally {
      if (timeoutId != null) {
        clearTimeout(timeoutId);
      }
      detachAbort();
    }
  }

  function requestText(url, opts) {
    return request(url, Object.assign({}, opts, { expect: "text" }));
  }

  function requestJSON(url, opts) {
    return request(url, Object.assign({}, opts, { expect: "json" }));
  }

  const api = window.BMAjaxFetch || {};
  api.request = request;
  api.requestText = requestText;
  api.requestJSON = requestJSON;
  window.BMAjaxFetch = api;
})();

