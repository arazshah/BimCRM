"""Claims on the agent's public site: report a loss, upload papers, sign, chat with the office and follow progress.

The policyholder logs in with the same SMS code as the customer portal; every query is limited to the
claims of that customer, so nobody can reach another person's file by guessing a number.
"""

from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.claims import services
from apps.claims.models import Claim, ClaimDocRequest, ClaimEvent, ClaimFormFile
from apps.crm.models import Policy

from .views import _customer_mobile, _features, _is_team_member, _portal_customer, _site, _site_context

# Steps the policyholder sees, in order. «نیاز به مدارک» is shown only while it is the current status.
STEPS = [
    (Claim.Status.REPORTED, "اعلام شد"),
    (Claim.Status.SUBMITTED, "ارسال به شرکت بیمه"),
    (Claim.Status.INSPECTION, "بازدید کارشناس"),
    (Claim.Status.APPROVED, "تأیید شد"),
    (Claim.Status.PAID, "پرداخت شد"),
]
_ORDER = {s: i for i, (s, _) in enumerate(STEPS)}
_ORDER[Claim.Status.DOCS_NEEDED] = 0

CLAIM_HELP = {
    Claim.Status.REPORTED: "پرونده شما رسید و دفتر در حال بررسی است.",
    Claim.Status.DOCS_NEEDED: "برای ادامه کار، مدارک خواسته‌شده را از همین صفحه بفرستید.",
    Claim.Status.SUBMITTED: "پرونده برای شرکت بیمه ارسال شده است.",
    Claim.Status.INSPECTION: "منتظر بازدید یا نظر کارشناس شرکت بیمه هستیم.",
    Claim.Status.APPROVED: "خسارت تأیید شد؛ پرداخت در مراحل انجام است.",
    Claim.Status.PAID: "خسارت پرداخت شد.",
    Claim.Status.REJECTED: "پرونده رد شد. برای توضیح بیشتر با دفتر گفتگو کنید.",
}


def _stepper(claim):
    current = _ORDER.get(claim.status, -1)
    steps = []
    for i, (_status, label) in enumerate(STEPS):
        steps.append({"label": label, "state": "done" if i < current else "now" if i == current else "todo"})
    if claim.status == Claim.Status.REJECTED:
        steps = [{"label": s["label"], "state": "todo"} for s in steps]
        steps.append({"label": "رد شد", "state": "bad"})
    elif claim.status == Claim.Status.DOCS_NEEDED:
        steps[0]["label"] = "نیاز به مدارک"
    elif claim.status == Claim.Status.PAID:
        steps[-1]["state"] = "done"
    return steps


def _forms_for(line):
    return ClaimFormFile.objects.filter(Q(line=line) | Q(line__isnull=True))


def _gate(request):
    """Common checks. Returns (context, None) or (None, response)."""
    if "claims" not in _features(request):
        raise Http404
    site = _site(request)
    if not site.is_published and not _is_team_member(request):
        return None, render(request, "sites/coming_soon.html", {"tenant": request.tenant})
    ctx = _site_context(request, site)
    ctx["is_noindex"] = True
    ctx["claims_nav"] = True
    return ctx, None


def _need_login(request, ctx):
    """None when the customer is logged in; otherwise a response that sends them to the SMS login."""
    if _customer_mobile(request):
        return None
    if not ctx["can_portal"]:
        return render(request, "sites/claims/no_login.html", ctx)
    request.session["portal_next"] = request.get_full_path()
    return redirect("sites:account")


def _own_claim(request, pk):
    customer = _portal_customer(request)
    if customer is None:
        raise Http404
    return get_object_or_404(
        Claim.objects.select_related("policy__line", "policy__company", "policy__customer"),
        pk=pk,
        policy__customer=customer,
    )


def claims_home(request):
    ctx, resp = _gate(request)
    if resp:
        return resp
    ctx["is_noindex"] = False
    ctx["page_title"] = f"اعلام و پیگیری خسارت | {request.tenant.name}"
    ctx["page_description"] = (
        f"خسارت بیمه خود را آنلاین به دفتر {request.tenant.name} اعلام کنید، مدارک را بفرستید و مراحل را پیگیری کنید."
    )
    ctx["forms"] = ClaimFormFile.objects.select_related("line")
    ctx["logged_in"] = bool(_customer_mobile(request))
    ctx["lines_help"] = [{"line": line, "slots": services.doc_slots(line)} for line in ctx["lines"][:4]]
    return render(request, "sites/claims/home.html", ctx)


