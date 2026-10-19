import csv
import io
import logging
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Membership, normalize_mobile
from apps.billing.models import Addon, Invoice, Package, Period, StorageTier, Subscription, SubscriptionItem
from apps.claims.models import Claim
from apps.core import jalali
from apps.core.dns import check_domain
from apps.core.models import Domain, PlatformSettings
from apps.crm.models import Branch, Customer, Policy, QuoteRequest
from apps.finance.models import Installment
from apps.integrations.models import KIND_LABELS, PROVIDERS, Integration
from apps.integrations.senders import test_connection
from apps.sites import registry
from apps.sites.models import FAQ, SiteLineContent, SiteSettings, Testimonial
from apps.sites.readiness import publication_issues
from apps.tickets.models import Ticket, TicketMessage

from .access import MANAGERS, branch_filter, panel_view, scoped, storage_used_bytes
from .forms import (
    BranchForm,
    CustomerForm,
    DomainForm,
    DomainServiceForm,
    FAQFormSet,
    ImportForm,
    MemberBranchForm,
    MemberForm,
    PolicyForm,
    QuoteUpdateForm,
    RenewalOrderForm,
    ReplyForm,
    SiteContentForm,
    SiteLineContentForm,
    TestimonialFormSet,
    TicketForm,
)
from .views_work import customer_work_context

User = get_user_model()
logger = logging.getLogger(__name__)


def _queue_custom_domain_route_sync():
    from apps.core.tasks import sync_custom_domain_routes

    try:
        sync_custom_domain_routes.delay()
    except Exception:
        # The periodic reconciliation retries if Redis is temporarily unavailable.
        logger.exception("Unable to queue BimCRM custom-domain route synchronization")


def _site(request) -> SiteSettings:
    site, _ = SiteSettings.objects.get_or_create(tenant=request.tenant, defaults={"hero_title": request.tenant.name})
    return site


# ---------------- Dashboard ----------------


def _trial_nudge(request):
    """In the last days of the free trial: how many days are left and which package fits this office."""
    sub = request.subscription
    if not sub or sub.status != Subscription.Status.TRIAL or sub.days_left > 5:
        return None
    if request.membership.role not in MANAGERS or getattr(request, "live_demo", False):
        return None
    from apps.billing import pricing

    return {"days": sub.days_left, **(pricing.suggested_plan(request.tenant) or {})}


