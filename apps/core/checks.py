from django.core.checks import Warning, register
from django.db import connection


@register(deploy=True)
def rls_effective(app_configs, **kwargs):
    """Row-level security is silently skipped for superusers and BYPASSRLS roles."""
    if connection.vendor != "postgresql":
        return []
    try:
        with connection.cursor() as c:
            c.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            row = c.fetchone()
    except Exception:  # database not reachable at check time
        return []
    if row and row[0]:
        return [
            Warning(
                "The app connects to PostgreSQL as a superuser/BYPASSRLS role, so row-level security is not "
                "enforced. Set APP_DB_USER/APP_DB_PASSWORD and connect with that role (see DEPLOY.md).",
                id="bimcrm.W001",
            )
        ]
    return []
