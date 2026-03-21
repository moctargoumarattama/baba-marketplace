(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_VENDOR_SECURITY_PAGE_INIT__) return;
  window.__BM_VENDOR_SECURITY_PAGE_INIT__ = true;

  const root = document.querySelector('[data-vendor-security-root="true"]');
  if (!root) return;

  const VendorUI = window.VendorUI || {};
  if (typeof VendorUI.initOnce === "function") {
    VendorUI.initOnce();
  }

  function sanitizeNumeric(value, maxLen) {
    const limit = Math.max(1, Number(maxLen || 6));
    return String(value || "").replace(/\D+/g, "").slice(0, limit);
  }

  function bindPinInputs() {
    root.querySelectorAll(".js-pin-input").forEach(function (input) {
      if (input.dataset.pinBound === "1") return;
      input.dataset.pinBound = "1";

      const maxLen = Number(input.getAttribute("maxlength") || 6);

      input.addEventListener("input", function () {
        const sanitized = sanitizeNumeric(input.value, maxLen);
        if (sanitized !== input.value) {
          input.value = sanitized;
        }
      });

      input.addEventListener(
        "paste",
        function () {
          window.setTimeout(function () {
            input.value = sanitizeNumeric(input.value, maxLen);
          }, 0);
        },
        { passive: true }
      );
    });
  }

  function bindPinToggles() {
    root.querySelectorAll(".js-toggle-pin").forEach(function (button) {
      if (button.dataset.pinToggleBound === "1") return;
      button.dataset.pinToggleBound = "1";

      button.addEventListener("click", function () {
        const targetId = String(button.dataset.target || "");
        if (!targetId) return;

        const input = document.getElementById(targetId);
        if (!input) return;

        const isPassword = input.type === "password";
        input.type = isPassword ? "text" : "password";

        const icon = button.querySelector("i");
        if (icon) {
          icon.classList.toggle("bi-eye", !isPassword);
          icon.classList.toggle("bi-eye-slash", isPassword);
        }
      });
    });
  }

  function bindDeleteConfirm() {
    root.querySelectorAll(".js-delete-period-form").forEach(function (form) {
      if (form.dataset.confirmBound === "1") return;
      form.dataset.confirmBound = "1";

      form.addEventListener("submit", function (event) {
        const pinInput = form.querySelector('input[name="pin"]');
        const pinValue = pinInput ? String(pinInput.value || "").trim() : "";

        if (!/^\d{4,6}$/.test(pinValue)) {
          event.preventDefault();
          if (pinInput) {
            pinInput.focus();
            if (typeof VendorUI.markFieldInvalid === "function") {
              VendorUI.markFieldInvalid(pinInput, { durationMs: 1600 });
            }
          }
          return;
        }

        const periodName = String(form.dataset.periodName || "cette periode");
        const ok = window.confirm(
          "Confirmer la suppression definitive de " + periodName + " ? Cette action est irreversible."
        );
        if (!ok) {
          event.preventDefault();
        }
      });
    });
  }

  bindPinInputs();
  bindPinToggles();
  bindDeleteConfirm();
})();

