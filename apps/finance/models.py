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
    amount = models.PositiveBigIntegerField("مبلغ (ریال)")
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
    amount = models.PositiveBigIntegerField("مبلغ (ریال)")
    description = models.CharField("شرح", max_length=200, blank=True)
    policy = models.ForeignKey(
        "crm.Policy", null=True, blank=True, on_delete=models.SET_NULL, verbose_name="بیمه‌نامه مرتبط"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ردیف دفتر"
        verbose_name_plural = "دفتر درآمد و هزینه"
        ordering = ["-date", "-id"]


# ---- Cash boxes, bank accounts and received cheques. All amounts here are in RIALS. ----


class FinanceAccount(TenantOwned):
    """A place money sits: the office cash box, a bank account or a card reader (POS)."""

    class Kind(models.TextChoices):
        CASH = "cash", "صندوق"
        BANK = "bank", "حساب بانکی"
        POS = "pos", "کارت‌خوان"

    kind = models.CharField("نوع", max_length=10, choices=Kind.choices, default=Kind.BANK)
    title = models.CharField("عنوان", max_length=80)
    bank_name = models.CharField("بانک", max_length=60, blank=True)
    branch_name = models.CharField("شعبه", max_length=60, blank=True)
    account_number = models.CharField("شماره حساب", max_length=40, blank=True)
    sheba = models.CharField("شماره شبا", max_length=26, blank=True, help_text="بدون IR، ۲۴ رقم")
    card_number = models.CharField("شماره کارت", max_length=19, blank=True)
    opening_balance = models.BigIntegerField("مانده اول دوره (ریال)", default=0)
    is_active = models.BooleanField("فعال", default=True)

    class Meta:
        verbose_name = "صندوق/حساب"
        verbose_name_plural = "صندوق‌ها و حساب‌ها"
        ordering = ["kind", "title"]

    def __str__(self):
        return self.title


class Cheque(TenantOwned):
    """A cheque received from a customer. Status moves along TRANSITIONS; every move is kept in ChequeEvent."""

    class Kind(models.TextChoices):
        NORMAL = "normal", "عادی"
        SECURITY = "security", "تضمینی"
        TRUST = "trust", "امانی"

    class Status(models.TextChoices):
        IN_HAND = "in_hand", "نزد صندوق"
        DEPOSITED = "deposited", "در جریان وصول"
        CLEARED = "cleared", "وصول‌شده"
        BOUNCED = "bounced", "برگشتی"
        SPENT = "spent", "خرج‌شده"
        RETURNED = "returned", "عودت‌شده به مشتری"
        CANCELLED = "cancelled", "باطل"

    TRANSITIONS = {
        Status.IN_HAND: [Status.DEPOSITED, Status.CLEARED, Status.SPENT, Status.RETURNED, Status.CANCELLED],
        Status.DEPOSITED: [Status.CLEARED, Status.BOUNCED, Status.IN_HAND],
        Status.BOUNCED: [Status.IN_HAND, Status.DEPOSITED, Status.RETURNED, Status.CANCELLED],
        Status.SPENT: [Status.BOUNCED, Status.IN_HAND],
        Status.CLEARED: [],
        Status.RETURNED: [],
        Status.CANCELLED: [],
    }
    OPEN = (Status.IN_HAND, Status.DEPOSITED, Status.BOUNCED)

    customer = models.ForeignKey(
        "crm.Customer", on_delete=models.PROTECT, related_name="cheques", verbose_name="دریافت از"
    )
    policy = models.ForeignKey(
        "crm.Policy",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cheques",
        verbose_name="بیمه‌نامه",
    )
    installment = models.ForeignKey(
        Installment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cheques",
        verbose_name="قسط مرتبط",
    )
    kind = models.CharField("نوع چک", max_length=10, choices=Kind.choices, default=Kind.NORMAL)
    status = models.CharField("وضعیت", max_length=12, choices=Status.choices, default=Status.IN_HAND, db_index=True)
    serial = models.CharField("شماره چک", max_length=30)
    sayad_id = models.CharField("شناسه صیاد", max_length=16, blank=True, help_text="۱۶ رقم")
    bank_name = models.CharField("بانک", max_length=60)
    branch_name = models.CharField("شعبه", max_length=60, blank=True)
    account_number = models.CharField("شماره حساب", max_length=40, blank=True)
    drawer_name = models.CharField("صاحب حساب", max_length=100, blank=True)
    drawer_national_id = models.CharField("کد ملی صاحب حساب", max_length=11, blank=True)
    amount = models.PositiveBigIntegerField("مبلغ (ریال)")
    issue_date = models.DateField("تاریخ صدور", null=True, blank=True)
    due_date = models.DateField("تاریخ سررسید", db_index=True)
    received_date = models.DateField("تاریخ دریافت", default=timezone.localdate)
    deposit_account = models.ForeignKey(
        FinanceAccount,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cheques",
        verbose_name="حساب وصول",
    )
    handed_to = models.CharField("خرج‌شده به", max_length=100, blank=True)
    image = models.FileField("تصویر چک", upload_to="cheques/%Y/%m/", blank=True)
    image_size = models.PositiveBigIntegerField(default=0, editable=False)
    note = models.CharField("توضیح", max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "چک دریافتی"
        verbose_name_plural = "چک‌های دریافتی"
        ordering = ["due_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "sayad_id"],
                condition=~models.Q(sayad_id=""),
                name="uniq_cheque_sayad_per_tenant",
            ),
        ]

    def __str__(self):
        return f"چک {self.serial} — {self.bank_name}"

    def save(self, *args, **kwargs):
        if self.image and hasattr(self.image, "size"):
            try:
                self.image_size = self.image.size
            except (OSError, ValueError):
                pass
        elif not self.image:
            self.image_size = 0
        super().save(*args, **kwargs)

    @property
    def is_overdue(self) -> bool:
        return self.status in (self.Status.IN_HAND, self.Status.DEPOSITED) and self.due_date < timezone.localdate()

    @property
    def next_statuses(self):
        return [(s.value, s.label) for s in self.TRANSITIONS.get(self.Status(self.status), [])]

    def move_to(self, status, *, user=None, when=None, note="", account=None, handed_to=""):
        """Change status, validating the move and recording it. Clearing a cheque settles its installment."""
        status = self.Status(status)
        if status not in self.TRANSITIONS[self.Status(self.status)]:
            raise ValueError(f"انتقال از «{self.get_status_display()}» به «{status.label}» مجاز نیست.")
        when = when or timezone.localdate()
        old = self.status
        self.status = status
        if account is not None:
            self.deposit_account = account
        if status == self.Status.SPENT:
            self.handed_to = handed_to
        self.save()
        ChequeEvent.objects.create(
            tenant_id=self.tenant_id, cheque=self, date=when, from_status=old, to_status=status, note=note, user=user
        )
        if status == self.Status.CLEARED and self.installment_id:
            Installment.all_objects.filter(pk=self.installment_id).exclude(status=Installment.Status.PAID).update(
                status=Installment.Status.PAID, paid_at=when
            )
        elif status == self.Status.BOUNCED and self.installment_id:
            Installment.all_objects.filter(pk=self.installment_id).update(status=Installment.Status.BOUNCED)


class ChequeEvent(TenantOwned):
    cheque = models.ForeignKey(Cheque, on_delete=models.CASCADE, related_name="events")
    date = models.DateField("تاریخ", default=timezone.localdate)
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12)
    note = models.CharField("توضیح", max_length=250, blank=True)
    user = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ثبت‌کننده"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    @property
    def to_label(self):
        return Cheque.Status(self.to_status).label

    @property
    def from_label(self):
        return Cheque.Status(self.from_status).label if self.from_status else "ثبت اولیه"


