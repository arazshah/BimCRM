from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("sites", "0001_initial")]
    operations = [enable_rls_operation("sites_sitesettings", "sites_testimonial", "sites_faq")]
