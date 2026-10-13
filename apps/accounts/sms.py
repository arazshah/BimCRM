"""Platform SMS through sms.ir. Used only for the platform's own messages."""

import logging

import requests

from apps.core.platform_config import sms_backend, smsir_config

log = logging.getLogger(__name__)

SMSIR_BASE = "https://api.sms.ir/v1"


class SmsError(Exception):
    pass


class SmsIrClient:
    def __init__(self, api_key: str, line_number: str = "", otp_template_id: str = ""):
        self.api_key = api_key
        self.line_number = line_number
        self.otp_template_id = otp_template_id

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = requests.post(
                f"{SMSIR_BASE}{path}",
                json=payload,
                headers={"X-API-KEY": self.api_key, "Accept": "application/json"},
                timeout=10,
            )
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise SmsError(f"sms.ir unreachable: {exc}") from exc
        if data.get("status") != 1:
            raise SmsError(f"sms.ir error: {data.get('message')}")
        return data

    def send_verify(self, mobile: str, code: str):
        if not self.otp_template_id:
            raise SmsError("شناسه قالب کد تأیید sms.ir تنظیم نشده است.")
        return self._post(
            "/send/verify",
            {
                "mobile": mobile,
                "templateId": int(self.otp_template_id),
                "parameters": [{"name": "CODE", "value": code}],
            },
        )

    def send_text(self, mobile: str, text: str):
        return self._post(
            "/send/bulk", {"lineNumber": int(self.line_number or 0), "messageText": text, "mobiles": [mobile]}
        )

    def credit(self) -> float:
        try:
            resp = requests.get(f"{SMSIR_BASE}/credit", headers={"X-API-KEY": self.api_key}, timeout=10)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise SmsError(str(exc)) from exc
        if data.get("status") != 1:
            raise SmsError(data.get("message") or "invalid key")
        return float(data.get("data") or 0)


def send_platform_otp(mobile: str, code: str):
    if sms_backend() == "console":
        log.warning("OTP for %s: %s", mobile, code)
        return
    cfg = smsir_config()
    SmsIrClient(cfg.api_key, cfg.line_number, cfg.otp_template_id).send_verify(mobile, code)


def send_platform_text(mobile: str, text: str):
    if sms_backend() == "console":
        log.warning("SMS to %s: %s", mobile, text)
        return
    try:
        cfg = smsir_config()
        SmsIrClient(cfg.api_key, cfg.line_number).send_text(mobile, text)
    except SmsError:
        log.exception("platform SMS to %s failed", mobile)
