"""Everything priced here is created and edited by the super admin. Prices are in Toman."""

from datetime import timedelta

from django.db import models
from django.utils import timezone


class Period(models.TextChoices):
    MONTHLY = "monthly", "ماهانه"
    YEARLY = "yearly", "سالانه"


class PricedItem(models.Model):
    name = models.CharField("نام", max_length=80)
    description = models.CharField("توضیح", max_length=255, blank=True)
    monthly_price = models.PositiveBigIntegerField("قیمت ماهانه (تومان)", default=0)
    yearly_price = models.PositiveBigIntegerField("قیمت سالانه (تومان)", default=0)
    is_active = models.BooleanField("فعال", default=True)
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        abstract = True
        ordering = ["order", "id"]

    def __str__(self):
        return self.name

    def price_for(self, period: str) -> int:
        return self.yearly_price if period == Period.YEARLY else self.monthly_price


class Package(PricedItem):
    """A plan the agent picks: price, included storage, users, domains and the add-ons it already contains."""

    included_users = models.PositiveIntegerField("کاربر شامل", default=1)
    included_domains = models.PositiveIntegerField("دامنه شامل", default=1)
    is_default = models.BooleanField(
        "پکیج پیش‌فرض", default=False, help_text="وقتی پکیجی انتخاب نشده (مثلاً ساخت دستی محیط)"
    )
    is_recommended = models.BooleanField(
        "پیشنهاد ما", default=False, help_text="در صفحه قیمت برجسته و از پیش انتخاب‌شده"
    )
    tagline = models.CharField("یک خط معرفی", max_length=140, blank=True)
    best_for = models.CharField("مناسب برای", max_length=200, blank=True)
    storage_tier = models.ForeignKey(
        "StorageTier", null=True, blank=True, on_delete=models.PROTECT, related_name="+", verbose_name="فضای شامل"
    )
    addons = models.ManyToManyField("Addon", blank=True, related_name="packages", verbose_name="امکانات شامل")
    features = models.TextField("امکانات اصلی (هر خط یکی)", blank=True)

    class Meta(PricedItem.Meta):
        verbose_name = "پکیج"
        verbose_name_plural = "پکیج‌ها"

    def feature_lines(self):
        return [line.strip() for line in self.features.splitlines() if line.strip()]

    def included_codes(self) -> set[str]:
        return set(self.addons.filter(is_active=True).values_list("code", flat=True))

    @property
    def storage_label(self) -> str:
        return self.storage_tier.storage_label if self.storage_tier else ""

    @property
    def yearly_months_free(self) -> int:
        """How many months a yearly payment saves, rounded down."""
        if not self.monthly_price or not self.yearly_price:
            return 0
        return max(0, 12 - round(self.yearly_price / self.monthly_price))

    @classmethod
    def plans(cls):
        return cls.objects.filter(is_active=True).select_related("storage_tier").prefetch_related("addons")

    @classmethod
    def default(cls):
        return cls.objects.filter(is_active=True).order_by("-is_default", "order").first()

    @classmethod
    def recommended(cls):
        return cls.objects.filter(is_active=True).order_by("-is_recommended", "order").first()

    @classmethod
    def cheapest_with(cls, code: str):
        return cls.objects.filter(is_active=True, addons__code=code).order_by("monthly_price").first()


class StorageTier(PricedItem):
    storage_mb = models.PositiveIntegerField("فضا (مگابایت)")

    class Meta(PricedItem.Meta):
        verbose_name = "پله فضا"
        verbose_name_plural = "پله‌های فضا"

    @property
    def storage_label(self):
        return f"{self.storage_mb // 1024} گیگ" if self.storage_mb >= 1024 else f"{self.storage_mb} مگ"


class Addon(PricedItem):
    class Code(models.TextChoices):
        EXTRA_USER = "extra_user", "کاربر اضافه"
        FINANCE = "finance", "مالی و حسابداری"
        CLAIMS = "claims", "خسارت"
        MARKETERS = "marketers", "بازاریابان و زیرشبکه"
        BRANCHES = "branches", "چندشعبه‌ای"
        ADVANCED_REPORTS = "advanced_reports", "گزارش‌های پیشرفته"
        SMS_CAMPAIGNS = "sms_campaigns", "کمپین پیامکی"
        PREMIUM_TEMPLATE = "premium_template", "قالب ویژه"
        EXTRA_DOMAIN = "extra_domain", "دامنه اضافه"

    code = models.CharField("کد امکان", max_length=40, choices=Code.choices, unique=True)
    per_unit = models.BooleanField("قابل خرید چندتایی", default=False, help_text="مثل کاربر اضافه که تعداد دارد")

    class Meta(PricedItem.Meta):
        verbose_name = "افزونه"
        verbose_name_plural = "افزونه‌ها"


