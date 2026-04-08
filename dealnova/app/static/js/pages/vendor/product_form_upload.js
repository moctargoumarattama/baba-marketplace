(function () {
    "use strict";

    if (typeof window === "undefined" || typeof document === "undefined") return;
    if (window.__PRODUCT_FORM_UPLOAD_INIT__) return;
    window.__PRODUCT_FORM_UPLOAD_INIT__ = true;

    var isSubmitting = false;

    function getForm() {
        return document.getElementById("productForm");
    }

    function getSubmitButton(form) {
        return form ? form.querySelector('button[type="submit"]') : null;
    }

    function showOfflineNotice() {
        var message = "Vous etes hors ligne. Verifiez votre connexion avant d'envoyer votre produit.";
        if (window.BMCoreUI && typeof window.BMCoreUI.showToast === "function") {
            window.BMCoreUI.showToast(message, "warning");
            return;
        }
        window.alert(message);
    }

    function ensureOverlay() {
        var existing = document.getElementById("r-uploadOverlay");
        if (existing) return existing;

        var overlay = document.createElement("div");
        overlay.className = "r-upload-overlay";
        overlay.id = "r-uploadOverlay";
        overlay.setAttribute("hidden", "");
        overlay.innerHTML =
            '<div class="r-upload-modal" role="status" aria-live="polite" aria-label="Enregistrement en cours">' +
                '<div class="r-upload-kicker">Publication</div>' +
                '<h3 class="r-upload-title">Enregistrement en cours</h3>' +
                '<p class="r-upload-copy">Vos fichiers sont en train d\'etre envoyes. Gardez cette page ouverte quelques instants.</p>' +
                '<div class="r-upload-spinner"></div>' +
                '<div class="r-progress-bar-container" aria-hidden="true">' +
                    '<div class="r-progress-bar-fill is-indeterminate"></div>' +
                "</div>" +
            "</div>";
        document.body.appendChild(overlay);
        return overlay;
    }

    function showUploadOverlay() {
        var overlay = ensureOverlay();
        overlay.removeAttribute("hidden");
        document.body.classList.add("r-upload-active");
    }

    function hideUploadOverlay() {
        var overlay = document.getElementById("r-uploadOverlay");
        if (overlay) overlay.setAttribute("hidden", "");
        document.body.classList.remove("r-upload-active");
    }

    function disableSubmitButton(btn) {
        if (!btn) return;
        btn.disabled = true;
        btn.classList.add("r-btn-loading");
        if (!btn.dataset.originalHtml) {
            btn.dataset.originalHtml = btn.innerHTML;
        }
        btn.innerHTML = '<span class="r-spinner"></span> Enregistrement...';
    }

    function enableSubmitButton(btn) {
        if (!btn) return;
        btn.disabled = false;
        btn.classList.remove("r-btn-loading");
        if (btn.dataset.originalHtml) {
            btn.innerHTML = btn.dataset.originalHtml;
        }
    }

    function attachToForm(form) {
        if (!form || form.dataset.rUploadAttached === "true") return;
        form.dataset.rUploadAttached = "true";

        var submitBtn = getSubmitButton(form);
        if (!submitBtn) return;

        form.addEventListener("submit", function (event) {
            if (event.defaultPrevented) return;

            if (isSubmitting) {
                event.preventDefault();
                return;
            }

            if (navigator.onLine === false) {
                event.preventDefault();
                showOfflineNotice();
                return;
            }

            isSubmitting = true;
            disableSubmitButton(submitBtn);
            showUploadOverlay();
        });
    }

    function restoreUIState() {
        isSubmitting = false;
        hideUploadOverlay();
        enableSubmitButton(getSubmitButton(getForm()));
    }

    function init() {
        attachToForm(getForm());

        window.addEventListener("pageshow", restoreUIState);
        window.addEventListener("offline", restoreUIState);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
        return;
    }

    init();
})();
