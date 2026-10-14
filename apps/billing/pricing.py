"""One place that turns plans and add-ons into something an agent can compare at a glance.

Used by the landing page, the sign-up plan step and the panel's subscription page, so all three say the same thing.
"""

from .models import Addon, Package, StorageTier

STORAGE_HINT = "برای فایل بیمه‌نامه‌ها و مدارک مشتری؛ هر گیگ حدود ۲٬۰۰۰ فایل PDF یا عکس"
USERS_HINT = "هر همکاری که با موبایل خودش وارد پنل می‌شود (خودتان هم یکی حساب می‌شوید)"
DOMAINS_HINT = "آدرس اختصاصی مثل alborzbime.ir؛ آدرس رایگان bimcrm.ir همیشه هست"


def _gb(mb: int) -> str:
    return f"{mb // 1024} گیگ" if mb >= 1024 else f"{mb} مگ"


def comparison(plans=None):
    plans = list(plans if plans is not None else Package.plans())
    included = {p.pk: p.included_codes() for p in plans}
    rows = [
        {
            "label": "همکاران",
            "hint": USERS_HINT,
            "cells": [{"ok": True, "text": f"{p.included_users} نفر"} for p in plans],
        },
        {
            "label": "فضای فایل",
            "hint": STORAGE_HINT,
            "cells": [{"ok": True, "text": _gb(p.storage_tier.storage_mb) if p.storage_tier else "—"} for p in plans],
        },
        {
            "label": "دامنه اختصاصی",
            "hint": DOMAINS_HINT,
            "cells": [{"ok": True, "text": f"{p.included_domains} دامنه"} for p in plans],
        },
        {
            "label": "امکانات اصلی",
            "hint": "سایت و فرم استعلام، مشتری و بیمه‌نامه، یادآور پیامکی، کارها و تقویم، باشگاه مشتریان",
            "cells": [{"ok": True, "text": ""} for _ in plans],
        },
    ]
    for addon in Addon.objects.filter(is_active=True, per_unit=False).order_by("order"):
        rows.append(
            {
                "label": addon.name,
                "hint": addon.description,
                "cells": [
                    {"ok": True, "text": ""}
                    if addon.code in included[p.pk]
                    else {"ok": False, "text": "", "price": addon.monthly_price}
                    for p in plans
                ],
            }
        )
    return rows


def extras():
    """Things you can add to any plan later, in plain words."""
    out = []
    for addon in Addon.objects.filter(is_active=True, per_unit=True).order_by("order"):
        out.append({"title": addon.name, "text": addon.description, "price": addon.monthly_price, "unit": "هر عدد"})
    big = StorageTier.objects.filter(is_active=True).order_by("storage_mb").last()
    if big:
        out.append(
            {
                "title": "فضای بیشتر",
                "text": f"تا {_gb(big.storage_mb)}؛ فقط اگر فایل‌هایتان زیاد شد",
                "price": None,
                "unit": "",
            }
        )
    return out


FAQ = [
    (
        "فرق پکیج‌ها چیست؟",
        "امکانات اصلی (سایت، مشتری، بیمه‌نامه، یادآور تمدید، کارها و باشگاه مشتریان) در هر سه هست. "
        "پکیج‌های بالاتر امکانات دفترهای بزرگ‌تر مثل مالی، خسارت، شعبه و بازاریاب و همکار و فضای بیشتر دارند.",
    ),
    (
        "فضای فایل یعنی چه و چقدر لازم دارم؟",
        "جایی که فایل بیمه‌نامه‌ها و عکس مدارک مشتری‌ها ذخیره می‌شود. هر گیگ حدود ۲٬۰۰۰ فایل است؛ "
        "برای بیشتر دفترها همان مقدار داخل پکیج کافی است.",
    ),
    (
        "بعداً می‌توانم پکیج را عوض کنم؟",
        "بله، هر وقت خواستید از داخل پنل، بدون از دست رفتن هیچ اطلاعاتی. اگر فقط یک امکان یا یک همکار بیشتر لازم دارید، "
        "می‌توانید همان را جداگانه اضافه کنید.",
    ),
    (
        "۱۴ روز رایگان چطور است؟",
        "هر پکیجی انتخاب کنید، ۱۴ روز کامل و رایگان کار می‌کند؛ بدون کارت بانکی. بعد از آن اگر خواستید تمدید می‌کنید.",
    ),
]


def plan_cards(plans=None):
    """Each plan with what it adds on top of the previous one, so cards read "everything in X, plus …"."""
    plans = list(plans if plans is not None else Package.plans())
    cards, prev, prev_codes = [], None, set()
    for p in plans:
        codes = p.included_codes()
        adds = [a for a in p.addons.all() if a.is_active and a.code not in prev_codes]
        adds.sort(key=lambda a: a.order)
        cards.append({"plan": p, "prev": prev, "adds": adds})
        prev, prev_codes = p, codes
    return cards


def cheaper_plan(sub):
    """If another plan covers everything this office uses for less money, say which and how much it saves a month."""
    from .models import Addon

    needed = {c for c in sub.active_addon_codes()} - {Addon.Code.EXTRA_USER, Addon.Code.EXTRA_DOMAIN}
    users, domains = sub.user_limit(), sub.domain_limit()
    current = sub.renewal_amount("monthly")
    user_price = Addon.objects.filter(code=Addon.Code.EXTRA_USER).values_list("monthly_price", flat=True).first() or 0
    domain_price = (
        Addon.objects.filter(code=Addon.Code.EXTRA_DOMAIN).values_list("monthly_price", flat=True).first() or 0
    )
    best = None
    for plan in Package.plans():
        if plan.pk == sub.package_id or not needed <= plan.included_codes():
            continue
        cost = plan.monthly_price
        cost += max(0, users - plan.included_users) * user_price
        cost += max(0, domains - plan.included_domains) * domain_price
        base = plan.storage_tier
        if base and sub.storage_tier.storage_mb > base.storage_mb:
            cost += max(0, sub.storage_tier.monthly_price - base.monthly_price)
        if cost < current and (best is None or cost < best[1]):
            best = (plan, cost)
    if best is None:
        return None
    return {"plan": best[0], "saving": current - best[1]}
