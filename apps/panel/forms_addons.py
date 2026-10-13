from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import normalize_mobile, validate_mobile
from apps.claims.models import Claim
from apps.crm.models import Policy
from apps.finance.models import CommissionRule, Installment, LedgerEntry
from apps.messaging.models import Campaign, ReminderSettings
from apps.network.models import Marketer, MarketerPayout

from .forms import JalaliDateInput


class InstallmentPlanForm(forms.Form):
    """Splits an amount into N monthly installments."""

    policy = forms.ModelChoiceField(label="بیمه‌نامه", queryset=Policy.objects.none())
    total = forms.IntegerField(label="مبلغ کل اقساط (تومان)", min_value=1)
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
        widgets = {"date": JalaliDateInput()}


class CommissionReceiveForm(forms.Form):
    amount = forms.IntegerField(label="مبلغ دریافتی (تومان)", min_value=1)


class ClaimForm(forms.ModelForm):
    class Meta:
        model = Claim
        fields = ["policy", "incident_date", "description", "amount_claimed", "insurer_file_number", "assigned_to"]
        widgets = {
            "incident_date": JalaliDateInput(),
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
    amount_paid = forms.IntegerField(label="مبلغ پرداختی (تومان)", min_value=0, required=False)


class ClaimDocumentForm(forms.Form):
    title = forms.CharField(label="عنوان مدرک", max_length=120)
    file = forms.FileField(label="فایل")


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
        widgets = {"date": JalaliDateInput()}


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ["title", "text", "line", "city"]
        widgets = {"text": forms.Textarea(attrs={"rows": 4, "maxlength": 600})}


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
