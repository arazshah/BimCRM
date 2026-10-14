"""Customer segments, cross-selling and the customer club."""

from django import forms
from django.contrib import messages
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.club.models import TIER_LABELS, ClubSettings, PointEntry
from apps.club.services import award, recalc, referral_code_for
from apps.crm.models import Customer
from apps.crm.segments import BY_CODE, SEGMENTS, customers_in
from apps.work.models import Task

from .access import panel_view, scoped
from .forms import JalaliDateInput
from .forms_work import UserChoice, member_users


class SegmentTasksForm(forms.Form):
    title = forms.CharField(label="عنوان کار", max_length=120)
    due_date = forms.DateField(label="موعد", widget=JalaliDateInput())
    assigned_to = UserChoice(queryset=None, required=False, label="مسئول", empty_label="هر کدام از همکاران")

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = member_users(tenant)


@panel_view(perm="segments")
def segments(request):
    base = scoped(request, Customer.objects.all())
    groups = {}
    for s in SEGMENTS:
        groups.setdefault(s.group, []).append({"seg": s, "count": customers_in(s.code, base).count()})
    return render(
        request,
        "panel/segments.html",
        {
            "groups": list(groups.items()),
            "task_form": SegmentTasksForm(tenant=request.tenant, initial={"due_date": timezone.localdate()}),
        },
    )


@panel_view(perm="segments")
@require_POST
def segment_tasks(request, code):
    seg = BY_CODE.get(code)
    if seg is None:
        return redirect("panel:segments")
    form = SegmentTasksForm(request.POST, tenant=request.tenant)
    if not form.is_valid():
        messages.error(request, "عنوان و موعد را درست وارد کنید.")
        return redirect("panel:segments")
    d = form.cleaned_data
    created = 0
    for c in customers_in(code, scoped(request, Customer.objects.all()))[:500]:
        key = f"seg:{code}:{c.pk}:{d['due_date']:%Y%m%d}"
        if Task.objects.filter(auto_key=key).exists():
            continue
        Task.objects.create(
            title=f"{d['title']} — {c.full_name}",
            customer=c,
            due_date=d["due_date"],
            assigned_to=d["assigned_to"],
            auto_key=key,
            created_by=request.user,
        )
        created += 1
    if created and d["assigned_to"] and d["assigned_to"] != request.user:
        from apps.work.services import notify

        notify(
            request.tenant,
            [d["assigned_to"]],
            f"{created} کار «{d['title']}» به شما سپرده شد",
            reverse("panel:tasks") + "?f=all",
        )
    messages.success(request, f"{created} کار برای بخش «{seg.title}» ساخته شد.")
    return redirect(reverse("panel:tasks") + "?f=all")


class ClubSettingsForm(forms.ModelForm):
    class Meta:
        model = ClubSettings
        fields = [
            "enabled",
            "points_per_million",
            "renewal_bonus",
            "installment_bonus",
            "referral_bonus",
            "silver_at",
            "gold_at",
            "perks",
            "sms_on_reward",
        ]
        widgets = {"perks": forms.Textarea(attrs={"rows": 2})}


@panel_view(perm="segments")
def club(request):
    obj = ClubSettings.for_tenant(request.tenant)
    form = ClubSettingsForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        for c in Customer.objects.filter(points_lifetime__gt=0):
            recalc(c, form.instance)
        messages.success(request, "تنظیمات باشگاه ذخیره شد.")
        return redirect("panel:club")
    customers = scoped(request, Customer.objects.all())
    tiers = {row["tier"]: row["n"] for row in customers.values("tier").annotate(n=Count("id"))}
    month_start = timezone.localdate().replace(day=1)
    return render(
        request,
        "panel/club.html",
        {
            "form": form,
            "tiers": [(k, TIER_LABELS[k], tiers.get(k, 0)) for k in ("gold", "silver", "bronze")],
            "issued": PointEntry.objects.filter(points__gt=0).aggregate(s=Sum("points"))["s"] or 0,
            "redeemed": -(PointEntry.objects.filter(points__lt=0).aggregate(s=Sum("points"))["s"] or 0),
            "referrals": customers.filter(referred_by__isnull=False).count(),
            "month_entries": PointEntry.objects.filter(created_at__date__gte=month_start).count(),
            "top": customers.filter(points_lifetime__gt=0).order_by("-points_lifetime")[:10],
            "recent": PointEntry.objects.select_related("customer")[:15],
        },
    )


class PointsForm(forms.Form):
    points = forms.IntegerField(label="امتیاز", help_text="مثبت برای افزودن، منفی برای استفاده (مثلاً ‎-100)")
    note = forms.CharField(label="توضیح", max_length=160)


@panel_view(perm="segments")
@require_POST
def customer_points(request, pk):
    customer = get_object_or_404(scoped(request, Customer.objects.all()), pk=pk)
    form = PointsForm(request.POST)
    back = reverse("panel:customer", args=[customer.pk]) + "#club"
    if not form.is_valid() or form.cleaned_data["points"] == 0:
        messages.error(request, "امتیاز و توضیح را بنویسید.")
        return redirect(back)
    pts = form.cleaned_data["points"]
    if pts < 0 and customer.points_balance + pts < 0:
        messages.error(request, f"موجودی امتیاز {customer.full_name} کافی نیست.")
        return redirect(back)
    reason = PointEntry.Reason.REDEEM if pts < 0 else PointEntry.Reason.MANUAL
    entry = award(customer, pts, reason, note=form.cleaned_data["note"], by=request.user)
    if entry is None:
        messages.error(request, "باشگاه مشتریان خاموش است؛ از صفحه باشگاه روشنش کنید.")
    else:
        messages.success(request, "امتیاز ثبت شد.")
    return redirect(back)


def customer_club_context(request, customer):
    from apps.crm.segments import cross_sell

    club = ClubSettings.for_tenant(request.tenant)
    ctx = {"cross_sell": cross_sell(customer), "club": club}
    if club.enabled:
        code = referral_code_for(customer)
        ctx.update(
            points=PointEntry.objects.filter(customer=customer)[:10],
            tier_label=TIER_LABELS.get(customer.tier, ""),
            ref_link=f"{request.tenant.site_url()}?c={code}",
            referrals=customer.referrals.all()[:10],
            points_form=PointsForm(),
        )
    return ctx
