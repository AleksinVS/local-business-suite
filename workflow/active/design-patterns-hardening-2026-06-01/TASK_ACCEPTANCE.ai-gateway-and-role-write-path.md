# Task Acceptance: AI gateway and role write-path

Дата: 2026-06-01.

## Итог

Статус: accepted for this slice.

Первый срез внедрения паттернов принят как частичное закрытие задач по безопасным AI-командам, единому write-path для ролевого контракта и безопасному runtime logging.

## Acceptance Checks

Принято:

- runtime не пишет сырой prompt и полный actor context в технические логи;
- runtime error payload не содержит текст исключения;
- role update через AI идет через Settings Center service layer;
- успешное применение role update создает `SettingsChange`;
- gateway отклоняет actor с несовпадающим `username`;
- gateway отклоняет нечисловой `actor.user_id` без 500;
- audit AI-команды содержит command metadata и confirmation state;
- runtime и Django warning logs не содержат текст исключения;
- пользовательский prompt остается доступен для разбора через `ChatMessage.content`, а технический поиск ошибки идет через `request_id`.

## Выполненные Команды

```bash
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_admin_role_update_tool_uses_settings_center_audit
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_tool_gateway_rejects_username_mismatch apps.ai.tests.AIViewsTests.test_tool_gateway_accepts_non_uuid_session_id apps.ai.tests.AIViewsTests.test_admin_role_update_tool_uses_settings_center_audit
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_tool_gateway_rejects_invalid_actor_user_id apps.ai.tests.AIViewsTests.test_tool_gateway_rejects_username_mismatch apps.ai.tests.AIViewsTests.test_list_workorders_tool_returns_visible_items_and_logs_action apps.ai.tests.AIViewsTests.test_open_right_panel_tool_returns_ui_command_for_visible_workorder
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_chat_send_runtime_error_is_user_safe_and_audited apps.ai.tests.AIViewsTests.test_chat_stream_runtime_error_is_returned_saved_and_audited apps.ai.tests.AIViewsTests.test_tool_gateway_rejects_invalid_actor_user_id
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization.TestRuntimeSafeLogging -v
```

Результат: пройдено.

Независимая read-only проверка субагентом подтвердила targeted checks. Найденные замечания по `logger.exception` и нечисловому `actor.user_id` исправлены и закрыты отдельными тестами.

## Финальные Проверки

```bash
make gen-struct
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test apps.ai.tests apps.settings_center.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
git diff --check
```

Результат: пройдено.

Подробно:

- `make gen-struct`: `PROJECT_STRUCTURE.yaml` обновлен;
- `manage.py check`: без замечаний;
- `validate_architecture_contracts`: контракты валидны;
- `makemigrations --check --dry-run`: изменений миграций нет;
- `services.agent_runtime.tests.test_normalization`: 35 тестов пройдены;
- `apps.ai.tests apps.settings_center.tests`: 88 тестов пройдены;
- `git diff --check`: без замечаний.

## Остаточный Scope

- Production/runtime migrations.
- Deployment-документация.
- PATH_INFO debug log hygiene.
- Старые не-AI role/workflow write paths.
- Внешний MCP access model и ADR при необходимости.
- Outbox/job contract и idempotency для фоновых задач.
