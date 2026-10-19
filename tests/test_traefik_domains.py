import tomllib

from apps.core.models import Domain
from apps.core.tasks import sync_custom_domain_routes
from apps.core.traefik import render_custom_domain_config, write_custom_domain_config


def test_render_config_creates_exact_tls_router_for_active_domain(tenant):
    domain = Domain.objects.create(tenant=tenant, hostname="alborz8351.ir", status=Domain.Status.ACTIVE)
    Domain.objects.create(tenant=tenant, hostname="pending.ir", status=Domain.Status.PENDING)
    Domain.objects.create(tenant=tenant, hostname="error.ir", status=Domain.Status.ERROR)

    config = tomllib.loads(render_custom_domain_config([domain]))
    routers = config["http"]["routers"]

    assert len(routers) == 1
    router = next(iter(routers.values()))
    assert router["rule"] == "Host(`alborz8351.ir`) || Host(`www.alborz8351.ir`)"
    assert router["entryPoints"] == ["https"]
    assert router["service"] == "bimcrm-wild@docker"
    assert router["tls"]["certResolver"] == "letsencrypt"
    assert router["tls"]["domains"] == [{"main": "alborz8351.ir", "sans": ["www.alborz8351.ir"]}]


def test_write_config_updates_only_bimcrm_file_and_skips_identical_content(tenant, tmp_path):
    domain = Domain.objects.create(tenant=tenant, hostname="alborz8351.ir", status=Domain.Status.ACTIVE)
    config_path = tmp_path / "bimcrm-domains.toml"
    other_file = tmp_path / "other-site.toml"
    other_file.write_text("[http.routers.other]\nrule = \"Host(`other.example`)\"\n")
    other_content = other_file.read_bytes()

    assert write_custom_domain_config([domain], config_path) is True
    written = config_path.read_bytes()
    assert tomllib.loads(written.decode())["http"]["routers"]
    assert write_custom_domain_config([domain], config_path) is False
    assert config_path.read_bytes() == written
    assert other_file.read_bytes() == other_content


def test_write_empty_config_removes_stale_routes(tenant, tmp_path):
    domain = Domain.objects.create(tenant=tenant, hostname="alborz8351.ir", status=Domain.Status.ACTIVE)
    config_path = tmp_path / "bimcrm-domains.toml"
    write_custom_domain_config([domain], config_path)

    assert write_custom_domain_config([], config_path) is True
    assert tomllib.loads(config_path.read_text()) == {}


def test_sync_task_rebuilds_routes_from_active_domains(tenant, settings, tmp_path):
    active = Domain.objects.create(tenant=tenant, hostname="alborz8351.ir", status=Domain.Status.ACTIVE)
    Domain.objects.create(tenant=tenant, hostname="pending.ir", status=Domain.Status.PENDING)
    settings.TRAEFIK_DYNAMIC_CONFIG_FILE = str(tmp_path / "bimcrm-domains.toml")

    assert sync_custom_domain_routes() is True

    config = tomllib.loads((tmp_path / "bimcrm-domains.toml").read_text())
    assert len(config["http"]["routers"]) == 1
    assert active.hostname in next(iter(config["http"]["routers"].values()))["rule"]
