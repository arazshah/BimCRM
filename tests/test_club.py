from datetime import timedelta

import pytest
from django.core import signing
from django.utils import timezone

from apps.club.models import ClubSettings, PointEntry
from apps.core.models import InsuranceCompany, LineOfBusiness
from apps.core.tenancy import tenant_context
from apps.crm.models import Customer, Policy, QuoteRequest
from apps.crm.segments import SEGMENTS, cross_sell, customers_in
from apps.finance.models import Installment
from apps.messaging.models import Campaign
from apps.sites.models import SiteSettings
from apps.sites.views import CUSTOMER_COOKIE
from apps.work.models import Task

from .conftest import host
from .test_addons import ALL_ADDONS, enable, make_policy

pytestmark = pytest.mark.django_db


def test_points_tiers_renewal_and_installment(client, tenant, owner):
    p = make_policy(tenant, premium=300_000_000)  # 300 points -> silver (200)
    c = Customer.all_objects.get(pk=p.customer_id)
    assert c.points_balance == 300 and c.tier == "silver"
    with tenant_context(tenant):
        renewed = Policy.objects.create(
            customer=c,
            line=p.line,
            company=p.company,
            number="R1",
            start_date=p.end_date,
            end_date=p.end_date + timedelta(days=365),
            premium=200_000_000,
            renewed_from=p,
        )
    c.refresh_from_db()
    assert c.points_lifetime == 300 + 200 + 50 and c.tier == "gold"
    enable(tenant, "finance")
    with tenant_context(tenant):
        inst = Installment.objects.create(
            policy=renewed, due_date=timezone.localdate() + timedelta(days=3), amount=1000
        )
    client.force_login(owner)
    client.post(f"/panel/finance/installments/{inst.pk}/paid/", HTTP_HOST=host(tenant))
    assert PointEntry.all_objects.filter(reason="installment").count() == 1
    # redeem from the customer page; cannot overdraw
    client.post(f"/panel/customers/{c.pk}/points/", {"points": -100, "note": "تخفیف"}, HTTP_HOST=host(tenant))
    client.post(f"/panel/customers/{c.pk}/points/", {"points": -10_000, "note": "زیاد"}, HTTP_HOST=host(tenant))
    c.refresh_from_db()
    assert c.points_balance == 555 - 100 and c.tier == "gold"
    page = client.get(f"/panel/customers/{c.pk}/", HTTP_HOST=host(tenant)).content.decode()
    assert "طلایی" in page and "?c=" in page


def test_customer_referral_from_site_link(client, tenant, owner):
    p = make_policy(tenant)
    referrer = Customer.all_objects.get(pk=p.customer_id)
    from apps.club.services import referral_code_for

    code = referral_code_for(referrer)
    site = SiteSettings.all_objects.get(tenant=tenant)
    site.is_published = True
    site.save()
    site.lines.set(LineOfBusiness.objects.filter(slug="third-party"))
    client.get(f"/?c={code}", HTTP_HOST=host(tenant))
    client.post(
        "/quote/", {"line": "third-party", "full_name": "دوست", "mobile": "09125550099"}, HTTP_HOST=host(tenant)
    )
    q = QuoteRequest.all_objects.get(tenant=tenant)
    assert q.referrer == referrer
    client.force_login(owner)
    client.post(f"/panel/quotes/{q.pk}/", {"make_customer": "1"}, HTTP_HOST=host(tenant))
    friend = Customer.all_objects.get(mobile="09125550099")
    assert friend.referred_by == referrer and friend.source == Customer.Source.REFERRAL
    before = Customer.all_objects.get(pk=referrer.pk).points_balance
    make_policy(tenant, mobile="09125550099")
    assert Customer.all_objects.get(pk=referrer.pk).points_balance == before + 100


def test_segments_cross_sell_tasks_and_campaign(client, tenant, owner):
    enable(tenant, *ALL_ADDONS)
    make_policy(tenant)  # third-party only
    p2 = make_policy(tenant, mobile="09121234569")
    with tenant_context(tenant):
        Policy.objects.create(
            customer=p2.customer,
            line=LineOfBusiness.objects.get(slug="car-body"),
            company=InsuranceCompany.objects.first(),
            number="B1",
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=365),
            premium=1,
        )
        assert customers_in("tp_no_body").count() == 1
        assert customers_in("multi").count() == 1
        assert "بیمه بدنه خودرو" in cross_sell(Customer.objects.get(mobile="09121234567"))
        for s in SEGMENTS:
            customers_in(s.code).count()  # every segment query runs
    client.force_login(owner)
    h = host(tenant)
    assert "ثالث دارند، بدنه ندارند" in client.get("/panel/segments/", HTTP_HOST=h).content.decode()
    client.post(
        "/panel/segments/tp_no_body/tasks/",
        {"title": "پیشنهاد بدنه", "due_date": timezone.localdate().isoformat()},
        HTTP_HOST=h,
    )
    assert Task.all_objects.filter(tenant=tenant, title__startswith="پیشنهاد بدنه").count() == 1
    assert client.get("/panel/customers/?seg=tp_no_body", HTTP_HOST=h).status_code == 200
    resp = client.post(
        "/panel/campaigns/", {"title": "بدنه", "text": "سلام {name}", "segment": "tp_no_body"}, HTTP_HOST=h
    )
    camp = Campaign.all_objects.get(tenant=tenant)
    assert resp.status_code == 302 and camp.segment == "tp_no_body"
    from apps.messaging.services import campaign_recipients

    with tenant_context(tenant):
        assert campaign_recipients(camp).count() == 1
    assert client.get("/panel/club/", HTTP_HOST=h).status_code == 200


def test_portal_shows_club_card(client, tenant):
    make_policy(tenant, premium=50_000_000)
    client.cookies[CUSTOMER_COOKIE] = signing.dumps({"m": "09121234567"}, salt=f"customer:{tenant.pk}")
    page = client.get("/account/", HTTP_HOST=host(tenant)).content.decode()
    assert "امتیاز باشگاه مشتریان" in page and "wa.me" in page
    ClubSettings.objects.update_or_create(tenant=tenant, defaults={"enabled": False})
    assert "امتیاز باشگاه مشتریان" not in client.get("/account/", HTTP_HOST=host(tenant)).content.decode()
