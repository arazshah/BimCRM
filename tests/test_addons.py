from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.accounts.sms import SmsError
from apps.billing.models import Addon, SubscriptionItem
from apps.claims.models import Claim, ClaimDocument
from apps.core import jalali
from apps.core.models import InsuranceCompany, LineOfBusiness
from apps.core.tenancy import tenant_context
from apps.crm.models import Customer, Policy, QuoteRequest
from apps.finance.models import CommissionRule, Installment, LedgerEntry
from apps.integrations.models import Integration
from apps.messaging.models import Campaign, MessageLog, ReminderSettings
from apps.messaging.services import run_campaign, send_all_daily_reminders, send_daily_reminders
from apps.network.models import Marketer
from apps.sites.models import SiteSettings

from .conftest import host

pytestmark = pytest.mark.django_db

ALL_ADDONS = ["finance", "claims", "marketers", "sms_campaigns", "advanced_reports"]


def enable(tenant, *codes):
    for code in codes:
        SubscriptionItem.objects.get_or_create(subscription=tenant.subscription, addon=Addon.objects.get(code=code))


def connect_sms(tenant):
    with tenant_context(tenant):
        integ = Integration(kind="sms", provider="smsir")
        integ.config = {"api_key": "k"}
        integ.save()


@pytest.fixture
def sent(monkeypatch):
    """Captures SMS the office's own panel would send."""
    out = []
    monkeypatch.setattr("apps.messaging.services.send_tenant_text", lambda t, m, text: out.append((m, text)))
    return out


def make_policy(tenant, mobile="09121234567", name="رضا", end=None, premium=10_000_000, **extra):
    end = end or timezone.localdate() + timedelta(days=200)
    with tenant_context(tenant):
        customer, _ = Customer.objects.get_or_create(mobile=mobile, defaults={"full_name": name, **extra})
        return Policy.objects.create(
            customer=customer,
            line=LineOfBusiness.objects.get(slug="third-party"),
            company=InsuranceCompany.objects.get(name="بیمه البرز"),
            number=f"P-{mobile[-4:]}-{end.isoformat()}",
            start_date=end - timedelta(days=365),
            end_date=end,
            premium=premium,
        )


# ---------- Gating ----------


def test_addon_pages_are_locked_without_the_addon(client, tenant, owner):
    client.force_login(owner)
    for path in ["finance/", "claims/", "marketers/", "campaigns/", "reports/"]:
        resp = client.get(f"/panel/{path}", HTTP_HOST=host(tenant))
        assert resp.status_code == 402, path
        assert "اشتراک" in resp.content.decode()


def test_all_addon_pages_render_with_addons(client, tenant, owner):
    enable(tenant, *ALL_ADDONS)
    policy = make_policy(tenant)
    with tenant_context(tenant):
        claim = Claim.objects.create(policy=policy, incident_date=date(2026, 9, 1), description="تصادف از عقب")
        marketer = Marketer.objects.create(full_name="بازاریاب", mobile="09125550000")
        campaign = Campaign.objects.create(title="نوروز", text="سلام {name}")
    client.force_login(owner)
    paths = [
        "reminders/",
        "finance/",
        "finance/?m=-2",
        "finance/installments/",
        "finance/installments/plan/",
        "finance/commissions/",
        "finance/ledger/",
        "claims/",
        "claims/new/",
        f"claims/{claim.pk}/",
        f"claims/{claim.pk}/edit/",
        "marketers/",
        "marketers/new/",
        f"marketers/{marketer.pk}/",
        "campaigns/",
        f"campaigns/{campaign.pk}/",
        "reports/",
        f"customers/{policy.customer_id}/",
        "",
    ]
    for path in paths:
        assert client.get(f"/panel/{path}", HTTP_HOST=host(tenant)).status_code == 200, path


def test_addon_fields_only_with_addon(client, tenant, owner):
    client.force_login(owner)
    page = client.get("/panel/policies/new/", HTTP_HOST=host(tenant)).content.decode()
    assert 'name="commission_rate"' not in page and 'name="marketer"' not in page
    enable(tenant, "finance", "marketers")
    page = client.get("/panel/policies/new/", HTTP_HOST=host(tenant)).content.decode()
    assert 'name="commission_rate"' in page and 'name="marketer"' in page


# ---------- Finance ----------


