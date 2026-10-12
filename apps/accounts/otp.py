"""One-time codes with rate limits. The sender is pluggable so tenants can use their own SMS panel."""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import OTPCode


class OTPError(Exception):
    pass


def issue_code(mobile: str, sender, scope: str = "platform", purpose: str = "login") -> None:
    now = timezone.now()
    recent = OTPCode.objects.filter(mobile=mobile, scope=scope)
    last = recent.order_by("-created_at").first()
    if last and (now - last.created_at).total_seconds() < settings.OTP_RESEND_SECONDS:
        wait = int(settings.OTP_RESEND_SECONDS - (now - last.created_at).total_seconds())
        raise OTPError(f"کد قبلی هنوز معتبر است. {wait} ثانیه دیگر دوباره تلاش کنید.")
    if recent.filter(created_at__gte=now - timedelta(hours=1)).count() >= settings.OTP_MAX_PER_HOUR:
        raise OTPError("تعداد درخواست کد در این ساعت زیاد بوده است. کمی بعد تلاش کنید.")

    code = f"{secrets.randbelow(100000):05d}"
    OTPCode.objects.create(
        mobile=mobile,
        scope=scope,
        purpose=purpose,
        code_hash=make_password(code),
        expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
    )
    sender(mobile, code)


def verify_code(mobile: str, code: str, scope: str = "platform") -> bool:
    code = (code or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    otp = (
        OTPCode.objects.filter(mobile=mobile, scope=scope, used=False, expires_at__gt=timezone.now())
        .order_by("-created_at")
        .first()
    )
    if otp is None:
        raise OTPError("کد منقضی شده است. کد جدید بگیرید.")
    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise OTPError("تعداد تلاش‌ها زیاد بود. کد جدید بگیرید.")
    if not check_password(code, otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        raise OTPError("کد وارد شده درست نیست.")
    otp.used = True
    otp.save(update_fields=["used"])
    return True
