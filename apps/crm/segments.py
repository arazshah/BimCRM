"""Smart customer segments: ready-made groups for follow-up, cross-selling and campaigns."""

from dataclasses import dataclass
from datetime import timedelta

import jdatetime
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from .models import Customer, Policy


@dataclass(frozen=True)
class Segment:
    code: str
    title: str
    hint: str
    action: str  # suggested follow-up task title; {line} filled for cross-sell
    group: str


def _active(today):
    return Policy.objects.filter(customer=OuterRef("pk"), status=Policy.Status.ACTIVE, end_date__gte=today)


def _has(today, slug):
    return Exists(_active(today).filter(line__slug=slug))


SEGMENTS = [
    Segment("tp_no_body", "ثالث دارند، بدنه ندارند", "بهترین فرصت فروش بیمه بدنه", "پیشنهاد بیمه بدنه", "فروش متقابل"),
    Segment(
        "car_no_home",
        "خودرو دارند، آتش‌سوزی منزل ندارند",
        "بیمه منزل ارزان است و راحت فروخته می‌شود",
        "پیشنهاد بیمه آتش‌سوزی منزل",
        "فروش متقابل",
    ),
    Segment(
        "no_life",
        "بیمه عمر ندارند",
        "مشتریان فعالی که هنوز بیمه عمر نگرفته‌اند",
        "مشاوره بیمه عمر و سرمایه‌گذاری",
        "فروش متقابل",
    ),
    Segment(
        "no_health", "درمان تکمیلی ندارند", "برای خانواده‌ها و کارمندان", "پیشنهاد بیمه درمان تکمیلی", "فروش متقابل"
    ),
    Segment(
        "single", "فقط یک بیمه‌نامه دارند", "با یک پیشنهاد دوم، وفادارتر می‌شوند", "پیشنهاد بیمه‌نامه دوم", "فروش متقابل"
    ),
    Segment("expiring", "تمدید ۳۰ روز آینده", "بیمه‌نامه‌شان تا یک ماه دیگر تمام می‌شود", "تماس برای تمدید", "تمدید"),
    Segment(
        "lapsed",
        "تمدیدنکرده‌ها",
        "در یک سال گذشته بیمه‌نامه‌شان تمام شده و پیش شما تمدید نکرده‌اند",
        "تماس برای برگرداندن مشتری",
        "تمدید",
    ),
    Segment(
        "multi", "چندبیمه‌نامه‌ای‌ها", "دو بیمه‌نامه فعال یا بیشتر؛ مشتریان ارزشمند دفتر", "تشکر و پیشنهاد ویژه", "وفاداری"
    ),
    Segment("gold", "مشتریان طلایی باشگاه", "بالاترین سطح باشگاه مشتریان", "تماس تشکر و هدیه", "وفاداری"),
    Segment("silver", "مشتریان نقره‌ای باشگاه", "یک قدم تا طلایی", "پیشنهاد برای رسیدن به سطح طلایی", "وفاداری"),
    Segment("referrers", "معرف‌ها", "کسانی که مشتری تازه معرفی کرده‌اند", "تشکر از معرفی", "وفاداری"),
    Segment("birthday", "تولد این ماه", "برای تبریک یا هدیه کوچک", "تبریک تولد", "وفاداری"),
    Segment("new", "مشتریان جدید ۹۰ روز", "در ۳ ماه گذشته به دفتر آمده‌اند", "تماس خوش‌آمد و معرفی خدمات", "ارتباط"),
    Segment(
        "leads",
        "بدون بیمه‌نامه",
        "استعلام گرفته‌اند یا ثبت شده‌اند ولی هنوز از شما بیمه نخریده‌اند",
        "پیگیری برای صدور",
        "ارتباط",
    ),
    Segment("quiet", "بی‌ارتباط ۶ ماه", "۶ ماه است نه تعاملی ثبت شده نه بیمه‌نامه‌ای", "تماس احوال‌پرسی", "ارتباط"),
]
BY_CODE = {s.code: s for s in SEGMENTS}


def customers_in(code: str, qs=None):
    today = timezone.localdate()
    qs = qs if qs is not None else Customer.objects.all()
    if code == "tp_no_body":
        return qs.filter(_has(today, "third-party")).exclude(_has(today, "car-body"))
    if code == "car_no_home":
        car = Q(_has(today, "third-party")) | Q(_has(today, "car-body"))
        return qs.filter(car).exclude(_has(today, "home-fire"))
    if code == "no_life":
        return qs.filter(Exists(_active(today))).exclude(_has(today, "life"))
    if code == "no_health":
        return qs.filter(Exists(_active(today))).exclude(_has(today, "health"))
    if code in ("single", "multi"):
        qs = qs.annotate(
            _n=Count("policies", filter=Q(policies__status=Policy.Status.ACTIVE, policies__end_date__gte=today))
        )
        return qs.filter(_n=1) if code == "single" else qs.filter(_n__gte=2)
    if code == "expiring":
        return qs.filter(Exists(_active(today).filter(end_date__lte=today + timedelta(days=30))))
    if code == "lapsed":
        ended = Policy.objects.filter(
            customer=OuterRef("pk"),
            status=Policy.Status.ACTIVE,
            end_date__lt=today,
            end_date__gte=today - timedelta(days=365),
            renewals__isnull=True,
        )
        return qs.filter(Exists(ended))
    if code in ("gold", "silver"):
        return qs.filter(tier=code)
    if code == "referrers":
        return qs.filter(Exists(Customer.objects.filter(referred_by=OuterRef("pk"))))
    if code == "birthday":
        j = jdatetime.date.fromgregorian(date=today)
        start = jdatetime.date(j.year, j.month, 1)
        ids = [
            c.pk
            for c in qs.exclude(birth_date=None).only("pk", "birth_date")
            if jdatetime.date.fromgregorian(date=c.birth_date).month == start.month
        ]
        return qs.filter(pk__in=ids)
    if code == "new":
        return qs.filter(created_at__date__gte=today - timedelta(days=90))
    if code == "leads":
        return qs.exclude(Exists(Policy.objects.filter(customer=OuterRef("pk"))))
    if code == "quiet":
        from apps.work.models import Activity

        since = timezone.now() - timedelta(days=180)
        recent_act = Activity.objects.filter(customer=OuterRef("pk"), created_at__gte=since)
        recent_pol = Policy.objects.filter(customer=OuterRef("pk"), created_at__gte=since)
        return qs.filter(created_at__lt=since).exclude(Exists(recent_act)).exclude(Exists(recent_pol))
    return qs.none()


CROSS_SELL = [
    # (needs any of, lacks, suggestion)
    (("third-party",), "car-body", "بیمه بدنه خودرو"),
    (("third-party", "car-body"), "home-fire", "بیمه آتش‌سوزی منزل"),
    ((), "life", "بیمه عمر و سرمایه‌گذاری"),
    ((), "health", "بیمه درمان تکمیلی"),
]


def cross_sell(customer) -> list[str]:
    today = timezone.localdate()
    lines = set(
        customer.policies.filter(status=Policy.Status.ACTIVE, end_date__gte=today).values_list("line__slug", flat=True)
    )
    if not lines:
        return []
    out = []
    for needs, lacks, label in CROSS_SELL:
        if lacks not in lines and (not needs or lines & set(needs)):
            out.append(label)
    return out
