"""Creates/updates the limited database role the running app connects with.

Row-level security does not apply to superusers or roles with BYPASSRLS, and the postgres Docker image
makes POSTGRES_USER a superuser. So migrations run as that owner, and web/worker/beat connect as
APP_DB_USER: a plain role that can read and write rows but cannot bypass RLS or change the schema.

Run with the owner's connection: DATABASE_URL=$MIGRATE_DATABASE_URL python manage.py ensure_app_role
"""

import os

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Create or update the non-superuser role the application connects as."

    def handle(self, *args, **options):
        user = os.environ.get("APP_DB_USER", "")
        password = os.environ.get("APP_DB_PASSWORD", "")
        if connection.vendor != "postgresql":
            self.stdout.write("Not PostgreSQL; skipping.")
            return
        if not user:
            self.stdout.write("APP_DB_USER not set; skipping (the app will use the owner role, RLS ineffective).")
            return
        if not password:
            raise CommandError("APP_DB_PASSWORD is required with APP_DB_USER.")
        q = connection.ops.quote_name
        with connection.cursor() as c:
            c.execute("SELECT current_user, current_database()")
            owner, database = c.fetchone()
            c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [user])
            verb = "ALTER" if c.fetchone() else "CREATE"
            c.execute(
                f"{verb} ROLE {q(user)} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD %s", [password]
            )
            for sql in [
                f"GRANT CONNECT ON DATABASE {q(database)} TO {q(user)}",
                f"GRANT USAGE ON SCHEMA public TO {q(user)}",
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {q(user)}",
                f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {q(user)}",
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {q(owner)} IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {q(user)}",
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {q(owner)} IN SCHEMA public "
                f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {q(user)}",
            ]:
                c.execute(sql)
        self.stdout.write(self.style.SUCCESS(f"Role {user} ready ({verb.lower()}d)."))
