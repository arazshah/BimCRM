from django.conf import settings
from django.utils.functional import SimpleLazyObject


def platform(request):
    scheme = settings.PLATFORM_SCHEME
    return {
        "PLATFORM_DOMAIN": settings.PLATFORM_DOMAIN,
        "PLATFORM_URL": f"{scheme}://{settings.PLATFORM_DOMAIN}",
        "BRAND_NAME": "CRM بیمه",
        "current_tenant": getattr(request, "tenant", None),
        # Lazy: only queried by templates that use it (the main site's base).
        "PLATFORM_SETTINGS": SimpleLazyObject(_load_settings),
    }


def _load_settings():
    from .models import PlatformSettings

    return PlatformSettings.load()
