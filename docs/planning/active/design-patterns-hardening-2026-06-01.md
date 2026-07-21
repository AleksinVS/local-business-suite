# Внедрение архитектурных паттернов

Дата: 2026-06-01.

Статус: re-scoped (2026-07-07) — часть исходного scope закрыта смежными блоками, см. раздел «Пере-скоуп».

Основание: `docs/architecture/DESIGN_PATTERNS_REVIEW_2026-06-01.md`.

Связанный исполнительный блок: `workflow/active/design-patterns-hardening-2026-06-01/`.

## Методическая заметка

Архитектурный паттерн в этом плане понимается как повторяемое правило организации кода: где проходит граница домена, через какой путь меняются данные, где проверяются права, как фиксируются ошибки и как повторяется фоновая работа без дублей. Цель не в добавлении новых слоев ради формы, а в устранении мест, где один и тот же бизнес-сценарий может выполняться разными путями.

## Цель

Закрепить набор прикладных паттернов, которые сделают текущий Django-монолит устойчивее при росте AI-инструментов, памяти, аналитики, фоновых задач и интеграций.

## Бизнес-ценность

- Снизить риск обхода прав и аудита при действиях через AI.
- Уменьшить дублирование бизнес-логики между страницами, AI-инструментами и командами управления.
- Сделать ошибки в фоновых задачах воспроизводимыми и разборными.
- Подготовить проект к будущим worker-процессам без преждевременного ухода в микросервисы.
- Упростить обучение и сопровождение: новые участники видят один способ для записи, чтения, проверки прав и интеграций.

## Рекомендуемый Целевой Подход

### 1. Слой сценариев записи

Все значимые изменения состояния должны идти через доменные функции в `services.py`.

Примеры:

- создание и переход заявки — через `apps.workorders.services`;
- изменение изделий — через сервис `inventory`;
- изменение runtime-контрактов — через `apps.settings_center.contract_services.apply_contract_payload`;
- AI-инструменты и страницы вызывают те же сервисы, а не пишут в модели напрямую.

Ожидаемый результат: один сценарий имеет один путь записи, одну проверку инвариантов и один audit.

### 2. Команда действия для AI-инструментов

Каждое write-действие AI оформляется как команда:

- код инструмента;
- пользователь и сессия;
- входные данные;
- признак необходимости подтверждения;
- `request_id` и `conversation_id`;
- результат или ошибка.

`PendingAction` должен хранить ожидающую команду, а `AgentActionLog` — итог выполнения. Сам AI-инструмент остается тонкой прослойкой и вызывает доменный сервис.

### 3. Единые политики доступа

Права должны проверяться одинаково для UI, AI gateway, management commands и future workers.

Текущий хороший образец — `apps.workorders.policies`. Аналогичные единые входы нужны для:

- проверки доступа к source objects памяти;
- проверки service identity AI runtime/MCP;
- изменения ролей и runtime contracts;
- аналитических read models.

### 4. Переходники и единый конверт данных

`SourceAdapter` и `SourceObjectEnvelope` остаются основной границей для памяти и аналитики.

Новый источник, внутренний или внешний, должен сначала превратиться в единый конверт:

- `source_code`;
- `object_type`;
- `object_id`;
- `content_hash`;
- `sensitivity`;
- `privacy_profile`;
- `access_policy`;
- `provenance`.

Память и аналитика не должны знать внутренний формат каждой внешней системы.

### 5. Строгий AI-шлюз

AI runtime и MCP не должны работать с Django-моделями напрямую. Они обращаются только к разрешенным инструментам через Django gateway.

Gateway обязан проверять:

- служебный токен;
- связь пользователя и chat session;
- контракт инструмента;
- права пользователя;
- необходимость подтверждения;
- audit.

### 6. Журнал исходящих задач

Если бизнес-действие должно запустить долгую работу или внешний side effect, сначала создается запись задачи/outbox в той же транзакции, а worker выполняет ее отдельно.

Кандидаты:

- ingestion документов;
- переиндексация FTS/vector;
- memory reflection;
- пересчет аналитики;
- внешние коннекторы;
- будущие уведомления.

