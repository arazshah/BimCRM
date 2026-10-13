from django.contrib import admin, messages

from .dns import check_domain
from .models import Domain, InsuranceCompany, LineOfBusiness, PlatformSettings, ReservedSubdomain, Tenant


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


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
