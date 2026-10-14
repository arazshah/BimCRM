import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Membership, User
from apps.core.models import LineOfBusiness
from apps.core.tenancy import tenant_context
from apps.crm.models import CustomerDocument, QuoteRequest
from apps.work.models import Notification

from .conftest import host
from .test_addons import ALL_ADDONS, enable, make_policy

pytestmark = pytest.mark.django_db


def pdf(name="a.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")


def test_required_docs_seeded():
    assert "car_card" in LineOfBusiness.objects.get(slug="car-body").required_docs


def test_panel_document_upload_checklist_and_access(client, tenant, owner, other_tenant):
    p = make_policy(tenant)
    c = p.customer
    client.force_login(owner)
    h = host(tenant)
    page = client.get(f"/panel/customers/{c.pk}/", HTTP_HOST=h).content.decode()
    assert "کارت خودرو" in page and "doc-check" in page  # third-party needs a car card
    resp = client.post(
        f"/panel/customers/{c.pk}/documents/", {"kind": "car_card", "policy": p.pk, "file": pdf()}, HTTP_HOST=h
    )
    assert resp.status_code == 302
    doc = CustomerDocument.all_objects.get(tenant=tenant)
    assert doc.kind == "car_card" and doc.uploaded_by == owner and doc.size > 0
    assert client.get("/media/" + doc.file.name, HTTP_HOST=h).status_code == 200
    client.post(
        f"/panel/customers/{c.pk}/documents/",
        {"kind": "other", "file": SimpleUploadedFile("x.exe", b"MZ")},
        HTTP_HOST=h,
    )
    assert CustomerDocument.all_objects.count() == 1
    client.post(f"/panel/customers/{c.pk}/documents/{doc.pk}/delete/", HTTP_HOST=h)
    assert not CustomerDocument.all_objects.exists()


def test_customer_uploads_document_from_portal(client, tenant, owner):
    with tenant_context(tenant):
        QuoteRequest.objects.create(
            line=LineOfBusiness.objects.get(slug="car-body"), full_name="نگار", mobile="09127773344"
        )
    from django.core import signing

    from apps.sites.views import CUSTOMER_COOKIE

    client.cookies[CUSTOMER_COOKIE] = signing.dumps({"m": "09127773344"}, salt=f"customer:{tenant.pk}")
    page = client.get("/account/", HTTP_HOST=host(tenant)).content.decode()
    assert "عکس خودرو" in page and "/account/documents/" in page
    client.post("/account/documents/", {"kind": "car_card", "file": pdf()}, HTTP_HOST=host(tenant))
    doc = CustomerDocument.all_objects.get(tenant=tenant)
    assert doc.by_customer and doc.customer.mobile == "09127773344"
    assert QuoteRequest.all_objects.get(tenant=tenant).customer == doc.customer
    assert Notification.all_objects.filter(user=owner, text__contains="مدرک فرستاد").exists()


def test_staff_permissions(client, tenant, owner):
    enable(tenant, *ALL_ADDONS)
    u = User.objects.create_user("09120000088", full_name="کارمند")
    m = Membership.objects.create(user=u, tenant=tenant, role=Membership.Role.STAFF)
    client.force_login(u)
    h = host(tenant)
    assert client.get("/panel/finance/installments/", HTTP_HOST=h).status_code == 200
    assert client.get("/panel/campaigns/", HTTP_HOST=h).status_code == 403  # off by default
    assert client.get("/panel/reminders/", HTTP_HOST=h).status_code == 403
    page = client.get("/panel/", HTTP_HOST=h).content.decode()
    nav = page[page.index('class="side-nav"') : page.index("</nav>", page.index('class="side-nav"'))]
    assert "/panel/campaigns/" not in nav and "/panel/integrations/" not in nav
    client.force_login(owner)
    client.post("/panel/team/", {"set_perms": m.pk, "perm": ["campaigns", "claims"]}, HTTP_HOST=h)
    m.refresh_from_db()
    assert m.can("campaigns") and m.can("claims") and not m.can("finance") and not m.can("reports")
    client.force_login(u)
    assert client.get("/panel/campaigns/", HTTP_HOST=h).status_code == 200
    assert client.get("/panel/finance/installments/", HTTP_HOST=h).status_code == 403
    assert client.get("/panel/reports/", HTTP_HOST=h).status_code == 403
