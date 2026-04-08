(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_CHECKOUT_BOOTSTRAP__) return;
  window.__BM_CHECKOUT_BOOTSTRAP__ = true;

  function initCheckoutPage() {
    if (window.__BM_CHECKOUT_INIT__) return;
    window.__BM_CHECKOUT_INIT__ = true;
    const checkoutRootForm = document.querySelector(".checkout-form");
  const citySelect = document.getElementById("city-select");
  const shippingEl = document.getElementById("shipping-amount");
  const totalEl = document.getElementById("total-amount");
  const subtotalNode = document.getElementById("subtotal-amount");
  const subtotal = parseFloat((subtotalNode && subtotalNode.dataset.subtotal) || "0") || 0;
  const summaryHintEl = document.getElementById("summary_hint");
  const priceStateBadge = document.getElementById("price_state_badge");
  const trustLine = document.getElementById("trust_line");

  const step1 = document.getElementById("checkout_step_1");
  const step2 = document.getElementById("checkout_step_2");
  const nextStepBtn = document.getElementById("next_step_btn");
  const backStepBtn = document.getElementById("back_step_btn");
  const stepIndicators = Array.from(document.querySelectorAll("[data-step-indicator]"));

  const locationLink = document.getElementById("location_link");
  const locationLat = document.getElementById("location_lat");
  const locationLng = document.getElementById("location_lng");
  const locationBtn = document.getElementById("location_btn");
  const locationStatus = document.getElementById("location_status");
  const locationPreview = document.getElementById("location_preview");
  const locationCoordsDisplay = document.getElementById("location_coords_display");

  const fullNameInput = document.getElementById("full_name_input");
  const phoneInput = document.getElementById("phone_input");
  const addressInput = document.getElementById("address_input");

  function setStep(step) {
    if (step1) step1.classList.toggle("is-active", step === 1);
    if (step2) step2.classList.toggle("is-active", step === 2);
    stepIndicators.forEach((node) => {
      const nodeStep = Number(node.dataset.stepIndicator || "0");
      node.classList.toggle("is-active", nodeStep === step);
    });
  }

  function setLocationStatus(message, isError) {
    if (!locationStatus) return;
    locationStatus.textContent = message || "";
    locationStatus.className = `small ${isError ? "text-danger" : "text-success"} mt-1`;
  }

  function canUseGeolocationNow() {
    return Boolean(
      window.isSecureContext ||
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1"
    );
  }

  function isWhatsAppUrl(url) {
    try {
      const parsed = new URL(String(url || ""), window.location.href);
      return parsed.hostname === "wa.me" || parsed.hostname === "api.whatsapp.com";
    } catch (_error) {
      return false;
    }
  }

  function openExternalTarget(url) {
    const targetUrl = String(url || "").trim();
    if (!targetUrl) return false;

    if (isWhatsAppUrl(targetUrl) && (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone)) {
      try {
        const anchor = document.createElement("a");
        anchor.href = targetUrl;
        anchor.target = "_blank";
        anchor.rel = "noopener noreferrer external";
        anchor.referrerPolicy = "no-referrer";
        anchor.style.display = "none";
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        return true;
      } catch (_error) {}
    }

    try {
      window.location.assign(targetUrl);
      return true;
    } catch (_error) {}

    try {
      window.location.href = targetUrl;
      return true;
    } catch (_error) {}

    return false;
  }

  function coerceFloat(value) {
    const raw = (value || "").toString().replace(",", ".").trim();
    const num = parseFloat(raw);
    return Number.isFinite(num) ? num : null;
  }

  function coordsToLink(lat, lng) {
    return `https://maps.google.com/q=${lat.toFixed(6)},${lng.toFixed(6)}`;
  }

  function setCoords(lat, lng, keepLink) {
    const latNum = coerceFloat(lat);
    const lngNum = coerceFloat(lng);
    if (latNum === null || lngNum === null) return false;
    locationLat.value = latNum.toFixed(6);
    locationLng.value = lngNum.toFixed(6);
    if (locationPreview && locationCoordsDisplay) {
      locationPreview.classList.remove("d-none");
      locationCoordsDisplay.textContent = `${latNum.toFixed(6)}, ${lngNum.toFixed(6)}`;
    }
    if (!keepLink) locationLink.value = coordsToLink(latNum, lngNum);
    return true;
  }

  function extractCoords(text) {
    const t = (text || "").trim();
    if (!t) return null;
    const match = t.match(/(-?\d{1,3}(?:[.,]\d+)?)[\s,]+(-?\d{1,3}(?:[.,]\d+)?)/);
    if (!match) return null;
    return { lat: match[1], lng: match[2] };
  }

  function setCheckoutEnabled(enabled) {
    const checkoutSubmitBtn = document.getElementById("checkout_submit_btn");
    if (checkoutSubmitBtn) checkoutSubmitBtn.disabled = !enabled;
  }

  function setSummaryState(state, shippingText, totalText) {
    if (priceStateBadge) {
      priceStateBadge.className = "price-state";
    }
    if (state === "ready") {
      if (priceStateBadge) {
        priceStateBadge.classList.add("ready");
        priceStateBadge.textContent = "Prix confirme";
      }
      if (summaryHintEl) summaryHintEl.textContent = "Parfait. Tu peux commander maintenant.";
      if (trustLine) trustLine.classList.remove("d-none");
      setCheckoutEnabled(true);
    } else if (state === "loading") {
      if (priceStateBadge) {
        priceStateBadge.classList.add("loading");
        priceStateBadge.textContent = "Calcul...";
      }
      if (summaryHintEl) summaryHintEl.textContent = "On calcule le prix livraison pour cette ville.";
      if (trustLine) trustLine.classList.add("d-none");
      setCheckoutEnabled(false);
    } else if (state === "error") {
      if (priceStateBadge) {
        priceStateBadge.classList.add("error");
        priceStateBadge.textContent = "Indisponible";
      }
      if (summaryHintEl) summaryHintEl.textContent = "Prix indisponible. Essaie une autre ville.";
      if (trustLine) trustLine.classList.add("d-none");
      setCheckoutEnabled(false);
    } else {
      if (priceStateBadge) {
        priceStateBadge.classList.add("waiting");
        priceStateBadge.textContent = "Choisis la ville";
      }
      if (summaryHintEl) summaryHintEl.textContent = "Choisis la ville pour afficher le prix livraison.";
      if (trustLine) trustLine.classList.add("d-none");
      setCheckoutEnabled(false);
    }
    if (shippingEl && typeof shippingText === "string") shippingEl.textContent = shippingText;
    if (totalEl && typeof totalText === "string") totalEl.textContent = totalText;
  }

  setSummaryState("empty", "Choisis ta ville", "--");

  let pricingEndpoint = "/api/pricing/delivery";
  if (checkoutRootForm && checkoutRootForm.dataset && checkoutRootForm.dataset.pricingEndpoint) {
    pricingEndpoint = checkoutRootForm.dataset.pricingEndpoint;
  }

  if (window.DeliveryPricing && citySelect) {
    const priceHidden = document.getElementById("delivery_price_cents");
    window.DeliveryPricing.init({
      citySelector: "#city-select",
      hiddenPriceSelector: "#delivery_price_cents",
      endpoint: pricingEndpoint,
      source: "marketplace",
      debounceMs: 150,
      onEmpty: function () {
        setSummaryState("empty", "Choisis ta ville", "--");
        if (priceHidden) priceHidden.value = "";
      },
      onLoading: function () {
        setSummaryState("loading", "Calcul...", "--");
      },
      onPrice: function (priceCents) {
        const shipping = Math.max(0, Number(priceCents || 0)) / 100;
        const shippingText = shipping.toFixed(2) + " MAD";
        const totalText = (subtotal + shipping).toFixed(2) + " MAD";
        setSummaryState("ready", shippingText, totalText);
      },
      onError: function () {
        setSummaryState("error", "Prix indisponible", "--");
        if (priceHidden) priceHidden.value = "";
      }
    });
  }

  if (nextStepBtn) {
    nextStepBtn.addEventListener("click", () => {
      const fields = [fullNameInput, phoneInput, citySelect, addressInput].filter(Boolean);
      const invalid = fields.find((field) => !field.checkValidity());
      if (invalid) {
        invalid.reportValidity();
        return;
      }
      if (!document.getElementById("delivery_price_cents")?.value) {
        if (citySelect) citySelect.focus();
        if (summaryHintEl) summaryHintEl.textContent = "Attends le calcul du prix livraison, puis continue.";
        return;
      }
      setStep(2);
    });
  }

  if (backStepBtn) {
    backStepBtn.addEventListener("click", () => setStep(1));
  }

  if (locationLink && locationLat && locationLng && locationBtn) {
    locationLink.addEventListener("input", () => {
      const coords = extractCoords(locationLink.value);
      if (coords && setCoords(coords.lat, coords.lng, true)) {
        setLocationStatus("Coordonnees detectees.", false);
      }
    });

    locationBtn.addEventListener("click", () => {
      if (!navigator.geolocation) {
        setLocationStatus("Geolocalisation indisponible sur cet appareil.", true);
        return;
      }
      if (!canUseGeolocationNow()) {
        setLocationStatus("La geolocalisation demande une page HTTPS. Saisis l adresse ou utilise localhost.", true);
        return;
      }

      const original = locationBtn.innerHTML;
      locationBtn.disabled = true;
      locationBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Localisation...';

      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const ok = setCoords(pos.coords.latitude, pos.coords.longitude, false);
          if (ok) setLocationStatus("Position detectee et ajoutee.", false);
          locationBtn.disabled = false;
          locationBtn.innerHTML = original;
        },
        (error) => {
          let message = "Impossible d obtenir la position. Verifiez les permissions.";
          if (error && error.code === 1) {
            message = "Acces a la position refuse. Autorise la localisation puis reessaie.";
          } else if (error && error.code === 2) {
            message = "Position indisponible pour le moment. Reessaie dans un instant.";
          } else if (error && error.code === 3) {
            message = "La localisation a pris trop de temps. Reessaie ou saisis l adresse.";
          }
          setLocationStatus(message, true);
          locationBtn.disabled = false;
          locationBtn.innerHTML = original;
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
      );
    });
  }

  const checkoutForm = document.querySelector(".checkout-form");
  const statusEl = document.getElementById("wa-status");
  const fallbackWrap = document.getElementById("wa-fallback");
  const fallbackLink = document.getElementById("wa-fallback-link");
  function getCoreDomApi() {
    return window.BMCoreDom || {};
  }
  function createRequestSeq() {
    const coreDomApi = getCoreDomApi();
    if (typeof coreDomApi.makeRequestSeq === "function") {
      return coreDomApi.makeRequestSeq();
    }
    if (window.BMAjaxGuard && typeof window.BMAjaxGuard.makeRequestSeq === "function") {
      return window.BMAjaxGuard.makeRequestSeq();
    }
    return (function () {
      let latest = 0;
      return {
        next: function () {
          latest += 1;
          return latest;
        },
        isLatest: function (id) {
          return Number(id) === latest;
        }
      };
    })();
  }
  const submitRequestSeq = createRequestSeq();
  let submitController = null;

  function showStatus(message) {
    if (!statusEl) return;
    statusEl.textContent = message || "";
    statusEl.classList.toggle("d-none", !message);
  }

  const bmCsrfApi = window.BMAjaxCSRF || window.BMAjaxCsrf || null;

  function bmAddCsrfHeaders(headers, formEl) {
    const baseHeaders = Object.assign({}, headers || {});
    if (bmCsrfApi && typeof bmCsrfApi.addToHeaders === "function") {
      return bmCsrfApi.addToHeaders(baseHeaders, formEl || null);
    }
    if (!baseHeaders["X-CSRFToken"] && !baseHeaders["x-csrftoken"] && window.csrfToken) {
      baseHeaders["X-CSRFToken"] = window.csrfToken;
    }
    return baseHeaders;
  }

  async function requestJSON(url, options) {
    const coreDomApi = getCoreDomApi();
    if (typeof coreDomApi.requestJSON === "function") {
      return coreDomApi.requestJSON(url, options || {});
    }
    try {
      const response = await fetch(url, options || {});
      let data = {};
      try {
        data = await response.json();
      } catch (_) {
        data = {};
      }
      return {
        ok: response.ok,
        status: response.status,
        data: data,
        error: response.ok ? null : (response.statusText || `HTTP ${response.status}`),
        aborted: false,
        timedOut: false
      };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        data: {},
        error: String((error && error.message) || "network_error"),
        aborted: !!(error && error.name === "AbortError"),
        timedOut: false
      };
    }
  }

  if (checkoutForm) {
    checkoutForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (checkoutForm.dataset.submitted === "true") return;
      const requestId = submitRequestSeq.next();

      checkoutForm.dataset.submitted = "true";
      showStatus("");
      if (fallbackWrap) fallbackWrap.classList.add("d-none");

      const submitBtn = checkoutForm.querySelector('button[type="submit"]');
      const originalHTML = submitBtn ? submitBtn.innerHTML : "";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Envoi...';
      }
      if (submitController) {
        try {
          submitController.abort();
        } catch (_) {}
      }
      submitController = (typeof AbortController !== "undefined") ? new AbortController() : null;

      try {
        const result = await requestJSON(checkoutForm.action, {
          method: "POST",
          body: new FormData(checkoutForm),
          headers: bmAddCsrfHeaders({
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json"
          }, checkoutForm),
          credentials: "same-origin",
          signal: submitController ? submitController.signal : undefined,
          timeoutMs: 25000
        });

        if (!submitRequestSeq.isLatest(requestId)) return;
        if (result.aborted) return;

        const data = (result.data && typeof result.data === "object") ? result.data : {};

        if (!result.ok || data.success === false) {
          showStatus(data.message || result.error || "Erreur lors de l envoi. Reessayez.");
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalHTML;
          }
          checkoutForm.dataset.submitted = "false";
          return;
        }

        const waUrl = data.wa_url;
        if (!waUrl) {
          showStatus("Lien WhatsApp indisponible. Reessayez.");
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalHTML;
          }
          checkoutForm.dataset.submitted = "false";
          return;
        }

        const opened = openExternalTarget(waUrl);
        if (!opened) {
          showStatus("Ouverture WhatsApp impossible. Utilise le lien ci-dessous.");
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalHTML;
          }
          checkoutForm.dataset.submitted = "false";
        }

        setTimeout(() => {
          if (waUrl && fallbackWrap && fallbackLink) {
            fallbackLink.href = waUrl;
            fallbackWrap.classList.remove("d-none");
          }
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalHTML || "Ouvrir WhatsApp";
          }
          checkoutForm.dataset.submitted = "false";
        }, 2500);
      } catch (_) {
        if (!submitRequestSeq.isLatest(requestId)) return;
        showStatus("Erreur reseau. Verifiez votre connexion.");
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalHTML;
        }
        checkoutForm.dataset.submitted = "false";
      } finally {
        if (submitRequestSeq.isLatest(requestId)) {
          submitController = null;
        }
      }
    });
  }


  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCheckoutPage, { once: true });
    return;
  }

  initCheckoutPage();
})();

