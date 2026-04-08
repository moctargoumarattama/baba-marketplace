(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_COURIER_DELIVERIES_INIT__) return;
  window.__BM_COURIER_DELIVERIES_INIT__ = true;
  var makeRequestSeq =
    window.BMCoreDom && typeof window.BMCoreDom.makeRequestSeq === "function"
      ? window.BMCoreDom.makeRequestSeq
      : window.BMAjaxGuard.makeRequestSeq.bind(window.BMAjaxGuard);
  var requestText =
    window.BMCoreDom && typeof window.BMCoreDom.requestText === "function"
      ? window.BMCoreDom.requestText
      : window.BMAjaxFetch.requestText.bind(window.BMAjaxFetch);

  function restoreY(y) {
    var target = Math.max(Number(y || 0), 0);
    if (window.AdminHelpers && typeof window.AdminHelpers.restoreInstantScroll === "function") {
      window.AdminHelpers.restoreInstantScroll(target);
      return;
    }
    requestAnimationFrame(function () {
      try {
        window.scrollTo({ top: target, left: 0, behavior: "instant" });
      } catch (_err) {
        window.scrollTo(0, target);
      }
    });
  }

  function initCourierDeliveriesPage() {
    var root = document.querySelector(".courier-wrap");
    if (!root) return;
    if (root.dataset.courierDeliveriesInit === "1") return;
    root.dataset.courierDeliveriesInit = "1";

    var seq = makeRequestSeq();
    var activeController = null;
    var lock = false;
    var assignedWatchUrl = root.getAttribute("data-assigned-watch-url") || "";
    var soundEnabled = true;
    var audioCtx = null;
    var audioArmed = false;
    var alertStopTimer = null;
    var activeOscillators = [];
    var activeGains = [];
    var pollingHandle = null;
    var knownAssignedIds = collectAssignedIds(document);
    var soundToggle = document.getElementById("soundToggle");
    var soundTestBtn = document.getElementById("courierSoundTestBtn");
    var refreshBtn = document.getElementById("courierRefreshBtn");
    var liveStatus = document.getElementById("courierLiveStatus");
    var orderToast = document.getElementById("admin-order-toast");
    var orderToastText = document.getElementById("admin-order-toast-text");
    var orderToastTitle = orderToast ? orderToast.querySelector(".toast-title") : null;
    var toastTimer = null;

    try {
      soundEnabled = localStorage.getItem("adminOrderSound") !== "0";
    } catch (_err) {
      soundEnabled = true;
    }

    function collectAssignedIds(scope) {
      var source = scope || document;
      var ids = {};
      var rows = source.querySelectorAll("tr[data-order-id][data-delivery-status]");
      rows.forEach(function (row) {
        var status = String(row.getAttribute("data-delivery-status") || "").toLowerCase();
        var orderId = String(row.getAttribute("data-order-id") || "").trim();
        if (!orderId || status !== "assigned") return;
        ids[orderId] = true;
      });
      return ids;
    }

    function stopAssignedAlert() {
      if (alertStopTimer) {
        window.clearTimeout(alertStopTimer);
        alertStopTimer = null;
      }
      activeOscillators.forEach(function (oscillator) {
        try {
          oscillator.stop();
        } catch (_err) {}
      });
      activeOscillators = [];
      activeGains.forEach(function (gainNode) {
        try {
          gainNode.disconnect();
        } catch (_err) {}
      });
      activeGains = [];
    }

    function armAudioOnce() {
      try {
        var AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;
        if (!audioCtx) {
          audioCtx = new AudioCtx();
        }
        if (audioCtx.state === "suspended") {
          audioCtx.resume().catch(function () {});
        }
        audioArmed = audioCtx.state === "running" || audioCtx.state === "suspended";
      } catch (_err) {
        audioArmed = false;
      }
    }

    function syncSoundPreference() {
      try {
        soundEnabled = localStorage.getItem("adminOrderSound") !== "0";
      } catch (_err) {
        soundEnabled = true;
      }
    }

    function showAssignedToast(message) {
      if (!orderToast || !orderToastText) return;
      if (orderToastTitle) {
        orderToastTitle.textContent = "Nouvelle livraison assignée";
      }
      orderToastText.textContent = message || "Une nouvelle livraison vient de vous être assignée.";
      orderToast.classList.add("show");
      if (toastTimer) {
        window.clearTimeout(toastTimer);
      }
      toastTimer = window.setTimeout(function () {
        orderToast.classList.remove("show");
      }, 4200);
    }

    function playAssignedAlert() {
      syncSoundPreference();
      if (!soundEnabled || !audioArmed || !audioCtx) return;
      stopAssignedAlert();
      try {
        var startedAt = audioCtx.currentTime;
        var pulseLength = 0.44;
        var gapLength = 0.11;
        var cycleLength = pulseLength + gapLength;
        var totalDuration = 5;
        var cycleCount = Math.ceil(totalDuration / cycleLength);
        var frequencies = [784, 1046, 1174];

        for (var cycle = 0; cycle < cycleCount; cycle += 1) {
          for (var idx = 0; idx < frequencies.length; idx += 1) {
            var noteStart = startedAt + cycle * cycleLength + idx * 0.07;
            if (noteStart > startedAt + totalDuration) continue;
            var oscillator = audioCtx.createOscillator();
            var gain = audioCtx.createGain();
            oscillator.type = idx === 0 ? "triangle" : "sine";
            oscillator.frequency.setValueAtTime(frequencies[idx], noteStart);
            gain.gain.setValueAtTime(0.0001, noteStart);
            gain.gain.exponentialRampToValueAtTime(0.09, noteStart + 0.03);
            gain.gain.exponentialRampToValueAtTime(0.0001, Math.min(noteStart + 0.34, startedAt + totalDuration));
            oscillator.connect(gain);
            gain.connect(audioCtx.destination);
            oscillator.start(noteStart);
            oscillator.stop(Math.min(noteStart + 0.36, startedAt + totalDuration));
            activeOscillators.push(oscillator);
            activeGains.push(gain);
          }
        }

        alertStopTimer = window.setTimeout(stopAssignedAlert, totalDuration * 1000 + 180);
        if (navigator && typeof navigator.vibrate === "function") {
          navigator.vibrate([300, 140, 300, 140, 300]);
        }
      } catch (_err) {
        stopAssignedAlert();
      }
    }

    function detectNewAssignedIds(nextIds) {
      var incoming = nextIds || {};
      var added = [];
      Object.keys(incoming).forEach(function (id) {
        if (!knownAssignedIds[id]) added.push(id);
      });
      knownAssignedIds = incoming;
      return added;
    }

    function currentPageUrl() {
      return window.location.pathname + window.location.search;
    }

    function updateLiveStatus(message) {
      if (!liveStatus) return;
      liveStatus.innerHTML = '<i class="bi bi-broadcast-pin"></i>' + String(message || "Mise a jour auto active");
    }

    function sameCardContent(nextCard, currentCard) {
      if (!nextCard || !currentCard) return false;
      return String(nextCard.innerHTML || "").trim() === String(currentCard.innerHTML || "").trim();
    }

    async function pollAssignedDeliveries() {
      if (!assignedWatchUrl || lock) return;
      var response = await requestText(assignedWatchUrl, {
        headers: { "X-Requested-With": "XMLHttpRequest" }
      });
      if (!response.ok || !response.data) return;
      var doc = new DOMParser().parseFromString(String(response.data || ""), "text/html");
      var nextAssignedIds = collectAssignedIds(doc);
      var newAssignedIds = detectNewAssignedIds(nextAssignedIds);
      if (newAssignedIds.length) {
        showAssignedToast(
          newAssignedIds.length > 1
            ? newAssignedIds.length + " nouvelles livraisons vous ont été assignées."
            : "Nouvelle livraison assignée."
        );
        armAudioOnce();
        playAssignedAlert();
      }
    }

    async function fetchAndSwap(url) {
      if (!url || lock) return;
      lock = true;
      var keepY = window.scrollY || 0;

      if (activeController && typeof activeController.abort === "function") {
        try {
          activeController.abort();
        } catch (_err) {}
      }
      activeController = typeof AbortController !== "undefined" ? new AbortController() : null;

      var requestId = seq.next();
      try {
        var response = await requestText(url, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          signal: activeController ? activeController.signal : undefined,
        });

        if (!seq.isLatest(requestId)) return;
        if (!response.ok) {
          if (!response.aborted) window.location.href = url;
          return;
        }

        var doc = new DOMParser().parseFromString(String(response.data || ""), "text/html");
        var nextCard = doc.querySelector(".courier-card");
        var currentCard = document.querySelector(".courier-card");
        if (!nextCard || !currentCard) {
          window.location.href = url;
          return;
        }

        if (sameCardContent(nextCard, currentCard)) {
          knownAssignedIds = collectAssignedIds(document);
          updateLiveStatus("Verifie a " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
          return;
        }

        currentCard.innerHTML = nextCard.innerHTML;
        try {
          window.history.replaceState({}, "", url);
        } catch (_err) {}
        knownAssignedIds = collectAssignedIds(document);
        updateLiveStatus("Mis a jour a " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));

        restoreY(keepY);
        try {
          document.dispatchEvent(new CustomEvent("ajax:page-replaced", { detail: { url: url } }));
        } catch (_err) {}
      } catch (_err) {
        window.location.href = url;
      } finally {
        if (seq.isLatest(requestId)) {
          lock = false;
          activeController = null;
        }
      }
    }

    root.addEventListener("click", function (event) {
      var link = event.target && event.target.closest ? event.target.closest(".courier-card .page-link") : null;
      if (!link) return;

      var href = link.getAttribute("href");
      var parent = link.closest(".page-item");
      if (!href || (parent && parent.classList.contains("disabled"))) return;

      event.preventDefault();
      fetchAndSwap(href).catch(function () {
        window.location.href = href;
      });
    });

    window.addEventListener("pointerdown", armAudioOnce, { once: true, passive: true });
    window.addEventListener("touchstart", armAudioOnce, { once: true, passive: true });
    window.addEventListener("keydown", armAudioOnce, { once: true });
    window.addEventListener("focus", armAudioOnce);

    if (soundToggle) {
      soundToggle.addEventListener("click", function () {
        window.setTimeout(function () {
          syncSoundPreference();
          armAudioOnce();
          if (soundEnabled) {
            showAssignedToast("Son activé pour les nouvelles livraisons.");
            playAssignedAlert();
          } else {
            stopAssignedAlert();
          }
        }, 20);
      });
    }

    if (soundTestBtn) {
      soundTestBtn.addEventListener("click", function () {
        syncSoundPreference();
        armAudioOnce();
        showAssignedToast(
          soundEnabled
            ? "Test du son en cours."
            : "Le son est coupé. Activez d'abord le bouton Son."
        );
        if (soundEnabled) {
          playAssignedAlert();
        }
      });
    }

    if (refreshBtn) {
      refreshBtn.addEventListener("click", function () {
        if (lock) return;
        updateLiveStatus("Actualisation...");
        fetchAndSwap(currentPageUrl()).catch(function () {
          window.location.reload();
        });
      });
    }

    pollingHandle = window.setInterval(function () {
      pollAssignedDeliveries().catch(function () {});
      if (!document.hidden && !lock && root.getAttribute("data-current-tab") === "in_progress") {
        fetchAndSwap(currentPageUrl()).catch(function () {});
      }
    }, 15000);

    window.addEventListener("beforeunload", function () {
      if (pollingHandle) {
        window.clearInterval(pollingHandle);
        pollingHandle = null;
      }
      stopAssignedAlert();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCourierDeliveriesPage, { once: true });
    return;
  }

  initCourierDeliveriesPage();
})();

