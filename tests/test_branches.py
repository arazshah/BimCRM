"""Branches add-on: branch-limited staff only see their branch; managers see everything and can filter."""

import pytest

from apps.accounts.models import Membership, User
from apps.claims.models import Claim
from apps.core.tenancy import tenant_context
from apps.crm.models import Branch, Customer, Policy, QuoteRequest
from apps.finance.models import Installment
from apps.sites.models import SiteSettings

from .conftest import host
from .test_addons import ALL_ADDONS, enable, make_policy

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(tenant):
    """Two branches, one customer + policy in each, and a clerk limited to Karaj."""
    enable(tenant, "branches", *ALL_ADDONS)
    with tenant_context(tenant):
        tehran = Branch.objects.create(name="مرکزی تهران", city="تهران", phone="02188776655")
        karaj = Branch.objects.create(name="شعبه کرج", city="کرج")
    p_teh = make_policy(tenant, mobile="09121110001", name="تهرانی", branch=tehran)
    p_kar = make_policy(tenant, mobile="09121110002", name="کرجی", branch=karaj)
    clerk = User.objects.create_user("09125550000", full_name="کارمند کرج")
    Membership.objects.create(user=clerk, tenant=tenant, role=Membership.Role.STAFF, branch=karaj)
    return {"tehran": tehran, "karaj": karaj, "p_teh": p_teh, "p_kar": p_kar, "clerk": clerk}


def test_policy_inherits_branch_from_customer(setup):
    assert setup["p_teh"].branch == setup["tehran"]
    assert setup["p_kar"].branch == setup["karaj"]


def test_clerk_sees_only_own_branch(client, tenant, setup):
    client.force_login(setup["clerk"])
    h = host(tenant)
    page = client.get("/panel/customers/", HTTP_HOST=h).content.decode()
    assert "کرجی" in page and "تهرانی" not in page
    page = client.get("/panel/policies/", HTTP_HOST=h).content.decode()
    assert setup["p_kar"].number in page and setup["p_teh"].number not in page
    teh_customer = setup["p_teh"].customer_id
    assert client.get(f"/panel/customers/{teh_customer}/", HTTP_HOST=h).status_code == 404
    assert client.get(f"/panel/customers/{teh_customer}/edit/", HTTP_HOST=h).status_code == 404
    assert client.get(f"/panel/policies/{setup['p_teh'].pk}/edit/", HTTP_HOST=h).status_code == 404
    assert client.get(f"/panel/policies/new/?renew={setup['p_teh'].pk}", HTTP_HOST=h).status_code == 404
    page = client.get("/panel/", HTTP_HOST=h).content.decode()
    assert "شعبه کرج" in page  # branch badge in the sidebar


def test_clerk_records_are_saved_into_own_branch(client, tenant, setup):
    client.force_login(setup["clerk"])
    resp = client.post(
        "/panel/customers/new/",
        {"full_name": "مشتری تازه", "mobile": "09121110009", "source": "walk_in", "branch": setup["tehran"].pk},
        HTTP_HOST=host(tenant),
    )
    assert resp.status_code == 302
    with tenant_context(tenant):
        assert Customer.objects.get(mobile="09121110009").branch == setup["karaj"]


def test_clerk_cannot_pick_foreign_policy_in_forms(client, tenant, setup):
    client.force_login(setup["clerk"])
    h = host(tenant)
    page = client.get("/panel/claims/new/", HTTP_HOST=h).content.decode()
    assert "کرجی" in page and "تهرانی" not in page
    resp = client.post(
        "/panel/claims/new/",
        {"policy": setup["p_teh"].pk, "incident_date": "2026-10-01", "description": "x"},
        HTTP_HOST=h,
    )
    assert resp.status_code == 200  # invalid choice
    with tenant_context(tenant):
        assert not Claim.objects.exists()
        inst = Installment.objects.create(policy=setup["p_teh"], due_date="2026-11-01", amount=1000)
    assert client.get(f"/panel/finance/installments/{inst.pk}/", HTTP_HOST=h).status_code == 404
    assert client.post(f"/panel/finance/installments/{inst.pk}/paid/", HTTP_HOST=h).status_code == 404


