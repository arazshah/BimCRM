from django import forms
from django.contrib import messages
from django.core import signing
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from apps.accounts.models import normalize_mobile, validate_mobile
from apps.accounts.otp import OTPError, issue_code, verify_code
from apps.crm.models import Branch, Customer, Policy, QuoteRequest
from apps.integrations.models import Integration
from apps.integrations.senders import send_tenant_otp, tenant_can_sms

from .models import FAQ, SiteSettings, Testimonial

REF_COOKIE = "bc_ref"
REF_MAX_AGE = 60 * 60 * 24 * 30
CUSTOMER_COOKIE = "bc_customer"
CUSTOMER_MAX_AGE = 60 * 60 * 24 * 30


def _site(request) -> SiteSettings:
    site, _ = SiteSettings.objects.get_or_create(tenant=request.tenant, defaults={"hero_title": request.tenant.name})
    return site


def _is_team_member(request) -> bool:
    return (
        request.user.is_authenticated and request.tenant.memberships.filter(user=request.user, is_active=True).exists()
    )


def _site_context(request, site: SiteSettings) -> dict:
    codes = {
        (i.kind, i.provider): i.config for i in Integration.objects.filter(enabled=True, kind__in=["trust", "custom"])
    }
    trust_badges = [
        mark_safe(c.get("badge_html", "")) for (k, _), c in codes.items() if k == "trust" and c.get("badge_html")
    ]
    head = codes.get(("custom", "head"), {}).get("code", "")
    meta = codes.get(("trust", "enamad"), {}).get("meta_code", "")
    lines = site.lines.filter(is_active=True)
    site_branches = []
    if "branches" in _features(request):
        site_branches = list(Branch.objects.filter(is_active=True, show_on_site=True).order_by("order", "name"))
    return {
        "site_branches": site_branches,
        "site": site,
        "tenant": request.tenant,
        "tpl": site.template_info,
        "lines": lines,
        "companies": site.companies.filter(is_active=True),
        "testimonials": Testimonial.objects.filter(is_visible=True)[:6],
        "faqs": FAQ.objects.all()[:8],
        "trust_badges": trust_badges,
        "head_code": mark_safe(meta + head),
        "body_code": mark_safe(codes.get(("custom", "body"), {}).get("code", "")),
        "is_demo": False,
        "can_portal": tenant_can_sms(request.tenant),
        "is_preview": not site.is_published,
        "base_template": f"sites/{site.template}/base.html",
    }


def home(request):
    site = _site(request)
    if not site.is_published and not _is_team_member(request):
        return render(request, "sites/coming_soon.html", {"tenant": request.tenant}, status=200)
    resp = render(request, f"sites/{site.template}/home.html", _site_context(request, site))
    ref = request.GET.get("ref", "").strip().lower()[:12]
    if ref and ref.isalnum():
        # Marketer referral: remembered for 30 days, attached to the visitor's quote request.
        resp.set_cookie(REF_COOKIE, ref, max_age=REF_MAX_AGE, httponly=True, samesite="Lax", secure=request.is_secure())
    return resp


def _referring_marketer(request):
    from apps.billing.models import has_feature
    from apps.network.models import Marketer

    code = request.COOKIES.get(REF_COOKIE)
    if not code or not has_feature(request.tenant, "marketers"):
        return None
    return Marketer.objects.filter(code=code, is_active=True).first()


class QuoteForm(forms.Form):
    line = forms.CharField()
    full_name = forms.CharField(max_length=120)
    mobile = forms.CharField(max_length=20)
    message = forms.CharField(required=False, max_length=1000)

    def clean_mobile(self):
        mobile = normalize_mobile(self.cleaned_data["mobile"])
        validate_mobile(mobile)
        return mobile


