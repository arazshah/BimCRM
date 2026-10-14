import pytest
from django.test import override_settings

from apps.main.help import ORDER
from apps.tickets.models import Ticket

from .conftest import MAIN, host


@pytest.mark.django_db
def test_help_index_lists_every_article(client):
    resp = client.get("/help/", HTTP_HOST=MAIN)
    assert resp.status_code == 200
    html = resp.content.decode()
    for a in ORDER:
        assert f"/help/{a.slug}/" in html


@pytest.mark.django_db
@pytest.mark.parametrize("slug", [a.slug for a in ORDER])
def test_every_help_article_renders(client, slug):
    resp = client.get(f"/help/{slug}/", HTTP_HOST=MAIN)
    assert resp.status_code == 200
    assert "hbody" in resp.content.decode()


@pytest.mark.django_db
def test_unknown_help_article_is_404_and_sitemap_lists_help(client):
    assert client.get("/help/nope/", HTTP_HOST=MAIN).status_code == 404
    sm = client.get("/sitemap.xml", HTTP_HOST=MAIN).content.decode()
    assert "/help/" in sm and "/help/sms/" in sm


@pytest.mark.django_db
def test_sms_help_and_integrations_show_signup_link(client, tenant, owner):
    assert "sign-up?ref=HXQGN" in client.get("/help/sms/", HTTP_HOST=MAIN).content.decode()
    client.force_login(owner)
    resp = client.get("/panel/integrations/", HTTP_HOST=host(tenant))
    assert resp.status_code == 200
    assert "sign-up?ref=HXQGN" in resp.content.decode()


@pytest.mark.django_db
@override_settings(SUPERADMIN_MOBILE="09100000000")
def test_domain_service_opens_ticket_and_notifies_owner(client, tenant, owner, monkeypatch):
    sent = []
    monkeypatch.setattr("apps.accounts.sms.send_platform_text", lambda m, t: sent.append((m, t)))
    client.force_login(owner)
    page = client.get("/panel/domains/", HTTP_HOST=host(tenant)).content.decode()
    assert "ما برایتان می‌خریم" in page
    resp = client.post(
        "/panel/domains/service/",
        {"wanted": "alborzbime.ir", "contact_mobile": "09121234567", "note": ""},
        HTTP_HOST=host(tenant),
    )
    assert resp.status_code == 302
    t = Ticket.all_objects.get(tenant=tenant)
    assert t.category == Ticket.Category.DOMAIN and "alborzbime.ir" in t.subject
    assert sent and sent[0][0] == "09100000000"
    page = client.get("/panel/domains/", HTTP_HOST=host(tenant)).content.decode()
    assert "پیگیری درخواست" in page


@pytest.mark.django_db
def test_domain_service_rejects_bad_mobile(client, tenant, owner):
    client.force_login(owner)
    client.post("/panel/domains/service/", {"contact_mobile": "123"}, HTTP_HOST=host(tenant))
    assert not Ticket.all_objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("picked, stored", [("#000000", ""), ("", ""), ("#c0392b", "#c0392b")])
def test_saving_site_content_keeps_template_colour_unless_changed(client, tenant, owner, picked, stored):
    from apps.sites.models import SiteSettings

    client.force_login(owner)
    page = client.get("/panel/site/", HTTP_HOST=host(tenant)).content.decode()
    site = SiteSettings.all_objects.get(tenant=tenant)
    assert f'value="{site.template_info.default_color}"' in page
    data = {
        "s-hero_title": "دفتر من",
        "s-primary_color": picked,
        "t-TOTAL_FORMS": "0",
        "t-INITIAL_FORMS": "0",
        "q-TOTAL_FORMS": "0",
        "q-INITIAL_FORMS": "0",
    }
    resp = client.post("/panel/site/", data, HTTP_HOST=host(tenant))
    assert resp.status_code == 302, resp.content.decode()[:500]
    site.refresh_from_db()
    assert site.hero_title == "دفتر من" and site.primary_color == stored


@pytest.mark.django_db
def test_video_pages_and_embeds(client):
    from pathlib import Path

    from django.conf import settings

    from apps.main.help import PROMO, VIDEOS

    for v in [PROMO, *VIDEOS]:
        for rel in (v.src, v.poster):
            assert (Path(settings.BASE_DIR) / "static" / rel).is_file(), rel
    page = client.get("/help/videos/", HTTP_HOST=MAIN).content.decode()
    assert page.count("<video") == len(VIDEOS) and '"@type":"VideoObject"' in page
    assert "help-02-sms.mp4" in client.get("/help/sms/", HTTP_HOST=MAIN).content.decode()
    assert "<video" not in client.get("/help/faq/", HTTP_HOST=MAIN).content.decode()
    assert "help-15-team.mp4" in client.get("/help/team/", HTTP_HOST=MAIN).content.decode()
    assert "/help/videos/" in client.get("/help/", HTTP_HOST=MAIN).content.decode()
    landing = client.get("/", HTTP_HOST=MAIN).content.decode()
    assert "video/promo.mp4" in landing and "data-play" in landing
    assert "/help/videos/" in client.get("/sitemap.xml", HTTP_HOST=MAIN).content.decode()


@pytest.mark.django_db
def test_free_domain_promo_shows_until_its_date(client, tenant, owner, monkeypatch):
    import datetime

    from django.utils import timezone

    from apps.core.models import PlatformSettings

    ps = PlatformSettings.load()
    ps.free_domain_until = timezone.localdate() + datetime.timedelta(days=10)
    ps.save()
    landing = client.get("/", HTTP_HOST=MAIN).content.decode()
    assert "promo-ribbon" in landing and "dc-free" in landing
    assert "رایگان" in client.get("/help/domain/", HTTP_HOST=MAIN).content.decode()
    client.force_login(owner)
    assert "طرح ویژه" in client.get("/panel/", HTTP_HOST=host(tenant)).content.decode()
    assert "concierge-offer" in client.get("/panel/domains/", HTTP_HOST=host(tenant)).content.decode()
    monkeypatch.setattr("apps.accounts.sms.send_platform_text", lambda m, t: None)
    client.post("/panel/domains/service/", {"wanted": "x.ir", "contact_mobile": "09121234567"}, HTTP_HOST=host(tenant))
    assert Ticket.all_objects.get(tenant=tenant).subject.startswith("درخواست خرید دامنه (طرح رایگان)")

    ps.free_domain_until = timezone.localdate() - datetime.timedelta(days=1)
    ps.save()
    assert "promo-ribbon" not in client.get("/", HTTP_HOST=MAIN).content.decode()
    assert "طرح ویژه" not in client.get("/panel/", HTTP_HOST=host(tenant)).content.decode()
