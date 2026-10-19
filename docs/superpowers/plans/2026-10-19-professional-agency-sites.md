# برنامهٔ اجرا: تجربهٔ حرفه‌ای سایت نمایندگی

**مشخصات:** [2026-10-19-professional-agency-sites-design.md](../specs/2026-10-19-professional-agency-sites-design.md)  
**وضعیت:** تکمیل؛ آمادهٔ بازبینی و ادغام پس از تصمیم کاربر  
**روش:** TDD؛ برای هر برش ابتدا آزمون شکست‌خورده، سپس پیاده‌سازی کمینه، بعد بازآرایی.

## محدودیت‌های سراسری

- پنج قالب موجود حفظ شود؛ تصمیم‌های محتوایی میان پنج قالب مشترک بمانند.
- هیچ متن/قیمت/نظر/سابقهٔ ساختگی به سایت مشتری اضافه نشود.
- همهٔ queryها و فرم‌های دادهٔ tenant از `request.tenant` محدود شوند.
- فرم پیگیری، PII را در URL یا sitemap قرار ندهد.
- migration جدید باید RLS و الگوی migrationهای فعلی را حفظ کند.
- متن‌های رابط فارسی، RTL، mobile-first و accessible باشند.
- آزمون‌ها در `tests/test_agency_sites.py` (و migration/RLS در صورت لزوم) نگهداری شوند.

## مرحلهٔ 0 — خط مبنا و طراحی

- [x] آخرین `origin/main` را در worktree جدا دریافت کن.
- [x] مسئله، مرز محصول و معیار پذیرش را در مشخصات ثبت کن.
- [x] این برنامه را ثبت کن.
- [x] بررسی مشخصات و بازبینی پیاده‌سازی؛ اصلاح موارد باقی‌مانده.
- [x] اجرای مجموعهٔ pytest در PostgreSQL.

## مرحلهٔ 1 — دادهٔ قابل‌ویرایش برای رشته‌های نمایندگی

**فایل‌ها:** `apps/sites/models.py`, migration جدید `apps/sites/migrations/`, `apps/sites/admin.py`, `apps/panel/forms.py`, `apps/panel/views.py`, `templates/panel/site.html`.

- [x] آزمون: ذخیره و جداسازی SiteLineContent بر اساس tenant/line، و عدم دسترسی سایت tenant A به محتوای B.
- [x] مدل `SiteLineContent` یکتا برای tenant+line، شامل intro، توضیح پوشش/روند/مدارک و metadata قابل ویرایش.
- [x] فرم‌ست پنل فقط برای رشته‌های فعال دفتر؛ حفظ رکورد غیرفعال/موجود و امکان ذخیره امن چند فرم.
- [x] مهاجرت schema و RLS مطابق الگوی `apps/sites/migrations/0002_rls.py`.
- [x] اجرای آزمون مدل/پنل و `makemigrations --check`.

## مرحلهٔ 2 — صفحات و مسیرهای عمومی رشته‌ها

**فایل‌ها:** `apps/sites/urls.py`, `apps/sites/views.py`, `templates/sites/line_detail.html`, `templates/sites/parts/*`, `templates/sites/_head.html`, استایل مشترک.

- [x] آزمون: صفحهٔ رشتهٔ متعلق به سایت پاسخ 200، رشتهٔ ناموجود/غیرفعال/منتخب‌نشده 404، title/canonical/description متناسب.
- [x] افزودن `/insurance/<slug>/`؛ محتوای tenant به‌علاوهٔ fallback از کاتالوگ، فرم با رشتهٔ ازپیش‌انتخاب‌شده.
- [x] include مشترک برای توضیحات رشته، مدارک موجود، مراحل تماس، و CTA؛ عدم ادعای نرخ یا صدور آنلاین.
- [x] لینک همهٔ کارت‌های رشته در پنج قالب به صفحهٔ اختصاصی؛ anchor/form همچنان قابل دسترس.
- [x] بخش راهنمای خسارت و تمدید فقط با محتوای عمومی خنثی و مسیر تماس/پنل واقعی.

## مرحلهٔ 3 — ایمن‌سازی و تکمیل فرم استعلام/پیگیری

**فایل‌ها:** `apps/sites/views.py`, `templates/sites/_quote_form.html`, `templates/sites/track.html`, `templates/sites/quote_done.html`, `templates/sites/_scripts.html`, `static/css/sites/common.css`.

