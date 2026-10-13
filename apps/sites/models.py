from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import LineOfBusiness, TenantOwned

from . import registry

hex_color = RegexValidator(r"^#[0-9a-fA-F]{6}$", "رنگ را به شکل #1d3557 وارد کنید.")


class SiteSettings(TenantOwned):
    template = models.CharField("قالب", max_length=30, choices=registry.CHOICES, default="modern")
    primary_color = models.CharField(
        "رنگ اصلی", max_length=7, blank=True, validators=[hex_color], help_text="خالی = رنگ پیش‌فرض قالب"
    )
    is_published = models.BooleanField("سایت منتشر شده", default=False)
    logo = models.ImageField("لوگو", upload_to="logos/", blank=True)
    hero_title = models.CharField("عنوان اصلی", max_length=120, blank=True)
    hero_subtitle = models.CharField("زیرعنوان", max_length=255, blank=True)
    about = models.TextField("درباره دفتر", blank=True)
    years_active = models.PositiveIntegerField("سال‌های فعالیت", null=True, blank=True)
    customers_count = models.PositiveIntegerField("تعداد مشتری (برای نمایش)", null=True, blank=True)
    phone = models.CharField("تلفن نمایش در سایت", max_length=20, blank=True)
    whatsapp = models.CharField("واتس‌اپ/بله (شماره)", max_length=20, blank=True)
    email = models.EmailField("ایمیل", blank=True)
    address = models.CharField("نشانی", max_length=255, blank=True)
    working_hours = models.CharField("ساعات کاری", max_length=120, blank=True)
    lines = models.ManyToManyField(LineOfBusiness, blank=True, verbose_name="رشته‌های قابل استعلام")
    companies = models.ManyToManyField("core.InsuranceCompany", blank=True, verbose_name="شرکت‌های همکار")
    seo_description = models.CharField("توضیح برای گوگل", max_length=160, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیمات سایت"
        verbose_name_plural = "تنظیمات سایت‌ها"
        constraints = [models.UniqueConstraint(fields=["tenant"], name="one_site_per_tenant")]

    def __str__(self):
        return f"سایت {self.tenant.slug}"

    @property
    def template_info(self):
        return registry.get(self.template)

    @property
    def color(self):
        return self.primary_color or self.template_info.default_color


class Testimonial(TenantOwned):
    name = models.CharField("نام مشتری", max_length=80)
    text = models.CharField("متن", max_length=300)
    is_visible = models.BooleanField("نمایش", default=True)

    class Meta:
        verbose_name = "نظر مشتری"
        verbose_name_plural = "نظرات مشتریان"

    def __str__(self):
        return self.name


class FAQ(TenantOwned):
    question = models.CharField("سؤال", max_length=200)
    answer = models.TextField("پاسخ")
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        verbose_name = "سؤال متداول"
        verbose_name_plural = "سؤالات متداول"
        ordering = ["order", "id"]

    def __str__(self):
        return self.question
