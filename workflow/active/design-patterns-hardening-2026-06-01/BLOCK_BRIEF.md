# Внедрение архитектурных паттернов 2026-06-01

## Цель

Перевести рекомендации из `docs/architecture/DESIGN_PATTERNS_REVIEW_2026-06-01.md` в исполнимый набор работ: единые сценарии записи, безопасные AI-команды, единые политики, переходники источников и надежные фоновые задачи.

## Контекст

Проект уже использует модульный Django-монолит, contracts, Settings Center, AI gateway, `SourceAdapter`/`SourceObjectEnvelope` и audit-модели. Основной риск — не отсутствие паттернов, а разные пути выполнения одного сценария в UI, AI, командах и будущих workers.

## Write Scope

Предполагаемый write scope для будущей реализации:

- `apps/workorders/services.py`;
- `apps/workorders/policies.py`;
- `apps/workorders/selectors.py`;
- `apps/inventory/services.py`;
- `apps/ai/tooling.py`;
- `apps/ai/services.py`;
- `apps/ai/views.py`;
- `apps/ai/runtime_client.py`;
- `services/agent_runtime/`;
- `apps/settings_center/contract_services.py`;
- `apps/core/source_adapters.py`;
- `apps/memory/`;
- `apps/analytics/`;
- `docs/architecture/`;
- `docs/guides/`;
- `docs/planning/`;
- `workflow/`.

Точный write scope уточняется в каждом task packet перед реализацией.

## Non-Goals

- Не переписывать проект на микросервисы.
- Не вводить общий repository поверх каждой Django-модели.
- Не менять основной стек Django/Python.
- Не публиковать MCP наружу без отдельного ADR.
- Не менять корневой `BACKLOG.md`, так как он является личными заметками владельца.

## Acceptance

Блок считается готовым к приемке, когда:

- для write-сценариев есть один доменный service path;
- AI write tools выполняются как команды с подтверждением, audit и trace identifiers;
- gateway/MCP не доверяют произвольному `user_id` из тела запроса;
- source adapters остаются единой границей для памяти и аналитики;
- для фоновых задач есть job/outbox contract, retry rules и idempotency keys;
- обновлены документы, тесты и проектная карта;
- выполнены согласованные unit/integration/e2e проверки.

## Обязательные Проверки

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test apps.workorders.tests apps.ai.tests apps.memory.tests apps.analytics.tests apps.settings_center.tests
git diff --check
```
