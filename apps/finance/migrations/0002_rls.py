from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]
    operations = [enable_rls_operation("finance_commissionrule", "finance_installment", "finance_ledgerentry")]
