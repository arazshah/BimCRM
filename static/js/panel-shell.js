/* Panel shell: command palette (Ctrl+K), the "new" menu, bottom-bar menu button and dismissible banners.
   Everything degrades to plain links when scripts are off. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var digits = { "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9" };
  function norm(s) {
    return (s || "").toLowerCase().replace(/[۰-۹]/g, function (d) { return digits[d]; }).replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/‌/g, " ");
  }

  /* ── "new" menu ── */
  var menu = $("#new-menu"), scrim = $(".new-scrim");
  function setMenu(open) {
    if (!menu) return;
    menu.hidden = !open;
    if (scrim) scrim.hidden = !open;
    $$("[data-new-toggle]").forEach(function (b) { b.setAttribute("aria-expanded", open ? "true" : "false"); });
    if (open) { var first = $("a", menu); if (first) first.focus(); }
  }
  $$("[data-new-toggle]").forEach(function (b) {
    b.addEventListener("click", function (e) { e.preventDefault(); setMenu(menu.hidden); });
  });
  if (scrim) scrim.addEventListener("click", function () { setMenu(false); });
  document.addEventListener("click", function (e) {
    if (menu && !menu.hidden && !menu.contains(e.target) && !e.target.closest("[data-new-toggle]")) setMenu(false);
  });

  /* ── bottom bar: open the full menu ── */
  $$("[data-nav-open]").forEach(function (b) {
    b.addEventListener("click", function () { document.body.classList.add("nav-open"); });
  });

  /* ── command palette ── */
  var dlg = $("#palette"), input = $("#pal-input"), list = $("#pal-list"), empty = $("#pal-empty");
  var dataEl = $("#pal-data"), pages = [], found = [], active = 0, timer = null, seq = 0;
  try { pages = dataEl ? JSON.parse(dataEl.textContent) : []; } catch (e) { pages = []; }

  function row(it) {
    var li = document.createElement("li");
    li.setAttribute("role", "option");
    var a = document.createElement("a");
    a.href = it.url;
    var t = document.createElement("span");
    t.className = "pal-t";
    t.textContent = it.label;
    var h = document.createElement("small");
    h.textContent = it.hint || "";
    a.appendChild(t); a.appendChild(h);
    li.appendChild(a);
    return li;
  }
  function section(title) {
    var li = document.createElement("li");
    li.className = "pal-sec";
    li.setAttribute("role", "presentation");
    li.textContent = title;
    return li;
  }
  function render() {
    var q = norm(input.value.trim());
    var match = function (it) { return !q || norm(it.label + " " + (it.hint || "")).indexOf(q) !== -1; };
    var groups = [
      ["مشتریان و بیمه‌نامه‌ها", found],
      ["رفتن به", pages.filter(function (p) { return p.kind === "page" && match(p); }).slice(0, q ? 8 : 7)],
      ["دستورها", pages.filter(function (p) { return p.kind === "command" && match(p); }).slice(0, 6)]
    ];
    list.textContent = "";
    var n = 0;
    groups.forEach(function (g) {
      if (!g[1].length) return;
      list.appendChild(section(g[0]));
      g[1].forEach(function (it) { list.appendChild(row(it)); n++; });
    });
    empty.hidden = n > 0;
    active = 0;
    mark();
  }
  function items() { return $$("li[role=option]", list); }
  function mark() {
    items().forEach(function (li, i) { li.classList.toggle("on", i === active); });
    var cur = items()[active];
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest" });
  }
  function lookup() {
    var q = input.value.trim();
    var mine = ++seq;
    if (q.length < 2) { found = []; render(); return; }
    fetch(dlg.getAttribute("data-search-url") + "?q=" + encodeURIComponent(q), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : { customers: [], policies: [] }; })
      .then(function (d) {
        if (mine !== seq) return;
        found = (d.customers || []).concat(d.policies || []);
        render();
      })
      .catch(function () { /* offline: local pages still work */ });
  }
  function openPalette() {
    if (!dlg || typeof dlg.showModal !== "function") return false;
    setMenu(false);
    if (!dlg.open) dlg.showModal();
    input.value = "";
    found = [];
    render();
    input.focus();
    return true;
  }
  if (dlg) {
    $$("[data-palette-open]").forEach(function (a) {
      a.addEventListener("click", function (e) { if (openPalette()) e.preventDefault(); });
    });
    input.addEventListener("input", function () { render(); clearTimeout(timer); timer = setTimeout(lookup, 180); });
    dlg.addEventListener("keydown", function (e) {
      var n = items().length;
      if (e.key === "Escape") { e.preventDefault(); dlg.close(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); active = (active + 1) % Math.max(n, 1); mark(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = (active - 1 + n) % Math.max(n, 1); mark(); }
      else if (e.key === "Enter") {
        var cur = items()[active];
        if (cur) { e.preventDefault(); window.location.href = $("a", cur).href; }
      }
    });
    dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
  }
  document.addEventListener("keydown", function (e) {
    var tag = (e.target && e.target.tagName) || "";
    var typing = /INPUT|TEXTAREA|SELECT/.test(tag) || (e.target && e.target.isContentEditable);
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) { if (openPalette()) e.preventDefault(); }
    else if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) { if (openPalette()) e.preventDefault(); }
    else if (e.key === "Escape") {
      if (menu && !menu.hidden) setMenu(false);
      document.body.classList.remove("nav-open");
    }
  });

  /* ── dismissible banner (remembered per browser) ── */
  var ban = $("[data-banner-key]");
  if (ban) {
    var key = "bimcrm-banner-" + ban.getAttribute("data-banner-key");
    var day = new Date().toISOString().slice(0, 10);
    try { if (localStorage.getItem(key) === day) ban.hidden = true; } catch (e) { /* storage blocked */ }
    var close = $("[data-banner-close]", ban);
    if (close) close.addEventListener("click", function () {
      ban.hidden = true;
      try { localStorage.setItem(key, day); } catch (e) { /* storage blocked */ }
    });
  }
})();
