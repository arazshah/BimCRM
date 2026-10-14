import pytest

from apps.accounts.models import Membership, User
from apps.billing.models import Addon, Package, StorageTier

from .conftest import MAIN, host


@pytest.fixture
def plans(db):
    return {p.name: p for p in Package.plans()}


def test_three_plans_seeded_with_recommended_middle(plans):
    assert list(plans) == ["شروع", "حرفه‌ای", "دفتر بزرگ"]
    assert plans["حرفه‌ای"].is_recommended and not plans["شروع"].is_recommended
    assert plans["شروع"].included_codes() == set()
    assert {"marketers", "branches"} <= plans["دفتر بزرگ"].included_codes()
    assert not Addon.objects.get(code="premium_template").is_active


@pytest.mark.django_db
def test_landing_shows_cards_comparison_and_plain_answers(client, plans):
    page = client.get("/", HTTP_HOST=MAIN).content.decode()
    for name in plans:
        assert f"<h3>{name}</h3>" in page
    assert "پیشنهاد ما" in page and "مقایسه کامل پکیج‌ها" in page
    assert "فضای فایل یعنی چه" in page and "همه امکانات «شروع»، به‌علاوه:" in page


@pytest.mark.django_db
def test_change_plan_unlocks_features_and_drops_redundant_items(client, tenant, owner, plans):
    sub = tenant.subscription
    finance = Addon.objects.get(code="finance")
    sub.items.create(addon=finance, quantity=1)
    assert sub.renewal_amount("monthly") == plans["شروع"].monthly_price + finance.monthly_price
    client.force_login(owner)
    locked = client.get("/panel/claims/", HTTP_HOST=host(tenant))
    assert locked.status_code == 402 and "«حرفه‌ای»" in locked.content.decode()
    client.post("/panel/billing/", {"change_plan": plans["حرفه‌ای"].pk}, HTTP_HOST=host(tenant))
    sub.refresh_from_db()
    assert sub.package == plans["حرفه‌ای"] and sub.storage_tier == plans["حرفه‌ای"].storage_tier
    assert not sub.items.filter(addon=finance).exists()
    assert sub.renewal_amount("monthly") == plans["حرفه‌ای"].monthly_price
    assert client.get("/panel/claims/", HTTP_HOST=host(tenant)).status_code == 200


@pytest.mark.django_db
def test_cannot_downgrade_below_team_size(client, tenant, owner, plans):
    sub = tenant.subscription
    sub.package = plans["حرفه‌ای"]
    sub.save()
    for i in range(2):
        u = User.objects.create_user(f"0912333000{i}")
        Membership.objects.create(user=u, tenant=tenant, role=Membership.Role.STAFF)
    client.force_login(owner)
    resp = client.post("/panel/billing/", {"change_plan": plans["شروع"].pk}, HTTP_HOST=host(tenant), follow=True)
    sub.refresh_from_db()
    assert sub.package == plans["حرفه‌ای"] and "همکار" in resp.content.decode()


@pytest.mark.django_db
def test_extra_storage_charged_as_difference(client, tenant, owner, plans):
    sub = tenant.subscription
    big = StorageTier.objects.order_by("-storage_mb").first()
    client.force_login(owner)
    client.post("/panel/billing/", {"storage_tier": big.pk, "addon_extra_user": "2"}, HTTP_HOST=host(tenant))
    sub.refresh_from_db()
    base = plans["شروع"].storage_tier
    user = Addon.objects.get(code="extra_user")
    expected = plans["شروع"].monthly_price + (big.monthly_price - base.monthly_price) + 2 * user.monthly_price
    assert sub.storage_tier == big and sub.renewal_amount("monthly") == expected and sub.user_limit() == 3
    page = client.get("/panel/billing/", HTTP_HOST=host(tenant)).content.decode()
    assert "پکیج فعلی شما" in page and "تغییر به «حرفه‌ای»" in page


