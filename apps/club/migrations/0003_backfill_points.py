"""Credits club points for policies registered before the club existed, so offices start with real tiers."""

from django.db import migrations
from django.db.models import Sum


def backfill(apps, schema_editor):
    Policy = apps.get_model("crm", "Policy")
    Customer = apps.get_model("crm", "Customer")
    PointEntry = apps.get_model("club", "PointEntry")
    done = set(PointEntry.objects.exclude(key="").values_list("tenant_id", "key"))
    rows = []
    for p in Policy.objects.all().only("pk", "tenant_id", "customer_id", "premium", "renewed_from_id"):
        key = f"policy:{p.pk}"
        if (p.tenant_id, key) not in done and p.premium:
            rows.append(
                PointEntry(
                    tenant_id=p.tenant_id,
                    customer_id=p.customer_id,
                    points=p.premium * 10 // 1_000_000,
                    reason="policy",
                    key=key,
                    note="امتیاز بیمه‌نامه‌های قبلی",
                )
            )
        if p.renewed_from_id and (p.tenant_id, f"renewal:{p.pk}") not in done:
            rows.append(
                PointEntry(
                    tenant_id=p.tenant_id, customer_id=p.customer_id, points=50, reason="renewal", key=f"renewal:{p.pk}"
                )
            )
    PointEntry.objects.bulk_create([r for r in rows if r.points], batch_size=500)
    for c in Customer.objects.filter(pk__in=PointEntry.objects.values("customer_id")):
        entries = PointEntry.objects.filter(customer_id=c.pk)
        balance = entries.aggregate(s=Sum("points"))["s"] or 0
        lifetime = entries.filter(points__gt=0).aggregate(s=Sum("points"))["s"] or 0
        tier = "gold" if lifetime >= 500 else "silver" if lifetime >= 200 else "bronze"
        Customer.objects.filter(pk=c.pk).update(points_balance=balance, points_lifetime=lifetime, tier=tier)


class Migration(migrations.Migration):
    dependencies = [("club", "0002_rls"), ("crm", "0007_customer_points_balance_customer_points_lifetime_and_more")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
