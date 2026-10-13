"""PostgreSQL row-level security for every table with per-office data (TenantOwned models).

The policy: when `app.tenant_id` is set, only that tenant's rows can be read, inserted, updated or
deleted; when it is empty, everything is visible (super admin and cross-office background jobs).
FORCE is required because the application connects as the tables' owner, who otherwise bypasses RLS.

New TenantOwned models must be added with `enable_rls_operation(...)` in their migration;
tests/test_rls.py fails if any TenantOwned table is missing it.
"""

from django.db import migrations

POLICY = "tenant_isolation"
# nullif first: PostgreSQL may evaluate both sides of OR, and ''::bigint would fail.
_TENANT = "nullif(current_setting('app.tenant_id', true), '')::bigint"
CONDITION = f"{_TENANT} IS NULL OR tenant_id = {_TENANT}"

_ENABLE = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS {policy} ON {table};
CREATE POLICY {policy} ON {table}
    USING ({condition})
    WITH CHECK ({condition});
"""

_DISABLE = """
DROP POLICY IF EXISTS {policy} ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""


def _run(sql_template, tables):
    def apply(apps, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            return
        for table in tables:
            schema_editor.execute(
                sql_template.format(table=schema_editor.quote_name(table), policy=POLICY, condition=CONDITION)
            )

    return apply


def enable_rls_operation(*tables):
    return migrations.RunPython(_run(_ENABLE, tables), _run(_DISABLE, tables))
