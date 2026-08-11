# Базовый просмотр канбана и диагностика SSO

Write scope: политики и селекторы `apps/workorders`, объяснение итогового доступа
в `apps/accounts`, шаблон доски, тесты, ADR и документация IIS SSO.

Read-only scope диагностики: `config/settings.py`, middleware и backend
`apps.accounts`, `docs/deployment/IIS_SSO.md`. Host-specific deployment-файлы
не изменяются без данных целевого хоста.

Проверки: целевые тесты accounts/workorders, профили `ui` и `deployment`, полный
набор, HTTP smoke работающего сервиса.
