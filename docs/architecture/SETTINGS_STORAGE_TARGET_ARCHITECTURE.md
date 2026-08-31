# Целевая архитектура хранения настроек

Статус: проектное предложение, исполняемое поведение не изменено.

Дата анализа: 2026-08-31.

Связанные материалы:

- решение: `docs/adr/ADR-0048-typed-setting-documents-and-postgresql-runtime-state.md`;
- активный план: `docs/planning/active/settings-storage-simplification.md`;
- workflow: `workflow/active/settings-storage-simplification/`;
- действующий файловый store: `docs/adr/ADR-0031-runtime-contract-store-and-delivery.md`;
- Центр настроек: `docs/adr/ADR-0007-settings-center-and-contextual-help.md`.

## 1. Резюме повторного анализа

Предыдущее предложение правильно разделяло deployment, секреты, Git-дефолты и
рабочие настройки, но слишком рано предлагало физически укрупнять документы и
ориентировалось на их общее количество.

Повторный аудит показал:

1. В `contracts/` есть 29 JSON-документов значений, не считая схем; столько же
   рабочих копий создаётся в `data/contracts/`.
2. Центр настроек знает о 18 runtime-контрактах, 17 из них редактируются.
3. `apps.core.contract_store` обслуживает только четыре документа.
4. Большинство AI/memory/FileHub/analytics потребителей читает значения из
   `settings.LOCAL_BUSINESS_*`, то есть получает снимок времени старта процесса.
5. Agent-runtime отдельно разрешает пути к трём AI-файлам и имеет собственный
   кэш.
6. Запись значения находится в файле, а audit — в PostgreSQL; из-за этого
   существует staged-протокол `pending -> file write -> applied`, состояния
   `inconsistent`, reconcile-команда и межпроцессная файловая блокировка.

Контрольный запуск `validate_architecture_contracts` на текущем хосте
2026-08-31 дал такой снимок:

- 10 из 18 зарегистрированных runtime-контрактов совпадают с Git-дефолтом;
- 7 имеют рабочие отличия: AI models/registry и memory claims, ingestion,
  profiles, retrieval budget, sources;
- `core.contract.role_rules` имеет default-only ключи `$defaults` и `viewer` и
  классифицирован текущей командой как кандидат на ручной перенос.

Это snapshot для планирования, а не инструкция применить Git-дефолт. К моменту
исполнения пакет 01 обязан пересчитать его. Для `role_rules` автоматическое
добавление ключей запрещено до сверки с ADR-0045, фактическими группами и
матрицей доступа.

Следовательно, основной источник сложности — не «29 слишком мелких файлов», а:

- несколько реестров;
- разные семантики чтения;
- две системы согласованности;
- смешение пользовательских настроек, контрактов и runtime-артефактов;
- зависимость актуальности от перезапуска конкретного потребителя.

Целевое решение не сокращает документы по квоте. Оно сокращает число способов
работы с ними.

## 2. Цели и ограничения

### Цели

- один каталог типизированных документов;
- один API чтения для Django;
- одна транзакция PostgreSQL для рабочего значения и audit;
- явный Git-дефолт без зеркальной рабочей копии, если override отсутствует;
- одинаковая ревизия в web workers, background jobs и agent-runtime;
- сохранение доменных валидаторов и специальных security-команд;
- независимость структуры страницы настроек от границы хранения;
- проверяемая миграция без постоянной двойной записи.

### Не цели

- один огромный документ всех настроек;
- произвольное объединение контрактов по разделу интерфейса;
- хранение секретов в JSON, YAML или audit snapshots;
- автоматическое рекурсивное слияние старого override с новым дефолтом;
- Redis, broker или новый runtime-сервис ради кэша;
- generic key/value таблица по одной строке на поле;
- перенос схем, статических справочников и многофайловых AI skills в `jsonb`;
- изменение бизнес-смысла ролей, workflow, memory или AI tools.

## 3. Таксономия конфигурации

| Класс | Источник истины | Изменение | Примеры |
|---|---|---|---|
| `deployment_env` | приватный deployment-контур | оператором вне обычного runtime writer | `DATABASE_URL`, AD host, timeout |
| `secret_handle` | внешнее хранилище | специальным workflow | API key, AD service password |
| `git_static` | `contracts/` | code review/deployment | схемы, неизменяемые каталоги |
| `database_override` | Git-дефолт либо PostgreSQL override | Центром настроек/доменной командой | роли, workflow, цвета, memory policies |
| `generated_file` | `data/` | специализированным worker/service | runtime AI skills, export packages |

