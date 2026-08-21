(function () {
  "use strict";

  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const csrfToken = csrfMeta ? (csrfMeta.getAttribute("content") || "") : "";
  window.csrfToken = csrfToken;
  let deferredInstallPrompt = null;
  const uiScrollLocks = new Set();
  const perfFlags = window.BM_PERF_FLAGS || {};
  const frontFluidityEnabled = perfFlags.frontFluidity !== false;
  const PWA_SESSION_SCOPE_KEY = "bm:pwa-session-scope";
  const PWA_STORAGE_PREFIX = "bm:pwa:v2";
  const PWA_STORAGE_VERSION = (document.body && document.body.dataset && document.body.dataset.staticVersion) || "dev";
  const PWA_DEBUG = (function () {
    try {
      return (
        window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1" ||
        localStorage.getItem("pwaDebug") === "1"
      );
    } catch (_error) {
      return window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    }
  })();

  function pwaLog(level) {
    if (!PWA_DEBUG || !window.console) return;
    const method = typeof window.console[level] === "function" ? level : "log";
    const args = Array.prototype.slice.call(arguments, 1);
    window.console[method].apply(window.console, ["[PWA]"].concat(args));
  }

  function scheduleLowPriority(callback, timeoutMs) {
    if (typeof callback !== "function") return;
    const delay = Math.max(0, Number(timeoutMs) || 0);
    if (typeof window.requestIdleCallback === "function") {
      window.requestIdleCallback(function () {
        callback();
      }, { timeout: Math.max(300, delay || 800) });
      return;
    }
    window.setTimeout(callback, delay);
  }

  function pwaStorageKey(name) {
    return PWA_STORAGE_PREFIX + ":" + PWA_STORAGE_VERSION + ":" + String(name || "");
  }

  function migrateLegacyPwaStorage() {
    try {
      const migrationKey = pwaStorageKey("legacy-migrated");
      if (localStorage.getItem(migrationKey) === "1") return;
      localStorage.removeItem("pwa_hide_until");
      localStorage.removeItem("pwa_modal_last");
      localStorage.removeItem("install_bar_dismissed_at");
      localStorage.setItem(migrationKey, "1");
    } catch (_error) {
      // Ignore storage migration failures and keep the PWA flow usable.
    }
  }

  function getConnectionInfo() {
    const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection || null;
    const effectiveType = conn ? String(conn.effectiveType || "").toLowerCase() : "";
    const saveData = !!(conn && conn.saveData);
    const online = navigator.onLine !== false;
    const slow = !!(
      online &&
      (
        saveData ||
        effectiveType === "slow-2g" ||
        effectiveType === "2g" ||
        effectiveType === "3g"
      )
    );
    return {
      online: online,
      slow: slow,
      saveData: saveData,
      effectiveType: effectiveType,
    };
  }

  function applyConnectionInfo(info) {
    const state = info || getConnectionInfo();
    window.BMConnectionInfo = state;
    if (document && document.documentElement) {
      document.documentElement.setAttribute("data-bm-connection", state.slow ? "slow" : "normal");
      document.documentElement.setAttribute("data-bm-effective-type", state.effectiveType || "unknown");
    }
    return state;
  }

  function readConnectionInfo() {
    return applyConnectionInfo(getConnectionInfo());
  }

  function slowConnectionMessage(state) {
    if (state && state.saveData) {
      return "Connexion lente - economie de donnees active";
    }
    return "Connexion lente detectee - mode allege";
  }

  function currentSessionScope() {
    const body = document.body;
    if (!body || !body.dataset) return "anon";
    const scope = String(body.dataset.sessionScope || "").trim();
    return scope || "anon";
  }

  function postServiceWorkerMessage(message) {
    if (!("serviceWorker" in navigator) || !message) return;
    const controller = navigator.serviceWorker.controller;
    if (!controller || typeof controller.postMessage !== "function") return;
    try {
      controller.postMessage(message);
    } catch (_error) {}
  }

  async function clearPublicPageCaches() {
    if (!("caches" in window)) return false;
    try {
      const keys = await window.caches.keys();
      await Promise.all(
        keys
          .filter(function (key) {
            return key.indexOf("dealnova-") === 0 && /-pages$/.test(key);
          })
          .map(function (key) {
            return window.caches.delete(key);
          })
      );
      postServiceWorkerMessage({ type: "BM_CLEAR_PUBLIC_PAGE_CACHE" });
      return true;
    } catch (error) {
      pwaLog("warn", "Failed to clear public page caches", error);
      return false;
    }
  }

  async function reconcilePwaSessionScope() {
    const nextScope = currentSessionScope();
    let previousScope = "";
    try {
      previousScope = localStorage.getItem(PWA_SESSION_SCOPE_KEY) || "";
    } catch (_error) {
      previousScope = "";
    }

    const shouldClear = previousScope ? previousScope !== nextScope : nextScope !== "anon";
    if (shouldClear) {
      pwaLog("info", "Session scope changed, clearing cached public pages", {
        from: previousScope || "(none)",
        to: nextScope,
      });
      await clearPublicPageCaches();
    }

    try {
      localStorage.setItem(PWA_SESSION_SCOPE_KEY, nextScope);
    } catch (_error) {}
  }

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
    "/vendor",
    "/cart",
    "/login",
    "/logout",
    "/register",
    "/lang",
    "/booking",
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

  function trackAnalyticsEvent(eventName, extra) {
    const name = String(eventName || "").trim();
    if (!name) return;
    const payload = Object.assign(
      {
        event: name,
        path: window.location.pathname || "/",
        surface: "public",
      },
      extra || {}
    );
    const body = JSON.stringify(payload);
    const csrfApi = window.BMAjaxCSRF;
    const headers = csrfApi && typeof csrfApi.addToHeaders === "function"
      ? csrfApi.addToHeaders(
          {
            "Content-Type": "application/json",
            "X-Requested-With": "fetch",
          },
          null
        )
      : {
          "Content-Type": "application/json",
          "X-Requested-With": "fetch",
          "X-CSRFToken": csrfToken,
        };

    try {
      fetch("/api/analytics/event", {
        method: "POST",
        headers: headers,
        body: body,
        credentials: "same-origin",
        keepalive: true,
      }).catch(function () {});
    } catch (_error) {}
  }

  window.BMAnalytics = window.BMAnalytics || {
    track: trackAnalyticsEvent,
  };

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
    let pwaScopeSyncQueued = false;
    function schedulePwaScopeSync(delayMs) {
      if (pwaScopeSyncQueued) return;
      pwaScopeSyncQueued = true;
      scheduleLowPriority(function () {
        pwaScopeSyncQueued = false;
        reconcilePwaSessionScope().catch(function (error) {
          pwaLog("warn", "Session scope reconciliation failed", error);
        });
      }, delayMs);
    }

    schedulePwaScopeSync(450);

    window.addEventListener("storage", function (event) {
      if (!event || event.key !== PWA_SESSION_SCOPE_KEY) return;
      const storedScope = String(event.newValue || "").trim();
      if (!storedScope || storedScope === currentSessionScope()) return;
      clearPublicPageCaches().catch(function (error) {
        pwaLog("warn", "Cross-tab public page cache clear failed", error);
      });
    });

    // Preserve and restore scroll per page to keep UX stable on back/forward/reload.
    (function preservePublicScroll() {
      const KEY_PREFIX = "bm:scroll:";

      function pageKeyFromLocation(loc) {
        const path = (loc && loc.pathname) || "";
        const search = (loc && loc.search) || "";
        return KEY_PREFIX + path + search;
      }

      function saveCurrentScroll() {
        try {
          const y = Math.max(window.scrollY || window.pageYOffset || 0, 0);
          sessionStorage.setItem(pageKeyFromLocation(window.location), String(y));
        } catch (_error) {}
      }

      function restoreCurrentScroll() {
        try {
          const key = pageKeyFromLocation(window.location);
          const raw = sessionStorage.getItem(key);
          if (raw == null) return;
          sessionStorage.removeItem(key);
          const y = parseInt(raw, 10);
          if (!Number.isFinite(y) || y < 0) return;
          requestAnimationFrame(function () {
            requestAnimationFrame(function () {
              try {
                window.scrollTo({ top: y, left: 0, behavior: "instant" });
              } catch (_e) {
                window.scrollTo(0, y);
              }
            });
          });
        } catch (_error) {}
      }

      if ("scrollRestoration" in history) {
        history.scrollRestoration = "manual";
      }

      window.addEventListener("beforeunload", saveCurrentScroll, { capture: true, passive: true });
      document.addEventListener(
        "submit",
        function (event) {
          const form = event.target;
          if (!form || form.dataset.preserveScroll === "off") return;
          saveCurrentScroll();
        },
        true
      );

      document.addEventListener(
        "click",
        function (event) {
          const link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
          if (!link) return;
          if (link.dataset.preserveScroll === "off") return;
          if (link.target && link.target !== "_self") return;
          const href = String(link.getAttribute("href") || "").trim();
          if (!href || href.startsWith("#") || href.startsWith("javascript:") || href.startsWith("mailto:") || href.startsWith("tel:")) return;
          let targetUrl;
          try {
            targetUrl = new URL(href, window.location.href);
          } catch (_error) {
            return;
          }
          if (targetUrl.origin !== window.location.origin) return;
          saveCurrentScroll();
        },
        true
      );

      window.addEventListener("pageshow", restoreCurrentScroll);
      restoreCurrentScroll();
    })();

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
    if (backBtn && backBtn.dataset.backManaged !== "1" && !window.__BM_BACK_FAB__) {
      function shouldShowBackButton() {
        const currentPath = window.location.pathname;
        const previousUrl = document.referrer || "";

        if (currentPath === "/" || currentPath === "/index.html") return false;
        if (window.history.length > 1) return true;
        if (!previousUrl) return false;
        try {
          const prev = new URL(previousUrl, window.location.origin);
          if (prev.origin !== window.location.origin) return false;
          if (prev.pathname === window.location.pathname && prev.search === window.location.search) return false;
          return true;
        } catch (_error) {
          return false;
        }
      }

      backBtn.style.display = shouldShowBackButton() ? "flex" : "none";

      backBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (window.history.length > 1) {
          window.history.back();
          return;
        }
        const fallback = backBtn.getAttribute("data-fallback") || "/";
        const previousUrl = document.referrer || "";
        if (previousUrl) {
          try {
            const prev = new URL(previousUrl, window.location.origin);
            if (prev.origin === window.location.origin) {
              window.location.assign(prev.href);
              return;
            }
          } catch (_error) {}
        }
        window.location.assign(fallback);
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
    let navConnectionInfo = window.BMConnectionInfo || readConnectionInfo();
    let restartNavPolling = function () {};

    if (hasNavBadges) {
      const rawAttnSeconds = Number(
        (navBadgeRoot && navBadgeRoot.getAttribute("data-cart-attn-seconds")) || 60
      );
      const cartAttentionMs = Math.max(5000, Math.min(120000, rawAttnSeconds * 1000));
      const prefersReducedMotion = Boolean(
        window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
      );
      const navRefreshSeq =
        window.BMCoreDom && typeof window.BMCoreDom.makeRequestSeq === "function"
          ? window.BMCoreDom.makeRequestSeq()
          : window.BMAjaxGuard && typeof window.BMAjaxGuard.makeRequestSeq === "function"
            ? window.BMAjaxGuard.makeRequestSeq()
          : (function () {
              let latest = 0;
              return {
                next: function () {
                  latest += 1;
                  return latest;
                },
                isLatest: function (id) {
                  return Number(id) === latest;
                },
              };
            })();
      let navRefreshAbortController = null;
      let cartAttentionTimer = null;
      let navPollStableCount = 0;
      const navPollHotMs = 90000;
      const navPollWarmMs = 150000;
      const navPollColdMs = 180000;
      const navState = {
        initialized: false,
        cartCount: Number((cartBadge && cartBadge.getAttribute("data-cart-count")) || (cartBadge && cartBadge.textContent) || 0) || 0,
        trackActive: Boolean(trackBadge && trackBadge.getAttribute("data-track-active") === "1"),
      };

      function currentNavPollMultiplier() {
        if (!navConnectionInfo || !navConnectionInfo.slow) return 1;
        return navConnectionInfo.saveData ? 3 : 2;
      }

      function scaledNavPollDelay(baseMs) {
        return Math.max(1000, Math.round(Number(baseMs || 0) * currentNavPollMultiplier()));
      }

      function nextNavPollDelay() {
        if (!navigator.onLine) return scaledNavPollDelay(navPollColdMs);
        if (navState.trackActive || navState.cartCount > 0) return scaledNavPollDelay(navPollHotMs);
        if (navPollStableCount >= 3) return scaledNavPollDelay(navPollColdMs);
        return scaledNavPollDelay(navPollWarmMs);
      }

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
          window.requestAnimationFrame(function () {
            node.classList.add("badge-pulse");
          });
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

      async function requestNavStatus(signal) {
        const coreDomApi = window.BMCoreDom || {};
        if (typeof coreDomApi.requestJSON === "function") {
          return coreDomApi.requestJSON("/cart/api/nav-status", {
            method: "GET",
            headers: {
              "X-Requested-With": "fetch",
              Accept: "application/json",
            },
            credentials: "same-origin",
            cache: "no-store",
            signal: signal,
            timeoutMs: 12000,
          });
        }
        if (window.BMAjaxFetch && typeof window.BMAjaxFetch.requestJSON === "function") {
          return window.BMAjaxFetch.requestJSON("/cart/api/nav-status", {
            method: "GET",
            headers: {
              "X-Requested-With": "fetch",
              Accept: "application/json",
            },
            credentials: "same-origin",
            cache: "no-store",
            signal: signal,
            timeoutMs: 12000,
          });
        }

        try {
          const response = await fetch("/cart/api/nav-status", {
            method: "GET",
            headers: {
              "X-Requested-With": "fetch",
              Accept: "application/json",
            },
            credentials: "same-origin",
            cache: "no-store",
            signal: signal,
          });
          let data = null;
          try {
            data = await response.json();
          } catch (_parseError) {
            data = null;
          }
          return {
            ok: response.ok,
            status: response.status,
            data: data,
            error: response.ok ? null : "nav-status-http",
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

      async function refreshNavBadges(options) {
        const requestId = navRefreshSeq.next();
        if (navRefreshAbortController) {
          try {
            navRefreshAbortController.abort();
          } catch (_abortError) {}
        }
        navRefreshAbortController = typeof AbortController !== "undefined" ? new AbortController() : null;
        try {
          const result = await requestNavStatus(navRefreshAbortController ? navRefreshAbortController.signal : undefined);
          if (!navRefreshSeq.isLatest(requestId)) return false;
          if (!result || result.aborted || result.timedOut || !result.ok) return false;
          const payload = result.data || {};
          const nextCartCount = Math.max(0, Number(payload && payload.cart_count) || 0);
          const nextTrackActive = Boolean(payload && payload.track_active);
          const changed =
            nextCartCount !== navState.cartCount ||
            nextTrackActive !== navState.trackActive ||
            !navState.initialized;
          applyNavState(
            {
              cartCount: nextCartCount,
              trackActive: nextTrackActive,
            },
            options || {}
          );
          navPollStableCount = changed ? 0 : Math.min(navPollStableCount + 1, 6);
          return changed;
        } catch (_) {
          // Keep UI stable on network or backend issues.
          return false;
        } finally {
          if (navRefreshSeq.isLatest(requestId)) {
            navRefreshAbortController = null;
          }
        }
      }

      function watchedPath(pathname) {
        if (!pathname) return false;
        if (pathname === "/cart/api/nav-status" || pathname === "/cart/api/summary") return false;
        if (pathname.startsWith("/cart/api/")) return true;
        if (pathname === "/cart/checkout" || pathname === "/cart/whatsapp") return true;
        return false;
      }

      document.addEventListener("bm:ajax:response", function (event) {
        const detail = event && event.detail ? event.detail : null;
        if (!detail || !detail.ok || detail.aborted || detail.timedOut) return;
        const pathname = safePath(detail.url || "");
        if (!watchedPath(pathname)) return;
        window.setTimeout(function () {
          refreshNavBadges({ pulse: true });
        }, 120);
      });

      window.refreshNavBadges = function (opts) {
        return refreshNavBadges(opts || {});
      };

      document.addEventListener("cart:changed", function () {
        refreshNavBadges({ pulse: true });
      });

      document.addEventListener("track:changed", function () {
        refreshNavBadges({ pulse: true });
      });

      document.addEventListener("bm:ajax-form-success", function (event) {
        const detail = event && event.detail ? event.detail : null;
        const action = detail && detail.action ? String(detail.action) : "";
        if (action !== "add-to-cart") return;
        refreshNavBadges({ pulse: true });
      });

      document.addEventListener("ajax:page-replaced", function () {
        refreshNavBadges({ pulse: false });
      });

      document.addEventListener("visibilitychange", function () {
        if (!document.hidden && navigator.onLine) refreshNavBadges({ pulse: false });
      });

      let navAutoSyncStarted = false;
      function startNavAutoSync() {
        if (navAutoSyncStarted) return;
        navAutoSyncStarted = true;

        if (navigator.onLine) {
          scheduleLowPriority(function () {
            refreshNavBadges({ pulse: false });
          }, 300);
        }

        if (window.BMAjaxPolling && typeof window.BMAjaxPolling.start === "function") {
          const startSharedPolling = function () {
            window.BMAjaxPolling.start({
              key: "ui-shell-nav-badges",
              fn: function () {
                return refreshNavBadges({ pulse: false });
              },
              intervalMs: scaledNavPollDelay(navPollHotMs),
              inactiveIntervalMs: scaledNavPollDelay(navPollColdMs),
              hiddenPause: true,
              when: function () {
                return !!document.querySelector("[data-nav-badges]") && navigator.onLine;
              },
            });
          };
          restartNavPolling = function () {
            if (!navAutoSyncStarted || !window.BMAjaxPolling || typeof window.BMAjaxPolling.stop !== "function") return;
            window.BMAjaxPolling.stop("ui-shell-nav-badges");
            startSharedPolling();
          };
          startSharedPolling();
          return;
        }

        let navPollTimer = null;
        function clearNavPollTimer() {
          if (navPollTimer) {
            clearTimeout(navPollTimer);
            navPollTimer = null;
          }
        }
        function scheduleNavPoll(delayMs) {
          clearNavPollTimer();
          navPollTimer = window.setTimeout(runNavPoll, Math.max(1000, Number(delayMs) || nextNavPollDelay()));
        }
        function runNavPoll() {
          if (document.hidden || !navigator.onLine) {
            clearNavPollTimer();
            return;
          }
          refreshNavBadges({ pulse: false }).finally(function () {
            scheduleNavPoll(nextNavPollDelay());
          });
        }

        document.addEventListener("visibilitychange", function () {
          if (document.hidden) {
            clearNavPollTimer();
            return;
          }
          if (!navigator.onLine) return;
          scheduleNavPoll(2500);
        });
        window.addEventListener("online", function () {
          scheduleNavPoll(2500);
        });
        window.addEventListener("offline", function () {
          clearNavPollTimer();
        });

        if (!document.hidden && navigator.onLine) {
          scheduleNavPoll(nextNavPollDelay());
        }
        restartNavPolling = function () {
          if (!navAutoSyncStarted || document.hidden || !navigator.onLine) return;
          scheduleNavPoll(1200);
        };
      }

      document.addEventListener("pointerdown", startNavAutoSync, { once: true, passive: true, capture: true });
      window.addEventListener("load", function () {
        scheduleLowPriority(startNavAutoSync, 700);
      }, { once: true });
    }

    const offlineBanner = document.getElementById("offlineBanner");
    const navOfflineHint = document.getElementById("navOfflineHint");
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
    const PWA_HIDE_UNTIL_KEY = pwaStorageKey("hide_until");
    const PWA_MODAL_LAST_KEY = pwaStorageKey("modal_last");
    const PWA_ANDROID_DISMISSED_KEY = pwaStorageKey("install_bar_dismissed_at");

    migrateLegacyPwaStorage();
    const onlineRequiredRegistry = {
      dirty: true,
      nodes: [],
    };
    let onlineNoticeTimer = null;
    let offlineActionNoticeTimer = null;
    let connectivityOverrideUntil = 0;
    let connectivityProbePromise = null;
    let wasOffline = !navigator.onLine;
    let wasSlowConnection = false;
    let androidShimmerTimer = null;
    let androidShimmerCleanupTimer = null;
    let connectionInfo = window.BMConnectionInfo || readConnectionInfo();

    const prefersReducedMotion = Boolean(
      window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );

    function isDrawerVisiblyOpen() {
      const drawer = document.getElementById("mainNavbar");
      return Boolean(drawer && drawer.classList.contains("show") && window.matchMedia("(max-width: 991.98px)").matches);
    }

    function isInstallModalOpen() {
      if (!installModal) return false;
      const ariaHidden = installModal.getAttribute("aria-hidden");
      return !installModal.classList.contains("hidden") && ariaHidden !== "true";
    }

    function ensureScrollLockConsistency() {
      const shouldLock = isDrawerVisiblyOpen() || isInstallModalOpen();
      if (!shouldLock) {
        if (
          uiScrollLocks.size > 0 ||
          document.documentElement.classList.contains("scroll-locked") ||
          document.body.classList.contains("scroll-locked")
        ) {
          hardResetUI();
        }
        return;
      }

      if (uiScrollLocks.size === 0) {
        if (isDrawerVisiblyOpen()) uiScrollLocks.add("drawer");
        if (isInstallModalOpen()) uiScrollLocks.add("install-modal");
      }
      applyScrollLockState();
    }

    window.ensureScrollLockConsistency = ensureScrollLockConsistency;

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

    function getEventElement(target) {
      if (!target) return null;
      if (target.nodeType === 1) return target;
      return target.parentElement || null;
    }

    function isEffectivelyOffline() {
      return !navigator.onLine && Date.now() > connectivityOverrideUntil;
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
      return localStorage.getItem(PWA_MODAL_LAST_KEY) !== dayKey();
    }

    function markPwaModalShownToday() {
      if (!canUseStorage()) return;
      localStorage.setItem(PWA_MODAL_LAST_KEY, dayKey());
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
      const value = Number(localStorage.getItem(PWA_ANDROID_DISMISSED_KEY) || "0");
      if (!value) return false;
      const oneDay = 24 * 60 * 60 * 1000;
      return Date.now() - value < oneDay;
    }

    function dismissAndroidInstallForToday() {
      if (!canUseStorage()) return;
      localStorage.setItem(PWA_ANDROID_DISMISSED_KEY, String(Date.now()));
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
        if (document.hidden) return;
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

    function collectOnlineRequiredNodes() {
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

      return Array.from(nodes);
    }

    function markOnlineRequiredRegistryDirty() {
      onlineRequiredRegistry.dirty = true;
    }

    function getOnlineRequiredNodes() {
      if (!frontFluidityEnabled) {
        return collectOnlineRequiredNodes();
      }
      if (!onlineRequiredRegistry.dirty && onlineRequiredRegistry.nodes.length) {
        onlineRequiredRegistry.nodes = onlineRequiredRegistry.nodes.filter(function (node) {
          return !!(node && node.isConnected);
        });
        return onlineRequiredRegistry.nodes;
      }
      onlineRequiredRegistry.nodes = collectOnlineRequiredNodes();
      onlineRequiredRegistry.dirty = false;
      return onlineRequiredRegistry.nodes;
    }

    function refreshOnlineRequiredUI() {
      const offline = isEffectivelyOffline();
      getOnlineRequiredNodes().forEach(function (node) {
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

    function clearOfflineActionNoticeTimer() {
      if (offlineActionNoticeTimer) {
        window.clearTimeout(offlineActionNoticeTimer);
        offlineActionNoticeTimer = null;
      }
    }

    function hideNavOfflineHint() {
      if (!navOfflineHint) return;
      navOfflineHint.classList.remove("show");
      navOfflineHint.textContent = "";
    }

    function resolveOfflineActionNode(node) {
      if (!node) return null;
      if (node.matches && node.matches("form")) return node;
      if (!node.closest) return null;
      return node.closest("[data-offline-message], [data-requires-online], a[href], button, input[type='submit'], form");
    }

    function resolveOfflineActionMessage(node) {
      const actionNode = resolveOfflineActionNode(node);
      const candidates = [
        actionNode,
        actionNode && actionNode.form ? actionNode.form : null,
      ];
      for (let i = 0; i < candidates.length; i += 1) {
        const candidate = candidates[i];
        if (!candidate || !candidate.getAttribute) continue;
        const message = (candidate.getAttribute("data-offline-message") || "").trim();
        if (message) return message;
      }
      return "Connexion requise pour cette action.";
    }

    function showOfflineActionNotice(node, explicitMessage) {
      const actionNode = resolveOfflineActionNode(node) || node;
      const message = String(explicitMessage || resolveOfflineActionMessage(actionNode) || "").trim()
        || "Connexion requise pour cette action.";
      const showNearNav = Boolean(
        navOfflineHint
        && actionNode
        && actionNode.closest
        && actionNode.closest("[data-nav-badges]")
      );

      clearOfflineActionNoticeTimer();
      hideNavOfflineHint();

      if (showNearNav) {
        navOfflineHint.textContent = message;
        navOfflineHint.classList.add("show");
      } else if (offlineBanner) {
        offlineBanner.textContent = message;
        offlineBanner.classList.add("show");
      } else {
        window.alert(message);
        return;
      }

      offlineActionNoticeTimer = window.setTimeout(function () {
        hideNavOfflineHint();
        updateOfflineBanner();
      }, 2400);
    }

    async function confirmOnlineReachability() {
      if (!isEffectivelyOffline()) return true;
      if (connectivityProbePromise) return connectivityProbePromise;

      const controller = typeof AbortController === "function" ? new AbortController() : null;
      const timeoutId = controller
        ? window.setTimeout(function () {
            controller.abort();
          }, 1800)
        : null;

      connectivityProbePromise = fetch("/health?_=" + Date.now(), {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "X-Requested-With": "fetch",
        },
        signal: controller ? controller.signal : undefined,
      })
        .then(function (response) {
          return Boolean(response && response.ok);
        })
        .catch(function () {
          return false;
        })
        .then(function (isReachable) {
          if (isReachable) {
            connectivityOverrideUntil = Date.now() + 12000;
          }
          return isReachable;
        })
        .finally(function () {
          if (timeoutId) {
            window.clearTimeout(timeoutId);
          }
          connectivityProbePromise = null;
          updateOfflineBanner();
        });

      return connectivityProbePromise;
    }

    function updateOfflineBanner() {
      if (!offlineBanner) return;
      connectionInfo = readConnectionInfo();
      const offline = isEffectivelyOffline();
      if (offline) {
        if (onlineNoticeTimer) {
          window.clearTimeout(onlineNoticeTimer);
          onlineNoticeTimer = null;
        }
        offlineBanner.textContent = "Hors connexion - mode lecture";
        offlineBanner.classList.add("show");
        wasOffline = true;
        wasSlowConnection = connectionInfo.slow;
      } else {
        if (wasOffline) {
          offlineBanner.textContent = "Connexion retablie";
          offlineBanner.classList.add("show");
          onlineNoticeTimer = window.setTimeout(function () {
            updateOfflineBanner();
          }, 1600);
        } else if (connectionInfo.slow) {
          if (onlineNoticeTimer) {
            window.clearTimeout(onlineNoticeTimer);
            onlineNoticeTimer = null;
          }
          offlineBanner.textContent = slowConnectionMessage(connectionInfo);
          offlineBanner.classList.add("show");
        } else if (wasSlowConnection) {
          offlineBanner.textContent = "Connexion stabilisee";
          offlineBanner.classList.add("show");
          onlineNoticeTimer = window.setTimeout(function () {
            offlineBanner.classList.remove("show");
          }, 1600);
        } else {
          if (onlineNoticeTimer) {
            window.clearTimeout(onlineNoticeTimer);
            onlineNoticeTimer = null;
          }
          offlineBanner.classList.remove("show");
        }
        wasOffline = false;
        wasSlowConnection = connectionInfo.slow;
      }
      refreshOnlineRequiredUI();
    }

    document.addEventListener(
      "click",
      async function (e) {
        const target = getEventElement(e.target);
        const bypassNode = target && target.closest ? target.closest("[data-bm-offline-verified='1']") : null;
        if (bypassNode) {
          bypassNode.removeAttribute("data-bm-offline-verified");
          return;
        }
        if (!isEffectivelyOffline()) return;
        if (!elementNeedsOnline(target)) return;
        e.preventDefault();
        e.stopPropagation();
        const reachable = await confirmOnlineReachability();
        if (reachable) {
          const anchor = target && target.closest ? target.closest("a[href]") : null;
          if (anchor && anchor.href) {
            window.location.assign(anchor.href);
            return;
          }

          const submitter = target && target.closest ? target.closest("button, input[type='submit']") : null;
          if (submitter && submitter.form) {
            submitter.form.setAttribute("data-bm-offline-verified", "1");
            if (typeof submitter.form.requestSubmit === "function") {
              submitter.form.requestSubmit(submitter);
            } else {
              submitter.form.submit();
            }
            return;
          }

          const actionNode = resolveOfflineActionNode(target);
          if (actionNode && actionNode.click) {
            actionNode.setAttribute("data-bm-offline-verified", "1");
            actionNode.click();
          }
          return;
        }
        showOfflineActionNotice(target);
      },
      true
    );

    document.addEventListener(
      "submit",
      async function (e) {
        const form = e.target;
        if (!form || !form.matches || !form.matches("form")) return;
        if (form.getAttribute("data-bm-offline-verified") === "1") {
          form.removeAttribute("data-bm-offline-verified");
          return;
        }
        const action = form.getAttribute("action") || window.location.pathname;
        const needsOnline = form.hasAttribute("data-requires-online") || isOnlineRequiredPath(safePath(action));
        if (!needsOnline || !isEffectivelyOffline()) return;
        e.preventDefault();
        e.stopPropagation();
        const reachable = await confirmOnlineReachability();
        if (reachable) {
          form.setAttribute("data-bm-offline-verified", "1");
          if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
          } else {
            form.submit();
          }
          return;
        }
        showOfflineActionNotice(form);
      },
      true
    );

    window.addEventListener("online", function () {
      connectivityOverrideUntil = 0;
      navConnectionInfo = readConnectionInfo();
      restartNavPolling();
      updateOfflineBanner();
    });
    window.addEventListener("offline", function () {
      connectivityOverrideUntil = 0;
      navConnectionInfo = readConnectionInfo();
      restartNavPolling();
      updateOfflineBanner();
    });
    const liveConnection = navigator.connection || navigator.mozConnection || navigator.webkitConnection || null;
    if (liveConnection) {
      const onConnectionChange = function () {
        navConnectionInfo = readConnectionInfo();
        restartNavPolling();
        updateOfflineBanner();
      };
      if (typeof liveConnection.addEventListener === "function") {
        liveConnection.addEventListener("change", onConnectionChange);
      } else if (typeof liveConnection.addListener === "function") {
        liveConnection.addListener(onConnectionChange);
      }
    }
    document.addEventListener("ajax:page-replaced", function () {
      markOnlineRequiredRegistryDirty();
      refreshOnlineRequiredUI();
    });
    updateOfflineBanner();

    document.addEventListener("shown.bs.collapse", function (e) {
      if (e && e.target && e.target.id === "mainNavbar") ensureScrollLockConsistency();
    });
    document.addEventListener("hidden.bs.collapse", function (e) {
      if (e && e.target && e.target.id === "mainNavbar") ensureScrollLockConsistency();
    });
    window.addEventListener("pageshow", function () {
      window.requestAnimationFrame(ensureScrollLockConsistency);
    });
    window.addEventListener("focus", function () {
      window.requestAnimationFrame(ensureScrollLockConsistency);
    });
    window.addEventListener("orientationchange", function () {
      window.setTimeout(ensureScrollLockConsistency, 120);
    });
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) window.requestAnimationFrame(ensureScrollLockConsistency);
    });
    window.requestAnimationFrame(ensureScrollLockConsistency);

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
      trackAnalyticsEvent("pwa_installed", { source: "browser_event" });
    });

    document.addEventListener("click", function (event) {
      const link = event.target && event.target.closest
        ? event.target.closest('a[href*="wa.me/"], a[href*="api.whatsapp.com/"]')
        : null;
      if (!link) return;
      trackAnalyticsEvent("whatsapp_open", {
        href: link.getAttribute("href") || "",
        page: window.location.pathname || "/",
      });
    }, true);

    let pwaInstallUiBooted = false;
    function bootPwaInstallUi() {
      if (pwaInstallUiBooted) return;
      pwaInstallUiBooted = true;
      showSoftInstallUI();
      if (deferredInstallPrompt) {
        showAndroidInstallBar();
      }
    }

    if (document.readyState === "complete" || document.readyState === "interactive") {
      scheduleLowPriority(bootPwaInstallUi, 0);
    } else {
      document.addEventListener("DOMContentLoaded", function () {
        scheduleLowPriority(bootPwaInstallUi, 0);
      }, { once: true });
    }
    window.addEventListener("load", bootPwaInstallUi, { once: true });

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) return;
      schedulePwaScopeSync(250);
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
      schedulePwaScopeSync(250);
      if (isStandalone()) {
        closePwaModal();
        closePwaBanner();
      }
    });

    function registerServiceWorker() {
      if (!("serviceWorker" in navigator)) return;
      const staticVersion = (document.body && document.body.dataset && document.body.dataset.staticVersion) || "dev";
      const swUrl = "/sw.js?v=" + encodeURIComponent(staticVersion) + (PWA_DEBUG ? "&debug=1" : "");
      let swRefreshTriggered = false;

      function requestWaitingWorkerActivation(registration, reason) {
        const waitingWorker = registration && registration.waiting;
        if (!waitingWorker || !navigator.serviceWorker.controller) return false;
        if (swRefreshTriggered) return true;
        swRefreshTriggered = true;
        pwaLog("info", "Activating waiting service worker", { reason: reason || "unknown" });
        try {
          waitingWorker.postMessage({ type: "BM_SKIP_WAITING" });
          return true;
        } catch (error) {
          swRefreshTriggered = false;
          pwaLog("warn", "Failed to activate waiting service worker", error);
          return false;
        }
      }

      navigator.serviceWorker.addEventListener("controllerchange", function () {
        pwaLog("info", "Service worker controller changed");
        if (!swRefreshTriggered) return;
        swRefreshTriggered = false;
        if (window.BMSafeRefresh && typeof window.BMSafeRefresh.request === "function") {
          window.BMSafeRefresh.request("sw_controllerchange", { delayMs: 120, replaceReason: true });
          return;
        }
        window.setTimeout(function () {
          try {
            window.location.reload();
          } catch (_error) {
            window.location.href = window.location.href;
          }
        }, 120);
      });
      navigator.serviceWorker
        .register(swUrl, { scope: "/", updateViaCache: "none" })
        .then(function (registration) {
          pwaLog("info", "Service worker registered", { scope: registration && registration.scope });
          if (registration && registration.waiting) {
            pwaLog("info", "Service worker update is waiting");
            requestWaitingWorkerActivation(registration, "register_waiting");
          }
          if (registration) {
            registration.addEventListener("updatefound", function () {
              const nextWorker = registration.installing;
              if (!nextWorker) return;
              pwaLog("info", "Service worker update found");
              nextWorker.addEventListener("statechange", function () {
                pwaLog("info", "Service worker state", nextWorker.state);
                if (nextWorker.state === "installed" && navigator.serviceWorker.controller) {
                  pwaLog("info", "New service worker installed and waiting");
                  requestWaitingWorkerActivation(registration, "update_installed");
                }
              });
            });
          }
          if (registration && typeof registration.update === "function") {
            registration.update().catch(function (error) {
              pwaLog("warn", "Service worker update failed", error);
            });
          }
        })
        .catch(function (error) {
          pwaLog("error", "Service worker registration failed", error);
        });
    }

    let serviceWorkerRegistrationQueued = false;
    function queueServiceWorkerRegistration() {
      if (serviceWorkerRegistrationQueued) return;
      serviceWorkerRegistrationQueued = true;
      scheduleLowPriority(registerServiceWorker, 250);
    }

    if (document.readyState === "complete" || document.readyState === "interactive") {
      queueServiceWorkerRegistration();
    } else {
      document.addEventListener("DOMContentLoaded", queueServiceWorkerRegistration, { once: true });
    }
    window.addEventListener("load", queueServiceWorkerRegistration, { once: true });
  });
})();
