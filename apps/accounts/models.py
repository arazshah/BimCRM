import re

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

MOBILE_RE = re.compile(r"^09\d{9}$")
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_mobile(value: str) -> str:
    value = (value or "").translate(_FA_DIGITS)
    value = re.sub(r"[\s\-()]", "", value)
    if value.startswith("+98"):
        value = "0" + value[3:]
    elif value.startswith("0098"):
        value = "0" + value[4:]
    elif value.startswith("98") and len(value) == 12:
        value = "0" + value[2:]
    elif value.startswith("9") and len(value) == 10:
        value = "0" + value
    return value


def validate_mobile(value: str):
    if not MOBILE_RE.match(value or ""):
        raise ValidationError("شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود.")


class UserManager(BaseUserManager):
    def create_user(self, mobile, password=None, **extra):
        mobile = normalize_mobile(mobile)
        validate_mobile(mobile)
        user = self.model(mobile=mobile, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, mobile, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(mobile, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    mobile = models.CharField("موبایل", max_length=11, unique=True, validators=[validate_mobile])
    full_name = models.CharField("نام و نام خانوادگی", max_length=120, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    is_staff = models.BooleanField("دسترسی سوپرادمین", default=False)
    date_joined = models.DateTimeField("عضویت", default=timezone.now)

    USERNAME_FIELD = "mobile"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"

    def __str__(self):
        return self.full_name or self.mobile


class Membership(models.Model):
    """A user's role inside one agency workspace."""

    class Role(models.TextChoices):
        OWNER = "owner", "مالک"
        MANAGER = "manager", "مدیر"
        STAFF = "staff", "کارمند"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField("نقش", max_length=20, choices=Role.choices, default=Role.STAFF)
    branch = models.ForeignKey(
        "crm.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="شعبه",
        help_text="کارمند شعبه فقط مشتریان و پرونده‌های همان شعبه را می‌بیند",
    )
    is_active = models.BooleanField("فعال", default=True)
    calendar_token = models.CharField(max_length=64, blank=True, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "عضویت"
        verbose_name_plural = "عضویت‌ها"
        unique_together = [("user", "tenant")]

    def __str__(self):
        return f"{self.user} @ {self.tenant.slug} ({self.get_role_display()})"


class OTPCode(models.Model):
    mobile = models.CharField(max_length=11, db_index=True)
    code_hash = models.CharField(max_length=128)
    purpose = models.CharField(max_length=20, default="login")
    scope = models.CharField(max_length=40, default="platform", help_text="platform or tenant:<id>")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["mobile", "scope", "created_at"])]
