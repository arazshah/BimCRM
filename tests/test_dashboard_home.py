"""The "today" desk, the grouped menu, the palette lookup and the merged-section tabs."""

from datetime import timedelta

import jdatetime
from django.utils import timezone

from apps.accounts.models import Membership, User
from apps.claims.models import Claim
from apps.core.tenancy import tenant_context
from apps.crm.models import QuoteRequest
from apps.finance.models import Cheque, Installment

from .conftest import host
from .test_addons import ALL_ADDONS, enable, make_policy


def _page(client, tenant, path="/panel/"):
    resp = client.get(path, HTTP_HOST=host(tenant))
    assert resp.status_code == 200
    return resp


def test_today_list_gathers_every_source_with_actions(client, tenant, owner):
    enable(tenant, *ALL_ADDONS)
    today = timezone.localdate()
    policy = make_policy(tenant, name="مریم رضایی", end=today + timedelta(days=2))
    with tenant_context(tenant):
        inst = Installment.objects.create(policy=policy, amount=15_000_000, due_date=today - timedelta(days=5))
        Cheque.objects.create(
            customer=policy.customer, serial="1", bank_name="ملی", amount=5_000_000, due_date=today, status="in_hand"
        )
        Cheque.objects.create(
            customer=policy.customer, serial="2", bank_name="ملت", amount=7_000_000, due_date=today, status="bounced"
        )
        Claim.objects.create(
            policy=policy, incident_date=today, description="تصادف", reported_by_customer=True, status="reported"
        )
        line = policy.line
        QuoteRequest.objects.create(line=line, full_name="لید تازه", mobile="09121110000")
        # birthday today in the Jalali calendar
        j = jdatetime.date.fromgregorian(date=today)
        born = jdatetime.date(j.year - 30, j.month, j.day).togregorian()
        policy.customer.birth_date = born
        policy.customer.save()
    client.force_login(owner)
    resp = _page(client, tenant)
    page = resp.content.decode()
    inbox = resp.context["inbox"]
    kinds = {r["kind"] for g in inbox["groups"] for r in g["items"]}
    assert kinds == {"renew", "quote", "money", "claim", "birthday"}
    assert "تمدید — مریم رضایی" in page and "قسط معوق — مریم رضایی" in page
    assert "چک برگشتی" in page and "سررسید چک" in page and "خسارت تازه از پنل مشتری" in page
    assert "لید تازه" in page and "تولد مریم رضایی" in page
    # overdue instalment is one tap away: a POST form that marks it paid
    assert f'action="/panel/finance/installments/{inst.pk}/paid/"' in page
    assert inbox["urgent"] >= 3
    # filter chips narrow the list
    only = _page(client, tenant, "/panel/?f=claim").context["inbox"]
    assert [r["kind"] for g in only["groups"] for r in g["items"]] == ["claim"]


def test_today_list_respects_plan_and_permissions(client, tenant, owner):
    today = timezone.localdate()
    policy = make_policy(tenant, end=today + timedelta(days=40))
    with tenant_context(tenant):
        Installment.objects.create(policy=policy, amount=1_000_000, due_date=today - timedelta(days=3))
        Claim.objects.create(policy=policy, incident_date=today, description="x", reported_by_customer=True)
    client.force_login(owner)
    # no finance / claims add-ons: those rows never show, and the empty state is friendly
    resp = _page(client, tenant)
    assert resp.context["inbox"]["empty"] is True
    assert "همه‌چیز مرتب است" in resp.content.decode()
    # add-on on but staff lacks the permission
    enable(tenant, *ALL_ADDONS)
    staff = User.objects.create_user("09120000077", full_name="کارمند")
    Membership.objects.create(
        user=staff, tenant=tenant, role=Membership.Role.STAFF, perms={"finance": False, "claims": False}
    )
    client.force_login(staff)
    assert _page(client, tenant).context["inbox"]["empty"] is True
    client.force_login(owner)
    assert _page(client, tenant).context["inbox"]["empty"] is False