# ---- Receipts (money in) and payment orders (money out). Rials. ----


class Receipt(TenantOwned):
    """رسید دریافت: what a customer handed over, split over cash / card / transfer / cheque lines."""

    class Status(models.TextChoices):
        ACTIVE = "active", "معتبر"
        CANCELLED = "cancelled", "ابطال‌شده"

    number = models.PositiveIntegerField("شماره رسید", editable=False)
    date = models.DateField("تاریخ", default=timezone.localdate, db_index=True)
    customer = models.ForeignKey(
        "crm.Customer", on_delete=models.PROTECT, related_name="receipts", verbose_name="دریافت از"
    )
    policy = models.ForeignKey(
        "crm.Policy", null=True, blank=True, on_delete=models.SET_NULL, related_name="receipts", verbose_name="بیمه‌نامه"
    )
    description = models.CharField("شرح", max_length=250, blank=True)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.ACTIVE)
    cancel_reason = models.CharField("دلیل ابطال", max_length=250, blank=True)
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ثبت‌کننده"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "رسید دریافت"
        verbose_name_plural = "رسیدهای دریافت"
        ordering = ["-date", "-number"]
        constraints = [models.UniqueConstraint(fields=["tenant", "number"], name="uniq_receipt_number")]

    def __str__(self):
        return f"رسید {self.number}"

    @property
    def total(self) -> int:
        return sum(line.amount for line in self.lines.all())

    @classmethod
    def next_number(cls, tenant_id) -> int:
        last = cls.all_objects.filter(tenant_id=tenant_id).aggregate(m=models.Max("number"))["m"]
        return (last or 0) + 1


class ReceiptLine(TenantOwned):
    class Method(models.TextChoices):
        CASH = "cash", "نقد"
        CARD = "card", "کارت‌خوان"
        TRANSFER = "transfer", "واریز / حواله بانکی"
        CHEQUE = "cheque", "چک"

    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="lines")
    method = models.CharField("روش", max_length=10, choices=Method.choices, default=Method.CASH)
    amount = models.PositiveBigIntegerField("مبلغ (ریال)")
    account = models.ForeignKey(
        FinanceAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="receipt_lines",
        verbose_name="صندوق/حساب",
    )
    cheque = models.ForeignKey(
        Cheque, null=True, blank=True, on_delete=models.PROTECT, related_name="receipt_lines", verbose_name="چک"
    )
    installment = models.ForeignKey(
        Installment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="receipt_lines",
        verbose_name="قسط",
    )
    reference = models.CharField("شماره پیگیری / مرجع", max_length=60, blank=True)

    class Meta:
        ordering = ["id"]


