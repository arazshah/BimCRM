import datetime
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from .tenancy import get_current_tenant

SUBDOMAIN_RE = re.compile(r"^[a-z][a-z0-9-]{1,28}[a-z0-9]$")

# Always reserved, in addition to ReservedSubdomain rows the super admin adds.
BUILTIN_RESERVED = {
    "www",
    "admin",
    "app",
    "api",
    "panel",
    "ns",
    "ns1",
    "ns2",
    "ns3",
    "mail",
    "smtp",
    "imap",
    "pop",
    "ftp",
    "support",
    "help",
    "blog",
    "status",
    "static",
    "media",
    "cdn",
    "dev",
    "staging",
    "test",
    "demo",
    "demo1",
    "demo2",
    "demo3",
    "demo4",
    "demo5",
    "bimcrm",
    "billing",
    "pay",
    "login",
    "signup",
    "account",
    "accounts",
}


def validate_subdomain_format(value: str):
    if not SUBDOMAIN_RE.match(value or ""):
        raise ValidationError(
            "فقط حروف کوچک انگلیسی، عدد و خط تیره؛ ۳ تا ۳۰ کاراکتر؛ با حرف شروع و با حرف یا عدد تمام شود."
        )
    if "--" in value:
        raise ValidationError("دو خط تیره پشت سر هم مجاز نیست.")


def is_subdomain_available(value: str) -> tuple[bool, str]:
    value = (value or "").strip().lower()
    try:
        validate_subdomain_format(value)
    except ValidationError as exc:
        return False, exc.messages[0]
    if value in BUILTIN_RESERVED or ReservedSubdomain.objects.filter(name=value).exists():
        return False, "این نام رزرو شده است."
    if Tenant.objects.filter(slug=value).exists():
        return False, "این نام قبلاً گرفته شده است."
    return True, "آزاد است."


