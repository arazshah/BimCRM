from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.otp import OTPError, issue_code, verify_code
from apps.accounts.sms import SmsError, send_platform_otp
from apps.billing import zarinpal
from apps.billing.models import Invoice, Package, Period, Subscription
from apps.billing.services import create_workspace
from apps.core.models import InsuranceCompany, PlatformSettings, Showcase, Tenant, is_subdomain_available
from apps.sites import registry
from apps.sites.demo import demo_context

from .forms import CodeForm, MobileForm, OfficeForm, TemplateForm

User = get_user_model()
WIZARD_KEY = "signup_wizard"


def health(request):
    return JsonResponse({"ok": True})


def landing(request):
    return render(
        request,
        "main/landing.html",
        {
            "templates": registry.TEMPLATES,
            **_pricing(),
            "platform": PlatformSettings.load(),
            "companies": InsuranceCompany.objects.filter(is_active=True),
            "showcases": Showcase.objects.filter(is_active=True).select_related("tenant"),
        },
    )


def features_page(request):
    """Every feature in plain words (moved off the landing page so the landing stays short)."""
    return render(request, "main/features.html", {**_pricing(), "platform": PlatformSettings.load()})


def _pricing():
    from apps.billing import pricing

    from . import features

    plans = list(Package.plans())
    explorer, feature_total = features.explorer(plans)
    return {
        "explorer": explorer,
        "feature_total": feature_total,
        "plans": plans,
        "cards": pricing.plan_cards(plans),
        "compare": pricing.comparison(plans),
        "extras": pricing.extras(),
        "price_faq": pricing.FAQ,
    }


@xframe_options_sameorigin
def template_preview(request, key):
    """Live demo of a template. The landing page frames it (?embed=1) to show the real output."""
    if key not in registry.BY_KEY:
        return redirect("main:landing")
    ctx = demo_context(key)
    ctx["is_embed"] = request.GET.get("embed") == "1"
    return render(request, f"sites/{key}/home.html", ctx)


@require_GET
def check_slug(request):
    ok, msg = is_subdomain_available(request.GET.get("slug", ""))
    return JsonResponse({"ok": ok, "message": msg})


# ---------- Login / sign-up with mobile + one-time code ----------


def login_start(request):
    """Step 1 for both login and sign-up: enter mobile, receive a code."""
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    if request.user.is_authenticated:
        return redirect(next_url if _is_safe_next(next_url) else "main:dashboard")
    form = MobileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        mobile = form.cleaned_data["mobile"]
        try:
            issue_code(mobile, send_platform_otp)
        except (OTPError, SmsError) as exc:
            form.add_error("mobile", str(exc))
        else:
            request.session["login_mobile"] = mobile
            request.session["login_next"] = next_url
            return redirect("main:login_verify")
    return render(request, "main/login.html", {"form": form, "next": next_url})


def login_verify(request):
    mobile = request.session.get("login_mobile")
    if not mobile:
        return redirect("main:login")
    form = CodeForm(request.POST or None)
    if request.method == "POST":
        if "resend" in request.POST:
            try:
                issue_code(mobile, send_platform_otp)
                messages.success(request, "کد جدید فرستاده شد.")
            except (OTPError, SmsError) as exc:
                messages.error(request, str(exc))
            return redirect("main:login_verify")
        if form.is_valid():
            try:
                verify_code(mobile, form.cleaned_data["code"])
            except OTPError as exc:
                form.add_error("code", str(exc))
            else:
                user, _ = User.objects.get_or_create(mobile=mobile)
                if not user.is_active:
                    form.add_error("code", "این حساب غیرفعال شده است. با پشتیبانی تماس بگیرید.")
                else:
                    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                    request.session.pop("login_mobile", None)
                    nxt = request.session.pop("login_next", "")
                    if _is_safe_next(nxt):
                        return redirect(nxt)
                    return redirect("main:dashboard")
    return render(request, "main/login_verify.html", {"form": form, "mobile": mobile})


