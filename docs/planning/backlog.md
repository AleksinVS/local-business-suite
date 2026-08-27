# Backlog

Актуальная очередь работ. Завершенные задачи здесь не хранятся: после завершения они удаляются из backlog, а итоговые планы и workflow-артефакты остаются в `docs/planning/archive/` и `workflow/archive/`.

## Active

### Единый UX администрирования доступа

ADR-0040 принят. Пакеты 00a–00d и 01–03 реализованы: канонические сервисы записи,
privilege ceiling и self-assignment active superuser, резервный Django Admin,
staged contract write с межпроцессной блокировкой, доменные Board/memory write,
каталог и impact-редактор роли, поиск и компактная карточка источников.

Пользовательская приемка 2026-08-13 показала, что отдельные страницы остаются
лабиринтом. Пакеты 06–08 и уточнение ADR-0043 реализованы: одно окно
`/settings/access/`, шесть разрезов, левый редактор значения, правый инспектор
объекта, безопасное изменение участников и создание обычной роли, read-only
explain-адаптеры и адаптивная browser/e2e-приемка. Упрощение ролевой модели
заархивировано отдельно. В этом UX-блоке остаются общая read-only проекция
журнала и итоговая приемка всего направления перед архивированием.

Пакет 20 перевёл обычные продуктовые редакторы пользователя, роли, доски и групп
на одну команду `Сохранить` по ADR-0042. Отдельные preview/apply-процессы остались
только у AI `PendingAction`, резервного Django Admin и общих runtime-настроек.

Пакеты 21–24 устранили второй список пользователей и расхождение AD-состояния,
закрыли пустые principal в автоматической синхронизации, добавили копирование
плоской роли без участников/ACL и зафиксировали предложенную архитектуру будущей
аддитивной иерархии. Иерархия в runtime не включена. В активном направлении
остаются общая read-only проекция журнала и итоговая пользовательская приёмка.

Пакет 19 устранил бесконечное состояние загрузки при сохранении пользователя и
роли: длительные ingestion/reindex/FileHub worker отделены от access-lock, а
HTMX имеет ограничение ожидания и восстанавливает черновик. Следующий
технический шаг — устойчивый фазовый протокол для синхронных `accept/reject`
knowledge-файлов и удаления устаревшего индекса; до него этот редкий путь может
дать контролируемую просьбу повторить сохранение, но не бесконечную загрузку.

Контекст:

- план: `docs/planning/active/access-administration-ux-unification.md`;
- ADR: `docs/adr/ADR-0040-unified-access-administration-control-plane.md`;
- workflow: `workflow/active/access-administration-ux-unification/`.

### Канбан: дерево подразделений в фильтре и сворачиваемый ИИ-чат

Пакеты 01-04 и уточнения 06-08, 10 выполнены: медизделия стали листьями дерева, добавлены
выбор строк с Ctrl/клавиатурой, контекстное создание заявки и изменяемая ширина левой
панели. Визуальная доработка сделала дерево компактным, перенесла создание в строку изделия,
устранила конфликт изменяемой ширины с общим сворачиванием и добавила рекурсивное сворачивание
ветвей с восстановлением раскрытого состояния. Левая панель получила приоритет ширины, а правая
теперь занимает оставшееся пространство без перекрытия. Для постоянных PWA-профилей исправлен
бессрочный cache-first статических файлов: `pwa-v4` получает актуальные CSS/JS с сервера и использует
кэш только как офлайн-резерв. Профильный и полный наборы проверок были завершены
успешно до последнего уточнения. Пакет 11 обновляет форму новой заявки: безопасное
автодополнение, предзаполнение из дерева и учетной записи, отсутствие раннего назначения
исполнителя, необязательный заголовок и поиск по обоим номерам изделия. Пакет 11 технически
принят; ожидается пользовательская проверка перед архивированием блока.

