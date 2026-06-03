# PWA и Tauri уведомления

## Статус

Архитектура принята. Этап 1 реализован как MVP и ожидает приемку владельцем. Этап 2 Tauri не начат.

Архитектурное решение: `docs/adr/ADR-0026-pwa-first-and-optional-tauri-notifications.md`.

Активный план: `docs/planning/active/desktop-notifications-pwa-tauri.md`.

Workflow-блок: `workflow/active/desktop-notifications-pwa-tauri/`.

## Методологическая заметка

Уведомление - это не просто всплывающее окно. Надежный контур состоит из серверной очереди, правил выбора получателей, состояния прочтения и клиентского канала доставки. Клиент показывает только то, что сервер уже разрешил конкретному пользователю.

## Цель

Добавить пользователям портала уведомления об изменениях в системе:

- новая заявка;
- изменение заявки;
- назначение исполнителя;
- новый комментарий;
- выполнение или закрытие заявки;
- будущие системные события других доменов.

Первый этап должен работать для всех пользователей через портал/PWA без стороннего Web Push. Второй этап добавляет опциональное приложение в трее для пользователей, которым нужен постоянный фоновый канал.

## Принятое направление

```text
Этап 1:
  Django notifications domain
  + центр уведомлений в портале
  + PWA manifest/service worker
  + браузерные уведомления при открытом портале
  + HTTP polling, позже SSE при готовности deployment
  - без Push API, VAPID и внешних browser push endpoints

Этап 2:
  Tauri tray client
  + device token
  + internal notification API
  + системные уведомления Windows/Linux
  + открыть ссылку в браузере
```

## Реализованный срез этапа 1

Реализовано:

- приложение `apps.notifications`;
- модели `NotificationEvent`, `NotificationRecipient`, `NotificationPreference`, `NotificationBrowserClient`, `NotificationDeviceToken`;
- API `feed`, `mark-seen`, `mark-read`, `dismiss`, `browser-client`, `preferences`;
- центр уведомлений в общей шапке портала;
- `manifest.webmanifest`;
- service worker с корневым URL `/service-worker.js`;
- клиентский polling с cursor на основе `NotificationRecipient.id`;
- browser permission prompt только по явному нажатию пользователя;
- безопасные события заявок в `apps.workorders.notification_events`;
- unit/integration тесты и базовый Playwright e2e для manifest/service worker.

Не реализовано в этапе 1:

- Push API, VAPID и сторонние browser push endpoints;
- SSE/WebSocket;
- гарантированные системные уведомления при закрытом браузере;
- Tauri API обмена одноразового кода на device token;
- UI управления device tokens;
- quiet hours UI.

## Пользовательские сценарии

### Этап 1. Включение PWA-уведомлений

1. Пользователь входит в портал обычным способом.
2. В верхней панели или профиле открывает "Уведомления".
3. Видит объяснение: уведомления будут приходить, пока портал открыт в браузере или PWA-окне.
4. Нажимает "Включить уведомления на этом устройстве".
5. Браузер показывает системный запрос разрешения.
6. Если разрешение дано, портал сохраняет настройку пользователя.
7. Пользователь может установить портал как приложение, если браузер поддерживает PWA install.
8. При событиях сервер добавляет уведомление в очередь, открытая страница получает его и показывает системное уведомление.

Если пользователь отказал в разрешении, центр уведомлений в портале все равно работает. Повторное включение требует инструкции по настройкам браузера.

### Этап 1. Получение уведомления

1. Инженеру назначили заявку.
2. `apps.workorders` создает доменный notification payload.
3. `apps.notifications` сохраняет событие и строку получателя.
4. Открытая страница портала запрашивает новые уведомления по cursor.
5. Портал показывает системное уведомление:

```text
Заявка №123 назначена вам
Открыть в портале
```

6. Пользователь нажимает уведомление.
7. Открывается URL заявки в портале.
8. Сервер снова проверяет доступ к заявке.

### Этап 1. Портал был закрыт

1. Пока портал закрыт, системные уведомления не показываются.
2. Все события сохраняются на сервере.
3. При следующем открытии портала пользователь видит счетчик и список пропущенных уведомлений.

