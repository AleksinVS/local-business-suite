# UI аудита и ревью проблем памяти и поискового индекса

## Статус

Implemented; owner review pending.

Архитектурное решение: `docs/adr/ADR-0017-memory-audit-review-ui.md` со статусом `Accepted`.

## Цель

Сделать рабочий интерфейс для администраторов и аудиторов памяти:

- видеть проблемы загрузки, переиндексации, privacy и ACL;
- понимать состояние FTS/vector индекса по знаниям и исходным файлам;
- безопасно обрабатывать `secret_blocked`, `pii_audit`, `partial_indexed`, `acl_unresolved` и проблемы состояния индекса;
- запускать понятные действия: acknowledge, assign, resolve, ignore, retry, reindex, delete stale index;
- сохранять журнал действий без секретов, необезличенной PII и raw query.

## Не цели

- Не реализовывать отдельную SPA в первом срезе.
- Не заменять Settings Center: настройки остаются там, рабочее ревью живет в домене памяти.
- Не хранить полный извлеченный текст документов в Django.
- Не показывать raw secret values, raw PII или raw query.
- Не разрешать принудительное индексирование документа, где найден секрет.
- Не вводить постоянную универсальную модель `ReviewCase` в MVP; для UI использовать только нормализованную selector-level проекцию `ReviewQueueItem`.
- Не менять внешний контракт `memory.search`.

## Текущая база

Уже есть:

- `MemoryIngestionIssue` с `issue_kind`, `status`, `severity`, `source`, `source_object`, `run`, `metadata`;
- `MemorySearchDocument` с `document_id`, `corpus_type`, `object_kind`, `body_hash`, `index_status`, `indexed_at`, `metadata`;
- `MemoryAccessAudit` для вызовов `memory.search`;
- Django Admin для базового просмотра и bulk actions;
- reindex поведение для secret/PII согласно ADR-0016.

Недостатки:

- нет специализированной очереди ревью;
- нет безопасного журнала действий для решений ревьюера;
- нет UI состояния индекса;
- нет роли `memory_auditor`/`memory_index_operator`;
- нет явного пути от issue к source object, search document, reindex и audit trace.

## Пользователи и роли

Минимальные роли:

| Роль | Назначение |
| --- | --- |
| `memory_admin` | Полное ревью issues, действия с индексом, просмотр audit |
| `memory_auditor` | Privacy/audit review, PII audit, безопасный просмотр issue metadata |
| `memory_index_operator` | Reindex/delete stale/retry failed index без privacy-деталей |
| `memory_observer` | Только чтение безопасной очереди |
| `superuser` | Полный доступ |

Минимальные capabilities:

```text
memory.view_review_queue
memory.review_issues
memory.review_privacy_issues
memory.manage_search_index
memory.view_memory_access_audit
```

Фильтрация по source/domain/scope выполняется сервером.

## Экраны

### Сводка

Показывает:

- счетчики открытых issues по severity и issue kind;
- количество документов по `index_status`;
- количество failed/stale/missing FTS/vector документов;
- последние `secret_blocked` и `pii_audit`;
- последние reindex jobs;
- ссылки на очереди и фильтры.

### Очередь issues

Фильтры:

- status;
- severity;
- issue kind;
- source/domain;
- corpus type;
- assigned_to;
- created date;
- source object extension;
- только blocker/privacy/проблемы состояния индекса.

Колонки:

- severity;
- issue kind;
- status;
- source;
- source object;
- linked search document status;
- created/updated;
- assigned_to;
- безопасное сообщение.

Массовые действия разрешены только там, где они безопасны: acknowledge, assign, request expert review. Resolve/ignore для privacy и secret issues лучше делать из карточки.

### Карточка issue

Показывает:

- issue summary;
- source/source object metadata;
- linked `MemorySearchDocument`, если есть;
- run/job context;
- безопасные detector metadata;
- историю `MemoryReviewAction`;
- доступные действия по правам пользователя;
- предупреждение для `source_data`: это исходный документ, а не принятое знание.

### Состояние поискового индекса

Фильтры:

- corpus type: `knowledge`, `source_data`;
- object kind;
- index status;
- source/domain;
- indexed_at range;
- parser/extraction/embedding version;
- stale reason;
- missing FTS;
- missing vector;
- deleted source with live index.

Колонки:

- document id;
- corpus/object kind;
- target;
- source;
- index status;
- indexed_at;
- body_hash/content_hash;
- FTS/vector status;
- last issue;
- action menu.

### Карточка search document

Показывает:

- technical metadata;
- source refs;
- scope/sensitivity summary;
- index versions;
- last indexed time;
- related issues;
- related reindex jobs;
- related access audit entries by returned document id, without raw query.

Действия:

- dry-run reindex;
- enqueue reindex;
- retry failed index;
- delete stale FTS/vector rows;
- mark deleted index cleaned;
- create issue.

### Журнал аудита

Показывает:

- `MemoryReviewAction`;
- связанные issue/document/source/job/audit ids;
- actor;
- action/decision;
- before/after state;
- safe metadata;
- comment;
- created_at.

`MemoryAccessAudit` показывается отдельно или как связанный контекст. Raw query не выводится.

## Данные и миграции

Рекомендуемый MVP:

