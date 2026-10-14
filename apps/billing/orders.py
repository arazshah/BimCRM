"""Renewal by order: the agent places an order with an itemised pre-invoice, the platform owner calls them,
arranges payment (card transfer, deposit, …) and confirms it in the super admin. A ticket carries the
conversation, and the office stays active for a few days while the order is open."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.sms import send_platform_text
from apps.core.models import PlatformSettings
from apps.tickets.models import Ticket, TicketMessage

from .models import Invoice, Period, Subscription


def order_lines(sub: Subscription, period: str) -> list[dict]:
    """The pre-invoice rows, frozen at order time so later price changes don't rewrite it."""
    label = Period(period).label
    rows = [{"title": f"پکیج {sub.package.name} ({label})", "qty": 1, "amount": sub.package.price_for(period)}]
    storage = sub.storage_extra_price(period)
    if storage:
        rows.append({"title": f"فضای بیشتر: {sub.storage_tier.storage_label}", "qty": 1, "amount": storage})
    for item in sub.extra_items():
        rows.append(
            {
                "title": item.addon.name,
                "qty": item.quantity,
                "amount": item.addon.price_for(period) * item.quantity,
            }
        )
    return rows


def open_order(tenant):
    return Invoice.objects.filter(tenant=tenant, method=Invoice.Method.ORDER, status=Invoice.Status.PENDING).first()


def _staff_note(invoice: Invoice, author, text: str, status=Ticket.Status.ANSWERED):
    if not invoice.ticket_id:
        return
    TicketMessage.objects.create(ticket=invoice.ticket, author=author, body=text, is_staff_reply=True)
    Ticket.all_objects.filter(pk=invoice.ticket_id).update(status=status, updated_at=timezone.now())


@transaction.atomic
def place_order(*, tenant, user, period: str, contact_mobile: str, contact_time: str, note: str = "") -> Invoice:
    sub: Subscription = tenant.subscription
    if period not in Period.values:
        period = sub.period
    lines = order_lines(sub, period)
    invoice = Invoice.objects.create(
        tenant=tenant,
        period=period,
        amount=sum(r["amount"] for r in lines),
        description=f"تمدید اشتراک {tenant.name} ({Period(period).label})",
        method=Invoice.Method.ORDER,
        lines=lines,
        contact_mobile=contact_mobile,
        contact_time=contact_time,
        note=note,
    )
    contact_label = Invoice.ContactTime(contact_time).label
    ticket = Ticket.all_objects.create(
        tenant=tenant,
        subject=f"سفارش تمدید {invoice.number} ({Period(period).label})",
        category=Ticket.Category.BILLING,
        created_by=user,
    )
    body = (
        f"سفارش تمدید {invoice.number}\n"
        f"دوره: {Period(period).label}\n"
        f"مبلغ: {invoice.amount:,} تومان\n"
        f"موبایل تماس: {contact_mobile}\n"
        f"زمان مناسب تماس: {contact_label}"
    )
    if note:
        body += f"\nتوضیح: {note}"
    TicketMessage.objects.create(ticket=ticket, author=user, body=body)
    invoice.ticket = ticket

    # Keep the office running while the order is being arranged (at most once every 30 days).
    grace_days = PlatformSettings.load().order_grace_days
    now = timezone.now()
    recent_grace = Invoice.objects.filter(
        tenant=tenant, grace_from__isnull=False, created_at__gte=now - timedelta(days=30)
    ).exists()
    if grace_days and not recent_grace and sub.current_period_end < now + timedelta(days=grace_days):
        invoice.grace_from = sub.current_period_end
        sub.current_period_end = now + timedelta(days=grace_days)
        if sub.status in (Subscription.Status.GRACE, Subscription.Status.EXPIRED):
            sub.status = Subscription.Status.ACTIVE
        sub.save(update_fields=["current_period_end", "status"])
    invoice.save()

    send_platform_text(
        contact_mobile,
        f"CRM بیمه: سفارش تمدید {invoice.number} به مبلغ {invoice.amount:,} تومان ثبت شد. "
        "کارشناس حساب برای هماهنگی پرداخت با شما تماس می‌گیرد.",
    )
    if settings.SUPERADMIN_MOBILE:
        send_platform_text(
            settings.SUPERADMIN_MOBILE,
            f"سفارش تمدید {invoice.number}: {tenant.name}، {invoice.amount:,} تومان، "
            f"تماس {contact_mobile} ({contact_label})",
        )
    return invoice


def mark_contacted(invoice: Invoice, by_user):
    if invoice.contacted_at or not invoice.is_open_order:
        return
    invoice.contacted_at = timezone.now()
    invoice.save(update_fields=["contacted_at"])
    _staff_note(invoice, by_user, "کارشناس حساب با شما تماس گرفت. بعد از واریز، سفارش تأیید و اشتراک تمدید می‌شود.")


@transaction.atomic
def confirm_payment(invoice: Invoice, by_user, ref_id: str = ""):
    """Mark paid and extend the subscription. Grace days granted at order time are not counted twice."""
    if invoice.status == Invoice.Status.PAID:
        return
    sub = invoice.tenant.subscription
    if invoice.grace_from:
        sub.current_period_end = invoice.grace_from
    sub.extend(invoice.period)
    invoice.status = Invoice.Status.PAID
    invoice.paid_at = timezone.now()
    invoice.contacted_at = invoice.contacted_at or invoice.paid_at
    invoice.ref_id = ref_id or invoice.ref_id or f"MANUAL-{invoice.paid_at:%Y%m%d}"
    invoice.save(update_fields=["status", "paid_at", "contacted_at", "ref_id"])
    from apps.core.templatetags.fa import jdate

    until = jdate(sub.current_period_end, "long")
    _staff_note(
        invoice, by_user, f"پرداخت تأیید شد. اشتراک تا {until} تمدید شد. ممنون از همراهی‌تان.", Ticket.Status.CLOSED
    )
    send_platform_text(
        invoice.contact_mobile or invoice.tenant.owner.mobile,
        f"CRM بیمه: پرداخت سفارش {invoice.number} تأیید شد و اشتراک «{invoice.tenant.name}» تا {until} تمدید شد.",
    )


def cancel_order(invoice: Invoice, by_user, staff=True):
    if not invoice.is_open_order:
        return
    invoice.status = Invoice.Status.CANCELLED
    invoice.save(update_fields=["status"])
    text = "سفارش لغو شد." if staff else "سفارش‌دهنده سفارش را لغو کرد."
    if staff:
        _staff_note(invoice, by_user, text, Ticket.Status.CLOSED)
    elif invoice.ticket_id:
        TicketMessage.objects.create(ticket=invoice.ticket, author=by_user, body=text)
        Ticket.all_objects.filter(pk=invoice.ticket_id).update(status=Ticket.Status.CLOSED, updated_at=timezone.now())