def _is_safe_next(url: str) -> bool:
    """Relative paths, or absolute URLs on bimcrm.ir and its subdomains (the panels live there)."""
    if not url:
        return False
    if url.startswith("/") and not url.startswith("//"):
        return True
    parsed = urlparse(url)
    base = settings.PLATFORM_DOMAIN.lower()
    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and (host == base or host.endswith("." + base))


def logout_view(request):
    logout(request)
    return redirect("main:landing")


@login_required
def dashboard(request):
    """After login: one workspace → go to its panel; none → start the wizard; several → choose."""
    tenants = Tenant.objects.filter(memberships__user=request.user, memberships__is_active=True).distinct()
    if not tenants:
        return redirect("main:signup")
    if len(tenants) == 1 and not request.GET.get("all"):
        return redirect(tenants[0].panel_url())
    return render(request, "main/workspaces.html", {"tenants": tenants})


# ---------- Workspace wizard: office -> template -> plan ----------


def _wizard(request) -> dict:
    return request.session.setdefault(WIZARD_KEY, {})


@login_required
def signup(request):
    data = _wizard(request)
    initial = {**data, "full_name": request.user.full_name}
    if request.GET.get("slug"):
        initial["slug"] = request.GET["slug"].strip().lower()[:30]
    form = OfficeForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data.update(form.cleaned_data)
        request.session.modified = True
        if not request.user.full_name:
            request.user.full_name = form.cleaned_data["full_name"]
            request.user.save(update_fields=["full_name"])
        return redirect("main:signup_template")
    return render(request, "main/signup_office.html", {"form": form, "step": 1})


@login_required
def signup_template(request):
    """Last step: pick a look, and the site and panel are created on the spot.

    No package or price is asked for here. Every office starts a free trial on the recommended package, so the
    agent sees the whole product working with their own data first and chooses a package in the panel later.
    """
    data = _wizard(request)
    if "slug" not in data:
        return redirect("main:signup")
    form = TemplateForm(request.POST or None, initial={"template": data.get("template", "modern")})
    if request.method == "POST" and form.is_valid():
        ok, msg = is_subdomain_available(data["slug"])
        if not ok:
            messages.error(request, f"آدرس {data['slug']}: {msg} لطفاً آدرس دیگری انتخاب کنید.")
            return redirect("main:signup")
        tenant = create_workspace(
            owner=request.user,
            name=data["name"],
            slug=data["slug"],
            template=form.cleaned_data["template"],
            package=Package.recommended(),
            period="monthly",
        )
        request.session.pop(WIZARD_KEY, None)
        return redirect(tenant.panel_url() + "?welcome=1")
    return render(
        request,
        "main/signup_template.html",
        {
            "form": form,
            "step": 2,
            "templates": registry.TEMPLATES,
            "slug": data["slug"],
            "platform": PlatformSettings.load(),
            "trial_plan": Package.recommended(),
        },
    )


@login_required
def signup_plan(request):
    """Old third step (choosing a package). Packages are now chosen in the panel after the free trial."""
    return redirect("main:signup_template")


# ---------- Paying for a subscription (Zarinpal) ----------


@login_required
@require_POST
def pay(request, tenant_slug):
    tenant = get_object_or_404(
        Tenant, slug=tenant_slug, memberships__user=request.user, memberships__role__in=["owner", "manager"]
    )
    if PlatformSettings.load().payment_mode != PlatformSettings.PaymentMode.ONLINE:
        return redirect(tenant.panel_url() + "billing/")
    return start_subscription_payment(request, tenant)


