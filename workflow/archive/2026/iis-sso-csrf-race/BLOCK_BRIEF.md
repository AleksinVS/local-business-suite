# Block Brief: устранение гонки Windows SSO/CSRF на IIS

## Цель

Исключить конкурирующий SSO-вход автоматического favicon-запроса и проверить
другие публичные ресурсы, способные создать session/CSRF side effect.

## Write scope

- IIS/Remote User middleware и тесты;
- базовый шаблон ссылок на browser icons;
- Windows deployment scripts и IIS runbook;
- ADR, planning/workflow и карта структуры.

## Риски

- ослабление CSRF или Remote User вместо устранения побочного входа;
- поломка корневого PWA service worker;
- ложная уверенность без обновления приватного host-specific `web.config`;
- неполная проверка из-за отсутствия IIS в Linux-среде.

## Приёмка

Ротация CSRF сохраняется, служебные ресурсы не запускают SSO, реальный POST
редактора ролей проходит CSRF-проверку, а конфигурация IIS диагностируется.
