(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_VENDOR_MANAGE_SHOP_PAGE_INIT__) return;
  window.__BM_VENDOR_MANAGE_SHOP_PAGE_INIT__ = true;

  const CONFIG_ID = "vendorManageShopPageConfig";
  const defaults = {
    unsupportedGeolocationText: "Geolocalisation non supportee sur cet appareil.",
    locatingText: "Localisation en cours...",
    updatePositionLabel: "Mettre a jour ma position",
    sharePositionLabel: "Partager ma position exacte",
    allowLocationMessage: "Autorisez la localisation pour enregistrer la position exacte.",
    locateFailedMessage: "Impossible de recuperer votre position. Reessayez.",
    positionReadyPrefix: "Position exacte prete:",
    positionRemovedText: "Position exacte retiree. Enregistrez pour confirmer.",
    copiedLinkText: "Lien copie",
    copyFailedText: "Copie impossible sur ce navigateur.",
    shareBaseUrl: "https://wa.me/text=",
  };

  function readConfig() {
    const node = document.getElementById(CONFIG_ID);
    if (!node) return defaults;
    try {
      const parsed = JSON.parse(node.textContent || "{}");
      if (!parsed || typeof parsed !== "object") return defaults;
      return Object.assign({}, defaults, parsed);
    } catch (_error) {
      return defaults;
    }
  }

  const cfg = readConfig();
  const VendorUI = window.VendorUI || {};
  const LIGHTBOX_ID = "manage-shop-image-lightbox";

  function initTooltips() {
    if (!(window.bootstrap && window.bootstrap.Tooltip)) return;
    const nodes = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    nodes.forEach(function (node) {
      if (node.dataset.manageShopTooltipBound === "1") return;
      node.dataset.manageShopTooltipBound = "1";
      try {
        new window.bootstrap.Tooltip(node);
      } catch (_error) {}
    });
  }

  async function copyTextToClipboard(rawValue) {
    const value = String(rawValue || "").trim();
    if (!value) return false;

    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
        return true;
      }
    } catch (_error) {}

    const helper = document.createElement("textarea");
    helper.value = value;
    helper.setAttribute("readonly", "readonly");
    helper.style.position = "fixed";
    helper.style.top = "-9999px";
    helper.style.left = "-9999px";
    document.body.appendChild(helper);
    helper.focus();
    helper.select();

    let copied = false;
    try {
      copied = Boolean(document.execCommand("copy"));
    } catch (_error) {
      copied = false;
    }

    helper.remove();
    return copied;
  }

  function bindShopPublicUrlActions() {
    const publicLink = document.getElementById("shopPublicUrlLink");
    const copyBtn = document.getElementById("copyShopPublicUrlBtn");
    const hint = document.getElementById("shopPublicUrlHint");

    if (!publicLink || !copyBtn) return;

    copyBtn.addEventListener("click", async function () {
      const copied = await copyTextToClipboard(publicLink.getAttribute("href") || publicLink.textContent || "");
      if (hint) {
        hint.textContent = copied ? cfg.copiedLinkText : cfg.copyFailedText;
      }
    });
  }

  function bindRealtimeSearch() {
    const searchInput = document.getElementById("manageShopRealtimeSearch");
    const searchClear = document.getElementById("manageShopSearchClear");
    const searchEmpty = document.getElementById("manageShopSearchEmpty");
    const searchableItems = Array.from(document.querySelectorAll(".js-manage-search-item"));

    if (!searchInput || !searchableItems.length) return;

    function applyManageSearch() {
      const query = String(searchInput.value || "").trim().toLowerCase();
      let visibleCount = 0;
      searchableItems.forEach(function (item) {
        const haystack = String(item.getAttribute("data-search") || item.textContent || "").toLowerCase();
        const isVisible = !query || haystack.includes(query);
        item.classList.toggle("is-hidden-by-search", !isVisible);
        if (isVisible) visibleCount += 1;
      });
      if (searchEmpty) {
        searchEmpty.style.display = query && visibleCount === 0 ? "block" : "none";
      }
    }

    searchInput.addEventListener("input", applyManageSearch, { passive: true });
    if (searchClear) {
      searchClear.addEventListener("click", function () {
        searchInput.value = "";
        applyManageSearch();
        searchInput.focus();
      });
    }
  }

  function bindMobileInfoToggle() {
    const mobileInfoGrid = document.getElementById("mobileInfoGrid");
    const mobileInfoToggleBtn = document.getElementById("mobileInfoToggleBtn");
    if (!mobileInfoGrid || !mobileInfoToggleBtn) return;

    mobileInfoToggleBtn.addEventListener("click", function () {
      const expanded = mobileInfoGrid.classList.toggle("mobile-info-expanded");
      mobileInfoToggleBtn.textContent = expanded ? "Voir moins d'infos" : "Voir plus d'infos";
    });
  }

  function bindServiceLocationPanel() {
    const captureBtn = document.getElementById("captureExactLocationBtn");
    const clearBtn = document.getElementById("clearExactLocationBtn");
    const latInput = document.getElementById("serviceLatitudeInput");
    const lngInput = document.getElementById("serviceLongitudeInput");
    const clearExactInput = document.getElementById("clearExactLocationInput");
    const statusEl = document.getElementById("exactLocationStatus");
    const rawMapInput = document.getElementById("serviceRawMapUrl");
    const rawMapHint = document.getElementById("rawMapHint");
    const copyRawBtn = document.getElementById("copyRawMapUrlBtn");
    const shareRawBtn = document.getElementById("shareRawMapWhatsappBtn");
    const addressInput = document.querySelector('input[name="service_address"]');
    const noteInput = document.querySelector('input[name="service_location_note"]');

    if (!latInput && !lngInput && !statusEl) return;

    function getRawMapUrl() {
      const lat = String((latInput && latInput.value) || "").trim();
      const lng = String((lngInput && lngInput.value) || "").trim();
      if (!lat || !lng) return "";
      return "https://www.google.com/maps?q=" + lat + "," + lng;
    }

    function refreshRawMapUi() {
      const rawUrl = getRawMapUrl();
      if (rawMapInput) rawMapInput.value = rawUrl;
      const hasLocation = Boolean(rawUrl);
      if (copyRawBtn) copyRawBtn.disabled = !hasLocation;
      if (shareRawBtn) shareRawBtn.disabled = !hasLocation;
      if (rawMapHint) {
        rawMapHint.textContent = hasLocation
          ? "Lien pret a copier et partager."
          : "Ajoutez votre position exacte.";
      }
      if (clearBtn) {
        clearBtn.style.display = hasLocation ? "" : "none";
      }
    }

    function setExactStatus(text, tone) {
      if (!statusEl) return;
      statusEl.textContent = text;
      statusEl.classList.remove("text-muted", "text-success", "text-danger");
      if (tone === "success") {
        statusEl.classList.add("text-success");
      } else if (tone === "danger") {
        statusEl.classList.add("text-danger");
      } else {
        statusEl.classList.add("text-muted");
      }
    }

    if (captureBtn) {
      captureBtn.addEventListener("click", function () {
        if (!navigator.geolocation) {
          setExactStatus(cfg.unsupportedGeolocationText, "danger");
          return;
        }
        if (!window.isSecureContext && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
          setExactStatus("La geolocalisation demande HTTPS. Ouvre la page en HTTPS ou saisis la position manuellement.", "danger");
          return;
        }

        captureBtn.disabled = true;
        captureBtn.innerHTML = '<i class="bi bi-hourglass-split me-2"></i> ' + cfg.locatingText;

        navigator.geolocation.getCurrentPosition(
          function (position) {
            const lat = Number(position.coords.latitude).toFixed(6);
            const lng = Number(position.coords.longitude).toFixed(6);
            if (latInput) latInput.value = lat;
            if (lngInput) lngInput.value = lng;
            if (clearExactInput) clearExactInput.value = "0";
            refreshRawMapUi();
            setExactStatus(cfg.positionReadyPrefix + " " + lat + ", " + lng, "success");
            captureBtn.disabled = false;
            captureBtn.innerHTML = '<i class="bi bi-crosshair me-2"></i> ' + cfg.updatePositionLabel;
          },
          function (error) {
            let message = cfg.locateFailedMessage;
            if (error && error.code === 1) {
              message = cfg.allowLocationMessage;
            } else if (error && error.code === 3) {
              message = "La detection de position a pris trop de temps. Reessaie ou saisis la position manuellement.";
            }
            setExactStatus(message, "danger");
            captureBtn.disabled = false;
            captureBtn.innerHTML = '<i class="bi bi-crosshair me-2"></i> ' + cfg.sharePositionLabel;
          },
          { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
        );
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        if (latInput) latInput.value = "";
        if (lngInput) lngInput.value = "";
        if (clearExactInput) clearExactInput.value = "1";
        refreshRawMapUi();
        setExactStatus(cfg.positionRemovedText, "muted");
      });
    }

    if (copyRawBtn) {
      copyRawBtn.addEventListener("click", async function () {
        const rawUrl = getRawMapUrl();
        if (!rawUrl) return;
        const copied = await copyTextToClipboard(rawUrl);
        if (rawMapHint) rawMapHint.textContent = copied ? cfg.copiedLinkText : cfg.copyFailedText;
      });
    }

    if (shareRawBtn) {
      shareRawBtn.addEventListener("click", function () {
        const rawUrl = getRawMapUrl();
        if (!rawUrl) return;
        const lines = ["Position : " + rawUrl];
        const address = String((addressInput && addressInput.value) || "").trim();
        const note = String((noteInput && noteInput.value) || "").trim();
        if (address) lines.push("Adresse : " + address);
        if (note) lines.push("Repere : " + note);
        const msg = encodeURIComponent(lines.join("\n"));
        window.open(cfg.shareBaseUrl + msg, "_blank", "noopener");
      });
    }

    refreshRawMapUi();
  }

  function revealAnimatedCards() {
    const cards = document.querySelectorAll(".animated-card");
    cards.forEach(function (card) {
      card.style.opacity = "0";
      window.setTimeout(function () {
        card.style.opacity = "1";
      }, 100);
    });
  }

  function applyProductRowAnimationDelay() {
    document.querySelectorAll(".product-row[data-delay]").forEach(function (row) {
      const delay = row.dataset.delay;
      if (!delay) return;
      row.style.animationDelay = String(delay) + "s";
    });
  }

  function ensureRippleKeyframes() {
    if (document.getElementById("manage-shop-ripple-style")) return;
    const style = document.createElement("style");
    style.id = "manage-shop-ripple-style";
    style.textContent = "@keyframes ripple { to { transform: scale(4); opacity: 0; } }";
    document.head.appendChild(style);
  }

  function bindRippleEffect() {
    ensureRippleKeyframes();
    document.querySelectorAll(".btn-hover-effect").forEach(function (button) {
      if (button.dataset.manageRippleBound === "1") return;
      button.dataset.manageRippleBound = "1";
      button.addEventListener("click", function (event) {
        const rect = this.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const x = event.clientX - rect.left - size / 2;
        const y = event.clientY - rect.top - size / 2;

        const ripple = document.createElement("span");
        ripple.style.cssText = "position:absolute;border-radius:50%;background:rgba(255,255,255,0.6);transform:scale(0);animation:ripple 0.6s linear;width:" + size + "px;height:" + size + "px;top:" + y + "px;left:" + x + "px;";
        this.appendChild(ripple);
        window.setTimeout(function () {
          ripple.remove();
        }, 600);
      });
    });
  }

  function openImageLightbox(src, title) {
    const imageSrc = String(src || "").trim();
    if (!imageSrc) return;

    const existing = document.getElementById(LIGHTBOX_ID);
    if (existing) existing.remove();

    const previousOverflow = document.body ? document.body.style.overflow : "";
    const modal = document.createElement("div");
    modal.id = LIGHTBOX_ID;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.style.cssText = "position:fixed;inset:0;background:rgba(2,6,23,.9);display:flex;align-items:center;justify-content:center;padding:16px;z-index:9999;cursor:zoom-out;";

    const img = document.createElement("img");
    img.src = imageSrc;
    img.alt = String(title || "Photo produit");
    img.style.cssText = "max-width:min(96vw,1200px);max-height:92vh;object-fit:contain;border-radius:14px;box-shadow:0 30px 70px rgba(0,0,0,.45);";

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "Fermer l'aperçu");
    closeBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    closeBtn.style.cssText = "position:fixed;top:16px;right:16px;width:42px;height:42px;border-radius:999px;border:1px solid rgba(255,255,255,.25);background:rgba(15,23,42,.66);color:#fff;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;z-index:10000;";

    const caption = document.createElement("div");
    caption.textContent = String(title || "");
    caption.style.cssText = "position:fixed;left:50%;bottom:16px;transform:translateX(-50%);padding:8px 12px;border-radius:999px;background:rgba(15,23,42,.66);border:1px solid rgba(255,255,255,.2);color:#fff;font-weight:600;font-size:.85rem;max-width:90vw;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
    if (!caption.textContent) {
      caption.style.display = "none";
    }

    function cleanup() {
      document.removeEventListener("keydown", onKeydown);
      if (modal && modal.parentNode) modal.parentNode.removeChild(modal);
      if (closeBtn && closeBtn.parentNode) closeBtn.parentNode.removeChild(closeBtn);
      if (caption && caption.parentNode) caption.parentNode.removeChild(caption);
      if (document.body) {
        document.body.style.overflow = previousOverflow;
      }
    }

    function onKeydown(event) {
      if (event.key === "Escape") cleanup();
    }

    modal.addEventListener("click", function (event) {
      if (event.target === modal) cleanup();
    });
    closeBtn.addEventListener("click", cleanup);
    document.addEventListener("keydown", onKeydown);

    modal.appendChild(img);
    document.body.appendChild(modal);
    document.body.appendChild(closeBtn);
    document.body.appendChild(caption);
    document.body.style.overflow = "hidden";
  }

  function bindProductImagePreview() {
    document.querySelectorAll(".manage-product-thumb[data-large]").forEach(function (img) {
      if (img.dataset.managePreviewBound === "1") return;
      img.dataset.managePreviewBound = "1";

      function openPreview() {
        const src = img.getAttribute("data-large") || img.getAttribute("src") || "";
        const title = img.getAttribute("data-title") || img.getAttribute("alt") || "Photo produit";
        openImageLightbox(src, title);
      }

      img.addEventListener("click", openPreview);
      img.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openPreview();
        }
      });
    });
  }

  function animateStatCounters() {
    document.querySelectorAll(".stat-value").forEach(function (stat) {
      const target = parseInt(String(stat.textContent || ""), 10);
      if (!Number.isFinite(target) || target <= 0) return;

      let current = 0;
      const increment = target / 50;
      const timer = window.setInterval(function () {
        current += increment;
        if (current >= target) {
          current = target;
          window.clearInterval(timer);
        }
        stat.textContent = Math.floor(current).toLocaleString();
      }, 30);
    });
  }

  function bindHeaderParallax() {
    const header = document.querySelector(".shop-header");
    if (!header) return;

    const prefersReducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion) return;

    const rafThrottle = typeof VendorUI.rafThrottle === "function"
      ? VendorUI.rafThrottle
      : function (fn) {
          let ticking = false;
          return function () {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(function () {
              ticking = false;
              fn();
            });
          };
        };

    const onScroll = rafThrottle(function () {
      const scrolled = window.pageYOffset || 0;
      const rate = scrolled * -0.5;
      header.style.transform = "translateY(" + rate + "px)";
    });

    window.addEventListener("scroll", onScroll, { passive: true });
  }

  function init() {
    if (typeof VendorUI.initOnce === "function") {
      VendorUI.initOnce();
    }
    if (typeof VendorUI.bindConfirmForms === "function") {
      VendorUI.bindConfirmForms(document);
    }

    initTooltips();
    bindShopPublicUrlActions();
    bindRealtimeSearch();
    bindMobileInfoToggle();
    bindServiceLocationPanel();
    revealAnimatedCards();
    applyProductRowAnimationDelay();
    bindRippleEffect();
    bindProductImagePreview();
    animateStatCounters();
    bindHeaderParallax();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();

