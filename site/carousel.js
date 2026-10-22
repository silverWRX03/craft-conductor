"use strict";
// Progressive enhancement: without JavaScript all six features remain readable in order.
(function () {
  const carousel = document.getElementById("feature-carousel");
  if (!carousel) return;
  const slides = [...carousel.querySelectorAll(".feature")];
  const dots = [...carousel.querySelectorAll("[data-carousel-dot]")];
  const status = document.getElementById("carousel-status");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let current = 0;

  function show(index, announce = true) {
    const previous = current;
    const direction = index > current ? 1 : -1;
    const before = slides.map((slide) => {
      const style = getComputedStyle(slide);
      return { transform: style.transform, opacity: style.opacity, visibility: style.visibility };
    });
    slides.forEach((slide) => slide.getAnimations().forEach((animation) => animation.cancel()));
    current = (index + slides.length) % slides.length;
    slides.forEach((slide, i) => {
      const active = i === current;
      slide.classList.toggle("active", active);
      slide.classList.toggle("previous", i === (current + slides.length - 1) % slides.length);
      slide.classList.toggle("next", i === (current + 1) % slides.length);
      slide.setAttribute("aria-hidden", String(!active));
      slide.inert = !active;
      if (active) dots[i].setAttribute("aria-current", "true");
      else dots[i].removeAttribute("aria-current");
    });
    if (announce && previous !== current && !reducedMotion.matches) {
      slides.forEach((slide, i) => {
        const after = getComputedStyle(slide);
        const visible = after.visibility === "visible";
        // Animate only the center and its neighbors. Hidden slides never travel across the view.
        if (!visible && i !== previous) return;
        const from = before[i].visibility === "visible" ? before[i] : {
          transform: i === current ? `translateX(${direction * 104}%) scale(.94)` : after.transform,
          opacity: "0",
        };
        slide.animate([
          { transform: from.transform, opacity: from.opacity, visibility: "visible" },
          { transform: visible ? after.transform : `translateX(${-direction * 104}%) scale(.94)`,
            opacity: visible ? after.opacity : "0", visibility: "visible" },
        ], { duration: 420, easing: "cubic-bezier(.22,.68,0,1)" });
      });
    }
    if (announce) status.textContent = `${current + 1} of ${slides.length}: ${slides[current].querySelector("h3").textContent}`;
  }

  slides.forEach((slide, i) => {
    slide.setAttribute("role", "group");
    slide.setAttribute("aria-roledescription", "slide");
    slide.setAttribute("aria-label", `${i + 1} of ${slides.length}`);
    slide.querySelector("img").decoding = "async";
  });
  carousel.setAttribute("aria-describedby", "carousel-help");
  carousel.querySelector("[data-carousel-prev]").addEventListener("click", () => show(current - 1));
  carousel.querySelector("[data-carousel-next]").addEventListener("click", () => show(current + 1));
  dots.forEach((dot, i) => dot.addEventListener("click", () => show(i)));
  carousel.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const destinations = { ArrowLeft: current - 1, ArrowRight: current + 1, Home: 0, End: slides.length - 1 };
    if (!(event.key in destinations)) return;
    event.preventDefault();
    show(destinations[event.key]);
  });
  show(0, false);
  carousel.classList.add("ready");
  carousel.querySelector(".carousel-controls").hidden = false;
  reducedMotion.addEventListener("change", () => {
    if (reducedMotion.matches) slides.forEach((slide) => slide.getAnimations().forEach((animation) => animation.cancel()));
  });
  // Deliberately no timer: visitors decide when to move on, including with reduced motion.
})();
