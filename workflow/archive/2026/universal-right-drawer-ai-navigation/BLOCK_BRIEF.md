# Workflow Brief: universal-right-drawer-ai-navigation

Статус: implemented MVP, ready for owner verification.

Дата: 2026-05-28.

## Цель

Реализовать универсальное открытие правого сайдбара для объектов модулей, чтобы ИИ-бот мог открыть заявку, запись листа ожидания или будущий модульный объект без знания внутреннего UI-кода модуля.

## Архитектурные источники

- `docs/adr/ADR-0020-universal-right-drawer-ai-navigation.md`
- `docs/planning/active/universal-right-drawer-ai-navigation.md`
- `docs/adr/ADR-0018-universal-source-adapters-memory-analytics.md`
- `docs/adr/ADR-0019-context-aware-sidebar-ai-chat.md`

## Read scope

- `templates/base.html`
- `templates/ai/chat_detail.html`
- `templates/workorders/`
- `templates/waiting_list/`
- `static/src/js/ai_chat.js`
- `static/src/js/page_context.js`
- `static/src/css/app.css`
- `apps/ai/`
- `apps/core/`
- `apps/workorders/`
- `apps/waiting_list/`
- `contracts/ai/tools.json`
- `services/agent_runtime/`

## Write scope

Ожидаемый write scope при реализации:

- `apps/core/right_panels.py`
- `apps/workorders/right_panel.py`
- `apps/waiting_list/right_panel.py`
- `apps/workorders/apps.py`
- `apps/waiting_list/apps.py`
- `templates/base.html`
- `static/src/js/right_panel.js`
- `static/src/js/ai_chat.js`
- `static/src/js/sidebar_chat.js`, если sidebar stream тоже должен исполнять UI-команды
- `static/src/css/app.css`
- `apps/ai/tooling.py`
- `apps/ai/tool_definitions.py`
- `contracts/ai/tools.json`
- `services/agent_runtime/tools.py`
- `services/agent_runtime/prompting.py`
- tests и e2e
- docs/guides после реализации

## Non-goals

- Не вводить универсальную платформу событий.
- Не делать универсальный CRUD.
- Не выполнять write-действия через `ui.open_right_panel`.
- Не принимать произвольные URL от ИИ.
- Не расширять `SourceAdapter` HTML/UI-обязанностями.
- Не переносить доменные permissions из модулей в `apps.core`.

## Ключевое решение

MVP использует `RightPanelProvider` registry и общий drawer-host. Каждый модуль регистрирует provider для своих объектов. AI tool `ui.open_right_panel` возвращает браузеру безопасную UI-команду, а не HTML и не произвольный URL.

## Acceptance

- Есть общий right drawer host на всех страницах.
- `workorders` и `waiting_list` открываются через provider registry.
- Страница `AI чат` может открыть объект справа.
- Обычные клики в канбане и листе ожидания не сломаны.
- Неизвестный provider, неизвестный mode и чужой объект fail-closed.
- Открытие панели обновляет `PageContextEnvelope`.
- `ui.get_current_context` после открытия видит выбранный объект.
- Tool `ui.open_right_panel` не требует confirmation, но пишет безопасный audit trace.
- Tool registry валиден.

## Verification

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.core.tests apps.ai.tests apps.workorders.tests apps.waiting_list.tests
python -m unittest services.agent_runtime.tests.test_normalization
npm run test:e2e -- --project=chromium
make gen-struct
```
