/* Jalali (شمسی) date picker for <input type="date">. The real input keeps the Gregorian value the server expects;
   a visible text field shows and accepts Jalali dates (typed with Persian or Latin digits, or picked from a popup). */
(() => {
  const div = (a, b) => ~~(a / b);
  function g2j(gy, gm, gd) {
    const g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    const gy2 = gm > 2 ? gy + 1 : gy;
    let days = 355666 + 365 * gy + div(gy2 + 3, 4) - div(gy2 + 99, 100) + div(gy2 + 399, 400) + gd + g_d_m[gm - 1];
    let jy = -1595 + 33 * div(days, 12053); days %= 12053;
    jy += 4 * div(days, 1461); days %= 1461;
    if (days > 365) { jy += div(days - 1, 365); days = (days - 1) % 365; }
    const jm = days < 186 ? 1 + div(days, 31) : 7 + div(days - 186, 30);
    const jd = 1 + (days < 186 ? days % 31 : (days - 186) % 30);
    return [jy, jm, jd];
  }
  function j2g(jy, jm, jd) {
    jy += 1595;
    let days = -355668 + 365 * jy + div(jy, 33) * 8 + div((jy % 33) + 3, 4) + jd + (jm < 7 ? (jm - 1) * 31 : (jm - 7) * 30 + 186);
    let gy = 400 * div(days, 146097); days %= 146097;
    if (days > 36524) { gy += 100 * div(--days, 36524); days %= 36524; if (days >= 365) days++; }
    gy += 4 * div(days, 1461); days %= 1461;
    if (days > 365) { gy += div(days - 1, 365); days = (days - 1) % 365; }
    let gd = days + 1;
    const sal = [0, 31, (gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0 ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let gm = 0;
    for (gm = 1; gm <= 12 && gd > sal[gm]; gm++) gd -= sal[gm];
    return [gy, gm, gd];
  }
  const jLen = (y, m) => m <= 6 ? 31 : m <= 11 ? 30 : (b => b[0] === y && b[1] === 12 && b[2] === 30)(g2j(...j2g(y, 12, 30))) ? 30 : 29;
  const FA = '۰۱۲۳۴۵۶۷۸۹', fa = s => String(s).replace(/\d/g, d => FA[d]);
  const en = s => String(s).replace(/[۰-۹]/g, d => FA.indexOf(d)).replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
  const pad = n => String(n).padStart(2, '0');
  const MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];
  const toJ = iso => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ''); return m ? g2j(+m[1], +m[2], +m[3]) : null; };
  const toIso = (y, m, d) => { const [a, b, c] = j2g(y, m, d); return `${a}-${pad(b)}-${pad(c)}`; };
  const show = j => j ? fa(`${j[0]}/${pad(j[1])}/${pad(j[2])}`) : '';

  let open = null;
  function close() { if (open) { open.remove(); open = null; } }
  document.addEventListener('click', e => { if (open && !open.contains(e.target) && !e.target.classList.contains('jd-input')) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });

  function popup(real, vis) {
    close();
    const today = g2j(...(d => [d.getFullYear(), d.getMonth() + 1, d.getDate()])(new Date()));
    let cur = toJ(real.value) || today, view = [cur[0], cur[1]];
    const box = document.createElement('div'); box.className = 'jd-pop'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', 'انتخاب تاریخ');
    function draw() {
      const [y, m] = view, first = j2g(y, m, 1), wd = (new Date(first[0], first[1] - 1, first[2]).getDay() + 1) % 7, n = jLen(y, m);
      let h = `<div class="jd-head"><button type="button" data-nav="-1" aria-label="ماه قبل">›</button><b>${MONTHS[m - 1]} ${fa(y)}</b><button type="button" data-nav="1" aria-label="ماه بعد">‹</button></div><div class="jd-grid">`;
      h += ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج'].map(d => `<span class="jd-wd">${d}</span>`).join('');
      for (let i = 0; i < wd; i++) h += '<span></span>';
      for (let d = 1; d <= n; d++) {
        const sel = cur && cur[0] === y && cur[1] === m && cur[2] === d, td = today[0] === y && today[1] === m && today[2] === d;
        h += `<button type="button" data-d="${d}" class="${sel ? 'sel' : ''}${td ? ' today' : ''}">${fa(d)}</button>`;
      }
      h += `</div><div class="jd-foot"><button type="button" data-today>امروز</button>${real.required ? '' : '<button type="button" data-clear>پاک کردن</button>'}</div>`;
      box.innerHTML = h;
    }
    box.addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return; e.preventDefault();
      if (b.dataset.nav) { let [y, m] = view; m += +b.dataset.nav; if (m > 12) { m = 1; y++; } if (m < 1) { m = 12; y--; } view = [y, m]; draw(); return; }
      if (b.dataset.today !== undefined) cur = today;
      else if (b.dataset.clear !== undefined) cur = null;
      else cur = [view[0], view[1], +b.dataset.d];
      real.value = cur ? toIso(...cur) : ''; vis.value = show(cur); real.dispatchEvent(new Event('change', { bubbles: true })); close(); vis.focus();
    });
    draw();
    vis.parentNode.insertBefore(box, vis.nextSibling);
    open = box;
  }

  function enhance(real) {
    if (real.dataset.jd) return; real.dataset.jd = '1';
    const vis = document.createElement('input');
    vis.type = 'text'; vis.className = 'jd-input'; vis.inputMode = 'numeric'; vis.autocomplete = 'off'; vis.placeholder = '۱۴۰۵/۰۱/۰۱';
    vis.value = show(toJ(real.value)); vis.dir = 'ltr';
    if (real.id) { vis.id = real.id + '-jd'; const lab = document.querySelector(`label[for="${real.id}"]`); if (lab) lab.htmlFor = vis.id; }
    real.type = 'hidden';
    real.parentNode.insertBefore(vis, real);
    vis.addEventListener('focus', () => popup(real, vis));
    vis.addEventListener('click', () => { if (!open) popup(real, vis); });
    vis.addEventListener('change', () => {
      const m = /^(\d{4})[\/\-.](\d{1,2})[\/\-.](\d{1,2})$/.exec(en(vis.value.trim()));
      if (m && +m[2] >= 1 && +m[2] <= 12 && +m[3] >= 1 && +m[3] <= jLen(+m[1], +m[2])) { real.value = toIso(+m[1], +m[2], +m[3]); vis.value = show([+m[1], +m[2], +m[3]]); vis.setCustomValidity(''); }
      else if (!vis.value.trim()) { real.value = ''; vis.setCustomValidity(''); }
      else vis.setCustomValidity('تاریخ را به شکل ۱۴۰۵/۰۸/۰۱ بنویسید');
    });
  }
  const run = () => document.querySelectorAll('input[type="date"]').forEach(enhance);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run();
  window.jdate = { g2j, j2g };
})();
