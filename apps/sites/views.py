import re
import time

from django import forms
from django.contrib import messages
from django.core import signing
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from apps.accounts.models import normalize_mobile, validate_mobile
from apps.accounts.otp import OTPError, issue_code, verify_code
from apps.crm.models import Branch, Customer, CustomerDocument, Policy, QuoteRequest
from apps.integrations.models import Integration
from apps.integrations.senders import send_tenant_otp, tenant_can_sms

from . import pwa
from .models import FAQ, SiteLineContent, SiteSettings, Testimonial

SITE_TRACKED_QUOTE = "site_tracked_quote"
SITE_CREATED_QUOTE = "site_created_quote"
SESSION_QUOTE_TTL = 5 * 60
CUSTOM_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

REF_COOKIE = "bc_ref"
CREF_COOKIE = "bc_cref"
REF_MAX_AGE = 60 * 60 * 24 * 30
CUSTOMER_COOKIE = "bc_customer"
CUSTOMER_MAX_AGE = 60 * 60 * 24 * 30


def _store_session_quote(request, key, quote):
    request.session[key] = {"id": quote.pk, "expires": int(time.time()) + SESSION_QUOTE_TTL}


def _consume_session_quote(request, key):
    payload = request.session.pop(key, None)
    if not isinstance(payload, dict):
        return None
    try:
        quote_id = int(payload["id"])
        expires = int(payload["expires"])
    except (KeyError, TypeError, ValueError):
        return None
    if expires <= int(time.time()):
        return None
    return QuoteRequest.objects.filter(pk=quote_id).select_related("line").first()


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
    lines = list(site.lines.filter(is_active=True))
    for line in lines:
        line.public_form_fields = _public_form_fields(line)
    selected_line = next((line for line in lines if line.slug == request.GET.get("line")), None)
    if selected_line is None and lines:
        selected_line = lines[0]
    line_contents = {
        content.line_id: content for content in SiteLineContent.objects.filter(line__in=lines).select_related("line")
    }
    site_branches = []
    if "branches" in _features(request):
        site_branches = list(Branch.objects.filter(is_active=True, show_on_site=True).order_by("order", "name"))
    return {
        "site_branches": site_branches,
        "site": site,
        "tenant": request.tenant,
        "tpl": site.template_info,
        "lines": lines,
        "selected_line": selected_line,
        "selected_line_slug": selected_line.slug if selected_line else "",
        "form_page": "",
        "line_fields": selected_line.public_form_fields if selected_line else [],
        "line_contents": line_contents,
        "companies": site.companies.filter(is_active=True),
        "testimonials": Testimonial.objects.filter(is_visible=True)[:6],
        "faqs": FAQ.objects.all()[:8],
        "trust_badges": trust_badges,
        "head_code": mark_safe(meta + head),
        "body_code": mark_safe(codes.get(("custom", "body"), {}).get("code", "")),
        "is_demo": False,
        "can_portal": tenant_can_sms(request.tenant),
        "has_claims": "claims" in _features(request),
        "is_preview": not site.is_published,
        "is_noindex": not site.is_published,
        "base_template": f"sites/{site.template}/base.html",
        "mbar_items": pwa.mbar_items(site, tenant_can_sms(request.tenant), "claims" in _features(request)),
        "mbar_active": pwa.mbar_active(request.path),
    }


