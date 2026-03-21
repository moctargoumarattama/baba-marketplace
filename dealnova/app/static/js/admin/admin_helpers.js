(function () {
  "use strict";

  if (window.AdminHelpers) return;

  function restoreInstantScroll(y) {
    if (typeof window.restoreInstantScroll === "function") {
      window.restoreInstantScroll(y);
      return;
    }
    const target = Math.max(Number(y || 0), 0);
    requestAnimationFrame(function () {
      try {
        window.scrollTo({ top: target, left: 0, behavior: "instant" });
      } catch (_err) {
        window.scrollTo(0, target);
      }
    });
  }

  function initBackToTop(options) {
    const cfg = options || {};
    const button = cfg.button || (cfg.selector ? document.querySelector(cfg.selector) : null);
    if (!button) return { destroy: function () {} };

    const threshold = Number(cfg.threshold || 300);
    const behavior = cfg.behavior || "smooth";

    const onScroll = function () {
      button.classList.toggle("show", (window.scrollY || 0) > threshold);
    };

    const onClick = function () {
      window.scrollTo({ top: 0, behavior: behavior });
    };

    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    button.addEventListener("click", onClick);

    return {
      destroy: function () {
        window.removeEventListener("scroll", onScroll);
        button.removeEventListener("click", onClick);
      },
    };
  }

  function initScrollMemory(options) {
    const cfg = options || {};
    const key = String(cfg.key || "").trim();
    if (!key) {
      return {
        save: function () {},
        restore: function () {},
        bind: function () {},
      };
    }

    const useLocalScroll = cfg.useLocalScroll !== false;
    if (!useLocalScroll) {
      return {
        save: function () {},
        restore: function () {},
        bind: function () {},
      };
    }

    const storage = cfg.storage || window.localStorage;
    const maxAgeMs = Number(cfg.maxAgeMs || 5 * 60 * 1000);
    const saveDebounceMs = Number(cfg.saveDebounceMs || 250);
    const behavior = cfg.behavior || "smooth";
    const getContext = typeof cfg.getContext === "function" ? cfg.getContext : null;
    const matchContext = typeof cfg.matchContext === "function" ? cfg.matchContext : null;
    const debug = !!cfg.debug;
    let saveTimer = null;

    function log() {
      if (!debug) return;
      try {
        // eslint-disable-next-line no-console
        console.log.apply(console, ["[AdminHelpers.scroll]"].concat(Array.prototype.slice.call(arguments)));
      } catch (_err) {}
    }

    function read() {
      try {
        const raw = storage.getItem(key);
        if (!raw) return null;
        return JSON.parse(raw);
      } catch (_err) {
        return null;
      }
    }

    function clear() {
      try {
        storage.removeItem(key);
      } catch (_err) {}
    }

    function save() {
      const viewportHeight = window.innerHeight || 0;
      const documentHeight = document.documentElement ? document.documentElement.scrollHeight : 0;
      const maxScroll = Math.max(documentHeight - viewportHeight, 1);
      const scrollY = Math.max(window.scrollY || 0, 0);
      const scrollPercentage = (scrollY / maxScroll) * 100;
      const context = getContext ? getContext() : null;

      try {
        storage.setItem(
          key,
          JSON.stringify({
            scrollY: scrollY,
            scrollPercentage: scrollPercentage,
            context: context,
            timestamp: Date.now(),
          })
        );
      } catch (_err) {}
    }

    function saveDebounced() {
      if (saveTimer) window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(function () {
        save();
      }, Math.max(0, saveDebounceMs));
    }

    function restore() {
      const payload = read();
      if (!payload) return false;

      const age = Date.now() - Number(payload.timestamp || 0);
      if (age > maxAgeMs) {
        clear();
        return false;
      }

      const currentContext = getContext ? getContext() : null;
      let shouldRestore = true;
      if (matchContext) {
        shouldRestore = !!matchContext(payload.context || null, currentContext);
      } else if (getContext) {
        shouldRestore = JSON.stringify(payload.context || null) === JSON.stringify(currentContext);
      }

      if (!shouldRestore) {
        clear();
        return false;
      }

      window.setTimeout(function () {
        const viewportHeight = window.innerHeight || 0;
        const documentHeight = document.documentElement ? document.documentElement.scrollHeight : 0;
        const maxScroll = Math.max(documentHeight - viewportHeight, 0);
        const percentage = Number(payload.scrollPercentage || 0);
        const fallbackY = Math.max(Number(payload.scrollY || 0), 0);
        const targetY = Math.max(Math.min((percentage / 100) * maxScroll, maxScroll), 0);

        if (behavior === "instant") {
          restoreInstantScroll(Number.isFinite(targetY) ? targetY : fallbackY);
        } else {
          window.scrollTo({
            top: Number.isFinite(targetY) ? targetY : fallbackY,
            behavior: behavior,
          });
        }
      }, Number(cfg.restoreDelayMs || 100));

      clear();
      log("restored", key);
      return true;
    }

    function bind() {
      window.addEventListener("beforeunload", save);
      window.addEventListener(
        "scroll",
        function () {
          saveDebounced();
        },
        { passive: true }
      );

      const selectors = Array.isArray(cfg.saveOnSelectors) ? cfg.saveOnSelectors : [];
      selectors.forEach(function (selector) {
        document.querySelectorAll(selector).forEach(function (el) {
          if (el.dataset.scrollSaveBound === "1") return;
          el.dataset.scrollSaveBound = "1";
          el.addEventListener("click", save);
        });
      });
    }

    return { save: save, restore: restore, bind: bind };
  }

  window.AdminHelpers = {
    restoreInstantScroll: restoreInstantScroll,
    initBackToTop: initBackToTop,
    initScrollMemory: initScrollMemory,
  };
})();