@panel_view()
def dashboard(request):
    today = timezone.localdate()
    policies = scoped(request, Policy.objects.all())
    customers_qs = scoped(request, Customer.objects.all())
    quotes_qs = scoped(request, QuoteRequest.objects.all(), include_unassigned=True)
    renewals = (
        policies.filter(status=Policy.Status.ACTIVE, end_date__gte=today, end_date__lte=today + timedelta(days=30))
        .select_related("customer", "line", "company")
        .order_by("end_date")[:12]
    )
    site = _site(request)
    checklist = [
        ("اطلاعات سایت را کامل کنید", bool(site.about and site.phone), "panel:site"),
        ("رشته‌های قابل استعلام را انتخاب کنید", site.lines.exists(), "panel:site"),
        ("مشتریان قبلی را وارد کنید", Customer.objects.exists(), "panel:customer_import"),
        (
            "پنل پیامک خودتان را وصل کنید",
            Integration.objects.filter(kind="sms", enabled=True).exists(),
            "panel:integrations",
        ),
        ("سایت را منتشر کنید", site.is_published, "panel:site"),
    ]
    month_start, month_end, _ = jalali.month_bounds(today)
    live = policies.exclude(status=Policy.Status.CANCELLED)

    # Premium written per Jalali month, last six months (oldest first) for the trend chart.
    trend = []
    for offset in range(-5, 1):
        start, end, label = jalali.month_bounds(today, offset)
        agg = live.filter(start_date__gte=start, start_date__lt=end).aggregate(s=Sum("premium"), n=Count("id"))
        trend.append({"label": label.split(" ")[0], "full": label, "value": agg["s"] or 0, "count": agg["n"]})
    peak = max((t["value"] for t in trend), default=0)
    for t in trend:
        t["pct"] = round(t["value"] * 100 / peak) if peak else 0
    month_premium, prev_premium = trend[-1]["value"], trend[-2]["value"]
    delta = round((month_premium - prev_premium) * 100 / prev_premium) if prev_premium else None

    upcoming = policies.filter(
        status=Policy.Status.ACTIVE, end_date__gte=today, end_date__lte=today + timedelta(days=30)
    )
    status_labels = dict(QuoteRequest.Status.choices)
    open_statuses = ["new", "contacted", "waiting_docs"]
    open_counts = {
        row["status"]: row["n"]
        for row in quotes_qs.filter(status__in=open_statuses).values("status").annotate(n=Count("id"))
    }
    pipeline = [{"key": k, "label": status_labels.get(k, k), "n": open_counts.get(k, 0)} for k in open_statuses]

    alerts = []
    if "finance" in request.features:
        overdue = scoped(request, Installment.objects.all(), "policy__branch").filter(
            status=Installment.Status.PENDING, due_date__lt=today
        )
        n = overdue.count()
        if n:
            total = overdue.aggregate(s=Sum("amount"))["s"] or 0
            alerts.append((f"{n} قسط معوق به مبلغ {total:,} تومان", "panel:installments", "?f=overdue"))
    if "claims" in request.features:
        n = (
            scoped(request, Claim.objects.all(), "policy__branch")
            .filter(status=Claim.Status.REPORTED, reported_by_customer=True)
            .count()
        )
        if n:
            alerts.append((f"{n} خسارت تازه از پنل مشتری", "panel:claims", "?s=reported"))
    platform = PlatformSettings.load()
    if platform.free_domain_active and not Domain.objects.filter(tenant=request.tenant).exists():
        from apps.core.templatetags.fa import jdate

        until = jdate(platform.free_domain_until, "long")
        alerts.append((f"طرح ویژه: تا {until} دامنه ir و راه‌اندازی آن رایگان است؛ درخواست بدهید", "panel:domains", ""))
    from apps.work.models import Task

    my_tasks = (
        Task.objects.filter(done_at__isnull=True, due_date__lte=today)
        .filter(Q(assigned_to=request.user) | Q(assigned_to__isnull=True))
        .select_related("customer")
        .order_by("due_date", "-priority")[:6]
    )
    name = (request.user.full_name or "").split(" ")[0]
    return render(
        request,
        "panel/dashboard.html",
        {
            "renewals": renewals,
            "my_tasks": my_tasks,
            "new_quotes": quotes_qs.filter(status=QuoteRequest.Status.NEW).select_related("line")[:6],
            "stats": {
                "customers": customers_qs.count(),
                "active_policies": policies.filter(status=Policy.Status.ACTIVE, end_date__gte=today).count(),
                "month_premium": month_premium,
                "prev_premium": prev_premium,
                "premium_delta": delta,
                "open_quotes": sum(p["n"] for p in pipeline),
                "new_quotes": open_counts.get("new", 0),
                "renewals_30": upcoming.count(),
                "renewals_7": upcoming.filter(end_date__lte=today + timedelta(days=7)).count(),
            },
            "trend": trend,
            "trend_peak": peak,
            "pipeline": pipeline,
            "checklist": checklist,
            "trial_nudge": _trial_nudge(request),
            "alerts": alerts,
            "checklist_done": sum(1 for c in checklist if c[1]),
            "welcome": request.GET.get("welcome"),
            "site": site,
            "today": today,
            "greeting_name": name,
        },
    )


# ---------------- Customers ----------------


@panel_view()
def customers(request):
    qs = scoped(request, Customer.objects.annotate(n_policies=Count("policies"))).order_by("-created_at")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q) | Q(mobile__contains=normalize_mobile(q) or q) | Q(national_code__contains=q)
        )
    from apps.crm.segments import BY_CODE, SEGMENTS, customers_in

    seg = BY_CODE.get(request.GET.get("seg", ""))
    if seg:
        qs = customers_in(seg.code, qs)
    tier = request.GET.get("tier", "")
    if tier in ("bronze", "silver", "gold"):
        qs = qs.filter(tier=tier)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "panel/customers.html",
        {"page": page, "q": q, "seg": seg, "segments": SEGMENTS, "tier": tier, **branch_filter(request)},
    )


@panel_view()
def customer_edit(request, pk=None):
    obj = get_object_or_404(scoped(request, Customer.objects.all()), pk=pk) if pk else None
    form = CustomerForm(
        request.POST or None, instance=obj, features=request.features, branch_scope=request.branch_scope
    )
    if request.method == "POST" and form.is_valid():
        customer = form.save(commit=False)
        if request.branch_scope is not None:
            customer.branch = request.branch_scope
        customer.save()
        messages.success(request, "مشتری ذخیره شد.")
        return redirect("panel:customer", pk=customer.pk)
    return render(
        request,
        "panel/form.html",
        {"form": form, "title": "ویرایش مشتری" if obj else "مشتری جدید", "back": "panel:customers"},
    )


@panel_view()
def customer_detail(request, pk):
    customer = get_object_or_404(scoped(request, Customer.objects.all()), pk=pk)
    return render(
        request,
        "panel/customer_detail.html",
        {
            "customer": customer,
            "policies": customer.policies.select_related("line", "company").order_by("-end_date"),
            "quotes": QuoteRequest.objects.filter(mobile=customer.mobile).select_related("line"),
            "installments": Installment.objects.filter(policy__customer=customer).select_related("policy__line")
            if "finance" in request.features
            else None,
            "claims": Claim.objects.filter(policy__customer=customer).select_related("policy__line")
            if "claims" in request.features
            else None,
            **customer_work_context(request, customer),
        },
    )


