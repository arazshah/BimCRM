"""Render and update BimCRM's isolated Traefik dynamic configuration file."""

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterable
from pathlib import Path

from django.conf import settings

from .models import Domain

_HOSTNAME_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_CONFIG_HEADER = "# Managed by BimCRM. Manual edits will be replaced.\n"


def render_custom_domain_config(domains: Iterable[Domain]) -> str:
    """Return TOML containing exact HTTPS routers for active, valid custom domains only."""
    entries = sorted(
        {
            domain.hostname.lower().rstrip(".")
            for domain in domains
            if domain.status == Domain.Status.ACTIVE and _HOSTNAME_RE.fullmatch(domain.hostname.lower().rstrip("."))
        }
    )
    sections = [_CONFIG_HEADER.rstrip()]
    for hostname in entries:
        router_name = f"bimcrm-domain-{hashlib.sha256(hostname.encode()).hexdigest()[:16]}"
        www_hostname = f"www.{hostname}"
        sections.extend(
            [
                "",
                f"[http.routers.{router_name}]",
                f"rule = {json.dumps(f'Host(`{hostname}`) || Host(`{www_hostname}`)')}",
                'entryPoints = ["https"]',
                'service = "bimcrm-wild@docker"',
                "priority = 1000",
                f"[http.routers.{router_name}.tls]",
                'certResolver = "letsencrypt"',
                f"[[http.routers.{router_name}.tls.domains]]",
                f"main = {json.dumps(hostname)}",
                f"sans = [{json.dumps(www_hostname)}]",
            ]
        )
    return "\n".join(sections) + "\n"


def write_custom_domain_config(domains: Iterable[Domain], path=None) -> bool:
    """Update only the dedicated BimCRM file; return whether its contents changed.

    The file is bind-mounted into the worker by inode, so it must be updated in place rather than
    replaced with os.replace. flock serializes overlapping Celery runs. Trailing whitespace is
    retained when the rendered configuration shrinks, which is valid TOML and avoids truncation.
    """
    configured_path = path if path is not None else settings.TRAEFIK_DYNAMIC_CONFIG_FILE
    if not configured_path:
        return False

    output = render_custom_domain_config(domains).encode("utf-8")
    fd = os.open(Path(configured_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        existing_length = os.fstat(fd).st_size
        existing = os.read(fd, existing_length)
        if existing.rstrip(b" \t\r\n") == output.rstrip(b" \t\r\n"):
            return False

        payload = output + b" " * max(0, existing_length - len(output))
        os.lseek(fd, 0, os.SEEK_SET)
        written = 0
        while written < len(payload):
            written += os.write(fd, payload[written:])
        os.fsync(fd)
        return True
    finally:
        os.close(fd)
