(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_LOCATIONS_PAGE_BOOTSTRAP__) return;
  window.__BM_LOCATIONS_PAGE_BOOTSTRAP__ = true;

  function initLocationsIndexPage() {
    if (window.__BM_LOCATIONS_PAGE_INIT__) return;
    window.__BM_LOCATIONS_PAGE_INIT__ = true;
    var form = document.getElementById("locationsFilterForm");
    var locationsResults = document.getElementById("locationsResults");
    if (!form || !locationsResults) return;
    var prefetchApi = window.BMIntentPrefetch || null;
    var fetchSeqFactory =
      window.BMAjaxGuard && typeof window.BMAjaxGuard.makeRequestSeq === "function"
        ? window.BMAjaxGuard.makeRequestSeq
        : function () {
            var latest = 0;
            return {
              next: function () {
                latest += 1;
                return latest;
              },
              isLatest: function (id) {
                return Number(id) === latest;
              },
            };
          };
    var swapRequestSeq = fetchSeqFactory();

    var submitTimer = null;
    var loadingHideTimer = null;
    var loadingShowTimer = null;
    var loadingVisibleSince = 0;
    var pendingAnchorTop = null;
    var pendingLockedHeight = 0;
    var isCoarsePointer = !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
    var carouselControllers = [];
    var carouselVisibilityObserver = null;

    function hardNavigate(url) {
      var targetUrl = String(url || "").trim();
      if (!targetUrl) return;
      if (window.BMPageNav && typeof window.BMPageNav.navigate === "function") {
        window.BMPageNav.navigate(targetUrl);
        return;
      }
      window.location.assign(targetUrl);
    }
    var rentalVideoObserver = null;

    if ("scrollRestoration" in history) {
      history.scrollRestoration = "manual";
    }

    function currentGrid() {
      return document.getElementById("rentalsGrid");
    }

    function currentRelativeUrl() {
      return window.location.pathname + window.location.search;
    }

    function normalizeSpaces(value) {
      return String(value || "").replace(/\s+/g, " ").trim();
    }

    function normalizeNumericText(value) {
      var cleaned = String(value || "").trim().replace(",", ".");
      if (!cleaned) return "";
      var parsed = Number.parseFloat(cleaned);
      if (!Number.isFinite(parsed) || parsed < 0) return cleaned;
      return String(parsed).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
    }

    function setInputValue(el, value) {
      if (!el) return;
      if (el.value === value) return;
      el.value = value;
    }

    function ensureLocationsSkeleton() {
      var existing = locationsResults.querySelector(".locations-skeleton");
      if (existing) return existing;
      var skeleton = document.createElement("div");
      skeleton.className = "locations-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      var html = "";
      for (var i = 0; i < 6; i += 1) {
        html +=
          '<div class="locations-skeleton-card">' +
          '<div class="locations-skeleton-media"></div>' +
          '<div class="locations-skeleton-line is-wide"></div>' +
          '<div class="locations-skeleton-line"></div>' +
          '<div class="locations-skeleton-line is-short"></div>' +
          "</div>";
      }
      skeleton.innerHTML = html;
      locationsResults.appendChild(skeleton);
      return skeleton;
    }

    function setResultsLoading(active) {
      if (loadingShowTimer) {
        window.clearTimeout(loadingShowTimer);
        loadingShowTimer = null;
      }
      if (loadingHideTimer) {
        window.clearTimeout(loadingHideTimer);
        loadingHideTimer = null;
      }
      if (active) {
        loadingVisibleSince = Date.now();
      }
      locationsResults.classList.toggle("is-loading", !!active);
      var skeleton = ensureLocationsSkeleton();
      if (skeleton && skeleton.classList) {
        skeleton.classList.toggle("show", !!active);
      }
    }

    function scheduleResultsLoading() {
      if (loadingShowTimer) {
        window.clearTimeout(loadingShowTimer);
      }
      loadingShowTimer = window.setTimeout(function () {
        loadingShowTimer = null;
        setResultsLoading(true);
      }, 140);
    }

    function hideResultsLoadingSmooth() {
      if (loadingShowTimer) {
        window.clearTimeout(loadingShowTimer);
        loadingShowTimer = null;
      }
      if (!locationsResults.classList.contains("is-loading")) {
        setResultsLoading(false);
        return;
      }
      var elapsed = loadingVisibleSince ? Date.now() - loadingVisibleSince : 0;
      var remaining = Math.max(0, 120 - elapsed);
      if (remaining > 0) {
        loadingHideTimer = window.setTimeout(function () {
          setResultsLoading(false);
        }, remaining);
        return;
      }
      setResultsLoading(false);
    }

    function lockResultsLayout() {
      if (!locationsResults || !locationsResults.style) return 0;
      var height = Math.max(0, Math.round(locationsResults.getBoundingClientRect().height || 0));
      if (height > 0) {
        locationsResults.style.minHeight = height + "px";
        locationsResults.classList.add("is-swapping");
      }
      return height;
    }

    function unlockResultsLayout() {
      if (!locationsResults || !locationsResults.style) return;
      locationsResults.style.removeProperty("min-height");
      locationsResults.classList.remove("is-swapping");
    }

    function restoreStableAnchorPosition() {
      if (!locationsResults || pendingAnchorTop == null) return;
      var nextTop = locationsResults.getBoundingClientRect().top;
      var delta = nextTop - pendingAnchorTop;
      if (Math.abs(delta) > 1) {
        window.scrollBy(0, delta);
      }
    }

    function prepareStableSwap() {
      pendingAnchorTop = locationsResults ? locationsResults.getBoundingClientRect().top : null;
      pendingLockedHeight = lockResultsLayout();
    }

    function finalizeStableSwap() {
      restoreStableAnchorPosition();
      if (pendingLockedHeight > 0) {
        window.setTimeout(function () {
          unlockResultsLayout();
          restoreStableAnchorPosition();
          pendingLockedHeight = 0;
          pendingAnchorTop = null;
        }, 120);
      } else {
        unlockResultsLayout();
        restoreStableAnchorPosition();
        pendingAnchorTop = null;
      }
    }

    function parseDh(value) {
      var parsed = Number.parseFloat(String(value || "").replace(",", "."));
      return Number.isFinite(parsed) ? Math.round(parsed * 100) : null;
    }

    function getNormalizedPriceRange() {
      var minText = normalizeNumericText(minInput ? minInput.value : "");
      var maxText = normalizeNumericText(maxInput ? maxInput.value : "");
      var min = parseDh(minText);
      var max = parseDh(maxText);

      if (min !== null && max !== null && min > max) {
        var minSwap = min;
        var minTextSwap = minText;
        min = max;
        minText = maxText;
        max = minSwap;
        maxText = minTextSwap;
      }

      return {
        min: min,
        max: max,
        minText: minText,
        maxText: maxText
      };
    }

    function commitNormalizedPriceRange() {
      var range = getNormalizedPriceRange();
      setInputValue(minInput, range.minText);
      setInputValue(maxInput, range.maxText);
      return range;
    }

    function syncQueryInputs(sourceEl) {
      var nextValue = normalizeSpaces(sourceEl ? sourceEl.value : qInput ? qInput.value : "");
      setInputValue(qInput, nextValue);
      setInputValue(heroSearchInput, nextValue);
      return nextValue;
    }

    function buildUrlFromForm(resetPage) {
      var url = new URL(window.location.href);
      var params = new URLSearchParams();
      var qValue = normalizeSpaces(qInput ? qInput.value : "");
      var cityValue = normalizeSpaces(cityInput ? cityInput.value : "");
      var typeValue = String(typeInput ? typeInput.value : "").trim();
      var propertyValue = String(propertyInput ? propertyInput.value : "").trim();
      var range = getNormalizedPriceRange();

      if (qValue) params.set("q", qValue);
      if (typeValue) params.set("type", typeValue);
      if (propertyValue) params.set("property_type", propertyValue);
      if (cityValue) params.set("city", cityValue);
      if (range.minText) params.set("min", range.minText);
      if (range.maxText) params.set("max", range.maxText);

      if (!resetPage) {
        var currentPage = url.searchParams.get("page");
        if (currentPage) params.set("page", currentPage);
      }

      var query = params.toString();
      return query ? url.pathname + "?" + query : url.pathname;
    }

    function getActiveFilterCount() {
      var range = getNormalizedPriceRange();
      var count = 0;
      if (normalizeSpaces(qInput ? qInput.value : "")) count += 1;
      if (typeInput && typeInput.value) count += 1;
      if (propertyInput && propertyInput.value) count += 1;
      if (normalizeSpaces(cityInput ? cityInput.value : "")) count += 1;
      if (range.minText) count += 1;
      if (range.maxText) count += 1;
      return count;
    }

    function updateFilterFootNote(state, visibleCount, totalCount) {
      if (!filterFootNoteText) return;
      if (state === "loading") {
        filterFootNoteText.textContent = "Mise à jour en cours…";
        return;
      }
      var activeFilters = getActiveFilterCount();
      if (typeof visibleCount === "number" && typeof totalCount === "number" && activeFilters > 0) {
        filterFootNoteText.textContent =
          visibleCount + " visible(s) maintenant · " + totalCount + " sur cette page";
        return;
      }
      if (activeFilters > 0) {
        filterFootNoteText.textContent = activeFilters + " filtre(s) actif(s) · mise à jour auto";
        return;
      }
      filterFootNoteText.textContent = "Résultats instantanés";
    }

    function syncResetButtonState() {
      if (!restoreSearchBtn) return;
      restoreSearchBtn.classList.toggle("empty-attention", getActiveFilterCount() > 0);
    }

    function getLiveEmptyState() {
      return document.getElementById("locationsLiveEmptyState");
    }

    function updateLiveResultsSummary(visibleCount, totalCount, hasFilters) {
      var countEl = locationsResults.querySelector(".results-count");
      if (!countEl) {
        updateFilterFootNote("ready", visibleCount, totalCount);
        return;
      }
      var remoteTotal = Number.parseInt(String(countEl.getAttribute("data-total-count") || ""), 10);
      if (!Number.isFinite(remoteTotal)) {
        remoteTotal = totalCount;
      }
      if (!hasFilters) {
        countEl.innerHTML = '<span class="results-dot"></span>' + remoteTotal + " offre(s) trouvee(s)";
        updateFilterFootNote("ready");
        return;
      }
      countEl.innerHTML =
        '<span class="results-dot"></span>' +
        visibleCount +
        " visible(s) sur cette page · " +
        remoteTotal +
        " total";
      updateFilterFootNote("ready", visibleCount, totalCount);
    }

    function localFilterPreview() {
      var grid = currentGrid();
      if (!grid) {
        syncResetButtonState();
        updateFilterFootNote("ready");
        return;
      }

      var cards = grid.querySelectorAll(".js-rental-card");
      var q = normalizeSpaces((qInput && qInput.value) || "").toLowerCase();
      var cityFilter = normalizeSpaces((cityInput && cityInput.value) || "").toLowerCase();
      var typeValue = typeInput ? typeInput.value : "";
      var propertyValue = propertyInput ? propertyInput.value : "";
      var range = getNormalizedPriceRange();
      var min = range.min;
      var max = range.max;
      var visibleCount = 0;
      var hasFilters = !!(
        q ||
        cityFilter ||
        typeValue ||
        propertyValue ||
        range.minText ||
        range.maxText
      );

      cards.forEach(function (card) {
        var title = String(card.getAttribute("data-title") || "");
        var city = String(card.getAttribute("data-city") || "");
        var type = String(card.getAttribute("data-type") || "");
        var property = String(card.getAttribute("data-property") || "");
        var rent = Number.parseInt(String(card.getAttribute("data-rent") || "0"), 10);

        var okQ = !q || title.indexOf(q) !== -1 || city.indexOf(q) !== -1;
        var okCity = !cityFilter || city.indexOf(cityFilter) !== -1;
        var okType = !typeValue || type === typeValue;
        var okProperty = !propertyValue || property === propertyValue;
        var okMin = min === null || rent >= min;
        var okMax = max === null || rent <= max;
        var isVisible = okQ && okCity && okType && okProperty && okMin && okMax;
        card.style.display = isVisible ? "" : "none";
        if (isVisible) visibleCount += 1;
      });

      var liveEmptyState = getLiveEmptyState();
      if (liveEmptyState) {
        liveEmptyState.classList.toggle("d-none", visibleCount !== 0 || !cards.length);
      }
      updateLiveResultsSummary(visibleCount, cards.length, hasFilters);
      syncResetButtonState();
    }

    function initCarousels(scope) {
      if ("IntersectionObserver" in window && !carouselVisibilityObserver) {
        carouselVisibilityObserver = new IntersectionObserver(function (entries) {
          entries.forEach(function (entry) {
            var carousel = entry.target;
            if (!carousel) return;
            carousel.dataset.inView = entry.isIntersecting ? "1" : "0";
            var controller = carousel.__bmCarouselController;
            if (!controller) return;
            if (entry.isIntersecting) {
              controller.restartAuto();
            } else {
              controller.clearAuto();
            }
          });
        }, { rootMargin: "120px 0px", threshold: 0.2 });
      }

      (scope || document).querySelectorAll(".js-card-carousel").forEach(function (carousel) {
        if (carousel.dataset.carouselInit === "1") return;
        carousel.dataset.carouselInit = "1";
        carousel.dataset.inView = "1";

        var track = carousel.querySelector(".rental-track");
        if (!track) return;
        var slides = track.children;
        if (!slides || slides.length <= 1) return;

        var prev = carousel.querySelector(".js-prev");
        var next = carousel.querySelector(".js-next");
        var dots = carousel.querySelectorAll(".slide-dot");
        var index = 0;
        var timer = null;
        var touchStartX = 0;
        var touchEndX = 0;

        function clearAuto() {
          if (!timer) return;
          window.clearInterval(timer);
          timer = null;
        }

        function render() {
          if (!track.isConnected) {
            clearAuto();
            return;
          }
          track.style.transform = "translateX(-" + index * 100 + "%)";
          dots.forEach(function (dot, idx) {
            dot.classList.toggle("active", idx === index);
          });
        }

        function go(step) {
          if (!track.isConnected) {
            clearAuto();
            return;
          }
          index += step;
          if (index >= slides.length) index = 0;
          if (index < 0) index = slides.length - 1;
          render();
        }

        function restartAuto() {
          clearAuto();
          if (document.hidden) return;
          if (carousel.dataset.inView === "0") return;
          timer = window.setInterval(function () {
            go(1);
          }, isCoarsePointer ? 4600 : 3800);
        }

        if (prev) {
          prev.addEventListener("click", function () {
            go(-1);
            restartAuto();
          });
        }
        if (next) {
          next.addEventListener("click", function () {
            go(1);
            restartAuto();
          });
        }

        carousel.addEventListener(
          "touchstart",
          function (event) {
            touchStartX = event.changedTouches[0].screenX;
          },
          { passive: true }
        );

        carousel.addEventListener(
          "touchend",
          function (event) {
            touchEndX = event.changedTouches[0].screenX;
            var delta = touchEndX - touchStartX;
            if (Math.abs(delta) > 35) {
              if (delta < 0) go(1);
              else go(-1);
              restartAuto();
            }
          },
          { passive: true }
        );

        carousel.addEventListener("mouseenter", clearAuto);
        carousel.addEventListener("mouseleave", restartAuto);

        var controller = {
          clearAuto: clearAuto,
          restartAuto: restartAuto,
          carousel: carousel
        };
        carousel.__bmCarouselController = controller;
        carouselControllers.push(controller);
        if (carouselVisibilityObserver) {
          carouselVisibilityObserver.observe(carousel);
        }

        render();
        restartAuto();
      });
    }

    function initLazyRentalVideos(scope) {
      var root = scope || document;
      var videos = root.querySelectorAll(".js-lazy-rental-video");
      if (!videos.length) return;

      if ("IntersectionObserver" in window && !rentalVideoObserver) {
        rentalVideoObserver = new IntersectionObserver(
          function (entries) {
            entries.forEach(function (entry) {
              var video = entry.target;
              if (!video) return;
              if (entry.isIntersecting && entry.intersectionRatio >= 0.2) {
                hydrate(video);
                playIfPossible(video);
                return;
              }
              try {
                video.pause();
              } catch (_error) {}
            });
          },
          { rootMargin: "160px 0px", threshold: [0, 0.2, 0.6] }
        );
      }

      function hydrate(video) {
        if (!video || video.dataset.videoLoaded === "1") return;
        var source = video.querySelector("source");
        var src = video.getAttribute("data-video-src") || (source ? source.getAttribute("data-src") : "");
        if (!src) return;
        if (source && !source.getAttribute("src")) {
          source.setAttribute("src", src);
        }
        video.dataset.videoLoaded = "1";
        video.load();
      }

      function playIfPossible(video) {
        if (!video) return;
        var promise = video.play();
        if (promise && typeof promise.catch === "function") {
          promise.catch(function () {});
        }
      }

      if (!("IntersectionObserver" in window)) {
        videos.forEach(function (video) {
          hydrate(video);
          playIfPossible(video);
        });
        return;
      }

      videos.forEach(function (video) {
        if (video.dataset.videoObserved === "1") return;
        video.dataset.videoObserved = "1";
        rentalVideoObserver.observe(video);
      });
    }

    function fetchAndSwap(url, pushState, triggerEl) {
      if (submitTimer) window.clearTimeout(submitTimer);
      var requestId = swapRequestSeq.next();
      prepareStableSwap();
      scheduleResultsLoading();
      if (window.AjaxPagination && typeof window.AjaxPagination.navigate === "function") {
        window.AjaxPagination.navigate(url, {
          push: pushState !== false,
          scrollMode: "preserve",
          triggerEl: triggerEl || null
        });
        loadingHideTimer = window.setTimeout(function () {
          if (swapRequestSeq.isLatest(requestId)) {
            setResultsLoading(false);
          }
        }, 5500);
        return;
      }
      setResultsLoading(false);
      hardNavigate(url);
    }

    var qInput = form.querySelector('input[name="q"]');
    var heroSearchInput = document.getElementById("heroSearchInput");
    var cityInput = form.querySelector('input[name="city"]');
    var typeInput = form.querySelector('select[name="type"]');
    var propertyInput = form.querySelector('select[name="property_type"]');
    var minInput = form.querySelector('input[name="min"]');
    var maxInput = form.querySelector('input[name="max"]');
    var restoreSearchBtn = document.getElementById("restoreSearchBtn");
    var filterFootNoteText = document.getElementById("filterFootNoteText");
    var liveInputDelay = isCoarsePointer ? 260 : 220;

    function scheduleFetch(resetPage, triggerEl, options) {
      var opts = options || {};
      if (submitTimer) window.clearTimeout(submitTimer);
      if (opts.commitRange) {
        commitNormalizedPriceRange();
      }
      var targetUrl = buildUrlFromForm(resetPage);
      if (targetUrl === currentRelativeUrl()) {
        form.classList.remove("is-optimistic");
        updateFilterFootNote("ready");
        syncResetButtonState();
        return;
      }
      form.classList.add("is-optimistic");
      updateFilterFootNote("loading");
      submitTimer = window.setTimeout(function () {
        fetchAndSwap(targetUrl, true, triggerEl || null);
      }, typeof opts.delayMs === "number" ? opts.delayMs : liveInputDelay);
    }

    function buildProbableFilterUrl() {
      if (!typeInput) return "";
      var nextType = "";
      if (typeInput.value === "monthly") {
        nextType = "daily";
      } else {
        nextType = "monthly";
      }
      var currentUrl = new URL(buildUrlFromForm(true), window.location.origin);
      if (nextType) currentUrl.searchParams.set("type", nextType);
      currentUrl.searchParams.delete("page");
      return currentUrl.pathname + (currentUrl.search || "");
    }

    function collectPrefetchUrls() {
      var urls = [];
      var nextPageLink = document.querySelector("#locationsPagination a.next-link[href]");
      if (nextPageLink) {
        urls.push(nextPageLink.getAttribute("href"));
      }
      var probableFilterUrl = buildProbableFilterUrl();
      if (probableFilterUrl) {
        urls.push(probableFilterUrl);
      }
      return urls;
    }

    function warmupPrefetch() {
      if (!prefetchApi) return;
      if (typeof prefetchApi.prefetchOnIntent === "function") {
        prefetchApi.prefetchOnIntent(
          document,
          "#locationsPagination a.next-link[href], .hero-return-link[href]",
          { headers: { Accept: "text/html" } }
        );
      }
      if (typeof prefetchApi.prefetchIdle === "function") {
        prefetchApi.prefetchIdle(collectPrefetchUrls(), {
          headers: { Accept: "text/html" },
          timeoutMs: 1200,
        });
      }
    }

    syncQueryInputs(qInput || heroSearchInput);

    [qInput, heroSearchInput, cityInput, minInput, maxInput].forEach(function (el) {
      if (!el) return;
      var isQueryInput = el === qInput || el === heroSearchInput;
      var isRangeInput = el === minInput || el === maxInput;
      el.addEventListener("input", function () {
        if (isQueryInput) {
          syncQueryInputs(el);
        }
        localFilterPreview();
        scheduleFetch(true, el);
      });
      el.addEventListener("blur", function () {
        if (isQueryInput) {
          syncQueryInputs(el);
        }
        if (isRangeInput) {
          commitNormalizedPriceRange();
        }
        localFilterPreview();
        scheduleFetch(true, el, { delayMs: 0, commitRange: isRangeInput });
      });
      el.addEventListener("keydown", function (event) {
        if (event.key !== "Enter") return;
        event.preventDefault();
        if (isQueryInput) {
          syncQueryInputs(el);
        }
        if (isRangeInput) {
          commitNormalizedPriceRange();
        }
        localFilterPreview();
        scheduleFetch(true, el, { delayMs: 0, commitRange: isRangeInput });
      });
    });

    [typeInput, propertyInput].forEach(function (el) {
      if (!el) return;
      el.addEventListener("change", function () {
        localFilterPreview();
        scheduleFetch(true, el, { delayMs: 90 });
      });
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (submitTimer) window.clearTimeout(submitTimer);
      syncQueryInputs(qInput || heroSearchInput);
      commitNormalizedPriceRange();
      localFilterPreview();
      form.classList.add("is-optimistic");
      updateFilterFootNote("loading");
      fetchAndSwap(buildUrlFromForm(true), true, event.submitter || form);
    });

    if (restoreSearchBtn) {
      restoreSearchBtn.addEventListener("click", function () {
        if (qInput) qInput.value = "";
        if (heroSearchInput) heroSearchInput.value = "";
        if (cityInput) cityInput.value = "";
        if (typeInput) typeInput.value = "";
        if (propertyInput) propertyInput.value = "";
        if (minInput) minInput.value = "";
        if (maxInput) maxInput.value = "";
        localFilterPreview();
        form.classList.add("is-optimistic");
        updateFilterFootNote("loading");
        fetchAndSwap(buildUrlFromForm(true), true, restoreSearchBtn);
      });
    }

    initCarousels(document);
    initLazyRentalVideos(document);
    localFilterPreview();
    document.addEventListener("ajax:page-replaced", function () {
      hideResultsLoadingSmooth();
      form.classList.remove("is-optimistic");
      finalizeStableSwap();
      syncQueryInputs(qInput || heroSearchInput);
      initCarousels(locationsResults);
      initLazyRentalVideos(locationsResults);
      localFilterPreview();
      warmupPrefetch();
    });
    window.addEventListener("pageshow", function () {
      hideResultsLoadingSmooth();
      form.classList.remove("is-optimistic");
      finalizeStableSwap();
      syncQueryInputs(qInput || heroSearchInput);
      localFilterPreview();
    });
    document.addEventListener("click", function (event) {
      var link = event.target.closest("#locationsPagination a.page-link[href]");
      if (!link) return;
      prepareStableSwap();
    }, true);
    document.addEventListener("visibilitychange", function () {
      carouselControllers = carouselControllers.filter(function (controller) {
        return !!(controller && controller.carousel && controller.carousel.isConnected);
      });
      carouselControllers.forEach(function (controller) {
        if (!controller) return;
        if (document.hidden) {
          controller.clearAuto();
          return;
        }
        controller.restartAuto();
      });
      document.querySelectorAll(".js-lazy-rental-video").forEach(function (video) {
        if (document.hidden) {
          try {
            video.pause();
          } catch (_error) {}
        }
      });
    });
    warmupPrefetch();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLocationsIndexPage, { once: true });
    return;
  }

  initLocationsIndexPage();
})();

