"""Sending SMS through the agent's own panel. If the agent has none, nothing is sent."""

import logging

import requests

from apps.accounts.sms import SmsError, SmsIrClient
from apps.core.platform_config import sms_backend

from .models import active_integration

log = logging.getLogger(__name__)


def tenant_can_sms(tenant) -> bool:
    return active_integration(tenant, "sms") is not None


def _kavenegar(cfg: dict, method: str, params: dict) -> dict:
    try:
        data = requests.post(
            f"https://api.kavenegar.com/v1/{cfg['api_key']}/{method}.json", data=params, timeout=10
        ).json()
    except (requests.RequestException, ValueError) as exc:
        raise SmsError(str(exc)) from exc
    if (data.get("return") or {}).get("status") != 200:
        raise SmsError((data.get("return") or {}).get("message", "kavenegar error"))
    return data


def send_tenant_otp(tenant, mobile: str, code: str):
    integ = active_integration(tenant, "sms")
    if integ is None:
        raise SmsError("این دفتر هنوز پنل پیامک وصل نکرده است.")
    cfg = integ.config
    if sms_backend() == "console":
        log.warning("[tenant %s] OTP for %s: %s", tenant.slug, mobile, code)
        return
    if integ.provider == "smsir":
        client = SmsIrClient(cfg.get("api_key", ""), cfg.get("line_number", ""), cfg.get("otp_template_id", ""))
        if cfg.get("otp_template_id"):
            client.send_verify(mobile, code)
        else:
            client.send_text(mobile, f"کد ورود: {code}\n{tenant.name}")
    elif integ.provider == "kavenegar":
        if cfg.get("otp_template"):
            _kavenegar(cfg, "verify/lookup", {"receptor": mobile, "token": code, "template": cfg["otp_template"]})
        else:
            _kavenegar(
                cfg,
                "sms/send",
                {"receptor": mobile, "sender": cfg.get("sender", ""), "message": f"کد ورود: {code}\n{tenant.name}"},
            )
    elif integ.provider == "melipayamak":
        send_tenant_text(tenant, mobile, f"کد ورود: {code}\n{tenant.name}")
    else:
        raise SmsError("سرویس پیامک پشتیبانی نمی‌شود.")


def send_tenant_text(tenant, mobile: str, text: str):
    integ = active_integration(tenant, "sms")
    if integ is None:
        raise SmsError("این دفتر هنوز پنل پیامک وصل نکرده است.")
    cfg = integ.config
    if sms_backend() == "console":
        log.warning("[tenant %s] SMS to %s: %s", tenant.slug, mobile, text)
        return
    if integ.provider == "smsir":
        SmsIrClient(cfg.get("api_key", ""), cfg.get("line_number", "")).send_text(mobile, text)
    elif integ.provider == "kavenegar":
        _kavenegar(cfg, "sms/send", {"receptor": mobile, "sender": cfg.get("sender", ""), "message": text})
    elif integ.provider == "melipayamak":
        try:
            data = requests.post(
                "https://rest.payamak-panel.com/api/SendSMS/SendSMS",
                data={
                    "username": cfg.get("username"),
                    "password": cfg.get("password"),
                    "to": mobile,
                    "from": cfg.get("sender", ""),
                    "text": text,
                    "isflash": "false",
                },
                timeout=10,
            ).json()
        except (requests.RequestException, ValueError) as exc:
            raise SmsError(str(exc)) from exc
        if str(data.get("RetStatus")) != "1":
            raise SmsError(data.get("StrRetStatus", "melipayamak error"))


def test_connection(integration) -> tuple[bool, str]:
    """Checks the credentials without sending anything, where the provider allows it."""
    cfg = integration.config
    try:
        if integration.kind == "sms" and integration.provider == "smsir":
            credit = SmsIrClient(cfg.get("api_key", "")).credit()
            return True, f"اتصال برقرار است. اعتبار: {credit:,.0f}"
        if integration.kind == "sms" and integration.provider == "kavenegar":
            data = _kavenegar(cfg, "account/info", {})
            return True, f"اتصال برقرار است. اعتبار: {data.get('entries', {}).get('remaincredit', '?')}"
    except SmsError as exc:
        return False, f"اتصال برقرار نشد: {exc}"
    except KeyError:
        return False, "فیلدهای ضروری را کامل کنید."
    return True, "ذخیره شد. این سرویس آزمایش خودکار ندارد؛ با یک تراکنش یا پیام واقعی امتحان کنید."
