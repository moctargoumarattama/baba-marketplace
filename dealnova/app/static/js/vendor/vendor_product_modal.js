(function () {
  "use strict";

  const standalone = !!document.getElementById("vendorFormPage");
  const dialog = document.getElementById("vendorProductDialog") || document.getElementById("vendorFormPage");
  if (!dialog || dialog.dataset.bound === "1") return;
  let createType = dialog.dataset.defaultType === "location" ? "location" : "product";
  let editUrl = null;
  let formMode = "create";
  let preferredKind = null;
  const triggers = "[data-vendor-product-create], [data-vendor-location-create], [data-vendor-product-edit], [data-vendor-location-edit]";
  function createUrl(type = createType) {
    return type === "location" ? dialog.dataset.locationCreateUrl : dialog.dataset.createUrl;
  }
  function formUrl() { return editUrl || createUrl(); }
  function editTarget(raw, type) {
    try {
      const url = new URL(raw, location.href);
      const pattern = type === "location" ? /^\/owner\/location\/\d+\/edit$/ : /^\/vendor\/product\/\d+\/edit$/;
      if (url.origin !== location.origin || !pattern.test(url.pathname)) return null;
      url.search = "";
      url.hash = "";
      return url.href;
    } catch (_error) { return null; }
  }
  function requestedForm(url) {
    for (const type of ["product", "location"]) {
      const id = url.searchParams.get("edit_" + type);
      const template = type === "location" ? dialog.dataset.locationEditUrl : dialog.dataset.productEditUrl;
      if (id && /^\d+$/.test(id) && template) return { type, url: editTarget(template.replace("/0/edit", "/" + id + "/edit"), type) };
    }
    const type = url.searchParams.get("new");
    return type === "product" || type === "location" ? { type, url: null } : null;
  }
  if (!standalone && typeof dialog.showModal !== "function") {
    const requested = requestedForm(new URL(location.href));
    if (requested) {
      const target = new URL(requested.url || createUrl(requested.type), location.href);
      target.searchParams.set("standalone", "1");
      window.location.replace(target.href);
    }
    return;
  }
  dialog.dataset.bound = "1";
  const content = document.getElementById("vendorProductContent");
  const title = document.getElementById("vendorProductTitle");
  const status = document.getElementById("vpmStatus");
  const submit = dialog.querySelector("[data-vpm-submit]");
  const submitLabel = dialog.querySelector("[data-vpm-submit-label]");
  const confirm = document.getElementById("vpmDiscardConfirm");
  const progressWrap = document.getElementById("vpmProgress");
  const progress = progressWrap.querySelector("progress");
  const historyKey = "bmVendorProductCreate";
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let phase = "closed";
  let busy = false;
  let form = null;
  let config = {};
  let initialValues = "";
  let photos = [];
  let video = null;
  let opener = null;
  let confirmOpener = null;
  let scrollSnapshot = null;
  let loader = null;
  let requestSeq = 0;
  let viewportFrame = 0;
  let reopenAfterClose = false;
  let confirmedLeave = false;
  let restoringHistory = false;
  let closeWhenHistoryRestored = false;
  let disabledControls = [];
  const categoryMemory = { physical: "", service: "" };
  const headers = { "X-Vendor-Modal": createType + "-create", "X-Requested-With": "fetch", Accept: "application/json" };

  function setStatus(message) {
    status.textContent = message || "";
  }

  function safeLink(raw) {
    try {
      const url = new URL(raw, window.location.href);
      return url.origin === window.location.origin && /^https?:$/.test(url.protocol) ? url.href : null;
    } catch (_error) {
      return null;
    }
  }

  function showError(message, redirectUrl) {
    const target = form ? form.querySelector("#vpmFormError") : content;
    target.replaceChildren();
    const copy = document.createElement("p");
    copy.textContent = message || "Impossible d’enregistrer. Réessayez dans quelques instants.";
    target.appendChild(copy);
    const href = redirectUrl && safeLink(redirectUrl);
    if (href) {
      const link = document.createElement("a");
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Ouvrir la page dans un autre onglet";
      target.appendChild(link);
    }
    target.hidden = false;
    if (!form) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "vpm-button vpm-button-secondary";
      retry.dataset.vpmRetry = "1";
      retry.textContent = "Réessayer";
      target.appendChild(retry);
      target.classList.add("vpm-load-state");
    }
  }

  function currentKind() {
    return form && form.querySelector('[name="kind"]:checked, input[type="hidden"][name="kind"]')?.value === "service" ? "service" : "physical";
  }

  function signature() {
    if (!form) return "";
    return JSON.stringify(Array.from(form.elements)
      .filter((field) => field.name && field.type !== "file" && field.name !== "csrf_token" && !field.disabled && (!/^(radio|checkbox)$/.test(field.type) || field.checked))
      .map((field) => [field.name, field.value]));
  }

  function isDirty() {
    return !!form && (signature() !== initialValues || photos.length > 0 || !!video);
  }

  function updateViewport() {
    viewportFrame = 0;
    if (!dialog.open || phase === "opening" || phase === "closing") return;
    const viewport = window.visualViewport;
    if (viewport && viewport.scale > 1.05) return;
    const height = Math.round(viewport ? viewport.height : window.innerHeight);
    const top = Math.round(viewport ? viewport.offsetTop : 0);
    const nextHeight = height + "px";
    const nextTop = top + "px";
    if (dialog.style.getPropertyValue("--vpm-viewport-height") !== nextHeight) dialog.style.setProperty("--vpm-viewport-height", nextHeight);
    if (dialog.style.getPropertyValue("--vpm-viewport-top") !== nextTop) dialog.style.setProperty("--vpm-viewport-top", nextTop);
  }

  function scheduleViewport() {
    if (!viewportFrame) viewportFrame = window.requestAnimationFrame(updateViewport);
  }

  function lockPage() {
    if (scrollSnapshot) return;
    const body = document.body;
    const root = document.documentElement;
    const bodyKeys = ["position", "top", "left", "width", "paddingRight"];
    scrollSnapshot = { x: window.scrollX, y: window.scrollY, rootOverflow: root.style.overflow, body: {} };
    bodyKeys.forEach((key) => { scrollSnapshot.body[key] = body.style[key]; });
    const gap = Math.max(0, window.innerWidth - root.clientWidth);
    const padding = parseFloat(window.getComputedStyle(body).paddingRight) || 0;
    body.style.position = "fixed";
    body.style.top = -scrollSnapshot.y + "px";
    body.style.left = -scrollSnapshot.x + "px";
    body.style.width = "100%";
    if (gap) body.style.paddingRight = padding + gap + "px";
    root.style.overflow = "hidden";
  }

  function unlockPage() {
    if (!scrollSnapshot) return;
    const saved = scrollSnapshot;
    scrollSnapshot = null;
    Object.keys(saved.body).forEach((key) => { document.body.style[key] = saved.body[key]; });
    document.documentElement.style.overflow = saved.rootOverflow;
    window.scrollTo({ left: saved.x, top: saved.y, behavior: "instant" });
  }

  function afterMotion(done) {
    const panel = dialog.querySelector(".vpm-panel");
    let finished = false;
    function finish(event) {
      if (event && event.target !== panel) return;
      if (finished) return;
      finished = true;
      window.clearTimeout(timer);
      panel.removeEventListener("animationend", finish);
      done();
    }
    const timer = window.setTimeout(finish, reducedMotion.matches ? 0 : 230);
    panel.addEventListener("animationend", finish);
  }

  function releaseMedia() {
    content.querySelectorAll("video").forEach((player) => {
      player.pause();
      player.removeAttribute("src");
      player.load();
    });
    photos.forEach((entry) => URL.revokeObjectURL(entry.url));
    photos = [];
    if (video) URL.revokeObjectURL(video.url);
    video = null;
  }

  function setConfirm(open) {
    if (open && confirm.hidden) confirmOpener = document.activeElement;
    confirm.hidden = !open;
    Array.from(dialog.querySelector(".vpm-panel").children).forEach((node) => {
      if (node !== confirm) node.inert = open;
    });
    if (open) confirm.querySelector("[data-vpm-keep]").focus({ preventScroll: true });
    else if (confirmOpener?.isConnected && dialog.contains(confirmOpener)) confirmOpener.focus({ preventScroll: true });
  }

  function finishClose() {
    dialog.classList.remove("is-entering", "is-closing");
    dialog.close();
    setConfirm(false);
    phase = "closed";
    releaseMedia();
    form = null;
    content.replaceChildren();
    confirmedLeave = false;
    unlockPage();
    if (opener?.isConnected && !opener.closest("[inert]")) opener.focus({ preventScroll: true });
    else document.querySelector(createType === "location" ? "[data-vendor-location-create]" : "[data-vendor-product-create]")?.focus({ preventScroll: true });
    document.dispatchEvent(new CustomEvent("vendor:form-closed", { detail: { formType: createType } }));
    if (reopenAfterClose) {
      const next = reopenAfterClose;
      reopenAfterClose = false;
      openDialog(null, false, next.type, next.url, next.kind);
    }
  }

  function closeDialog(updateHistory) {
    if (phase === "closed" || phase === "closing") return;
    if (updateHistory && restoringHistory) {
      closeWhenHistoryRestored = true;
      return;
    }
    ++requestSeq;
    if (loader) loader.abort();
    phase = "closing";
    dialog.classList.remove("is-entering");
    dialog.classList.add("is-closing");
    afterMotion(finishClose);
    if (updateHistory && window.history.state?.[historyKey]) window.history.back();
  }

  function requestClose() {
    if (busy || phase === "closing") return;
    if (isDirty()) {
      setConfirm(true);
      return;
    }
    closeDialog(true);
  }

  function clearFieldError(name) {
    if (!form) return;
    const error = Array.from(form.querySelectorAll("[data-vpm-field-error]")).find((node) => node.dataset.vpmFieldError === name);
    if (error) { error.hidden = true; error.textContent = ""; }
    Array.from(form.elements).filter((node) => node.name === name).forEach((node) => node.removeAttribute("aria-invalid"));
  }

  function fieldError(name, message) {
    if (!form) return;
    const error = Array.from(form.querySelectorAll("[data-vpm-field-error]")).find((node) => node.dataset.vpmFieldError === name);
    if (error) { error.textContent = message; error.hidden = false; }
    const details = error?.closest("details");
    if (details) details.open = true;
    Array.from(form.elements).filter((node) => node.name === name).forEach((node) => node.setAttribute("aria-invalid", "true"));
  }

  function syncKind(remember) {
    const kind = currentKind();
    const category = form.elements.namedItem("category_id");
    if (remember) categoryMemory[remember] = category.value;
    title.textContent = formMode === "edit" ? (kind === "service" ? "Modifier le service" : "Modifier le produit") : (kind === "service" ? "Ajouter un service" : "Ajouter un produit");
    form.querySelector("[data-vpm-name-label]").textContent = kind === "service" ? "Nom du service" : "Nom du produit";
    const stock = form.elements.namedItem("stock");
    form.querySelector("[data-vpm-stock]").hidden = kind === "service";
    stock.disabled = kind === "service";
    stock.required = kind !== "service";
    category.replaceChildren(new Option("Choisir une catégorie", ""));
    (config.categoriesByKind?.[kind] || []).forEach((row) => category.add(new Option(String(row.name), String(row.id))));
    category.value = categoryMemory[kind] || "";
    ["kind", "stock", "category_id"].forEach(clearFieldError);
    form.dataset.kind = kind;
  }

  function syncLocation() {
    const deposit = form.elements.namedItem("deposit");
    const hasDeposit = form.elements.namedItem("deposit_required").value === "1";
    form.querySelector("[data-vpm-deposit]").hidden = !hasDeposit;
    deposit.disabled = !hasDeposit;
    deposit.required = hasDeposit;
    if (!hasDeposit) clearFieldError("deposit");
    const daily = form.querySelector('[name="listing_type"]:checked')?.value === "daily";
    const label = form.querySelector("[data-vpm-rent-label]");
    if (label) label.textContent = daily ? "Loyer (DH / jour)" : "Loyer (DH / mois)";
    const rawFee = Number(String(form.elements.namedItem("owner_fee").value || "0").replace(",", "."));
    const fee = Number.isFinite(rawFee) ? Math.max(0, Math.round(rawFee * 100)) : 0;
    const rawCommission = fee * Number(config.commissionRateBps || 0) / 10000;
    const base = Math.floor(rawCommission);
    const cents = rawCommission - base === 0.5 ? base + (base % 2) : Math.round(rawCommission);
    const output = form.querySelector("[data-vpm-commission]");
    if (output) output.textContent = new Intl.NumberFormat("fr-MA", { maximumFractionDigits: 2 }).format(cents / 100);
    const duration = form.querySelector("[data-vpm-duration]");
    const days = daily ? config.dailyDurationDays : config.monthlyDurationDays;
    if (duration && days) duration.textContent = "Annonce diffusée pendant " + days + " jours.";
  }

  function renderPhotos() {
    const grid = document.getElementById("vpmImagePreviews");
    grid.querySelectorAll(".vpm-image-preview").forEach((node) => node.remove());
    const add = form.querySelector("[data-vpm-add-images]");
    photos.forEach((entry, index) => {
      const tile = document.createElement("div");
      tile.className = "vpm-image-preview";
      const image = document.createElement("img");
      image.src = entry.url;
      image.alt = entry.file.name;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.dataset.vpmRemoveImage = String(index);
      remove.setAttribute("aria-label", "Retirer la photo " + (index + 1));
      tile.append(image, remove);
      if (add.parentElement === grid) grid.insertBefore(tile, add);
      else grid.appendChild(tile);
    });
    const count = photos.length + keptImageCount();
    document.getElementById("vpmImageCount").textContent = count + " / " + config.maxImages;
    add.hidden = count >= config.maxImages;
    form.querySelectorAll('[name="delete_images"]').forEach((field) => field.closest(".vpm-existing-image")?.classList.toggle("is-removed", field.checked));
  }

  function keptImageCount() {
    const removed = new Set(Array.from(form.querySelectorAll('[name="delete_images"]:checked'), (field) => String(field.value)));
    return (config.existingImages || []).filter((entry) => !removed.has(String(entry.id))).length;
  }

  function addPhotos(files) {
    clearFieldError("images");
    let message = "";
    for (const file of Array.from(files || [])) {
      const duplicate = photos.some((entry) => entry.file.name === file.name && entry.file.size === file.size && entry.file.lastModified === file.lastModified);
      if (duplicate) continue;
      if (!/\.(jpe?g|png|webp)$/i.test(file.name) || (file.type && !/^image\/(jpeg|png|webp)$/i.test(file.type))) message = "Choisissez une photo JPG, PNG ou WebP.";
      else if (!file.size) message = "Cette photo est vide. Choisissez un autre fichier.";
      else if (photos.length + keptImageCount() >= config.maxImages) message = "Vous pouvez conserver jusqu’à " + config.maxImages + " photos. Retirez une photo avant d’en ajouter une autre.";
      else if (config.maxImageBytes && file.size > config.maxImageBytes) message = "Chaque photo doit faire moins de " + Math.round(config.maxImageBytes / 1024 / 1024) + " Mo.";
      else if (photos.reduce((sum, entry) => sum + entry.file.size, file.size) > config.maxTotalBytes) message = "Les photos doivent faire moins de 15 Mo au total.";
      else photos.push({ file, url: URL.createObjectURL(file) });
    }
    form.querySelector("#vpmImages").value = "";
    renderPhotos();
    if (message) fieldError("images", message);
  }

  function setVideo(file) {
    clearFieldError("video");
    if (file && (!/\.(mp4|mov|webm|m4v|avi|mkv|3gp|mpeg|mpg|wmv|flv)$/i.test(file.name) || file.size > config.maxVideoBytes)) {
      fieldError("video", "Choisissez une vidéo de moins de " + config.maxVideoMB + " Mo (MP4, MOV ou WebM recommandé).");
      form.querySelector("#vpmVideo").value = "";
      return;
    }
    const preview = form.querySelector("#vpmVideoPreview");
    const player = preview.querySelector("video");
    player.pause();
    player.removeAttribute("src");
    if (video) URL.revokeObjectURL(video.url);
    video = file ? { file, url: URL.createObjectURL(file) } : null;
    if (video) player.src = video.url;
    player.load();
    preview.hidden = !video;
    form.querySelector("[data-vpm-add-video]").hidden = !!video;
    form.querySelector(".vpm-existing-video")?.classList.toggle("is-replaced", !!video);
    form.querySelector("#vpmVideo").value = "";
  }

  function bindForm() {
    form = content.querySelector("#vendorCreateForm");
    const cfgNode = content.querySelector("#vpmFormConfig");
    if (!form || !cfgNode) throw new Error("invalid_form");
    config = JSON.parse(cfgNode.textContent);
    config = Object.assign({ maxImages: 4, maxTotalBytes: createType === "location" ? Infinity : 15 * 1024 * 1024, maxVideoBytes: 30 * 1024 * 1024, maxVideoMB: 30 }, config);
    formMode = config.mode === "edit" ? "edit" : "create";
    createType = config.formType === "location" ? "location" : "product";
    headers["X-Vendor-Modal"] = createType + "-" + formMode;
    dialog.classList.add("vpm-enhanced");
    form.noValidate = true;
    if (createType === "location") {
      title.textContent = formMode === "edit" ? "Modifier la location" : "Nouvelle location";
      ["rent", "deposit", "owner_fee"].forEach((name) => { form.elements.namedItem(name).max = "21474836.47"; });
      syncLocation();
    } else {
      form.elements.namedItem("name").maxLength = 150;
      form.elements.namedItem("price").max = "21474836.47";
      form.elements.namedItem("stock").max = "2147483647";
      categoryMemory.physical = "";
      categoryMemory.service = "";
      categoryMemory[currentKind()] = form.elements.namedItem("category_id").value;
      if (formMode === "create" && preferredKind) {
        const kindField = form.querySelector('[name="kind"][value="' + preferredKind + '"]');
        if (kindField && !kindField.disabled && kindField.type === "radio") kindField.checked = true;
      }
      syncKind();
    }
    renderPhotos();
    submitLabel.textContent = saveLabel();
    initialValues = signature();
    form.addEventListener("change", (event) => {
      const field = event.target;
      if (field.name === "kind") syncKind(form.dataset.kind);
      if (createType === "location" && ["listing_type", "deposit_required"].includes(field.name)) syncLocation();
      if (field.id === "vpmImages") addPhotos(field.files);
      if (field.id === "vpmVideo") setVideo(field.files?.[0]);
      if (field.name === "delete_images") renderPhotos();
      if (field.name === "delete_video") field.closest(".vpm-existing-video")?.classList.toggle("is-removed", field.checked);
    });
    form.addEventListener("input", (event) => {
      clearFieldError(event.target.name);
      if (createType === "location" && event.target.name === "owner_fee") syncLocation();
    });
    form.addEventListener("submit", saveOffer);
    submit.disabled = false;
  }

  async function loadForm() {
    const seq = ++requestSeq;
    if (loader) loader.abort();
    loader = new AbortController();
    const timeout = window.setTimeout(() => loader?.abort(), 20000);
    content.classList.add("vpm-load-state");
    content.textContent = "Chargement du formulaire…";
    submit.disabled = true;
    setStatus("");
    try {
      const response = await fetch(formUrl(), { headers, credentials: "same-origin", cache: "no-store", signal: loader.signal });
      const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
      if (seq !== requestSeq || phase === "closed" || phase === "closing") return;
      if (!response.ok || !data?.success || typeof data.html !== "string") {
        showError(data?.message || "Le formulaire est indisponible. Vérifiez votre connexion ou votre session.", data?.redirect_url || (response.redirected ? response.url : null));
        return;
      }
      content.classList.remove("vpm-load-state");
      content.innerHTML = data.html;
      bindForm();
    } catch (_error) {
      if (seq === requestSeq && phase !== "closed" && phase !== "closing") showError("Impossible de charger le formulaire. Vérifiez votre connexion puis réessayez.");
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function openDialog(trigger, pushHistory, type = createType, targetUrl = null, defaultKind = null) {
    const requestedKind = trigger?.dataset.vendorDefaultKind || defaultKind;
    if (phase === "closing") { reopenAfterClose = { type, url: targetUrl, kind: requestedKind }; return; }
    if (phase !== "closed") return;
    createType = type === "location" ? "location" : "product";
    editUrl = targetUrl ? editTarget(targetUrl, createType) : null;
    formMode = editUrl ? "edit" : "create";
    preferredKind = createType === "product" && formMode === "create" && ["physical", "service"].includes(requestedKind) ? requestedKind : null;
    headers["X-Vendor-Modal"] = createType + "-" + formMode;
    dialog.dataset.activeType = createType;
    dialog.querySelectorAll("[data-vpm-icon]").forEach((node) => { node.hidden = node.dataset.vpmIcon !== createType; });
    title.textContent = formMode === "edit" ? (createType === "location" ? "Modifier la location" : "Modifier le produit") : (createType === "location" ? "Nouvelle location" : "Ajouter un produit");
    submitLabel.textContent = saveLabel();
    opener = trigger || document.activeElement;
    phase = "open";
    updateViewport();
    // Read the viewport before entering: keyboard/toolbar events cannot resize a moving sheet.
    const viewport = window.visualViewport;
    dialog.style.setProperty("--vpm-viewport-height", Math.round(viewport?.height || window.innerHeight) + "px");
    dialog.style.setProperty("--vpm-viewport-top", Math.round(viewport?.offsetTop || 0) + "px");
    lockPage();
    setStatus("");
    progressWrap.hidden = true;
    dialog.classList.add("is-entering");
    dialog.showModal();
    phase = "opening";
    dialog.querySelector("[data-vpm-close]").focus({ preventScroll: true });
    if (pushHistory) {
      const url = new URL(window.location.href);
      ["new", "edit_product", "edit_location"].forEach((key) => url.searchParams.delete(key));
      if (editUrl) url.searchParams.set("edit_" + createType, new URL(editUrl).pathname.match(/\/(\d+)\/edit$/)[1]);
      else url.searchParams.set("new", createType);
      const state = editUrl ? { type: createType, url: editUrl } : preferredKind ? { type: createType, kind: preferredKind } : createType;
      window.history.pushState(Object.assign({}, window.history.state, { [historyKey]: state }), "", url);
    }
    document.dispatchEvent(new CustomEvent("vendor:form-opened", { detail: { formType: createType } }));
    afterMotion(() => {
      if (phase !== "opening") return;
      dialog.classList.remove("is-entering");
      phase = "open";
      updateViewport();
    });
    loadForm();
  }

  function validateForm() {
    let first = null;
    form.querySelector("#vpmFormError").hidden = true;
    form.querySelectorAll("[data-vpm-field-error]").forEach((node) => clearFieldError(node.dataset.vpmFieldError));
    Array.from(form.elements).forEach((field) => {
      if (!field.willValidate) return;
      let message = "";
      if (field.validity.valueMissing) message = "Ce champ est obligatoire.";
      else if (field.validity.rangeUnderflow || field.validity.badInput || field.validity.stepMismatch) message = field.name === "stock" ? "Indiquez un stock entier supérieur ou égal à 0." : createType === "location" ? "Indiquez un montant positif ou nul, avec deux décimales maximum." : "Indiquez un prix supérieur à 0, avec deux décimales maximum.";
      else if (!field.validity.valid) message = "Vérifiez ce champ.";
      if (field.name === "name" && !field.value.trim()) message = "Indiquez le nom de votre offre.";
      if (field.name === "title" && field.value.trim().length < 6) message = "Saisissez un titre d’au moins 6 caractères.";
      if (field.name === "city" && !field.value.trim()) message = "Indiquez la ville du bien.";
      if (message) { fieldError(field.name, message); if (!first) first = field; }
    });
    if (photos.length + keptImageCount() > config.maxImages) {
      fieldError("images", "Conservez au maximum " + config.maxImages + " photos.");
      if (!first) first = form.querySelector('[name="delete_images"], [data-vpm-add-images]');
    }
    if (first) first.focus();
    return !first;
  }

  function saveLabel() {
    return formMode === "edit" ? "Enregistrer" : createType === "location" ? "Publier l’annonce" : "Enregistrer";
  }

  function setBusy(active) {
    busy = active;
    if (active) {
      disabledControls = Array.from(form.querySelectorAll("input, select, textarea, button")).map((node) => [node, node.disabled]);
      disabledControls.forEach(([node]) => { node.disabled = true; });
    } else {
      disabledControls.forEach(([node, disabled]) => { node.disabled = disabled; });
      disabledControls = [];
    }
    form.setAttribute("aria-busy", String(active));
    dialog.querySelectorAll("[data-vpm-close]").forEach((node) => { node.disabled = active; });
    submit.disabled = active;
    submitLabel.textContent = active ? "Enregistrement…" : saveLabel();
    progressWrap.hidden = !active;
    if (active) progress.removeAttribute("value");
  }

  async function refreshSession(button) {
    if (busy || !form) return;
    button.disabled = true;
    const currentForm = form;
    try {
      const response = await fetch(formUrl(), { headers, credentials: "same-origin", cache: "no-store" });
      const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
      if (form !== currentForm || (!standalone && !dialog.open) || phase === "closing") return;
      const parsed = data?.html ? new DOMParser().parseFromString(data.html, "text/html") : null;
      const token = parsed?.querySelector('[name="csrf_token"]')?.value;
      if (!response.ok || !data?.success || !token) {
        showError(data?.message || "Connectez-vous de nouveau pour continuer. Votre saisie est conservée.", data?.redirect_url);
        return;
      }
      form.elements.namedItem("csrf_token").value = token;
      document.querySelectorAll('input[name="csrf_token"]').forEach((node) => { node.value = token; });
      const csrfMeta = document.querySelector('meta[name="csrf-token"]');
      if (csrfMeta) csrfMeta.content = token;
      form.querySelector("#vpmFormError").hidden = true;
      setStatus("Session actualisée. Vous pouvez réessayer d’enregistrer.");
    } catch (_error) {
      if (form === currentForm && (standalone || dialog.open)) showError("Impossible d’actualiser la session. Vérifiez votre connexion ; votre saisie est conservée.");
    } finally {
      if (button.isConnected) button.disabled = false;
    }
  }

  function saveOffer(event) {
    event.preventDefault();
    if (busy || !validateForm()) return;
    if (navigator.onLine === false) { showError("Vous êtes hors ligne. Votre saisie est conservée ; reconnectez-vous pour enregistrer."); return; }
    const body = new FormData(form);
    body.delete("images");
    body.delete("video");
    photos.forEach((entry) => body.append("images", entry.file, entry.file.name));
    if (video) body.append("video", video.file, video.file.name);
    if (createType === "product" && currentKind() === "service") body.set("stock", "0");
    const uploadBytes = photos.reduce((sum, entry) => sum + entry.file.size, video?.file.size || 0);
    if (config.maxRequestBytes && uploadBytes + 65536 > config.maxRequestBytes) {
      showError("L’ensemble des fichiers dépasse la limite de " + Math.floor(config.maxRequestBytes / 1024 / 1024) + " Mo. Réduisez leur taille avant de publier.");
      return;
    }
    setBusy(true);
    setStatus("Envoi en cours…");
    const xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.timeout = 180000;
    Object.entries(headers).forEach(([key, value]) => xhr.setRequestHeader(key, value));
    const token = body.get("csrf_token");
    if (token) xhr.setRequestHeader("X-CSRFToken", token);
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      const percent = Math.min(100, Math.round(event.loaded * 100 / event.total));
      progress.value = percent;
      setStatus(percent < 100 ? "Envoi des fichiers… " + percent + " %" : "Enregistrement en cours…");
    };
    let settled = false;
    function finish() {
      if (settled) return false;
      settled = true;
      setBusy(false);
      setStatus("");
      return true;
    }
    xhr.onload = () => {
      if (!finish()) return;
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch (_error) { /* Non-JSON includes expired sessions and upload limits. */ }
      if (xhr.status >= 200 && xhr.status < 300 && data?.success && (createType === "location" ? data.listing : data.product)) {
        initialValues = signature();
        confirmedLeave = true;
        if ("serviceWorker" in navigator && navigator.serviceWorker.controller) {
          try {
            navigator.serviceWorker.controller.postMessage({ type: "BM_CLEAR_PUBLIC_PAGE_CACHE" });
          } catch (_e) {}
        }
        if (standalone) { window.location.assign(safeLink(dialog.dataset.backUrl) || "/vendor/dashboard"); return; }
        document.dispatchEvent(new CustomEvent("vendor:" + createType + (formMode === "edit" ? "-updated" : "-created"), { detail: data }));
        closeDialog(true);
        const message = [data.message || (formMode === "edit" ? "Modifications enregistrées." : "Offre créée."), ...(data.notices || [])].join(" ");
        if (typeof window.BMTriggerHaptic === "function") window.BMTriggerHaptic("heavy");
        if (window.VendorUI?.toast) window.VendorUI.toast(message, "success");
        else window.BMCoreUI?.showToast?.(message, "success");
        return;
      }
      let message = data?.message;
      if (!message) message = xhr.status === 413 ? "Les fichiers sont trop volumineux. Réduisez leur taille puis réessayez." : "La session ou la connexion a été interrompue. Votre saisie est conservée. Vérifiez votre session avant de réessayer.";
      showError(message, data?.redirect_url);
      if (xhr.status === 400 && !data) {
        const refresh = document.createElement("button");
        refresh.type = "button";
        refresh.className = "vpm-button vpm-button-secondary";
        refresh.dataset.vpmRefreshSession = "1";
        refresh.textContent = "Actualiser la session";
        form.querySelector("#vpmFormError").appendChild(refresh);
      }
      let first = null;
      Object.entries(data?.errors || {}).forEach(([name, error]) => {
        fieldError(name, String(error));
        const field = form.elements.namedItem(name);
        if (!first && field instanceof HTMLElement && field.type !== "file") first = field;
      });
      if (first) first.focus();
      else form.querySelector("#vpmFormError").scrollIntoView({ block: "nearest" });
    };
    xhr.onerror = xhr.ontimeout = xhr.onabort = () => {
      if (!finish()) return;
      showError("La connexion a été interrompue. Votre saisie est conservée. Vérifiez vos annonces avant de réessayer pour éviter un doublon.", createType === "location" ? "/owner/locations" : "/vendor/catalog");
    };
    xhr.send(body);
  }

  document.addEventListener("click", (event) => {
    if (standalone) return;
    const trigger = event.target.closest?.(triggers);
    if (!trigger || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    const type = trigger.hasAttribute("data-vendor-location-create") || trigger.hasAttribute("data-vendor-location-edit") ? "location" : "product";
    const target = trigger.hasAttribute("data-vendor-" + type + "-edit") ? editTarget(trigger.href, type) : null;
    if (trigger.hasAttribute("data-vendor-" + type + "-edit") && !target) return;
    event.preventDefault();
    event.stopPropagation();
    openDialog(trigger, true, type, target);
  }, true);

  dialog.addEventListener("pointerdown", (event) => {
    // Avoid blurring the mobile keyboard before closing, which moves the close target.
    if (event.pointerType === "touch" && event.target.closest("[data-vpm-close], [data-vpm-submit], [data-vpm-keep], [data-vpm-discard]")) event.preventDefault();
  });
  dialog.addEventListener("click", (event) => {
    const target = event.target;
    if (target.closest("[data-vpm-close]")) requestClose();
    else if (target.closest("[data-vpm-keep]")) setConfirm(false);
    else if (target.closest("[data-vpm-discard]")) { confirmedLeave = true; closeDialog(true); }
    else if (target.closest("[data-vpm-retry]")) loadForm();
    else if (target.closest("[data-vpm-refresh-session]")) refreshSession(target.closest("[data-vpm-refresh-session]"));
    else if (target.closest("[data-vpm-add-images]")) form.querySelector("#vpmImages").click();
    else if (target.closest("[data-vpm-add-video]")) form.querySelector("#vpmVideo").click();
    else if (target.closest("[data-vpm-remove-video]")) setVideo(null);
    else if (target.closest("[data-vpm-remove-image]")) {
      const index = Number(target.closest("[data-vpm-remove-image]").dataset.vpmRemoveImage);
      const entry = photos.splice(index, 1)[0];
      if (entry) URL.revokeObjectURL(entry.url);
      clearFieldError("images");
      renderPhotos();
      form.querySelector("[data-vpm-add-images]").focus({ preventScroll: true });
    }
    // Backdrop clicks deliberately keep a form open to prevent accidental data loss.
  });
  dialog.addEventListener("cancel", (event) => {
    if (standalone) return;
    event.preventDefault();
    if (!confirm.hidden) setConfirm(false);
    else requestClose();
  });
  dialog.addEventListener("keydown", (event) => {
    if (standalone || event.key !== "Tab" || confirm.hidden) return;
    const buttons = Array.from(confirm.querySelectorAll("button"));
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  window.addEventListener("popstate", () => {
    if (standalone) return;
    const shouldOpen = !!window.history.state?.[historyKey];
    if (shouldOpen) {
      restoringHistory = false;
      if (closeWhenHistoryRestored) {
        closeWhenHistoryRestored = false;
        closeDialog(true);
        return;
      }
      const saved = window.history.state[historyKey];
      const type = saved === "location" || saved?.type === "location" ? "location" : "product";
      const url = typeof saved === "object" ? editTarget(saved.url, type) : null;
      if (phase === "closed") openDialog(null, false, type, url, saved?.kind);
      else if (phase === "closing") reopenAfterClose = { type, url, kind: saved?.kind };
      return;
    }
    if (phase === "closed" || phase === "closing") return;
    if (!confirmedLeave && (busy || isDirty())) {
      if (restoringHistory) return;
      restoringHistory = true;
      window.history.forward();
      if (!busy) setConfirm(true);
      return;
    }
    closeDialog(false);
  });
  window.addEventListener("beforeunload", (event) => {
    if ((!standalone && !dialog.open) || confirmedLeave || (!busy && !isDirty())) return;
    event.preventDefault();
    event.returnValue = "";
  });
  window.addEventListener("resize", scheduleViewport, { passive: true });
  window.visualViewport?.addEventListener("resize", scheduleViewport, { passive: true });
  window.visualViewport?.addEventListener("scroll", scheduleViewport, { passive: true });
  if (standalone) {
    editUrl = content.querySelector("form")?.action;
    bindForm();
    return;
  }
  const initialUrl = new URL(window.location.href);
  const initial = requestedForm(initialUrl);
  if (initial) {
    if (window.history.state?.[historyKey]) openDialog(null, false, initial.type, initial.url, window.history.state[historyKey]?.kind);
    else {
      ["new", "edit_product", "edit_location"].forEach((key) => initialUrl.searchParams.delete(key));
      window.history.replaceState(window.history.state, "", initialUrl);
      openDialog(null, true, initial.type, initial.url);
    }
  }
})();
