# Развертывание Корпоративный портал ВОБ №3

## Назначение

Production-развертывание поддерживает две конфигурации:

### 1. Docker (рекомендуется для Linux/VPS)

Строится на трех контейнерах:
- `web` — Django + Gunicorn
- `agent-runtime` — LangGraph runtime и MCP bridge
- `caddy` — reverse proxy

PostgreSQL хранится в отдельном Docker volume `postgres_data`. Пользовательские файлы и runtime-файлы хранятся на хосте:
- `data/media/`
- `data/logs/`
- `data/contracts/`
- `data/knowledge_repo/`

SQLite-файлы в `data/db/` остаются только legacy/dev источником миграции и не являются production target основного репозитория.

Статические файлы не монтируются в отдельный volume. Они собираются внутри image во время старта `web`.

`agent-runtime` не публикуется наружу отдельным портом. Он доступен только внутри Docker-сети и используется Django AI chat surface.

`agent-runtime` получает актуальные AI-контракты (`tools.json`, `task_types.json`, `models.json`)
через том `./data:/app/data:ro` в `docker-compose.yml` и `docker-compose.prod.yml`
(ADR-0031, доставка контрактов, шаг 1). Том смонтирован **строго read-only** — runtime
не должен иметь права записи в состояние Django. Правки контрактов через Settings Center
доходят до работающего agent-runtime без перезапуска: путь к файлу пере-резолвится на
каждое чтение, а разобранный JSON кэшируется по ключу `(st_mtime_ns, st_size, st_ino)`
(`services/agent_runtime/contract_cache.py`). Если рабочая копия недоступна (том не
смонтирован, либо Django еще не создал её при первом старте compose), runtime
откатывается на дефолт из `contracts/`, но не молча: при старте пишет `WARNING` с
фактическим путём для каждого откатившегося контракта; тот же источник виден
в `GET /health/details` runtime-сервиса (`services/agent_runtime/README.md`).
**Ограничение окружения:** `data/` должна лежать на локальной файловой системе —
на NFS/SMB инвалидация по метаданным файла не гарантирована (см. ADR-0031, раздел
«Последствия»).

### 2. IIS (для Windows Server)

Развертывание на IIS через FastCGI (wfastcgi):

- **Веб-сервер**: IIS 10.0+
- **Python**: 3.11.9 (важно: 3.13+ несовместим с wfastcgi 3.0.0)
- **FastCGI**: wfastcgi 3.0.0
- **Аутентификация**: Windows Authentication (SSO) с fallback на LDAP
- **Agent Runtime**: отдельный процесс uvicorn, запускаемый через `.venv\Scripts\python.exe` одной задачей Task Scheduler. Скрипты: `scripts/windows/setup_agent_runtime_autostart.ps1` и `scripts/windows/check_agent_runtime_autostart.ps1`.

**Важные особенности IIS развертывания**:
- Используйте отдельный IIS Site для приложения, а не application внутри другого сайта
- Требуется middleware для исправления проблемы с PATH_INFO (см. `IIS_SSO.md`)
- Секреты хранятся в `.env` файле, не в `web.config`
- Статические файлы обслуживаются через Whitenoise middleware
- Не оставляйте две задачи автозапуска Agent Runtime. Целевая задача — `Portal Agent Runtime` в `\Portal\`, исполнитель — `.venv\Scripts\python.exe`. Если есть устаревшая задача (например, из `archive/TASK_SCHEDULER_COMPLETED.md` с исполнителем `C:\Program Files\Python311\python.exe`), выполните `setup_agent_runtime_autostart.ps1 -Force` и проверьте результат через `check_agent_runtime_autostart.ps1`.
- Два процесса python с разными `ExecutablePath` (`.venv\Scripts\python.exe` и `C:\Program Files\Python311\python.exe`) — это **нормально**: uvicorn multiprocessing (master + worker) на venv, построенном поверх системного Python 3.11 (см. `pyvenv.cfg:executable`). Подробности в `WINDOWS_RUN.md` → «Анатомия процессов Agent Runtime».

## Что должно быть на VPS

- Docker
- `docker compose` plugin
- пользователь с SSH-доступом
- право запускать Docker-команды

Если у пользователя нет доступа к Docker без `sudo`, можно использовать [setup-docker-rights.sh](scripts/setup-docker-rights.sh) на самом VPS.

## Локальная подготовка

1. Сгенерировать production `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

