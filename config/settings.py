"""Settings for CRM بیمه (bimcrm.ir). Every deploy-specific value comes from the environment."""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    SECURE_SSL=(bool, False),
    ZARINPAL_SANDBOX=(bool, True),
)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

DEBUG = env("DEBUG")
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key-change-me" if DEBUG else environ.Env.NOTSET)

# Hosts are validated by apps.core.middleware.TenantHostMiddleware (platform hosts,
# tenant subdomains and verified custom domains), so Django's own check is open.
ALLOWED_HOSTS = ["*"]

PLATFORM_DOMAIN = env("PLATFORM_DOMAIN", default="bimcrm.localhost")
PLATFORM_SCHEME = env("PLATFORM_SCHEME", default="http" if DEBUG else "https")
PLATFORM_NAMESERVERS = env.list("PLATFORM_NAMESERVERS", default=["ns1.bimcrm.ir", "ns2.bimcrm.ir"])
ADMIN_SUBDOMAIN = "admin"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "apps.core",
    "apps.accounts",
    "apps.billing",
    "apps.sites",
    "apps.crm",
    "apps.integrations",
    "apps.tickets",
    "apps.network",
    "apps.finance",
    "apps.claims",
    "apps.messaging",
    "apps.panel",
    "apps.main",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.core.middleware.TenantHostMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls_main"
URLCONF_ADMIN = "config.urls_admin"
URLCONF_TENANT = "config.urls_tenant"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.platform",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
DATABASES["default"]["CONN_MAX_AGE"] = 60

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
LOGIN_URL = "main:login"

LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sessions: one login across bimcrm.ir and *.bimcrm.ir
SESSION_COOKIE_DOMAIN = env("SESSION_COOKIE_DOMAIN", default=f".{PLATFORM_DOMAIN}")
CSRF_COOKIE_DOMAIN = SESSION_COOKIE_DOMAIN
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14

if env("SECURE_SSL"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True
USE_X_FORWARDED_HOST = True

# Celery
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "check-pending-domains": {"task": "apps.core.tasks.check_pending_domains", "schedule": 300.0},
    "subscription-lifecycle": {"task": "apps.billing.tasks.run_subscription_lifecycle", "schedule": 3600.0},
    # Customers' renewal, installment and birthday SMS go out at 10:00 Tehran time.
    "daily-reminders": {"task": "apps.messaging.tasks.daily_reminders", "schedule": crontab(hour=10, minute=0)},
}

# Platform SMS (sms.ir) — only for platform messages: OTP, subscription reminders, ticket replies
SMS_BACKEND = env("SMS_BACKEND", default="console")
SMSIR_API_KEY = env("SMSIR_API_KEY", default="")
SMSIR_OTP_TEMPLATE_ID = env("SMSIR_OTP_TEMPLATE_ID", default="")
SMSIR_LINE_NUMBER = env("SMSIR_LINE_NUMBER", default="")

# Platform payments (Zarinpal) — only for subscriptions and add-ons
ZARINPAL_MERCHANT_ID = env("ZARINPAL_MERCHANT_ID", default="")
ZARINPAL_SANDBOX = env("ZARINPAL_SANDBOX")

FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")
SUPERADMIN_MOBILE = env("SUPERADMIN_MOBILE", default="")
SUPERADMIN_PASSWORD = env("SUPERADMIN_PASSWORD", default="")

OTP_TTL_SECONDS = 120
OTP_RESEND_SECONDS = 60
OTP_MAX_PER_HOUR = 6
OTP_MAX_ATTEMPTS = 5

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
SILENCED_SYSTEM_CHECKS = ["models.W047"]  # SQLite (dev only) lacks NULLS NOT DISTINCT; PostgreSQL enforces it
