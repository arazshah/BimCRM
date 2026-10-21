from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.finance.models import Cheque, FinanceAccount, Installment
from apps.finance.money import number_to_words, parse_amount, rial_in_toman_words

from .conftest import host
from .test_addons import enable, make_policy


def test_rial_words_and_parsing():
    assert rial_in_toman_words(12_500_000) == "یک میلیون و دویست و پنجاه هزار تومان"
    assert rial_in_toman_words(15) == "یک تومان و پنج ریال"
    assert rial_in_toman_words(5) == "پنج ریال"
    assert rial_in_toman_words(None) == "" and rial_in_toman_words(0) == ""
    assert number_to_words(115) == "یکصد و پانزده"
    assert parse_amount("۱٬۲۵۰,۰۰۰") == 1_250_000
    assert parse_amount("12 5") == 125 and parse_amount("abc") is None and parse_amount("") is None


def _cheque_data(customer, **over):
    data = {
        "customer": customer.pk,
        "kind": "normal",
        "serial": "123456",
        "sayad_id": "1234567890123456",
        "bank_name": "ملی",
        "amount": "12,500,000",
        "due_date": "2026-12-01",
        "received_date": "2026-10-21",
    }
    data.update(over)
    return data


def test_cheque_form_accepts_grouped_amount_and_records_history(client, tenant, owner):
    enable(tenant, "finance")
    policy = make_policy(tenant)
    client.force_login(owner)
    h = host(tenant)
    page = client.get("/panel/finance/cheques/new/", HTTP_HOST=h).content.decode()
    assert "data-rial" in page and "rial-words" in page
    resp = client.post("/panel/finance/cheques/new/", _cheque_data(policy.customer), HTTP_HOST=h)
    assert resp.status_code == 302, resp.content.decode()[:500]
    with tenant_context(tenant):
        cheque = Cheque.objects.get()
        assert cheque.amount == 12_500_000 and cheque.status == "in_hand"
        assert cheque.events.count() == 1


def test_cheque_validation(client, tenant, owner):
    enable(tenant, "finance")
    policy = make_policy(tenant)
    client.force_login(owner)
    h = host(tenant)
    bad = client.post("/panel/finance/cheques/new/", _cheque_data(policy.customer, sayad_id="123"), HTTP_HOST=h)
    assert bad.status_code == 200 and "۱۶ رقم" in bad.content.decode()
    client.post("/panel/finance/cheques/new/", _cheque_data(policy.customer), HTTP_HOST=h)
    dup = client.post("/panel/finance/cheques/new/", _cheque_data(policy.customer, serial="999"), HTTP_HOST=h)
    assert dup.status_code == 200 and "قبلاً ثبت" in dup.content.decode()
    early = client.post(
        "/panel/finance/cheques/new/",
        _cheque_data(policy.customer, sayad_id="", issue_date="2027-01-01"),
        HTTP_HOST=h,
    )
    assert early.status_code == 200 and "قبل از تاریخ صدور" in early.content.decode()


def test_cheque_lifecycle_settles_installment(client, tenant, owner):
    enable(tenant, "finance")
    policy = make_policy(tenant)
    with tenant_context(tenant):
        inst = Installment.objects.create(policy=policy, due_date=date(2026, 12, 1), amount=1_250_000, method="cheque")
        bank = FinanceAccount.objects.create(kind="bank", title="ملی ۱۲۳")
    client.force_login(owner)
    h = host(tenant)
    client.post(
        "/panel/finance/cheques/new/",
        _cheque_data(policy.customer, policy=policy.pk, installment=inst.pk),
        HTTP_HOST=h,
    )
    with tenant_context(tenant):
        cheque = Cheque.objects.get()
    url = f"/panel/finance/cheques/{cheque.pk}/"
    # clearing straight from deposit needs an account
    no_acc = client.post(url, {"status": "deposited", "date": "2026-12-01"}, HTTP_HOST=h)
    assert "حساب بانکی" in no_acc.content.decode()
    client.post(url, {"status": "deposited", "date": "2026-11-30", "account": bank.pk}, HTTP_HOST=h)
    client.post(url, {"status": "bounced", "date": "2026-12-02"}, HTTP_HOST=h)
    with tenant_context(tenant):
        inst.refresh_from_db()
        assert inst.status == "bounced"
    client.post(url, {"status": "deposited", "date": "2026-12-03"}, HTTP_HOST=h)
    client.post(url, {"status": "cleared", "date": "2026-12-04"}, HTTP_HOST=h)
    with tenant_context(tenant):
        cheque.refresh_from_db()
        inst.refresh_from_db()
        assert cheque.status == "cleared" and inst.status == "paid" and inst.paid_at == date(2026, 12, 4)
        assert cheque.events.count() == 5
        with pytest.raises(ValueError):
            cheque.move_to("in_hand")  # cleared is final
    assert client.get(url, HTTP_HOST=h).status_code == 200


