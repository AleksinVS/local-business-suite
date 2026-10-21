# Agent Interaction Kernel — контракты и протоколы

Статус: proposed normative design; используется всеми адаптерами агентов LBS Factory.

## 1. Требование

Агенты внедрения (Pi, Claude, другие coding agents) и эксплуатационные агенты (LangGraph, другие) могут делегировать проверяемые задачи друг другу независимо от внутреннего runtime. Не требуется единая память, одинаковая модель, общий prompt или единая реализация tool loop. Взаимодействие **не должно автоматически расширять полномочия** принимающего агента.

## 2. Разделение стандартов

| Плоскость | Стандарт | Использование |
|---|---|---|
| Agent ↔ Agent | **A2A 1.0** | Снаружи границ runtime; discovery, задания, сообщения, artifacts, статус, streaming; использовать официальный SDK/adapter, не создавать собственный wire protocol |
| Agent ↔ Tools | **MCP** | Доступ к capabilities, Wiki, Bitrix, TaskProvider; identity и policy на стороне tool-server/доменного сервиса |
| Agent ↔ Human UI | **AG-UI** | События ответа, прогресс/UX, по необходимости; не source-of-truth состояния задания |
| Local orchestration | **Task API** | Локальный типизированный интерфейс постановки и контроля заданий, опционально persistent store; A2A adapter отображает его на стандартные сущности. **Task fields не считаются proof of authorization** |
| Job transport | In-process / DB-backed queue / optional broker | Способ доставки/повторов, не публичный протокол |

A2A подходит для независимых «чёрных ящиков». Внутри SDK можно использовать собственные handoffs/agents-as-tools; запрещено упаковывать каждую внутреннюю функцию в сетевой A2A-сервис. Не применять MCP для работы с «агентом-сотрудником» как простой набор бездоверительных инструментов, если требуется долгий цикл задачи. Не использовать шину событий в качестве task coordinator.

## 3. Минимальные сущности

### AgentDescriptor

- `agent_id`, `provider_kind`, `version`;
- `capabilities`: типизированные сценарии, а не полный список внутренних команд;
- `endpoint` или локальный adapter ref;
- `supported_modes`: request/response, async, streaming (по факту);
- `auth_scheme`, `allowed_data_classes`, `trust_boundary`, `cost_model`;
- `health`, `max_concurrency` и явный enabled state.

Реестр agent descriptors — **локальный allowlist** доверенных провайдеров; нельзя автоматически делегировать произвольному URL, переданному в prompt. Экспортируемый A2A Agent Card формируется отдельно и не раскрывает закрытую внутреннюю конфигурацию, сети и права.

### AgentTask (локальный DTO, НЕ A2A wire schema)

```json
{
  "schema_version": "lbs.agent-task.v1",
  "task_id": "01JABCDEF0123456789ABCDEFA",
  "installation_id": "customer-alpha",
  "initiator": {"kind": "user", "subject_ref": "id:123"},
  "requested_by_agent": "discovery-agent",
  "target_agent": "architecture-reviewer",
  "capability": "review.solution.v1",
  "goal": "Проверить архитектуру интеграции",
  "inputs": {"spec_ref": "artifact:solution-plan@sha256:..."},
  "context_refs": ["wiki:concept-42@revision-7"],
  "effective_scope": ["knowledge.read:project-alpha"],
  "policy_ref": "policy:agent-delegation@v1",
  "approval_ref": null,
  "correlation_id": "trace-881",
  "parent_task_id": "01JABCDEFGHIJKLMN000000000",
  "idempotency_key": "review-solution-7",
  "limits": {"wall_time_seconds": 900, "max_input_tokens": 12000, "max_cost_usd": 2.5},
  "output_schema": "lbs.review-report.v1",
  "created_at": "2026-10-12T10:00:00Z"
}
```

Пример логический: ссылки вида `artifact:...` и `wiki:...` должны разрешаться только через доверенный Artifact/Knowledge API, после проверки прав; не трактуются как прямые файловые пути или произвольные URL. Транспорт адаптера обязан поддержать собственную версию контракта, а не выдавать вышеуказанный JSON за A2A payload.

### AgentTaskResult

- `task_id`, `status`, `completed_at`, `artifacts[]`, `error_code`, `resource_usage`, `trace_ref`;
- у каждого artifact: ID, digest, media type, schema version, classification, ACL reference, provenance/producer, URI для выдачи по правам;
- текстовые сообщения между агентами не считаются официальными результатами задачи;
- `status=completed` допустим только после валидации output_schema (если задана) и сохранения артефактов.

### Durable Task Ledger

Минимальные статусы: `queued`, `running`, `needs_input`, `completed`, `failed`, `cancelled`. `timeout`/`retry_count` — поля или reason codes, а не обязательные новые статусы. Предусмотреть lease/expires для running, попытки, конечные ошибки и ссылки на проверяемые результаты.

