# AGENTS.md

## Архитектурная дисциплина и структура репозитория (Repository Rules)

Все ИИ-агенты и разработчики обязаны соблюдать следующие правила для поддержания чистоты и порядка в проекте:

### 0. Язык и стиль общения
Агент должен общаться с пользователем простым и понятным техническим языком: строго по делу, без художественных сравнений, отвлеченных рассуждений и деталей, которые не помогают решить текущую задачу. В русскоязычных ответах, документации и постановках задач нужно по возможности избегать англицизмов. Если точный технический термин на английском языке необходим для однозначности (`workflow`, `runtime`, `scope`, `commit`, `push`, имя команды, путь, API-термин), допускается использовать его, но предпочтительно сразу дать русское пояснение или выбрать понятный русский эквивалент.

### 0.1 Интернет-поиск и субагенты
Если задача требует поиска в интернете, предпочтительно, но не обязательно, поручать первичный сбор источников отдельному субагенту с более дешевой моделью. Это правило применяется по ситуации: если поиск короткий, срочный, требует точного контроля источников основным агентом или субагент недоступен, основной агент может искать напрямую. Основной агент отвечает за проверку выводов, качество источников и финальное решение.

### 1. Дисциплина корня проекта (Clean Root)
Корневая директория — это витрина проекта. В ней разрешены только:
- Точки входа (`manage.py`).
- Файлы оркестрации и зависимостей (`Dockerfile`, `docker-compose.yml`, `Makefile`, `requirements.*`).
- Главные документы (`README.md`, `AGENTS.md`, `CLAUDE.md`, `PROJECT_STRUCTURE.yaml`).
- Корневой `BACKLOG.md` только как короткий указатель на актуальный backlog в `docs/planning/backlog.md`.
- Базовые шаблоны окружения (`.env.example`).
- Отдельные пользовательские клиенты в `clients/`, если они не являются серверными runtime-сервисами и имеют собственные `.desc.json`, инструкции сборки и проверки.
**Строгий запрет:** Любые временные файлы агентов, кэши тестирования (pytest, playwright), промежуточные логи или локальные скрипты должны генерироваться строго внутри скрытой директории `.local/`.

### 2. Изоляция сред развертывания (Deployment Silos)
Файлы, специфичные для конкретных серверов и хостов, не являются частью кодовой базы проекта:
- Секретные конфигурации (`.env`), SSL-сертификаты, специфичные `docker-compose` или `web.config` хранятся в приватных репозиториях.
- При развертывании эти приватные репозитории клонируются строго в `deployments/<название_хоста>/`.
- Папка `deployments/` игнорируется в `.gitignore`. Никакие секреты хостов не должны лежать в корне проекта.

### 3. Строгие границы доменов и Гибридные интеграции
Запрещено создавать приложения-свалки (God Objects).
- **Общий SDK (Транспорт):** Логика аутентификации, обработки HTTP-ошибок и базовых транспортов выносится в общие сервисы (например, `apps.core.integrations`). Она не должна знать о бизнес-моделях.
- **Доменные границы (Бизнес-логика):** Прикладная логика интеграции (маппинг внешних данных в модели `User`, `MedicalDevice`, `WorkOrder`) размещается строго внутри соответствующих приложений (`accounts`, `inventory`, `workorders`).
- **Реестр:** Общий список внешних систем хранится в `contracts/integrations/registry.json`.

### 4. Разделение Кода и Данных (Code vs Data)
В проекте реализован паттерн "Immutable Infrastructure" (неизменяемая инфраструктура):
- **Код и Дефолты:** Папки `apps/`, `contracts/`, `templates/`, `static/` управляются через Git и доступны только для чтения (Read-Only) в Production-среде.
- **Данные и Состояние:** Все изменяемые данные, включая базу данных, медиа-файлы, логи и **рабочие копии контрактов**, хранятся в директории `data/`.
- **Атомарная запись:** Любые изменения бизнес-контрактов (роли, workflow) через UI должны выполняться атомарно (запись в `.tmp` файл с последующим `os.replace`) и сохраняться строго в `data/contracts/`.

