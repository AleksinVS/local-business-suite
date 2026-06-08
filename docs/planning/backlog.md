# Backlog

Актуальная очередь работ. Завершенные задачи здесь не хранятся: после завершения они удаляются из backlog, а итоговые планы и workflow-артефакты остаются в `docs/planning/archive/` и `workflow/archive/`.

## Active

### Русификация интерфейса портала

MVP реализован и ожидает приемку владельцем. Видимые элементы UI переведены на русский, путь к будущей архитектуре локализации зафиксирован без внедрения полноценного многоязычного runtime в текущем срезе.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0022-interface-russification-and-localization-roadmap.md`;
- активный план находится в `docs/planning/active/interface-russification-and-localization.md`;
- workflow package находится в `workflow/active/interface-russification/`;
- правила UI-строк находятся в `docs/guides/INTERFACE_RUSSIFICATION.md`.

Статус реализации:
- переведены шаблоны, JS-сообщения, Django labels, формы, настройки и описания ИИ-инструментов;
- переведены дефолтные контракты `contracts/ai/tools.json` и `contracts/ai/task_types.json`, рабочие копии обновлены в `data/contracts/ai/`;
- технические коды, JSON-ключи, tool id и общепринятые аббревиатуры оставлены без перевода;
- проверки Django, контрактов, unit, e2e и визуальный проход выполнены.

Оставшееся действие:
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

### Дерево заявок и режимы просмотра доски

MVP реализован и ожидает приемку владельцем. На существующей странице заявок добавлен режим `view=tree`, сохранены канбан-доска, правый сайдбар, фильтры и стиль карточек.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0023-workorder-tree-view-and-customer-branch-access.md`;
- активный план находится в `docs/planning/active/workorder-tree-view.md`;
- workflow package находится в `workflow/active/workorder-tree-view/`.

Статус реализации:
- добавлен `department_branch` scope для заявок;
- роль `customer` в дефолтном и runtime-контракте переведена на видимость ветки `User.department`;
- формы создания и редактирования ограничивают подразделения и медизделия доступной веткой;
- дерево строится серверно поверх текущего visible queryset;
- открытие, создание и редактирование заявок из дерева используют правый сайдбар;
- добавлены unit/view тесты и Playwright e2e spec.

Оставшееся действие:
- выполнить браузерный e2e на стенде с `E2E_USERNAME` и `E2E_PASSWORD`;
- проверить заполненность `User.department` у реальных заказчиков;
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

### Модульные AI skills и registry-driven MCP-фасад

MVP реализован и ожидает приемку владельцем. Доменные AI workflow вынесены из общего agent runtime в skills, которые регистрируют сами модули. Существующий MCP-сервер стал внешним фасадом для безопасных resources поверх тех же реестров, но не стал обязательной внутренней прослойкой sidebar chat.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0021-module-registered-agent-skills-and-mcp-facade.md`;
- активный план находится в `docs/planning/active/module-registered-agent-skills-and-mcp-facade.md`;
- workflow package находится в `workflow/active/module-registered-agent-skills-and-mcp-facade/`.

Статус реализации:
- добавлен `apps.core.ai_skills` registry;
- `apps.ai.skills_service` собирает module и runtime contract skills;
- зарегистрированы skills для `workorders`, `waiting_list` и `ai.skill_creator`;
- временный hard-coded shortcut по заявкам удален из agent runtime;
- добавлено управляемое создание instruction-only runtime skills через `ai.skills.create_or_update`;
- добавлены MCP resources для skills/tools/module capabilities;
- обновлены unit/integration/e2e проверки и операторская документация.

Оставшееся действие:
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

### Универсальные источники для памяти и аналитики

MVP общего source adapter/envelope подхода реализован и ожидает приемку владельцем. Канбан, лист ожидания, файлы, внешние API и будущие модули подключаются к памяти и аналитике через адаптеры, без прямой зависимости ядра памяти от доменных моделей.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0018-universal-source-adapters-memory-analytics.md`;
- активный план находится в `docs/planning/active/universal-source-adapters-memory-analytics.md`;
- workflow package находится в `workflow/active/universal-source-adapters-memory-analytics/`.