@panel_view()
def customer_import(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        raw = form.cleaned_data["file"].read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1256", errors="replace")
        created = skipped = 0
        reader = csv.reader(io.StringIO(text))
        next(reader, None)
        for row in reader:
            if len(row) < 2:
                skipped += 1
                continue
            mobile = normalize_mobile(row[1])
            if len(mobile) != 11 or not mobile.startswith("09") or Customer.objects.filter(mobile=mobile).exists():
                skipped += 1
                continue
            Customer.objects.create(
                full_name=row[0].strip()[:120] or mobile,
                mobile=mobile,
                national_code=(row[2].strip() if len(row) > 2 else "")[:10],
                city=(row[3].strip() if len(row) > 3 else "")[:60],
                source=Customer.Source.IMPORT,
            )
            created += 1
        messages.success(request, f"{created} مشتری اضافه شد؛ {skipped} ردیف تکراری یا نامعتبر رد شد.")
        return redirect("panel:customers")
    return render(
        request,
        "panel/form.html",
        {"form": form, "title": "ورود مشتریان از اکسل", "back": "panel:customers", "multipart": True},
    )


# ---------------- Policies ----------------


@panel_view()
def policies(request):
    qs = scoped(request, Policy.objects.select_related("customer", "line", "company"))
    today = timezone.localdate()
    flt = request.GET.get("f", "")
    if flt == "expiring":
        qs = qs.filter(status=Policy.Status.ACTIVE, end_date__gte=today, end_date__lte=today + timedelta(days=30))
    elif flt == "expired":
        qs = qs.filter(end_date__lt=today, renewals__isnull=True)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(customer__full_name__icontains=q) | Q(subject__icontains=q))
    page = Paginator(qs.order_by("end_date"), 25).get_page(request.GET.get("page"))
    return render(
        request,
        "panel/policies.html",
        {"page": page, "f": flt, "q": q, "today": today, **branch_filter(request)},
    )


def _storage_left(request) -> int | None:
    sub = request.subscription
    if not sub:
        return None
    return max(0, sub.storage_limit_bytes() - storage_used_bytes(request.tenant))


@panel_view()
def policy_edit(request, pk=None):
    obj = get_object_or_404(scoped(request, Policy.objects.all()), pk=pk) if pk else None
    initial = {}
    renew_from = None
    if not obj and request.GET.get("renew"):
        renew_from = get_object_or_404(scoped(request, Policy.objects.all()), pk=request.GET["renew"])
        initial = {
            "customer": renew_from.customer_id,
            "line": renew_from.line_id,
            "company": renew_from.company_id,
            "subject": renew_from.subject,
            "start_date": renew_from.end_date,
            "end_date": renew_from.end_date + timedelta(days=365),
            "branch": renew_from.branch_id,
        }
    elif not obj and request.GET.get("customer"):
        initial = {"customer": request.GET["customer"]}
    form = PolicyForm(
        request.POST or None,
        request.FILES or None,
        instance=obj,
        initial=initial,
        storage_left=_storage_left(request),
        features=request.features,
        branch_scope=request.branch_scope,
    )
    if request.method == "POST" and form.is_valid():
        policy = form.save(commit=False)
        if request.branch_scope is not None:
            policy.branch = request.branch_scope
        if renew_from:
            policy.renewed_from = renew_from
        if not obj:
            policy.created_by = request.user
        policy.save()
        messages.success(request, "بیمه‌نامه ذخیره شد.")
        return redirect("panel:customer", pk=policy.customer_id)
    return render(
        request,
        "panel/form.html",
        {
            "form": form,
            "multipart": True,
            "back": "panel:policies",
            "title": "ویرایش بیمه‌نامه" if obj else ("تمدید بیمه‌نامه" if renew_from else "بیمه‌نامه جدید"),
        },
    )


# ---------------- Quote requests ----------------


@panel_view()
def quotes(request):
    qs = scoped(request, QuoteRequest.objects.select_related("line", "assigned_to", "branch"), include_unassigned=True)
    status = request.GET.get("s", "")
    if status in QuoteRequest.Status.values:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "panel/quotes.html",
        {"page": page, "s": status, "statuses": QuoteRequest.Status.choices, **branch_filter(request)},
    )