@require_POST
def submit_quote(request):
    site = _site(request)
    form = QuoteForm(request.POST)
    line = site.lines.filter(slug=request.POST.get("line")).first()
    if not form.is_valid() or line is None:
        messages.error(request, "نام، موبایل درست و رشته بیمه را وارد کنید.")
        return redirect("/#quote")
    details = {}
    for field in line.form_fields or []:
        name = field.get("name")
        value = request.POST.get(f"f_{name}", "").strip()[:200] if name else ""
        if value:
            details[field.get("label", name)] = value
    customer = Customer.objects.filter(mobile=form.cleaned_data["mobile"]).first()
    marketer = _referring_marketer(request)
    if customer and customer.marketer_id is None and marketer:
        customer.marketer = marketer
        customer.save(update_fields=["marketer"])
    branch = None
    b = request.POST.get("branch", "")
    if b.isdigit() and "branches" in _features(request):
        branch = Branch.objects.filter(pk=int(b), is_active=True, show_on_site=True).first()
    if branch is None and customer:
        branch = customer.branch
    quote = QuoteRequest.objects.create(
        branch=branch,
        marketer=marketer,
        line=line,
        full_name=form.cleaned_data["full_name"],
        mobile=form.cleaned_data["mobile"],
        message=form.cleaned_data["message"],
        details=details,
        customer=customer,
    )
    from apps.work.services import on_new_quote

    on_new_quote(quote)
    return render(request, "sites/quote_done.html", {**_site_context(request, site), "quote": quote})


def track(request):
    site = _site(request)
    quote = None
    code = request.GET.get("code", "").strip()
    mobile = normalize_mobile(request.GET.get("mobile", ""))
    if code and mobile:
        quote = QuoteRequest.objects.filter(tracking_code=code, mobile=mobile).first()
        if quote is None:
            messages.error(request, "درخواستی با این کد و موبایل پیدا نشد.")
    return render(
        request, "sites/track.html", {**_site_context(request, site), "quote": quote, "code": code, "mobile": mobile}
    )


# ---------- Customer portal (login with the agent's own SMS panel) ----------


def _customer_mobile(request):
    raw = request.COOKIES.get(CUSTOMER_COOKIE)
    if not raw:
        return None
    try:
        data = signing.loads(raw, salt=f"customer:{request.tenant.pk}", max_age=CUSTOMER_MAX_AGE)
    except signing.BadSignature:
        return None
    return data.get("m")


def account(request):
    site = _site(request)
    ctx = _site_context(request, site)
    mobile = _customer_mobile(request)
    if mobile:
        return render(request, "sites/account.html", {**ctx, **_portal_data(request, mobile)})
    if not ctx["can_portal"]:
        return render(request, "sites/account_unavailable.html", ctx)
    step = "code" if request.session.get("portal_mobile") else "mobile"
    if request.method == "POST":
        scope = f"tenant:{request.tenant.pk}"
        if "mobile" in request.POST:
            mobile = normalize_mobile(request.POST["mobile"])
            try:
                validate_mobile(mobile)
                issue_code(mobile, lambda m, c: send_tenant_otp(request.tenant, m, c), scope=scope)
            except Exception as exc:  # validation, OTP limits or provider errors
                msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
                messages.error(request, msg)
                return redirect("sites:account")
            request.session["portal_mobile"] = mobile
            return redirect("sites:account")
        if "code" in request.POST and request.session.get("portal_mobile"):
            mobile = request.session["portal_mobile"]
            try:
                verify_code(mobile, request.POST["code"], scope=scope)
            except OTPError as exc:
                messages.error(request, str(exc))
                return redirect("sites:account")
            request.session.pop("portal_mobile", None)
            resp = redirect("sites:account")
            resp.set_cookie(
                CUSTOMER_COOKIE,
                signing.dumps({"m": mobile}, salt=f"customer:{request.tenant.pk}"),
                max_age=CUSTOMER_MAX_AGE,
                httponly=True,
                samesite="Lax",
                secure=request.is_secure(),
            )
            return resp
    return render(
        request,
        "sites/account_login.html",
        {**ctx, "step": step, "portal_mobile": request.session.get("portal_mobile")},
    )


