"""Creates the super admin from SUPERADMIN_MOBILE on deploy if they don't exist yet.

The password comes from SUPERADMIN_PASSWORD when set; otherwise a random one is printed once in the
deploy log. Change it after first login.
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
        password = settings.SUPERADMIN_PASSWORD or secrets.token_urlsafe(12)
        user, created = User.objects.get_or_create(mobile=mobile)
        user.is_staff = user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(
            self.style.WARNING(
                f"Super admin {mobile} {'created' if created else 'promoted'}."
                + ("" if settings.SUPERADMIN_PASSWORD else f" One-time password: {password}")
            )
        )