Классификация относится к документу целиком. Поле внутри документа не получает
отдельный backend.

## 4. Компоненты и зависимости

```text
Доменное приложение
  -> ConfigDocumentSpec + validator + domain command
        -> единый ConfigDocumentRegistry
              -> ConfigDocumentRepository
                    -> contracts/ (Git default)
                    -> RuntimeSettingDocument (PostgreSQL override)
              -> Settings Center read/write UI
              -> health / validate / export / migrate commands
              -> Django gateway + ETag
                    -> agent-runtime last-known-good cache
```

Общий слой знает, как найти, проверить версию, прочитать, заблокировать и
записать документ. Он не знает, что означает роль, переход заявки или источник
памяти. Эти правила остаются в `accounts`, `workorders`, `ai`, `memory` и других
доменах.

## 5. Единая спецификация документа

Минимальный контракт `ConfigDocumentSpec`:

| Поле | Назначение |
|---|---|
| `document_id` | стабильный идентификатор; для существующих документов равен `setting_id` |
| `domain` | владелец бизнес-смысла |
| `storage_policy` | `git_static`, `database_override` или `generated_file` |
| `default_path` | путь к Git-дефолту либо `None` для generated |
| `schema_version` | версия формы payload |
| `validator` | callable доменной проверки, не строковое имя |
| `cross_validators` | явно объявленные зависимости от других документов |
| `failure_policy` | `fail_closed` или `visible_default_fallback` |
| `write_policy` | read-only, generic editor или domain workflow |
| `required_permission` | продуктовая возможность изменения |
| `requires_restart/reindex` | последствия применения |
| `delivery_scope` | Django only либо разрешённая доставка agent-runtime |

Правила реестра:

- `document_id` уникален;
- для `database_override` обязательны default, schema version и validator;
- security/private документ не может иметь мягкий fallback;
- secret-bearing schema запрещена для ordinary document;
- cross-document зависимости не образуют неявных циклов;
- один и тот же путь не регистрируется двумя документами;
- registry импортирует доменные модули, но не содержит доменных валидаторов.

`SettingDescriptor` для runtime-документа становится представлением этой
спецификации для интерфейса. Поля окружения, Django-модели и secret handles
продолжают использовать свои дескрипторы.

Не следует в первом срезе строить универсальный генератор форм из `x-ui`.
Существующих 18 document-level дескрипторов недостаточно много, чтобы окупить
новый UI-язык. JSON Schema остаётся источником структурной проверки, а сложные
редакторы — явным доменным кодом. Генерацию простых полей можно оценить после
устранения storage-дублирования.

## 6. Модель рабочего документа

Предлагаемая модель:

```text
RuntimeSettingDocument
  document_id        varchar primary key
  schema_version     positive integer
  payload            jsonb
  revision           positive bigint
  content_hash       char(64)
  default_hash       char(64)
  updated_by_id      nullable FK user
  created_at
  updated_at
```

Инварианты:

- `revision >= 1`;
- `content_hash == canonical_hash(payload)`;
- один `document_id` — одна текущая рабочая версия;
- отсутствие строки — не ошибка, а использование Git-дефолта;
- `payload` — полный документ;
- новая рабочая версия всегда проходит текущий validator;
- ручная правка строки вне service layer считается повреждением и обнаруживается
  health/check по несовпадению хеша или схемы.

История остаётся в `SettingsChange`. Для DB-документа полезно добавить поля
`document_revision_before` и `document_revision_after`; существующие snapshots и
hash сохраняются. Audit и текущее значение записываются в одной транзакции.

## 7. Чтение и снимки

Алгоритм `get_document(document_id, request=None)`:

1. Получить спецификацию.
2. Для `git_static` прочитать и проверить Git-документ.
3. Для `database_override` запросить строку по первичному ключу.
4. Если строки нет — прочитать Git-дефолт.
5. Проверить schema version, canonical hash и доменный validator.
6. Сохранить снимок в request-local mapping, если передан HTTP request.
7. Вернуть копию, которую потребитель не может использовать для мутации кэша.

