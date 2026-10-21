import pytest
from django.db import IntegrityError, transaction

from apps.core.models import InsuranceCompany, LineOfBusiness
from apps.core.tenancy import tenant_context
from apps.crm.models import QuoteRequest
from apps.sites.models import SiteLineContent, SiteSettings

from .conftest import host

pytestmark = pytest.mark.django_db


def publishable_site(tenant):
    site = SiteSettings.all_objects.get(tenant=tenant)
    site.is_published = True
    site.hero_title = tenant.name
    site.phone = "02112345678"
    site.hero_subtitle = "کارشناس دفتر درخواست شما را بررسی می‌کند."
    site.save()
    site.lines.set(LineOfBusiness.objects.filter(slug="third-party"))
    return site


def test_line_content_is_tenant_scoped_and_unique(tenant, other_tenant):
    line = LineOfBusiness.objects.get(slug="third-party")
    with tenant_context(tenant):
        content = SiteLineContent.objects.create(line=line, intro="توضیح دفتر اول")
    with tenant_context(other_tenant):
        assert not SiteLineContent.objects.filter(line=line).exists()
        SiteLineContent.objects.create(line=line, intro="توضیح دفتر دوم")
    with tenant_context(tenant):
        content.refresh_from_db()
        assert content.intro == "توضیح دفتر اول"
        with pytest.raises(IntegrityError), transaction.atomic():
            SiteLineContent.objects.create(line=line, intro="تکراری")


def test_line_detail_uses_only_this_agencys_content(client, tenant, other_tenant):
    publishable_site(tenant)
    line = LineOfBusiness.objects.get(slug="third-party")
    with tenant_context(tenant):
        SiteLineContent.objects.create(line=line, intro="پاسخ اختصاصی دفتر البرز")
    with tenant_context(other_tenant):
        SiteLineContent.objects.create(line=line, intro="متن محرمانه دفتر دیگر")

    response = client.get("/insurance/third-party/", HTTP_HOST=host(tenant))
    html = response.content.decode()
    assert response.status_code == 200
    assert "پاسخ اختصاصی دفتر البرز" in html
    assert "متن محرمانه دفتر دیگر" not in html
    assert 'name="line"' in html and 'value="third-party"' in html


def test_line_detail_rejects_unavailable_line(client, tenant):
    publishable_site(tenant)
    assert client.get("/insurance/life/", HTTP_HOST=host(tenant)).status_code == 404
    assert client.get("/insurance/not-a-line/", HTTP_HOST=host(tenant)).status_code == 404


@pytest.mark.parametrize("template", ["modern", "etemad", "khanevadeh", "khodro", "chandsherkati"])
def test_line_detail_renders_in_every_existing_template(client, tenant, template):
    site = publishable_site(tenant)
    site.template = template
    site.save(update_fields=["template"])
    response = client.get("/insurance/third-party/", HTTP_HOST=host(tenant))
    html = response.content.decode()
    assert response.status_code == 200
    assert "شخص ثالث" in html and 'rel="canonical"' in html
    assert "<title>شخص ثالث | نمایندگی البرز ۱۲۳۴</title>" in html


@pytest.mark.parametrize("template", ["modern", "etemad", "khanevadeh", "khodro", "chandsherkati"])
def test_homepage_navigation_does_not_point_to_missing_optional_sections(client, tenant, template):
    site = publishable_site(tenant)
    site.template = template
    site.about = ""
    site.save(update_fields=["template", "about"])

    html = client.get("/", HTTP_HOST=host(tenant)).content.decode()

    assert 'href="/#faq"' not in html
    assert 'href="/#about"' not in html


def test_homepage_keeps_company_name_visible_when_logo_is_empty(client, tenant):
    site = publishable_site(tenant)
    company = InsuranceCompany.objects.create(name="شرکت نمونهٔ همکار")
    site.companies.set([company])

    html = client.get("/", HTTP_HOST=host(tenant)).content.decode()

    assert "شرکت نمونهٔ همکار" in html
    assert 'src=""' not in html


def test_footer_hides_empty_contact_column(client, tenant):
    site = publishable_site(tenant)
    site.phone = ""
    site.address = ""
    site.working_hours = ""
    site.email = ""
    site.save(update_fields=["phone", "address", "working_hours", "email"])

    html = client.get("/", HTTP_HOST=host(tenant)).content.decode()

    assert 'class="s-footer-contact"' not in html


