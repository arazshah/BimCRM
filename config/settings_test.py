"""Test settings: safe defaults, then the normal settings."""

import os

os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("PLATFORM_DOMAIN", "bimcrm.test")
os.environ.setdefault("SMS_BACKEND", "console")

from .settings import *  # noqa: E402,F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
