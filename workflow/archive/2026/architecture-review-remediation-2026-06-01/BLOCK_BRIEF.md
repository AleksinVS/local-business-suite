# Исправления по архитектурному ревью 2026-06-01

## Цель

Закрыть архитектурные расхождения, найденные в `docs/guides/ARCHITECTURE_REVIEW_2026-06-01.md`, сохранив текущий local-first Django monorepo и принятые ADR.

## Бизнес-ценность

Снизить риск неработающего production-старта, неаудируемого изменения прав, утечки prompt в технические логи и небезопасного расширения AI/MCP-доступа.

## Write Scope

Предполагаемый write scope для реализации:

- `docker/entrypoint.prod.sh`;
- `scripts/windows/run_windows.ps1`;
- `docs/deployment/`;
- `README.md`;
- `apps/core/views.py`;
- `apps/ai/services.py`;
- `apps/ai/tooling.py`;
- `apps/ai/views.py`;
- `services/agent_runtime/app.py`;
- `services/agent_runtime/mcp_server.py`;
- `apps/core/middleware.py`;
- точечные тесты в `apps/*/tests.py`;
- `.desc.json` и `PROJECT_STRUCTURE.yaml`, если меняется структура.

## Non-goals

- Не внедрять новый runtime-сервис.
- Не менять бизнес-модель заявок, памяти или аналитики.
- Не публиковать MCP наружу.
- Не чистить корневой `BACKLOG.md`, так как он является личными заметками владельца.

## Acceptance

Работа считается принятой, когда:

- миграции всех runtime-баз применяются единым documented путем;
- изменение `role_rules` идет через один service layer с audit;
- agent runtime не пишет raw prompt и полный actor context в технические логи;
- AI gateway/MCP не позволяют выполнять tools без проверенной привязки пользователя и сессии;
- debug PATH_INFO log не пишет файл в корень проекта;
- устаревшие архитектурные ссылки обновлены;
- проверки из active plan выполнены или явно зафиксированы причины пропуска.
