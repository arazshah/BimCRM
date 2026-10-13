from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.accounts.sms import send_platform_text
from apps.core.models import PlatformSettings

from .models import Subscription


def run_lifecycle(now=None):
    """trial/active -> grace at period end -> expired (read-only) after grace days. Reminds 3 days before."""
    now = now or timezone.now()
    grace = timedelta(days=PlatformSettings.load().grace_days)
    live = [Subscription.Status.TRIAL, Subscription.Status.ACTIVE]

    for sub in Subscription.objects.filter(
        status__in=live,
        current_period_end__lte=now + timedelta(days=3),
        current_period_end__gt=now,
        reminded_at__isnull=True,
    ):
        send_platform_text(
            sub.tenant.owner.mobile,
            f"CRM بیمه: اشتراک «{sub.tenant.name}» تا {sub.days_left} روز دیگر تمام می‌شود. تمدید از بخش اشتراک پنل.",
        )
        sub.reminded_at = now
        sub.save(update_fields=["reminded_at"])

    Subscription.objects.filter(status__in=live, current_period_end__lte=now).update(status=Subscription.Status.GRACE)
    Subscription.objects.filter(status=Subscription.Status.GRACE, current_period_end__lte=now - grace).update(
        status=Subscription.Status.EXPIRED
    )


@shared_task
def run_subscription_lifecycle():
    run_lifecycle()
