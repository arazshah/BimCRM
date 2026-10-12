"""The five public-site templates. All share the same content blocks; only look and layout differ."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SiteTemplate:
    key: str
    name: str
    tagline: str
    best_for: str
    default_color: str
    demo_number: int


TEMPLATES = [
    SiteTemplate("etemad", "اعتماد", "کلاسیک و رسمی؛ سابقه دفتر در مرکز توجه", "دفاتر قدیمی و شناخته‌شده", "#1d3557", 1),
    SiteTemplate(
        "modern",
        "مدرن",
        "روشن و خلوت؛ فرم استعلام همان بالای صفحه",
        "نمایندگانی که بیشتر آنلاین می‌فروشند",
        "#0f766e",
        2,
    ),
    SiteTemplate(
        "khanevadeh",
        "خانواده",
        "گرم و صمیمی؛ برای بیمه‌های عمر، درمان و منزل",
        "دفاتری که مشتری خانوادگی دارند",
        "#a3214f",
        3,
    ),
    SiteTemplate(
        "khodro",
        "خودرو",
        "تیره و پرانرژی؛ استعلام ثالث و تمدید سریع",
        "دفاتری که بیشتر ثالث و بدنه می‌فروشند",
        "#ea580c",
        4,
    ),
    SiteTemplate(
        "chandsherkati",
        "چندشرکتی",
        "ساختاریافته؛ مقایسه رشته‌ها و شرکت‌ها",
        "دفاتر بزرگ، چندشعبه یا با چند شرکت",
        "#1e40af",
        5,
    ),
]

BY_KEY = {t.key: t for t in TEMPLATES}
CHOICES = [(t.key, t.name) for t in TEMPLATES]


def get(key: str) -> SiteTemplate:
    return BY_KEY.get(key, TEMPLATES[1])