def start_subscription_payment(request, tenant):
    """Create the invoice and send the user to Zarinpal. Called from the main site and from the panel."""
    sub: Subscription = tenant.subscription
    period = request.POST.get("period", sub.period)
    if period not in Period.values:
        period = sub.period
    amount = sub.renewal_amount(period)
    invoice = Invoice.objects.create(
        tenant=tenant, period=period, amount=amount, description=f"تمدید اشتراک {tenant.name} ({Period(period).label})"
    )
    if amount == 0:
        _mark_paid(invoice, ref_id="FREE")
        messages.success(request, "اشتراک تمدید شد.")
        return redirect(tenant.panel_url() + "billing/")
    # The callback always lives on the main domain, whichever host started the payment.
    path = reverse("main:pay_callback", args=[invoice.pk], urlconf=settings.ROOT_URLCONF)
    callback = f"{settings.PLATFORM_SCHEME}://{settings.PLATFORM_DOMAIN}{path}"
    try:
        authority, url = zarinpal.request_payment(amount, invoice.description, callback, request.user.mobile)
    except zarinpal.ZarinpalError as exc:
        invoice.status = Invoice.Status.FAILED
        invoice.save(update_fields=["status"])
        messages.error(request, str(exc))
        return redirect(tenant.panel_url() + "billing/")
    invoice.authority = authority
    invoice.save(update_fields=["authority"])
    return redirect(url)


def pay_callback(request, invoice_id):
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    panel_billing = invoice.tenant.panel_url() + "billing/"
    if invoice.status == Invoice.Status.PAID:
        return redirect(panel_billing)
    authority = request.GET.get("Authority", "")
    if request.GET.get("Status") != "OK" or authority != invoice.authority:
        invoice.status = Invoice.Status.FAILED
        invoice.save(update_fields=["status"])
        return render(request, "main/pay_result.html", {"ok": False, "invoice": invoice, "back": panel_billing})
    try:
        ref_id = zarinpal.verify_payment(invoice.amount, authority)
    except zarinpal.ZarinpalError as exc:
        invoice.status = Invoice.Status.FAILED
        invoice.save(update_fields=["status"])
        return render(
            request, "main/pay_result.html", {"ok": False, "invoice": invoice, "back": panel_billing, "error": str(exc)}
        )
    _mark_paid(invoice, ref_id)
    return render(request, "main/pay_result.html", {"ok": True, "invoice": invoice, "back": panel_billing})


def _mark_paid(invoice: Invoice, ref_id: str):
    invoice.status = Invoice.Status.PAID
    invoice.ref_id = ref_id
    invoice.paid_at = timezone.now()
    invoice.save(update_fields=["status", "ref_id", "paid_at"])
    invoice.tenant.subscription.extend(invoice.period)


def verification_file(request, name):
    """Empty file at the site root that seal providers (eNamad) ask for to prove domain ownership."""
    code = PlatformSettings.load().enamad_code
    if not code or name != code:
        raise Http404
    return HttpResponse("", content_type="text/plain")


def robots(request):
    base = f"{settings.PLATFORM_SCHEME}://{settings.PLATFORM_DOMAIN}"
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /me/",
        "Disallow: /login/",
        "Disallow: /signup/",
        "Disallow: /pay/",
        "Disallow: /api/",
        "Disallow: /templates/",
        "",
        f"Sitemap: {base}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def help_index(request):
    from . import help as h

    return render(
        request,
        "help/index.html",
        {
            "sections": h.SECTIONS,
            "videos": h.VIDEOS[:3],
            "video_count": len(h.VIDEOS),
            "platform": PlatformSettings.load(),
        },
    )


def demo(request):
    """Public demo office: its website, management panel and customer portal, open to everyone, nothing saved."""
    from .demo import ensure_demo

    tenant = ensure_demo()
    return render(
        request,
        "main/demo.html",
        {
            "site_url": f"{settings.PLATFORM_SCHEME}://{tenant.subdomain_host}/",
            "panel_url": tenant.panel_url(),
            "portal_url": f"{settings.PLATFORM_SCHEME}://{tenant.subdomain_host}/account/",
            "host": tenant.subdomain_host,
            "platform": PlatformSettings.load(),
        },
    )


