# ADR-0018: Универсальные источники для памяти и аналитики

## Статус

Accepted

## Дата

2026-05-28

## Контекст

Система должна поддерживать подключаемые доменные модули и внешние источники без переписывания памяти, поиска и аналитики. Канбан-доска, лист ожидания, файлы, внешние API и будущие модули должны рассматриваться как равноправные источники.

Текущая база уже содержит два близких, но независимых контура:

- память: `MemorySource`, `MemorySourceObject`, `MemorySearchDocument`, FTS5/vector search, source_data/knowledge;
- аналитика: `AnalyticsSource`, `AnalyticsContentObject`, `AnalyticsExtractionPacket`, `AnalyticsFact`, метрики и сигналы.

Если память будет напрямую знать про `WorkOrder`, `WaitingListEntry` или будущие модели, система быстро станет хрупкой: удаление или замена модуля потребует менять память, аналитику, права и индексирование. Нужен общий контракт источника, который отделяет доменную модель от производных проекций памяти и аналитики.

Отдельно нужно учесть privacy-политику. PII-ограничения должны быть параметрическими:

- по умолчанию PII-контроль выключен;
- для внешних систем PII-контроль включен дефолтом;
- если PII-контроль выключен, выключены детекция, маскирование, блокировка и PII-аудит;
- сканирование секретов не является PII-контролем и всегда остается включенным.

## Решение

Ввести универсальный контракт источника на уровне адаптера и нормализованного envelope, не вводя в MVP отдельную универсальную платформу событий.

Целевая схема MVP:

```text
Внутренний модуль / файл / внешний API
  -> SourceAdapter
  -> SourceObjectEnvelope
  -> Memory projection
  -> Analytics projection
```

Память и аналитика не должны напрямую зависеть от конкретных Django-моделей бизнес-модулей. Модуль сам поставляет адаптер, который:

- объявляет источник и типы объектов;
- формирует нормализованный envelope текущего состояния объекта;
- указывает policy-поля: sensitivity, privacy profile, retention, access policy;
- рендерит безопасный текст для поиска;
- отдает аналитические факты или входные данные для извлечения фактов;
- проверяет доступ к объекту, если права динамические;
- обрабатывает tombstone/delete.

### SourceObjectEnvelope

Минимальная форма envelope:

```json
{
  "schema_version": "source-object-envelope-v1",
  "envelope_id": "workorders:workorder:123:sha256...",
  "source_code": "workorders",
  "source_origin": "internal",
  "source_kind": "django_model",
  "domain": "workorders",
  "object_type": "workorder",
  "object_id": "123",
  "operation": "upsert",
  "title": "Заявка 123",
  "text": "Безопасный текст для поиска",
  "payload": {},
  "relations": [],
  "content_hash": "sha256...",
  "previous_content_hash": "",
  "source_updated_at": "2026-05-28T12:00:00+03:00",
  "source_sequence": null,
  "sensitivity": "internal",
  "privacy_profile": "pii_off",
  "access_policy": {
    "mode": "adapter_check",
    "policy_ref": "workorders.visible",
    "scope_tokens": ["org:default"]
  },
  "analytics": {
    "enabled": true,
    "fact_candidates": []
  },
  "provenance": {
    "adapter": "workorders",
    "adapter_version": "v1",
    "generated_at": "2026-05-28T12:00:01+03:00"
  }
}
```

`text` используется для FTS/vector индекса. `payload` хранит только нормализованные поля, разрешенные политикой источника. Полный исходный объект остается в source of truth: Django-модуле, файле или внешней системе.

### Privacy profiles

Базовые профили:

```json
{
  "pii_off": {
    "enabled": false,
    "detect": false,
    "redact_before_index": false,
    "audit": false,
    "block": false
  },
  "pii_guarded": {
    "enabled": true,
    "detect": true,
    "redact_before_index": true,
    "audit": true,
    "block": false
  },
  "pii_strict": {
    "enabled": true,
    "detect": true,
    "redact_before_index": true,
    "audit": true,
    "block": true
  }
}
```

Дефолты по origin/source kind:

| Источник | Дефолт |
| --- | --- |
| `internal` / `django_model` | `pii_off` |
| `internal` / `local_path` | `pii_off` |
| `internal` / `unc_path` | `pii_off` |
| `external` / `external_api` | `pii_guarded` |
| `external` / `email_imap` | `pii_guarded` |
| `external` / `file_drop` | `pii_guarded` |

Явная настройка источника может переопределить дефолт. Если профиль `pii_off`, PII-аудит тоже не создается.

Секреты обрабатываются отдельной политикой: credential material всегда блокируется перед индексированием и записью в audit/metadata.

### Access policy

Для внутренних модулей с динамическими правами используется `adapter_check`:

```json
{
  "mode": "adapter_check",
  "policy_ref": "workorders.visible",
  "scope_tokens": ["org:default"]
}
```

`scope_tokens` могут применяться как предварительный фильтр, но финальная выдача результата должна вызвать адаптер источника. Это нужно для модулей, где доступ зависит от автора, исполнителя, доски, статуса или иных доменных правил.

Для файлов и внешних API допустимы режимы:

