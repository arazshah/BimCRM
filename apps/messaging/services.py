import logging
from collections import defaultdict
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone

from apps.accounts.sms import SmsError
from apps.billing.models import has_feature
from apps.core.models import Tenant
from apps.core.tenancy import tenant_context
from apps.integrations.senders import send_tenant_text, tenant_can_sms

from .models import Campaign, MessageLog, ReminderSettings

log = logging.getLogger(__name__)

_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def render(template: str, **values) -> str:
    """Fills {name}-style placeholders; unknown ones become empty instead of raising."""
    safe = defaultdict(str, {k: ("" if v is None else str(v)) for k, v in values.items()})
    try:
        return template.format_map(safe).strip()
    except (ValueError, IndexError):
        return template


def send_logged(tenant, kind: str, key: str, mobile: str, text: str) -> bool | None:
    """Sends once per (tenant, key). Returns None when already sent, else whether it went out."""
    entry = MessageLog.all_objects.filter(tenant=tenant, key=key).first()
    if entry is not None and entry.ok:
        return None
    if entry is None:
        try:
            entry = MessageLog.all_objects.create(tenant=tenant, kind=kind, key=key, mobile=mobile, text=text)
        except IntegrityError:
            return None
    else:  # a previous attempt failed (e.g. the panel was out of credit): try again
        entry.ok, entry.error, entry.text = True, "", text
        entry.save(update_fields=["ok", "error", "text"])
    try:
        send_tenant_text(tenant, mobile, text)
    except SmsError as exc:
        entry.ok = False
        entry.error = str(exc)[:255]
        entry.save(update_fields=["ok", "error"])
        return False
    return True


def reminder_settings(tenant) -> ReminderSettings:
    obj, _ = ReminderSettings.all_objects.get_or_create(tenant=tenant)
    return obj


def _jdate(d) -> str:
    import jdatetime

    j = jdatetime.date.fromgregorian(date=d)
    return f"{j.year}/{j.month:02d}/{j.day:02d}".translate(_FA)


def send_daily_reminders(tenant, today=None) -> int:
    """Renewal, installment and birthday messages for one office. Safe to run more than once a day."""
    from apps.crm.models import Customer, Policy
    from apps.finance.models import Installment
    from apps.sites.models import SiteSettings

    today = today or timezone.localdate()
    cfg = reminder_settings(tenant)
    site = SiteSettings.all_objects.filter(tenant=tenant).first()
    phone = (site.phone if site else "") or tenant.phone
    count = 0

    if cfg.renewals_enabled:
        for days in cfg.parse_days(cfg.renewal_days):
            target = today + timedelta(days=days)
            policies = Policy.all_objects.filter(
                tenant=tenant, status=Policy.Status.ACTIVE, end_date=target, renewals__isnull=True
            ).select_related("customer", "line")
            for p in policies:
                text = render(
                    cfg.renewal_text,
                    name=p.customer.full_name,
                    line=p.line.name,
                    subject=f" ({p.subject})" if p.subject else "",
                    days=str(days).translate(_FA),
                    date=_jdate(p.end_date),
                    office=tenant.name,
                    phone=phone,
                )
                count += bool(
                    send_logged(tenant, MessageLog.Kind.RENEWAL, f"renewal:{p.pk}:{days}", p.customer.mobile, text)
                )

    if cfg.installments_enabled and has_feature(tenant, "finance"):
        for days in cfg.parse_days(cfg.installment_days):
            target = today + timedelta(days=days)
            items = Installment.all_objects.filter(
                tenant=tenant, status=Installment.Status.PENDING, due_date=target
            ).select_related("policy__customer", "policy__line")
            for i in items:
                text = render(
                    cfg.installment_text,
                    name=i.policy.customer.full_name,
                    line=i.policy.line.name,
                    amount=f"{i.amount:,}".replace(",", "٬").translate(_FA),
                    date=_jdate(i.due_date),
                    office=tenant.name,
                    phone=phone,
                )
                count += bool(
                    send_logged(
                        tenant,
                        MessageLog.Kind.INSTALLMENT,
                        f"installment:{i.pk}:{days}",
                        i.policy.customer.mobile,
                        text,
                    )
                )

    if cfg.birthday_enabled:
        for c in Customer.all_objects.filter(tenant=tenant, birth_date__month=today.month, birth_date__day=today.day):
            text = render(cfg.birthday_text, name=c.full_name, office=tenant.name, phone=phone)
            count += bool(
                send_logged(tenant, MessageLog.Kind.BIRTHDAY, f"birthday:{c.pk}:{today.year}", c.mobile, text)
            )
    return count


def send_all_daily_reminders(today=None) -> int:
    total = 0
    for tenant in Tenant.objects.filter(status=Tenant.Status.ACTIVE).select_related("subscription"):
        sub = getattr(tenant, "subscription", None)
        if not sub or not sub.is_writable or not tenant_can_sms(tenant):
            continue
        with tenant_context(tenant):
            try:
                total += send_daily_reminders(tenant, today)
            except Exception:  # one office's bad data must not stop the others
                log.exception("daily reminders failed for %s", tenant.slug)
    return total


def campaign_recipients(campaign: Campaign):
    from apps.crm.models import Customer

    qs = Customer.all_objects.filter(tenant=campaign.tenant, sms_opt_out=False)
    if campaign.line_id:
        qs = qs.filter(policies__line_id=campaign.line_id)
    if campaign.city:
        qs = qs.filter(city=campaign.city)
    return qs.distinct()


def run_campaign(campaign: Campaign):
    recipients = list(campaign_recipients(campaign))
    campaign.status = Campaign.Status.SENDING
    campaign.recipients = len(recipients)
    campaign.save(update_fields=["status", "recipients"])
    sent = failed = 0
    for c in recipients:
        result = send_logged(
            campaign.tenant,
            MessageLog.Kind.CAMPAIGN,
            f"campaign:{campaign.pk}:{c.pk}",
            c.mobile,
            render(campaign.text, name=c.full_name, office=campaign.tenant.name) + "\nلغو۱۱",
        )
        if result is True:
            sent += 1
        elif result is False:
            failed += 1
    campaign.sent, campaign.failed, campaign.status = sent, failed, Campaign.Status.DONE
    campaign.save(update_fields=["sent", "failed", "status"])


def notify_claim(claim, note: str = ""):
    """Tells the customer about a claim status change, if the office has an SMS panel."""
    tenant = claim.tenant
    if not tenant_can_sms(tenant):
        return
    customer = claim.policy.customer
    text = f"{customer.full_name} عزیز، وضعیت خسارت {claim.code}: {claim.get_status_display()}."
    if note:
        text += f" {note}"
    text += f" — {tenant.name}"
    send_logged(
        tenant, MessageLog.Kind.CLAIM, f"claim:{claim.pk}:{claim.status}:{claim.events.count()}", customer.mobile, text
    )
