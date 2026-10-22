import json

import pytest

from apps.sites.pwa import mbar_active, mbar_items
from apps.sites.registry import TEMPLATES

from .conftest import host
from .test_agency_sites import publishable_site

pytestmark = pytest.mark.django_db


class FakeSite:
    def __init__(self, phone="", whatsapp=""):
        self.phone, self.whatsapp = phone, whatsapp


def keys(items):
    return [i["key"] for i in items]


def test_mobile_bar_always_has_five_slots_with_quote_in_the_middle():
    for kwargs in (
        dict(site=FakeSite(), can_portal=False, has_claims=False),
        dict(site=FakeSite("0211234"), can_portal=True, has_claims=True),
        dict(site=FakeSite("0211234", "09120000000"), can_portal=False, has_claims=False),
    ):
        items = mbar_items(**kwargs)
        assert len(items) == 5
        assert items[2]["key"] == "quote" and items[2]["main"]


def test_mobile_bar_prefers_claims_and_account_then_contact():
    assert keys(mbar_items(FakeSite("0211234"), True, True)) == ["home", "track", "quote", "claims", "account"]
    assert keys(mbar_items(FakeSite("0211234"), False, False))[3:] == ["call", "guide"]
    chat = mbar_items(FakeSite(whatsapp="09121112233"), False, False)[3]
    assert chat["key"] == "chat" and chat["href"] == "https://wa.me/989121112233"


def test_mobile_bar_active_section():
    assert mbar_active("/") == "home" and mbar_active("/track/") == "track"
    assert mbar_active("/claims/new/") == "claims" and mbar_active("/account/") == "account"
    assert mbar_active("/insurance/third-party/") == ""


@pytest.mark.parametrize("template", [t.key for t in TEMPLATES])
def test_every_template_renders_the_app_bar_and_installable_head(client, tenant, template):
    site = publishable_site(tenant)
    site.template = template
    site.save(update_fields=["template"])

    html = client.get("/", HTTP_HOST=host(tenant)).content.decode()

    assert html.count('class="s-mbar"') == 1
    assert "data-open-quote" in html and 'aria-current="page"' in html
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert 'name="theme-color"' in html
    assert 'data-qf-step="1"' in html and 'data-qf-step="3"' in html
    assert "js/site-app.js" in html


def test_manifest_uses_the_agency_brand(client, tenant):
    site = publishable_site(tenant)
    site.primary_color = "#a3214f"
    site.save(update_fields=["primary_color"])

    response = client.get("/manifest.webmanifest", HTTP_HOST=host(tenant))
    data = json.loads(response.content)

    assert response["Content-Type"].startswith("application/manifest+json")
    assert data["name"] == tenant.name and data["dir"] == "rtl" and data["display"] == "standalone"
    assert data["theme_color"] == site.color and data["icons"][0]["src"] == "/pwa-icon.svg"


def test_service_worker_never_caches_customer_pages(client, tenant):
    response = client.get("/sw.js", HTTP_HOST=host(tenant))
    body = response.content.decode()

    assert response["Content-Type"].startswith("application/javascript")
    assert response["Service-Worker-Allowed"] == "/"
    assert '"/offline/"' in body and "cache.put" not in body and "cache.addAll" not in body


def test_pwa_icon_and_offline_page(client, tenant):
    publishable_site(tenant)
    icon = client.get("/pwa-icon.svg", HTTP_HOST=host(tenant))
    offline = client.get("/offline/", HTTP_HOST=host(tenant))

    assert icon["Content-Type"] == "image/svg+xml" and b"<svg" in icon.content
    assert offline.status_code == 200 and "اتصال اینترنت قطع است" in offline.content.decode()


def test_vcard_contains_only_public_office_details_and_cannot_be_injected(client, tenant):
    site = publishable_site(tenant)
    site.address = "تهران\r\nTEL:0900-injected; پلاک ۱"
    site.save(update_fields=["address"])

    response = client.get("/contact.vcf", HTTP_HOST=host(tenant))
    lines = response.content.decode().splitlines()

    assert response["Content-Type"].startswith("text/vcard")
    assert "TEL;TYPE=WORK,VOICE:02112345678" in lines
    assert not any(line.startswith("TEL:0900") for line in lines)
    assert lines[0] == "BEGIN:VCARD" and lines[-1] == "END:VCARD"