- [x] آزمون قرمز: درخواست quote نامعتبر خطاهای قابل نمایش داشته باشد، POST معتبر PRG شود، refresh رکورد اضافه نسازد.
- [x] اعتبارسنجی فیلدهای سفارشی تعریف‌شده: شناسه امن فیلد، نوع پشتیبانی‌شده، required، طول و مجموعهٔ انتخابی؛ همان منبع قواعد برای HTML/سرور.
- [x] رفتار سازگار برای رشته‌های بدون `form_fields` و فرم‌های قدیمی.
- [x] آزمون قرمز: GET `/track/` با query code/mobile هیچ quote برنگرداند؛ POST خطا/موفقیت در URL مقدار نداشته باشد؛ موفقیت با تطبیق هر دو پارامتر.
- [x] فرم پیگیری POST و redirect به نتیجهٔ session کوتاه‌عمر؛ پاک‌سازی session پس از نمایش و عدم لو رفتن وجود کد معتبر در پیام.
- [x] پیام‌های فرم و خطا در صفحهٔ خانه و صفحهٔ رشته render شوند.

## مرحلهٔ 4 — چک‌لیست انتشار و ویرایش آسان

**فایل‌ها:** `apps/panel/views.py`, فرم/قالب panel site, helper تازه در `apps/sites/`.

- [x] آزمون: بدون رشته یا هیچ راه تماس انتشار رد شود؛ خطاهای متنی فارسی؛ دادهٔ کافی انتشار را فعال کند.
- [x] تابع خالص readiness بر اساس اطلاعات واقعی و پیام‌های قابل‌فهم، بدون بررسی سخت‌گیرانهٔ آمار اختیاری.
- [x] چک‌لیست و پیش‌نمایش/وضعیت انتشار در صفحهٔ تنظیم محتوا.
- [x] فرم محتوای رشته برای هر رشتهٔ منتخب قابل‌فهم و ذخیره‌پذیر باشد.

## مرحلهٔ 5 — حرفه‌ای‌سازی محتوای پنج قالب، اعتماد و موبایل

**فایل‌ها:** هر پنج `templates/sites/*/home.html`, baseها، `templates/sites/parts/*`, `static/css/sites/common.css`, پنج CSS قالب.

- [x] آزمون: همهٔ قالب‌ها خانه و لینک‌های رشته، tracking، تماس/ورود مشتری و راهنمای اقدام را دارند.
- [x] یک مسیر معنایی یکسان با ظاهر متناسب موجود: معرفی، خدمات، روند، اعتماد واقعی، FAQ، تماس و شعب.
- [x] ادعاهای مقایسهٔ آنی و خدمت غیرموجود حذف/تبدیل به عبارت «درخواست استعلام/کارشناس بررسی می‌کند».
- [x] اصلاح labels/help text برای مدارک و زمان پاسخ؛ بدون SLA ساختگی.
- [x] ناوبری موبایل لینک‌های مهم را پوشش دهد و نوار سریع track/quote/contact/portal را مطابق قابلیت موجود نمایش دهد.
- [x] focus، رنگ، touch target، reduced motion و breakpoint بررسی شوند.

## مرحلهٔ 6 — SEO، robots، sitemap و structured data

**فایل‌ها:** `apps/sites/views.py`, `templates/sites/_head.html`, صفحات جدید، `tests/test_agency_sites.py`.

- [x] آزمون: sitemap فقط صفحات خانه/رشتهٔ عمومی سایت منتشرشده، بدون track/account.
- [x] `/track/` و `/account/` دارای `noindex`; robots مسیرهای private را مسدود و sitemap درست را معرفی کند.
- [x] canonical با host/path معتبر برای هر صفحه؛ title/description از محتوا و طول منطقی.
- [x] `InsuranceAgency` دادهٔ ساختاریافته از فیلدهای موجود و escape ایمن ساخته شود.

## مرحلهٔ 7 — بازبینی و تأیید

- [x] pytest کامل + ruff + Django check + migration check + Docker build.
- [x] بررسی tenant isolation/RLS، URL privacy، XSS در custom code و محتوای JSON-LD.
- [x] مرور دستی HTML و CSS پنج قالب، viewportهای موبایل/دسکتاپ و flow استعلام/پیگیری.
- [x] بازبینی کد و رفع یافته‌های مهم.
- [x] شاخه آمادهٔ بازبینی/PR؛ ادغام یا انتشار production نیازمند درخواست جداگانه است.

## ثبت پیشرفت

| تاریخ | مرحله | نتیجه |
|---|---|---|
| ۲۰۲۶-۱۰-۱۹ | طراحی/برنامه | مبنای آخرین `main` با commit `e93b68e`؛ اجرای مشخصات شروع شد. |
| ۲۰۲۶-۱۰-۱۹ | پیاده‌سازی/تأیید | پنج قالب، صفحات رشته و راهنما، محتوای پنل، انتشار امن، فرم استعلام/پیگیری، SEO و responsive تکمیل شد. pytest کامل PostgreSQL، Ruff، Django/migration check، مرورگر دسکتاپ/موبایل و Docker build موفق؛ یافته‌های بازبینی و حالت پیگیری نامعتبر پس از نتیجهٔ قبلی نیز اصلاح شد. |
