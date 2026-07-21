# ADR-0017: UI аудита и ревью проблем памяти и поискового индекса

## Статус

Accepted

## Дата

2026-05-27

## Контекст

Система памяти уже умеет:

- ставить проблемы загрузки и переиндексации в `MemoryIngestionIssue`;
- хранить техническую карточку поискового документа в `MemorySearchDocument`;
- писать аудит вызовов `memory.search` в `MemoryAccessAudit`;
- блокировать документы с секретами через `secret_blocked`;
- индексировать документы с PII и ставить их в очередь аудита через `pii_audit`;
- выполнять FTS5 и LanceDB поиск по знаниям и исходным файлам.

Сейчас операторская видимость частично есть в Django Admin, но этого недостаточно для нормального рабочего процесса:

- нет отдельной очереди ревью с приоритетами, назначением и безопасными действиями;
- нет экрана состояния поискового индекса по документам, источникам и корпусам;
- нет неизменяемого журнала действий ревьюера;
- трудно отличить принятое знание от исходных документов и технических проблем состояния индекса;
- админ-действия не объясняют последствия для FTS/vector индексов и reindex.

Нужен пользовательский интерфейс для администраторов, аудиторов памяти и операторов индекса.

## Решение

Создать отдельный рабочий UI для аудита и ревью памяти. Первый вариант строится на Django templates и HTMX в стиле существующего портала и Settings Center. Settings Center остается местом настройки правил, а новый UI является рабочим экраном обработки проблем.

Начальная маршрутизация:

```text
/memory/review/
  dashboard
  issues
  issues/<id>
  index
  index/<document_id>
  audit
```

Точный URL namespace можно уточнить при реализации, но UI должен принадлежать домену `apps.memory`, а не расширять `apps.settings_center` бизнес-логикой памяти.

### Основной источник очереди

В MVP не вводить постоянную универсальную модель `ReviewCase`.

Базовая очередь строится вокруг существующего `MemoryIngestionIssue`:

- `secret_blocked`;
- `pii_audit`;
- `partial_indexed`;
- `unsupported_format`;
- `encrypted_file`;
- `file_too_large`;
- `acl_unresolved`;
- parser/OCR timeout;
- schema и graph bootstrap проблемы.

Экран состояния индекса строится из `MemorySearchDocument`, `MemorySourceObject`, `MemoryIndexJob` и диагностик индексных хранилищ. Если проверка состояния индекса должна создать устойчивую задачу ревью, она создает или обновляет `MemoryIngestionIssue` с новым issue kind, например:

- `index_failed`;
- `index_stale`;
- `fts_missing`;
- `vector_missing`;
- `source_deleted_index_left`.

Такой подход проще, чем отдельная постоянная абстракция `ReviewCase`, и сохраняет одну основную очередь для операторов.

### Унифицированная проекция для UI

Чтобы UI не зависел от деталей каждой модели, selectors должны возвращать нормализованную проекцию очереди, рабочее имя `ReviewQueueItem`.

`ReviewQueueItem` не является Django model, не хранится в базе и не становится источником истины. Это read-only DTO для отображения очереди и доступных действий.

Рекомендуемые поля:

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

Источники проекции:

- `MemoryIngestionIssue` для основной очереди проблем;
- диагностика `MemorySearchDocument` для состояния индекса;
- `MemoryReviewAction` для истории действий;
- `MemoryAccessAudit` только как связанный безопасный контекст, без raw query.

Такой слой дает единый интерфейс очереди без миграции `ReviewCase` и без синхронизации двух статусов. Если позже появятся независимые процессы ревью с одинаковым жизненным циклом, `ReviewQueueItem` можно заменить или дополнить постоянной `MemoryReviewCase`.

### Журнал действий ревью

Добавить отдельную неизменяемую модель действий ревью, рабочее имя `MemoryReviewAction`.

Назначение:

- фиксировать кто, когда и что сделал;
- хранить безопасный комментарий ревьюера;
- сохранять старый и новый статус issue/search document;
- связывать действие с `MemoryIngestionIssue`, `MemorySearchDocument`, `MemorySourceObject`, `MemoryIndexJob` или `MemoryAccessAudit`;
- не хранить исходный секрет, полный извлеченный текст, необезличенную PII или raw query.

Рекомендуемые поля:

```text
actor
action
decision
issue
search_document
source_object
index_job
access_audit
before_state
after_state
safe_metadata
comment
created_at
```

Для удобства фильтрации допускается добавить прямые поля в `MemoryIngestionIssue`:

```text
assigned_to
reviewed_by
resolution_code
resolution_note
review_due_at
```

Если на старте нужно сократить миграции, assignment можно отложить, но журнал действий должен быть реализован в первом UI-срезе.

### Роли и права

Использовать серверные Django permissions и группы, без доверия к состоянию интерфейса.

Минимальные capabilities:

```text
memory.view_review_queue
memory.review_issues
memory.review_privacy_issues
memory.manage_search_index
memory.view_memory_access_audit
```

Роли:

- `superuser`: полный доступ;
- `memory_admin`: ревью issues, действия с индексом, просмотр audit;
- `memory_auditor`: ревью PII/audit issues и просмотр безопасных сведений;
- `memory_index_operator`: reindex/delete/retry без privacy-деталей;
- `memory_observer`: только чтение безопасной очереди.

