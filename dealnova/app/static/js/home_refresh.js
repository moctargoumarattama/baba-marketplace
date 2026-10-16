(function () {
  'use strict';
  function initImages(root) {
    root.querySelectorAll('.hub-product-media img, .hub-shop-image img').forEach(function (image) {
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

  function initRotation() {
    var root = document.querySelector('[data-home-rotation-url]');
    if (!root || root.dataset.rotationReady) return;
    root.dataset.rotationReady = '1';
    var timer, controller, nextRefresh, suspended = false;
    var kinds = ['products', 'services'];
    function busy() {
      return document.querySelector('[role="dialog"][aria-hidden="false"], .modal.show') ||
        kinds.some(function (kind) {
          return root.querySelector('[data-home-offers="' + kind + '"]').contains(document.activeElement);
        });
    }
    function armTimer() {
      clearTimeout(timer);
      if (!document.hidden && !suspended && !controller) {
        timer = setTimeout(refresh, Math.max(0, nextRefresh - Date.now()));
      }
    }
    function schedule(seconds) {
      nextRefresh = Date.now() + seconds * 1000;
      armTimer();
    }
    async function refresh() {
      if (document.hidden || suspended || controller) return;
      if (busy()) { schedule(15); return; }
      controller = new AbortController();
      var activeRequest = controller;
      var timeout = setTimeout(function () { activeRequest.abort(); }, 10000);
      var delay = 60;
      try {
        var response = await fetch(root.dataset.homeRotationUrl, {
          credentials: 'same-origin', cache: 'no-store', signal: activeRequest.signal
        });
        if (!response.ok) throw new Error('Home selection unavailable');
        var payload = await response.json();
        if (!Number.isFinite(payload.refresh_after) || payload.refresh_after < 1 || payload.refresh_after > 1800) {
          throw new Error('Invalid rotation interval');
        }
        var fragments = kinds.map(function (kind) {
          var section = payload.sections[kind];
          if (!section || typeof section.html !== 'string' || !Number.isInteger(section.count) || section.count < 0 || section.count > 4) {
            throw new Error('Invalid home selection');
          }
          var template = document.createElement('template');
          template.innerHTML = section.html;
          if (template.content.querySelectorAll('.hub-product').length !== section.count) {
            throw new Error('Incomplete home selection');
          }
          return template.content;
        });
        if (document.hidden || suspended || busy()) { delay = 15; return; }
        kinds.forEach(function (kind, index) {
          var section = root.querySelector('[data-home-offers="' + kind + '"]');
          var grid = section.querySelector('.hub-products-grid');
          grid.replaceChildren(fragments[index]);
          if (kind === 'services') section.hidden = payload.sections[kind].count === 0;
          initImages(grid);
        });
        delay = payload.refresh_after;
      } catch (_error) {
        // Keep the current cards during a connection failure and retry later.
      } finally {
        clearTimeout(timeout);
        controller = null;
        schedule(delay);
      }
    }
    document.addEventListener('visibilitychange', armTimer);
    window.addEventListener('pagehide', function () {
      suspended = true;
      clearTimeout(timer);
      if (controller) controller.abort();
    });
    window.addEventListener('pageshow', function () { suspended = false; armTimer(); });
    schedule(Number(root.dataset.homeRefreshAfter) || 1800);
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
      if (accountButton && account) {
        account.open = !account.open;
        if (account.open) {
          window.scrollTo({ top: 0, behavior: 'auto' });
          var first = account.querySelector('a, button');
          if (first) first.focus();
        }
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
    initRotation();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initStorefront);
  else initStorefront();
})();