class Subscription(models.Model):
    class Status(models.TextChoices):
        TRIAL = "trial", "آزمایشی"
        ACTIVE = "active", "فعال"
        GRACE = "grace", "مهلت پرداخت"
        EXPIRED = "expired", "منقضی (فقط‌خواندنی)"

    tenant = models.OneToOneField("core.Tenant", on_delete=models.CASCADE, related_name="subscription")
    package = models.ForeignKey(Package, on_delete=models.PROTECT, verbose_name="پکیج")
    storage_tier = models.ForeignKey(StorageTier, on_delete=models.PROTECT, verbose_name="فضا")
    period = models.CharField("دوره", max_length=10, choices=Period.choices, default=Period.MONTHLY)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.TRIAL)
    current_period_end = models.DateTimeField("پایان دوره")
    reminded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "اشتراک"
        verbose_name_plural = "اشتراک‌ها"

    def __str__(self):
        return f"{self.tenant.slug}: {self.get_status_display()}"

    @property
    def is_writable(self) -> bool:
        return self.status != self.Status.EXPIRED

    @property
    def days_left(self) -> int:
        return max(0, (self.current_period_end - timezone.now()).days)

    def included_codes(self) -> set[str]:
        return self.package.included_codes()

    def active_addon_codes(self) -> set[str]:
        bought = set(self.items.filter(addon__is_active=True).values_list("addon__code", flat=True))
        return self.included_codes() | bought

    def extra_items(self):
        """Add-ons bought on top of the plan (anything the plan already contains is free)."""
        included = self.included_codes()
        return [i for i in self.items.select_related("addon").order_by("addon__order") if i.addon.code not in included]

    def addon_quantity(self, code: str) -> int:
        item = self.items.filter(addon__code=code).first()
        return item.quantity if item else 0

    def user_limit(self) -> int:
        return self.package.included_users + self.addon_quantity(Addon.Code.EXTRA_USER)

    def domain_limit(self) -> int:
        return self.package.included_domains + self.addon_quantity(Addon.Code.EXTRA_DOMAIN)

    def storage_limit_bytes(self) -> int:
        return self.storage_tier.storage_mb * 1024 * 1024

    def storage_extra_price(self, period: str) -> int:
        """Storage above what the plan includes is charged at the difference between the two tiers."""
        base = self.package.storage_tier
        if base is None:
            return self.storage_tier.price_for(period)
        if self.storage_tier.storage_mb <= base.storage_mb:
            return 0
        return max(0, self.storage_tier.price_for(period) - base.price_for(period))

    def renewal_amount(self, period: str | None = None) -> int:
        period = period or self.period
        total = self.package.price_for(period) + self.storage_extra_price(period)
        for item in self.extra_items():
            total += item.addon.price_for(period) * item.quantity
        return total

    def extend(self, period: str):
        start = max(self.current_period_end, timezone.now())
        self.period = period
        self.current_period_end = start + timedelta(days=365 if period == Period.YEARLY else 30)
        self.status = self.Status.ACTIVE
        self.reminded_at = None
        self.save()


class SubscriptionItem(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="items")
    addon = models.ForeignKey(Addon, on_delete=models.PROTECT, verbose_name="افزونه")
    quantity = models.PositiveIntegerField("تعداد", default=1)

    class Meta:
        unique_together = [("subscription", "addon")]
        verbose_name = "افزونه اشتراک"
        verbose_name_plural = "افزونه‌های اشتراک"


class Invoice(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار پرداخت"
        PAID = "paid", "پرداخت‌شده"
        FAILED = "failed", "ناموفق"
        CANCELLED = "cancelled", "لغوشده"

    class Method(models.TextChoices):
        ONLINE = "online", "درگاه آنلاین"
        ORDER = "order", "سفارش و هماهنگی با کارشناس"

    class ContactTime(models.TextChoices):
        ANY = "any", "هر ساعتی از روز"
        MORNING = "morning", "صبح (۹ تا ۱۲)"
        AFTERNOON = "afternoon", "بعدازظهر (۱۲ تا ۱۷)"
        EVENING = "evening", "عصر (۱۷ تا ۲۰)"

    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE, related_name="invoices")
    period = models.CharField("دوره", max_length=10, choices=Period.choices)
    amount = models.PositiveBigIntegerField("مبلغ (تومان)")
    description = models.CharField("شرح", max_length=255)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.PENDING)
    method = models.CharField("روش", max_length=10, choices=Method.choices, default=Method.ONLINE)
    authority = models.CharField(max_length=64, blank=True, db_index=True)
    ref_id = models.CharField("کد پیگیری", max_length=64, blank=True)
    created_at = models.DateTimeField("تاریخ", auto_now_add=True)
    paid_at = models.DateTimeField("پرداخت", null=True, blank=True)

    # Order-based renewal (no online gateway): who to call, when, and the itemised pre-invoice.
    lines = models.JSONField("ردیف‌ها", default=list, blank=True)
    contact_mobile = models.CharField("موبایل تماس", max_length=11, blank=True)
    contact_time = models.CharField(
        "زمان مناسب تماس", max_length=10, choices=ContactTime.choices, default=ContactTime.ANY
    )
    note = models.TextField("توضیح سفارش‌دهنده", blank=True)
    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="تیکت"
    )
    contacted_at = models.DateTimeField("تماس کارشناس", null=True, blank=True)
    grace_from = models.DateTimeField("پایان دوره پیش از مهلت سفارش", null=True, blank=True)

    class Meta:
        verbose_name = "فاکتور"
        verbose_name_plural = "فاکتورها"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} {self.tenant.slug} {self.amount:,}"

    @property
    def number(self) -> str:
        return f"BC-{self.pk:05d}" if self.pk else "BC-?"

    @property
    def is_open_order(self) -> bool:
        return self.method == self.Method.ORDER and self.status == self.Status.PENDING


def has_feature(tenant, code: str) -> bool:
    sub = getattr(tenant, "subscription", None)
    return bool(sub) and code in sub.active_addon_codes()