def test_jalali_months():
    # 31 Shahrivar 1405 + 1 month -> 30 Mehr 1405 (Mehr has 30 days)
    assert jalali.add_months(date(2026, 9, 22), 1) == date(2026, 10, 22)
    start, end, label = jalali.month_bounds(date(2026, 10, 13))
    assert (start, end) == (date(2026, 9, 23), date(2026, 10, 23)) and label == "مهر ۱۴۰۵"
    start, _, label = jalali.month_bounds(date(2026, 10, 13), -7)
    assert label == "اسفند ۱۴۰۴" and start == date(2026, 2, 20)


def test_installment_plan_and_payment(client, tenant, owner):
    enable(tenant, "finance")
    policy = make_policy(tenant)
    client.force_login(owner)
    h = host(tenant)
    client.post(
        "/panel/finance/installments/plan/",
        {"policy": policy.pk, "total": 10_000_001, "count": 3, "first_due": "2026-10-22", "method": "cheque"},
        HTTP_HOST=h,
    )
    with tenant_context(tenant):
        items = list(Installment.objects.order_by("due_date"))
    assert [i.amount for i in items] == [3_333_333, 3_333_333, 3_333_335]
    assert [i.due_date for i in items] == [date(2026, 10, 22), date(2026, 11, 21), date(2026, 12, 21)]
    resp = client.post(f"/panel/finance/installments/{items[0].pk}/paid/", {"next": "https://evil.com/"}, HTTP_HOST=h)
    assert "evil.com" not in resp["Location"]
    items[0].refresh_from_db()
    assert items[0].status == "paid" and items[0].paid_at == timezone.localdate()


def test_commission_rules_pick_most_specific(tenant):
    alborz = InsuranceCompany.objects.get(name="بیمه البرز")
    third = LineOfBusiness.objects.get(slug="third-party")
    with tenant_context(tenant):
        CommissionRule.objects.create(rate=Decimal("5"))
        CommissionRule.objects.create(line=third, rate=Decimal("6"))
        p = make_policy(tenant)
        assert p.commission_rate == Decimal("6") and p.commission_expected == 600_000
        CommissionRule.objects.create(company=alborz, line=third, rate=Decimal("7.5"))
        p2 = make_policy(tenant, mobile="09121234568")
        assert p2.commission_rate == Decimal("7.5")
        life = make_policy(tenant, mobile="09121234569")
        life.line = LineOfBusiness.objects.get(slug="life")
        life.commission_rate = None
        life.save()
        assert life.commission_rate == Decimal("5")


def test_receiving_commission_writes_ledger(client, tenant, owner):
    enable(tenant, "finance")
    policy = make_policy(tenant)
    client.force_login(owner)
    client.post(f"/panel/finance/commissions/{policy.pk}/receive/", {"amount": 450_000}, HTTP_HOST=host(tenant))
    policy.refresh_from_db()
    assert policy.commission_received == 450_000
    with tenant_context(tenant):
        entry = LedgerEntry.objects.get()
    assert entry.kind == "income" and entry.category == "commission" and entry.amount == 450_000
    page = client.get("/panel/finance/", HTTP_HOST=host(tenant)).content.decode()
    assert "۴۵۰٬۰۰۰" in page


def test_finance_is_isolated_between_offices(client, tenant, other_tenant, owner):
    enable(tenant, "finance")
    foreign = make_policy(other_tenant)
    with tenant_context(other_tenant):
        inst = Installment.objects.create(policy=foreign, due_date=date(2026, 1, 1), amount=1)
    client.force_login(owner)
    assert client.get(f"/panel/finance/installments/{inst.pk}/", HTTP_HOST=host(tenant)).status_code == 404
    assert client.post(f"/panel/finance/installments/{inst.pk}/paid/", HTTP_HOST=host(tenant)).status_code == 404


# ---------- Marketers ----------


def test_marketer_referral_to_policy_and_commission(client, tenant, owner):
    enable(tenant, "marketers")
    site = SiteSettings.all_objects.get(tenant=tenant)
    site.is_published = True
    site.save()
    site.lines.set(LineOfBusiness.objects.filter(slug="third-party"))
    with tenant_context(tenant):
        lead = Marketer.objects.create(
            full_name="سرگروه", mobile="09125550001", rate=Decimal("2"), override_rate=Decimal("1")
        )
        rep = Marketer.objects.create(full_name="بازاریاب", mobile="09125550002", parent=lead, rate=Decimal("3"))
    client.get(f"/?ref={rep.code}", HTTP_HOST=host(tenant))
    client.post(
        "/quote/", {"line": "third-party", "full_name": "مشتری معرفی", "mobile": "09127770000"}, HTTP_HOST=host(tenant)
    )
    quote = QuoteRequest.all_objects.get(tenant=tenant)
    assert quote.marketer == rep
    client.force_login(owner)
    client.post(f"/panel/quotes/{quote.pk}/", {"make_customer": "1"}, HTTP_HOST=host(tenant))
    with tenant_context(tenant):
        customer = Customer.objects.get(mobile="09127770000")
    assert customer.marketer == rep
    policy = make_policy(tenant, mobile="09127770000", premium=20_000_000)
    assert policy.marketer == rep  # inherited from the customer
    assert rep.earned() == 600_000  # 3% own
    assert lead.earned() == 200_000  # 1% override on the direct child's policy