def test_quote_post_redirects_and_refresh_does_not_duplicate(client, tenant, monkeypatch):
    publishable_site(tenant)
    monkeypatch.setattr("apps.work.services.on_new_quote", lambda quote: None)
    response = client.post(
        "/quote/",
        {"line": "third-party", "full_name": "سارا", "mobile": "09127778888"},
        HTTP_HOST=host(tenant),
    )
    assert response.status_code == 302
    assert response["Location"] == "/quote/done/"
    assert QuoteRequest.all_objects.filter(tenant=tenant).count() == 1
    response = client.get(response["Location"], HTTP_HOST=host(tenant))
    assert response.status_code == 200 and "درخواستتان ثبت شد" in response.content.decode()
    client.get(response.wsgi_request.path, HTTP_HOST=host(tenant))
    assert QuoteRequest.all_objects.filter(tenant=tenant).count() == 1


def test_quote_post_rejects_inactive_line(client, tenant, monkeypatch):
    publishable_site(tenant)
    monkeypatch.setattr("apps.work.services.on_new_quote", lambda quote: None)
    line = LineOfBusiness.objects.get(slug="third-party")
    line.is_active = False
    line.save(update_fields=["is_active"])

    response = client.post(
        "/quote/",
        {"line": "third-party", "full_name": "سارا", "mobile": "09127778888"},
        HTTP_HOST=host(tenant),
    )

    assert response.status_code == 400
    assert "فعال نیست" in response.content.decode()
    assert QuoteRequest.all_objects.filter(tenant=tenant).count() == 0


def test_quote_completion_expires_after_short_session_ttl(client, tenant, monkeypatch):
    import apps.sites.views as site_views

    publishable_site(tenant)
    monkeypatch.setattr("apps.work.services.on_new_quote", lambda quote: None)
    monkeypatch.setattr(site_views.time, "time", lambda: 1_000)
    response = client.post(
        "/quote/",
        {"line": "third-party", "full_name": "سارا", "mobile": "09127778888"},
        HTTP_HOST=host(tenant),
    )
    assert response.status_code == 302
    assert client.session[site_views.SITE_CREATED_QUOTE]["expires"] == 1_000 + site_views.SESSION_QUOTE_TTL

    monkeypatch.setattr(site_views.time, "time", lambda: 1_000 + site_views.SESSION_QUOTE_TTL + 1)
    result = client.get("/quote/done/", HTTP_HOST=host(tenant))

    assert result.status_code == 302
    assert site_views.SITE_CREATED_QUOTE not in client.session


def test_quote_validates_required_typed_custom_fields(client, tenant):
    publishable_site(tenant)
    line = LineOfBusiness.objects.get(slug="third-party")
    line.form_fields = [
        {"name": "email", "label": "ایمیل", "type": "email", "required": True},
        {"name": "vehicle", "label": "نوع خودرو", "type": "select", "options": ["سواری", "وانت"]},
    ]
    line.save(update_fields=["form_fields"])
    response = client.post(
        "/quote/",
        {"line": line.slug, "full_name": "سارا", "mobile": "09127778888", "f_email": "bad"},
        HTTP_HOST=host(tenant),
    )
    html = response.content.decode()
    assert response.status_code == 400
    assert "ایمیل" in html and 'type="email"' in html and "required" in html
    assert QuoteRequest.all_objects.filter(tenant=tenant).count() == 0

    response = client.post(
        "/quote/",
        {
            "line": line.slug,
            "full_name": "سارا",
            "mobile": "09127778888",
            "f_email": "sara@example.com",
            "f_vehicle": "تانک",
        },
        HTTP_HOST=host(tenant),
    )
    assert response.status_code == 400
    assert "گزینه‌های نمایش‌داده‌شده" in response.content.decode()
    assert QuoteRequest.all_objects.filter(tenant=tenant).count() == 0


