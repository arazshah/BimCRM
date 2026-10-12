"""Sample content so each template can be previewed before an agent picks it."""

from types import SimpleNamespace

from apps.core.models import InsuranceCompany, LineOfBusiness

from . import registry

DEMO_LINES = [
    ("شخص ثالث", "third-party", "car", "استعلام نرخ با پلاک و سابقه تخفیف"),
    ("بدنه خودرو", "car-body", "car", "پوشش تصادف، سرقت و حوادث طبیعی"),
    ("آتش‌سوزی منازل", "home-fire", "home", "پوشش آتش، زلزله و سیل برای خانه و اثاثیه"),
    ("عمر و سرمایه‌گذاری", "life", "heart", "آینده خانواده و پس‌انداز بلندمدت"),
    ("درمان تکمیلی", "health", "health", "هزینه بیمارستان، دندان‌پزشکی و پاراکلینیک"),
    ("مسافرتی", "travel", "plane", "پوشش درمان و حوادث سفرهای خارجی"),
]


def demo_context(key: str) -> dict:
    tpl = registry.get(key)
    lines = list(LineOfBusiness.objects.filter(is_active=True)[:6]) or [
        SimpleNamespace(name=n, slug=s, icon=i, summary=d, form_fields=[], pk=0) for n, s, i, d in DEMO_LINES
    ]
    companies = list(InsuranceCompany.objects.filter(is_active=True)[:8])
    site = SimpleNamespace(
        template=key,
        template_info=tpl,
        color=tpl.default_color,
        is_published=True,
        logo=None,
        hero_title="نمایندگی بیمه البرز — کد ۱۲۳۴",
        hero_subtitle="ثالث، بدنه، آتش‌سوزی و عمر؛ استعلام آنلاین و صدور در کمتر از یک روز کاری.",
        about="از سال ۱۳۸۲ در خدمت خانواده‌ها و کسب‌وکارهای شهر هستیم. پیش از هر خرید، پوشش‌ها را با شما مرور "
        "می‌کنیم و بعد از صدور هم برای تمدید و خسارت کنارتان می‌مانیم.",
        years_active=21,
        customers_count=4800,
        phone="۰۲۱-۸۸۰۰۱۲۳۴",
        whatsapp="09120000000",
        email="",
        address="تهران، خیابان ولیعصر، نرسیده به میدان ونک، پلاک ۱۲",
        working_hours="شنبه تا پنج‌شنبه ۹ تا ۱۸",
        seo_description="",
    )
    tenant = SimpleNamespace(name="نمایندگی بیمه البرز کد ۱۲۳۴", agency_code="۱۲۳۴", slug="demo")
    testimonials = [
        SimpleNamespace(name="مریم ر.", text="تمدید ثالث را پیامک یادآوری کردند و ده دقیقه‌ای انجام شد."),
        SimpleNamespace(
            name="حمید ک.", text="برای خسارت بدنه از اول تا آخر پیگیری کردند، بی‌آنکه چند بار بروم و بیایم."
        ),
        SimpleNamespace(name="شرکت آرین‌تجارت", text="بیمه مسئولیت کارفرمایی را با مقایسه چند شرکت انتخاب کردیم."),
    ]
    faqs = [
        SimpleNamespace(
            question="برای ثالث چه مدارکی لازم است؟",
            answer="کارت خودرو، بیمه‌نامه قبلی و کارت ملی مالک. تصویرشان را در فرم استعلام بفرستید کافی است.",
        ),
        SimpleNamespace(
            question="پرداخت اقساطی دارید؟", answer="برای بیشتر رشته‌ها بله؛ شرایط هر رشته را در تماس اول می‌گوییم."
        ),
    ]
    return {
        "site": site,
        "tenant": tenant,
        "lines": lines,
        "companies": companies,
        "testimonials": testimonials,
        "faqs": faqs,
        "is_demo": True,
        "tpl": tpl,
        "trust_badges": [],
        "head_code": "",
        "body_code": "",
        "can_portal": True,
        "base_template": f"sites/{key}/base.html",
    }
