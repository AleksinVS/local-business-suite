# Анализ полезных паттернов проектирования

Дата: 2026-06-01.

Статус: recommendation.

## Методическая заметка

Паттерн проектирования полезен, когда он закрепляет повторяющуюся границу ответственности: кто принимает решение, кто меняет состояние, кто обращается к внешней системе, кто проверяет права и кто пишет audit. В этом проекте не нужно переносить абстрактные паттерны один к одному из книг. Полезнее выбирать маленькие прикладные паттерны, которые усиливают уже принятую архитектуру: Django как источник истины, контракты как декларативные правила, `data/` как runtime-состояние, AI runtime через gateway, память и аналитика через adapters/projections.

## Использованные источники

- Django design philosophies: loose coupling, DRY, explicitness, model/domain logic, SQL efficiency.
  <https://docs.djangoproject.com/en/5.2/misc/design-philosophies/>
- Django transactions: autocommit, `atomic()`, ограничения транзакций вокруг request/streaming.
  <https://docs.djangoproject.com/en/5.2/topics/db/transactions/>
- Django multiple databases: дополнительные шаги и явные database routers.
  <https://docs.djangoproject.com/en/5.2/topics/db/multi-db/>
- Django managers: managers/querysets для table-level логики.
  <https://docs.djangoproject.com/en/5.2/topics/db/managers/>
- OWASP Logging Cheat Sheet: исключение sensitive data из логов, correlation/interaction identifiers.
  <https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html>
- Microsoft Azure Architecture Center: паттерны Anti-Corruption Layer, Cache-Aside, Queue-Based Load Leveling, Retry, Circuit Breaker, CQRS.
  <https://learn.microsoft.com/en-us/azure/architecture/patterns/>
- AWS Prescriptive Guidance: Transactional Outbox для устранения dual-write риска.
  <https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html>
- Enterprise Integration Patterns: Message Translator, Normalizer, Canonical Data Model, Message History, Idempotent Receiver.
  <https://www.enterpriseintegrationpatterns.com/patterns/messaging/MessageTranslator.html>
- Microsoft domain analysis: bounded contexts, core/supporting/generic subdomains.
  <https://learn.microsoft.com/en-us/azure/architecture/microservices/model/domain-analysis>
- MADR: структурная фиксация значимых решений.
  <https://adr.github.io/madr/>

## Текущее состояние проекта

Проект уже использует несколько правильных архитектурных паттернов:

- **Модульный монолит.** Домены разделены на Django apps: `workorders`, `inventory`, `accounts`, `memory`, `analytics`, `ai`, `settings_center`, `core`.
- **Декларативные контракты.** Git-дефолты лежат в `contracts/`, runtime-копии в `data/contracts/`, валидация идет через `validate_architecture_contracts`.
- **Settings Center как единый путь записи настроек.** `apps.settings_center.contract_services.apply_contract_payload` валидирует, атомарно пишет и создает audit.
- **Adapter/Envelope для источников.** `apps.core.source_adapters.SourceAdapter` и `SourceObjectEnvelope` нормализуют доменные и внешние источники для памяти и аналитики.
- **Gateway/Facade для AI.** Agent runtime не пишет в бизнес-БД напрямую, а обращается в Django через AI gateway.
- **Policy functions.** `apps.workorders.policies` содержит серверные проверки прав и workflow-переходов.
- **Selectors.** `apps.workorders.selectors` отделяет переиспользуемые read-запросы от views.
- **Audit Log.** `AgentActionLog`, `MemoryAccessAudit`, `SettingsChange` фиксируют действия и ошибки.

Главный риск сейчас не в отсутствии паттернов, а в неравномерности их применения: часть write-path проходит через правильные сервисы, часть остается в отдельных views/tools; часть интеграций уже нормализована через envelope, часть еще требует единого queue/outbox контура; agent runtime и MCP требуют более строгой модели service identity.

## Рекомендуемые паттерны

### 1. Модульный Монолит И Bounded Context

Приоритет: высокий.

Что применять:

- оставить Django monorepo основным способом разработки;
- считать Django app границей доменного контекста, если у нее есть свои модели, правила, UI и проверки;
- не выносить сервис из монолита без измеренной причины и ADR;
- перед добавлением нового приложения описывать его владельца данных и связи с другими доменами.

Где применить:

- `workorders` - core domain: заявки, workflow, права действий;
- `inventory` - supporting domain: справочник изделий;
- `accounts`/SSO - generic/supporting domain;
- `memory` и `analytics` - platform/insight domains, которые читают проекции, но не должны становиться владельцами бизнес-истины;
- `ai` - orchestration domain, который вызывает bounded tools, но не хранит доменную логику чужих модулей.