Глобальный payload-кэш на первом этапе отсутствует. Это даёт простую
межпроцессную согласованность PostgreSQL. Для role/access один HTTP-запрос обязан
использовать один снимок документа. Background operation читает все нужные
документы один раз в начале команды или задания.

Если измерения покажут существенную стоимость, допустим LRU/TTL-кэш по паре
`(document_id, revision)`, но только отдельным изменением с тестом окна
устаревания. Redis и LISTEN/NOTIFY не являются предусловием.

## 8. Запись, блокировки и rollback

Обычный writer:

```text
transaction.atomic
  pg_advisory_xact_lock for sorted affected document ids
  select_for_update current document row
  verify expected revision/hash
  load required cross-document rows in sorted order
  build candidate
  JSON Schema + domain + cross validation
  update payload/revision/hash
  insert SettingsChange(status=applied)
commit
on_commit: optional cache notification / reindex scheduling
```

Transaction-level advisory lock закрывает случай отсутствующей override-строки,
которую нельзя заблокировать `SELECT FOR UPDATE`. Ключ строится как стабильное
signed 64-bit значение из SHA-256 `document_id`; применение Python `hash()`
запрещено из-за процессной рандомизации. Все затрагиваемые ids сортируются до
получения locks. Advisory locks автоматически освобождаются transaction end;
existing rows затем блокируются обычным `SELECT FOR UPDATE`.

Если строки override ещё нет, CAS сравнивается с хешем Git-дефолта, после чего
создаётся revision 1. Для одновременного первого создания используется
уникальность `document_id` и повторная классификация конфликта как stale edit.

Rollback — обычная новая запись кандидата из `before_snapshot` выбранного
audit-события. Старая ревизия не становится текущей магически, а история остаётся
монотонной.

Критичные доменные команды сохраняются:

- полное изменение каталога ролей — только active superuser;
- ограниченное изменение определения роли — существующий signed preview и
  privilege ceiling;
- пары role/workflow валидируются на одном согласованном снимке;
- обновление status colors валидируется против той же ревизии workflow, которая
  участвовала в проверке.

## 9. Эволюция схемы и Git-дефолта

Автоматическое глубокое слияние запрещено. Оно не различает новый дефолт,
осознанное удаление и `null` как значение.

Правила:

- совместимое добавление поля оформляется новой schema version и явным
  migrator-ом с default;
- несовместимое изменение имеет отдельную функцию преобразования `N -> N+1`;
- команда миграции поддерживает `--plan` и `--apply`;
- план показывает before/after hash, изменённые пути и validator result;
- миграция пишет обычный `SettingsChange` с actor/system identity и причиной;
- deploy check сообщает `migration_required`, но не правит данные;
- security-критичный consumer не использует неизвестную schema version.

## 10. Доставка agent-runtime

Предлагаемый read-only gateway:

```text
GET /ai/gateway/config/documents?ids=ai.contract.tools,ai.contract.task_types,...
Authorization: существующая service identity
If-None-Match: "<aggregate-hash>"
```

Ответ содержит только allowlisted документы и метаданные:

```json
{
  "documents": [
    {
      "document_id": "ai.contract.tools",
      "schema_version": 1,
      "revision": 3,
      "content_hash": "...",
      "payload": {}
    }
  ]
}
```

Agent-runtime хранит ограниченный last-known-good снимок в памяти или своём
runtime cache, проверяет schema version и переиспользует его только при временной
недоступности gateway. Неизвестная версия или невалидный документ не заменяет
последний валидный. Источник и возраст снимка видны в diagnostics/health.

Agent-runtime не получает generic list всех портальных настроек и не имеет
write endpoint.

## 11. Границы документов и UX

Физическое объединение разрешено, только если одновременно совпадают:

- доменный владелец;
- право изменения;
- validator и cross-dependencies;
- политика сбоя;
- необходимость restart/reindex;
- ожидаемая частота изменения;
- граница rollback.

Отсюда следуют проектные решения:

- `workorders.contract.status_colors` и
  `waiting_list.contract.status_colors` остаются разными документами, но
  отображаются на одной странице;
- роли и workflow остаются разными документами и блокируются вместе только для
  кросс-валидации;
- memory sources, ingestion profiles, routing и trust policy не объединяются в
  один memory-document;
