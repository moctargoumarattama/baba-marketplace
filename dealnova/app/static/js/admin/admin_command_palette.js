(function () {
  "use strict";

  if (window.__BM_ADMIN_PALETTE_INIT__) return;
  window.__BM_ADMIN_PALETTE_INIT__ = true;

  var THEME_KEY = "admin_theme_mode";

  function bindGlobalThemeToggle() {
    var btn = document.getElementById("adminThemeToggle");
    if (!btn || btn.dataset.admThemeBound === "1") return;
    btn.dataset.admThemeBound = "1";

    function currentMode() {
      return document.documentElement.getAttribute("data-admin-theme") === "noc" ? "noc" : "default";
    }

    function applyMode(mode) {
      var next = mode === "noc" ? "noc" : "default";
      document.documentElement.setAttribute("data-admin-theme", next);
      try {
        window.localStorage.setItem(THEME_KEY, next);
      } catch (_err) {}
      var icon = btn.querySelector("i");
      var label = btn.querySelector("span");
      if (icon) {
        icon.className = next === "noc" ? "bi bi-sun" : "bi bi-moon-stars";
      }
      if (label) {
        label.textContent = next === "noc" ? "Clair" : "Thème";
      }
    }

    applyMode(currentMode());
    btn.addEventListener("click", function () {
      applyMode(currentMode() === "noc" ? "default" : "noc");
    });
  }

  function initCommandPalette() {
    var overlay = document.getElementById("adminCmdOverlay");
    var openBtn = document.getElementById("adminQuickSearchBtn");
    var closeBtn = document.getElementById("adminCmdClose");
    var input = document.getElementById("adminCmdInput");
    var resultsEl = document.getElementById("adminCmdResults");
    if (!overlay || !input || !resultsEl) return;

    var searchUrl = overlay.getAttribute("data-search-url") || "/admin/quick-search";
    var debounceTimer = null;
    var activeIndex = -1;
    var lastRequestId = 0;

    function getResultLinks() {
      return Array.prototype.slice.call(resultsEl.querySelectorAll("a.adm-cmd-item"));
    }

    function setActiveLink(nextIdx) {
      var links = getResultLinks();
      links.forEach(function (el) {
        el.classList.remove("is-active");
      });
      if (!links.length) {
        activeIndex = -1;
        return;
      }
      if (nextIdx < 0) nextIdx = links.length - 1;
      if (nextIdx >= links.length) nextIdx = 0;
      activeIndex = nextIdx;
      var current = links[activeIndex];
      current.classList.add("is-active");
      current.scrollIntoView({ block: "nearest" });
    }

    function createGroup(titleText, items, iconClass) {
      if (!items || !items.length) return null;
      var group = document.createElement("div");
      group.className = "adm-cmd-group";

      var label = document.createElement("div");
      label.className = "adm-cmd-group-title";
      label.textContent = titleText;
      group.appendChild(label);

      items.forEach(function (item) {
        var link = document.createElement("a");
        link.className = "adm-cmd-item";
        link.href = item.url || "#";

        var iconWrap = document.createElement("span");
        iconWrap.className = "adm-cmd-item-icon";
        var icon = document.createElement("i");
        icon.className = "bi " + (item.icon || iconClass || "bi-arrow-right-short");
        iconWrap.appendChild(icon);

        var body = document.createElement("span");
        body.className = "adm-cmd-item-body";
        var title = document.createElement("strong");
        title.textContent = item.name || item.title || "";
        var sub = document.createElement("small");
        sub.textContent = item.subtitle || "";
        body.appendChild(title);
        body.appendChild(sub);

        var arrow = document.createElement("i");
        arrow.className = "bi bi-return-left adm-cmd-enter";
        arrow.setAttribute("aria-hidden", "true");

        link.appendChild(iconWrap);
        link.appendChild(body);
        link.appendChild(arrow);
        group.appendChild(link);
      });
      return group;
    }

    function renderResults(payload) {
      resultsEl.textContent = "";
      activeIndex = -1;

      var groups = [
        createGroup("Boutiques", payload.shops, "bi-shop"),
        createGroup("Vendeurs & Comptes", payload.users, "bi-person"),
        createGroup("Catalogue (Produits & Services)", payload.products, "bi-box-seam"),
        createGroup("Pages Admin", payload.pages, "bi-compass"),
      ].filter(Boolean);

      if (!groups.length) {
        var empty = document.createElement("div");
        empty.className = "adm-cmd-empty";
        empty.textContent = "Aucun resultat pour cette recherche.";
        resultsEl.appendChild(empty);
        return;
      }

      groups.forEach(function (group) {
        resultsEl.appendChild(group);
      });
      setActiveLink(0);
    }

    function runSearch(query) {
      var reqId = ++lastRequestId;
      var url = searchUrl + "?q=" + encodeURIComponent(query || "");
      fetch(url, { headers: { Accept: "application/json", "X-Requested-With": "fetch" } })
        .then(function (resp) {
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          return resp.json();
        })
        .then(function (data) {
          if (reqId !== lastRequestId) return;
          renderResults(data || {});
        })
        .catch(function () {
          if (reqId !== lastRequestId) return;
          resultsEl.textContent = "";
          var err = document.createElement("div");
          err.className = "adm-cmd-empty";
          err.textContent = "Impossible de charger les raccourcis pour le moment.";
          resultsEl.appendChild(err);
        });
    }

    function openPalette() {
      overlay.hidden = false;
      overlay.classList.add("is-open");
      overlay.setAttribute("data-safe-refresh-lock", "1");
      input.focus();
      input.select();
      runSearch(input.value.trim());
    }

    function closePalette() {
      overlay.classList.remove("is-open");
      overlay.removeAttribute("data-safe-refresh-lock");
      overlay.hidden = true;
    }

    if (openBtn) {
      openBtn.addEventListener("click", openPalette);
    }
    Array.prototype.slice.call(document.querySelectorAll("[data-cmd-open]")).forEach(function (trigger) {
      if (trigger === openBtn) return;
      trigger.addEventListener("click", openPalette);
    });
    if (closeBtn) {
      closeBtn.addEventListener("click", closePalette);
    }
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay) closePalette();
    });

    input.addEventListener("input", function () {
      if (debounceTimer) window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(function () {
        runSearch(input.value.trim());
      }, 160);
    });

    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveLink(activeIndex + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveLink(activeIndex - 1);
      } else if (event.key === "Enter") {
        var links = getResultLinks();
        if (activeIndex >= 0 && links[activeIndex]) {
          event.preventDefault();
          window.location.href = links[activeIndex].href;
        }
      } else if (event.key === "Escape") {
        event.preventDefault();
        closePalette();
      }
    });

    document.addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && String(event.key || "").toLowerCase() === "k") {
        event.preventDefault();
        if (overlay.classList.contains("is-open")) {
          closePalette();
        } else {
          openPalette();
        }
      } else if (event.key === "Escape" && overlay.classList.contains("is-open")) {
        closePalette();
      }
    });
  }

  function bindPromoBulkChecks() {
    document.addEventListener("change", function (event) {
      var target = event.target;
      if (!target) return;

      if (target.matches("[data-promo-select-all]")) {
        var checks = document.querySelectorAll(".promo-bulk-check");
        checks.forEach(function (box) {
          box.checked = !!target.checked;
        });
      }

      if (target.matches("[data-promo-select-all], .promo-bulk-check")) {
        var countEl = document.getElementById("promoBulkCount");
        var allBoxes = Array.prototype.slice.call(document.querySelectorAll(".promo-bulk-check"));
        var checkedCount = allBoxes.filter(function (b) { return b.checked; }).length;
        if (countEl) {
          countEl.textContent = checkedCount + " sélectionnée(s)";
        }
        var master = document.querySelector("[data-promo-select-all]");
        if (master && allBoxes.length > 0 && target.classList.contains("promo-bulk-check")) {
          master.checked = checkedCount === allBoxes.length;
        }
      }
    });
  }

  function bootstrap() {
    bindGlobalThemeToggle();
    initCommandPalette();
    bindPromoBulkChecks();
  }

  if (document.readyState === "loading") {
    document.addEventListener("readystatechange", function onReady() {
      if (document.readyState !== "loading") {
        document.removeEventListener("readystatechange", onReady);
        bootstrap();
      }
    });
  } else {
    bootstrap();
  }
})();
