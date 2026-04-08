(function () {
  "use strict";

  var widgets = document.querySelectorAll("[data-support-fab]");
  if (!widgets.length) return;

  widgets.forEach(function (root) {
    if (!root || root.dataset.supportReady === "1") return;
    root.dataset.supportReady = "1";

    var fab = root.querySelector("[data-support-open]");
    var dialog = root.querySelector("[data-support-dialog]");
    var backdrop = root.querySelector("[data-support-backdrop]");
    var closeButtons = root.querySelectorAll("[data-support-close]");
    var storageKey = root.getAttribute("data-support-storage-key") || "bm-support-fab";
    if (!fab || !dialog || !backdrop) return;

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
      } catch (_error) {}
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
      } catch (_error) {}
    }

    function openDialog() {
      backdrop.hidden = false;
      dialog.hidden = false;
      document.body.classList.add("support-issue-open");
      var firstField = dialog.querySelector("select, textarea, input");
      if (firstField) {
        window.setTimeout(function () {
          try {
            firstField.focus({ preventScroll: true });
          } catch (_error) {
            firstField.focus();
          }
        }, 40);
      }
    }

    function closeDialog() {
      backdrop.hidden = true;
      dialog.hidden = true;
      document.body.classList.remove("support-issue-open");
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
      try {
        fab.setPointerCapture(pointerId);
      } catch (_error) {}
    });

    fab.addEventListener("pointermove", function (event) {
      if (pointerId !== event.pointerId) return;
      var deltaX = event.clientX - startX;
      var deltaY = event.clientY - startY;
      if (!dragging && Math.abs(deltaX) + Math.abs(deltaY) < 18) return;
      dragging = true;
      fab.classList.add("is-dragging");
      applyPosition(originLeft + deltaX, originTop + deltaY, false);
    });

    function finishDrag(event) {
      if (pointerId !== event.pointerId) return;
      try {
        fab.releasePointerCapture(pointerId);
      } catch (_error) {}
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

    backdrop.addEventListener("click", closeDialog);
    closeButtons.forEach(function (button) {
      button.addEventListener("click", closeDialog);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !dialog.hidden) {
        closeDialog();
      }
    });

    window.requestAnimationFrame(restorePosition);
    window.addEventListener("resize", function () {
      applyPosition(fab.offsetLeft, fab.offsetTop, false);
    });
  });
})();