Контекст:
- ADR: `docs/adr/ADR-0037-kanban-department-filter-and-collapsible-ai-sidebar.md`;
- активный план: `docs/planning/active/kanban-department-filter-ai-sidebar.md`;
- workflow package: `workflow/active/kanban-department-filter-ai-sidebar/`.

Следующее действие:
- владелец проверяет пользовательский результат;
- после явной приемки выполнить архивный пакет 09 и удалить блок из backlog.

### Миграция основного хранилища на PostgreSQL

Переход на одну PostgreSQL database выполнен в production 2026-08-18 после
двух dry-run, strict validation и freeze window. Smoke-проверки и владелец
подтвердили работу; rollback window закрыт после записи новых данных. Подробности:
`workflow/active/postgresql-primary-store-migration/EXECUTOR_REPORT.production-cutover.md`.
SQLite baseline-ветка `sqlite-legacy-2026-06-15` опубликована на `origin`.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0029-postgresql-primary-store-and-sqlite-fork.md`;
- проектный план находится в `docs/architecture/POSTGRESQL_PRIMARY_STORE_PLAN.md`;
- active planning находится в `docs/planning/active/postgresql-primary-store-migration.md`;
- runbook находится в `docs/deployment/POSTGRESQL_MIGRATION.md`;
- workflow package находится в `workflow/active/postgresql-primary-store-migration/`.

Оставшиеся действия:
- отключить старую backup Scheduled Task под `SYSTEM` и пересоздать её под
  dedicated backup identity с закрытым каталогом вне `data/` по
  `docs/deployment/POSTGRESQL_MIGRATION.md`;
- при необходимости создать отдельный standalone SQLite-репозиторий из `origin/sqlite-legacy-2026-06-15` (базовая ветка уже на remote);
- блок `memory-hybrid-knowledge-v05-alignment` (ADR-0030) разблокирован dev-cutover'ом, исполнен и заархивирован 2026-07-04; доводка — в блоке `memory-alignment-hardening` (см. `Next`);
- после backup-hardening и решения по SQLite перенести planning/workflow в архив
  и удалить этот блок из active backlog.

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

### Доводка памяти после ревью целевой архитектуры (memory-alignment-hardening)

Блок выравнивания памяти по ADR-0030 исполнен и заархивирован 2026-07-04. Ревью целевой архитектуры 2026-07-06 (дополнение в ADR-0030), ретроспектива блока, кросс-ревью находок параллельного kb-проекта, обсуждение паттерна «сверка на записи» (2026-07-07) и второй проход кросс-ревью (2026-07-13: потребитель сигнала `contradicts`, авто-снятие reconciler-issues, per-file пересчет очереди) оставили девять пробелов: LF-нормализация канона и `.gitattributes` (без них git-autocrlf на Windows ломает content-hash дисциплину), гарантия отсутствия петли `needs-reconcile`, синглтон `memory_reconcile`, канон-ориентированный обход reconciler с базисами из git (файлы в обход `memory.remember` сейчас невидимы, перенос файла молча пропускается, `--force` теряет базисы гарда и очереди), инструкция эмиссии `relations:` для семантического прохода и обновление входящих рёбер при `supersede` (словарь и материализатор есть, производителя рёбер нет), golden set `MemoryEvalCase` для проверяемых критериев возврата отложенных контуров, матрица восстановления в deployment-документации, чистка `ranking_profiles` и фильтра review-UI, протокол противоречия и команда `memory_impact` — детерминированный проверочный набор перед правкой канона (паттерн «сверка на записи», концепт §7.4).

Контекст:
- основание: `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md`, раздел «Требуемые действия», дополнения 2026-07-06, 2026-07-07 и 2026-07-13;
- остаточные риски: `workflow/archive/2026/memory-hybrid-knowledge-v05-alignment/RETROSPECTIVE.md`;
- активный план: `docs/planning/active/memory-alignment-hardening.md`;
- workflow package: `workflow/active/memory-alignment-hardening/` (3 task packets, порядок 01 -> 02/03).

Критерии готовности к старту выполнены: пакеты содержат точные имена файлов, моделей и шаги; блок готов к исполнению. Пакет 01 — рискованный (путь записи канона), требует независимой проверки субагентом.

### Внедрение архитектурных паттернов

Подготовлен отдельный planning/workflow-блок для постепенного внедрения прикладных паттернов из архитектурного анализа. Scope направлен на единые сценарии записи, безопасные AI-команды, единые политики доступа, переходники источников и надежные фоновые задачи.

Контекст:
- анализ паттернов находится в `docs/architecture/DESIGN_PATTERNS_REVIEW_2026-06-01.md`;
- активный план находится в `docs/planning/active/design-patterns-hardening-2026-06-01.md`;
- workflow package находится в `workflow/active/design-patterns-hardening-2026-06-01/`;
- связанные исправления по ревью находятся в `docs/planning/archive/2026/architecture-review-remediation-2026-06-01.md`.

Предварительный scope:
- свести write-сценарии UI, AI и management commands к доменным сервисам;
- оформить AI write tools как команды с подтверждением, audit и trace identifiers;
- усилить service identity и session ownership в AI gateway/MCP;
- унифицировать политики доступа и повторяемые выборки;
- закрепить `SourceAdapter`/`SourceObjectEnvelope` как границу памяти, аналитики и внешних источников;
- спроектировать job/outbox contract для ingestion, indexing, analytics recompute и external connectors;
- добавить idempotency keys, retry limits и ручной путь разбора ошибок.
- развязать `core → workorders` в `contract_store`/`forms` через реестр валидаторов (следствие разноса `json_utils`, п.11 блока 2026-07-04).

Критерии готовности к старту:
- пересекающиеся исправления архитектурного ревью 2026-07-04 завершены (блок исполнен и заархивирован 2026-07-07); часть scope уже закрыта — service identity gateway/MCP (п.05), ролевой write-path (п.01), — поэтому нужен ре-скоуп: вычесть сделанное;
- согласовано, какие write-сценарии входят в первый срез;
- определено, нужен ли ADR для изменения AI gateway/MCP identity model или production worker контура.

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

Полнотекстовый и векторный поиск по документу целиком реализованы. Следующий отдельный этап — перейти от документного результата к крупным разделам/листам/диапазонам строк без возврата старой модели `MemoryChunk`.

Очередность: ревью целевой архитектуры 2026-07-06 (ADR-0030, дополнение) рекомендует этот этап первым шагом качества поиска после блока `memory-alignment-hardening` — впереди graph runtime search и профилей ранжирования, потому что это единственный отложенный контур с гарантированным потребителем (длинные source_data-документы бьют по точности и токен-бюджету уже сейчас).

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
- обзор моделей-кандидатов глубокого слоя (openai/privacy-filter, GLiNER2-PII, Piiranha, Presidio+RU NER) — в `docs/architecture/PRIVACY_DEEP_LAYER_MODELS_REVIEW_2026-07-13.md`;
- связанный Settings Center план (реализован, принят) — в архиве: `docs/planning/archive/2026/settings-center-gui.md`.

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

### База проектных знаний для ИИ-агентов (project knowledge base, kb)

Спроектирована локальная система знаний о проекте для агентов-архитекторов и агентов-разработчиков (адаптация гибридной концепции управления знаниями): markdown-канон `docs/knowledge/` + производная SQLite-проекция (FTS5, граф рёбер, очередь), CLI `kb`, двухуровневый контур качества с сессией-уборщиком. Проект прошёл внутреннее ревью и перенос применимых находок ревью основной системы знаний (версия 0.5); исполнительная спецификация T0–T6 готова — DDL, алгоритмы и форматы заданы дословно, исполнение воспроизводимо любой моделью.

Контекст:
- проектный документ: `docs/architecture/project-knowledge-system-v0.1.md` (v0.9, Proposed);
- исполнительный план: `docs/planning/active/project-knowledge-system-mvp.md`;
- workflow-блок: `workflow/active/project-knowledge-base-mvp/` (6 task packets, готов к исполнению);
- базовая концепция: `docs/architecture/hybrid-knowledge-architecture-v0.5.md`.

Оставшееся действие:
- владельцу: решение о старте исполнения (ADR создаётся задачей T6 со статусом Proposed);
- исполнить пакеты 01–06 блока `project-knowledge-base-mvp` (T0–T6 плана); фаза 2 (наполнение, лимит 20–30 страниц + golden set) и фаза 3 (интеграция карты проекта) — отдельными задачами после приёмки MVP.

## Later

### Data store: реестр датасетов и capture/query (этапы 5а/5б ADR-0030)

Управляемый долг из `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md` (решение 7). Слой данных (append-only наблюдения) не реализован; в коде оставлены заглушки `apps/memory/data_store.py` и маркеры `DEBT(ADR-0030-5a)` / `DEBT(ADR-0030-5b)` (созданы исполненным блоком выравнивания, архив: `workflow/archive/2026/memory-hybrid-knowledge-v05-alignment/`).

Этап 5а — реестр датасетов и типизированный `capture`/`query`:
- дескриптор датасета = концепт-страница `type: Dataset` (шаблон — в `docs/planning/archive/2026/memory-hybrid-knowledge-v05-alignment.md`, раздел «Этапы 5а/5б»), реестр — производная проекция reconciler;
- fail-safe маршрутизация `memory.remember`: наблюдение пишется в data store только при совпадении со схемой зарегистрированного датасета, иначе — файл знания;
- идемпотентный `capture` (дедуп-ключ), аддитивная эволюция схемы через ревью;
- материализатор реестра выполняет только аддитивный DDL (`CREATE TABLE`, `ADD COLUMN` с NULL-допуском); `DROP`, смена типов и переименования — только вручную по runbook;
- первый потребитель — аналитический контур ADR-0008 (факты/метрики как первые датасеты);
- инсайты из данных — в вики с контрактом деривации `derived_from`/`as_of`/`window`.

Этап 5б — рефлексия-инициатор датасетов:
- детекция серий однотипных фактов в вики, предложение датасета через pending-страницу;
- миграция страниц-наблюдений в data store, старые страницы помечаются `superseded`.

Критерии старта: предусловие 5а (приемка этапов 1–4 блока выравнивания) выполнено 2026-07-04 — старт по решению владельца, рекомендуется после блока `memory-alignment-hardening`; 5б — после работоспособного 5а. Технология выбирается на старте 5а: после ADR-0029 естественный кандидат — append-only таблицы в основной PostgreSQL БД; DuckDB остается слоем OLAP-витрин.

### Профили гибридного ранжирования памяти

Реализация ADR-0016 отложена управляемо решением `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md` как архитектурный долг: в runtime остается один профиль по умолчанию (RRF-слияние FTS и вектора). Возврат к профилям — после того, как `python manage.py memory_eval` на golden set (suite `golden`, создается пакетом 02 блока `memory-alignment-hardening`) покажет измеримую пользу дифференциации профилей; без golden set критерий не срабатывает. Прежний план находится в `docs/planning/active/memory-hybrid-ranking-profiles-and-agent-prompts.md`, workflow package — в `workflow/active/memory-hybrid-ranking-profiles/`; при старте среза их нужно актуализировать против ADR-0030.

### Graph runtime search

Прежний LLM graph-extraction контур удален блоком выравнивания ADR-0030 (2026-07-04). Текущее состояние: словарь типов рёбер в `contracts/ai/memory_graph_schema.json`, валидатор `relations:` и детерминированный материализатор `MemoryKnowledgeEdge` реализованы; производителем рёбер назначается семантический проход рефлексии (пакет 03 блока `memory-alignment-hardening`). Включение graph-канала в `memory.search` — только после того, как в `MemoryKnowledgeEdge` накопятся реальные рёбра и `memory_eval` на golden set покажет пользу обхода соседей; потребуются стратегия прав внутри обхода и ранжирование (RRF-вес канала).

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
