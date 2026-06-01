# Исправления по архитектурному ревью 2026-06-01

Статус: active plan.

Связанные материалы:

- ревью: `docs/guides/ARCHITECTURE_REVIEW_2026-06-01.md`;
- workflow-блок: `workflow/active/architecture-review-remediation-2026-06-01/`.

## Цель

Закрыть архитектурные расхождения, найденные в ревью от 2026-06-01, без смены основного стека и без расширения scope на новые продуктовые функции.

Главная ценность: привести запуск, изменение контрактов, AI gateway, логи и документацию к уже принятым правилам проекта.

## Scope

1. Production/runtime migrations:
   - единый путь применения миграций для `default`, `chat`, `knowledge_meta`, `analytics_control`;
   - обновление Docker, Windows/IIS и deployment-документации.

2. Runtime contract write-path:
   - перевести старые пути изменения `role_rules` на Settings Center service layer;
   - оставить audit и атомарную запись обязательными;
   - решить судьбу AI tool `access.update_role_permissions`: service-layer wrapper, proposal-only или удаление из write-tools.

3. AI gateway, MCP и prompt logging:
   - убрать сырой prompt и actor context из agent runtime logs;
   - закрепить безопасный порядок разбора ошибок по `request_id`;
   - усилить проверку session ownership и service identity;
   - определить условия, при которых MCP можно считать внешним фасадом.

4. Root/debug hygiene и документация:
   - перенести PATH_INFO debug log в `data/logs/` или `.local/logs/`;
   - обновить устаревшие ссылки в архитектурных документах;
   - сохранить решение владельца: корневой `BACKLOG.md` остается личными заметками, рабочий backlog агентов остается `docs/planning/backlog.md`.

## Non-goals

- Не менять модель хранения памяти.
- Не внедрять PostgreSQL, Celery, Redis или новый broker в этом срезе.
- Не публиковать MCP наружу.
- Не переписывать UI Settings Center.
- Не чистить личные заметки владельца в корневом `BACKLOG.md`.

## Acceptance Checks

Минимальные проверки после реализации:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test apps.core.tests apps.ai.tests apps.memory.tests apps.analytics.tests apps.settings_center.tests
git diff --check
```

Дополнительные e2e или smoke checks:

```bash
.venv/bin/python manage.py migrate --database=default --noinput --plan
.venv/bin/python manage.py migrate --database=chat --noinput --plan
.venv/bin/python manage.py migrate --database=knowledge_meta --noinput --plan
.venv/bin/python manage.py migrate --database=analytics_control --noinput --plan
.venv/bin/python manage.py memory_eval --dry-run
```

Если меняется браузерный или AI-путь, добавить targeted e2e через Django Client, Playwright или management-command сценарий.

## ADR

Новый ADR не нужен для исправления найденных расхождений, если работы остаются в рамках уже принятых решений:

- ADR-0007 для Settings Center и runtime contracts;
- ADR-0011 для раздельных баз и файловых знаний;
- ADR-0021 для AI skills и MCP-фасада;
- ADR-0024 для безопасного выноса сервисов.

ADR нужен, если в ходе реализации будет принято решение публиковать MCP как внешний production API или менять модель доверия AI gateway.

## Порядок Работ

1. Сначала исправить миграции всех баз и deployment-документацию.
2. Затем убрать raw prompt logging и добавить операторский порядок разбора ошибок.
3. После этого свести role contract writes к Settings Center.
4. Затем усилить AI gateway/MCP identity checks.
5. В конце обновить архитектурные ссылки, `.desc.json`, `PROJECT_STRUCTURE.yaml` и выполнить проверки.

## Остаточные Риски

- Если несколько процессов Django держат старые runtime settings в памяти, изменение contracts через UI может требовать явного restart/reload.
- Если MCP будет опубликован наружу до усиления identity model, риск имперсонации станет высоким.
- Если debug logging останется включенным на production, возможна запись диагностических данных вне регламентированных runtime-путей.
