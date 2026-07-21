# AI-First / Code-First Review

Дата: 2026-03-27
Проект: `local-business-suite`
Контекст ревью: разработка сильной облачной моделью, дальнейшее использование и доработка слабой локальной моделью через заранее подготовленные skills.

## Итоговая оценка

Проект уже выглядит как хороший каркас для AI-слоя: есть Django как system of record, отдельный runtime, tool gateway, JSON-контракты, handoff-документы и базовые архитектурные валидаторы.

Но в текущем состоянии это скорее `docs-first with code around it`, чем полноценный `ai-first + code-first` контур. Основная проблема не в отсутствии идей, а в том, что декларативные артефакты пока не управляют исполнением достаточно жёстко. Сильная облачная модель это частично компенсирует, слабая локальная модель не компенсирует.

## Findings

### 1. Tool catalog не является реальным source of truth

`config/ai/tools.json` обещает больше, чем реально поддерживают gateway и runtime.

Примеры:

- `workorders.list` задекларирован с фильтрами `department_id`, `assignee_id`, `author_id`, `query`, `priority` и выходом `count`.
- Реальный `apps/ai/tooling.py` прокидывает только `status` и `limit`.
- `apps/ai/services.py` тоже поддерживает только `status` и `limit`.
- `services/agent_runtime/tools.py` и `services/agent_runtime/mcp_server.py` повторяют ту же урезанную форму.
- `workorders.create` в каталоге заявлен с `device_id`, но runtime tool не принимает его аргументом.

Следствие:

- локальная слабая модель со skill, который опирается на `config/ai/tools.json`, будет регулярно генерировать некорректные вызовы;
- контракты нельзя безопасно использовать как единственный слой навигации для агента;
- handoff между моделями будет терять надёжность.

Ключевые ссылки:

- `config/ai/tools.json`
- `apps/ai/tooling.py`
- `apps/ai/services.py`
- `services/agent_runtime/tools.py`
- `services/agent_runtime/mcp_server.py`

### 2. Confirmation policy существует в документах и prompt, но почти не существует в исполнении

В проекте декларируется, что write-операции требуют подтверждения:

- в `config/ai/tools.json`;
- в `config/ai/task_types.json`;
- в `config/ai/registry.json`;
- в system prompt runtime.

Но фактический `LangGraph`-контур в `services/agent_runtime/graph.py` не содержит явного состояния подтверждения, отдельного approval step, confirmation token, server-side enforcement или промежуточного execution gate.

Сейчас логика примерно такая:

1. модель решает вызвать tool;
2. runtime сразу вызывает tool;
3. gateway исполняет действие, если policy слоя Django разрешает его.

Это не human-in-the-loop orchestration. Это prompt-mediated compliance.

Следствие:

- безопасность write-path зависит от дисциплины конкретной модели;
- слабая локальная модель будет ошибаться чаще, чем сильная облачная;
- архитектурное обещание и фактическое поведение расходятся в самом рискованном месте.

Ключевые ссылки:

- `config/ai/registry.json`
- `config/ai/tools.json`
- `config/ai/task_types.json`
- `services/agent_runtime/graph.py`
- `services/agent_runtime/prompting.py`
- `services/agent_runtime/prompts/hospital_system_prompt.txt`

### 3. Task types и машиночитаемые AI-артефакты пока в основном декоративны

`config/ai/task_types.json` содержит полезные поля:

- `allowed_tools`
- `required_slots`
- `optional_slots`
- `requires_confirmation`
- `output_mode`

Но runtime их не использует как исполняемую оркестрационную схему.

Дополнительно:

- `services/agent_runtime/config.py` по умолчанию всегда грузит внешний system prompt файл;
- fallback-режим, где prompt собирается из каталогов tools/task types, остаётся фактически нерабочим как основной контур;
- `apps/core/json_utils.py` проверяет в основном наличие ключей и базовые типы, но почти не проверяет семантическую согласованность между каталогами и runtime.

Следствие:

- локальная слабая модель не может опираться на эти JSON-артефакты как на строгую операционную спецификацию;
- skills неизбежно будут содержать дополнительную скрытую логику и knowledge drift;
- проект рискует накапливать параллельные истины: код, prompt, JSON, handoff.

Ключевые ссылки:

- `config/ai/task_types.json`
- `services/agent_runtime/config.py`
- `services/agent_runtime/prompting.py`
- `apps/core/json_utils.py`
- `config/schemas/*.json`

### 4. Identity model и audit trail недотянуты до уровня многоагентной разработки

В `config/ai/registry.json` декларируется minimum identity context:

