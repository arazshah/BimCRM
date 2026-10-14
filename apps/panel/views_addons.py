"""Panel sections for add-ons (finance, claims, marketers, SMS campaigns, advanced reports) and reminders."""

import csv
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.claims.models import Claim, ClaimDocument, ClaimEvent
from apps.core import jalali
from apps.crm.models import Policy
from apps.finance.models import CommissionRule, Installment, LedgerEntry
from apps.integrations.senders import tenant_can_sms
from apps.messaging.models import Campaign, MessageLog
from apps.messaging.services import campaign_recipients, notify_claim, reminder_settings
from apps.network.models import Marketer

from .access import branch_filter, panel_view, scoped, storage_used_bytes
from .forms_addons import (
    CampaignForm,
    ClaimDocumentForm,
    ClaimForm,
    ClaimStatusForm,
    CommissionReceiveForm,
    CommissionRuleForm,
    InstallmentForm,
    InstallmentPlanForm,
    LedgerForm,
    MarketerForm,
    PayoutForm,
    ReminderSettingsForm,
)


def _next(request, default: str):
    """Only same-site paths are accepted as a post-action destination."""
    nxt = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}) and nxt.startswith("/"):
        return redirect(nxt)
    return redirect(default)


def _csv_cell(value):
    """Stops spreadsheet formula injection (=, +, -, @ at the start of a cell)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _month(request):
    """The Jalali month chosen with ?m=-1, -2 … (0 = this month)."""
    try:
        offset = max(-36, min(0, int(request.GET.get("m", 0))))
    except ValueError:
        offset = 0
    start, end, label = jalali.month_bounds(timezone.localdate(), offset)
    return offset, start, end, label


# ======================= Reminders (base package) =======================


@panel_view(perm="reminders")
def reminders(request):
    cfg = reminder_settings(request.tenant)
    form = ReminderSettingsForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تنظیمات یادآور ذخیره شد.")
        return redirect("panel:reminders")
    logs = MessageLog.objects.all()[:30]
    return render(
        request,
        "panel/reminders.html",
        {
            "form": form,
            "logs": logs,
            "can_sms": tenant_can_sms(request.tenant),
            "failed_count": MessageLog.objects.filter(
                ok=False, created_at__gte=timezone.now() - timedelta(days=7)
            ).count(),
        },
    )


# ======================= Finance =======================


@panel_view(feature="finance", office_wide=True, perm="books")
def finance(request):
    today = timezone.localdate()
    offset, start, end, label = _month(request)
    ledger = LedgerEntry.objects.filter(date__gte=start, date__lt=end)
    income = ledger.filter(kind=LedgerEntry.Kind.INCOME).aggregate(s=Sum("amount"))["s"] or 0
    expense = ledger.filter(kind=LedgerEntry.Kind.EXPENSE).aggregate(s=Sum("amount"))["s"] or 0
    month_policies = Policy.objects.filter(start_date__gte=start, start_date__lt=end).exclude(status="cancelled")
    expected = sum(p.commission_expected for p in month_policies)
    received = month_policies.aggregate(s=Sum("commission_received"))["s"] or 0
    pending = Installment.objects.filter(status=Installment.Status.PENDING).select_related("policy__customer")
    return render(
        request,
        "panel/finance.html",
        {
            "label": label,
            "offset": offset,
            "income": income,
            "expense": expense,
            "net": income - expense,
            "expected": expected,
            "received": received,
            "overdue": pending.filter(due_date__lt=today)[:10],
            "upcoming": pending.filter(due_date__gte=today, due_date__lte=today + timedelta(days=14))[:10],
            "overdue_total": pending.filter(due_date__lt=today).aggregate(s=Sum("amount"))["s"] or 0,
            "by_category": ledger.values("kind", "category").annotate(total=Sum("amount")).order_by("kind", "-total"),
            "categories": dict(LedgerEntry.Category.choices),
        },
    )


@panel_view(feature="finance", perm="finance")
def installments(request):
    qs = scoped(request, Installment.objects.select_related("policy__customer", "policy__line"), "policy__branch")
    today = timezone.localdate()
    flt = request.GET.get("f", "pending")
    if flt == "pending":
        qs = qs.filter(status=Installment.Status.PENDING)
    elif flt == "overdue":
        qs = qs.filter(status=Installment.Status.PENDING, due_date__lt=today)
    elif flt == "cheques":
        qs = qs.filter(method=Installment.Method.CHEQUE)
    elif flt == "bounced":
        qs = qs.filter(status=Installment.Status.BOUNCED)
    page = Paginator(qs.order_by("due_date"), 30).get_page(request.GET.get("page"))
    return render(request, "panel/installments.html", {"page": page, "f": flt, "today": today})


@panel_view(feature="finance", perm="finance")
def installment_plan(request):
    initial = {"first_due": timezone.localdate() + timedelta(days=30)}
    if request.GET.get("policy"):
        policy = scoped(request, Policy.objects.all()).filter(pk=request.GET["policy"]).first()
        if policy:
            initial.update(policy=policy.pk, total=policy.premium)
    form = InstallmentPlanForm(request.POST or None, initial=initial, policies=scoped(request, Policy.objects.all()))
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        base, rest = divmod(d["total"], d["count"])
        with transaction.atomic():
            for i in range(d["count"]):
                Installment.objects.create(
                    policy=d["policy"],
                    due_date=jalali.add_months(d["first_due"], i),
                    amount=base + (rest if i == d["count"] - 1 else 0),
                    method=d["method"],
                )
        messages.success(request, f"{d['count']} قسط ساخته شد. شماره و بانک چک‌ها را از فهرست اقساط کامل کنید.")
        return redirect(reverse("panel:installments") + "?f=pending")
    return render(request, "panel/form.html", {"form": form, "title": "تقسیط بیمه‌نامه", "back": "panel:installments"})


@panel_view(feature="finance", perm="finance")
def installment_edit(request, pk):
    obj = get_object_or_404(scoped(request, Installment.objects.all(), "policy__branch"), pk=pk)
    form = InstallmentForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        inst = form.save(commit=False)
        if inst.status == Installment.Status.PAID and not inst.paid_at:
            inst.paid_at = timezone.localdate()
        inst.save()
        if inst.status == Installment.Status.PAID:
            from apps.club.services import on_installment_paid

            on_installment_paid(inst)
        messages.success(request, "قسط ذخیره شد.")
        return redirect("panel:installments")
    return render(
        request,
        "panel/form.html",
        {"form": form, "title": f"قسط {obj.policy.customer.full_name}", "back": "panel:installments"},
    )


@panel_view(feature="finance", perm="finance")
@require_POST
def installment_paid(request, pk):
    inst = get_object_or_404(scoped(request, Installment.objects.all(), "policy__branch"), pk=pk)
    inst.status = Installment.Status.PAID
    inst.paid_at = timezone.localdate()
    inst.save(update_fields=["status", "paid_at"])
    from apps.club.services import on_installment_paid

    on_installment_paid(inst)
    messages.success(request, "قسط وصول شد.")
    return _next(request, "panel:installments")


@panel_view(feature="finance", office_wide=True, perm="books")
def commissions(request):
    rules = CommissionRule.objects.select_related("company", "line")
    form = CommissionRuleForm(request.POST or None, tenant=request.tenant)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "نرخ کارمزد ذخیره شد. برای بیمه‌نامه‌های جدید خودکار اعمال می‌شود.")
        return redirect("panel:commissions")
    offset, start, end, label = _month(request)
    policies = (
        Policy.objects.filter(start_date__gte=start, start_date__lt=end)
        .exclude(status="cancelled")
        .select_related("customer", "company", "line")
    )
    return render(
        request,
        "panel/commissions.html",
        {"rules": rules, "form": form, "policies": policies, "label": label, "offset": offset},
    )


@panel_view(feature="finance", office_wide=True, perm="books")
@require_POST
def commission_rule_delete(request, pk):
    get_object_or_404(CommissionRule, pk=pk).delete()
    messages.success(request, "نرخ حذف شد.")
    return redirect("panel:commissions")


@panel_view(feature="finance", office_wide=True, perm="books")
@require_POST
def commission_receive(request, pk):
    policy = get_object_or_404(Policy, pk=pk)
    form = CommissionReceiveForm(request.POST)
    if form.is_valid():
        amount = form.cleaned_data["amount"]
        with transaction.atomic():
            Policy.objects.filter(pk=policy.pk).update(commission_received=F("commission_received") + amount)
            LedgerEntry.objects.create(
                kind=LedgerEntry.Kind.INCOME,
                category=LedgerEntry.Category.COMMISSION,
                amount=amount,
                policy=policy,
                description=f"کارمزد {policy.line} {policy.number} — {policy.company}",
            )
        messages.success(request, "کارمزد ثبت و در دفتر درآمد نوشته شد.")
    else:
        messages.error(request, "مبلغ را درست وارد کنید.")
    return _next(request, "panel:commissions")


@panel_view(feature="finance", office_wide=True, perm="books")
def ledger(request):
    offset, start, end, label = _month(request)
    form = LedgerForm(request.POST or None, initial={"date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "ردیف ثبت شد.")
        return redirect("panel:ledger")
    entries = LedgerEntry.objects.filter(date__gte=start, date__lt=end)
    totals = {k: entries.filter(kind=k).aggregate(s=Sum("amount"))["s"] or 0 for k in LedgerEntry.Kind.values}
    return render(
        request,
        "panel/ledger.html",
        {
            "form": form,
            "entries": entries,
            "label": label,
            "offset": offset,
            "income": totals["income"],
            "expense": totals["expense"],
        },
    )


@panel_view(feature="finance", office_wide=True, perm="books")
@require_POST
def ledger_delete(request, pk):
    get_object_or_404(LedgerEntry, pk=pk).delete()
    messages.success(request, "ردیف حذف شد.")
    return redirect("panel:ledger")


# ======================= Claims =======================


@panel_view(feature="claims", perm="claims")
def claims(request):
    qs = scoped(
        request, Claim.objects.select_related("policy__customer", "policy__line", "policy__company"), "policy__branch"
    )
    status = request.GET.get("s", "open")
    if status == "open":
        qs = qs.exclude(status__in=[Claim.Status.PAID, Claim.Status.REJECTED])
    elif status in Claim.Status.values:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "panel/claims.html", {"page": page, "s": status, "statuses": Claim.Status.choices})


@panel_view(feature="claims", perm="claims")
def claim_new(request):
    initial = {"incident_date": timezone.localdate()}
    if request.GET.get("policy"):
        initial["policy"] = request.GET["policy"]
    form = ClaimForm(
        request.POST or None, initial=initial, tenant=request.tenant, policies=scoped(request, Policy.objects.all())
    )
    if request.method == "POST" and form.is_valid():
        claim = form.save()
        ClaimEvent.objects.create(claim=claim, status=claim.status, created_by=request.user)
        messages.success(request, f"پرونده خسارت {claim.code} ساخته شد.")
        return redirect("panel:claim", pk=claim.pk)
    return render(request, "panel/form.html", {"form": form, "title": "ثبت خسارت", "back": "panel:claims"})


@panel_view(feature="claims", perm="claims")
def claim_detail(request, pk):
    claim = get_object_or_404(
        scoped(request, Claim.objects.select_related("policy__customer", "policy__line"), "policy__branch"), pk=pk
    )
    status_form = ClaimStatusForm(initial={"status": claim.status, "amount_paid": claim.amount_paid or None})
    doc_form = ClaimDocumentForm()
    if request.method == "POST":
        if "status" in request.POST:
            status_form = ClaimStatusForm(request.POST)
            if status_form.is_valid():
                d = status_form.cleaned_data
                claim.status = d["status"]
                if d.get("amount_paid") is not None:
                    claim.amount_paid = d["amount_paid"]
                claim.save()
                ClaimEvent.objects.create(claim=claim, status=claim.status, note=d["note"], created_by=request.user)
                notify_claim(claim, d["note"])
                messages.success(
                    request, "وضعیت به‌روز شد" + (" و به مشتری پیامک شد." if tenant_can_sms(request.tenant) else ".")
                )
                return redirect("panel:claim", pk=claim.pk)
        else:
            doc_form = ClaimDocumentForm(request.POST, request.FILES)
            if doc_form.is_valid():
                f = doc_form.cleaned_data["file"]
                sub = request.subscription
                if sub and f.size > sub.storage_limit_bytes() - storage_used_bytes(request.tenant):
                    doc_form.add_error("file", "فضای محیط پر است. از بخش اشتراک فضا اضافه کنید.")
                else:
                    ClaimDocument.objects.create(claim=claim, title=doc_form.cleaned_data["title"], file=f)
                    messages.success(request, "مدرک بارگذاری شد.")
                    return redirect("panel:claim", pk=claim.pk)
    return render(
        request,
        "panel/claim_detail.html",
        {
            "claim": claim,
            "status_form": status_form,
            "doc_form": doc_form,
            "events": claim.events.select_related("created_by"),
            "documents": claim.documents.all(),
        },
    )


@panel_view(feature="claims", perm="claims")
def claim_edit(request, pk):
    claim = get_object_or_404(scoped(request, Claim.objects.all(), "policy__branch"), pk=pk)
    form = ClaimForm(
        request.POST or None, instance=claim, tenant=request.tenant, policies=scoped(request, Policy.objects.all())
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("panel:claim", pk=claim.pk)
    return render(
        request, "panel/form.html", {"form": form, "title": f"ویرایش خسارت {claim.code}", "back": "panel:claims"}
    )


# ======================= Marketers =======================


def _ref_url(request, marketer):
    return f"{request.tenant.site_url()}?ref={marketer.code}"


@panel_view(feature="marketers", office_wide=True, perm="marketers")
def marketers(request):
    rows = []
    for m in Marketer.objects.select_related("parent").annotate(n_customers=Count("customers", distinct=True)):
        earned = m.earned()
        paid = m.paid()
        rows.append({"m": m, "earned": earned, "paid": paid, "balance": earned - paid, "url": _ref_url(request, m)})
    return render(request, "panel/marketers.html", {"rows": rows})


@panel_view(feature="marketers", office_wide=True, perm="marketers")
def marketer_edit(request, pk=None):
    obj = get_object_or_404(Marketer, pk=pk) if pk else None
    form = MarketerForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "بازاریاب ذخیره شد.")
        return redirect("panel:marketers")
    return render(
        request,
        "panel/form.html",
        {"form": form, "back": "panel:marketers", "title": "ویرایش بازاریاب" if obj else "بازاریاب جدید"},
    )


@panel_view(feature="marketers", office_wide=True, perm="marketers")
def marketer_detail(request, pk):
    m = get_object_or_404(Marketer, pk=pk)
    form = PayoutForm(
        request.POST or None, initial={"date": timezone.localdate(), "amount": max(0, m.earned() - m.paid())}
    )
    if request.method == "POST" and form.is_valid():
        payout = form.save(commit=False)
        payout.marketer = m
        payout.save()
        LedgerEntry.objects.create(
            kind=LedgerEntry.Kind.EXPENSE,
            category=LedgerEntry.Category.MARKETER,
            amount=payout.amount,
            date=payout.date,
            description=f"تسویه با {m.full_name}",
        )
        messages.success(request, "تسویه ثبت شد و در دفتر هزینه نوشته شد.")
        return redirect("panel:marketer", pk=m.pk)
    policies = Policy.objects.filter(Q(marketer=m) | Q(marketer__parent=m)).select_related(
        "customer", "line", "marketer"
    )
    earned, paid = m.earned(), m.paid()
    return render(
        request,
        "panel/marketer_detail.html",
        {
            "m": m,
            "form": form,
            "policies": policies[:50],
            "payouts": m.payouts.all()[:20],
            "earned": earned,
            "paid": paid,
            "balance": earned - paid,
            "url": _ref_url(request, m),
            "children": m.children.all(),
        },
    )


# ======================= SMS campaigns =======================


@panel_view(feature="sms_campaigns", perm="campaigns")
def campaigns(request):
    from apps.crm.segments import BY_CODE

    seg = BY_CODE.get(request.GET.get("seg", ""))
    form = CampaignForm(request.POST or None, initial={"segment": seg.code, "title": seg.title} if seg else None)
    if request.method == "POST" and form.is_valid():
        campaign = form.save()
        return redirect("panel:campaign", pk=campaign.pk)
    return render(
        request,
        "panel/campaigns.html",
        {"form": form, "campaigns": Campaign.objects.all()[:30], "can_sms": tenant_can_sms(request.tenant)},
    )


@panel_view(feature="sms_campaigns", perm="campaigns")
def campaign_detail(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if request.method == "POST" and campaign.status == Campaign.Status.DRAFT:
        if not tenant_can_sms(request.tenant):
            messages.error(request, "اول پنل پیامک دفتر را از «اتصالات» وصل کنید.")
        else:
            from apps.messaging.tasks import run_campaign_task

            run_campaign_task.delay(campaign.pk)
            messages.success(request, "ارسال شروع شد. نتیجه چند دقیقه دیگر همین‌جا دیده می‌شود.")
        return redirect("panel:campaign", pk=campaign.pk)
    recipients = campaign_recipients(campaign)
    return render(
        request,
        "panel/campaign_detail.html",
        {
            "campaign": campaign,
            "segment": __import__("apps.crm.segments", fromlist=["BY_CODE"]).BY_CODE.get(campaign.segment),
            "count": recipients.count(),
            "sample": recipients[:8],
            "can_sms": tenant_can_sms(request.tenant),
        },
    )


# ======================= Advanced reports =======================


@panel_view(feature="advanced_reports", office_wide=True, perm="reports")
def reports(request):
    today = timezone.localdate()
    policies = scoped(request, Policy.objects.all())
    months = []
    for off in range(-11, 1):
        start, end, label = jalali.month_bounds(today, off)
        qs = policies.filter(start_date__gte=start, start_date__lt=end).exclude(status="cancelled")
        agg = qs.aggregate(premium=Sum("premium"), n=Count("id"))
        months.append({"label": label, "premium": agg["premium"] or 0, "n": agg["n"]})
    peak = max((m["premium"] for m in months), default=0) or 1
    year_start = jalali.month_bounds(today, -11)[0]
    year_qs = policies.filter(start_date__gte=year_start).exclude(status="cancelled")
    by_company = year_qs.values("company__name").annotate(premium=Sum("premium"), n=Count("id")).order_by("-premium")
    by_line = year_qs.values("line__name").annotate(premium=Sum("premium"), n=Count("id")).order_by("-premium")
    ended = policies.filter(end_date__gte=today - timedelta(days=365), end_date__lt=today).exclude(status="cancelled")
    ended_n = ended.count()
    renewed_n = ended.filter(renewals__isnull=False).distinct().count()
    from apps.crm.models import QuoteRequest

    quotes = scoped(request, QuoteRequest.objects.filter(created_at__date__gte=year_start))
    by_branch = None
    if "branches" in request.features:
        by_branch = year_qs.values("branch__name").annotate(premium=Sum("premium"), n=Count("id")).order_by("-premium")
    return render(
        request,
        "panel/reports.html",
        {
            "months": months,
            "peak": peak,
            "by_company": by_company,
            "by_line": by_line,
            "ended_n": ended_n,
            "renewed_n": renewed_n,
            "renewal_rate": round(100 * renewed_n / ended_n) if ended_n else None,
            "quotes_n": quotes.count(),
            "quotes_issued": quotes.filter(status="issued").count(),
            "year_total": sum(m["premium"] for m in months),
            "by_branch": by_branch,
            **branch_filter(request),
        },
    )


@panel_view(feature="advanced_reports", office_wide=True, perm="reports")
def reports_export(request):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="policies-{request.tenant.slug}.csv"'
    resp.write("﻿")
    w = csv.writer(resp)
    w.writerow(
        [
            "بیمه‌گذار",
            "موبایل",
            "رشته",
            "شرکت",
            "شماره",
            "شروع",
            "پایان",
            "حق بیمه",
            "کارمزد انتظار",
            "کارمزد دریافتی",
            "بازاریاب",
            "شعبه",
            "وضعیت",
        ]
    )
    qs = scoped(request, Policy.objects.select_related("customer", "line", "company", "marketer", "branch")).order_by(
        "start_date"
    )
    for p in qs.iterator():
        w.writerow(
            [
                _csv_cell(v)
                for v in (
                    p.customer.full_name,
                    p.customer.mobile,
                    p.line.name,
                    p.company.name,
                    p.number,
                    p.start_date.isoformat(),
                    p.end_date.isoformat(),
                    p.premium,
                    p.commission_expected,
                    p.commission_received,
                    p.marketer.full_name if p.marketer else "",
                    p.branch.name if p.branch else "",
                    p.get_status_display(),
                )
            ]
        )
    return resp
