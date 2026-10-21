"""The dashboard's "today" list: everything that waits for the agent, in one prioritised stream.

Each source (renewals, website requests, instalments, cheques, claims, tasks, birthdays) contributes rows with a
group (now / today / soon), a kind (used by the filter chips) and one action. Sources the plan or the staff
permissions do not cover are skipped, so nobody sees a row they cannot act on.
"""

from datetime import timedelta

import jdatetime
from django.db.models import Q
from django.template.defaultfilters import timesince
from django.urls import reverse

from apps.claims.models import Claim
from apps.core.templatetags.fa import toman
from apps.crm.models import Customer, Policy, QuoteRequest
from apps.finance.models import Cheque, Installment
from apps.work.models import Task

from .access import scoped

GROUPS = [("now", "فوری"), ("today", "امروز"), ("soon", "پیش رو")]
KINDS = [
    ("renew", "تمدید"),
    ("quote", "درخواست سایت"),
    ("money", "اقساط و چک"),
    ("claim", "خسارت"),
    ("task", "کارها"),
    ("birthday", "تولد"),
]
PER_SOURCE = 8


def _days(n: int) -> str:
    return "امروز" if n == 0 else f"{n} روز"


def _ago(when) -> str:
    return timesince(when).split("،")[0].replace("\xa0", " ") + " پیش"


def _row(kind, group, icon, tone, title, sub, meta, action, url, *, hot=False, post=False, primary=False, order=0):
    return {
        "kind": kind,
        "group": group,
        "icon": icon,
        "tone": tone,
        "title": title,
        "sub": sub,
        "meta": meta,
        "hot": hot,
        "action": action,
        "url": url,
        "post": post,
        "primary": primary,
        "order": order,
    }


def _renewals(request, today):
    qs = (
        scoped(request, Policy.objects.all())
        .filter(status=Policy.Status.ACTIVE, end_date__gte=today, end_date__lte=today + timedelta(days=30))
        .select_related("customer", "line", "company")
        .order_by("end_date")[:PER_SOURCE]
    )
    for p in qs:
        d = (p.end_date - today).days
        group = "now" if d <= 3 else "soon"
        sub = f"{p.line} · {p.company}" + (f" · {p.subject}" if p.subject else "")
        yield _row(
            "renew", group, "p-clock", "amber", f"تمدید — {p.customer.full_name}", sub,
            f"{d} روز مانده" if d else "امروز تمام می‌شود", "تمدید",
            reverse("panel:policy_new") + f"?renew={p.pk}", hot=d <= 3, primary=d <= 3, order=d,
        )  # fmt: skip


def _quotes(request, today):
    qs = (
        scoped(request, QuoteRequest.objects.all(), include_unassigned=True)
        .filter(status=QuoteRequest.Status.NEW)
        .select_related("line")
        .order_by("-created_at")[:PER_SOURCE]
    )
    for q in qs:
        yield _row(
            "quote", "today", "p-inbox", "violet", f"استعلام از سایت — {q.full_name}", f"{q.line} · منتظر تماس شما",
            _ago(q.created_at), "تماس", reverse("panel:quote", args=[q.pk]), order=0,
        )  # fmt: skip


def _installments(request, today):
    qs = (
        scoped(request, Installment.objects.all(), "policy__branch")
        .filter(status=Installment.Status.PENDING, due_date__lt=today)
        .select_related("policy__customer")
        .order_by("due_date")[:PER_SOURCE]
    )
    for i in qs:
        late = (today - i.due_date).days
        yield _row(
            "money", "now", "p-wallet", "red", f"قسط معوق — {i.policy.customer.full_name}",
            f"{toman(i.amount)} ریال · {i.policy.line}", f"{late} روز گذشته", "ثبت دریافت",
            reverse("panel:installment_paid", args=[i.pk]), hot=True, post=True, primary=True, order=-late,
        )  # fmt: skip


def _cheques(request, today):
    horizon = today + timedelta(days=7)
    qs = (
        scoped(request, Cheque.objects.all(), "customer__branch")
        .filter(
            Q(status=Cheque.Status.BOUNCED)
            | Q(status__in=(Cheque.Status.IN_HAND, Cheque.Status.DEPOSITED), due_date__lte=horizon)
        )
        .select_related("customer")
        .order_by("due_date")[:PER_SOURCE]
    )
    for c in qs:
        d = (c.due_date - today).days
        sub = f"{toman(c.amount)} ریال · {c.bank_name} · {c.get_status_display()}"
        if c.status == Cheque.Status.BOUNCED:
            group, title, meta, hot = "now", f"چک برگشتی — {c.customer.full_name}", "برگشت خورده", True
        elif d < 0:
            group, title, meta, hot = "now", f"چک سررسیدگذشته — {c.customer.full_name}", f"{-d} روز گذشته", True
        elif d == 0:
            group, title, meta, hot = "today", f"سررسید چک — {c.customer.full_name}", "امروز", False
        else:
            group, title, meta, hot = "soon", f"سررسید چک — {c.customer.full_name}", f"{d} روز دیگر", False
        yield _row("money", group, "p-cheque", "red" if hot else "green", title, sub, meta, "بررسی",
                   reverse("panel:cheque", args=[c.pk]), hot=hot, order=d)  # fmt: skip


