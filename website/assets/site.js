(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Mobile navigation
  const menuButton = document.querySelector(".menu-button");
  const navLinks = document.querySelector(".nav-links");
  if (menuButton && navLinks) {
    menuButton.addEventListener("click", () => {
      const open = navLinks.classList.toggle("open");
      menuButton.setAttribute("aria-expanded", String(open));
      menuButton.textContent = open ? "CLOSE" : "MENU";
    });
    navLinks.addEventListener("click", (event) => {
      if (event.target.closest("a")) {
        navLinks.classList.remove("open");
        menuButton.setAttribute("aria-expanded", "false");
        menuButton.textContent = "MENU";
      }
    });
  }

  // Staggered page reveal
  const revealItems = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window) || reduceMotion) {
    revealItems.forEach((item) => item.classList.add("in"));
  } else {
    const revealObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            revealObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
    );
    revealItems.forEach((item) => revealObserver.observe(item));
  }

  // Screenshot theme switcher
  const shot = document.getElementById("app-shot");
  const shotTabs = document.querySelectorAll("[data-shot]");
  const shots = {
    dark: { src: "assets/images/main-window.png", alt: "The SYNAPSE desktop application in its dark theme." },
    light: { src: "assets/images/light-theme.png", alt: "The SYNAPSE desktop application in its light theme." },
  };
  shotTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const choice = shots[tab.dataset.shot];
      if (!shot || !choice) return;
      shotTabs.forEach((other) => other.setAttribute("aria-selected", String(other === tab)));
      shot.src = choice.src;
      shot.alt = choice.alt;
    });
  });

  // Copy install command
  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const source = document.getElementById(button.dataset.copy);
      if (!source) return;
      const text = source.innerText.replace(/^\$\s/gm, "").replace(/^#.*$/gm, "").trim();
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const field = document.createElement("textarea");
        field.value = text;
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.appendChild(field);
        field.select();
        document.execCommand("copy");
        field.remove();
      }
      const previous = button.textContent;
      button.textContent = "COPIED";
      window.setTimeout(() => { button.textContent = previous; }, 1600);
    });
  });

  // Documentation section highlighting
  const docLinks = Array.from(document.querySelectorAll(".doc-nav a[href^='#']"));
  if (docLinks.length && "IntersectionObserver" in window) {
    const sections = docLinks
      .map((link) => document.querySelector(link.getAttribute("href")))
      .filter(Boolean);
    const linkFor = new Map(sections.map((section) => [section, document.querySelector(`.doc-nav a[href="#${section.id}"]`)]));
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          docLinks.forEach((link) => link.classList.remove("active"));
          const link = linkFor.get(entry.target);
          if (link) link.classList.add("active");
        });
      },
      { rootMargin: "-18% 0px -68% 0px", threshold: 0 }
    );
    sections.forEach((section) => observer.observe(section));
    if (!document.querySelector(".doc-nav a.active") && docLinks[0]) docLinks[0].classList.add("active");
  }
})();
