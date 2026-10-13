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
    amount_claimed = models.PositiveBigIntegerField("مبلغ درخواستی (تومان)", default=0)
    amount_paid = models.PositiveBigIntegerField("مبلغ پرداختی (تومان)", default=0)
    insurer_file_number = models.CharField("شماره پرونده در شرکت بیمه", max_length=60, blank=True)
    reported_by_customer = models.BooleanField("اعلام از پنل مشتری", default=False)
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


class ClaimDocument(models.Model):
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="documents")
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
