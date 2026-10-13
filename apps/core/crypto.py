"""Symmetric encryption for secrets stored in the database (integration keys, platform API keys)."""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def fernet() -> Fernet:
    key = settings.FIELD_ENCRYPTION_KEY
    if not key:
        # Development fallback derived from SECRET_KEY; production must set FIELD_ENCRYPTION_KEY.
        import base64
        import hashlib

        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_text(value: str) -> str:
    return fernet().encrypt(value.encode()).decode() if value else ""


def decrypt_text(token: str) -> str:
    if not token:
        return ""
    try:
        return fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""
