"""Messages the platform sends on an agent's behalf, through the agent's own SMS panel."""

from django.db import models

from apps.core.models import TenantOwned

DEFAULT_RENEWAL_TEXT = (
    "{name} عزیز، بیمه‌نامه {line} شما{subject} {days} روز دیگر ({date}) تمام می‌شود. "
    "برای تمدید با {office} تماس بگیرید: {phone}"
)
DEFAULT_INSTALLMENT_TEXT = "{name} عزیز، قسط {amount} تومانی بیمه‌نامه {line} شما سررسید {date} است. {office}"
DEFAULT_BIRTHDAY_TEXT = "{name} عزیز، تولدتان مبارک. با آرزوی سلامتی — {office}"


class ReminderSettings(TenantOwned):
    renewals_enabled = models.BooleanField("یادآور تمدید", default=True)
    renewal_days = models.CharField(
        "چند روز مانده به پایان", max_length=40, default="30,15,3", help_text="عددها را با کاما جدا کنید"
    )
    renewal_text = models.TextField("متن یادآور تمدید", default=DEFAULT_RENEWAL_TEXT)
    installments_enabled = models.BooleanField("یادآور قسط (افزونه مالی)", default=True)
    installment_days = models.CharField("چند روز مانده به سررسید قسط", max_length=40, default="3,0")
    installment_text = models.TextField("متن یادآور قسط", default=DEFAULT_INSTALLMENT_TEXT)
    birthday_enabled = models.BooleanField("تبریک تولد", default=False)
    birthday_text = models.TextField("متن تبریک تولد", default=DEFAULT_BIRTHDAY_TEXT)
    renewal_tasks_enabled = models.BooleanField(
        "ساخت خودکار «کار تماس تمدید» برای همکاران",
        default=True,
        help_text="چند روز مانده به پایان هر بیمه‌نامه، یک کار تماس در فهرست کارها ساخته می‌شود.",
    )
    renewal_task_days = models.PositiveSmallIntegerField("کار تماس تمدید، چند روز مانده", default=10)
    staff_digest_enabled = models.BooleanField(
        "پیامک کارهای روز به همکاران",
        default=False,
        help_text="هر روز ساعت ۸:۳۰ به هر همکاری که کار امروز یا عقب‌افتاده دارد، یک پیامک کوتاه از پنل پیامک دفتر می‌رود.",
    )

    class Meta:
        verbose_name = "تنظیمات یادآور"
        verbose_name_plural = "تنظیمات یادآور"
        constraints = [models.UniqueConstraint(fields=["tenant"], name="one_reminder_settings")]

    @staticmethod
    def parse_days(value: str) -> list[int]:
        days = []
        for part in (value or "").replace("،", ",").split(","):
            part = part.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            if part.isdigit() and int(part) <= 365:
                days.append(int(part))
        return sorted(set(days), reverse=True)


class Campaign(TenantOwned):
    """Group SMS. Add-on: sms_campaigns."""

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        SENDING = "sending", "در حال ارسال"
        DONE = "done", "ارسال شد"

    title = models.CharField("عنوان", max_length=120)
    text = models.TextField("متن پیامک", help_text="{name} با نام مشتری جایگزین می‌شود")
    line = models.ForeignKey(
        "core.LineOfBusiness", null=True, blank=True, on_delete=models.SET_NULL, verbose_name="فقط دارندگان رشته"
    )
    city = models.CharField("فقط شهر", max_length=60, blank=True)
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.DRAFT)
    recipients = models.PositiveIntegerField("گیرندگان", default=0)
    sent = models.PositiveIntegerField("ارسال‌شده", default=0)
    failed = models.PositiveIntegerField("ناموفق", default=0)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)

    class Meta:
        verbose_name = "کمپین پیامکی"
        verbose_name_plural = "کمپین‌های پیامکی"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class MessageLog(TenantOwned):
    class Kind(models.TextChoices):
        RENEWAL = "renewal", "یادآور تمدید"
        INSTALLMENT = "installment", "یادآور قسط"
        BIRTHDAY = "birthday", "تبریک تولد"
        CAMPAIGN = "campaign", "کمپین"
        CLAIM = "claim", "خسارت"
        QUOTE = "quote", "درخواست"
        MANUAL = "manual", "پیامک دستی"
        STAFF = "staff", "کارهای روز همکاران"

    kind = models.CharField("نوع", max_length=20, choices=Kind.choices)
    key = models.CharField(max_length=80, help_text="Prevents sending the same reminder twice")
    mobile = models.CharField("موبایل", max_length=11)
    text = models.TextField("متن")
    ok = models.BooleanField("ارسال شد", default=True)
    error = models.CharField("خطا", max_length=255, blank=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "پیامک ارسالی"
        verbose_name_plural = "پیامک‌های ارسالی"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "key"], name="unique_message_key")]
