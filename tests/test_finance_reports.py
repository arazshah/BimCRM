from datetime import date

from apps.core.tenancy import tenant_context
from apps.crm.models import Customer
from apps.finance.models import Cheque, FinanceAccount, Installment, PaymentOrder, create_receipt
from apps.finance.reports import customer_statement, daily_cash, debtors

from .conftest import host
from .test_addons import enable, make_policy


def _receipt(tenant, owner, policy, amount, account, day=date(2026, 10, 21), **line):
    return create_receipt(
        tenant_id=tenant.pk,
        user=owner,
        data={"date": day, "customer": policy.customer, "policy": policy, "description": ""},
        lines=[{"method": "cash", "amount": amount, "account": account, **line}],
    )


def test_customer_statement_and_debtors(tenant, owner):
    policy = make_policy(tenant, premium=10_000_000)
    other = make_policy(tenant, mobile="09129990000", name="بدهکار دوم", premium=3_000_000)
    with tenant_context(tenant):
        cash = FinanceAccount.objects.create(kind="cash", title="صندوق")
        _receipt(tenant, owner, policy, 4_000_000, cash)
        old = Installment.objects.create(
            policy=policy, due_date=date(2026, 10, 1), amount=1_000_000, status="paid", paid_at=date(2026, 10, 2)
        )
        stmt = customer_statement(policy.customer)
        assert stmt["debit"] == 10_000_000 and stmt["credit"] == 5_000_000 and stmt["balance"] == 5_000_000
        assert [r["balance"] for r in stmt["rows"]][-1] == 5_000_000
        rows = debtors(Customer.objects.all())
        assert [r["balance"] for r in rows] == [5_000_000, 3_000_000]
        # an installment paid through a receipt is counted once
        _receipt(tenant, owner, policy, 1_000_000, cash, installment=old)
        assert customer_statement(policy.customer)["credit"] == 5_000_000  # moved from "no receipt" to the receipt
        _receipt(tenant, owner, other, 3_000_000, cash)
        assert len(debtors(Customer.objects.all())) == 1


def test_daily_cash_totals(tenant, owner):
    policy = make_policy(tenant)
    day = date(2026, 10, 21)
    with tenant_context(tenant):
        cash = FinanceAccount.objects.create(kind="cash", title="صندوق")
        bank = FinanceAccount.objects.create(kind="bank", title="ملی")
        _receipt(tenant, owner, policy, 2_000_000, cash, day)
        PaymentOrder.objects.create(
            number=1, date=day, payee="مالک", method="cash", account=cash, amount=500_000, category="rent"
        )
        cheque = Cheque.objects.create(
            customer=policy.customer, serial="1", bank_name="ملی", amount=700_000, due_date=day
        )
        cheque.move_to("deposited", account=bank, when=day)
        cheque.move_to("cleared", when=day)
        d = daily_cash(day)
        assert d["total_in"] == 2_700_000 and d["total_out"] == 500_000
        by = {a["title"]: a["net"] for a in d["accounts"]}
        assert by == {"صندوق": 1_500_000, "ملی": 700_000}


def test_report_pages_render_and_scope(client, tenant, other_tenant, owner):
    enable(tenant, "finance")
    policy = make_policy(tenant)
    client.force_login(owner)
    h = host(tenant)
    for u in (
        "finance/",
        "finance/debtors/",
        "finance/daily/",
        "finance/daily/?d=2026-10-21",
        f"customers/{policy.customer_id}/account/",
        f"customers/{policy.customer_id}/",
    ):
        assert client.get(f"/panel/{u}", HTTP_HOST=h).status_code == 200, u
    assert "صورت‌حساب" in client.get(f"/panel/customers/{policy.customer_id}/", HTTP_HOST=h).content.decode()
    with tenant_context(other_tenant):
        assert debtors(Customer.objects.all()) == []