@panel_view()
def quote_detail(request, pk):
    quote = get_object_or_404(
        scoped(request, QuoteRequest.objects.select_related("line", "branch"), include_unassigned=True), pk=pk
    )
    form = QuoteUpdateForm(
        request.POST or None,
        instance=quote,
        tenant=request.tenant,
        features=request.features,
        branch_scope=request.branch_scope,
    )
    if request.method == "POST":
        if "make_customer" in request.POST:
            customer, created = Customer.objects.get_or_create(
                mobile=quote.mobile,
                defaults={
                    "full_name": quote.full_name,
                    "source": Customer.Source.REFERRAL if quote.referrer_id else Customer.Source.WEBSITE,
                    "marketer": quote.marketer,
                    "branch": quote.branch or request.branch_scope,
                    "referred_by": quote.referrer,
                },
            )
            quote.customer = customer
            quote.save(update_fields=["customer"])
            messages.success(request, "مشتری ساخته شد." if created else "به مشتری موجود وصل شد.")
            return redirect("panel:quote", pk=quote.pk)
        if form.is_valid():
            quote = form.save(commit=False)
            if quote.status != QuoteRequest.Status.NEW and quote.first_contact_at is None:
                quote.first_contact_at = timezone.now()
                from apps.work.models import Task

                # The automatic "call this lead" task is done once someone followed the request up.
                Task.objects.filter(auto_key=f"quote:{quote.pk}", done_at__isnull=True).update(
                    done_at=timezone.now(), done_by=request.user
                )
            if request.branch_scope is not None and quote.branch_id is None:
                quote.branch = request.branch_scope  # staff who pick up an unrouted lead take it into their branch
            quote.save()
            messages.success(request, "درخواست به‌روز شد.")
            return redirect("panel:quotes")
    from apps.crm.documents import checklist

    from .views_docs import DocumentForm

    return render(
        request,
        "panel/quote_detail.html",
        {
            "quote": quote,
            "form": form,
            "doc_checklist": checklist(quote.customer, [quote.line]),
            "doc_form": DocumentForm(customer=quote.customer) if quote.customer else None,
        },
    )


# ---------------- Website ----------------


@panel_view(perm="site")
def site_settings(request):
    site = _site(request)
    form = SiteContentForm(request.POST or None, request.FILES or None, instance=site, prefix="s")
    tforms = TestimonialFormSet(request.POST or None, queryset=Testimonial.objects.all(), prefix="t")
    fforms = FAQFormSet(request.POST or None, queryset=FAQ.objects.all(), prefix="q")
    line_forms = []
    for line in site.lines.filter(is_active=True):
        content = SiteLineContent.objects.filter(line=line).first()
        if content is None:
            content = SiteLineContent(tenant=request.tenant, line=line)
        line_forms.append((line, SiteLineContentForm(request.POST or None, instance=content, prefix=f"line{line.pk}")))
    all_valid = (
        form.is_valid()
        and tforms.is_valid()
        and fforms.is_valid()
        and all(line_form.is_valid() for _, line_form in line_forms)
    )
    if request.method == "POST" and all_valid:
        form.save()
        for line, line_form in line_forms:
            content = line_form.save(commit=False)
            content.tenant = request.tenant
            content.line = line
            content.save()
        for fs in (tforms, fforms):
            for obj in fs.save(commit=False):
                obj.save()
            for obj in fs.deleted_objects:
                obj.delete()
        issues = publication_issues(site)
        if site.is_published and issues:
            site.is_published = False
            site.save(update_fields=["is_published", "updated_at"])
            messages.warning(
                request, "سایت از دسترس عمومی خارج شد؛ برای انتشار دوباره این موارد را کامل کنید: " + " ".join(issues)
            )
        else:
            messages.success(request, "محتوای سایت ذخیره شد.")
        return redirect("panel:site")
    return render(
        request,
        "panel/site.html",
        {
            "form": form,
            "tforms": tforms,
            "fforms": fforms,
            "line_forms": line_forms,
            "site": site,
            "publication_issues": publication_issues(site),
        },
    )


@panel_view(perm="site")
def site_template(request):
    site = _site(request)
    if request.method == "POST":
        key = request.POST.get("template")
        if key in registry.BY_KEY:
            site.template = key
            site.save(update_fields=["template", "updated_at"])
            messages.success(request, f"قالب «{registry.get(key).name}» فعال شد. محتوای سایت دست نخورد.")
        return redirect("panel:site_template")
    return render(request, "panel/site_template.html", {"site": site, "templates": registry.TEMPLATES})


@panel_view(perm="site")
@require_POST
def site_publish(request):
    site = _site(request)
    site.is_published = request.POST.get("publish") == "1"
    issues = publication_issues(site) if site.is_published else []
    if issues:
        site.is_published = False
        messages.error(request, "انتشار سایت نیاز به تکمیل دارد: " + " ".join(issues))
        return redirect("panel:site")
    site.save(update_fields=["is_published", "updated_at"])
    messages.success(request, "سایت منتشر شد." if site.is_published else "سایت از دسترس عموم خارج شد.")
    return redirect("panel:site")


# ---------------- Domains ----------------


