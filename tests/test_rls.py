"""PostgreSQL row-level security. These run in CI (PostgreSQL) and are skipped on SQLite."""

import pytest
from django.apps import apps
from django.db import connection, transaction
from django.db.utils import ProgrammingError

from apps.core.models import TenantOwned
from apps.core.tenancy import tenant_context
from apps.crm.models import Customer

from .conftest import host

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="row-level security is PostgreSQL-only"),
]


def _setting():
    with connection.cursor() as c:
        c.execute("SELECT current_setting('app.tenant_id', true)")
        return c.fetchone()[0] or ""


def test_every_tenant_table_has_forced_rls():
    tables = sorted(m._meta.db_table for m in apps.get_models() if issubclass(m, TenantOwned))
    with connection.cursor() as c:
        c.execute(
            "SELECT relname FROM pg_class WHERE relname = ANY(%s) AND relrowsecurity AND relforcerowsecurity",
            [tables],
        )
        protected = sorted(r[0] for r in c.fetchall())
    assert protected == tables, f"missing RLS: {set(tables) - set(protected)} — add enable_rls_operation()"


def test_database_hides_other_offices_even_without_the_manager(tenant, other_tenant):
    with tenant_context(tenant):
        Customer.objects.create(full_name="خودی", mobile="09120000101")
    with tenant_context(other_tenant):
        Customer.objects.create(full_name="غریبه", mobile="09120000102")
    with tenant_context(tenant):
        # all_objects has no tenant filter: only the database stands in the way
        assert list(Customer.all_objects.values_list("full_name", flat=True)) == ["خودی"]
        with connection.cursor() as c:
            c.execute("SELECT count(*) FROM crm_customer")
            assert c.fetchone()[0] == 1
        assert Customer.all_objects.filter(mobile="09120000102").update(full_name="x") == 0
    # No tenant set (super admin, cross-office jobs): everything is visible
    assert Customer.all_objects.count() == 2


def test_database_refuses_writing_into_another_office(tenant, other_tenant):
    with tenant_context(tenant):
        with pytest.raises(ProgrammingError), transaction.atomic():
            Customer.all_objects.create(tenant=other_tenant, full_name="نفوذی", mobile="09120000103")


def test_request_does_not_leave_tenant_on_the_connection(client, tenant):
    assert _setting() == ""
    client.get("/", HTTP_HOST=host(tenant))
    assert _setting() == ""
    with tenant_context(tenant):
        assert _setting() == str(tenant.pk)
        with tenant_context(None):
            assert _setting() == ""
        assert _setting() == str(tenant.pk)
    assert _setting() == ""
