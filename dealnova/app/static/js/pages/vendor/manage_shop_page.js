(function () {
  "use strict";
  const region = document.getElementById("shopManageContent");
  const dialog = document.getElementById("shopEditDialog");
  const body = document.getElementById("shopEditBody");
  const discard = document.getElementById("shopDiscardConfirm");
  const workspace = window.BMVendorWorkspace;
  if (!region || !dialog || !body || !workspace || !window.fetch || typeof dialog.showModal !== "function") return;
  const headers = { "X-BM-Shop-Modal": "1", "X-Requested-With": "XMLHttpRequest", Accept: "application/json" };
  const historyKey = "bmShopEdit";
  let form = null, baseline = "", loader = null, sequence = 0, mutation = false;
  let fromHistory = false, closingHistory = false, logoUrl = null, locateSequence = 0, viewportFrame = 0;
  function logoFallback(image) {
    if (!(image instanceof HTMLImageElement) || !image.closest(".sm-avatar")) return;
    image.hidden = true;
    let icon = image.parentElement.querySelector("i.bi-shop");
    if (!icon) { icon = document.createElement("i"); icon.className = "bi bi-shop"; icon.setAttribute("aria-hidden", "true"); image.after(icon); }
    icon.hidden = false;
  }
  document.addEventListener("error", event => logoFallback(event.target), true);
  document.querySelectorAll(".sm-avatar img").forEach(image => { if (image.complete && !image.naturalWidth) logoFallback(image); });

  function message(node, text) {
    if (!node) return;
    node.textContent = text || "";
    node.hidden = !text;
  }
  function feedback(text) { message(document.getElementById("shopPageFeedback"), text); }
  function signature() {
    return form ? JSON.stringify(Array.from(new FormData(form).entries()).filter(([name]) => name !== "csrf_token")
      .map(([name, value]) => [name, value instanceof File ? (value.name ? [value.name, value.size, value.lastModified] : null) : value])) : "";
  }
  function dirty() { return !!form && signature() !== baseline; }
  function revokeLogo() { if (logoUrl) URL.revokeObjectURL(logoUrl); logoUrl = null; }
  function confirmDiscard() {
    discard.hidden = false;
    discard.querySelector("[data-shop-keep-editing]").focus({ preventScroll: true });
  }
  function setBusy(value) {
    mutation = value;
    dialog.dataset.busy = value ? "1" : "0";
    if (form) {
      form.setAttribute("aria-busy", String(value));
      form.querySelectorAll("button[type=submit]").forEach(button => { button.disabled = value; });
      // Preserve fields and files in the DOM through validation/network errors.
      form.querySelectorAll("input,textarea").forEach(input => {
        if (value) { input.dataset.shopWasDisabled = String(input.disabled); input.disabled = true; }
        else { input.disabled = input.dataset.shopWasDisabled === "true"; delete input.dataset.shopWasDisabled; }
      });
    }
  }
  function bindForm() {
    form = body.querySelector("#shopEditForm");
    baseline = signature();
    if (form && form.querySelector("[data-field-error]:not(:empty)")) baseline = "";
  }
  function loadState(text, retry) {
    const wrap = document.createElement("div");
    wrap.className = "sm-loading";
    const copy = document.createElement("p");
    copy.textContent = text;
    wrap.append(copy);
    if (retry) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "sm-button"; button.dataset.shopRetry = "1"; button.textContent = "Réessayer";
      wrap.append(button);
    }
    body.replaceChildren(wrap);
  }
  async function readJSON(response) {
    let data;
    try { data = await response.json(); } catch (_) { throw new Error("La session a expiré ou le serveur ne répond pas. Réessayez."); }
    if (response.ok && !data.success) throw new Error(data.message || "Impossible de terminer cette action.");
    return data;
  }
  async function post(action, payload) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(action, { method:"POST", body:payload, credentials:"same-origin", headers, signal:controller.signal });
      const data = await readJSON(response);
      if (response.status === 400 && data.error === "csrf") {
        // Refresh only the token. Never resend a mutation or replace the user's files.
        const fresh = await fetch(region.querySelector("[data-shop-edit]").dataset.editUrl, { credentials:"same-origin", headers, signal:controller.signal });
        const freshData = await readJSON(fresh);
        const parsed = new DOMParser().parseFromString(freshData.html || "", "text/html");
        const token = parsed.querySelector('[name="csrf_token"]')?.value;
        if (fresh.ok && token) {
          document.querySelectorAll('[name="csrf_token"]').forEach(input => { input.value = token; });
          document.querySelector('meta[name="csrf-token"]')?.setAttribute("content", token);
          data.message = "Votre session a été actualisée. Réessayez pour confirmer.";
        } else {
          data.message = freshData.message || "Reconnectez-vous pour enregistrer vos modifications.";
          data.redirect_url = freshData.redirect_url;
        }
      }
      return { response, data };
    } catch (error) {
      if (error.name === "AbortError") throw new Error("Le serveur met trop de temps à répondre. Vérifiez l’enregistrement avant de réessayer ; votre saisie est conservée.");
      throw error;
    } finally { clearTimeout(timer); }
  }
  async function loadForm() {
    loader?.abort();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    loader = controller;
    const current = ++sequence;
    form = null; baseline = "";
    body.setAttribute("aria-busy", "true");
    loadState("Chargement du formulaire…");
    try {
      const url = region.querySelector("[data-shop-edit]")?.dataset.editUrl;
      const response = await fetch(url, { credentials: "same-origin", headers, signal: controller.signal });
      const data = await readJSON(response);
      if (!response.ok) throw new Error(data.message || "Impossible de charger le formulaire.");
      if (current !== sequence || !dialog.open) return;
      body.innerHTML = data.html;
      bindForm();
    } catch (error) {
      if (current === sequence && dialog.open) loadState(error.name === "AbortError" ? "Le chargement a pris trop de temps. Réessayez." : error.message || "Impossible de charger le formulaire.", true);
    } finally { clearTimeout(timer); if (current === sequence) body.setAttribute("aria-busy", "false"); }
  }
  function viewport() {
    viewportFrame = 0;
    if (!dialog.open) return;
    const visual = window.visualViewport;
    if (visual?.scale > 1.05) return;
    // No height/transform animation: keyboard and browser toolbar movement stay stable.
    if (matchMedia("(max-width:767px)").matches) {
      dialog.style.height = Math.round(visual?.height || innerHeight) + "px";
      dialog.style.top = Math.round(visual?.offsetTop || 0) + "px";
      dialog.style.bottom = "auto";
    } else { dialog.style.height = ""; dialog.style.top = ""; dialog.style.bottom = ""; }
  }
  function scheduleViewport() { if (!viewportFrame) viewportFrame = requestAnimationFrame(viewport); }
  function openEditor(trigger, existing) {
    if (mutation || closingHistory || dialog.open) return;
    workspace.openDialog(dialog.id, trigger);
    if (!dialog.open) return;
    discard.hidden = true;
    viewport();
    if (!history.state?.[historyKey]) history.pushState(Object.assign({}, history.state, { [historyKey]: true }), "", location.href);
    if (existing) { body.replaceChildren(existing); bindForm(); }
    else loadForm();
  }
  dialog.addEventListener("vendor:workspace-dialog-before-close", event => {
    if (dirty()) { event.preventDefault(); confirmDiscard(); }
  });
  dialog.addEventListener("vendor:workspace-dialog-closed", () => {
    ++sequence; ++locateSequence; loader?.abort(); loader = null;
    form = null; baseline = ""; revokeLogo(); body.replaceChildren(); discard.hidden = true;
    dialog.dataset.busy = "0";
    if (!fromHistory && history.state?.[historyKey]) { closingHistory = true; history.back(); }
    fromHistory = false;
    region.querySelector("[data-shop-edit]")?.focus({ preventScroll: true });
  });
  window.addEventListener("popstate", () => {
    closingHistory = false;
    if (dialog.open && !history.state?.[historyKey]) {
      if (mutation || dirty()) {
        history.pushState(Object.assign({}, history.state, { [historyKey]: true }), "", location.href);
        if (!mutation) confirmDiscard();
      } else { fromHistory = true; workspace.closeDialog(); }
    } else if (!dialog.open && history.state?.[historyKey]) openEditor(region.querySelector("[data-shop-edit]"));
  });
  window.addEventListener("beforeunload", event => {
    if (dialog.open && (mutation || dirty())) { event.preventDefault(); event.returnValue = ""; }
  });
  window.visualViewport?.addEventListener("resize", scheduleViewport);
  window.visualViewport?.addEventListener("scroll", scheduleViewport);
  window.addEventListener("resize", scheduleViewport);

  function replaceContent(html, keepSection) {
    const opened = Array.from(region.querySelectorAll("details[open]"), node => node.id);
    region.innerHTML = html;
    opened.forEach(id => { const node = document.getElementById(id); if (node) node.open = true; });
    if (keepSection) document.getElementById(keepSection)?.querySelector("summary")?.focus({ preventScroll: true });
  }
  function showFormErrors(data) {
    const notice = form.querySelector("[data-shop-form-error]");
    message(notice, data.message || "Vérifiez les champs indiqués.");
    if (data.redirect_url) {
      const url = new URL(data.redirect_url, location.href);
      if (url.origin === location.origin) {
        const link = document.createElement("a");
        link.href = url.href; link.target = "_blank"; link.rel = "noopener"; link.textContent = "Se reconnecter";
        notice.append(document.createTextNode(" "), link);
      }
    }
    Object.entries(data.errors || {}).forEach(([name, text]) => {
      const input = form.elements.namedItem(name);
      if (input instanceof HTMLElement) input.setAttribute("aria-invalid", "true");
      const error = Array.from(form.querySelectorAll("[data-field-error]")).find(node => node.dataset.fieldError === name);
      if (error) error.textContent = Array.isArray(text) ? text.join(" ") : String(text);
    });
    const first = form.querySelector('[aria-invalid="true"]') || form.querySelector("[data-shop-form-error]");
    first?.scrollIntoView({ block: "nearest", behavior: "instant" });
  }
  async function saveEditor() {
    if (!form || mutation || !form.reportValidity()) return;
    const submitted = new FormData(form);
    const action = form.action;
    form.querySelectorAll("[data-field-error]").forEach(node => { node.textContent = ""; });
    form.querySelectorAll("[aria-invalid]").forEach(node => node.removeAttribute("aria-invalid"));
    message(form.querySelector("[data-shop-form-error]"), "");
    ++locateSequence;
    setBusy(true);
    try {
      const { response, data } = await post(action, submitted);
      if (!response.ok || !data.success) { showFormErrors(data); return; }
      if (typeof data.html !== "string") throw new Error("Les informations ont été envoyées. Rechargez la page pour vérifier l’enregistrement.");
      replaceContent(data.html);
      baseline = signature();
      setBusy(false);
      workspace.closeDialog();
      feedback(data.message || "Les informations de la boutique sont enregistrées.");
    } catch (error) {
      if (form) message(form.querySelector("[data-shop-form-error]"), error.message || "La connexion a été interrompue. Vos modifications sont conservées ici.");
    } finally { setBusy(false); }
  }
  async function sendPageForm(target, kind) {
    if (mutation) return;
    const payload = new FormData(target);
    const errorNode = target.querySelector(kind === "request" ? "[data-shop-request-error]" : "[data-shop-visibility-error]");
    const controls = Array.from(target.querySelectorAll("button"));
    const fields = Array.from(target.querySelectorAll("input,textarea,select"), field => [field, field.disabled]);
    message(errorNode, "");
    mutation = true;
    controls.forEach(button => { button.disabled = true; });
    fields.forEach(([field]) => { field.disabled = true; });
    target.setAttribute("aria-busy", "true");
    try {
      const { response, data } = await post(target.action, payload);
      if (!response.ok || !data.success) { message(errorNode, data.message || "Impossible d’enregistrer."); return; }
      if (typeof data.html !== "string") throw new Error("Rechargez la page pour vérifier cette action.");
      replaceContent(data.html, kind === "request" ? "shopChangeRequests" : "shopAdvancedOptions");
      feedback(data.message || "Modification enregistrée.");
    } catch (error) { message(errorNode, error.message || "Connexion interrompue. Vérifiez votre connexion avant de réessayer."); }
    finally { mutation = false; controls.forEach(button => { button.disabled = false; }); fields.forEach(([field, disabled]) => { field.disabled = disabled; }); target.setAttribute("aria-busy", "false"); }
  }
  async function copyLink() {
    const input = document.getElementById("shopPublicUrl");
    const status = document.getElementById("shopLinkFeedback");
    try {
      if (!navigator.clipboard?.writeText) throw new Error();
      await navigator.clipboard.writeText(input.value);
      message(status, "Lien copié.");
    } catch (_) {
      input.focus({ preventScroll:true }); input.select(); input.setSelectionRange(0, input.value.length);
      let copied = false;
      try { copied = document.execCommand("copy"); } catch (_) { /* Selection remains available. */ }
      message(status, copied ? "Lien copié." : "Le lien est sélectionné. Copiez-le pour le partager.");
    }
  }
  async function shareLink() {
    const url = document.getElementById("shopPublicUrl").value;
    if (navigator.share) {
      try { await navigator.share({ title:region.querySelector(".sm-identity h2").textContent, url }); return; }
      catch (error) { if (error.name === "AbortError") return; }
    }
    document.getElementById("shopShareFallback").hidden = false;
    message(document.getElementById("shopLinkFeedback"), "Copiez le lien ou partagez-le sur WhatsApp.");
  }
  function locate(button) {
    if (!form || mutation) return;
    const status = document.getElementById("shopLocationStatus");
    if (!navigator.geolocation) { message(status, "La localisation n’est pas disponible sur cet appareil."); return; }
    const current = ++locateSequence, activeForm = form;
    button.disabled = true;
    message(status, "Recherche de votre position…");
    navigator.geolocation.getCurrentPosition(position => {
      button.disabled = false;
      if (current !== locateSequence || form !== activeForm || mutation || !dialog.open) return;
      form.elements.service_latitude.value = String(position.coords.latitude);
      form.elements.service_longitude.value = String(position.coords.longitude);
      form.elements.clear_exact_location.value = "0";
      form.querySelector("[data-shop-clear-location]").hidden = false;
      message(status, "Position ajoutée. Enregistrez pour la conserver.");
    }, error => {
      button.disabled = false;
      if (current !== locateSequence || form !== activeForm || !dialog.open) return;
      message(status, error.code === 1 ? "Autorisez la localisation dans votre navigateur pour utiliser votre position." : "Position introuvable. Réessayez ou renseignez votre adresse.");
    }, { enableHighAccuracy:true, timeout:12000, maximumAge:60000 });
  }
  document.addEventListener("click", event => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const trigger = target.closest("[data-shop-edit]");
    if (trigger) { event.preventDefault(); openEditor(trigger); }
    if (target.closest("[data-shop-close]") && !target.closest("[data-vd-close]")) { event.preventDefault(); workspace.requestCloseDialog(); }
    if (target.closest("[data-shop-retry]")) loadForm();
    if (target.closest("[data-shop-keep-editing]")) { discard.hidden = true; dialog.querySelector("[data-shop-close]").focus({ preventScroll:true }); }
    if (target.closest("[data-shop-discard]") && !mutation) workspace.closeDialog();
    if (target.closest("#shopCopyLink")) copyLink();
    if (target.closest("#shopShareLink")) shareLink();
    const locateButton = target.closest("[data-shop-locate]");
    if (locateButton) locate(locateButton);
    if (target.closest("[data-shop-clear-location]") && form && !mutation) {
      ++locateSequence;
      form.elements.service_latitude.value = ""; form.elements.service_longitude.value = ""; form.elements.clear_exact_location.value = "1";
      form.querySelector("[data-shop-clear-location]").hidden = true;
      form.querySelector("[data-shop-locate]").disabled = false;
      message(document.getElementById("shopLocationStatus"), "Position retirée. Enregistrez pour confirmer.");
    }
    if (target.closest("[data-shop-visibility-cancel]")) document.getElementById("shopVisibilityConfirm").hidden = true;
    if (target.closest("[data-shop-visibility-confirm]")) sendPageForm(document.getElementById("shopVisibilityForm"), "visibility");
  });
  document.addEventListener("submit", event => {
    const target = event.target;
    if (!(target instanceof HTMLFormElement)) return;
    if (target.id === "shopEditForm") { event.preventDefault(); saveEditor(); }
    if (target.matches("[data-shop-request]")) { event.preventDefault(); sendPageForm(target, "request"); }
    if (target.id === "shopVisibilityForm") {
      event.preventDefault();
      if (target.elements.is_active.value === "0") { const confirm = document.getElementById("shopVisibilityConfirm"); confirm.hidden = false; confirm.querySelector("[data-shop-visibility-cancel]").focus({ preventScroll:true }); }
      else sendPageForm(target, "visibility");
    }
  });
  document.addEventListener("change", event => {
    if (!form || event.target !== form.elements.logo) return;
    revokeLogo();
    const file = form.elements.logo.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { message(form.querySelector("[data-shop-form-error]"), "Le logo ne doit pas dépasser 5 Mo."); return; }
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return;
    logoUrl = URL.createObjectURL(file);
    const image = document.createElement("img");
    image.src = logoUrl; image.alt = "Nouveau logo";
    document.getElementById("shopLogoPreview").replaceChildren(image);
    if (form.elements.remove_logo) form.elements.remove_logo.checked = false;
  });
  const inline = document.getElementById("shopInlineEditor");
  if (inline) {
    const existing = inline.querySelector("#shopEditForm");
    const url = new URL(location.href); url.searchParams.delete("edit_shop");
    const state = Object.assign({}, history.state); delete state[historyKey];
    history.replaceState(state, "", url);
    openEditor(region.querySelector("[data-shop-edit]"), existing);
    if (dialog.open) inline.remove();
  }
})();