def test_referral_ignored_without_addon(client, tenant):
    site = SiteSettings.all_objects.get(tenant=tenant)
    site.is_published = True
    site.save()
    site.lines.set(LineOfBusiness.objects.filter(slug="third-party"))
    with tenant_context(tenant):
        rep = Marketer.objects.create(full_name="x", mobile="09125550003")
    client.get(f"/?ref={rep.code}", HTTP_HOST=host(tenant))
    client.post("/quote/", {"line": "third-party", "full_name": "y", "mobile": "09127770001"}, HTTP_HOST=host(tenant))
    assert QuoteRequest.all_objects.get(tenant=tenant).marketer is None


def test_marketer_cannot_be_own_parent(client, tenant, owner):
    enable(tenant, "marketers")
    with tenant_context(tenant):
        a = Marketer.objects.create(full_name="a", mobile="09125550004")
        b = Marketer.objects.create(full_name="b", mobile="09125550005", parent=a)
    client.force_login(owner)
    resp = client.post(
        f"/panel/marketers/{a.pk}/edit/",
        {
            "full_name": "a",
            "mobile": "09125550004",
            "parent": b.pk,
            "rate": "2",
            "override_rate": "0.5",
            "is_active": "on",
        },
        HTTP_HOST=host(tenant),
    )
    assert resp.status_code == 200 and "زیرمجموعه" in resp.content.decode()


# ---------- Claims ----------


def test_claim_lifecycle_in_panel(client, tenant, owner, sent):
    enable(tenant, "claims")
    connect_sms(tenant)
    policy = make_policy(tenant)
    client.force_login(owner)
    h = host(tenant)
    client.post(
        "/panel/claims/new/",
        {"policy": policy.pk, "incident_date": "2026-10-01", "description": "تصادف", "amount_claimed": 5_000_000},
        HTTP_HOST=h,
    )
    claim = Claim.all_objects.get(tenant=tenant)
    client.post(f"/panel/claims/{claim.pk}/", {"status": "docs_needed", "note": "کروکی را بفرستید"}, HTTP_HOST=h)
    claim.refresh_from_db()
    assert claim.status == "docs_needed" and claim.events.count() == 2
    assert sent and "کروکی" in sent[-1][1] and sent[-1][0] == "09121234567"


def test_customer_reports_claim_and_uploads(client, tenant, monkeypatch):
    enable(tenant, "claims")
    connect_sms(tenant)
    policy = make_policy(tenant, mobile="09124445566")
    other = make_policy(tenant, mobile="09124445577")
    with tenant_context(tenant):
        foreign_claim = Claim.objects.create(policy=other, incident_date=date(2026, 9, 1), description="x" * 20)
    codes = {}
    monkeypatch.setattr("apps.sites.views.send_tenant_otp", lambda t, m, c: codes.update(code=c))
    h = host(tenant)
    client.post("/account/", {"mobile": "09124445566"}, HTTP_HOST=h)
    client.post("/account/", {"code": codes["code"]}, HTTP_HOST=h)
    client.post(
        "/account/claims/report/",
        {"policy": other.pk, "incident_date": "2026-10-01", "description": "خسارت روی بیمه‌نامه دیگری"},
        HTTP_HOST=h,
    )
    assert Claim.all_objects.filter(policy=other).count() == 1  # not someone else's policy
    client.post(
        "/account/claims/report/",
        {"policy": policy.pk, "incident_date": "2026-10-01", "description": "تصادف در اتوبان همت"},
        HTTP_HOST=h,
    )
    claim = Claim.all_objects.get(policy=policy)
    assert claim.reported_by_customer
    pdf = SimpleUploadedFile("kroki.pdf", b"%PDF-1.4", content_type="application/pdf")
    client.post(f"/account/claims/{claim.pk}/upload/", {"title": "کروکی", "file": pdf}, HTTP_HOST=h)
    exe = SimpleUploadedFile("x.exe", b"MZ")
    client.post(f"/account/claims/{claim.pk}/upload/", {"file": exe}, HTTP_HOST=h)
    stolen = SimpleUploadedFile("a.pdf", b"%PDF")
    client.post(f"/account/claims/{foreign_claim.pk}/upload/", {"file": stolen}, HTTP_HOST=h)
    assert list(ClaimDocument.objects.values_list("title", "claim_id")) == [("کروکی", claim.pk)]
    assert "مدارک فرستاده‌شده: کروکی" in client.get("/account/", HTTP_HOST=h).content.decode()


