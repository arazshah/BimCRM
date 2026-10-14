"""Panel access: logged-in member of this workspace, active workspace, write blocked once expired."""

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from apps.accounts.models import Membership
from apps.billing.models import Addon
from apps.core.models import Tenant

MANAGERS = (Membership.Role.OWNER, Membership.Role.MANAGER)


def _login_redirect(request):
    scheme = settings.PLATFORM_SCHEME
    nxt = quote(request.build_absolute_uri(), safe="")
    return redirect(f"{scheme}://{settings.PLATFORM_DOMAIN}/login/?next={nxt}")


def panel_view(*, write_ok_when_expired=False, managers_only=False, feature=None, office_wide=False, perm=None):
    """office_wide: whole-office pages (books, commissions, reports) closed to branch-limited staff.
    perm: a STAFF_PERMS code; staff without it get a friendly "ask your manager" page."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            tenant = request.tenant
            if not request.user.is_authenticated:
                return _login_redirect(request)
            membership = Membership.objects.filter(tenant=tenant, user=request.user, is_active=True).first()
            if membership is None:
                return render(request, "panel/no_access.html", status=403)
            if tenant.status == Tenant.Status.SUSPENDED:
                return render(request, "panel/suspended.html", status=403)
            request.membership = membership
            from django.db.models import Q
            from django.utils import timezone

            from apps.work.models import Notification, Task

            request.unread_count = Notification.objects.filter(user=request.user, read_at__isnull=True).count()
            request.due_tasks = (
                Task.objects.filter(done_at__isnull=True, due_date__lte=timezone.localdate())
                .filter(Q(assigned_to=request.user) | Q(assigned_to__isnull=True))
                .count()
            )
            request.subscription = getattr(tenant, "subscription", None)
            request.features = request.subscription.active_addon_codes() if request.subscription else set()
            # Staff assigned to a branch only see that branch's records (branches add-on).
            request.branch_scope = (
                membership.branch
                if membership.branch_id and membership.role not in MANAGERS and "branches" in request.features
                else None
            )
            request.can = membership.can_map()
            if managers_only and membership.role not in MANAGERS:
                return HttpResponseForbidden("این بخش فقط برای مالک و مدیر دفتر است.")
            if perm and not membership.can(perm):
                return render(request, "panel/no_perm.html", status=403)
            if office_wide and request.branch_scope is not None:
                return HttpResponseForbidden("این بخش برای کل دفتر است و کارمندان شعبه به آن دسترسی ندارند.")
            if feature and feature not in request.features:
                addon = Addon.objects.filter(code=feature).first()
                return render(request, "panel/feature_locked.html", {"addon": addon}, status=402)
            sub = request.subscription
            if request.method == "POST" and sub and not sub.is_writable and not write_ok_when_expired:
                messages.error(request, "اشتراک منقضی شده و محیط فقط‌خواندنی است. از بخش اشتراک تمدید کنید.")
                return redirect("panel:billing")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def storage_used_bytes(tenant) -> int:
    from django.db.models import Sum

    from apps.claims.models import ClaimDocument
    from apps.crm.models import CustomerDocument, Policy

    policies = Policy.all_objects.filter(tenant=tenant).aggregate(s=Sum("file_size"))["s"] or 0
    claims = ClaimDocument.objects.filter(claim__tenant=tenant).aggregate(s=Sum("size"))["s"] or 0
    docs = CustomerDocument.all_objects.filter(tenant=tenant).aggregate(s=Sum("size"))["s"] or 0
    return policies + claims + docs


def scoped(request, qs, path: str = "branch", include_unassigned: bool = False):
    """Limits a queryset to the user's branch when they are branch-limited staff.

    include_unassigned also keeps rows with no branch (e.g. website leads nobody has routed yet).
    Managers can narrow lists with ?b=<branch id>.
    """
    from django.db.models import Q

    scope = getattr(request, "branch_scope", None)
    if scope is not None:
        cond = Q(**{path: scope})
        if include_unassigned:
            cond |= Q(**{f"{path}__isnull": True})
        return qs.filter(cond)
    b = request.GET.get("b", "")
    if b.isdigit() and "branches" in getattr(request, "features", ()):
        return qs.filter(**{f"{path}_id": int(b)})
    return qs


def branch_filter(request) -> dict:
    """Context for the managers' branch dropdown on list pages (branches add-on)."""
    if "branches" not in request.features or request.branch_scope is not None:
        return {}
    from apps.crm.models import Branch

    return {"branches": Branch.objects.filter(is_active=True), "b": request.GET.get("b", "")}
