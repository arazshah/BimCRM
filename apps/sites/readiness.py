def publication_issues(site):
    """Return the minimum content needed to make a public agency site useful."""
    issues = []
    if not site.lines.filter(is_active=True).exists():
        issues.append("دست‌کم یک رشتهٔ بیمهٔ فعال برای استعلام انتخاب کنید.")
    if not any((site.phone.strip(), site.email.strip(), site.whatsapp.strip())):
        issues.append("برای پاسخ به مشتری، شمارهٔ تماس، ایمیل یا واتس‌اپ دفتر را ثبت کنید.")
    if not (site.hero_subtitle.strip() or site.about.strip()):
        issues.append("یک معرفی کوتاه از دفتر یا توضیحی دربارهٔ نحوهٔ پاسخ‌گویی بنویسید.")
    return issues
