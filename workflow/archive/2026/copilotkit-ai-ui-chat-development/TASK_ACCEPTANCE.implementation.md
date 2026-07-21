# Task acceptance: implementation

## Результат

Первый runtime hardening срез принят на уровне локальных unit/integration/e2e-проверок.

## Закрытые критерии

- `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit` получает управляемый новый sidebar thread.
- Основной пользовательский вход `/ai/chat/` открывает CopilotKit-страницу, а не старый chat detail.
- Django остается владельцем `ChatSession`.
- Предыдущая активная sidebar-сессия архивируется при создании новой.
- Page context обновляется в CopilotKit properties после изменения страницы или правой панели.
- Отсутствующий LLM API key возвращает AG-UI `RUN_ERROR`, а не разрыв HTTP-stream до событий.
- UI-команды нормализуются и фильтруются на сервере.
- Tool trace не раскрывает nested token/secret/password/cookie/api_key значения.

## Остаточные условия приемки владельцем

- Проверить реальный prompt/response сценарий при настроенном LLM API key.
- Проверить reverse proxy `/copilotkit` и SSE timeout на целевом deployment.
