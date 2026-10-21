from datetime import date

from apps.core.tenancy import tenant_context
from apps.finance.models import Cheque, FinanceAccount, Installment, PaymentOrder, Receipt, account_balance

from .conftest import host
from .test_addons import enable, make_policy


def _setup(tenant):
    policy = make_policy(tenant)
    with tenant_context(tenant):
        cash = FinanceAccount.objects.create(kind="cash", title="صندوق", opening_balance=1_000_000)
        bank = FinanceAccount.objects.create(kind="bank", title="ملی")
    return policy, cash, bank


def _post(client, h, policy, lines, **extra):
    data = {
        "date": "2026-10-21",
        "customer": policy.customer_id,
        "policy": policy.pk,
        "description": "حق بیمه",
        "lines-TOTAL_FORMS": str(len(lines) + 1),
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        **extra,
    }
    for i, line in enumerate(lines):
        for k, v in line.items():
            data[f"lines-{i}-{k}"] = v
    return client.post("/panel/finance/receipts/new/", data, HTTP_HOST=h)


def test_receipt_multi_method_numbers_and_balance(client, tenant, owner):
    enable(tenant, "finance")
    policy, cash, bank = _setup(tenant)
    client.force_login(owner)
    h = host(tenant)
    r = _post(
        client,
        h,
        policy,
        [
            {"method": "cash", "amount": "2,000,000", "account": cash.pk},
            {"method": "transfer", "amount": "3,000,000", "account": bank.pk, "reference": "998877"},
        ],
    )
    assert r.status_code == 302, r.content.decode()[:600]
    _post(client, h, policy, [{"method": "cash", "amount": "500000", "account": cash.pk}])
    with tenant_context(tenant):
        nums = list(Receipt.objects.order_by("number").values_list("number", flat=True))
        first = Receipt.objects.get(number=1)
        assert nums == [1, 2] and first.total == 5_000_000
        assert account_balance(cash) == 1_000_000 + 2_000_000 + 500_000
        assert account_balance(bank) == 3_000_000
    for u in ("receipts/", "receipts/?q=1", f"receipts/{first.pk}/", f"receipts/{first.pk}/?print=1", "receipts/new/"):
        assert client.get(f"/panel/finance/{u}", HTTP_HOST=h).status_code == 200, u


def test_receipt_validation(client, tenant, owner):
    enable(tenant, "finance")
    policy, cash, bank = _setup(tenant)
    client.force_login(owner)
    h = host(tenant)
    wrong_acc = _post(client, h, policy, [{"method": "cash", "amount": "1000", "account": bank.pk}])
    assert wrong_acc.status_code == 200 and "نمی‌خواند" in wrong_acc.content.decode()
    no_acc = _post(client, h, policy, [{"method": "transfer", "amount": "1000"}])
    assert "انتخاب کنید" in no_acc.content.decode()
    empty = _post(client, h, policy, [])
    assert empty.status_code == 200 and "حداقل یک ردیف" in empty.content.decode()
    with tenant_context(tenant):
        assert Receipt.objects.count() == 0


def test_receipt_with_cheque_and_installment_cancel_reopens(client, tenant, owner):
    enable(tenant, "finance")
    policy, cash, bank = _setup(tenant)
    with tenant_context(tenant):
        inst = Installment.objects.create(policy=policy, due_date=date(2026, 11, 1), amount=100_000, method="cash")
        cheque = Cheque.objects.create(
            customer=policy.customer, serial="55", bank_name="ملت", amount=400_000, due_date=date(2026, 12, 1)
        )
    client.force_login(owner)
    h = host(tenant)
    _post(
        client,
        h,
        policy,
        [
            {"method": "cash", "amount": "1,000,000", "account": cash.pk, "installment": inst.pk},
            {"method": "cheque", "cheque": cheque.pk},
        ],
    )
    with tenant_context(tenant):
        receipt = Receipt.objects.get()
        inst.refresh_from_db()
        assert receipt.total == 1_400_000 and inst.status == "paid"
    client.post(f"/panel/finance/receipts/{receipt.pk}/", {"reason": "اشتباه"}, HTTP_HOST=h)
    with tenant_context(tenant):
        receipt.refresh_from_db()
        inst.refresh_from_db()
        assert receipt.status == "cancelled" and inst.status == "pending" and inst.paid_at is None
        assert account_balance(cash) == 1_000_000  # cancelled receipts leave the balance


def test_receipt_rejects_other_customers_cheque(client, tenant, owner):
    enable(tenant, "finance")
    policy, cash, bank = _setup(tenant)
    other = make_policy(tenant, mobile="09129998888", name="دیگری")
    with tenant_context(tenant):
        cheque = Cheque.objects.create(
            customer=other.customer, serial="9", bank_name="ملی", amount=1000, due_date=date(2026, 12, 1)
        )
    client.force_login(owner)
    r = _post(client, owner and host(tenant), policy, [{"method": "cheque", "cheque": cheque.pk}])
    assert r.status_code == 200
    with tenant_context(tenant):
        assert Receipt.objects.count() == 0


def test_payment_order_lifecycle_and_balance(client, tenant, owner):
    enable(tenant, "finance")
    policy, cash, bank = _setup(tenant)
    client.force_login(owner)
    h = host(tenant)
    bad = client.post(
        "/panel/finance/payments/new/",
        {
            "date": "2026-10-21",
            "payee": "آقای الف",
            "category": "rent",
            "method": "cash",
            "account": bank.pk,
            "amount": "1",
        },
        HTTP_HOST=h,
    )
    assert bad.status_code == 200 and "نمی‌خواند" in bad.content.decode()
    ok = client.post(
        "/panel/finance/payments/new/",
        {
            "date": "2026-10-21",
            "payee": "مالک",
            "category": "rent",
            "method": "cash",
            "account": cash.pk,
            "amount": "300,000",
        },
        HTTP_HOST=h,
    )
    assert ok.status_code == 302
    with tenant_context(tenant):
        order = PaymentOrder.objects.get()
        assert order.number == 1 and account_balance(cash) == 700_000
    for u in ("payments/", f"payments/{order.pk}/", f"payments/{order.pk}/?print=1", "payments/new/"):
        assert client.get(f"/panel/finance/{u}", HTTP_HOST=h).status_code == 200, u
    client.post(f"/panel/finance/payments/{order.pk}/", {"reason": "تکراری"}, HTTP_HOST=h)
    with tenant_context(tenant):
        assert account_balance(cash) == 1_000_000


def test_cleared_cheque_raises_bank_balance_and_numbers_isolated(client, tenant, other_tenant, owner):
    enable(tenant, "finance")
    policy, cash, bank = _setup(tenant)
    with tenant_context(tenant):
        cheque = Cheque.objects.create(
            customer=policy.customer, serial="1", bank_name="ملی", amount=700_000, due_date=date(2026, 12, 1)
        )
        cheque.move_to("deposited", account=bank)
        assert account_balance(bank) == 0
        cheque.move_to("cleared")
        assert account_balance(bank) == 700_000
    with tenant_context(other_tenant):
        assert Receipt.next_number(other_tenant.pk) == 1
