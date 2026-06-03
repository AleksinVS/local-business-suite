# Workflow Brief: desktop-notifications-pwa-tauri

Статус: planned, documentation prepared.

Дата: 2026-06-03.

## Цель

Подготовить и реализовать контур пользовательских уведомлений:

- этап 1: PWA и браузерные уведомления для всех пользователей без стороннего Web Push;
- этап 2: опциональное Tauri-приложение в трее для Windows/Linux.

## Архитектурные источники

- `docs/adr/ADR-0026-pwa-first-and-optional-tauri-notifications.md`
- `docs/architecture/PWA_AND_TAURI_NOTIFICATIONS_PLAN.md`
- `docs/planning/active/desktop-notifications-pwa-tauri.md`

## Read scope

- `apps/workorders/models.py`
- `apps/workorders/services.py`
- `apps/workorders/policies.py`
- `apps/workorders/selectors.py`
- `apps/workorders/tests.py`
- `templates/base.html`
- `static/src/js/`
- `static/src/css/app.css`
- `config/settings.py`
- `config/urls.py`
- `docs/adr/`
- `docs/architecture/`
- `docs/planning/active/`
- `docs/guides/TESTING_POLICY.md`
- `docs/deployment/DEPLOYMENT.md`
- `docs/deployment/IIS_SSO.md`

## Write scope этапа 1

- `apps/notifications/`
- `apps/workorders/notification_events.py`
- `apps/workorders/services.py`
- `apps/workorders/tests.py`
- `config/settings.py`
- `config/urls.py`
- `templates/base.html`
- `templates/notifications/`
- `static/src/js/notifications.js`
- `static/src/js/pwa.js`
- `static/src/css/app.css`
- `static/manifest.webmanifest`
- `static/service-worker.js` или Django route для service worker с корневым scope
- `scripts/e2e/tests/notifications.spec.ts`
- `docs/guides/NOTIFICATIONS_USER_GUIDE.md`
- `docs/deployment/DEPLOYMENT.md`, если меняются HTTPS/service worker требования
- `.desc.json`
- `PROJECT_STRUCTURE.yaml`
- `workflow/active/desktop-notifications-pwa-tauri/`

## Write scope этапа 2

Точный каталог Tauri-клиента должен быть утвержден перед реализацией второго этапа.

Предварительно:

- `clients/desktop-notifier/` или согласованный аналог;
- `apps/notifications/` device API;
- `docs/guides/DESKTOP_NOTIFIER_USER_GUIDE.md`;
- `docs/deployment/DESKTOP_NOTIFIER_DEPLOYMENT.md`;
- `.desc.json`;
- `PROJECT_STRUCTURE.yaml`.

## Non-goals

- Не использовать Push API, VAPID и сторонние browser push endpoints в первом этапе.
- Не обещать фоновые системные уведомления при закрытом браузере на первом этапе.
- Не добавлять WebSocket/Channels без отдельного решения.
- Не хранить бизнес-данные заявок в PWA или Tauri-клиенте.
- Не раскрывать чувствительные детали в системных уведомлениях.
- Не делать Tauri обязательным для всех пользователей.

## Acceptance этапа 1

- Центр уведомлений доступен из портала.
- Пользователь может включить browser notifications только явным действием.
- PWA manifest и service worker корректно подключены.
- Новые события заявок создают уведомления для разрешенных получателей.
- API не отдает чужие уведомления.
- Клик по уведомлению открывает портал.
- События не теряются при закрытом портале и видны после следующего входа.
- Отказ browser permission не ломает центр уведомлений.
- Unit/integration/e2e проверки покрывают основной пользовательский сценарий.

## Acceptance этапа 2

- Tauri-клиент подключается через одноразовый код.
- Устройство можно отозвать.
- Клиент показывает уведомления при закрытом браузере, если запущен.
- Клик открывает ссылку в системном браузере.
- Device token имеет минимальный scope.
- Логи клиента безопасны.

## Verification

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.notifications.tests apps.workorders.tests
npm run test:e2e -- --project=chromium --grep "notifications"
make gen-struct
git diff --check
```

Для Tauri после старта второго этапа:

```bash
python manage.py test apps.notifications.tests
npm run tauri test
npm run tauri build
```
