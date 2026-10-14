from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("club", "0001_initial")]
    operations = [enable_rls_operation("club_clubsettings", "club_pointentry")]