Допустимые переходы: queued→running/cancelled; running→needs_input/completed/failed/cancelled; needs_input→queued/cancelled. Не переводить failed обратно в running под тем же attempt без явного протокола возобновления; retry — новая попытка с тем же idempotency domain key либо новое task id по описанной policy. Для внешнего A2A mapper проверять семантику A2A `TaskState` и хранить несовпадающие состояния в reason codes; нельзя предполагать идентичность перечислений.

## 4. Контракт вызывающего adapter

```python
class AgentProvider(Protocol):
    def capabilities(self) -> AgentDescriptor: ...
    def submit(self, task: AgentTask) -> AgentHandle: ...
    def status(self, handle: AgentHandle) -> AgentTaskStatus: ...
    def cancel(self, handle: AgentHandle) -> None: ...
    def collect(self, handle: AgentHandle) -> AgentTaskResult: ...
```

В компактном профиле `submit()` может вызывать функцию внутри процесса. В распределённом — адаптер A2A, RPC или durable job. Streaming и resume опциональны и объявляются в `supported_modes`. Асинхронное выполнение должно оставлять в Ledger состояние, не зависящее от существования HTTP/WebSocket-соединения пользователя.

Минимальное техническое размещение: `Task API + Task Ledger adapter + Artifact Store adapter + AgentRegistry`. Брокер и отдельный orchestrator service не вводить до появления подтверждённой потребности.

## 5. Правила делегирования

1. **Наследование контекста по ссылкам:** агент получает goal + минимальный перечень разрешённых `context_refs`, а не всю историю сообщений/вики/чата.
2. **Предельные права:** допустимые операции = пересечение **полных ролевых/предметных предикатов** инициатора, requesting/target agent и ограничений задачи (плюс актуальные права системы-владельца). Поле `effective_scope` в DTO — информационная заявка/ограничение, **не доверенное разрешение**; нельзя склеивать `scope` одной роли с `targets` другой. Администратор/агент не повышает scope текстом задания.
3. **Проверка источника:** service identity целевого runtime + доверенная связь с initiator; нельзя доверять значениям `roles`, `subject_id` из A2A message.
4. **Human-in-the-loop:** подтверждение критических side effects создаётся на уровне Capability/Domain Gateway и проверяется при фактическом исполнении; LLM или принимающий агент не могут «подтвердить» собственный side effect.
5. **Дедупликация и идемпотентность:** повторный submit и повторное событие после сетевой ошибки не должны дублировать операцию записи.
6. **Счётчики и квоты:** max depth, child tasks, runtime/cost, retry/backoff и expiry. Для неизвестного провайдера вызов не выполняется.
7. **Cancellation:** best effort для runtime, обязательная фиксация terminal status в ledger; отмена не обещает автоматический rollback уже совершённой бизнес-операции.
8. **Ошибки и завершение:** отказ одной подсистемы не должен делать результат незаметно успешным; consumer опирается на Task Ledger и artifacts, а не исключительно на эфемерные stream events.
9. **Classifications:** результат получает не более открытый уровень, чем допустим по источникам и политике; межагентная передача чувствительных данных — отдельная egress-проверка.
10. **Изоляция:** coding agents работают в sandbox с урезанными токенами и сетевыми ACL; trusted production access предоставляется только инструментам/approval flow.

## 6. Типовые сценарии

### Сценарий A: интервью → анализ → Wiki

1. Telegram или Web принимает сообщение участника с доверенной привязкой к project/room.
2. Channel Adapter создаёт `AgentTask(capability=discovery.interview)`.
3. Discovery Agent через Knowledge API получает разрешённые вопросы и проверенные ранее факты.
4. Чувствительную исходную стенограмму при необходимости хранят отдельно; безопасная тематическая выдержка **сразу** обновляет рабочую Wiki.
5. Агент формирует `knowledge.proposal` с цитатами, scope и metadata, архивирует артефакт в Task Ledger.
6. При обнаружении неясности агент помечает страницу needs_confirmation без блокирования работы; утверждение официального регламента выполняется отдельно.
7. При необходимости агент делегирует узкую задачу reviewer через `AgentTask`; последний видит только разрешённые ссылки.

### Сценарий B: создание задачи Bitrix24

1. Агент готовит `tasks.create` с полями и ожидаемым владельцем задачи.
2. TaskProvider проверяет user grants и требуемое подтверждение, не принимает `author_id` как полномочие.
3. После подтверждения вызов Bitrix24 идемпотентно исполняется с correlation key и сохраняет внешний task id.
4. В Wiki попадает при необходимости **знание о процессе**, но не обязательная полная копия карточки задачи.

### Сценарий C: сложная разработка несколькими агентами

1. Lead Agent выбирает Pi/Claude review или implementation provider через AgentRegistry (не по произвольному URL).
2. Разбивает задачу на контрактные независимые пакеты с write-scope и budget.
3. Каждая задача выполняется в изолированном рабочем дереве/контейнере; результат — commit/patch, test report, decision artifact.
4. Независимый reviewer получает diff + контекст, не полный репозиторий без нужды.
5. Lead Agent объединяет только проверенные артефакты через обычный Git/CI; runtime сам не имеет прав на production deployment.

## 7. Протоколы: граф постепенного включения

