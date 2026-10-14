import secrets

from django.conf import settings
from django.db import models

from apps.core.models import InsuranceCompany, LineOfBusiness, TenantOwned


class Branch(TenantOwned):
    """A branch office (شعبه). Add-on: branches."""

    name = models.CharField("نام شعبه", max_length=80)
    city = models.CharField("شهر", max_length=60, blank=True)
    address = models.CharField("نشانی", max_length=255, blank=True)
    phone = models.CharField("تلفن", max_length=20, blank=True)
    show_on_site = models.BooleanField("نمایش در سایت", default=True)
    is_active = models.BooleanField("فعال", default=True)
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        verbose_name = "شعبه"
        verbose_name_plural = "شعبه‌ها"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


def _branch_field(related_name):
    return models.ForeignKey(
        Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name=related_name, verbose_name="شعبه"
    )


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
    referred_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="referrals",
        verbose_name="معرف (از مشتریان)",
    )
    referral_code = models.CharField("کد معرف", max_length=10, blank=True, db_index=True, editable=False)
    points_balance = models.IntegerField("امتیاز باشگاه", default=0, editable=False)
    points_lifetime = models.PositiveIntegerField("امتیاز کل", default=0, editable=False)
    tier = models.CharField("سطح", max_length=10, default="bronze", editable=False)
    branch = _branch_field("customers")
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
    branch = _branch_field("policies")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="ثبت‌کننده",
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
        if self.customer_id and (self.marketer_id is None or self.branch_id is None):
            marketer_id, branch_id = Customer.all_objects.filter(pk=self.customer_id).values_list(
                "marketer_id", "branch_id"
            ).first() or (None, None)
            self.marketer_id = self.marketer_id or marketer_id
            self.branch_id = self.branch_id or branch_id
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
    referrer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="معرفی‌شده توسط مشتری"
    )
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="quotes")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="مسئول"
    )
    staff_note = models.TextField("یادداشت داخلی", blank=True)
    first_contact_at = models.DateTimeField("اولین پیگیری", null=True, blank=True, editable=False)
    marketer = models.ForeignKey(
        "network.Marketer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quotes",
        verbose_name="بازاریاب معرف",
    )
    branch = _branch_field("quotes")
    created_at = models.DateTimeField("ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "درخواست استعلام"
        verbose_name_plural = "درخواست‌های استعلام"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.line} — {self.full_name}"


class CustomerDocument(TenantOwned):
    """A customer's paper: ID card, car card, previous policy, endorsement… optionally tied to a policy or a quote."""

    class Kind(models.TextChoices):
        NATIONAL_CARD = "national_card", "کارت ملی"
        BIRTH_CERT = "birth_cert", "شناسنامه"
        CAR_CARD = "car_card", "کارت خودرو"
        GREEN_SHEET = "green_sheet", "برگ سبز خودرو"
        PREV_POLICY = "prev_policy", "بیمه‌نامه قبلی"
        NO_CLAIM = "no_claim", "گواهی تخفیف عدم خسارت"
        CAR_PHOTOS = "car_photos", "عکس خودرو"
        PROPERTY = "property", "سند یا اجاره‌نامه ملک"
        MEDICAL = "medical", "مدارک پزشکی"
        PASSPORT = "passport", "گذرنامه"
        ENDORSEMENT = "endorsement", "الحاقیه"
        POLICY_COPY = "policy_copy", "فایل بیمه‌نامه"
        OTHER = "other", "سایر"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="documents", verbose_name="مشتری")
    policy = models.ForeignKey(
        Policy, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents", verbose_name="بیمه‌نامه"
    )
    kind = models.CharField("نوع مدرک", max_length=20, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField("توضیح", max_length=120, blank=True)
    file = models.FileField("فایل", upload_to="documents/%Y/%m/")
    size = models.PositiveBigIntegerField(default=0, editable=False)
    by_customer = models.BooleanField("فرستاده مشتری", default=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مدرک مشتری"
        verbose_name_plural = "مدارک مشتریان"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or self.get_kind_display()

    def save(self, *args, **kwargs):
        try:
            self.size = self.file.size
        except (OSError, ValueError, AttributeError):
            pass
        super().save(*args, **kwargs)
