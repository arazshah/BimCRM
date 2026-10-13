"""The tenant of the current request, kept in a context variable and mirrored into PostgreSQL.

Application code filters by tenant through TenantManager. As a second, independent layer, PostgreSQL
row-level security (see apps/core/rls.py) only lets a connection see rows of the tenant named in the
session setting `app.tenant_id`. With no tenant set (super admin, background jobs that loop over all
offices, the marketing site) the setting is empty and every row is visible, as before.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connection

_current_tenant: ContextVar = ContextVar("current_tenant", default=None)

RLS_SETTING = "app.tenant_id"


def get_current_tenant():
    return _current_tenant.get()


def _sync_db(tenant):
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, false)", [RLS_SETTING, str(tenant.pk) if tenant else ""])


def set_current_tenant(tenant):
    token = _current_tenant.set(tenant)
    _sync_db(tenant)
    return token


def reset_current_tenant(token):
    _current_tenant.reset(token)
    # Persistent connections (CONN_MAX_AGE) are reused by the next request: never leave a tenant behind.
    _sync_db(_current_tenant.get())


@contextmanager
def tenant_context(tenant):
    token = set_current_tenant(tenant)
    try:
        yield tenant
    finally:
        reset_current_tenant(token)
