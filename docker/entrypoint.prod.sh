#!/bin/sh
set -eu

mkdir -p /app/data/db /app/data/media /app/data/logs /app/data/contracts /app/staticfiles

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_roles

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --timeout "${GUNICORN_TIMEOUT:-600}" \
    --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
    --workers "${GUNICORN_WORKERS:-3}" \
    --worker-class "${GUNICORN_WORKER_CLASS:-sync}"
