import csv
import io
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Membership, normalize_mobile
from apps.billing.models import Addon, Invoice, Period, StorageTier, SubscriptionItem
from apps.claims.models import Claim
from apps.core import jalali
from apps.core.dns import check_domain
from apps.core.models import Domain, PlatformSettings
from apps.crm.models import Customer, Policy, QuoteRequest
from apps.finance.models import Installment
from apps.integrations.models import KIND_LABELS, PROVIDERS, Integration
from apps.integrations.senders import test_connection
from apps.sites import registry
from apps.sites.models import FAQ, SiteSettings, Testimonial
from apps.tickets.models import Ticket, TicketMessage

from .access import MANAGERS, panel_view, storage_used_bytes
from .forms import (
    CustomerForm,
    DomainForm,
    FAQFormSet,
    ImportForm,
    MemberForm,
    PolicyForm,
    QuoteUpdateForm,
    ReplyForm,
    SiteContentForm,
    TestimonialFormSet,
    TicketForm,
)

User = get_user_model()


def _site(request) -> SiteSettings:
    site, _ = SiteSettings.objects.get_or_create(tenant=request.tenant, defaults={"hero_title": request.tenant.name})
    return site


# ---------------- Dashboard ----------------


@panel_view()
def dashboard(request):
    today = timezone.localdate()
    renewals = (
        Policy.objects.filter(
            status=Policy.Status.ACTIVE, end_date__gte=today, end_date__lte=today + timedelta(days=30)
        )
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
    alerts = []
    if "finance" in request.features:
        overdue = Installment.objects.filter(status=Installment.Status.PENDING, due_date__lt=today)
        n = overdue.count()
        if n:
            total = overdue.aggregate(s=Sum("amount"))["s"] or 0
            alerts.append((f"{n} قسط معوق به مبلغ {total:,} تومان", "panel:installments", "?f=overdue"))
    if "claims" in request.features:
        n = Claim.objects.filter(status=Claim.Status.REPORTED, reported_by_customer=True).count()
        if n:
            alerts.append((f"{n} خسارت تازه از پنل مشتری", "panel:claims", "?s=reported"))
    return render(
        request,
        "panel/dashboard.html",
        {
            "renewals": renewals,
            "new_quotes": QuoteRequest.objects.filter(status=QuoteRequest.Status.NEW).select_related("line")[:6],
            "stats": {
                "customers": Customer.objects.count(),
                "active_policies": Policy.objects.filter(status=Policy.Status.ACTIVE, end_date__gte=today).count(),
                "month_premium": Policy.objects.filter(start_date__gte=month_start, start_date__lt=month_end)
                .exclude(status=Policy.Status.CANCELLED)
                .aggregate(s=Sum("premium"))["s"]
                or 0,
                "open_quotes": QuoteRequest.objects.filter(status__in=["new", "contacted", "waiting_docs"]).count(),
            },
            "checklist": checklist,
            "alerts": alerts,
            "checklist_done": sum(1 for c in checklist if c[1]),
            "welcome": request.GET.get("welcome"),
            "site": site,
            "today": today,
        },
    )


# ---------------- Customers ----------------


@panel_view()
def customers(request):
    qs = Customer.objects.annotate(n_policies=Count("policies")).order_by("-created_at")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q) | Q(mobile__contains=normalize_mobile(q) or q) | Q(national_code__contains=q)
        )
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "panel/customers.html", {"page": page, "q": q})


@panel_view()
def customer_edit(request, pk=None):
    obj = get_object_or_404(Customer, pk=pk) if pk else None
    form = CustomerForm(request.POST or None, instance=obj, features=request.features)
    if request.method == "POST" and form.is_valid():
        customer = form.save()
        messages.success(request, "مشتری ذخیره شد.")
        return redirect("panel:customer", pk=customer.pk)
    return render(
        request,
        "panel/form.html",
        {"form": form, "title": "ویرایش مشتری" if obj else "مشتری جدید", "back": "panel:customers"},
    )


@panel_view()
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
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
    qs = Policy.objects.select_related("customer", "line", "company")
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
    return render(request, "panel/policies.html", {"page": page, "f": flt, "q": q, "today": today})


def _storage_left(request) -> int | None:
    sub = request.subscription
    if not sub:
        return None
    return max(0, sub.storage_limit_bytes() - storage_used_bytes(request.tenant))


@panel_view()
def policy_edit(request, pk=None):
    obj = get_object_or_404(Policy, pk=pk) if pk else None
    initial = {}
    renew_from = None
    if not obj and request.GET.get("renew"):
        renew_from = get_object_or_404(Policy, pk=request.GET["renew"])
        initial = {
            "customer": renew_from.customer_id,
            "line": renew_from.line_id,
            "company": renew_from.company_id,
            "subject": renew_from.subject,
            "start_date": renew_from.end_date,
            "end_date": renew_from.end_date + timedelta(days=365),
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
    )
    if request.method == "POST" and form.is_valid():
        policy = form.save(commit=False)
        if renew_from:
            policy.renewed_from = renew_from
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
    qs = QuoteRequest.objects.select_related("line", "assigned_to")
    status = request.GET.get("s", "")
    if status in QuoteRequest.Status.values:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "panel/quotes.html", {"page": page, "s": status, "statuses": QuoteRequest.Status.choices})


