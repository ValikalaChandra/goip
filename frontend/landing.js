(function () {
  "use strict";
  const FX = window.GOIPFX;
  if (!FX) return;
  FX.smooth();
  FX.aos();
  FX.spotlight(document);
  FX.feel(document);

  /* Hero: the one animated background, and one entrance. */
  FX.network(document.querySelector("#hero-bg"));
  const heroEls = document.querySelectorAll(".hero-el");
  if (!FX.reduce && window.gsap) {
    window.gsap.from(heroEls, { y: 28, opacity: 0, duration: 0.9, ease: "power3.out", stagger: 0.11, delay: 0.1, clearProps: "transform,opacity" });
  }
  FX.counters(document.querySelector(".proof"));

  /* Nav fades in a background once the page scrolls. */
  const nav = document.querySelector("#nav");
  const onScroll = () => nav.classList.toggle("solid", window.scrollY > 40);
  window.addEventListener("scroll", onScroll, { passive: true });

  /* The pipeline: a pulse runs along the line and each agent lights in turn as it is reached. */
  const steps = Array.from(document.querySelectorAll("[data-step]"));
  const pulse = document.querySelector("#flow-pulse");
  if (!FX.reduce && window.gsap && window.ScrollTrigger && steps.length) {
    const tl = window.gsap.timeline({ scrollTrigger: { trigger: "#flow", start: "top 72%", end: "bottom 45%", scrub: 0.6 } });
    if (pulse) tl.to(pulse, { strokeDashoffset: 0, ease: "none", duration: steps.length }, 0);
    steps.forEach((step, i) => {
      tl.call(() => step.classList.add("lit"), null, i + 0.1);
      tl.call(() => step.classList.toggle("lit", true), null, i + 0.1);
    });
    tl.eventCallback("onReverseComplete", () => steps.forEach((s) => s.classList.remove("lit")));
    window.ScrollTrigger.create({ trigger: "#flow", start: "top 80%", onLeaveBack: () => steps.forEach((s) => s.classList.remove("lit")) });
  } else {
    steps.forEach((s) => s.classList.add("lit"));
  }

  /* Free the WebGL context while the hero is off screen. */
  const hero = document.querySelector("#top");
  if ("IntersectionObserver" in window && hero) {
    new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && !FX.vanta) FX.network(document.querySelector("#hero-bg"));
        if (!entry.isIntersecting && FX.vanta) FX.stopNetwork();
      });
    }, { threshold: 0.05 }).observe(hero);
  }
  window.addEventListener("load", () => FX.refresh());
})();
