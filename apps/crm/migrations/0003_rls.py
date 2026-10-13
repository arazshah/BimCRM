from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("crm", "0002_customer_marketer_customer_sms_opt_out_and_more")]
    operations = [enable_rls_operation("crm_customer", "crm_policy", "crm_quoterequest")]