# ---------- Reminders ----------


def test_renewal_reminders_once_per_window(tenant, sent):
    connect_sms(tenant)
    today = timezone.localdate()
    make_policy(tenant, end=today + timedelta(days=30))
    make_policy(tenant, mobile="09121112222", end=today + timedelta(days=29))
    assert send_all_daily_reminders(today) == 1
    assert "۳۰ روز" in sent[0][1] and sent[0][0] == "09121234567"
    assert send_all_daily_reminders(today) == 0  # same day again: nothing new
    assert MessageLog.all_objects.filter(tenant=tenant, kind="renewal").count() == 1


def test_renewed_policy_gets_no_reminder(tenant, sent):
    connect_sms(tenant)
    today = timezone.localdate()
    old = make_policy(tenant, end=today + timedelta(days=15))
    with tenant_context(tenant):
        renewal = make_policy(tenant, end=today + timedelta(days=380))
        renewal.renewed_from = old
        renewal.save()
    assert send_all_daily_reminders(today) == 0


def test_failed_sms_is_retried(tenant, monkeypatch):
    connect_sms(tenant)
    today = timezone.localdate()
    make_policy(tenant, end=today + timedelta(days=3))

    def fail(*a):
        raise SmsError("no credit")

    monkeypatch.setattr("apps.messaging.services.send_tenant_text", fail)
    with tenant_context(tenant):
        send_daily_reminders(tenant, today)
    log = MessageLog.all_objects.get(tenant=tenant)
    assert not log.ok and "credit" in log.error
    monkeypatch.setattr("apps.messaging.services.send_tenant_text", lambda *a: None)
    with tenant_context(tenant):
        assert send_daily_reminders(tenant, today) == 1
    log.refresh_from_db()
    assert log.ok and log.error == ""


def test_no_reminders_without_office_sms_panel(tenant, sent):
    make_policy(tenant, end=timezone.localdate() + timedelta(days=30))
    assert send_all_daily_reminders() == 0 and not sent


def test_installment_and_birthday_reminders(tenant, sent):
    connect_sms(tenant)
    today = timezone.localdate()
    policy = make_policy(tenant, birth_date=date(1990, today.month, today.day))
    with tenant_context(tenant):
        Installment.objects.create(policy=policy, due_date=today + timedelta(days=3), amount=2_500_000)
        cfg = ReminderSettings.objects.create(birthday_enabled=True)
    with tenant_context(tenant):
        send_daily_reminders(tenant, today)
    kinds = set(MessageLog.all_objects.values_list("kind", flat=True))
    assert kinds == {"birthday"}  # installment reminders need the finance add-on
    enable(tenant, "finance")
    with tenant_context(tenant):
        send_daily_reminders(tenant, today)
    assert "۲٬۵۰۰٬۰۰۰" in sent[-1][1]
    assert cfg.parse_days("۳۰، 15 ,x, 3") == [30, 15, 3]


# ---------- Campaigns and reports ----------


def test_campaign_skips_opted_out(tenant, sent):
    connect_sms(tenant)
    make_policy(tenant, mobile="09120000011", name="الف")
    make_policy(tenant, mobile="09120000012", name="ب", sms_opt_out=True)
    with tenant_context(tenant):
        Customer.objects.create(full_name="بدون بیمه‌نامه", mobile="09120000013", city="کرج")
        c = Campaign.objects.create(title="t", text="سلام {name}", line=LineOfBusiness.objects.get(slug="third-party"))
        run_campaign(c)
    c.refresh_from_db()
    assert (c.recipients, c.sent, c.status) == (1, 1, "done")
    assert sent == [("09120000011", "سلام الف\nلغو۱۱")]


def test_report_export_escapes_formulas(client, tenant, owner):
    enable(tenant, "advanced_reports")
    make_policy(tenant, name='=HYPERLINK("http://x")')
    client.force_login(owner)
    body = client.get("/panel/reports/policies.csv", HTTP_HOST=host(tenant)).content.decode("utf-8")
    assert "'=HYPERLINK" in body
