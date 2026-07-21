# ADR-0021: Модульные AI skills и registry-driven MCP-фасад

## Статус

Accepted

## Дата

2026-05-28

## Контекст

После внедрения контекстного ИИ-чата и универсального правого сайдбара появился повторяемый сценарий:

- пользователь просит ИИ открыть объект в правом сайдбаре;
- ИИ должен понять, к какому модулю относится объект;
- модуль должен сам описывать, как искать и открывать свои объекты;
- добавление или удаление модуля не должно требовать правок в общем AI runtime.

Временная правка для заявок решила пользовательский сценарий, но добавила доменную ветку в `services/agent_runtime/graph.py`. Это ухудшает границы: agent runtime начинает знать про заявки и их номера. Для универсальной системы такое поведение нужно вынести в модульные инструкции.

В проекте уже есть несколько близких механизмов:

- `ui.open_right_panel` и `RightPanelProvider` registry;
- `SourceAdapter` registry для памяти и аналитики;
- `apps/ai/skills_service.py`, который умеет читать файловые `SKILL.md`;
- `activate_skill` в agent runtime;
- MCP-сервер в `services/agent_runtime/mcp_server.py`.

Текущий MCP-сервер вручную дублирует часть business tools. Он полезен как внешний стандартный фасад, но не должен становиться обязательной внутренней прослойкой между sidebar chat и Django gateway.

Актуальные практики OpenAI и Agent Skills:

- skill должен быть узким повторяемым workflow с `SKILL.md`, `name` и `description`;
- описание skill должно явно отвечать, когда skill применять и когда не применять;
- skills стоит подключать через progressive disclosure: сначала каталог, затем полное тело только при необходимости;
- tool-specific инструкции лучше держать в описаниях tools, а не раздувать общий system prompt;
- MCP полезен для внешнего изменяемого контекста, повторяемых интеграций и доступа к tools/resources через стандартный протокол;
- не нужно подключать весь каталог tools сразу, лучше начинать с реальных рабочих сценариев;
- skills считаются привилегированными инструкциями и не должны быть произвольным открытым каталогом для конечных пользователей.

Источники:

- https://developers.openai.com/codex/skills
- https://developers.openai.com/codex/learn/best-practices#turn-repeatable-work-into-skills
- https://developers.openai.com/codex/learn/best-practices#use-mcps-for-external-context
- https://developers.openai.com/api/docs/guides/tools
- https://developers.openai.com/api/docs/guides/tools-skills
- https://modelcontextprotocol.io/specification/2025-11-25

## Решение

Принять module-registered AI skills как ближайший механизм расширения поведения агента и подготовить существующий MCP-сервер к registry-driven фасаду.

### Ближайшая архитектура

```text
apps/<module>/ai_skills.py
  -> apps.core.ai_skills registry
  -> apps.ai.skills_service catalog/load
  -> services.agent_runtime activate_skill
  -> обычные tools через Django AI gateway
```

Каждый модуль сам регистрирует свои skills в `AppConfig.ready()`, рядом с `right_panel.register()` и `source_adapter.register()`.

Skill описывает workflow, но не выполняет бизнес-логику напрямую. Бизнес-операции остаются в tools и проходят через Django AI gateway, policies, confirmation flow и audit.

### Регистрация runtime skills

Поддерживаются два доверенных источника skills:

1. Module skills.

   Модуль регистрирует skill кодом при старте Django-процесса:

   ```text
   Django startup
     -> apps.<module>.apps.AppConfig.ready()
     -> apps/<module>/ai_skills.py:register()
     -> apps.core.ai_skills.register_agent_skill(...)
   ```

   Такой skill живет в памяти процесса и меняется через обычный code deployment.

2. Runtime contract skills.

   Администратор или Settings Center сохраняет instruction-only skill в:

   ```text
   data/contracts/ai/skills/<skill_id>/SKILL.md
   ```

   Такой skill регистрируется не отдельной записью в БД, а при discovery:

   ```text
   agent runtime requests /ai/gateway/skills/catalog/
     -> apps.ai.skills_service.discover_skills()
     -> scans apps.core.ai_skills registry
     -> scans data/contracts/ai/skills
     -> scans contracts/ai/skills
     -> returns validated catalog
   ```

   После добавления файла skill должен стать доступен на следующем запросе каталога или после истечения короткого кэша, если он будет включен. Явный restart для runtime contract skills не требуется.

