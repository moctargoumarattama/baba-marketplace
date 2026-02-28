(function () {
  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  onReady(function () {
    var drawer = document.getElementById("mainNavbar");
    var toggler = document.querySelector('.navbar-toggler[data-bs-target="#mainNavbar"]');
    var overlay = document.getElementById("drawerOverlay");
    var closeBtn = document.getElementById("drawerCloseBtn");

    if (!drawer || !toggler || !overlay) return;
    if (!window.bootstrap || !window.bootstrap.Collapse) return;

    var collapse = window.bootstrap.Collapse.getOrCreateInstance(drawer, { toggle: false });

    function isMobileDrawer() {
      return window.matchMedia("(max-width: 991.98px)").matches;
    }

    function hardResetDrawerUI() {
      document.body.classList.remove("menu-open");
      document.body.classList.remove("drawer-open");
      toggler.setAttribute("aria-expanded", "false");
      overlay.setAttribute("aria-hidden", "true");
      if (typeof window.hardResetUI === "function") {
        window.hardResetUI("drawer");
      } else if (typeof window.unlockScroll === "function") {
        window.unlockScroll("drawer");
      } else {
        document.documentElement.classList.remove("scroll-locked");
        document.body.classList.remove("scroll-locked");
      }
    }

    function closeDrawer() {
      if (!isMobileDrawer()) return;
      collapse.hide();
      window.setTimeout(function () {
        if (drawer.classList.contains("show")) {
          hardResetDrawerUI();
        }
      }, 420);
    }

    if (closeBtn) {
      var closeWithIntent = function (e) {
        if (e) {
          e.stopPropagation();
        }
        closeDrawer();
      };

      closeBtn.addEventListener("click", closeWithIntent);
      closeBtn.addEventListener("touchend", closeWithIntent, { passive: true });
      closeBtn.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          closeWithIntent(e);
        }
      });
    }

    overlay.addEventListener("click", function () {
      closeDrawer();
    });

    overlay.addEventListener("touchend", function () {
      closeDrawer();
    }, { passive: true });

    drawer.addEventListener("click", function (e) {
      e.stopPropagation();
      var link = e.target && e.target.closest ? e.target.closest(".mobile-menu a, .mobile-menu button[type='submit']") : null;
      if (!link) return;
      closeDrawer();
    });

    var startX = 0;
    var endX = 0;
    var track = false;

    drawer.addEventListener(
      "touchstart",
      function (e) {
        if (!isMobileDrawer() || !drawer.classList.contains("show")) return;
        if (!e.touches || !e.touches.length) return;
        track = true;
        startX = e.touches[0].clientX;
        endX = startX;
      },
      { passive: true }
    );

    drawer.addEventListener(
      "touchmove",
      function (e) {
        if (!track || !e.touches || !e.touches.length) return;
        endX = e.touches[0].clientX;
      },
      { passive: true }
    );

    drawer.addEventListener(
      "touchend",
      function () {
        if (!track) return;
        track = false;
        if (endX - startX < -42) closeDrawer();
      },
      { passive: true }
    );

    drawer.addEventListener("shown.bs.collapse", function () {
      if (!isMobileDrawer()) return;
      document.body.classList.add("menu-open");
      document.body.classList.add("drawer-open");
      toggler.setAttribute("aria-expanded", "true");
      overlay.setAttribute("aria-hidden", "false");
      if (typeof window.lockScroll === "function") {
        window.lockScroll("drawer");
      }
      if (closeBtn) {
        window.setTimeout(function () {
          closeBtn.focus({ preventScroll: true });
        }, 120);
      }
    });

    drawer.addEventListener("hidden.bs.collapse", function () {
      hardResetDrawerUI();
    });

    window.addEventListener("resize", function () {
      if (!isMobileDrawer()) {
        hardResetDrawerUI();
      }
    });

    document.addEventListener("keydown", function (e) {
      if (!isMobileDrawer()) return;
      if (e.key !== "Escape") return;
      if (!drawer.classList.contains("show")) return;
      closeDrawer();
    });
  });
})();