def test_menu_is_grouped_by_work_and_marks_locked_features(client, tenant, owner):
    client.force_login(owner)
    resp = _page(client, tenant, "/panel/customers/")
    groups = {g["key"]: g for g in resp.context["request"].nav["items"] if not g.get("single")}
    assert {"sales", "follow"} <= set(groups) and groups["sales"]["active"] is True
    page = resp.content.decode()
    assert page.count('class="nav-grp"') + page.count('class="nav-grp" open') >= 2
    assert "فروش و مشتریان" in page and "تنظیمات دفتر" in page
    # finance is not in the plan: still listed, with a lock rather than a package label
    nav = page[page.index('class="side-nav"') : page.index("</nav>", page.index('class="side-nav"'))]
    assert "مالی و حسابداری" in nav and "در پکیج فعلی شما نیست" in nav
    enable(tenant, "finance")
    nav = _page(client, tenant, "/panel/customers/").content.decode()
    nav = nav[nav.index('class="side-nav"') :]
    assert "مالی و حسابداری" in nav.split("</nav>")[0]


def test_new_menu_and_palette_follow_permissions(client, tenant, owner):
    client.force_login(owner)
    labels = [n["label"] for n in _page(client, tenant).context["request"].nav["new"]]
    assert labels == ["بیمه‌نامه", "مشتری", "کار و پیگیری"]
    enable(tenant, "finance", "claims")
    nav = _page(client, tenant).context["request"].nav
    assert {"رسید دریافت", "چک دریافتی", "اعلام خسارت"} <= {n["label"] for n in nav["new"]}
    assert any(p["kind"] == "command" and "رسید" in p["label"] for p in nav["palette"])
    page = _page(client, tenant).content.decode()
    assert 'id="pal-data"' in page and 'id="palette"' in page and 'class="bottom-nav"' in page


def test_palette_search_finds_customers_and_policies_with_persian_digits(client, tenant, owner):
    policy = make_policy(tenant, mobile="09125550101", name="علی حسینی")
    other = User.objects.create_user("09120000003")
    client.force_login(owner)
    h = host(tenant)
    assert client.get("/panel/search/?q=a", HTTP_HOST=h).json() == {"customers": [], "policies": []}
    data = client.get("/panel/search/?q=حسینی", HTTP_HOST=h).json()
    assert [c["label"] for c in data["customers"]] == ["علی حسینی"]
    assert data["policies"] and data["policies"][0]["url"].endswith(f"/policies/{policy.pk}/edit/")
    data = client.get("/panel/search/?q=۰۹۱۲۵۵۵۰۱۰۱", HTTP_HOST=h).json()
    assert data["customers"][0]["hint"] == "09125550101"
    # login required, tenant-isolated
    client.logout()
    assert client.get("/panel/search/?q=حسینی", HTTP_HOST=h).status_code == 302
    client.force_login(other)
    assert client.get("/panel/search/?q=حسینی", HTTP_HOST=h).status_code == 403


def test_merged_sections_show_tabs(client, tenant, owner):
    client.force_login(owner)
    page = _page(client, tenant, "/panel/site/lines/").content.decode()
    assert 'aria-label="سایت من"' in page and "قالب" in page and "دامنه" in page
    page = _page(client, tenant, "/panel/team/").content.decode()
    assert 'aria-label="تنظیمات دفتر"' in page and "همکاران" in page and "اتصالات" in page and "اشتراک" in page
    # staff only has the subscription page under office settings: no tabs for a single entry
    staff = User.objects.create_user("09120000066", full_name="کارمند")
    Membership.objects.create(user=staff, tenant=tenant, role=Membership.Role.STAFF)
    client.force_login(staff)
    resp = _page(client, tenant, "/panel/billing/")
    assert resp.context["request"].nav["office_tabs"] == []
    assert 'aria-label="تنظیمات دفتر"' not in resp.content.decode()


def test_only_one_banner_shows_at_a_time(client, tenant, owner):
    from apps.core.models import PlatformSettings

    ps = PlatformSettings.load()
    ps.free_domain_until = timezone.localdate() - timedelta(days=1)
    ps.save()
    client.force_login(owner)
    resp = _page(client, tenant)
    assert resp.context["banner"]["type"] == "setup" and resp.context["banner"]["total"] == 5
    page = resp.content.decode()
    assert page.count("data-banner-key") == 1 and "مرحلهٔ بعدی راه‌اندازی" in page
    # the subscription page stays one click away in the sidebar
    assert 'href="/panel/billing/"' in page
    # a running free-domain offer outranks the setup nudge
    ps.free_domain_until = timezone.localdate() + timedelta(days=10)
    ps.save()
    resp = _page(client, tenant)
    assert resp.context["banner"]["type"] == "domain" and resp.content.decode().count("data-banner-key") == 1
