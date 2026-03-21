// static/js/pages/vendor/product_form_upload.js
(function() {
    'use strict';

    if (window.__PRODUCT_FORM_UPLOAD_INIT__) return;
    window.__PRODUCT_FORM_UPLOAD_INIT__ = true;

    const CONFIG = {
        timeoutMs: 30000,
        debug: false
    };

    let uploadController = null;
    let currentForm = null;
    let currentSubmitBtn = null;
    let pendingRedirectUrl = '';

    function log(...args) {
        if (CONFIG.debug) {
            console.log('[ProductUpload]', ...args);
        }
    }

    function showUploadOverlay() {
        if (document.getElementById('r-uploadOverlay')) return;

        const overlay = document.createElement('div');
        overlay.className = 'r-upload-overlay';
        overlay.id = 'r-uploadOverlay';
        overlay.innerHTML = `
            <div class="r-upload-modal">
                <h3>Publication en cours</h3>
                <div class="r-upload-spinner"></div>
                <div class="r-progress-bar-container">
                    <div class="r-progress-bar-fill" id="r-uploadProgress"></div>
                </div>
                <div class="r-upload-status" id="r-uploadStatus">Préparation des fichiers...</div>
                <p class="text-muted small">Veuillez patienter, cela peut prendre quelques secondes</p>
                <button class="btn btn-outline-secondary mt-3" id="r-cancelUploadBtn">Annuler</button>
            </div>
        `;
        document.body.appendChild(overlay);

        document.getElementById('r-cancelUploadBtn')?.addEventListener('click', () => {
            if (uploadController) {
                uploadController.abort();
            }
            hideUploadOverlay(false, 'Upload annulé');
        });
    }

    function updateUploadProgress(percent, status) {
        const progressBar = document.getElementById('r-uploadProgress');
        const statusEl = document.getElementById('r-uploadStatus');
        if (progressBar) progressBar.style.width = percent + '%';
        if (statusEl) statusEl.textContent = status;
    }

    function hideUploadOverlay(success = true, message = '') {
        const overlay = document.getElementById('r-uploadOverlay');
        if (!overlay) return;
        
        if (success) {
            overlay.innerHTML = `
                <div class="r-upload-modal">
                    <h3 style="color: #10b981;">✓ Publication réussie !</h3>
                    <p>Redirection en cours...</p>
                </div>
            `;
            setTimeout(() => {
                window.location.href = pendingRedirectUrl || '/vendor/dashboard';
            }, 1500);
        } else {
            // Version mobile-friendly avec échappatoires
            overlay.innerHTML = `
                <div class="r-upload-modal">
                    <h3 style="color: #dc3545;">❌ Erreur</h3>
                    <p class="mb-3">${message || 'Une erreur est survenue.'}</p>
                    
                    <div class="d-flex flex-column gap-2 mt-4">
                        <!-- Option 1: Revenir au formulaire (conserver les données) -->
                        <button class="btn btn-primary w-100 py-3" id="r-retryBtn">
                            🔄 Réessayer
                        </button>
                        
                        <!-- Option 2: Retour au formulaire sans réessayer -->
                        <button class="btn btn-outline-secondary w-100 py-3" id="r-backToFormBtn">
                            ⬅️ Retour au formulaire
                        </button>
                        
                        <!-- Option 3: Sortie propre -->
                        <button class="btn btn-outline-danger w-100 py-3 mt-2" id="r-exitBtn">
                            🏠 Retour au tableau de bord
                        </button>
                        
                        <!-- Option 4: Rechargement (dernier recours) -->
                        <button class="btn btn-link text-muted small mt-3" id="r-reloadBtn">
                            ⚡ Recharger la page
                        </button>
                    </div>
                </div>
            `;

            // 1. RÉESSAYER - conserve les données et relance
            document.getElementById('r-retryBtn')?.addEventListener('click', () => {
                overlay.remove();
                enableSubmitButton(currentSubmitBtn);
                if (currentForm) {
                    // Petit délai pour que l'UI se mette à jour
                    setTimeout(() => {
                        currentForm.dispatchEvent(new Event('submit', { cancelable: true }));
                    }, 100);
                }
            });

            // 2. RETOUR AU FORMULAIRE - ferme l'overlay, garde les données
            document.getElementById('r-backToFormBtn')?.addEventListener('click', () => {
                overlay.remove();
                enableSubmitButton(currentSubmitBtn);
                // Scroll jusqu'au formulaire
                currentForm?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            });

            // 3. SORTIE - retour au dashboard
            document.getElementById('r-exitBtn')?.addEventListener('click', () => {
                window.location.href = '/vendor/dashboard';
            });

            // 4. RECHARGEMENT - dernier recours
            document.getElementById('r-reloadBtn')?.addEventListener('click', () => {
                window.location.reload();
            });
        }
    }

    function estimateTotalSize(formData) {
        let totalSize = 0;
        for (let pair of formData.entries()) {
            if (pair[1] instanceof File && pair[1].size) {
                totalSize += pair[1].size;
            }
        }
        return totalSize;
    }

    function isDashboardUrl(url) {
        return String(url || '').toLowerCase().includes('/vendor/dashboard');
    }

    function resolveRedirectUrl(response) {
        if (response && response.redirected && response.url) {
            return response.url;
        }
        if (currentForm && currentForm.action) {
            return currentForm.action;
        }
        return '/vendor/dashboard';
    }

    function disableSubmitButton(btn) {
        if (!btn) return;
        btn.disabled = true;
        btn.classList.add('r-btn-loading');
        btn.dataset.originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="r-spinner"></span> Envoi en cours...';
    }

    function enableSubmitButton(btn) {
        if (!btn) return;
        btn.disabled = false;
        btn.classList.remove('r-btn-loading');
        if (btn.dataset.originalHtml) {
            btn.innerHTML = btn.dataset.originalHtml;
        }
    }

    function attachToForm(form) {
        if (!form) return;
        if (form.dataset.rUploadAttached) return;
        form.dataset.rUploadAttached = 'true';

        const submitBtn = form.querySelector('button[type="submit"]');
        if (!submitBtn) return;

        form.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            if (!navigator.onLine) {
                alert('Vous êtes hors ligne. Vérifiez votre connexion.');
                return;
            }

            currentForm = form;
            currentSubmitBtn = submitBtn;

            disableSubmitButton(submitBtn);
            showUploadOverlay();

            const formData = new FormData(form);
            const totalBytes = estimateTotalSize(formData);

            uploadController = new AbortController();
            const timeoutId = setTimeout(() => uploadController.abort(), CONFIG.timeoutMs);

            let progress = 0;
            const progressInterval = setInterval(() => {
                const increment = totalBytes > 10 * 1024 * 1024 ? 2 : 5;
                progress += increment;
                if (progress > 90) progress = 90;
                updateUploadProgress(progress, 'Téléversement en cours...');
            }, 300);

            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    body: formData,
                    signal: uploadController.signal
                });

                clearInterval(progressInterval);
                clearTimeout(timeoutId);

                if (response.ok) {
                    const destinationUrl = resolveRedirectUrl(response);

                    if (response.redirected && !isDashboardUrl(destinationUrl)) {
                        window.location.href = destinationUrl;
                        return;
                    }

                    pendingRedirectUrl = destinationUrl || '/vendor/dashboard';
                    updateUploadProgress(100, 'Finalisation...');
                    setTimeout(() => {
                        hideUploadOverlay(true);
                    }, 500);
                } else {
                    throw new Error(`Erreur serveur: ${response.status}`);
                }
            } catch (error) {
                clearInterval(progressInterval);
                clearTimeout(timeoutId);

                log('Upload error:', error);

                let errorMessage = 'Une erreur est survenue.';
                if (error.name === 'AbortError') {
                    errorMessage = 'Délai dépassé (30s). Fichier trop volumineux.';
                } else if (!navigator.onLine) {
                    errorMessage = 'Connexion perdue.';
                }

                hideUploadOverlay(false, errorMessage);
                // Ne pas réactiver le bouton - on laisse l'utilisateur choisir
            }
        });
    }

    function init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                const form = document.getElementById('productForm');
                if (form) attachToForm(form);
            });
        } else {
            const form = document.getElementById('productForm');
            if (form) attachToForm(form);
        }
    }

    init();
})();
