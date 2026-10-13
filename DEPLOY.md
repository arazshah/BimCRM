# راه‌اندازی CRM بیمه روی Coolify

این راهنما برای سرور خودت با Coolify و build pack «Docker Compose» است.

## ۱. مسیر استقرار

```
Pull Request → CI (lint + تست روی PostgreSQL + ساخت ایمیج) → merge به main
            → CI دوباره روی main → اگر سبز بود → وب‌هوک Coolify → دیپلوی
```

برای اینکه فقط کد تست‌شده دیپلوی شود:

1. در Coolify، در تنظیمات همین ریسورس، **Auto Deploy را خاموش کن** تا با هر push مستقیم دیپلوی نشود.
2. در Coolify از بخش Webhooks ریسورس، آدرس **Deploy Webhook** را کپی کن.
3. در Coolify از Keys & Tokens یک **API Token** با دسترسی deploy بساز.
4. در GitHub ریپو → Settings → Secrets and variables → Actions دو secret بساز:
   - `COOLIFY_WEBHOOK` = آدرس Deploy Webhook
   - `COOLIFY_TOKEN` = همان API Token
5. در GitHub → Settings → Branches برای `main` قانون بگذار: «Require status checks to pass» با چک‌های `test` و `docker`.

تا وقتی `COOLIFY_WEBHOOK` تنظیم نشده، مرحله deploy در CI بی‌صدا رد می‌شود.

## ۲. ساخت ریسورس در Coolify

- Source: ریپوی `arazshah/BimCRM`، شاخه `main`
- Build Pack: **Docker Compose**، فایل `docker-compose.yml`
- دامنه‌های سرویس `web` (پورت 8000):
  - `https://bimcrm.ir`
  - `https://admin.bimcrm.ir`
  - زیردامنه‌های نماینده‌ها: بخش ۴ را ببین.

### متغیرهای محیطی (Environment Variables)

