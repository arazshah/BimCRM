from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import normalize_mobile, validate_mobile
from apps.claims.models import Claim, ClaimFormFile
from apps.crm.documents import validate_upload
from apps.crm.models import Customer, Policy
from apps.finance.models import (
    Cheque,
    CommissionRule,
    FinanceAccount,
    Installment,
    LedgerEntry,
    PaymentOrder,
    Receipt,
    ReceiptLine,
)
from apps.finance.money import RialInput
from apps.messaging.models import Campaign, ReminderSettings
from apps.network.models import Marketer, MarketerPayout

from .forms import JalaliDateInput


class InstallmentPlanForm(forms.Form):
    """Splits an amount into N monthly installments."""

    policy = forms.ModelChoiceField(label="بیمه‌نامه", queryset=Policy.objects.none())
    total = forms.IntegerField(label="مبلغ کل اقساط (ریال)", min_value=1, widget=RialInput())
    count = forms.IntegerField(label="تعداد قسط", min_value=1, max_value=36, initial=4)
    first_due = forms.DateField(label="سررسید قسط اول", widget=JalaliDateInput())
    method = forms.ChoiceField(label="روش", choices=Installment.Method.choices, initial=Installment.Method.CHEQUE)

    def __init__(self, *args, policies=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = policies if policies is not None else Policy.objects.all()
        self.fields["policy"].queryset = qs.select_related("customer", "line").order_by("-start_date")
        self.fields["policy"].label_from_instance = lambda p: f"{p.customer.full_name} — {p.line} {p.number}"


class InstallmentForm(forms.ModelForm):
    class Meta:
        model = Installment
        fields = ["due_date", "amount", "method", "cheque_number", "cheque_bank", "status", "paid_at", "note"]
        widgets = {
            "amount": RialInput(),
            "due_date": JalaliDateInput(),
            "paid_at": JalaliDateInput(),
            "cheque_number": forms.TextInput(attrs={"dir": "ltr"}),
        }


class CommissionRuleForm(forms.ModelForm):
    class Meta:
        model = CommissionRule
        fields = ["company", "line", "rate"]

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant

    def clean(self):
        data = super().clean()
        qs = CommissionRule.objects.filter(company=data.get("company"), line=data.get("line"))
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("برای همین شرکت و رشته قبلاً نرخ ثبت کرده‌اید؛ همان را ویرایش کنید.")
        return data


class LedgerForm(forms.ModelForm):
    class Meta:
        model = LedgerEntry
        fields = ["date", "kind", "category", "amount", "description"]
        widgets = {"date": JalaliDateInput(), "amount": RialInput()}


class CommissionReceiveForm(forms.Form):
    amount = forms.IntegerField(label="مبلغ دریافتی (ریال)", min_value=1, widget=RialInput())


class ClaimForm(forms.ModelForm):
    class Meta:
        model = Claim
        fields = ["policy", "incident_date", "description", "amount_claimed", "insurer_file_number", "assigned_to"]
        widgets = {
            "incident_date": JalaliDateInput(),
            "amount_claimed": RialInput(),
            "description": forms.Textarea(attrs={"rows": 4}),
            "insurer_file_number": forms.TextInput(attrs={"dir": "ltr"}),
        }

    def __init__(self, *args, tenant=None, policies=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import User

        qs = policies if policies is not None else Policy.objects.all()
        self.fields["policy"].queryset = qs.select_related("customer", "line").order_by("-start_date")
        self.fields["policy"].label_from_instance = lambda p: f"{p.customer.full_name} — {p.line} {p.number}"
        self.fields["assigned_to"].queryset = User.objects.filter(
            memberships__tenant=tenant, memberships__is_active=True
        )


class ClaimStatusForm(forms.Form):
    status = forms.ChoiceField(label="وضعیت جدید", choices=Claim.Status.choices)
    note = forms.CharField(label="توضیح برای مشتری", max_length=300, required=False)
    amount_paid = forms.IntegerField(label="مبلغ پرداختی (ریال)", min_value=0, required=False, widget=RialInput())


class ClaimDocumentForm(forms.Form):
    title = forms.CharField(label="عنوان مدرک", max_length=120)
    file = forms.FileField(label="فایل")


class ClaimMessageForm(forms.Form):
    text = forms.CharField(label="پیام برای بیمه‌گذار", max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))


class ClaimRequestDocsForm(forms.Form):
    titles = forms.CharField(
        label="مدارک لازم (هر خط یک مورد)",
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "کروکی پلیس\nعکس کارت ماشین"}),
    )
    note = forms.CharField(label="توضیح (اختیاری)", max_length=300, required=False)


