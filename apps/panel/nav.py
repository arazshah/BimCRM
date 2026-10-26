"""Panel navigation, built once per request.

The sidebar is grouped by what an agent is doing (selling, following up, money, claims, marketing, site, settings),
not by which package a feature belongs to. The same data feeds the "new" menu, the command palette and the
in-page tabs of the merged "site" and "office settings" sections, so a link is defined in exactly one place.
"""

from django.urls import reverse

FINANCE_PREFIXES = (
    "finance",
    "installment",
    "cheque",
    "receipt",
    "payment",
    "debtors",
    "daily_cash",
    "commission",
    "ledger",
)


def _url(name: str, *args) -> str:
    return reverse(f"panel:{name}", args=args)


def _counts(request) -> dict:
    """Small badges for the menu: new website requests and unread customer claims."""
    from apps.claims.models import Claim
    from apps.crm.models import QuoteRequest

    from .access import scoped

    quotes = scoped(request, QuoteRequest.objects.all(), include_unassigned=True).filter(status="new").count()
    claims = 0
    if "claims" in request.features and request.can.get("claims"):
        claims = scoped(request, Claim.objects.all(), "policy__branch").filter(office_unread=True).count()
    return {"quotes": quotes, "claims": claims}


def build_nav(request) -> dict:
    u = (request.resolver_match.url_name if request.resolver_match else "") or ""
    feats, can = request.features, request.can
    staff = request.membership.role == "staff"
    limited = request.branch_scope is not None
    counts = _counts(request)

    def entry(label, name, icon, active, *, badge=0, feature=None, hot=False):
        locked = feature is not None and feature not in feats
        return {
            "label": label,
            "url": _url(name),
            "icon": icon,
            "active": bool(active),
            "badge": badge or 0,
            "hot": hot,
            "locked": locked,
            "plan": request.plan_for.get(feature, "") if locked else "",
        }

    def group(key, label, icon, children):
        children = [c for c in children if c]
        if not children:
            return None
        active = any(c["active"] for c in children)
        return {
            "key": key,
            "label": label,
            "icon": icon,
            "children": children,
            "active": active,
            "badge": sum(c["badge"] for c in children),
        }

    sales = group(
        "sales",
        "فروش و مشتریان",
        "p-users",
        [
            entry(
                "مشتریان",
                "customers",
                "p-users",
                u.startswith("customer"),
            ),
            entry("درخواست‌های سایت", "quotes", "p-inbox", u in ("quotes", "quote"), badge=counts["quotes"]),
            entry("بیمه‌نامه‌ها و تمدید", "policies", "p-doc", "polic" in u),
            entry("باشگاه مشتریان", "segments", "p-star", u in ("segments", "segment_tasks", "club"))
            if can.get("segments")
            else None,
        ],
    )
    follow = group(
        "follow",
        "پیگیری",
        "p-tasks",
        [
            entry("کارها و پیگیری‌ها", "tasks", "p-tasks", "task" in u, badge=getattr(request, "due_tasks", 0)),
            entry("تقویم", "calendar", "p-calendar", u == "calendar"),
            entry("یادآورهای پیامکی", "reminders", "p-bell", u == "reminders") if can.get("reminders") else None,
        ],
    )
    items = [{"single": True, "key": "home", **entry("خانه", "dashboard", "p-home", u == "dashboard")}]
    if sales:
        items.append(sales)
    if follow:
        items.append(follow)
    if can.get("finance") or can.get("books"):
        target = "installments" if (limited or not can.get("books")) else "finance"
        items.append(
            {
                "single": True,
                "key": "finance",
                **entry("مالی و حسابداری", target, "p-wallet", u.startswith(FINANCE_PREFIXES), feature="finance"),
            }
        )
    if can.get("claims"):
        items.append(
            {
                "single": True,
                "key": "claims",
                **entry(
                    "خسارت",
                    "claims",
                    "p-shield",
                    u.startswith("claim"),
                    badge=counts["claims"],
                    feature="claims",
                    hot=True,
                ),
            }
        )
    if not limited:
        marketing = group(
            "marketing",
            "بازاریابی و گزارش",
            "p-chart",
            [
                entry("کمپین پیامکی", "campaigns", "p-megaphone", "campaign" in u, feature="sms_campaigns")
                if can.get("campaigns")
                else None,
                entry("بازاریابان", "marketers", "p-network", "marketer" in u, feature="marketers")
                if can.get("marketers")
                else None,
                entry("گزارش‌ها", "reports", "p-chart", "report" in u, feature="advanced_reports")
                if can.get("reports")
                else None,
            ],
        )
        if marketing:
            items.append(marketing)

    site_tabs = []
    if can.get("site"):
        site_tabs += [
            entry("محتوا و اطلاعات", "site", "p-globe", u == "site"),
            entry("صفحهٔ رشته‌ها", "site_lines", "p-shield", u in ("site_lines", "site_line")),
            entry("قالب", "site_template", "p-palette", u == "site_template"),
        ]
    if not staff:
        site_tabs.append(entry("دامنه", "domains", "p-link", u.startswith("domain")))
    if site_tabs:
        items.append(
            {
                "single": True,
                "key": "site",
                **{
                    **site_tabs[0],
                    "label": "سایت من",
                    "icon": "p-globe",
                    "active": any(t["active"] for t in site_tabs),
                },
            }
        )

    office_tabs = []
    if not staff:
        office_tabs += [
            entry("همکاران", "team", "p-team", u.startswith("team")),
            entry("شعبه‌ها", "branches", "p-building", "branch" in u, feature="branches"),
            entry("اتصالات", "integrations", "p-plug", "integration" in u),
        ]
    office_tabs.append(entry("اشتراک", "billing", "p-card", u.startswith("billing")))
    billing = office_tabs[-1]
    settings_link = (
        {
            **office_tabs[0],
            "label": "تنظیمات دفتر",
            "icon": "p-gear",
            "active": any(t["active"] for t in office_tabs[:-1]),
        }
        if not staff
        else None
    )

    new_menu = [
        {"label": "بیمه‌نامه", "url": _url("policy_new"), "icon": "p-doc", "tone": "green"},
        {"label": "مشتری", "url": _url("customer_new"), "icon": "p-users", "tone": "blue"},
        {"label": "کار و پیگیری", "url": _url("task_new"), "icon": "p-tasks", "tone": "violet"},
    ]
    if "finance" in feats and can.get("finance"):
        new_menu += [
            {"label": "رسید دریافت", "url": _url("receipt_new"), "icon": "p-receipt", "tone": "green"},
            {"label": "چک دریافتی", "url": _url("cheque_new"), "icon": "p-cheque", "tone": "amber"},
        ]
    if "claims" in feats and can.get("claims"):
        new_menu.append({"label": "اعلام خسارت", "url": _url("claim_new"), "icon": "p-shield", "tone": "red"})

    # Everything the palette can jump to, flattened.
    pages = []
    for it in items:
        if it.get("single"):
            pages.append((it["label"], it["url"], "صفحه"))
        else:
            pages += [(c["label"], c["url"], it["label"]) for c in it["children"]]
    pages += [(f"سایت من › {t['label']}", t["url"], "سایت") for t in site_tabs]
    pages += [(f"تنظیمات دفتر › {t['label']}", t["url"], "تنظیمات") for t in office_tabs]
    pages.append(("پشتیبانی", _url("tickets"), "راهنما"))
    palette = [{"label": label, "url": url, "hint": hint, "kind": "page"} for label, url, hint in pages]
    palette += [
        {"label": f"ثبت {n['label']} جدید", "url": n["url"], "hint": "دستور", "kind": "command"} for n in new_menu
    ]
    palette.append({"label": "ورود اطلاعات از اکسل", "url": _url("data_import"), "hint": "دستور", "kind": "command"})

    return {
        "items": items,
        "settings": settings_link,
        "billing": billing,
        "site_tabs": site_tabs if len(site_tabs) > 1 else [],
        "office_tabs": office_tabs if len(office_tabs) > 1 else [],
        "new": new_menu,
        "palette": palette,
        "search_url": _url("search"),
    }
