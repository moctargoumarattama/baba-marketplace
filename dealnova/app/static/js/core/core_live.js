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
  const dom = window.BMCoreDom || {};

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

  const escapeHtml =
    typeof dom.escapeHtml === "function"
      ? dom.escapeHtml
      : (value) => {
          const div = document.createElement("div");
          div.textContent = value == null ? "" : String(value);
          return div.innerHTML;
        };
  const safeUrl =
    typeof dom.safeUrl === "function"
      ? dom.safeUrl
      : (url) => {
          const u = String(url || "");
          return u.startsWith("/") || u.startsWith("http://") || u.startsWith("https://")
            ? u
            : "#";
        };

  function currentBody() {
    return document.body;
  }

  function getPageId() {
    const body = currentBody();
    if (!body || !body.dataset) return "";
    return String(body.dataset.page || "").trim().toLowerCase();
  }

  function isLiveDebugEnabled() {
    try {
      return window.localStorage && window.localStorage.getItem("liveDebug") === "1";
    } catch (_error) {
      return false;
    }
  }

  function logMissingLiveUrl(scopeName, body) {
    if (!isLiveDebugEnabled()) return;
    const pageId = body && body.dataset ? body.dataset.page || "" : "";
    // eslint-disable-next-line no-console
    console.log("[BM live] liveUrl missing", { scope: scopeName, page: pageId });
  }

  function inferLiveType(pageId, explicitType) {
    const liveType = String(explicitType || "").trim().toLowerCase();
    if (liveType) return liveType;
    if (pageId === "admin.deliveries") {
      return "deliveries";
    }
    return "";
  }

  function canRunHeavyLive(pageId, liveType) {
    const body = currentBody();
    if (!liveType) return false;
    if (liveType !== "orders" && liveType !== "deliveries") return false;
    if (body && body.dataset && body.dataset.liveForce === "1") return true;
    if (!pageId) return true; // Legacy fallback if page flag is missing.
    return (
      pageId.startsWith("admin.") ||
      pageId.startsWith("admin_users.")
    );
  }

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    if (window.csrfToken) return window.csrfToken;
    return "";
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
        setButtonLoading(submitBtn, false);
        return;
      }

      const action = form.dataset.action;
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

      setButtonLoading(submitBtn, false);
    } catch (_error) {
      showAlert("Erreur lors de la requete.", "error");
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

  function initDeliveriesLive() {
    const body = currentBody();
    if (!body) return;
    const liveUrl = body.dataset.liveUrl;
    if (!liveUrl) {
      logMissingLiveUrl("deliveries", body);
      return;
    }

    const deliveriesPage = document.querySelector('[data-deliveries-page="true"]');
    if (!deliveriesPage) return;
    let readOnly = deliveriesPage.dataset.readOnly === "1";

    const pendingTableBody = document.getElementById("pendingTableBody");
    const historyTableBody = document.getElementById("historyTableBody");
    const pendingCountLabel = document.getElementById("pendingCountLabel");
    const historyTotalLabel = document.getElementById("historyTotalLabel");
    const pendingStat = document.getElementById("pendingStat");
    const deliveredStat = document.getElementById("deliveredStat");
    const commissionStat = document.getElementById("commissionStat");

    function getValue(name) {
      const el = document.querySelector(`[name="${name}"]`);
      return el ? el.value : "";
    }

    function buildQuery() {
      const params = new URLSearchParams();
      const page =
        deliveriesPage.dataset.page ||
        new URLSearchParams(window.location.search).get("page") ||
        "1";
      params.set("page", page);

      const fields = [
        "range",
        "order_status",
        "delivery_status",
        "date_from",
        "date_to",
        "city",
        "client",
        "phone",
      ];
      fields.forEach((field) => {
        params.set(field, getValue(field) || "");
      });
      return params.toString();
    }

    function buildLiveUrl(query) {
      const url = new URL(liveUrl, window.location.origin);
      const params = new URLSearchParams(query);
      params.forEach((value, key) => {
        if (!value) {
          url.searchParams.delete(key);
        } else {
          url.searchParams.set(key, value);
        }
      });
      return `${url.pathname}?${url.searchParams.toString()}`;
    }

    function renderDeliveryStatus(order) {
      var orderStatus = String((order && order.status) || "").toLowerCase();
      var deliveryStatus = String((order && order.delivery_status) || "").toLowerCase();

      if (orderStatus === "delivered" || deliveryStatus === "delivered") {
        return '<span class="status-pill status-delivered"><i class="bi bi-check-circle"></i> Livree</span>';
      }
      if (orderStatus === "cancelled" || deliveryStatus === "canceled") {
        return '<span class="status-pill status-cancelled"><i class="bi bi-x-circle"></i> Annulee</span>';
      }
      if (orderStatus === "pending") {
        return '<span class="status-pill status-pending"><i class="bi bi-clock"></i> En attente</span><div class="small text-muted mt-1">Livraison: Nouvelle</div>';
      }
      return `<span class="status-pill status-pending">${escapeHtml(orderStatus || deliveryStatus || "pending")}</span>`;
    }

    function renderPendingRow(order) {
      const canMutate = !readOnly && !!order.can_mutate;
      const item = escapeHtml(order.special_item || "Livraison express");
      const pickup = escapeHtml(order.pickup_address || "");
      const fullName = escapeHtml(order.full_name || "");
      const phone = escapeHtml(order.phone || "");
      const city = escapeHtml(order.city || "");
      const detailUrl = safeUrl(order.detail_url);
      const callUrl = safeUrl(order.call_url);
      const deliverUrl = safeUrl(order.deliver_url);
      const cancelUrl = safeUrl(order.cancel_url);
      const deliveryPrice = Number(order.delivery_price || 0).toFixed(2);
      const babaFee = Number(order.delivery_platform_fee || 0).toFixed(2);
      const babaSettled = !!order.baba_fee_settled;
      const csrfToken = getCsrfToken();
      const babaCell = `<span class="badge bg-warning text-dark">${babaFee} MAD</span>${
        babaSettled ? '<div class="small text-success">Remis</div>' : ""
      }`;
      const mutateActions = canMutate
        ? `
              <form method="POST" action="${deliverUrl}" class="d-inline" data-ajax="true" data-action="order-status" data-order-id="${order.id}">
                <input type="hidden" name="csrf_token" value="${csrfToken}">
                <button class="btn btn-success btn-sm" type="submit">
                  <i class="bi bi-check-circle me-1"></i>Livree
                </button>
              </form>
              <form method="POST" action="${cancelUrl}" class="d-inline" data-ajax="true" data-action="order-status" data-order-id="${order.id}" data-confirm="Annuler cette livraison ?">
                <input type="hidden" name="csrf_token" value="${csrfToken}">
                <button class="btn btn-outline-danger btn-sm" type="submit">
                  <i class="bi bi-x-circle me-1"></i>Annuler
                </button>
              </form>
            `
        : '<span class="badge text-bg-secondary align-self-center">Lecture seule</span>';
      return `
        <tr class="order-row-pending" data-order-id="${order.id}" data-order-section="pending">
          <td>${order.id}</td>
          <td>
            <div class="fw-semibold">${fullName}</div>
            <small class="text-muted">${phone}</small>
          </td>
          <td>${city}</td>
          <td><div class="list-text">${item}</div></td>
          <td><div class="list-text">${pickup || "-"}</div></td>
          <td>${Number(order.total || 0).toFixed(2)} MAD</td>
          <td>${deliveryPrice} MAD</td>
          <td>${babaCell}</td>
          <td class="order-actions">
            <div class="d-flex gap-2 flex-wrap">
              <a href="${detailUrl}" class="btn btn-sm btn-primary">
                <i class="bi bi-eye"></i>
              </a>
              <a href="${callUrl}" class="btn btn-sm btn-outline-primary">
                <i class="bi bi-telephone"></i>
              </a>
              ${mutateActions}
            </div>
          </td>
        </tr>
      `;
    }

    function renderHistoryRow(order) {
      const canMutate = !readOnly && !!order.can_mutate;
      const item = escapeHtml(order.special_item || "Livraison express");
      const pickup = escapeHtml(order.pickup_address || "");
      const statusCell = renderDeliveryStatus(order);
      const fullName = escapeHtml(order.full_name || "");
      const phone = escapeHtml(order.phone || "");
      const city = escapeHtml(order.city || "");
      const createdAt = escapeHtml(order.created_at || "");
      const detailUrl = safeUrl(order.detail_url);
      const callUrl = safeUrl(order.call_url);
      const deliverUrl = safeUrl(order.deliver_url);
      const cancelUrl = safeUrl(order.cancel_url);
      const deliveryPrice = Number(order.delivery_price || 0).toFixed(2);
      const babaFee = Number(order.delivery_platform_fee || 0).toFixed(2);
      const babaSettled = !!order.baba_fee_settled;
      const csrfToken = getCsrfToken();
      const babaCell = `<span class="badge bg-warning text-dark">${babaFee} MAD</span>${
        babaSettled ? '<div class="small text-success">Remis</div>' : ""
      }`;
      const mutateActions =
        String(order.delivery_status || "").toLowerCase() === "new" && canMutate
          ? `
            <form method="POST" action="${deliverUrl}" class="d-inline" data-ajax="true" data-action="order-status" data-order-id="${order.id}">
              <input type="hidden" name="csrf_token" value="${csrfToken}">
              <button class="btn btn-success btn-sm" type="submit">
                <i class="bi bi-check-circle me-1"></i>Livree
              </button>
            </form>
            <form method="POST" action="${cancelUrl}" class="d-inline" data-ajax="true" data-action="order-status" data-order-id="${order.id}" data-confirm="Annuler cette livraison ?">
              <input type="hidden" name="csrf_token" value="${csrfToken}">
              <button class="btn btn-outline-danger btn-sm" type="submit">
                <i class="bi bi-x-circle me-1"></i>Annuler
              </button>
            </form>
          `
          : readOnly
          ? '<span class="badge text-bg-secondary align-self-center">Lecture seule</span>'
          : "";
      const actions = `
        <div class="d-flex gap-2 flex-wrap">
          <a href="${detailUrl}" class="btn btn-sm btn-primary">
            <i class="bi bi-eye"></i>
          </a>
          <a href="${callUrl}" class="btn btn-sm btn-outline-primary">
            <i class="bi bi-telephone"></i>
          </a>
          ${mutateActions}
        </div>
      `;

      return `
        <tr class="${
          order.status === "pending" ? "order-row-pending" : ""
        }" data-order-id="${order.id}" data-order-section="history">
          <td>${order.id}</td>
          <td>
            <div class="fw-semibold">${fullName}</div>
            <small class="text-muted">${phone}</small>
          </td>
          <td>${city}</td>
          <td><div class="list-text">${item}</div></td>
          <td><div class="list-text">${pickup || "-"}</div></td>
          <td>${Number(order.total || 0).toFixed(2)} MAD</td>
          <td>${deliveryPrice} MAD</td>
          <td>${babaCell}</td>
          <td data-order-status>${statusCell}</td>
          <td><small>${createdAt}</small></td>
          <td class="order-actions">${actions}</td>
        </tr>
      `;
    }

    async function refreshDeliveries() {
      try {
        const query = buildQuery();
        const res = await fetch(buildLiveUrl(query), { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (!data) return;
        readOnly = !!data.read_only;
        deliveriesPage.dataset.readOnly = readOnly ? "1" : "0";
        if (data.page) deliveriesPage.dataset.page = String(data.page);

        if (pendingCountLabel) pendingCountLabel.textContent = data.pending_count || 0;
        if (historyTotalLabel) historyTotalLabel.textContent = data.history_total || 0;
        if (pendingStat) pendingStat.textContent = data.pending_count || 0;
        if (deliveredStat) deliveredStat.textContent = data.delivered_recent_count || 0;
        if (commissionStat) {
          commissionStat.textContent = `${Number(
            data.total_baba_fee || 0
          ).toFixed(2)} MAD`;
        }
        const pendingRows = data.pending || data.pending_orders || [];
        const historyRows = data.history || data.history_orders || [];
        if (pendingTableBody) {
          pendingTableBody.innerHTML = pendingRows.map(renderPendingRow).join("") || "";
        }
        if (historyTableBody) {
          historyTableBody.innerHTML = historyRows.map(renderHistoryRow).join("") || "";
        }
      } catch (_error) {}
    }

    const interval = parseInt(body.dataset.interval || "15000", 10);
    startAdaptivePoll("deliveries", refreshDeliveries, {
      activeInterval: interval,
      inactiveInterval: Math.max(interval * 3, 30000),
    });
  }

  function initLiveFeatures() {
    const body = currentBody();
    if (!body) return;
    const pageId = getPageId();
    const liveType = inferLiveType(pageId, body.dataset.live);
    stopPoller("deliveries");
    if (!canRunHeavyLive(pageId, liveType)) return;
    if (liveType === "deliveries") initDeliveriesLive();
  }

  function init() {
    if (window.__BM_LIVE_INIT__ || window._BM_LIVE_INIT) return;
    window.__BM_LIVE_INIT__ = true;
    // Legacy alias kept for safety.
    window._BM_LIVE_INIT = true;

    bindAjaxSubmitOnce();
    bindVisibilityRefreshOnce();
    initLiveFeatures();

    const cart = window.BMCoreCart || {};
    if (typeof cart.initOrderNotifications === "function") {
      cart.initOrderNotifications({
        body: currentBody(),
        startAdaptivePoll,
        refreshLiveFeatures: initLiveFeatures,
      });
    }
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
})();

