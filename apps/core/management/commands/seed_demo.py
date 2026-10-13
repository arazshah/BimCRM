"""Sample workspace for local development: python manage.py seed_demo

Creates the owner 09120000000 and the workspace demo-alborz with customers, policies and quote requests.
Never run this on production.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.models import Addon, StorageTier, SubscriptionItem
from apps.billing.services import create_workspace
from apps.claims.models import Claim, ClaimEvent
from apps.core.models import InsuranceCompany, LineOfBusiness, Tenant
from apps.core.tenancy import tenant_context
from apps.crm.models import Customer, Policy, QuoteRequest
from apps.finance.models import CommissionRule, Installment, LedgerEntry
from apps.network.models import Marketer
from apps.sites.models import FAQ, SiteSettings, Testimonial

PEOPLE = [
    ("مریم رضایی", "09121000001", "تهران"),
    ("حمید کاظمی", "09121000002", "کرج"),
    ("سارا محمدی", "09121000003", "تهران"),
    ("علی حسینی", "09121000004", "قزوین"),
    ("نرگس احمدی", "09121000005", "تهران"),
    ("رضا موسوی", "09121000006", "کرج"),
]


class Command(BaseCommand):
    help = "Create a demo workspace with sample data (development only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG=True.")
        owner, _ = User.objects.get_or_create(mobile="09120000000", defaults={"full_name": "مدیر نمونه"})
        tenant = Tenant.objects.filter(slug="demo-alborz").first()
        if tenant is None:
            tenant = create_workspace(
                owner=owner,
                name="نمایندگی بیمه البرز کد ۱۲۳۴",
                slug="demo-alborz",
                template="etemad",
                storage_tier=StorageTier.objects.order_by("order").first(),
                addons={},
                period="monthly",
            )
        today = timezone.localdate()
        lines = list(LineOfBusiness.objects.all())
        companies = list(InsuranceCompany.objects.all()[:5])
        with tenant_context(tenant):
            site = SiteSettings.objects.get()
            site.hero_subtitle = "ثالث، بدنه، آتش‌سوزی و عمر؛ استعلام آنلاین و صدور در کمتر از یک روز کاری."
            site.about = "از سال ۱۳۸۲ در خدمت خانواده‌ها و کسب‌وکارهای شهر هستیم."
            site.phone = "021-88001234"
            site.address = "تهران، خیابان ولیعصر، پلاک ۱۲"
            site.working_hours = "شنبه تا پنج‌شنبه ۹ تا ۱۸"
            site.years_active = 21
            site.customers_count = 4800
            site.is_published = True
            site.save()
            site.lines.set(lines)
            site.companies.set(companies)
            Testimonial.objects.get_or_create(name="مریم ر.", defaults={"text": "تمدید ثالث را پیامک یادآوری کردند."})
            FAQ.objects.get_or_create(
                question="برای ثالث چه مدارکی لازم است؟", defaults={"answer": "کارت خودرو و بیمه‌نامه قبلی."}
            )
            for i, (name, mobile, city) in enumerate(PEOPLE):
                c, _ = Customer.objects.get_or_create(mobile=mobile, defaults={"full_name": name, "city": city})
                end = today + timedelta(days=[3, 9, 17, 26, 60, 140][i])
                Policy.objects.get_or_create(
                    customer=c,
                    number=f"1403/{1000 + i}",
                    defaults={
                        "line": lines[i % len(lines)],
                        "company": companies[i % len(companies)],
                        "start_date": end - timedelta(days=365),
                        "end_date": end,
                        "premium": 3_500_000 + i * 900_000,
                        "subject": ["پژو ۲۰۶", "پراید ۱۳۱", "آپارتمان ۸۵ متری", "", "دنا پلاس", ""][i],
                    },
                )
            if not QuoteRequest.objects.exists():
                QuoteRequest.objects.create(
                    line=lines[0], full_name="کاوه نیک‌نام", mobile="09121000099", details={"نوع و مدل خودرو": "کوییک"}
                )
                QuoteRequest.objects.create(line=lines[2], full_name="لیلا صادقی", mobile="09121000098")
            self._addons(tenant, today)
        self.stdout.write(self.style.SUCCESS(f"Demo ready: {tenant.panel_url()} (login with 09120000000)"))

    def _addons(self, tenant, today):
        """Every add-on switched on, with a little data in each."""
        for addon in Addon.objects.filter(
            code__in=["finance", "claims", "marketers", "sms_campaigns", "advanced_reports"]
        ):
            SubscriptionItem.objects.get_or_create(subscription=tenant.subscription, addon=addon)
        if Marketer.objects.exists():
            return
        CommissionRule.objects.create(rate=8)
        lead = Marketer.objects.create(full_name="فرهاد سرگروه", mobile="09122000001", rate=2, override_rate=1)
        rep = Marketer.objects.create(full_name="نیلوفر بازاریاب", mobile="09122000002", parent=lead, rate=3)
        policies = list(Policy.objects.select_related("customer").order_by("pk"))
        for i, p in enumerate(policies):
            p.start_date = today - timedelta(days=20 * i)
            p.marketer = rep if i % 2 else lead
            p.commission_rate = 8
            p.save()
        first = policies[0]
        for n in range(3):
            Installment.objects.create(
                policy=first,
                due_date=today + timedelta(days=30 * n - 5),
                amount=1_500_000,
                method="cheque",
                cheque_number=f"7731{n}",
                cheque_bank="ملت",
            )
        LedgerEntry.objects.create(
            kind="income", category="commission", amount=320_000, policy=first, description="کارمزد ثالث"
        )
        LedgerEntry.objects.create(kind="expense", category="rent", amount=1_800_000, description="اجاره مهر")
        claim = Claim.objects.create(
            policy=policies[1],
            incident_date=today - timedelta(days=4),
            description="تصادف از عقب در بزرگراه همت؛ کروکی کشیده شده.",
            amount_claimed=18_000_000,
            reported_by_customer=True,
        )
        ClaimEvent.objects.create(claim=claim, status="reported", note="اعلام از پنل مشتری")
        claim.status = "docs_needed"
        claim.save()
        ClaimEvent.objects.create(claim=claim, status="docs_needed", note="عکس کارت ماشین و کروکی را بفرستید")