def help_videos(request):
    from . import help as h

    return render(request, "help/videos.html", {"videos": h.VIDEOS, "platform": PlatformSettings.load()})


def help_article(request, slug):
    from django.http import Http404

    from . import help as h

    article = h.BY_SLUG.get(slug)
    if article is None:
        raise Http404
    prev, nxt = h.neighbours(slug)
    return render(
        request,
        "help/article.html",
        {
            "article": article,
            "section": h.section_of(slug),
            "sections": h.SECTIONS,
            "prev": prev,
            "next": nxt,
            "body_template": f"help/a/{slug}.html",
            "videos": h.videos_for(slug),
            "platform": PlatformSettings.load(),
        },
    )


def help_articles():
    from . import help as h

    return h.ORDER


def guide_list():
    from . import guides as g

    return g.GUIDES


def company_list():
    from apps.core.models import InsuranceCompany

    return InsuranceCompany.objects.filter(is_active=True).exclude(slug="")


def sitemap(request):
    base = f"{settings.PLATFORM_SCHEME}://{settings.PLATFORM_DOMAIN}"
    today = timezone.localdate().isoformat()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{base}/</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>1.0</priority></url>\n"
        f"  <url><loc>{base}/features/</loc><lastmod>{today}</lastmod><priority>0.9</priority></url>\n"
        f"  <url><loc>{base}/help/</loc><lastmod>{today}</lastmod><priority>0.7</priority></url>\n"
        f"  <url><loc>{base}/help/videos/</loc><lastmod>{today}</lastmod><priority>0.7</priority></url>\n"
        + "".join(f"  <url><loc>{base}/help/{a.slug}/</loc><priority>0.6</priority></url>\n" for a in help_articles())
        + f"  <url><loc>{base}/guides/</loc><lastmod>{today}</lastmod><priority>0.8</priority></url>\n"
        + "".join(f"  <url><loc>{base}/guides/{x.slug}/</loc><priority>0.8</priority></url>\n" for x in guide_list())
        + f"  <url><loc>{base}/bime/</loc><lastmod>{today}</lastmod><priority>0.7</priority></url>\n"
        + "".join(f"  <url><loc>{base}/bime/{c.slug}/</loc><priority>0.6</priority></url>\n" for c in company_list())
        + "</urlset>\n"
    )
    return HttpResponse(xml, content_type="application/xml")


def company_hub(request):
    from apps.core.models import InsuranceCompany

    companies = InsuranceCompany.objects.filter(is_active=True).exclude(slug="")
    return render(request, "main/company_hub.html", {"companies": companies, "platform": PlatformSettings.load()})


def company_page(request, slug):
    from django.http import Http404

    from apps.core.models import InsuranceCompany, LineOfBusiness

    company = InsuranceCompany.objects.filter(is_active=True, slug=slug).first()
    if company is None:
        raise Http404
    others = InsuranceCompany.objects.filter(is_active=True).exclude(slug="").exclude(pk=company.pk)[:8]
    return render(
        request,
        "main/company.html",
        {
            "company": company,
            "lines": LineOfBusiness.objects.filter(is_active=True),
            "others": others,
            "platform": PlatformSettings.load(),
        },
    )


def guides_index(request):
    from . import guides as g

    return render(request, "main/guides_index.html", {"guides": g.GUIDES, "platform": PlatformSettings.load()})


def guide_page(request, slug):
    from django.http import Http404

    from . import guides as g

    guide = g.BY_SLUG.get(slug)
    if guide is None:
        raise Http404
    return render(
        request,
        "main/guide.html",
        {
            "guide": guide,
            "body_template": f"main/guides/{slug}.html",
            "others": [x for x in g.GUIDES if x.slug != slug][:3],
            "platform": PlatformSettings.load(),
        },
    )
