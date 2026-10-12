from django.conf import settings
from django.db import models

from apps.core.models import TenantOwned


class Ticket(TenantOwned):
    class Category(models.TextChoices):
        TECHNICAL = "technical", "فنی"
        BILLING = "billing", "مالی و اشتراک"
        DOMAIN = "domain", "دامنه و سایت"
        OTHER = "other", "سایر"

    class Status(models.TextChoices):
        OPEN = "open", "باز"
        ANSWERED = "answered", "پاسخ داده شد"
        CLOSED = "closed", "بسته"

    subject = models.CharField("موضوع", max_length=160)
    category = models.CharField("دسته", max_length=20, choices=Category.choices, default=Category.TECHNICAL)
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.OPEN)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tickets", verbose_name="ثبت‌کننده"
    )
    created_at = models.DateTimeField("ثبت", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "تیکت"
        verbose_name_plural = "تیکت‌ها"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.subject


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="نویسنده")
    body = models.TextField("متن")
    attachment = models.FileField("پیوست", upload_to="tickets/%Y/%m/", blank=True)
    is_staff_reply = models.BooleanField("پاسخ پشتیبانی", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "پیام"
        verbose_name_plural = "پیام‌ها"
