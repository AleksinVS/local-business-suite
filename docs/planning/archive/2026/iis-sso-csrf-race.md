# Устранение гонки Windows SSO/CSRF на автоматических запросах браузера

## Цель

Первое сохранение формы роли после Windows SSO не должно получать 403 из-за
параллельного запроса `/favicon.ico` с отдельной ротацией session/CSRF cookie.

## Реализованный scope

- исключение favicon из FastCGI в каноническом примере IIS;
- резервный SSO bypass для автоматических публичных ресурсов;
- явные favicon/apple-touch ссылки на существующие PWA icons;
- общая проверка `web.config` в Windows setup/import scripts;
- HTTP-регрессия реального GET формы и POST с включённой CSRF-проверкой;
- аудит `/static/`, manifest, service worker и стандартных browser icons.

## Non-goals

- изменение штатной ротации CSRF Django;
- commit host-specific `web.config` или секретов в основной репозиторий;
- обновление wfastcgi, IIS или схемы аутентификации.

## Приёмка

- автоматические публичные запросы с `REMOTE_USER` не создают пользователя,
  SSO-сессию или конкурирующую CSRF-cookie;
- форма ролей после первого Remote User GET проходит реальную CSRF-проверку POST;
- Windows-скрипты распознают обязательный favicon bypass;
- документация содержит исправление хоста и отдельное требование `DEBUG=0`.
