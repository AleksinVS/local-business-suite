# AI-First / Code-First Remediation Plan

Дата: 2026-03-27
Проект: `local-business-suite`

## Цель

Перевести проект из состояния `хороший AI-каркас с drift между декларациями и кодом` в состояние, где:

- сильная облачная модель проектирует и режет bounded slices;
- слабая локальная модель может безопасно выполнять доработки через skills;
- JSON-контракты реально управляют исполнением;
- review и handoff меньше зависят от памяти модели.

## Принципы выполнения

- Делать изменения bounded slices, по одному архитектурному контуру за раз.
- Сначала устранять contract drift, потом расширять tool coverage.
- Не добавлять новые AI-возможности до стабилизации execution policy.
- Каждый slice завершать кодом, тестами, обновлением документации и отдельным commit.

## Приоритет 0. Репозиторий должен воспроизводиться из коробки

### Проблема

Локальный цикл проверки зависит от заранее подготовленной среды и не является достаточно self-hosting.

### Что сделать

- Добавить явный bootstrap path:
  - `make venv`
  - `make install`
  - `make test`
- Зафиксировать единый путь установки для Django и agent runtime.
- Обновить README/handoff так, чтобы слабая локальная модель могла поднимать среду без догадок.

### Выход slice

- воспроизводимый setup для `.venv`;
- документированный install flow;
- smoke-check команды, которые реально работают в чистом окружении.

## Приоритет 1. Сделать tool catalog реальным source of truth

### Проблема

`config/ai/tools.json` и фактические Python-реализации уже расходятся.

### Что сделать

Выбрать один из двух вариантов и зафиксировать его архитектурно:

1. `catalog-first`
   Генерировать runtime/gateway tool adapters из декларативного каталога.

2. `code-first with generated contracts`
   Держать tool definitions в Python и генерировать `config/ai/tools.json` из них.

Для этого проекта прагматичнее второй путь:

- определить canonical Python representation для tool definitions;
- генерировать JSON registry из кода;
- валидировать, что runtime/Django/MCP используют одинаковую сигнатуру.

### Минимальный scope

- синхронизировать `workorders.list`;
- синхронизировать `workorders.create`;
- убрать или реализовать все задекларированные, но неподдержанные поля;
- унифицировать структуру `outputs`.

### Выход slice

- один canonical tool definition layer;
- no drift между registry, gateway, runtime и MCP;
- тест, который падает при рассинхронизации сигнатуры.

## Приоритет 2. Перенести confirmation policy из prompt в код

### Проблема

Подтверждение write-действий не enforced, а только “рекомендуется” prompt-ом.

### Что сделать

- Ввести явную модель pending action:
  - intent resolved
  - arguments prepared
  - confirmation required
  - confirmed or cancelled
  - execution completed
- Добавить server-side confirmation token или persisted pending action record.
- Запретить непосредственное выполнение write-tools без подтверждения, если tool/task type этого требует.
- Разрешить bypass только для явно помеченных safe-write случаев, если это отдельное архитектурное решение.

### Минимальный scope

- `workorders.create`
- `workorders.transition`

### Выход slice

- кодовый gate перед write execution;
- audit trail с фазами `requested`, `awaiting_confirmation`, `confirmed`, `executed`, `cancelled`;
- тесты на bypass prevention.

## Приоритет 3. Сделать task types исполняемым слоем, а не справочником

### Проблема

`task_types.json` сейчас не управляет runtime.

### Что сделать

- использовать task type как явный orchestration contract;
- проверять:
  - allowed tools;
  - required slots;
  - optional slots;
  - output mode;
  - requires confirmation.
- В runtime хранить resolved task type и текущий slot state.
- Добавить deterministic slot resolution helpers для частых сценариев.

### Минимальный scope

- `workorders.list`
- `workorders.create`
- `workorders.transition`

### Выход slice

- runtime, который может объяснимо ответить, какой task type выбран;
- стабильный slot-filling path;
- меньшая зависимость от свободной интерпретации prompt.