class ClaimFormFileForm(forms.ModelForm):
    class Meta:
        model = ClaimFormFile
        fields = ["title", "line", "file", "instructions"]

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".docx")):
            raise ValidationError("فقط PDF، عکس یا Word.")
        if f.size > 10 * 1024 * 1024:
            raise ValidationError("حجم فایل حداکثر ۱۰ مگابایت است.")
        return f


class MarketerForm(forms.ModelForm):
    class Meta:
        model = Marketer
        fields = ["full_name", "mobile", "parent", "rate", "override_rate", "is_active"]
        widgets = {"mobile": forms.TextInput(attrs={"dir": "ltr", "inputmode": "numeric"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Marketer.objects.filter(is_active=True)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = qs

    def clean_mobile(self):
        mobile = normalize_mobile(self.cleaned_data["mobile"])
        validate_mobile(mobile)
        qs = Marketer.objects.filter(mobile=mobile)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("بازاریاب دیگری با این موبایل ثبت شده است.")
        return mobile

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        node = parent
        while node is not None:
            if self.instance.pk and node.pk == self.instance.pk:
                raise ValidationError("سرگروه نمی‌تواند زیرمجموعه خود این بازاریاب باشد.")
            node = node.parent
        return parent


class PayoutForm(forms.ModelForm):
    class Meta:
        model = MarketerPayout
        fields = ["amount", "date", "note"]
        widgets = {"date": JalaliDateInput(), "amount": RialInput()}


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ["title", "text", "segment", "line", "city"]
        widgets = {"text": forms.Textarea(attrs={"rows": 4, "maxlength": 600})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.crm.segments import SEGMENTS

        self.fields["segment"] = forms.ChoiceField(
            label="فقط این بخش از مشتریان",
            required=False,
            choices=[("", "همه مشتریان")] + [(s.code, s.title) for s in SEGMENTS],
        )


class ReminderSettingsForm(forms.ModelForm):
    class Meta:
        model = ReminderSettings
        fields = [
            "renewals_enabled",
            "renewal_days",
            "renewal_text",
            "installments_enabled",
            "installment_days",
            "installment_text",
            "birthday_enabled",
            "birthday_text",
            "renewal_tasks_enabled",
            "renewal_task_days",
            "staff_digest_enabled",
        ]
        widgets = {
            "renewal_text": forms.Textarea(attrs={"rows": 3}),
            "installment_text": forms.Textarea(attrs={"rows": 2}),
            "birthday_text": forms.Textarea(attrs={"rows": 2}),
            "renewal_days": forms.TextInput(attrs={"dir": "ltr"}),
            "installment_days": forms.TextInput(attrs={"dir": "ltr"}),
        }

    def clean_renewal_days(self):
        value = self.cleaned_data["renewal_days"]
        if not ReminderSettings.parse_days(value):
            raise ValidationError("دست‌کم یک عدد مثل 30,15,3 وارد کنید.")
        return value


def parse_digits(text: str) -> str:
    """Latin digits only ('۱۲۳' → '123'); everything else is dropped."""
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return "".join(ch for ch in str(text or "").translate(table) if ch.isascii() and ch.isdigit())


# ---- cash boxes, bank accounts, received cheques (amounts in rials) ----


class FinanceAccountForm(forms.ModelForm):
    class Meta:
        model = FinanceAccount
        fields = [
            "kind",
            "title",
            "bank_name",
            "branch_name",
            "account_number",
            "sheba",
            "card_number",
            "opening_balance",
            "is_active",
        ]
        widgets = {
            "opening_balance": RialInput(),
            "account_number": forms.TextInput(attrs={"dir": "ltr"}),
            "sheba": forms.TextInput(attrs={"dir": "ltr", "maxlength": 26}),
            "card_number": forms.TextInput(attrs={"dir": "ltr", "maxlength": 19}),
        }

    def clean_sheba(self):
        value = parse_digits(self.cleaned_data.get("sheba", "").upper().removeprefix("IR"))
        if value and len(value) != 24:
            raise ValidationError("شماره شبا باید ۲۴ رقم (بدون IR) باشد.")
        return value


class ChequeForm(forms.ModelForm):
    class Meta:
        model = Cheque
        fields = [
            "customer",
            "policy",
            "installment",
            "kind",
            "serial",
            "sayad_id",
            "bank_name",
            "branch_name",
            "account_number",
            "drawer_name",
            "drawer_national_id",
            "amount",
            "issue_date",
            "due_date",
            "received_date",
            "image",
            "note",
        ]
        widgets = {
            "amount": RialInput(),
            "issue_date": JalaliDateInput(),
            "due_date": JalaliDateInput(),
            "received_date": JalaliDateInput(),
            "serial": forms.TextInput(attrs={"dir": "ltr"}),
            "sayad_id": forms.TextInput(attrs={"dir": "ltr", "maxlength": 16}),
            "account_number": forms.TextInput(attrs={"dir": "ltr"}),
            "drawer_national_id": forms.TextInput(attrs={"dir": "ltr", "maxlength": 11}),
        }

    def __init__(self, *args, customers=None, policies=None, installments=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = (customers if customers is not None else Customer.objects.all()).order_by(
            "full_name"
        )
        self.fields["policy"].queryset = (policies if policies is not None else Policy.objects.all()).select_related(
            "line"
        )
        self.fields["policy"].label_from_instance = lambda p: f"{p.line} {p.number}"
        self.fields["installment"].queryset = (
            installments if installments is not None else Installment.objects.all()
        ).exclude(status=Installment.Status.PAID)
        self.fields["installment"].label_from_instance = lambda i: f"{i.policy.number} — سررسید {i.due_date}"
        for name in ("policy", "installment"):
            self.fields[name].required = False

    def clean_sayad_id(self):
        value = parse_digits(self.cleaned_data.get("sayad_id", ""))
        if value and len(value) != 16:
            raise ValidationError("شناسه صیاد باید ۱۶ رقم باشد.")
        if value:
            dup = Cheque.objects.filter(sayad_id=value).exclude(pk=self.instance.pk)
            if dup.exists():
                raise ValidationError("چکی با این شناسه صیاد قبلاً ثبت شده است.")
        return value

    def clean_image(self):
        f = self.cleaned_data.get("image")
        if f and hasattr(f, "size"):
            err = validate_upload(f)
            if err:
                raise ValidationError(err)
        return f

    def clean(self):
        data = super().clean()
        customer, policy, inst = data.get("customer"), data.get("policy"), data.get("installment")
        if customer and policy and policy.customer_id != customer.pk:
            self.add_error("policy", "این بیمه‌نامه مال همین مشتری نیست.")
        if inst and policy and inst.policy_id != policy.pk:
            self.add_error("installment", "این قسط مربوط به بیمه‌نامه انتخاب‌شده نیست.")
        if data.get("issue_date") and data.get("due_date") and data["issue_date"] > data["due_date"]:
            self.add_error("due_date", "سررسید نمی‌تواند قبل از تاریخ صدور باشد.")
        return data


class ChequeMoveForm(forms.Form):
    status = forms.ChoiceField(label="وضعیت جدید")
    date = forms.DateField(label="تاریخ", widget=JalaliDateInput())
    account = forms.ModelChoiceField(label="حساب وصول", queryset=FinanceAccount.objects.none(), required=False)
    handed_to = forms.CharField(label="خرج‌شده به", max_length=100, required=False)
    note = forms.CharField(label="توضیح", max_length=250, required=False)

    def __init__(self, *args, cheque, **kwargs):
        super().__init__(*args, **kwargs)
        self.cheque = cheque
        self.fields["status"].choices = cheque.next_statuses
        self.fields["account"].queryset = FinanceAccount.objects.filter(is_active=True, kind=FinanceAccount.Kind.BANK)

    def clean(self):
        data = super().clean()
        status = data.get("status")
        if status in (Cheque.Status.DEPOSITED, Cheque.Status.CLEARED) and not (
            data.get("account") or self.cheque.deposit_account_id
        ):
            self.add_error("account", "حساب بانکی وصول را انتخاب کنید.")
        if status == Cheque.Status.SPENT and not data.get("handed_to"):
            self.add_error("handed_to", "نام کسی که چک به او خرج شده را بنویسید.")
        return data


# ---- receipts and payment orders ----

ACCOUNT_KINDS = {
    "cash": (FinanceAccount.Kind.CASH,),
    "card": (FinanceAccount.Kind.POS, FinanceAccount.Kind.BANK),
    "transfer": (FinanceAccount.Kind.BANK,),
}


def _check_account(form, method, account):
    kinds = ACCOUNT_KINDS.get(method)
    if kinds is None:
        return
    if account is None:
        form.add_error("account", "صندوق یا حساب را انتخاب کنید.")
    elif account.kind not in kinds:
        form.add_error("account", "این حساب با روش پرداخت انتخاب‌شده نمی‌خواند.")


class ReceiptForm(forms.ModelForm):
    class Meta:
        model = Receipt
        fields = ["date", "customer", "policy", "description"]
        widgets = {"date": JalaliDateInput()}

    def __init__(self, *args, customers=None, policies=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = (customers if customers is not None else Customer.objects.all()).order_by(
            "full_name"
        )
        self.fields["policy"].queryset = (policies if policies is not None else Policy.objects.all()).select_related(
            "line"
        )
        self.fields["policy"].label_from_instance = lambda p: f"{p.line} {p.number}"
        self.fields["policy"].required = False

    def clean(self):
        data = super().clean()
        if data.get("customer") and data.get("policy") and data["policy"].customer_id != data["customer"].pk:
            self.add_error("policy", "این بیمه‌نامه مال همین مشتری نیست.")
        return data


class ReceiptLineForm(forms.Form):
    method = forms.ChoiceField(label="روش", choices=ReceiptLine.Method.choices, required=False)
    amount = forms.IntegerField(label="مبلغ (ریال)", min_value=1, required=False, widget=RialInput())
    account = forms.ModelChoiceField(label="صندوق/حساب", queryset=FinanceAccount.objects.none(), required=False)
    cheque = forms.ModelChoiceField(label="چک", queryset=Cheque.objects.none(), required=False)
    installment = forms.ModelChoiceField(label="تسویه قسط", queryset=Installment.objects.none(), required=False)
    reference = forms.CharField(label="شماره پیگیری", max_length=60, required=False)

    def __init__(self, *args, cheques=None, installments=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = FinanceAccount.objects.filter(is_active=True)
        self.fields["cheque"].queryset = (cheques if cheques is not None else Cheque.objects.none()).filter(
            status=Cheque.Status.IN_HAND
        )
        self.fields["cheque"].label_from_instance = lambda c: f"{c.serial} — {c.bank_name} — {c.amount:,}"
        self.fields["installment"].queryset = (
            installments if installments is not None else Installment.objects.none()
        ).exclude(status=Installment.Status.PAID)
        self.fields["installment"].label_from_instance = lambda i: f"{i.policy.number} — {i.due_date}"

    def clean(self):
        data = super().clean()
        if not data.get("method") and not data.get("amount") and not data.get("cheque"):
            return data  # an empty row
        method = data.get("method")
        if method == ReceiptLine.Method.CHEQUE:
            if not data.get("cheque"):
                self.add_error("cheque", "چک را انتخاب کنید.")
            else:
                data["amount"] = data["cheque"].amount
        else:
            if not data.get("amount"):
                self.add_error("amount", "مبلغ را وارد کنید.")
            _check_account(self, method, data.get("account"))
            data["cheque"] = None
        return data


class BaseReceiptLineFormSet(forms.BaseFormSet):
    def get_form_kwargs(self, index):
        return self.form_kwargs

    def clean(self):
        super().clean()
        used = [f.cleaned_data.get("cheque") for f in self.forms if f.cleaned_data.get("cheque")]
        if len(used) != len(set(used)):
            raise ValidationError("یک چک را فقط یک بار می‌توانید در رسید بیاورید.")
        if not any(f.cleaned_data.get("amount") for f in self.forms if f.cleaned_data):
            raise ValidationError("حداقل یک ردیف دریافتی وارد کنید.")


ReceiptLineFormSet = forms.formset_factory(ReceiptLineForm, formset=BaseReceiptLineFormSet, extra=4)


class CancelForm(forms.Form):
    reason = forms.CharField(label="دلیل ابطال", max_length=250)


class PaymentOrderForm(forms.ModelForm):
    class Meta:
        model = PaymentOrder
        fields = ["date", "payee", "marketer", "category", "method", "account", "amount", "reference", "description"]
        widgets = {"date": JalaliDateInput(), "amount": RialInput()}

    def __init__(self, *args, marketers=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = FinanceAccount.objects.filter(is_active=True)
        if marketers is None:
            del self.fields["marketer"]
        else:
            self.fields["marketer"].queryset = marketers
            self.fields["marketer"].required = False
        self.fields["payee"].required = False

    def clean(self):
        data = super().clean()
        _check_account(self, data.get("method"), data.get("account"))
        if not data.get("payee"):
            if data.get("marketer"):
                data["payee"] = data["marketer"].full_name
            else:
                self.add_error("payee", "نام دریافت‌کننده را بنویسید.")
        return data
