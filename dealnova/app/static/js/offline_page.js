(function () {
  var retryBtn = document.getElementById("retryBtn");
  if (retryBtn) {
    retryBtn.addEventListener("click", function () {
      window.location.reload();
    });
  }

  var fab = document.querySelector("[data-offline-support-open]");
  var dialog = document.querySelector("[data-offline-support-dialog]");
  var backdrop = document.querySelector("[data-offline-support-backdrop]");
  var closeButtons = document.querySelectorAll("[data-offline-support-close]");
  var form = document.querySelector("[data-offline-support-form]");
  if (!fab || !dialog || !backdrop || !form) return;

  var supportNumber = form.getAttribute("data-support-number") || "212770010264";
  var storageKey = "bm-offline-support-fab";
  var pointerId = null;
  var startX = 0;
  var startY = 0;
  var originLeft = 0;
  var originTop = 0;
  var dragging = false;
  var suppressClick = false;

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function getBounds() {
    var margin = 8;
    return {
      minLeft: margin,
      minTop: margin,
      maxLeft: Math.max(margin, window.innerWidth - fab.offsetWidth - margin),
      maxTop: Math.max(margin, window.innerHeight - fab.offsetHeight - margin),
    };
  }

  function applyPosition(left, top, persist) {
    var bounds = getBounds();
    var safeLeft = clamp(left, bounds.minLeft, bounds.maxLeft);
    var safeTop = clamp(top, bounds.minTop, bounds.maxTop);
    fab.style.left = safeLeft + "px";
    fab.style.top = safeTop + "px";
    fab.style.right = "auto";
    fab.style.bottom = "auto";
    if (!persist) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify({ left: safeLeft, top: safeTop }));
    } catch (error) {}
  }

  function restorePosition() {
    var rect = fab.getBoundingClientRect();
    applyPosition(rect.left, rect.top, false);
    try {
      var raw = localStorage.getItem(storageKey);
      if (!raw) return;
      var saved = JSON.parse(raw);
      if (typeof saved.left === "number" && typeof saved.top === "number") {
        applyPosition(saved.left, saved.top, false);
      }
    } catch (error) {}
  }

  function openDialog() {
    backdrop.hidden = false;
    dialog.hidden = false;
    document.body.classList.add("offline-support-open");
    document.body.style.overflow = "hidden";
    dialog.scrollTop = 0;
    var supportCard = dialog.querySelector(".offline-support-card");
    if (supportCard) supportCard.scrollTop = 0;
    var firstField = dialog.querySelector("select, textarea, input");
    if (firstField) {
      window.setTimeout(function () {
        try { firstField.focus({ preventScroll: true }); } catch (error) { firstField.focus(); }
      }, 40);
    }
  }

  function closeDialog() {
    backdrop.hidden = true;
    dialog.hidden = true;
    document.body.classList.remove("offline-support-open");
    document.body.style.overflow = "";
  }

  fab.addEventListener("click", function (event) {
    if (suppressClick) {
      event.preventDefault();
      event.stopPropagation();
      suppressClick = false;
      return;
    }
    openDialog();
  });

  fab.addEventListener("pointerdown", function (event) {
    if (event.button !== 0) return;
    pointerId = event.pointerId;
    startX = event.clientX;
    startY = event.clientY;
    originLeft = fab.offsetLeft;
    originTop = fab.offsetTop;
    dragging = false;
    fab.classList.remove("is-dragging");
    try { fab.setPointerCapture(pointerId); } catch (error) {}
  });

  fab.addEventListener("pointermove", function (event) {
    if (pointerId !== event.pointerId) return;
    var deltaX = event.clientX - startX;
    var deltaY = event.clientY - startY;
    if (!dragging && Math.abs(deltaX) + Math.abs(deltaY) < 6) return;
    dragging = true;
    fab.classList.add("is-dragging");
    applyPosition(originLeft + deltaX, originTop + deltaY, false);
  });

  function finishDrag(event) {
    if (pointerId !== event.pointerId) return;
    try { fab.releasePointerCapture(pointerId); } catch (error) {}
    pointerId = null;
    if (dragging) {
      fab.classList.remove("is-dragging");
      applyPosition(fab.offsetLeft, fab.offsetTop, true);
      suppressClick = true;
      window.setTimeout(function () {
        suppressClick = false;
      }, 180);
    }
    dragging = false;
  }

  fab.addEventListener("pointerup", finishDrag);
  fab.addEventListener("pointercancel", finishDrag);
  fab.addEventListener("lostpointercapture", function () {
    pointerId = null;
    dragging = false;
    fab.classList.remove("is-dragging");
  });

  closeButtons.forEach(function (button) {
    button.addEventListener("click", closeDialog);
  });
  backdrop.addEventListener("click", closeDialog);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !dialog.hidden) {
      closeDialog();
    }
  });

  function bullet(value) {
    var cleaned = String(value || "").replace(/\s+/g, " ").trim();
    return cleaned ? "- " + cleaned : "- ";
  }

  function openWhatsAppMessage(message) {
    var encoded = encodeURIComponent(message);
    var appUrl = "whatsapp://send?phone=" + supportNumber + "&text=" + encoded;
    var webUrl = "https://wa.me/" + supportNumber + "?text=" + encoded;

    try {
      window.location.href = appUrl;
    } catch (error) {}

    window.setTimeout(function () {
      if (!document.hidden) {
        window.location.href = webUrl;
      }
    }, 700);
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var data = new FormData(form);
    var issueType = String(data.get("issue_type") || "Autre").trim();
    var details = String(data.get("details") || "").trim();
    var expected = String(data.get("expected") || "").trim();

    var message = [
      "Bonjour, je signale un probleme sur l'ecran hors connexion.",
      "Page: offline.html",
      "Type: " + issueType,
      "",
      "Probleme constate:",
      bullet(details),
      "",
      "Resultat attendu:",
      bullet(expected),
    ].join("\n");

    closeDialog();
    openWhatsAppMessage(message);
  });

  window.requestAnimationFrame(restorePosition);
  window.addEventListener("resize", function () {
    applyPosition(fab.offsetLeft, fab.offsetTop, false);
  });
})();
