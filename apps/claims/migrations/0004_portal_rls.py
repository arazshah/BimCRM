from django.db import migrations

from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):
    dependencies = [("claims", "0003_claim_portal")]
    operations = [enable_rls_operation("claims_claimdocrequest", "claims_claimmessage", "claims_claimformfile")]
