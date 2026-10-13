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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "بیمه‌نامه"
        verbose_name_plural = "بیمه‌نامه‌ها"
        ordering = ["end_date"]

    def __str__(self):
        return f"{self.line} {self.number}"

    def save(self, *args, **kwargs):
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
    created_at = models.DateTimeField("ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "درخواست استعلام"
        verbose_name_plural = "درخواست‌های استعلام"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.line} — {self.full_name}"