### 5. Принцип DRY (Don't Repeat Yourself)
Избегайте дублирования логики. Если функционал (например, валидация JSON или форматирование имен) используется в двух и более приложениях, он должен быть вынесен в `apps.core`.

### 6. Фиксация архитектурных решений (ADR)
Любое существенное архитектурное решение должно быть зафиксировано в Architecture Decision Record (ADR) в `docs/adr/`.
- **Когда нужен ADR:** выбор нового хранилища или внешней библиотеки, изменение границ сервисов/приложений, новый интеграционный паттерн, изменение security/privacy модели, изменение контрактов данных, ввод нового runtime-сервиса или фонового контура.
- **Формат ADR:** контекст, решение, рассмотренные альтернативы, последствия, статус (`Proposed`, `Accepted`, `Superseded`).
- **Связь с планами:** roadmap/implementation plan может описывать шаги работ, но не заменяет ADR. Если план содержит архитектурное решение, перед реализацией нужно создать или обновить соответствующий ADR.
- **Структура:** при добавлении ADR обновить `docs/adr/.desc.json` и запустить `make gen-struct`.

### 7. Актуальность проектной документации (Documentation Freshness)
Документация должна обновляться вместе с кодом, контрактами и runtime-подходами. Агент обязан проверять, не устаревают ли пользовательские инструкции, архитектурные документы и карты проекта после внесенных изменений.
- **README.md:** поддерживать как входную карту проекта для людей: назначение, текущее состояние, ключевые подсистемы, ссылки на инструкции, базовые команды запуска и проверки.
- **AGENTS.md:** поддерживать как операционный протокол для ИИ-агентов: правила работы с репозиторием, документацией, ADR, planning/workflow и проверками.
- **PROJECT_STRUCTURE.yaml:** после изменения структуры проекта обновлять через `make gen-struct`; перед этим обновить соответствующие `.desc.json`.
- **Архитектура и deployment:** при изменении границ сервисов, контрактов, настроек запуска, команд обслуживания или deployment-процедур обновлять документы в `docs/architecture/`, `docs/deployment/` и `docs/guides/`.
- **Планирование:** backlog, active plans и workflow-пакеты должны отражать актуальный статус работ; завершенные задачи не должны оставаться в активной очереди.
- **Проверка перед завершением:** в финальном отчете явно отмечать, какие документы обновлены или почему документация не требовала изменений.

### 8. Система планирования и постановки задач (Planning & Workflow)
Планирование разделено на несколько уровней. Агент обязан писать артефакты в правильное место и не смешивать backlog, планы, workflow-пакеты и временные файлы.

#### Где искать актуальное
- **Backlog:** `docs/planning/backlog.md` — единственный актуальный список активных и будущих задач. Корневой `BACKLOG.md` является только ссылкой.
- **Активные планы:** `docs/planning/active/` — человекочитаемые планы крупных направлений, которые сейчас прорабатываются или реализуются.
- **Архив планов:** `docs/planning/archive/` — закрытые или остановленные планы. В backlog архивный блок не добавляется.
- **Архитектурные решения:** `docs/adr/` — решения, которые объясняют "почему"; планы и backlog не заменяют ADR.
- **Исполнительные workflow-пакеты:** `workflow/active/` и `workflow/archive/` — технический след исполнения сложных работ.
- **Временные агентные файлы:** `.local/` — черновики, промежуточные логи, временные скрипты, результаты локальных экспериментов.

#### Что писать в backlog
`docs/planning/backlog.md` содержит только рабочую очередь:
- `Active` — задачи и направления, которые уже выполняются;
- `Next` — ближайшие кандидаты на работу;
- `Later` — отложенные идеи;
- `Blocked` — задачи, которые ждут внешнего решения или зависимости.

Не хранить в backlog завершенные задачи, историю исполнения, executor reports, acceptance reports или длинные проектные планы. После завершения задача удаляется из backlog, а итоговые материалы остаются в `docs/planning/archive/` и/или `workflow/archive/`.

#### Когда создавать план в `docs/planning/active/`
Создавайте отдельный план, если работа:
- длится больше одной небольшой правки;
- затрагивает несколько модулей;
- имеет риски для security/privacy, contracts, deployment или данных;
- требует предварительного обсуждения подхода;
- распадается на несколько задач.

