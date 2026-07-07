#!/bin/sh
set -eu

mkdir -p /app/staticfiles

# Идемпотентная первичная подготовка runtime: каталоги data/ и копии дефолтных
# контрактов в data/contracts/. Заменяет побочные эффекты, которые раньше
# выполнялись на импорте config/settings.py. Выполняется ДО migrate, не требует БД
# и не запускает system checks (иначе проверка контрактов сработала бы до того,
# как рабочие копии скопированы). Повторный запуск безопасен.
python manage.py bootstrap_runtime

python manage.py wait_for_database --timeout "${LOCAL_BUSINESS_DB_WAIT_TIMEOUT:-60}"
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_roles

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --timeout "${GUNICORN_TIMEOUT:-600}" \
    --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
    --workers "${GUNICORN_WORKERS:-3}" \
    --worker-class "${GUNICORN_WORKER_CLASS:-sync}"
