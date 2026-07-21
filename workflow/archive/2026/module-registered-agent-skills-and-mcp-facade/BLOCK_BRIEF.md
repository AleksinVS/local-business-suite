# Workflow Brief: module-registered-agent-skills-and-mcp-facade

Статус: implemented MVP, awaiting owner acceptance.

Дата: 2026-05-28.

## Цель

Реализовать модульные AI skills, чтобы доменные workflow-инструкции для открытия объектов и работы с модулем регистрировались самим модулем, а не жили в общем agent runtime.

Одновременно подготовить существующий MCP-сервер к registry-driven модели tools/resources/skills без превращения MCP во внутреннюю обязательную прослойку sidebar chat.

## Архитектурные источники

- `docs/adr/ADR-0021-module-registered-agent-skills-and-mcp-facade.md`
- `docs/planning/archive/2026/module-registered-agent-skills-and-mcp-facade.md`
- `docs/adr/ADR-0020-universal-right-drawer-ai-navigation.md`
- `docs/adr/ADR-0019-context-aware-sidebar-ai-chat.md`
- `docs/adr/ADR-0018-universal-source-adapters-memory-analytics.md`

## Read scope

- `apps/core/source_adapters.py`
- `apps/core/right_panels.py`
- `apps/core/tests.py`
- `apps/ai/skills_service.py`
- `apps/ai/views.py`
- `apps/ai/tool_definitions.py`
- `apps/ai/tooling.py`
- `apps/workorders/apps.py`
- `apps/waiting_list/apps.py`
- `services/agent_runtime/tools.py`
- `services/agent_runtime/prompting.py`
- `services/agent_runtime/graph.py`
- `services/agent_runtime/mcp_server.py`
- `services/agent_runtime/tests/test_normalization.py`
- `contracts/ai/`
- `data/contracts/ai/`
- `data/contracts/ai/skills/`
- `scripts/e2e/tests/sidebar_ai_context.spec.ts`

## Write scope

Ожидаемый write scope:

- `apps/core/ai_skills.py`
- `apps/core/tests.py`
- `apps/core/.desc.json`
- `apps/ai/skills_service.py`
- `apps/ai/tests.py`
- `apps/workorders/ai_skills.py`
- `apps/workorders/apps.py`
- `apps/workorders/tests.py`
- `apps/waiting_list/ai_skills.py`
- `apps/waiting_list/apps.py`
- `apps/waiting_list/tests.py`
- `services/agent_runtime/prompting.py`
- `services/agent_runtime/graph.py`
- `services/agent_runtime/mcp_server.py`
- `services/agent_runtime/tests/test_normalization.py`
- `data/contracts/ai/skills/`, только через runtime или тестовые фикстуры
- management commands для `ai_skill_list`, `ai_skill_validate`, `ai_skill_reload`, если создаются
- `scripts/e2e/tests/sidebar_ai_context.spec.ts`
- `docs/guides/AI_SIDEBAR_CHAT.md`
- guide по созданию runtime skills, если выделяется отдельно
- `services/agent_runtime/README.md`, если меняется MCP contract
- `.desc.json` и `PROJECT_STRUCTURE.yaml` при структурных изменениях

## Non-goals

- Не переводить внутренний sidebar chat на MCP.
- Не делать multi-agent архитектуру.
- Не реализовывать `ui.resolve_open_target` в MVP.
- Не открывать произвольный каталог пользовательских skills.
- Не разрешать scripts/assets в runtime contract skills в MVP.
- Не добавлять внешний MCP deployment/auth без отдельного решения.
- Не переносить permissions из модулей в `apps.core`.

## Ключевое решение

Module skills являются внутренним механизмом выбора workflow. MCP является внешним фасадом поверх тех же реестров. Tool execution остается через Django AI gateway.

## Acceptance

- Есть `apps.core.ai_skills` с provider registry.
- `workorders` и `waiting_list` регистрируют skills из `AppConfig.ready()`.
- `apps.ai.skills_service` возвращает module skills и файловые skills.
- `activate_skill` загружает body module skill.
- В `services/agent_runtime/graph.py` удалена hard-coded заявочная ветка.
- Агент через skills открывает заявку и запись листа ожидания справа.
- Администратор с `ai.manage_skills` может создать instruction-only runtime skill через `ai.skill_creator` и audited write-tool.
- Пользователь без `ai.manage_skills` не может создать или изменить runtime skill.
- Runtime contract skill подхватывается discovery без restart.
- MCP endpoint продолжает работать.
- MCP resources безопасно отдают descriptions для skills/tools/module capabilities.
- Все write tools по-прежнему требуют confirmation там, где требовали раньше.
- E2E покрывает основной sidebar-сценарий.

## Verification

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.core.tests apps.ai.tests apps.workorders.tests apps.waiting_list.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
npm run test:e2e -- --project=chromium --grep "sidebar"
make gen-struct
```
