"""Follow-up helpers: notifications, automatic tasks, the customer timeline and the daily work job."""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Membership
from apps.core.models import Tenant
from apps.core.tenancy import tenant_context

from .models import Activity, Notification, Task

log = logging.getLogger(__name__)
MANAGER_ROLES = (Membership.Role.OWNER, Membership.Role.MANAGER)


def notify(tenant, users, text: str, url: str = "", exclude=None):
    rows = [
        Notification(tenant=tenant, user=u, text=text[:255], url=url)
        for u in {u for u in users if u is not None and u != exclude}
    ]
    Notification.all_objects.bulk_create(rows)


def office_members(tenant, branch=None, managers_only=False):
    """Active colleagues who should hear about something: managers, plus staff of that branch (or unbranched)."""
    users = []
    for m in Membership.objects.filter(tenant=tenant, is_active=True).select_related("user"):
        if m.role in MANAGER_ROLES:
            users.append(m.user)
        elif not managers_only and (branch is None or m.branch_id is None or m.branch_id == branch.pk):
            users.append(m.user)
    return users


def auto_task(tenant, key: str, **fields) -> Task | None:
    """Creates a system task once per key (e.g. one renewal call per policy)."""
    if Task.all_objects.filter(tenant=tenant, auto_key=key).exists():
        return None
    try:
        with transaction.atomic():
            return Task.all_objects.create(tenant=tenant, auto_key=key, **fields)
    except IntegrityError:
        return None


def on_new_quote(quote):
    """A site visitor asked for a quote: a call task for today and a heads-up for the office."""
    tenant = quote.tenant
    auto_task(
        tenant,
        f"quote:{quote.pk}",
        title=f"تماس با {quote.full_name} — استعلام {quote.line}",
        kind=Task.Kind.CALL,
        quote=quote,
        customer=quote.customer,
        assigned_to=quote.assigned_to,
        due_date=timezone.localdate(),
        priority=Task.Priority.HIGH,
    )
    url = reverse("panel:quote", args=[quote.pk])
    notify(
        tenant,
        office_members(tenant, getattr(quote, "branch", None)),
        f"درخواست تازه از سایت: {quote.full_name} ({quote.line})",
        url,
    )


def on_customer_claim(claim):
    url = reverse("panel:claim", args=[claim.pk])
    notify(
        claim.tenant,
        office_members(claim.tenant, getattr(claim.policy.customer, "branch", None)),
        f"خسارت تازه از پنل مشتری: {claim.policy.customer.full_name}",
        url,
    )


def on_task_assigned(task, by):
    if task.assigned_to_id and task.assigned_to != by:
        who = by.full_name if by else "سیستم"
        notify(
            task.tenant,
            [task.assigned_to],
            f"{who} یک کار به شما سپرد: {task.title}",
            reverse("panel:tasks") + f"#t{task.pk}",
        )


# ---------------------------------------------------------------- timeline
def customer_timeline(customer, limit: int = 60) -> list[dict]:
    """Everything that happened with a customer, newest first."""
    from apps.claims.models import ClaimEvent
    from apps.crm.models import QuoteRequest
    from apps.messaging.models import MessageLog

    items = []
    for a in Activity.objects.filter(customer=customer).select_related("created_by", "policy__line")[:limit]:
        items.append(
            {
                "at": a.created_at,
                "kind": a.kind,
                "title": a.get_kind_display(),
                "body": a.body,
                "by": a.created_by,
                "extra": str(a.policy.line) if a.policy_id else "",
            }
        )
    for m in MessageLog.objects.filter(mobile=customer.mobile).exclude(kind=MessageLog.Kind.STAFF)[:limit]:
        items.append(
            {
                "at": m.created_at,
                "kind": "sms_out",
                "title": f"پیامک: {m.get_kind_display()}",
                "body": m.text,
                "ok": m.ok,
                "error": m.error,
            }
        )
    for p in customer.policies.select_related("line", "company"):
        items.append(
            {
                "at": p.created_at,
                "kind": "policy",
                "title": f"ثبت بیمه‌نامه {p.line}",
                "body": f"{p.company} · {p.number}",
            }
        )
    for q in QuoteRequest.objects.filter(mobile=customer.mobile).select_related("line"):
        items.append(
            {
                "at": q.created_at,
                "kind": "quote",
                "title": f"درخواست از سایت: {q.line}",
                "body": q.message,
                "url": reverse("panel:quote", args=[q.pk]),
            }
        )
    for e in ClaimEvent.objects.filter(claim__policy__customer=customer).select_related("claim", "created_by"):
        items.append(
            {
                "at": e.created_at,
                "kind": "claim",
                "title": f"خسارت {e.claim.code}: {e.get_status_display()}",
                "body": e.note,
                "by": e.created_by,
                "url": reverse("panel:claim", args=[e.claim_id]),
            }
        )
    for t in Task.objects.filter(customer=customer, done_at__isnull=False).select_related("done_by"):
        items.append(
            {"at": t.done_at, "kind": "task", "title": f"انجام شد: {t.title}", "body": t.note, "by": t.done_by}
        )
    items.sort(key=lambda i: i["at"], reverse=True)
    return items[:limit]