2. Создать локальный `.env.production` по образцу `.env.example` и указать:
- `DJANGO_ENV=production`
- `DJANGO_DEBUG=0`
- `DJANGO_SECRET_KEY=<production-secret>`
- `LOCAL_BUSINESS_DB_BACKEND=postgresql`
- `POSTGRES_DB=local_business_suite`
- `POSTGRES_USER=local_business_app`
- `POSTGRES_PASSWORD=<production-db-password>`
- `DJANGO_ALLOWED_HOSTS=<ip-or-domain>`
- `DJANGO_INTERNAL_ALLOWED_HOSTS=web`
- `LOCAL_BUSINESS_SHARED_NETWORK=local-business-suite_internal`
- `LOCAL_BUSINESS_AGENT_RUNTIME_URL=http://agent-runtime:8090`
- `LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT=90`
- `GUNICORN_TIMEOUT=600`
- `GUNICORN_GRACEFUL_TIMEOUT=30`
- `OPENAI_API_KEY=<provider-key>`
- `OPENAI_BASE_URL=<openai-compatible-base-url>`
- `AI_AGENT_MODEL_NAME=<provider-model-name>`
- `LOCAL_BUSINESS_AI_GATEWAY_TOKEN=<production-token>`
- для текущего HTTP-only профиля: `DJANGO_SECURE_SSL_REDIRECT=False`, `DJANGO_SESSION_COOKIE_SECURE=False`, `DJANGO_CSRF_COOKIE_SECURE=False`

Минимальный пример:

```env
DJANGO_ENV=production
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=replace-me
LOCAL_BUSINESS_DB_BACKEND=postgresql
POSTGRES_DB=local_business_suite
POSTGRES_USER=local_business_app
POSTGRES_PASSWORD=replace-me
DJANGO_ALLOWED_HOSTS=188.120.246.243
DJANGO_INTERNAL_ALLOWED_HOSTS=web
LOCAL_BUSINESS_SHARED_NETWORK=local-business-suite_internal
LOCAL_BUSINESS_AGENT_RUNTIME_URL=http://agent-runtime:8090
LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT=90
GUNICORN_TIMEOUT=600
GUNICORN_GRACEFUL_TIMEOUT=30
LOCAL_BUSINESS_AI_GATEWAY_TOKEN=replace-me
OPENAI_API_KEY=replace-me
OPENAI_BASE_URL=https://api.openai.com/v1
AI_AGENT_MODEL_NAME=gpt-4.1-mini
DJANGO_SECURE_SSL_REDIRECT=False
DJANGO_SESSION_COOKIE_SECURE=False
DJANGO_CSRF_COOKIE_SECURE=False
```

## AI streaming timeouts

AI chat requests that use tools, especially `memory.search`, can take noticeably longer than a simple greeting because the runtime may perform:

```text
LLM call -> Django gateway tool call -> memory.search -> LLM call
```

Production `web` must therefore run Gunicorn with a timeout greater than `LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT`. The required rule is:

```text
GUNICORN_TIMEOUT >= LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT + 30
```

Default production values are:

```env
LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT=90
GUNICORN_TIMEOUT=600
GUNICORN_GRACEFUL_TIMEOUT=30
```

`python manage.py validate_architecture_contracts` checks this relation. If `GUNICORN_TIMEOUT` is too low, deployment must be stopped before users see hanging AI chat streams.

### Runtime-side LLM timeout

В дополнение к Gunicorn-таймауту, LLM-вызов в самом runtime ограничен 120 секундами через `init_kwargs = {"temperature": 0, "timeout": 120}` в `services/agent_runtime/graph.py:85-92, 209-216` (sync и stream пути). При зависании LLM-провайдера runtime получает `httpx.TimeoutException`, существующий `try/except` в `services/agent_runtime/app.py:99-105, 138-152` возвращает клиенту осмысленную ошибку и wfastcgi-воркер не зависает на стриме. Это правило не отменяет GUNICORN_TIMEOUT, а дополняет его: первое ограничивает время ожидания LLM на стороне runtime, второе — общее время обработки запроса на стороне Django.

## Опциональный базовый замер производительности

Для расследования задержек можно включить локальный сбор latency-событий. По умолчанию он выключен, чтобы не добавлять запись на диск на каждый HTTP-запрос.

```env
LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED=true
LOCAL_BUSINESS_PERFORMANCE_METRICS_PATH=data/logs/performance_events.jsonl
LOCAL_BUSINESS_PERFORMANCE_METRICS_SAMPLE_RATE=1.0
LOCAL_BUSINESS_PERFORMANCE_METRICS_EXCLUDE_PREFIXES=/static/,/media/,/favicon.
```

Отчет p50/p95:

```bash
python manage.py performance_report --group-by route_name --min-count 20
```

События не содержат полный URL, query string, тело запроса, prompt, `user_id`, значения форм или исходные документы. Операционные правила описаны в `docs/architecture/OBSERVABILITY_BASELINE.md`.

## AI chat error handling

AI chat must fail visibly and audibly in production: the UI should never leave the assistant bubble in a permanent `печатает...` state.

When Django cannot get a response from `agent-runtime`, the chat surface:

