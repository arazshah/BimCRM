import secrets

from django.conf import settings
from django.db import models

from apps.core.models import InsuranceCompany, LineOfBusiness, TenantOwned


class Customer(TenantOwned):
    class Source(models.TextChoices):
        WEBSITE = "website", "سایت"
        WALK_IN = "walk_in", "مراجعه حضوری"
        PHONE = "phone", "تلفن"
        REFERRAL = "referral", "معرفی"
        IMPORT = "import", "ورود از اکسل"
        OTHER = "other", "سایر"

    full_name = models.CharField("نام و نام خانوادگی", max_length=120)
    mobile = models.CharField("موبایل", max_length=11, db_index=True)
    national_code = models.CharField("کد ملی", max_length=10, blank=True)
    birth_date = models.DateField("تاریخ تولد", null=True, blank=True)
    city = models.CharField("شهر", max_length=60, blank=True)
    source = models.CharField("منبع آشنایی", max_length=20, choices=Source.choices, default=Source.OTHER)
    notes = models.TextField("یادداشت", blank=True)
    marketer = models.ForeignKey(
        "network.Marketer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customers",
        verbose_name="بازاریاب معرف",
    )
    sms_opt_out = models.BooleanField("پیامک تبلیغاتی نمی‌خواهد", default=False)
    created_at = models.DateTimeField("ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "مشتری"
        verbose_name_plural = "مشتریان"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "mobile"], name="unique_customer_mobile")]

    def __str__(self):
        return f"{self.full_name} ({self.mobile})"


class Policy(TenantOwned):
    class Status(models.TextChoices):
        ACTIVE = "active", "فعال"
        CANCELLED = "cancelled", "ابطال‌شده"

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="policies", verbose_name="بیمه‌گذار")
    line = models.ForeignKey(LineOfBusiness, on_delete=models.PROTECT, verbose_name="رشته")
    company = models.ForeignKey(InsuranceCompany, on_delete=models.PROTECT, verbose_name="شرکت بیمه")
    number = models.CharField("شماره بیمه‌نامه", max_length=60)
    start_date = models.DateField("شروع")
    end_date = models.DateField("پایان", db_index=True)
    premium = models.PositiveBigIntegerField("حق بیمه (تومان)", default=0)
    subject = models.CharField("موضوع بیمه", max_length=160, blank=True, help_text="مثلاً پلاک خودرو یا نشانی ملک")
    file = models.FileField("فایل بیمه‌نامه", upload_to="policies/%Y/%m/", blank=True)
    file_size = models.PositiveBigIntegerField(default=0, editable=False)
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    renewed_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="renewals", verbose_name="تمدید از"
    )
    commission_rate = models.DecimalField(
        "نرخ کارمزد (درصد)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="خالی = از جدول نرخ کارمزد خوانده می‌شود",
    )
    commission_received = models.PositiveBigIntegerField("کارمزد دریافت‌شده (تومان)", default=0)
    marketer = models.ForeignKey(
        "network.Marketer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="policies",
        verbose_name="بازاریاب",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "بیمه‌نامه"
        verbose_name_plural = "بیمه‌نامه‌ها"
        ordering = ["end_date"]

    def __str__(self):
        return f"{self.line} {self.number}"

    @property
    def commission_expected(self) -> int:
        if self.commission_rate is None:
            return 0
        return int(self.premium * self.commission_rate / 100)

    def save(self, *args, **kwargs):
        self.ensure_tenant()
        if self.commission_rate is None and self.company_id and self.line_id:
            from apps.finance.models import CommissionRule

            self.commission_rate = CommissionRule.rate_for(self.tenant_id, self.company_id, self.line_id)
        if self.marketer_id is None and self.customer_id:
            self.marketer_id = (
                Customer.all_objects.filter(pk=self.customer_id).values_list("marketer_id", flat=True).first()
            )
        if self.file and hasattr(self.file, "size"):
            try:
                self.file_size = self.file.size
            except (OSError, ValueError):
                pass
        super().save(*args, **kwargs)


def new_tracking_code() -> str:
    return f"{secrets.randbelow(10**8):08d}"


class QuoteRequest(TenantOwned):
    class Status(models.TextChoices):
        NEW = "new", "جدید"
        CONTACTED = "contacted", "تماس گرفته شد"
        WAITING_DOCS = "waiting_docs", "در انتظار مدارک"
        ISSUED = "issued", "صادر شد"
        LOST = "lost", "منصرف شد"

    line = models.ForeignKey(LineOfBusiness, on_delete=models.PROTECT, verbose_name="رشته")
    full_name = models.CharField("نام", max_length=120)
    mobile = models.CharField("موبایل", max_length=11)
    details = models.JSONField("جزئیات فرم", default=dict, blank=True)
    message = models.TextField("توضیحات مشتری", blank=True)
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.NEW)
    tracking_code = models.CharField("کد پیگیری", max_length=8, default=new_tracking_code, db_index=True)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="quotes")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="مسئول"
    )
    staff_note = models.TextField("یادداشت داخلی", blank=True)
    marketer = models.ForeignKey(
        "network.Marketer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quotes",
        verbose_name="بازاریاب معرف",
    )
    created_at = models.DateTimeField("ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "درخواست استعلام"
        verbose_name_plural = "درخواست‌های استعلام"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.line} — {self.full_name}"
