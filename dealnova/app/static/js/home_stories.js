/**
 * Baba Market — Discovery Stories & Video Feed Controller
 * Accessible, native <dialog> based, non-intrusive story player.
 */
(function () {
  'use strict';

  var dialog = document.getElementById('bmStoriesDialog');
  var rail = document.querySelector('.bm-stories-rail');
  var prevBtn = document.querySelector('.bm-stories-prev');
  var nextBtn = document.querySelector('.bm-stories-next');
  if (!dialog || !rail) return;

  var bubbles = Array.prototype.slice.call(rail.querySelectorAll('.bm-story-bubble'));
  if (!bubbles.length) return;

  var progressContainer = document.getElementById('bmStoryProgressBars');
  var videoElem = document.getElementById('bmStoryVideo');
  var imageElem = document.getElementById('bmStoryImage');
  var loaderElem = document.getElementById('bmStoryLoader');
  var shopLogo = document.getElementById('bmStoryShopLogo');
  var shopName = document.getElementById('bmStoryShopName');
  var badgeElem = document.getElementById('bmStoryBadge');
  var titleElem = document.getElementById('bmStoryTitle');
  var priceElem = document.getElementById('bmStoryPrice');
  var origPriceElem = document.getElementById('bmStoryOrigPrice');
  var waBtn = document.getElementById('bmStoryWhatsAppBtn');
  var detailBtn = document.getElementById('bmStoryDetailBtn');
  var audioBtn = document.getElementById('bmStoryAudioBtn');
  var playBtn = document.getElementById('bmStoryPlayBtn');
  var tapPrev = document.getElementById('bmStoryTapPrev');
  var tapNext = document.getElementById('bmStoryTapNext');

  var stories = [];
  var currentIndex = 0;
  var isPlaying = false;
  var isMuted = true;
  var progressTimer = null;
  var storyStartTime = 0;
  var storyDuration = 5000; // 5s default for photos
  var elapsedTime = 0;
  var isHolding = false;
  var holdTimeout = null;

  var STORAGE_KEY = 'bm_viewed_stories';

  function getViewedStories() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function markStoryViewed(storyId) {
    if (!storyId) return;
    try {
      var viewed = getViewedStories();
      if (viewed.indexOf(storyId) === -1) {
        viewed.push(storyId);
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(viewed));
      }
      var b = rail.querySelector('[data-story-id="' + storyId + '"]');
      if (b) b.classList.add('is-viewed');
    } catch (e) {}
  }

  function applyViewedStates() {
    var viewed = getViewedStories();
    bubbles.forEach(function (b) {
      var id = b.getAttribute('data-story-id');
      if (id && viewed.indexOf(id) !== -1) {
        b.classList.add('is-viewed');
      }
    });
  }

  // Parse story data from DOM
  bubbles.forEach(function (b, index) {
    stories.push({
      id: b.getAttribute('data-story-id'),
      title: b.getAttribute('data-story-title') || '',
      mediaUrl: b.getAttribute('data-story-media') || '',
      mediaType: b.getAttribute('data-story-type') || 'image',
      label: b.getAttribute('data-story-label') || '',
      price: b.getAttribute('data-story-price') || '',
      origPrice: b.getAttribute('data-story-orig-price') || '',
      shopName: b.getAttribute('data-story-shop') || '',
      shopLogo: b.getAttribute('data-story-shop-logo') || '',
      whatsappUrl: b.getAttribute('data-story-wa') || '#',
      detailUrl: b.getAttribute('data-story-detail') || '#',
    });

    b.addEventListener('click', function () {
      openStoryViewer(index);
    });
  });

  // Render segmented progress bars
  function renderProgressBars() {
    if (!progressContainer) return;
    progressContainer.innerHTML = '';
    stories.forEach(function (_, i) {
      var seg = document.createElement('div');
      seg.className = 'bm-story-progress-segment';
      var fill = document.createElement('div');
      fill.className = 'bm-story-progress-fill';
      seg.appendChild(fill);
      progressContainer.appendChild(seg);
    });
  }

  function updateProgressSegments() {
    var segments = progressContainer ? progressContainer.children : [];
    for (var i = 0; i < segments.length; i++) {
      var seg = segments[i];
      var fill = seg.querySelector('.bm-story-progress-fill');
      if (i < currentIndex) {
        seg.classList.add('completed');
        if (fill) fill.style.width = '100%';
      } else if (i === currentIndex) {
        seg.classList.remove('completed');
        var pct = Math.min(100, Math.max(0, (elapsedTime / storyDuration) * 100));
        if (fill) fill.style.width = pct + '%';
      } else {
        seg.classList.remove('completed');
        if (fill) fill.style.width = '0%';
      }
    }
  }

  function showStory(index) {
    if (index < 0 || index >= stories.length) {
      closeStoryViewer();
      return;
    }

    currentIndex = index;
    var s = stories[currentIndex];
    markStoryViewed(s.id);

    // Stop current media
    if (videoElem) {
      videoElem.pause();
      videoElem.removeAttribute('src');
      videoElem.load();
      videoElem.classList.add('hidden');
    }
    if (imageElem) {
      imageElem.classList.add('hidden');
    }
    if (loaderElem) loaderElem.classList.remove('hidden');

    // Populate info
    if (titleElem) titleElem.textContent = s.title;
    if (shopName) shopName.textContent = s.shopName;
    if (badgeElem) badgeElem.textContent = s.label || 'Story';
    if (priceElem) priceElem.textContent = s.price;
    if (origPriceElem) origPriceElem.textContent = s.origPrice;

    if (shopLogo) {
      if (s.shopLogo) {
        shopLogo.src = s.shopLogo;
        shopLogo.style.display = 'block';
      } else {
        shopLogo.style.display = 'none';
      }
    }

    if (waBtn) waBtn.href = s.whatsappUrl;
    if (detailBtn) detailBtn.href = s.detailUrl;

    elapsedTime = 0;
    updateProgressSegments();

    if (s.mediaType === 'video' && s.mediaUrl) {
      storyDuration = 10000; // Will adjust once metadata loads
      if (videoElem) {
        videoElem.classList.remove('hidden');
        videoElem.muted = isMuted;
        videoElem.src = s.mediaUrl;
        videoElem.onloadedmetadata = function () {
          if (videoElem.duration && !isNaN(videoElem.duration)) {
            storyDuration = Math.max(3000, videoElem.duration * 1000);
          }
          if (loaderElem) loaderElem.classList.add('hidden');
          startPlayback();
        };
        videoElem.onerror = function () {
          // Fallback to 5s if video cannot play
          if (loaderElem) loaderElem.classList.add('hidden');
          startPlayback();
        };
        videoElem.load();
      }
    } else {
      storyDuration = 5000;
      if (imageElem) {
        imageElem.classList.remove('hidden');
        imageElem.onload = function () {
          if (loaderElem) loaderElem.classList.add('hidden');
          startPlayback();
        };
        imageElem.onerror = function () {
          if (loaderElem) loaderElem.classList.add('hidden');
          startPlayback();
        };
        imageElem.src = s.mediaUrl || '';
      }
    }
  }

  function startPlayback() {
    isPlaying = true;
    storyStartTime = Date.now() - elapsedTime;
    if (playBtn) {
      playBtn.setAttribute('aria-label', 'Mettre en pause');
      playBtn.innerHTML = '<i class="bi bi-pause-fill" aria-hidden="true"></i>';
    }

    var s = stories[currentIndex];
    if (s && s.mediaType === 'video' && videoElem && !videoElem.classList.contains('hidden')) {
      videoElem.muted = isMuted;
      videoElem.play().catch(function () {});
    }

    if (progressTimer) cancelAnimationFrame(progressTimer);

    function tick() {
      if (!isPlaying) return;
      var now = Date.now();
      elapsedTime = now - storyStartTime;
      updateProgressSegments();

      if (elapsedTime >= storyDuration) {
        showNextStory();
      } else {
        progressTimer = requestAnimationFrame(tick);
      }
    }

    progressTimer = requestAnimationFrame(tick);
  }

  function pausePlayback() {
    isPlaying = false;
    if (progressTimer) {
      cancelAnimationFrame(progressTimer);
      progressTimer = null;
    }
    if (videoElem && !videoElem.classList.contains('hidden')) {
      videoElem.pause();
    }
    if (playBtn) {
      playBtn.setAttribute('aria-label', 'Reprendre la lecture');
      playBtn.innerHTML = '<i class="bi bi-play-fill" aria-hidden="true"></i>';
    }
  }

  function showNextStory() {
    if (currentIndex < stories.length - 1) {
      showStory(currentIndex + 1);
    } else {
      closeStoryViewer();
    }
  }

  function showPrevStory() {
    if (currentIndex > 0) {
      showStory(currentIndex - 1);
    } else {
      showStory(0);
    }
  }

  function openStoryViewer(index) {
    renderProgressBars();
    dialog.showModal();
    showStory(index);
  }

  function closeStoryViewer() {
    pausePlayback();
    if (dialog.open) {
      dialog.close();
    }
    if (videoElem) {
      videoElem.pause();
      videoElem.removeAttribute('src');
      videoElem.load();
    }
  }

  // Dialog dismissal listener
  dialog.addEventListener('close', function () {
    pausePlayback();
    if (videoElem) {
      videoElem.pause();
      videoElem.removeAttribute('src');
      videoElem.load();
    }
  });

  // Controls
  if (playBtn) {
    playBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (isPlaying) {
        pausePlayback();
      } else {
        startPlayback();
      }
    });
  }

  if (audioBtn) {
    audioBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      isMuted = !isMuted;
      if (videoElem) {
        videoElem.muted = isMuted;
      }
      if (isMuted) {
        audioBtn.innerHTML = '<i class="bi bi-volume-mute-fill" aria-hidden="true"></i>';
        audioBtn.setAttribute('aria-label', 'Activer le son');
      } else {
        audioBtn.innerHTML = '<i class="bi bi-volume-up-fill" aria-hidden="true"></i>';
        audioBtn.setAttribute('aria-label', 'Couper le son');
      }
    });
  }

  // Tap navigation zones
  if (tapPrev) {
    tapPrev.addEventListener('click', function (e) {
      e.stopPropagation();
      showPrevStory();
    });
  }

  if (tapNext) {
    tapNext.addEventListener('click', function (e) {
      e.stopPropagation();
      showNextStory();
    });
  }

  // Hold to pause (pointerdown / pointerup)
  var card = dialog.querySelector('.bm-story-player-card');
  if (card) {
    card.addEventListener('pointerdown', function (e) {
      if (e.target.closest('.bm-story-controls') || e.target.closest('.bm-story-actions')) return;
      holdTimeout = setTimeout(function () {
        isHolding = true;
        pausePlayback();
      }, 150);
    });

    card.addEventListener('pointerup', function () {
      if (holdTimeout) clearTimeout(holdTimeout);
      if (isHolding) {
        isHolding = false;
        startPlayback();
      }
    });

    card.addEventListener('pointercancel', function () {
      if (holdTimeout) clearTimeout(holdTimeout);
      if (isHolding) {
        isHolding = false;
        startPlayback();
      }
    });
  }

  // Keyboard navigation
  dialog.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowRight') {
      showNextStory();
    } else if (e.key === 'ArrowLeft') {
      showPrevStory();
    } else if (e.key === ' ' || e.key === 'Spacebar') {
      e.preventDefault();
      if (isPlaying) pausePlayback();
      else startPlayback();
    }
  });

  // Rail scroll arrows on desktop
  function updateRailArrows() {
    if (!prevBtn || !nextBtn) return;
    var scrollLeft = rail.scrollLeft;
    var maxScroll = rail.scrollWidth - rail.clientWidth;
    prevBtn.hidden = scrollLeft <= 4;
    nextBtn.hidden = scrollLeft >= maxScroll - 4;
  }

  if (prevBtn) {
    prevBtn.addEventListener('click', function () {
      rail.scrollBy({ left: -240, behavior: 'smooth' });
    });
  }
  if (nextBtn) {
    nextBtn.addEventListener('click', function () {
      rail.scrollBy({ left: 240, behavior: 'smooth' });
    });
  }
  rail.addEventListener('scroll', updateRailArrows, { passive: true });
  window.addEventListener('resize', updateRailArrows, { passive: true });

  // Init
  applyViewedStates();
  updateRailArrows();
})();