def _line_page_context(context, line):
    content = context["line_contents"].get(line.pk)
    document_labels = dict(CustomerDocument.Kind.choices)
    return {
        "line": line,
        "line_content": content,
        "page_title": content.seo_title if content and content.seo_title else f"{line.name} | {context['tenant'].name}",
        "page_description": content.seo_description
        if content and content.seo_description
        else (content.intro if content and content.intro else line.summary),
        "selected_line_slug": line.slug,
        "form_page": line.slug,
        "required_doc_labels": [document_labels.get(key, key) for key in (line.required_docs or [])],
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
    cref = request.GET.get("c", "").strip().upper()[:10]
    if cref and cref.isalnum():
        # A customer's own referral code (customer club).
        resp.set_cookie(
            CREF_COOKIE, cref, max_age=REF_MAX_AGE, httponly=True, samesite="Lax", secure=request.is_secure()
        )
    return resp


def line_detail(request, slug):
    site = _site(request)
    if not site.is_published and not _is_team_member(request):
        return render(request, "sites/coming_soon.html", {"tenant": request.tenant}, status=200)
    line = site.lines.filter(slug=slug, is_active=True).first()
    if line is None:
        from django.http import Http404

        raise Http404
    context = _site_context(request, site)
    context.update(_line_page_context(context, line))
    return render(request, "sites/line_detail.html", context)


def guide(request, kind):
    site = _site(request)
    if kind not in {"claims", "renewal"}:
        from django.http import Http404

        raise Http404
    if not site.is_published and not _is_team_member(request):
        return render(request, "sites/coming_soon.html", {"tenant": request.tenant}, status=200)
    context = _site_context(request, site)
    guide_title = "راهنمای اقدام هنگام خسارت" if kind == "claims" else "راهنمای تمدید بیمه‌نامه"
    context.update(
        {
            "guide_kind": kind,
            "page_title": f"{guide_title} | {request.tenant.name}",
            "page_description": f"اطلاعات اولیه دربارهٔ {guide_title} و راه ارتباط با دفتر {request.tenant.name}.",
            "is_noindex": False,
        }
    )
    return render(request, "sites/guide.html", context)


def privacy(request):
    site = _site(request)
    if not site.is_published and not _is_team_member(request):
        return render(request, "sites/coming_soon.html", {"tenant": request.tenant}, status=200)
    context = _site_context(request, site)
    context.update(
        {
            "page_title": f"حریم خصوصی | {request.tenant.name}",
            "page_description": f"نحوهٔ استفاده از اطلاعات فرم استعلام و پنل مشتری در سایت {request.tenant.name}.",
            "is_noindex": False,
        }
    )
    return render(request, "sites/privacy.html", context)


def _referring_customer(request, mobile=""):
    code = request.COOKIES.get(CREF_COOKIE, "")
    if not code:
        return None
    ref = Customer.objects.filter(referral_code=code).first()
    return ref if ref and ref.mobile != mobile else None


def _referring_marketer(request):
    from apps.billing.models import has_feature
    from apps.network.models import Marketer

    code = request.COOKIES.get(REF_COOKIE)
    if not code or not has_feature(request.tenant, "marketers"):
        return None
    return Marketer.objects.filter(code=code, is_active=True).first()


class QuoteForm(forms.Form):
    line = forms.CharField(max_length=40)
    full_name = forms.CharField(max_length=120)
    mobile = forms.CharField(max_length=20)
    message = forms.CharField(required=False, max_length=1000)

    def clean_full_name(self):
        value = self.cleaned_data["full_name"].strip()
        if not value:
            raise forms.ValidationError("نام و نام خانوادگی را وارد کنید.")
        return value

    def clean_mobile(self):
        mobile = normalize_mobile(self.cleaned_data["mobile"])
        validate_mobile(mobile)
        return mobile


def _public_form_fields(line):
    """Normalize the editable catalog schema before it reaches either HTML or validation."""
    fields = []
    for raw in line.form_fields or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", ""))
        if not CUSTOM_FIELD_NAME.fullmatch(name):
            continue
        field_type = raw.get("type", "text")
        if field_type not in {"text", "number", "email", "tel", "date", "select", "textarea"}:
            field_type = "text"
        options = raw.get("options", [])
        if not isinstance(options, list):
            options = []
        options = [str(option).strip()[:80] for option in options if str(option).strip()][:30]
        if field_type == "select" and not options:
            continue
        try:
            max_length = int(raw.get("max_length", 200))
        except (TypeError, ValueError):
            max_length = 200
        fields.append(
            {
                "name": name,
                "label": str(raw.get("label") or name)[:80],
                "type": field_type,
                "required": bool(raw.get("required", False)),
                "max_length": min(200, max(1, max_length)),
                "options": options,
            }
        )
    return fields


def _custom_quote_details(request, line):
    details, errors = {}, []
    for field in _public_form_fields(line):
        value = request.POST.get(f"f_{field['name']}", "").strip()
        if field["required"] and not value:
            errors.append(f"وارد کردن «{field['label']}» الزامی است.")
            continue
        if len(value) > field["max_length"]:
            errors.append(f"مقدار «{field['label']}» بیش از حد مجاز است.")
            continue
        if field["type"] == "select" and value and value not in field["options"]:
            errors.append(f"مقدار «{field['label']}» را از گزینه‌های نمایش‌داده‌شده انتخاب کنید.")
            continue
        if field["type"] == "email" and value:
            try:
                forms.EmailField().clean(value)
            except forms.ValidationError:
                errors.append(f"نشانی ایمیل «{field['label']}» معتبر نیست.")
                continue
        numeric = value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        if field["type"] == "number" and value and not re.fullmatch(r"\d+(?:[.,]\d+)?", numeric):
            errors.append(f"مقدار «{field['label']}» باید عدد باشد.")
            continue
        if field["type"] == "date" and value:
            try:
                forms.DateField().clean(value)
            except forms.ValidationError:
                errors.append(f"تاریخ «{field['label']}» معتبر نیست.")
                continue
        if value:
            details[field["label"]] = value
    return details, errors


def _quote_error_page(request, site, line, form, extra_errors):
    context = _site_context(request, site)
    context.update(
        {
            "quote_errors": [error for errors in form.errors.values() for error in errors] + extra_errors,
            "form_values": request.POST,
            "custom_values": {
                key[2:]: value[:200]
                for key, value in request.POST.items()
                if key.startswith("f_") and CUSTOM_FIELD_NAME.fullmatch(key[2:])
            },
            "selected_line_slug": line.slug if line else request.POST.get("line", ""),
            "selected_line": line,
            "line_fields": _public_form_fields(line) if line else [],
        }
    )
    template = (
        "sites/line_detail.html"
        if line and request.POST.get("form_page") == line.slug
        else f"sites/{site.template}/home.html"
    )
    if template == "sites/line_detail.html":
        context.update(_line_page_context(context, line))
    return render(request, template, context, status=400)


@require_POST
def submit_quote(request):
    site = _site(request)
    form = QuoteForm(request.POST)
    line = site.lines.filter(slug=request.POST.get("line"), is_active=True).first()
    valid = form.is_valid()
    if not valid or line is None:
        if line is None:
            extra_errors = ["رشتهٔ بیمهٔ انتخاب‌شده برای این دفتر فعال نیست."]
        else:
            extra_errors = []
        return _quote_error_page(request, site, line, form, extra_errors)
    details, extra_errors = _custom_quote_details(request, line)
    if extra_errors:
        return _quote_error_page(request, site, line, form, extra_errors)
    customer = Customer.objects.filter(mobile=form.cleaned_data["mobile"]).first()
    marketer = _referring_marketer(request)
    referrer = _referring_customer(request, form.cleaned_data["mobile"])
    if customer and referrer and customer.referred_by_id is None and not customer.policies.exists():
        customer.referred_by = referrer
        customer.save(update_fields=["referred_by"])
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
        referrer=referrer,
    )
    from apps.work.services import on_new_quote

    on_new_quote(quote)
    _store_session_quote(request, SITE_CREATED_QUOTE, quote)
    return redirect("/quote/done/")


