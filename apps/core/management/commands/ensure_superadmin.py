"""Makes sure the platform super admin exists (from SUPERADMIN_MOBILE) on every deploy.

- Missing: created with SUPERADMIN_PASSWORD, or a random one printed in the deploy log.
- Existing but never logged in (last_login is empty): the first password is issued again the same way,
  so a lost or never-seen first password is fixed by simply redeploying.
- Existing and already used: left untouched, so a password you changed is never overwritten.
"""

import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the platform super admin from SUPERADMIN_MOBILE if missing (or reissue the unused first password)."

    def handle(self, *args, **options):
        mobile = settings.SUPERADMIN_MOBILE
        if not mobile:
            self.stdout.write("SUPERADMIN_MOBILE not set; skipping.")
            return
        User = get_user_model()
        user = User.objects.filter(mobile=mobile).first()
        if user and user.is_superuser and user.last_login is not None:
            self.stdout.write("Super admin already exists and has logged in; password left unchanged.")
            return
        random_password = not settings.SUPERADMIN_PASSWORD
        password = settings.SUPERADMIN_PASSWORD or secrets.token_urlsafe(12)
        created = user is None
        if created:
            user = User(mobile=mobile)
        user.is_staff = user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()
        what = "created" if created else "first password reissued"
        msg = f"Super admin {mobile} {what}."
        if random_password:
            msg += f"\n>>> SUPERADMIN ONE-TIME PASSWORD: {password}  (change it after the first login)"
        self.stdout.write(self.style.WARNING(msg))
