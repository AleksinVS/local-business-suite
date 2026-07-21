# Разработка самописного AG-UI ИИ-чата

## Статус

Implemented first slice. Реализовано в ветке `feature/copilotkit-ag-ui-integration` как срез основного самописного ИИ-чата поверх AG-UI.

## Цель

Перенести полезные решения из CopilotKit-пилота в самописный `native` UI, сохранив общий backend-контур:

- `apps.ai.ui_runtime`;
- `services.agent_runtime.protocols`;
- Django session/auth/history/audit;
- AG-UI event stream;
- безопасные UI-команды правой панели.

## Контекст

В ADR-0028 зафиксировано, что основной целевой ИИ-чат проекта - самописный AG-UI-compatible UI. CopilotKit остается равноправным драйвером и референсом.

Проверка версий 2026-06-15:

- в проекте `@ag-ui/client=0.0.55`;
- latest npm `@ag-ui/client=0.0.57`;
- в проекте `@copilotkit/runtime=1.59.5`;
- latest npm `@copilotkit/runtime=1.60.1`.

Обновление версии AG-UI не входит в scope и требует отдельного согласования.

## Write scope

- `templates/base.html`;
- `apps/ai/context_processors.py`;
- `apps/ai/ui_runtime/config.py`;
- `static/src/ai_ui/native_ai.js`;
- `static/src/ai_ui/native_ai.css`;
- `scripts/e2e/tests/native_ai_ui.spec.ts`;
- `apps/ai/tests.py`;
- `docs/architecture/`;
- `docs/planning/active/`;
- `docs/guides/`;
- `workflow/active/native-ag-ui-chat-development/`;
- `.desc.json`;
- `PROJECT_STRUCTURE.yaml`.

## Non-goals

- Не обновлять AG-UI/CopilotKit зависимости.
- Не менять wire contract несовместимо.
- Не добавлять browser-side write tools.
- Не удалять CopilotKit/legacy драйверы.
- Не менять доменные модели и contracts.

## План

### 1. Документация и workflow

Статус: выполнено.

Создать:

- архитектурный план;
- active planning-файл;
- workflow brief;
- task packets;
- executor/acceptance report после реализации.

### 2. Native mount и asset freshness

Статус: выполнено.

Исправить native branch в `templates/base.html`, добавить version query для native JS/CSS и не использовать CopilotKit config endpoint.

### 3. Thread/run lifecycle

Статус: выполнено.

Добавить кнопку нового чата, обновление config/thread, `runId`, блокировку формы и нормальное завершение run.

### 4. AG-UI reducer

Статус: выполнено.

Реализовать обработку lifecycle, text, tool, state, custom и error events.

### 5. UI-команды и page context

Статус: выполнено.

Выполнять только `open_right_panel`, дедуплицировать команды, слушать `ai-context:update`.

### 6. Тесты и приемка

Статус: выполнено для unit/e2e. Ожидает пользовательскую приемку.

Добавить/обновить unit и e2e проверки. Зафиксировать результаты в workflow.

### 7. UX parity со старым чатом

Статус: sidebar parity выполнен, full-page/rich input parity ожидают реализации.

Цель - довести `native` до возможностей старого Django/HTMX чата, не возвращая старую архитектуру и не делая CopilotKit обязательной зависимостью.

Работа разбита на task packets:

- `05-sidebar-history-model-and-clear-parity` - выполнено: история после reload, выбор модели, очистка с подтверждением, timestamps, ссылка на полный чат;
- `06-native-full-page-session-management` - полноценная native-страница чата, список сессий, переключение, переименование и удаление;
- `07-native-rich-input-markdown-commands-attachments` - Markdown, slash-команды, меню команд, autocomplete и вложения;
- `08-native-ux-parity-e2e-acceptance` - e2e matrix, rollback smoke и финальная приемка.

Parity baseline:

| Возможность старого чата | Native target |
| --- | --- |
| Последние сообщения sidebar после reload | Загружать из `/ai/ui/config/` безопасный список сообщений |
| Выбор модели в sidebar | Использовать общий список моделей и обновлять `ChatSession.metadata.model_id` |
| Очистка sidebar-чата | Same-origin endpoint с подтверждением в UI |
| Переход в полный чат | Кнопка/ссылка на native full-page chat текущей сессии |
| Список сессий полной страницы | Native full-page session list с правами текущего пользователя |
| Переименование/удаление чата | Переиспользовать существующие Django views/services или нейтральные endpoints |
| Markdown assistant messages | Безопасный rendering без XSS и без внешнего CDN в production |
| Slash-команды | Передавать predefined/custom commands в native config |
| Вложения | Переиспользовать `ChatAttachment`, текущие upload limits и Django auth |

## Acceptance checks

- `native` root берет config с `/ai/ui/config/`.
- Новый чат создает новый `thread_id`.
- Потоковый ответ собирается из `TEXT_MESSAGE_*`.
- Tool trace отображает `TOOL_CALL_*`.
- `STATE_DELTA /localBusiness/uiCommands` открывает правую панель один раз.
- `RUN_ERROR` показывает ошибку и разблокирует форму.
- Unknown AG-UI event игнорируется.
- UX parity task packets существуют и готовы к реализации.
- Документация и структура актуальны.

## Результат первого среза

Реализовано:

- native root/config/new-session URL в `templates/base.html`;
- versioned native assets и service worker bypass для `/static/src/ai_ui/`;
- AG-UI SSE parser и reducers в `static/src/ai_ui/native_ai.js`;
- compact tool trace и error states;
- сохранение native user/assistant/error messages в Django history;
- подмешивание Django `ChatSession` history в следующий AG-UI run;
- e2e для нового чата, tool trace, UI-команды, `RUN_ERROR`.

Осталось после приемки:

- реализовать `06-native-full-page-session-management`;
- реализовать `07-native-rich-input-markdown-commands-attachments`;
- выполнить `08-native-ux-parity-e2e-acceptance`;
- решить, обновлять ли `@ag-ui/client` с `0.0.55` на `0.0.57`;
- выполнить production smoke на целевом reverse proxy/SSE timeout;
- после приемки перенести план и workflow в архив.

## Проверки

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
node --check static/src/ai_ui/native_ai.js
E2E_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "native AG-UI-compatible"
E2E_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "native chat UX parity"
make gen-struct
git diff --check -- . ':(exclude)BACKLOG.md'
```
