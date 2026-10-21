"""Policyholder claims on the agent's own site: report, upload, sign, chat, follow; office side from the panel."""

import base64
import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.claims.models import Claim, ClaimDocRequest, ClaimDocument, ClaimFormFile, ClaimMessage
from apps.core.tenancy import tenant_context
from apps.sites.models import SiteSettings
from apps.work.models import Notification

from .conftest import host
from .test_addons import connect_sms, enable, make_policy, sent

pytestmark = pytest.mark.django_db

__all__ = ["sent"]


def png_data_url():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (60, 20), (0, 0, 0, 255)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def login_customer(client, tenant, monkeypatch, mobile):
    codes = {}
    monkeypatch.setattr("apps.sites.views.send_tenant_otp", lambda t, m, c: codes.update(code=c))
    h = host(tenant)
    client.post("/account/", {"mobile": mobile}, HTTP_HOST=h)
    client.post("/account/", {"code": codes["code"]}, HTTP_HOST=h)
    return h


def report(client, h, policy, **extra):
    data = {
        "policy": policy.pk,
        "incident_date": "2026-10-01",
        "incident_place": "اتوبان همت",
        "description": "تصادف از پشت در ترافیک اتوبان",
        "amount_claimed": "5,000,000",
        "iban": "IR" + "1" * 24,
        "declaration": "1",
        "signature_data": png_data_url(),
        **extra,
    }
    return client.post("/claims/new/", data, HTTP_HOST=h)


@pytest.fixture
def ready(tenant):
    enable(tenant, "claims")
    connect_sms(tenant)
    with tenant_context(tenant):
        SiteSettings.objects.update_or_create(tenant=tenant, defaults={"is_published": True, "hero_title": "x"})
    return make_policy(tenant, mobile="09124445566")


def test_public_page_and_login_redirect(client, tenant, ready, monkeypatch):
    h = host(tenant)
    assert "اعلام و پیگیری خسارت" in client.get("/claims/", HTTP_HOST=h).content.decode()
    r = client.get("/claims/new/", HTTP_HOST=h)  # not logged in -> SMS login, then back here
    assert r.status_code == 302 and r.url == "/account/"
    login = login_customer(client, tenant, monkeypatch, "09124445566")
    assert login == h
    assert client.get("/claims/new/", HTTP_HOST=h).status_code == 200


def test_claims_feature_required(client, tenant):
    assert client.get("/claims/", HTTP_HOST=host(tenant)).status_code == 404


def test_report_with_documents_and_signature(client, tenant, ready, monkeypatch, owner):
    h = login_customer(client, tenant, monkeypatch, "09124445566")
    bad = SimpleUploadedFile("x.exe", b"MZ")
    report(client, h, ready, report=[bad])
    assert not Claim.all_objects.filter(tenant=tenant).exists()  # a refused file blocks the report, nothing half-saved
    photo = SimpleUploadedFile("a.jpg", b"\xff\xd8\xff", content_type="image/jpeg")
    r = report(client, h, ready, photo=[photo])
    claim = Claim.all_objects.get(tenant=tenant)
    assert r.status_code == 302 and r.url == f"/claims/{claim.pk}/"
    assert claim.reported_by_customer and claim.office_unread and claim.amount_claimed == 5_000_000
    assert claim.signed_at and claim.iban.startswith("IR")
    kinds = sorted(ClaimDocument.objects.filter(claim=claim).values_list("kind", flat=True))
    assert kinds == ["photo", "signature"]
    assert Notification.all_objects.filter(tenant=tenant, text__contains="خسارت تازه").exists()
    page = client.get(f"/claims/{claim.pk}/", HTTP_HOST=h).content.decode()
    assert "اعلام شد" in page and claim.code[-3:] in page


def test_report_validation(client, tenant, ready, monkeypatch):
    h = login_customer(client, tenant, monkeypatch, "09124445566")
    report(client, h, ready, declaration="")
    report(client, h, ready, signature_data="")
    report(client, h, ready, description="کوتاه")
    report(client, h, ready, incident_date="2999-01-01")
    report(client, h, ready, signature_data="data:image/png;base64,AAAA")
    assert not Claim.all_objects.filter(tenant=tenant).exists()
    # a signed paper form replaces the drawn signature
    pdf = SimpleUploadedFile("form.pdf", b"%PDF-1.4")
    report(client, h, ready, signature_data="", form=[pdf])
    assert Claim.all_objects.filter(tenant=tenant).count() == 1


def test_cannot_report_on_someone_elses_policy_or_open_their_claim(client, tenant, ready, monkeypatch):
    other = make_policy(tenant, mobile="09124445577")
    with tenant_context(tenant):
        foreign = Claim.objects.create(policy=other, incident_date=date(2026, 9, 1), description="x" * 20)
    h = login_customer(client, tenant, monkeypatch, "09124445566")
    report(client, h, other)
    assert Claim.all_objects.filter(policy=other).count() == 1
    assert client.get(f"/claims/{foreign.pk}/", HTTP_HOST=h).status_code == 404
    assert client.post(f"/claims/{foreign.pk}/message/", {"text": "سلام!"}, HTTP_HOST=h).status_code == 404
    pdf = SimpleUploadedFile("a.pdf", b"%PDF")
    assert client.post(f"/claims/{foreign.pk}/upload/", {"file": pdf}, HTTP_HOST=h).status_code == 404


