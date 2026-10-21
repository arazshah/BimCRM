"""Claims (خسارت). Add-on: claims."""

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TenantOwned


def new_claim_code() -> str:
    return f"{secrets.randbelow(10**7):07d}"


class Claim(TenantOwned):
    class Status(models.TextChoices):
        REPORTED = "reported", "اعلام شد"
        DOCS_NEEDED = "docs_needed", "نیاز به مدارک"
        SUBMITTED = "submitted", "ارسال به شرکت بیمه"
        INSPECTION = "inspection", "بازدید کارشناس"
        APPROVED = "approved", "تأیید شد"
        PAID = "paid", "پرداخت شد"
        REJECTED = "rejected", "رد شد"

    policy = models.ForeignKey("crm.Policy", on_delete=models.PROTECT, related_name="claims", verbose_name="بیمه‌نامه")
    code = models.CharField("کد پرونده", max_length=7, default=new_claim_code, db_index=True)
    incident_date = models.DateField("تاریخ حادثه")
    description = models.TextField("شرح حادثه")
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.REPORTED)
    amount_claimed = models.PositiveBigIntegerField("مبلغ درخواستی (ریال)", default=0)
    amount_paid = models.PositiveBigIntegerField("مبلغ پرداختی (ریال)", default=0)
    insurer_file_number = models.CharField("شماره پرونده در شرکت بیمه", max_length=60, blank=True)
    reported_by_customer = models.BooleanField("اعلام از پنل مشتری", default=False)
    incident_place = models.CharField("محل حادثه", max_length=200, blank=True)
    third_party = models.TextField("مشخصات طرف مقابل / شاهد", max_length=1000, blank=True)
    iban = models.CharField("شبا برای واریز خسارت", max_length=26, blank=True)
    signed_at = models.DateTimeField("زمان امضای اظهارنامه", null=True, blank=True)
    office_unread = models.BooleanField("فعالیت جدید مشتری (خوانده‌نشده)", default=False, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="مسئول"
    )
    created_at = models.DateTimeField("ثبت", auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "خسارت"
        verbose_name_plural = "خسارت‌ها"
        ordering = ["-created_at"]

    def __str__(self):
        return f"خسارت {self.code}"

    @property
    def is_open(self) -> bool:
        return self.status not in (self.Status.PAID, self.Status.REJECTED)


class ClaimEvent(models.Model):
    """Timeline the customer also sees: each status change with an optional note."""

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20, choices=Claim.Status.choices)
    note = models.CharField("توضیح برای مشتری", max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]


class ClaimDocRequest(TenantOwned):
    """The office asks the policyholder for one specific paper; the customer answers it from the site."""

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="doc_requests")
    title = models.CharField("مدرک درخواستی", max_length=120)
    note = models.CharField("توضیح", max_length=300, blank=True)
    done = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["done", "created_at"]


class ClaimMessage(TenantOwned):
    """Conversation between the policyholder and the office, kept on the claim."""

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="messages")
    by_customer = models.BooleanField(default=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    text = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class ClaimFormFile(TenantOwned):
    """A blank form of the insurer/office (PDF or image) customers can download, fill in, sign and upload back."""

    title = models.CharField("عنوان فرم", max_length=120)
    line = models.ForeignKey(
        "core.LineOfBusiness",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="رشته (خالی = همه)",
    )
    file = models.FileField("فایل", upload_to="claimforms/%Y/%m/")
    instructions = models.CharField("راهنما", max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]


class ClaimDocument(models.Model):
    class Kind(models.TextChoices):
        PHOTO = "photo", "عکس خسارت"
        REPORT = "report", "گزارش پلیس/کروکی/کارشناسی"
        FORM = "form", "فرم خسارت امضاشده"
        IDENTITY = "identity", "مدارک هویتی و بیمه‌نامه"
        INVOICE = "invoice", "فاکتور/مدارک پزشکی یا تعمیر"
        SIGNATURE = "signature", "امضا"
        OTHER = "other", "سایر"

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.OTHER)
    request = models.ForeignKey(
        "ClaimDocRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    title = models.CharField("عنوان", max_length=120)
    file = models.FileField("فایل", upload_to="claims/%Y/%m/")
    size = models.PositiveBigIntegerField(default=0)
    uploaded_by_customer = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        try:
            self.size = self.file.size
        except (OSError, ValueError, AttributeError):
            pass
        super().save(*args, **kwargs)
