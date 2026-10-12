from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Membership
from apps.core.models import PlatformSettings, Tenant

from .models import Addon, Package, StorageTier, Subscription, SubscriptionItem


@transaction.atomic
def create_workspace(
    *, owner, name: str, slug: str, template: str, storage_tier: StorageTier, addons: dict[Addon, int], period: str
) -> Tenant:
    from apps.sites.models import SiteSettings

    tenant = Tenant.objects.create(name=name, slug=slug, owner=owner)
    Membership.objects.create(user=owner, tenant=tenant, role=Membership.Role.OWNER)
    trial_days = PlatformSettings.load().trial_days
    sub = Subscription.objects.create(
        tenant=tenant,
        package=Package.default(),
        storage_tier=storage_tier,
        period=period,
        status=Subscription.Status.TRIAL,
        current_period_end=timezone.now() + timedelta(days=trial_days),
    )
    for addon, qty in addons.items():
        if qty > 0:
            SubscriptionItem.objects.create(subscription=sub, addon=addon, quantity=qty)
    SiteSettings.objects.create(tenant=tenant, template=template, hero_title=name)
    return tenant