## Приоритет 4. Усилить identity model и correlation

### Проблема

В реестре identity богаче, чем в реальном runtime и журналах.

### Что сделать

- ввести обязательные поля:
  - `conversation_id`
  - `request_id`
  - `origin_channel`
  - `actor_version` или аналогичный trace marker
- передавать их через:
  - Django chat surface
  - runtime request schema
  - gateway execution payload
  - action log
- хранить их в `ChatSession.metadata`, `ChatMessage.metadata` и `AgentActionLog`.

### Выход slice

- сквозная correlation chain;
- возможность разбирать конкретный агентский запрос end-to-end;
- лучшая база для skills и локальных handoff-процедур.

## Приоритет 5. Перевести tool outputs к строгой структурированной форме

### Проблема

Runtime tools сейчас конвертируют structured results в строки.

### Что сделать

- возвращать из tools строгий JSON-compatible объект;
- унифицировать envelope:
  - `ok`
  - `tool`
  - `result`
  - `errors`
  - `meta`
- отделить human-readable formatting от machine-readable payload.

### Выход slice

- слабая локальная модель получает стабильную структуру;
- уменьшается количество ошибок следующих tool calls;
- улучшается совместимость с MCP clients и skills.

## Приоритет 6. Сделать schema layer действительно полезным

### Проблема

Текущие schema-файлы и Python validators слишком поверхностны.

### Что сделать

- описать полную структуру tool registry, task type registry и AI registry;
- добавить семантические проверки:
  - все `allowed_tools` существуют;
  - все `required_slots` допустимы;
  - tools, помеченные как write, имеют согласованную confirmation policy;
  - identity minimum fields реально присутствуют в runtime schema;
  - declared outputs согласованы с serializer/result envelope.
- Добавить validation command, который проверяет не только JSON shape, но и code-contract alignment.

### Выход slice

- schema layer перестаёт быть декоративным;
- локальная модель и skills получают надёжную опору;
- drift ловится до исполнения.

## Приоритет 7. Подготовить agent-facing delivery protocol для слабой локальной модели

### Проблема

В проекте есть handoff-документы, но нет жёсткого, короткого execution protocol для слабой модели.

### Что сделать

- создать отдельный `AGENTS.md` или эквивалентный canonical agent brief;
- добавить короткие обязательные правила:
  - где source of truth;
  - как поднимать среду;
  - как выбирать bounded slice;
  - какие команды обязательны перед commit;
  - какие JSON-контракты нельзя менять без синхронизации кода;
  - как обновлять handoff и change plan.
- Подготовить skills, которые опираются только на реально enforced артефакты.

### Выход slice

- локальная модель меньше “думает”, больше следует протоколу;
- снижается стоимость handoff;
- повышается повторяемость результатов.

## Рекомендуемая последовательность слайсов

1. Bootstrap and reproducibility
2. Canonical tool definitions
3. Write confirmation enforcement
4. Executable task types
5. Identity and correlation
6. Structured tool outputs
7. Strong schema and alignment validation
8. Agent protocol and weak-model skills

## Что не стоит делать сейчас

- Не расширять tool catalog новыми write-actions до фикса confirmation flow.
- Не добавлять новые chat frontends до стабилизации contracts.
- Не пытаться сразу сделать “универсального агента”.
- Не компенсировать архитектурные дыры только prompt engineering.

## Definition of Done для перехода к устойчивой agent-driven разработке

Проект можно считать готовым к стабильной схеме `cloud strong model -> local weak model + skills`, когда одновременно выполнены условия:

- tool catalog и код синхронизируются автоматически;
- write-tools не исполняются без code-enforced confirmation policy;
- task types реально участвуют в orchestration;
- identity/correlation проходит через весь стек;
- tool outputs строго структурированы;
- contract validation ловит drift до runtime;
- bootstrap окружения воспроизводим из чистого checkout;
- у локальной модели есть короткий canonical execution protocol, опирающийся на реально enforced правила.
