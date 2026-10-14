from django.contrib import admin, messages

from . import orders
from .models import Addon, Invoice, Package, StorageTier, Subscription, SubscriptionItem


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "monthly_price",
        "yearly_price",
        "included_users",
        "storage_tier",
        "is_recommended",
        "is_active",
        "order",
    )
    list_editable = ("monthly_price", "yearly_price", "is_recommended", "is_active", "order")
    filter_horizontal = ("addons",)
    fieldsets = (
        (None, {"fields": ("name", "tagline", "best_for", "is_recommended", "is_active", "order")}),
        ("قیمت (تومان)", {"fields": ("monthly_price", "yearly_price")}),
        ("داخل پکیج", {"fields": ("included_users", "included_domains", "storage_tier", "addons", "features")}),
        ("پیشرفته", {"classes": ("collapse",), "fields": ("description", "is_default")}),
    )


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
    list_display = (
        "order_number",
        "tenant",
        "amount",
        "period",
        "method",
        "order_state",
        "contact_mobile",
        "contact_time",
        "created_at",
        "paid_at",
    )
    list_filter = ("status", "method", "contact_time")
    search_fields = ("tenant__slug", "tenant__name", "ref_id", "authority", "contact_mobile")
    readonly_fields = ("authority", "paid_at", "contacted_at", "grace_from", "lines", "ticket")
    actions = ["action_contacted", "action_confirm", "action_cancel"]

    @admin.display(description="شماره", ordering="pk")
    def order_number(self, obj):
        return obj.number

    @admin.display(description="وضعیت")
    def order_state(self, obj):
        if obj.is_open_order:
            return "در انتظار واریز" if obj.contacted_at else "در انتظار تماس"
        return obj.get_status_display()

    @admin.action(description="ثبت شد: با دفتر تماس گرفتم")
    def action_contacted(self, request, queryset):
        n = 0
        for inv in queryset.filter(method=Invoice.Method.ORDER, status=Invoice.Status.PENDING):
            orders.mark_contacted(inv, request.user)
            n += 1
        self.message_user(request, f"{n} سفارش به «تماس گرفته شد» رفت.")

    @admin.action(description="تأیید پرداخت و تمدید اشتراک")
    def action_confirm(self, request, queryset):
        n = 0
        for inv in queryset.exclude(status=Invoice.Status.PAID):
            orders.confirm_payment(inv, request.user)
            n += 1
        self.message_user(request, f"{n} سفارش تأیید و اشتراکش تمدید شد. به دفتر پیامک رفت.", messages.SUCCESS)

    @admin.action(description="لغو سفارش")
    def action_cancel(self, request, queryset):
        n = 0
        for inv in queryset.filter(method=Invoice.Method.ORDER, status=Invoice.Status.PENDING):
            orders.cancel_order(inv, request.user)
            n += 1
        self.message_user(request, f"{n} سفارش لغو شد.")
