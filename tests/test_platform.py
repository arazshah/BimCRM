from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Membership, OTPCode, User, normalize_mobile
from apps.billing.models import Subscription
from apps.billing.tasks import run_lifecycle
from apps.core.dns import check_domain, normalize_hostname
from apps.core.models import Domain, InsuranceCompany, LineOfBusiness, Tenant, is_subdomain_available
from apps.core.tenancy import tenant_context
from apps.crm.models import Customer, Policy, QuoteRequest
from apps.integrations.models import Integration
from apps.sites import registry
from apps.sites.models import SiteSettings

from .conftest import MAIN, host

pytestmark = pytest.mark.django_db


# ---------- Host routing ----------


def test_main_site_and_health(client):
    assert client.get("/", HTTP_HOST=MAIN).status_code == 200
    assert client.get("/healthz", HTTP_HOST="anything.example").status_code == 200


def test_www_redirects_to_bare_domain(client):
    resp = client.get("/login/", HTTP_HOST=f"www.{MAIN}")
    assert resp.status_code == 301 and resp["Location"].endswith(f"{MAIN}/login/")


def test_unknown_subdomain_and_domain_are_404(client):
    assert client.get("/", HTTP_HOST=f"nobody.{MAIN}").status_code == 404
    assert client.get("/", HTTP_HOST="random-domain.ir").status_code == 404


def test_admin_host_serves_django_admin(client):
    assert client.get("/admin/login/", HTTP_HOST=f"admin.{MAIN}").status_code == 200
    assert client.get("/admin/login/", HTTP_HOST=MAIN).status_code == 404


def test_unpublished_site_shows_coming_soon_to_public(client, tenant):
    resp = client.get("/", HTTP_HOST=host(tenant))
    assert resp.status_code == 200
    assert "به‌زودی" in resp.content.decode()


def test_owner_sees_preview_of_unpublished_site(client, tenant, owner):
    client.force_login(owner)
    resp = client.get("/", HTTP_HOST=host(tenant))
    assert "منتشر نشده" in resp.content.decode()


def test_active_custom_domain_serves_site_and_subdomain_redirects(client, tenant):
    Domain.objects.create(tenant=tenant, hostname="alborz1234.ir", status=Domain.Status.ACTIVE)
    SiteSettings.all_objects.filter(tenant=tenant).update(is_published=True)
    assert client.get("/", HTTP_HOST="alborz1234.ir").status_code == 200
    assert client.get("/", HTTP_HOST="www.alborz1234.ir").status_code == 200
    resp = client.get("/", HTTP_HOST=host(tenant))
    assert resp.status_code == 301 and "alborz1234.ir" in resp["Location"]
    # The panel stays on the subdomain
    assert client.get("/panel/", HTTP_HOST=host(tenant)).status_code == 302
    resp = client.get("/panel/", HTTP_HOST="alborz1234.ir")
    assert resp.status_code == 301 and host(tenant) in resp["Location"]


def test_pending_domain_is_not_served(client, tenant):
    Domain.objects.create(tenant=tenant, hostname="pending.ir")
    assert client.get("/", HTTP_HOST="pending.ir").status_code == 404


# ---------- Subdomain rules ----------


@pytest.mark.parametrize(
    "slug,ok",
    [
        ("alborz1234", True),
        ("ab", False),
        ("Alborz", False),
        ("1abc", False),
        ("abc-", False),
        ("a--b", False),
        ("admin", False),
        ("www", False),
        ("asia", False),
        ("x" * 31, False),
    ],
)
def test_subdomain_rules(slug, ok):
    assert is_subdomain_available(slug)[0] is ok


def test_taken_subdomain(tenant):
    ok, msg = is_subdomain_available("alborz1234")
    assert not ok and "گرفته" in msg


# ---------- OTP login and sign-up wizard ----------


def test_mobile_normalization():
    assert normalize_mobile("۰۹۱۲ ۳۴۵ ۶۷۸۹") == "09123456789"
    assert normalize_mobile("+989123456789") == "09123456789"
    assert normalize_mobile("9123456789") == "09123456789"