- AI tools, task types и models не объединяются: у них разные владельцы
  изменений и доставка;
- настройки окружения не становятся разделом runtime JSON-документа.

Так сокращается пользовательская сложность без увеличения blast radius.

## 12. Инвентарь и предварительная классификация

Повторная проверка содержимого показала, что часть нынешних `editable`
дескрипторов описывает не операторские настройки, а исполняемый/security
контракт. Их перенос в DB сохранил бы опасную возможность менять через общий JSON
editor то, что должно проходить code review.

| Документ | Предварительная цель | Основание/условие |
|---|---|---|
| `role_rules.json` | `database_override` | специальный access workflow, fail closed |
| `workflow_rules.json` | `database_override` | доменная команда и cross-validation |
| `workorder_status_colors.json` | `database_override` | связанный access/workflow срез, не pilot |
| `waiting_list_status_colors.json` | `database_override` | первый независимый pilot |
| `ai/chat_settings.json` | `database_override` | операторские параметры UX/контекста |
| `ai/registry.json` | `git_static` | identity/execution security architecture, не обычная настройка |
| `ai/tools.json` | `git_static` | каталог должен совпадать с Python tool definitions |
| `ai/task_types.json` | `git_static` | содержит allowed tools и confirmation policy; editable aliases требуют будущего безопасного выделения |
| `ai/models.json` | `unresolved` | выбрать Git-static либо специальный model-profile workflow; raw keys всё равно вне документа |
| `ai/memory_sources.json` | `database_override` | host/runtime sources, доменная проверка |
| `ai/memory_profiles.json` | `database_override` | runtime profiles, requires evaluation |
| `ai/memory_routing.json` | `database_override` | runtime routing, privacy-aware validator |
| `ai/memory_trust_policy.json` | `database_override` | fail closed, специальное право |
| `ai/memory_claims_policy.json` | `unresolved` | claim/belief layer сейчас отложен; проверить consumer и удалить либо оставить Git-static |
| `ai/memory_retrieval_budget.json` | `database_override` | tuning document с ограничениями |
| `ai/memory_ingestion_profiles.json` | `database_override` | доменная настройка, последствия для ingestion |
| `ai/memory_file_organization_profiles.json` | `database_override` | один snapshot на FileHub job |
| `ai/memory_graph_schema.json` | `database_override` через domain workflow | не generic editor; модерация экспертом/владельцем графа |
| `analytics/analysis_scope_rules.json` | `git_static` предварительно | нет runtime owner/writer; privacy policy требует review |
| `analytics/business_facts.json` | `git_static` предварительно | нет runtime owner/writer |
| `analytics/datasets.json` | `git_static` предварительно | registry contract; не operational data rows |
| `analytics/dedup_rules.json` | `git_static` предварительно | менять только после domain workflow |
| `analytics/diagnostic_playbooks.json` | `git_static` предварительно | нет runtime writer |
| `analytics/metrics.json` | `git_static` предварительно | metric definition contract |
| `analytics/monitors.json` | `git_static` предварительно | monitor definition contract |
| `analytics/retention_profiles.json` | `git_static` предварительно | privacy/retention review |
| `analytics/sources.json` | `git_static` предварительно | до появления управляемого source workflow |
| `analytics/workflow_routes.json` | `git_static` предварительно | нет runtime writer |
| `integrations/registry.json` | `git_static` | канонический общий registry по правилам репозитория |

Итого предварительно: 13 `database_override`, 14 `git_static`, 2 `unresolved`.
Первый task packet обязан подтвердить это машинным inventory и фактическими
consumer-ами. Статус `unresolved` блокирует автоматический перенос, а
предварительный `git_static` не удаляет runtime copy до доказанного cutover.

Runtime AI skills (`SKILL.md` и связанные директории) остаются `generated_file`
и не входят в список 29 JSON-документов.

## 13. Миграционная классификация legacy-файлов

| Состояние | Действие |
|---|---|
| runtime hash равен Git default hash | не создавать DB override |
| runtime hash совпадает с `after_hash` применённого `SettingsChange` | импортировать как подтверждённую рабочую версию |
| runtime отличается, audit отсутствует | остановить автоматический импорт, запросить решение владельца |
| runtime не проходит текущую схему | остановить, сначала подготовить migrator |
| security runtime не содержит новые default keys | отдельная ручная сверка; generic merge запрещён |
| env переопределяет путь | отдельная ручная ветка; не угадывать источник |
| файл отсутствует, default валиден | оставить отсутствие override |