def test_tracking_requires_post_and_never_puts_personal_data_in_url(client, tenant):
    publishable_site(tenant)
    quote = QuoteRequest.all_objects.create(
        tenant=tenant,
        line=LineOfBusiness.objects.get(slug="third-party"),
        full_name="سارا",
        mobile="09127778888",
    )
    get_response = client.get(f"/track/?code={quote.tracking_code}&mobile={quote.mobile}", HTTP_HOST=host(tenant))
    assert get_response.status_code == 302
    assert get_response["Location"] == "/track/"
    post_response = client.post(
        "/track/",
        {
            "code": quote.tracking_code.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")),
            "mobile": quote.mobile,
        },
        HTTP_HOST=host(tenant),
    )
    assert post_response.status_code == 302
    assert post_response["Location"] == "/track/"
    payload = client.session["site_tracked_quote"]
    assert payload["id"] == quote.pk
    assert payload["expires"] > 0
    result = client.get(post_response["Location"], HTTP_HOST=host(tenant))
    html = result.content.decode()
    assert quote.get_status_display() in html
    assert quote.mobile not in html
    assert 'name="robots" content="noindex,follow"' in html


def test_tracking_result_expires_after_short_session_ttl(client, tenant, monkeypatch):
    import apps.sites.views as site_views

    publishable_site(tenant)
    quote = QuoteRequest.all_objects.create(
        tenant=tenant,
        line=LineOfBusiness.objects.get(slug="third-party"),
        full_name="سارا",
        mobile="09127778888",
    )
    monkeypatch.setattr(site_views.time, "time", lambda: 1_000)
    response = client.post("/track/", {"code": quote.tracking_code, "mobile": quote.mobile}, HTTP_HOST=host(tenant))
    assert response.status_code == 302
    assert client.session[site_views.SITE_TRACKED_QUOTE]["expires"] == 1_000 + site_views.SESSION_QUOTE_TTL

    monkeypatch.setattr(site_views.time, "time", lambda: 1_000 + site_views.SESSION_QUOTE_TTL + 1)
    result = client.get("/track/", HTTP_HOST=host(tenant))

    assert result.status_code == 200
    assert "— ثبت" not in result.content.decode()
    assert site_views.SITE_TRACKED_QUOTE not in client.session


def test_invalid_tracking_attempt_clears_previous_unconsumed_result(client, tenant):
    publishable_site(tenant)
    quote = QuoteRequest.all_objects.create(
        tenant=tenant,
        line=LineOfBusiness.objects.get(slug="third-party"),
        full_name="سارا",
        mobile="09127778888",
    )
    client.post("/track/", {"code": quote.tracking_code, "mobile": quote.mobile}, HTTP_HOST=host(tenant))

    failed = client.post("/track/", {"code": "00000000", "mobile": quote.mobile}, HTTP_HOST=host(tenant))
    assert failed.status_code == 302
    result = client.get("/track/", HTTP_HOST=host(tenant))

    assert "— ثبت" not in result.content.decode()
    assert "site_tracked_quote" not in client.session


def test_unpublished_site_cannot_be_published_without_readiness(client, tenant, owner):
    site = SiteSettings.all_objects.get(tenant=tenant)
    client.force_login(owner)
    response = client.post("/panel/site/publish/", {"publish": "1"}, HTTP_HOST=host(tenant))
    site.refresh_from_db()
    assert response.status_code == 302
    assert not site.is_published
    page = client.get("/panel/site/", HTTP_HOST=host(tenant)).content.decode()
    assert "انتشار سایت نیاز به تکمیل دارد" in page


def test_ready_site_can_be_published(client, tenant, owner):
    site = publishable_site(tenant)
    client.force_login(owner)
    response = client.post("/panel/site/publish/", {"publish": "1"}, HTTP_HOST=host(tenant))
    site.refresh_from_db()
    assert response.status_code == 302
    assert site.is_published


def test_line_pages_have_their_own_panel_section(client, tenant, owner):
    site = SiteSettings.all_objects.get(tenant=tenant)
    line = LineOfBusiness.objects.get(slug="third-party")
    site.lines.set([line])
    client.force_login(owner)
    site_page = client.get("/panel/site/", HTTP_HOST=host(tenant))
    assert site_page.status_code == 200
    assert "line-content-editor" not in site_page.content.decode()
    hub = client.get("/panel/site/lines/", HTTP_HOST=host(tenant))
    assert hub.status_code == 200 and "شخص ثالث" in hub.content.decode()
    assert client.get("/panel/site/lines/third-party/", HTTP_HOST=host(tenant)).status_code == 200
    assert client.get("/panel/site/lines/life/", HTTP_HOST=host(tenant)).status_code == 404


