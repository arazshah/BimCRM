from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("messaging", "0001_initial")]
    operations = [enable_rls_operation("messaging_remindersettings", "messaging_campaign", "messaging_messagelog")]