@panel_view(managers_only=True)
def domains(request):
    sub = request.subscription
    domains_qs = Domain.objects.filter(tenant=request.tenant)
    limit = sub.domain_limit() if sub else 1
    form = DomainForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if domains_qs.count() >= limit:
            messages.error(request, "سقف دامنه‌های اشتراک پر است. دامنه اضافه را از بخش اشتراک بخرید.")
        else:
            domain = Domain.objects.create(
                tenant=request.tenant,
                hostname=form.cleaned_data["hostname"],
                is_primary=not domains_qs.filter(is_primary=True).exists(),
            )
            messages.success(request, f"{domain.hostname} اضافه شد. حالا NSهای آن را تنظیم کنید.")
        return redirect("panel:domains")
    platform = PlatformSettings.load()
    return render(
        request,
        "panel/domains.html",
        {
            "form": form,
            "domains": domains_qs,
            "limit": limit,
            "nameservers": platform.get_nameservers(),
            "platform": platform,
            "service_form": DomainServiceForm(initial={"contact_mobile": request.user.mobile}),
            "service_ticket": Ticket.objects.filter(
                category=Ticket.Category.DOMAIN, subject__startswith="درخواست خرید دامنه"
            )
            .exclude(status=Ticket.Status.CLOSED)
            .first(),
        },
    )


@panel_view(managers_only=True)
@require_POST
def domain_service(request):
    """ "Buy and set up my domain for me": opens a domain ticket and tells the platform owner by SMS."""
    from django.conf import settings as dj_settings

    from apps.accounts.sms import send_platform_text

    form = DomainServiceForm(request.POST)
    if not form.is_valid():
        messages.error(request, "شماره موبایل درست را وارد کنید.")
        return redirect("panel:domains")
    wanted = form.cleaned_data["wanted"].strip()
    ticket = Ticket.objects.create(
        subject=f"درخواست خرید دامنه{' (طرح رایگان)' if PlatformSettings.load().free_domain_active else ''}"
        f"{': ' + wanted if wanted else ''}"[:160],
        category=Ticket.Category.DOMAIN,
        created_by=request.user,
    )
    body = (
        "لطفاً دامنه اختصاصی را برای دفتر ما ثبت و به سایت وصل کنید.\n"
        f"دامنه‌های پیشنهادی: {wanted or 'هنوز انتخاب نشده'}\n"
        f"موبایل تماس: {form.cleaned_data['contact_mobile']}"
    )
    if form.cleaned_data["note"]:
        body += f"\nتوضیح: {form.cleaned_data['note']}"
    TicketMessage.objects.create(ticket=ticket, author=request.user, body=body)
    if dj_settings.SUPERADMIN_MOBILE:
        send_platform_text(
            dj_settings.SUPERADMIN_MOBILE,
            f"درخواست خرید دامنه: {request.tenant.name}، {wanted or 'بدون نام پیشنهادی'}، "
            f"تماس {form.cleaned_data['contact_mobile']}",
        )
    messages.success(request, "درخواست ثبت شد. برای انتخاب و ثبت دامنه با شما تماس می‌گیریم.")
    return redirect("panel:ticket", pk=ticket.pk)


@panel_view(managers_only=True)
@require_POST
def domain_action(request, pk):
    domain = get_object_or_404(Domain, pk=pk, tenant=request.tenant)
    action = request.POST.get("action")
    if action == "check":
        ok = check_domain(domain)
        _queue_custom_domain_route_sync()
        if ok:
            messages.success(request, f"{domain.hostname} فعال شد. گواهی SSL ظرف چند دقیقه صادر می‌شود.")
        else:
            seen = domain.last_seen_ns or "هیچ NSی پیدا نشد"
            messages.warning(
                request, f"هنوز NSهای ما دیده نمی‌شود (فعلی: {seen}). تغییر NS در ir ممکن است چند ساعت طول بکشد."
            )
    elif action == "primary":
        Domain.objects.filter(tenant=request.tenant).update(is_primary=False)
        domain.is_primary = True
        domain.save(update_fields=["is_primary"])
        messages.success(request, f"{domain.hostname} دامنه اصلی سایت شد.")
    elif action == "delete":
        domain.delete()
        _queue_custom_domain_route_sync()
        messages.success(request, "دامنه حذف شد.")
    return redirect("panel:domains")


# ---------------- Integrations ----------------


def _integration_form(kind, provider, data=None, initial=None):
    fields = {"enabled": forms.BooleanField(label="فعال", required=False, initial=True)}
    for name, label, required in PROVIDERS[kind][provider]["fields"]:
        widget = (
            forms.Textarea(attrs={"rows": 4, "dir": "ltr"})
            if name in ("code", "badge_html")
            else forms.TextInput(attrs={"dir": "ltr", "autocomplete": "off"})
        )
        fields[name] = forms.CharField(label=label, required=required, widget=widget)
    form_class = type("IntegrationForm", (forms.Form,), fields)
    return form_class(data, initial=initial)


@panel_view(managers_only=True)
def integrations(request):
    existing = {(i.kind, i.provider): i for i in Integration.objects.all()}
    groups = [
        {
            "kind": kind,
            "label": KIND_LABELS[kind],
            "providers": [
                {"key": p, "label": meta["label"], "obj": existing.get((kind, p))}
                for p, meta in PROVIDERS[kind].items()
            ],
        }
        for kind in PROVIDERS
    ]
    sms_connected = any(i.enabled for (k, _), i in existing.items() if k == "sms")
    return render(request, "panel/integrations.html", {"groups": groups, "sms_connected": sms_connected})


