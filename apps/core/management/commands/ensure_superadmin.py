"""Creates the super admin from SUPERADMIN_MOBILE on deploy if they don't exist yet.

The password is printed once in the deploy log; change it after first login.
"""

import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the platform super admin from SUPERADMIN_MOBILE if missing."

    def handle(self, *args, **options):
        mobile = settings.SUPERADMIN_MOBILE
        if not mobile:
            self.stdout.write("SUPERADMIN_MOBILE not set; skipping.")
            return
        User = get_user_model()
        if User.objects.filter(mobile=mobile, is_superuser=True).exists():
            self.stdout.write("Super admin already exists.")
            return
        password = secrets.token_urlsafe(12)
        user, created = User.objects.get_or_create(mobile=mobile)
        user.is_staff = user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(
            self.style.WARNING(
                f"Super admin {mobile} {'created' if created else 'promoted'}. One-time password: {password}"
            )
        )
