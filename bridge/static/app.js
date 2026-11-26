/* Progressive enhancement only: every action still works without JS. */
(() => {
  "use strict";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- toasts (server flash via ?ok= / ?error=) ---------- */
  const toast = document.getElementById("toast");
  if (toast) {
    const msg = toast.dataset.msg;
    if (msg) {
      setTimeout(() => {
        toast.classList.add("out");
        setTimeout(() => { toast.hidden = true; }, 250);
      }, 3200);
    }
  }

  /* ---------- FAB -> composer ---------- */
  const fab = document.getElementById("fab");
  const composer = document.getElementById("newContent");
  if (fab && composer) {
    fab.hidden = false;
    fab.addEventListener("click", () => {
      composer.open = true;
      composer.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      const first = composer.querySelector("input, textarea, select");
      if (first) setTimeout(() => first.focus({ preventScroll: true }), 200);
    });
  }

  document.querySelectorAll('a[href="#newContent"]').forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      if (composer) { composer.open = true; composer.scrollIntoView({ behavior: reduce ? "auto" : "smooth" }); }
    }));

  /* ---------- skeleton overlay on navigation / form submit ---------- */
  const skel = document.getElementById("skel");
  const showSkeleton = () => {
    if (!skel) return;
    skel.hidden = false;
    document.documentElement.setAttribute("aria-busy", "true");
  };
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
    const url = a.getAttribute("href") || "";
    if (!url.startsWith("/ui") || a.closest("nav")) return;
    showSkeleton();
  });
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (form.matches("form[data-confirm]") &&
        !confirm(form.dataset.confirm)) { e.preventDefault(); return; }
    const btn = form.querySelector("button");
    if (btn) { btn.disabled = true; btn.classList.add("busy"); }
    showSkeleton();
  });

  /* ---------- pull to refresh (touch, top of page only) ---------- */
  const ptr = document.getElementById("ptr");
  if (ptr && "ontouchstart" in window) {
    let startY = 0, pulling = false;
    addEventListener("touchstart", (e) => {
      if (scrollY > 0 || e.touches.length !== 1) return;
      startY = e.touches[0].clientY; pulling = true;
    }, { passive: true });
    addEventListener("touchmove", (e) => {
      if (!pulling) return;
      const dy = e.touches[0].clientY - startY;
      if (dy <= 0) return;
      ptr.style.setProperty("--pull", Math.min(dy, 72) + "px");
      ptr.classList.add("on");
    }, { passive: true });
    addEventListener("touchend", () => {
      if (!pulling) return;
      pulling = false;
      const pulled = parseFloat(ptr.style.getPropertyValue("--pull") || "0");
      ptr.classList.remove("on");
      ptr.style.setProperty("--pull", "0px");
      if (pulled > 54) { showSkeleton(); location.reload(); }
    }, { passive: true });
  }

  /* ---------- chips: keep active chip in view ---------- */
  const activeChip = document.querySelector(".chips a.on");
  if (activeChip) activeChip.scrollIntoView({ block: "nearest", inline: "center" });
})();
