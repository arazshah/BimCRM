"""Office finance. Add-on: finance.

Premiums the agent collects on behalf of insurers are tracked as installments/cheques, not as income.
The office's own income (commission) and expenses go in the ledger.
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import InsuranceCompany, LineOfBusiness, TenantOwned


class CommissionRule(TenantOwned):
    """Commission % by company and/or line. The most specific matching rule wins."""

    company = models.ForeignKey(
        InsuranceCompany,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="شرکت",
        help_text="خالی = همه شرکت‌ها",
    )
    line = models.ForeignKey(
        LineOfBusiness,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="رشته",
        help_text="خالی = همه رشته‌ها",
    )
    rate = models.DecimalField("نرخ کارمزد (درصد)", max_digits=5, decimal_places=2)

    class Meta:
        verbose_name = "نرخ کارمزد"
        verbose_name_plural = "نرخ‌های کارمزد"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "company", "line"], name="one_rule_per_pair", nulls_distinct=False
            )
        ]

    def __str__(self):
        return f"{self.company or 'همه شرکت‌ها'} / {self.line or 'همه رشته‌ها'}: {self.rate}٪"

    @classmethod
    def rate_for(cls, tenant_id, company_id, line_id) -> Decimal | None:
        rules = cls.all_objects.filter(tenant_id=tenant_id)
        for company, line in ((company_id, line_id), (company_id, None), (None, line_id), (None, None)):
            rule = rules.filter(company_id=company, line_id=line).first()
            if rule:
                return rule.rate
        return None


class Installment(TenantOwned):
    class Method(models.TextChoices):
        CASH = "cash", "نقد"
        CARD = "card", "کارت‌خوان"
        TRANSFER = "transfer", "واریز"
        ONLINE = "online", "درگاه آنلاین"
        CHEQUE = "cheque", "چک"

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار"
        PAID = "paid", "پرداخت‌شده"
        BOUNCED = "bounced", "برگشتی"

    policy = models.ForeignKey(
        "crm.Policy", on_delete=models.CASCADE, related_name="installments", verbose_name="بیمه‌نامه"
    )
    due_date = models.DateField("سررسید", db_index=True)
    amount = models.PositiveBigIntegerField("مبلغ (تومان)")
    method = models.CharField("روش", max_length=20, choices=Method.choices, default=Method.TRANSFER)
    cheque_number = models.CharField("شماره چک", max_length=30, blank=True)
    cheque_bank = models.CharField("بانک", max_length=60, blank=True)
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateField("تاریخ وصول", null=True, blank=True)
    note = models.CharField("توضیح", max_length=200, blank=True)

    class Meta:
        verbose_name = "قسط"
        verbose_name_plural = "اقساط و چک‌ها"
        ordering = ["due_date"]

    def __str__(self):
        return f"{self.policy} — {self.due_date}"

    @property
    def is_overdue(self) -> bool:
        return self.status == self.Status.PENDING and self.due_date < timezone.localdate()


class LedgerEntry(TenantOwned):
    class Kind(models.TextChoices):
        INCOME = "income", "درآمد"
        EXPENSE = "expense", "هزینه"

    class Category(models.TextChoices):
        COMMISSION = "commission", "کارمزد"
        RENT = "rent", "اجاره"
        SALARY = "salary", "حقوق"
        MARKETER = "marketer", "پورسانت بازاریاب"
        ADS = "ads", "تبلیغات"
        BILLS = "bills", "قبوض و شارژ"
        OTHER = "other", "سایر"

    date = models.DateField("تاریخ", default=timezone.localdate, db_index=True)
    kind = models.CharField("نوع", max_length=10, choices=Kind.choices)
    category = models.CharField("دسته", max_length=20, choices=Category.choices, default=Category.OTHER)
    amount = models.PositiveBigIntegerField("مبلغ (تومان)")
    description = models.CharField("شرح", max_length=200, blank=True)
    policy = models.ForeignKey(
        "crm.Policy", null=True, blank=True, on_delete=models.SET_NULL, verbose_name="بیمه‌نامه مرتبط"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ردیف دفتر"
        verbose_name_plural = "دفتر درآمد و هزینه"
        ordering = ["-date", "-id"]
