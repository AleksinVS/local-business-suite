#!/bin/sh
set -eu

mkdir -p /app/db /app/media /app/logs

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_roles

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000
