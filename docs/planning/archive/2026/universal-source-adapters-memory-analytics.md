# Универсальные источники для памяти и аналитики

## Статус

Implemented in MVP; остается в active до приемки владельцем и возможного переноса в архив.

Архитектурное решение: `docs/adr/ADR-0018-universal-source-adapters-memory-analytics.md`.

Workflow-блок: `workflow/archive/2026/universal-source-adapters-memory-analytics/`.

## Цель

Сделать подключение внутренних модулей, файлов и внешних систем к памяти и аналитике единообразным. Канбан-доска, лист ожидания, файловые источники, API и будущие модули должны подключаться через адаптер источника, а не через прямые зависимости памяти от доменных моделей.

## Пользовательская ценность

- ИИ-бот сможет искать по заявкам, листу ожидания, файлам и API-объектам через общий механизм `memory.search` или доменные wrapper-инструменты.
- Аналитика сможет строить факты и метрики из тех же нормализованных объектов, что используются для поиска.
- Новые модули можно будет добавлять и удалять без переписывания памяти и аналитики.
- Privacy-поведение будет управляться настройками источника: PII по умолчанию выключено, для внешних систем включено.

## Принципы

1. Источник истины остается в домене: заявка в `apps.workorders`, запись ожидания в `apps.waiting_list`, файл на диске, внешний объект во внешней системе.
2. Память и аналитика хранят производные проекции, а не становятся владельцами бизнес-объекта.
3. Один адаптер источника формирует один нормализованный `SourceObjectEnvelope`.
4. Из envelope строятся две независимые проекции: memory projection и analytics projection.
5. Для динамических прав финальная проверка доступа выполняется адаптером источника.
6. PII-аудит выключен, если PII-профиль выключен.
7. Secret scanning всегда включен и не зависит от PII-профиля.
8. Универсальную event platform не вводить в MVP, но envelope должен быть совместим с будущим событийным режимом.

## Не цели

- Не объединять `MemorySource` и `AnalyticsSource` в одну таблицу в этом этапе.
- Не строить универсальный event bus/outbox как обязательную инфраструктуру MVP.
- Не добавлять отдельный внешний API источников.
- Не превращать все source_data в accepted knowledge.
- Не делать OCR изображений.
- Не хранить полный исходный объект в `MemorySearchDocument.metadata`.
- Не делать память зависимой от `WorkOrder`, `WaitingListEntry` или будущих доменных моделей.

## Целевая архитектура

```text
Источник
  internal django module / file / external API

  -> SourceAdapter
       discover/sync/get/render/check_access/extract_facts

  -> SourceObjectEnvelope
       identity, text, payload, relations, content_hash,
       privacy_profile, access_policy, provenance

  -> Memory projection
       MemorySourceObject, MemorySearchDocument, FTS5, vector,
       issues, review UI, citations

  -> Analytics projection
       AnalyticsContentObject, ExtractionPacket, AnalyticsFact,
       metrics, signals, diagnostics
```

## Privacy profiles

Дефолты:

| Source origin/kind | Privacy profile |
| --- | --- |
| internal django module | `pii_off` |
| internal local/UNC file | `pii_off` |
| external API | `pii_guarded` |
| email IMAP | `pii_guarded` |
| external file drop | `pii_guarded` |

Профили:

| Профиль | PII detect | Redact | Audit | Block |
| --- | --- | --- | --- | --- |
| `pii_off` | no | no | no | no |
| `pii_guarded` | yes | yes | yes | no |
| `pii_strict` | yes | yes | yes | yes |

Если `pii_off`, PII-аудит не создается. Секреты блокируются всегда.

## Access policy

Минимальные режимы:

| Режим | Назначение |
| --- | --- |
| `scope_tokens` | Статический доступ через токены |
| `acl_inherited` | Наследование ACL файла или внешнего объекта |
| `manual_mapping` | Ручной маппинг доступа внешней системы |
| `adapter_check` | Финальная проверка через доменный адаптер |

Для `workorders` и `waiting_list` использовать `adapter_check`, потому что доступ зависит от доменных правил и пользователя.

Если адаптер отсутствует, источник с `adapter_check` работает fail-closed: результат не возвращается в контекст.

## Этапы реализации

### Этап 1. Контракт и настройки

Задачи:

- принять ADR-0018;
- добавить `SourceObjectEnvelope` dataclass/schema;
- добавить `SourceAdapter` protocol;
- добавить adapter registry;
- добавить privacy profile resolver;
- добавить contract validation для новых source policy fields.

