"""Panel access: logged-in member of this workspace, active workspace, write blocked once expired."""

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from apps.accounts.models import Membership
from apps.billing.models import has_feature
from apps.core.models import Tenant

MANAGERS = (Membership.Role.OWNER, Membership.Role.MANAGER)


def _login_redirect(request):
    scheme = settings.PLATFORM_SCHEME
    nxt = quote(request.build_absolute_uri(), safe="")
    return redirect(f"{scheme}://{settings.PLATFORM_DOMAIN}/login/?next={nxt}")


def panel_view(*, write_ok_when_expired=False, managers_only=False, feature=None):
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
            request.subscription = getattr(tenant, "subscription", None)
            if managers_only and membership.role not in MANAGERS:
                return HttpResponseForbidden("این بخش فقط برای مالک و مدیر دفتر است.")
            if feature and not has_feature(tenant, feature):
                return render(request, "panel/feature_locked.html", {"feature": feature}, status=402)
            sub = request.subscription
            if request.method == "POST" and sub and not sub.is_writable and not write_ok_when_expired:
                messages.error(request, "اشتراک منقضی شده و محیط فقط‌خواندنی است. از بخش اشتراک تمدید کنید.")
                return redirect("panel:billing")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def storage_used_bytes(tenant) -> int:
    from django.db.models import Sum

    from apps.crm.models import Policy

    return Policy.all_objects.filter(tenant=tenant).aggregate(s=Sum("file_size"))["s"] or 0