# ---------------------------------------------------------------- daily job
def renewal_tasks(tenant, today=None) -> int:
    from apps.crm.models import Policy
    from apps.messaging.models import ReminderSettings

    rs = ReminderSettings.objects.filter(tenant=tenant).first()
    if rs is not None and not rs.renewal_tasks_enabled:
        return 0
    days = rs.renewal_task_days if rs else 10
    today = today or timezone.localdate()
    created = 0
    due = Policy.objects.filter(
        status=Policy.Status.ACTIVE,
        end_date__gte=today,
        end_date__lte=today + timedelta(days=days),
        renewals__isnull=True,
    ).select_related("customer", "line")
    for p in due:
        t = auto_task(
            tenant,
            f"renew:{p.pk}:{p.end_date:%Y%m%d}",
            title=f"تماس برای تمدید {p.line} — {p.customer.full_name}",
            kind=Task.Kind.RENEWAL,
            customer=p.customer,
            policy=p,
            due_date=today,
            priority=Task.Priority.HIGH if (p.end_date - today).days <= 3 else Task.Priority.NORMAL,
        )
        created += t is not None
    return created


def open_tasks_for(user, tenant):
    from django.db.models import Q

    return Task.objects.filter(done_at__isnull=True).filter(Q(assigned_to=user) | Q(assigned_to__isnull=True))


def staff_digest(tenant, today=None) -> int:
    from apps.integrations.senders import tenant_can_sms
    from apps.messaging.models import MessageLog, ReminderSettings
    from apps.messaging.services import send_logged

    rs = ReminderSettings.objects.filter(tenant=tenant).first()
    if not rs or not rs.staff_digest_enabled or not tenant_can_sms(tenant):
        return 0
    today = today or timezone.localdate()
    sent = 0
    for m in Membership.objects.filter(tenant=tenant, is_active=True).select_related("user"):
        tasks = open_tasks_for(m.user, tenant).filter(due_date__lte=today)
        n = tasks.count()
        if not n:
            continue
        urgent = tasks.filter(priority__gte=Task.Priority.HIGH).count()
        name = (m.user.full_name or "").split(" ")[0] or "همکار"
        text = (
            f"{name} عزیز، امروز {n} کار در پنل دارید"
            + (f" ({urgent} مهم)" if urgent else "")
            + f". {tenant.subdomain_host}/panel/tasks/"
        )
        if send_logged(tenant, MessageLog.Kind.STAFF, f"digest:{m.pk}:{today:%Y%m%d}", m.user.mobile, text):
            sent += 1
    return sent


def run_daily_work(today=None) -> dict:
    totals = {"renewal_tasks": 0, "digests": 0}
    for tenant in Tenant.objects.filter(status=Tenant.Status.ACTIVE).select_related("subscription"):
        sub = getattr(tenant, "subscription", None)
        if not sub or not sub.is_writable:
            continue
        with tenant_context(tenant):
            try:
                totals["renewal_tasks"] += renewal_tasks(tenant, today)
                totals["digests"] += staff_digest(tenant, today)
            except Exception:
                log.exception("daily work failed for %s", tenant.slug)
    return totals


def ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", r"\;").replace(",", "\\,").replace("\n", "\\n")


def platform_host() -> str:
    return settings.PLATFORM_DOMAIN