class PaymentOrder(TenantOwned):
    """حواله پرداخت: money the office pays out (marketer commission, rent, refunds ...)."""

    class Method(models.TextChoices):
        CASH = "cash", "نقد"
        TRANSFER = "transfer", "واریز / حواله بانکی"
        CARD = "card", "کارت‌خوان"

    class Status(models.TextChoices):
        ACTIVE = "active", "معتبر"
        CANCELLED = "cancelled", "ابطال‌شده"

    number = models.PositiveIntegerField("شماره حواله", editable=False)
    date = models.DateField("تاریخ", default=timezone.localdate, db_index=True)
    payee = models.CharField("پرداخت به", max_length=120)
    marketer = models.ForeignKey(
        "network.Marketer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="بازاریاب",
    )
    category = models.CharField(
        "دسته", max_length=20, choices=LedgerEntry.Category.choices, default=LedgerEntry.Category.OTHER
    )
    method = models.CharField("روش", max_length=10, choices=Method.choices, default=Method.TRANSFER)
    account = models.ForeignKey(
        FinanceAccount, on_delete=models.PROTECT, related_name="payments", verbose_name="از صندوق/حساب"
    )
    amount = models.PositiveBigIntegerField("مبلغ (ریال)")
    reference = models.CharField("شماره پیگیری / مرجع", max_length=60, blank=True)
    description = models.CharField("شرح", max_length=250, blank=True)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.ACTIVE)
    cancel_reason = models.CharField("دلیل ابطال", max_length=250, blank=True)
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ثبت‌کننده"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "حواله پرداخت"
        verbose_name_plural = "حواله‌های پرداخت"
        ordering = ["-date", "-number"]
        constraints = [models.UniqueConstraint(fields=["tenant", "number"], name="uniq_payment_number")]

    def __str__(self):
        return f"حواله {self.number}"

    @classmethod
    def next_number(cls, tenant_id) -> int:
        last = cls.all_objects.filter(tenant_id=tenant_id).aggregate(m=models.Max("number"))["m"]
        return (last or 0) + 1


def account_balance(account: FinanceAccount) -> int:
    """Opening balance + money received into it − money paid out of it (rials).

    Cheques count when they are cleared into a bank account, not when they are received.
    """
    from django.db.models import Sum

    received = (
        ReceiptLine.all_objects.filter(
            account=account, receipt__status=Receipt.Status.ACTIVE, method__in=["cash", "card", "transfer"]
        ).aggregate(s=Sum("amount"))["s"]
        or 0
    )
    cleared = (
        Cheque.all_objects.filter(deposit_account=account, status=Cheque.Status.CLEARED).aggregate(s=Sum("amount"))["s"]
        or 0
    )
    paid = (
        PaymentOrder.all_objects.filter(account=account, status=PaymentOrder.Status.ACTIVE).aggregate(s=Sum("amount"))[
            "s"
        ]
        or 0
    )
    return account.opening_balance + received + cleared - paid


def create_receipt(*, tenant_id, user, data: dict, lines: list[dict]) -> Receipt:
    """Saves a receipt with its lines under the next number and settles the installments it pays."""
    from django.db import IntegrityError, transaction

    for _attempt in range(5):
        try:
            with transaction.atomic():
                receipt = Receipt.all_objects.create(
                    tenant_id=tenant_id,
                    number=Receipt.next_number(tenant_id),
                    created_by=user,
                    **data,
                )
                for line in lines:
                    obj = ReceiptLine.all_objects.create(tenant_id=tenant_id, receipt=receipt, **line)
                    inst = obj.installment
                    if inst and inst.status != Installment.Status.PAID:
                        if obj.amount >= inst.amount:
                            Installment.all_objects.filter(pk=inst.pk).update(
                                status=Installment.Status.PAID, paid_at=receipt.date
                            )
                return receipt
        except IntegrityError:
            continue
    raise RuntimeError("could not allocate a receipt number")


def cancel_receipt(receipt: Receipt, reason: str):
    """Cancels a receipt and re-opens the installments it had settled."""
    from django.db import transaction

    with transaction.atomic():
        receipt.status = Receipt.Status.CANCELLED
        receipt.cancel_reason = reason
        receipt.save(update_fields=["status", "cancel_reason"])
        for line in receipt.lines.select_related("installment"):
            inst = line.installment
            if inst and inst.status == Installment.Status.PAID and inst.paid_at == receipt.date:
                still_paid = (
                    ReceiptLine.all_objects.filter(installment=inst, receipt__status=Receipt.Status.ACTIVE)
                    .exclude(pk=line.pk)
                    .exists()
                )
                if not still_paid:
                    Installment.all_objects.filter(pk=inst.pk).update(status=Installment.Status.PENDING, paid_at=None)
