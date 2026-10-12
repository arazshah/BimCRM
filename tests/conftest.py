import pytest

from apps.accounts.models import User
from apps.billing.models import StorageTier
from apps.billing.services import create_workspace

MAIN = "bimcrm.test"


@pytest.fixture(autouse=True)
def _settings(settings, tmp_path):
    settings.PLATFORM_DOMAIN = MAIN
    settings.SESSION_COOKIE_DOMAIN = None
    settings.SMS_BACKEND = "console"
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture
def owner(db):
    return User.objects.create_user("09120000001", full_name="مالک دفتر")


@pytest.fixture
def tenant(owner):
    return create_workspace(
        owner=owner,
        name="نمایندگی البرز ۱۲۳۴",
        slug="alborz1234",
        template="modern",
        storage_tier=StorageTier.objects.order_by("order").first(),
        addons={},
        period="monthly",
    )


@pytest.fixture
def other_tenant(db):
    user = User.objects.create_user("09120000002")
    return create_workspace(
        owner=user,
        name="دفتر دیگر",
        slug="other",
        template="etemad",
        storage_tier=StorageTier.objects.order_by("order").first(),
        addons={},
        period="monthly",
    )


def host(tenant):
    return f"{tenant.slug}.{MAIN}"