def account_logout(request):
    request.session.pop("portal_mobile", None)
    resp = redirect("sites:home")
    resp.delete_cookie(CUSTOMER_COOKIE)
    return resp


# ---------- Customer portal: installments and claims (when the office has those add-ons) ----------

CUSTOMER_UPLOAD_MAX = 10 * 1024 * 1024
CUSTOMER_UPLOAD_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf")


def _features(request) -> set:
    sub = getattr(request.tenant, "subscription", None)
    return sub.active_addon_codes() if sub and sub.is_writable else set()


def _portal_data(request, mobile: str) -> dict:
    from apps.claims.models import Claim
    from apps.finance.models import Installment

    features = _features(request)
    customer = Customer.objects.filter(mobile=mobile).first()
    policies = (
        list(Policy.objects.filter(customer=customer).select_related("line", "company").order_by("-end_date"))
        if customer
        else []
    )
    data = {
        "customer": customer,
        "policies": policies,
        "mobile": mobile,
        "quotes": QuoteRequest.objects.filter(mobile=mobile).select_related("line")[:10],
        "installments": None,
        "claims": None,
    }
    if customer and "finance" in features:
        data["installments"] = (
            Installment.objects.filter(policy__customer=customer)
            .exclude(status=Installment.Status.PAID)
            .select_related("policy__line")
        )
    from apps.crm.documents import checklist, customer_lines
    from apps.crm.models import CustomerDocument

    if customer:
        data["documents"] = CustomerDocument.objects.filter(customer=customer)
        data["doc_checklist"] = checklist(customer, customer_lines(customer))
    else:
        lines = [
            q.line for q in data["quotes"] if q.status not in (QuoteRequest.Status.ISSUED, QuoteRequest.Status.LOST)
        ]
        data["doc_checklist"] = checklist(None, lines) if lines else []
    data["doc_kinds"] = [
        (k, v)
        for k, v in CustomerDocument.Kind.choices
        if k not in (CustomerDocument.Kind.ENDORSEMENT, CustomerDocument.Kind.POLICY_COPY)
    ]
    data["can_upload_docs"] = bool(customer or data["quotes"])
    if customer and "claims" in features:
        data["claims"] = Claim.objects.filter(policy__customer=customer).prefetch_related("events", "documents")
        data["claimable"] = [p for p in policies if p.status == Policy.Status.ACTIVE]
    return data


def _portal_customer(request):
    mobile = _customer_mobile(request)
    return Customer.objects.filter(mobile=mobile).first() if mobile else None


@require_POST
def account_document_upload(request):
    from apps.crm.documents import validate_upload
    from apps.crm.models import CustomerDocument
    from apps.panel.access import storage_used_bytes
    from apps.work.services import notify, office_members

    mobile = _customer_mobile(request)
    if not mobile:
        return redirect("sites:account")
    customer = Customer.objects.filter(mobile=mobile).first()
    if customer is None:
        quote = QuoteRequest.objects.filter(mobile=mobile).order_by("-created_at").first()
        if quote is None:
            return redirect("sites:account")
        customer = Customer.objects.create(
            full_name=quote.full_name,
            mobile=mobile,
            source=Customer.Source.WEBSITE,
            branch=quote.branch,
            marketer=quote.marketer,
        )
        QuoteRequest.objects.filter(mobile=mobile, customer__isnull=True).update(customer=customer)
    f = request.FILES.get("file")
    kind = request.POST.get("kind", "other")
    if kind not in CustomerDocument.Kind.values:
        kind = CustomerDocument.Kind.OTHER
    err = validate_upload(f) if f else "فایل را انتخاب کنید."
    sub = getattr(request.tenant, "subscription", None)
    if not err and sub and f.size > sub.storage_limit_bytes() - storage_used_bytes(request.tenant):
        err = "در حال حاضر امکان بارگذاری نیست؛ لطفاً با دفتر تماس بگیرید."
    if err:
        messages.error(request, err)
        return redirect("/account/#docs")
    doc = CustomerDocument.objects.create(customer=customer, kind=kind, file=f, by_customer=True)
    notify(
        request.tenant,
        office_members(request.tenant, customer.branch),
        f"{customer.full_name} مدرک فرستاد: {doc.get_kind_display()}",
        f"/panel/customers/{customer.pk}/#docs",
    )
    messages.success(request, f"{doc.get_kind_display()} رسید؛ ممنون. دفتر بررسی می‌کند.")
    return redirect("/account/#docs")


