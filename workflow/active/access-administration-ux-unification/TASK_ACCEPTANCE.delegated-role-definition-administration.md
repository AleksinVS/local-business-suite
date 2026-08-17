# Приёмка: делегированное редактирование определений ролей

## Решение

PASS.

Определения ролей могут менять активные аутентифицированные superuser,
администраторы Django (`is_staff`) и участники контрактной роли `admin`.
Пользователь с одним `manage_roles`, обычный и неактивный пользователь редактор
не получают.

## Проверенные инварианты

- один predicate используется в навигации, Access Workspace, правом инспекторе,
  отдельной странице, legacy redirect, AI preview/apply и contract service;
- прямой POST и прямой вызов сервиса не обходят предметную проверку;
- signed preview связан с `is_staff`, `is_superuser`, активностью и составом
  ролей актора;
- ошибка чтения role contract закрывает доступ;
- preview, impact, risk confirmation, CAS, атомарная запись и аудит сохранены;
- сквозная команда не использует рабочие role-группы и очищает тестовые данные.

## Проверки

- `make verify-fast TEST_SCOPE='apps/settings_center/tests.py apps/core/tests.py apps/ai/tests/test_views.py'` — `239 passed`, `5 deselected`, `36 subtests`;
- `python manage.py access_administration_e2e` в контейнере — успешно;
- `python manage.py check` в контейнере — успешно;
- `python manage.py validate_architecture_contracts` в контейнере — успешно;
- Playwright Chromium, три сценария редактора роли — `3 passed`;
- `git diff --check` — успешно.

## Остаточная граница

Редактирование существующих ролей принято. Создание новой контрактной роли в UI
не входит в пакет и пока не поддерживается. Для листа ожидания используется
существующая роль «Врач».
