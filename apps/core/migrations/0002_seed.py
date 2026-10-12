from django.db import migrations

LINES = [
    ("شخص ثالث", "third-party", "car", "استعلام نرخ با پلاک و سابقه تخفیف", [
        {"name": "car", "label": "نوع و مدل خودرو", "type": "text"},
        {"name": "year", "label": "سال ساخت", "type": "text"},
        {"name": "discount", "label": "سال‌های تخفیف عدم خسارت", "type": "text"},
        {"name": "expiry", "label": "تاریخ پایان بیمه قبلی", "type": "text"},
    ]),
    ("بدنه خودرو", "car-body", "car", "پوشش تصادف، سرقت و حوادث طبیعی", [
        {"name": "car", "label": "نوع و مدل خودرو", "type": "text"},
        {"name": "value", "label": "ارزش تقریبی خودرو (تومان)", "type": "text"},
    ]),
    ("آتش‌سوزی منازل", "home-fire", "home", "پوشش آتش، زلزله و سیل برای خانه و اثاثیه", [
        {"name": "area", "label": "متراژ", "type": "text"},
        {"name": "city", "label": "شهر", "type": "text"},
    ]),
    ("عمر و سرمایه‌گذاری", "life", "heart", "آینده خانواده و پس‌انداز بلندمدت", [
        {"name": "age", "label": "سن بیمه‌شده", "type": "text"},
    ]),
    ("درمان تکمیلی", "health", "health", "هزینه بیمارستان، دندان‌پزشکی و پاراکلینیک", [
        {"name": "people", "label": "تعداد افراد", "type": "text"},
    ]),
    ("مسافرتی", "travel", "plane", "پوشش درمان و حوادث سفرهای خارجی", [
        {"name": "destination", "label": "کشور مقصد", "type": "text"},
        {"name": "days", "label": "مدت سفر (روز)", "type": "text"},
    ]),
    ("مسئولیت", "liability", "briefcase", "مسئولیت کارفرما، حرفه‌ای و مدنی", [
        {"name": "business", "label": "نوع کسب‌وکار", "type": "text"},
    ]),
]

COMPANIES = [
    ("بیمه ایران", "iran"), ("بیمه آسیا", "asia"), ("بیمه البرز", "alborz"), ("بیمه دانا", "dana"),
    ("بیمه پارسیان", "parsian"), ("بیمه کارآفرین", "karafarin"), ("بیمه سامان", "saman"),
    ("بیمه ملت", "mellat"), ("بیمه دی", "dey"), ("بیمه رازی", "razi"), ("بیمه معلم", "moallem"),
    ("بیمه پاسارگاد", "pasargad"), ("بیمه سینا", "sina"), ("بیمه نوین", "novin"), ("بیمه کوثر", "kowsar"),
    ("بیمه ما", "mabime"), ("بیمه تعاون", "taavon"), ("بیمه سرمد", "sarmad"), ("بیمه حکمت", "hekmat"),
    ("بیمه آرمان", "arman"), ("بیمه تجارت نو", "tejaratno"), ("بیمه میهن", "mihan"),
]


def seed(apps, schema_editor):
    Line = apps.get_model("core", "LineOfBusiness")
    Company = apps.get_model("core", "InsuranceCompany")
    Reserved = apps.get_model("core", "ReservedSubdomain")
    PlatformSettings = apps.get_model("core", "PlatformSettings")

    for i, (name, slug, icon, summary, fields) in enumerate(LINES):
        Line.objects.get_or_create(slug=slug, defaults={"name": name, "icon": icon, "summary": summary,
                                                        "form_fields": fields, "order": i})
    for i, (name, latin) in enumerate(COMPANIES):
        Company.objects.get_or_create(name=name, defaults={"order": i})
        Reserved.objects.get_or_create(name=latin, defaults={"note": f"نام {name}"})
    PlatformSettings.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
