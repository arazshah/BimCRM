from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("work", "0001_initial")]
    operations = [enable_rls_operation("work_activity", "work_task", "work_notification")]
