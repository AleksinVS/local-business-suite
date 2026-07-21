# Executor Report: context-aware-sidebar-ai-chat

Дата: 2026-05-28.

Статус: implemented, awaiting owner acceptance.

## Реализовано

- Перенесена навигация в выпадающее меню `Все функции` в `templates/base.html`.
- Левая панель занята встроенным ИИ-чатом на отдельной `sidebar`-сессии.
- Добавлен общий контракт `contracts/ai/chat_settings.json`, loader `apps.ai.chat_settings` и descriptor Settings Center.
- Добавлена модель `AIWindowContextSnapshot`, endpoint обновления контекста окна и команда очистки expired snapshots.
- Добавлен browser bridge `static/src/js/page_context.js` и sidebar-клиент `static/src/js/sidebar_chat.js`.
- Добавлена привязка `context_snapshot_id` к `ChatMessage` при submit.
- Добавлен read-only tool `ui.get_current_context` в Django gateway и agent runtime.
- Обновлены prompts agent runtime: контекст-зависимые вопросы должны вызывать `ui.get_current_context`.
- Детальная резолюция выбранной сущности реализована для `workorders`.
- Для остальных страниц добавлен базовый route context `module/view`.
- Добавлена суммаризация sidebar-сессии с сохранением последних N сообщений из `ai.chat_settings`.
- Добавлен Playwright e2e `scripts/e2e/tests/sidebar_ai_context.spec.ts`.
- Добавлено руководство `docs/guides/AI_SIDEBAR_CHAT.md`.

## Ограничения MVP

- Детальные `selection`-resolvers для inventory, waiting list, memory review и analytics не реализованы в этом срезе.
- E2E не вызывает реальный LLM; он проверяет UI, snapshot и передачу контекста до runtime boundary.
- Race-safety проверяется серверной привязкой snapshot в unit-тестах.
- Универсальная event platform не вводилась по ADR-0019.

## Проверки

```bash
./.venv/bin/python manage.py makemigrations --check --dry-run
./.venv/bin/python manage.py check
./.venv/bin/python manage.py validate_architecture_contracts
./.venv/bin/python manage.py test apps.ai.tests --keepdb
./.venv/bin/python manage.py test apps.workorders.tests --keepdb
./.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization
E2E_BASE_URL=http://127.0.0.1:8001 E2E_USERNAME=e2e-sidebar-user E2E_PASSWORD=e2e-sidebar-pass npm run test:e2e -- --project=chromium
```

Результат: все перечисленные проверки прошли после исправления тестовой настройки staticfiles.

## Артефакты

- Desktop screenshot: `.local/playwright/manual/sidebar-ai-desktop.png`
- Mobile screenshot: `.local/playwright/manual/sidebar-ai-mobile.png`
- Playwright report: `.local/playwright/report/`
