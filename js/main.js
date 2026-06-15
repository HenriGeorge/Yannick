/* ============================================================
   Yannick Henderickx — Sonic Portfolio
   Interactive engine: custom cursor + magnetic buttons, scroll
   reveals, floating dots, film grain, an audio-reactive hero
   waveform field, a touchable sound playground, and a fully
   in-browser Web Audio engine (ambient drone + four generative
   project "tracks" + pentatonic mouse tones).

   All audio is synthesized live — nothing is loaded. The drone
   is bright/open at the top of the page and its filter closes
   as you scroll into the dark.
   ============================================================ */
(function () {
  'use strict';

  var TAU = Math.PI * 2;
  var $ = function (sel, root) { return (root || document).querySelector(sel); };

  function Sonic() {
    this.state = { soundOn: false, menuOpen: false, showIndex: false, playing: -1, formDone: false };

    // Canvas + layer elements (refs in the prototype).
    this.hc = $('[data-hero-canvas]');
    this.pc = $('[data-play-canvas]');
    this.gc = $('[data-grain-canvas]');
    this.dref = $('[data-dots-canvas]');
    this.cd = $('[data-cursor-dot]');
    this.cr = $('[data-cursor-ring]');
    this.li = $('[data-cursor-light]');
    this.thumbs = [0, 1, 2, 3].map(function (i) { return $('[data-thumb="' + i + '"]'); });
    this.meters = [0, 1, 2, 3].map(function (i) { return $('[data-meter="' + i + '"]'); });

    this.mount();
  }

  Sonic.prototype.mount = function () {
    var self = this;
    this.alive = true;
    this.fine = typeof matchMedia === 'function' && matchMedia('(pointer: fine)').matches;
    this.mx = innerWidth / 2; this.my = innerHeight / 2;
    this.dx = this.mx; this.dy = this.my; this.rx = this.mx; this.ry = this.my;
    this.lx = this.mx; this.ly = this.my;
    this.ringScale = 1; this.ringTarget = 1;
    this.level = 0; this.particles = []; this.rings = [];
    this.heroVis = true; this.playVis = false; this.lastGrain = 0;
    this.scrollP = 0; this.lastBgP = -1;

    /* ---- pointer move: cursor, pentatonic zone tones, magnetics ---- */
    this.onMove = function (e) {
      self.mx = e.clientX; self.my = e.clientY;
      var gz = Math.floor(self.mx / innerWidth * 9);
      if (gz !== self.gZone) {
        var now = performance.now();
        if (self.gZone !== undefined && self.ctx && self.ctx.state === 'running' &&
            self.state.soundOn && now - (self.gZoneT || 0) > 150) {
          var sc = [587.33, 698.46, 783.99, 880, 1046.5, 880, 783.99, 698.46, 587.33];
          self.blip(sc[gz] || 880, 0.016, 1.3, 'sine');
          self.gZoneT = now;
        }
        self.gZone = gz;
      }
      if (self.magnet) {
        var r = self.magnet.getBoundingClientRect();
        var ox = (self.mx - (r.left + r.width / 2)) * 0.28;
        var oy = (self.my - (r.top + r.height / 2)) * 0.28;
        self.magnet.style.transform = 'translate(' + ox.toFixed(1) + 'px,' + oy.toFixed(1) + 'px)';
      }
    };
    document.addEventListener('mousemove', this.onMove, { passive: true });

    /* ---- hover state for cursor ring + magnetic attach ---- */
    this.onOver = function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var m = t.closest('[data-magnetic]');
      if (m && m !== self.magnet) {
        m.style.transition = 'transform .25s cubic-bezier(.3,1,.4,1), border-color .3s ease, color .3s ease, background .35s ease';
        self.magnet = m;
      }
      var h = t.closest('a, button, input, textarea, [data-cursor]');
      self.ringTarget = h ? 2.4 : 1;
      if (self.cr) self.cr.style.borderColor = h ? 'rgba(201,155,196,0.8)' : 'rgba(234,229,227,0.45)';
    };
    this.onOut = function (e) {
      var rel = e.relatedTarget;
      if (self.magnet && (!rel || !self.magnet.contains(rel))) {
        var within = rel && rel.closest && rel.closest('[data-magnetic]') === self.magnet;
        if (!within) { self.magnet.style.transform = 'translate(0px, 0px)'; self.magnet = null; }
      }
      var h = rel && rel.closest && rel.closest('a, button, input, textarea, [data-cursor]');
      if (!h) { self.ringTarget = 1; if (self.cr) self.cr.style.borderColor = 'rgba(234,229,227,0.45)'; }
    };
    document.addEventListener('mouseover', this.onOver, true);
    document.addEventListener('mouseout', this.onOut, true);

    /* ---- scroll: reveal INDEX, track scroll depth ---- */
    this.onScroll = function () {
      var s = scrollY > innerHeight * 0.6;
      if (s !== self.state.showIndex) { self.state.showIndex = s; self.render(); }
      var max = document.documentElement.scrollHeight - innerHeight;
      self.scrollP = max > 0 ? Math.min(1, Math.max(0, scrollY / max)) : 0;
    };
    addEventListener('scroll', this.onScroll, { passive: true });

    this.onKey = function (e) {
      if (e.key === 'Escape' && self.state.menuOpen) { self.state.menuOpen = false; self.render(); }
    };
    addEventListener('keydown', this.onKey);

    this.onResize = function () { self.sizeAll(); };
    addEventListener('resize', this.onResize);
    this.sizeAll();
    this.drawThumbs();

    if (!this.fine) {
      if (this.cd) this.cd.style.display = 'none';
      if (this.cr) this.cr.style.display = 'none';
    }

    /* ---- scroll reveal with a Stripe-style staggered ease ---- */
    var els = Array.prototype.slice.call(document.querySelectorAll('[data-reveal]'));
    els.forEach(function (el, i) {
      var r = el.getBoundingClientRect();
      if (r.top > innerHeight * 0.92) {
        el.style.opacity = '0';
        el.style.transform = 'translateY(72px)';
        var d = (i % 3) * 0.1;
        el.style.transition = 'opacity .7s cubic-bezier(.215,.61,.355,1) ' + d + 's, transform .9s cubic-bezier(.215,.61,.355,1) ' + d + 's';
      }
    });
    this.ro = new IntersectionObserver(function (en) {
      en.forEach(function (x) {
        if (x.isIntersecting) {
          x.target.style.opacity = '1';
          x.target.style.transform = 'translateY(0px)';
          self.ro.unobserve(x.target);
        }
      });
    }, { threshold: 0.12 });
    els.forEach(function (el) { self.ro.observe(el); });

    /* ---- only animate the heavy canvases while on screen ---- */
    this.vo = new IntersectionObserver(function (en) {
      en.forEach(function (x) {
        if (x.target === self.hc) self.heroVis = x.isIntersecting;
        if (x.target === self.pc) self.playVis = x.isIntersecting;
      });
    });
    if (this.hc) this.vo.observe(this.hc);
    if (this.pc) this.vo.observe(this.pc);

    /* ---- sound playground interactions ---- */
    this.onPlayMove = function (e) {
      var c = self.pc; if (!c) return;
      var r = c.getBoundingClientRect();
      var x = e.clientX - r.left, y = e.clientY - r.top;
      var now = performance.now();
      if (!self.lastSpawn || now - self.lastSpawn > 28) { self.spawn(x, y, 1, false); self.lastSpawn = now; }
    };
    this.onPlayDown = function (e) {
      self.ensureCtx();
      var c = self.pc; if (!c) return;
      var r = c.getBoundingClientRect();
      var x = e.clientX - r.left, y = e.clientY - r.top;
      var sc = [146.83, 174.61, 196, 220, 261.63, 293.66, 349.23, 392, 440];
      var f = sc[Math.min(sc.length - 1, Math.floor(x / r.width * sc.length))] || 220;
      self.blip(f, 0.09, 1.8, 'triangle');
      self.blip(f * 2, 0.028, 1.4, 'sine');
      self.spawn(x, y, 16, true);
      self.rings.push({ x: x, y: y, r: 6, a: 0.5 });
    };
    if (this.pc) {
      this.pc.addEventListener('pointermove', this.onPlayMove);
      this.pc.addEventListener('pointerdown', this.onPlayDown);
    }

    /* ---- UI wiring (replaces DC {{ }} bindings) ---- */
    Array.prototype.forEach.call(document.querySelectorAll('[data-sound-toggle]'), function (b) {
      b.addEventListener('click', function () { self.toggleSound(); });
    });
    var openBtn = $('[data-open-menu]');
    if (openBtn) openBtn.addEventListener('click', function () { self.state.menuOpen = true; self.render(); });
    Array.prototype.forEach.call(document.querySelectorAll('[data-close-menu]'), function (b) {
      b.addEventListener('click', function () { self.state.menuOpen = false; self.render(); });
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-play]'), function (b) {
      var i = parseInt(b.getAttribute('data-play'), 10);
      b.addEventListener('click', function () { self.playProject(i); });
    });
    var form = $('[data-contact-form]');
    if (form) form.addEventListener('submit', function (e) {
      e.preventDefault(); self.state.formDone = true; self.render();
    });

    this.render();
    this.loop = this.loop.bind(this);
    this.raf = requestAnimationFrame(this.loop);
  };

  /* ===================== STATE → DOM ===================== */

  Sonic.prototype.render = function () {
    var s = this.state;
    var label = $('[data-sound-label]'); if (label) label.textContent = s.soundOn ? 'SOUND — ON' : 'SOUND — OFF';
    var dot = $('[data-sound-dot]'); if (dot) dot.classList.toggle('is-on', s.soundOn);
    var heroLabel = $('[data-hero-sound-label]'); if (heroLabel) heroLabel.textContent = s.soundOn ? 'MUTE ATMOS' : 'ENABLE SOUND';

    var menu = $('[data-menu]'); if (menu) menu.hidden = !s.menuOpen;
    var idx = $('[data-open-menu]'); if (idx) idx.hidden = !(s.showIndex && !s.menuOpen);

    for (var i = 0; i < 4; i++) {
      var b = document.querySelector('[data-play="' + i + '"]');
      if (b) b.textContent = s.playing === i ? 'STOP' : 'PLAY';
    }

    var pending = $('[data-form-pending]'); if (pending) pending.hidden = s.formDone;
    var done = $('[data-form-done]'); if (done) done.hidden = !s.formDone;
  };

  /* ===================== SIZING ===================== */

  Sonic.prototype.sizeAll = function () {
    var dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    this.dpr = dpr;
    [this.hc, this.pc, this.dref].forEach(function (c) {
      if (!c) return;
      var r = c.getBoundingClientRect();
      if (r.width > 0) { c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr); }
    });
  };

  /* ===================== MAIN LOOP ===================== */

  Sonic.prototype.loop = function (ts) {
    if (!this.alive) return;
    var t = ts / 1000;
    if (this.an && this.fd) {
      this.an.getByteFrequencyData(this.fd);
      var sum = 0; for (var i = 2; i < 50; i++) sum += this.fd[i];
      var lv = sum / 48 / 255;
      this.level += (lv - this.level) * 0.12;
    } else { this.level *= 0.95; }

    if (this.fine) {
      this.dx += (this.mx - this.dx) * 0.5; this.dy += (this.my - this.dy) * 0.5;
      this.rx += (this.mx - this.rx) * 0.16; this.ry += (this.my - this.ry) * 0.16;
      this.ringScale += (this.ringTarget - this.ringScale) * 0.16;
      if (this.cd) this.cd.style.transform = 'translate(' + (this.dx - 3) + 'px,' + (this.dy - 3) + 'px)';
      if (this.cr) this.cr.style.transform = 'translate(' + (this.rx - 18) + 'px,' + (this.ry - 18) + 'px) scale(' + this.ringScale.toFixed(3) + ')';
    }
    this.lx += (this.mx - this.lx) * 0.045; this.ly += (this.my - this.ly) * 0.045;
    if (this.li) this.li.style.transform = 'translate(' + (this.lx - 600) + 'px,' + (this.ly - 600) + 'px)';

    var sp = this.scrollP || 0;
    if (sp !== this.lastBgP) {
      this.lastBgP = sp;
      if (this.ambLp) this.ambLp.frequency.value = 660 - sp * 360;
    }
    this.drawDots(t);

    if (this.heroVis) this.drawHero(t);
    if (this.playVis) this.drawPlay(t);
    if (ts - this.lastGrain > 90) { this.drawGrain(); this.lastGrain = ts; }
    if (this.state.playing >= 0) this.drawMeter();

    this.raf = requestAnimationFrame(this.loop);
  };

  /* ===================== HERO WAVEFORM FIELD ===================== */

  Sonic.prototype.drawHero = function (t) {
    var c = this.hc; if (!c || !c.width) return;
    var x2 = c.getContext('2d');
    var w = c.width, h = c.height, dpr = this.dpr || 1;
    x2.clearRect(0, 0, w, h);
    var r = c.getBoundingClientRect();
    var mx = (this.mx - r.left) * dpr, my = (this.my - r.top) * dpr;
    var N = 26, pad = h * 0.1;
    var lvl = this.level;
    x2.lineWidth = Math.max(1, 0.9 * dpr);
    var step = 7 * dpr;
    for (var i = 0; i < N; i++) {
      var ly = pad + (h - 2 * pad) * i / (N - 1);
      var band = this.fd ? this.fd[2 + Math.floor(i / N * 64)] / 255 : 0;
      var idle = 0.5 + 0.5 * Math.sin(t * 0.45 + i * 0.42);
      var amp = (3 + idle * 5 + band * band * 56) * dpr;
      var gy = Math.exp(-Math.pow((ly - my) / (h * 0.15), 2));
      var alpha = Math.min(0.5, 0.055 + band * 0.32 + gy * 0.09);
      x2.strokeStyle = 'rgba(48,36,54,' + alpha.toFixed(3) + ')';
      x2.beginPath();
      for (var x = 0; x <= w; x += step) {
        var gx = Math.exp(-Math.pow((x - mx) / (w * 0.13), 2));
        var wob = Math.sin(x * 0.004 / dpr + t * 0.9 + i * 0.55) * Math.sin(x * 0.0009 / dpr - t * 0.22 + i * 1.7);
        var y = ly + wob * (amp + gx * gy * 50 * dpr * (0.45 + lvl * 2.2));
        if (x === 0) x2.moveTo(x, y); else x2.lineTo(x, y);
      }
      x2.stroke();
    }
    if (lvl > 0.015) {
      var ly2 = h * 0.5;
      x2.strokeStyle = 'rgba(72,53,79,' + Math.min(0.75, lvl * 1.9).toFixed(3) + ')';
      x2.lineWidth = Math.max(1, 1.1 * dpr);
      x2.beginPath();
      for (var x3 = 0; x3 <= w; x3 += step) {
        var wob2 = Math.sin(x3 * 0.006 / dpr + t * 1.6) * Math.sin(x3 * 0.0014 / dpr - t * 0.4);
        var y3 = ly2 + wob2 * (6 + lvl * 90) * dpr;
        if (x3 === 0) x2.moveTo(x3, y3); else x2.lineTo(x3, y3);
      }
      x2.stroke();
      x2.lineWidth = Math.max(1, 0.9 * dpr);
    }
  };

  /* ===================== SOUND PLAYGROUND ===================== */

  Sonic.prototype.spawn = function (x, y, n, burst) {
    for (var i = 0; i < n; i++) {
      this.particles.push({
        x: x, y: y,
        vx: (Math.random() - 0.5) * (burst ? 3.2 : 0.7),
        vy: burst ? (Math.random() - 0.5) * 3.2 : -0.35 - Math.random() * 0.7,
        life: 1, decay: 0.0045 + Math.random() * 0.009,
        accent: Math.random() < (burst ? 0.18 : 0.05),
        r: 1 + Math.random() * (burst ? 2.4 : 1.6)
      });
    }
    if (this.particles.length > 340) this.particles.splice(0, this.particles.length - 340);
  };

  Sonic.prototype.drawPlay = function (t) {
    var c = this.pc; if (!c || !c.width) return;
    var x2 = c.getContext('2d');
    var w = c.width, h = c.height, dpr = this.dpr || 1;
    x2.clearRect(0, 0, w, h);
    var lvl = this.level;
    var sp = 52 * dpr;
    x2.fillStyle = 'rgba(46,33,51,0.16)';
    for (var gx = sp / 2; gx < w; gx += sp) {
      for (var gy = sp / 2; gy < h; gy += sp) {
        var j = Math.sin(t * 0.8 + gx * 0.01 + gy * 0.013) * (1 + lvl * 10) * dpr;
        x2.fillRect(gx + j, gy - j, dpr, dpr);
      }
    }
    if (lvl > 0.04 && Math.random() < 0.35) this.spawn(Math.random() * w / dpr, h / dpr * (0.7 + Math.random() * 0.3), 1, false);
    var ps = this.particles;
    for (var i = ps.length - 1; i >= 0; i--) {
      var p = ps[i];
      p.x += p.vx; p.y += p.vy;
      p.vy -= 0.004;
      p.life -= p.decay;
      if (p.life <= 0) { ps.splice(i, 1); continue; }
      var a = p.life * (p.accent ? 0.85 : 0.5) * (0.7 + lvl * 1.2);
      x2.fillStyle = p.accent ? 'rgba(72,53,79,' + a.toFixed(3) + ')' : 'rgba(46,33,51,' + a.toFixed(3) + ')';
      x2.beginPath();
      x2.arc(p.x * dpr, p.y * dpr, p.r * dpr * (0.6 + p.life * 0.6), 0, TAU);
      x2.fill();
    }
    var rs = this.rings;
    for (var k = rs.length - 1; k >= 0; k--) {
      var g = rs[k];
      g.r += 2.6; g.a *= 0.962;
      if (g.a < 0.01) { rs.splice(k, 1); continue; }
      x2.strokeStyle = 'rgba(46,33,51,' + g.a.toFixed(3) + ')';
      x2.lineWidth = dpr;
      x2.beginPath();
      x2.arc(g.x * dpr, g.y * dpr, g.r * dpr, 0, TAU);
      x2.stroke();
    }
  };

  /* ===================== DOTS + GRAIN + METERS ===================== */

  Sonic.prototype.drawDots = function (t) {
    var c = this.dref; if (!c) return;
    if (!c.width) {
      var r = c.getBoundingClientRect();
      if (r.width > 0) { c.width = Math.round(r.width * (this.dpr || 1)); c.height = Math.round(r.height * (this.dpr || 1)); }
      if (!c.width) return;
    }
    var x2 = c.getContext('2d');
    var w = c.width, h = c.height, dpr = this.dpr || 1;
    if (!this.dots) {
      this.dots = [];
      for (var i = 0; i < 64; i++) this.dots.push({ x: Math.random(), y: Math.random(), r: 0.6 + Math.random() * 1.9, s: 0.00012 + Math.random() * 0.00035, ph: Math.random() * 6.28, a: 0.22 + Math.random() * 0.5 });
    }
    x2.clearRect(0, 0, w, h);
    var sp = this.scrollP || 0;
    var cr = Math.round(46 + (234 - 46) * sp), cg = Math.round(33 + (229 - 33) * sp), cb = Math.round(51 + (227 - 51) * sp);
    for (var d, n = 0; n < this.dots.length; n++) {
      d = this.dots[n];
      d.y -= d.s * (1 + this.level * 5);
      if (d.y < -0.02) { d.y = 1.02; d.x = Math.random(); }
      var xx = (d.x + Math.sin(t * 0.12 + d.ph) * 0.012) * w;
      var a = d.a * (0.55 + 0.45 * Math.sin(t * 0.5 + d.ph));
      x2.fillStyle = 'rgba(' + cr + ',' + cg + ',' + cb + ',' + a.toFixed(3) + ')';
      x2.beginPath(); x2.arc(xx, d.y * h, d.r * dpr, 0, TAU); x2.fill();
    }
  };

  Sonic.prototype.drawGrain = function () {
    var c = this.gc; if (!c) return;
    var x2 = c.getContext('2d');
    if (!this.gid) this.gid = x2.createImageData(c.width, c.height);
    var d = this.gid.data;
    for (var i = 0; i < d.length; i += 4) {
      var v = (Math.random() * 255) | 0;
      d[i] = v; d[i + 1] = v; d[i + 2] = v; d[i + 3] = 26;
    }
    x2.putImageData(this.gid, 0, 0);
  };

  Sonic.prototype.drawMeter = function () {
    var m = this.meters[this.state.playing];
    if (!m || !this.fd) return;
    var idx = [4, 10, 20, 34, 52];
    var ch = m.children;
    for (var k = 0; k < 5; k++) {
      if (ch[k]) ch[k].style.transform = 'scaleY(' + (0.12 + this.fd[idx[k]] / 255 * 0.92).toFixed(3) + ')';
    }
  };

  Sonic.prototype.resetMeters = function () {
    this.meters.forEach(function (m) {
      if (!m) return;
      for (var k = 0; k < m.children.length; k++) m.children[k].style.transform = 'scaleY(0.12)';
    });
  };

  /* ===================== GENERATIVE THUMBNAILS ===================== */

  Sonic.prototype.drawThumbs = function () {
    var W = 1280, H = 800;
    var grain = function (x2, n, a) {
      x2.fillStyle = 'rgba(234,229,227,' + a + ')';
      for (var i = 0; i < n; i++) x2.fillRect(Math.random() * W, Math.random() * H, 1, 1);
    };
    var c = this.thumbs[0];
    if (c) { // HALOS — concentric rings of light
      var x2 = c.getContext('2d');
      x2.fillStyle = '#130F14'; x2.fillRect(0, 0, W, H);
      var cx = W * 0.5, cy = H * 0.46;
      var g = x2.createRadialGradient(cx, cy, 0, cx, cy, H * 0.55);
      g.addColorStop(0, 'rgba(216,200,216,0.22)'); g.addColorStop(0.4, 'rgba(177,149,177,0.06)'); g.addColorStop(1, 'rgba(0,0,0,0)');
      x2.fillStyle = g; x2.fillRect(0, 0, W, H);
      for (var i = 0; i < 30; i++) {
        var rr = 40 + i * 18 + Math.sin(i * 1.7) * 6;
        x2.strokeStyle = 'rgba(231,226,225,' + (0.02 + 0.16 * Math.pow(Math.sin(i * 0.5) * 0.5 + 0.5, 2)).toFixed(3) + ')';
        x2.lineWidth = i % 7 === 3 ? 2 : 1;
        x2.beginPath(); x2.arc(cx, cy, rr, 0, TAU); x2.stroke();
      }
      x2.strokeStyle = 'rgba(201,155,196,0.5)'; x2.lineWidth = 1.5;
      x2.beginPath(); x2.arc(cx, cy, 214, 0, TAU); x2.stroke();
      grain(x2, 2600, 0.05);
    }
    c = this.thumbs[1];
    if (c) { // PULSE // FIELD — vertical bar field
      var x2b = c.getContext('2d');
      x2b.fillStyle = '#110F15'; x2b.fillRect(0, 0, W, H);
      var base = H * 0.78;
      x2b.strokeStyle = 'rgba(234,229,227,0.18)';
      x2b.beginPath(); x2b.moveTo(0, base); x2b.lineTo(W, base); x2b.stroke();
      for (var b = 0; b < 96; b++) {
        var bx = 24 + b * (W - 48) / 95;
        var v = Math.pow(Math.abs(Math.sin(b * 0.43) * Math.sin(b * 0.11)), 1.4);
        var bh = 24 + v * H * 0.55;
        var acc = b === 57;
        x2b.fillStyle = acc ? 'rgba(201,155,196,0.85)' : 'rgba(234,229,227,' + (0.1 + v * 0.5).toFixed(3) + ')';
        x2b.fillRect(bx, base - bh, 3, bh);
      }
      grain(x2b, 2200, 0.045);
    }
    c = this.thumbs[2];
    if (c) { // MONOLITH — slab against a faint horizon
      var x2c = c.getContext('2d');
      var g2 = x2c.createLinearGradient(0, 0, 0, H);
      g2.addColorStop(0, '#161119'); g2.addColorStop(0.62, '#100C12'); g2.addColorStop(1, '#0B080D');
      x2c.fillStyle = g2; x2c.fillRect(0, 0, W, H);
      x2c.strokeStyle = 'rgba(234,229,227,0.13)';
      x2c.beginPath(); x2c.moveTo(0, H * 0.62); x2c.lineTo(W, H * 0.62); x2c.stroke();
      var mw = W * 0.16, mh = H * 0.56, mxp = W * 0.5 - mw / 2, myp = H * 0.62 - mh;
      x2c.fillStyle = '#060409'; x2c.fillRect(mxp, myp, mw, mh);
      x2c.strokeStyle = 'rgba(234,229,227,0.3)'; x2c.lineWidth = 1;
      x2c.beginPath(); x2c.moveTo(mxp + mw, myp); x2c.lineTo(mxp + mw, myp + mh); x2c.stroke();
      x2c.strokeStyle = 'rgba(201,155,196,0.55)';
      x2c.beginPath(); x2c.moveTo(mxp, myp + mh * 0.82); x2c.lineTo(mxp + mw, myp + mh * 0.82); x2c.stroke();
      var rg = x2c.createRadialGradient(W * 0.5, H * 0.62, 0, W * 0.5, H * 0.62, W * 0.4);
      rg.addColorStop(0, 'rgba(177,149,177,0.08)'); rg.addColorStop(1, 'rgba(0,0,0,0)');
      x2c.fillStyle = rg; x2c.fillRect(0, 0, W, H);
      grain(x2c, 3200, 0.06);
    }
    c = this.thumbs[3];
    if (c) { // AETHER — flowing ribbons
      var x2d = c.getContext('2d');
      x2d.fillStyle = '#120F14'; x2d.fillRect(0, 0, W, H);
      for (var rb = 0; rb < 22; rb++) {
        var yo = H * 0.18 + rb * H * 0.032;
        var acc2 = rb === 11;
        x2d.strokeStyle = acc2 ? 'rgba(201,155,196,0.5)' : 'rgba(234,229,227,' + (0.04 + 0.14 * Math.abs(Math.sin(rb * 0.6))).toFixed(3) + ')';
        x2d.lineWidth = acc2 ? 1.4 : 1;
        x2d.beginPath();
        for (var x = 0; x <= W; x += 8) {
          var y = yo + Math.sin(x * 0.004 + rb * 0.5) * 70 * Math.sin(x * 0.0012 + rb) + Math.sin(x * 0.01 + rb * 2) * 8;
          if (x === 0) x2d.moveTo(x, y); else x2d.lineTo(x, y);
        }
        x2d.stroke();
      }
      grain(x2d, 2400, 0.05);
    }
  };

  /* ===================== AUDIO ENGINE ===================== */

  Sonic.prototype.ensureCtx = function () {
    try {
      if (!this.ctx) {
        var AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return false;
        var ctx = this.ctx = new AC();
        this.master = ctx.createGain(); this.master.gain.value = 0.9;
        var comp = ctx.createDynamicsCompressor();
        this.an = ctx.createAnalyser(); this.an.fftSize = 256; this.an.smoothingTimeConstant = 0.85;
        this.master.connect(comp); comp.connect(this.an); this.an.connect(ctx.destination);
        this.fd = new Uint8Array(this.an.frequencyBinCount);
        this.dly = ctx.createDelay(1); this.dly.delayTime.value = 0.31;
        var fb = ctx.createGain(); fb.gain.value = 0.34;
        this.dly.connect(fb); fb.connect(this.dly);
        var dw = ctx.createGain(); dw.gain.value = 0.5;
        this.dly.connect(dw); dw.connect(this.master);
        var len = ctx.sampleRate * 2;
        var buf = ctx.createBuffer(1, len, ctx.sampleRate);
        var ch = buf.getChannelData(0);
        var p = 0;
        for (var i = 0; i < len; i++) { p = p * 0.985 + (Math.random() * 2 - 1) * 0.015; ch[i] = p * 3.2; }
        this.noiseBuf = buf;
      }
      if (this.ctx.state === 'suspended') this.ctx.resume();
      return true;
    } catch (e) { return false; }
  };

  Sonic.prototype.blip = function (f, vol, dur, type) {
    if (!this.ctx || !this.master) return;
    var ctx = this.ctx, t = ctx.currentTime;
    var o = ctx.createOscillator(); o.type = type || 'sine'; o.frequency.value = f;
    var g = ctx.createGain();
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(vol, t + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g); g.connect(this.master);
    var s = ctx.createGain(); s.gain.value = 0.55; g.connect(s); s.connect(this.dly);
    o.start(t); o.stop(t + dur + 0.1);
    o.onended = function () { try { o.disconnect(); g.disconnect(); s.disconnect(); } catch (e) {} };
  };

  Sonic.prototype.startAmbient = function () {
    if (this.amb || !this.ctx) return;
    var ctx = this.ctx, t = ctx.currentTime;
    var ag = ctx.createGain();
    ag.gain.setValueAtTime(0, t);
    ag.gain.linearRampToValueAtTime(0.15, t + 2.5);
    ag.connect(this.master);
    var lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 660; lp.Q.value = 0.7;
    this.ambLp = lp;
    lp.connect(ag);
    var sd = ctx.createGain(); sd.gain.value = 0.18; lp.connect(sd); sd.connect(this.dly);
    var oscs = [];
    var mk = function (type, f, g2, det) {
      var o = ctx.createOscillator(); o.type = type; o.frequency.value = f;
      if (det) o.detune.value = det;
      var og = ctx.createGain(); og.gain.value = g2;
      o.connect(og); og.connect(lp); o.start(); oscs.push(o);
    };
    mk('sawtooth', 73.42, 0.5, 0);
    mk('sine', 110.0, 0.6, 0);
    mk('sine', 146.83, 0.25, 7);
    mk('sine', 220.0, 0.14, -4);
    var lfo = ctx.createOscillator(); lfo.frequency.value = 0.06;
    var lg = ctx.createGain(); lg.gain.value = 110;
    lfo.connect(lg); lg.connect(lp.frequency); lfo.start(); oscs.push(lfo);
    var ns = ctx.createBufferSource(); ns.buffer = this.noiseBuf; ns.loop = true;
    var bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 900; bp.Q.value = 0.5;
    var ng = ctx.createGain(); ng.gain.value = 0.05;
    ns.connect(bp); bp.connect(ng); ng.connect(ag); ns.start();
    this.amb = { stop: function () {
      var tt = ctx.currentTime;
      ag.gain.cancelScheduledValues(tt);
      ag.gain.setValueAtTime(ag.gain.value, tt);
      ag.gain.linearRampToValueAtTime(0.0001, tt + 0.8);
      setTimeout(function () { try { oscs.forEach(function (o) { o.stop(); }); ns.stop(); ag.disconnect(); } catch (e) {} }, 950);
    } };
  };

  Sonic.prototype.stopAmbient = function () { if (this.amb) { this.amb.stop(); this.amb = null; } this.ambLp = null; };

  Sonic.prototype.toggleSound = function () {
    if (!this.state.soundOn) {
      if (!this.ensureCtx()) return;
      this.startAmbient();
      this.state.soundOn = true; this.render();
    } else {
      this.stopAmbient();
      this.stopProj();
      this.state.soundOn = false; this.render();
    }
  };

  Sonic.prototype.stopProj = function () {
    if (this.proj) { this.proj.stop(); this.proj = null; }
    if (this.state.playing !== -1) { this.state.playing = -1; this.render(); }
    this.resetMeters();
  };

  Sonic.prototype.playProject = function (i) {
    if (this.state.playing === i) { this.stopProj(); return; }
    if (!this.ensureCtx()) return;
    if (this.proj) { this.proj.stop(); this.proj = null; }
    var ctx = this.ctx;
    var grp = ctx.createGain();
    grp.gain.setValueAtTime(0, ctx.currentTime);
    grp.gain.linearRampToValueAtTime(0.85, ctx.currentTime + 1.2);
    grp.connect(this.master);
    var send = ctx.createGain(); send.gain.value = 0.4;
    grp.connect(send); send.connect(this.dly);
    var inner = [this.mkHalos, this.mkPulse, this.mkMonolith, this.mkAether][i].call(this, grp);
    this.proj = { stop: function () {
      var t = ctx.currentTime;
      grp.gain.cancelScheduledValues(t);
      grp.gain.setValueAtTime(grp.gain.value, t);
      grp.gain.linearRampToValueAtTime(0.0001, t + 0.6);
      inner.stop();
      setTimeout(function () { try { grp.disconnect(); send.disconnect(); } catch (e) {} }, 800);
    } };
    this.state.playing = i; this.render();
  };

  Sonic.prototype.mkHalos = function (out) { // airy choral drone
    var ctx = this.ctx, oscs = [];
    var lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 520; lp.Q.value = 0.8;
    var ig = ctx.createGain(); ig.gain.value = 0.16;
    lp.connect(ig); ig.connect(out);
    var mk = function (type, f, g2, det) {
      var o = ctx.createOscillator(); o.type = type; o.frequency.value = f;
      if (det) o.detune.value = det;
      var og = ctx.createGain(); og.gain.value = g2;
      o.connect(og); og.connect(lp); o.start(); oscs.push(o);
    };
    mk('sawtooth', 73.42, 0.4, 0);
    mk('sine', 110.0, 0.55, -5);
    mk('sine', 174.61, 0.3, 6);
    mk('triangle', 220.0, 0.14, 0);
    var sh = ctx.createOscillator(); sh.type = 'sine'; sh.frequency.value = 587.33;
    var shg = ctx.createGain(); shg.gain.value = 0.018;
    var vib = ctx.createOscillator(); vib.frequency.value = 4.7;
    var vg = ctx.createGain(); vg.gain.value = 5;
    vib.connect(vg); vg.connect(sh.frequency);
    sh.connect(shg); shg.connect(out); sh.start(); vib.start(); oscs.push(sh, vib);
    var lfo = ctx.createOscillator(); lfo.frequency.value = 0.09;
    var lg = ctx.createGain(); lg.gain.value = 180;
    lfo.connect(lg); lg.connect(lp.frequency); lfo.start(); oscs.push(lfo);
    var ns = ctx.createBufferSource(); ns.buffer = this.noiseBuf; ns.loop = true;
    var bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 2400; bp.Q.value = 0.4;
    var ng = ctx.createGain(); ng.gain.value = 0.012;
    ns.connect(bp); bp.connect(ng); ng.connect(out); ns.start();
    return { stop: function () { setTimeout(function () { try { oscs.forEach(function (o) { o.stop(); }); ns.stop(); } catch (e) {} }, 700); } };
  };

  Sonic.prototype.mkPulse = function (out) { // generative arpeggio
    var ctx = this.ctx;
    var seq = [220, 261.63, 329.63, 392, 329.63, 261.63, 440, 392];
    var dur = 60 / 132 / 2;
    var step = 0, next = ctx.currentTime + 0.06;
    var voice = function (f, at) {
      var o = ctx.createOscillator(); o.type = 'square'; o.frequency.value = f;
      var lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 1400; lp.Q.value = 2;
      var g = ctx.createGain();
      g.gain.setValueAtTime(0, at);
      g.gain.linearRampToValueAtTime(0.055, at + 0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, at + dur * 0.92);
      o.connect(lp); lp.connect(g); g.connect(out);
      o.start(at); o.stop(at + dur);
      o.onended = function () { try { o.disconnect(); lp.disconnect(); g.disconnect(); } catch (e) {} };
    };
    var sub = function (at) {
      var o = ctx.createOscillator(); o.type = 'sine'; o.frequency.value = 55;
      var g = ctx.createGain();
      g.gain.setValueAtTime(0.1, at);
      g.gain.exponentialRampToValueAtTime(0.0001, at + 0.32);
      o.connect(g); g.connect(out);
      o.start(at); o.stop(at + 0.35);
      o.onended = function () { try { o.disconnect(); g.disconnect(); } catch (e) {} };
    };
    var timer = setInterval(function () {
      while (next < ctx.currentTime + 0.25) {
        voice(seq[step % seq.length], next);
        if (step % 4 === 0) sub(next);
        step++; next += dur;
      }
    }, 90);
    return { stop: function () { clearInterval(timer); } };
  };

  Sonic.prototype.mkMonolith = function (out) { // sub drone + pulse
    var ctx = this.ctx, oscs = [], timers = [];
    var o1 = ctx.createOscillator(); o1.type = 'sine'; o1.frequency.value = 41.2;
    var g1 = ctx.createGain(); g1.gain.value = 0.28;
    o1.connect(g1); g1.connect(out); o1.start(); oscs.push(o1);
    var o2 = ctx.createOscillator(); o2.type = 'sawtooth'; o2.frequency.value = 61.74;
    var lp2 = ctx.createBiquadFilter(); lp2.type = 'lowpass'; lp2.frequency.value = 130;
    var g2 = ctx.createGain(); g2.gain.value = 0.12;
    o2.connect(lp2); lp2.connect(g2); g2.connect(out); o2.start(); oscs.push(o2);
    var kick = function () {
      var t = ctx.currentTime;
      var o = ctx.createOscillator(); o.type = 'sine';
      o.frequency.setValueAtTime(96, t);
      o.frequency.exponentialRampToValueAtTime(36, t + 0.13);
      var g = ctx.createGain();
      g.gain.setValueAtTime(0.5, t);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.3);
      o.connect(g); g.connect(out);
      o.start(t); o.stop(t + 0.32);
      o.onended = function () { try { o.disconnect(); g.disconnect(); } catch (e) {} };
    };
    timers.push(setInterval(kick, 923));
    var hiss = function () {
      var t = ctx.currentTime;
      var ns = ctx.createBufferSource(); ns.buffer = this.noiseBuf;
      var bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 420 + Math.random() * 700; bp.Q.value = 1.2;
      var g = ctx.createGain();
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.035, t + 0.7);
      g.gain.linearRampToValueAtTime(0, t + 1.7);
      ns.connect(bp); bp.connect(g); g.connect(out);
      ns.start(t); ns.stop(t + 1.8);
      ns.onended = function () { try { ns.disconnect(); bp.disconnect(); g.disconnect(); } catch (e) {} };
    }.bind(this);
    timers.push(setInterval(hiss, 3700));
    return { stop: function () { timers.forEach(clearInterval); setTimeout(function () { try { oscs.forEach(function (o) { o.stop(); }); } catch (e) {} }, 700); } };
  };

  Sonic.prototype.mkAether = function (out) { // glass bells
    var ctx = this.ctx, oscs = [];
    var pg = ctx.createGain(); pg.gain.value = 0.024;
    var lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 900;
    lp.connect(pg); pg.connect(out);
    [261.63, 327.03].forEach(function (f) {
      var o = ctx.createOscillator(); o.type = 'sine'; o.frequency.value = f;
      o.connect(lp); o.start(); oscs.push(o);
    });
    var set = [392, 523.25, 587.33, 659.25, 783.99, 880];
    var tm = null, dead = false;
    var bell = function () {
      if (dead) return;
      var t = ctx.currentTime;
      var f = set[(Math.random() * set.length) | 0];
      var o = ctx.createOscillator(); o.type = 'sine'; o.frequency.value = f;
      var g = ctx.createGain();
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.045, t + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 2.4);
      var o2 = ctx.createOscillator(); o2.type = 'sine'; o2.frequency.value = f * 2.756;
      var g2 = ctx.createGain();
      g2.gain.setValueAtTime(0, t);
      g2.gain.linearRampToValueAtTime(0.012, t + 0.008);
      g2.gain.exponentialRampToValueAtTime(0.0001, t + 1.5);
      o.connect(g); g.connect(out); o2.connect(g2); g2.connect(out);
      o.start(t); o.stop(t + 2.5); o2.start(t); o2.stop(t + 1.6);
      o.onended = function () { try { o.disconnect(); g.disconnect(); o2.disconnect(); g2.disconnect(); } catch (e) {} };
      tm = setTimeout(bell, 600 + Math.random() * 950);
    };
    bell();
    return { stop: function () { dead = true; clearTimeout(tm); setTimeout(function () { try { oscs.forEach(function (o) { o.stop(); }); } catch (e) {} }, 700); } };
  };

  /* ===================== BOOT ===================== */

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { new Sonic(); });
  } else {
    new Sonic();
  }
})();
