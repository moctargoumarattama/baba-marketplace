/**
 * ============================================================================
 * BABA MARKET — MOTEUR D'ARRIÈRE-PLAN 3D CINÉTIQUE & INTERACTIF
 * Arrière-plan 3D sur fond blanc pur avec sphères translucides et rubans fluides
 * Réaction dynamique à la souris (PC) et au gyroscope / toucher (Mobile)
 * Performance 60/120 FPS • GPU Accéléré • Zéro dépendance
 * ============================================================================
 */
(function () {
  'use strict';

  function initKinetic3D() {
    var canvas = document.getElementById('baba3DKineticCanvas');
    if (!canvas) return;

    var ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    var width = 0;
    var height = 0;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);

    // Positions et cibles de mouvement (normalisées entre -1 et 1)
    var mouse = { x: 0, y: 0, targetX: 0, targetY: 0 };
    var isMobile = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);

    // Redimensionnement fluide du canvas
    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
    }
    window.addEventListener('resize', resize, { passive: true });
    resize();

    // 1. Définition des sphères 3D en verre dépoli et reflets émeraude
    var spheres = [
      { baseRelX: 0.12, baseRelY: 0.18, r: 48, depth: 1.35, color: 'emerald', phase: 0.0, speed: 0.8 },
      { baseRelX: 0.88, baseRelY: 0.14, r: 64, depth: 1.6, color: 'pearl', phase: 1.4, speed: 0.7 },
      { baseRelX: 0.06, baseRelY: 0.58, r: 56, depth: 1.1, color: 'pearl', phase: 2.8, speed: 0.9 },
      { baseRelX: 0.92, baseRelY: 0.62, r: 76, depth: 1.8, color: 'emerald', phase: 4.1, speed: 0.65 },
      { baseRelX: 0.22, baseRelY: 0.88, r: 52, depth: 1.25, color: 'emerald', phase: 5.2, speed: 0.85 },
      { baseRelX: 0.82, baseRelY: 0.90, r: 42, depth: 0.95, color: 'pearl', phase: 0.8, speed: 1.0 },
      // Sphères d'ambiance centrale plus subtiles
      { baseRelX: 0.48, baseRelY: 0.32, r: 34, depth: 0.7, color: 'pearl', phase: 3.3, speed: 0.75 },
      { baseRelX: 0.54, baseRelY: 0.78, r: 38, depth: 0.8, color: 'emerald', phase: 2.1, speed: 0.82 }
    ];

    // 2. Écouteurs de mouvements interactifs (Souris sur PC & Gyroscope/Touch sur Mobile)
    window.addEventListener('mousemove', function (e) {
      var nx = (e.clientX / width - 0.5) * 2;
      var ny = (e.clientY / height - 0.5) * 2;
      mouse.targetX = Math.max(-1, Math.min(1, nx));
      mouse.targetY = Math.max(-1, Math.min(1, ny));
    }, { passive: true });

    // Gyroscope mobile (inclinaison naturelle de l'appareil)
    if (window.DeviceOrientationEvent) {
      window.addEventListener('deviceorientation', function (e) {
        if (e.gamma !== null && e.beta !== null) {
          // Gamma : inclinaison gauche/droite (-45 à 45 deg)
          // Beta : inclinaison avant/arrière (10 à 60 deg typique tenue en main)
          var gx = (e.gamma || 0) / 30;
          var gy = ((e.beta || 30) - 35) / 30;
          mouse.targetX = Math.max(-1, Math.min(1, gx));
          mouse.targetY = Math.max(-1, Math.min(1, gy));
        }
      }, { passive: true });
    }

    // Toucher / Glissement sur mobile en complément
    window.addEventListener('touchmove', function (e) {
      if (e.touches && e.touches.length > 0) {
        var t = e.touches[0];
        var nx = (t.clientX / width - 0.5) * 2;
        var ny = (t.clientY / height - 0.5) * 2;
        mouse.targetX = Math.max(-1, Math.min(1, nx));
        mouse.targetY = Math.max(-1, Math.min(1, ny));
      }
    }, { passive: true });

    // 3. Dessin d'une sphère 3D volumétrique en verre dépoli
    function draw3DSphere(x, y, r, depth, colorType, time, phase) {
      // Ombre portée diffuse au sol blanc
      var shadowOffsetY = r * 0.75 + depth * 8;
      var shadowRx = r * 0.9;
      var shadowRy = r * 0.28;
      var shadowGrad = ctx.createRadialGradient(x, y + shadowOffsetY, 0, x, y + shadowOffsetY, shadowRx);
      shadowGrad.addColorStop(0, 'rgba(15, 23, 42, 0.08)');
      shadowGrad.addColorStop(0.5, 'rgba(15, 23, 42, 0.03)');
      shadowGrad.addColorStop(1, 'rgba(15, 23, 42, 0)');
      ctx.beginPath();
      ctx.ellipse(x, y + shadowOffsetY, shadowRx, shadowRy, 0, 0, Math.PI * 2);
      ctx.fillStyle = shadowGrad;
      ctx.fill();

      // Corps de la sphère avec dégradé volumétrique 3D (lumière venant du haut-gauche)
      var lightX = x - r * 0.35;
      var lightY = y - r * 0.35;
      var sphereGrad = ctx.createRadialGradient(lightX, lightY, r * 0.08, x, y, r);

      if (colorType === 'emerald') {
        // Reflet verre avec aura émeraude subtile
        sphereGrad.addColorStop(0, 'rgba(255, 255, 255, 0.95)');
        sphereGrad.addColorStop(0.25, 'rgba(236, 253, 245, 0.85)');
        sphereGrad.addColorStop(0.65, 'rgba(167, 243, 208, 0.55)');
        sphereGrad.addColorStop(0.92, 'rgba(16, 185, 129, 0.28)');
        sphereGrad.addColorStop(1, 'rgba(5, 150, 105, 0.15)');
      } else {
        // Reflet verre cristal opalin
        sphereGrad.addColorStop(0, 'rgba(255, 255, 255, 0.98)');
        sphereGrad.addColorStop(0.3, 'rgba(248, 250, 252, 0.88)');
        sphereGrad.addColorStop(0.7, 'rgba(226, 232, 240, 0.50)');
        sphereGrad.addColorStop(0.94, 'rgba(203, 213, 225, 0.25)');
        sphereGrad.addColorStop(1, 'rgba(148, 163, 184, 0.12)');
      }

      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = sphereGrad;
      ctx.fill();

      // Liseré spéculaire externe de réfraction (verre taillé)
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = (colorType === 'emerald') ? 'rgba(16, 185, 129, 0.25)' : 'rgba(255, 255, 255, 0.85)';
      ctx.stroke();

      // Point d'éclat lumineux supérieur (Specular glint)
      var glintGrad = ctx.createRadialGradient(lightX, lightY, 0, lightX, lightY, r * 0.3);
      glintGrad.addColorStop(0, 'rgba(255, 255, 255, 0.9)');
      glintGrad.addColorStop(0.6, 'rgba(255, 255, 255, 0.4)');
      glintGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.beginPath();
      ctx.arc(lightX, lightY, r * 0.3, 0, Math.PI * 2);
      ctx.fillStyle = glintGrad;
      ctx.fill();

      // Arc de réflexion inférieur doux (Fresnel bounce)
      ctx.beginPath();
      ctx.arc(x + r * 0.18, y + r * 0.2, r * 0.72, Math.PI * 0.15, Math.PI * 0.85);
      ctx.lineWidth = 1.8;
      ctx.strokeStyle = (colorType === 'emerald') ? 'rgba(52, 211, 153, 0.35)' : 'rgba(255, 255, 255, 0.6)';
      ctx.stroke();
    }

    // 4. Dessin de rubans soyeux ondulants en 3D
    function drawFluidRibbon(time) {
      ctx.save();
      ctx.beginPath();

      var startX = -40;
      var startY = height * 0.38 + Math.sin(time * 0.6) * 45;
      ctx.moveTo(startX, startY);

      var cp1x = width * 0.28 + mouse.x * 35;
      var cp1y = height * 0.22 + Math.cos(time * 0.7) * 55 + mouse.y * 25;
      var cp2x = width * 0.68 - mouse.x * 35;
      var cp2y = height * 0.52 + Math.sin(time * 0.8 + 1) * 60 - mouse.y * 30;
      var endX = width + 40;
      var endY = height * 0.42 + Math.cos(time * 0.5) * 40;

      ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, endX, endY);

      var ribbonGrad = ctx.createLinearGradient(0, 0, width, height * 0.6);
      ribbonGrad.addColorStop(0, 'rgba(16, 185, 129, 0)');
      ribbonGrad.addColorStop(0.3, 'rgba(16, 185, 129, 0.12)');
      ribbonGrad.addColorStop(0.7, 'rgba(52, 211, 153, 0.16)');
      ribbonGrad.addColorStop(1, 'rgba(16, 185, 129, 0)');

      ctx.lineWidth = 28;
      ctx.lineCap = 'round';
      ctx.strokeStyle = ribbonGrad;
      ctx.stroke();

      // Second ruban plus fin et lumineux
      ctx.beginPath();
      ctx.moveTo(startX, startY + 25);
      ctx.bezierCurveTo(cp1x + 30, cp1y + 35, cp2x - 30, cp2y - 35, endX, endY + 25);
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = 'rgba(16, 185, 129, 0.28)';
      ctx.stroke();

      ctx.restore();
    }

    // 5. Boucle principale d'animation 60/120 FPS
    var startTime = performance.now();
    var isRunning = true;

    function render(now) {
      if (!isRunning) return;

      var elapsed = (now - startTime) * 0.001;

      // Amorti soyeux de l'interaction (Linear Interpolation - Lerp)
      mouse.x += (mouse.targetX - mouse.x) * 0.065;
      mouse.y += (mouse.targetY - mouse.y) * 0.065;

      // Effacement propre du canvas (laisse voir le fond blanc de la page)
      ctx.clearRect(0, 0, width, height);

      // Dessiner le ruban fluide d'ambiance
      drawFluidRibbon(elapsed);

      // Dessiner chaque sphère 3D avec sa parallaxe spatiale
      for (var i = 0; i < spheres.length; i++) {
        var s = spheres[i];

        // Mouvement de flottaison harmonique autonome
        var floatX = Math.sin(elapsed * s.speed + s.phase) * (8 * s.depth);
        var floatY = Math.cos(elapsed * s.speed * 0.9 + s.phase) * (14 * s.depth);

        // Déplacement interactif proportionnel à la profondeur 3D
        var parallaxX = mouse.x * (s.depth * 45);
        var parallaxY = mouse.y * (s.depth * 35);

        var finalX = (s.baseRelX * width) + floatX + parallaxX;
        var finalY = (s.baseRelY * height) + floatY + parallaxY;

        draw3DSphere(finalX, finalY, s.r, s.depth, s.color, elapsed, s.phase);
      }

      requestAnimationFrame(render);
    }

    // Gestion de visibilité : pause si l'onglet est masqué (économie batterie)
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        isRunning = false;
      } else {
        if (!isRunning) {
          isRunning = true;
          requestAnimationFrame(render);
        }
      }
    });

    requestAnimationFrame(render);
  }

  // Démarrer dès le DOM prêt
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initKinetic3D);
  } else {
    initKinetic3D();
  }
})();
