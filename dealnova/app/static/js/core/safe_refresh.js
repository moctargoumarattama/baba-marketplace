(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.BMSafeRefresh && window.BMSafeRefresh.__loaded) return;

  const DEBUG = (function () {
    try {
      return localStorage.getItem("safeRefreshDebug") === "1";
    } catch (_error) {
      return false;
    }
  })();

  const STALE_AFTER_HIDDEN_MS = 6 * 60 * 1000;
  const INTERACTION_COOLDOWN_MS = 1600;
  const PENDING_FORM_TTL_MS = 25000;
  const MIN_REFRESH_GAP_MS = 20000;
  const MAX_DEFERRAL_ATTEMPTS = 90;
  const EXCLUDED_PATH_PREFIXES = [
    "/cart/checkout",
    "/checkout",
    "/payment",
    "/login",
    "/register",
    "/vendor/access",
  ];

  const pendingForms = new Set();
  let lastInteractionAt = 0;
  let lastRefreshAt = 0;
  let hiddenSince = null;
  let pendingReason = "";
  let pendingTimer = null;
  let pendingAttempts = 0;

  function log() {
    if (!DEBUG || !window.console || typeof window.console.log !== "function") return;
    const args = Array.prototype.slice.call(arguments);
    args.unshift("[safe-refresh]");
    window.console.log.apply(window.console, args);
  }

  function now() {
    return Date.now();
  }

  function currentPathname() {
    try {
      return window.location.pathname || "/";
    } catch (_error) {
      return "/";
    }
  }

  function isPathExcluded(pathname) {
    const path = String(pathname || "").trim();
    if (!path) return false;
    return EXCLUDED_PATH_PREFIXES.some(function (prefix) {
      return path === prefix || path.startsWith(prefix + "/");
    });
  }

  function markInteraction() {
    lastInteractionAt = now();
  }

  function isEditableField(node) {
    if (!node || node.nodeType !== 1) return false;
    if (node.isContentEditable) return true;

    const tag = String(node.tagName || "").toUpperCase();
    if (tag === "TEXTAREA" || tag === "SELECT") return true;
    if (tag !== "INPUT") return false;
    if (node.disabled || node.readOnly) return false;

    const type = String(node.getAttribute("type") || "text").toLowerCase();
    if (
      type === "button" ||
      type === "submit" ||
      type === "reset" ||
      type === "checkbox" ||
      type === "radio" ||
      type === "file" ||
      type === "image" ||
      type === "hidden" ||
      type === "range" ||
      type === "color"
    ) {
      return false;
    }
    return true;
  }

  function hasActiveEditor() {
    return isEditableField(document.activeElement);
  }

  function hasRecentInteraction() {
    return now() - lastInteractionAt < INTERACTION_COOLDOWN_MS;
  }

  function readControlValue(control) {
    if (!control || control.disabled) return "";
    const tag = String(control.tagName || "").toUpperCase();
    if (tag === "TEXTAREA" || tag === "SELECT") {
      if (tag === "SELECT" && control.multiple) {
        const selected = [];
        const options = control.options || [];
        for (let i = 0; i < options.length; i += 1) {
          if (options[i].selected) selected.push(options[i].value);
        }
        return selected.join("||");
      }
      return String(control.value || "");
    }
    if (tag !== "INPUT") return "";

    const type = String(control.getAttribute("type") || "text").toLowerCase();
    if (type === "checkbox" || type === "radio") {
      return control.checked ? "1" : "0";
    }
    return String(control.value || "");
  }

  function ensureControlBaseline(control) {
    if (!control || !control.getAttribute) return "";
    const key = "data-safe-refresh-initial";
    let baseline = control.getAttribute(key);
    if (baseline !== null) return baseline;
    baseline = readControlValue(control);
    control.setAttribute(key, baseline);
    return baseline;
  }

  function controlIsDirty(control) {
    if (!control || control.disabled) return false;

    const tag = String(control.tagName || "").toUpperCase();
    if (tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") return false;

    if (tag === "INPUT") {
      const type = String(control.getAttribute("type") || "text").toLowerCase();
      if (
        type === "button" ||
        type === "submit" ||
        type === "reset" ||
        type === "hidden" ||
        type === "image" ||
        type === "file"
      ) {
        return false;
      }
    }

    const currentValue = readControlValue(control);
    const baselineValue = ensureControlBaseline(control);
    if (baselineValue === null || baselineValue === "") {
      return currentValue !== "";
    }
    return currentValue !== baselineValue;
  }

  function formIsDirty(form) {
    if (!form || form.getAttribute("data-safe-refresh-ignore-dirty") === "1") return false;
    const controls = form.elements ? Array.prototype.slice.call(form.elements) : [];
    for (let i = 0; i < controls.length; i += 1) {
      if (controlIsDirty(controls[i])) return true;
    }
    return false;
  }

  function hasDirtyForms() {
    const forms = document.forms ? Array.prototype.slice.call(document.forms) : [];
    for (let i = 0; i < forms.length; i += 1) {
      if (formIsDirty(forms[i])) return true;
    }
    return false;
  }

  function nodeIsVisible(node) {
    if (!node || node.nodeType !== 1) return false;
    if (node.hidden) return false;
    if (node.getAttribute("aria-hidden") === "true") return false;
    if (node.classList.contains("hidden")) return false;
    const style = window.getComputedStyle ? window.getComputedStyle(node) : null;
    if (!style) return true;
    return style.display !== "none" && style.visibility !== "hidden";
  }

  function hasVisibleNode(selector) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      if (nodeIsVisible(nodes[i])) return true;
    }
    return false;
  }

  function hasBlockingOverlay() {
    if (hasVisibleNode("[data-safe-refresh-lock='1']")) return true;
    if (hasVisibleNode(".modal.show")) return true;
    if (hasVisibleNode(".offcanvas.show")) return true;
    if (hasVisibleNode("[aria-modal='true']")) return true;
    if (hasVisibleNode("#mainNavbar.show")) return true;
    if (hasVisibleNode("#installModal")) return true;
    return false;
  }

  function hasPendingSubmissions() {
    if (pendingForms.size > 0) return true;
    return Boolean(document.querySelector("form[data-safe-refresh-submitting='1']"));
  }

  function canRefreshNow() {
    if (document.hidden) return { ok: false, reason: "hidden" };
    if (isPathExcluded(currentPathname())) return { ok: false, reason: "excluded_path" };
    if (hasActiveEditor()) return { ok: false, reason: "active_editor" };
    if (hasRecentInteraction()) return { ok: false, reason: "recent_interaction" };
    if (hasPendingSubmissions()) return { ok: false, reason: "pending_submission" };
    if (hasDirtyForms()) return { ok: false, reason: "dirty_form" };
    if (hasBlockingOverlay()) return { ok: false, reason: "overlay_open" };
    if (now() - lastRefreshAt < MIN_REFRESH_GAP_MS) return { ok: false, reason: "cooldown" };
    return { ok: true, reason: "ready" };
  }

  function triggerReload(reason) {
    lastRefreshAt = now();
    log("reload", reason || "unknown");
    try {
      window.location.reload();
    } catch (_error) {
      window.location.href = window.location.href;
    }
  }

  function clearPendingTimer() {
    if (!pendingTimer) return;
    window.clearTimeout(pendingTimer);
    pendingTimer = null;
  }

  function nextRetryDelay() {
    return Math.min(700 + pendingAttempts * 350, 5000);
  }

  function flushPendingRequest() {
    clearPendingTimer();
    if (!pendingReason) return;

    const verdict = canRefreshNow();
    if (verdict.ok) {
      const reason = pendingReason;
      pendingReason = "";
      pendingAttempts = 0;
      triggerReload(reason);
      return;
    }

    pendingAttempts += 1;
    if (pendingAttempts > MAX_DEFERRAL_ATTEMPTS) {
      log("drop_pending_refresh", { reason: pendingReason, blocked_by: verdict.reason });
      pendingReason = "";
      pendingAttempts = 0;
      return;
    }

    log("defer", { reason: pendingReason, blocked_by: verdict.reason, attempt: pendingAttempts });
    pendingTimer = window.setTimeout(flushPendingRequest, nextRetryDelay());
  }

  function scheduleFlush(delayMs) {
    if (pendingTimer) return;
    const delay = Math.max(120, Number(delayMs) || 0);
    pendingTimer = window.setTimeout(flushPendingRequest, delay);
  }

  function request(reason, options) {
    const opts = options || {};
    const nextReason = String(reason || "").trim();
    if (nextReason) {
      pendingReason = nextReason;
    } else if (!pendingReason) {
      pendingReason = "safe_refresh";
    }
    if (opts.replaceReason) {
      pendingAttempts = 0;
    }
    scheduleFlush(opts.delayMs || 0);
  }

  function clearPendingForms() {
    pendingForms.clear();
    const flagged = document.querySelectorAll("form[data-safe-refresh-submitting='1']");
    for (let i = 0; i < flagged.length; i += 1) {
      flagged[i].removeAttribute("data-safe-refresh-submitting");
    }
  }

  function onSubmit(event) {
    const form = event && event.target && event.target.matches && event.target.matches("form")
      ? event.target
      : null;
    if (!form) return;

    pendingForms.add(form);
    form.setAttribute("data-safe-refresh-submitting", "1");
    markInteraction();

    window.setTimeout(function () {
      pendingForms.delete(form);
      if (form && form.removeAttribute) {
        form.removeAttribute("data-safe-refresh-submitting");
      }
    }, PENDING_FORM_TTL_MS);
  }

  function onVisibilityChange() {
    if (document.hidden) {
      hiddenSince = now();
      return;
    }

    const hiddenDuration = hiddenSince ? now() - hiddenSince : 0;
    hiddenSince = null;

    if (hiddenDuration >= STALE_AFTER_HIDDEN_MS) {
      request("resume_stale_page", { delayMs: 180, replaceReason: true });
      return;
    }
    if (pendingReason) {
      scheduleFlush(120);
    }
  }

  function onFocus() {
    if (!pendingReason) return;
    scheduleFlush(120);
  }

  function onOnline() {
    if (!pendingReason) return;
    scheduleFlush(260);
  }

  function bootstrapControlBaselines() {
    const controls = document.querySelectorAll("input, textarea, select");
    for (let i = 0; i < controls.length; i += 1) {
      ensureControlBaseline(controls[i]);
    }
  }

  document.addEventListener("input", markInteraction, true);
  document.addEventListener("change", markInteraction, true);
  document.addEventListener("keydown", markInteraction, true);
  document.addEventListener("submit", onSubmit, true);
  document.addEventListener("bm:ajax:response", clearPendingForms);
  document.addEventListener("bm:ajax-form-success", clearPendingForms);
  document.addEventListener("bm:ajax-form-error", clearPendingForms);
  window.addEventListener("focus", onFocus);
  window.addEventListener("online", onOnline);
  document.addEventListener("visibilitychange", onVisibilityChange);
  document.addEventListener("DOMContentLoaded", bootstrapControlBaselines, { once: true });
  window.addEventListener("pageshow", bootstrapControlBaselines);

  window.BMSafeRefresh = {
    __loaded: true,
    request: request,
    canRefreshNow: canRefreshNow,
    flush: flushPendingRequest,
    hasPendingRequest: function () {
      return Boolean(pendingReason);
    },
    debugState: function () {
      return {
        pendingReason: pendingReason,
        pendingAttempts: pendingAttempts,
        pendingForms: pendingForms.size,
        hiddenSince: hiddenSince,
        lastInteractionAt: lastInteractionAt,
        lastRefreshAt: lastRefreshAt,
      };
    },
    EXCLUDED_PATH_PREFIXES: EXCLUDED_PATH_PREFIXES.slice(),
  };
})();
