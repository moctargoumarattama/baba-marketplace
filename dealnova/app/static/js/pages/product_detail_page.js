(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_PRODUCT_DETAIL_INIT__) return;
  window.__BM_PRODUCT_DETAIL_INIT__ = true;

  let suppressZoomUntil = 0;

  function createRequestSeq() {
    if (window.BMAjaxGuard && typeof window.BMAjaxGuard.makeRequestSeq === "function") {
      return window.BMAjaxGuard.makeRequestSeq();
    }
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
  }

  const formSeqMap = new WeakMap();
  const formControllerMap = new WeakMap();
  const bmFetchApi = window.BMAjaxFetch || null;
  const bmCsrfApi = window.BMAjaxCSRF || window.BMAjaxCsrf || null;

  function bmAddCsrfHeaders(headers, formEl) {
    const baseHeaders = Object.assign({}, headers || {});
    if (bmCsrfApi && typeof bmCsrfApi.addToHeaders === "function") {
      return bmCsrfApi.addToHeaders(baseHeaders, formEl || null);
    }

    if (!baseHeaders["X-CSRFToken"] && !baseHeaders["x-csrftoken"]) {
      const meta = document.querySelector('meta[name="csrf-token"]');
      const token = meta && meta.content ? String(meta.content) : "";
      if (token) {
        baseHeaders["X-CSRFToken"] = token;
      }
    }
    return baseHeaders;
  }

  async function bmFetchJSON(url, options) {
    if (bmFetchApi && typeof bmFetchApi.requestJSON === "function") {
      return bmFetchApi.requestJSON(url, options || {});
    }

    const opts = options || {};
    try {
      const response = await fetch(url, opts);
      let data = {};
      try {
        data = await response.json();
      } catch (_error) {
        data = {};
      }
      return {
        ok: response.ok,
        status: Number(response.status || 0),
        data: data,
        error: response.ok ? null : String(response.statusText || ("HTTP " + String(response.status || 0))),
        aborted: false,
        timedOut: false,
      };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        data: {},
        error: String((error && error.message) || "network_error"),
        aborted: !!(error && error.name === "AbortError"),
        timedOut: false,
      };
    }
  }

  function showAlert(message) {
    if (window.BMCoreUI && typeof window.BMCoreUI.showAlert === "function") {
      window.BMCoreUI.showAlert(message, "error");
      return;
    }
    window.alert(message);
  }

  function showToast(message) {
    if (window.BMCoreUI && typeof window.BMCoreUI.showToast === "function") {
      window.BMCoreUI.showToast(message, "success");
      return;
    }
    try {
      window.alert(message);
    } catch (_error) {}
  }

  function updateMainImageFitMode() {
    const mainImage = document.getElementById("mainImage");
    const wrap = document.querySelector(".main-image-wrap");
    if (!mainImage || !wrap || !mainImage.naturalWidth || !mainImage.naturalHeight) return;
    const ratio = mainImage.naturalWidth / mainImage.naturalHeight;
    wrap.classList.remove("is-portrait", "is-landscape");
    if (ratio < 0.86) {
      wrap.classList.add("is-portrait");
    } else if (ratio > 1.2) {
      wrap.classList.add("is-landscape");
    }
  }

  function applyRelatedImageFitModes() {
    const relatedImages = Array.from(document.querySelectorAll(".related-media-img"));
    relatedImages.forEach(function (img) {
      const frame = img.closest(".related-media-frame");
      if (!frame) return;

      const classify = function () {
        if (!img.naturalWidth || !img.naturalHeight) return;
        const ratio = img.naturalWidth / img.naturalHeight;
        frame.classList.remove("is-portrait", "is-landscape");
        if (ratio < 0.86) {
          frame.classList.add("is-portrait");
        } else if (ratio > 1.2) {
          frame.classList.add("is-landscape");
        }
      };

      if (img.complete) {
        classify();
      } else {
        img.addEventListener("load", classify, { once: true });
      }
    });
  }

  function changeImage(src, element) {
    const mainImage = document.getElementById("mainImage");
    if (!mainImage) return;
    mainImage.src = src;

    document.querySelectorAll('[data-role="thumb-switch"]').forEach(function (thumb) {
      thumb.classList.remove("active");
    });

    if (element) {
      element.classList.add("active");
    }
  }

  function bindGallery() {
    const galleryThumbs = Array.from(document.querySelectorAll('[data-role="thumb-switch"]'));
    const galleryNavButtons = Array.from(document.querySelectorAll("[data-gallery-nav]"));
    const galleryWrap = document.querySelector(".main-image-wrap");

    function findActiveThumbIndex() {
      if (!galleryThumbs.length) return -1;
      return galleryThumbs.findIndex(function (thumb) {
        return thumb.classList.contains("active");
      });
    }

    function goToRelativeImage(step) {
      if (!galleryThumbs.length) return;
      const current = findActiveThumbIndex();
      const safeCurrent = current >= 0 ? current : 0;
      const target = (safeCurrent + step + galleryThumbs.length) % galleryThumbs.length;
      const thumb = galleryThumbs[target];
      if (!thumb) return;
      changeImage(thumb.dataset.large || thumb.src, thumb);
    }

    galleryThumbs.forEach(function (thumb) {
      if (thumb.dataset.galleryBound === "1") return;
      thumb.dataset.galleryBound = "1";
      thumb.addEventListener("click", function () {
        changeImage(thumb.dataset.large || thumb.src, thumb);
      });
    });

    galleryNavButtons.forEach(function (btn) {
      if (btn.dataset.galleryBound === "1") return;
      btn.dataset.galleryBound = "1";
      btn.addEventListener("click", function () {
        const direction = btn.dataset.galleryNav === "prev" ? -1 : 1;
        goToRelativeImage(direction);
      });
    });

    if (!galleryWrap || galleryThumbs.length <= 1 || galleryWrap.dataset.gallerySwipeBound === "1") return;
    galleryWrap.dataset.gallerySwipeBound = "1";
    galleryWrap.classList.add("gallery-swipe-enabled");

    let startX = 0;
    let startY = 0;
    let endX = 0;
    let endY = 0;
    let touching = false;

    const SWIPE_MIN_X = 36;
    const SWIPE_MAX_Y = 56;

    function resetTouch() {
      touching = false;
      startX = 0;
      startY = 0;
      endX = 0;
      endY = 0;
    }

    galleryWrap.addEventListener(
      "touchstart",
      function (event) {
        if (!event.touches || event.touches.length !== 1) return;
        const t = event.touches[0];
        startX = t.clientX;
        startY = t.clientY;
        endX = t.clientX;
        endY = t.clientY;
        touching = true;
      },
      { passive: true }
    );

    galleryWrap.addEventListener(
      "touchmove",
      function (event) {
        if (!touching || !event.touches || event.touches.length !== 1) return;
        const t = event.touches[0];
        endX = t.clientX;
        endY = t.clientY;
      },
      { passive: true }
    );

    galleryWrap.addEventListener(
      "touchend",
      function () {
        if (!touching) return;
        const dx = endX - startX;
        const dy = endY - startY;
        if (Math.abs(dx) >= SWIPE_MIN_X && Math.abs(dy) <= SWIPE_MAX_Y) {
          goToRelativeImage(dx < 0 ? 1 : -1);
          suppressZoomUntil = Date.now() + 420;
        }
        resetTouch();
      },
      { passive: true }
    );

    galleryWrap.addEventListener("touchcancel", resetTouch, { passive: true });
  }

  function updateBadges(count) {
    const safeCount = Math.max(0, Number(count || 0));
    document.querySelectorAll("[data-cart-badge], [data-drawer-cart-badge]").forEach(function (el) {
      el.textContent = String(safeCount);
      el.classList.toggle("d-none", safeCount <= 0);
    });
  }

  function bindSmoothAddToCart() {
    const forms = Array.from(document.querySelectorAll('form[data-action="add-to-cart"][data-ajax="true"]'));
    if (!forms.length) return;

    forms.forEach(function (form) {
      if (form.dataset.localAjaxBound === "1") return;
      form.dataset.localAjaxBound = "1";

      if (!formSeqMap.has(form)) {
        formSeqMap.set(form, createRequestSeq());
      }

      form.addEventListener(
        "submit",
        function (event) {
          event.preventDefault();
          event.stopPropagation();

          const submitBtn = form.querySelector('button[type="submit"]');
          if (submitBtn && submitBtn.disabled) return;

          const seq = formSeqMap.get(form);
          const reqId = seq.next();

          const previousController = formControllerMap.get(form);
          if (previousController) {
            try {
              previousController.abort();
            } catch (_error) {}
          }

          const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
          formControllerMap.set(form, controller);

          if (submitBtn) {
            submitBtn.disabled = true;
          }

          const formData = new FormData(form);
          bmFetchJSON(form.action, {
            method: form.method || "POST",
            body: formData,
            headers: bmAddCsrfHeaders(
              {
                "X-Requested-With": "fetch",
                Accept: "application/json",
              },
              form
            ),
            credentials: "same-origin",
            signal: controller ? controller.signal : undefined,
            timeoutMs: 18000,
          })
            .then(function (result) {
              if (!seq.isLatest(reqId)) return;
              if (!result || result.aborted || result.timedOut) return;

              const data = result.data && typeof result.data === "object" ? result.data : {};
              if (!result.ok || data.success === false) {
                const message = data.message || "Erreur lors de l'ajout au panier.";
                showAlert(message);
                return;
              }

              if (Object.prototype.hasOwnProperty.call(data, "cart_count")) {
                updateBadges(data.cart_count);
              }
              document.dispatchEvent(
                new CustomEvent("cart:changed", {
                  detail: { source: "product_detail", cartCount: data.cart_count ?? null },
                })
              );

              showToast(data.message || form.dataset.successMessage || "Produit ajoute au panier");
            })
            .catch(function () {
              if (!seq.isLatest(reqId)) return;
              showAlert("Erreur reseau. Reessayez.");
            })
            .finally(function () {
              if (!seq.isLatest(reqId)) return;
              if (submitBtn) {
                submitBtn.disabled = false;
              }
              if (formControllerMap.get(form) === controller) {
                formControllerMap.delete(form);
              }
            });
        },
        true
      );
    });
  }

  function bindImageZoom() {
    const mainImage = document.getElementById("mainImage");
    if (!mainImage) return;

    if (mainImage.complete) {
      updateMainImageFitMode();
    }
    mainImage.addEventListener("load", updateMainImageFitMode);

    if (mainImage.dataset.zoomBound === "1") return;
    mainImage.dataset.zoomBound = "1";

    mainImage.addEventListener("click", function () {
      if (Date.now() < suppressZoomUntil) return;
      const src = mainImage.src;
      const modal = document.createElement("div");
      modal.style.cssText =
        "position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.9); display: flex; align-items: center; justify-content: center; z-index: 9999; cursor: zoom-out;";

      const img = document.createElement("img");
      img.src = src;
      img.style.cssText = "max-width: 90%; max-height: 90%; object-fit: contain;";

      modal.appendChild(img);
      modal.addEventListener("click", function () {
        modal.remove();
        document.body.style.overflow = "auto";
      });

      document.body.appendChild(modal);
      document.body.style.overflow = "hidden";
    });
  }

  function bindProductVideoPreview() {
    const video = document.getElementById("productMainVideo");
    const fallback = document.getElementById("productVideoFallback");
    if (!video || video.dataset.previewBound === "1") return;
    video.dataset.previewBound = "1";
    let previewPrimed = false;

    function hideFallback() {
      if (!fallback) return;
      fallback.hidden = true;
    }

    function showFallback() {
      if (!fallback) return;
      fallback.hidden = false;
    }

    function showFirstFrame() {
      try {
        if (previewPrimed) return;
        if (video.readyState >= 2 && Number(video.duration || 0) > 0.2) {
          if (video.currentTime <= 0) {
            video.currentTime = 0.01;
          }
          previewPrimed = true;
          hideFallback();
        }
      } catch (_error) {}
    }

    function tryWarmPreview() {
      try {
        if (previewPrimed || video.readyState < 2) return;
        const wasMuted = !!video.muted;
        video.muted = true;
        const playPromise = video.play();
        if (playPromise && typeof playPromise.then === "function") {
          playPromise.then(function () {
            window.setTimeout(function () {
              try {
                video.pause();
                if (video.currentTime <= 0) {
                  video.currentTime = 0.01;
                }
                previewPrimed = true;
                hideFallback();
              } catch (_error) {}
              video.muted = wasMuted;
            }, 90);
          }).catch(function () {
            video.muted = wasMuted;
          });
          return;
        }
        video.muted = wasMuted;
      } catch (_error) {}
    }

    video.addEventListener("loadedmetadata", showFirstFrame);
    video.addEventListener("canplay", showFirstFrame);
    video.addEventListener("loadeddata", showFirstFrame);
    video.addEventListener("error", function () {
      const currentSrc = String(video.currentSrc || video.getAttribute("src") || "");
      if (!currentSrc || video.dataset.videoReloaded === "1") return;
      const cleanSrc = currentSrc.replace(/#t=.*$/, "");
      if (!cleanSrc || cleanSrc === currentSrc) {
        showFallback();
        return;
      }
      video.dataset.videoReloaded = "1";
      video.src = cleanSrc;
      try {
        video.load();
      } catch (_error) {
        showFallback();
      }
    });

    window.setTimeout(function () {
      showFirstFrame();
      tryWarmPreview();
    }, 120);

    if (video.readyState >= 2) {
      showFirstFrame();
      return;
    }

    try {
      video.load();
    } catch (_error) {}
  }

  function initProductDetailPage() {
    bindGallery();
    applyRelatedImageFitModes();
    bindSmoothAddToCart();
    bindImageZoom();
    bindProductVideoPreview();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initProductDetailPage, { once: true });
  } else {
    initProductDetailPage();
  }
})();
