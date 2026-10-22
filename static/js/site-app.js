/* App-like behaviour of the public agency sites. Everything here is progressive enhancement:
   without JavaScript the quote form, tracking and links keep working as plain pages. */
(() => {
  "use strict";

  const DRAFT_KEY = "qf-draft";
  const DRAFT_TTL = 7 * 24 * 3600 * 1000;
  const ICONS = {
    car: "car", home: "home", heart: "heart", health: "health", plane: "plane", briefcase: "briefcase",
    shield: "shield", doc: "doc",
  };
  const mobile = window.matchMedia("(max-width: 760px)");

  const store = {
    get() {
      try {
        const d = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
        return d && Date.now() - d.ts < DRAFT_TTL ? d : null;
      } catch (e) { return null; }
    },
    set(d) { try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ ...d, ts: Date.now() })); } catch (e) {} },
  };

  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === "class") n.className = v;
      else if (v === true) n.setAttribute(k, "");
      else if (v !== false && v != null) n.setAttribute(k, v);
    });
    kids.forEach((c) => n.append(c));
    return n;
  };
  const svg = (name) => {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("aria-hidden", "true");
    const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
    u.setAttribute("href", "#i-" + name);
    s.append(u);
    return s;
  };

  /* ---------- quote wizard (phones) ---------- */
  const form = document.getElementById("quote-form");
  const select = document.getElementById("qf-line");
  const extra = document.getElementById("qf-extra");

  if (form && select && extra) {
    let sheet, panel, titleEl, subEl, backBtn, body, foot, progress, tiles, resumeBox, placeholder, lastFocus;
    let step = 1;
    let open = false;

    const lineName = () => (select.selectedOptions[0] ? select.selectedOptions[0].textContent.trim() : "");
    const hasExtra = () => extra.children.length > 0;

    const saveDraft = () => {
      const values = {};
      extra.querySelectorAll("[name^='f_']").forEach((i) => { if (i.value) values[i.name] = i.value; });
      store.set({ line: select.value, values });
    };

    const build = () => {
      tiles = el("div", { class: "qf-tiles", "data-qf-step": "1" });
      Array.from(select.options).forEach((opt) => {
        const tile = el("button", { type: "button", class: "qf-tile", "data-slug": opt.value },
          svg(opt.dataset.icon && ICONS[opt.dataset.icon] ? ICONS[opt.dataset.icon] : "shield"),
          el("b", {}, opt.textContent.trim()));
        tile.addEventListener("click", () => { choose(opt.value); });
        tiles.append(tile);
      });
      form.prepend(el("p", { class: "qf-q", "data-qf-step": "1" }, "چه بیمه‌ای لازم دارید؟"), tiles);
      titleEl = el("h2", {});
      subEl = el("small", {});
      backBtn = el("button", { type: "button", class: "qf-icon-btn", "aria-label": "قدم قبل" }, arrow());
      const closeBtn = el("button", { type: "button", class: "qf-icon-btn", "aria-label": "بستن" }, cross());
      progress = el("div", { class: "qf-progress", "aria-hidden": "true" }, el("span"), el("span"), el("span"));
      body = el("div", { class: "qf-body" });
      foot = el("div", { class: "qf-foot" });
      const next = el("button", { type: "button", class: "qf-submit" }, "ادامه");
      foot.append(next);
      panel = el("div", { class: "qf-panel", role: "dialog", "aria-modal": "true", "aria-label": "استعلام بیمه" },
        el("div", { class: "qf-grip", "aria-hidden": "true" }),
        el("div", { class: "qf-head" }, backBtn, el("h2", {}, titleEl, subEl), closeBtn),
        progress, body, foot);
      sheet = el("div", { class: "qf-sheet", hidden: true }, panel);
      document.body.append(sheet);
      closeBtn.addEventListener("click", close);
      backBtn.addEventListener("click", back);
      next.addEventListener("click", forward);
      sheet.addEventListener("mousedown", (e) => { if (e.target === sheet) close(); });
      sheet.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { close(); return; }
        if (e.key !== "Tab") return;
        const f = Array.from(panel.querySelectorAll("button, input, select, textarea, a[href]")).filter((n) => n.offsetParent !== null && !n.disabled);
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      });
    };

    const arrow = () => {
      const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor");
      s.setAttribute("stroke-width", "2"); s.setAttribute("stroke-linecap", "round"); s.setAttribute("aria-hidden", "true");
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", "M9 6l6 6-6 6"); s.append(p); return s;
    };
    const cross = () => {
      const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor");
      s.setAttribute("stroke-width", "2"); s.setAttribute("stroke-linecap", "round"); s.setAttribute("aria-hidden", "true");
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", "M6 6l12 12M18 6L6 18"); s.append(p); return s;
    };

    const render = () => {
      form.dataset.step = String(step);
      progress.querySelectorAll("span").forEach((s, i) => s.classList.toggle("on", i < step));
      titleEl.textContent = step === 1 ? "استعلام بیمه" : lineName();
      subEl.textContent = "قدم " + ["۱", "۲", "۳"][step - 1] + " از ۳";
      backBtn.hidden = step === 1;
      foot.hidden = step !== 2;
      if (resumeBox) resumeBox.hidden = step !== 1;
      const target = body.querySelector("[data-qf-step='" + step + "']:not([hidden]) input, [data-qf-step='" + step + "']:not([hidden]) select, [data-qf-step='" + step + "']:not([hidden]) textarea");
      if (step === 1) { const t = tiles.querySelector(".qf-tile"); if (t) t.focus(); }
      else if (target) target.focus();
    };

    const choose = (slug) => {
      select.value = slug;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      saveDraft();
      step = hasExtra() ? 2 : 3;
      render();
    };

    const forward = () => {
      if (step === 2) {
        const bad = Array.from(extra.querySelectorAll("input, select, textarea")).find((i) => !i.checkValidity());
        if (bad) { bad.reportValidity(); return; }
        saveDraft();
        step = 3;
        render();
      }
    };
    const back = () => {
      if (step === 3) step = hasExtra() ? 2 : 1;
      else if (step === 2) step = 1;
      render();
    };

    const showResume = () => {
      if (resumeBox) resumeBox.remove();
      resumeBox = null;
      const d = store.get();
      const opt = d && Array.from(select.options).find((o) => o.value === d.line);
      if (!opt) return;
      resumeBox = el("button", { type: "button", class: "qf-resume", "data-qf-step": "1" },
        el("span", {}, "استعلام نیمه‌کارهٔ " + opt.textContent.trim() + " را ادامه دهید"), el("b", {}, "ادامه"));
      resumeBox.addEventListener("click", () => {
        select.value = d.line;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        Object.entries(d.values || {}).forEach(([name, v]) => { const i = extra.querySelector("[name='" + name + "']"); if (i) i.value = v; });
        step = hasExtra() ? 2 : 3;
        render();
      });
      form.prepend(resumeBox);
    };

    const openSheet = (e) => {
      if (!mobile.matches) return;
      if (e) e.preventDefault();
      if (open) return;
      if (!sheet) build();
      lastFocus = document.activeElement;
      placeholder = document.createComment("quote-form");
      form.before(placeholder);
      body.append(form);
      form.classList.add("qf-wizard");
      showResume();
      sheet.hidden = false;
      document.documentElement.classList.add("qf-lock");
      open = true;
      step = 1;
      render();
    };

    const close = () => {
      if (!open) return;
      sheet.hidden = true;
      form.classList.remove("qf-wizard");
      delete form.dataset.step;
      if (resumeBox) { resumeBox.remove(); resumeBox = null; }
      placeholder.replaceWith(form);
      document.documentElement.classList.remove("qf-lock");
      open = false;
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    };

    document.querySelectorAll("[data-open-quote], a[href$='#quote']").forEach((a) => a.addEventListener("click", openSheet));
    extra.addEventListener("input", () => { if (open) saveDraft(); });
    mobile.addEventListener("change", () => { if (!mobile.matches) close(); });
    if (location.hash === "#quote" && mobile.matches) openSheet();
  }

  /* ---------- quote done page ---------- */
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    const src = document.querySelector(btn.dataset.copy);
    if (!src || !navigator.clipboard) return;
    btn.hidden = false;
    btn.addEventListener("click", () => {
      const ascii = src.textContent.trim().replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d));
      navigator.clipboard.writeText(ascii).then(() => { btn.textContent = "کپی شد"; });
    });
  });

  let installEvent = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    installEvent = e;
    document.querySelectorAll("[data-install]").forEach((b) => { b.hidden = false; });
  });
  document.querySelectorAll("[data-install]").forEach((b) => b.addEventListener("click", () => {
    if (installEvent) { installEvent.prompt(); installEvent = null; b.hidden = true; }
  }));

  /* ---------- installable app ---------- */
  if ("serviceWorker" in navigator && document.querySelector("link[rel='manifest']")) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
  }
})();
