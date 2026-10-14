"""Customer club: points for policies, renewals, on-time installments and referrals; tiers by lifetime points."""

from django.conf import settings
from django.db import models

from apps.core.models import TenantOwned


class ClubSettings(TenantOwned):
    enabled = models.BooleanField("باشگاه مشتریان فعال است", default=True)
    points_per_million = models.PositiveIntegerField(
        "امتیاز به ازای هر یک میلیون تومان حق بیمه", default=10, help_text="مثلاً بیمه‌نامه ۸ میلیونی = ۸۰ امتیاز"
    )
    renewal_bonus = models.PositiveIntegerField("جایزه تمدید", default=50)
    installment_bonus = models.PositiveIntegerField("جایزه پرداخت به‌موقع هر قسط", default=5)
    referral_bonus = models.PositiveIntegerField(
        "جایزه معرفی مشتری", default=100, help_text="وقتی مشتری معرفی‌شده اولین بیمه‌نامه‌اش را بگیرد، به معرف می‌رسد"
    )
    silver_at = models.PositiveIntegerField("حد سطح نقره‌ای (امتیاز کل)", default=200)
    gold_at = models.PositiveIntegerField("حد سطح طلایی (امتیاز کل)", default=500)
    perks = models.TextField(
        "امتیازها را چطور می‌شود خرج کرد",
        blank=True,
        default="هر ۱۰۰ امتیاز = ۱۰۰ هزار تومان تخفیف در تمدید بعدی. مشتریان طلایی: مشاوره و پیگیری خسارت ویژه.",
        help_text="در پنل مشتری روی سایت نمایش داده می‌شود",
    )
    sms_on_reward = models.BooleanField("پیامک تبریک هنگام گرفتن جایزه معرفی یا رسیدن به سطح بالاتر", default=True)

    class Meta:
        verbose_name = "تنظیمات باشگاه مشتریان"
        verbose_name_plural = "تنظیمات باشگاه مشتریان"
        constraints = [models.UniqueConstraint(fields=["tenant"], name="one_club_settings")]

    @classmethod
    def for_tenant(cls, tenant):
        obj = cls.all_objects.filter(tenant=tenant).first()
        return obj or cls(tenant=tenant)

    def tier_for(self, lifetime: int) -> str:
        if lifetime >= self.gold_at:
            return "gold"
        if lifetime >= self.silver_at:
            return "silver"
        return "bronze"


TIER_LABELS = {"bronze": "برنزی", "silver": "نقره‌ای", "gold": "طلایی"}


class PointEntry(TenantOwned):
    class Reason(models.TextChoices):
        POLICY = "policy", "خرید بیمه‌نامه"
        RENEWAL = "renewal", "جایزه تمدید"
        INSTALLMENT = "installment", "پرداخت به‌موقع قسط"
        REFERRAL = "referral", "معرفی مشتری"
        REDEEM = "redeem", "استفاده از امتیاز"
        MANUAL = "manual", "ثبت دستی"

    customer = models.ForeignKey("crm.Customer", on_delete=models.CASCADE, related_name="points")
    points = models.IntegerField("امتیاز")
    reason = models.CharField("بابت", max_length=20, choices=Reason.choices)
    note = models.CharField("توضیح", max_length=160, blank=True)
    policy = models.ForeignKey("crm.Policy", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    key = models.CharField(max_length=80, blank=True, help_text="Prevents awarding the same thing twice")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "امتیاز"
        verbose_name_plural = "امتیازها"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], condition=~models.Q(key=""), name="unique_point_key")
        ]
