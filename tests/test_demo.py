from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models import Tenant
from apps.core.tenancy import tenant_context
from apps.crm.models import Customer, Policy, QuoteRequest
from apps.main.demo import ensure_demo, rebuild, refresh

from .conftest import MAIN

DEMO = f"demo.{MAIN}"


@pytest.fixture
def demo(db):
    return ensure_demo()


def test_demo_page_builds_the_office_and_links_to_it(client, db):
    resp = client.get("/demo/", HTTP_HOST=MAIN)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert f"{DEMO}/panel/" in html and f"{DEMO}/account/" in html
    tenant = Tenant.objects.get(slug="demo")
    assert tenant.demo_built_on == timezone.localdate()
    with tenant_context(tenant):
        assert Customer.objects.count() >= 20
        assert Policy.objects.filter(end_date__lte=timezone.localdate() + timedelta(days=7)).exists()
        assert QuoteRequest.objects.filter(status="new").exists()
    # Visiting again does not build a second office.
    client.get("/demo/", HTTP_HOST=MAIN)
    assert Tenant.objects.filter(demo_built_on__isnull=False).count() == 1


def test_landing_menu_links_to_the_demo(client, db):
    html = client.get("/", HTTP_HOST=MAIN).content.decode()
    assert 'href="/demo/"' in html or "/demo/" in html


@pytest.mark.parametrize(
    "path",
    [
        "/panel/",
        "/panel/customers/",
        "/panel/quotes/",
        "/panel/policies/",
        "/panel/reports/",
        "/panel/claims/",
        "/panel/finance/installments/",
        "/panel/tasks/",
        "/panel/club/",
        "/panel/team/",
        "/panel/billing/",
    ],
)
def test_anyone_can_browse_the_demo_panel(client, demo, path):
    resp = client.get(path, HTTP_HOST=DEMO)
    assert resp.status_code == 200, path
    assert "پنل نمونه" in resp.content.decode()


def test_demo_saves_nothing(client, demo):
    with tenant_context(demo):
        before = Customer.objects.count(), QuoteRequest.objects.count()
    resp = client.post(
        "/panel/customers/new/",
        {"full_name": "تست", "mobile": "09121112233"},
        HTTP_HOST=DEMO,
        HTTP_REFERER=f"http://{DEMO}/panel/customers/",
    )
    assert resp.status_code == 302 and resp["Location"].endswith("/panel/customers/")
    resp = client.post("/quote/", {"full_name": "تست", "mobile": "09121112233"}, HTTP_HOST=DEMO)
    assert resp.status_code == 302
    with tenant_context(demo):
        assert (Customer.objects.count(), QuoteRequest.objects.count()) == before
    assert "نسخهٔ نمایشی" in client.get("/", HTTP_HOST=DEMO).content.decode()


def test_demo_customer_portal_is_open(client, demo):
    resp = client.get("/account/", HTTP_HOST=DEMO)
    assert resp.status_code == 200
    assert "مریم رضایی" in resp.content.decode()


def test_real_offices_are_untouched(client, tenant):
    resp = client.get("/panel/", HTTP_HOST=f"{tenant.slug}.{MAIN}")
    assert resp.status_code == 302  # still asks for login
    assert client.get("/account/", HTTP_HOST=f"{tenant.slug}.{MAIN}").status_code == 200


def test_dates_move_forward_once_a_day(demo):
    with tenant_context(demo):
        first = Policy.objects.order_by("pk").first()
    Tenant.objects.filter(pk=demo.pk).update(demo_built_on=demo.demo_built_on - timedelta(days=5))
    demo.refresh_from_db()
    assert refresh(demo) == 5
    assert refresh(demo) == 0
    with tenant_context(demo):
        moved = Policy.objects.get(pk=first.pk)
    assert moved.end_date == first.end_date + timedelta(days=5)


def test_demo_slug_is_reserved_and_rebuild_works(demo):
    from apps.core.models import is_subdomain_available

    assert is_subdomain_available("demo")[0] is False
    again = rebuild()
    assert again.pk != demo.pk and again.slug == "demo"
