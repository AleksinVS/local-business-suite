# Корпоративный портал ВОБ №3

Корпоративный портал для управления техническим обслуживанием и ремонтами медицинских изделий с поддержкой Active Directory, AI-чата, локальной системы памяти и аналитического контура.

Проект развивается как local-first Django monorepo: основной контур работает локально/on-premise, бизнес-правила описываются контрактами, изменяемое runtime-состояние хранится в `data/`, а архитектурные решения фиксируются в ADR.

## Текущее состояние

Реализованы и поддерживаются:

- **Канбан-доска заявок** на техническое обслуживание и ремонт с workflow.
- **Лист ожидания** для первичной регистрации заявок.
- **Справочник медицинских изделий** с архивированием.
- **Active Directory / Windows SSO** для корпоративной аутентификации.
- **Ролевая модель и политики доступа** на основе серверных контрактов.
- **AI-чат** с bounded tools и gateway-интеграцией в Django.
- **Система памяти AI** для поиска по безопасному корпусу знаний с citations и audit.
- **Аналитика** по заявкам и устройствам.
- **Контрактная конфигурация** ролей, workflow, AI tools, task types и memory sources.

## Архитектура

Основные блоки:

- `apps/` — Django-приложения доменов: accounts, inventory, workorders, waiting_list, analytics, ai, memory, core.
- `contracts/` — дефолтные JSON-контракты, которые версионируются в Git.
- `data/contracts/` — runtime-копии контрактов для изменяемой среды.
- `services/agent_runtime/` — отдельный runtime AI-агента на LangGraph/MCP.
- `docs/` — архитектура, ADR, инструкции пользователя, deployment и планирование.
- `workflow/` — рабочие пакеты и отчеты выполнения активных блоков разработки.

Ключевые источники истины:

- `AGENTS.md` — актуальный протокол работы ИИ-агентов.
- `PROJECT_STRUCTURE.yaml` — автоматически генерируемая карта структуры проекта.
- `contracts/` и `data/contracts/` — декларативные контракты системы.
- `apps/ai/tool_definitions.py` — реестр AI-инструментов на стороне Django.
- `python manage.py validate_architecture_contracts` — проверка контрактов.

## Система памяти AI

Система памяти реализована как Django-приложение `apps.memory`, а не как отдельный сетевой сервис. AI runtime обращается к ней через Django gateway и read-only tool `memory.search`.

Что делает память:

- синхронизирует источники из `contracts/ai/memory_sources.json`;
- пропускает данные через privacy pipeline перед индексированием;
- хранит safe corpus, manifests и локальные индексы в `data/memory/`;
- поддерживает полнотекстовый MVP backend на SQLite FTS;
- хранит графовые факты через backend-neutral интерфейс;
- возвращает AI-чату только безопасные результаты с `citations`;
- пишет каждый разрешенный или запрещенный поиск в `MemoryAccessAudit`.

Основные файлы:

- `docs/guides/MEMORY_USER_GUIDE.md` — как пользоваться памятью через AI-чат и что проверять в ответах.
- `docs/deployment/MEMORY_DEPLOYMENT.md` — как развернуть, настроить и проверить память.
- `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md` — план реализации и архитектурные пояснения.
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md` — финальный план ingestion-коннектора и bootstrapping схемы графа.
- `docs/adr/ADR-0003-ai-memory-service.md` — архитектурное решение по памяти.
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md` — архитектурное решение по ingestion и bootstrapping.
- `contracts/ai/memory_sources.json` — источники памяти.
- `contracts/ai/memory_profiles.json` — профили chunking, extraction, indexing и ranking.
- `contracts/ai/memory_routing.json` — правила маршрутизации по sensitivity.

Ограничения текущей версии:

- production scheduler/Celery пока не подключен;
- embeddings-интерфейс заложен, но в MVP используется локальный full-text backend;
- Kuzu backend подготовлен как lazy placeholder;
- ingestion-коннектор корпоративных документов и bootstrapping схемы графа спроектированы, но еще не реализованы;
- внешний API памяти вынесен в backlog и пока не реализуется;
- облачная маршрутизация для чувствительных случаев не включена.

## Быстрый старт

### Linux/VPS

```bash
git clone https://github.com/AleksinVS/local-business-suite.git
cd local-business-suite
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Windows

```cmd
git clone https://github.com/AleksinVS/local-business-suite.git
cd local-business-suite
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Проверка проекта

Базовые проверки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test
```

Проверки системы памяти:

```bash
python manage.py memory_sync_source --dry-run
python manage.py memory_reindex --dry-run
python manage.py memory_eval --dry-run
```

Ожидаемый smoke-результат для eval:

```text
Memory eval checks: passed=4, failed=0
```

Проверка AI tool registry:

```bash
python manage.py shell -c "from apps.ai.tool_definitions import get_tool_registry; print('memory.search' in get_tool_registry())"
```

Ожидаемо:

```text
True
```

## Развертывание

Поддерживаемые варианты:

- **Linux/VPS**: Docker Compose, Gunicorn, Caddy. Основная инструкция: `docs/deployment/DEPLOYMENT.md`.
- **Windows Server / IIS**: IIS 10+, FastCGI, wfastcgi, Python 3.11. Инструкция: `docs/deployment/IIS_SSO.md`.
- **Локальный запуск Windows**: `docs/deployment/WINDOWS_RUN.md`.
- **Система памяти**: дополнительные шаги в `docs/deployment/MEMORY_DEPLOYMENT.md`.

Runtime-данные не коммитятся:

- база данных, медиа и логи;
- `data/contracts/` — рабочие копии контрактов;
- `data/memory/safe_corpus/`;
- `data/memory/indexes/`;
- `data/memory/manifests/`;
- `data/memory/eval/`.

## Документация

- `docs/architecture/ARCHITECTURE.md` — обзор архитектуры и ссылки на ключевые документы.
- `docs/architecture/blueprint.md` — архитектурный blueprint.
- `docs/architecture/DOMAIN_MODEL.md` — доменная модель.
- `docs/architecture/POLICY_MODEL.md` — модель ролей и политик.
- `docs/architecture/INTEGRATIONS.md` — стратегия интеграций.
- `docs/architecture/ANALYTICS_MODEL.md` — аналитический контур.
- `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md` — план реализации сервиса памяти.
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md` — план ingestion-коннектора и bootstrapping схемы графа.
- `docs/guides/MEMORY_USER_GUIDE.md` — руководство по системе памяти.
- `docs/deployment/MEMORY_DEPLOYMENT.md` — deployment и smoke-проверки памяти.
- `docs/deployment/DEPLOYMENT.md` — production deployment.
- `docs/deployment/IIS_SSO.md` — IIS и Active Directory.
- `docs/planning/README.md` — процесс планирования.
- `docs/planning/backlog.md` — backlog.
- `docs/adr/` — Architecture Decision Records.
- `archive/` — исторические материалы.

## Правила разработки

- Архитектурно значимые решения фиксируются в ADR.
- Новые важные файлы и директории описываются в `.desc.json`.
- После изменения структуры нужно запускать `make gen-struct`.
- Временные файлы, логи и локальные артефакты создаются только в `.local/`.
- Секреты и host-specific deployment-файлы не хранятся в репозитории.
- Изменяемые бизнес-контракты в runtime пишутся в `data/contracts/`.

## Лицензия и поддержка

Проект является внутренним корпоративным приложением.

Для настройки и эксплуатации используйте документацию из `docs/deployment/` и `docs/guides/`. Для архитектурных изменений сначала проверьте `docs/adr/` и актуальный backlog.
