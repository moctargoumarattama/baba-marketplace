/**
 * product_detail_page.js - Version nettoyée
 * Délègue la plupart des fonctionnalités aux modules core
 */

(function () {
  "use strict";

  if (window.__BM_PRODUCT_DETAIL_INIT__) return;
  window.__BM_PRODUCT_DETAIL_INIT__ = true;

  // ========== 1. DÉLÉGATION AUX MODULES CORE ==========
  const ui = window.BMCoreUI;
  const cart = window.BMCoreCart;
  const csrf = window.BMAjaxCSRF;
  const fetchApi = window.BMAjaxFetch;

  // ========== 2. CONFIGURATION ==========
  const SELECTORS = {
    mainImage: '#mainImage',
    thumbnails: '[data-role="thumb-switch"]',
    galleryNav: '[data-gallery-nav]',
    addToCartForm: 'form[data-action="add-to-cart"][data-ajax="true"]',
    productVideo: '#productMainVideo',
    videoFallback: '#productVideoFallback'
  };

  // ========== 3. GALERIE SIMPLIFIÉE ==========
  function initGallery() {
    const mainImage = document.querySelector(SELECTORS.mainImage);
    const thumbs = document.querySelectorAll(SELECTORS.thumbnails);
    const navBtns = document.querySelectorAll(SELECTORS.galleryNav);
    
    if (!mainImage || thumbs.length <= 1) return;

    // Changer d'image
    const setImage = (src, activeThumb) => {
      mainImage.src = src;
      thumbs.forEach(thumb => thumb.classList.remove('active'));
      if (activeThumb) activeThumb.classList.add('active');
    };

    // Navigation par miniatures
    thumbs.forEach(thumb => {
      thumb.addEventListener('click', () => {
        setImage(thumb.dataset.large || thumb.src, thumb);
      });
    });

    // Navigation par boutons
    const goToRelative = (step) => {
      const activeIndex = Array.from(thumbs).findIndex(t => t.classList.contains('active'));
      const current = activeIndex >= 0 ? activeIndex : 0;
      const target = (current + step + thumbs.length) % thumbs.length;
      setImage(thumbs[target].dataset.large || thumbs[target].src, thumbs[target]);
    };

    navBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        goToRelative(btn.dataset.galleryNav === 'prev' ? -1 : 1);
      });
    });

    // Swipe sur mobile (optionnel)
    const wrap = document.querySelector('.main-image-wrap');
    if (wrap && 'ontouchstart' in window) {
      let touchStart = 0;
      wrap.addEventListener('touchstart', (e) => {
        touchStart = e.touches[0].clientX;
      });
      wrap.addEventListener('touchend', (e) => {
        if (!touchStart) return;
        const diff = e.changedTouches[0].clientX - touchStart;
        if (Math.abs(diff) > 50) {
          goToRelative(diff > 0 ? -1 : 1);
        }
        touchStart = 0;
      });
    }
  }

  // ========== 4. VIDÉO - SIMPLE ET ROBUSTE ==========
  function initVideo() {
    const video = document.querySelector(SELECTORS.productVideo);
    const fallback = document.querySelector(SELECTORS.videoFallback);
    if (!video) return;

    const showFallback = () => {
      if (fallback) fallback.hidden = false;
    };

    // Essayer de charger la première image
    const tryLoadFirstFrame = () => {
      if (video.readyState >= 2 && video.duration > 0.2) {
        if (video.currentTime <= 0) video.currentTime = 0.01;
        if (fallback) fallback.hidden = true;
      }
    };

    video.addEventListener('loadedmetadata', tryLoadFirstFrame);
    video.addEventListener('error', showFallback);
    
    // Prévisualisation silencieuse au survol (optionnel)
    let previewTimer;
    video.addEventListener('mouseenter', () => {
      previewTimer = setTimeout(() => {
        if (video.paused && video.readyState >= 3) {
          video.muted = true;
          video.play().catch(() => {});
          setTimeout(() => video.pause(), 100);
        }
      }, 300);
    });
    video.addEventListener('mouseleave', () => clearTimeout(previewTimer));
  }

  // ========== 5. AJOUT AU PANIER - DÉLÉGATION COMPLÈTE ==========
  function initAddToCart() {
    // Les formulaires sont déjà gérés par core_live.js
    // On ajoute juste un feedback visuel supplémentaire
    const forms = document.querySelectorAll(SELECTORS.addToCartForm);
    forms.forEach(form => {
      form.addEventListener('bm:ajax-form-success', (e) => {
        const btn = form.querySelector('button[type="submit"]');
        if (btn) {
          const originalText = btn.innerHTML;
          btn.innerHTML = '<i class="bi bi-check-lg"></i> Ajouté !';
          setTimeout(() => btn.innerHTML = originalText, 1500);
        }
      });
    });
  }

  // ========== 6. ZOOM D'IMAGE - CSS FIRST ==========
  function initImageZoom() {
    // Pas de JS ! CSS fait le travail :
    // .main-image-wrap img { transition: transform 0.3s; cursor: zoom-in; }
    // .main-image-wrap img:active { transform: scale(1.5); cursor: zoom-out; }
    
    // Version légère pour le modal
    const mainImage = document.querySelector(SELECTORS.mainImage);
    if (!mainImage) return;
    
    mainImage.addEventListener('click', () => {
      const modal = document.createElement('div');
      modal.style.cssText = `
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.9);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
        cursor: zoom-out;
      `;
      const img = document.createElement('img');
      img.src = mainImage.src;
      img.style.maxWidth = '90%';
      img.style.maxHeight = '90%';
      modal.appendChild(img);
      modal.addEventListener('click', () => modal.remove());
      document.body.appendChild(modal);
      document.body.style.overflow = 'hidden';
      modal.addEventListener('click', () => {
        modal.remove();
        document.body.style.overflow = '';
      });
    });
  }

  // ========== 7. INITIALISATION ==========
  function init() {
    initGallery();
    initVideo();
    initAddToCart();
    initImageZoom();
    
    // Mettre à jour le badge panier au chargement
    if (cart && typeof cart.getCartCount === 'function') {
      cart.getCartCount().then(count => {
        document.querySelectorAll('[data-cart-badge]').forEach(el => {
          el.textContent = count;
          el.classList.toggle('d-none', count <= 0);
        });
      });
    }
  }

  // Démarrer quand le DOM est prêt
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
