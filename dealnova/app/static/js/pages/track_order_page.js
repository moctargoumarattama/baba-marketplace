(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_TRACK_ORDER_INIT__) return;
  window.__BM_TRACK_ORDER_INIT__ = true;

  function makeRequestSeq() {
    if (window.BMAjaxGuard && typeof window.BMAjaxGuard.makeRequestSeq === "function") {
      return window.BMAjaxGuard.makeRequestSeq();
    }
    var latest = 0;
    return {
      next: function () {
        latest += 1;
        return latest;
      },
      isLatest: function (id) {
        return Number(id) === latest;
      },
    };
  }

  const bmFetchApi = window.BMAjaxFetch || null;

  async function bmFetchJSON(url, options) {
    var opts = options || {};
    if (bmFetchApi && typeof bmFetchApi.requestJSON === "function") {
      return bmFetchApi.requestJSON(url, opts);
    }
    try {
      var response = await fetch(url, opts);
      var data = null;
      try {
        data = await response.json();
      } catch (_parseError) {
        data = null;
      }
      return {
        ok: response.ok,
        status: response.status,
        data: data,
        error: response.ok ? null : (response.statusText || ("HTTP " + response.status)),
        aborted: false,
        timedOut: false,
      };
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

  function initTrackOrderPage() {
    var page = document.getElementById("trackOrderPage");
    if (!page) return;
    if (page.dataset.trackOrderInit === "1") return;
    page.dataset.trackOrderInit = "1";

    var dataset = page.dataset || {};
    var orderToken = String(dataset.token || "");
    if (!orderToken) return;

    var statusBadge = document.getElementById("statusBadge");
    var liveText = document.getElementById("liveText");
    var flow = ["new", "assigned", "picked_up", "delivering", "delivered"];
    var statusRequestSeq = makeRequestSeq();
    var activeStatusController = null;

    function normalizeStatus(value) {
      var raw = String(value || "").toLowerCase().trim();
      if (raw === "cancelled") return "canceled";
      return raw || "new";
    }

    var lastKnownStatus = normalizeStatus(dataset.initialStatus || "new");
    var fallbackLabels = { _fallback: "En cours" };
    document.querySelectorAll(".timeline-step[data-step]").forEach(function (node) {
      var step = String(node.getAttribute("data-step") || "").trim();
      var titleNode = node.querySelector(".timeline-title");
      var label = titleNode ? String(titleNode.textContent || "").trim() : "";
      if (step && label) fallbackLabels[step] = label;
    });

    function setBadge(status, label) {
      if (!statusBadge) return;
      var ds = normalizeStatus(status);
      statusBadge.className = "status-badge badge-" + ds;
      statusBadge.textContent = label || fallbackLabels[ds] || fallbackLabels._fallback || ds;
    }

    function setTimeline(status) {
      var ds = normalizeStatus(status);
      var currentIdx = flow.indexOf(ds);
      document.querySelectorAll(".timeline-step[data-step]").forEach(function (node) {
        var step = node.getAttribute("data-step");
        var idx = flow.indexOf(step);
        node.classList.remove("done", "active");
        if (currentIdx > -1 && idx < currentIdx) node.classList.add("done");
        if (currentIdx > -1 && idx === currentIdx) node.classList.add("active");
        if (ds === "canceled") node.classList.remove("active");
      });
    }

    function setTime(step, isoValue) {
      var node = document.getElementById("time-" + step);
      if (!node || !isoValue) return;
      var dt = new Date(isoValue);
      if (Number.isNaN(dt.getTime())) return;
      node.textContent = dt.toLocaleString("fr-FR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    }

    async function refreshStatus() {
      var requestId = statusRequestSeq.next();

      if (activeStatusController && typeof activeStatusController.abort === "function") {
        try {
          activeStatusController.abort();
        } catch (_err) {}
      }
      activeStatusController = typeof AbortController !== "undefined" ? new AbortController() : null;

      try {
        var response = await bmFetchJSON("/cart/track/" + orderToken + "/status", {
          method: "GET",
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json", "X-Requested-With": "fetch" },
          signal: activeStatusController ? activeStatusController.signal : undefined,
          timeoutMs: 12000,
        });

        if (!statusRequestSeq.isLatest(requestId)) return;
        if (!response || response.aborted || response.timedOut || !response.ok) return;

        var data = response.data || {};
        var ds = normalizeStatus(data.delivery_status || data.status);
        setBadge(ds, data.delivery_status_label || data.status_label || ds);
        setTimeline(ds);
        setTime("assigned", data.assigned_at);
        setTime("picked_up", data.picked_up_at);
        setTime("delivered", data.delivered_at);

        if (ds !== lastKnownStatus) {
          lastKnownStatus = ds;
          try {
            document.dispatchEvent(new CustomEvent("track:changed", { detail: { status: ds } }));
          } catch (_err) {}
        }

        if (liveText) {
          var now = new Date();
          liveText.textContent = "Derniere mise a jour: " + now.toLocaleTimeString("fr-FR");
        }
      } catch (_err) {
        // keep page stable on polling failure
      } finally {
        if (statusRequestSeq.isLatest(requestId)) {
          activeStatusController = null;
        }
      }
    }

    function copyLink() {
      var value = window.location.href;
      var fallback = function () {
        var input = document.createElement("input");
        input.value = value;
        document.body.appendChild(input);
        input.select();
        document.execCommand("copy");
        input.remove();
      };

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).catch(fallback);
      } else {
        fallback();
      }
    }

    var copyBtn = document.getElementById("copyBtn");
    if (copyBtn) copyBtn.addEventListener("click", copyLink);

    var shareBtn = document.getElementById("shareBtn");
    if (shareBtn) {
      shareBtn.addEventListener("click", async function () {
        var orderId = Number(dataset.orderId || 0);
        var title = orderId > 0 ? "Suivi commande #" + orderId : "Suivi commande";
        var payload = { title: title, text: title, url: window.location.href };
        if (navigator.share) {
          try {
            await navigator.share(payload);
            return;
          } catch (_err) {}
        }
        copyLink();
      });
    }

    var refreshBtn = document.getElementById("refreshBtn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", function (event) {
        event.preventDefault();
        refreshStatus();
      });
    }

    setBadge(dataset.initialStatus || "new", dataset.initialLabel || "");
    setTimeline(dataset.initialStatus || "new");
    refreshStatus();

    if (window.BMAjaxPolling && typeof window.BMAjaxPolling.start === "function") {
      window.BMAjaxPolling.start({
        key: "track-order-status-" + orderToken,
        fn: refreshStatus,
        intervalMs: 10000,
        hiddenPause: true,
      });
      return;
    }

    var timerId = null;
    function clearTimer() {
      if (!timerId) return;
      window.clearTimeout(timerId);
      timerId = null;
    }
    function schedule(delayMs) {
      clearTimer();
      timerId = window.setTimeout(runTick, Math.max(1000, Number(delayMs) || 10000));
    }
    function runTick() {
      if (document.hidden) {
        clearTimer();
        return;
      }
      refreshStatus().finally(function () {
        schedule(10000);
      });
    }
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        clearTimer();
        return;
      }
      schedule(1000);
    });
    schedule(10000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTrackOrderPage, { once: true });
    return;
  }

  initTrackOrderPage();
})();

