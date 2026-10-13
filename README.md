# CRM بیمه

پلتفرم SaaS برای دفاتر نمایندگی بیمه: هر نماینده با موبایل ثبت‌نام می‌کند، قالب، فضا و افزونه انتخاب می‌کند و یک محیط اختصاصی (پنل مدیریت + سایت) روی `slug.bimcrm.ir` می‌گیرد؛ بعداً دامنه خودش را با NS وصل می‌کند.

## ساختار

| مسیر | کار |
| --- | --- |
| `apps/core` | مستأجرها (Tenant)، دامنه‌ها، مسیریابی بر اساس Host، بررسی NS، رشته‌ها و شرکت‌های بیمه |
| `apps/accounts` | کاربر با موبایل، کد یک‌بارمصرف، پیامک پلتفرم (sms.ir) |
| `apps/billing` | پکیج پایه، پله‌های فضا، افزونه‌ها، اشتراک، فاکتور، زرین‌پال |
| `apps/main` | سایت bimcrm.ir: معرفی، ورود، جادوگر ساخت محیط، پرداخت |
| `apps/panel` | پنل نماینده: داشبورد، مشتریان، بیمه‌نامه‌ها، درخواست‌ها، سایت، دامنه، اتصالات، همکاران، اشتراک، پشتیبانی |
| `apps/sites` | سایت عمومی نماینده با ۵ قالب، استعلام، پیگیری، پنل مشتری |
| `apps/crm` | مشتری، بیمه‌نامه، درخواست استعلام |
| `apps/integrations` | سرویس‌های خود نماینده (درگاه، پیامک، اینماد، کد دلخواه) با رمزنگاری |
| `apps/tickets` | تیکت پشتیبانی بین نماینده و سوپرادمین |
| `apps/messaging` | یادآور تمدید، قسط و تولد با پنل پیامک خود نماینده (هر روز ساعت ۱۰)، کمپین پیامکی |
| `apps/finance` | افزونه مالی: اقساط و چک، نرخ و دریافت کارمزد، دفتر درآمد و هزینه |
| `apps/claims` | افزونه خسارت: پرونده، روند وضعیت، مدارک؛ اعلام خسارت از پنل مشتری |
| `apps/network` | افزونه بازاریابان: لینک معرف، کمیسیون دو سطحی، تسویه |

| Host | چه چیزی |
| --- | --- |
| `bimcrm.ir` | سایت معرفی، ثبت‌نام و ورود |
| `admin.bimcrm.ir` | پنل سوپرادمین (Django admin) |
| `<slug>.bimcrm.ir` | سایت نماینده؛ پنل در `/panel/` |
| دامنه فعال نماینده | سایت نماینده |

## اجرای محلی

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DEBUG=True
python manage.py migrate
python manage.py seed_demo          # محیط نمونه demo-alborz با همه افزونه‌ها، موبایل 09120000000
python manage.py createsuperuser    # برای admin
python manage.py runserver
```

مرورگر `*.localhost` را خودش به 127.0.0.1 می‌برد:

- http://bimcrm.localhost:8000 — سایت اصلی (کد ورود در خروجی سرور چاپ می‌شود، چون `SMS_BACKEND=console`)
- http://demo-alborz.bimcrm.localhost:8000/panel/ — پنل نمونه
- http://admin.bimcrm.localhost:8000 — سوپرادمین

## تست

```bash
pytest
ruff check . && ruff format --check .
```

## استقرار

[DEPLOY.md](DEPLOY.md)
