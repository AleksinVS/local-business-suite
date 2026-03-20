# Развертывание Local Business Suite на VPS

## Назначение

Production-развертывание строится на трех контейнерах:
- `web` — Django + Gunicorn
- `agent-runtime` — LangGraph runtime и MCP bridge
- `caddy` — reverse proxy

База данных и пользовательские файлы хранятся на хосте:
- `db/`
- `media/`
- `logs/`

Статические файлы не монтируются в отдельный volume. Они собираются внутри image во время старта `web`.

`agent-runtime` не публикуется наружу отдельным портом. Он доступен только внутри Docker-сети и используется Django AI chat surface.

## Что должно быть на VPS

- Docker
- `docker-compose` 1.x или 2.x
- пользователь с SSH-доступом
- право запускать Docker-команды

Если у пользователя нет доступа к Docker без `sudo`, можно использовать [setup-docker-rights.sh](/home/abc/.openclaw/workspace/projects/local-business-suite/setup-docker-rights.sh) на самом VPS.

## Локальная подготовка

1. Сгенерировать production `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

2. Создать локальный `.env.production` по образцу `.env.example` и указать:
- `DJANGO_DEBUG=0`
- `DJANGO_SECRET_KEY=<production-secret>`
- `DJANGO_ALLOWED_HOSTS=<ip-or-domain>`
- `DJANGO_INTERNAL_ALLOWED_HOSTS=web`
- `LOCAL_BUSINESS_AGENT_RUNTIME_URL=http://agent-runtime:8090`
- `OPENAI_API_KEY=<provider-key>`
- `OPENAI_BASE_URL=<openai-compatible-base-url>`
- `AI_AGENT_MODEL_NAME=<provider-model-name>`
- при необходимости `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`

Минимальный пример:

```env
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=replace-me
DJANGO_ALLOWED_HOSTS=188.120.246.243
DJANGO_INTERNAL_ALLOWED_HOSTS=web
LOCAL_BUSINESS_AGENT_RUNTIME_URL=http://agent-runtime:8090
OPENAI_API_KEY=replace-me
OPENAI_BASE_URL=https://api.openai.com/v1
AI_AGENT_MODEL_NAME=gpt-4.1-mini
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

## Основной сценарий деплоя

Использовать только [deploy.sh](/home/abc/.openclaw/workspace/projects/local-business-suite/deploy.sh):

```bash
./deploy.sh
```

Скрипт делает следующее:
- проверяет SSH-доступ;
- синхронизирует проект на VPS через `rsync --delete`;
- загружает `.env.production`;
- выполняет `docker-compose down --remove-orphans`;
- пересобирает и поднимает production-стек.

По умолчанию используются:
- host: `188.120.246.243`
- user: `admin`
- port: `2222`
- dir: `/home/admin/local-business-suite`
- compose command: `sudo docker-compose`

Их можно переопределить через переменные окружения:

```bash
VPS_HOST=example.com VPS_USER=deploy VPS_PORT=22 PROJECT_DIR=/opt/local-business-suite ./deploy.sh
```

## Как работает production-старт

`web` запускается через [docker/entrypoint.prod.sh](/home/abc/.openclaw/workspace/projects/local-business-suite/docker/entrypoint.prod.sh), который перед запуском Gunicorn выполняет:
- `python manage.py migrate --noinput`
- `python manage.py collectstatic --noinput`
- `python manage.py seed_roles`

Это защищает от типовых проблем первого запуска:
- нет таблиц в SQLite;
- не собрана статика;
- не созданы role groups.

`agent-runtime` запускается отдельно и читает provider variables из `.env.production`.

## Caddy

Текущий [Caddyfile](/home/abc/.openclaw/workspace/projects/local-business-suite/Caddyfile) intentionally minimal:
- HTTP на `:80`
- `reverse_proxy web:8000`
- без отдельной файловой раздачи `/static` и `/media`

Статика обслуживается Django/WhiteNoise. Это проще и надежнее для текущего состава проекта.

Если позже понадобится HTTPS через домен, Caddy можно перевести с `:80` на доменное имя и включить автоматические сертификаты.

## Проверка после деплоя

Проверить вручную:

```bash
curl -I http://<host>/health/
curl -I http://<host>/accounts/login/
curl -I http://<host>/
```

Ожидаемое поведение:
- `/health/` -> `200`
- `/accounts/login/` -> `200`
- `/` -> `302` на login или dashboard

## Полезные команды

Логи:

```bash
ssh -i ~/.ssh/openclaw_vps_ed25519 -p 2222 admin@188.120.246.243 'cd /home/admin/local-business-suite && sudo docker-compose -f docker-compose.prod.yml logs -f'
```

Статус контейнеров:

```bash
ssh -i ~/.ssh/openclaw_vps_ed25519 -p 2222 admin@188.120.246.243 'cd /home/admin/local-business-suite && sudo docker-compose -f docker-compose.prod.yml ps'
```

Ручной rebuild:

```bash
ssh -i ~/.ssh/openclaw_vps_ed25519 -p 2222 admin@188.120.246.243 'cd /home/admin/local-business-suite && sudo docker-compose -f docker-compose.prod.yml down --remove-orphans && sudo docker-compose -f docker-compose.prod.yml up -d --build'
```

## Типовые проблемы

### `500` на `/accounts/login/`

Наиболее вероятные причины:
- не попал каталог `static/` в Docker build context;
- не выполнился `collectstatic`;
- старый контейнер остался после неудачного deploy;
- `.env.production` не был загружен на VPS.

### `docker-compose` падает с `KeyError: ContainerConfig`

Это баг старого `docker-compose` 1.29 на некоторых VPS. Рабочий обход:

```bash
sudo docker-compose -f docker-compose.prod.yml down --remove-orphans
sudo docker-compose -f docker-compose.prod.yml up -d --build
```

### `502 Bad Gateway`

Проверить:
- поднялся ли `web`;
- прошли ли миграции;
- отвечает ли `http://localhost:8000/health/` внутри контейнера `web`.

### Статика не находится

Проверить:
- что `static/` не исключен из `.dockerignore`;
- что `collectstatic` выполнился без ошибок;
- что HTML ссылается на manifest-generated файлы, а не на отсутствующие raw paths.
