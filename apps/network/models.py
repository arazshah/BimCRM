"""Marketers (بازاریاب‌ها) and their two-level commission. Add-on: marketers."""

import secrets
from decimal import Decimal

from django.db import models
from django.db.models import Sum

from apps.core.models import TenantOwned


def new_ref_code() -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


class Marketer(TenantOwned):
    full_name = models.CharField("نام", max_length=120)
    mobile = models.CharField("موبایل", max_length=11)
    code = models.CharField("کد معرف", max_length=12, default=new_ref_code)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children", verbose_name="سرگروه"
    )
    rate = models.DecimalField(
        "کمیسیون از حق بیمه (درصد)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("2.00"),
        help_text="از حق بیمه بیمه‌نامه‌هایی که خودش آورده",
    )
    override_rate = models.DecimalField(
        "کمیسیون سرگروهی (درصد)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.50"),
        help_text="از حق بیمه بیمه‌نامه‌های زیرمجموعه‌های مستقیمش",
    )
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "بازاریاب"
        verbose_name_plural = "بازاریابان"
        ordering = ["full_name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="unique_marketer_code"),
            models.UniqueConstraint(fields=["tenant", "mobile"], name="unique_marketer_mobile"),
        ]

    def __str__(self):
        return self.full_name

    def earned(self, start=None, end=None) -> int:
        """Own commission plus override on direct children's policies, for policies started in [start, end)."""
        from apps.crm.models import Policy

        def premium(qs):
            if start:
                qs = qs.filter(start_date__gte=start)
            if end:
                qs = qs.filter(start_date__lt=end)
            return qs.exclude(status=Policy.Status.CANCELLED).aggregate(s=Sum("premium"))["s"] or 0

        own = premium(Policy.all_objects.filter(marketer=self))
        team = premium(Policy.all_objects.filter(marketer__parent=self))
        return int(own * self.rate / 100 + team * self.override_rate / 100)

    def paid(self) -> int:
        return self.payouts.aggregate(s=Sum("amount"))["s"] or 0


class MarketerPayout(TenantOwned):
    marketer = models.ForeignKey(Marketer, on_delete=models.CASCADE, related_name="payouts", verbose_name="بازاریاب")
    amount = models.PositiveBigIntegerField("مبلغ (تومان)")
    date = models.DateField("تاریخ")
    note = models.CharField("توضیح", max_length=200, blank=True)

    class Meta:
        verbose_name = "تسویه بازاریاب"
        verbose_name_plural = "تسویه‌های بازاریاب"
        ordering = ["-date"]
