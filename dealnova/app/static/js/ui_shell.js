(function () {
  "use strict";

  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const csrfToken = csrfMeta ? (csrfMeta.getAttribute("content") || "") : "";
  window.csrfToken = csrfToken;
  let deferredInstallPrompt = null;
  const uiScrollLocks = new Set();

  function applyScrollLockState() {
    const shouldLock = uiScrollLocks.size > 0;
    document.documentElement.classList.toggle("scroll-locked", shouldLock);
    document.body.classList.toggle("scroll-locked", shouldLock);
  }

  function lockScroll(lockId = "global") {
    uiScrollLocks.add(lockId);
    applyScrollLockState();
  }

  function unlockScroll(lockId = "global") {
    uiScrollLocks.delete(lockId);
    applyScrollLockState();
  }

  function hardResetUI(lockId) {
    if (lockId) {
      uiScrollLocks.delete(lockId);
    } else {
      uiScrollLocks.clear();
    }
    document.body.style.transform = "";
    document.documentElement.style.transform = "";
    applyScrollLockState();
  }

  window.lockScroll = lockScroll;
  window.unlockScroll = unlockScroll;
  window.hardResetUI = hardResetUI;

  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferredInstallPrompt = e;
    window.dispatchEvent(new Event("pwa:beforeinstallprompt-ready"));
  });

  const ONLINE_ONLY_PREFIXES = [
    "/admin",
    "/api",
    "/courier",
    "/vendor",
    "/cart",
    "/delivery",
    "/login",
    "/logout",
    "/register",
    "/lang",
    "/booking",
    "/shop/track",
    "/shop/suivi",
  ];

  function safePath(input) {
    if (!input) return "";
    try {
      return new URL(input, window.location.origin).pathname || "";
    } catch (_) {
      return "";
    }
  }

  function isOnlineRequiredPath(pathname) {
    if (!pathname) return false;
    return ONLINE_ONLY_PREFIXES.some(function (prefix) {
      return pathname === prefix || pathname.startsWith(prefix + "/");
    });
  }

  function elementNeedsOnline(el) {
    if (!el || !el.closest) return false;

    const forced = el.closest("[data-requires-online]");
    if (forced) return true;

    const anchor = el.closest("a[href]");
    if (anchor) {
      const href = anchor.getAttribute("href") || "";
      if (!href || href.startsWith("#") || href.startsWith("javascript:")) return false;
      return isOnlineRequiredPath(safePath(anchor.href));
    }

    const submitButton = el.closest("button, input[type='submit']");
    if (submitButton) {
      const form = submitButton.form || el.closest("form");
      if (!form) return false;
      const action = form.getAttribute("action") || window.location.pathname;
      if (form.hasAttribute("data-requires-online")) return true;
      return isOnlineRequiredPath(safePath(action));
    }

    return false;
  }

  // Stop accidental navigation from interactive elements inside clickable cards.
  document.addEventListener("click", function (e) {
    const stopEl = e.target && e.target.closest ? e.target.closest("[data-stop-nav]") : null;
    if (!stopEl) return;

    const parentAnchor = stopEl.closest("a[href]");
    if (parentAnchor && parentAnchor !== stopEl) {
      e.preventDefault();
    }

    e.stopPropagation();
    if (stopEl.getAttribute("data-stop-nav") === "hard") {
      e.stopImmediatePropagation();
    }
  });

  document.addEventListener(
    "submit",
    function (e) {
      const form = e.target && e.target.matches ? e.target : null;
      if (!form) return;
      const message = form.getAttribute("data-confirm-submit") || form.getAttribute("data-confirm");
      if (!message) return;
      if (!window.confirm(message)) {
        e.preventDefault();
        e.stopPropagation();
      }
    },
    true
  );

  document.addEventListener(
    "click",
    function (e) {
      const confirmEl = e.target && e.target.closest ? e.target.closest("[data-confirm-click]") : null;
      if (confirmEl) {
        const message = confirmEl.getAttribute("data-confirm-click") || confirmEl.getAttribute("data-confirm");
        if (message && !window.confirm(message)) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
      }

      const reloadEl = e.target && e.target.closest ? e.target.closest('[data-action="reload-page"]') : null;
      if (reloadEl) {
        e.preventDefault();
        window.location.reload();
        return;
      }

      const closeEl = e.target && e.target.closest ? e.target.closest("[data-close-target]") : null;
      if (closeEl) {
        e.preventDefault();
        const selector = closeEl.getAttribute("data-close-target");
        if (!selector) return;
        const target = closeEl.closest(selector) || document.querySelector(selector);
        if (target) target.classList.remove("show");
      }
    },
    true
  );

  document.addEventListener(
    "change",
    function (e) {
      const autoSubmit = e.target && e.target.closest ? e.target.closest(".js-auto-submit") : null;
      if (!autoSubmit || !autoSubmit.form) return;
      autoSubmit.form.submit();
    },
    true
  );

  document.addEventListener(
    "error",
    function (e) {
      const img = e.target;
      if (!img || img.tagName !== "IMG") return;

      const fallbackSrc = img.getAttribute("data-fallback-src");
      if (fallbackSrc && img.getAttribute("src") !== fallbackSrc) {
        img.setAttribute("src", fallbackSrc);
        return;
      }

      const fallbackMode = img.getAttribute("data-img-fallback");
      if (fallbackMode === "remove") {
        img.remove();
      }
    },
    true
  );

  document.addEventListener(
    "click",
    function (e) {
      const langLink = e.target && e.target.closest ? e.target.closest("[data-lang-switch]") : null;
      if (!langLink) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || langLink.target === "_blank") return;
      e.preventDefault();

      const langForm = document.getElementById("langSwitchForm");
      if (!langForm) {
        window.location.href = langLink.href;
        return;
      }
      const nextInput = document.getElementById("langSwitchNext");
      if (nextInput) nextInput.value = window.location.pathname + window.location.search;
      langForm.action = langLink.href;
      langForm.submit();
    },
    true
  );

  if (localStorage.getItem("clickDebug") === "1") {
    document.addEventListener(
      "click",
      function (e) {
        const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
        if (!a) return;
        console.log("[CLICK]", a.href, a);
      },
      true
    );
  }

  document.addEventListener("DOMContentLoaded", function () {
    const navbar = document.querySelector(".navbar");
    if (navbar) {
      let ticking = false;
      window.addEventListener(
        "scroll",
        function () {
          if (!ticking) {
            window.requestAnimationFrame(function () {
              if (window.scrollY > 50) {
                navbar.classList.add("scrolled");
              } else {
                navbar.classList.remove("scrolled");
              }
              ticking = false;
            });
            ticking = true;
          }
        },
        { passive: true }
      );
    }

    // Mobile drawer behavior is handled in static/js/ui_drawer.js.

    const backBtn = document.querySelector(".back-fab");
    if (backBtn) {
      function shouldShowBackButton() {
        const currentPath = window.location.pathname;
        const previousUrl = document.referrer;

        if (currentPath === "/" || currentPath === "/index.html") return false;
        if (!previousUrl) return false;
        if (previousUrl.includes(currentPath)) return false;
        return true;
      }

      backBtn.style.display = shouldShowBackButton() ? "flex" : "none";

      backBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (document.referrer) {
          window.location.href = document.referrer;
        } else {
          window.history.back();
        }
      });

      window.addEventListener("pageshow", function () {
        backBtn.style.display = shouldShowBackButton() ? "flex" : "none";
      });
    }

    const cartIcon = document.querySelector("[data-cart-icon]");
    const trackIcon = document.querySelector("[data-track-icon]");
    const cartBadge = document.querySelector("[data-cart-badge]");
    const trackBadge = document.querySelector("[data-track-badge]");
    const drawerCartBadge = document.querySelector("[data-drawer-cart-badge]");
    const drawerTrackBadge = document.querySelector("[data-drawer-track-badge]");
    const homeCartBadge = document.querySelector("[data-home-cart-badge]");
    const homeTrackBadge = document.querySelector("[data-home-track-badge]");
    const navBadgeRoot = document.querySelector("[data-nav-badges]");
    const hasNavBadges = Boolean(cartIcon || trackIcon || cartBadge || trackBadge);

    if (hasNavBadges) {
      const rawAttnSeconds = Number(
        (navBadgeRoot && navBadgeRoot.getAttribute("data-cart-attn-seconds")) || 60
      );
      const cartAttentionMs = Math.max(5000, Math.min(120000, rawAttnSeconds * 1000));
      const prefersReducedMotion = Boolean(
        window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
      );
      let isNavRefreshInFlight = false;
      let cartAttentionTimer = null;
      const navState = {
        initialized: false,
        cartCount: Number((cartBadge && cartBadge.getAttribute("data-cart-count")) || (cartBadge && cartBadge.textContent) || 0) || 0,
        trackActive: Boolean(trackBadge && trackBadge.getAttribute("data-track-active") === "1"),
      };

      function setVisible(node, visible) {
        if (!node) return;
        node.classList.toggle("d-none", !visible);
      }

      function setNumericBadge(node, count) {
        if (!node) return;
        node.textContent = String(count);
        setVisible(node, count > 0);
      }

      function setDotBadge(node, active) {
        if (!node) return;
        setVisible(node, Boolean(active));
      }

      function pulseNodes(nodes) {
        if (prefersReducedMotion) return;
        nodes.forEach(function (node) {
          if (!node || node.classList.contains("d-none")) return;
          node.classList.remove("badge-pulse");
          // Force reflow so pulse can replay.
          void node.offsetWidth;
          node.classList.add("badge-pulse");
          const stop = function () { node.classList.remove("badge-pulse"); };
          node.addEventListener("animationend", stop, { once: true });
          window.setTimeout(stop, 950);
        });
      }

      function stopCartAttention() {
        if (cartAttentionTimer) {
          window.clearTimeout(cartAttentionTimer);
          cartAttentionTimer = null;
        }
        if (cartBadge) {
          cartBadge.classList.remove("cart-badge-attn");
        }
      }

      function startCartAttention() {
        if (prefersReducedMotion) return;
        if (!cartBadge || cartBadge.classList.contains("d-none")) return;
        stopCartAttention();
        cartBadge.classList.add("cart-badge-attn");
        cartAttentionTimer = window.setTimeout(function () {
          if (cartBadge) {
            cartBadge.classList.remove("cart-badge-attn");
          }
          cartAttentionTimer = null;
        }, cartAttentionMs);
      }

      function applyNavState(next, options) {
        const pulse = Boolean(options && options.pulse);
        const nextCartCount = Math.max(0, Number(next && next.cartCount) || 0);
        const nextTrackActive = Boolean(next && next.trackActive);
        const cartChanged = nextCartCount !== navState.cartCount;
        const trackChanged = nextTrackActive !== navState.trackActive;

        [cartBadge, drawerCartBadge, homeCartBadge].forEach(function (node) {
          setNumericBadge(node, nextCartCount);
        });
        if (cartBadge) {
          cartBadge.setAttribute("data-cart-count", String(nextCartCount));
        }
        [trackBadge, drawerTrackBadge, homeTrackBadge].forEach(function (node) {
          setDotBadge(node, nextTrackActive);
        });
        if (trackBadge) {
          trackBadge.setAttribute("data-track-active", nextTrackActive ? "1" : "0");
        }

        if (cartIcon) {
          cartIcon.setAttribute(
            "aria-label",
            nextCartCount > 0 ? `Panier (${nextCartCount})` : "Panier"
          );
        }
        if (trackIcon) {
          trackIcon.setAttribute(
            "aria-label",
            nextTrackActive ? "Suivi commande active" : "Suivi commande"
          );
        }

        if (nextCartCount > 0) {
          if (cartChanged || !navState.initialized) {
            startCartAttention();
          }
        } else {
          stopCartAttention();
        }

        if (pulse && navState.initialized) {
          if (cartChanged) {
            pulseNodes([cartBadge, drawerCartBadge, homeCartBadge]);
          }
          if (trackChanged) {
            pulseNodes([trackBadge, drawerTrackBadge, homeTrackBadge]);
          }
        }

        navState.cartCount = nextCartCount;
        navState.trackActive = nextTrackActive;
        navState.initialized = true;
      }

      async function fetchNavStatus() {
        const response = await fetch("/cart/api/nav-status", {
          method: "GET",
          headers: {
            "X-Requested-With": "fetch",
            Accept: "application/json",
          },
          credentials: "same-origin",
          cache: "no-store",
        });
        if (!response.ok) throw new Error("nav-status-http");
        return response.json();
      }

      async function refreshNavBadges(options) {
        if (isNavRefreshInFlight) return;
        isNavRefreshInFlight = true;
        try {
          const payload = await fetchNavStatus();
          applyNavState(
            {
              cartCount: payload && payload.cart_count,
              trackActive: payload && payload.track_active,
            },
            options || {}
          );
        } catch (_) {
          // Keep UI stable on network or backend issues.
        } finally {
          isNavRefreshInFlight = false;
        }
      }

      function watchedPath(pathname) {
        if (!pathname) return false;
        if (pathname === "/cart/api/nav-status" || pathname === "/cart/api/summary") return false;
        if (pathname.startsWith("/cart/api/")) return true;
        if (pathname === "/cart/checkout" || pathname === "/cart/whatsapp") return true;
        if (pathname === "/cart/suivi" || pathname === "/cart/mes-commandes") return true;
        if (pathname.startsWith("/cart/track/")) return true;
        return false;
      }

      if (typeof window.fetch === "function" && !window.__navBadgeFetchWrapped) {
        const nativeFetch = window.fetch.bind(window);
        window.fetch = function (input, init) {
          let pathname = "";
          try {
            pathname = safePath(typeof input === "string" ? input : (input && input.url) || "");
          } catch (_) {
            pathname = "";
          }

          return nativeFetch(input, init).then(function (response) {
            if (response && response.ok && watchedPath(pathname)) {
              window.setTimeout(function () {
                refreshNavBadges({ pulse: true });
              }, 120);
            }
            return response;
          });
        };
        window.__navBadgeFetchWrapped = true;
      }

      window.refreshNavBadges = function (opts) {
        return refreshNavBadges(opts || {});
      };

      document.addEventListener("cart:changed", function () {
        refreshNavBadges({ pulse: true });
      });

      document.addEventListener("track:changed", function () {
        refreshNavBadges({ pulse: true });
      });

      document.addEventListener("ajax:page-replaced", function () {
        refreshNavBadges({ pulse: false });
      });

      document.addEventListener("visibilitychange", function () {
        if (!document.hidden) refreshNavBadges({ pulse: false });
      });

      refreshNavBadges({ pulse: false });
      window.setInterval(function () {
        refreshNavBadges({ pulse: false });
      }, 45000);
    }

    const offlineBanner = document.getElementById("offlineBanner");
    const installBanner = document.getElementById("installBanner");
    const installModal = document.getElementById("installModal");
    const androidInstallBar = document.getElementById("androidInstallBar");
    const androidInstallBtn = document.getElementById("androidInstallBtn");
    const androidInstallClose = document.getElementById("androidInstallClose");
    const pwaBannerInstall = document.getElementById("pwaBannerInstall");
    const pwaHowBtn = document.getElementById("pwaHowBtn");
    const pwaBannerLater = document.getElementById("pwaBannerLater");
    const pwaModalInstall = document.getElementById("pwaModalInstall");
    const pwaModalLater = document.getElementById("pwaModalLater");
    const pwaModalToday = document.getElementById("pwaModalToday");
    const iosHint = document.getElementById("iosHint");
    const PWA_HIDE_UNTIL_KEY = "pwa_hide_until";
    let onlineNoticeTimer = null;
    let wasOffline = !navigator.onLine;
    let androidShimmerTimer = null;
    let androidShimmerCleanupTimer = null;

    const prefersReducedMotion = Boolean(
      window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );

    function isIOS() {
      return /iphone|ipad|ipod/i.test(window.navigator.userAgent || "");
    }

    function isIOSSafari() {
      const ua = window.navigator.userAgent || "";
      const iOS = /iphone|ipad|ipod/i.test(ua);
      const webkit = /WebKit/i.test(ua);
      const otherIOSBrowser = /(CriOS|FxiOS|EdgiOS|OPiOS|OPT|DuckDuckGo)/i.test(ua);
      return iOS && webkit && !otherIOSBrowser;
    }

    function isAndroid() {
      return /android/i.test(window.navigator.userAgent || "");
    }

    function isStandalone() {
      const standaloneDisplay = window.matchMedia && window.matchMedia("(display-mode: standalone)").matches;
      const iosStandalone = window.navigator.standalone === true;
      return Boolean(standaloneDisplay || iosStandalone);
    }

    function canUseStorage() {
      try {
        const key = "__pwa_test__";
        localStorage.setItem(key, "1");
        localStorage.removeItem(key);
        return true;
      } catch (_) {
        return false;
      }
    }

    function dayKey() {
      const d = new Date();
      return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate();
    }

    function hideInstallFor24h() {
      if (!canUseStorage()) return;
      const until = Date.now() + 24 * 60 * 60 * 1000;
      localStorage.setItem(PWA_HIDE_UNTIL_KEY, String(until));
    }

    function hideInstallUntilEndOfDay() {
      if (!canUseStorage()) return;
      const now = new Date();
      const until = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate(),
        23,
        59,
        59,
        999
      ).getTime();
      localStorage.setItem(PWA_HIDE_UNTIL_KEY, String(until));
    }

    function shouldHideInstall() {
      if (!canUseStorage()) return false;
      const until = Number(localStorage.getItem(PWA_HIDE_UNTIL_KEY) || "0");
      return Date.now() < until;
    }

    function shouldShowPwaModal() {
      if (!canUseStorage()) return true;
      return localStorage.getItem("pwa_modal_last") !== dayKey();
    }

    function markPwaModalShownToday() {
      if (!canUseStorage()) return;
      localStorage.setItem("pwa_modal_last", dayKey());
    }

    function closePwaModal() {
      if (!installModal) return;
      installModal.classList.add("hidden");
      installModal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("install-modal-open");
      hardResetUI("install-modal");
    }

    function closePwaBanner() {
      if (!installBanner) return;
      installBanner.classList.add("hidden");
    }

    function showPwaModal() {
      if (!installModal) return;
      installModal.classList.remove("hidden");
      installModal.setAttribute("aria-hidden", "false");
      document.body.classList.add("install-modal-open");
      lockScroll("install-modal");
    }

    function dismissedAndroidInstallToday() {
      if (!canUseStorage()) return false;
      const value = Number(localStorage.getItem("install_bar_dismissed_at") || "0");
      if (!value) return false;
      const oneDay = 24 * 60 * 60 * 1000;
      return Date.now() - value < oneDay;
    }

    function dismissAndroidInstallForToday() {
      if (!canUseStorage()) return;
      localStorage.setItem("install_bar_dismissed_at", String(Date.now()));
    }

    function stopAndroidInstallEffects() {
      if (androidShimmerTimer) {
        window.clearInterval(androidShimmerTimer);
        androidShimmerTimer = null;
      }
      if (androidShimmerCleanupTimer) {
        window.clearTimeout(androidShimmerCleanupTimer);
        androidShimmerCleanupTimer = null;
      }
      if (androidInstallBtn) {
        androidInstallBtn.classList.remove("pulse");
        androidInstallBtn.classList.remove("shimmer");
      }
    }

    function hideAndroidInstallBar() {
      if (!androidInstallBar) return;
      stopAndroidInstallEffects();
      androidInstallBar.classList.remove("show");
      window.setTimeout(function () {
        androidInstallBar.classList.add("hidden");
      }, 240);
    }

    function startAndroidInstallEffects() {
      if (!androidInstallBtn || prefersReducedMotion) return;
      stopAndroidInstallEffects();
      androidInstallBtn.classList.add("pulse");
      androidShimmerTimer = window.setInterval(function () {
        if (!androidInstallBtn || !androidInstallBar || androidInstallBar.classList.contains("hidden")) return;
        androidInstallBtn.classList.add("shimmer");
        androidShimmerCleanupTimer = window.setTimeout(function () {
          if (androidInstallBtn) androidInstallBtn.classList.remove("shimmer");
        }, 1000);
      }, 7000);
    }

    function showAndroidInstallBar() {
      if (!androidInstallBar) return;
      if (!isAndroid()) return;
      if (isStandalone()) return;
      if (!deferredInstallPrompt) return;
      if (dismissedAndroidInstallToday()) return;
      if (window.location.pathname.startsWith("/admin")) return;

      closePwaBanner();
      closePwaModal();
      androidInstallBar.classList.remove("hidden");
      window.requestAnimationFrame(function () {
        androidInstallBar.classList.add("show");
      });
      startAndroidInstallEffects();
    }

    function showSoftInstallUI() {
      if (!installBanner || !installModal) return;
      if (document.querySelector("[data-home-bottom-tabs]")) {
        document.body.classList.add("has-home-bottom-tabs");
      }
      if (isStandalone()) return;
      if (window.location.pathname.startsWith("/admin")) return;
      if (shouldHideInstall()) return;
      if (isAndroid()) {
        closePwaBanner();
        closePwaModal();
        showAndroidInstallBar();
        return;
      }
      installBanner.classList.remove("hidden");

      if (shouldShowPwaModal()) {
        showPwaModal();
        markPwaModalShownToday();
      }

      if (isIOSSafari()) {
        if (iosHint) iosHint.classList.remove("hidden");
        if (pwaBannerInstall) pwaBannerInstall.classList.add("hidden");
        if (pwaHowBtn) pwaHowBtn.classList.remove("hidden");
        if (pwaModalInstall) pwaModalInstall.classList.add("hidden");
      } else {
        if (iosHint) iosHint.classList.add("hidden");
        if (pwaBannerInstall) pwaBannerInstall.classList.remove("hidden");
        if (pwaHowBtn) pwaHowBtn.classList.add("hidden");
        if (pwaModalInstall) pwaModalInstall.classList.remove("hidden");
      }
    }

    async function handleInstallClick() {
      if (isIOSSafari()) {
        hideInstallFor24h();
        closePwaBanner();
        showPwaModal();
        return;
      }

      if (!deferredInstallPrompt) {
        showPwaModal();
        return;
      }

      try {
        deferredInstallPrompt.prompt();
        await deferredInstallPrompt.userChoice;
      } catch (_) {
        // Keep UX stable if prompt fails.
      } finally {
        deferredInstallPrompt = null;
      }
    }

    function refreshOnlineRequiredUI() {
      const offline = !navigator.onLine;
      const nodes = new Set();

      document.querySelectorAll("[data-requires-online]").forEach(function (node) {
        nodes.add(node);
      });

      document.querySelectorAll("a[href]").forEach(function (anchor) {
        if (isOnlineRequiredPath(safePath(anchor.href))) {
          nodes.add(anchor);
        }
      });

      document.querySelectorAll("form").forEach(function (form) {
        const action = form.getAttribute("action") || window.location.pathname;
        const requiresOnline = form.hasAttribute("data-requires-online") || isOnlineRequiredPath(safePath(action));
        if (!requiresOnline) return;
        form.querySelectorAll("button, input[type='submit']").forEach(function (submitter) {
          nodes.add(submitter);
        });
      });

      nodes.forEach(function (node) {
        node.classList.toggle("is-offline-disabled", offline);
        if (offline && "disabled" in node && node.tagName !== "A") {
          if (!node.hasAttribute("data-offline-original-disabled")) {
            node.setAttribute("data-offline-original-disabled", node.disabled ? "1" : "0");
          }
          node.disabled = true;
        } else if (!offline && "disabled" in node && node.hasAttribute("data-offline-original-disabled")) {
          node.disabled = node.getAttribute("data-offline-original-disabled") === "1";
          node.removeAttribute("data-offline-original-disabled");
        }

        if (node.tagName === "A") {
          node.setAttribute("aria-disabled", offline ? "true" : "false");
        }
      });
    }

    function showOfflineActionNotice() {
      if (offlineBanner) {
        offlineBanner.textContent = "Connexion requise pour cette action.";
        offlineBanner.classList.add("show");
        return;
      }
      window.alert("Connexion requise pour cette action.");
    }

    function updateOfflineBanner() {
      if (!offlineBanner) return;
      if (!navigator.onLine) {
        if (onlineNoticeTimer) {
          window.clearTimeout(onlineNoticeTimer);
          onlineNoticeTimer = null;
        }
        offlineBanner.textContent = "Hors connexion - mode lecture";
        offlineBanner.classList.add("show");
        wasOffline = true;
      } else {
        if (wasOffline) {
          offlineBanner.textContent = "Connexion retablie";
          offlineBanner.classList.add("show");
          onlineNoticeTimer = window.setTimeout(function () {
            offlineBanner.classList.remove("show");
          }, 1600);
        } else {
          offlineBanner.classList.remove("show");
        }
        wasOffline = false;
      }
      refreshOnlineRequiredUI();
    }

    document.addEventListener(
      "click",
      function (e) {
        if (navigator.onLine) return;
        if (!elementNeedsOnline(e.target)) return;
        e.preventDefault();
        e.stopPropagation();
        showOfflineActionNotice();
      },
      true
    );

    document.addEventListener(
      "submit",
      function (e) {
        if (navigator.onLine) return;
        const form = e.target;
        if (!form || !form.matches || !form.matches("form")) return;
        const action = form.getAttribute("action") || window.location.pathname;
        const needsOnline = form.hasAttribute("data-requires-online") || isOnlineRequiredPath(safePath(action));
        if (!needsOnline) return;
        e.preventDefault();
        e.stopPropagation();
        showOfflineActionNotice();
      },
      true
    );

    window.addEventListener("online", updateOfflineBanner);
    window.addEventListener("offline", updateOfflineBanner);
    updateOfflineBanner();

    if (pwaBannerInstall) {
      pwaBannerInstall.addEventListener("click", handleInstallClick);
    }
    if (pwaHowBtn) {
      pwaHowBtn.addEventListener("click", function () {
        hideInstallFor24h();
        closePwaBanner();
        showPwaModal();
      });
    }
    if (pwaModalInstall) {
      pwaModalInstall.addEventListener("click", handleInstallClick);
    }
    if (pwaBannerLater) {
      pwaBannerLater.addEventListener("click", function () {
        hideInstallFor24h();
        closePwaBanner();
      });
    }
    if (pwaModalLater) {
      pwaModalLater.addEventListener("click", closePwaModal);
    }
    if (pwaModalToday) {
      pwaModalToday.addEventListener("click", function () {
        hideInstallUntilEndOfDay();
        markPwaModalShownToday();
        closePwaModal();
      });
    }
    if (installModal) {
      installModal.addEventListener("click", function (e) {
        if (e.target === installModal) closePwaModal();
      });
    }

    window.addEventListener("pwa:beforeinstallprompt-ready", function () {
      showAndroidInstallBar();
    });

    if (androidInstallBtn) {
      androidInstallBtn.addEventListener("click", async function () {
        if (!deferredInstallPrompt) return;
        if (!prefersReducedMotion) {
          androidInstallBtn.classList.remove("pulse");
          androidInstallBtn.classList.add("shimmer");
          window.setTimeout(function () {
            androidInstallBtn.classList.remove("shimmer");
          }, 900);
        }

        try {
          deferredInstallPrompt.prompt();
          await deferredInstallPrompt.userChoice;
        } catch (_) {
          // Keep UI stable if prompt fails.
        } finally {
          deferredInstallPrompt = null;
          hideAndroidInstallBar();
        }
      });
    }

    if (androidInstallClose) {
      androidInstallClose.addEventListener("click", function () {
        dismissAndroidInstallForToday();
        hideAndroidInstallBar();
      });
    }

    if (window.matchMedia) {
      const standaloneMedia = window.matchMedia("(display-mode: standalone)");
      const handleStandaloneChange = function () {
        if (!isStandalone()) return;
        closePwaModal();
        closePwaBanner();
      };
      if (typeof standaloneMedia.addEventListener === "function") {
        standaloneMedia.addEventListener("change", handleStandaloneChange);
      } else if (typeof standaloneMedia.addListener === "function") {
        standaloneMedia.addListener(handleStandaloneChange);
      }
    }

    window.addEventListener("appinstalled", function () {
      closePwaModal();
      closePwaBanner();
      hideAndroidInstallBar();
      deferredInstallPrompt = null;
    });

    window.addEventListener("load", function () {
      showSoftInstallUI();
      if (deferredInstallPrompt) {
        showAndroidInstallBar();
      }
    }, { once: true });

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) return;
      if (isStandalone()) {
        closePwaModal();
        closePwaBanner();
        return;
      }
      if (!shouldHideInstall() && !isAndroid() && installBanner) {
        installBanner.classList.remove("hidden");
      }
    });

    window.addEventListener("focus", function () {
      if (isStandalone()) {
        closePwaModal();
        closePwaBanner();
      }
    });

    if ("serviceWorker" in navigator) {
      const staticVersion = (document.body && document.body.dataset && document.body.dataset.staticVersion) || "dev";
      const swUrl = "/sw.js?v=" + encodeURIComponent(staticVersion);
      navigator.serviceWorker
        .register(swUrl, { scope: "/", updateViaCache: "none" })
        .then(function (registration) {
          if (registration && typeof registration.update === "function") {
            registration.update().catch(function () {});
          }
        })
        .catch(function () {});
    }
  });
})();