Статус реализации:
- ADR-0018 принят;
- добавлены `SourceObjectEnvelope`, `SourceAdapter` protocol и adapter registry;
- добавлен privacy profile resolver: PII по умолчанию выключено, для внешних источников включен guarded profile, при `pii_off` PII-аудит выключен;
- secret scanning остается всегда включенным;
- memory projection и analytics projection строятся из одного envelope;
- `workorders` и `waiting_list` подключены как внутренние адаптеры с `adapter_check`;
- добавлены `source_adapter_reconcile`, `workorders.search`, тесты и операторская документация.

Оставшееся действие:
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

### Контекстный ИИ-чат в левой боковой панели

MVP реализован и ожидает приемку владельцем. Меню перенесено в `Все функции`, левая панель занята встроенным ИИ-чатом, добавлены `PageContextEnvelope`, `AIWindowContextSnapshot`, `ui.get_current_context`, общий контракт `ai.chat_settings` и e2e для контекста открытой заявки.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0019-context-aware-sidebar-ai-chat.md`;
- активный план находится в `docs/planning/active/context-aware-sidebar-ai-chat.md`;
- workflow package находится в `workflow/active/context-aware-sidebar-ai-chat/`;
- руководство находится в `docs/guides/AI_SIDEBAR_CHAT.md`.

Оставшееся действие:
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

### Knowledge-driven business analytics

MVP vertical slice реализован: контракты аналитики, контрольные модели, fixture-first IMAP/email ingestion, общий extraction packet, дедупликация, пересчет метрик, reflection-кандидаты и AI diagnostics routing. В active backlog остается production hardening и подключение реальных источников.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0008-knowledge-driven-business-analytics.md`;
- проектный план находится в `docs/architecture/KNOWLEDGE_DRIVEN_ANALYTICS_PLAN.md`;
- операционный guide находится в `docs/guides/KNOWLEDGE_ANALYTICS_OPERATIONS.md`;
- active planning находится в `docs/planning/active/knowledge-driven-business-analytics.md`;
- workflow package находится в `workflow/active/knowledge-driven-business-analytics/`.

Оставшийся scope:
- подключить production IMAP/IDLE adapter с UIDVALIDITY/UID watermarks и секретами из deployment-среды;
- заменить JSONL fallback на Parquet/DuckDB после выбора runtime-зависимостей;
- подключить production queue backend для scheduled/polling jobs;
- добавить LLM/parser extraction backend вместо deterministic MVP extractor;
- реализовать optional DMS connector для выбранной системы документооборота;
- провести pilot tuning scope, retention, authority и dedup rules с владельцем данных.

### Автоупорядочивание файловых источников

