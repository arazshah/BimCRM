from celery import shared_task

from .services import run_daily_work


@shared_task
def daily_work():
    return run_daily_work()
