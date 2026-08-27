# Приёмка пакетов 21–24

Дата: 2026-08-26

## Решение

Пакеты 21–24 технически приняты. P0/P1 замечания независимого Luna xhigh-ревью
исправлены. Динамическая иерархия ролей не принята к реализации и остаётся
отдельным решением владельца.

## Проверки

- `make verify-fast TEST_SCOPE='apps/accounts/tests.py::LDAPAuthConfigTests apps/settings_center/tests.py::AccessWorkspaceTests apps/settings_center/tests.py::SettingsCenterUserViewsTests apps/workorders/tests.py::BoardAdminAccessTests'`
  — 80 passed, 18 subtests passed.
- `make verify-fast TEST_SCOPE='apps/accounts/tests.py apps/settings_center/tests.py apps/workorders/tests.py'`
  — 330 passed, 6 deselected, 83 subtests passed.
- `python manage.py access_administration_e2e`
  — OK, тестовые данные удалены.
- `make verify-profile PROFILE=contracts`
  — architecture contracts valid; 52 passed, 55 deselected, 2 subtests passed.
- `python manage.py check` и `git diff --check` — успешно.

Первый запуск contracts-профиля встретил временную блокировку общей SQLite-базы
параллельным тестовым процессом. После освобождения ресурса повторный запуск по
новой гипотезе прошёл полностью; исходный сбой не относился к изменению кода.

## Критерии безопасности

- отсутствие AD principal не создаёт и не стирает identity;
- ручной и автоматический AD-контуры ограничены провайдером AD и аудитом;
- пользователь без роли не получает разделы или неявное участие `customer`;
- копия роли проходит повторную проверку автора, источника, версии и цели под lock;
- копия не получает пользователей, Board ACL или memory-группы;
- защищённые и effectively critical роли копирует только активный superuser;
- старый список не остаётся второй базой отображения.

## Остаточный риск

Статическое UX-ревью охватило маршруты, тексты, HTMX targets, доступность и
адаптивные шаблоны. Постоянный management-command e2e проверяет серверную связку,
но ручная браузерная проверка на реальных размерах данных всё ещё нужна для
пагинации, мобильной прокрутки и поведения выбранного объекта под фильтром.