def _login_with_otp(client, mobile, monkeypatch):
    sent = {}
    monkeypatch.setattr("apps.main.views.send_platform_otp", lambda m, c: sent.update(code=c))
    client.post("/login/", {"mobile": mobile}, HTTP_HOST=MAIN)
    return client.post("/login/verify/", {"code": sent["code"]}, HTTP_HOST=MAIN)


def test_signup_flow_creates_workspace_with_trial(client, monkeypatch):
    resp = _login_with_otp(client, "09121112233", monkeypatch)
    assert resp.status_code == 302 and resp["Location"].endswith("/me/")
    resp = client.get("/me/", HTTP_HOST=MAIN)
    assert resp.status_code == 302 and resp["Location"].endswith("/signup/")
    resp = client.post("/signup/", {"name": "نمایندگی تست", "full_name": "علی", "slug": "test-agency"}, HTTP_HOST=MAIN)
    assert resp.status_code == 302
    client.post("/signup/template/", {"template": "khodro"}, HTTP_HOST=MAIN)
    from apps.billing.models import Addon, StorageTier

    tier = StorageTier.objects.order_by("order")[1]
    resp = client.post(
        "/signup/plan/",
        {"period": "yearly", "storage_tier": tier.pk, "addon_finance": "on", "addon_extra_user": "2"},
        HTTP_HOST=MAIN,
    )
    tenant = Tenant.objects.get(slug="test-agency")
    assert resp.status_code == 302 and resp["Location"].startswith(f"http://test-agency.{MAIN}/panel/")
    sub = tenant.subscription
    assert sub.status == Subscription.Status.TRIAL and sub.storage_tier == tier and sub.period == "yearly"
    assert sub.active_addon_codes() == {"finance", "extra_user"}
    assert sub.user_limit() == 1 + 2
    assert SiteSettings.all_objects.get(tenant=tenant).template == "khodro"
    assert Membership.objects.get(tenant=tenant).role == "owner"
    assert User.objects.get(mobile="09121112233").full_name == "علی"
    assert Addon.objects.count() >= 9


def test_wrong_otp_is_rejected_and_limited(client, monkeypatch):
    monkeypatch.setattr("apps.main.views.send_platform_otp", lambda m, c: None)
    client.post("/login/", {"mobile": "09125556677"}, HTTP_HOST=MAIN)
    for _ in range(5):
        client.post("/login/verify/", {"code": "00000"}, HTTP_HOST=MAIN)
    otp = OTPCode.objects.get(mobile="09125556677")
    assert otp.attempts == 5 and not otp.used
    assert "_auth_user_id" not in client.session


def test_otp_resend_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr("apps.main.views.send_platform_otp", lambda m, c: None)
    client.post("/login/", {"mobile": "09125556677"}, HTTP_HOST=MAIN)
    resp = client.post("/login/", {"mobile": "09125556677"}, HTTP_HOST=MAIN)
    assert resp.status_code == 200 and OTPCode.objects.count() == 1


def test_login_next_allows_platform_subdomains_only(client, monkeypatch, tenant):
    monkeypatch.setattr("apps.main.views.send_platform_otp", lambda m, c: None)
    sent = {}
    monkeypatch.setattr("apps.main.views.send_platform_otp", lambda m, c: sent.update(code=c))
    client.post("/login/", {"mobile": "09120000001", "next": "https://evil.com/x"}, HTTP_HOST=MAIN)
    resp = client.post("/login/verify/", {"code": sent["code"]}, HTTP_HOST=MAIN)
    assert "evil.com" not in resp["Location"]


# ---------- Panel and tenant isolation ----------


def test_panel_requires_login_and_membership(client, tenant, other_tenant):
    resp = client.get("/panel/", HTTP_HOST=host(tenant))
    assert resp.status_code == 302 and f"{MAIN}/login/" in resp["Location"]
    client.force_login(other_tenant.owner)
    assert client.get("/panel/", HTTP_HOST=host(tenant)).status_code == 403


