import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

OLD = [
    ("finance", "0007_alter_installment_amount_alter_ledgerentry_amount"),
    ("crm", "0009_alter_policy_commission_received_and_more"),
    ("network", "0003_alter_marketerpayout_amount"),
    ("claims", "0005_alter_claim_amount_claimed_alter_claim_amount_paid"),
]


@pytest.mark.django_db(transaction=True)
def test_amounts_are_multiplied_by_ten_once():
    from apps.accounts.models import User
    from apps.billing.models import StorageTier
    from apps.billing.services import create_workspace
    from apps.core.tenancy import tenant_context

    owner = User.objects.create_user("09120009999")
    tenant = create_workspace(
        owner=owner,
        name="دفتر مهاجرت",
        slug="migr",
        template="modern",
        storage_tier=StorageTier.objects.order_by("order").first(),
        addons={},
        period="monthly",
    )
    from apps.core.models import InsuranceCompany, LineOfBusiness
    from apps.crm.models import Customer, Policy
    from apps.finance.models import Installment, LedgerEntry

    with tenant_context(tenant):
        c = Customer.objects.create(full_name="الف", mobile="09121110000")
        p = Policy.objects.create(
            customer=c,
            line=LineOfBusiness.objects.first(),
            company=InsuranceCompany.objects.first(),
            number="1",
            start_date="2026-01-01",
            end_date="2027-01-01",
            premium=1_000_000,
            commission_received=80_000,
        )
        Installment.objects.create(policy=p, due_date="2026-12-01", amount=250_000)
        LedgerEntry.objects.create(kind="income", amount=5_000)
    executor = MigrationExecutor(connection)
    executor.migrate([("finance", "0007_alter_installment_amount_alter_ledgerentry_amount")])  # unapply the data step
    executor = MigrationExecutor(connection)
    with tenant_context(tenant):
        assert Policy.objects.get().premium == 100_000  # ÷10 on the way back
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())
    with tenant_context(tenant):
        p = Policy.objects.get()
        assert p.premium == 1_000_000 and p.commission_received == 80_000
        assert Installment.objects.get().amount == 250_000 and LedgerEntry.objects.get().amount == 5_000