Проверки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.core.tests
```

### Этап 2. Memory projection из envelope

Задачи:

- добавить сервис `upsert_memory_projection_from_envelope`;
- сохранять `MemorySourceObject` и `MemorySearchDocument`;
- индексировать `text` в FTS/vector;
- поддержать `operation=delete`;
- применить secret gate всегда;
- применить PII pipeline только если privacy profile включен;
- перед выдачей source_data вызывать `adapter_check`, если он задан.

Проверки:

```bash
python manage.py test apps.memory.tests
python manage.py memory_reindex --corpus source_data --backend fulltext --dry-run
python manage.py memory_file_content_search_e2e
```

### Этап 3. Analytics projection из envelope

Задачи:

- добавить сервис `upsert_analytics_projection_from_envelope`;
- создавать или обновлять `AnalyticsContentObject`;
- формировать `AnalyticsExtractionPacket`;
- сохранять `AnalyticsFact`;
- поддержать tombstone/deactivate;
- не читать доменные таблицы напрямую из analytics без адаптера.

Проверки:

```bash
python manage.py test apps.analytics.tests
python manage.py analytics_extract_source --source-code <test-source> --dry-run
python manage.py analytics_recalculate_metrics --dry-run
```

### Этап 4. Адаптер `workorders`

Задачи:

- добавить адаптер заявок;
- включить в envelope номер, заголовок, описание, отдел, статус, приоритет, устройство, комментарии, переходы, закрытие и оценку;
- access policy: `adapter_check`;
- факты: создана заявка, смена статуса, закрытие, оценка, проблема по устройству;
- добавить команду sync/reindex для источника;
- добавить wrapper-инструмент `workorders.search` или подготовить контракт для него.

Проверки:

```bash
python manage.py test apps.workorders.tests apps.memory.tests apps.analytics.tests
```

### Этап 5. Адаптер `waiting_list`

Задачи:

- добавить адаптер листа ожидания;
- дефолтный privacy profile: `pii_off`, так как модуль внутренний;
- для безопасного поиска включить услугу, статус, CITO, даты, комментарий и обезличенный summary только если профиль требует;
- access policy: `adapter_check`;
- факты: запись создана, назначена, подтверждена, отменена, CITO, срок ожидания;
- проверить, что при `pii_off` не создается PII audit.

Проверки:

```bash
python manage.py test apps.waiting_list.tests apps.memory.tests apps.analytics.tests
```

### Этап 6. Reconcile, lifecycle и удаление модулей

Задачи:

- добавить общий sync/reconcile command по source_code и target;
- обработать missing adapter fail-closed;
- добавить tombstone для удаленных объектов;
- зафиксировать runtime-статусы source: enabled, disabled, missing_adapter, error;
- описать operator guide.

Проверки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
```

### Этап 7. E2E и документация

Задачи:

- e2e: заявка находится через source_data и доменный search wrapper;
- e2e: чужая заявка не возвращается при dynamic access check;
- e2e: лист ожидания индексируется без PII-аудита при `pii_off`;
- e2e: внешний тестовый source включает PII-аудит при `pii_guarded`;
- обновить `MEMORY_MVP_CURRENT_STATE`, `ANALYTICS_MODEL`, `MEMORY_USER_GUIDE` и operator docs.

Проверки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.analytics.tests apps.workorders.tests apps.waiting_list.tests apps.ai.tests
python manage.py memory_file_content_search_e2e
```

## Открытые вопросы

- Нужен ли отдельный пользовательский UI для управления source adapters или достаточно Settings Center на первом этапе?
- Нужен ли сразу `workorders.search` как AI-инструмент, или на первом срезе достаточно `memory.search` с source filter?
- Какой retention нужен для исторических source_data после удаления внутреннего модуля?
- Должны ли аналитические факты по листу ожидания хранить PII-free dimensions всегда, даже если PII profile выключен?

## Definition of Done

- ADR-0018 принят или обновлен по итогам ревью.
- Envelope/schema/protocol покрыты unit-тестами.
- Память и аналитика строят проекции из одного envelope.
- `workorders` и `waiting_list` подключены как adapters, а не как прямые зависимости памяти.
- PII defaults соответствуют решению: global off, external guarded.
- PII-аудит не создается при `pii_off`.
- Секреты блокируются независимо от PII.
- Доступ к source_data с `adapter_check` проверяется сервером перед выдачей.
- E2E покрывает поиск, доступ, privacy profile и аналитику.
- Документация, `.desc.json` и `PROJECT_STRUCTURE.yaml` обновлены.
