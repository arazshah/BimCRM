from unittest.mock import patch

from apps.core import pdns
from apps.core.dns import check_domain
from apps.core.models import Domain


def test_ensure_zone_noop_without_config(settings):
    settings.PDNS_API_URL = ""
    assert pdns.ensure_zone("alborz8351.ir", ["ns1.bimcrm.ir", "ns2.bimcrm.ir"]) is False


def test_ensure_zone_creates_then_patches(settings):
    settings.PDNS_API_URL = "http://pdns:8081"
    settings.PDNS_API_KEY = "k"
    settings.SERVER_PUBLIC_IP = "1.2.3.4"
    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code = code
            self.text = ""

    def fake_post(url, json, headers, timeout):
        calls.append(("post", url, json))
        return Resp(201)

    def fake_patch(url, json, headers, timeout):
        calls.append(("patch", url, json))
        return Resp(204)

    with patch("apps.core.pdns.requests.post", side_effect=fake_post):
        with patch("apps.core.pdns.requests.patch", side_effect=fake_patch):
            assert pdns.ensure_zone("alborz8351.ir", ["ns1.bimcrm.ir", "ns2.bimcrm.ir"]) is True
    assert calls[0][0] == "post" and calls[0][2]["name"] == "alborz8351.ir."
    assert calls[1][0] == "patch"
    records = calls[1][2]["rrsets"]
    assert records[0]["records"][0]["content"] == "1.2.3.4"
    assert records[0]["name"] == "alborz8351.ir."
    assert records[1]["name"] == "www.alborz8351.ir."


def test_check_domain_retries_zone_creation_while_nameservers_match(tenant, settings):
    settings.PDNS_API_URL = "http://pdns:8081"
    domain = Domain.objects.create(tenant=tenant, hostname="alborz8351.ir")
    calls = []
    with patch("apps.core.pdns.ensure_zone", side_effect=lambda *a: calls.append(a) or True):
        check_domain(domain, resolver=lambda h: ["ns1.bimcrm.ir", "ns2.bimcrm.ir"])
        assert len(calls) == 1
        domain.refresh_from_db()
        assert domain.status == Domain.Status.ACTIVE
        # Active domains must retry zone setup, since the first API attempt may have failed.
        check_domain(domain, resolver=lambda h: ["ns1.bimcrm.ir", "ns2.bimcrm.ir"])
        assert len(calls) == 2


def test_check_domain_retries_failed_zone_creation(tenant):
    domain = Domain.objects.create(tenant=tenant, hostname="alborz8351.ir")
    attempts = iter([False, True])
    with patch("apps.core.pdns.ensure_zone", side_effect=lambda *a: next(attempts)):
        assert check_domain(domain, resolver=lambda h: ["ns1.bimcrm.ir", "ns2.bimcrm.ir"])
        assert check_domain(domain, resolver=lambda h: ["ns1.bimcrm.ir", "ns2.bimcrm.ir"])

    domain.refresh_from_db()
    assert domain.status == Domain.Status.ACTIVE
