(function () {
  'use strict';
  function enhancePromotionPhoto(frame, image) {
    if (!frame || !image || image.dataset.promotionPhotoBound) return;
    image.dataset.promotionPhotoBound = '1';
    var backdrop = null;
    function showBackdrop() {
      if (!image.naturalWidth) return;
      if (!backdrop) {
        backdrop = document.createElement('span');
        backdrop.className = 'promotion-photo-backdrop';
        backdrop.setAttribute('aria-hidden', 'true');
        frame.insertBefore(backdrop, frame.firstChild);
      }
      backdrop.style.backgroundImage = 'url(' + JSON.stringify(image.currentSrc || image.src) + ')';
    }
    image.addEventListener('load', showBackdrop);
    image.addEventListener('error', function () {
      if (backdrop) { backdrop.remove(); backdrop = null; }
    });
    if (image.complete && image.naturalWidth) showBackdrop();
  }
  window.BMPromotionPhotos = { enhance: enhancePromotionPhoto };

  function initImages(root) {
    root.querySelectorAll('.promotion-photo-frame').forEach(function (frame) {
      enhancePromotionPhoto(frame, frame.querySelector('img'));
    });
    root.querySelectorAll('.hub-product-media img').forEach(function (image) {
      function showPlaceholder() {
        if (image.hidden) return;
        image.hidden = true;
        var placeholder = document.createElement('span');
        placeholder.className = 'hub-image-placeholder';
        var icon = document.createElement('i');
        icon.className = 'bi bi-image';
        icon.setAttribute('aria-hidden', 'true');
        var label = document.createElement('span');
        label.textContent = 'Sans photo';
        placeholder.appendChild(icon);
        placeholder.appendChild(label);
        image.parentNode.appendChild(placeholder);
      }
      image.addEventListener('error', showPlaceholder, { once: true });
      if (image.complete && !image.naturalWidth) showPlaceholder();
    });
  }

  function initStorefront() {
    var account = document.getElementById('hubAccount');
    var disclosures = document.querySelectorAll('.hub-disclosure');
    disclosures.forEach(function (details) {
      details.addEventListener('toggle', function () {
        if (!details.open) return;
        disclosures.forEach(function (other) { if (other !== details) other.open = false; });
      });
    });
    document.addEventListener('click', function (event) {
      if (event.target.closest('[data-hub-home]')) window.scrollTo({ top: 0, behavior: 'auto' });
    }, true);
    document.addEventListener('click', function (event) {
      var accountButton = event.target.closest('[data-hub-account]');
      if (accountButton) {
        if (account) {
          account.open = !account.open;
          if (account.open) {
            window.scrollTo({ top: 0, behavior: 'auto' });
            var first = account.querySelector('a, button');
            if (first) first.focus();
          }
          return;
        }
        var targetUrl = accountButton.getAttribute('data-href');
        if (targetUrl) {
          window.location.assign(targetUrl);
          return;
        }
        window.location.assign('/login');
        return;
      }
      disclosures.forEach(function (details) { if (!details.contains(event.target)) details.open = false; });
    });
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      disclosures.forEach(function (details) {
        if (!details.open) return;
        details.open = false;
        var trigger = details.querySelector('summary');
        if (!trigger.getClientRects().length) trigger = document.querySelector('[data-hub-account]');
        if (trigger) trigger.focus();
      });
    });
    initImages(document);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initStorefront);
  else initStorefront();
})();
