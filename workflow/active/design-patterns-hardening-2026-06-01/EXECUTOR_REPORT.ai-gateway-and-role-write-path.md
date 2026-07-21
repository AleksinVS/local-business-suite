# Executor Report: AI gateway and role write-path

Дата: 2026-06-01.

## Scope

Срез закрывает часть task packets:

- `01-service-layer-and-write-paths`;
- `02-ai-command-flow-and-gateway-identity`;
- `06-docs-tests-and-acceptance`.

## Изменения

- `services/agent_runtime/app.py`: удалено логирование сырого prompt и полного actor context.
- `services/agent_runtime/app.py`: добавлен безопасный log context с `request_id`, `conversation_id`, `session_id`, `model_id`, длиной/hash prompt и ограниченной сводкой actor.
- `services/agent_runtime/app.py`: ошибки `/chat` и `/chat/stream` возвращают безопасный payload без текста исключения.
- `apps/ai/views.py`: Django chat surface больше не пишет значение runtime-исключения в warning-лог.
- `apps/ai/views.py`: gateway проверяет, что `actor.user_id` существует, активен и не противоречит переданному `username`.
- `apps/ai/views.py`: gateway управляемо отклоняет некорректный тип `actor.user_id`.
- `apps/ai/services.py`: `access.update_role_permissions` переведен на `apply_contract_payload`.
- `apps/ai/tooling.py`: audit payload получил `command` metadata: tool, action kind, actor, session, trace identifiers, confirmation state и payload keys.
- `apps/ai/tests.py`: добавлены проверки username mismatch и role update через Settings Center audit.
- `services/agent_runtime/tests/test_normalization.py`: добавлены проверки безопасного runtime log context и отсутствия текста исключения в runtime error log.
- `docs/guides/ARCHITECTURE_REVIEW_2026-06-01.md` и active plans обновлены по фактическому состоянию.

## Не Входило

- Миграции всех runtime-баз и deployment-документация.
- Перенос PATH_INFO debug log.
- Полная модель внешнего MCP-доступа.
- Outbox/job contract для фоновых задач.
- Полная унификация всех старых не-AI write paths.

## Проверки

Выполнены targeted checks:

```bash
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_admin_role_update_tool_uses_settings_center_audit
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_tool_gateway_rejects_username_mismatch apps.ai.tests.AIViewsTests.test_tool_gateway_accepts_non_uuid_session_id apps.ai.tests.AIViewsTests.test_admin_role_update_tool_uses_settings_center_audit
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_tool_gateway_rejects_invalid_actor_user_id apps.ai.tests.AIViewsTests.test_tool_gateway_rejects_username_mismatch apps.ai.tests.AIViewsTests.test_list_workorders_tool_returns_visible_items_and_logs_action apps.ai.tests.AIViewsTests.test_open_right_panel_tool_returns_ui_command_for_visible_workorder
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_chat_send_runtime_error_is_user_safe_and_audited apps.ai.tests.AIViewsTests.test_chat_stream_runtime_error_is_returned_saved_and_audited apps.ai.tests.AIViewsTests.test_tool_gateway_rejects_invalid_actor_user_id
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization.TestRuntimeSafeLogging -v
```

Результат: пройдено.

Независимый проверочный субагент дополнительно подтвердил targeted checks и нашел два замечания. Оба устранены:

- `logger.exception` заменен на безопасный `logger.error` без traceback-значения исключения;
- добавлена проверка некорректного `actor.user_id`.

Полный набор проверок фиксируется в `TASK_ACCEPTANCE.ai-gateway-and-role-write-path.md`.

## Остаточные Риски

- MCP нельзя публиковать наружу без отдельного ADR и дополнительной service identity model.
- Старые runtime contract write paths вне AI требуют отдельной проверки.
- Deployment/migration hardening еще не выполнен.