def test_all_panel_pages_render(client, tenant, owner):
    client.force_login(owner)
    for path in [
        "",
        "customers/",
        "customers/new/",
        "customers/import/",
        "policies/",
        "policies/new/",
        "quotes/",
        "site/",
        "site/template/",
        "domains/",
        "integrations/",
        "integrations/sms/smsir/",
        "team/",
        "billing/",
        "support/",
    ]:
        resp = client.get(f"/panel/{path}", HTTP_HOST=host(tenant))
        assert resp.status_code == 200, path


def test_tenant_data_is_isolated(client, tenant, other_tenant, owner):
    with tenant_context(other_tenant):
        foreign = Customer.objects.create(full_name="مشتری دیگری", mobile="09129999999")
    with tenant_context(tenant):
        Customer.objects.create(full_name="مشتری خودی", mobile="09128888888")
    client.force_login(owner)
    page = client.get("/panel/customers/", HTTP_HOST=host(tenant)).content.decode()
    assert "مشتری خودی" in page and "مشتری دیگری" not in page
    assert client.get(f"/panel/customers/{foreign.pk}/", HTTP_HOST=host(tenant)).status_code == 404


def test_customer_and_policy_and_renewal(client, tenant, owner):
    client.force_login(owner)
    h = host(tenant)
    client.post("/panel/customers/new/", {"full_name": "رضا", "mobile": "09121234567", "source": "phone"}, HTTP_HOST=h)
    with tenant_context(tenant):
        customer = Customer.objects.get(mobile="09121234567")
    line = LineOfBusiness.objects.get(slug="third-party")
    company = InsuranceCompany.objects.first()
    end = timezone.localdate() + timedelta(days=10)
    resp = client.post(
        "/panel/policies/new/",
        {
            "customer": customer.pk,
            "line": line.pk,
            "company": company.pk,
            "number": "123/45",
            "start_date": (end - timedelta(days=365)).isoformat(),
            "end_date": end.isoformat(),
            "premium": "4500000",
            "status": "active",
        },
        HTTP_HOST=h,
    )
    assert resp.status_code == 302
    dash = client.get("/panel/", HTTP_HOST=h).content.decode()
    assert "رضا" in dash  # appears in the renewals list
    with tenant_context(tenant):
        old = Policy.objects.get()
    resp = client.get(f"/panel/policies/new/?renew={old.pk}", HTTP_HOST=h)
    assert resp.status_code == 200 and "تمدید بیمه‌نامه" in resp.content.decode()


def test_expired_subscription_is_read_only(client, tenant, owner):
    Subscription.objects.filter(tenant=tenant).update(status=Subscription.Status.EXPIRED)
    client.force_login(owner)
    resp = client.post(
        "/panel/customers/new/", {"full_name": "x", "mobile": "09121234567", "source": "phone"}, HTTP_HOST=host(tenant)
    )
    assert resp.status_code == 302 and resp["Location"].endswith("/panel/billing/")
    with tenant_context(tenant):
        assert not Customer.objects.exists()
    assert client.get("/panel/customers/", HTTP_HOST=host(tenant)).status_code == 200


def test_csv_import(client, tenant, owner):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_login(owner)
    csv = "نام,موبایل,کد ملی,شهر\nمینا,09121231234,0012345678,تهران\nتکراری,09121231234,,\nبد,123,,\n"
    client.post(
        "/panel/customers/import/",
        {"file": SimpleUploadedFile("c.csv", csv.encode("utf-8-sig"))},
        HTTP_HOST=host(tenant),
    )
    with tenant_context(tenant):
        assert list(Customer.objects.values_list("full_name", flat=True)) == ["مینا"]


def test_team_limit(client, tenant, owner):
    client.force_login(owner)
    client.post(
        "/panel/team/", {"mobile": "09123330000", "full_name": "همکار", "role": "staff"}, HTTP_HOST=host(tenant)
    )
    assert Membership.objects.filter(tenant=tenant).count() == 1  # base package includes one user


