"""Claim helpers shared by the customer site and the office panel."""

import base64
import io

from django.core.files.base import ContentFile
from django.utils import timezone

from .models import Claim, ClaimDocument, ClaimEvent, ClaimMessage

UPLOAD_MAX = 10 * 1024 * 1024
UPLOAD_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf")
MAX_FILES_PER_REQUEST = 12
SIGNATURE_MAX = 300 * 1024

K = ClaimDocument.Kind

# What the policyholder is asked to send, by line of business (slug). Generic list for any other line.
_GENERIC = [
    (K.PHOTO, "عکس‌های خسارت", "از چند زاویه؛ نزدیک و دور"),
    (K.REPORT, "گزارش رسمی یا کارشناسی", "گزارش پلیس، کروکی، گزارش آتش‌نشانی یا نظر کارشناس (در صورت وجود)"),
    (K.IDENTITY, "مدارک هویتی و بیمه‌نامه", "کارت ملی، تصویر بیمه‌نامه و مدارک مالکیت"),
    (K.INVOICE, "فاکتور یا مدارک هزینه", "فاکتور تعمیر، صورت‌حساب بیمارستان یا برآورد هزینه"),
    (K.FORM, "فرم خسارت امضاشده", "فرم را از همین صفحه دانلود، پر و امضا کنید و عکسش را بفرستید"),
]
_HINTS = {
    "third-party": {
        K.PHOTO: "عکس از صحنه، هر دو خودرو و محل برخورد",
        K.REPORT: "کروکی یا گزارش پلیس راهور",
        K.IDENTITY: "گواهینامه، کارت خودرو، کارت ملی و بیمه‌نامه شخص ثالث هر دو طرف",
    },
    "car-body": {
        K.PHOTO: "عکس از همه زوایای خودرو و محل آسیب",
        K.REPORT: "کروکی، گزارش پلیس یا گزارش سرقت",
        K.IDENTITY: "گواهینامه، کارت خودرو، کارت ملی و بیمه‌نامه بدنه",
    },
    "home-fire": {
        K.PHOTO: "عکس و فیلم کوتاه از محل آسیب و اموال خسارت‌دیده",
        K.REPORT: "گزارش آتش‌نشانی یا نظر کارشناس",
        K.IDENTITY: "سند یا اجاره‌نامه، کارت ملی و بیمه‌نامه",
    },
    "health": {
        K.PHOTO: "عکس مدارک پزشکی (نسخه، گزارش پزشک)",
        K.REPORT: "گزارش پزشک یا پاراکلینیک",
        K.IDENTITY: "کارت ملی و کارت بیمه",
        K.INVOICE: "اصل صورت‌حساب بیمارستان/داروخانه/دندان‌پزشکی",
    },
}


def doc_slots(line) -> list[dict]:
    slug = getattr(line, "slug", "")
    hints = _HINTS.get(slug, {})
    return [{"kind": k, "label": label, "hint": hints.get(k, hint)} for k, label, hint in _GENERIC]


def validate_upload(f) -> str | None:
    if f.size > UPLOAD_MAX:
        return "حجم هر فایل حداکثر ۱۰ مگابایت است."
    if not f.name.lower().endswith(UPLOAD_EXT):
        return "فقط عکس یا PDF بفرستید."
    return None


def storage_left(tenant) -> int | None:
    from apps.panel.access import storage_used_bytes

    sub = getattr(tenant, "subscription", None)
    if sub is None:
        return None
    return sub.storage_limit_bytes() - storage_used_bytes(tenant)


def save_customer_files(claim, files, kind, title="", doc_request=None) -> tuple[int, str | None]:
    """Stores the files a policyholder sent. Returns (saved count, first error)."""
    saved, error = 0, None
    left = storage_left(claim.tenant)
    kind = kind if kind in K.values and kind != K.SIGNATURE else K.OTHER
    for f in files[:MAX_FILES_PER_REQUEST]:
        err = validate_upload(f)
        if not err and left is not None and f.size > left:
            err = "امکان بارگذاری نیست؛ لطفاً با دفتر تماس بگیرید."
        if err:
            error = error or err
            continue
        if left is not None:
            left -= f.size
        ClaimDocument.objects.create(
            claim=claim,
            kind=kind,
            title=(title or K(kind).label)[:120],
            file=f,
            uploaded_by_customer=True,
            request=doc_request,
        )
        saved += 1
    if saved and doc_request is not None and not doc_request.done:
        doc_request.done = True
        doc_request.save(update_fields=["done"])
    return saved, error


def decode_signature(data_url: str) -> bytes | None:
    """The PNG bytes of a canvas signature, or None when it is not a small, valid PNG."""
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix) or len(data_url) > SIGNATURE_MAX * 2:
        return None
    try:
        raw = base64.b64decode(data_url[len(prefix) :], validate=True)
        if len(raw) > SIGNATURE_MAX:
            return None
        from PIL import Image

        Image.open(io.BytesIO(raw)).verify()
    except Exception:
        return None
    return raw


def save_signature(claim, data_url: str) -> bool:
    """Stores a hand-drawn signature and marks the declaration as signed."""
    raw = decode_signature(data_url)
    if raw is None:
        return False
    doc = ClaimDocument(claim=claim, kind=K.SIGNATURE, title="امضای اظهارنامه", uploaded_by_customer=True)
    doc.file.save("signature.png", ContentFile(raw), save=False)
    doc.save()
    claim.signed_at = timezone.now()
    claim.save(update_fields=["signed_at"])
    return True


def flag_office(claim, text: str):
    """Marks the claim as having something new from the customer and tells the colleagues."""
    from django.urls import reverse

    from apps.work.services import notify, office_members

    Claim.all_objects.filter(pk=claim.pk).update(office_unread=True)
    notify(
        claim.tenant,
        office_members(claim.tenant, getattr(claim.policy.customer, "branch", None)),
        f"خسارت {claim.code} — {claim.policy.customer.full_name}: {text}",
        reverse("panel:claim", args=[claim.pk]),
    )


def add_message(claim, text: str, *, by_customer: bool, author=None) -> ClaimMessage:
    msg = ClaimMessage.objects.create(claim=claim, text=text.strip()[:2000], by_customer=by_customer, author=author)
    return msg


def request_documents(claim, titles: list[str], note: str, user) -> list:
    """The office asks for specific papers; moves the claim to «نیاز به مدارک» and tells the customer."""
    from apps.messaging.services import notify_claim

    from .models import ClaimDocRequest

    rows = [
        ClaimDocRequest.objects.create(claim=claim, title=t[:120], note=note[:300], created_by=user)
        for t in titles
        if t.strip()
    ]
    if rows:
        claim.status = Claim.Status.DOCS_NEEDED
        claim.save(update_fields=["status", "updated_at"])
        text = "لطفاً این مدارک را از صفحه پیگیری خسارت بفرستید: " + "، ".join(r.title for r in rows)
        ClaimEvent.objects.create(claim=claim, status=claim.status, note=text[:300], created_by=user)
        notify_claim(claim, text[:200])
    return rows
