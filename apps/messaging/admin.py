from django.contrib import admin

from apps.finance.admin import TenantScopedAdmin

from .models import Campaign, MessageLog


@admin.register(MessageLog)
class MessageLogAdmin(TenantScopedAdmin):
    list_display = ("tenant", "kind", "mobile", "ok", "error", "created_at")
    list_filter = ("kind", "ok")
    search_fields = ("tenant__slug", "mobile")
    readonly_fields = ("tenant", "kind", "key", "mobile", "text", "ok", "error", "created_at")


@admin.register(Campaign)
class CampaignAdmin(TenantScopedAdmin):
    list_display = ("title", "tenant", "status", "recipients", "sent", "failed", "created_at")
    list_filter = ("status",)
