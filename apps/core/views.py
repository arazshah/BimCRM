from django.conf import settings
from django.http import HttpResponse

from .dns import normalize_hostname
from .models import Domain, Tenant


def tls_ask(request):
    """Caddy on-demand TLS asks here before issuing a certificate: 200 = allowed, 404 = refuse.

    Allowed: the platform's own hosts, existing tenant subdomains, and agents' domains whose NS point here.
    This stops strangers from making the server request certificates for arbitrary names.
    """
    host = normalize_hostname(request.GET.get("domain", ""))
    base = settings.PLATFORM_DOMAIN.lower()
    if host in (base, f"admin.{base}"):
        return HttpResponse("ok")
    if host.endswith("." + base):
        ok = Tenant.objects.filter(slug=host[: -len(base) - 1]).exists()
    else:
        ok = Domain.objects.filter(hostname=host, status=Domain.Status.ACTIVE).exists()
    return HttpResponse("ok") if ok else HttpResponse("no", status=404)
