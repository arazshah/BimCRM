"""Platform-level service settings: the super admin's values win, the server environment is the fallback."""

from dataclasses import dataclass

from django.conf import settings

from .models import PlatformSettings


@dataclass(frozen=True)
class SmsIrConfig:
    api_key: str
    line_number: str
    otp_template_id: str


def sms_backend() -> str:
    """'console' prints codes to the server log; anything else sends for real through sms.ir."""
    return PlatformSettings.load().sms_backend or settings.SMS_BACKEND


def smsir_config() -> SmsIrConfig:
    p = PlatformSettings.load()
    return SmsIrConfig(
        api_key=p.smsir_api_key or settings.SMSIR_API_KEY,
        line_number=p.smsir_line_number or settings.SMSIR_LINE_NUMBER,
        otp_template_id=p.smsir_otp_template_id or settings.SMSIR_OTP_TEMPLATE_ID,
    )


def zarinpal_config() -> tuple[str, bool]:
    """Returns (merchant_id, sandbox)."""
    p = PlatformSettings.load()
    merchant = p.zarinpal_merchant_id or settings.ZARINPAL_MERCHANT_ID
    if p.zarinpal_mode == PlatformSettings.ZarinpalMode.SANDBOX:
        sandbox = True
    elif p.zarinpal_mode == PlatformSettings.ZarinpalMode.LIVE:
        sandbox = False
    else:
        sandbox = settings.ZARINPAL_SANDBOX
    return merchant, sandbox
