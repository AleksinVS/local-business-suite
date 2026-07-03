# Backlog

Актуальная очередь работ. Завершенные задачи здесь не хранятся: после завершения они удаляются из backlog, а итоговые планы и workflow-артефакты остаются в `docs/planning/archive/` и `workflow/archive/`.

## Active

### Миграция основного хранилища на PostgreSQL

Создан проектный и исполнительный контур для перехода основного репозитория с текущего SQLite-разделения на одну PostgreSQL database. Кодовый срез миграции реализован: настройки PostgreSQL, единый `default` alias, восстановление внутренних FK, команды export/import/validate, PostgreSQL full-text backend и database queue backend. SQLite-вариант зафиксирован локальной веткой `sqlite-legacy-2026-06-15` и должен быть вынесен в отдельный удаленный fork/ветку.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0029-postgresql-primary-store-and-sqlite-fork.md`;
- проектный план находится в `docs/architecture/POSTGRESQL_PRIMARY_STORE_PLAN.md`;
- active planning находится в `docs/planning/active/postgresql-primary-store-migration.md`;
- runbook находится в `docs/deployment/POSTGRESQL_MIGRATION.md`;
- workflow package находится в `workflow/active/postgresql-primary-store-migration/`.

Оставшееся действие:
- создать удаленный SQLite-fork из `sqlite-legacy-2026-06-15`;
- провести migration dry-run на копии реальных runtime SQLite-файлов;
- провести cutover и cleanup по `workflow/active/postgresql-primary-store-migration/task-packets/06-cutover-verification-and-cleanup.json`;
- после приемки перенести planning/workflow в архив и удалить этот блок из active backlog.

### Разработка самописного AG-UI ИИ-чата

Первый срез основного самописного ИИ-чата в режиме `LOCAL_BUSINESS_AI_UI_DRIVER=native` реализован. Перенесены полезные решения из CopilotKit reference: новый чат, AG-UI stream reducer, tool trace, UI-команды, page context bridge, сохранение истории, ошибки и e2e. Task packet `05-sidebar-history-model-and-clear-parity` выполнен: боковая панель восстанавливает историю, показывает времена сообщений, поддерживает выбор модели, очистку и переход в полный чат.

Контекст:
- основной целевой UI: самописный AG-UI-compatible чат;
- архитектурное решение находится в `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- проектный план находится в `docs/architecture/NATIVE_AG_UI_CHAT_DEVELOPMENT_PLAN.md`;
- активный план находится в `docs/planning/active/native-ag-ui-chat-development.md`;
- workflow package находится в `workflow/active/native-ag-ui-chat-development/`.

Оставшееся действие:
- реализовать `workflow/active/native-ag-ui-chat-development/task-packets/06-native-full-page-session-management.json`;
- реализовать `workflow/active/native-ag-ui-chat-development/task-packets/07-native-rich-input-markdown-commands-attachments.json`;
- выполнить `workflow/active/native-ag-ui-chat-development/task-packets/08-native-ux-parity-e2e-acceptance.json`;
- отдельно согласовать, обновлять ли `@ag-ui/client` с `0.0.55` до `0.0.57`;
- проверить `legacy`, `copilotkit`, `native` smoke перед слиянием;
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

### Разработка ИИ-чата в режиме CopilotKit UI

Создан проектный и исполнительный контур для доведения CopilotKit-варианта ИИ-чата до production candidate в основном Django UI. Первый runtime hardening срез реализован: новый CopilotKit thread, основной вход `/ai/chat/` на CopilotKit-страницу, реактивный page context, AG-UI `RUN_ERROR` при отсутствующем LLM key, server-side нормализация UI-команд и e2e smoke для нового чата.

Контекст:
- целевой режим запуска: `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit`;
- архитектурное решение CopilotKit/AG-UI находится в `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- архитектурное решение по общей protocol foundation находится в `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- проектный план находится в `docs/architecture/COPILOTKIT_AI_UI_CHAT_DEVELOPMENT_PLAN.md`;
- активный план находится в `docs/planning/active/copilotkit-ai-ui-chat-development.md`;
- workflow package находится в `workflow/active/copilotkit-ai-ui-chat-development/`.

Оставшееся действие:
- проверить prompt/response сценарий при настроенном LLM API key;
- проверить reverse proxy `/copilotkit` и SSE timeout на целевом deployment;
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

### Версионируемая основа AI UI протоколов

Первый реализационный срез общей основы выполнен в отдельной ветке. Теперь два варианта интерфейса могут развиваться поверх общего слоя: самописный AG-UI-compatible UI как основной целевой чат и CopilotKit/AG-UI как равноправный драйвер/референс. Вынесены actor/session context, подпись, UI-команды, protocol metadata и выбор UI-драйвера.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- проектный план находится в `docs/architecture/AI_UI_PROTOCOL_FOUNDATION_PLAN.md`;
- активный план находится в `docs/planning/active/ai-ui-protocol-foundation.md`;
- workflow package находится в `workflow/active/ai-ui-protocol-foundation/`.

Оставшееся действие:
- выполнить полный e2e для `legacy`, `copilotkit` и `native` после перезапуска сервисов с нужными env;
- при backend-изменениях AG-UI контура проверять актуальность `@ag-ui/client`/`agui_profile` и по умолчанию только предупреждать о новой версии без обновления зависимостей;
- проверить reverse proxy и timeout на целевом deployment;
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

### CopilotKit и AG-UI в основном Django UI