def test_integration_credentials_are_encrypted(client, tenant, owner):
    client.force_login(owner)
    client.post(
        "/panel/integrations/sms/kavenegar/", {"enabled": "on", "api_key": "SECRET-KEY-123"}, HTTP_HOST=host(tenant)
    )
    integ = Integration.all_objects.get(tenant=tenant)
    assert integ.config["api_key"] == "SECRET-KEY-123"
    assert "SECRET-KEY-123" not in integ._config


# ---------- Domains ----------


def test_domain_add_and_ns_check(client, tenant, owner):
    client.force_login(owner)
    client.post("/panel/domains/", {"hostname": "https://www.Alborz1234.IR/"}, HTTP_HOST=host(tenant))
    domain = Domain.objects.get(tenant=tenant)
    assert domain.hostname == "alborz1234.ir" and domain.status == Domain.Status.PENDING
    assert not check_domain(domain, resolver=lambda h: ["ns1.other.ir", "ns2.other.ir"])
    assert check_domain(domain, resolver=lambda h: ["ns1.bimcrm.ir", "ns2.bimcrm.ir"])
    domain.refresh_from_db()
    assert domain.status == Domain.Status.ACTIVE and domain.activated_at
    check_domain(domain, resolver=lambda h: [])
    domain.refresh_from_db()
    assert domain.status == Domain.Status.ERROR


def test_domain_validation(client, tenant, owner):
    client.force_login(owner)
    resp = client.post("/panel/domains/", {"hostname": f"x.{MAIN}"}, HTTP_HOST=host(tenant))
    assert "زیردامنه" in resp.content.decode()
    assert normalize_hostname("HTTP://www.Test.ir/path") == "test.ir"


# ---------- Public site ----------


@pytest.mark.parametrize("key", [t.key for t in registry.TEMPLATES])
def test_every_template_renders_live_and_as_preview(client, tenant, key):
    site = SiteSettings.all_objects.get(tenant=tenant)
    site.template = key
    site.is_published = True
    site.about = "درباره"
    site.save()
    site.lines.set(LineOfBusiness.objects.all())
    site.companies.set(InsuranceCompany.objects.all()[:4])
    resp = client.get("/", HTTP_HOST=host(tenant))
    assert resp.status_code == 200 and "t-" in resp.content.decode()
    assert client.get(f"/templates/{key}/", HTTP_HOST=MAIN).status_code == 200
    assert client.get("/track/", HTTP_HOST=host(tenant)).status_code == 200


def test_quote_submission_and_tracking(client, tenant):
    site = SiteSettings.all_objects.get(tenant=tenant)
    site.is_published = True
    site.save()
    site.lines.set(LineOfBusiness.objects.filter(slug="third-party"))
    resp = client.post(
        "/quote/",
        {"line": "third-party", "full_name": "سارا", "mobile": "۰۹۱۲۷۷۷۸۸۸۸", "f_car": "پژو ۲۰۶"},
        HTTP_HOST=host(tenant),
    )
    assert resp.status_code == 200
    q = QuoteRequest.all_objects.get(tenant=tenant)
    assert q.mobile == "09127778888" and q.details == {"نوع و مدل خودرو": "پژو ۲۰۶"}
    resp = client.get(f"/track/?code={q.tracking_code}&mobile=09127778888", HTTP_HOST=host(tenant))
    assert q.get_status_display() in resp.content.decode()
    # A line the agent did not enable is refused
    client.post("/quote/", {"line": "life", "full_name": "x", "mobile": "09120000000"}, HTTP_HOST=host(tenant))
    assert QuoteRequest.all_objects.count() == 1


def test_customer_portal_needs_agent_sms(client, tenant):
    resp = client.get("/account/", HTTP_HOST=host(tenant))
    assert "هنوز فعال نشده" in resp.content.decode()


