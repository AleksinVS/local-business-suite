# AI skills: создание и эксплуатация

Статус: implemented MVP.

Дата: 2026-05-29.

Связанные документы:

- `docs/adr/ADR-0021-module-registered-agent-skills-and-mcp-facade.md`
- `docs/planning/active/module-registered-agent-skills-and-mcp-facade.md`
- `workflow/active/module-registered-agent-skills-and-mcp-facade/`

## Назначение

AI skill описывает повторяемый workflow для агента: когда применять сценарий, какие tools вызвать, как обработать неоднозначность и что ответить пользователю. Skill не выполняет бизнес-логику сам и не выдает новых прав.

Бизнес-действия остаются в Django AI gateway. Все записи проходят service layer, confirmation flow и audit.

## Источники skills

MVP поддерживает два доверенных источника:

- module skills: код в `apps/<module>/ai_skills.py`, регистрация в `AppConfig.ready()`;
- runtime contract skills: файл `data/contracts/ai/skills/<skill_id>/SKILL.md`.

Runtime skill считается зарегистрированным при следующем discovery каталога. Restart не нужен; если включен кэш, его сбрасывают командой `ai_skill_reload` или tool записи делает это автоматически.

## Module skill

Минимальный модульный skill:

```python
from apps.core.ai_skills import AgentSkillDescriptor, register_agent_skill


def register() -> None:
    register_agent_skill(
        AgentSkillDescriptor(
            skill_id="module.open_right_panel",
            name="module-open-right-panel",
            description="Используй, когда пользователь просит открыть объект модуля справа.",
            source_code="module",
            object_types=("record",),
            required_tools=("ui.get_current_context", "ui.open_right_panel"),
            trigger_examples=("Открой запись 12", "Открой ее справа"),
            body="Workflow instructions...",
        ),
        replace=True,
    )
```

Регистрация:

```python
def ready(self):
    from . import ai_skills, right_panel, source_adapter

    ai_skills.register()
    right_panel.register()
    source_adapter.register()
```

## Runtime skill

Runtime skill хранится как один файл `SKILL.md`. В MVP запрещены `scripts/`, `assets/` и произвольные дополнительные файлы.

```md
---
name: module-open-right-panel
description: Используй, когда пользователь просит открыть видимую запись модуля справа.
source_code: module
object_types: record
required_tools: ui.get_current_context, ui.open_right_panel
trigger_examples: Открой запись 12; Открой ее справа
---

# Открытие записи

Опиши workflow, правила неоднозначности и безопасный ответ.
```

`description` должна быть достаточно точной, чтобы агент выбрал skill без чтения тела. `required_tools` должны уже существовать в tool registry.

## Создание администратором

Агент имеет системный skill `ai.skill_creator`. Он помогает составить узкий instruction-only skill и при наличии права вызывает write-tool:

- tool: `ai.skills.create_or_update`;
- право: `ai.manage_skills`;
- запись: атомарно в `data/contracts/ai/skills/<skill_id>/SKILL.md`;
- аудит: через `AgentActionLog`, без полного body в audit payload.

Пользователь без права может получить черновик `SKILL.md`, но tool записи будет отклонен после confirmation.

## Команды

```bash
python manage.py ai_skill_list
python manage.py ai_skill_validate --all
python manage.py ai_skill_validate --path data/contracts/ai/skills/<skill_id>/SKILL.md
python manage.py ai_skill_reload
```

`ai_skill_reload` сбрасывает кэш только в текущем процессе команды. Web/runtime-процессы обновляют каталог при следующем discovery или после успешного write-tool.

## Rollback

Для отката runtime skill:

1. Удалите или переименуйте `data/contracts/ai/skills/<skill_id>/SKILL.md`.
2. Выполните `python manage.py ai_skill_validate --all`.
3. Выполните `python manage.py ai_skill_reload` для текущего процесса.
4. Перезапустите Django/agent runtime, если нужно принудительно сбросить память долгоживущего процесса.

Удаление через UI/Settings Center отложено на следующий этап.

## MCP resources

MCP остается внешним фасадом, не внутренним транспортом sidebar-чата.

Доступные read-only resources:

- `local-business://skills/{skill_id}`;
- `local-business://tools/{tool_code}`;
- `local-business://modules/{source_code}/capabilities`.

Resources отдают только безопасные описания: идентификаторы, descriptions, inputs/outputs, required tools и capabilities. Полное тело skill, секреты, PII и raw paths не публикуются.

## Проверка

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.core.tests apps.ai.tests apps.workorders.tests apps.waiting_list.tests
python -m unittest services.agent_runtime.tests.test_normalization
npm run test:e2e -- --project=chromium --grep "sidebar"
```
