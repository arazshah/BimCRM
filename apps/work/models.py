"""Follow-ups: what happened with a customer (activities), what must happen next (tasks), and in-panel notifications."""

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TenantOwned


class Activity(TenantOwned):
    """One interaction with a customer, logged by a colleague."""

    class Kind(models.TextChoices):
        CALL = "call", "تماس تلفنی"
        NOTE = "note", "یادداشت"
        VISIT = "visit", "مراجعه حضوری"
        WHATSAPP = "whatsapp", "واتس‌اپ"
        SMS = "sms", "پیامک"
        EMAIL = "email", "ایمیل"

    customer = models.ForeignKey("crm.Customer", on_delete=models.CASCADE, related_name="activities")
    policy = models.ForeignKey(
        "crm.Policy", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="بیمه‌نامه"
    )
    kind = models.CharField("نوع", max_length=20, choices=Kind.choices, default=Kind.CALL)
    body = models.TextField("شرح")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField("زمان", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "تعامل"
        verbose_name_plural = "تعاملات"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.body[:40]}"


class Task(TenantOwned):
    class Priority(models.IntegerChoices):
        LOW = 1, "کم"
        NORMAL = 2, "عادی"
        HIGH = 3, "مهم"
        URGENT = 4, "فوری"

    class Kind(models.TextChoices):
        CALL = "call", "تماس"
        RENEWAL = "renewal", "تمدید"
        PAYMENT = "payment", "وصول"
        DOCS = "docs", "مدارک"
        MEETING = "meeting", "جلسه"
        OTHER = "other", "سایر"

    title = models.CharField("کار", max_length=160)
    kind = models.CharField("نوع", max_length=20, choices=Kind.choices, default=Kind.CALL)
    note = models.TextField("توضیح", blank=True)
    customer = models.ForeignKey(
        "crm.Customer", null=True, blank=True, on_delete=models.CASCADE, related_name="tasks", verbose_name="مشتری"
    )
    policy = models.ForeignKey(
        "crm.Policy", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="بیمه‌نامه"
    )
    quote = models.ForeignKey("crm.QuoteRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="مسئول",
        help_text="خالی یعنی هر کدام از همکاران",
    )
    due_date = models.DateField("موعد", db_index=True)
    due_time = models.TimeField("ساعت", null=True, blank=True)
    priority = models.PositiveSmallIntegerField("اولویت", choices=Priority.choices, default=Priority.NORMAL)
    done_at = models.DateTimeField("انجام شد", null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    auto_key = models.CharField(
        max_length=80, blank=True, help_text="Set on tasks the system created, to avoid duplicates"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "کار"
        verbose_name_plural = "کارها"
        ordering = ["done_at", "due_date", "-priority", "due_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "auto_key"], condition=~models.Q(auto_key=""), name="unique_auto_task"
            )
        ]

    def __str__(self):
        return self.title

    @property
    def is_done(self):
        return self.done_at is not None

    @property
    def is_overdue(self):
        return not self.is_done and self.due_date < timezone.localdate()


class Notification(TenantOwned):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    text = models.CharField(max_length=255)
    url = models.CharField(max_length=255, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "اعلان"
        verbose_name_plural = "اعلان‌ها"
        ordering = ["-created_at"]


def new_calendar_token():
    return secrets.token_urlsafe(24)