def test_spent_cheque_needs_recipient(client, tenant, owner):
    enable(tenant, "finance")
    policy = make_policy(tenant)
    client.force_login(owner)
    h = host(tenant)
    client.post("/panel/finance/cheques/new/", _cheque_data(policy.customer), HTTP_HOST=h)
    with tenant_context(tenant):
        cheque = Cheque.objects.get()
    url = f"/panel/finance/cheques/{cheque.pk}/"
    assert "نام کسی" in client.post(url, {"status": "spent", "date": "2026-11-01"}, HTTP_HOST=h).content.decode()
    client.post(url, {"status": "spent", "date": "2026-11-01", "handed_to": "علی رضایی"}, HTTP_HOST=h)
    with tenant_context(tenant):
        cheque.refresh_from_db()
        assert cheque.status == "spent" and cheque.handed_to == "علی رضایی"


def test_cheque_list_filters_and_pages_render(client, tenant, owner):
    enable(tenant, "finance")
    policy = make_policy(tenant)
    with tenant_context(tenant):
        FinanceAccount.objects.create(kind="cash", title="صندوق", opening_balance=5_000_000)
        Cheque.objects.create(
            customer=policy.customer,
            serial="1",
            bank_name="ملی",
            amount=1_000_000,
            due_date=timezone.localdate().replace(year=2020),
        )
        Cheque.objects.create(
            customer=policy.customer, serial="2", bank_name="ملت", amount=2_000_000, due_date=date(2099, 1, 1)
        )
    client.force_login(owner)
    h = host(tenant)
    for q in ("", "?f=overdue", "?f=all", "?f=cleared", "?f=week&k=security", "?q=ملت"):
        assert client.get(f"/panel/finance/cheques/{q}", HTTP_HOST=h).status_code == 200, q
    assert (
        "ملت" not in client.get("/panel/finance/cheques/?f=overdue", HTTP_HOST=h).content.decode().split("<tbody>")[1]
    )
    assert client.get("/panel/finance/accounts/", HTTP_HOST=h).status_code == 200
    assert client.get("/panel/finance/accounts/new/", HTTP_HOST=h).status_code == 200


def test_cheque_image_is_private_and_isolated(client, tenant, other_tenant, owner):
    enable(tenant, "finance")
    policy = make_policy(tenant)
    client.force_login(owner)
    h = host(tenant)
    img = SimpleUploadedFile("c.jpg", b"\xff\xd8\xff" + b"0" * 100, content_type="image/jpeg")
    resp = client.post("/panel/finance/cheques/new/", {**_cheque_data(policy.customer), "image": img}, HTTP_HOST=h)
    assert resp.status_code == 302, resp.content.decode()[:400]
    with tenant_context(tenant):
        cheque = Cheque.objects.get()
        assert cheque.image and cheque.image_size > 0
    assert client.get(cheque.image.url, HTTP_HOST=h).status_code == 200
    client.logout()
    assert client.get(cheque.image.url, HTTP_HOST=h).status_code == 404
    # another office never sees this office's cheques
    with tenant_context(other_tenant):
        assert Cheque.objects.count() == 0
