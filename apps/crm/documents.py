"""Which papers a customer still owes, based on the lines of their open requests and active policies."""

from django.utils import timezone

from .models import CustomerDocument, Policy, QuoteRequest

KIND_LABELS = dict(CustomerDocument.Kind.choices)
MAX_UPLOAD = 15 * 1024 * 1024
ALLOWED_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf")


def checklist(customer, lines) -> list[dict]:
    have = set(CustomerDocument.objects.filter(customer=customer).values_list("kind", flat=True)) if customer else set()
    out, seen = [], set()
    for line in lines:
        for kind in line.required_docs or []:
            if kind in seen or kind not in KIND_LABELS:
                continue
            seen.add(kind)
            out.append({"kind": kind, "label": KIND_LABELS[kind], "ok": kind in have, "line": line.name})
    return out


def customer_lines(customer):
    """Lines of the customer's open site requests and active policies (for the documents checklist)."""
    from apps.core.models import LineOfBusiness

    ids = set(
        Policy.objects.filter(
            customer=customer, status=Policy.Status.ACTIVE, end_date__gte=timezone.localdate()
        ).values_list("line_id", flat=True)
    )
    ids |= set(
        QuoteRequest.objects.filter(mobile=customer.mobile)
        .exclude(status__in=[QuoteRequest.Status.ISSUED, QuoteRequest.Status.LOST])
        .values_list("line_id", flat=True)
    )
    return list(LineOfBusiness.objects.filter(pk__in=ids).order_by("order"))


def validate_upload(f) -> str | None:
    if f.size > MAX_UPLOAD:
        return "حجم فایل بیشتر از ۱۵ مگابایت است."
    if not f.name.lower().endswith(ALLOWED_EXT):
        return "فقط عکس (jpg، png) یا PDF بفرستید."
    return None