@panel_view(managers_only=True)
def integration_edit(request, kind, provider):
    if kind not in PROVIDERS or provider not in PROVIDERS[kind]:
        return redirect("panel:integrations")
    obj = Integration.objects.filter(kind=kind, provider=provider).first()
    initial = {**(obj.config if obj else {}), "enabled": obj.enabled if obj else True}
    form = _integration_form(kind, provider, request.POST or None, initial=initial)
    if request.method == "POST":
        if "delete" in request.POST and obj:
            obj.delete()
            messages.success(request, "اتصال حذف شد.")
            return redirect("panel:integrations")
        if form.is_valid():
            obj = obj or Integration(kind=kind, provider=provider)
            obj.enabled = form.cleaned_data.pop("enabled")
            obj.config = {k: v.strip() for k, v in form.cleaned_data.items()}
            obj.save()
            if obj.enabled and kind in ("payment", "sms"):
                Integration.objects.filter(kind=kind).exclude(pk=obj.pk).update(enabled=False)
            ok, msg = test_connection(obj)
            (messages.success if ok else messages.warning)(request, msg)
            return redirect("panel:integrations")
    return render(
        request,
        "panel/form.html",
        {
            "form": form,
            "back": "panel:integrations",
            "danger_delete": bool(obj),
            "title": f"{KIND_LABELS[kind]}: {PROVIDERS[kind][provider]['label']}",
            "note": "این اطلاعات رمزنگاری‌شده ذخیره می‌شود. قرارداد و هزینه این سرویس با خود شماست.",
            "signup_url": PlatformSettings.load().smsir_signup_url if provider == "smsir" else "",
        },
    )


# ---------------- Team ----------------


@panel_view(managers_only=True)
def team(request):
    members = Membership.objects.filter(tenant=request.tenant).select_related("user", "branch")
    sub = request.subscription
    limit = sub.user_limit() if sub else 1
    if request.method == "POST" and "set_perms" in request.POST:
        from apps.accounts.models import STAFF_PERMS

        m = get_object_or_404(members, pk=request.POST["set_perms"], role=Membership.Role.STAFF)
        m.perms = {code: code in request.POST.getlist("perm") for code, _, _ in STAFF_PERMS}
        m.save(update_fields=["perms"])
        messages.success(request, f"دسترسی‌های {m.user} ذخیره شد.")
        return redirect("panel:team")
    if request.method == "POST" and "set_branch" in request.POST:
        m = get_object_or_404(members, pk=request.POST["set_branch"])
        bf = MemberBranchForm(request.POST)
        if "branches" in request.features and bf.is_valid():
            m.branch = bf.cleaned_data["branch"]
            m.save(update_fields=["branch"])
            messages.success(request, f"شعبه {m.user} به‌روز شد.")
        return redirect("panel:team")
    form = MemberForm(request.POST or None, features=request.features)
    if request.method == "POST" and form.is_valid():
        if members.filter(is_active=True).count() >= limit:
            messages.error(request, "سقف کاربران پر است. از بخش اشتراک «کاربر اضافه» بخرید.")
        else:
            user, _ = User.objects.get_or_create(
                mobile=form.cleaned_data["mobile"], defaults={"full_name": form.cleaned_data["full_name"]}
            )
            branch = form.cleaned_data.get("branch")
            m, created = Membership.objects.get_or_create(
                user=user, tenant=request.tenant, defaults={"role": form.cleaned_data["role"], "branch": branch}
            )
            if not created:
                m.is_active = True
                m.role = form.cleaned_data["role"]
                m.branch = branch
                m.save()
            messages.success(request, f"{user} اضافه شد؛ با همین موبایل از bimcrm.ir وارد می‌شود.")
        return redirect("panel:team")
    branches = Branch.objects.filter(is_active=True) if "branches" in request.features else None
    from apps.accounts.models import STAFF_PERMS

    return render(
        request,
        "panel/team.html",
        {"members": members, "form": form, "limit": limit, "branches": branches, "staff_perms": STAFF_PERMS},
    )


# ---------------- Branches (add-on) ----------------


@panel_view(feature="branches", managers_only=True)
def branches(request):
    rows = Branch.objects.annotate(
        n_customers=Count("customers", distinct=True),
        n_staff=Count("membership", filter=Q(membership__is_active=True), distinct=True),
    ).order_by("order", "name")
    return render(request, "panel/branches.html", {"rows": rows})


@panel_view(feature="branches", managers_only=True)
def branch_edit(request, pk=None):
    obj = get_object_or_404(Branch, pk=pk) if pk else None
    form = BranchForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "شعبه ذخیره شد.")
        return redirect("panel:branches")
    return render(
        request,
        "panel/form.html",
        {"form": form, "title": f"ویرایش {obj.name}" if obj else "شعبه جدید", "back": "panel:branches"},
    )