Для runtime contract skills в MVP разрешаются только `SKILL.md` и instruction-only поведение. `scripts/`, `assets/` и произвольные дополнительные файлы не включаются до отдельного security-решения.

### Admin skill creator

Нужно добавить системный доверенный skill для создания skills, условно `ai.skill_creator`.

Назначение:

- объяснить администратору, как устроен `SKILL.md`;
- помочь превратить описание workflow в корректный instruction-only skill;
- проверить `name`, `description`, `required_tools`, `source_code`, `object_types` и trigger examples;
- при наличии прав вызвать отдельный write-tool для атомарного сохранения skill в `data/contracts/ai/skills/<skill_id>/SKILL.md`;
- если прав нет, подготовить проект skill и объяснить, кто может его сохранить.

Meta-skill сам не пишет файлы и не дает новых прав. Для записи нужен отдельный tool, например `ai.skills.create_or_update`, с permission `ai.manage_skills`. Tool обязан:

- принимать нормализованный `skill_id`, frontmatter и body;
- разрешать только instruction-only skills;
- валидировать, что `required_tools` существуют в tool registry;
- атомарно писать в `data/contracts/ai/skills/<skill_id>/SKILL.md` через временный файл и `os.replace`;
- сбрасывать skill catalog cache, если он включен;
- писать audit trace без секретов и без полного пользовательского содержимого, если оно может содержать чувствительные данные.

Удаление или отключение runtime skills должно быть отдельным действием с audit и, при необходимости, подтверждением.

### Подготовка к resolver-слою

Следующий архитектурный шаг после module skills: универсальный resolver для открытия объектов.

```text
user prompt
  -> module skill
  -> ui.resolve_open_target
  -> module-owned OpenTargetResolver
  -> ui.open_right_panel
```

В MVP resolver можно не реализовывать, но интерфейсы skills должны быть готовы к нему:

- `source_code`;
- `object_types`;
- `required_tools`;
- `trigger_examples`;
- понятные правила извлечения идентификатора из текущего диалога и `ui.get_current_context`.

### MCP

MCP не становится основным внутренним протоколом sidebar chat. Внутренний путь остается:

```text
browser chat
  -> Django chat views
  -> agent runtime
  -> Django AI gateway
```

Существующий MCP-сервер переводится в целевую модель:

```text
tool registry + module skills + module capabilities
  -> registry-driven MCP server
  -> external MCP clients
```

MCP должен быть внешним фасадом для:

- read/write tools с теми же policy и audit checks;
- read-only resources с безопасным описанием tools, skills и module capabilities;
- позже, prompts для внешних клиентов, если появится реальный потребитель.

### Не принимаем

Не вводим новый отдельный MCP-сервер. Существующий сервер в `services/agent_runtime/mcp_server.py` остается точкой входа, но должен строиться из общих реестров, а не из ручного списка функций.

Не переносим внутреннее выполнение sidebar chat на MCP в этом этапе.

Не создаем multi-agent архитектуру для открытия сайдбара. Для текущего сценария достаточно одного агента, skills и tools.

## Контракты

### AgentSkillProvider

```python
class AgentSkillProvider(Protocol):
    skill_id: str
    name: str
    description: str
    source_code: str
    object_types: tuple[str, ...]
    required_tools: tuple[str, ...]
    trigger_examples: tuple[str, ...]

    def is_available_for_user(self, user) -> bool: ...
    def catalog_entry(self) -> dict: ...
    def load_body(self) -> str: ...
```

### Skill catalog entry

```json
{
  "id": "workorders.open_right_panel",
  "name": "workorders-open-right-panel",
  "description": "Открывает видимую заявку в правом сайдбаре...",
  "source_code": "workorders",
  "object_types": ["workorder"],
  "required_tools": ["workorders.get", "ui.open_right_panel", "ui.get_current_context"],
  "trigger_examples": ["Открой заявку №17", "Открой ее справа"]
}
```

### Skill body

