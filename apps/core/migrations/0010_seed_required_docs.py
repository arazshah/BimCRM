from django.db import migrations

DOCS = {
    "third-party": ["national_card", "car_card", "prev_policy", "no_claim"],
    "car-body": ["national_card", "car_card", "prev_policy", "car_photos"],
    "home-fire": ["national_card", "property"],
    "life": ["national_card", "birth_cert", "medical"],
    "health": ["national_card", "birth_cert"],
    "travel": ["passport", "national_card"],
    "liability": ["national_card"],
}


def seed(apps, schema_editor):
    Line = apps.get_model("core", "LineOfBusiness")
    for slug, docs in DOCS.items():
        Line.objects.filter(slug=slug, required_docs=[]).update(required_docs=docs)


class Migration(migrations.Migration):
    dependencies = [("core", "0009_lineofbusiness_required_docs")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
