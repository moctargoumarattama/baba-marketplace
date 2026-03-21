(function () {
  "use strict";

  const boundForms = new WeakSet();
  let initialized = false;

  function showError(message) {
    const text = String(message || "Erreur reseau");
    if (window.VendorUI && typeof window.VendorUI.toast === "function") {
      window.VendorUI.toast(text, "error");
      return;
    }
    if (window.BMCoreUI && typeof window.BMCoreUI.toast === "function") {
      window.BMCoreUI.toast(text, "error");
      return;
    }
    console.error("[BMAjaxForms]", text);
  }

  function unlockSubmitter(submitter) {
    if (!submitter) return;
    if (window.BMAjaxGuard && typeof window.BMAjaxGuard.unlock === "function") {
      window.BMAjaxGuard.unlock(submitter);
      return;
    }
    if ("disabled" in submitter) {
      submitter.disabled = false;
    }
  }

  async function handleSubmit(event) {
    const form = event.currentTarget;
    if (!form) return;

    event.preventDefault();

    const submitter = event.submitter || form.querySelector('[type="submit"]');
    if (submitter && window.BMAjaxGuard && typeof window.BMAjaxGuard.lock === "function") {
      if (!window.BMAjaxGuard.lock(submitter, 1600)) {
        return;
      }
    } else if (submitter && "disabled" in submitter) {
      submitter.disabled = true;
    }

    const method = String(form.getAttribute("method") || "POST").toUpperCase();
    const action = form.getAttribute("action") || window.location.href;
    const formData = new FormData(form);
    const fetchApi = window.BMAjaxFetch;

    let result = { ok: false, status: 0, data: null, error: "missing_ajax_core" };
    if (fetchApi && typeof fetchApi.request === "function") {
      result = await fetchApi.request(action, {
        method: method,
        body: formData,
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
        form: form,
        expect: "text",
      });
    }

    if (result.ok) {
      const detail = {
        form: form,
        action: action,
        method: method,
        status: result.status,
        data: result.data,
      };
      form.dispatchEvent(
        new CustomEvent("bm:ajax-form-success", {
          bubbles: true,
          detail: detail,
        })
      );
      document.dispatchEvent(
        new CustomEvent("bm:ajax-form-success", {
          detail: detail,
        })
      );
    } else {
      showError(result.error || "Erreur reseau");
    }

    unlockSubmitter(submitter);
  }

  function bindForm(form) {
    if (!form || boundForms.has(form)) return;
    boundForms.add(form);
    form.addEventListener("submit", handleSubmit);
  }

  function init(root) {
    const scope = root && root.querySelectorAll ? root : document;
    const forms = scope.querySelectorAll('form[data-ajax="true"]');
    forms.forEach(bindForm);
    initialized = true;
    return forms.length;
  }

  const api = window.BMAjaxForms || {};
  api.init = init;
  api.bindForm = bindForm;
  api.isInitialized = function () {
    return initialized;
  };
  window.BMAjaxForms = api;
})();


