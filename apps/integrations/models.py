"""The agent's own services (payment gateway, SMS panel, trust seals, custom code).

The platform only stores the settings (credentials encrypted) and calls them on the agent's behalf.
Contracts, costs and legal responsibility stay with the agent.
"""

import json

from cryptography.fernet import InvalidToken
from django.db import models

from apps.core.crypto import fernet
from apps.core.models import TenantOwned

PROVIDERS = {
    "payment": {
        "zarinpal": {"label": "زرین‌پال", "fields": [("merchant_id", "مرچنت کد", True)]},
        "idpay": {"label": "آیدی‌پی", "fields": [("api_key", "کلید API", True)]},
    },
    "sms": {
        "smsir": {
            "label": "sms.ir",
            "fields": [
                ("api_key", "کلید API", True),
                ("line_number", "شماره خط", False),
                ("otp_template_id", "شناسه قالب کد تأیید", False),
            ],
        },
        "kavenegar": {
            "label": "کاوه‌نگار",
            "fields": [
                ("api_key", "کلید API", True),
                ("sender", "شماره خط", False),
                ("otp_template", "نام الگوی کد تأیید", False),
            ],
        },
        "melipayamak": {
            "label": "ملی‌پیامک",
            "fields": [
                ("username", "نام کاربری", True),
                ("password", "رمز وب‌سرویس", True),
                ("sender", "شماره خط", False),
            ],
        },
    },
    "trust": {
        "enamad": {
            "label": "اینماد",
            "fields": [("meta_code", "کد متاتگ تأیید دامنه", False), ("badge_html", "کد نماد (HTML)", False)],
        },
        "samandehi": {"label": "ساماندهی", "fields": [("badge_html", "کد نماد (HTML)", False)]},
    },
    "custom": {
        "head": {"label": "کد داخل head", "fields": [("code", "کد (آمارگیر، پیکسل و …)", False)]},
        "body": {"label": "کد انتهای صفحه", "fields": [("code", "کد (گفتگوی آنلاین و …)", False)]},
    },
}

KIND_LABELS = {"payment": "درگاه پرداخت", "sms": "پنل پیامک", "trust": "اینماد و ساماندهی", "custom": "کدهای دلخواه"}


_fernet = fernet


class Integration(TenantOwned):
    kind = models.CharField("نوع", max_length=20, choices=list(KIND_LABELS.items()))
    provider = models.CharField("سرویس", max_length=30)
    enabled = models.BooleanField("فعال", default=True)
    _config = models.TextField(db_column="config", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "اتصال نماینده"
        verbose_name_plural = "اتصالات نمایندگان"
        constraints = [models.UniqueConstraint(fields=["tenant", "kind", "provider"], name="one_integration_each")]

    def __str__(self):
        return f"{self.tenant.slug}: {self.provider_label}"

    @property
    def provider_label(self):
        return PROVIDERS.get(self.kind, {}).get(self.provider, {}).get("label", self.provider)

    @property
    def config(self) -> dict:
        if not self._config:
            return {}
        try:
            return json.loads(_fernet().decrypt(self._config.encode()).decode())
        except (InvalidToken, ValueError):
            return {}

    @config.setter
    def config(self, value: dict):
        self._config = _fernet().encrypt(json.dumps(value).encode()).decode()


def active_integration(tenant, kind: str):
    return Integration.all_objects.filter(tenant=tenant, kind=kind, enabled=True).order_by("-updated_at").first()
