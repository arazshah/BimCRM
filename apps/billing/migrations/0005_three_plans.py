"""Three simple plans instead of "base package + storage + add-ons". Prices are suggestions; edit them in admin."""

from django.db import migrations

CORE = """سایت فروش با ۵ قالب و فرم استعلام آنلاین
مشتریان، بیمه‌نامه‌ها و تمدید یک‌کلیکی
یادآور پیامکی تمدید، قسط و تولد
کارها، پیگیری‌ها و تقویم
پرونده کامل مشتری و مدارک
باشگاه مشتریان و فروش متقابل
پنل مشتری روی سایت
پشتیبانی با تیکت"""

PLANS = [
    # name, tagline, best_for, monthly, yearly, users, domains, storage_mb, addon codes, recommended, default
    ("شروع", "سایت و پرونده مشتری برای شروع کار", "نماینده‌ای که تنها کار می‌کند یا تازه شروع کرده",
     490_000, 4_900_000, 1, 1, 2048, [], False, True),
    ("حرفه‌ای", "همه ابزار فروش، مالی و خسارت برای دفتر فعال", "بیشتر دفترها؛ دفتری با ۲ یا ۳ همکار",
     990_000, 9_900_000, 3, 1, 10240, ["finance", "claims", "sms_campaigns", "advanced_reports"], True, False),
    ("دفتر بزرگ", "چند شعبه، شبکه بازاریاب و تیم بزرگ", "دفترهای پرمشتری، چندشعبه یا با بازاریاب",
     1_890_000, 18_900_000, 10, 2, 51200,
     ["finance", "claims", "sms_campaigns", "advanced_reports", "marketers", "branches"], False, False),
]

PLAIN = {
    "extra_user": ("برای هر همکار با نقش و دسترسی جدا", "یک همکار بیشتر که با موبایل خودش وارد پنل می‌شود"),
    "finance": ("اقساط، چک، کارمزد، دفتر درآمد و هزینه", "قسط و چک مشتری، کارمزد شرکت‌ها، درآمد و هزینه دفتر"),
    "claims": ("اعلام و پیگیری خسارت از پنل مشتری", "پرونده خسارت مرحله‌به‌مرحله، با پیامک به مشتری"),
    "marketers": ("کد معرف، کمیسیون چندسطحی و پنل بازاریاب", "بازاریاب با لینک اختصاصی و پورسانت خودکار"),
    "branches": ("چند دفتر زیر یک حساب با گزارش تجمیعی", "چند شعبه زیر یک حساب، هر شعبه با دسترسی جدا"),
    "advanced_reports": ("تولید به تفکیک، نرخ تمدید، هدف فروش",
                         "فروش ۱۲ ماه، سهم شرکت‌ها و رشته‌ها، نرخ تمدید و عملکرد همکاران"),
    "sms_campaigns": ("پیامک گروهی و مناسبتی با پنل پیامک خودتان",
                      "پیامک گروهی به یک گروه از مشتریان، مثلاً تخفیف بیمه بدنه"),
    "extra_domain": ("اتصال دامنه دوم و بیشتر", "یک دامنه دیگر برای همین سایت"),
}


def forward(apps, schema_editor):
    Package = apps.get_model("billing", "Package")
    StorageTier = apps.get_model("billing", "StorageTier")
    Addon = apps.get_model("billing", "Addon")
    for code, (old, new) in PLAIN.items():
        Addon.objects.filter(code=code, description=old).update(description=new)
    # Not built yet: don't sell it.
    Addon.objects.filter(code="premium_template").update(is_active=False)

    existing = Package.objects.order_by("-is_default", "order").first()
    if Package.objects.count() > 1:
        return  # the owner has already shaped the plans by hand
    for i, (name, tagline, best_for, m, y, users, domains, mb, codes, rec, default) in enumerate(PLANS):
        tier = StorageTier.objects.filter(storage_mb=mb).first() or StorageTier.objects.order_by("storage_mb").first()
        values = dict(name=name, tagline=tagline, best_for=best_for, monthly_price=m, yearly_price=y,
                      included_users=users, included_domains=domains, storage_tier=tier, is_recommended=rec,
                      is_default=default, order=i, features=CORE, is_active=True, description=tagline)
        if i == 0 and existing is not None:
            # Keep existing subscriptions on the same row (and their price) — only describe it better.
            values.pop("monthly_price"), values.pop("yearly_price")
            for k, v in values.items():
                setattr(existing, k, v)
            existing.save()
            plan = existing
        else:
            plan = Package.objects.create(**values)
        plan.addons.set(Addon.objects.filter(code__in=codes))


class Migration(migrations.Migration):
    dependencies = [("billing", "0004_simple_plans")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