@pytest.mark.django_db
def test_billing_suggests_cheaper_plan_for_many_addons(client, tenant, owner, plans):
    sub = tenant.subscription
    for code in ["finance", "claims", "sms_campaigns", "advanced_reports", "marketers", "branches"]:
        sub.items.create(addon=Addon.objects.get(code=code), quantity=1)
    from apps.billing.pricing import cheaper_plan

    tip = cheaper_plan(sub)
    assert tip["plan"] == plans["دفتر بزرگ"]
    assert tip["saving"] == sub.renewal_amount("monthly") - plans["دفتر بزرگ"].monthly_price
    client.force_login(owner)
    assert "صرفه‌جویی ماهانه" in client.get("/panel/billing/", HTTP_HOST=host(tenant)).content.decode()


@pytest.mark.django_db
def test_feature_explorer_badges_follow_the_packages(client, plans):
    from apps.main import features

    cats, total = features.explorer(list(plans.values()))
    items = {it["f"].title: it for c in cats for it in c["items"]}
    assert total == len(items) >= 30
    assert items["پرونده کامل مشتری"]["badge"] == "همه پکیج‌ها"
    assert items["اقساط و چک"]["badge"] == "حرفه‌ای و بالاتر"
    assert items["چند شعبه"]["badge"] == "دفتر بزرگ"
    page = client.get("/", HTTP_HOST=MAIN).content.decode()
    assert "همه امکانات، به زبان ساده" in page and page.count('class="fx-card"') == total
    for c in cats:
        for it in c["items"]:
            assert client.get(f"/help/{it['f'].help}/", HTTP_HOST=MAIN).status_code == 200


@pytest.mark.django_db
def test_landing_offers_a_free_start_before_the_paid_plans(client, plans):
    page = client.get("/", HTTP_HOST=MAIN).content.decode()
    assert "<h3>شروع رایگان</h3>" in page and "اطلاعاتتان می‌ماند" in page
    assert page.index("<h3>شروع رایگان</h3>") < page.index("<h3>شروع</h3>")


@pytest.mark.django_db
def test_suggested_plan_follows_what_the_office_used(tenant, plans):
    from datetime import date

    from apps.billing.pricing import suggested_plan
    from apps.claims.models import Claim
    from apps.core.models import InsuranceCompany, LineOfBusiness
    from apps.core.tenancy import tenant_context
    from apps.crm.models import Customer, Policy

    assert suggested_plan(tenant)["plan"] == plans["شروع"]
    with tenant_context(tenant):
        c = Customer.objects.create(full_name="مشتری", mobile="09121112233")
        p = Policy.objects.create(
            customer=c,
            line=LineOfBusiness.objects.first(),
            company=InsuranceCompany.objects.first(),
            number="1",
            start_date=date(2026, 1, 1),
            end_date=date(2027, 1, 1),
        )
        Claim.objects.create(policy=p, incident_date=date(2026, 5, 1), description="تصادف")
    got = suggested_plan(tenant)
    assert got["plan"] == plans["حرفه‌ای"] and "پرونده خسارت داشتید" in got["reasons"]


@pytest.mark.django_db
def test_dashboard_nudges_in_the_last_trial_days(client, tenant, owner, plans):
    from datetime import timedelta

    from django.utils import timezone

    sub = tenant.subscription
    client.force_login(owner)
    assert "از دورهٔ رایگان مانده" not in client.get("/panel/", HTTP_HOST=host(tenant)).content.decode()
    sub.current_period_end = timezone.now() + timedelta(days=3, hours=1)
    sub.save()
    page = client.get("/panel/", HTTP_HOST=host(tenant)).content.decode()
    assert "۳ روز از دورهٔ رایگان مانده" in page and "«شروع»" in page
    billing = client.get("/panel/billing/", HTTP_HOST=host(tenant)).content.decode()
    assert "پیشنهاد ما برای دفتر شما" in billing and "دورهٔ رایگان تا" in billing