@panel_view(managers_only=True)
@require_POST
def team_remove(request, pk):
    m = get_object_or_404(Membership, pk=pk, tenant=request.tenant)
    if m.role == Membership.Role.OWNER:
        messages.error(request, "مالک دفتر حذف نمی‌شود.")
    else:
        m.is_active = False
        m.save(update_fields=["is_active"])
        messages.success(request, "دسترسی همکار برداشته شد.")
    return redirect("panel:team")


# ---------------- Subscription ----------------


@require_POST
@panel_view(write_ok_when_expired=True)
def billing_pay(request):
    """Same-origin payment start (posting from the subdomain to bimcrm.ir is blocked by browsers' Origin: null)."""
    from apps.main.views import start_subscription_payment

    if request.membership.role not in MANAGERS or not request.subscription:
        return redirect("panel:billing")
    if PlatformSettings.load().payment_mode != PlatformSettings.PaymentMode.ONLINE:
        return redirect("panel:billing")
    return start_subscription_payment(request, request.tenant)


@require_POST
@panel_view(write_ok_when_expired=True)
def billing_order(request):
    """Renewal by order: itemised pre-invoice, a billing ticket, and a call from the platform to arrange payment."""
    from apps.billing import orders

    sub = request.subscription
    if request.membership.role not in MANAGERS or not sub:
        return redirect("panel:billing")
    existing = orders.open_order(request.tenant)
    if existing:
        messages.info(request, f"سفارش {existing.number} هنوز باز است؛ همان را پیگیری می‌کنیم.")
        return redirect("panel:billing_order_detail", pk=existing.pk)
    form = RenewalOrderForm(request.POST, initial_mobile=request.user.mobile)
    if not form.is_valid():
        messages.error(request, "دوره و شماره موبایل درست را وارد کنید.")
        return redirect("panel:billing")
    invoice = orders.place_order(
        tenant=request.tenant,
        user=request.user,
        period=form.cleaned_data["period"],
        contact_mobile=form.cleaned_data["contact_mobile"],
        contact_time=form.cleaned_data["contact_time"],
        note=form.cleaned_data["note"],
    )
    return redirect("panel:billing_order_detail", pk=invoice.pk)


@panel_view(write_ok_when_expired=True)
def billing_order_detail(request, pk):
    from apps.billing import orders

    invoice = get_object_or_404(Invoice, pk=pk, tenant=request.tenant)
    if request.method == "POST" and request.POST.get("cancel") and request.membership.role in MANAGERS:
        orders.cancel_order(invoice, request.user, staff=False)
        messages.success(request, f"سفارش {invoice.number} لغو شد.")
        return redirect("panel:billing")
    steps = [
        ("ثبت سفارش", invoice.created_at, True),
        ("تماس کارشناس حساب", invoice.contacted_at, bool(invoice.contacted_at)),
        ("پرداخت و فعال‌سازی", invoice.paid_at, invoice.status == Invoice.Status.PAID),
    ]
    return render(
        request,
        "panel/billing_order.html",
        {
            "invoice": invoice,
            "steps": steps,
            "platform": PlatformSettings.load(),
            "can_manage": request.membership.role in MANAGERS,
        },
    )


@panel_view(write_ok_when_expired=True)
def billing(request):
    sub = request.subscription
    if request.method == "POST" and request.membership.role in MANAGERS and sub:
        if request.POST.get("change_plan"):
            return _change_plan(request, sub)
        return _save_extras(request, sub)
    items = {i.addon.code: i.quantity for i in sub.items.select_related("addon")} if sub else {}
    platform = PlatformSettings.load()
    from apps.billing import pricing
    from apps.billing.orders import open_order

    plans = list(Package.plans())
    base_tier = sub.package.storage_tier if sub else None
    base_mb, base_price = (base_tier.storage_mb, base_tier.monthly_price) if base_tier else (0, 0)
    included = sub.included_codes() if sub else set()
    return render(
        request,
        "panel/billing.html",
        {
            "sub": sub,
            "items": items,
            "plans": plans,
            "cards": pricing.plan_cards(plans),
            "compare": pricing.comparison(plans),
            "current": sub.package if sub else None,
            "cheaper": pricing.cheaper_plan(sub) if sub else None,
            "suggested": pricing.suggested_plan(request.tenant)
            if sub and sub.status != Subscription.Status.ACTIVE
            else None,
            "tiers": [
                (t, max(0, t.monthly_price - base_price))
                for t in StorageTier.objects.filter(is_active=True, storage_mb__gte=base_mb).order_by("storage_mb")
            ],
            "base_mb": base_mb,
            "addons": [a for a in Addon.objects.filter(is_active=True) if a.code not in included],
            "included_addons": [a for a in Addon.objects.filter(is_active=True) if a.code in included],
            "storage_extra": sub.storage_extra_price(sub.period) if sub else 0,
            "periods": Period.choices,
            "invoices": Invoice.objects.filter(tenant=request.tenant)[:20],
            "used": storage_used_bytes(request.tenant),
            "pay_url": reverse("panel:billing_pay"),
            "monthly": sub.renewal_amount(Period.MONTHLY) if sub else 0,
            "yearly": sub.renewal_amount(Period.YEARLY) if sub else 0,
            "can_manage": request.membership.role in MANAGERS,
            "platform": platform,
            "online": platform.payment_mode == PlatformSettings.PaymentMode.ONLINE,
            "open_order": open_order(request.tenant),
            "order_form": RenewalOrderForm(initial_mobile=request.user.mobile),
        },
    )


