from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Membership, User
from apps.core.models import LineOfBusiness
from apps.core.tenancy import tenant_context
from apps.crm.models import Customer, QuoteRequest
from apps.messaging.models import MessageLog, ReminderSettings
from apps.sites.models import SiteSettings
from apps.work.models import Activity, Notification, Task
from apps.work.services import customer_timeline, renewal_tasks, run_daily_work

from .conftest import host
from .test_addons import connect_sms, make_policy, sent  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(tenant):
    u = User.objects.create_user("09120000077", full_name="مینا همکار")
    Membership.objects.create(user=u, tenant=tenant, role=Membership.Role.STAFF)
    return u


def test_site_quote_creates_call_task_and_notifies_office(client, tenant, owner, staff):
    site = SiteSettings.all_objects.get(tenant=tenant)
    site.is_published = True
    site.save()
    site.lines.set(LineOfBusiness.objects.filter(slug="third-party"))
    client.post(
        "/quote/", {"line": "third-party", "full_name": "سارا", "mobile": "09127778888"}, HTTP_HOST=host(tenant)
    )
    q = QuoteRequest.all_objects.get(tenant=tenant)
    t = Task.all_objects.get(tenant=tenant)
    assert t.quote == q and t.due_date == timezone.localdate() and t.priority == Task.Priority.HIGH
    assert set(Notification.all_objects.filter(tenant=tenant).values_list("user", flat=True)) == {owner.pk, staff.pk}
    client.force_login(owner)
    page = client.get("/panel/", HTTP_HOST=host(tenant)).content.decode()
    assert "تماس با سارا" in page and 'class="dot"' in page


def test_tasks_crud_toggle_and_visibility(client, tenant, owner, staff):
    client.force_login(owner)
    today = timezone.localdate()
    resp = client.post(
        "/panel/tasks/new/",
        {
            "title": "پیگیری چک",
            "kind": "payment",
            "assigned_to": staff.pk,
            "due_date": today.isoformat(),
            "priority": 3,
        },
        HTTP_HOST=host(tenant),
    )
    assert resp.status_code == 302
    t = Task.all_objects.get(tenant=tenant)
    assert t.assigned_to == staff and t.created_by == owner
    assert Notification.all_objects.filter(user=staff, text__contains="پیگیری چک").exists()
    with tenant_context(tenant):
        Task.objects.create(title="کار خصوصی مدیر", assigned_to=owner, due_date=today)
    client.force_login(staff)
    page = client.get("/panel/tasks/?f=all", HTTP_HOST=host(tenant)).content.decode()
    assert "پیگیری چک" in page and "کار خصوصی مدیر" not in page
    client.post(f"/panel/tasks/{t.pk}/toggle/", HTTP_HOST=host(tenant))
    t.refresh_from_db()
    assert t.done_at and t.done_by == staff
    for f in ("mine", "week", "all", "done"):
        assert client.get(f"/panel/tasks/?f={f}", HTTP_HOST=host(tenant)).status_code == 200


def test_activity_timeline_followup_and_sms(client, tenant, owner, staff, sent):  # noqa: F811
    p = make_policy(tenant)
    c = p.customer
    connect_sms(tenant)
    client.force_login(owner)
    h = host(tenant)
    resp = client.post(
        f"/panel/customers/{c.pk}/activity/",
        {
            "kind": "call",
            "body": "قیمت بدنه خواست",
            "notify": staff.pk,
            "follow_up": (timezone.localdate() + timedelta(days=2)).isoformat(),
        },
        HTTP_HOST=h,
    )
    assert resp.status_code == 302
    assert Activity.all_objects.get(tenant=tenant).created_by == owner
    follow = Task.all_objects.get(tenant=tenant)
    assert follow.assigned_to == staff and follow.customer == c
    assert Notification.all_objects.filter(user=staff).count() == 2  # mention + assigned task
    client.post(f"/panel/customers/{c.pk}/sms/", {"text": "سلام، تمدید آماده است"}, HTTP_HOST=h)
    assert sent and sent[-1][0] == c.mobile
    assert MessageLog.all_objects.filter(tenant=tenant, kind="manual").exists()
    with tenant_context(tenant):
        kinds = [i["kind"] for i in customer_timeline(c)]
    assert {"call", "sms_out", "policy"} <= set(kinds)
    page = client.get(f"/panel/customers/{c.pk}/", HTTP_HOST=h).content.decode()
    assert "قیمت بدنه خواست" in page and "سلام، تمدید آماده است" in page


def test_renewal_tasks_and_staff_digest(tenant, owner, staff, sent):  # noqa: F811
    today = timezone.localdate()
    make_policy(tenant, end=today + timedelta(days=5))
    make_policy(tenant, mobile="09121234568", end=today + timedelta(days=60))
    with tenant_context(tenant):
        assert renewal_tasks(tenant) == 1
        assert renewal_tasks(tenant) == 0  # once per policy
        ReminderSettings.objects.update_or_create(tenant=tenant, defaults={"staff_digest_enabled": True})
    connect_sms(tenant)
    totals = run_daily_work()
    assert totals["digests"] == 2  # unassigned renewal task reaches both colleagues
    assert {m for m, _ in sent} == {owner.mobile, staff.mobile}
    assert run_daily_work()["digests"] == 0


def test_calendar_and_ics_feed(client, tenant, owner):
    today = timezone.localdate()
    make_policy(tenant, end=today + timedelta(days=3))
    with tenant_context(tenant):
        Task.objects.create(title="جلسه با شرکت", due_date=today, assigned_to=owner)
        Customer.objects.filter(mobile="09121234567").update(birth_date=today.replace(year=1990))
    client.force_login(owner)
    page = client.get("/panel/calendar/", HTTP_HOST=host(tenant)).content.decode()
    assert "جلسه با شرکت" in page and "تولد" in page
    token = Membership.objects.get(user=owner, tenant=tenant).calendar_token
    assert len(token) > 20
    client.logout()
    ics = client.get(f"/panel/calendar/feed/{token}.ics", HTTP_HOST=host(tenant))
    body = ics.content.decode()
    assert ics.status_code == 200 and "BEGIN:VCALENDAR" in body and "SUMMARY:جلسه با شرکت" in body
    assert client.get("/panel/calendar/feed/" + "x" * 30 + ".ics", HTTP_HOST=host(tenant)).status_code == 404


def test_notifications_page_marks_read(client, tenant, owner):
    with tenant_context(tenant):
        n = Notification.objects.create(user=owner, text="سلام", url="/panel/tasks/")
    client.force_login(owner)
    assert "سلام" in client.get("/panel/notifications/", HTTP_HOST=host(tenant)).content.decode()
    assert client.get(f"/panel/notifications/{n.pk}/", HTTP_HOST=host(tenant)).url == "/panel/tasks/"
    n.refresh_from_db()
    assert n.read_at