@require_POST
def account_claim_report(request):
    from django.utils.dateparse import parse_date

    from apps.claims.models import Claim, ClaimEvent

    customer = _portal_customer(request)
    if customer is None or "claims" not in _features(request):
        return redirect("sites:account")
    policy = Policy.objects.filter(customer=customer, pk=request.POST.get("policy")).first()
    incident = parse_date(request.POST.get("incident_date", ""))
    description = request.POST.get("description", "").strip()[:2000]
    if policy is None or incident is None or len(description) < 10:
        messages.error(request, "بیمه‌نامه، تاریخ حادثه و شرح حادثه (دست‌کم چند کلمه) را وارد کنید.")
        return redirect("sites:account")
    claim = Claim.objects.create(
        policy=policy, incident_date=incident, description=description, reported_by_customer=True
    )
    ClaimEvent.objects.create(claim=claim, status=claim.status, note="اعلام از پنل مشتری")
    from apps.work.services import on_customer_claim

    on_customer_claim(claim)
    messages.success(request, f"خسارت با شماره پرونده {claim.code} اعلام شد. مدارک را همین‌جا بارگذاری کنید.")
    return redirect("sites:account")


@require_POST
def account_claim_upload(request, claim_id):
    from apps.claims.models import Claim, ClaimDocument
    from apps.panel.access import storage_used_bytes

    customer = _portal_customer(request)
    if customer is None or "claims" not in _features(request):
        return redirect("sites:account")
    claim = Claim.objects.filter(pk=claim_id, policy__customer=customer).first()
    f = request.FILES.get("file")
    title = request.POST.get("title", "").strip()[:120] or "مدرک"
    if claim is None or f is None:
        return redirect("sites:account")
    sub = request.tenant.subscription
    if not f.name.lower().endswith(CUSTOMER_UPLOAD_EXT) or f.size > CUSTOMER_UPLOAD_MAX:
        messages.error(request, "فقط عکس یا PDF تا ۱۰ مگابایت.")
    elif f.size > sub.storage_limit_bytes() - storage_used_bytes(request.tenant):
        messages.error(request, "امکان بارگذاری نیست؛ با دفتر تماس بگیرید.")
    else:
        ClaimDocument.objects.create(claim=claim, title=title, file=f, uploaded_by_customer=True)
        messages.success(request, "مدرک رسید.")
    return redirect("sites:account")


def robots(request):
    site = _site(request)
    if not site.is_published:
        body = "User-agent: *\nDisallow: /\n"
    else:
        body = (
            "User-agent: *\nAllow: /\nDisallow: /panel/\nDisallow: /account/\nDisallow: /quote/\n\n"
            f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}\n"
        )
    return HttpResponse(body, content_type="text/plain")


def sitemap(request):
    site = _site(request)
    urls = [("/", "1.0"), ("/track/", "0.3")] if site.is_published else []
    rows = "".join(
        f"  <url><loc>{request.build_absolute_uri(path)}</loc><priority>{prio}</priority></url>\n"
        for path, prio in urls
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + rows
        + "</urlset>\n"
    )
    return HttpResponse(xml, content_type="application/xml")


def favicon(request):
    site = _site(request)
    if site.logo:
        return redirect(site.logo.url)
    return HttpResponse(status=204)
