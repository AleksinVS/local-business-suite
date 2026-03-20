# Развертывание Local Business Suite на VPS

## Назначение

Production-развертывание строится на трех контейнерах:
- `web` — Django + Gunicorn
- `agent-runtime` — LangGraph runtime и MCP bridge
- `caddy` — reverse proxy

LibreChat разворачивается отдельным compose-проектом и доступен через `Caddy` по пути `/librechat/`, без отдельного внешнего порта.

База данных и пользовательские файлы хранятся на хосте:
- `db/`
- `media/`
- `logs/`

Статические файлы не монтируются в отдельный volume. Они собираются внутри image во время старта `web`.

`agent-runtime` не публикуется наружу отдельным портом. Он доступен только внутри Docker-сети и используется Django AI chat surface.

## Что должно быть на VPS

- Docker
- `docker compose` plugin
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
- `LOCAL_BUSINESS_SHARED_NETWORK=local-business-suite_internal`
- `LOCAL_BUSINESS_AGENT_RUNTIME_URL=http://agent-runtime:8090`
- `OPENAI_API_KEY=<provider-key>`
- `OPENAI_BASE_URL=<openai-compatible-base-url>`
- `AI_AGENT_MODEL_NAME=<provider-model-name>`
- `LIBRECHAT_PUBLIC_URL=http://<host>/librechat`
- `LIBRECHAT_APP_TITLE=<chat-title>`
- `LIBRECHAT_JWT_SECRET=<64-hex>`
- `LIBRECHAT_JWT_REFRESH_SECRET=<64-hex>`
- `LIBRECHAT_CREDS_KEY=<64-hex>`
- `LIBRECHAT_CREDS_IV=<32-hex>`
- `LIBRECHAT_MEILI_MASTER_KEY=<64-hex>`
- при необходимости `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`

Минимальный пример:

```env
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=replace-me
DJANGO_ALLOWED_HOSTS=188.120.246.243
DJANGO_INTERNAL_ALLOWED_HOSTS=web
LOCAL_BUSINESS_SHARED_NETWORK=local-business-suite_internal
LOCAL_BUSINESS_AGENT_RUNTIME_URL=http://agent-runtime:8090
OPENAI_API_KEY=replace-me
OPENAI_BASE_URL=https://api.openai.com/v1
AI_AGENT_MODEL_NAME=gpt-4.1-mini
LIBRECHAT_PUBLIC_URL=http://188.120.246.243/librechat
LIBRECHAT_APP_TITLE=Local Business Suite AI Chat
LIBRECHAT_JWT_SECRET=replace-with-64-hex-chars
LIBRECHAT_JWT_REFRESH_SECRET=replace-with-64-hex-chars
LIBRECHAT_CREDS_KEY=replace-with-64-hex-chars
LIBRECHAT_CREDS_IV=replace-with-32-hex-chars
LIBRECHAT_MEILI_MASTER_KEY=replace-with-64-hex-chars
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
- генерирует production `services/librechat/.env` из `.env.production`;
- создает общий Docker network `local-business-suite_internal`, если его еще нет;
- при наличии старого standalone `docker-compose` делает cleanup legacy-контейнеров;
- пересобирает и поднимает production-стек через `docker compose`;
- пересобирает и поднимает LibreChat-стек отдельным `docker compose` project;
- публикует LibreChat через `/librechat/` на основном хосте.

По умолчанию используются:
- host: `188.120.246.243`
- user: `admin`
- port: `2222`
- dir: `/home/admin/local-business-suite`
- compose command: `sudo docker compose`
- prod project: `local-business-suite-prod`
- librechat project: `local-business-suite-librechat`

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

LibreChat запускается отдельным compose-проектом, но в общей internal-сети, и публикуется только через Caddy. Внешний URL должен указывать на путь `/librechat/`.

## Caddy

Текущий [Caddyfile](/home/abc/.openclaw/workspace/projects/local-business-suite/Caddyfile) обрабатывает два публичных маршрута:
- `/` -> `web:8000`
- `/librechat/` -> `librechat:3080`

Статика обслуживается Django/WhiteNoise. Это проще и надежнее для текущего состава проекта.

Если позже понадобится HTTPS через домен, Caddy можно перевести с `:80` на доменное имя и включить автоматические сертификаты.

## Проверка после деплоя

Проверить вручную:

```bash
curl -I http://<host>/health/
curl -I http://<host>/accounts/login/
curl -I http://<host>/librechat/
curl -I http://<host>/
```

Ожидаемое поведение:
- `/health/` -> `200`
- `/accounts/login/` -> `200`
- `/librechat/` -> `200`
- `/` -> `302` на login или dashboard

## Полезные команды

Логи:

```bash
ssh -i ~/.ssh/openclaw_vps_ed25519 -p 2222 admin@188.120.246.243 'cd /home/admin/local-business-suite && sudo docker compose -p local-business-suite-prod -f docker-compose.prod.yml logs -f'
```

Логи LibreChat:

```bash
ssh -i ~/.ssh/openclaw_vps_ed25519 -p 2222 admin@188.120.246.243 'cd /home/admin/local-business-suite && sudo docker compose -p local-business-suite-librechat -f docker-compose.librechat.yml -f docker-compose.librechat.prod.yml logs -f'
```

Статус контейнеров:

```bash
ssh -i ~/.ssh/openclaw_vps_ed25519 -p 2222 admin@188.120.246.243 'cd /home/admin/local-business-suite && sudo docker compose -p local-business-suite-prod -f docker-compose.prod.yml ps'
```

Статус LibreChat:

```bash
ssh -i ~/.ssh/openclaw_vps_ed25519 -p 2222 admin@188.120.246.243 'cd /home/admin/local-business-suite && sudo docker compose -p local-business-suite-librechat -f docker-compose.librechat.yml -f docker-compose.librechat.prod.yml ps'
```

Ручной rebuild:

```bash
ssh -i ~/.ssh/openclaw_vps_ed25519 -p 2222 admin@188.120.246.243 'cd /home/admin/local-business-suite && sudo docker compose -p local-business-suite-prod -f docker-compose.prod.yml down --remove-orphans && sudo docker compose -p local-business-suite-prod -f docker-compose.prod.yml up -d --build'
```

## Типовые проблемы

### `500` на `/accounts/login/`

Наиболее вероятные причины:
- не попал каталог `static/` в Docker build context;
- не выполнился `collectstatic`;
- старый контейнер остался после неудачного deploy;
- `.env.production` не был загружен на VPS.

### `docker compose` падает при пересоздании стека

Если VPS еще использует старый `docker-compose` 1.29, он может падать на `ContainerConfig`. Этот проект теперь рассчитан на `docker compose` plugin.

```bash
docker compose version
sudo docker compose -p local-business-suite-prod -f docker-compose.prod.yml down --remove-orphans
sudo docker compose -p local-business-suite-prod -f docker-compose.prod.yml up -d --build
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
