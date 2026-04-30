(function () {
  "use strict";

  if (window.__ADM_FORMS_INIT__ && window.AdminForms) {
    return;
  }
  window.__ADM_FORMS_INIT__ = true;

  function ensureGlobalCsrfToken(formEl) {
    if (window.csrfToken) {
      return String(window.csrfToken).trim();
    }

    var token = "";
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) token = String(meta.getAttribute("content") || "").trim();
    if (!token && formEl && formEl.querySelector) {
      var input = formEl.querySelector('input[name="csrf_token"]');
      if (input) token = String(input.value || "").trim();
    }
    if (token) {
      window.csrfToken = token;
    }
    return token;
  }

  function withCsrfHeaders(headers, formEl) {
    var source = Object.assign({}, headers || {});
    if (window.BMAjaxCSRF) {
      if (typeof window.BMAjaxCSRF.withCsrfHeaders === "function") {
        return window.BMAjaxCSRF.withCsrfHeaders(source, formEl || null);
      }
      if (typeof window.BMAjaxCSRF.addToHeaders === "function") {
        return window.BMAjaxCSRF.addToHeaders(source, formEl || null);
      }
    }

    if (!source["X-CSRFToken"]) {
      var token = ensureGlobalCsrfToken(formEl);
      if (token) source["X-CSRFToken"] = token;
    }

    return source;
  }
  var coreDomApi = window.BMCoreDom || {};
  var requestJSON =
    typeof coreDomApi.requestJSON === "function"
      ? function (url, options) {
          return coreDomApi.requestJSON(url, options || {});
        }
      : window.BMAjaxFetch.requestJSON.bind(window.BMAjaxFetch);
  var requestText =
    typeof coreDomApi.requestText === "function"
      ? function (url, options) {
          return coreDomApi.requestText(url, options || {});
        }
      : window.BMAjaxFetch.requestText.bind(window.BMAjaxFetch);

  function normalizeValue(value) {
    return String(value || "")
      .trim()
      .toLowerCase();
  }

  function setButtonBusy(button, busy) {
    if (!button) return;
    if (busy) {
      button.dataset.admBusyPrevDisabled = button.disabled ? "1" : "0";
      button.disabled = true;
      button.classList.add("is-loading");
      return;
    }

    var prevDisabled = button.dataset.admBusyPrevDisabled === "1";
    button.disabled = prevDisabled;
    delete button.dataset.admBusyPrevDisabled;
    button.classList.remove("is-loading");
  }

  function toast(message, type) {
    if (!message) return;
    if (window.VendorUI && typeof window.VendorUI.toast === "function") {
      window.VendorUI.toast(String(message), type || "info");
      return;
    }
    if (window.AdminHelpers && typeof window.AdminHelpers.toast === "function") {
      window.AdminHelpers.toast(String(message), type || "info");
      return;
    }
    // eslint-disable-next-line no-console
    console.info("[AdminForms]", String(message));
  }

  function bindConfirmSubmit(root) {
    var scope = root || document;
    scope.querySelectorAll('form[data-adm-confirm-submit]').forEach(function (form) {
      if (form.dataset.admConfirmBound === "1") return;
      form.dataset.admConfirmBound = "1";
      form.addEventListener(
        "submit",
        function (event) {
          var message = form.getAttribute("data-adm-confirm-submit");
          if (!message) return;
          if (!window.confirm(message)) {
            event.preventDefault();
            event.stopPropagation();
          }
        },
        true
      );
    });
  }

  function dismissAlerts(scope) {
    var host = scope || document;
    var alerts = host.querySelectorAll
      ? host.querySelectorAll('.alert-custom[data-autodismiss="true"]')
      : [];
    if (!alerts.length) return;

    window.setTimeout(function () {
      alerts.forEach(function (alert) {
        alert.style.opacity = "0";
        alert.style.transform = "translateY(-0.5rem)";
        window.setTimeout(function () {
          if (alert && alert.remove) alert.remove();
        }, 300);
      });
    }, 5000);
  }

  function initAdminContent(root) {
    var scope = root && root.nodeType === 1 ? root : document;
    dismissAlerts(scope);
  }

  function confirmAction(message) {
    var content = message || "Etes-vous sur de vouloir effectuer cette action ?";
    return window.confirm(content);
  }

  async function adminPost(url, confirmMessage) {
    if (!url) return false;
    if (confirmMessage && !confirmAction(confirmMessage)) return false;
    try {
      var response = await requestText(url, {
        method: "POST",
        headers: withCsrfHeaders(
          {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
          },
          null
        ),
      });
      if (response.ok) {
        window.location.reload();
        return true;
      }
    } catch (_err) {}
    window.alert("Erreur lors de la modification");
    return false;
  }

  async function copyToClipboard(text, triggerEl) {
    var raw = String(text || "").trim();
    if (!raw) return false;
    var ok = false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(raw);
        ok = true;
      }
    } catch (_err) {}

    if (!ok) {
      var area = document.createElement("textarea");
      area.value = raw;
      area.setAttribute("readonly", "");
      area.style.position = "absolute";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      try {
        ok = document.execCommand("copy");
      } catch (_err) {
        ok = false;
      }
      document.body.removeChild(area);
    }

    if (triggerEl) {
      var original = triggerEl.dataset.copyOriginalLabel || triggerEl.textContent.trim();
      triggerEl.dataset.copyOriginalLabel = original;
      triggerEl.textContent = ok ? "Copie ✅" : "Echec";
      window.setTimeout(function () {
        triggerEl.textContent = original;
      }, 1200);
    }

    return ok;
  }

  function initBaseUtilities() {
    if (window.__ADM_BASE_FORMS_INIT__) return;
    window.__ADM_BASE_FORMS_INIT__ = true;

    var body = document.body;
    if (body) {
      body.setAttribute("data-admBaseFormsInit", "1");
      if (body.dataset) body.dataset.admBaseFormsInit = "1";
    }

    ensureGlobalCsrfToken(null);
    window.adminPost = adminPost;
    window.copyToClipboard = copyToClipboard;
    window.initAdminContent = initAdminContent;

    document.addEventListener(
      "click",
      function (event) {
        var stopEl =
          event.target && event.target.closest ? event.target.closest("[data-stop-nav]") : null;
        if (!stopEl) return;

        var parentAnchor = stopEl.closest("a[href]");
        if (parentAnchor && parentAnchor !== stopEl) {
          event.preventDefault();
        }

        event.stopPropagation();
        if (stopEl.getAttribute("data-stop-nav") === "hard") {
          event.stopImmediatePropagation();
        }
      },
      true
    );

    document.addEventListener(
      "submit",
      function (event) {
        var form = event.target && event.target.matches ? event.target : null;
        if (!form || form.hasAttribute("data-adm-confirm-submit")) return;
        var message = form.getAttribute("data-confirm-submit") || form.getAttribute("data-confirm");
        if (!message) return;
        if (!window.confirm(message)) {
          event.preventDefault();
          event.stopPropagation();
        }
      },
      true
    );

    document.addEventListener(
      "click",
      function (event) {
        var confirmEl =
          event.target && event.target.closest ? event.target.closest("[data-confirm-click]") : null;
        if (confirmEl) {
          var message =
            confirmEl.getAttribute("data-confirm-click") || confirmEl.getAttribute("data-confirm");
          if (message && !window.confirm(message)) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
        }

        var reloadEl =
          event.target && event.target.closest
            ? event.target.closest('[data-action="reload-page"]')
            : null;
        if (reloadEl) {
          event.preventDefault();
          window.location.reload();
          return;
        }

        var closeEl =
          event.target && event.target.closest ? event.target.closest("[data-close-target]") : null;
        if (closeEl) {
          event.preventDefault();
          var selector = closeEl.getAttribute("data-close-target");
          if (!selector) return;
          var target = closeEl.closest(selector) || document.querySelector(selector);
          if (target) target.classList.remove("show");
          return;
        }

        var copyBtn =
          event.target && event.target.closest ? event.target.closest("[data-copy-text]") : null;
        if (!copyBtn) return;
        event.preventDefault();
        if (copyBtn.disabled) return;
        copyToClipboard(copyBtn.getAttribute("data-copy-text") || "", copyBtn).catch(function () {});
      },
      true
    );

    document.addEventListener(
      "change",
      function (event) {
        var autoSubmit =
          event.target && event.target.closest ? event.target.closest(".js-auto-submit") : null;
        if (!autoSubmit || !autoSubmit.form) return;
        autoSubmit.form.submit();
      },
      true
    );

    document.addEventListener(
      "error",
      function (event) {
        var img = event.target;
        if (!img || img.tagName !== "IMG") return;
        var fallbackSrc = img.getAttribute("data-fallback-src");
        if (fallbackSrc && img.getAttribute("src") !== fallbackSrc) {
          img.setAttribute("src", fallbackSrc);
          return;
        }
        if (img.getAttribute("data-img-fallback") === "remove") {
          img.remove();
        }
      },
      true
    );

    var clickDebugEnabled = false;
    try {
      clickDebugEnabled = localStorage.getItem("clickDebug") === "1";
    } catch (_err) {
      clickDebugEnabled = false;
    }
    if (clickDebugEnabled) {
      document.addEventListener(
        "click",
        function (event) {
          var link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
          if (!link) return;
          // eslint-disable-next-line no-console
          console.log("[CLICK]", link.href, link);
        },
        true
      );
    }
  }

  function bindDisableOnSubmit(root) {
    var scope = root || document;
    scope.querySelectorAll('form[data-adm-disable-submit]').forEach(function (form) {
      if (form.dataset.admDisableBound === "1") return;
      form.dataset.admDisableBound = "1";
      form.addEventListener("submit", function () {
        if (isAjaxFormCandidate(form)) return;
        var submitBtn = form.querySelector('[type="submit"]');
        if (submitBtn) {
          setButtonBusy(submitBtn, true);
        }
      });
    });
  }

  function isAjaxFormCandidate(form) {
    if (!form || !form.getAttribute) return false;
    if (form.getAttribute("data-adm-ajax") === "1") return true;
    if (form.getAttribute("data-ajax") === "true" && form.getAttribute("data-adm-action") === "post") return true;
    return false;
  }

  async function handleAjaxFormSubmit(event) {
    var form = event && event.target;
    if (!form || !form.matches || !form.matches("form")) return;
    if (!isAjaxFormCandidate(form)) return;
    if (event.defaultPrevented) return;

    var method = normalizeValue(form.getAttribute("method") || "post");
    if (method !== "post") return;

    event.preventDefault();
    event.stopPropagation();

    if (form.dataset.admAjaxBusy === "1") return;
    form.dataset.admAjaxBusy = "1";

    var submitter = event.submitter || form.querySelector('[type="submit"]');
    setButtonBusy(submitter, true);

    var requestUrl = form.getAttribute("action") || window.location.href;
    var headers = withCsrfHeaders(
      {
        "X-Requested-With": "XMLHttpRequest",
      },
      form
    );

    try {
      var response = await requestText(requestUrl, {
        method: "POST",
        body: new FormData(form),
        headers: headers,
      });

      if (!response.ok) {
        throw new Error(response.error || ("HTTP " + response.status));
      }

      try {
        document.dispatchEvent(
          new CustomEvent("bm:ajax-form-success", {
            detail: {
              form: form,
              url: requestUrl,
              status: response.status,
              responseText: response.data,
            },
          })
        );
      } catch (_err) {}

      var successMode = normalizeValue(form.getAttribute("data-adm-success") || "none");
      if (successMode === "reload") {
        window.location.reload();
        return;
      }
      if (successMode === "redirect") {
        window.location.href = requestUrl;
        return;
      }
    } catch (error) {
      try {
        document.dispatchEvent(
          new CustomEvent("bm:ajax-form-error", {
            detail: {
              form: form,
              url: requestUrl,
              error: String((error && error.message) || "request_failed"),
            },
          })
        );
      } catch (_err) {}
      toast(form.getAttribute("data-adm-error") || "Action impossible. Reessayez.", "error");
    } finally {
      form.dataset.admAjaxBusy = "0";
      setButtonBusy(submitter, false);
    }
  }

  async function handleAjaxPostClick(event) {
    var trigger = event && event.target && event.target.closest ? event.target.closest('[data-adm-action="post"]') : null;
    if (!trigger || !trigger.matches) return;
    if (trigger.closest("form")) return;
    if (event.defaultPrevented) return;

    var requestUrl = String(trigger.getAttribute("data-url") || "").trim();
    if (!requestUrl) return;

    event.preventDefault();
    if (trigger.dataset.admAjaxBusy === "1") return;
    trigger.dataset.admAjaxBusy = "1";
    setButtonBusy(trigger, true);

    var headers = withCsrfHeaders(
      {
        "X-Requested-With": "XMLHttpRequest",
      },
      null
    );

    var body = null;
    var payloadRaw = String(trigger.getAttribute("data-payload") || "").trim();
    if (payloadRaw) {
      try {
        body = JSON.stringify(JSON.parse(payloadRaw));
        headers["Content-Type"] = "application/json";
      } catch (_err) {
        body = payloadRaw;
      }
    }

    try {
      var response = await requestText(requestUrl, {
        method: "POST",
        headers: headers,
        body: body,
      });
      if (!response.ok) {
        throw new Error(response.error || ("HTTP " + response.status));
      }

      var successMode = normalizeValue(trigger.getAttribute("data-adm-success") || "reload");
      if (successMode === "reload") {
        window.location.reload();
        return;
      }
      if (successMode === "redirect") {
        window.location.href = requestUrl;
        return;
      }
    } catch (_error) {
      toast(trigger.getAttribute("data-adm-error") || "Action impossible. Reessayez.", "error");
    } finally {
      trigger.dataset.admAjaxBusy = "0";
      setButtonBusy(trigger, false);
    }
  }

  function init(root) {
    var scope = root || document;
    bindConfirmSubmit(scope);
    bindDisableOnSubmit(scope);
    initAdminContent(scope);
  }

  function autoInit() {
    initBaseUtilities();
    init(document);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit, { once: true });
  } else {
    autoInit();
  }

  document.addEventListener("ajax:page-replaced", function (event) {
    var detail = (event && event.detail) || {};
    var target = detail.target && detail.target.nodeType === 1 ? detail.target : document;
    init(target);
  });

  document.addEventListener("submit", function (event) {
    handleAjaxFormSubmit(event).catch(function () {});
  });

  document.addEventListener("click", function (event) {
    handleAjaxPostClick(event).catch(function () {});
  });

  window.AdminForms = {
    ensureGlobalCsrfToken: ensureGlobalCsrfToken,
    withCsrfHeaders: withCsrfHeaders,
    requestJSON: requestJSON,
    requestText: requestText,
    setButtonBusy: setButtonBusy,
    bindConfirmSubmit: bindConfirmSubmit,
    bindDisableOnSubmit: bindDisableOnSubmit,
    handleAjaxFormSubmit: handleAjaxFormSubmit,
    initAdminContent: initAdminContent,
    copyToClipboard: copyToClipboard,
    adminPost: adminPost,
    initBaseUtilities: initBaseUtilities,
    toast: toast,
    init: init,
    autoInit: autoInit,
  };
})();

