from django.contrib import admin

from .models import Addon, Invoice, Package, StorageTier, Subscription, SubscriptionItem


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("name", "monthly_price", "yearly_price", "included_users", "is_default", "is_active")
    list_editable = ("monthly_price", "yearly_price", "is_active")


@admin.register(StorageTier)
class StorageTierAdmin(admin.ModelAdmin):
    list_display = ("name", "storage_mb", "monthly_price", "yearly_price", "is_active", "order")
    list_editable = ("monthly_price", "yearly_price", "is_active", "order")


@admin.register(Addon)
class AddonAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "monthly_price", "yearly_price", "per_unit", "is_active", "order")
    list_editable = ("monthly_price", "yearly_price", "is_active", "order")


class SubscriptionItemInline(admin.TabularInline):
    model = SubscriptionItem
    extra = 0


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "status", "period", "storage_tier", "current_period_end")
    list_filter = ("status", "period")
    search_fields = ("tenant__slug", "tenant__name", "tenant__owner__mobile")
    inlines = [SubscriptionItemInline]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "amount", "period", "status", "ref_id", "created_at", "paid_at")
    list_filter = ("status",)
    search_fields = ("tenant__slug", "ref_id", "authority")
    readonly_fields = ("authority", "ref_id", "paid_at")
