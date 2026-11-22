/* Motion layer shared by the showcase page and the dashboard.
   Lenis: smooth scroll. GSAP + ScrollTrigger: entrances, counters, scroll scenes. Motion: hover and press feel.
   AOS: scroll reveals on the showcase page. Vanta + three.js: the one animated background.
   Every effect is skipped under prefers-reduced-motion, and nothing here is required for the pages to work. */
(function () {
  "use strict";
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const has = (name) => typeof window[name] !== "undefined";
  const FX = { reduce, lenis: null, vanta: null };

  FX.smooth = function () {
    if (reduce || !has("Lenis")) return null;
    const lenis = new window.Lenis({ lerp: 0.085, wheelMultiplier: 0.95, smoothWheel: true });
    FX.lenis = lenis;
    if (has("gsap")) {
      if (has("ScrollTrigger")) {
        window.gsap.registerPlugin(window.ScrollTrigger);
        lenis.on("scroll", window.ScrollTrigger.update);
      }
      window.gsap.ticker.add((time) => lenis.raf(time * 1000));
      window.gsap.ticker.lagSmoothing(0);
    } else {
      const raf = (time) => { lenis.raf(time); requestAnimationFrame(raf); };
      requestAnimationFrame(raf);
    }
    return lenis;
  };

  FX.toTop = function () {
    if (FX.lenis) FX.lenis.scrollTo(0, { immediate: true });
    else window.scrollTo(0, 0);
  };

  /* Count a number up to its value. Keeps the final text exact (no rounding drift) and never hides it. */
  FX.countUp = function (el, value, opts) {
    const target = Number(value);
    if (!el) return;
    const fmt = (n) => Math.round(n).toLocaleString();
    if (reduce || !has("gsap") || !Number.isFinite(target)) { el.textContent = Number.isFinite(target) ? fmt(target) : String(value); return; }
    const box = { v: 0 };
    window.gsap.to(box, {
      v: target, duration: (opts && opts.duration) || 1.1, ease: "power2.out", delay: (opts && opts.delay) || 0,
      onUpdate: () => { el.textContent = fmt(box.v); },
      onComplete: () => { el.textContent = fmt(target); },
    });
  };

  FX.counters = function (root) {
    (root || document).querySelectorAll("[data-count]").forEach((el, i) => FX.countUp(el, el.dataset.count, { delay: i * 0.05 }));
  };

  /* Stagger children in. clearProps guarantees the resting state is the stylesheet's, so a failed tween never hides content. */
  FX.enter = function (root, selector, opts) {
    const items = (root || document).querySelectorAll(selector);
    if (!items.length || reduce || !has("gsap")) return;
    window.gsap.from(items, {
      y: (opts && opts.y) || 16, opacity: 0, duration: (opts && opts.duration) || 0.55, ease: "power3.out",
      stagger: (opts && opts.stagger) || 0.045, clearProps: "transform,opacity", delay: (opts && opts.delay) || 0,
    });
  };

  /* Bars that grow to their target width. */
  FX.bars = function (root) {
    const bars = (root || document).querySelectorAll("[data-w]");
    bars.forEach((el) => {
      const w = Math.max(0, Math.min(100, Number(el.dataset.w) || 0));
      if (reduce || !has("gsap")) { el.style.width = w + "%"; return; }
      el.style.width = "0%";
      window.gsap.to(el, { width: w + "%", duration: 0.9, ease: "power3.out", delay: 0.1 });
    });
  };

  /* Cursor spotlight: only writes two CSS custom properties. */
  FX.spotlight = function (root) {
    (root || document).querySelectorAll(".spot").forEach((card) => {
      if (card.dataset.spot) return;
      card.dataset.spot = "1";
      card.addEventListener("pointermove", (event) => {
        const box = card.getBoundingClientRect();
        card.style.setProperty("--mx", event.clientX - box.left + "px");
        card.style.setProperty("--my", event.clientY - box.top + "px");
      });
    });
  };

  /* Hover lift and press feel through Motion. Falls back silently to the CSS transitions. */
  FX.feel = function (root) {
    if (reduce || !has("Motion") || !window.Motion.press) return;
    const M = window.Motion;
    const scope = root || document;
    scope.querySelectorAll("button:not([data-feel]), .btn:not([data-feel])").forEach((el) => {
      el.dataset.feel = "1";
      M.press(el, () => {
        M.animate(el, { scale: 0.96 }, { duration: 0.1 });
        return () => M.animate(el, { scale: 1 }, { type: "spring", stiffness: 500, damping: 22 });
      });
    });
  };

  FX.aos = function () {
    if (!has("AOS")) return;
    window.AOS.init({ duration: 750, easing: "ease-out-cubic", once: true, offset: 70, disable: reduce });
  };

  FX.refresh = function () {
    if (has("AOS")) window.AOS.refresh();
    if (has("ScrollTrigger")) window.ScrollTrigger.refresh();
  };

  /* The one animated background: a Vanta network. One WebGL context at a time. */
  FX.network = function (el, opts) {
    FX.stopNetwork();
    if (reduce || !el || !has("VANTA") || !window.VANTA.NET) return null;
    try {
      FX.vanta = window.VANTA.NET(Object.assign({
        el, mouseControls: true, touchControls: true, gyroControls: false, minHeight: 200, minWidth: 200,
        scale: 1, scaleMobile: 1, color: 0x3b82f6, backgroundColor: 0x070b14, points: 9, maxDistance: 21, spacing: 17, showDots: true,
      }, opts || {}));
    } catch (error) {
      FX.vanta = null; // no WebGL: the CSS background underneath is the fallback
    }
    return FX.vanta;
  };

  FX.stopNetwork = function () {
    if (FX.vanta && FX.vanta.destroy) { try { FX.vanta.destroy(); } catch (error) { /* already gone */ } }
    FX.vanta = null;
  };

  window.GOIPFX = FX;
})();