def test_customer_portal_login(client, tenant, monkeypatch):
    with tenant_context(tenant):
        integ = Integration(kind="sms", provider="smsir")
        integ.config = {"api_key": "k"}
        integ.save()
        Customer.objects.create(full_name="نرگس", mobile="09124445566")
    sent = {}
    monkeypatch.setattr("apps.sites.views.send_tenant_otp", lambda t, m, c: sent.update(code=c))
    client.post("/account/", {"mobile": "09124445566"}, HTTP_HOST=host(tenant))
    client.post("/account/", {"code": sent["code"]}, HTTP_HOST=host(tenant))
    resp = client.get("/account/", HTTP_HOST=host(tenant))
    assert "نرگس" in resp.content.decode()


def test_private_media_needs_membership(client, tenant, owner, settings):
    import os

    os.makedirs(os.path.join(settings.MEDIA_ROOT, "policies"), exist_ok=True)
    with open(os.path.join(settings.MEDIA_ROOT, "policies", "p.pdf"), "wb") as fh:
        fh.write(b"%PDF")
    with tenant_context(tenant):
        c = Customer.objects.create(full_name="x", mobile="09121110000")
        Policy.objects.create(
            customer=c,
            line=LineOfBusiness.objects.first(),
            company=InsuranceCompany.objects.first(),
            number="1",
            start_date=date(2025, 1, 1),
            end_date=date(2026, 1, 1),
            file="policies/p.pdf",
        )
    assert client.get("/media/policies/p.pdf", HTTP_HOST=host(tenant)).status_code == 404
    client.force_login(owner)
    assert client.get("/media/policies/p.pdf", HTTP_HOST=host(tenant)).status_code == 200
    assert client.get("/media/../settings.py", HTTP_HOST=host(tenant)).status_code == 404


# ---------- Billing lifecycle ----------


def test_subscription_lifecycle(tenant):
    sub = tenant.subscription
    now = timezone.now()
    sub.current_period_end = now + timedelta(days=2)
    sub.save()
    run_lifecycle(now)
    sub.refresh_from_db()
    assert sub.reminded_at and sub.status == Subscription.Status.TRIAL
    run_lifecycle(now + timedelta(days=3))
    sub.refresh_from_db()
    assert sub.status == Subscription.Status.GRACE
    run_lifecycle(now + timedelta(days=12))
    sub.refresh_from_db()
    assert sub.status == Subscription.Status.EXPIRED and not sub.is_writable
    sub.extend("monthly")
    assert sub.status == Subscription.Status.ACTIVE and sub.current_period_end > now + timedelta(days=29)


def test_payment_callback_extends_subscription(client, tenant, owner, monkeypatch):
    monkeypatch.setattr("apps.billing.zarinpal.request_payment", lambda *a, **k: ("A123", "https://pay/StartPay/A123"))
    monkeypatch.setattr("apps.billing.zarinpal.verify_payment", lambda amount, authority: "REF9")
    client.force_login(owner)
    resp = client.post(f"/pay/{tenant.slug}/", {"period": "yearly"}, HTTP_HOST=MAIN)
    assert resp.status_code == 302 and "StartPay" in resp["Location"]
    from apps.billing.models import Invoice

    inv = Invoice.objects.get()
    resp = client.get(f"/pay/callback/{inv.pk}/?Authority=A123&Status=OK", HTTP_HOST=MAIN)
    inv.refresh_from_db()
    assert inv.status == "paid" and inv.ref_id == "REF9"
    sub = Subscription.objects.get(tenant=tenant)
    assert sub.status == "active" and sub.period == "yearly"
    # Replaying the callback does not extend twice
    end = sub.current_period_end
    client.get(f"/pay/callback/{inv.pk}/?Authority=A123&Status=OK", HTTP_HOST=MAIN)
    sub.refresh_from_db()
    assert sub.current_period_end == end


def test_payment_by_non_member_is_404(client, tenant, other_tenant):
    client.force_login(other_tenant.owner)
    assert client.post(f"/pay/{tenant.slug}/", {"period": "monthly"}, HTTP_HOST=MAIN).status_code == 404


