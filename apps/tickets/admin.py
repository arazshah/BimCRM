from django.contrib import admin

from apps.accounts.sms import send_platform_text

from .models import Ticket, TicketMessage


class TicketMessageInline(admin.StackedInline):
    model = TicketMessage
    extra = 1
    fields = ("author", "body", "attachment", "is_staff_reply", "created_at")
    readonly_fields = ("author", "is_staff_reply", "created_at")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("subject", "tenant", "category", "status", "updated_at")
    list_filter = ("status", "category")
    search_fields = ("subject", "tenant__slug", "tenant__name")
    inlines = [TicketMessageInline]
    readonly_fields = ("tenant", "created_by", "created_at", "updated_at")

    def get_queryset(self, request):
        return Ticket.all_objects.select_related("tenant")

    def save_formset(self, request, form, formset, change):
        replied = False
        for msg in formset.save(commit=False):
            if not msg.pk:
                msg.author = request.user
                msg.is_staff_reply = True
                replied = True
            msg.save()
        formset.save_m2m()
        ticket = form.instance
        if replied:
            ticket.status = Ticket.Status.ANSWERED
            ticket.save(update_fields=["status", "updated_at"])
            send_platform_text(
                ticket.created_by.mobile, f"CRM بیمه: به تیکت «{ticket.subject}» پاسخ داده شد. پنل > پشتیبانی"
            )
