from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.crm.models import Policy


@receiver(post_save, sender=Policy, dispatch_uid="club_policy_points")
def policy_points(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        from .services import on_policy_created

        on_policy_created(instance)