Для мелких исправлений достаточно записи в backlog, понятного commit/PR и стандартных проверок.

#### Когда нужен workflow-блок
`workflow/` — это не общий список задач, а журнал исполняемых пакетов для сложных работ. Новый workflow-блок нужен только если работа:
- multi-step или multi-agent;
- требует явного read/write scope;
- требует task packets для исполнителей;
- имеет повышенный риск (`security`, `contracts`, `deployment`, миграции данных);
- должна оставить воспроизводимый след: brief, план, task packets, executor reports, acceptance reports.

Новые workflow-блоки создаются в `workflow/active/<block-id>/`. После приемки блок переносится в `workflow/archive/<YYYY>/<block-id>/`. Старые блоки, лежащие прямо в `workflow/<block-id>/`, считаются legacy-историей; новые блоки в корне `workflow/` не создавать.

#### Минимальное содержимое workflow-блока
Для сложной работы используйте такую структуру:

```text
workflow/active/<block-id>/
  BLOCK_BRIEF.md
  ARCHITECT_PLAN.json
  task-packets/
    <task-id>.json
  EXECUTOR_REPORT.<task-id>.md
  TASK_ACCEPTANCE.<task-id>.md
  RETROSPECTIVE.md
```

Допускается упрощать структуру, если блок маленький, но цель, границы, проверки и результат приемки должны быть понятны из файлов блока.

#### Definition of Ready
Задача готова к реализации, если известны:
- цель и пользовательская/бизнес-ценность;
- затрагиваемые модули и предполагаемый write scope;
- non-goals, если есть риск расползания задачи;
- acceptance checks;
- команды проверки, включая unit-тесты и, для крупных блоков разработки, e2e-тесты;
- необходимость ADR.

#### Definition of Done
Задача считается завершенной, если:
- код и документация обновлены в нужных местах;
- README.md, PROJECT_STRUCTURE.yaml, ADR, deployment/user guides и planning-документы проверены на необходимость обновления;
- unit-тесты выполнены или явно указано, почему их нельзя выполнить;
- каждый крупный блок разработки завершен e2e-тестами, покрывающими основной пользовательский или интеграционный сценарий; если e2e-тест невозможен в текущей среде, причина и остаточный риск зафиксированы в финальном отчете;
- при изменении структуры обновлены `.desc.json` и `PROJECT_STRUCTURE.yaml`;
- runtime-данные и временные артефакты не попали в корень проекта;
- backlog очищен от завершенной задачи;
- для workflow-блока есть отчет исполнения и приемка.

#### `generate_change_plan`
`python manage.py generate_change_plan` — опциональный инструмент для параллельного agent workflow и субагентной оркестрации. Он не является обязательным входом в обычную разработку. Если используется, его результаты должны попадать в соответствующий workflow-блок или `.local/`, а не в корень проекта.

## Dual-Use Context

This project is both a **production system** and a **learning platform** for the owner. Topics of study: Python, backend engineering, DevSecOps. When discussing or implementing solutions related to these areas, the agent must:

1. **Provide a brief methodological note first** — a concise explanation of the concept, pattern, or mechanism at play (what it is, why it exists, how it works in principle).
2. **Then proceed with the implementation** as usual.
3. **Detailed breakdown available on request** — if the owner asks, expand the explanation with step-by-step analysis, trade-offs, and alternatives.

## Sources Of Truth

- **Входная карта проекта для людей:** `README.md` (назначение, текущее состояние, навигация по документации и базовые проверки).
- **Операционный протокол для ИИ-агентов:** `AGENTS.md` (правила исполнения, структура, ADR, planning/workflow и проверки).
- **Карта проекта:** `PROJECT_STRUCTURE.yaml` (генерируется автоматически, содержит описания всех важных узлов).
- **Планирование:** `docs/planning/backlog.md`, `docs/planning/active/`, `docs/planning/archive/`.
- **Workflow-пакеты:** `workflow/active/`, `workflow/archive/`.
- **Архитектурные решения:** `docs/adr/`.
- **Инструменты AI:** `apps/ai/tool_definitions.py`.
- **Контракты:** `contracts/` (дефолты) и `data/contracts/` (рантайм).
- **Валидация:** `python manage.py validate_architecture_contracts`.

