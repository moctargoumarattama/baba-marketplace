(function () {
  "use strict";

  if (window.__BM_AJAX_CORE_INIT__ && window.BMAjaxGuard) {
    return;
  }
  window.__BM_AJAX_CORE_INIT__ = true;

  const LOCK_UNTIL_KEY = "bmLockUntil";
  const LOCK_PREV_DISABLED_KEY = "bmLockPrevDisabled";

  function lock(el, ms) {
    if (!el || !el.dataset) return false;

    const now = Date.now();
    const waitMs = Math.max(0, Number(ms) || 900);
    const currentUntil = parseInt(el.dataset[LOCK_UNTIL_KEY] || "0", 10);
    if (!Number.isNaN(currentUntil) && currentUntil > now) {
      return false;
    }

    const until = now + waitMs;
    el.dataset[LOCK_UNTIL_KEY] = String(until);
    el.dataset[LOCK_PREV_DISABLED_KEY] =
      "disabled" in el && el.disabled ? "1" : "0";

    if ("disabled" in el) {
      el.disabled = true;
    }
    if (el.classList) {
      el.classList.add("is-loading");
    }

    if (waitMs > 0) {
      window.setTimeout(function () {
        const stillLockedUntil = parseInt(el.dataset[LOCK_UNTIL_KEY] || "0", 10);
        if (stillLockedUntil === until) {
          unlock(el);
        }
      }, waitMs + 16);
    }
    return true;
  }

  function unlock(el) {
    if (!el || !el.dataset) return;

    const prevDisabled = el.dataset[LOCK_PREV_DISABLED_KEY] === "1";
    delete el.dataset[LOCK_UNTIL_KEY];
    delete el.dataset[LOCK_PREV_DISABLED_KEY];

    if ("disabled" in el) {
      el.disabled = prevDisabled;
    }
    if (el.classList) {
      el.classList.remove("is-loading");
    }
  }

  function makeRequestSeq() {
    let latest = 0;
    return {
      next: function () {
        latest += 1;
        return latest;
      },
      isLatest: function (id) {
        return Number(id) === latest;
      },
      current: function () {
        return latest;
      },
    };
  }

  const api = window.BMAjaxGuard || {};
  api.lock = lock;
  api.unlock = unlock;
  api.makeRequestSeq = makeRequestSeq;
  window.BMAjaxGuard = api;
})();