### 7. Повторное выполнение без дублей

Каждая фоновая задача должна иметь ключ повторного выполнения:

- `job_id`;
- `idempotency_key`;
- `content_hash`;
- `source_sequence`;
- `request_id`.

Повторный запуск после сбоя должен исправлять состояние, а не создавать дубли.

### 8. Отдельные модели чтения для памяти и аналитики

Доменные приложения остаются источником истины. Память, поиск, индексы и аналитика строят производные представления, которые можно пересобрать.

Это уже соответствует направлению `MemorySearchDocument`, analytics facts/evidence и future DuckDB/Parquet.

## Scope Работ

### Входит

- Уточнение границ доменных сервисов и write-path.
- Укрепление AI command flow и подтверждаемых действий.
- Проверка и унификация policy entrypoints.
- Расширение `SourceAdapter`/`SourceObjectEnvelope` как единой границы.
- Проектирование outbox/job contract для фоновых контуров.
- Подготовка правил для повторного выполнения без дублей.
- Обновление документации, тестов и e2e-проверок по затронутым сценариям.

### Не Входит

- Полный переход на микросервисы.
- Полная Clean/Hexagonal Architecture во всем проекте.
- Generic repository поверх каждой Django-модели.
- Event sourcing всего workflow заявок.
- Смена основного стека Django/Python.
- Публикация MCP наружу без отдельного ADR.

## Порядок Реализации

1. Закрыть пересечения с `architecture-review-remediation-2026-06-01`: логи prompt, роли, AI gateway, migration path. — **выполнено** (scope поглощён блоком 2026-07-04, который заархивирован 2026-07-07).
2. Перенести write-действия AI к доменным сервисам и Settings Center service layer.
3. Добавить атомарность и блокировки в критичные сценарии записи.
4. Оформить command flow для AI tools и pending confirmations.
5. Закрепить service identity и session ownership в AI gateway/MCP. — **выполнено** (срез 2026-06-01 + пакет 05 ревью 2026-07-04, все пункты CONFIRMED).
6. Описать и внедрить минимальный job/outbox contract для фоновых задач.
7. Расширить selectors/querysets для повторяющихся read-сценариев.
8. Добавить или обновить unit/integration/e2e проверки.
9. Обновить архитектурную и эксплуатационную документацию.

## Журнал Реализации

### 2026-06-01. AI gateway и role write-path

Первый срез реализации закрывает часть пунктов 1, 2, 4, 5 и 9:

- `services/agent_runtime/app.py` больше не пишет сырой prompt и полный actor context в технический лог;
- runtime-лог содержит только `request_id`, `conversation_id`, `session_id`, `model_id`, длину и hash prompt, счетчик истории и безопасную сводку исполнителя;
- ошибки `/chat` и `/chat/stream` возвращают технический код и trace identifiers без текста исключения и не пишут значение исключения в runtime/Django warning logs;
- Django AI gateway проверяет, что `actor.user_id` существует, активен, имеет корректный тип, а переданный `username` не противоречит `user_id`;
- `access.update_role_permissions` переведен на `apps.settings_center.contract_services.apply_contract_payload`, поэтому использует валидацию, атомарную запись и `SettingsChange` audit;
- `AgentActionLog.request_payload` получил command metadata: tool, action kind, actor, session, confirmation state и список ключей payload без дублирования значений.

Исполнительный отчет: `workflow/active/design-patterns-hardening-2026-06-01/EXECUTOR_REPORT.ai-gateway-and-role-write-path.md`.

## Пере-скоуп (2026-07-07)

После исполнения блока `architecture-review-remediation-2026-07-04` и приёмки
смежных блоков часть исходного scope уже закрыта — план сокращён, чтобы не
переделывать сделанное.

**Уже реализовано (вычитается из блока):**
- **Строгий AI-шлюз / идентичность** (§5, пакет 02): служебный токен, связь
  пользователь↔сессия, отклонение несуществующего/неактивного/некорректного
  `actor.user_id`, TTL подписи актора — реализованы и НЕЗАВИСИМО проверены
  (срез 2026-06-01 + пакет 05 ревью 2026-07-04, все пункты CONFIRMED). Модель
  доверия gateway/MCP зафиксирована и в этом блоке НЕ меняется → ADR не нужен.
