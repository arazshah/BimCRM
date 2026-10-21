"""The public read-only demo office at demo.<platform>.

Anyone can open its website, its management panel (signed in as the demo owner, nothing is saved) and its customer
portal. The office is built on first use; afterwards every date in it is moved forward each day so renewals,
tasks and reports always look current.
"""

import random
from datetime import datetime, time, timedelta

from django.apps import apps
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

DEMO_SLUG = "demo"
DEMO_OWNER_MOBILE = "09000000000"
DEMO_CUSTOMER_MOBILE = "09121000001"
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
OFFICE_NAME = "دفتر بیمه آرمان، نمایندگی کد ۴۵۶۷"

CUSTOMERS = [
    ("مریم رضایی", "تهران"),
    ("حمید کاظمی", "کرج"),
    ("سارا محمدی", "تهران"),
    ("علی حسینی", "تهران"),
    ("نرگس احمدی", "کرج"),
    ("رضا موسوی", "تهران"),
    ("فاطمه کریمی", "تهران"),
    ("محمد جعفری", "کرج"),
    ("زهرا نوری", "تهران"),
    ("امیر صادقی", "تهران"),
    ("لیلا رحیمی", "کرج"),
    ("حسین قاسمی", "تهران"),
    ("شرکت پخش آرین", "تهران"),
    ("مهسا یوسفی", "تهران"),
    ("کامران شریفی", "کرج"),
    ("نسرین باقری", "تهران"),
    ("بهرام عباسی", "تهران"),
    ("پریسا اکبری", "کرج"),
    ("سعید طاهری", "تهران"),
    ("الهام فرهادی", "تهران"),
    ("داوود ملکی", "کرج"),
    ("رستوران برگ سبز", "تهران"),
    ("یاسمن حیدری", "تهران"),
    ("مجید رستمی", "کرج"),
]
CARS = ["پژو ۲۰۶", "پراید ۱۳۱", "دنا پلاس", "تارا", "سمند", "کوییک", "شاهین", "هایما S7", "پژو پارس"]
HOMES = ["آپارتمان ۸۵ متری، سعادت‌آباد", "آپارتمان ۱۲۰ متری، گوهردشت", "ویلای ۲۰۰ متری، مهرشهر", "واحد تجاری ۴۰ متری"]


def get_demo():
    from apps.core.models import Tenant

    return Tenant.objects.filter(demo_built_on__isnull=False).first()


def ensure_demo():
    """The demo office, built if missing and with its dates brought up to today."""
    tenant = get_demo()
    if tenant is None:
        tenant = _build()
    refresh(tenant)
    return tenant


def rebuild():
    """Deletes the demo office and builds it again from scratch."""
    from apps.claims.models import Claim
    from apps.core.tenancy import tenant_context
    from apps.crm.models import Policy
    from apps.finance.models import Installment, LedgerEntry

    tenant = get_demo()
    if tenant is not None:
        with transaction.atomic(), tenant_context(tenant):
            Claim.objects.all().delete()
            Installment.objects.all().delete()
            LedgerEntry.objects.all().delete()
            Policy.objects.all().delete()
            tenant.delete()
    return ensure_demo()


def refresh(tenant) -> int:
    """Moves every date in the demo forward to today. Returns the number of days shifted (0 when already current)."""
    from apps.core.models import Tenant
    from apps.core.tenancy import tenant_context

    today = timezone.localdate()
    built = tenant.demo_built_on
    if built is None or built >= today:
        return 0
    days = (today - built).days
    with transaction.atomic():
        # Only one request wins the shift, even if many arrive together on a new day.
        if not Tenant.objects.filter(pk=tenant.pk, demo_built_on=built).update(demo_built_on=today):
            return 0
        with tenant_context(tenant):
            _shift_dates(tenant, timedelta(days=days))
    tenant.demo_built_on = today
    return days


