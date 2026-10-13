from django.contrib import admin

from .models import CommissionRule, Installment, LedgerEntry


class TenantScopedAdmin(admin.ModelAdmin):
    """Super admin sees every office's rows (read for support)."""

    def get_queryset(self, request):
        return self.model.all_objects.select_related("tenant")


@admin.register(Installment)
class InstallmentAdmin(TenantScopedAdmin):
    list_display = ("tenant", "policy", "due_date", "amount", "method", "status")
    list_filter = ("status", "method")
    search_fields = ("tenant__slug", "policy__number", "cheque_number")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(TenantScopedAdmin):
    list_display = ("tenant", "date", "kind", "category", "amount", "description")
    list_filter = ("kind", "category")
    search_fields = ("tenant__slug", "description")


@admin.register(CommissionRule)
class CommissionRuleAdmin(TenantScopedAdmin):
    list_display = ("tenant", "company", "line", "rate")
    search_fields = ("tenant__slug",)
