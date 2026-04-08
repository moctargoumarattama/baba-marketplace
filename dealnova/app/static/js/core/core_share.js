(function (window, document) {
  "use strict";

  if (window.BMCoreShare) return;

  function showToast(message, type) {
    try {
      if (window.BMCoreUI && typeof window.BMCoreUI.showToast === "function") {
        window.BMCoreUI.showToast(String(message || ""), type || "success");
        return;
      }
    } catch (_error) {}
  }

  function fallbackCopyText(value) {
    try {
      var input = document.createElement("textarea");
      input.value = String(value || "");
      input.setAttribute("readonly", "readonly");
      input.style.position = "fixed";
      input.style.top = "-9999px";
      input.style.left = "-9999px";
      document.body.appendChild(input);
      input.focus();
      input.select();
      var copied = document.execCommand("copy");
      input.remove();
      return !!copied;
    } catch (_error) {
      return false;
    }
  }

  async function copyText(value) {
    var text = String(value || "");
    if (!text) return false;

    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function" && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_error) {}
    }

    return fallbackCopyText(text);
  }

  async function sharePayload(payload, copiedMessage) {
    if (navigator.share && typeof navigator.share === "function") {
      try {
        await navigator.share(payload);
        return { shared: true, copied: false, canceled: false };
      } catch (error) {
        if (error && (error.name === "AbortError" || error.name === "NotAllowedError")) {
          return { shared: false, copied: false, canceled: true };
        }
      }
    }

    var copied = await copyText(payload && payload.url ? payload.url : window.location.href);
    if (copied) {
      showToast(copiedMessage || "Lien copie", "success");
    } else {
      showToast("Impossible de copier le lien", "error");
    }
    return { shared: false, copied: copied, canceled: false };
  }

  async function onShareButtonClick(event) {
    event.preventDefault();

    var button = event.currentTarget;
    if (!button) return;

    var payload = {
      title: button.getAttribute("data-share-title") || document.title,
      text: button.getAttribute("data-share-text") || document.title,
      url: button.getAttribute("data-share-url") || window.location.href
    };

    await sharePayload(payload, button.getAttribute("data-share-copied-message") || "Lien copie");
  }

  function bind(root) {
    var scope = root && typeof root.querySelectorAll === "function" ? root : document;
    scope.querySelectorAll("[data-share-button]").forEach(function (button) {
      if (button.dataset.shareBound === "1") return;
      button.dataset.shareBound = "1";
      button.addEventListener("click", onShareButtonClick);
    });
  }

  window.BMCoreShare = {
    bind: bind,
    sharePayload: sharePayload
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { bind(document); }, { once: true });
  } else {
    bind(document);
  }

  document.addEventListener("ajax:page-replaced", function (event) {
    bind((event && event.target) || document);
  });
})(window, document);
