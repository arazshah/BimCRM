import datetime

import jdatetime
from django import template
from django.utils import timezone

register = template.Library()

_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


@register.filter
def fa(value):
    """Persian digits."""
    if value is None:
        return ""
    return str(value).translate(_DIGITS)


@register.filter
def toman(value):
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return value
    return f"{n:,}".replace(",", "٬").translate(_DIGITS)


@register.filter
def rial_toman(value):
    """Rials shown as grouped Persian-digit tomans (for customers, who think in tomans)."""
    try:
        n = int(value or 0) // 10
    except (TypeError, ValueError):
        return value
    return f"{n:,}".replace(",", "٬").translate(_DIGITS)


@register.filter
def jdate(value, fmt="short"):
    if not value:
        return ""
    if isinstance(value, datetime.datetime):
        value = timezone.localtime(value) if timezone.is_aware(value) else value
        jd = jdatetime.datetime.fromgregorian(datetime=value)
    else:
        jd = jdatetime.date.fromgregorian(date=value)
    if fmt == "long":
        text = f"{jd.day} {MONTHS[jd.month - 1]} {jd.year}"
    elif fmt == "time" and isinstance(jd, jdatetime.datetime):
        text = f"{jd.year}/{jd.month:02d}/{jd.day:02d} {jd.hour:02d}:{jd.minute:02d}"
    else:
        text = f"{jd.year}/{jd.month:02d}/{jd.day:02d}"
    return text.translate(_DIGITS)


@register.filter
def days_until(value):
    if not value:
        return ""
    return (value - timezone.localdate()).days


@register.filter
def filesize_fa(value):
    value = int(value or 0)
    if value >= 1024**3:
        text = f"{value / 1024**3:.1f} گیگ"
    elif value >= 1024**2:
        text = f"{value / 1024**2:.1f} مگ"
    else:
        text = f"{value / 1024:.0f} کیلوبایت"
    return text.translate(_DIGITS)


@register.filter
def percent_of(value, total):
    try:
        return min(100, round(100 * float(value) / float(total)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.filter
def get_item(mapping, key):
    return (mapping or {}).get(key)


@register.filter
def json_attr(value):
    """JSON for an HTML attribute (escaped; the browser decodes it back for dataset)."""
    import json

    from django.utils.html import escape

    return escape(json.dumps(value or [], ensure_ascii=False))


@register.filter
def perm_on(membership, code):
    return membership.can(code)
