"""Read-only finance reports built from policies, receipts, installments, cheques and payments (rials).

Customer balance = premiums issued − money received. "Money received" is every active receipt line, plus
installments an office marked paid by hand without writing a receipt (older data), so nothing is counted twice.
"""

from collections import defaultdict
from datetime import date

from django.db.models import Sum

from apps.crm.models import Customer, Policy

from .models import Cheque, Installment, PaymentOrder, Receipt, ReceiptLine


def _unreceipted_paid_installments(customer_ids=None):
    qs = Installment.objects.filter(status=Installment.Status.PAID).exclude(
        pk__in=ReceiptLine.objects.filter(receipt__status=Receipt.Status.ACTIVE, installment__isnull=False).values(
            "installment_id"
        )
    )
    if customer_ids is not None:
        qs = qs.filter(policy__customer_id__in=customer_ids)
    return qs.select_related("policy__line")


def customer_statement(customer: Customer) -> dict:
    """Chronological rows with a running balance (positive = the customer owes the office)."""
    rows = []
    for p in Policy.objects.filter(customer=customer).exclude(status=Policy.Status.CANCELLED).select_related("line"):
        rows.append(
            {
                "date": p.start_date,
                "text": f"حق بیمه {p.line} {p.number}",
                "debit": p.premium,
                "credit": 0,
                "link": ("policy", p.pk),
                "order": 0,
            }
        )
    for r in Receipt.objects.filter(customer=customer, status=Receipt.Status.ACTIVE).prefetch_related("lines"):
        rows.append(
            {
                "date": r.date,
                "text": f"رسید دریافت {r.number}" + (f" — {r.description}" if r.description else ""),
                "debit": 0,
                "credit": r.total,
                "link": ("receipt", r.pk),
                "order": 1,
            }
        )
    for i in _unreceipted_paid_installments([customer.pk]):
        rows.append(
            {
                "date": i.paid_at or i.due_date,
                "text": f"وصول قسط {i.policy.line} (بدون رسید)",
                "debit": 0,
                "credit": i.amount,
                "link": None,
                "order": 1,
            }
        )
    rows.sort(key=lambda r: (r["date"], r["order"]))
    balance = 0
    for r in rows:
        balance += r["debit"] - r["credit"]
        r["balance"] = balance
    return {
        "rows": rows,
        "debit": sum(r["debit"] for r in rows),
        "credit": sum(r["credit"] for r in rows),
        "balance": balance,
    }


def debtors(customers_qs, minimum: int = 1) -> list[dict]:
    """Customers who owe the office, biggest debt first. customers_qs limits who is considered (branch scope)."""
    ids = list(customers_qs.values_list("pk", flat=True))
    if not ids:
        return []
    owed = defaultdict(int)
    for cid, total in (
        Policy.objects.filter(customer_id__in=ids)
        .exclude(status=Policy.Status.CANCELLED)
        .values_list("customer_id")
        .annotate(s=Sum("premium"))
    ):
        owed[cid] += total or 0
    for cid, total in (
        ReceiptLine.objects.filter(receipt__customer_id__in=ids, receipt__status=Receipt.Status.ACTIVE)
        .values_list("receipt__customer_id")
        .annotate(s=Sum("amount"))
    ):
        owed[cid] -= total or 0
    for i in _unreceipted_paid_installments(ids):
        owed[i.policy.customer_id] -= i.amount
    out = [{"customer": c, "balance": owed[c.pk]} for c in customers_qs.filter(pk__in=ids) if owed[c.pk] >= minimum]
    out.sort(key=lambda r: -r["balance"])
    return out


def daily_cash(day: date) -> dict:
    """Everything that moved on one day: receipt lines, cleared cheques and payment orders, with totals per account."""
    movements = []
    for line in ReceiptLine.objects.filter(receipt__date=day, receipt__status=Receipt.Status.ACTIVE).select_related(
        "receipt__customer", "account", "cheque"
    ):
        movements.append(
            {
                "kind": "in",
                "text": f"رسید {line.receipt.number} — {line.receipt.customer.full_name} ({line.get_method_display()})",
                "account": line.account.title if line.account else "چک نزد صندوق",
                "account_id": line.account_id,
                "amount": line.amount,
                "counts": line.method != ReceiptLine.Method.CHEQUE,
            }
        )
    for c in Cheque.objects.filter(
        status=Cheque.Status.CLEARED, events__to_status=Cheque.Status.CLEARED, events__date=day
    ).select_related("deposit_account", "customer"):
        movements.append(
            {
                "kind": "in",
                "text": f"وصول چک {c.serial} — {c.customer.full_name}",
                "account": c.deposit_account.title if c.deposit_account else "—",
                "account_id": c.deposit_account_id,
                "amount": c.amount,
                "counts": True,
            }
        )
    for o in PaymentOrder.objects.filter(date=day, status=PaymentOrder.Status.ACTIVE).select_related("account"):
        movements.append(
            {
                "kind": "out",
                "text": f"حواله {o.number} — {o.payee}",
                "account": o.account.title,
                "account_id": o.account_id,
                "amount": o.amount,
                "counts": True,
            }
        )
    per_account = defaultdict(lambda: {"in": 0, "out": 0})
    for m in movements:
        if m["counts"] and m["account_id"]:
            per_account[m["account"]][m["kind"]] += m["amount"]
    return {
        "movements": movements,
        "accounts": [{"title": t, **v, "net": v["in"] - v["out"]} for t, v in sorted(per_account.items())],
        "total_in": sum(m["amount"] for m in movements if m["kind"] == "in" and m["counts"]),
        "total_out": sum(m["amount"] for m in movements if m["kind"] == "out"),
        "cheques_received": sum(m["amount"] for m in movements if m["kind"] == "in" and not m["counts"]),
    }
