# Executor Report: implementation

Дата: 2026-05-28.

## Выполнено

- Добавлен `apps.core.right_panels` с `RightPanelDescriptor`, `RightPanelProvider` и registry.
- Добавлен общий правый сайдбар в `templates/base.html`.
- Добавлен browser bridge `static/src/js/right_panel.js`.
- Подключены providers:
  - `apps.workorders.right_panel.WorkOrderRightPanelProvider`;
  - `apps.waiting_list.right_panel.WaitingListRightPanelProvider`.
- Добавлен AI tool `ui.open_right_panel` в Python registry, JSON contract и agent runtime.
- Потоковый full-page и sidebar чат исполняют `ui_command`.
- `PageContextEnvelope` теперь умеет разрешать `waiting_list/waiting_list_entry`.
- Добавлены unit/integration tests и e2e-сценарии.
- Обновлены ADR, active plan, guide и `.desc.json`.

## Non-goals сохранены

- Универсальная платформа событий не вводилась.
- Универсальный CRUD не вводился.
- `SourceAdapter` не расширялся UI-обязанностями.
- `ui.open_right_panel` поддерживает только `mode=view`.
- Запись бизнес-данных осталась в отдельных доменных tools/views.

## Проверки

Выполнено:

```bash
python manage.py check
node --check static/src/js/right_panel.js
node --check static/src/js/ai_chat.js
node --check static/src/js/sidebar_chat.js
python -m unittest services.agent_runtime.tests.test_normalization
python manage.py test apps.core.tests apps.workorders.tests apps.waiting_list.tests apps.ai.tests
```

E2E и `make gen-struct` выполняются отдельным завершающим шагом после обновления документации.