MVP реализован и ожидает приемку владельцем. Добавлен контур stable file identity, автоматический baseline, входной каталог, агрегированные предложения структуры, managed_fs copy/verify/quarantine/purge gate, минимальный UI и e2e-проверка. S3/S3-compatible backend оставлен как future backend через подготовленную модель хранения.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0025-file-source-auto-organization.md`;
- проектный план находится в `docs/architecture/MEMORY_FILE_SOURCE_AUTO_ORGANIZATION_PLAN.md`;
- активный план находится в `docs/planning/active/memory-file-source-auto-organization.md`;
- workflow package находится в `workflow/active/memory-file-source-auto-organization/`.

Статус реализации:
- добавлены модели `MemoryFileObject`, версии, физические размещения, path aliases, virtual views/placements, usage events, organization proposals/decisions и move jobs;
- добавлен контракт `memory_file_organization_profiles.json` и schema;
- baseline generator создает виртуальные размещения с confidence/evidence/conflicts и review visibility;
- incoming worker обрабатывает стабильные файлы и блокирует найденные секреты;
- статистика создает предложения только после aggregation thresholds;
- managed_fs перенос выполняет copy/verify/metadata commit/quarantine, а purge требует retention и backup checkpoint;
- UI `/memory/review/file-organization/` показывает источники, baseline, proposals и move jobs;
- UI `/memory/files/` позволяет пользователю создать личное виртуальное размещение доступного файла;
- `memory_file_auto_organization_e2e` покрывает основной сценарий.

Оставшееся действие:
- выбрать реальный пилотный source, настроить runtime `managed_root`, retention и backup checkpoint;
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

### PWA-first уведомления и опциональный Tauri-клиент

Этап 1 PWA/browser notifications реализован как MVP. Этап 2 Tauri реализован как первичный optional client и ожидает техническую проверку сборки на целевых ОС.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0026-pwa-first-and-optional-tauri-notifications.md`;
- проектный план находится в `docs/architecture/PWA_AND_TAURI_NOTIFICATIONS_PLAN.md`;
- активный план находится в `docs/planning/active/desktop-notifications-pwa-tauri.md`;
- workflow package находится в `workflow/active/desktop-notifications-pwa-tauri/`;
- руководство пользователя находится в `docs/guides/NOTIFICATIONS_USER_GUIDE.md`.
- руководство Tauri-клиента находится в `docs/guides/DESKTOP_NOTIFIER_USER_GUIDE.md`;
- deployment guide Tauri-клиента находится в `docs/deployment/DESKTOP_NOTIFIER_DEPLOYMENT.md`.

Статус реализации:
- добавлен серверный домен `apps.notifications`;
- добавлен центр уведомлений в шапку портала;
- добавлены PWA manifest и root service worker;
- browser permission запрашивается только по явному действию пользователя;
- доставка в открытую страницу работает через polling с cursor;
- события заявок создают безопасные уведомления для разрешенных получателей;
- добавлены unit/integration тесты и Playwright spec для PWA-ресурсов.
- добавлен device API для Tauri: exchange-code, feed, ack, revoke;
- добавлена страница `Уведомления` -> `Устройства`;
- добавлен Tauri 2 клиент `clients/desktop-notifier/` с tray, notifications, autostart, opener и Stronghold vault.

Оставшееся действие:
- выполнить миграции на целевой базе;
- проверить HTTPS-профиль production для PWA/browser notifications;
- выполнить авторизованный Playwright UI-сценарий на стенде с `E2E_USERNAME` и `E2E_PASSWORD`;
- собрать Tauri-клиент на Windows и выбранном Linux окружении;
- проверить tray/notification behavior на рабочих местах;
- решить вопросы installer signing, обновлений и подавления дублей PWA/Tauri;
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

## Next

### CopilotKit и AG-UI в основном Django UI

Подготовлен документационный срез для пилотного встраивания CopilotKit в основной Django UI через AG-UI adapter. Реализация не начата: перед стартом нужно согласовать ADR и deployment-подход.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- проектный план находится в `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`;
- активный план находится в `docs/planning/active/copilotkit-ag-ui-integration.md`;
- workflow package находится в `workflow/active/copilotkit-ag-ui-integration/`;
- операционный guide находится в `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md`;
- deployment note находится в `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`.

Предварительный scope:
- добавить AG-UI endpoint в `services.agent_runtime`, не ломая текущие `/chat` и `/chat/stream`;
- добавить отдельный server-side Copilot Runtime service;
- встроить CopilotKit как React island за feature flag;
- сохранить Django AI gateway, confirmation и audit как единственный путь бизнес-действий;
- покрыть основной сценарий e2e и проверить privacy/security ограничения.

Критерии готовности к старту:
- владелец принимает ADR-0027 или корректирует решение;
- согласовано, нужен ли отдельный `services/copilot_runtime`;
- согласовано место первого React island: текущий sidebar или отдельный экспериментальный маршрут;
- согласовано, кто видит pilot и какие e2e обязательны для первого включения.

### Внедрение архитектурных паттернов

Подготовлен отдельный planning/workflow-блок для постепенного внедрения прикладных паттернов из архитектурного анализа. Scope направлен на единые сценарии записи, безопасные AI-команды, единые политики доступа, переходники источников и надежные фоновые задачи.

