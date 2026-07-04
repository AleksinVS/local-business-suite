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
- **Автоупорядочивание файловых источников памяти** с виртуальной baseline-структурой, входным каталогом и безопасным managed_fs переносом.
- **Уведомления портала**: PWA/browser notifications без стороннего Web Push и опциональный Tauri-клиент в трее.
- **Аналитика** по заявкам и устройствам.
- **Контрактная конфигурация** ролей, workflow, AI tools, task types и memory sources.

## Архитектура

Основные блоки:

- `apps/` — Django-приложения доменов: accounts, inventory, workorders, waiting_list, analytics, ai, memory, core.
- `contracts/` — дефолтные JSON-контракты, которые версионируются в Git.
- `data/contracts/` — runtime-копии контрактов для изменяемой среды.
- `services/agent_runtime/` — отдельный runtime AI-агента на LangGraph/MCP.
- `services/copilot_runtime/` — пилотный CopilotKit Runtime для AG-UI интеграции в основной Django UI.
- `clients/desktop-notifier/` — опциональный Tauri-клиент уведомлений в трее.
- `docs/` — архитектура, ADR, инструкции пользователя, deployment и планирование.
- `workflow/` — рабочие пакеты и отчеты выполнения активных блоков разработки.

Ключевые источники истины:

- `AGENTS.md` — актуальный протокол работы ИИ-агентов.
- `PROJECT_STRUCTURE.yaml` — автоматически генерируемая карта структуры проекта.
- `contracts/` и `data/contracts/` — декларативные контракты системы.
- `apps/ai/tool_definitions.py` — реестр AI-инструментов на стороне Django.
- `python manage.py validate_architecture_contracts` — проверка контрактов.

Основной целевой вариант нового ИИ-чата - самописный AG-UI-compatible UI поверх общего backend-контура. Он является режимом по умолчанию (`LOCAL_BUSINESS_AI_UI_DRIVER=native`) и не требует Node.js в production runtime. CopilotKit используется как отдельный равноправный драйвер, пилот и эталон совместимости; он описан в `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`, `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md` и `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`. Общая основа протокола описана в `docs/architecture/AI_UI_PROTOCOL_FOUNDATION_PLAN.md`.

## Система памяти AI

Система памяти реализована как Django-приложение `apps.memory`, а не как отдельный сетевой сервис. AI runtime обращается к ней через Django gateway и read-only tool `memory.search`.

Что делает память:

- синхронизирует источники из `contracts/ai/memory_sources.json`;
- пропускает данные через privacy pipeline перед индексированием;
- хранит принятые знания в runtime Git-репозитории `data/knowledge_repo/`;
- хранит метаданные знаний в основной PostgreSQL database; SQLite-вариант сохранен в отдельной legacy-ветке/форке;
- поддерживает PostgreSQL full-text индекс в основной БД; SQLite FTS остается dev/legacy-бэкендом;
- обнаруживает корпоративные документы из local/UNC источников через ingestion MVP;
- строит стабильную идентичность файлов, baseline virtual structure, входной каталог и согласованный managed_fs перенос с quarantine/purge gate;
- дает пользователю личную виртуальную файловую структуру в `/memory/files/`, не меняя физическое размещение и права доступа;
- ведет issue/review queue для skipped, partial, unsupported и рискованных документов;
- поддерживает контракт `memory_graph_schema.json` как контролируемый словарь типов рёбер для блока `relations:` frontmatter и детерминированный материализатор `MemoryKnowledgeEdge` (ADR-0030 решение 3; LLM graph-extraction контур удален), но не включает graph runtime search;
- содержит reference implementation подключения внешних информационных систем через queued API-коннекторы, database queue backend и normalized landing zone;
- хранит данные чатов, metadata памяти и управляющие модели аналитики в единой основной БД;
- возвращает AI-чату только безопасные результаты с `citations`;
- пишет каждый разрешенный или запрещенный поиск в `MemoryAccessAudit`.

Основные файлы:

