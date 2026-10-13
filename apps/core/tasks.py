from celery import shared_task

from .dns import check_domain
from .models import Domain


@shared_task
def check_domain_task(domain_id: int):
    domain = Domain.objects.filter(pk=domain_id).first()
    if domain:
        check_domain(domain)


@shared_task
def check_pending_domains():
    """Every 5 minutes: activate domains whose NS now point here, flag active ones that moved away."""
    for domain in Domain.objects.all().iterator():
        check_domain(domain)