def claims_mine(request):
    ctx, resp = _gate(request)
    if resp:
        return resp
    if (resp := _need_login(request, ctx)) is not None:
        return resp
    customer = _portal_customer(request)
    claims = (
        Claim.objects.filter(policy__customer=customer).select_related("policy__line", "policy__company")
        if customer
        else []
    )
    ctx.update({"claims": claims, "customer": customer, "mobile": _customer_mobile(request)})
    return render(request, "sites/claims/mine.html", ctx)


def _report_context(request, ctx, customer, policy_id=None):
    policies = list(
        Policy.objects.filter(customer=customer, status=Policy.Status.ACTIVE).select_related("line", "company")
    )
    chosen = next((p for p in policies if str(p.pk) == str(policy_id)), policies[0] if policies else None)
    ctx.update(
        {
            "customer": customer,
            "claimable": policies,
            "chosen": chosen,
            "slots": services.doc_slots(chosen.line) if chosen else [],
            "forms": _forms_for(chosen.line) if chosen else [],
            "today": timezone.localdate().isoformat(),
        }
    )
    return ctx


def claim_new(request):
    ctx, resp = _gate(request)
    if resp:
        return resp
    if (resp := _need_login(request, ctx)) is not None:
        return resp
    customer = _portal_customer(request)
    if customer is None:
        ctx["mobile"] = _customer_mobile(request)
        return render(request, "sites/claims/no_customer.html", ctx)
    _report_context(request, ctx, customer, request.POST.get("policy") or request.GET.get("policy"))
    if request.method != "POST":
        return render(request, "sites/claims/new.html", ctx)

    errors = []
    policy = next((p for p in ctx["claimable"] if str(p.pk) == request.POST.get("policy")), None)
    incident = parse_date(request.POST.get("incident_date", ""))
    description = request.POST.get("description", "").strip()[:2000]
    iban = request.POST.get("iban", "").replace(" ", "").upper()[:26]
    signature = request.POST.get("signature_data", "")
    uploads = {k["kind"]: request.FILES.getlist(k["kind"]) for k in ctx["slots"]}
    if policy is None:
        errors.append("بیمه‌نامه را انتخاب کنید.")
    if incident is None or incident > timezone.localdate():
        errors.append("تاریخ حادثه را درست وارد کنید.")
    if len(description) < 10:
        errors.append("شرح حادثه را کمی کامل‌تر بنویسید.")
    if iban and not (iban.startswith("IR") and len(iban) == 26):
        errors.append("شماره شبا باید به صورت IR و ۲۴ رقم باشد، یا آن را خالی بگذارید.")
    if not request.POST.get("declaration"):
        errors.append("تأیید صحت اطلاعات الزامی است.")
    if signature and services.decode_signature(signature) is None:
        signature = ""
        errors.append("امضا معتبر نبود؛ دوباره در کادر امضا کنید.")
    elif not signature and not uploads.get("form"):
        errors.append("اظهارنامه را امضا کنید یا فرم امضاشده را بارگذاری کنید.")
    for files in uploads.values():
        for f in files:
            if err := services.validate_upload(f):
                errors.append(f"{f.name}: {err}")
    try:
        amount = max(0, int(request.POST.get("amount_claimed", "0").replace(",", "").strip() or 0))
    except ValueError:
        amount = 0
        errors.append("مبلغ برآوردی را به عدد وارد کنید.")
    if errors:
        for e in dict.fromkeys(errors):
            messages.error(request, e)
        ctx["posted"] = request.POST
        return render(request, "sites/claims/new.html", ctx)

    claim = Claim.objects.create(
        policy=policy,
        incident_date=incident,
        description=description,
        incident_place=request.POST.get("incident_place", "").strip()[:200],
        third_party=request.POST.get("third_party", "").strip()[:1000],
        amount_claimed=amount,
        iban=iban,
        reported_by_customer=True,
        office_unread=True,
    )
    ClaimEvent.objects.create(claim=claim, status=claim.status, note="اعلام از سایت توسط بیمه‌گذار")
    if signature:
        services.save_signature(claim, signature)
    failed = None
    for kind, files in uploads.items():
        _, err = services.save_customer_files(claim, files, kind)
        failed = failed or err
    from apps.work.services import on_customer_claim

    on_customer_claim(claim)
    messages.success(request, f"خسارت شما با پرونده شماره {claim.code} ثبت شد. از همین صفحه مراحل را دنبال کنید.")
    if failed:
        messages.error(request, "بعضی فایل‌ها ذخیره نشد: " + failed)
    return redirect("sites:claim_detail", pk=claim.pk)


