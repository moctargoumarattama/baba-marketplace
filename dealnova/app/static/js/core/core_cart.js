(() => {
  "use strict";

  if (window.__BM_CORE_CART_INIT__) return;
  window.__BM_CORE_CART_INIT__ = true;

  const existing = window.BMCoreCart || {};
  if (existing.__ready && typeof existing.initOrderNotifications === "function") {
    return;
  }

  const initializedBodies = typeof WeakSet !== "undefined" ? new WeakSet() : null;

  function createLocalRequestSeq() {
    let latest = 0;
    return {
      next() {
        latest += 1;
        return latest;
      },
      isLatest(id) {
        return Number(id) === latest;
      },
    };
  }

  function shouldRunNotifyPolling(body) {
    if (!body || !body.dataset) return false;
    if (!body.dataset.notifyUrl) return false;

    const scope = String(body.dataset.notifyScope || "").trim().toLowerCase();
    if (scope === "off") return false;
    if (scope === "all") return true;

    const pageId = String(body.dataset.page || "").trim().toLowerCase();
    const explicitPages = String(body.dataset.notifyPages || "")
      .split(",")
      .map((entry) => String(entry || "").trim().toLowerCase())
      .filter(Boolean);
    if (explicitPages.length) {
      return explicitPages.includes(pageId);
    }

    return (
      pageId.includes("all_orders") ||
      pageId.includes("deliveries") ||
      pageId.includes("fraud") ||
      pageId.includes("courier.panel_orders") ||
      pageId.includes("courier.panel_deliveries")
    );
  }

  async function fallbackRequestJSON(url, options) {
    const opts = Object.assign({}, options || {});
    const response = await fetch(url, opts);
    let data = null;
    try {
      data = await response.json();
    } catch (_parseError) {
      data = null;
    }
    return {
      ok: response.ok,
      status: response.status,
      data,
      error: response.ok ? null : (response.statusText || ("HTTP " + response.status)),
      aborted: false,
      timedOut: false,
    };
  }

  async function requestJSON(url, options) {
    if (window.BMAjaxFetch && typeof window.BMAjaxFetch.requestJSON === "function") {
      return window.BMAjaxFetch.requestJSON(url, options || {});
    }
    try {
      return await fallbackRequestJSON(url, options);
    } catch (error) {
      return {
        ok: false,
        status: 0,
        data: null,
        error: String((error && error.message) || "network_error"),
        aborted: !!(error && error.name === "AbortError"),
        timedOut: false,
      };
    }
  }

  function initOrderNotifications(context) {
    const ctx = context || {};
    const body = ctx.body || document.body;
    const startAdaptivePoll = ctx.startAdaptivePoll;
    const refreshLiveFeatures = ctx.refreshLiveFeatures;
    if (!body || typeof startAdaptivePoll !== "function") return;
    if (!shouldRunNotifyPolling(body)) return;

    if (initializedBodies) {
      if (initializedBodies.has(body)) return;
      initializedBodies.add(body);
    } else if (body.dataset && body.dataset.bmCoreCartBound === "1") {
      return;
    } else if (body.dataset) {
      body.dataset.bmCoreCartBound = "1";
    }

    const notifyUrl = body.dataset.notifyUrl;
    if (!notifyUrl) return;
    const interval = parseInt(body.dataset.notifyInterval || "20000", 10);
    const notifyKey = body.dataset.notifyKey || "adminLastOrderId";

    const orderToast = document.getElementById("admin-order-toast");
    const orderToastText = document.getElementById("admin-order-toast-text");
    const sidebarBadge = document.getElementById("sidebarPendingBadge");
    const sidebarToConfirmBadge = document.getElementById("sidebarToConfirmBadge");
    const navPendingBadge = document.getElementById("navPendingBadge");
    const navToConfirmBadge = document.getElementById("navToConfirmBadge");
    const pendingCountEl = document.getElementById("pendingCount");
    const pendingStatEl = document.getElementById("pendingStat");
    const pendingPill = document.getElementById("pendingPill");
    const toConfirmCountEl = document.getElementById("toConfirmCount");
    const toConfirmStatEl = document.getElementById("toConfirmStat");
    const toConfirmPill = document.getElementById("toConfirmPill");
    const soundToggle = document.getElementById("soundToggle");

    let soundEnabled = localStorage.getItem("adminOrderSound") !== "0";
    let toastTimer = null;
    let activePollController = null;
    const pollRequestSeq = (
      window.BMAjaxGuard &&
      typeof window.BMAjaxGuard.makeRequestSeq === "function"
    )
      ? window.BMAjaxGuard.makeRequestSeq()
      : createLocalRequestSeq();

    function updateSoundToggle() {
      if (!soundToggle) return;
      soundToggle.innerHTML = soundEnabled
        ? '<i class="bi bi-volume-up"></i> Son On'
        : '<i class="bi bi-volume-mute"></i> Son Off';
    }
    updateSoundToggle();

    if (soundToggle) {
      soundToggle.addEventListener("click", () => {
        soundEnabled = !soundEnabled;
        localStorage.setItem("adminOrderSound", soundEnabled ? "1" : "0");
        updateSoundToggle();
      });
    }

    function playPing() {
      if (!soundEnabled) return;
      try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        const audioCtx = new AudioCtx();
        const notes = [880, 1174, 988];
        let t = audioCtx.currentTime;
        notes.forEach((freq) => {
          const osc = audioCtx.createOscillator();
          const gain = audioCtx.createGain();
          osc.type = "sine";
          osc.frequency.value = freq;
          gain.gain.value = 0.0001;
          osc.connect(gain);
          gain.connect(audioCtx.destination);
          osc.start(t);
          gain.gain.exponentialRampToValueAtTime(0.16, t + 0.05);
          gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.3);
          osc.stop(t + 0.32);
          t += 0.12;
        });
      } catch (_error) {}
    }

    function escapeHtml(value) {
      const div = document.createElement("div");
      div.textContent = value == null ? "" : String(value);
      return div.innerHTML;
    }

    function buildItemsText(items) {
      if (!Array.isArray(items) || !items.length) return "";
      const parts = items.slice(0, 3).map((item) => {
        const name = escapeHtml(item.name || "Produit");
        const qty = Number(item.qty || item.quantity || 0);
        return `${name} x${qty}`;
      });
      if (items.length > 3) parts.push(`+${items.length - 3} autres`);
      return parts.join(", ");
    }

    function showOrderToast(pendingCount, message, items) {
      if (!orderToast || !orderToastText) return;
      const itemsText = buildItemsText(items);
      const text =
        message ||
        itemsText ||
        (pendingCount > 0 ? `${pendingCount} commande(s) en attente` : "Nouvelle commande");
      orderToastText.textContent = text;
      orderToast.classList.add("show");
      if (toastTimer) {
        clearTimeout(toastTimer);
      }
      toastTimer = setTimeout(() => {
        orderToast.classList.remove("show");
      }, 3200);
    }

    function updatePending(count) {
      const val = Number(count || 0);
      if (pendingCountEl) pendingCountEl.textContent = val;
      if (pendingStatEl) pendingStatEl.textContent = val;
      if (pendingPill) pendingPill.style.opacity = val > 0 ? "1" : "0.6";
      if (sidebarBadge) {
        sidebarBadge.textContent = val;
        sidebarBadge.classList.toggle("is-hidden", !val);
      }
      if (navPendingBadge) {
        navPendingBadge.textContent = val;
        navPendingBadge.classList.toggle("is-hidden", !val);
      }
    }

    function updateToConfirm(count) {
      const val = Number(count || 0);
      if (toConfirmCountEl) toConfirmCountEl.textContent = val;
      if (toConfirmStatEl) toConfirmStatEl.textContent = val;
      if (toConfirmPill) toConfirmPill.classList.toggle("is-hidden", !val);
      if (sidebarToConfirmBadge) {
        sidebarToConfirmBadge.textContent = val;
        sidebarToConfirmBadge.classList.toggle("is-hidden", !val);
      }
      if (navToConfirmBadge) {
        navToConfirmBadge.textContent = val;
        navToConfirmBadge.classList.toggle("is-hidden", !val);
      }
    }

    // Legacy globals kept for compatibility.
    window.updatePending = updatePending;
    window.updateToConfirm = updateToConfirm;

    let lastNotified = Number(localStorage.getItem(notifyKey) || 0);
    let notifInitialized = false;

    function abortActivePoll() {
      if (!activePollController) return;
      try {
        activePollController.abort();
      } catch (_abortError) {}
    }

    function onVisibilityChange() {
      if (document.hidden) {
        abortActivePoll();
      }
    }
    document.addEventListener("visibilitychange", onVisibilityChange);

    async function pollOrders() {
      if (document.hidden) return;
      abortActivePoll();

      const requestId = pollRequestSeq.next();
      const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
      activePollController = controller;

      try {
        const result = await requestJSON(notifyUrl, {
          cache: "no-store",
          credentials: "same-origin",
          signal: controller ? controller.signal : undefined,
          timeoutMs: 12000,
        });
        if (!pollRequestSeq.isLatest(requestId)) return;
        if (!result || result.aborted || result.timedOut || !result.ok) return;

        const data = result.data;
        if (!data || typeof data !== "object") return;

        updatePending(data.pending_count || 0);
        updateToConfirm(data.to_confirm_count || 0);

        if (!notifInitialized && !lastNotified) {
          lastNotified = data.latest_id || 0;
          localStorage.setItem(notifyKey, String(lastNotified));
          notifInitialized = true;
          return;
        }

        if (data.latest_id && data.latest_id > lastNotified) {
          lastNotified = data.latest_id;
          localStorage.setItem(notifyKey, String(lastNotified));
          showOrderToast(data.pending_count || 0, data.message || "", data.items || []);
          playPing();
        }

        notifInitialized = true;
        if (body.dataset.live === "orders" && typeof refreshLiveFeatures === "function") {
          refreshLiveFeatures();
        }
      } catch (_error) {
      } finally {
        if (pollRequestSeq.isLatest(requestId)) {
          activePollController = null;
        }
      }
    }

    startAdaptivePoll("notify", pollOrders, {
      activeInterval: interval,
      inactiveInterval: Math.max(interval * 3, 30000),
      runWhenHidden: false,
    });
  }

  window.BMCoreCart = Object.assign({}, existing, {
    initOrderNotifications,
    __ready: true,
  });
})();

