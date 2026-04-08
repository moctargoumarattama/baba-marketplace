(function () {
  "use strict";

  const body = document.body;
  if (!body || !body.dataset || body.dataset.admin !== "1") return;

  const staticVersion = String(body.dataset.staticVersion || "").trim();

  function getCsrfHeaders() {
    const baseHeaders = {
      "Content-Type": "application/json",
      "X-Requested-With": "fetch",
    };
    const csrfApi = window.BMAjaxCSRF;
    if (csrfApi && typeof csrfApi.addToHeaders === "function") {
      return csrfApi.addToHeaders(baseHeaders, null);
    }
    if (window.csrfToken) {
      baseHeaders["X-CSRFToken"] = String(window.csrfToken).trim();
    }
    return baseHeaders;
  }

  function trackAnalyticsEvent(eventName, extra) {
    const name = String(eventName || "").trim();
    if (!name) return;

    const payload = Object.assign(
      {
        event: name,
        path: window.location.pathname || "/",
        surface: "admin",
      },
      extra || {}
    );

    try {
      fetch("/api/analytics/event", {
        method: "POST",
        headers: getCsrfHeaders(),
        body: JSON.stringify(payload),
        credentials: "same-origin",
        keepalive: true,
      }).catch(function () {});
    } catch (_error) {}
  }

  window.BMAnalytics = Object.assign({}, window.BMAnalytics || {}, {
    track: trackAnalyticsEvent,
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      const swUrl = "/sw.js?v=" + encodeURIComponent(staticVersion || "admin");
      navigator.serviceWorker.register(swUrl).catch(function () {});
    }, { once: true });
  }

  if (!window.__BM_ADMIN_PWA_INSTALLED_BOUND__) {
    window.__BM_ADMIN_PWA_INSTALLED_BOUND__ = true;
    window.addEventListener("appinstalled", function () {
      trackAnalyticsEvent("pwa_installed", { source: "browser_event" });
    });
  }
})();