`SKILL.md` должен содержать:

- когда использовать skill;
- когда не использовать skill;
- какие tools вызывать;
- какие входные данные извлекать из сообщения, истории и `ui.get_current_context`;
- как действовать при неоднозначности;
- какие сообщения возвращать пользователю после успешного открытия;
- запрет обходить права и придумывать object_id.

### Runtime SKILL.md frontmatter

Минимальный frontmatter для runtime contract skill:

```md
---
name: workorders-open-right-panel
description: Используй, когда администратор или пользователь просит открыть видимую заявку в правом сайдбаре.
source_code: workorders
object_types: workorder
required_tools: workorders.get, ui.get_current_context, ui.open_right_panel
trigger_examples: Открой заявку №17; Открой ее справа
---
```

`description` должен быть написан так, чтобы агент мог выбрать skill без чтения полного body. `required_tools` не выдают новых прав, а только декларируют, какие tools skill собирается использовать.

### MCP resources

Запланированные read-only resources:

- `local-business://skills/{skill_id}`;
- `local-business://tools/{tool_code}`;
- `local-business://modules/{source_code}/capabilities`.

Resources не должны раскрывать секреты, PII, raw paths, внутренние токены и произвольные пользовательские данные.

## Альтернативы

### Оставить hard-coded правила в agent runtime

Плюсы:

- быстро;
- уже работает для заявок.

Минусы:

- runtime знает доменные детали;
- новые модули требуют правок AI-ядра;
- растет риск конфликтов и расползания подсказок.

Решение: временный shortcut допустим только до внедрения module skills.

### Сделать MCP основным внутренним протоколом

Плюсы:

- единый стандарт tools/resources;
- легче подключать внешних агентов.

Минусы:

- лишняя сетевая прослойка внутри уже работающего Django gateway контура;
- сложнее передавать `session_id`, `window_id`, page context и confirmation flow;
- больше surface для auth и audit ошибок;
- задерживает текущий сценарий sidebar chat.

Решение: не делать в MVP.

### Файловые skills без module registry

Плюсы:

- проще старт;
- соответствует базовому формату Agent Skills.

Минусы:

- слабее модульная ownership-модель;
- сложнее фильтровать по ролям, source_code и установленным модулям;
- сложнее удалять модуль без осиротевших skills.

Решение: разрешить файловые skills как дополнительный слой, но module registry сделать основным.

### Multi-agent/handoff по модулям

Плюсы:

- каждый домен может иметь специалиста.

Минусы:

- лишняя недетерминированность;
- больше проверок handoff;
- избыточно для открытия UI-объектов.

Решение: отложить до появления eval-доказательств.

## Последствия

Положительные:

- модули сами владеют своими AI-инструкциями;
- общий runtime освобождается от доменных веток;
- skills переиспользуются в обычном чате, sidebar chat и потенциально внешнем MCP-клиенте;
- MCP перестает дублировать tools вручную и получает путь к масштабированию;
- появляется единое место для тестирования выбора skill и tool calls.

Отрицательные:

- нужен новый registry `apps.core.ai_skills`;
- нужно писать качественные `SKILL.md`, иначе агент будет ошибаться в выборе;
- нужно дополнительно тестировать не только business tools, но и skill routing;
- MCP-фасад требует аккуратной auth/audit модели, если будет открыт внешним клиентам.

## Безопасность

- Skills регистрируются только кодом модуля или доверенными contract files.
- Конечный пользователь не получает произвольный выбор и загрузку skills.
- Runtime contract skills может создавать только администратор с правом `ai.manage_skills`.
- Admin skill creator помогает сформировать skill, но запись выполняет только отдельный audited write-tool.
- В MVP runtime contract skills являются instruction-only; scripts/assets запрещены.
- Tool execution остается за Django gateway.
- Write-tools продолжают требовать confirmation.
- MCP resources только read-only и проходят фильтрацию.
- MCP tools должны сохранять те же audit/correlation поля, что и обычный runtime.
- Неизвестный skill, tool или module capability fail-closed.

## Статус реализации

Не реализовано. Исполнительный план: `docs/planning/archive/2026/module-registered-agent-skills-and-mcp-facade.md`.