- `docs/architecture/MEMORY_MVP_CURRENT_STATE.md` — фактическая рабочая граница текущей MVP-памяти.
- `docs/guides/MEMORY_USER_GUIDE.md` — как пользоваться памятью через AI-чат и что проверять в ответах.
- `docs/guides/MEMORY_INGESTION_OPERATIONS.md` — как внедрять ingestion на Windows/UNC, вести issue/review queue и bootstrapping схемы графа.
- `docs/guides/MEMORY_EXTERNAL_SYSTEMS_QUESTIONNAIRES.md` — бизнес-опросники для подключения внешних ИС и первичного описания сущностей графа знаний.
- `docs/deployment/MEMORY_DEPLOYMENT.md` — как развернуть, настроить и проверить память.
- `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md` — план реализации и архитектурные пояснения.
- `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md` — целевая схема файловых знаний, раздельных баз и единого поиска.
- `docs/architecture/MEMORY_FILE_ONLY_KNOWLEDGE_BODY_PLAN.md` — план строгого хранения текста знания только в файле знания.
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md` — финальный план ingestion-коннектора и bootstrapping схемы графа.
- `docs/architecture/MEMORY_FILE_SOURCE_AUTO_ORGANIZATION_PLAN.md` — план автоупорядочивания файловых источников: virtual structure, incoming, proposals, managed_fs и future S3.
- `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_PLAN.md` — план сбора знаний из внешних информационных систем.
- `docs/adr/ADR-0003-ai-memory-service.md` — архитектурное решение по памяти.
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md` — архитектурное решение по ingestion и bootstrapping.
- `docs/adr/ADR-0006-external-system-knowledge-connectors.md` — архитектурное решение по коннекторам внешних ИС.
- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md` — архитектурное решение по файловым знаниям и единому поиску.
- `docs/adr/ADR-0013-file-only-knowledge-body.md` — архитектурное решение: текст знания только в файле, индекс перестраиваемый.
- `docs/adr/ADR-0025-file-source-auto-organization.md` — архитектурное решение по автоупорядочиванию файловых источников.
- `contracts/ai/memory_sources.json` — источники памяти.
- `contracts/ai/memory_profiles.json` — профили chunking, extraction, indexing и ranking.
- `contracts/ai/memory_routing.json` — правила маршрутизации по sensitivity.
- `contracts/ai/memory_ingestion_profiles.json` — профили local/UNC adapters, parser/OCR cascade, limits и raw/ACL policies.
- `contracts/ai/memory_file_organization_profiles.json` — профили входного каталога, managed root, retention и порогов предложений файловой структуры.
- `contracts/ai/memory_graph_schema.json` — контролируемый словарь типов рёбер/концептов для `relations:` frontmatter и материализатора рёбер.

Ограничения текущей версии:

- production scheduler/Celery пока не подключен;
- в production full-text индекс хранится в основной PostgreSQL БД; SQLite FTS5 остается для dev/legacy;
- LanceDB vector backend включен с локальным deterministic test embedding profile; production-модель подключается отдельной настройкой;
- старый слой `MemorySnapshot`/`MemoryChunk` удален из текущей схемы; индексация идет через `MemorySearchDocument`;
- отдельное DuckDB-хранилище аналитических срезов еще не подключено;
- external connector MVP является reference implementation; source-specific pilot adapter выбирается и реализуется отдельно;
- автоупорядочивание файлов поддерживает `managed_fs`, а S3/S3-compatible backend оставлен будущим backend;
- graph runtime search отключен и отображается как `disabled/not_ready`;
- ingestion MVP реально обрабатывает text-like файлы (`.txt`, `.md`, `.log`, `.json`, `.yaml`, `.yml`, `.csv`, `.tsv`) и табличные `.xlsx/.xls`, а PDF/DOC/DOCX/images пока переводит в issue queue до подключения Docling/Tika/OCR backend;
- внешний API памяти вынесен в backlog и пока не реализуется;
- облачная маршрутизация для чувствительных случаев не включена.

Ограничения ingestion/bootstrapping MVP:

- первый источник документов — dedicated read-only folder на Windows Server или UNC path;
- mapped drives для сервисов не используются;
- raw mode по умолчанию `reference_only`, без копирования всех документов в `data/memory/raw_vault/`;
- default file limit 100 MB, большие/сложные документы допускают partial indexing с issue flag;
- ACL inheritance, production cloud OCR/LLM и mandatory review каждого graph instance не входят в MVP.

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

Подробная политика тестирования: `docs/guides/TESTING_POLICY.md`.
Практические способы ускорения без снижения покрытия: `docs/guides/TEST_ACCELERATION.md`.

Базовые проверки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test
```

Проверки системы памяти:

