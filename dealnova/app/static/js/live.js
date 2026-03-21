(() => {
  if (typeof window === "undefined") return;

  const noop = () => {};
  if (typeof window.initFraudPage !== "function") window.initFraudPage = noop;
  if (typeof window.updatePending !== "function") window.updatePending = noop;
  if (typeof window.updateToConfirm !== "function") window.updateToConfirm = noop;
  if (typeof window.initLiveFeatures !== "function") window.initLiveFeatures = noop;

  // Legacy entrypoint kept for compatibility with existing templates.
  const core = window.BMCoreLive;
  if (!core || typeof core.init !== "function") {
    // Legacy kept for safety: if core files fail to load, do not throw.
    return;
  }
  core.init();
})();