def _shift_dates(tenant, delta):
    from apps.claims.models import ClaimEvent
    from apps.core.models import TenantOwned

    for model in apps.get_models():
        if issubclass(model, TenantOwned):
            _shift_model(model, model.all_objects.filter(tenant=tenant), delta)
    _shift_model(ClaimEvent, ClaimEvent.objects.filter(claim__tenant=tenant), delta)
    from apps.billing.models import Subscription

    Subscription.objects.filter(tenant=tenant).update(current_period_end=timezone.now() + timedelta(days=3650))


def _shift_model(model, qs, delta):
    fields = [
        f.name
        for f in model._meta.concrete_fields
        if isinstance(f, (models.DateField, models.DateTimeField)) and not f.primary_key
    ]
    if fields:
        # update() skips auto_now fields, so created_at moves along with everything else.
        qs.update(**{name: F(name) + delta for name in fields})


def _aware(day, hour=10, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def _build():
    from apps.accounts.models import Membership, User
    from apps.billing.models import Package, Subscription
    from apps.billing.services import create_workspace
    from apps.core.models import Tenant
    from apps.core.tenancy import tenant_context

    owner, _ = User.objects.get_or_create(mobile=DEMO_OWNER_MOBILE, defaults={"full_name": "رضا آرمان"})
    slug = DEMO_SLUG if not Tenant.objects.filter(slug=DEMO_SLUG).exists() else "demo-office"
    plan = Package.plans().order_by("-monthly_price").first()
    with transaction.atomic():
        tenant = create_workspace(
            owner=owner, name=OFFICE_NAME, slug=slug, template="modern", period="yearly", package=plan
        )
        tenant.agency_code = "۴۵۶۷"
        tenant.phone = "021-88001234"
        tenant.address = "تهران، خیابان ولیعصر، بالاتر از پارک ساعی، پلاک ۱۲"
        tenant.demo_built_on = timezone.localdate()
        tenant.save()
        Subscription.objects.filter(tenant=tenant).update(
            status=Subscription.Status.ACTIVE, current_period_end=timezone.now() + timedelta(days=3650)
        )
        team = {
            "manager": ("نگار صادقی", "09000000001", Membership.Role.MANAGER),
            "staff": ("امید رستمی", "09000000002", Membership.Role.STAFF),
            "karaj": ("سمیرا نیک‌پور", "09000000003", Membership.Role.STAFF),
        }
        users = {"owner": owner}
        for key, (name, mobile, role) in team.items():
            user, _ = User.objects.get_or_create(mobile=mobile, defaults={"full_name": name})
            Membership.objects.get_or_create(user=user, tenant=tenant, defaults={"role": role})
            users[key] = user
        with tenant_context(tenant):
            _fill(tenant, users)
    return tenant


def _fill(tenant, users):  # noqa: C901 - one long, readable recipe
    from apps.accounts.models import Membership
    from apps.claims.models import Claim, ClaimEvent
    from apps.club.models import ClubSettings, PointEntry
    from apps.core.models import InsuranceCompany, LineOfBusiness
    from apps.crm.models import Branch, Customer, Policy, QuoteRequest
    from apps.finance.models import CommissionRule, Installment, LedgerEntry
    from apps.messaging.models import Campaign, MessageLog, ReminderSettings
    from apps.network.models import Marketer
    from apps.sites.models import FAQ, SiteSettings, Testimonial
    from apps.work.models import Activity, Notification, Task

    rnd = random.Random(4567)
    today = timezone.localdate()
    owner, manager, staff = users["owner"], users["manager"], users["staff"]
    lines = {line.slug: line for line in LineOfBusiness.objects.all()}
    any_line = next(iter(lines.values()))

    def line(slug):
        return lines.get(slug, any_line)

    companies = list(InsuranceCompany.objects.order_by("order")[:6])

    # Nothing in the demo may text a real number.
    ReminderSettings.objects.update_or_create(
        tenant=tenant,
        defaults={"renewals_enabled": False, "installments_enabled": False, "staff_digest_enabled": False},
    )
    club, _ = ClubSettings.objects.get_or_create(tenant=tenant)
    club.sms_on_reward = False
    club.save()

    site = SiteSettings.objects.get()
    site.hero_title = "بیمه آرمان؛ آسوده‌خاطر رانندگی کنید"
    site.hero_subtitle = "ثالث، بدنه، آتش‌سوزی، درمان و عمر؛ استعلام آنلاین و صدور در کمتر از یک روز کاری."
    site.about = (
        "از سال ۱۳۸۲ کنار خانواده‌ها و کسب‌وکارهای تهران و کرج هستیم. "
        "مشاوره رایگان، مقایسه چند شرکت و پیگیری خسارت تا روز پرداخت، کار هر روز ماست."
    )
    site.phone, site.whatsapp = "021-88001234", "09121234567"
    site.address = tenant.address
    site.working_hours = "شنبه تا چهارشنبه ۹ تا ۱۸، پنج‌شنبه ۹ تا ۱۳"
    site.years_active, site.customers_count = 21, 4800
    site.seo_description = "نمایندگی بیمه در تهران و کرج؛ استعلام آنلاین ثالث، بدنه، آتش‌سوزی و درمان."
    site.is_published = True
    site.save()
    site.lines.set(lines.values())
    site.companies.set(companies)
    for name, text in [
        ("مریم ر.", "ده روز مانده به تمدید ثالث پیامک دادند؛ دیگر نگران دیرکرد نیستم."),
        ("حمید ک.", "خسارت بدنه را از پنل مشتری اعلام کردم و مرحله‌به‌مرحله در جریان بودم."),
        ("شرکت پخش آرین", "بیمه درمان ۴۰ نفر از همکاران را سریع و بی‌دردسر انجام دادند."),
    ]:
        Testimonial.objects.create(name=name, text=text)
    for i, (q, a) in enumerate(
        [
            ("برای بیمه ثالث چه مدارکی لازم است؟", "کارت خودرو، بیمه‌نامه قبلی و کارت ملی مالک."),
            ("می‌توانم قسطی پرداخت کنم؟", "برای بدنه و آتش‌سوزی بله؛ با چک یا واریز ماهانه."),
            ("تخفیف عدم خسارت منتقل می‌شود؟", "بله؛ با بیمه‌نامه قبلی، تخفیف شما به بیمه جدید منتقل می‌شود."),
            ("خسارت را چطور اعلام کنم؟", "از «پنل مشتری» در همین سایت، یا با تماس با دفتر."),
        ]
    ):
        FAQ.objects.create(question=q, answer=a, order=i)

    hq = Branch.objects.create(name="دفتر مرکزی", city="تهران", address="خیابان ولیعصر، پلاک ۱۲", order=0)
    karaj = Branch.objects.create(name="شعبه کرج", city="کرج", address="عظیمیه، میدان مهران", order=1)
    Membership.objects.filter(tenant=tenant, user=users["karaj"]).update(branch=karaj)
    CommissionRule.objects.create(rate=8)
    lead = Marketer.objects.create(full_name="فرهاد سرگروه", mobile="09122000001", rate=2, override_rate=1)
    rep = Marketer.objects.create(full_name="نیلوفر بازاریاب", mobile="09122000002", parent=lead, rate=3)
    Marketer.objects.create(full_name="کیان فروش", mobile="09122000003", parent=lead, rate=3)

    customers = []
    for i, (name, city) in enumerate(CUSTOMERS):
        c = Customer.objects.create(
            full_name=name,
            mobile=f"0912100{i + 1:04d}",
            city=city,
            branch=karaj if city == "کرج" else hq,
            source=rnd.choice(["website", "walk_in", "phone", "referral"]),
            birth_date=today - timedelta(days=365 * rnd.randint(25, 60) + (5 if i == 3 else rnd.randint(30, 300))),
            marketer=rep if i % 4 == 1 else (lead if i % 7 == 2 else None),
        )
        customers.append(c)
    customers[5].referred_by = customers[0]
    customers[9].referred_by = customers[0]
    customers[14].referred_by = customers[1]
    for c in (customers[5], customers[9], customers[14]):
        c.save(update_fields=["referred_by"])

    # Renewals spread over the coming weeks, plus a year of sales for the reports.
    renew_in = [2, 4, 6, 9, 12, 15, 19, 24, 28, 35, 44, 58]
    policies = []
    n = 0

    def add_policy(customer, slug, end, premium, subject=""):
        nonlocal n
        n += 1
        p = Policy.objects.create(
            customer=customer,
            line=line(slug),
            company=companies[n % len(companies)],
            number=f"۱۴۰۴/{2300 + n}".translate(FA_DIGITS),
            start_date=end - timedelta(days=365),
            end_date=end,
            premium=premium * 10,
            subject=subject,
            created_by=rnd.choice([owner, manager, staff]),
            commission_received=premium * 80 // 100 if n % 3 else 0,
        )
        policies.append(p)
        return p

    for i, days in enumerate(renew_in):
        c = customers[i]
        slug = ["third-party", "car-body", "third-party", "home-fire", "third-party", "health"][i % 6]
        subject = (
            rnd.choice(CARS) if "third" in slug or "car" in slug else (rnd.choice(HOMES) if "home" in slug else "")
        )
        add_policy(c, slug, today + timedelta(days=days), rnd.randint(4, 16) * 1_000_000, subject)
    for i in range(26):
        c = customers[(i * 5 + 3) % len(customers)]
        slug = rnd.choice(["third-party", "third-party", "car-body", "home-fire", "health", "life", "travel"])
        end = today + timedelta(days=60 + i * 11)
        premium = {"health": 28, "life": 36, "car-body": 18}.get(slug, 6) * 1_000_000 + rnd.randint(0, 9) * 250_000
        subject = rnd.choice(CARS) if slug in ("third-party", "car-body") else ""
        add_policy(c, slug, end, premium, subject)
    # Recent renewals (this month's production and the renewal rate) and a few that were lost.
    for k in range(9):
        c = customers[(k * 3 + 13) % len(customers)]
        slug = ["third-party", "car-body", "home-fire"][k % 3]
        subject = rnd.choice(CARS) if slug != "home-fire" else rnd.choice(HOMES)
        premium = rnd.randint(5, 14) * 1_000_000
        old = add_policy(c, slug, today - timedelta(days=2 + k * 6), premium, subject)
        if k < 7:
            new = add_policy(c, slug, old.end_date + timedelta(days=365), premium * 115 // 100, subject)
            new.renewed_from = old
            new.save(update_fields=["renewed_from"])
    group = add_policy(customers[12], "health", today + timedelta(days=210), 96_000_000, "درمان تکمیلی ۴۰ نفر کارکنان")
    # Created dates follow the start dates, so «production this month» looks real.
    for p in policies:
        Policy.objects.filter(pk=p.pk).update(created_at=_aware(p.start_date, 11))

    statuses = ["new", "new", "contacted", "contacted", "waiting_docs", "issued", "issued", "lost"]
    leads = [
        ("کاوه نیک‌نام", "third-party", {"نوع و مدل خودرو": "کوییک", "سال ساخت": "۱۴۰۰"}),
        ("لیلا صادقی", "home-fire", {"متراژ": "۹۰", "شهر": "تهران"}),
        ("بابک امینی", "car-body", {"نوع و مدل خودرو": "تارا", "ارزش تقریبی خودرو (تومان)": "۱٬۲۰۰٬۰۰۰٬۰۰۰"}),
        ("شیما کرمی", "travel", {"کشور مقصد": "ترکیه", "مدت سفر (روز)": "۷"}),
        ("آرش مرادی", "health", {"تعداد افراد": "۴"}),
        ("رویا شفیعی", "third-party", {"نوع و مدل خودرو": "پژو ۲۰۷"}),
        ("مهدی کیانی", "life", {"سن بیمه‌شده": "۳۵"}),
        ("نازنین فراهانی", "car-body", {"نوع و مدل خودرو": "سمند"}),
    ]
    for i, (name, slug, details) in enumerate(leads):
        q = QuoteRequest.objects.create(
            line=line(slug),
            full_name=name,
            mobile=f"0935200{i:04d}",
            details=details,
            status=statuses[i],
            assigned_to=[None, staff, manager, staff, owner, staff, manager, None][i],
            branch=karaj if i in (2, 5) else hq,
            referrer=customers[0] if i == 6 else None,
            staff_note="قیمت سه شرکت فرستاده شد." if statuses[i] in ("contacted", "waiting_docs") else "",
        )
        created = timezone.now() - timedelta(hours=[3, 20, 30, 50, 72, 120, 200, 260][i])
        first = created + timedelta(minutes=25) if statuses[i] != "new" else None
        QuoteRequest.objects.filter(pk=q.pk).update(created_at=created, first_contact_at=first)

    tasks = [
        ("تماس برای تمدید ثالث", "renewal", 0, owner, 3, customers[0], time(10, 0)),
        ("پیگیری مدارک بدنه تارا", "docs", 0, staff, 2, customers[1], time(12, 30)),
        ("وصول قسط دوم آتش‌سوزی", "payment", -1, manager, 3, customers[3], None),
        ("جلسه با مدیر شرکت پخش آرین؛ تمدید درمان گروهی", "meeting", 1, owner, 4, customers[12], time(11, 0)),
        ("ارسال قیمت بدنه برای کاوه نیک‌نام", "call", 1, staff, 2, None, None),
        ("تبریک تولد و پیشنهاد بیمه عمر", "call", 3, manager, 1, customers[3], None),
        ("بازدید ملک برای آتش‌سوزی", "other", 5, staff, 2, customers[6], time(16, 0)),
    ]
    for title, kind, due, who, prio, cust, at in tasks:
        Task.objects.create(
            title=title,
            kind=kind,
            due_date=today + timedelta(days=due),
            due_time=at,
            assigned_to=who,
            priority=prio,
            customer=cust,
            created_by=owner,
        )
    Task.objects.create(
        title="ثبت بیمه‌نامه‌های هفته در پنل",
        kind="other",
        due_date=today - timedelta(days=2),
        assigned_to=staff,
        done_at=timezone.now() - timedelta(days=2),
        done_by=staff,
        created_by=owner,
    )

    notes = [
        ("call", "تماس گرفتم؛ تمدید را هفته بعد انجام می‌دهد. قیمت دو شرکت را خواست."),
        ("whatsapp", "عکس کارت ماشین و بیمه‌نامه قبلی را در واتس‌اپ فرستاد."),
        ("visit", "حضوری آمد؛ آتش‌سوزی منزل را هم خواست."),
        ("sms", "پیامک یادآور تمدید ارسال شد."),
        ("note", "مشتری خوش‌حساب؛ ترجیح می‌دهد صبح‌ها تماس بگیریم."),
    ]
    for i, c in enumerate(customers[:14]):
        for k in range(1 + i % 3):
            kind, body = notes[(i + k) % len(notes)]
            Activity.objects.create(
                customer=c,
                kind=kind,
                body=body,
                created_by=rnd.choice([owner, manager, staff]),
                created_at=timezone.now() - timedelta(days=k * 6 + i % 4, hours=i),
            )

    first = policies[3]
    for k in range(4):
        due = today + timedelta(days=30 * k - 40)
        paid = due < today
        Installment.objects.create(
            policy=first,
            due_date=due,
            amount=25_000_000,
            method="cheque",
            cheque_number=f"77310{k}",
            cheque_bank="ملت",
            status="paid" if paid else "pending",
            paid_at=due if paid else None,
        )
    Installment.objects.create(
        policy=policies[1],
        due_date=today - timedelta(days=6),
        amount=40_000_000,
        method="cheque",
        cheque_number="551208",
        cheque_bank="صادرات",
        status="bounced",
        note="برگشت خورد؛ تماس گرفته شد",
    )
    Installment.objects.create(policy=group, due_date=today + timedelta(days=3), amount=240_000_000, method="transfer")
    for m in range(6):
        day = today - timedelta(days=30 * m + 3)
        LedgerEntry.objects.create(
            date=day,
            kind="income",
            category="commission",
            amount=rnd.randint(28, 46) * 10_000_000,
            description="کارمزد ماهانه شرکت‌ها",
        )
        LedgerEntry.objects.create(
            date=day, kind="expense", category="rent", amount=180_000_000, description="اجاره دفتر"
        )
        LedgerEntry.objects.create(
            date=day, kind="expense", category="salary", amount=320_000_000, description="حقوق همکاران"
        )
        LedgerEntry.objects.create(
            date=day + timedelta(days=1),
            kind="expense",
            category="ads",
            amount=rnd.randint(2, 5) * 10_000_000,
            description="تبلیغات اینستاگرام",
        )

    claim_rows = [
        (policies[1], "تصادف از عقب در بزرگراه همت؛ کروکی کشیده شده.", 180_000_000, 0, ["reported", "docs_needed"]),
        (
            policies[3],
            "نشت آب از لوله آشپزخانه و خرابی کابینت.",
            420_000_000,
            0,
            ["reported", "submitted", "inspection"],
        ),
        (policies[2], "شکستگی چراغ و سپر جلو.", 95_000_000, 90_000_000, ["reported", "submitted", "approved", "paid"]),
    ]
    notes_for = {
        "reported": "اعلام از پنل مشتری",
        "docs_needed": "لطفاً عکس کارت ماشین و کروکی را بفرستید",
        "submitted": "پرونده به شرکت بیمه ارسال شد",
        "inspection": "کارشناس فردا ساعت ۱۰ بازدید می‌کند",
        "approved": "خسارت تأیید شد",
        "paid": "مبلغ به حساب شما واریز شد",
    }
    for i, (policy, desc, asked, paid, steps) in enumerate(claim_rows):
        claim = Claim.objects.create(
            policy=policy,
            incident_date=today - timedelta(days=4 + i * 9),
            description=desc,
            amount_claimed=asked,
            amount_paid=paid,
            reported_by_customer=i != 1,
            status=steps[-1],
            assigned_to=staff,
        )
        for k, st in enumerate(steps):
            ClaimEvent.objects.create(
                claim=claim,
                status=st,
                note=notes_for[st],
                created_at=timezone.now() - timedelta(days=(len(steps) - k) * 2 + i),
            )

    Campaign.objects.create(
        title="تخفیف بیمه بدنه ویژه پاییز",
        text="{name} عزیز، تا پایان ماه بیمه بدنه با ۱۵٪ تخفیف ویژه مشتریان دفتر آرمان.",
        line=line("third-party"),
        status="done",
        recipients=420,
        sent=416,
        failed=4,
    )
    Campaign.objects.create(
        title="تبریک تولد",
        text="{name} عزیز، تولدتان مبارک! هدیه شما: ۱۰٪ تخفیف بیمه عمر.",
        status="draft",
    )
    for c in customers[:8]:
        MessageLog.objects.create(
            kind="renewal",
            key=f"demo:{c.pk}",
            mobile=c.mobile,
            text=f"{c.full_name} عزیز، بیمه‌نامه شما رو به پایان است. برای تمدید با دفتر آرمان تماس بگیرید.",
        )
    PointEntry.objects.create(customer=customers[0], points=100, reason="referral", note="معرفی سعید طاهری")
    PointEntry.objects.create(customer=customers[0], points=-150, reason="redeem", note="تخفیف تمدید ثالث")
    for c in customers[:3]:
        from apps.club.services import recalc

        recalc(c)

    for text, url in [
        ("درخواست استعلام جدید: کاوه نیک‌نام، شخص ثالث", "/panel/quotes/"),
        ("مریم رضایی خسارت جدید اعلام کرد", "/panel/claims/"),
        ("چک ۵۵۱۲۰۸ برگشت خورد", "/panel/finance/installments/"),
    ]:
        Notification.objects.create(user=owner, text=text, url=url)