1. Оставить `MemoryIngestionIssue` основной очередью.
2. Добавить `MemoryReviewAction` как неизменяемый журнал действий.
3. Добавить в `MemoryIngestionIssue` только необходимые поля для фильтрации и назначения:

```text
assigned_to
reviewed_by
resolution_code
resolution_note
review_due_at
```

4. Добавить новые issue kinds для состояния индекса только после реализации диагностики:

```text
index_failed
index_stale
fts_missing
vector_missing
source_deleted_index_left
```

5. Не хранить полный извлеченный текст в новых таблицах.

6. Не добавлять миграцию и таблицу `ReviewCase` в MVP.

Если при реализации выяснится, что состояние индекса и аудит доступа требуют независимых процессов ревью, вернуться к варианту `MemoryReviewCase` отдельным обновлением ADR.

## Унифицированная проекция очереди

Для единого отображения очереди selectors должны возвращать `ReviewQueueItem`. Это не Django model и не таблица, а read-only структура для UI.

Минимальные поля:

```text
kind
stable_key
source_model
source_pk
severity
status
title
safe_summary
source
target_type
target_id
assigned_to
created_at
updated_at
available_actions
links
```

Принцип:

- источник истины для проблем — `MemoryIngestionIssue`;
- источник истины для состояния индекса — `MemorySearchDocument` и диагностики FTS/vector;
- история действий — `MemoryReviewAction`;
- `ReviewQueueItem` только собирает эти сведения для списка и карточек;
- статусы не дублируются между `ReviewQueueItem` и доменными моделями.

## Сервисный слой

Нужны сервисы в `apps.memory`:

- selectors для очереди ревью, состояния индекса и `ReviewQueueItem`;
- permission-фильтры;
- action services для issue transitions;
- action services для reindex/delete stale;
- writer неизменяемого журнала действий;
- safe metadata serializer;
- diagnostics для FTS/vector presence.

Views не должны менять модели напрямую.

## UX-ограничения

- Экран должен быть плотным операторским интерфейсом, а не landing page.
- Использовать существующий layout портала.
- Не вкладывать карточки в карточки.
- Для массовых операций показывать количество затронутых объектов.
- Опасные действия выполнять через подтверждение POST.
- Кнопки действий должны быть недоступны без права, но основная защита обязана быть на сервере.
- `secret_blocked` всегда показывает запрет на force-index.

## План реализации

1. Использовать ADR-0017 как принятую архитектурную базу.
2. Уточнить модель и миграции: `MemoryReviewAction`, assignment/resolution fields, новые `IssueKind`, без таблицы `ReviewCase`.
3. Реализовать selectors и permission policy.
4. Реализовать `ReviewQueueItem`, сервисы действий и журнал действий.
5. Реализовать dashboard, issue queue, issue detail.
6. Реализовать список/карточку состояния индекса и действия reindex/delete stale.
7. Реализовать audit log.
8. Добавить Django Client e2e и unit-тесты.
9. Обновить пользовательскую/операционную документацию.

## Исполнительный пакет

Workflow-блок:

```text
workflow/active/memory-audit-review-ui/
```

Task packets:

- `01-adr-and-model-contract`;
- `02-review-selectors-and-services`;
- `03-review-ui-issue-queue`;
- `04-index-health-ui-and-actions`;
- `05-permissions-audit-and-safety`;
- `06-e2e-docs-and-handoff`.

## Acceptance checks

Документация готова к реализации, если:

- ADR принят и описывает модель очереди, роли, журнал действий, `ReviewQueueItem` и запреты на raw secret/PII;
- active plan описывает экраны, действия, данные и этапы;
- workflow packets имеют read/write scope и проверки;
- backlog указывает на активный план;
- структура проекта обновлена.

Будущая реализация готова, если:

- пользователь с `memory_admin` видит сводку, очередь issues, карточку issue, состояние индекса и журнал аудита;
- пользователь без прав получает 403 и не видит чужие source objects;
- `secret_blocked` нельзя force-index через UI;
- `pii_audit` индексированный документ можно acknowledged/resolved с audit action;
- index operator может поставить reindex и удалить stale FTS/vector rows;
- каждое действие пишет `MemoryReviewAction`;
- очередь UI строится через `ReviewQueueItem`, но источник истины остается в доменных моделях;
- журнал не содержит raw secret, raw PII, full extracted text или raw query;
- e2e покрывает ревью issue и действие по состоянию индекса.

Команды проверки будущей реализации:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.settings_center.tests apps.ai.tests
python manage.py memory_file_content_search_e2e
```

## Implementation result

Реализовано 2026-05-27:

- добавлена модель `MemoryReviewAction` и поля назначения/резолюции в `MemoryIngestionIssue`;
- постоянная `ReviewCase` не добавлялась, очередь UI строится через read-only `ReviewQueueItem`;
- добавлены selectors, safe serializer и сервисы действий ревью;
- добавлен UI `/memory/review/`: сводка, issues, карточка issue, индекс, карточка search document, журнал;
- добавлены роли/capabilities через permissions и группы `memory_admin`, `memory_auditor`, `memory_index_operator`, `memory_observer`;
- добавлены tests для доступа, projection, issue review и index actions;
- обновлены operator/user guides.

Фактические проверки записаны в `workflow/active/memory-audit-review-ui/TASK_ACCEPTANCE.memory-audit-review-ui.md`.
