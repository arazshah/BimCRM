"""Serves uploaded files. Logos are public; policy files and ticket attachments need a logged-in owner."""

from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404

PUBLIC_PREFIXES = ("logos/", "companies/", "showcases/", "lines/", "claimforms/")


def serve_media(request, path):
    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise Http404
    if not path.startswith(PUBLIC_PREFIXES) and not _may_read_private(request, path):
        raise Http404
    return FileResponse(open(target, "rb"))


def _may_read_private(request, path: str) -> bool:
    user = request.user
    if not user.is_authenticated:
        return False
    if request.host_kind == "admin":
        return user.is_staff
    tenant = request.tenant
    if tenant is None or not tenant.memberships.filter(user=user, is_active=True).exists():
        return False
    from apps.crm.models import Policy
    from apps.tickets.models import TicketMessage

    if path.startswith("policies/"):
        return Policy.all_objects.filter(tenant=tenant, file=path).exists()
    if path.startswith("claims/"):
        from apps.claims.models import ClaimDocument

        return ClaimDocument.objects.filter(claim__tenant=tenant, file=path).exists()
    if path.startswith("documents/"):
        from apps.crm.models import CustomerDocument

        return CustomerDocument.all_objects.filter(tenant=tenant, file=path).exists()
    if path.startswith("cheques/"):
        from apps.finance.models import Cheque

        return Cheque.all_objects.filter(tenant=tenant, image=path).exists()
    if path.startswith("tickets/"):
        return TicketMessage.objects.filter(ticket__tenant=tenant, attachment=path).exists()
    return False