- `scope_tokens` - статическая проверка через токены;
- `acl_inherited` - права наследуются из ACL;
- `manual_mapping` - права заданы в настройках источника;
- `adapter_check` - финальную проверку выполняет адаптер.

Если адаптер недоступен, источник с `adapter_check` работает fail-closed: результаты не выдаются в контекст, пока источник не переведен в архивный режим с явным правилом доступа.

### Memory projection

Память строит из envelope:

- `MemorySource`;
- `MemorySourceObject`;
- `MemorySearchDocument` с `corpus_type=source_data`;
- FTS5/vector записи;
- `MemoryIngestionIssue` для проблем DLP, секретов, доступа, формата, индекса.

`source_data` остается исходным объектом, а не принятым знанием. Для превращения повторяющихся случаев в `knowledge` нужен отдельный review/reflection pipeline.

### Analytics projection

Аналитика строит из того же envelope:

- `AnalyticsSource`;
- `AnalyticsContentObject`;
- `AnalyticsExtractionPacket`;
- `AnalyticsFact`;
- метрики, сигналы, диагностические кейсы.

Принцип: extract once, derive many. Один нормализованный объект источника должен быть пригоден и для поиска, и для аналитики, но память и аналитика сохраняют свои модели и жизненные циклы.

### Не вводить event platform в MVP

MVP использует snapshot/envelope sync:

```text
adapter.iter_changed_objects(watermark)
  -> envelope
  -> upsert/delete projections
```

Не вводить в этом этапе отдельный event bus/outbox как обязательный слой. Это снижает сложность, но envelope резервирует поля `source_sequence`, `previous_content_hash`, `operation` и `provenance`, чтобы позже добавить event-driven режим.

Доменные модули, где история важна, должны использовать собственный audit/transition log уже сейчас. Канбан использует `WorkOrderTransitionLog`, лист ожидания использует `WaitingListAuditLog`.

## Рассмотренные альтернативы

### Память напрямую знает про каждый модуль

Плюсы:

- быстрее реализовать первый модуль;
- меньше общего слоя.

Минусы:

- память и аналитика становятся зависимыми от конкретных моделей;
- удаление модуля ломает поиск или требует ручных cleanup;
- права доступа размазываются между доменами;
- будущие источники будут копировать одинаковую логику.

Отклонено.

### Единая таблица Source для памяти и аналитики

Плюсы:

- единое место регистрации источников;
- меньше дублирования на уровне настроек.

Минусы:

- потребуется заметная миграция уже работающих `MemorySource` и `AnalyticsSource`;
- память и аналитика имеют разные runtime-задачи и статусы;
- риск смешать поисковую и аналитическую ответственность.

Откладывается. В MVP общий контракт находится на уровне envelope и адаптера, а не общей таблицы.

### Универсальная платформа событий сразу

Плюсы:

- лучшая свежесть;
- единая подписка для памяти, аналитики, уведомлений и интеграций;
- удобный replay событий.

Минусы:

- больше инфраструктуры: outbox, consumer jobs, retry, dead letter, порядок событий, версии схем;
- сложнее эксплуатация и тестирование;
- для текущей задачи поиска и базовой аналитики достаточно snapshot/reindex;
- повышается риск недоделанного центрального слоя.

Откладывается. Архитектура должна быть совместима с future event mode, но не должна зависеть от него в MVP.

### Полный CloudEvents/PROV стандарт

Плюсы:

- стандартизированные поля событий и происхождения данных;
- проще объяснять интеграционный контракт.

Минусы:

- избыточно для внутреннего MVP;
- потребует адаптации терминов к существующим моделям.

Откладывается. Envelope заимствует идеи `source`, `type`, `subject`, `data`, `provenance`, но не требует полной совместимости со стандартами.

## Последствия

Положительные:

- новые модули подключаются через адаптер, без изменений в ядре памяти и аналитики;
- канбан, лист ожидания, файлы и API становятся равноправными источниками;
- PII-поведение управляется настройками источника;
- поиск и аналитика используют один нормализованный вход;
- удаление модуля можно обработать fail-closed и архивированием проекций;
- сохраняется путь к future event-driven архитектуре.

Отрицательные:

- нужен новый слой adapter registry и envelope validation;
- для динамических прав финальная выдача результатов требует вызова адаптера;
- без event platform возможна задержка между изменением объекта и обновлением индекса;
- точная событийная аналитика зависит от доменных audit logs;
- нужно аккуратно поддерживать lifecycle источника при отключении или удалении модуля.

## Границы MVP

Входит:

- envelope contract;
- adapter registry;
- privacy profile resolver;
- fail-closed access policy for adapter_check;
- memory projection from envelope;
- analytics projection from envelope;
- adapters for `workorders` and `waiting_list`;
- reindex/reconcile command;
- tests and e2e for search, access, privacy defaults and analytics facts.

Не входит:

- универсальный event bus/outbox;
- слияние `MemorySource` и `AnalyticsSource`;
- OCR изображений;
- автоматическое превращение всех source_data в accepted knowledge;
- внешний HTTP API для источников;
- полная CloudEvents/PROV совместимость.

## Проверки

Минимальные проверки реализации:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.analytics.tests apps.workorders.tests apps.waiting_list.tests
python manage.py memory_file_content_search_e2e
python manage.py analytics_extract_source --source-code <test-source> --dry-run
```
