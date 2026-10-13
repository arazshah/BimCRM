from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import Membership, normalize_mobile, validate_mobile
from apps.core.dns import HOSTNAME_RE, normalize_hostname
from apps.core.models import Domain
from apps.crm.models import Customer, Policy, QuoteRequest
from apps.sites.models import FAQ, SiteSettings, Testimonial
from apps.tickets.models import Ticket


class JalaliDateInput(forms.DateInput):
    """Native date picker for now; values are stored Gregorian and shown Jalali in lists."""

    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


def _limit_addon_fields(form, features):
    """Fields that belong to add-ons only appear when the office has that add-on."""
    from apps.network.models import Marketer

    if "marketer" in form.fields:
        if "marketers" in features:
            form.fields["marketer"].queryset = Marketer.objects.filter(is_active=True)
        else:
            del form.fields["marketer"]
    if "commission_rate" in form.fields and "finance" not in features:
        del form.fields["commission_rate"]


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "full_name",
            "mobile",
            "national_code",
            "birth_date",
            "city",
            "source",
            "marketer",
            "notes",
            "sms_opt_out",
        ]
        widgets = {
            "birth_date": JalaliDateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "mobile": forms.TextInput(attrs={"dir": "ltr", "inputmode": "numeric"}),
            "national_code": forms.TextInput(attrs={"dir": "ltr", "inputmode": "numeric"}),
        }

    def __init__(self, *args, features=frozenset(), **kwargs):
        super().__init__(*args, **kwargs)
        _limit_addon_fields(self, features)

    def clean_mobile(self):
        mobile = normalize_mobile(self.cleaned_data["mobile"])
        validate_mobile(mobile)
        qs = Customer.objects.filter(mobile=mobile)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("مشتری دیگری با این موبایل ثبت شده است.")
        return mobile


class PolicyForm(forms.ModelForm):
    class Meta:
        model = Policy
        fields = [
            "customer",
            "line",
            "company",
            "number",
            "subject",
            "start_date",
            "end_date",
            "premium",
            "file",
            "status",
            "commission_rate",
            "marketer",
        ]
        widgets = {
            "start_date": JalaliDateInput(),
            "end_date": JalaliDateInput(),
            "number": forms.TextInput(attrs={"dir": "ltr"}),
        }

    def __init__(self, *args, storage_left: int | None = None, features=frozenset(), **kwargs):
        super().__init__(*args, **kwargs)
        _limit_addon_fields(self, features)
        self.storage_left = storage_left
        self.fields["customer"].queryset = Customer.objects.all()
        self.fields["line"].queryset = self.fields["line"].queryset.filter(is_active=True)
        self.fields["company"].queryset = self.fields["company"].queryset.filter(is_active=True)

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end <= start:
            self.add_error("end_date", "تاریخ پایان باید بعد از شروع باشد.")
        f = data.get("file")
        if f and hasattr(f, "size") and self.storage_left is not None and f.size > self.storage_left:
            self.add_error("file", "فضای محیط شما پر است. از بخش اشتراک فضای بیشتری اضافه کنید.")
        return data


class QuoteUpdateForm(forms.ModelForm):
    class Meta:
        model = QuoteRequest
        fields = ["status", "assigned_to", "staff_note"]
        widgets = {"staff_note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import User

        self.fields["assigned_to"].queryset = User.objects.filter(
            memberships__tenant=tenant, memberships__is_active=True
        )


class SiteContentForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = [
            "hero_title",
            "hero_subtitle",
            "about",
            "years_active",
            "customers_count",
            "phone",
            "whatsapp",
            "email",
            "address",
            "working_hours",
            "lines",
            "companies",
            "primary_color",
            "logo",
            "seo_description",
        ]
        widgets = {
            "about": forms.Textarea(attrs={"rows": 5}),
            "lines": forms.CheckboxSelectMultiple,
            "companies": forms.CheckboxSelectMultiple,
            "primary_color": forms.TextInput(attrs={"type": "color"}),
            "phone": forms.TextInput(attrs={"dir": "ltr"}),
            "whatsapp": forms.TextInput(attrs={"dir": "ltr"}),
            "email": forms.EmailInput(attrs={"dir": "ltr"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lines"].queryset = self.fields["lines"].queryset.filter(is_active=True)
        self.fields["companies"].queryset = self.fields["companies"].queryset.filter(is_active=True)


TestimonialFormSet = forms.modelformset_factory(
    Testimonial, fields=["name", "text", "is_visible"], extra=1, can_delete=True
)
FAQFormSet = forms.modelformset_factory(
    FAQ,
    fields=["question", "answer", "order"],
    extra=1,
    can_delete=True,
    widgets={"answer": forms.Textarea(attrs={"rows": 2})},
)


class DomainForm(forms.Form):
    hostname = forms.CharField(
        label="دامنه شما", max_length=253, widget=forms.TextInput(attrs={"dir": "ltr", "placeholder": "alborz1234.ir"})
    )

    def clean_hostname(self):
        from django.conf import settings

        host = normalize_hostname(self.cleaned_data["hostname"])
        if not HOSTNAME_RE.match(host):
            raise ValidationError("دامنه را به شکل example.ir وارد کنید.")
        if host == settings.PLATFORM_DOMAIN or host.endswith("." + settings.PLATFORM_DOMAIN):
            raise ValidationError("زیردامنه bimcrm.ir از قبل برای شما فعال است؛ دامنه خودتان را وارد کنید.")
        if Domain.objects.filter(hostname=host).exists():
            raise ValidationError("این دامنه به محیط دیگری وصل است. اگر مال شماست تیکت بزنید.")
        return host


class MemberForm(forms.Form):
    mobile = forms.CharField(
        label="موبایل همکار", max_length=20, widget=forms.TextInput(attrs={"dir": "ltr", "inputmode": "numeric"})
    )
    full_name = forms.CharField(label="نام همکار", max_length=120)
    role = forms.ChoiceField(
        label="نقش", choices=[(Membership.Role.MANAGER, "مدیر"), (Membership.Role.STAFF, "کارمند")]
    )

    def clean_mobile(self):
        mobile = normalize_mobile(self.cleaned_data["mobile"])
        validate_mobile(mobile)
        return mobile


class TicketForm(forms.ModelForm):
    body = forms.CharField(label="شرح", widget=forms.Textarea(attrs={"rows": 5}))
    attachment = forms.FileField(label="پیوست (اختیاری)", required=False)

    class Meta:
        model = Ticket
        fields = ["subject", "category"]


class ReplyForm(forms.Form):
    body = forms.CharField(label="پاسخ", widget=forms.Textarea(attrs={"rows": 4}))
    attachment = forms.FileField(label="پیوست (اختیاری)", required=False)


class ImportForm(forms.Form):
    file = forms.FileField(
        label="فایل CSV مشتریان",
        help_text="ستون‌ها: نام، موبایل، کد ملی، شهر (ردیف اول عنوان). از اکسل «ذخیره به CSV UTF-8» بگیرید.",
    )
