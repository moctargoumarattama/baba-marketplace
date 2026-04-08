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
    var perfFlags = window.BM_PERF_FLAGS || {};
    var interactionFeedbackEnabled = perfFlags.interactionFeedback !== false;
    var prefetchApi = window.BMIntentPrefetch || null;
    var pressedNode = null;
    var pendingNode = null;

    if (!drawer || !toggler || !overlay) return;
    if (!window.bootstrap || !window.bootstrap.Collapse) return;

    var collapse = window.bootstrap.Collapse.getOrCreateInstance(drawer, { toggle: false });

    function isMobileDrawer() {
      return window.matchMedia("(max-width: 991.98px)").matches;
    }

    function hardResetDrawerUI() {
      document.body.classList.remove("menu-open");
      document.body.classList.remove("drawer-open");
      document.body.classList.remove("drawer-is-navigating");
      drawer.classList.remove("is-nav-leaving");
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

    function clearPressedState() {
      if (!pressedNode || !pressedNode.classList) {
        pressedNode = null;
        return;
      }
      pressedNode.classList.remove("is-pressed");
      pressedNode = null;
    }

    function markPressedState(node) {
      if (!interactionFeedbackEnabled || !node || !node.classList) return;
      if (pressedNode && pressedNode !== node) {
        clearPressedState();
      }
      pressedNode = node;
      node.classList.add("is-pressed");
    }

    function clearPendingState() {
      if (pendingNode && pendingNode.removeAttribute) {
        pendingNode.removeAttribute("data-bm-pending");
      }
      pendingNode = null;
      clearPressedState();
      document.body.classList.remove("drawer-is-navigating");
      drawer.classList.remove("is-nav-leaving");
    }

    function markPendingState(node) {
      if (!interactionFeedbackEnabled || !node) return;
      clearPendingState();
      pendingNode = node;
      markPressedState(node);
      if (node.setAttribute) {
        node.setAttribute("data-bm-pending", "1");
      }
      document.body.classList.add("drawer-is-navigating");
      drawer.classList.add("is-nav-leaving");
    }

    function isPrefetchableLink(node) {
      if (!node || !node.matches || !node.matches("a[href]")) return false;
      if (node.hasAttribute("data-lang-switch")) return false;
      var href = String(node.getAttribute("href") || "").trim();
      if (!href) return false;
      if (
        href.indexOf("#") === 0 ||
        href.indexOf("javascript:") === 0 ||
        href.indexOf("mailto:") === 0 ||
        href.indexOf("tel:") === 0
      ) {
        return false;
      }
      try {
        return new URL(href, window.location.href).origin === window.location.origin;
      } catch (_error) {
        return false;
      }
    }

    function prefetchLink(node) {
      if (!prefetchApi || typeof prefetchApi.prefetchUrl !== "function") return;
      if (!isPrefetchableLink(node)) return;
      prefetchApi.prefetchUrl(node.href, {
        headers: { Accept: "text/html" }
      });
    }

    function bindDrawerPrefetch() {
      if (!prefetchApi || typeof prefetchApi.prefetchOnIntent !== "function") return;
      prefetchApi.prefetchOnIntent(
        drawer,
        '.mobile-menu a[href]:not([data-lang-switch]):not([href^="#"]):not([href^="javascript:"]):not([href^="mailto:"]):not([href^="tel:"])',
        { headers: { Accept: "text/html" } }
      );
    }

    function warmDrawerPrefetch() {
      if (!prefetchApi || typeof prefetchApi.prefetchIdle !== "function") return;
      var seen = Object.create(null);
      var urls = [];
      drawer.querySelectorAll(".mobile-menu a[href]").forEach(function (node) {
        if (!isPrefetchableLink(node)) return;
        var href = String(node.getAttribute("href") || "").trim();
        if (!href || seen[href]) return;
        seen[href] = true;
        urls.push(href);
      });
      if (!urls.length) return;
      prefetchApi.prefetchIdle(urls.slice(0, 6), {
        headers: { Accept: "text/html" },
        timeoutMs: 900
      });
    }

    function closeDrawer(options) {
      if (!isMobileDrawer()) return;
      var opts = options || {};
      if (opts.fastExit) {
        document.body.classList.add("drawer-is-navigating");
        drawer.classList.add("is-nav-leaving");
      }
      collapse.hide();
      window.setTimeout(function () {
        if (drawer.classList.contains("show")) {
          hardResetDrawerUI();
        }
      }, opts.fastExit ? 120 : 420);
    }

    function syncDrawerVisibilityState() {
      if (!isMobileDrawer()) {
        hardResetDrawerUI();
        return;
      }

      var isOpen = drawer.classList.contains("show");
      document.body.classList.toggle("menu-open", isOpen);
      document.body.classList.toggle("drawer-open", isOpen);
      toggler.setAttribute("aria-expanded", isOpen ? "true" : "false");
      overlay.setAttribute("aria-hidden", isOpen ? "false" : "true");

      if (isOpen) {
        if (typeof window.lockScroll === "function") {
          window.lockScroll("drawer");
        }
        return;
      }

      if (typeof window.ensureScrollLockConsistency === "function") {
        window.ensureScrollLockConsistency();
      }
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

    drawer.addEventListener(
      "pointerdown",
      function (e) {
        var trigger = e.target && e.target.closest ? e.target.closest(".mobile-menu a, .mobile-menu button[type='submit']") : null;
        if (!trigger) return;
        markPressedState(trigger);
        prefetchLink(trigger);
      },
      { passive: true }
    );

    drawer.addEventListener(
      "pointerup",
      function () {
        if (!pendingNode) {
          clearPressedState();
        }
      },
      { passive: true }
    );

    drawer.addEventListener(
      "pointercancel",
      function () {
        if (!pendingNode) {
          clearPressedState();
        }
      },
      { passive: true }
    );

    drawer.addEventListener("click", function (e) {
      e.stopPropagation();
      var link = e.target && e.target.closest ? e.target.closest(".mobile-menu a, .mobile-menu button[type='submit']") : null;
      if (!link) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (link.matches && link.matches("a[href]") && link.target === "_blank") return;
      markPendingState(link);
      closeDrawer({ fastExit: true });
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
      bindDrawerPrefetch();
      warmDrawerPrefetch();
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
      clearPendingState();
      hardResetDrawerUI();
    });

    syncDrawerVisibilityState();

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

    function reconcileDrawerAfterNavigation() {
      clearPendingState();
      if (!drawer.classList.contains("show")) {
        hardResetDrawerUI();
      }
      if (typeof window.ensureScrollLockConsistency === "function") {
        window.ensureScrollLockConsistency();
      }
    }

    window.addEventListener("pageshow", reconcileDrawerAfterNavigation);
    window.addEventListener("load", reconcileDrawerAfterNavigation, { once: true });

    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState !== "visible") return;
      reconcileDrawerAfterNavigation();
    });
  });
})();

