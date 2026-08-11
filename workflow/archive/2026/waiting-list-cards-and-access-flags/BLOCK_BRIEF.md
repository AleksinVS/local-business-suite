# Карточки пациента и технические флаги доступа

Цель: выполнить два согласованных пользовательских сценария без обхода доменных
сервисов и журналов.

Write scope:

- `apps/waiting_list/`, `templates/waiting_list/`, `static/src/css/app.css`;
- `apps/accounts/`, `apps/settings_center/`, `templates/settings_center/`;
- миграции, тесты, ADR и документы этого блока.

Проверки: целевые тесты приложений, профили `ui` и `contracts`, полный набор,
Playwright-сценарий редактирования карточки и команда `access_management_e2e`.
