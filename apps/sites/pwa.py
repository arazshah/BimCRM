"""Shared mobile-app behaviour of the public agency sites: bottom bar, installable manifest, contact card."""

import json
from html import escape

from django.http import HttpResponse

SW_JS = """\
// Network-only except for an offline fallback page. Customer pages are never cached.
self.addEventListener("install", (e) => { e.waitUntil(caches.open("offline-v1").then((c) => c.add("/offline/"))); self.skipWaiting(); });
self.addEventListener("activate", (e) => { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(() => caches.match("/offline/")));
});
"""


def mbar_active(path: str) -> str:
    if path.startswith("/track"):
        return "track"
    if path.startswith("/claims"):
        return "claims"
    if path.startswith("/account"):
        return "account"
    if path == "/":
        return "home"
    return ""


def _whatsapp_href(number: str) -> str:
    digits = "".join(ch for ch in number if ch.isdigit())
    if digits.startswith("0"):
        digits = "98" + digits[1:]
    return f"https://wa.me/{digits}"


def mbar_items(site, can_portal: bool, has_claims: bool) -> list[dict]:
    """Five fixed slots: home, track, quote (centre, highlighted), then the two most useful of
    claims / account / call / chat for this agency. Never fewer than five, so the bar does not jump."""
    items = [
        {"key": "home", "label": "خانه", "href": "/", "icon": "home"},
        {"key": "track", "label": "پیگیری", "href": "/track/", "icon": "search"},
        {"key": "quote", "label": "استعلام", "href": "/#quote", "icon": "doc", "main": True},
    ]
    phone = getattr(site, "phone", "") or ""
    whatsapp = getattr(site, "whatsapp", "") or ""
    options = []
    if has_claims:
        options.append({"key": "claims", "label": "خسارت", "href": "/claims/", "icon": "shield"})
    if can_portal:
        options.append({"key": "account", "label": "حساب من", "href": "/account/", "icon": "user"})
    if phone:
        options.append({"key": "call", "label": "تماس", "href": f"tel:{phone}", "icon": "phone"})
    if whatsapp:
        options.append({"key": "chat", "label": "گفتگو", "href": _whatsapp_href(whatsapp), "icon": "chat"})
    options.append({"key": "guide", "label": "راهنما", "href": "/guide/claims/", "icon": "doc"})
    options.append({"key": "privacy", "label": "حریم خصوصی", "href": "/privacy/", "icon": "shield"})
    return items + options[:2]


def manifest(request, site):
    name = request.tenant.name
    icon = site.logo.url if site.logo else "/pwa-icon.svg"
    icons = [{"src": icon, "sizes": "any", "purpose": "any"}]
    body = {
        "name": name,
        "short_name": name[:12],
        "lang": "fa",
        "dir": "rtl",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": site.color,
        "icons": icons,
    }
    return HttpResponse(json.dumps(body, ensure_ascii=False), content_type="application/manifest+json")


def service_worker(request):
    response = HttpResponse(SW_JS, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


def icon_svg(request, site):
    letter = escape((request.tenant.name.strip() or "B")[0])
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
        f'<rect width="512" height="512" rx="112" fill="{site.color}"/>'
        f'<text x="256" y="340" text-anchor="middle" font-size="280" font-weight="800" fill="#fff" '
        f'font-family="sans-serif">{letter}</text></svg>'
    )
    return HttpResponse(svg, content_type="image/svg+xml")


def _vc(value: str) -> str:
    """Escape a vCard text value; it also drops line breaks so user text cannot inject extra properties."""
    value = " ".join(str(value).split())
    return value.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def vcard(request, site):
    """Lets a customer save the office in their contacts; only data the office already shows publicly."""
    name = _vc(request.tenant.name)
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{name}", f"ORG:{name}"]
    if site.phone:
        lines.append(f"TEL;TYPE=WORK,VOICE:{_vc(site.phone)}")
    if site.email:
        lines.append(f"EMAIL:{_vc(site.email)}")
    if site.address:
        lines.append(f"ADR;TYPE=WORK:;;{_vc(site.address)};;;;")
    lines.append(f"URL:{request.scheme}://{request.get_host()}/")
    lines.append("END:VCARD")
    response = HttpResponse("\r\n".join(lines) + "\r\n", content_type="text/vcard; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="office.vcf"'
    return response
