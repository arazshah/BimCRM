"""Shared with tests/test_content.py, so the seeding logic in 0014_showcase.py is covered without
needing a full migration-testing setup. Not itself a migration."""


def seed_first_showcase(apps, schema_editor):
    """The first agent to go live on their own domain: alborz8351.ir. No-op if it isn't found
    (e.g. a fresh dev/test database), and safe to run twice (get_or_create on the URL)."""
    Domain = apps.get_model("core", "Domain")
    Showcase = apps.get_model("core", "Showcase")
    domain = Domain.objects.filter(hostname="alborz8351.ir").select_related("tenant").first()
    if domain is None:
        return
    Showcase.objects.get_or_create(
        url=f"https://{domain.hostname}/",
        defaults={"tenant": domain.tenant, "name": domain.tenant.name, "order": 0},
    )
