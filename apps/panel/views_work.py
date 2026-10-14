"""Follow-ups, tasks, calendar and notifications."""

import datetime
import secrets
import uuid
from collections import defaultdict

import jdatetime
from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Membership
from apps.core import jalali
from apps.crm.models import Customer, Policy
from apps.work.models import Notification, Task
from apps.work.services import customer_timeline, ics_escape, notify, on_task_assigned

from .access import MANAGERS, panel_view, scoped
from .forms_work import ActivityForm, CustomerSmsForm, TaskForm


def _is_manager(request):
    return request.membership.role in MANAGERS


def _visible_tasks(request):
    qs = Task.objects.select_related("customer", "assigned_to", "policy__line")
    if not _is_manager(request):
        qs = qs.filter(Q(assigned_to=request.user) | Q(assigned_to__isnull=True))
    if request.branch_scope is not None:
        qs = qs.filter(
            Q(customer__isnull=True) | Q(customer__branch=request.branch_scope) | Q(customer__branch__isnull=True)
        )
    return qs


@panel_view()
def tasks(request):
    today = timezone.localdate()
    f = request.GET.get("f", "mine")
    qs = _visible_tasks(request)
    who = request.GET.get("u", "")
    if f == "done":
        qs = qs.filter(done_at__isnull=False).order_by("-done_at")
    else:
        qs = qs.filter(done_at__isnull=True)
        if f == "mine":
            qs = qs.filter(
                Q(assigned_to=request.user) | Q(assigned_to__isnull=True),
                due_date__lte=today + datetime.timedelta(days=0),
            )
        elif f == "week":
            qs = qs.filter(due_date__lte=today + datetime.timedelta(days=7))
        if who.isdigit() and _is_manager(request):
            qs = qs.filter(assigned_to_id=int(who))
    groups = None
    if f != "done":
        groups = defaultdict(list)
        for t in qs[:300]:
            key = (
                "overdue"
                if t.due_date < today
                else "today"
                if t.due_date == today
                else "tomorrow"
                if t.due_date == today + datetime.timedelta(days=1)
                else "later"
            )
            groups[key].append(t)
        labels = {"overdue": "عقب‌افتاده", "today": "امروز", "tomorrow": "فردا", "later": "بعداً"}
        groups = [(labels[k], k, groups[k]) for k in ("overdue", "today", "tomorrow", "later") if groups.get(k)]
    counts = {
        "mine": _visible_tasks(request)
        .filter(done_at__isnull=True, due_date__lte=today)
        .filter(Q(assigned_to=request.user) | Q(assigned_to__isnull=True))
        .count(),
        "all": _visible_tasks(request).filter(done_at__isnull=True).count(),
    }
    from .forms_work import member_users

    return render(
        request,
        "panel/tasks.html",
        {
            "f": f,
            "groups": groups,
            "done": qs[:100] if f == "done" else None,
            "counts": counts,
            "today": today,
            "members": member_users(request.tenant) if _is_manager(request) else None,
            "u": who,
        },
    )


@panel_view()
def task_edit(request, pk=None):
    obj = get_object_or_404(_visible_tasks(request), pk=pk) if pk else None
    initial = {"due_date": timezone.localdate()}
    if not obj and request.GET.get("customer", "").isdigit():
        c = scoped(request, Customer.objects.all()).filter(pk=int(request.GET["customer"])).first()
        if c:
            initial.update(customer=c.pk, title=f"تماس با {c.full_name}")
    if not obj and request.GET.get("policy", "").isdigit():
        p = (
            scoped(request, Policy.objects.select_related("customer", "line"))
            .filter(pk=int(request.GET["policy"]))
            .first()
        )
        if p:
            initial.update(customer=p.customer_id, title=f"پیگیری {p.line} — {p.customer.full_name}")
    if not obj and request.GET.get("title"):
        initial["title"] = request.GET["title"][:160]
    form = TaskForm(
        request.POST or None,
        instance=obj,
        initial=initial,
        tenant=request.tenant,
        customers=scoped(request, Customer.objects.all()).order_by("full_name"),
    )
    if request.method == "POST" and form.is_valid():
        before = obj.assigned_to_id if obj else None
        task = form.save(commit=False)
        if not obj:
            task.created_by = request.user
        if not task.assigned_to_id and not _is_manager(request) and not obj:
            task.assigned_to = request.user
        task.save()
        if task.assigned_to_id != before:
            on_task_assigned(task, request.user)
        messages.success(request, "کار ذخیره شد.")
        nxt = request.POST.get("next") or request.GET.get("next")
        if nxt and nxt.startswith("/panel/"):
            return redirect(nxt)
        return redirect("panel:tasks")
    return render(
        request,
        "panel/form.html",
        {"form": form, "title": "ویرایش کار" if obj else "کار جدید", "back": "panel:tasks"},
    )


@panel_view()
@require_POST
def task_toggle(request, pk):
    task = get_object_or_404(_visible_tasks(request), pk=pk)
    if task.done_at:
        task.done_at, task.done_by = None, None
        messages.info(request, "کار دوباره باز شد.")
    else:
        task.done_at, task.done_by = timezone.now(), request.user
        messages.success(request, f"انجام شد: {task.title}")
    task.save(update_fields=["done_at", "done_by"])
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/panel/") else reverse("panel:tasks"))