Практическое правило: если функция меняет заявку, она должна жить в `apps.workorders.services` или вызывать его. Если AI-инструмент создает заявку, он остается тонким адаптером и вызывает доменный service layer.

### 2. Service Layer Для Write Use Cases

Приоритет: высокий.

Что применять:

- все значимые изменения состояния оформлять как use-case функции в доменном `services.py`;
- view, AI tool и management command должны вызывать один и тот же сервис;
- сервис должен выполнять валидацию доменных инвариантов, проверку прав или принимать уже проверенный контекст явно;
- для операций из нескольких записей использовать `transaction.atomic()`.

Где усилить:

- `apps.workorders.services.transition_workorder` уже является правильной точкой для переходов, но стоит добавить атомарность, `select_for_update()` для конкурентных переходов и проверку allowed transition ближе к сервису;
- `apps.ai.services` сейчас содержит много функций чужих доменов (`create_workorder_for_actor`, `create_device_for_actor`, `update_role_permissions_for_actor`). Их лучше постепенно превратить в тонкие команды, которые вызывают сервисы `workorders`, `inventory`, `settings_center`;
- старые write-path для ролевых контрактов должны вызывать `apply_contract_payload`, а не писать JSON напрямую.

Не нужно: создавать отдельный класс-сервис для каждой простой CRUD-операции без инвариантов.

### 3. Command И Unit Of Work Для AI Tools И Подтверждаемых Действий

Приоритет: высокий.

Что применять:

- каждое write-действие AI считать командой: tool id, actor, payload, confirmation state, request id, result;
- подтверждаемое действие (`PendingAction`) должно фиксировать команду до выполнения;
- выполнение команды должно быть атомарным в пределах одной базы;
- если команда порождает внешний side effect, использовать outbox.

Где применить:

- `apps.ai.tooling.execute_tool` и `execute_pending_action`;
- `workorders.create`, `workorders.transition`, `workorders.delete`, `inventory.devices.*`, `access.*`, `memory.remember`;
- future workers для ingestion/indexing/analytics.

Практическое правило: AI tool не должен сам решать бизнес-правила. Он формирует command, проверяет confirmation, вызывает доменный сервис и пишет audit.

### 4. Policy/Specification Для Прав Доступа И Workflow

Приоритет: высокий.

Что применять:

- продолжать хранить декларативные правила в contracts;
- runtime-проверки держать в policy layer;
- сложные условия оформлять как маленькие спецификации: `can_view`, `can_transition`, `can_manage_inventory`, `can_access_source_object`;
- одинаковые политики для UI, AI tools и workers должны вызываться из одного места.

Где применить:

- `apps.workorders.policies` уже задает хороший образец;
- для AI gateway/MCP добавить политику service identity: runtime может действовать только от пользователя, связанного с проверенной chat session;
- для памяти закрепить единый policy entrypoint для `scope_tokens`, `adapter_check`, `manual_mapping`, `acl_inherited`.

Не нужно: переносить все policies в абстрактный rules engine, пока JSON-контракты и функции остаются читаемыми.

### 5. Selector, Query Object И Custom QuerySet/Manager Для Read Side

Приоритет: средний.

Что применять:

- сложные read-запросы держать в `selectors.py`, custom `QuerySet` или manager;
- views должны собирать HTTP-контекст и выбирать template, но не дублировать фильтрацию видимости;
- для повторяющихся table-level операций Django docs рекомендуют managers/querysets.

Где применить:

- `apps.workorders.selectors.visible_workorders_queryset` уже правильный pattern;
- аналогичные selectors полезны для `inventory`, `memory.review`, `analytics`;
- custom managers стоит добавлять только там, где это дает выразительный ORM API: `WorkOrder.objects.visible_to(user)` или `MemoryKnowledgeItem.objects.active_for_scope(tokens)`.

Не нужно: общий Repository поверх Django ORM для каждой модели. Django ORM уже дает достаточно сильный слой доступа к данным; лишняя repository-обертка ухудшит читаемость и тесты.

### 6. Adapter, Anti-Corruption Layer И Canonical Envelope

Приоритет: высокий.

Что применять:

- все внешние системы и внутренние доменные источники переводить в canonical envelope;
- внешние форматы не должны протекать в доменные модели и UI;
- source-specific mapping держать в adapter, а не в `memory`/`analytics`.

