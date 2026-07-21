# Task Acceptance: tauri

Дата: 2026-06-03.

## Результат

Этап 2 реализован как первичный optional Tauri-клиент и серверный device API. Требуется техническая проверка сборки на целевых ОС перед production rollout.

## Проверено по acceptance

- Пользователь может сформировать одноразовый код подключения в портале.
- Device API меняет код на device token.
- Устройство отображается в профиле уведомлений и может быть отозвано.
- Token API ограничен чтением и подтверждением уведомлений.
- Сервер хранит HMAC-хеш токена, а не исходный токен.
- Tauri-клиент содержит tray menu, polling, notification action, opener, autostart и Stronghold storage.
- Есть user guide и deployment guide.

## Проверки

Выполнены:

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

Нативные Rust/Tauri проверки и сборка installer не выполнены в текущем окружении: отсутствуют `cargo`, `rustc`, `rustup`, `webkit2gtk-4.1` и `rsvg2`.

## Остаточные действия перед production

- Установить Tauri build dependencies на Windows/Linux runner.
- Выполнить фактическую сборку на целевых ОС.
- Проверить tray и системные уведомления на рабочих местах.
- Подготовить signing и upgrade strategy.