@panel_view()
@require_POST
def activity_add(request, pk):
    customer = get_object_or_404(scoped(request, Customer.objects.all()), pk=pk)
    form = ActivityForm(request.POST, tenant=request.tenant)
    if form.is_valid():
        a = form.save(commit=False)
        a.customer, a.created_by = customer, request.user
        a.save()
        url = reverse("panel:customer", args=[customer.pk])
        if form.cleaned_data["notify"]:
            notify(
                request.tenant,
                [form.cleaned_data["notify"]],
                f"{request.user.full_name or 'همکار'} درباره {customer.full_name}: {a.body[:80]}",
                url + "#timeline",
                exclude=request.user,
            )
        if form.cleaned_data["follow_up"]:
            t = Task.objects.create(
                title=form.cleaned_data["follow_title"] or f"پیگیری {customer.full_name}",
                customer=customer,
                due_date=form.cleaned_data["follow_up"],
                assigned_to=form.cleaned_data["notify"] or request.user,
                created_by=request.user,
                note=a.body,
            )
            on_task_assigned(t, request.user)
        messages.success(request, "در پرونده ثبت شد.")
    else:
        messages.error(request, "شرح را بنویسید.")
    return redirect(reverse("panel:customer", args=[customer.pk]) + "#timeline")


@panel_view()
@require_POST
def customer_sms(request, pk):
    from apps.integrations.senders import tenant_can_sms
    from apps.messaging.models import MessageLog
    from apps.messaging.services import send_logged

    customer = get_object_or_404(scoped(request, Customer.objects.all()), pk=pk)
    form = CustomerSmsForm(request.POST)
    if not tenant_can_sms(request.tenant):
        messages.error(request, "اول پنل پیامک دفتر را از «اتصالات» وصل کنید.")
    elif form.is_valid():
        ok = send_logged(
            request.tenant,
            MessageLog.Kind.MANUAL,
            f"manual:{uuid.uuid4().hex[:20]}",
            customer.mobile,
            form.cleaned_data["text"],
        )
        if ok:
            messages.success(request, "پیامک ارسال شد.")
        else:
            messages.error(request, "ارسال نشد؛ اعتبار و تنظیمات پنل پیامک را بررسی کنید.")
    return redirect(reverse("panel:customer", args=[customer.pk]) + "#timeline")


def customer_work_context(request, customer):
    from apps.crm.documents import checklist, customer_lines
    from apps.crm.models import CustomerDocument
    from apps.integrations.senders import tenant_can_sms

    from .views_club import customer_club_context
    from .views_docs import DocumentForm

    return {
        **customer_club_context(request, customer),
        "documents": CustomerDocument.objects.filter(customer=customer).select_related("policy__line", "uploaded_by"),
        "doc_checklist": checklist(customer, customer_lines(customer)),
        "doc_form": DocumentForm(customer=customer),
        "timeline": customer_timeline(customer),
        "open_tasks": Task.objects.filter(customer=customer, done_at__isnull=True).select_related("assigned_to"),
        "activity_form": ActivityForm(tenant=request.tenant),
        "sms_form": CustomerSmsForm(),
        "can_sms": tenant_can_sms(request.tenant),
        "today": timezone.localdate(),
    }


# ------------------------------------------------------------------ notifications
@panel_view(write_ok_when_expired=True)
def notifications(request):
    items = Notification.objects.filter(user=request.user)[:100]
    if request.method == "POST":
        Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return redirect("panel:notifications")
    return render(request, "panel/notifications.html", {"items": items})


@panel_view(write_ok_when_expired=True)
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.read_at:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return redirect(n.url if n.url.startswith("/panel/") else "panel:notifications")


# ------------------------------------------------------------------ calendar
def _events(request_or_member, start, end, user, managers, features, branch=None, everyone=False):
    """Calendar events between [start, end): tasks, renewals, installments, birthdays."""
    ev = defaultdict(list)
    tq = Task.objects.filter(due_date__gte=start, due_date__lt=end).select_related("customer")
    if not (managers and everyone):
        tq = tq.filter(Q(assigned_to=user) | Q(assigned_to__isnull=True))
    for t in tq:
        ev[t.due_date].append(
            {
                "type": "task",
                "title": t.title,
                "done": t.done_at is not None,
                "pri": t.priority,
                "url": reverse("panel:tasks") + f"#t{t.pk}",
                "time": t.due_time,
            }
        )
    pq = Policy.objects.filter(status=Policy.Status.ACTIVE, end_date__gte=start, end_date__lt=end).select_related(
        "customer", "line"
    )
    if branch is not None:
        pq = pq.filter(branch=branch)
    for p in pq:
        ev[p.end_date].append(
            {
                "type": "renewal",
                "title": f"پایان {p.line}: {p.customer.full_name}",
                "url": reverse("panel:customer", args=[p.customer_id]),
            }
        )
    if "finance" in features:
        from apps.finance.models import Installment

        iq = Installment.objects.filter(
            due_date__gte=start, due_date__lt=end, status=Installment.Status.PENDING
        ).select_related("policy__customer")
        if branch is not None:
            iq = iq.filter(policy__branch=branch)
        for i in iq:
            ev[i.due_date].append(
                {
                    "type": "installment",
                    "title": f"قسط {i.policy.customer.full_name}",
                    "url": reverse("panel:installments"),
                }
            )
    # birthdays: compare Jalali month/day
    cq = Customer.objects.exclude(birth_date=None)
    if branch is not None:
        cq = cq.filter(branch=branch)
    days = {}
    d = start
    while d < end:
        j = jdatetime.date.fromgregorian(date=d)
        days[(j.month, j.day)] = d
        d += datetime.timedelta(days=1)
    for c in cq.only("pk", "full_name", "birth_date"):
        j = jdatetime.date.fromgregorian(date=c.birth_date)
        if (j.month, j.day) in days:
            ev[days[(j.month, j.day)]].append(
                {"type": "birthday", "title": f"تولد {c.full_name}", "url": reverse("panel:customer", args=[c.pk])}
            )
    return ev


