# Executor report: native chat UX parity planning

## Scope

Подготовлена исполнительная документация для доведения `LOCAL_BUSINESS_AI_UI_DRIVER=native` до функционального уровня старого Django/HTMX ИИ-чата.

## Updated artifacts

- `workflow/active/native-ag-ui-chat-development/BLOCK_BRIEF.md`;
- `workflow/active/native-ag-ui-chat-development/ARCHITECT_PLAN.json`;
- `workflow/active/native-ag-ui-chat-development/task-packets/05-sidebar-history-model-and-clear-parity.json`;
- `workflow/active/native-ag-ui-chat-development/task-packets/06-native-full-page-session-management.json`;
- `workflow/active/native-ag-ui-chat-development/task-packets/07-native-rich-input-markdown-commands-attachments.json`;
- `workflow/active/native-ag-ui-chat-development/task-packets/08-native-ux-parity-e2e-acceptance.json`;
- `docs/architecture/NATIVE_AG_UI_CHAT_DEVELOPMENT_PLAN.md`;
- `docs/planning/active/native-ag-ui-chat-development.md`;
- `docs/planning/backlog.md`.

## AG-UI version check

Проверка 2026-06-15:

- pinned `@ag-ui/client=0.0.55`;
- latest npm `@ag-ui/client=0.0.57`;
- pinned `@copilotkit/runtime=1.59.5`;
- latest npm `@copilotkit/runtime=1.60.1`.

Обновление версий не выполнялось: по правилам проекта это только предупреждение до отдельного согласования.

## Result

Документация разбивает parity на четыре исполнимых этапа: sidebar parity, full-page session management, rich input/Markdown/commands/attachments и e2e acceptance matrix.