- **Write-path ролей и runtime-контрактов** (§1, пакет 01): идёт через
  `settings_center.contract_services.apply_contract_payload` (валидация,
  атомарная запись, `SettingsChange`) + contract store ADR-0031 (пакет 01
  ревью). В обход валидации/аудита роли/контракты больше не пишутся.
- **Единый конверт источников** (§4, пакет 04): `SourceObjectEnvelope`,
  `SourceAdapter`, registry, privacy-profiles и адаптеры workorders/waiting_list
  реализованы блоком `universal-source-adapters-memory-analytics` (принят,
  архив 2026-07-07). Остаётся только «закрепить» границу (adapter_check для
  остальных источников), а не заводить её заново.
- **Безопасное логирование runtime + command-metadata в `AgentActionLog`**
  (§2, частично) — из среза 2026-06-01.

**Остаётся (реальный открытый scope, приоритет сверху вниз):**
1. **Outbox/job contract + идемпотентность** (§6/§7, пакет 05) — не начато,
   наивысшая ценность: ingestion, reindex, reflection, пересчёт аналитики,
   внешние коннекторы и уведомления получают `job_id`/`idempotency_key`/
   `content_hash`; повтор после сбоя чинит состояние, а не плодит дубли.
2. **Широкая консолидация write-path** (§1, остаток пакета 01) — свести
   доменные сценарии заявок/инвентаря к сервисам (роль/контракты уже сделаны).
3. **Command-flow для всех AI write tools** (§2, остаток пакета 02) —
   `PendingAction`+подтверждение+trace для каждого write-инструмента, не только
   обновления роли; инструмент — тонкая прослойка к доменному сервису.
4. **Единые policy entrypoints, selectors и read models** (§3/§8, пакет 03),
   плюс развязка `core → workorders`: `contract_store`/`forms` тянут доменные
   валидаторы (следствие разноса `json_utils`, п.11 ревью 2026-07-04) — вынести
   в реестр валидаторов, чтобы ядро не зависело от домена.

**Стартовое решение владельца:** какие доменные write-сценарии входят в первый
срез. ADR на данном этапе не требуется (см. раздел «ADR»).

## Acceptance Checks

Минимальный набор для всего блока:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test apps.workorders.tests apps.ai.tests apps.memory.tests apps.analytics.tests apps.settings_center.tests
git diff --check
```

Для каждого task packet исполнитель обязан добавить targeted unit tests. Для крупного пользовательского сценария нужен e2e через HTTP/UI/API/management command.

## ADR

Новый ADR не нужен для документального планирования.

ADR нужен перед реализацией, если принимается одно из решений:

- новая модель доверия AI gateway/MCP;
- новый production worker или message broker;
- новый storage backend для search/vector/analytics;
- изменение формата `SourceObjectEnvelope`;
- перевод outbox/job contract в обязательный runtime-контур;
- публикация MCP наружу.

## Остаточные Риски

- Без единого write-path AI и UI могут расходиться в проверках прав.
- Без outbox/job record фоновые задачи могут теряться при сбоях между шагами.
- Без strict gateway identity MCP может стать обходным путем к инструментам.
- Без idempotency повторная обработка источников может создавать дубли.

## Связанные Документы

- `docs/architecture/DESIGN_PATTERNS_REVIEW_2026-06-01.md`;
- `docs/guides/ARCHITECTURE_REVIEW_2026-06-01.md`;
- `docs/planning/archive/2026/architecture-review-remediation-2026-06-01.md`;
- `docs/architecture/SERVICE_EXTRACTION_GUIDE.md`;
- `docs/architecture/OBSERVABILITY_BASELINE.md`;
- `docs/adr/ADR-0021-module-registered-agent-skills-and-mcp-facade.md`;
- `docs/adr/ADR-0024-service-extraction-readiness.md`.
