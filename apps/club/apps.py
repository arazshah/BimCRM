from django.apps import AppConfig


class ClubConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.club"
    verbose_name = "باشگاه مشتریان"

    def ready(self):
        from . import signals  # noqa: F401
