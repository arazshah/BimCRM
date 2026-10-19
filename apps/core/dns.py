"""Checks whether an agent's domain points its NS records at the platform."""

import re

import dns.exception
import dns.resolver

from .models import Domain, PlatformSettings

HOSTNAME_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def normalize_hostname(value: str) -> str:
    value = (value or "").strip().lower()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    value = value.split("/")[0].split(":")[0].rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    return value


def lookup_nameservers(hostname: str) -> list[str]:
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 6
    try:
        answer = resolver.resolve(hostname, "NS")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
        return []
    return sorted(str(r.target).rstrip(".").lower() for r in answer)


def nameservers_match(found: list[str], expected: list[str]) -> bool:
    return bool(found) and set(found) == set(expected)


def check_domain(domain: Domain, resolver=lookup_nameservers) -> bool:
    from . import pdns

    expected = PlatformSettings.load().get_nameservers()
    found = resolver(domain.hostname)
    ok = nameservers_match(found, expected)
    domain.mark_checked(found, ok)
    if ok:
        # Keep reconciling the zone while the nameservers point here. If PowerDNS was unavailable
        # during activation, the periodic check can recover without requiring a manual action.
        pdns.ensure_zone(domain.hostname, expected)
    return ok