Где применить:

- текущий `SourceAdapter`/`SourceObjectEnvelope` оставить основной границей для memory/analytics;
- external connectors должны писать в landing zone и далее нормализовать в envelope;
- для новых интеграций использовать registry + adapter + dry-run + audit.

Практическое правило: `memory` и `analytics` получают нормализованный envelope. Они не знают, как конкретная внешняя ИС называет заявку, сотрудника, отдел или документ.

### 7. Gateway/Facade Для AI Runtime И MCP

Приоритет: высокий.

Что применять:

- AI runtime и MCP должны видеть только bounded tools, а не модели Django;
- gateway проверяет service token, actor/session ownership, tool contract, права и audit;
- MCP-фасад должен быть read-only/proposal-only, пока не введена строгая service identity.

Где усилить:

- `AIToolExecuteView` не должен принимать `actor` из тела запроса как достаточное основание;
- `validate_gateway_actor` должен быть обязательным для tool execution;
- `services/agent_runtime/mcp_server.py` должен прокидывать проверенный контекст, а не произвольные `user_id`, `roles`.

Это продолжение уже принятого направления ADR-0021.

### 8. Transactional Outbox И Idempotent Receiver

Приоритет: средний сейчас, высокий перед production workers.

Что применять:

- если бизнес-запись должна породить фоновую задачу или внешний вызов, сначала писать outbox/job в ту же транзакцию;
- worker читает outbox/job, выполняет side effect и помечает статус;
- обработчики должны быть идемпотентными через `idempotency_key`, `content_hash`, `source_sequence` или `job_id`.

Где применить:

- ingestion документов;
- indexing FTS/vector;
- memory reflection;
- analytics projection/recompute;
- external connector sync;
- future notifications.

Практическое правило: нельзя делать `save()` в БД и сразу после этого необратимый внешний вызов без записи задачи/outbox. При падении между двумя действиями система потеряет согласованность.

### 9. Retry, Circuit Breaker И Bulkhead Для Внешних Зависимостей

Приоритет: средний.

Что применять:

- retry только для временных ошибок и только с лимитами;
- circuit breaker для зависимостей, которые могут долго лежать: LLM gateway, external APIs, OCR/parser backend;
- bulkhead: разделять очереди или лимиты для AI-чата, indexing, ingestion, analytics, чтобы тяжелый контур не блокировал пользовательский UI.

Где применить:

- `AgentRuntimeClient`;
- `DjangoGatewayClient`;
- external connectors;
- vector/search backend;
- parser/OCR worker.

Не нужно: retry вокруг операций, которые не идемпотентны или могут создать дубль без idempotency key.

### 10. Pipeline/Template Method Для Ingestion И Индексации

Приоритет: средний.

Что применять:

- закрепить pipeline стадиями: discover -> fetch/reference -> parse -> privacy gate -> chunk/extract -> write safe projection -> index -> review/audit;
- каждая стадия должна иметь вход, выход, статус, ошибку и dry-run;
- разные adapters могут менять реализацию стадий, но не общий порядок.

Где применить:

- `apps.memory.document_ingestion`;
- `apps.memory.external_connectors`;
- management commands `memory_*`;
- будущие OCR/parser backends.

Польза: проще отлаживать partial indexing, review queue, privacy blocks и повторную обработку.

### 11. CQRS/Read Model Для Аналитики И Памяти

Приоритет: средний.

Что применять:

- write model остается в доменных приложениях;
- memory/analytics строят read models/projections;
- аналитика не должна напрямую становиться частью транзакционного workflow заявок;
- перестраиваемые индексы считать производными артефактами, а не источником истины.

Где применить:

- `MemorySearchDocument` и индексы;
- `AnalyticsContentObject`, evidence, facts, monitors;
- будущий DuckDB/Parquet слой.

Не нужно: разделять command/read path для простых справочников, где нет нагрузки и разных моделей чтения/записи.

### 12. Registry + Contract Validation

Приоритет: высокий.

Что применять:

- реестры инструментов, настроек, adapters и внешних систем должны иметь один canonical source и валидатор;
- runtime-контракты меняются только через Settings Center или management command с теми же валидаторами;
- generated contract должен проверяться на совпадение с Python registry.

Где применить:

- `apps.ai.tool_definitions.py` + `contracts/ai/tools.json`;
- `apps.settings_center.registry`;
- `contracts/integrations/registry.json`;
- source adapters registry.

Практическое правило: если есть registry, нельзя иметь второй ручной список той же сущности без проверки drift.

