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
    # Make sure our PowerDNS zone exists BEFORE looking up the NS records. A recursive resolver
    # follows the registry delegation to our nameservers; with no zone they answer REFUSED, the
    # lookup fails (SERVFAIL) and the NS never look "ours" — so creating the zone only after a
    # successful check would deadlock every newly delegated domain. ensure_zone() is idempotent,
    # never raises, and also recovers from earlier PowerDNS outages on every periodic check.
    pdns.ensure_zone(domain.hostname, expected)
    found = resolver(domain.hostname)
    ok = nameservers_match(found, expected)
    domain.mark_checked(found, ok)
    return ok
