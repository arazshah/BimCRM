#!/bin/sh
set -e

case "$1" in
  web)
    # Schema changes and the app role use the owner connection; the app itself runs as the limited role.
    OWNER_URL="${MIGRATE_DATABASE_URL:-$DATABASE_URL}"
    DATABASE_URL="$OWNER_URL" python manage.py migrate --noinput
    DATABASE_URL="$OWNER_URL" python manage.py ensure_app_role
    python manage.py ensure_superadmin
    python manage.py check --deploy --fail-level ERROR || true
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-3}" --timeout 60 --access-logfile - --forwarded-allow-ips="*"
    ;;
  worker)
    # Rehydrate BimCRM's exact-host routes on deploy. If the optional bind-mounted file is not
    # writable yet, keep Celery running so its periodic retry can recover after permissions are fixed.
    python manage.py shell -c 'from apps.core.tasks import sync_custom_domain_routes; sync_custom_domain_routes()' \
      || echo "WARNING: BimCRM Traefik route sync failed; periodic domain checks will retry." >&2
    exec celery -A config worker --loglevel=info --concurrency "${CELERY_CONCURRENCY:-2}"
    ;;
  beat)
    exec celery -A config beat --loglevel=info --schedule /tmp/celerybeat-schedule
    ;;
  *)
    exec "$@"
    ;;
esac
