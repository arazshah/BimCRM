from django.contrib import admin

from apps.finance.admin import TenantScopedAdmin

from .models import Marketer, MarketerPayout


@admin.register(Marketer)
class MarketerAdmin(TenantScopedAdmin):
    list_display = ("full_name", "tenant", "mobile", "code", "parent", "rate", "is_active")
    search_fields = ("full_name", "mobile", "code", "tenant__slug")


@admin.register(MarketerPayout)
class MarketerPayoutAdmin(TenantScopedAdmin):
    list_display = ("marketer", "tenant", "amount", "date")
