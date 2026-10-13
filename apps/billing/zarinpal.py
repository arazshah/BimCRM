"""Zarinpal REST v4 — used only for the platform's own sales (subscriptions and add-ons)."""

import requests

from apps.core.platform_config import zarinpal_config


class ZarinpalError(Exception):
    pass


def _base() -> str:
    return "https://sandbox.zarinpal.com" if zarinpal_config()[1] else "https://payment.zarinpal.com"


def request_payment(amount_toman: int, description: str, callback_url: str, mobile: str = "") -> tuple[str, str]:
    """Returns (authority, redirect_url)."""
    payload = {
        "merchant_id": zarinpal_config()[0],
        "amount": int(amount_toman),
        "currency": "IRT",
        "description": description[:255],
        "callback_url": callback_url,
        "metadata": {"mobile": mobile} if mobile else {},
    }
    try:
        data = requests.post(f"{_base()}/pg/v4/payment/request.json", json=payload, timeout=15).json()
    except (requests.RequestException, ValueError) as exc:
        raise ZarinpalError("اتصال به زرین‌پال برقرار نشد.") from exc
    body = data.get("data") or {}
    if body.get("code") != 100:
        raise ZarinpalError(f"زرین‌پال درخواست را نپذیرفت ({_error_text(data)}).")
    authority = body["authority"]
    return authority, f"{_base()}/pg/StartPay/{authority}"


def verify_payment(amount_toman: int, authority: str) -> str:
    """Returns the ref_id when the payment is confirmed (code 100 or 101)."""
    payload = {"merchant_id": zarinpal_config()[0], "amount": int(amount_toman), "authority": authority}
    try:
        data = requests.post(f"{_base()}/pg/v4/payment/verify.json", json=payload, timeout=15).json()
    except (requests.RequestException, ValueError) as exc:
        raise ZarinpalError("اتصال به زرین‌پال برقرار نشد.") from exc
    body = data.get("data") or {}
    if body.get("code") in (100, 101):
        return str(body.get("ref_id", ""))
    raise ZarinpalError(f"پرداخت تأیید نشد ({_error_text(data)}).")


def _error_text(data: dict) -> str:
    errors = data.get("errors")
    if isinstance(errors, dict):
        return str(errors.get("code", "")) + " " + str(errors.get("message", ""))
    return "نامشخص"
