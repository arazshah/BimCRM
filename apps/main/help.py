"""Help centre: sections and articles. Each article's body is templates/help/a/<slug>.html."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Article:
    slug: str
    title: str
    summary: str
    icon: str


SECTIONS = [
    (
        "شروع",
        [
            Article("start", "شروع کار در چند دقیقه", "ثبت‌نام با موبایل، ساخت سایت و پنل، و اولین کارها", "p-home"),
            Article("dashboard", "داشبورد و منوی پنل", "هر عدد و هر بخش داشبورد چه می‌گوید", "p-chart"),
        ],
    ),
    (
        "سایت دفتر",
        [
            Article("site-content", "محتوای سایت و انتشار", "عنوان، معرفی، رشته‌ها، شرکت‌ها، نظرات و سؤالات", "p-globe"),
            Article("templates", "قالب سایت", "انتخاب و تعویض قالب بدون از دست رفتن محتوا", "p-palette"),
            Article("domain", "دامنه اختصاصی", "اتصال دامنه ir خودتان، یا خرید و راه‌اندازی توسط ما", "p-link"),
        ],
    ),
    (
        "کار روزانه",
        [
            Article("quotes", "درخواست‌های سایت و کد پیگیری", "از استعلام مشتری تا صدور، قدم‌به‌قدم", "p-inbox"),
            Article("customers", "مشتریان و ورود از اکسل", "پرونده بیمه‌گذار و وارد کردن مشتریان قبلی", "p-users"),
            Article("policies", "بیمه‌نامه‌ها و تمدید", "ثبت بیمه‌نامه، فایل، فیلترها و تمدید یک‌کلیکی", "p-doc"),
            Article("sms", "پنل پیامک و یادآور تمدید", "ساخت حساب sms.ir، اتصال و تنظیم یادآورها", "p-bell"),
            Article("portal", "پنل مشتری روی سایت", "مشتری چطور بیمه‌نامه، قسط و خسارتش را می‌بیند", "p-team"),
        ],
    ),
    (
        "افزونه‌ها",
        [
            Article("finance", "مالی و حسابداری", "اقساط و چک، کارمزد، درآمد و هزینه", "p-wallet"),
            Article("claims", "خسارت", "اعلام، مدارک و پیگیری مرحله‌ای پرونده خسارت", "p-shield"),
            Article("branches", "شعبه‌ها", "چند دفتر زیر یک حساب با دسترسی جدا", "p-building"),
            Article("marketers", "بازاریاب‌ها و کمیسیون", "لینک معرف، زیرشبکه و تسویه", "p-network"),
            Article("campaigns", "کمپین پیامکی", "پیامک گروهی و مناسبتی به مشتریان", "p-megaphone"),
            Article("reports", "گزارش‌ها", "تولید ماهانه، شرکت‌ها، رشته‌ها و نرخ تمدید", "p-chart"),
        ],
    ),
    (
        "دفتر و اشتراک",
        [
            Article("team", "همکاران و دسترسی‌ها", "افزودن همکار با موبایل و تعیین نقش", "p-team"),
            Article("integrations", "درگاه، اینماد و کدهای دلخواه", "سرویس‌های خود دفتر را وصل کنید", "p-plug"),
            Article("billing", "اشتراک، افزونه‌ها و تمدید", "فضا، افزونه‌ها، سفارش تمدید و پیش‌فاکتور", "p-card"),
            Article("support", "پشتیبانی و تیکت", "سؤال و درخواست از ما", "p-help"),
            Article("faq", "سؤالات رایج و رفع اشکال", "پاسخ کوتاه به رایج‌ترین گیرها", "p-help"),
        ],
    ),
]

ORDER = [a for _, items in SECTIONS for a in items]
BY_SLUG = {a.slug: a for a in ORDER}


def neighbours(slug: str):
    i = next(k for k, a in enumerate(ORDER) if a.slug == slug)
    return (ORDER[i - 1] if i > 0 else None, ORDER[i + 1] if i + 1 < len(ORDER) else None)


def section_of(slug: str) -> str:
    return next(name for name, items in SECTIONS for a in items if a.slug == slug)
