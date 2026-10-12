"""Sample starting prices (Toman). Change them any time in admin.bimcrm.ir; nothing is fixed in code."""

from django.db import migrations

FEATURES = """داشبورد و یادآور تمدید
مشتریان و بیمه‌نامه‌ها
صندوق درخواست‌های سایت
سایت با ۵ قالب و اتصال یک دامنه
پنل مشتری با ورود موبایلی
پشتیبانی با تیکت"""

TIERS = [("پایه — ۲ گیگ", 2048, 0, 0), ("متوسط — ۱۰ گیگ", 10240, 150_000, 1_500_000),
         ("بزرگ — ۵۰ گیگ", 51200, 450_000, 4_500_000), ("سازمانی — ۲۰۰ گیگ", 204800, 1_200_000, 12_000_000)]

ADDONS = [
    ("extra_user", "کاربر اضافه", "برای هر همکار با نقش و دسترسی جدا", 120_000, 1_200_000, True),
    ("finance", "مالی و حسابداری", "اقساط، چک، کارمزد، دفتر درآمد و هزینه", 290_000, 2_900_000, False),
    ("claims", "خسارت", "اعلام و پیگیری خسارت از پنل مشتری", 190_000, 1_900_000, False),
    ("marketers", "بازاریابان و زیرشبکه", "کد معرف، کمیسیون چندسطحی و پنل بازاریاب", 390_000, 3_900_000, False),
    ("branches", "چندشعبه‌ای", "چند دفتر زیر یک حساب با گزارش تجمیعی", 490_000, 4_900_000, False),
    ("advanced_reports", "گزارش‌های پیشرفته", "تولید به تفکیک، نرخ تمدید، هدف فروش", 190_000, 1_900_000, False),
    ("sms_campaigns", "کمپین پیامکی", "پیامک گروهی و مناسبتی با پنل پیامک خودتان", 150_000, 1_500_000, False),
    ("premium_template", "قالب ویژه", "قالب‌های پولی با طراحی اختصاصی‌تر", 100_000, 1_000_000, False),
    ("extra_domain", "دامنه اضافه", "اتصال دامنه دوم و بیشتر", 80_000, 800_000, True),
]


def seed(apps, schema_editor):
    Package = apps.get_model("billing", "Package")
    StorageTier = apps.get_model("billing", "StorageTier")
    Addon = apps.get_model("billing", "Addon")
    if not Package.objects.exists():
        Package.objects.create(name="پکیج پایه", monthly_price=490_000, yearly_price=4_900_000, included_users=1,
                               included_domains=1, is_default=True, features=FEATURES,
                               description="همه چیزی که یک نماینده برای شروع لازم دارد")
    for i, (name, mb, m, y) in enumerate(TIERS):
        StorageTier.objects.get_or_create(storage_mb=mb, defaults={"name": name, "monthly_price": m,
                                                                   "yearly_price": y, "order": i})
    for i, (code, name, desc, m, y, per_unit) in enumerate(ADDONS):
        Addon.objects.get_or_create(code=code, defaults={"name": name, "description": desc, "monthly_price": m,
                                                         "yearly_price": y, "per_unit": per_unit, "order": i})


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