@panel_view()
def quote_detail(request, pk):
    quote = get_object_or_404(QuoteRequest.objects.select_related("line"), pk=pk)
    form = QuoteUpdateForm(request.POST or None, instance=quote, tenant=request.tenant)
    if request.method == "POST":
        if "make_customer" in request.POST:
            customer, created = Customer.objects.get_or_create(
                mobile=quote.mobile,
                defaults={"full_name": quote.full_name, "source": Customer.Source.WEBSITE, "marketer": quote.marketer},
            )
            quote.customer = customer
            quote.save(update_fields=["customer"])
            messages.success(request, "مشتری ساخته شد." if created else "به مشتری موجود وصل شد.")
            return redirect("panel:quote", pk=quote.pk)
        if form.is_valid():
            form.save()
            messages.success(request, "درخواست به‌روز شد.")
            return redirect("panel:quotes")
    return render(request, "panel/quote_detail.html", {"quote": quote, "form": form})


# ---------------- Website ----------------


@panel_view()
def site_settings(request):
    site = _site(request)
    form = SiteContentForm(request.POST or None, request.FILES or None, instance=site, prefix="s")
    tforms = TestimonialFormSet(request.POST or None, queryset=Testimonial.objects.all(), prefix="t")
    fforms = FAQFormSet(request.POST or None, queryset=FAQ.objects.all(), prefix="q")
    if request.method == "POST" and form.is_valid() and tforms.is_valid() and fforms.is_valid():
        form.save()
        for fs in (tforms, fforms):
            for obj in fs.save(commit=False):
                obj.save()
            for obj in fs.deleted_objects:
                obj.delete()
        messages.success(request, "محتوای سایت ذخیره شد.")
        return redirect("panel:site")
    return render(request, "panel/site.html", {"form": form, "tforms": tforms, "fforms": fforms, "site": site})


@panel_view()
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


@panel_view(managers_only=True)
@require_POST
def site_publish(request):
    site = _site(request)
    site.is_published = request.POST.get("publish") == "1"
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
    return render(
        request,
        "panel/domains.html",
        {
            "form": form,
            "domains": domains_qs,
            "limit": limit,
            "nameservers": PlatformSettings.load().get_nameservers(),
        },
    )


@panel_view(managers_only=True)
@require_POST
def domain_action(request, pk):
    domain = get_object_or_404(Domain, pk=pk, tenant=request.tenant)
    action = request.POST.get("action")
    if action == "check":
        ok = check_domain(domain)
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
    return render(request, "panel/integrations.html", {"groups": groups})


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
        },
    )


# ---------------- Team ----------------


@panel_view(managers_only=True)
def team(request):
    members = Membership.objects.filter(tenant=request.tenant).select_related("user")
    sub = request.subscription
    limit = sub.user_limit() if sub else 1
    form = MemberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if members.filter(is_active=True).count() >= limit:
            messages.error(request, "سقف کاربران پر است. از بخش اشتراک «کاربر اضافه» بخرید.")
        else:
            user, _ = User.objects.get_or_create(
                mobile=form.cleaned_data["mobile"], defaults={"full_name": form.cleaned_data["full_name"]}
            )
            m, created = Membership.objects.get_or_create(
                user=user, tenant=request.tenant, defaults={"role": form.cleaned_data["role"]}
            )
            if not created:
                m.is_active = True
                m.role = form.cleaned_data["role"]
                m.save()
            messages.success(request, f"{user} اضافه شد؛ با همین موبایل از bimcrm.ir وارد می‌شود.")
        return redirect("panel:team")
    return render(request, "panel/team.html", {"members": members, "form": form, "limit": limit})


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


@panel_view(write_ok_when_expired=True)
def billing(request):
    sub = request.subscription
    if request.method == "POST" and request.membership.role in MANAGERS and sub:
        tier = StorageTier.objects.filter(pk=request.POST.get("storage_tier"), is_active=True).first()
        if tier:
            sub.storage_tier = tier
            sub.save(update_fields=["storage_tier"])
        for addon in Addon.objects.filter(is_active=True):
            raw = request.POST.get(f"addon_{addon.code}")
            qty = (int(raw) if (raw or "").isdigit() else 0) if addon.per_unit else (1 if raw else 0)
            if qty:
                SubscriptionItem.objects.update_or_create(subscription=sub, addon=addon, defaults={"quantity": qty})
            else:
                SubscriptionItem.objects.filter(subscription=sub, addon=addon).delete()
        messages.success(request, "تغییرات ثبت شد و از همین حالا فعال است؛ مبلغ آن در تمدید بعدی حساب می‌شود.")
        return redirect("panel:billing")
    items = {i.addon.code: i.quantity for i in sub.items.select_related("addon")} if sub else {}
    return render(
        request,
        "panel/billing.html",
        {
            "sub": sub,
            "items": items,
            "tiers": StorageTier.objects.filter(is_active=True),
            "addons": Addon.objects.filter(is_active=True),
            "periods": Period.choices,
            "invoices": Invoice.objects.filter(tenant=request.tenant)[:20],
            "used": storage_used_bytes(request.tenant),
            "pay_url": f"{settings.PLATFORM_SCHEME}://{settings.PLATFORM_DOMAIN}/pay/{request.tenant.slug}/",
            "monthly": sub.renewal_amount(Period.MONTHLY) if sub else 0,
            "yearly": sub.renewal_amount(Period.YEARLY) if sub else 0,
            "can_manage": request.membership.role in MANAGERS,
        },
    )


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
