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

  function fallbackCopyText(value, source) {
    var input;
    var previous = document.activeElement;
    try {
      input = document.createElement("textarea");
      input.value = String(value || "");
      input.setAttribute("readonly", "readonly");
      input.style.position = "fixed";
      input.style.top = "-9999px";
      input.style.left = "-9999px";
      // The page outside an open sheet is inert; keep the copy field inside it.
      var anchor = source || previous;
      var dialog = anchor && anchor.closest('[role="dialog"]');
      (dialog || document.body).appendChild(input);
      input.focus({ preventScroll: true });
      input.select();
      input.setSelectionRange(0, input.value.length);
      var copied = document.execCommand("copy");
      return !!copied;
    } catch (_error) {
      return false;
    } finally {
      if (input) input.remove();
      if (previous && previous.isConnected && typeof previous.focus === "function") {
        previous.focus({ preventScroll: true });
      }
    }
  }

  async function copyText(value, source) {
    var text = String(value || "");
    if (!text) return false;

    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function" && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_error) {}
    }

    if (source && !isCurrentSource({ url: text }, source)) return false;
    return fallbackCopyText(text, source);
  }

  function isCurrentSource(payload, source) {
    if (!source) return true;
    if (!source.isConnected || source.closest('[inert], [aria-hidden="true"]')) return false;
    return (source.getAttribute("data-share-url") || window.location.href) === payload.url;
  }

  async function sharePayload(payload, copiedMessage, source) {
    if (navigator.share && typeof navigator.share === "function") {
      try {
        await navigator.share(payload);
        return { shared: true, copied: false, canceled: false };
      } catch (error) {
        if (error && error.name === "AbortError") {
          return { shared: false, copied: false, canceled: true };
        }
      }
    }

    if (!isCurrentSource(payload, source)) {
      return { shared: false, copied: false, canceled: true };
    }
    var copied = await copyText(payload && payload.url ? payload.url : window.location.href, source);
    if (isCurrentSource(payload, source)) {
      showToast(copied ? (copiedMessage || "Lien copié") : "Impossible de copier le lien", copied ? "success" : "error");
    }
    return { shared: false, copied: copied, canceled: false };
  }

  function statusFor(button) {
    if (button.__shareStatus && button.__shareStatus.isConnected) return button.__shareStatus;
    var status = document.createElement("span");
    status.className = "visually-hidden";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("aria-atomic", "true");
    status.setAttribute("data-share-status", "");
    button.insertAdjacentElement("afterend", status);
    button.__shareStatus = status;
    return status;
  }

  async function onShareButtonClick(event) {
    var button = event.target.closest && event.target.closest("[data-share-button]");
    if (!button) return;
    event.preventDefault();
    if (button.disabled || button.__sharePending || button.getAttribute("aria-disabled") === "true") return;

    var payload = {
      title: button.getAttribute("data-share-title") || document.title,
      text: button.getAttribute("data-share-text") || document.title,
      url: button.getAttribute("data-share-url") || window.location.href
    };

    var status = statusFor(button);
    status.textContent = "";
    var copiedMessage = button.getAttribute("data-share-copied-message") || "Lien copié";
    button.__sharePending = true;
    button.setAttribute("aria-busy", "true");
    button.setAttribute("aria-disabled", "true");
    try {
      var result = await sharePayload(payload, copiedMessage, button);
      // A sheet can be reused for another offer while a native share is pending.
      if (isCurrentSource(payload, button)) {
        if (result.copied) status.textContent = copiedMessage;
        else if (!result.shared && !result.canceled) status.textContent = "Impossible de copier le lien";
      }
    } finally {
      button.__sharePending = false;
      if (button.hasAttribute("data-share-ready")) {
        button.disabled = button.getAttribute("data-share-ready") === "0";
      }
      button.removeAttribute("aria-busy");
      button.removeAttribute("aria-disabled");
    }
  }

  function bind(root) {
    var scope = root && typeof root.querySelectorAll === "function" ? root : document;
    scope.querySelectorAll("[data-share-button]").forEach(function (button) {
      statusFor(button);
    });
  }

  window.BMCoreShare = {
    bind: bind,
    sharePayload: sharePayload
  };

  document.addEventListener("click", onShareButtonClick);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { bind(document); }, { once: true });
  } else {
    bind(document);
  }

  document.addEventListener("ajax:page-replaced", function (event) {
    bind((event && event.target) || document);
  });
})(window, document);