def _claims(request, today):
    qs = (
        scoped(request, Claim.objects.all(), "policy__branch")
        .filter(Q(status=Claim.Status.REPORTED, reported_by_customer=True) | Q(office_unread=True))
        .select_related("policy__customer")
        .order_by("-created_at")[:PER_SOURCE]
    )
    for c in qs:
        who = c.policy.customer.full_name
        title = f"خسارت تازه از پنل مشتری — {who}" if c.reported_by_customer else f"فعالیت تازه در پروندهٔ خسارت — {who}"
        yield _row("claim", "today", "p-shield", "red", title, c.description[:70], _ago(c.created_at), "بررسی",
                   reverse("panel:claim", args=[c.pk]), order=0)  # fmt: skip


def _tasks(request, today):
    qs = (
        Task.objects.filter(done_at__isnull=True, due_date__lte=today)
        .filter(Q(assigned_to=request.user) | Q(assigned_to__isnull=True))
        .select_related("customer")
        .order_by("due_date", "-priority")[:PER_SOURCE]
    )
    for t in qs:
        late = (today - t.due_date).days
        sub = t.customer.full_name if t.customer_id else t.get_kind_display()
        yield _row(
            "task", "now" if late else "today", "p-tasks", "blue", t.title, sub,
            f"{late} روز گذشته" if late else "امروز", "انجام شد",
            reverse("panel:task_toggle", args=[t.pk]), hot=bool(late), post=True, order=-late,
        )  # fmt: skip


def _birthdays(request, today):
    """Customers whose Jalali birthday falls in the next 7 days (Gregorian dates are only used to narrow the query)."""
    targets = {}
    for n in range(8):
        d = today + timedelta(days=n)
        j = jdatetime.date.fromgregorian(date=d)
        targets[(j.month, j.day)] = n
    near = Q()
    for n in range(8):
        for shift in (-1, 0, 1):
            g = today + timedelta(days=n + shift)
            near |= Q(birth_date__month=g.month, birth_date__day=g.day)
    found = []
    for c in scoped(request, Customer.objects.exclude(birth_date=None).filter(near)).only(
        "pk", "full_name", "birth_date"
    ):
        j = jdatetime.date.fromgregorian(date=c.birth_date)
        n = targets.get((j.month, j.day))
        if n is not None:
            found.append((n, c))
    for n, c in sorted(found, key=lambda x: x[0])[:PER_SOURCE]:
        yield _row("birthday", "today" if n == 0 else "soon", "p-cake", "pink", f"تولد {c.full_name}",
                   "یک پیام تبریک مشتری را خوشحال می‌کند", "امروز" if n == 0 else f"{n} روز دیگر", "مشاهده",
                   reverse("panel:customer", args=[c.pk]), order=n)  # fmt: skip


def build_inbox(request, today, flt: str = "") -> dict:
    sources = [_renewals, _quotes, _tasks, _birthdays]
    if "finance" in request.features and request.can.get("finance"):
        sources += [_installments, _cheques]
    if "claims" in request.features and request.can.get("claims"):
        sources.append(_claims)
    rows = [r for source in sources for r in source(request, today)]
    rows.sort(key=lambda r: ([g for g, _ in GROUPS].index(r["group"]), r["order"]))

    kind_n = {k: sum(1 for r in rows if r["kind"] == k) for k, _ in KINDS}
    chips = [{"key": "", "label": "همه", "n": len(rows)}]
    chips.append({"key": "now", "label": "فوری", "n": sum(1 for r in rows if r["group"] == "now")})
    chips += [{"key": k, "label": label, "n": kind_n[k]} for k, label in KINDS if kind_n[k]]
    chips = [c for c in chips if c["key"] in ("", flt) or c["n"]]
    for c in chips:
        c["on"] = c["key"] == flt

    shown = [r for r in rows if not flt or r["group"] == flt or r["kind"] == flt]
    groups = [{"key": key, "label": label, "items": [r for r in shown if r["group"] == key]} for key, label in GROUPS]
    groups = [g for g in groups if g["items"]]
    return {
        "groups": groups,
        "chips": chips,
        "empty": not shown,
        "waiting": sum(1 for r in rows if r["group"] in ("now", "today")),
        "urgent": sum(1 for r in rows if r["group"] == "now"),
        "filter": flt,
    }


def money_stats(request, today) -> dict:
    """Receivables for the side column; only when the finance add-on is on and the user may see it."""
    from django.db.models import Count, Sum

    horizon = today + timedelta(days=7)
    inst = scoped(request, Installment.objects.all(), "policy__branch").filter(
        status=Installment.Status.PENDING, due_date__lte=horizon
    )
    chq = scoped(request, Cheque.objects.all(), "customer__branch").filter(status__in=Cheque.OPEN)
    inst_agg = inst.aggregate(n=Count("id"), s=Sum("amount"))
    chq_week = chq.filter(due_date__lte=horizon).aggregate(n=Count("id"), s=Sum("amount"))
    chq_all = chq.aggregate(n=Count("id"), s=Sum("amount"))
    return {
        "week_total": (inst_agg["s"] or 0) + (chq_week["s"] or 0),
        "week_inst": inst_agg["n"],
        "week_chq": chq_week["n"],
        "open_chq": chq_all["n"],
        "open_chq_sum": chq_all["s"] or 0,
    }


def banner(request, checklist, trial_nudge, domain_promo):
    """One banner at a time, most pressing first: trial ending, the time-limited domain offer, then unfinished setup."""
    if trial_nudge:
        return {"key": "trial", "type": "trial", "nudge": trial_nudge}
    if domain_promo:
        return {"key": "domain", "type": "domain", **domain_promo}
    done = sum(1 for c in checklist if c[1])
    if done < len(checklist) and not getattr(request, "live_demo", False):
        nxt = next(c for c in checklist if not c[1])
        return {"key": "setup", "type": "setup", "done": done, "total": len(checklist), "label": nxt[0], "url": nxt[2]}
    return None