### 13. Audit Log + Correlation Identifier

Приоритет: высокий.

Что применять:

- каждый пользовательский и agent workflow должен иметь `request_id` и `conversation_id`;
- в технические логи писать идентификаторы, классы ошибок, длины, хэши и статусы;
- prompt, секреты, персональные данные, медицинские сведения и access tokens не писать в technical logs;
- для разбора использовать контролируемый доступ к `ChatMessage.content` и audit records.

Где применить:

- `AgentActionLog`;
- `MemoryAccessAudit`;
- `SettingsChange`;
- `services/agent_runtime/app.py`;
- future workers.

Это прямо закрывает риск из архитектурного ревью: сырой prompt не нужен в логах, потому что уже есть сохраненное пользовательское сообщение и trace identifiers.

## Паттерны, Которые Не Стоит Вводить Сейчас

### Generic Repository Для Каждой Django-Модели

Почему не стоит: Django ORM уже является высокоуровневым data access API. Дополнительный слой `UserRepository`, `WorkOrderRepository`, `DeviceRepository` без реальной альтернативы хранилища создаст дублирование и ухудшит запросы.

Где repository допустим:

- файловое knowledge-хранилище;
- vector backend;
- внешние API;
- DuckDB/Parquet;
- сложное хранилище, которое не является обычной Django-моделью.

### Полная Clean/Hexagonal Architecture

Почему не стоит: проект local-first, Django templates/HTMX и Django ORM дают скорость разработки и понятную эксплуатацию. Полное отделение domain от Django на этом этапе добавит boilerplate и снизит прозрачность.

Что взять точечно: ports/adapters только на границах внешних систем, AI runtime, storage backends и workers.

### Микросервисы Для Бизнес-Доменов

Почему не стоит: заявки, роли, workflow, SSO и audit сильно связаны. Разносить их по сетевым сервисам без нагрузки и команды эксплуатации преждевременно.

Что допустимо: вынос технических workers по правилам `SERVICE_EXTRACTION_GUIDE.md`.

### Event Sourcing Для Всего Workflow

Почему не стоит: текущей модели `WorkOrder` + `WorkOrderTransitionLog` достаточно. Полный event sourcing усложнит чтение, миграции и восстановление без явной потребности.

Что допустимо: append-only audit/outbox для ключевых действий и workers.

## Приоритетная Карта Внедрения

1. Закрепить service layer как единственный write-path для ролей, заявок, устройств и AI tools.
2. Убрать raw prompt из runtime logs, оставить correlation/audit identifiers.
3. Усилить gateway/facade: обязательная session ownership и service identity.
4. Добавить атомарность и блокировки в критичные write use cases: transitions, pending confirmations, contract writes.
5. Оформить outbox/job pattern для ingestion, indexing, analytics recompute и external connectors.
6. Расширять selectors/querysets для повторяющихся read-сценариев.
7. Поддерживать SourceAdapter/Envelope как единую anti-corruption границу для памяти и аналитики.
8. Перед каждым новым runtime-сервисом проверять ADR, p50/p95, contracts, audit, retry/idempotency и e2e.

## Критерии Выбора Паттерна

Использовать паттерн, если он отвечает хотя бы на один вопрос:

- где проходит граница домена;
- где выполняется бизнес-запись;
- как гарантируется атомарность;
- как повторить действие без дублей;
- как проверить права одним способом для UI, AI и worker;
- как скрыть внешний формат за стабильным контрактом;
- как отладить ошибку без утечки данных;
- как доказать, что runtime-сервис не стал вторым источником истины.

Не использовать паттерн, если он только добавляет папки, интерфейсы или классы без нового контроля над риском.

## Связь С Текущим Ревью

Рекомендации напрямую поддерживают исправления из `docs/guides/ARCHITECTURE_REVIEW_2026-06-01.md`:

- миграции и deployment: Unit of Work, multi-db discipline;
- роли и runtime contracts: Service Layer, Registry, Contract Validation;
- AI gateway/MCP: Gateway/Facade, Policy, Audit;
- prompt logging: Audit Log + Correlation Identifier;
- интеграции и память: Adapter, Anti-Corruption Layer, Outbox, Idempotent Receiver;
- future workers: Queue, Retry, Circuit Breaker, Bulkhead.

ADR сейчас не нужен, потому что документ не принимает новое решение. ADR потребуется перед вводом нового runtime-сервиса, нового storage backend, внешнего message broker, изменением gateway identity model или переводом outbox/job pattern в production-контур.
