from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import LineOfBusiness, TenantOwned

from . import registry

hex_color = RegexValidator(r"^#[0-9a-fA-F]{6}$", "رنگ را به شکل #1d3557 وارد کنید.")


MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_GALLERY_IMAGES = 8


def validate_image_size(file):
    if file.size > MAX_IMAGE_BYTES:
        raise ValidationError("حجم تصویر باید کمتر از ۳ مگابایت باشد.")


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


class SiteLineContent(TenantOwned):
    """Agency-authored public details for one insurance line."""

    line = models.ForeignKey(LineOfBusiness, on_delete=models.PROTECT, verbose_name="رشته بیمه")
    intro = models.CharField("معرفی کوتاه", max_length=255, blank=True)
    cover = models.ImageField(
        "تصویر شاخص",
        upload_to="lines/",
        blank=True,
        validators=[validate_image_size],
        help_text="تصویر بزرگ بالای صفحه (افقی، حداقل ۱۲۰۰ پیکسل عرض). حداکثر ۳ مگابایت.",
    )
    cover_alt = models.CharField("توضیح تصویر شاخص", max_length=120, blank=True)
    highlights = models.TextField(
        "نکات برجسته",
        blank=True,
        help_text="هر خط یک نکتهٔ کوتاه؛ مثل «پاسخ در همان روز کاری». حداکثر ۶ مورد نمایش داده می‌شود.",
    )
    description = models.TextField("توضیحات رشته", blank=True)
    coverage = models.TextField("پوشش‌هایی که دفتر بررسی می‌کند", blank=True)
    considerations = models.TextField("شرایطی که مشتری باید بررسی کند", blank=True)
    documents = models.TextField("مدارک و اطلاعات موردنیاز", blank=True)
    process = models.TextField("روند درخواست تا پاسخ دفتر", blank=True)
    seo_title = models.CharField("عنوان صفحه برای گوگل", max_length=120, blank=True)
    seo_description = models.CharField("توضیح صفحه برای گوگل", max_length=160, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "محتوای رشته در سایت"
        verbose_name_plural = "محتوای رشته‌های سایت"
        constraints = [models.UniqueConstraint(fields=["tenant", "line"], name="one_site_line_content_per_tenant")]

    def __str__(self):
        return f"{self.line} — {self.tenant.name}"

    @property
    def highlight_list(self):
        return [line.strip() for line in self.highlights.splitlines() if line.strip()][:6]


class SiteLineImage(TenantOwned):
    """One gallery picture on an insurance line's public page."""

    content = models.ForeignKey(
        SiteLineContent, on_delete=models.CASCADE, related_name="images", verbose_name="محتوای رشته"
    )
    image = models.ImageField("تصویر", upload_to="lines/gallery/", validators=[validate_image_size])
    caption = models.CharField("شرح تصویر", max_length=120, blank=True)
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        verbose_name = "تصویر رشته"
        verbose_name_plural = "تصاویر رشته‌ها"
        ordering = ["order", "id"]

    def __str__(self):
        return self.caption or f"تصویر {self.pk}"


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
