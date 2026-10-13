from django import forms
from django.contrib import messages
from django.core import signing
from django.shortcuts import redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from apps.accounts.models import normalize_mobile, validate_mobile
from apps.accounts.otp import OTPError, issue_code, verify_code
from apps.crm.models import Customer, Policy, QuoteRequest
from apps.integrations.models import Integration
from apps.integrations.senders import send_tenant_otp, tenant_can_sms

from .models import FAQ, SiteSettings, Testimonial

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
    return {
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
    return render(request, f"sites/{site.template}/home.html", _site_context(request, site))


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
    quote = QuoteRequest.objects.create(
        line=line,
        full_name=form.cleaned_data["full_name"],
        mobile=form.cleaned_data["mobile"],
        message=form.cleaned_data["message"],
        details=details,
        customer=customer,
    )
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
        customer = Customer.objects.filter(mobile=mobile).first()
        policies = Policy.objects.filter(customer=customer).select_related("line", "company") if customer else []
        quotes = QuoteRequest.objects.filter(mobile=mobile)[:10]
        return render(
            request,
            "sites/account.html",
            {**ctx, "customer": customer, "policies": policies, "quotes": quotes, "mobile": mobile},
        )
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