def _png(name="a.png", size=(40, 30)):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (20, 120, 110)).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def _line_post(**extra):
    post = {
        "c-intro": "توضیح ویژهٔ ثالث",
        "c-cover_alt": "تصویر ثالث",
        "c-highlights": "پاسخ در همان روز\nبررسی رایگان",
        "c-description": "توضیح کامل رشته",
        "c-coverage": "بررسی پوشش‌ها",
        "c-considerations": "موارد قابل بررسی",
        "c-documents": "مدارک لازم را دفتر اعلام می‌کند",
        "c-process": "درخواست و سپس بررسی کارشناس",
        "c-seo_title": "",
        "c-seo_description": "",
        "g-TOTAL_FORMS": "1",
        "g-INITIAL_FORMS": "0",
        "g-MIN_NUM_FORMS": "0",
        "g-MAX_NUM_FORMS": "8",
        "g-0-caption": "کارت بیمه",
        "g-0-order": "1",
    }
    post.update(extra)
    return post


def test_line_page_editor_saves_text_cover_and_gallery(client, tenant, owner, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    site = SiteSettings.all_objects.get(tenant=tenant)
    line = LineOfBusiness.objects.get(slug="third-party")
    site.lines.set([line])
    client.force_login(owner)
    post = _line_post(**{"c-cover": _png("cover.png"), "g-0-image": _png("g.png")})
    response = client.post("/panel/site/lines/third-party/", post, HTTP_HOST=host(tenant))
    assert response.status_code == 302, response.context["form"].errors
    with tenant_context(tenant):
        content = SiteLineContent.objects.get(line=line)
        assert content.intro == "توضیح ویژهٔ ثالث" and content.considerations == "موارد قابل بررسی"
        assert content.cover and content.highlight_list == ["پاسخ در همان روز", "بررسی رایگان"]
        assert content.images.count() == 1 and content.images.first().caption == "کارت بیمه"
    again = client.post(
        "/panel/site/lines/third-party/",
        _line_post(**{"c-remove_cover": "on", "g-TOTAL_FORMS": "0"}),
        HTTP_HOST=host(tenant),
    )
    assert again.status_code == 302
    with tenant_context(tenant):
        assert not SiteLineContent.objects.get(line=line).cover


def test_line_page_shows_cover_gallery_and_quote_form_beside_content(client, tenant, owner, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    publishable_site(tenant)
    client.force_login(owner)
    post = _line_post(**{"c-cover": _png("cover.png"), "g-0-image": _png("g.png")})
    assert client.post("/panel/site/lines/third-party/", post, HTTP_HOST=host(tenant)).status_code == 302
    html = client.get("/insurance/third-party/", HTTP_HOST=host(tenant)).content.decode()
    assert "line-cover" in html and "line-gallery" in html and "پاسخ در همان روز" in html
    hero = html.split('<section class="line-body">')[0]
    assert 'id="quote-form"' not in hero  # the inquiry form lives beside the content, not in the hero
    assert html.count('id="quote-form"') == 1
    cover_url = SiteLineContent.all_objects.get(tenant=tenant).cover.url
    assert client.get(cover_url, HTTP_HOST=host(tenant)).status_code == 200  # uploaded pictures are public


def test_line_page_without_images_still_has_a_visual_not_an_empty_hero(client, tenant):
    publishable_site(tenant)
    html = client.get("/insurance/third-party/", HTTP_HOST=host(tenant)).content.decode()
    assert "line-path" in html and "line-gallery" not in html


def test_line_page_rejects_oversized_image(client, tenant, owner, settings, tmp_path):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = str(tmp_path)
    site = SiteSettings.all_objects.get(tenant=tenant)
    site.lines.set(LineOfBusiness.objects.filter(slug="third-party"))
    client.force_login(owner)
    big = SimpleUploadedFile("big.png", b"\x89PNG" + b"0" * (3 * 1024 * 1024 + 10), content_type="image/png")
    response = client.post("/panel/site/lines/third-party/", _line_post(**{"c-cover": big}), HTTP_HOST=host(tenant))
    assert response.status_code == 200
    assert not SiteLineContent.all_objects.filter(tenant=tenant).exists()


def test_sitemap_excludes_private_workflows_and_includes_enabled_line(client, tenant):
    publishable_site(tenant)
    response = client.get("/sitemap.xml", HTTP_HOST=host(tenant))
    xml = response.content.decode()
    assert "/insurance/third-party/" in xml
    assert "/track/" not in xml and "/account/" not in xml
