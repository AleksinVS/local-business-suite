# Executor Report: tauri

Дата: 2026-06-03.

## Scope

Реализован второй этап как первичный optional Tauri-клиент уведомлений в трее.

## Измененные области

- `apps.notifications` — одноразовые коды подключения, device token exchange, bearer-auth device API, revoke.
- `templates/notifications/devices.html` — страница выпуска кода и отзыва устройств.
- `clients/desktop-notifier/` — Tauri 2 клиент.
- `docs/guides/DESKTOP_NOTIFIER_USER_GUIDE.md` — пользовательская инструкция.
- `docs/deployment/DESKTOP_NOTIFIER_DEPLOYMENT.md` — сборка и распространение.
- `package.json` — root-команды `desktop-notifier:*`.
- `AGENTS.md` и `.desc.json` — разрешен root-раздел `clients/`.

## Реализованные решения

- Одноразовый код действует 10 минут и используется один раз.
- Device token отдается клиенту только при обмене кода.
- Сервер хранит только HMAC-хеш device token.
- Device token имеет scope `notifications:read` и `notifications:ack`.
- Device API не использует Django session cookie.
- Tauri-клиент хранит токен в Stronghold vault.
- URL уведомления открывается как относительный путь внутри заданного portal origin.
- Действие системного уведомления открывает целевую ссылку и отправляет ack `read`.
- Tray menu содержит действия открыть, свернуть и выход.

## Выполненные проверки

```bash
npm --prefix clients/desktop-notifier run build
.venv/bin/python -m json.tool clients/desktop-notifier/package.json
.venv/bin/python -m json.tool clients/desktop-notifier/src-tauri/tauri.conf.json
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.notifications.tests
make gen-struct
git diff --check -- . ':!BACKLOG.md'
```

Нативные Rust/Tauri проверки не выполнены в текущем окружении: `cargo`, `rustc`, `rustup`, `webkit2gtk-4.1` и `rsvg2` отсутствуют по выводу `tauri info`.

## Остаточные риски

- Сборка Tauri требует Node.js, Rust и системных зависимостей Tauri на целевой ОС.
- Linux tray/notification behavior зависит от окружения рабочего стола.
- Windows rollout требует отдельной подписи installer перед широким распространением.
- Автообновление клиента не реализовано.
- Возможны дубли между PWA и Tauri при одновременной работе.
