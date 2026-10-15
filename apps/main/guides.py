"""Educational guides for insurance agents. Body of each is templates/main/guides/<slug>.html."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Guide:
    slug: str
    title: str
    summary: str
    minutes: int


GUIDES = [
    Guide(
        "renewal-checklist",
        "چطور هیچ تمدید بیمه‌نامه‌ای را از دست ندهیم؟",
        "یک روش ساده و قابل اجرا برای نماینده‌ای که چند صد بیمه‌نامه دارد: از ثبت تاریخ تا پیامک و تماس.",
        5,
    ),
    Guide(
        "agency-website",
        "سایت دفتر نمایندگی بیمه چه چیزهایی باید داشته باشد؟",
        "فهرست عملی بخش‌هایی که مشتری انتظار دارد و باعث می‌شود استعلام بگذارد.",
        5,
    ),
    Guide(
        "insurance-crm",
        "CRM بیمه چیست و نماینده به کدام امکانات آن نیاز دارد؟",
        "تفاوت CRM بیمه با دفترچه و اکسل، و معیارهایی برای انتخاب نرم‌افزار دفتر نمایندگی.",
        6,
    ),
    Guide(
        "installments-cheques",
        "مدیریت اقساط و چک مشتریان بیمه بدون دفترچه",
        "چطور سررسید قسط و چک را ثبت کنیم تا هیچ پرداختی گم نشود و بیمه‌نامه لغو نشود.",
        4,
    ),
    Guide(
        "multi-company-agent",
        "نمایندهٔ چند شرکت بیمه: یک فهرست برای همه",
        "وقتی بیمه‌نامه‌ها از چند شرکت است، چطور مشتری، تمدید و کارمزد را یک‌جا ببینیم.",
        4,
    ),
]
BY_SLUG = {g.slug: g for g in GUIDES}