| متغیر | توضیح |
| --- | --- |
| `SECRET_KEY` | یک رشته تصادفی بلند. ساخت: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `FIELD_ENCRYPTION_KEY` | کلید رمزنگاری اطلاعات اتصالات نماینده‌ها. ساخت: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` — **هرگز عوضش نکن و جایی امن نگهش دار**؛ عوض شدنش یعنی کلیدهای درگاه و پیامک همه نماینده‌ها غیرقابل‌خواندن می‌شود. |
| `POSTGRES_PASSWORD` | رمز مالک پایگاه داده (فقط برای migrate) |
| `APP_DB_PASSWORD` | رمز نقش محدود `bimcrm_app` که برنامه با آن وصل می‌شود؛ یک رمز جدا و بلند |
| `SUPERADMIN_MOBILE` | موبایل خودت. در اولین دیپلوی ساخته می‌شود و رمز یک‌بارمصرفش در لاگ سرویس `web` چاپ می‌شود. |
| `SMSIR_*`، `ZARINPAL_*`، `SMS_BACKEND` | **اختیاری.** مقدار پیش‌فرض پیامک و زرین‌پال؛ بهتر است همه را از پنل سوپرادمین (تنظیمات پلتفرم) وارد کنی. هر چه آنجا پر باشد، بر این‌ها غلبه می‌کند. قالب کد تأیید sms.ir باید پارامتری به نام `CODE` داشته باشد. |
| `SUPERADMIN_PASSWORD` | اختیاری. رمز اولیه سوپرادمین تا اولین ورود؛ خالی = رمز تصادفی در لاگ `web`. |

بقیه متغیرها مقدار پیش‌فرض درست دارند (`docker-compose.yml`).

## ۳. ایمیج‌ها روی سرور ایران

Docker Hub درخواست‌های IP ایران را رد می‌کند، پس `python:3.13-slim`، `postgres:16-alpine` و `redis:7-alpine` ممکن است دانلود نشوند. یک mirror داخلی در `/etc/docker/daemon.json` سرور بگذار:

```json
{ "registry-mirrors": ["https://docker.arvancloud.ir"] }
```

و `systemctl restart docker`. اگر PyPI هم کند یا بسته بود، در Coolify آرگومان build `PIP_INDEX_URL` را روی یک mirror PyPI بگذار.

## ۴. زیردامنه‌ها، دامنه نماینده‌ها و SSL

این بخش در PR بعدی کامل می‌شود و فعلاً این وضعیت را دارد:

- **کد آماده است:** مسیریابی بر اساس دامنه، بررسی NS، و آدرس `/internal/tls-ask?domain=...` که فقط برای دامنه‌های مجاز (bimcrm.ir، زیردامنه نماینده‌های موجود، دامنه‌های فعال) جواب ۲۰۰ می‌دهد.
- **مانده:** 
  1. **PowerDNS** روی سرور (پورت ۵۳) تا وقتی نماینده NS را روی `ns1/ns2.bimcrm.ir` گذاشت، دامنه‌اش به سرور ما اشاره کند. پنل به‌محض فعال شدن دامنه از طریق API، zone را می‌سازد.
  2. **پراکسی با SSL درخواستی:** Traefik پیش‌فرض Coolify برای دامنه‌های ناشناخته گواهی نمی‌گیرد. دو راه: تغییر پراکسی Coolify به Caddy با `on_demand_tls` که از `/internal/tls-ask` اجازه می‌گیرد، یا یک Caddy جدا جلوی سرویس. این را با هم روی سرورت تنظیم می‌کنیم.
  3. **گواهی wildcard** برای `*.bimcrm.ir` با چالش DNS روی همان PowerDNS.
- **رکورد glue:** در پنل ایرنیک برای `bimcrm.ir`، نام‌سرورهای `ns1.bimcrm.ir` و `ns2.bimcrm.ir` را همراه IP سرور تعریف کن.

تا آن موقع می‌توانی `bimcrm.ir` و `admin.bimcrm.ir` را در Coolify بگذاری و چند زیردامنه آزمایشی را دستی اضافه کنی.

## ۵. بعد از اولین دیپلوی

1. لاگ `web` را باز کن و رمز یک‌بارمصرف سوپرادمین را بردار.
2. وارد `https://admin.bimcrm.ir` شو و رمز را عوض کن.
3. در «تنظیمات پلتفرم» کلید و قالب sms.ir و مرچنت زرین‌پال را وارد کن (روش ارسال را «ارسال واقعی با sms.ir» و حالت زرین‌پال را «واقعی» بگذار). سپس «پکیج‌های پایه»، «پله‌های فضا» و «افزونه‌ها» قیمت‌های واقعی را بگذار (مقادیر فعلی نمونه‌اند).
4. در «زیردامنه‌های رزرو» هر نامی که نباید ثبت شود اضافه کن.
5. از `https://bimcrm.ir` با یک موبایل دیگر ثبت‌نام آزمایشی کن.

## ۶. جداسازی داده دفاتر در پایگاه داده

جدا از فیلتر برنامه، PostgreSQL با Row-Level Security نمی‌گذارد هیچ درخواستی ردیف دفتر دیگری را ببیند یا تغییر دهد. این لایه فقط وقتی کار می‌کند که برنامه با نقش غیرسوپریوزر وصل شود؛ برای همین:

- migrate با مالک (`MIGRATE_DATABASE_URL`) اجرا می‌شود؛
- `ensure_app_role` نقش `bimcrm_app` را می‌سازد (بدون SUPERUSER و BYPASSRLS) و دسترسی خواندن/نوشتن می‌دهد؛
- web، worker و beat با `bimcrm_app` وصل می‌شوند.

اگر به هر دلیل برنامه با نقش سوپریوزر وصل شود، `check --deploy` در لاگ هشدار `bimcrm.W001` می‌دهد.

## ۷. پشتیبان‌گیری

حجم‌های `pgdata` و `media` را در Coolify (بخش Backups) روزانه به مقصدی بیرون از همین سرور بفرست.
