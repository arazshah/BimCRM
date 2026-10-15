import pytest

from apps.core.models import InsuranceCompany
from apps.main import guides

from .conftest import MAIN


def test_every_guide_renders(client, db):
    assert client.get("/guides/", HTTP_HOST=MAIN).status_code == 200
    for g in guides.GUIDES:
        resp = client.get(f"/guides/{g.slug}/", HTTP_HOST=MAIN)
        assert resp.status_code == 200 and g.title in resp.content.decode()
    assert client.get("/guides/nope/", HTTP_HOST=MAIN).status_code == 404


def test_company_pages_and_hub(client, db):
    c = InsuranceCompany.objects.get(slug="iran")
    resp = client.get("/bime/iran/", HTTP_HOST=MAIN)
    assert resp.status_code == 200 and c.name in resp.content.decode()
    assert "وابسته به هیچ شرکت" in resp.content.decode()
    assert c.name in client.get("/bime/", HTTP_HOST=MAIN).content.decode()
    assert client.get("/bime/zzz/", HTTP_HOST=MAIN).status_code == 404


def test_inactive_company_page_is_404(client, db):
    InsuranceCompany.objects.filter(slug="iran").update(is_active=False)
    assert client.get("/bime/iran/", HTTP_HOST=MAIN).status_code == 404


def test_company_logo_chip_links_out_only_with_website(client, db):
    InsuranceCompany.objects.filter(name="بیمه سامان").update(website="https://example.com")
    html = client.get("/", HTTP_HOST=MAIN).content.decode()
    assert 'href="https://example.com"' in html and "nofollow" in html


@pytest.mark.parametrize("path", ["/guides/renewal-checklist/", "/bime/saman/"])
def test_in_sitemap(client, db, path):
    assert path in client.get("/sitemap.xml", HTTP_HOST=MAIN).content.decode()