def quote_done(request):
    site = _site(request)
    quote = _consume_session_quote(request, SITE_CREATED_QUOTE)
    if quote is None:
        return redirect("sites:home")
    context = _site_context(request, site)
    context.update({"quote": quote, "is_noindex": True})
    return render(request, "sites/quote_done.html", context)


def track(request):
    site = _site(request)
    if request.method == "GET" and request.GET:
        return redirect("/track/")
    quote = None
    if request.method == "POST":
        request.session.pop(SITE_TRACKED_QUOTE, None)
        code = request.POST.get("code", "").strip()[:16]
        code = code.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        mobile = normalize_mobile(request.POST.get("mobile", "")[:20])
        valid_code = len(code) == 8 and code.isdecimal()
        quote = (
            QuoteRequest.objects.filter(tracking_code=code, mobile=mobile).first() if valid_code and mobile else None
        )
        if quote is None:
            messages.error(request, "درخواستی با این کد و موبایل پیدا نشد.")
        else:
            _store_session_quote(request, SITE_TRACKED_QUOTE, quote)
        return redirect("/track/")
    quote = _consume_session_quote(request, SITE_TRACKED_QUOTE)
    context = _site_context(request, site)
    context.update({"quote": quote, "is_noindex": True})
    return render(request, "sites/track.html", context)


# ---------- Customer portal (login with the agent's own SMS panel) ----------


def _customer_mobile(request):
    if getattr(request, "live_demo", False):
        from apps.main.demo import DEMO_CUSTOMER_MOBILE

        return DEMO_CUSTOMER_MOBILE
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
    ctx["is_noindex"] = True
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
            after = request.session.pop("portal_next", "")
            resp = redirect(after if after.startswith("/") and not after.startswith("//") else "sites:account")
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
    from apps.club.models import TIER_LABELS, ClubSettings
    from apps.club.services import referral_code_for

    club = ClubSettings.for_tenant(request.tenant)
    if customer and club.enabled:
        code = referral_code_for(customer)
        link = f"{request.tenant.site_url()}?c={code}"
        data["club"] = {
            "tier": customer.tier,
            "tier_label": TIER_LABELS.get(customer.tier, ""),
            "balance": customer.points_balance,
            "perks": club.perks,
            "code": code,
            "link": link,
            "bonus": club.referral_bonus,
            "share": f"من بیمه‌هایم را از {request.tenant.name} می‌گیرم؛ با این لینک استعلام بگیر: {link}",
            "next_tier": ("نقره‌ای", club.silver_at - customer.points_lifetime)
            if customer.tier == "bronze"
            else ("طلایی", club.gold_at - customer.points_lifetime)
            if customer.tier == "silver"
            else None,
        }
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
    urls = []
    if site.is_published:
        urls = [("/", "1.0")]
        urls.extend(
            (f"/insurance/{slug}/", "0.8") for slug in site.lines.filter(is_active=True).values_list("slug", flat=True)
        )
        urls.extend((("/guide/claims/", "0.5"), ("/guide/renewal/", "0.5"), ("/privacy/", "0.4")))
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


def web_manifest(request):
    return pwa.manifest(request, _site(request))


def service_worker(request):
    return pwa.service_worker(request)


def pwa_icon(request):
    return pwa.icon_svg(request, _site(request))


def office_vcard(request):
    return pwa.vcard(request, _site(request))


def offline(request):
    context = _site_context(request, _site(request))
    context["is_noindex"] = True
    return render(request, "sites/offline.html", context)


def favicon(request):
    site = _site(request)
    if site.logo:
        return redirect(site.logo.url)
    return HttpResponse(status=204)
