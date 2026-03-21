(function () {
  "use strict";

  const polls = new Map();

  function clearTimer(state) {
    if (!state) return;
    if (state.timerId != null) {
      clearTimeout(state.timerId);
      state.timerId = null;
    }
  }

  function scheduleNext(state, delayMs) {
    clearTimer(state);
    state.timerId = window.setTimeout(function () {
      runPoll(state, false);
    }, Math.max(1000, Number(delayMs) || state.intervalMs));
  }

  function shouldRun(state) {
    if (!state || typeof state.when !== "function") {
      return true;
    }
    try {
      return state.when() !== false;
    } catch (_error) {
      return false;
    }
  }

  async function runPoll(state, force) {
    if (!state || state.inFlight) return;
    const hidden = document.hidden;
    if (state.hiddenPause && hidden && !force) {
      clearTimer(state);
      return;
    }
    if (!shouldRun(state)) {
      scheduleNext(state, state.inactiveIntervalMs);
      return;
    }

    state.inFlight = true;
    try {
      await state.fn();
    } catch (error) {
      console.error("[BMAjaxPolling]", error);
    } finally {
      state.inFlight = false;
    }

    if (!polls.has(state.key)) return;
    if (state.hiddenPause && document.hidden) {
      clearTimer(state);
      return;
    }
    scheduleNext(state, shouldRun(state) ? state.intervalMs : state.inactiveIntervalMs);
  }

  function start(options) {
    const opts = options || {};
    const key = String(opts.key || "").trim();
    const fn = opts.fn;
    const intervalMs = Math.max(1000, Number(opts.intervalMs) || 10000);
    const inactiveIntervalMs = Math.max(intervalMs, Number(opts.inactiveIntervalMs) || intervalMs * 2);
    const hiddenPause = opts.hiddenPause !== false;
    if (!key || typeof fn !== "function") {
      return false;
    }

    stop(key);

    const state = {
      key: key,
      fn: fn,
      intervalMs: intervalMs,
      inactiveIntervalMs: inactiveIntervalMs,
      hiddenPause: hiddenPause,
      when: typeof opts.when === "function" ? opts.when : null,
      inFlight: false,
      timerId: null,
    };

    polls.set(key, state);
    runPoll(state, true);
    return true;
  }

  function stop(key) {
    const id = String(key || "").trim();
    if (!id) return;
    const state = polls.get(id);
    if (!state) return;
    clearTimer(state);
    polls.delete(id);
  }

  document.addEventListener("visibilitychange", function () {
    polls.forEach(function (state) {
      if (!state || !state.hiddenPause) return;
      if (document.hidden) {
        clearTimer(state);
        return;
      }
      runPoll(state, true);
    });
  });

  const api = window.BMAjaxPolling || {};
  api.start = start;
  api.stop = stop;
  window.BMAjaxPolling = api;
})();