Контекст:
- анализ паттернов находится в `docs/architecture/DESIGN_PATTERNS_REVIEW_2026-06-01.md`;
- активный план находится в `docs/planning/active/design-patterns-hardening-2026-06-01.md`;
- workflow package находится в `workflow/active/design-patterns-hardening-2026-06-01/`;
- связанные исправления по ревью находятся в `docs/planning/active/architecture-review-remediation-2026-06-01.md`.

Предварительный scope:
- свести write-сценарии UI, AI и management commands к доменным сервисам;
- оформить AI write tools как команды с подтверждением, audit и trace identifiers;
- усилить service identity и session ownership в AI gateway/MCP;
- унифицировать политики доступа и повторяемые выборки;
- закрепить `SourceAdapter`/`SourceObjectEnvelope` как границу памяти, аналитики и внешних источников;
- спроектировать job/outbox contract для ingestion, indexing, analytics recompute и external connectors;
- добавить idempotency keys, retry limits и ручной путь разбора ошибок.

Критерии готовности к старту:
- завершены или синхронизированы пересекающиеся исправления из архитектурного ревью;
- согласовано, какие write-сценарии входят в первый срез;
- определено, нужен ли ADR для изменения AI gateway/MCP identity model или production worker контура.

### Исправления по архитектурному ревью 2026-06-01

Архитектурное ревью сохранено и требует отдельного hardening-среза перед расширением production-использования AI/MCP, памяти и внешних источников.

Контекст:
- ревью находится в `docs/guides/ARCHITECTURE_REVIEW_2026-06-01.md`;
- активный план находится в `docs/planning/active/architecture-review-remediation-2026-06-01.md`;
- workflow package находится в `workflow/active/architecture-review-remediation-2026-06-01/`.

Предварительный scope:
- привести production-старт и Windows/IIS инструкции к миграциям всех runtime-баз: `default`, `chat`, `knowledge_meta`, `analytics_control`;
- свести изменение `role_rules` к единому Settings Center service layer с atomic write, validation и audit;
- убрать raw prompt и полный actor context из agent runtime logs, оставить разбор ошибок по `request_id`, hash и данным `ChatMessage`;
- усилить AI gateway/MCP identity checks до публикации MCP наружу;
- перенести PATH_INFO debug logging из корня проекта в runtime/local path;
- обновить устаревшие ссылки в архитектурной документации.

Критерии готовности к старту:
- подтверждено, что корневой `BACKLOG.md` остается личными заметками владельца и не входит в scope чистки;
- согласовано, будет ли `access.update_role_permissions` оставлен как audited wrapper или переведен в proposal-only;
- согласована модель service identity для MCP, если фасад планируется использовать вне внутренней Docker/host-сети.

### Производительность и готовность к выносу сервисов

Базовое архитектурное решение и минимальный контур p50/p95 реализованы. Следующий этап — собрать фактические показатели на пилоте и закрыть дешевые узкие места внутри текущего Django-стека до обсуждения Go/Rust-выноса.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0024-service-extraction-readiness.md`;
- правила выноса сервисов находятся в `docs/architecture/SERVICE_EXTRACTION_GUIDE.md`;
- baseline наблюдаемости находится в `docs/architecture/OBSERVABILITY_BASELINE.md`;
- операции worker/очередей находятся в `docs/guides/WORKER_AND_QUEUE_OPERATIONS.md`;
- опциональный HTTP latency-сбор включается через `LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED=true`;
- отчет p50/p95 доступен через `python manage.py performance_report`.

Предварительный scope:
- включить latency-сбор на тестовом или пилотном стенде и собрать p50/p95 по доске заявок, правому сайдбару, AI-чату и memory.search;
- закрыть дешевые проблемы из `docs/guides/PROJECT_REVIEW.md`: N+1, недостающие `db_index`, SQLite WAL/PRAGMA и тяжелые выборки;
- добавить p50/p95 для ключевых management commands и worker-очередей;
- формализовать единый job contract для новых очередей без миграции старых моделей без необходимости;
- по результатам измерений решить, нужны ли PostgreSQL, Celery/Redis, Qdrant или отдельный worker.

Критерии готовности к старту:
- выбран стенд для сбора метрик;
- согласован срок хранения `data/logs/performance_events.jsonl`;
- определены начальные p95-пороги для рабочих сценариев;
- подтвержден список страниц и команд для первого замера.

### Профили гибридного ранжирования памяти и подсказки ИИ-бота

FTS5 и LanceDB уже подключены, но гибридное ранжирование пока не нормализует BM25/vector score как разные шкалы. Следующий этап — ввести серверные профили ранжирования, включить semantic search по исходным файлам через локальные embeddings и закрепить, как ИИ-бот выбирает режим поиска по намерению пользователя.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0016-memory-hybrid-ranking-profiles.md`;
- активный план находится в `docs/planning/active/memory-hybrid-ranking-profiles-and-agent-prompts.md`;
- workflow package находится в `workflow/active/memory-hybrid-ranking-profiles/`.