def test_office_wide_pages_closed_to_clerk(client, tenant, setup, owner):
    client.force_login(setup["clerk"])
    h = host(tenant)
    for path in ["finance/", "finance/ledger/", "finance/commissions/", "reports/", "marketers/", "branches/"]:
        assert client.get(f"/panel/{path}", HTTP_HOST=h).status_code == 403, path
    assert client.get("/panel/finance/installments/", HTTP_HOST=h).status_code == 200
    assert client.get("/panel/claims/", HTTP_HOST=h).status_code == 200


def test_unrouted_web_leads_visible_to_clerk(client, tenant, setup):
    with tenant_context(tenant):
        line = setup["p_teh"].line
        QuoteRequest.objects.create(line=line, full_name="بی‌شعبه", mobile="09121110020")
        QuoteRequest.objects.create(line=line, full_name="لید تهران", mobile="09121110021", branch=setup["tehran"])
    client.force_login(setup["clerk"])
    page = client.get("/panel/quotes/", HTTP_HOST=host(tenant)).content.decode()
    assert "بی‌شعبه" in page and "لید تهران" not in page


def test_manager_sees_all_and_filters(client, tenant, owner, setup):
    client.force_login(owner)
    h = host(tenant)
    page = client.get("/panel/customers/", HTTP_HOST=h).content.decode()
    assert "کرجی" in page and "تهرانی" in page and 'name="b"' in page
    page = client.get(f"/panel/customers/?b={setup['tehran'].pk}", HTTP_HOST=h).content.decode()
    assert "تهرانی" in page and "کرجی" not in page
    page = client.get("/panel/reports/", HTTP_HOST=h).content.decode()
    assert "به تفکیک شعبه" in page
    assert client.get("/panel/branches/", HTTP_HOST=h).status_code == 200


def test_manager_creates_branch_and_assigns_member(client, tenant, owner, setup):
    client.force_login(owner)
    h = host(tenant)
    resp = client.post(
        "/panel/branches/new/", {"name": "شعبه قزوین", "city": "قزوین", "is_active": "on", "order": 2}, HTTP_HOST=h
    )
    assert resp.status_code == 302
    with tenant_context(tenant):
        qazvin = Branch.objects.get(name="شعبه قزوین")
    m = Membership.objects.get(user=setup["clerk"], tenant=tenant)
    client.post("/panel/team/", {"set_branch": m.pk, "branch": qazvin.pk}, HTTP_HOST=h)
    m.refresh_from_db()
    assert m.branch == qazvin


def test_branch_pages_locked_without_addon(client, tenant, owner):
    client.force_login(owner)
    assert client.get("/panel/branches/", HTTP_HOST=host(tenant)).status_code == 402


def test_branch_scope_ignored_without_addon(client, tenant, setup):
    """If the office drops the add-on, branch staff fall back to seeing the whole office."""
    tenant.subscription.items.filter(addon__code="branches").delete()
    client.force_login(setup["clerk"])
    page = client.get("/panel/customers/", HTTP_HOST=host(tenant)).content.decode()
    assert "کرجی" in page and "تهرانی" in page


def test_public_site_lists_branches_and_routes_quote(client, tenant, setup):
    with tenant_context(tenant):
        site = SiteSettings.objects.get()
        site.is_published = True
        site.save()
        site.lines.add(setup["p_teh"].line)
    h = host(tenant)
    page = client.get("/", HTTP_HOST=h).content.decode()
    assert "مرکزی تهران" in page and 'name="branch"' in page
    client.post(
        "/quote/",
        {"line": "third-party", "full_name": "متقاضی", "mobile": "09121110030", "branch": setup["karaj"].pk},
        HTTP_HOST=h,
    )
    with tenant_context(tenant):
        assert QuoteRequest.objects.get(mobile="09121110030").branch == setup["karaj"]


def test_policy_branch_kept_when_customer_changes_nothing(tenant, setup):
    with tenant_context(tenant):
        p = Policy.objects.get(pk=setup["p_kar"].pk)
        p.premium += 1
        p.save()
        assert p.branch == setup["karaj"]
