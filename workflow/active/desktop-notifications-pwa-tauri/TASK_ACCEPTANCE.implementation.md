# Task Acceptance: implementation

Дата: 2026-06-03.

## Результат

Этап 1 PWA/browser notifications технически готов к приемке владельцем.

## Проверено по acceptance

- Центр уведомлений доступен из портала.
- Browser notification permission вызывается только после явного действия пользователя.
- PWA manifest и service worker подключены.
- Новые события заявок создают уведомления для разрешенных получателей.
- API не отдает и не изменяет чужие уведомления.
- Ссылка уведомления ведет в портал, где права проверяются штатно.
- При закрытом портале события сохраняются в серверной очереди.
- Отказ browser permission не ломает центр уведомлений.
- Документация объясняет ограничение первого этапа без Web Push.

## Проверки

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py test apps.notifications.tests apps.workorders.tests
npm run test:e2e -- --project=chromium --grep "notifications"
```

Результат:

- `manage.py check` — OK.
- `68 tests` — OK.
- Playwright — `1 passed`, `1 skipped` из-за отсутствия стендовых учетных данных.

## Остаточные действия перед production

- Выполнить миграции на целевой базе.
- Проверить HTTPS-профиль для PWA/browser notifications.
- Выполнить авторизованный Playwright UI-сценарий на стенде с `E2E_USERNAME` и `E2E_PASSWORD`.
- Принять отдельное решение о старте этапа 2 Tauri.
