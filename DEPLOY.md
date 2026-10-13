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

## ۴. زیردامنه‌ها و گواهی wildcard (بدون Cloudflare)

هدف: برای `*.bimcrm.ir` یک گواهی که خودکار تمدید شود. NS اصلی دامنه در پارس‌پک می‌ماند؛ فقط نام `_acme-challenge` را به PowerDNS خودمان می‌دهیم و Traefik تأیید DNS-01 را از همان‌جا می‌گیرد. رکورد glue در ایرنیک لازم نیست.

**گام ۱ — رکوردهای پارس‌پک** (`SERVER_IP` = IP عمومی سرور)

| نام | نوع | مقدار |
|---|---|---|
| `ns1` | A | `SERVER_IP` |
| `*` | A | `SERVER_IP` |
| `_acme-challenge` | NS | `ns1.bimcrm.ir.` |

**گام ۲ — فایروال:** پورت ۵۳ هم TCP و هم UDP را (در پنل سرویس‌دهنده‌ی سرور و `ufw`) باز کن.

**گام ۳ — نصب PowerDNS در Coolify**
1. Project → New Resource → **Docker Compose Empty**.
2. محتوای فایل `deploy/powerdns/docker-compose.yml` همین ریپو را بچسبان.
3. در Environment Variables: `PUBLIC_IP` (IP عمومی سرور) و `PDNS_API_KEY` (یک رشته‌ی تصادفی بلند؛ همان را در گام ۴ هم می‌گذاری).
4. Deploy. سرویس `pdns-init` بعد از ساختن zone با موفقیت تمام می‌شود و خارج شدنش طبیعی است (لاگش باید `HTTP 201` یا `HTTP 409` نشان دهد).
5. تست از بیرون سرور: `nslookup -type=SOA _acme-challenge.bimcrm.ir 8.8.8.8` باید به `ns1.bimcrm.ir` برسد.

**گام ۴ — پیکربندی Traefik در Coolify** (Servers → سرور → Proxy → Configuration). در همان فایل yaml چهار چیز اضافه کن:

۱) زیر `command:` سه خط، کنار بقیه‌ی `--certificatesresolvers...`:

```yaml
      - '--certificatesresolvers.letsencrypt-dns.acme.email=YOUR_EMAIL'
      - '--certificatesresolvers.letsencrypt-dns.acme.storage=/traefik/acme-dns.json'
      - '--certificatesresolvers.letsencrypt-dns.acme.dnschallenge.provider=pdns'
```

۲) زیر `environment:` سرویس traefik:

```yaml
      - PDNS_API_URL=http://bimcrm-pdns:8081
      - PDNS_API_KEY=همان_مقدار_گام_۳
      - PDNS_PROPAGATION_TIMEOUT=300
```

۳) Save و **Restart Proxy**. (شبکه‌ی `coolify` از قبل برای Traefik هست و PowerDNS به آن وصل شده.)

۴) این ریپو را دیپلوی کن (labels مسیر wildcard روی سرویس `web` در `docker-compose.yml` هست).

**گام ۵ — تست:** چند دقیقه صبر کن و `https://test123.bimcrm.ir` را باز کن. اگر خطا دارد: Proxy → Logs را ببین (`acme`, `pdns`). زیاد Restart نکن؛ Let's Encrypt بعد از چند شکست پشت‌سرهم موقتاً جلوی تلاش را می‌گیرد.

### مانده
- **دامنه‌ی `.ir` خود نماینده‌ها:** گواهی wildcard شامل آن‌ها نیست؛ برای آن‌ها پراکسی با on-demand TLS (Caddy) و `/internal/tls-ask` لازم است (مرحله‌ی بعد).
- **ساخت خودکار zone دامنه‌ی نماینده** از طریق API پاورDNS هنوز در برنامه پیاده نشده است.

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
