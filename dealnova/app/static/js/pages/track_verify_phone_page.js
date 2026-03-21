(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_TRACK_VERIFY_PHONE_INIT__) return;
  window.__BM_TRACK_VERIFY_PHONE_INIT__ = true;

  function initTrackVerifyPage() {
    const form = document.querySelector('form[action]');
    if (!form) return;

    if (form.dataset.trackVerifyBound === "1") return;
    form.dataset.trackVerifyBound = "1";

    form.addEventListener("submit", function (event) {
      if (form.dataset.submitted === "true") {
        event.preventDefault();
        return;
      }

      form.dataset.submitted = "true";
      const button = form.querySelector('button[type="submit"]');
      if (!button) return;

      if (!button.dataset.originalHtml) {
        button.dataset.originalHtml = button.innerHTML;
      }

      button.disabled = true;
      button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Verification...';
    });

    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) return;
      form.dataset.submitted = "false";
      const button = form.querySelector('button[type="submit"]');
      if (!button) return;
      button.disabled = false;
      if (button.dataset.originalHtml) {
        button.innerHTML = button.dataset.originalHtml;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTrackVerifyPage, { once: true });
    return;
  }

  initTrackVerifyPage();
})();