Отчёт `--plan` пишется только в `.local/` и не содержит секретов. Для каждого
документа выводятся классификация, source paths, хеши, schema version, audit
evidence и предлагаемое действие.

## 14. Порядок внедрения

1. Инвентарь и единый registry без изменения поведения.
2. Модель, repository, transactional writer и тесты на временных документах.
3. Идемпотентный migration planner/importer.
4. Pilot независимого `waiting_list.contract.status_colors`; общий экран
   продолжает показывать обе палитры, но палитра заявок пока остаётся legacy.
5. Core role/workflow и `workorders.contract.status_colors` как единый
   dependency-closed security acceptance slice.
6. AI documents одновременно с gateway и agent-runtime ETag delivery.
7. Memory/FileHub consumers; один снимок на job/command.
8. Analytics/integrations classification, удаление startup payload constants и
   legacy runtime copies только после доказанной приемки.

Постоянная двойная запись file+DB запрещена. На cutover конкретного среза запись
кратко замораживается, выполняются final plan/import/switch/smoke, затем окно
наблюдения.

## 15. Проверки приемки

### Инварианты

- у каждого document setting ровно одна `ConfigDocumentSpec`;
- для переведённого документа нет прямых `load_json_file` и payload-констант;
- значение и `SettingsChange` либо фиксируются вместе, либо не фиксируются;
- stale revision не перезаписывается;
- rollback создаёт новую ревизию;
- два web worker видят новую ревизию без перезапуска;
- один HTTP request не смешивает ревизии;
- security-критичная ошибка даёт закрытый отказ;
- agent-runtime и Django сообщают один content hash;
- отсутствие override использует актуальный Git-дефолт без runtime-копии;
- YAML не становится скрытым вторым источником.

### Минимальные e2e-сценарии

- изменение цвета через UI -> PostgreSQL -> новая страница видит цвет;
- конкурентное изменение одного документа -> второй writer получает conflict;
- изменение/rollback роли -> матрица разрешений до/после совпадает с ожиданием;
- изменение AI tools -> agent-runtime получает новый ETag без restart;
- migration `--plan` ничего не пишет, повторный `--apply` идемпотентен;
- повреждённая/неизвестная schema version видна в health и не применяется;
- backup/restore PostgreSQL возвращает рабочие документы и audit continuity.

## 16. YAML

YAML остаётся возможным форматом обмена, но не хранения рабочего состояния.
Причины:

- веб-интерфейс всё равно работает с типизированным объектом, а не комментариями;
- обычный parse/dump не обязан сохранять комментарии и исходное форматирование;
- YAML имеет aliases, tags и более сложное разрешение scalar types;
- нужен отдельный безопасный parser profile;
- второй канонический формат увеличит, а не уменьшит число путей проверки.

Если YAML import/export появится позже, он обязан использовать YAML 1.2 safe
subset, затем проходить ту же JSON Schema и доменную проверку. Хеш считается по
каноническому JSON-представлению.

## 17. Внешние основания

- Django гарантирует атомарность ORM-операций внутри `transaction.atomic()` и
  рекомендует выполнять побочные действия после успешного commit:
  <https://docs.djangoproject.com/en/5.2/topics/db/transactions/>.
- Django `JSONField` на PostgreSQL использует `jsonb`:
  <https://docs.djangoproject.com/en/5.2/ref/models/fields/#jsonfield>.
- PostgreSQL документирует различия и свойства `jsonb`:
  <https://www.postgresql.org/docs/current/datatype-json.html>.
- PostgreSQL transaction-level advisory locks подходят для application-defined
  объектов, которые неудобно блокировать обычной строкой:
  <https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS>.
- JSON Schema определяет структуру, assertions и annotations документов:
  <https://json-schema.org/draft/2020-12>.
- `ETag` и условные запросы определены HTTP Semantics:
  <https://www.rfc-editor.org/rfc/rfc9110.html>.
- YAML information model и ограничения mappings определены YAML 1.2.2:
  <https://yaml.org/spec/1.2.2/>.