class PlatformSettings(models.Model):
    """Singleton editable from the super admin panel."""

    trial_days = models.PositiveIntegerField("روزهای آزمایشی رایگان", default=14)
    grace_days = models.PositiveIntegerField("روزهای مهلت پس از انقضا", default=7)
    data_retention_days = models.PositiveIntegerField("نگهداری داده پس از انقضا (روز)", default=90)
    yearly_discount_note = models.CharField("توضیح تخفیف سالانه", max_length=120, blank=True, default="دو ماه رایگان")
    support_phone = models.CharField("تلفن پشتیبانی", max_length=20, blank=True)
    nameservers = models.CharField(
        "نام‌سرورهای پلتفرم",
        max_length=255,
        blank=True,
        help_text="با کاما جدا کنید. خالی = مقدار تنظیمات سرور.",
    )

    # --- Platform services. Empty = fall back to the server environment (see apps/core/platform_config.py). ---
    class SmsBackend(models.TextChoices):
        SERVER = "", "از تنظیمات سرور"
        CONSOLE = "console", "فقط در لاگ سرور چاپ شود (آزمایشی)"
        SMSIR = "smsir", "ارسال واقعی با sms.ir"

    class ZarinpalMode(models.TextChoices):
        SERVER = "", "از تنظیمات سرور"
        SANDBOX = "sandbox", "آزمایشی (sandbox)"
        LIVE = "live", "واقعی"

    sms_backend = models.CharField("روش ارسال پیامک", max_length=10, choices=SmsBackend.choices, blank=True)
    smsir_api_key_enc = models.TextField(blank=True, editable=False)
    smsir_otp_template_id = models.CharField("شناسه قالب کد تأیید sms.ir", max_length=20, blank=True)
    smsir_line_number = models.CharField("شماره خط sms.ir", max_length=30, blank=True)
    zarinpal_merchant_id = models.CharField("مرچنت کد زرین‌پال", max_length=64, blank=True)
    zarinpal_mode = models.CharField("حالت زرین‌پال", max_length=10, choices=ZarinpalMode.choices, blank=True)

    # --- Partner links shown to offices ---
    smsir_signup_url = models.URLField(
        "لینک ساخت حساب sms.ir برای دفترها",
        blank=True,
        default="https://app.sms.ir/auth/sign-up?ref=HXQGN",
        help_text="در بخش اتصالات و یادآورهای پنل دفترها، کنار «پنل پیامک ندارید؟» نمایش داده می‌شود.",
    )
    domain_service_enabled = models.BooleanField(
        "خدمت خرید و راه‌اندازی دامنه",
        default=True,
        help_text="بخش «دامنه را برایتان می‌خریم و راه می‌اندازیم» در سایت اصلی و پنل دفترها.",
    )
    free_domain_until = models.DateField(
        "طرح دامنه رایگان تا تاریخ",
        null=True,
        blank=True,
        default=datetime.date(2026, 12, 20),
        help_text="تا این تاریخ (میلادی) ثبت دامنه ir و راه‌اندازی رایگان اعلام می‌شود. خالی یعنی طرحی در کار نیست.",
    )

    @property
    def free_domain_active(self) -> bool:
        return bool(
            self.domain_service_enabled and self.free_domain_until and timezone.localdate() <= self.free_domain_until
        )

    # --- How agents pay for their subscription ---
    class PaymentMode(models.TextChoices):
        ORDER = "order", "ثبت سفارش و هماهنگی تلفنی (بدون درگاه)"
        ONLINE = "online", "پرداخت آنلاین با زرین‌پال"

    payment_mode = models.CharField(
        "روش پرداخت اشتراک", max_length=10, choices=PaymentMode.choices, default=PaymentMode.ORDER
    )
    order_grace_days = models.PositiveIntegerField(
        "روزهای فعال ماندن تا تأیید سفارش",
        default=3,
        help_text="اگر اشتراک دفتر در این فاصله تمام شود، تا تأیید پرداخت فعال می‌ماند (هر ۳۰ روز یک بار).",
    )
    order_payment_info = models.TextField(
        "اطلاعات پرداخت روی پیش‌فاکتور",
        blank=True,
        help_text="اختیاری؛ مثلاً شماره کارت یا شبا و نام صاحب حساب. خالی بماند تا فقط تلفنی هماهنگ شود.",
    )

    # --- Trust seals of the platform site itself (bimcrm.ir) ---
    enamad_code = models.CharField(
        "کد تأیید اینماد",
        max_length=20,
        blank=True,
        validators=[RegexValidator(r"^\d+$", "فقط عدد؛ همان کدی که اینماد داده، مثلاً 42186568.")],
        help_text="با وارد کردن این کد، متاتگ اینماد در صفحه اصلی و فایل خالی «کد.txt» در ریشه سایت خودکار ساخته می‌شود.",
    )
    google_site_verification = models.CharField(
        "کد تأیید گوگل (Search Console)",
        max_length=120,
        blank=True,
        help_text='فقط مقدار content از تگ <meta name="google-site-verification" content="...">. '
        "اگر سایت را با رکورد DNS تأیید کرده‌اید، لازم نیست.",
    )
    footer_badges_html = models.TextField(
        "کد نمادهای اعتماد در فوتر",
        blank=True,
        help_text="کد HTML نشان اینماد، ساماندهی و … که بعد از صدور نماد می‌گیرید. در فوتر همه صفحات bimcrm.ir نمایش داده می‌شود.",
    )

    @property
    def smsir_api_key(self) -> str:
        from .crypto import decrypt_text

        return decrypt_text(self.smsir_api_key_enc)

    @smsir_api_key.setter
    def smsir_api_key(self, value: str):
        from .crypto import encrypt_text

        self.smsir_api_key_enc = encrypt_text(value)

    class Meta:
        verbose_name = "تنظیمات پلتفرم"
        verbose_name_plural = "تنظیمات پلتفرم"

    def __str__(self):
        return "تنظیمات پلتفرم"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "PlatformSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def get_nameservers(self) -> list[str]:
        if self.nameservers.strip():
            return [n.strip().lower().rstrip(".") for n in self.nameservers.split(",") if n.strip()]
        return [n.lower() for n in settings.PLATFORM_NAMESERVERS]


class ReservedSubdomain(models.Model):
    name = models.CharField("نام", max_length=30, unique=True)
    note = models.CharField("توضیح", max_length=120, blank=True)

    class Meta:
        verbose_name = "زیردامنه رزرو"
        verbose_name_plural = "زیردامنه‌های رزرو"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip().lower()
        super().save(*args, **kwargs)


