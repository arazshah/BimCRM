from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import ImproperlyConfigured

from .crypto import fernet
from .dns import check_domain
from .models import Domain, InsuranceCompany, LineOfBusiness, PlatformSettings, ReservedSubdomain, Tenant


class PlatformSettingsForm(forms.ModelForm):
    smsir_api_key_input = forms.CharField(
        label="کلید API سرویس sms.ir",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password", "dir": "ltr"}),
        help_text="کلید رمزنگاری‌شده ذخیره می‌شود و دوباره نمایش داده نمی‌شود. خالی بگذارید تا کلید فعلی بماند.",
    )
    clear_smsir_api_key = forms.BooleanField(label="کلید ذخیره‌شده پاک شود", required=False)

    class Meta:
        model = PlatformSettings
        fields = [
            "trial_days",
            "grace_days",
            "data_retention_days",
            "yearly_discount_note",
            "support_phone",
            "nameservers",
            "sms_backend",
            "smsir_otp_template_id",
            "smsir_line_number",
            "zarinpal_mode",
            "zarinpal_merchant_id",
            "enamad_code",
            "footer_badges_html",
            "google_site_verification",
            "smsir_signup_url",
            "domain_service_enabled",
            "payment_mode",
            "order_grace_days",
            "order_payment_info",
        ]

    def clean(self):
        data = super().clean()
        if data.get("smsir_api_key_input"):
            try:
                fernet()
            except ImproperlyConfigured:
                self.add_error(
                    "smsir_api_key_input",
                    "کلید رمزنگاری سرور (FIELD_ENCRYPTION_KEY) معتبر نیست؛ مقدارش را در Coolify اصلاح کنید "
                    "(۴۴ نویسه که به = ختم می‌شود).",
                )
        if data.get("sms_backend") == PlatformSettings.SmsBackend.SMSIR:
            has_key = bool(data.get("smsir_api_key_input")) or (
                bool(self.instance.smsir_api_key) and not data.get("clear_smsir_api_key")
            )
            has_key = has_key or bool(settings.SMSIR_API_KEY)
            has_template = bool(data.get("smsir_otp_template_id")) or bool(settings.SMSIR_OTP_TEMPLATE_ID)
            if not has_key:
                self.add_error("smsir_api_key_input", "برای ارسال واقعی، کلید API لازم است.")
            if not has_template:
                self.add_error("smsir_otp_template_id", "برای ارسال واقعی، شناسه قالب کد تأیید لازم است.")
        if data.get("zarinpal_mode") == PlatformSettings.ZarinpalMode.LIVE:
            if not (data.get("zarinpal_merchant_id") or settings.ZARINPAL_MERCHANT_ID):
                self.add_error("zarinpal_merchant_id", "برای حالت واقعی، مرچنت کد لازم است.")
        return data


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    form = PlatformSettingsForm
    fieldsets = (
        (
            "اشتراک و نگهداری",
            {"fields": ("trial_days", "grace_days", "data_retention_days", "yearly_discount_note", "support_phone")},
        ),
        ("دامنه", {"fields": ("nameservers",)}),
        (
            "پیامک پلتفرم (sms.ir)",
            {
                "description": "کد ورود و ثبت‌نام نمایندگان با این پنل ارسال می‌شود. هر مقداری که خالی بماند، "
                "از متغیرهای محیطی سرور خوانده می‌شود. تا «ارسال واقعی» را انتخاب نکنید، کدها فقط در لاگ سرور چاپ می‌شوند.",
                "fields": (
                    "sms_backend",
                    "smsir_api_key_input",
                    "clear_smsir_api_key",
                    "smsir_otp_template_id",
                    "smsir_line_number",
                ),
            },
        ),
        (
            "خدمات همکار",
            {"fields": ("smsir_signup_url", "domain_service_enabled")},
        ),
        (
            "روش پرداخت اشتراک",
            {
                "description": "در حالت «ثبت سفارش»، نماینده پیش‌فاکتور می‌گیرد و یک تیکت مالی برای شما باز می‌شود؛ "
                "بعد از واریز، از «فاکتورها» با عمل «تأیید پرداخت و تمدید اشتراک» آن را فعال کنید.",
                "fields": ("payment_mode", "order_grace_days", "order_payment_info"),
            },
        ),
        (
            "پرداخت اشتراک‌ها (زرین‌پال)",
            {
                "description": "مرچنت کد زرین‌پال خودتان برای فروش اشتراک و افزونه. در حالت آزمایشی پرداخت واقعی انجام نمی‌شود.",
                "fields": ("zarinpal_mode", "zarinpal_merchant_id"),
            },
        ),
        (
            "اینماد، نمادهای اعتماد و گوگل",
            {
                "description": "برای تأیید مالکیت دامنه در اینماد، کد عددی را وارد کنید و ذخیره کنید؛ سپس در سایت اینماد "
                "«تایید متاتگ» یا «تایید بارگذاری» را بزنید. بعد از صدور نماد، کد نشان را در کادر دوم بگذارید.",
                "fields": ("enamad_code", "footer_badges_html", "google_site_verification"),
            },
        ),
    )

    def has_add_permission(self, request):
        return not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        new_key = form.cleaned_data.get("smsir_api_key_input")
        if new_key:
            obj.smsir_api_key = new_key.strip()
        elif form.cleaned_data.get("clear_smsir_api_key"):
            obj.smsir_api_key = ""
        super().save_model(request, obj, form, change)


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 0
    fields = ("hostname", "is_primary", "status", "last_checked_at", "last_seen_ns")
    readonly_fields = ("last_checked_at", "last_seen_ns")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "status", "subscription_status", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "slug", "owner__mobile", "agency_code")
    inlines = [DomainInline]
    actions = ["suspend", "activate"]

    @admin.display(description="اشتراک")
    def subscription_status(self, obj):
        sub = getattr(obj, "subscription", None)
        return sub.get_status_display() if sub else "—"

    @admin.action(description="تعلیق محیط‌های انتخاب‌شده")
    def suspend(self, request, queryset):
        queryset.update(status=Tenant.Status.SUSPENDED)

    @admin.action(description="فعال‌سازی محیط‌های انتخاب‌شده")
    def activate(self, request, queryset):
        queryset.update(status=Tenant.Status.ACTIVE)


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("hostname", "tenant", "status", "is_primary", "last_checked_at", "last_seen_ns")
    list_filter = ("status",)
    search_fields = ("hostname", "tenant__slug")
    actions = ["check_now"]

    @admin.action(description="بررسی NS همین حالا")
    def check_now(self, request, queryset):
        ok = sum(check_domain(d) for d in queryset)
        self.message_user(request, f"{ok} دامنه از {queryset.count()} فعال است.", messages.INFO)


@admin.register(ReservedSubdomain)
class ReservedSubdomainAdmin(admin.ModelAdmin):
    list_display = ("name", "note")
    search_fields = ("name",)


@admin.register(InsuranceCompany)
class InsuranceCompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "order")
    list_editable = ("is_active", "order")


@admin.register(LineOfBusiness)
class LineOfBusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "order")
    list_editable = ("is_active", "order")
    prepopulated_fields = {"slug": ("name",)}


admin.site.site_header = "CRM بیمه — مدیریت کل"
admin.site.site_title = "CRM بیمه"
admin.site.index_title = "پنل سوپرادمین"
