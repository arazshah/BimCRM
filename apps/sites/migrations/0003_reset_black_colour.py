from django.db import migrations


class Migration(migrations.Migration):
    """Sites saved before the colour-picker fix stored #000000 instead of following their template."""

    dependencies = [("sites", "0002_rls")]
    operations = [
        migrations.RunSQL(
            "UPDATE sites_sitesettings SET primary_color = '' WHERE lower(primary_color) = '#000000'",
            migrations.RunSQL.noop,
        )
    ]
