# Модульные AI skills и registry-driven MCP-фасад

## Статус

Implemented MVP, awaiting owner acceptance.

Архитектурное решение: `docs/adr/ADR-0021-module-registered-agent-skills-and-mcp-facade.md`.

Workflow-блок: `workflow/active/module-registered-agent-skills-and-mcp-facade/`.

## Цель

Убрать доменные правила открытия объектов из общего agent runtime и заменить их модульными skills, которые регистрируют сами модули.

Дополнительно подготовить существующий MCP-сервер к registry-driven модели, чтобы tools, resources и skills не дублировались вручную.

## Пользовательская ценность

- Пользователь может сказать: "Открой заявку №17", "Открой ее справа", "Покажи запись листа ожидания".
- ИИ использует модульный skill, находит объект доступными tools и открывает его через общий `ui.open_right_panel`.
- Новый модуль добавляет свой skill и provider без правок AI-ядра.
- Внешний MCP-клиент в будущем сможет видеть те же возможности через стандартный протокол.

## Принципы

1. Skill описывает workflow, tool выполняет действие.
2. Модуль сам регистрирует свои skills.
3. Общий runtime не знает доменные правила заявок, листа ожидания и будущих модулей.
4. MCP не становится обязательной внутренней прослойкой sidebar chat.
5. Существующий MCP-сервер не дублирует tools руками, а строится из реестров.
6. Пользователь не может загружать произвольные skills.
7. Все права, подтверждения и аудит остаются в Django gateway.
8. Администраторские runtime skills создаются только через доверенный файловый контракт или audited tool.

## Не цели

- Не мигрировать весь agent runtime на OpenAI Agents SDK в этом этапе.
- Не вводить multi-agent/handoff по модулям.
- Не делать MCP основным внутренним транспортом между runtime и Django.
- Не открывать внешний MCP endpoint без отдельного решения по auth/deployment.
- Не добавлять произвольный пользовательский каталог skills.
- Не реализовывать `ui.resolve_open_target` в MVP, но подготовить интерфейсы к нему.

## Целевая архитектура

```text
Модуль
  -> apps/<module>/ai_skills.py
  -> register_agent_skill(...)
  -> apps.core.ai_skills
  -> apps.ai.skills_service
  -> services.agent_runtime activate_skill
  -> Django AI gateway tools
  -> ui.open_right_panel
```

MCP-фасад:

```text
apps.ai.tool_definitions + apps.core.ai_skills + module capabilities
  -> services.agent_runtime.mcp_server
  -> MCP tools/resources
```

Жизненный цикл регистрации:

```text
module skill:
  Django startup -> AppConfig.ready() -> register_agent_skill(...)

runtime contract skill:
  data/contracts/ai/skills/<skill_id>/SKILL.md
  -> discover_skills() при запросе каталога
  -> validation
  -> catalog entry
  -> activate_skill(skill_id)
```

Администраторский meta-skill:

```text
admin describes desired skill
  -> ai.skill_creator
  -> validates name/description/tools/body
  -> ai.skills.create_or_update, если есть ai.manage_skills
  -> atomic write to data/contracts/ai/skills/<skill_id>/SKILL.md
  -> cache reset + audit
```

## Этапы реализации

### Этап 1. Core registry для AI skills

Статус: implemented.

Задачи:

- добавить `apps/core/ai_skills.py`;
- определить `AgentSkillProvider` и `AgentSkillDescriptor`;
- добавить `register_agent_skill`, `unregister_agent_skill`, `get_agent_skill`, `registered_agent_skills`;
- поддержать `source_code`, `object_types`, `required_tools`, `trigger_examples`;
- сделать fail-closed поведение для неизвестных skills;
- добавить unit-тесты в `apps.core.tests`.

Проверки:

```bash
.venv/bin/python manage.py test apps.core.tests
.venv/bin/python manage.py check
```

### Этап 2. Интеграция `skills_service`

Статус: implemented.

Задачи:

- переделать `apps/ai/skills_service.py`, чтобы каталог собирался из:
  - module-registered skills;
  - `data/contracts/ai/skills`;
  - `contracts/ai/skills`;
- сохранить строгую allow-list для `skill_id`;
- возвращать расширенный catalog entry;
- загружать тело skill через provider или `SKILL.md`;
- добавить фильтрацию по доступности для пользователя, если skill provider ее объявляет;
- определить момент регистрации runtime contract skills как discovery при запросе каталога;
- добавить короткий cache TTL или явный cache reset, если discovery окажется дорогим;
- не требовать restart для новых runtime contract skills;
- обновить tests для `AISkillCatalogView` и `AISkillLoadView`.

Проверки:

```bash
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python manage.py check
```

### Этап 3. Модульные skills для `workorders` и `waiting_list`

Статус: implemented.

Задачи:

- добавить `apps/workorders/ai_skills.py`;
- зарегистрировать skill `workorders.open_right_panel`;
- добавить `apps/waiting_list/ai_skills.py`;
- зарегистрировать skill `waiting_list.open_right_panel`;
- подключить регистрацию в `AppConfig.ready()`;
- в skill body описать:
  - когда использовать;
  - когда не использовать;
  - порядок `ui.get_current_context`, доменного get/search и `ui.open_right_panel`;
  - работу с "ее/его/это/текущая карточка";
  - правила неоднозначности;
  - краткий ответ после успешного открытия.

