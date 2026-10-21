"""Money helpers: the finance module stores amounts in rials.

Inputs are shown grouped by three digits and a small line below spells the amount in tomans.
"""

from django import forms
from django.utils.html import format_html

_AR_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SEPARATORS = (",", "٬", "،", " ", "‌", " ", "_")

_ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"]
_TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"]
_TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
_HUNDREDS = ["", "یکصد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"]
_SCALES = ["", "هزار", "میلیون", "میلیارد", "تریلیون", "کوادریلیون"]


def parse_amount(raw) -> int | None:
    """'۱٬۲۵۰٬۰۰۰' / '1,250,000' → 1250000. Returns None for empty or non-numeric input."""
    if raw is None:
        return None
    text = str(raw).translate(_AR_DIGITS)
    for sep in _SEPARATORS:
        text = text.replace(sep, "")
    if not text:
        return None
    return int(text) if text.isdigit() else None


def _below_thousand(n: int) -> str:
    parts = []
    h, rest = divmod(n, 100)
    if h:
        parts.append(_HUNDREDS[h])
    if 10 <= rest < 20:
        parts.append(_TEENS[rest - 10])
    else:
        t, o = divmod(rest, 10)
        if t:
            parts.append(_TENS[t])
        if o:
            parts.append(_ONES[o])
    return " و ".join(parts)


def number_to_words(n: int) -> str:
    if n == 0:
        return "صفر"
    groups = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    parts = []
    for i in range(len(groups) - 1, -1, -1):
        if groups[i]:
            words = _below_thousand(groups[i])
            parts.append(f"{words} {_SCALES[i]}".strip())
    return " و ".join(parts)


def rial_in_toman_words(rial: int | None) -> str:
    """Words for the toman value of a rial amount (10 rials = 1 toman); '' when empty."""
    if not rial:
        return ""
    toman, rest = divmod(int(rial), 10)
    if toman == 0:
        return f"{number_to_words(rest)} ریال"
    text = f"{number_to_words(toman)} تومان"
    return f"{text} و {number_to_words(rest)} ریال" if rest else text


class RialInput(forms.TextInput):
    """Text box that groups digits by three while typing (static/js/money.js) and spells the tomans below."""

    def __init__(self, attrs=None):
        base = {"inputmode": "numeric", "dir": "ltr", "autocomplete": "off", "data-rial": "1", "class": "rial-input"}
        super().__init__({**base, **(attrs or {})})

    def format_value(self, value):
        n = parse_amount(value) if not isinstance(value, int) else value
        return f"{n:,}" if n is not None else (value or "")

    def value_from_datadict(self, data, files, name):
        raw = data.get(name)
        n = parse_amount(raw)
        return str(n) if n is not None else raw

    def render(self, name, value, attrs=None, renderer=None):
        html = super().render(name, value, attrs, renderer)
        n = parse_amount(value) if value not in (None, "") else None
        return format_html(
            '{}<small class="rial-words muted" aria-live="polite">{}</small>', html, rial_in_toman_words(n)
        )
