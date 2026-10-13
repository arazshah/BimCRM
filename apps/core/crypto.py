"""Symmetric encryption for secrets stored in the database (integration keys, platform API keys)."""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _normalize(raw: str) -> bytes:
    """Forgives common copy/paste damage: surrounding spaces or quotes and a lost trailing '=' padding."""
    key = (raw or "").strip().strip("'\"").strip()
    key += "=" * (-len(key) % 4)
    return key.encode()


def fernet() -> Fernet:
    raw = settings.FIELD_ENCRYPTION_KEY
    if not raw:
        # Development fallback derived from SECRET_KEY; production must set FIELD_ENCRYPTION_KEY.
        import base64
        import hashlib

        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()))
    try:
        return Fernet(_normalize(raw))
    except ValueError as exc:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is not a valid Fernet key (44 characters ending in '='). "
            'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        ) from exc


def encrypt_text(value: str) -> str:
    return fernet().encrypt(value.encode()).decode() if value else ""


def decrypt_text(token: str) -> str:
    if not token:
        return ""
    try:
        return fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""
