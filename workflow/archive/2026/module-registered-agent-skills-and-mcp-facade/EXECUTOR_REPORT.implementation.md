# Executor Report: implementation

Дата: 2026-05-29.

## Сделано

- Добавлен `apps.core.ai_skills` с `AgentSkillDescriptor`, `AgentSkillProvider` и registry.
- `apps.ai.skills_service` теперь собирает каталог из module skills, `data/contracts/ai/skills` и `contracts/ai/skills`.
- Добавлены module skills:
  - `workorders.open_right_panel`;
  - `waiting_list.open_right_panel`;
  - `ai.skill_creator`.
- Удален временный hard-coded shortcut открытия заявок из `services/agent_runtime/graph.py`.
- Добавлен tool `waiting_list.get` для безопасного получения метаданных записи листа ожидания.
- Добавлен write-tool `ai.skills.create_or_update` с confirmation flow, проверкой `ai.manage_skills`, атомарной записью и audit redaction.
- Добавлены команды:
  - `ai_skill_list`;
  - `ai_skill_validate`;
  - `ai_skill_reload`.
- MCP-сервер получил read-only resources для skills, tools и module capabilities.
- Обновлены runtime prompt, tool wrappers, tool contracts и e2e-сценарии sidebar-чата.
- Обновлена операторская документация.

## Проверки

- `python manage.py check` — OK.
- `python manage.py validate_architecture_contracts` — OK.
- `python -m unittest services.agent_runtime.tests.test_normalization -v` — OK, 32 tests.
- `python manage.py ai_skill_validate --all` — OK.
- `python manage.py test apps.core.tests apps.ai.tests --keepdb` — OK, 102 tests.
- `python manage.py test apps.core.tests apps.ai.tests apps.workorders.tests apps.waiting_list.tests --keepdb` — OK, 172 tests.
- `npm run test:e2e -- --project=chromium --grep "sidebar"` — OK, 4 tests.
- `make gen-struct` — OK.
- `git diff --check` — OK.

## Остаточные риски

- Полное автоматическое создание skills через диалог зависит от качества выбора `ai.skill_creator` моделью; это покрывается подсказками и integration-тестами write-tool.
- MCP tools пока сохранены как typed wrappers; полная генерация MCP tools из registry отложена, чтобы не потерять сигнатуры.
- UI Settings Center для просмотра, отключения и истории runtime skills отложен.