## AI Memory Ingestion & Graph Bootstrapping

При задачах по ingestion корпоративных документов и bootstrapping схемы графа сначала сверять:

- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- `docs/guides/MEMORY_INGESTION_OPERATIONS.md`;
- `docs/deployment/MEMORY_DEPLOYMENT.md`.

Операционные ограничения MVP:

- первый deployment target — Windows Server в домене AD;
- источники документов — dedicated read-only local folder или UNC path вида `\\SERVER\Share\Folder`;
- mapped drives для services запрещены;
- service account/gMSA credentials и host-specific UNC paths не коммитятся;
- raw mode по умолчанию `reference_only`;
- default max file size 100 MB, partial indexing обязан создавать issue/review visibility;
- graph schema bootstrapping модерируется профильными экспертами и владельцем графа;
- routine GraphEntity/GraphFact instances после принятия схемы не требуют обязательного review каждого instance;
- cloud OCR/LLM разрешены только для подготовленного non-sensitive или pseudonymized test package.

Агентам запрещено в рамках документационных или planning-задач по ingestion менять `apps/` или `contracts/` без явно заданного write scope. Временные parser logs, corpus manifests, export packages и локальные эксперименты писать только в `.local/`, а runtime eval reports — в `data/memory/eval/`.

## Bootstrap & Verification

Для code changes обязательны unit-тесты по затронутому scope. Для каждого крупного блока разработки дополнительно обязательны e2e-тесты: через HTTP/UI/API/management-command сценарий, который проверяет реальную связку компонентов, а не только отдельные функции. Временные e2e-скрипты, логи и артефакты писать только в `.local/`; постоянные e2e-тесты размещать в штатной тестовой структуре проекта.

Постоянная политика тестирования описана в `docs/guides/TESTING_POLICY.md`.

### Независимая проверка тестов

Для крупных, рискованных или многошаговых изменений рекомендуется разделять роли:
- основной агент реализует код и добавляет или обновляет тесты;
- отдельный быстрый проверочный субагент запускает согласованный набор проверок и сообщает фактические результаты.

Независимая проверка особенно желательна для изменений в `contracts/`, AI tools/runtime/MCP, памяти, правах доступа, privacy/security, миграциях данных, deployment-процедурах, e2e-сценариях и пользовательских сквозных workflow.

Проверочный субагент не должен менять код без явного задания. Его задача — запустить targeted unit/integration/e2e проверки по затронутому scope, проверить содержательность новых тестов, зафиксировать команды, результат, падения и остаточные риски. Временные файлы, логи и артефакты проверки должны оставаться в `.local/`. Для малых низкорисковых правок допускается проверка тем же агентом.

```bash
make venv
make install
make check
make test
make contracts
```

Дополнительные проверки памяти:

```bash
python manage.py memory_sync_source --dry-run
python manage.py memory_discover_source --source-code <code> --dry-run
python manage.py memory_ingest_source --source-code <code> --dry-run
python manage.py memory_prepare_bootstrap_package --source-code <code> --department <department> --dry-run
python manage.py memory_graph_extract --source-code <code> --dry-run
python manage.py memory_file_organization_baseline --source-code <code> --dry-run
python manage.py memory_file_incoming_worker --source-code <code> --dry-run
python manage.py memory_file_structure_stats --source-code <code> --dry-run
python manage.py memory_file_move_worker --source-code <code> --dry-run
python manage.py memory_file_auto_organization_e2e
python manage.py memory_reindex --dry-run
python manage.py memory_eval --dry-run
python manage.py validate_architecture_contracts
```

При любом изменении структуры (добавлении папок/важных файлов) необходимо обновить соответствующие `.desc.json` и запустить `make gen-struct`.

## Handoff

- `archive/PROJECT_HANDOFF.md` — исторический обзор.
- `AGENTS.md` — актуальный протокол исполнения.
