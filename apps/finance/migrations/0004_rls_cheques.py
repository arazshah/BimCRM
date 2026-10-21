from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("finance", "0003_cheques_accounts")]
    operations = [enable_rls_operation("finance_financeaccount", "finance_cheque", "finance_chequeevent")]
