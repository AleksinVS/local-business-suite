# Task Acceptance: implementation

Дата: 2026-06-09.

## Итог

Первый срез реализации принят для ветки: код, настройки, документы и workflow-след согласованы между собой.

## Acceptance

- `/ag-ui` добавлен и покрыт unit-тестами на порядок событий, tool trace, `ui_command` и ошибку подписи.
- Текущие `/chat` и `/chat/stream` не менялись.
- CopilotKit Runtime запускается отдельным Node-процессом и имеет health endpoint.
- React-остров включается только через `LOCAL_BUSINESS_COPILOTKIT_ENABLED`.
- Browser не получает gateway token; actor/session payload подписывается Django и проверяется agent runtime.
- `ui.open_right_panel` остается UI-командой и открывает существующий безопасный правый сайдбар.
- Deployment/operations/docs/backlog/structure обновлены.

## Условия перед pilot-включением

- Выполнить авторизованный e2e на стенде.
- Проверить reverse proxy `/copilotkit` на целевом deployment.
- Подтвердить, что `COPILOTKIT_TELEMETRY_DISABLED=true` задан в deployment-среде.