```bash
python manage.py memory_sync_source --dry-run
python manage.py memory_discover_source --source-code <code> --dry-run
python manage.py memory_ingest_source --source-code <code> --dry-run
python manage.py memory_prepare_bootstrap_package --source-code <code> --department <department> --dry-run
python manage.py memory_reconcile --dry-run
python manage.py memory_reindex --corpus all --backend fulltext --dry-run
python manage.py memory_reindex --corpus all --backend vector --dry-run
python manage.py memory_eval --dry-run
python manage.py knowledge_reflection_worker --dry-run
python manage.py memory_verify_knowledge_files --strict
python manage.py memory_alignment_acceptance_e2e
python manage.py memory_file_organization_baseline --source-code <code> --dry-run
python manage.py memory_file_incoming_worker --source-code <code> --dry-run
python manage.py memory_file_structure_stats --source-code <code> --dry-run
python manage.py memory_file_move_worker --source-code <code> --dry-run
python manage.py memory_file_auto_organization_e2e
python manage.py memory_file_content_search_e2e
```

`memory.remember` пишет знание синхронно (файл + git commit + индекс за один вызов); `knowledge_writer_worker`/`knowledge_index_worker` выведены из кода (ADR-0030). Команды автоупорядочивания файлов зарегистрированы в замороженном `apps.filehub`.

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

Отчет по базовым latency-метрикам, если включен сбор `LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED=true`:

```bash
python manage.py performance_report
```

## Развертывание

Поддерживаемые варианты:

- **Linux/VPS**: Docker Compose, Gunicorn, Caddy. Основная инструкция: `docs/deployment/DEPLOYMENT.md`.
- **Windows Server / IIS**: IIS 10+, FastCGI, wfastcgi, Python 3.11. Инструкция: `docs/deployment/IIS_SSO.md`.
- **Локальный запуск Windows**: `docs/deployment/WINDOWS_RUN.md`.
- **Система памяти**: дополнительные шаги в `docs/deployment/MEMORY_DEPLOYMENT.md`.
- **Tauri-клиент уведомлений**: сборка и распространение в `docs/deployment/DESKTOP_NOTIFIER_DEPLOYMENT.md`.

Runtime-данные не коммитятся:

- база данных, медиа и логи;
- `data/contracts/` — рабочие копии контрактов;
- `data/knowledge_repo/` — runtime Git-репозиторий знаний;
- `data/db/*.sqlite3` — только legacy/dev SQLite-файлы и источники миграции, не production target основного репозитория;
- `data/indexes/` — полнотекстовые, векторные и графовые индексы;
- `data/processing/` — временные raw/safe/extraction слои;
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
- `docs/architecture/OBSERVABILITY_BASELINE.md` — базовая наблюдаемость, p50/p95 и команда `performance_report`.
- `docs/architecture/SERVICE_EXTRACTION_GUIDE.md` — правила безопасного выноса технических workers/services без смены основного стека.
- `docs/architecture/POSTGRESQL_PRIMARY_STORE_PLAN.md` — целевой план миграции основного хранилища на одну PostgreSQL database и выноса SQLite-варианта.
- `docs/architecture/KNOWLEDGE_DRIVEN_ANALYTICS_PLAN.md` — непрерывная бизнес-аналитика из знаний, email, документов и DMS.
- `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md` — план реализации сервиса памяти.
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md` — план ingestion-коннектора и bootstrapping схемы графа.
- `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_PLAN.md` — план queued API-коннекторов и landing zone для внешних ИС.
- `docs/architecture/PWA_AND_TAURI_NOTIFICATIONS_PLAN.md` — архитектура PWA-уведомлений и Tauri-клиента.
- `docs/guides/MEMORY_USER_GUIDE.md` — руководство по системе памяти.
- `docs/guides/NOTIFICATIONS_USER_GUIDE.md` — руководство по центру уведомлений и PWA.
- `docs/guides/DESKTOP_NOTIFIER_USER_GUIDE.md` — руководство по Tauri-клиенту уведомлений.
- `docs/guides/MEMORY_INGESTION_OPERATIONS.md` — эксплуатация ingestion, review queues и schema bootstrapping.
- `docs/guides/MEMORY_EXTERNAL_SYSTEMS_QUESTIONNAIRES.md` — опросники для владельцев данных и профильных экспертов.
- `docs/guides/TEST_ACCELERATION.md` — ускорение локальных и контрольных тестов без снижения покрытия.
- `docs/guides/TESTING_POLICY.md` — уровни тестов, матрица обязательных проверок и независимая проверка субагентом.
- `docs/guides/WORKER_AND_QUEUE_OPERATIONS.md` — единые правила worker-команд, очередей, retry и idempotency.
- `docs/deployment/MEMORY_DEPLOYMENT.md` — deployment и smoke-проверки памяти.
- `docs/deployment/POSTGRESQL_MIGRATION.md` — runbook миграции с SQLite runtime-файлов на одну PostgreSQL database.
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