Проверки:

```bash
.venv/bin/python manage.py test apps.workorders.tests apps.waiting_list.tests apps.ai.tests
```

### Этап 4. Runtime prompt и удаление hard-coded shortcut

Статус: implemented.

Задачи:

- обновить `services/agent_runtime/prompting.py`:
  - общий prompt должен говорить использовать skills для модульных workflows;
  - убрать доменные примеры, которые лучше жить в module skill;
  - оставить общие правила `ui.get_current_context` и `ui.open_right_panel`;
- удалить временный shortcut по заявкам из `services/agent_runtime/graph.py`;
- проверить, что `activate_skill` работает одинаково в `run_agent` и `stream_agent`;
- добавить runtime tests на catalog, activation и отсутствие доменной ветки.

Проверки:

```bash
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
.venv/bin/python manage.py test apps.ai.tests
```

### Этап 5. Registry-driven MCP tools/resources

Статус: implemented.

Задачи:

- описать минимальный внутренний helper для регистрации MCP tools из существующего tool registry;
- убрать ручное дублирование там, где это безопасно сделать без потери typed signatures;
- добавить MCP resources:
  - `local-business://skills/{skill_id}`;
  - `local-business://tools/{tool_code}`;
  - `local-business://modules/{source_code}/capabilities`;
- resources должны быть read-only и безопасными;
- не открывать новые внешние deployment-инструкции без отдельного решения по auth.

Проверки:

```bash
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
.venv/bin/python manage.py check
curl -fsS http://127.0.0.1:8090/health
```

### Этап 6. Admin skill creator и управляемое создание runtime skills

Статус: implemented.

Задачи:

- добавить доверенный module/system skill `ai.skill_creator`;
- описать в skill body:
  - как администратор формулирует назначение skill;
  - как выбрать `name`, `description`, `source_code`, `object_types`, `required_tools`, `trigger_examples`;
  - как отличить workflow-инструкции от tool schema;
  - когда нельзя создавать skill;
  - что делать при неоднозначном или опасном описании;
- добавить write-tool `ai.skills.create_or_update` или management command с тем же service-layer методом;
- ограничить tool правом `ai.manage_skills`;
- разрешить только instruction-only `SKILL.md`;
- валидировать `required_tools` по tool registry;
- писать в `data/contracts/ai/skills/<skill_id>/SKILL.md` атомарно;
- сбрасывать skill catalog cache после успешной записи;
- добавить audit без секретов и без необработанных чувствительных данных;
- добавить list/validate/reload command:
  - `ai_skill_list`;
  - `ai_skill_validate`;
  - `ai_skill_reload`.

Проверки:

```bash
.venv/bin/python manage.py test apps.ai.tests apps.core.tests
.venv/bin/python manage.py check
```

### Этап 7. E2E, документация и приемка

Статус: implemented.

Задачи:

- e2e: sidebar chat "Открой заявку №17";
- e2e: после ответа про заявку "открой ее в правом сайдбаре";
- e2e: аналогичный сценарий для листа ожидания;
- e2e: неизвестный или недоступный объект не открывается;
- e2e или integration test: администратор создает instruction-only skill из описания;
- e2e или integration test: пользователь без `ai.manage_skills` не может создать skill;
- обновить `docs/guides/AI_SIDEBAR_CHAT.md`;
- добавить guide по созданию runtime skills;
- обновить `services/agent_runtime/README.md`, если меняется MCP contract;
- подготовить executor report и acceptance.

Проверки:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.core.tests apps.ai.tests apps.workorders.tests apps.waiting_list.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
npm run test:e2e -- --project=chromium --grep "sidebar"
make gen-struct
```

## Критерии готовности

- `workorders` и `waiting_list` регистрируют skills из своих модулей.
- `skills_service` видит module skills и файловые skills.
- Runtime contract skill появляется после discovery без restart.
- Есть `ai.skill_creator`, который помогает администратору создать instruction-only skill.
- Запись runtime skill проходит только через `ai.manage_skills`, атомарную запись и audit.
- Агент может активировать module skill и открыть объект справа.
- В `services/agent_runtime/graph.py` нет hard-coded ветки для заявок.
- MCP resources отдают безопасные описания skills/tools/capabilities.
- Existing MCP endpoint продолжает отвечать.
- Все права и аудит остаются в Django gateway.
- E2E покрывает открытие заявки и записи листа ожидания через sidebar chat.

## Риски

- Модель может не выбрать skill по описанию. Снижение риска: хорошие `description`, trigger examples и e2e prompts.
- Skill body может начать дублировать tool schema. Снижение риска: держать в skill workflow, а в tool description side effects и inputs.
- Администратор может создать слишком широкий skill. Снижение риска: `ai.skill_creator` должен требовать узкий scope, positive/negative examples и список required tools.
- MCP может разрастись. Снижение риска: публиковать только tools/resources, которые реально нужны.
- Ручное удаление hard-coded shortcut может вернуть регрессию. Снижение риска: сначала добавить module skills и e2e, затем удалить shortcut.

## Deferred

- `ui.resolve_open_target`;
- MCP prompts;
- внешний MCP auth/deployment profile;
- version pinning runtime contract skills;
- scripts/assets для runtime contract skills;
- UI Settings Center для просмотра, отключения и истории runtime skills;
- отдельные specialist agents.
