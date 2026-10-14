from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("crm", "0005_customerdocument")]
    operations = [enable_rls_operation("crm_customerdocument")]
