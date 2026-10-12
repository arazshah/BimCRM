#!/bin/sh
set -e

case "$1" in
  web)
    python manage.py migrate --noinput
    python manage.py ensure_superadmin
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-3}" --timeout 60 --access-logfile - --forwarded-allow-ips="*"
    ;;
  worker)
    exec celery -A config worker --loglevel=info --concurrency "${CELERY_CONCURRENCY:-2}"
    ;;
  beat)
    exec celery -A config beat --loglevel=info --schedule /tmp/celerybeat-schedule
    ;;
  *)
    exec "$@"
    ;;
esac
