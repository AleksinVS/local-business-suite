# Executor Report: implementation

Дата: 2026-06-03.

## Scope

Реализован этап 1 PWA/browser notifications без стороннего Web Push.

## Измененные области

- `apps.notifications` — серверный домен уведомлений, модели, API, админка, тесты.
- `apps.workorders.notification_events` — безопасные события заявок и выбор получателей через существующие политики видимости.
- `apps.workorders.services` и `apps.workorders.views` — явные вызовы производителей уведомлений.
- `templates/base.html` и `templates/notifications/` — центр уведомлений в шапке и страница уведомлений.
- `static/src/js/notifications.js` и `static/src/js/pwa.js` — polling, browser permission, отметки состояний, регистрация service worker.
- `static/manifest.webmanifest`, `static/service-worker.js`, `static/icons/` — PWA-ресурсы.
- `scripts/e2e/tests/notifications.spec.ts` — e2e-проверка manifest/service worker и авторизованного центра при наличии учетных данных.
- `docs/guides/NOTIFICATIONS_USER_GUIDE.md` и `docs/deployment/DEPLOYMENT.md` — пользовательские и deployment-ограничения.

## Реализованные решения

- Cursor API использует `NotificationRecipient.id`.
- API фильтрует все операции по `request.user`.
- Browser client хранит хеш отпечатка, а не сырой идентификатор.
- Permission prompt вызывается только из пользовательского обработчика кнопки.
- Service worker отдается по `/service-worker.js`, чтобы scope покрывал портал.
- Service worker не кэширует защищенные HTML/API, только ограниченный набор static assets.
- Push API, VAPID и сторонние browser push endpoints не добавлялись.

## Проверки

Выполнено:

```bash
.venv/bin/python manage.py makemigrations notifications
.venv/bin/python manage.py check
.venv/bin/python manage.py test apps.notifications.tests apps.workorders.tests
npm run test:e2e -- --project=chromium --grep "notifications"
```

Результат:

- Django system check identified no issues.
- `apps.notifications.tests apps.workorders.tests`: 68 tests, OK.
- Playwright `notifications`: 1 passed, 1 skipped. Авторизованный UI-сценарий пропущен без `E2E_USERNAME` и `E2E_PASSWORD`.

## Остаточные риски

- Для production browser notifications нужен HTTPS; HTTP-only профиль оставляет рабочим только центр уведомлений.
- На большом количестве пользователей расчет получателей через перебор активных пользователей может потребовать оптимизации.
- Tauri API и клиент не реализованы в этом срезе.