def claim_detail(request, pk):
    ctx, resp = _gate(request)
    if resp:
        return resp
    if (resp := _need_login(request, ctx)) is not None:
        return resp
    claim = _own_claim(request, pk)
    docs = list(claim.documents.exclude(kind="signature"))
    ctx.update(
        {
            "claim": claim,
            "steps": _stepper(claim),
            "status_help": CLAIM_HELP.get(claim.status, ""),
            "events": claim.events.all(),
            "documents": docs,
            "signature": claim.documents.filter(kind="signature").first(),
            "open_requests": claim.doc_requests.filter(done=False),
            "done_requests": claim.doc_requests.filter(done=True),
            "thread": claim.messages.select_related("author"),
            "forms": _forms_for(claim.policy.line),
            "slots": services.doc_slots(claim.policy.line),
        }
    )
    return render(request, "sites/claims/detail.html", ctx)


@require_POST
def claim_upload(request, pk):
    if "claims" not in _features(request):
        raise Http404
    claim = _own_claim(request, pk)
    if not claim.is_open:
        messages.error(request, "این پرونده بسته شده است؛ برای مورد تازه از دفتر بپرسید.")
        return redirect("sites:claim_detail", pk=claim.pk)
    files = request.FILES.getlist("file")
    if not files:
        messages.error(request, "فایل را انتخاب کنید.")
        return redirect("sites:claim_detail", pk=claim.pk)
    doc_request = None
    if request.POST.get("request"):
        doc_request = ClaimDocRequest.objects.filter(pk=request.POST["request"], claim=claim).first()
    kind = request.POST.get("kind", "other")
    title = request.POST.get("title", "").strip()[:120] or (doc_request.title if doc_request else "")
    saved, err = services.save_customer_files(claim, files, kind, title, doc_request)
    if saved:
        services.flag_office(claim, f"{saved} مدرک تازه فرستاد" + (f" ({title})" if title else ""))
        messages.success(request, "مدرک رسید؛ دفتر بررسی می‌کند.")
    if err:
        messages.error(request, err)
    return redirect("sites:claim_detail", pk=claim.pk)


@require_POST
def claim_message(request, pk):
    if "claims" not in _features(request):
        raise Http404
    claim = _own_claim(request, pk)
    text = request.POST.get("text", "").strip()
    if len(text) < 2:
        messages.error(request, "پیام را بنویسید.")
    else:
        services.add_message(claim, text, by_customer=True)
        services.flag_office(claim, "پیام تازه: " + text[:80])
        messages.success(request, "پیام شما برای دفتر فرستاده شد.")
    return redirect("sites:claim_detail", pk=claim.pk)


@require_POST
def claim_sign(request, pk):
    if "claims" not in _features(request):
        raise Http404
    claim = _own_claim(request, pk)
    if request.POST.get("declaration") and services.save_signature(claim, request.POST.get("signature_data", "")):
        services.flag_office(claim, "اظهارنامه را امضا کرد")
        messages.success(request, "امضا ثبت شد.")
    else:
        messages.error(request, "امضا را در کادر بکشید و تأیید صحت اطلاعات را بزنید.")
    return redirect("sites:claim_detail", pk=claim.pk)


def claim_file(request, pk, doc_id):
    """The policyholder's own uploaded papers (the media route is for logged-in office members only)."""
    if "claims" not in _features(request):
        raise Http404
    claim = _own_claim(request, pk)
    doc = get_object_or_404(claim.documents, pk=doc_id)
    try:
        return FileResponse(doc.file.open("rb"), as_attachment=False)
    except (OSError, ValueError):
        raise Http404
