from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("finance", "0005_receipts_payments")]
    operations = [enable_rls_operation("finance_receipt", "finance_receiptline", "finance_paymentorder")]