Фильтрация по source/domain/scope должна выполняться на сервере. Пользователь не должен видеть source object или search document, если его роль и scope этого не позволяют.

### Безопасность данных

UI не должен показывать:

- raw secret values;
- полный извлеченный текст документа;
- необезличенную PII из issue metadata;
- raw query пользователя из `MemoryAccessAudit`;
- скрытые локальные или UNC пути пользователям без служебного права.

Для ревью показывать:

- тип срабатывания;
- detector id;
- confidence;
- безопасную позицию или фрагмент, если он уже безопасно сформирован загрузкой или переиндексацией;
- source, relative path и file metadata с учетом прав;
- document id, corpus type, index status, версии parser/embedding/index;
- ссылку на исходный объект или внешний DMS объект, если у пользователя есть право.

Для просмотра содержимого исходного файла нужен отдельный явный режим. Первый UI-срез не должен превращаться в просмотрщик документов и не должен хранить извлеченный текст в Django.

### Действия в UI

Для issue:

- acknowledge;
- assign;
- request expert review;
- resolve;
- ignore;
- reopen;
- добавить комментарий;
- создать reindex request;
- перейти к source object/search document.

Для privacy/security:

- `secret_blocked`: нельзя принудительно индексировать документ с секретом; разрешены resolve после исправления источника, request remediation, retry reindex после подтверждения;
- `pii_audit`: разрешены acknowledge/resolve/needs expert review, документ остается индексированным согласно ADR-0016.

Для индекса:

- dry-run reindex;
- enqueue reindex;
- delete stale index records;
- retry failed index;
- mark deleted document index as cleaned;
- открыть trace последней индексации или поиска, если он безопасен.

Все действия выполняются через сервисный слой `apps.memory`, а не через прямые изменения из view.

### Связь с поиском и ИИ-ботом

UI не меняет контракт `memory.search`. Он только помогает администратору понимать:

- какие документы не попали в FTS/vector;
- какие документы заблокированы из-за секретов;
- какие документы индексируются с PII audit issue;
- какие результаты поиска возвращались пользователям и по каким scope.

ИИ-бот может использовать этот UI косвенно через будущие админ-команды или обертки инструментов, но первый этап не добавляет публичный внешний API ревью.

## Рассмотренные альтернативы

### Оставить только Django Admin

Плюсы: уже есть список моделей и простые bulk actions.

Минусы: нет безопасного рабочего процесса, роли слишком грубые, слабая навигация между issue/source/index/audit, трудно объяснить последствия reindex/delete.

Решение: отклонено как основной UX, но Django Admin остается техническим fallback.

### Сделать отдельную SPA

Плюсы: потенциально богаче интерфейс.

Минусы: больше инфраструктуры и тестов, не соответствует текущему Django-template направлению портала, усложняет security review.

Решение: отложено. Первый UI делать через Django templates и HTMX.

### Ввести универсальную модель `MemoryReviewCase`

Плюсы: единая абстракция для всех будущих ревью.

Минусы: риск overengineering, дублирование `MemoryIngestionIssue`, новые миграции и правила синхронизации.

Решение: отклонено для MVP. Принятое направление — `ReviewQueueItem` как selector-level проекция без хранения в базе. Вернуться к `MemoryReviewCase` только если появятся процессы ревью, которые нельзя нормально выразить через `MemoryIngestionIssue`, `MemorySearchDocument` diagnostics и `MemoryReviewAction`.

### Хранить извлеченный текст в Django для удобства ревью

Плюсы: проще показывать фрагменты.

Минусы: противоречит текущей privacy-модели, увеличивает риск утечки секретов/PII, дублирует индексное хранилище.

Решение: отклонено. UI показывает безопасные метаданные и ссылки; просмотр содержимого требует отдельного явного решения.

## Последствия

Положительные:

- появляется понятная операторская очередь по памяти и поисковому индексу;
- действия ревьюера становятся воспроизводимыми и аудируемыми;
- secret/PII поведение из ADR-0016 получает видимый UI;
- состояние индекса перестает быть скрытой технической проблемой;
- UI получает единый список через `ReviewQueueItem` без преждевременной универсальной таблицы;
- архитектура не вводит лишнюю универсальную review-модель на старте.

Ограничения:

- нужно добавить модель `MemoryReviewAction` и, вероятно, поля assignment/resolution;
- selectors должны поддерживать стабильный контракт `ReviewQueueItem`;
- нужен аккуратный permission model для privacy и index actions;
- просмотр содержимого документов остается отдельным решением;
- часть проблем состояния индекса потребует новых `IssueKind` и диагностик переиндексации.

## Проверки реализации

- unit-тесты сервисов ревью и permission-фильтров;
- unit-тесты формирования `ReviewQueueItem` из issue и index diagnostics;
- unit-тесты журнала действий без raw secret/PII/raw query;
- Django Client e2e: очередь issue -> detail -> action -> audit log;
- Django Client e2e: состояние индекса -> enqueue reindex/delete stale -> журнал действий;
- проверка, что пользователь без прав не видит чужие source objects и audit;
- `python manage.py check`;
- `python manage.py validate_architecture_contracts`;
- `python manage.py test apps.memory.tests apps.settings_center.tests apps.ai.tests`.