def test_tls_ask_only_allows_known_hosts(client, tenant):
    Domain.objects.create(tenant=tenant, hostname="good.ir", status=Domain.Status.ACTIVE)
    Domain.objects.create(tenant=tenant, hostname="pending.ir")
    ask = lambda d: client.get(f"/internal/tls-ask?domain={d}", HTTP_HOST="127.0.0.1").status_code  # noqa: E731
    assert ask(MAIN) == 200 and ask(f"admin.{MAIN}") == 200 and ask(host(tenant)) == 200
    assert ask("good.ir") == 200 and ask("www.good.ir") == 200
    assert ask("pending.ir") == 404 and ask(f"ghost.{MAIN}") == 404 and ask("evil.com") == 404


def test_ensure_superadmin_uses_configured_password(settings, db):
    from django.core.management import call_command

    settings.SUPERADMIN_MOBILE = "09104151005"
    settings.SUPERADMIN_PASSWORD = "first-Pass-123"
    call_command("ensure_superadmin")
    user = User.objects.get(mobile="09104151005")
    assert user.is_superuser and user.is_staff and user.check_password("first-Pass-123")


def test_ensure_superadmin_reissues_password_until_first_login(settings, db, capsys):
    from django.core.management import call_command
    from django.utils import timezone

    settings.SUPERADMIN_MOBILE = "09104151005"
    settings.SUPERADMIN_PASSWORD = ""
    call_command("ensure_superadmin")
    first = capsys.readouterr().out.split("PASSWORD: ")[1].split()[0]
    assert User.objects.get(mobile="09104151005").check_password(first)
    # Never logged in: a redeploy issues a fresh one-time password.
    call_command("ensure_superadmin")
    second = capsys.readouterr().out.split("PASSWORD: ")[1].split()[0]
    user = User.objects.get(mobile="09104151005")
    assert second != first and user.check_password(second) and not user.check_password(first)
    # After the first login the password belongs to the admin and is never touched again.
    user.last_login = timezone.now()
    user.set_password("my-own-password")
    user.save()
    call_command("ensure_superadmin")
    assert User.objects.get(mobile="09104151005").check_password("my-own-password")


# ---------- Platform services configured in the super admin ----------


def _platform(**fields):
    from apps.core.models import PlatformSettings

    p = PlatformSettings.load()
    for k, v in fields.items():
        setattr(p, k, v)
    p.save()
    return p


def test_super_admin_values_win_and_server_env_is_the_fallback(settings, db):
    from apps.core.platform_config import sms_backend, smsir_config, zarinpal_config

    settings.SMS_BACKEND = "console"
    settings.SMSIR_API_KEY = "env-key"
    settings.SMSIR_OTP_TEMPLATE_ID = "111"
    settings.SMSIR_LINE_NUMBER = "3000"
    settings.ZARINPAL_MERCHANT_ID = "env-merchant"
    settings.ZARINPAL_SANDBOX = True
    assert sms_backend() == "console"
    assert smsir_config().api_key == "env-key" and smsir_config().otp_template_id == "111"
    assert zarinpal_config() == ("env-merchant", True)

    _platform(
        sms_backend="smsir",
        smsir_api_key="db-key",
        smsir_otp_template_id="222",
        zarinpal_merchant_id="db-merchant",
        zarinpal_mode="live",
    )
    assert sms_backend() == "smsir"
    cfg = smsir_config()
    assert (cfg.api_key, cfg.otp_template_id, cfg.line_number) == ("db-key", "222", "3000")
    assert zarinpal_config() == ("db-merchant", False)


def test_platform_otp_uses_super_admin_credentials(db, monkeypatch):
    from apps.accounts import sms

    sent = {}
    monkeypatch.setattr(
        sms.SmsIrClient,
        "send_verify",
        lambda self, mobile, code: sent.update(key=self.api_key, tpl=self.otp_template_id, mobile=mobile, code=code),
    )
    _platform(sms_backend="smsir", smsir_api_key="db-key", smsir_otp_template_id="222")
    sms.send_platform_otp("09121112233", "4821")
    assert sent == {"key": "db-key", "tpl": "222", "mobile": "09121112233", "code": "4821"}


