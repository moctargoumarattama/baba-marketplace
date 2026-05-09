(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_ADMIN_LOCATIONS_INIT__) return;
  window.__BM_ADMIN_LOCATIONS_INIT__ = true;
  var makeRequestSeq =
    window.BMCoreDom && typeof window.BMCoreDom.makeRequestSeq === "function"
      ? window.BMCoreDom.makeRequestSeq
      : window.BMAjaxGuard.makeRequestSeq.bind(window.BMAjaxGuard);
  var requestText =
    window.BMCoreDom && typeof window.BMCoreDom.requestText === "function"
      ? window.BMCoreDom.requestText
      : window.BMAjaxFetch.requestText.bind(window.BMAjaxFetch);

  function restoreY(y) {
    var target = Math.max(Number(y || 0), 0);
    if (window.AdminHelpers && typeof window.AdminHelpers.restoreInstantScroll === "function") {
      window.AdminHelpers.restoreInstantScroll(target);
      return;
    }
    requestAnimationFrame(function () {
      try {
        window.scrollTo({ top: target, left: 0, behavior: "instant" });
      } catch (_err) {
        window.scrollTo(0, target);
      }
    });
  }

  function initAdminLocationsPage() {
    var pvNode = document.getElementById("pv");
    if (!pvNode) return;

    var pv = {};
    try {
      pv = JSON.parse(pvNode.textContent || "{}");
    } catch (_err) {
      pv = {};
    }

    var baseUrl = String(pv.base_url || "").trim();
    if (!baseUrl) return;

    if (document.body && document.body.dataset) {
      document.body.dataset.admLocationsInit = "1";
    }

    var state = {
      q: String(pv.q || ""),
      status: String(pv.status || ""),
      owner: String(pv.owner_id || ""),
      range: String(pv.range || "month"),
      dateFrom: String(pv.date_from || ""),
      dateTo: String(pv.date_to || ""),
      lpage: Number.parseInt(String(pv.lpage || "1"), 10) || 1,
      apage: Number.parseInt(String(pv.apage || "1"), 10) || 1,
    };

    var fq = document.getElementById("fq");
    var fstatus = document.getElementById("fstatus");
    var fowner = document.getElementById("fowner");
    var frange = document.getElementById("frange");
    var ffrom = document.getElementById("ffrom");
    var fto = document.getElementById("fto");
    var btnReset = document.getElementById("btnReset");
    var searchInd = document.getElementById("searchInd");

    var listingsMask = document.getElementById("listingsMask");
    var archivesMask = document.getElementById("archivesMask");
    var listingsTbody = document.getElementById("listingsTbody");
    var archivesTbody = document.getElementById("archivesTbody");
    var listingsPg = document.getElementById("listingsPg");
    var archivesPg = document.getElementById("archivesPg");
    var listingsSub = document.getElementById("listingsSub");
    var archivesSub = document.getElementById("archivesSub");
    var locationsStats = document.getElementById("locationsStats");

    if (!listingsTbody || !archivesTbody || !listingsPg || !archivesPg) return;

    var seq = makeRequestSeq();
    var activeController = null;
    var debounceTimer = null;

    function setMasks(listingsOn, archivesOn) {
      if (listingsMask) listingsMask.classList.toggle("on", !!listingsOn);
      if (archivesMask) archivesMask.classList.toggle("on", !!archivesOn);
    }

    function setSearchIndicator(on) {
      if (!searchInd) return;
      searchInd.classList.toggle("on", !!on);
    }

    function buildURL(lp, ap, options) {
      var cfg = options || {};
      var section = String(cfg.section || "").trim();
      var params = new URLSearchParams();
      if (state.q) params.set("q", state.q);
      if (state.status) params.set("status", state.status);
      if (state.owner) params.set("owner_id", state.owner);
      if (state.range) params.set("range", state.range);
      if (state.dateFrom) params.set("date_from", state.dateFrom);
      if (state.dateTo) params.set("date_to", state.dateTo);
      params.set("page", String(lp || state.lpage || 1));
      params.set("apage", String(ap || state.apage || 1));
      if (section) params.set("section", section);
      if (cfg.includeStats) params.set("stats", "1");
      return baseUrl + "?" + params.toString();
    }

    function hardNavigate(lp, ap) {
      window.location.href = buildURL(lp, ap);
    }

    function bindPagination() {
      document.querySelectorAll("[data-lpage]").forEach(function (el) {
        if (el.dataset.bound === "1") return;
        el.dataset.bound = "1";
        el.addEventListener("click", function (event) {
          event.preventDefault();
          var page = Number.parseInt(String(el.dataset.lpage || "1"), 10) || 1;
          loadListings(page);
        });
      });

      document.querySelectorAll("[data-apage]").forEach(function (el) {
        if (el.dataset.bound === "1") return;
        el.dataset.bound = "1";
        el.addEventListener("click", function (event) {
          event.preventDefault();
          var page = Number.parseInt(String(el.dataset.apage || "1"), 10) || 1;
          loadArchives(page);
        });
      });
    }

    async function fetchHtml(lp, ap, options) {
      if (activeController && typeof activeController.abort === "function") {
        try {
          activeController.abort();
        } catch (_err) {}
      }
      activeController = typeof AbortController !== "undefined" ? new AbortController() : null;

      var requestId = seq.next();
      var response = await requestText(buildURL(lp, ap, options), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: activeController ? activeController.signal : undefined,
      });

      if (!seq.isLatest(requestId)) {
        return { stale: true, requestId: requestId };
      }
      return { stale: false, requestId: requestId, response: response };
    }

    function applyDoc(doc, options) {
      var cfg = options || {};
      var includeListings = !!cfg.includeListings;
      var includeArchives = !!cfg.includeArchives;
      var nextStats = doc.getElementById("locationsStats");
      if (locationsStats && nextStats) {
        locationsStats.innerHTML = nextStats.innerHTML;
      }

      if (includeListings) {
        var nextListingsBody = doc.getElementById("listingsTbody");
        var nextListingsPager = doc.getElementById("listingsPg");
        var nextListingsSub = doc.getElementById("listingsSub");
        if (!nextListingsBody || !nextListingsPager) return false;
        listingsTbody.innerHTML = nextListingsBody.innerHTML;
        listingsTbody.classList.add("fade-in");
        window.setTimeout(function () {
          listingsTbody.classList.remove("fade-in");
        }, 200);
        listingsPg.innerHTML = nextListingsPager.innerHTML;
        if (listingsSub && nextListingsSub) listingsSub.textContent = nextListingsSub.textContent;
      }

      if (includeArchives) {
        var nextArchivesBody = doc.getElementById("archivesTbody");
        var nextArchivesPager = doc.getElementById("archivesPg");
        var nextArchivesSub = doc.getElementById("archivesSub");
        if (!nextArchivesBody || !nextArchivesPager) return false;
        archivesTbody.innerHTML = nextArchivesBody.innerHTML;
        archivesTbody.classList.add("fade-in");
        window.setTimeout(function () {
          archivesTbody.classList.remove("fade-in");
        }, 200);
        archivesPg.innerHTML = nextArchivesPager.innerHTML;
        if (archivesSub && nextArchivesSub) archivesSub.textContent = nextArchivesSub.textContent;
      }

      bindPagination();
      return true;
    }

    async function loadListings(page) {
      var keepY = window.scrollY || 0;
      state.lpage = Number.parseInt(String(page || "1"), 10) || 1;
      setMasks(true, false);

      try {
        var payload = await fetchHtml(state.lpage, state.apage, { section: "listings" });
        if (payload.stale) return;
        var response = payload.response;
        if (!response || !response.ok) {
          if (!response || !response.aborted) hardNavigate(state.lpage, state.apage);
          return;
        }
        var doc = new DOMParser().parseFromString(String(response.data || ""), "text/html");
        if (!applyDoc(doc, { includeListings: true, includeArchives: false })) {
          hardNavigate(state.lpage, state.apage);
          return;
        }
        try {
          window.history.replaceState(null, "", buildURL(state.lpage, state.apage));
        } catch (_err) {}
        restoreY(keepY);
      } catch (_err) {
        hardNavigate(state.lpage, state.apage);
      } finally {
        setMasks(false, false);
      }
    }

    async function loadArchives(page) {
      var keepY = window.scrollY || 0;
      state.apage = Number.parseInt(String(page || "1"), 10) || 1;
      setMasks(false, true);

      try {
        var payload = await fetchHtml(state.lpage, state.apage, { section: "archives" });
        if (payload.stale) return;
        var response = payload.response;
        if (!response || !response.ok) {
          if (!response || !response.aborted) hardNavigate(state.lpage, state.apage);
          return;
        }
        var doc = new DOMParser().parseFromString(String(response.data || ""), "text/html");
        if (!applyDoc(doc, { includeListings: false, includeArchives: true })) {
          hardNavigate(state.lpage, state.apage);
          return;
        }
        try {
          window.history.replaceState(null, "", buildURL(state.lpage, state.apage));
        } catch (_err) {}
        restoreY(keepY);
      } catch (_err) {
        hardNavigate(state.lpage, state.apage);
      } finally {
        setMasks(false, false);
      }
    }

    async function loadBoth(lp, ap) {
      var keepY = window.scrollY || 0;
      state.lpage = Number.parseInt(String(lp || "1"), 10) || 1;
      state.apage = Number.parseInt(String(ap || "1"), 10) || 1;
      setMasks(true, true);

      try {
        var payload = await fetchHtml(state.lpage, state.apage, { section: "both", includeStats: true });
        if (payload.stale) return;
        var response = payload.response;
        if (!response || !response.ok) {
          if (!response || !response.aborted) hardNavigate(state.lpage, state.apage);
          return;
        }
        var doc = new DOMParser().parseFromString(String(response.data || ""), "text/html");
        if (!applyDoc(doc, { includeListings: true, includeArchives: true })) {
          hardNavigate(state.lpage, state.apage);
          return;
        }
        try {
          window.history.replaceState(null, "", buildURL(state.lpage, state.apage));
        } catch (_err) {}
        restoreY(keepY);
      } catch (_err) {
        hardNavigate(state.lpage, state.apage);
      } finally {
        setMasks(false, false);
      }
    }

    function applyFilters() {
      state.q = fq ? String(fq.value || "").trim() : "";
      state.status = fstatus ? String(fstatus.value || "") : "";
      state.owner = fowner ? String(fowner.value || "") : "";
      state.range = frange ? String(frange.value || "month") : "month";
      state.dateFrom = ffrom ? String(ffrom.value || "") : "";
      state.dateTo = fto ? String(fto.value || "") : "";
      state.lpage = 1;
      state.apage = 1;
      setSearchIndicator(false);
      loadBoth(1, 1);
    }

    if (fq) {
      fq.addEventListener("input", function () {
        setSearchIndicator(true);
        if (debounceTimer) window.clearTimeout(debounceTimer);
        debounceTimer = window.setTimeout(applyFilters, 700);
      });
      fq.addEventListener("keydown", function (event) {
        if (event.key !== "Enter") return;
        event.preventDefault();
        if (debounceTimer) window.clearTimeout(debounceTimer);
        applyFilters();
      });
    }

    if (fstatus) {
      fstatus.addEventListener("change", function () {
        if (debounceTimer) window.clearTimeout(debounceTimer);
        applyFilters();
      });
    }

    if (fowner) {
      fowner.addEventListener("change", function () {
        if (debounceTimer) window.clearTimeout(debounceTimer);
        applyFilters();
      });
    }

    if (frange) {
      frange.addEventListener("change", function () {
        if (debounceTimer) window.clearTimeout(debounceTimer);
        applyFilters();
      });
    }

    if (ffrom) {
      ffrom.addEventListener("change", function () {
        if (debounceTimer) window.clearTimeout(debounceTimer);
        applyFilters();
      });
    }

    if (fto) {
      fto.addEventListener("change", function () {
        if (debounceTimer) window.clearTimeout(debounceTimer);
        applyFilters();
      });
    }

    if (btnReset) {
      btnReset.addEventListener("click", function () {
        if (fq) fq.value = "";
        if (fstatus) fstatus.value = "";
        if (fowner) fowner.value = "";
        if (frange) frange.value = "month";
        if (ffrom) ffrom.value = "";
        if (fto) fto.value = "";
        if (debounceTimer) window.clearTimeout(debounceTimer);
        applyFilters();
      });
    }

    bindPagination();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAdminLocationsPage, { once: true });
    return;
  }

  initAdminLocationsPage();
})();