**MVP:** один agent provider и простой локальный Task/Result интерфейс, без обязательного DB ledger для коротких синхронных действий. Ledger — только для долгих/восстанавливаемых задач; A2A/MCP по необходимости. Описания agents готовы к экспорту как A2A Agent Card.

**Stage 2:** минимум один настоящий внешний A2A peer (Pi/Claude adapter либо отдельный agent server), contract tests для Task/Artifact/error/cancel/auth. Только тогда поднимать A2A ingress/egress.

**Stage 3:** дополнительные агенты, разные организации/границы доверия, durable asynchronous jobs, optional event transport и более продвинутая маршрутизация.

Это позволяет изначально **запроектировать** стандарт A2A, не реализуя преждевременно весь набор функций его спецификации.

## 8. Acceptance tests

- Два разных AgentProvider исполняют одно типизированное задание и возвращают одинаковый валидируемый result schema.
- Внешний незарегистрированный Agent Card/URL отклоняется.
- Перехват/подмена `subject_id`, `roles` и чужого `installation_id` не расширяет права.
- Ограничение бюджета/глубины обрывает бесконечное делегирование.
- Сбой сети + повторная доставка не приводит к двойной записи в Bitrix/БД.
- Внешнему reviewer не передаются секреты, сырые интервью или лишние документы.
- При перезапуске coordinator ожидающие задания сохраняются и доводятся до терминального состояния по явно заданной retry-policy.
- Неавторизованный участник группового чата не видит artifact из другой комнаты, даже зная его ID.
- Отмена и таймаут логируются; для исполненных side effects нет ложного «отката».
- Полный A2A compatibility suite запускается только для реально реализованного сетевого adapter, не для локального интерфейса.

## 9. Открытые вопросы

- Будет ли A2A server публичным в пределах сети заказчика или останется внутри доверенного контура? По умолчанию — внутри.
- Нужны ли межорганизационные агентные задачи? По умолчанию — нет.
- Какие виды задач должны поддерживать `resume`, а какие достаточно безопасно перезапускать?
- Кто утверждает external egress для SaaS-моделей в каждом внедрении?
- Нужна ли независимая транзакционная долговечность agent task store от основного Web Chat? По умолчанию — одна БД/локальный ledger по профилю.

## 10. Источники стандартов

- A2A v1.0: https://a2a-protocol.org/v1.0.0/specification/
- MCP specification: https://modelcontextprotocol.io/specification
- AG-UI docs: https://github.com/ag-ui-protocol/ag-ui
- LangGraph persistence: https://langchain-ai.github.io/langgraph/concepts/durable_execution/

## 11. Подключение LBS Access (v3.3)

- Trust boundary: `AgentProvider` получает только проверенные actor/delegation references; `AgentTask.initiator.subject_ref`, `effective_scope`, `policy_ref` не являются авторизацией сами по себе. Любое право подтверждается актуальным `AuthorizationProvider` и `DomainPolicy`.
- Для внешнего A2A/MCP используются проверенные идентичности сервисов, `installation_id`, audience, short TTL и revocation; запрещено принимать роли или пользователей из payload как authority.
- AI-agent не может менять роли, privileged flags, оргструктуру пользователя, AD identity через tool в базовом профиле (пока отдельным утверждённым ADR это не разрешено); подготовить/открыть редактор допускается.
- Для действия, вызванного из группового чата, критерий допустимой аудитории проверяется до retrieval и до публикации результата. Unverified Telegram group audience = только общедоступные материалы/санитизированный ответ.
- Долгие задачи переживают изменение ролей: критическое изменение повторно проверяет полномочия **непосредственно перед side effect**, не используя устаревший scope начала задачи.

См. `07_ACCESS_ARCHITECTURE.md` и `08_ACCESS_MIGRATION_AND_TESTS.md`; не дублировать их policy engine в Task Ledger.

## 12. Упрощение начального Agent Runtime (v3.4)

Контракт AgentTask заранее сохраняем, но не превращаем его в новый LangGraph. Один агент вызывает инструменты напрямую; устойчивое хранение задач, A2A и независимые сервисы вводятся после конкретного сценария делегирования. Рабочее знание из интервью записывается сразу, а review-реестр не является частью цикла выполнения агента. См. [09_PROGRESSIVE_COMPLEXITY_AND_OPENFGA.md](09_PROGRESSIVE_COMPLEXITY_AND_OPENFGA.md).

## 13. Privacy boundary перед контекстом агента (v3.4)

Отбор доступного источника и подготовка текста для LLM — разные проверки. `SourceObjectEnvelope.text` и raw `adapter.render_envelope` не становятся безопасными от проверки `adapter.can_access`. Каждая агентная отправка использует SafeProjection по назначению; `title`, ссылки и метаданные тоже проверяются. При невозможности обязательной подготовки — контролируемый отказ для конкретного объекта, **никогда raw fallback**. Перед первым Git commit рабочего знания действует то же правило; реестр подтверждений не заменяет privacy gate. [10_CONTENT_PRIVACY_PIPELINE.md](10_CONTENT_PRIVACY_PIPELINE.md).
