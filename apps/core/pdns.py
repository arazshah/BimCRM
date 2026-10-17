"""Creates a DNS zone (with an A record pointing here) for an agent's own domain once its NS
records point at us — otherwise an "active" Domain in our DB is just bookkeeping: our PowerDNS
has no zone for it, so it answers nothing and the site never actually loads.

Needs PDNS_API_URL / PDNS_API_KEY / SERVER_PUBLIC_IP (see DEPLOY.md, section 4). Without them,
ensure_zone() is a no-op — a platform that only uses subdomains (bimcrm.ir wildcard) doesn't need
this at all.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _api(path: str) -> str:
    return f"{settings.PDNS_API_URL.rstrip('/')}/api/v1/servers/localhost{path}"


def _headers() -> dict:
    return {"X-API-Key": settings.PDNS_API_KEY, "Content-Type": "application/json"}


def ensure_zone(hostname: str, nameservers: list[str]) -> bool:
    """Idempotent: create the zone if missing, then make sure its apex A record (and www) point
    at SERVER_PUBLIC_IP. Returns True if the zone is ready, False if PowerDNS isn't configured or
    the call failed (logged, never raised — a DNS hiccup shouldn't break the admin page or the
    5-minute domain-check task).
    """
    if not (settings.PDNS_API_URL and settings.PDNS_API_KEY and settings.SERVER_PUBLIC_IP):
        return False
    fqdn = f"{hostname}."
    try:
        resp = requests.post(
            _api("/zones"),
            json={
                "name": fqdn,
                "kind": "Native",
                "nameservers": [f"{ns}." if not ns.endswith(".") else ns for ns in nameservers],
            },
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code not in (201, 409):
            logger.warning("pdns zone create for %s -> HTTP %s: %s", hostname, resp.status_code, resp.text[:300])
            return False
        patch = requests.patch(
            _api(f"/zones/{fqdn}"),
            json={
                "rrsets": [
                    {
                        "name": fqdn,
                        "type": "A",
                        "ttl": 300,
                        "changetype": "REPLACE",
                        "records": [{"content": settings.SERVER_PUBLIC_IP, "disabled": False}],
                    },
                    {
                        "name": f"www.{fqdn}",
                        "type": "A",
                        "ttl": 300,
                        "changetype": "REPLACE",
                        "records": [{"content": settings.SERVER_PUBLIC_IP, "disabled": False}],
                    },
                ]
            },
            headers=_headers(),
            timeout=10,
        )
        if patch.status_code not in (204,):
            logger.warning("pdns A record for %s -> HTTP %s: %s", hostname, patch.status_code, patch.text[:300])
            return False
        return True
    except requests.RequestException:
        logger.exception("pdns zone setup failed for %s", hostname)
        return False
