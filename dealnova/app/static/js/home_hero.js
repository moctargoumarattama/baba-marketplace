(function () {
  'use strict';
  function init() {
    var hero = document.querySelector('[data-hero-carousel]');
    if (!hero || hero.dataset.heroReady) return;
    hero.dataset.heroReady = '1';
    var slides = Array.from(hero.querySelectorAll('[data-hero-slide]'));
    var dots = Array.from(hero.querySelectorAll('[data-hero-to]'));
    var pause = hero.querySelector('[data-hero-pause]');
    var status = hero.querySelector('[data-hero-status]');
    var motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    var index = 0, timer, paused = motion.matches, hovered = false, visible = true, suspended = false, gesture = null;

    function updatePause() {
      pause.setAttribute('aria-pressed', String(paused));
      pause.setAttribute('aria-label', paused ? pause.dataset.playLabel : pause.dataset.pauseLabel);
      pause.querySelector('i').className = paused ? 'bi bi-play-fill' : 'bi bi-pause-fill';
    }
    function schedule() {
      clearTimeout(timer);
      var focused = hero.contains(document.activeElement) && document.activeElement !== pause;
      if (paused || hovered || focused || document.hidden || !visible || suspended) return;
      timer = setTimeout(function () {
        if (document.querySelector('[role="dialog"][aria-hidden="false"], .modal.show, .hub-search:focus-within')) {
          schedule();
          return;
        }
        show(index + 1, false);
      }, 6000);
    }
    function show(next, manual) {
      index = (next + slides.length) % slides.length;
      slides.forEach(function (slide, position) {
        var active = position === index;
        slide.classList.toggle('is-active', active);
        slide.setAttribute('aria-hidden', String(!active));
        slide.inert = !active;
        dots[position].setAttribute('aria-pressed', String(active));
      });
      if (manual) {
        paused = true;
        updatePause();
        status.textContent = slides[index].dataset.heroLabel;
      }
      schedule();
    }
    dots.forEach(function (dot, position) { dot.addEventListener('click', function () { show(position, true); }); });
    pause.addEventListener('click', function () {
      paused = !paused;
      if (!paused) pause.focus({ preventScroll: true });
      updatePause();
      schedule();
    });
    hero.addEventListener('keydown', function (event) {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      var direction = event.key === 'ArrowRight' ? 1 : -1;
      if (getComputedStyle(hero).direction === 'rtl') direction *= -1;
      show(index + direction, true);
    });
    hero.addEventListener('pointerdown', function (event) {
      if (!event.isPrimary || event.button !== 0 || event.target.closest('button, a')) return;
      gesture = { id: event.pointerId, x: event.clientX, y: event.clientY };
      clearTimeout(timer);
      hero.setPointerCapture(event.pointerId);
    });
    hero.addEventListener('pointerup', function (event) {
      if (!gesture || gesture.id !== event.pointerId) return;
      var dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
      gesture = null;
      if (Math.abs(dx) >= 45 && Math.abs(dx) > Math.abs(dy) * 1.5) {
        var direction = dx < 0 ? 1 : -1;
        if (getComputedStyle(hero).direction === 'rtl') direction *= -1;
        show(index + direction, true);
      } else schedule();
    });
    hero.addEventListener('pointercancel', function () { gesture = null; schedule(); });
    hero.addEventListener('pointerenter', function (event) {
      if (event.pointerType === 'mouse' && window.matchMedia('(hover: hover)').matches) { hovered = true; schedule(); }
    });
    hero.addEventListener('pointerleave', function () { hovered = false; schedule(); });
    hero.addEventListener('focusin', schedule);
    hero.addEventListener('focusout', function () { setTimeout(schedule, 0); });
    document.addEventListener('visibilitychange', schedule);
    window.addEventListener('pagehide', function () { suspended = true; clearTimeout(timer); });
    window.addEventListener('pageshow', function () { suspended = false; schedule(); });
    motion.addEventListener('change', function () { if (motion.matches) paused = true; updatePause(); schedule(); });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting && entries[0].intersectionRatio >= 0.15;
        schedule();
      }, { threshold: [0, 0.15] }).observe(hero);
    }
    hero.querySelector('[data-hero-controls]').hidden = false;
    updatePause();
    show(0, false);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