Это ожидаемое ограничение первого этапа, потому что сторонний Web Push не используется.

### Этап 2. Подключение Tauri-клиента

1. Пользователь устанавливает приложение уведомлений.
2. В портале открывает "Подключить приложение уведомлений".
3. Получает одноразовый код или deep link подключения.
4. Tauri-клиент меняет код на device token.
5. Клиент сохраняет токен в защищенном хранилище ОС.
6. Иконка появляется в трее.
7. Клиент получает уведомления от портала даже при закрытом браузере, пока сам клиент запущен.

## Техническая архитектура

### Серверная модель

Рекомендуемые сущности:

```text
NotificationEvent
  event_id
  event_type
  source_app
  source_object_type
  source_object_id
  title
  body
  target_url
  severity
  created_at
  metadata

NotificationRecipient
  event
  user
  state: new | seen | read | dismissed
  cursor
  delivered_at
  seen_at
  read_at

NotificationPreference
  user
  channel
  event_type
  enabled
  min_severity
  quiet_hours

NotificationBrowserClient
  user
  browser_fingerprint_hash
  user_agent_family
  notification_permission
  enabled
  last_seen_at

NotificationDeviceToken
  user
  device_name
  platform
  token_hash
  scopes
  last_seen_at
  revoked_at
```

`NotificationBrowserClient` не хранит Push API endpoint в первом этапе. Он нужен только для настроек, диагностики и объяснения пользователю состояния браузерных уведомлений.

В реализации этапа 1 `cursor` не является отдельным полем модели. API использует `NotificationRecipient.id` как монотонный курсор.

### API этапа 1

```text
GET  /notifications/api/feed/?cursor=<cursor>
POST /notifications/api/mark-seen/
POST /notifications/api/mark-read/
POST /notifications/api/dismiss/
POST /notifications/api/browser-client/
GET  /notifications/api/preferences/
POST /notifications/api/preferences/
```

Правила:

- все API работают только с текущей сессией пользователя;
- `GET feed` возвращает только его уведомления;
- `cursor` должен быть монотонным и устойчивым к повторному запросу;
- mark-read должен быть идемпотентным;
- прямой URL объекта из уведомления не заменяет проверку доступа.

### API этапа 2

```text
POST /notifications/api/devices/exchange-code/
GET  /notifications/api/devices/feed/?cursor=<cursor>
POST /notifications/api/devices/ack/
POST /notifications/api/devices/revoke/
```

Эти endpoint пока не реализованы. В этапе 1 добавлена только модель `NotificationDeviceToken` как подготовка к Tauri.

Токен устройства:

- не является Django session cookie;
- имеет ограниченные права;
- хранится только в виде hash на сервере;
- может быть отозван пользователем или администратором;
- не должен использоваться для общего API портала.

## Производители событий

Для заявок события создаются в `apps.workorders`, потому что только домен заявок знает бизнес-смысл изменения.

Точки интеграции:

- `create_workorder()`;
- `transition_workorder()`;
- `confirm_closure()`;
- создание комментария;
- изменение исполнителя;
- будущие изменения приоритета и срока.

Рекомендуемый локальный модуль:

```text
apps/workorders/notification_events.py
```

Он должен:

- строить безопасный payload;
- определять тип события;
- выбирать потенциальных получателей по ролям и видимости;
- передавать результат в сервис `apps.notifications`;
- не показывать автору лишнее уведомление о собственном действии, если это не настроено явно.

## Матрица доставки

| Состояние пользователя | Этап 1 PWA без Web Push | Этап 2 Tauri |
| --- | --- | --- |
| Портал открыт во вкладке | Системное уведомление и центр уведомлений | Можно не дублировать или сгруппировать |
| PWA-окно открыто | Системное уведомление и центр уведомлений | Можно не дублировать или сгруппировать |
| Браузер открыт, портал закрыт | Только серверная очередь до следующего открытия | Системное уведомление |
| Браузер полностью закрыт | Только серверная очередь до следующего открытия | Системное уведомление, если Tauri запущен |
| Нет разрешения браузера | Только центр уведомлений | Системное уведомление через Tauri |
| Нет сети | Серверная очередь после восстановления | Клиент повторяет запрос после восстановления |