- shows a safe Russian message with the failure reason category and `request_id`;
- stores the same user-facing message in `ChatMessage` with `metadata.error=true`;
- stores technical diagnostics in `AgentActionLog` with `tool_code=agent_runtime.chat` or `agent_runtime.chat_stream`;
- stores prompt hash and prompt length, not raw prompt text, in the technical action payload;
- updates `ChatSession.metadata.last_error_request_id`, `last_error_action_id`, and `last_error_code`.

Operational check after a reported chat failure:

```bash
python manage.py shell
```

```python
from apps.ai.models import AgentActionLog

action = AgentActionLog.objects.filter(status="failed", tool_code__startswith="agent_runtime.").first()
print(action.id, action.request_payload.get("request_id"), action.error_message)
```

The `request_id` shown to the user should match `AgentActionLog.request_payload["request_id"]`. Raw runtime exception text should be visible only in `AgentActionLog.error_message` and server logs, not in the user-facing chat bubble.

## HTTP-only trusted network profile

На текущем этапе production работает без HTTPS. Это допустимо только как профиль доверенной сети:

- приложение не публикуется напрямую в интернет;
- доступ открыт только из LAN/VPN или через firewall allowlist;
- `agent-runtime` и Django AI gateway не публикуются наружу;
- `/health/` возвращает только минимальный статус, подробная диагностика доступна только staff-пользователям;
- `DJANGO_DEBUG=0`, production `DJANGO_SECRET_KEY` и `LOCAL_BUSINESS_AI_GATEWAY_TOKEN` обязательны.

## PWA и браузерные уведомления

Центр уведомлений в портале работает через обычные session-auth API и не требует отдельного runtime-сервиса.

Для PWA service worker и системных браузерных уведомлений в production нужен HTTPS. Исключение браузеров для небезопасного origin обычно действует только на `localhost` в разработке.

Если стенд остается в HTTP-only trusted network profile:

- серверная очередь и центр уведомлений в портале работают;
- browser notification permission и установка PWA могут быть недоступны или нестабильны;
- пользователю нельзя обещать системные уведомления ОС.

Для пилота PWA-уведомлений production-профиль должен быть переведен на HTTPS через Caddy, IIS TLS binding или другой утвержденный reverse proxy.

Опциональный Tauri-клиент уведомлений собирается и распространяется отдельно от Django deployment. Инструкции находятся в `docs/deployment/DESKTOP_NOTIFIER_DEPLOYMENT.md`.

## Основной сценарий деплоя

Использовать только [deploy.sh](deploy.sh):

```bash
./deploy.sh
```

Скрипт делает следующее:
- проверяет SSH-доступ;
- синхронизирует проект на VPS через `rsync --delete`;
- загружает `.env.production`;
- создает общий Docker network `local-business-suite_internal`, если его еще нет;
- при наличии старого standalone `docker-compose` делает cleanup legacy-контейнеров;
- пересобирает и поднимает production-стек через `docker compose`.

По умолчанию используются:
- host: `188.120.246.243`
- user: `admin`
- port: `2222`
- dir: `/home/admin/local-business-suite`
- compose command: `sudo docker compose`
- prod project: `local-business-suite-prod`

Их можно переопределить через переменные окружения:

```bash
VPS_HOST=example.com VPS_USER=deploy VPS_PORT=22 PROJECT_DIR=/opt/local-business-suite ./deploy.sh
```

## Как работает production-старт

`web` запускается через [docker/entrypoint.prod.sh](docker/entrypoint.prod.sh), который перед запуском Gunicorn выполняет:
- `python manage.py migrate --noinput`
- `python manage.py collectstatic --noinput`
- `python manage.py seed_roles`

Это защищает от типовых проблем первого запуска:
- нет таблиц в SQLite;
- не собрана статика;
- не созданы role groups.

`agent-runtime` запускается отдельно и читает provider variables из `.env.production`.

## Caddy

Текущий [Caddyfile](Caddyfile) обрабатывает публичный маршрут:
- `/` -> `web:8000`

Статика обслуживается Django/WhiteNoise. Это проще и надежнее для текущего состава проекта.

Если позже понадобится HTTPS через домен, Caddy можно перевести с `:80` на доменное имя и включить автоматические сертификаты.

## IIS и доменная авторизация

Для Windows/IIS доступны четыре режима авторизации через `DJANGO_AUTH_MODE`: `local`, `ldap`, `remote_user`, `hybrid`.
Подробная настройка IIS Windows Authentication, fallback-формы и LDAP/LDAPS транспорта описана в [IIS_SSO.md](IIS_SSO.md).

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
ssh -i ~/.ssh/openclaw_vps_ed25519 -p 2222 admin@188.120.246.243 'cd /home/admin/local-business-suite && sudo docker compose -p local-business-suite-prod -f docker-compose.prod.yml logs -f'
```

Статус контейнеров:

```bash
ssh -i ~/.ssh/openclaw_vps_ed25519 -p 2222 admin@188.120.246.243 'cd /home/admin/local-business-suite && sudo docker compose -p local-business-suite-prod -f docker-compose.prod.yml ps'
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