- `user_id`
- `roles`
- `session_id`
- `conversation_id`
- `request_id`

Но фактически:

- `services/agent_runtime/schemas.py` не требует `conversation_id` и `request_id`;
- `apps/ai/runtime_client.py` их не передаёт;
- `apps/ai/models.py` не хранит отдельные correlation identifiers для трассировки запроса сквозь runtime и gateway.

Следствие:

- трассировка действий агента остаётся неполной;
- воспроизводимость конкретного решения по логам ограничена;
- слабая локальная модель и её skills не смогут надёжно собирать контекст прошлых запусков без дополнительного glue-layer.

Ключевые ссылки:

- `config/ai/registry.json`
- `services/agent_runtime/schemas.py`
- `apps/ai/runtime_client.py`
- `apps/ai/models.py`
- `apps/ai/views.py`

### 5. JSON Schema слой слишком слабый, чтобы быть опорой code-first разработки

В `config/schemas/*.schema.json` присутствуют только очень тонкие схемы верхнего уровня. Например, schema для tool registry проверяет только наличие ключей верхнего уровня и не описывает структуру каждого tool, типов входов, связей между task types и tools, confirmation semantics или identity requirements.

Следствие:

- проект заявляет contract-driven подход, но не получает от schema-слоя реальной защиты от drift;
- локальная слабая модель не сможет безопасно опираться на schema validation как на источник истины;
- ошибки будут выявляться поздно, по факту выполнения.

Ключевые ссылки:

- `config/schemas/chat_agent_tools.schema.json`
- `config/schemas/chat_agent_task_types.schema.json`
- `config/schemas/chat_agent_registry.schema.json`
- `apps/core/json_utils.py`

### 6. Tool outputs ориентированы на LLM-удобство, а не на строгую машинную интеграцию

На стороне Django результаты ещё возвращаются как структуры JSON, но runtime tools в `services/agent_runtime/tools.py` сразу превращают результат в `str(result["result"])`.

Это ухудшает:

- предсказуемость последующей обработки;
- совместимость со слабыми моделями;
- стабильность форматирования;
- возможность строить поверх tools детерминированные skills и промежуточные резолверы.

Следствие:

- сильная модель ещё сможет восстановить структуру из строки;
- слабая локальная модель будет чаще терять поля, путать типы и принимать неверные решения на следующем шаге.

Ключевые ссылки:

- `services/agent_runtime/tools.py`
- `services/agent_runtime/graph.py`
- `apps/ai/services.py`

### 7. Репозиторий пока недостаточно self-hosting для code-first потока

В проекте есть `Makefile`, Dockerfile и тесты, но локально из текущего состояния репозитория проверка не стартует без отдельной подготовки среды:

- `Makefile` жёстко ожидает `./.venv/bin/python`;
- в текущем окружении `python3` есть, но `Django` не установлен;
- это означает, что repo не гарантирует мгновенный reproducible bootstrap без явного шага setup.

Это не архитектурный дефект уровня design, но для agent-driven delivery это важный операционный дефект.

Следствие:

- слабая локальная модель будет тратить контекст и шаги на подъём среды;
- review/test loop дорожает;
- skills придётся делать более хрупкими и средозависимыми.

Ключевые ссылки:

- `Makefile`
- `requirements.txt`
- `services/agent_runtime/requirements.txt`
- `Dockerfile`
- `docker-compose.yml`

## Что в проекте уже хорошо

- Бизнес-правила и запись данных остаются в Django service/policy слое.
- Chat/runtime вынесены отдельно и не пишут напрямую в БД.
- Есть machine-readable templates для task brief и change plan.
- Есть аудит tool calls.
- Есть handoff-документация и архитектурные карты проекта.
- Есть понятный слой runtime boundary между UI, orchestration и domain services.

Это хороший фундамент. Проблема не в выборе направления, а в степени доведения этого направления до исполняемого контракта.

## Вывод

Если проект продолжит развиваться сильной облачной моделью, он сможет двигаться достаточно быстро даже в текущем виде.

Если проект должен устойчиво поддерживаться слабой локальной моделью через skills, то приоритет нужно сместить с добавления новых AI-фич на:

- устранение drift между JSON-контрактами и кодом;
- перевод confirmation policy из prompt-уровня в code-enforced execution flow;
- усиление identity/audit/correlation;
- превращение task/tool catalogs в реально исполняемые контракты;
- усиление schema validation и bootstrap reproducibility.

Без этого локальная модель будет не столько продолжать архитектуру, сколько каждый раз заново восстанавливать её по косвенным признакам.
