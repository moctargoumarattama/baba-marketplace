(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_VENDOR_PRODUCT_FORM_PAGE_INIT__) return;
  window.__BM_VENDOR_PRODUCT_FORM_PAGE_INIT__ = true;

  const CONFIG_ID = "vendorProductFormPageConfig";
  const defaults = {
    maxImages: 4,
    maxTotalBytes: 15 * 1024 * 1024,
    maxVideoBytes: 30 * 1024 * 1024,
    categoriesByKind: {
      physical: [],
      service: [],
    },
  };

  const VendorUI = window.VendorUI || {};

  function fallbackParseConfig(nodeId, fallback) {
    const node = document.getElementById(String(nodeId || ""));
    if (!node) return fallback;
    try {
      const parsed = JSON.parse(node.textContent || "{}");
      if (!parsed || typeof parsed !== "object") return fallback;
      return Object.assign({}, fallback, parsed);
    } catch (_error) {
      return fallback;
    }
  }

  const parseConfig =
    typeof VendorUI.parsePageConfig === "function"
      ? VendorUI.parsePageConfig
      : fallbackParseConfig;

  const cfg = parseConfig(CONFIG_ID, defaults);

  const MAX_IMAGES = Math.max(1, Number(cfg.maxImages || defaults.maxImages));
  const MAX_TOTAL_BYTES = Math.max(1, Number(cfg.maxTotalBytes || defaults.maxTotalBytes));
  const MAX_VIDEO_BYTES = Math.max(1, Number(cfg.maxVideoBytes || defaults.maxVideoBytes));

  function normalizeCategoryRows(rows) {
    if (!Array.isArray(rows)) return [];
    return rows
      .map(function (entry) {
        if (!entry || typeof entry !== "object") return null;
        const id = entry.id;
        const name = String(entry.name || "").trim();
        if (id == null || !name) return null;
        return {
          id: String(id),
          name: name,
        };
      })
      .filter(Boolean);
  }

  const categoriesByKind = {
    physical: normalizeCategoryRows(cfg.categoriesByKind && cfg.categoriesByKind.physical),
    service: normalizeCategoryRows(cfg.categoriesByKind && cfg.categoriesByKind.service),
  };

  const form = document.getElementById("productForm");
  if (!form) return;

  const kindSelect = document.getElementById("kind");
  const kindHiddenInput = form.querySelector('input[name="kind"]');
  const stockGroup = document.getElementById("stockGroup");
  const stockInput = document.getElementById("stock");
  const stockRequired = document.getElementById("stockRequired");
  const categorySelect = document.getElementById("category");

  const input = document.getElementById("imagesInput");
  const videoInput = document.getElementById("videoInput");
  const previewGrid = document.getElementById("previewGrid");
  const previewContainer = document.getElementById("previewContainer");
  const clearBtn = document.getElementById("clearBtn");
  const newCount = document.getElementById("newCount");
  const dropZone = document.getElementById("dropZone");
  const uploadTrigger = document.getElementById("uploadTrigger");
  const removeImagesInput = document.getElementById("removeImagesInput");
  const existingCount = document.getElementById("existingCount");
  const existingCards = Array.from(document.querySelectorAll(".js-existing-image-card"));
  const mediaLightbox = document.getElementById("mediaLightbox");
  const mediaLightboxImage = document.getElementById("mediaLightboxImage");
  const mediaLightboxClose = document.getElementById("mediaLightboxClose");
  const mediaLightboxBackdrop = document.getElementById("mediaLightboxBackdrop");
  const videoDropZone = document.getElementById("videoDropZone");
  const videoUploadTrigger = document.getElementById("videoUploadTrigger");
  const videoPreviewContainer = document.getElementById("videoPreviewContainer");
  const videoPreviewGrid = document.getElementById("videoPreviewGrid");
  const clearVideoBtn = document.getElementById("clearVideoBtn");
  const newVideoCount = document.getElementById("newVideoCount");
  const removeVideoInput = document.getElementById("removeVideoInput");
  const existingVideoCard = document.querySelector(".js-existing-video-card");

  const removedExisting = new Set();
  let removedExistingVideo = false;
  let currentVideoPreviewUrl = "";
  const selectedCategoryByKind = {
    physical: "",
    service: "",
  };

  function createDataTransfer() {
    try {
      return new DataTransfer();
    } catch (_error) {
      return null;
    }
  }

  const dataTransfer = createDataTransfer();
  const videoDataTransfer = createDataTransfer();
  let fallbackFiles = [];
  let fallbackVideoFiles = [];

  function getCurrentKind() {
    if (kindSelect) return kindSelect.value === "service" ? "service" : "physical";
    if (kindHiddenInput) return kindHiddenInput.value === "service" ? "service" : "physical";
    return "physical";
  }

  function getNewFiles() {
    if (dataTransfer) return Array.from(dataTransfer.files);
    return fallbackFiles.slice();
  }

  function getNewVideoFiles() {
    if (videoDataTransfer) return Array.from(videoDataTransfer.files);
    return fallbackVideoFiles.slice();
  }

  function setNewFiles(files) {
    const safeFiles = Array.isArray(files) ? files.filter(Boolean) : [];

    if (dataTransfer) {
      while (dataTransfer.items.length) {
        dataTransfer.items.remove(0);
      }
      safeFiles.forEach(function (file) {
        dataTransfer.items.add(file);
      });
      if (input) {
        input.files = dataTransfer.files;
      }
    } else {
      fallbackFiles = safeFiles;
    }

    renderPreview();
  }

  function setNewVideoFiles(files) {
    const safeFiles = Array.isArray(files) ? files.filter(Boolean).slice(0, 1) : [];

    if (videoDataTransfer) {
      while (videoDataTransfer.items.length) {
        videoDataTransfer.items.remove(0);
      }
      safeFiles.forEach(function (file) {
        videoDataTransfer.items.add(file);
      });
      if (videoInput) {
        videoInput.files = videoDataTransfer.files;
      }
    } else {
      fallbackVideoFiles = safeFiles;
    }

    renderVideoPreview();
  }

  function formatBytes(value) {
    return (Number(value || 0) / (1024 * 1024)).toFixed(1) + " MB";
  }

  function getCurrentExistingCount() {
    return existingCards.length - removedExisting.size;
  }

  function getNewFilesBytes() {
    return getNewFiles().reduce(function (sum, file) {
      return sum + Number((file && file.size) || 0);
    }, 0);
  }

  function showUploadLimitMessage(message) {
    const text = String(message || "");
    if (!text) return;

    if (typeof VendorUI.toast === "function") {
      VendorUI.toast(text, "warning");
      return;
    }

    const coreUI = window.BMCoreUI || {};
    if (typeof coreUI.showToast === "function") {
      coreUI.showToast(text, "warning");
      return;
    }

    window.alert(text);
  }

  function markFieldInvalid(field) {
    if (!field) return;
    if (typeof VendorUI.markFieldInvalid === "function") {
      VendorUI.markFieldInvalid(field, { color: "var(--danger)", durationMs: 2000 });
      return;
    }

    field.style.borderColor = "var(--danger)";
    window.setTimeout(function () {
      field.style.borderColor = "";
    }, 2000);
  }

  function renderCategoryOptions(kind, keepSelected) {
    if (!categorySelect) return;

    const safeKind = kind === "service" ? "service" : "physical";
    const options = categoriesByKind[safeKind] || [];
    const previousSelected =
      selectedCategoryByKind[safeKind] ||
      (keepSelected ? categorySelect.value || categorySelect.dataset.selectedCategory || "" : "");

    categorySelect.innerHTML = "";

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = options.length
      ? "Selectionnez une categorie..."
      : "Aucune categorie disponible pour ce type";
    categorySelect.appendChild(placeholder);

    let matched = false;
    options.forEach(function (entry) {
      const option = document.createElement("option");
      option.value = String(entry.id);
      option.textContent = String(entry.name);
      if (previousSelected && option.value === String(previousSelected)) {
        option.selected = true;
        matched = true;
      }
      categorySelect.appendChild(option);
    });

    if (!matched) {
      categorySelect.value = "";
    }
    categorySelect.disabled = options.length === 0;
  }

  function syncKindUI() {
    const isService = getCurrentKind() === "service";

    if (stockGroup) stockGroup.style.display = isService ? "none" : "";
    if (stockRequired) stockRequired.style.display = isService ? "none" : "";

    if (stockInput) {
      stockInput.required = !isService;
      if (isService) stockInput.value = 0;
    }

    renderCategoryOptions(isService ? "service" : "physical", true);
  }

  function syncExistingRemovalUI() {
    if (removeImagesInput) {
      removeImagesInput.value = Array.from(removedExisting).join(",");
    }

    if (existingCount) {
      existingCount.textContent = String(getCurrentExistingCount());
    }

    existingCards.forEach(function (card) {
      const filename = String(card.dataset.filename || "");
      card.classList.toggle("marked-remove", removedExisting.has(filename));
    });

    if (removeVideoInput) {
      removeVideoInput.value = removedExistingVideo ? "1" : "";
    }
    if (existingVideoCard) {
      existingVideoCard.classList.toggle("marked-remove", removedExistingVideo);
    }
  }

  function removeFile(index) {
    const files = getNewFiles().filter(function (_file, fileIndex) {
      return fileIndex !== index;
    });
    setNewFiles(files);
  }

  function renderPreview() {
    if (!previewGrid || !previewContainer) return;

    const files = getNewFiles();
    previewGrid.innerHTML = "";

    if (!files.length) {
      previewContainer.style.display = "none";
      if (newCount) newCount.textContent = "0";
      return;
    }

    previewContainer.style.display = "block";
    if (newCount) newCount.textContent = String(files.length);

    files.forEach(function (file, index) {
      const card = document.createElement("div");
      card.className = "image-card";

      const img = document.createElement("img");
      img.alt = String(file && file.name ? file.name : "Image");

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "remove-btn";
      btn.textContent = "x";
      btn.title = "Retirer cette image";
      btn.addEventListener("click", function (event) {
        event.stopPropagation();
        removeFile(index);
      });

      card.appendChild(img);
      card.appendChild(btn);
      previewGrid.appendChild(card);

      const reader = new FileReader();
      reader.onload = function (event) {
        img.src = String((event && event.target && event.target.result) || "");
      };
      reader.readAsDataURL(file);
    });
  }

  function renderVideoPreview() {
    if (!videoPreviewGrid || !videoPreviewContainer) return;

    const files = getNewVideoFiles();
    videoPreviewGrid.innerHTML = "";
    if (currentVideoPreviewUrl) {
      URL.revokeObjectURL(currentVideoPreviewUrl);
      currentVideoPreviewUrl = "";
    }

    if (!files.length) {
      videoPreviewContainer.style.display = "none";
      if (newVideoCount) newVideoCount.textContent = "0";
      return;
    }

    const file = files[0];
    videoPreviewContainer.style.display = "block";
    if (newVideoCount) newVideoCount.textContent = "1";

    const card = document.createElement("div");
    card.className = "image-card video-preview-card";

    const frame = document.createElement("div");
    frame.className = "video-preview-frame";

    const video = document.createElement("video");
    video.controls = true;
    video.preload = "metadata";
    video.muted = true;
    video.playsInline = true;
    currentVideoPreviewUrl = URL.createObjectURL(file);
    video.src = currentVideoPreviewUrl;
    video.addEventListener("loadedmetadata", function () {
      try {
        const targetTime = Number.isFinite(video.duration) && video.duration > 0.15 ? 0.15 : 0;
        video.currentTime = targetTime;
      } catch (_error) {}
    });
    video.addEventListener(
      "seeked",
      function () {
        try {
          video.pause();
        } catch (_error) {}
      },
      { once: true }
    );

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "remove-btn";
    btn.textContent = "x";
    btn.title = "Retirer cette video";
    btn.addEventListener("click", function (event) {
      event.stopPropagation();
        setNewVideoFiles([]);
        if (videoInput) {
          videoInput.value = "";
        }
      });

    const meta = document.createElement("div");
    meta.className = "video-preview-meta";

    const title = document.createElement("div");
    title.className = "video-preview-title";
    title.textContent = String(file.name || "Video");

    const note = document.createElement("div");
    note.className = "video-preview-note";
    note.textContent =
      formatBytes(file.size) +
      " - " +
      String(file.type || "video").replace("video/", "").toUpperCase();

    video.addEventListener("error", function () {
      note.textContent = "Apercu limite pour ce format, mais l'envoi reste possible.";
    });

    frame.appendChild(video);
    meta.appendChild(title);
    meta.appendChild(note);
    card.appendChild(frame);
    card.appendChild(meta);
    card.appendChild(btn);
    videoPreviewGrid.appendChild(card);
    video.load();
  }

  function openImageLightbox(src, altText) {
    if (!mediaLightbox || !mediaLightboxImage || !src) return;
    mediaLightboxImage.src = String(src);
    mediaLightboxImage.alt = String(altText || "Apercu");
    mediaLightbox.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeImageLightbox() {
    if (!mediaLightbox || !mediaLightboxImage) return;
    mediaLightbox.hidden = true;
    mediaLightboxImage.src = "";
    document.body.style.overflow = "";
  }

  function pushAcceptedFiles(fileList, replaceExisting) {
    const incoming = Array.from(fileList || []);
    if (!incoming.length) return;

    const accepted = replaceExisting ? [] : getNewFiles();
    let nextCount = getCurrentExistingCount() + accepted.length;
    let nextBytes = getNewFilesBytes();
    if (replaceExisting) {
      nextBytes = 0;
    }

    for (const file of incoming) {
      if (!file || !String(file.type || "").startsWith("image/")) {
        showUploadLimitMessage("Format non supporte. Utilisez une image (png, jpg, jpeg, webp).");
        continue;
      }

      if (nextCount >= MAX_IMAGES) {
        showUploadLimitMessage("Maximum " + String(MAX_IMAGES) + " photos au total.");
        break;
      }

      const size = Number(file.size || 0);
      if (nextBytes + size > MAX_TOTAL_BYTES) {
        showUploadLimitMessage("Taille totale depassee (" + formatBytes(MAX_TOTAL_BYTES) + " max).");
        break;
      }

      accepted.push(file);
      nextCount += 1;
      nextBytes += size;
    }

    setNewFiles(accepted);
  }

  function bindDropZone() {
    if (!dropZone) return;

    function preventDefaults(event) {
      event.preventDefault();
      event.stopPropagation();
    }

    ["dragenter", "dragover", "dragleave", "drop"].forEach(function (eventName) {
      dropZone.addEventListener(eventName, preventDefaults, false);
      document.body.addEventListener(eventName, preventDefaults, false);
    });

    ["dragenter", "dragover"].forEach(function (eventName) {
      dropZone.addEventListener(
        eventName,
        function () {
          dropZone.classList.add("dragover");
        },
        false
      );
    });

    ["dragleave", "drop"].forEach(function (eventName) {
      dropZone.addEventListener(
        eventName,
        function () {
          dropZone.classList.remove("dragover");
        },
        false
      );
    });

    dropZone.addEventListener(
      "drop",
      function (event) {
        const dtFiles = event.dataTransfer && event.dataTransfer.files;
        if (!dtFiles || !dtFiles.length) return;
        if (!dataTransfer) {
          showUploadLimitMessage("Glisser-deposer non supporte sur ce navigateur. Utilisez 'Choisir des fichiers'.");
          return;
        }
        pushAcceptedFiles(dtFiles);
      },
      false
    );
  }

  function pushAcceptedVideo(file) {
    if (!file) return;

    if (!String(file.type || "").startsWith("video/")) {
      showUploadLimitMessage("Format non supporte. Utilisez un fichier video.");
      return;
    }

    const size = Number(file.size || 0);
    if (size > MAX_VIDEO_BYTES) {
      showUploadLimitMessage("Video trop lourde (" + formatBytes(MAX_VIDEO_BYTES) + " max).");
      return;
    }

    setNewVideoFiles([file]);
  }

  function bindVideoDropZone() {
    if (!videoDropZone) return;

    function preventDefaults(event) {
      event.preventDefault();
      event.stopPropagation();
    }

    ["dragenter", "dragover", "dragleave", "drop"].forEach(function (eventName) {
      videoDropZone.addEventListener(eventName, preventDefaults, false);
    });

    ["dragenter", "dragover"].forEach(function (eventName) {
      videoDropZone.addEventListener(eventName, function () {
        videoDropZone.classList.add("dragover");
      });
    });

    ["dragleave", "drop"].forEach(function (eventName) {
      videoDropZone.addEventListener(eventName, function () {
        videoDropZone.classList.remove("dragover");
      });
    });

    videoDropZone.addEventListener("drop", function (event) {
      const dtFiles = event.dataTransfer && event.dataTransfer.files;
      if (!dtFiles || !dtFiles.length) return;
      if (!videoDataTransfer) {
        showUploadLimitMessage("Glisser-deposer non supporte sur ce navigateur. Utilisez 'Choisir une video'.");
        return;
      }
      pushAcceptedVideo(dtFiles[0]);
    });
  }

  function bindFormValidation() {
    form.addEventListener("submit", function (event) {
      const category = document.getElementById("category");
      const name = document.getElementById("name");
      const price = document.getElementById("price");
      const totalImages = getCurrentExistingCount() + getNewFiles().length;
      const totalBytes = getNewFilesBytes();
      const newVideoFiles = getNewVideoFiles();

      if (category && !category.value) {
        event.preventDefault();
        category.focus();
        markFieldInvalid(category);
        return;
      }

      if (name && !String(name.value || "").trim()) {
        event.preventDefault();
        name.focus();
        markFieldInvalid(name);
        return;
      }

      const priceValue = Number(price && price.value ? price.value : 0);
      if (!price || !price.value || !Number.isFinite(priceValue) || priceValue <= 0) {
        event.preventDefault();
        if (price) {
          price.focus();
          markFieldInvalid(price);
        }
        return;
      }

      if (totalImages > MAX_IMAGES) {
        event.preventDefault();
        showUploadLimitMessage("Maximum " + String(MAX_IMAGES) + " photos au total.");
        return;
      }

      if (totalBytes > MAX_TOTAL_BYTES) {
        event.preventDefault();
        showUploadLimitMessage("Taille totale depassee (" + formatBytes(MAX_TOTAL_BYTES) + " max).");
        return;
      }

      if (newVideoFiles.length > 1) {
        event.preventDefault();
        showUploadLimitMessage("Une seule video est autorisee.");
        return;
      }

      if (newVideoFiles[0] && Number(newVideoFiles[0].size || 0) > MAX_VIDEO_BYTES) {
        event.preventDefault();
        showUploadLimitMessage("Video trop lourde (" + formatBytes(MAX_VIDEO_BYTES) + " max).");
      }
    });
  }

  function initKindCategoryBinding() {
    if (kindSelect) {
      kindSelect.addEventListener("change", syncKindUI);
    }

    if (categorySelect) {
      const initialKind = getCurrentKind();
      const initialSelectedCategory = String(categorySelect.dataset.selectedCategory || "");
      if (initialSelectedCategory) {
        selectedCategoryByKind[initialKind] = initialSelectedCategory;
      }

      categorySelect.addEventListener("change", function () {
        selectedCategoryByKind[getCurrentKind()] = categorySelect.value || "";
      });
    }

    syncKindUI();
  }

  function bindUploadInput() {
    if (!input) return;

    input.addEventListener("change", function () {
      pushAcceptedFiles(input.files, !dataTransfer);
      if (dataTransfer) {
        input.files = dataTransfer.files;
      }
    });

    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        setNewFiles([]);
        input.value = "";
      });
    }

    if (uploadTrigger) {
      uploadTrigger.addEventListener("click", function (event) {
        if (!event.target.closest(".btn-upload")) return;
        event.preventDefault();
        input.click();
      });
    }
  }

  function bindVideoInput() {
    if (!videoInput) return;

    videoInput.addEventListener("change", function () {
      const file = videoInput.files && videoInput.files[0];
      if (!file) {
        setNewVideoFiles([]);
        return;
      }
      pushAcceptedVideo(file);
      if (videoDataTransfer) {
        videoInput.files = videoDataTransfer.files;
      }
    });

    if (clearVideoBtn) {
      clearVideoBtn.addEventListener("click", function () {
        setNewVideoFiles([]);
        videoInput.value = "";
      });
    }

    if (videoUploadTrigger) {
      videoUploadTrigger.addEventListener("click", function (event) {
        if (!event.target.closest(".btn-upload")) return;
        event.preventDefault();
        videoInput.click();
      });
    }
  }

  function bindExistingImageToggles() {
    document.querySelectorAll(".js-remove-existing").forEach(function (button) {
      button.addEventListener("click", function (event) {
        event.preventDefault();

        const card = button.closest(".js-existing-image-card");
        if (!card) return;

        const filename = String(card.dataset.filename || "");
        if (!filename) return;

        if (removedExisting.has(filename)) {
          removedExisting.delete(filename);
        } else {
          removedExisting.add(filename);
        }

        syncExistingRemovalUI();
      });
    });

    syncExistingRemovalUI();
  }

  function bindImageLightbox() {
    document.querySelectorAll(".media-preview-link").forEach(function (link) {
      link.addEventListener("click", function (event) {
        event.preventDefault();
        openImageLightbox(link.href, link.querySelector("img")?.alt || "Image");
      });
    });

    if (mediaLightboxClose) {
      mediaLightboxClose.addEventListener("click", closeImageLightbox);
    }

    if (mediaLightboxBackdrop) {
      mediaLightboxBackdrop.addEventListener("click", closeImageLightbox);
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && mediaLightbox && !mediaLightbox.hidden) {
        closeImageLightbox();
      }
    });
  }

  function bindExistingVideoToggle() {
    const button = document.querySelector(".js-remove-existing-video");
    if (!button) {
      syncExistingRemovalUI();
      return;
    }

    button.addEventListener("click", function (event) {
      event.preventDefault();
      removedExistingVideo = !removedExistingVideo;
      syncExistingRemovalUI();
    });
  }

  initKindCategoryBinding();
  bindDropZone();
  bindVideoDropZone();
  bindUploadInput();
  bindVideoInput();
  bindExistingImageToggles();
  bindImageLightbox();
  bindExistingVideoToggle();
  bindFormValidation();
  renderPreview();
  renderVideoPreview();
  window.addEventListener("beforeunload", function () {
    if (currentVideoPreviewUrl) {
      URL.revokeObjectURL(currentVideoPreviewUrl);
      currentVideoPreviewUrl = "";
    }
  });
})();

