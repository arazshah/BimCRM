from django.conf import settings


def platform(request):
    scheme = settings.PLATFORM_SCHEME
    return {
        "PLATFORM_DOMAIN": settings.PLATFORM_DOMAIN,
        "PLATFORM_URL": f"{scheme}://{settings.PLATFORM_DOMAIN}",
        "BRAND_NAME": "CRM بیمه",
        "current_tenant": getattr(request, "tenant", None),
    }
