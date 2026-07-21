# Развертывание Tauri-клиента уведомлений

## Назначение

Документ описывает сборку и распространение опционального Tauri-клиента `clients/desktop-notifier/` для Windows и Linux.

Клиент использует:

- Tauri 2;
- system tray;
- notification plugin;
- autostart plugin;
- opener plugin;
- Stronghold для хранения device token;
- device API портала `/notifications/api/devices/*`.

## Предварительные требования

На машине сборки нужны:

- Node.js и npm;
- Rust toolchain;
- системные зависимости Tauri для целевой ОС;
- доступ к исходному репозиторию.

Для Linux обычно нужны WebKitGTK/GTK/AppIndicator-зависимости, состав пакетов зависит от дистрибутива. Для Windows нужен стандартный Windows Rust/MSVC toolchain.

## Команды разработки

Из корня проекта:

```bash
npm run desktop-notifier:dev
npm run desktop-notifier:rust:fmt
npm run desktop-notifier:rust:check
npm run desktop-notifier:rust:test
```

Из каталога клиента:

```bash
cd clients/desktop-notifier
npm install
npm run tauri:dev
```

## Сборка

```bash
cd clients/desktop-notifier
npm install
npm run tauri:build
```

Или из корня:

```bash
npm run desktop-notifier:build
```

Ожидаемые артефакты зависят от ОС и Tauri bundler target:

- Windows: NSIS installer;
- Linux: AppImage/deb.

## Серверные требования

Перед пилотом:

```bash
python manage.py migrate
python manage.py check
python manage.py test apps.notifications.tests
```

Портал должен быть доступен по HTTPS или другому утвержденному защищенному каналу. HTTP-only профиль повышает риск перехвата device token и не рекомендуется для Tauri-клиента.

## Подключение пользователя

1. Пользователь входит в портал.
2. Открывает `Уведомления` -> `Устройства`.
3. Формирует одноразовый код.
4. Вводит код и URL портала в Tauri-клиенте.
5. Клиент меняет код на device token.

Сервер хранит только HMAC-хеш токена. Device token имеет ограниченные scope: чтение своей очереди уведомлений и подтверждение состояний.

## Безопасность

- Device token не является Django session cookie.
- Token API не дает доступа к общему API портала.
- Токен можно отозвать пользователем в портале.
- URL из уведомления должен быть относительным путем портала.
- Логи клиента не должны содержать токены и тексты заявок.

## Остаточные production-задачи

- Проверить Linux tray/notification поведение на выбранных рабочих окружениях.
- Подготовить Windows-подпись для installer перед широким rollout.
- Определить стратегию обновления клиента.
- Добавить подавление дублей между PWA и Tauri, если это потребуется на пилоте.
