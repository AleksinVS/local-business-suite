# Task Acceptance: implementation

Дата: 2026-05-29.

## Acceptance

- `apps.core.ai_skills` добавлен и покрыт тестами.
- `workorders` и `waiting_list` регистрируют AI skills из `AppConfig.ready()`.
- `apps.ai.skills_service` видит module skills и runtime contract skills.
- Runtime contract skill подхватывается discovery без restart.
- `ai.skill_creator` добавлен как trusted system skill.
- `ai.skills.create_or_update` пишет только instruction-only `SKILL.md`, требует `ai.manage_skills`, проходит confirmation и audit.
- Пользователь без права не может подтвердить запись runtime skill.
- В `services/agent_runtime/graph.py` удалена доменная ветка открытия заявок.
- Agent runtime prompt направляет модульные сценарии в skills.
- MCP endpoint сохраняется и получает read-only resources:
  - `local-business://skills/{skill_id}`;
  - `local-business://tools/{tool_code}`;
  - `local-business://modules/{source_code}/capabilities`.
- E2E-файл обновлен для открытия заявки и записи листа ожидания через sidebar stream `ui_command`.
- Документация обновлена:
  - `docs/guides/AI_SIDEBAR_CHAT.md`;
  - `docs/guides/AI_SKILLS_OPERATIONS.md`;
  - `services/agent_runtime/README.md`.

## Verification

- `python manage.py check` — OK.
- `python manage.py validate_architecture_contracts` — OK.
- `python manage.py ai_skill_validate --all` — OK.
- `python manage.py test apps.core.tests apps.ai.tests apps.workorders.tests apps.waiting_list.tests --keepdb` — OK, 172 tests.
- `python -m unittest services.agent_runtime.tests.test_normalization -v` — OK, 32 tests.
- `npm run test:e2e -- --project=chromium --grep "sidebar"` — OK, 4 tests.
- `make gen-struct` — OK.
- `git diff --check` — OK.

## Решение

Реализация принята на уровне code/integration/e2e checks. Workflow остается в `active` до приемки владельцем.