Предварительный scope:
- добавить `ranking_profile` в `memory.search` и agent runtime wrapper;
- заменить сложение raw score на RRF-based fusion;
- включить LanceDB retrieval для `source_data` в явных source-режимах без нового внешнего API;
- добавить правила: секрет блокирует индексирование документа и ставит blocker issue; PII индексируется, но ставится в audit queue;
- реализовать reindex/delete по `document_id` с delete+upsert для LanceDB;
- добавить trace с профилем, весами, RRF-позициями и итоговым score;
- уточнить системные подсказки ИИ-бота для `source_explicit`, `knowledge_semantic`, `knowledge_precise`, `source_fallback`;
- покрыть `precise`, `balanced`, `semantic_heavy`, `source_content` и `source_semantic` e2e-тестами.

Критерии готовности к старту:
- подтверждено, что MVP использует RRF, а не min-max как основной fusion;
- подтверждено, что source semantic search входит в ближайший scope без нового внешнего API и cloud embeddings;
- согласованы тексты подсказок ИИ-бота.

### Поиск по крупным разделам документов

FTS5 и LanceDB по документу целиком реализованы. Следующий отдельный этап — перейти от документного результата к крупным разделам/листам/диапазонам строк без возврата старой модели `MemoryChunk`.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0015-file-content-fts-vector-search.md`;
- архивный план реализованного среза находится в `docs/planning/archive/2026/memory-file-content-fts-and-vector-search.md`;
- предварительно рекомендованный вариант — `MemorySearchSegment` в Django без хранения полного текста.

### Pilot adapter внешней информационной системы

Generic external connector MVP архивирован как reference implementation. Следующий шаг возможен только после выбора первой внешней системы.

Критерии готовности к старту:
- выбран pilot source и владелец данных;
- заполнены опросники из `docs/guides/MEMORY_EXTERNAL_SYSTEMS_QUESTIONNAIRES.md`;
- утверждены sensitivity, scope mapping и retention;
- подтвержден способ синхронизации: delta API, `updated_at`, webhook+reconciliation или scheduled full sync.

### Система обезличивания данных и управляемые настройки

Черновик направления: реализовать контур обезличивания, управляемый контрактами, который включается постепенно по источникам, типам данных, целевым системам и этапам обработки.

Контекст:
- черновое архитектурное решение находится в `docs/adr/ADR-0012-data-anonymization-and-privacy-pipeline.md`;
- черновой план находится в `docs/planning/active/data-anonymization-privacy-pipeline.md`;
- связанный Settings Center план находится в `docs/planning/active/settings-center-gui.md`.

Предварительный scope:
- добавить контракт `contracts/privacy/anonymization_profiles.json` и JSON Schema;
- реализовать resolver маршрутов `source/type/target/stage -> profile`;
- включить MVP только на `before_cloud_llm` и `before_external_export`;
- добавить режимы `off`, `observe`, `warn`, `detect_and_redact`, `stable_pseudonym`, `review`, `block`;
- добавить audit без исходных PII/secret values;
- добавить dry-run/eval проверки;
- позже подключить Settings Center, Presidio-compatible adapter и privacy-worker.

Критерии готовности к старту:
- утверждены пилотные источники и целевые системы;
- согласован минимальный набор entity types;
- согласованы fallback-правила для внешних передач;
- подготовлен синтетический eval corpus;
- ADR и план переведены из черновика в принятое состояние.

### Production parser/OCR backend для ingestion памяти

Подключить production-grade parser/OCR cascade к уже реализованному ingestion MVP.

Контекст:
- архитектурное решение принято в `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- финальный план находится в `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- операторские правила находятся в `docs/guides/MEMORY_INGESTION_OPERATIONS.md`;
- ingestion MVP уже имеет discovery state, issue queue, local/UNC path adapter, graph schema contract и команды;
- текущий parser baseline индексирует text-like файлы, а PDF/Office/images отправляет в issue queue до подключения реального parser/OCR backend.

Предварительный scope:
- подключить и протестировать Docling/equivalent для PDF/DOCX/XLSX;
- подключить Tika/LibreOffice fallback для DOC/XLS;
- подключить OCR backend `rus+eng` для scans/images;
- формализовать GLM-OCR cloud test profile для подготовленной non-sensitive выборки;
- расширить parser quality eval на реальных тестовых документах;
- уточнить Excel limits после тестовой эксплуатации.

Критерии готовности к старту:
- создан workflow-блок и task packets для parser/OCR интеграции;
- определен первый read-only source folder и учетная запись сервиса для доступа;
- подтвержден UNC/local path deployment model без mapped drives;
- подготовлена безопасная тестовая выборка PDF/Office/scans;
- согласовано, какие документы можно отправлять в cloud GLM-OCR на тестах.

## Later

### Graph runtime search

Graph schema bootstrapping и extraction-команды остаются подготовительным контуром. Возврат graph facts через `memory.search` не включен в MVP и требует отдельной стратегии индекса, прав, provenance и ранжирования.

### Claim/belief governance

`MemoryClaim`/`MemoryBelief` не входят в текущую MVP-схему и обычный путь `memory.remember`/`memory.search`. Возвращаться к этому слою стоит только после появления реальных противоречивых источников и процесса review.

### MLflow quality tracing

Черновой план MLflow архивирован. Контур качества можно вернуть в работу после стабилизации поиска по содержимому и отдельного решения по безопасной записи trace без секретов и необезличенных персональных данных.

### Внешний API системы памяти

Спроектировать и реализовать полноценный внешний API для доступа сторонних сервисов к системе памяти. На текущем этапе не реализуем.

Контекст:
- текущая память не является отдельным сетевым сервисом: это Django app `apps.memory` внутри основного приложения;
- текущий внешний для agent-runtime путь доступа — Django AI gateway tool `memory.search`;
- прямой доступ сторонних сервисов к `data/memory/indexes/`, safe corpus или таблицам памяти запрещен;
- решение о стабильном внешнем API должно быть оформлено отдельным ADR до реализации.

Предварительный scope:
- HTTP API contract для поиска, citations, health/status и, при необходимости, ingestion requests;
- service identity и auth model для machine-to-machine доступа;
- RBAC/scope translation для сервисных учетных записей;
- rate limits, quotas и request tracing;
- обязательный `MemoryAccessAudit` для всех retrieval calls;
- запрет выдачи raw snapshots, raw paths, original PII и secrets;
- versioning API и backward compatibility policy;
- integration guide для новых сервисов;
- smoke/security tests и deployment checks.

Критерии готовности к старту:
- утвержден ADR;
- понятен первый внешний потребитель API;
- определены allowed operations: только retrieval или retrieval + managed ingestion;
- выбран механизм auth: gateway token, service accounts, mTLS или другой вариант;
- описаны форматы ошибок, citations и audit trace.

## Blocked

- Нет заблокированных задач.
