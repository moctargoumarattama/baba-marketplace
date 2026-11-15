(() => {
  if (typeof window === "undefined") return;
  const existing = window.BMCoreLive || {};
  if (existing.__loaded) return;

  const pollers = new Map();
  let ajaxSubmitBound = false;
  let visibilityRefreshBound = false;
  const noop = () => {};

  function ensureGlobalApi(name, implementation) {
    if (typeof window[name] === "function") return window[name];
    const fn = typeof implementation === "function" ? implementation : noop;
    window[name] = fn;
    return fn;
  }

  // Global APIs are always present to avoid "is not a function" on legacy pages.
  ensureGlobalApi("initFraudPage");
  ensureGlobalApi("updatePending");
  ensureGlobalApi("updateToConfirm");
  ensureGlobalApi("initLiveFeatures");

  const ui = window.BMCoreUI || {};

  const showToast =
    typeof ui.showToast === "function" ? ui.showToast : () => {};
  const showAlert =
    typeof ui.showAlert === "function" ? ui.showAlert : (message) => {
      if (message) window.alert(message);
    };
  const setButtonLoading =
    typeof ui.setButtonLoading === "function"
      ? ui.setButtonLoading
      : () => {};
  const applyToggleState =
    typeof ui.applyToggleState === "function"
      ? ui.applyToggleState
      : () => {};
  const updateBadge =
    typeof ui.updateBadge === "function" ? ui.updateBadge : () => {};
  const removeClosest =
    typeof ui.removeClosest === "function" ? ui.removeClosest : () => {};

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    if (window.csrfToken) return window.csrfToken;
    return "";
  }

  function startLongActionHints(action, submitBtn) {
    const deleteActions = new Set(["delete-user", "delete-shop", "delete-product"]);
    if (!deleteActions.has(String(action || ""))) return () => {};

    const timers = [];
    const hints = [
      { delayMs: 2200, message: "Suppression en cours..." },
      { delayMs: 6000, message: "Nettoyage des donnees associees..." },
      { delayMs: 12000, message: "Finalisation... merci de patienter." },
    ];

    hints.forEach((hint) => {
      const timer = window.setTimeout(() => {
        if (!submitBtn || !submitBtn.isConnected || !submitBtn.disabled) return;
        showToast(hint.message, "info");
      }, hint.delayMs);
      timers.push(timer);
    });

    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }

  function renderStatus(status) {
    if (status === "pending") {
      return '<span class="status-pill status-pending"><i class="bi bi-clock"></i> En attente</span>';
    }
    if (status === "delivered") {
      return '<span class="status-pill status-delivered"><i class="bi bi-check-circle"></i> Livree</span>';
    }
    if (status === "cancelled") {
      return '<span class="status-pill status-cancelled"><i class="bi bi-x-circle"></i> Annulee</span>';
    }
    return `<span class="status-pill status-pending">${status || ""}</span>`;
  }

  function updateOrderRow(orderId, status) {
    if (!orderId) return;
    const row = document.querySelector(`[data-order-id="${orderId}"]`);
    if (!row) return;
    const statusEl = row.querySelector("[data-order-status]");
    if (statusEl) statusEl.innerHTML = renderStatus(status);
    row.classList.toggle("order-row-pending", status === "pending");
    if (row.dataset.orderSection === "pending" && status !== "pending") {
      row.remove();
    }
  }

  async function refreshSectionFromCurrentPage(selector) {
    const cssSelector = String(selector || "").trim();
    if (!cssSelector) return false;
    const currentNode = document.querySelector(cssSelector);
    if (!currentNode) return false;

    try {
      const res = await fetch(window.location.href, {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "fetch",
          Accept: "text/html",
        },
      });
      if (!res.ok) return false;
      const html = await res.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, "text/html");
      const nextNode = doc.querySelector(cssSelector);
      if (!nextNode) return false;
      currentNode.replaceWith(nextNode);
      document.dispatchEvent(
        new CustomEvent("ajax:page-replaced", {
          detail: { selector: cssSelector },
        })
      );
      return true;
    } catch (_error) {
      return false;
    }
  }

  async function handleAjaxForm(form) {
    const confirmMessage = form.dataset.confirm;
    if (confirmMessage && !window.confirm(confirmMessage)) return;

    const submitBtn = form.querySelector('button[type="submit"]');
    setButtonLoading(submitBtn, true);
    const action = String(form.dataset.action || "");
    const stopLongActionHints = startLongActionHints(action, submitBtn);

    const formData = new FormData(form);
    const csrfToken = getCsrfToken();

    try {
      const res = await fetch(form.action, {
        method: form.method || "POST",
        body: formData,
        headers: {
          "X-Requested-With": "fetch",
          "X-CSRFToken": csrfToken,
          Accept: "application/json",
        },
      });

      let data = {};
      try {
        data = await res.json();
      } catch (_error) {
        data = {};
      }

      if (!res.ok || data.success === false) {
        const msg = data.message || "Erreur lors de la modification.";
        showAlert(msg, "error");
        stopLongActionHints();
        setButtonLoading(submitBtn, false);
        return;
      }

      const successMsg = data.message || form.dataset.successMessage;
      if (successMsg) {
        showToast(successMsg, "success");
      } else if (action) {
        showToast("Action effectuee", "success");
      }

      if (action === "toggle-user") {
        const isActive = !!data.is_active;
        applyToggleState(submitBtn, isActive);
        if (data.user_id) {
          document
            .querySelectorAll(`[data-user-status="${data.user_id}"]`)
            .forEach((el) => updateBadge(el, isActive));
        }
      } else if (
        action === "delete-user" ||
        action === "delete-shop" ||
        action === "delete-product"
      ) {
        const shouldRedirect = form.dataset.redirect === "true";
        if (shouldRedirect && data.redirect_url) {
          window.location.href = data.redirect_url;
        } else {
          removeClosest(form, form.dataset.removeTarget || "tr");
        }
      } else if (action === "toggle-shop" || action === "toggle-vendor-shop") {
        const isActive = !!data.is_active;
        applyToggleState(submitBtn, isActive);
        if (data.shop_id) {
          document
            .querySelectorAll(`[data-shop-status="${data.shop_id}"]`)
            .forEach((el) => updateBadge(el, isActive));
        }
      } else if (action === "add-to-cart") {
        if (data && Object.prototype.hasOwnProperty.call(data, "cart_count")) {
          const count = Math.max(0, Number(data.cart_count || 0));
          const hasItems = count > 0;
          document.querySelectorAll("[data-cart-badge], [data-drawer-cart-badge]").forEach((el) => {
            el.textContent = String(count);
            el.classList.toggle("d-none", !hasItems);
          });
        }
        if (data.redirect_url) {
          window.location.href = data.redirect_url;
          return;
        }
      } else if (action === "order-status") {
        const fallbackOrderId = form.dataset.orderId || 0;
        updateOrderRow(data.order_id || Number(fallbackOrderId), data.status);
      }

      const refreshTarget = String(form.dataset.refreshTarget || "").trim();
      if (refreshTarget) {
        await refreshSectionFromCurrentPage(refreshTarget);
      }

      document.dispatchEvent(
        new CustomEvent("bm:ajax-form-success", {
          detail: { form, action: action || "", data },
        })
      );

      stopLongActionHints();
      setButtonLoading(submitBtn, false);
    } catch (_error) {
      showAlert("Erreur lors de la requete.", "error");
      stopLongActionHints();
      setButtonLoading(submitBtn, false);
    }
  }

  function bindAjaxSubmitOnce() {
    if (ajaxSubmitBound) return;
    ajaxSubmitBound = true;
    document.addEventListener("submit", (e) => {
      const form = e.target;
      if (!form || form.dataset.ajax !== "true") return;
      e.preventDefault();
      handleAjaxForm(form);
    });
  }

  function stopPoller(key) {
    const poller = pollers.get(key);
    if (poller && typeof poller.stop === "function") poller.stop();
    pollers.delete(key);
  }

  function startAdaptivePoll(key, fn, options) {
    stopPoller(key);
    const config = options || {};
    const activeInterval = Number(config.activeInterval || 5000);
    const inactiveInterval = Number(
      config.inactiveInterval || Math.max(activeInterval * 3, 30000)
    );
    const runWhenHidden = !!config.runWhenHidden;
    const pauseWhenHidden = config.pauseWhenHidden !== false;
    let timer = null;
    let stopped = false;
    let inFlight = false;

    function clearTimer() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    }

    function schedule(delayMs) {
      clearTimer();
      timer = setTimeout(() => tick(false), Math.max(1000, Number(delayMs) || activeInterval));
    }

    async function tick(force) {
      if (stopped) return;
      if (inFlight) return;
      const hidden = document.hidden;
      if (hidden && !runWhenHidden && pauseWhenHidden && !force) {
        clearTimer();
        return;
      }
      if (force || !hidden || runWhenHidden) {
        inFlight = true;
        try {
          await fn();
        } catch (_error) {}
        inFlight = false;
      }
      if (stopped) return;
      if (document.hidden && !runWhenHidden && pauseWhenHidden) {
        clearTimer();
        return;
      }
      const interval = document.hidden ? inactiveInterval : activeInterval;
      schedule(interval);
    }

    tick(true);
    const poller = {
      stop() {
        stopped = true;
        clearTimer();
      },
      refresh() {
        if (!stopped) tick(true);
      },
      pause() {
        clearTimer();
      },
    };
    pollers.set(key, poller);
    return poller;
  }

  function bindVisibilityRefreshOnce() {
    if (visibilityRefreshBound) return;
    visibilityRefreshBound = true;
    document.addEventListener("visibilitychange", () => {
      pollers.forEach((poller) => {
        if (!poller) return;
        if (document.hidden) {
          if (typeof poller.pause === "function") poller.pause();
          return;
        }
        if (typeof poller.refresh === "function") poller.refresh();
      });
    });
  }

  function initLiveFeatures() {
    stopPoller("deliveries");
  }

  function init() {
    if (window.__BM_LIVE_INIT__ || window._BM_LIVE_INIT) return;
    window.__BM_LIVE_INIT__ = true;
    // Legacy alias kept for safety.
    window._BM_LIVE_INIT = true;

    bindAjaxSubmitOnce();
    bindVisibilityRefreshOnce();
    initLiveFeatures();
  }

  window.initLiveFeatures = initLiveFeatures;
  window.BMCoreLive = {
    init,
    initLiveFeatures,
    startAdaptivePoll,
    stopPoller,
    handleAjaxForm,
    __loaded: true,
  };

  // Auto-init to replace the old live.js shim seamlessly
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
      init();
    }
  }
})();

