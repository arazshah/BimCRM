from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import normalize_mobile, validate_mobile
from apps.billing.models import Addon, Period, StorageTier
from apps.core.models import is_subdomain_available
from apps.sites import registry


class MobileForm(forms.Form):
    mobile = forms.CharField(
        label="شماره موبایل",
        max_length=20,
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "tel", "placeholder": "۰۹۱۲۳۴۵۶۷۸۹", "dir": "ltr"}
        ),
    )

    def clean_mobile(self):
        mobile = normalize_mobile(self.cleaned_data["mobile"])
        validate_mobile(mobile)
        return mobile


class CodeForm(forms.Form):
    code = forms.CharField(
        label="کد تأیید",
        max_length=8,
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "dir": "ltr", "autofocus": True}
        ),
    )


class OfficeForm(forms.Form):
    name = forms.CharField(
        label="نام دفتر یا نمایندگی",
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "نمایندگی بیمه البرز کد ۱۲۳۴"}),
    )
    full_name = forms.CharField(label="نام شما", max_length=120)
    slug = forms.CharField(
        label="آدرس سایت (انگلیسی)",
        max_length=30,
        widget=forms.TextInput(
            attrs={"dir": "ltr", "placeholder": "alborz1234", "autocapitalize": "off", "spellcheck": "false"}
        ),
    )

    def clean_slug(self):
        slug = self.cleaned_data["slug"].strip().lower()
        ok, msg = is_subdomain_available(slug)
        if not ok:
            raise ValidationError(msg)
        return slug


class TemplateForm(forms.Form):
    template = forms.ChoiceField(label="قالب سایت", choices=registry.CHOICES, widget=forms.RadioSelect)


class PlanForm(forms.Form):
    period = forms.ChoiceField(
        label="دوره پرداخت", choices=Period.choices, widget=forms.RadioSelect, initial=Period.MONTHLY
    )
    storage_tier = forms.ModelChoiceField(
        label="فضا", queryset=StorageTier.objects.filter(is_active=True), widget=forms.RadioSelect, empty_label=None
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.addons = list(Addon.objects.filter(is_active=True))
        for addon in self.addons:
            if addon.per_unit:
                self.fields[f"addon_{addon.code}"] = forms.IntegerField(
                    label=addon.name, min_value=0, max_value=50, initial=0, required=False
                )
            else:
                self.fields[f"addon_{addon.code}"] = forms.BooleanField(label=addon.name, required=False)
        tiers = self.fields["storage_tier"].queryset
        if tiers.exists() and not self.is_bound:
            self.initial.setdefault("storage_tier", tiers.first().pk)

    def selected_addons(self) -> dict:
        result = {}
        for addon in self.addons:
            value = self.cleaned_data.get(f"addon_{addon.code}")
            qty = int(value or 0) if addon.per_unit else (1 if value else 0)
            if qty:
                result[addon] = qty
        return result

    def addon_rows(self):
        return [(addon, self[f"addon_{addon.code}"]) for addon in self.addons]
