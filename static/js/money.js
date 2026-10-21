/* Rial inputs: group digits by three while typing and spell the amount in tomans underneath. */
(function () {
  var ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"];
  var TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"];
  var TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"];
  var HUNDREDS = ["", "یکصد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"];
  var SCALES = ["", "هزار", "میلیون", "میلیارد", "تریلیون", "کوادریلیون"];

  function below(n) {
    var p = [], h = Math.floor(n / 100), r = n % 100;
    if (h) p.push(HUNDREDS[h]);
    if (r >= 10 && r < 20) p.push(TEENS[r - 10]);
    else {
      if (Math.floor(r / 10)) p.push(TENS[Math.floor(r / 10)]);
      if (r % 10) p.push(ONES[r % 10]);
    }
    return p.join(" و ");
  }
  function words(digits) { // digits: string of 0-9, no leading zeros issue
    digits = digits.replace(/^0+/, "");
    if (!digits) return "صفر";
    var groups = [];
    for (var i = digits.length; i > 0; i -= 3) groups.push(parseInt(digits.slice(Math.max(0, i - 3), i), 10));
    var parts = [];
    for (var g = groups.length - 1; g >= 0; g--) if (groups[g]) parts.push((below(groups[g]) + " " + SCALES[g]).trim());
    return parts.join(" و ");
  }
  function rialWords(digits) {
    if (!digits || /^0*$/.test(digits)) return "";
    var rest = parseInt(digits.slice(-1), 10), toman = digits.slice(0, -1).replace(/^0+/, "");
    if (!toman) return words(String(rest)) + " ریال";
    var t = words(toman) + " تومان";
    return rest ? t + " و " + words(String(rest)) + " ریال" : t;
  }
  function clean(v) {
    return v.replace(/[۰-۹]/g, function (d) { return "۰۱۲۳۴۵۶۷۸۹".indexOf(d); })
            .replace(/[٠-٩]/g, function (d) { return "٠١٢٣٤٥٦٧٨٩".indexOf(d); })
            .replace(/\D/g, "");
  }
  function group(d) { return d.replace(/\B(?=(\d{3})+(?!\d))/g, ","); }

  function update(input) {
    var fromEnd = input.value.length - (input.selectionStart || 0);
    var digits = clean(input.value);
    input.value = group(digits);
    var pos = Math.max(0, input.value.length - fromEnd);
    try { input.setSelectionRange(pos, pos); } catch (e) {}
    var out = input.parentNode.querySelector(".rial-words");
    if (out) out.textContent = rialWords(digits);
  }
  document.addEventListener("input", function (e) {
    if (e.target && e.target.matches && e.target.matches("input[data-rial]")) update(e.target);
  });
  document.addEventListener("submit", function (e) {
    e.target.querySelectorAll("input[data-rial]").forEach(function (i) { i.value = clean(i.value); });
  }, true);
  window.BimMoney = { rialWords: rialWords };
})();
