from django.contrib import admin

from apps.finance.admin import TenantScopedAdmin

from .models import Claim, ClaimEvent


class ClaimEventInline(admin.TabularInline):
    model = ClaimEvent
    extra = 0
    readonly_fields = ("status", "note", "created_by", "created_at")


@admin.register(Claim)
class ClaimAdmin(TenantScopedAdmin):
    list_display = ("code", "tenant", "policy", "status", "incident_date", "amount_claimed", "amount_paid")
    list_filter = ("status", "reported_by_customer")
    search_fields = ("code", "tenant__slug", "policy__number")
    inlines = [ClaimEventInline]