Первый рабочий срез добавлен в отдельной ветке: AG-UI endpoint, CopilotKit Runtime service, React-остров в левой AI-панели и feature flag. Локальный e2e выполнен в режиме CopilotKit и fallback-режиме. До включения пилота нужны проверка reverse proxy на целевом deployment и приемка владельцем.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- проектный план находится в `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`;
- активный план находится в `docs/planning/active/copilotkit-ag-ui-integration.md`;
- workflow package находится в `workflow/active/copilotkit-ag-ui-integration/`;
- операционный guide находится в `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md`;
- deployment note находится в `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`.

Статус реализации:
- добавлен `/ag-ui` в `services.agent_runtime` без изменения текущих `/chat` и `/chat/stream`;
- добавлен `services/copilot_runtime` как server-side Copilot Runtime service;
- CopilotKit встроен как React island за `LOCAL_BUSINESS_COPILOTKIT_ENABLED`;
- actor/session context подписывается Django и проверяется agent runtime;
- `ui.open_right_panel` идет через AG-UI state/custom event и существующий безопасный правый сайдбар.
- Playwright e2e покрывает CopilotKit-enabled режим и fallback-режим текущего HTMX sidebar.

Оставшееся действие:
- проверить reverse proxy `/copilotkit` на целевом deployment;
- после приемки владельцем перенести planning/workflow в архив и удалить этот блок из active backlog.

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

### Приведение системы памяти к архитектуре hybrid-knowledge v0.5

Принято решение выровнять ядро памяти с целевой архитектурой гибридной системы знаний: файл знания становится каноном (frontmatter авторитетен), запись идет напрямую с pull-reconciler вместо push-очередей, ревизии и ревью переходят на git-примитив, LLM graph extraction заменяется объявленными рёбрами из frontmatter, автоупорядочивание файлов выносится в отдельное замороженное приложение, вводится data store с дескрипторами датасетов.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md`;
- целевой концепт находится в `docs/architecture/hybrid-knowledge-architecture-v0.5.md`;
- текущая рабочая граница описана в `docs/architecture/MEMORY_MVP_CURRENT_STATE.md`;
- активный план находится в `docs/planning/active/memory-hybrid-knowledge-v05-alignment.md`;
- workflow package находится в `workflow/active/memory-hybrid-knowledge-v05-alignment/` (8 task packets).

Scope блока (см. план):
- 01: канон в файлах, кроссплатформенная блокировка записи, `memory_reconcile`, двойная сверка и откат;
- 02: прямая запись `memory.remember`, единая таблица-очередь с DLQ, `index.md`;
- 03: кандидатство и ревью через pending-страницы поверх git, `log.md` из истории;
- 04: вынос автоупорядочивания файлов в `apps.filehub` и заморозка;
- 05: удаление graph-extraction контура, словарь типов рёбер, материализатор;
- 06: один профиль ранжирования RRF;
- 07: заглушки и DEBT-маркеры этапов data store 5а/5б;
- 08: документация, e2e acceptance, Definition of Done.

Критерии готовности к старту выполнены: план и workflow-блок созданы, порядок миграции и откат описаны в пакетах 01/02, имя отдельного приложения (`apps.filehub`) определено. Блок готов к исполнению; этапы data store 5а/5б вынесены в отдельную debt-запись в `Later`.

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

### Data store: реестр датасетов и capture/query (этапы 5а/5б ADR-0030)

Управляемый долг из `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md` (решение 7). Слой данных (append-only наблюдения) не реализуется в блоке выравнивания памяти; в коде остаются заглушки `apps/memory/data_store.py` и маркеры `DEBT(ADR-0030-5a)` / `DEBT(ADR-0030-5b)` (создаются task packet `07-data-store-debt-stubs`).

Этап 5а — реестр датасетов и типизированный `capture`/`query`:
- дескриптор датасета = концепт-страница `type: Dataset` (шаблон — в `docs/planning/active/memory-hybrid-knowledge-v05-alignment.md`), реестр — производная проекция reconciler;
- fail-safe маршрутизация `memory.remember`: наблюдение пишется в data store только при совпадении со схемой зарегистрированного датасета, иначе — файл знания;
- идемпотентный `capture` (дедуп-ключ), аддитивная эволюция схемы через ревью;
- первый потребитель — аналитический контур ADR-0008 (факты/метрики как первые датасеты);
- инсайты из данных — в вики с контрактом деривации `derived_from`/`as_of`/`window`.

Этап 5б — рефлексия-инициатор датасетов:
- детекция серий однотипных фактов в вики, предложение датасета через pending-страницу;
- миграция страниц-наблюдений в data store, старые страницы помечаются `superseded`.

Критерии старта: 5а — после приемки этапов 1–4 блока `memory-hybrid-knowledge-v05-alignment`; 5б — после работоспособного 5а. Технология (SQLite vs DuckDB) выбирается на старте 5а.

### Профили гибридного ранжирования памяти

Реализация ADR-0016 отложена управляемо решением `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md` как архитектурный долг: в runtime остается один профиль по умолчанию (RRF-слияние FTS и вектора). Возврат к профилям — после того, как `python manage.py memory_eval` на реальном корпусе покажет измеримую пользу дифференциации профилей. Прежний план находится в `docs/planning/active/memory-hybrid-ranking-profiles-and-agent-prompts.md`, workflow package — в `workflow/active/memory-hybrid-ranking-profiles/`; при старте среза их нужно актуализировать против ADR-0030.

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