@panel_view()
def calendar(request):
    today = timezone.localdate()
    try:
        offset = int(request.GET.get("m", "0"))
    except ValueError:
        offset = 0
    start, end, label = jalali.month_bounds(today, offset)
    everyone = request.GET.get("all") == "1"
    ev = _events(
        request, start, end, request.user, _is_manager(request), request.features, request.branch_scope, everyone
    )
    # grid: weeks start on Saturday
    first_weekday = (start.weekday() + 2) % 7  # Saturday=0
    cells = [None] * first_weekday
    d = start
    while d < end:
        j = jdatetime.date.fromgregorian(date=d)
        cells.append({"date": d, "day": j.day, "today": d == today, "events": ev.get(d, [])})
        d += datetime.timedelta(days=1)
    while len(cells) % 7:
        cells.append(None)
    weeks = [cells[i : i + 7] for i in range(0, len(cells), 7)]
    m = request.membership
    if not m.calendar_token:
        m.calendar_token = secrets.token_urlsafe(24)
        m.save(update_fields=["calendar_token"])
    feed = f"{request.scheme}://{request.get_host()}{reverse('panel:calendar_feed', args=[m.calendar_token])}"
    return render(
        request,
        "panel/calendar.html",
        {
            "weeks": weeks,
            "label": label,
            "offset": offset,
            "feed": feed,
            "everyone": everyone,
            "is_manager": _is_manager(request),
        },
    )


@panel_view()
@require_POST
def calendar_token_reset(request):
    m = request.membership
    m.calendar_token = secrets.token_urlsafe(24)
    m.save(update_fields=["calendar_token"])
    messages.success(request, "لینک تقویم عوض شد. لینک قبلی دیگر کار نمی‌کند؛ لینک تازه را دوباره اضافه کنید.")
    return redirect("panel:calendar")


def calendar_feed(request, token):
    """iCalendar subscription (Google Calendar, iPhone, Android) — authenticated by the secret link."""
    if len(token) < 20:
        raise Http404
    m = (
        Membership.objects.filter(tenant=request.tenant, calendar_token=token, is_active=True)
        .select_related("user")
        .first()
    )
    if m is None:
        raise Http404
    sub = getattr(request.tenant, "subscription", None)
    features = sub.active_addon_codes() if sub else set()
    today = timezone.localdate()
    start, end = today - datetime.timedelta(days=30), today + datetime.timedelta(days=120)
    branch = m.branch if (m.branch_id and m.role not in MANAGERS and "branches" in features) else None
    ev = _events(None, start, end, m.user, m.role in MANAGERS, features, branch, everyone=False)
    host = request.get_host()
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CRM Bime//FA",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{ics_escape(request.tenant.name)}",
        "X-WR-TIMEZONE:Asia/Tehran",
    ]
    for day, items in sorted(ev.items()):
        for k, e in enumerate(items):
            if e["type"] == "task" and e.get("done"):
                continue
            uid = f"{day:%Y%m%d}-{e['type']}-{k}-{abs(hash(e['title'])) % 10**8}@{host}"
            lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}"]
            if e.get("time"):
                dt = datetime.datetime.combine(day, e["time"])
                lines += [
                    f"DTSTART;TZID=Asia/Tehran:{dt:%Y%m%dT%H%M%S}",
                    f"DTEND;TZID=Asia/Tehran:{dt + datetime.timedelta(minutes=30):%Y%m%dT%H%M%S}",
                ]
            else:
                lines += [
                    f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
                    f"DTEND;VALUE=DATE:{day + datetime.timedelta(days=1):%Y%m%d}",
                ]
            lines += [f"SUMMARY:{ics_escape(e['title'])}", f"URL:{request.scheme}://{host}{e['url']}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    resp = HttpResponse("\r\n".join(lines) + "\r\n", content_type="text/calendar; charset=utf-8")
    resp["Cache-Control"] = "private, max-age=900"
    return resp