def test_zarinpal_uses_super_admin_merchant_and_mode(db, monkeypatch):
    from apps.billing import zarinpal

    calls = []

    class Resp:
        def json(self):
            return {"data": {"code": 100, "authority": "A1"}}

    monkeypatch.setattr(
        zarinpal.requests, "post", lambda url, json=None, timeout=0: calls.append((url, json)) or Resp()
    )
    _platform(zarinpal_mode="live", zarinpal_merchant_id="m-live")
    authority, url = zarinpal.request_payment(1000, "x", "https://cb")
    assert calls[0][0].startswith("https://payment.zarinpal.com") and calls[0][1]["merchant_id"] == "m-live"
    assert url == "https://payment.zarinpal.com/pg/StartPay/A1"
    _platform(zarinpal_mode="sandbox")
    zarinpal.request_payment(1000, "x", "https://cb")
    assert calls[1][0].startswith("https://sandbox.zarinpal.com")


def _admin_client(client):
    admin = User.objects.create_superuser("09104151005", password="pw-12345")
    client.force_login(admin)
    return f"admin.{MAIN}"


def _settings_form(**over):
    base = {
        "trial_days": 14,
        "grace_days": 7,
        "data_retention_days": 90,
        "yearly_discount_note": "دو ماه رایگان",
        "support_phone": "",
        "nameservers": "",
        "sms_backend": "",
        "smsir_api_key_input": "",
        "smsir_otp_template_id": "",
        "smsir_line_number": "",
        "zarinpal_mode": "",
        "zarinpal_merchant_id": "",
    }
    base.update(over)
    return base


def test_admin_saves_sms_key_encrypted_and_never_shows_it(client, settings, db):
    from apps.core.models import PlatformSettings

    settings.SMSIR_API_KEY = ""
    settings.SMSIR_OTP_TEMPLATE_ID = ""
    h = _admin_client(client)
    url = "/admin/core/platformsettings/1/change/"
    PlatformSettings.load()
    resp = client.post(
        url,
        _settings_form(sms_backend="smsir", smsir_api_key_input="SECRET-KEY-123", smsir_otp_template_id="555"),
        HTTP_HOST=h,
    )
    assert resp.status_code == 302
    p = PlatformSettings.load()
    assert p.smsir_api_key == "SECRET-KEY-123"
    assert "SECRET-KEY-123" not in p.smsir_api_key_enc
    page = client.get("/admin/core/platformsettings/1/change/", HTTP_HOST=h).content.decode()
    assert "SECRET-KEY-123" not in page
    # Blank keeps the stored key; the checkbox clears it.
    client.post(
        "/admin/core/platformsettings/1/change/",
        _settings_form(sms_backend="smsir", smsir_otp_template_id="555"),
        HTTP_HOST=h,
    )
    assert PlatformSettings.load().smsir_api_key == "SECRET-KEY-123"
    client.post(
        "/admin/core/platformsettings/1/change/",
        _settings_form(smsir_otp_template_id="555", clear_smsir_api_key="on"),
        HTTP_HOST=h,
    )
    assert PlatformSettings.load().smsir_api_key == ""


def test_admin_refuses_real_sms_or_live_payment_without_credentials(client, settings, db):
    settings.SMSIR_API_KEY = settings.SMSIR_OTP_TEMPLATE_ID = settings.ZARINPAL_MERCHANT_ID = ""
    h = _admin_client(client)
    resp = client.post(
        "/admin/core/platformsettings/1/change/", _settings_form(sms_backend="smsir", zarinpal_mode="live"), HTTP_HOST=h
    )
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "کلید API لازم است" in body and "شناسه قالب" in body and "مرچنت کد لازم است" in body