class Tenant(models.Model):
    """One agency workspace (محیط اختصاصی)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "فعال"
        SUSPENDED = "suspended", "معلق"

    name = models.CharField("نام دفتر", max_length=120)
    slug = models.CharField("زیردامنه", max_length=30, unique=True, validators=[validate_subdomain_format])
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_tenants", verbose_name="مالک"
    )
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    agency_code = models.CharField("کد نمایندگی", max_length=40, blank=True)
    phone = models.CharField("تلفن دفتر", max_length=20, blank=True)
    address = models.CharField("نشانی", max_length=255, blank=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    # Set only on the public read-only demo office; its dates are shifted forward to this day.
    demo_built_on = models.DateField("دموی عمومی (تاریخ داده‌ها)", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "محیط نماینده"
        verbose_name_plural = "محیط‌های نمایندگان"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    @property
    def subdomain_host(self) -> str:
        return f"{self.slug}.{settings.PLATFORM_DOMAIN}"

    @property
    def primary_host(self) -> str:
        domain = self.domains.filter(status=Domain.Status.ACTIVE, is_primary=True).first()
        return domain.hostname if domain else self.subdomain_host

    def panel_url(self) -> str:
        return f"{_scheme()}://{self.subdomain_host}/panel/"

    def site_url(self) -> str:
        return f"{_scheme()}://{self.primary_host}/"


def _scheme() -> str:
    return settings.PLATFORM_SCHEME


class Domain(models.Model):
    """An agent's own domain, connected by pointing its NS records at the platform."""

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار تنظیم NS"
        ACTIVE = "active", "فعال"
        ERROR = "error", "NS تغییر کرده"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="domains")
    hostname = models.CharField("دامنه", max_length=253, unique=True)
    is_primary = models.BooleanField("دامنه اصلی سایت", default=True)
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.PENDING)
    last_checked_at = models.DateTimeField("آخرین بررسی", null=True, blank=True)
    activated_at = models.DateTimeField("زمان فعال‌سازی", null=True, blank=True)
    last_seen_ns = models.CharField("NSهای دیده‌شده", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "دامنه"
        verbose_name_plural = "دامنه‌ها"
        ordering = ["-created_at"]

    def __str__(self):
        return self.hostname

    def mark_checked(self, nameservers: list[str], ok: bool):
        now = timezone.now()
        self.last_checked_at = now
        self.last_seen_ns = ", ".join(nameservers)[:255]
        if ok:
            if self.status != self.Status.ACTIVE:
                self.activated_at = now
            self.status = self.Status.ACTIVE
        elif self.status == self.Status.ACTIVE:
            self.status = self.Status.ERROR
        self.save(update_fields=["last_checked_at", "last_seen_ns", "status", "activated_at"])


class InsuranceCompany(models.Model):
    name = models.CharField("نام شرکت", max_length=80, unique=True)
    logo = models.ImageField("لوگو", upload_to="companies/", blank=True)
    website = models.URLField(
        "سایت رسمی", blank=True, help_text="اگر پر شود، کلیک روی شرکت در صفحهٔ اصلی به این آدرس می‌رود."
    )
    is_active = models.BooleanField("فعال", default=True)
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        verbose_name = "شرکت بیمه"
        verbose_name_plural = "شرکت‌های بیمه"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class LineOfBusiness(models.Model):
    """Insurance line (رشته) with the extra fields its quote form asks for."""

    name = models.CharField("نام رشته", max_length=60, unique=True)
    slug = models.SlugField("شناسه", max_length=40, unique=True, allow_unicode=False)
    summary = models.CharField("توضیح کوتاه", max_length=200, blank=True)
    icon = models.CharField(
        "آیکون", max_length=30, default="shield", help_text="car, shield, home, heart, plane, briefcase, health"
    )
    form_fields = models.JSONField(
        "فیلدهای فرم استعلام",
        default=list,
        blank=True,
        help_text='فهرست مثل [{"name": "plate", "label": "پلاک", "type": "text"}]',
    )
    required_docs = models.JSONField(
        "مدارک لازم",
        default=list,
        blank=True,
        help_text='کد مدارک لازم برای صدور، مثل ["national_card", "car_card", "prev_policy"]. کدها: national_card کارت ملی، '
        "birth_cert شناسنامه، car_card کارت خودرو، green_sheet برگ سبز، prev_policy بیمه‌نامه قبلی، no_claim تخفیف عدم خسارت، "
        "car_photos عکس خودرو، property سند ملک، medical مدارک پزشکی، passport گذرنامه، other سایر",
    )
    is_active = models.BooleanField("فعال", default=True)
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        verbose_name = "رشته بیمه"
        verbose_name_plural = "رشته‌های بیمه"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant):
        return self.filter(tenant=tenant)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Scopes every query to the tenant of the current request when one is set."""

    def get_queryset(self):
        qs = super().get_queryset()
        tenant = get_current_tenant()
        return qs.filter(tenant=tenant) if tenant is not None else qs


class TenantOwned(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="+", verbose_name="محیط")

    objects = TenantManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def ensure_tenant(self):
        if not self.tenant_id:
            tenant = get_current_tenant()
            if tenant is None:
                raise ValueError(f"{type(self).__name__} needs a tenant")
            self.tenant = tenant

    def save(self, *args, **kwargs):
        self.ensure_tenant()
        super().save(*args, **kwargs)
