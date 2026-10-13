from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("claims", "0001_initial")]
    operations = [enable_rls_operation("claims_claim")]
