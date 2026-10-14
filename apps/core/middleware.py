"""Routes each request by its Host header.

bimcrm.ir / www.bimcrm.ir   -> marketing site, sign-up, login        (config.urls_main)
admin.bimcrm.ir             -> super admin                          (config.urls_admin)
<slug>.bimcrm.ir            -> that agent's site + /panel/          (config.urls_tenant)
agent's own active domain   -> that agent's site                    (config.urls_tenant)
anything else               -> 404
"""

from django.conf import settings
from django.http import HttpResponseNotFound, HttpResponsePermanentRedirect

from .models import Domain, Tenant
from .tenancy import reset_current_tenant, set_current_tenant

HEALTH_PATH = "/healthz"
# Called by the reverse proxy (Caddy on-demand TLS) from inside the server; answers for any Host.
INTERNAL_PATHS = (HEALTH_PATH, "/internal/tls-ask")


class TenantHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        request.host_kind = None
        host = request.get_host().split(":")[0].lower().rstrip(".")
        base = settings.PLATFORM_DOMAIN.lower()

        if request.path in INTERNAL_PATHS:
            request.urlconf = settings.ROOT_URLCONF
            return self.get_response(request)

        tenant = None
        if host in (base, f"www.{base}"):
            if host.startswith("www."):
                return HttpResponsePermanentRedirect(f"{request.scheme}://{base}{request.get_full_path()}")
            request.host_kind = "main"
            request.urlconf = settings.ROOT_URLCONF
        elif host == f"{settings.ADMIN_SUBDOMAIN}.{base}":
            request.host_kind = "admin"
            request.urlconf = settings.URLCONF_ADMIN
        elif host.endswith(f".{base}"):
            slug = host[: -len(base) - 1]
            tenant = Tenant.objects.filter(slug=slug).first()
            if tenant is None:
                return HttpResponseNotFound("این آدرس هنوز به هیچ دفتری تعلق ندارد.")
            # Once the agent's own domain is active, the public site moves there.
            # The panel stays on the subdomain so the shared login cookie keeps working.
            if not request.path.startswith(("/panel", "/static", "/media")):
                primary = tenant.domains.filter(status=Domain.Status.ACTIVE, is_primary=True).first()
                if primary:
                    return HttpResponsePermanentRedirect(
                        f"{request.scheme}://{primary.hostname}{request.get_full_path()}"
                    )
            request.host_kind = "tenant"
            request.urlconf = settings.URLCONF_TENANT
        else:
            bare = host[4:] if host.startswith("www.") else host
            domain = (
                Domain.objects.select_related("tenant")
                .filter(hostname=bare, status__in=[Domain.Status.ACTIVE, Domain.Status.ERROR])
                .first()
            )
            if domain is None:
                return HttpResponseNotFound("این دامنه به CRM بیمه متصل نیست.")
            tenant = domain.tenant
            if request.path.startswith("/panel"):
                return HttpResponsePermanentRedirect(
                    f"{request.scheme}://{tenant.subdomain_host}{request.get_full_path()}"
                )
            request.host_kind = "tenant"
            request.urlconf = settings.URLCONF_TENANT

        request.tenant = tenant
        token = set_current_tenant(tenant)
        try:
            return self.get_response(request)
        finally:
            reset_current_tenant(token)


class HostCookieDomainMiddleware:
    """Share the session and CSRF cookies across bimcrm.ir and its subdomains, but not on agents' own domains.

    SESSION_COOKIE_DOMAIN/CSRF_COOKIE_DOMAIN are ".bimcrm.ir". A browser on alborz1234.ir rejects a cookie for
    that domain, which would break every form (quote request, customer login) on a connected custom domain.
    There the cookies are re-issued as host-only.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        host = request.get_host().split(":")[0].lower()
        platform = settings.PLATFORM_DOMAIN.lower()
        if host != platform and not host.endswith("." + platform):
            for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
                if name in response.cookies:
                    response.cookies[name]["domain"] = ""
        return response


class LiveDemoMiddleware:
    """The public demo office: everyone browses its panel as the demo owner, and nothing is ever saved."""

    NOTICE = "این نسخهٔ نمایشی است و تغییرات ذخیره نمی‌شود. برای دفتر خودتان، سایت و پنل رایگان بسازید."

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        request.live_demo = bool(tenant is not None and tenant.demo_built_on)
        if not request.live_demo:
            return self.get_response(request)
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.utils.http import url_has_allowed_host_and_scheme

        from apps.main.demo import refresh

        refresh(tenant)
        if request.path.startswith("/panel"):
            request.user = tenant.owner
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            messages.info(request, self.NOTICE)
            back = request.META.get("HTTP_REFERER", "")
            if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
                back = request.path
            return redirect(back)
        return self.get_response(request)
