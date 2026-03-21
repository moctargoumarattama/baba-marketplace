(function () {
  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  function normalizePath(raw) {
    try {
      const url = new URL(raw, window.location.origin);
      return (url.pathname || "/").replace(/\/+$/, "") || "/";
    } catch (_err) {
      return "/";
    }
  }

  onReady(function () {
    const tabs = document.querySelector("[data-home-bottom-tabs]");
    if (!tabs) return;

    const links = Array.prototype.slice.call(tabs.querySelectorAll(".home-tab[href], .bm-home-tab[href]"));
    if (!links.length) return;

    const currentPath = normalizePath(window.location.pathname);

    links.forEach(function (link) {
      const targetPath = normalizePath(link.getAttribute("href") || "/");
      const active = targetPath === currentPath;
      link.classList.toggle("is-active", active);

      const pressOn = function () { link.classList.add("is-pressed"); };
      const pressOff = function () { link.classList.remove("is-pressed"); };
      link.addEventListener("pointerdown", pressOn, { passive: true });
      link.addEventListener("pointerup", pressOff, { passive: true });
      link.addEventListener("pointercancel", pressOff, { passive: true });
      link.addEventListener("blur", pressOff, { passive: true });
    });
  });
})();