def test_customer_upload_message_sign_and_file_access(client, tenant, ready, monkeypatch):
    h = login_customer(client, tenant, monkeypatch, "09124445566")
    report(client, h, ready, signature_data="", form=[SimpleUploadedFile("f.pdf", b"%PDF-1.4")])
    claim = Claim.all_objects.get(tenant=tenant)
    assert claim.signed_at is None
    Claim.all_objects.filter(pk=claim.pk).update(office_unread=False)
    pdf = SimpleUploadedFile("kroki.pdf", b"%PDF-1.4")
    client.post(f"/claims/{claim.pk}/upload/", {"file": [pdf], "kind": "report", "title": "کروکی"}, HTTP_HOST=h)
    claim.refresh_from_db()
    assert claim.office_unread
    doc = ClaimDocument.objects.get(claim=claim, title="کروکی")
    assert client.get(f"/claims/{claim.pk}/file/{doc.pk}/", HTTP_HOST=h).status_code == 200
    client.post(f"/claims/{claim.pk}/message/", {"text": "کی بازدید می‌کنید؟"}, HTTP_HOST=h)
    assert ClaimMessage.objects.filter(claim=claim, by_customer=True).count() == 1
    client.post(f"/claims/{claim.pk}/sign/", {"declaration": "1", "signature_data": png_data_url()}, HTTP_HOST=h)
    claim.refresh_from_db()
    assert claim.signed_at
    client.get("/account/logout/", HTTP_HOST=h)
    assert client.get(f"/claims/{claim.pk}/file/{doc.pk}/", HTTP_HOST=h).status_code in (302, 404)


def test_office_requests_docs_and_replies(client, tenant, owner, ready, monkeypatch, sent):
    h = login_customer(client, tenant, monkeypatch, "09124445566")
    report(client, h, ready)
    claim = Claim.all_objects.get(tenant=tenant)
    customer_client = client
    from django.test import Client

    office = Client()
    office.force_login(owner)
    office.post(
        f"/panel/claims/{claim.pk}/",
        {"request_docs": "1", "titles": "کارت خودرو\nگواهینامه", "note": "عکس واضح"},
        HTTP_HOST=h,
    )
    claim.refresh_from_db()
    assert claim.status == "docs_needed" and ClaimDocRequest.objects.filter(claim=claim, done=False).count() == 2
    assert any("کارت خودرو" in text for _, text in sent)
    page = customer_client.get(f"/claims/{claim.pk}/", HTTP_HOST=h).content.decode()
    assert "کارت خودرو" in page and "مدارک خواسته‌شده از شما" in page
    req = ClaimDocRequest.objects.get(claim=claim, title="کارت خودرو")
    customer_client.post(
        f"/claims/{claim.pk}/upload/",
        {"request": req.pk, "file": [SimpleUploadedFile("c.jpg", b"\xff\xd8\xff")]},
        HTTP_HOST=h,
    )
    req.refresh_from_db()
    assert req.done and ClaimDocument.objects.filter(request=req).exists()
    office.post(f"/panel/claims/{claim.pk}/", {"reply": "1", "text": "مدارک کامل شد"}, HTTP_HOST=h)
    assert ClaimMessage.objects.filter(claim=claim, by_customer=False).exists()
    assert "مدارک کامل شد" in customer_client.get(f"/claims/{claim.pk}/", HTTP_HOST=h).content.decode()
    # opening the claim in the panel clears the "new from customer" flag
    office.get(f"/panel/claims/{claim.pk}/", HTTP_HOST=h)
    claim.refresh_from_db()
    assert not claim.office_unread


def test_forms_managed_in_panel_shown_on_site(client, tenant, owner, ready):
    from django.test import Client

    office = Client()
    office.force_login(owner)
    h = host(tenant)
    pdf = SimpleUploadedFile("form.pdf", b"%PDF-1.4")
    office.post(
        "/panel/claims/forms/", {"title": "فرم اعلام خسارت", "file": pdf, "instructions": "چاپ و امضا"}, HTTP_HOST=h
    )
    item = ClaimFormFile.all_objects.get(tenant=tenant)
    assert "فرم اعلام خسارت" in client.get("/claims/", HTTP_HOST=h).content.decode()
    assert client.get(item.file.url, HTTP_HOST=h).status_code == 200  # blank forms are public
    office.post(f"/panel/claims/forms/{item.pk}/delete/", HTTP_HOST=h)
    assert not ClaimFormFile.all_objects.filter(tenant=tenant).exists()
