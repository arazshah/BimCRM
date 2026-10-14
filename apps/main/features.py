"""The landing page's feature explorer: every feature in one plain sentence, grouped, with the package it belongs to.

`addon` is the add-on code that unlocks the feature (None = in every package). Package names and contents come from
the database, so renaming or reshaping packages in admin updates the badges automatically.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Feature:
    title: str
    text: str
    icon: str
    help: str
    addon: str | None = None


CATEGORIES = [
    (
        "site",
        "سایت و فروش آنلاین",
        "p-globe",
        [
            Feature(
                "سایت آماده با ۵ قالب",
                "سایت حرفه‌ای دفترتان در چند دقیقه؛ قالب را هر وقت خواستید عوض کنید، متن‌ها سر جایشان می‌مانند.",
                "p-palette",
                "templates",
            ),
            Feature(
                "فرم استعلام آنلاین",
                "مشتری نوع بیمه را انتخاب می‌کند و فقط سؤال‌های همان رشته را جواب می‌دهد؛ درخواست مستقیم به پنل شما می‌آید.",
                "p-inbox",
                "quotes",
            ),
            Feature(
                "کد پیگیری برای مشتری",
                "مشتری با کد و موبایلش می‌بیند درخواستش به کجا رسیده؛ تماس‌های «چی شد؟» کم می‌شود.",
                "p-search",
                "quotes",
            ),
            Feature(
                "دامنه اختصاصی و https",
                "سایت روی آدرس خودتان مثل alborzbime.ir با قفل امنیتی؛ ثبت و راه‌اندازی را هم ما انجام می‌دهیم.",
                "p-link",
                "domain",
            ),
            Feature(
                "پنل مشتری روی سایت",
                "مشتری با موبایل وارد می‌شود و بیمه‌نامه، قسط، خسارت و امتیازش را خودش می‌بیند.",
                "p-team",
                "portal",
            ),
            Feature(
                "اینماد، درگاه و پنل پیامک خودتان",
                "نماد اعتماد، درگاه پرداخت و پنل پیامک به نام خود دفتر وصل می‌شود.",
                "p-plug",
                "integrations",
            ),
        ],
    ),
    (
        "customers",
        "مشتری و بیمه‌نامه",
        "p-users",
        [
            Feature(
                "پرونده کامل مشتری",
                "همه بیمه‌نامه‌ها، تماس‌ها، پیامک‌ها و مدارک یک نفر در یک صفحه.",
                "p-users",
                "customers",
            ),
            Feature(
                "تاریخچه تماس‌ها",
                "هر تماس و یادداشت با تاریخ و نام همکار ثبت می‌شود؛ همه می‌دانند آخرین بار چه گفته شده.",
                "p-phone",
                "customers",
            ),
            Feature(
                "مدارک با چک‌لیست",
                "کارت ملی، کارت خودرو و الحاقیه؛ سیستم می‌گوید کدام مدرک هنوز نرسیده. مشتری هم خودش بارگذاری می‌کند.",
                "p-note",
                "customers",
            ),
            Feature(
                "بیمه‌نامه و فایلش", "شماره، شرکت، تاریخ‌ها و فایل PDF؛ جستجو با نام، شماره یا پلاک.", "p-doc", "policies"
            ),
            Feature(
                "تمدید با یک کلیک",
                "فرم بیمه‌نامه سال بعد با اطلاعات امسال از قبل پر می‌شود؛ فقط شماره و مبلغ جدید را بنویسید.",
                "p-swap",
                "policies",
            ),
            Feature(
                "ورود مشتری‌ها از اکسل",
                "مشتری‌های قبلی را با یک فایل وارد کنید؛ تکراری‌ها و شماره‌های اشتباه خودکار کنار می‌روند.",
                "p-up",
                "customers",
            ),
        ],
    ),
    (
        "sms",
        "یادآور و پیامک",
        "p-bell",
        [
            Feature(
                "یادآور تمدید خودکار",
                "۳۰، ۱۵ و ۳ روز مانده (یا هر روزی که بخواهید) خودش به مشتری پیامک می‌دهد.",
                "p-bell",
                "sms",
            ),
            Feature(
                "یادآور قسط و تبریک تولد",
                "سررسید قسط و روز تولد مشتری را خودکار پیامک می‌کند؛ با نام دفتر شما.",
                "p-clock",
                "sms",
            ),
            Feature(
                "پیامک و واتس‌اپ از پرونده",
                "از داخل پرونده با یک کلیک پیام بدهید؛ در تاریخچه مشتری ثبت می‌شود.",
                "p-chat",
                "customers",
            ),
            Feature(
                "کمپین پیامکی",
                "پیامک گروهی به یک گروه از مشتریان؛ مثلاً تخفیف بدنه برای دارندگان ثالث.",
                "p-megaphone",
                "campaigns",
                "sms_campaigns",
            ),
        ],
    ),
    (
        "team",
        "کارها و تیم",
        "p-tasks",
        [
            Feature(
                "کارهای امروز من",
                "هر همکار صبح می‌بیند امروز با چه کسی باید تماس بگیرد و چه کاری عقب افتاده.",
                "p-tasks",
                "tasks",
            ),
            Feature(
                "کار خودکار برای پیگیری",
                "برای هر درخواست سایت و هر تمدید نزدیک، کار پیگیری خودش ساخته می‌شود.",
                "p-check",
                "tasks",
            ),
            Feature(
                "تقویم روی گوشی",
                "کارها، پایان بیمه‌نامه‌ها، اقساط و تولدها در تقویم شمسی؛ همگام با گوگل و آیفون.",
                "p-calendar",
                "tasks",
            ),
            Feature(
                "اعلان و یادداشت برای همکار",
                "یادداشت بگذارید و همکار را خبر کنید؛ زنگوله پنل و پیامک صبحگاهی نشانش می‌دهد.",
                "p-bell",
                "tasks",
            ),
            Feature(
                "همکار با دسترسی جدا",
                "هر همکار با موبایل خودش وارد می‌شود و فقط بخش‌هایی را می‌بیند که اجازه دارد.",
                "p-team",
                "team",
            ),
            Feature(
                "چند شعبه",
                "چند دفتر زیر یک حساب؛ هر شعبه فقط پرونده‌های خودش را می‌بیند و گزارش کل هم دارید.",
                "p-building",
                "branches",
                "branches",
            ),
        ],
    ),
    (
        "growth",
        "فروش بیشتر و وفاداری",
        "p-star",
        [
            Feature(
                "بخش‌های هوشمند مشتری",
                "گروه‌های آماده مثل «ثالث دارند، بدنه ندارند» یا «تمدیدنکرده‌ها»؛ با یک کلیک برای همه کار بسازید.",
                "p-search",
                "segments",
            ),
            Feature("پیشنهاد فروش متقابل", "در پرونده هر مشتری می‌بینید چه بیمه‌ای را هنوز ندارد.", "p-up", "segments"),
            Feature(
                "باشگاه مشتریان",
                "امتیاز برای خرید و تمدید، سطح نقره‌ای و طلایی، و تخفیف تمدید با امتیاز.",
                "p-star",
                "club",
            ),
            Feature(
                "لینک معرفی برای هر مشتری",
                "هر مشتری لینک خودش را دارد؛ دوستش که بیاید، امتیاز می‌گیرد.",
                "p-link",
                "club",
            ),
            Feature(
                "بازاریاب و پورسانت",
                "بازاریاب‌ها با لینک اختصاصی مشتری می‌آورند و پورسانتشان خودکار حساب می‌شود.",
                "p-network",
                "marketers",
                "marketers",
            ),
        ],
    ),
    (
        "money",
        "مالی، خسارت و گزارش",
        "p-wallet",
        [
            Feature(
                "اقساط و چک",
                "بیمه‌نامه را قسطی کنید؛ سررسید هر چک و قسط معوق جلوی چشمتان است.",
                "p-wallet",
                "finance",
                "finance",
            ),
            Feature(
                "کارمزد و دخل‌وخرج دفتر",
                "کارمزد هر بیمه‌نامه، اجاره، حقوق و بقیه هزینه‌ها در یک دفتر حساب.",
                "p-card",
                "finance",
                "finance",
            ),
            Feature(
                "پرونده خسارت",
                "خسارت مرحله‌به‌مرحله تا پرداخت؛ در هر مرحله پیامک به مشتری و مدارک کنار پرونده.",
                "p-shield",
                "claims",
                "claims",
            ),
            Feature(
                "گزارش فروش و تمدید",
                "فروش ۱۲ ماه، سهم هر شرکت و رشته، و درصد مشتری‌هایی که تمدید کردند.",
                "p-chart",
                "reports",
                "advanced_reports",
            ),
            Feature(
                "عملکرد همکاران",
                "هر همکار چقدر فروخته، چند پیگیری داشته و چقدر سریع به مشتری جواب داده.",
                "p-team",
                "reports",
                "advanced_reports",
            ),
        ],
    ),
]


def explorer(plans):
    """Categories with each feature's badge and the plans that include it (for the plan filter)."""
    from . import help as h

    video_for = {}
    for v in h.VIDEOS:
        video_for.setdefault(v.article, v.anchor)
    plans = sorted(plans, key=lambda p: p.monthly_price)
    included = [(p, p.included_codes()) for p in plans]
    out, total = [], 0
    for key, title, icon, items in CATEGORIES:
        rows = []
        for f in items:
            have = [p for p, codes in included if f.addon is None or f.addon in codes]
            if f.addon is None or len(have) == len(plans):
                badge, level = "همه پکیج‌ها", "all"
            elif have:
                badge = have[0].name + (" و بالاتر" if len(have) > 1 else "")
                level = "mid" if len(have) > 1 else "top"
            else:
                badge, level = "جداگانه", "top"
            rows.append(
                {
                    "f": f,
                    "badge": badge,
                    "level": level,
                    "plans": " ".join(str(p.pk) for p in have),
                    "video": video_for.get(f.help),
                }
            )
        total += len(rows)
        out.append({"key": key, "title": title, "icon": icon, "items": rows})
    return out, total