def _change_plan(request, sub):
    plan = Package.plans().filter(pk=request.POST.get("change_plan")).first()
    if plan is None or plan.pk == sub.package_id:
        return redirect("panel:billing")
    used = storage_used_bytes(request.tenant)
    tier = sub.storage_tier
    # Storage: never below what the new plan includes; going down only if the files fit.
    if plan.storage_tier and (tier.storage_mb < plan.storage_tier.storage_mb or tier == sub.package.storage_tier):
        tier = plan.storage_tier
    if used > tier.storage_mb * 1024 * 1024:
        messages.error(
            request, f"فایل‌های دفتر بیشتر از فضای «{plan.name}» است. اول فایل‌های قدیمی را کم کنید یا فضای بیشتر بگیرید."
        )
        return redirect("panel:billing")
    staff = Membership.objects.filter(tenant=request.tenant, is_active=True).count()
    extra_users = sub.addon_quantity(Addon.Code.EXTRA_USER)
    if staff > plan.included_users + extra_users:
        messages.error(
            request,
            f"«{plan.name}» برای {plan.included_users} همکار است و دفتر شما {staff} همکار دارد. "
            "اول دسترسی چند همکار را بردارید یا همکار اضافه بگیرید.",
        )
        return redirect("panel:billing")
    sub.package = plan
    sub.storage_tier = tier
    sub.save(update_fields=["package", "storage_tier"])
    # Anything the new plan already contains is no longer bought separately.
    sub.items.filter(addon__code__in=plan.included_codes()).delete()
    messages.success(request, f"پکیج «{plan.name}» از همین حالا فعال است؛ مبلغ جدید در تمدید بعدی حساب می‌شود.")
    return redirect("panel:billing")


def _save_extras(request, sub):
    base_mb = sub.package.storage_tier.storage_mb if sub.package.storage_tier else 0
    tier = StorageTier.objects.filter(
        pk=request.POST.get("storage_tier"), is_active=True, storage_mb__gte=base_mb
    ).first()
    if tier:
        if storage_used_bytes(request.tenant) > tier.storage_mb * 1024 * 1024:
            messages.error(request, "فایل‌های دفتر از این فضا بیشتر است.")
            return redirect("panel:billing")
        sub.storage_tier = tier
        sub.save(update_fields=["storage_tier"])
    included = sub.included_codes()
    for addon in Addon.objects.filter(is_active=True).exclude(code__in=included):
        raw = request.POST.get(f"addon_{addon.code}")
        qty = (int(raw) if (raw or "").isdigit() else 0) if addon.per_unit else (1 if raw else 0)
        if qty:
            SubscriptionItem.objects.update_or_create(
                subscription=sub, addon=addon, defaults={"quantity": min(qty, 50)}
            )
        else:
            SubscriptionItem.objects.filter(subscription=sub, addon=addon).delete()
    messages.success(request, "تغییرات ثبت شد و از همین حالا فعال است؛ مبلغ آن در تمدید بعدی حساب می‌شود.")
    return redirect("panel:billing")


# ---------------- Support tickets ----------------


@panel_view(write_ok_when_expired=True)
def tickets(request):
    form = TicketForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        ticket = form.save(commit=False)
        ticket.created_by = request.user
        ticket.save()
        TicketMessage.objects.create(
            ticket=ticket,
            author=request.user,
            body=form.cleaned_data["body"],
            attachment=form.cleaned_data.get("attachment"),
        )
        messages.success(request, "تیکت ثبت شد. پاسخ را با پیامک خبر می‌دهیم.")
        return redirect("panel:ticket", pk=ticket.pk)
    return render(request, "panel/tickets.html", {"tickets": Ticket.objects.all(), "form": form})


@panel_view(write_ok_when_expired=True)
def ticket_detail(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    form = ReplyForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        TicketMessage.objects.create(
            ticket=ticket,
            author=request.user,
            body=form.cleaned_data["body"],
            attachment=form.cleaned_data.get("attachment"),
        )
        ticket.status = Ticket.Status.OPEN
        ticket.save(update_fields=["status", "updated_at"])
        return redirect("panel:ticket", pk=ticket.pk)
    return render(
        request,
        "panel/ticket_detail.html",
        {"ticket": ticket, "form": form, "msgs": ticket.messages.select_related("author")},
    )
