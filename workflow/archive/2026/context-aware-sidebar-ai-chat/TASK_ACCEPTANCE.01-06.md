# Task Acceptance: context-aware-sidebar-ai-chat

Дата: 2026-05-28.

Статус: accepted by executor, awaiting owner acceptance.

## Acceptance

- `Все функции` доступно в верхнем левом блоке, пункты меню сохранены.
- В левом сайдбаре загружается встроенный ИИ-чат.
- Sidebar-chat использует отдельную `ChatSession.channel=sidebar`.
- Full-page chat остается доступен и открывает sidebar-сессию по ссылке.
- `PageContextEnvelope` публикуется браузером и сохраняется как `AIWindowContextSnapshot`.
- Для заявки в drawer сервер резолвит объект через права текущего пользователя.
- Сообщение чата получает immutable `context_snapshot_id`.
- `ui.get_current_context` возвращает bound snapshot текущего запроса.
- Sidebar history compact использует `surfaces.sidebar.recent_message_limit`, по умолчанию `8`.
- Контракт `ai.chat_settings` валидируется через Settings Center/architecture contracts.
- E2E подтверждает сценарий `board -> sidebar chat -> open workorder -> context`.

## Residual Risk

- Для модулей кроме `workorders` пока есть только базовый route context; detailed selection надо добавлять при развитии конкретных сценариев.
- Реальный LLM routing зависит от runtime prompt following; в тестах проверены prompt/tool registration и gateway path, но не качество ответа конкретной модели.
- Mobile layout читабелен, но выпадающее меню занимает почти весь экран; при отдельной задаче UI polish можно сделать mobile drawer-режим.

## Acceptance Checks

Все обязательные проверки из executor report выполнены успешно.
