"""Awarding and spending club points."""

import logging
import secrets

from django.db import IntegrityError, transaction
from django.db.models import Sum

from .models import TIER_LABELS, ClubSettings, PointEntry

log = logging.getLogger(__name__)
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def referral_code_for(customer) -> str:
    """Short code customers share; created on first use."""
    from apps.crm.models import Customer

    if customer.referral_code:
        return customer.referral_code
    for _ in range(10):
        code = "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if not Customer.all_objects.filter(tenant_id=customer.tenant_id, referral_code=code).exists():
            Customer.all_objects.filter(pk=customer.pk).update(referral_code=code)
            customer.referral_code = code
            return code
    raise RuntimeError("could not allocate a referral code")


def recalc(customer, club=None) -> str | None:
    """Refreshes cached balance/lifetime/tier; returns the new tier if it went up."""
    from apps.crm.models import Customer

    agg = PointEntry.all_objects.filter(customer=customer)
    balance = agg.aggregate(s=Sum("points"))["s"] or 0
    lifetime = agg.filter(points__gt=0).aggregate(s=Sum("points"))["s"] or 0
    club = club or ClubSettings.for_tenant(customer.tenant)
    tier = club.tier_for(lifetime)
    order = ["bronze", "silver", "gold"]
    went_up = order.index(tier) > order.index(customer.tier or "bronze")
    Customer.all_objects.filter(pk=customer.pk).update(points_balance=balance, points_lifetime=lifetime, tier=tier)
    customer.points_balance, customer.points_lifetime, customer.tier = balance, lifetime, tier
    return tier if went_up else None


def award(
    customer, points: int, reason: str, key: str = "", note: str = "", policy=None, by=None, club=None
) -> PointEntry | None:
    club = club or ClubSettings.for_tenant(customer.tenant)
    if not club.enabled or not points:
        return None
    try:
        with transaction.atomic():
            entry = PointEntry.all_objects.create(
                tenant_id=customer.tenant_id,
                customer=customer,
                points=points,
                reason=reason,
                key=key,
                note=note,
                policy=policy,
                created_by=by,
            )
    except IntegrityError:
        return None
    new_tier = recalc(customer, club)
    if new_tier and club.sms_on_reward:
        _sms(
            customer,
            f"{customer.full_name} عزیز، تبریک! در باشگاه مشتریان {customer.tenant.name} به سطح {TIER_LABELS[new_tier]} رسیدید.",
            f"tier:{customer.pk}:{new_tier}",
        )
    return entry


def _sms(customer, text, key):
    from apps.integrations.senders import tenant_can_sms
    from apps.messaging.models import MessageLog
    from apps.messaging.services import send_logged

    if customer.sms_opt_out or not tenant_can_sms(customer.tenant):
        return
    try:
        send_logged(customer.tenant, MessageLog.Kind.CLUB, f"club:{key}", customer.mobile, text)
    except Exception:
        log.exception("club SMS failed")


def on_policy_created(policy):
    customer = policy.customer
    club = ClubSettings.for_tenant(customer.tenant)
    if not club.enabled:
        return
    pts = policy.premium * club.points_per_million // 10_000_000
    award(
        customer,
        pts,
        PointEntry.Reason.POLICY,
        key=f"policy:{policy.pk}",
        note=f"{policy.line} {policy.number}",
        policy=policy,
        club=club,
    )
    if policy.renewed_from_id:
        award(
            customer,
            club.renewal_bonus,
            PointEntry.Reason.RENEWAL,
            key=f"renewal:{policy.pk}",
            policy=policy,
            club=club,
        )
    ref = customer.referred_by
    if ref and customer.policies.count() == 1:
        if (
            award(
                ref,
                club.referral_bonus,
                PointEntry.Reason.REFERRAL,
                key=f"referral:{customer.pk}",
                note=f"معرفی {customer.full_name}",
                club=club,
            )
            and club.sms_on_reward
        ):
            _sms(
                ref,
                f"{ref.full_name} عزیز، {customer.full_name} با معرفی شما مشتری {customer.tenant.name} شد و {club.referral_bonus} امتیاز گرفتید. ممنون از اعتمادتان.",
                f"ref:{customer.pk}",
            )


def on_installment_paid(inst):
    if inst.paid_at and inst.paid_at <= inst.due_date:
        club = ClubSettings.for_tenant(inst.tenant)
        award(
            inst.policy.customer,
            club.installment_bonus,
            PointEntry.Reason.INSTALLMENT,
            key=f"inst:{inst.pk}",
            policy=inst.policy,
            club=club,
        )
