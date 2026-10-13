from celery import shared_task

from apps.core.tenancy import tenant_context

from .models import Campaign
from .services import run_campaign, send_all_daily_reminders


@shared_task
def daily_reminders():
    return send_all_daily_reminders()


@shared_task
def run_campaign_task(campaign_id: int):
    campaign = Campaign.all_objects.select_related("tenant").filter(pk=campaign_id).first()
    if campaign and campaign.status == Campaign.Status.DRAFT:
        with tenant_context(campaign.tenant):
            run_campaign(campaign)