## UX и тексты

### Центр уведомлений

Разместить в верхней панели:

- иконка уведомлений;
- счетчик новых;
- список последних событий;
- действия "Открыть", "Отметить прочитанным", "Все уведомления";
- пустое состояние;
- состояние "Браузерные уведомления выключены".

### Запрос разрешения

Не запрашивать разрешение на загрузке страницы.

Правильный порядок:

1. показать собственное объяснение;
2. дать кнопку "Включить";
3. только после клика вызвать browser permission prompt.

Текст должен прямо объяснять ограничение:

```text
Браузерные уведомления будут приходить, пока портал открыт во вкладке или установленном PWA-окне. Если нужен постоянный фоновой режим, используйте отдельное приложение уведомлений после его внедрения.
```

### Системные уведомления

Требования:

- короткий заголовок;
- безопасный текст;
- один URL действия;
- группировка частых изменений одной заявки;
- приоритеты без агрессивного звука по умолчанию;
- fallback в центр уведомлений.

## Безопасность и приватность

- Сервер вычисляет получателей, клиент ничего не фильтрует сам.
- Системный текст не содержит чувствительных деталей.
- Metadata уведомления не должна включать секреты, пути файлов, raw payload внешних систем.
- Все write-действия API требуют CSRF или device-token защиту в зависимости от канала.
- Device token для Tauri имеет отдельный scope.
- Browser permission state не считается security boundary.
- Отказ браузера не должен ломать веб-интерфейс.

## Deployment

Этап 1:

- нужен HTTPS для service worker и Notifications API в production;
- `localhost` допускается только для разработки;
- PWA manifest и service worker должны обслуживаться с корректным content type;
- на IIS и Linux проверить cache headers для service worker;
- корпоративные политики браузера могут запретить уведомления;
- для Linux поведение зависит от desktop notification service.

Этап 2:

- нужны отдельные сборочные инструкции Windows/Linux;
- Windows: MSI или NSIS, кодовая подпись при production rollout;
- Linux: AppImage/deb/rpm по выбранному окружению;
- обновление клиента не должно требовать прав администратора без необходимости;
- локальные логи клиента не должны содержать токены и тексты заявок.

## Проверки

Этап 1:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.notifications.tests apps.workorders.tests
npm run test:e2e -- --project=chromium --grep "notifications"
```

Минимальный e2e-сценарий:

1. пользователь включает уведомления в портале;
2. создается заявка для него;
3. центр уведомлений показывает событие;
4. browser notification API вызывается только после разрешения;
5. клик по уведомлению открывает заявку;
6. другой пользователь не видит чужое уведомление;
7. отказ в permission сохраняет рабочий центр уведомлений.

Этап 2:

```bash
python manage.py test apps.notifications.tests
npm run tauri test
npm run tauri build
```

E2E для Tauri должен проверять:

- подключение устройства;
- получение уведомления;
- click-to-open URL;
- отзыв токена;
- повторный запуск клиента;
- отсутствие секретов в логах.

## Источники и ограничения браузеров

- MDN Notifications API: `https://developer.mozilla.org/docs/Web/API/Notifications_API/Using_the_Notifications_API`
- MDN Service Worker API: `https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API`
- MDN Push API / PushManager: `https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe`
- MDN Web App Manifest: `https://developer.mozilla.org/en-US/docs/Web/Manifest`
- web.dev permissions best practices: `https://web.dev/articles/permissions-best-practices`
- Tauri system tray: `https://v2.tauri.app/learn/system-tray/`
- Tauri notification plugin: `https://v2.tauri.app/plugin/notification/`
- Tauri autostart plugin: `https://v2.tauri.app/plugin/autostart/`

Ключевое ограничение первого этапа: без Push API и стороннего Web Push нет надежного фонового системного уведомления при закрытом браузере. Это компенсируется серверной очередью и будущим Tauri-клиентом.
