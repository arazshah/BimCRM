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
            Article(
                "customers", "مشتریان و ورود از اکسل", "پرونده بیمه‌گذار، تاریخچه تعاملات و ورود از اکسل", "p-users"
            ),
            Article("tasks", "کارها، پیگیری‌ها و تقویم", "کار با موعد و مسئول، تقویم گوشی و اعلان‌ها", "p-tasks"),
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


@dataclass(frozen=True)
class Video:
    num: int
    file: str
    title: str
    summary: str
    article: str
    seconds: int

    @property
    def src(self) -> str:
        return f"video/{self.file}.mp4"

    @property
    def poster(self) -> str:
        return f"video/{self.file}.jpg"

    @property
    def anchor(self) -> str:
        return f"v{self.num:02d}"

    @property
    def iso_duration(self) -> str:
        return f"PT{self.seconds}S"


PROMO = Video(0, "promo", "CRM بیمه در ۴۵ ثانیه", "سایت فروش و پنل کامل دفتر نمایندگی بیمه", "", 45)

VIDEOS = [
    Video(1, "help-01-start", "ساخت سایت دفتر در ۵ دقیقه", "از انتخاب آدرس تا سایت و پنل آماده", "start", 47),
    Video(2, "help-02-sms", "اتصال پنل پیامک sms.ir", "ساخت حساب، کلید API و یادآورها", "sms", 43),
    Video(
        3, "help-03-renewals", "هیچ تمدیدی از دست نرود", "داشبورد، فیلتر سررسید، تمدید یک‌کلیکی و پیامک", "policies", 41
    ),
    Video(4, "help-04-excel", "ورود مشتریان از اکسل", "چهار ستون، ذخیره به CSV و ورود به پنل", "customers", 34),
    Video(5, "help-05-policies", "ثبت بیمه‌نامه و فایل آن", "ثبت کامل بیمه‌نامه در پرونده مشتری", "policies", 35),
    Video(6, "help-06-quotes", "استعلام آنلاین از سایت", "از فرم مشتری تا پیگیری در پنل", "quotes", 40),
    Video(7, "help-07-domain", "دامنه اختصاصی", "خرید و راه‌اندازی توسط ما، یا اتصال با NS", "domain", 36),
    Video(8, "help-08-installments", "اقساط و چک‌ها", "تقسیط، وصول و خلاصه مالی ماه", "finance", 35),
    Video(9, "help-09-claims", "پیگیری پرونده خسارت", "مرحله‌به‌مرحله با پیامک خودکار به مشتری", "claims", 34),
    Video(10, "help-10-site", "محتوا و قالب سایت", "متن‌ها، انتشار و پنج قالب آماده", "site-content", 35),
]


def videos_for(slug: str):
    extra = {"templates": "site-content"}
    return [v for v in VIDEOS if v.article == extra.get(slug, slug)]
