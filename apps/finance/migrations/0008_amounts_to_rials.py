"""The office books move from tomans to rials: every existing money value is multiplied by 10 (once)."""

from django.db import migrations
from django.db.models import F

FIELDS = [
    ("crm", "Policy", ["premium", "commission_received"]),
    ("finance", "Installment", ["amount"]),
    ("finance", "LedgerEntry", ["amount"]),
    ("network", "MarketerPayout", ["amount"]),
    ("claims", "Claim", ["amount_claimed", "amount_paid"]),
]


def _scale(apps, factor_up: bool):
    for app, model, fields in FIELDS:
        Model = apps.get_model(app, model)
        for field in fields:
            expr = F(field) * 10 if factor_up else F(field) / 10
            Model._default_manager.update(**{field: expr})


def to_rials(apps, schema_editor):
    _scale(apps, True)


def to_tomans(apps, schema_editor):
    _scale(apps, False)


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0007_alter_installment_amount_alter_ledgerentry_amount"),
        ("crm", "0009_alter_policy_commission_received_and_more"),
        ("network", "0003_alter_marketerpayout_amount"),
        ("claims", "0005_alter_claim_amount_claimed_alter_claim_amount_paid"),
    ]
    operations = [migrations.RunPython(to_rials, to_tomans)]
